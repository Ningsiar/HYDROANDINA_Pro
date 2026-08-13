# -*- coding: utf-8 -*-
"""
core/direct_discharge_methods.py

Fórmulas empíricas de estimación DIRECTA del caudal máximo (distintas de
los métodos de transformación lluvia-escorrentía con hidrograma unitario
ya implementados en core/unit_hydrographs.py): Témez, Mac Math y
Creager. Se usan típicamente como comparación/verificación cruzada del
caudal de diseño obtenido por SCS/Snyder/Clark.

FÓRMULAS Y FUENTES:

  MÉTODO DE TÉMEZ (fórmula racional modificada, Témez 1978): variante de
  la fórmula racional que incorpora un coeficiente de uniformidad K que
  corrige el caudal punta por la falta de simultaneidad de toda la
  cuenca al pico, en función del tiempo de concentración:
      K = 1 + (Tc^1.25) / (Tc^1.25 + 14)
      Q = (C * I * A) / 3.6 * K
  Q en m³/s, C coef. de escorrentía (0-1), I intensidad de lluvia de
  diseño para duración Tc (mm/h), A en km², Tc en horas.
  Fuente: Témez, J.R. (1978), "Cálculo Hidrometeorológico de Caudales
  Máximos en Pequeñas Cuencas Naturales"; ampliamente reproducida en
  manuales de drenaje vial de España y Latinoamérica (p.ej. instrucción
  5.2-IC de España, manuales de MTC/ANA Perú).

  MÉTODO DE MAC MATH (McMath, EE.UU., cuencas pequeñas/urbanas):
      Q = 0.0091 * C * I * A^0.8 * S^0.2
  Q en m³/s, C coef. de escorrentía (0-1), I intensidad (mm/h) para
  duración Tc, A en HECTÁREAS, S pendiente media del cauce (%).
  Fuente: fórmula clásica reproducida en múltiples manuales de
  hidrología aplicada (p.ej. Villón Béjar, "Hidrología").

  MÉTODO DE CREAGER (curva envolvente regional, Creager et al. 1945):
      Q = C * 1.303 * A^(0.936 * A^(-0.048))
  Q en m³/s, A en km², C coeficiente envolvente regional (adimensional;
  valores típicos citados en la bibliografía van de ~6-30 para cuencas
  con crecidas moderadas hasta 60-100 para las envolventes más extremas
  a nivel mundial — DEBE calibrarse/verificarse contra caudales
  máximos observados en la región, ya que es una curva envolvente, no
  una fórmula predictiva ajustada a un caso general).

TRANSPARENCIA: estas tres fórmulas son ampliamente reproducidas en la
bibliografía de hidrología aplicada de Latinoamérica, pero (como con
todos los métodos empíricos históricos de este plugin) los coeficientes
pueden variar ligeramente entre fuentes; verifique contra la referencia
que use su institución antes de un diseño definitivo.

FÓRMULAS ENVOLVENTES ADICIONALES (Dicken, Ryves, Inglis, Myer, Kresnik,
Francou-Rodier, Ventura, Bürkli-Ziegler): a diferencia de Témez/Mac Math/
Creager (que combinan intensidad de lluvia de diseño + tiempo de
concentración), estas son en su mayoría curvas ENVOLVENTES puramente
regionales -- ajustadas históricamente contra crecidas máximas OBSERVADAS
en una región concreta, con el área de la cuenca como única o principal
variable. Todas requieren, en mayor o menor medida, calibración regional
del coeficiente (C_D, C_R, C_M, C_K, K, C_v): los valores por defecto de
este módulo son puntos de partida orientativos de la bibliografía
general, NO coeficientes calibrados para los Andes peruanos -- úselas
como verificación de orden de magnitud / techo probable, no como caudal
de diseño final sin calibración local.

  DICKEN (1865, norte/centro de India): Q = C_D * A^0.75 (A en km²).
  C_D = 6-9 en zonas planas interiores, 14-28 en zonas costeras/monzónicas.

  RYVES (1884, sur de India, zonas costeras): Q = C_R * A^(2/3) (A en km²).
  C_R = 6.8 en zonas llanas interiores, hasta 10.2 en zonas costeras/montaña.

  INGLIS (1930, Ghats occidentales, cuencas montañosas de respuesta
  rápida): Q = 123.7*A / sqrt(A + 10.4) (A en km²). Sin coeficiente
  regional -- es una curva fija, calibrada específicamente para esas
  cuencas; úsela solo como referencia de orden de magnitud fuera de ellas.

  MYER / MYER-JARVIS (EE. UU., techo histórico de crecidas):
  Q = 176 * C_M * sqrt(A) (A en km²). C_M en fracción decimal (0.005-1.0);
  C_M=1.0 representa la envolvente superior absoluta histórica de EE. UU.

  KRESNIK (Europa central/regiones alpinas, cuencas pequeñas/medianas de
  alta pendiente): Q = C_K * 32*A / (0.5 + sqrt(A)) (A en km²).
  C_K = 0.2 en cuencas planas, 2.0-3.0 en cuencas alpinas.

  FRANCOU-RODIER (IAHS, formulación envolvente mundial más reconocida
  para crecidas extremas en cuencas no aforadas): Q = 10^(6-K) * A^(1-0.10*K)
  (A en km²). K = 2.0-3.0 árido/llanuras lentas, 4.0-5.0 templado/tropical
  estándar, 5.5-6.0 crecidas extremas mundiales (monzones, tifones, alta
  montaña).

  VENTURA (España/cuencas mediterráneas, microcuencas de alta pendiente):
  Q = C_v * sqrt(S * A) (A en km², S pendiente media del cauce en m/m).
  C_v = 10-40 según la torrencialidad de la zona.

  BÜRKLI-ZIEGLER (Suiza, drenaje urbano): Q = 0.00392*C*I*A_ha^0.75*(S‰)^0.25
  (A en hectáreas, I intensidad mm/h para duración Tc, S en tanto por mil
  -- por eso se multiplica la pendiente en m/m por 1000 -- C coeficiente de
  escorrentía 0-1, igual concepto que en Témez/Mac Math).

  Fuentes: catálogo compilado de fórmulas envolventes de cobertura global/
  continental (Francou-Rodier, Myer, Kresnik) y de la escuela empírica
  asiática/Commonwealth (Dicken, Ryves, Inglis), ampliamente reproducidas
  en manuales de hidrología aplicada e ingeniería de crecidas.

  NOTA: Mac Math YA estaba implementado en este módulo (caudal_mac_math,
  arriba) con una fórmula y constante (0.0091, S en % con exponente 0.2)
  ya citada a Villón Béjar y verificada en versiones anteriores del
  plugin; se mantiene esa versión sin cambios -- no se agrega una segunda
  variante de Mac Math con otra convención de unidades de pendiente (S en
  ‰ en vez de %) para no introducir ambigüedad entre dos "Mac Math"
  distintos dentro del mismo plugin.
"""
import math
from typing import Optional


