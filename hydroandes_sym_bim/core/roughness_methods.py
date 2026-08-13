# -*- coding: utf-8 -*-
"""
core/roughness_methods.py

Métodos para OBTENER el coeficiente de rugosidad de Manning n, para el
método de Kerby (Pestaña 4) y para la Sección-Pendiente / verificación
cruzada de la Pestaña 6, en vez de dejarlo como un único valor manual.

Cinco familias, la clasificación estándar en hidráulica fluvial:

  1. MÉTODOS GRANULOMÉTRICOS -- relacionan n con el tamaño del sedimento
     del lecho (d50/d84/d90, de un tamizado o conteo Wolman). Válidos
     para cauces aluviales de grava/arena SIN formas de fondo
     importantes (dunas, rizos): Strickler (1923), Limerinos (1970),
     Meyer-Peter & Müller, Bray (1979).

  2. MÉTODO ADITIVO DE COWAN (1956) -- para cauces naturales complejos,
     ajusta un n base con factores correctivos de irregularidad,
     variación de sección, obstrucciones, vegetación y meandros. No
     necesita granulometría, solo inspección visual del tramo (Chow,
     1959, "Open-Channel Hydraulics", Tabla 5-6).

  3. MÉTODOS LOGARÍTMICOS TEÓRICOS -- de la ecuación de Keulegan para
     flujo turbulento rugoso, relacionando n con la altura de aspereza
     de Nikuradse ks. Es la base de los modelos 2D tipo TELEMAC/Iber.

  4. PONDERACIÓN EN SECCIONES COMPUESTAS -- cuando la rugosidad cambia a
     lo largo de la sección (cauce principal + llanura de inundación con
     vegetación distinta), se subdivide la sección y se integra un n
     equivalente: Horton-Einstein (velocidad media igual en todas las
     subsecciones) y Lotter (caudal total = suma de caudales parciales).

  5. CALIBRACIÓN INVERSA Y TELEDETECCIÓN -- a partir de marcas de agua
     máximas o series limnimétricas con caudal conocido, ajustando n en
     un modelo hidráulico hasta minimizar el error de la lámina de agua;
     o clasificación NDVI/satélite → uso de suelo → n espacialmente
     variable. NO se implementa como cálculo aquí: la primera exige un
     modelo hidráulico ya corrido con datos de campo (flujo de trabajo,
     no una fórmula), y la segunda un ráster de cobertura ya clasificado
     e importado, que es un insumo de otra pestaña (Uso de Suelo, si se
     activa CN automático) -- no una ecuación que "calcular" aquí
     inventaría un resultado sin ese insumo real.
"""
import math
from typing import List, Tuple


class RoughnessError(Exception):
    pass


G = 9.81


# ======================================================================
# 1. MÉTODOS GRANULOMÉTRICOS
# ======================================================================
def n_strickler(d50_m: float) -> dict:
    """Strickler (1923): n = d50^(1/6) / 21.1, d50 en metros. La más
    extendida para lechos de grava/material granular uniforme sin
    formas de fondo significativas."""
    if d50_m <= 0:
        raise RoughnessError("d50 debe ser mayor que 0.")
    n = (d50_m ** (1.0 / 6.0)) / 21.1
    return {"metodo": "Strickler (1923)", "n": round(n, 4), "d50_m": d50_m}


def n_limerinos(radio_hidraulico_m: float, d84_m: float) -> dict:
    """
    Limerinos (1970): n = 0.0926·Rh^(1/6) / [1.16 + 2.0·log10(Rh/d84)].
    Muy precisa para ríos de montaña / lechos de grava gruesa: es la
    única de las granulométricas que incorpora el radio hidráulico Rh,
    no solo el tamaño del sedimento.
    """
    if radio_hidraulico_m <= 0:
        raise RoughnessError("El radio hidráulico debe ser mayor que 0.")
    if d84_m <= 0:
        raise RoughnessError("d84 debe ser mayor que 0.")
    razon = radio_hidraulico_m / d84_m
    if razon <= 0:
        raise RoughnessError("Rh/d84 debe ser mayor que 0.")
    denominador = 1.16 + 2.0 * math.log10(razon)
    if denominador <= 0:
        raise RoughnessError(
            "Rh/d84 demasiado pequeño: el denominador de Limerinos se vuelve negativo o nulo "
            "(fórmula no válida en este rango; verifique las unidades de Rh y d84)."
        )
    n = (0.0926 * radio_hidraulico_m ** (1.0 / 6.0)) / denominador
    return {"metodo": "Limerinos (1970)", "n": round(n, 4),
            "radio_hidraulico_m": radio_hidraulico_m, "d84_m": d84_m, "Rh_d84": round(razon, 2)}


