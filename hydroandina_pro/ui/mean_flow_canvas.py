# -*- coding: utf-8 -*-
"""
ui/mean_flow_canvas.py

Gráficos de alto impacto visual de la Pestaña "Caudales Medios (Qm)":
  1) Hidrograma simulado vs. observado (si hay aforos) por paso de tiempo.
  2) Dispersión observado vs. simulado con línea 1:1 y R².
  3) Comparación de parámetros antes/después de la calibración.
"""
import numpy as np

try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
except ImportError:
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure


class MeanFlowCanvas(FigureCanvas):

    def __init__(self, parent=None, width=7.6, height=4.8, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.ax = self.fig.add_subplot(111)
        super().__init__(self.fig)
        self.setParent(parent)
        self.setMinimumSize(int(width * dpi), int(height * dpi))

    # ------------------------------------------------------------------
    def plot_hidrograma(self, pasos, q_sim, q_obs=None, nombre_modelo="", unidad="m³/s"):
        self.ax.clear()
        self.ax.plot(pasos, q_sim, "-", color="#1F6FB2", linewidth=2.2, label=f"Q simulado ({nombre_modelo})", zorder=4)
        if q_obs is not None:
            self.ax.plot(pasos, q_obs, "o--", color="#7A1712", linewidth=1.4, markersize=4,
                        label="Q observado (aforo)", zorder=3, alpha=0.85)
        self.ax.set_xlabel("Paso de tiempo")
        self.ax.set_ylabel(f"Caudal ({unidad})")
        self.ax.set_title(f"Hidrograma de caudales medios — {nombre_modelo}", pad=14, fontsize=11, fontweight="bold")
        self.ax.grid(True, linestyle=":", linewidth=0.5)
        self.ax.legend(fontsize=8.5, loc="best", frameon=True)
        self.fig.tight_layout()
        self.draw()

    # ------------------------------------------------------------------
    def plot_dispersión_obs_sim(self, q_obs, q_sim, r2=None, nse=None, unidad="m³/s"):
        self.ax.clear()
        self.ax.scatter(q_obs, q_sim, color="#1F6FB2", edgecolor="black", linewidth=0.4, s=40, zorder=3)
        maximo = max(max(q_obs), max(q_sim)) * 1.05
        self.ax.plot([0, maximo], [0, maximo], "--", color="#7A1712", linewidth=1.6, label="Línea 1:1", zorder=2)
        self.ax.set_xlim(0, maximo)
        self.ax.set_ylim(0, maximo)
        self.ax.set_xlabel(f"Q observado ({unidad})")
        self.ax.set_ylabel(f"Q simulado ({unidad})")
        titulo = "Observado vs. simulado"
        if r2 is not None:
            titulo += f"  (R² = {r2:.3f}"
            if nse is not None:
                titulo += f", NSE = {nse:.3f}"
            titulo += ")"
        self.ax.set_title(titulo, pad=14, fontsize=11, fontweight="bold")
        self.ax.grid(True, linestyle=":", linewidth=0.5)
        self.ax.legend(fontsize=8.5, loc="upper left", frameon=False)
        self.ax.set_aspect("equal", adjustable="box")
        self.fig.tight_layout()
        self.draw()

    # ------------------------------------------------------------------
    def plot_calibracion_parametros(self, nombres_parametros, valores_iniciales, valores_calibrados):
        self.ax.clear()
        x = np.arange(len(nombres_parametros))
        ancho = 0.35
        self.ax.bar(x - ancho / 2, valores_iniciales, ancho, color="#999999", edgecolor="black",
                   linewidth=0.5, label="Inicial", zorder=3)
        barras_cal = self.ax.bar(x + ancho / 2, valores_calibrados, ancho, color="#2E7D32", edgecolor="black",
                                linewidth=0.5, label="Calibrado", zorder=3)
        for barra, valor in zip(barras_cal, valores_calibrados):
            self.ax.annotate(f"{valor:.3g}", (barra.get_x() + barra.get_width() / 2, valor),
                            xytext=(0, 4), textcoords="offset points", ha="center", fontsize=7.5, fontweight="bold")
        self.ax.set_xticks(x)
        self.ax.set_xticklabels(nombres_parametros, rotation=20, ha="right", fontsize=7.5)
        self.ax.set_ylabel("Valor del parámetro")
        self.ax.set_title("Parámetros antes y después de la calibración", pad=14, fontsize=11, fontweight="bold")
        self.ax.legend(fontsize=8.5, loc="best", frameon=False)
        self.ax.grid(True, axis="y", linestyle=":", linewidth=0.5)
        self.fig.tight_layout()
        self.draw()
