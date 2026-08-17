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

  1. ESA WorldCover vía STAC: se prueban DOS proveedores en orden,
     porque un despliegue en vivo (feedback directo del usuario, con
     acceso de red real) encontró que Earth Search v1 (Element84)
         https://earth-search.aws.element84.com/v1/search
     NO tiene una colección "esa-worldcover" a secas -- solo existen
     "esa-worldcover-2021"/"esa-worldcover-2020" (mosaicos por año), y
     una búsqueda con el nombre equivocado responde 200 OK con
     `features: []` en vez de un error, así que el bbox llegaba bien
     pero el bucle de colecciones se vaciaba en silencio. Si Earth
     Search tampoco da resultados (bbox fuera de cobertura, colección
     renombrada de nuevo, etc.), se reintenta contra Microsoft
     Planetary Computer:
         https://planetarycomputer.microsoft.com/api/stac/v1/search
     con la colección "esa-worldcover" (esta sí existe ahí con ese
     nombre). Los assets de Planetary Computer están firmados por SAS
     token (Azure Blob Storage) -- `_firmar_href_planetary_computer()`
     llama a su endpoint público de firma
     (.../api/sas/v1/sign?href=...) antes de intentar leer el COG; si
     la firma falla (p.ej. sin red), se seguirá usando el href sin
     firmar como último recurso, que puede o no ser accesible según el
     dataset. Este segundo proveedor y el paso de firma NO se pudieron
     probar en vivo en este entorno (sin acceso de red desde donde se
     escribió este módulo) -- si `buscar_coleccion_esa_worldcover()` no
     encuentra la colección en NINGÚN proveedor, revise
     https://earth-search.aws.element84.com/v1 y
     https://planetarycomputer.microsoft.com/api/stac/v1 en un
     navegador y ajuste `_STAC_PROVEEDORES_WORLDCOVER` abajo.

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
import hashlib
import json
import os
import tempfile
import urllib.request
import urllib.error
import urllib.parse
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
# Caché local de mosaicos descargados/recortados -- evita re-descargar
# y re-recortar ESA WorldCover/SoilGrids en ejecuciones sucesivas sobre
# la MISMA extensión de cuenca (recomendación de desarrollo del
# usuario). El directorio vive en el perfil de QGIS (persiste entre
# sesiones, a diferencia del directorio temporal del sistema operativo,
# que el SO puede limpiar en cualquier momento).
# ---------------------------------------------------------------------
def _directorio_cache() -> str:
    base = None
    try:
        from qgis.core import QgsApplication
        base = QgsApplication.qgisSettingsDirPath()
    except Exception:
        base = None
    # qgisSettingsDirPath() puede devolver "" (cadena vacía, no una
    # excepción) si se llama sobre una QgsApplication sin perfil real
    # configurado -- os.path.join con base="" resolvería relativo al
    # directorio de trabajo actual (podría terminar escribiendo DENTRO
    # del repositorio del plugin en vez de un lugar persistente), así
    # que se exige un valor no vacío explícitamente.
    if not base:
        base = tempfile.gettempdir()
    directorio = os.path.join(base, "hydroandes_sym_bim_cache_cn")
    os.makedirs(directorio, exist_ok=True)
    return directorio


def _ruta_cache(nombre_dataset: str, bbox_wgs84: Tuple[float, float, float, float]) -> str:
    """Ruta determinística de caché para `nombre_dataset` recortado al
    `bbox_wgs84` indicado (west,south,east,north) -- el mismo bbox
    (redondeado a 6 decimales, ~0.1 m de tolerancia en el ecuador)
    siempre produce la misma ruta."""
    bbox_redondeado = tuple(round(v, 6) for v in bbox_wgs84)
    clave = f"{nombre_dataset}_{bbox_redondeado}"
    hash_clave = hashlib.md5(clave.encode("utf-8")).hexdigest()[:16]
    return os.path.join(_directorio_cache(), f"{nombre_dataset}_{hash_clave}.tif")


def limpiar_cache() -> int:
    """Borra todos los archivos del directorio de caché (LULC/HSG
    descargados y recortados) -- devuelve cuántos se borraron. Úselo si
    un dataset remoto se actualizó (nueva versión de ESA WorldCover/
    SoilGrids) y quiere forzar una redescarga en la próxima ejecución."""
    directorio = _directorio_cache()
    n = 0
    for nombre in os.listdir(directorio):
        ruta = os.path.join(directorio, nombre)
        try:
            os.remove(ruta)
            n += 1
        except OSError:
            pass
    return n


