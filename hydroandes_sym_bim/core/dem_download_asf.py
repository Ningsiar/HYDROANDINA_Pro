# -*- coding: utf-8 -*-
"""
core/dem_download_asf.py

Descarga de MDE desde el catálogo de ASF DAAC (search.asf.alaska.edu /
Vertex), como alternativa a OpenTopography (core/dem_download.py).

TRANSPARENCIA IMPORTANTE (no verificado en vivo en este entorno, sin
acceso de red a asf.alaska.edu desde donde se escribió este módulo):

  - ASF DAAC está especializado en datos SAR (Sentinel-1, ALOS PALSAR),
    pero también aloja el DEM de referencia (Copernicus GLO-30) que usa
    internamente para sus productos RTC/InSAR, accesible vía su API de
    búsqueda estándar (la misma que usa la librería oficial
    `asf_search` y el sitio Vertex): 
        https://api.daac.asf.alaska.edu/services/search/param
    con el parámetro `dataset=COP-DEM_GLO-30-DGED` (o `processingLevel`
    equivalente). Verifique el nombre exacto del dataset/colección en
    https://asf.alaska.edu/api/ antes de production, ya que ASF ha
    reorganizado nombres de datasets en el pasado.

  - Autenticación: a diferencia de OpenTopography (una API Key simple),
    ASF/NASA Earthdata usa un TOKEN BEARER de Earthdata Login (URS):
    genere uno gratis en https://urs.earthdata.nasa.gov/ (My Profile ->
    Generate Token) y péguelo en el campo de la interfaz — se envía como
    cabecera 'Authorization: Bearer <token>' en cada descarga, el patrón
    estándar de autenticación de todos los DAAC de NASA Earthdata,
    incluido ASF.

  - Mosaico de múltiples tiles: Copernicus GLO-30 se distribue en tiles
    de 1x1 grado; si el AOI cae en más de un tile, se descargan todos
    los que intersectan el bbox y se mosaican con GDAL (gdal.Warp) antes
    de recortar a la extensión exacta solicitada.

Registro de token gratuito: https://urs.earthdata.nasa.gov/
"""
import json
import os
import tempfile
import urllib.request
import urllib.parse
import urllib.error

try:
    from osgeo import gdal
    gdal.UseExceptions()
except ImportError:
    gdal = None


_ENDPOINT_BUSQUEDA = "https://api.daac.asf.alaska.edu/services/search/param"
_DATASET_DEM_DEFAULT = "COP-DEM_GLO-30-DGED"


class DemDownloadAsfError(Exception):
    pass


def buscar_granulos_dem(bbox_wgs84, dataset: str = _DATASET_DEM_DEFAULT, timeout_seg: int = 60):
    """
    bbox_wgs84: (south, north, west, east) en grados decimales WGS84
        (mismo orden que usa dem_download.descargar_dem, para
        consistencia entre ambas fuentes en la interfaz).
    Devuelve una lista de URLs de descarga de los tiles DEM que
    intersectan el bbox.
    """
    south, north, west, east = bbox_wgs84
    poligono_wkt = (
        f"POLYGON(({west} {south},{east} {south},{east} {north},{west} {north},{west} {south}))"
    )
    params = {
        "dataset": dataset,
        "intersectsWith": poligono_wkt,
        "output": "json",
    }
    url = f"{_ENDPOINT_BUSQUEDA}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=timeout_seg) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise DemDownloadAsfError(f"Error HTTP {e.code} consultando el catálogo de ASF: {e.reason}") from e
    except urllib.error.URLError as e:
        raise DemDownloadAsfError(f"No se pudo conectar con el catálogo de ASF: {e.reason}") from e

    # La API de ASF devuelve, en su formato 'json', una lista anidada
    # [[granulo1, granulo2, ...]] o directamente una lista según la
    # versión de la API; se maneja ambos casos.
    granulos = data[0] if (isinstance(data, list) and data and isinstance(data[0], list)) else data
    urls = [g["url"] for g in granulos if g.get("url")]
    if not urls:
        raise DemDownloadAsfError(
            f"No se encontraron tiles del dataset '{dataset}' que intersecten el bbox indicado. "
            "Verifique el bbox y el nombre del dataset (ver nota de transparencia en "
            "core/dem_download_asf.py)."
        )
    return urls


def _descargar_con_token(url: str, token: str, destino: str, timeout_seg: int):
    peticion = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(peticion, timeout=timeout_seg) as resp:
            contenido = resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise DemDownloadAsfError(
                "Token de NASA Earthdata inválido o expirado (HTTP 401). Genere uno nuevo en "
                "https://urs.earthdata.nasa.gov/ (My Profile > Generate Token)."
            ) from e
        elif e.code == 403:
            raise DemDownloadAsfError(
                "Acceso denegado (HTTP 403). Verifique que su cuenta de Earthdata haya aceptado "
                "los términos de uso de ASF DAAC (Vertex > My Profile)."
            ) from e
        else:
            raise DemDownloadAsfError(f"Error HTTP {e.code} descargando el tile: {e.reason}") from e
    except urllib.error.URLError as e:
        raise DemDownloadAsfError(f"No se pudo conectar con ASF DAAC: {e.reason}") from e
    with open(destino, "wb") as f:
        f.write(contenido)


def descargar_dem_asf(bbox_wgs84, token: str, dataset: str = _DATASET_DEM_DEFAULT,
                       destino_tif: str = None, timeout_seg: int = 180) -> str:
    """
    Descarga (y mosaica si es necesario) el MDE Copernicus GLO-30 alojado
    en ASF DAAC para el bbox indicado, usando un token Bearer de NASA
    Earthdata Login. Devuelve la ruta del .tif final.
    """
    if not token:
        raise DemDownloadAsfError(
            "No se proporcionó un token de NASA Earthdata. Genere uno gratis en "
            "https://urs.earthdata.nasa.gov/ (My Profile > Generate Token) y péguelo en la "
            "pestaña 'DEM y Delineación'."
        )

    urls = buscar_granulos_dem(bbox_wgs84, dataset=dataset, timeout_seg=timeout_seg)

    carpeta_tmp = tempfile.mkdtemp(prefix="hydroandes_asf_dem_")
    rutas_tiles = []
    for i, url in enumerate(urls):
        destino_tile = os.path.join(carpeta_tmp, f"tile_{i}.tif")
        _descargar_con_token(url, token, destino_tile, timeout_seg)
        rutas_tiles.append(destino_tile)

    if destino_tif is None:
        destino_tif = os.path.join(tempfile.gettempdir(), "hydroandes_dem_asf_copdem30.tif")

    if len(rutas_tiles) == 1:
        import shutil
        shutil.copyfile(rutas_tiles[0], destino_tif)
    else:
        if gdal is None:
            raise DemDownloadAsfError(
                "El AOI requiere mosaicar varios tiles DEM, pero no se encontraron los bindings "
                "de Python de GDAL (osgeo.gdal) para hacerlo."
            )
        resultado = gdal.Warp(destino_tif, rutas_tiles, format="GTiff")
        if resultado is None:
            raise DemDownloadAsfError("gdal.Warp no pudo mosaicar los tiles DEM descargados.")
        resultado = None  # cerrar el dataset y volcar a disco

    return destino_tif