class DirectDischargeError(Exception):
    pass


def caudal_temez(coef_escorrentia_c: float, intensidad_mm_h: float, area_km2: float, tc_horas: float) -> dict:
    if not (0.0 <= coef_escorrentia_c <= 1.0):
        raise DirectDischargeError("El coeficiente de escorrentía C debe estar entre 0 y 1.")
    if tc_horas <= 0:
        raise DirectDischargeError("Tc debe ser mayor que 0.")
    k = 1.0 + (tc_horas ** 1.25) / (tc_horas ** 1.25 + 14.0)
    q = (coef_escorrentia_c * intensidad_mm_h * area_km2) / 3.6 * k
    return {
        "metodo": "Témez (1978)", "Q_m3_s": round(q, 3), "coeficiente_uniformidad_K": round(k, 4),
        "C": coef_escorrentia_c, "I_mm_h": intensidad_mm_h, "A_km2": area_km2, "Tc_h": tc_horas,
    }


def caudal_mac_math(coef_escorrentia_c: float, intensidad_mm_h: float, area_km2: float, pendiente_pct: float) -> dict:
    if not (0.0 <= coef_escorrentia_c <= 1.0):
        raise DirectDischargeError("El coeficiente de escorrentía C debe estar entre 0 y 1.")
    if pendiente_pct <= 0:
        raise DirectDischargeError("La pendiente debe ser mayor que 0.")
    area_ha = area_km2 * 100.0
    q = 0.0091 * coef_escorrentia_c * intensidad_mm_h * (area_ha ** 0.8) * (pendiente_pct ** 0.2)
    return {
        "metodo": "Mac Math", "Q_m3_s": round(q, 3),
        "C": coef_escorrentia_c, "I_mm_h": intensidad_mm_h, "A_ha": round(area_ha, 2), "S_pct": pendiente_pct,
    }


def caudal_creager(area_km2: float, coeficiente_envolvente_c: float = 30.0) -> dict:
    if area_km2 <= 0:
        raise DirectDischargeError("El área debe ser mayor que 0.")
    exponente = 0.936 * (area_km2 ** -0.048)
    q = coeficiente_envolvente_c * 1.303 * (area_km2 ** exponente)
    return {
        "metodo": "Creager (envolvente regional)", "Q_m3_s": round(q, 3),
        "A_km2": area_km2, "C_envolvente": coeficiente_envolvente_c,
        "nota": (
            "Curva ENVOLVENTE regional: C debe calibrarse contra caudales máximos observados en la "
            "región (valores de referencia de la bibliografía: ~6-30 para crecidas moderadas, "
            "60-100 para envolventes mundiales extremas). Sin calibración local, este resultado es "
            "solo orientativo."
        ),
    }


def caudal_racional(coef_escorrentia_c: float, intensidad_mm_h: float, area_km2: float,
                     factor_frecuencia_cf: float = 1.0) -> dict:
    """
    Método Racional clásico: Q = Cf*C*I*A / 3.6 (Q en m3/s, I en mm/h, A
    en km²). A diferencia de Témez (arriba), NO incluye el coeficiente de
    uniformidad K que corrige la falta de simultaneidad de toda la cuenca
    al pico -- se mantiene aquí como referencia del método base sin esa
    corrección, para comparar el efecto de K entre ambos resultados.
    factor_frecuencia_cf: factor opcional (>1.0) para ajustar C por
    periodo de retorno, como en el "Racional Modificado" de algunos
    manuales de drenaje urbano (por defecto 1.0 = método racional simple).
    """
    if not (0.0 <= coef_escorrentia_c <= 1.0):
        raise DirectDischargeError("El coeficiente de escorrentía C debe estar entre 0 y 1.")
    if area_km2 <= 0:
        raise DirectDischargeError("El área debe ser mayor que 0.")
    q = (factor_frecuencia_cf * coef_escorrentia_c * intensidad_mm_h * area_km2) / 3.6
    return {
        "metodo": "Racional (simple, sin K)", "Q_m3_s": round(q, 3),
        "C": coef_escorrentia_c, "I_mm_h": intensidad_mm_h, "A_km2": area_km2, "Cf": factor_frecuencia_cf,
    }


def comparar_metodos_directos(coef_escorrentia_c: float, intensidad_mm_h: float, area_km2: float,
                               tc_horas: float, pendiente_cauce_pct: float,
                               coeficiente_creager: float = 30.0) -> dict:
    """Calcula los métodos directos con los mismos datos de entrada, para
    comparar contra el caudal de diseño obtenido por SCS/Snyder/Clark
    (Pestaña 6)."""
    return {
        "racional": caudal_racional(coef_escorrentia_c, intensidad_mm_h, area_km2),
        "temez": caudal_temez(coef_escorrentia_c, intensidad_mm_h, area_km2, tc_horas),
        "mac_math": caudal_mac_math(coef_escorrentia_c, intensidad_mm_h, area_km2, pendiente_cauce_pct),
        "creager": caudal_creager(area_km2, coeficiente_creager),
    }


def caudal_dicken(area_km2: float, coeficiente_dicken: float = 11.0) -> dict:
    if area_km2 <= 0:
        raise DirectDischargeError("El área debe ser mayor que 0.")
    q = coeficiente_dicken * (area_km2 ** 0.75)
    return {
        "metodo": "Dicken (1865)", "Q_m3_s": round(q, 3),
        "A_km2": area_km2, "C_D": coeficiente_dicken,
        "nota": "Envolvente India norte/centro: C_D=6-9 interior, 14-28 costero/monzónico.",
    }


