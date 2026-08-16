# -*- coding: utf-8 -*-
"""
ui/bim_canvas.py

Módulo BIM (después de la Pestaña 8, Simulación 2D) -- render 3D
acotado de UNA estructura hidráulica ya calculada, a partir de
cualquiera de las dos fuentes de datos del plugin:

  - Pestaña 7 (self.resultados_hidraulica_drenaje) -- geometría real de
    ingeniería (canales, alcantarillas, enrocado, sumideros). Pontón,
    Puente y Defensa Ribereña solo registran cotas de verificación de
    borde libre, NO luz/ancho/longitud reales -- se muestran como
    esquema con un ancho nominal, claramente rotulado como tal.
  - Pestaña 8 (self.tabla_estructuras_2d / swe2d.Estructura) --
    geometría esquemática de inserción para el modelo hidrodinámico
    (vertedero/orificio/alcantarilla), con mucho menos detalle
    constructivo que la Pestaña 7.

Extrusión paramétrica simple (perfil 2D barrido a lo largo de una
longitud L) usando Poly3DCollection sobre el mismo backend Agg de
matplotlib que el resto del plugin -- mismo patrón que
ui/swe2d_canvas.py::TerrenoCalado3DCanvas (item 8, fase 4a), así que se
puede probar en headless igual que cualquier otro gráfico, sin
depender de un contexto OpenGL real.

Los perfiles 2D (contorno de cada estructura) viven en
core/bim_geometry.py, no aquí -- así el render 3D (este archivo), los
metrados (core/bim_metrados.py, fase 2) y la futura exportación IFC
(fase 3) parten de EXACTAMENTE la misma geometría.

NO es diseño estructural ni geotécnico: es una representación
geométrica de las dimensiones YA calculadas en Pestaña 7/8.
"""
import math

try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
except ImportError:
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from .chart_style import aplicar_estilo_graficos
from ..core import bim_geometry as bg
from ..core.bim_geometry import GeometriaNoDisponibleError  # noqa: F401  (reexportado)

aplicar_estilo_graficos()

# Ancho/longitud NOMINALES usados solo para dibujar estructuras cuyo
# origen de datos no registra esa dimensión (Pontón/Puente de Pestaña 7,
# que solo verifican borde libre). Se rotulan siempre como "esquema".
ANCHO_NOMINAL_M = 6.0
LONGITUD_POR_DEFECTO_M = 10.0

_COLOR_CONCRETO = "#B5B2AC"
_COLOR_METAL = "#8C8C8C"
_COLOR_ROCA = "#9C9C9C"
_COLOR_AGUA = "#1F6FB2"


