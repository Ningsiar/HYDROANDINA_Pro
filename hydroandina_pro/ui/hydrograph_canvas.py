# -*- coding: utf-8 -*-
"""
ui/hydrograph_canvas.py

Widget de matplotlib embebido para graficar el hidrograma de crecida
resultante (Pestaña 5).

NOTA DE COMPATIBILIDAD: ver ui/hypsometric_canvas.py — se usa el backend
genérico backend_qtagg para funcionar tanto en QGIS 3.x (Qt5) como 4.x (Qt6).
"""
try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
except ImportError:
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure


class HydrographCanvas(FigureCanvas):

    def __init__(self, parent=None, width=6.5, height=4.8, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.ax = self.fig.add_subplot(111)
        super().__init__(self.fig)
        self.setParent(parent)
        # Ver comentario equivalente en ui/hypsometric_canvas.py: evita que
        # el QScrollArea deforme el gráfico al angostar la ventana.
        self.setMinimumSize(int(width * dpi), int(height * dpi))

    def plot_hidrograma(self, tiempos_h, caudal_m3s, metodo: str, qp: float, tp: float):
        import numpy as np

        self.ax.clear()

        tiempos_h = np.asarray(tiempos_h, dtype=float)
        caudal_m3s = np.asarray(caudal_m3s, dtype=float)

        # El hidrograma se calcula con el Dt del hietograma de entrada
        # (frecuentemente 0.5-1 h), lo que da un aspecto de tramos rectos/
        # "quebrado" al graficarlo directo. Para una lectura de más impacto
        # visual, se interpola a un paso de tiempo mucho más fino (PCHIP,
        # que no genera sobreoscilaciones espurias entre puntos, a
        # diferencia de un spline cúbico común) SOLO para el dibujo; los
        # valores calculados (Qp, Tp, la tabla, la exportación) no cambian.
        if len(tiempos_h) >= 3:
            t_fino = np.linspace(tiempos_h.min(), tiempos_h.max(), max(len(tiempos_h) * 12, 300))
            try:
                from scipy.interpolate import PchipInterpolator
                q_fino = PchipInterpolator(tiempos_h, caudal_m3s)(t_fino)
            except ImportError:
                q_fino = np.interp(t_fino, tiempos_h, caudal_m3s)
            q_fino = np.clip(q_fino, 0.0, None)  # el caudal no puede ser negativo
        else:
            t_fino, q_fino = tiempos_h, caudal_m3s

        self.ax.plot(t_fino, q_fino, linewidth=2.0, color="#1F3864")
        self.ax.fill_between(t_fino, q_fino, alpha=0.12, color="#1F3864")
        self.ax.plot(tiempos_h, caudal_m3s, "o", markersize=3, color="#5B7FB5",
                     label="Valores calculados (Dt del hietograma)")
        self.ax.axvline(tp, linestyle=":", color="#B3261E", linewidth=1)
        self.ax.annotate(f"Qp = {qp:.1f} m³/s", (tp, qp), textcoords="offset points",
                          xytext=(8, 10), fontsize=9, color="#B3261E",
                          bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.75))
        self.ax.set_xlabel("Tiempo (h)")
        self.ax.set_ylabel("Caudal (m³/s)")
        self.ax.set_title(f"Hidrograma de crecida - método {metodo}", pad=12)
        # Margen superior extra para que la etiqueta de Qp (que suele caer
        # cerca del punto más alto de la curva) nunca choque con el título.
        self.ax.set_ylim(0, max(q_fino.max(), caudal_m3s.max()) * 1.18)
        self.ax.grid(True, linestyle=":", linewidth=0.5)
        self.ax.legend(fontsize=8, loc="upper right")
        self.fig.tight_layout()
        self.draw()

    def plot_comparacion_metodos(self, nombres, valores, titulo="Comparación de métodos de caudal máximo"):
        """Gráfico de barras comparando el Qp obtenido por distintos
        métodos (SCS/Snyder/Clark, Témez, Mac Math, Creager, ...), con
        las etiquetas de valor SOBRE cada barra pero con margen
        suficiente para que no se superpongan con el título."""
        self.ax.clear()
        colores = ["#1F3864", "#2E7D32", "#B3261E", "#8B5CF6", "#EF9F27"]
        barras = self.ax.bar(nombres, valores, color=[colores[i % len(colores)] for i in range(len(nombres))])
        self.ax.bar_label(barras, fmt="%.1f", padding=4, fontsize=9)
        # Margen superior extra (20%) para que las etiquetas de las
        # barras más altas queden dentro del área de trazado y no choquen
        # con el título.
        y_max = max(valores) if valores else 1
        self.ax.set_ylim(0, y_max * 1.2)
        self.ax.set_ylabel("Caudal Qp (m³/s)")
        self.ax.set_title(titulo, pad=14)
        self.ax.tick_params(axis="x", rotation=15)
        self.ax.grid(True, axis="y", linestyle=":", linewidth=0.5)
        self.fig.tight_layout()
        self.draw()
