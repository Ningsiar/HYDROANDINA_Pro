# -*- coding: utf-8 -*-
"""
core/hydraulic_structures.py

Motor de cálculo para la Pestaña 7 (Hidráulica y Drenaje): dimensionamiento
y verificación de canales abiertos por MÁXIMA EFICIENCIA HIDRÁULICA
(sección de mínimo perímetro mojado para un área dada), y cálculos de
apoyo para el resto de estructuras de drenaje típicas de un expediente
vial/hidráulico de montaña (alcantarillas, enrocado, sumideros, cunetas
de coronación, y verificación hidráulica básica de pontones/puentes/
defensas ribereñas).

TRANSPARENCIA IMPORTANTE (léase antes de un diseño definitivo):

  - Canales (Rectangular, Triangular, Trapezoidal): las fórmulas de
    "sección de máxima eficiencia hidráulica" son las clásicas de Chow
    (1959), "Open-Channel Hydraulics", tabla 7-1 — de las más verificadas
    y reproducidas en toda la bibliografía de hidráulica de canales.
    Confianza alta.

  - Parabólico: se usa la aproximación estándar de perímetro mojado de
    Chow para parábolas someras (P ≈ T + 8y²/3T), válida cuando y/T no es
    grande. No se reclama una fórmula de "sección de máxima eficiencia"
    para la parábola con la misma certeza que para las tres anteriores
    (es un resultado menos estandarizado en la bibliografía); se ofrece
    también el modo general (a partir de un ancho superior T dado por el
    usuario) para no depender de ese supuesto.

  - Gutter / Cuneta vial: se implementa la ecuación de flujo en cuneta
    triangular de la FHWA HEC-22 (ecuación de Izzard modificada),
    ampliamente publicada y estandarizada para diseño vial.

  - Irregular: solución general de tirante normal (Manning + bisección)
    a partir de una sección transversal estación-elevación dada por el
    usuario (sin supuesto de "máxima eficiencia", que no aplica a una
    geometría fija impuesta por el terreno).

  - Alcantarilla: se calcula la capacidad en RÉGIMEN UNIFORME (control de
    sección/"outlet control" simplificado, vía Manning) para conductos
    circulares o rectangulares (cajón). NO incluye el análisis completo
    de control de entrada ("inlet control", curvas HY-8/FHWA) que en la
    práctica puede gobernar el diseño; se advierte explícitamente en el
    resultado para que el usuario verifique también esa condición.

  - Enrocado (RipRap): dimensionamiento por la ecuación de Isbash (1936),
    ampliamente citada en la bibliografía de protección de cauces, con
    coeficientes C=0.86 (roca parcialmente expuesta/embebida) y C=1.20
    (roca totalmente expuesta a la corriente) — verifique siempre contra
    el manual de diseño local (p.ej. HEC-11, Maynord, o el manual de
    carreteras vigente) antes de un diseño definitivo, ya que existen
    varios métodos de la bibliografía (HEC-11, Isbash, Maynord/USACE,
    California/Caltrans) que pueden dar tamaños distintos.

  - Sumideros (inlet de cuneta): se implementa una verificación
    SIMPLIFICADA de capacidad como vertedero de ventana (weir), Q = Cw *
    L * y^1.5. El diseño completo de sumideros según HEC-22 (transición
    weir/orificio, coeficientes por tipo de reja/ventana, eficiencia de
    intercepción) requiere más parámetros específicos del producto/reja
    y NO se implementa aquí en esa forma completa.

  - Pontón / Puente / Defensa ribereña: NO se implementa aquí un diseño
    estructural (no es competencia de este plugin, que es un motor
    hidrológico/hidráulico). Se ofrece únicamente una VERIFICACIÓN
    HIDRÁULICA básica: borde libre (revancha) entre el nivel de agua
    calculado (a partir del canal/cauce) y la cota de la estructura, y
    una alerta de socavación potencial por contracción simplificada para
    puentes. El diseño estructural, geotécnico y de cimentación requiere
    un análisis adicional fuera del alcance de este plugin.

  - Badén / Vado (ford): verificación hidráulica básica (tirante,
    velocidad, borde libre respecto a la calzada) para el paso de agua
    sobre la vía; no reemplaza el diseño estructural del pavimento/losa.
"""
import math
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

