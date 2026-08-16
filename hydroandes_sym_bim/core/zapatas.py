# -*- coding: utf-8 -*-
"""
core/zapatas.py

Diseño de una ZAPATA AISLADA de columna bajo carga axial (caso más
común y el que se verifica en este módulo) -- geotécnico por la Norma
E.050 (dimensionamiento en planta, reutilizando
core/geotecnia_e050.py) y estructural por la Norma E.060 Cap. 15
(peralte y acero, reutilizando core/reinforced_concrete_e060.py), más
las exigencias de conexión sísmica de la Norma E.030.

MARCO NORMATIVO (para que quede explícito qué gobierna cada parte):
  - E.050 (Suelos y Cimentaciones): capacidad portante, presión
    admisible -- YA cubierto por core/geotecnia_e050.py, este módulo
    solo lo reutiliza para el área en planta.
  - E.060 (Concreto Armado, Cap. 15): diseño estructural. DOS cálculos
    con cargas DISTINTAS -- no confundirlos:
      1. Dimensionamiento en PLANTA (B×L) -> cargas de SERVICIO (sin
         amplificar) contra la presión admisible (15.2.2).
      2. Peralte y acero -> diseño por RESISTENCIA, con la carga
         amplificada Pu y la reacción NETA amplificada del suelo
         (q_neta = Pu / (B·L)) (15.2.3).
    Verificaciones: momento en la cara de la columna (15.4), cortante
    en una dirección (viga ancha, sección crítica a "d" de la cara,
    15.5.2), punzonamiento (cortante en dos direcciones, perímetro
    crítico a "d/2" de la cara, 15.5.2 + ACI 318 -- fórmula de 3
    condiciones, se toma la menor), peralte mínimo sobre el refuerzo
    inferior (150 mm sobre suelo, 300 mm sobre pilotes, 15.7), y
    transferencia de fuerzas columna-zapata por aplastamiento y
    varillas de anclaje/dowels (15.9).
  - E.030 (Diseño Sismorresistente, Cimentaciones): en zonas sísmicas
    2 y 3, con perfil de suelo S3 o S4, zapatas aisladas y cajones
    requieren elementos de conexión (vigas de cimentación)
    dimensionados para una fuerza horizontal mínima del 10% de la
    carga vertical; en pilotes, armadura en tracción ≥15% de la carga
    vertical.

ALCANCE: zapata aislada CUADRADA/RECTANGULAR bajo carga AXIAL
(columna centrada, sin momento significativo) -- el caso más común y
el que se puede verificar con un ejemplo de mano de forma inequívoca.
NO cubre: zapatas con excentricidad/momento importante (combinadas,
medianeras), zapatas conectadas, plateas de cimentación, ni pilotes.
Cálculo PRELIMINAR de apoyo -- no reemplaza el criterio de un
ingeniero estructural/geotécnico colegiado.
"""
import math

from . import reinforced_concrete_e060 as rc

# NOTA de integración: la presión admisible `q_adm_kpa` que recibe este
# módulo se obtiene de core/geotecnia_e050.py (capacidad_portante_ultima +
# presion_admisible) -- normalmente calculada en la Pestaña 8b y pasada
# aquí como dato de entrada, igual que hace core/estabilidad_muros.py.

PHI_APLASTAMIENTO = 0.65  # E.060 -- φ para aplastamiento (bearing) en la base de la columna
PERALTE_MINIMO_SUELO_CM = 15.0   # 150 mm (E.060 15.7, zapata apoyada directamente sobre el suelo)
PERALTE_MINIMO_PILOTES_CM = 30.0  # 300 mm (E.060 15.7, zapata sobre cabezas de pilotes)
CUANTIA_MINIMA_DOWELS = 0.005    # 0.5% del área de la columna (E.060 15.8.2.1), SIEMPRE, aunque
                                  # el aplastamiento no lo exija por cálculo


