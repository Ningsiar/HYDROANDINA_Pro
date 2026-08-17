# -*- coding: utf-8 -*-
"""
core/print_layout.py

Generador genérico de láminas de impresión (QgsPrintLayout) para la
Pestaña "Mapas Temáticos" -- mapa + leyenda + norte + escala + título,
exportable a PDF/PNG. Un único generador reutilizado por todos los
mapas temáticos (morfometría, CN, precipitación, peligro hidráulico,
etc.), en vez de armar la lámina a mano en cada uno.

Depende de qgis.core/qgis.PyQt -- solo se importa dentro de QGIS.

NORTE: se usa el SVG de flecha de norte que trae QGIS incorporado en
sus propios recursos Qt (":/images/north_arrows/layout_default_north_arrow.svg"),
sin depender de un archivo externo que pudiera faltar.
"""
from typing import List, Optional, Sequence

from qgis.core import (
    QgsProject, QgsPrintLayout, QgsLayoutItemMap, QgsLayoutItemLegend,
    QgsLayoutItemScaleBar, QgsLayoutItemPicture, QgsLayoutItemLabel,
    QgsLayoutPoint, QgsLayoutSize, QgsUnitTypes, QgsLayoutItemPage,
    QgsLayoutExporter, QgsRectangle, QgsTextFormat,
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QFont

_RUTA_FLECHA_NORTE = ":/images/north_arrows/layout_default_north_arrow.svg"


class PrintLayoutError(Exception):
    pass


def crear_layout_tematico(nombre: str, capas: Sequence, titulo: str,
                           extent: Optional[QgsRectangle] = None,
                           tamano_papel: str = "A4",
                           orientacion: str = "landscape",
                           subtitulo: str = "") -> QgsPrintLayout:
    """Arma una lámina de impresión completa (mapa + leyenda + norte +
    escala + título) para `capas` (lista de QgsMapLayer YA estilizadas
    -- ver core/map_styling.py) y la registra en el gestor de layouts
    del proyecto (reemplaza uno anterior con el mismo `nombre`, para
    poder regenerar sin acumular duplicados). `extent`: si no se
    indica, se usa la extensión combinada de todas las `capas`.
    `orientacion`: "landscape" u "portrait"."""
    if not capas:
        raise PrintLayoutError("no se indicó ninguna capa para el layout de impresión.")

    proyecto = QgsProject.instance()
    gestor = proyecto.layoutManager()
    existente = gestor.layoutByName(nombre)
    if existente is not None:
        gestor.removeLayout(existente)

    layout = QgsPrintLayout(proyecto)
    layout.initializeDefaults()
    layout.setName(nombre)

    pagina = layout.pageCollection().pages()[0]
    orientacion_enum = (QgsLayoutItemPage.Landscape if orientacion == "landscape"
                         else QgsLayoutItemPage.Portrait)
    pagina.setPageSize(tamano_papel, orientacion_enum)
    ancho_pagina = pagina.pageSize().width()
    alto_pagina = pagina.pageSize().height()

    # --- título (y subtítulo opcional) ---
    label_titulo = QgsLayoutItemLabel(layout)
    label_titulo.setText(titulo)
    formato_titulo = QgsTextFormat()
    formato_titulo.setFont(QFont("Arial", 16, QFont.Bold))
    formato_titulo.setSize(16)
    label_titulo.setTextFormat(formato_titulo)
    label_titulo.attemptMove(QgsLayoutPoint(8, 5, QgsUnitTypes.LayoutMillimeters))
    label_titulo.attemptResize(QgsLayoutSize(ancho_pagina - 16, 12, QgsUnitTypes.LayoutMillimeters))
    layout.addLayoutItem(label_titulo)

    y_mapa = 18
    if subtitulo:
        label_sub = QgsLayoutItemLabel(layout)
        label_sub.setText(subtitulo)
        label_sub.attemptMove(QgsLayoutPoint(8, 17, QgsUnitTypes.LayoutMillimeters))
        label_sub.attemptResize(QgsLayoutSize(ancho_pagina - 16, 8, QgsUnitTypes.LayoutMillimeters))
        layout.addLayoutItem(label_sub)
        y_mapa = 26

    # --- mapa principal ---
    alto_mapa = alto_pagina - y_mapa - 18  # deja margen inferior para escala/pie
    ancho_mapa = ancho_pagina - 16 - 55    # deja franja derecha de 55mm para leyenda
    item_mapa = QgsLayoutItemMap(layout)
    item_mapa.attemptMove(QgsLayoutPoint(8, y_mapa, QgsUnitTypes.LayoutMillimeters))
    item_mapa.attemptResize(QgsLayoutSize(ancho_mapa, alto_mapa, QgsUnitTypes.LayoutMillimeters))
    item_mapa.setLayers(list(capas))
    extent_final = extent
    if extent_final is None:
        extent_final = QgsRectangle(capas[0].extent())
        for capa in capas[1:]:
            extent_final.combineExtentWith(capa.extent())
    # margen del 5% alrededor del extent, para que los bordes no queden pegados
    extent_final = QgsRectangle(extent_final)
    extent_final.grow(max(extent_final.width(), extent_final.height()) * 0.05 or 1.0)
    item_mapa.setExtent(extent_final)
    item_mapa.setBackgroundColor(Qt.white)
    layout.addLayoutItem(item_mapa)

    x_derecha = 8 + ancho_mapa + 6

    # --- leyenda (vinculada al mapa -- solo muestra lo que el mapa renderiza) ---
    leyenda = QgsLayoutItemLegend(layout)
    leyenda.setTitle("Leyenda")
    leyenda.setLinkedMap(item_mapa)
    leyenda.attemptMove(QgsLayoutPoint(x_derecha, y_mapa, QgsUnitTypes.LayoutMillimeters))
    leyenda.attemptResize(QgsLayoutSize(48, alto_mapa * 0.7, QgsUnitTypes.LayoutMillimeters))
    layout.addLayoutItem(leyenda)

    # --- flecha de norte ---
    flecha_norte = QgsLayoutItemPicture(layout)
    flecha_norte.setPicturePath(_RUTA_FLECHA_NORTE)
    flecha_norte.attemptMove(
        QgsLayoutPoint(x_derecha + 15, y_mapa + alto_mapa * 0.72, QgsUnitTypes.LayoutMillimeters))
    flecha_norte.attemptResize(QgsLayoutSize(16, 20, QgsUnitTypes.LayoutMillimeters))
    layout.addLayoutItem(flecha_norte)

    # --- barra de escala (vinculada al mapa) ---
    barra_escala = QgsLayoutItemScaleBar(layout)
    barra_escala.setLinkedMap(item_mapa)
    barra_escala.setStyle("Single Box")
    barra_escala.setUnits(QgsUnitTypes.DistanceMeters)
    barra_escala.setUnitLabel("m")
    barra_escala.setNumberOfSegments(4)
    barra_escala.setNumberOfSegmentsLeft(0)
    barra_escala.update()
    barra_escala.attemptMove(QgsLayoutPoint(8, alto_pagina - 12, QgsUnitTypes.LayoutMillimeters))
    barra_escala.attemptResize(QgsLayoutSize(ancho_mapa, 8, QgsUnitTypes.LayoutMillimeters))
    layout.addLayoutItem(barra_escala)

    gestor.addLayout(layout)
    return layout


def exportar_layout_pdf(layout: QgsPrintLayout, ruta: str) -> str:
    """Exporta `layout` a PDF (vectorial, ideal para el expediente
    técnico). Devuelve la ruta escrita, o lanza PrintLayoutError con el
    código de resultado si la exportación falló."""
    exportador = QgsLayoutExporter(layout)
    resultado = exportador.exportToPdf(ruta, QgsLayoutExporter.PdfExportSettings())
    if resultado != QgsLayoutExporter.Success:
        raise PrintLayoutError(f"la exportación a PDF falló (código {resultado}) -- ruta: {ruta}")
    return ruta


def exportar_layout_png(layout: QgsPrintLayout, ruta: str, dpi: int = 300) -> str:
    """Exporta `layout` a PNG (raster, para incrustar en un informe
    Word/PowerPoint) a `dpi` puntos por pulgada."""
    exportador = QgsLayoutExporter(layout)
    ajustes = QgsLayoutExporter.ImageExportSettings()
    ajustes.dpi = dpi
    resultado = exportador.exportToImage(ruta, ajustes)
    if resultado != QgsLayoutExporter.Success:
        raise PrintLayoutError(f"la exportación a PNG falló (código {resultado}) -- ruta: {ruta}")
    return ruta


def listar_layouts_tematicos() -> List[str]:
    """Nombres de todos los layouts ya generados por la Pestaña "Mapas
    Temáticos" registrados en el proyecto actual."""
    return [lay.name() for lay in QgsProject.instance().layoutManager().layouts()]
