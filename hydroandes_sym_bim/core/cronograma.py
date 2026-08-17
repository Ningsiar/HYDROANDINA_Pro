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

CALENDARIO LABORAL (opcional, ver `CalendarioLaboral`): el CPM en sí
(pase adelante/atrás, holgura, ruta crítica) SIEMPRE trabaja en
"unidades de día" abstractas -- eso NO cambia con o sin calendario. Lo
que sí cambia es `Cronograma.fecha_de()`, que convierte esas unidades
a una fecha de calendario real: SIN calendario (por defecto,
`calendario=None`), suma días CORRIDOS tal cual (comportamiento
histórico de este módulo); CON un `CalendarioLaboral`, cuenta esa
cantidad de días SALTÁNDOSE los no laborables (fines de semana según
el patrón elegido, más los feriados indicados) -- es decir, la
DURACIÓN de cada actividad se sigue interpretando en días de trabajo
(igual que en la práctica: "esta partida toma 5 días" significa 5 días
trabajados, no 5 días de calendario), y es la conversión a fecha la
que ahora respeta qué días son laborables.

ALCANCE Y LIMITACIONES:
  - Relaciones Fin-a-Inicio (FS) únicamente por ahora, con lag/lead
    opcional -- Inicio-a-Inicio (SS), Fin-a-Fin (FF) e Inicio-a-Fin
    (SF) quedan para una fase posterior si hace falta.
  - El calendario laboral solo distingue día laborable/no laborable
    (para saltarlo al convertir a fecha) -- NO modela turnos parciales,
    horas efectivas por día, ni calendarios DISTINTOS por actividad o
    por recurso (MS Project/Primavera sí lo hacen) -- un único
    calendario para todo el proyecto.
  - `feriados_peru()` solo cubre los feriados NACIONALES fijos más
    Jueves/Viernes Santo (movibles, calculados) -- NO incluye feriados
    regionales/locales (varían por departamento) ni los "feriados
    puente" que el Gobierno a veces decreta año a año (no son
    predecibles de antemano); agréguelos a mano si aplican a su obra.
  - NO reemplaza el criterio de un ingeniero de planificación de obra
    ni sustituye una revisión con Microsoft Project/Primavera para un
    cronograma contractual definitivo.
