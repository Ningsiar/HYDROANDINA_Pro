# -*- coding: utf-8 -*-
"""
core/water_yield.py

Módulo de OFERTA HÍDRICA (disponibilidad de agua a largo plazo), en
contraste con el resto del plugin que se enfoca en CRECIDAS/caudales
máximos de diseño. Cubre 3 enfoques de complejidad creciente:

  1. Ecuación de Budyko/Fu: reparto de la precipitación media anual (o
     mensual) entre evapotranspiración real y escorrentía, en función
     únicamente del índice de aridez (PET/P). Método simple y muy
     verificado en la bibliografía (Fu, 1981; Zhang et al., 2004).

  2. Balance hídrico mensual simplificado (INSPIRADO en la estructura de
     GR2M — Mouelhi et al., 2006 — pero NO una réplica certificada de
     GR2M): modelo conceptual de 2 parámetros (capacidad del reservorio
     de producción X1, capacidad del reservorio de rutina/agotamiento
     X2) que genera una serie mensual de caudales a partir de P y ETP.
     TRANSPARENCIA: no se pudo verificar con certeza suficiente la
     formulación EXACTA de las funciones de intercambio subterráneo y
     los coeficientes internos del GR2M original publicado por
     Irstea/INRAE; esta es una adaptación simplificada de ESPÍRITU
     similar (reservorio de producción + reservorio de rutina con
     recesión exponencial), pensada como una primera aproximación, NO
     como sustituto de la implementación oficial de GR2M si necesita
     resultados certificados.

  3. Método de Lutz Scholz (estructura general): modelo de balance
     hídrico mensual desarrollado específicamente para cuencas de la
     sierra peruana (Scholz, 1980, cooperación técnica alemana
     GTZ/Plan Meris II, publicado en ANA/PLAN MERIS "Balance Hídrico
     Superficial del Perú"). Aquí se implementa la ESTRUCTURA GENERAL
     del modelo (precipitación efectiva, retención de la cuenca,
     coeficiente de agotamiento, generación del caudal mensual y curva
     de duración), pero los COEFICIENTES REGIONALES ESPECÍFICOS por
     zona del Perú que Scholz publicó en sus tablas originales NO se
     incluyen aquí (no se pudieron verificar con certeza suficiente sin
     acceso a la publicación original); el usuario debe suministrar sus
     propios coeficientes de retención (a) y agotamiento (b) — ya sea
     tomados de la publicación original de Scholz para su región, o
     calibrados contra caudales observados.

TRANSPARENCIA GENERAL: los modelos 2 y 3 son modelos CONCEPTUALES que
requieren calibración contra caudales observados para ser confiables;
sin calibración, sus resultados son solo orientativos.
"""
import math
from typing import List, Optional, Tuple

import numpy as np


class WaterYieldError(Exception):
    pass


# ---------------------------------------------------------------------
# 1) Budyko / Fu
# ---------------------------------------------------------------------
def balance_budyko_fu(precipitacion_mm: float, evapotranspiracion_potencial_mm: float, w: float = 2.6) -> dict:
    """
    Ecuación de Fu (1981) / Zhang et al. (2004), forma cerrada de la
    curva de Budyko:
        AET/P = 1 + PET/P - [1 + (PET/P)^w]^(1/w)
    w: parámetro de forma (controla qué tan rápido se acerca la curva a
       sus asíntotas; w≈2.6 es un valor de referencia típico para
       cuencas con cobertura vegetal mixta — ajústelo si tiene un valor
       calibrado localmente).
    """
    if precipitacion_mm <= 0 or evapotranspiracion_potencial_mm <= 0:
        raise WaterYieldError("P y PET deben ser mayores que 0.")
    indice_aridez = evapotranspiracion_potencial_mm / precipitacion_mm
    razon_aet = 1 + indice_aridez - (1 + indice_aridez ** w) ** (1.0 / w)
    aet = razon_aet * precipitacion_mm
    escorrentia = precipitacion_mm - aet
    return {
        "indice_aridez_PET_P": round(indice_aridez, 3),
        "AET_mm": round(aet, 1), "escorrentia_mm": round(escorrentia, 1),
        "coeficiente_escorrentia": round(escorrentia / precipitacion_mm, 3),
        "w_usado": w,
    }