# ---------------------------------------------------------------------
# A) ESA WorldCover vía STAC (Earth Search / AWS, con respaldo en
#    Microsoft Planetary Computer) -- ver nota de transparencia #1.
# ---------------------------------------------------------------------
_STAC_PROVEEDORES_WORLDCOVER = [
    {
        "nombre": "Earth Search (Element84)",
        "endpoint": "https://earth-search.aws.element84.com/v1/search",
        "colecciones": ["esa-worldcover-2021", "esa-worldcover-2020"],
        "requiere_firma": False,
    },
    {
        "nombre": "Microsoft Planetary Computer",
        "endpoint": "https://planetarycomputer.microsoft.com/api/stac/v1/search",
        "colecciones": ["esa-worldcover"],
        "requiere_firma": True,
    },
]
_URL_FIRMA_PLANETARY_COMPUTER = "https://planetarycomputer.microsoft.com/api/sas/v1/sign?href={href}"

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


def cargar_matriz_cn(ruta: Optional[str] = None) -> Dict[int, dict]:
    """Carga la matriz LULC->CN desde resources/cn_matriz_lulc.json
    (editable a mano por el usuario, ver Pestaña 3) -- si el archivo no
    existe o no se puede leer, usa TABLA_CN_ESA_WORLDCOVER (los mismos
    valores, embebidos como respaldo) para que el plugin nunca se
    quede sin matriz utilizable."""
    if ruta is None:
        ruta = os.path.join(os.path.dirname(__file__), "..", "resources", "cn_matriz_lulc.json")
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            datos = json.load(f)
        return {int(k): v for k, v in datos.items() if not k.startswith("_")}
    except (OSError, ValueError, json.JSONDecodeError):
        return dict(TABLA_CN_ESA_WORLDCOVER)


def guardar_matriz_cn(matriz: Dict[int, dict], ruta: Optional[str] = None) -> str:
    """Inverso de cargar_matriz_cn() -- persiste `matriz` (dict
    código_lulc -> {"nombre","cn_a","cn_b","cn_c","cn_d"}) al JSON
    editable. Devuelve la ruta escrita."""
    if ruta is None:
        ruta = os.path.join(os.path.dirname(__file__), "..", "resources", "cn_matriz_lulc.json")
    datos = {"_comentario": "Matriz de equivalencia clase LULC (ESA WorldCover) -> CN por Grupo "
                            "Hidrológico de Suelo (A/B/C/D), TR-55/NRCS. Editable a mano desde la "
                            "Pestaña 3."}
    datos.update({str(k): v for k, v in matriz.items()})
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, indent=2, ensure_ascii=False)
    return ruta


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


def _firmar_href_planetary_computer(href: str, timeout_seg: int = 15) -> str:
    """Firma `href` (asset de Planetary Computer, en Azure Blob Storage)
    con su API pública de firma SAS -- sin la firma, muchos contenedores
    de Planetary Computer devuelven 403 al leer directamente. Si la
    firma falla (p.ej. sin red), se devuelve `href` SIN firmar como
    último recurso -- puede o no ser accesible según el dataset, pero
    es mejor que abortar aquí y perder el resto del flujo."""
    try:
        peticion = urllib.request.Request(
            _URL_FIRMA_PLANETARY_COMPUTER.format(href=urllib.parse.quote(href, safe="")),
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(peticion, timeout=timeout_seg) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("href", href)
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, ValueError):
        return href


