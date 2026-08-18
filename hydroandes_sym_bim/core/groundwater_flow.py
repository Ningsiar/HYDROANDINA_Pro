# -*- coding: utf-8 -*-
"""
core/groundwater_flow.py

Motor de cálculo de FLUJO SUBTERRÁNEO: Ley de Darcy, flujo 1D entre dos
puntos (confinado y no confinado -- ecuación de Dupuit-Forchheimer), y
un solver 2D de flujo subterráneo en RÉGIMEN PERMANENTE por diferencias
finitas (5 puntos, Gauss-Seidel con sobre-relajación SOR), para
acuíferos confinados homogéneos o con transmisividad variable por
celda.

TRANSPARENCIA: este módulo NO reemplaza a MODFLOW/FEFLOW para modelos
3D transitorios, heterogéneos y con geología compleja -- eso requiere
el software especializado que menciona la metodología (fases:
modelo conceptual, discretización, selección de software, calibración/
validación). Lo que aquí se implementa es un solver 2D genuino en
régimen permanente (no una simulación de fachada): resuelve la ecuación
de Laplace/Poisson del flujo subterráneo confinado mediante diferencias
finitas, útil para análisis preliminares, validación de órdenes de
magnitud, y fines didácticos. Para estudios definitivos con recarga
variable en el tiempo, drenanaje libre, o acuíferos multicapa, use
MODFLOW/FEFLOW calibrado con piezómetros de campo.

CONDICIONES TIPO RÍO (RIV) Y DREN (DRN): además de la carga fija
(Dirichlet) y las fuentes/sumideros puntuales de caudal fijo (pozos,
recarga), `resolver_flujo_2d_permanente()` acepta condiciones RIV y DRN
-- la misma formulación que los paquetes RIV/DRN de MODFLOW: el
intercambio de caudal DEPENDE de la carga simulada en la celda (no es
un caudal fijo), así que el solver los trata como un "vecino virtual"
de conductancia C y carga h_río/h_dren dentro de cada iteración de
Gauss-Seidel -- el mismo esquema de Picard (linealización iterativa)
que usa MODFLOW para estas condiciones no lineales. RIV se desconecta
del acuífero (deja de depender de h) cuando la carga simulada cae por
debajo del fondo del lecho del río; DRN solo EXTRAE agua (nunca
inyecta) y se desactiva cuando la carga simulada cae por debajo del
nivel del dren.

La hidráulica de POZOS específica (Thiem, Theis, Cooper-Jacob, radio de
influencia) se trata en el módulo "Hidráulica de Pozos" -- este módulo
se enfoca en el flujo GENERAL del acuífero.
"""
import math
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np


class GroundwaterError(Exception):
    pass


# ============================================================================
# 1) LEY DE DARCY
# ============================================================================

def velocidad_darcy(k_m_s: float, gradiente_hidraulico: float) -> float:
    """v = -K*(dh/dl); se reporta la magnitud (m/s). v es la "velocidad
    de Darcy" o descarga específica -- NO es la velocidad real del agua
    en los poros (ver velocidad_lineal_promedio)."""
    return k_m_s * abs(gradiente_hidraulico)


def caudal_darcy(k_m_s: float, area_m2: float, gradiente_hidraulico: float) -> float:
    """Q = K*A*(dh/dl) (m³/s)."""
    return k_m_s * area_m2 * abs(gradiente_hidraulico)


def velocidad_lineal_promedio(v_darcy_m_s: float, porosidad_efectiva: float) -> float:
    """v_real = v_Darcy/ne -- velocidad lineal promedio real del agua
    entre los poros (siempre mayor que la velocidad de Darcy, ya que
    ne<1)."""
    if porosidad_efectiva <= 0 or porosidad_efectiva > 1:
        raise GroundwaterError("La porosidad efectiva debe estar entre 0 (excluido) y 1.")
    return v_darcy_m_s / porosidad_efectiva


def transmisividad(k_m_s: float, espesor_saturado_m: float) -> float:
    """T = K*b (m²/s)."""
    return k_m_s * espesor_saturado_m


# ============================================================================
# 2) FLUJO 1D ENTRE DOS PUNTOS (CONFINADO Y NO CONFINADO)
# ============================================================================

