# -*- coding: utf-8 -*-
"""
core/sediment_transport.py

Motor de cálculo de transporte de sedimentos: inicio del movimiento
(tensión tangencial vs. tensión crítica de Shields), carga de FONDO
(Meyer-Peter y Müller, Einstein-Brown, Bagnold), carga en SUSPENSIÓN
(perfil de Rouse, integrado numéricamente -- enfoque de Lane y
Kalinske) y carga TOTAL (Engelund y Hansen, Yang, Ackers y White).

NOTACIÓN COMÚN: s = ρs/ρw (densidad relativa del sedimento, típico
2.65); d en metros salvo que se indique mm; g = 9.81 m/s²; R = radio
hidráulico (m); S = pendiente de la línea de energía (m/m); V =
velocidad media (m/s); u* = velocidad de corte = sqrt(g·R·S) (m/s).

FÓRMULAS Y FUENTES (todas de uso estándar y ampliamente reproducidas en
la bibliografía de transporte de sedimentos -- Julien "Erosion and
Sedimentation"; Yang "Sediment Transport: Theory and Practice"; Simons
& Sentürk "Sediment Transport Technology"):

  Velocidad de caída (Van Rijn, 1984), según el rango de diámetro.
  Shields crítico (Van Rijn, 1984) en función del diámetro adimensional D*.
  Meyer-Peter y Müller (1948): qb* = 8·(θ-θc)^1.5 (transporte de fondo).
  Einstein-Brown (forma simplificada, muy citada, del método
    probabilístico de Einstein 1950): Φ = 40·Ψ⁻³ (Ψ = 1/θ).
  Bagnold (1966): enfoque de potencia de la corriente (stream power).
  Rouse (1937) / Lane y Kalinske: perfil vertical de concentración
    C(y)/Ca=[(h-y)/y · a/(h-a)]^Z, integrado numéricamente con un
    perfil logarítmico de velocidad para obtener el caudal sólido en
    suspensión.
  Engelund y Hansen (1967): Φ = (0.05/Cf)·θ^2.5 (carga total, ríos
    arenosos con dunas).
  Yang (1973): potencia unitaria de la corriente, muy preciso para
    ríos de lecho arenoso.
  Ackers y White (1973): análisis dimensional, número de movilidad Fgr
    y parámetro de transporte Ggr según el diámetro adimensional Dgr.

TRANSPARENCIA: estos son los métodos estándar reproducidos casi
universalmente en la bibliografía de transporte de sedimentos: los
coeficientes empíricos (especialmente en Einstein-Brown, Bagnold, Yang
y Ackers-White) tienen variantes menores entre autores. Verifique
contra la referencia de su institución antes de un diseño definitivo y
trate el resultado como una ESTIMACIÓN a contrastar entre métodos.
"""
import math
from typing import Dict, List, Optional, Sequence

import numpy as np

G = 9.81
KAPPA = 0.41  # constante de von Kármán
NU_AGUA = 1.0e-6  # viscosidad cinemática del agua, m²/s (20°C aprox.)


class SedimentTransportError(Exception):
    pass


# ============================================================================
# 1) PROPIEDADES DEL SEDIMENTO
# ============================================================================

def velocidad_caida_van_rijn(d_mm: float, rho_s: float = 2650.0, rho_w: float = 1000.0,
                              nu: float = NU_AGUA) -> float:
    """Velocidad de caída ws (m/s) por el método de Van Rijn (1984), en
    tres regímenes según el diámetro de la partícula (d en mm)."""
    if d_mm <= 0:
        raise SedimentTransportError("El diámetro debe ser mayor que cero.")
    d = d_mm / 1000.0
    s_rel = (rho_s - rho_w) / rho_w
    if d_mm <= 0.1:
        return (s_rel * G * d ** 2) / (18 * nu)
    elif d_mm <= 1.0:
        return (10 * nu / d) * (math.sqrt(1 + 0.01 * s_rel * G * d ** 3 / nu ** 2) - 1)
    else:
        return 1.1 * math.sqrt(s_rel * G * d)


