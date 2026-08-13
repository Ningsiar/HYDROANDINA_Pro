# -*- coding: utf-8 -*-
"""
core/landcover_soils.py

Obtención automática de:
  A) Uso y Cobertura de Suelo (LULC) — ESA WorldCover 10 m, vía el
     catálogo STAC de AWS Earth Search (Element84).
  B) Grupos Hidrológicos de Suelo (HSG: A/B/C/D) — HYSOGs250m (Oak Ridge
     National Laboratory) o, alternativamente, SoilGrids (ISRIC),
     recortados a la cuenca desde una URL o ruta que indique el usuario.

...y el cálculo del CN ponderado por cruce (intersección pixel a pixel)
de ambos rásters, para la Pestaña 3 (Número de Curva SCS).

TRANSPARENCIA IMPORTANTE (léase antes de usar en producción):

  1. ESA WorldCover vía STAC: se implementa contra el endpoint público
     documentado de Earth Search v1 (Element84):
         https://earth-search.aws.element84.com/v1/search
     con la colección "esa-worldcover" (mosaicos 2020/2021). No se pudo
     verificar en vivo en este entorno (sin acceso de red a AWS desde
     donde se escribió este módulo) que el nombre exacto de la colección
     y de los assets ("map") siga siendo el mismo al momento en que este
     plugin se ejecute — Element84 ha reorganizado colecciones STAC en
     el pasado. Si `buscar_coleccion_esa_worldcover()` no encuentra la
     colección, revise https://earth-search.aws.element84.com/v1 en un
     navegador y ajuste `_CANDIDATOS_COLECCION_WORLDCOVER` abajo.

  2. HSG (HYSOGs250m / SoilGrids): a diferencia de ESA WorldCover, NO se
     encontró un catálogo STAC público estable para HYSOGs250m al
     redactar este módulo (el dataset se distribuye principalmente desde
     ORNL DAAC como GeoTIFF único: https://doi.org/10.3334/ORNLDAAC/1566).
     Por eso `obtener_hsg_recortado()` recibe una URL o ruta local que el
     USUARIO debe indicar (descargar una vez desde ORNL DAAC, o usar la
     URL directa si el dataset expone acceso HTTP por rango). Se aceptan
     ambos casos porque GDAL puede leer un GeoTIFF remoto vía /vsicurl/
     sin descargarlo completo, si el servidor soporta rangos HTTP.

  3. Mapeo LULC->CN: la tabla TABLA_CN_ESA_WORLDCOVER de abajo es un
     mapeo de referencia (adaptado de los análogos más cercanos de
     TR-55 para cada clase de ESA WorldCover) y, como el resto de tablas
     de CN de este plugin, debe verificarse/ajustarse contra una fuente
     local antes de un diseño definitivo.

  4. Codificación HSG asumida: 1=A, 2=B, 3=C, 4=D (codificación estándar
     de HYSOGs250m, Ross et al. 2018). Si su ráster de HSG usa otra
     codificación, ajuste `mapeo_codigo_hsg` al llamar a
     calcular_cn_ponderado_automatico().
"""
import json
import math
import os
import tempfile
import urllib.request
import urllib.error
from typing import Dict, List, Optional, Tuple

import numpy as np

try:
    from osgeo import gdal
    gdal.UseExceptions()
except ImportError:
    gdal = None


class LandcoverSoilsError(Exception):
    pass


# ---------------------------------------------------------------------
# A) ESA WorldCover vía STAC (Earth Search / AWS)
# ---------------------------------------------------------------------
_STAC_ENDPOINT_BUSQUEDA = "https://earth-search.aws.element84.com/v1/search"
_CANDIDATOS_COLECCION_WORLDCOVER = ["esa-worldcover", "esa-worldcover-2021", "esa-worldcover-2020"]

