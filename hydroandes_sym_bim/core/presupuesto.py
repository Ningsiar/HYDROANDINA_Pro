# -*- coding: utf-8 -*-
"""
core/presupuesto.py

Módulo "Presupuesto, APU e Insumos" -- fase 1 de N: núcleo de datos y
motor de cálculo, sin dependencias de Qt (funciones y clases puras),
mismo patrón que core/bim_geometry.py y core/hydraulic_structures.py.

Estructura general (el estándar de facto en construcción civil
peruana, tipo S10 Presupuestos):
  - Presupuesto: lista de Partidas (cada una con su propio código,
    descripción, unidad, metrado y ruta de agrupación Título/Subtítulo
    -- la agrupación es solo una cadena de texto para que la interfaz
    arme el árbol EDT; el cálculo no depende de esa jerarquía).
  - Cada Partida tiene un Análisis de Precios Unitarios (APU) propio:
    Mano de Obra + Materiales + Equipos + Herramienta Menor, cada uno
    con sus propios ItemApu (insumo + cuadrilla/rendimiento o cantidad
    directa) tomados de una librería reutilizable de Insumo.
  - La Relación de Insumos consolida TODOS los insumos de TODAS las
    partidas (multiplicados por su metrado) en una sola lista de
    compra -- es la que alimentará el cronograma de adquisición de
    materiales del futuro módulo de Programación y Cronogramas.

FÓRMULAS (mano de obra y equipo, método del rendimiento -- el mismo
que usa S10/CAPECO):
    cantidad_por_unidad_partida (hh u hm) = (cuadrilla × 8 horas/jornal) / rendimiento
donde `cuadrilla` es el número de personas/equipos de ese recurso en
la cuadrilla típica (p.ej. 1 Operario + 0.5 Oficial + 2 Peones) y
`rendimiento` es cuánto produce esa cuadrilla por jornada de 8 horas
(unidad de la partida / día) -- el resultado queda en horas-hombre
(hh) u horas-máquina (hm) por unidad de partida, que es como S10
expresa el precio unitario de mano de obra/equipo (S/./hh, S/./hm).
Para materiales, la cantidad es directa (con un % de desperdicio
opcional). Para herramienta menor sin insumo propio, ver
`agregar_herramienta_manual_pct()` -- el atajo usual de expresarla
como un % del subtotal de mano de obra.

RENDIMIENTOS: este módulo NO trae cifras de CAPECO/Revista Costos
precargadas -- son tablas de publicaciones comerciales, no
reproducibles de memoria de forma confiable ni por derechos de autor.
La librería de insumos/rendimientos es 100% editable por el usuario,
igual que la matriz de uso de suelo del número de curva SCS
(core/curve_number.py). Si el usuario aporta el documento fuente, se
puede poblar con cifras reales verificadas -- mismo patrón que las
Tablas 37-39 de IILA-SENAMHI (core/iila_senamhi_zones.py).
"""

JORNADA_HORAS = 8.0  # horas por jornal -- estándar de construcción civil en Perú


class TipoInsumo:
    """Las 4 categorías clásicas de un APU peruano (S10/CAPECO)."""
    MANO_DE_OBRA = "Mano de Obra"
    MATERIALES = "Materiales"
    EQUIPOS = "Equipos"
    HERRAMIENTAS = "Herramienta Manual"
    SUBCONTRATOS = "Subcontratos"

    TODOS = (MANO_DE_OBRA, MATERIALES, EQUIPOS, HERRAMIENTAS, SUBCONTRATOS)


class PresupuestoError(Exception):
    """Datos insuficientes o inconsistentes para calcular un APU, una
    partida, el presupuesto o la relación de insumos -- el mensaje
    explica exactamente qué falta o qué valor es inválido."""


# ======================================================================
# Librería de insumos (recursos reutilizables entre partidas)
# ======================================================================
class Insumo:
    """Un recurso de la librería -- descripción, unidad y precio
    unitario, independiente de en qué partidas se use. `codigo` es la
    clave que consolida cantidades iguales en la Relación de Insumos
    (dos ItemApu con el mismo Insumo se suman, no se duplican).
    `indice_inei` (opcional) es el código del Índice Unificado de
    Precios de la Construcción del INEI al que corresponde este
    insumo (ver core/formula_polinomica.py::INDICES_INEI) -- se usa
    para calcular la Fórmula Polinómica de reajuste; no hace falta
    para presupuestar ni para el APU."""

    __slots__ = ("codigo", "descripcion", "unidad", "tipo", "precio_unitario", "indice_inei")

    def __init__(self, codigo: str, descripcion: str, unidad: str, tipo: str,
                 precio_unitario: float, indice_inei: int = None):
        if tipo not in TipoInsumo.TODOS:
            raise PresupuestoError(
                f"tipo de insumo «{tipo}» no reconocido -- use uno de {TipoInsumo.TODOS}")
        if precio_unitario < 0:
            raise PresupuestoError(f"precio unitario negativo para «{descripcion}»")
        self.codigo = codigo
        self.descripcion = descripcion
        self.unidad = unidad
        self.tipo = tipo
        self.precio_unitario = float(precio_unitario)
        self.indice_inei = indice_inei


