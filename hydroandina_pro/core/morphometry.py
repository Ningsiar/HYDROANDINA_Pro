# -*- coding: utf-8 -*-
"""
core/morphometry.py

Implementa los 6 grupos de parámetros morfométricos e hidrológicos
especificados. Son funciones puras (reciben números/arrays, devuelven
diccionarios de resultados) para que sean testeables sin necesidad de
un proyecto QGIS abierto.

NOTA IMPORTANTE DE TRANSPARENCIA (léase antes de usar en producción):
Dos ecuaciones de la especificación original tenían una inconsistencia
de unidades que corregimos aquí; se documenta en cada función afectada:

  1. Kirpich (1940): la especificación pedía
         Tc = 0.0078 * (Lc_km*1000)^0.77 * Se^-0.385
     pero el coeficiente 0.0078 corresponde a la versión de Kirpich con
     L en PIES, no en metros. Si se aplica 0.0078 a metros, Tc queda
     sobrestimado en un factor de ~3.6x. Aquí se implementa la versión
     métrica estándar (Chow, Maidment & Mays, 1988; y la misma que
     usamos para la subcuenca Acomayo): Tc[min] = 0.01947 * L[m]^0.77
     * S[m/m]^-0.385. Se deja también la variante literal del prompt
     disponible bajo el nombre 'kirpich_prompt_literal' por si se
     requiere reproducir exactamente lo solicitado.

  2. SCS Lag (USDA-NRCS): la especificación escribe (S_mm + 1)^0.7,
     pero la fórmula original de retención potencial S debe expresarse
     en PULGADAS dentro de esa ecuación (no en milímetros). Aquí se
     recibe S en mm (como lo entrega el módulo de número de curva) y se
     convierte internamente a pulgadas antes de aplicar la fórmula.

Estas correcciones se hacen porque el plugin alimenta directamente el
dimensionamiento de obras de protección contra inundaciones; un Tc mal
escalado afecta el caudal de diseño en HEC-HMS aguas abajo.
"""
import math
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple

import numpy as np


# ---------------------------------------------------------------------
# GRUPO 1: Parámetros básicos
# ---------------------------------------------------------------------
def grupo1_basicos(area_m2: float, perimetro_m: float, lb_m: float,
                    z_max: float, z_min: float, z_array: np.ndarray) -> dict:
    """
    area_m2, perimetro_m, lb_m: geometría de la cuenca (Lb = eje mayor del
        minimum rotated bounding box).
    z_array: array 1D de elevaciones del MDE dentro de la cuenca (sin
        nodata), para media y mediana.
    """
    area_km2 = area_m2 / 1e6
    perimetro_km = perimetro_m / 1000.0
    lb_km = lb_m / 1000.0
    b_km = area_km2 / lb_km if lb_km > 0 else float("nan")
    z_med = float(np.mean(z_array)) if z_array.size else float("nan")
    z_50 = float(np.percentile(z_array, 50)) if z_array.size else float("nan")
    h = z_max - z_min

    return {
        "A": round(area_km2, 3), "P": round(perimetro_km, 3), "Lb": round(lb_km, 3),
        "B": round(b_km, 3), "Zmax": round(z_max, 3), "Zmin": round(z_min, 3),
        "Zmed": round(z_med, 3), "Z50": round(z_50, 3), "H": round(h, 3),
    }


