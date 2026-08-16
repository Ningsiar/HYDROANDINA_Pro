# -*- coding: utf-8 -*-
"""
core/cronograma.py

Módulo "Programación y Cronogramas" -- fase 1 de N: núcleo de datos y
motor CPM (Método de la Ruta Crítica) + PERT (estimación de 3 puntos),
sin dependencias de Qt -- mismo patrón que core/presupuesto.py y
core/bim_geometry.py.

MÉTODO: Programación por Precedencias (Precedence Diagramming Method,
PDM) con relaciones Fin-a-Inicio (FS, Finish-to-Start) + holgura
opcional (lag si es positiva/espera, lead si es negativa/adelanto) --
la relación más común en construcción civil y la que usa Microsoft
Project por defecto.

CPM (Critical Path Method), sobre las actividades ya en orden
topológico (Cronograma._orden_topologico(), detecta ciclos):
  1. PASE HACIA ADELANTE (forward pass): Inicio Temprano (ES) y Fin
     Temprano (EF = ES + duración) de cada actividad, a partir de sus
     predecesoras: ES = max(EF_predecesora + lag) sobre todas sus
     predecesoras (0 si no tiene ninguna).
  2. PASE HACIA ATRÁS (backward pass): Fin Tardío (LF) e Inicio Tardío
     (LS = LF - duración), a partir de sus sucesoras: LF = min(LS_sucesora
     - lag) sobre todas sus sucesoras (duración total del proyecto si
     no tiene ninguna).
  3. HOLGURA (float) = LS - ES (= LF - EF). Actividades con holgura 0
     forman la RUTA CRÍTICA -- cualquier atraso en ellas atrasa todo
     el proyecto; el resto tiene margen para atrasarse sin afectar la
     fecha final, hasta agotar su holgura.

PERT (Program Evaluation and Review Technique) -- estimación de
duración de 3 puntos, cuando la duración no se conoce con certeza:
    duración_esperada (te) = (to + 4·tm + tp) / 6
    varianza = ((tp - to) / 6)²
donde to=optimista, tm=más probable, tp=pesimista (distribución beta
asumida, la aproximación clásica de PERT). Opcional: si se dan los 3
valores, se usa duración_esperada; si se da una sola duración, se usa
tal cual (CPM determinístico puro).

ALCANCE Y LIMITACIONES:
  - Relaciones Fin-a-Inicio (FS) únicamente por ahora, con lag/lead
    opcional -- Inicio-a-Inicio (SS), Fin-a-Fin (FF) e Inicio-a-Fin
    (SF) quedan para una fase posterior si hace falta.
  - Días CORRIDOS, no días hábiles -- sin calendario laboral (fines de
    semana/feriados). Para un cronograma contractual definitivo,
    ajuste las duraciones considerando los días no laborables de su
    calendario real.
  - NO reemplaza el criterio de un ingeniero de planificación de obra
    ni sustituye una revisión con Microsoft Project/Primavera para un
    cronograma contractual definitivo.
"""
import datetime

DIAS_POR_MES = 30  # aproximación simple para reportes en meses (igual que un cronograma de
# desembolsos típico de obra, ver Módulo Presupuesto) -- no calendario real


class CronogramaError(Exception):
    """Datos insuficientes o inconsistentes para calcular el CPM (ciclo
    de dependencias, predecesora inexistente, duración inválida) -- el
    mensaje explica exactamente qué falla."""


def duracion_pert(optimista: float, mas_probable: float, pesimista: float):
    """Duración esperada (te) y varianza de la aproximación beta de
    PERT, a partir de una estimación de 3 puntos. Levanta CronogramaError
    si los 3 valores no están en orden optimista <= mas_probable <= pesimista."""
    if not (optimista <= mas_probable <= pesimista):
        raise CronogramaError(
            f"la estimación PERT debe cumplir optimista ({optimista}) <= más probable "
            f"({mas_probable}) <= pesimista ({pesimista}).")
    te = (optimista + 4.0 * mas_probable + pesimista) / 6.0
    varianza = ((pesimista - optimista) / 6.0) ** 2
    return te, varianza


class Actividad:
    """Una actividad del cronograma -- código (puede coincidir con el
    código de una Partida del Módulo Presupuesto, para enlazarlas),
    nombre, duración en días corridos, y sus predecesoras (relación
    Fin-a-Inicio + lag/lead opcional por predecesora). Los campos
    es/ef/ls/lf/holgura/es_critica los llena Cronograma.calcular() --
    no se deben fijar a mano."""

    def __init__(self, codigo: str, nombre: str, duracion_dias: float,
                 predecesoras: list = None, lag_dias: dict = None):
        if duracion_dias < 0:
            raise CronogramaError(f"duración negativa en la actividad «{codigo}»")
        self.codigo = codigo
        self.nombre = nombre
        self.duracion_dias = float(duracion_dias)
        self.predecesoras = list(predecesoras) if predecesoras else []
        self.lag_dias = dict(lag_dias) if lag_dias else {}
        # resultados del CPM (día relativo al inicio del proyecto, 0 = día 1)
        self.es = None
        self.ef = None
        self.ls = None
        self.lf = None
        self.holgura = None
        self.es_critica = False