# ======================================================================
# Análisis de Precios Unitarios (APU)
# ======================================================================
class ItemApu:
    """Una fila del APU de UNA partida -- referencia a un Insumo de la
    librería más:
      - Mano de Obra / Equipos: `cuadrilla` (recursos de ese tipo en la
        cuadrilla, típicamente 0.1-10) y `rendimiento` (unidad de la
        partida por jornada de esa cuadrilla, > 0) -- la cantidad se
        DERIVA (cuadrilla / rendimiento), no se ingresa directamente.
      - Materiales / Herramienta Manual (como insumo propio, poco
        común): `cantidad` directa por unidad de partida, con un
        `desperdicio_pct` opcional (p.ej. 5.0 para 5%)."""

    def __init__(self, insumo: Insumo, cuadrilla: float = None, rendimiento: float = None,
                 cantidad: float = None, desperdicio_pct: float = 0.0):
        self.insumo = insumo
        self.cuadrilla = cuadrilla
        self.rendimiento = rendimiento
        self.cantidad = cantidad
        self.desperdicio_pct = desperdicio_pct or 0.0

    def cantidad_por_unidad(self) -> float:
        """Cantidad de este insumo requerida por CADA unidad de la
        partida (p.ej. hh/m³, kg/m², un/m³)."""
        usa_rendimiento = self.insumo.tipo in (TipoInsumo.MANO_DE_OBRA, TipoInsumo.EQUIPOS)
        if usa_rendimiento and self.rendimiento is not None:
            if self.rendimiento <= 0:
                raise PresupuestoError(
                    f"rendimiento inválido ({self.rendimiento}) para «{self.insumo.descripcion}»")
            cuadrilla = self.cuadrilla if self.cuadrilla is not None else 1.0
            return (cuadrilla / self.rendimiento) * JORNADA_HORAS
        if self.cantidad is None:
            raise PresupuestoError(
                f"falta cantidad (o cuadrilla/rendimiento) para «{self.insumo.descripcion}»")
        return self.cantidad * (1.0 + self.desperdicio_pct / 100.0)

    def parcial_por_unidad(self) -> float:
        """Costo de este insumo por CADA unidad de la partida (S/. por
        unidad de partida) -- lo que se suma para el precio unitario."""
        return self.cantidad_por_unidad() * self.insumo.precio_unitario


class Apu:
    """El Análisis de Precios Unitarios completo de UNA partida --
    lista de ItemApu de las 4 categorías."""

    def __init__(self, items: list = None):
        self.items = list(items) if items else []

    def agregar(self, item: ItemApu):
        self.items.append(item)
        return self

    def subtotal_por_tipo(self) -> dict:
        """{tipo: S/. por unidad de partida} -- para el desglose que
        muestra S10 (Mano de Obra / Materiales / Equipos / Herramienta)."""
        subtotales = {t: 0.0 for t in TipoInsumo.TODOS}
        for item in self.items:
            subtotales[item.insumo.tipo] += item.parcial_por_unidad()
        return subtotales

    def precio_unitario(self) -> float:
        """S/. por unidad de la partida -- la cifra que S10 llama
        "Costo Unitario" del APU."""
        if not self.items:
            raise PresupuestoError("el APU no tiene ningún insumo agregado")
        return sum(item.parcial_por_unidad() for item in self.items)