def diametro_adimensional(d_mm: float, rho_s: float = 2650.0, rho_w: float = 1000.0,
                           nu: float = NU_AGUA) -> float:
    """D* = d·[(s-1)·g/nu²]^(1/3), diámetro adimensional de Van Rijn."""
    d = d_mm / 1000.0
    s_rel = (rho_s - rho_w) / rho_w
    return d * (s_rel * G / nu ** 2) ** (1.0 / 3.0)


# ============================================================================
# 2) INICIO DEL MOVIMIENTO
# ============================================================================

def tension_tangencial(gamma_agua_n_m3: float, r_m: float, s_pendiente: float) -> float:
    """tau0 = gamma*R*S (Pa)."""
    return gamma_agua_n_m3 * r_m * s_pendiente


def shields_critico_van_rijn(d_mm: float, rho_s: float = 2650.0, rho_w: float = 1000.0,
                              nu: float = NU_AGUA) -> Dict:
    """theta_critico y tau_critico (Pa), aproximación explícita de Van
    Rijn (1984) por tramos del diámetro adimensional D*."""
    d_star = diametro_adimensional(d_mm, rho_s, rho_w, nu)
    if d_star <= 4:
        theta_cr = 0.24 * d_star ** -1.0
    elif d_star <= 10:
        theta_cr = 0.14 * d_star ** -0.64
    elif d_star <= 20:
        theta_cr = 0.04 * d_star ** -0.10
    elif d_star <= 150:
        theta_cr = 0.013 * d_star ** 0.29
    else:
        theta_cr = 0.055
    d_m = d_mm / 1000.0
    tau_cr = theta_cr * (rho_s - rho_w) * G * d_m
    return {"D_star": d_star, "theta_critico": theta_cr, "tau_critico_Pa": tau_cr}


def evaluar_inicio_movimiento(tau0_pa: float, tau_critico_pa: float) -> Dict:
    return {"tau0_Pa": tau0_pa, "tau_critico_Pa": tau_critico_pa,
            "hay_transporte": tau0_pa > tau_critico_pa,
            "razon_tau0_tauc": tau0_pa / tau_critico_pa if tau_critico_pa > 0 else float("inf")}


# ============================================================================
# 3) CARGA DE FONDO
# ============================================================================

def meyer_peter_muller(tau0_pa: float, d_mm: float, rho_s: float = 2650.0,
                        rho_w: float = 1000.0) -> Dict:
    """qb* = 8*(theta-theta_c)^1.5 (Meyer-Peter y Müller, 1948). Devuelve
    el caudal sólido de fondo por unidad de ancho en m³/s/m (volumétrico,
    sedimento suelto)."""
    d_m = d_mm / 1000.0
    s = rho_s / rho_w
    shields = shields_critico_van_rijn(d_mm, rho_s, rho_w)
    theta = tau0_pa / ((rho_s - rho_w) * G * d_m)
    theta_c = shields["theta_critico"]
    if theta <= theta_c:
        return {"metodo": "Meyer-Peter y Müller", "theta": theta, "theta_c": theta_c,
                "qb_m3_s_m": 0.0, "transporte_activo": False}
    qb_adim = 8.0 * (theta - theta_c) ** 1.5
    qb = qb_adim * math.sqrt((s - 1) * G * d_m ** 3)
    return {"metodo": "Meyer-Peter y Müller", "theta": theta, "theta_c": theta_c,
            "qb_adimensional": qb_adim, "qb_m3_s_m": qb, "transporte_activo": True}


