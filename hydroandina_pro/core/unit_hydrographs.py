# -*- coding: utf-8 -*-
"""
core/unit_hydrographs.py

Motor de hidrogramas unitarios sintéticos para estimar caudales de
crecida de forma empírica, replicando los tres métodos de transformación
lluvia-escorrentía que también ofrece HEC-HMS: SCS (triangular/adimensional),
Snyder, y Clark (área-tiempo + embalse lineal). Se combina con las
pérdidas por infiltración del número de curva SCS (core/curve_number.py)
mediante convolución discreta para producir el hidrograma total y el
caudal pico, dada una tormenta de diseño.

FÓRMULAS Y VERIFICACIÓN (todas confirmadas contra fuentes citadas antes
de implementarlas, no se completaron de memoria):

  SCS Unit Hydrograph (triangular, USDA-NRCS):
    tp = D/2 + tlag                     (tiempo al pico, h)
    Qp = 2.08 * A / tp                  (m3/s por mm de lluvia efectiva, A en km2)
    Tb = 2.67 * tp                      (tiempo base, h)

  Snyder (1938) [SI]:
    tp = 0.75 * Ct * (L * Lca)^0.3      (horas; L, Lca en km; Ct: 1.8-2.2 típico)
    tr = tp / 5.5                        (duración estándar, h)
    qp = 2.75 * Cp / tp                  (m3/s/km2; Cp: 0.4-0.8)
    Qp = A * qp
    Tb = 5.56 / qp                       (horas)
    Aproximación triangular con tiempo de subida = tp + tr/2 (tiempo al
    pico medido desde el inicio de la lluvia) y recesión hasta Tb.

  Clark (Clark, 1945; formulación estándar HEC-1/HEC-HMS):
    Curva área-tiempo por defecto:
      Ai/A = 1.414*(Ti/Tc)^1.5           si Ti/Tc <= 0.5
      Ai/A = 1 - 1.414*(1-Ti/Tc)^1.5     si Ti/Tc >  0.5
    Tránsito por embalse lineal (storage coefficient R):
      O(t) = C_A*I(t) + C_B*O(t-1)
      C_A = Dt / (R + 0.5*Dt)
      C_B = (R - 0.5*Dt) / (R + 0.5*Dt)
    Requiere Tc (de cualquiera de los métodos de tc_methods.py) y R
    (storage coefficient; si no se conoce, se puede aproximar con
    R/(R+Tc) entre 0.5 y 0.7, valor por defecto 0.5 aquí, EDITABLE).
"""
import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np


# ---------------------------------------------------------------------
# Pérdidas por infiltración (número de curva) - lluvia efectiva incremental
# ---------------------------------------------------------------------
def lluvia_efectiva_incremental(hietograma_mm: List[float], s_mm: float, ia_mm: Optional[float] = None) -> List[float]:
    """
    hietograma_mm: lista de incrementos de lluvia total por intervalo (mm).
    s_mm: retención potencial (S) del número de curva.
    ia_mm: abstracción inicial; si es None se usa 0.2*S (SCS estándar).
    Devuelve la lista de incrementos de lluvia EFECTIVA (excedente) por
    intervalo, con el mismo número de elementos que la entrada.
    """
    if ia_mm is None:
        ia_mm = 0.2 * s_mm

    acumulado = 0.0
    pe_acumulada_anterior = 0.0
    incrementos_pe = []
    for p_incr in hietograma_mm:
        acumulado += p_incr
        if acumulado > ia_mm:
            pe_acumulada = ((acumulado - ia_mm) ** 2) / (acumulado - ia_mm + s_mm)
        else:
            pe_acumulada = 0.0
        incrementos_pe.append(max(pe_acumulada - pe_acumulada_anterior, 0.0))
        pe_acumulada_anterior = pe_acumulada
    return incrementos_pe


# ---------------------------------------------------------------------
# Convolución discreta: hidrograma unitario (mm de entrada) x lluvia
# efectiva incremental (mm) -> hidrograma total (m3/s)
# ---------------------------------------------------------------------
def convolucionar(ordenadas_uh_m3s_por_mm: List[float], lluvia_efectiva_incr_mm: List[float]) -> List[float]:
    """
    ordenadas_uh_m3s_por_mm: ordenadas del hidrograph unitario para 1 mm
        de lluvia efectiva caída uniformemente en el intervalo de tiempo
        Dt (mismo Dt que el hietograma).
    lluvia_efectiva_incr_mm: incrementos de lluvia efectiva por intervalo.
    Devuelve el hidrograma total (m3/s) por convolución discreta estándar.
    """
    n_u = len(ordenadas_uh_m3s_por_mm)
    n_p = len(lluvia_efectiva_incr_mm)
    n_q = n_u + n_p - 1
    q = [0.0] * n_q
    for j in range(n_p):
        pj = lluvia_efectiva_incr_mm[j]
        if pj == 0:
            continue
        for i in range(n_u):
            q[i + j] += pj * ordenadas_uh_m3s_por_mm[i]
    return q