def n_meyer_peter_muller(d90_m: float) -> dict:
    """Meyer-Peter & Müller: n = d90^(1/6) / 26, d90 en metros."""
    if d90_m <= 0:
        raise RoughnessError("d90 debe ser mayor que 0.")
    n = (d90_m ** (1.0 / 6.0)) / 26.0
    return {"metodo": "Meyer-Peter & Müller", "n": round(n, 4), "d90_m": d90_m}


def n_bray(d50_m: float) -> dict:
    """
    Bray (1979): n = 0.0495 · d50^0.16.

    *** VERIFICAR UNIDADES ANTES DE UN DISEÑO DEFINITIVO *** el
    coeficiente 0.0495 depende de en qué unidad se exprese d50 según la
    fuente consultada (hay variantes con d50 en mm en otras
    publicaciones); aquí se aplica tal como se especificó, con d50 en
    METROS, consistente con las demás fórmulas granulométricas de este
    módulo. Contraste el resultado contra Strickler/Limerinos para el
    mismo lecho antes de adoptarlo.
    """
    if d50_m <= 0:
        raise RoughnessError("d50 debe ser mayor que 0.")
    n = 0.0495 * d50_m ** 0.16
    return {"metodo": "Bray (1979)", "n": round(n, 4), "d50_m": d50_m,
            "nota": "Verifique la unidad de d50 contra la fuente original antes de un diseño definitivo."}


def comparar_metodos_granulometricos(d50_m: float = None, d84_m: float = None,
                                      d90_m: float = None,
                                      radio_hidraulico_m: float = None) -> dict:
    """Calcula todos los métodos granulométricos para los que haya datos
    suficientes, y avisa cuáles se omitieron por falta de dato."""
    resultados, omitidos = {}, []
    if d50_m:
        resultados["strickler"] = n_strickler(d50_m)
        resultados["bray"] = n_bray(d50_m)
    else:
        omitidos.append("Strickler y Bray (requieren d50)")
    if radio_hidraulico_m and d84_m:
        resultados["limerinos"] = n_limerinos(radio_hidraulico_m, d84_m)
    else:
        omitidos.append("Limerinos (requiere Rh y d84)")
    if d90_m:
        resultados["meyer_peter_muller"] = n_meyer_peter_muller(d90_m)
    else:
        omitidos.append("Meyer-Peter & Müller (requiere d90)")
    if not resultados:
        raise RoughnessError("No hay datos suficientes para calcular ningún método granulométrico.")
    return {"resultados": resultados, "omitidos": omitidos}


# ======================================================================
# 2. MÉTODO ADITIVO DE COWAN (1956)
# ======================================================================
# Rangos típicos de Chow (1959), Tabla 5-6 -- valores ORIENTATIVOS,
# punto de partida editable por el usuario según inspección del tramo.
COWAN_N0_MATERIAL_BASE = {
    "Tierra": (0.020, 0.025),
    "Corte en roca": (0.025, 0.035),
    "Grava fina": (0.024, 0.028),
    "Grava gruesa": (0.028, 0.035),
}
COWAN_N1_IRREGULARIDAD = {
    "Suave": (0.000, 0.000),
    "Menor": (0.001, 0.005),
    "Moderada": (0.006, 0.010),
    "Severa": (0.011, 0.020),
}
COWAN_N2_VARIACION_SECCION = {
    "Gradual": (0.000, 0.000),
    "Ocasional (alternante)": (0.001, 0.005),
    "Frecuente (alternante)": (0.010, 0.015),
}
COWAN_N3_OBSTRUCCIONES = {
    "Despreciable": (0.000, 0.004),
    "Menor": (0.005, 0.015),
    "Apreciable": (0.020, 0.030),
    "Severa": (0.040, 0.060),
}
COWAN_N4_VEGETACION = {
    "Baja": (0.002, 0.010),
    "Media": (0.010, 0.025),
    "Alta": (0.025, 0.050),
    "Muy alta": (0.050, 0.100),
}
COWAN_M5_MEANDRIZACION = {
    "Menor (Lcurva/Lrecta < 1.2)": 1.00,
    "Apreciable (1.2 - 1.5)": 1.15,
    "Severa (> 1.5)": 1.30,
}


