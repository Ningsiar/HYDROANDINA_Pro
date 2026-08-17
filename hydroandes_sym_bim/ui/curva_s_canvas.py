# -*- coding: utf-8 -*-
"""
ui/curva_s_canvas.py

Gráfico de alto impacto de la Curva S de avance físico-financiero
PLANIFICADO (ver core/curva_s.py) -- curva acumulada en % (eje
izquierdo) y en S/. (eje derecho, mismos puntos, solo cambia la
escala) contra la fecha, con área sombreada bajo la curva y una caja
de resumen (costo total programable, partidas excluidas si las hay).
Mismo patrón que ui/cronograma_canvas.py (FigureCanvas + chart_style)."""
try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
except ImportError:
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.dates as mdates

from .chart_style import aplicar_estilo_graficos

aplicar_estilo_graficos()

_COLOR_CURVA = "#2c6fa8"
_COLOR_AREA = "#a9c9e6"
_COLOR_ALERTA = "#c0392b"


class CurvaSCanvas(FigureCanvas):
    """Curva S planificada -- ver docstring del módulo."""

    def __init__(self, parent=None, width=8.4, height=5.2, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.ax = self.fig.add_subplot(111)
        super().__init__(self.fig)
        self.setParent(parent)
        self.setMinimumSize(int(width * dpi), int(height * dpi))

    def graficar(self, resultado: dict):
        """`resultado`: dict de core.curva_s.curva_s_planificada()."""
        self.ax.clear()
        puntos = resultado["puntos"]
        fechas = [p["fecha"] for p in puntos]
        fechas_num = mdates.date2num(fechas)
        pcts = [p["pct_acumulado"] for p in puntos]
        costos = [p["costo_acumulado"] for p in puntos]

        self.ax.fill_between(fechas_num, pcts, color=_COLOR_AREA, alpha=0.5, zorder=1)
        self.ax.plot(fechas_num, pcts, color=_COLOR_CURVA, linewidth=2.2, marker="o",
                     markersize=3.5, zorder=3, label="Avance planificado")
        self.ax.set_ylim(0, max(105, max(pcts) * 1.05 if pcts else 105))
        self.ax.set_ylabel("Avance físico-financiero acumulado (%)", color=_COLOR_CURVA)
        self.ax.tick_params(axis="y", labelcolor=_COLOR_CURVA)
        self.ax.xaxis_date()
        self.fig.autofmt_xdate(rotation=35)
        self.ax.xaxis.set_major_formatter(mdates.DateFormatter("%d-%m-%y"))
        self.ax.grid(True, axis="y", linewidth=0.4, alpha=0.5)

        eje_costo = self.ax.twinx()
        eje_costo.plot(fechas_num, costos, alpha=0)  # mismo rango, invisible -- solo fija la escala
        eje_costo.set_ylabel("Costo acumulado (S/.)", color="#555555")
        eje_costo.tick_params(axis="y", labelcolor="#555555")
        if costos:
            eje_costo.set_ylim(0, max(costos) * 1.10 if max(costos) > 0 else 1)

        titulo = f"Curva S -- Avance Planificado ({resultado['periodo'].capitalize()})"
        color_titulo = "#2c2c2c"
        texto_caja = (f"Costo total programable: S/. {resultado['costo_total_programable']:,.2f}\n"
                      f"Partidas programadas: {resultado['n_partidas_programadas']}")
        if resultado["n_partidas_excluidas"]:
            texto_caja += (f"\n⚠ {resultado['n_partidas_excluidas']} partida(s) SIN actividad "
                           f"vinculada -- excluida(s) de la curva\n"
                           f"(S/. {resultado['costo_excluido']:,.2f} no representado)")
            color_titulo = _COLOR_ALERTA
        self.ax.text(0.02, 0.97, texto_caja, transform=self.ax.transAxes, fontsize=8, va="top",
                     ha="left", family="monospace",
                     bbox=dict(boxstyle="round", facecolor="white", edgecolor="#888888", linewidth=1.0))

        self.ax.set_title(titulo, fontsize=10.5, color=color_titulo, fontweight="bold")
        self.ax.set_xlabel("Fecha")
        self.fig.tight_layout()
        self.draw()
