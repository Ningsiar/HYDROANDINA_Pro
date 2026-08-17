# -*- coding: utf-8 -*-
"""
core/areal_precipitation.py

Cálculo de la precipitación areal (promedio espacial sobre la cuenca
delimitada) a partir de valores puntuales de estaciones, por varios
métodos de interpolación/ponderación espacial.

MÉTODOS IMPLEMENTADOS:
  - Thiessen (polígonos de Voronoi): pondera cada estación por el área
    de su polígono de influencia dentro de la cuenca.
  - IDW (Inverse Distance Weighting): interpola sobre una grilla dentro
    de la cuenca y promedia.
  - RBF (Radial Basis Function, interpolador exacto tipo "thin plate
    spline" simplificado): resuelve un sistema lineal con la matriz de
    distancias entre estaciones.
  - Kriging Ordinario: con un variograma esférico o exponencial ajustado
    por mínimos cuadrados a partir del semivariograma experimental de
    las propias estaciones (requiere al menos ~6-8 estaciones para un
    ajuste razonable; con menos estaciones el variograma es poco
    confiable — se advierte en el resultado).

SERIE DE MÁXIMOS ANUALES AREAL PONDERADA (Pestaña 5, "1c. Múltiples
Estaciones"): distinto de los métodos de arriba, que arealizan UN
evento (todas las estaciones midieron la misma tormenta). Aquí el
problema es otro: se tienen N series de máximos anuales INDEPENDIENTES
(el máximo anual de la estación A y el de la B casi nunca son la misma
tormenta), y se quiere UNA sola serie representativa de la cuenca para
el análisis de frecuencia. La práctica estándar (y la que se
implementa aquí, ver serie_anual_ponderada()) es ponderar los DATOS
año por año -- no promediar los valores de diseño P24(Tr) ya ajustados
por estación, que sobreestimaría el extremo areal (es muy improbable
que todas las estaciones tengan su máximo anual el mismo día; ver nota
de Factor de Reducción Areal más abajo). La serie resultante se ajusta
después con el mismo motor de 9 distribuciones de siempre
(core/frequency_analysis.py) -- sin duplicar nada.

LIMITACIÓN DOCUMENTADA: no se aplica ningún Factor de Reducción Areal
(ARF, p.ej. NRCS TR-55 o el Flood Studies Report del Reino Unido) al
resultado. Esas curvas están calibradas con datos de EE.UU./RU;
aplicarlas a cuencas andinas sin una fuente regional verificada sería
imponer una corrección de origen incierto. Se deja como extensión
futura si se cuenta con una curva ARF calibrada localmente.

TRANSPARENCIA:
  - Co-Kriging (con una variable auxiliar, p.ej. elevación) NO se
    implementa: requiere modelar la correlación cruzada entre dos
    variables regionalizadas de forma robusta, y no se pudo verificar
    una implementación con la confianza necesaria en este entorno sin
    poder probarla contra un caso de referencia conocido. Como
    alternativa práctica, considere una regresión con la elevación como
    covariable (residual kriging), que puede añadirse en una iteración
    futura si se necesita.
  - GPI y LPI (Gradient/Local Plane Interpolation) tampoco se
    implementan aquí por la misma razón de falta de una fuente
    verificable con certeza suficiente para un cálculo de diseño.
"""
import math
import os
import tempfile
from typing import Dict, List, Optional, Tuple

import numpy as np

try:
    from osgeo import gdal
    gdal.UseExceptions()
except ImportError:
    gdal = None


class ArealPrecipitationError(Exception):
    pass


def _grilla_dentro_de_poligono(vertices_poligono: List[Tuple[float, float]], resolucion_m: float):
    """Genera una grilla regular de puntos dentro de un polígono simple
    (lista de vértices [(x,y),...]), usando el algoritmo de
    punto-en-polígono por cruce de rayos (ray casting)."""
    xs = [p[0] for p in vertices_poligono]
    ys = [p[1] for p in vertices_poligono]
    x_min, x_max, y_min, y_max = min(xs), max(xs), min(ys), max(ys)

    def punto_en_poligono(px, py):
        dentro = False
        n = len(vertices_poligono)
        j = n - 1
        for i in range(n):
            xi, yi = vertices_poligono[i]
            xj, yj = vertices_poligono[j]
            if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi + 1e-15) + xi):
                dentro = not dentro
            j = i
        return dentro

    puntos = []
    x = x_min
    while x <= x_max:
        y = y_min
        while y <= y_max:
            if punto_en_poligono(x, y):
                puntos.append((x, y))
            y += resolucion_m
        x += resolucion_m
    if not puntos:
        raise ArealPrecipitationError(
            "La grilla generada no tiene puntos dentro del polígono; reduzca la resolución de la grilla."
        )
    return puntos


