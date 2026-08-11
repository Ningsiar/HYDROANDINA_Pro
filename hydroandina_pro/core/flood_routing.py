# -*- coding: utf-8 -*-
"""
core/flood_routing.py

Tránsito de avenidas (flood routing): propagación de un hidrograma de
crecida a lo largo de un tramo de cauce (tránsito hidrológico en cauce)
o a través de un embalse/laguna (tránsito en vaso).

POR QUÉ IMPORTA: el hidrograma que calcula la Pestaña 7 (SCS/Snyder/
Clark) corresponde a la SALIDA DE LA CUENCA. Si la obra que se está
diseñando está aguas abajo de ese punto -- un puente varios kilómetros
más abajo, una defensa ribereña en otro tramo, o aguas abajo de una
laguna de regulación -- usar ese caudal pico sin transitarlo SOBREESTIMA
el caudal de diseño, porque ignora la atenuación que produce el
almacenamiento del propio cauce o del vaso. El tránsito cuantifica esa
atenuación (reducción del pico) y el retardo (desplazamiento del tiempo
al pico).

MÉTODOS IMPLEMENTADOS:

  1. MUSKINGUM (McCarthy, 1938) — tránsito hidrológico en cauce con
     coeficientes K y X dados por el usuario o calibrados:
         S = K*[X*I + (1-X)*O]
         O2 = C0*I2 + C1*I1 + C2*O1
     con C0 = (-KX + 0.5dt)/D, C1 = (KX + 0.5dt)/D, C2 = (K - KX - 0.5dt)/D
     y D = K - KX + 0.5dt. K tiene unidades de tiempo (h) y representa el
     tiempo de viaje de la onda; X (0 a 0.5) pondera cuánto influye el
     caudal de entrada en el almacenamiento (X=0 es un embalse lineal
     puro, máxima atenuación; X=0.5 es traslación pura sin atenuación).

  2. MUSKINGUM-CUNGE (Cunge, 1969) — variante que NO requiere calibrar K
     y X con hidrogramas observados de entrada y salida (que casi nunca
     existen en cuencas altoandinas no aforadas): los deriva de la
     GEOMETRÍA E HIDRÁULICA del cauce, que sí se puede medir o estimar:
         c = celeridad de la onda cinemática = m * V   (m ~ 5/3 con Manning
             en canal ancho; V = velocidad media del flujo)
         K = Δx / c
         X = 0.5 * [1 - Q / (B * S0 * c * Δx)]
     con Q el caudal de referencia, B el ancho superficial, S0 la
     pendiente del fondo y Δx la longitud del tramo. Esto lo convierte en
     el método de elección para este plugin: se alimenta de datos que las
     otras pestañas ya calculan (pendiente del cauce, longitud, ancho).

  3. PULS MODIFICADO (tránsito en vaso/embalse, "storage indication
     method") — para lagunas de regulación, represas o cualquier
     almacenamiento con una relación conocida entre nivel, volumen
     almacenado y descarga:
         (S1/dt + O1/2) + (I1+I2)/2 - O1 = S2/dt + O2/2
     Se resuelve interpolando en la curva auxiliar [S/dt + O/2] vs O,
     construida a partir de la curva cota-volumen-descarga del vaso.

TRANSPARENCIA / LÍMITES DE VALIDEZ:
  - Muskingum y Muskingum-Cunge son tránsitos HIDROLÓGICOS (agregados):
    no resuelven las ecuaciones de Saint-Venant completas. No representan
    efectos de remanso (curvas de remanso por una estructura aguas abajo),
    ni flujo no permanente rápidamente variado, ni rotura de presa. Para
    esos casos hace falta un modelo hidrodinámico (HEC-RAS unsteady, Iber).
  - Muskingum-Cunge asume onda difusiva/cinemática: válido en cauces con
    pendiente suficiente y sin control aguas abajo -- condición que suelen
    cumplir bien los cauces andinos de fuerte pendiente para los que está
    orientado este plugin, pero que se degrada en tramos muy planos.
  - Se advierte explícitamente cuando la combinación de dt, K y X viola
    las condiciones de estabilidad numérica del esquema (ver
    verificar_estabilidad_muskingum): con parámetros fuera de rango el
    método puede producir oscilaciones o caudales negativos sin sentido
    físico, y es un error clásico no detectarlo.
"""
import math
from typing import Dict, List, Optional, Sequence, Tuple


