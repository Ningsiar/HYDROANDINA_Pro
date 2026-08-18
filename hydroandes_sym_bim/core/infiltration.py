# -*- coding: utf-8 -*-
"""
core/infiltration.py

Modelos de INFILTRACIÓN para el cálculo de pérdidas: Green-Ampt (1911) y
Horton (1940). Son una alternativa al método del número de curva SCS que
el plugin ya usa (core/curve_number.py + core/unit_hydrographs.py) para
convertir el hietograma de lluvia TOTAL en lluvia EFECTIVA, que es la que
alimenta el hidrograma unitario y produce el caudal pico:

    Hietograma → [PÉRDIDAS: SCS-CN | Green-Ampt | Horton] → Lluvia efectiva
               → Hidrograma unitario (SCS/Snyder/Clark) → Qp

POR QUÉ IMPORTA ELEGIR EL MODELO DE PÉRDIDAS:
El SCS-CN es un método AGREGADO de evento: aplica una abstracción que
depende solo de la lámina acumulada, no de la intensidad instantánea. Por
eso dos tormentas con la misma lámina total dan la misma lluvia efectiva
aunque una sea corta e intensa y la otra larga y suave. Green-Ampt y
Horton, en cambio, comparan la INTENSIDAD de cada intervalo contra la
capacidad de infiltración del momento: una tormenta intensa satura el
suelo antes y genera más escorrentía que una suave de igual lámina. En
cuencas altoandinas, donde las tormentas convectivas son cortas e
intensas, esa diferencia se traslada directamente al caudal de diseño.

  GREEN-AMPT (1911) — físicamente basado. Modela un frente húmedo que
  avanza en un suelo homogéneo:
        f = K * (1 + psi*delta_theta / F)
  con f la capacidad de infiltración (mm/h), K la conductividad
  hidráulica saturada (mm/h), psi la altura de succión del frente húmedo
  (mm), delta_theta el déficit de humedad (adimensional, porosidad
  efectiva por la fracción no saturada) y F la infiltración acumulada
  (mm). La relación entre F y el tiempo es IMPLÍCITA:
        F - psi*delta_theta * ln(1 + F/(psi*delta_theta)) = K*t
  y se resuelve numéricamente (Newton-Raphson).

  HORTON (1940) — empírico. La capacidad de infiltración decae
  exponencialmente desde un valor inicial hasta uno de equilibrio:
        f(t) = fc + (f0 - fc) * exp(-k*t)
        F(t) = fc*t + ((f0 - fc)/k) * (1 - exp(-k*t))

SUTILEZA QUE ESTE MÓDULO SÍ RESUELVE (y que muchas implementaciones de
libro de texto omiten): tanto f(t) de Horton como F(t) de Green-Ampt
están escritas en función del TIEMPO suponiendo ENCHARCAMIENTO CONTINUO
desde t=0, es decir, que la lluvia siempre supera la capacidad de
infiltración. En un hietograma real hay intervalos de lluvia débil o
nula en los que toda el agua infiltra y la capacidad NO se consume al
ritmo que marca el reloj. Aplicar f(t) con el tiempo de reloj
subestima la infiltración -- y por tanto SOBREESTIMA la escorrentía y el
caudal pico. Aquí se trabaja siempre con la infiltración ACUMULADA F
como variable de estado:
  - en Horton se invierte F(t) por Newton-Raphson para obtener el
    "tiempo equivalente" que corresponde al F ya acumulado, y desde ahí
    se avanza;
  - en Green-Ampt se detecta el instante de encharcamiento dentro de
    cada intervalo (Chow, Maidment & Mays, "Applied Hydrology", cap. 4-5)
    y se integra la ecuación implícita solo a partir de ese instante.

TRANSPARENCIA: Green-Ampt supone suelo homogéneo, humedad inicial
uniforme y frente húmedo abrupto; no representa suelos estratificados,
macroporos ni flujo preferencial. Horton es puramente empírico: sus tres
parámetros deben calibrarse con datos locales de infiltración
(infiltrómetro) y los valores de referencia por grupo hidrológico que se
listan aquí son solo un punto de partida orientativo.
"""
import math
from typing import Dict, List, Optional, Sequence, Tuple


class InfiltrationError(Exception):
    pass


# ---------------------------------------------------------------------
# Tablas de parámetros de referencia
# ---------------------------------------------------------------------
# Green-Ampt por clase textural (Rawls, Brakensiek & Miller, 1983,
# "Green-Ampt infiltration parameters from soils data", ASCE Journal of
# Hydraulic Engineering) -- la tabla estándar, también usada por HEC-HMS.
# Formato: clave -> (nombre, K en mm/h, psi en mm, porosidad efectiva)
PARAMETROS_GREEN_AMPT = {
    "arena":              ("Arena",                        117.8,  49.5, 0.417),
    "arena_franca":       ("Arena franca",                   29.9,  61.3, 0.401),
    "franco_arenoso":     ("Franco arenoso",                 10.9, 110.1, 0.412),
    "franco":             ("Franco",                          3.4,  88.9, 0.434),
    "franco_limoso":      ("Franco limoso",                   6.5, 166.8, 0.486),
    "franco_arcillo_aren": ("Franco arcillo-arenoso",          1.5, 218.5, 0.330),
    "franco_arcilloso":   ("Franco arcilloso",                1.0, 208.8, 0.309),
    "franco_arcillo_lim": ("Franco arcillo-limoso",           1.0, 273.0, 0.432),
    "arcillo_arenoso":    ("Arcillo-arenoso",                 0.6, 239.0, 0.321),
    "arcillo_limoso":     ("Arcillo-limoso",                  0.5, 292.2, 0.423),
    "arcilla":            ("Arcilla",                         0.3, 316.3, 0.385),
}

# Horton por grupo hidrológico de suelo SCS (A/B/C/D) -- los mismos
# grupos que ya usa la Pestaña 3 del plugin para el número de curva, para
# que el usuario pueda reutilizar esa clasificación.
# Formato: grupo -> (descripción, f0 en mm/h, fc en mm/h)
PARAMETROS_HORTON = {
    "A": ("Grupo A — alta infiltración (arenas, gravas profundas)", 250.0, 25.0),
    "B": ("Grupo B — infiltración moderada (francos arenosos)",     200.0, 13.0),
    "C": ("Grupo C — infiltración lenta (francos arcillosos)",      125.0,  6.0),
    "D": ("Grupo D — muy lenta (arcillas, roca somera)",             75.0,  3.0),
}

# Constante de decaimiento k de Horton (1/h). El valor más citado en la
# bibliografía es 4.14 1/h (equivalente a 0.069 1/min); el rango usual va
# de 2 a 7 1/h y debe calibrarse localmente.
K_HORTON_DEFAULT = 4.14


def _validar_hietograma(hietograma_mm: Sequence[float], dt_h: float) -> List[float]:
    if dt_h <= 0:
        raise InfiltrationError("El intervalo de tiempo dt debe ser mayor que 0.")
    if not hietograma_mm:
        raise InfiltrationError("El hietograma no puede estar vacío.")
    serie = [float(p) for p in hietograma_mm]
    if any(p < 0 for p in serie):
        raise InfiltrationError("El hietograma no puede contener incrementos de lluvia negativos.")
    return serie