def caudal_ryves(area_km2: float, coeficiente_ryves: float = 8.5) -> dict:
    if area_km2 <= 0:
        raise DirectDischargeError("El área debe ser mayor que 0.")
    q = coeficiente_ryves * (area_km2 ** (2.0 / 3.0))
    return {
        "metodo": "Ryves (1884)", "Q_m3_s": round(q, 3),
        "A_km2": area_km2, "C_R": coeficiente_ryves,
        "nota": "Envolvente India sur/costera: C_R=6.8 interior, hasta 10.2 costero/montaña.",
    }


def caudal_inglis(area_km2: float) -> dict:
    if area_km2 <= 0:
        raise DirectDischargeError("El área debe ser mayor que 0.")
    q = (123.7 * area_km2) / math.sqrt(area_km2 + 10.4)
    return {
        "metodo": "Inglis (1930)", "Q_m3_s": round(q, 3), "A_km2": area_km2,
        "nota": "Curva fija (sin coeficiente regional), calibrada para los Ghats occidentales (India).",
    }


def caudal_myer(area_km2: float, coeficiente_myer: float = 0.05) -> dict:
    if area_km2 <= 0:
        raise DirectDischargeError("El área debe ser mayor que 0.")
    q = 176.0 * coeficiente_myer * math.sqrt(area_km2)
    return {
        "metodo": "Myer / Myer-Jarvis", "Q_m3_s": round(q, 3),
        "A_km2": area_km2, "C_M": coeficiente_myer,
        "nota": "Techo histórico EE. UU.: C_M=0.005-1.0 (1.0 = envolvente superior absoluta histórica).",
    }


def caudal_kresnik(area_km2: float, coeficiente_kresnik: float = 1.0) -> dict:
    if area_km2 <= 0:
        raise DirectDischargeError("El área debe ser mayor que 0.")
    q = coeficiente_kresnik * (32.0 * area_km2) / (0.5 + math.sqrt(area_km2))
    return {
        "metodo": "Kresnik", "Q_m3_s": round(q, 3),
        "A_km2": area_km2, "C_K": coeficiente_kresnik,
        "nota": "Europa central/alpina: C_K=0.2 cuencas planas, 2.0-3.0 cuencas alpinas.",
    }


def caudal_francou_rodier(area_km2: float, k_regional: float = 4.5) -> dict:
    if area_km2 <= 0:
        raise DirectDischargeError("El área debe ser mayor que 0.")
    q = (10.0 ** (6.0 - k_regional)) * (area_km2 ** (1.0 - 0.10 * k_regional))
    return {
        "metodo": "Francou-Rodier (IAHS)", "Q_m3_s": round(q, 3),
        "A_km2": area_km2, "K": k_regional,
        "nota": (
            "Envolvente mundial (IAHS): K=2.0-3.0 árido/llanura lenta, 4.0-5.0 templado/tropical "
            "estándar, 5.5-6.0 crecidas extremas mundiales (monzón, tifón, alta montaña)."
        ),
    }


def caudal_ventura(area_km2: float, pendiente_m_m: float, coeficiente_ventura: float = 20.0) -> dict:
    if area_km2 <= 0:
        raise DirectDischargeError("El área debe ser mayor que 0.")
    if pendiente_m_m <= 0:
        raise DirectDischargeError("La pendiente debe ser mayor que 0.")
    q = coeficiente_ventura * math.sqrt(pendiente_m_m * area_km2)
    return {
        "metodo": "Ventura", "Q_m3_s": round(q, 3),
        "A_km2": area_km2, "S_m_m": pendiente_m_m, "C_v": coeficiente_ventura,
        "nota": "Microcuencas mediterráneas de alta pendiente: C_v=10-40 según torrencialidad.",
    }


def caudal_burkli_ziegler(coef_escorrentia_c: float, intensidad_mm_h: float, area_km2: float,
                           pendiente_m_m: float) -> dict:
    if not (0.0 <= coef_escorrentia_c <= 1.0):
        raise DirectDischargeError("El coeficiente de escorrentía C debe estar entre 0 y 1.")
    if pendiente_m_m <= 0:
        raise DirectDischargeError("La pendiente debe ser mayor que 0.")
    area_ha = area_km2 * 100.0
    pendiente_por_mil = pendiente_m_m * 1000.0
    q = 0.00392 * coef_escorrentia_c * intensidad_mm_h * (area_ha ** 0.75) * (pendiente_por_mil ** 0.25)
    return {
        "metodo": "Bürkli-Ziegler", "Q_m3_s": round(q, 3),
        "C": coef_escorrentia_c, "I_mm_h": intensidad_mm_h, "A_ha": round(area_ha, 2),
        "S_por_mil": round(pendiente_por_mil, 3),
        "nota": "Fórmula suiza de drenaje URBANO; pendiente en tanto por mil (S x 1000).",
    }


def caudal_crippen_bue(area_km2: float, k_regional_usgs: float = 10.0, exponente_b: float = 0.55) -> dict:
    """
    Ecuación envolvente de Crippen & Bue (USGS, EE. UU.): Q = kR * A^b,
    con kR (multiplicador regional USGS) y b (exponente regional,
    típicamente 0.40-0.65) calibrados por región fisiográfica de EE. UU.
    en los "Regional Flood-Frequency" reports del USGS. Igual que las
    demás envolventes de este módulo, kR/b deben calibrarse localmente;
    los valores por defecto son solo un punto de partida orientativo.
    """
    if area_km2 <= 0:
        raise DirectDischargeError("El área debe ser mayor que 0.")
    q = k_regional_usgs * (area_km2 ** exponente_b)
    return {
        "metodo": "Crippen & Bue (USGS)", "Q_m3_s": round(q, 3),
        "A_km2": area_km2, "kR": k_regional_usgs, "b": exponente_b,
        "nota": "Envolvente USGS por región fisiográfica: b típico 0.40-0.65; kR debe calibrarse localmente.",
    }