class FloodRoutingError(Exception):
    pass


# =====================================================================
# MUSKINGUM CLÁSICO
# =====================================================================
def coeficientes_muskingum(k_horas: float, x: float, dt_horas: float) -> dict:
    """
    Coeficientes C0, C1, C2 del esquema de Muskingum. Su suma debe ser
    exactamente 1 (se devuelve para verificarlo: es la comprobación
    estándar de que no hay error aritmético en el cálculo).
    """
    if k_horas <= 0:
        raise FloodRoutingError("K debe ser mayor que 0.")
    if not (0.0 <= x <= 0.5):
        raise FloodRoutingError("X debe estar entre 0 y 0.5 (fuera de ese rango no tiene sentido físico).")
    if dt_horas <= 0:
        raise FloodRoutingError("El intervalo de tiempo dt debe ser mayor que 0.")

    denominador = k_horas - k_horas * x + 0.5 * dt_horas
    if abs(denominador) < 1e-12:
        raise FloodRoutingError("Denominador nulo en los coeficientes de Muskingum; revise K, X y dt.")
    c0 = (-k_horas * x + 0.5 * dt_horas) / denominador
    c1 = (k_horas * x + 0.5 * dt_horas) / denominador
    c2 = (k_horas - k_horas * x - 0.5 * dt_horas) / denominador
    return {"C0": c0, "C1": c1, "C2": c2, "suma": c0 + c1 + c2}


def verificar_estabilidad_muskingum(k_horas: float, x: float, dt_horas: float) -> dict:
    """
    Verifica las condiciones de estabilidad numérica del esquema de
    Muskingum y devuelve las advertencias correspondientes.

    Condición clásica:  2*K*X <= dt <= 2*K*(1-X)
    Si dt < 2KX el coeficiente C0 se vuelve negativo y aparecen
    oscilaciones espurias (incluso caudales negativos) en la salida; si
    dt > 2K(1-X) es C2 el que se vuelve negativo. Es un error muy común
    elegir el dt del hidrograma sin comprobar esto y aceptar como buena
    una salida oscilante.
    """
    limite_inferior = 2.0 * k_horas * x
    limite_superior = 2.0 * k_horas * (1.0 - x)
    advertencias = []
    if dt_horas < limite_inferior:
        advertencias.append(
            f"dt={dt_horas:.3f} h es MENOR que 2·K·X={limite_inferior:.3f} h: el coeficiente C0 sale "
            "negativo y el tránsito puede oscilar o dar caudales negativos. Aumente dt o reduzca X."
        )
    if dt_horas > limite_superior:
        advertencias.append(
            f"dt={dt_horas:.3f} h es MAYOR que 2·K·(1-X)={limite_superior:.3f} h: el coeficiente C2 "
            "sale negativo y el tránsito pierde sentido físico. Reduzca dt."
        )
    return {
        "estable": not advertencias,
        "dt_minimo_recomendado_h": round(limite_inferior, 4),
        "dt_maximo_recomendado_h": round(limite_superior, 4),
        "advertencias": advertencias,
    }