G = 9.81  # aceleración de la gravedad, m/s²


class HydraulicError(Exception):
    pass


# ---------------------------------------------------------------------
# Geometría de canales — Manning: Q = (1/n) * A * R^(2/3) * S^(1/2)
# ---------------------------------------------------------------------
@dataclass
class ResultadoCanal:
    forma: str
    y_m: float                 # tirante normal (m)
    area_m2: float
    perimetro_m: float
    radio_hidraulico_m: float
    ancho_superior_m: float
    velocidad_m_s: float
    caudal_m3_s: float
    numero_froude: float
    tipo_flujo: str             # "Subcrítico" / "Crítico" / "Supercrítico"
    tirante_critico_m: float
    pendiente_critica: float
    energia_especifica_m: float
    geometria: Dict[str, float] = field(default_factory=dict)  # b, z, T, etc. según forma


def _numero_froude(v: float, y_hidraulico: float) -> float:
    """Fr = V / sqrt(g * D), con D = A/T (profundidad hidráulica)."""
    if y_hidraulico <= 0:
        return float("nan")
    return v / math.sqrt(G * y_hidraulico)


def _tipo_flujo(fr: float) -> str:
    if fr < 0.98:
        return "Subcrítico"
    elif fr > 1.02:
        return "Supercrítico"
    return "Crítico"


def _resolver_tirante_normal(func_area_perimetro_top: Callable[[float], Tuple[float, float, float]],
                              n: float, s: float, q: float,
                              y_min: float = 1e-4, y_max: float = 50.0,
                              tol: float = 1e-6, max_iter: int = 200) -> float:
    """
    Resuelve el tirante normal y tal que Manning(y) = q, por bisección,
    dada una función que devuelve (area, perimetro, ancho_superior) para
    un tirante y. Requiere que el caudal de Manning sea creciente con y
    (cierto para toda sección convexa simple creciente con la profundidad,
    como las de este módulo).
    """
    def q_manning(y):
        a, p, _ = func_area_perimetro_top(y)
        if a <= 0 or p <= 0:
            return 0.0
        r = a / p
        return (1.0 / n) * a * (r ** (2.0 / 3.0)) * math.sqrt(s)

    lo, hi = y_min, y_max
    q_hi = q_manning(hi)
    intentos = 0
    while q_hi < q and intentos < 60:
        hi *= 1.5
        q_hi = q_manning(hi)
        intentos += 1
    if q_hi < q:
        raise HydraulicError(
            "No se pudo acotar el tirante normal para el caudal indicado (Q muy grande o S/n "
            "fuera de rango razonable)."
        )
    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        if q_manning(mid) < q:
            lo = mid
        else:
            hi = mid
        if (hi - lo) < tol:
            break
    return (lo + hi) / 2.0


def _armar_resultado(forma: str, y: float, area: float, perimetro: float, top: float,
                      n: float, s: float, q: float, geometria: dict,
                      y_critico: float, s_critica: float) -> ResultadoCanal:
    if area <= 0 or perimetro <= 0:
        raise HydraulicError("Geometría inválida (área o perímetro no positivos) para el tirante calculado.")
    r = area / perimetro
    v = q / area
    profundidad_hidraulica = area / top if top > 0 else float("nan")
    fr = _numero_froude(v, profundidad_hidraulica)
    energia_especifica = y + (v ** 2) / (2 * G)
    return ResultadoCanal(
        forma=forma, y_m=round(y, 4), area_m2=round(area, 4), perimetro_m=round(perimetro, 4),
        radio_hidraulico_m=round(r, 4), ancho_superior_m=round(top, 4),
        velocidad_m_s=round(v, 4), caudal_m3_s=round(q, 4),
        numero_froude=round(fr, 4) if not math.isnan(fr) else float("nan"),
        tipo_flujo=_tipo_flujo(fr) if not math.isnan(fr) else "N/D",
        tirante_critico_m=round(y_critico, 4), pendiente_critica=round(s_critica, 6),
        energia_especifica_m=round(energia_especifica, 4), geometria=geometria,
    )


