# -*- coding: utf-8 -*-
"""
core/runoff_coefficient.py

Métodos para OBTENER el coeficiente de escorrentía C del Método Racional
(y de las fórmulas de la Pestaña 6 que lo reutilizan), en vez de dejarlo
como un único valor manual. El manual sigue siendo válido y sigue siendo
el que se usa por defecto (self.spin_coef_c en la Pestaña 4) -- lo que
faltaba era una forma trazable de LLEGAR a ese número.

Se ofrecen dos métodos adicionales:

  1. PONDERADO POR USO DE SUELO/COBERTURA -- igual en espíritu a la
     ponderación de Número de Curva que ya existe en core/curve_number.py
     (tabla de coberturas x área, promedio ponderado). Los valores de C
     por cobertura son los rangos ORIENTATIVOS de uso extendido en
     ingeniería hidrológica para el Método Racional (frecuencia de
     diseño 5-10 años); como con la tabla de Número de Curva, son un
     punto de partida editable, no un valor normativo fijo -- verifíquelos
     contra la norma local antes de un diseño definitivo.

  2. DESDE EL NÚMERO DE CURVA (CN) YA CALCULADO EN LA PESTAÑA 3 -- si ya
     tiene el CN de la cuenca, C se puede derivar de forma consistente
     con la MISMA ecuación SCS-CN que el resto del plugin usa para las
     pérdidas por infiltración (ver core/infiltration.py::perdidas_scs_cn
     y core/curve_number.py::condiciones_amc), en vez de introducir una
     fórmula de conversión CN→C aparte. Por definición, el coeficiente de
     escorrentía ES el cociente escorrentía/lluvia (C = Q/P); si ya se
     conoce Q por el método SCS-CN para la lámina de diseño P, C = Q/P se
     sigue directamente, sin ningún coeficiente de conversión adicional
     que verificar.
"""
import math
from typing import List, Tuple


class RunoffCoefficientError(Exception):
    pass


# ======================================================================
# 1. PONDERADO POR USO DE SUELO / COBERTURA
# ======================================================================
# (nombre, C típico, C mínimo, C máximo). Valores orientativos de uso
# extendido en ingeniería hidrológica para el Método Racional (frecuencia
# de diseño 5-10 años; para Tr mayores algunas referencias recomiendan
# incrementarlos con un factor de ajuste, no incluido aquí). El usuario
# puede editar cualquier fila o agregar coberturas propias.
TABLA_COEFICIENTES_C_DEFAULT: List[Tuple[str, float, float, float]] = [
    ("Techos / superficies impermeables", 0.90, 0.75, 0.95),
    ("Pavimento asfáltico/concreto", 0.85, 0.70, 0.95),
    ("Zona urbana densa (comercial/industrial)", 0.75, 0.60, 0.90),
    ("Zona urbana media (residencial compacta)", 0.55, 0.40, 0.65),
    ("Zona urbana dispersa (residencial con jardines)", 0.35, 0.25, 0.45),
    ("Suelo desnudo / erosionado", 0.50, 0.35, 0.70),
    ("Pastos / praderas (pendiente moderada-alta, Andes)", 0.35, 0.20, 0.50),
    ("Cultivos en ladera", 0.40, 0.25, 0.55),
    ("Matorral / arbustos", 0.30, 0.15, 0.45),
    ("Bosque / cobertura densa", 0.20, 0.10, 0.30),
    ("Roca expuesta / afloramientos", 0.60, 0.45, 0.80),
    ("Nieve / glaciar (escorrentía de deshielo)", 0.45, 0.25, 0.65),
]


def coeficiente_escorrentia_ponderado(coberturas: List[Tuple[str, float, float]]) -> dict:
    """
    coberturas: lista de (nombre, área_km2, C) -- el mismo patrón que
    cn_ponderado() en core/curve_number.py. Devuelve el C ponderado por
    área y el detalle por cobertura, para poder mostrarlo en una tabla.
    """
    area_total = sum(area for _, area, _ in coberturas)
    if area_total <= 0:
        raise RunoffCoefficientError("El área total de las coberturas debe ser mayor que 0.")
    if any(c < 0 or c > 1 for _, _, c in coberturas):
        raise RunoffCoefficientError("El coeficiente C de cada cobertura debe estar entre 0 y 1.")

    suma_ponderada = sum(area * c for _, area, c in coberturas)
    c_ponderado = suma_ponderada / area_total

    detalle = [
        {"cobertura": nombre, "area_km2": round(area, 4),
         "porcentaje": round(area / area_total * 100.0, 2), "C": c}
        for nombre, area, c in coberturas
    ]
    return {"C_ponderado": round(c_ponderado, 4), "area_total_km2": round(area_total, 4),
            "n_coberturas": len(coberturas), "detalle": detalle}


# ======================================================================
# 2. DESDE EL NÚMERO DE CURVA (misma ecuación SCS-CN que el resto del plugin)
# ======================================================================
def coeficiente_escorrentia_desde_cn(p_mm: float, s_mm: float, ia_mm: float = None) -> dict:
    """
    Deriva C = Q/P a partir de la lámina de diseño P (mm, típicamente el
    P24 de la Pestaña 5) y la retención potencial máxima S (mm, del
    Número de Curva ya calculado en la Pestaña 3 -- ver
    core.curve_number.condiciones_amc), aplicando la MISMA ecuación
    SCS-CN de escorrentía directa que usa el resto del plugin:

        Q = (P − Ia)² / (P − Ia + S)     si P > Ia,  si no Q = 0
        Ia = 0.2·S                        (salvo que se indique otro Ia)

    C = Q/P es, por definición, el coeficiente de escorrentía -- no hace
    falta ninguna fórmula de conversión CN→C aparte de la que ya calcula
    la escorrentía SCS: si P y S ya dieron Q, C se sigue directamente.

    Devuelve también Q_mm y el % de la lluvia que se pierde (Ia + pérdida
    por infiltración posterior), para que el usuario vea de dónde sale
    el número.
    """
    if p_mm <= 0:
        raise RunoffCoefficientError("La lámina de precipitación P debe ser mayor que 0.")
    if s_mm <= 0:
        raise RunoffCoefficientError(
            "S debe ser mayor que 0. Calcule primero el Número de Curva en la Pestaña 3.")
    ia = 0.2 * s_mm if ia_mm is None else ia_mm
    if p_mm <= ia:
        q_mm = 0.0
    else:
        q_mm = (p_mm - ia) ** 2 / (p_mm - ia + s_mm)
    c = q_mm / p_mm
    return {
        "C_desde_CN": round(c, 4), "Q_mm": round(q_mm, 3), "P_mm": p_mm,
        "S_mm": s_mm, "Ia_mm": round(ia, 3),
        "perdidas_mm": round(p_mm - q_mm, 3),
        "nota": (
            "C = Q/P con Q de la ecuación SCS-CN estándar (misma que las pérdidas por infiltración "
            "de la Pestaña 3), no una fórmula de conversión CN→C aparte."
        ),
    }