def caudal_1d_confinado(transmisividad_m2_s: float, h1_m: float, h2_m: float,
                         longitud_m: float, ancho_m: float) -> float:
    """Q = T*(h1-h2)/L * ancho (m³/s), flujo 1D en un acuífero CONFINADO
    de espesor constante entre dos secciones con cargas h1 y h2."""
    if longitud_m <= 0 or ancho_m <= 0:
        raise GroundwaterError("La longitud y el ancho deben ser mayores que cero.")
    return transmisividad_m2_s * (h1_m - h2_m) / longitud_m * ancho_m


def caudal_1d_dupuit(k_m_s: float, h1_m: float, h2_m: float, longitud_m: float,
                      ancho_m: float) -> float:
    """q = K*(h1²-h2²)/(2L) * ancho (m³/s), ecuación de Dupuit-Forchheimer
    para flujo 1D en un acuífero LIBRE (no confinado) entre dos secciones
    con niveles freáticos h1 y h2 medidos desde la base impermeable."""
    if longitud_m <= 0 or ancho_m <= 0:
        raise GroundwaterError("La longitud y el ancho deben ser mayores que cero.")
    return k_m_s * (h1_m ** 2 - h2_m ** 2) / (2 * longitud_m) * ancho_m


# ============================================================================
# 3) SOLVER 2D DE FLUJO SUBTERRÁNEO EN RÉGIMEN PERMANENTE
#    (diferencias finitas, 5 puntos, Gauss-Seidel con SOR)
# ============================================================================

def conductancia_lecho(k_lecho_m_s: float, longitud_m: float, ancho_m: float,
                        espesor_lecho_m: float) -> float:
    """Conductancia de un lecho de río/dren (m²/s): C = K_lecho*L*W/M,
    la misma fórmula estándar de los paquetes RIV/DRN de MODFLOW.
    k_lecho_m_s: conductividad hidráulica vertical del material del
    lecho (limo/arena/grava depositados), casi siempre distinta de la K
    del acuífero. L, W: largo y ancho del tramo dentro de la celda (m).
    espesor_lecho_m: espesor del lecho semipermeable (m)."""
    if espesor_lecho_m <= 0:
        raise GroundwaterError("El espesor del lecho debe ser mayor que 0.")
    if longitud_m <= 0 or ancho_m <= 0:
        raise GroundwaterError("El largo y el ancho del tramo deben ser mayores que 0.")
    return k_lecho_m_s * longitud_m * ancho_m / espesor_lecho_m


