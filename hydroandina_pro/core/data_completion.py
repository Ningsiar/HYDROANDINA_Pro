# -*- coding: utf-8 -*-
"""
core/data_completion.py

Completación de datos faltantes en series hidrometeorológicas (varias
estaciones concurrentes), previo a los análisis de la Pestaña 5.

MÉTODOS:
  - IDW (Inverse Distance Weighting): estima el dato faltante de la
    estación objetivo como el promedio ponderado por 1/distancia^p de
    las estaciones vecinas con dato válido en ese mismo periodo.
  - Regresión Múltiple: ajuste por mínimos cuadrados del valor de la
    estación objetivo en función de las estaciones vecinas (en los
    periodos donde todas tienen dato), usado para predecir los periodos
    faltantes.
  - Random Forest: igual que la regresión múltiple, pero con un modelo
    de bosque aleatorio (no lineal), vía scikit-learn. Requiere
    scikit-learn instalado (se importa de forma perezosa).
  - Vector Regional (método del índice regional, Hiez/Brunet-Moret,
    ampliamente usado en hidrología andina — SENAMHI/IRD): se calcula un
    "vector regional" de índices anuales/mensuales estandarizados a
    partir de todas las estaciones con dato válido en cada periodo, y
    se completa cada estación como (índice_regional_del_periodo *
    desv_estandar_estacion) + media_estacion. Esta es una versión
    SIMPLIFICADA del método clásico (que en su forma completa incluye
    un proceso iterativo de ponderación por calidad de cada estación);
    aquí se pondera cada estación por igual en el vector regional.
  - Selección de predictoras por correlación ("cutoff"): antes de la
    Regresión Múltiple, seleccionar_estaciones_por_correlacion() filtra
    las estaciones vecinas a solo aquellas con correlación >= umbral
    (0.70 por defecto, el mismo criterio usado en la homogeneización de
    2415 estaciones chinas de Wang Qiuxiang et al., 2012) —
    completar_regresion_multiple_seleccionada() aplica este filtro
    automáticamente antes de ajustar la regresión.

TRANSPARENCIA: la completación de datos siempre introduce incertidumbre
adicional; los periodos completados deben marcarse como tales en
cualquier análisis posterior (p.ej. no deberían pesar igual que un dato
observado real en un estudio de diseño definitivo).
"""
import math
from typing import Dict, List, Optional, Tuple

import numpy as np


class DataCompletionError(Exception):
    pass


def _matriz_desde_series(series_estaciones: Dict[str, List[float]]) -> Tuple[List[str], np.ndarray]:
    nombres = list(series_estaciones.keys())
    longitudes = {len(v) for v in series_estaciones.values()}
    if len(longitudes) != 1:
        raise DataCompletionError("Todas las series deben tener la misma longitud (mismos periodos, con NaN donde falte el dato).")
    matriz = np.array([series_estaciones[n] for n in nombres], dtype=float)  # filas=estaciones, columnas=periodos
    return nombres, matriz


def completar_idw(series_estaciones: Dict[str, List[float]], coordenadas: Dict[str, Tuple[float, float]],
                   estacion_objetivo: str, potencia: float = 2.0) -> List[Optional[float]]:
    """
    coordenadas: {nombre_estacion: (x, y)} en un CRS proyectado (metros).
    Devuelve la serie completada de estacion_objetivo (lista, con None
    donde ninguna estación vecina tuviera dato válido en ese periodo).
    """
    if estacion_objetivo not in series_estaciones:
        raise DataCompletionError(f"'{estacion_objetivo}' no está en las series proporcionadas.")
    nombres, matriz = _matriz_desde_series(series_estaciones)
    idx_obj = nombres.index(estacion_objetivo)
    x0, y0 = coordenadas[estacion_objetivo]

    distancias = {}
    for n in nombres:
        if n == estacion_objetivo:
            continue
        x, y = coordenadas[n]
        d = math.hypot(x - x0, y - y0)
        distancias[n] = max(d, 1e-6)

    serie_original = matriz[idx_obj]
    serie_completada = []
    for t in range(matriz.shape[1]):
        valor = serie_original[t]
        if not np.isnan(valor):
            serie_completada.append(float(valor))
            continue
        pesos, valores = [], []
        for i, n in enumerate(nombres):
            if n == estacion_objetivo:
                continue
            v = matriz[i, t]
            if not np.isnan(v):
                pesos.append(1.0 / (distancias[n] ** potencia))
                valores.append(v)
        if valores:
            serie_completada.append(float(np.average(valores, weights=pesos)))
        else:
            serie_completada.append(None)
    return serie_completada


