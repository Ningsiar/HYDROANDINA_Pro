# -*- coding: utf-8 -*-
"""
core/frequency_analysis.py

Análisis de frecuencia de precipitación máxima en 24 horas: ajuste de
distribuciones de probabilidad, prueba de bondad de ajuste de
Kolmogorov-Smirnov, y estimación de precipitaciones de diseño para
distintos periodos de retorno.

Distribuciones implementadas (parámetros por momentos, salvo GEV que
usa momentos-L de Hosking, más robustos para esa familia):
  - Normal
  - Log-Normal (2 parámetros)
  - Gumbel / Valor Extremo Tipo I (EV1)
  - Log-Pearson III (aproximación de Wilson-Hilferty/Kite para el
    factor de frecuencia, Chow et al. 1988, "Applied Hydrology")
  - GEV (Valor Extremo Generalizada), momentos-L, Hosking (1990)

DISEÑO SIN DEPENDENCIA DE SCIPY: el cuantil normal estándar (inversa de
la CDF normal) se calcula por Newton-Raphson usando `math.erf` de la
librería estándar de Python, en vez de codificar una aproximación
racional (tipo Acklam) cuyos coeficientes no se pudieron verificar con
certeza suficiente aquí. Esto es más lento pero matemáticamente exacto
y no depende de constantes de memoria.

VERIFICADO en este entorno (probado con datos sintéticos):
  - z(0.975) converge a 1.95996... (valor tabulado estándar) ✓
  - Los cuantiles Normal/LogNormal/Gumbel/LogPearson3/GEV son monótona-
    mente crecientes con el periodo de retorno para datos sintéticos.
"""
import math
from dataclasses import dataclass
from typing import List, Dict, Callable, Optional