class Cronograma:
    """Un cronograma completo -- diccionario de Actividad (por código)
    más la fecha de inicio real del proyecto (para convertir los días
    relativos del CPM a fechas de calendario)."""

    def __init__(self, nombre: str, actividades: list, fecha_inicio: datetime.date = None):
        self.nombre = nombre
        self.actividades = {}
        for a in actividades:
            if a.codigo in self.actividades:
                raise CronogramaError(f"código de actividad duplicado: «{a.codigo}»")
            self.actividades[a.codigo] = a
        self.fecha_inicio = fecha_inicio or datetime.date.today()

    def _orden_topologico(self) -> list:
        """Orden de las actividades tal que toda predecesora aparece
        antes que sus sucesoras (algoritmo de Kahn) -- levanta
        CronogramaError si hay un ciclo de dependencias (imposible de
        programar) o una predecesora que no existe."""
        grado_entrada = {c: 0 for c in self.actividades}
        sucesoras = {c: [] for c in self.actividades}
        for act in self.actividades.values():
            for pred_codigo in act.predecesoras:
                if pred_codigo not in self.actividades:
                    raise CronogramaError(
                        f"la actividad «{act.codigo}» tiene como predecesora a «{pred_codigo}», "
                        f"que no existe en el cronograma.")
                sucesoras[pred_codigo].append(act.codigo)
                grado_entrada[act.codigo] += 1
        cola = [c for c, g in grado_entrada.items() if g == 0]
        orden = []
        while cola:
            actual = cola.pop(0)
            orden.append(actual)
            for suc in sucesoras[actual]:
                grado_entrada[suc] -= 1
                if grado_entrada[suc] == 0:
                    cola.append(suc)
        if len(orden) != len(self.actividades):
            pendientes = [c for c in self.actividades if c not in orden]
            raise CronogramaError(
                f"hay un ciclo de dependencias entre las actividades {pendientes} -- "
                f"un cronograma no puede tener dependencias circulares.")
        return orden

    def calcular(self) -> dict:
        """Corre el CPM completo (pase adelante + pase atrás + holgura
        + ruta crítica) sobre todas las actividades -- modifica cada
        Actividad en el sitio (es/ef/ls/lf/holgura/es_critica) y
        devuelve el resumen del proyecto."""
        if not self.actividades:
            raise CronogramaError("el cronograma no tiene ninguna actividad")
        orden = self._orden_topologico()

        # --- pase hacia adelante ---
        for codigo in orden:
            act = self.actividades[codigo]
            if not act.predecesoras:
                act.es = 0.0
            else:
                act.es = max(
                    self.actividades[p].ef + act.lag_dias.get(p, 0.0) for p in act.predecesoras)
            act.ef = act.es + act.duracion_dias

        duracion_total = max(a.ef for a in self.actividades.values())

        # --- pase hacia atrás ---
        sucesoras = {c: [] for c in self.actividades}
        for act in self.actividades.values():
            for pred_codigo in act.predecesoras:
                sucesoras[pred_codigo].append(act.codigo)
        for codigo in reversed(orden):
            act = self.actividades[codigo]
            sucs = sucesoras[codigo]
            if not sucs:
                act.lf = duracion_total
            else:
                act.lf = min(
                    self.actividades[s].ls - self.actividades[s].lag_dias.get(codigo, 0.0)
                    for s in sucs)
            act.ls = act.lf - act.duracion_dias
            act.holgura = act.ls - act.es
            act.es_critica = abs(act.holgura) < 1e-6

        ruta_critica = [c for c in orden if self.actividades[c].es_critica]
        return {
            "duracion_total_dias": duracion_total,
            "fecha_inicio": self.fecha_inicio,
            "fecha_fin": self.fecha_de(duracion_total),
            "ruta_critica": ruta_critica,
            "n_actividades": len(self.actividades),
            "n_actividades_criticas": len(ruta_critica),
        }

    def fecha_de(self, dia_relativo: float) -> datetime.date:
        """Convierte un día relativo del CPM (0 = inicio del proyecto)
        a una fecha de calendario real, sumando días corridos."""
        return self.fecha_inicio + datetime.timedelta(days=round(dia_relativo))

    def resumen_actividades(self) -> list:
        """Lista de dicts (uno por actividad, en orden de ES) lista
        para una tabla de interfaz -- código, nombre, duración,
        ES/EF/LS/LF en días Y en fechas, holgura, y si es crítica."""
        filas = []
        for act in sorted(self.actividades.values(), key=lambda a: (a.es or 0, a.codigo)):
            filas.append({
                "codigo": act.codigo, "nombre": act.nombre, "duracion_dias": act.duracion_dias,
                "es_dia": act.es, "ef_dia": act.ef, "ls_dia": act.ls, "lf_dia": act.lf,
                "es_fecha": self.fecha_de(act.es), "ef_fecha": self.fecha_de(act.ef),
                "ls_fecha": self.fecha_de(act.ls), "lf_fecha": self.fecha_de(act.lf),
                "holgura_dias": act.holgura, "critica": act.es_critica,
                "predecesoras": list(act.predecesoras),
            })
        return filas
