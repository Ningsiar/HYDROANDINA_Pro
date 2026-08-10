# -*- coding: utf-8 -*-
"""
core/design_storm.py

Genera un hietograma de diseño (bloques alternos) a partir de la
precipitación máxima 24h de un periodo de retorno dado, para alimentar
directamente el motor de hidrogramas unitarios (core/unit_hydrographs.py)
sin que el usuario tenga que teclear el hietograma a mano.

MÉTODO DE DESAGREGACIÓN (documentado explícitamente, léase antes de usar
en diseño definitivo): al no disponerse aquí de una curva Intensidad-
Duración-Frecuencia (IDF) local calibrada para el punto de interés, la
lámina de duración d se estima mediante un escalamiento potencial
estándar del tipo Sherman:

    P(d) = P24h * (d / 1440min)^n

con n editable (por defecto 0.20, dentro del rango típico 0.15-0.30
reportado para relaciones profundidad-duración en curvas IDF). Esta es
una SIMPLIFICACIÓN explícita, no una curva IDF real de la zona; si se
dispone de una curva IDF de SENAMHI/ANA para la subcuenca del río
Cachimayo, debe preferirse esa fuente y no este escalamiento genérico
para un diseño definitivo. Como alternativa, ver core/scs_storm_patterns.py
para desagregar usando los patrones adimensionales SCS Tipo I/II/III.

Una vez obtenidas las láminas P(d) para cada duración múltiplo de Dt
hasta la duración total de la tormenta, se aplica el método de bloques
alternos estándar (Chow, Maidment & Mays, 1988): se calculan las
láminas incrementales, se ordenan de mayor a menor, y se intercalan
alrededor del bloque central (el mayor incremento se ubica al centro).
"""
from typing import List


def profundidad_por_duracion(p24_mm: float, duracion_min: float, exponente_n: float = 0.20) -> float:
    """P(d) = P24h * (d/1440)^n, d en minutos."""
    return p24_mm * ((duracion_min / 1440.0) ** exponente_n)


def bloques_alternos(p24_mm: float, duracion_total_h: float, dt_h: float,
                      exponente_n: float = 0.20) -> List[float]:
    """
    Genera el hietograma de diseño (lista de incrementos de lluvia TOTAL
    en mm, uno por intervalo Dt) mediante el método de bloques alternos.

    duracion_total_h: duración total de la tormenta de diseño (h). Un
        valor de referencia razonable es 2-4 veces el tiempo de
        concentración de la cuenca (criterio práctico habitual; ajústelo
        según el criterio del proyecto).
    dt_h: duración del intervalo de cálculo (h).
    """
    n_intervalos = int(round(duracion_total_h / dt_h))
    if n_intervalos < 1:
        raise ValueError("duracion_total_h debe ser mayor o igual a dt_h.")

    profundidades_acumuladas = [
        profundidad_por_duracion(p24_mm, (i + 1) * dt_h * 60.0, exponente_n)
        for i in range(n_intervalos)
    ]

    incrementos = [profundidades_acumuladas[0]] + [
        profundidades_acumuladas[i] - profundidades_acumuladas[i - 1] for i in range(1, n_intervalos)
    ]

    incrementos_ordenados = sorted(incrementos, reverse=True)
    hietograma = [0.0] * n_intervalos
    centro = n_intervalos // 2
    izquierda = centro - 1
    derecha = centro
    alternar_derecha = True

    for valor in incrementos_ordenados:
        if alternar_derecha and derecha < n_intervalos:
            hietograma[derecha] = valor
            derecha += 1
        elif not alternar_derecha and izquierda >= 0:
            hietograma[izquierda] = valor
            izquierda -= 1
        elif derecha < n_intervalos:
            hietograma[derecha] = valor
            derecha += 1
        elif izquierda >= 0:
            hietograma[izquierda] = valor
            izquierda -= 1
        alternar_derecha = not alternar_derecha

    return hietograma
