# -*- coding: utf-8 -*-
"""
core/low_flows.py

Motor de cálculo de CAUDALES MÍNIMOS: curva de duración de caudales
(persistencia, Q95), método de Tennant/Montana (caudal ecológico como
% del caudal medio anual), análisis de frecuencia de valores mínimos
(Weibull y Gumbel de mínimos) y transferencia por cuenca homóloga para
cuencas sin información (relación de áreas).

FUENTES: estos son los métodos hidrológicos estándar para caudales
mínimos/ecológicos reproducidos en manuales de la ANA-Perú y en la
bibliografía de hidrología general (Tennant, 1976; Chow, "Handbook of
Applied Hydrology"; Kite, 1977, para la distribución Gumbel aplicada a
mínimos).

TRANSPARENCIA: el análisis de frecuencia de mínimos aquí se resuelve
por momentos/posición de graficación (no por máxima verosimilitud);
para un expediente de acreditación hídrica definitivo verifique el
ajuste con software especializado (HEC-SSP, o el ajuste estadístico
completo con bondad de ajuste Kolmogorov-Smirnov/Chi-cuadrado).
"""
import math
from typing import Dict, List, Sequence, Tuple

G = 9.81


class LowFlowError(Exception):
    pass


# ============================================================================
# 1) CURVA DE DURACIÓN DE CAUDALES (CDC) / PERSISTENCIA
# ============================================================================

def curva_duracion(caudales: Sequence[float]) -> Dict:
    """Ordena los caudales de mayor a menor y calcula la probabilidad de
    excedencia empírica (posición de graficación de Weibull:
    P = m/(n+1)*100, m=rango 1..n de mayor a menor)."""
    valores = sorted([float(x) for x in caudales if x is not None], reverse=True)
    n = len(valores)
    if n < 5:
        raise LowFlowError("Se requieren al menos 5 datos para la curva de duración.")
    prob_excedencia = [(m / (n + 1)) * 100.0 for m in range(1, n + 1)]
    return {"caudales_ordenados": valores, "prob_excedencia_pct": prob_excedencia}


def caudal_persistencia(caudales: Sequence[float], porcentaje: float = 95.0) -> float:
    """Interpola el caudal correspondiente a un percentil de persistencia
    dado (Q95 = caudal excedido el 95% del tiempo, estándar regulatorio
    peruano como mínimo técnico permanente)."""
    cdc = curva_duracion(caudales)
    p = cdc["prob_excedencia_pct"]
    q = cdc["caudales_ordenados"]
    if porcentaje <= p[0]:
        return q[0]
    if porcentaje >= p[-1]:
        return q[-1]
    for i in range(len(p) - 1):
        if p[i] <= porcentaje <= p[i + 1]:
            frac = (porcentaje - p[i]) / (p[i + 1] - p[i]) if p[i + 1] != p[i] else 0.0
            return q[i] + frac * (q[i + 1] - q[i])
    return q[-1]


# ============================================================================
# 2) MÉTODO DE TENNANT (MONTANA)
# ============================================================================

_TABLA_TENNANT = [
    (0, "Degradación severa del hábitat"), (10, "Mínimo (supervivencia de corto plazo)"),
    (20, "Regular / pobre"), (30, "Bueno"), (40, "Muy bueno"), (60, "Excelente"),
    (100, "Rango óptimo (100% del Qma)"),
]


def tennant_caudal_ecologico(q_medio_anual_m3s: float, porcentaje_estiaje: float = 10.0,
                              porcentaje_normal: float = 30.0) -> Dict:
    """Caudal ecológico de Tennant/Montana como % del Qma. En Perú se
    adopta frecuentemente el 10% del Qma en época de estiaje como límite
    crítico de supervivencia inmediata."""
    if q_medio_anual_m3s <= 0:
        raise LowFlowError("El caudal medio anual debe ser mayor que cero.")
    return {
        "Q_estiaje_m3s": q_medio_anual_m3s * porcentaje_estiaje / 100.0,
        "Q_normal_m3s": q_medio_anual_m3s * porcentaje_normal / 100.0,
        "categoria_estiaje": clasificar_tennant(porcentaje_estiaje),
        "categoria_normal": clasificar_tennant(porcentaje_normal),
    }


def clasificar_tennant(porcentaje: float) -> str:
    categoria = _TABLA_TENNANT[0][1]
    for limite, nombre in _TABLA_TENNANT:
        if porcentaje >= limite:
            categoria = nombre
        else:
            break
    return categoria


# ============================================================================
# 3) ANÁLISIS DE FRECUENCIA DE VALORES MÍNIMOS
# ============================================================================

def _posicion_graficacion_weibull(n: int) -> List[float]:
    """p_i = i/(n+1), i=1..n (caudales ordenados ASCENDENTE para mínimos)."""
    return [i / (n + 1) for i in range(1, n + 1)]


