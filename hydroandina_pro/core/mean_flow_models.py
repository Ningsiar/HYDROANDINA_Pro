# -*- coding: utf-8 -*-
"""
core/mean_flow_models.py

Motor de modelos conceptuales de generación de caudales (precipitación-
escorrentía), métricas de bondad de ajuste y un calibrador genérico
(simplex de Nelder-Mead, sin dependencias externas) que funciona con
cualquiera de los modelos implementados.

MODELOS IMPLEMENTADOS EN ESTA VERSIÓN:
  - Lutz Scholz (versión simplificada): balance hídrico mensual por
    almacenamientos (escorrentía directa, retención de suelo, acuífero),
    en el espíritu del método Lutz Scholz/GTZ-PLAN MERISS muy usado en
    cuencas altoandinas peruanas.
  - GR2M (Mouelhi et al., 2006; CemaGREF): modelo mensual de 2
    parámetros, con almacenamiento de producción (capacidad X1) y
    almacenamiento de ruteo (capacidad fija 60 mm, coeficiente de
    intercambio X2).
  - GR4J (Perrin, Michel y Andréassian, 2003): modelo de 4 parámetros
    con almacenamiento de producción, dos hidrogramas unitarios (90%/
    10% del excedente) y almacenamiento de ruteo con intercambio
    subterráneo no lineal.
  - HBV (versión mensual simplificada): rutina de nieve grado-día,
    humedad de suelo (parámetro de forma BETA) y dos reservorios
    lineales (rápido/lento).
  - SAC-SMA (versión simplificada del modelo Sacramento del NWS):
    zona superior (tensión + agua libre) y zona inferior (tensión +
    agua libre primaria/secundaria), con percolación y agotamiento
    exponencial de cada almacenamiento.
  - SNOW-SD: grado-día con curva de agotamiento areal de la cobertura
    de nieve (Snow Depletion Curve).

TRANSPARENCIA: SOCONT, GSM y SWMM (mencionados en el enunciado) NO se
implementan como motores numéricos en esta versión: SWMM es un
software completo de simulación hidrológica-hidráulica (EPA SWMM) que
requiere su propio motor de cálculo (p.ej. vía pyswmm) y no puede
reproducirse de forma fiable dentro de un plugin; SOCONT tiene una
formulación específica del software Routing System/RS Minerve (EPFL)
que requiere la documentación oficial para reproducirse con exactitud;
"GSM" no tiene una definición única y consistente en la bibliografía
revisada. Impleméntelos como una futura extensión si cuenta con la
documentación de referencia de cada uno.

Los modelos aquí presentes SÍ son estructuras estándar ampliamente
publicadas (GR2M/GR4J: Perrin et al.; HBV: Bergström; SAC-SMA: NWS;
Lutz Scholz: metodología PLAN MERISS/GTZ). Aun así, calibre siempre
contra sus propios aforos antes de un uso definitivo -- por eso este
módulo incluye el calibrador genérico.
"""
import math
from typing import Callable, Dict, List, Optional, Sequence, Tuple

G = 9.81


class MeanFlowError(Exception):
    pass


# ============================================================================
# 0) UTILIDADES DE UNIDADES
# ============================================================================

def mm_a_caudal_m3s(lamina_mm: float, area_km2: float, duracion_dias: float) -> float:
    """Convierte una lámina de escorrentía (mm) en un caudal medio (m³/s)
    para una cuenca de área area_km2 y un paso de tiempo de duracion_dias."""
    volumen_m3 = lamina_mm / 1000.0 * area_km2 * 1.0e6
    segundos = duracion_dias * 86400.0
    return volumen_m3 / segundos if segundos > 0 else 0.0


def serie_mm_a_m3s(serie_mm: Sequence[float], area_km2: float, duracion_dias: float) -> List[float]:
    return [mm_a_caudal_m3s(x, area_km2, duracion_dias) for x in serie_mm]


# ============================================================================
# 1) LUTZ SCHOLZ (VERSIÓN SIMPLIFICADA)
# ============================================================================

DEF_LUTZ_SCHOLZ = [
    ("C - coeficiente de escorrentía directa", 0.30, 0.05, 0.90),
    ("R_max - capacidad de retención del suelo (mm)", 50.0, 10.0, 200.0),
    ("b - coeficiente de agotamiento de la retención", 0.30, 0.05, 0.90),
    ("a - coeficiente de agotamiento subterráneo", 0.15, 0.02, 0.60),
]


def simular_lutz_scholz(parametros: Sequence[float], p_mm: Sequence[float], etp_mm: Sequence[float]) -> List[float]:
    c, r_max, b, a = parametros
    retencion, subterraneo = 0.0, 0.0
    q_sim = []
    for p, etp in zip(p_mm, etp_mm):
        etr = min(etp, p)
        excedente = max(p - etr, 0.0)
        ro = c * excedente
        infiltracion = excedente - ro
        espacio = max(r_max - retencion, 0.0)
        recarga_retencion = min(infiltracion, espacio)
        retencion += recarga_retencion
        recarga_subterranea = infiltracion - recarga_retencion
        gr = retencion * (1 - b)
        retencion -= gr
        subterraneo += recarga_subterranea
        qs = subterraneo * a
        subterraneo -= qs
        q_sim.append(ro + gr + qs)
    return q_sim


# ============================================================================
# 2) GR2M
# ============================================================================

DEF_GR2M = [
    ("X1 - capacidad del almacenamiento de producción (mm)", 300.0, 10.0, 3000.0),
    ("X2 - coeficiente de intercambio subterráneo", 1.00, 0.20, 2.00),
]


