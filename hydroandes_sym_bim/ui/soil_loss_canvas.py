# -*- coding: utf-8 -*-
"""
ui/soil_loss_canvas.py

Gráficos de alto impacto visual de la Pestaña "Pérdida en Suelos"
(USLE/RUSLE):
  1) Descomposición de factores R·K·LS·C·P de una zona (barras).
  2) Comparación de pérdida de suelo A (t/ha/año) entre varias zonas de
     estudio, coloreada por clase de severidad, con etiquetas de valor.
  3) Mapa clasificado del ráster de pérdida de suelo espacializado (si se
     usó el modo SIG), con leyenda de clases e histograma de área por
     clase.
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
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.patches import Patch

CLASES_EROSION = ["Ligera / tolerable", "Moderada", "Alta", "Muy alta", "Severa / crítica"]
COLORES_EROSION = ["#2E7D32", "#8FAF2E", "#EF9F27", "#D9622B", "#B3261E"]
LIMITES_EROSION = [0, 10, 50, 200, 400, 1e6]


class SoilLossCanvas(FigureCanvas):

    def __init__(self, parent=None, width=7.4, height=5.2, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.ax = self.fig.add_subplot(111)
        super().__init__(self.fig)
        self.setParent(parent)
        self.setMinimumSize(int(width * dpi), int(height * dpi))

    # ------------------------------------------------------------------
    def plot_factores(self, nombre_zona, r, k, ls, c, p, a_resultado):
        self.ax.clear()
        etiquetas = ["R\n(erosividad)", "K\n(erosionabilidad)", "LS\n(topográfico)",
                     "C\n(cobertura)", "P\n(prácticas)"]
        valores = [r, k, ls, c, p]
        colores = ["#1F6FB2", "#7A1712", "#8B5CF6", "#2E7D32", "#EF9F27"]
        barras = self.ax.bar(etiquetas, valores, color=colores, edgecolor="black", linewidth=0.6, zorder=3)
        for barra, valor in zip(barras, valores):
            self.ax.annotate(f"{valor:.3g}", (barra.get_x() + barra.get_width() / 2, valor),
                             xytext=(0, 4), textcoords="offset points", ha="center",
                             fontsize=8.5, fontweight="bold")
        self.ax.set_yscale("symlog", linthresh=0.1)
        self.ax.set_ylabel("Valor del factor (escala log)")
        self.ax.set_title(f"Factores USLE/RUSLE — {nombre_zona}\nA = R·K·LS·C·P = {a_resultado:.2f} t/ha/año",
                          pad=14, fontsize=11, fontweight="bold")
        self.ax.grid(True, axis="y", linestyle=":", linewidth=0.5)
        self.fig.tight_layout()
        self.draw()

    # ------------------------------------------------------------------
    def plot_comparacion_zonas(self, nombres_zonas, valores_a):
        self.ax.clear()
        colores = [self._color_por_clase(v) for v in valores_a]
        barras = self.ax.bar(range(len(nombres_zonas)), valores_a, color=colores,
                              edgecolor="black", linewidth=0.6, zorder=3)
        for barra, valor in zip(barras, valores_a):
            self.ax.annotate(f"{valor:.1f}", (barra.get_x() + barra.get_width() / 2, valor),
                             xytext=(0, 4), textcoords="offset points", ha="center",
                             fontsize=8.5, fontweight="bold")
        self.ax.set_xticks(range(len(nombres_zonas)))
        self.ax.set_xticklabels(nombres_zonas, rotation=28, ha="right", fontsize=8)
        self.ax.set_ylabel("Pérdida de suelo A (t/ha/año)")
        self.ax.set_title("Comparación de pérdida de suelo entre zonas de estudio", pad=14,
                          fontsize=11, fontweight="bold")
        leyenda = [Patch(facecolor=col, edgecolor="black", label=clase)
                   for clase, col in zip(CLASES_EROSION, COLORES_EROSION)]
        self.ax.legend(handles=leyenda, fontsize=7.5, loc="upper center",
                       bbox_to_anchor=(0.5, -0.20), ncol=3, frameon=False)
        self.ax.grid(True, axis="y", linestyle=":", linewidth=0.5)
        self.fig.tight_layout()
        self.draw()

    def _color_por_clase(self, valor):
        for i in range(len(LIMITES_EROSION) - 1):
            if LIMITES_EROSION[i] <= valor < LIMITES_EROSION[i + 1]:
                return COLORES_EROSION[i]
        return COLORES_EROSION[-1]

    # ------------------------------------------------------------------
    def plot_mapa_clasificado(self, array_a, area_por_clase_ha):
        self.ax.clear()
        cmap = ListedColormap(COLORES_EROSION)
        norm = BoundaryNorm(LIMITES_EROSION, cmap.N)
        arr_plot = np.where(np.isnan(array_a), np.nan, array_a)
        im = self.ax.imshow(arr_plot, cmap=cmap, norm=norm, interpolation="nearest")
        self.ax.set_title("Mapa de clasificación de pérdida de suelo (espacializado SIG)",
                          pad=14, fontsize=11, fontweight="bold")
        self.ax.set_xlabel("Columna (píxel)")
        self.ax.set_ylabel("Fila (píxel)")
        leyenda = [Patch(facecolor=col, edgecolor="black",
                        label=f"{clase} ({area_por_clase_ha.get(clase, 0):.1f} ha)")
                   for clase, col in zip(CLASES_EROSION, COLORES_EROSION)]
        self.ax.legend(handles=leyenda, fontsize=7.5, loc="upper center",
                       bbox_to_anchor=(0.5, -0.12), ncol=2, frameon=False)
        self.fig.tight_layout()
        self.draw()