class Estructura3DCanvas(FigureCanvas):
    """Vista 3D de UNA estructura hidráulica con sus dimensiones
    acotadas. Ver docstring del módulo para las dos fuentes soportadas."""

    def __init__(self, parent=None, width=7.6, height=6.0, dpi=100):
        from mpl_toolkits.mplot3d import Axes3D  # noqa: F401  (registra projection="3d")
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.ax = self.fig.add_subplot(111, projection="3d")
        super().__init__(self.fig)
        self.setParent(parent)
        self.setMinimumSize(int(width * dpi), int(height * dpi))

    # ------------------------------------------------------------
    # Primitivas de dibujo
    # ------------------------------------------------------------
    def _extruir_perfil(self, xs, zs, longitud, cerrado, color, alpha=0.9):
        """Barre el contorno (xs, zs) -- a Y=0 -- hasta Y=longitud,
        agregando las caras laterales (y, si `cerrado`, un tubo cerrado
        en vez de una artesa abierta) más las 2 tapas de los extremos."""
        from mpl_toolkits.mplot3d.art3d import Poly3DCollection
        n = len(xs)
        rango = range(n) if cerrado else range(n - 1)
        caras = []
        for i in rango:
            j = (i + 1) % n
            caras.append([
                (xs[i], 0.0, zs[i]), (xs[j], 0.0, zs[j]),
                (xs[j], longitud, zs[j]), (xs[i], longitud, zs[i]),
            ])
        self.ax.add_collection3d(Poly3DCollection(
            caras, facecolor=color, edgecolor="#3B3B3B", linewidth=0.25, alpha=alpha))
        tapa_inicio = [[(xs[i], 0.0, zs[i]) for i in range(n)]]
        tapa_fin = [[(xs[i], longitud, zs[i]) for i in range(n)]]
        self.ax.add_collection3d(Poly3DCollection(tapa_inicio, facecolor=color, alpha=alpha, edgecolor="none"))
        self.ax.add_collection3d(Poly3DCollection(tapa_fin, facecolor=color, alpha=alpha, edgecolor="none"))

    def _agregar_plano(self, x0, x1, y0, y1, z, color=_COLOR_AGUA, alpha=0.35):
        from mpl_toolkits.mplot3d.art3d import Poly3DCollection
        cara = [(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)]
        self.ax.add_collection3d(Poly3DCollection([cara], facecolor=color, alpha=alpha, edgecolor="none"))

    def _ajustar_limites(self, xs, ys, zs, exageracion_vertical=1.0):
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)
        z_min, z_max = min(zs), max(zs)
        # margen para que las anotaciones de texto no queden pegadas al borde
        mx = max((x_max - x_min) * 0.15, 0.2)
        mz = max((z_max - z_min) * 0.2, 0.2)
        self.ax.set_xlim(x_min - mx, x_max + mx)
        self.ax.set_ylim(y_min, y_max)
        self.ax.set_zlim(z_min, z_max + mz)
        try:
            self.ax.set_box_aspect((
                (x_max - x_min) + 2 * mx, (y_max - y_min) or 1.0,
                ((z_max - z_min) + mz) * exageracion_vertical))
        except AttributeError:
            pass  # matplotlib < 3.3

    def _rotular(self, titulo):
        self.ax.set_xlabel("Ancho (m)")
        self.ax.set_ylabel("Longitud (m)")
        self.ax.set_zlabel("Altura / cota (m)")
        self.ax.set_title(f"{titulo} — vista 3D (arrastre para rotar)", pad=12)

    # ------------------------------------------------------------
    # Fuente 1 -- Pestaña 7 (self.resultados_hidraulica_drenaje)
    # ------------------------------------------------------------
    def graficar_desde_pestana7(self, nombre: str, datos: dict, longitud_m: float = LONGITUD_POR_DEFECTO_M):
        self.ax.clear()
        tipo = datos.get("tipo", "")
        if tipo == "Canal":
            self._graficar_canal(datos, longitud_m)
        elif tipo == "Alcantarilla":
            self._graficar_alcantarilla_p7(datos, longitud_m)
        elif tipo == "Enrocado (RipRap)":
            self._graficar_enrocado(datos, longitud_m)
        elif tipo == "Sumidero":
            self._graficar_sumidero(datos)
        elif tipo in ("Pontón", "Puente"):
            self._graficar_borde_libre(tipo, datos, longitud_m)
        elif tipo == "Defensa Ribereña":
            self._graficar_defensa(datos, longitud_m)
        else:
            raise GeometriaNoDisponibleError(
                f"el tipo «{tipo}» todavía no tiene render 3D en el módulo BIM (fase 1 cubre "
                f"canales, alcantarillas, enrocado, sumideros, pontón/puente y defensa ribereña).")
        self._rotular(nombre)
        self.fig.tight_layout()
        self.draw()

    def _graficar_canal(self, datos, longitud_m):
        xs, zs, etiqueta = bg.perfil_canal_desde_datos(datos)
        self._extruir_perfil(xs, zs, longitud_m, cerrado=False, color=_COLOR_CONCRETO)
        y = datos.get("tirante_normal_m")
        if y:
            self._agregar_plano(min(xs), max(xs), 0.0, longitud_m, y)
        self.ax.text(min(xs), longitud_m * 1.05, max(zs), f"{etiqueta}\nL = {longitud_m:.1f} m", fontsize=8.5)
        self._ajustar_limites(xs, [0.0, longitud_m], zs)

    def _graficar_alcantarilla_p7(self, datos, longitud_m):
        y = datos.get("tirante_m")
        xs, zs, etiqueta = bg.perfil_alcantarilla_desde_datos(datos)
        self._extruir_perfil(xs, zs, longitud_m, cerrado=True, color=_COLOR_METAL)
        if y:
            self._agregar_plano(min(xs), max(xs), 0.0, longitud_m, y)
        self.ax.text(min(xs), longitud_m * 1.05, max(zs), f"{etiqueta}\nL = {longitud_m:.1f} m", fontsize=8.5)
        self._ajustar_limites(xs, [0.0, longitud_m], zs)

    def _graficar_enrocado(self, datos, longitud_m, angulo_talud_deg=33.7):
        d50 = datos.get("D50_m")
        if d50 is None:
            raise GeometriaNoDisponibleError("falta D50_m para el enrocado")
        xs, zs, alto_talud, _, espesor = bg.perfil_talud_enrocado(d50, angulo_talud_deg)
        self._extruir_perfil(xs, zs, longitud_m, cerrado=True, color=_COLOR_ROCA)
        self.ax.text(0.0, longitud_m * 1.05, alto_talud,
                      f"D50 = {d50 * 100:.1f} cm, espesor ≈ {espesor:.2f} m\nL = {longitud_m:.1f} m "
                      f"(talud {angulo_talud_deg:.1f}°, ilustrativo)", fontsize=8.5)
        self._ajustar_limites(xs, [0.0, longitud_m], zs)

    def _graficar_sumidero(self, datos):
        largo_ventana = datos.get("L_m")
        y = datos.get("y_m")
        if largo_ventana is None or y is None:
            raise GeometriaNoDisponibleError("faltan L_m/y_m del sumidero")
        xs, zs, ancho_caja, profundidad_caja = bg.perfil_sumidero(largo_ventana, y)
        self._extruir_perfil(xs, zs, largo_ventana, cerrado=True, color=_COLOR_CONCRETO)
        self._agregar_plano(0.0, ancho_caja, 0.0, largo_ventana, y)
        self.ax.text(0.0, largo_ventana * 1.05, profundidad_caja,
                      f"L (ventana) = {largo_ventana:.2f} m, y = {y:.2f} m\n"
                      f"caja: {profundidad_caja:.2f} m de profundidad (nominal)", fontsize=8.5)
        self._ajustar_limites([0.0, ancho_caja], [0.0, largo_ventana], [0.0, profundidad_caja])

    def _graficar_borde_libre(self, nombre_estructura, datos, longitud_m):
        cota_agua = datos.get("cota_agua_m")
        cota_estructura = datos.get("cota_estructura_m")
        if cota_agua is None or cota_estructura is None:
            raise GeometriaNoDisponibleError(f"faltan cotas de agua/estructura para {nombre_estructura}")
        z0 = min(cota_agua, cota_estructura) - 1.0
        agua_z, estructura_z = cota_agua - z0, cota_estructura - z0
        self._agregar_plano(0.0, ANCHO_NOMINAL_M, 0.0, longitud_m, agua_z)
        from mpl_toolkits.mplot3d.art3d import Poly3DCollection
        cara = [(0.0, 0.0, estructura_z), (ANCHO_NOMINAL_M, 0.0, estructura_z),
                (ANCHO_NOMINAL_M, longitud_m, estructura_z), (0.0, longitud_m, estructura_z)]
        self.ax.add_collection3d(Poly3DCollection([cara], facecolor=_COLOR_CONCRETO, alpha=0.9, edgecolor="#3B3B3B"))
        bl = datos.get("borde_libre_disponible_m", cota_estructura - cota_agua)
        self.ax.text(ANCHO_NOMINAL_M * 1.05, longitud_m / 2, (agua_z + estructura_z) / 2,
                      f"BL disponible = {bl:.2f} m\nagua = {cota_agua:.2f} m s.n.m.\n"
                      f"{nombre_estructura.lower()} = {cota_estructura:.2f} m s.n.m.", fontsize=8)
        self.ax.text(0.0, longitud_m * 1.05, max(agua_z, estructura_z),
                      f"⚠ Esquema: {nombre_estructura} solo registra verificación de borde libre "
                      f"en Pestaña 7 -- ancho ({ANCHO_NOMINAL_M:.0f} m) y longitud "
                      f"({longitud_m:.1f} m) son NOMINALES, no la luz/vano real.",
                      fontsize=7.5, color="#8a5a00")
        self._ajustar_limites([0.0, ANCHO_NOMINAL_M], [0.0, longitud_m], [0.0, max(agua_z, estructura_z)])

    def _graficar_defensa(self, datos, longitud_m, angulo_talud_deg=33.7):
        cota_agua = datos.get("cota_agua_m")
        cota_corona = datos.get("cota_corona_m")
        d50 = datos.get("D50_m")
        if cota_agua is None or cota_corona is None or d50 is None:
            raise GeometriaNoDisponibleError("faltan cota_agua_m/cota_corona_m/D50_m de la defensa ribereña")
        z0 = min(cota_agua, cota_corona) - 1.0
        agua_z, corona_z = cota_agua - z0, cota_corona - z0
        xs, zs, alto_talud, _, espesor = bg.perfil_talud_enrocado(d50, angulo_talud_deg)
        # el talud de la defensa arranca en la cota de agua local (z0), no en 0 --
        # se desplaza el perfil verticalmente para que la corona quede en corona_z
        desplazamiento = corona_z - alto_talud
        zs = [z + desplazamiento for z in zs]
        alto_talud = corona_z
        self._extruir_perfil(xs, zs, longitud_m, cerrado=True, color=_COLOR_ROCA)
        self._agregar_plano(min(xs), max(xs), 0.0, longitud_m, agua_z)
        bl = datos.get("borde_libre_disponible_m", cota_corona - cota_agua)
        self.ax.text(min(xs), longitud_m * 1.05, alto_talud,
                      f"corona = {cota_corona:.2f} m s.n.m., agua = {cota_agua:.2f} m s.n.m.\n"
                      f"BL = {bl:.2f} m, D50 = {d50 * 100:.1f} cm\nL = {longitud_m:.1f} m "
                      f"(talud {angulo_talud_deg:.1f}°, ilustrativo)", fontsize=8)
        self._ajustar_limites(xs, [0.0, longitud_m], zs)

    # ------------------------------------------------------------
    # Fuente 2 -- Pestaña 8 (swe2d.Estructura, ver
    # plugin_dialog.py::_leer_estructuras_2d)
    # ------------------------------------------------------------
    def graficar_desde_pestana8(self, estructura):
        """`estructura`: instancia de core.swe2d.Estructura (atributos
        .tipo, .parametros, .nombre) -- se reutiliza tal cual la arma
        _leer_estructuras_2d(), sin volver a interpretar la tabla."""
        self.ax.clear()
        tipo = estructura.tipo
        p = estructura.parametros
        if tipo == "alcantarilla":
            self._graficar_alcantarilla_p8(p)
        elif tipo == "vertedero":
            self._graficar_vertedero_p8(p)
        elif tipo == "orificio":
            self._graficar_orificio_p8(p)
        else:
            raise GeometriaNoDisponibleError(f"tipo de estructura de Pestaña 8 no reconocido: «{tipo}»")
        self._rotular(f"{estructura.nombre} (Pestaña 8, esquemático)")
        self.fig.tight_layout()
        self.draw()

    def _graficar_alcantarilla_p8(self, p):
        d = p.get("diametro")
        longitud = p.get("longitud", LONGITUD_POR_DEFECTO_M)
        if not d:
            raise GeometriaNoDisponibleError("falta el diámetro de la alcantarilla")
        xs, zs = bg.perfil_circular(d)
        self._extruir_perfil(xs, zs, longitud, cerrado=True, color=_COLOR_METAL)
        self.ax.text(min(xs), longitud * 1.05, max(zs),
                      f"D = {d:.2f} m, L = {longitud:.2f} m\ncota entrada = {p.get('cota_entrada', '?')} m s.n.m.",
                      fontsize=8.5)
        self._ajustar_limites(xs, [0.0, longitud], zs)

    def _graficar_vertedero_p8(self, p):
        longitud_cresta = p.get("longitud", 5.0)
        cota_cresta = p.get("cota_cresta", 0.0)
        xs, zs = bg.perfil_muro_nominal()
        alto_muro = max(zs)
        self._extruir_perfil(xs, zs, longitud_cresta, cerrado=True, color=_COLOR_CONCRETO)
        self.ax.text(0.0, longitud_cresta * 1.05, alto_muro,
                      f"Vertedero -- longitud de cresta = {longitud_cresta:.2f} m\n"
                      f"cota de cresta = {cota_cresta:.2f} m s.n.m., Cd = {p.get('coef_descarga', '?')}\n"
                      f"⚠ Esquema: alto/espesor de muro son nominales (Pestaña 8 no los registra).",
                      fontsize=7.5, color="#8a5a00")
        self._ajustar_limites(xs, [0.0, longitud_cresta], zs)

    def _graficar_orificio_p8(self, p):
        area = p.get("area", 0.5)
        lado = math.sqrt(max(area, 1e-6))
        xs, zs = bg.perfil_muro_nominal(alto=max(lado * 1.8, 1.5))
        alto_muro = max(zs)
        self._extruir_perfil(xs, zs, lado, cerrado=True, color=_COLOR_CONCRETO)
        self.ax.text(0.0, lado * 1.4, alto_muro,
                      f"Orificio -- área = {area:.3f} m² (lado equivalente ≈ {lado:.2f} m)\n"
                      f"Cd = {p.get('coef_descarga', '?')}\n"
                      f"⚠ Esquema: no representa la forma real del orificio ni el muro que lo contiene.",
                      fontsize=7.5, color="#8a5a00")
        self._ajustar_limites(xs, [0.0, lado], zs)