def simular_gr2m(parametros: Sequence[float], p_mm: Sequence[float], etp_mm: Sequence[float]) -> List[float]:
    x1, x2 = parametros
    s, r = x1 * 0.3, 30.0  # estados iniciales típicos (fracción de capacidad)
    q_sim = []
    for p, e in zip(p_mm, etp_mm):
        phi = math.tanh(p / x1)
        s1 = (s + x1 * phi) / (1 + phi * (s / x1))
        psi = math.tanh(e / x1)
        s2 = s1 * (1 - psi) / (1 + psi * (1 - s1 / x1))
        s2 = max(s2, 0.0)
        s_next = s2 / (1 + (s2 / x1) ** 3) ** (1.0 / 3.0)
        p2 = s2 - s_next  # percolación del almacenamiento de producción
        p1 = p + s - s1  # excedente directo del paso de producción
        s = s_next
        p3 = max(p1, 0.0) + p2
        r1 = r + p3
        r2 = x2 * r1
        r_next = r2 / math.sqrt(1 + (r2 / 60.0) ** 2)
        q = r2 - r_next
        r = r_next
        q_sim.append(max(q, 0.0))
    return q_sim


# ============================================================================
# 3) GR4J
# ============================================================================

DEF_GR4J = [
    ("X1 - capacidad de producción (mm)", 350.0, 10.0, 3000.0),
    ("X2 - coeficiente de intercambio subterráneo (mm/paso)", 0.0, -10.0, 10.0),
    ("X3 - capacidad del almacenamiento de ruteo (mm)", 90.0, 10.0, 1000.0),
    ("X4 - tiempo base del hidrograma unitario (pasos)", 2.0, 0.5, 10.0),
]


def _sh1(t, x4):
    if t <= 0:
        return 0.0
    if t < x4:
        return (t / x4) ** 2.5
    return 1.0


def _sh2(t, x4):
    if t <= 0:
        return 0.0
    if t <= x4:
        return 0.5 * (t / x4) ** 2.5
    if t < 2 * x4:
        return 1.0 - 0.5 * (2 - t / x4) ** 2.5
    return 1.0


def _ordenadas_uh(x4, sh_func, n_max=None):
    n = n_max or (int(math.ceil(2 * x4)) + 2)
    ordenadas = []
    sh_prev = 0.0
    for t in range(1, n + 1):
        sh_t = sh_func(t, x4)
        ordenadas.append(sh_t - sh_prev)
        sh_prev = sh_t
    return ordenadas


def simular_gr4j(parametros: Sequence[float], p_mm: Sequence[float], etp_mm: Sequence[float]) -> List[float]:
    x1, x2, x3, x4 = parametros
    if x4 <= 0:
        raise MeanFlowError("X4 debe ser mayor que cero (GR4J).")
    s = x1 * 0.3
    r = x3 * 0.3
    uh1 = _ordenadas_uh(x4, _sh1)
    uh2 = _ordenadas_uh(2 * x4, _sh2, n_max=int(math.ceil(2 * x4)) + 2)
    n1, n2 = len(uh1), len(uh2)
    reserva_uh1 = [0.0] * n1
    reserva_uh2 = [0.0] * n2
    q_sim = []
    for p, e in zip(p_mm, etp_mm):
        if p >= e:
            pn, en = p - e, 0.0
            phi = math.tanh(pn / x1)
            ps = x1 * (1 - (s / x1) ** 2) * phi / (1 + (s / x1) * phi)
            s += ps
            es = 0.0
        else:
            pn, en = 0.0, e - p
            psi = math.tanh(en / x1)
            es = s * (2 - s / x1) * psi / (1 + (1 - s / x1) * psi)
            s = max(s - es, 0.0)
            ps = 0.0
        perc = s * (1 - (1 + (4 * s / (9 * x1)) ** 4) ** (-0.25))
        s -= perc
        pr = perc + (pn - ps)

        # convolución con los hidrogramas unitarios (90% UH1, 10% UH2), cola FIFO:
        # offset 0 = aporte en el mismo paso, se suma primero y luego se consume/desplaza
        for i in range(n1):
            reserva_uh1[i] += 0.9 * pr * uh1[i]
        aporte_uh1 = reserva_uh1.pop(0)
        reserva_uh1.append(0.0)

        for i in range(n2):
            reserva_uh2[i] += 0.1 * pr * uh2[i]
        aporte_uh2 = reserva_uh2.pop(0)
        reserva_uh2.append(0.0)

        f = x2 * (r / x3) ** 3.5
        r = max(r + aporte_uh1 + f, 0.0)
        qr = r * (1 - (1 + (r / x3) ** 4) ** (-0.25))
        r -= qr
        qd = max(aporte_uh2 + f, 0.0)
        q_sim.append(qr + qd)
    return q_sim


# ============================================================================
# 4) HBV (VERSIÓN MENSUAL SIMPLIFICADA)
# ============================================================================

DEF_HBV = [
    ("Tt - temperatura umbral de nieve (°C)", 0.0, -3.0, 3.0),
    ("CFMAX - factor grado-día (mm/°C/paso)", 60.0, 20.0, 200.0),
    ("FC - capacidad de campo del suelo (mm)", 250.0, 50.0, 700.0),
    ("BETA - parámetro de forma de la recarga", 2.0, 1.0, 5.0),
    ("LP - fracción de FC para ETP potencial=real", 0.70, 0.30, 1.0),
    ("PERC - percolación UZ->LZ (mm/paso)", 20.0, 0.0, 100.0),
    ("K0 - agotamiento rápido adicional (UZ>UZL)", 0.30, 0.10, 0.90),
    ("UZL - umbral de la zona superior (mm)", 20.0, 0.0, 100.0),
    ("K1 - agotamiento de la zona superior", 0.15, 0.02, 0.50),
    ("K2 - agotamiento de la zona inferior", 0.05, 0.005, 0.20),
]