class ZapataError(Exception):
    """Datos insuficientes o geometría/carga inconsistente para
    diseñar la zapata -- el mensaje explica exactamente qué falla."""


def dimensionar_planta(carga_servicio_kn: float, q_adm_kpa: float,
                        factor_peso_propio: float = 1.10) -> float:
    """Área REQUERIDA en planta (m²) -- E.060 15.2.2: con cargas de
    SERVICIO (sin amplificar), no las de resistencia. `factor_peso_propio`
    (1.10 por defecto) aproxima el peso propio de la zapata + relleno
    sobre ella (~10% adicional) sin iterar -- ajústelo si su caso lo
    amerita."""
    if carga_servicio_kn <= 0:
        raise ZapataError("la carga de servicio debe ser positiva.")
    if q_adm_kpa <= 0:
        raise ZapataError("la presión admisible debe ser positiva.")
    return (carga_servicio_kn * factor_peso_propio) / q_adm_kpa


def peralte_efectivo_cm(h_zapata_cm: float, recubrimiento_cm: float, diametro_barra_cm: float) -> float:
    """d = h - recubrimiento - Ø/2 (peralte efectivo, hasta el centroide
    del refuerzo inferior)."""
    d = h_zapata_cm - recubrimiento_cm - diametro_barra_cm / 2.0
    if d <= 0:
        raise ZapataError(
            f"el peralte de la zapata ({h_zapata_cm:.1f} cm) es insuficiente para el "
            f"recubrimiento ({recubrimiento_cm:.1f} cm) indicado -- aumente el peralte.")
    return d


def verificar_cortante_unidireccional(q_neta_kg_cm2: float, b_zapata_cm: float, l_zapata_cm: float,
                                       b_columna_cm: float, d_cm: float, fc_kg_cm2: float):
    """Cortante en UNA dirección (viga ancha) -- sección crítica a "d"
    de la cara de la columna, en la dirección del ancho `b_zapata_cm`
    (perpendicular a `l_zapata_cm`, que es el ancho de la franja que
    resiste el cortante). Devuelve (Vu_kg, φVc_kg, cumple)."""
    volado_cm = (b_zapata_cm - b_columna_cm) / 2.0
    x_critico_cm = volado_cm - d_cm
    if x_critico_cm <= 0:
        return 0.0, None, True  # el peralte ya cubre todo el volado -- sin sección crítica que evaluar
    vu_kg = q_neta_kg_cm2 * l_zapata_cm * x_critico_cm
    phi_vc_kg, cumple = rc.verificar_corte(vu_kg, l_zapata_cm, d_cm, fc_kg_cm2)
    return vu_kg, phi_vc_kg, cumple


def verificar_punzonamiento(pu_kg: float, q_neta_kg_cm2: float, b_columna_cm: float, h_columna_cm: float,
                             d_cm: float, fc_kg_cm2: float, tipo_columna: str = "interior"):
    """Punzonamiento (cortante en DOS direcciones) -- perímetro crítico
    bo a "d/2" de la cara de la columna. Vc = min(3 condiciones de
    ACI 318/E.060) × bo × d:
      (1) 0.53·(1+2/βc)·√f'c  -- βc = lado mayor/lado menor de la columna
      (2) 0.27·(αs·d/bo + 2)·√f'c  -- αs: 40 interior, 30 borde, 20 esquina
      (3) 1.06·√f'c  -- límite superior
    Devuelve (Vu_kg, φVc_kg, cumple, bo_cm)."""
    bo_cm = 2.0 * (b_columna_cm + d_cm) + 2.0 * (h_columna_cm + d_cm)
    area_critica_cm2 = (b_columna_cm + d_cm) * (h_columna_cm + d_cm)
    vu_kg = pu_kg - q_neta_kg_cm2 * area_critica_cm2
    beta_c = max(b_columna_cm, h_columna_cm) / min(b_columna_cm, h_columna_cm)
    alpha_s = {"interior": 40, "borde": 30, "esquina": 20}.get(tipo_columna)
    if alpha_s is None:
        raise ZapataError(f"tipo de columna «{tipo_columna}» no reconocido -- use 'interior', 'borde' o 'esquina'.")
    raiz_fc = math.sqrt(fc_kg_cm2)
    vc1 = 0.53 * (1.0 + 2.0 / beta_c) * raiz_fc
    vc2 = 0.27 * (alpha_s * d_cm / bo_cm + 2.0) * raiz_fc
    vc3 = 1.06 * raiz_fc
    vc_kg_cm2 = min(vc1, vc2, vc3)
    phi_vc_kg = rc.PHI_CORTE * vc_kg_cm2 * bo_cm * d_cm
    return vu_kg, phi_vc_kg, vu_kg <= phi_vc_kg, bo_cm


