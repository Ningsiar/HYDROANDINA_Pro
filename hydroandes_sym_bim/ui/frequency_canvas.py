# -*- coding: utf-8 -*-
"""
ui/frequency_canvas.py

Widget de matplotlib embebido para graficar la serie de máximos anuales
contra las distribuciones ajustadas (Pestaña de Precipitación Máx 24h).

NOTA DE COMPATIBILIDAD: ver ui/hypsometric_canvas.py — backend_qtagg
genérico, compatible con QGIS 3.x (Qt5) y 4.x (Qt6).
"""
import numpy as np

try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
except ImportError:
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

# Estilo comun de leyendas y ejes (ui/chart_style.py). Es idempotente,
# asi que cada lienzo puede invocarlo sin coordinarse con los demas.
from .chart_style import aplicar_estilo_graficos, leyenda_impacto

aplicar_estilo_graficos()


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

    def plot_no_estacionario(self, comparacion: dict, serie_observada, anios):
        """
        Análisis de frecuencia no estacionario en dos paneles:

        ARRIBA: la serie observada con la recta de tendencia ajustada, que
        es donde se ve si la tendencia es real o la impone un par de años
        extremos. Se anota la pendiente y su p-valor.
        ABAJO: la precipitación de diseño estacionaria frente a la que da
        el modelo no estacionario evaluado en distintos años, para
        distintos periodos de retorno -- el análisis de sensibilidad que
        es el uso recomendable de este método. Los años posteriores al
        último observado se dibujan con trama distinta por ser
        EXTRAPOLACIÓN.
        """
        self.fig.clear()
        modelo = comparacion["modelo"]
        ax1 = self.fig.add_subplot(211)
        ax2 = self.fig.add_subplot(212)

        # --- Panel superior: serie y tendencia ---
        ax1.plot(anios, serie_observada, "o-", markersize=4, linewidth=1.1,
                 color="#1F3864", label="Serie observada")
        p = modelo["parametros"]
        pendiente = modelo["tendencia_por_año"]
        if "mu0" in p:
            intercepto = p["mu0"]
        else:
            # Gumbel: xi0 es la posición; la recta de la media va desplazada
            # por la constante de Euler multiplicada por alpha.
            intercepto = p["xi0"] + 0.5772156649 * p["alpha"]
        recta = [intercepto + pendiente * a for a in anios]
        significativa = modelo["tendencia_significativa_5pct"]
        ax1.plot(anios, recta, "--", linewidth=2.0,
                 color="#B3261E" if significativa else "#999999",
                 label=(f"Tendencia: {modelo['tendencia_por_decada']:+.2f} mm/década "
                        f"(p={modelo['p_valor_tendencia']:.4f}, "
                        f"{'significativa' if significativa else 'NO significativa'})"))
        ax1.set_xlabel("Año")
        ax1.set_ylabel("Pmax 24h (mm)")
        ax1.set_title(f"Serie observada y tendencia — {modelo['nombre']}", pad=10)
        ax1.grid(True, linestyle=":", linewidth=0.5)
        ax1.legend(fontsize=7.5, loc="upper left", framealpha=0.9)

        # --- Panel inferior: sensibilidad del valor de diseño ---
        trs = comparacion["periodos_retorno"]
        anios_eval = comparacion["anios_evaluacion"]
        x = list(range(len(trs)))
        ancho = 0.8 / (len(anios_eval) + 1)

        estacionario = [comparacion["tabla"][tr]["estacionario"] for tr in trs]
        ax2.bar([xi - 0.4 + ancho / 2 for xi in x], estacionario, width=ancho,
                color="#1F3864", label="Estacionario")
        paleta = ["#2E7D32", "#EF9F27", "#B3261E"]
        for j, anio in enumerate(anios_eval):
            valores = [comparacion["tabla"][tr][anio]["valor"] for tr in trs]
            es_extrap = comparacion["tabla"][trs[0]][anio]["es_extrapolacion"]
            ax2.bar([xi - 0.4 + ancho * (j + 1) + ancho / 2 for xi in x], valores, width=ancho,
                    color=paleta[j % len(paleta)],
                    hatch="//" if es_extrap else None,
                    edgecolor="white" if es_extrap else None,
                    label=f"{anio}" + (" (EXTRAPOLACIÓN)" if es_extrap else ""))
        ax2.set_xticks(x)
        ax2.set_xticklabels([str(t) for t in trs])
        ax2.set_xlabel("Periodo de retorno (años)")
        ax2.set_ylabel("Pmax 24h de\ndiseño (mm)")
        ax2.set_title("Sensibilidad del valor de diseño frente al modelo estacionario", pad=10)
        ax2.grid(True, axis="y", linestyle=":", linewidth=0.5)
        ax2.legend(fontsize=7, loc="upper left", ncol=2, framealpha=0.9)

        self.fig.tight_layout()
        self.draw()

    def plot_bandas_confianza(self, bandas: dict, datos_observados=None, escala_log: bool = True):
        """
        Curva de frecuencia P24 vs. Tr con la BANDA DE CONFIANZA por
        bootstrap sombreada alrededor.

        bandas: dict devuelto por
            frequency_analysis.bandas_confianza_bootstrap().
        datos_observados: serie observada opcional; si se pasa, se
            dibujan sus puntos con posición de graficación de Weibull
            (i/(n+1)), para ver dónde caen los datos reales respecto de
            la banda -- que es lo que permite juzgar si el ajuste es
            creíble en el rango donde SÍ hay observaciones.
        """
        self.ax.clear()
        trs = sorted(bandas["limites"].keys())
        central = [bandas["limites"][tr]["central"] for tr in trs]
        inferiores = [bandas["limites"][tr]["inferior"] for tr in trs]
        superiores = [bandas["limites"][tr]["superior"] for tr in trs]

        if all(v is not None for v in inferiores + superiores):
            self.ax.fill_between(
                trs, inferiores, superiores, alpha=0.22, color="#1F3864",
                label=f"Banda de confianza {bandas['nivel_confianza']:.0%} "
                      f"({bandas['n_remuestreos']} remuestreos bootstrap)")
            self.ax.plot(trs, inferiores, linestyle=":", linewidth=1.0, color="#1F3864")
            self.ax.plot(trs, superiores, linestyle=":", linewidth=1.0, color="#1F3864")

        self.ax.plot(trs, central, "-o", linewidth=2.2, markersize=4.5, color="#B3261E",
                     label=f"Estimación central — {bandas['nombre_distribucion']}")

        if datos_observados:
            x = sorted(datos_observados)
            n = len(x)
            # Posición de graficación de Weibull: F = i/(n+1), Tr = 1/(1-F).
            tr_obs, p_obs = [], []
            for i, valor in enumerate(x, start=1):
                f = i / (n + 1.0)
                if f < 1.0:
                    tr_obs.append(1.0 / (1.0 - f))
                    p_obs.append(valor)
            self.ax.plot(tr_obs, p_obs, "s", markersize=4, color="#2E7D32",
                         label=f"Datos observados (n={n}, posición de Weibull)")

        if escala_log:
            self.ax.set_xscale("log")
            self.ax.set_xlabel("Periodo de retorno Tr (años, escala log)")
        else:
            self.ax.set_xscale("linear")
            self.ax.set_xlabel("Periodo de retorno Tr (años)")
        self.ax.set_ylabel("Pmax 24h de diseño (mm)")
        self.ax.set_title(
            f"Banda de confianza de la precipitación de diseño — {bandas['nombre_distribucion']}",
            pad=12)
        self.ax.legend(fontsize=7.5, loc="upper left", framealpha=0.9)
        self.ax.grid(True, which="both", linestyle=":", linewidth=0.5)
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