def ajustar_weibull_minimos(caudales_minimos_anuales: Sequence[float]) -> Dict:
    """Ajusta una distribución Weibull de 2 parámetros a la serie de
    mínimos anuales mediante regresión lineal en el papel probabilístico
    de Weibull: ln(-ln(1-F)) = forma*ln(x) - forma*ln(escala)."""
    valores = sorted([float(x) for x in caudales_minimos_anuales if x is not None and x > 0])
    n = len(valores)
    if n < 5:
        raise LowFlowError("Se requieren al menos 5 años de caudales mínimos anuales.")
    p = _posicion_graficacion_weibull(n)
    xs = [math.log(v) for v in valores]
    ys = [math.log(-math.log(1 - pi)) for pi in p]
    media_x = sum(xs) / n
    media_y = sum(ys) / n
    num = sum((x - media_x) * (y - media_y) for x, y in zip(xs, ys))
    den = sum((x - media_x) ** 2 for x in xs)
    if den == 0:
        raise LowFlowError("No se pudo ajustar Weibull (varianza nula en los datos).")
    forma = num / den
    intercepto = media_y - forma * media_x
    escala = math.exp(-intercepto / forma)
    return {"forma": forma, "escala": escala, "n_datos": n}


def caudal_tr_weibull(parametros: Dict, tr_anios: float) -> float:
    """Caudal mínimo asociado a un periodo de retorno Tr (años),
    distribución Weibull: x = escala*(-ln(1-1/Tr))^(1/forma)."""
    forma, escala = parametros["forma"], parametros["escala"]
    prob_no_excedencia = 1.0 / tr_anios  # probabilidad de que el mínimo sea igual o menor (evento raro = muy seco)
    return escala * (-math.log(1 - prob_no_excedencia)) ** (1.0 / forma)


def ajustar_gumbel_minimos(caudales_minimos_anuales: Sequence[float]) -> Dict:
    """Ajusta Gumbel de mínimos por el método de momentos:
    alpha = sigma*sqrt(6)/pi ; u = media + 0.5772*alpha (nótese el signo
    invertido respecto al Gumbel de máximos)."""
    valores = [float(x) for x in caudales_minimos_anuales if x is not None]
    n = len(valores)
    if n < 5:
        raise LowFlowError("Se requieren al menos 5 años de caudales mínimos anuales.")
    media = sum(valores) / n
    varianza = sum((x - media) ** 2 for x in valores) / (n - 1)
    sigma = math.sqrt(varianza)
    alpha = sigma * math.sqrt(6) / math.pi
    u = media + 0.5772 * alpha
    return {"u": u, "alpha": alpha, "media": media, "sigma": sigma, "n_datos": n}


def caudal_tr_gumbel_minimos(parametros: Dict, tr_anios: float) -> float:
    """Caudal mínimo asociado a Tr (años), Gumbel de mínimos (derivación
    por reflexión Y=-X desde el Gumbel de máximos estándar):
    x_T = media + alpha*[0.5772 + ln(ln(T/(T-1)))].
    A mayor Tr (evento más raro), x_T DISMINUYE (sequía más severa),
    comportamiento físicamente correcto y verificado numéricamente."""
    if tr_anios <= 1:
        raise LowFlowError("El periodo de retorno debe ser mayor que 1 año.")
    media, alpha = parametros["media"], parametros["alpha"]
    return media + alpha * (0.5772 + math.log(math.log(tr_anios / (tr_anios - 1))))


# ============================================================================
# 4) TRANSFERENCIA POR CUENCA HOMÓLOGA (cuencas sin información)
# ============================================================================

def transferencia_cuenca_homologa(q_min_homologa_m3s: float, area_estudio_km2: float,
                                   area_homologa_km2: float) -> float:
    """Q_min_estudio = Q_min_homóloga * (Área_estudio/Área_homóloga)."""
    if area_homologa_km2 <= 0:
        raise LowFlowError("El área de la cuenca homóloga debe ser mayor que cero.")
    return q_min_homologa_m3s * (area_estudio_km2 / area_homologa_km2)


# ============================================================================
# 5) RESUMEN COMPARATIVO
# ============================================================================

def resumen_comparativo(resultados_por_metodo: Dict[str, float]) -> Dict:
    """A diferencia de socavación (donde se toma el máximo como criterio
    conservador), en caudales MÍNIMOS/ecológicos el criterio conservador
    para no comprometer el ecosistema es adoptar el MÍNIMO valor entre
    métodos aplicables (el caudal a garantizar debe ser al menos el
    mayor de los mínimos exigidos, salvo criterio experto document ado)."""
    if not resultados_por_metodo:
        return {}
    metodo_critico = min(resultados_por_metodo, key=lambda k: resultados_por_metodo[k])
    valores = list(resultados_por_metodo.values())
    return {
        "metodo_mas_restrictivo": metodo_critico,
        "q_minimo_recomendado_m3s": resultados_por_metodo[metodo_critico],
        "promedio_m3s": sum(valores) / len(valores),
        "minimo_m3s": min(valores),
        "maximo_m3s": max(valores),
    }