def transitar_muskingum(hidrograma_entrada: Sequence[float], dt_horas: float,
                         k_horas: float, x: float,
                         caudal_inicial_salida: Optional[float] = None) -> dict:
    """
    Transita un hidrograma por el método de Muskingum.

    hidrograma_entrada: caudales de entrada al tramo (m³/s), uno por dt.
    caudal_inicial_salida: caudal de salida en t=0; por defecto se toma
    igual al primero de entrada (supuesto de régimen permanente inicial,
    que es lo habitual cuando el hidrograma arranca del caudal base).
    """
    if len(hidrograma_entrada) < 2:
        raise FloodRoutingError("El hidrograma de entrada debe tener al menos 2 valores.")
    coefs = coeficientes_muskingum(k_horas, x, dt_horas)
    estabilidad = verificar_estabilidad_muskingum(k_horas, x, dt_horas)
    c0, c1, c2 = coefs["C0"], coefs["C1"], coefs["C2"]

    entrada = [float(q) for q in hidrograma_entrada]
    salida = [float(caudal_inicial_salida) if caudal_inicial_salida is not None else entrada[0]]

    for i in range(1, len(entrada)):
        o_siguiente = c0 * entrada[i] + c1 * entrada[i - 1] + c2 * salida[-1]
        # El caudal físico no puede ser negativo. Si el esquema lo produce
        # (parámetros fuera del rango de estabilidad) se acota a 0 y queda
        # constancia en las advertencias de estabilidad, en vez de
        # devolver silenciosamente un caudal negativo.
        salida.append(max(o_siguiente, 0.0))

    # La cola del hidrograma de salida puede seguir descargando después de
    # que la entrada ya volvió a cero: se continúa el tránsito con entrada
    # nula hasta que la salida decae, para no truncar el volumen
    # (mismo problema que se corrigió en el Clark de core/unit_hydrographs.py).
    umbral = max(max(salida) * 0.001, 1e-9)
    pasos_extra, tope = 0, 20 * len(entrada)
    while salida[-1] > umbral and pasos_extra < tope:
        o_siguiente = c2 * salida[-1]
        if o_siguiente >= salida[-1]:
            break  # sin decaimiento: evita un bucle infinito
        salida.append(max(o_siguiente, 0.0))
        pasos_extra += 1

    tiempos = [i * dt_horas for i in range(len(salida))]
    return _resumen_transito(entrada, salida, tiempos, dt_horas, "Muskingum",
                              {**coefs, "K_h": k_horas, "X": x}, estabilidad)


# =====================================================================
# MUSKINGUM-CUNGE
# =====================================================================
def parametros_muskingum_cunge(caudal_referencia_m3_s: float, ancho_superficial_m: float,
                                pendiente_fondo_m_m: float, longitud_tramo_m: float,
                                velocidad_media_m_s: float, exponente_m: float = 5.0 / 3.0) -> dict:
    """
    Deriva K y X de la geometría e hidráulica del cauce (Cunge, 1969),
    en vez de calibrarlos con hidrogramas observados.

    exponente_m: relación entre celeridad y velocidad media, c = m*V.
    5/3 corresponde a la ecuación de Manning en un canal ancho (valor por
    defecto y el más usado); 3/2 correspondería a Chézy.
    """
    if caudal_referencia_m3_s <= 0:
        raise FloodRoutingError("El caudal de referencia debe ser mayor que 0.")
    if ancho_superficial_m <= 0:
        raise FloodRoutingError("El ancho superficial debe ser mayor que 0.")
    if pendiente_fondo_m_m <= 0:
        raise FloodRoutingError("La pendiente del fondo debe ser mayor que 0.")
    if longitud_tramo_m <= 0:
        raise FloodRoutingError("La longitud del tramo debe ser mayor que 0.")
    if velocidad_media_m_s <= 0:
        raise FloodRoutingError("La velocidad media debe ser mayor que 0.")

    celeridad = exponente_m * velocidad_media_m_s
    k_horas = (longitud_tramo_m / celeridad) / 3600.0
    x = 0.5 * (1.0 - caudal_referencia_m3_s /
               (ancho_superficial_m * pendiente_fondo_m_m * celeridad * longitud_tramo_m))

    # X negativo (posible con tramos cortos o pendientes muy suaves) no
    # tiene sentido en el esquema de Muskingum; se acota a 0, que es el
    # caso de máxima atenuación (embalse lineal puro), y se deja
    # constancia para que el usuario sepa que hubo acotamiento.
    x_acotado = min(max(x, 0.0), 0.5)
    return {
        "K_h": k_horas,
        "X": x_acotado,
        "X_calculado_sin_acotar": x,
        "celeridad_m_s": celeridad,
        "fue_acotado": abs(x_acotado - x) > 1e-12,
        "longitud_tramo_m": longitud_tramo_m,
        "velocidad_media_m_s": velocidad_media_m_s,
    }


