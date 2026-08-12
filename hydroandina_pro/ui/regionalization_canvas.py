# -*- coding: utf-8 -*-
"""
ui/regionalization_canvas.py

Gráficos de las dos secciones nuevas de la Pestaña 15 (Precipitación
Media Mensual):

  * RegionalizacionCanvas: dispersión variable-covariable con la recta
    ajustada y su banda de confianza al 95%, más los puntos estimados
    superpuestos -- el gráfico que permite ver de un vistazo si la
    covariable (típicamente la altitud) realmente explica la variación
    entre estaciones, o si la nube está tan dispersa que extrapolar
    sería inventar.

  * ValidacionGrilladaCanvas: dos paneles complementarios para juzgar un
    producto grillado (CHIRPS / IMERG / ERA5-Land / PISCOp) --
    dispersión 1:1 frente a la estación (¿acierta la magnitud?) y tabla
    de contingencia de detección de lluvia (¿acierta CUÁNDO llueve?).
    Se muestran juntos a propósito: un producto puede acertar el volumen
    acumulado y fallar los días, o al revés, y ninguna de las dos cosas
    sola basta para aceptarlo.

NOTA DE COMPATIBILIDAD: ver ui/hypsometric_canvas.py -- backend_qtagg
genérico, compatible con QGIS 3.x (Qt5) y 4.x (Qt6).
"""
import numpy as np

try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
except ImportError:
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from .chart_style import aplicar_estilo_graficos, leyenda_impacto

aplicar_estilo_graficos()


