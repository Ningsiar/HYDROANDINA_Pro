# -*- coding: utf-8 -*-
"""
core/iila_senamhi_zones.py

Datos y funciones auxiliares del método IILA-SENAMHI-UNI (1983,
"Estudio de la Hidrología del Perú") que faltaban en
core/idf_curves.py::intensidad_iila_senamhi() -- esa función YA implementa
la fórmula general i(t,T) = a·(1+K·log10 T)·(t+b)^(n-1), pero exige que el
usuario traiga a, K, b y n "de la publicación IILA-SENAMHI para la zona
correspondiente" a mano. Este módulo es lo que faltaba para no tener que
salir del plugin a buscarlos.

FUENTE DE LOS DATOS (importante para saber qué tan lejos llega esto):
No existe públicamente un shapefile ni un mapa georreferenciado de las
zonas/subzonas pluviométricas IILA-SENAMHI (se buscó explícitamente; ver
PROYECTOS/HydroAndina_Pro/ESTADO_PROYECTO.md). Los coeficientes de este
módulo se transcribieron de las Tablas 37, 38 y 39 de
`resources/Estudio_Hidrologico_Hidraulico.docx` (estudio hidrológico real
de CORPORATIVO CONSTRUCTIVO LIMA BERLÍN SRL para un proyecto en Cusco),
que a su vez las reproduce del estudio original de 1983. Dos consecuencias
de dónde vienen estos números:

  1. TABLA_SUBZONAS_37_A_N (n, a directos por subzona -- régimen de
     3 a 24 horas) es un extracto PARCIAL: el informe fuente solo incluyó
     las subzonas relevantes a su propio estudio (zona 123 -- sierra sur/
     Cusco -- y unas pocas de zona 5a), NO la tabla completa de las ~30
     subzonas del Perú. Sirve para trabajos en esa región; para otra
     región del país estos valores no aplican y hay que conseguir la
     tabla completa del estudio original de 1983 (no localizada
     públicamente).
  2. El régimen de MENOS de 3 horas del método (que deriva "a" a partir
     de εg mediante a = (1/tg)^r · εg) NO se pudo reconstruir del
     documento: el exponente "r" quedó ilegible incluso extrayendo el
     objeto de ecuación nativo de Word (OOXML m:oMath) -- se optó por
     NO adivinarlo. Esa fórmula corta (t<3h) no está implementada aquí;
     solo el régimen de 3 a 24 horas, que sí se pudo recuperar completo.

MÉTODO RECOMENDADO (el que no depende de zona): la Tabla 39 da razones
Pt/P24h e It/I24h por duración, UNIFORMES para todo el Perú según el
propio estudio -- aplicadas sobre el P24(Tr) que el plugin ya calcula en
el análisis de frecuencia (Pestaña 5), sin tener que ubicar ninguna zona.
Es, de hecho, el método que el propio informe fuente usó en su caso
resuelto (sus Tablas 40-43).

LÍMITE ENCONTRADO AL VERIFICAR (no es un supuesto, es un resultado de
prueba): entre 3 y 24 horas, precipitacion_intensidad_desde_p24()
reproduce esas Tablas 40-41 con menos de un 4% de diferencia -- pero a
1 hora la diferencia sube a ~38%. La Tabla 39 comparte la misma forma
funcional que el régimen de 3-24h (Pt/P24H=((t+b)/24)^n es la versión
normalizada de Pt=a·(1+K·log T)·t^n), así que por debajo de 3 horas dejó
de representar el régimen corto real, que usa la fórmula con εg no
reconstruible (ver más abajo). Por eso esta función RECHAZA duraciones
fuera de 3-24h en vez de devolver un número engañoso.
"""
import math
from typing import Optional


class IilaSenamhiZonasError(Exception):
    pass


# ======================================================================
# TABLA 39 -- razones Pt/P24h e It/I24h por duración (independiente de
# zona y de periodo de retorno T). (duracion_h, razón_P, razón_I).
# ======================================================================
TABLA_39_RAZONES_DURACION = [
    (10 / 60, 0.20, 8.33),
    (20 / 60, 0.22, 7.20),
    (30 / 60, 0.24, 6.41),
    (40 / 60, 0.26, 5.83),
    (50 / 60, 0.28, 5.37),
    (1.0, 0.29, 4.99),
    (1.5, 0.33, 4.20),
    (2.0, 0.37, 3.68),
    (4.0, 0.46, 2.76),
    (6.0, 0.55, 2.19),
    (7.0, 0.59, 2.01),
    (8.0, 0.62, 1.86),
    (10.0, 0.68, 1.64),
    (11.0, 0.71, 1.56),
    (12.0, 0.74, 1.48),
    (24.0, 1.00, 1.00),
]