def buscar_coleccion_esa_worldcover(bbox_wgs84: Tuple[float, float, float, float],
                                     timeout_seg: int = 30) -> Tuple[str, List[str]]:
    """
    Consulta los catálogos STAC de _STAC_PROVEEDORES_WORLDCOVER, EN
    ORDEN (Earth Search primero, Planetary Computer como respaldo), y
    devuelve (id_coleccion_encontrada, [urls_cog_de_los_items_que_cubren_el_bbox]).
    Los assets de proveedores con `requiere_firma=True` se firman antes
    de devolverse (ver `_firmar_href_planetary_computer()`), para que
    la URL resultante sea directamente utilizable con /vsicurl/.
    """
    west, south, east, north = bbox_wgs84
    ultimo_error = None
    intentos = []  # (proveedor, colección) probados, para el mensaje de error final
    for proveedor in _STAC_PROVEEDORES_WORLDCOVER:
        for coleccion in proveedor["colecciones"]:
            intentos.append(f"{proveedor['nombre']}/{coleccion}")
            payload = json.dumps({
                "collections": [coleccion],
                "bbox": [west, south, east, north],
                "limit": 20,
            }).encode("utf-8")
            peticion = urllib.request.Request(
                proveedor["endpoint"], data=payload,
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
                        if proveedor["requiere_firma"]:
                            href = _firmar_href_planetary_computer(href, timeout_seg)
                        urls.append(href)
                if urls:
                    return coleccion, urls
            except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as e:
                ultimo_error = e
                continue
    raise LandcoverSoilsError(
        "No se encontró la colección ESA WorldCover en ningún proveedor STAC para el bbox "
        f"indicado (probados: {', '.join(intentos)}). "
        "Verifique conectividad a https://earth-search.aws.element84.com/v1 y "
        "https://planetarycomputer.microsoft.com/api/stac/v1, y si algún nombre de colección "
        "cambió (ver nota de transparencia #1 en core/landcover_soils.py). "
        f"Último error: {ultimo_error}"
    )


def obtener_lulc_esa_worldcover_recortado(cuenca_layer, context, feedback,
                                           destino_tif: Optional[str] = None,
                                           usar_cache: bool = True) -> str:
    """
    Localiza el/los mosaico(s) COG de ESA WorldCover que cubren la
    cuenca, los recorta a la extensión/máscara de la cuenca (con
    lectura remota vía /vsicurl/, sin descargar el mosaico global) y,
    si son varios tiles, los combina en un único ráster. Devuelve la
    ruta del GeoTIFF final recortado. `usar_cache`: si el recorte para
    esta MISMA extensión de cuenca ya existe en la caché local (ver
    `_directorio_cache()`), lo reutiliza sin volver a descargar/recortar.
    """
    bbox = _bbox_wgs84_de_capa(cuenca_layer)
    if usar_cache and destino_tif is None:
        destino_tif = _ruta_cache("esa_worldcover", bbox)
        if os.path.isfile(destino_tif) and os.path.getsize(destino_tif) > 0:
            return destino_tif
    import processing
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
                           destino_tif: Optional[str] = None, usar_cache: bool = True) -> str:
    """
    Recorta el ráster de Grupos Hidrológicos de Suelo (HYSOGs250m u otro
    ya reclasificado a A/B/C/D) a la cuenca. Acepta tanto una ruta local
    como una URL http(s) (leída vía /vsicurl/ sin descarga completa, si
    el servidor soporta rangos HTTP — la mayoría de servidores de
    ORNL DAAC lo soportan). `usar_cache`: ver `obtener_lulc_esa_worldcover_recortado()`
    -- la clave de caché aquí incluye la ruta/URL indicada, así que un
    cambio de fuente no reutiliza por error el recorte de otra.
    """
    entrada = ruta_o_url_hsg
    if entrada.lower().startswith("http://") or entrada.lower().startswith("https://"):
        entrada = f"/vsicurl/{entrada}"

    if usar_cache and destino_tif is None:
        hash_fuente = hashlib.md5(ruta_o_url_hsg.encode("utf-8")).hexdigest()[:10]
        destino_tif = _ruta_cache(f"hsg_manual_{hash_fuente}", _bbox_wgs84_de_capa(cuenca_layer))
        if os.path.isfile(destino_tif) and os.path.getsize(destino_tif) > 0:
            return destino_tif

    import processing
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
# B2) HSG 100% AUTÓNOMO vía SoilGrids (ISRIC) + textura USDA -- sin que
# el usuario tenga que aportar un ráster de HSG ya clasificado.
# ---------------------------------------------------------------------
# TRANSPARENCIA IMPORTANTE (léase antes de usar en producción, mismo
# criterio que la nota #1 de ESA WorldCover arriba):
#
#   SoilGrids v2.0 (ISRIC) publica sus mapas globales como VRT/COG en
#   https://files.isric.org/soilgrids/latest/data/<propiedad>/<propiedad>_<profundidad>_mean.vrt
#   (p.ej. .../clay/clay_0-5cm_mean.vrt) accesibles vía /vsicurl/ igual
#   que ESA WorldCover -- esta es la ruta documentada por ISRIC al
#   redactar este módulo, pero NO se pudo verificar en vivo (sin acceso
#   de red desde este entorno) que siga vigente. Si
#   `obtener_hsg_soilgrids_automatico()` falla al abrir un VRT, revise
#   https://www.isric.org/explore/soilgrids/faq-soilgrids en un
#   navegador y ajuste `_URL_SOILGRIDS_VRT` abajo.
#
#   CRS: SoilGrids se distribuye en la proyección Homolosine
#   interrumpida de Goode (no WGS84) -- se asume que el VRT trae su
#   propia georreferenciación embebida (como cualquier COG bien
#   formado) y que `gdal:cliprasterbymasklayer` la reproyecta
#   correctamente al recortar contra la máscara de la cuenca (mismo
#   mecanismo que ya usa `obtener_lulc_esa_worldcover_recortado`).
#
#   ESCALA DE LOS VALORES: SoilGrids expresa arcilla/arena/limo en
#   g/kg × 10 (es decir, valor de píxel / 10 = %) -- se aplica esa
#   conversión aquí. Verifique contra la documentación de ISRIC si el
#   resultado da porcentajes que no cuadran (p.ej. muy por encima de
#   100%, señal de que el factor de escala cambió).
_URL_SOILGRIDS_VRT = "https://files.isric.org/soilgrids/latest/data/{propiedad}/{propiedad}_{profundidad}_mean.vrt"
_PROFUNDIDADES_SOILGRIDS_0_30CM = (("0-5cm", 5.0), ("5-15cm", 10.0), ("15-30cm", 15.0))  # (etiqueta, espesor_cm)