# ---------------------------------------------------------------------
# Cuantil normal estándar (sin scipy), por Newton-Raphson sobre math.erf
# ---------------------------------------------------------------------
def _cdf_normal_estandar(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _pdf_normal_estandar(z: float) -> float:
    return (1.0 / math.sqrt(2.0 * math.pi)) * math.exp(-0.5 * z * z)


def cuantil_normal_estandar(p: float, tol: float = 1e-12, max_iter: int = 100) -> float:
    """Inversa de la CDF normal estándar N(0,1), z tal que Phi(z) = p."""
    if not (0.0 < p < 1.0):
        raise ValueError("p debe estar estrictamente entre 0 y 1.")
    z = 0.0
    lo, hi = -10.0, 10.0
    for _ in range(max_iter):
        f = _cdf_normal_estandar(z) - p
        if abs(f) < tol:
            return z
        deriv = _pdf_normal_estandar(z)
        if deriv > 1e-300:
            z_newton = z - f / deriv
        else:
            z_newton = z
        if not (lo < z_newton < hi):
            z_newton = (lo + hi) / 2.0
        if f > 0:
            hi = z
        else:
            lo = z
        z = z_newton
    return z


# ---------------------------------------------------------------------
# Estadísticos muestrales básicos
# ---------------------------------------------------------------------
def _media(x: List[float]) -> float:
    return sum(x) / len(x)


def _desv_std(x: List[float], ddof: int = 1) -> float:
    m = _media(x)
    n = len(x)
    return math.sqrt(sum((xi - m) ** 2 for xi in x) / (n - ddof))


def _sesgo(x: List[float]) -> float:
    """Coeficiente de asimetría muestral (sesgo), corregido (g1 con factor n²/((n-1)(n-2)))."""
    n = len(x)
    m = _media(x)
    s = _desv_std(x)
    if s == 0 or n < 3:
        return 0.0
    suma_cubos = sum((xi - m) ** 3 for xi in x)
    return (n / ((n - 1) * (n - 2))) * (suma_cubos / (s ** 3))


# ---------------------------------------------------------------------
# Ajuste de distribuciones
# ---------------------------------------------------------------------
@dataclass
class DistribucionAjustada:
    nombre: str
    parametros: Dict[str, float]
    cuantil: Callable[[float], float]   # cuantil(p_no_excedencia) -> valor
    cdf: Callable[[float], float]       # cdf(valor) -> p_no_excedencia


def ajustar_normal(datos: List[float]) -> DistribucionAjustada:
    mu, sigma = _media(datos), _desv_std(datos)

    def cuantil(p):
        return mu + sigma * cuantil_normal_estandar(p)

    def cdf(x):
        return _cdf_normal_estandar((x - mu) / sigma)

    return DistribucionAjustada("Normal", {"mu": mu, "sigma": sigma}, cuantil, cdf)


def ajustar_lognormal2(datos: List[float]) -> DistribucionAjustada:
    if any(d <= 0 for d in datos):
        raise ValueError("Log-Normal requiere datos estrictamente positivos.")
    logs = [math.log(d) for d in datos]
    mu_log, sigma_log = _media(logs), _desv_std(logs)

    def cuantil(p):
        return math.exp(mu_log + sigma_log * cuantil_normal_estandar(p))

    def cdf(x):
        return _cdf_normal_estandar((math.log(x) - mu_log) / sigma_log)

    return DistribucionAjustada("Log-Normal (2 parámetros)", {"mu_log": mu_log, "sigma_log": sigma_log}, cuantil, cdf)


def ajustar_gumbel(datos: List[float]) -> DistribucionAjustada:
    """Gumbel / EV1 por el método de momentos (Chow, 1951)."""
    media, s = _media(datos), _desv_std(datos)
    alpha = (math.sqrt(6.0) * s) / math.pi
    u = media - 0.5772156649 * alpha  # 0.5772... = constante de Euler-Mascheroni

    def cuantil(p):
        return u - alpha * math.log(-math.log(p))

    def cdf(x):
        return math.exp(-math.exp(-(x - u) / alpha))

    return DistribucionAjustada("Gumbel (EV1)", {"u": u, "alpha": alpha}, cuantil, cdf)


def _factor_frecuencia_pearson3(z: float, cs: float) -> float:
    """
    Aproximación de Wilson-Hilferty / Kite (1977) para el factor de
    frecuencia K de la distribución Pearson III, en función del sesgo Cs
    y del cuantil normal estándar z. Fuente: Kite (1977); reproducida en
    Chow, Maidment & Mays (1988), "Applied Hydrology", cap. 12.
    """
    k = cs / 6.0
    return (z + (z ** 2 - 1) * k
            + (1.0 / 3.0) * (z ** 3 - 6 * z) * k ** 2
            - (z ** 2 - 1) * k ** 3
            + z * k ** 4
            + (1.0 / 3.0) * k ** 5)


def ajustar_logpearson3(datos: List[float]) -> DistribucionAjustada:
    if any(d <= 0 for d in datos):
        raise ValueError("Log-Pearson III requiere datos estrictamente positivos.")
    logs = [math.log10(d) for d in datos]
    media_log, s_log, cs_log = _media(logs), _desv_std(logs), _sesgo(logs)

    def cuantil(p):
        z = cuantil_normal_estandar(p)
        k = _factor_frecuencia_pearson3(z, cs_log)
        return 10 ** (media_log + k * s_log)

    def cdf(x):
        lo, hi = 1e-9, 1 - 1e-9
        for _ in range(80):
            mid = (lo + hi) / 2.0
            if cuantil(mid) < x:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2.0

    return DistribucionAjustada(
        "Log-Pearson III", {"media_log10": media_log, "s_log10": s_log, "sesgo_log10": cs_log}, cuantil, cdf
    )


def _log_gamma(x: float) -> float:
    return math.lgamma(x)


# ---------------------------------------------------------------------
# Función gamma incompleta regularizada P(a,x), sin scipy (algoritmo
# estándar de serie + fracción continua, Numerical Recipes / Abramowitz
# & Stegun 6.5.29-6.5.31 — identidades matemáticas exactas, no
# coeficientes empíricos de una fuente hidrológica particular).
# ---------------------------------------------------------------------
def _gammainc_p(a: float, x: float, iter_max: int = 200, eps: float = 1e-12) -> float:
    """P(a,x) = gamma(a,x)/Gamma(a), regularizada, 0<=P<=1."""
    if x < 0 or a <= 0:
        raise ValueError("_gammainc_p requiere a > 0, x >= 0.")
    if x == 0:
        return 0.0
    if x < a + 1.0:
        # Desarrollo en serie (Abramowitz & Stegun 6.5.29)
        termino = 1.0 / a
        suma = termino
        ai = a
        for _ in range(iter_max):
            ai += 1.0
            termino *= x / ai
            suma += termino
            if abs(termino) < abs(suma) * eps:
                break
        return suma * math.exp(-x + a * math.log(x) - _log_gamma(a))
    else:
        # Fracción continua (algoritmo de Lentz) para Q(a,x) = 1-P(a,x)
        tiny = 1e-300
        b = x + 1.0 - a
        c = 1.0 / tiny
        d = 1.0 / b
        h = d
        for i in range(1, iter_max + 1):
            an = -i * (i - a)
            b += 2.0
            d = an * d + b
            if abs(d) < tiny:
                d = tiny
            c = b + an / c
            if abs(c) < tiny:
                c = tiny
            d = 1.0 / d
            delta = d * c
            h *= delta
            if abs(delta - 1.0) < eps:
                break
        q = math.exp(-x + a * math.log(x) - _log_gamma(a)) * h
        return 1.0 - q


def _gammainc_p_inversa(a: float, p: float, tol: float = 1e-9, max_iter: int = 100) -> float:
    """Invierte _gammainc_p por bisección: encuentra x tal que P(a,x)=p."""
    if not (0.0 < p < 1.0):
        raise ValueError("p debe estar estrictamente entre 0 y 1.")
    lo, hi = 0.0, max(a * 10.0, 10.0)
    # Expandir el límite superior hasta que P(a,hi) supere p
    while _gammainc_p(a, hi) < p:
        hi *= 2.0
        if hi > 1e12:
            raise RuntimeError("No se pudo acotar el cuantil de la Gamma (a muy grande o p~1).")
    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        if _gammainc_p(a, mid) < p:
            lo = mid
        else:
            hi = mid
        if (hi - lo) < tol * max(hi, 1.0):
            break
    return (lo + hi) / 2.0


def ajustar_gamma2(datos: List[float]) -> DistribucionAjustada:
    """Gamma de 2 parámetros (sin desplazamiento), método de momentos:
    alpha = (media/desv_std)^2, beta = desv_std^2/media. Requiere datos
    estrictamente positivos (típico de series de lluvia)."""
    if any(d <= 0 for d in datos):
        raise ValueError("La distribución Gamma requiere datos estrictamente positivos.")
    media, s = _media(datos), _desv_std(datos)
    alpha = (media / s) ** 2
    beta = (s ** 2) / media

    def cuantil(p):
        return beta * _gammainc_p_inversa(alpha, p)

    def cdf(x):
        return _gammainc_p(alpha, x / beta)

    return DistribucionAjustada("Gamma (2 parámetros)", {"alpha": alpha, "beta": beta}, cuantil, cdf)


def ajustar_gamma3_pearson3(datos: List[float]) -> DistribucionAjustada:
    """Gamma de 3 parámetros = Pearson tipo III aplicada DIRECTAMENTE
    sobre los datos (no sobre sus logaritmos, a diferencia de
    Log-Pearson III). Mismo factor de frecuencia de Wilson-Hilferty/Kite
    que ajustar_logpearson3(), pero con media/desv/sesgo de X en vez de
    log(X). Fuente: Kite (1977); Chow, Maidment & Mays (1988), cap. 12."""
    media, s, cs = _media(datos), _desv_std(datos), _sesgo(datos)

    def cuantil(p):
        z = cuantil_normal_estandar(p)
        k = _factor_frecuencia_pearson3(z, cs)
        return media + k * s

    def cdf(x):
        lo, hi = 1e-9, 1 - 1e-9
        for _ in range(80):
            mid = (lo + hi) / 2.0
            if cuantil(mid) < x:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2.0

    return DistribucionAjustada(
        "Gamma 3 parámetros (Pearson III)", {"media": media, "s": s, "sesgo": cs}, cuantil, cdf
    )


def ajustar_lognormal3(datos: List[float]) -> DistribucionAjustada:
    """
    Log-Normal de 3 parámetros: X - x0 es Log-Normal(mu,sigma), con x0 el
    límite inferior. Método de momentos (Sangal & Biswas, 1970 / Kite,
    1977): el sesgo de X es igual al de la parte log-normal (invariante
    ante el desplazamiento x0), lo que permite resolver primero
    B = exp(sigma^2) a partir del sesgo muestral, y luego mu, x0 a partir
    de la media y varianza:
        Cs = (B+2)*sqrt(B-1)               [se resuelve B por bisección]
        Var = exp(2*mu+sigma^2)*(B-1)
        x0  = media - exp(mu + sigma^2/2)
    Requiere sesgo muestral positivo (distribución con cola a la derecha,
    caso típico de series de máximos de lluvia); si el sesgo es negativo
    o casi nulo, no es aplicable con este método y se reporta como error
    en vez de forzar un resultado no válido.
    """
    media, s, cs = _media(datos), _desv_std(datos), _sesgo(datos)
    if cs <= 1e-6:
        raise ValueError(
            "Log-Normal 3P (método de momentos) requiere sesgo muestral positivo; "
            f"el sesgo de la serie es {cs:.4f}. No es aplicable con este método para esta serie."
        )
    var = s ** 2

    def f(b):
        return (b + 2.0) * math.sqrt(max(b - 1.0, 0.0)) - cs

    lo, hi = 1.0 + 1e-9, 1000.0
    while f(hi) < 0:
        hi *= 2.0
        if hi > 1e9:
            raise RuntimeError("No se pudo resolver B=exp(sigma^2) para Log-Normal 3P (sesgo extremo).")
    for _ in range(100):
        mid = (lo + hi) / 2.0
        if f(mid) < 0:
            lo = mid
        else:
            hi = mid
    b = (lo + hi) / 2.0

    sigma = math.sqrt(math.log(b))
    mu = 0.5 * math.log(var / (b * (b - 1.0)))
    x0 = media - math.exp(mu + (sigma ** 2) / 2.0)

    def cuantil(p):
        return x0 + math.exp(mu + sigma * cuantil_normal_estandar(p))

    def cdf(x):
        if x <= x0:
            return 0.0
        return _cdf_normal_estandar((math.log(x - x0) - mu) / sigma)

    return DistribucionAjustada(
        "Log-Normal (3 parámetros)", {"x0": x0, "mu_log": mu, "sigma_log": sigma}, cuantil, cdf
    )


def ajustar_loggumbel(datos: List[float]) -> DistribucionAjustada:
    """Log-Gumbel: ln(X) se distribuye Gumbel/EV1 (método de momentos
    sobre los logaritmos de los datos, misma formulación que
    ajustar_gumbel() pero aplicada a log(X) en vez de X)."""
    if any(d <= 0 for d in datos):
        raise ValueError("Log-Gumbel requiere datos estrictamente positivos.")
    logs = [math.log(d) for d in datos]
    media_log, s_log = _media(logs), _desv_std(logs)
    alpha_log = (math.sqrt(6.0) * s_log) / math.pi
    u_log = media_log - 0.5772156649 * alpha_log

    def cuantil(p):
        return math.exp(u_log - alpha_log * math.log(-math.log(p)))

    def cdf(x):
        return math.exp(-math.exp(-(math.log(x) - u_log) / alpha_log))

    return DistribucionAjustada("Log-Gumbel", {"u_log": u_log, "alpha_log": alpha_log}, cuantil, cdf)


def ajustar_gev(datos: List[float]) -> DistribucionAjustada:
    """
    GEV por momentos-L (Hosking, 1990, "L-moments: Analysis and
    Estimation of Distributions using Linear Combinations of Order
    Statistics", JRSS-B 52(1):105-124). Aproximación de kappa a partir
    de la L-asimetría t3 (ecuación 3.5-3.6 de Hosking, 1990); válida con
    buena precisión para -0.5 < t3 < 0.5 (rango típico de series de
    máximos anuales de precipitación).
    """
    n = len(datos)
    x = sorted(datos)

    b0 = _media(x)
    b1 = sum((i / (n - 1)) * x[i] for i in range(n)) / n if n > 1 else 0.0
    b2 = (sum(((i * (i - 1)) / ((n - 1) * (n - 2))) * x[i] for i in range(n)) / n) if n > 2 else 0.0

    l1 = b0
    l2 = 2 * b1 - b0
    l3 = 6 * b2 - 6 * b1 + b0
    t3 = l3 / l2 if l2 != 0 else 0.0

    c = (2.0 / (3.0 + t3)) - (math.log(2) / math.log(3))
    kappa = 7.8590 * c + 2.9554 * (c ** 2)

    if abs(kappa) < 1e-6:
        alpha = l2 / math.log(2)
        xi = l1 - 0.5772156649 * alpha

        def cuantil(p):
            return xi - alpha * math.log(-math.log(p))

        def cdf(xv):
            return math.exp(-math.exp(-(xv - xi) / alpha))
    else:
        gamma_1_k = math.exp(_log_gamma(1 + kappa))
        alpha = (kappa * l2) / (gamma_1_k * (1 - 2 ** (-kappa)))
        xi = l1 - (alpha / kappa) * (1 - gamma_1_k)

        def cuantil(p):
            return xi + (alpha / kappa) * (1 - (-math.log(p)) ** kappa)

        def cdf(xv):
            base = 1 - kappa * (xv - xi) / alpha
            if base <= 0:
                return 1.0 if kappa > 0 else 0.0
            return math.exp(-base ** (1.0 / kappa))

    return DistribucionAjustada("GEV (momentos-L, Hosking 1990)",
                                 {"xi": xi, "alpha": alpha, "kappa": kappa}, cuantil, cdf)


# =====================================================================
# AJUSTE POR MOMENTOS-L (Hosking 1990; Hosking & Wallis 1997)
# =====================================================================
# Los momentos ordinarios (media, desviación, sesgo) elevan las
# desviaciones al cuadrado y al cubo, así que un único dato extremo pesa
# muchísimo en el ajuste -- y las series de máximos anuales de
# precipitación son, por construcción, series de valores extremos, a
# menudo cortas (20-40 años). El coeficiente de sesgo muestral es
# especialmente inestable: está acotado por el tamaño de la muestra y
# tiene un sesgo negativo importante en muestras pequeñas.
#
# Los momentos-L son combinaciones LINEALES de los estadísticos de orden,
# así que ningún dato entra elevado a una potencia: son mucho más
# robustos frente a valores atípicos y mucho menos sesgados en muestras
# cortas. Son hoy el estándar en análisis regional de frecuencias
# (Hosking & Wallis, "Regional Frequency Analysis: An Approach Based on
# L-Moments", Cambridge University Press, 1997).
#
# La GEV de este módulo ya se ajustaba por momentos-L desde el inicio
# (ver ajustar_gev). Aquí se agregan las 8 distribuciones restantes, de
# modo que el usuario pueda comparar ambos métodos sobre su propia serie.

def momentos_l(datos: List[float]) -> dict:
    """
    Momentos-L muestrales insesgados l1..l4 y sus razones t2 (L-CV),
    t3 (L-asimetría) y t4 (L-curtosis), calculados a partir de los
    momentos ponderados por probabilidad b0..b3.
    """
    x = sorted(datos)
    n = len(x)
    if n < 4:
        raise ValueError("Se necesitan al menos 4 datos para calcular los momentos-L hasta l4.")

    b0 = sum(x) / n
    b1 = sum((i / (n - 1)) * x[i] for i in range(n)) / n
    b2 = sum(((i * (i - 1)) / ((n - 1) * (n - 2))) * x[i] for i in range(n)) / n
    b3 = sum(((i * (i - 1) * (i - 2)) / ((n - 1) * (n - 2) * (n - 3))) * x[i] for i in range(n)) / n

    l1 = b0
    l2 = 2 * b1 - b0
    l3 = 6 * b2 - 6 * b1 + b0
    l4 = 20 * b3 - 30 * b2 + 12 * b1 - b0
    return {
        "l1": l1, "l2": l2, "l3": l3, "l4": l4,
        "t2": (l2 / l1) if l1 != 0 else 0.0,
        "t3": (l3 / l2) if l2 != 0 else 0.0,
        "t4": (l4 / l2) if l2 != 0 else 0.0,
    }


def ajustar_normal_lmomentos(datos: List[float]) -> DistribucionAjustada:
    """Normal por momentos-L: mu = l1, sigma = l2*sqrt(pi) (relación
    exacta, no una aproximación: para la normal l2 = sigma/sqrt(pi))."""
    m = momentos_l(datos)
    mu = m["l1"]
    sigma = m["l2"] * math.sqrt(math.pi)
    if sigma <= 0:
        raise ValueError("Sigma no positivo al ajustar la Normal por momentos-L.")

    def cuantil(p):
        return mu + sigma * cuantil_normal_estandar(p)

    def cdf(x):
        return _cdf_normal_estandar((x - mu) / sigma)

    return DistribucionAjustada("Normal (momentos-L)", {"mu": mu, "sigma": sigma}, cuantil, cdf)


def ajustar_lognormal2_lmomentos(datos: List[float]) -> DistribucionAjustada:
    """Log-Normal 2P por momentos-L: es una Normal ajustada sobre los
    logaritmos, así que se aplican los mismos estimadores a ln(x)."""
    if any(v <= 0 for v in datos):
        raise ValueError("La Log-Normal requiere que todos los datos sean positivos.")
    logs = [math.log(v) for v in datos]
    m = momentos_l(logs)
    mu_y = m["l1"]
    sigma_y = m["l2"] * math.sqrt(math.pi)
    if sigma_y <= 0:
        raise ValueError("Sigma no positivo al ajustar la Log-Normal 2P por momentos-L.")

    def cuantil(p):
        return math.exp(mu_y + sigma_y * cuantil_normal_estandar(p))

    def cdf(x):
        if x <= 0:
            return 0.0
        return _cdf_normal_estandar((math.log(x) - mu_y) / sigma_y)

    return DistribucionAjustada("Log-Normal 2P (momentos-L)", {"mu_y": mu_y, "sigma_y": sigma_y},
                                 cuantil, cdf)


def ajustar_gumbel_lmomentos(datos: List[float]) -> DistribucionAjustada:
    """Gumbel/EV1 por momentos-L: alpha = l2/ln(2), xi = l1 - gamma*alpha
    (relaciones exactas, con gamma la constante de Euler-Mascheroni)."""
    m = momentos_l(datos)
    alpha = m["l2"] / math.log(2.0)
    if alpha <= 0:
        raise ValueError("Alpha no positivo al ajustar Gumbel por momentos-L.")
    xi = m["l1"] - 0.5772156649 * alpha

    def cuantil(p):
        return xi - alpha * math.log(-math.log(p))

    def cdf(x):
        return math.exp(-math.exp(-(x - xi) / alpha))

    return DistribucionAjustada("Gumbel (momentos-L)", {"xi": xi, "alpha": alpha}, cuantil, cdf)


def ajustar_loggumbel_lmomentos(datos: List[float]) -> DistribucionAjustada:
    """Log-Gumbel por momentos-L: Gumbel sobre los logaritmos."""
    if any(v <= 0 for v in datos):
        raise ValueError("La Log-Gumbel requiere que todos los datos sean positivos.")
    logs = [math.log(v) for v in datos]
    m = momentos_l(logs)
    alpha = m["l2"] / math.log(2.0)
    if alpha <= 0:
        raise ValueError("Alpha no positivo al ajustar Log-Gumbel por momentos-L.")
    xi = m["l1"] - 0.5772156649 * alpha

    def cuantil(p):
        return math.exp(xi - alpha * math.log(-math.log(p)))

    def cdf(x):
        if x <= 0:
            return 0.0
        return math.exp(-math.exp(-(math.log(x) - xi) / alpha))

    return DistribucionAjustada("Log-Gumbel (momentos-L)", {"xi": xi, "alpha": alpha}, cuantil, cdf)


def _forma_gamma_desde_t2(t2: float) -> float:
    """
    Parámetro de forma de la Gamma a partir de la L-CV (t2 = l2/l1),
    por la aproximación racional de Hosking (1990) -- error relativo
    reportado por debajo de 5e-5 en todo el rango.
    """
    if t2 <= 0 or t2 >= 1:
        raise ValueError(f"L-CV fuera de rango para la Gamma (t2 = {t2:.4f}; debe estar entre 0 y 1).")
    if t2 < 0.5:
        z = math.pi * t2 * t2
        alpha = (1.0 - 0.3080 * z) / (z - 0.05812 * z ** 2 + 0.01765 * z ** 3)
    else:
        z = 1.0 - t2
        alpha = (0.7213 * z - 0.5947 * z ** 2) / (1.0 - 2.1817 * z + 1.2113 * z ** 2)
    if alpha <= 0:
        raise ValueError("Forma no positiva al ajustar la Gamma por momentos-L.")
    return alpha


def ajustar_gamma2_lmomentos(datos: List[float]) -> DistribucionAjustada:
    """Gamma 2P por momentos-L (Hosking 1990): la forma se obtiene de la
    L-CV y la escala de la media (l1 = forma*escala)."""
    if any(v <= 0 for v in datos):
        raise ValueError("La Gamma requiere que todos los datos sean positivos.")
    m = momentos_l(datos)
    forma = _forma_gamma_desde_t2(m["t2"])
    escala = m["l1"] / forma

    def cuantil(p):
        return escala * _gammainc_p_inversa(forma, p)

    def cdf(x):
        if x <= 0:
            return 0.0
        return _gammainc_p(forma, x / escala)

    return DistribucionAjustada("Gamma 2P (momentos-L)", {"alpha": forma, "beta": escala}, cuantil, cdf)


def _parametros_pearson3_lmomentos(m: dict) -> tuple:
    """
    Parámetros (media, desviación, sesgo) de una Pearson III a partir de
    sus momentos-L, por las aproximaciones racionales de Hosking &
    Wallis (1997, apéndice A.9). Devuelve (mu, sigma, gamma_sesgo).
    """
    t3 = m["t3"]
    if abs(t3) >= 1.0:
        raise ValueError(f"L-asimetría fuera de rango para Pearson III (t3 = {t3:.4f}).")
    if abs(t3) < 1e-9:
        # Sin asimetría la Pearson III degenera en una Normal.
        return m["l1"], m["l2"] * math.sqrt(math.pi), 0.0
    if abs(t3) < 1.0 / 3.0:
        z = 3.0 * math.pi * t3 * t3
        alpha = (1.0 + 0.2906 * z) / (z + 0.1882 * z ** 2 + 0.0442 * z ** 3)
    else:
        z = 1.0 - abs(t3)
        alpha = ((0.36067 * z - 0.59567 * z ** 2 + 0.25361 * z ** 3) /
                 (1.0 - 2.78861 * z + 2.56096 * z ** 2 - 0.77045 * z ** 3))
    if alpha <= 0:
        raise ValueError("Forma no positiva al ajustar Pearson III por momentos-L.")
    sesgo = (2.0 / math.sqrt(alpha)) * (1.0 if t3 > 0 else -1.0)
    # Relación exacta entre l2 y los parámetros de la Pearson III: para una
    # Gamma de forma alpha y escala beta se cumple
    #     l2 = beta * Gamma(alpha + 1/2) / (sqrt(pi) * Gamma(alpha))
    # (verificado en el caso alpha=1, exponencial: l2 = beta/2). Como
    # sigma = beta*sqrt(alpha), al despejar queda
    #     sigma = l2 * sqrt(pi) * sqrt(alpha) * Gamma(alpha) / Gamma(alpha + 1/2)
    # Se calcula con logaritmos porque Gamma() desborda para alpha grande.
    log_ratio = _log_gamma(alpha) - _log_gamma(alpha + 0.5)
    sigma = m["l2"] * math.sqrt(math.pi) * math.sqrt(alpha) * math.exp(log_ratio)
    if sigma <= 0:
        raise ValueError("Sigma no positivo al ajustar Pearson III por momentos-L.")
    return m["l1"], sigma, sesgo


def ajustar_gamma3_pearson3_lmomentos(datos: List[float]) -> DistribucionAjustada:
    """Gamma 3P / Pearson III por momentos-L (Hosking & Wallis 1997)."""
    m = momentos_l(datos)
    mu, sigma, cs = _parametros_pearson3_lmomentos(m)

    def cuantil(p):
        return mu + sigma * _factor_frecuencia_pearson3(cuantil_normal_estandar(p), cs)

    def cdf(x):
        # Igual que en la versión por momentos ordinarios: se invierte
        # numéricamente el cuantil, porque la CDF de Pearson III con
        # sesgo arbitrario no tiene forma cerrada elemental.
        lo, hi = 1e-9, 1.0 - 1e-9
        for _ in range(80):
            mid = 0.5 * (lo + hi)
            if cuantil(mid) < x:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)

    return DistribucionAjustada("Gamma 3P / Pearson III (momentos-L)",
                                 {"mu": mu, "sigma": sigma, "Cs": cs}, cuantil, cdf)