# ---------------------------------------------------------------------
# GREEN-AMPT
# ---------------------------------------------------------------------
def _resolver_green_ampt_implicita(f_inicial: float, k_mm_h: float, succion_por_deficit: float,
                                    dt_h: float, tol: float = 1e-9, max_iter: int = 80) -> float:
    """
    Resuelve por Newton-Raphson la ecuación implícita de Green-Ampt para
    la infiltración acumulada al final de un intervalo ENCHARCADO:

        F2 - F1 - psi*dtheta * ln((F2 + psi*dtheta)/(F1 + psi*dtheta)) = K*dt

    La derivada es g'(F2) = 1 - psi*dtheta/(F2 + psi*dtheta), siempre
    positiva para F2 > 0, así que la convergencia desde F1 + K*dt es
    rápida y estable.
    """
    sd = succion_por_deficit
    objetivo = k_mm_h * dt_h
    f2 = f_inicial + objetivo  # semilla
    for _ in range(max_iter):
        if f2 + sd <= 0:
            f2 = f_inicial + objetivo
            break
        g = (f2 - f_inicial) - sd * math.log((f2 + sd) / (f_inicial + sd)) - objetivo
        dg = 1.0 - sd / (f2 + sd)
        if abs(dg) < 1e-14:
            break
        paso = g / dg
        f2 -= paso
        if f2 <= f_inicial:
            f2 = f_inicial + 1e-9
        if abs(paso) < tol:
            break
    return max(f2, f_inicial)


def infiltracion_green_ampt(hietograma_mm: Sequence[float], dt_h: float,
                             conductividad_k_mm_h: float, succion_psi_mm: float,
                             deficit_humedad: float,
                             infiltracion_acumulada_inicial_mm: float = 0.0) -> dict:
    """
    Aplica Green-Ampt a un hietograma de lluvia total, con detección del
    instante de encharcamiento dentro de cada intervalo.

    deficit_humedad (delta_theta): porosidad efectiva por la fracción no
        saturada. 1.0 x porosidad efectiva = suelo inicialmente muy seco;
        valores menores = suelo previamente húmedo (menos capacidad de
        almacenamiento y por tanto más escorrentía).
    """
    serie = _validar_hietograma(hietograma_mm, dt_h)
    if conductividad_k_mm_h <= 0:
        raise InfiltrationError("La conductividad hidráulica K debe ser mayor que 0.")
    if succion_psi_mm <= 0:
        raise InfiltrationError("La succión del frente húmedo psi debe ser mayor que 0.")
    if not (0.0 < deficit_humedad <= 1.0):
        raise InfiltrationError("El déficit de humedad debe estar entre 0 y 1.")

    sd = succion_psi_mm * deficit_humedad  # psi * delta_theta, en mm
    f_acum = float(infiltracion_acumulada_inicial_mm)
    infiltracion, escorrentia, capacidad = [], [], []
    paso_encharcamiento = None

    for indice, lluvia in enumerate(serie):
        intensidad = lluvia / dt_h  # mm/h
        if lluvia <= 0:
            infiltracion.append(0.0)
            escorrentia.append(0.0)
            capacidad.append(
                conductividad_k_mm_h * (1.0 + sd / f_acum) if f_acum > 0 else float("inf"))
            continue

        # Capacidad de infiltración al inicio del intervalo.
        cap_inicial = (conductividad_k_mm_h * (1.0 + sd / f_acum)) if f_acum > 0 else float("inf")
        capacidad.append(cap_inicial if math.isfinite(cap_inicial) else intensidad)

        if intensidad <= conductividad_k_mm_h:
            # La intensidad no supera ni la conductividad saturada: nunca
            # habrá encharcamiento en este intervalo, todo infiltra.
            f_acum += lluvia
            infiltracion.append(lluvia)
            escorrentia.append(0.0)
            continue

        if intensidad <= cap_inicial:
            # Al inicio del intervalo la capacidad todavía supera a la
            # intensidad: puede haber encharcamiento A MITAD del intervalo.
            # F de encharcamiento (Chow et al.): Fp = K*psi*dtheta/(i - K).
            f_encharcamiento = (conductividad_k_mm_h * sd) / (intensidad - conductividad_k_mm_h)
            if f_encharcamiento >= f_acum + lluvia:
                # No se alcanza dentro de este intervalo: todo infiltra.
                f_acum += lluvia
                infiltracion.append(lluvia)
                escorrentia.append(0.0)
                continue
            # Se encharca a mitad del intervalo: hasta Fp todo infiltra,
            # y el resto del intervalo se integra con la ecuación implícita.
            dt_hasta_encharcar = (f_encharcamiento - f_acum) / intensidad
            dt_restante = dt_h - dt_hasta_encharcar
            f_tras_encharcar = _resolver_green_ampt_implicita(
                f_encharcamiento, conductividad_k_mm_h, sd, dt_restante)
            infiltrado = f_tras_encharcar - f_acum
            if paso_encharcamiento is None:
                paso_encharcamiento = indice
        else:
            # Ya está encharcado desde el inicio del intervalo.
            f_final = _resolver_green_ampt_implicita(f_acum, conductividad_k_mm_h, sd, dt_h)
            infiltrado = f_final - f_acum
            if paso_encharcamiento is None:
                paso_encharcamiento = indice

        # La infiltración nunca puede superar la lluvia disponible.
        infiltrado = min(max(infiltrado, 0.0), lluvia)
        f_acum += infiltrado
        infiltracion.append(infiltrado)
        escorrentia.append(lluvia - infiltrado)

    return _resumen_infiltracion(
        serie, infiltracion, escorrentia, capacidad, dt_h, "Green-Ampt (1911)",
        {"K_mm_h": conductividad_k_mm_h, "psi_mm": succion_psi_mm,
         "delta_theta": deficit_humedad, "psi_x_delta_theta_mm": round(sd, 3)},
        paso_encharcamiento)


# ---------------------------------------------------------------------
# HORTON
# ---------------------------------------------------------------------
def _tiempo_equivalente_horton(f_acum: float, f0: float, fc: float, k: float,
                                tol: float = 1e-9, max_iter: int = 80) -> float:
    """
    Invierte por Newton-Raphson la infiltración acumulada de Horton
        F(t) = fc*t + ((f0 - fc)/k) * (1 - exp(-k*t))
    para obtener el "tiempo equivalente" que corresponde a un F ya
    acumulado.

    ES LA PIEZA CLAVE para no subestimar la infiltración: la capacidad de
    Horton debe decaer en función del agua REALMENTE infiltrada, no del
    tiempo de reloj. Si en el hietograma hay intervalos secos o de lluvia
    débil, el tiempo de reloj avanza pero la capacidad casi no se
    consume, y usar t directamente daría una capacidad artificialmente
    baja (y por tanto más escorrentía y más caudal pico de la real).
    """
    if f_acum <= 0:
        return 0.0
    delta = f0 - fc
    t = f_acum / max(fc, 1e-9)  # semilla: si solo actuara fc
    for _ in range(max_iter):
        valor = fc * t + (delta / k) * (1.0 - math.exp(-k * t)) - f_acum
        derivada = fc + delta * math.exp(-k * t)
        if abs(derivada) < 1e-14:
            break
        paso = valor / derivada
        t -= paso
        if t < 0:
            t = 0.0
        if abs(paso) < tol:
            break
    return max(t, 0.0)


