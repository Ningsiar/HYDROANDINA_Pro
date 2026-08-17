# -*- coding: utf-8 -*-
"""
core/pfafstetter.py

Codificación Pfafstetter (Verdin & Verdin, 1999) de subcuencas, sobre
la red de drenaje YA vectorizada de la cuenca (pestaña 1) -- sin
necesitar una grilla de acumulación de flujo recortada aparte: se
reutiliza el mismo grafo no dirigido nodo-a-nodo que ya construye
core.main_channel._construir_grafo() (el que usa la extracción del
perfil del cauce principal), y como estimador del "tamaño" de cada
tributario para elegir los 4 mayores se usa la LONGITUD TOTAL de
cauces aguas arriba de la confluencia -- proxy razonable y monótono
del área de drenaje en una red dendrítica (relación de Hack,
longitud~área^0.6), sin requerir remuestrear una grilla de acumulación
de flujo a esta red en particular.

MÉTODO (Verdin & Verdin, 1999), por nivel de codificación:
  1. Se identifica el "cauce principal" de la (sub)red: el camino de
     mayor longitud acumulada desde el punto de salida -- mismo
     algoritmo que core.main_channel (_camino_mas_largo_desde).
  2. Se identifican los hasta 4 tributarios de MAYOR tamaño que entran
     al cauce principal.
  3. Estos tributarios dividen el cauce principal en hasta 5
     segmentos. Numerando desde la salida (aguas abajo) hacia la
     naciente: los segmentos del cauce principal ("interbasin", área
     que drena directo al cauce principal sin pasar por un tributario
     grande) reciben los dígitos IMPARES 1,3,5,7,9; los tributarios
     reciben los dígitos PARES 2,4,6,8, en el mismo orden aguas
     abajo->arriba en que entran al cauce principal.
  4. Cada tramo lateral MENOR (que no es uno de los tributarios
     seleccionados) hereda el código del segmento interbasin al que
     drena.
  5. (`nivel_max` > 1): se repite el mismo procedimiento DENTRO de
     cada una de las hasta 9 subcuencas de este nivel, sobre su propia
     subred (con su propio punto de salida local), agregando un
     dígito más al código -- p.ej. "24" es el segundo tributario
     grande DENTRO del tributario grande "2".

LIMITACIÓN DOCUMENTADA: se codifican los TRAMOS DE LA RED DE DRENAJE
(un mapa temático de líneas coloreado por código, igual que el orden
de Strahler de la Fase 1), no los POLÍGONOS de cada subcuenca --
delinear el polígono de cada una de las hasta 9^nivel_max subcuencas
requeriría ejecutar un algoritmo de cuenca de aportación por cada
punto de salida tributario (con recorte/remuestreo de una grilla de
flujo por cada uno); se dejó fuera de esta iteración por la misma
razón de tiempo/alcance que otras decisiones ya documentadas en este
plugin (ver p.ej. Co-Kriging en core/areal_precipitation.py).

Depende de qgis.core -- solo se importa dentro de QGIS.
"""
from typing import Dict, Set, Tuple

from qgis.core import QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY

from .main_channel import _construir_grafo, _nodo_mas_cercano, _camino_mas_largo_desde


class PfafstetterError(Exception):
    pass


def _longitud_subarbol(adyacencia, nodo_inicio, nodo_prohibido) -> float:
    """Suma de longitudes de todos los tramos alcanzables desde
    `nodo_inicio` sin pasar por `nodo_prohibido` -- proxy del tamaño de
    la subcuenca aguas arriba de una confluencia."""
    visitados = {nodo_inicio, nodo_prohibido}
    total = 0.0
    pila = [nodo_inicio]
    while pila:
        actual = pila.pop()
        for vecino, longitud_m, _ in adyacencia.get(actual, []):
            if vecino in visitados:
                continue
            visitados.add(vecino)
            total += longitud_m
            pila.append(vecino)
    return total


def _sub_adyacencia(adyacencia, aristas_permitidas: Set[int]):
    """Adyacencia inducida solo por las aristas en `aristas_permitidas`."""
    sub = {}
    for nodo, vecinos in adyacencia.items():
        filtrados = [(v, long_m, idx) for (v, long_m, idx) in vecinos if idx in aristas_permitidas]
        if filtrados:
            sub[nodo] = filtrados
    return sub


