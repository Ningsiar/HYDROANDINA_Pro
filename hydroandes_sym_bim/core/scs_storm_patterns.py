# -*- coding: utf-8 -*-
"""
core/scs_storm_patterns.py

Generación de hietogramas de diseño mediante los patrones de tormenta
adimensionales SCS/NRCS Tipo I, II y III, como alternativa al método de
bloques alternos basado en una curva IDF genérica (core/design_storm.py).

TRANSPARENCIA IMPORTANTE (léase antes de usar en diseño definitivo):
Las curvas oficiales del SCS/NRCS (publicadas en USDA-SCS TR-55, 2ª ed.,
1986, Apéndice B) están tabuladas en más de 48 puntos por tipo de
tormenta, en incrementos de 6 minutos. Esos valores tabulados exactos
NO se pudieron verificar de forma verbatim y confiable en este entorno
(las fuentes primarias consultadas —TR-55 Apéndice B, archivos .hcr de
HydroCAD— están en formatos no extraíbles como texto plano aquí). Por
esa razón, este módulo implementa una **aproximación paramétrica** de
la FORMA GENERAL de cada curva (basada en las características
cualitativas ampliamente documentadas de cada tipo: Tipo I = clima
mediterráneo/costero, la más suave y de pico más temprano; Tipo II = la
más intensa y de uso más extendido en EE.UU., pico agudo centrado en
t=12h; Tipo III = clima húmedo tropical/costa del Golfo, pico centrado
pero con cola posterior más pesada que el Tipo II), NO una reproducción
exacta de la tabla oficial NRCS.

Para un diseño definitivo o una presentación regulatoria que exija la
curva NRCS exacta, use `cargar_tabla_oficial_csv()` para reemplazar esta
aproximación por los valores tabulados oficiales (obtenibles del
apéndice B de TR-55 o de WinTR-55), en vez de la curva aproximada aquí
generada.

ADEMÁS de los 4 tipos SCS aproximados, este módulo expone
`curva_cusco_astete_2015()`: el patrón de tormenta de 24h de la
estación KAYRA (Cusco), Astete, E. (2015) -- a diferencia de los tipos
SCS, esta SÍ es una curva TABULADA (241 puntos cada 6 min), aportada
directamente por el usuario y verificada contra su propia hoja de
cálculo (ver docstring de esa función).
"""
import csv
import json
import math
import os
from typing import List, Tuple, Optional


def _curva_adimensional_sigmoidal(a: float, k: float, n_puntos: int = 289) -> List[Tuple[float, float]]:
    """
    Curva S adimensional F(t) en [0,1] x [0,1], mediante
    F(t) = u^a / (u^a + (1-u)^a), con u = t^k (reparametrización que
    adelanta o retrasa el punto de inflexión sin romper F(0)=0, F(1)=1
    ni la monotonía). 'a' controla qué tan abrupto es el pico (mayor a
    = tormenta más intensa/concentrada); 'k' controla si el pico ocurre
    antes (k<1) o después (k>1) del punto medio del periodo.
    """
    puntos = []
    for i in range(n_puntos + 1):
        t = i / n_puntos
        if t <= 0:
            f = 0.0
        elif t >= 1:
            f = 1.0
        else:
            u = t ** k
            f = (u ** a) / (u ** a + (1 - u) ** a)
        puntos.append((t, f))
    return puntos


# Parámetros de forma por tipo (ver advertencia de aproximación arriba).
_PARAMETROS_TIPO = {
    "I":   {"a": 3.0, "k": 0.80},   # más suave, pico más temprano (~t=0.35-0.40)
    # Tipo IA: el MENOS intenso de los cuatro (clima marítimo del Pacífico
    # noroeste). Su pico es el más temprano y el más aplanado, de modo que
    # para una misma lámina de 24 h produce el caudal punta más bajo. Se
    # añadió en la v0.2.65 -- faltaba pese a ser uno de los cuatro tipos
    # estándar del NRCS, y su ausencia obligaba a usar el Tipo I, que
    # sobrestima el pico en climas de ese régimen.
    "IA":  {"a": 2.0, "k": 0.70},
    "II":  {"a": 9.0, "k": 1.00},   # más intensa, pico agudo centrado (t=0.5)
    "III": {"a": 6.0, "k": 1.00},   # intensa, centrada, cola posterior más pesada que II
}


def curva_adimensional(tipo: str, n_puntos: int = 289) -> List[Tuple[float, float]]:
    tipo = tipo.upper()
    if tipo not in _PARAMETROS_TIPO:
        raise ValueError(f"Tipo debe ser uno de {list(_PARAMETROS_TIPO)} (se recibió '{tipo}').")
    p = _PARAMETROS_TIPO[tipo]
    return _curva_adimensional_sigmoidal(p["a"], p["k"], n_puntos)