def infiltracion_horton(hietograma_mm: Sequence[float], dt_h: float,
                         f0_mm_h: float, fc_mm_h: float, k_decaimiento: float = K_HORTON_DEFAULT,
                         infiltracion_acumulada_inicial_mm: float = 0.0) -> dict:
    """
    Aplica Horton a un hietograma de lluvia total, avanzando sobre la
    infiltración ACUMULADA (no sobre el tiempo de reloj) para respetar
    los intervalos en los que la lluvia no llega a saturar la capacidad.
    """
    serie = _validar_hietograma(hietograma_mm, dt_h)
    if f0_mm_h <= 0 or fc_mm_h <= 0:
        raise InfiltrationError("Las capacidades f0 y fc deben ser mayores que 0.")
    if fc_mm_h > f0_mm_h:
        raise InfiltrationError(
            "La capacidad final fc no puede ser mayor que la inicial f0 (la capacidad DECAE con el tiempo).")
    if k_decaimiento <= 0:
        raise InfiltrationError("La constante de decaimiento k debe ser mayor que 0.")

    delta = f0_mm_h - fc_mm_h
    f_acum = float(infiltracion_acumulada_inicial_mm)
    infiltracion, escorrentia, capacidad = [], [], []
    paso_encharcamiento = None

    for indice, lluvia in enumerate(serie):
        intensidad = lluvia / dt_h
        t_eq = _tiempo_equivalente_horton(f_acum, f0_mm_h, fc_mm_h, k_decaimiento)
        cap_actual = fc_mm_h + delta * math.exp(-k_decaimiento * t_eq)
        capacidad.append(round(cap_actual, 4))

        if lluvia <= 0:
            infiltracion.append(0.0)
            escorrentia.append(0.0)
            continue

        if intensidad <= cap_actual:
            # Toda la lluvia infiltra: la capacidad se consume solo por lo
            # realmente infiltrado (esto es lo que evita el sesgo).
            infiltrado = lluvia
        else:
            # Encharcado: infiltra según la curva de Horton, integrando
            # entre el tiempo equivalente actual y t_eq + dt.
            f_al_final = (fc_mm_h * (t_eq + dt_h)
                          + (delta / k_decaimiento) * (1.0 - math.exp(-k_decaimiento * (t_eq + dt_h))))
            infiltrado = min(f_al_final - f_acum, lluvia)
            if paso_encharcamiento is None:
                paso_encharcamiento = indice

        infiltrado = max(infiltrado, 0.0)
        f_acum += infiltrado
        infiltracion.append(infiltrado)
        escorrentia.append(lluvia - infiltrado)

    return _resumen_infiltracion(
        serie, infiltracion, escorrentia, capacidad, dt_h, "Horton (1940)",
        {"f0_mm_h": f0_mm_h, "fc_mm_h": fc_mm_h, "k_1_h": k_decaimiento},
        paso_encharcamiento)


# ---------------------------------------------------------------------
# PHILIP (1957)
# ---------------------------------------------------------------------
def infiltracion_philip(hietograma_mm: Sequence[float], dt_h: float,
                         sorptividad_mm_h05: float, factor_gravedad_a_mm_h: float,
                         infiltracion_acumulada_inicial_mm: float = 0.0) -> dict:
    """
    Solución analítica simplificada de la ecuación de Richards propuesta
    por Philip (1957), que separa la infiltración en dos fases: la
    dominada por la succión capilar (sorptividad) y la dominada por la
    gravedad.

        f(t) = (1/2)*S*t^(-1/2) + A          [capacidad, mm/h]
        F(t) = S*t^(1/2) + A*t                [acumulada, mm]

    S: sorptividad (mm/h^0.5), capacidad del suelo seco de absorber agua
       por capilaridad.
    A: factor de transmisibilidad por gravedad (mm/h); la bibliografía lo
       estima entre 0.38 y 0.8 veces la conductividad saturada Ks.

    Igual que en Horton, se avanza sobre la infiltración ACUMULADA y no
    sobre el tiempo de reloj: se invierte F(t) para hallar el tiempo
    equivalente al F ya infiltrado. Aquí la inversión SÍ es analítica,
    porque F(t) = S*sqrt(t) + A*t es una cuadrática en sqrt(t):
        sqrt(t) = (-S + sqrt(S^2 + 4*A*F)) / (2*A)
    lo que evita cualquier iteración numérica.

    OJO: f(t) diverge a infinito en t=0 (el término S/(2*sqrt(t))), así
    que en el primer intervalo la capacidad se toma como la infiltración
    acumulada del intervalo dividida por su duración -- que es el valor
    medio correcto -- en vez de evaluar f en t=0.
    """
    serie = _validar_hietograma(hietograma_mm, dt_h)
    if sorptividad_mm_h05 <= 0:
        raise InfiltrationError("La sorptividad S debe ser mayor que 0.")
    if factor_gravedad_a_mm_h <= 0:
        raise InfiltrationError("El factor de gravedad A debe ser mayor que 0.")

    s_sorp, a_grav = sorptividad_mm_h05, factor_gravedad_a_mm_h

    def tiempo_equivalente(f_acum):
        if f_acum <= 0:
            return 0.0
        raiz_t = (-s_sorp + math.sqrt(s_sorp * s_sorp + 4.0 * a_grav * f_acum)) / (2.0 * a_grav)
        return max(raiz_t, 0.0) ** 2

    f_acum = float(infiltracion_acumulada_inicial_mm)
    infiltracion, escorrentia, capacidad = [], [], []
    paso_encharcamiento = None

    for indice, lluvia in enumerate(serie):
        intensidad = lluvia / dt_h
        t_eq = tiempo_equivalente(f_acum)
        # Capacidad media a lo largo del intervalo, que es lo que se puede
        # comparar con la intensidad media del mismo intervalo.
        f_potencial = s_sorp * math.sqrt(t_eq + dt_h) + a_grav * (t_eq + dt_h)
        cap_media = (f_potencial - f_acum) / dt_h
        capacidad.append(round(cap_media, 4))

        if lluvia <= 0:
            infiltracion.append(0.0)
            escorrentia.append(0.0)
            continue

        if intensidad <= cap_media:
            infiltrado = lluvia
        else:
            infiltrado = min(f_potencial - f_acum, lluvia)
            if paso_encharcamiento is None:
                paso_encharcamiento = indice

        infiltrado = max(infiltrado, 0.0)
        f_acum += infiltrado
        infiltracion.append(infiltrado)
        escorrentia.append(lluvia - infiltrado)

    return _resumen_infiltracion(
        serie, infiltracion, escorrentia, capacidad, dt_h, "Philip (1957)",
        {"S_sorptividad_mm_h05": sorptividad_mm_h05, "A_gravedad_mm_h": factor_gravedad_a_mm_h},
        paso_encharcamiento)


