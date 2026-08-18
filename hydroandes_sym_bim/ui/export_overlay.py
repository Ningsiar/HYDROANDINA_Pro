# -*- coding: utf-8 -*-
"""
ui/export_overlay.py

Botón de descarga flotante (⬇) que se coloca en la esquina superior
derecha de CUALQUIER tabla, gráfico o cuadro de resumen del plugin, SIN
tocar el layout que lo contiene -- se agrega como hijo directo del propio
widget y se reposiciona con un event filter cada vez que el widget cambia
de tamaño (crece una tabla, se redimensiona un gráfico, etc.).

Por qué así y no un botón normal agregado al layout de cada pestaña: el
plugin tiene más de 150 tablas/gráficos/resúmenes repartidos en ~21
pestañas -- agregar un botón "de verdad" (dentro del layout) a cada uno
implicaría reescribir esa cantidad de bloques de interfaz, con alto
riesgo de romper la disposición existente. Un botón flotante superpuesto
se puede aplicar de una sola vez, al final de HydroAndinaProDialog.__init__
(ver plugin_dialog.py::_habilitar_descargas_universales), recorriendo
TODOS los QTableWidget/gráficos/resúmenes ya construidos con
self.findChildren(...) -- sin tocar ninguno de los ~21 métodos
_build_tab*() uno por uno, y cubriendo automáticamente cualquier tabla o
gráfico que se agregue en el futuro.
"""
from qgis.PyQt.QtCore import QEvent, QObject, Qt
from qgis.PyQt.QtWidgets import QApplication, QFileDialog, QMenu, QMessageBox, QToolButton

from ..core import table_export


class _ReposicionadorEsquina(QObject):
    """Event filter que mantiene el botón flotante pegado a la esquina
    superior derecha del widget padre, incluso cuando este cambia de
    tamaño (tablas que crecen al calcular, gráficos que se redimensionan
    con la ventana, pestañas que recién se hacen visibles)."""

    def __init__(self, boton: QToolButton, margen: int = 4):
        super().__init__(boton)
        self.boton = boton
        self.margen = margen

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Resize, QEvent.Show):
            self.reposicionar(obj)
        return False  # nunca se consume el evento -- solo se observa

    def reposicionar(self, padre):
        x = padre.width() - self.boton.width() - self.margen
        self.boton.move(max(0, x), self.margen)
        self.boton.raise_()


def _crear_boton_flotante(padre) -> QToolButton:
    boton = QToolButton(padre)
    boton.setText("⬇")
    boton.setToolTip("Descargar / exportar")
    boton.setCursor(Qt.PointingHandCursor)
    boton.setFixedSize(22, 20)
    boton.setStyleSheet(
        "QToolButton { background: rgba(255,255,255,225); border: 1px solid #9AA7B5; "
        "border-radius: 4px; font-size: 10px; padding: 0px; } "
        "QToolButton:hover { background: rgba(223,238,252,240); border-color: #2c6fa8; } "
        "QToolButton::menu-indicator { image: none; width: 0px; }"
    )
    boton.setPopupMode(QToolButton.InstantPopup)
    filtro = _ReposicionadorEsquina(boton)
    padre.installEventFilter(filtro)
    filtro.reposicionar(padre)
    boton.show()
    boton.raise_()
    return boton


def _pedir_ruta_guardar(padre, sugerido: str, filtro: str):
    ruta, _ = QFileDialog.getSaveFileName(padre, "Guardar como", sugerido, filtro)
    return ruta or None


def agregar_boton_descarga_tabla(tabla, nombre_base: str = "tabla"):
    """Botón flotante para un QTableWidget YA construido: exportar a
    CSV/XLSX y copiar al portapapeles (TSV, pegable directo en
    Excel/Sheets). No se agrega dos veces sobre la misma tabla."""
    if getattr(tabla, "_boton_descarga_agregado", False):
        return None
    tabla._boton_descarga_agregado = True

    boton = _crear_boton_flotante(tabla)
    menu = QMenu(boton)

    def _tabla_vacia():
        return tabla.rowCount() == 0

    def _exportar_csv():
        if _tabla_vacia():
            QMessageBox.information(tabla, "Tabla vacía", "Esta tabla todavía no tiene datos para exportar.")
            return
        ruta = _pedir_ruta_guardar(tabla, f"{nombre_base}.csv", "CSV (*.csv)")
        if not ruta:
            return
        try:
            table_export.exportar_tabla_a_csv(tabla, ruta)
            QMessageBox.information(tabla, "Exportado", f"Tabla exportada a:\n{ruta}")
        except Exception as e:
            QMessageBox.critical(tabla, "Error al exportar", str(e))

    def _exportar_xlsx():
        if _tabla_vacia():
            QMessageBox.information(tabla, "Tabla vacía", "Esta tabla todavía no tiene datos para exportar.")
            return
        ruta = _pedir_ruta_guardar(tabla, f"{nombre_base}.xlsx", "Excel (*.xlsx)")
        if not ruta:
            return
        try:
            table_export.exportar_tabla_a_xlsx(tabla, ruta, nombre_hoja=nombre_base)
            QMessageBox.information(tabla, "Exportado", f"Tabla exportada a:\n{ruta}")
        except table_export.TableExportError as e:
            QMessageBox.warning(tabla, "openpyxl no disponible", str(e))
        except Exception as e:
            QMessageBox.critical(tabla, "Error al exportar", str(e))

    def _copiar():
        if _tabla_vacia():
            QMessageBox.information(tabla, "Tabla vacía", "Esta tabla todavía no tiene datos para copiar.")
            return
        QApplication.clipboard().setText(table_export.texto_tsv_desde_tabla(tabla))

    menu.addAction("Exportar a Excel (.xlsx)", _exportar_xlsx)
    menu.addAction("Exportar a CSV (.csv)", _exportar_csv)
    menu.addAction("Copiar (pegar en Excel/Sheets)", _copiar)
    boton.setMenu(menu)
    return boton