def _tirante_y_pendiente_critica_generico(func_area_top: Callable[[float], Tuple[float, float]],
                                           q: float, n: float,
                                           func_area_perim: Callable[[float], Tuple[float, float, float]],
                                           y_min=1e-4, y_max=50.0, tol=1e-6, max_iter=200) -> Tuple[float, float]:
    """
    Tirante crítico: condición Q²T/(g·A³) = 1. Se resuelve por bisección
    sobre y. Pendiente crítica: la pendiente de Manning que produce
    exactamente ese tirante como tirante normal (S = (Qn/(A R^(2/3)))²).
    """
    def condicion(y):
        a, t = func_area_top(y)
        if a <= 0 or t <= 0:
            return -1.0
        return (q ** 2) * t / (G * a ** 3) - 1.0

    lo, hi = y_min, y_max
    c_hi = condicion(hi)
    intentos = 0
    while c_hi > 0 and intentos < 60:
        hi *= 1.5
        c_hi = condicion(hi)
        intentos += 1
    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        if condicion(mid) > 0:
            lo = mid
        else:
            hi = mid
        if (hi - lo) < tol:
            break
    y_c = (lo + hi) / 2.0
    a_c, p_c, _ = func_area_perim(y_c)
    r_c = a_c / p_c if p_c > 0 else float("nan")
    s_c = ((q * n) / (a_c * (r_c ** (2.0 / 3.0)))) ** 2 if a_c > 0 and r_c > 0 else float("nan")
    return y_c, s_c


# ---------------- Rectangular (máxima eficiencia: b = 2y) ----------------
def canal_rectangular_maxima_eficiencia(n: float, s: float, q: Optional[float] = None,
                                         y: Optional[float] = None) -> ResultadoCanal:
    """Sección de máxima eficiencia hidráulica: b = 2y (semicuadrado).
    A=2y², P=4y, T=2y (Chow, 1959, Tabla 7-1)."""
    def area_perim_top(yy):
        return 2 * yy ** 2, 4 * yy, 2 * yy

    def area_top(yy):
        return 2 * yy ** 2, 2 * yy

    if q is not None:
        y_res = _resolver_tirante_normal(area_perim_top, n, s, q)
    elif y is not None:
        y_res = y
        area, perim, _ = area_perim_top(y_res)
        r = area / perim
        q = (1.0 / n) * area * (r ** (2.0 / 3.0)) * math.sqrt(s)
    else:
        raise HydraulicError("Debe indicar Q o el tirante y.")

    area, perim, top = area_perim_top(y_res)
    y_c, s_c = _tirante_y_pendiente_critica_generico(area_top, q, n, area_perim_top)
    b = 2 * y_res
    return _armar_resultado("Rectangular (máx. eficiencia)", y_res, area, perim, top, n, s, q,
                             {"b_m": round(b, 4)}, y_c, s_c)


# ---------------- Triangular (máxima eficiencia: z=1, 45°) ----------------
def canal_triangular_maxima_eficiencia(n: float, s: float, q: Optional[float] = None,
                                        y: Optional[float] = None) -> ResultadoCanal:
    """Sección de máxima eficiencia: mitad de un cuadrado, taludes z=1
    (45° respecto a la vertical) en ambos lados. A=y², P=2√2·y, T=2y
    (Chow, 1959, Tabla 7-1)."""
    z = 1.0

    def area_perim_top(yy):
        return z * yy ** 2, 2 * yy * math.sqrt(1 + z ** 2), 2 * z * yy

    def area_top(yy):
        return z * yy ** 2, 2 * z * yy

    if q is not None:
        y_res = _resolver_tirante_normal(area_perim_top, n, s, q)
    elif y is not None:
        y_res = y
        area, perim, _ = area_perim_top(y_res)
        r = area / perim
        q = (1.0 / n) * area * (r ** (2.0 / 3.0)) * math.sqrt(s)
    else:
        raise HydraulicError("Debe indicar Q o el tirante y.")

    area, perim, top = area_perim_top(y_res)
    y_c, s_c = _tirante_y_pendiente_critica_generico(area_top, q, n, area_perim_top)
    return _armar_resultado("Triangular (máx. eficiencia, z=1)", y_res, area, perim, top, n, s, q,
                             {"z": z}, y_c, s_c)


