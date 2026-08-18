# -*- coding: utf-8 -*-
"""
core/quality_control.py

Control de calidad y homogeneidad de series hidrometeorológicas (P24h
anual u otra serie temporal), previo al análisis de frecuencia de la
Pestaña 5: detección de puntos de cambio (Pettitt), tendencias
(Mann-Kendall + pendiente de Sen), y consistencia frente a una serie de
referencia (curva de doble masa).

FUENTES (métodos estándar de la literatura estadística/hidrológica,
implementados directamente de sus definiciones matemáticas, sin
depender de ninguna librería/plataforma de terceros):
  - Pettitt, A.N. (1979). "A non-parametric approach to the change-point
    problem". Journal of the Royal Statistical Society, Series C.
  - Mann, H.B. (1945) / Kendall, M.G. (1975). Prueba de tendencia no
    paramétrica de Mann-Kendall (con corrección por varianza para
    empates, Kendall 1975).
  - Sen, P.K. (1968). "Estimates of the regression coefficient based on
    Kendall's tau". Estimador de pendiente no paramétrico.
  - Curva de doble masa: técnica clásica de hidrología operativa (WMO,
    "Guide to Hydrological Practices") para verificar la consistencia de
    una estación frente a un patrón de referencia (usualmente el
    promedio de varias estaciones vecinas).
"""
import math
from typing import Dict, List, Optional, Tuple

import numpy as np


class QualityControlError(Exception):
    pass


# ---------------------------------------------------------------------
# Prueba de Pettitt (punto de cambio)
# ---------------------------------------------------------------------
def test_pettitt(serie: List[float]) -> dict:
    """
    Detecta el punto de cambio más probable en la media de la serie
    (sin asumir distribución), y evalúa su significancia mediante la
    aproximación asintótica de Pettitt (1979).

    Devuelve: {'indice_cambio', 'anio_o_posicion_1_indexado', 'U_max',
               'p_valor_aprox', 'es_significativo' (alpha=0.05),
               'media_antes', 'media_despues'}
    """
    x = np.asarray(serie, dtype=float)
    n = len(x)
    if n < 4:
        raise QualityControlError("Se requieren al menos 4 datos para la prueba de Pettitt.")

    # U_t = suma de signos de (x_i - x_j) para i<=t, j>t
    # Cálculo eficiente O(n^2) vía rangos (suficiente para series anuales, n < unos pocos miles)
    signos = np.sign(x[:, None] - x[None, :])  # matriz n x n
    U = np.array([signos[:t, t:].sum() for t in range(1, n)])
    k = int(np.argmax(np.abs(U)))
    U_max = float(U[k])
    t_cambio = k + 1  # posición 1-indexada: el cambio ocurre ENTRE el dato t_cambio y el siguiente

    # p-valor aproximado (Pettitt, 1979), válido para |U_max| grande
    p_valor = 2.0 * math.exp((-6.0 * U_max ** 2) / (n ** 3 + n ** 2))
    p_valor = min(max(p_valor, 0.0), 1.0)

    return {
        "indice_cambio": t_cambio,
        "U_max": round(U_max, 2),
        "p_valor_aprox": round(p_valor, 4),
        "es_significativo_alpha_0_05": p_valor < 0.05,
        "media_antes": round(float(np.mean(x[:t_cambio])), 3),
        "media_despues": round(float(np.mean(x[t_cambio:])), 3),
        "interpretacion": (
            f"Posible quiebre de homogeneidad entre las posiciones {t_cambio} y {t_cambio + 1} de la "
            f"serie (p≈{p_valor:.4f} < 0.05)." if p_valor < 0.05 else
            "No se detecta un punto de cambio estadísticamente significativo (p≥0.05); la serie se "
            "comporta como homogénea según esta prueba."
        ),
    }


# ---------------------------------------------------------------------
# Mann-Kendall (tendencia) + pendiente de Sen (magnitud)
# ---------------------------------------------------------------------
def test_mann_kendall(serie: List[float]) -> dict:
    """Prueba de tendencia no paramétrica de Mann-Kendall, con
    corrección de varianza por valores empatados (Kendall, 1975)."""
    x = np.asarray(serie, dtype=float)
    n = len(x)
    if n < 4:
        raise QualityControlError("Se requieren al menos 4 datos para la prueba de Mann-Kendall.")

    S = 0
    for i in range(n - 1):
        S += np.sum(np.sign(x[i + 1:] - x[i]))

    valores, cuentas = np.unique(x, return_counts=True)
    termino_empates = np.sum(cuentas * (cuentas - 1) * (2 * cuentas + 5))
    var_S = (n * (n - 1) * (2 * n + 5) - termino_empates) / 18.0

    if S > 0:
        z = (S - 1) / math.sqrt(var_S)
    elif S < 0:
        z = (S + 1) / math.sqrt(var_S)
    else:
        z = 0.0

    p_valor = 2.0 * (1.0 - _cdf_normal_estandar(abs(z)))
    tendencia = "creciente" if (z > 0 and p_valor < 0.05) else ("decreciente" if (z < 0 and p_valor < 0.05) else "sin tendencia significativa")

    return {
        "S": int(S), "var_S": round(var_S, 2), "Z": round(z, 3), "p_valor": round(p_valor, 4),
        "tendencia": tendencia, "es_significativa_alpha_0_05": p_valor < 0.05,
    }