def agregar_herramienta_manual_pct(apu: Apu, insumo_herramienta: Insumo, porcentaje: float = 3.0):
    """Atajo para el caso MUY común en que la herramienta manual no se
    detalla insumo por insumo, sino como un % del subtotal de Mano de
    Obra (3-5% es lo habitual en la práctica peruana). `insumo_herramienta`
    debe ser un Insumo de tipo TipoInsumo.HERRAMIENTAS con
    precio_unitario=1.0 (se usa como "factor", no como precio real).
    Modifica `apu` en el sitio y lo devuelve."""
    subtotal_mo = sum(i.parcial_por_unidad() for i in apu.items
                       if i.insumo.tipo == TipoInsumo.MANO_DE_OBRA)
    if subtotal_mo <= 0:
        raise PresupuestoError(
            "no se puede calcular herramienta manual por % -- agregue primero la mano de obra")
    monto = subtotal_mo * porcentaje / 100.0
    apu.agregar(ItemApu(insumo_herramienta, cantidad=monto))
    return apu


# ======================================================================
# Partida y Presupuesto
# ======================================================================
class Partida:
    """Una partida del presupuesto -- código, descripción, unidad,
    metrado (cantidad a ejecutar) y su propio Apu. `grupo` es SOLO una
    ruta de texto (p.ej. "01 ESTRUCTURAS > 01.02 CONCRETO ARMADO") para
    que la interfaz arme el árbol Título/Subtítulo -- el cálculo no
    depende de esa jerarquía, cada Partida se evalúa de forma
    independiente. `origen_metrado` documenta de dónde salió el
    metrado (p.ej. "Módulo BIM -- Pestaña 8b: Canal 01") cuando viene
    autocompletado, para que quede trazable en el reporte."""

    def __init__(self, codigo: str, descripcion: str, unidad: str, metrado: float,
                 apu: Apu = None, grupo: str = "", origen_metrado: str = ""):
        if metrado < 0:
            raise PresupuestoError(f"metrado negativo en la partida «{descripcion}»")
        self.codigo = codigo
        self.descripcion = descripcion
        self.unidad = unidad
        self.metrado = float(metrado)
        self.apu = apu
        self.grupo = grupo
        self.origen_metrado = origen_metrado

    def precio_unitario(self) -> float:
        if self.apu is None:
            raise PresupuestoError(f"la partida «{self.descripcion}» no tiene APU asignado")
        return self.apu.precio_unitario()

    def costo_parcial(self) -> float:
        return self.metrado * self.precio_unitario()


class Presupuesto:
    """Un presupuesto completo -- lista de Partidas más los porcentajes
    globales de gastos generales, utilidad e IGV (estructura estándar
    peruana: Costo Directo -> + GG -> + Utilidad -> Subtotal -> + IGV
    -> Presupuesto Total)."""

    def __init__(self, nombre: str, partidas: list = None,
                 gastos_generales_pct: float = 10.0, utilidad_pct: float = 10.0,
                 igv_pct: float = 18.0):
        self.nombre = nombre
        self.partidas = list(partidas) if partidas else []
        self.gastos_generales_pct = gastos_generales_pct
        self.utilidad_pct = utilidad_pct
        self.igv_pct = igv_pct

    def agregar(self, partida: Partida):
        self.partidas.append(partida)
        return self

    def costo_directo(self) -> float:
        return sum(p.costo_parcial() for p in self.partidas)

    def resumen(self) -> dict:
        """Cuadro resumen del presupuesto -- costo directo, gastos
        generales, utilidad, subtotal, IGV y total, más el % que
        representa cada partida sobre el costo directo (para el
        gráfico de composición de costos)."""
        cd = self.costo_directo()
        gg = cd * self.gastos_generales_pct / 100.0
        ut = cd * self.utilidad_pct / 100.0
        subtotal = cd + gg + ut
        igv = subtotal * self.igv_pct / 100.0
        total = subtotal + igv
        composicion = []
        for p in self.partidas:
            parcial = p.costo_parcial()
            composicion.append({
                "codigo": p.codigo, "descripcion": p.descripcion, "grupo": p.grupo,
                "metrado": p.metrado, "unidad": p.unidad,
                "precio_unitario": round(p.precio_unitario(), 2),
                "parcial": round(parcial, 2),
                "pct_costo_directo": round(100.0 * parcial / cd, 2) if cd > 0 else 0.0,
            })
        return {
            "nombre": self.nombre, "costo_directo": round(cd, 2),
            "gastos_generales_pct": self.gastos_generales_pct, "gastos_generales": round(gg, 2),
            "utilidad_pct": self.utilidad_pct, "utilidad": round(ut, 2),
            "subtotal": round(subtotal, 2),
            "igv_pct": self.igv_pct, "igv": round(igv, 2),
            "total": round(total, 2),
            "n_partidas": len(self.partidas),
            "composicion": composicion,
        }

    def relacion_insumos(self) -> list:
        """Consolida TODOS los insumos de TODAS las partidas (cantidad
        por unidad × metrado de cada partida) en una sola lista de
        compra -- un insumo usado en varias partidas aparece UNA sola
        vez con la cantidad total sumada. Ordenada por tipo y
        descripción (mismo orden que el reporte "Relación de Insumos"
        de S10)."""
        acumulado = {}
        for p in self.partidas:
            if p.apu is None:
                continue
            for item in p.apu.items:
                cantidad_total = item.cantidad_por_unidad() * p.metrado
                costo_total = cantidad_total * item.insumo.precio_unitario
                clave = item.insumo.codigo
                if clave not in acumulado:
                    acumulado[clave] = {"insumo": item.insumo, "cantidad": 0.0, "costo": 0.0}
                acumulado[clave]["cantidad"] += cantidad_total
                acumulado[clave]["costo"] += costo_total
        filas = [{
            "codigo": datos["insumo"].codigo, "descripcion": datos["insumo"].descripcion,
            "unidad": datos["insumo"].unidad, "tipo": datos["insumo"].tipo,
            "precio_unitario": datos["insumo"].precio_unitario,
            "indice_inei": datos["insumo"].indice_inei,
            "cantidad_total": round(datos["cantidad"], 4),
            "costo_total": round(datos["costo"], 2),
        } for datos in acumulado.values()]
        filas.sort(key=lambda f: (TipoInsumo.TODOS.index(f["tipo"]), f["descripcion"]))
        return filas


