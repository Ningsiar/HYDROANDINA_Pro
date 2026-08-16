# -*- coding: utf-8 -*-
"""
core/bim_geometry.py

Geometría paramétrica compartida por el Módulo BIM: perfiles 2D
(contorno de fondo/paredes) de cada tipo de estructura, usados tanto
por el render 3D (ui/bim_canvas.py) como por los metrados
(core/bim_metrados.py) y, en una fase futura, la exportación IFC --
para que las tres fases usen EXACTAMENTE la misma geometría en vez de
recalcularla cada una por su lado.

Sin dependencias de Qt/matplotlib/QGIS a propósito: son funciones
puras (solo `math`), así que se pueden probar con Python simple.

Dos categorías de perfil, según cómo se calcula su volumen (ver
core/bim_metrados.py):
  - "cascara" (canales, alcantarillas, sumideros): xs/zs es el contorno
    MOJADO (el vacío por donde pasa el agua) -- el volumen de concreto
    es una cáscara de espesor `espesor_muro` alrededor de ese contorno.
  - "area_solida" (enrocado, defensa ribereña, muros esquemáticos de
    Pestaña 8): xs/zs YA es el contorno del material sólido (la capa de
    roca, el muro) -- el volumen es directamente su área × longitud,
    sin envolver una cáscara adicional.
"""
import math


class GeometriaNoDisponibleError(Exception):
    """La estructura seleccionada no tiene datos suficientes para
    construir su geometría. El mensaje explica qué falta."""


# ======================================================================
# Perfiles base
# ======================================================================
def perfil_rectangular(b, y):
    return [0.0, 0.0, b, b], [y * 1.15, 0.0, 0.0, y * 1.15]


def perfil_triangular(z, y):
    return [-z * y * 1.15, 0.0, z * y * 1.15], [y * 1.15, 0.0, y * 1.15]


def perfil_trapezoidal(b, z, y):
    x_top = b / 2 + z * y
    xs = [-x_top * 1.1, -b / 2 - z * y, -b / 2, b / 2, b / 2 + z * y, x_top * 1.1]
    zs = [y * 1.15, y, 0.0, 0.0, y, y * 1.15]
    return xs, zs


def perfil_parabolico(t, y, n_pts=24):
    xs, zs = [], []
    for i in range(n_pts + 1):
        frac = i / n_pts
        xs.append((t / 2) * frac)
        zs.append(y * (frac ** 2))
    return [-x for x in reversed(xs)] + xs, list(reversed(zs)) + zs


def perfil_circular(diametro, n_pts=32):
    r = diametro / 2
    angulos = [i * 2 * math.pi / n_pts for i in range(n_pts)]
    return [r * math.sin(a) for a in angulos], [r - r * math.cos(a) for a in angulos]


def perfil_cajon(ancho, alto):
    return [0.0, 0.0, ancho, ancho], [alto, 0.0, 0.0, alto]


def perfil_sumidero(largo_ventana, y):
    """(xs, zs, ancho_caja, profundidad_caja) de la caja NOMINAL de un
    sumidero -- el ancho/profundidad de la caja no se calculan, son
    valores de referencia solo para render/metrados preliminares."""
    profundidad_caja = max(0.6, 3 * y)
    ancho_caja = max(0.6, largo_ventana)
    xs, zs = perfil_cajon(ancho_caja, profundidad_caja)
    return xs, zs, ancho_caja, profundidad_caja


def perfil_muro_nominal(alto=1.5, espesor=0.3):
    """(xs, zs) de un muro delgado NOMINAL -- usado para representar
    vertederos/orificios de Pestaña 8, que no registran las
    dimensiones reales del muro que los contiene."""
    return [0.0, 0.0, espesor, espesor], [alto, 0.0, 0.0, alto]


def perfil_talud_enrocado(d50_m, angulo_talud_deg=33.7):
    """(xs, zs) del talud+capa de enrocado -- categoría "area_solida"
    (el contorno YA es la capa de roca, no un vacío). `angulo_talud_deg`
    es solo para el dibujo/estimación (1.5H:1V típico), no calculado --
    el diseño geotécnico del talud está fuera de este plugin."""
    alto_talud = max(1.5, 6 * d50_m)
    ancho_talud = alto_talud / math.tan(math.radians(angulo_talud_deg))
    espesor_capa = 2 * d50_m  # práctica estándar: espesor mínimo = 2×D50
    a = math.radians(angulo_talud_deg)
    normal = (math.sin(a), math.cos(a))
    xs_talud, zs_talud = [0.0, ancho_talud], [alto_talud, 0.0]
    xs_capa = [x + espesor_capa * normal[0] for x in xs_talud]
    zs_capa = [z + espesor_capa * normal[1] for z in zs_talud]
    xs = xs_talud + list(reversed(xs_capa))
    zs = zs_talud + list(reversed(zs_capa))
    return xs, zs, alto_talud, ancho_talud, espesor_capa


