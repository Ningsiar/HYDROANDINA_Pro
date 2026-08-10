# -*- coding: utf-8 -*-
"""
ui/low_flow_canvas.py

Gráficos de alto impacto visual de la Pestaña "Caudales Mínimos":
  1) Curva de duración de caudales (CDC) con el percentil de persistencia
     marcado (p.ej. Q95).
  2) Escala de Tennant/Montana con el caudal ecológico resultante.
  3) Curva Caudal mínimo vs. Periodo de retorno (Weibull y Gumbel).
  4) Comparación final entre todos los métodos aplicados.
"""
import numpy as np

try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
except ImportError:
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure


class LowFlowCanvas(FigureCanvas):

    def __init__(self, parent=None, width=7.6, height=4.8, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.ax = self.fig.add_subplot(111)
        super().__init__(self.fig)
        self.setParent(parent)
        self.setMinimumSize(int(width * dpi), int(height * dpi))

    # ------------------------------------------------------------------
    def plot_curva_duracion(self, prob_excedencia_pct, caudales_ordenados, percentil_marcado=None, q_marcado=None):
        self.ax.clear()
        self.ax.plot(prob_excedencia_pct, caudales_ordenados, "-", color="#1F6FB2", linewidth=2.2, zorder=3)
        self.ax.set_yscale("log")
        if percentil_marcado is not None and q_marcado is not None:
            self.ax.axvline(percentil_marcado, color="#7A1712", linestyle="--", linewidth=1.4, zorder=2)
            self.ax.axhline(q_marcado, color="#7A1712", linestyle="--", linewidth=1.4, zorder=2)
            self.ax.plot([percentil_marcado], [q_marcado], "o", color="#7A1712", markersize=8, zorder=4)
            self.ax.annotate(f"Q{percentil_marcado:.0f} = {q_marcado:.3f} m³/s", (percentil_marcado, q_marcado),
                            xytext=(10, 10), textcoords="offset points", fontsize=9.5, fontweight="bold",
                            color="#7A1712", bbox=dict(boxstyle="round", fc="white", ec="#7A1712"))
        self.ax.set_xlabel("Probabilidad de excedencia (%)")
        self.ax.set_ylabel("Caudal (m³/s, escala log)")
        self.ax.set_title("Curva de Duración de Caudales", pad=14, fontsize=11, fontweight="bold")
        self.ax.grid(True, which="both", linestyle=":", linewidth=0.5)
        self.fig.tight_layout()
        self.draw()

    # ------------------------------------------------------------------
    def plot_tennant(self, q_ma, porcentaje_estiaje, q_estiaje, porcentaje_normal, q_normal):
        self.ax.clear()
        bandas = [(0, 10, "#B3261E", "Degradación severa"), (10, 20, "#D9622B", "Mínimo"),
                  (20, 30, "#EF9F27", "Regular/pobre"), (30, 40, "#8FAF2E", "Bueno"),
                  (40, 60, "#2E7D32", "Muy bueno"), (60, 100, "#1F6FB2", "Excelente/óptimo")]
        for lo, hi, color, nombre in bandas:
            self.ax.barh(0, hi - lo, left=lo, height=0.6, color=color, edgecolor="white", linewidth=1.2)
        self.ax.axvline(porcentaje_estiaje, color="black", linestyle="--", linewidth=2.0, zorder=5)
        self.ax.annotate(f"Estiaje: {porcentaje_estiaje:.0f}% Qma\n= {q_estiaje:.3f} m³/s",
                         (porcentaje_estiaje, 0.4), ha="center", fontsize=8.5, fontweight="bold",
                         bbox=dict(boxstyle="round", fc="white", ec="black"))
        self.ax.axvline(porcentaje_normal, color="dimgray", linestyle="--", linewidth=2.0, zorder=5)
        self.ax.annotate(f"Normal: {porcentaje_normal:.0f}% Qma\n= {q_normal:.3f} m³/s",
                         (porcentaje_normal, -0.4), ha="center", fontsize=8.5, fontweight="bold",
                         bbox=dict(boxstyle="round", fc="white", ec="dimgray"))
        self.ax.set_xlim(0, 100)
        self.ax.set_ylim(-0.6, 0.6)
        self.ax.set_yticks([])
        self.ax.set_xlabel("Porcentaje del caudal medio anual Qma (%)")
        self.ax.set_title(f"Método de Tennant/Montana (Qma = {q_ma:.3f} m³/s)", pad=14, fontsize=11, fontweight="bold")
        self.fig.tight_layout()
        self.draw()

    # ------------------------------------------------------------------
    def plot_frecuencia_minimos(self, periodos_retorno, q_weibull=None, q_gumbel=None):
        self.ax.clear()
        if q_weibull:
            self.ax.plot(periodos_retorno, q_weibull, "-o", color="#1F6FB2", linewidth=2.0, markersize=5, label="Weibull")
        if q_gumbel:
            self.ax.plot(periodos_retorno, q_gumbel, "-s", color="#7A1712", linewidth=2.0, markersize=5, label="Gumbel de mínimos")
        self.ax.set_xscale("log")
        self.ax.set_xlabel("Periodo de retorno Tr (años, escala log)")
        self.ax.set_ylabel("Caudal mínimo (m³/s)")
        self.ax.set_title("Análisis de frecuencia de caudales mínimos", pad=14, fontsize=11, fontweight="bold")
        self.ax.grid(True, which="both", linestyle=":", linewidth=0.5)
        self.ax.legend(fontsize=9, loc="best", frameon=True)
        self.fig.tight_layout()
        self.draw()

    # ------------------------------------------------------------------
    def plot_comparacion_metodos(self, nombres_metodos, valores, metodo_critico=None):
        self.ax.clear()
        colores = ["#7A1712" if nm == metodo_critico else "#1F6FB2" for nm in nombres_metodos]
        barras = self.ax.bar(range(len(nombres_metodos)), valores, color=colores, edgecolor="black",
                            linewidth=0.6, zorder=3)
        for barra, valor in zip(barras, valores):
            self.ax.annotate(f"{valor:.3f}", (barra.get_x() + barra.get_width() / 2, valor),
                            xytext=(0, 4), textcoords="offset points", ha="center", fontsize=8.5, fontweight="bold")
        self.ax.set_xticks(range(len(nombres_metodos)))
        self.ax.set_xticklabels(nombres_metodos, rotation=25, ha="right", fontsize=8)
        self.ax.set_ylabel("Caudal mínimo (m³/s)")
        titulo = "Comparación entre métodos de caudal mínimo"
        if metodo_critico:
            titulo += f"\n(más restrictivo: {metodo_critico})"
        self.ax.set_title(titulo, pad=14, fontsize=10.5, fontweight="bold")
        self.ax.grid(True, axis="y", linestyle=":", linewidth=0.5)
        self.fig.tight_layout()
        self.draw()
