# -*- coding: utf-8 -*-
"""
core/direct_discharge_methods.py

Fórmulas empíricas de estimación DIRECTA del caudal máximo (distintas de
los métodos de transformación lluvia-escorrentía con hidrograma unitario
ya implementados en core/unit_hydrographs.py): Témez, Mac Math y
Creager. Se usan típicamente como comparación/verificación cruzada del
caudal de diseño obtenido por SCS/Snyder/Clark.

FÓRMULAS Y FUENTES:

  MÉTODO DE TÉMEZ (fórmula racional modificada, Témez 1978): variante de
  la fórmula racional que incorpora un coeficiente de uniformidad K que
  corrige el caudal punta por la falta de simultaneidad de toda la
  cuenca al pico, en función del tiempo de concentración:
      K = 1 + (Tc^1.25) / (Tc^1.25 + 14)
      Q = (C * I * A) / 3.6 * K
  Q en m³/s, C coef. de escorrentía (0-1), I intensidad de lluvia de
  diseño para duración Tc (mm/h), A en km², Tc en horas.
  Fuente: Témez, J.R. (1978), "Cálculo Hidrometeorológico de Caudales
  Máximos en Pequeñas Cuencas Naturales"; ampliamente reproducida en
  manuales de drenaje vial de España y Latinoamérica (p.ej. instrucción
  5.2-IC de España, manuales de MTC/ANA Perú).

  MÉTODO DE MAC MATH (McMath, EE.UU., cuencas pequeñas/urbanas):
      Q = 0.0091 * C * I * A^0.8 * S^0.2
  Q en m³/s, C coef. de escorrentía (0-1), I intensidad (mm/h) para
  duración Tc, A en HECTÁREAS, S pendiente media del cauce (%).
  Fuente: fórmula clásica reproducida en múltiples manuales de
  hidrología aplicada (p.ej. Villón Béjar, "Hidrología").

  MÉTODO DE CREAGER (curva envolvente regional, Creager et al. 1945):
      Q = C * 1.303 * A^(0.936 * A^(-0.048))
  Q en m³/s, A en km², C coeficiente envolvente regional (adimensional;
  valores típicos citados en la bibliografía van de ~6-30 para cuencas
  con crecidas moderadas hasta 60-100 para las envolventes más extremas
  a nivel mundial — DEBE calibrarse/verificarse contra caudales
  máximos observados en la región, ya que es una curva envolvente, no
  una fórmula predictiva ajustada a un caso general).

TRANSPARENCIA: estas tres fórmulas son ampliamente reproducidas en la
bibliografía de hidrología aplicada de Latinoamérica, pero (como con
todos los métodos empíricos históricos de este plugin) los coeficientes
pueden variar ligeramente entre fuentes; verifique contra la referencia
que use su institución antes de un diseño definitivo.
"""
import math
from typing import Optional


class DirectDischargeError(Exception):
    pass


def caudal_temez(coef_escorrentia_c: float, intensidad_mm_h: float, area_km2: float, tc_horas: float) -> dict:
    if not (0.0 <= coef_escorrentia_c <= 1.0):
        raise DirectDischargeError("El coeficiente de escorrentía C debe estar entre 0 y 1.")
    if tc_horas <= 0:
        raise DirectDischargeError("Tc debe ser mayor que 0.")
    k = 1.0 + (tc_horas ** 1.25) / (tc_horas ** 1.25 + 14.0)
    q = (coef_escorrentia_c * intensidad_mm_h * area_km2) / 3.6 * k
    return {
        "metodo": "Témez (1978)", "Q_m3_s": round(q, 3), "coeficiente_uniformidad_K": round(k, 4),
        "C": coef_escorrentia_c, "I_mm_h": intensidad_mm_h, "A_km2": area_km2, "Tc_h": tc_horas,
    }


def caudal_mac_math(coef_escorrentia_c: float, intensidad_mm_h: float, area_km2: float, pendiente_pct: float) -> dict:
    if not (0.0 <= coef_escorrentia_c <= 1.0):
        raise DirectDischargeError("El coeficiente de escorrentía C debe estar entre 0 y 1.")
    if pendiente_pct <= 0:
        raise DirectDischargeError("La pendiente debe ser mayor que 0.")
    area_ha = area_km2 * 100.0
    q = 0.0091 * coef_escorrentia_c * intensidad_mm_h * (area_ha ** 0.8) * (pendiente_pct ** 0.2)
    return {
        "metodo": "Mac Math", "Q_m3_s": round(q, 3),
        "C": coef_escorrentia_c, "I_mm_h": intensidad_mm_h, "A_ha": round(area_ha, 2), "S_pct": pendiente_pct,
    }


def caudal_creager(area_km2: float, coeficiente_envolvente_c: float = 30.0) -> dict:
    if area_km2 <= 0:
        raise DirectDischargeError("El área debe ser mayor que 0.")
    exponente = 0.936 * (area_km2 ** -0.048)
    q = coeficiente_envolvente_c * 1.303 * (area_km2 ** exponente)
    return {
        "metodo": "Creager (envolvente regional)", "Q_m3_s": round(q, 3),
        "A_km2": area_km2, "C_envolvente": coeficiente_envolvente_c,
        "nota": (
            "Curva ENVOLVENTE regional: C debe calibrarse contra caudales máximos observados en la "
            "región (valores de referencia de la bibliografía: ~6-30 para crecidas moderadas, "
            "60-100 para envolventes mundiales extremas). Sin calibración local, este resultado es "
            "solo orientativo."
        ),
    }


def comparar_metodos_directos(coef_escorrentia_c: float, intensidad_mm_h: float, area_km2: float,
                               tc_horas: float, pendiente_cauce_pct: float,
                               coeficiente_creager: float = 30.0) -> dict:
    """Calcula los 3 métodos con los mismos datos de entrada, para
    comparar contra el caudal de diseño obtenido por SCS/Snyder/Clark
    (Pestaña 6)."""
    return {
        "temez": caudal_temez(coef_escorrentia_c, intensidad_mm_h, area_km2, tc_horas),
        "mac_math": caudal_mac_math(coef_escorrentia_c, intensidad_mm_h, area_km2, pendiente_cauce_pct),
        "creager": caudal_creager(area_km2, coeficiente_creager),
    }
