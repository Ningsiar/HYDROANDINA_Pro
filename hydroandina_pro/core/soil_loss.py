# -*- coding: utf-8 -*-
"""
core/soil_loss.py

Motor de cálculo de la Ecuación Universal de Pérdida de Suelo (USLE) y su
revisión RUSLE:

    A = R · K · LS · C · P

A: pérdida de suelo (t/ha/año). R: erosividad de la lluvia
(MJ·mm/(ha·h·año)). K: erosionabilidad del suelo (t·ha·h/(ha·MJ·mm)).
LS: factor topográfico (adimensional). C: factor de cobertura vegetal
(adimensional, 0-1). P: factor de prácticas de conservación
(adimensional, 0-1).

FÓRMULAS Y FUENTES:

  FACTOR R (erosividad de la lluvia)
  -----------------------------------
  Wischmeier & Smith (1978), fórmula directa de precipitación anual para
  climas húmedos (sin datos de pluviógrafo para EI30):
      R = 0.0483 * P_anual^1.61   (P en mm, R en MJ·mm/(ha·h·año))

  Arnoldus (1980) / Índice de Fournier Modificado (IFM), muy usado en
  Latinoamérica cuando solo se dispone de precipitación MENSUAL:
      IFM = Σ(Pi²) / P_anual   (Pi = precipitación de cada mes)
      R = 4.17 * IFM - 152

  FACTOR K (erosionabilidad del suelo) -- nomograma de Wischmeier & Smith:
      100*K_US = 2.1e-4 * M^1.14 * (12-a) + 3.25*(b-2) + 2.5*(c-3)
      M = (%limo + %arena_muy_fina) * (100 - %arcilla)
      a: % materia orgánica; b: código de estructura (1=granular muy
      fina .. 4=bloques/laminar/masiva); c: código de permeabilidad
      (1=rápida .. 6=muy lenta). K_US en ton·acre·h/(acre·pie-tonf·pulg);
      se convierte a SI multiplicando por 0.1317.

  FACTOR LS (topográfico)
  ------------------------
  Wischmeier-Smith / McCool et al. (1987, RUSLE), con exponente m
  continuo según la pendiente (McCool):
      β = (sinθ/0.0896) / (3·sinθ^0.8 + 0.56)
      m = β/(1+β)
      L = (λ/22.13)^m         (λ = longitud de la pendiente, m)
      S = 65.41·sin²θ + 4.56·sinθ + 0.065
      LS = L·S

  Moore & Burch (1986), versión "espacializable" con Área de Contribución
  Específica (As, m²/m) en vez de longitud de pendiente -- la que se usa
  para el ráster de LS a partir de la acumulación de flujo del MDE:
      LS = (As/22.13)^0.4 · (sinθ/0.0896)^1.3

  FACTOR C (cobertura vegetal)
  ------------------------------
  Tabla de valores típicos por tipo de cobertura (Wischmeier & Smith;
  Morgan, "Soil Erosion and Conservation"), o estimación espacial a
  partir de NDVI satelital (Van der Knijff et al., 2000, JRC European
  Soil Erosion Risk Assessment):
      C = exp(-alpha * NDVI / (beta - NDVI))   (alpha=2.0, beta=1.0 típicos)

  FACTOR P (prácticas de conservación)
  ---------------------------------------
  Tabla de valores típicos por práctica (Wischmeier & Smith).

  CLASIFICACIÓN DE LA SEVERIDAD DE EROSIÓN
  ------------------------------------------
  Rangos aproximados de uso común en estudios de conservación de suelos
  en Latinoamérica (FAO/PNUMA): <10 ligera/tolerable, 10-50 moderada,
  50-200 alta, 200-400 muy alta, >400 t/ha/año severa/crítica.

TRANSPARENCIA: USLE/RUSLE es el método indirecto más reproducido a nivel
mundial, pero cada factor tiene varias formulaciones regionales
alternativas en la bibliografía (el R de Fournier, en particular, se
calibra con coeficientes distintos según la región); verifique contra
los valores de referencia de su institución antes de un diseño
definitivo, y trate el resultado como una ESTIMACIÓN.
"""
import math
import os
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