def diseno_por_flexion_zapata(q_neta_kg_cm2: float, l_zapata_cm: float, b_zapata_cm: float,
                               b_columna_cm: float, h_zapata_cm: float, d_cm: float,
                               fc_kg_cm2: float, fy_kg_cm2: float):
    """Momento último en la cara de la columna (volado en voladizo,
    E.060 15.4) sobre la franja de ancho `l_zapata_cm`, y el acero
    requerido/mínimo resultante. `b_zapata_cm`/`b_columna_cm`: ancho de
    la zapata y de la columna EN LA DIRECCIÓN DEL VOLADO que se está
    verificando (llame dos veces, una por dirección, si la zapata es
    rectangular con columna rectangular)."""
    volado_cm = (b_zapata_cm - b_columna_cm) / 2.0
    if volado_cm <= 0:
        raise ZapataError("el volado de la zapata resultó nulo o negativo -- revise B vs. la columna.")
    mu_kg_cm = q_neta_kg_cm2 * l_zapata_cm * volado_cm ** 2 / 2.0
    as_flexion = rc.as_requerido_flexion(mu_kg_cm, l_zapata_cm, d_cm, fc_kg_cm2, fy_kg_cm2)
    if as_flexion is None:
        raise ZapataError(
            "el momento en la cara de la columna excede la capacidad de la sección con el "
            "peralte indicado -- aumente el peralte de la zapata.")
    as_min = rc.as_minimo_temperatura(l_zapata_cm, h_zapata_cm, fy_kg_cm2)
    as_adoptado = max(as_flexion, as_min)
    return {"volado_cm": volado_cm, "mu_kg_cm": mu_kg_cm, "as_flexion_cm2": as_flexion,
            "as_minimo_cm2": as_min, "as_adoptado_cm2": as_adoptado}


def verificar_transferencia_fuerzas(pu_kg: float, b_columna_cm: float, h_columna_cm: float,
                                     fc_kg_cm2: float, fy_kg_cm2: float, factor_a2_a1: float = 1.0):
    """Transferencia de fuerzas columna-zapata por APLASTAMIENTO
    (E.060 15.9) -- φPnb = φ·0.85·f'c·A1·min(√(A2/A1), 2.0). Si
    Pu excede φPnb, el exceso se transfiere con varillas de anclaje
    (dowels): As_dowels = exceso/(φ·fy). SIEMPRE se exige, además, un
    mínimo de 0.5% del área de la columna (15.8.2.1), aunque el
    aplastamiento por sí solo no lo requiera."""
    area_columna_cm2 = b_columna_cm * h_columna_cm
    factor_incremento = min(math.sqrt(max(factor_a2_a1, 1.0)), 2.0)
    phi_pnb_kg = PHI_APLASTAMIENTO * 0.85 * fc_kg_cm2 * area_columna_cm2 * factor_incremento
    excede_aplastamiento = pu_kg > phi_pnb_kg
    exceso_kg = max(pu_kg - phi_pnb_kg, 0.0)
    as_dowels_transferencia_cm2 = exceso_kg / (PHI_APLASTAMIENTO * fy_kg_cm2) if exceso_kg > 0 else 0.0
    as_dowels_min_cm2 = CUANTIA_MINIMA_DOWELS * area_columna_cm2
    as_dowels_cm2 = max(as_dowels_transferencia_cm2, as_dowels_min_cm2)
    return {"phi_pnb_kg": phi_pnb_kg, "excede_aplastamiento": excede_aplastamiento,
            "as_dowels_transferencia_cm2": as_dowels_transferencia_cm2,
            "as_dowels_minimo_cm2": as_dowels_min_cm2, "as_dowels_cm2": as_dowels_cm2}