def completar_regresion_multiple(series_estaciones: Dict[str, List[float]], estacion_objetivo: str) -> dict:
    """Regresión lineal múltiple: y (estación objetivo) ~ X (resto de
    estaciones), ajustada por mínimos cuadrados en los periodos donde
    TODAS las estaciones tienen dato, y usada para predecir los periodos
    faltantes de la estación objetivo."""
    nombres, matriz = _matriz_desde_series(series_estaciones)
    idx_obj = nombres.index(estacion_objetivo)
    predictoras = [i for i in range(len(nombres)) if i != idx_obj]
    if not predictoras:
        raise DataCompletionError("Se requiere al menos una estación adicional como predictora.")

    y = matriz[idx_obj]
    X = matriz[predictoras].T  # periodos x n_predictoras
    filas_completas = ~np.isnan(y) & ~np.isnan(X).any(axis=1)
    if filas_completas.sum() < len(predictoras) + 2:
        raise DataCompletionError("No hay suficientes periodos con dato completo en todas las estaciones para ajustar la regresión.")

    X_ajuste = np.column_stack([np.ones(filas_completas.sum()), X[filas_completas]])
    y_ajuste = y[filas_completas]
    coeficientes, _, _, _ = np.linalg.lstsq(X_ajuste, y_ajuste, rcond=None)

    y_pred_todo = coeficientes[0] + X @ coeficientes[1:]
    serie_completada = np.where(np.isnan(y), y_pred_todo, y)
    r2 = _r2(y_ajuste, X_ajuste @ coeficientes)

    return {
        "serie_completada": [None if np.isnan(v) else round(float(v), 2) for v in serie_completada],
        "coeficientes": {"intercepto": round(float(coeficientes[0]), 4),
                          **{nombres[predictoras[i]]: round(float(c), 4) for i, c in enumerate(coeficientes[1:])}},
        "r2_ajuste": round(r2, 4), "n_periodos_ajuste": int(filas_completas.sum()),
    }


def _r2(y_obs, y_pred) -> float:
    ss_res = np.sum((y_obs - y_pred) ** 2)
    ss_tot = np.sum((y_obs - y_obs.mean()) ** 2)
    return 1 - ss_res / ss_tot if ss_tot > 0 else 0.0


def completar_random_forest(series_estaciones: Dict[str, List[float]], estacion_objetivo: str,
                             n_arboles: int = 200, semilla: int = 42) -> dict:
    """Igual que completar_regresion_multiple(), pero con un modelo no
    lineal de bosque aleatorio (RandomForestRegressor de scikit-learn)."""
    try:
        from sklearn.ensemble import RandomForestRegressor
    except ImportError as e:
        raise DataCompletionError(
            "scikit-learn no está instalado en el intérprete de Python de QGIS. Ejecute "
            "'pip install scikit-learn' desde el OSGeo4W Shell (Windows) o el terminal con el "
            "Python de QGIS, y vuelva a intentar."
        ) from e

    nombres, matriz = _matriz_desde_series(series_estaciones)
    idx_obj = nombres.index(estacion_objetivo)
    predictoras = [i for i in range(len(nombres)) if i != idx_obj]
    if not predictoras:
        raise DataCompletionError("Se requiere al menos una estación adicional como predictora.")

    y = matriz[idx_obj]
    X = matriz[predictoras].T
    filas_completas = ~np.isnan(y) & ~np.isnan(X).any(axis=1)
    if filas_completas.sum() < 10:
        raise DataCompletionError("Se recomiendan al menos 10 periodos con dato completo para entrenar el Random Forest.")

    modelo = RandomForestRegressor(n_estimators=n_arboles, random_state=semilla)
    modelo.fit(X[filas_completas], y[filas_completas])
    y_pred_todo = modelo.predict(X)
    serie_completada = np.where(np.isnan(y), y_pred_todo, y)
    r2 = float(modelo.score(X[filas_completas], y[filas_completas]))

    return {
        "serie_completada": [None if np.isnan(v) else round(float(v), 2) for v in serie_completada],
        "importancia_variables": {nombres[predictoras[i]]: round(float(imp), 4)
                                    for i, imp in enumerate(modelo.feature_importances_)},
        "r2_ajuste_entrenamiento": round(r2, 4), "n_periodos_ajuste": int(filas_completas.sum()),
    }