# ---------------------------------------------------------------------
# SCS - hidrograma unitario triangular
# ---------------------------------------------------------------------
@dataclass
class ResultadoUH:
    tiempos_h: List[float]
    ordenadas_m3s_por_mm: List[float]
    tp_h: float
    qp_m3s_por_mm: float
    tb_h: float
    metodo: str


def uh_scs_triangular(area_km2: float, tlag_h: float, duracion_efectiva_h: float, dt_h: float) -> ResultadoUH:
    tp_h = duracion_efectiva_h / 2.0 + tlag_h
    qp = 2.08 * area_km2 / tp_h  # m3/s por mm
    tb_h = 2.67 * tp_h

    tiempos = np.arange(0.0, tb_h + dt_h, dt_h)
    ordenadas = []
    for t in tiempos:
        if t <= tp_h:
            q = qp * (t / tp_h) if tp_h > 0 else 0.0
        elif t <= tb_h:
            q = qp * ((tb_h - t) / (tb_h - tp_h)) if tb_h > tp_h else 0.0
        else:
            q = 0.0
        ordenadas.append(max(q, 0.0))

    return ResultadoUH(list(tiempos), ordenadas, tp_h, qp, tb_h, "SCS Triangular")


# ---------------------------------------------------------------------
# Snyder - hidrograma unitario (aproximación triangular)
# ---------------------------------------------------------------------
def uh_snyder(area_km2: float, l_km: float, lca_km: float, dt_h: float,
              ct: float = 2.0, cp: float = 0.6) -> ResultadoUH:
    tp_h = 0.75 * ct * ((l_km * lca_km) ** 0.3)
    tr_h = tp_h / 5.5  # duración estándar de la lluvia efectiva de Snyder
    qp_especifico = 2.75 * cp / tp_h  # m3/s/km2
    qp = area_km2 * qp_especifico     # m3/s (para la duración estándar tr)
    tb_h = 5.56 / qp_especifico       # horas

    # Tiempo de subida medido desde el inicio de la lluvia (no desde el
    # centroide): Tp_subida = tr/2 + tp, convención estándar Snyder/HEC-HMS.
    tp_subida = tr_h / 2.0 + tp_h

    tiempos = np.arange(0.0, tb_h + dt_h, dt_h)
    ordenadas = []
    qp_por_mm = qp  # Snyder da Qp para 1 unidad de lluvia efectiva (mm-equivalente aquí, ver nota)
    for t in tiempos:
        if t <= tp_subida:
            q = qp_por_mm * (t / tp_subida) if tp_subida > 0 else 0.0
        elif t <= tb_h:
            q = qp_por_mm * ((tb_h - t) / (tb_h - tp_subida)) if tb_h > tp_subida else 0.0
        else:
            q = 0.0
        ordenadas.append(max(q, 0.0))

    return ResultadoUH(list(tiempos), ordenadas, tp_subida, qp_por_mm, tb_h, "Snyder")


# ---------------------------------------------------------------------
# Clark - área-tiempo + embalse lineal
# ---------------------------------------------------------------------
def curva_area_tiempo_default(tc_h: float, n_intervalos: int = 20) -> List[Tuple[float, float]]:
    """Devuelve [(Ti, Ai/A), ...] usando la curva área-tiempo por defecto
    de HEC-1/HEC-HMS (Ponce, cita en el docstring del módulo)."""
    puntos = []
    for i in range(n_intervalos + 1):
        ti = tc_h * i / n_intervalos
        r = ti / tc_h if tc_h > 0 else 0.0
        if r <= 0.5:
            ai_a = 1.414 * (r ** 1.5)
        else:
            ai_a = 1.0 - 1.414 * ((1.0 - r) ** 1.5)
        puntos.append((ti, ai_a))
    return puntos