def _codificar_subred(adyacencia_completa, aristas_disponibles: Set[int], nodo_raiz,
                       prefijo: str, nivel_actual: int, nivel_max: int,
                       codigos_por_arista: Dict[int, str]) -> None:
    """Codifica UN nivel de Pfafstetter sobre la subred inducida por
    `aristas_disponibles` con punto de salida local `nodo_raiz`, y
    recursa hasta `nivel_max`. Escribe directamente en
    `codigos_por_arista` (índice de arista -> código completo)."""
    if not aristas_disponibles:
        return
    sub_ady = _sub_adyacencia(adyacencia_completa, aristas_disponibles)
    if nodo_raiz not in sub_ady:
        if len(aristas_disponibles) == 1:
            (unica,) = aristas_disponibles
            codigos_por_arista[unica] = prefijo
        return

    camino_nodos, aristas_principales, _ = _camino_mas_largo_desde(sub_ady, nodo_raiz)
    if not aristas_principales:
        return
    aristas_principales_set = set(aristas_principales)

    # Tamaño de cada rama lateral que entra en cada nodo del cauce
    # principal de ESTA subred (excluye el propio cauce principal).
    candidatos = []  # (tamano, posicion_en_camino, idx_arista_raiz, nodo_vecino)
    for i, nodo in enumerate(camino_nodos[:-1]):
        for vecino, longitud_m, idx_arista in sub_ady.get(nodo, []):
            if idx_arista in aristas_principales_set:
                continue
            tamano = longitud_m + _longitud_subarbol(sub_ady, vecino, nodo)
            candidatos.append((tamano, i, idx_arista, vecino))

    candidatos.sort(key=lambda c: -c[0])
    seleccionados = candidatos[:4]
    seleccionados.sort(key=lambda c: (c[1], -c[0]))  # orden aguas abajo -> arriba
    limites = [c[1] for c in seleccionados]

    # 1) segmentos del cauce principal (dígitos impares 1,3,5,7,9)
    for e, idx_arista in enumerate(aristas_principales):
        n_superados = sum(1 for lim in limites if lim <= e)
        codigos_por_arista[idx_arista] = f"{prefijo}{2 * n_superados + 1}"

    # 2) los hasta 4 tributarios seleccionados (dígitos pares 2,4,6,8) --
    #    se recolecta TODA la subred aguas arriba de cada uno (incluida
    #    la arista de la confluencia misma) para poder recursar.
    aristas_de_tributario: Dict[int, Set[int]] = {}
    for k, (tamano, i, idx_arista, vecino) in enumerate(seleccionados):
        codigo = f"{prefijo}{2 * (k + 1)}"
        propias = {idx_arista}
        visitados = {camino_nodos[i], vecino}
        pila = [vecino]
        while pila:
            actual = pila.pop()
            for vec2, _long2, idx2 in sub_ady.get(actual, []):
                if idx2 in propias:
                    continue
                propias.add(idx2)
                if vec2 not in visitados:
                    visitados.add(vec2)
                    pila.append(vec2)
        for idx2 in propias:
            codigos_por_arista[idx2] = codigo
        aristas_de_tributario[idx_arista] = propias

    # 3) tramos laterales MENORES que cuelgan del cauce principal (ni
    #    son el cauce principal ni uno de los tributarios
    #    seleccionados) -- heredan el código del segmento interbasin
    #    en el que entran.
    aristas_ya_codificadas = set(codigos_por_arista.keys())
    for i, nodo in enumerate(camino_nodos[:-1]):
        n_superados = sum(1 for lim in limites if lim <= i)
        codigo_interbasin = f"{prefijo}{2 * n_superados + 1}"
        for vecino, _long_m, idx_arista in sub_ady.get(nodo, []):
            if idx_arista in aristas_principales_set or idx_arista in aristas_ya_codificadas:
                continue
            propias = {idx_arista}
            visitados = {nodo, vecino}
            pila = [vecino]
            while pila:
                actual = pila.pop()
                for vec2, _long2, idx2 in sub_ady.get(actual, []):
                    if idx2 in propias or idx2 in aristas_ya_codificadas:
                        continue
                    propias.add(idx2)
                    if vec2 not in visitados:
                        visitados.add(vec2)
                        pila.append(vec2)
            for idx2 in propias:
                codigos_por_arista[idx2] = codigo_interbasin
            aristas_ya_codificadas |= propias

    # 4) recursión al siguiente nivel
    if nivel_actual >= nivel_max:
        return

    # 4a) segmentos interbasin: la raíz local de cada uno es el nodo del
    #     cauce principal donde EMPIEZA ese segmento (aguas abajo) --
    #     para el segmento "1" coincide con nodo_raiz.
    grupos_interbasin: Dict[str, Set[int]] = {}
    for idx_arista, codigo in codigos_por_arista.items():
        if idx_arista in aristas_disponibles and len(codigo) == len(prefijo) + 1 \
                and codigo.startswith(prefijo) and int(codigo[-1]) % 2 == 1:
            grupos_interbasin.setdefault(codigo, set()).add(idx_arista)

    inicio_por_digito: Dict[int, int] = {}
    for e in range(len(aristas_principales) + 1):
        n_superados = sum(1 for lim in limites if lim <= e)
        digito = 2 * n_superados + 1
        inicio_por_digito.setdefault(digito, e)
    for digito, e_inicio in inicio_por_digito.items():
        codigo = f"{prefijo}{digito}"
        if codigo in grupos_interbasin:
            _codificar_subred(adyacencia_completa, grupos_interbasin[codigo], camino_nodos[e_inicio],
                               codigo, nivel_actual + 1, nivel_max, codigos_por_arista)

    # 4b) tributarios seleccionados: la raíz local es el nodo del cauce
    #     principal PADRE donde se desprende el tributario (su propio
    #     "punto de salida"), NO el primer nodo aguas arriba -- de lo
    #     contrario la búsqueda del cauce principal de la subred podría
    #     "retroceder" hacia el nodo padre a través de la misma arista
    #     de la confluencia y confundir la dirección aguas arriba.
    for k, (tamano, i, idx_arista, vecino) in enumerate(seleccionados):
        codigo = f"{prefijo}{2 * (k + 1)}"
        _codificar_subred(adyacencia_completa, aristas_de_tributario[idx_arista], camino_nodos[i],
                           codigo, nivel_actual + 1, nivel_max, codigos_por_arista)


