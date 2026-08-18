# -*- coding: utf-8 -*-
"""
core/well_hydraulics.py

Motor de cálculo de HIDRÁULICA DE POZOS: régimen permanente (Thiem para
acuíferos confinados, Dupuit-Thiem para acuíferos libres), régimen
variable (Theis con la función de pozo W(u), y su simplificación de
Cooper-Jacob), pérdidas de carga en el pozo (ensayo escalonado,
sw=B·Q+C·Q²), y radio de influencia por varios métodos (Sichardt,
Kusakin, Theis, prueba de bombeo), con selección de la "mejor
propuesta" según el criterio de exactitud descrito en la bibliografía.

FUENTES: fórmulas estándar de hidráulica de pozos (Thiem, 1906; Theis,
1935; Cooper & Jacob, 1946), ampliamente reproducidas en manuales de
hidrogeología. La función de pozo W(u) (idéntica a la integral
exponencial E1(u)) se calcula con las aproximaciones racionales
estándar de Abramowitz & Stegun (1964, §5.1.53 y §5.1.56).
"""
import math
from typing import Callable, Dict, List, Sequence, Tuple

G = 9.81


class WellHydraulicsError(Exception):
    pass


# ============================================================================
# 1) RÉGIMEN PERMANENTE: THIEM (CONFINADO) Y DUPUIT-THIEM (LIBRE)
# ============================================================================

def descenso_diferencial_thiem_confinado(q_m3s: float, t_m2s: float, r1_m: float, r2_m: float) -> float:
    """s1-s2 = Q/(2πT)·ln(r2/r1), acuífero CONFINADO en régimen
    permanente (r2 > r1, ambos medidos desde el eje del pozo de bombeo)."""
    if r1_m <= 0 or r2_m <= 0 or t_m2s <= 0:
        raise WellHydraulicsError("r1, r2 y T deben ser mayores que cero.")
    return q_m3s / (2 * math.pi * t_m2s) * math.log(r2_m / r1_m)


def transmisividad_thiem_confinado(q_m3s: float, s1_m: float, s2_m: float, r1_m: float, r2_m: float) -> float:
    """Despeja T a partir de dos pozos de observación (s1 a r1, s2 a
    r2): T = Q·ln(r2/r1) / (2π·(s1-s2))."""
    if s1_m <= s2_m:
        raise WellHydraulicsError("s1 (más cercano) debe ser mayor que s2 (más lejano).")
    return q_m3s * math.log(r2_m / r1_m) / (2 * math.pi * (s1_m - s2_m))


def caudal_dupuit_thiem_libre(k_m_s: float, h1_m: float, h2_m: float, r1_m: float, r2_m: float) -> float:
    """Q = π·K·(h2²-h1²)/ln(r2/r1), acuífero LIBRE en régimen permanente."""
    if r1_m <= 0 or r2_m <= 0:
        raise WellHydraulicsError("r1 y r2 deben ser mayores que cero.")
    return math.pi * k_m_s * (h2_m ** 2 - h1_m ** 2) / math.log(r2_m / r1_m)


def conductividad_dupuit_thiem_libre(q_m3s: float, h1_m: float, h2_m: float, r1_m: float, r2_m: float) -> float:
    """Despeja K a partir de dos pozos de observación."""
    if h2_m <= h1_m:
        raise WellHydraulicsError("h2 (más lejano) debe ser mayor que h1 (más cercano, con más descenso).")
    return q_m3s * math.log(r2_m / r1_m) / (math.pi * (h2_m ** 2 - h1_m ** 2))


# ============================================================================
# 2) RÉGIMEN VARIABLE: THEIS Y COOPER-JACOB
# ============================================================================

def funcion_pozo_theis(u: float) -> float:
    """W(u), función de pozo de Theis (idéntica a la integral
    exponencial E1(u)), calculada con las aproximaciones racionales
    estándar de Abramowitz & Stegun (1964)."""
    if u <= 0:
        raise WellHydraulicsError("u debe ser mayor que cero.")
    if u <= 1.0:
        a0, a1, a2, a3, a4, a5 = (-0.57721566, 0.99999193, -0.24991055,
                                    0.05519968, -0.00976004, 0.00107857)
        return (-math.log(u) + a0 + a1 * u + a2 * u ** 2 + a3 * u ** 3
                + a4 * u ** 4 + a5 * u ** 5)
    else:
        a1, a2, a3, a4 = 8.5733287401, 18.0590169730, 8.6347608925, 0.2677737343
        b1, b2, b3, b4 = 9.5733223454, 25.6329561486, 21.0996530827, 3.9584969228
        numerador = u ** 4 + a1 * u ** 3 + a2 * u ** 2 + a3 * u + a4
        denominador = u ** 4 + b1 * u ** 3 + b2 * u ** 2 + b3 * u + b4
        return (numerador / denominador) / (u * math.exp(u))