def resolver_flujo_2d_permanente(n_filas: int, n_columnas: int, dx_m: float, dy_m: float,
                                  transmisividad_m2_s, condiciones_borde: Dict[Tuple[int, int], float],
                                  fuentes_sumideros: Optional[Dict[Tuple[int, int], float]] = None,
                                  condiciones_rio: Optional[Dict[Tuple[int, int], Dict[str, float]]] = None,
                                  condiciones_dren: Optional[Dict[Tuple[int, int], Dict[str, float]]] = None,
                                  h_inicial_m: float = 0.0, tol_m: float = 1e-5, max_iter: int = 20000,
                                  factor_sor: float = 1.8) -> Dict:
    """Resuelve T*∇²h + Q/(dx·dy) = 0 en una malla rectangular de
    n_filas x n_columnas, con condiciones de carga fija (Dirichlet) en
    las celdas indicadas por condiciones_borde={(fila,col): h_fijo_m},
    fuentes/sumideros de caudal FIJO (recarga positiva, bombeo negativo,
    m³/s) en fuentes_sumideros={(fila,col): Q_m3s}, y borde SIN FLUJO
    (Neumann cero, reflexión) en cualquier otra celda del perímetro no
    fijada explícitamente. transmisividad_m2_s puede ser un escalar
    (acuífero homogéneo) o un array (n_filas,n_columnas) para T variable
    por celda (se usa la media aritmética entre celdas vecinas en la
    interfaz, aproximación estándar cuando no se dispone de la media
    armónica exacta de Harbaugh/MODFLOW).

    condiciones_rio (paquete RIV de MODFLOW): {(fila,col): {"conductancia":
    C_m2_s, "nivel": h_rio_m, "fondo": fondo_lecho_m}} -- el caudal
    intercambiado depende de la carga simulada: mientras h_simulada >=
    fondo, el río se comporta como un vecino de carga fija h_rio a
    través de la conductancia C (puede tanto recargar como drenar el
    acuífero); si h_simulada cae por debajo del fondo del lecho, el río
    se DESCONECTA del acuífero y entrega un caudal FIJO
    C*(h_rio - fondo) (ya no depende de la carga -- el mismo
    comportamiento de "goteo" del RIV package cuando el nivel freático
    baja del lecho).

    condiciones_dren (paquete DRN de MODFLOW): {(fila,col): {"conductancia":
    C_m2_s, "nivel": h_dren_m}} -- solo EXTRAE agua del acuífero
    (nunca inyecta): actúa como un vecino de carga fija h_dren mientras
    h_simulada > h_dren, y se desactiva por completo (conductancia 0)
    en cuanto h_simulada <= h_dren."""
    if n_filas < 2 or n_columnas < 2:
        raise GroundwaterError("La malla debe tener al menos 2x2 celdas.")
    fuentes_sumideros = fuentes_sumideros or {}
    condiciones_rio = condiciones_rio or {}
    condiciones_dren = condiciones_dren or {}
    h = np.full((n_filas, n_columnas), h_inicial_m, dtype=float)
    for (i, j), valor in condiciones_borde.items():
        h[i, j] = valor

    t_array = (np.full((n_filas, n_columnas), transmisividad_m2_s, dtype=float)
               if np.isscalar(transmisividad_m2_s) else np.asarray(transmisividad_m2_s, dtype=float))
    if t_array.shape != (n_filas, n_columnas):
        raise GroundwaterError("El array de transmisividad debe tener la forma (n_filas, n_columnas).")

    def t_interfaz(i1, j1, i2, j2):
        return 0.5 * (t_array[i1, j1] + t_array[i2, j2])

    celdas_fijas = set(condiciones_borde.keys())
    historial_residuo = []
    for iteracion in range(max_iter):
        residuo_max = 0.0
        for i in range(n_filas):
            for j in range(n_columnas):
                if (i, j) in celdas_fijas:
                    continue
                suma_c = 0.0
                suma_ch = 0.0
                # vecinos horizontales (misma fila): conductancia C = T*dy/dx
                for dj in (-1, 1):
                    nj = j + dj
                    if 0 <= nj < n_columnas:
                        c = t_interfaz(i, j, i, nj) * dy_m / dx_m
                        suma_c += c
                        suma_ch += c * h[i, nj]
                # vecinos verticales (misma columna): conductancia C = T*dx/dy
                for di in (-1, 1):
                    ni = i + di
                    if 0 <= ni < n_filas:
                        c = t_interfaz(i, j, ni, j) * dx_m / dy_m
                        suma_c += c
                        suma_ch += c * h[ni, j]
                q_celda = fuentes_sumideros.get((i, j), 0.0)
                h_actual = h[i, j]  # criterio de conexión/activación EN LA ITERACIÓN ANTERIOR (Picard)
                celda_no_lineal = False  # RIV/DRN activos -- ver nota de factor_sor más abajo
                riv = condiciones_rio.get((i, j))
                if riv is not None:
                    c_riv = riv["conductancia"]
                    celda_no_lineal = True
                    if h_actual >= riv["fondo"]:
                        suma_c += c_riv
                        suma_ch += c_riv * riv["nivel"]
                    else:
                        # Río desconectado del acuífero: entrega un goteo FIJO,
                        # ya no depende de la carga simulada.
                        q_celda += c_riv * (riv["nivel"] - riv["fondo"])
                dren = condiciones_dren.get((i, j))
                if dren is not None:
                    celda_no_lineal = True
                    if h_actual > dren["nivel"]:
                        suma_c += dren["conductancia"]
                        suma_ch += dren["conductancia"] * dren["nivel"]
                if suma_c <= 0:
                    continue
                h_nuevo_gs = (suma_ch + q_celda) / suma_c
                h_anterior = h[i, j]
                # SIN sobre-relajación (factor 1.0, Gauss-Seidel puro) en
                # celdas RIV/DRN: son condiciones NO LINEALES que pueden
                # cambiar de régimen (conectado/desconectado, activo/
                # inactivo) de una iteración a otra, y su conductancia
                # puede ser mucho mayor que la de las celdas vecinas
                # "normales" -- aplicarles el mismo factor_sor>1 de las
                # celdas lineales amplifica el sobresalto de cada cambio
                # de régimen en vez de amortiguarlo, y puede diverger
                # (verificado: con factor_sor=1.8 y una condición de
                # borde inicial lejos del equilibrio, el residuo se
                # disparaba a valores de millones en vez de converger).
                factor_efectivo = 1.0 if celda_no_lineal else factor_sor
                h_sor = h_anterior + factor_efectivo * (h_nuevo_gs - h_anterior)
                residuo_max = max(residuo_max, abs(h_sor - h_anterior))
                h[i, j] = h_sor
        historial_residuo.append(residuo_max)
        if residuo_max < tol_m:
            break
    else:
        pass  # se alcanzó max_iter sin converger del todo; se reporta igualmente con advertencia

    convergio = historial_residuo[-1] < tol_m if historial_residuo else True

    caudal_rio_total = 0.0
    for (i, j), riv in condiciones_rio.items():
        if h[i, j] >= riv["fondo"]:
            caudal_rio_total += riv["conductancia"] * (riv["nivel"] - h[i, j])
        else:
            caudal_rio_total += riv["conductancia"] * (riv["nivel"] - riv["fondo"])
    caudal_dren_total = 0.0
    for (i, j), dren in condiciones_dren.items():
        if h[i, j] > dren["nivel"]:
            caudal_dren_total += dren["conductancia"] * (dren["nivel"] - h[i, j])  # siempre <= 0 (sale del acuífero)

    return {"cargas_h": h, "iteraciones": len(historial_residuo), "residuo_final_m": historial_residuo[-1] if historial_residuo else 0.0,
            "convergio": convergio, "historial_residuo": historial_residuo,
            "caudal_rio_total_m3s": caudal_rio_total, "caudal_dren_total_m3s": caudal_dren_total}


