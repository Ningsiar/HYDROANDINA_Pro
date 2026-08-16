# -*- coding: utf-8 -*-
"""
core/estabilidad_muros.py

Verificación de ESTABILIDAD GLOBAL de un muro de contención en
voladizo (volteo, deslizamiento, excentricidad/presiones de contacto y
capacidad portante) -- complementa el diseño por FLEXIÓN del muro ya
existente en core/bim_refuerzo.py, que NO verifica estabilidad global
(un muro puede salir bien armado a flexión y aun así fallar por
volteo si la zapata es angosta).

MÉTODO IMPLEMENTADO: equilibrio límite clásico con factores de
seguridad globales -- el más usado en la práctica peruana (ACI/AASHTO
y bibliografía Das/Bowles; la E.050 no tabula FS de volteo/
deslizamiento para muros de contención explícitamente, solo fija FS de
capacidad portante -- Art. 21: 3.0 estático/2.5 sísmico -- y de
estabilidad de taludes -- Art. 30.3: 1.5/1.25 -- los 1.5-2.0 y 1.25-1.5
de volteo/deslizamiento de este módulo vienen de esa tradición
bibliográfica, decláralos así en su memoria de cálculo):

  - VOLTEO respecto al pie (punta): FS_v = ΣM_resistentes/ΣM_actuantes
    ≥ 1.5-2.0 estático, ≥ 1.25-1.5 sísmico.
  - DESLIZAMIENTO en la base: FS_d = (N·tanδ + ca·B + Ep)/ΣFh ≥ 1.5
    estático, ≥ 1.25 sísmico. δ = factor·φ (típicamente ⅔φ a φ), Ep
    (empuje pasivo en la puntera) normalmente reducido al 50% o
    despreciado (riesgo de excavación futura frente al muro).
  - EXCENTRICIDAD: e ≤ B/6 para evitar tracciones (distribución
    trapezoidal clásica); si e > B/6, ancho efectivo de Meyerhof
    (B'=B-2e, presión uniforme sobre B') en vez de permitir tracción.
  - CAPACIDAD PORTANTE: Terzaghi-Bowles (E.050 Art. 20, ver
    core/geotecnia_e050.py), con el ancho EFECTIVO (B' si e>B/6) y las
    cargas (N, Fh) de este mismo análisis -- FS 3.0 estático/2.5
    sísmico (Art. 21).

MÉTODOS CONSIDERADOS PERO NO IMPLEMENTADOS (documentados para que
quede explícito por qué, no son necesariamente inferiores -- son
alcances distintos):
  - Criterio de excentricidad LRFD (e≤B/4 suelo, ≤3B/8 roca) y
    verificación por factores de resistencia parciales φτ/φep -- del
    AASHTO LRFD / Manual de Puentes del MTC, para OBRAS VIALES, no
    para el alcance general de edificaciones de la E.050.
  - Eurocódigo 7 (modos EQU/GEO, factores parciales γφ=γc=1.25): no es
    la normativa peruana.
  - Diseño por desplazamiento (Richards-Elms, Newmark, Whitman-Liao):
    alternativa racional al FS≥1 bajo sismo (acepta un desplazamiento
    permanente tolerable, 25-50 mm típico) -- válida para una fase
    posterior si se requiere ese enfoque en vez de FS.
  - Métodos numéricos (MEF/MDF con reducción c-φ -- Plaxis, Midas GTS,
    FLAC): requieren software externo especializado.
  - Estabilidad global de la masa de suelo que envuelve al muro
    (Bishop, Janbu, Spencer, Morgenstern-Price -- falla profunda, NO
    la estabilidad del muro en sí): un módulo aparte, de alcance
    mayor -- se olvida seguido en la práctica y es causa frecuente de
    colapso; considérelo cuando el muro esté sobre un talud o suelo
    blando.

DOS COSAS QUE DECIDEN MÁS QUE EL MÉTODO ELEGIDO (adviértalo siempre en
la memoria de cálculo): el DRENAJE -- un lloradero tapado convierte
Ka·γ·H²/2 en un empuje HIDROSTÁTICO que duplica la solicitación, es la
causa #1 de fallas reales de muros -- y el PESO DEL RELLENO SOBRE EL
TALÓN, que es lo que realmente estabiliza al volteo en un muro en
voladizo (no el peso propio del muro, que suele ser secundario).

Geometría asumida (muro en voladizo, de puntera a talón):
    |<-- b_puntera -->|<-- e_pantalla -->|<-- b_talon -->|
    (lado del relleno excavado)          (lado del relleno retenido)
Se analiza POR METRO LINEAL de muro (zapata "corrida").

Este módulo NO reemplaza el Estudio de Mecánica de Suelos (EMS) ni el
criterio de un ingeniero geotécnico/estructural colegiado.
"""
import math

