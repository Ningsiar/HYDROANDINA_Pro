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


# =====================================================================
# MÉTODOS ALTERNATIVOS DE GENERACIÓN DE CURVAS IDF
# =====================================================================
# El método por defecto de este módulo (escalamiento de Sherman con n
# editable) es genérico. Los tres que siguen son los más usados en la
# práctica peruana y cada uno se apoya en información distinta, así que
# conviene compararlos antes de adoptar uno para diseño.

def idf_dyck_peschke(p24_por_tr: Dict[int, float],
                      duraciones_min: List[float] = None) -> Dict[int, List[Tuple[float, float]]]:
    """
    DYCK Y PESCHKE (1978), también citado como método de Grobe.

        P(d) = P24h * (d / 1440)^0.25          (d en minutos)
        i(d) = P(d) / (d/60)                    [mm/h]

    Es el escalamiento potencial de Sherman con el exponente FIJADO en
    0.25, valor que Dyck y Peschke propusieron para lluvias de duración
    menor a 24 h. Su ventaja es que no exige calibrar nada: se aplica
    directamente sobre la P24h del análisis de frecuencia. Su limitación
    es la misma: al ser un exponente único y fijo, no distingue el
    régimen pluviográfico de una región de otra.

    Se implementa aparte de intensidad_mm_h() -- en vez de llamarla con
    exponente_n=0.25 -- para que quede explícito en los resultados QUÉ
    método se usó, y para que un cambio futuro del valor por defecto de
    Sherman no altere en silencio las curvas de Dyck-Peschke.
    """
    duraciones_min = duraciones_min or DURACIONES_MIN_DEFAULT
    salida = {}
    for tr, p24 in p24_por_tr.items():
        puntos = []
        for d in duraciones_min:
            if d <= 0:
                raise ValueError("Las duraciones deben ser mayores que cero.")
            profundidad = p24 * ((d / 1440.0) ** 0.25)
            puntos.append((d, profundidad / (d / 60.0)))
        salida[tr] = puntos
    return salida


# Rango de validez declarado por Bell (1969) para su relación.
BELL_DURACION_MIN_VALIDA = 5.0     # minutos
BELL_DURACION_MAX_VALIDA = 120.0   # minutos
BELL_TR_MIN_VALIDO = 2.0           # años
BELL_TR_MAX_VALIDO = 100.0         # años


def p60_10_desde_p24(p24_10_anios: float) -> float:
    """
    Estima la lluvia de 60 min y 10 años de periodo de retorno -- el
    valor de referencia que exige Bell -- a partir de la P24h de 10 años,
    aplicando el escalamiento de Dyck-Peschke:
        P(60min) = P24h * (60/1440)^0.25 = P24h * 0.4518
    El factor resultante (0.45) es coherente con el 0.4 que suele citarse
    en la práctica peruana para esta conversión. Es una ESTIMACIÓN: si se
    dispone de un pluviograma o de una curva IDF regional que dé
    directamente P(60min,10años), debe preferirse ese valor.
    """
    if p24_10_anios <= 0:
        raise ValueError("La P24h de 10 años debe ser mayor que cero.")
    return p24_10_anios * ((60.0 / 1440.0) ** 0.25)


def idf_bell(p60_10_mm: float, periodos_retorno: List[int],
             duraciones_min: List[float] = None) -> dict:
    """
    FREDERICH BELL (1969) — relación generalizada de precipitación:

        P(t,T) = (0.21*ln(T) + 0.52) * (0.54*t^0.25 - 0.50) * P(60min,10años)

    con t en MINUTOS y T en AÑOS. Bell la dedujo de registros de lluvias
    convectivas de varias regiones del mundo y la validó para
    t = 5 a 120 min y T = 2 a 100 años; fuera de ese rango se extrapola y
    este módulo lo ADVIERTE en vez de callarlo, porque el segundo factor
    se anula alrededor de t = 2.7 min y por debajo de eso daría láminas
    negativas, sin sentido físico.

    Devuelve dict con 'curvas' {tr: [(d, i_mm_h)]}, el P60,10 usado y las
    advertencias de rango.
    """
    duraciones_min = duraciones_min or DURACIONES_MIN_DEFAULT
    if p60_10_mm <= 0:
        raise ValueError("P(60min, 10 años) debe ser mayor que cero.")

    advertencias = []
    fuera_dur = [d for d in duraciones_min
                 if d < BELL_DURACION_MIN_VALIDA or d > BELL_DURACION_MAX_VALIDA]
    if fuera_dur:
        advertencias.append(
            f"Duraciones fuera del rango validado por Bell (5-120 min): "
            f"{', '.join(f'{d:g}' for d in fuera_dur)} min. Los valores para esas duraciones son una "
            "extrapolación; para duraciones largas prefiera Dyck-Peschke o IILA-SENAMHI."
        )
    fuera_tr = [tr for tr in periodos_retorno
                if tr < BELL_TR_MIN_VALIDO or tr > BELL_TR_MAX_VALIDO]
    if fuera_tr:
        advertencias.append(
            f"Periodos de retorno fuera del rango validado por Bell (2-100 años): "
            f"{', '.join(str(t) for t in fuera_tr)} años. Extrapolación."
        )

    curvas = {}
    for tr in periodos_retorno:
        if tr <= 1:
            raise ValueError("El periodo de retorno debe ser mayor que 1 año.")
        factor_tr = 0.21 * math.log(tr) + 0.52
        puntos = []
        for d in duraciones_min:
            factor_dur = 0.54 * (d ** 0.25) - 0.50
            if factor_dur <= 0:
                # Por debajo de ~2.7 min el factor se vuelve negativo: se
                # omite el punto en vez de devolver una lámina negativa.
                continue
            profundidad = factor_tr * factor_dur * p60_10_mm
            puntos.append((d, profundidad / (d / 60.0)))
        curvas[tr] = puntos

    return {"curvas": curvas, "P60_10_mm": round(p60_10_mm, 3), "advertencias": advertencias}


