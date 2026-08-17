# -*- coding: utf-8 -*-
"""
core/curva_s.py

Curva S de avance físico-financiero PLANIFICADO -- combina el
Presupuesto (costo por partida) con el Cronograma YA CALCULADO (fechas
ES/EF por actividad, mismo código que la partida) en una curva
acumulada de costo/avance en el tiempo. Sin dependencias de Qt, y SIN
importar core.presupuesto ni core.cronograma (duck typing sobre ambos
-- mismo patrón que cronograma_adquisicion_materiales() en
core/cronograma.py, para no crear una dependencia entre módulos que no
la necesitan en el otro sentido).

MÉTODO: cada partida vinculada a una actividad de MISMO CÓDIGO
distribuye su costo_parcial() LINEALMENTE a lo largo de la duración de
esa actividad (ES a EF) -- el supuesto estándar cuando no se cuenta
con una curva de desembolso propia por partida (si una partida tiene
un patrón de ejecución conocido no lineal -- arranque lento, etc. --
este módulo no lo modela; ajuste manualmente si hace falta mayor
precisión). La curva se arma en cortes periódicos (diario/semanal/
mensual) sumando, en cada corte, la fracción de costo YA "transcurrida"
de cada partida vinculada.

Partidas SIN una actividad de igual código en el cronograma NO pueden
ubicarse en el tiempo -- se EXCLUYEN de la curva y se reportan aparte
(`partidas_excluidas`/`costo_excluido`), para que el usuario sepa qué
fracción del presupuesto total la curva no cubre (enlácelas generando/
editando las actividades del cronograma, Pestaña 10).

AVANCE FÍSICO vs. FINANCIERO: esta curva es, en rigor, la de avance
FINANCIERO planificado (S/. acumulados). En la práctica de
valorización de obra peruana, el avance FÍSICO planificado se reporta
con la MISMA curva expresada en % (cada partida "pesa" en el avance
físico proporcional a su costo, no a su metrado -- es la convención
usual cuando las partidas son heterogéneas en unidades) -- por eso
`curva_s_planificada()` devuelve el acumulado tanto en S/. como en %,
ambos derivados de la misma distribución, no de dos cálculos
independientes.

ALCANCE: curva PLANIFICADA únicamente -- este plugin no registra
avance REAL ejecutado (valorizaciones), así que no compara curva
planificada vs. real (el uso típico de una Curva S en obra). Si se
agrega un módulo de valorizaciones a futuro, esta función es la base
para la curva planificada de esa comparación.
"""
DIAS_POR_MES = 30  # misma convención que core/presupuesto.py -- no es un calendario real


class CurvaSError(Exception):
    """Datos insuficientes o inconsistentes (presupuesto vacío, ninguna
    partida vinculada al cronograma, período no reconocido) -- el
    mensaje explica exactamente qué falta."""


def _fraccion_transcurrida(dia_evaluado: float, es: float, ef: float) -> float:
    """Fracción [0,1] de la duración [es, ef] ya transcurrida en
    `dia_evaluado` -- 0 antes de es, 1 desde ef en adelante, LINEAL en
    medio. Si es==ef (actividad de duración 0), el costo se aplica
    íntegro apenas dia_evaluado >= es (instantáneo, sin tramo lineal
    que dividir por cero)."""
    if ef <= es:
        return 1.0 if dia_evaluado >= es else 0.0
    if dia_evaluado <= es:
        return 0.0
    if dia_evaluado >= ef:
        return 1.0
    return (dia_evaluado - es) / (ef - es)


def curva_s_planificada(presupuesto_calculado, cronograma_calculado, periodo: str = "semanal") -> dict:
    """`presupuesto_calculado`: objeto con `.partidas` (lista de
    Partida -- cada una con `.codigo` y `.costo_parcial()`).
    `cronograma_calculado`: objeto con `.actividades` (dict código ->
    Actividad, cada una YA con `.es`/`.ef` puestos por
    `Cronograma.calcular()`) y `.fecha_de(dia)`. `periodo`: "diario",
    "semanal" (7 días) o "mensual" (30 días, misma convención que el
    resto del plugin)."""
    if not presupuesto_calculado.partidas:
        raise CurvaSError("el presupuesto no tiene ninguna partida.")

    dias_periodo = {"diario": 1, "semanal": 7, "mensual": DIAS_POR_MES}.get(periodo)
    if dias_periodo is None:
        raise CurvaSError(f"período «{periodo}» no reconocido -- use 'diario', 'semanal' o 'mensual'.")

    vinculadas = []
    excluidas = []
    costo_excluido = 0.0
    for p in presupuesto_calculado.partidas:
        act = cronograma_calculado.actividades.get(p.codigo)
        costo = p.costo_parcial()
        if act is None or act.es is None or act.ef is None:
            excluidas.append(p.codigo)
            costo_excluido += costo
            continue
        vinculadas.append((p, act, costo))

    if not vinculadas:
        raise CurvaSError(
            "ninguna partida del presupuesto tiene una actividad con el mismo código en el "
            "cronograma -- genere/edite las actividades (Pestaña 10, sección 1b) para que los "
            "códigos coincidan con los de las partidas del presupuesto.")

    costo_total_programable = sum(c for _, _, c in vinculadas)
    dia_max = max(act.ef for _, act, _ in vinculadas)

    puntos = []
    dia = 0.0
    while True:
        acumulado = sum(c * _fraccion_transcurrida(dia, act.es, act.ef) for _, act, c in vinculadas)
        puntos.append({
            "dia": dia, "fecha": cronograma_calculado.fecha_de(dia),
            "costo_acumulado": round(acumulado, 2),
            "pct_acumulado": round(100.0 * acumulado / costo_total_programable, 3)
            if costo_total_programable > 0 else 0.0,
        })
        if dia >= dia_max:
            break
        dia = min(dia + dias_periodo, dia_max)

    return {
        "periodo": periodo, "puntos": puntos,
        "costo_total_programable": round(costo_total_programable, 2),
        "n_partidas_programadas": len(vinculadas),
        "partidas_excluidas": excluidas, "costo_excluido": round(costo_excluido, 2),
        "n_partidas_excluidas": len(excluidas),
        "metodo": ("Distribución LINEAL del costo de cada partida entre el Inicio Temprano (ES) y "
                   "Fin Temprano (EF) de su actividad vinculada (mismo código) -- curva S "
                   "PLANIFICADA (este plugin no registra avance REAL ejecutado, no hay comparación "
                   "planificado vs. real). El avance FÍSICO planificado se reporta con la misma "
                   "curva en %, proporcional al peso de costo de cada partida."),
    }