# Clases ESA WorldCover (código -> nombre), y su mapeo a CN por grupo
# hidrológico A/B/C/D. Ver nota de transparencia #3 del docstring.
TABLA_CN_ESA_WORLDCOVER: Dict[int, dict] = {
    10: {"nombre": "Bosque / cobertura arbórea", "cn_a": 30, "cn_b": 55, "cn_c": 70, "cn_d": 77},
    20: {"nombre": "Matorral (shrubland)", "cn_a": 35, "cn_b": 56, "cn_c": 70, "cn_d": 77},
    30: {"nombre": "Pastizal (grassland)", "cn_a": 39, "cn_b": 61, "cn_c": 74, "cn_d": 80},
    40: {"nombre": "Cultivos (cropland)", "cn_a": 67, "cn_b": 78, "cn_c": 85, "cn_d": 89},
    50: {"nombre": "Área construida (built-up)", "cn_a": 77, "cn_b": 85, "cn_c": 90, "cn_d": 92},
    60: {"nombre": "Suelo desnudo / vegetación escasa", "cn_a": 77, "cn_b": 86, "cn_c": 91, "cn_d": 94},
    70: {"nombre": "Nieve / hielo", "cn_a": 100, "cn_b": 100, "cn_c": 100, "cn_d": 100},
    80: {"nombre": "Cuerpo de agua", "cn_a": 100, "cn_b": 100, "cn_c": 100, "cn_d": 100},
    90: {"nombre": "Humedal herbáceo (bofedal)", "cn_a": 30, "cn_b": 50, "cn_c": 65, "cn_d": 75},
    95: {"nombre": "Manglar", "cn_a": 30, "cn_b": 50, "cn_c": 65, "cn_d": 75},
    100: {"nombre": "Musgo / liquen", "cn_a": 35, "cn_b": 56, "cn_c": 70, "cn_d": 77},
}


def _bbox_wgs84_de_capa(cuenca_layer) -> Tuple[float, float, float, float]:
    """Devuelve (west, south, east, north) en WGS84 a partir del extent
    de la capa de cuenca (que puede estar en cualquier CRS proyectado)."""
    from qgis.core import QgsCoordinateTransform, QgsCoordinateReferenceSystem, QgsProject
    extent = cuenca_layer.extent()
    crs_origen = cuenca_layer.crs()
    wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
    if crs_origen.authid() != "EPSG:4326":
        xform = QgsCoordinateTransform(crs_origen, wgs84, QgsProject.instance())
        extent = xform.transformBoundingBox(extent)
    return extent.xMinimum(), extent.yMinimum(), extent.xMaximum(), extent.yMaximum()


