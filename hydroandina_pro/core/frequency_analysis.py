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
# Análisis completo: ajusta todas las distribuciones, aplica KS, y
# selecciona la de menor estadístico D (mejor ajuste)
# ---------------------------------------------------------------------
def analizar_todas(datos: List[float], alpha_ks: float = 0.05) -> Dict[str, dict]:
    resultados = {}
    n = len(datos)
    d_crit = ks_valor_critico(n, alpha_ks)

    for clave, func_ajuste in DISTRIBUCIONES_DISPONIBLES.items():
        try:
            dist = func_ajuste(datos)
            d_ks = ks_estadistico(datos, dist.cdf)
            resultados[clave] = {
                "nombre": dist.nombre,
                "parametros": dist.parametros,
                "D_ks": round(d_ks, 4),
                "D_critico": round(d_crit, 4),
                "pasa_ks": d_ks <= d_crit,
                "distribucion": dist,
                "error": None,
            }
        except Exception as e:
            resultados[clave] = {"nombre": clave, "parametros": {}, "D_ks": None,
                                  "D_critico": round(d_crit, 4), "pasa_ks": False,
                                  "distribucion": None, "error": str(e)}
    return resultados


def mejor_ajuste(resultados_analisis: Dict[str, dict]) -> Optional[str]:
    """Devuelve la clave de la distribución con menor D_ks entre las
    que pasan la prueba KS; si ninguna pasa, la de menor D_ks general."""
    validos = {k: v for k, v in resultados_analisis.items() if v["D_ks"] is not None}
    if not validos:
        return None
    que_pasan = {k: v for k, v in validos.items() if v["pasa_ks"]}
    universo = que_pasan if que_pasan else validos
    return min(universo, key=lambda k: universo[k]["D_ks"])


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