def codificar_pfafstetter(red_drenaje_layer, punto_salida_xy: Tuple[float, float],
                           nivel_max: int = 1, tol_nodo_m: float = 1.0):
    """Codifica cada tramo de `red_drenaje_layer` (capa de líneas ya
    recortada a la cuenca) con su código Pfafstetter, hasta `nivel_max`
    dígitos. Devuelve (codigos_por_arista, geometrias_por_arista) --
    ambos indexados por el mismo índice de arista que usa
    core.main_channel._construir_grafo()."""
    if nivel_max < 1:
        raise PfafstetterError("nivel_max debe ser al menos 1.")
    adyacencia, geometrias = _construir_grafo(red_drenaje_layer, tol_nodo_m)
    if not adyacencia:
        raise PfafstetterError("la red de drenaje no tiene tramos válidos para codificar.")

    nodo_salida = _nodo_mas_cercano(adyacencia, punto_salida_xy)
    if nodo_salida is None:
        raise PfafstetterError("no se encontró ningún nodo de la red cerca del punto de salida.")

    todas_las_aristas = set(geometrias.keys())
    codigos_por_arista: Dict[int, str] = {}
    _codificar_subred(adyacencia, todas_las_aristas, nodo_salida, "", 1, nivel_max, codigos_por_arista)

    faltantes = todas_las_aristas - set(codigos_por_arista.keys())
    if faltantes:
        raise PfafstetterError(
            f"{len(faltantes)} tramo(s) de la red no recibieron código Pfafstetter -- probablemente "
            "la red tiene más de una componente desconectada (varios puntos de salida); revise que "
            "toda la red de drenaje esté conectada a un único punto de salida."
        )
    return codigos_por_arista, geometrias


def generar_capa_pfafstetter(red_drenaje_layer, punto_salida_xy: Tuple[float, float],
                              nivel_max: int = 1, tol_nodo_m: float = 1.0) -> QgsVectorLayer:
    """Capa de líneas (memoria) -- copia de `red_drenaje_layer` con un
    campo de texto "pfafstetter" agregado, mismo patrón que
    core.mapas_tematicos.calcular_orden_strahler_en_capa()."""
    codigos_por_arista, geometrias = codificar_pfafstetter(
        red_drenaje_layer, punto_salida_xy, nivel_max, tol_nodo_m)

    crs_id = red_drenaje_layer.crs().authid()
    capa_salida = QgsVectorLayer(f"LineString?crs={crs_id}&field=pfafstetter:string(20)",
                                  "Codificación Pfafstetter", "memory")
    prov_salida = capa_salida.dataProvider()
    nuevas_feats = []
    for idx_arista, puntos in geometrias.items():
        f = QgsFeature()
        f.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(p) for p in puntos]))
        f.setAttributes([codigos_por_arista.get(idx_arista, "")])
        nuevas_feats.append(f)
    prov_salida.addFeatures(nuevas_feats)
    capa_salida.updateExtents()
    return capa_salida
