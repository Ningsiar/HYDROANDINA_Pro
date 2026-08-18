# -*- coding: utf-8 -*-
"""
core/etp_methods.py

Métodos de cálculo de la evapotranspiración potencial (ETP) reproducidos
del Manual Técnico de RS MINERVE (CREALP/HydroCosmos, v2.25, abril 2020),
sección "Complementary calculations for the Potential Evapotranspiration
(ETP)" (ecuaciones A.9 a A.18).

TRANSPARENCIA: Turc y McGuinness-Bordne requieren la radiación global Rg,
que en RS MINERVE se obtiene de la malla NASA SSE (Surface meteorological
and Solar Energy). Este plugin no tiene acceso a esa malla, así que Rg se
ingresa manualmente (constante mensual, tal como la describe el propio
manual: "these data are regional averages, not point data"). Oudin es el
único método que no requiere ningún dato externo (solo latitud y fecha),
ya que calcula la radiación extraterrestre Re analíticamente.
"""
import math
from datetime import date
from typing import Optional


class EtpError(Exception):
    pass


def dia_juliano(anio: int, mes: int, dia: int = 15) -> int:
    """Día del año (1-365/366), usado por Oudin y por el coeficiente
    grado-día estacional de Snow-SD/GSM/SOCONT. Si no se conoce el día
    exacto (series mensuales), se usa el día 15 del mes como
    representativo del paso."""
    try:
        return date(anio, mes, min(dia, 28) if mes == 2 else dia).timetuple().tm_yday
    except ValueError:
        return date(anio, mes, 15).timetuple().tm_yday


# ============================================================================
# a) TURC (1955, 1961) -- ecuación A.9-A.10
# ============================================================================

def turc(t_c: float, rg_kwh_m2_dia: float, mes: int, coeff_etp: float = 1.0) -> float:
    """ETP (mm/mes) según Turc. Rg debe darse en kWh/m²/día (como en la
    malla NASA SSE); se convierte internamente a cal/cm²/día
    (1 kWh/m² = 86.0421 cal/cm²)."""
    if t_c <= 0:
        return 0.0
    rg_cal_cm2_dia = rg_kwh_m2_dia * 86.0421
    k = 0.37 if mes == 2 else 0.40
    return coeff_etp * k * (t_c / (t_c + 15.0)) * (rg_cal_cm2_dia + 50.0)


# ============================================================================
# b) McGUINNESS Y BORDNE (1972) -- ecuación A.11
# ============================================================================

def mcguinness_bordne(t_c: float, rg_kwh_m2_dia: float, coeff_etp: float = 1.0) -> float:
    """ETP (mm/día) según McGuinness-Bordne. Rg en kWh/m²/día, convertido
    a MJ/m²/día (1 kWh = 3.6 MJ). rho=1000 kg/m3, lambda=2.26 MJ/kg."""
    if t_c <= -5:
        return 0.0
    rg_mj_m2_dia = rg_kwh_m2_dia * 3.6
    rho, lam = 1000.0, 2.26
    etp_m_d = coeff_etp * (rg_mj_m2_dia / (rho * lam)) * ((t_c + 5.0) / 68.0)
    return etp_m_d * 1000.0  # m/d -> mm/d


# ============================================================================
# c) OUDIN (2004) -- ecuaciones A.12-A.17
# ============================================================================

def _radiacion_extraterrestre(latitud_grados: float, jd: int) -> float:
    """Re (MJ/m²/día), ecuaciones A.13 a A.16."""
    lat_rad = math.radians(latitud_grados)
    dr = 1 + 0.033 * math.cos(2 * math.pi * jd / 365.0)
    decl = 0.409 * math.sin(2 * math.pi * jd / 365.0 - 1.39)
    cos_ws = -math.tan(lat_rad) * math.tan(decl)
    cos_ws = min(max(cos_ws, -1.0), 1.0)  # evita error de dominio en latitudes altas
    ws = math.acos(cos_ws)
    re = 37.6 * dr * (ws * math.sin(lat_rad) * math.sin(decl) + math.sin(ws) * math.cos(lat_rad) * math.cos(decl))
    return max(re, 0.0)


def oudin(t_c: float, latitud_grados: float, anio: int, mes: int, dia: int = 15,
          coeff_etp: float = 1.0) -> float:
    """ETP (mm/día) según Oudin (2004). Único método que no requiere Rg
    externo: calcula la radiación extraterrestre Re analíticamente a
    partir de la latitud y la fecha."""
    if t_c <= -5:
        return 0.0
    jd = dia_juliano(anio, mes, dia)
    re = _radiacion_extraterrestre(latitud_grados, jd)
    rho, lam = 1000.0, 2.26
    etp_m_d = coeff_etp * (re / (rho * lam)) * ((t_c + 5.0) / 100.0)
    return etp_m_d * 1000.0  # m/d -> mm/d


# ============================================================================
# d) ETP UNIFORME -- ecuación A.18
# ============================================================================

def etp_uniforme(valor_mm_dia: float, coeff_etp: float = 1.0) -> float:
    return coeff_etp * valor_mm_dia