def caudal_iszkowski(area_km2: float, coeficiente_iszkowski: float, factor_forma_m: float) -> dict:
    """
    Fórmula de Iszkowski (Europa del Este/Sudamérica): Q = Ci * m * A,
    con m un factor de forma de la cuenca (derivado del ancho medio y la
    longitud del cauce principal: m = A / L² es una definición usual,
    pero el usuario puede ingresarlo directamente si ya lo tiene de otra
    fuente) y Ci un coeficiente regional. Ambos deben calibrarse/
    estimarse localmente -- se piden como entradas explícitas en vez de
    asumir un valor por defecto, dado que no hay un rango bibliográfico
    tan acotado como en Dicken/Ryves/etc.
    """
    if area_km2 <= 0:
        raise DirectDischargeError("El área debe ser mayor que 0.")
    q = coeficiente_iszkowski * factor_forma_m * area_km2
    return {
        "metodo": "Iszkowski", "Q_m3_s": round(q, 3),
        "A_km2": area_km2, "Ci": coeficiente_iszkowski, "m_forma": factor_forma_m,
        "nota": "m = factor de forma de la cuenca (p.ej. m = A/L²); Ci sin rango bibliográfico acotado, calibrar localmente.",
    }


def comparar_metodos_envolventes(area_km2: float, pendiente_m_m: float, coef_escorrentia_c: float,
                                  intensidad_mm_h: float, coeficiente_dicken: float = 11.0,
                                  coeficiente_ryves: float = 8.5, coeficiente_myer: float = 0.05,
                                  coeficiente_kresnik: float = 1.0, k_francou_rodier: float = 4.5,
                                  coeficiente_ventura: float = 20.0, k_regional_usgs: float = 10.0,
                                  exponente_b_usgs: float = 0.55, coeficiente_iszkowski: float = 1.0,
                                  factor_forma_iszkowski: float = 0.3) -> dict:
    """Calcula las 10 fórmulas envolventes/regionales adicionales con los
    mismos datos de entrada (reutiliza A, S, C, I ya usados por
    comparar_metodos_directos), para comparar contra el caudal de diseño
    SCS/Snyder/Clark y contra Témez/Mac Math/Creager/Racional (Pestaña 7)."""
    return {
        "dicken": caudal_dicken(area_km2, coeficiente_dicken),
        "ryves": caudal_ryves(area_km2, coeficiente_ryves),
        "inglis": caudal_inglis(area_km2),
        "myer": caudal_myer(area_km2, coeficiente_myer),
        "kresnik": caudal_kresnik(area_km2, coeficiente_kresnik),
        "francou_rodier": caudal_francou_rodier(area_km2, k_francou_rodier),
        "ventura": caudal_ventura(area_km2, pendiente_m_m, coeficiente_ventura),
        "burkli_ziegler": caudal_burkli_ziegler(coef_escorrentia_c, intensidad_mm_h, area_km2, pendiente_m_m),
        "crippen_bue": caudal_crippen_bue(area_km2, k_regional_usgs, exponente_b_usgs),
        "iszkowski": caudal_iszkowski(area_km2, coeficiente_iszkowski, factor_forma_iszkowski),
    }


# ==============================================================================
# MÉTODO INDIRECTO SECCIÓN-PENDIENTE (Manning inverso) Y CAUDAL CRÍTICO
# ==============================================================================
# A diferencia de todas las fórmulas empíricas/envolventes de arriba (que
# ESTIMAN el caudal de diseño a partir de la cuenca), el método de
# Sección-Pendiente es un método INDIRECTO de AFORO: reconstruye el
# caudal pico de una crecida YA OCURRIDA a partir de evidencia de campo
# levantada después del evento (marcas de agua/nivel máximo en las
# orillas, sección transversal y pendiente de la línea de energía
# medidas en el tramo), aplicando la ecuación de Manning con esa
# geometría. Es la base de la mayoría de aforos indirectos post-crecida
# en cuencas sin estación de medición. El caudal crítico (Fr=1) se
# incluye como referencia -- útil para verificar el régimen de flujo del
# tramo aforado y como caudal de control en el diseño de estructuras.

def caudal_seccion_pendiente_manning(area_mojada_m2: float, radio_hidraulico_m: float,
                                      pendiente_m_m: float, manning_n: float) -> dict:
    """Método de Sección y Pendiente (aforo indirecto post-crecida):
    Q = (1/n) * A * R^(2/3) * S^(1/2) (ecuación de Manning aplicada a la
    sección y pendiente de la línea de energía medidas en campo)."""
    if manning_n <= 0:
        raise DirectDischargeError("El coeficiente de Manning n debe ser mayor que 0.")
    if pendiente_m_m <= 0:
        raise DirectDischargeError("La pendiente de la línea de energía debe ser mayor que 0.")
    if area_mojada_m2 <= 0 or radio_hidraulico_m <= 0:
        raise DirectDischargeError("El área mojada y el radio hidráulico deben ser mayores que 0.")
    q = (1.0 / manning_n) * area_mojada_m2 * (radio_hidraulico_m ** (2.0 / 3.0)) * math.sqrt(pendiente_m_m)
    v = q / area_mojada_m2
    return {
        "metodo": "Sección-Pendiente (Manning, aforo indirecto)", "Q_m3_s": round(q, 3),
        "velocidad_m_s": round(v, 3), "A_m2": area_mojada_m2, "R_m": radio_hidraulico_m,
        "S_m_m": pendiente_m_m, "n_manning": manning_n,
    }


def caudal_critico(area_critica_m2: float, ancho_superficial_m: float, gravedad_m_s2: float = 9.81) -> dict:
    """Caudal bajo régimen crítico (número de Froude = 1):
    Qc = Ac * sqrt(g*Ac/Bc). Útil como referencia de control de flujo del
    tramo aforado por Sección-Pendiente, y como caudal de diseño en
    estructuras que operan en régimen crítico (p.ej. vertederos, control
    de entrada de alcantarillas)."""
    if ancho_superficial_m <= 0 or area_critica_m2 <= 0:
        raise DirectDischargeError("El área crítica y el ancho superficial deben ser mayores que 0.")
    q = area_critica_m2 * math.sqrt((gravedad_m_s2 * area_critica_m2) / ancho_superficial_m)
    return {
        "metodo": "Caudal crítico (Fr=1)", "Q_m3_s": round(q, 3),
        "Ac_m2": area_critica_m2, "Bc_m": ancho_superficial_m,
    }