def simular_hbv_mensual(parametros: Sequence[float], p_mm: Sequence[float], etp_mm: Sequence[float],
                         t_media: Optional[Sequence[float]] = None) -> List[float]:
    tt, cfmax, fc, beta, lp, perc, k0, uzl, k1, k2 = parametros
    nieve, sm, uz, lz = 0.0, fc * 0.5, 0.0, 0.0
    if t_media is None:
        t_media = [tt + 1] * len(p_mm)  # sin dato de temperatura -> se asume sin nieve (T>Tt siempre)
    q_sim = []
    for p, e, t in zip(p_mm, etp_mm, t_media):
        if t <= tt:
            nieve += p
            lluvia_o_deshielo = 0.0
        else:
            deshielo = min(nieve, cfmax * max(t - tt, 0.0))
            nieve -= deshielo
            lluvia_o_deshielo = p + deshielo
        recarga = lluvia_o_deshielo * (sm / fc) ** beta if fc > 0 else 0.0
        sm = min(sm + (lluvia_o_deshielo - recarga), fc)
        etr = e * min(sm / (lp * fc), 1.0) if fc > 0 else 0.0
        sm = max(sm - etr, 0.0)
        uz += recarga
        perc_efectiva = min(perc, uz)
        uz -= perc_efectiva
        lz += perc_efectiva
        q0 = k0 * max(uz - uzl, 0.0)
        uz -= q0
        q1 = k1 * uz
        uz -= q1
        q2 = k2 * lz
        lz -= q2
        q_sim.append(q0 + q1 + q2)
    return q_sim


# ============================================================================
# 5) SAC-SMA (VERSIÓN SIMPLIFICADA)
# ============================================================================

DEF_SAC_SMA = [
    ("UZTWM - tensión zona superior (mm)", 50.0, 10.0, 150.0),
    ("UZFWM - agua libre zona superior (mm)", 40.0, 10.0, 150.0),
    ("UZK - coef. agotamiento agua libre superior", 0.30, 0.10, 0.60),
    ("LZTWM - tensión zona inferior (mm)", 130.0, 50.0, 300.0),
    ("LZFPM - agua libre primaria zona inferior (mm)", 60.0, 10.0, 200.0),
    ("LZFSM - agua libre secundaria zona inferior (mm)", 40.0, 10.0, 150.0),
    ("LZPK - coef. agotamiento primario", 0.010, 0.001, 0.050),
    ("LZSK - coef. agotamiento secundario", 0.080, 0.020, 0.300),
    ("PFREE - % percolación directa a agua libre inferior", 0.20, 0.0, 0.60),
]


def simular_sac_sma(parametros: Sequence[float], p_mm: Sequence[float], etp_mm: Sequence[float]) -> List[float]:
    uztwm, uzfwm, uzk, lztwm, lzfpm, lzfsm, lzpk, lzsk, pfree = parametros
    uztw, uzfw = uztwm * 0.5, uzfwm * 0.3
    lztw, lzfp, lzfs = lztwm * 0.5, lzfpm * 0.3, lzfsm * 0.3
    q_sim = []
    for p, e in zip(p_mm, etp_mm):
        etr_uztw = min(e, uztw)
        uztw -= etr_uztw
        etr_restante = e - etr_uztw
        etr_uzfw = min(etr_restante, uzfw)
        uzfw -= etr_uzfw

        deficit_uztw = uztwm - uztw
        entrada_uztw = min(p, deficit_uztw)
        uztw += entrada_uztw
        excedente = p - entrada_uztw

        deficit_uzfw = uzfwm - uzfw
        entrada_uzfw = min(excedente, deficit_uzfw)
        uzfw += entrada_uzfw
        excedente -= entrada_uzfw  # este remanente es escorrentía directa (suelo saturado)
        directa = excedente

        # percolación de la zona superior (agua libre) a la zona inferior
        percolacion = uzk * uzfw
        uzfw -= percolacion
        interflujo = uzk * uzfw  # simplificación: el agotamiento de UZFW alimenta el interflujo del paso siguiente
        # (se contabiliza como salida de UZFW más abajo)

        deficit_lztw = lztwm - lztw
        a_lztw = min(percolacion * (1 - pfree), deficit_lztw)
        lztw += a_lztw
        resto_percolacion = percolacion - a_lztw

        deficit_lzfp = lzfpm - lzfp
        a_lzfp = min(resto_percolacion * 0.6, deficit_lzfp)
        lzfp += a_lzfp
        deficit_lzfs = lzfsm - lzfs
        a_lzfs = min(resto_percolacion - a_lzfp, deficit_lzfs)
        lzfs += a_lzfs

        q_directa = directa
        q_interflujo = uzk * uzfw
        uzfw -= q_interflujo
        q_primaria = lzpk * lzfp
        lzfp -= q_primaria
        q_secundaria = lzsk * lzfs
        lzfs -= q_secundaria

        q_sim.append(q_directa + q_interflujo + q_primaria + q_secundaria)
    return q_sim


# ============================================================================
# 6) SNOW-SD (RS MINERVE, Manual Técnico v2.25, sección 2.3, ec. B.1-B.10)
# ============================================================================

DEF_SNOW_SD = [
    ("S - coeficiente grado-día de referencia (mm/°C/paso)", 2.0, 0.5, 20.0),
    ("SInt - intervalo estacional del coeficiente grado-día (mm/°C/paso)", 2.0, 0.0, 4.0),
    ("SMin - coeficiente grado-día mínimo (mm/°C/paso)", 1.0, 0.0, 20.0),
    ("SPh - desfase de la función sinusoidal (día del año, 80=21 mar hem. norte, 264=21 sep hem. sur)", 80.0, 1.0, 365.0),
    ("ThetaCri - contenido relativo de agua crítico del paquete de nieve", 0.10, 0.05, 0.40),
    ("bp - coef. de fusión por precipitación líquida (paso/mm)", 0.0125, 0.0, 0.05),
    ("Tcp1 - temperatura crítica mínima de precipitación líquida (°C)", 0.0, -3.0, 3.0),
    ("Tcp2 - temperatura crítica máxima de precipitación sólida (°C)", 4.0, 1.0, 8.0),
    ("Tcf - temperatura crítica de fusión de nieve (°C)", 0.0, -3.0, 3.0),
    ("CFR - coeficiente de recongelamiento", 0.05, 0.0, 1.0),
]


