# -*- coding: utf-8 -*-
"""
core/gridded_validation.py

Validación de productos grillados de precipitación (satelitales: CHIRPS,
IMERG/GPM; o de reanálisis: ERA5-Land, PISCOp) frente a datos de
estaciones pluviométricas en tierra, mediante métricas de bondad de
ajuste continuas y de detección categórica de eventos de lluvia.

Complementa core/precip_source.py (que ahora, con
extraer_serie_diaria_desde_netcdf(), puede extraer la serie grillada en
el píxel de cualquier estación) y core/data_completion.py (que rellena
huecos ENTRE estaciones): este módulo responde la pregunta "¿qué tan
confiable es el dato grillado en el píxel de esta estación, para
sustituir o completar la serie observada donde no hay estación?".

MÉTRICAS CONTINUAS (magnitud del error):
  - NSE (Nash-Sutcliffe Efficiency)
  - KGE (Kling-Gupta Efficiency, con su descomposición r / alpha / beta)
  - PBIAS (sesgo porcentual), RMSE, MAE
  - R (correlación de Pearson), R²

MÉTRICAS CATEGÓRICAS (capacidad de DETECTAR el evento de lluvia, no solo
su magnitud -- crítico para alerta temprana de crecidas, donde importa
si el producto grillado "vio" o no la tormenta):
  - POD (Probability of Detection), FAR (False Alarm Ratio)
  - FBI (Frequency Bias Index), HSS (Heidke Skill Score)

FUENTES (deliberadamente no limitadas a bibliografía estadounidense o
europea, por instrucción del proyecto):
  - Nash, J.E.; Sutcliffe, J.V. (1970). "River flow forecasting through
    conceptual models". J. Hydrology, 10(3), 282-290. (NSE)
  - Gupta, H.V.; Kling, H.; Yilmaz, K.K.; Martinez, G.F. (2009).
    "Decomposition of the mean squared error and NSE performance
    criteria". J. Hydrology, 377(1-2), 80-91. (KGE)
  - Moriasi, D.N. et al. (2007). "Model evaluation guidelines for
    systematic quantification of accuracy in watershed simulations".
    Trans. ASABE, 50(3), 885-900. (bandas de calificación usadas en
    clasificar_desempeno())
  - Evaluación de GPM IMERG y CHIRPS contra estaciones meteorológicas en
    la península de Crimea (región de Europa del Este / Federación
    Rusa): ambos productos sobreestimaron sistemáticamente la
    precipitación medida en tierra (PBIAS positivo).
  - "Assessment of Satellite Precipitation Products in an Andean
    Catchment" (cuenca del río Ambato, Ecuador, 2025): compara CHIRPS e
    IMERG contra 6 pluviómetros automáticos 2014-2023 en un contexto
    andino -- la misma región geográfica de este proyecto -- usando
    exactamente las métricas continuas y categóricas implementadas aquí
    (POD/FAR/HSS + NSE/RMSE/PBIAS). Encontró que IMERG detecta mejor el
    evento de lluvia diario (POD más alto) mientras CHIRPS es más
    estable en periodos secos (FAR más bajo); ambos comportamientos son
    razonables de esperar en cuencas andinas similares.
"""
import math
from typing import Dict, List, Tuple

import numpy as np


class GriddedValidationError(Exception):
    pass


def _pares_validos(sim: List[float], obs: List[float]) -> Tuple[np.ndarray, np.ndarray]:
    s = np.asarray(sim, dtype=float)
    o = np.asarray(obs, dtype=float)
    if len(s) != len(o):
        raise GriddedValidationError("'sim' (grillado) y 'obs' (estación) deben tener la misma longitud.")
    validos = ~np.isnan(s) & ~np.isnan(o)
    return s[validos], o[validos]