# ==============================================================================
# ESCUELAS REGIONALES ADICIONALES (Latinoamérica, Europa clásica, Norteamérica
# histórica pre-USGS/pre-SCS)
# ==============================================================================
# Mismo carácter y las mismas advertencias que el bloque de envolventes de
# arriba: son curvas ajustadas históricamente contra crecidas máximas
# OBSERVADAS de una región concreta. Las de Santa María (Chile) y Rocha
# (Brasil) son las más cercanas al contexto de este plugin (vertiente
# andina / sudamericana), pero AUN ASÍ requieren calibración local: el
# coeficiente regional es el que absorbe toda la diferencia entre una
# cuenca chilena/brasileña y una cuenca altoandina peruana.
#
# NOTA sobre Kuichling y Murphy: no tienen coeficiente regional -- son
# curvas envolventes FIJAS, calibradas contra las crecidas históricas del
# estado de Nueva York y del este de EE. UU. respectivamente. Fuera de
# esas regiones son solo una referencia de "techo histórico" de otra
# parte del mundo, no una estimación transferible; se incluyen por
# completitud del catálogo comparativo, y sus valores suelen quedar muy
# por encima del resto (es lo esperable de una envolvente superior).

def caudal_santa_maria(area_km2: float, coeficiente_cs: float = 25.0) -> dict:
    """Fórmula de Santa María (Chile, cuencas andinas de alta pendiente y
    respuesta muy rápida): Q = Cs * A^0.60."""
    if area_km2 <= 0:
        raise DirectDischargeError("El área debe ser mayor que 0.")
    q = coeficiente_cs * (area_km2 ** 0.60)
    return {
        "metodo": "Santa María (Chile)", "Q_m3_s": round(q, 3),
        "A_km2": area_km2, "Cs": coeficiente_cs,
        "nota": "Vertiente andina: Cs=15-40 según latitud y torrencialidad. Escuela regional más cercana a los Andes peruanos.",
    }


def caudal_springall(area_km2: float, p24_mm: float, coeficiente_csp: float = 0.50) -> dict:
    """Fórmula de Springall (México, cuencas medianas áridas/semiáridas):
    Q = 1.15 * Csp * A^0.67 * P24^0.5."""
    if area_km2 <= 0:
        raise DirectDischargeError("El área debe ser mayor que 0.")
    if p24_mm <= 0:
        raise DirectDischargeError("La precipitación máxima en 24h debe ser mayor que 0.")
    q = 1.15 * coeficiente_csp * (area_km2 ** 0.67) * (p24_mm ** 0.50)
    return {
        "metodo": "Springall (México)", "Q_m3_s": round(q, 3),
        "A_km2": area_km2, "P24_mm": p24_mm, "Csp": coeficiente_csp,
        "nota": "Zonas áridas/semiáridas de México: Csp=0.20-0.80 según cobertura vegetal y permeabilidad del suelo.",
    }


def caudal_rocha(area_km2: float, pendiente_m_km: float, coeficiente_cr: float = 2.5) -> dict:
    """Fórmula de Rocha (Brasil, sudeste, cuencas no aforadas con
    vegetación densa): Q = Cr * A^0.75 * S^0.20, con S en m/km (ojo: NO en
    m/m ni en %; el llamador debe convertir -- S[m/km] = S[%] * 10)."""
    if area_km2 <= 0:
        raise DirectDischargeError("El área debe ser mayor que 0.")
    if pendiente_m_km <= 0:
        raise DirectDischargeError("La pendiente debe ser mayor que 0.")
    q = coeficiente_cr * (area_km2 ** 0.75) * (pendiente_m_km ** 0.20)
    return {
        "metodo": "Rocha (Brasil)", "Q_m3_s": round(q, 3),
        "A_km2": area_km2, "S_m_km": round(pendiente_m_km, 3), "Cr": coeficiente_cr,
        "nota": "Sudeste de Brasil, vegetación densa: Cr=1.5-5.0. Pendiente en m/km (= S% x 10).",
    }


def caudal_possenti(area_montana_km2: float, area_llana_km2: float, longitud_cauce_km: float,
                     coeficiente_cp: float = 90.0) -> dict:
    """Fórmula de Possenti (Italia): Q = (Cp/L) * (Am + 0.33*Ap). Una de
    las primeras en diferenciar explícitamente el aporte de la zona
    montañosa (Am, aporta completo) del de la zona llana/de valle (Ap,
    aporta solo un tercio por su mayor amortiguamiento)."""
    if longitud_cauce_km <= 0:
        raise DirectDischargeError("La longitud del cauce principal debe ser mayor que 0.")
    if area_montana_km2 < 0 or area_llana_km2 < 0:
        raise DirectDischargeError("Las áreas montañosa y llana no pueden ser negativas.")
    if (area_montana_km2 + area_llana_km2) <= 0:
        raise DirectDischargeError("La suma del área montañosa y llana debe ser mayor que 0.")
    q = (coeficiente_cp / longitud_cauce_km) * (area_montana_km2 + 0.33 * area_llana_km2)
    return {
        "metodo": "Possenti (Italia)", "Q_m3_s": round(q, 3),
        "Am_km2": area_montana_km2, "Ap_km2": area_llana_km2, "L_km": longitud_cauce_km, "Cp": coeficiente_cp,
        "nota": "Cuencas mixtas: Cp=70-120 (torrencialidad). El área llana aporta solo 1/3 del área montañosa.",
    }


def caudal_lauterburg(area_km2: float, coeficiente_cl: float = 1.0) -> dict:
    """Fórmula de Lauterburg (Suiza, Alpes): Q = Cl * 0.62*A/(1+0.0008*A)."""
    if area_km2 <= 0:
        raise DirectDischargeError("El área debe ser mayor que 0.")
    q = coeficiente_cl * ((0.62 * area_km2) / (1.0 + 0.0008 * area_km2))
    return {
        "metodo": "Lauterburg (Suiza)", "Q_m3_s": round(q, 3),
        "A_km2": area_km2, "Cl": coeficiente_cl,
        "nota": "Alpes suizos, drenaje de cuencas de montaña: Cl=0.8-2.5 (climático/estacional).",
    }