# ---------------------------------------------------------------------
# GRUPO 2: Índices de forma
# ---------------------------------------------------------------------
def grupo2_forma(area_km2: float, lb_km: float, perimetro_km: float,
                  lc_km: float, lt_km: float) -> dict:
    ff = area_km2 / (lb_km ** 2) if lb_km > 0 else float("nan")
    re = (2.0 / math.sqrt(math.pi)) * (math.sqrt(area_km2) / lb_km) if lb_km > 0 else float("nan")
    rc = (4.0 * math.pi * area_km2) / (perimetro_km ** 2) if perimetro_km > 0 else float("nan")
    kc = 0.28 * (perimetro_km / math.sqrt(area_km2)) if area_km2 > 0 else float("nan")
    rf = lc_km / perimetro_km if perimetro_km > 0 else float("nan")
    isi = lc_km / lb_km if lb_km > 0 else float("nan")
    sc = area_km2 / (lt_km * lc_km) if (lt_km and lc_km) else float("nan")

    interpretacion = []
    interpretacion.append("Cuenca alargada" if ff < 0.45 else "Cuenca no alargada (Ff)")
    if 0.50 <= re < 0.70:
        interpretacion.append("Cuenca oblonga (Re)")
    elif re < 0.50:
        interpretacion.append("Cuenca muy alargada (Re)")
    else:
        interpretacion.append("Cuenca circular a oval (Re)")
    interpretacion.append("Cuenca muy alargada (Rc << 1)" if rc < 0.4 else "Cuenca con forma cercana a circular (Rc)")
    interpretacion.append("Cuenca rectangular-oblonga (Kc > 1.75)" if kc > 1.75 else "Cuenca de forma más compacta (Kc <= 1.75)")
    interpretacion.append("Cauce sinuoso (IS > 1.3)" if isi > 1.3 else "Cauce de baja sinuosidad (IS <= 1.3)")

    return {
        "Ff": round(ff, 3), "Re": round(re, 3), "Rc": round(rc, 3), "Kc": round(kc, 3),
        "Rf": round(rf, 3), "IS": round(isi, 3), "Sc": round(sc, 3),
        "interpretacion": interpretacion,
    }


# ---------------------------------------------------------------------
# GRUPO 3: Parámetros del cauce principal
# ---------------------------------------------------------------------
@dataclass
class TramoCauce:
    """Un tramo del perfil longitudinal del cauce principal, para el
    cálculo de la pendiente compensada de Taylor-Schwartz."""
    longitud_m: float
    pendiente_m_m: float  # debe ser > 0


def grupo3_cauce_principal(lc_km: float, z_inicio: float, z_fin: float,
                            perfil_distancias_m: np.ndarray, perfil_elevaciones_m: np.ndarray,
                            tramos: Optional[List[TramoCauce]] = None) -> dict:
    """
    perfil_distancias_m / perfil_elevaciones_m: muestreo del perfil
        longitudinal del cauce (p.ej. cada 10-50 m), ordenado desde el
        punto de salida (distancia 0) hasta la naciente.
    tramos: lista de TramoCauce si ya se dispone de la segmentación por
        tramos homogéneos; si no se provee, se deriva automáticamente
        del perfil muestreado dividiéndolo en 10 tramos iguales.
    """
    hc = z_inicio - z_fin
    se = hc / (lc_km * 1000.0) if lc_km > 0 else float("nan")

    # --- pendiente 10-85 (compatible HEC-HMS) ---
    dist_total = perfil_distancias_m[-1] if perfil_distancias_m.size else lc_km * 1000.0
    d10 = 0.10 * dist_total
    d85 = 0.85 * dist_total
    z10 = float(np.interp(d10, perfil_distancias_m, perfil_elevaciones_m))
    z85 = float(np.interp(d85, perfil_distancias_m, perfil_elevaciones_m))
    s1085 = abs(z85 - z10) / (0.75 * lc_km * 1000.0) if lc_km > 0 else float("nan")

    # --- pendiente compensada por regresión lineal (SLR) ---
    if perfil_distancias_m.size >= 2:
        slope_reg, intercept = np.polyfit(perfil_distancias_m, perfil_elevaciones_m, 1)
        slr = abs(slope_reg)
    else:
        slr = float("nan")

    # --- Taylor-Schwartz ---
    if tramos is None and perfil_distancias_m.size >= 11:
        # Segmentación automática en 10 tramos iguales por distancia
        tramos = []
        bordes = np.linspace(perfil_distancias_m[0], perfil_distancias_m[-1], 11)
        for i in range(10):
            d0, d1 = bordes[i], bordes[i + 1]
            z0 = float(np.interp(d0, perfil_distancias_m, perfil_elevaciones_m))
            z1 = float(np.interp(d1, perfil_distancias_m, perfil_elevaciones_m))
            long_tramo = d1 - d0
            pend_tramo = abs(z0 - z1) / long_tramo if long_tramo > 0 else 1e-6
            tramos.append(TramoCauce(longitud_m=long_tramo, pendiente_m_m=max(pend_tramo, 1e-6)))

    if tramos:
        suma_li_sqrt_si = sum(t.longitud_m / math.sqrt(t.pendiente_m_m) for t in tramos)
        sts = (lc_km * 1000.0 / suma_li_sqrt_si) ** 2 if suma_li_sqrt_si > 0 else float("nan")
    else:
        sts = float("nan")

    gc = se
    torrencial = gc > 0.05

    return {
        "Lc": round(lc_km, 3), "Zinicio": round(z_inicio, 3), "Zfin": round(z_fin, 3),
        "Hc": round(hc, 3), "Se": round(se, 5), "S10_85": round(s1085, 5),
        "SLR": round(slr, 5), "STS": round(sts, 5), "Gc": round(gc, 5),
        "interpretacion": "Torrencial / alta pendiente" if torrencial else "Pendiente moderada a baja",
    }