def clasificar_desempeno(nse: float, pbias: float) -> str:
    """
    Clasificación cualitativa según las bandas de Moriasi et al. (2007)
    (desarrolladas originalmente para caudal simulado en cuencas, pero
    ampliamente adoptadas también para validar precipitación grillada
    frente a estaciones, p.ej. en el estudio de la cuenca del Ambato,
    Ecuador citado en el docstring del módulo).
    """
    if nse > 0.75 and abs(pbias) < 10:
        return "muy_bueno"
    if nse > 0.65 and abs(pbias) < 15:
        return "bueno"
    if nse > 0.50 and abs(pbias) < 25:
        return "satisfactorio"
    return "insatisfactorio"


def metricas_continuas(sim: List[float], obs: List[float]) -> dict:
    """
    Métricas continuas de bondad de ajuste entre una serie grillada
    (sim) y una serie observada en estación (obs), en pares completos
    (exclusión pareada de NaN, sin relleno de huecos -- mismo criterio
    que el estudio de la cuenca del Ambato, Ecuador, 2025).
    """
    s, o = _pares_validos(sim, obs)
    n = len(s)
    if n < 3:
        raise GriddedValidationError("Se requieren al menos 3 pares de datos válidos (sim, obs).")

    o_media = float(o.mean())
    error = s - o

    ss_res = float(np.sum(error ** 2))
    ss_tot = float(np.sum((o - o_media) ** 2))
    nse = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")

    rmse = float(math.sqrt(ss_res / n))
    mae = float(np.mean(np.abs(error)))
    pbias = float(100.0 * np.sum(error) / np.sum(o)) if np.sum(o) != 0 else float("nan")

    if np.std(s) > 0 and np.std(o) > 0:
        r = float(np.corrcoef(s, o)[0, 1])
    else:
        r = float("nan")

    # KGE (Gupta et al., 2009): componentes r (correlación), alpha
    # (variabilidad relativa), beta (sesgo relativo de la media)
    alpha = float(np.std(s) / np.std(o)) if np.std(o) > 0 else float("nan")
    beta = float(np.mean(s) / o_media) if o_media != 0 else float("nan")
    if any(math.isnan(v) for v in (r, alpha, beta)):
        kge = float("nan")
    else:
        kge = 1 - math.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)

    desempeno = clasificar_desempeno(nse, pbias) if not (math.isnan(nse) or math.isnan(pbias)) else None

    return {
        "n_pares": n,
        "NSE": round(nse, 4) if not math.isnan(nse) else None,
        "KGE": round(kge, 4) if not math.isnan(kge) else None,
        "KGE_r_correlacion": round(r, 4) if not math.isnan(r) else None,
        "KGE_alpha_variabilidad": round(alpha, 4) if not math.isnan(alpha) else None,
        "KGE_beta_sesgo": round(beta, 4) if not math.isnan(beta) else None,
        "PBIAS_pct": round(pbias, 2) if not math.isnan(pbias) else None,
        "RMSE": round(rmse, 3), "MAE": round(mae, 3),
        "R_pearson": round(r, 4) if not math.isnan(r) else None,
        "R2": round(r ** 2, 4) if not math.isnan(r) else None,
        "desempeno_moriasi_2007": desempeno,
    }