def _separacion_lluvia_nieve(p_mm: float, t_c: float, tcp1: float, tcp2: float):
    """alpha: fracción líquida (ecs. B.1-B.3 / F.1-F.3 / G.1-G.3, idénticas)."""
    if t_c <= tcp1:
        alpha = 0.0
    elif t_c >= tcp2:
        alpha = 1.0
    else:
        alpha = (t_c - tcp1) / (tcp2 - tcp1)
    return alpha * p_mm, (1 - alpha) * p_mm  # Pw (líquida), Psn (sólida)


def _paso_snow_sd(estado: dict, p_mm: float, t_c: float, jd: int, s: float, s_int: float,
                   s_min: float, s_ph: float, theta_cri: float, bp: float, tcp1: float,
                   tcp2: float, tcf: float, cfr: float) -> Tuple[float, dict]:
    """Un paso del modelo Snow-SD (dt=1 paso; ecuaciones B.1 a B.10 del
    Manual Técnico de RS MINERVE). estado = {'Hsnow': .., 'Wsnow': ..}.
    Devuelve (Peq, nuevo_estado)."""
    hsnow, wsnow = estado["Hsnow"], estado["Wsnow"]
    pw, psn = _separacion_lluvia_nieve(p_mm, t_c, tcp1, tcp2)

    s_prime = max(s_min, s + (s_int / 2.0) * math.sin(2 * math.pi * (jd - s_ph) / 365.0))
    if t_c > tcf:
        msn_bruto = s_prime * (1 + bp * pw) * (t_c - tcf)
    else:
        msn_bruto = s_prime * cfr * (t_c - tcf)  # negativo => recongelamiento

    cota_sup = psn + hsnow
    cota_inf = -wsnow
    msn = min(max(msn_bruto, cota_inf), cota_sup)

    hsnow_nuevo = hsnow + (psn - msn)
    hsnow_nuevo = max(hsnow_nuevo, 0.0)

    if hsnow_nuevo <= 1e-9:
        peq = pw + wsnow  # todo el contenido de agua se libera al fundirse el paquete
        wsnow_nuevo = 0.0
    else:
        theta = wsnow / hsnow_nuevo if hsnow_nuevo > 0 else 0.0
        if theta <= theta_cri:
            peq = 0.0
        else:
            peq = (theta - theta_cri) * hsnow_nuevo
        wsnow_nuevo = pw + msn - peq
        wsnow_nuevo = max(wsnow_nuevo, 0.0)

    return max(peq, 0.0), {"Hsnow": hsnow_nuevo, "Wsnow": wsnow_nuevo}


def simular_snow_sd(parametros: Sequence[float], p_mm: Sequence[float], etp_mm: Sequence[float],
                     t_media: Sequence[float], dias_juliano: Optional[Sequence[int]] = None,
                     swe_ini_hsnow_mm: float = 0.0, wsnow_ini_mm: float = 0.0) -> List[float]:
    """Modelo Snow-SD oficial de RS MINERVE. Devuelve la precipitación
    equivalente (Peq, mm/paso) -- ESTE modelo por sí solo no genera
    caudal; Peq es la entrada de otro modelo (GR4J, SAC-SMA, o aquí
    mismo se devuelve como "caudal" en mm equivalentes para poder
    visualizarlo/calibrarlo de forma independiente si se desea)."""
    s, s_int, s_min, s_ph, theta_cri, bp, tcp1, tcp2, tcf, cfr = parametros
    if dias_juliano is None:
        dias_juliano = [180] * len(p_mm)
    estado = {"Hsnow": swe_ini_hsnow_mm, "Wsnow": wsnow_ini_mm}
    peq_serie = []
    for p, t, jd in zip(p_mm, t_media, dias_juliano):
        peq, estado = _paso_snow_sd(estado, p, t, jd, s, s_int, s_min, s_ph, theta_cri,
                                     bp, tcp1, tcp2, tcf, cfr)
        peq_serie.append(peq)
    return peq_serie


# ============================================================================
# 7) RUNOFF (SWMM) -- Manual Técnico sección 2.4, ec. E.1-E.3
# ============================================================================

DEF_SWMM = [
    ("A - superficie de escorrentía (m²)", 1.0e6, 1.0e4, 1.0e8),
    ("L - longitud del plano (m)", 500.0, 10.0, 5000.0),
    ("J0 - pendiente del plano de escorrentía", 0.05, 0.001, 0.5),
    ("K - coeficiente de Strickler (m^1/3/s)", 20.0, 0.1, 90.0),
]


def _paso_reservorio_no_lineal_swmm(h_anterior: float, i_net_m_s: float, k_strickler: float,
                                     j0: float, l_m: float, dt_s: float, max_iter: int = 60) -> float:
    """Resuelve UN paso completo del reservorio no lineal de SWMM
    (ec. E.1-E.3) de forma IMPLÍCITA (Euler hacia atrás + bisección),
    evitando la inestabilidad numérica del esquema explícito cuando el
    paso de tiempo es grande frente a la dinámica rápida del reservorio:
        H_nuevo = H_anterior + 2*dt*(iNet - K*sqrt(J0)*H_nuevo^(5/3)/L)
    f(H) es monótona creciente en H, así que la bisección converge
    siempre."""
    c = k_strickler * math.sqrt(j0) / l_m

    def f(h):
        ir = c * (max(h, 0.0) ** (5.0 / 3.0))
        return h - h_anterior - 2 * dt_s * (i_net_m_s - ir)

    h_lo, h_hi = 0.0, max(h_anterior, 1e-3)
    intentos = 0
    while f(h_hi) < 0 and intentos < 60:
        h_hi *= 2.0
        intentos += 1
    for _ in range(max_iter):
        h_mid = 0.5 * (h_lo + h_hi)
        if f(h_mid) > 0:
            h_hi = h_mid
        else:
            h_lo = h_mid
    return 0.5 * (h_lo + h_hi)