def precipitacion_thiessen(valores_estaciones: Dict[str, float], areas_thiessen_m2: Dict[str, float]) -> dict:
    """
    areas_thiessen_m2: área (m2) del polígono de Thiessen de cada
    estación YA RECORTADO a la cuenca (calculado previamente en QGIS,
    p.ej. con native:voronoipolygons + intersección con la cuenca).
    """
    nombres = list(valores_estaciones.keys())
    area_total = sum(areas_thiessen_m2.get(n, 0.0) for n in nombres)
    if area_total <= 0:
        raise ArealPrecipitationError("El área total de los polígonos de Thiessen dentro de la cuenca es cero.")
    p_areal = sum(valores_estaciones[n] * areas_thiessen_m2.get(n, 0.0) for n in nombres) / area_total
    pesos = {n: round(areas_thiessen_m2.get(n, 0.0) / area_total, 4) for n in nombres}
    return {"precipitacion_areal_mm": round(p_areal, 2), "pesos_thiessen": pesos}


def precipitacion_idw(valores_estaciones: Dict[str, float], coordenadas: Dict[str, Tuple[float, float]],
                       vertices_cuenca: List[Tuple[float, float]], potencia: float = 2.0,
                       resolucion_grilla_m: float = 200.0) -> dict:
    nombres = list(valores_estaciones.keys())
    if len(nombres) < 2:
        raise ArealPrecipitationError("Se requieren al menos 2 estaciones para IDW.")
    puntos_grilla = _grilla_dentro_de_poligono(vertices_cuenca, resolucion_grilla_m)

    valores_grilla = []
    for gx, gy in puntos_grilla:
        pesos, valores = [], []
        for n in nombres:
            x, y = coordenadas[n]
            d = max(math.hypot(x - gx, y - gy), 1e-3)
            pesos.append(1.0 / (d ** potencia))
            valores.append(valores_estaciones[n])
        valores_grilla.append(np.average(valores, weights=pesos))

    return {
        "precipitacion_areal_mm": round(float(np.mean(valores_grilla)), 2),
        "n_puntos_grilla": len(puntos_grilla),
    }


def precipitacion_rbf(valores_estaciones: Dict[str, float], coordenadas: Dict[str, Tuple[float, float]],
                       vertices_cuenca: List[Tuple[float, float]], resolucion_grilla_m: float = 200.0) -> dict:
    """Interpolador RBF exacto (thin-plate spline: phi(r) = r^2 * ln(r)),
    resolviendo el sistema lineal de pesos + término polinómico lineal
    de deriva."""
    nombres = list(valores_estaciones.keys())
    n = len(nombres)
    if n < 4:
        raise ArealPrecipitationError("Se requieren al menos 4 estaciones para un ajuste RBF razonable.")
    puntos = np.array([coordenadas[e] for e in nombres])
    valores = np.array([valores_estaciones[e] for e in nombres])

    def phi(r):
        return np.where(r > 0, r ** 2 * np.log(np.where(r > 0, r, 1)), 0.0)

    dist = np.sqrt(((puntos[:, None, :] - puntos[None, :, :]) ** 2).sum(axis=2))
    M = phi(dist)
    P = np.column_stack([np.ones(n), puntos])
    A_sistema = np.block([[M, P], [P.T, np.zeros((3, 3))]])
    b_sistema = np.concatenate([valores, np.zeros(3)])
    coeficientes = np.linalg.lstsq(A_sistema, b_sistema, rcond=None)[0]
    pesos_rbf, coef_poly = coeficientes[:n], coeficientes[n:]

    puntos_grilla = _grilla_dentro_de_poligono(vertices_cuenca, resolucion_grilla_m)
    valores_grilla = []
    for gx, gy in puntos_grilla:
        d = np.sqrt(((puntos - np.array([gx, gy])) ** 2).sum(axis=1))
        valor = np.sum(pesos_rbf * phi(d)) + coef_poly[0] + coef_poly[1] * gx + coef_poly[2] * gy
        valores_grilla.append(valor)

    return {
        "precipitacion_areal_mm": round(float(np.mean(valores_grilla)), 2),
        "n_puntos_grilla": len(puntos_grilla),
    }