# ---------------------------------------------------------------------
# KOSTIAKOV (1932) y KOSTIAKOV-LEWIS
# ---------------------------------------------------------------------
def infiltracion_kostiakov(hietograma_mm: Sequence[float], dt_h: float,
                            coef_a: float, exponente_b: float,
                            fc_mm_h: float = 0.0,
                            infiltracion_acumulada_inicial_mm: float = 0.0) -> dict:
    """
    Kostiakov (1932) y su variante Kostiakov-Lewis.

        Kostiakov:        F(t) = a*t^b        f(t) = a*b*t^(b-1)
        Kostiakov-Lewis:  F(t) = a*t^b + fc*t  f(t) = a*b*t^(b-1) + fc

    a y b son coeficientes empíricos de ensayos de infiltrómetro (a > 0,
    0 < b < 1). fc = 0 da el Kostiakov estándar; fc > 0 da la variante de
    Lewis, que evita el defecto conocido del original: con b<1 la
    capacidad f(t) tiende a CERO cuando t crece, lo que es físicamente
    imposible -- ningún suelo deja de infiltrar por completo. Por eso, si
    la tormenta es larga, la variante de Lewis es la recomendable.

    La inversión de F(t) para obtener el tiempo equivalente es analítica
    cuando fc = 0 (t = (F/a)^(1/b)); con fc > 0 se resuelve por
    Newton-Raphson, igual que en Horton.
    """
    serie = _validar_hietograma(hietograma_mm, dt_h)
    if coef_a <= 0:
        raise InfiltrationError("El coeficiente a de Kostiakov debe ser mayor que 0.")
    if not (0.0 < exponente_b < 1.0):
        raise InfiltrationError(
            "El exponente b de Kostiakov debe estar entre 0 y 1 (fuera de ese rango la capacidad de "
            "infiltración no decaería, que es justamente lo que el método modela).")
    if fc_mm_h < 0:
        raise InfiltrationError("La tasa final fc no puede ser negativa.")

    def tiempo_equivalente(f_acum):
        if f_acum <= 0:
            return 0.0
        if fc_mm_h <= 0:
            return (f_acum / coef_a) ** (1.0 / exponente_b)
        t = (f_acum / (coef_a + fc_mm_h)) ** (1.0 / exponente_b)
        for _ in range(60):
            valor = coef_a * (t ** exponente_b) + fc_mm_h * t - f_acum
            derivada = coef_a * exponente_b * (t ** (exponente_b - 1.0)) + fc_mm_h if t > 0 else fc_mm_h
            if abs(derivada) < 1e-14:
                break
            paso = valor / derivada
            t -= paso
            if t < 0:
                t = 1e-12
            if abs(paso) < 1e-10:
                break
        return max(t, 0.0)

    f_acum = float(infiltracion_acumulada_inicial_mm)
    infiltracion, escorrentia, capacidad = [], [], []
    paso_encharcamiento = None

    for indice, lluvia in enumerate(serie):
        intensidad = lluvia / dt_h
        t_eq = tiempo_equivalente(f_acum)
        f_potencial = coef_a * ((t_eq + dt_h) ** exponente_b) + fc_mm_h * (t_eq + dt_h)
        cap_media = (f_potencial - f_acum) / dt_h
        capacidad.append(round(cap_media, 4))

        if lluvia <= 0:
            infiltracion.append(0.0)
            escorrentia.append(0.0)
            continue

        if intensidad <= cap_media:
            infiltrado = lluvia
        else:
            infiltrado = min(f_potencial - f_acum, lluvia)
            if paso_encharcamiento is None:
                paso_encharcamiento = indice

        infiltrado = max(infiltrado, 0.0)
        f_acum += infiltrado
        infiltracion.append(infiltrado)
        escorrentia.append(lluvia - infiltrado)

    nombre = "Kostiakov-Lewis" if fc_mm_h > 0 else "Kostiakov (1932)"
    return _resumen_infiltracion(
        serie, infiltracion, escorrentia, capacidad, dt_h, nombre,
        {"a": coef_a, "b": exponente_b, "fc_mm_h": fc_mm_h}, paso_encharcamiento)


# ---------------------------------------------------------------------
# HOLTAN (USDA-HL)
# ---------------------------------------------------------------------
def infiltracion_holtan(hietograma_mm: Sequence[float], dt_h: float,
                         coef_a: float, indice_crecimiento_gi: float,
                         almacenamiento_disponible_mm: float, fc_mm_h: float,
                         exponente_d: float = 1.4,
                         tasa_drenaje_profundo_mm_h: float = None) -> dict:
    """
    Holtan (USDA-HL): a diferencia de los métodos anteriores, la
    capacidad de infiltración NO depende del tiempo ni de la
    infiltración acumulada, sino del ALMACENAMIENTO DISPONIBLE que
    todavía queda en la zona radicular:

        f = a * GI * SA^d + fc

    a: índice de cobertura vegetal/superficie.
    GI: índice de crecimiento de la planta (0-1 según la etapa fenológica).
    SA: almacenamiento disponible en la zona de raíces (mm de poros aún
        no llenos). Es la VARIABLE DE ESTADO: disminuye conforme infiltra
        agua y se recupera por drenaje profundo.
    d: exponente empírico (típicamente 1.4).
    fc: infiltración final constante.

    Esta formulación tiene una consecuencia importante y deseable: cuando
    el suelo se satura (SA → 0) la capacidad cae a fc, no a cero, y el
    método representa de forma natural la RECUPERACIÓN de la capacidad
    entre eventos, que Horton y Philip no capturan (en ellos la capacidad
    solo puede decaer). La recuperación se modela drenando el perfil a la
    tasa `tasa_drenaje_profundo_mm_h` (por defecto igual a fc).

    *** ATENCIÓN A LAS UNIDADES (trampa detectada al validar) ***
    La ecuación original de Holtan está formulada en el sistema inglés:
    f en pulgadas/hora y SA en PULGADAS de almacenamiento disponible, con
    el coeficiente "a" en el rango 0.1-1.0 que da la bibliografía.
    Introducir SA directamente en milímetros hace explotar el término
    SA^1.4: con SA=80 mm y a=25 la capacidad salía 9243 mm/h, un valor
    físicamente imposible (mismo tipo de error de unidades que las
    constantes "por centímetro" de SCS/Snyder corregidas en la v0.2.44).
    Aquí el término potencial se evalúa internamente en PULGADAS y el
    resultado se reconvierte a mm/h, de modo que el usuario ingresa SA en
    mm (coherente con el resto del plugin) y "a" conserva el rango
    bibliográfico de 0.1-1.0. fc se maneja directamente en mm/h.
    """
    serie = _validar_hietograma(hietograma_mm, dt_h)
    if coef_a <= 0:
        raise InfiltrationError("El coeficiente a de Holtan debe ser mayor que 0.")
    if coef_a > 3.0:
        raise InfiltrationError(
            f"El coeficiente a de Holtan vale {coef_a}, muy por encima del rango bibliográfico "
            "(0.1-1.0). Recuerde que en esta implementación el término potencial se evalúa en "
            "pulgadas, como en la formulación original, así que 'a' conserva su rango clásico: no "
            "hay que inflarlo para compensar unidades."
        )
    if not (0.0 < indice_crecimiento_gi <= 1.0):
        raise InfiltrationError("El índice de crecimiento GI debe estar entre 0 y 1.")
    if almacenamiento_disponible_mm <= 0:
        raise InfiltrationError("El almacenamiento disponible en la zona radicular debe ser mayor que 0.")
    if fc_mm_h <= 0:
        raise InfiltrationError("La infiltración final fc debe ser mayor que 0.")
    if exponente_d <= 0:
        raise InfiltrationError("El exponente d debe ser mayor que 0.")

    drenaje = fc_mm_h if tasa_drenaje_profundo_mm_h is None else tasa_drenaje_profundo_mm_h
    sa_total = float(almacenamiento_disponible_mm)
    sa = sa_total
    infiltracion, escorrentia, capacidad = [], [], []
    paso_encharcamiento = None

    MM_POR_PULGADA = 25.4
    for indice, lluvia in enumerate(serie):
        intensidad = lluvia / dt_h
        # El término potencial se evalúa en PULGADAS (formulación original
        # de Holtan) y se reconvierte a mm/h; fc ya viene en mm/h.
        sa_pulgadas = max(sa, 0.0) / MM_POR_PULGADA
        cap = (coef_a * indice_crecimiento_gi * (sa_pulgadas ** exponente_d)) * MM_POR_PULGADA + fc_mm_h
        capacidad.append(round(cap, 4))

        infiltrado = min(lluvia, cap * dt_h) if lluvia > 0 else 0.0
        # La infiltración tampoco puede exceder el espacio disponible más
        # lo que drena en el intervalo: sin este tope el suelo aceptaría
        # más agua de la que físicamente cabe.
        infiltrado = min(infiltrado, max(sa, 0.0) + drenaje * dt_h)
        infiltrado = max(infiltrado, 0.0)
        if lluvia > 0 and infiltrado < lluvia - 1e-12 and paso_encharcamiento is None:
            paso_encharcamiento = indice

        # Actualización del almacenamiento: se llena con lo infiltrado y se
        # recupera por drenaje profundo, sin superar nunca su capacidad.
        sa = min(sa - infiltrado + drenaje * dt_h, sa_total)
        sa = max(sa, 0.0)

        infiltracion.append(infiltrado)
        escorrentia.append(max(lluvia - infiltrado, 0.0))

    return _resumen_infiltracion(
        serie, infiltracion, escorrentia, capacidad, dt_h, "Holtan (USDA-HL)",
        {"a": coef_a, "GI": indice_crecimiento_gi, "SA_inicial_mm": almacenamiento_disponible_mm,
         "d": exponente_d, "fc_mm_h": fc_mm_h, "drenaje_profundo_mm_h": drenaje},
        paso_encharcamiento)