def simular_swmm_runoff(parametros: Sequence[float], p_mm: Sequence[float],
                         duracion_dias: float) -> List[float]:
    """Modelo SWMM (Metcalf & Eddy, 1971) de RS MINERVE: reservorio de
    transferencia NO LINEAL (ec. E.1-E.3), resuelto de forma implícita
    (ver _paso_reservorio_no_lineal_swmm) para estabilidad numérica.
    Entrada iNet = intensidad neta de lluvia (aquí se toma P directamente
    como hietograma neto, sin pérdidas adicionales). SALIDA YA EN m³/s
    (a diferencia de los demás modelos, que trabajan en lámina mm/paso):
    H (nivel, m), A, L, J0, K son magnitudes físicas reales, no una
    abstracción de "lámina sobre la cuenca"."""
    a_m2, l_m, j0, k = parametros
    if l_m <= 0 or k <= 0:
        raise MeanFlowError("L y K deben ser mayores que cero (SWMM).")
    dt_s = duracion_dias * 86400.0
    h = 0.0
    q_sim = []
    for p in p_mm:
        i_net = (p / 1000.0) / dt_s  # mm/paso -> m/s (intensidad neta media del paso)
        h = _paso_reservorio_no_lineal_swmm(h, i_net, k, j0, l_m, dt_s)
        ir_final = k * math.sqrt(j0) * (h ** (5.0 / 3.0)) / l_m if h > 0 else 0.0
        q_sim.append(ir_final * a_m2)
    return q_sim


# ============================================================================
# 8) GSM -- Manual Técnico sección 2.5, ec. F.1-F.17 (nieve + glaciar)
# ============================================================================

DEF_GSM = [
    ("S - coef. grado-día nieve (mm/°C/paso)", 2.0, 0.5, 20.0),
    ("SInt - intervalo estacional nieve (mm/°C/paso)", 2.0, 0.0, 4.0),
    ("SMin - coef. grado-día mínimo nieve (mm/°C/paso)", 1.0, 0.0, 20.0),
    ("SPh - desfase estacional (día del año)", 80.0, 1.0, 365.0),
    ("ThetaCri - contenido relativo de agua crítico", 0.10, 0.05, 0.40),
    ("bp - coef. de fusión por precipitación líquida (paso/mm)", 0.0125, 0.0, 0.05),
    ("Tcp1 - temp. crítica mínima precipitación líquida (°C)", 0.0, -3.0, 3.0),
    ("Tcp2 - temp. crítica máxima precipitación sólida (°C)", 4.0, 1.0, 8.0),
    ("Tcf - temp. crítica de fusión de nieve (°C)", 0.0, -3.0, 3.0),
    ("G - coef. grado-día de fusión glaciar (mm/°C/paso)", 2.0, 0.5, 20.0),
    ("GInt - intervalo estacional glaciar (mm/°C/paso)", 2.0, 0.0, 4.0),
    ("GMin - coef. grado-día mínimo glaciar (mm/°C/paso)", 1.0, 0.0, 20.0),
    ("Tcg - temp. crítica de fusión glaciar (°C)", 0.0, -3.0, 3.0),
    ("Kgl - coef. de vaciado del reservorio de fusión glaciar (1/paso)", 0.3, 0.02, 5.0),
    ("Ksn - coef. de vaciado del reservorio de fusión nival (1/paso)", 0.3, 0.02, 5.0),
    ("CFR - coeficiente de recongelamiento", 0.05, 0.0, 1.0),
]


def simular_gsm(parametros: Sequence[float], p_mm: Sequence[float], etp_mm: Sequence[float],
                 t_media: Sequence[float], dias_juliano: Optional[Sequence[int]] = None) -> List[float]:
    """Modelo GSM (nieve Snow-SD + glaciar) de RS MINERVE. SIMPLIFICACIÓN
    DE UNIDADES: los reservorios lineales de nieve (Rsn) y de fusión
    glaciar (Rgl) se mantienen en lámina (mm) en vez de nivel físico (m)
    multiplicado por la superficie A -- esto es equivalente para el
    caudal específico de la cuenca y evita introducir una segunda
    superficie "A" distinta del área de cuenca ya usada por el resto del
    plugin para la conversión final mm->m³/s."""
    (s, s_int, s_min, s_ph, theta_cri, bp, tcp1, tcp2, tcf,
     g, g_int, g_min, tcg, kgl, ksn, cfr) = parametros
    if dias_juliano is None:
        dias_juliano = [180] * len(p_mm)
    estado_nieve = {"Hsnow": 0.0, "Wsnow": 0.0}
    r_sn, r_gl = 0.0, 0.0
    q_sim = []
    for p, t, jd in zip(p_mm, t_media, dias_juliano):
        peq, estado_nieve = _paso_snow_sd(estado_nieve, p, t, jd, s, s_int, s_min, s_ph,
                                           theta_cri, bp, tcp1, tcp2, tcf, cfr)
        r_sn = r_sn + (peq - ksn * r_sn)
        r_sn = max(r_sn, 0.0)
        q_snow = ksn * r_sn

        g_prime = max(g_min, g + (g_int / 2.0) * math.sin(2 * math.pi * (jd - s_ph) / 365.0))
        if t > tcg and estado_nieve["Hsnow"] <= 1e-9:
            peq_gl = g_prime * (t - tcg)
        else:
            peq_gl = 0.0
        r_gl = r_gl + (peq_gl - kgl * r_gl)
        r_gl = max(r_gl, 0.0)
        q_glacier = kgl * r_gl

        q_sim.append(q_snow + q_glacier)
    return q_sim


# ============================================================================
# 9) SOCONT -- Manual Técnico sección 2.6, ec. G.1-G.18 (nieve + GR3 + SWMM)
# ============================================================================

