# -*- coding: utf-8 -*-
"""
core/formula_polinomica.py

Fórmula Polinómica de reajuste de precios para contratos de obra
pública en el Perú (D.S. N° 011-79-VC y sus modificatorias) -- se
apoya en la Relación de Insumos del Módulo Presupuesto, APU e Insumos
(core/presupuesto.py).

CONCEPTO: el costo de una obra varía entre el mes del presupuesto
(mes base, subíndice "o") y el mes real de cada valorización de obra
(subíndice "r"), por variación de precios de mano de obra, materiales,
equipo, dólar, etc. La Fórmula Polinómica reajusta el monto de cada
valorización multiplicándolo por un coeficiente de reajuste K:

    K = a1*(I1r/I1o) + a2*(I2r/I2o) + ... + an*(Inr/Ino)

donde cada término (monomio) agrupa una o más categorías de costo
(mano de obra, acero, cemento, dólar, equipo importado, índice
general, etc.), con un coeficiente `a` (peso del monomio, Σa = 1.000,
máximo 8 monomios -- límite normativo), e Ir/Io es la razón entre el
Índice Unificado de Precios de la Construcción del mes de la
valorización (r) y el del mes base (o), tal como los publica
MENSUALMENTE el INEI en su "Boletín de Índices Unificados de Precios
de la Construcción".

PROCESO (2 fases, igual que hace S10 -- ver core/presupuesto.py::
Presupuesto.relacion_insumos()):
  1. PARTICIPACIÓN POR ÍNDICE (agrupamiento preliminar): a partir de
     la Relación de Insumos, se calcula qué % del costo directo
     corresponde a CADA índice unificado (cada Insumo debe tener su
     `indice_inei` asignado -- ver core/presupuesto.py::Insumo).
  2. AGRUPAMIENTO FINAL: los índices de MENOR participación se
     combinan ("agrupan") dentro de índices más afines/mayores hasta
     quedar en 8 monomios o menos, cada uno con coeficiente redondeado
     a 3 decimales (Σ = 1.000). ESTE PASO requiere criterio técnico-
     económico del proyectista (qué índice pequeño se agrupa con cuál
     mayor, según afinidad de mercado) -- NO se automatiza aquí; se
     arma explícitamente con FormulaPolinomica/Monomio/
     ComponenteMonomio, que sí verifican que la estructura resultante
     sea válida (Σfactor=1.000, Σpesos por monomio=100%, ≤8 monomios).

ÍNDICES UNIFICADOS: el catálogo INDICES_INEI de este módulo son
códigos y descripciones OFICIALES publicados por el INEI (estadística
pública del Estado peruano, no una tabla de una editorial privada) --
se cargaron los códigos verificados contra un presupuesto de obra vial
real (ver metadata.txt); el catálogo es AMPLIABLE, no pretende ser la
lista completa que publica el INEI.

REAJUSTE: una vez con los valores reales Ir/Io del boletín INEI del
mes correspondiente, el monto reajustado de una valorización es
    monto_reajustado = valorización_bruta × K
(D.S. 011-79-VC, art. 2).

Este módulo NO reemplaza el criterio del especialista en costos y
presupuestos ni la verificación contra el Boletín de Índices
Unificados de Precios de la Construcción del INEI vigente para cada
mes de valorización.
"""

# Índices Unificados de Precios de la Construcción (INEI) -- códigos y
# descripciones verificados contra un presupuesto de obra vial real
# (proyecto de referencia, ver metadata.txt); catálogo AMPLIABLE, NO
# es la lista completa que publica el INEI (que tiene más categorías).
INDICES_INEI = {
    1: "Aceite",
    2: "Acero de construcción liso",
    3: "Acero de construcción corrugado",
    4: "Agregado fino",
    5: "Agregado grueso",
    9: "Alcantarilla metálica",
    12: "Artefacto de alumbrado interior",
    13: "Asfalto",
    19: "Cable NYY y NKY",
    21: "Cemento Portland Tipo I",
    26: "Cerrajería nacional",
    27: "Detonante",
    28: "Dinamita",
    30: "Dólar (general ponderado)",
    32: "Flete terrestre",
    34: "Gasolina",
    37: "Herramienta manual",
    38: "Hormigón",
    39: "Índice general de precios al consumidor",
    43: "Madera nacional para encof. y carpint.",
    44: "Madera terciada para carpintería",
    45: "Madera terciada para encofrado",
    47: "Mano de obra inc. leyes sociales",
    48: "Maquinaria y equipo nacional",
    49: "Maquinaria y equipo importado",
    51: "Perfil de acero liviano",
    53: "Petróleo diessel",
    54: "Pintura látex",
    56: "Plancha de acero LAC",
    60: "Plancha de poliuretano",
    61: "Plancha galvanizada",
    71: "Tubería de fierro fundido",
    72: "Tubería de PVC para agua",
}

MAX_MONOMIOS = 8  # límite normativo (D.S. 011-79-VC y modificatorias)


class FormulaPolinomicaError(Exception):
    """Datos insuficientes o inconsistentes para calcular la
    participación, el agrupamiento o el coeficiente K -- el mensaje
    explica exactamente qué falta o qué valor es inválido."""