# ---------------------------------------------------------------------
# GRUPO 4: Pendiente de cuenca y curva hipsométrica
# ---------------------------------------------------------------------
def curva_cota_area_volumen(z_array: np.ndarray, pixel_area_m2: float, n_niveles: int = 30) -> dict:
    """
    Curva Cota-Área-Volumen (C-A-V), típica de estudios de embalses/
    presas: para cada nivel de agua (cota), calcula el área inundada
    acumulada por debajo de esa cota y el volumen acumulado embalsado
    (integración numérica por el método trapezoidal entre niveles
    sucesivos: V_i = V_(i-1) + (A_(i-1) + A_i)/2 * dz).

    z_array: elevaciones del MDE dentro del vaso/cuenca de interés
        (mismo tipo de array que usan grupo1_basicos/grupo4).
    pixel_area_m2: área de cada celda del MDE (para convertir conteo de
        píxeles a área real).
    n_niveles: número de niveles de cota a evaluar entre el mínimo y el
        máximo del MDE (por defecto 30).

    Devuelve {'curva': [{'cota_m','area_m2','area_acumulada_m2',
    'volumen_acumulado_m3'}, ...], 'z_min','z_max','area_total_m2',
    'volumen_total_m3'}.
    """
    validos = z_array[~np.isnan(z_array)]
    if validos.size == 0:
        raise ValueError("El array de elevaciones no tiene datos válidos.")

    z_min, z_max = float(validos.min()), float(validos.max())
    if z_max <= z_min:
        raise ValueError("El rango de elevaciones es nulo; no se puede construir la curva C-A-V.")

    niveles = np.linspace(z_min, z_max, n_niveles + 1)
    dz = niveles[1] - niveles[0]

    curva = []
    volumen_acum = 0.0
    area_anterior = 0.0
    for i, cota in enumerate(niveles):
        area_m2 = float(np.sum(validos <= cota)) * pixel_area_m2
        if i > 0:
            volumen_acum += (area_anterior + area_m2) / 2.0 * dz
        curva.append({
            "cota_m": round(float(cota), 2),
            "area_acumulada_m2": round(area_m2, 1),
            "area_acumulada_km2": round(area_m2 / 1e6, 5),
            "volumen_acumulado_m3": round(volumen_acum, 1),
            "volumen_acumulado_hm3": round(volumen_acum / 1e6, 5),
        })
        area_anterior = area_m2

    return {
        "curva": curva,
        "z_min": round(z_min, 2),
        "z_max": round(z_max, 2),
        "area_total_m2": round(area_anterior, 1),
        "volumen_total_m3": round(volumen_acum, 1),
        "nota": (
            "Volumen calculado por integración trapezoidal del área inundada acumulada entre "
            "niveles de cota sucesivos (método estándar de curvas C-A-V a partir de un MDE). La "
            "precisión depende directamente de la resolución del MDE utilizado."
        ),
    }