def _discretizacion_courant(k_total_horas: float, dt_horas: float,
                             max_subtramos: int = 60, max_refinamiento: int = 60) -> Tuple[int, int]:
    """
    Elige el número de SUBTRAMOS (N) en que dividir el tramo y el factor
    de REFINAMIENTO temporal (f) para que el número de Courant valga 1.

    Por qué exactamente 1: en Muskingum-Cunge se toma Δx = c·Δt (Courant
    unitario), con lo que K de cada subtramo vale K_sub = Δx/c = Δt. Al
    sustituir K = Δt en las dos condiciones de estabilidad del esquema de
    Muskingum,
        2·K·X <= Δt   ->   2·Δt·X <= Δt   ->   X <= 0.5
        Δt <= 2·K·(1-X)  ->  Δt <= 2·Δt·(1-X)  ->  X <= 0.5
    AMBAS se reducen a X <= 0.5, que se cumple siempre. Es decir, con
    Courant unitario el esquema es incondicionalmente estable -- por eso
    no basta con calcular K y X y aplicarlos tal cual sobre el tramo
    completo: hay que discretizarlo.

    Como K_total/Δt = N/f, se busca una fracción N/f que aproxime esa
    razón (con denominador acotado para no refinar el tiempo de forma
    absurda).
    """
    razon = k_total_horas / dt_horas
    if razon <= 0:
        return 1, 1
    try:
        from fractions import Fraction
        fraccion = Fraction(razon).limit_denominator(max_refinamiento)
        n_subtramos = max(1, min(fraccion.numerator, max_subtramos))
        f_refinamiento = max(1, min(fraccion.denominator, max_refinamiento))
    except Exception:
        n_subtramos = max(1, min(int(round(razon)), max_subtramos))
        f_refinamiento = 1
    return n_subtramos, f_refinamiento


def _interpolar_hidrograma(hidrograma: Sequence[float], factor: int) -> List[float]:
    """Interpola linealmente un hidrograma para refinar su paso de tiempo
    por un factor entero (factor=3 -> 3 veces más puntos)."""
    if factor <= 1:
        return [float(q) for q in hidrograma]
    fino = []
    for i in range(len(hidrograma) - 1):
        q0, q1 = float(hidrograma[i]), float(hidrograma[i + 1])
        for j in range(factor):
            fino.append(q0 + (q1 - q0) * j / factor)
    fino.append(float(hidrograma[-1]))
    return fino


