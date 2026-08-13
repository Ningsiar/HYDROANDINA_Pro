# -*- coding: utf-8 -*-
"""
core/main_channel.py

Identifica automáticamente el "cauce principal" dentro de la red de
drenaje ya vectorizada (pestaña 1) y muestrea el MDE a lo largo de él,
para alimentar core.morphometry.grupo3_cauce_principal() con un perfil
longitudinal REAL en vez de la aproximación cruda Se = H/Lc que se usaba
antes en la pestaña 4 (ver nota de corrección en plugin_dialog.py,
_on_calcular_tc).

MÉTODO (documentado, sin dependencias externas a QGIS/numpy):
  1. La red de drenaje recortada a la cuenca (native:clip, ya generada
     en la pestaña 1) es, para una cuenca con un único punto de salida,
     topológicamente un ÁRBOL (sin bucles): cada tramo tiene un extremo
     aguas abajo y uno aguas arriba. Se construye un grafo no dirigido
     nodo-a-nodo a partir de los vértices extremos de cada tramo
     (redondeados a una tolerancia de snapping para fusionar nodos
     coincidentes producidos por r.to.vect).
  2. Se ubica el nodo del grafo más cercano al punto de salida (break
     point ya ajustado al cauce).
  3. "Cauce principal" se define, como es estándar cuando no se cuenta
     con un atributo de orden de Strahler ya calculado por tramo, como
     el camino de MAYOR LONGITUD ACUMULADA desde el punto de salida
     hasta cualquier nodo terminal aguas arriba (equivalente a la
     definición operativa usada por HEC-GeoHMS/ArcHydro para "longest
     flow path"). Se resuelve con una búsqueda en anchura (BFS) que
     acumula distancia por tramo, ya que el grafo es un árbol (no hay
     ciclos que compliquen encontrar el camino más largo).
  4. Se concatena la geometría de los tramos del camino encontrado y se
     muestrea el MDE cada `paso_muestreo_m` metros a lo largo de ella.
"""
import math
from typing import List, Tuple

import numpy as np
from qgis.core import QgsPointXY, QgsRaster


class ExtraccionCauceError(Exception):
    pass


def _nodo_key(pt, tol=1.0):
    """Redondea una coordenada a una rejilla de tolerancia `tol` metros,
    para fusionar nodos que deberían coincidir pero difieren por error
    numérico de la vectorización (r.to.vect)."""
    return (round(pt.x() / tol) * tol, round(pt.y() / tol) * tol)


def _construir_grafo(red_drenaje_layer, tol_nodo_m: float = 1.0):
    """Devuelve (adyacencia, geometrias_por_arista) donde adyacencia es
    dict nodo -> list[(nodo_vecino, longitud_m, indice_arista)]."""
    adyacencia = {}
    geometrias = {}
    idx = 0
    for feat in red_drenaje_layer.getFeatures():
        geom = feat.geometry()
        if geom is None or geom.isEmpty():
            continue
        # Soporta tanto LineString como MultiLineString (toma cada parte)
        partes = geom.asMultiPolyline() if geom.isMultipart() else [geom.asPolyline()]
        for parte in partes:
            if len(parte) < 2:
                continue
            p_ini, p_fin = QgsPointXY(parte[0]), QgsPointXY(parte[-1])
            longitud_m = sum(
                math.hypot(parte[i + 1].x() - parte[i].x(), parte[i + 1].y() - parte[i].y())
                for i in range(len(parte) - 1)
            )
            n_ini, n_fin = _nodo_key(p_ini, tol_nodo_m), _nodo_key(p_fin, tol_nodo_m)
            geometrias[idx] = list(parte)
            adyacencia.setdefault(n_ini, []).append((n_fin, longitud_m, idx))
            adyacencia.setdefault(n_fin, []).append((n_ini, longitud_m, idx))
            idx += 1
    return adyacencia, geometrias


def _nodo_mas_cercano(adyacencia, punto_xy: Tuple[float, float]):
    x0, y0 = punto_xy
    mejor, mejor_d2 = None, float("inf")
    for nodo in adyacencia:
        d2 = (nodo[0] - x0) ** 2 + (nodo[1] - y0) ** 2
        if d2 < mejor_d2:
            mejor, mejor_d2 = nodo, d2
    return mejor


def _camino_mas_largo_desde(adyacencia, nodo_origen):
    """BFS/DFS iterativo sobre un árbol: devuelve la lista ordenada de
    (nodo, indice_arista_usada) del camino de mayor longitud acumulada
    desde nodo_origen hasta el nodo terminal más lejano."""
    visitados = {nodo_origen}
    distancia_acum = {nodo_origen: 0.0}
    padre = {}  # nodo -> (nodo_padre, indice_arista)
    pila = [nodo_origen]
    nodo_mas_lejano, dist_max = nodo_origen, 0.0

    while pila:
        actual = pila.pop()
        for vecino, longitud_m, idx_arista in adyacencia.get(actual, []):
            if vecino in visitados:
                continue
            visitados.add(vecino)
            distancia_acum[vecino] = distancia_acum[actual] + longitud_m
            padre[vecino] = (actual, idx_arista)
            if distancia_acum[vecino] > dist_max:
                dist_max, nodo_mas_lejano = distancia_acum[vecino], vecino
            pila.append(vecino)

    # Reconstruir camino origen -> nodo_mas_lejano
    camino_nodos = [nodo_mas_lejano]
    aristas = []
    n = nodo_mas_lejano
    while n != nodo_origen:
        p, idx_arista = padre[n]
        aristas.append(idx_arista)
        camino_nodos.append(p)
        n = p
    camino_nodos.reverse()
    aristas.reverse()
    return camino_nodos, aristas, dist_max


