# -*- coding: utf-8 -*-
"""
ui/swe2d_canvas.py

Gráficos de la Pestaña 8 (Simulación Hidráulica 2D de Estructuras).

Son cuatro lienzos con propósitos distintos, y esa separación es
deliberada: un único gráfico que intente mostrar mapa, evolución y
balance a la vez no permite leer bien ninguno de los tres.

  * MapaCalado2DCanvas — mapa de calados máximos con el relieve
    sombreado debajo, para situar la mancha de inundación sobre el
    terreno real y no sobre un fondo plano.
  * MapaPeligrosidadCanvas — clasificación h·v por umbrales de la guía
    FD2320, con el reparto de área por clase al lado.
  * HidrogramasSwe2DCanvas — caudales de entrada y salida, volumen
    almacenado y área inundada frente al tiempo: es lo que dice si la
    simulación llegó a régimen y si el balance cierra.
  * PerfilSwe2DCanvas — corte longitudinal o transversal con fondo,
    lámina de agua y calado, que es la vista con la que un proyectista
    comprueba un resguardo o el calado sobre una obra de paso.

NOTA DE COMPATIBILIDAD: ver ui/hypsometric_canvas.py -- backend_qtagg
genérico, compatible con QGIS 3.x (Qt5) y 4.x (Qt6).
"""
import numpy as np

try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
except ImportError:
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
import matplotlib
from matplotlib.figure import Figure
from matplotlib.colors import ListedColormap, BoundaryNorm
from matplotlib.patches import Patch

from .chart_style import aplicar_estilo_graficos, leyenda_impacto

aplicar_estilo_graficos()


def _mapa_color(nombre):
    """matplotlib >= 3.9 eliminó cm.get_cmap(); colormaps[...] es la
    forma nueva. Se mantiene el respaldo por si QGIS trae una versión
    más antigua."""
    try:
        return matplotlib.colormaps[nombre]
    except AttributeError:                        # pragma: sin cobertura
        from matplotlib import cm
        return cm.get_cmap(nombre)


def _relieve_sombreado(zb, dx, dy):
    """
    Sombreado analítico del relieve (azimut 315°, elevación 45°), la
    iluminación convencional de la cartografía. Se dibuja bajo la
    mancha de agua para que el mapa se lea como un terreno y no como
    una silueta: sin él, no hay forma de saber si el agua sigue un
    cauce o se está desparramando por una ladera.
    """
    z = np.where(np.isfinite(zb), zb, np.nan)
    dzdy, dzdx = np.gradient(np.nan_to_num(z, nan=float(np.nanmean(z))), dy, dx)
    pendiente = np.pi / 2.0 - np.arctan(np.hypot(dzdx, dzdy))
    aspecto = np.arctan2(-dzdx, dzdy)
    azimut, altura = np.radians(315.0), np.radians(45.0)
    sombra = (np.sin(altura) * np.sin(pendiente) +
              np.cos(altura) * np.cos(pendiente) * np.cos(azimut - aspecto))
    return np.clip(sombra, 0, 1)


