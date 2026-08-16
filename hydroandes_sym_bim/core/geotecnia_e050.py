# -*- coding: utf-8 -*-
"""
core/geotecnia_e050.py

Capacidad portante y asentamientos según la Norma E.050 "Suelos y
Cimentaciones" (2018, Ministerio de Vivienda, Construcción y
Saneamiento) -- motor compartido por core/estabilidad_muros.py (zapata
corrida bajo un muro de contención) y core/zapatas.py (zapatas
aisladas de columnas), sin dependencias de Qt (funciones puras).

MÉTODO (Art. 20 E.050): capacidad de carga última por la ecuación de
Terzaghi MODIFICADA con los factores de Bowles (1996) -- no Terzaghi
original -- con factores de forma (s) e inclinación de carga (i):

    q_d = c·Nc·sc·ic + γ1·Df·Nq·sq·iq + 0.5·γ2·B·Nγ·sγ·iγ

donde:
  - Nc, Nq, Nγ: factores de capacidad de carga (función de φ).
  - sc, sq, sγ: factores de FORMA de la zapata (B/L).
  - ic, iq, iγ: factores de INCLINACIÓN de la carga (ángulo de la
    resultante respecto a la vertical) -- 1.0 si la carga es vertical.
  - γ1: peso específico del suelo SOBRE el nivel de desplante
    (sobrecarga); γ2: peso específico del suelo BAJO la zapata (puede
    ser el mismo valor si el perfil es homogéneo).
  - Art. 20.2 (suelos cohesivos, φ=0): se reduce a q_d = Nc·c·ic·sc.
  - Art. 20.3 (suelos friccionantes, c=0): se reduce a
    q_d = Nq·γ1·Df·iq·sq + 0.5·γ2·B·Nγ·iγ·sγ.
  Ambos son casos particulares de la fórmula general de arriba, que es
  la que implementa este módulo (evita mantener dos fórmulas por
  separado).

PRESIÓN ADMISIBLE (Art. 21): q_adm = q_d / FS, con FS=3.0 en condición
ESTÁTICA y FS=2.5 en condición SÍSMICA o de viento -- el Perú NO aplica
LRFD geotécnico en edificaciones (ese enfoque es del Manual de Puentes
del MTC/AASHTO, fuera del alcance de este módulo).

ASENTAMIENTOS (Art. 19): el criterio de aceptación de la E.050 no es
el asentamiento total sino la DISTORSIÓN ANGULAR entre dos puntos de
apoyo (Tabla 8): ≤1/500 sin riesgo de agrietamiento, 1/500-1/300
pueden aparecer primeras grietas, 1/300-1/150 riesgo de daño
estructural, >1/150 daño estructural esperado. Este módulo NO calcula
el asentamiento en sí (elástico o por consolidación -- depende del
perfil estratigráfico real del EMS) -- solo evalúa la distorsión
angular dado un asentamiento diferencial YA ESTIMADO por el usuario a
partir de su Estudio de Mecánica de Suelos.

ALCANCE: cálculo PRELIMINAR de apoyo. NO reemplaza el Estudio de
Mecánica de Suelos (EMS) firmado por un Profesional Responsable (Art.
15.3.2 y ss. de la E.050) ni el criterio de un ingeniero geotécnico
colegiado. Análisis especiales obligatorios cuando aplican (licuación
Art. 16.2.8/38, suelos colapsables Art. 35, suelos expansivos Art. 37)
NO están cubiertos por este módulo -- requieren el EMS completo, no un
estudio simplificado (ITS).
"""
import math

FS_CAPACIDAD_PORTANTE_ESTATICO = 3.0
FS_CAPACIDAD_PORTANTE_SISMICO = 2.5

# Tabla 8 (E.050) -- distorsión angular límite.
DISTORSION_ANGULAR_SIN_AGRIETAMIENTO = 1.0 / 500.0
DISTORSION_ANGULAR_PRIMERAS_GRIETAS = 1.0 / 300.0
DISTORSION_ANGULAR_DANIO_ESTRUCTURAL = 1.0 / 150.0


class GeotecniaError(Exception):
    """Datos insuficientes o inconsistentes para calcular la capacidad
    portante o la distorsión angular -- el mensaje explica qué falla."""


def factores_capacidad_portante_bowles(phi_suelo_deg: float):
    """(Nc, Nq, Nγ) -- Terzaghi modificado con las expresiones de
    Bowles (1996): Nq = e^(π·tanφ)·tan²(45+φ/2), Nc = (Nq-1)/tanφ,
    Nγ = 2·(Nq+1)·tanφ. Para φ=0 usa Nc=5.14 (solución exacta de
    Prandtl -- el límite de (Nq-1)/tanφ cuando φ→0) y Nq=1, Nγ=0."""
    if phi_suelo_deg < 0:
        raise GeotecniaError("el ángulo de fricción φ no puede ser negativo.")
    if phi_suelo_deg == 0:
        return 5.14, 1.0, 0.0
    phi = math.radians(phi_suelo_deg)
    nq = math.exp(math.pi * math.tan(phi)) * math.tan(math.radians(45.0 + phi_suelo_deg / 2.0)) ** 2
    nc = (nq - 1.0) / math.tan(phi)
    ngamma = 2.0 * (nq + 1.0) * math.tan(phi)
    return nc, nq, ngamma


