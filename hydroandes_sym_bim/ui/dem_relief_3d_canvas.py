# -*- coding: utf-8 -*-
"""
ui/dem_relief_3d_canvas.py

Visor 3D "workspace view" del MDE para la Pestaña 1 (DEM y Delimitación),
a pedido explícito del usuario: relieve sombreado (hillshade) con mezcla
MULTIPLICAR sobre un color base, rotable libremente en 360° con el mouse.

DE DÓNDE SALEN LOS VALORES POR DEFECTO (factor Z=1, azimut=42,
altitud=45, color base #B2DF8A): el usuario pidió una paleta "similar a
la que tenemos en el GIS abierto llamado PRUEBA_HYDROANDINA" y, al
preguntársele, indicó que se leyera el archivo del proyecto. Se localizó
y se leyó su capa "DEM_COMBINADO_RELLENO"
(D:\\Ningsiar\\2 BUSSINES\\Hidrologia\\2026\\MERISS\\GIS\\PRUEBA_HYDROANDINA.qgz,
sección <maplayer>/<pipe>/<rasterrenderer type="hillshade">): usa
zfactor="1", azimuth="42", angle="45", y un efecto "Colorize" (huesaturation
colorizeOn=1, colorizeRed=178 colorizeGreen=223 colorizeBlue=138,
colorizeStrength=100) sobre la capa, compuesta con <blendMode>6</blendMode>
-- 6 es el código de "Multiply" en QGIS (QgsPainting::BlendMultiply). Esos
son exactamente los valores por defecto de este módulo.

POR QUÉ EL HILLSHADE SE CALCULA CON matplotlib.colors.LightSource Y NO
CON gdal:hillshade (como core/mapas_tematicos.py::generar_hillshade):
LightSource.hillshade() devuelve directamente un array 2D en memoria
(0-1) alineado celda a celda con la elevación ya leída para la
superficie 3D, sin pasar por processing.run() (que exige un
QgsProcessingContext/Feedback y escribir un ráster temporal a disco) --
más simple y más rápido de recalcular mientras el usuario ajusta
parámetros o gira la cámara. Es el mismo modelo de sombreado
Lambertiano (azimut + altitud de una fuente de luz) que gdal:hillshade.

MEZCLA "MULTIPLICAR": color_final = color_base * hillshade_gris (canal a
canal), la misma fórmula que el modo de fusión "Multiply" de
QGIS/Photoshop/GIMP. Se aplica aquí a mano (no hay un "blend mode" de
matplotlib que la reproduzca) y el resultado se pasa como `facecolors`
de plot_surface(), en vez de dejar que un `cmap` coloree la superficie
por elevación -- así el color final ya lleva el relieve incorporado, tal
como en la capa de referencia.

La rotación 360° viene GRATIS de Axes3D (arrastre con el mouse), el
mismo mecanismo ya usado en ui/swe2d_canvas.py::TerrenoCalado3DCanvas --
no se usa el motor Qt3D nativo de QGIS por la misma razón documentada
allí: este backend Agg es el que se puede probar en un entorno headless
(un Qgs3DMapCanvas necesita un contexto OpenGL real, no garantizado en
headless).
"""
import numpy as np

try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
except ImportError:
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.colors import LightSource

# Valores por defecto extraídos de PRUEBA_HYDROANDINA.qgz (ver docstring
# del módulo) -- capa "DEM_COMBINADO_RELLENO", renderizador hillshade.
AZIMUT_DEFECTO = 42.0
ALTITUD_DEFECTO = 45.0
Z_FACTOR_DEFECTO = 1.0
COLOR_BASE_DEFECTO = (178, 223, 138)  # RGB 0-255, = #B2DF8A


class DemRelieveCanvasError(Exception):
    pass