from . import lateral_pressures as lp
from . import geotecnia_e050 as geo

FS_VOLTEO_ESTATICO_MIN = 1.5
FS_VOLTEO_SISMICO_MIN = 1.25
FS_DESLIZAMIENTO_ESTATICO_MIN = 1.5
FS_DESLIZAMIENTO_SISMICO_MIN = 1.25
FACTOR_DELTA_DESLIZAMIENTO_DEFECTO = 2.0 / 3.0  # δ = ⅔φ, valor típico (rango ⅔φ a φ)
FACTOR_REDUCCION_PASIVO_DEFECTO = 0.5


class EstabilidadMurosError(Exception):
    """Datos insuficientes, geometría inestable, o combinación de
    ángulos/cargas fuera de rango físico -- el mensaje explica qué
    falla exactamente."""


def excentricidad_y_presiones(n_kn: float, m_resistente_kn_m: float, m_actuante_kn_m: float, b_m: float):
    """Excentricidad de la resultante respecto al centro de la zapata,
    y presiones de contacto -- momentos tomados respecto al PIE (borde
    de la puntera, x=0). x̄ = (M_resistente - M_actuante)/N (distancia
    desde el pie al punto de aplicación de la resultante N),
    e = B/2 - x̄.
      - Si e ≤ B/6 (SIN tracción): distribución trapezoidal clásica,
        q_max/q_min = (N/B)·(1 ± 6e/B).
      - Si e > B/6: ANCHO EFECTIVO de Meyerhof, B'=B-2e, presión
        UNIFORME q=N/B' sobre B' -- en vez de permitir tracción (el
        suelo no la resiste)."""
    if n_kn <= 0:
        raise EstabilidadMurosError("la fuerza vertical resultante N debe ser positiva.")
    if b_m <= 0:
        raise EstabilidadMurosError("el ancho de la zapata B debe ser positivo.")
    x_barra = (m_resistente_kn_m - m_actuante_kn_m) / n_kn
    if not (0.0 < x_barra < b_m):
        raise EstabilidadMurosError(
            f"la resultante cae fuera de la base de la zapata (x̄={x_barra:.3f} m, B={b_m:.3f} m) "
            f"-- el muro estaría en volteo inminente con esta geometría/cargas; revíselas antes de "
            f"seguir (ver también FS_volteo, que ya debería haber avisado esto).")
    e = b_m / 2.0 - x_barra
    cumple_b6 = abs(e) <= b_m / 6.0
    if cumple_b6:
        q_max = (n_kn / b_m) * (1.0 + 6.0 * e / b_m)
        q_min = (n_kn / b_m) * (1.0 - 6.0 * e / b_m)
        b_efectiva = b_m
    else:
        b_efectiva = b_m - 2.0 * abs(e)
        if b_efectiva <= 0:
            raise EstabilidadMurosError(
                f"excentricidad e={e:.3f} m demasiado grande -- el ancho efectivo de Meyerhof "
                f"(B'=B-2e={b_efectiva:.3f} m) resulta nulo o negativo; la zapata es inestable "
                f"con esta geometría/cargas.")
        q_max = q_min = n_kn / b_efectiva
    return {
        "x_barra_m": round(x_barra, 4), "excentricidad_m": round(e, 4),
        "cumple_e_b6": cumple_b6, "b_efectiva_m": round(b_efectiva, 4),
        "q_max_kpa": round(q_max, 2), "q_min_kpa": round(q_min, 2),
    }