def extraer_perfil_cauce_principal(red_drenaje_layer, dem_layer, punto_salida_xy: Tuple[float, float],
                                    paso_muestreo_m: float = 30.0, tol_nodo_m: float = 1.0):
    """
    Devuelve un dict con 'distancias_m' y 'elevaciones_m' (np.ndarray,
    ordenados desde el punto de salida hacia la naciente) y 'lc_km' (la
    longitud real del cauce principal encontrado, en km), listos para
    pasar a core.morphometry.grupo3_cauce_principal().

    red_drenaje_layer: capa vectorial de líneas ya recortada a la cuenca
        (la que genera delineation.extraer_y_recortar_red()).
    dem_layer: QgsRasterLayer del MDE (en la misma proyección UTM que la
        red de drenaje).
    punto_salida_xy: (x, y) del punto de salida YA AJUSTADO al cauce, en
        el mismo CRS que red_drenaje_layer.
    """
    adyacencia, geometrias = _construir_grafo(red_drenaje_layer, tol_nodo_m)
    if not adyacencia:
        raise ExtraccionCauceError(
            "La red de drenaje no tiene tramos válidos para construir el grafo del cauce."
        )

    nodo_salida = _nodo_mas_cercano(adyacencia, punto_salida_xy)
    if nodo_salida is None:
        raise ExtraccionCauceError("No se encontró ningún nodo de la red cerca del punto de salida.")

    camino_nodos, aristas, longitud_total_m = _camino_mas_largo_desde(adyacencia, nodo_salida)
    if not aristas:
        raise ExtraccionCauceError(
            "El camino del cauce principal quedó vacío; revise que la red de drenaje "
            "recortada a la cuenca tenga más de un tramo."
        )

    # Concatenar las polilíneas de las aristas del camino, en el orden
    # correcto (origen -> naciente), respetando la orientación de cada
    # tramo según por cuál extremo se entra a él.
    puntos_concatenados: List[QgsPointXY] = []
    nodo_actual = nodo_salida
    for idx_arista, nodo_siguiente in zip(aristas, camino_nodos[1:]):
        parte = geometrias[idx_arista]
        n_ini = _nodo_key(QgsPointXY(parte[0]), tol_nodo_m)
        if n_ini == nodo_actual:
            secuencia = parte
        else:
            secuencia = list(reversed(parte))
        if puntos_concatenados and puntos_concatenados[-1] == QgsPointXY(secuencia[0]):
            secuencia = secuencia[1:]
        puntos_concatenados.extend(QgsPointXY(p) for p in secuencia)
        nodo_actual = nodo_siguiente

    if len(puntos_concatenados) < 2:
        raise ExtraccionCauceError("El cauce principal reconstruido tiene menos de 2 vértices.")

    # Muestreo del MDE cada paso_muestreo_m a lo largo del camino concatenado
    distancias_acum = [0.0]
    for i in range(1, len(puntos_concatenados)):
        d = puntos_concatenados[i].distance(puntos_concatenados[i - 1])
        distancias_acum.append(distancias_acum[-1] + d)
    longitud_real_m = distancias_acum[-1]
    if longitud_real_m <= 0:
        raise ExtraccionCauceError("La longitud del cauce principal reconstruido es cero.")

    n_muestras = max(int(longitud_real_m / paso_muestreo_m), 10)
    distancias_muestreo = np.linspace(0.0, longitud_real_m, n_muestras + 1)

    xs = [p.x() for p in puntos_concatenados]
    ys = [p.y() for p in puntos_concatenados]
    x_muestreo = np.interp(distancias_muestreo, distancias_acum, xs)
    y_muestreo = np.interp(distancias_muestreo, distancias_acum, ys)

    provider = dem_layer.dataProvider()
    elevaciones = []
    for x, y in zip(x_muestreo, y_muestreo):
        resultado = provider.identify(QgsPointXY(float(x), float(y)), QgsRaster.IdentifyFormatValue)
        valor = None
        if resultado.isValid():
            valores = resultado.results()
            if valores:
                valor = list(valores.values())[0]
        elevaciones.append(float(valor) if valor is not None else np.nan)

    elevaciones = np.array(elevaciones, dtype=float)
    # Punto de salida = distancia 0 (aguas abajo); si el orden quedó
    # invertido (elevación en el extremo 0 mayor que en el extremo final),
    # se voltea para que el perfil vaya siempre de aguas abajo a aguas arriba.
    validos = ~np.isnan(elevaciones)
    if validos.sum() >= 2 and elevaciones[validos][0] > elevaciones[validos][-1]:
        distancias_muestreo = distancias_muestreo[::-1].copy()
        distancias_muestreo = distancias_muestreo.max() - distancias_muestreo
        elevaciones = elevaciones[::-1].copy()

    return {
        "distancias_m": distancias_muestreo,
        "elevaciones_m": elevaciones,
        "lc_km": longitud_real_m / 1000.0,
    }