def completar_extender_fourier(serie: List[Optional[float]], periodo: int = 12, n_armonicos: int = 4,
                                n_periodos_extension: int = 0) -> dict:
    """
    Completa los huecos (None/NaN) de una serie periódica (p.ej. mensual,
    periodo=12) ajustando por mínimos cuadrados una serie de Fourier
    truncada:
        x(t) = a0 + sum_{k=1}^{K} [a_k*cos(2*pi*k*t/periodo) + b_k*sin(2*pi*k*t/periodo)]
    usando SOLO los datos válidos, y evalúa el ajuste en todos los
    periodos (incluidos los faltantes). Si n_periodos_extension > 0,
    además extiende la serie hacia adelante ese número de periodos.

    Método estándar de análisis armónico de series climáticas
    periódicas (ampliamente usado para rellenar/extender series
    mensuales de precipitación o temperatura).
    """
    x = np.array([np.nan if v is None else v for v in serie], dtype=float)
    n = len(x)
    if n < 2 * n_armonicos + 2:
        raise DataCompletionError(
            f"Se requieren al menos {2 * n_armonicos + 2} datos para ajustar {n_armonicos} armónicos."
        )
    t = np.arange(n)
    validos = ~np.isnan(x)
    if validos.sum() < 2 * n_armonicos + 2:
        raise DataCompletionError("No hay suficientes datos válidos (no-NaN) para ajustar la serie de Fourier.")

    columnas = [np.ones(n)]
    for k in range(1, n_armonicos + 1):
        columnas.append(np.cos(2 * np.pi * k * t / periodo))
        columnas.append(np.sin(2 * np.pi * k * t / periodo))
    Base = np.column_stack(columnas)

    coeficientes, _, _, _ = np.linalg.lstsq(Base[validos], x[validos], rcond=None)
    ajuste = Base @ coeficientes
    r2 = _r2(x[validos], ajuste[validos])

    serie_completada = np.where(np.isnan(x), ajuste, x)

    extension = []
    if n_periodos_extension > 0:
        t_ext = np.arange(n, n + n_periodos_extension)
        columnas_ext = [np.ones(n_periodos_extension)]
        for k in range(1, n_armonicos + 1):
            columnas_ext.append(np.cos(2 * np.pi * k * t_ext / periodo))
            columnas_ext.append(np.sin(2 * np.pi * k * t_ext / periodo))
        Base_ext = np.column_stack(columnas_ext)
        extension = (Base_ext @ coeficientes).tolist()

    return {
        "serie_completada": [round(float(v), 2) for v in serie_completada],
        "extension": [round(float(v), 2) for v in extension],
        "r2_ajuste_estacional": round(r2, 4),
        "n_armonicos": n_armonicos,
        "nota": ("El ajuste de Fourier captura el ciclo estacional promedio (armónicos de "
                  "periodo/2, periodo/3, ...); no reproduce anomalías interanuales específicas de "
                  "cada hueco, solo el patrón estacional típico."),
    }


def completar_extender_wavelet(serie: List[Optional[float]], wavelet: str = "db4", nivel: Optional[int] = None) -> dict:
    """
    Completa los huecos de una serie mediante un enfoque de suavizado
    por wavelets: 1) rellena un estimado inicial de los huecos por
    interpolación lineal; 2) descompone la serie (transformada wavelet
    discreta) y reconstruye aplicando un umbral suave (soft-threshold
    universal de Donoho-Johnstone) a los coeficientes de detalle,
    obteniendo una versión suavizada multiescala; 3) usa esa
    reconstrucción SOLO en las posiciones originalmente faltantes
    (los datos observados se conservan tal cual).

    TRANSPARENCIA: a diferencia del método de Fourier (estándar y bien
    establecido para relleno estacional), este es un enfoque heurístico
    de suavizado wavelet adaptado para relleno de huecos — no hay un
    único "algoritmo estándar de relleno por wavelets" universalmente
    citado; verifique que el resultado sea físicamente razonable antes
    de usarlo. Requiere PyWavelets ('pip install PyWavelets').
    """
    try:
        import pywt
    except ImportError as e:
        raise DataCompletionError(
            "PyWavelets no está instalado en el intérprete de Python de QGIS. Ejecute "
            "'pip install PyWavelets' desde el OSGeo4W Shell (Windows) o el terminal con el "
            "Python de QGIS, y vuelva a intentar."
        ) from e

    x = np.array([np.nan if v is None else v for v in serie], dtype=float)
    n = len(x)
    faltantes = np.isnan(x)
    if not faltantes.any():
        return {"serie_completada": [round(float(v), 2) for v in x], "nota": "La serie no tiene huecos que completar."}

    indices = np.arange(n)
    x_relleno_inicial = x.copy()
    x_relleno_inicial[faltantes] = np.interp(indices[faltantes], indices[~faltantes], x[~faltantes])

    nivel_max = pywt.dwt_max_level(n, pywt.Wavelet(wavelet).dec_len)
    nivel_usado = min(nivel or nivel_max, nivel_max)
    if nivel_usado < 1:
        raise DataCompletionError("La serie es demasiado corta para descomponerla con este wavelet.")

    coeficientes = pywt.wavedec(x_relleno_inicial, wavelet, level=nivel_usado)
    sigma = np.median(np.abs(coeficientes[-1])) / 0.6745 if len(coeficientes[-1]) else 0.0
    umbral = sigma * math.sqrt(2 * math.log(n)) if sigma > 0 else 0.0
    coeficientes_suavizados = [coeficientes[0]] + [pywt.threshold(c, umbral, mode="soft") for c in coeficientes[1:]]
    reconstruida = pywt.waverec(coeficientes_suavizados, wavelet)[:n]

    serie_completada = x_relleno_inicial.copy()
    serie_completada[faltantes] = reconstruida[faltantes]

    return {
        "serie_completada": [round(float(v), 2) for v in serie_completada],
        "wavelet": wavelet, "nivel_descomposicion": nivel_usado, "umbral_soft": round(float(umbral), 4),
        "nota": ("Enfoque heurístico de suavizado wavelet multiescala (ver docstring); verifique la "
                  "razonabilidad física del resultado, especialmente en huecos largos."),
    }
