# -*- coding: utf-8 -*-
"""
core/map_styling.py

Simbología reutilizable para la Pestaña "Mapas Temáticos" -- helpers
sobre capas ráster y vectoriales YA generadas por otras pestañas del
plugin (CN, HSG, morfometría, SWE2D, etc.), para no repetir la misma
receta de QgsSingleBandPseudoColorRenderer/QgsGraduatedSymbolRenderer
en cada mapa temático. Depende de qgis.core -- solo se importa dentro
de QGIS (ui/plugin_dialog.py), nunca desde un script standalone.

CONVENCIÓN DE RAMPAS: se usan las rampas con nombre YA registradas en
QgsStyle().defaultStyle() (las mismas que aparecen en el selector de
color ramp del panel de Simbología de QGIS -- "RdYlGn", "Spectral",
"Blues", etc., todas parte de la instalación estándar de QGIS/Qt, sin
depender de un archivo de estilo externo que pudiera faltar).
"""
import math
from typing import Dict, Optional

from qgis.core import (
    QgsRasterShader, QgsColorRampShader, QgsSingleBandPseudoColorRenderer,
    QgsStyle, QgsGraduatedSymbolRenderer, QgsCategorizedSymbolRenderer,
    QgsRendererCategory, QgsSymbol, QgsClassificationEqualInterval,
    QgsProject, QgsLayerTreeGroup, QgsLayerTree,
)
from qgis.PyQt.QtGui import QColor


class MapStylingError(Exception):
    pass


# ======================================================================
# Grupo de capas -- organiza la Pestaña "Mapas Temáticos" en el panel
# de capas de QGIS, en vez de amontonar todo en la raíz.
# ======================================================================
def obtener_o_crear_grupo(nombre_grupo: str, subgrupo: Optional[str] = None) -> QgsLayerTreeGroup:
    """Devuelve (creándolo si no existe) el grupo `nombre_grupo` en la
    raíz del árbol de capas, y opcionalmente un `subgrupo` dentro de
    él (p.ej. grupo="Mapas Temáticos", subgrupo="Morfometría")."""
    raiz: QgsLayerTree = QgsProject.instance().layerTreeRoot()
    grupo = raiz.findGroup(nombre_grupo)
    if grupo is None:
        grupo = raiz.insertGroup(0, nombre_grupo)
    if subgrupo:
        sub = grupo.findGroup(subgrupo)
        if sub is None:
            sub = grupo.insertGroup(0, subgrupo)
        return sub
    return grupo


def agregar_capa_a_grupo(capa, subgrupo: Optional[str] = None,
                          nombre_grupo_raiz: str = "Mapas Temáticos"):
    """Registra `capa` en el proyecto SIN agregarla a la raíz del árbol
    (addToLegend=False) y la inserta dentro del grupo/subgrupo
    indicado -- evita que las capas de Mapas Temáticos se mezclen con
    las que ya arma cada pestaña individual."""
    QgsProject.instance().addMapLayer(capa, False)
    grupo = obtener_o_crear_grupo(nombre_grupo_raiz, subgrupo)
    grupo.insertLayer(0, capa)
    return capa


# ======================================================================
# Ráster -- pseudocolor de una banda, con rampa continua o clasificada
# ======================================================================
def estilizar_raster_pseudocolor(capa_raster, rampa: str = "RdYlGn", n_clases: int = 8,
                                  invertir: bool = False, valor_min: Optional[float] = None,
                                  valor_max: Optional[float] = None,
                                  modo: str = "EqualInterval") -> None:
    """Aplica un QgsSingleBandPseudoColorRenderer a `capa_raster`
    (banda 1) con la rampa de color con nombre `rampa` (debe existir en
    QgsStyle().defaultStyle(), ver docstring del módulo).
    `valor_min`/`valor_max`: si no se indican, se toman del propio
    ráster (estadísticas de banda). `modo`: "EqualInterval" o
    "Continuous" (interpolación continua entre min y max, sin
    clasificar en `n_clases` escalones)."""
    proveedor = capa_raster.dataProvider()
    banda = 1
    if valor_min is None or valor_max is None:
        stats = proveedor.bandStatistics(banda)
        if valor_min is None:
            valor_min = stats.minimumValue
        if valor_max is None:
            valor_max = stats.maximumValue
    if valor_min is None or valor_max is None or math.isnan(valor_min) or math.isnan(valor_max):
        raise MapStylingError(
            "no se pudo calcular el rango de valores del ráster (estadísticas de banda no "
            "disponibles) -- revise que no esté vacío/todo NoData."
        )
    if valor_max < valor_min:
        raise MapStylingError(
            f"el ráster no tiene un rango de valores válido para estilizar (min={valor_min} > "
            f"max={valor_max}) -- revise que no esté vacío/todo NoData.")
    if valor_max == valor_min:
        # Valor uniforme en todo el ráster -- caso LEGÍTIMO (p.ej. una
        # superficie perfectamente plana produce un hillshade uniforme),
        # no un ráster vacío. Se renderiza con un único color en vez de
        # fallar, ensanchando levemente el rango para que el shader no
        # reciba un intervalo de ancho cero.
        valor_max = valor_min + max(abs(valor_min) * 1e-6, 1e-6)

    estilo_qgis = QgsStyle().defaultStyle()
    color_ramp = estilo_qgis.colorRamp(rampa)
    if color_ramp is None:
        raise MapStylingError(
            f"la rampa de color «{rampa}» no existe en QgsStyle().defaultStyle() -- use una rampa "
            f"estándar de QGIS (p.ej. 'RdYlGn', 'Spectral', 'Blues', 'YlOrRd')."
        )
    if invertir:
        color_ramp.invert()

    shader = QgsRasterShader()
    color_ramp_shader = QgsColorRampShader(valor_min, valor_max, color_ramp)
    if modo == "Continuous":
        color_ramp_shader.setColorRampType(QgsColorRampShader.Interpolated)
        paso = (valor_max - valor_min) / max(n_clases - 1, 1)
        items = []
        for i in range(n_clases):
            valor = valor_min + i * paso
            color = color_ramp.color(i / max(n_clases - 1, 1))
            items.append(QgsColorRampShader.ColorRampItem(valor, color, f"{valor:.2f}"))
        color_ramp_shader.setColorRampItemList(items)
    else:
        color_ramp_shader.setColorRampType(QgsColorRampShader.Discrete)
        paso = (valor_max - valor_min) / n_clases
        items = []
        for i in range(n_clases):
            limite_sup = valor_min + (i + 1) * paso
            color = color_ramp.color(i / max(n_clases - 1, 1))
            etiqueta = f"{valor_min + i * paso:.2f} - {limite_sup:.2f}"
            items.append(QgsColorRampShader.ColorRampItem(limite_sup, color, etiqueta))
        color_ramp_shader.setColorRampItemList(items)

    shader.setRasterShaderFunction(color_ramp_shader)
    renderer = QgsSingleBandPseudoColorRenderer(proveedor, banda, shader)
    capa_raster.setRenderer(renderer)
    capa_raster.triggerRepaint()


