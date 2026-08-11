# -*- coding: utf-8 -*-
"""
core/baseflow.py

Separación de flujo base: descompone un hidrograma OBSERVADO en su
componente de escorrentía directa (la respuesta rápida al evento de
lluvia) y su flujo base (el aporte sostenido del agua subterránea y del
almacenamiento de la cuenca).

PARA QUÉ SIRVE EN ESTE PLUGIN:
  - Calibrar el número de curva SCS (Pestaña 3) y los hidrogramas
    unitarios (Pestaña 7) contra crecidas realmente observadas: esos
    métodos producen ESCORRENTÍA DIRECTA, no caudal total, así que
    compararlos con un caudal aforado sin separar el flujo base
    sobreestima sistemáticamente el ajuste.
  - Estimar el Índice de Flujo Base (BFI = volumen de flujo base /
    volumen total), un descriptor muy usado de la capacidad de
    regulación natural de una cuenca y de la disponibilidad hídrica en
    estiaje.

MÉTODOS IMPLEMENTADOS:

  1. LYNE-HOLLICK (1979) — filtro digital recursivo de un parámetro, el
     más difundido:
         qd_i = a*qd_{i-1} + ((1+a)/2)*(Q_i - Q_{i-1})
         qb_i = Q_i - qd_i     (acotado a 0 <= qb_i <= Q_i)
     con "a" el parámetro de filtro (típicamente 0.90-0.98; 0.925 es el
     valor más citado). Se aplica en varias pasadas alternando sentido
     (adelante-atrás-adelante), lo habitual para evitar el sesgo de
     dirección de una pasada única.

  2. ECKHARDT (2005) — filtro de dos parámetros, que corrige una
     limitación real del anterior: Lyne-Hollick no impone ningún límite
     superior al flujo base, de modo que el BFI resultante depende
     fuertemente del número de pasadas y no tiene interpretación física
     directa. Eckhardt añade el BFImax (índice máximo de flujo base,
     propio del tipo de cauce y acuífero):
         qb_i = ((1-BFImax)*a*qb_{i-1} + (1-a)*BFImax*Q_i) / (1 - a*BFImax)
     Valores de BFImax recomendados por Eckhardt: 0.80 para cauces
     perennes con acuífero poroso, 0.50 para cauces efímeros con
     acuífero poroso, 0.25 para cauces perennes sobre roca dura.

  3. MÍNIMOS LOCALES (método gráfico clásico, USGS/HYSEP) — divide la
     serie en intervalos, toma el mínimo de cada uno y los conecta
     linealmente. No requiere parámetros de filtrado, pero sí la
     longitud del intervalo, que se estima de la superficie de la cuenca
     con la regla clásica N = A^0.2 (A en millas cuadradas, N en días).

TRANSPARENCIA: la separación del flujo base NO tiene una solución única
ni "verdadera" -- no es una magnitud medible, sino una construcción
conceptual. Métodos distintos (y parámetros distintos dentro de un mismo
método) dan separaciones distintas para el mismo hidrograma, y todas son
igualmente "válidas" formalmente. Por eso este módulo implementa tres
métodos y el plugin los muestra juntos: la coincidencia o divergencia
entre ellos es en sí misma información sobre cuán robusta es la
separación en esa cuenca. Use el mismo método y los mismos parámetros de
forma consistente a lo largo de un estudio.
"""
import math
from typing import Dict, List, Optional, Sequence


class BaseflowError(Exception):
    pass


BFIMAX_RECOMENDADOS = {
    "perenne_poroso": (0.80, "Cauce perenne con acuífero poroso"),
    "efimero_poroso": (0.50, "Cauce efímero con acuífero poroso"),
    "perenne_roca_dura": (0.25, "Cauce perenne sobre roca dura"),
}


def _validar_serie(caudales: Sequence[float]) -> List[float]:
    if caudales is None or len(caudales) < 3:
        raise BaseflowError("Se necesitan al menos 3 valores de caudal para separar el flujo base.")
    serie = [float(q) for q in caudales]
    if any(q < 0 for q in serie):
        raise BaseflowError("La serie de caudales no puede contener valores negativos.")
    return serie