# ============================================================================
# 3b) MODELO MULTICAPA (CUASI-3D) EN RÉGIMEN PERMANENTE
#    -- capas 2D acopladas por goteo vertical (leakance/VCONT), el mismo
#    esquema de los paquetes BCF/LPF de MODFLOW, SIN llegar a un flujo
#    3D completo (no hay términos de flujo horizontal cruzados entre
#    capas -- cada capa resuelve su propio flujo horizontal en el plano,
#    y el acoplamiento entre capas es solo el goteo vertical).
# ============================================================================

def leakance_entre_capas(kv1_m_s: float, espesor1_m: float, kv2_m_s: float, espesor2_m: float) -> float:
    """VCONT (1/s) entre dos capas ADYACENTES, fórmula estándar de
    MODFLOW (BCF/LPF): combina en serie la resistencia vertical de la
    mitad inferior de la capa superior y la mitad superior de la capa
    inferior:
        VCONT = 1 / (b1/(2*Kv1) + b2/(2*Kv2))
    kv1_m_s, espesor1_m: conductividad vertical y espesor de la capa
    SUPERIOR (capa k). kv2_m_s, espesor2_m: ídem de la capa INFERIOR
    (capa k+1). El caudal vertical intercambiado entre ambas celdas es
    Q = VCONT * dx*dy * (h_superior - h_inferior) (m³/s)."""
    if kv1_m_s <= 0 or kv2_m_s <= 0:
        raise GroundwaterError("Las conductividades verticales deben ser mayores que 0.")
    if espesor1_m <= 0 or espesor2_m <= 0:
        raise GroundwaterError("Los espesores deben ser mayores que 0.")
    resistencia = espesor1_m / (2.0 * kv1_m_s) + espesor2_m / (2.0 * kv2_m_s)
    return 1.0 / resistencia


