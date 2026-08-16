# -*- coding: utf-8 -*-
"""
core/bim_refuerzo.py

Diseño simplificado de refuerzo de acero (Módulo BIM, fase 4 de 4) para
el muro/losa de una estructura tipo "cáscara" (canal, alcantarilla,
sumidero -- las mismas que ya tienen metrados de concreto en
core/bim_metrados.py), bajo empuje de agua + empuje de tierra
(estático + incremento sísmico opcional), según la Norma E.060
(concreto armado) y E.030 (sismorresistente, para el empuje sísmico vía
Mononobe-Okabe).

Se evalúan DOS casos de carga y se diseña para el que gobierna (mayor
momento):
  A) "Estructura llena, sin relleno actuando": solo empuje hidrostático
     hacia afuera.
  B) "Estructura vacía, con relleno posterior": empuje de tierra
     (+ sobrecarga + sismo, si se indicó zona) hacia adentro.
Si el usuario indica que el muro NO tiene relleno posterior (canales
sin talud/relleno detrás, por ejemplo), solo se evalúa el caso A.

Enrocado (RipRap) y Defensa Ribereña son capas de ROCA, no concreto
armado -- no aplica refuerzo (RefuerzoNoAplicaError). Pontón y Puente
tampoco (ya sin metrados posibles por falta de geometría real).

Ver el docstring de core/lateral_pressures.py y
core/reinforced_concrete_e060.py para el alcance y las limitaciones
EXACTAS de cada método -- este es un cálculo PRELIMINAR de apoyo, no un
expediente estructural definitivo ni un sustituto de la revisión de un
ingeniero estructural/geotécnico colegiado.
"""
from . import bim_geometry as bg
from . import lateral_pressures as lp
from . import reinforced_concrete_e060 as rc

GAMMA_AGUA_KN_M3 = 9.81
DENSIDAD_ACERO_KG_M3 = 7850.0

_TIPOS_CONCRETO_P7 = {"Canal", "Alcantarilla", "Sumidero"}
_TIPOS_ROCA_P7 = {"Enrocado (RipRap)", "Defensa Ribereña"}


class RefuerzoNoAplicaError(Exception):
    """La estructura seleccionada no tiene un muro/losa de concreto
    real sobre el que calcular refuerzo (ej. Pontón/Puente sin
    geometría, o enrocado/defensa que son roca, no concreto armado)."""


# ======================================================================
# Altura de diseño del muro/losa -- valor de referencia autocompletado,
# AJUSTABLE por el usuario en la interfaz (mismo patrón que la
# longitud de extrusión del render 3D).
# ======================================================================
def altura_muro_por_defecto_pestana7(datos: dict):
    tipo = datos.get("tipo", "")
    if tipo == "Canal":
        y = datos.get("tirante_normal_m")
        return round(y * 1.20, 3) if y else None  # 20% de borde libre sobre el tirante, referencial
    if tipo == "Alcantarilla":
        if str(datos.get("subtipo", "")).startswith("Circular"):
            return datos.get("diametro_m")
        return datos.get("alto_m")
    if tipo == "Sumidero":
        largo_ventana, y = datos.get("L_m"), datos.get("y_m")
        if largo_ventana is None or y is None:
            return None
        _, _, _, profundidad_caja = bg.perfil_sumidero(largo_ventana, y)
        return profundidad_caja
    return None


def altura_muro_por_defecto_pestana8(estructura):
    tipo = estructura.tipo
    p = estructura.parametros
    if tipo == "alcantarilla":
        return p.get("diametro")
    if tipo == "vertedero":
        _, zs = bg.perfil_muro_nominal()
        return max(zs)
    if tipo == "orificio":
        import math
        lado = math.sqrt(max(p.get("area", 0.5), 1e-6))
        _, zs = bg.perfil_muro_nominal(alto=max(lado * 1.8, 1.5))
        return max(zs)
    return None


