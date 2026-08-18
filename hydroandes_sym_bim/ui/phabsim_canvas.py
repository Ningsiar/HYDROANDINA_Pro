# -*- coding: utf-8 -*-
"""
ui/phabsim_canvas.py

Gráficos de alto impacto visual de la Pestaña "Caudal Ecológico -
PHABSIM":
  1) Curvas de idoneidad de hábitat (HSI): velocidad, profundidad y
     sustrato.
  2) Curva Caudal vs. Área Útil Ponderada (WUA), con el caudal óptimo,
     el umbral porcentual y el punto de inflexión marcados.
  3) Composición del WUA por estación del transecto, en el caudal
     seleccionado.
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


class PhabsimCanvas(FigureCanvas):

    def __init__(self, parent=None, width=7.6, height=4.8, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.ax = self.fig.add_subplot(111)
        super().__init__(self.fig)
        self.setParent(parent)
        self.setMinimumSize(int(width * dpi), int(height * dpi))

    # ------------------------------------------------------------------
    def plot_curvas_hsi(self, curva_v, curva_d, curva_s):
        self.fig.clear()
        ax1 = self.fig.add_subplot(131)
        ax2 = self.fig.add_subplot(132)
        ax3 = self.fig.add_subplot(133)
        for ax, curva, titulo, xlabel, color in [
                (ax1, curva_v, "Velocidad", "Velocidad (m/s)", "#1F6FB2"),
                (ax2, curva_d, "Profundidad", "Tirante (m)", "#2E7D32"),
                (ax3, curva_s, "Sustrato", "Código de sustrato", "#7A1712")]:
            xs = [p[0] for p in curva]
            ys = [p[1] for p in curva]
            ax.plot(xs, ys, "-o", color=color, linewidth=2.0, markersize=4)
            ax.fill_between(xs, 0, ys, color=color, alpha=0.2)
            ax.set_title(titulo, fontsize=10, fontweight="bold")
            ax.set_xlabel(xlabel, fontsize=8.5)
            ax.set_ylabel("Idoneidad (0-1)", fontsize=8.5)
            ax.set_ylim(0, 1.05)
            ax.grid(True, linestyle=":", linewidth=0.5)
        self.fig.suptitle("Curvas de Idoneidad de Hábitat (HSI)", fontsize=11, fontweight="bold")
        self.fig.tight_layout()
        self.draw()

    # ------------------------------------------------------------------
    def plot_curva_q_wua(self, caudales, wua, q_optimo=None, wua_max=None,
                          q_umbral=None, wua_umbral=None, porcentaje_umbral=None,
                          q_inflexion=None, wua_inflexion=None):
        self.fig.clear()
        ax = self.fig.add_subplot(111)
        ax.plot(caudales, wua, "-", color="#1F6FB2", linewidth=2.4, zorder=3, label="WUA(Q)")
        ax.fill_between(caudales, 0, wua, color="#BEE0F5", alpha=0.4, zorder=1)

        if q_optimo is not None:
            ax.axvline(q_optimo, color="#2E7D32", linestyle="--", linewidth=1.6, zorder=2)
            ax.plot([q_optimo], [wua_max], "o", color="#2E7D32", markersize=9, zorder=5)
            ax.annotate(f"Q óptimo = {q_optimo:.2f} m³/s\nWUA máx = {wua_max:.0f} m²/km",
                       (q_optimo, wua_max), xytext=(10, 10), textcoords="offset points",
                       fontsize=8.5, fontweight="bold", color="#2E7D32",
                       bbox=dict(boxstyle="round", fc="white", ec="#2E7D32"))
        if q_umbral is not None:
            ax.axvline(q_umbral, color="#7A1712", linestyle="--", linewidth=1.6, zorder=2)
            ax.plot([q_umbral], [wua_umbral], "s", color="#7A1712", markersize=8, zorder=5)
            ax.annotate(f"Q ({porcentaje_umbral:.0f}% WUA máx) = {q_umbral:.2f} m³/s",
                       (q_umbral, wua_umbral), xytext=(10, -22), textcoords="offset points",
                       fontsize=8.5, fontweight="bold", color="#7A1712",
                       bbox=dict(boxstyle="round", fc="white", ec="#7A1712"))
        if q_inflexion is not None:
            ax.plot([q_inflexion], [wua_inflexion], "^", color="#EF9F27", markersize=9, zorder=5)
            ax.annotate(f"Punto de inflexión\nQ = {q_inflexion:.2f} m³/s",
                       (q_inflexion, wua_inflexion), xytext=(-90, 12), textcoords="offset points",
                       fontsize=8.5, fontweight="bold", color="#B36B00",
                       bbox=dict(boxstyle="round", fc="white", ec="#EF9F27"))

        ax.set_xlabel("Caudal Q (m³/s)")
        ax.set_ylabel("Área Útil Ponderada, WUA (m²/km)")
        ax.set_title("Curva Caudal vs. Hábitat Disponible (WUA)", pad=14, fontsize=11, fontweight="bold")
        ax.grid(True, linestyle=":", linewidth=0.5)
        ax.legend(fontsize=8.5, loc="lower right", frameon=True)
        self.fig.tight_layout()
        self.draw()

    # ------------------------------------------------------------------
    def plot_composicion_estaciones(self, nombres_estaciones, aportes_m2_m, caudal_m3s):
        self.fig.clear()
        ax = self.fig.add_subplot(111)
        colores = plt_colores = ["#1F6FB2"] * len(nombres_estaciones)
        barras = ax.bar(range(len(nombres_estaciones)), aportes_m2_m, color="#1F6FB2",
                        edgecolor="black", linewidth=0.6, zorder=3)
        for barra, valor in zip(barras, aportes_m2_m):
            ax.annotate(f"{valor:.2f}", (barra.get_x() + barra.get_width() / 2, valor),
                       xytext=(0, 4), textcoords="offset points", ha="center", fontsize=8, fontweight="bold")
        ax.set_xticks(range(len(nombres_estaciones)))
        ax.set_xticklabels(nombres_estaciones, rotation=0, fontsize=8.5)
        ax.set_ylabel("Aporte al hábitat (m²/m de cauce)")
        ax.set_title(f"Composición del hábitat por estación (Q = {caudal_m3s:.2f} m³/s)",
                    pad=14, fontsize=11, fontweight="bold")
        ax.grid(True, axis="y", linestyle=":", linewidth=0.5)
        self.fig.tight_layout()
        self.draw()