def completar_vector_regional(series_estaciones: Dict[str, List[float]]) -> dict:
    """
    Vector Regional simplificado (índice regional estandarizado, en el
    espíritu del método de Hiez/Brunet-Moret): para cada periodo t, el
    índice regional I_t es el promedio de los z-scores [(x_i,t -
    media_i)/desv_i] de todas las estaciones con dato válido en t. Cada
    estación se completa como: x_i,t = media_i + I_t * desv_i.

    SIMPLIFICACIÓN respecto al método clásico: se pondera cada estación
    por igual (el método original de Hiez pondera iterativamente por la
    calidad/consistencia de cada estación, un proceso más elaborado que
    no se implementa aquí).
    """
    nombres, matriz = _matriz_desde_series(series_estaciones)
    medias = np.nanmean(matriz, axis=1)
    desvs = np.nanstd(matriz, axis=1, ddof=1)
    if np.any(desvs == 0):
        raise DataCompletionError("Alguna estación tiene desviación estándar nula (serie constante); no se puede estandarizar.")

    z_scores = (matriz - medias[:, None]) / desvs[:, None]
    indice_regional = np.nanmean(z_scores, axis=0)  # promedio por periodo, ignorando NaN

    matriz_completada = matriz.copy()
    for i in range(len(nombres)):
        faltantes = np.isnan(matriz[i])
        matriz_completada[i, faltantes] = medias[i] + indice_regional[faltantes] * desvs[i]

    return {
        "indice_regional_por_periodo": [round(float(v), 3) if not np.isnan(v) else None for v in indice_regional],
        "series_completadas": {
            nombres[i]: [round(float(v), 2) for v in matriz_completada[i]] for i in range(len(nombres))
        },
        "medias_por_estacion": {nombres[i]: round(float(medias[i]), 3) for i in range(len(nombres))},
        "desv_std_por_estacion": {nombres[i]: round(float(desvs[i]), 3) for i in range(len(nombres))},
    }


# ---------------------------------------------------------------------
# Selección de estaciones predictoras por correlación (umbral / "cutoff")
# ---------------------------------------------------------------------
def correlacion_pearson_pares(x: List[float], y: List[float]) -> Tuple[float, int]:
    """Correlación de Pearson entre dos series, usando solo los periodos
    donde AMBAS tienen dato válido (pares completos). Devuelve (r, n_pares);
    r=nan si hay menos de 3 pares válidos."""
    xa = np.asarray(x, dtype=float)
    ya = np.asarray(y, dtype=float)
    if len(xa) != len(ya):
        raise DataCompletionError("Las dos series deben tener la misma longitud.")
    validos = ~np.isnan(xa) & ~np.isnan(ya)
    n_pares = int(validos.sum())
    if n_pares < 3:
        return float("nan"), n_pares
    return float(np.corrcoef(xa[validos], ya[validos])[0, 1]), n_pares