def obtener_propiedad_suelo_soilgrids_recortada(propiedad: str, profundidad: str, cuenca_layer,
                                                 context, feedback, destino_tif: Optional[str] = None,
                                                 usar_cache: bool = True) -> str:
    """Recorta UN mapa de SoilGrids (una propiedad -- "clay"/"sand" -- a
    una profundidad nativa -- "0-5cm"/"5-15cm"/"15-30cm") a la cuenca,
    leyendo el VRT remoto vía /vsicurl/ (sin descargar el mosaico
    global). Ver la nota de transparencia arriba. `usar_cache`: ver
    `obtener_lulc_esa_worldcover_recortado()`."""
    url = _URL_SOILGRIDS_VRT.format(propiedad=propiedad, profundidad=profundidad)
    bbox = _bbox_wgs84_de_capa(cuenca_layer)
    if usar_cache and destino_tif is None:
        destino_tif = _ruta_cache(f"soilgrids_{propiedad}_{profundidad}", bbox)
        if os.path.isfile(destino_tif) and os.path.getsize(destino_tif) > 0:
            return destino_tif
    import processing
    if destino_tif is None:
        destino_tif = os.path.join(
            tempfile.gettempdir(), f"hydroandina_soilgrids_{propiedad}_{profundidad}.tif")
    resultado = processing.run(
        "gdal:cliprasterbymasklayer",
        {
            "INPUT": f"/vsicurl/{url}", "MASK": cuenca_layer, "SOURCE_CRS": None, "TARGET_CRS": None,
            "NODATA": None, "ALPHA_BAND": False, "CROP_TO_CUTLINE": True,
            "KEEP_RESOLUTION": True, "OUTPUT": destino_tif,
        },
        context=context, feedback=feedback, is_child_algorithm=True,
    )
    ruta_out = resultado.get("OUTPUT")
    if not ruta_out:
        raise LandcoverSoilsError(
            f"No se pudo recortar SoilGrids ({propiedad}, {profundidad}) a la cuenca -- verifique "
            f"conectividad a {url} (ver nota de transparencia en core/landcover_soils.py)."
        )
    return ruta_out