def cargar_tabla_oficial_csv(ruta_csv: str) -> List[Tuple[float, float]]:
    """
    Permite reemplazar la curva aproximada por la tabla oficial NRCS
    (o cualquier otra curva adimensional), cargada desde un CSV con
    columnas 't_fraccion' (0 a 1, tiempo/duración total) y
    'f_acumulada' (0 a 1, fracción acumulada de lluvia).
    """
    puntos = []
    with open(ruta_csv, newline="", encoding="utf-8") as f:
        lector = csv.DictReader(f)
        if "t_fraccion" not in lector.fieldnames or "f_acumulada" not in lector.fieldnames:
            raise ValueError("El CSV debe tener columnas 't_fraccion' y 'f_acumulada'.")
        for fila in lector:
            puntos.append((float(fila["t_fraccion"]), float(fila["f_acumulada"])))
    puntos.sort(key=lambda p: p[0])
    if abs(puntos[0][0]) > 1e-6 or abs(puntos[0][1]) > 1e-6:
        raise ValueError("La curva debe iniciar en (t=0, F=0).")
    if abs(puntos[-1][0] - 1.0) > 1e-6 or abs(puntos[-1][1] - 1.0) > 1e-6:
        raise ValueError("La curva debe terminar en (t=1, F=1).")
    return puntos


_CURVA_CUSCO_CACHE: Optional[List[Tuple[float, float]]] = None


def curva_cusco_astete_2015() -> List[Tuple[float, float]]:
    """
    Curva adimensional TABULADA (no una aproximación paramétrica como los
    tipos I/IA/II/III de arriba) del patrón de tormenta de 24 horas de la
    estación KAYRA (Cusco), Astete, E. (2015) -- 241 puntos cada 6 minutos,
    aportados por el usuario en su hoja de cálculo "Patron Tormenta -
    CUSCO.xlsx" (hoja "PATRON"; verificados en este plugin contra las
    hojas "PRUEBA 1/2 Max 24Hrs" del mismo archivo, que aplican esta
    misma curva a P24 de Tr=100/200/500/1000 años -- ver
    resources/patron_tormenta_cusco_astete_2015.json para la fuente
    exacta y la trazabilidad completa).

    A diferencia de curva_adimensional() (SCS I/IA/II/III), esta SÍ es la
    tabla original del autor, no una forma aproximada -- se usa
    directamente como `curva_personalizada` de hietograma_scs()."""
    global _CURVA_CUSCO_CACHE
    if _CURVA_CUSCO_CACHE is None:
        ruta = os.path.join(os.path.dirname(__file__), "..", "resources",
                             "patron_tormenta_cusco_astete_2015.json")
        with open(ruta, "r", encoding="utf-8") as f:
            datos = json.load(f)
        _CURVA_CUSCO_CACHE = [(float(t), float(f)) for t, f in datos["curva"]]
    return _CURVA_CUSCO_CACHE


def hietograma_scs(p_total_mm: float, duracion_total_h: float, dt_h: float,
                    tipo: str = "II", curva_personalizada: Optional[List[Tuple[float, float]]] = None) -> List[float]:
    """
    Genera el hietograma de diseño (incrementos de lluvia TOTAL en mm,
    uno por intervalo Dt) distribuyendo p_total_mm según la forma de la
    curva adimensional del tipo SCS indicado (o una curva personalizada
    ya cargada con cargar_tabla_oficial_csv).

    duracion_total_h: duración total de la tormenta a la que se aplica
        la curva (normalmente 24h para las curvas SCS estándar, pero se
        deja configurable por si se usa junto con una curva personalizada
        de otra duración).
    """
    curva = curva_personalizada if curva_personalizada is not None else curva_adimensional(tipo)
    n_intervalos = int(round(duracion_total_h / dt_h))
    if n_intervalos < 1:
        raise ValueError("duracion_total_h debe ser mayor o igual a dt_h.")

    ts_curva = [p[0] for p in curva]
    fs_curva = [p[1] for p in curva]

    def f_en(t_fraccion: float) -> float:
        # Interpolación lineal sobre la curva adimensional
        if t_fraccion <= 0:
            return 0.0
        if t_fraccion >= 1:
            return 1.0
        # búsqueda lineal simple (la curva tiene pocos cientos de puntos, es rápido)
        for i in range(1, len(ts_curva)):
            if ts_curva[i] >= t_fraccion:
                t0, t1 = ts_curva[i - 1], ts_curva[i]
                f0, f1 = fs_curva[i - 1], fs_curva[i]
                if t1 == t0:
                    return f1
                return f0 + (f1 - f0) * (t_fraccion - t0) / (t1 - t0)
        return 1.0

    acumulados = [p_total_mm * f_en((i + 1) * dt_h / duracion_total_h) for i in range(n_intervalos)]
    incrementos = [acumulados[0]] + [acumulados[i] - acumulados[i - 1] for i in range(1, n_intervalos)]
    return incrementos


def tiempo_pico_relativo(tipo: str) -> float:
    """Fracción de tiempo (0-1) en la que ocurre el incremento máximo de
    lluvia, útil para mostrar al usuario qué tan concentrado es el pico
    de cada tipo de tormenta aproximada."""
    curva = curva_adimensional(tipo, n_puntos=576)
    incrementos = [curva[i][1] - curva[i - 1][1] for i in range(1, len(curva))]
    idx_max = incrementos.index(max(incrementos))
    return curva[idx_max][0]