def caudal_turazza(coef_escorrentia_c: float, intensidad_mm_h: float, area_km2: float,
                    tc_horas: float) -> dict:
    """Fórmula de Turazza (Italia), precursora directa del método
    racional en Europa continental: Q = (C*I*A/3.6) * 1/(1+0.05*Tc). El
    segundo factor amortigua el caudal racional puro en función del
    tiempo de concentración -- mismo propósito que el coeficiente K de
    Témez, pero con otra formulación (aquí REDUCE el caudal, mientras que
    la K de Témez lo AUMENTA; compárense ambos resultados)."""
    if not (0.0 <= coef_escorrentia_c <= 1.0):
        raise DirectDischargeError("El coeficiente de escorrentía C debe estar entre 0 y 1.")
    if area_km2 <= 0:
        raise DirectDischargeError("El área debe ser mayor que 0.")
    if tc_horas <= 0:
        raise DirectDischargeError("Tc debe ser mayor que 0.")
    factor_amortiguamiento = 1.0 / (1.0 + 0.05 * tc_horas)
    q = ((coef_escorrentia_c * intensidad_mm_h * area_km2) / 3.6) * factor_amortiguamiento
    return {
        "metodo": "Turazza (Italia)", "Q_m3_s": round(q, 3),
        "C": coef_escorrentia_c, "I_mm_h": intensidad_mm_h, "A_km2": area_km2, "Tc_h": tc_horas,
        "factor_amortiguamiento": round(factor_amortiguamiento, 4),
        "nota": "Precursora del método racional; el factor 1/(1+0.05·Tc) reduce el caudal (opuesto a la K de Témez).",
    }


def caudal_kuichling(area_km2: float) -> dict:
    """Ecuación de Kuichling (Nueva York, EE. UU., fines del siglo XIX):
    Q = A * (4400/(A+170) + 20). Curva envolvente FIJA, sin coeficiente
    regional."""
    if area_km2 <= 0:
        raise DirectDischargeError("El área debe ser mayor que 0.")
    q = area_km2 * ((4400.0 / (area_km2 + 170.0)) + 20.0)
    return {
        "metodo": "Kuichling (Nueva York)", "Q_m3_s": round(q, 3), "A_km2": area_km2,
        "nota": "Envolvente FIJA (sin coeficiente) del estado de Nueva York. Fuera de esa región es solo un techo histórico ajeno, no transferible.",
    }


def caudal_murphy(area_km2: float) -> dict:
    """Fórmula de Murphy (ríos del este de EE. UU., primera mitad del
    siglo XX): Q = 1351*A/(A+93). Curva envolvente FIJA, sin coeficiente
    regional."""
    if area_km2 <= 0:
        raise DirectDischargeError("El área debe ser mayor que 0.")
    q = (1351.0 * area_km2) / (area_km2 + 93.0)
    return {
        "metodo": "Murphy (este de EE. UU.)", "Q_m3_s": round(q, 3), "A_km2": area_km2,
        "nota": "Envolvente FIJA (sin coeficiente) del este de EE. UU. Fuera de esa región es solo un techo histórico ajeno, no transferible.",
    }


def comparar_escuelas_regionales(area_km2: float, pendiente_pct: float,
                                  p24_mm: float, coef_escorrentia_c: float, intensidad_mm_h: float,
                                  tc_horas: float, coeficiente_santa_maria: float = 25.0,
                                  coeficiente_springall: float = 0.50, coeficiente_rocha: float = 2.5,
                                  coeficiente_lauterburg: float = 1.0) -> dict:
    """Calcula las 6 fórmulas de escuelas regionales adicionales
    (latinoamericana, europea clásica y norteamericana histórica) con los
    mismos datos ya ingresados en la Pestaña 6.

    Possenti y Kuichling se retiraron del cálculo (v0.3.x) a pedido
    expreso: Possenti exige repartir el área entre zona montañosa y de
    valle, un dato que rara vez se tiene con soltura en una cuenca
    altoandina sin levantamiento de detalle, y Kuichling es una
    envolvente FIJA calibrada contra crecidas históricas de Nueva York,
    sin ningún coeficiente regional que la adapte a otro contexto -- fuera
    de esa región es solo un techo ajeno, no una estimación transferible.
    Las funciones caudal_possenti() y caudal_kuichling() se conservan en
    este módulo por si se necesitan de forma puntual."""
    return {
        "santa_maria": caudal_santa_maria(area_km2, coeficiente_santa_maria),
        "springall": caudal_springall(area_km2, p24_mm, coeficiente_springall),
        "rocha": caudal_rocha(area_km2, pendiente_pct * 10.0, coeficiente_rocha),
        "lauterburg": caudal_lauterburg(area_km2, coeficiente_lauterburg),
        "turazza": caudal_turazza(coef_escorrentia_c, intensidad_mm_h, area_km2, tc_horas),
        "murphy": caudal_murphy(area_km2),
    }


# ==============================================================================
# MÉTODOS COMPLEMENTARIOS QUE REQUIEREN DATOS ADICIONALES
# ==============================================================================
# A diferencia de todo lo anterior (que se calcula con A, S, L, C, I, Tc,
# P24 -- datos que el plugin ya tiene de las pestañas 2/3/4/5), estos
# necesitan información extra que el usuario debe aportar: cotas de la
# cuenca (Giandotti), lámina de escorrentía y duración de la crecida
# (Sokolovsky), parámetros climáticos/de vegetación (Alekseev), o
# directamente una SERIE DE CAUDALES OBSERVADOS (Fuller, Gumbel-FFA).
#
# Fuller y Gumbel-FFA son cualitativamente distintos del resto del
# módulo: no estiman el caudal desde la lluvia ni desde el área, sino que
# EXTRAPOLAN a un periodo de retorno T a partir de caudales máximos
# anuales ya OBSERVADOS en una estación de aforo. Si se dispone de esa
# serie, son la estimación más confiable de todo este módulo (usan datos
# reales del río, no una curva ajustada en otra región del mundo).