def buscar_coleccion_esa_worldcover(bbox_wgs84: Tuple[float, float, float, float],
                                     timeout_seg: int = 30) -> Tuple[str, List[str]]:
    """
    Consulta el catálogo STAC de Earth Search y devuelve
    (id_coleccion_encontrada, [urls_cog_de_los_items_que_cubren_el_bbox]).
    """
    west, south, east, north = bbox_wgs84
    ultimo_error = None
    for coleccion in _CANDIDATOS_COLECCION_WORLDCOVER:
        payload = json.dumps({
            "collections": [coleccion],
            "bbox": [west, south, east, north],
            "limit": 20,
        }).encode("utf-8")
        peticion = urllib.request.Request(
            _STAC_ENDPOINT_BUSQUEDA, data=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(peticion, timeout=timeout_seg) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            features = data.get("features", [])
            if not features:
                continue
            urls = []
            for feat in features:
                assets = feat.get("assets", {})
                # El nombre del asset del COG principal ha variado entre
                # versiones del catálogo ("map", "ESA_WORLDCOVER_10M_MAP", etc.);
                # se busca el primer asset cuyo media_type sea GeoTIFF/COG.
                href = None
                for clave, asset in assets.items():
                    tipo = asset.get("type", "")
                    if "tiff" in tipo.lower() or clave.lower() in ("map", "data"):
                        href = asset.get("href")
                        if href:
                            break
                if href:
                    urls.append(href)
            if urls:
                return coleccion, urls
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as e:
            ultimo_error = e
            continue
    raise LandcoverSoilsError(
        "No se encontró la colección ESA WorldCover en Earth Search para el bbox indicado "
        f"(colecciones probadas: {_CANDIDATOS_COLECCION_WORLDCOVER}). "
        "Verifique conectividad a https://earth-search.aws.element84.com/v1 y si el nombre "
        "de la colección cambió (ver nota de transparencia #1 en core/landcover_soils.py). "
        f"Último error: {ultimo_error}"
    )


def obtener_lulc_esa_worldcover_recortado(cuenca_layer, context, feedback,
                                           destino_tif: Optional[str] = None) -> str:
    """
    Localiza el/los mosaico(s) COG de ESA WorldCover que cubren la
    cuenca, los recorta a la extensión/máscara de la cuenca (con
    lectura remota vía /vsicurl/, sin descargar el mosaico global) y,
    si son varios tiles, los combina en un único ráster. Devuelve la
    ruta del GeoTIFF final recortado.
    """
    import processing
    bbox = _bbox_wgs84_de_capa(cuenca_layer)
    _, urls_cog = buscar_coleccion_esa_worldcover(bbox)

    rutas_recortadas = []
    for i, url in enumerate(urls_cog):
        ruta_vsicurl = f"/vsicurl/{url}"
        resultado = processing.run(
            "gdal:cliprasterbymasklayer",
            {
                "INPUT": ruta_vsicurl,
                "MASK": cuenca_layer,
                "SOURCE_CRS": None,
                "TARGET_CRS": None,
                "NODATA": None,
                "ALPHA_BAND": False,
                "CROP_TO_CUTLINE": True,
                "KEEP_RESOLUTION": True,
                "OUTPUT": "TEMPORARY_OUTPUT",
            },
            context=context, feedback=feedback, is_child_algorithm=True,
        )
        ruta_out = resultado.get("OUTPUT")
        if ruta_out:
            rutas_recortadas.append(ruta_out)

    if not rutas_recortadas:
        raise LandcoverSoilsError("Ningún tile de ESA WorldCover pudo recortarse a la cuenca.")

    if destino_tif is None:
        destino_tif = os.path.join(tempfile.gettempdir(), "hydroandina_lulc_esa_worldcover.tif")

    if len(rutas_recortadas) == 1:
        import shutil
        shutil.copyfile(rutas_recortadas[0], destino_tif)
    else:
        resultado_merge = processing.run(
            "gdal:merge",
            {"INPUT": rutas_recortadas, "OUTPUT": destino_tif},
            context=context, feedback=feedback, is_child_algorithm=True,
        )
        if not resultado_merge.get("OUTPUT"):
            raise LandcoverSoilsError("No se pudo combinar los tiles de ESA WorldCover recortados.")

    return destino_tif


# ---------------------------------------------------------------------
# B) Grupos Hidrológicos de Suelo (HSG) — HYSOGs250m / SoilGrids
# ---------------------------------------------------------------------
def obtener_hsg_recortado(ruta_o_url_hsg: str, cuenca_layer, context, feedback,
                           destino_tif: Optional[str] = None) -> str:
    """
    Recorta el ráster de Grupos Hidrológicos de Suelo (HYSOGs250m u otro
    ya reclasificado a A/B/C/D) a la cuenca. Acepta tanto una ruta local
    como una URL http(s) (leída vía /vsicurl/ sin descarga completa, si
    el servidor soporta rangos HTTP — la mayoría de servidores de
    ORNL DAAC lo soportan).
    """
    import processing
    entrada = ruta_o_url_hsg
    if entrada.lower().startswith("http://") or entrada.lower().startswith("https://"):
        entrada = f"/vsicurl/{entrada}"

    if destino_tif is None:
        destino_tif = os.path.join(tempfile.gettempdir(), "hydroandina_hsg_recortado.tif")

    resultado = processing.run(
        "gdal:cliprasterbymasklayer",
        {
            "INPUT": entrada, "MASK": cuenca_layer, "SOURCE_CRS": None, "TARGET_CRS": None,
            "NODATA": None, "ALPHA_BAND": False, "CROP_TO_CUTLINE": True,
            "KEEP_RESOLUTION": True, "OUTPUT": destino_tif,
        },
        context=context, feedback=feedback, is_child_algorithm=True,
    )
    ruta_out = resultado.get("OUTPUT")
    if not ruta_out:
        raise LandcoverSoilsError(
            "No se pudo recortar el ráster de HSG a la cuenca. Verifique que la ruta/URL sea "
            "correcta y accesible, y que el ráster cubra efectivamente la extensión de la cuenca."
        )
    return ruta_out


# ---------------------------------------------------------------------
# C) Cruce LULC x HSG -> CN ponderado
# ---------------------------------------------------------------------
def calcular_cn_ponderado_automatico(lulc_clip_path: str, hsg_clip_path: str,
                                      mapeo_codigo_hsg: Optional[Dict[int, str]] = None,
                                      tabla_cn: Optional[Dict[int, dict]] = None) -> dict:
    """
    Cruza pixel a pixel el ráster de LULC (ESA WorldCover, ya recortado
    a la cuenca) con el ráster de HSG (ya recortado a la misma cuenca,
    posiblemente en otra resolución/grilla), calcula el CN de cada pixel
    según (clase LULC, grupo HSG) usando `tabla_cn`, y devuelve el CN_II
    ponderado por área junto con el desglose área x CN de cada
    combinación LULC x HSG presente en la cuenca.

    Requiere GDAL con bindings de Python (osgeo.gdal), disponibles en el
    entorno de QGIS.
    """
    if gdal is None:
        raise LandcoverSoilsError(
            "No se encontraron los bindings de Python de GDAL (osgeo.gdal), necesarios para "
            "cruzar los rásters de LULC y HSG. Esto es inusual en una instalación estándar de "
            "QGIS; verifique la instalación."
        )
    mapeo_codigo_hsg = mapeo_codigo_hsg or {1: "A", 2: "B", 3: "C", 4: "D"}
    tabla_cn = tabla_cn or TABLA_CN_ESA_WORLDCOVER

    ds_lulc = gdal.Open(lulc_clip_path)
    if ds_lulc is None:
        raise LandcoverSoilsError(f"No se pudo abrir el ráster de LULC recortado: {lulc_clip_path}")

    ancho, alto = ds_lulc.RasterXSize, ds_lulc.RasterYSize
    gt = ds_lulc.GetGeoTransform()
    proj = ds_lulc.GetProjection()
    pixel_area_m2 = abs(gt[1] * gt[5])

    lulc_array = ds_lulc.GetRasterBand(1).ReadAsArray()

    # Remuestrear el HSG (usualmente 250 m) a la grilla exacta del LULC
    # (usualmente 10 m) con vecino más cercano, ya que HSG es categórico.
    ds_hsg_resampleado = gdal.Warp(
        "", hsg_clip_path, format="MEM",
        width=ancho, height=alto, outputBounds=(
            gt[0], gt[3] + alto * gt[5], gt[0] + ancho * gt[1], gt[3]
        ),
        dstSRS=proj, resampleAlg="near",
    )
    if ds_hsg_resampleado is None:
        raise LandcoverSoilsError("No se pudo remuestrear el ráster de HSG a la grilla del LULC.")
    hsg_array = ds_hsg_resampleado.GetRasterBand(1).ReadAsArray()

    if lulc_array.shape != hsg_array.shape:
        raise LandcoverSoilsError(
            "Las grillas de LULC y HSG remuestreado no coinciden en forma "
            f"({lulc_array.shape} vs {hsg_array.shape}); revise el remuestreo."
        )

    combinaciones: Dict[Tuple[int, str], int] = {}
    codigos_lulc = np.unique(lulc_array)
    for codigo_lulc in codigos_lulc:
        if int(codigo_lulc) not in tabla_cn:
            continue
        mascara_lulc = lulc_array == codigo_lulc
        codigos_hsg_presentes = np.unique(hsg_array[mascara_lulc])
        for codigo_hsg in codigos_hsg_presentes:
            letra_hsg = mapeo_codigo_hsg.get(int(codigo_hsg))
            if letra_hsg is None:
                continue
            n_pixeles = int(np.sum(mascara_lulc & (hsg_array == codigo_hsg)))
            combinaciones[(int(codigo_lulc), letra_hsg)] = n_pixeles

    if not combinaciones:
        raise LandcoverSoilsError(
            "No se encontró ninguna combinación válida (LULC, HSG) dentro de la cuenca; "
            "verifique que ambos rásters efectivamente se solapen con la cuenca delineada."
        )

    filas_cn = []
    desglose = []
    area_total_km2 = 0.0
    for (codigo_lulc, letra_hsg), n_pixeles in combinaciones.items():
        area_km2 = (n_pixeles * pixel_area_m2) / 1e6
        atributo_cn = f"cn_{letra_hsg.lower()}"
        cn = tabla_cn[codigo_lulc][atributo_cn]
        filas_cn.append({"area_km2": area_km2, "cn": cn})
        desglose.append({
            "lulc_codigo": codigo_lulc, "lulc_nombre": tabla_cn[codigo_lulc]["nombre"],
            "hsg": letra_hsg, "area_km2": round(area_km2, 4), "cn": cn,
        })
        area_total_km2 += area_km2

    from .curve_number import cn_ponderado_mixto
    cn_ii = cn_ponderado_mixto(filas_cn)

    desglose.sort(key=lambda d: d["area_km2"], reverse=True)
    return {
        "cn_ii_ponderado": round(cn_ii, 2),
        "area_total_km2": round(area_total_km2, 4),
        "desglose": desglose,
    }
