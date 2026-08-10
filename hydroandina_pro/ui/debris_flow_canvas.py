# -*- coding: utf-8 -*-
"""
ui/debris_flow_canvas.py

Gráficos de alto impacto visual de la Pestaña "Flujos Hiperconcentrados/
Lodos/Detritos":
  1) Clasificación del flujo según Cv (barra de rango con bandas de
     color y marcador de la Cv ingresada).
  2) Reología de Bingham: tau vs. tasa de deformación, con tau_y anotado.
  3) Comparación de tirante y velocidad entre métodos (O'Brien-Julien
     vs. Takahashi), con el método recomendado resaltado.
"""
import numpy as np

try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
except ImportError:
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

BANDAS_CV = [(0.0, 0.20, "Fluvial convencional", "#2E7D32"),
             (0.20, 0.45, "Hiperconcentrado", "#EF9F27"),
             (0.45, 0.55, "Flujo de Lodos", "#D9622B"),
             (0.55, 1.0, "Flujo de Detritos", "#B3261E")]


class DebrisFlowCanvas(FigureCanvas):

    def __init__(self, parent=None, width=7.4, height=4.6, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.ax = self.fig.add_subplot(111)
        super().__init__(self.fig)
        self.setParent(parent)
        self.setMinimumSize(int(width * dpi), int(height * dpi))

    # ------------------------------------------------------------------
    def plot_clasificacion(self, cv, clasificacion):
        self.ax.clear()
        for lo, hi, nombre, color in BANDAS_CV:
            self.ax.barh(0, hi - lo, left=lo, height=0.6, color=color, edgecolor="white", linewidth=1.5)
            self.ax.text((lo + hi) / 2 * 100, 0, nombre, ha="center", va="center",
                        fontsize=8.5, fontweight="bold", color="white",
                        rotation=0 if hi - lo > 0.12 else 90)
        self.ax.axvline(cv * 100, color="black", linewidth=2.5, zorder=5)
        self.ax.annotate(f"Cv = {cv*100:.1f}%\n({clasificacion})", (cv * 100, 0.42),
                         ha="center", fontsize=9.5, fontweight="bold",
                         bbox=dict(boxstyle="round", fc="white", ec="black"))
        self.ax.set_xlim(0, 100)
        self.ax.set_ylim(-0.5, 0.6)
        self.ax.set_xlabel("Concentración volumétrica de sedimentos Cv (%)")
        self.ax.set_yticks([])
        self.ax.set_title("Clasificación del flujo según Cv", pad=14, fontsize=11, fontweight="bold")
        self.fig.tight_layout()
        self.draw()

    # ------------------------------------------------------------------
    def plot_reologia_bingham(self, tau_y, mu_p, tasa_max=20):
        self.ax.clear()
        tasa = np.linspace(0, tasa_max, 100)
        tau = tau_y + mu_p * tasa
        self.ax.plot(tasa, tau, "-", color="#7A1712", linewidth=2.4, label="τ = τy + μp·(dv/dy)")
        self.ax.axhline(tau_y, color="#1F6FB2", linestyle="--", linewidth=1.4)
        self.ax.annotate(f"τy = {tau_y:.2f} Pa", (tasa_max * 0.05, tau_y), xytext=(0, 8),
                         textcoords="offset points", fontsize=9, fontweight="bold", color="#1F6FB2")
        self.ax.fill_between(tasa, 0, tau_y, color="#BEE0F5", alpha=0.4)
        self.ax.set_xlabel("Tasa de deformación por corte, dv/dy (s⁻¹)")
        self.ax.set_ylabel("Esfuerzo de corte τ (Pa)")
        self.ax.set_title(f"Reología de Bingham (μp = {mu_p:.3f} Pa·s)", pad=14, fontsize=11, fontweight="bold")
        self.ax.grid(True, linestyle=":", linewidth=0.5)
        self.ax.legend(fontsize=8.5, loc="upper left", frameon=False)
        self.fig.tight_layout()
        self.draw()

    # ------------------------------------------------------------------
    def plot_comparacion_metodos(self, nombres_metodos, tirantes, velocidades, metodo_recomendado=None):
        self.fig.clear()
        ax1 = self.fig.add_subplot(111)
        x = np.arange(len(nombres_metodos))
        ancho = 0.35
        colores_h = ["#7A1712" if nm == metodo_recomendado else "#1F6FB2" for nm in nombres_metodos]
        barras_h = ax1.bar(x - ancho / 2, tirantes, ancho, color=colores_h, edgecolor="black",
                          linewidth=0.6, label="Tirante h (m)", zorder=3)
        for barra, valor in zip(barras_h, tirantes):
            ax1.annotate(f"{valor:.2f} m", (barra.get_x() + barra.get_width() / 2, valor),
                        xytext=(0, 4), textcoords="offset points", ha="center", fontsize=8, fontweight="bold")
        ax1.set_ylabel("Tirante h (m)")

        ax2 = ax1.twinx()
        barras_v = ax2.bar(x + ancho / 2, velocidades, ancho, color="#2E7D32", edgecolor="black",
                          linewidth=0.6, alpha=0.85, label="Velocidad V (m/s)", zorder=3)
        for barra, valor in zip(barras_v, velocidades):
            ax2.annotate(f"{valor:.2f} m/s", (barra.get_x() + barra.get_width() / 2, valor),
                        xytext=(0, 4), textcoords="offset points", ha="center", fontsize=8, fontweight="bold")
        ax2.set_ylabel("Velocidad V (m/s)")

        ax1.set_xticks(x)
        ax1.set_xticklabels(nombres_metodos, fontsize=9)
        titulo = "Comparación de tirante y velocidad entre métodos"
        if metodo_recomendado:
            titulo += f"\n(recomendado: {metodo_recomendado})"
        ax1.set_title(titulo, pad=14, fontsize=10.5, fontweight="bold")
        h1, l1 = ax1.get_legend_handles_labels()
        h2, l2 = ax2.get_legend_handles_labels()
        ax1.legend(h1 + h2, l1 + l2, fontsize=8.5, loc="upper center",
                  bbox_to_anchor=(0.5, -0.12), ncol=2, frameon=False)
        ax1.grid(True, axis="y", linestyle=":", linewidth=0.5)
        self.fig.tight_layout()
        self.draw()
