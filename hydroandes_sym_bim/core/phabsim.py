# -*- coding: utf-8 -*-
"""
core/phabsim.py

Motor de cálculo del método PHABSIM (Physical Habitat Simulation, USGS)
para caudal ecológico: acopla un módulo HIDRÁULICO (relación tirante/
velocidad vs. caudal en cada estación de un transecto, ajustada a partir
de mediciones de campo en varios caudales de calibración) con un módulo
de HÁBITAT (curvas de idoneidad HSI de velocidad, profundidad y
sustrato para la especie objetivo), obteniendo el Área Útil Ponderada
(WUA, m²/km) en función del caudal:

    WUA = Σ_i [ancho_i · Iv(v_i) · Id(d_i) · Is(s_i)] · 1000

TRANSPARENCIA: las curvas HSI son ESPECÍFICAS de cada especie/etapa de
vida y deben provenir de estudios de campo propios, de cuencas
homólogas, o de la bibliografía especializada (p.ej. curvas de
Oncorhynchus mykiss/trucha arcoíris publicadas para la región de
estudio) -- este módulo NO trae curvas HSI precargadas para evitar
presentar datos biológicos específicos de especie sin la validación de
un biólogo/ecólogo, tal como exige la normativa (firma multidisciplinaria
ANA). El ajuste hidráulico por estación es una regresión potencial
simple (tirante y velocidad vs. caudal en escala log-log), consistente
con el enfoque IFG4/MANSQ clásico de PHABSIM para relaciones sencillas
tirante-velocidad-caudal; para geometrías complejas (control hidráulico
variable, canales muy irregulares) valide contra un modelo hidráulico
1D/2D completo (river2D, HEC-RAS 2D).
"""
import math
from typing import Dict, List, Sequence, Tuple

import numpy as np


class PhabsimError(Exception):
    pass


# ============================================================================
# 1) AJUSTE HIDRÁULICO POR ESTACIÓN (tirante y velocidad vs. caudal)
# ============================================================================

def _ajuste_potencial(caudales: Sequence[float], valores: Sequence[float]) -> Tuple[float, float]:
    """Ajusta valor = c*Q^d mediante regresión lineal en escala log-log.
    Devuelve (c, d)."""
    if len(caudales) < 2 or len(valores) < 2:
        raise PhabsimError("Se requieren al menos 2 caudales de calibración por estación.")
    if any(q <= 0 for q in caudales) or any(v <= 0 for v in valores):
        raise PhabsimError("Caudales, tirantes y velocidades de calibración deben ser mayores que cero.")
    ln_q = [math.log(q) for q in caudales]
    ln_v = [math.log(v) for v in valores]
    n = len(ln_q)
    media_q = sum(ln_q) / n
    media_v = sum(ln_v) / n
    num = sum((q - media_q) * (v - media_v) for q, v in zip(ln_q, ln_v))
    den = sum((q - media_q) ** 2 for q in ln_q)
    if den == 0:
        raise PhabsimError("No se pudo ajustar la curva (todos los caudales de calibración son iguales).")
    d = num / den
    ln_c = media_v - d * media_q
    return math.exp(ln_c), d


def ajustar_estacion(caudales_calibracion: Sequence[float], tirantes: Sequence[float],
                      velocidades: Sequence[float]) -> Dict:
    """Ajusta las relaciones potenciales tirante(Q)=c_h*Q^d_h y
    velocidad(Q)=c_v*Q^d_v para UNA estación del transecto, a partir de
    N caudales de calibración medidos en campo (N>=2, recomendado >=3)."""
    c_h, d_h = _ajuste_potencial(caudales_calibracion, tirantes)
    c_v, d_v = _ajuste_potencial(caudales_calibracion, velocidades)
    return {"c_h": c_h, "d_h": d_h, "c_v": c_v, "d_v": d_v}


def predecir_tirante_velocidad(ajuste: Dict, caudal_m3s: float) -> Tuple[float, float]:
    tirante = ajuste["c_h"] * caudal_m3s ** ajuste["d_h"]
    velocidad = ajuste["c_v"] * caudal_m3s ** ajuste["d_v"]
    return tirante, velocidad


# ============================================================================
# 2) CURVAS DE IDONEIDAD DE HÁBITAT (HSI)
# ============================================================================