def resolver_flujo_multicapa_permanente(n_capas: int, n_filas: int, n_columnas: int, dx_m: float, dy_m: float,
                                         transmisividad_m2_s, condiciones_borde: Dict[Tuple[int, int, int], float],
                                         fuentes_sumideros: Optional[Dict[Tuple[int, int, int], float]] = None,
                                         leakance_s1: Optional[Sequence] = None,
                                         condiciones_rio: Optional[Dict[Tuple[int, int, int], Dict[str, float]]] = None,
                                         condiciones_dren: Optional[Dict[Tuple[int, int, int], Dict[str, float]]] = None,
                                         h_inicial_m: float = 0.0, tol_m: float = 1e-5, max_iter: int = 20000,
                                         factor_sor: float = 1.8) -> Dict:
    """Extensión MULTICAPA (cuasi-3D) de resolver_flujo_2d_permanente():
    resuelve n_capas capas horizontales, cada una con su propio flujo 2D
    en el plano (misma discretización de 5 puntos que la versión de 1
    capa), acopladas verticalmente por GOTEO (leakance/VCONT) entre
    capas adyacentes -- ver leakance_entre_capas().

    Todas las claves de celda son ahora TRIPLETES (capa, fila, columna),
    0-index, capa 0 = capa superior: condiciones_borde={(capa,fila,col):
    h_fijo_m}, fuentes_sumideros={(capa,fila,col): Q_m3s},
    condiciones_rio/condiciones_dren={(capa,fila,col): {...}} (mismo
    formato interno que resolver_flujo_2d_permanente(), normalmente
    aplicadas solo en la capa 0 -- un río real interactúa con la capa
    freática superior, no con capas profundas).

    transmisividad_m2_s: escalar (todas las capas homogéneas), array
    (n_capas,) (una T por capa, homogénea en el plano), o array
    (n_capas,n_filas,n_columnas) (T variable por celda).

    leakance_s1: VCONT (1/s) entre la capa k y la capa k+1, para
    k=0..n_capas-2 -- escalar (todas las interfaces iguales), o array
    (n_capas-1,) (una VCONT por interfaz, homogénea en el plano), o
    array (n_capas-1,n_filas,n_columnas) (VCONT variable por celda).
    Con n_capas=1 no se necesita (no hay interfaces) y esta función se
    reduce exactamente al caso de 1 capa."""
    if n_capas < 1:
        raise GroundwaterError("El número de capas debe ser al menos 1.")
    if n_filas < 2 or n_columnas < 2:
        raise GroundwaterError("La malla debe tener al menos 2x2 celdas.")
    fuentes_sumideros = fuentes_sumideros or {}
    condiciones_rio = condiciones_rio or {}
    condiciones_dren = condiciones_dren or {}
    h = np.full((n_capas, n_filas, n_columnas), h_inicial_m, dtype=float)
    for (k, i, j), valor in condiciones_borde.items():
        h[k, i, j] = valor

    def _expandir(valor, forma_plana):
        if valor is None:
            return None
        arr = np.asarray(valor, dtype=float)
        if arr.ndim == 0:
            return np.full(forma_plana, float(arr))
        if arr.ndim == 1:
            # una T/VCONT por capa/interfaz, homogénea en el plano
            salida = np.empty(forma_plana)
            for k in range(forma_plana[0]):
                salida[k] = arr[k]
            return salida
        if arr.shape != forma_plana:
            raise GroundwaterError(f"El array debe tener la forma {forma_plana} (o (n,) u escalar).")
        return arr

    t_array = _expandir(transmisividad_m2_s, (n_capas, n_filas, n_columnas))
    leak_array = _expandir(leakance_s1, (max(n_capas - 1, 0), n_filas, n_columnas)) if n_capas > 1 else None
    if n_capas > 1 and leak_array is None:
        raise GroundwaterError("Con más de 1 capa debe indicarse leakance_s1 (goteo entre capas).")

    def t_interfaz(k, i1, j1, i2, j2):
        return 0.5 * (t_array[k, i1, j1] + t_array[k, i2, j2])

    celdas_fijas = set(condiciones_borde.keys())
    historial_residuo = []
    for _iteracion in range(max_iter):
        residuo_max = 0.0
        for k in range(n_capas):
            for i in range(n_filas):
                for j in range(n_columnas):
                    if (k, i, j) in celdas_fijas:
                        continue
                    suma_c = 0.0
                    suma_ch = 0.0
                    for dj in (-1, 1):
                        nj = j + dj
                        if 0 <= nj < n_columnas:
                            c = t_interfaz(k, i, j, i, nj) * dy_m / dx_m
                            suma_c += c
                            suma_ch += c * h[k, i, nj]
                    for di in (-1, 1):
                        ni = i + di
                        if 0 <= ni < n_filas:
                            c = t_interfaz(k, i, j, ni, j) * dx_m / dy_m
                            suma_c += c
                            suma_ch += c * h[k, ni, j]
                    # Goteo vertical hacia la capa de ARRIBA (interfaz k-1<->k)
                    if k > 0:
                        c_v = leak_array[k - 1, i, j] * dx_m * dy_m
                        suma_c += c_v
                        suma_ch += c_v * h[k - 1, i, j]
                    # Goteo vertical hacia la capa de ABAJO (interfaz k<->k+1)
                    if k < n_capas - 1:
                        c_v = leak_array[k, i, j] * dx_m * dy_m
                        suma_c += c_v
                        suma_ch += c_v * h[k + 1, i, j]
                    q_celda = fuentes_sumideros.get((k, i, j), 0.0)
                    h_actual = h[k, i, j]
                    celda_no_lineal = False
                    riv = condiciones_rio.get((k, i, j))
                    if riv is not None:
                        c_riv = riv["conductancia"]
                        celda_no_lineal = True
                        if h_actual >= riv["fondo"]:
                            suma_c += c_riv
                            suma_ch += c_riv * riv["nivel"]
                        else:
                            q_celda += c_riv * (riv["nivel"] - riv["fondo"])
                    dren = condiciones_dren.get((k, i, j))
                    if dren is not None:
                        celda_no_lineal = True
                        if h_actual > dren["nivel"]:
                            suma_c += dren["conductancia"]
                            suma_ch += dren["conductancia"] * dren["nivel"]
                    if suma_c <= 0:
                        continue
                    h_nuevo_gs = (suma_ch + q_celda) / suma_c
                    h_anterior = h[k, i, j]
                    # Mismo criterio de estabilidad que en la versión de 1
                    # capa: sin sobre-relajación en celdas con RIV/DRN
                    # activos (condición no lineal, riesgo de divergencia
                    # con factor_sor>1 -- ver esa función para el detalle).
                    factor_efectivo = 1.0 if celda_no_lineal else factor_sor
                    h_sor = h_anterior + factor_efectivo * (h_nuevo_gs - h_anterior)
                    residuo_max = max(residuo_max, abs(h_sor - h_anterior))
                    h[k, i, j] = h_sor
        historial_residuo.append(residuo_max)
        if residuo_max < tol_m:
            break

    convergio = historial_residuo[-1] < tol_m if historial_residuo else True

    caudal_rio_total = 0.0
    for (k, i, j), riv in condiciones_rio.items():
        if h[k, i, j] >= riv["fondo"]:
            caudal_rio_total += riv["conductancia"] * (riv["nivel"] - h[k, i, j])
        else:
            caudal_rio_total += riv["conductancia"] * (riv["nivel"] - riv["fondo"])
    caudal_dren_total = 0.0
    for (k, i, j), dren in condiciones_dren.items():
        if h[k, i, j] > dren["nivel"]:
            caudal_dren_total += dren["conductancia"] * (dren["nivel"] - h[k, i, j])

    caudal_leakance_por_interfaz = []
    for k in range(n_capas - 1):
        q_interfaz = float(np.sum(leak_array[k] * dx_m * dy_m * (h[k] - h[k + 1])))
        caudal_leakance_por_interfaz.append(q_interfaz)

    return {"cargas_h": h, "iteraciones": len(historial_residuo),
            "residuo_final_m": historial_residuo[-1] if historial_residuo else 0.0,
            "convergio": convergio, "historial_residuo": historial_residuo,
            "caudal_rio_total_m3s": caudal_rio_total, "caudal_dren_total_m3s": caudal_dren_total,
            "caudal_leakance_por_interfaz_m3s": caudal_leakance_por_interfaz}