# ======================================================================
# Participación por índice (fase 1 -- agrupamiento preliminar)
# ======================================================================
def participacion_por_indice(relacion_insumos: list) -> dict:
    """A partir de la Relación de Insumos (ver
    core/presupuesto.py::Presupuesto.relacion_insumos(), cuyas filas ya
    traen `indice_inei` desde el Insumo), calcula el % de participación
    de CADA índice sobre el costo total de los insumos QUE TIENEN
    índice asignado -- fase 1 (agrupamiento preliminar). Insumos sin
    `indice_inei` se ignoran (deben mapearse todos antes de armar la
    fórmula final). Devuelve {índice: pct}, sumando 100% entre sí."""
    costos_por_indice = {}
    costo_total = 0.0
    for fila in relacion_insumos:
        indice = fila.get("indice_inei")
        if indice is None:
            continue
        costos_por_indice[indice] = costos_por_indice.get(indice, 0.0) + fila["costo_total"]
        costo_total += fila["costo_total"]
    if costo_total <= 0:
        raise FormulaPolinomicaError(
            "ningún insumo de la relación de insumos tiene un índice INEI asignado todavía "
            "(Insumo(..., indice_inei=...))")
    return {indice: round(100.0 * costo / costo_total, 3) for indice, costo in costos_por_indice.items()}


# ======================================================================
# Fórmula final (fase 2 -- agrupamiento en ≤8 monomios)
# ======================================================================
class ComponenteMonomio:
    """Un índice INEI dentro de un monomio, con su peso (%) DENTRO del
    monomio -- la suma de pesos de los componentes de un mismo monomio
    debe ser 100 (p.ej. un monomio "M" con Cemento 28% + Agregado
    grueso 68% + Madera 4%)."""
    __slots__ = ("indice", "peso_pct")

    def __init__(self, indice: int, peso_pct: float):
        if indice not in INDICES_INEI:
            raise FormulaPolinomicaError(
                f"índice INEI «{indice}» no está en el catálogo (INDICES_INEI) -- agréguelo si "
                f"es un índice oficial válido que falta en este catálogo ampliable.")
        self.indice = indice
        self.peso_pct = peso_pct


class Monomio:
    """Un término de la fórmula polinómica: símbolo (J, M, A, D, E,
    GG...), coeficiente `factor` (peso del monomio en K -- Σ de todos
    los factores de la fórmula debe ser 1.000) y sus componentes (uno
    o más índices INEI, con pesos que suman 100%)."""

    def __init__(self, simbolo: str, factor: float, componentes: list):
        if not componentes:
            raise FormulaPolinomicaError(f"el monomio «{simbolo}» no tiene ningún componente")
        total_pct = sum(c.peso_pct for c in componentes)
        if abs(total_pct - 100.0) > 0.5:
            raise FormulaPolinomicaError(
                f"los pesos de los componentes del monomio «{simbolo}» suman {total_pct:.3f}%, "
                f"deben sumar 100%")
        self.simbolo = simbolo
        self.factor = factor
        self.componentes = componentes

    def valor(self, razones_ir_io: dict) -> float:
        """Contribución de este monomio a K -- `razones_ir_io`:
        {índice INEI: Ir/Io}."""
        acumulado = 0.0
        for c in self.componentes:
            if c.indice not in razones_ir_io:
                raise FormulaPolinomicaError(
                    f"falta la razón Ir/Io del índice {c.indice} ({INDICES_INEI[c.indice]}) "
                    f"para el monomio «{self.simbolo}»")
            acumulado += (c.peso_pct / 100.0) * razones_ir_io[c.indice]
        return self.factor * acumulado


class FormulaPolinomica:
    """La fórmula polinómica completa de un presupuesto -- lista de
    Monomio (máximo 8, límite normativo), con Σfactor = 1.000."""

    def __init__(self, monomios: list):
        if not monomios:
            raise FormulaPolinomicaError("la fórmula no tiene ningún monomio")
        if len(monomios) > MAX_MONOMIOS:
            raise FormulaPolinomicaError(
                f"la fórmula tiene {len(monomios)} monomios -- el máximo normativo es "
                f"{MAX_MONOMIOS} (D.S. 011-79-VC y modificatorias); agrupe algún índice más.")
        total_factor = sum(m.factor for m in monomios)
        if abs(total_factor - 1.0) > 0.005:
            raise FormulaPolinomicaError(
                f"los coeficientes de los monomios suman {total_factor:.4f}, deben sumar 1.000")
        self.monomios = monomios

    def calcular_k(self, razones_ir_io: dict) -> float:
        """Coeficiente de reajuste K -- `razones_ir_io`: {índice INEI:
        Ir/Io}, la razón entre el índice del mes de la valorización (r)
        y el índice del mes base del presupuesto (o), tal como publica
        el INEI en su Boletín de Índices Unificados de Precios de la
        Construcción. Con todas las razones en 1.0 (mismo mes base y de
        valorización), K = 1.0 exactamente."""
        return sum(m.valor(razones_ir_io) for m in self.monomios)

    def formula_texto(self) -> str:
        """Representación 'K = a1*(Jr/Jo) + ...' -- mismo formato que
        muestra S10 en su reporte de Fórmula Polinómica."""
        return "K = " + " + ".join(
            f"{m.factor:.3f}*({m.simbolo}r/{m.simbolo}o)" for m in self.monomios)

    def resumen(self) -> list:
        """Lista de dicts (uno por monomio) lista para una tabla de
        interfaz -- símbolo, factor, y sus componentes (índice,
        descripción, peso %)."""
        return [{
            "simbolo": m.simbolo, "factor": m.factor,
            "componentes": [{"indice": c.indice, "descripcion": INDICES_INEI[c.indice],
                              "peso_pct": c.peso_pct} for c in m.componentes],
        } for m in self.monomios]


def reajustar_valorizacion(valorizacion_bruta: float, k: float) -> float:
    """Monto reajustado de una valorización de obra -- D.S. 011-79-VC,
    art. 2: monto_reajustado = valorización_bruta × K."""
    return round(valorizacion_bruta * k, 2)
