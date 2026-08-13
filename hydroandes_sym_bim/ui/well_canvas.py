# -*- coding: utf-8 -*-
"""
ui/well_canvas.py

Gráficos de alto impacto visual de la Pestaña "Hidráulica de Pozos":
  1) Curva de descenso vs. tiempo (Theis) en escala semi-log.
  2) Ajuste de Cooper-Jacob (recta s vs. log t) con T y S resultantes.
  3) Ensayo de bombeo escalonado: sw/Q vs. Q, con B y C.
  4) Comparación de radios de influencia entre métodos.
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


class WellCanvas(FigureCanvas):

    def __init__(self, parent=None, width=7.6, height=4.8, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.ax = self.fig.add_subplot(111)
        super().__init__(self.fig)
        self.setParent(parent)
        self.setMinimumSize(int(width * dpi), int(height * dpi))

    # ------------------------------------------------------------------
    def plot_descenso_tiempo(self, tiempos_s, descensos_m, tiempos_obs=None, descensos_obs=None):
        self.fig.clear()
        ax = self.fig.add_subplot(111)
        ax.semilogx(tiempos_s, descensos_m, "-", color="#1F6FB2", linewidth=2.2, label="Descenso teórico (Theis)", zorder=3)
        if tiempos_obs is not None and descensos_obs is not None:
            ax.semilogx(tiempos_obs, descensos_obs, "o", color="#7A1712", markersize=6, label="Medido en campo", zorder=4)
        ax.invert_yaxis()
        ax.set_xlabel("Tiempo desde el inicio del bombeo (s, escala log)")
        ax.set_ylabel("Descenso s (m)")
        ax.set_title("Curva de descenso vs. tiempo", pad=14, fontsize=11, fontweight="bold")
        ax.grid(True, which="both", linestyle=":", linewidth=0.5)
        ax.legend(fontsize=8.5, loc="best")
        self.fig.tight_layout()
        self.draw()

    # ------------------------------------------------------------------
    def plot_cooper_jacob(self, tiempos_s, descensos_m, t0_s, pendiente, intercepto):
        self.fig.clear()
        ax = self.fig.add_subplot(111)
        log_t = np.log10(tiempos_s)
        ax.plot(log_t, descensos_m, "o", color="#7A1712", markersize=7, zorder=4, label="Datos medidos")
        x_recta = np.linspace(min(log_t) - 0.3, max(log_t) + 0.5, 50)
        y_recta = pendiente * x_recta + intercepto
        ax.plot(x_recta, y_recta, "-", color="#1F6FB2", linewidth=2.0, zorder=3, label="Recta ajustada")
        ax.axvline(np.log10(t0_s), color="#2E7D32", linestyle="--", linewidth=1.4, zorder=2)
        ax.plot([np.log10(t0_s)], [0], "s", color="#2E7D32", markersize=9, zorder=5)
        ax.annotate(f"t0 = {t0_s:.1f} s\n(s=0, extrapolado)", (np.log10(t0_s), 0), xytext=(10, 15),
                   textcoords="offset points", fontsize=8.5, fontweight="bold", color="#2E7D32",
                   bbox=dict(boxstyle="round", fc="white", ec="#2E7D32"))
        ax.invert_yaxis()
        ax.set_xlabel("log₁₀(tiempo, s)")
        ax.set_ylabel("Descenso s (m)")
        ax.set_title("Ajuste de Cooper-Jacob (recta s vs. log t)", pad=14, fontsize=11, fontweight="bold")
        ax.grid(True, linestyle=":", linewidth=0.5)
        ax.legend(fontsize=8.5, loc="best")
        self.fig.tight_layout()
        self.draw()

    # ------------------------------------------------------------------
    def plot_ensayo_escalonado(self, caudales_m3s, descensos_m, b, c):
        self.fig.clear()
        ax = self.fig.add_subplot(111)
        y_datos = [s / q for s, q in zip(descensos_m, caudales_m3s)]
        ax.plot(caudales_m3s, y_datos, "o", color="#7A1712", markersize=8, zorder=4, label="sw/Q medido")
        x_recta = np.linspace(0, max(caudales_m3s) * 1.15, 50)
        y_recta = b + c * x_recta
        ax.plot(x_recta, y_recta, "-", color="#1F6FB2", linewidth=2.0, zorder=3,
               label=f"sw/Q = {b:.2f} + {c:.2f}·Q")
        ax.set_xlabel("Caudal Q (m³/s)")
        ax.set_ylabel("sw/Q (s/m²)")
        ax.set_title("Ensayo de bombeo escalonado — pérdidas de pozo", pad=14, fontsize=11, fontweight="bold")
        ax.grid(True, linestyle=":", linewidth=0.5)
        ax.legend(fontsize=8.5, loc="best")
        self.fig.tight_layout()
        self.draw()

    # ------------------------------------------------------------------
    def plot_comparacion_radios(self, nombres_metodos, valores, metodo_recomendado=None):
        self.fig.clear()
        ax = self.fig.add_subplot(111)
        colores = ["#7A1712" if nm == metodo_recomendado else "#1F6FB2" for nm in nombres_metodos]
        barras = ax.bar(range(len(nombres_metodos)), valores, color=colores, edgecolor="black",
                       linewidth=0.6, zorder=3)
        for barra, valor in zip(barras, valores):
            ax.annotate(f"{valor:.1f} m", (barra.get_x() + barra.get_width() / 2, valor),
                       xytext=(0, 4), textcoords="offset points", ha="center", fontsize=8.5, fontweight="bold")
        ax.set_xticks(range(len(nombres_metodos)))
        ax.set_xticklabels(nombres_metodos, rotation=15, ha="right", fontsize=9)
        ax.set_ylabel("Radio de influencia R (m)")
        titulo = "Comparación de radios de influencia"
        if metodo_recomendado:
            titulo += f"\n(recomendado: {metodo_recomendado})"
        ax.set_title(titulo, pad=14, fontsize=10.5, fontweight="bold")
        ax.grid(True, axis="y", linestyle=":", linewidth=0.5)
        self.fig.tight_layout()
        self.draw()