def seleccionar_estaciones_por_correlacion(series_estaciones: Dict[str, List[float]], estacion_objetivo: str,
                                            umbral_correlacion: float = 0.70) -> dict:
    """
    Selecciona, de entre todas las estaciones vecinas disponibles, solo
    aquellas cuya correlación (Pearson, pares completos) con la estación
    objetivo alcanza o supera un umbral -- el mismo criterio del método
    de "cutoff" por correlación (paquete R cutoffR, habitualmente con
    Spearman) y el aplicado en la homogeneización de 2415 estaciones de
    precipitación diaria en China por Wang Qiuxiang et al. (2012), donde
    solo se corrigieron/relacionaron estaciones cuya correlación con su
    referencia superaba 0.70 -- el mismo valor de umbral usado aquí por
    defecto.

    Útil como paso previo a completar_regresion_multiple(): en vez de
    usar TODAS las estaciones vecinas como predictoras (lo que puede
    introducir ruido de estaciones poco relacionadas físicamente, p.ej.
    de otra vertiente o con régimen distinto), se usan solo las que
    demuestran una relación estadística suficientemente fuerte. Ver
    completar_regresion_multiple_seleccionada() para el flujo completo.

    FUENTE: Wang, Q.; Li, Q.; Zhou, H.; Wei, N.; Xing, X.; Wu, S. (2012).
    "Homogeneity Study and Comparison Analysis on Precipitation Series
    over China" [中国降水序列均一性研究及对比分析]. Meteorological
    Monthly, 38(11), 1390-1398.
    """
    if estacion_objetivo not in series_estaciones:
        raise DataCompletionError(f"'{estacion_objetivo}' no está en las series proporcionadas.")
    objetivo = series_estaciones[estacion_objetivo]

    resultados = []
    for nombre, serie in series_estaciones.items():
        if nombre == estacion_objetivo:
            continue
        r, n_pares = correlacion_pearson_pares(objetivo, serie)
        resultados.append({
            "estacion": nombre, "correlacion": round(r, 4) if not math.isnan(r) else None,
            "n_periodos_comunes": n_pares,
            "cumple_umbral": (not math.isnan(r)) and r >= umbral_correlacion,
        })
    resultados.sort(key=lambda d: -(d["correlacion"] if d["correlacion"] is not None else -1))
    seleccionadas = [d["estacion"] for d in resultados if d["cumple_umbral"]]

    return {
        "estacion_objetivo": estacion_objetivo, "umbral_correlacion": umbral_correlacion,
        "estaciones_evaluadas": resultados, "estaciones_seleccionadas": seleccionadas,
        "advertencia": (
            None if seleccionadas else
            f"Ninguna estación vecina alcanza r≥{umbral_correlacion} con '{estacion_objetivo}'; considere "
            "bajar el umbral, agregar estaciones vecinas, o usar un método que no dependa de "
            "predictoras correlacionadas (IDW, Vector Regional, Fourier)."
        ),
    }


def completar_regresion_multiple_seleccionada(series_estaciones: Dict[str, List[float]], estacion_objetivo: str,
                                               umbral_correlacion: float = 0.70) -> dict:
    """
    Combina seleccionar_estaciones_por_correlacion() + completar_regresion_multiple():
    ajusta la regresión múltiple usando SOLO las estaciones vecinas cuya
    correlación con la estación objetivo alcanza el umbral, en vez de
    todas las disponibles (que es lo que hace completar_regresion_multiple()
    por sí sola). Ver seleccionar_estaciones_por_correlacion() para la
    justificación y fuente del umbral por defecto.
    """
    seleccion = seleccionar_estaciones_por_correlacion(series_estaciones, estacion_objetivo, umbral_correlacion)
    if not seleccion["estaciones_seleccionadas"]:
        raise DataCompletionError(seleccion["advertencia"])

    series_filtradas = {estacion_objetivo: series_estaciones[estacion_objetivo]}
    for nombre in seleccion["estaciones_seleccionadas"]:
        series_filtradas[nombre] = series_estaciones[nombre]

    resultado = completar_regresion_multiple(series_filtradas, estacion_objetivo)
    resultado["estaciones_predictoras_usadas"] = seleccion["estaciones_seleccionadas"]
    resultado["umbral_correlacion_aplicado"] = umbral_correlacion
    resultado["correlaciones"] = {
        d["estacion"]: d["correlacion"] for d in seleccion["estaciones_evaluadas"]
        if d["estacion"] in seleccion["estaciones_seleccionadas"]
    }
    return resultado