def caudal_giandotti(area_km2: float, longitud_cauce_km: float, cota_media_m: float,
                      cota_minima_m: float, p_max_mm: float, coeficiente_lambda: float = 0.15,
                      tiempo_retardo_h: float = 1.0) -> dict:
    """Método de Giandotti (Italia/Sudamérica): calcula internamente el
    tiempo de concentración de Giandotti
    Tc = (4*sqrt(A) + 1.5*L) / (0.8*sqrt(Hmedia - Hmin))
    y con él el caudal Q = (A*Pmax)/(Tc + tr) * lambda.

    NOTA DE UNIDADES: el coeficiente lambda (0.15 por defecto) absorbe la
    conversión de unidades de la expresión (km²·mm/h no da m³/s por sí
    solo); es un coeficiente empírico calibrado, no un factor físico --
    verifíquelo contra la referencia que use su institución."""
    if area_km2 <= 0:
        raise DirectDischargeError("El área debe ser mayor que 0.")
    if longitud_cauce_km <= 0:
        raise DirectDischargeError("La longitud del cauce principal debe ser mayor que 0.")
    desnivel = cota_media_m - cota_minima_m
    if desnivel <= 0:
        raise DirectDischargeError(
            "La cota media debe ser mayor que la cota mínima (desnivel > 0) para aplicar Giandotti."
        )
    tc_h = (4.0 * math.sqrt(area_km2) + 1.5 * longitud_cauce_km) / (0.8 * math.sqrt(desnivel))
    q = ((area_km2 * p_max_mm) / (tc_h + tiempo_retardo_h)) * coeficiente_lambda
    return {
        "metodo": "Giandotti", "Q_m3_s": round(q, 3), "Tc_giandotti_h": round(tc_h, 3),
        "A_km2": area_km2, "L_km": longitud_cauce_km, "desnivel_m": round(desnivel, 2),
        "P_max_mm": p_max_mm, "lambda": coeficiente_lambda, "tr_h": tiempo_retardo_h,
        "nota": "λ (0.15 por defecto) absorbe la conversión de unidades; es empírico, verifíquelo con su referencia.",
    }


def caudal_sokolovsky(area_km2: float, lamina_escorrentia_mm: float, duracion_horas: float,
                       factor_forma: float = 1.0, delta_lagos: float = 1.0) -> dict:
    """Fórmula de Sokolovsky (escuela rusa):
    Q = 0.28 * A * h * f * delta / T, con A en km², h la lámina de
    escorrentía en mm y T la duración de la crecida en horas.

    El 0.28 es la conversión estándar mm/h·km² -> m³/s (1/3.6 = 0.2778),
    igual que el /3.6 de Témez: es una identidad de unidades, no un
    coeficiente empírico ambiguo. f (forma del hidrograma) y delta
    (atenuación por lagos/embalses naturales) sí son empíricos."""
    if area_km2 <= 0:
        raise DirectDischargeError("El área debe ser mayor que 0.")
    if duracion_horas <= 0:
        raise DirectDischargeError("La duración de la crecida debe ser mayor que 0.")
    if lamina_escorrentia_mm <= 0:
        raise DirectDischargeError("La lámina de escorrentía debe ser mayor que 0.")
    q = (0.28 * area_km2 * lamina_escorrentia_mm * factor_forma * delta_lagos) / duracion_horas
    return {
        "metodo": "Sokolovsky (escuela rusa)", "Q_m3_s": round(q, 3),
        "A_km2": area_km2, "h_mm": lamina_escorrentia_mm, "T_h": duracion_horas,
        "f_forma": factor_forma, "delta_lagos": delta_lagos,
        "nota": "0.28 = 1/3.6 (conversión mm/h·km²→m³/s). Puede usar la lluvia efectiva del hidrograma (Pestaña 6) como lámina h.",
    }


def caudal_alekseev(area_km2: float, tc_horas: float, hp_m: float, n_clima: float,
                     mu_vegetacion: float) -> dict:
    """Fórmula de Alekseev (escuela rusa):
    Q = (1000*Hp*A) / ((Tc+1)^n) * mu, con Hp la lámina de lluvia en
    METROS, n un exponente climático y mu un coeficiente de vegetación/
    cobertura.

    *** CUIDADO CON LA ESCALA DE ESTA FÓRMULA ***
    El factor 1000 delante convierte Hp de metros a milímetros, de modo
    que el numerador es en realidad Hp[mm]*A[km²] -- un número muy grande.
    En consecuencia, mu NO es un coeficiente cercano a 1: además del
    efecto de la vegetación, es mu quien absorbe el resto de la
    conversión de unidades de la fórmula. Con mu=1.0 el resultado sale
    típicamente UN ORDEN DE MAGNITUD por encima del de los demás métodos
    de este módulo para la misma cuenca (mismo tipo de trampa que las
    constantes "por centímetro" de SCS/Snyder corregidas en la v0.2.44).

    Por eso este módulo NO fija un valor por defecto de mu: debe
    ingresarse explícitamente, y el llamador debería contrastar el
    resultado con el resto de métodos antes de darlo por bueno.

    El exponente n INTERACTÚA fuerte con mu, porque ambos aparecen
    multiplicando/dividiendo el mismo numerador: con n≈3 (valor de
    referencia usado en la interfaz), (Tc+1) queda elevado a un exponente
    alto y el divisor crece mucho más rápido con Tc, así que mu puede
    tomar valores del orden del coeficiente de escorrentía de la cuenca
    (0.3-0.6) sin disparar el resultado. Con un n mucho menor (p.ej. 0.6)
    el divisor crece poco y hace falta un mu muy pequeño (0.05-0.15) para
    no sobreestimar -- son dos calibraciones distintas de la misma
    fórmula, no intercambiables entre sí."""
    if area_km2 <= 0:
        raise DirectDischargeError("El área debe ser mayor que 0.")
    if tc_horas < 0:
        raise DirectDischargeError("Tc no puede ser negativo.")
    if hp_m <= 0:
        raise DirectDischargeError("La lámina de lluvia Hp debe ser mayor que 0.")
    q = ((1000.0 * hp_m * area_km2) / ((tc_horas + 1.0) ** n_clima)) * mu_vegetacion
    return {
        "metodo": "Alekseev (escuela rusa)", "Q_m3_s": round(q, 3),
        "A_km2": area_km2, "Tc_h": tc_horas, "Hp_m": hp_m, "n_clima": n_clima, "mu_veg": mu_vegetacion,
        "nota": (
            "OJO CON LA ESCALA: el factor 1000 pasa Hp de m a mm, así que μ absorbe la conversión de "
            "unidades además de la vegetación -- con μ=1 el caudal sale ~1 orden de magnitud por encima "
            "del resto de métodos. Contraste siempre con las demás fórmulas antes de darlo por bueno."
        ),
    }