def idf_iila_senamhi(parametro_a: float, parametro_k: float, parametro_b: float,
                      parametro_n: float, periodos_retorno: List[int],
                      duraciones_min: List[float] = None) -> dict:
    """
    IILA-SENAMHI-UNI (1983), "Estudio de la Hidrología del Perú":

        t < 3 h:   P(t,T) = a * (1 + K*log10(T)) * (t + b)^n
        t >= 3 h:  P(t,T) = a * (1 + K*log10(T)) * t^n

    con t en HORAS, P en mm y T en años. El cambio de expresión en las 3
    horas es parte del modelo original: el término b amortigua la
    singularidad de las duraciones cortas y deja de aplicarse a partir de
    ese umbral.

    LOS PARÁMETROS a, K, b y n SON REGIONALES: el estudio los tabula por
    subzona pluviométrica del Perú. Este módulo NO los incorpora ni los
    supone -- deben tomarse de la publicación IILA-SENAMHI para la
    subzona donde está la cuenca, o de un estudio regional equivalente.
    Inventarlos daría curvas de aspecto creíble pero sin ningún respaldo,
    y es justamente el tipo de error que no se detecta al revisar un
    informe.

    Devuelve dict con 'curvas' {tr: [(d, i_mm_h)]} y los parámetros usados.
    """
    duraciones_min = duraciones_min or DURACIONES_MIN_DEFAULT
    if parametro_a <= 0:
        raise ValueError("El parámetro a de IILA-SENAMHI debe ser mayor que cero.")
    if parametro_b < 0:
        raise ValueError("El parámetro b de IILA-SENAMHI no puede ser negativo.")

    curvas = {}
    for tr in periodos_retorno:
        if tr <= 0:
            raise ValueError("El periodo de retorno debe ser mayor que cero.")
        factor_tr = parametro_a * (1.0 + parametro_k * math.log10(tr))
        puntos = []
        for d_min in duraciones_min:
            t_h = d_min / 60.0
            if t_h < 3.0:
                profundidad = factor_tr * ((t_h + parametro_b) ** parametro_n)
            else:
                profundidad = factor_tr * (t_h ** parametro_n)
            puntos.append((d_min, profundidad / t_h))
        curvas[tr] = puntos

    return {
        "curvas": curvas,
        "parametros": {"a": parametro_a, "K": parametro_k, "b": parametro_b, "n": parametro_n},
        "nota": ("Los parámetros a, K, b y n son REGIONALES: tómelos de la publicación IILA-SENAMHI "
                 "para la subzona pluviométrica de su cuenca. El plugin no los supone."),
    }


def comparar_metodos_idf(p24_por_tr: Dict[int, float], exponente_sherman: float = 0.20,
                          p60_10_mm: float = None, parametros_iila: dict = None,
                          duraciones_min: List[float] = None) -> dict:
    """
    Genera las curvas IDF por todos los métodos disponibles sobre los
    mismos datos, para poder compararlas. Los métodos que requieren
    información adicional (Bell necesita P60,10; IILA necesita los
    parámetros regionales) se omiten si no se proporciona, en vez de
    inventar valores.
    """
    duraciones_min = duraciones_min or DURACIONES_MIN_DEFAULT
    periodos = sorted(p24_por_tr.keys())
    resultados = {
        "sherman": {
            "nombre": f"Sherman genérico (n={exponente_sherman})",
            "curvas": tabla_idf(p24_por_tr, exponente_sherman, duraciones_min),
        },
        "dyck_peschke": {
            "nombre": "Dyck y Peschke / Grobe (n=0.25)",
            "curvas": idf_dyck_peschke(p24_por_tr, duraciones_min),
        },
    }
    if p60_10_mm:
        bell = idf_bell(p60_10_mm, periodos, duraciones_min)
        resultados["bell"] = {
            "nombre": "Frederich Bell (1969)", "curvas": bell["curvas"],
            "advertencias": bell["advertencias"], "P60_10_mm": bell["P60_10_mm"],
        }
    if parametros_iila:
        iila = idf_iila_senamhi(periodos_retorno=periodos, duraciones_min=duraciones_min,
                                 **parametros_iila)
        resultados["iila"] = {
            "nombre": "IILA-SENAMHI-UNI (1983)", "curvas": iila["curvas"],
            "parametros": iila["parametros"], "nota": iila["nota"],
        }
    return resultados


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
