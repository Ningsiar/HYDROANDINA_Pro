# -*- coding: utf-8 -*-
"""
ui/frequency_canvas.py

Widget de matplotlib embebido para graficar la serie de máximos anuales
contra las distribuciones ajustadas (Pestaña de Precipitación Máx 24h).

NOTA DE COMPATIBILIDAD: ver ui/hypsometric_canvas.py — backend_qtagg
genérico, compatible con QGIS 3.x (Qt5) y 4.x (Qt6).
"""
try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
except ImportError:
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure


class FrequencyCanvas(FigureCanvas):

    def __init__(self, parent=None, width=6.5, height=4.8, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.ax = self.fig.add_subplot(111)
        super().__init__(self.fig)
        self.setParent(parent)
        # Ver comentario equivalente en ui/hypsometric_canvas.py: evita que
        # el QScrollArea deforme el gráfico al angostar la ventana.
        self.setMinimumSize(int(width * dpi), int(height * dpi))

    def plot_ajuste(self, datos_ordenados, resultados_analisis, mejor_clave):
        """
        datos_ordenados: lista de valores observados (mm), ya ordenados.
        resultados_analisis: dict devuelto por frequency_analysis.analizar_todas().
        mejor_clave: clave de la distribución seleccionada como mejor ajuste.
        """
        self.ax.clear()
        n = len(datos_ordenados)
        p_empirica = [(i + 1) / (n + 1) for i in range(n)]  # posición de graficación (Weibull)

        self.ax.scatter(p_empirica, datos_ordenados, s=18, color="#1F3864", label="Datos (posición Weibull)", zorder=3)

        p_continuo = [0.01 + 0.98 * i / 199 for i in range(200)]
        colores = {"normal": "#8FAF7A", "lognormal2": "#EF9F27", "lognormal3": "#D9822B",
                   "gumbel": "#B3261E", "loggumbel": "#7A1712",
                   "gamma2": "#2E7D32", "gamma3_pearson3": "#00897B",
                   "logpearson3": "#7FA8D9", "gev": "#8B5CF6"}
        for clave, resultado in resultados_analisis.items():
            if resultado["error"] or resultado["distribucion"] is None:
                continue
            dist = resultado["distribucion"]
            y = [dist.cuantil(p) for p in p_continuo]
            ancho = 2.2 if clave == mejor_clave else 1.0
            estilo = "-" if clave == mejor_clave else "--"
            self.ax.plot(p_continuo, y, estilo, linewidth=ancho, color=colores.get(clave, "#666666"),
                         label=resultado["nombre"] + (" (mejor ajuste)" if clave == mejor_clave else ""))

        self.ax.set_xlabel("Probabilidad de no excedencia")
        self.ax.set_ylabel("P24h (mm)")
        self.ax.set_title("Ajuste de distribuciones de probabilidad", pad=12)
        self.ax.legend(fontsize=7, loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=3, frameon=False)
        self.ax.grid(True, linestyle=":", linewidth=0.5)
        self.fig.tight_layout()
        self.draw()

    def plot_comparacion_tr(self, tabla_comparacion: dict, resultados_analisis: dict, mejor_clave,
                             escala_log: bool = True):
        """
        Grafica Pmax24h (mm) vs. periodo de retorno Tr (años) para TODAS
        las distribuciones ajustadas, para poder comparar visualmente las
        magnitudes entre distribuciones y decidir con criterio cuál
        adoptar para el caudal máximo.

        tabla_comparacion: dict devuelto por
            frequency_analysis.tabla_comparacion_tr(), {clave: {tr: p24}}.
        escala_log: True = eje Tr en escala logarítmica (por defecto);
            False = eje Tr en escala cartesiana (lineal).
        """
        self.ax.clear()
        colores = {"normal": "#8FAF7A", "lognormal2": "#EF9F27", "lognormal3": "#D9822B",
                   "gumbel": "#B3261E", "loggumbel": "#7A1712",
                   "gamma2": "#2E7D32", "gamma3_pearson3": "#00897B",
                   "logpearson3": "#7FA8D9", "gev": "#8B5CF6"}
        for clave, serie_tr in tabla_comparacion.items():
            trs = sorted(serie_tr.keys())
            valores = [serie_tr[tr] for tr in trs]
            nombre = resultados_analisis.get(clave, {}).get("nombre", clave)
            ancho = 2.4 if clave == mejor_clave else 1.2
            estilo = "-o" if clave == mejor_clave else "--o"
            self.ax.plot(trs, valores, estilo, linewidth=ancho, markersize=4,
                         color=colores.get(clave, "#666666"),
                         label=nombre + (" (mejor ajuste)" if clave == mejor_clave else ""))
        if escala_log:
            self.ax.set_xscale("log")
            self.ax.set_xlabel("Periodo de retorno Tr (años, escala log)")
            titulo = "Comparación Pmax 24h vs. periodo de retorno, por distribución (escala log)"
        else:
            self.ax.set_xscale("linear")
            self.ax.set_xlabel("Periodo de retorno Tr (años, escala cartesiana)")
            titulo = "Comparación Pmax 24h vs. periodo de retorno, por distribución (escala cartesiana)"
        self.ax.set_ylabel("Pmax 24h de diseño (mm)")
        self.ax.set_title(titulo, pad=12)
        self.ax.legend(fontsize=7, loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=3, frameon=False)
        self.ax.grid(True, which="both", linestyle=":", linewidth=0.5)
        self.fig.tight_layout()
        self.draw()