def _altura_agua_pestana7(datos: dict):
    tipo = datos.get("tipo", "")
    if tipo == "Canal":
        return datos.get("tirante_normal_m")
    if tipo == "Alcantarilla":
        return datos.get("tirante_m")
    if tipo == "Sumidero":
        return datos.get("y_m")
    return None


# ======================================================================
# Cálculo estructural
# ======================================================================
def calcular_refuerzo(nombre: str, altura_muro_m: float, altura_agua_m: float, espesor_muro_m: float,
                       longitud_m: float = 1.0,
                       fc_kg_cm2: float = 210.0, fy_kg_cm2: float = 4200.0, recubrimiento_cm: float = 4.0,
                       con_relleno_posterior: bool = True, gamma_suelo_kn_m3: float = 18.0,
                       phi_suelo_deg: float = 30.0, metodo_empuje: str = "Ko", sobrecarga_kn_m2: float = 0.0,
                       zona_sismica=None, diametro_barra: str = "1/2\"",
                       diametro_barra_temperatura: str = "3/8\"") -> dict:
    """Diseño de refuerzo por flexión de una franja de 1 m del muro/
    losa. Devuelve un dict con el caso gobernante, el momento de
    diseño, el acero requerido/mínimo/adoptado, la barra y
    espaciamiento sugeridos, y la verificación de corte."""
    b_cm = 100.0  # franja de diseño de 1 m de ancho
    h_cm = espesor_muro_m * 100.0
    diametro_barra_asumido_cm = next(
        (d for n, d, _ in rc.BARRAS_COMERCIALES if n == diametro_barra), 1.27)
    d_cm = h_cm - recubrimiento_cm - diametro_barra_asumido_cm / 2.0
    if d_cm <= 0:
        raise RefuerzoNoAplicaError(
            f"el espesor de muro ({espesor_muro_m:.2f} m) es insuficiente para el recubrimiento "
            f"indicado ({recubrimiento_cm:.1f} cm) -- aumente el espesor.")

    # --- Caso A: hidrostático (estructura llena, sin relleno actuando) ---
    y_agua = min(altura_agua_m, altura_muro_m)
    p_agua_kn, brazo_agua_m = lp.presion_hidrostatica_resultante(GAMMA_AGUA_KN_M3, y_agua)
    casos = [{
        "caso": "A -- estructura llena (solo empuje hidrostático)",
        "p_total_kn_m": p_agua_kn, "mu_kn_m": p_agua_kn * brazo_agua_m,
        "detalle": {"P_agua_kN/m": round(p_agua_kn, 2), "brazo_agua_m": round(brazo_agua_m, 3)},
    }]

    # --- Caso B: relleno posterior (empuje de tierra), si aplica ---
    if con_relleno_posterior:
        k = (lp.coeficiente_empuje_reposo(phi_suelo_deg) if metodo_empuje == "Ko"
             else lp.coeficiente_empuje_activo_rankine(phi_suelo_deg))
        p_suelo_kn, brazo_suelo_m = lp.presion_suelo_resultante(gamma_suelo_kn_m3, altura_muro_m, k)
        p_total_b, mu_b = p_suelo_kn, p_suelo_kn * brazo_suelo_m
        detalle_b = {"K_" + metodo_empuje: round(k, 3), "P_suelo_kN/m": round(p_suelo_kn, 2),
                     "brazo_suelo_m": round(brazo_suelo_m, 3)}
        if sobrecarga_kn_m2:
            p_sc_kn, brazo_sc_m = lp.presion_sobrecarga_resultante(k, sobrecarga_kn_m2, altura_muro_m)
            p_total_b += p_sc_kn
            mu_b += p_sc_kn * brazo_sc_m
            detalle_b["P_sobrecarga_kN/m"] = round(p_sc_kn, 2)
        if zona_sismica:
            delta_p_kn, brazo_sismo_m, kh = lp.incremento_sismico_empuje(
                gamma_suelo_kn_m3, altura_muro_m, phi_suelo_deg, zona_sismica)
            p_total_b += delta_p_kn
            mu_b += delta_p_kn * brazo_sismo_m
            detalle_b.update({"kh": round(kh, 3), "delta_P_sismico_kN/m": round(delta_p_kn, 2),
                              "zona_sismica": zona_sismica})
        casos.append({"caso": "B -- estructura vacía (empuje de tierra + relleno)",
                       "p_total_kn_m": p_total_b, "mu_kn_m": mu_b, "detalle": detalle_b})

    gobernante = max(casos, key=lambda c: c["mu_kn_m"])
    # kN·m/m -> kgf·cm/m  (1 kN = 1000/9.81 kgf ; 1 m = 100 cm)
    mu_kg_cm = gobernante["mu_kn_m"] * (1000.0 / 9.81) * 100.0
    vu_kg = gobernante["p_total_kn_m"] * (1000.0 / 9.81)

    as_flexion = rc.as_requerido_flexion(mu_kg_cm, b_cm, d_cm, fc_kg_cm2, fy_kg_cm2)
    if as_flexion is None:
        raise RefuerzoNoAplicaError(
            "el momento de diseño excede la capacidad de la sección con el espesor de muro "
            "indicado -- aumente el espesor de muro/losa y vuelva a calcular.")
    as_min_temp = rc.as_minimo_temperatura(b_cm, h_cm, fy_kg_cm2)
    as_min_flex = rc.as_minimo_flexion(b_cm, d_cm, fc_kg_cm2, fy_kg_cm2)
    # Dos partidas de acero, con su propio diámetro/espaciamiento --
    # PRINCIPAL (dirección de flexión, barras "verticales" según el
    # modelo de la Fig. en core/bim_geometry.py::desplazar_contorno_normal,
    # espaciadas a lo largo de la longitud L) y TEMPERATURA/RETRACCIÓN
    # (dirección perpendicular, corridas a lo largo de L, espaciadas en
    # altura) -- así el metrado ya no mezcla ambas en una sola cifra.
    as_principal = max(as_flexion, as_min_flex)
    espaciamiento_principal_cm, barra_principal = rc.espaciamiento_sugerido(as_principal, diametro_barra)
    espaciamiento_temperatura_cm, barra_temperatura = rc.espaciamiento_sugerido(
        as_min_temp, diametro_barra_temperatura)
    as_adoptado = max(as_principal, as_min_temp)  # para compatibilidad -- el mayor de ambas partidas
    phi_vc_kg, corte_cumple = rc.verificar_corte(vu_kg, b_cm, d_cm, fc_kg_cm2)

    # Peso de acero: PRINCIPAL en ambas caras -- la carga se invierte
    # entre el caso A (agua, empuja hacia afuera) y el caso B (tierra,
    # empuja hacia adentro), así que ambas caras necesitan refuerzo en
    # la práctica -- MÁS el acero de TEMPERATURA en la dirección
    # perpendicular, también en ambas caras. Es un metrado preliminar
    # de la cuantía total, no un despiece de planos.
    area_muro_m2 = altura_muro_m * longitud_m
    peso_principal_kg = 2 * (as_principal / 10000.0) * area_muro_m2 * DENSIDAD_ACERO_KG_M3
    peso_temperatura_kg = 2 * (as_min_temp / 10000.0) * area_muro_m2 * DENSIDAD_ACERO_KG_M3
    peso_acero_total_kg = peso_principal_kg + peso_temperatura_kg

    return {
        "nombre": nombre, "altura_muro_m": round(altura_muro_m, 3), "altura_agua_m": round(y_agua, 3),
        "longitud_m": round(longitud_m, 2),
        "espesor_muro_m": espesor_muro_m, "recubrimiento_cm": recubrimiento_cm,
        "fc_kg_cm2": fc_kg_cm2, "fy_kg_cm2": fy_kg_cm2, "peralte_efectivo_d_cm": round(d_cm, 2),
        "con_relleno_posterior": con_relleno_posterior,
        "caso_gobernante": gobernante["caso"], "casos_evaluados": casos,
        "momento_diseno_kN_m_por_m": round(gobernante["mu_kn_m"], 3),
        "cortante_diseno_kN_por_m": round(gobernante["p_total_kn_m"], 3),
        "as_requerido_flexion_cm2_m": round(as_flexion, 3),
        "as_minimo_temperatura_cm2_m": round(as_min_temp, 3),
        "as_minimo_flexion_cm2_m": round(as_min_flex, 3),
        "as_adoptado_cm2_m": round(as_adoptado, 3),
        # Partida PRINCIPAL (flexión) -- alias barra_sugerida/espaciamiento_sugerido_cm se
        # mantienen por compatibilidad con la tabla de metrados (ver plugin_dialog.py).
        "as_principal_cm2_m": round(as_principal, 3),
        "barra_principal": barra_principal, "espaciamiento_principal_cm": espaciamiento_principal_cm,
        "barra_sugerida": barra_principal, "espaciamiento_sugerido_cm": espaciamiento_principal_cm,
        # Partida de TEMPERATURA/RETRACCIÓN (perpendicular a la principal)
        "as_temperatura_cm2_m": round(as_min_temp, 3),
        "barra_temperatura": barra_temperatura, "espaciamiento_temperatura_cm": espaciamiento_temperatura_cm,
        "phi_Vc_kg_por_m": round(phi_vc_kg, 1), "Vu_kg_por_m": round(vu_kg, 1),
        "cortante_cumple": corte_cumple,
        "peso_acero_principal_kg": round(peso_principal_kg, 1),
        "peso_acero_temperatura_kg": round(peso_temperatura_kg, 1),
        "peso_acero_total_kg": round(peso_acero_total_kg, 1),
        "metodo": ("Diseño por resistencia (E.060) + empuje de tierra Ko/Ka y, si se indicó zona "
                   "sísmica, incremento dinámico Mononobe-Okabe (E.030) -- cálculo PRELIMINAR, ver "
                   "limitaciones exactas en core/lateral_pressures.py y "
                   "core/reinforced_concrete_e060.py. No reemplaza la revisión de un ingeniero "
                   "estructural/geotécnico colegiado."),
    }