def einstein_brown(tau0_pa: float, r_m: float, s_pendiente: float, d_mm: float,
                    rho_s: float = 2650.0, rho_w: float = 1000.0) -> Dict:
    """Forma simplificada de Einstein-Brown (aproximación muy citada del
    método probabilístico de Einstein): Phi = 40*Psi^-3, Psi = 1/theta."""
    d_m = d_mm / 1000.0
    s = rho_s / rho_w
    theta = tau0_pa / ((rho_s - rho_w) * G * d_m)
    if theta <= 0:
        return {"metodo": "Einstein-Brown", "theta": theta, "qb_m3_s_m": 0.0, "transporte_activo": False}
    psi = 1.0 / theta
    phi = 40.0 * psi ** -3
    qb = phi * math.sqrt((s - 1) * G * d_m ** 3)
    advertencia = None
    if psi < 1.0:
        advertencia = ("Psi<1 (theta>1): intensidad de transporte muy alta, fuera del rango en que la "
                        "aproximación asintótica de Einstein-Brown es confiable; contrastar con MPM/Bagnold.")
    return {"metodo": "Einstein-Brown", "theta": theta, "Psi": psi, "Phi": phi,
            "qb_m3_s_m": qb, "transporte_activo": qb > 0, "advertencia": advertencia}


def bagnold_carga_fondo(tau0_pa: float, v_m_s: float, eb: float = 0.15, tan_alpha: float = 0.63,
                         rho_s: float = 2650.0, rho_w: float = 1000.0) -> Dict:
    """Bagnold (1966): enfoque de potencia de la corriente (stream power).
    omega = tau0*V (W/m²); ib = (eb/tan(alpha))*omega (tasa de transporte
    en peso sumergido, N/s/m); qb = ib/((rho_s-rho_w)*g) (m³/s/m).
    eb: eficiencia de transporte de fondo (típico 0.10-0.20).
    tan_alpha: coeficiente de fricción dinámica del sedimento (típico
    0.32 a 0.75 según angulosidad; 0.63 valor por defecto típico de arena)."""
    omega = tau0_pa * v_m_s  # W/m2
    ib = (eb / tan_alpha) * omega  # N/s/m (peso sumergido por unidad de ancho y tiempo)
    qb = ib / ((rho_s - rho_w) * G)
    return {"metodo": "Bagnold", "omega_W_m2": omega, "ib_N_s_m": ib, "qb_m3_s_m": qb,
            "transporte_activo": qb > 0}


# ============================================================================
# 4) CARGA EN SUSPENSIÓN -- ROUSE / LANE Y KALINSKE (integración numérica)
# ============================================================================

def numero_rouse(ws_m_s: float, u_estrella_m_s: float) -> float:
    if u_estrella_m_s <= 0:
        raise SedimentTransportError("La velocidad de corte debe ser mayor que cero.")
    return ws_m_s / (KAPPA * u_estrella_m_s)


def carga_suspension_rouse(h_m: float, u_estrella_m_s: float, ws_m_s: float,
                            ca_concentracion: float, a_relativo: float = 0.05,
                            n_puntos: int = 200) -> Dict:
    """Integra numéricamente el perfil de Rouse (concentración) junto con
    un perfil logarítmico de velocidad, entre la altura de referencia
    a=a_relativo*h (típico 5% del tirante) y la superficie, para obtener
    el caudal sólido en suspensión por unidad de ancho qs (m³/s/m).
    ca_concentracion: concentración de referencia en 'a' (fracción
    volumétrica, medida con muestreador físico o estimada aparte)."""
    if h_m <= 0 or u_estrella_m_s <= 0:
        raise SedimentTransportError("El tirante y la velocidad de corte deben ser mayores que cero.")
    a = a_relativo * h_m
    z = numero_rouse(ws_m_s, u_estrella_m_s)
    y = np.linspace(a, h_m, n_puntos)
    # perfil de concentración de Rouse (normalizado con Ca en y=a)
    c_rel = ((h_m - y) / y * a / (h_m - a)) ** z
    c_rel = np.clip(c_rel, 0, None)
    c_perfil = ca_concentracion * c_rel
    # perfil logarítmico de velocidad (ley de la pared), y0 = a/30 (fondo hidráulicamente rugoso simplificado)
    y0 = a / 30.0
    u_perfil = (u_estrella_m_s / KAPPA) * np.log(np.maximum(y / y0, 1.0001))
    integrando = u_perfil * c_perfil
    trapecio = getattr(np, "trapezoid", None) or np.trapz
    qs = float(trapecio(integrando, y))  # m3/s/m (si c_perfil es fracción volumétrica)
    return {"metodo": "Rouse / Lane y Kalinske (integración numérica)", "Z_rouse": z,
            "a_m": a, "qs_m3_s_m": qs, "perfil_y": y.tolist(), "perfil_concentracion": c_perfil.tolist(),
            "perfil_velocidad": u_perfil.tolist()}