# ============================================================================
# 3c) RÉGIMEN TRANSITORIO (1 CAPA) -- ESQUEMA IMPLÍCITO (BACKWARD EULER)
# ============================================================================
# S*(dh/dt) = T*∇²h + Q/(dx·dy). Se discretiza de forma IMPLÍCITA (backward
# Euler): en cada paso de tiempo Δt se resuelve un sistema en régimen
# "cuasi-permanente" donde el término de almacenamiento actúa como una
# fuente/conductancia adicional contra la carga del paso ANTERIOR --
# S*dx*dy/Δt * (h_nuevo - h_anterior_paso) se suma a la ecuación de cada
# celda exactamente igual que un término de conductancia más (misma
# idea que el "vecino virtual" de las condiciones RIV/DRN). El esquema
# implícito es incondicionalmente estable (no impone un Δt máximo por
# estabilidad numérica, a diferencia de un esquema explícito), al costo
# de resolver un sistema (aquí, Gauss-Seidel/SOR) en cada paso de tiempo.

def resolver_flujo_2d_transitorio(n_filas: int, n_columnas: int, dx_m: float, dy_m: float,
                                   transmisividad_m2_s, s_almacenamiento,
                                   condiciones_borde: Dict[Tuple[int, int], float],
                                   dt_s: float, n_pasos: int,
                                   fuentes_sumideros=None,
                                   condiciones_rio: Optional[Dict[Tuple[int, int], Dict[str, float]]] = None,
                                   condiciones_dren: Optional[Dict[Tuple[int, int], Dict[str, float]]] = None,
                                   h_inicial=0.0, tol_m: float = 1e-6, max_iter_por_paso: int = 5000,
                                   factor_sor: float = 1.8) -> Dict:
    """Simulación TRANSITORIA de flujo subterráneo 2D (1 capa), esquema
    implícito (backward Euler) -- ver nota de la sección arriba.

    s_almacenamiento: coeficiente de almacenamiento S (adimensional --
    Ss*b para un acuífero confinado, o Sy para uno libre), escalar o
    array (n_filas,n_columnas).

    dt_s: duración de cada paso de tiempo (s). n_pasos: número de pasos.

    fuentes_sumideros: {(fila,col): Q_m3s} FIJO durante toda la
    simulación, o una LISTA de n_pasos diccionarios (uno por paso) si
    el bombeo/recarga varía en el tiempo -- p.ej. para simular el
    encendido de un pozo en un paso determinado.

    condiciones_rio/condiciones_dren: mismo formato que
    resolver_flujo_2d_permanente(), fijos durante toda la simulación.

    h_inicial: condición inicial en t=0 -- escalar o array
    (n_filas,n_columnas).

    Devuelve "cargas_por_paso": lista de arrays h (uno por paso,
    SIN incluir t=0) y "tiempos_s": los tiempos acumulados
    correspondientes, además del resultado final (cargas_h = último
    paso) para reutilizar calcular_velocidades_darcy_2d() y
    comparar_cargas_observadas() sin cambios."""
    if n_filas < 2 or n_columnas < 2:
        raise GroundwaterError("La malla debe tener al menos 2x2 celdas.")
    if dt_s <= 0:
        raise GroundwaterError("dt_s debe ser mayor que 0.")
    if n_pasos < 1:
        raise GroundwaterError("n_pasos debe ser al menos 1.")
    condiciones_rio = condiciones_rio or {}
    condiciones_dren = condiciones_dren or {}

    t_array = (np.full((n_filas, n_columnas), transmisividad_m2_s, dtype=float)
               if np.isscalar(transmisividad_m2_s) else np.asarray(transmisividad_m2_s, dtype=float))
    s_array = (np.full((n_filas, n_columnas), s_almacenamiento, dtype=float)
               if np.isscalar(s_almacenamiento) else np.asarray(s_almacenamiento, dtype=float))
    if np.any(s_array <= 0):
        raise GroundwaterError("El coeficiente de almacenamiento S debe ser mayor que 0 en toda celda activa.")

    h = (np.full((n_filas, n_columnas), h_inicial, dtype=float)
         if np.isscalar(h_inicial) else np.array(h_inicial, dtype=float))
    for (i, j), valor in condiciones_borde.items():
        h[i, j] = valor

    def t_interfaz(i1, j1, i2, j2):
        return 0.5 * (t_array[i1, j1] + t_array[i2, j2])

    if isinstance(fuentes_sumideros, list):
        if len(fuentes_sumideros) != n_pasos:
            raise GroundwaterError("La lista de fuentes_sumideros debe tener un diccionario por paso (n_pasos).")
        fuentes_por_paso = fuentes_sumideros
    else:
        fuentes_por_paso = [fuentes_sumideros or {}] * n_pasos

    celdas_fijas = set(condiciones_borde.keys())
    cargas_por_paso = []
    iteraciones_por_paso = []
    for paso in range(n_pasos):
        fuentes = fuentes_por_paso[paso]
        h_paso_anterior = h.copy()
        historial_residuo = []
        for _iteracion in range(max_iter_por_paso):
            residuo_max = 0.0
            for i in range(n_filas):
                for j in range(n_columnas):
                    if (i, j) in celdas_fijas:
                        continue
                    suma_c = 0.0
                    suma_ch = 0.0
                    for dj in (-1, 1):
                        nj = j + dj
                        if 0 <= nj < n_columnas:
                            c = t_interfaz(i, j, i, nj) * dy_m / dx_m
                            suma_c += c
                            suma_ch += c * h[i, nj]
                    for di in (-1, 1):
                        ni = i + di
                        if 0 <= ni < n_filas:
                            c = t_interfaz(i, j, ni, j) * dx_m / dy_m
                            suma_c += c
                            suma_ch += c * h[ni, j]
                    # Término de almacenamiento (backward Euler): actúa
                    # como una conductancia adicional S*dx*dy/Δt contra
                    # la carga del PASO anterior (no de la iteración
                    # anterior dentro del mismo paso).
                    c_s = s_array[i, j] * dx_m * dy_m / dt_s
                    suma_c += c_s
                    suma_ch += c_s * h_paso_anterior[i, j]
                    q_celda = fuentes.get((i, j), 0.0)
                    h_actual = h[i, j]
                    celda_no_lineal = False
                    riv = condiciones_rio.get((i, j))
                    if riv is not None:
                        c_riv = riv["conductancia"]
                        celda_no_lineal = True
                        if h_actual >= riv["fondo"]:
                            suma_c += c_riv
                            suma_ch += c_riv * riv["nivel"]
                        else:
                            q_celda += c_riv * (riv["nivel"] - riv["fondo"])
                    dren = condiciones_dren.get((i, j))
                    if dren is not None:
                        celda_no_lineal = True
                        if h_actual > dren["nivel"]:
                            suma_c += dren["conductancia"]
                            suma_ch += dren["conductancia"] * dren["nivel"]
                    if suma_c <= 0:
                        continue
                    h_nuevo_gs = (suma_ch + q_celda) / suma_c
                    h_anterior = h[i, j]
                    factor_efectivo = 1.0 if celda_no_lineal else factor_sor
                    h_sor = h_anterior + factor_efectivo * (h_nuevo_gs - h_anterior)
                    residuo_max = max(residuo_max, abs(h_sor - h_anterior))
                    h[i, j] = h_sor
            historial_residuo.append(residuo_max)
            if residuo_max < tol_m:
                break
        iteraciones_por_paso.append(len(historial_residuo))
        cargas_por_paso.append(h.copy())

    tiempos_s = [dt_s * (p + 1) for p in range(n_pasos)]
    convergio_todos = all(it < max_iter_por_paso for it in iteraciones_por_paso)
    return {"cargas_h": h, "cargas_por_paso": cargas_por_paso, "tiempos_s": tiempos_s,
            "iteraciones_por_paso": iteraciones_por_paso, "convergio": convergio_todos}


