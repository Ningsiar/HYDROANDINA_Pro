# -*- coding: utf-8 -*-
"""
core/curve_number.py

Modelo de número de curva SCS/NRCS: matriz uso de suelo x grupo
hidrológico (A/B/C/D), cálculo de CN ponderado (AMC II) y su conversión
a condición seca (AMC I) y húmeda (AMC III), retención potencial S y
abstracción inicial Ia.

La tabla por defecto está adaptada a coberturas típicas del Altiplano/
Puna andina (pastos naturales tipo ichu, afloramientos rocosos/suelo
desnudo, bofedales). Los valores de CN para estas coberturas específicas
NO están tan universalmente tabulados como los usos agrícolas/urbanos
clásicos del manual TR-55; aquí se usan valores de referencia razonables
adaptados de literatura de hidrología andina, pero se recomienda
verificarlos/ajustarlos contra un manual local (ANA, SENAMHI) antes de
un diseño definitivo. Todos los valores son editables desde la interfaz.
"""
import math
from dataclasses import dataclass
from typing import List, Dict


@dataclass
class UsoSuelo:
    nombre: str
    cn_a: int
    cn_b: int
    cn_c: int
    cn_d: int
    area_km2: float = 0.0


# Tabla por defecto orientativa para condiciones altoandinas/Puna.
# EDITAR/VALIDAR contra fuente local antes de uso en diseño definitivo.
TABLA_USOS_ANDINOS_DEFAULT: List[UsoSuelo] = [
    UsoSuelo("Pastos naturales (ichu / ratio bueno)", cn_a=39, cn_b=61, cn_c=74, cn_d=80),
    UsoSuelo("Pastos naturales (ichu / ratio pobre-degradado)", cn_a=68, cn_b=79, cn_c=86, cn_d=89),
    UsoSuelo("Bofedal / humedal altoandino", cn_a=30, cn_b=50, cn_c=65, cn_d=75),
    UsoSuelo("Afloramiento rocoso / suelo desnudo", cn_a=77, cn_b=86, cn_c=91, cn_d=94),
    UsoSuelo("Cultivos en secano (surcos rectos)", cn_a=67, cn_b=78, cn_c=85, cn_d=89),
    UsoSuelo("Centro poblado / área urbana dispersa", cn_a=77, cn_b=85, cn_c=90, cn_d=92),
    UsoSuelo("Matorral / arbustos andinos", cn_a=35, cn_b=56, cn_c=70, cn_d=77),
]


def cn_ponderado(usos: List[UsoSuelo], grupo_hidrologico: str) -> float:
    """
    grupo_hidrologico: 'A', 'B', 'C' o 'D'. Pondera por área (km2) cada
    uso de suelo con su CN correspondiente al grupo hidrológico indicado.
    Si el usuario tiene una mezcla de grupos hidrológicos por uso de
    suelo (caso más realista), use cn_ponderado_mixto().
    """
    area_total = sum(u.area_km2 for u in usos)
    if area_total <= 0:
        raise ValueError("El área total de los usos de suelo debe ser mayor que cero.")
    atributo = {"A": "cn_a", "B": "cn_b", "C": "cn_c", "D": "cn_d"}[grupo_hidrologico.upper()]
    suma = sum(u.area_km2 * getattr(u, atributo) for u in usos)
    return suma / area_total


def cn_ponderado_mixto(filas: List[dict]) -> float:
    """
    filas: lista de {'area_km2': float, 'cn': int} ya resueltas (uso de
    suelo x grupo hidrológico específico de cada polígono, típicamente
    obtenido cruzando en QGIS la capa de uso de suelo con la de grupo
    hidrológico mediante 'native:intersection' antes de llamar aquí).
    """
    area_total = sum(f["area_km2"] for f in filas)
    if area_total <= 0:
        raise ValueError("El área total debe ser mayor que cero.")
    return sum(f["area_km2"] * f["cn"] for f in filas) / area_total


def condiciones_amc(cn_ii: float) -> Dict[str, float]:
    cn_i = cn_ii / (2.281 - 0.01281 * cn_ii)
    cn_iii = cn_ii / (0.427 + 0.00573 * cn_ii)
    s_mm = (1000.0 / cn_ii - 10.0) * 25.4
    ia_mm = 0.2 * s_mm
    return {
        "CN_I": round(cn_i, 2),
        "CN_II": round(cn_ii, 2),
        "CN_III": round(cn_iii, 2),
        "S_mm": round(s_mm, 2),
        "Ia_mm": round(ia_mm, 2),
    }