def _interpolar_log_log(x: float, tabla, indice_y: int) -> float:
    """Interpola log-log entre los puntos de `tabla` (lista de tuplas con
    x en la posición 0 e y en `indice_y`) -- la forma estándar de
    interpolar razones de una curva IDF, que en escala log-log es
    aproximadamente una recta. Fuera del rango tabulado, extrapola con el
    tramo extremo más cercano en vez de fallar."""
    puntos = sorted(tabla, key=lambda p: p[0])
    if x <= puntos[0][0]:
        i0, i1 = 0, 1
    elif x >= puntos[-1][0]:
        i0, i1 = len(puntos) - 2, len(puntos) - 1
    else:
        i0 = max(i for i in range(len(puntos) - 1) if puntos[i][0] <= x)
        i1 = i0 + 1
    x0, x1 = puntos[i0][0], puntos[i1][0]
    y0, y1 = puntos[i0][indice_y], puntos[i1][indice_y]
    lx0, lx1, lx = math.log(x0), math.log(x1), math.log(max(x, 1e-6))
    ly0, ly1 = math.log(max(y0, 1e-9)), math.log(max(y1, 1e-9))
    if lx1 == lx0:
        return y0
    ly = ly0 + (ly1 - ly0) * (lx - lx0) / (lx1 - lx0)
    return math.exp(ly)


def precipitacion_intensidad_desde_p24(p24_mm: float, duracion_h: float) -> dict:
    """
    Método RECOMENDADO -- no requiere ubicar ninguna zona geográfica.

    Aplica las razones de la Tabla 39 (IILA-SENAMHI) sobre el P24 de
    diseño que el plugin ya calculó en el análisis de frecuencia
    (Pestaña 5) para obtener la precipitación y la intensidad a
    cualquier duración, por interpolación log-log entre los puntos
    tabulados.

    LÍMITE VERIFICADO: restringido a 3-24 horas, el mismo régimen que
    precipitacion_intensidad_zona(). Se probó explícitamente contra el
    caso resuelto real del informe fuente (sus Tablas 40-41): entre 3 y
    24 horas la razón de la Tabla 39 reproduce esos valores con menos del
    3-4% de diferencia, pero a 1 hora la diferencia sube a ~38% -- la
    Tabla 39 tiene la MISMA forma funcional que la fórmula del régimen de
    3 a 24 horas (Pt/P24H=((t+b)/24)^n es la versión normalizada de
    Pt=a·(1+K·log T)·t^n), así que extrapolarla por debajo de 3 horas
    pisa el régimen corto, que usa una fórmula distinta (con εg) que este
    módulo no pudo reconstruir -- ver docstring del módulo. Devolver un
    número ahí sería más engañoso que negarse a calcularlo.
    """
    if p24_mm <= 0:
        raise IilaSenamhiZonasError("El P24 de diseño debe ser mayor que 0.")
    if not (3.0 <= duracion_h <= 24.0):
        raise IilaSenamhiZonasError(
            "Las razones de la Tabla 39 solo se verificaron confiables entre 3 y 24 horas "
            "(por debajo de 3 horas corresponden a un régimen distinto del método IILA-SENAMHI "
            "que no se pudo reconstruir de la fuente disponible -- ver docstring del módulo). "
            "Use una duración entre 3 y 24 horas.")
    razon_p = _interpolar_log_log(duracion_h, TABLA_39_RAZONES_DURACION, 1)
    razon_i = _interpolar_log_log(duracion_h, TABLA_39_RAZONES_DURACION, 2)
    p_t = razon_p * p24_mm
    i_24h = p24_mm / 24.0
    i_t = razon_i * i_24h
    return {
        "duracion_h": duracion_h, "p24_mm": p24_mm,
        "razon_p_p24": round(razon_p, 4), "razon_i_i24": round(razon_i, 4),
        "p_t_mm": round(p_t, 3), "i_t_mm_h": round(i_t, 3),
        "nota": ("Tabla 39 (razones Pt/P24h, It/I24h) del estudio IILA-SENAMHI-UNI (1983), "
                 "uniforme para todo el Perú -- no depende de la zona pluviométrica."),
    }


# ======================================================================
# TABLA 37 -- (n, a) directos por subzona, régimen de 3 a 24 horas:
#   Pt = a·(1 + K·log10 T)·t^n         It = a·(1 + K·log10 T)·t^(n-1)
# EXTRACTO PARCIAL (ver docstring del módulo): solo subzonas de la zona
# 123 (sierra sur/Cusco) y de la zona 5a que trae el informe fuente.
# `a` puede ser un número fijo o una función de la altitud Y (msnm) o de
# la distancia a la cordillera Dc (km) -- se representa como callable.
# ======================================================================
TABLA_37_SUBZONAS = {
    # subzona: (n, a_o_funcion_de_Y_o_Dc, "descripción de qué necesita `a`")
    "123_1":  (0.357, 32.2, None),
    "123_3":  (0.405, lambda y=None, dc=None: 37.85 - 0.0083 * y, "altitud Y (msnm)"),
    "123_5":  (0.353, 9.2, None),
    "123_6":  (0.380, 11.0, None),
    "123_8":  (0.232, 14.0, None),
    "123_9":  (0.242, 12.1, None),
    "123_10": (0.254, lambda y=None, dc=None: 3.01 + 0.0025 * y, "altitud Y (msnm)"),
    "123_11": (0.286, lambda y=None, dc=None: 0.46 + 0.0023 * y, "altitud Y (msnm)"),
    "5a_2":   (0.301, lambda y=None, dc=None: 14.1 - 0.078 * dc, "distancia a la cordillera Dc (km)"),
    "5a_5":   (0.303, lambda y=None, dc=None: -2.6 + 0.0031 * y, "altitud Y (msnm)"),
    "5a_10":  (0.434, lambda y=None, dc=None: 5.80 + 0.0009 * y, "altitud Y (msnm)"),
}

