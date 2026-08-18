# -*- coding: utf-8 -*-
"""
core/regionalization.py

Regionalización de variables hidrometeorológicas (precipitación,
temperatura) en función de covariables geográficas/fisiográficas
(altitud, latitud, longitud) medidas en un conjunto de estaciones, para
extender/interpolar la variable a puntos sin medición directa (p.ej. el
centroide de una subcuenca, o una grilla derivada del MDE).

MÉTODO:
  1. correlacion_con_covariable(): correlación y significancia de la
     variable vs. una covariable geográfica en las estaciones con dato.
  2. regresion_regionalizacion(): regresión (simple o múltiple) de la
     variable vs. las covariables provistas, con IC 95% y residuos.
  3. predecir_en_puntos(): aplica el modelo ajustado a puntos nuevos.
  4. regionalizar_con_correccion_residual(): además de la tendencia de
     regresión, corrige localmente con IDW de los residuos en las
     estaciones más cercanas a cada punto nuevo -- una aproximación
     práctica al co-kriging (regresión + kriging de residuos) que no
     requiere ajustar un variograma.

FUENTES (deliberadamente no limitadas a bibliografía estadounidense o
europea, por instrucción del proyecto):
  - Naoum, S.; Tsanis, I.K. (2004). "Orographic Precipitation Modeling
    with Multiple Linear Regression". J. Hydrologic Engineering, 9(2),
    79-102. Regresión múltiple precipitación ~ altitud+latitud+longitud
    en la isla de Creta -- la misma estructura de modelo que se
    implementa en regresion_regionalizacion().
  - Vinogradov, Yu.B. "Hydrology of Sloping Terrain", capítulo de la
    Enciclopedia UNESCO-EOLSS de Hidrología (autor ruso): discute la
    relación altitud-precipitación en cuencas de montaña y advierte que
    NO es universal ni siempre monótona (efecto de barlovento/sotavento,
    "medida orográfica" en función del recorrido de las masas de aire) --
    advertencia trasladada al resultado de correlacion_con_covariable().
  - Análisis de métodos de interpolación de precipitación para la
    República de Bashkortostan, Federación Rusa (WSEAS Transactions on
    Environment and Development, 2014): compara IDW, kriging ordinario,
    geo-regresión y co-kriging; encuentra que geo-regresión + kriging de
    los residuos supera tanto a la regresión sola como al IDW solo en
    terreno complejo -- es la base de
    regionalizar_con_correccion_residual().
  - Živković, N. "Altitude precipitation gradient in Serbia": ejemplo de
    zonificación en regiones homogéneas antes de ajustar el gradiente
    altitud-precipitación (ver advertencia en regresion_regionalizacion()
    cuando R² es bajo).

TRANSPARENCIA: la relación variable~altitud NO es universal ni siempre
lineal; un R² bajo indica que la cuenca puede requerir dividirse en
zonas climáticamente más homogéneas (p.ej. por vertiente) antes de
regionalizar, no que el método esté mal aplicado.
"""
import math
from typing import Dict, List, Optional, Tuple

import numpy as np


class RegionalizationError(Exception):
    pass