G = 9.81


class SoilLossError(Exception):
    pass


# ============================================================================
# 1) FACTOR R -- EROSIVIDAD DE LA LLUVIA
# ============================================================================

def r_wischmeier_smith(p_anual_mm: float) -> float:
    """R = 0.0483*P^1.61 (Wischmeier & Smith 1978, climas húmedos, sin EI30)."""
    if p_anual_mm <= 0:
        raise SoilLossError("La precipitación anual debe ser mayor que cero.")
    return 0.0483 * p_anual_mm ** 1.61


def r_arnoldus_fournier(precip_mensual_mm: Sequence[float]) -> Dict:
    """IFM (Índice de Fournier Modificado) y R = 4.17*IFM - 152 (Arnoldus, 1980)."""
    valores = list(precip_mensual_mm)
    if len(valores) != 12:
        raise SoilLossError("Se requieren exactamente 12 valores de precipitación mensual.")
    p_anual = sum(valores)
    if p_anual <= 0:
        raise SoilLossError("La precipitación anual (suma de los 12 meses) debe ser mayor que cero.")
    ifm = sum(p ** 2 for p in valores) / p_anual
    r = max(4.17 * ifm - 152, 0.0)
    return {"IFM": ifm, "R": r, "P_anual_mm": p_anual}


# ============================================================================
# 2) FACTOR K -- EROSIONABILIDAD DEL SUELO (nomograma de Wischmeier-Smith)
# ============================================================================

def k_wischmeier_nomograma(pct_limo_mas_arena_muy_fina: float, pct_arcilla: float,
                            pct_materia_organica: float, codigo_estructura: int,
                            codigo_permeabilidad: int) -> Dict:
    """codigo_estructura: 1=granular muy fina, 2=granular fina, 3=granular
    media/gruesa, 4=bloques/laminar/masiva. codigo_permeabilidad: 1=rápida
    .. 6=muy lenta. Devuelve K en unidades US y en SI (t·ha·h/(ha·MJ·mm))."""
    if not (1 <= codigo_estructura <= 4):
        raise SoilLossError("El código de estructura debe estar entre 1 y 4.")
    if not (1 <= codigo_permeabilidad <= 6):
        raise SoilLossError("El código de permeabilidad debe estar entre 1 y 6.")
    m = pct_limo_mas_arena_muy_fina * (100 - pct_arcilla)
    a = pct_materia_organica
    b = codigo_estructura
    c = codigo_permeabilidad
    k_us_x100 = 2.1e-4 * (m ** 1.14) * (12 - a) + 3.25 * (b - 2) + 2.5 * (c - 3)
    k_us = k_us_x100 / 100.0
    k_si = k_us * 0.1317
    return {"M": m, "K_US": k_us, "K_SI": k_si}


# ============================================================================
# 3) FACTOR LS -- TOPOGRÁFICO
# ============================================================================

def ls_wischmeier_mccool(longitud_pendiente_m: float, pendiente_pct: float) -> Dict:
    if longitud_pendiente_m <= 0:
        raise SoilLossError("La longitud de la pendiente debe ser mayor que cero.")
    theta = math.atan(pendiente_pct / 100.0)
    sin_t = math.sin(theta)
    beta = (sin_t / 0.0896) / (3 * sin_t ** 0.8 + 0.56)
    m = beta / (1 + beta)
    l_factor = (longitud_pendiente_m / 22.13) ** m
    s_factor = 65.41 * sin_t ** 2 + 4.56 * sin_t + 0.065
    return {"m_exponente": m, "L": l_factor, "S": s_factor, "LS": l_factor * s_factor}


def ls_moore_burch(area_contrib_especifica_m2_m: float, pendiente_pct: float) -> float:
    """LS espacializable a partir del Área de Contribución Específica As
    (m²/m), típicamente derivada de la acumulación de flujo del MDE."""
    if area_contrib_especifica_m2_m < 0:
        raise SoilLossError("El área de contribución específica no puede ser negativa.")
    theta = math.atan(pendiente_pct / 100.0)
    return (area_contrib_especifica_m2_m / 22.13) ** 0.4 * (math.sin(theta) / 0.0896) ** 1.3