DEF_SOCONT = [
    ("A - superficie (m²)", 1.0e6, 1.0e4, 1.0e8),
    ("S - coef. grado-día nieve (mm/°C/paso)", 2.0, 0.5, 20.0),
    ("SInt - intervalo estacional nieve (mm/°C/paso)", 2.0, 0.0, 4.0),
    ("SMin - coef. grado-día mínimo nieve (mm/°C/paso)", 1.0, 0.0, 20.0),
    ("SPh - desfase estacional (día del año)", 80.0, 1.0, 365.0),
    ("ThetaCri - contenido relativo de agua crítico", 0.10, 0.05, 0.40),
    ("bp - coef. de fusión por precipitación líquida (paso/mm)", 0.0125, 0.0, 0.05),
    ("Tcp1 - temp. crítica mínima precipitación líquida (°C)", 0.0, -3.0, 3.0),
    ("Tcp2 - temp. crítica máxima precipitación sólida (°C)", 4.0, 1.0, 8.0),
    ("Tcf - temp. crítica de fusión de nieve (°C)", 0.0, -3.0, 3.0),
    ("HGR3Max - altura máxima del reservorio de infiltración (mm)", 200.0, 20.0, 800.0),
    ("KGR3 - coef. de vaciado del reservorio de infiltración (1/paso)", 0.05, 0.001, 0.5),
    ("L - longitud del plano de escorrentía (m)", 500.0, 10.0, 5000.0),
    ("J0 - pendiente del plano de escorrentía", 0.05, 0.001, 0.5),
    ("Kr - coeficiente de Strickler (m^1/3/s)", 20.0, 0.1, 90.0),
    ("CFR - coeficiente de recongelamiento", 0.05, 0.0, 1.0),
]


def simular_socont(parametros: Sequence[float], p_mm: Sequence[float], etp_mm: Sequence[float],
                    t_media: Sequence[float], duracion_dias: float,
                    dias_juliano: Optional[Sequence[int]] = None) -> List[float]:
    """Modelo SOCONT (nieve Snow-SD + reservorio de infiltración GR3 +
    escorrentía SWMM) de RS MINERVE. SALIDA YA EN m³/s (QGR3 se convierte
    de mm/paso a m³/s con A y la duración del paso; Qr del SWMM ya sale
    en m³/s de forma nativa)."""
    (a_m2, s, s_int, s_min, s_ph, theta_cri, bp, tcp1, tcp2, tcf,
     hgr3_max, kgr3, l_m, j0, kr, cfr) = parametros
    if dias_juliano is None:
        dias_juliano = [180] * len(p_mm)
    estado_nieve = {"Hsnow": 0.0, "Wsnow": 0.0}
    h_gr3 = hgr3_max * 0.3
    h_swmm = 0.0
    dt_s = duracion_dias * 86400.0
    q_sim = []
    for p, etp, t, jd in zip(p_mm, etp_mm, t_media, dias_juliano):
        peq, estado_nieve = _paso_snow_sd(estado_nieve, p, t, jd, s, s_int, s_min, s_ph,
                                           theta_cri, bp, tcp1, tcp2, tcf, cfr)

        if h_gr3 <= hgr3_max:
            i_inf = peq * (1 - h_gr3 / hgr3_max) ** 2
            etr = etp * (h_gr3 / hgr3_max)
            q_gr3_mm = kgr3 * h_gr3
        else:
            i_inf = 0.0
            etr = etp
            q_gr3_mm = kgr3 * hgr3_max
        i_net = peq - i_inf
        h_gr3 = h_gr3 + (i_inf - etr - q_gr3_mm)
        h_gr3 = max(h_gr3, 0.0)
        q_gr3_m3s = mm_a_caudal_m3s(q_gr3_mm, a_m2 / 1.0e6, duracion_dias)

        i_net_m_s = (i_net / 1000.0) / dt_s
        h_swmm = _paso_reservorio_no_lineal_swmm(h_swmm, i_net_m_s, kr, j0, l_m, dt_s)
        ir_final = kr * math.sqrt(j0) * (h_swmm ** (5.0 / 3.0)) / l_m if h_swmm > 0 else 0.0
        q_r_m3s = ir_final * a_m2

        q_sim.append(q_gr3_m3s + q_r_m3s)
    return q_sim


# ============================================================================
# 7) INDICADORES DE DESEMPEÑO (Manual Técnico RS MINERVE, Capítulo 3)
# ============================================================================
# Convención: sim = valor simulado; ref (u obs) = valor observado/referencia.
# Todas las fórmulas son las ecuaciones IND.1 a IND.14 del manual.

def nash_sutcliffe(q_obs: Sequence[float], q_sim: Sequence[float]) -> float:
    """Coeficiente de Nash-Sutcliffe (ec. IND.1). -inf a 1, 1=óptimo."""
    media_obs = sum(q_obs) / len(q_obs)
    num = sum((s - o) ** 2 for o, s in zip(q_obs, q_sim))
    den = sum((o - media_obs) ** 2 for o in q_obs)
    return 1 - num / den if den > 0 else float("nan")


def nash_logaritmico(q_obs: Sequence[float], q_sim: Sequence[float], epsilon: float = 1e-4) -> float:
    """Nash-Sutcliffe sobre valores logarítmicos (ec. IND.2), para
    evaluar el desempeño en caudales bajos. epsilon evita ln(0)."""
    ln_obs = [math.log(max(o, epsilon)) for o in q_obs]
    ln_sim = [math.log(max(s, epsilon)) for s in q_sim]
    media_ln_obs = sum(ln_obs) / len(ln_obs)
    num = sum((s - o) ** 2 for o, s in zip(ln_obs, ln_sim))
    den = sum((o - media_ln_obs) ** 2 for o in ln_obs)
    return 1 - num / den if den > 0 else float("nan")


def pearson(q_obs: Sequence[float], q_sim: Sequence[float]) -> float:
    """Coeficiente de correlación de Pearson (ec. IND.3). -1 a 1, 1=óptimo."""
    n = len(q_obs)
    media_o = sum(q_obs) / n
    media_s = sum(q_sim) / n
    cov = sum((s - media_s) * (o - media_o) for o, s in zip(q_obs, q_sim))
    var_o = sum((o - media_o) ** 2 for o in q_obs)
    var_s = sum((s - media_s) ** 2 for s in q_sim)
    if var_o <= 0 or var_s <= 0:
        return float("nan")
    return cov / math.sqrt(var_o * var_s)


