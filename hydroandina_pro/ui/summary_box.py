# -*- coding: utf-8 -*-
"""
ui/summary_box.py

Cuadro resumen de ALTO IMPACTO: un recuadro enmarcado y centrado que
destaca el resultado principal de un cálculo, con las magnitudes
secundarias desglosadas debajo en una cuadrícula.

MOTIVO: las tablas Parámetro/Valor/Unidad/Comentario (ui/table_utils.py)
son excelentes para consultar el detalle completo de un cálculo, pero
todas sus filas tienen el mismo peso visual -- el dato que de verdad
importa (el caudal de diseño, la lluvia efectiva, la ecuación ajustada)
queda al mismo nivel que un parámetro intermedio. Este widget resuelve
eso: pone UNA cifra grande y legible de un vistazo, con su contexto
alrededor, y deja la tabla para el detalle.

Se introdujo primero a mano para la ecuación IDF combinada (v0.2.45) y
se extrajo aquí como componente reutilizable para poder aplicar el mismo
formato de forma consistente en todas las pestañas.
"""
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QFrame, QVBoxLayout, QHBoxLayout, QGridLayout,
                                  QLabel, QWidget)


# Paletas por tipo de resultado, para que el color comunique el estado
# sin depender solo del texto.
PALETAS = {
    "info":      {"borde": "#2c6fa8", "fondo": "#eef5fb", "titulo": "#1a4a70", "valor": "#0d3757"},
    "exito":     {"borde": "#2E7D32", "fondo": "#eef7ee", "titulo": "#1B5E20", "valor": "#1B5E20"},
    "atencion":  {"borde": "#EF9F27", "fondo": "#fdf6e9", "titulo": "#8a5a00", "valor": "#8a5a00"},
    "alerta":    {"borde": "#B3261E", "fondo": "#fdeeed", "titulo": "#7A1712", "valor": "#7A1712"},
}


class CuadroResumenImpacto(QFrame):
    """
    Recuadro con: título, subtítulo opcional, una cifra principal grande,
    una cuadrícula de métricas secundarias y una leyenda al pie.

    Todo el contenido se fija con actualizar(), de modo que el mismo
    widget se reutiliza en cada recálculo sin reconstruir la interfaz.
    """

    def __init__(self, parent=None, ancho_maximo: int = 720):
        super().__init__(parent)
        self.setObjectName("cuadroResumenImpacto")
        self.setFrameShape(QFrame.StyledPanel)
        self.setMaximumWidth(ancho_maximo)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(16, 12, 16, 14)
        self._layout.setSpacing(6)

        self.lbl_titulo = QLabel("")
        self.lbl_titulo.setAlignment(Qt.AlignCenter)
        self._layout.addWidget(self.lbl_titulo)

        self.lbl_subtitulo = QLabel("")
        self.lbl_subtitulo.setAlignment(Qt.AlignCenter)
        self.lbl_subtitulo.setWordWrap(True)
        self._layout.addWidget(self.lbl_subtitulo)

        self._linea_sup = QFrame()
        self._linea_sup.setFrameShape(QFrame.HLine)
        self._layout.addWidget(self._linea_sup)

        self.lbl_valor = QLabel("—")
        self.lbl_valor.setAlignment(Qt.AlignCenter)
        self.lbl_valor.setWordWrap(True)
        self._layout.addWidget(self.lbl_valor)

        self._linea_inf = QFrame()
        self._linea_inf.setFrameShape(QFrame.HLine)
        self._layout.addWidget(self._linea_inf)

        self._contenedor_metricas = QWidget()
        self._grid = QGridLayout(self._contenedor_metricas)
        self._grid.setHorizontalSpacing(26)
        self._grid.setVerticalSpacing(2)
        h_centrado = QHBoxLayout()
        h_centrado.addStretch()
        h_centrado.addWidget(self._contenedor_metricas)
        h_centrado.addStretch()
        self._layout.addLayout(h_centrado)

        self.lbl_leyenda = QLabel("")
        self.lbl_leyenda.setAlignment(Qt.AlignCenter)
        self.lbl_leyenda.setWordWrap(True)
        self._layout.addWidget(self.lbl_leyenda)

        self.aplicar_paleta("info")

    def aplicar_paleta(self, tipo: str = "info"):
        p = PALETAS.get(tipo, PALETAS["info"])
        self._paleta_actual = p
        self.setStyleSheet(
            "QFrame#cuadroResumenImpacto {"
            f"  border: 2px solid {p['borde']};"
            "   border-radius: 10px;"
            f"  background-color: {p['fondo']};"
            "}"
        )
        self.lbl_titulo.setStyleSheet(
            f"font-weight: bold; font-size: 10.5pt; color: {p['titulo']}; letter-spacing: 1px;")
        self.lbl_subtitulo.setStyleSheet("font-size: 8pt; color: #4a4a4a; font-style: italic;")
        for linea in (self._linea_sup, self._linea_inf):
            linea.setStyleSheet(f"color: {p['borde']};")
        self.lbl_valor.setStyleSheet(
            "font-family: 'Consolas', 'Courier New', monospace; font-size: 15pt; font-weight: bold; "
            f"color: {p['valor']}; padding: 4px 0px;")
        self.lbl_leyenda.setStyleSheet("font-size: 7.7pt; color: #6a6a6a; font-style: italic;")

    def _limpiar_metricas(self):
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def actualizar(self, titulo: str, valor_principal: str, subtitulo: str = "",
                   metricas=None, leyenda: str = "", tipo: str = "info"):
        """
        titulo: encabezado en mayúsculas del recuadro.
        valor_principal: la cifra o expresión destacada (texto ya formateado).
        subtitulo: aclaración breve bajo el título.
        metricas: lista de tuplas (descripción, valor) que se disponen en
            una fila de columnas centradas bajo la cifra principal.
        leyenda: nota al pie (unidades, fuente, advertencia corta).
        tipo: clave de PALETAS ('info', 'exito', 'atencion', 'alerta').
        """
        self.aplicar_paleta(tipo)
        self.lbl_titulo.setText(titulo)
        self.lbl_subtitulo.setText(subtitulo)
        self.lbl_subtitulo.setVisible(bool(subtitulo))
        self.lbl_valor.setText(valor_principal)
        self.lbl_leyenda.setText(leyenda)
        self.lbl_leyenda.setVisible(bool(leyenda))

        self._limpiar_metricas()
        metricas = metricas or []
        for columna, (descripcion, valor) in enumerate(metricas):
            lbl_desc = QLabel(str(descripcion))
            lbl_desc.setAlignment(Qt.AlignCenter)
            lbl_desc.setWordWrap(True)
            lbl_desc.setStyleSheet("font-size: 7.7pt; color: #4a4a4a;")
            self._grid.addWidget(lbl_desc, 0, columna)

            lbl_val = QLabel(str(valor))
            lbl_val.setAlignment(Qt.AlignCenter)
            lbl_val.setStyleSheet(
                f"font-size: 11pt; font-weight: bold; color: {self._paleta_actual['valor']};")
            self._grid.addWidget(lbl_val, 1, columna)
        self._contenedor_metricas.setVisible(bool(metricas))
        self._linea_inf.setVisible(bool(metricas))


def centrar_en_layout(widget, layout):
    """Agrega `widget` a `layout` centrado horizontalmente, sin que se
    estire a todo el ancho disponible."""
    fila = QHBoxLayout()
    fila.addStretch()
    fila.addWidget(widget)
    fila.addStretch()
    layout.addLayout(fila)
    return fila
