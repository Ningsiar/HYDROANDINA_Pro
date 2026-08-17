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
from qgis.core import QgsVectorLayer, QgsFeature, QgsRasterLayer, QgsPointXY

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