# K'g por ZONA (no por subzona) -- Tabla 38. Las subzonas de
# TABLA_37_SUBZONAS caen todas en la zona "123" o "5a".
TABLA_38_KG_POR_ZONA = {
    "123": 0.553,
    "5a": None,  # Tabla 38 la da como fórmula K'g = 11·εg^-0.85 (necesita εg,
                 # que a su vez requiere el régimen <3h no reconstruido) --
                 # no hay un K'g fijo utilizable aquí para la zona 5a.
}

NOMBRES_SUBZONAS_37 = {
    "123_1": "123₁ (sierra sur/Cusco)", "123_3": "123₃ (sierra sur/Cusco)",
    "123_5": "123₅ (sierra sur/Cusco)", "123_6": "123₆ (sierra sur/Cusco)",
    "123_8": "123₈ (sierra sur/Cusco)", "123_9": "123₉ (sierra sur/Cusco)",
    "123_10": "123₁₀ (sierra sur/Cusco)", "123_11": "123₁₁ (sierra sur/Cusco)",
    "5a_2": "5a₂", "5a_5": "5a₅", "5a_10": "5a₁₀",
}


def precipitacion_intensidad_zona(subzona: str, tr: float, duracion_h: float,
                                   altitud_m: Optional[float] = None,
                                   distancia_cordillera_km: Optional[float] = None) -> dict:
    """
    Método por zona/subzona -- SOLO para el régimen de 3 a 24 horas y
    SOLO para las subzonas de TABLA_37_SUBZONAS (extracto parcial, ver
    docstring del módulo). Para cualquier otra parte del Perú, use
    precipitacion_intensidad_desde_p24() (no depende de zona).
    """
    if subzona not in TABLA_37_SUBZONAS:
        raise IilaSenamhiZonasError(
            f"No hay coeficientes verificados para la subzona «{subzona}». Este módulo solo "
            f"cubre {', '.join(sorted(TABLA_37_SUBZONAS))}, tomadas de un informe real que no "
            "reproducía la tabla nacional completa del estudio de 1983.")
    if not (3.0 <= duracion_h <= 24.0):
        raise IilaSenamhiZonasError(
            "Este método solo cubre el régimen de 3 a 24 horas del modelo IILA-SENAMHI "
            "(el de menos de 3 horas no se pudo reconstruir de forma confiable de la fuente "
            "disponible -- ver docstring del módulo). Use una duración entre 3 y 24 horas.")
    if tr <= 1:
        raise IilaSenamhiZonasError("El periodo de retorno T debe ser mayor que 1 año.")

    n, a_o_funcion, requisito = TABLA_37_SUBZONAS[subzona]
    if callable(a_o_funcion):
        if requisito and "altitud" in requisito and altitud_m is None:
            raise IilaSenamhiZonasError(
                f"La subzona «{subzona}» necesita la altitud Y (msnm) para calcular «a».")
        if requisito and "cordillera" in requisito and distancia_cordillera_km is None:
            raise IilaSenamhiZonasError(
                f"La subzona «{subzona}» necesita la distancia a la cordillera Dc (km) para "
                "calcular «a».")
        a = a_o_funcion(y=altitud_m, dc=distancia_cordillera_km)
    else:
        a = a_o_funcion
    if a <= 0:
        raise IilaSenamhiZonasError(
            f"El parámetro «a» calculado para «{subzona}» dio {a:.3g} (≤ 0) -- revise la "
            "altitud/distancia ingresada, el rango de validez de la fórmula regional es limitado.")

    zona = subzona.split("_")[0]
    kg = TABLA_38_KG_POR_ZONA.get(zona)
    if kg is None:
        raise IilaSenamhiZonasError(
            f"La zona «{zona}» no tiene un K'g fijo disponible en este módulo (su fórmula "
            "depende de εg, que requiere el régimen <3h no reconstruido -- ver docstring).")

    factor_tr = 1.0 + kg * math.log10(tr)
    p_t = a * factor_tr * duracion_h ** n
    i_t = a * factor_tr * duracion_h ** (n - 1.0)
    return {
        "subzona": subzona, "zona": zona, "n": n, "a": round(a, 4), "kg": kg,
        "tr_anios": tr, "duracion_h": duracion_h,
        "p_t_mm": round(p_t, 3), "i_t_mm_h": round(i_t, 3),
        "nota": ("Tablas 37-38 (IILA-SENAMHI-UNI, 1983), régimen de 3 a 24 horas -- extracto "
                 "parcial, solo para las subzonas listadas en TABLA_37_SUBZONAS."),
    }