"""
import datetime
import re

DIAS_POR_MES = 30  # aproximación simple para reportes en meses (igual que un cronograma de
# desembolsos típico de obra, ver Módulo Presupuesto) -- no calendario real

# Feriados NACIONALES fijos de Perú (mes, día) -- hechos de dominio
# público (calendario oficial), no cubre feriados regionales/locales
# ni "feriados puente" decretados año a año.
FERIADOS_FIJOS_PERU = (
    (1, 1),    # Año Nuevo
    (5, 1),    # Día del Trabajo
    (6, 29),   # San Pedro y San Pablo
    (7, 28),   # Fiestas Patrias
    (7, 29),   # Fiestas Patrias
    (8, 30),   # Santa Rosa de Lima
    (10, 8),   # Combate de Angamos
    (11, 1),   # Todos los Santos
    (12, 8),   # Inmaculada Concepción
    (12, 9),   # Batalla de Ayacucho
    (12, 25),  # Navidad
)


def _domingo_pascua(anio: int) -> datetime.date:
    """Domingo de Pascua para `anio` (calendario gregoriano) --
    algoritmo anónimo de Gauss/Meeus (computus), el estándar de
    dominio público para esta fecha movible."""
    a = anio % 19
    b = anio // 100
    c = anio % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    mes = (h + m - 7 * n + 114) // 31
    dia = ((h + m - 7 * n + 114) % 31) + 1
    return datetime.date(anio, mes, dia)


def feriados_peru(anio: int, incluir_semana_santa: bool = True) -> list:
    """Feriados NACIONALES de Perú para `anio` -- los fijos
    (FERIADOS_FIJOS_PERU) más, opcionalmente, Jueves y Viernes Santo
    (movibles, calculados desde el Domingo de Pascua). Ver alcance
    exacto en el docstring del módulo."""
    feriados = [datetime.date(anio, mes, dia) for mes, dia in FERIADOS_FIJOS_PERU]
    if incluir_semana_santa:
        pascua = _domingo_pascua(anio)
        feriados.append(pascua - datetime.timedelta(days=3))  # Jueves Santo
        feriados.append(pascua - datetime.timedelta(days=2))  # Viernes Santo
    return feriados


class CalendarioLaboral:
    """Calendario de días laborables para convertir "días de CPM" a
    fechas de calendario reales (ver Cronograma.fecha_de()).
    `dias_libres_semana`: conjunto de índices de date.weekday()
    (0=Lunes ... 6=Domingo) que NO se trabajan -- por defecto {6}
    (solo domingo libre, Lunes a Sábado, el patrón más común en
    construcción civil peruana). `feriados`: colección de
    datetime.date adicionales que tampoco se trabajan (ver
    feriados_peru() para poblarlo con los feriados nacionales)."""

    def __init__(self, dias_libres_semana=None, feriados=None):
        self.dias_libres_semana = set(dias_libres_semana) if dias_libres_semana is not None else {6}
        self.feriados = set(feriados) if feriados else set()

    def es_laborable(self, fecha: datetime.date) -> bool:
        return fecha.weekday() not in self.dias_libres_semana and fecha not in self.feriados

    def avanzar_dias_laborables(self, fecha_inicio: datetime.date, n_dias_laborables) -> datetime.date:
        """Fecha resultante de avanzar `n_dias_laborables` días
        LABORABLES desde `fecha_inicio` (si `fecha_inicio` mismo cae
        en un día no laborable, se adelanta primero al siguiente día
        laborable -- ese pasa a contar como el día 0). `n_dias_laborables`
        se redondea al entero más cercano (mismo criterio que el
        Cronograma sin calendario, que ya redondea el día relativo del
        CPM al convertirlo a fecha)."""
        fecha = fecha_inicio
        while not self.es_laborable(fecha):
            fecha += datetime.timedelta(days=1)
        restantes = round(n_dias_laborables)
        paso = 1 if restantes >= 0 else -1
        while restantes != 0:
            fecha += datetime.timedelta(days=paso)
            if self.es_laborable(fecha):
                restantes -= paso
        return fecha


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

    def __init__(self, nombre: str, actividades: list, fecha_inicio: datetime.date = None,
                 calendario: "CalendarioLaboral" = None):
        self.nombre = nombre
        self.actividades = {}
        for a in actividades:
            if a.codigo in self.actividades:
                raise CronogramaError(f"código de actividad duplicado: «{a.codigo}»")
            self.actividades[a.codigo] = a
        self.fecha_inicio = fecha_inicio or datetime.date.today()
        self.calendario = calendario  # None = días CORRIDOS (comportamiento histórico), ver fecha_de()

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
        a una fecha de calendario real. SIN calendario laboral (por
        defecto): suma días CORRIDOS. CON `self.calendario` asignado:
        cuenta esa cantidad de días LABORABLES desde `fecha_inicio`,
        saltándose fines de semana/feriados -- ver CalendarioLaboral."""
        if self.calendario is None:
            return self.fecha_inicio + datetime.timedelta(days=round(dia_relativo))
        return self.calendario.avanzar_dias_laborables(self.fecha_inicio, dia_relativo)

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