# ======================================================================
# Resolutores: (datos guardados en Pestaña 7/8) -> perfil + categoría
# ======================================================================
def perfil_canal_desde_datos(datos: dict):
    """(xs, zs, etiqueta) del contorno MOJADO de un canal de Pestaña 7
    (self.resultados_hidraulica_drenaje). Categoría "cascara"."""
    forma = str(datos.get("forma", ""))
    y = datos.get("tirante_normal_m")
    if forma.startswith("Rectangular"):
        b = datos.get("b_m")
        if b is None or y is None:
            raise GeometriaNoDisponibleError("faltan b_m/tirante_normal_m para el rectángulo")
        return (*perfil_rectangular(b, y), f"b = {b:.2f} m, y = {y:.2f} m")
    if forma.startswith("Triangular"):
        z = datos.get("z")
        if z is None or y is None:
            raise GeometriaNoDisponibleError("faltan z/tirante_normal_m para el triángulo")
        return (*perfil_triangular(z, y), f"z = {z:.2f} (H:V), y = {y:.2f} m")
    if forma.startswith("Trapezoidal"):
        b, z = datos.get("b_m"), datos.get("z")
        if b is None or z is None or y is None:
            raise GeometriaNoDisponibleError("faltan b_m/z/tirante_normal_m para el trapecio")
        return (*perfil_trapezoidal(b, z, y), f"b = {b:.2f} m, z = {z:.2f}, y = {y:.2f} m")
    if forma == "Parabólico":
        t = datos.get("T_m")
        if t is None or y is None:
            raise GeometriaNoDisponibleError("faltan T_m/tirante_normal_m para la parábola")
        return (*perfil_parabolico(t, y), f"T = {t:.2f} m, y = {y:.2f} m")
    raise GeometriaNoDisponibleError(
        f"la forma «{forma}» (irregular, o cuneta vial Gutter/HEC-22) todavía no está soportada "
        f"en el Módulo BIM.")


def perfil_alcantarilla_desde_datos(datos: dict):
    """(xs, zs, etiqueta) del contorno MOJADO de una alcantarilla de
    Pestaña 7. Categoría "cascara", cerrada (tubo/cajón)."""
    subtipo = str(datos.get("subtipo", ""))
    if subtipo.startswith("Circular"):
        d = datos.get("diametro_m")
        if d is None:
            raise GeometriaNoDisponibleError(
                "esta alcantarilla se calculó con una versión anterior del plugin que no "
                "guardaba el diámetro -- vuelva a la Pestaña 7 y presione «Calcular» de nuevo.")
        return (*perfil_circular(d), f"D = {d:.2f} m")
    ancho, alto = datos.get("ancho_m"), datos.get("alto_m")
    if ancho is None or alto is None:
        raise GeometriaNoDisponibleError(
            "esta alcantarilla se calculó con una versión anterior del plugin que no guardaba "
            "ancho/alto -- vuelva a la Pestaña 7 y presione «Calcular» de nuevo.")
    return (*perfil_cajon(ancho, alto), f"ancho = {ancho:.2f} m, alto = {alto:.2f} m")


# ======================================================================
# Área de un polígono cerrado (fórmula del shoelace) -- usada para la
# categoría "area_solida" (enrocado, defensa, muros esquemáticos).
# ======================================================================
def area_poligono(xs, zs) -> float:
    n = len(xs)
    doble_area = 0.0
    for i in range(n):
        j = (i + 1) % n
        doble_area += xs[i] * zs[j] - xs[j] * zs[i]
    return abs(doble_area) / 2.0


def longitud_perimetro(xs, zs, cerrado: bool) -> float:
    n = len(xs)
    rango = range(n) if cerrado else range(n - 1)
    total = 0.0
    for i in rango:
        j = (i + 1) % n
        total += math.hypot(xs[j] - xs[i], zs[j] - zs[i])
    return total


