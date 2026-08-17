# -*- coding: utf-8 -*-
"""
core/mapas_tematicos.py

Orquestación de las capas específicas de la Pestaña "Mapas Temáticos"
que NO están ya calculadas por otra pestaña -- hillshade, curvas de
nivel, y orden de Strahler escrito como campo en la red de drenaje
(el algoritmo `morphometry.strahler_order()` ya existía pero no
estaba conectado a ninguna capa real de la interfaz). El resto de
mapas temáticos (CN, HSG, LULC, calado/velocidad SWE2D, etc.) reutiliza
directamente las capas que ya generan sus propias pestañas -- solo se
estilizan con core/map_styling.py, sin pasar por este módulo.

Depende de qgis.core/processing -- solo se importa dentro de QGIS.
"""
from typing import Dict, Tuple

from qgis.core import QgsVectorLayer, QgsFeature, QgsRasterLayer, QgsPointXY, QgsGeometry

from .qgis_layer_utils import obtener_capa
from . import morphometry


class MapasTematicosError(Exception):
    pass


def generar_hillshade(dem_path: str, context, feedback, azimut: float = 315.0,
                       altitud: float = 45.0):
    """Sombreado de relieve (gdal:hillshade) del DEM ya recortado a la
    cuenca (self.dem_clip_path) -- devuelve la capa ráster resultante."""
    import processing
    resultado = processing.run(
        "gdal:hillshade",
        {"INPUT": dem_path, "BAND": 1, "Z_FACTOR": 1.0, "SCALE": 1.0,
         "AZIMUTH": azimut, "ALTITUDE": altitud, "OUTPUT": "TEMPORARY_OUTPUT"},
        context=context, feedback=feedback, is_child_algorithm=True,
    )
    return obtener_capa(resultado.get("OUTPUT"), context, es_raster=True, nombre="Hillshade")


def generar_curvas_nivel(dem_path: str, intervalo_m: float, context, feedback):
    """Curvas de nivel (gdal:contour) del DEM ya recortado, cada
    `intervalo_m` metros -- devuelve la capa vectorial de líneas
    resultante (campo "ELEV" con la cota de cada curva)."""
    import processing
    if intervalo_m <= 0:
        raise MapasTematicosError("el intervalo de curvas de nivel debe ser mayor que 0.")
    resultado = processing.run(
        "gdal:contour",
        {"INPUT": dem_path, "BAND": 1, "INTERVAL": intervalo_m, "FIELD_NAME": "ELEV",
         "CREATE_3D": False, "IGNORE_NODATA": False, "OUTPUT": "TEMPORARY_OUTPUT"},
        context=context, feedback=feedback, is_child_algorithm=True,
    )
    return obtener_capa(resultado.get("OUTPUT"), context, es_raster=False, nombre="Curvas de nivel")


