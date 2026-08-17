# -*- coding: utf-8 -*-
"""
core/outlier_analysis.py

Prueba de outliers ALTOS y BAJOS de Grubbs y Beck (Grubbs & Beck,
1972), la que adoptó el USWRC Bulletin 17B (1982, "Guidelines for
Determining Flood Flow Frequency") como paso de control de calidad
previo/paralelo al ajuste de distribuciones de probabilidad en
análisis de frecuencia de crecidas y precipitación máxima -- se aplica
sobre la Pestaña 5 (Precipitación Máx 24h), ANTES de ajustar las 9
distribuciones, para señalar qué años de la serie se apartan tanto del
resto que conviene revisarlos (error de medición/digitación vs. un
evento real extremo) antes de confiar en el ajuste.

MÉTODO (test de una sola pasada, sobre log10 de la serie):
  1. logs = log10(valores)
  2. media_log = media(logs) ; s_log = desviación estándar muestral (n-1)
  3. Umbral alto:  X_H = media_log + Kn·s_log
     Umbral bajo:  X_L = media_log − Kn·s_log
  4. log10(x_i) > X_H  ->  outlier ALTO
     log10(x_i) < X_L  ->  outlier BAJO
  Se trabaja en log10 -- igual que Bulletin 17B -- sea cual sea la
  distribución que se vaya a ajustar después (el test de outliers es
  una prueba de control de calidad SEPARADA del ajuste final, no
  presupone Log-Pearson III).

VALOR CRÍTICO Kn -- CALCULADO ANALÍTICAMENTE, NO DESDE LA TABLA
IMPRESA. Bulletin 17B publicó Kn como una tabla (su Tabla I-3, al 10%
de significancia) calculada por Monte Carlo por Grubbs & Beck (1972).
Aquí se usa en su lugar la fórmula analítica estándar del valor
crítico UNILATERAL del residuo normalizado extremo (Grubbs, 1969;
documentada también en el NIST/SEMATECH e-Handbook of Statistical
Methods), con corrección de Bonferroni por las n comparaciones:

    Kn(n, α) = (n−1)/√n · √( t² / (n−2+t²) ) ,  t = t_{1−α/n, n−2}

donde t_{1−α/n, n−2} es el percentil (1−α/n) de la distribución t de
Student con (n−2) grados de libertad.

POR QUÉ FÓRMULA Y NO LA TABLA: se intentó extraer la tabla original de
Bulletin 17B (vía OCR de su reproducción en FHWA HDS-2, Tabla 4.21,
"Outlier Test Deviates (KN) at 10 Percent Significance Level") para
transcribirla, y el OCR resultó demostrablemente corrupto en al menos
un tramo -- p.ej. figuraba Kn(92) = 2.889, un valor MENOR que Kn(91) =
2.984, lo cual es imposible: Kn crece monótonamente con n. Ante el
riesgo de fijar un error de transcripción en un plugin de uso real, se
optó por la fórmula analítica, verificada aquí contra los valores
LIMPIOS de esa misma tabla (los que no mostraban anomalías de
monotonicidad): coincide hasta la 3ra-4ta cifra decimal para n≤50
(diferencia < 0.001) y diverge como máximo ~0.25% en n=120-140 -- sin
relevancia práctica frente a la incertidumbre propia de series
hidrológicas de esa longitud, y coherente con que Bulletin 17C (USGS,
2019) reemplazó la tabla fija por un cálculo numérico equivalente
(test de Grubbs-Beck múltiple, MGBT) por esta misma razón de
precisión/flexibilidad.

LIMITACIÓN DOCUMENTADA: se implementa el test de Grubbs-Beck de UNA
SOLA PASADA (no el procedimiento iterativo completo de Bulletin 17B,
que remueve los outliers detectados y reajusta media/desviación antes
de volver a probar, ni el ajuste por "datos históricos"/percepción
censurada) -- es la versión de referencia más usada como criterio de
detección; se documenta para quien necesite el procedimiento iterativo
completo.
"""
import math
from typing import List, Optional, Tuple

import numpy as np

try:
    from scipy import stats
except ImportError:                                  # pragma: sin cobertura
    stats = None


class OutlierAnalysisError(Exception):
    pass