class DiagnosticoDistribucionCanvas(FigureCanvas):
    """
    Panel de 6 gráficos de diagnóstico para UNA distribución ajustada:
    densidad, distribución, supervivencia, riesgo, riesgo acumulado, y
    los diagnósticos P-P / Q-Q -- el juego de gráficos estándar de un
    informe de análisis de frecuencia (misma composición que
    `fitdistrplus::plotdist`/`gofstat` en R, una referencia habitual en
    hidrología estadística).

    Se agrupan en UN panel de 2×3 en vez de 6 lienzos sueltos: es como
    se presentan convencionalmente (para compararlos de un vistazo) y
    evita saturar la pestaña con seis widgets independientes.
    """

    def __init__(self, parent=None, width=10.5, height=6.6, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        super().__init__(self.fig)
        self.setParent(parent)
        self.setMinimumSize(int(width * dpi), int(height * dpi))

    def plot_diagnosticos(self, diagnostico: dict, nombre_distribucion: str, unidad: str = "mm"):
        """
        diagnostico: dict devuelto por
            core.frequency_analysis.diagnostico_distribucion().
        """
        self.fig.clear()
        ejes = self.fig.subplots(2, 3)
        (ax_dens, ax_cdf, ax_surv), (ax_riesgo, ax_riesgo_acum, ax_qqpp) = ejes

        x = np.array(diagnostico["malla_x"])
        datos = np.array(diagnostico["datos_ordenados"])
        color_curva = "#1F3864"
        color_datos = "#B3261E"

        # ---- 1) Densidad de probabilidad f(x) ----
        ax_dens.plot(x, diagnostico["densidad"], "-", linewidth=2.0, color=color_curva,
                     label=nombre_distribucion)
        ax_dens.hist(datos, bins=min(12, max(5, len(datos) // 3)), density=True,
                     color=color_datos, alpha=0.25, edgecolor=color_datos, linewidth=0.6,
                     label="Histograma de los datos")
        ax_dens.set_title("Densidad de probabilidad f(x)", pad=8)
        ax_dens.set_xlabel(f"P24h ({unidad})")
        ax_dens.set_ylabel("Densidad")
        leyenda_impacto(ax_dens, loc="best")

        # ---- 2) Función de distribución F(x) ----
        n = len(datos)
        p_empirica = [(i + 1) / (n + 1) for i in range(n)]
        ax_cdf.plot(x, diagnostico["distribucion_acumulada"], "-", linewidth=2.0, color=color_curva,
                    label="F(x) ajustada")
        ax_cdf.scatter(datos, p_empirica, s=16, color=color_datos, zorder=3,
                       label="Empírica (Weibull)")
        ax_cdf.set_title("Función de distribución F(x)", pad=8)
        ax_cdf.set_xlabel(f"P24h ({unidad})")
        ax_cdf.set_ylabel("P(X ≤ x)")
        leyenda_impacto(ax_cdf, loc="best")

        # ---- 3) Supervivencia S(x) = 1 - F(x) ----
        ax_surv.plot(x, diagnostico["supervivencia"], "-", linewidth=2.0, color="#2E7D32")
        ax_surv.set_title("Supervivencia S(x) = P(X > x)", pad=8)
        ax_surv.set_xlabel(f"P24h ({unidad})")
        ax_surv.set_ylabel("Probabilidad de excedencia")
        ax_surv.grid(True, linestyle=":", linewidth=0.5)

        # ---- 4) Riesgo instantáneo h(x) = f(x)/S(x) ----
        riesgo = np.array(diagnostico["riesgo"])
        valido = np.isfinite(riesgo)
        ax_riesgo.plot(x[valido], riesgo[valido], "-", linewidth=2.0, color="#8B5CF6")
        ax_riesgo.set_title("Riesgo instantáneo h(x) = f(x)/S(x)", pad=8)
        ax_riesgo.set_xlabel(f"P24h ({unidad})")
        ax_riesgo.set_ylabel("Tasa de riesgo")
        ax_riesgo.grid(True, linestyle=":", linewidth=0.5)

        # ---- 5) Riesgo acumulado H(x) = -ln(S(x)) ----
        ax_riesgo_acum.plot(x, diagnostico["riesgo_acumulado"], "-", linewidth=2.0, color="#EF9F27")
        ax_riesgo_acum.set_title("Riesgo acumulado H(x) = −ln S(x)", pad=8)
        ax_riesgo_acum.set_xlabel(f"P24h ({unidad})")
        ax_riesgo_acum.set_ylabel("Riesgo acumulado")
        ax_riesgo_acum.grid(True, linestyle=":", linewidth=0.5)

        # ---- 6) P-P y Q-Q superpuestos (ambos en [0,1] tras normalizar Q-Q) ----
        p_teorica = np.array(diagnostico["p_teorica"])
        q_teorica = np.array(diagnostico["q_teorica"])
        rango_datos = datos.max() - datos.min() or 1.0
        q_emp_norm = (datos - datos.min()) / rango_datos
        q_teo_norm = (q_teorica - datos.min()) / rango_datos

        ax_qqpp.plot([0, 1], [0, 1], "--", linewidth=1.4, color="#666666", label="Diagonal 1:1")
        ax_qqpp.scatter(p_empirica, p_teorica, s=20, marker="o", color=color_curva,
                        label="P-P (probabilidad)", zorder=3)
        ax_qqpp.scatter(q_emp_norm, q_teo_norm, s=20, marker="^", color=color_datos,
                        label="Q-Q (cuantil, normalizado)", zorder=3)
        ax_qqpp.set_title("Diagnóstico P-P y Q-Q", pad=8)
        ax_qqpp.set_xlabel("Empírico")
        ax_qqpp.set_ylabel("Teórico")
        ax_qqpp.set_xlim(-0.02, 1.02)
        ax_qqpp.set_ylim(-0.02, 1.02)
        leyenda_impacto(ax_qqpp, loc="lower right")

        for ax in (ax_dens, ax_cdf, ax_surv, ax_riesgo, ax_riesgo_acum, ax_qqpp):
            ax.grid(True, linestyle=":", linewidth=0.4)

        self.fig.suptitle(f"Diagnóstico gráfico — {nombre_distribucion}", fontsize=12, fontweight="bold")
        self.fig.tight_layout(rect=[0, 0, 1, 0.96])
        self.draw()

    def guardar_figura(self, ruta_png: str):
        self.fig.savefig(ruta_png, dpi=300, bbox_inches="tight")