def _promedio_ponderado_0_30cm(propiedad: str, cuenca_layer, context, feedback) -> np.ndarray:
    """Recorta los 3 intervalos nativos de SoilGrids (0-5, 5-15, 15-30
    cm) de `propiedad` y devuelve el array 0-30 cm ponderado por
    espesor, ya en % (valor de píxel SoilGrids / 10, ver nota de
    transparencia arriba)."""
    if gdal is None:
        raise LandcoverSoilsError(
            "No se encontraron los bindings de Python de GDAL (osgeo.gdal), necesarios para "
            "combinar los intervalos de profundidad de SoilGrids."
        )
    arrays_y_pesos = []
    forma_referencia = None
    for etiqueta_profundidad, espesor_cm in _PROFUNDIDADES_SOILGRIDS_0_30CM:
        ruta = obtener_propiedad_suelo_soilgrids_recortada(propiedad, etiqueta_profundidad, cuenca_layer,
                                                            context, feedback)
        ds = gdal.Open(ruta)
        if ds is None:
            raise LandcoverSoilsError(f"No se pudo abrir el recorte de SoilGrids {ruta}.")
        arr = ds.GetRasterBand(1).ReadAsArray().astype(np.float64)
        if forma_referencia is None:
            forma_referencia = arr.shape
            geotransform, proyeccion = ds.GetGeoTransform(), ds.GetProjection()
        elif arr.shape != forma_referencia:
            raise LandcoverSoilsError(
                f"Los 3 intervalos de profundidad de SoilGrids ({propiedad}) no coinciden en "
                f"tamaño de grilla ({arr.shape} vs {forma_referencia}) -- inusual, revise que el "
                f"recorte se haya hecho con la misma extensión en los 3 casos."
            )
        arrays_y_pesos.append((arr, espesor_cm))

    espesor_total_cm = sum(e for _, e in arrays_y_pesos)
    suma_ponderada = sum(arr * e for arr, e in arrays_y_pesos)
    valor_pct = (suma_ponderada / espesor_total_cm) / 10.0  # g/kg*10 -> % (ver nota de transparencia)
    return valor_pct, geotransform, proyeccion


def obtener_hsg_soilgrids_automatico(cuenca_layer, context, feedback,
                                      destino_tif: Optional[str] = None) -> str:
    """Deriva el HSG (A/B/C/D) 100% AUTÓNOMO -- sin que el usuario
    aporte ningún ráster propio -- descargando/recortando arcilla y
    arena de SoilGrids (0-30 cm, promedio ponderado de los 3
    intervalos nativos), clasificando textura USDA + HSG píxel a píxel
    (core/pedotransfer_soilgrids.py) y escribiendo el resultado como
    un GeoTIFF de códigos 1-4 (mismo convenio que
    `obtener_hsg_recortado()`, así que es un reemplazo DIRECTO de esa
    función en `calcular_cn_ponderado_automatico()`)."""
    if gdal is None:
        raise LandcoverSoilsError(
            "No se encontraron los bindings de Python de GDAL (osgeo.gdal), necesarios para "
            "escribir el ráster de HSG resultante."
        )
    from . import pedotransfer_soilgrids as pedo

    arena_pct, geotransform, proyeccion = _promedio_ponderado_0_30cm("sand", cuenca_layer, context, feedback)
    arcilla_pct, _, _ = _promedio_ponderado_0_30cm("clay", cuenca_layer, context, feedback)
    if arena_pct.shape != arcilla_pct.shape:
        raise LandcoverSoilsError(
            f"Los recortes de arena ({arena_pct.shape}) y arcilla ({arcilla_pct.shape}) de "
            f"SoilGrids no coinciden en tamaño de grilla -- inusual, revise la extensión del recorte."
        )

    hsg_arr = pedo.clasificar_hsg_raster(arena_pct, arcilla_pct)

    if destino_tif is None:
        destino_tif = os.path.join(tempfile.gettempdir(), "hydroandina_hsg_soilgrids.tif")
    driver = gdal.GetDriverByName("GTiff")
    out_ds = driver.Create(destino_tif, hsg_arr.shape[1], hsg_arr.shape[0], 1, gdal.GDT_Byte)
    out_ds.SetGeoTransform(geotransform)
    out_ds.SetProjection(proyeccion)
    out_band = out_ds.GetRasterBand(1)
    out_band.WriteArray(hsg_arr)
    out_band.SetNoDataValue(0)
    out_ds.FlushCache()
    out_ds = None
    return destino_tif


