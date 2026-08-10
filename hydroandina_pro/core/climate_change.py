# -*- coding: utf-8 -*-
"""
core/climate_change.py

Módulo "Cambio Climático - Escenarios": marco de referencia CMIP6
(SSP-RCP, experimentos DECK) y las dos herramientas de cálculo
realmente aplicables dentro de un plugin de QGIS sin conexión directa
a ESGF: (1) aplicación de deltas de cambio climático a una serie base
observada (método "delta-change", el más usado en estudios de
disponibilidad hídrica cuando ya se cuenta con las anomalías de un
informe CMIP6/CORDEX), y (2) corrección de sesgo / escalamiento
estadístico de series de un modelo climático (global o regional)
contra observaciones locales.

TRANSPARENCIA IMPORTANTE: este módulo NO descarga ni procesa archivos
NetCDF de CMIP6/ESGF (eso requiere acceso a internet, librerías
pesadas -xarray/netCDF4- y volúmenes de datos fuera del alcance de un
plugin de escritorio). Lo que hace es: (a) documentar el marco SSP-RCP
y DECK como referencia rápida, y (b) aplicar los deltas/series que
USTED ya obtuvo de un informe CMIP6/CORDEX, de la plataforma del
IPCC WGI Interactive Atlas, o de un modelo regional, a su propia serie
histórica observada. Los valores de forzamiento radiativo de cada SSP
(2.6/4.5/7.0/8.5 W/m² hacia 2100) son la definición estándar del
escenario, no una proyección local.

FÓRMULAS:

  Delta-change multiplicativo (precipitación):
      P_futura(mes) = P_base(mes) * (1 + delta_%(mes)/100)

  Delta-change aditivo (temperatura):
      T_futura(mes) = T_base(mes) + delta_°C(mes)

  Escalamiento lineal (bias correction, Escalamiento Estadístico -
  ítem E del enunciado): factor de corrección mensual a partir del
  periodo histórico común entre observado y modelo:
      Precipitación (multiplicativo): FC(mes) = P_obs(mes)/P_modelo_hist(mes)
          P_futuro_corregido(mes) = P_modelo_futuro(mes) * FC(mes)
      Temperatura (aditivo): FC(mes) = T_obs(mes) - T_modelo_hist(mes)
          T_futuro_corregido(mes) = T_modelo_futuro(mes) + FC(mes)

  Mapeo de cuantiles empírico (quantile mapping), corrección de sesgo
  más robusta que el escalamiento lineal porque corrige toda la
  distribución (no solo la media): cada valor del modelo futuro se
  ubica en el percentil de la distribución histórica del MODELO, y se
  reemplaza por el valor del OBSERVADO en ese mismo percentil.
"""
import math
from typing import Dict, List, Sequence

import numpy as np

MESES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


class ClimateChangeError(Exception):
    pass


# ============================================================================
# 1) MARCO DE REFERENCIA CMIP6 (informativo)
# ============================================================================

ESCENARIOS_SSP_RCP = {
    "SSP1-2.6": {"forzamiento_w_m2_2100": 2.6,
                 "descripcion": "Sostenibilidad: desarrollo bajo en emisiones, forzamiento radiativo bajo."},
    "SSP2-4.5": {"forzamiento_w_m2_2100": 4.5,
                 "descripcion": "Camino intermedio: tendencias socioeconómicas históricas se mantienen."},
    "SSP3-7.0": {"forzamiento_w_m2_2100": 7.0,
                 "descripcion": "Rivalidad regional: desarrollo desigual, forzamiento medio-alto."},
    "SSP5-8.5": {"forzamiento_w_m2_2100": 8.5,
                 "descripcion": "Desarrollo basado en combustibles fósiles, forzamiento radiativo alto."},
}

EXPERIMENTOS_DECK = {
    "AMIP": "Atmósfera con temperatura del mar observada históricamente (1979-presente).",
    "piControl": "Control preindustrial: GEI constantes a niveles de 1850.",
    "1pctCO2": "Incremento abrupto del 1% anual en CO2 hasta cuadruplicar el valor inicial.",
    "abrupt-4xCO2": "Incremento instantáneo y cuádruple del CO2, para medir sensibilidad climática.",
}


def listar_escenarios() -> List[str]:
    return list(ESCENARIOS_SSP_RCP.keys())


# ============================================================================
# 2) MÉTODO DELTA-CHANGE
# ============================================================================

def aplicar_delta_precipitacion(p_base_mensual: Sequence[float], delta_pct_mensual: Sequence[float]) -> List[float]:
    """P_futura(mes) = P_base(mes)*(1+delta_%/100)."""
    if len(p_base_mensual) != 12 or len(delta_pct_mensual) != 12:
        raise ClimateChangeError("Se requieren 12 valores mensuales (base y delta).")
    return [pb * (1 + d / 100.0) for pb, d in zip(p_base_mensual, delta_pct_mensual)]


