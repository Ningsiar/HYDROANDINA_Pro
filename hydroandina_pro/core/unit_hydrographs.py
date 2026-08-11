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
    Qp = 2.08 * A / tp                  (m3/s POR CENTÍMETRO de lluvia efectiva, A en km2 -- Aparicio
                                          Mijares, "Fundamentos de Hidrología de Superficie", y Ven Te
                                          Chow et al., "Applied Hydrology": la constante 2.08 SIEMPRE se
                                          da en la bibliografía en m3/s por CM, nunca por mm)
    Tb = 2.67 * tp                      (tiempo base, h)

  Snyder (1938) [SI]:
    tp = 0.75 * Ct * (L * Lca)^0.3      (horas; L, Lca en km; Ct: 1.8-2.2 típico)
    tr = tp / 5.5                        (duración estándar, h)
    qp = 2.75 * Cp / tp                  (m3/s/km2 POR CENTÍMETRO de lluvia efectiva; Cp: 0.4-0.8 --
                                          misma convención "por cm" que SCS, mismas fuentes)
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

CORRECCIÓN DE UNIDADES (encontrada y corregida verificando la
conservación de masa: el volumen bajo cada hidrograma unitario DEBE
reproducir exactamente 1 mm de lámina sobre toda el área, por
definición de "hidrograma unitario"; medido con la regla del trapecio
antes de esta corrección, SCS y Snyder daban ~10 veces ese volumen):

  1. SCS y Snyder: como se documenta arriba, las constantes 2.08 y 2.75
     de la bibliografía dan m3/s POR CENTÍMETRO de lluvia efectiva, no
     por milímetro -- pero el resto del pipeline de precipitación de
     este plugin trabaja enteramente en mm (P24h, S del número de
     curva, lluvia_efectiva_incr_mm de la función de abajo). Aplicar
     esas constantes tal cual a una lluvia efectiva en mm sobreestimaba
     el caudal pico en un factor de 10 (1 cm = 10 mm).
       - SCS: Tb = 2.67*tp no depende de la constante de qp, así que
         basta con dividir 2.08 -> 0.208 (verificado: proporción
         volumen-UH/esperado 1.00, antes 9.98).
       - Snyder: Tb = 5.56/qp_específico SÍ depende de esa constante --
         si se divide qp_específico entre 10 antes de calcular Tb, Tb
         sale 10 veces más largo de lo debido, y como el volumen del
         triángulo es 0.5*qp*Tb, un qp 10 veces más chico junto a un Tb
         10 veces más grande SE CANCELAN (verificado: con ese orden, la
         proporción seguía dando ~10, sin corregirse). La forma correcta
         calcula Tb con la constante "por cm" tal cual la bibliografía
         (que es con la que esa fórmula de Tb está calibrada), y solo
         convierte a "por mm" el qp final usado como altura del
         triángulo del hidrograma unitario (proporción ya corregida:
         1.00, antes 10.01, verificado también para varios Ct/Cp).
  2. Clark: el hidrograma de tránsito por embalse lineal se truncaba a
     la misma duración que la curva área-tiempo (Tc), cortando la cola
     de recesión exponencial del embalse lineal, que en teoría se
     extiende indefinidamente (solo tiende a cero, nunca llega
     exactamente). Esto perdía ~63% del volumen total (verificado: la
     proporción medida era 0.37, no 1.00). Se corrige extendiendo la
     recursión con entrada cero hasta que la salida decae por debajo de
     un umbral despreciable (0.1% del pico) o se alcanza un tope de
     seguridad de pasos, en vez de detenerse abruptamente al final de
     la curva área-tiempo.
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
    # 2.08 (bibliografía) da m3/s POR CENTÍMETRO; /10 para m3/s por
    # MILÍMETRO, consistente con el resto del pipeline (mm). Ver nota de
    # "CORRECCIÓN DE UNIDADES" en el docstring del módulo.
    qp = 0.208 * area_km2 / tp_h  # m3/s por mm
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
    # Las fórmulas clásicas de qp y Tb (bibliografía) están AMBAS
    # calibradas asumiendo qp en m3/s/km2 POR CENTÍMETRO -- se calculan
    # tal cual con esa convención (incluido Tb, cuya constante 5.56
    # también asume qp "por cm") y solo AL FINAL se convierte qp a m3/s
    # por MILÍMETRO (/10) para el hidrograma unitario. Si se dividiera
    # qp_especifico entre 10 antes de calcular Tb, Tb saldría 10 veces
    # más largo de lo debido, y como el volumen del triángulo es
    # 0.5*qp*Tb, un qp 10 veces más chico junto a un Tb 10 veces más
    # grande se cancelan exactamente -- el error de volumen NO se
    # corregía (verificado numéricamente: con esa forma, la razón
    # volumen-UH/volumen-esperado seguía dando ~10, sin cambio).
    qp_especifico_cm = 2.75 * cp / tp_h  # m3/s/km2 por CENTÍMETRO (bibliografía)
    tb_h = 5.56 / qp_especifico_cm       # horas (fórmula calibrada para qp "por cm")
    qp_especifico = qp_especifico_cm / 10.0  # m3/s/km2 por MILÍMETRO
    qp = area_km2 * qp_especifico            # m3/s por mm

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
    # La recesión de un embalse lineal es exponencial y en teoría no
    # termina nunca (solo tiende a 0); truncar el hidrograma justo al
    # final de la curva área-tiempo (como antes) cortaba la cola y
    # perdía una fracción significativa del volumen total (~63% en
    # pruebas, ver "CORRECCIÓN DE UNIDADES" en el docstring). Se
    # continúa la misma recursión con entrada cero hasta que la salida
    # decae por debajo del 0.1% del pico, o hasta un tope de seguridad
    # de pasos (20 veces la duración de la curva área-tiempo) para no
    # iterar indefinidamente si C_B >= 1 por un R_storage mal ingresado.
    qp_provisional = max(outflow) if len(outflow) > 1 else 0.0
    umbral_cola = max(qp_provisional * 0.001, 1e-9)
    tope_pasos_cola = 20 * max(len(inflow_m3s_por_mm), 1)
    pasos_cola = 0
    while outflow[-1] > umbral_cola and pasos_cola < tope_pasos_cola:
        o_actual = c_b * outflow[-1]
        outflow.append(max(o_actual, 0.0))
        pasos_cola += 1
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
                           s_mm: float, metodo: str, modelo_perdidas: str = "scs",
                           params_perdidas: dict = None, **kwargs_metodo) -> dict:
    """
    hietograma_total_mm: incrementos de lluvia TOTAL (no efectiva) por
        intervalo de duración dt_h, p.ej. de un bloque alterno o de una
        distribución SCS Tipo II ya escalada a la lámina de diseño.
    metodo: 'scs', 'snyder' o 'clark' (hidrograma unitario).
    modelo_perdidas: 'scs' (número de curva, por defecto y comportamiento
        histórico del plugin), 'green_ampt' u 'horton'. Ver
        core/infiltration.py.
    params_perdidas: parámetros del modelo de pérdidas elegido; se ignora
        con 'scs', que usa s_mm.
    kwargs_metodo: parámetros específicos de cada método (ver las
        funciones uh_scs_triangular / uh_snyder / uh_clark).
    Devuelve dict con 'tiempos_h', 'caudal_m3s', 'caudal_pico_m3s',
    'tiempo_pico_h', y el objeto ResultadoUH del hidrograma unitario usado.
    """
    # Modelo de PÉRDIDAS: por defecto el número de curva SCS (el que usó
    # siempre el plugin), o bien Green-Ampt/Horton desde core/infiltration.py.
    # Los tres producen lo mismo conceptualmente -- la lluvia efectiva que
    # alimenta el hidrograma unitario -- pero SCS-CN depende solo de la
    # lámina acumulada mientras que los otros dos responden a la INTENSIDAD
    # de cada intervalo, de modo que distinguen una tormenta corta e intensa
    # de una larga y suave con la misma lámina total.
    detalle_perdidas = None
    if modelo_perdidas in (None, "scs", "scs_cn"):
        lluvia_efectiva = lluvia_efectiva_incremental(hietograma_total_mm, s_mm)
    elif modelo_perdidas in ("green_ampt", "horton"):
        from . import infiltration
        params = dict(params_perdidas or {})
        if modelo_perdidas == "green_ampt":
            detalle_perdidas = infiltration.infiltracion_green_ampt(
                hietograma_total_mm, dt_h, **params)
        else:
            detalle_perdidas = infiltration.infiltracion_horton(
                hietograma_total_mm, dt_h, **params)
        lluvia_efectiva = detalle_perdidas["lluvia_efectiva_incr_mm"]
    else:
        raise ValueError("modelo_perdidas debe ser 'scs', 'green_ampt' u 'horton'.")

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

    # Volumen total de escorrentía directa: integral del hidrograma
    # (regla del trapecio, paso constante dt_h) -- útil para verificar
    # que el volumen escurrido sea consistente con la lámina efectiva
    # total (lluvia_efectiva * área), y como insumo directo para
    # dimensionar un embalse/laguna de detención.
    dt_s = dt_h * 3600.0
    if len(caudal_total) >= 2:
        volumen_m3 = dt_s * (sum(caudal_total) - 0.5 * caudal_total[0] - 0.5 * caudal_total[-1])
    elif caudal_total:
        volumen_m3 = caudal_total[0] * dt_s
    else:
        volumen_m3 = 0.0
    lamina_efectiva_equivalente_mm = (
        (volumen_m3 / (area_km2 * 1e6)) * 1000.0 if area_km2 > 0 else 0.0
    )

    return {
        "tiempos_h": tiempos_totales,
        "caudal_m3s": caudal_total,
        "caudal_pico_m3s": round(qp, 3),
        "tiempo_pico_h": round(tp, 3),
        "lluvia_efectiva_incr_mm": lluvia_efectiva,
        "volumen_escorrentia_directa_m3": round(volumen_m3, 1),
        "volumen_escorrentia_directa_hm3": round(volumen_m3 / 1e6, 5),
        "lamina_efectiva_equivalente_mm": round(lamina_efectiva_equivalente_mm, 2),
        "unit_hydrograph": uh,
        "modelo_perdidas": modelo_perdidas or "scs",
        "detalle_perdidas": detalle_perdidas,
    }