# ============================================================================
# 4) FACTOR C -- COBERTURA VEGETAL
# ============================================================================

TABLA_C_COBERTURA = {
    "Suelo desnudo / descubierto": 1.00,
    "Cultivo en limpio (maíz, papa, hortalizas)": 0.40,
    "Cultivo denso (cereales en cobertura completa)": 0.15,
    "Pastos degradados / sobrepastoreados": 0.10,
    "Pastos naturales densos": 0.02,
    "Matorral / arbustos ralos": 0.05,
    "Matorral denso": 0.02,
    "Bosque denso (cobertura >75%)": 0.001,
    "Bosque abierto / plantación forestal joven": 0.01,
    "Terrazas con cultivo": 0.20,
    "Área urbana / impermeabilizada": 0.01,
}


def c_desde_ndvi(ndvi: float, alpha: float = 2.0, beta: float = 1.0) -> float:
    """C = exp(-alpha*NDVI/(beta-NDVI)), Van der Knijff et al. (2000)."""
    if ndvi >= beta:
        raise SoilLossError("NDVI debe ser menor que el parámetro beta (típicamente 1.0).")
    return math.exp(-alpha * ndvi / (beta - ndvi))


# ============================================================================
# 5) FACTOR P -- PRÁCTICAS DE CONSERVACIÓN
# ============================================================================

TABLA_P_PRACTICAS = {
    "Sin práctica de conservación": 1.00,
    "Cultivo en contorno (pendiente 2-7%)": 0.50,
    "Cultivo en contorno (pendiente 8-12%)": 0.60,
    "Cultivo en contorno (pendiente 13-18%)": 0.80,
    "Fajas en contorno (strip cropping)": 0.30,
    "Terrazas de banco / absorción total": 0.10,
    "Terrazas con desagüe": 0.12,
    "Barreras vivas / zanjas de infiltración": 0.25,
}


# ============================================================================
# 6) PÉRDIDA DE SUELO Y CLASIFICACIÓN
# ============================================================================

def perdida_suelo(r: float, k: float, ls: float, c: float, p: float) -> float:
    return r * k * ls * c * p


_TABLA_CLASES_EROSION = [
    (10, "Ligera / tolerable"), (50, "Moderada"), (200, "Alta"),
    (400, "Muy alta"), (float("inf"), "Severa / crítica"),
]


def clasificar_erosion(a_t_ha_ano: float) -> str:
    for limite, nombre in _TABLA_CLASES_EROSION:
        if a_t_ha_ano < limite:
            return nombre
    return "Severa / crítica"


# ============================================================================
# 7) ESPACIALIZACIÓN SIG (ráster de pérdida de suelo A = R·K·LS·C·P)
# ============================================================================

def _leer_array_y_geotransform(ruta_raster: str):
    from osgeo import gdal
    ds = gdal.Open(ruta_raster)
    if ds is None:
        raise SoilLossError(f"No se pudo abrir el ráster: {ruta_raster}")
    banda = ds.GetRasterBand(1)
    nodata = banda.GetNoDataValue()
    arr = banda.ReadAsArray().astype("float64")
    gt = ds.GetGeoTransform()
    proj = ds.GetProjection()
    if nodata is not None:
        arr = np.where(arr == nodata, np.nan, arr)
    ds = None
    return arr, gt, proj, nodata


def _escribir_geotiff(ruta_salida: str, array: np.ndarray, geotransform, proyeccion, nodata=-9999.0):
    from osgeo import gdal
    driver = gdal.GetDriverByName("GTiff")
    filas, columnas = array.shape
    ds = driver.Create(ruta_salida, columnas, filas, 1, gdal.GDT_Float32)
    ds.SetGeoTransform(geotransform)
    ds.SetProjection(proyeccion)
    banda = ds.GetRasterBand(1)
    array_salida = np.where(np.isnan(array), nodata, array).astype("float32")
    banda.WriteArray(array_salida)
    banda.SetNoDataValue(nodata)
    banda.FlushCache()
    ds = None
    return ruta_salida