# ---------------------------------------------------------------------
# 2) Balance mensual simplificado (inspirado en GR2M, ver docstring)
# ---------------------------------------------------------------------
def balance_mensual_simplificado(precipitacion_mensual_mm: List[float], etp_mensual_mm: List[float],
                                  x1_capacidad_produccion_mm: float = 200.0,
                                  x2_coeficiente_intercambio: float = 1.1,
                                  almacenamiento_inicial_frac: float = 0.5) -> dict:
    """
    Modelo conceptual mensual de 2 parámetros (ver advertencia de
    transparencia en el docstring del módulo). Reservorio de producción
    S (capacidad X1) genera escorrentía directa por exceso; un segundo
    reservorio de rutina R (con un coeficiente de intercambio/pérdida
    X2) amortigua y da forma a la escorrentía mensual generada.
    """
    p = np.asarray(precipitacion_mensual_mm, dtype=float)
    etp = np.asarray(etp_mensual_mm, dtype=float)
    if len(p) != len(etp):
        raise WaterYieldError("Las series de precipitación y ETP deben tener la misma longitud.")
    n = len(p)
    if n < 12:
        raise WaterYieldError("Se recomienda al menos 12 meses (1 año) de datos.")

    S = x1_capacidad_produccion_mm * almacenamiento_inicial_frac
    R = 60.0  # almacenamiento inicial del reservorio de rutina (mm), valor de arranque típico
    caudal_mensual, s_serie, r_serie = [], [], []

    for t in range(n):
        # Reservorio de producción: separa precipitación neta en infiltración vs. escorrentía directa
        if p[t] >= etp[t]:
            p_neta = p[t] - etp[t]
            tanh_arg = p_neta / x1_capacidad_produccion_mm
            S_nueva = (S + x1_capacidad_produccion_mm * math.tanh(tanh_arg)) / \
                      (1 + (S / x1_capacidad_produccion_mm) * math.tanh(tanh_arg))
            escorrentia_directa = p_neta - (S_nueva - S)
            S = S_nueva
        else:
            deficit = etp[t] - p[t]
            tanh_arg = deficit / x1_capacidad_produccion_mm
            S_nueva = S * (1 - math.tanh(tanh_arg)) / (1 + (1 - S / x1_capacidad_produccion_mm) * math.tanh(tanh_arg))
            escorrentia_directa = 0.0
            S = S_nueva

        # Reservorio de rutina: recesión exponencial + intercambio
        R = R + escorrentia_directa
        R = R / x2_coeficiente_intercambio if x2_coeficiente_intercambio > 0 else R
        caudal_generado = (R ** 2) / (R + 60.0)  # forma de recesión cuadrática, capacidad de referencia 60mm
        R = R - caudal_generado

        caudal_mensual.append(max(caudal_generado, 0.0))
        s_serie.append(S)
        r_serie.append(R)

    return {
        "caudal_mensual_mm": [round(v, 2) for v in caudal_mensual],
        "almacenamiento_produccion_mm": [round(v, 1) for v in s_serie],
        "almacenamiento_rutina_mm": [round(v, 1) for v in r_serie],
        "caudal_medio_mensual_mm": round(float(np.mean(caudal_mensual)), 2),
        "nota": (
            "Modelo conceptual simplificado INSPIRADO en la estructura de GR2M, NO una réplica "
            "certificada del modelo original; requiere calibración de X1 y X2 contra caudales "
            "observados antes de usarse para estudios de disponibilidad hídrica reales."
        ),
    }


# ---------------------------------------------------------------------
# 3) Lutz Scholz (estructura general, coeficientes a cargo del usuario)
# ---------------------------------------------------------------------
def balance_lutz_scholz(precipitacion_mensual_mm: List[float], etp_mensual_mm: List[float],
                         coeficiente_retencion_a: float, coeficiente_agotamiento_b: float,
                         area_km2: float, capacidad_retencion_cuenca_mm: float = 100.0) -> dict:
    """
    Estructura general del método de Scholz (1980) — ver advertencia de
    transparencia en el docstring del módulo sobre los coeficientes
    regionales.

    coeficiente_retencion_a: fracción de la precipitación mensual que
        pasa a formar parte de la retención de la cuenca (0-1). En la
        publicación original de Scholz se relaciona con la cobertura
        vegetal/geología de cada región del Perú.
    coeficiente_agotamiento_b: coeficiente de agotamiento del caudal
        base (recesión mensual, 0-1; b más cercano a 1 = agotamiento
        más lento/cuenca con mayor regulación natural).
    """
    p = np.asarray(precipitacion_mensual_mm, dtype=float)
    etp = np.asarray(etp_mensual_mm, dtype=float)
    if len(p) != len(etp):
        raise WaterYieldError("Las series de precipitación y ETP deben tener la misma longitud.")
    if not (0.0 <= coeficiente_retencion_a <= 1.0) or not (0.0 <= coeficiente_agotamiento_b <= 1.0):
        raise WaterYieldError("Los coeficientes a y b deben estar entre 0 y 1.")

    n = len(p)
    retencion = capacidad_retencion_cuenca_mm * 0.5  # arranque
    caudal_mensual_mm = []
    for t in range(n):
        precipitacion_efectiva = max(p[t] - etp[t], 0.0)
        aporte_retencion = precipitacion_efectiva * coeficiente_retencion_a
        retencion = min(retencion + aporte_retencion, capacidad_retencion_cuenca_mm)
        escorrentia_directa = precipitacion_efectiva * (1 - coeficiente_retencion_a)
        aporte_subterraneo = retencion * (1 - coeficiente_agotamiento_b)
        retencion -= aporte_subterraneo
        caudal_mensual_mm.append(escorrentia_directa + aporte_subterraneo)

    # Conversión de lámina mensual (mm) a caudal medio mensual (m3/s)
    segundos_por_mes = 30.44 * 86400.0
    caudal_m3s = [v / 1000.0 * area_km2 * 1e6 / segundos_por_mes for v in caudal_mensual_mm]

    curva_duracion = sorted(caudal_m3s, reverse=True)
    percentiles = [50, 75, 90]
    persistencias = {
        f"Q{p_}": round(float(np.percentile(caudal_m3s, 100 - p_)), 3) for p_ in percentiles
    }

    return {
        "caudal_mensual_m3s": [round(v, 3) for v in caudal_m3s],
        "caudal_medio_m3s": round(float(np.mean(caudal_m3s)), 3),
        "persistencia": persistencias,
        "curva_duracion_m3s": [round(v, 3) for v in curva_duracion],
        "nota": (
            "Estructura general del método de Scholz (1980); los coeficientes de retención (a) y "
            "agotamiento (b) usados fueron los ingresados por el usuario — NO son los valores "
            "regionales tabulados en la publicación original de ANA/PLAN MERIS 'Balance Hídrico "
            "Superficial del Perú', que no se pudieron verificar con certeza suficiente en este "
            "entorno. Calibre a y b contra caudales observados de su cuenca, o consulte la "
            "publicación original si su región ya tiene coeficientes tabulados."
        ),
    }