class RegionalizacionCanvas(FigureCanvas):

    def __init__(self, parent=None, width=7.4, height=4.8, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.ax = self.fig.add_subplot(111)
        super().__init__(self.fig)
        self.setParent(parent)
        self.setMinimumSize(int(width * dpi), int(height * dpi))

    def plot_regionalizacion(self, covariable, valores, nombres, modelo,
                             puntos_covariable=None, puntos_valores=None, puntos_nombres=None,
                             etiqueta_covariable="Altitud (m s.n.m.)",
                             etiqueta_variable="Precipitación (mm)"):
        """
        covariable / valores / nombres: datos de las estaciones.
        modelo: resultado de core.regionalization.regresion_regionalizacion()
            con UNA covariable -- se usan sus coeficientes para trazar la
            recta y su R² para el título.
        puntos_*: puntos estimados (sin estación), que se dibujan con
            otro símbolo para distinguirlos de los datos medidos.
        """
        self.fig.clear()
        self.ax = self.fig.add_subplot(111)
        x = np.asarray(covariable, dtype=float)
        y = np.asarray(valores, dtype=float)

        self.ax.scatter(x, y, s=62, color="#1F3864", edgecolor="white", linewidth=1.2,
                        zorder=4, label="Estaciones con dato medido")
        # Las etiquetas se alternan arriba/abajo siguiendo el orden de
        # altitud: con estaciones de cota parecida (lo habitual en una
        # misma cuenca) las anotaciones fijas se pisan entre sí.
        orden = np.argsort(x)
        for posicion, indice in enumerate(orden):
            desplazamiento = (7, 6) if posicion % 2 == 0 else (7, -13)
            self.ax.annotate(str(nombres[indice]), (x[indice], y[indice]),
                             textcoords="offset points", xytext=desplazamiento,
                             fontsize=7.5, color="#33415c")

        # El eje debe abarcar también los puntos a estimar: si uno cae
        # fuera del rango de las estaciones se está EXTRAPOLANDO, y eso
        # tiene que verse -- una recta que se corta antes del punto
        # estimado esconde justamente el riesgo que hay que comunicar.
        x_todo = list(x)
        if puntos_covariable is not None and len(puntos_covariable):
            x_todo += list(np.asarray(puntos_covariable, dtype=float))

        coef = modelo.get("_coeficientes_array")
        r2 = modelo.get("r2")
        if coef is not None and len(coef) >= 2:
            b0, b1 = float(coef[0]), float(coef[1])
            margen = 0.05 * ((max(x_todo) - min(x_todo)) or 1.0)
            x_recta = np.linspace(min(x_todo) - margen, max(x_todo) + margen, 100)
            y_recta = b0 + b1 * x_recta
            signo = "+" if b1 >= 0 else "−"
            self.ax.plot(x_recta, y_recta, "-", linewidth=2.2, color="#B3261E", zorder=3,
                         label=f"Tendencia regional:  y = {b0:.2f} {signo} {abs(b1):.4f}·x")

            # Banda de confianza al 95% de la RESPUESTA MEDIA:
            #     SE(x) = s * sqrt(1/n + (x - x̄)² / Sxx)
            # Se calcula con la fórmula exacta y no sumando en cuadratura
            # los errores estándar de b0 y b1: esos dos coeficientes
            # están fuertemente correlacionados (subir la pendiente baja
            # el intercepto), y sumarlos como independientes infla la
            # banda un orden de magnitud -- haría ver un ajuste excelente
            # como si no sirviera. La banda es correctamente estrecha en
            # el centro de los datos y se abre hacia los extremos, que es
            # justo lo que debe comunicar sobre la extrapolación.
            residuos_modelo = [r["residuo"] for r in (modelo.get("residuos") or {}).values()]
            n = len(x)
            if len(residuos_modelo) == n and n > 2:
                ss_res = float(np.sum(np.asarray(residuos_modelo, dtype=float) ** 2))
                s = np.sqrt(ss_res / (n - 2))
                sxx = float(np.sum((x - x.mean()) ** 2))
                if sxx > 0:
                    semiancho = 1.96 * s * np.sqrt(1.0 / n + (x_recta - x.mean()) ** 2 / sxx)
                    self.ax.fill_between(x_recta, y_recta - semiancho, y_recta + semiancho,
                                         color="#B3261E", alpha=0.16, zorder=1,
                                         label="Banda de confianza 95% de la tendencia")

            # Zonas de extrapolación: fuera del rango de covariable
            # cubierto por las estaciones, el modelo ya no está
            # respaldado por ningún dato medido. Se sombrean para que el
            # usuario no lea una estimación extrapolada como si tuviera
            # el mismo respaldo que una interpolada.
            primera_zona = True
            for inicio, fin in ((x_recta.min(), x.min()), (x.max(), x_recta.max())):
                if fin > inicio:
                    self.ax.axvspan(
                        inicio, fin, color="#8a5a00", alpha=0.07, zorder=0,
                        label="Zona de EXTRAPOLACIÓN (sin estaciones)" if primera_zona else None)
                    primera_zona = False

        if puntos_covariable is not None and puntos_valores is not None and len(puntos_covariable):
            px = np.asarray(puntos_covariable, dtype=float)
            py = np.asarray(puntos_valores, dtype=float)
            self.ax.scatter(px, py, s=110, marker="*", color="#2E7D32", edgecolor="white",
                            linewidth=1.0, zorder=5, label="Puntos estimados (sin estación)")
            if puntos_nombres:
                for xi, yi, nombre in zip(px, py, puntos_nombres):
                    self.ax.annotate(str(nombre), (xi, yi), textcoords="offset points",
                                     xytext=(6, -12), fontsize=7.5, color="#1B5E20",
                                     fontweight="bold")

        self.ax.set_xlabel(etiqueta_covariable)
        self.ax.set_ylabel(etiqueta_variable)
        titulo = "Regionalización: variable frente a covariable geográfica"
        if r2 is not None:
            titulo += f"   —   R² = {r2:.4f}"
        self.ax.set_title(titulo, pad=12)
        self.ax.grid(True, linestyle=":", linewidth=0.6)
        leyenda_impacto(self.ax, titulo="Elementos del ajuste", loc="best")
        self.fig.tight_layout()
        self.draw()

    def guardar_figura(self, ruta_png: str):
        self.fig.savefig(ruta_png, dpi=300, bbox_inches="tight")


class ValidacionGrilladaCanvas(FigureCanvas):

    def __init__(self, parent=None, width=8.4, height=4.4, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        super().__init__(self.fig)
        self.setParent(parent)
        self.setMinimumSize(int(width * dpi), int(height * dpi))

    def plot_validacion(self, sim, obs, continuas: dict, categoricas: dict = None,
                        nombre_producto="Producto grillado", nombre_estacion="Estación"):
        self.fig.clear()
        ejes = self.fig.subplots(1, 2) if categoricas else [self.fig.add_subplot(111)]
        ax1 = ejes[0]
        s = np.asarray(sim, dtype=float)
        o = np.asarray(obs, dtype=float)

        umbral = (categoricas or {}).get("umbral_mm")
        if umbral is not None:
            # Separar los pares por si superan el umbral de "día con
            # lluvia" hace visible el sesgo de detección en la misma
            # dispersión: los aciertos se agrupan lejos del origen.
            con_lluvia = (o >= umbral) | (s >= umbral)
            ax1.scatter(o[~con_lluvia], s[~con_lluvia], s=34, color="#9db4c8",
                        edgecolor="white", linewidth=0.7, zorder=3,
                        label=f"Pares bajo el umbral (< {umbral:g} mm)")
            ax1.scatter(o[con_lluvia], s[con_lluvia], s=48, color="#1F3864",
                        edgecolor="white", linewidth=0.8, zorder=4,
                        label=f"Pares con lluvia (≥ {umbral:g} mm)")
        else:
            ax1.scatter(o, s, s=48, color="#1F3864", edgecolor="white", linewidth=0.8,
                        zorder=4, label="Pares (observado, grillado)")

        lim_max = float(max(o.max(), s.max())) * 1.06 if len(o) else 1.0
        ax1.plot([0, lim_max], [0, lim_max], "--", linewidth=1.8, color="#B3261E", zorder=2,
                 label="Línea 1:1 (acuerdo perfecto)")
        ax1.set_xlim(0, lim_max)
        ax1.set_ylim(0, lim_max)
        ax1.set_xlabel(f"{nombre_estacion} — observado (mm)")
        ax1.set_ylabel(f"{nombre_producto} (mm)")
        nse = continuas.get("NSE")
        kge = continuas.get("KGE")
        ax1.set_title(
            "Magnitud: grillado vs. observado"
            + (f"\nNSE = {nse:.3f}" if nse is not None else "")
            + (f"   ·   KGE = {kge:.3f}" if kge is not None else ""), pad=10)
        ax1.grid(True, linestyle=":", linewidth=0.6)
        leyenda_impacto(ax1, titulo="Series comparadas", loc="upper left")

        if categoricas:
            ax2 = ejes[1]
            tabla = categoricas.get("tabla_contingencia", {})
            etiquetas = ["Aciertos\n(hits)", "Falsas\nalarmas", "Fallos\n(misses)",
                         "Correctos\nsin lluvia"]
            claves = ["aciertos_hits", "falsas_alarmas", "fallos_misses", "correctos_sin_lluvia"]
            # Verde = el producto acertó; rojo/naranja = falló. El color
            # traduce la tabla de contingencia sin tener que leerla.
            colores = ["#2E7D32", "#EF9F27", "#B3261E", "#7ba05b"]
            valores = [tabla.get(c, 0) for c in claves]
            barras = ax2.bar(etiquetas, valores, color=colores, edgecolor="#33415c",
                             linewidth=0.9, zorder=3)
            for barra, valor in zip(barras, valores):
                ax2.annotate(f"{valor}", (barra.get_x() + barra.get_width() / 2, barra.get_height()),
                             textcoords="offset points", xytext=(0, 4), ha="center",
                             fontsize=9.5, fontweight="bold", color="#1a1a1a")
            ax2.set_ylabel("Número de pasos de tiempo")
            pod = categoricas.get("POD")
            far = categoricas.get("FAR")
            hss = categoricas.get("HSS")
            resumen = "   ·   ".join(
                f"{nombre} = {valor:.3f}" for nombre, valor in
                (("POD", pod), ("FAR", far), ("HSS", hss)) if valor is not None)
            ax2.set_title(f"Detección de lluvia (umbral {categoricas.get('umbral_mm', 1):g} mm)"
                          + (f"\n{resumen}" if resumen else ""), pad=10)
            ax2.grid(True, axis="y", linestyle=":", linewidth=0.6)
            ax2.set_axisbelow(True)

        self.fig.tight_layout()
        self.draw()

    def guardar_figura(self, ruta_png: str):
        self.fig.savefig(ruta_png, dpi=300, bbox_inches="tight")
