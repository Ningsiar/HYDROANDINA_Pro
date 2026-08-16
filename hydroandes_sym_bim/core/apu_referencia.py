# -*- coding: utf-8 -*-
"""
core/apu_referencia.py

Ejemplo de referencia REAL para el Módulo Presupuesto, APU e Insumos --
resources/apu_referencia_cajamarca_2025.json, extraído y AUTO-VALIDADO
del presupuesto/APU/relación de insumos reales de un proyecto vial que
el usuario aportó ("MEJORAMIENTO DEL SERVICIO DE TRANSITABILIDAD VIAL
INTERURBANA... CARRETERA VECINAL CA 1066", Bambamarca, Hualgayoc,
Cajamarca -- presupuesto con fecha 01/12/2025).

IMPORTANTE -- qué es y qué NO es este archivo:
  - SÍ es: el presupuesto/APU REAL de un proyecto específico, con sus
    precios y cantidades tal como se calcularon para esa obra, esa
    ubicación y esa fecha.
  - NO es: una tarifa oficial de CAPECO/Revista Costos ni una "base de
    rendimientos" universal -- este plugin no reproduce esas
    publicaciones comerciales (ver core/presupuesto.py). Los precios y
    rendimientos aquí son los de UN proyecto real, útiles como ejemplo/
    punto de partida, no como referencia vigente para cualquier otro
    proyecto/ubicación/fecha sin verificar.

PROCESO DE EXTRACCIÓN (para que quede documentado cómo se generó, no
solo el resultado): se extrajo el texto de 3 PDF reales (Presupuesto,
Relación de Insumos, Análisis de Precios Unitarios de 260 páginas) con
PyPDF2, se parsearon con expresiones regulares, y CADA partida del APU
se reconstruyó sumando (cantidad × precio_insumo) de sus propios
insumos y se comparó contra el precio unitario que aparece en el
Presupuesto (una fuente independiente del mismo proyecto) -- SOLO se
conservaron las partidas cuyo precio unitario reconstruido coincide
con el del Presupuesto real dentro de 1% de error. De 638 partidas del
presupuesto, 626 pasaron esta validación cruzada (98%); las que no
(datos incompletos en la extracción de texto del PDF) se descartaron
en vez de incluirse con un valor no verificado.

ESTRUCTURA DEL JSON:
  {"meta": {...}, "insumos": {codigo: {descripcion, unidad, precio, tipo}},
   "partidas": {codigo: {descripcion, items: [{codigo_insumo, cantidad,
   seccion}], precio_unitario_esperado}}}
`tipo` ya viene en español igual a TipoInsumo.TODOS de core/presupuesto.py
(incluye "Subpartida" para las ~20 subpartidas/insumos compuestos que
aparecían como recurso dentro de otras partidas, p.ej. un concreto
premezclado con su propio costo ya calculado).
"""
import json
import os

from . import presupuesto as pp

_RUTA_JSON = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                           "resources", "apu_referencia_cajamarca_2025.json")

_cache = None


class ReferenciaNoDisponibleError(Exception):
    """El archivo de referencia no está disponible (no se instaló con
    el plugin, o está corrupto) -- el mensaje explica qué falló."""


def _cargar_json() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    if not os.path.isfile(_RUTA_JSON):
        raise ReferenciaNoDisponibleError(
            f"no se encontró el archivo de referencia en «{_RUTA_JSON}» -- reinstale el plugin.")
    try:
        with open(_RUTA_JSON, encoding="utf-8") as f:
            _cache = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise ReferenciaNoDisponibleError(f"no se pudo leer el archivo de referencia -- {e}") from e
    return _cache


def obtener_metadatos() -> dict:
    """{"fuente": ..., "n_insumos": ..., "n_partidas_verificadas": ..., ...}"""
    return dict(_cargar_json()["meta"])


def construir_insumos() -> dict:
    """{código: presupuesto.Insumo} -- toda la librería de referencia
    (mano de obra + materiales + equipos + herramienta manual +
    subcontratos + subpartidas)."""
    datos = _cargar_json()
    insumos = {}
    for codigo, info in datos["insumos"].items():
        insumos[codigo] = pp.Insumo(codigo, info["descripcion"], info["unidad"], info["tipo"],
                                     info["precio"])
    return insumos


def construir_partidas(insumos: dict = None, metrado_por_defecto: float = 1.0) -> dict:
    """{código: presupuesto.Partida} -- las 626 partidas verificadas,
    cada una con su Apu ya armado a partir de los insumos de
    construir_insumos() (o los que se le pasen). `metrado_por_defecto`
    es solo un valor de partida (1.0 -- unidad de la partida) hasta que
    el usuario lo ajuste o lo autocompleta desde otra fuente (p.ej. el
    Módulo BIM)."""
    datos = _cargar_json()
    if insumos is None:
        insumos = construir_insumos()
    partidas = {}
    for codigo, info in datos["partidas"].items():
        apu = pp.Apu()
        for item in info["items"]:
            insumo = insumos.get(item["codigo_insumo"])
            if insumo is None:
                continue  # insumo no encontrado -- se omite ese renglón, no toda la partida
            apu.agregar(pp.ItemApu(insumo, cantidad=item["cantidad"]))
        if not apu.items:
            continue
        partidas[codigo] = pp.Partida(codigo, info["descripcion"], info.get("unidad", "und"),
                                       metrado_por_defecto, apu=apu,
                                       grupo="Ejemplo de referencia -- Cajamarca dic-2025")
    return partidas
