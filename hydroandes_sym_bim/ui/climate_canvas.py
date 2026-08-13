# -*- coding: utf-8 -*-
"""
ui/climate_canvas.py

Gráficos de alto impacto visual de la Pestaña "Cambio Climático -
Escenarios":
  1) Régimen mensual base vs. escenarios futuros (barras agrupadas,
     precipitación o temperatura).
  2) Cambio porcentual/absoluto anual por escenario (barras etiquetadas).
  3) Corrección de sesgo: serie observada vs. modelo crudo vs. modelo
     corregido.
"""
import numpy as np

try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
except ImportError:
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

# Estilo comun de leyendas y ejes (ui/chart_style.py). Es idempotente,
# asi que cada lienzo puede invocarlo sin coordinarse con los demas.
from .chart_style import aplicar_estilo_graficos

aplicar_estilo_graficos()

COLORES_ESCENARIOS = {"Base (histórico)": "#444444", "SSP1-2.6": "#2E7D32", "SSP2-4.5": "#EF9F27",
                       "SSP3-7.0": "#D9622B", "SSP5-8.5": "#B3261E"}
MESES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


class ClimateCanvas(FigureCanvas):

    def __init__(self, parent=None, width=7.6, height=4.8, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.ax = self.fig.add_subplot(111)
        super().__init__(self.fig)
        self.setParent(parent)
        self.setMinimumSize(int(width * dpi), int(height * dpi))

    # ------------------------------------------------------------------
    def plot_regimen_mensual(self, series_por_escenario: dict, variable="Precipitación", unidad="mm"):
        self.ax.clear()
        n_series = len(series_por_escenario)
        ancho = 0.8 / max(n_series, 1)
        x = np.arange(12)
        for i, (nombre, valores) in enumerate(series_por_escenario.items()):
            color = COLORES_ESCENARIOS.get(nombre, f"C{i}")
            offset = (i - (n_series - 1) / 2) * ancho
            self.ax.bar(x + offset, valores, ancho, label=nombre, color=color, edgecolor="black", linewidth=0.4, zorder=3)
        self.ax.set_xticks(x)
        self.ax.set_xticklabels(MESES)
        self.ax.set_ylabel(f"{variable} ({unidad})")
        self.ax.set_title(f"Régimen mensual — {variable}: histórico vs. escenarios futuros",
                          pad=14, fontsize=11, fontweight="bold")
        self.ax.grid(True, axis="y", linestyle=":", linewidth=0.5)
        self.ax.legend(fontsize=7.5, loc="upper center", bbox_to_anchor=(0.5, -0.15), ncol=5, frameon=False)
        self.fig.tight_layout()
        self.draw()

    # ------------------------------------------------------------------
    def plot_cambio_anual(self, nombres_escenarios, valores_cambio, variable="Precipitación",
                          unidad="%"):
        self.ax.clear()
        colores = [COLORES_ESCENARIOS.get(nm, "#1F6FB2") for nm in nombres_escenarios]
        barras = self.ax.bar(nombres_escenarios, valores_cambio, color=colores, edgecolor="black",
                            linewidth=0.6, zorder=3)
        for barra, valor in zip(barras, valores_cambio):
            self.ax.annotate(f"{valor:+.1f}{unidad}", (barra.get_x() + barra.get_width() / 2, valor),
                            xytext=(0, 6 if valor >= 0 else -14), textcoords="offset points",
                            ha="center", fontsize=9, fontweight="bold")
        self.ax.axhline(0, color="black", linewidth=0.8)
        self.ax.set_ylabel(f"Cambio de {variable} ({unidad})")
        self.ax.set_title(f"Cambio anual proyectado de {variable} por escenario", pad=14,
                          fontsize=11, fontweight="bold")
        self.ax.grid(True, axis="y", linestyle=":", linewidth=0.5)
        self.fig.tight_layout()
        self.draw()

    # ------------------------------------------------------------------
    def plot_correccion_sesgo(self, meses_o_indices, obs, modelo_crudo, modelo_corregido, variable="Precipitación", unidad="mm"):
        self.ax.clear()
        x = list(meses_o_indices)
        self.ax.plot(x, obs, "-o", color="#2E7D32", linewidth=2.2, markersize=5, label="Observado", zorder=4)
        self.ax.plot(x, modelo_crudo, "--s", color="#B3261E", linewidth=1.8, markersize=4,
                    label="Modelo crudo (sin corregir)", zorder=3, alpha=0.85)
        self.ax.plot(x, modelo_corregido, "-^", color="#1F6FB2", linewidth=2.0, markersize=5,
                    label="Modelo corregido (bias correction)", zorder=5)
        self.ax.set_ylabel(f"{variable} ({unidad})")
        self.ax.set_title(f"Corrección de sesgo — {variable}: observado vs. modelo crudo vs. corregido",
                          pad=14, fontsize=11, fontweight="bold")
        self.ax.grid(True, linestyle=":", linewidth=0.5)
        self.ax.legend(fontsize=8.5, loc="best", frameon=True)
        self.fig.tight_layout()
        self.draw()
