# -*- coding: utf-8 -*-
"""ui/cav_canvas.py — curva Cota-Área-Volumen (C-A-V), con doble eje X
(área acumulada y volumen acumulado) compartiendo el eje Y (cota)."""
try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
except ImportError:
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

# Estilo comun de leyendas y ejes (ui/chart_style.py). Es idempotente,
# asi que cada lienzo puede invocarlo sin coordinarse con los demas.
from .chart_style import aplicar_estilo_graficos

aplicar_estilo_graficos()


class CavCanvas(FigureCanvas):

    def __init__(self, parent=None, width=6.5, height=4.8, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.ax = self.fig.add_subplot(111)
        self._ax2 = None
        super().__init__(self.fig)
        self.setParent(parent)
        self.setMinimumSize(int(width * dpi), int(height * dpi))

    def plot_cav(self, curva: list):
        self.ax.clear()
        if self._ax2 is None:
            self._ax2 = self.ax.twiny()
        else:
            self._ax2.clear()
        ax2 = self._ax2

        cotas = [d["cota_m"] for d in curva]
        areas_km2 = [d["area_acumulada_km2"] for d in curva]
        volumenes_hm3 = [d["volumen_acumulado_hm3"] for d in curva]

        l1, = self.ax.plot(areas_km2, cotas, "-o", color="#1F6F54", markersize=3, label="Área acumulada (km²)")
        self.ax.set_xlabel("Área acumulada (km²)", color="#1F6F54")
        self.ax.set_ylabel("Cota (m s.n.m.)")
        self.ax.tick_params(axis="x", labelcolor="#1F6F54")
        self.ax.grid(True, linestyle=":", linewidth=0.5)

        l2, = ax2.plot(volumenes_hm3, cotas, "-s", color="#1F3864", markersize=3, label="Volumen acumulado (hm³)")
        ax2.set_xlabel("Volumen acumulado (hm³)", color="#1F3864")
        ax2.tick_params(axis="x", labelcolor="#1F3864")

        self.ax.set_title("Curva Cota-Área-Volumen (C-A-V)", pad=32)
        self.ax.legend([l1, l2], ["Área acumulada", "Volumen acumulado"], fontsize=8, loc="lower right")
        self.fig.tight_layout()
        self.draw()

    def guardar_figura(self, ruta_png: str):
        self.fig.savefig(ruta_png, dpi=300, bbox_inches="tight")