# ======================================================================
# Cadena de INVERSIÓN PÚBLICA peruana (Invierte.pe), por encima del
# Valor Referencial de la obra (Presupuesto.resumen()["total"]) --
# función independiente porque estos conceptos (supervisión,
# expediente técnico, gestión del proyecto, control concurrente) NO
# forman parte del precio que licita el contratista, sino del costo
# total de la inversión que presupuesta la entidad pública.
# ======================================================================
def resumen_inversion_publica(valor_referencial: float, supervision_liquidacion_pct: float = 3.0,
                               expediente_tecnico: float = 0.0, gestion_proyecto: dict = None,
                               control_concurrente_pct: float = 0.5) -> dict:
    """Cadena de costos de una obra pública peruana por encima del
    Valor Referencial (el propio Presupuesto.resumen()["total"]):
        Valor Referencial
        -> + Supervisión y Liquidación (% del Valor Referencial)
        -> + Expediente Técnico (monto directo, si se cotiza aparte)
        -> + Gestión del Proyecto (suma de partidas propias del
             usuario -- p.ej. PAC, Gestión de Riesgos, JPRD, PMA,
             Gastos Administrativos)
        = Costo Total de la Inversión
        -> + Control Concurrente de Obra (% del Costo Total de la
             Inversión, Contraloría General de la República)
        = Presupuesto Total
    `control_concurrente_pct` NO tiene un valor único fijado por norma
    para todo tipo de obra/entidad -- verifique el % vigente para su
    caso contra la Contraloría antes de un expediente definitivo; el
    valor por defecto (0.5%) es solo el observado en el proyecto de
    referencia usado para verificar esta función, no una tasa oficial
    universal. NO reemplaza el criterio de la Oficina de Programación
    Multianual de Inversiones (OPMI) ni la normativa vigente de
    Invierte.pe."""
    if valor_referencial < 0:
        raise PresupuestoError("valor_referencial negativo")
    supervision = valor_referencial * supervision_liquidacion_pct / 100.0
    gestion_proyecto = gestion_proyecto or {}
    total_gestion = sum(gestion_proyecto.values())
    costo_total_inversion = valor_referencial + supervision + expediente_tecnico + total_gestion
    control_concurrente = costo_total_inversion * control_concurrente_pct / 100.0
    presupuesto_total = costo_total_inversion + control_concurrente
    return {
        "valor_referencial": round(valor_referencial, 2),
        "supervision_liquidacion_pct": supervision_liquidacion_pct,
        "supervision_liquidacion": round(supervision, 2),
        "expediente_tecnico": round(expediente_tecnico, 2),
        "gestion_proyecto": {k: round(v, 2) for k, v in gestion_proyecto.items()},
        "gestion_proyecto_total": round(total_gestion, 2),
        "costo_total_inversion": round(costo_total_inversion, 2),
        "control_concurrente_pct": control_concurrente_pct,
        "control_concurrente": round(control_concurrente, 2),
        "presupuesto_total": round(presupuesto_total, 2),
    }
