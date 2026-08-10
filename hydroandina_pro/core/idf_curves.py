# -*- coding: utf-8 -*-
"""
core/idf_curves.py

Curvas Intensidad-Duración-Frecuencia (IDF), derivadas de las
precipitaciones de diseño P24h(Tr) ya calculadas en la Pestaña 5
(core/frequency_analysis.py) para los periodos de retorno establecidos
(frequency_analysis.PERIODOS_RETORNO_DEFAULT).

TRANSPARENCIA METODOLÓGICA (léase antes de usar en diseño definitivo):
este plugin NO cuenta con series de precipitación sub-diaria (pluviograma)
para ajustar una curva IDF real, calibrada con intensidades observadas a
distintas duraciones -- solo con la serie de máximos anuales de P24h. Las
curvas de este módulo se DERIVAN analíticamente de P24h(Tr) mediante el
mismo escalamiento potencial tipo Sherman ya usado en
core/design_storm.py para desagregar el hietograma de diseño:

    P(d) = P24h(Tr) * (d/1440min)^n          (d en minutos)
    i(d) = P(d) / (d/60min)  [mm/h]           (intensidad = lámina / duración)

con n editable por el usuario (por defecto 0.20, rango típico 0.15-0.30
reportado en la bibliografía para relaciones profundidad-duración). Esto
es una SIMPLIFICACIÓN EXPLÍCITA, consistente con la misma que ya usa
core/design_storm.py -- no reemplaza una curva IDF regional real (p.ej.
de SENAMHI/ANA) si se dispone de ella para la subcuenca de interés.

A partir de esos puntos (d, i) por cada Tr se ajustan dos tipos de
ecuación, ambas por mínimos cuadrados en escala log-log:
  1. Una ecuación potencial simple por cada curva/Tr: i = a * t^b.
  2. Una ecuación IDF combinada de las 3 variables (todas las curvas a
     la vez): i = K * Tr^m / t^n_exp. Se omite deliberadamente el
     parámetro de retardo "c" de la forma clásica de 4 parámetros
     (i = K*Tr^m/(t+c)^n) porque, al derivarse analíticamente de un
     único exponente n de Sherman en vez de intensidades observadas,
     no hay información independiente en los datos para identificar
     "c" con confianza -- forzarlo solo agregaría una falsa precisión.
"""
import math
from typing import Dict, List, Tuple

import numpy as np

# Duraciones estándar (minutos) para construir cada curva IDF, de 5 min
# a 24 h -- cubre el rango típico de interés en obras de drenaje urbano
# y de carretera (duraciones cortas) hasta la duración de la serie base
# (P24h, duración larga).
DURACIONES_MIN_DEFAULT: List[float] = [5, 10, 15, 20, 30, 45, 60, 90, 120, 180, 240, 360, 480, 720, 1440]


def intensidad_mm_h(p24_mm: float, duracion_min: float, exponente_n: float = 0.20) -> float:
    """
    Intensidad de diseño (mm/h) para una duración dada, a partir de
    P24h mediante el escalamiento potencial de Sherman (mismo método y
    exponente n que core.design_storm.profundidad_por_duracion).
    """
    if duracion_min <= 0:
        raise ValueError("La duración debe ser mayor que cero.")
    profundidad_mm = p24_mm * ((duracion_min / 1440.0) ** exponente_n)
    duracion_h = duracion_min / 60.0
    return profundidad_mm / duracion_h


def curva_idf_para_tr(p24_mm: float, exponente_n: float = 0.20,
                       duraciones_min: List[float] = None) -> List[Tuple[float, float]]:
    """Lista de (duracion_min, intensidad_mm_h) para un único Tr."""
    duraciones_min = duraciones_min or DURACIONES_MIN_DEFAULT
    return [(d, intensidad_mm_h(p24_mm, d, exponente_n)) for d in duraciones_min]


def tabla_idf(p24_por_tr: Dict[int, float], exponente_n: float = 0.20,
              duraciones_min: List[float] = None) -> Dict[int, List[Tuple[float, float]]]:
    """Curva IDF completa (todas las duraciones) para cada Tr en p24_por_tr."""
    duraciones_min = duraciones_min or DURACIONES_MIN_DEFAULT
    return {tr: curva_idf_para_tr(p24, exponente_n, duraciones_min) for tr, p24 in p24_por_tr.items()}


def _r2(y_obs: np.ndarray, y_pred: np.ndarray) -> float:
    ss_res = float(np.sum((y_obs - y_pred) ** 2))
    ss_tot = float(np.sum((y_obs - np.mean(y_obs)) ** 2))
    if ss_tot <= 0:
        return 1.0  # todos los puntos idénticos: el "ajuste" es exacto por definición
    return 1.0 - ss_res / ss_tot


def ajustar_ecuacion_potencial(duraciones_min: List[float], intensidades_mm_h: List[float]) -> dict:
    """
    Ajusta i = a*t^b (t en minutos) por mínimos cuadrados en escala
    log-log: ln(i) = ln(a) + b*ln(t). Devuelve {'a', 'b', 'r2'}.
    """
    t = np.asarray(duraciones_min, dtype=float)
    i = np.asarray(intensidades_mm_h, dtype=float)
    if t.size < 2:
        raise ValueError("Se necesitan al menos 2 duraciones para ajustar la ecuación potencial.")
    ln_t, ln_i = np.log(t), np.log(i)
    b, ln_a = np.polyfit(ln_t, ln_i, 1)
    a = math.exp(ln_a)
    r2 = _r2(ln_i, ln_a + b * ln_t)
    return {"a": a, "b": float(b), "r2": r2}


def ajustar_idf_combinada(p24_por_tr: Dict[int, float], exponente_n: float = 0.20,
                           duraciones_min: List[float] = None) -> dict:
    """
    Ajusta la ecuación IDF combinada de 3 parámetros i = K*Tr^m/t^n_exp
    (t en minutos, Tr en años) usando TODOS los puntos (Tr, t, i) de
    todas las curvas a la vez, por mínimos cuadrados en escala log-log:

        ln(i) = ln(K) + m*ln(Tr) - n_exp*ln(t)

    Devuelve {'K', 'm', 'n_exp', 'r2', 'ecuacion_texto'}.
    """
    duraciones_min = duraciones_min or DURACIONES_MIN_DEFAULT
    if len(p24_por_tr) < 2:
        raise ValueError("Se necesitan al menos 2 periodos de retorno para ajustar la ecuación combinada.")

    filas_x, filas_y = [], []
    for tr, p24 in p24_por_tr.items():
        for d in duraciones_min:
            i_val = intensidad_mm_h(p24, d, exponente_n)
            filas_x.append([1.0, math.log(tr), math.log(d)])
            filas_y.append(math.log(i_val))

    X = np.array(filas_x)
    y = np.array(filas_y)
    coeficientes, *_ = np.linalg.lstsq(X, y, rcond=None)
    ln_k, m, pendiente_t = coeficientes
    k = math.exp(ln_k)
    n_exp = -pendiente_t
    r2 = _r2(y, X @ coeficientes)

    return {
        "K": float(k), "m": float(m), "n_exp": float(n_exp), "r2": float(r2),
        "ecuacion_texto": f"i = {k:.3f} · Tr^{m:.4f} / t^{n_exp:.4f}  (i en mm/h, t en min, Tr en años)",
    }