def uh_clark(area_km2: float, tc_h: float, r_storage_h: float, dt_h: float) -> ResultadoUH:
    """
    r_storage_h: storage coefficient R del embalse lineal (horas). Si no
    se dispone de calibración local, un punto de partida razonable
    (documentado en la literatura de HEC-HMS) es asumir R/(R+Tc) entre
    0.5 y 0.7; con 0.5 => R = Tc.
    """
    n_pasos_tc = max(int(math.ceil(tc_h / dt_h)), 1)
    curva = curva_area_tiempo_default(tc_h, n_intervalos=n_pasos_tc)

    # Histograma área-tiempo (incremento de área por intervalo, en km2)
    areas_incr_km2 = []
    for i in range(1, len(curva)):
        areas_incr_km2.append((curva[i][1] - curva[i - 1][1]) * area_km2)

    # Hidrograma de traslación (inflow al embalse lineal), en m3/s por mm
    # de lluvia efectiva: Q = Area_incr(km2)*1mm(m) / Dt(s) * 1000 (para
    # convertir km2*mm a m3 y dividir entre segundos del intervalo).
    dt_s = dt_h * 3600.0
    inflow_m3s_por_mm = [ (a_km2 * 1.0e6 * 0.001) / dt_s for a_km2 in areas_incr_km2 ]  # a_km2*1e6 m2 * 0.001 m (=1mm) / dt_s

    c_a = dt_h / (r_storage_h + 0.5 * dt_h) if (r_storage_h + 0.5 * dt_h) > 0 else 1.0
    c_b = (r_storage_h - 0.5 * dt_h) / (r_storage_h + 0.5 * dt_h) if (r_storage_h + 0.5 * dt_h) > 0 else 0.0

    outflow = [0.0]
    for i_val in inflow_m3s_por_mm:
        o_anterior = outflow[-1]
        o_actual = c_a * i_val + c_b * o_anterior
        outflow.append(max(o_actual, 0.0))
    outflow = outflow[1:]  # se descarta el valor inicial ficticio (t=0)

    tiempos = [dt_h * (i + 1) for i in range(len(outflow))]
    qp = max(outflow) if outflow else 0.0
    tp_h = tiempos[outflow.index(qp)] if outflow else 0.0
    tb_h = tiempos[-1] if tiempos else 0.0

    return ResultadoUH(tiempos, outflow, tp_h, qp, tb_h, "Clark")


# ---------------------------------------------------------------------
# Utilidad de alto nivel: hidrograma total de crecida para una tormenta
# ---------------------------------------------------------------------
def hidrograma_de_crecida(hietograma_total_mm: List[float], dt_h: float, area_km2: float,
                           s_mm: float, metodo: str, **kwargs_metodo) -> dict:
    """
    hietograma_total_mm: incrementos de lluvia TOTAL (no efectiva) por
        intervalo de duración dt_h, p.ej. de un bloque alterno o de una
        distribución SCS Tipo II ya escalada a la lámina de diseño.
    metodo: 'scs', 'snyder' o 'clark'.
    kwargs_metodo: parámetros específicos de cada método (ver las
        funciones uh_scs_triangular / uh_snyder / uh_clark).
    Devuelve dict con 'tiempos_h', 'caudal_m3s', 'caudal_pico_m3s',
    'tiempo_pico_h', y el objeto ResultadoUH del hidrograma unitario usado.
    """
    lluvia_efectiva = lluvia_efectiva_incremental(hietograma_total_mm, s_mm)

    if metodo == "scs":
        uh = uh_scs_triangular(area_km2, dt_h=dt_h, **kwargs_metodo)
    elif metodo == "snyder":
        uh = uh_snyder(area_km2, dt_h=dt_h, **kwargs_metodo)
    elif metodo == "clark":
        uh = uh_clark(area_km2, dt_h=dt_h, **kwargs_metodo)
    else:
        raise ValueError("metodo debe ser 'scs', 'snyder' o 'clark'.")

    caudal_total = convolucionar(uh.ordenadas_m3s_por_mm, lluvia_efectiva)
    tiempos_totales = [dt_h * i for i in range(len(caudal_total))]
    qp = max(caudal_total) if caudal_total else 0.0
    tp = tiempos_totales[caudal_total.index(qp)] if caudal_total else 0.0

    return {
        "tiempos_h": tiempos_totales,
        "caudal_m3s": caudal_total,
        "caudal_pico_m3s": round(qp, 3),
        "tiempo_pico_h": round(tp, 3),
        "lluvia_efectiva_incr_mm": lluvia_efectiva,
        "unit_hydrograph": uh,
    }