def interpolar_hsi(curva_pares: Sequence[Tuple[float, float]], valor: float) -> float:
    """Interpola linealmente la idoneidad (0-1) de una curva HSI dada
    como pares (valor_variable, idoneidad), ordenados por valor. Fuera
    del rango de la curva, la idoneidad se extiende con el valor del
    extremo más cercano (0 si la curva ya llega a 0 en ese extremo)."""
    curva = sorted(curva_pares, key=lambda p: p[0])
    if len(curva) < 2:
        raise PhabsimError("La curva HSI necesita al menos 2 puntos.")
    xs = [p[0] for p in curva]
    ys = [p[1] for p in curva]
    if valor <= xs[0]:
        return max(min(ys[0], 1.0), 0.0)
    if valor >= xs[-1]:
        return max(min(ys[-1], 1.0), 0.0)
    for i in range(len(xs) - 1):
        if xs[i] <= valor <= xs[i + 1]:
            frac = (valor - xs[i]) / (xs[i + 1] - xs[i]) if xs[i + 1] != xs[i] else 0.0
            idoneidad = ys[i] + frac * (ys[i + 1] - ys[i])
            return max(min(idoneidad, 1.0), 0.0)
    return 0.0


# ============================================================================
# 3) CÁLCULO DEL ÁREA ÚTIL PONDERADA (WUA)
# ============================================================================

def calcular_wua(estaciones: List[Dict], curva_hsi_velocidad: Sequence[Tuple[float, float]],
                  curva_hsi_profundidad: Sequence[Tuple[float, float]],
                  curva_hsi_sustrato: Sequence[Tuple[float, float]], caudal_m3s: float) -> Dict:
    """estaciones: lista de dicts {'ancho': m, 'sustrato_code': float,
    'ajuste': dict de ajustar_estacion()}. Devuelve el WUA total (m²/km)
    y el detalle por estación (tirante, velocidad, idoneidades, aporte)."""
    detalle = []
    wua_total_por_metro = 0.0
    for est in estaciones:
        tirante, velocidad = predecir_tirante_velocidad(est["ajuste"], caudal_m3s)
        iv = interpolar_hsi(curva_hsi_velocidad, velocidad)
        id_ = interpolar_hsi(curva_hsi_profundidad, tirante)
        is_ = interpolar_hsi(curva_hsi_sustrato, est["sustrato_code"])
        idoneidad_compuesta = iv * id_ * is_
        aporte = est["ancho"] * idoneidad_compuesta  # m²/m de cauce
        wua_total_por_metro += aporte
        detalle.append({"estacion": est.get("nombre", ""), "tirante_m": tirante, "velocidad_m_s": velocidad,
                        "Iv": iv, "Id": id_, "Is": is_, "idoneidad_compuesta": idoneidad_compuesta,
                        "aporte_m2_m": aporte})
    return {"caudal_m3s": caudal_m3s, "WUA_m2_km": wua_total_por_metro * 1000.0, "detalle": detalle}


def curva_caudal_wua(estaciones: List[Dict], curva_hsi_velocidad, curva_hsi_profundidad,
                      curva_hsi_sustrato, q_min: float, q_max: float, n_puntos: int = 30) -> Dict:
    if q_min <= 0 or q_max <= q_min:
        raise PhabsimError("El rango de caudales a evaluar debe ser 0 < Q_min < Q_max.")
    caudales = np.linspace(q_min, q_max, n_puntos)
    wua_valores = []
    for q in caudales:
        r = calcular_wua(estaciones, curva_hsi_velocidad, curva_hsi_profundidad, curva_hsi_sustrato, float(q))
        wua_valores.append(r["WUA_m2_km"])
    return {"caudales": caudales.tolist(), "wua": wua_valores}


# ============================================================================
# 4) CAUDAL ÓPTIMO Y CAUDAL ECOLÓGICO (punto de inflexión / umbral)
# ============================================================================

def encontrar_caudal_optimo(curva_q_wua: Dict) -> Dict:
    caudales, wua = curva_q_wua["caudales"], curva_q_wua["wua"]
    idx_max = max(range(len(wua)), key=lambda i: wua[i])
    return {"Q_optimo_m3s": caudales[idx_max], "WUA_maximo_m2_km": wua[idx_max]}


