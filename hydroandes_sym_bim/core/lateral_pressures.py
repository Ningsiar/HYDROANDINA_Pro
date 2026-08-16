# -*- coding: utf-8 -*-
"""
core/lateral_pressures.py

Empujes laterales sobre un muro/losa vertical (agua + suelo, estático
y sísmico) para el diseño simplificado de refuerzo del Módulo BIM (ver
core/bim_refuerzo.py). Métodos: Rankine (empuje activo Ka) y Jaky
(empuje en reposo Ko) para la parte estática; Mononobe-Okabe (1929)
para el incremento sísmico dinámico, con el punto de aplicación de
Seed & Whitman (1970) para ese incremento (0.6H en vez de H/3).

ALCANCE Y LIMITACIONES -- léase antes de usar en un expediente técnico:
  - Muro vertical (β=0), relleno horizontal (i=0), fricción muro-suelo
    despreciada (δ=0) -- simplificaciones conservadoras estándar para
    un cálculo PRELIMINAR; un análisis definitivo debe considerar la
    geometría e interacción suelo-estructura reales.
  - kh = 0.5·Z (coeficiente sísmico horizontal pseudo-estático, kv=0) --
    una regla simplificada de uso común en la práctica peruana para el
    diseño pseudo-estático de muros de contención, NO un análisis
    dinámico modal-espectral completo de la Norma E.030.
  - Verifique los coeficientes y el zonificado exactos contra la
    edición vigente de la Norma E.030 antes de un expediente técnico
    definitivo -- este módulo no reemplaza el criterio de un ingeniero
    estructural/geotécnico colegiado.
"""
import math

# Factor de zona sísmica Z (aceleración máxima del terreno, fracción de
# g) según la Norma E.030 "Diseño Sismorresistente" -- 4 zonas.
ZONAS_SISMICAS_E030 = {
    "Zona 1": 0.10,
    "Zona 2": 0.25,
    "Zona 3": 0.35,
    "Zona 4": 0.45,
}


def presion_hidrostatica_resultante(gamma_agua_kn_m3: float, altura_agua_m: float):
    """Empuje hidrostático triangular (0 en la superficie libre, máximo
    en el fondo) -- resultante P (kN por metro de muro) y brazo desde
    la base (m)."""
    p = 0.5 * gamma_agua_kn_m3 * altura_agua_m ** 2
    brazo = altura_agua_m / 3.0
    return p, brazo


def coeficiente_empuje_reposo(phi_suelo_deg: float) -> float:
    """Ko de Jaky: Ko = 1 - sen(phi)."""
    return 1.0 - math.sin(math.radians(phi_suelo_deg))


def coeficiente_empuje_activo_rankine(phi_suelo_deg: float) -> float:
    """Ka de Rankine (muro vertical, relleno horizontal, sin fricción
    muro-suelo): Ka = tan²(45° - phi/2)."""
    return math.tan(math.radians(45.0 - phi_suelo_deg / 2.0)) ** 2


def presion_suelo_resultante(gamma_suelo_kn_m3: float, altura_m: float, k: float):
    """Empuje de suelo triangular con coeficiente k (Ko o Ka) --
    resultante P (kN/m) y brazo desde la base (m)."""
    p = 0.5 * k * gamma_suelo_kn_m3 * altura_m ** 2
    brazo = altura_m / 3.0
    return p, brazo


def presion_sobrecarga_resultante(k: float, sobrecarga_kn_m2: float, altura_m: float):
    """Empuje uniforme por sobrecarga viva en superficie (distribución
    rectangular) -- resultante P (kN/m) y brazo desde la base (m)."""
    p = k * sobrecarga_kn_m2 * altura_m
    brazo = altura_m / 2.0
    return p, brazo


def coeficiente_empuje_activo_sismico_mononobe_okabe(phi_suelo_deg: float, kh: float, kv: float = 0.0) -> float:
    """Kae de Mononobe-Okabe (1929) -- coeficiente de empuje activo
    DINÁMICO TOTAL (estático + sísmico), muro vertical, relleno
    horizontal, sin fricción muro-suelo (β=i=δ=0)."""
    phi = math.radians(phi_suelo_deg)
    theta = math.atan(kh / max(1.0 - kv, 1e-6))
    if phi - theta <= 0:
        raise ValueError(
            "kh es demasiado grande para este ángulo de fricción del suelo (phi - theta <= 0) -- "
            "el método de Mononobe-Okabe no converge; revise phi_suelo o la zona sísmica.")
    numerador = math.cos(phi - theta) ** 2
    interior = math.sqrt((math.sin(phi) * math.sin(phi - theta)) / math.cos(theta))
    denominador = math.cos(theta) * (1.0 + interior) ** 2
    return numerador / denominador


def incremento_sismico_empuje(gamma_suelo_kn_m3: float, altura_m: float, phi_suelo_deg: float,
                               zona_sismica: str, coeficiente_reduccion_kh: float = 0.5, kv: float = 0.0):
    """Incremento DINÁMICO del empuje de tierra por sismo (Mononobe-
    Okabe total menos la parte estática activa de Rankine), aplicado a
    0.6·H desde la base (Seed & Whitman, 1970) en vez de H/3. Devuelve
    (delta_P_kN_m, brazo_m, kh_usado)."""
    if zona_sismica not in ZONAS_SISMICAS_E030:
        raise ValueError(
            f"zona sísmica «{zona_sismica}» no reconocida; use una de {list(ZONAS_SISMICAS_E030)}")
    z = ZONAS_SISMICAS_E030[zona_sismica]
    kh = coeficiente_reduccion_kh * z
    ka_estatico = coeficiente_empuje_activo_rankine(phi_suelo_deg)
    kae = coeficiente_empuje_activo_sismico_mononobe_okabe(phi_suelo_deg, kh, kv)
    p_total_dinamico = 0.5 * kae * gamma_suelo_kn_m3 * altura_m ** 2
    p_estatico_activo = 0.5 * ka_estatico * gamma_suelo_kn_m3 * altura_m ** 2
    delta_p = max(p_total_dinamico - p_estatico_activo, 0.0)
    brazo = 0.6 * altura_m
    return delta_p, brazo, kh