def transitar_muskingum_cunge(hidrograma_entrada: Sequence[float], dt_horas: float,
                               caudal_referencia_m3_s: float, ancho_superficial_m: float,
                               pendiente_fondo_m_m: float, longitud_tramo_m: float,
                               velocidad_media_m_s: float,
                               exponente_m: float = 5.0 / 3.0) -> dict:
    """
    Transita un hidrograma por Muskingum-Cunge: deriva K y X de la
    hidráulica del tramo (sin necesidad de calibrar con hidrogramas
    observados) y aplica el esquema de Muskingum SUBDIVIDIENDO el tramo
    en subtramos con número de Courant unitario -- ver
    _discretizacion_courant para el porqué.

    Aplicar K y X directamente sobre el tramo completo, sin subdividir,
    es un error clásico: en cauces de fuerte pendiente (los de este
    plugin) X sale muy cerca de 0.5 y el esquema, fuera de su rango de
    estabilidad, llega a devolver un caudal de salida MAYOR que el de
    entrada -- físicamente imposible, porque un tránsito solo puede
    atenuar el pico, nunca amplificarlo.
    """
    params_globales = parametros_muskingum_cunge(
        caudal_referencia_m3_s, ancho_superficial_m, pendiente_fondo_m_m,
        longitud_tramo_m, velocidad_media_m_s, exponente_m,
    )
    celeridad = params_globales["celeridad_m_s"]
    k_total = params_globales["K_h"]

    n_subtramos, f_refinamiento = _discretizacion_courant(k_total, dt_horas)
    dt_interno = dt_horas / f_refinamiento
    longitud_subtramo = longitud_tramo_m / n_subtramos
    k_subtramo = k_total / n_subtramos

    # X se recalcula para la longitud del SUBTRAMO, no la del tramo
    # completo: al ser Δx menor, el término Q/(B·S0·c·Δx) crece y X baja,
    # que es justamente lo que devuelve el esquema a su rango estable.
    x_subtramo = 0.5 * (1.0 - caudal_referencia_m3_s /
                        (ancho_superficial_m * pendiente_fondo_m_m * celeridad * longitud_subtramo))
    x_sin_acotar = x_subtramo
    x_subtramo = min(max(x_subtramo, 0.0), 0.5)

    entrada_original = [float(q) for q in hidrograma_entrada]
    caudal = _interpolar_hidrograma(entrada_original, f_refinamiento)

    # Tránsito sucesivo por cada subtramo.
    resultado_parcial = None
    for _ in range(n_subtramos):
        resultado_parcial = transitar_muskingum(caudal, dt_interno, k_subtramo, x_subtramo)
        caudal = resultado_parcial["caudal_salida_m3_s"]

    salida_fina = caudal
    # IMPORTANTE: el resumen (caudal pico, atenuación, retardo, volumen) se
    # calcula sobre la serie FINA, no sobre una diezmada al dt original.
    # Diezmar antes de medir el pico introduce un artefacto de muestreo:
    # cada subtramo desplaza el hidrograma una fracción de dt, así que al
    # tomar 1 de cada f valores la fase del pico respecto de la rejilla
    # cambia con el número de subtramos, y la atenuación medida oscilaba
    # según la paridad de N en vez de crecer de forma monótona con la
    # longitud del tramo.
    entrada_fina = _interpolar_hidrograma(entrada_original, f_refinamiento)
    if len(entrada_fina) < len(salida_fina):
        entrada_fina = entrada_fina + [0.0] * (len(salida_fina) - len(entrada_fina))
    tiempos = [i * dt_interno for i in range(len(salida_fina))]

    numero_courant = dt_interno / k_subtramo if k_subtramo > 0 else float("inf")
    estabilidad = verificar_estabilidad_muskingum(k_subtramo, x_subtramo, dt_interno)
    estabilidad["numero_courant"] = round(numero_courant, 4)

    resultado = _resumen_transito(
        entrada_fina[:len(salida_fina)], salida_fina, tiempos, dt_interno, "Muskingum-Cunge",
        {
            "K_total_h": round(k_total, 4), "K_subtramo_h": round(k_subtramo, 4),
            "X_subtramo": round(x_subtramo, 5), "X_sin_acotar": round(x_sin_acotar, 5),
            "n_subtramos": n_subtramos, "refinamiento_temporal": f_refinamiento,
            "dt_interno_h": round(dt_interno, 5),
            "longitud_subtramo_m": round(longitud_subtramo, 2),
            "celeridad_m_s": round(celeridad, 4),
            "numero_courant": round(numero_courant, 4),
            "longitud_tramo_m": longitud_tramo_m,
            "velocidad_media_m_s": velocidad_media_m_s,
        },
        estabilidad,
    )

    # Guarda física: un tránsito NUNCA puede amplificar el pico. Si esto
    # ocurre, es señal de un problema numérico y debe avisarse, no
    # devolverse en silencio como si fuera un resultado válido.
    if resultado["Qp_salida_m3_s"] > resultado["Qp_entrada_m3_s"] * 1.001:
        resultado["estabilidad"]["estable"] = False
        resultado["estabilidad"]["advertencias"].append(
            f"El caudal pico de SALIDA ({resultado['Qp_salida_m3_s']} m³/s) resultó mayor que el de "
            f"ENTRADA ({resultado['Qp_entrada_m3_s']} m³/s), lo cual es físicamente imposible en un "
            "tránsito. Indica un problema numérico: pruebe con un dt menor en el hidrograma de "
            "entrada, o revise la longitud del tramo, el ancho superficial y la pendiente."
        )
    if params_globales["fue_acotado"] or abs(x_subtramo - x_sin_acotar) > 1e-12:
        resultado["estabilidad"]["advertencias"].append(
            f"El X derivado de la hidráulica del subtramo salió {x_sin_acotar:.4f}, fuera del rango "
            "físico [0, 0.5], y se acotó. Suele indicar un subtramo demasiado corto para el caudal "
            "considerado, o una pendiente muy suave: revise longitud, ancho superficial y pendiente."
        )
    return resultado