def encontrar_caudal_umbral_pct(curva_q_wua: Dict, porcentaje: float = 80.0) -> Dict:
    """Primer caudal (en la rama ascendente, antes del pico) en que el
    WUA alcanza el porcentaje indicado del WUA máximo -- criterio
    práctico simple y muy usado para fijar el caudal ecológico cuando
    mantener el caudal óptimo todo el año no es viable hidrológicamente."""
    caudales, wua = curva_q_wua["caudales"], curva_q_wua["wua"]
    idx_max = max(range(len(wua)), key=lambda i: wua[i])
    wua_max = wua[idx_max]
    objetivo = wua_max * porcentaje / 100.0
    for i in range(idx_max + 1):
        if wua[i] >= objetivo:
            return {"Q_umbral_m3s": caudales[i], "WUA_en_umbral_m2_km": wua[i], "porcentaje": porcentaje}
    return {"Q_umbral_m3s": caudales[idx_max], "WUA_en_umbral_m2_km": wua_max, "porcentaje": porcentaje}


def encontrar_punto_inflexion(curva_q_wua: Dict) -> Dict:
    """Detecta el punto de inflexión de la curva Q-WUA en la rama
    ascendente (donde la segunda derivada discreta cambia de signo, es
    decir, donde el incremento marginal de hábitat por unidad de caudal
    empieza a disminuir más fuertemente) -- criterio alternativo al
    umbral porcentual para fijar el caudal ecológico en época de estiaje
    severo."""
    caudales, wua = curva_q_wua["caudales"], curva_q_wua["wua"]
    idx_max = max(range(len(wua)), key=lambda i: wua[i])
    if idx_max < 2:
        return {"Q_inflexion_m3s": caudales[0], "WUA_en_inflexion_m2_km": wua[0]}
    segunda_derivada = []
    for i in range(1, idx_max):
        d2 = wua[i + 1] - 2 * wua[i] + wua[i - 1]
        segunda_derivada.append((i, d2))
    for i, d2 in segunda_derivada:
        if d2 < 0:
            return {"Q_inflexion_m3s": caudales[i], "WUA_en_inflexion_m2_km": wua[i]}
    idx_medio = idx_max // 2
    return {"Q_inflexion_m3s": caudales[idx_medio], "WUA_en_inflexion_m2_km": wua[idx_medio]}


# ============================================================================
# 5) CURVAS HSI DE REFERENCIA ORIENTATIVA (plantillas, NO datos validados)
# ============================================================================
# TRANSPARENCIA MUY IMPORTANTE: estas curvas son PLANTILLAS ILUSTRATIVAS con
# la FORMA típica descrita en la ECOLOGÍA GENERAL de cada especie/gremio
# (preferencias de velocidad, profundidad y sustrato ampliamente conocidas:
# p.ej. el paiche como pez de cochas/aguas quietas de la Amazonía, el camarón
# de río asociado a sustrato rocoso en rápidos de la costa peruana, etc.).
# NO provienen de un estudio bibliográfico específico verificado por Claude
# ni son curvas HSI validadas de ninguna especie, cuenca o población en
# particular -- para especies peruanas/amazónicas en especial (camarón de
# río, paiche, paco, carachama) la bibliografía primaria específica con
# curvas HSI publicadas es escasa y dispersa; instituciones como el IIAP
# (Instituto de Investigaciones de la Amazonía Peruana), IMARPE, o estudios
# de la ANA/SENACE de proyectos específicos son las fuentes a consultar para
# una curva validada. NO sustituyen datos de campo propios, de una cuenca
# homóloga, o de una fuente bibliográfica específica citada y revisada por
# un biólogo/ecólogo. Úselas solo como punto de partida orientativo para
# calibrar la forma general de sus propias curvas, nunca como sustento
# técnico final de un expediente.
#
# Escala de sustrato asumida (orientativa, tipo Brusven): 1=limo/arcilla,
# 2=arena, 3=grava fina, 4=grava media, 5=grava gruesa, 6=canto rodado,
# 7=bloques, 8=roca madre.

