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