def n_cowan(n0: float, n1: float, n2: float, n3: float, n4: float, m5: float) -> dict:
    """n = (n0 + n1 + n2 + n3 + n4) · m5 (Cowan, 1956)."""
    for nombre, valor in (("n0", n0), ("n1", n1), ("n2", n2), ("n3", n3), ("n4", n4)):
        if valor < 0:
            raise RoughnessError(f"El factor {nombre} de Cowan no puede ser negativo.")
    if m5 < 1.0:
        raise RoughnessError("m5 (meandrización) no puede ser menor que 1.0.")
    suma = n0 + n1 + n2 + n3 + n4
    n = suma * m5
    return {"metodo": "Cowan (1956)", "n": round(n, 4),
            "suma_factores": round(suma, 4), "factores": {"n0": n0, "n1": n1, "n2": n2,
                                                            "n3": n3, "n4": n4, "m5": m5}}


# ======================================================================
# 3. MÉTODOS LOGARÍTMICOS TEÓRICOS (Keulegan)
# ======================================================================
def n_keulegan(ks_m: float) -> dict:
    """
    n ≈ ks^(1/6) / 25.4 (relación tipo Strickler derivada de la ecuación
    de Keulegan para flujo rugoso turbulento; ks es la altura de aspereza
    de Nikuradse, en metros). Es la base del cálculo de rugosidad en
    modelos 2D tipo TELEMAC/Iber.
    """
    if ks_m <= 0:
        raise RoughnessError("ks debe ser mayor que 0.")
    n = (ks_m ** (1.0 / 6.0)) / 25.4
    return {"metodo": "Keulegan (flujo rugoso turbulento)", "n": round(n, 4), "ks_m": ks_m}


def factor_friccion_keulegan(radio_hidraulico_m: float, ks_m: float) -> dict:
    """1/√f = 2·log10(12.2·Rh/ks) -- el factor de fricción de Darcy-Weisbach
    equivalente, útil para contrastar contra el n de Manning derivado."""
    if radio_hidraulico_m <= 0 or ks_m <= 0:
        raise RoughnessError("Rh y ks deben ser mayores que 0.")
    inv_sqrt_f = 2.0 * math.log10(12.2 * radio_hidraulico_m / ks_m)
    if inv_sqrt_f <= 0:
        raise RoughnessError("1/√f resultó ≤ 0: Rh/ks demasiado pequeño para este rango de validez.")
    f = 1.0 / inv_sqrt_f ** 2
    return {"f_darcy_weisbach": round(f, 5), "radio_hidraulico_m": radio_hidraulico_m, "ks_m": ks_m}


# ======================================================================
# 4. PONDERACIÓN EN SECCIONES COMPUESTAS
# ======================================================================
def n_equivalente_horton_einstein(subsecciones: List[Tuple[float, float]]) -> dict:
    """
    Horton-Einstein: n_eq = [ Σ(Pi·ni^1.5) / P ]^(2/3)

    Asume que la velocidad media es igual en todas las subsecciones
    (hipótesis razonable cuando el flujo es aproximadamente uniforme a
    lo ancho de la sección).

    subsecciones: lista de (perímetro_mojado_parcial_m, n_parcial).
    """
    if not subsecciones:
        raise RoughnessError("Debe indicar al menos una subsección.")
    perimetro_total = sum(p for p, _ in subsecciones)
    if perimetro_total <= 0:
        raise RoughnessError("El perímetro mojado total debe ser mayor que 0.")
    if any(n <= 0 for _, n in subsecciones):
        raise RoughnessError("El n de cada subsección debe ser mayor que 0.")
    suma = sum(p * (n ** 1.5) for p, n in subsecciones)
    n_eq = (suma / perimetro_total) ** (2.0 / 3.0)
    return {"metodo": "Horton-Einstein", "n_equivalente": round(n_eq, 4),
            "perimetro_total_m": round(perimetro_total, 3), "n_subsecciones": len(subsecciones)}