def parametro_u_theis(r_m: float, s_almacenamiento: float, t_m2s: float, tiempo_s: float) -> float:
    """u = r²·S/(4·T·t)."""
    if t_m2s <= 0 or tiempo_s <= 0:
        raise WellHydraulicsError("T y t deben ser mayores que cero.")
    return r_m ** 2 * s_almacenamiento / (4 * t_m2s * tiempo_s)


def descenso_theis(q_m3s: float, t_m2s: float, s_almacenamiento: float, r_m: float, tiempo_s: float) -> Dict:
    u = parametro_u_theis(r_m, s_almacenamiento, t_m2s, tiempo_s)
    w_u = funcion_pozo_theis(u)
    s = q_m3s / (4 * math.pi * t_m2s) * w_u
    return {"u": u, "W_u": w_u, "s_m": s}


def descenso_cooper_jacob(q_m3s: float, t_m2s: float, s_almacenamiento: float, r_m: float, tiempo_s: float) -> Dict:
    """Simplificación de Cooper-Jacob (válida para u<0.01, tiempos
    prolongados o distancias cortas): s = (2.303Q)/(4πT)·log10(2.25Tt/(r²S))."""
    u = parametro_u_theis(r_m, s_almacenamiento, t_m2s, tiempo_s)
    argumento = 2.25 * t_m2s * tiempo_s / (r_m ** 2 * s_almacenamiento)
    if argumento <= 0:
        raise WellHydraulicsError("El argumento del logaritmo debe ser positivo (revise T, t, r, S).")
    s = (2.303 * q_m3s) / (4 * math.pi * t_m2s) * math.log10(argumento)
    return {"u": u, "valido_u_menor_0_01": u < 0.01, "s_m": s}


def ajustar_cooper_jacob(tiempos_s: Sequence[float], descensos_m: Sequence[float], q_m3s: float,
                          r_m: float) -> Dict:
    """Ajusta la recta s vs. log10(t) (método gráfico estándar de
    Cooper-Jacob) por mínimos cuadrados para obtener T y S a partir de
    un ensayo de bombeo en un único pozo de observación:
    pendiente m = 2.303Q/(4πT) => T = 2.303Q/(4π·m)
    t0 (intersección en s=0) => S = 2.25·T·t0/r²"""
    if len(tiempos_s) < 3:
        raise WellHydraulicsError("Se requieren al menos 3 pares (t, s) para el ajuste de Cooper-Jacob.")
    log_t = [math.log10(t) for t in tiempos_s]
    n = len(log_t)
    media_x = sum(log_t) / n
    media_y = sum(descensos_m) / n
    num = sum((x - media_x) * (y - media_y) for x, y in zip(log_t, descensos_m))
    den = sum((x - media_x) ** 2 for x in log_t)
    if den == 0:
        raise WellHydraulicsError("No se pudo ajustar la recta (varianza nula en log(t)).")
    pendiente = num / den
    intercepto = media_y - pendiente * media_x
    if pendiente <= 0:
        raise WellHydraulicsError("La pendiente debe ser positiva (el descenso debe crecer con el tiempo).")
    t_m2s = 2.303 * q_m3s / (4 * math.pi * pendiente)
    log_t0 = -intercepto / pendiente  # log10(t0) donde s=0
    t0_s = 10 ** log_t0
    s_almacenamiento = 2.25 * t_m2s * t0_s / (r_m ** 2)
    return {"T_m2s": t_m2s, "S": s_almacenamiento, "pendiente": pendiente, "t0_s": t0_s}


# ============================================================================
# 3) PÉRDIDAS DE CARGA EN EL POZO (ENSAYO ESCALONADO)
# ============================================================================

def ajustar_perdidas_pozo(caudales_m3s: Sequence[float], descensos_m: Sequence[float]) -> Dict:
    """sw = B·Q + C·Q² -> sw/Q = B + C·Q (recta), ajustada por mínimos
    cuadrados a partir de un ensayo de bombeo escalonado (varios
    caudales con su descenso total en el pozo)."""
    if len(caudales_m3s) < 2:
        raise WellHydraulicsError("Se requieren al menos 2 escalones de caudal.")
    y = [s / q for s, q in zip(descensos_m, caudales_m3s)]
    x = list(caudales_m3s)
    n = len(x)
    media_x = sum(x) / n
    media_y = sum(y) / n
    num = sum((xi - media_x) * (yi - media_y) for xi, yi in zip(x, y))
    den = sum((xi - media_x) ** 2 for xi in x)
    if den == 0:
        raise WellHydraulicsError("No se pudo ajustar (todos los caudales son iguales).")
    c = num / den
    b = media_y - c * media_x
    return {"B": b, "C": c}