def ajustar_logpearson3_lmomentos(datos: List[float]) -> DistribucionAjustada:
    """Log-Pearson III por momentos-L: Pearson III sobre los logaritmos."""
    if any(v <= 0 for v in datos):
        raise ValueError("La Log-Pearson III requiere que todos los datos sean positivos.")
    logs = [math.log(v) for v in datos]
    m = momentos_l(logs)
    mu_y, sigma_y, cs_y = _parametros_pearson3_lmomentos(m)

    def cuantil(p):
        return math.exp(mu_y + sigma_y * _factor_frecuencia_pearson3(cuantil_normal_estandar(p), cs_y))

    def cdf(x):
        if x <= 0:
            return 0.0
        lo, hi = 1e-9, 1.0 - 1e-9
        for _ in range(80):
            mid = 0.5 * (lo + hi)
            if cuantil(mid) < x:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)

    return DistribucionAjustada("Log-Pearson III (momentos-L)",
                                 {"mu_y": mu_y, "sigma_y": sigma_y, "Cs_y": cs_y}, cuantil, cdf)


def ajustar_lognormal3_lmomentos(datos: List[float]) -> DistribucionAjustada:
    """
    Log-Normal 3P por momentos-L, en la parametrización de "normal
    generalizada" de Hosking & Wallis (1997, A.8), que es la forma en que
    la log-normal de 3 parámetros admite estimadores de momentos-L
    cerrados. Se reporta además el parámetro de posición equivalente
    (x0 = xi - alpha/k), que es el "límite inferior" con el que
    tradicionalmente se presenta la log-normal 3P.
    """
    m = momentos_l(datos)
    t3 = m["t3"]
    if abs(t3) >= 0.95:
        raise ValueError(f"L-asimetría fuera de rango para la Log-Normal 3P (t3 = {t3:.4f}).")

    e0, e1, e2, e3 = 2.0466534, -3.6544371, 1.8396733, -0.20360244
    f1, f2, f3 = -2.0182173, 1.2420401, -0.21741801
    z = t3
    k = -z * (e0 + e1 * z ** 2 + e2 * z ** 4 + e3 * z ** 6) / \
        (1.0 + f1 * z ** 2 + f2 * z ** 4 + f3 * z ** 6)
    if abs(k) < 1e-8:
        raise ValueError("La Log-Normal 3P degenera en Normal (asimetría nula); use la Normal.")

    # alpha = l2 * k * exp(-k^2/2) / (1 - 2*Phi(-k/sqrt(2)))
    denominador = 1.0 - 2.0 * _cdf_normal_estandar(-k / math.sqrt(2.0))
    if abs(denominador) < 1e-12:
        raise ValueError("Denominador nulo al ajustar la Log-Normal 3P por momentos-L.")
    alpha = m["l2"] * k * math.exp(-k * k / 2.0) / denominador
    if alpha <= 0:
        raise ValueError("Alpha no positivo al ajustar la Log-Normal 3P por momentos-L.")
    xi = m["l1"] - (alpha / k) * (1.0 - math.exp(k * k / 2.0))

    def cuantil(p):
        return xi + (alpha / k) * (1.0 - math.exp(-k * cuantil_normal_estandar(p)))

    def cdf(x):
        base = 1.0 - k * (x - xi) / alpha
        if base <= 0:
            return 1.0 if k > 0 else 0.0
        return _cdf_normal_estandar(-math.log(base) / k)

    return DistribucionAjustada(
        "Log-Normal 3P (momentos-L)",
        {"xi": xi, "alpha": alpha, "k": k, "x0_limite_inferior": xi - alpha / k},
        cuantil, cdf)