# ---------------- Trapezoidal (máxima eficiencia: semihexágono) ----------------
def canal_trapezoidal_maxima_eficiencia(n: float, s: float, q: Optional[float] = None,
                                         y: Optional[float] = None) -> ResultadoCanal:
    """Sección de máxima eficiencia: mitad de un hexágono regular,
    z = 1/√3 (talud a 60° de la horizontal), b = (2/√3)y. A=√3·y²,
    P=2√3·y, T=(4/√3)y (Chow, 1959, Tabla 7-1)."""
    z = 1.0 / math.sqrt(3.0)
    b_sobre_y = 2 * (math.sqrt(1 + z ** 2) - z)  # = 2/√3

    def area_perim_top(yy):
        b = b_sobre_y * yy
        area = (b + z * yy) * yy
        perim = b + 2 * yy * math.sqrt(1 + z ** 2)
        top = b + 2 * z * yy
        return area, perim, top

    def area_top(yy):
        a, _, t = area_perim_top(yy)
        return a, t

    if q is not None:
        y_res = _resolver_tirante_normal(area_perim_top, n, s, q)
    elif y is not None:
        y_res = y
        area, perim, _ = area_perim_top(y_res)
        r = area / perim
        q = (1.0 / n) * area * (r ** (2.0 / 3.0)) * math.sqrt(s)
    else:
        raise HydraulicError("Debe indicar Q o el tirante y.")

    area, perim, top = area_perim_top(y_res)
    y_c, s_c = _tirante_y_pendiente_critica_generico(area_top, q, n, area_perim_top)
    b = b_sobre_y * y_res
    return _armar_resultado("Trapezoidal (máx. eficiencia, semihexágono)", y_res, area, perim, top, n, s, q,
                             {"b_m": round(b, 4), "z": round(z, 4)}, y_c, s_c)


# ---------------- Trapezoidal general (b y z dados por el usuario) ----------------
def canal_trapezoidal_general(n: float, s: float, b: float, z: float,
                               q: Optional[float] = None, y: Optional[float] = None) -> ResultadoCanal:
    def area_perim_top(yy):
        area = (b + z * yy) * yy
        perim = b + 2 * yy * math.sqrt(1 + z ** 2)
        top = b + 2 * z * yy
        return area, perim, top

    def area_top(yy):
        a, _, t = area_perim_top(yy)
        return a, t

    if q is not None:
        y_res = _resolver_tirante_normal(area_perim_top, n, s, q)
    elif y is not None:
        y_res = y
        area, perim, _ = area_perim_top(y_res)
        r = area / perim
        q = (1.0 / n) * area * (r ** (2.0 / 3.0)) * math.sqrt(s)
    else:
        raise HydraulicError("Debe indicar Q o el tirante y.")

    area, perim, top = area_perim_top(y_res)
    y_c, s_c = _tirante_y_pendiente_critica_generico(area_top, q, n, area_perim_top)
    return _armar_resultado("Trapezoidal (geometría dada)", y_res, area, perim, top, n, s, q,
                             {"b_m": b, "z": z}, y_c, s_c)


# ---------------- Parabólico (aproximación de Chow, ver docstring) ----------------
def canal_parabolico(n: float, s: float, t_ancho_superior_m: float,
                      q: Optional[float] = None, y: Optional[float] = None) -> ResultadoCanal:
    """T fijo (ancho superior de diseño); A=(2/3)Ty, P≈T+8y²/(3T)
    (aproximación estándar de Chow para parábolas someras)."""
    t = t_ancho_superior_m

    def area_perim_top(yy):
        area = (2.0 / 3.0) * t * yy
        perim = t + (8.0 / 3.0) * (yy ** 2) / t
        return area, perim, t

    def area_top(yy):
        return (2.0 / 3.0) * t * yy, t

    if q is not None:
        y_res = _resolver_tirante_normal(area_perim_top, n, s, q)
    elif y is not None:
        y_res = y
        area, perim, _ = area_perim_top(y_res)
        r = area / perim
        q = (1.0 / n) * area * (r ** (2.0 / 3.0)) * math.sqrt(s)
    else:
        raise HydraulicError("Debe indicar Q o el tirante y.")

    if y_res >= t / 2.0:
        raise HydraulicError(
            f"El tirante calculado ({y_res:.3f} m) excede el rango válido de la aproximación "
            f"parabólica para T={t} m; aumente el ancho superior T o reduzca Q."
        )

    area, perim, top = area_perim_top(y_res)
    y_c, s_c = _tirante_y_pendiente_critica_generico(area_top, q, n, area_perim_top)
    return _armar_resultado("Parabólico (aprox. Chow)", y_res, area, perim, top, n, s, q,
                             {"T_m": t}, y_c, s_c)


