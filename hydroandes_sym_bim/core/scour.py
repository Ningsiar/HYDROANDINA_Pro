# -*- coding: utf-8 -*-
"""
core/scour.py

Motor de cálculo de socavación (Pestaña "Socavación"): socavación
GENERAL (degradación del fondo del cauce en avenida), socavación por
CONTRACCIÓN (estrechamiento del cauce) y socavación LOCAL (pilares y
estribos de puentes), para suelos cohesivos y no cohesivos.

MÉTODOS IMPLEMENTADOS Y FUENTES:

  GENERAL
  -------
  Lischtvan-Lebediev (1959): método de "velocidad erosiva vs. velocidad
  real", el más usado en Latinoamérica (reproducido en el Manual de
  Hidrología, Hidráulica y Drenaje del MTC-Perú, y en Juárez Badillo &
  Rico Rodríguez, "Mecánica de Suelos"). Calcula, vertical por vertical
  de la sección, el tirante de equilibrio erosionado He a partir del
  tirante real Hi, el coeficiente de sección alpha, el coeficiente beta
  (periodo de retorno) y el diámetro medio del material (no cohesivo) o
  el peso específico seco (cohesivo).

  Lacey (1930) / régimen: dsm = 1.34*(q^2/f)^(1/3), f = 1.76*sqrt(Dm_mm),
  fórmula de régimen para lechos móviles con transporte continuo,
  ampliamente adoptada en códigos de puentes de la India/Pakistán
  (IRC:78) y citada en manuales latinoamericanos como método de
  contraste de la socavación general.

  Blench (1969) / régimen: dsm = 1.48*(q^2/Fb)^(1/3), Fb = 1.9*sqrt(Dm_mm).

  Neill & Kellerhals: velocidad competente para lechos de grava gruesa
  (Neill, 1967): Vc = 1.702 * y^(1/6) * D^(1/3) (SI, y y D en metros);
  se resuelve el tirante de equilibrio y tal que la velocidad media por
  continuidad (Q/(Be*y)) iguale la velocidad competente Vc(y).

  LOCAL (pilares)
  ---------------
  CSU / HEC-RAS (Richardson & Davis, HEC-18, FHWA): ecuación estándar
      ys/y1 = 2.0*K1*K2*K3*K4*(a/y1)^0.65 * Fr1^0.43

  Froehlich (1991), ecuación de diseño reproducida en HEC-18:
      ys = 0.32*Kf*(a')^0.62 * y1^0.47 * Fr1^0.22 * D50^-0.09 + a

  CONTRACCIÓN
  -----------
  Laursen (1960/1963), reproducidas en HEC-18:
    Lecho móvil:  y2/y1 = (Q2/Q1)^(6/7) * (W1/W2)^k1
    Agua clara:   y2 = [(Ku*Q2^2)/(Dm^(2/3)*W2^2)]^(3/7), Ku=0.0246 (SI)

TRANSPARENCIA: estas son las fórmulas estándar reproducidas de forma
prácticamente universal en la bibliografía de hidráulica fluvial y en
HEC-18 (FHWA); los coeficientes tabulados (x de Lischtvan-Lebediev, K1
a K4 de CSU, Kf de Froehlich, k1 de Laursen) son los valores más
comúnmente citados. Verifique contra la referencia de su institución
antes de un diseño definitivo, y trate siempre el resultado como una
ESTIMACIÓN a contrastar entre métodos (de ahí el cuadro comparativo).
"""
import math
from typing import Dict, List, Optional, Sequence, Tuple

G = 9.81  # m/s2


class SocavacionError(Exception):
    pass


# ============================================================================
# 1) CURVA GRANULOMÉTRICA -> DIÁMETROS CARACTERÍSTICOS
# ============================================================================