# =====================================================================
# PULS MODIFICADO (tránsito en vaso/embalse)
# =====================================================================
def transitar_puls(hidrograma_entrada: Sequence[float], dt_horas: float,
                    almacenamiento_m3: Sequence[float], descarga_m3_s: Sequence[float],
                    almacenamiento_inicial_m3: float = 0.0) -> dict:
    """
    Tránsito en vaso por el método de Puls modificado ("storage
    indication"). Requiere la curva del embalse en forma de dos listas
    paralelas: almacenamiento (m³) y descarga del vertedero/obra de
    salida (m³/s) correspondiente a ese almacenamiento.

    Se construye la función auxiliar  Φ(O) = S/dt + O/2  y en cada paso
    se despeja Φ2 = Φ1 - O1 + (I1+I2)/2, obteniendo O2 por interpolación
    inversa en esa curva.
    """
    if len(hidrograma_entrada) < 2:
        raise FloodRoutingError("El hidrograma de entrada debe tener al menos 2 valores.")
    if len(almacenamiento_m3) != len(descarga_m3_s):
        raise FloodRoutingError(
            "Las listas de almacenamiento y descarga deben tener la misma cantidad de puntos.")
    if len(almacenamiento_m3) < 2:
        raise FloodRoutingError("La curva del embalse necesita al menos 2 puntos.")
    if dt_horas <= 0:
        raise FloodRoutingError("El intervalo de tiempo dt debe ser mayor que 0.")

    dt_s = dt_horas * 3600.0
    puntos = sorted(zip(almacenamiento_m3, descarga_m3_s), key=lambda par: par[0])
    s_lista = [float(p[0]) for p in puntos]
    o_lista = [float(p[1]) for p in puntos]
    if any(o_lista[i + 1] < o_lista[i] for i in range(len(o_lista) - 1)):
        raise FloodRoutingError(
            "La descarga debe ser creciente (o al menos no decreciente) con el almacenamiento: "
            "revise la curva cota-volumen-descarga del embalse.")

    # Curva auxiliar Φ = S/dt + O/2, monótona creciente por construcción.
    phi_lista = [s / dt_s + o / 2.0 for s, o in zip(s_lista, o_lista)]

    def interpolar(x_objetivo, xs, ys):
        if x_objetivo <= xs[0]:
            return ys[0]
        if x_objetivo >= xs[-1]:
            # Extrapolación lineal con la pendiente del último tramo, para
            # no "aplanar" artificialmente la descarga si la crecida supera
            # el rango tabulado -- pero se registra como desbordamiento.
            if len(xs) >= 2 and xs[-1] != xs[-2]:
                pendiente = (ys[-1] - ys[-2]) / (xs[-1] - xs[-2])
                return ys[-1] + pendiente * (x_objetivo - xs[-1])
            return ys[-1]
        for i in range(len(xs) - 1):
            if xs[i] <= x_objetivo <= xs[i + 1]:
                if xs[i + 1] == xs[i]:
                    return ys[i]
                frac = (x_objetivo - xs[i]) / (xs[i + 1] - xs[i])
                return ys[i] + frac * (ys[i + 1] - ys[i])
        return ys[-1]

    entrada = [float(q) for q in hidrograma_entrada]
    o_actual = interpolar(almacenamiento_inicial_m3, s_lista, o_lista)
    phi_actual = almacenamiento_inicial_m3 / dt_s + o_actual / 2.0
    salida = [o_actual]
    almacenamientos = [float(almacenamiento_inicial_m3)]
    excedio_curva = False

    for i in range(1, len(entrada)):
        phi_siguiente = phi_actual - o_actual + 0.5 * (entrada[i - 1] + entrada[i])
        if phi_siguiente > phi_lista[-1]:
            excedio_curva = True
        o_siguiente = max(interpolar(phi_siguiente, phi_lista, o_lista), 0.0)
        s_siguiente = max((phi_siguiente - o_siguiente / 2.0) * dt_s, 0.0)
        salida.append(o_siguiente)
        almacenamientos.append(s_siguiente)
        phi_actual, o_actual = phi_siguiente, o_siguiente

    # Continuación del vaciado tras terminar la entrada.
    umbral = max(max(salida) * 0.001, 1e-9)
    pasos_extra, tope = 0, 20 * len(entrada)
    while salida[-1] > umbral and pasos_extra < tope:
        phi_siguiente = phi_actual - o_actual
        if phi_siguiente <= 0:
            break
        o_siguiente = max(interpolar(phi_siguiente, phi_lista, o_lista), 0.0)
        if o_siguiente >= o_actual and pasos_extra > 0:
            break
        s_siguiente = max((phi_siguiente - o_siguiente / 2.0) * dt_s, 0.0)
        salida.append(o_siguiente)
        almacenamientos.append(s_siguiente)
        phi_actual, o_actual = phi_siguiente, o_siguiente
        pasos_extra += 1

    tiempos = [i * dt_horas for i in range(len(salida))]
    estabilidad = {"estable": True, "advertencias": []}
    if excedio_curva:
        estabilidad["estable"] = False
        estabilidad["advertencias"].append(
            "La crecida superó el rango de la curva cota-volumen-descarga ingresada: la descarga se "
            "extrapoló linealmente más allá del último punto tabulado. Extienda la curva del embalse "
            "hasta cubrir el nivel máximo alcanzado, o el resultado no será confiable (típicamente "
            "significa que el vaso desbordaría por coronación)."
        )

    resultado = _resumen_transito(entrada, salida, tiempos, dt_horas, "Puls modificado (vaso)",
                                  {"puntos_curva_embalse": len(s_lista),
                                   "S_inicial_m3": almacenamiento_inicial_m3}, estabilidad)
    resultado["almacenamiento_m3"] = [round(s, 2) for s in almacenamientos]
    resultado["almacenamiento_maximo_m3"] = round(max(almacenamientos), 2)
    resultado["almacenamiento_maximo_hm3"] = round(max(almacenamientos) / 1e6, 5)
    return resultado