# ---------------------------------------------------------------------
# GRUPO 4: Pendiente de la cuenca y curva hipsométrica
# ---------------------------------------------------------------------
def grupo4_pendiente_hipsometria(slope_array_pct: np.ndarray, z_array: np.ndarray, n_bins: int = 20) -> dict:
    """
    slope_array_pct: array de pendiente celda-a-celda (%) dentro de la
        cuenca (derivado del MDE con un algoritmo de pendiente estándar,
        p.ej. gdal:slope o native:slope, ANTES de llamar esta función).
    z_array: elevaciones del MDE dentro de la cuenca (para la curva
        hipsométrica).
    """
    s_media_pct = float(np.mean(slope_array_pct)) if slope_array_pct.size else float("nan")
    s_media_deg = float(np.degrees(np.arctan(np.mean(slope_array_pct) / 100.0))) if slope_array_pct.size else float("nan")

    # --- curva hipsométrica: 20 intervalos de elevación (21 bordes), % área acumulada ---
    z_min, z_max = float(np.min(z_array)), float(np.max(z_array))
    bordes = np.linspace(z_min, z_max, n_bins + 1)
    total_celdas = z_array.size
    curva = []
    # OJO: bordes tiene n_bins+1 valores (0..n_bins); iterar solo
    # range(n_bins) (0..n_bins-1) deja fuera bordes[n_bins] = z_max, es
    # decir, la cota más alta de la cuenca NUNCA se agregaba a la curva
    # -- se veía "cortada" antes de llegar al 0% de área acumulada (la
    # cumbre). Se corrige iterando range(n_bins + 1) para incluir también
    # ese último borde.
    for i in range(n_bins + 1):
        umbral = bordes[i]
        area_sobre_umbral = float(np.sum(z_array >= umbral)) / total_celdas * 100.0
        elevacion_relativa = (umbral - z_min) / (z_max - z_min) * 100.0 if z_max > z_min else 0.0
        curva.append({"elevacion_m": round(umbral, 2), "elevacion_relativa_pct": round(elevacion_relativa, 2),
                      "area_acumulada_pct": round(area_sobre_umbral, 2)})

    return {
        "S_cuenca_pct": round(s_media_pct, 3), "S_cuenca_deg": round(s_media_deg, 3),
        "interpretacion": "Muy escarpada" if s_media_pct > 30 else "Pendiente moderada a suave",
        "curva_hipsometrica": curva,
    }


# ---------------------------------------------------------------------
# GRUPO 5: Parámetros de la red de drenaje
# ---------------------------------------------------------------------
def grupo5_red_drenaje(lt_km: float, area_km2: float, perimetro_km: float, n_cauces: int) -> dict:
    dd = lt_km / area_km2 if area_km2 > 0 else float("nan")
    fs = n_cauces / area_km2 if area_km2 > 0 else float("nan")
    dt = n_cauces / perimetro_km if perimetro_km > 0 else float("nan")
    idd = fs / dd if dd else float("nan")
    lo = 1.0 / (2.0 * dd) if dd else float("nan")
    c = 1.0 / dd if dd else float("nan")
    iff = dd * fs
    # Longitud media de corrientes: Lm = Lt/Nu. Nu es la cantidad de
    # cauces ingresada por el usuario (Pestaña 2); se incluye también
    # aquí en el diccionario de salida (antes solo existía como el valor
    # crudo del spinbox, sin aparecer en los resultados de este grupo).
    lm = lt_km / n_cauces if n_cauces else float("nan")

    return {
        "Lt": round(lt_km, 3), "Dd": round(dd, 3), "Fs": round(fs, 3), "Dt": round(dt, 3),
        "Id": round(idd, 3), "Lo": round(lo, 3), "C": round(c, 3), "If": round(iff, 3),
        "Nu": n_cauces, "Lm": round(lm, 3),
    }