DISTRIBUCIONES_DISPONIBLES = {
    "normal": ajustar_normal,
    "lognormal2": ajustar_lognormal2,
    "lognormal3": ajustar_lognormal3,
    "gumbel": ajustar_gumbel,
    "loggumbel": ajustar_loggumbel,
    "gamma2": ajustar_gamma2,
    "gamma3_pearson3": ajustar_gamma3_pearson3,
    "logpearson3": ajustar_logpearson3,
    "gev": ajustar_gev,
}

# Mismas 9 distribuciones, ajustadas por momentos-L. La GEV es la misma
# función en ambos diccionarios porque ya se ajustaba así desde el inicio.
DISTRIBUCIONES_LMOMENTOS = {
    "normal": ajustar_normal_lmomentos,
    "lognormal2": ajustar_lognormal2_lmomentos,
    "lognormal3": ajustar_lognormal3_lmomentos,
    "gumbel": ajustar_gumbel_lmomentos,
    "loggumbel": ajustar_loggumbel_lmomentos,
    "gamma2": ajustar_gamma2_lmomentos,
    "gamma3_pearson3": ajustar_gamma3_pearson3_lmomentos,
    "logpearson3": ajustar_logpearson3_lmomentos,
    "gev": ajustar_gev,
}

METODOS_AJUSTE = {
    "momentos": ("Momentos ordinarios", DISTRIBUCIONES_DISPONIBLES),
    "momentos_l": ("Momentos-L (Hosking)", DISTRIBUCIONES_LMOMENTOS),
}