CURVAS_REFERENCIA_ORIENTATIVAS = {
    "Trucha arcoíris - adulto (orientativa, NO validada)": {
        "velocidad": [(0.0, 0.10), (0.1, 0.30), (0.3, 0.80), (0.5, 1.00), (0.8, 0.70), (1.2, 0.30), (1.8, 0.0)],
        "profundidad": [(0.0, 0.0), (0.2, 0.30), (0.4, 0.70), (0.6, 1.00), (1.0, 0.90), (1.5, 0.60), (2.5, 0.20)],
        "sustrato": [(1, 0.10), (2, 0.20), (3, 0.50), (4, 0.80), (5, 1.00), (6, 0.90), (7, 0.50), (8, 0.20)],
    },
    "Trucha arcoíris - juvenil/alevín (orientativa, NO validada)": {
        "velocidad": [(0.0, 0.30), (0.1, 0.80), (0.2, 1.00), (0.4, 0.60), (0.6, 0.20), (1.0, 0.0)],
        "profundidad": [(0.0, 0.20), (0.1, 0.70), (0.2, 1.00), (0.4, 0.60), (0.8, 0.20), (1.2, 0.0)],
        "sustrato": [(1, 0.20), (2, 0.40), (3, 0.80), (4, 1.00), (5, 0.70), (6, 0.40), (7, 0.20), (8, 0.10)],
    },
    "Salmón - adulto reproductor (genérico; especie NO establecida en ríos naturales del Perú)": {
        "velocidad": [(0.0, 0.10), (0.2, 0.30), (0.4, 0.70), (0.6, 1.00), (0.9, 0.80), (1.3, 0.40), (1.8, 0.10)],
        "profundidad": [(0.0, 0.0), (0.2, 0.20), (0.4, 0.50), (0.6, 0.80), (0.9, 1.00), (1.4, 0.70), (2.0, 0.30)],
        "sustrato": [(2, 0.10), (3, 0.30), (4, 0.50), (5, 0.90), (6, 1.00), (7, 0.60), (8, 0.20)],
    },
    "Genérico reófilo de aguas rápidas/rápidos (orientativo, NO validado)": {
        "velocidad": [(0.0, 0.0), (0.3, 0.30), (0.6, 0.80), (0.9, 1.00), (1.2, 0.80), (1.6, 0.40), (2.0, 0.10)],
        "profundidad": [(0.0, 0.10), (0.3, 0.50), (0.6, 0.90), (1.0, 1.00), (1.5, 0.70), (2.0, 0.30)],
        "sustrato": [(1, 0.10), (3, 0.40), (5, 0.80), (6, 1.00), (7, 0.70), (8, 0.30)],
    },
    "Genérico de pozas/aguas lentas (orientativo, NO validado)": {
        "velocidad": [(0.0, 0.60), (0.1, 1.00), (0.3, 0.70), (0.5, 0.30), (0.8, 0.10), (1.2, 0.0)],
        "profundidad": [(0.0, 0.0), (0.3, 0.30), (0.6, 0.60), (1.0, 0.90), (1.5, 1.00), (2.5, 0.80), (4.0, 0.50)],
        "sustrato": [(1, 0.70), (2, 1.00), (3, 0.70), (4, 0.40), (5, 0.20), (6, 0.10)],
    },
    "Camarón de río - Cryphiops caementarius, adulto (orientativo, NO validado; ríos de la costa peruana)": {
        "velocidad": [(0.0, 0.10), (0.2, 0.40), (0.4, 0.80), (0.6, 1.00), (0.9, 0.70), (1.3, 0.30), (1.8, 0.05)],
        "profundidad": [(0.0, 0.15), (0.15, 0.60), (0.3, 1.00), (0.5, 0.80), (0.8, 0.40), (1.2, 0.10)],
        "sustrato": [(1, 0.05), (2, 0.10), (3, 0.30), (4, 0.60), (5, 0.90), (6, 1.00), (7, 0.70), (8, 0.30)],
    },
    "Paiche - Arapaima gigas (orientativo, NO validado; cochas/aguas quietas amazónicas)": {
        "velocidad": [(0.0, 1.00), (0.05, 0.90), (0.15, 0.60), (0.3, 0.25), (0.5, 0.05), (0.8, 0.0)],
        "profundidad": [(0.0, 0.0), (0.5, 0.30), (1.0, 0.60), (2.0, 0.90), (3.0, 1.00), (5.0, 0.85), (8.0, 0.60)],
        "sustrato": [(1, 1.00), (2, 0.70), (3, 0.30), (4, 0.10), (5, 0.0)],
    },
    "Paco - Piaractus brachypomus (orientativo, NO validado; bosque inundable amazónico)": {
        "velocidad": [(0.0, 0.50), (0.1, 0.90), (0.3, 1.00), (0.5, 0.60), (0.8, 0.20), (1.2, 0.0)],
        "profundidad": [(0.0, 0.10), (0.5, 0.50), (1.0, 0.90), (1.5, 1.00), (2.5, 0.70), (4.0, 0.40)],
        "sustrato": [(1, 0.80), (2, 1.00), (3, 0.60), (4, 0.30), (5, 0.10)],
    },
    "Carachama genérica - Loricariidae (orientativo, NO validado; alta variabilidad entre géneros)": {
        "velocidad": [(0.0, 0.20), (0.2, 0.60), (0.4, 1.00), (0.7, 0.70), (1.0, 0.30), (1.4, 0.10)],
        "profundidad": [(0.0, 0.20), (0.2, 0.60), (0.4, 1.00), (0.7, 0.70), (1.2, 0.30)],
        "sustrato": [(1, 0.10), (2, 0.20), (3, 0.30), (5, 0.50), (6, 0.80), (7, 1.00), (8, 0.60)],
    },
    # -- Manglares de Tumbes (estuarino/mareal; el sustrato 1-8 tipo Brusven no capta bien
    # cobertura vegetal/raíces de mangle, ver nota de la interfaz) --
    "Pez diablo / Pámpano - manglar de Tumbes (orientativo, NO validado)": {
        "velocidad": [(0.0, 1.00), (0.1, 0.90), (0.3, 0.50), (0.5, 0.20), (0.8, 0.0)],
        "profundidad": [(0.0, 0.20), (0.3, 0.70), (0.6, 1.00), (1.0, 0.80), (2.0, 0.40)],
        "sustrato": [(1, 1.00), (2, 0.70), (3, 0.30), (4, 0.10)],
    },
    "Robalo - Centropomus spp., manglar de Tumbes (orientativo, NO validado)": {
        "velocidad": [(0.0, 0.30), (0.1, 0.70), (0.3, 1.00), (0.5, 0.70), (0.8, 0.30), (1.2, 0.0)],
        "profundidad": [(0.0, 0.10), (0.3, 0.40), (0.6, 0.80), (1.0, 1.00), (2.0, 0.90), (3.0, 0.60)],
        "sustrato": [(1, 0.60), (2, 0.80), (3, 1.00), (4, 0.50), (5, 0.20)],
    },
    "Cornuda / Lisa - Mugil spp., manglar de Tumbes (orientativo, NO validado)": {
        "velocidad": [(0.0, 0.60), (0.1, 1.00), (0.3, 0.80), (0.5, 0.40), (0.8, 0.10)],
        "profundidad": [(0.0, 0.20), (0.3, 0.60), (0.6, 1.00), (1.0, 0.90), (2.0, 0.50)],
        "sustrato": [(1, 0.50), (2, 1.00), (3, 0.60), (4, 0.20)],
    },
    "Juveniles de pargo/mero - refugio en manglar (orientativo, NO validado)": {
        "velocidad": [(0.0, 1.00), (0.1, 0.80), (0.2, 0.40), (0.4, 0.10), (0.6, 0.0)],
        "profundidad": [(0.0, 0.30), (0.2, 0.80), (0.4, 1.00), (0.7, 0.70), (1.2, 0.30)],
        "sustrato": [(1, 0.60), (2, 0.80), (3, 1.00), (4, 0.50)],
    },
    # -- Lago Titicaca (sistema léntico/lacustre; la velocidad es casi nula en la mayor
    # parte del lago -- las curvas de velocidad son más relevantes en la zona litoral/ríos
    # tributarios que en aguas abiertas) --
    "Carachi - Orestias spp., Lago Titicaca (orientativo, NO validado)": {
        "velocidad": [(0.0, 1.00), (0.05, 0.90), (0.15, 0.50), (0.3, 0.10), (0.5, 0.0)],
        "profundidad": [(0.0, 0.20), (0.3, 0.70), (0.6, 1.00), (1.0, 0.80), (2.0, 0.40)],
        "sustrato": [(1, 0.20), (2, 0.40), (3, 0.70), (4, 0.90), (5, 1.00), (6, 0.60)],
    },
    "Ispi - Orestias agassizii, Lago Titicaca (orientativo, NO validado; especie pelágica)": {
        "velocidad": [(0.0, 0.80), (0.05, 1.00), (0.15, 0.60), (0.3, 0.20), (0.5, 0.0)],
        "profundidad": [(0.0, 0.10), (0.5, 0.50), (1.5, 0.90), (3.0, 1.00), (6.0, 0.80), (10.0, 0.50)],
        "sustrato": [(1, 0.50), (3, 0.50), (5, 0.50), (7, 0.50)],
    },
    "Suche - Trichomycterus rivulatus, Lago Titicaca (orientativo, NO validado; bentónico)": {
        "velocidad": [(0.0, 0.30), (0.1, 0.70), (0.3, 1.00), (0.5, 0.70), (0.8, 0.30), (1.2, 0.0)],
        "profundidad": [(0.0, 0.30), (0.2, 0.80), (0.4, 1.00), (0.8, 0.60), (1.5, 0.20)],
        "sustrato": [(1, 0.10), (3, 0.30), (4, 0.50), (5, 0.80), (6, 1.00), (7, 0.70)],
    },
    "Pejerrey - especie introducida, Lago Titicaca (orientativo, NO validado)": {
        "velocidad": [(0.0, 0.50), (0.1, 0.90), (0.3, 1.00), (0.5, 0.60), (0.8, 0.20)],
        "profundidad": [(0.0, 0.10), (0.5, 0.50), (1.5, 0.90), (3.0, 1.00), (5.0, 0.70)],
        "sustrato": [(1, 0.30), (2, 0.50), (3, 0.80), (4, 1.00), (5, 0.60)],
    },
    # -- Ríos altoandinos (aguas frías, torrentosas, baja diversidad nativa) --
    "Suche / Mauri - Trichomycterus spp., ríos andinos (orientativo, NO validado)": {
        "velocidad": [(0.0, 0.10), (0.2, 0.40), (0.5, 0.80), (0.8, 1.00), (1.2, 0.80), (1.8, 0.30)],
        "profundidad": [(0.0, 0.20), (0.1, 0.60), (0.25, 1.00), (0.5, 0.70), (0.9, 0.30)],
        "sustrato": [(4, 0.30), (5, 0.50), (6, 0.90), (7, 1.00), (8, 0.70)],
    },
    "Preñadilla / Bagre trepador - Astroblepus spp., ríos andinos (orientativo, NO validado)": {
        "velocidad": [(0.0, 0.10), (0.3, 0.30), (0.7, 0.70), (1.2, 1.00), (1.8, 0.90), (2.5, 0.50)],
        "profundidad": [(0.0, 0.30), (0.05, 0.80), (0.1, 1.00), (0.2, 0.70), (0.4, 0.30), (0.8, 0.05)],
        "sustrato": [(5, 0.20), (6, 0.60), (7, 1.00), (8, 1.00)],
    },
    # -- Ríos de la costa peruana (cortos, estacionales, tramos bajos estuarinos) --
    "Lisa - Mugil cephalus, ríos de la costa (orientativo, NO validado)": {
        "velocidad": [(0.0, 0.40), (0.1, 0.80), (0.3, 1.00), (0.5, 0.70), (0.8, 0.30), (1.2, 0.0)],
        "profundidad": [(0.0, 0.10), (0.3, 0.50), (0.6, 0.90), (1.0, 1.00), (2.0, 0.60)],
        "sustrato": [(1, 0.40), (2, 0.80), (3, 1.00), (4, 0.60)],
    },
    "Taimo / Zúngaro costero - ríos de la costa, tramos bajos (orientativo, NO validado)": {
        "velocidad": [(0.0, 0.70), (0.1, 1.00), (0.3, 0.70), (0.5, 0.30), (0.8, 0.05)],
        "profundidad": [(0.0, 0.10), (0.3, 0.40), (0.6, 0.80), (1.0, 1.00), (2.0, 0.80), (3.5, 0.50)],
        "sustrato": [(1, 0.80), (2, 1.00), (3, 0.60), (4, 0.30)],
    },
}


def listar_curvas_referencia() -> List[str]:
    return list(CURVAS_REFERENCIA_ORIENTATIVAS.keys())
