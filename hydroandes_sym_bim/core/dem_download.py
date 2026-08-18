# -*- coding: utf-8 -*-
"""
core/dem_download.py

Descarga de MDE desde la API pública de OpenTopography (SRTM GL1/GL3,
ALOS World 3D, Copernicus GLO-30, etc.), usando el bounding box de la
capa AOI y una API Key personal del usuario.

IMPORTANTE (no verificado en este entorno): esta función hace una
petición HTTP real; no se pudo probar en el entorno donde se escribió
este plugin porque no hay acceso a red aquí. El formato del endpoint
está documentado públicamente por OpenTopography y se implementó tal
como está publicado, pero se recomienda probarlo primero con un
bounding box pequeño antes de integrarlo a un flujo de producción,
y manejar el caso de error 401 (API key inválida) / 429 (límite de
tasa excedido) explícitamente como se hace abajo.

Registro de API Key gratuita: https://portal.opentopography.org/
"""
import os
import urllib.request
import urllib.parse
import urllib.error


DEMTYPES_DISPONIBLES = {
    "SRTMGL1": "SRTM GL1 (30 m)",
    "SRTMGL3": "SRTM GL3 (90 m)",
    "AW3D30": "ALOS World 3D (30 m)",
    "COP30": "Copernicus GLO-30 (30 m)",
    "COP90": "Copernicus GLO-90 (90 m)",
}

_ENDPOINT = "https://portal.opentopography.org/API/globaldem"


class DemDownloadError(Exception):
    pass


def descargar_dem(bbox_wgs84, api_key: str, demtype: str = "SRTMGL1",
                   destino_tif: str = None, timeout_seg: int = 120) -> str:
    """
    bbox_wgs84: (south, north, west, east) en grados decimales WGS84.
    api_key: clave personal de OpenTopography (Tab 1 de la interfaz).
    demtype: uno de DEMTYPES_DISPONIBLES.
    destino_tif: ruta de salida; si es None se usa un archivo temporal.
    Devuelve la ruta del archivo .tif descargado.
    """
    if not api_key:
        raise DemDownloadError(
            "No se proporcionó API Key de OpenTopography. Regístrese gratis en "
            "https://portal.opentopography.org/ y péguela en la pestaña 'DEM Acquisition'."
        )
    if demtype not in DEMTYPES_DISPONIBLES:
        raise DemDownloadError(f"demtype '{demtype}' no reconocido. Opciones: {list(DEMTYPES_DISPONIBLES)}")

    south, north, west, east = bbox_wgs84
    params = {
        "demtype": demtype,
        "south": south, "north": north, "west": west, "east": east,
        "outputFormat": "GTiff",
        "API_Key": api_key,
    }
    url = f"{_ENDPOINT}?{urllib.parse.urlencode(params)}"

    if destino_tif is None:
        import tempfile
        destino_tif = os.path.join(tempfile.gettempdir(), f"hydroandes_dem_{demtype}.tif")

    try:
        with urllib.request.urlopen(url, timeout=timeout_seg) as respuesta:
            contenido = respuesta.read()
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise DemDownloadError("API Key inválida o no autorizada (HTTP 401).") from e
        elif e.code == 429:
            raise DemDownloadError("Límite de peticiones a OpenTopography excedido (HTTP 429). Intente más tarde.") from e
        else:
            raise DemDownloadError(f"Error HTTP {e.code} al descargar el MDE: {e.reason}") from e
    except urllib.error.URLError as e:
        raise DemDownloadError(f"No se pudo conectar con OpenTopography: {e.reason}") from e

    with open(destino_tif, "wb") as f:
        f.write(contenido)

    return destino_tif