# ---------------------------------------------------------------------
# Prueba de bondad de ajuste de Kolmogorov-Smirnov
# ---------------------------------------------------------------------
def ks_estadistico(datos: List[float], cdf_teorica: Callable[[float], float]) -> float:
    """
    Estadístico D de Kolmogorov-Smirnov (una muestra): máxima distancia
    entre la CDF empírica y la CDF teórica ajustada.
    """
    x = sorted(datos)
    n = len(x)
    d_max = 0.0
    for i, xi in enumerate(x, start=1):
        f_teorica = cdf_teorica(xi)
        d_plus = abs((i / n) - f_teorica)
        d_minus = abs(f_teorica - (i - 1) / n)
        d_max = max(d_max, d_plus, d_minus)
    return d_max


def ks_valor_critico(n: int, alpha: float = 0.05) -> float:
    """
    Valor crítico asintótico de KS (Smirnov, 1948), D_crit = c(alpha)/sqrt(n).
    Verificado por búsqueda: c(0.05) = 1.36 (múltiples fuentes coinciden).
    c(0.10)=1.22 y c(0.01)=1.63 son las constantes estándar asociadas a
    la misma familia de aproximación (Massey, 1951). Válido para n
    moderado-grande (>~35); para n pequeño se recomienda la tabla exacta
    de Kolmogorov-Smirnov en vez de esta aproximación.
    """
    constantes = {0.10: 1.22, 0.05: 1.36, 0.01: 1.63}
    if alpha not in constantes:
        raise ValueError(f"alpha debe ser uno de {list(constantes)}")
    return constantes[alpha] / math.sqrt(n)