def calcular_orden_strahler_en_capa(red_drenaje_layer: QgsVectorLayer,
                                     dem_path: str) -> QgsVectorLayer:
    """Copia `red_drenaje_layer` a una capa de memoria nueva con un
    campo entero "strahler" agregado, calculado con
    morphometry.strahler_order() -- la dirección de cada tramo se
    infiere de la elevación de sus dos extremos, muestreada del DEM
    (ver docstring de strahler_order() para el criterio completo:
    fluye del extremo más alto al más bajo)."""
    dem_layer = QgsRasterLayer(dem_path, "dem_muestreo")
    if not dem_layer.isValid():
        raise MapasTematicosError(f"no se pudo abrir el DEM para muestrear elevaciones: {dem_path}")
    proveedor_dem = dem_layer.dataProvider()

    def _elevacion(punto: QgsPointXY) -> float:
        valor, valido = proveedor_dem.sample(punto, 1)
        if not valido or valor is None:
            raise MapasTematicosError(
                f"no se pudo muestrear la elevación del DEM en ({punto.x():.5f}, {punto.y():.5f}) -- "
                "¿la red de drenaje se sale de la extensión del DEM recortado?"
            )
        return float(valor)

    lineas = []
    geometrias_por_id = {}
    for feat in red_drenaje_layer.getFeatures():
        geom = feat.geometry()
        if geom is None or geom.isEmpty():
            continue
        polilinea = geom.asPolyline() if not geom.isMultipart() else (
            geom.asMultiPolyline()[0] if geom.asMultiPolyline() else None)
        if not polilinea or len(polilinea) < 2:
            continue
        nodo_inicio, nodo_fin = polilinea[0], polilinea[-1]
        lineas.append({
            "id": feat.id(), "nodo_inicio": (nodo_inicio.x(), nodo_inicio.y()),
            "nodo_fin": (nodo_fin.x(), nodo_fin.y()),
            "z_inicio": _elevacion(nodo_inicio), "z_fin": _elevacion(nodo_fin),
        })
        geometrias_por_id[feat.id()] = geom

    if not lineas:
        raise MapasTematicosError("la red de drenaje no tiene ninguna línea válida para procesar.")

    ordenes = morphometry.strahler_order(lineas)

    crs_id = red_drenaje_layer.crs().authid()
    capa_salida = QgsVectorLayer(f"LineString?crs={crs_id}&field=strahler:integer", "Red de Drenaje (Strahler)",
                                  "memory")
    prov_salida = capa_salida.dataProvider()
    nuevas_feats = []
    for ln in lineas:
        f = QgsFeature()
        f.setGeometry(geometrias_por_id[ln["id"]])
        f.setAttributes([ordenes.get(ln["id"], 1)])
        nuevas_feats.append(f)
    prov_salida.addFeatures(nuevas_feats)
    capa_salida.updateExtents()
    return capa_salida


# ==========================================================================
# Precipitación y clima -- reutiliza los datos de estaciones YA
# ingresados por el usuario en "Módulos Avanzados (Beta) > Precipitación
# Areal" (self.edit_areal_estaciones / self._parsear_estaciones_areal()
# en plugin_dialog.py), sin pedirlos de nuevo.
# ==========================================================================
def generar_capa_estaciones(valores_estaciones: Dict[str, float],
                             coordenadas: Dict[str, Tuple[float, float]],
                             crs_id: str) -> QgsVectorLayer:
    """Capa de puntos en memoria, una entidad por estación, con campos
    "nombre" (texto) y "valor_mm" (precipitación puntual, el mismo dato
    ya ingresado por el usuario)."""
    capa = QgsVectorLayer(
        f"Point?crs={crs_id}&field=nombre:string&field=valor_mm:double",
        "Estaciones pluviométricas", "memory")
    prov = capa.dataProvider()
    feats = []
    for nombre, (x, y) in coordenadas.items():
        f = QgsFeature()
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
        f.setAttributes([nombre, valores_estaciones.get(nombre)])
        feats.append(f)
    if not feats:
        raise MapasTematicosError("no hay estaciones para generar la capa de puntos.")
    prov.addFeatures(feats)
    capa.updateExtents()
    return capa