# ======================================================================
# Corrección por pendiente (Williams, 1995) -- entorno andino
# ======================================================================
def correccion_pendiente_williams(cn_ii: float, cn_iii: float, pendiente_pct: float) -> float:
    """CN_II corregido por pendiente (Williams, 1995, tal como se cita
    en la documentación teórica de SWAT -- Neitsch et al., "Soil and
    Water Assessment Tool Theoretical Documentation"). La metodología
    NRCS/TR-55 original se calibró para pendientes de referencia ~5%,
    insuficiente en la cordillera andina donde las laderas superan
    fácilmente ese valor -- esta corrección lo compensa:

        CN_IIs = (CN_III - CN_II)/3 · (1 - 2·e^(-13.86·α)) + CN_II

    con α = pendiente_pct/100 (fracción). PROPIEDAD DE CALIBRACIÓN
    verificable analíticamente: a pendiente EXACTAMENTE 5% (α=0.05),
    el factor (1-2·e^(-13.86·α)) se anula y CN_IIs = CN_II (sin
    corrección) -- es el punto de referencia con el que el NRCS
    desarrolló sus tablas de CN originales. Para pendientes menores a
    5% el CN corregido baja (menos escorrentía relativa); para
    pendientes mayores sube hacia CN_III (más escorrentía).

    `cn_iii` debe venir de `condiciones_amc(cn_ii)["CN_III"]` (la
    forma polinómica NRCS clásica, la misma que usa el resto del
    plugin) -- no mezcle con otra fórmula de CN_III."""
    if not (0.0 < cn_ii <= 100.0):
        raise ValueError(f"CN_II fuera de rango físico (0,100]: {cn_ii}")
    if pendiente_pct < 0:
        raise ValueError("la pendiente no puede ser negativa.")
    alpha = pendiente_pct / 100.0
    factor = 1.0 - 2.0 * math.exp(-13.86 * alpha)
    cn_corregido = (cn_iii - cn_ii) / 3.0 * factor + cn_ii
    return min(max(cn_corregido, 1.0), 100.0)  # límites físicos del CN


# ======================================================================
# Selección de AMC por precipitación antecedente de 5 días -- Tabla 4-1
# del National Engineering Handbook (SCS/NRCS, Section 4), reproducida
# también en el manual TR-55.
# ======================================================================
# temporada -> (umbral_bajo_mm, umbral_alto_mm): <bajo -> AMC I,
# [bajo,alto] -> AMC II, >alto -> AMC III. Umbrales originales en
# pulgadas (dormant: <0.5, 0.5-1.1, >1.1; growing: <1.4, 1.4-2.1,
# >2.1), convertidos aquí a mm (1 in = 25.4 mm).
UMBRALES_AMC_MM: Dict[str, tuple] = {
    "dormant": (12.7, 27.94),   # temporada NO vegetativa (suelo desnudo/latente)
    "growing": (35.56, 53.34),  # temporada vegetativa (mayor evapotranspiración, tolera más lluvia)
}


def amc_por_precipitacion_antecedente(precip_5dias_mm: float, temporada: str = "growing") -> str:
    """Clasifica la condición de humedad antecedente (AMC "I"/"II"/
    "III") a partir de la lluvia acumulada en los 5 días previos al
    evento de diseño, según la Tabla 4-1 del NRCS -- ver
    UMBRALES_AMC_MM. `temporada`: "dormant" (no vegetativa) o
    "growing" (vegetativa, umbrales más altos)."""
    if temporada not in UMBRALES_AMC_MM:
        raise ValueError(f"temporada «{temporada}» no reconocida -- use 'dormant' o 'growing'.")
    if precip_5dias_mm < 0:
        raise ValueError("la precipitación antecedente no puede ser negativa.")
    bajo, alto = UMBRALES_AMC_MM[temporada]
    if precip_5dias_mm < bajo:
        return "I"
    if precip_5dias_mm <= alto:
        return "II"
    return "III"


def cn_por_amc_automatico(cn_ii: float, precip_5dias_mm: float, temporada: str = "growing") -> dict:
    """Combina `condiciones_amc()` con `amc_por_precipitacion_antecedente()`:
    calcula CN_I/CN_II/CN_III y además indica cuál de los tres aplica
    (y su valor, `CN_aplicable`) según la lluvia antecedente de 5 días
    indicada -- para usar automáticamente sin que el usuario deba
    elegir a mano la clase AMC."""
    resultado = dict(condiciones_amc(cn_ii))
    clase = amc_por_precipitacion_antecedente(precip_5dias_mm, temporada)
    resultado["clase_amc_seleccionada"] = clase
    resultado["CN_aplicable"] = resultado[f"CN_{clase}"]
    resultado["precip_5dias_mm"] = precip_5dias_mm
    resultado["temporada"] = temporada
    return resultado
