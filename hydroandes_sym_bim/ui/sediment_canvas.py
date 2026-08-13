# -*- coding: utf-8 -*-
"""
ui/sediment_canvas.py

Gráficos de alto impacto visual de la Pestaña "Sedimentos en Suspensión
y Transporte de Sedimentos":
  1) Sección transversal CON y SIN transporte de sedimentos activo
     (perfil de fondo + tasa de transporte unitaria por estación en eje
     secundario, con etiquetas de valor).
  2) Comparación de tasa de transporte entre métodos (barras con
     etiquetas), separado por tipo (fondo / total).
  3) Perfil vertical de Rouse: concentración y velocidad vs. profundidad.
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


class SedimentCanvas(FigureCanvas):

    def __init__(self, parent=None, width=7.4, height=5.2, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.ax = self.fig.add_subplot(111)
        super().__init__(self.fig)
        self.setParent(parent)
        self.setMinimumSize(int(width * dpi), int(height * dpi))

    # ------------------------------------------------------------------
    def plot_seccion_transporte(self, estaciones, elevaciones, tasa_transporte_por_estacion,
                                 nombre_seccion="", nombre_metodo="", unidad="m³/s/m"):
        self.fig.clear()
        ax1 = self.fig.add_subplot(111)
        est = list(estaciones)
        elev = list(elevaciones)
        ax1.plot(est, elev, "-", color="#6B4A2E", linewidth=2.4, zorder=4, label="Fondo del cauce")
        ax1.fill_between(est, elev, min(elev) - 0.5, color="#E8D9C8", alpha=0.5, zorder=1)
        ax1.set_xlabel("Estación (m)")
        ax1.set_ylabel("Elevación (m s.n.m.)", color="#6B4A2E")
        ax1.tick_params(axis="y", labelcolor="#6B4A2E")
        ax1.grid(True, linestyle=":", linewidth=0.5)

        ax2 = ax1.twinx()
        tasa = list(tasa_transporte_por_estacion)
        cero = [0.0] * len(est)
        ax2.plot(est, cero, "--", color="#999999", linewidth=1.2, zorder=2, label="Sin transporte (referencia)")
        ax2.fill_between(est, cero, tasa, color="#1F6FB2", alpha=0.55, zorder=3,
                         label=f"Con transporte de sedimentos ({nombre_metodo})" if nombre_metodo else "Con transporte de sedimentos")
        ax2.set_ylabel(f"Tasa de transporte ({unidad})", color="#1F6FB2")
        ax2.tick_params(axis="y", labelcolor="#1F6FB2")

        if tasa:
            idx_max = max(range(len(tasa)), key=lambda i: tasa[i])
            if tasa[idx_max] > 0:
                ax2.annotate(f"máx = {tasa[idx_max]:.4g} {unidad}\n(estación {est[idx_max]:.1f} m)",
                            (est[idx_max], tasa[idx_max]), xytext=(10, 10), textcoords="offset points",
                            fontsize=8.5, fontweight="bold", color="#0D3D66",
                            arrowprops=dict(arrowstyle="->", color="#0D3D66"),
                            bbox=dict(boxstyle="round", fc="white", ec="#0D3D66", alpha=0.92))

        titulo = "Sección transversal con y sin transporte de sedimentos"
        if nombre_seccion:
            titulo += f" — {nombre_seccion}"
        ax1.set_title(titulo, pad=14, fontsize=11, fontweight="bold")
        h1, l1 = ax1.get_legend_handles_labels()
        h2, l2 = ax2.get_legend_handles_labels()
        ax1.legend(h1 + h2, l1 + l2, fontsize=7.5, loc="upper center",
                   bbox_to_anchor=(0.5, -0.14), ncol=2, frameon=False)
        self.fig.tight_layout()
        self.draw()

    # ------------------------------------------------------------------
    def plot_comparacion_metodos(self, nombres_metodos, valores, titulo="Comparación entre métodos",
                                  unidad="m³/s/m", metodo_gobernante=None):
        self.fig.clear()
        ax = self.fig.add_subplot(111)
        colores = ["#7A1712" if nm == metodo_gobernante else "#1F6FB2" for nm in nombres_metodos]
        barras = ax.bar(range(len(nombres_metodos)), valores, color=colores,
                        edgecolor="black", linewidth=0.6, zorder=3)
        for barra, valor in zip(barras, valores):
            ax.annotate(f"{valor:.3g}", (barra.get_x() + barra.get_width() / 2, valor),
                       xytext=(0, 4), textcoords="offset points", ha="center",
                       fontsize=8.5, fontweight="bold")
        ax.set_xticks(range(len(nombres_metodos)))
        ax.set_xticklabels(nombres_metodos, rotation=22, ha="right", fontsize=8)
        ax.set_ylabel(f"Tasa de transporte ({unidad})")
        titulo_completo = titulo + (f"\n(gobernante: {metodo_gobernante})" if metodo_gobernante else "")
        ax.set_title(titulo_completo, pad=14, fontsize=10.5, fontweight="bold")
        ax.grid(True, axis="y", linestyle=":", linewidth=0.5)
        self.fig.tight_layout()
        self.draw()

    # ------------------------------------------------------------------
    def plot_perfil_rouse(self, perfil_y, perfil_concentracion, perfil_velocidad, z_rouse):
        self.fig.clear()
        ax1 = self.fig.add_subplot(111)
        y = np.array(perfil_y)
        c = np.array(perfil_concentracion)
        v = np.array(perfil_velocidad)
        ax1.plot(c, y, "-", color="#7A1712", linewidth=2.2, label="Concentración C(y)")
        ax1.set_xlabel("Concentración volumétrica (fracción)", color="#7A1712")
        ax1.set_ylabel("Altura sobre el fondo, y (m)")
        ax1.tick_params(axis="x", labelcolor="#7A1712")
        ax1.grid(True, linestyle=":", linewidth=0.5)

        ax2 = ax1.twiny()
        ax2.plot(v, y, "-", color="#1F6FB2", linewidth=2.0, label="Velocidad u(y)")
        ax2.set_xlabel("Velocidad (m/s)", color="#1F6FB2")
        ax2.tick_params(axis="x", labelcolor="#1F6FB2")

        ax1.set_title(f"Perfil vertical de Rouse (Z = {z_rouse:.3f})", pad=28, fontsize=11, fontweight="bold")
        h1, l1 = ax1.get_legend_handles_labels()
        h2, l2 = ax2.get_legend_handles_labels()
        ax1.legend(h1 + h2, l1 + l2, fontsize=8, loc="lower right", frameon=True)
        self.fig.tight_layout()
        self.draw()
