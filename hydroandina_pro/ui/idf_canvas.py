# -*- coding: utf-8 -*-
"""
ui/idf_canvas.py

Gráfico de las curvas Intensidad-Duración-Frecuencia (IDF) de la
Pestaña 5 (Precipitación Máx 24h), en el formato estándar de
presentación de curvas IDF: escala log-log, una curva suavizada (ajuste
potencial i=a*t^b) por periodo de retorno, con los puntos calculados
superpuestos, ordenadas y coloreadas de menor a mayor Tr.

NOTA DE COMPATIBILIDAD: ver ui/hypsometric_canvas.py — backend_qtagg
genérico, compatible con QGIS 3.x (Qt5) y 4.x (Qt6).
"""
import numpy as np

try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
except ImportError:
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
import matplotlib
from matplotlib.figure import Figure


class IdfCanvas(FigureCanvas):

    def __init__(self, parent=None, width=7.6, height=5.2, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.ax = self.fig.add_subplot(111)
        super().__init__(self.fig)
        self.setParent(parent)
        # Ver comentario equivalente en ui/hypsometric_canvas.py: evita que
        # el QScrollArea deforme el gráfico al angostar la ventana.
        self.setMinimumSize(int(width * dpi), int(height * dpi))

    def plot_curvas_idf(self, datos_por_tr: dict, ecuaciones_por_tr: dict = None, escala_log: bool = True):
        """
        datos_por_tr: {Tr: [(duracion_min, intensidad_mm_h), ...], ...},
            como lo devuelve core.idf_curves.tabla_idf().
        ecuaciones_por_tr: {Tr: {'a', 'b', 'r2'}, ...} (opcional), como
            lo devuelve core.idf_curves.ajustar_ecuacion_potencial() por
            cada Tr -- si se pasa, se dibuja la curva suavizada del ajuste
            (i = a*t^b) además de los puntos calculados; si no, solo los
            puntos unidos por una línea recta.
        escala_log: True (por defecto) = ambos ejes en escala logarítmica
            (presentación estándar de curvas IDF, donde el ajuste potencial
            se ve como rectas paralelas). False = ambos ejes en escala
            cartesiana (lineal) -- útil para ver la forma real, muy
            curvada, de las mismas curvas (se concentran y "aplanan"
            rápido a duraciones largas, lo que en log-log no se aprecia).
        """
        self.ax.clear()
        trs_ordenados = sorted(datos_por_tr.keys())
        n = len(trs_ordenados)
        # Paleta ordenada de menor a mayor Tr (colores claros = Tr bajo,
        # oscuros/intensos = Tr alto), coherente con la idea de que un Tr
        # mayor es un evento más extremo/"intenso".
        # matplotlib >= 3.9 eliminó matplotlib.cm.get_cmap();
        # matplotlib.colormaps[...] es la forma nueva (disponible desde
        # 3.5). Respaldo a cm.get_cmap() solo por si corre con una
        # versión de matplotlib más vieja empaquetada con QGIS.
        try:
            mapa_color = matplotlib.colormaps["viridis"]
        except AttributeError:
            from matplotlib import cm
            mapa_color = cm.get_cmap("viridis")
        colores = mapa_color(np.linspace(0.85, 0.05, max(n, 1)))

        t_min_global = min(d for curva in datos_por_tr.values() for d, _ in curva)
        t_max_global = max(d for curva in datos_por_tr.values() for d, _ in curva)
        t_denso = np.geomspace(t_min_global, t_max_global, 100) if escala_log else \
            np.linspace(t_min_global, t_max_global, 100)

        for idx, tr in enumerate(trs_ordenados):
            curva = sorted(datos_por_tr[tr], key=lambda p: p[0])
            t_pts = np.array([p[0] for p in curva])
            i_pts = np.array([p[1] for p in curva])
            color = colores[idx]

            etiqueta = f"Tr = {tr} años"
            if ecuaciones_por_tr and tr in ecuaciones_por_tr:
                eq = ecuaciones_por_tr[tr]
                i_denso = eq["a"] * (t_denso ** eq["b"])
                self.ax.plot(t_denso, i_denso, "-", linewidth=1.8, color=color, zorder=2, label=etiqueta)
                self.ax.scatter(t_pts, i_pts, s=14, color=color, zorder=3, edgecolor="none")
            else:
                self.ax.plot(t_pts, i_pts, "-o", linewidth=1.5, markersize=3.5, color=color,
                              zorder=2, label=etiqueta)

        if escala_log:
            self.ax.set_xscale("log")
            self.ax.set_yscale("log")
            self.ax.set_xlabel("Duración (min, escala log)")
            self.ax.set_ylabel("Intensidad (mm/h, escala log)")
            titulo = "Curvas Intensidad-Duración-Frecuencia (IDF) — escala log-log"
            self.ax.grid(True, which="major", linestyle=":", linewidth=0.6, color="#999999")
            self.ax.grid(True, which="minor", linestyle=":", linewidth=0.35, color="#cccccc")
        else:
            self.ax.set_xscale("linear")
            self.ax.set_yscale("linear")
            self.ax.set_xlabel("Duración (min, escala cartesiana)")
            self.ax.set_ylabel("Intensidad (mm/h, escala cartesiana)")
            titulo = "Curvas Intensidad-Duración-Frecuencia (IDF) — escala cartesiana"
            self.ax.grid(True, linestyle=":", linewidth=0.5)
        self.ax.set_title(titulo, pad=12)
        # Leyenda ordenada de menor a mayor Tr (el orden de graficación ya
        # es ascendente, así que el orden por defecto de la leyenda ya
        # sale correcto sin reordenar aparte).
        self.ax.legend(fontsize=7.5, loc="upper center", bbox_to_anchor=(0.5, -0.14),
                        ncol=min(n, 5) or 1, frameon=False)
        self.fig.tight_layout()
        self.draw()

    def plot_comparacion_metodos_idf(self, resultados_por_metodo: dict, tr_referencia: int,
                                      escala_log: bool = True):
        """
        Compara las curvas IDF que producen los distintos métodos para UN
        periodo de retorno, que es la forma de ver cuánto difieren entre
        sí: superponer todas las curvas de todos los Tr sería ilegible.
        """
        self.fig.clear()
        self.ax = self.fig.add_subplot(111)
        colores = {"sherman": "#1F3864", "dyck_peschke": "#2E7D32",
                   "bell": "#B3261E", "iila": "#8B5CF6"}
        estilos = {"sherman": "-", "dyck_peschke": "--", "bell": "-.", "iila": ":"}

        for clave, datos in resultados_por_metodo.items():
            curvas = datos.get("curvas") or {}
            if tr_referencia not in curvas:
                continue
            puntos = curvas[tr_referencia]
            if not puntos:
                continue
            self.ax.plot([d for d, _ in puntos], [i for _, i in puntos],
                         estilos.get(clave, "-"), linewidth=2.0, marker="o", markersize=3.5,
                         color=colores.get(clave, "#666666"), label=datos.get("nombre", clave))

        if escala_log:
            self.ax.set_xscale("log")
            self.ax.set_yscale("log")
            self.ax.set_xlabel("Duración (min, escala log)")
            self.ax.set_ylabel("Intensidad (mm/h, escala log)")
        else:
            self.ax.set_xlabel("Duración (min)")
            self.ax.set_ylabel("Intensidad (mm/h)")
        self.ax.set_title(
            f"Comparación de métodos de generación de curvas IDF — Tr = {tr_referencia} años", pad=12)
        self.ax.grid(True, which="both", linestyle=":", linewidth=0.5)
        self.ax.legend(fontsize=8, loc="upper right", framealpha=0.9)
        self.fig.tight_layout()
        self.draw()

    def guardar_figura(self, ruta_png: str):
        """Exporta las curvas IDF actualmente dibujadas a un PNG de alta
        resolución (300 dpi), para incluir en el expediente técnico."""
        self.fig.savefig(ruta_png, dpi=300, bbox_inches="tight")