# ============================================================================
# 5) CARGA TOTAL
# ============================================================================

def engelund_hansen(tau0_pa: float, v_m_s: float, r_m: float, s_pendiente: float, d_mm: float,
                     rho_s: float = 2650.0, rho_w: float = 1000.0) -> Dict:
    """Engelund y Hansen (1967): Phi = (0.05/Cf)*theta^2.5, Cf = g*R*S/V²."""
    d_m = d_mm / 1000.0
    s = rho_s / rho_w
    if v_m_s <= 0:
        raise SedimentTransportError("La velocidad media debe ser mayor que cero (Engelund-Hansen).")
    cf = (G * r_m * s_pendiente) / v_m_s ** 2
    theta = tau0_pa / ((rho_s - rho_w) * G * d_m)
    phi = (0.05 / cf) * theta ** 2.5
    qt = phi * math.sqrt((s - 1) * G * d_m ** 3)
    return {"metodo": "Engelund y Hansen", "Cf": cf, "theta": theta, "Phi": phi, "qt_m3_s_m": qt}


def yang_1973(v_m_s: float, u_estrella_m_s: float, ws_m_s: float, d_mm: float,
              nu: float = NU_AGUA) -> Dict:
    """Yang (1973), fórmula para arenas: log(Ct) en ppm por peso.
    Vcr/ws según el número de Reynolds de la partícula (u*d/nu)."""
    if ws_m_s <= 0 or u_estrella_m_s <= 0:
        raise SedimentTransportError("ws y u* deben ser mayores que cero (Yang).")
    d_m = d_mm / 1000.0
    re_p = u_estrella_m_s * d_m / nu
    if re_p >= 70:
        vcr_ws = 2.05
    else:
        vcr_ws = 2.5 / (math.log10(max(re_p, 1e-6)) - 0.06) + 0.66
    vcr = vcr_ws * ws_m_s
    term_vs = v_m_s * 0 + 0  # placeholder para claridad de unidades (V*S/ws se calcula abajo con S)
    log_ws_d_nu = math.log10(ws_m_s * d_m / nu) if ws_m_s * d_m / nu > 0 else 0.0
    log_u_ws = math.log10(u_estrella_m_s / ws_m_s)
    return {"metodo": "Yang (1973)", "Re_particula": re_p, "Vcr_m_s": vcr,
            "log_ws_d_nu": log_ws_d_nu, "log_u_estrella_ws": log_u_ws}


def yang_1973_concentracion(v_m_s: float, s_pendiente: float, u_estrella_m_s: float,
                             ws_m_s: float, d_mm: float, q_m3_s: float, ancho_m: float,
                             nu: float = NU_AGUA) -> Dict:
    """Completa Yang (1973): calcula log(Ct) y el caudal sólido total
    qt (m³/s) a partir de la concentración total en ppm por peso."""
    base = yang_1973(v_m_s, u_estrella_m_s, ws_m_s, d_mm, nu)
    vcr = base["Vcr_m_s"]
    arg = (v_m_s * s_pendiente - vcr * s_pendiente) / ws_m_s
    if arg <= 0:
        return {**base, "log_Ct": None, "Ct_ppm": 0.0, "qt_m3_s": 0.0, "transporte_activo": False}
    log_ct = (5.435 - 0.286 * base["log_ws_d_nu"] - 0.457 * base["log_u_estrella_ws"]
              + (1.799 - 0.409 * base["log_ws_d_nu"] - 0.314 * base["log_u_estrella_ws"]) * math.log10(arg))
    ct_ppm = 10 ** log_ct
    # Ct en ppm por peso (mg de sedimento / kg de agua-sedimento aprox.) -> caudal másico y volumétrico
    caudal_masico_agua_kg_s = q_m3_s * 1000.0
    masa_sedimento_kg_s = ct_ppm * 1e-6 * caudal_masico_agua_kg_s
    qt_m3_s = masa_sedimento_kg_s / 2650.0
    return {**base, "log_Ct": log_ct, "Ct_ppm": ct_ppm, "qt_m3_s": qt_m3_s,
            "qt_m3_s_m": qt_m3_s / ancho_m if ancho_m > 0 else None, "transporte_activo": True}