# ---------------- Irregular (sección estación-elevación dada) ----------------
def canal_irregular(n: float, s: float, puntos_estacion_elevacion: List[Tuple[float, float]],
                     q: Optional[float] = None, y: Optional[float] = None) -> ResultadoCanal:
    """
    puntos_estacion_elevacion: lista de (estación_m, cota_m) ordenados de
    izquierda a derecha, describiendo el fondo del cauce/canal (sección
    transversal), con la cota mínima como referencia de fondo.
    Se calcula A(y), P(y), T(y) recortando el polígono de la sección al
    nivel de agua y (algoritmo estándar de intersección de polilínea con
    una recta horizontal).
    """
    puntos = sorted(puntos_estacion_elevacion, key=lambda p: p[0])
    z_fondo = min(z for _, z in puntos)

    def geometria(yy):
        nivel_agua = z_fondo + yy
        area = 0.0
        perim = 0.0
        estaciones_interseccion = []
        for i in range(len(puntos) - 1):
            x1, z1 = puntos[i]
            x2, z2 = puntos[i + 1]
            d1_bajo = z1 < nivel_agua
            d2_bajo = z2 < nivel_agua
            if d1_bajo and d2_bajo:
                area += (nivel_agua - z1 + nivel_agua - z2) / 2.0 * (x2 - x1)
                perim += math.hypot(x2 - x1, z2 - z1)
                if i == 0:
                    estaciones_interseccion.append(x1)
                estaciones_interseccion.append(x2)
            elif d1_bajo != d2_bajo:
                # Intersección del segmento con el nivel de agua
                t_interp = (nivel_agua - z1) / (z2 - z1)
                x_int = x1 + t_interp * (x2 - x1)
                if d1_bajo:
                    area += (nivel_agua - z1) / 2.0 * (x_int - x1)
                    perim += math.hypot(x_int - x1, nivel_agua - z1)
                else:
                    area += (nivel_agua - z2) / 2.0 * (x2 - x_int)
                    perim += math.hypot(x2 - x_int, nivel_agua - z2)
                estaciones_interseccion.append(x_int)
        if not estaciones_interseccion:
            return 0.0, 0.0, 0.0
        top = max(estaciones_interseccion) - min(estaciones_interseccion)
        return area, perim, top

    def area_perim_top(yy):
        return geometria(yy)

    def area_top(yy):
        a, _, t = geometria(yy)
        return a, t

    y_max_valido = max(z for _, z in puntos) - z_fondo
    if q is not None:
        y_res = _resolver_tirante_normal(area_perim_top, n, s, q, y_max=y_max_valido * 0.999)
    elif y is not None:
        y_res = y
        area, perim, _ = area_perim_top(y_res)
        r = area / perim
        q = (1.0 / n) * area * (r ** (2.0 / 3.0)) * math.sqrt(s)
    else:
        raise HydraulicError("Debe indicar Q o el tirante y.")

    area, perim, top = area_perim_top(y_res)
    y_c, s_c = _tirante_y_pendiente_critica_generico(area_top, q, n, area_perim_top, y_max=y_max_valido * 0.999)
    return _armar_resultado("Irregular (sección dada)", y_res, area, perim, top, n, s, q,
                             {"z_fondo_m": z_fondo}, y_c, s_c)


