# -*- coding: utf-8 -*-
"""
core/debris_flow.py

Motor de cálculo de flujos hiperconcentrados, de lodos y de detritos
("debris flow"): clasificación por concentración volumétrica de
sedimentos (Cv), reología de Bingham, factor de amplificación por
sedimento (bulking factor) y dos métodos de cálculo de velocidad/tirante:
resistencia de O'Brien y Julien (general, válido para hiperconcentrado/
lodos/detritos con reología calibrada) y velocidad crítica de Takahashi
(específico para flujos de detritos maduros, granulometría gruesa).

CLASIFICACIÓN (criterio de concentración volumétrica Cv):
    Cv < 20%             -> Fluvial convencional (newtoniano)
    20% <= Cv < 45%       -> Flujo Hiperconcentrado (transición)
    45% <= Cv < 55%       -> Flujo de Lodos (cohesivo, Bingham)
    Cv >= 55%             -> Flujo de Detritos (granular-viscoso)

REOLOGÍA DE BINGHAM: tau = tau_y + mu_p*(dv/dy). Estimación empírica de
Julien y Lan (1991) cuando no hay ensayos de viscosímetro:
    tau_y = alpha1 * exp(beta1*Cv)
    mu_p  = alpha2 * exp(beta2*Cv)
(alpha y beta son coeficientes empíricos que dependen del tipo de
suelo/arcilla de la cuenca -- se dejan editables, sin un valor único
"correcto"; deben calibrarse con ensayos de campo/laboratorio siempre
que sea posible).

RESISTENCIA DE O'BRIEN Y JULIEN (1985): combina resistencia de fluencia,
viscosa y turbulenta-dispersiva:
    Sf = tau_y/(gamma_m*h) + 3*mu_p*V/(gamma_m*h^2) + n_td^2*V^2/h^(4/3)
    gamma_m = gamma_w + Cv*(gamma_s - gamma_w)

VELOCIDAD CRÍTICA DE TAKAHASHI (flujos de detritos maduros):
    V = (2/3)*(h/sqrt(d*lambda))*sqrt(g*sin(theta)/ai)
    lambda = [(Cmax/Cv)^(1/3) - 1]^-1  (concentración lineal de esferas)

FACTOR DE AMPLIFICACIÓN (BULKING FACTOR): BF = 1/(1-Cv);
Q_mezcla = Q_líquido * BF.

TRANSPARENCIA: estos son los métodos estándar de la bibliografía de
flujos hiperconcentrados/detritos (Julien, "Erosion and Sedimentation";
O'Brien & Julien, 1985; Takahashi, "Debris Flow: Mechanics, Prediction
and Countermeasures"). Los coeficientes empíricos (alpha/beta de
Julien-Lan, n_td, a_i) varían según la cuenca y el tipo de material;
trate el resultado como una ESTIMACIÓN preliminar de validación, no
como sustituto de la modelación numérica 2D (FLO-2D, HEC-RAS, RAMMS)
para el diseño definitivo.
"""
import math
from typing import Dict, Optional

G = 9.81
GAMMA_AGUA_N_M3 = 9810.0
GAMMA_SOLIDOS_N_M3 = 26000.0  # peso específico típico de partículas minerales (2650 kg/m3)


class DebrisFlowError(Exception):
    pass


# ============================================================================
# 1) CLASIFICACIÓN DEL FLUJO
# ============================================================================

def clasificar_flujo(cv: float) -> str:
    if cv < 0 or cv >= 1:
        raise DebrisFlowError("La concentración volumétrica Cv debe estar entre 0 y 1 (0-100%).")
    if cv < 0.20:
        return "Fluvial convencional"
    elif cv < 0.45:
        return "Flujo Hiperconcentrado"
    elif cv < 0.55:
        return "Flujo de Lodos"
    else:
        return "Flujo de Detritos"


def peso_especifico_mezcla(cv: float, gamma_w: float = GAMMA_AGUA_N_M3,
                            gamma_s: float = GAMMA_SOLIDOS_N_M3) -> float:
    """gamma_m = gamma_w + Cv*(gamma_s - gamma_w), peso específico de la mezcla (N/m³)."""
    return gamma_w + cv * (gamma_s - gamma_w)


def bulking_factor(cv: float) -> float:
    """BF = 1/(1-Cv)."""
    if cv >= 1:
        raise DebrisFlowError("Cv debe ser menor que 1 para calcular el factor de amplificación.")
    return 1.0 / (1.0 - cv)


def caudal_mezcla(q_liquido_m3s: float, cv: float) -> Dict:
    bf = bulking_factor(cv)
    return {"BF": bf, "Q_mezcla_m3s": q_liquido_m3s * bf}