def verificar_volteo(m_resistente_kn_m: float, m_actuante_kn_m: float, condicion: str = "estatico"):
    """FS_volteo = ΣM_resistentes/ΣM_actuantes respecto al pie -- ≥1.5
    estático, ≥1.25 sísmico (mínimos de la tradición ACI/AASHTO/Das-
    Bowles; el rango recomendado llega a 2.0/1.5, ver docstring del
    módulo). Devuelve (fs, fs_minimo, cumple)."""
    if m_actuante_kn_m <= 0:
        raise EstabilidadMurosError("el momento actuante (volteo) debe ser positivo.")
    fs_minimo = {"estatico": FS_VOLTEO_ESTATICO_MIN, "sismico": FS_VOLTEO_SISMICO_MIN}.get(condicion)
    if fs_minimo is None:
        raise EstabilidadMurosError(f"condición «{condicion}» no reconocida -- use 'estatico' o 'sismico'.")
    fs = m_resistente_kn_m / m_actuante_kn_m
    return fs, fs_minimo, fs >= fs_minimo


def verificar_deslizamiento(n_kn: float, fh_kn: float, phi_suelo_deg: float, b_m: float,
                             ca_kpa: float = 0.0, ep_kn: float = 0.0,
                             factor_delta: float = FACTOR_DELTA_DESLIZAMIENTO_DEFECTO,
                             condicion: str = "estatico"):
    """FS_deslizamiento = (N·tanδ + ca·B + Ep) / ΣFh -- ≥1.5 estático,
    ≥1.25 sísmico. δ = factor_delta·φ (por defecto ⅔φ, rango típico
    ⅔φ a φ). `ep_kn` YA debe venir reducido (50% o despreciado según
    el criterio del usuario, ver docstring del módulo -- este módulo
    no aplica la reducción por usted). Devuelve (fs, fs_minimo,
    cumple, delta_usado_deg)."""
    if fh_kn <= 0:
        raise EstabilidadMurosError("la fuerza horizontal actuante ΣFh debe ser positiva.")
    if n_kn <= 0:
        raise EstabilidadMurosError("la fuerza vertical N debe ser positiva.")
    fs_minimo = {"estatico": FS_DESLIZAMIENTO_ESTATICO_MIN,
                 "sismico": FS_DESLIZAMIENTO_SISMICO_MIN}.get(condicion)
    if fs_minimo is None:
        raise EstabilidadMurosError(f"condición «{condicion}» no reconocida -- use 'estatico' o 'sismico'.")
    delta_deg = factor_delta * phi_suelo_deg
    resistencia = n_kn * math.tan(math.radians(delta_deg)) + ca_kpa * b_m + ep_kn
    fs = resistencia / fh_kn
    return fs, fs_minimo, fs >= fs_minimo, delta_deg