def generar_thiessen_recortado(capa_estaciones: QgsVectorLayer, cuenca_layer: QgsVectorLayer,
                                context, feedback) -> QgsVectorLayer:
    """Polígonos de Thiessen (native:voronoipolygons) de `capa_estaciones`,
    recortados a `cuenca_layer` (native:clip) -- cada polígono conserva
    los campos "nombre"/"valor_mm" de su estación de origen (comportamiento
    nativo de voronoipolygons: un polígono por punto de entrada)."""
    import processing
    if capa_estaciones.featureCount() < 3:
        raise MapasTematicosError(
            "se necesitan al menos 3 estaciones para construir polígonos de Thiessen "
            f"(hay {capa_estaciones.featureCount()}).")

    # BUFFER de native:voronoipolygons es un % de la EXTENSIÓN DE LOS
    # PUNTOS (no de la cuenca) -- con BUFFER=0 el diagrama de Voronoi
    # queda acotado exactamente al bounding box de las estaciones, y si
    # la cuenca se extiende más allá de ese bbox (caso normal: las
    # estaciones rara vez caen justo en el borde de la cuenca), el
    # recorte posterior deja huecos SIN ningún polígono ahí -- se
    # calcula dinámicamente el buffer mínimo necesario para que el
    # diagrama cubra la extensión completa de la cuenca, con margen de
    # seguridad, en vez de un valor fijo que podría no alcanzar.
    extent_estaciones = capa_estaciones.extent()
    extent_cuenca = cuenca_layer.extent()
    ancho_e = max(extent_estaciones.width(), 1e-6)
    alto_e = max(extent_estaciones.height(), 1e-6)
    margen_izq = max(0.0, extent_estaciones.xMinimum() - extent_cuenca.xMinimum())
    margen_der = max(0.0, extent_cuenca.xMaximum() - extent_estaciones.xMaximum())
    margen_inf = max(0.0, extent_estaciones.yMinimum() - extent_cuenca.yMinimum())
    margen_sup = max(0.0, extent_cuenca.yMaximum() - extent_estaciones.yMaximum())
    buffer_pct_x = 100.0 * max(margen_izq, margen_der) / ancho_e
    buffer_pct_y = 100.0 * max(margen_inf, margen_sup) / alto_e
    buffer_pct = max(buffer_pct_x, buffer_pct_y) * 1.5 + 20.0  # factor de seguridad + piso mínimo

    resultado_voronoi = processing.run(
        "native:voronoipolygons",
        {"INPUT": capa_estaciones, "BUFFER": buffer_pct, "OUTPUT": "TEMPORARY_OUTPUT"},
        context=context, feedback=feedback, is_child_algorithm=True,
    )
    capa_voronoi = obtener_capa(resultado_voronoi.get("OUTPUT"), context, es_raster=False,
                                 nombre="thiessen_bruto")
    resultado_clip = processing.run(
        "native:clip",
        {"INPUT": capa_voronoi, "OVERLAY": cuenca_layer, "OUTPUT": "TEMPORARY_OUTPUT"},
        context=context, feedback=feedback, is_child_algorithm=True,
    )
    capa_recortada = obtener_capa(resultado_clip.get("OUTPUT"), context, es_raster=False,
                                   nombre="Polígonos de Thiessen")
    # obtener_capa() solo aplica el nombre `nombre=` cuando la salida es
    # una ruta de archivo (algoritmos gdal:*/grass7:*) -- las salidas de
    # algoritmos native:* (como voronoipolygons/clip) quedan registradas
    # como sink en el contexto y NO se renombran por ese camino; se fija
    # el nombre explícitamente aquí para que sea consistente en ambos
    # casos.
    capa_recortada.setName("Polígonos de Thiessen")
    if capa_recortada.featureCount() == 0:
        raise MapasTematicosError(
            "el recorte de los polígonos de Thiessen a la cuenca no produjo ningún polígono -- "
            "revise que las estaciones estén cerca de la cuenca delimitada.")
    return capa_recortada


def generar_isoyetas(raster_precipitacion_path: str, intervalo_mm: float, context, feedback):
    """Isoyetas (curvas de igual precipitación, gdal:contour) a partir
    del ráster ya interpolado (ver areal_precipitation.generar_raster_precipitacion_idw()),
    cada `intervalo_mm` -- devuelve la capa vectorial de líneas
    resultante (campo "PRECIP_MM" con el valor de cada isoyeta), mismo
    patrón que generar_curvas_nivel()."""
    import processing
    if intervalo_mm <= 0:
        raise MapasTematicosError("el intervalo de isoyetas debe ser mayor que 0.")
    resultado = processing.run(
        "gdal:contour",
        {"INPUT": raster_precipitacion_path, "BAND": 1, "INTERVAL": intervalo_mm,
         "FIELD_NAME": "PRECIP_MM", "CREATE_3D": False, "IGNORE_NODATA": False,
         "OUTPUT": "TEMPORARY_OUTPUT"},
        context=context, feedback=feedback, is_child_algorithm=True,
    )
    return obtener_capa(resultado.get("OUTPUT"), context, es_raster=False, nombre="Isoyetas")