def aplicar_delta_temperatura(t_base_mensual: Sequence[float], delta_c_mensual: Sequence[float]) -> List[float]:
    """T_futura(mes) = T_base(mes) + delta_°C."""
    if len(t_base_mensual) != 12 or len(delta_c_mensual) != 12:
        raise ClimateChangeError("Se requieren 12 valores mensuales (base y delta).")
    return [tb + d for tb, d in zip(t_base_mensual, delta_c_mensual)]


def resumen_cambio_anual(serie_base: Sequence[float], serie_futura: Sequence[float], es_precipitacion: bool) -> Dict:
    base_anual = sum(serie_base)
    futura_anual = sum(serie_futura)
    if es_precipitacion:
        cambio = (futura_anual - base_anual) / base_anual * 100.0 if base_anual != 0 else float("nan")
        return {"base_anual": base_anual, "futura_anual": futura_anual, "cambio_pct": cambio}
    else:
        base_media = base_anual / 12.0
        futura_media = futura_anual / 12.0
        return {"base_media_anual": base_media, "futura_media_anual": futura_media,
                "cambio_absoluto": futura_media - base_media}


# ============================================================================
# 3) CORRECCIÓN DE SESGO / ESCALAMIENTO ESTADÍSTICO
# ============================================================================

def escalamiento_lineal_precipitacion(obs_mensual: Sequence[float], modelo_hist_mensual: Sequence[float],
                                       modelo_futuro_mensual: Sequence[float]) -> Dict:
    """FC(mes)=Obs/Modelo_hist (multiplicativo); aplica FC al modelo futuro."""
    if not (len(obs_mensual) == len(modelo_hist_mensual) == len(modelo_futuro_mensual) == 12):
        raise ClimateChangeError("Se requieren 12 valores mensuales en las 3 series.")
    factores = [o / m if m != 0 else 1.0 for o, m in zip(obs_mensual, modelo_hist_mensual)]
    corregida = [mf * fc for mf, fc in zip(modelo_futuro_mensual, factores)]
    return {"factores_correccion": factores, "serie_corregida": corregida}


def escalamiento_lineal_temperatura(obs_mensual: Sequence[float], modelo_hist_mensual: Sequence[float],
                                     modelo_futuro_mensual: Sequence[float]) -> Dict:
    """FC(mes)=Obs-Modelo_hist (aditivo); aplica FC al modelo futuro."""
    if not (len(obs_mensual) == len(modelo_hist_mensual) == len(modelo_futuro_mensual) == 12):
        raise ClimateChangeError("Se requieren 12 valores mensuales en las 3 series.")
    factores = [o - m for o, m in zip(obs_mensual, modelo_hist_mensual)]
    corregida = [mf + fc for mf, fc in zip(modelo_futuro_mensual, factores)]
    return {"factores_correccion": factores, "serie_corregida": corregida}


def mapeo_cuantiles(obs_serie: Sequence[float], modelo_hist_serie: Sequence[float],
                     modelo_futuro_serie: Sequence[float], n_percentiles: int = 100) -> Dict:
    """Corrección de sesgo por mapeo de cuantiles empírico: cada valor del
    modelo futuro se ubica en el percentil de la distribución histórica
    del MODELO, y se reemplaza por el valor del OBSERVADO en ese mismo
    percentil (interpolación lineal entre percentiles tabulados)."""
    obs = np.asarray(obs_serie, dtype=float)
    mod_hist = np.asarray(modelo_hist_serie, dtype=float)
    mod_fut = np.asarray(modelo_futuro_serie, dtype=float)
    if obs.size < 4 or mod_hist.size < 4 or mod_fut.size < 1:
        raise ClimateChangeError("Se requieren al menos 4 datos históricos (obs/modelo) para el mapeo de cuantiles.")
    percentiles = np.linspace(0, 100, n_percentiles + 1)
    cuantiles_obs = np.percentile(obs, percentiles)
    cuantiles_mod_hist = np.percentile(mod_hist, percentiles)
    # percentil de cada valor futuro dentro de la distribución histórica del modelo
    percentil_valor = np.interp(mod_fut, cuantiles_mod_hist, percentiles)
    corregida = np.interp(percentil_valor, percentiles, cuantiles_obs)
    return {"serie_corregida": corregida.tolist(), "percentiles": percentiles.tolist(),
            "cuantiles_obs": cuantiles_obs.tolist(), "cuantiles_modelo_hist": cuantiles_mod_hist.tolist()}