def separar_lyne_hollick(caudales: Sequence[float], parametro_filtro: float = 0.925,
                          n_pasadas: int = 3) -> dict:
    """
    Filtro digital recursivo de Lyne-Hollick (1979).

    n_pasadas: número de pasadas alternando sentido (adelante, atrás,
    adelante...). Con 1 sola pasada el resultado queda sesgado por la
    dirección del filtrado; 3 es la práctica más habitual. Cada pasada
    adicional reduce el flujo base estimado, y ese es precisamente el
    punto débil del método que corrige Eckhardt.
    """
    serie = _validar_serie(caudales)
    if not (0.0 < parametro_filtro < 1.0):
        raise BaseflowError("El parámetro de filtro debe estar entre 0 y 1 (típico: 0.90-0.98).")
    if n_pasadas < 1:
        raise BaseflowError("Debe haber al menos 1 pasada de filtrado.")

    a = parametro_filtro
    flujo_base = list(serie)

    for pasada in range(n_pasadas):
        entrada = flujo_base if pasada > 0 else serie
        # Las pasadas impares (0, 2, 4...) van hacia adelante; las pares
        # intermedias, hacia atrás.
        hacia_adelante = (pasada % 2 == 0)
        secuencia = entrada if hacia_adelante else list(reversed(entrada))

        directo = [0.0] * len(secuencia)
        base_pasada = [0.0] * len(secuencia)
        base_pasada[0] = secuencia[0]
        for i in range(1, len(secuencia)):
            directo[i] = a * directo[i - 1] + ((1.0 + a) / 2.0) * (secuencia[i] - secuencia[i - 1])
            if directo[i] < 0:
                directo[i] = 0.0
            base_pasada[i] = secuencia[i] - directo[i]
            # El flujo base nunca puede superar al caudal total ni ser negativo.
            base_pasada[i] = min(max(base_pasada[i], 0.0), secuencia[i])

        flujo_base = base_pasada if hacia_adelante else list(reversed(base_pasada))

    flujo_base = [min(max(b, 0.0), q) for b, q in zip(flujo_base, serie)]
    escorrentia = [q - b for q, b in zip(serie, flujo_base)]
    return _resumen_separacion(serie, flujo_base, escorrentia, "Lyne-Hollick (1979)",
                                {"parametro_filtro_a": parametro_filtro, "n_pasadas": n_pasadas})


def separar_eckhardt(caudales: Sequence[float], parametro_recesion: float = 0.98,
                      bfi_max: float = 0.80) -> dict:
    """
    Filtro digital de dos parámetros de Eckhardt (2005).

    parametro_recesion (a): constante de recesión del flujo base entre
        pasos de tiempo; típicamente 0.95-0.99 en datos diarios.
    bfi_max: índice máximo de flujo base alcanzable; ver
        BFIMAX_RECOMENDADOS. Es el parámetro que da al método su
        interpretación física y lo hace preferible a Lyne-Hollick, cuyo
        resultado depende del número de pasadas sin tener un tope
        conceptual.
    """
    serie = _validar_serie(caudales)
    if not (0.0 < parametro_recesion < 1.0):
        raise BaseflowError("El parámetro de recesión debe estar entre 0 y 1 (típico: 0.95-0.99).")
    if not (0.0 < bfi_max < 1.0):
        raise BaseflowError("BFImax debe estar entre 0 y 1 (recomendados: 0.80, 0.50 o 0.25).")

    a = parametro_recesion
    denominador = 1.0 - a * bfi_max
    if abs(denominador) < 1e-12:
        raise BaseflowError("Combinación de parámetro de recesión y BFImax degenerada; ajuste los valores.")

    flujo_base = [0.0] * len(serie)
    # El primer valor se inicializa con el propio caudal ponderado por
    # BFImax: arrancar en Q completo sesgaría el inicio de la serie.
    flujo_base[0] = min(serie[0] * bfi_max, serie[0])
    for i in range(1, len(serie)):
        b = ((1.0 - bfi_max) * a * flujo_base[i - 1] + (1.0 - a) * bfi_max * serie[i]) / denominador
        flujo_base[i] = min(max(b, 0.0), serie[i])

    escorrentia = [q - b for q, b in zip(serie, flujo_base)]
    return _resumen_separacion(serie, flujo_base, escorrentia, "Eckhardt (2005)",
                                {"parametro_recesion_a": parametro_recesion, "BFImax": bfi_max})