# ======================================================================
# Cronograma de adquisición de materiales -- enlaza este módulo con el
# Módulo Presupuesto, APU e Insumos (core/presupuesto.py) SIN importarlo
# (duck typing sobre Partida/Apu/ItemApu/Insumo, para no crear una
# dependencia entre módulos que no la necesitan en el otro sentido).
# ======================================================================
def cronograma_adquisicion_materiales(cronograma_calculado: "Cronograma", partidas: list,
                                       dias_anticipacion: float = 15.0) -> list:
    """Para cada insumo usado en `partidas` (lista de
    core.presupuesto.Partida, cada una con su Apu ya armado), calcula
    cuándo debe estar disponible en obra: la fecha de Inicio Temprano
    (ES) de la actividad con el MISMO CÓDIGO en `cronograma_calculado`
    (ya con .calcular() ejecutado), menos `dias_anticipacion` días de
    plazo de compra/entrega -- y la cantidad total requerida,
    consolidada si el insumo se usa en más de una partida (se toma la
    fecha MÁS TEMPRANA entre todas las que lo necesitan, para que la
    compra alcance a cubrir el primer uso). Partidas sin una actividad
    de igual código en el cronograma se omiten (no hay fecha con la
    que calcular su necesidad) -- ver Cronograma.resumen_actividades()
    para saber qué actividades sí están programadas.
    Devuelve una lista ordenada por fecha_requerida (lo más urgente
    primero)."""
    acumulado = {}
    for partida in partidas:
        act = cronograma_calculado.actividades.get(partida.codigo)
        if act is None or act.es is None or partida.apu is None:
            continue
        fecha_requerida = cronograma_calculado.fecha_de(act.es) - datetime.timedelta(days=dias_anticipacion)
        for item in partida.apu.items:
            cantidad = item.cantidad_por_unidad() * partida.metrado
            clave = item.insumo.codigo
            if clave not in acumulado:
                acumulado[clave] = {"insumo": item.insumo, "cantidad_total": 0.0,
                                     "fecha_mas_temprana": fecha_requerida, "codigos_partida": set()}
            acumulado[clave]["cantidad_total"] += cantidad
            acumulado[clave]["fecha_mas_temprana"] = min(
                acumulado[clave]["fecha_mas_temprana"], fecha_requerida)
            acumulado[clave]["codigos_partida"].add(partida.codigo)

    filas = [{
        "codigo": datos["insumo"].codigo, "descripcion": datos["insumo"].descripcion,
        "unidad": datos["insumo"].unidad, "tipo": datos["insumo"].tipo,
        "cantidad_total": round(datos["cantidad_total"], 4),
        "fecha_requerida": datos["fecha_mas_temprana"],
        "n_partidas": len(datos["codigos_partida"]),
    } for datos in acumulado.values()]
    filas.sort(key=lambda f: f["fecha_requerida"])
    return filas