def kling_gupta(q_obs: Sequence[float], q_sim: Sequence[float]) -> Dict:
    """Kling-Gupta Efficiency, versión revisada de Kling et al. (2012),
    ec. IND.4 a IND.6. 0 a 1, 1=óptimo."""
    media_o = sum(q_obs) / len(q_obs)
    media_s = sum(q_sim) / len(q_sim)
    if media_o == 0 or media_s == 0:
        return {"KGE": float("nan"), "r": float("nan"), "beta": float("nan"), "gamma": float("nan")}
    r = pearson(q_obs, q_sim)
    beta = media_s / media_o
    std_o = math.sqrt(sum((o - media_o) ** 2 for o in q_obs) / len(q_obs))
    std_s = math.sqrt(sum((s - media_s) ** 2 for s in q_sim) / len(q_sim))
    cv_o = std_o / media_o
    cv_s = std_s / media_s
    gamma = cv_s / cv_o if cv_o != 0 else float("nan")
    kge = 1 - math.sqrt((r - 1) ** 2 + (beta - 1) ** 2 + (gamma - 1) ** 2)
    return {"KGE": kge, "r": r, "beta": beta, "gamma": gamma}


def bias_score(q_obs: Sequence[float], q_sim: Sequence[float]) -> float:
    """Bias Score (ec. IND.7). -inf a 1, 1=óptimo."""
    media_o = sum(q_obs) / len(q_obs)
    media_s = sum(q_sim) / len(q_sim)
    if media_o == 0 or media_s == 0:
        return float("nan")
    return 1 - (max(media_s / media_o, media_o / media_s) - 1) ** 2


def rrmse(q_obs: Sequence[float], q_sim: Sequence[float]) -> float:
    """Relative Root Mean Square Error (ec. IND.8). 0 a +inf, 0=óptimo."""
    media_o = sum(q_obs) / len(q_obs)
    if media_o == 0:
        return float("nan")
    return math.sqrt(sum((s - o) ** 2 for o, s in zip(q_obs, q_sim)) / len(q_obs)) / media_o


def relative_volume_bias(q_obs: Sequence[float], q_sim: Sequence[float]) -> float:
    """Relative Volume Bias (ec. IND.9). -1 a +inf, 0=óptimo."""
    suma_obs = sum(q_obs)
    if suma_obs == 0:
        return float("nan")
    return sum(s - o for o, s in zip(q_obs, q_sim)) / suma_obs


def normalized_peak_error(q_obs: Sequence[float], q_sim: Sequence[float]) -> float:
    """Normalized Peak Error (ec. IND.10-IND.12), sobre los máximos
    absolutos de todo el periodo. -1 a +inf, 0=óptimo."""
    r_max = max(q_obs)
    s_max = max(q_sim)
    if r_max == 0:
        return float("nan")
    return (s_max - r_max) / r_max


def _tabla_contingencia(q_obs: Sequence[float], q_sim: Sequence[float],
                         umbral_obs: float, umbral_sim: float) -> Tuple[int, int, int, int]:
    a = b = c = d = 0
    for o, s in zip(q_obs, q_sim):
        obs_excede = o > umbral_obs
        sim_excede = s > umbral_sim
        if obs_excede and sim_excede:
            a += 1
        elif sim_excede and not obs_excede:
            b += 1
        elif obs_excede and not sim_excede:
            c += 1
        else:
            d += 1
    return a, b, c, d


def peirce_skill_score(q_obs: Sequence[float], q_sim: Sequence[float],
                        umbral_obs: float, umbral_sim: Optional[float] = None) -> float:
    """Peirce Skill Score (ec. IND.13), basado en una tabla de
    contingencia de superación de umbral. -1 a 1, 1=óptimo."""
    umbral_sim = umbral_obs if umbral_sim is None else umbral_sim
    a, b, c, d = _tabla_contingencia(q_obs, q_sim, umbral_obs, umbral_sim)
    den = (a + c) * (b + d)
    return (a * d - b * c) / den if den != 0 else 0.0


def overall_accuracy(q_obs: Sequence[float], q_sim: Sequence[float],
                      umbral_obs: float, umbral_sim: Optional[float] = None) -> float:
    """Overall Accuracy (ec. IND.14). 0 a 1, 1=óptimo."""
    umbral_sim = umbral_obs if umbral_sim is None else umbral_sim
    a, b, c, d = _tabla_contingencia(q_obs, q_sim, umbral_obs, umbral_sim)
    total = a + b + c + d
    return (a + d) / total if total > 0 else float("nan")


def metricas_ajuste(q_obs: Sequence[float], q_sim: Sequence[float],
                     umbral_obs: Optional[float] = None, umbral_sim: Optional[float] = None) -> Dict:
    """Los 10 indicadores del Capítulo 3 del Manual Técnico de RS MINERVE.
    Si no se da un umbral, PSS y OA usan la media observada como umbral
    por defecto (criterio práctico razonable para "evento" vs "no evento")."""
    if umbral_obs is None:
        umbral_obs = sum(q_obs) / len(q_obs)
    kge = kling_gupta(q_obs, q_sim)
    return {
        "Nash": nash_sutcliffe(q_obs, q_sim),
        "Nash_ln": nash_logaritmico(q_obs, q_sim),
        "Pearson": pearson(q_obs, q_sim),
        "KGE": kge["KGE"],
        "BiasScore": bias_score(q_obs, q_sim),
        "RRMSE": rrmse(q_obs, q_sim),
        "RVB": relative_volume_bias(q_obs, q_sim),
        "NPE": normalized_peak_error(q_obs, q_sim),
        "PSS": peirce_skill_score(q_obs, q_sim, umbral_obs, umbral_sim),
        "OA": overall_accuracy(q_obs, q_sim, umbral_obs, umbral_sim),
    }


# ============================================================================
# 8) CALIBRACIÓN GENÉRICA (SIMPLEX DE NELDER-MEAD, SIN DEPENDENCIAS)
# ============================================================================