def strahler_order(lineas: List[dict]) -> Dict[int, int]:
    """
    Cálculo aproximado del orden de Strahler sobre la red vectorizada.

    Supuesto (documentado): la red vectorial no trae un atributo de
    dirección de flujo explícito, así que la dirección de cada tramo se
    infiere por elevación (fluye desde el extremo de mayor cota hacia el
    de menor cota, usando elevaciones muestreadas del MDE en los nodos
    extremos). Con esa dirección se construye un grafo dirigido y se
    aplica la regla de Strahler: una confluencia de dos tramos del mismo
    orden k produce un tramo de orden k+1 aguas abajo; si los órdenes
    difieren, el tramo de salida toma el mayor de los dos.

    lineas: lista de dicts, cada uno con:
        {'id': int, 'nodo_inicio': (x,y), 'nodo_fin': (x,y),
         'z_inicio': float, 'z_fin': float}
    Devuelve {id_linea: orden_strahler}.
    """
    # Normalizar dirección: inicio = extremo más alto (aguas arriba)
    tramos = []
    for ln in lineas:
        if ln["z_inicio"] >= ln["z_fin"]:
            aguas_arriba, aguas_abajo = ln["nodo_inicio"], ln["nodo_fin"]
        else:
            aguas_arriba, aguas_abajo = ln["nodo_fin"], ln["nodo_inicio"]
        tramos.append({"id": ln["id"], "arriba": aguas_arriba, "abajo": aguas_abajo})

    # Nodo aguas abajo -> lista de tramos que llegan a él
    llegan_a: Dict[Tuple[float, float], List[dict]] = {}
    for t in tramos:
        llegan_a.setdefault(t["abajo"], []).append(t)

    orden: Dict[int, int] = {}

    def calcular_orden(tramo) -> int:
        if tramo["id"] in orden:
            return orden[tramo["id"]]
        # Tramos que confluyen EN el nodo "arriba" de este tramo (sus afluentes)
        afluentes = llegan_a.get(tramo["arriba"], [])
        if not afluentes:
            orden[tramo["id"]] = 1
            return 1
        ordenes_afluentes = [calcular_orden(a) for a in afluentes]
        maximo = max(ordenes_afluentes)
        n_max = ordenes_afluentes.count(maximo)
        resultado = maximo + 1 if n_max >= 2 else maximo
        orden[tramo["id"]] = resultado
        return resultado

    for t in tramos:
        calcular_orden(t)

    return orden


# ---------------------------------------------------------------------
# GRUPO 6: Relieve e índices de riesgo por flujo de detritos
# ---------------------------------------------------------------------
def grupo6_relieve_riesgo(h_m: float, area_km2: float, lb_km: float, dd_km_km2: float, z_med: float) -> dict:
    rr = h_m / math.sqrt(area_km2) if area_km2 > 0 else float("nan")
    rh = h_m / (lb_km * 1000.0) if lb_km > 0 else float("nan")
    rn = (dd_km_km2 * h_m) / 1000.0
    oc = ((z_med / 1000.0) ** 2) / area_km2 if area_km2 > 0 else float("nan")
    im = z_med / area_km2 if area_km2 > 0 else float("nan")
    mel = h_m / math.sqrt(area_km2 * 1e6) if area_km2 > 0 else float("nan")

    alerta_flujo_detritos = mel >= 0.60

    return {
        "Rr": round(rr, 3), "Rh": round(rh, 3), "Rn": round(rn, 3),
        "Oc": round(oc, 3), "Im": round(im, 3), "Mel": round(mel, 3),
        "alerta_flujo_detritos": alerta_flujo_detritos,
        "mensaje_alerta": ("FLUJO DE DETRITOS MUY PROBABLE (Mel >= 0.60)"
                            if alerta_flujo_detritos else
                            "Melton no indica por sí solo alta probabilidad de flujo de detritos (Mel < 0.60)"),
    }