# =====================================================================
# RESUMEN COMÚN A TODOS LOS MÉTODOS
# =====================================================================
def _volumen_trapecio(caudales: Sequence[float], dt_horas: float) -> float:
    """Volumen (m³) bajo un hidrograma por la regla del trapecio."""
    if len(caudales) < 2:
        return (caudales[0] * dt_horas * 3600.0) if caudales else 0.0
    dt_s = dt_horas * 3600.0
    return dt_s * (sum(caudales) - 0.5 * caudales[0] - 0.5 * caudales[-1])


def _resumen_transito(entrada: List[float], salida: List[float], tiempos: List[float],
                       dt_horas: float, metodo: str, parametros: dict,
                       estabilidad: dict) -> dict:
    """
    Arma el resultado común: hidrogramas, caudales pico, atenuación,
    retardo y verificación de conservación de volumen.

    LA VERIFICACIÓN DE VOLUMEN ES IMPORTANTE: un tránsito hidrológico
    ATENÚA el pico pero NO debe crear ni destruir agua -- el volumen de
    salida tiene que coincidir con el de entrada (salvo el pequeño
    residuo que quede almacenado al final del cómputo). Si no coincide,
    hay un error en los parámetros o en el esquema, y es justo el tipo de
    fallo que pasa desapercibido si solo se mira el caudal pico.
    """
    qp_entrada = max(entrada)
    qp_salida = max(salida)
    idx_entrada = entrada.index(qp_entrada)
    idx_salida = salida.index(qp_salida)

    volumen_entrada = _volumen_trapecio(entrada, dt_horas)
    volumen_salida = _volumen_trapecio(salida, dt_horas)
    error_volumen_pct = (
        abs(volumen_salida - volumen_entrada) / volumen_entrada * 100.0 if volumen_entrada > 0 else 0.0
    )

    atenuacion_pct = ((qp_entrada - qp_salida) / qp_entrada * 100.0) if qp_entrada > 0 else 0.0
    retardo_h = (idx_salida - idx_entrada) * dt_horas

    return {
        "metodo": metodo,
        "parametros": dict(parametros),
        "estabilidad": estabilidad,
        "dt_h": dt_horas,
        "tiempos_h": [round(t, 4) for t in tiempos],
        "caudal_entrada_m3_s": [round(q, 4) for q in entrada],
        "caudal_salida_m3_s": [round(q, 4) for q in salida],
        "Qp_entrada_m3_s": round(qp_entrada, 3),
        "Qp_salida_m3_s": round(qp_salida, 3),
        "atenuacion_m3_s": round(qp_entrada - qp_salida, 3),
        "atenuacion_pct": round(atenuacion_pct, 2),
        "tiempo_pico_entrada_h": round(idx_entrada * dt_horas, 3),
        "tiempo_pico_salida_h": round(idx_salida * dt_horas, 3),
        "retardo_pico_h": round(retardo_h, 3),
        "volumen_entrada_m3": round(volumen_entrada, 1),
        "volumen_salida_m3": round(volumen_salida, 1),
        "volumen_entrada_hm3": round(volumen_entrada / 1e6, 5),
        "volumen_salida_hm3": round(volumen_salida / 1e6, 5),
        "error_volumen_pct": round(error_volumen_pct, 3),
        "conserva_volumen": error_volumen_pct < 2.0,
    }