def verificar_peralte_minimo(h_zapata_cm: float, sobre_pilotes: bool = False):
    """Peralte mínimo sobre el refuerzo inferior (E.060 15.7): 150 mm
    sobre suelo, 300 mm sobre cabezas de pilotes. Devuelve (cumple,
    minimo_cm)."""
    minimo_cm = PERALTE_MINIMO_PILOTES_CM if sobre_pilotes else PERALTE_MINIMO_SUELO_CM
    return h_zapata_cm >= minimo_cm, minimo_cm


def fuerza_minima_conexion_e030(pu_kn: float, zona_sismica: str, perfil_suelo: str,
                                 tipo_cimentacion: str = "zapata_aislada"):
    """E.030 (Cimentaciones) -- en zonas sísmicas 2 y 3, CON perfil de
    suelo S3 o S4, las zapatas aisladas/cajones necesitan una fuerza
    horizontal mínima de diseño del 10% de la carga vertical para sus
    elementos de conexión (vigas de cimentación); en pilotes, armadura
    en tracción ≥15% de la carga vertical. Devuelve None si no aplica
    (zona/perfil fuera de esa condición) -- NO es un error, es que la
    norma no exige el elemento de conexión en ese caso."""
    if zona_sismica not in ("Zona 2", "Zona 3") or perfil_suelo not in ("S3", "S4"):
        return None
    porcentaje = 0.15 if tipo_cimentacion == "pilotes" else 0.10
    return pu_kn * porcentaje


