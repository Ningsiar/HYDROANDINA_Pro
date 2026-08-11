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

    # Paleta por familia de métodos, para que en el gráfico comparativo se
    # distinga de un vistazo de qué tipo es cada barra (ver plot_comparacion_metodos).
    COLORES_FAMILIA = {
        "Lluvia-escorrentía": "#1F3864",
        "Directo": "#2E7D32",
        "Envolvente": "#B3261E",
        "Escuela regional": "#8B5CF6",
        "Complementario": "#EF9F27",
        "Aforo indirecto": "#0E7490",
    }

    def plot_comparacion_metodos(self, nombres, valores, titulo="Comparación de métodos de caudal máximo",
                                  familias=None, umbral_horizontal=9):
        """Gráfico de barras comparando el Qp obtenido por distintos
        métodos (SCS/Snyder/Clark, Témez, Creager, envolventes, ...).

        Con pocos métodos usa barras VERTICALES (lectura clásica, con la
        etiqueta de valor sobre cada barra). A partir de `umbral_horizontal`
        métodos cambia automáticamente a barras HORIZONTALES ordenadas de
        mayor a menor: con ~30 métodos las etiquetas del eje X en vertical
        se solapan y se vuelven ilegibles, mientras que en horizontal cada
        nombre tiene su propia línea y la comparación de magnitudes es
        inmediata.

        `familias` (opcional): lista paralela a `nombres` con la familia de
        cada método (ver COLORES_FAMILIA), para colorear las barras por tipo
        y agregar una leyenda -- así el orden por magnitud no hace perder la
        información de a qué grupo pertenece cada método.
        """
        self.fig.clear()
        self.ax = self.fig.add_subplot(111)
        if not nombres:
            self.draw()
            return

        if familias and len(familias) == len(nombres):
            colores = [self.COLORES_FAMILIA.get(f, "#666666") for f in familias]
        else:
            paleta = ["#1F3864", "#2E7D32", "#B3261E", "#8B5CF6", "#EF9F27"]
            colores = [paleta[i % len(paleta)] for i in range(len(nombres))]
            familias = None

        if len(nombres) < umbral_horizontal:
            barras = self.ax.bar(nombres, valores, color=colores)
            self.ax.bar_label(barras, fmt="%.1f", padding=4, fontsize=9)
            # Margen superior extra (20%) para que las etiquetas de las
            # barras más altas queden dentro del área de trazado y no
            # choquen con el título.
            self.ax.set_ylim(0, (max(valores) if valores else 1) * 1.2)
            self.ax.set_ylabel("Caudal Qp (m³/s)")
            self.ax.tick_params(axis="x", rotation=15)
            self.ax.grid(True, axis="y", linestyle=":", linewidth=0.5)
        else:
            # Ordenado de mayor a menor y dibujado de abajo hacia arriba,
            # para que el método de mayor caudal quede arriba del todo.
            orden = sorted(range(len(valores)), key=lambda i: valores[i])
            nombres_ord = [nombres[i] for i in orden]
            valores_ord = [valores[i] for i in orden]
            colores_ord = [colores[i] for i in orden]
            posiciones = range(len(nombres_ord))
            barras = self.ax.barh(list(posiciones), valores_ord, color=colores_ord)
            self.ax.set_yticks(list(posiciones))
            self.ax.set_yticklabels(nombres_ord, fontsize=8)
            self.ax.bar_label(barras, fmt="%.1f", padding=3, fontsize=7.5)
            self.ax.set_xlim(0, (max(valores) if valores else 1) * 1.18)
            self.ax.set_xlabel("Caudal Qp (m³/s)")
            self.ax.grid(True, axis="x", linestyle=":", linewidth=0.5)
            # Con muchos métodos la figura por defecto queda apretada:
            # se le da ~0.30 pulgadas de alto por método (mínimo el alto
            # original) para que las etiquetas nunca se solapen.
            alto_necesario = max(self.fig.get_figheight(), 1.6 + 0.30 * len(nombres_ord))
            self.fig.set_figheight(alto_necesario)
            self.setMinimumHeight(int(alto_necesario * self.fig.dpi))

        if familias:
            from matplotlib.patches import Patch
            vistas = []
            for f in familias:
                if f not in vistas:
                    vistas.append(f)
            self.ax.legend(
                handles=[Patch(facecolor=self.COLORES_FAMILIA.get(f, "#666666"), label=f) for f in vistas],
                fontsize=7.5, loc="lower right", framealpha=0.9,
            )

        self.ax.set_title(titulo, pad=14)
        self.fig.tight_layout()
        self.draw()