def pendiente_sen(serie: List[float]) -> dict:
    """Estimador de pendiente no paramétrico de Sen (1968): la mediana
    de todas las pendientes (x_j - x_i)/(j - i) para i < j."""
    x = np.asarray(serie, dtype=float)
    n = len(x)
    if n < 2:
        raise QualityControlError("Se requieren al menos 2 datos para la pendiente de Sen.")
    pendientes = [
        (x[j] - x[i]) / (j - i)
        for i in range(n - 1) for j in range(i + 1, n)
    ]
    pendiente_mediana = float(np.median(pendientes))
    return {
        "pendiente_por_periodo": round(pendiente_mediana, 4),
        "interpretacion": (
            f"Cambio estimado de {pendiente_mediana:+.3f} unidades por periodo (año), mediana de "
            f"todas las pendientes posibles entre pares de datos — robusto frente a valores atípicos."
        ),
    }


def _cdf_normal_estandar(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _rangos(x: np.ndarray) -> np.ndarray:
    """Rangos (1..n), con el promedio en caso de empates."""
    orden = np.argsort(x, kind="mergesort")
    rangos = np.empty(len(x), dtype=float)
    rangos[orden] = np.arange(1, len(x) + 1)
    # promediar rangos de valores empatados
    valores_unicos, inversa, cuentas = np.unique(x, return_inverse=True, return_counts=True)
    suma_rangos_por_valor = np.zeros(len(valores_unicos))
    np.add.at(suma_rangos_por_valor, inversa, rangos)
    rango_promedio_por_valor = suma_rangos_por_valor / cuentas
    return rango_promedio_por_valor[inversa]


# =======================================================================
# GRUPO: TENDENCIAS
# =======================================================================
def test_spearman_rho(serie: List[float]) -> dict:
    """Correlación de rangos de Spearman entre el valor y el orden
    temporal, como prueba de tendencia (equivalente no paramétrico de la
    regresión lineal). Significancia vía aproximación t de Student."""
    x = np.asarray(serie, dtype=float)
    n = len(x)
    if n < 4:
        raise QualityControlError("Se requieren al menos 4 datos para Spearman's Rho.")
    rangos_x = _rangos(x)
    rangos_t = np.arange(1, n + 1, dtype=float)
    rho = float(np.corrcoef(rangos_x, rangos_t)[0, 1])
    t_stat = rho * math.sqrt((n - 2) / max(1e-12, 1 - rho ** 2))
    p_valor = 2 * (1 - _cdf_t_student(abs(t_stat), n - 2))
    return {
        "rho": round(rho, 4), "t": round(t_stat, 3), "p_valor_aprox": round(p_valor, 4),
        "tendencia_significativa_alpha_0_05": p_valor < 0.05,
    }


def test_regresion_lineal_tendencia(serie: List[float]) -> dict:
    """Pendiente de la regresión lineal (valor vs. orden temporal) y su
    significancia (t de Student sobre la pendiente)."""
    x = np.asarray(serie, dtype=float)
    n = len(x)
    if n < 4:
        raise QualityControlError("Se requieren al menos 4 datos para la regresión lineal.")
    t = np.arange(1, n + 1, dtype=float)
    t_media, x_media = t.mean(), x.mean()
    Sxx = np.sum((t - t_media) ** 2)
    Sxy = np.sum((t - t_media) * (x - x_media))
    pendiente = Sxy / Sxx
    intercepto = x_media - pendiente * t_media
    residuos = x - (pendiente * t + intercepto)
    s2 = np.sum(residuos ** 2) / (n - 2)
    error_std_pendiente = math.sqrt(s2 / Sxx)
    t_stat = pendiente / error_std_pendiente if error_std_pendiente > 0 else 0.0
    p_valor = 2 * (1 - _cdf_t_student(abs(t_stat), n - 2))
    return {
        "pendiente_por_periodo": round(float(pendiente), 4), "intercepto": round(float(intercepto), 4),
        "t": round(t_stat, 3), "p_valor_aprox": round(p_valor, 4),
        "tendencia_significativa_alpha_0_05": p_valor < 0.05,
    }


# =======================================================================
# GRUPO: CAMBIO EN MEDIA/MEDIANA (punto de quiebre)
# =======================================================================
def test_cusum_libre_distribucion(serie: List[float]) -> dict:
    """CUSUM de rangos (distribution-free), Kundzewicz & Robson (2000):
    Sk = sum de (rango_i - (n+1)/2) para i=1..k. El punto de mayor
    |Sk| es el candidato a quiebre. La significancia exacta requiere
    tablas de valores críticos (dependientes de n); aquí se reporta un
    estadístico rescalado Q y una referencia asintótica aproximada
    (Kolmogorov-Smirnov), a falta de esas tablas."""
    x = np.asarray(serie, dtype=float)
    n = len(x)
    if n < 4:
        raise QualityControlError("Se requieren al menos 4 datos para el CUSUM de rangos.")
    rangos = _rangos(x)
    Sk = np.cumsum(rangos - (n + 1) / 2.0)
    k_max = int(np.argmax(np.abs(Sk))) + 1
    S_max = float(np.max(np.abs(Sk)))
    Q = S_max / math.sqrt(n ** 3 / 12.0)
    return {
        "posicion_quiebre_candidata": k_max, "S_max": round(S_max, 2), "Q_rescalado": round(Q, 4),
        "referencia_aprox_alpha_0_05": 1.36,
        "es_significativo_aprox": Q > 1.36,
        "nota": "Q > ~1.36 (referencia asintótica tipo Kolmogorov-Smirnov al 5%) sugiere un quiebre; "
                "para significancia exacta use las tablas de valores críticos según n.",
    }


def test_desviacion_acumulada(serie: List[float]) -> dict:
    """Prueba de Buishand (1982) de desviación acumulada: Sk* = suma de
    (x_i - media) para i=1..k. Estadísticos Q (máximo |Sk*| rescalado
    por la desviación estándar) y R (rango ajustado rescalado)."""
    x = np.asarray(serie, dtype=float)
    n = len(x)
    if n < 4:
        raise QualityControlError("Se requieren al menos 4 datos para la desviación acumulada de Buishand.")
    media = x.mean()
    desv = x.std(ddof=0)
    if desv == 0:
        raise QualityControlError("La serie no tiene variabilidad (desviación estándar nula).")
    Sk = np.cumsum(x - media)
    k_max = int(np.argmax(np.abs(Sk))) + 1
    Q = float(np.max(np.abs(Sk)) / desv)
    R = float((np.max(Sk) - np.min(Sk)) / desv)
    Q_n = Q / math.sqrt(n)
    return {
        "posicion_quiebre_candidata": k_max, "Q": round(Q, 3), "Q_sobre_raiz_n": round(Q_n, 4),
        "R_rango_ajustado": round(R, 3),
        "referencia_aprox_Q_raiz_n_alpha_0_05": 1.36,
        "es_significativo_aprox": Q_n > 1.36,
        "nota": "Valores críticos exactos de Buishand (1982) dependen de n; Q/√n > ~1.36 es una "
                "referencia asintótica aproximada al 5%, no el valor tabulado exacto.",
    }


def test_worsley_likelihood_ratio(serie: List[float]) -> dict:
    """Prueba de razón de verosimilitud de Worsley (1979) para un
    quiebre único en la media, en una posición desconocida:
    V_k = sqrt(k(n-k)/n) * |media_1..k - media_(k+1)..n| / s_conjunta,
    tomando el máximo sobre todos los k candidatos."""
    x = np.asarray(serie, dtype=float)
    n = len(x)
    if n < 5:
        raise QualityControlError("Se requieren al menos 5 datos para la prueba de Worsley.")
    s = x.std(ddof=1)
    mejor_V, mejor_k = -1.0, None
    for k in range(2, n - 1):
        m1, m2 = x[:k].mean(), x[k:].mean()
        V = math.sqrt(k * (n - k) / n) * abs(m1 - m2) / s
        if V > mejor_V:
            mejor_V, mejor_k = V, k
    # p-valor aproximado (corrección tipo Bonferroni sobre n-1 posiciones candidatas, vía normal estándar)
    p_por_posicion = 2 * (1 - _cdf_normal_estandar(mejor_V))
    p_valor_aprox = min(1.0, p_por_posicion * (n - 3))
    return {
        "posicion_quiebre_candidata": mejor_k, "V_max": round(mejor_V, 3),
        "p_valor_aprox": round(p_valor_aprox, 4), "es_significativo_aprox_alpha_0_05": p_valor_aprox < 0.05,
        "nota": "p-valor aproximado (corrección tipo Bonferroni sobre las posiciones candidatas); "
                "Worsley (1979) provee una aproximación más precisa por tablas específicas.",
    }


# =======================================================================
# GRUPO: DIFERENCIA EN MEDIA/MEDIANA ENTRE 2 PERIODOS
# =======================================================================
def test_rank_sum(serie_periodo1: List[float], serie_periodo2: List[float]) -> dict:
    """Prueba de suma de rangos de Wilcoxon-Mann-Whitney: compara la
    mediana de dos periodos/muestras independientes, sin asumir
    distribución."""
    x1 = np.asarray(serie_periodo1, dtype=float)
    x2 = np.asarray(serie_periodo2, dtype=float)
    n1, n2 = len(x1), len(x2)
    if n1 < 2 or n2 < 2:
        raise QualityControlError("Cada periodo debe tener al menos 2 datos para el rank-sum test.")
    combinados = np.concatenate([x1, x2])
    rangos = _rangos(combinados)
    W = float(np.sum(rangos[:n1]))
    media_W = n1 * (n1 + n2 + 1) / 2.0
    var_W = n1 * n2 * (n1 + n2 + 1) / 12.0
    z = (W - media_W) / math.sqrt(var_W)
    p_valor = 2 * (1 - _cdf_normal_estandar(abs(z)))
    return {
        "W": round(W, 2), "Z": round(z, 3), "p_valor_aprox": round(p_valor, 4),
        "diferencia_significativa_alpha_0_05": p_valor < 0.05,
        "mediana_periodo1": round(float(np.median(x1)), 3), "mediana_periodo2": round(float(np.median(x2)), 3),
    }


def test_t_student(serie_periodo1: List[float], serie_periodo2: List[float]) -> dict:
    """Prueba t de Student de dos muestras (Welch, varianzas no
    necesariamente iguales) para diferencia de medias entre 2 periodos."""
    x1 = np.asarray(serie_periodo1, dtype=float)
    x2 = np.asarray(serie_periodo2, dtype=float)
    n1, n2 = len(x1), len(x2)
    if n1 < 2 or n2 < 2:
        raise QualityControlError("Cada periodo debe tener al menos 2 datos para el t-test.")
    m1, m2 = x1.mean(), x2.mean()
    v1, v2 = x1.var(ddof=1), x2.var(ddof=1)
    error_std = math.sqrt(v1 / n1 + v2 / n2)
    t_stat = (m1 - m2) / error_std if error_std > 0 else 0.0
    gl = (v1 / n1 + v2 / n2) ** 2 / (((v1 / n1) ** 2 / (n1 - 1)) + ((v2 / n2) ** 2 / (n2 - 1)))
    p_valor = 2 * (1 - _cdf_t_student(abs(t_stat), gl))
    return {
        "t": round(t_stat, 3), "grados_libertad_welch": round(gl, 1), "p_valor_aprox": round(p_valor, 4),
        "diferencia_significativa_alpha_0_05": p_valor < 0.05,
        "media_periodo1": round(float(m1), 3), "media_periodo2": round(float(m2), 3),
    }


# =======================================================================
# GRUPO: ALEATORIEDAD
# =======================================================================
def test_cruces_mediana(serie: List[float]) -> dict:
    """Test de cruces de la mediana: cuenta cuántas veces la serie pasa
    de un lado a otro de su mediana; bajo aleatoriedad, el número
    esperado de cruces es (n-1)/2."""
    x = np.asarray(serie, dtype=float)
    n = len(x)
    if n < 8:
        raise QualityControlError("Se requieren al menos 8 datos para el test de cruces de la mediana.")
    mediana = np.median(x)
    signo = x > mediana
    cruces = int(np.sum(signo[1:] != signo[:-1]))
    esperado = (n - 1) / 2.0
    varianza = (n - 1) / 4.0
    z = (cruces - esperado) / math.sqrt(varianza)
    p_valor = 2 * (1 - _cdf_normal_estandar(abs(z)))
    return {
        "cruces_observados": cruces, "cruces_esperados": round(esperado, 1), "Z": round(z, 3),
        "p_valor_aprox": round(p_valor, 4), "no_aleatorio_alpha_0_05": p_valor < 0.05,
    }


def test_puntos_de_giro(serie: List[float]) -> dict:
    """Test de puntos de giro (turning points): cuenta máximos/mínimos
    locales; bajo aleatoriedad, el número esperado es 2(n-2)/3."""
    x = np.asarray(serie, dtype=float)
    n = len(x)
    if n < 8:
        raise QualityControlError("Se requieren al menos 8 datos para el test de puntos de giro.")
    giros = 0
    for i in range(1, n - 1):
        if (x[i - 1] < x[i] > x[i + 1]) or (x[i - 1] > x[i] < x[i + 1]):
            giros += 1
    esperado = 2.0 * (n - 2) / 3.0
    varianza = (16.0 * n - 29.0) / 90.0
    z = (giros - esperado) / math.sqrt(varianza)
    p_valor = 2 * (1 - _cdf_normal_estandar(abs(z)))
    return {
        "puntos_de_giro_observados": giros, "puntos_de_giro_esperados": round(esperado, 1), "Z": round(z, 3),
        "p_valor_aprox": round(p_valor, 4), "no_aleatorio_alpha_0_05": p_valor < 0.05,
    }


def test_diferencia_rangos(serie: List[float]) -> dict:
    """Test de signo de diferencias sucesivas (variante de rangos de
    Kendall para aleatoriedad): cuenta cuántas diferencias sucesivas
    (x_{i+1} - x_i) son positivas; bajo aleatoriedad el número esperado
    es (n-1)/2. NOTA: existen varias pruebas de rango relacionadas en la
    bibliografía con nombres similares ("rank difference test"); esta
    implementación usa el test de signo de diferencias sucesivas de
    Kendall, matemáticamente equivalente en espíritu. Verifique contra
    la fuente exacta que use su institución si necesita reproducir un
    resultado específico de otro software."""
    x = np.asarray(serie, dtype=float)
    n = len(x)
    if n < 8:
        raise QualityControlError("Se requieren al menos 8 datos para el test de diferencia de rangos.")
    diferencias_positivas = int(np.sum(np.diff(x) > 0))
    esperado = (n - 1) / 2.0
    varianza = (n + 1) / 12.0
    z = (diferencias_positivas - esperado) / math.sqrt(varianza)
    p_valor = 2 * (1 - _cdf_normal_estandar(abs(z)))
    return {
        "diferencias_positivas_observadas": diferencias_positivas, "esperadas": round(esperado, 1), "Z": round(z, 3),
        "p_valor_aprox": round(p_valor, 4), "no_aleatorio_alpha_0_05": p_valor < 0.05,
    }


def test_autocorrelacion(serie: List[float], lag: int = 1) -> dict:
    """Coeficiente de autocorrelación serial (lag-1 por defecto) y su
    significancia aproximada (bajo H0 de independencia, r_k ~ N(-1/n, 1/n))."""
    x = np.asarray(serie, dtype=float)
    n = len(x)
    if n < 8 or lag >= n:
        raise QualityControlError("Se requieren al menos 8 datos (y lag < n) para la autocorrelación.")
    media = x.mean()
    num = np.sum((x[:-lag] - media) * (x[lag:] - media))
    den = np.sum((x - media) ** 2)
    r_k = float(num / den) if den > 0 else 0.0
    error_std = 1.0 / math.sqrt(n)
    z = (r_k - (-1.0 / n)) / error_std
    p_valor = 2 * (1 - _cdf_normal_estandar(abs(z)))
    return {
        "lag": lag, "r": round(r_k, 4), "Z": round(z, 3), "p_valor_aprox": round(p_valor, 4),
        "autocorrelacion_significativa_alpha_0_05": p_valor < 0.05,
    }


def _cdf_t_student(t: float, gl: float) -> float:
    """CDF de la distribución t de Student vía la función beta
    incompleta regularizada (relación estándar t <-> F <-> Beta)."""
    if gl <= 0:
        return 0.5
    x = gl / (gl + t ** 2)
    ib = _beta_incompleta_regularizada(x, gl / 2.0, 0.5)
    return 1 - 0.5 * ib if t > 0 else 0.5 * ib


def _beta_incompleta_regularizada(x: float, a: float, b: float, iter_max: int = 200, eps: float = 1e-10) -> float:
    """Fracción continua de Lentz para la función beta incompleta
    regularizada I_x(a,b) (Numerical Recipes, identidad matemática
    estándar)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    frente = math.exp(lbeta + a * math.log(x) + b * math.log(1 - x))
    if x < (a + 1) / (a + b + 2):
        return frente * _cf_beta(x, a, b, iter_max, eps) / a
    else:
        return 1.0 - frente * _cf_beta(1 - x, b, a, iter_max, eps) / b


def _cf_beta(x, a, b, iter_max, eps):
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, iter_max + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d, c = 1.0 / d, c
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


# ---------------------------------------------------------------------
# Curva de doble masa
# ---------------------------------------------------------------------
def curva_doble_masa(serie_estacion: List[float], serie_referencia: Optional[List[float]] = None) -> dict:
    """
    Curva de doble masa: acumulado de la estación en estudio vs.
    acumulado de una serie de referencia (usualmente el promedio de
    varias estaciones vecinas confiables, del mismo periodo).

    Si no se provee serie_referencia, se usa como referencia la propia
    serie ordenada de forma "ideal" (acumulado lineal esperado si no
    hubiera ninguna inconsistencia, es decir la recta n*promedio) — una
    alternativa simplificada cuando no se dispone de estaciones vecinas,
    MENOS rigurosa que la doble masa clásica entre dos estaciones reales;
    se advierte explícitamente en el resultado.
    """
    x = np.asarray(serie_estacion, dtype=float)
    n = len(x)
    if n < 3:
        raise QualityControlError("Se requieren al menos 3 datos para la curva de doble masa.")

    acum_estacion = np.cumsum(x)

    if serie_referencia is not None:
        y = np.asarray(serie_referencia, dtype=float)
        if len(y) != n:
            raise QualityControlError("La serie de referencia debe tener la misma longitud que la serie de la estación.")
        acum_referencia = np.cumsum(y)
        metodo = "doble_masa_clasica_2_series"
    else:
        promedio = float(np.mean(x))
        acum_referencia = promedio * np.arange(1, n + 1)
        metodo = "aproximacion_sin_serie_de_referencia"

    # Pendiente de cada segmento consecutivo (para detectar quiebres visualmente)
    pendientes_segmento = []
    for i in range(1, n):
        dx = acum_referencia[i] - acum_referencia[i - 1]
        dy = acum_estacion[i] - acum_estacion[i - 1]
        pendientes_segmento.append(dy / dx if dx != 0 else float("nan"))

    return {
        "metodo": metodo,
        "acumulado_estacion": acum_estacion.tolist(),
        "acumulado_referencia": acum_referencia.tolist(),
        "pendientes_segmento": [round(p, 3) if not math.isnan(p) else None for p in pendientes_segmento],
        "advertencia": (
            None if serie_referencia is not None else
            "Se usó la aproximación sin una serie de referencia real (recta del promedio acumulado); "
            "para un diagnóstico de doble masa riguroso, provea el acumulado de una serie de "
            "referencia (p. ej. el promedio de estaciones vecinas confiables del mismo periodo)."
        ),
    }


# =======================================================================
# GRUPO: NORMALIDAD
# =======================================================================
def test_anderson_darling(serie: List[float]) -> dict:
    """
    Prueba de Anderson-Darling (1952) para normalidad, variante de caso 3
    (media y varianza desconocidas, estimadas de la muestra), con la
    corrección de muestra finita y la aproximación de p-valor de
    D'Agostino & Stephens (1986) -- el mismo test usado en la literatura
    hidrológica para evaluar si una serie de precipitación/caudal se
    ajusta a la distribución normal (p.ej. antes de decidir si aplicar
    una transformación previo a completar datos o a un análisis de
    doble masa paramétrico).

    A diferencia de Shapiro-Wilk (cuyos coeficientes exactos del
    algoritmo AS R94 de Royston no se pudieron verificar con certeza en
    este entorno), Anderson-Darling tiene una fórmula cerrada bien
    establecida que sí se implementa completa aquí; si necesita
    Shapiro-Wilk específicamente, use scipy.stats.shapiro si su
    intérprete de Python de QGIS tiene scipy instalado.

    FUENTES:
      - Anderson, T.W.; Darling, D.A. (1952). "Asymptotic theory of
        certain 'goodness of fit' criteria based on stochastic
        processes". Annals of Mathematical Statistics, 23(2), 193-212.
      - D'Agostino, R.B.; Stephens, M.A., eds. (1986). "Goodness-of-Fit
        Techniques". Marcel Dekker (corrección de muestra finita y
        aproximación de p-valor usadas aquí).
    """
    x = np.asarray(serie, dtype=float)
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 8:
        raise QualityControlError("Se requieren al menos 8 datos para la prueba de Anderson-Darling.")

    media, desv = float(x.mean()), float(x.std(ddof=1))
    if desv == 0:
        raise QualityControlError("La serie no tiene variabilidad (desviación estándar nula).")

    x_ordenado = np.sort(x)
    z = (x_ordenado - media) / desv
    phi = np.array([_cdf_normal_estandar(v) for v in z])
    phi = np.clip(phi, 1e-12, 1 - 1e-12)  # evita log(0) en colas extremas

    i = np.arange(1, n + 1)
    S = np.sum((2 * i - 1) * (np.log(phi) + np.log(1 - phi[::-1])))
    A2 = -n - S / n
    A2_ajustado = A2 * (1 + 0.75 / n + 2.25 / n ** 2)

    if A2_ajustado >= 0.6:
        p_valor = math.exp(1.2937 - 5.709 * A2_ajustado + 0.0186 * A2_ajustado ** 2)
    elif A2_ajustado >= 0.34:
        p_valor = math.exp(0.9177 - 4.279 * A2_ajustado - 1.38 * A2_ajustado ** 2)
    elif A2_ajustado >= 0.2:
        p_valor = 1 - math.exp(-8.318 + 42.796 * A2_ajustado - 59.938 * A2_ajustado ** 2)
    else:
        p_valor = 1 - math.exp(-13.436 + 101.14 * A2_ajustado - 223.73 * A2_ajustado ** 2)
    p_valor = min(max(p_valor, 0.0), 1.0)

    return {
        "A2": round(float(A2), 4), "A2_ajustado": round(float(A2_ajustado), 4),
        "p_valor_aprox": round(p_valor, 4), "acepta_normalidad_alpha_0_05": p_valor >= 0.05,
        "interpretacion": (
            f"No se rechaza la normalidad (p≈{p_valor:.4f} ≥ 0.05)." if p_valor >= 0.05 else
            f"Se rechaza la normalidad (p≈{p_valor:.4f} < 0.05); considere una transformación "
            "(log, Box-Cox) antes de análisis que asuman datos normales (p.ej. regresión lineal "
            "múltiple para completación de datos, curva de doble masa paramétrica)."
        ),
    }


# =======================================================================
# GRUPO: TENDENCIA ESTACIONAL Y HOMOGENEIZACIÓN
# =======================================================================
def test_mann_kendall_estacional(serie: List[float], periodo: int = 12) -> dict:
    """
    Prueba de Mann-Kendall ESTACIONAL (Hirsch, Slack & Smith, 1982): en
    vez de aplicar Mann-Kendall a la serie completa (lo que puede dar
    falsos positivos/negativos de tendencia por el propio ciclo
    estacional en series mensuales), se calcula S y su varianza de forma
    INDEPENDIENTE para cada estación del ciclo (p.ej. cada uno de los 12
    meses del año, a través de los años) y luego se suman.

    SIMPLIFICACIÓN: se asume independencia entre estaciones del ciclo
    (S y varianza se suman directamente). Hirsch & Slack (1984)
    extienden el método con una corrección de covarianza entre
    estaciones correlacionadas (p.ej. si un mes lluvioso tiende a ir
    seguido de otro mes lluvioso); esa corrección NO se implementa aquí.

    FUENTE: Hirsch, R.M.; Slack, J.R.; Smith, R.A. (1982). "Techniques
    of trend analysis for monthly water quality data". Water Resources
    Research, 18(1), 107-121.
    """
    x = np.asarray(serie, dtype=float)
    n = len(x)
    if periodo < 2:
        raise QualityControlError("El periodo estacional debe ser >= 2 (p.ej. 12 para datos mensuales).")
    if n < periodo * 3:
        raise QualityControlError(
            f"Se recomiendan al menos 3 ciclos completos ({periodo * 3} datos) para Mann-Kendall estacional."
        )

    S_total, var_total = 0.0, 0.0
    detalle_por_estacion = []
    for s in range(periodo):
        sub = x[s::periodo]
        sub = sub[~np.isnan(sub)]
        m = len(sub)
        if m < 4:
            detalle_por_estacion.append({"estacion": s + 1, "n": m, "S": None, "nota": "insuficientes datos, excluida"})
            continue
        S_s = 0
        for i in range(m - 1):
            S_s += np.sum(np.sign(sub[i + 1:] - sub[i]))
        valores, cuentas = np.unique(sub, return_counts=True)
        termino_empates = np.sum(cuentas * (cuentas - 1) * (2 * cuentas + 5))
        var_s = (m * (m - 1) * (2 * m + 5) - termino_empates) / 18.0
        S_total += S_s
        var_total += var_s
        detalle_por_estacion.append({"estacion": s + 1, "n": m, "S": int(S_s)})

    if S_total > 0:
        z = (S_total - 1) / math.sqrt(var_total)
    elif S_total < 0:
        z = (S_total + 1) / math.sqrt(var_total)
    else:
        z = 0.0
    p_valor = 2.0 * (1.0 - _cdf_normal_estandar(abs(z)))
    tendencia = ("creciente" if (z > 0 and p_valor < 0.05) else
                 ("decreciente" if (z < 0 and p_valor < 0.05) else "sin tendencia significativa"))

    return {
        "S_total": int(S_total), "var_S_total": round(var_total, 2), "Z": round(z, 3),
        "p_valor": round(p_valor, 4), "tendencia": tendencia, "es_significativa_alpha_0_05": p_valor < 0.05,
        "detalle_por_estacion": detalle_por_estacion,
    }


def corregir_por_quiebre(serie: List[float], indice_quiebre: int, metodo: str = "aditivo") -> dict:
    """
    Corrige (homogeneiza) una serie a partir de un punto de quiebre ya
    detectado (p.ej. por test_pettitt, test_desviacion_acumulada o
    test_worsley_likelihood_ratio): ajusta el segmento POSTERIOR al
    quiebre para que su media coincida con la del segmento ANTERIOR.

    Sigue la práctica estándar de homogeneización hidrológica (WMO,
    "Guide to Hydrological Practices") y, específicamente para
    precipitación, el criterio de corrección aplicado por Wang Qiuxiang
    et al. (2012) sobre 2415 estaciones de precipitación diaria en
    China: tras detectar el quiebre (en su caso con SNHT), corrigieron
    estación por estación llevando un segmento a la media del otro.

    indice_quiebre: posición 1-indexada del último dato del segmento
    ANTERIOR (mismo formato que 'indice_cambio' de test_pettitt()).

    metodo: 'aditivo' (suma la diferencia de medias -- apropiado para
    variables que pueden ser negativas o cero, p.ej. caudal base o
    anomalías de temperatura) o 'multiplicativo' (escala por el cociente
    de medias -- apropiado para precipitación, que no debe volverse
    negativa).

    TRANSPARENCIA: corrige solo la MEDIA (salto de nivel), no cambios de
    varianza ni tendencias dentro de cada segmento. El segmento
    ANTERIOR se toma como referencia por convención (más antiguo); si lo
    que cambió fue la instalación/ubicación original de la estación,
    puede ser más apropiado corregir en sentido contrario -- revise el
    contexto físico antes de aceptar la corrección automática.
    """
    x = np.asarray(serie, dtype=float)
    n = len(x)
    if not (1 <= indice_quiebre < n):
        raise QualityControlError(f"indice_quiebre debe estar entre 1 y {n - 1}.")
    if metodo not in ("aditivo", "multiplicativo"):
        raise QualityControlError("metodo debe ser 'aditivo' o 'multiplicativo'.")

    antes, despues = x[:indice_quiebre], x[indice_quiebre:]
    media_antes = float(np.nanmean(antes))
    media_despues = float(np.nanmean(despues))

    serie_corregida = x.copy()
    if metodo == "aditivo":
        ajuste = media_antes - media_despues
        serie_corregida[indice_quiebre:] = despues + ajuste
    else:
        if media_despues == 0:
            raise QualityControlError("La media del segmento posterior es 0; use metodo='aditivo'.")
        ajuste = media_antes / media_despues
        serie_corregida[indice_quiebre:] = despues * ajuste

    return {
        "metodo": metodo, "media_antes": round(media_antes, 3), "media_despues_original": round(media_despues, 3),
        "media_despues_corregida": round(float(np.nanmean(serie_corregida[indice_quiebre:])), 3),
        "ajuste_aplicado": round(float(ajuste), 4),
        "serie_corregida": [round(float(v), 3) if not np.isnan(v) else None for v in serie_corregida],
        "advertencia": (
            "La corrección homogeneiza la MEDIA de ambos segmentos; documente siempre que estos "
            "valores son 'corregidos', no observados directamente, en cualquier reporte técnico."
        ),
    }


def funcion_autocorrelacion_parcial(serie: List[float], max_lag: int = 12) -> dict:
    """
    Función de autocorrelación parcial (PACF) mediante la recursión de
    Durbin-Levinson, hasta max_lag. Complementa a test_autocorrelacion()
    (que evalúa un solo lag a la vez) con el conjunto completo de
    coeficientes parciales -- útil para diagnosticar la estructura de
    dependencia serial de una serie (p.ej. antes de asumir independencia
    en un análisis de frecuencia, o para fijar el orden de un modelo
    autorregresivo de relleno).

    FUENTE: Durbin, J. (1960). "The fitting of time-series models".
    Revue de l'Institut International de Statistique, 28(3), 233-244.
    """
    x = np.asarray(serie, dtype=float)
    x = x[~np.isnan(x)]
    n = len(x)
    if max_lag < 1 or max_lag >= n:
        raise QualityControlError("max_lag debe ser >= 1 y menor que el número de datos válidos.")

    media = x.mean()
    xc = x - media
    c0 = float(np.sum(xc ** 2) / n)
    if c0 == 0:
        raise QualityControlError("La serie no tiene variabilidad (varianza nula).")
    acf = [float(np.sum(xc[:n - k] * xc[k:]) / n) / c0 for k in range(0, max_lag + 1)]

    phi = np.zeros((max_lag + 1, max_lag + 1))
    pacf = [1.0]
    phi[1, 1] = acf[1]
    pacf.append(float(phi[1, 1]))
    for k in range(2, max_lag + 1):
        num = acf[k] - sum(phi[k - 1, j] * acf[k - j] for j in range(1, k))
        den = 1 - sum(phi[k - 1, j] * acf[j] for j in range(1, k))
        phi[k, k] = num / den if den != 0 else 0.0
        for j in range(1, k):
            phi[k, j] = phi[k - 1, j] - phi[k, k] * phi[k - 1, k - j]
        pacf.append(float(phi[k, k]))

    limite = 1.96 / math.sqrt(n)  # banda de confianza aprox. 95% bajo H0 de ruido blanco
    lags_significativos = [k for k in range(1, max_lag + 1) if abs(pacf[k]) > limite]

    return {
        "pacf_por_lag": {k: round(v, 4) for k, v in enumerate(pacf)},
        "limite_significancia_aprox_95": round(limite, 4), "lags_significativos": lags_significativos,
        "interpretacion": (
            "Sin dependencia serial significativa detectada en los lags evaluados (banda ±95%)."
            if not lags_significativos else
            f"Dependencia serial significativa en el(los) lag(s) {lags_significativos}; considérelo al "
            "interpretar pruebas que asumen independencia (Mann-Kendall, Pettitt, etc. pierden "
            "confiabilidad con autocorrelación fuerte)."
        ),
    }