def ackers_white(v_m_s: float, r_m: float, d_mm: float, rho_s: float = 2650.0,
                  rho_w: float = 1000.0, nu: float = NU_AGUA) -> Dict:
    """Ackers y White (1973): número de movilidad Fgr y parámetro de
    transporte Ggr, con coeficientes A, C, m, n según el diámetro
    adimensional Dgr (régimen transicional 1<Dgr<=60, o grueso Dgr>60)."""
    d_m = d_mm / 1000.0
    s = rho_s / rho_w
    dgr = d_m * (G * (s - 1) / nu ** 2) ** (1.0 / 3.0)
    if dgr <= 1:
        raise SedimentTransportError("Ackers-White no es aplicable para Dgr<=1 (partícula demasiado fina).")
    if dgr <= 60:
        n = 1 - 0.56 * math.log10(dgr)
        a_coef = 0.23 / math.sqrt(dgr) + 0.14
        m_coef = 9.66 / dgr + 1.34
        c_coef = 10 ** (2.86 * math.log10(dgr) - (math.log10(dgr)) ** 2 - 3.53)
    else:
        n, a_coef, m_coef, c_coef = 0.0, 0.17, 1.50, 0.025

    u_estrella = math.sqrt(G * r_m * (v_m_s ** 2) / (18 * math.log10(10 * r_m / d_m) ** 2 * r_m)) \
        if r_m > 0 else 0.0
    # u* a partir de la ecuación de resistencia de Ackers-White (aprox. Colebrook-White):
    # V/u* = 5.75*log10(10*R/d)  =>  u* = V / (5.75*log10(10R/d))
    u_estrella = v_m_s / (5.75 * math.log10(10 * r_m / d_m))
    if u_estrella <= 0:
        raise SedimentTransportError("No se pudo calcular u* (verifique R y d).")

    fgr = (u_estrella ** n / math.sqrt(G * d_m * (s - 1))) * (v_m_s / (math.sqrt(32) * math.log10(10 * r_m / d_m))) ** (1 - n)
    if fgr <= a_coef:
        return {"metodo": "Ackers y White", "Dgr": dgr, "Fgr": fgr, "A": a_coef, "n": n,
                "Ggr": 0.0, "Xgr_ppm": 0.0, "qt_m3_s_m": 0.0, "transporte_activo": False}
    ggr = c_coef * (fgr / a_coef - 1) ** m_coef
    xgr = ggr * (d_m / r_m) * (v_m_s / u_estrella) ** n  # concentración por peso (fracción)
    qt_masico = xgr * rho_w * v_m_s * r_m  # kg/s/m aprox. (X * rho_agua * V * R, forma estándar simplificada)
    qt_m3_s_m = qt_masico / rho_s
    return {"metodo": "Ackers y White", "Dgr": dgr, "Fgr": fgr, "Ggr": ggr, "A": a_coef,
            "n": n, "m": m_coef, "C": c_coef, "Xgr": xgr, "qt_m3_s_m": qt_m3_s_m, "transporte_activo": True}


# ============================================================================
# 6) RESUMEN COMPARATIVO
# ============================================================================

def resumen_comparativo(resultados_por_metodo: Dict[str, float]) -> Dict:
    if not resultados_por_metodo:
        return {}
    metodo_max = max(resultados_por_metodo, key=lambda k: resultados_por_metodo[k])
    valores = list(resultados_por_metodo.values())
    return {
        "metodo_gobernante": metodo_max,
        "qt_diseño_recomendado": resultados_por_metodo[metodo_max],
        "promedio": sum(valores) / len(valores),
        "minimo": min(valores),
        "maximo": max(valores),
    }