# ======================================================================
# Perfil SÓLIDO (material real, no el vacío) -- usado por la
# exportación IFC (fase 3). Envuelve el contorno "cascara" con un
# espesor constante para obtener el contorno de concreto real, en vez
# de exportar el vacío mojado como si fuera el material.
# ======================================================================
def desplazar_contorno_normal(xs, zs, distancia):
    """Desplaza cada vértice del contorno una distancia `distancia`
    hacia AFUERA (perpendicular local a cada segmento) -- misma lógica
    que ui/cross_section_canvas.py::_offset_perpendicular. Válido para
    cualquier perfil de este módulo porque todos se recorren en el
    mismo sentido (de la esquina superior izquierda, bajando por el
    fondo, hasta la esquina superior derecha; o una vuelta completa en
    sentido antihorario para las secciones cerradas) -- en ambos casos,
    rotar el vector tangente 90° en sentido HORARIO da el normal que
    apunta hacia afuera del área mojada."""
    n = len(xs)
    xs_ext, zs_ext = [], []
    for i in range(n):
        i0, i1 = max(i - 1, 0), min(i + 1, n - 1)
        dx, dz = xs[i1] - xs[i0], zs[i1] - zs[i0]
        norma = math.hypot(dx, dz) or 1.0
        nx, nz = dz / norma, -dx / norma
        xs_ext.append(xs[i] + nx * distancia)
        zs_ext.append(zs[i] + nz * distancia)
    return xs_ext, zs_ext


def perfil_solido_cascara(xs, zs, cerrado: bool, espesor: float):
    """Contorno 2D del material SÓLIDO (concreto) de una estructura tipo
    "cascara" -- envuelve el contorno mojado (xs, zs) con `espesor`
    constante. Devuelve (xs_poligono, zs_poligono, xs_hueco, zs_hueco):

      - Perfil ABIERTO (canal): un único polígono simple que recorre el
        borde mojado y regresa por el borde exterior -- mismo patrón
        que el relleno 2D de _dibujar_muro() en cross_section_canvas.py.
        xs_hueco/zs_hueco quedan en None (no hay hueco que declarar).
      - Perfil CERRADO (alcantarilla/sumidero): xs_poligono/zs_poligono
        es el anillo EXTERIOR y xs_hueco/zs_hueco es el anillo interior
        (el vacío mojado) -- listo para un IfcArbitraryProfileDefWithVoids."""
    xs_ext, zs_ext = desplazar_contorno_normal(xs, zs, espesor)
    if not cerrado:
        return list(xs) + list(reversed(xs_ext)), list(zs) + list(reversed(zs_ext)), None, None
    return xs_ext, zs_ext, list(xs), list(zs)


# ======================================================================
# Contorno del muro/losa por fuente -- usado por el diseño de refuerzo
# (core/bim_refuerzo.py), la exportación IFC (core/bim_ifc.py) y el
# overlay 3D de acero (ui/bim_canvas.py / plugin_dialog.py) para que
# las tres partes recorten EXACTAMENTE el mismo contorno de concreto.
# ======================================================================
def contorno_muro_pestana7(datos: dict):
    """(xs, zs, cerrado) del contorno del muro/losa de concreto para
    una estructura de Pestaña 7 -- solo Canal/Alcantarilla/Sumidero
    tienen muro de concreto real (categoría "cascara"). Devuelve
    (None, None, None) si el tipo no aplica (roca, o solo verificación
    de borde libre sin geometría de material)."""
    tipo = datos.get("tipo", "")
    if tipo == "Canal":
        xs, zs, _ = perfil_canal_desde_datos(datos)
        return xs, zs, False
    if tipo == "Alcantarilla":
        xs, zs, _ = perfil_alcantarilla_desde_datos(datos)
        return xs, zs, True
    if tipo == "Sumidero":
        xs, zs, _, _ = perfil_sumidero(datos.get("L_m"), datos.get("y_m"))
        return xs, zs, True
    return None, None, None


def contorno_muro_pestana8(estructura):
    """(xs, zs, cerrado) del contorno del muro nominal para una
    estructura de Pestaña 8 (alcantarilla/vertedero/orificio -- las
    únicas con muro esquemático). Devuelve (None, None, None) si el
    tipo no es reconocido."""
    tipo = estructura.tipo
    p = estructura.parametros
    if tipo == "alcantarilla":
        xs, zs = perfil_circular(p.get("diametro"))
        return xs, zs, True
    if tipo == "vertedero":
        xs, zs = perfil_muro_nominal()
        return xs, zs, True
    if tipo == "orificio":
        area = p.get("area", 0.5)
        lado = math.sqrt(max(area, 1e-6))
        xs, zs = perfil_muro_nominal(alto=max(lado * 1.8, 1.5))
        return xs, zs, True
    return None, None, None