def agregar_boton_descarga_grafico(canvas, nombre_base: str = "grafico"):
    """Botón flotante para un canvas de matplotlib YA construido (necesita
    un atributo .fig, presente en todos los *Canvas del plugin): guardar
    la figura como PNG o JPG.

    Si además el canvas expone un atributo `ruta_dem_ascii` (por ahora
    solo ui/dem_relief_3d_canvas.py::DemRelieve3DCanvas, el visor 3D de
    la Pestaña 1), se agrega una opción extra para exportar el MDE
    ACTUALMENTE renderizado como ESRI ASCII Grid (.asc) -- el ráster
    completo, no una captura de la imagen, listo para abrir en otro
    software GIS/CAD. El atributo se lee en el momento del clic (no al
    construir el menú), porque el botón se agrega una sola vez al
    iniciar el diálogo, antes de que se haya renderizado ningún MDE."""
    if getattr(canvas, "_boton_descarga_agregado", False):
        return None
    if not hasattr(canvas, "fig"):
        return None
    canvas._boton_descarga_agregado = True

    boton = _crear_boton_flotante(canvas)
    menu = QMenu(boton)

    def _guardar(extension, filtro):
        ruta = _pedir_ruta_guardar(canvas, f"{nombre_base}.{extension}", filtro)
        if not ruta:
            return
        try:
            canvas.fig.savefig(ruta, dpi=200, bbox_inches="tight")
            QMessageBox.information(canvas, "Exportado", f"Gráfico exportado a:\n{ruta}")
        except Exception as e:
            QMessageBox.critical(canvas, "Error al exportar", str(e))

    menu.addAction("Guardar como PNG", lambda: _guardar("png", "PNG (*.png)"))
    menu.addAction("Guardar como JPG", lambda: _guardar("jpg", "JPEG (*.jpg)"))

    if hasattr(canvas, "ruta_dem_ascii"):
        def _exportar_ascii():
            ruta_origen = getattr(canvas, "ruta_dem_ascii", None)
            if not ruta_origen:
                QMessageBox.information(
                    canvas, "Sin MDE renderizado",
                    "Renderice el relieve 3D antes de exportar el MDE a ASCII Grid.")
                return
            ruta = _pedir_ruta_guardar(canvas, f"{nombre_base}.asc", "ESRI ASCII Grid (*.asc)")
            if not ruta:
                return
            try:
                from ..core import raster_stats
                raster_stats.exportar_raster_a_ascii(ruta_origen, ruta)
                QMessageBox.information(canvas, "Exportado", f"MDE exportado a:\n{ruta}")
            except Exception as e:
                QMessageBox.critical(canvas, "Error al exportar", str(e))
        menu.addAction("Guardar MDE como ASCII Grid (.asc)", _exportar_ascii)

    boton.setMenu(menu)
    return boton


def agregar_boton_descarga_texto(widget_texto, nombre_base: str = "resumen"):
    """Botón flotante para un cuadro de resumen final YA construido:
    ResumenFinal (QTextBrowser -- expone toPlainText/toHtml) o
    CuadroResumenImpacto (expone texto_plano()). Copiar todo el
    contenido, y guardar como TXT (y HTML si el widget lo soporta)."""
    if getattr(widget_texto, "_boton_descarga_agregado", False):
        return None
    widget_texto._boton_descarga_agregado = True

    def _texto():
        if hasattr(widget_texto, "toPlainText"):
            return widget_texto.toPlainText()
        if hasattr(widget_texto, "texto_plano"):
            return widget_texto.texto_plano()
        return ""

    boton = _crear_boton_flotante(widget_texto)
    menu = QMenu(boton)

    def _copiar():
        texto = _texto()
        if not texto.strip():
            QMessageBox.information(widget_texto, "Sin contenido", "Este resumen todavía no tiene contenido.")
            return
        QApplication.clipboard().setText(texto)

    def _guardar_txt():
        texto = _texto()
        if not texto.strip():
            QMessageBox.information(widget_texto, "Sin contenido", "Este resumen todavía no tiene contenido.")
            return
        ruta = _pedir_ruta_guardar(widget_texto, f"{nombre_base}.txt", "Texto (*.txt)")
        if not ruta:
            return
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(texto)
        QMessageBox.information(widget_texto, "Exportado", f"Resumen exportado a:\n{ruta}")

    menu.addAction("Copiar todo", _copiar)
    menu.addAction("Guardar como TXT", _guardar_txt)

    if hasattr(widget_texto, "toHtml"):
        def _guardar_html():
            ruta = _pedir_ruta_guardar(widget_texto, f"{nombre_base}.html", "HTML (*.html)")
            if not ruta:
                return
            with open(ruta, "w", encoding="utf-8") as f:
                f.write(widget_texto.toHtml())
            QMessageBox.information(widget_texto, "Exportado", f"Resumen exportado a:\n{ruta}")
        menu.addAction("Guardar como HTML", _guardar_html)

    boton.setMenu(menu)
    return boton
