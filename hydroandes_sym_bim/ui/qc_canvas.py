# -*- coding: utf-8 -*-
"""ui/qc_canvas.py — gráficos de apoyo para los tests de control de
calidad y homogeneidad (pestaña 6, Precipitación Media Mensual)."""
try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
except ImportError:
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

# Estilo comun de leyendas y ejes (ui/chart_style.py). Es idempotente,
# asi que cada lienzo puede invocarlo sin coordinarse con los demas.
from .chart_style import aplicar_estilo_graficos, leyenda_impacto

aplicar_estilo_graficos()


class QcCanvas(FigureCanvas):

    def __init__(self, parent=None, width=6.5, height=4.6, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.ax = self.fig.add_subplot(111)
        super().__init__(self.fig)
        self.setParent(parent)
        self.setMinimumSize(int(width * dpi), int(height * dpi))

    def plot_serie_con_marca(self, serie, titulo, indice_marca=None, etiqueta_marca="",
                              linea_tendencia=None, linea_horizontal=None, etiqueta_horizontal=""):
        """
        serie: valores de la serie en el tiempo.
        indice_marca: posición (1-indexada) a resaltar con una línea
            vertical (punto de cambio candidato).
        linea_tendencia: (pendiente, intercepto) para dibujar la recta
            de tendencia ajustada, si aplica.
        linea_horizontal: valor y de una línea horizontal de referencia
            (p.ej. la mediana, para el test de cruces de mediana).
        """
        self.ax.clear()
        t = list(range(1, len(serie) + 1))
        self.ax.plot(t, serie, "-o", color="#1F3864", markersize=4, linewidth=1.3, label="Serie")

        if indice_marca:
            self.ax.axvline(indice_marca + 0.5, color="#B3261E", linestyle="--", linewidth=1.5,
                             label=etiqueta_marca or "Quiebre candidato")
        if linea_tendencia is not None:
            pendiente, intercepto = linea_tendencia
            y_tend = [pendiente * ti + intercepto for ti in t]
            self.ax.plot(t, y_tend, "-", color="#B3261E", linewidth=1.8, label="Tendencia ajustada")
        if linea_horizontal is not None:
            self.ax.axhline(linea_horizontal, color="#2E7D32", linestyle=":", linewidth=1.3,
                             label=etiqueta_horizontal or "Referencia")

        self.ax.set_xlabel("Posición en la serie")
        self.ax.set_ylabel("Valor")
        # pad en el título y leyenda fuera del área de trazado para que
        # nunca se superpongan con las líneas/marcas de la serie
        self.ax.set_title(titulo, pad=12)
        self.ax.legend(fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=3, frameon=False)
        self.ax.grid(True, linestyle=":", linewidth=0.5)
        self.fig.tight_layout()
        self.draw()

    def plot_dos_periodos(self, periodo1, periodo2, titulo, etiqueta1="Periodo 1", etiqueta2="Periodo 2"):
        self.ax.clear()
        # 'tick_labels' es el nombre del parámetro en Matplotlib >= 3.9;
        # 'labels' en versiones anteriores. Se intenta el nuevo primero
        # para no generar un DeprecationWarning en versiones recientes.
        try:
            self.ax.boxplot([periodo1, periodo2], tick_labels=[etiqueta1, etiqueta2], widths=0.5,
                             patch_artist=True,
                             boxprops=dict(facecolor="#8FCBEA", color="#1F3864"),
                             medianprops=dict(color="#B3261E", linewidth=2))
        except TypeError:
            self.ax.boxplot([periodo1, periodo2], labels=[etiqueta1, etiqueta2], widths=0.5,
                             patch_artist=True,
                             boxprops=dict(facecolor="#8FCBEA", color="#1F3864"),
                             medianprops=dict(color="#B3261E", linewidth=2))
        self.ax.set_ylabel("Valor")
        self.ax.set_title(titulo, pad=12)
        self.ax.grid(True, axis="y", linestyle=":", linewidth=0.5)
        self.fig.tight_layout()
        self.draw()

    def plot_pacf(self, pacf_por_lag: dict, limite_significancia: float,
                  lags_significativos=None, titulo="Función de autocorrelación parcial (PACF)"):
        """
        Correlograma parcial en formato de barras verticales (stem), con
        la banda de significancia al 95%.

        Se muestra así, y no como una curva, porque cada lag es una
        estimación independiente: lo que hay que leer es qué barras
        SALEN de la banda, no la forma del conjunto. Los lags
        significativos se destacan en rojo -- son los que invalidan la
        hipótesis de independencia que asumen Mann-Kendall, Pettitt y
        las demás pruebas de esta pestaña.
        """
        self.ax.clear()
        lags_significativos = set(lags_significativos or [])
        # El lag 0 vale siempre 1 por definición y no aporta información;
        # incluirlo aplastaría la escala del resto.
        lags = [int(k) for k in pacf_por_lag.keys() if int(k) > 0]
        lags.sort()
        valores = [pacf_por_lag[k] if k in pacf_por_lag else pacf_por_lag[str(k)] for k in lags]

        self.ax.axhspan(-limite_significancia, limite_significancia, color="#2c6fa8", alpha=0.13,
                        zorder=1, label=f"Banda de no significancia 95% (±{limite_significancia:.3f})")
        self.ax.axhline(0, color="#555555", linewidth=1.0, zorder=2)

        etiquetado_sig = etiquetado_no_sig = False
        for lag, valor in zip(lags, valores):
            significativo = lag in lags_significativos or abs(valor) > limite_significancia
            color = "#B3261E" if significativo else "#1F3864"
            etiqueta = None
            if significativo and not etiquetado_sig:
                etiqueta, etiquetado_sig = "Lag con dependencia serial significativa", True
            elif not significativo and not etiquetado_no_sig:
                etiqueta, etiquetado_no_sig = "Lag sin dependencia significativa", True
            self.ax.vlines(lag, 0, valor, color=color, linewidth=2.6, zorder=3, label=etiqueta)
            self.ax.plot(lag, valor, "o", markersize=6.5, color=color, markeredgecolor="white",
                         markeredgewidth=1.0, zorder=4)

        self.ax.set_xlabel("Lag (pasos de tiempo)")
        self.ax.set_ylabel("Autocorrelación parcial")
        self.ax.set_title(titulo, pad=12)
        self.ax.set_xticks(lags)
        self.ax.grid(True, axis="y", linestyle=":", linewidth=0.5)
        leyenda_impacto(self.ax, titulo="Lectura del correlograma", loc="best")
        self.fig.tight_layout()
        self.draw()
