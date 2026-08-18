# -*- coding: utf-8 -*-
"""
ui/infiltration_canvas.py

Gráficos de los modelos de pérdidas por infiltración (Pestaña 3):
curvas de capacidad de infiltración, separación lluvia
efectiva/infiltrada, y comparación entre métodos.

NOTA DE COMPATIBILIDAD: ver ui/hypsometric_canvas.py — se usa el backend
genérico backend_qtagg para funcionar tanto en QGIS 3.x (Qt5) como 4.x (Qt6).
"""
try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
except ImportError:
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

# Estilo comun de leyendas y ejes (ui/chart_style.py). Es idempotente,
# asi que cada lienzo puede invocarlo sin coordinarse con los demas.
from .chart_style import aplicar_estilo_graficos

aplicar_estilo_graficos()


class InfiltrationCanvas(FigureCanvas):

    COLORES_METODO = {
        "SCS — Número de Curva": "#1F3864",
        "Green-Ampt (1911)": "#B3261E",
        "Horton (1940)": "#2E7D32",
        "Philip (1957)": "#8B5CF6",
        "Kostiakov (1932)": "#EF9F27",
        "Kostiakov-Lewis": "#C77700",
        "Holtan (USDA-HL)": "#0E7490",
    }

    def __init__(self, parent=None, width=7.0, height=4.6, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.ax = self.fig.add_subplot(111)
        super().__init__(self.fig)
        self.setParent(parent)
        self.setMinimumSize(int(width * dpi), int(height * dpi))

    def plot_hietograma_separado(self, resultado, dt_h):
        """
        Hietograma en barras apiladas: la parte inferior es lo que
        infiltra y la superior la lluvia efectiva que escurre. Sobre él,
        en un eje secundario, la curva de capacidad de infiltración, para
        ver el instante en que la intensidad la supera (encharcamiento).
        """
        self.fig.clear()
        self.ax = self.fig.add_subplot(111)

        infiltrado = resultado["infiltracion_incr_mm"]
        efectiva = resultado["lluvia_efectiva_incr_mm"]
        n = len(infiltrado)
        tiempos = [i * dt_h for i in range(n)]
        ancho = dt_h * 0.85

        self.ax.bar(tiempos, infiltrado, width=ancho, align="edge",
                    color="#2E7D32", alpha=0.65, label="Infiltrado (pérdidas)")
        self.ax.bar(tiempos, efectiva, width=ancho, align="edge", bottom=infiltrado,
                    color="#B3261E", alpha=0.75, label="Lluvia efectiva (escurre)")
        self.ax.set_xlabel("Tiempo (h)")
        self.ax.set_ylabel("Lámina por intervalo (mm)")

        capacidad = resultado.get("capacidad_infiltracion_mm_h") or []
        validas = [(t, c) for t, c in zip(tiempos, capacidad) if c is not None]
        if validas:
            ax2 = self.ax.twinx()
            intensidad = [(i_mm + e_mm) / dt_h for i_mm, e_mm in zip(infiltrado, efectiva)]
            ax2.step([t for t, _ in validas], [c for _, c in validas], where="post",
                     linestyle="--", linewidth=1.6, color="#1F3864",
                     label="Capacidad de infiltración")
            ax2.step(tiempos, intensidad, where="post", linewidth=1.4, color="#EF9F27",
                     label="Intensidad de la lluvia")
            ax2.set_ylabel("Tasa (mm/h)")
            # Un tope razonable evita que la singularidad inicial de
            # algunos métodos (Philip diverge en t=0) aplaste la escala.
            tope = max(max(intensidad) if intensidad else 1,
                       sorted(c for _, c in validas)[len(validas) // 2] * 3)
            ax2.set_ylim(0, max(tope, 1) * 1.2)
            l1, e1 = self.ax.get_legend_handles_labels()
            l2, e2 = ax2.get_legend_handles_labels()
            self.ax.legend(l1 + l2, e1 + e2, fontsize=7.5, loc="upper right", framealpha=0.9)
        else:
            self.ax.legend(fontsize=8, loc="upper right")

        if resultado.get("hubo_encharcamiento"):
            t_ench = resultado["tiempo_encharcamiento_h"]
            self.ax.axvline(t_ench, linestyle=":", linewidth=1.4, color="#7A1712")
            self.ax.annotate(f"encharcamiento\nt = {t_ench} h", xy=(t_ench, 0),
                             xytext=(6, 8), textcoords="offset points", fontsize=7.5,
                             color="#7A1712")

        self.ax.set_title(
            f"{resultado['metodo']} — efectiva {resultado['lluvia_efectiva_total_mm']} mm "
            f"de {resultado['lluvia_total_mm']} mm  (C = {resultado['coeficiente_escorrentia']})",
            pad=12)
        self.ax.grid(True, axis="y", linestyle=":", linewidth=0.5)
        self.fig.tight_layout()
        self.draw()

    def plot_comparacion_metodos(self, resultados_por_metodo, dt_h):
        """
        Compara varios modelos de pérdidas sobre el mismo hietograma:
        arriba la lluvia efectiva acumulada de cada uno, abajo las barras
        de lluvia efectiva total. Permite ver de un vistazo cuánto
        difiere el caudal de diseño según el modelo elegido.
        """
        self.fig.clear()
        ax1 = self.fig.add_subplot(211)
        ax2 = self.fig.add_subplot(212)

        nombres, totales, colores = [], [], []
        for resultado in resultados_por_metodo:
            efectiva = resultado["lluvia_efectiva_incr_mm"]
            acumulada, suma = [], 0.0
            for valor in efectiva:
                suma += valor
                acumulada.append(suma)
            tiempos = [i * dt_h for i in range(len(acumulada))]
            color = self.COLORES_METODO.get(resultado["metodo"], "#666666")
            ax1.plot(tiempos, acumulada, linewidth=1.9, color=color, label=resultado["metodo"])
            nombres.append(resultado["metodo"])
            totales.append(resultado["lluvia_efectiva_total_mm"])
            colores.append(color)

        ax1.set_xlabel("Tiempo (h)")
        ax1.set_ylabel("Lluvia efectiva\nacumulada (mm)")
        ax1.set_title("Comparación de modelos de pérdidas sobre el mismo hietograma", pad=10)
        ax1.grid(True, linestyle=":", linewidth=0.5)
        ax1.legend(fontsize=7, loc="upper left", framealpha=0.9)

        barras = ax2.barh(range(len(nombres)), totales, color=colores)
        ax2.set_yticks(range(len(nombres)))
        ax2.set_yticklabels(nombres, fontsize=7.5)
        ax2.bar_label(barras, fmt="%.1f mm", padding=3, fontsize=7.5)
        ax2.set_xlim(0, (max(totales) if totales else 1) * 1.22)
        ax2.set_xlabel("Lluvia efectiva total (mm) — determina el caudal pico")
        ax2.grid(True, axis="x", linestyle=":", linewidth=0.5)

        self.fig.tight_layout()
        self.draw()
