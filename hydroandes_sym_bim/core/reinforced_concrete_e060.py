# -*- coding: utf-8 -*-
"""
core/reinforced_concrete_e060.py

Diseño simplificado por flexión de una franja de 1 m de ancho de muro/
losa de concreto armado, método de resistencia (rotura), con la misma
formulación de la Norma E.060 "Concreto Armado" (equivalente al ACI
318 en unidades kg/cm², como se enseña y aplica en el Perú -- ver p.ej.
Ottazzi, "Apuntes del curso Concreto Armado 1", PUCP, para la
formulación de As por flexión y el As mínimo por flexión tipo viga).

ALCANCE: diseño por flexión + acero mínimo (temperatura/retracción,
E.060 -- losas y muros, y mínimo por flexión tipo viga) + verificación
básica de corte por concreto (sin diseño de estribos). NO cubre:
punzonamiento, juntas, detallado de anclaje/empalmes, ni las
combinaciones de carga completas de la norma (aquí solo se combinan
las cargas de empuje lateral que calcula core/lateral_pressures.py).
Verifique los coeficientes y artículos exactos contra la edición
vigente de la norma antes de un expediente técnico definitivo -- este
módulo no reemplaza el criterio de un ingeniero estructural colegiado.
"""
import math

PHI_FLEXION = 0.90   # E.060 -- flexión, sección controlada por tracción
PHI_CORTE = 0.85      # E.060 -- cortante (sin refuerzo por corte)

# Barras de refuerzo comerciales en Perú: (nombre, diámetro cm, área cm²)
BARRAS_COMERCIALES = [
    ("3/8\"", 0.95, 0.71),
    ("1/2\"", 1.27, 1.29),
    ("5/8\"", 1.59, 2.00),
    ("3/4\"", 1.91, 2.84),
    ("1\"", 2.54, 5.10),
]


def as_requerido_flexion(mu_kg_cm: float, b_cm: float, d_cm: float,
                          fc_kg_cm2: float, fy_kg_cm2: float):
    """Área de acero requerida por flexión (cm²) para un momento último
    Mu (kg·cm) en una franja de ancho b_cm (cm) y peralte efectivo
    d_cm (cm). Devuelve None si la sección es insuficiente (el momento
    excede la capacidad con este espesor -- aumente el muro/losa)."""
    if mu_kg_cm <= 0:
        return 0.0
    ru = mu_kg_cm / (PHI_FLEXION * b_cm * d_cm ** 2)
    limite = 0.85 * fc_kg_cm2
    discriminante = 1.0 - (2.0 * ru / limite)
    if discriminante <= 0:
        return None
    rho = (limite / fy_kg_cm2) * (1.0 - math.sqrt(discriminante))
    return rho * b_cm * d_cm


def as_minimo_temperatura(b_cm: float, h_cm: float, fy_kg_cm2: float) -> float:
    """Acero mínimo por temperatura/retracción (E.060, losas y muros),
    en cm² -- rho_min = 0.0018·4200/fy, no menor a 0.0014, sobre la
    sección BRUTA (b·h, no b·d)."""
    rho_min = max(0.0018 * 4200.0 / fy_kg_cm2, 0.0014)
    return rho_min * b_cm * h_cm


def as_minimo_flexion(b_cm: float, d_cm: float, fc_kg_cm2: float, fy_kg_cm2: float) -> float:
    """Acero mínimo por flexión tipo viga -- As_min = 0.7·√f'c/fy · b·d
    (formulación usual en textos peruanos, equivalente en unidades
    kg/cm² al mínimo de ACI 318)."""
    return (0.7 * math.sqrt(fc_kg_cm2) / fy_kg_cm2) * b_cm * d_cm


def espaciamiento_sugerido(as_requerido_cm2_por_m: float, diametro_pulg: str = "1/2\""):
    """Espaciamiento (cm) de la barra indicada para cubrir
    As_requerido_cm2_por_m en una franja de 1 m (100 cm) de ancho --
    redondeado HACIA ABAJO al múltiplo de 5 cm más cercano (más acero
    que el estrictamente necesario, del lado seguro). Devuelve
    (espaciamiento_cm, nombre_barra_usada)."""
    barra = next((b for b in BARRAS_COMERCIALES if b[0] == diametro_pulg), BARRAS_COMERCIALES[1])
    area_barra_cm2 = barra[2]
    if as_requerido_cm2_por_m <= 0:
        return None, barra[0]
    s = (area_barra_cm2 * 100.0) / as_requerido_cm2_por_m
    s_redondeado = max(5.0, math.floor(s / 5.0) * 5.0)
    return s_redondeado, barra[0]


def verificar_corte(vu_kg: float, b_cm: float, d_cm: float, fc_kg_cm2: float):
    """Verificación básica de corte por concreto, sin refuerzo por
    corte: φ·Vc = φ · 0.53·√f'c · b · d (E.060, kg/cm²). Devuelve
    (phi_Vc_kg, cumple_bool)."""
    vc = 0.53 * math.sqrt(fc_kg_cm2) * b_cm * d_cm
    phi_vc = PHI_CORTE * vc
    return phi_vc, vu_kg <= phi_vc