# ======================================================================
# Importación de un cronograma real de Microsoft Project (MSPDI --
# Microsoft Project Data Interchange, el formato XML que MS Project
# exporta con "Guardar como... XML") -- SOLO con la librería estándar
# de Python (xml.etree.ElementTree), sin dependencias externas.
# ======================================================================
def _parsear_duracion_mspdi_horas(texto: str) -> float:
    """«PT2864H0M0S» (formato de duración MSPDI, similar a ISO 8601)
    -> horas totales (float). Devuelve 0.0 si el texto es None/vacío o
    no tiene el formato esperado."""
    if not texto:
        return 0.0
    m = re.match(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?", texto)
    if not m:
        return 0.0
    dias, horas, minutos, segundos = (float(g) if g else 0.0 for g in m.groups())
    return dias * 24.0 + horas + minutos / 60.0 + segundos / 3600.0


def importar_mspdi(ruta_archivo: str):
    """Importa un cronograma real exportado de Microsoft Project en
    formato XML (MSPDI), usando SOLO xml.etree.ElementTree (librería
    estándar, sin dependencias externas).

    Se importan las tareas HOJA (Summary=0) como Actividad -- las
    tareas RESUMEN (agrupadores de WBS, Summary=1) se omiten como
    actividades independientes del CPM porque su duración es la suma
    de sus tareas hijas, no una duración propia programable (mismo
    criterio que un presupuesto de obra real: sus "Títulos/Subtítulos"
    no son partidas ejecutables, ver core/presupuesto.py). El CÓDIGO de
    cada Actividad es el UID de la tarea en el XML (estable -- a
    diferencia del ID visible en pantalla, que cambia si se reordenan
    filas en MS Project), así que NO va a coincidir con el código de
    una Partida de S10 a menos que se arme el archivo a propósito para
    eso.

    DURACIÓN: convertida de horas (formato MSPDI «PTxHxMxSxS») a DÍAS
    usando 8 horas = 1 día -- la misma convención de jornada que el
    resto del plugin (ver core/presupuesto.py::JORNADA_HORAS). Coincide
    exactamente con un calendario de "días corridos" (semana completa,
    sin fines de semana descontados), pero puede no coincidir con un
    calendario de 5 días laborables real si el archivo lo usa --
    verifique contra el calendario real del proyecto.

    PREDECESORAS: se importan TODAS como relación Fin-a-Inicio (FS) --
    el único tipo que soporta este módulo por ahora -- sin distinguir
    Inicio-a-Inicio/Fin-a-Fin/Inicio-a-Fin si el archivo original los
    usa (limitación conocida). Las predecesoras que apuntan a una tarea
    RESUMEN (o a una tarea que no quedó entre las hojas importadas) se
    omiten, con una advertencia -- en vez de fallar todo el import.

    Devuelve (Cronograma, advertencias) -- `advertencias` es una lista
    de mensajes (str) sobre datos que se omitieron o aproximaron."""
    import xml.etree.ElementTree as ET

    try:
        tree = ET.parse(ruta_archivo)
    except (ET.ParseError, OSError) as e:
        raise CronogramaError(f"no se pudo leer el archivo MSPDI -- {e}") from e
    root = tree.getroot()
    ns_uri = root.tag.split("}")[0].strip("{") if root.tag.startswith("{") else ""

    def tag(t):
        return f"{{{ns_uri}}}{t}" if ns_uri else t

    tareas_el = root.find(tag("Tasks"))
    if tareas_el is None:
        raise CronogramaError(
            "el archivo no tiene ninguna sección <Tasks> -- no parece un MSPDI válido "
            "(en MS Project: Archivo > Guardar como... > tipo XML).")

    fecha_inicio_proyecto = None
    texto_fecha = root.findtext(tag("StartDate"))
    if texto_fecha:
        try:
            fecha_inicio_proyecto = datetime.date.fromisoformat(texto_fecha[:10])
        except ValueError:
            pass
    fecha_fin_proyecto_mspdi = None
    texto_fecha_fin = root.findtext(tag("FinishDate"))
    if texto_fecha_fin:
        try:
            fecha_fin_proyecto_mspdi = datetime.date.fromisoformat(texto_fecha_fin[:10])
        except ValueError:
            pass

    datos_por_uid = {}
    for t in tareas_el.findall(tag("Task")):
        uid = t.findtext(tag("UID"))
        if uid is None:
            continue
        predecesoras = [p.findtext(tag("PredecessorUID")) for p in t.findall(tag("PredecessorLink"))]
        datos_por_uid[uid] = {
            "nombre": t.findtext(tag("Name")) or f"Tarea {uid}",
            "es_resumen": t.findtext(tag("Summary")) == "1",
            "duracion_dias": _parsear_duracion_mspdi_horas(t.findtext(tag("Duration"))) / 8.0,
            "predecesoras": [p for p in predecesoras if p],
        }

    uids_hoja = {u for u, d in datos_por_uid.items() if not d["es_resumen"]}
    advertencias = []
    actividades = []
    for uid, d in datos_por_uid.items():
        if d["es_resumen"]:
            continue
        predecesoras_validas = [p for p in d["predecesoras"] if p in uids_hoja]
        omitidas = len(d["predecesoras"]) - len(predecesoras_validas)
        if omitidas:
            advertencias.append(
                f"la tarea «{d['nombre']}» (UID {uid}) tenía {omitidas} predecesora(s) que son "
                f"tareas resumen (o no quedaron entre las hojas importadas) -- se omitieron.")
        actividades.append(Actividad(uid, d["nombre"], max(d["duracion_dias"], 0.0),
                                      predecesoras=predecesoras_validas))

    if not actividades:
        raise CronogramaError(
            "no se encontró ninguna tarea hoja (Summary=0) en el archivo -- ¿es un MSPDI vacío?")

    if fecha_inicio_proyecto and fecha_fin_proyecto_mspdi:
        advertencias.insert(0, (
            f"MS Project calculó este cronograma del {fecha_inicio_proyecto:%d-%m-%Y} al "
            f"{fecha_fin_proyecto_mspdi:%d-%m-%Y} ({(fecha_fin_proyecto_mspdi - fecha_inicio_proyecto).days} "
            f"días) -- considerando calendarios, restricciones y nivelación de recursos que este "
            f"importador NO reproduce. Al presionar «Calcular CPM» en este plugin, la duración "
            f"total y las fechas de cada actividad se RECALCULAN desde cero, solo a partir de las "
            f"duraciones y relaciones Fin-a-Inicio de este archivo -- pueden diferir sustancialmente "
            f"de las fechas originales de MS Project. Útil para auditar la red lógica "
            f"(duración + predecesoras) del cronograma real, no como reemplazo exacto."))

    nombre_proyecto = root.findtext(tag("Name")) or root.findtext(tag("Title")) or "Cronograma importado"
    cron = Cronograma(nombre_proyecto, actividades, fecha_inicio=fecha_inicio_proyecto)
    return cron, advertencias