def _semivariograma_experimental(puntos, valores, n_lags=10):
    n = len(valores)
    pares = [(i, j) for i in range(n) for j in range(i + 1, n)]
    distancias = np.array([math.hypot(*(puntos[i] - puntos[j])) for i, j in pares])
    semivar = np.array([0.5 * (valores[i] - valores[j]) ** 2 for i, j in pares])
    d_max = distancias.max()
    bordes = np.linspace(0, d_max, n_lags + 1)
    lags_centro, semivar_promedio = [], []
    for k in range(n_lags):
        mascara = (distancias >= bordes[k]) & (distancias < bordes[k + 1])
        if mascara.sum() > 0:
            lags_centro.append((bordes[k] + bordes[k + 1]) / 2.0)
            semivar_promedio.append(semivar[mascara].mean())
    return np.array(lags_centro), np.array(semivar_promedio)


def _variograma_esferico(h, nugget, sill, rango):
    h = np.asarray(h, dtype=float)
    gamma = np.where(
        h <= rango,
        nugget + (sill - nugget) * (1.5 * (h / rango) - 0.5 * (h / rango) ** 3),
        sill,
    )
    return np.where(h == 0, 0.0, gamma)


def precipitacion_kriging_ordinario(valores_estaciones: Dict[str, float], coordenadas: Dict[str, Tuple[float, float]],
                                     vertices_cuenca: List[Tuple[float, float]],
                                     resolucion_grilla_m: float = 200.0) -> dict:
    nombres = list(valores_estaciones.keys())
    n = len(nombres)
    if n < 6:
        raise ArealPrecipitationError(
            "Se recomiendan al menos 6 estaciones para ajustar un variograma de Kriging razonable; "
            f"se proporcionaron {n}. Considere IDW o Thiessen con pocas estaciones."
        )
    puntos = np.array([coordenadas[e] for e in nombres])
    valores = np.array([valores_estaciones[e] for e in nombres])

    lags, semivar = _semivariograma_experimental(puntos, valores)
    if len(lags) < 3:
        raise ArealPrecipitationError("No se pudo construir un semivariograma experimental con suficientes puntos.")

    # Ajuste simple por mínimos cuadrados del modelo esférico (nugget, sill, rango)
    from scipy.optimize import curve_fit
    try:
        sill_inicial = float(np.var(valores))
        rango_inicial = float(lags.max() / 2.0)
        parametros, _ = curve_fit(
            _variograma_esferico, lags, semivar,
            p0=[0.0, sill_inicial, rango_inicial],
            bounds=([0, 0, 1e-3], [sill_inicial * 2 + 1e-6, sill_inicial * 3 + 1e-6, lags.max() * 3]),
            maxfev=5000,
        )
        nugget, sill, rango = parametros
    except Exception:
        # respaldo: variograma esférico "razonable" sin ajuste optimizado
        nugget, sill, rango = 0.0, float(np.var(valores)), float(lags.max())

    # Sistema de Kriging Ordinario
    dist_estaciones = np.sqrt(((puntos[:, None, :] - puntos[None, :, :]) ** 2).sum(axis=2))
    Gamma = _variograma_esferico(dist_estaciones, nugget, sill, rango)
    A = np.ones((n + 1, n + 1))
    A[:n, :n] = Gamma
    A[n, n] = 0.0

    puntos_grilla = _grilla_dentro_de_poligono(vertices_cuenca, resolucion_grilla_m)
    valores_grilla = []
    for gx, gy in puntos_grilla:
        d_grilla = np.sqrt(((puntos - np.array([gx, gy])) ** 2).sum(axis=1))
        b = np.append(_variograma_esferico(d_grilla, nugget, sill, rango), 1.0)
        try:
            pesos_lagrange = np.linalg.solve(A, b)
        except np.linalg.LinAlgError:
            continue
        pesos = pesos_lagrange[:n]
        valores_grilla.append(float(np.sum(pesos * valores)))

    if not valores_grilla:
        raise ArealPrecipitationError("El sistema de Kriging no pudo resolverse para ningún punto de la grilla (matriz singular).")

    return {
        "precipitacion_areal_mm": round(float(np.mean(valores_grilla)), 2),
        "n_puntos_grilla": len(valores_grilla),
        "variograma_ajustado": {"nugget": round(float(nugget), 3), "sill": round(float(sill), 3),
                                  "rango_m": round(float(rango), 1)},
        "nota": ("Variograma esférico ajustado por mínimos cuadrados al semivariograma experimental de las "
                  "propias estaciones; con pocas estaciones (<10-15) este ajuste es poco robusto — use con "
                  "cautela y compare contra IDW/Thiessen."),
    }