def kn_grubbs_beck(n: int, alpha: float = 0.10) -> float:
    """Valor crítico Kn del test de outliers de Grubbs-Beck (fórmula
    analítica -- ver docstring del módulo)."""
    if stats is None:
        raise OutlierAnalysisError(
            "SciPy no está disponible en este entorno; no se puede calcular el valor crítico Kn.")
    if n < 10:
        raise OutlierAnalysisError(
            f"el test de Grubbs-Beck (Bulletin 17B) requiere al menos 10 datos; se recibieron {n}.")
    if not (0.0 < alpha < 1.0):
        raise OutlierAnalysisError("alpha debe estar estrictamente entre 0 y 1.")
    t = stats.t.ppf(1.0 - alpha / n, n - 2)
    return (n - 1) / math.sqrt(n) * math.sqrt(t ** 2 / (n - 2 + t ** 2))


def detectar_outliers_grubbs_beck(valores: List[float], anios: Optional[List[int]] = None,
                                   alpha: float = 0.10) -> dict:
    """Aplica el test de outliers altos/bajos de Grubbs-Beck a
    `valores` (p.ej. self.serie_precip_anual.valores_mm). `anios`,
    opcional, permite identificar cada outlier por su año en vez de
    solo por su índice en la lista."""
    valores = list(valores)
    n = len(valores)
    if n < 10:
        raise OutlierAnalysisError(
            f"se necesitan al menos 10 años de datos para el test de outliers de Bulletin 17B "
            f"(hay {n}).")
    if any(v <= 0 for v in valores):
        raise OutlierAnalysisError(
            "el test trabaja en log10 de los datos y requiere valores estrictamente positivos; "
            "revise la serie (¿hay ceros o negativos?).")
    if anios is not None and len(anios) != n:
        raise OutlierAnalysisError(
            f"anios ({len(anios)}) y valores ({n}) deben tener la misma longitud.")

    logs = np.log10(np.asarray(valores, dtype=float))
    media_log = float(np.mean(logs))
    s_log = float(np.std(logs, ddof=1))
    kn = kn_grubbs_beck(n, alpha)
    umbral_alto_log = media_log + kn * s_log
    umbral_bajo_log = media_log - kn * s_log
    umbral_alto_mm = 10.0 ** umbral_alto_log
    umbral_bajo_mm = 10.0 ** umbral_bajo_log

    detalle = []
    indices_altos: List[int] = []
    indices_bajos: List[int] = []
    for i, (v, lv) in enumerate(zip(valores, logs)):
        es_alto = bool(lv > umbral_alto_log)
        es_bajo = bool(lv < umbral_bajo_log)
        detalle.append({
            "indice": i, "anio": anios[i] if anios is not None else None,
            "valor_mm": v, "es_outlier_alto": es_alto, "es_outlier_bajo": es_bajo,
        })
        if es_alto:
            indices_altos.append(i)
        if es_bajo:
            indices_bajos.append(i)

    return {
        "n": n, "alpha": alpha, "kn": round(kn, 4),
        "media_log10": round(media_log, 5), "desv_est_log10": round(s_log, 5),
        "umbral_alto_mm": round(umbral_alto_mm, 2), "umbral_bajo_mm": round(umbral_bajo_mm, 2),
        "detalle": detalle,
        "indices_outliers_altos": indices_altos,
        "indices_outliers_bajos": indices_bajos,
        "hay_outliers": bool(indices_altos or indices_bajos),
    }


def serie_sin_outliers(valores: List[float], anios: Optional[List[int]],
                        resultado_deteccion: dict) -> Tuple[List[float], Optional[List[int]]]:
    """Devuelve (valores_filtrados, anios_filtrados) excluyendo los
    índices que `resultado_deteccion` (el dict que devuelve
    detectar_outliers_grubbs_beck) marcó como outlier alto o bajo."""
    excluir = (set(resultado_deteccion["indices_outliers_altos"])
               | set(resultado_deteccion["indices_outliers_bajos"]))
    valores_filtrados = [v for i, v in enumerate(valores) if i not in excluir]
    anios_filtrados = ([a for i, a in enumerate(anios) if i not in excluir]
                        if anios is not None else None)
    return valores_filtrados, anios_filtrados