# ======================================================================
# Geometría 3D de las barras -- usada por el render (ui/bim_canvas.py)
# Y por la exportación IFC (core/bim_ifc.py), para que ambas muestren
# EXACTAMENTE la misma disposición de refuerzo.
# ======================================================================
def geometria_barras_refuerzo(xs, zs, cerrado: bool, longitud_m: float, espesor_muro_m: float,
                               espaciamiento_principal_cm: float, espaciamiento_temperatura_cm: float,
                               n_longitudinales: int = 12, diametro_barra: str = "1/2\"",
                               diametro_barra_temperatura: str = "3/8\"") -> dict:
    """Posiciones 3D (x, y, z) de las barras de refuerzo, ubicadas a
    media altura del espesor del muro (entre la cara mojada y la cara
    exterior):
      - "costillas": el contorno del muro (xs, zs) repetido cada
        `espaciamiento_principal_cm` a lo largo de Y -- representa las
        barras PRINCIPALES (de flexión).
      - "longitudinales": líneas rectas de Y=0 a Y=longitud_m, en unos
        `n_longitudinales` puntos representativos del contorno --
        representan las barras de TEMPERATURA/retracción.
    Incluye también el diámetro real (cm) de cada partida -- usado por
    la exportación IFC (core/bim_ifc.py) para dar a cada barra su
    espesor real (IfcSweptDiskSolid), no solo su trayectoria.
    Es una disposición esquemática (no un despiece de planos real: no
    considera empalmes, ganchos, ni el detallado de esquinas)."""
    xs_mid, zs_mid = bg.desplazar_contorno_normal(xs, zs, espesor_muro_m / 2.0)
    n = len(xs_mid)

    paso_principal_m = max(espaciamiento_principal_cm / 100.0, 0.05)
    costillas = []
    y = 0.0
    while True:
        y_actual = min(y, longitud_m)
        costillas.append([(xs_mid[i], y_actual, zs_mid[i]) for i in range(n)])
        if y_actual >= longitud_m:
            break
        y += paso_principal_m

    paso_muestra = max(1, n // max(n_longitudinales, 1))
    indices = list(range(0, n, paso_muestra))
    longitudinales = [
        [(xs_mid[i], 0.0, zs_mid[i]), (xs_mid[i], longitud_m, zs_mid[i])] for i in indices
    ]

    diametro_principal_cm = next(
        (d for n_, d, _ in rc.BARRAS_COMERCIALES if n_ == diametro_barra), 1.27)
    diametro_temperatura_cm = next(
        (d for n_, d, _ in rc.BARRAS_COMERCIALES if n_ == diametro_barra_temperatura), 0.95)

    return {"costillas": costillas, "longitudinales": longitudinales, "cerrado": cerrado,
            "espaciamiento_temperatura_cm": espaciamiento_temperatura_cm,
            "barra_principal": diametro_barra, "diametro_principal_cm": diametro_principal_cm,
            "barra_temperatura": diametro_barra_temperatura, "diametro_temperatura_cm": diametro_temperatura_cm}


# ======================================================================
# Despachadores por fuente (mismo patrón que core/bim_metrados.py)
# ======================================================================
def refuerzo_desde_pestana7(nombre: str, datos: dict, espesor_muro_m: float, altura_muro_m=None, **kwargs) -> dict:
    tipo = datos.get("tipo", "")
    if tipo in _TIPOS_ROCA_P7:
        raise RefuerzoNoAplicaError(
            f"«{tipo}» es una capa de roca (enrocado de protección), no concreto armado -- no "
            f"aplica cálculo de refuerzo de acero.")
    if tipo not in _TIPOS_CONCRETO_P7:
        raise RefuerzoNoAplicaError(
            f"«{tipo}» no tiene una geometría de material de concreto sobre la que calcular "
            f"refuerzo (solo verifica borde libre en Pestaña 7).")
    if altura_muro_m is None:
        altura_muro_m = altura_muro_por_defecto_pestana7(datos)
        if altura_muro_m is None:
            raise bg.GeometriaNoDisponibleError(
                "no se pudo determinar la altura del muro/losa automáticamente para esta "
                "estructura -- indíquela manualmente.")
    y_agua = _altura_agua_pestana7(datos) or altura_muro_m
    resultado = calcular_refuerzo(nombre, altura_muro_m, y_agua, espesor_muro_m, **kwargs)
    resultado["tipo_estructura"] = tipo
    return resultado


def refuerzo_desde_pestana8(estructura, espesor_muro_m: float, altura_muro_m=None, **kwargs) -> dict:
    tipo = estructura.tipo
    if tipo not in ("alcantarilla", "vertedero", "orificio"):
        raise RefuerzoNoAplicaError(f"tipo de estructura de Pestaña 8 no reconocido: «{tipo}»")
    if altura_muro_m is None:
        altura_muro_m = altura_muro_por_defecto_pestana8(estructura)
        if altura_muro_m is None:
            raise bg.GeometriaNoDisponibleError(
                "no se pudo determinar la altura del muro/losa automáticamente -- indíquela manualmente.")
    # Pestaña 8 no registra tirante de agua -- se asume la estructura llena (conservador para el
    # caso A; el caso B, si aplica, no depende de este valor).
    resultado = calcular_refuerzo(estructura.nombre, altura_muro_m, altura_muro_m, espesor_muro_m, **kwargs)
    resultado["tipo_estructura"] = f"{tipo} (Pestaña 8, esquemático)"
    return resultado