# =====================================================================
# RICHARDS 1D (física completa)
# =====================================================================
# Resuelve la ecuación de Richards en forma MIXTA:
#
#       d(theta)/dt = d/dz [ K(h) * ( dh/dz + 1 ) ]
#
# con z positivo hacia ARRIBA, h la carga de presión (negativa = succión,
# en mm) y K la conductividad hidráulica no saturada (mm/h).
#
# POR QUÉ LA FORMA MIXTA Y NO LA FORMA EN h: escribir la ecuación como
# C(h)*dh/dt = ... (forma "en h") es más simple de programar, pero es
# NOTORIAMENTE NO CONSERVATIVA: acumula errores de balance de masa que
# pueden llegar al 10-20% en frentes húmedos abruptos, precisamente el
# caso de la infiltración. Celia, Bouloutas & Zarba (1990, Water
# Resources Research 26(7):1483-1496) demostraron que conservar el
# término de almacenamiento como d(theta)/dt y resolverlo con una
# iteración de Picard MODIFICADA restaura la conservación de masa a
# precisión de máquina. Es la formulación que se implementa aquí.
#
# DISCRETIZACIÓN: volúmenes finitos (no diferencias finitas nodales), que
# es conservativa por construcción -- el balance de cada celda es exacto
# y los flujos entre celdas se cancelan telescópicamente. El sistema
# lineal de cada iteración es tridiagonal y se resuelve con el algoritmo
# de Thomas.
#
# RELACIONES CONSTITUTIVAS: van Genuchten (1980) para la retención y
# Mualem para la conductividad:
#       Se = [1 + (alpha*|h|)^n]^(-m),   m = 1 - 1/n
#       theta = theta_r + (theta_s - theta_r)*Se
#       K = Ks * Se^L * [1 - (1 - Se^(1/m))^m]^2,   L = 0.5
#       C = d(theta)/dh = alpha*m*n*(theta_s-theta_r)*(alpha*|h|)^(n-1)
#                          * [1 + (alpha*|h|)^n]^(-m-1)
#
# CONDICIÓN DE BORDE SUPERIOR CONMUTADA: mientras el suelo pueda absorber
# toda la lluvia se impone un flujo (Neumann) igual a la intensidad; si
# eso exigiera una presión positiva en superficie, se conmuta a carga
# impuesta h=0 (Dirichlet) y la infiltración real pasa a ser la que el
# suelo admite, yendo el resto a escorrentía. Esta conmutación es lo que
# hace que el modelo produzca escorrentía por exceso de infiltración de
# forma física, sin necesidad de un criterio empírico de encharcamiento.
#
# LÍMITES: es un modelo de columna 1D homogénea. No representa
# estratificación (salvo que se extienda a K variable por capa), flujo
# lateral, macroporos ni histéresis de la curva de retención. Es el más
# riguroso de este módulo, pero también el más caro de calcular y el que
# más parámetros exige.
#
# LÍMITE DE CONVERGENCIA MEDIDO (importante, y se informa en vez de
# ocultarlo): con el hietograma de prueba del plugin (pico de 56 mm/h) y
# succión inicial de -1000 mm, la iteración de Picard converge en 6 de
# las 12 clases texturales de Carsel & Parrish -- arena, arena franca,
# franco arenoso, franco, limo y franco arcillo-limoso -- y en ellas
# conserva la masa de la columna con errores de 0 a 4.5e-4 mm. En los
# suelos MÁS FINOS (franco limoso, francos arcillosos, arcillo-limoso,
# arcilla) el problema se vuelve demasiado rígido: su Ks (0.7-13 mm/h)
# queda uno o dos órdenes de magnitud por debajo de la intensidad de la
# lluvia, el frente húmedo es casi discontinuo y Picard no converge
# aunque se refine el paso de tiempo. En esos casos la función lanza
# InfiltrationError con un mensaje que indica qué ajustar (succión
# inicial menos extrema, más celdas, o menor Δt), y lo razonable es usar
# Green-Ampt, que está formulado precisamente para un frente abrupto y
# no tiene ese problema numérico. Resolverlo del todo requeriría un
# esquema de Newton con línea de búsqueda o transformación de Kirchhoff,
# que excede el alcance actual de este módulo.

# Parámetros de van Genuchten por clase textural (Carsel & Parrish, 1988,
# "Developing joint probability distributions of soil water retention
# characteristics", Water Resources Research 24(5):755-769) -- la tabla
# estándar, usada por HYDRUS entre otros.
# OJO CON LAS UNIDADES: la bibliografía da alpha en 1/cm y Ks en cm/h.
# Aquí se guardan tal cual (para que sean reconocibles al contrastar con
# la fuente) y la conversión a 1/mm y mm/h se hace al construir el
# modelo, no a mano por el usuario -- que es donde se cometen los errores.
# Formato: clave -> (nombre, theta_r, theta_s, alpha_1_cm, n, Ks_cm_h)
PARAMETROS_VAN_GENUCHTEN = {
    "arena":              ("Arena",                   0.045, 0.43, 0.145, 2.68, 29.70),
    "arena_franca":       ("Arena franca",            0.057, 0.41, 0.124, 2.28, 14.59),
    "franco_arenoso":     ("Franco arenoso",          0.065, 0.41, 0.075, 1.89,  4.42),
    "franco":             ("Franco",                  0.078, 0.43, 0.036, 1.56,  1.04),
    "limo":               ("Limo",                    0.034, 0.46, 0.016, 1.37,  0.25),
    "franco_limoso":      ("Franco limoso",           0.067, 0.45, 0.020, 1.41,  0.45),
    "franco_arcillo_aren": ("Franco arcillo-arenoso",  0.100, 0.39, 0.059, 1.48,  1.31),
    "franco_arcilloso":   ("Franco arcilloso",        0.095, 0.41, 0.019, 1.31,  0.26),
    "franco_arcillo_lim": ("Franco arcillo-limoso",   0.089, 0.43, 0.010, 1.23,  0.07),
    "arcillo_arenoso":    ("Arcillo-arenoso",         0.100, 0.38, 0.027, 1.23,  0.12),
    "arcillo_limoso":     ("Arcillo-limoso",          0.070, 0.36, 0.005, 1.09,  0.02),
    "arcilla":            ("Arcilla",                 0.068, 0.38, 0.008, 1.09,  0.20),
}