# ---------------------------------------------------------------------
# Prueba de bondad de ajuste de Anderson-Darling
# ---------------------------------------------------------------------
# El estadístico A² pondera las COLAS de la distribución mucho más que
# KS (que es más sensible al centro). En análisis de frecuencia de
# crecidas eso es justamente lo que interesa: el caudal/precipitación de
# diseño se lee en la cola alta (Tr=100, 500, 1000 años), así que una
# distribución puede pasar KS holgadamente y aun así ajustar mal
# precisamente donde se la va a usar. Por eso se agrega como prueba
# complementaria, no sustituta.
#
# SUTILEZA IMPORTANTE (y motivo de los "casos" de abajo): los valores
# críticos de A² dependen de si los parámetros de la distribución son
# conocidos de antemano o fueron ESTIMADOS a partir de la misma muestra
# que se está probando -- que es siempre el caso aquí. Al estimarlos, el
# ajuste es artificialmente mejor y los valores críticos del caso general
# resultan demasiado permisivos. La bibliografía (D'Agostino & Stephens,
# "Goodness-of-Fit Techniques", 1986) da modificaciones del estadístico y
# tablas de valores críticos específicas por distribución. Aquí se
# aplican las publicadas para normal/lognormal y para Gumbel/EV1; para
# el resto de distribuciones no se inventa un valor crítico: se usa el
# del caso general (parámetros conocidos) y se MARCA explícitamente como
# aproximado y conservador en el resultado, para que quien lo lea sepa
# que ese "pasa/no pasa" es menos estricto de lo que debería.

_AD_CRITICOS_CASO_GENERAL = {0.10: 1.933, 0.05: 2.492, 0.01: 3.857}
_AD_CRITICOS_NORMAL = {0.10: 0.632, 0.05: 0.751, 0.01: 1.029}
_AD_CRITICOS_GUMBEL = {0.10: 0.637, 0.05: 0.757, 0.01: 1.038}

# Distribuciones cuyos valores críticos de A² con parámetros estimados sí
# están tabulados en la bibliografía, con la familia que les corresponde.
_AD_FAMILIA_POR_DISTRIBUCION = {
    "normal": "normal",
    "lognormal2": "normal",      # log-normal = normal sobre los logaritmos
    "gumbel": "gumbel",
    "loggumbel": "gumbel",       # log-gumbel = gumbel sobre los logaritmos
}


def ad_estadistico(datos: List[float], cdf_teorica: Callable[[float], float]) -> float:
    """
    Estadístico A² de Anderson-Darling (una muestra):

        A² = -n - (1/n) * Σ (2i-1) * [ln(F(x_i)) + ln(1 - F(x_{n+1-i}))]

    con los datos ordenados de menor a mayor. Los valores de F se acotan
    lejos de 0 y 1 porque el logaritmo diverge en los extremos: con
    aritmética de punto flotante, una CDF que devuelva exactamente 0.0 o
    1.0 en el dato más extremo (cosa perfectamente posible por
    truncamiento) haría explotar el estadístico a infinito.
    """
    x = sorted(datos)
    n = len(x)
    if n < 2:
        raise ValueError("Se necesitan al menos 2 datos para Anderson-Darling.")
    eps = 1e-12
    suma = 0.0
    for i in range(1, n + 1):
        f_i = min(max(cdf_teorica(x[i - 1]), eps), 1.0 - eps)
        f_comp = min(max(cdf_teorica(x[n - i]), eps), 1.0 - eps)
        suma += (2 * i - 1) * (math.log(f_i) + math.log(1.0 - f_comp))
    return -n - suma / n