def verificar_muro_contencion(
        altura_relleno_m: float, espesor_pantalla_m: float, b_puntera_m: float, b_talon_m: float,
        espesor_zapata_m: float, df_m: float, gamma_suelo_kn_m3: float, phi_suelo_deg: float,
        c_suelo_kpa: float = 0.0, gamma_concreto_kn_m3: float = 24.0, metodo_empuje: str = "rankine",
        delta_muro_deg: float = 0.0, beta_muro_deg: float = 90.0, i_relleno_deg: float = 0.0,
        sobrecarga_kn_m2: float = 0.0, considerar_empuje_pasivo: bool = False,
        factor_reduccion_pasivo: float = FACTOR_REDUCCION_PASIVO_DEFECTO,
        factor_delta_deslizamiento: float = FACTOR_DELTA_DESLIZAMIENTO_DEFECTO,
        adherencia_ca_kpa: float = None, zona_sismica: str = None) -> dict:
    """Verificación COMPLETA de un muro de contención en voladizo, por
    metro lineal (zapata corrida) -- volteo, deslizamiento,
    excentricidad/presiones y capacidad portante, en condición
    ESTÁTICA y, si se indica `zona_sismica`, también en condición
    SÍSMICA (con el incremento dinámico de Mononobe-Okabe, punto de
    aplicación de Seed & Whitman a 0.6H).

    El empuje activo se calcula sobre un PLANO VERTICAL virtual que
    pasa por el borde posterior del talón (el método estándar para
    muros en voladizo -- evita modelar la fricción muro-concreto
    contra la cara real, inclinada, de la pantalla), con la altura
    TOTAL del relleno + zapata. `metodo_empuje`: "rankine" (δ=0 en ese
    plano, el caso simple/conservador estándar) o "coulomb" (permite
    incluir δ, β, i si el usuario quiere modelar la fricción sobre la
    cara real del muro en vez del plano virtual -- úselo con criterio).

    `adherencia_ca_kpa`: adherencia losa-suelo para el deslizamiento --
    si no se indica, se asume igual a `c_suelo_kpa` (simplificación
    usual; en la práctica a veces se reduce a 0.5-0.75·c, ajuste ese
    valor si su criterio geotécnico lo exige).

    Devuelve un dict con "estatico" y (si aplica) "sismico", cada uno
    con volteo/deslizamiento/presiones/capacidad_portante, más las
    cargas (N, pesos, empujes) para trazabilidad en la memoria de
    cálculo."""
    if altura_relleno_m <= 0 or espesor_pantalla_m <= 0 or espesor_zapata_m <= 0:
        raise EstabilidadMurosError("altura de relleno, espesor de pantalla y espesor de zapata deben ser > 0.")
    if b_puntera_m < 0 or b_talon_m <= 0:
        raise EstabilidadMurosError("el talón debe ser > 0 (puntera puede ser 0 en un muro sin puntera).")

    b_total = b_puntera_m + espesor_pantalla_m + b_talon_m
    h_total = altura_relleno_m + espesor_zapata_m  # altura para el empuje (relleno + zapata)
    l_corrida = 1.0e6  # zapata "corrida" -- B/L -> 0, factores de forma -> 1.0 (franja 2D clásica)

    if adherencia_ca_kpa is None:
        adherencia_ca_kpa = c_suelo_kpa

    # --- pesos (por metro lineal de muro) ---
    w_zapata = gamma_concreto_kn_m3 * b_total * espesor_zapata_m
    w_pantalla = gamma_concreto_kn_m3 * espesor_pantalla_m * altura_relleno_m
    w_relleno_talon = gamma_suelo_kn_m3 * b_talon_m * altura_relleno_m
    v_sobrecarga = sobrecarga_kn_m2 * b_talon_m
    n_total = w_zapata + w_pantalla + w_relleno_talon + v_sobrecarga

    # --- brazos desde el PIE (x=0, borde exterior de la puntera) ---
    brazo_zapata = b_total / 2.0
    brazo_pantalla = b_puntera_m + espesor_pantalla_m / 2.0
    brazo_talon = b_puntera_m + espesor_pantalla_m + b_talon_m / 2.0
    m_resistente_pesos = (w_zapata * brazo_zapata + w_pantalla * brazo_pantalla
                           + w_relleno_talon * brazo_talon + v_sobrecarga * brazo_talon)

    # --- empuje activo (plano vertical virtual en el talón) ---
    if metodo_empuje == "rankine":
        ka = lp.coeficiente_empuje_activo_rankine(phi_suelo_deg)
    elif metodo_empuje == "coulomb":
        ka = lp.coeficiente_empuje_activo_coulomb(phi_suelo_deg, delta_muro_deg, beta_muro_deg, i_relleno_deg)
    else:
        raise EstabilidadMurosError(f"método de empuje «{metodo_empuje}» no reconocido -- use 'rankine' o 'coulomb'.")
    pa_kn, brazo_pa = lp.presion_suelo_resultante(gamma_suelo_kn_m3, h_total, ka)
    psc_kn, brazo_psc = ((0.0, 0.0) if sobrecarga_kn_m2 <= 0
                         else lp.presion_sobrecarga_resultante(ka, sobrecarga_kn_m2, h_total))

    # --- empuje pasivo en la puntera (opcional, resistencia al deslizamiento) ---
    ep_kn = 0.0
    if considerar_empuje_pasivo and df_m > 0:
        kp = lp.coeficiente_empuje_pasivo_rankine(phi_suelo_deg)
        ep_bruto, _brazo_ep = lp.presion_suelo_resultante(gamma_suelo_kn_m3, df_m, kp)
        ep_kn = ep_bruto * factor_reduccion_pasivo

    def _evaluar(fh_extra_kn=0.0, m_extra_kn_m=0.0, condicion="estatico", detalle_extra=None):
        fh_total = pa_kn + psc_kn + fh_extra_kn
        m_actuante = pa_kn * brazo_pa + psc_kn * brazo_psc + m_extra_kn_m
        fs_v, fs_v_min, cumple_v = verificar_volteo(m_resistente_pesos, m_actuante, condicion)
        fs_d, fs_d_min, cumple_d, delta_usado = verificar_deslizamiento(
            n_total, fh_total, phi_suelo_deg, b_total, adherencia_ca_kpa, ep_kn,
            factor_delta_deslizamiento, condicion)
        presiones = excentricidad_y_presiones(n_total, m_resistente_pesos, m_actuante, b_total)
        qd = geo.capacidad_portante_ultima(
            c_suelo_kpa, phi_suelo_deg, gamma_suelo_kn_m3, gamma_suelo_kn_m3, df_m,
            presiones["b_efectiva_m"], l_corrida, fh_kn=fh_total, n_kn=n_total)
        q_adm = geo.presion_admisible(qd, condicion)
        cumple_capacidad = presiones["q_max_kpa"] <= q_adm
        resultado = {
            "condicion": condicion, "fh_total_kn_m": round(fh_total, 2), "m_actuante_kn_m": round(m_actuante, 2),
            "m_resistente_kn_m": round(m_resistente_pesos, 2),
            "fs_volteo": round(fs_v, 3), "fs_volteo_minimo": fs_v_min, "cumple_volteo": cumple_v,
            "fs_deslizamiento": round(fs_d, 3), "fs_deslizamiento_minimo": fs_d_min,
            "cumple_deslizamiento": cumple_d, "delta_deslizamiento_deg": round(delta_usado, 2),
            "excentricidad": presiones,
            "capacidad_portante_ultima_kpa": round(qd, 2), "presion_admisible_kpa": round(q_adm, 2),
            "cumple_capacidad_portante": cumple_capacidad,
        }
        if detalle_extra:
            resultado.update(detalle_extra)
        return resultado

    resultado_estatico = _evaluar(condicion="estatico")

    resultado_sismico = None
    if zona_sismica:
        delta_p_kn, brazo_sismico, kh = lp.incremento_sismico_empuje(
            gamma_suelo_kn_m3, h_total, phi_suelo_deg, zona_sismica)
        resultado_sismico = _evaluar(
            fh_extra_kn=delta_p_kn, m_extra_kn_m=delta_p_kn * brazo_sismico, condicion="sismico",
            detalle_extra={"delta_p_sismico_kn_m": round(delta_p_kn, 2), "kh": round(kh, 3),
                            "zona_sismica": zona_sismica})

    return {
        "geometria": {"b_total_m": round(b_total, 3), "h_total_m": round(h_total, 3),
                      "b_puntera_m": b_puntera_m, "b_talon_m": b_talon_m,
                      "espesor_pantalla_m": espesor_pantalla_m, "espesor_zapata_m": espesor_zapata_m},
        "cargas_verticales_kn_m": {"peso_zapata": round(w_zapata, 2), "peso_pantalla": round(w_pantalla, 2),
                                    "peso_relleno_talon": round(w_relleno_talon, 2),
                                    "sobrecarga_vertical": round(v_sobrecarga, 2), "n_total": round(n_total, 2)},
        "empuje_activo": {"ka": round(ka, 4), "metodo": metodo_empuje, "pa_kn_m": round(pa_kn, 2),
                          "brazo_pa_m": round(brazo_pa, 3)},
        "empuje_pasivo_kn_m": round(ep_kn, 2),
        "estatico": resultado_estatico,
        "sismico": resultado_sismico,
        "metodo": ("Equilibrio límite clásico (FS globales) -- volteo respecto al pie, deslizamiento "
                   "en la base, excentricidad e≤B/6 (Meyerhof B'=B-2e si se excede), capacidad "
                   "portante Terzaghi-Bowles (E.050 Art. 20-21). Cálculo PRELIMINAR -- no reemplaza "
                   "el Estudio de Mecánica de Suelos ni el criterio de un ingeniero estructural/"
                   "geotécnico colegiado. Verifique especialmente el sistema de drenaje real (un "
                   "lloradero tapado duplica el empuje de diseño) antes de un expediente definitivo."),
    }