def preparar_ls_raster_moore_burch(dem_layer, umbral_acumulacion: int = 100,
                                    ruta_salida: Optional[str] = None,
                                    context=None, feedback=None) -> Dict:
    """Calcula el ráster de LS espacializado (Moore & Burch) a partir del
    MDE: pendiente (gdal:slope) + acumulación de flujo D8 (grass7:
    r.watershed, reutilizando core.delineation). El Área de Contribución
    Específica As se aproxima como |acumulación| (en celdas) · tamaño de
    celda (m), una simplificación estándar de la formulación de Desmet &
    Govers cuando no se dispone del ráster de acumulación ponderado por
    ancho de contorno exacto."""
    from . import delineation
    slope_path = delineation.calcular_pendiente(dem_layer, context=context, feedback=feedback)
    flujo = delineation.calcular_flujo(dem_layer, umbral_acumulacion=umbral_acumulacion,
                                       context=context, feedback=feedback)
    acumulacion_path = flujo["raster_acumulacion"]

    pendiente_pct, gt, proj, _ = _leer_array_y_geotransform(slope_path)
    acumulacion, _, _, _ = _leer_array_y_geotransform(acumulacion_path)

    tamano_celda_m = abs(gt[1])
    area_contrib_especifica = np.abs(acumulacion) * tamano_celda_m  # As en m²/m

    theta = np.arctan(pendiente_pct / 100.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        ls_array = (area_contrib_especifica / 22.13) ** 0.4 * (np.sin(theta) / 0.0896) ** 1.3
    ls_array = np.nan_to_num(ls_array, nan=0.0, posinf=0.0, neginf=0.0)

    if ruta_salida is None:
        import tempfile
        ruta_salida = os.path.join(tempfile.gettempdir(), "ls_moore_burch.tif")
    _escribir_geotiff(ruta_salida, ls_array, gt, proj)

    return {
        "ls_raster_path": ruta_salida, "slope_raster_path": slope_path,
        "acumulacion_raster_path": acumulacion_path, "tamano_celda_m": tamano_celda_m,
        "ls_promedio": float(np.nanmean(ls_array)), "ls_maximo": float(np.nanmax(ls_array)),
    }


def calcular_raster_perdida_suelo(ls_raster_path: str, r_valor: float, k_valor: float,
                                   c_valor: float, p_valor: float,
                                   ruta_salida: Optional[str] = None) -> Dict:
    """Combina el ráster de LS ya calculado con los factores R, K, C, P
    (escalares uniformes para toda la zona de estudio) en el ráster final
    de pérdida de suelo A = R·K·LS·C·P, y devuelve estadísticas zonales
    (media, máximo, y área por clase de severidad en hectáreas)."""
    ls_array, gt, proj, _ = _leer_array_y_geotransform(ls_raster_path)
    a_array = r_valor * k_valor * c_valor * p_valor * ls_array
    a_array = np.where(np.isnan(ls_array), np.nan, a_array)

    if ruta_salida is None:
        import tempfile
        ruta_salida = os.path.join(tempfile.gettempdir(), "perdida_suelo_usle.tif")
    _escribir_geotiff(ruta_salida, a_array, gt, proj)

    tamano_celda_m = abs(gt[1])
    area_celda_ha = (tamano_celda_m ** 2) / 10000.0
    validos = a_array[~np.isnan(a_array)]
    if validos.size == 0:
        raise SoilLossError("El ráster resultante no tiene celdas válidas.")

    area_por_clase_ha = {}
    limite_inferior = 0
    for limite_superior, nombre in _TABLA_CLASES_EROSION:
        n_celdas = int(np.sum((validos >= limite_inferior) & (validos < limite_superior)))
        area_por_clase_ha[nombre] = n_celdas * area_celda_ha
        limite_inferior = limite_superior

    return {
        "raster_path": ruta_salida,
        "media_t_ha_ano": float(np.mean(validos)),
        "maximo_t_ha_ano": float(np.max(validos)),
        "minimo_t_ha_ano": float(np.min(validos)),
        "area_total_ha": float(validos.size * area_celda_ha),
        "area_por_clase_ha": area_por_clase_ha,
    }