# ======================================================================
# Vector -- graduado (campo numérico continuo) y categorizado (campo
# discreto: clases HSG, tipo de estructura, código LULC, etc.)
# ======================================================================
def estilizar_vector_graduado(capa_vector, campo: str, rampa: str = "RdYlGn", n_clases: int = 5,
                               invertir: bool = False, tipo_simbolo: str = "fill") -> None:
    """Aplica un QgsGraduatedSymbolRenderer sobre `campo` (numérico),
    clasificado por intervalos iguales (EqualInterval -- el método más
    simple y predecible para un mapa temático de ingeniería, sin
    depender de la distribución estadística de los datos). `tipo_simbolo`:
    "fill" (polígonos), "line" o "marker" (puntos)."""
    idx_campo = capa_vector.fields().indexFromName(campo)
    if idx_campo < 0:
        raise MapStylingError(f"el campo «{campo}» no existe en la capa «{capa_vector.name()}».")

    estilo_qgis = QgsStyle().defaultStyle()
    color_ramp = estilo_qgis.colorRamp(rampa)
    if color_ramp is None:
        raise MapStylingError(f"la rampa de color «{rampa}» no existe en QgsStyle().defaultStyle().")
    if invertir:
        color_ramp.invert()

    renderer = QgsGraduatedSymbolRenderer(campo)
    renderer.setClassificationMethod(QgsClassificationEqualInterval())
    renderer.updateClasses(capa_vector, n_clases)
    renderer.updateColorRamp(color_ramp)
    capa_vector.setRenderer(renderer)
    capa_vector.triggerRepaint()


def estilizar_vector_categorizado(capa_vector, campo: str,
                                   mapa_colores: Optional[Dict[str, str]] = None) -> None:
    """Aplica un QgsCategorizedSymbolRenderer sobre `campo` (texto o
    código discreto -- p.ej. HSG "A"/"B"/"C"/"D", orden de Strahler,
    tipo de estructura). `mapa_colores`: {valor_categoria: "#RRGGBB"}
    opcional -- si no se indica para alguna categoría presente en la
    capa, se le asigna un color de la rampa "Set1" (categórica,
    colores bien diferenciados) automáticamente."""
    idx_campo = capa_vector.fields().indexFromName(campo)
    if idx_campo < 0:
        raise MapStylingError(f"el campo «{campo}» no existe en la capa «{capa_vector.name()}».")
    mapa_colores = mapa_colores or {}

    valores = sorted({str(f[campo]) for f in capa_vector.getFeatures() if f[campo] is not None})
    if not valores:
        raise MapStylingError(f"la capa «{capa_vector.name()}» no tiene valores no nulos en «{campo}».")

    estilo_qgis = QgsStyle().defaultStyle()
    rampa_respaldo = estilo_qgis.colorRamp("Set1")
    categorias = []
    for i, valor in enumerate(valores):
        color_hex = mapa_colores.get(valor)
        color = QColor(color_hex) if color_hex else (
            rampa_respaldo.color(i / max(len(valores) - 1, 1)) if rampa_respaldo else QColor("#999999"))
        simbolo = QgsSymbol.defaultSymbol(capa_vector.geometryType())
        simbolo.setColor(color)
        categorias.append(QgsRendererCategory(valor, simbolo, valor))

    renderer = QgsCategorizedSymbolRenderer(campo, categorias)
    capa_vector.setRenderer(renderer)
    capa_vector.triggerRepaint()


# Paletas de referencia para categorías hidrológicas estándar del
# plugin (HSG y Grupo Hidrológico dominante ya usan estas letras en
# el resto de la interfaz) -- colores convencionales: A=verde
# (alta infiltración) a D=rojo (muy lenta), el mismo sentido que un
# semáforo de "capacidad de infiltración".
COLORES_HSG: Dict[str, str] = {"A": "#1a9850", "B": "#91cf60", "C": "#fc8d59", "D": "#d73027"}
