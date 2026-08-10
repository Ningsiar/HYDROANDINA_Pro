# -*- coding: utf-8 -*-
"""
ui/cross_section_canvas.py

Gráfico de la sección transversal de la estructura hidráulica calculada
en la Pestaña 7 (canales, alcantarillas), con relación de escala 1:1
entre el eje X (ancho) y el eje Y (altura) — indispensable para que la
forma dibujada (trapecio, triángulo, parábola, círculo parcial, etc.) se
vea geométricamente correcta y no distorsionada, y con etiquetas de las
dimensiones principales (b, z, y, T, D) directamente sobre el dibujo.
"""
import math

try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
except ImportError:
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure


class SeccionTransversalCanvas(FigureCanvas):

    def __init__(self, parent=None, width=6, height=4.6, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.ax = self.fig.add_subplot(111)
        super().__init__(self.fig)
        self.setParent(parent)
        self.setMinimumSize(int(width * dpi), int(height * dpi))

    def _preparar_ejes(self, titulo):
        self.ax.clear()
        self.ax.set_aspect("equal", adjustable="datalim")  # relación de escala 1:1 entre X e Y
        self.ax.set_xlabel("Ancho (m)")
        self.ax.set_ylabel("Altura (m)")
        self.ax.set_title(titulo, pad=14)
        # Margen superior extra: varias etiquetas de dimensiones (b, z, T,
        # D) se colocan justo encima del nivel de agua/fondo; sin este
        # margen podían quedar muy pegadas al título.
        self.ax.margins(y=0.18)
        self.ax.grid(True, linestyle=":", linewidth=0.5)

    def _dibujar_fondo_y_agua(self, xs_fondo, zs_fondo, y_agua, z_min):
        """Dibuja el contorno del fondo del canal y la superficie libre del
        agua (nivel y_agua sobre z_min), con relleno celeste bajo el agua."""
        self.ax.plot(xs_fondo, zs_fondo, "-", color="#3B3B3B", linewidth=2, zorder=3)
        nivel = z_min + y_agua
        x_izq, x_der = min(xs_fondo), max(xs_fondo)
        self.ax.plot([x_izq, x_der], [nivel, nivel], "--", color="#1F6FB2", linewidth=1.4, zorder=2)
        self.ax.fill_between(xs_fondo, zs_fondo, nivel, where=[z <= nivel for z in zs_fondo],
                              color="#8FCBEA", alpha=0.55, zorder=1)

    def plot_rectangular(self, b, y):
        self._preparar_ejes("Sección rectangular (máx. eficiencia)")
        xs = [0, 0, b, b]
        zs = [y * 1.15, 0, 0, y * 1.15]
        self._dibujar_fondo_y_agua(xs, zs, y, 0)
        self.ax.annotate(f"b = {b:.2f} m", (b / 2, -0.04 * y), ha="center", va="top", fontsize=9)
        self.ax.annotate(f"y = {y:.2f} m", (-0.06 * b, y / 2), ha="right", va="center", fontsize=9, rotation=90)
        self.fig.tight_layout()
        self.draw()

    def plot_triangular(self, z, y):
        self._preparar_ejes("Sección triangular (máx. eficiencia, z=1)")
        xs = [-z * y * 1.15, 0, z * y * 1.15]
        zs = [y * 1.15, 0, y * 1.15]
        self._dibujar_fondo_y_agua(xs, zs, y, 0)
        self.ax.annotate(f"z = {z:.2f} (H:V)", (0, y * 1.05), ha="center", va="bottom", fontsize=9)
        self.ax.annotate(f"y = {y:.2f} m", (z * y * 0.5, y / 2), ha="left", va="center", fontsize=9)
        self.fig.tight_layout()
        self.draw()

    def plot_trapezoidal(self, b, z, y, titulo="Sección trapezoidal"):
        self._preparar_ejes(titulo)
        x_top = b / 2 + z * y
        xs = [-x_top * 1.1, -b / 2 - z * y, -b / 2, b / 2, b / 2 + z * y, x_top * 1.1]
        zs = [y * 1.15, y, 0, 0, y, y * 1.15]
        self._dibujar_fondo_y_agua(xs, zs, y, 0)
        self.ax.annotate(f"b = {b:.2f} m", (0, -0.04 * y), ha="center", va="top", fontsize=9)
        self.ax.annotate(f"z = {z:.2f} (H:V)", (b / 2 + z * y / 2, y / 2), ha="left", va="center", fontsize=9)
        self.ax.annotate(f"y = {y:.2f} m", (-b / 2 - z * y * 0.6, y / 2), ha="right", va="center", fontsize=9)
        self.fig.tight_layout()
        self.draw()

    def plot_parabolico(self, t, y):
        self._preparar_ejes("Sección parabólica")
        n_pts = 60
        xs, zs = [], []
        for i in range(n_pts + 1):
            frac = i / n_pts  # 0..1 a lo largo de la mitad derecha
            x = (t / 2) * frac
            z = y * (frac ** 2)
            xs.append(x)
            zs.append(z)
        xs_completo = [-x for x in reversed(xs)] + xs
        zs_completo = list(reversed(zs)) + zs
        self._dibujar_fondo_y_agua(xs_completo, zs_completo, y, 0)
        self.ax.annotate(f"T = {t:.2f} m", (0, y * 1.08), ha="center", va="bottom", fontsize=9)
        self.ax.annotate(f"y = {y:.2f} m", (0, y / 2), ha="center", va="center", fontsize=9,
                          bbox=dict(boxstyle="round", fc="white", ec="none", alpha=0.7))
        self.fig.tight_layout()
        self.draw()

    def plot_irregular(self, puntos_estacion_elevacion, y):
        self._preparar_ejes("Sección irregular (dada por el usuario)")
        xs = [p[0] for p in puntos_estacion_elevacion]
        zs = [p[1] for p in puntos_estacion_elevacion]
        z_min = min(zs)
        self._dibujar_fondo_y_agua(xs, zs, y, z_min)
        self.ax.annotate(f"y = {y:.2f} m (sobre el punto más bajo)", (xs[0], z_min + y * 1.05),
                          ha="left", va="bottom", fontsize=9)
        self.fig.tight_layout()
        self.draw()

    def plot_circular(self, diametro, y):
        self._preparar_ejes("Sección circular (alcantarilla)")
        r = diametro / 2
        angulos = [i * math.pi / 100 for i in range(201)]
        xs = [r * math.sin(a) for a in angulos]
        zs = [r - r * math.cos(a) for a in angulos]
        self._dibujar_fondo_y_agua(xs, zs, y, 0)
        self.ax.annotate(f"D = {diametro:.2f} m", (0, diametro * 1.05), ha="center", va="bottom", fontsize=9)
        self.ax.annotate(f"y = {y:.2f} m", (r * 1.1, y / 2), ha="left", va="center", fontsize=9)
        self.fig.tight_layout()
        self.draw()

    def plot_cajon(self, ancho, alto_max, y):
        self._preparar_ejes("Sección rectangular (alcantarilla cajón)")
        xs = [0, 0, ancho, ancho]
        zs = [alto_max, 0, 0, alto_max]
        self._dibujar_fondo_y_agua(xs, zs, y, 0)
        self.ax.annotate(f"ancho = {ancho:.2f} m", (ancho / 2, -0.04 * alto_max), ha="center", va="top", fontsize=9)
        self.ax.annotate(f"y = {y:.2f} m", (-0.06 * ancho, y / 2), ha="right", va="center", fontsize=9, rotation=90)
        self.fig.tight_layout()
        self.draw()