# ---------------------------------------------------------------------
# C) Cruce LULC x HSG -> CN ponderado
# ---------------------------------------------------------------------
def _arrays_lulc_hsg_resampleados(lulc_clip_path: str, hsg_clip_path: str):
    """Abre LULC y HSG (ya recortados a la cuenca, posiblemente en
    grillas/resoluciones distintas), remuestrea HSG (categórico,
    vecino más cercano) a la grilla EXACTA de LULC, y devuelve
    (lulc_array, hsg_array, geotransform, proyección, área_pixel_m2)
    -- compartido entre calcular_cn_ponderado_automatico() (agregación
    a escalar) y generar_raster_cn() (ráster de CN por píxel)."""
    if gdal is None:
        raise LandcoverSoilsError(
            "No se encontraron los bindings de Python de GDAL (osgeo.gdal), necesarios para "
            "cruzar los rásters de LULC y HSG. Esto es inusual en una instalación estándar de "
            "QGIS; verifique la instalación."
        )
    ds_lulc = gdal.Open(lulc_clip_path)
    if ds_lulc is None:
        raise LandcoverSoilsError(f"No se pudo abrir el ráster de LULC recortado: {lulc_clip_path}")

    ancho, alto = ds_lulc.RasterXSize, ds_lulc.RasterYSize
    gt = ds_lulc.GetGeoTransform()
    proj = ds_lulc.GetProjection()
    pixel_area_m2 = abs(gt[1] * gt[5])

    lulc_array = ds_lulc.GetRasterBand(1).ReadAsArray()

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
    return lulc_array, hsg_array, gt, proj, pixel_area_m2


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
    mapeo_codigo_hsg = mapeo_codigo_hsg or {1: "A", 2: "B", 3: "C", 4: "D"}
    tabla_cn = tabla_cn or cargar_matriz_cn()

    lulc_array, hsg_array, gt, proj, pixel_area_m2 = _arrays_lulc_hsg_resampleados(
        lulc_clip_path, hsg_clip_path)

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


def generar_raster_cn(lulc_clip_path: str, hsg_clip_path: str,
                       mapeo_codigo_hsg: Optional[Dict[int, str]] = None,
                       tabla_cn: Optional[Dict[int, dict]] = None,
                       destino_tif: Optional[str] = None) -> str:
    """Genera un ráster ESPACIAL de Número de Curva (CN-II) por píxel,
    combinando LULC + HSG mediante lookup vectorizado en `tabla_cn`
    (misma tabla que usa calcular_cn_ponderado_automatico -- por
    defecto la matriz CN cargada de resources/cn_matriz_lulc.json).
    A diferencia de calcular_cn_ponderado_automatico() (que solo
    devuelve un promedio ponderado escalar), esta función escribe un
    GeoTIFF con la MISMA grilla/georreferenciación que `lulc_clip_path`,
    apto para estilizar como mapa temático (ver core/map_styling.py).

    Devuelve la ruta del GeoTIFF escrito (`destino_tif`, o un archivo
    temporal si no se indica)."""
    if gdal is None:
        raise LandcoverSoilsError(
            "GDAL no está disponible en este entorno; no se puede generar el ráster de CN.")

    mapeo_codigo_hsg = mapeo_codigo_hsg or {1: "A", 2: "B", 3: "C", 4: "D"}
    tabla_cn = tabla_cn or cargar_matriz_cn()
    lulc_array, hsg_array, gt, proj, _pixel_area_m2 = _arrays_lulc_hsg_resampleados(
        lulc_clip_path, hsg_clip_path)

    cn_array = np.full(lulc_array.shape, -9999.0, dtype=np.float32)
    for codigo_lulc, fila_cn in tabla_cn.items():
        for codigo_hsg, letra_hsg in mapeo_codigo_hsg.items():
            clave_cn = f"cn_{letra_hsg.lower()}"
            if clave_cn not in fila_cn:
                continue
            mascara = (lulc_array == codigo_lulc) & (hsg_array == codigo_hsg)
            if np.any(mascara):
                cn_array[mascara] = float(fila_cn[clave_cn])

    if destino_tif is None:
        destino_tif = os.path.join(
            tempfile.mkdtemp(prefix="hydroandes_cn_raster_"), "cn_ii_raster.tif")

    driver = gdal.GetDriverByName("GTiff")
    alto, ancho = cn_array.shape
    ds_salida = driver.Create(destino_tif, ancho, alto, 1, gdal.GDT_Float32)
    ds_salida.SetGeoTransform(gt)
    ds_salida.SetProjection(proj)
    banda_salida = ds_salida.GetRasterBand(1)
    banda_salida.WriteArray(cn_array)
    banda_salida.SetNoDataValue(-9999.0)
    banda_salida.FlushCache()
    ds_salida = None

    return destino_tif