def generar_raster_precipitacion_idw(valores_estaciones: Dict[str, float],
                                      coordenadas: Dict[str, Tuple[float, float]],
                                      extent: Tuple[float, float, float, float],
                                      resolucion_m: float, crs_wkt: str,
                                      potencia: float = 2.0,
                                      destino_tif: Optional[str] = None) -> str:
    """Genera un GeoTIFF con la precipitación interpolada por IDW sobre
    una grilla RECTANGULAR REGULAR completa (a diferencia de
    precipitacion_idw(), que solo promedia una nube de puntos dentro
    del polígono de la cuenca y no produce un ráster) -- misma fórmula
    de pesos (1/d^potencia) ya usada y verificada en precipitacion_idw().
    Apto para estilizar como mapa temático (core/map_styling.py) y para
    extraer isoyetas por contorno (gdal:contour).

    `extent`: (xmin, ymin, xmax, ymax) en el mismo CRS que `coordenadas`
    (normalmente el de la cuenca activa). `crs_wkt`: WKT del CRS de
    salida (p.ej. capa_cuenca.crs().toWkt())."""
    if gdal is None:
        raise ArealPrecipitationError(
            "GDAL no está disponible en este entorno; no se puede generar el ráster de precipitación.")
    nombres = list(valores_estaciones.keys())
    if len(nombres) < 2:
        raise ArealPrecipitationError("Se requieren al menos 2 estaciones para generar el ráster IDW.")

    xmin, ymin, xmax, ymax = extent
    if xmax <= xmin or ymax <= ymin:
        raise ArealPrecipitationError("La extensión indicada (extent) no es válida (xmax<=xmin o ymax<=ymin).")
    ancho = max(int(round((xmax - xmin) / resolucion_m)), 1)
    alto = max(int(round((ymax - ymin) / resolucion_m)), 1)

    xs = xmin + (np.arange(ancho) + 0.5) * resolucion_m
    ys = ymax - (np.arange(alto) + 0.5) * resolucion_m  # fila 0 = norte (arriba), como un ráster estándar
    grid_x, grid_y = np.meshgrid(xs, ys)  # shape (alto, ancho)

    suma_ponderada = np.zeros((alto, ancho), dtype=np.float64)
    suma_pesos = np.zeros((alto, ancho), dtype=np.float64)
    for nombre in nombres:
        ex, ey = coordenadas[nombre]
        d = np.sqrt((grid_x - ex) ** 2 + (grid_y - ey) ** 2)
        d = np.maximum(d, 1e-3)
        peso = 1.0 / (d ** potencia)
        suma_ponderada += peso * valores_estaciones[nombre]
        suma_pesos += peso
    raster_idw = (suma_ponderada / suma_pesos).astype(np.float32)

    if destino_tif is None:
        destino_tif = os.path.join(
            tempfile.mkdtemp(prefix="hydroandes_precip_idw_"), "precipitacion_idw.tif")

    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(destino_tif, ancho, alto, 1, gdal.GDT_Float32)
    gt = (xmin, resolucion_m, 0.0, ymax, 0.0, -resolucion_m)
    ds.SetGeoTransform(gt)
    ds.SetProjection(crs_wkt)
    banda = ds.GetRasterBand(1)
    banda.WriteArray(raster_idw)
    banda.FlushCache()
    ds = None

    return destino_tif


# ======================================================================
# Serie de máximos anuales AREAL PONDERADA multi-estación -- ver nota
# en el docstring del módulo. Los pesos de Thiessen (que requieren
# generar el polígono de Voronoi recortado a la cuenca en QGIS) se
# calculan aparte, en core/mapas_tematicos.py::calcular_pesos_thiessen_estaciones();
# aquí solo IDW (puro Python/numpy) y la combinación año-por-año, que
# es agnóstica de cómo se obtuvieron los pesos.
# ======================================================================
def calcular_pesos_idw_estaciones(coordenadas: Dict[str, Tuple[float, float]],
                                   punto_referencia: Tuple[float, float],
                                   potencia: float = 2.0) -> Dict[str, float]:
    """Pesos IDW (inverso a la distancia) de cada estación respecto a
    `punto_referencia` (típicamente el centroide de la cuenca),
    normalizados a que sumen 1. Alternativa más simple que Thiessen
    cuando no se cuenta con (o no se quiere generar) el polígono de
    Voronoi recortado a la cuenca."""
    nombres = list(coordenadas.keys())
    if len(nombres) < 2:
        raise ArealPrecipitationError("Se requieren al menos 2 estaciones para calcular pesos IDW.")
    rx, ry = punto_referencia
    pesos_brutos = {}
    for nombre in nombres:
        x, y = coordenadas[nombre]
        d = max(math.hypot(x - rx, y - ry), 1e-3)
        pesos_brutos[nombre] = 1.0 / (d ** potencia)
    suma = sum(pesos_brutos.values())
    return {nombre: p / suma for nombre, p in pesos_brutos.items()}


