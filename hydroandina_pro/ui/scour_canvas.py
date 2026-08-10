# -*- coding: utf-8 -*-
"""
ui/scour_canvas.py

Gráficos de alto impacto visual de la Pestaña "Socavación":
  1) Sección transversal CON y SIN socavación (fondo original vs. fondo
     socavado, nivel de agua, relleno diferenciado y etiqueta de la
     profundidad máxima de socavación).
  2) Curva granulométrica con D16/D35/D50/D65/D84/D90 marcados.
  3) Comparación de profundidad de socavación entre métodos (barras con
     etiquetas de valor), incluyendo el método gobernante resaltado.

Misma convención visual que el resto del plugin (backend_qtagg / qt5agg,
grid punteado fino, tight_layout, leyenda fuera del área de dibujo).
"""
import math

try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
except ImportError:
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure


class ScourCanvas(FigureCanvas):

    def __init__(self, parent=None, width=7.4, height=5.2, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.ax = self.fig.add_subplot(111)
        super().__init__(self.fig)
        self.setParent(parent)
        self.setMinimumSize(int(width * dpi), int(height * dpi))

    # ------------------------------------------------------------------
    # 1) Sección con / sin socavación
    # ------------------------------------------------------------------
    def plot_seccion_socavacion(self, estaciones, elevaciones_originales, elevaciones_socavadas,
                                 nivel_agua, nombre_seccion="", nombre_metodo="",
                                 estacion_local=None, ys_local=None, ancho_pila=None):
        """Dibuja el fondo original (línea café continua), el fondo
        socavado (línea roja discontinua) con relleno diferenciado entre
        ambos, el nivel de agua de diseño, y si se pasa una socavación
        LOCAL (pilar) la fosa puntual sobrepuesta en su estación."""
        self.ax.clear()
        est = list(estaciones)
        orig = list(elevaciones_originales)
        soc = list(elevaciones_socavadas)

        self.ax.plot(est, orig, "-", color="#6B4A2E", linewidth=2.4, zorder=4,
                     label="Fondo original (sin socavación)")
        self.ax.plot(est, soc, "--", color="#C0272D", linewidth=2.2, zorder=5,
                     label="Fondo socavado (" + nombre_metodo + ")" if nombre_metodo else "Fondo socavado")

        # relleno de la zona erosionada
        self.ax.fill_between(est, orig, soc, where=[s < o for s, o in zip(soc, orig)],
                              color="#F2B6B8", alpha=0.65, zorder=2, label="Zona erosionada")

        # nivel de agua
        x_izq, x_der = min(est), max(est)
        self.ax.plot([x_izq, x_der], [nivel_agua, nivel_agua], "-.", color="#1F6FB2",
                     linewidth=1.6, zorder=3, label="Nivel de agua de diseño")
        self.ax.fill_between(est, orig, nivel_agua, where=[o <= nivel_agua for o in orig],
                              color="#BEE0F5", alpha=0.45, zorder=1)

        # fosa local sobrepuesta (pilar/estribo), si aplica
        if estacion_local is not None and ys_local is not None:
            ancho = ancho_pila if ancho_pila else (x_der - x_izq) * 0.05
            elev_fondo_local = min(soc) if soc else min(orig)
            n = 40
            xs_fosa, zs_fosa = [], []
            for i in range(n + 1):
                frac = -1 + 2 * i / n
                x = estacion_local + frac * ancho * 1.5
                z = elev_fondo_local - ys_local * (1 - frac ** 2)
                xs_fosa.append(x)
                zs_fosa.append(z)
            self.ax.plot(xs_fosa, zs_fosa, ":", color="#7A1712", linewidth=2.0, zorder=6,
                         label=f"Fosa de socavación local (ys = {ys_local:.2f} m)")
            self.ax.annotate(f"ys local = {ys_local:.2f} m", (estacion_local, elev_fondo_local - ys_local),
                             xytext=(0, -16), textcoords="offset points", ha="center", fontsize=8,
                             fontweight="bold", color="#7A1712",
                             bbox=dict(boxstyle="round", fc="white", ec="#7A1712", alpha=0.9))

        # etiqueta de socavación máxima general
        if soc and orig:
            profundidades = [o - s for o, s in zip(orig, soc)]
            idx_max = max(range(len(profundidades)), key=lambda i: profundidades[i])
            if profundidades[idx_max] > 1e-3:
                self.ax.annotate(
                    f"ds máx = {profundidades[idx_max]:.2f} m\n(estación {est[idx_max]:.1f} m)",
                    (est[idx_max], soc[idx_max]), xytext=(12, -22), textcoords="offset points",
                    ha="left", fontsize=8.5, fontweight="bold", color="#7A1712",
                    arrowprops=dict(arrowstyle="->", color="#7A1712"),
                    bbox=dict(boxstyle="round", fc="white", ec="#7A1712", alpha=0.92))

        titulo = "Sección transversal con y sin socavación"
        if nombre_seccion:
            titulo += f" — {nombre_seccion}"
        self.ax.set_title(titulo, pad=14, fontsize=11, fontweight="bold")
        self.ax.set_xlabel("Estación (m)")
        self.ax.set_ylabel("Elevación (m s.n.m.)")
        self.ax.grid(True, linestyle=":", linewidth=0.5)
        self.ax.legend(fontsize=7.5, loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=2, frameon=False)
        self.fig.tight_layout()
        self.draw()

    # ------------------------------------------------------------------
    # 2) Curva granulométrica
    # ------------------------------------------------------------------
    def plot_curva_granulometrica(self, curva_ordenada, diametros_caracteristicos):
        self.ax.clear()
        diam = [p[0] for p in curva_ordenada]
        pasa = [p[1] for p in curva_ordenada]
        self.ax.semilogx(diam, pasa, "-o", color="#1F3864", linewidth=2.0, markersize=4,
                          zorder=3, label="Curva granulométrica")

        colores = {"D16": "#2E7D32", "D35": "#00897B", "D50": "#C0272D",
                   "D65": "#7A1712", "D84": "#B3261E", "D90": "#8B5CF6"}
        for clave, color in colores.items():
            d = diametros_caracteristicos.get(clave)
            if d is None:
                continue
            pct = int(clave[1:])
            self.ax.axvline(d, color=color, linestyle="--", linewidth=1.0, alpha=0.8, zorder=1)
            self.ax.annotate(f"{clave} = {d:.3f} mm", (d, pct), xytext=(6, 4),
                             textcoords="offset points", fontsize=7.5, color=color, fontweight="bold")
            self.ax.plot([d], [pct], "s", color=color, markersize=6, zorder=4)

        self.ax.set_xlabel("Diámetro de partícula (mm, escala log)")
        self.ax.set_ylabel("Porcentaje que pasa (%)")
        self.ax.set_title("Curva granulométrica del material del lecho", pad=14, fontsize=11, fontweight="bold")
        self.ax.set_ylim(0, 100)
        self.ax.grid(True, which="both", linestyle=":", linewidth=0.5)
        sigma_g = diametros_caracteristicos.get("sigma_g")
        if sigma_g and not math.isnan(sigma_g):
            self.ax.text(0.02, 0.94, f"Dm = {diametros_caracteristicos.get('Dm', 0):.3f} mm\n"
                                      f"σg = {sigma_g:.2f}",
                         transform=self.ax.transAxes, fontsize=8.5,
                         bbox=dict(boxstyle="round", fc="#F4F4F4", ec="#999999"))
        self.fig.tight_layout()
        self.draw()

    # ------------------------------------------------------------------
    # 3) Comparación entre métodos
    # ------------------------------------------------------------------
    def plot_comparacion_metodos(self, nombres_metodos, profundidades_m, metodo_gobernante=None):
        self.ax.clear()
        colores = ["#7A1712" if nm == metodo_gobernante else "#1F6FB2" for nm in nombres_metodos]
        barras = self.ax.bar(range(len(nombres_metodos)), profundidades_m, color=colores,
                              edgecolor="black", linewidth=0.6, zorder=3)
        for i, (barra, valor) in enumerate(zip(barras, profundidades_m)):
            self.ax.annotate(f"{valor:.2f} m", (barra.get_x() + barra.get_width() / 2, valor),
                             xytext=(0, 4), textcoords="offset points", ha="center",
                             fontsize=8.5, fontweight="bold")
        self.ax.set_xticks(range(len(nombres_metodos)))
        self.ax.set_xticklabels(nombres_metodos, rotation=28, ha="right", fontsize=8)
        self.ax.set_ylabel("Profundidad de socavación (m)")
        titulo = "Comparación de profundidad de socavación entre métodos"
        if metodo_gobernante:
            titulo += f"\n(gobernante: {metodo_gobernante})"
        self.ax.set_title(titulo, pad=14, fontsize=10.5, fontweight="bold")
        self.ax.grid(True, axis="y", linestyle=":", linewidth=0.5)
        self.fig.tight_layout()
        self.draw()