def _vg_se(h_mm, alpha_1_mm, n):
    """Saturación efectiva de van Genuchten."""
    if h_mm >= 0:
        return 1.0
    m = 1.0 - 1.0 / n
    return (1.0 + (alpha_1_mm * abs(h_mm)) ** n) ** (-m)


def _vg_theta(h_mm, theta_r, theta_s, alpha_1_mm, n):
    return theta_r + (theta_s - theta_r) * _vg_se(h_mm, alpha_1_mm, n)


def _vg_k(h_mm, ks_mm_h, alpha_1_mm, n, l_mualem=0.5):
    if h_mm >= 0:
        return ks_mm_h
    m = 1.0 - 1.0 / n
    se = _vg_se(h_mm, alpha_1_mm, n)
    se = min(max(se, 1e-12), 1.0)
    interior = 1.0 - (1.0 - se ** (1.0 / m)) ** m
    return ks_mm_h * (se ** l_mualem) * (interior ** 2)


def _vg_capacidad(h_mm, theta_r, theta_s, alpha_1_mm, n):
    """Capacidad específica de humedad C = d(theta)/dh (1/mm)."""
    if h_mm >= 0:
        return 0.0
    m = 1.0 - 1.0 / n
    ah = alpha_1_mm * abs(h_mm)
    if ah <= 0:
        return 0.0
    return (theta_s - theta_r) * alpha_1_mm * m * n * (ah ** (n - 1.0)) * \
           ((1.0 + ah ** n) ** (-m - 1.0))


def _thomas(a, b, c, d):
    """
    Algoritmo de Thomas para sistemas tridiagonales (eliminación
    gaussiana especializada, O(N) en vez de O(N^3)).
    a: subdiagonal (a[0] no se usa), b: diagonal, c: superdiagonal
    (c[-1] no se usa), d: término independiente.
    """
    n = len(b)
    cp = [0.0] * n
    dp = [0.0] * n
    if abs(b[0]) < 1e-300:
        raise InfiltrationError("Sistema tridiagonal singular en Richards (pivote nulo).")
    cp[0] = c[0] / b[0]
    dp[0] = d[0] / b[0]
    for i in range(1, n):
        denom = b[i] - a[i] * cp[i - 1]
        if abs(denom) < 1e-300:
            raise InfiltrationError("Sistema tridiagonal singular en Richards (pivote nulo).")
        cp[i] = c[i] / denom if i < n - 1 else 0.0
        dp[i] = (d[i] - a[i] * dp[i - 1]) / denom
    x = [0.0] * n
    x[-1] = dp[-1]
    for i in range(n - 2, -1, -1):
        x[i] = dp[i] - cp[i] * x[i + 1]
    return x