# ============================================================================
# 2) REOLOGÍA DE BINGHAM (estimación empírica de Julien y Lan, 1991)
# ============================================================================

def reologia_bingham_empirica(cv: float, alpha1: float, beta1: float,
                               alpha2: float, beta2: float) -> Dict:
    """tau_y = alpha1*exp(beta1*Cv) (Pa); mu_p = alpha2*exp(beta2*Cv) (Pa·s).
    alpha1, beta1, alpha2, beta2: coeficientes empíricos calibrados con
    ensayos de viscosímetro para el material de la cuenca (no hay un
    valor universal -- ingréselos según su estudio geotécnico, o use los
    valores por defecto solo como referencia orientativa inicial)."""
    tau_y = alpha1 * math.exp(beta1 * cv)
    mu_p = alpha2 * math.exp(beta2 * cv)
    return {"tau_y_Pa": tau_y, "mu_p_Pa_s": mu_p}


# ============================================================================
# 3) RESISTENCIA DE O'BRIEN Y JULIEN
# ============================================================================

def pendiente_friccion_obrien_julien(h_m: float, v_m_s: float, tau_y_pa: float, mu_p_pa_s: float,
                                      n_td: float, gamma_m_n_m3: float) -> Dict:
    """Sf (pendiente de fricción total) para un tirante h y velocidad V
    dados -- útil como diagnóstico o para construir una curva de descarga."""
    if h_m <= 0:
        raise DebrisFlowError("El tirante h debe ser mayor que cero.")
    s_fluencia = tau_y_pa / (gamma_m_n_m3 * h_m)
    s_viscosa = 3 * mu_p_pa_s * v_m_s / (gamma_m_n_m3 * h_m ** 2)
    s_turbulenta = (n_td ** 2) * (v_m_s ** 2) / (h_m ** (4.0 / 3.0))
    return {"Sf": s_fluencia + s_viscosa + s_turbulenta, "S_fluencia": s_fluencia,
            "S_viscosa": s_viscosa, "S_turbulenta_dispersiva": s_turbulenta}


def resolver_tirante_obrien_julien(q_mezcla_m3s: float, b_m: float, s_pendiente: float,
                                    tau_y_pa: float, mu_p_pa_s: float, n_td: float,
                                    gamma_m_n_m3: float, tol: float = 1e-5, max_iter: int = 200) -> Dict:
    """Resuelve por bisección el tirante h (canal rectangular de ancho b)
    tal que, con V=Q/(b·h) por continuidad, la pendiente de fricción de
    O'Brien-Julien Sf(h,V) iguale la pendiente del canal S (flujo
    uniforme supuesto)."""
    if b_m <= 0 or q_mezcla_m3s <= 0:
        raise DebrisFlowError("Q y el ancho b deben ser mayores que cero.")

    def residual(h):
        if h <= 1e-6:
            return 1e9
        v = q_mezcla_m3s / (b_m * h)
        sf = pendiente_friccion_obrien_julien(h, v, tau_y_pa, mu_p_pa_s, n_td, gamma_m_n_m3)["Sf"]
        return sf - s_pendiente

    h_lo, h_hi = 1e-3, 50.0
    r_lo, r_hi = residual(h_lo), residual(h_hi)
    if r_lo * r_hi > 0:
        h_hi = 200.0
        r_hi = residual(h_hi)
        if r_lo * r_hi > 0:
            raise DebrisFlowError("O'Brien-Julien: no se encontró un tirante de equilibrio en el rango 0.001-200 m.")
    for _ in range(max_iter):
        h_mid = 0.5 * (h_lo + h_hi)
        r_mid = residual(h_mid)
        if abs(r_mid) < tol:
            break
        if r_lo * r_mid <= 0:
            h_hi, r_hi = h_mid, r_mid
        else:
            h_lo, r_lo = h_mid, r_mid
    h_final = 0.5 * (h_lo + h_hi)
    v_final = q_mezcla_m3s / (b_m * h_final)
    detalle = pendiente_friccion_obrien_julien(h_final, v_final, tau_y_pa, mu_p_pa_s, n_td, gamma_m_n_m3)
    return {"metodo": "O'Brien y Julien", "h_m": h_final, "V_m_s": v_final, **detalle}


# ============================================================================
# 4) VELOCIDAD CRÍTICA DE TAKAHASHI
# ============================================================================

def concentracion_lineal_takahashi(cv: float, cmax: float = 0.65) -> float:
    """lambda = [(Cmax/Cv)^(1/3) - 1]^-1, concentración lineal de esferas."""
    if cv <= 0 or cv >= cmax:
        raise DebrisFlowError("Cv debe ser mayor que 0 y menor que Cmax para Takahashi.")
    base = (cmax / cv) ** (1.0 / 3.0) - 1.0
    if base <= 0:
        raise DebrisFlowError("Concentración lineal indefinida (Cv demasiado cercano a Cmax).")
    return 1.0 / base


