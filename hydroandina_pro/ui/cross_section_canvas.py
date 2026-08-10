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

    def plot_riprap_talud(self, velocidad_m_s, d50_m, angulo_talud_deg=33.7):
        """Esquema de un talud protegido con enrocado (RipRap): la capa de
        roca (espesor ~2xD50, práctica estándar) sobre el talud, con la
        velocidad de diseño y el D50 anotados. `angulo_talud_deg` es solo
        para el dibujo (33.7° = talud 1.5H:1V, un valor típico ilustrativo,
        no calculado -- el diseño geotécnico del talud está fuera de este
        plugin)."""
        self.ax.clear()
        self.ax.set_xlabel("Distancia horizontal (m)")
        self.ax.set_ylabel("Altura (m)")
        self.ax.set_title("Enrocado de protección (RipRap) — esquema del talud", pad=14)
        self.ax.grid(True, linestyle=":", linewidth=0.5)

        alto_talud = max(1.5, 6 * d50_m)
        ancho_talud = alto_talud / math.tan(math.radians(angulo_talud_deg))
        espesor_capa = 2 * d50_m  # práctica estándar: espesor mínimo = 2xD50

        # Talud natural (línea) y capa de enrocado (franja paralela hacia
        # afuera, desplazada por la normal unitaria a la línea del talud).
        # Para una línea que baja de (0, alto) a (ancho, 0), el vector
        # unitario "cuesta abajo" es (cos a, -sin a) (a = ángulo con la
        # horizontal); su normal hacia afuera del talud (rotado 90°) es
        # (sin a, cos a) -- ambos unitarios, así que desplazar por
        # `espesor_capa` a lo largo de esa normal ya da la franja paralela
        # correcta, sin necesidad de más trigonometría.
        a = math.radians(angulo_talud_deg)
        normal = (math.sin(a), math.cos(a))
        xs_talud = [0, ancho_talud]
        zs_talud = [alto_talud, 0]
        self.ax.plot(xs_talud, zs_talud, "-", color="#6B4A2F", linewidth=2, zorder=3, label="Talud")
        xs_capa = [x + espesor_capa * normal[0] for x in xs_talud]
        zs_capa = [z + espesor_capa * normal[1] for z in zs_talud]
        self.ax.fill(xs_talud + list(reversed(xs_capa)), zs_talud + list(reversed(zs_capa)),
                     color="#9C9C9C", alpha=0.6, zorder=2, label=f"Enrocado (espesor ≈ {espesor_capa:.2f} m)")

        # Rocas esquemáticas (círculos ≈D50) a media capa, siguiendo el talud
        n_rocas = 6
        xs_rocas, zs_rocas = [], []
        for i in range(n_rocas):
            frac = (i + 0.5) / n_rocas
            x_base = xs_talud[0] + frac * (xs_talud[1] - xs_talud[0])
            z_base = zs_talud[0] + frac * (zs_talud[1] - zs_talud[0])
            xs_rocas.append(x_base + (espesor_capa / 2) * normal[0])
            zs_rocas.append(z_base + (espesor_capa / 2) * normal[1])
        self.ax.scatter(xs_rocas, zs_rocas, s=max(80, d50_m * 3000), color="#5C5C5C",
                         edgecolor="#333333", zorder=4)

        self.ax.annotate(f"D50 = {d50_m * 100:.1f} cm", (xs_talud[1] * 0.5, zs_talud[0] * 0.55),
                          ha="center", fontsize=9,
                          bbox=dict(boxstyle="round", fc="white", ec="#5C5C5C", alpha=0.85))
        self.ax.annotate(f"V diseño = {velocidad_m_s:.2f} m/s →", (ancho_talud * 0.15, alto_talud * 0.08),
                          ha="left", fontsize=9, color="#1F6FB2")
        self.ax.set_xlim(-0.1 * ancho_talud, ancho_talud * 1.25)
        self.ax.set_ylim(-0.1 * alto_talud, (alto_talud + espesor_capa) * 1.15)
        self.ax.set_aspect("equal", adjustable="box")
        self.fig.tight_layout()
        self.draw()

    def plot_ventana_sumidero(self, largo_m, tirante_m, caudal_m3_s):
        """Esquema de la ventana/reja de un sumidero (vertedero lateral),
        con L (largo), y (tirante sobre la ventana) y el caudal interceptado
        calculado."""
        self._preparar_ejes("Sumidero — ventana de captación (esquema)")
        xs_marco = [0, 0, largo_m, largo_m]
        zs_marco = [tirante_m * 1.6, 0, 0, tirante_m * 1.6]
        self.ax.plot(xs_marco, zs_marco, "-", color="#3B3B3B", linewidth=2, zorder=3)
        # lámina de agua entrando por la ventana
        self.ax.fill_between([0, largo_m], [0, 0], [tirante_m, tirante_m],
                              color="#8FCBEA", alpha=0.6, zorder=1)
        self.ax.plot([0, largo_m], [tirante_m, tirante_m], "--", color="#1F6FB2", linewidth=1.4, zorder=2)
        self.ax.annotate(f"L = {largo_m:.2f} m", (largo_m / 2, -0.06 * tirante_m * 1.6),
                          ha="center", va="top", fontsize=9)
        self.ax.annotate(f"y = {tirante_m:.3f} m", (largo_m * 0.03, tirante_m / 2),
                          ha="left", va="center", fontsize=9)
        self.ax.annotate(f"Q interceptado = {caudal_m3_s:.4f} m³/s", (largo_m / 2, tirante_m * 1.3),
                          ha="center", fontsize=9,
                          bbox=dict(boxstyle="round", fc="white", ec="#1F6FB2", alpha=0.85))
        self.ax.set_xlim(-0.05 * largo_m, largo_m * 1.05)
        self.fig.tight_layout()
        self.draw()

    def plot_borde_libre(self, cota_agua, cota_estructura, borde_libre_min, nombre_estructura, cumple):
        """Esquema vertical de la verificación de borde libre: nivel de agua
        de diseño, cota inferior de la estructura (o corona, para defensas
        ribereñas), y el borde libre disponible vs. el mínimo requerido,
        coloreado en verde si cumple o rojo si no."""
        self.ax.clear()
        self.ax.set_ylabel("Cota (m s.n.m.)")
        self.ax.set_xticks([])
        estado = "CUMPLE" if cumple else "NO CUMPLE"
        color_estado = "#1E8449" if cumple else "#B3261E"
        self.ax.set_title(f"{nombre_estructura} — verificación de borde libre  [{estado}]",
                           pad=14, color=color_estado)
        self.ax.grid(True, axis="y", linestyle=":", linewidth=0.5)

        borde_libre_disponible = cota_estructura - cota_agua
        z_base = cota_agua - max(0.5, 0.3 * abs(borde_libre_disponible))
        z_top = cota_estructura + max(0.5, 0.3 * abs(borde_libre_disponible))
        ancho = 1.0

        # Agua (relleno celeste hasta la cota de agua)
        self.ax.fill_between([0, ancho], [z_base, z_base], [cota_agua, cota_agua],
                              color="#8FCBEA", alpha=0.6, zorder=1)
        self.ax.plot([0, ancho], [cota_agua, cota_agua], "-", color="#1F6FB2", linewidth=2, zorder=3)
        self.ax.annotate(f"Nivel de agua de diseño = {cota_agua:.2f} m s.n.m.",
                          (ancho * 1.05, cota_agua), va="center", fontsize=9, color="#1F6FB2")

        # Cota de la estructura (superestructura/corona)
        self.ax.plot([0, ancho], [cota_estructura, cota_estructura], "-", color=color_estado, linewidth=2.5, zorder=3)
        self.ax.annotate(f"{nombre_estructura} = {cota_estructura:.2f} m s.n.m.",
                          (ancho * 1.05, cota_estructura), va="center", fontsize=9, color=color_estado)

        # Flecha del borde libre disponible entre ambos niveles
        self.ax.annotate(
            "", xy=(ancho * 0.5, cota_estructura), xytext=(ancho * 0.5, cota_agua),
            arrowprops=dict(arrowstyle="<->", color="#333333", linewidth=1.3),
        )
        self.ax.annotate(
            f"BL disponible = {borde_libre_disponible:.2f} m\n(mínimo requerido = {borde_libre_min:.2f} m)",
            (ancho * 0.5, (cota_agua + cota_estructura) / 2), ha="left", va="center", fontsize=8.5,
            xytext=(ancho * 0.62, (cota_agua + cota_estructura) / 2),
            bbox=dict(boxstyle="round", fc="white", ec=color_estado, alpha=0.9),
        )

        self.ax.set_xlim(-0.1, ancho * 2.3)
        self.ax.set_ylim(z_base, z_top)
        self.fig.tight_layout()
        self.draw()