def infiltracion_richards_1d(hietograma_mm: Sequence[float], dt_h: float,
                              theta_r: float, theta_s: float, alpha_1_cm: float,
                              n_vg: float, ks_cm_h: float,
                              profundidad_columna_mm: float = 1000.0,
                              n_celdas: int = 40,
                              succion_inicial_mm: float = -1000.0,
                              max_subpasos: int = 20000,
                              tol_picard_mm: float = 1e-3,
                              max_iter_picard: int = 60) -> dict:
    """
    Resuelve la infiltración por la ecuación de Richards 1D.

    Parámetros de van Genuchten en las unidades de la BIBLIOGRAFÍA
    (alpha en 1/cm, Ks en cm/h); la conversión interna a 1/mm y mm/h la
    hace la función, para no trasladar al usuario un error de unidades
    que es de los más frecuentes con esta ecuación.

    profundidad_columna_mm: espesor del perfil simulado. Debe ser lo
        bastante grande para que el frente húmedo no alcance el fondo
        durante el evento; si lo alcanza, el drenaje por el fondo se
        contabiliza y se reporta.
    succion_inicial_mm: carga de presión inicial uniforme (negativa).
        -1000 mm ~ suelo bastante seco; -100 mm ~ suelo húmedo.
    """
    serie = _validar_hietograma(hietograma_mm, dt_h)
    if not (0.0 <= theta_r < theta_s <= 1.0):
        raise InfiltrationError("Debe cumplirse 0 <= theta_r < theta_s <= 1.")
    if n_vg <= 1.0:
        raise InfiltrationError("El parámetro n de van Genuchten debe ser mayor que 1.")
    if alpha_1_cm <= 0 or ks_cm_h <= 0:
        raise InfiltrationError("alpha y Ks deben ser mayores que 0.")
    if succion_inicial_mm >= 0:
        raise InfiltrationError("La succión inicial debe ser negativa (el suelo no parte saturado).")
    if n_celdas < 10:
        raise InfiltrationError("Se necesitan al menos 10 celdas para una discretización razonable.")

    # Conversión de unidades bibliográficas a las del plugin.
    alpha = alpha_1_cm / 10.0      # 1/cm -> 1/mm
    ks = ks_cm_h * 10.0            # cm/h -> mm/h

    dz = profundidad_columna_mm / n_celdas
    h = [float(succion_inicial_mm)] * n_celdas          # índice 0 = fondo, n-1 = superficie
    theta_inicial = [_vg_theta(hi, theta_r, theta_s, alpha, n_vg) for hi in h]
    almacenamiento_inicial = sum(t * dz for t in theta_inicial)

    infiltracion, escorrentia, capacidad = [], [], []
    paso_encharcamiento = None
    drenaje_fondo_total = 0.0

    def theta_de(hv):
        return _vg_theta(hv, theta_r, theta_s, alpha, n_vg)

    def k_de(hv):
        return _vg_k(hv, ks, alpha, n_vg)

    for indice, lluvia in enumerate(serie):
        intensidad = lluvia / dt_h
        infiltrado_intervalo = 0.0
        drenaje_intervalo = 0.0
        # PASO DE TIEMPO ADAPTATIVO. La no linealidad de Richards obliga a
        # sub-pasos pequeños cuando el frente húmedo es abrupto, pero
        # fijarlos de antemano es ineficiente (y si se refina a mitad del
        # intervalo, los sub-pasos ya dados quedarían con otro Δt: ese era
        # el error de la primera versión, que hacía fallar la convergencia).
        # Aquí se lleva el TIEMPO RESTANTE del intervalo: si Picard no
        # converge se reduce Δt y se reintenta ese mismo sub-paso; si
        # converge con holgura se deja crecer de nuevo.
        dt_sub = dt_h / 10.0
        dt_sub_minimo = dt_h / max_subpasos
        tiempo_restante = dt_h
        capacidad_registrada = None

        while tiempo_restante > 1e-12:
            dt_sub = min(dt_sub, tiempo_restante)
            h_viejo = list(h)
            theta_viejo = [theta_de(hv) for hv in h_viejo]
            almacen_antes = sum(theta_viejo[i] * dz for i in range(n_celdas))

            def resolver(ponded_flag):
                """Una tanda completa de Picard con la condición de borde
                superior indicada. Devuelve (h_resultante, convergio)."""
                h_it = list(h_viejo)
                for iteracion in range(max_iter_picard):
                    k_nodo = [k_de(hv) for hv in h_it]
                    # Conductividades en las caras: media aritmética. Se
                    # probó también la media geométrica, que la bibliografía
                    # recomienda para frentes abruptos: convergió en el mismo
                    # número de clases texturales (6 de 12), cambiando cuáles
                    # -- ganaba arcillo-arenoso pero perdía franco, que es un
                    # suelo mucho más frecuente. Se mantiene la aritmética
                    # por eso, no por descarte de la alternativa.
                    k_cara = [0.5 * (k_nodo[i] + k_nodo[i + 1]) for i in range(n_celdas - 1)]

                    a = [0.0] * n_celdas
                    b = [0.0] * n_celdas
                    c = [0.0] * n_celdas
                    d = [0.0] * n_celdas

                    for i in range(n_celdas):
                        c_i = _vg_capacidad(h_it[i], theta_r, theta_s, alpha, n_vg)
                        theta_i = theta_de(h_it[i])
                        # Flujo en la cara superior de la celda i (positivo hacia arriba)
                        if i < n_celdas - 1:
                            q_sup = -k_cara[i] * ((h_it[i + 1] - h_it[i]) / dz + 1.0)
                        else:
                            q_sup = -intensidad
                        # Flujo en la cara inferior
                        if i > 0:
                            q_inf = -k_cara[i - 1] * ((h_it[i] - h_it[i - 1]) / dz + 1.0)
                        else:
                            q_inf = -k_nodo[0]  # drenaje libre: gradiente unitario

                        residuo = dz * (theta_i - theta_viejo[i]) / dt_sub + (q_sup - q_inf)

                        b[i] = dz * c_i / dt_sub
                        if i > 0:
                            a[i] = -k_cara[i - 1] / dz
                            b[i] += k_cara[i - 1] / dz
                        if i < n_celdas - 1:
                            c[i] = -k_cara[i] / dz
                            b[i] += k_cara[i] / dz
                        d[i] = -residuo

                    if ponded_flag:
                        # Carga impuesta h=0 en la celda superficial.
                        a[-1] = 0.0
                        b[-1] = 1.0
                        c[-1] = 0.0
                        d[-1] = 0.0 - h_it[-1]

                    delta = _thomas(a, b, c, d)
                    # AMORTIGUAMIENTO ADAPTATIVO. En suelos finos (n cercano
                    # a 1, Ks muy baja frente a la intensidad de lluvia) el
                    # sistema es muy rígido y Picard oscila con pasos
                    # grandes. Se limita el salto por iteración y el tope se
                    # va reduciendo con las iteraciones: las primeras avanzan
                    # rápido y las últimas afinan sin sobrepasar la solución.
                    tope = 1000.0 / (1.0 + 0.15 * iteracion)
                    for i in range(n_celdas):
                        h_it[i] += max(min(delta[i], tope), -tope)
                    if max(abs(x) for x in delta) < tol_picard_mm:
                        return h_it, True
                return h_it, False

            def flujo_superficial(h_res):
                """Infiltración real del sub-paso (mm), deducida del balance
                de la columna: cambio de almacenamiento más drenaje por el
                fondo. Es la ÚNICA forma consistente de contabilizarla --
                leerla de la condición de borde daría un valor que no cuadra
                con lo que realmente entró en el perfil."""
                almacen_despues = sum(theta_de(hv) * dz for hv in h_res)
                drenaje = k_de(h_res[0]) * dt_sub
                return (almacen_despues - almacen_antes) + drenaje, drenaje

            # CONMUTACIÓN DE LA CONDICIÓN DE BORDE SUPERIOR.
            # 1) Se intenta con FLUJO impuesto (toda la lluvia infiltra).
            # 2) Si eso exigiría presión positiva en superficie, se conmuta
            #    a CARGA impuesta h=0 y la infiltración pasa a ser la que el
            #    suelo admite.
            # 3) Verificación de consistencia: si con carga impuesta el suelo
            #    admitiría MÁS de lo que llueve, entonces el encharcamiento
            #    no era real y se revierte al caso de flujo impuesto. Sin
            #    esta reversión el modelo "inventa" agua que no cayó, y el
            #    balance de la columna deja de cerrar (se midió un 6.2% de
            #    error antes de agregarla).
            h_iter, convergio = resolver(False)
            ponded = False
            infiltrado_sub = intensidad * dt_sub
            drenaje_sub = 0.0

            if convergio and h_iter[-1] > 0.0:
                h_pond, conv_pond = resolver(True)
                if conv_pond:
                    flujo_pond, drenaje_pond = flujo_superficial(h_pond)
                    if flujo_pond < intensidad * dt_sub:
                        ponded = True
                        h_iter = h_pond
                        infiltrado_sub = max(flujo_pond, 0.0)
                        drenaje_sub = drenaje_pond
                    else:
                        # El suelo admitía toda la lluvia: no hay encharcamiento.
                        _, drenaje_sub = flujo_superficial(h_iter)
                else:
                    convergio = False
            elif convergio:
                _, drenaje_sub = flujo_superficial(h_iter)

            if not convergio:
                # Sub-paso demasiado grande: se reduce Δt y se reintenta
                # ESTE MISMO sub-paso (el tiempo restante no se descuenta).
                dt_sub *= 0.5
                if dt_sub < dt_sub_minimo:
                    raise InfiltrationError(
                        "Richards 1D no convergió ni siquiera refinando el paso de tiempo hasta "
                        f"{dt_sub_minimo:.2e} h. Pruebe con una succión inicial menos extrema "
                        "(p.ej. -300 mm en vez de -1000), más celdas, o un Δt del hietograma menor."
                    )
                continue

            # infiltrado_sub y drenaje_sub ya quedaron fijados por la
            # conmutación de la condición de borde de arriba: NO se
            # recalculan ni se recortan aquí. Recortarlos a la lluvia
            # disponible era precisamente lo que rompía el balance de la
            # columna, porque descontaba en superficie agua que sí había
            # entrado en el perfil.
            if ponded and paso_encharcamiento is None:
                paso_encharcamiento = indice
            if capacidad_registrada is None:
                capacidad_registrada = infiltrado_sub / dt_sub if dt_sub > 0 else 0.0

            infiltrado_intervalo += infiltrado_sub
            drenaje_intervalo += drenaje_sub
            h = h_iter
            tiempo_restante -= dt_sub
            # Si convergió sin dificultad, se deja crecer el paso otra vez
            # (acotado al décimo del intervalo) para no encarecer el cálculo.
            dt_sub = min(dt_sub * 1.5, dt_h / 10.0)

        infiltrado_intervalo = min(infiltrado_intervalo, lluvia)
        drenaje_fondo_total += drenaje_intervalo
        infiltracion.append(infiltrado_intervalo)
        escorrentia.append(max(lluvia - infiltrado_intervalo, 0.0))
        capacidad.append(round(capacidad_registrada if capacidad_registrada is not None else 0.0, 4))

    resultado = _resumen_infiltracion(
        serie, infiltracion, escorrentia, capacidad, dt_h, "Richards 1D (van Genuchten)",
        {"theta_r": theta_r, "theta_s": theta_s, "alpha_1_cm": alpha_1_cm, "n": n_vg,
         "Ks_cm_h": ks_cm_h, "profundidad_mm": profundidad_columna_mm, "n_celdas": n_celdas,
         "succion_inicial_mm": succion_inicial_mm},
        paso_encharcamiento)

    # Diagnóstico específico de Richards: balance de agua en la COLUMNA
    # (no solo en la superficie). Es la verificación que delata una
    # formulación no conservativa.
    almacenamiento_final = sum(theta_de(hv) * dz for hv in h)
    cambio_almacenamiento = almacenamiento_final - almacenamiento_inicial
    error_columna = abs(resultado["infiltracion_total_mm"] - (cambio_almacenamiento + drenaje_fondo_total))
    resultado.update({
        "almacenamiento_inicial_mm": round(almacenamiento_inicial, 4),
        "almacenamiento_final_mm": round(almacenamiento_final, 4),
        "cambio_almacenamiento_mm": round(cambio_almacenamiento, 4),
        "drenaje_por_el_fondo_mm": round(drenaje_fondo_total, 4),
        "error_balance_columna_mm": round(error_columna, 6),
        "balance_columna_correcto": error_columna < max(0.01, resultado["infiltracion_total_mm"] * 0.005),
        "humedad_final_superficie": round(theta_de(h[-1]), 4),
        "humedad_final_fondo": round(theta_de(h[0]), 4),
        "succion_final_superficie_mm": round(h[-1], 2),
    })
    return resultado