# ---------------- Gutter / Cuneta vial (FHWA HEC-22) ----------------
def cuneta_vial_hec22(n: float, s_longitudinal: float, sx_transversal: float,
                       t_spread_m: Optional[float] = None, q: Optional[float] = None) -> dict:
    """
    Flujo en cuneta triangular de vía, ecuación de Izzard modificada
    (FHWA HEC-22, unidades SI): Q = (Kc/n)*Sx^(5/3)*S^(1/2)*T^(8/3),
    con Kc=0.376.

    Se puede resolver en cualquiera de los dos sentidos: dado el ancho de
    inundación admisible T (spread), calcula Q; o dado Q, calcula el
    spread T resultante.
    """
    kc = 0.376
    if t_spread_m is not None:
        t = t_spread_m
        q_calc = (kc / n) * (sx_transversal ** (5.0 / 3.0)) * math.sqrt(s_longitudinal) * (t ** (8.0 / 3.0))
        q_out = q_calc
    elif q is not None:
        # T = (Q*n / (Kc * Sx^(5/3) * sqrt(S)))^(3/8)
        t = (q * n / (kc * (sx_transversal ** (5.0 / 3.0)) * math.sqrt(s_longitudinal))) ** (3.0 / 8.0)
        q_out = q
    else:
        raise HydraulicError("Debe indicar el caudal Q o el ancho de inundación admisible T.")

    y_borde_calzada = t * sx_transversal  # tirante en el borde (contra la berma/sardinel)
    area = 0.5 * t * y_borde_calzada
    velocidad = q_out / area if area > 0 else float("nan")
    return {
        "spread_T_m": round(t, 3), "caudal_m3_s": round(q_out, 4),
        "tirante_borde_m": round(y_borde_calzada, 4), "area_m2": round(area, 4),
        "velocidad_m_s": round(velocidad, 3) if not math.isnan(velocidad) else None,
    }


# ---------------------------------------------------------------------
# Alcantarilla (capacidad en régimen uniforme, Manning)
# ---------------------------------------------------------------------
def alcantarilla_circular_capacidad(n: float, s: float, diametro_m: float, y: float) -> dict:
    """Conducto circular parcialmente lleno. Geometría estándar: para un
    tirante y y diámetro D, con theta = 2*arccos(1 - 2y/D):
    A = (D²/8)(theta - sin(theta)), P = (D/2)*theta."""
    d = diametro_m
    if y <= 0 or y >= d:
        raise HydraulicError("El tirante debe estar entre 0 y el diámetro (conducto parcialmente lleno).")
    theta = 2 * math.acos(1 - 2 * y / d)
    area = (d ** 2 / 8.0) * (theta - math.sin(theta))
    perim = (d / 2.0) * theta
    r = area / perim
    q = (1.0 / n) * area * (r ** (2.0 / 3.0)) * math.sqrt(s)
    v = q / area
    d_lleno = (d ** 2) * math.pi / 4.0
    return {
        "tirante_m": round(y, 4), "area_m2": round(area, 4), "perimetro_m": round(perim, 4),
        "radio_hidraulico_m": round(r, 4), "caudal_m3_s": round(q, 4), "velocidad_m_s": round(v, 4),
        "porcentaje_lleno_area": round(100 * area / d_lleno, 1),
        "advertencia": ("Capacidad calculada en régimen uniforme (control de sección/sección llena). "
                         "NO reemplaza la verificación de control de entrada (inlet control, curvas "
                         "HY-8/FHWA), que en alcantarillas cortas y pendientes fuertes puede gobernar "
                         "el diseño real; verifíquela por separado."),
    }


def alcantarilla_cajon_capacidad(n: float, s: float, ancho_m: float, alto_maximo_m: float, y: float) -> dict:
    if y <= 0 or y > alto_maximo_m:
        raise HydraulicError("El tirante debe ser mayor que 0 y no exceder la altura máxima del cajón.")
    area = ancho_m * y
    perim = ancho_m + 2 * y
    r = area / perim
    q = (1.0 / n) * area * (r ** (2.0 / 3.0)) * math.sqrt(s)
    v = q / area
    return {
        "tirante_m": round(y, 4), "area_m2": round(area, 4), "perimetro_m": round(perim, 4),
        "radio_hidraulico_m": round(r, 4), "caudal_m3_s": round(q, 4), "velocidad_m_s": round(v, 4),
        "porcentaje_lleno_altura": round(100 * y / alto_maximo_m, 1),
        "advertencia": ("Capacidad calculada en régimen uniforme (control de sección). NO reemplaza "
                         "la verificación de control de entrada; verifíquela por separado."),
    }