def velocidad_takahashi(h_m: float, d_mm: float, cv: float, theta_grados: float,
                         cmax: float = 0.65, a_i: float = 0.02) -> Dict:
    """V = (2/3)*(h/sqrt(d*lambda))*sqrt(g*sin(theta)/ai)."""
    if h_m <= 0 or d_mm <= 0:
        raise DebrisFlowError("h y d deben ser mayores que cero (Takahashi).")
    d_m = d_mm / 1000.0
    lam = concentracion_lineal_takahashi(cv, cmax)
    theta = math.radians(theta_grados)
    v = (2.0 / 3.0) * (h_m / math.sqrt(d_m * lam)) * math.sqrt(G * math.sin(theta) / a_i)
    return {"lambda_concentracion_lineal": lam, "V_m_s": v}


def resolver_tirante_takahashi(q_mezcla_m3s: float, b_m: float, d_mm: float, cv: float,
                                theta_grados: float, cmax: float = 0.65, a_i: float = 0.02,
                                tol: float = 1e-5, max_iter: int = 200) -> Dict:
    """Resuelve por bisección el tirante h (canal rectangular de ancho b)
    tal que V_Takahashi(h) y V_continuidad(h)=Q/(b·h) coincidan."""
    if b_m <= 0 or q_mezcla_m3s <= 0:
        raise DebrisFlowError("Q y el ancho b deben ser mayores que cero.")

    def residual(h):
        if h <= 1e-6:
            return 1e9
        v_continuidad = q_mezcla_m3s / (b_m * h)
        v_takahashi = velocidad_takahashi(h, d_mm, cv, theta_grados, cmax, a_i)["V_m_s"]
        return v_continuidad - v_takahashi

    h_lo, h_hi = 1e-3, 50.0
    r_lo, r_hi = residual(h_lo), residual(h_hi)
    if r_lo * r_hi > 0:
        h_hi = 200.0
        r_hi = residual(h_hi)
        if r_lo * r_hi > 0:
            raise DebrisFlowError("Takahashi: no se encontró un tirante de equilibrio en el rango 0.001-200 m.")
    for _ in range(max_iter):
        h_mid = 0.5 * (h_lo + h_hi)
        r_mid = residual(h_mid)
        if abs(r_mid) < tol:
            break
        if r_lo * r_mid <= 0:
            h_hi, r_hi = h_mid, r_mid
        else:
            h_lo, r_lo = h_mid, r_mid
    h_final = 0.5 * (h_lo + h_hi)
    v_final = q_mezcla_m3s / (b_m * h_final)
    detalle = velocidad_takahashi(h_final, d_mm, cv, theta_grados, cmax, a_i)
    return {"metodo": "Takahashi", "h_m": h_final, "V_m_s": v_final, **detalle}


# ============================================================================
# 5) FROUDE Y RESUMEN / MEJOR PROPUESTA
# ============================================================================

def numero_froude(v_m_s: float, h_m: float) -> float:
    if h_m <= 0:
        return 0.0
    return v_m_s / math.sqrt(G * h_m)


def seleccionar_mejor_propuesta(clasificacion: str, resultados: Dict[str, Dict]) -> Dict:
    """A diferencia de socavación/sedimentos (donde se adopta el máximo
    como envolvente conservadora), O'Brien-Julien y Takahashi estiman el
    mismo tirante/velocidad de equilibrio con hipótesis físicas
    DISTINTAS -- no tiene sentido promediarlos ni tomar el máximo. Se
    recomienda el método más específico para la clase de flujo
    diagnosticada: Takahashi para Flujo de Detritos maduro (granular
    grueso), O'Brien y Julien para Hiperconcentrado/Lodos (reología de
    Bingham, más general)."""
    if not resultados:
        return {}
    if clasificacion == "Flujo de Detritos" and "Takahashi" in resultados:
        preferido = "Takahashi"
        motivo = "Flujo de Detritos maduro: Takahashi es el método específico para este régimen granular grueso."
    elif "O'Brien y Julien" in resultados:
        preferido = "O'Brien y Julien"
        motivo = "Método general de resistencia (reología de Bingham calibrada), aplicable a hiperconcentrado/lodos."
    else:
        preferido = list(resultados.keys())[0]
        motivo = "Único método disponible con los datos ingresados."
    return {"metodo_recomendado": preferido, "motivo": motivo, "resultado": resultados[preferido]}
