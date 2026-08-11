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