def centroide_poligono(vertices: List[Tuple[float, float]]) -> Tuple[float, float]:
    """Centroide (promedio simple de vértices) de un polígono simple --
    suficiente como punto de referencia para IDW (no hace falta el
    centroide exacto ponderado por área para este propósito)."""
    if not vertices:
        raise ArealPrecipitationError("la lista de vértices del polígono está vacía.")
    xs = [v[0] for v in vertices]
    ys = [v[1] for v in vertices]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def serie_anual_ponderada(datos_por_estacion: Dict[str, Dict[int, float]],
                           pesos: Dict[str, float], minimo_estaciones: int = 2) -> dict:
    """Combina las series de máximos anuales de varias estaciones en
    UNA sola serie "areal ponderada", año por año: para cada año en el
    que reportan al menos `minimo_estaciones` estaciones, se pondera
    SOLO entre las que reportan ese año, RENORMALIZANDO sus pesos para
    que sumen 1 entre ellas -- así un año con huecos en algunas
    estaciones no queda ni excluido de más ni sesgado hacia cero por
    los pesos "faltantes". Los años con menos de `minimo_estaciones`
    estaciones se omiten de la serie resultante.

    datos_por_estacion: {nombre_estación: {año: valor_mm, ...}, ...}
        (con huecos: no todas las estaciones necesitan tener el mismo
        conjunto de años).
    pesos: {nombre_estación: peso}, deben sumar ~1 sobre TODAS las
        estaciones de `datos_por_estacion` (los que devuelven
        calcular_pesos_idw_estaciones() o los pesos de Thiessen
        calculados en QGIS).
    """
    nombres_pesos = set(pesos.keys())
    nombres_datos = set(datos_por_estacion.keys())
    if nombres_pesos != nombres_datos:
        raise ArealPrecipitationError(
            f"las estaciones con pesos ({sorted(nombres_pesos)}) no coinciden con las estaciones "
            f"con datos ({sorted(nombres_datos)}).")
    if minimo_estaciones < 2:
        raise ArealPrecipitationError("minimo_estaciones debe ser al menos 2.")

    todos_los_anios = sorted({anio for serie in datos_por_estacion.values() for anio in serie.keys()})
    anios_incluidos: List[int] = []
    valores_ponderados: List[float] = []
    detalle_por_anio: Dict[int, dict] = {}
    for anio in todos_los_anios:
        estaciones_reportando = sorted(n for n in nombres_datos if anio in datos_por_estacion[n])
        if len(estaciones_reportando) < minimo_estaciones:
            continue
        peso_total_reportando = sum(pesos[n] for n in estaciones_reportando)
        if peso_total_reportando <= 0:
            continue
        valor = sum(pesos[n] / peso_total_reportando * datos_por_estacion[n][anio]
                    for n in estaciones_reportando)
        anios_incluidos.append(anio)
        valores_ponderados.append(round(valor, 3))
        detalle_por_anio[anio] = {
            "estaciones": estaciones_reportando,
            "n_estaciones": len(estaciones_reportando),
            "pesos_renormalizados": {n: round(pesos[n] / peso_total_reportando, 4)
                                      for n in estaciones_reportando},
        }

    if not anios_incluidos:
        raise ArealPrecipitationError(
            f"ningún año tiene al menos {minimo_estaciones} estación(es) reportando -- no se puede "
            "construir la serie areal ponderada; reduzca el mínimo de estaciones o revise los datos.")

    return {
        "anios": anios_incluidos, "valores_mm": valores_ponderados,
        "n_anios": len(anios_incluidos), "detalle_por_anio": detalle_por_anio,
        "anios_totales_disponibles": len(todos_los_anios),
        "anios_excluidos_por_pocas_estaciones": len(todos_los_anios) - len(anios_incluidos),
    }
