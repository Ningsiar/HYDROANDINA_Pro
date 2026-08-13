# -*- coding: utf-8 -*-
"""
ui/groundwater_canvas.py

Gráficos de alto impacto visual de la Pestaña "Flujo Subterráneo":
  1) Mapa de cargas piezométricas (isolíneas + relleno de color) con
     vectores de flujo de Darcy superpuestos.
  2) Curva de convergencia del solver iterativo (Gauss-Seidel/SOR).
  3) Calibración: cargas simuladas vs. observadas en pozos, línea 1:1.
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


class GroundwaterCanvas(FigureCanvas):

    def __init__(self, parent=None, width=7.6, height=5.2, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.ax = self.fig.add_subplot(111)
        super().__init__(self.fig)
        self.setParent(parent)
        self.setMinimumSize(int(width * dpi), int(height * dpi))

    # ------------------------------------------------------------------
    def plot_mapa_cargas(self, h, dx, dy, vx=None, vy=None, pozos_coords=None):
        self.fig.clear()
        ax = self.fig.add_subplot(111)
        n_filas, n_columnas = h.shape
        x = np.arange(n_columnas) * dx
        y = np.arange(n_filas) * dy
        malla_x, malla_y = np.meshgrid(x, y)

        cf = ax.contourf(malla_x, malla_y, h, levels=20, cmap="viridis", zorder=1)
        self.fig.colorbar(cf, ax=ax, label="Carga hidráulica h (m)")
        cs = ax.contour(malla_x, malla_y, h, levels=12, colors="white", linewidths=0.6, zorder=2)
        ax.clabel(cs, inline=True, fontsize=6.5, fmt="%.1f")

        if vx is not None and vy is not None:
            paso = max(n_filas // 15, 1)
            ax.quiver(malla_x[::paso, ::paso], malla_y[::paso, ::paso],
                     vx[::paso, ::paso], -vy[::paso, ::paso], color="white", scale=None,
                     width=0.003, zorder=3, alpha=0.85)

        if pozos_coords:
            for (fila, col), etiqueta in pozos_coords:
                ax.plot(col * dx, fila * dy, "o", color="#B3261E", markersize=8, zorder=5,
                       markeredgecolor="white", markeredgewidth=1.2)
                if etiqueta:
                    ax.annotate(etiqueta, (col * dx, fila * dy), xytext=(6, 6),
                               textcoords="offset points", fontsize=8, fontweight="bold", color="#B3261E")

        ax.set_xlabel("Distancia X (m)")
        ax.set_ylabel("Distancia Y (m)")
        ax.set_title("Mapa de cargas piezométricas y flujo de Darcy", pad=14, fontsize=11, fontweight="bold")
        ax.invert_yaxis()
        self.fig.tight_layout()
        self.draw()

    # ------------------------------------------------------------------
    def plot_convergencia(self, historial_residuo, tol):
        self.fig.clear()
        ax = self.fig.add_subplot(111)
        ax.semilogy(range(1, len(historial_residuo) + 1), historial_residuo, "-", color="#1F6FB2", linewidth=1.8)
        ax.axhline(tol, color="#7A1712", linestyle="--", linewidth=1.4, label=f"Tolerancia = {tol:.1e} m")
        ax.set_xlabel("Iteración")
        ax.set_ylabel("Residuo máximo (m, escala log)")
        ax.set_title("Convergencia del solver (Gauss-Seidel/SOR)", pad=14, fontsize=11, fontweight="bold")
        ax.grid(True, which="both", linestyle=":", linewidth=0.5)
        ax.legend(fontsize=8.5, loc="best")
        self.fig.tight_layout()
        self.draw()

    # ------------------------------------------------------------------
    def plot_calibracion(self, h_obs, h_sim, rmse):
        self.fig.clear()
        ax = self.fig.add_subplot(111)
        ax.scatter(h_obs, h_sim, color="#1F6FB2", edgecolor="black", linewidth=0.5, s=50, zorder=3)
        minimo = min(min(h_obs), min(h_sim))
        maximo = max(max(h_obs), max(h_sim))
        margen = (maximo - minimo) * 0.1 or 1.0
        ax.plot([minimo - margen, maximo + margen], [minimo - margen, maximo + margen], "--",
               color="#7A1712", linewidth=1.6, label="Línea 1:1", zorder=2)
        ax.set_xlabel("Carga observada (m)")
        ax.set_ylabel("Carga simulada (m)")
        ax.set_title(f"Calibración: cargas simuladas vs. observadas (RMSE = {rmse:.3f} m)",
                    pad=14, fontsize=11, fontweight="bold")
        ax.grid(True, linestyle=":", linewidth=0.5)
        ax.legend(fontsize=8.5, loc="upper left", frameon=False)
        ax.set_aspect("equal", adjustable="box")
        self.fig.tight_layout()
        self.draw()