class DemRelieve3DCanvas(FigureCanvas):
    """
    Visor 3D "workspace view" del MDE: relieve sombreado (hillshade,
    azimut/altitud/factor Z configurables) con mezcla MULTIPLICAR sobre
    un color base configurable (ver `establecer_color_base()`).
    """

    def __init__(self, parent=None, width=5.0, height=4.4, dpi=100):
        # mpl_toolkits.mplot3d registra el proyector '3d' con solo
        # importarse -- basta con importarlo aquí, sin usar el nombre,
        # para que projection="3d" funcione más abajo.
        from mpl_toolkits.mplot3d import Axes3D  # noqa: F401
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.ax = self.fig.add_subplot(111, projection="3d")
        super().__init__(self.fig)
        self.setParent(parent)
        self.setMinimumSize(int(width * dpi * 0.75), int(height * dpi * 0.75))
        self.color_base_rgb = COLOR_BASE_DEFECTO
        self._timer_giro = None
        self._ultimo_render = None  # (elevacion_submuestreada, dx, dy, submuestreo) del último plot_dem()

    def establecer_color_base(self, rgb):
        """rgb: tupla (R, G, B) 0-255. Reemplaza el color BASE que se
        multiplica por el hillshade -- usado para igualar la paleta a la
        de un proyecto QGIS de referencia."""
        if len(rgb) != 3 or any(not (0 <= c <= 255) for c in rgb):
            raise DemRelieveCanvasError("El color base debe ser una tupla (R, G, B) con valores 0-255.")
        self.color_base_rgb = tuple(rgb)

    def plot_dem(self, elevacion: np.ndarray, dx: float, dy: float,
                 azimut: float = AZIMUT_DEFECTO, altitud: float = ALTITUD_DEFECTO,
                 z_factor: float = Z_FACTOR_DEFECTO, exageracion_vertical: float = 1.5,
                 submuestreo=None, objetivo_puntos_por_eje: int = 180, titulo=None):
        """
        elevacion: array 2D de cotas (m), con np.nan en las celdas sin
            dato (ver core/raster_stats.py::leer_elevacion_2d).
        dx, dy: tamaño de celda (m) en X e Y.
        azimut/altitud: posición de la fuente de luz del hillshade
            (grados; convención estándar de sombreado de relieve, igual
            que gdal:hillshade / QGIS).
        z_factor: exageración vertical aplicada AL SOMBREADO (no a la
            geometría 3D -- ver `exageracion_vertical` para esa),
            equivalente al parámetro "Z Factor" de QGIS/gdal:hillshade.
            1.0 = sin exageración (relieve real).
        exageracion_vertical: estira el eje Z de la superficie 3D
            respecto a X/Y (igual que en TerrenoCalado3DCanvas) -- sin
            esto, una cuenca real (kilómetros de ancho, decenas/cientos
            de metros de desnivel) se ve como una lámina casi plana.
        submuestreo: usar 1 de cada N celdas en cada eje -- un MDE
            completo (millones de celdas) es inviable como superficie 3D
            interactiva; se autocalcula si no se indica, apuntando a
            `objetivo_puntos_por_eje` puntos por lado.
        """
        self.ax.clear()
        filas, columnas = elevacion.shape
        if submuestreo is None:
            submuestreo = max(1, int(max(filas, columnas) / max(objetivo_puntos_por_eje, 1)))

        elev_s = elevacion[::submuestreo, ::submuestreo]
        filas_s, columnas_s = elev_s.shape
        if filas_s < 2 or columnas_s < 2:
            raise DemRelieveCanvasError("El MDE no tiene celdas suficientes para renderizar en 3D.")

        valido = np.isfinite(elev_s)
        if not np.any(valido):
            raise DemRelieveCanvasError("El MDE no tiene ninguna celda con dato válido.")

        xs = np.arange(columnas_s) * dx * submuestreo
        ys = np.arange(filas_s) * dy * submuestreo
        malla_x, malla_y = np.meshgrid(xs, ys)

        z_min, z_max = float(np.nanmin(elev_s)), float(np.nanmax(elev_s))
        malla_z = np.where(valido, elev_s, z_min)

        # --- Hillshade (0-1), mismo modelo Lambertiano que gdal:hillshade ---
        fuente_luz = LightSource(azdeg=azimut, altdeg=altitud)
        sombreado = fuente_luz.hillshade(malla_z, vert_exag=z_factor,
                                          dx=dx * submuestreo, dy=dy * submuestreo)
        sombreado = np.clip(sombreado, 0.0, 1.0)

        # --- Mezcla MULTIPLICAR: color_final = color_base * sombreado (por canal RGB) ---
        r, g, b = (c / 255.0 for c in self.color_base_rgb)
        color_final = np.empty(sombreado.shape + (4,))
        color_final[..., 0] = r * sombreado
        color_final[..., 1] = g * sombreado
        color_final[..., 2] = b * sombreado
        color_final[..., 3] = 1.0
        color_final = np.clip(color_final, 0.0, 1.0)

        self.ax.plot_surface(malla_x, malla_y, malla_z, facecolors=color_final, linewidth=0,
                              antialiased=True, rstride=1, cstride=1, shade=False, zorder=1)

        self.ax.set_xlabel("X (m)")
        self.ax.set_ylabel("Y (m)")
        self.ax.set_zlabel("Cota (m s.n.m.)")
        self.ax.set_title(titulo or "Relieve 3D del MDE (arrastre para rotar 360°)", pad=10)
        try:
            rango_z = (z_max - z_min) or 1.0
            self.ax.set_box_aspect((columnas_s * dx * submuestreo,
                                    filas_s * dy * submuestreo,
                                    rango_z * exageracion_vertical + 1e-6))
        except AttributeError:
            pass  # matplotlib < 3.3 no tiene set_box_aspect -- se deja la proporción por defecto
        self.ax.set_axis_off()  # "workspace view" de alto impacto: solo el relieve, sin ejes/grilla
        self.fig.tight_layout()
        self.draw()
        self._ultimo_render = (elev_s, dx, dy, submuestreo)

    def guardar_figura(self, ruta_png):
        self.fig.savefig(ruta_png, dpi=300, bbox_inches="tight")

    # ---------------- Giro automático (efecto "workspace" cinemático) ----------------
    def iniciar_giro_automatico(self, grados_por_paso: float = 1.0, intervalo_ms: int = 50):
        from qgis.PyQt.QtCore import QTimer
        if self._timer_giro is not None:
            return
        self._timer_giro = QTimer(self)
        self._timer_giro.timeout.connect(lambda: self._avanzar_giro(grados_por_paso))
        self._timer_giro.start(intervalo_ms)

    def detener_giro_automatico(self):
        if self._timer_giro is not None:
            self._timer_giro.stop()
            self._timer_giro.deleteLater()
            self._timer_giro = None

    def girando_automaticamente(self) -> bool:
        return self._timer_giro is not None

    def _avanzar_giro(self, grados_por_paso: float):
        self.ax.view_init(elev=self.ax.elev, azim=(self.ax.azim + grados_por_paso) % 360.0)
        self.draw()