def calcular_velocidades_darcy_2d(cargas_h: np.ndarray, transmisividad_m2_s, espesor_m: float,
                                   dx_m: float, dy_m: float) -> Dict:
    """Calcula el campo de velocidad de Darcy (vx, vy) a partir del
    gradiente de cargas resuelto: v = -(T/b)*grad(h) = -K*grad(h)."""
    t_array = (np.full(cargas_h.shape, transmisividad_m2_s, dtype=float)
               if np.isscalar(transmisividad_m2_s) else np.asarray(transmisividad_m2_s, dtype=float))
    k_array = t_array / espesor_m if espesor_m > 0 else t_array
    dh_dy, dh_dx = np.gradient(cargas_h, dy_m, dx_m)
    vx = -k_array * dh_dx
    vy = -k_array * dh_dy
    modulo = np.sqrt(vx ** 2 + vy ** 2)
    return {"vx": vx, "vy": vy, "modulo": modulo}


# ============================================================================
# 4) DIAGNÓSTICO DE CALIBRACIÓN (cargas simuladas vs. observadas)
# ============================================================================

def comparar_cargas_observadas(cargas_h: np.ndarray, pozos_observacion: Sequence[Tuple[int, int, float]]) -> Dict:
    """pozos_observacion: lista de (fila, columna, h_observado_m).
    Devuelve el detalle por pozo y el RMSE global."""
    detalle = []
    errores2 = []
    for fila, col, h_obs in pozos_observacion:
        if not (0 <= fila < cargas_h.shape[0] and 0 <= col < cargas_h.shape[1]):
            raise GroundwaterError(f"El pozo en ({fila},{col}) está fuera de la malla.")
        h_sim = float(cargas_h[fila, col])
        error = h_sim - h_obs
        detalle.append({"fila": fila, "columna": col, "h_observado_m": h_obs, "h_simulado_m": h_sim, "error_m": error})
        errores2.append(error ** 2)
    rmse = math.sqrt(sum(errores2) / len(errores2)) if errores2 else float("nan")
    return {"detalle": detalle, "rmse_m": rmse}
