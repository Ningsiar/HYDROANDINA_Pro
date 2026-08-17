# -*- coding: utf-8 -*-
"""
core/pedotransfer_soilgrids.py

Clasificación AUTÓNOMA del Grupo Hidrológico de Suelo (HSG: A/B/C/D) a
partir de textura (% arena, % arcilla) -- típicamente obtenida de
SoilGrids (ISRIC) a 0-30 cm, ver core/landcover_soils.py para la
descarga/recorte del ráster. Reemplaza la necesidad de que el usuario
aporte un ráster de HSG ya clasificado (HYSOGs250m u otro) cuando no
lo tiene a mano.

MÉTODO (2 pasos):

  1. Clasificación textural USDA: (% arena, % arcilla) -> una de las
     12 clases texturales del triángulo de suelos USDA, mediante el
     algoritmo estándar de discriminantes por región (el mismo que usa
     la calculadora de textura de suelos del USDA-NRCS y paquetes como
     `soiltexture` de R) -- sin aproximación por umbrales simplificados.

  2. HSG por clase textural: se usa la tabla de correspondencia
     textura->HSG estándar (reproducida en TR-55 y numerosos manuales
     de drenaje) -- NO se deriva de un umbral de conductividad
     hidráulica saturada (Ksat) propio, por la razón explicada abajo.

DECISIÓN DE DISEÑO IMPORTANTE (por qué NO se implementó la fórmula de
pedotransferencia de Saxton & Rawls que se mencionó como ejemplo
inicialmente): el plugin YA tiene, en core/infiltration.py
(`PARAMETROS_GREEN_AMPT`), la tabla de Rawls, Brakensiek & Miller
(1983) con el Ksat representativo de cada una de las 11 clases
texturales más comunes (la misma tabla que usa HEC-HMS) -- SE REUTILIZA
esa tabla aquí (columna `ksat_mm_h` del resultado) en vez de reimplementar
desde cero las ecuaciones multi-paso de Saxton & Rawls (2006), que no se
pudieron verificar con la precisión necesaria en este entorno (sin
acceso a la publicación original) y cuyo error, de tenerlo, sería
SILENCIOSO (un Ksat plausible pero sistemáticamente sesgado). Sin
embargo, el Ksat de Rawls et al. 1983 está calibrado para Green-Ampt
(ya reducido a la mitad respecto al Ksat saturado real, para compensar
el aire atrapado frente al frente de humedecimiento -- ver Bouwer,
1969) -- comparar ESE valor directamente contra los umbrales de HSG
del NRCS (que sí usan el Ksat saturado real, no el reducido) daría
clasificaciones sistemáticamente más finas de lo correcto (p.ej. Arena
pura, que obviamente es HSG A, caería en HSG B). Por eso el HSG se
determina por la tabla textura->HSG directa (independiente de
cualquier umbral de Ksat), y el Ksat de Rawls et al. queda solo como
dato AUXILIAR útil (p.ej. para alimentar el modelo Green-Ampt de la
misma Pestaña 3 con un valor consistente).

ALCANCE: NO cubre los modificadores de HYSOGs250m por profundidad a
capa restrictiva o nivel freático (Ross et al. 2018) -- solo la
textura del suelo superficial (0-30 cm). Para cuencas con capas
restrictivas someras conocidas (caliche, roca, permafrost), ajuste el
HSG manualmente a una clase más restrictiva (C o D) según su
criterio/EMS.
"""
from typing import Dict

try:
    import numpy as np
except ImportError:
    np = None

from .infiltration import PARAMETROS_GREEN_AMPT


class PedotransferError(Exception):
    pass


# Tabla textura USDA -> HSG (A/B/C/D) -- estándar reproducido en TR-55
# y manuales de drenaje (mismas 11 clases de Rawls, Brakensiek & Miller
# 1983 que ya usa core/infiltration.py -- la pura "limo" no está en esa
# tabla de Ksat, pero sí se clasifica texturalmente, con HSG B por
# analogía a franco limoso, ver docstring del módulo).
TEXTURA_A_HSG: Dict[str, str] = {
    "arena": "A", "arena_franca": "A", "franco_arenoso": "A",
    "franco_limoso": "B", "franco": "B", "limo": "B",
    "franco_arcillo_aren": "C",
    "franco_arcilloso": "D", "franco_arcillo_lim": "D",
    "arcillo_arenoso": "D", "arcillo_limoso": "D", "arcilla": "D",
}

# Códigos HSG numéricos (mismo convenio que core/landcover_soils.py:
# mapeo_codigo_hsg = {1: "A", 2: "B", 3: "C", 4: "D"}).
_HSG_A_CODIGO = {"A": 1, "B": 2, "C": 3, "D": 4}