def calibrar_nelder_mead(func_simular: Callable[[Sequence[float]], List[float]], q_obs: Sequence[float],
                          x0: Sequence[float], limites: Sequence[Tuple[float, float]],
                          max_iter: int = 300) -> Dict:
    """Minimiza (1-NSE) variando los parámetros del modelo con un simplex
    de Nelder-Mead simple (sin SciPy), respetando los límites min/max de
    cada parámetro (se recortan -clip- en cada evaluación)."""
    n = len(x0)

    def recortar(x):
        return [min(max(xi, lim[0]), lim[1]) for xi, lim in zip(x, limites)]

    def costo(x):
        x = recortar(x)
        try:
            q_sim = func_simular(x)
        except MeanFlowError:
            return 1e6
        if any(math.isnan(v) or math.isinf(v) for v in q_sim):
            return 1e6
        nse = nash_sutcliffe(q_obs, q_sim)
        if math.isnan(nse):
            return 1e6
        return 1 - nse

    # simplex inicial: x0 + una perturbación del 10% (o un paso mínimo) en cada dimensión
    simplex = [list(x0)]
    for i in range(n):
        punto = list(x0)
        paso = 0.1 * abs(x0[i]) if x0[i] != 0 else 0.1 * (limites[i][1] - limites[i][0])
        punto[i] += paso if paso != 0 else 0.1
        simplex.append(punto)
    valores = [costo(p) for p in simplex]

    alpha, gamma, rho, sigma = 1.0, 2.0, 0.5, 0.5
    for _ in range(max_iter):
        orden = sorted(range(len(simplex)), key=lambda i: valores[i])
        simplex = [simplex[i] for i in orden]
        valores = [valores[i] for i in orden]

        if abs(valores[-1] - valores[0]) < 1e-8:
            break

        centroide = [sum(simplex[i][j] for i in range(n)) / n for j in range(n)]
        peor = simplex[-1]
        reflejado = [centroide[j] + alpha * (centroide[j] - peor[j]) for j in range(n)]
        f_reflejado = costo(reflejado)

        if valores[0] <= f_reflejado < valores[-2]:
            simplex[-1], valores[-1] = reflejado, f_reflejado
        elif f_reflejado < valores[0]:
            expandido = [centroide[j] + gamma * (reflejado[j] - centroide[j]) for j in range(n)]
            f_expandido = costo(expandido)
            if f_expandido < f_reflejado:
                simplex[-1], valores[-1] = expandido, f_expandido
            else:
                simplex[-1], valores[-1] = reflejado, f_reflejado
        else:
            contraido = [centroide[j] + rho * (peor[j] - centroide[j]) for j in range(n)]
            f_contraido = costo(contraido)
            if f_contraido < valores[-1]:
                simplex[-1], valores[-1] = contraido, f_contraido
            else:
                mejor = simplex[0]
                for i in range(1, len(simplex)):
                    simplex[i] = [mejor[j] + sigma * (simplex[i][j] - mejor[j]) for j in range(n)]
                    valores[i] = costo(simplex[i])

    orden = sorted(range(len(simplex)), key=lambda i: valores[i])
    mejor_x = recortar(simplex[orden[0]])
    mejor_costo = valores[orden[0]]
    q_sim_final = func_simular(mejor_x)
    return {"parametros_calibrados": mejor_x, "NSE": 1 - mejor_costo,
            "metricas": metricas_ajuste(q_obs, q_sim_final), "q_sim": q_sim_final}


# ============================================================================
# 9) REGISTRO DE MODELOS DISPONIBLES (para la UI)
# ============================================================================

MODELOS_DISPONIBLES = {
    "Lutz Scholz (simplificado)": {
        "func": lambda p, precip, etp, t, jd, dt: simular_lutz_scholz(p, precip, etp),
        "parametros": DEF_LUTZ_SCHOLZ, "requiere_temperatura": False, "requiere_fecha": False,
        "salida_m3s_directo": False},
    "GR2M": {
        "func": lambda p, precip, etp, t, jd, dt: simular_gr2m(p, precip, etp),
        "parametros": DEF_GR2M, "requiere_temperatura": False, "requiere_fecha": False,
        "salida_m3s_directo": False},
    "GR4J": {
        "func": lambda p, precip, etp, t, jd, dt: simular_gr4j(p, precip, etp),
        "parametros": DEF_GR4J, "requiere_temperatura": False, "requiere_fecha": False,
        "salida_m3s_directo": False},
    "HBV (mensual simplificado)": {
        "func": lambda p, precip, etp, t, jd, dt: simular_hbv_mensual(p, precip, etp, t),
        "parametros": DEF_HBV, "requiere_temperatura": True, "requiere_fecha": False,
        "salida_m3s_directo": False},
    "SAC-SMA (simplificado)": {
        "func": lambda p, precip, etp, t, jd, dt: simular_sac_sma(p, precip, etp),
        "parametros": DEF_SAC_SMA, "requiere_temperatura": False, "requiere_fecha": False,
        "salida_m3s_directo": False},
    "Snow-SD (RS MINERVE, produce Peq -- no es caudal real)": {
        "func": lambda p, precip, etp, t, jd, dt: simular_snow_sd(p, precip, etp, t, jd),
        "parametros": DEF_SNOW_SD, "requiere_temperatura": True, "requiere_fecha": True,
        "salida_m3s_directo": False},
    "Runoff (SWMM)": {
        "func": lambda p, precip, etp, t, jd, dt: simular_swmm_runoff(p, precip, dt),
        "parametros": DEF_SWMM, "requiere_temperatura": False, "requiere_fecha": False,
        "salida_m3s_directo": True},
    "GSM (nieve + glaciar, RS MINERVE)": {
        "func": lambda p, precip, etp, t, jd, dt: simular_gsm(p, precip, etp, t, jd),
        "parametros": DEF_GSM, "requiere_temperatura": True, "requiere_fecha": True,
        "salida_m3s_directo": False},
    "SOCONT (nieve + GR3 + SWMM, RS MINERVE)": {
        "func": lambda p, precip, etp, t, jd, dt: simular_socont(p, precip, etp, t, dt, jd),
        "parametros": DEF_SOCONT, "requiere_temperatura": True, "requiere_fecha": True,
        "salida_m3s_directo": True},
}