# ---------------------------------------------------------------------
# Enrocado / RipRap — ecuación de Isbash (1936)
# ---------------------------------------------------------------------
def enrocado_isbash(velocidad_m_s: float, peso_especifico_roca_kn_m3: float = 26.0,
                     roca_expuesta: bool = True) -> dict:
    """
    D50 = V² / (2·g·(Ss-1)·C²), con Ss = peso_especifico_roca/peso_especifico_agua,
    C=1.20 (roca totalmente expuesta a la corriente) o C=0.86 (roca
    parcialmente protegida/embebida en el talud) — Isbash (1936).
    """
    peso_esp_agua = 9.81  # kN/m3
    ss = peso_especifico_roca_kn_m3 / peso_esp_agua
    if ss <= 1.0:
        raise HydraulicError("El peso específico de la roca debe ser mayor que el del agua.")
    c = 1.20 if roca_expuesta else 0.86
    d50 = (velocidad_m_s ** 2) / (2 * G * (ss - 1) * (c ** 2))
    return {
        "D50_m": round(d50, 3), "D50_cm": round(d50 * 100, 1),
        "gravedad_especifica_roca": round(ss, 3), "coeficiente_isbash": c,
        "nota": ("Ecuación de Isbash (1936); verifique contra el método de diseño vigente en su "
                 "localidad (p.ej. HEC-11, Maynord/USACE, o el manual de carreteras aplicable), ya "
                 "que distintos métodos de la bibliografía pueden dar tamaños de roca distintos "
                 "para las mismas condiciones."),
    }


# ---------------------------------------------------------------------
# Sumidero — capacidad simplificada como vertedero de ventana (weir)
# ---------------------------------------------------------------------
def sumidero_capacidad_vertedero(longitud_m: float, tirante_m: float, cw: float = 1.66) -> dict:
    """Q = Cw * L * y^1.5 (vertedero de pared delgada, aproximación para
    una ventana/reja de sumidero operando en régimen de vertedero, válida
    para tirantes pequeños respecto a la altura de la ventana)."""
    q = cw * longitud_m * (tirante_m ** 1.5)
    return {
        "caudal_interceptado_m3_s": round(q, 4),
        "advertencia": ("Fórmula simplificada de vertedero (weir); el diseño completo de sumideros "
                         "según HEC-22 requiere además verificar el régimen de orificio a tirantes "
                         "mayores y coeficientes propios del tipo de reja/ventana utilizada."),
    }


# ---------------------------------------------------------------------
# Verificación hidráulica básica: borde libre (pontón, puente, badén,
# defensa ribereña) — NO es diseño estructural.
# ---------------------------------------------------------------------
def verificar_borde_libre(cota_agua_diseno_m: float, cota_inferior_estructura_m: float,
                           borde_libre_minimo_m: float = 1.0) -> dict:
    borde_libre_disponible = cota_inferior_estructura_m - cota_agua_diseno_m
    cumple = borde_libre_disponible >= borde_libre_minimo_m
    return {
        "borde_libre_disponible_m": round(borde_libre_disponible, 3),
        "borde_libre_minimo_requerido_m": borde_libre_minimo_m,
        "cumple": cumple,
        "mensaje": ("Cumple el borde libre mínimo." if cumple else
                    "NO cumple el borde libre mínimo indicado; revise la cota de la estructura o "
                    "el caudal/nivel de diseño."),
        "nota": ("Esta es una verificación hidráulica básica (borde libre), no un diseño "
                 "estructural. El dimensionamiento estructural, geotécnico y de cimentación de "
                 "pontones, puentes, badenes y defensas ribereñas requiere un análisis adicional "
                 "fuera del alcance de este plugin."),
    }