def factores_forma_bowles(b_m: float, l_m: float, phi_suelo_deg: float, nc: float, nq: float):
    """(sc, sq, sγ) -- factores de forma de Bowles para una zapata
    rectangular B×L (se usa min(B,L)/max(B,L), así que el orden de los
    argumentos no importa). B/L→0 aproxima una zapata corrida."""
    if b_m <= 0 or l_m <= 0:
        raise GeotecniaError("B y L deben ser positivos.")
    br = min(b_m, l_m) / max(b_m, l_m)
    phi = math.radians(phi_suelo_deg)
    sc = 1.0 + br * (nq / nc) if nc > 0 else 1.0
    sq = 1.0 + br * math.tan(phi)
    sgamma = 1.0 - 0.4 * br
    return sc, sq, sgamma


def factores_inclinacion_bowles(fh_kn: float, n_kn: float, phi_suelo_deg: float):
    """(ic, iq, iγ) -- factores de inclinación de carga de Bowles, a
    partir del ángulo ψ de la resultante respecto a la vertical
    (ψ = atan(|Fh|/N)): ic=iq=(1-ψ/90°)², iγ=(1-ψ/φ)² (0 si ψ≥φ, la
    carga sale del cono de fricción del suelo). Con Fh=0 devuelve
    (1,1,1) -- sin reducción por inclinación."""
    if n_kn <= 0:
        raise GeotecniaError("la carga vertical N debe ser positiva para los factores de inclinación.")
    psi_deg = math.degrees(math.atan(abs(fh_kn) / n_kn))
    ic = iq = (1.0 - psi_deg / 90.0) ** 2
    igamma = (1.0 - psi_deg / phi_suelo_deg) ** 2 if 0 < psi_deg < phi_suelo_deg else 0.0
    return ic, iq, igamma


def capacidad_portante_ultima(c_kpa: float, phi_suelo_deg: float, gamma1_kn_m3: float,
                               gamma2_kn_m3: float, df_m: float, b_m: float, l_m: float = None,
                               fh_kn: float = 0.0, n_kn: float = None) -> float:
    """Capacidad de carga última q_d (kPa), Terzaghi-Bowles (E.050 Art.
    20) -- ver docstring del módulo para la fórmula completa.
    `l_m=None` asume zapata cuadrada (L=B). Los factores de inclinación
    solo se aplican si se dan `fh_kn` (≠0) Y `n_kn`; si no, ic=iq=iγ=1."""
    if l_m is None:
        l_m = b_m
    if df_m < 0:
        raise GeotecniaError("la profundidad de desplante Df no puede ser negativa.")
    nc, nq, ngamma = factores_capacidad_portante_bowles(phi_suelo_deg)
    sc, sq, sgamma = factores_forma_bowles(b_m, l_m, phi_suelo_deg, nc, nq)
    if fh_kn and n_kn:
        ic, iq, igamma = factores_inclinacion_bowles(fh_kn, n_kn, phi_suelo_deg)
    else:
        ic = iq = igamma = 1.0
    return (c_kpa * nc * sc * ic + gamma1_kn_m3 * df_m * nq * sq * iq
            + 0.5 * gamma2_kn_m3 * b_m * ngamma * sgamma * igamma)


def presion_admisible(qd_kpa: float, condicion: str = "estatico") -> float:
    """Presión admisible = q_d / FS -- E.050 Art. 21: FS=3.0 en
    condición "estatico", FS=2.5 en condición "sismico" (o viento)."""
    fs = {"estatico": FS_CAPACIDAD_PORTANTE_ESTATICO,
          "sismico": FS_CAPACIDAD_PORTANTE_SISMICO}.get(condicion)
    if fs is None:
        raise GeotecniaError(f"condición «{condicion}» no reconocida -- use 'estatico' o 'sismico'.")
    return qd_kpa / fs


def verificar_distorsion_angular(asentamiento_diferencial_m: float, distancia_m: float):
    """Distorsión angular = asentamiento diferencial / distancia entre
    apoyos -- criterio de la Tabla 8 (E.050). El asentamiento
    diferencial NO lo calcula este módulo (depende del perfil
    estratigráfico real del EMS) -- se recibe ya estimado por el
    usuario. Devuelve (distorsion, nivel_de_riesgo)."""
    if distancia_m <= 0:
        raise GeotecniaError("la distancia entre apoyos debe ser positiva.")
    if asentamiento_diferencial_m < 0:
        raise GeotecniaError("el asentamiento diferencial no puede ser negativo.")
    distorsion = asentamiento_diferencial_m / distancia_m
    if distorsion <= DISTORSION_ANGULAR_SIN_AGRIETAMIENTO:
        nivel = "Seguro -- sin riesgo de agrietamiento (≤1/500)"
    elif distorsion <= DISTORSION_ANGULAR_PRIMERAS_GRIETAS:
        nivel = "Alerta -- pueden aparecer primeras grietas (1/500-1/300)"
    elif distorsion <= DISTORSION_ANGULAR_DANIO_ESTRUCTURAL:
        nivel = "Riesgo -- posible daño estructural (1/300-1/150)"
    else:
        nivel = "Crítico -- daño estructural esperado (>1/150)"
    return distorsion, nivel