def intervalo_minimos_locales(area_km2: float) -> int:
    """
    Longitud del intervalo (en pasos de tiempo/días) para el método de
    mínimos locales, por la regla clásica N = A^0.2 con A en MILLAS
    CUADRADAS y N en días (USGS/HYSEP). Se convierte el área de km² a
    mi² internamente. El resultado se redondea al impar más próximo,
    como indica el procedimiento original.
    """
    if area_km2 <= 0:
        raise BaseflowError("El área de la cuenca debe ser mayor que 0.")
    area_mi2 = area_km2 * 0.386102
    n = area_mi2 ** 0.2
    n_entero = max(3, int(round(n)))
    if n_entero % 2 == 0:
        n_entero += 1
    return n_entero


def separar_minimos_locales(caudales: Sequence[float], intervalo: int = 5) -> dict:
    """
    Método gráfico de mínimos locales: se recorre la serie en ventanas de
    longitud `intervalo`, se marca el mínimo de cada ventana como punto
    de flujo base, y se interpolan linealmente los tramos entre puntos.
    """
    serie = _validar_serie(caudales)
    if intervalo < 3:
        raise BaseflowError("El intervalo debe ser de al menos 3 pasos de tiempo.")
    n = len(serie)
    if intervalo > n:
        raise BaseflowError(
            f"El intervalo ({intervalo}) no puede superar la longitud de la serie ({n}).")

    # Puntos de anclaje: mínimo de cada ventana centrada.
    medio = intervalo // 2
    indices_ancla = []
    for centro in range(medio, n - medio):
        ventana = serie[centro - medio:centro + medio + 1]
        if serie[centro] == min(ventana):
            indices_ancla.append(centro)
    # Se fuerzan los extremos como anclas para poder interpolar toda la serie.
    if not indices_ancla or indices_ancla[0] != 0:
        indices_ancla.insert(0, 0)
    if indices_ancla[-1] != n - 1:
        indices_ancla.append(n - 1)

    flujo_base = [0.0] * n
    for j in range(len(indices_ancla) - 1):
        i0, i1 = indices_ancla[j], indices_ancla[j + 1]
        q0, q1 = serie[i0], serie[i1]
        for i in range(i0, i1 + 1):
            frac = (i - i0) / (i1 - i0) if i1 > i0 else 0.0
            flujo_base[i] = q0 + (q1 - q0) * frac
    flujo_base = [min(max(b, 0.0), q) for b, q in zip(flujo_base, serie)]
    escorrentia = [q - b for q, b in zip(serie, flujo_base)]
    return _resumen_separacion(serie, flujo_base, escorrentia, "Mínimos locales (USGS/HYSEP)",
                                {"intervalo_pasos": intervalo, "n_anclas": len(indices_ancla)})


