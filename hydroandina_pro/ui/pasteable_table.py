# -*- coding: utf-8 -*-
"""
ui/pasteable_table.py

Widget QTableWidget con soporte de copiar/pegar estilo hoja de cálculo
(Ctrl+C / Ctrl+V), para permitir pegar directamente un rango de celdas
copiado desde Excel/LibreOffice/Google Sheets (formato estándar de
portapapeles: filas separadas por salto de línea, columnas por
tabulador).

La función de parseo (`parsear_texto_portapapeles`) es pura -- no
depende de Qt -- para poder probarla de forma aislada; la clase
`TablaPegable` es la envoltura de Qt que la conecta al portapapeles real.
"""
from typing import List

from qgis.PyQt.QtWidgets import QTableWidget, QTableWidgetItem, QApplication
from qgis.PyQt.QtGui import QKeySequence


def parsear_texto_portapapeles(texto: str) -> List[List[str]]:
    """
    Convierte texto de portapapeles tipo Excel (filas separadas por
    salto de línea \\n, columnas separadas por tabulador \\t) en una
    lista de listas de strings, una sublista por fila.

    Maneja saltos de línea de Windows (\\r\\n) y Mac clásico (\\r), y
    descarta una línea vacía final (típica al copiar un rango de Excel,
    que suele añadir un salto de línea sobrante al final).
    """
    if not texto:
        return []
    lineas = texto.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lineas and lineas[-1] == "":
        lineas = lineas[:-1]
    return [linea.split("\t") for linea in lineas]


def formatear_para_portapapeles(filas: List[List[str]]) -> str:
    """Inverso de parsear_texto_portapapeles: arma el texto tabulado a
    partir de una lista de listas de strings, para copiar hacia Excel."""
    return "\n".join("\t".join(celdas) for celdas in filas)


class TablaPegable(QTableWidget):
    """QTableWidget que intercepta Ctrl+V/Ctrl+C para pegar/copiar rangos
    de celdas en formato compatible con hojas de cálculo. El pegado
    inicia en la celda actualmente seleccionada y expande la tabla
    (agregando filas) si el contenido pegado no cabe en las filas
    existentes."""

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Paste):
            self._pegar_desde_portapapeles()
            return
        if event.matches(QKeySequence.Copy):
            self._copiar_a_portapapeles()
            return
        super().keyPressEvent(event)

    def _pegar_desde_portapapeles(self):
        texto = QApplication.clipboard().text()
        filas = parsear_texto_portapapeles(texto)
        if not filas:
            return

        fila_inicial = self.currentRow() if self.currentRow() >= 0 else 0
        col_inicial = self.currentColumn() if self.currentColumn() >= 0 else 0

        filas_necesarias = fila_inicial + len(filas)
        if filas_necesarias > self.rowCount():
            self.setRowCount(filas_necesarias)

        for i, celdas in enumerate(filas):
            for j, valor in enumerate(celdas):
                col = col_inicial + j
                if col >= self.columnCount():
                    continue
                self.setItem(fila_inicial + i, col, QTableWidgetItem(valor.strip()))

    def _copiar_a_portapapeles(self):
        seleccion = self.selectedRanges()
        if not seleccion:
            return
        rango = seleccion[0]
        filas = []
        for fila in range(rango.topRow(), rango.bottomRow() + 1):
            celdas = []
            for col in range(rango.leftColumn(), rango.rightColumn() + 1):
                item = self.item(fila, col)
                celdas.append(item.text() if item else "")
            filas.append(celdas)
        QApplication.clipboard().setText(formatear_para_portapapeles(filas))