def _cdf_normal_estandar(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _cdf_t_student(t: float, gl: float) -> float:
    """CDF de la t de Student vía la función beta incompleta
    regularizada. Implementación autocontenida (duplicada de la
    equivalente en core/quality_control.py) para que este módulo no
    dependa de otro módulo del plugin."""
    if gl <= 0:
        return 0.5
    x = gl / (gl + t ** 2)
    ib = _beta_incompleta_regularizada(x, gl / 2.0, 0.5)
    return 1 - 0.5 * ib if t > 0 else 0.5 * ib


def _beta_incompleta_regularizada(x: float, a: float, b: float, iter_max: int = 200, eps: float = 1e-10) -> float:
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    frente = math.exp(lbeta + a * math.log(x) + b * math.log(1 - x))
    if x < (a + 1) / (a + b + 2):
        return frente * _cf_beta(x, a, b, iter_max, eps) / a
    else:
        return 1.0 - frente * _cf_beta(1 - x, b, a, iter_max, eps) / b


def _cf_beta(x, a, b, iter_max, eps):
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, iter_max + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d, c = 1.0 / d, c
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def _t_critico_aprox(gl: float, alpha: float = 0.05) -> float:
    """t crítico (dos colas) aproximado para el IC 95%, por búsqueda
    binaria sobre la CDF t ya implementada arriba (evita depender de
    scipy.stats.t.ppf, no garantizado en el intérprete de QGIS)."""
    objetivo = 1 - alpha / 2
    lo, hi = 0.0, 50.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if _cdf_t_student(mid, gl) < objetivo:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def correlacion_con_covariable(valores: List[float], covariable: List[float]) -> dict:
    """
    Correlación de Pearson entre la variable (p.ej. precipitación o
    temperatura media anual por estación) y una covariable geográfica
    (p.ej. altitud), con su significancia (t de Student), siguiendo el
    mismo procedimiento que un cor.test() de dos variables continuas.
    """
    x = np.asarray(valores, dtype=float)
    h = np.asarray(covariable, dtype=float)
    if len(x) != len(h):
        raise RegionalizationError("'valores' y 'covariable' deben tener la misma longitud (una por estación).")
    n = len(x)
    if n < 4:
        raise RegionalizationError("Se requieren al menos 4 estaciones para evaluar la correlación con la covariable.")
    if np.std(x) == 0 or np.std(h) == 0:
        raise RegionalizationError("La variable o la covariable no tienen variabilidad (desviación estándar nula).")

    r = float(np.corrcoef(x, h)[0, 1])
    t_stat = r * math.sqrt((n - 2) / max(1e-12, 1 - r ** 2))
    p_valor = 2 * (1 - _cdf_t_student(abs(t_stat), n - 2))

    return {
        "r": round(r, 4), "r2": round(r ** 2, 4), "t": round(t_stat, 3), "p_valor": round(p_valor, 4),
        "significativa_alpha_0_05": p_valor < 0.05, "n_estaciones": n,
        "advertencia": (
            "La relación variable-altitud (u otra covariable geográfica) no es universal: puede "
            "invertirse por efecto de barlovento/sotavento, inversión térmica, o cambiar de signo "
            "entre vertientes de una misma cuenca. Un |r| bajo o no significativo sugiere dividir las "
            "estaciones en subregiones más homogéneas (p.ej. por vertiente) antes de regionalizar, no "
            "descartar el método (Vinogradov, EOLSS 'Hydrology of Sloping Terrain')."
        ),
    }


def regresion_regionalizacion(valores: List[float], covariables: Dict[str, List[float]],
                               nombres_estaciones: Optional[List[str]] = None) -> dict:
    """
    Regresión lineal (simple si covariables tiene 1 entrada, múltiple si
    tiene más) de la variable en función de las covariables geográficas
    provistas (p.ej. {'altitud': [...], 'latitud': [...]}), ajustada por
    mínimos cuadrados sobre las estaciones con dato disponible.

    Devuelve coeficientes con intervalo de confianza al 95%, R², y el
    residuo estandarizado de cada estación (para diagnóstico: residuos
    muy heterogéneos indican que el modelo no debería usarse para
    predecir sin antes revisar subregiones -- ver docstring del módulo).

    FUENTE: estructura de modelo de Naoum & Tsanis (2004) para
    precipitación ~ altitud + latitud + longitud (isla de Creta).
    """
    y = np.asarray(valores, dtype=float)
    n = len(y)
    nombres_cov = list(covariables.keys())
    if not nombres_cov:
        raise RegionalizationError("Debe proveer al menos una covariable (p.ej. 'altitud').")
    columnas = []
    for nombre in nombres_cov:
        col = np.asarray(covariables[nombre], dtype=float)
        if len(col) != n:
            raise RegionalizationError(f"La covariable '{nombre}' tiene una longitud distinta a 'valores'.")
        columnas.append(col)
    X = np.column_stack(columnas)
    k = X.shape[1]
    if n < k + 3:
        raise RegionalizationError(f"Se requieren al menos {k + 3} estaciones para ajustar {k} covariable(s) con confianza mínima.")

    X_diseno = np.column_stack([np.ones(n), X])
    coeficientes, _, _, _ = np.linalg.lstsq(X_diseno, y, rcond=None)
    y_pred = X_diseno @ coeficientes
    residuos = y - y_pred

    ss_res = float(np.sum(residuos ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    gl = n - k - 1
    if gl < 1:
        raise RegionalizationError("Grados de libertad insuficientes para estimar la incertidumbre del modelo.")
    s2 = ss_res / gl
    try:
        cov_beta = s2 * np.linalg.inv(X_diseno.T @ X_diseno)
    except np.linalg.LinAlgError:
        raise RegionalizationError(
            "Las covariables están perfectamente correlacionadas entre sí (matriz singular); "
            "elimine alguna covariable redundante."
        )
    errores_std = np.sqrt(np.clip(np.diag(cov_beta), 0, None))
    t_critico = _t_critico_aprox(gl)

    nombres_coef = ["intercepto"] + nombres_cov
    tabla_coeficientes = [{
        "termino": nombre, "coeficiente": round(float(coeficientes[i]), 6),
        "error_std": round(float(errores_std[i]), 6),
        "ic_95_inferior": round(float(coeficientes[i] - t_critico * errores_std[i]), 6),
        "ic_95_superior": round(float(coeficientes[i] + t_critico * errores_std[i]), 6),
    } for i, nombre in enumerate(nombres_coef)]

    desv_residuos = float(np.std(residuos, ddof=k + 1)) if gl > 0 else float("nan")
    residuos_estandarizados = (residuos / desv_residuos) if desv_residuos > 0 else np.full(n, np.nan)

    etiquetas = nombres_estaciones if nombres_estaciones else [f"estacion_{i + 1}" for i in range(n)]
    if len(etiquetas) != n:
        raise RegionalizationError("'nombres_estaciones' debe tener la misma longitud que 'valores'.")

    return {
        "covariables_usadas": nombres_cov, "n_estaciones": n, "r2": round(r2, 4),
        "coeficientes": tabla_coeficientes,
        "residuos": {
            etiquetas[i]: {
                "observado": round(float(y[i]), 3), "predicho": round(float(y_pred[i]), 3),
                "residuo": round(float(residuos[i]), 3),
                "residuo_estandarizado": (round(float(residuos_estandarizados[i]), 3)
                                           if not np.isnan(residuos_estandarizados[i]) else None),
            } for i in range(n)
        },
        "_coeficientes_array": coeficientes.tolist(),
        "nota_r2": (
            "R² alto (tendencia regional bien explicada por las covariables geográficas)." if r2 >= 0.5 else
            "R² bajo: las covariables geográficas explican poco de la variabilidad entre estaciones; "
            "considere dividir en subregiones más homogéneas antes de usar este modelo para predecir "
            "en puntos sin medición (ver advertencia de correlacion_con_covariable())."
        ),
    }


def predecir_en_puntos(modelo: dict, covariables_puntos: Dict[str, List[float]]) -> List[float]:
    """
    Aplica un modelo ya ajustado por regresion_regionalizacion() a un
    conjunto nuevo de puntos (p.ej. centroides de subcuencas, o una
    grilla de altitud/latitud derivada del MDE), devolviendo el valor
    regionalizado según la TENDENCIA de la regresión únicamente (sin
    corrección de residuos -- ver regionalizar_con_correccion_residual()
    para incluirla).
    """
    coeficientes = modelo.get("_coeficientes_array")
    covariables_usadas = modelo.get("covariables_usadas")
    if coeficientes is None or covariables_usadas is None:
        raise RegionalizationError("'modelo' debe ser el resultado de regresion_regionalizacion().")
    faltantes = [c for c in covariables_usadas if c not in covariables_puntos]
    if faltantes:
        raise RegionalizationError(f"Faltan covariables en 'covariables_puntos': {faltantes}")

    n_puntos = len(next(iter(covariables_puntos.values())))
    X = np.column_stack([np.asarray(covariables_puntos[c], dtype=float) for c in covariables_usadas])
    if X.shape[0] != n_puntos:
        raise RegionalizationError("Todas las covariables de 'covariables_puntos' deben tener la misma longitud.")
    X_diseno = np.column_stack([np.ones(n_puntos), X])
    y_pred = X_diseno @ np.asarray(coeficientes)
    return [round(float(v), 3) for v in y_pred]


def regionalizar_con_correccion_residual(valores: List[float], covariables: Dict[str, List[float]],
                                          coordenadas_estaciones: Dict[str, Tuple[float, float]],
                                          nombres_estaciones: List[str],
                                          covariables_puntos: Dict[str, List[float]],
                                          coordenadas_puntos: List[Tuple[float, float]],
                                          potencia_idw: float = 2.0) -> dict:
    """
    Regionalización en dos pasos ("geo-regresión + corrección residual
    por IDW"), una aproximación práctica al co-kriging que no requiere
    ajustar un variograma:

      1. Ajusta la tendencia regional (regresion_regionalizacion) y la
         evalúa en los puntos nuevos (predecir_en_puntos).
      2. Interpola por IDW (1/distancia^potencia) los RESIDUOS de la
         regresión en las estaciones, y los suma a la tendencia del
         paso 1 en cada punto nuevo -- capturando la variabilidad local
         que la tendencia regional (altitud/latitud) no explica.

    coordenadas_estaciones/coordenadas_puntos: {nombre: (x, y)} y lista
    de (x, y) respectivamente, en un CRS proyectado (metros).

    FUENTE del enfoque: comparación de métodos de interpolación de
    precipitación para la República de Bashkortostan, Federación Rusa
    (WSEAS Transactions on Environment and Development, 2014), donde
    geo-regresión + kriging de residuos superó a la regresión sola y al
    IDW solo en terreno de montaña; y Naoum & Tsanis (2004) para el caso
    de solo-regresión sin corrección de residuos.
    """
    modelo = regresion_regionalizacion(valores, covariables, nombres_estaciones)

    residuos_por_estacion = {
        nombre: modelo["residuos"][nombre]["residuo"] for nombre in nombres_estaciones
    }
    for nombre in nombres_estaciones:
        if nombre not in coordenadas_estaciones:
            raise RegionalizationError(f"Falta la coordenada de la estación '{nombre}' en 'coordenadas_estaciones'.")

    tendencia_puntos = predecir_en_puntos(modelo, covariables_puntos)
    if len(tendencia_puntos) != len(coordenadas_puntos):
        raise RegionalizationError("'covariables_puntos' y 'coordenadas_puntos' deben describir el mismo número de puntos.")

    resultados = []
    for idx_punto, (px, py) in enumerate(coordenadas_puntos):
        pesos, valores_residuo = [], []
        for nombre in nombres_estaciones:
            ex, ey = coordenadas_estaciones[nombre]
            d = math.hypot(px - ex, py - ey)
            pesos.append(1.0 / (max(d, 1e-6) ** potencia_idw))
            valores_residuo.append(residuos_por_estacion[nombre])
        residuo_interpolado = float(np.average(valores_residuo, weights=pesos))
        resultados.append({
            "tendencia_regresion": tendencia_puntos[idx_punto],
            "correccion_residual_idw": round(residuo_interpolado, 3),
            "valor_regionalizado": round(tendencia_puntos[idx_punto] + residuo_interpolado, 3),
        })

    return {
        "modelo_tendencia": {k: v for k, v in modelo.items() if not k.startswith("_")},
        "resultados_por_punto": resultados,
        "nota": (
            "El 'valor_regionalizado' combina la tendencia regional (regresión con las covariables "
            "geográficas) con la corrección local por IDW de los residuos en las estaciones -- análogo "
            "práctico a un co-kriging simplificado, sin ajuste de variograma."
        ),
    }