def ordenar_curva(curva_mm_pasa: Sequence[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """Ordena la curva granulométrica (diámetro_mm, %que_pasa) por diámetro
    ascendente y descarta filas inválidas (diámetro<=0 o %pasa fuera de 0-100)."""
    limpio = [(float(d), float(p)) for d, p in curva_mm_pasa if d and 0.0 <= float(p) <= 100.0]
    limpio = [x for x in limpio if x[0] > 0]
    limpio.sort(key=lambda x: x[0])
    if len(limpio) < 2:
        raise SocavacionError("La curva granulométrica necesita al menos 2 puntos válidos (diámetro>0, %pasa entre 0 y 100).")
    return limpio


def interpolar_diametro(curva_ordenada: List[Tuple[float, float]], pct_objetivo: float) -> float:
    """Interpola en escala log-lineal (estándar en granulometría: %pasa es
    lineal, diámetro en log10) el diámetro (mm) correspondiente a un
    porcentaje que pasa dado (p.ej. 50 -> D50, 84 -> D84)."""
    diam = [p[0] for p in curva_ordenada]
    pasa = [p[1] for p in curva_ordenada]
    if pct_objetivo <= pasa[0]:
        # extrapola levemente en log-espacio usando el primer tramo
        if len(pasa) < 2 or pasa[1] == pasa[0]:
            return diam[0]
        i0, i1 = 0, 1
    elif pct_objetivo >= pasa[-1]:
        i0, i1 = len(pasa) - 2, len(pasa) - 1
    else:
        i0 = max(i for i in range(len(pasa) - 1) if pasa[i] <= pct_objetivo)
        i1 = i0 + 1
    p0, p1 = pasa[i0], pasa[i1]
    d0, d1 = diam[i0], diam[i1]
    if p1 == p0:
        return d0
    frac = (pct_objetivo - p0) / (p1 - p0)
    log_d = math.log10(d0) + frac * (math.log10(d1) - math.log10(d0))
    return 10 ** log_d


def calcular_diametros_caracteristicos(curva_mm_pasa: Sequence[Tuple[float, float]]) -> Dict[str, float]:
    """Devuelve D16, D35, D50, D65, D84, D90, el diámetro medio ponderado Dm
    (media aritmética simple de D16/D50/D84, aproximación estándar cuando no
    se dispone de todas las fracciones retenidas) y la desviación estándar
    geométrica sigma_g = sqrt(D84/D16) (índice de uniformidad del material;
    sigma_g < 3 se considera material bien graduado/uniforme)."""
    curva = ordenar_curva(curva_mm_pasa)
    d16 = interpolar_diametro(curva, 16)
    d35 = interpolar_diametro(curva, 35)
    d50 = interpolar_diametro(curva, 50)
    d65 = interpolar_diametro(curva, 65)
    d84 = interpolar_diametro(curva, 84)
    d90 = interpolar_diametro(curva, 90)
    dm = (d16 + d50 + d84) / 3.0
    sigma_g = math.sqrt(d84 / d16) if d16 > 0 else float("nan")
    return {"D16": d16, "D35": d35, "D50": d50, "D65": d65, "D84": d84, "D90": d90,
            "Dm": dm, "sigma_g": sigma_g}


# ============================================================================
# 2) LISCHTVAN-LEBEDIEV
# ============================================================================

# Tabla estándar x = f(Dm en mm) para suelos NO cohesivos (MTC-Perú /
# Juárez Badillo). Interpolación lineal entre puntos tabulados.
_TABLA_X_NO_COHESIVO = [
    (0.05, 0.43), (0.15, 0.42), (0.50, 0.41), (1.00, 0.40), (1.50, 0.39),
    (2.50, 0.38), (4.00, 0.37), (6.00, 0.36), (8.00, 0.35), (10.00, 0.34),
    (15.00, 0.33), (20.00, 0.32), (25.00, 0.31), (40.00, 0.30), (60.00, 0.29),
    (90.00, 0.28), (140.00, 0.27), (190.00, 0.26), (250.00, 0.25),
]

# Tabla estándar x = f(peso específico seco gamma_d en t/m3) para suelos
# COHESIVOS (mismas fuentes).
_TABLA_X_COHESIVO = [
    (0.80, 0.52), (0.83, 0.51), (0.86, 0.50), (0.88, 0.49), (0.90, 0.48),
    (0.93, 0.47), (0.96, 0.46), (0.98, 0.45), (1.00, 0.44), (1.04, 0.43),
    (1.08, 0.42), (1.12, 0.41), (1.16, 0.40), (1.20, 0.39), (1.24, 0.38),
    (1.28, 0.37), (1.34, 0.36), (1.40, 0.35), (1.46, 0.34), (1.52, 0.33),
    (1.58, 0.32), (1.64, 0.31), (1.71, 0.30), (1.80, 0.29), (1.89, 0.28),
]

# Tabla estándar beta = f(periodo de retorno Tr en años).
_TABLA_BETA_TR = [
    (5, 0.82), (10, 0.86), (20, 0.90), (50, 0.94), (100, 1.00),
    (200, 1.02), (500, 1.05), (1000, 1.07),
]


def _interp_tabla(tabla: List[Tuple[float, float]], x: float) -> float:
    if x <= tabla[0][0]:
        return tabla[0][1]
    if x >= tabla[-1][0]:
        return tabla[-1][1]
    for i in range(len(tabla) - 1):
        x0, y0 = tabla[i]
        x1, y1 = tabla[i + 1]
        if x0 <= x <= x1:
            if x1 == x0:
                return y0
            return y0 + (x - x0) * (y1 - y0) / (x1 - x0)
    return tabla[-1][1]


def exponente_x_no_cohesivo(dm_mm: float) -> float:
    return _interp_tabla(_TABLA_X_NO_COHESIVO, dm_mm)


def exponente_x_cohesivo(gamma_d_tm3: float) -> float:
    return _interp_tabla(_TABLA_X_COHESIVO, gamma_d_tm3)


def coeficiente_beta(tr_años: float) -> float:
    return _interp_tabla(_TABLA_BETA_TR, tr_años)


def coeficiente_alpha(q_diseno_m3s: float, hm_m: float, be_m: float, mu: float = 1.0) -> float:
    """alpha = Q/(Hm^(5/3)*Be*mu): coeficiente de sección de
    Lischtvan-Lebediev. Hm = tirante medio de la sección (Área/Be), Be =
    ancho efectivo (superficial), mu = coeficiente de contracción
    (1.0 = sin contracción; <1.0 con estribos/pilares que angostan el
    cauce, tabulado según luz libre entre apoyos y velocidad de acceso)."""
    if hm_m <= 0 or be_m <= 0:
        raise SocavacionError("Hm y Be deben ser mayores que cero para calcular alpha.")
    return q_diseno_m3s / (hm_m ** (5.0 / 3.0) * be_m * mu)


def tirante_socavado_no_cohesivo(alpha: float, beta: float, hi_m: float, dm_mm: float) -> float:
    """He (m), tirante de agua erosionado bajo el nivel de la superficie
    libre, para una vertical de tirante real Hi, material no cohesivo."""
    if hi_m <= 0:
        return 0.0
    x = exponente_x_no_cohesivo(dm_mm)
    base = (alpha * beta * hi_m ** (5.0 / 3.0)) / (0.68 * dm_mm ** 0.28)
    return base ** (1.0 / (x + 1.0))


def tirante_socavado_cohesivo(alpha: float, beta: float, hi_m: float, gamma_d_tm3: float) -> float:
    """He (m) para material cohesivo, en función del peso específico seco
    del suelo gamma_d (t/m3)."""
    if hi_m <= 0:
        return 0.0
    x = exponente_x_cohesivo(gamma_d_tm3)
    base = (alpha * beta * hi_m ** (5.0 / 3.0)) / (0.60 * gamma_d_tm3 ** 1.18)
    return base ** (1.0 / (x + 1.0))


def perfil_socavado_lischtvan_lebediev(estaciones: Sequence[float], elevaciones: Sequence[float],
                                        nivel_agua: float, q_diseno_m3s: float, be_m: float,
                                        mu: float, tr_años: float, cohesivo: bool,
                                        dm_mm: Optional[float] = None,
                                        gamma_d_tm3: Optional[float] = None) -> Dict:
    """Aplica Lischtvan-Lebediev vertical por vertical a toda la sección
    (estaciones/elevaciones del levantamiento, GIS o manual) y devuelve el
    perfil de fondo SOCAVADO junto con la profundidad de socavación máxima
    y su ubicación. Solo se socava donde la vertical está bajo el agua
    (elevación < nivel_agua)."""
    estaciones = list(estaciones)
    elevaciones = list(elevaciones)
    if len(estaciones) != len(elevaciones) or len(estaciones) < 2:
        raise SocavacionError("Estaciones y elevaciones deben tener la misma longitud (>=2).")
    if cohesivo and not gamma_d_tm3:
        raise SocavacionError("Falta el peso específico seco (gamma_d) para suelo cohesivo.")
    if not cohesivo and not dm_mm:
        raise SocavacionError("Falta el diámetro medio Dm (mm) para suelo no cohesivo.")

    tirantes = [max(nivel_agua - z, 0.0) for z in elevaciones]
    hm = sum(tirantes) / len(tirantes)  # aproximación del tirante medio a partir del levantamiento
    if hm <= 0:
        raise SocavacionError("El nivel de agua ingresado no moja ninguna vertical de la sección.")
    alpha = coeficiente_alpha(q_diseno_m3s, hm, be_m, mu)
    beta = coeficiente_beta(tr_años)

    elevaciones_socavadas = []
    profundidades = []
    for z, hi in zip(elevaciones, tirantes):
        if hi <= 0:
            elevaciones_socavadas.append(z)
            profundidades.append(0.0)
            continue
        if cohesivo:
            he = tirante_socavado_cohesivo(alpha, beta, hi, gamma_d_tm3)
        else:
            he = tirante_socavado_no_cohesivo(alpha, beta, hi, dm_mm)
        he = max(he, hi)  # el método no predice "relleno", solo socavación
        ds = he - hi
        elevaciones_socavadas.append(nivel_agua - he)
        profundidades.append(ds)

    idx_max = max(range(len(profundidades)), key=lambda i: profundidades[i])
    return {
        "metodo": "Lischtvan-Lebediev (" + ("cohesivo" if cohesivo else "no cohesivo") + ")",
        "alpha": alpha, "beta": beta, "hm": hm,
        "elevaciones_originales": elevaciones, "elevaciones_socavadas": elevaciones_socavadas,
        "estaciones": estaciones, "profundidades": profundidades,
        "ds_max_m": profundidades[idx_max], "estacion_ds_max": estaciones[idx_max],
        "cota_socavada_max": elevaciones_socavadas[idx_max],
    }


# ============================================================================
# 3) MÉTODOS DE RÉGIMEN: LACEY, BLENCH, NEILL-KELLERHALS (socavación general,
#    valor único representativo -> se aplica como descenso uniforme del
#    fondo mojado para el gráfico comparativo)
# ============================================================================

def lacey_scour_depth(q_diseno_m3s: float, be_m: float, dm_mm: float,
                       factor_socavacion_disenio: float = 1.0) -> float:
    """Profundidad de socavación normal (dsm, m) bajo el nivel de aguas
    máximas, método de Lacey (régimen). f = 1.76*sqrt(Dm_mm) (factor de
    limo/sedimento de Lacey); q = caudal por unidad de ancho efectivo.
    factor_socavacion_disenio (>=1.0): factor de mayoración por curvatura
    del cauce / pilares / estribos (típico 1.25-2.0 según IRC:78), 1.0 =
    tramo recto sin obstrucción."""
    if be_m <= 0 or dm_mm <= 0:
        raise SocavacionError("Be y Dm deben ser mayores que cero (Lacey).")
    q_unit = q_diseno_m3s / be_m
    f = 1.76 * math.sqrt(dm_mm)
    dsm = 1.34 * (q_unit ** 2 / f) ** (1.0 / 3.0)
    return dsm * factor_socavacion_disenio


def blench_scour_depth(q_diseno_m3s: float, be_m: float, dm_mm: float,
                        factor_socavacion_disenio: float = 1.0) -> float:
    """Profundidad de socavación normal (dsm, m), método de Blench
    (régimen). Fb = 1.9*sqrt(Dm_mm) (factor de fondo de Blench)."""
    if be_m <= 0 or dm_mm <= 0:
        raise SocavacionError("Be y Dm deben ser mayores que cero (Blench).")
    q_unit = q_diseno_m3s / be_m
    fb = 1.9 * math.sqrt(dm_mm)
    dsm = 1.48 * (q_unit ** 2 / fb) ** (1.0 / 3.0)
    return dsm * factor_socavacion_disenio


def neill_kellerhals_scour_depth(q_diseno_m3s: float, be_m: float, d50_mm: float,
                                  tol: float = 1e-4, max_iter: int = 200) -> float:
    """Tirante de equilibrio (m) por velocidad competente de Neill (lechos
    de grava gruesa): Vc = 1.702*y^(1/6)*D50^(1/3) (SI, y y D50 en metros).
    Se resuelve por bisección el tirante y tal que Q/(Be*y) = Vc(y)."""
    if be_m <= 0 or d50_mm <= 0:
        raise SocavacionError("Be y D50 deben ser mayores que cero (Neill-Kellerhals).")
    d50_m = d50_mm / 1000.0

    def residual(y):
        if y <= 0:
            return 1e9
        v_continuidad = q_diseno_m3s / (be_m * y)
        v_competente = 1.702 * (y ** (1.0 / 6.0)) * (d50_m ** (1.0 / 3.0))
        return v_continuidad - v_competente

    y_lo, y_hi = 0.01, 50.0
    r_lo, r_hi = residual(y_lo), residual(y_hi)
    if r_lo * r_hi > 0:
        # amplía el rango antes de rendirse
        y_hi = 200.0
        r_hi = residual(y_hi)
        if r_lo * r_hi > 0:
            raise SocavacionError("Neill-Kellerhals: no se encontró un tirante de equilibrio en el rango 0.01-200 m.")
    for _ in range(max_iter):
        y_mid = 0.5 * (y_lo + y_hi)
        r_mid = residual(y_mid)
        if abs(r_mid) < tol:
            return y_mid
        if r_lo * r_mid <= 0:
            y_hi, r_hi = y_mid, r_mid
        else:
            y_lo, r_lo = y_mid, r_mid
    return 0.5 * (y_lo + y_hi)


def aplicar_descenso_uniforme(estaciones: Sequence[float], elevaciones: Sequence[float],
                               nivel_agua: float, tirante_equilibrio_m: float) -> Dict:
    """Convierte un tirante de equilibrio ÚNICO (Lacey/Blench/Neill-
    Kellerhals: valor representativo de toda la sección, no vertical por
    vertical) en un perfil de fondo socavado, descendiendo uniformemente
    cada vertical mojada en (tirante_equilibrio - Hi_original) cuando esa
    diferencia es positiva (nunca "rellena" donde el método da un tirante
    de equilibrio menor al tirante real, igual que Lischtvan-Lebediev)."""
    elevaciones_socavadas = []
    profundidades = []
    for z in elevaciones:
        hi = max(nivel_agua - z, 0.0)
        if hi <= 0:
            elevaciones_socavadas.append(z)
            profundidades.append(0.0)
            continue
        ds = max(tirante_equilibrio_m - hi, 0.0)
        elevaciones_socavadas.append(z - ds)
        profundidades.append(ds)
    idx_max = max(range(len(profundidades)), key=lambda i: profundidades[i]) if profundidades else 0
    return {
        "estaciones": list(estaciones), "elevaciones_originales": list(elevaciones),
        "elevaciones_socavadas": elevaciones_socavadas, "profundidades": profundidades,
        "ds_max_m": profundidades[idx_max] if profundidades else 0.0,
        "estacion_ds_max": estaciones[idx_max] if profundidades else None,
        "cota_socavada_max": elevaciones_socavadas[idx_max] if profundidades else None,
    }


# ============================================================================
# 4) SOCAVACIÓN LOCAL EN PILARES: CSU / HEC-RAS Y FROEHLICH
# ============================================================================

def numero_froude(v_m_s: float, y1_m: float) -> float:
    if y1_m <= 0:
        return 0.0
    return v_m_s / math.sqrt(G * y1_m)


def csu_pier_scour(y1_m: float, v_m_s: float, a_pila_m: float, k1_forma: float = 1.0,
                    k2_angulo: float = 1.0, k3_lecho: float = 1.1, k4_acorazamiento: float = 1.0) -> Dict:
    """Ecuación CSU (Colorado State University), estándar HEC-RAS/HEC-18:
        ys/y1 = 2.0*K1*K2*K3*K4*(a/y1)^0.65 * Fr1^0.43
    y1: tirante aguas arriba de la pila (m). v: velocidad aguas arriba
    (m/s). a: ancho de la pila (m). K1: forma de la nariz (1.0 redonda/
    cilíndrica, 1.1 cuadrada, 0.9 aguda). K2: ángulo de ataque, K2 =
    (cosθ + (L/a)·sinθ)^0.65 (calcular aparte y pasar aquí). K3: condición
    del lecho (1.1 lecho plano/aguas claras -- 1.3 dunas grandes). K4:
    corrección por acorazamiento (Molinas/Mueller; 1.0 si D50<2mm)."""
    if y1_m <= 0:
        raise SocavacionError("y1 (tirante aguas arriba de la pila) debe ser mayor que cero.")
    fr1 = numero_froude(v_m_s, y1_m)
    ys_sobre_y1 = 2.0 * k1_forma * k2_angulo * k3_lecho * k4_acorazamiento * (a_pila_m / y1_m) ** 0.65 * fr1 ** 0.43
    ys = ys_sobre_y1 * y1_m
    return {"metodo": "CSU / HEC-RAS (pilares)", "Fr1": fr1, "ys_m": ys, "ys_sobre_y1": ys_sobre_y1}


def k2_angulo_ataque(theta_grados: float, longitud_pila_m: float, ancho_pila_m: float) -> float:
    """K2 = (cosθ + (L/a)·sinθ)^0.65, factor de ángulo de ataque del flujo
    sobre la pila (CSU/HEC-18); θ=0 => K2=1 (flujo alineado con la pila)."""
    theta = math.radians(theta_grados)
    if ancho_pila_m <= 0:
        raise SocavacionError("El ancho de la pila debe ser mayor que cero.")
    base = math.cos(theta) + (longitud_pila_m / ancho_pila_m) * math.sin(theta)
    return max(base, 0.1) ** 0.65


def froehlich_pier_scour(y1_m: float, v_m_s: float, a_pila_m: float, d50_mm: float,
                          kf_forma: float = 1.0, theta_grados: float = 0.0,
                          longitud_pila_m: Optional[float] = None) -> Dict:
    """Ecuación de diseño de Froehlich (1991), reproducida en HEC-18:
        ys = 0.32*Kf*(a')^0.62 * y1^0.47 * Fr1^0.22 * D50^-0.09 + a
    a' = a*(cosθ + (L/a)·sinθ) = ancho proyectado efectivo de la pila
    ante un ángulo de ataque θ. Kf: 1.3 nariz cuadrada, 1.0 redonda/
    cilíndrica, 0.7 aguda. D50 en mm."""
    if y1_m <= 0 or a_pila_m <= 0 or d50_mm <= 0:
        raise SocavacionError("y1, ancho de pila y D50 deben ser mayores que cero (Froehlich).")
    l_pila = longitud_pila_m if longitud_pila_m else a_pila_m
    theta = math.radians(theta_grados)
    a_proyectada = a_pila_m * (math.cos(theta) + (l_pila / a_pila_m) * math.sin(theta))
    fr1 = numero_froude(v_m_s, y1_m)
    ys = 0.32 * kf_forma * (a_proyectada ** 0.62) * (y1_m ** 0.47) * (fr1 ** 0.22) * (d50_mm ** -0.09) + a_pila_m
    return {"metodo": "Froehlich (pilares)", "Fr1": fr1, "a_proyectada_m": a_proyectada, "ys_m": ys}


# ============================================================================
# 5) SOCAVACIÓN POR CONTRACCIÓN: LAURSEN
# ============================================================================

def clasificar_k1_laursen(v_estrella_sobre_w: float) -> float:
    """Exponente k1 de Laursen para socavación por contracción en lecho
    móvil, según la relación V*/w (velocidad de corte / velocidad de caída
    de la partícula): predomina el modo de transporte de fondo, mixto o
    en suspensión."""
    if v_estrella_sobre_w < 0.50:
        return 0.59  # mayormente carga de fondo
    elif v_estrella_sobre_w < 2.00:
        return 0.64  # modo mixto
    else:
        return 0.69  # mayormente en suspensión


def laursen_contraccion_lecho_movil(q1_m3s: float, q2_m3s: float, w1_m: float, w2_m: float,
                                     y1_m: float, k1_exponente: float) -> Dict:
    """Socavación por contracción en LECHO MÓVIL (hay transporte activo
    aguas arriba): y2/y1 = (Q2/Q1)^(6/7) * (W1/W2)^k1."""
    if q1_m3s <= 0 or w1_m <= 0 or w2_m <= 0 or y1_m <= 0:
        raise SocavacionError("Q1, W1, W2 e y1 deben ser mayores que cero (Laursen lecho móvil).")
    y2 = y1_m * (q2_m3s / q1_m3s) ** (6.0 / 7.0) * (w1_m / w2_m) ** k1_exponente
    ds = max(y2 - y1_m, 0.0)
    return {"metodo": "Laursen - contracción, lecho móvil", "y2_m": y2, "ds_m": ds}


def laursen_contraccion_agua_clara(q2_m3s: float, w2_m: float, dm_mm: float, y0_m: float) -> Dict:
    """Socavación por contracción en AGUA CLARA (sin aporte de sedimentos
    aguas arriba): y2 = [(Ku*Q2^2)/(Dm^(2/3)*W2^2)]^(3/7), Ku=0.0246 (SI,
    Dm en mm según HEC-18). y0: tirante existente en la sección contraída
    antes de la socavación, para obtener ds = y2 - y0."""
    if w2_m <= 0 or dm_mm <= 0:
        raise SocavacionError("W2 y Dm deben ser mayores que cero (Laursen agua clara).")
    ku = 0.0246
    y2 = ((ku * q2_m3s ** 2) / (dm_mm ** (2.0 / 3.0) * w2_m ** 2)) ** (3.0 / 7.0)
    ds = max(y2 - y0_m, 0.0)
    return {"metodo": "Laursen - contracción, agua clara", "y2_m": y2, "ds_m": ds}


def tension_tangencial_y_shields(radio_hidraulico_m: float, pendiente: float, d50_mm: float,
                                  peso_esp_agua_kn_m3: float = 9.81) -> Dict:
    """tau0 = gamma*R*S (Pa aprox. si gamma en kN/m3->kPa; se retorna en Pa)
    y una tau_critica de Shields simplificada (Shields adimensional ~0.06
    para régimen turbulento rugoso, tau_c = 0.06*(gamma_s-gamma_w)*d50) para
    decidir si el criterio de agua clara o lecho móvil aplica en Laursen."""
    tau0_pa = peso_esp_agua_kn_m3 * 1000.0 * radio_hidraulico_m * pendiente
    gamma_s_kn_m3 = 26.0  # peso específico típico de partículas minerales (2650 kg/m3)
    d50_m = d50_mm / 1000.0
    tau_c_pa = 0.06 * (gamma_s_kn_m3 - peso_esp_agua_kn_m3) * 1000.0 * d50_m
    return {"tau0_Pa": tau0_pa, "tau_critica_Pa": tau_c_pa, "lecho_movil": tau0_pa > tau_c_pa}


# ============================================================================
# 6) RESUMEN / COMPARACIÓN ENTRE MÉTODOS
# ============================================================================

def resumen_comparativo(resultados_por_metodo: Dict[str, float]) -> Dict:
    """Arma el cuadro comparativo final: método más conservador (mayor
    profundidad, criterio estándar de diseño en socavación -- se adopta el
    valor MÁXIMO entre métodos aplicables, nunca el promedio, salvo que el
    usuario decida lo contrario con criterio de experto), promedio y rango."""
    if not resultados_por_metodo:
        return {}
    metodo_max = max(resultados_por_metodo, key=lambda k: resultados_por_metodo[k])
    valores = list(resultados_por_metodo.values())
    return {
        "metodo_gobernante": metodo_max,
        "ds_diseño_recomendado_m": resultados_por_metodo[metodo_max],
        "promedio_m": sum(valores) / len(valores),
        "minimo_m": min(valores),
        "maximo_m": max(valores),
    }