def disenar_zapata_aislada(
        pu_kn: float, carga_servicio_kn: float, b_columna_m: float, h_columna_m: float,
        q_adm_kpa: float, h_zapata_m: float, fc_kg_cm2: float = 210.0, fy_kg_cm2: float = 4200.0,
        recubrimiento_cm: float = 7.5, diametro_barra_pulg: str = "5/8\"",
        tipo_columna: str = "interior", sobre_pilotes: bool = False,
        factor_peso_propio: float = 1.10, redondear_planta_cm: float = 5.0) -> dict:
    """Diseño COMPLETO de una zapata aislada cuadrada bajo carga axial
    -- ver docstring del módulo para el alcance y la normativa exacta
    de cada verificación. `pu_kn`/`carga_servicio_kn`: carga AMPLIFICADA
    y de SERVICIO de la columna, respectivamente (ambas necesarias --
    ver por qué en el docstring del módulo). `h_zapata_m`: peralte YA
    asumido por el usuario (este módulo no lo itera automáticamente,
    solo lo verifica -- ajústelo y recalcule si alguna verificación no
    cumple)."""
    if pu_kn <= 0 or carga_servicio_kn <= 0:
        raise ZapataError("Pu y la carga de servicio deben ser positivas.")
    if b_columna_m <= 0 or h_columna_m <= 0:
        raise ZapataError("las dimensiones de la columna deben ser positivas.")

    area_req_m2 = dimensionar_planta(carga_servicio_kn, q_adm_kpa, factor_peso_propio)
    lado_m = math.sqrt(area_req_m2)
    # redondeo hacia arriba al múltiplo indicado (5 cm por defecto), práctica usual en obra
    paso_m = redondear_planta_cm / 100.0
    lado_adoptado_m = math.ceil(lado_m / paso_m) * paso_m
    b_zapata_m = l_zapata_m = lado_adoptado_m

    diametro_barra_cm = next((d for n, d, _ in rc.BARRAS_COMERCIALES if n == diametro_barra_pulg), 1.59)
    h_zapata_cm = h_zapata_m * 100.0
    d_cm = peralte_efectivo_cm(h_zapata_cm, recubrimiento_cm, diametro_barra_cm)

    b_columna_cm, h_columna_cm = b_columna_m * 100.0, h_columna_m * 100.0
    b_zapata_cm = b_zapata_m * 100.0
    l_zapata_cm = l_zapata_m * 100.0

    kn_a_kg = 1000.0 / 9.81  # 1 kN = 1000/9.81 kgf
    pu_kg = pu_kn * kn_a_kg
    q_neta_kg_cm2 = pu_kg / (b_zapata_cm * l_zapata_cm)

    vu_1d, phi_vc_1d, cumple_1d = verificar_cortante_unidireccional(
        q_neta_kg_cm2, b_zapata_cm, l_zapata_cm, b_columna_cm, d_cm, fc_kg_cm2)
    vu_punz, phi_vc_punz, cumple_punz, bo_cm = verificar_punzonamiento(
        pu_kg, q_neta_kg_cm2, b_columna_cm, h_columna_cm, d_cm, fc_kg_cm2, tipo_columna)
    flexion = diseno_por_flexion_zapata(
        q_neta_kg_cm2, l_zapata_cm, b_zapata_cm, b_columna_cm, h_zapata_cm, d_cm, fc_kg_cm2, fy_kg_cm2)
    espaciamiento_cm, barra_sugerida = rc.espaciamiento_sugerido(
        flexion["as_adoptado_cm2"] / (l_zapata_cm / 100.0), diametro_barra_pulg)
    transferencia = verificar_transferencia_fuerzas(pu_kg, b_columna_cm, h_columna_cm, fc_kg_cm2, fy_kg_cm2)
    cumple_peralte, peralte_minimo_cm = verificar_peralte_minimo(h_zapata_cm, sobre_pilotes)

    return {
        "area_requerida_m2": round(area_req_m2, 3),
        "b_zapata_m": round(b_zapata_m, 2), "l_zapata_m": round(l_zapata_m, 2),
        "peralte_efectivo_cm": round(d_cm, 2), "peralte_zapata_cm": h_zapata_cm,
        "cumple_peralte_minimo": cumple_peralte, "peralte_minimo_cm": peralte_minimo_cm,
        "q_neta_amplificada_kg_cm2": round(q_neta_kg_cm2, 4),
        "cortante_1d": {"vu_kg": round(vu_1d, 1), "phi_vc_kg": round(phi_vc_1d, 1) if phi_vc_1d else None,
                        "cumple": cumple_1d},
        "punzonamiento": {"vu_kg": round(vu_punz, 1), "phi_vc_kg": round(phi_vc_punz, 1),
                          "cumple": cumple_punz, "bo_cm": round(bo_cm, 2)},
        "flexion": {k: round(v, 3) for k, v in flexion.items()},
        "espaciamiento_sugerido_cm": espaciamiento_cm, "barra_sugerida": barra_sugerida,
        "transferencia_fuerzas": {k: round(v, 2) if isinstance(v, float) else v
                                   for k, v in transferencia.items()},
        "cumple_todo": (cumple_1d and cumple_punz and cumple_peralte),
        "metodo": ("Dimensionamiento en planta con cargas de servicio (E.060 15.2.2) contra la "
                   "presión admisible (E.050 Art. 21); peralte y acero por resistencia con la "
                   "reacción neta amplificada del suelo (E.060 15.2.3/15.4/15.5/15.7/15.9). "
                   "Cálculo PRELIMINAR de una zapata aislada cuadrada bajo carga axial -- no "
                   "cubre excentricidad/momento significativo, zapatas conectadas ni plateas. No "
                   "reemplaza el criterio de un ingeniero estructural/geotécnico colegiado."),
    }