class MapaCalado2DCanvas(FigureCanvas):

    def __init__(self, parent=None, width=7.6, height=5.6, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.ax = self.fig.add_subplot(111)
        super().__init__(self.fig)
        self.setParent(parent)
        self.setMinimumSize(int(width * dpi), int(height * dpi))

    def plot_mapa(self, h_max, zb, dx, dy, activo=None, entradas=None,
                  estructuras=None, titulo="Calado máximo (m)",
                  etiqueta_barra="Calado máximo (m)"):
        self.fig.clear()
        self.ax = self.fig.add_subplot(111)
        filas, columnas = h_max.shape
        extension = [0, columnas * dx, 0, filas * dy]

        sombra = _relieve_sombreado(np.where(activo, zb, np.nan) if activo is not None else zb,
                                    dx, dy)
        self.ax.imshow(sombra, cmap="gray", extent=extension, origin="upper",
                       vmin=0, vmax=1, alpha=0.85, zorder=1)

        # Solo se pinta el agua donde realmente la hay: enmascarar las
        # celdas secas evita que una lámina de milímetros tiña de azul
        # todo el dominio y exagere la inundación.
        agua = np.ma.masked_where(h_max <= 1e-3, h_max)
        if activo is not None:
            agua = np.ma.masked_where(~activo, agua)
        imagen = self.ax.imshow(agua, cmap=_mapa_color("Blues"), extent=extension,
                                origin="upper", zorder=2, alpha=0.92)
        barra = self.fig.colorbar(imagen, ax=self.ax, shrink=0.82, pad=0.02)
        barra.set_label(etiqueta_barra, fontsize=9.5)

        if entradas:
            for e in entradas:
                x = (e["columna"] + 0.5) * dx
                y = (filas - e["fila"] - 0.5) * dy
                self.ax.plot(x, y, marker="v", markersize=11, color="#2E7D32",
                             markeredgecolor="white", markeredgewidth=1.2, zorder=5,
                             label="Entrada de caudal")
        if estructuras:
            for est in estructuras:
                f1, c1 = est.celda_1
                f2, c2 = est.celda_2
                xs = [(c1 + 0.5) * dx, (c2 + 0.5) * dx]
                ys = [(filas - f1 - 0.5) * dy, (filas - f2 - 0.5) * dy]
                self.ax.plot(xs, ys, "-", linewidth=3.0, color="#B3261E", zorder=6,
                             label="Estructura hidráulica")
                self.ax.plot(np.mean(xs), np.mean(ys), marker="s", markersize=8,
                             color="#B3261E", markeredgecolor="white",
                             markeredgewidth=1.2, zorder=7)

        self.ax.set_xlabel("Distancia X (m)")
        self.ax.set_ylabel("Distancia Y (m)")
        self.ax.set_title(titulo, pad=12)

        # Una sola entrada por tipo en la leyenda, aunque haya varias
        # entradas o estructuras dibujadas.
        manejadores, etiquetas = self.ax.get_legend_handles_labels()
        vistos, m_unicos, e_unicos = set(), [], []
        for m, e in zip(manejadores, etiquetas):
            if e not in vistos:
                vistos.add(e)
                m_unicos.append(m)
                e_unicos.append(e)
        if e_unicos:
            leyenda = self.ax.legend(m_unicos, e_unicos, title="Elementos del modelo",
                                     loc="upper right")
            leyenda.get_title().set_fontweight("bold")
            leyenda.get_frame().set_linewidth(1.4)
        self.fig.tight_layout()
        self.draw()

    def guardar_figura(self, ruta_png):
        self.fig.savefig(ruta_png, dpi=300, bbox_inches="tight")


class MapaPeligrosidadCanvas(FigureCanvas):

    def __init__(self, parent=None, width=8.6, height=5.0, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        super().__init__(self.fig)
        self.setParent(parent)
        self.setMinimumSize(int(width * dpi), int(height * dpi))

    def plot_peligrosidad(self, matriz_hv, clases_info, zb, dx, dy, activo=None):
        """
        clases_info: salida de core.mesh_export.clasificar_peligrosidad().
        Mapa clasificado a la izquierda y reparto de área a la derecha:
        el mapa dice DÓNDE y el reparto dice CUÁNTO, y para justificar
        una actuación hacen falta las dos cosas.
        """
        self.fig.clear()
        ejes = self.fig.subplots(1, 2, gridspec_kw={"width_ratios": [2.1, 1]})
        ax_mapa, ax_barras = ejes

        reparto = clases_info["reparto"]
        colores = [c["color"] for c in reparto]
        nombres = [c["clase"] for c in reparto]
        umbrales = [c["umbral_hv"] for c in reparto] + [max(float(np.max(matriz_hv)), 3.0)]

        filas, columnas = matriz_hv.shape
        extension = [0, columnas * dx, 0, filas * dy]
        sombra = _relieve_sombreado(np.where(activo, zb, np.nan) if activo is not None else zb,
                                    dx, dy)
        ax_mapa.imshow(sombra, cmap="gray", extent=extension, origin="upper",
                       vmin=0, vmax=1, alpha=0.85, zorder=1)

        datos = np.ma.masked_where(matriz_hv < 1e-3, matriz_hv)
        if activo is not None:
            datos = np.ma.masked_where(~activo, datos)
        ax_mapa.imshow(datos, cmap=ListedColormap(colores),
                       norm=BoundaryNorm(umbrales, len(colores)),
                       extent=extension, origin="upper", zorder=2, alpha=0.92)
        ax_mapa.set_xlabel("Distancia X (m)")
        ax_mapa.set_ylabel("Distancia Y (m)")
        ax_mapa.set_title("Peligrosidad h·v (m²/s)", pad=12)

        parches = [Patch(facecolor=c["color"], edgecolor="#33415c",
                         label=f"{c['clase']} (h·v ≥ {c['umbral_hv']:g})")
                   for c in reparto]
        leyenda = ax_mapa.legend(handles=parches, title="Clase de peligro (FD2320)",
                                 loc="upper center", bbox_to_anchor=(0.5, -0.13), ncol=2)
        leyenda.get_title().set_fontweight("bold")
        leyenda.get_frame().set_linewidth(1.4)

        porcentajes = [c["porcentaje"] for c in reparto]
        barras = ax_barras.barh(nombres, porcentajes, color=colores,
                                edgecolor="#33415c", linewidth=0.9, zorder=3)
        for barra, valor in zip(barras, porcentajes):
            ax_barras.annotate(f"{valor:.1f} %",
                               (barra.get_width(), barra.get_y() + barra.get_height() / 2),
                               textcoords="offset points", xytext=(5, 0), va="center",
                               fontsize=9.5, fontweight="bold")
        ax_barras.set_xlabel("% del área inundada")
        ax_barras.set_title("Reparto del área por clase", pad=12)
        ax_barras.set_xlim(0, max(porcentajes + [1.0]) * 1.25)
        ax_barras.grid(True, axis="x", linestyle=":", linewidth=0.6)
        ax_barras.set_axisbelow(True)

        self.fig.tight_layout()
        self.draw()

    def guardar_figura(self, ruta_png):
        self.fig.savefig(ruta_png, dpi=300, bbox_inches="tight")


class HidrogramasSwe2DCanvas(FigureCanvas):

    def __init__(self, parent=None, width=8.4, height=5.0, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        super().__init__(self.fig)
        self.setParent(parent)
        self.setMinimumSize(int(width * dpi), int(height * dpi))

    def plot_series(self, serie_tiempo, balance=None):
        """
        serie_tiempo: lista de (t, Q_entrada, Q_salida, volumen,
        area_inundada, Q_estructuras) que acumula el simulador.
        """
        self.fig.clear()
        if not serie_tiempo:
            return
        ejes = self.fig.subplots(2, 1, sharex=True,
                                 gridspec_kw={"height_ratios": [1.25, 1]})
        ax_q, ax_v = ejes

        datos = np.asarray(serie_tiempo, dtype=float)
        t_h = datos[:, 0] / 3600.0

        ax_q.plot(t_h, datos[:, 1], "-", linewidth=2.2, color="#2E7D32",
                  label="Caudal de entrada")
        ax_q.plot(t_h, datos[:, 2], "-", linewidth=2.2, color="#B3261E",
                  label="Caudal de salida del dominio")
        if datos.shape[1] > 5 and np.any(datos[:, 5] > 0):
            ax_q.plot(t_h, datos[:, 5], "--", linewidth=1.9, color="#8B5CF6",
                      label="Caudal por estructuras")
        ax_q.set_ylabel("Caudal (m³/s)")
        ax_q.set_title("Evolución de caudales, volumen y área inundada", pad=12)
        ax_q.grid(True, linestyle=":", linewidth=0.6)
        leyenda_impacto(ax_q, titulo="Series de caudal", loc="best")

        ax_v.plot(t_h, datos[:, 3], "-", linewidth=2.2, color="#1F3864",
                  label="Volumen almacenado en el dominio")
        ax_v.set_xlabel("Tiempo (h)")
        ax_v.set_ylabel("Volumen (m³)", color="#1F3864")
        ax_v.tick_params(axis="y", labelcolor="#1F3864")
        ax_v.grid(True, linestyle=":", linewidth=0.6)

        # El área inundada va en un eje secundario porque su magnitud no
        # tiene nada que ver con la del volumen; forzarlas al mismo eje
        # aplastaría una de las dos curvas contra el cero.
        ax_a = ax_v.twinx()
        ax_a.plot(t_h, datos[:, 4] / 10000.0, "--", linewidth=2.0, color="#EF9F27",
                  label="Área inundada")
        ax_a.set_ylabel("Área inundada (ha)", color="#a06b10")
        ax_a.tick_params(axis="y", labelcolor="#a06b10")

        m1, e1 = ax_v.get_legend_handles_labels()
        m2, e2 = ax_a.get_legend_handles_labels()
        leyenda = ax_v.legend(m1 + m2, e1 + e2, title="Almacenamiento y extensión",
                              loc="lower right")
        leyenda.get_title().set_fontweight("bold")
        leyenda.get_frame().set_linewidth(1.4)

        if balance:
            # El error de cierre se anota en el propio gráfico: es el dato
            # que decide si lo demás puede usarse, y en una nota al pie
            # separada pasa desapercibido.
            color = "#1B5E20" if balance["aceptable"] else "#7A1712"
            ax_q.annotate(
                f"Error de balance de masa: {balance['error_relativo_pct']:.4f} %"
                + ("  (aceptable)" if balance["aceptable"] else "  (NO ACEPTABLE)"),
                xy=(0.99, 0.03), xycoords="axes fraction", ha="right", fontsize=9,
                fontweight="bold", color=color,
                bbox=dict(boxstyle="round,pad=0.35", facecolor="#fbfdff",
                          edgecolor=color, linewidth=1.2))

        self.fig.tight_layout()
        self.draw()

    def guardar_figura(self, ruta_png):
        self.fig.savefig(ruta_png, dpi=300, bbox_inches="tight")

    def plot_hidrograma_puntual(self, tiempos_s, calados_m, etiqueta="Punto de corte"):
        """
        Serie temporal de calado en UN punto de la malla (p.ej. el punto
        medio de una línea de corte transversal), reconstruida a partir
        de los instantes capturados -- distinto de plot_series(), que es
        la serie AGREGADA de todo el dominio (caudales de entrada/salida,
        volumen, área). Es lo que responde "¿cómo sube y baja el agua
        AQUÍ, en este punto de la obra?", que la serie agregada no dice.
        """
        self.fig.clear()
        ax = self.fig.add_subplot(111)
        t_h = np.asarray(tiempos_s, dtype=float) / 3600.0
        ax.plot(t_h, calados_m, "-", linewidth=2.2, color="#1F6FB2", marker="o", markersize=3)
        ax.set_xlabel("Tiempo (h)")
        ax.set_ylabel("Calado (m)")
        ax.set_title(f"Calado en el tiempo — {etiqueta}", pad=12)
        ax.grid(True, linestyle=":", linewidth=0.6)
        self.fig.tight_layout()
        self.draw()


class PerfilSwe2DCanvas(FigureCanvas):

    def __init__(self, parent=None, width=8.4, height=4.6, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.ax = self.fig.add_subplot(111)
        super().__init__(self.fig)
        self.setParent(parent)
        self.setMinimumSize(int(width * dpi), int(height * dpi))

    def plot_perfil(self, zb_linea, h_linea, paso_m, titulo="Perfil del cauce",
                    cota_estructura=None, nombre_estructura=""):
        """
        Corte con fondo, lámina de agua y calado. Es la vista de
        proyectista: sobre ella se comprueba el resguardo bajo un tablero
        o el calado sobre una obra de paso, cosa que un mapa en planta
        no permite hacer.
        """
        self.fig.clear()
        self.ax = self.fig.add_subplot(111)
        distancia = np.arange(len(zb_linea)) * paso_m
        fondo = np.asarray(zb_linea, dtype=float)
        calado = np.asarray(h_linea, dtype=float)
        superficie = fondo + calado

        self.ax.fill_between(distancia, fondo.min() - 1.0, fondo, color="#8d6e4a",
                             alpha=0.85, zorder=2, label="Terreno (fondo)")
        self.ax.fill_between(distancia, fondo, superficie,
                             where=(calado > 1e-3), color="#4a90d9", alpha=0.75,
                             zorder=3, label="Lámina de agua")
        self.ax.plot(distancia, fondo, "-", linewidth=1.8, color="#5a4630", zorder=4)
        self.ax.plot(distancia, superficie, "-", linewidth=2.0, color="#1F3864",
                     zorder=5, label="Superficie libre")

        if cota_estructura is not None:
            self.ax.axhline(cota_estructura, linestyle="--", linewidth=2.0,
                            color="#B3261E", zorder=6,
                            label=nombre_estructura or "Cota de la estructura")

        self.ax.set_xlabel("Distancia a lo largo del perfil (m)")
        self.ax.set_ylabel("Cota (m s.n.m.)")
        self.ax.set_title(titulo, pad=12)
        self.ax.set_ylim(fondo.min() - 0.5, max(superficie.max(),
                                                 cota_estructura or -1e9) + 1.0)
        self.ax.grid(True, linestyle=":", linewidth=0.6)
        leyenda_impacto(self.ax, titulo="Elementos del perfil", loc="best")
        self.fig.tight_layout()
        self.draw()

    def guardar_figura(self, ruta_png):
        self.fig.savefig(ruta_png, dpi=300, bbox_inches="tight")


class TerrenoCalado3DCanvas(FigureCanvas):
    """
    Vista 3D del terreno con el calado superpuesto (item 8, fase 4a).

    Se usa el eje 3D de matplotlib (mpl_toolkits.mplot3d) en vez del
    motor Qt3D nativo de QGIS: es el mismo backend Agg que ya usan TODOS
    los demás gráficos del plugin, así que se puede verificar con una
    prueba automática (que la superficie se construyó con los datos
    correctos) igual que cualquier otro -- un `Qgs3DMapCanvas` necesita
    un contexto OpenGL real, que no está garantizado en un entorno
    headless, y hubiera quedado sin poder probarse.

    La rotación por arrastre viene GRATIS: Axes3D la activa sola
    (mouse_init()) sobre los eventos de mouse del propio canvas, sin
    depender de una barra de herramientas de navegación. El zoom, en
    cambio, NO se deja al scroll del mouse (su soporte varía entre
    versiones de matplotlib) -- se implementa aquí mismo recortando o
    expandiendo los 3 límites de eje, así que funciona igual en
    cualquier versión.
    """

    def __init__(self, parent=None, width=7.6, height=6.0, dpi=100):
        # mpl_toolkits.mplot3d registra el proyector '3d' con solo
        # importarse -- basta con importarlo aquí, sin usar el nombre,
        # para que projection="3d" funcione más abajo.
        from mpl_toolkits.mplot3d import Axes3D  # noqa: F401
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.ax = self.fig.add_subplot(111, projection="3d")
        super().__init__(self.fig)
        self.setParent(parent)
        self.setMinimumSize(int(width * dpi), int(height * dpi))
        self._limites_originales = None

    def plot_terreno_calado(self, zb, h, dx, dy, activo=None, submuestreo=None,
                            exageracion_vertical=2.0, objetivo_puntos_por_eje=150):
        """
        zb, h: matrices 2D completas de la malla de simulación (h puede
            ser el calado máximo o el de un instante cualquiera).
        submuestreo: usar 1 de cada N celdas en cada eje -- una malla de
            simulación (cientos de miles de celdas) es inviable como
            superficie 3D interactiva; se autocalcula si no se indica,
            apuntando a `objetivo_puntos_por_eje` puntos por lado.
        exageracion_vertical: cuánto se estira el eje Z respecto a la
            escala real de X/Y -- sin esto, el relieve de una cuenca real
            (kilómetros de ancho, decenas de metros de desnivel) se ve
            como una lámina plana.
        """
        self.ax.clear()
        filas, columnas = zb.shape
        if submuestreo is None:
            submuestreo = max(1, int(max(filas, columnas) / max(objetivo_puntos_por_eje, 1)))

        zb_s = zb[::submuestreo, ::submuestreo]
        h_s = h[::submuestreo, ::submuestreo] if h is not None else None
        activo_s = activo[::submuestreo, ::submuestreo] if activo is not None else None

        filas_s, columnas_s = zb_s.shape
        xs = np.arange(columnas_s) * dx * submuestreo
        ys = np.arange(filas_s) * dy * submuestreo
        malla_x, malla_y = np.meshgrid(xs, ys)
        z_valido = np.where(np.isfinite(zb_s), zb_s, np.nan)
        z_relleno = float(np.nanmin(z_valido)) if np.any(np.isfinite(z_valido)) else 0.0
        malla_z = np.where(np.isfinite(zb_s), zb_s, z_relleno)

        self.ax.plot_surface(malla_x, malla_y, malla_z, cmap="terrain", linewidth=0,
                             antialiased=True, alpha=0.95, rstride=1, cstride=1, zorder=1)

        if h_s is not None:
            agua = np.where(activo_s, h_s, 0.0) if activo_s is not None else h_s
            mascara_agua = agua > 1e-3
            if np.any(mascara_agua):
                malla_z_agua = np.where(mascara_agua, malla_z + agua, np.nan)
                self.ax.plot_surface(malla_x, malla_y, malla_z_agua, color="#1F6FB2",
                                     alpha=0.6, linewidth=0, antialiased=True, zorder=2)

        self.ax.set_xlabel("X (m)")
        self.ax.set_ylabel("Y (m)")
        self.ax.set_zlabel("Cota (m s.n.m.)")
        self.ax.set_title(
            f"Terreno y calado — vista 3D (arrastre para rotar; malla cada "
            f"{submuestreo} celda(s) de la simulación)", pad=12)
        try:
            rango_z = float(np.nanmax(malla_z) - np.nanmin(malla_z))
            self.ax.set_box_aspect((columnas_s * dx * submuestreo,
                                    filas_s * dy * submuestreo,
                                    rango_z * exageracion_vertical + 1e-6))
        except AttributeError:
            pass  # matplotlib < 3.3 no tiene set_box_aspect -- se deja la proporción por defecto
        self.fig.tight_layout()
        self.draw()
        self._limites_originales = (self.ax.get_xlim(), self.ax.get_ylim(), self.ax.get_zlim())

    def zoom(self, factor: float):
        """factor < 1 acerca, > 1 aleja -- recorta o expande los 3
        límites de eje alrededor de su centro actual."""
        for obtener, establecer in ((self.ax.get_xlim, self.ax.set_xlim),
                                    (self.ax.get_ylim, self.ax.set_ylim),
                                    (self.ax.get_zlim, self.ax.set_zlim)):
            lo, hi = obtener()
            centro = (lo + hi) / 2.0
            semirrango = (hi - lo) / 2.0 * factor
            establecer(centro - semirrango, centro + semirrango)
        self.draw()

    def restablecer_vista(self):
        if self._limites_originales:
            self.ax.set_xlim(self._limites_originales[0])
            self.ax.set_ylim(self._limites_originales[1])
            self.ax.set_zlim(self._limites_originales[2])
            self.draw()

    def guardar_figura(self, ruta_png):
        self.fig.savefig(ruta_png, dpi=300, bbox_inches="tight")