def n_equivalente_lotter(subsecciones: List[Tuple[float, float, float]],
                         radio_hidraulico_total_m: float = None) -> dict:
    """
    Lotter: n_eq = P·Rh^(5/3) / Σ(Pi·Rhi^(5/3)/ni)

    Asume que el caudal total es la suma de los caudales de cada
    subsección (más adecuado que Horton-Einstein cuando la rugosidad
    entre subsecciones es muy distinta, p.ej. cauce principal liso +
    llanura con vegetación densa).

    subsecciones: lista de (perímetro_mojado_parcial_m, radio_hidráulico_parcial_m, n_parcial).

    radio_hidraulico_total_m: radio hidráulico de la sección COMPLETA. Si
        se omite (recomendado), se DERIVA de las propias subsecciones
        como A_total/P_total, con Ai = Rhi·Pi -- que es, además, la única
        forma de que el resultado sea internamente consistente: la propia
        deducción de la fórmula de Lotter (igualar el caudal Manning de
        la sección completa a la suma de los caudales parciales) exige
        que A_total = Σ(Rhi·Pi), así que pasar un Rh_total que no
        provenga de las subsecciones (p.ej. uno medido aparte, algo
        redondeado) aleja aún más el resultado del método -- se puede
        seguir pasando explícitamente si se cuenta con un Rh_total propio
        y se prefiere usarlo, pero el valor por defecto es el
        geométricamente consistente.

        LIMITACIÓN DEL MÉTODO A TENER EN CUENTA (no un error de esta
        implementación): a diferencia de Horton-Einstein, con Lotter la
        rugosidad UNIFORME en todas las subsecciones NO siempre
        reproduce exactamente ese mismo n como resultado si los radios
        hidráulicos Rhi de las subsecciones son muy distintos entre sí
        (p.ej. cauce principal profundo + llanura somera). La razón es
        que Rh_total = A_total/P_total es un promedio ARITMÉTICO de los
        Rhi, mientras que la fórmula compara caudales que dependen de
        Rhi^(5/3) -- una función convexa -- así que ambos promedios no
        coinciden (desigualdad de Jensen) salvo que los Rhi sean
        iguales entre sí. Es una propiedad conocida del método, no algo
        que corregir aquí: en secciones con calados muy dispares entre
        subsecciones, Lotter tiende a subestimar el n equivalente frente
        al valor que dan métodos que ponderan por área en vez de por
        perímetro (p.ej. Horton-Einstein); compare ambos antes de
        adoptar uno.
    """
    if not subsecciones:
        raise RoughnessError("Debe indicar al menos una subsección.")
    perimetro_total = sum(p for p, _, _ in subsecciones)
    if perimetro_total <= 0:
        raise RoughnessError("El perímetro mojado total debe ser mayor que 0.")
    if any(n <= 0 or rh <= 0 for _, rh, n in subsecciones):
        raise RoughnessError("El radio hidráulico y el n de cada subsección deben ser mayores que 0.")
    if radio_hidraulico_total_m is None:
        area_total = sum(p * rh for p, rh, _ in subsecciones)
        radio_hidraulico_total_m = area_total / perimetro_total
    if radio_hidraulico_total_m <= 0:
        raise RoughnessError("El radio hidráulico total debe ser mayor que 0.")
    denominador = sum(p * (rh ** (5.0 / 3.0)) / n for p, rh, n in subsecciones)
    if denominador <= 0:
        raise RoughnessError("El denominador de Lotter resultó no positivo; revise los datos.")
    n_eq = (perimetro_total * radio_hidraulico_total_m ** (5.0 / 3.0)) / denominador
    return {"metodo": "Lotter", "n_equivalente": round(n_eq, 4),
            "perimetro_total_m": round(perimetro_total, 3),
            "radio_hidraulico_total_m": round(radio_hidraulico_total_m, 4),
            "n_subsecciones": len(subsecciones)}