def comparar_metodos_separacion(caudales: Sequence[float], parametro_filtro: float = 0.925,
                                 n_pasadas: int = 3, parametro_recesion: float = 0.98,
                                 bfi_max: float = 0.80, intervalo_minimos: int = 5) -> dict:
    """Aplica los 3 métodos a la misma serie. La dispersión entre sus
    BFI es, en sí misma, una medida de cuán bien definida está la
    separación en esa cuenca."""
    resultados = {
        "lyne_hollick": separar_lyne_hollick(caudales, parametro_filtro, n_pasadas),
        "eckhardt": separar_eckhardt(caudales, parametro_recesion, bfi_max),
        "minimos_locales": separar_minimos_locales(caudales, intervalo_minimos),
    }
    bfis = [r["BFI"] for r in resultados.values()]
    resultados["comparacion"] = {
        "BFI_minimo": round(min(bfis), 4),
        "BFI_maximo": round(max(bfis), 4),
        "BFI_promedio": round(sum(bfis) / len(bfis), 4),
        "dispersion_BFI": round(max(bfis) - min(bfis), 4),
        "interpretacion_dispersion": (
            "Los tres métodos coinciden bien: la separación está bien definida en esta serie."
            if (max(bfis) - min(bfis)) < 0.10 else
            "Los métodos difieren de forma apreciable: la separación es sensible al método elegido en "
            "esta serie. Reporte cuál usó y sus parámetros, y no compare resultados obtenidos con "
            "métodos distintos."
        ),
    }
    return resultados


def _resumen_separacion(caudal_total: List[float], flujo_base: List[float],
                         escorrentia: List[float], metodo: str, parametros: dict) -> dict:
    """
    Arma el resultado común: series separadas, volúmenes por integración
    trapezoidal e Índice de Flujo Base (BFI).

    El BFI se calcula como cociente de VOLÚMENES (no de caudales medios
    puntuales), que es su definición correcta.
    """
    volumen_total = sum(caudal_total)
    volumen_base = sum(flujo_base)
    bfi = (volumen_base / volumen_total) if volumen_total > 0 else 0.0

    qp_total = max(caudal_total)
    idx_pico = caudal_total.index(qp_total)

    # Las tres series se redondean de forma CONSISTENTE: la escorrentía
    # directa se obtiene restando las dos ya redondeadas, no redondeando
    # su valor crudo. Redondear las tres por separado hace que
    # base + directa deje de sumar exactamente el total (por hasta 1.5e-4),
    # lo que rompería cualquier comprobación del usuario al exportar
    # estas series a Excel o al graficarlas apiladas.
    total_red = [round(q, 4) for q in caudal_total]
    base_red = [round(b, 4) for b in flujo_base]
    directa_red = [round(q - b, 4) for q, b in zip(total_red, base_red)]

    return {
        "metodo": metodo,
        "parametros": dict(parametros),
        "caudal_total_m3_s": total_red,
        "flujo_base_m3_s": base_red,
        "escorrentia_directa_m3_s": directa_red,
        "BFI": round(bfi, 4),
        "BFI_pct": round(bfi * 100.0, 2),
        "Qp_total_m3_s": round(qp_total, 3),
        "flujo_base_en_el_pico_m3_s": round(flujo_base[idx_pico], 3),
        "escorrentia_directa_en_el_pico_m3_s": round(escorrentia[idx_pico], 3),
        "indice_paso_del_pico": idx_pico,
        "caudal_base_medio_m3_s": round(volumen_base / len(flujo_base), 4),
        "caudal_medio_m3_s": round(volumen_total / len(caudal_total), 4),
        "interpretacion_bfi": _interpretar_bfi(bfi),
    }


def _interpretar_bfi(bfi: float) -> str:
    if bfi >= 0.70:
        return ("BFI alto: el caudal proviene mayoritariamente del almacenamiento subterráneo. Cuenca "
                "con fuerte regulación natural y estiajes sostenidos.")
    if bfi >= 0.40:
        return ("BFI medio: aportes subterráneo y superficial comparables. Comportamiento típico de "
                "cuencas de montaña con cobertura y suelos de permeabilidad moderada.")
    if bfi >= 0.20:
        return ("BFI bajo: domina la respuesta rápida a la lluvia. Cuenca torrencial, con poca "
                "capacidad de regulación y estiajes marcados.")
    return ("BFI muy bajo: respuesta casi enteramente superficial, con aporte subterráneo mínimo. "
            "Típico de cuencas impermeables, muy pendientes o de régimen efímero.")