def ad_prueba(datos: List[float], cdf_teorica: Callable[[float], float],
              clave_distribucion: str = None, alpha: float = 0.05) -> dict:
    """
    Aplica Anderson-Darling devolviendo el estadístico (modificado si la
    distribución tiene una corrección tabulada), su valor crítico, y si
    pasa la prueba. Ver la nota extensa de arriba sobre por qué el valor
    crítico depende de la distribución.
    """
    if alpha not in _AD_CRITICOS_CASO_GENERAL:
        raise ValueError(f"alpha debe ser uno de {list(_AD_CRITICOS_CASO_GENERAL)}")
    n = len(datos)
    a2 = ad_estadistico(datos, cdf_teorica)
    familia = _AD_FAMILIA_POR_DISTRIBUCION.get(clave_distribucion)

    if familia == "normal":
        # Modificación de Stephens para parámetros estimados (normal/lognormal).
        a2_mod = a2 * (1.0 + 0.75 / n + 2.25 / (n * n))
        critico = _AD_CRITICOS_NORMAL[alpha]
        tipo_critico = "tabulado para parámetros estimados (normal/log-normal)"
        aproximado = False
    elif familia == "gumbel":
        a2_mod = a2 * (1.0 + 0.2 / math.sqrt(n))
        critico = _AD_CRITICOS_GUMBEL[alpha]
        tipo_critico = "tabulado para parámetros estimados (Gumbel/EV1)"
        aproximado = False
    else:
        a2_mod = a2
        critico = _AD_CRITICOS_CASO_GENERAL[alpha]
        tipo_critico = ("caso general (parámetros conocidos) — APROXIMADO y permisivo aquí, "
                        "porque los parámetros se estimaron de la misma muestra")
        aproximado = True

    return {
        "A2": round(a2, 4),
        "A2_modificado": round(a2_mod, 4),
        "A2_critico": critico,
        "pasa": a2_mod <= critico,
        "critico_aproximado": aproximado,
        "tipo_critico": tipo_critico,
    }


# ---------------------------------------------------------------------
# Prueba de bondad de ajuste Chi-cuadrado
# ---------------------------------------------------------------------
def chi2_valor_critico(grados_libertad: int, alpha: float = 0.05) -> float:
    """
    Valor crítico de la distribución Chi-cuadrado. No hace falta una tabla:
    Chi²(k) es exactamente una Gamma(forma=k/2, escala=2), así que se
    obtiene invirtiendo la función gamma incompleta regularizada que este
    módulo ya implementa para las distribuciones Gamma/Pearson.
    """
    if grados_libertad < 1:
        raise ValueError("Los grados de libertad deben ser >= 1.")
    return 2.0 * _gammainc_p_inversa(grados_libertad / 2.0, 1.0 - alpha)


def chi2_p_valor(estadistico: float, grados_libertad: int) -> float:
    """p-valor de la prueba Chi-cuadrado: P(X² > estadístico)."""
    if grados_libertad < 1:
        raise ValueError("Los grados de libertad deben ser >= 1.")
    return 1.0 - _gammainc_p(grados_libertad / 2.0, estadistico / 2.0)