def perdidas_pozo(b: float, c: float, q_m3s: float) -> Dict:
    perdida_acuifero = b * q_m3s
    perdida_pozo = c * q_m3s ** 2
    sw_total = perdida_acuifero + perdida_pozo
    eficiencia_pct = (perdida_acuifero / sw_total * 100.0) if sw_total > 0 else float("nan")
    return {"perdida_acuifero_m": perdida_acuifero, "perdida_pozo_m": perdida_pozo,
            "sw_total_m": sw_total, "eficiencia_pct": eficiencia_pct}


# ============================================================================
# 4) RADIO DE INFLUENCIA
# ============================================================================

def radio_influencia_sichardt(sw_m: float, k_m_s: float) -> float:
    """R = 3000·sw·sqrt(K) (acuíferos libres, régimen estacionario;
    fórmula empírica de Sichardt, K en m/s, sw y R en m)."""
    if sw_m <= 0 or k_m_s <= 0:
        raise WellHydraulicsError("sw y K deben ser mayores que cero.")
    return 3000.0 * sw_m * math.sqrt(k_m_s)


def radio_influencia_kusakin(sw_m: float, h_m: float, k_m_s: float) -> float:
    """R = 2·sw·sqrt(H·K) (acuíferos libres; fórmula de Kusakin)."""
    if sw_m <= 0 or h_m <= 0 or k_m_s <= 0:
        raise WellHydraulicsError("sw, H y K deben ser mayores que cero.")
    return 2.0 * sw_m * math.sqrt(h_m * k_m_s)


def radio_influencia_theis(t_m2s: float, tiempo_s: float, s_almacenamiento: float) -> float:
    """R = sqrt(2.25·T·t/S) (régimen transitorio, acuíferos confinados)."""
    if t_m2s <= 0 or tiempo_s <= 0 or s_almacenamiento <= 0:
        raise WellHydraulicsError("T, t y S deben ser mayores que cero.")
    return math.sqrt(2.25 * t_m2s * tiempo_s / s_almacenamiento)


def radio_influencia_prueba_bombeo(t_m2s: float, q_m3s: float, r_m: float, s_m: float) -> float:
    """Extrapola la recta de Thiem (s vs. ln(r)) hasta s=0, usando la
    transmisividad ya calibrada (p.ej. con transmisividad_thiem_confinado
    o ajustar_cooper_jacob) y UN dato (r, s) medido en campo:
    R = r·exp(2π·T·s/Q) -- el método más exacto según la bibliografía,
    porque proviene directamente de una prueba de bombeo real."""
    if t_m2s <= 0 or q_m3s <= 0 or r_m <= 0:
        raise WellHydraulicsError("T, Q y r deben ser mayores que cero.")
    return r_m * math.exp(2 * math.pi * t_m2s * s_m / q_m3s)


def seleccionar_mejor_radio_influencia(resultados: Dict[str, float], hay_prueba_bombeo: bool,
                                        hay_theis: bool) -> Dict:
    """Selecciona el radio de influencia recomendado según la jerarquía
    de exactitud de la bibliografía: (1) Prueba de bombeo real (el más
    exacto, si está disponible), (2) Theis en régimen transitorio (si
    se cuenta con T, S y t), (3) promedio de las fórmulas empíricas
    Sichardt/Kusakin (estimación preliminar más gruesa)."""
    if not resultados:
        return {}
    if hay_prueba_bombeo and "Prueba de bombeo" in resultados:
        preferido = "Prueba de bombeo"
        motivo = "Método más exacto: proviene directamente de una prueba de bombeo real en campo."
    elif hay_theis and "Theis" in resultados:
        preferido = "Theis"
        motivo = "Sin prueba de bombeo con pozos de observación: se prefiere Theis (base teórica transitoria) sobre las fórmulas puramente empíricas."
    else:
        empiricos = {k: v for k, v in resultados.items() if k in ("Sichardt", "Kusakin")}
        if empiricos:
            preferido = min(empiricos, key=lambda k: abs(empiricos[k] - sum(empiricos.values()) / len(empiricos)))
            motivo = "Solo se dispone de fórmulas empíricas (Sichardt/Kusakin): estimación preliminar, se recomienda contrastar con una prueba de bombeo antes del diseño definitivo."
        else:
            preferido = list(resultados.keys())[0]
            motivo = "Único método disponible con los datos ingresados."
    return {"metodo_recomendado": preferido, "R_recomendado_m": resultados[preferido], "motivo": motivo}