def metricas_categoricas_deteccion(sim: List[float], obs: List[float], umbral_mm: float = 1.0) -> dict:
    """
    Métricas de capacidad de DETECCIÓN de un día de lluvia (no de su
    magnitud), a partir de una tabla de contingencia 2x2 con el umbral
    dado (1.0 mm/día es el umbral estándar en la literatura de
    validación de productos satelitales, p.ej. el estudio de la cuenca
    del Ambato, Ecuador, 2025):

      - POD = aciertos / (aciertos + fallos)
      - FAR = falsas_alarmas / (aciertos + falsas_alarmas)
      - FBI = (aciertos + falsas_alarmas) / (aciertos + fallos)
      - HSS: habilidad categórica corregida por el acierto esperado al azar
    """
    s, o = _pares_validos(sim, obs)
    n = len(s)
    if n < 3:
        raise GriddedValidationError("Se requieren al menos 3 pares de datos válidos (sim, obs).")

    llueve_sim = s >= umbral_mm
    llueve_obs = o >= umbral_mm

    aciertos = int(np.sum(llueve_sim & llueve_obs))              # hits
    falsas_alarmas = int(np.sum(llueve_sim & ~llueve_obs))       # false alarms
    fallos = int(np.sum(~llueve_sim & llueve_obs))               # misses
    correctos_sin_lluvia = int(np.sum(~llueve_sim & ~llueve_obs))  # correct negatives

    pod = aciertos / (aciertos + fallos) if (aciertos + fallos) > 0 else float("nan")
    far = falsas_alarmas / (aciertos + falsas_alarmas) if (aciertos + falsas_alarmas) > 0 else float("nan")
    fbi = (aciertos + falsas_alarmas) / (aciertos + fallos) if (aciertos + fallos) > 0 else float("nan")

    esperado_azar = ((aciertos + fallos) * (aciertos + falsas_alarmas) +
                      (correctos_sin_lluvia + fallos) * (correctos_sin_lluvia + falsas_alarmas)) / n
    hss_den = aciertos + fallos + falsas_alarmas + correctos_sin_lluvia - esperado_azar
    hss = (aciertos + correctos_sin_lluvia - esperado_azar) / hss_den if hss_den != 0 else float("nan")

    return {
        "umbral_mm": umbral_mm, "n_pares": n,
        "tabla_contingencia": {"aciertos_hits": aciertos, "falsas_alarmas": falsas_alarmas,
                                "fallos_misses": fallos, "correctos_sin_lluvia": correctos_sin_lluvia},
        "POD": round(pod, 4) if not math.isnan(pod) else None,
        "FAR": round(far, 4) if not math.isnan(far) else None,
        "FBI": round(fbi, 4) if not math.isnan(fbi) else None,
        "HSS": round(hss, 4) if not math.isnan(hss) else None,
        "interpretacion": (
            "POD y HSS más cercanos a 1 = mejor detección del evento de lluvia; FAR más cercano a 0 = "
            "menos falsas alarmas; FBI=1 = frecuencia de días con lluvia bien representada (FBI>1: el "
            "grillado sobre-detecta lluvia; FBI<1: sub-detecta)."
        ),
    }


def validar_serie_gridded_vs_estacion(serie_gridded: List[float], serie_estacion: List[float],
                                       umbral_deteccion_mm: float = 1.0) -> dict:
    """Combina metricas_continuas() + metricas_categoricas_deteccion()
    para una estación, en un solo resultado -- listo para exportar a la
    tabla de validación de la interfaz o al reporte."""
    return {
        "metricas_continuas": metricas_continuas(serie_gridded, serie_estacion),
        "metricas_categoricas": metricas_categoricas_deteccion(serie_gridded, serie_estacion, umbral_deteccion_mm),
    }


def validar_red_estaciones(series_gridded: Dict[str, List[float]], series_estaciones: Dict[str, List[float]],
                            umbral_deteccion_mm: float = 1.0) -> dict:
    """
    Valida TODAS las estaciones de una red de una sola vez (mismas
    claves en ambos diccionarios), para construir la tabla/mapa de
    métricas por estación (p.ej. CC, RMSE, PBIAS por estación,
    representable luego como capa temática de la cuenca en QGIS -- ver
    core/report_generator.py y core/exporters.py para llevar esta salida
    a una capa vectorial exportable, en el mismo espíritu que la
    comparación multi-métrica por estación ya usada en el proyecto).

    Las estaciones para las que no se puede calcular la validación
    (p.ej. muy pocos pares válidos) se reportan en 'estaciones_con_error'
    en vez de interrumpir el cálculo de las demás.
    """
    faltantes = set(series_estaciones) - set(series_gridded)
    if faltantes:
        raise GriddedValidationError(f"No hay serie grillada para las estaciones: {sorted(faltantes)}")

    resultados, errores = {}, {}
    for nombre, serie_obs in series_estaciones.items():
        try:
            resultados[nombre] = validar_serie_gridded_vs_estacion(
                series_gridded[nombre], serie_obs, umbral_deteccion_mm
            )
        except GriddedValidationError as e:
            errores[nombre] = str(e)

    return {"resultados_por_estacion": resultados, "estaciones_con_error": errores}