def caudal_pettis(area_km2: float, longitud_cauce_km: float, p100_5dias_cm: float,
                   coeficiente_cp: float = 1.0) -> dict:
    """Fórmula de Pettis (USACE): Q = 1.5 * Cp * P^1.25 * W^0.8, con P la
    precipitación de 100 años en 5 días consecutivos (en CENTÍMETROS) y W
    el ancho medio de la cuenca (= A/L, en km)."""
    if area_km2 <= 0 or longitud_cauce_km <= 0:
        raise DirectDischargeError("El área y la longitud del cauce deben ser mayores que 0.")
    if p100_5dias_cm <= 0:
        raise DirectDischargeError("La precipitación de 100 años en 5 días debe ser mayor que 0.")
    ancho_medio_km = area_km2 / longitud_cauce_km
    q = 1.5 * coeficiente_cp * (p100_5dias_cm ** 1.25) * (ancho_medio_km ** 0.8)
    return {
        "metodo": "Pettis (USACE)", "Q_m3_s": round(q, 3),
        "A_km2": area_km2, "L_km": longitud_cauce_km, "W_medio_km": round(ancho_medio_km, 4),
        "P100_5dias_cm": p100_5dias_cm, "Cp": coeficiente_cp,
        "nota": "P en CENTÍMETROS y para 5 días consecutivos con Tr=100 años (no es la P24h de la Pestaña 5).",
    }


def caudal_fuller(caudal_medio_anual_m3_s: float, area_km2: float,
                   periodo_retorno_anios: float) -> dict:
    """Fórmula de Fuller: Q_T = Qmedio * (1 + 0.8*log10(T)) * (1 + 2*A^-0.3).

    Requiere el caudal máximo anual MEDIO observado (media de la serie de
    máximos anuales aforados). El primer factor extrapola al periodo de
    retorno T; el segundo convierte el caudal medio diario a caudal
    instantáneo de pico (por eso decrece con el área: en cuencas grandes
    el pico instantáneo se aparta menos del promedio diario)."""
    if area_km2 <= 0:
        raise DirectDischargeError("El área debe ser mayor que 0.")
    if periodo_retorno_anios <= 1.0:
        raise DirectDischargeError("El periodo de retorno debe ser mayor que 1 año.")
    if caudal_medio_anual_m3_s <= 0:
        raise DirectDischargeError("El caudal máximo anual medio observado debe ser mayor que 0.")
    factor_tr = 1.0 + 0.8 * math.log10(periodo_retorno_anios)
    factor_pico = 1.0 + 2.0 * (area_km2 ** -0.3)
    q = caudal_medio_anual_m3_s * factor_tr * factor_pico
    return {
        "metodo": "Fuller", "Q_m3_s": round(q, 3), "Q_medio_m3_s": caudal_medio_anual_m3_s,
        "A_km2": area_km2, "Tr_anios": periodo_retorno_anios,
        "factor_Tr": round(factor_tr, 4), "factor_pico_instantaneo": round(factor_pico, 4),
        "nota": "Requiere serie AFORADA de máximos anuales. Verifique si su referencia usa A en km² o en mi².",
    }


def caudal_gumbel_ffa(media_caudales_m3_s: float, desviacion_caudales_m3_s: float,
                       periodo_retorno_anios: float) -> dict:
    """Análisis de frecuencia de crecidas por Gumbel (Tipo I) aplicado a
    una serie de CAUDALES máximos anuales observados:
        yT = -ln(-ln((T-1)/T));  KT = (yT - 0.5772)/(pi/sqrt(6));
        QT = media + KT*desviación

    OJO -- esto es distinto del análisis de frecuencia de la Pestaña 5:
    aquel ajusta 9 distribuciones a la serie de PRECIPITACIÓN máxima en
    24h, mientras que este trabaja directamente sobre CAUDALES aforados.
    Si dispone de una estación de aforo en la cuenca, esta es la
    estimación más confiable de todo este módulo, porque usa el caudal
    real del río en vez de una curva ajustada en otra región.

    Se usa la forma ASINTÓTICA (muestra infinita: 0.5772 y pi/sqrt(6)).
    Para series cortas (n < 30-50) la bibliografía recomienda la variante
    de muestra finita con yn/sn tabulados en función de n, que da
    caudales algo distintos -- téngalo en cuenta si su serie es corta."""
    if periodo_retorno_anios <= 1.0:
        raise DirectDischargeError("El periodo de retorno T debe ser mayor que 1 año.")
    if desviacion_caudales_m3_s < 0:
        raise DirectDischargeError("La desviación estándar no puede ser negativa.")
    y_t = -math.log(-math.log((periodo_retorno_anios - 1.0) / periodo_retorno_anios))
    k_t = (y_t - 0.5772) / (math.pi / math.sqrt(6.0))
    q = media_caudales_m3_s + k_t * desviacion_caudales_m3_s
    return {
        "metodo": "Gumbel FFA (sobre caudales aforados)", "Q_m3_s": round(q, 3),
        "media_m3_s": media_caudales_m3_s, "desviacion_m3_s": desviacion_caudales_m3_s,
        "Tr_anios": periodo_retorno_anios, "yT": round(y_t, 4), "KT": round(k_t, 4),
        "nota": "Forma asintótica (muestra infinita); para n<30-50 use la variante de muestra finita (yn/sn tabulados).",
    }


def area_alcantarilla_talbot(area_ha: float, coeficiente_ct: float = 0.45) -> dict:
    """Fórmula de Talbot: a = Ct * A_ha^0.75.

    ATENCIÓN -- NO devuelve un caudal: devuelve el ÁREA DE LA SECCIÓN
    TRANSVERSAL (m²) que requiere la obra de arte (alcantarilla/ponton)
    para evacuar la crecida de esa cuenca. Por eso no aparece en el
    gráfico comparativo de caudales de la pestaña: no es comparable con
    los m³/s del resto de métodos. Ct clásico: ~1.0 en terreno montañoso
    rocoso de máxima escorrentía, bajando a ~0.2 en terreno llano y
    permeable -- verifique el valor y la convención de unidades contra la
    referencia que use su institución antes de dimensionar con esto."""
    if area_ha <= 0:
        raise DirectDischargeError("El área de la cuenca (ha) debe ser mayor que 0.")
    area_seccion_m2 = coeficiente_ct * (area_ha ** 0.75)
    return {
        "metodo": "Talbot (área de obra de arte)", "area_seccion_m2": round(area_seccion_m2, 3),
        "A_ha": round(area_ha, 2), "Ct": coeficiente_ct,
        "nota": "Resultado en m² de SECCIÓN (no es un caudal). Ct ~1.0 montañoso rocoso, ~0.2 llano permeable.",
    }