def clasificar_textura_usda(arena_pct: float, arcilla_pct: float) -> str:
    """(% arena, % arcilla) -> una de las 12 clases texturales USDA
    (% limo se deriva como 100-arena-arcilla). Devuelve la clave en
    español usada en TEXTURA_A_HSG / PARAMETROS_GREEN_AMPT (o "limo"
    para la clase pura, sin entrada de Ksat propia)."""
    if not (0.0 <= arena_pct <= 100.0) or not (0.0 <= arcilla_pct <= 100.0):
        raise PedotransferError(
            f"% arena ({arena_pct}) y % arcilla ({arcilla_pct}) deben estar en [0,100].")
    limo_pct = 100.0 - arena_pct - arcilla_pct
    if limo_pct < -1e-6:
        raise PedotransferError(
            f"% arena ({arena_pct}) + % arcilla ({arcilla_pct}) no puede superar 100 "
            f"(% limo resultante = {limo_pct:.2f}).")
    limo_pct = max(limo_pct, 0.0)
    sa, cl, si = arena_pct, arcilla_pct, limo_pct

    if si + 1.5 * cl < 15:
        return "arena"
    if si + 2.0 * cl < 30:
        return "arena_franca"
    if (7 <= cl <= 20 and sa > 52 and si + 2.0 * cl >= 30) or (cl < 7 and si < 50):
        return "franco_arenoso"
    if 7 <= cl <= 27 and 28 <= si < 50 and sa <= 52:
        return "franco"
    if (si >= 50 and 12 <= cl < 27) or (50 <= si < 80 and cl < 12):
        return "franco_limoso"
    if si >= 80 and cl < 12:
        return "limo"
    if 20 <= cl < 35 and si < 28 and sa > 45:
        return "franco_arcillo_aren"
    if 27 <= cl < 40 and sa <= 20:
        return "franco_arcillo_lim"
    if 27 <= cl < 40 and 20 < sa <= 45:
        return "franco_arcilloso"
    if cl >= 35 and sa >= 45:
        return "arcillo_arenoso"
    if cl >= 40 and si >= 40:
        return "arcillo_limoso"
    if cl >= 40 and sa <= 45:
        return "arcilla"
    # Punto residual (raro, cerca de vértices/bordes múltiples no cubiertos
    # arriba) -- se asigna a "franco" (la clase central del triángulo,
    # la opción menos extrema) en vez de fallar.
    return "franco"


def clasificar_hsg_desde_textura(arena_pct: float, arcilla_pct: float) -> dict:
    """Combina clasificar_textura_usda() + TEXTURA_A_HSG + el Ksat
    auxiliar de Rawls et al. 1983 (core/infiltration.py) en un solo
    resultado. `ksat_mm_h` es None para la clase "limo" (sin entrada
    en la tabla de Green-Ampt, ver docstring del módulo)."""
    clase = clasificar_textura_usda(arena_pct, arcilla_pct)
    hsg = TEXTURA_A_HSG[clase]
    entrada_ga = PARAMETROS_GREEN_AMPT.get(clase)
    return {
        "arena_pct": round(arena_pct, 2), "arcilla_pct": round(arcilla_pct, 2),
        "limo_pct": round(100.0 - arena_pct - arcilla_pct, 2),
        "clase_textural": clase, "clase_textural_nombre": entrada_ga[0] if entrada_ga else "Limo",
        "hsg": hsg,
        "ksat_mm_h": entrada_ga[1] if entrada_ga else None,
    }


def clasificar_hsg_raster(arena_arr, arcilla_arr):
    """Versión vectorizada (numpy) de clasificar_hsg_desde_textura(),
    para clasificar un ráster completo de una sola vez -- devuelve un
    array de códigos HSG (1=A, 2=B, 3=C, 4=D), mismo convenio que
    core/landcover_soils.py. Replica EXACTAMENTE las mismas reglas y
    el mismo orden de evaluación que la versión escalar (cada máscara
    se aplica solo sobre los píxeles aún sin clasificar, igual que la
    cadena if/elif escalar)."""
    if np is None:
        raise PedotransferError(
            "numpy no está disponible -- necesario para clasificar un ráster completo "
            "(clasificar_hsg_desde_textura() sí funciona sin numpy, píxel a píxel).")
    sa = np.asarray(arena_arr, dtype=np.float64)
    cl = np.asarray(arcilla_arr, dtype=np.float64)
    si = 100.0 - sa - cl

    hsg = np.zeros(sa.shape, dtype=np.uint8)
    sin_clasificar = np.ones(sa.shape, dtype=bool)

    def _asignar(mascara, letra):
        nonlocal sin_clasificar
        m = mascara & sin_clasificar
        hsg[m] = _HSG_A_CODIGO[letra]
        sin_clasificar &= ~m

    _asignar(si + 1.5 * cl < 15, "A")                                            # arena
    _asignar(si + 2.0 * cl < 30, "A")                                            # arena franca
    _asignar(((cl >= 7) & (cl <= 20) & (sa > 52) & (si + 2.0 * cl >= 30))
             | ((cl < 7) & (si < 50)), "A")                                      # franco arenoso
    _asignar((cl >= 7) & (cl <= 27) & (si >= 28) & (si < 50) & (sa <= 52), "B")   # franco
    _asignar(((si >= 50) & (cl >= 12) & (cl < 27))
             | ((si >= 50) & (si < 80) & (cl < 12)), "B")                        # franco limoso
    _asignar((si >= 80) & (cl < 12), "B")                                        # limo
    _asignar((cl >= 20) & (cl < 35) & (si < 28) & (sa > 45), "C")                # franco arcillo-arenoso
    _asignar((cl >= 27) & (cl < 40) & (sa <= 20), "D")                           # franco arcillo-limoso
    _asignar((cl >= 27) & (cl < 40) & (sa > 20) & (sa <= 45), "D")               # franco arcilloso
    _asignar((cl >= 35) & (sa >= 45), "D")                                       # arcillo-arenoso
    _asignar((cl >= 40) & (si >= 40), "D")                                       # arcillo-limoso
    _asignar((cl >= 40) & (sa <= 45), "D")                                       # arcilla
    _asignar(sin_clasificar, "B")                                                # residual -> franco (B)

    return hsg