# ---------------------------------------------------------------------
# RESUMEN Y COMPARACIÓN
# ---------------------------------------------------------------------
def _resumen_infiltracion(lluvia_total: List[float], infiltracion: List[float],
                           escorrentia: List[float], capacidad: List[float], dt_h: float,
                           metodo: str, parametros: dict,
                           paso_encharcamiento: Optional[int]) -> dict:
    """
    Arma el resultado y verifica el BALANCE DE MASA: la suma de la
    infiltración y de la escorrentía debe reproducir exactamente la
    lluvia total. Es la comprobación que delata cualquier error en la
    contabilidad de los intervalos parcialmente encharcados.
    """
    total = sum(lluvia_total)
    infiltrado = sum(infiltracion)
    escurrido = sum(escorrentia)
    error_balance = abs((infiltrado + escurrido) - total)

    return {
        "metodo": metodo,
        "parametros": dict(parametros),
        "dt_h": dt_h,
        "lluvia_total_incr_mm": [round(v, 4) for v in lluvia_total],
        "infiltracion_incr_mm": [round(v, 4) for v in infiltracion],
        "lluvia_efectiva_incr_mm": [round(v, 4) for v in escorrentia],
        "capacidad_infiltracion_mm_h": [round(v, 4) if math.isfinite(v) else None for v in capacidad],
        "lluvia_total_mm": round(total, 3),
        "infiltracion_total_mm": round(infiltrado, 3),
        "lluvia_efectiva_total_mm": round(escurrido, 3),
        "coeficiente_escorrentia": round(escurrido / total, 4) if total > 0 else 0.0,
        "error_balance_masa_mm": round(error_balance, 9),
        "balance_correcto": error_balance < 1e-6,
        "paso_encharcamiento": paso_encharcamiento,
        "tiempo_encharcamiento_h": (round(paso_encharcamiento * dt_h, 3)
                                     if paso_encharcamiento is not None else None),
        "hubo_encharcamiento": paso_encharcamiento is not None,
    }


def perdidas_scs_cn(hietograma_mm: Sequence[float], dt_h: float, s_mm: float) -> dict:
    """
    Número de curva SCS envuelto en el MISMO formato de resultado que los
    otros seis modelos, para que pueda seleccionarse, graficarse y
    resumirse igual que ellos.

    Reutiliza lluvia_efectiva_incremental() de core/unit_hydrographs.py --
    la implementación que el plugin ya usaba y tiene verificada -- en vez
    de reimplementar la ecuación aquí: dos copias de la misma fórmula
    acabarían divergiendo y el usuario no sabría cuál se aplicó.

    A diferencia de los demás, el SCS-CN NO tiene una curva de capacidad
    de infiltración instantánea: es un método agregado de evento cuya
    abstracción depende solo de la lámina acumulada. Por eso su lista de
    capacidad va a None y el gráfico omite esa curva, en vez de dibujar
    una línea inventada que sugeriría una comparación que no existe.
    """
    serie = _validar_hietograma(hietograma_mm, dt_h)
    if s_mm is None or s_mm <= 0:
        raise InfiltrationError(
            "No hay una retención potencial máxima S válida. Calcule primero el número de curva en "
            "la sección superior de esta pestaña."
        )
    from .unit_hydrographs import lluvia_efectiva_incremental
    efectiva = list(lluvia_efectiva_incremental(serie, s_mm))
    infiltrado = [p - e for p, e in zip(serie, efectiva)]

    # El "encharcamiento" del SCS-CN es el instante en que se supera la
    # abstracción inicial Ia = 0.2*S y empieza a generarse escorrentía:
    # es el equivalente conceptual y permite compararlo con los demás.
    paso_inicio = next((i for i, e in enumerate(efectiva) if e > 0), None)

    resultado = _resumen_infiltracion(
        serie, infiltrado, efectiva, [float("nan")] * len(serie), dt_h,
        "SCS — Número de Curva", {"S_mm": round(s_mm, 3), "Ia_mm": round(0.2 * s_mm, 3)},
        paso_inicio)
    resultado["capacidad_infiltracion_mm_h"] = [None] * len(serie)
    resultado["nota_metodo"] = (
        "Método agregado de evento: la abstracción depende solo de la lámina acumulada, no de la "
        "intensidad instantánea, por lo que no tiene curva de capacidad de infiltración. Dos tormentas "
        "de igual lámina total dan el mismo resultado aunque una sea corta e intensa."
    )
    return resultado


def comparar_modelos_perdidas(hietograma_mm: Sequence[float], dt_h: float,
                               s_mm_scs: Optional[float] = None,
                               green_ampt: Optional[dict] = None,
                               horton: Optional[dict] = None) -> dict:
    """
    Aplica al MISMO hietograma los modelos de pérdidas disponibles, para
    comparar la lluvia efectiva (y por tanto el caudal pico) que resulta
    de cada uno.

    s_mm_scs: retención potencial máxima S del número de curva (Pestaña 3).
    green_ampt: dict con 'conductividad_k_mm_h', 'succion_psi_mm', 'deficit_humedad'.
    horton: dict con 'f0_mm_h', 'fc_mm_h' y opcionalmente 'k_decaimiento'.
    """
    resultados = {}

    if s_mm_scs is not None:
        # Se reutiliza la implementación ya existente y verificada del
        # número de curva, para que la comparación sea contra el mismo
        # cálculo que usa el resto del plugin (no una reimplementación).
        from .unit_hydrographs import lluvia_efectiva_incremental
        efectiva = lluvia_efectiva_incremental(list(hietograma_mm), s_mm_scs)
        infiltrado = [p - e for p, e in zip(hietograma_mm, efectiva)]
        resultados["scs_cn"] = _resumen_infiltracion(
            [float(p) for p in hietograma_mm], infiltrado, list(efectiva),
            [float("nan")] * len(efectiva), dt_h, "SCS — Número de Curva",
            {"S_mm": s_mm_scs}, None)

    if green_ampt:
        resultados["green_ampt"] = infiltracion_green_ampt(hietograma_mm, dt_h, **green_ampt)

    if horton:
        resultados["horton"] = infiltracion_horton(hietograma_mm, dt_h, **horton)

    if len(resultados) > 1:
        efectivas = {k: v["lluvia_efectiva_total_mm"] for k, v in resultados.items()}
        maximo, minimo = max(efectivas.values()), min(efectivas.values())
        resultados["comparacion"] = {
            "lluvia_efectiva_por_modelo_mm": efectivas,
            "maximo_mm": maximo,
            "minimo_mm": minimo,
            "dispersion_mm": round(maximo - minimo, 3),
            "dispersion_relativa_pct": round((maximo - minimo) / maximo * 100.0, 2) if maximo > 0 else 0.0,
            "nota": (
                "La lluvia efectiva se traslada de forma prácticamente proporcional al caudal pico: una "
                "diferencia del X% entre modelos de pérdidas implica aproximadamente un X% de diferencia "
                "en el Qp de diseño. Elija el modelo según los datos de suelo de que disponga y "
                "manténgalo de forma consistente en todo el estudio."
            ),
        }
    return resultados