def chi2_prueba(datos: List[float], dist: "DistribucionAjustada",
                n_clases: int = None, alpha: float = 0.05) -> dict:
    """
    Prueba Chi-cuadrado de bondad de ajuste con CLASES EQUIPROBABLES: en
    vez de partir el rango en intervalos de igual ancho (que deja las
    clases de las colas casi vacías y viola el requisito de frecuencia
    esperada mínima), se usan como bordes los cuantiles teóricos j/k de
    la propia distribución ajustada. Así la frecuencia esperada es
    exactamente n/k en TODAS las clases -- que es la forma recomendada de
    aplicar esta prueba y la que maximiza su potencia.

    Grados de libertad = k - 1 - m, siendo m el número de parámetros
    estimados de la muestra (cada parámetro estimado consume un grado de
    libertad; ignorarlo haría la prueba artificialmente permisiva).
    """
    n = len(datos)
    n_parametros = len(dist.parametros)
    if n_clases is None:
        # Regla de Sturges, acotada por arriba para respetar el requisito
        # clásico de frecuencia esperada >= 5 por clase (k <= n/5), y por
        # abajo para que queden grados de libertad suficientes.
        n_clases = int(1 + 3.322 * math.log10(n)) if n > 1 else 4
        n_clases = max(n_parametros + 3, min(n_clases, n // 5 if n >= 20 else 4))

    grados_libertad = n_clases - 1 - n_parametros
    if grados_libertad < 1:
        raise ValueError(
            f"Muestra demasiado corta para Chi-cuadrado con esta distribución: con n={n} y "
            f"{n_parametros} parámetros estimados quedan {grados_libertad} grados de libertad "
            "(se necesita al menos 1). Use Kolmogorov-Smirnov o Anderson-Darling."
        )

    bordes = [dist.cuantil(j / n_clases) for j in range(1, n_clases)]
    observadas = [0] * n_clases
    for valor in datos:
        indice = 0
        while indice < len(bordes) and valor > bordes[indice]:
            indice += 1
        observadas[indice] += 1

    esperada = n / n_clases
    estadistico = sum((o - esperada) ** 2 / esperada for o in observadas)
    critico = chi2_valor_critico(grados_libertad, alpha)
    p_valor = chi2_p_valor(estadistico, grados_libertad)

    return {
        "chi2": round(estadistico, 4),
        "chi2_critico": round(critico, 4),
        "grados_libertad": grados_libertad,
        "n_clases": n_clases,
        "frecuencia_esperada_por_clase": round(esperada, 3),
        "p_valor": round(p_valor, 5),
        "pasa": estadistico <= critico,
        "frecuencia_esperada_suficiente": esperada >= 5.0,
    }


# ---------------------------------------------------------------------
# Análisis completo: ajusta todas las distribuciones, aplica las 3
# pruebas de bondad de ajuste, y selecciona el mejor ajuste
# ---------------------------------------------------------------------
def analizar_todas(datos: List[float], alpha_ks: float = 0.05,
                    metodo: str = "momentos") -> Dict[str, dict]:
    """
    Ajusta las 9 distribuciones y les aplica las 3 pruebas de bondad de
    ajuste. `metodo` elige el estimador de parámetros: "momentos"
    (ordinarios: media/desviación/sesgo) o "momentos_l" (momentos-L de
    Hosking, más robustos en series cortas y con valores extremos --
    ver la nota extensa junto a DISTRIBUCIONES_LMOMENTOS).
    """
    if metodo not in METODOS_AJUSTE:
        raise ValueError(f"metodo debe ser uno de {list(METODOS_AJUSTE)}")
    resultados = {}
    n = len(datos)
    d_crit = ks_valor_critico(n, alpha_ks)
    _, distribuciones = METODOS_AJUSTE[metodo]

    for clave, func_ajuste in distribuciones.items():
        try:
            dist = func_ajuste(datos)
            d_ks = ks_estadistico(datos, dist.cdf)
            entrada = {
                "nombre": dist.nombre,
                "parametros": dist.parametros,
                "D_ks": round(d_ks, 4),
                "D_critico": round(d_crit, 4),
                "pasa_ks": d_ks <= d_crit,
                "distribucion": dist,
                "error": None,
            }
            # Anderson-Darling y Chi-cuadrado se calculan por separado y
            # sin abortar el resto: una muestra corta puede dejar sin
            # grados de libertad al Chi-cuadrado sin que eso invalide el
            # ajuste ni las otras dos pruebas.
            try:
                entrada["ad"] = ad_prueba(datos, dist.cdf, clave, alpha_ks)
            except Exception as e_ad:
                entrada["ad"] = {"error": str(e_ad)}
            try:
                entrada["chi2"] = chi2_prueba(datos, dist, alpha=alpha_ks)
            except Exception as e_chi:
                entrada["chi2"] = {"error": str(e_chi)}
            resultados[clave] = entrada
        except Exception as e:
            resultados[clave] = {"nombre": clave, "parametros": {}, "D_ks": None,
                                  "D_critico": round(d_crit, 4), "pasa_ks": False,
                                  "distribucion": None, "error": str(e),
                                  "ad": {"error": "no se ajustó la distribución"},
                                  "chi2": {"error": "no se ajustó la distribución"}}
    return resultados


def resumen_pruebas_bondad(entrada: dict) -> str:
    """
    Resume en una frase corta cuántas de las 3 pruebas de bondad de
    ajuste pasa una distribución, para mostrarlo en la tabla de la
    interfaz sin obligar al usuario a leer 6 columnas numéricas.
    """
    if entrada.get("error"):
        return "no ajustada"
    pasadas, total, detalles = 0, 0, []
    if entrada.get("D_ks") is not None:
        total += 1
        ok = entrada.get("pasa_ks")
        pasadas += 1 if ok else 0
        detalles.append(f"KS {'✓' if ok else '✗'}")
    ad = entrada.get("ad") or {}
    if "pasa" in ad:
        total += 1
        pasadas += 1 if ad["pasa"] else 0
        detalles.append(f"AD {'✓' if ad['pasa'] else '✗'}" + ("*" if ad.get("critico_aproximado") else ""))
    chi = entrada.get("chi2") or {}
    if "pasa" in chi:
        total += 1
        pasadas += 1 if chi["pasa"] else 0
        detalles.append(f"χ² {'✓' if chi['pasa'] else '✗'}")
    if total == 0:
        return "sin pruebas aplicables"
    return f"{pasadas}/{total} — " + ", ".join(detalles)


def _cuenta_pruebas_pasadas(entrada: dict) -> int:
    """Número de pruebas de bondad de ajuste (de las 3) que pasa una
    distribución. Las pruebas no aplicables (p.ej. Chi-cuadrado sin
    grados de libertad suficientes) simplemente no suman."""
    total = 0
    if entrada.get("pasa_ks"):
        total += 1
    if (entrada.get("ad") or {}).get("pasa"):
        total += 1
    if (entrada.get("chi2") or {}).get("pasa"):
        total += 1
    return total


def mejor_ajuste(resultados_analisis: Dict[str, dict], solo_ks: bool = False) -> Optional[str]:
    """
    Devuelve la clave de la distribución mejor ajustada a la serie.

    CRITERIO (cambiado en la v0.2.48): se ordena primero por CANTIDAD DE
    PRUEBAS DE BONDAD DE AJUSTE SUPERADAS (KS, Anderson-Darling y
    Chi-cuadrado) y solo se desempata por el menor estadístico D de KS.
    Antes se usaba únicamente KS.

    El motivo del cambio es concreto y verificado con datos sintéticos:
    KS es poco sensible a las COLAS de la distribución, que es justo
    donde se lee la precipitación de diseño (Tr=100, 500, 1000 años). En
    una serie log-normal de prueba, KS aceptaba tanto la Normal como la
    Log-Gumbel -- claramente inadecuadas para esos datos -- mientras que
    Anderson-Darling las rechazaba correctamente. Seleccionar por KS solo
    podía por tanto adoptar una distribución que ajusta bien el centro
    pero mal el extremo que interesa.

    solo_ks=True restaura el criterio antiguo (únicamente KS), por si se
    necesita reproducir un resultado calculado con una versión anterior
    del plugin.
    """
    validos = {k: v for k, v in resultados_analisis.items() if v.get("D_ks") is not None}
    if not validos:
        return None
    if solo_ks:
        que_pasan = {k: v for k, v in validos.items() if v["pasa_ks"]}
        universo = que_pasan if que_pasan else validos
        return min(universo, key=lambda k: universo[k]["D_ks"])
    # Más pruebas superadas primero; a igualdad, menor D de KS.
    return min(validos, key=lambda k: (-_cuenta_pruebas_pasadas(validos[k]), validos[k]["D_ks"]))


PERIODOS_RETORNO_DEFAULT = [2, 5, 10, 25, 50, 100, 250, 500, 1000]


def precipitaciones_diseño(distribucion: DistribucionAjustada,
                            periodos_retorno: List[int] = None) -> Dict[int, float]:
    """
    Calcula la precipitación máxima 24h de diseño para cada periodo de
    retorno Tr, usando la probabilidad de no excedencia p = 1 - 1/Tr.
    """
    periodos_retorno = periodos_retorno or PERIODOS_RETORNO_DEFAULT
    resultado = {}
    for tr in periodos_retorno:
        p = 1.0 - 1.0 / tr
        resultado[tr] = round(distribucion.cuantil(p), 2)
    return resultado


def tabla_comparacion_tr(resultados_analisis: Dict[str, dict],
                          periodos_retorno: List[int] = None) -> Dict[str, Dict[int, float]]:
    """
    Construye la tabla comparativa "Pmax 24h vs. periodo de retorno" para
    TODAS las distribuciones ajustadas exitosamente en resultados_analisis
    (el dict que devuelve analizar_todas()), para poder comparar las
    magnitudes entre distribuciones y decidir con criterio cuál adoptar
    (además de/complementando el criterio puramente estadístico de KS).

    Devuelve {clave_distribucion: {tr: p24_mm}}.
    """
    periodos_retorno = periodos_retorno or PERIODOS_RETORNO_DEFAULT
    tabla = {}
    for clave, r in resultados_analisis.items():
        if r.get("error") or r.get("distribucion") is None:
            continue
        tabla[clave] = precipitaciones_diseño(r["distribucion"], periodos_retorno)
    return tabla
