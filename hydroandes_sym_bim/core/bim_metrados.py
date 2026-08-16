# -*- coding: utf-8 -*-
"""
core/bim_metrados.py

Metrados (cantidades) preliminares para la estructura seleccionada en
el Módulo BIM (Pestaña 8b, fase 2 de 3). Parte de la MISMA geometría
que usa el render 3D (core/bim_geometry.py), así que las dimensiones
mostradas y las cantidades calculadas nunca pueden desincronizarse.

IMPORTANTE -- alcance y limitaciones (léase antes de usar en un
expediente técnico):
  - El espesor de muro/losa y la cuantía de acero son ASUNCIONES que
    usted debe verificar/ajustar en la Pestaña 8b -- este plugin NO
    hace diseño estructural (no calcula espesores por flexión/corte, ni
    cuantías de acero por análisis estructural). Son valores de
    referencia para una estimación preliminar de cantidades, no para
    un expediente técnico definitivo.
  - El volumen de concreto de canales/alcantarillas/sumideros se
    calcula como (espesor de muro) × (perímetro del contorno mojado) ×
    (longitud) -- una aproximación estándar para muros/losas delgados
    respecto al radio de curvatura de la sección (válida para las
    secciones de este plugin), sin juntas, cimentación ni refuerzos
    locales.
  - El volumen de excavación es un PRISMA envolvente (dimensiones
    externas + un margen de trabajo lateral/inferior ajustable), no un
    cómputo de movimiento de tierras real (que depende de la
    topografía real y los taludes de corte según el tipo de suelo).
  - El encofrado es el área de las 2 caras del muro/losa (interior +
    exterior) -- en la práctica, muros contra el terreno natural a
    veces no llevan encofrado exterior; ajuste el resultado según su
    caso.
  - El enrocado (RipRap/Defensa Ribereña) NO es concreto: su "volumen"
    es el de la capa de roca, sin encofrado ni acero.
  - Pontón, Puente y Defensa* solo verifican borde libre en Pestaña 7
    (*Defensa sí tiene enrocado) -- Pontón/Puente no tienen metrados
    porque no hay geometría de material sobre la que calcularlos.
"""
import math

from . import bim_geometry as bg


class MetradoNoAplicaError(Exception):
    """La estructura seleccionada no tiene una geometría de material
    (solo una verificación, ej. borde libre de Pontón/Puente) -- no hay
    metrados que calcular."""


# ======================================================================
# Cálculos genéricos de cantidades, a partir de un perfil (xs, zs) --
# ver core/bim_geometry.py para qué representa cada categoría.
# ======================================================================
def metrados_cascara(xs, zs, cerrado: bool, longitud_m: float, espesor_muro_m: float,
                      margen_excavacion_m: float = 0.30, cuantia_acero_kg_m3=None) -> dict:
    """Categoría "cascara" (canal/alcantarilla/sumidero): xs/zs es el
    contorno MOJADO -- el concreto envuelve ese contorno con un espesor
    constante `espesor_muro_m`."""
    perimetro = bg.longitud_perimetro(xs, zs, cerrado)
    area_muro_transversal_m2 = perimetro * espesor_muro_m
    volumen_concreto_m3 = area_muro_transversal_m2 * longitud_m
    area_encofrado_m2 = 2 * perimetro * longitud_m  # cara interior + exterior

    ancho_total = (max(xs) - min(xs)) + 2 * margen_excavacion_m
    alto_total = (max(zs) - min(zs)) + margen_excavacion_m
    volumen_excavacion_m3 = ancho_total * alto_total * longitud_m

    resultado = {
        "categoria": "cascara", "material": "concreto",
        "perimetro_mojado_m": round(perimetro, 3),
        "espesor_muro_m": round(espesor_muro_m, 3),
        "area_muro_transversal_m2": round(area_muro_transversal_m2, 4),
        "volumen_concreto_m3": round(volumen_concreto_m3, 3),
        "area_encofrado_m2": round(area_encofrado_m2, 3),
        "margen_excavacion_lateral_m": round(margen_excavacion_m, 3),
        "volumen_excavacion_m3": round(volumen_excavacion_m3, 3),
    }
    if cuantia_acero_kg_m3:
        resultado["cuantia_acero_kg_m3"] = cuantia_acero_kg_m3
        resultado["peso_acero_estimado_kg"] = round(volumen_concreto_m3 * cuantia_acero_kg_m3, 1)
    return resultado


def metrados_area_solida(xs, zs, longitud_m: float, material: str,
                          es_concreto: bool = False, cuantia_acero_kg_m3=None) -> dict:
    """Categoría "area_solida" (enrocado/defensa/muros esquemáticos de
    Pestaña 8): xs/zs YA es el contorno del material sólido -- volumen
    = área del contorno × longitud, sin envolver una cáscara adicional."""
    area = bg.area_poligono(xs, zs)
    volumen_m3 = area * longitud_m
    resultado = {
        "categoria": "area_solida", "material": material,
        "area_transversal_m2": round(area, 4),
        "volumen_m3": round(volumen_m3, 3),
    }
    if es_concreto and cuantia_acero_kg_m3:
        resultado["cuantia_acero_kg_m3"] = cuantia_acero_kg_m3
        resultado["peso_acero_estimado_kg"] = round(volumen_m3 * cuantia_acero_kg_m3, 1)
    return resultado


# ======================================================================
# Despachadores por fuente -- misma lógica de "qué tipo usa qué
# geometría" que ui/bim_canvas.py, pero aplicada a metrados en vez de
# al render 3D.
# ======================================================================
def metrados_desde_pestana7(nombre: str, datos: dict, longitud_m: float, espesor_muro_m: float,
                             margen_excavacion_m: float = 0.30, cuantia_acero_kg_m3=None) -> dict:
    tipo = datos.get("tipo", "")
    etiqueta = ""
    if tipo == "Canal":
        xs, zs, etiqueta = bg.perfil_canal_desde_datos(datos)
        r = metrados_cascara(xs, zs, False, longitud_m, espesor_muro_m, margen_excavacion_m, cuantia_acero_kg_m3)
    elif tipo == "Alcantarilla":
        xs, zs, etiqueta = bg.perfil_alcantarilla_desde_datos(datos)
        r = metrados_cascara(xs, zs, True, longitud_m, espesor_muro_m, margen_excavacion_m, cuantia_acero_kg_m3)
    elif tipo == "Sumidero":
        largo_ventana, y = datos.get("L_m"), datos.get("y_m")
        if largo_ventana is None or y is None:
            raise bg.GeometriaNoDisponibleError("faltan L_m/y_m del sumidero")
        xs, zs, ancho_caja, profundidad_caja = bg.perfil_sumidero(largo_ventana, y)
        r = metrados_cascara(xs, zs, True, largo_ventana, espesor_muro_m, margen_excavacion_m, cuantia_acero_kg_m3)
        longitud_m = largo_ventana
        etiqueta = f"caja {ancho_caja:.2f} × {profundidad_caja:.2f} m"
    elif tipo in ("Enrocado (RipRap)", "Defensa Ribereña"):
        d50 = datos.get("D50_m")
        if d50 is None:
            raise bg.GeometriaNoDisponibleError(f"falta D50_m para {tipo}")
        xs, zs, _, _, espesor_capa = bg.perfil_talud_enrocado(d50)
        r = metrados_area_solida(xs, zs, longitud_m, material="roca (enrocado de protección)")
        etiqueta = f"D50 = {d50 * 100:.1f} cm, espesor de capa ≈ {espesor_capa:.2f} m"
    elif tipo in ("Pontón", "Puente"):
        raise MetradoNoAplicaError(
            f"{tipo} solo registra verificación de borde libre en Pestaña 7 (sin luz, ancho ni "
            f"espesor de losa reales) -- no hay una geometría de material sobre la que calcular "
            f"metrados. Un diseño estructural aparte (fuera del alcance de este plugin) es "
            f"necesario para dimensionar y metrar esta estructura.")
    else:
        raise bg.GeometriaNoDisponibleError(f"el tipo «{tipo}» todavía no tiene metrados en el módulo BIM.")
    r.update({"nombre": nombre, "tipo": tipo, "longitud_m": round(longitud_m, 2), "geometria": etiqueta})
    return r


def metrados_desde_pestana8(estructura, espesor_muro_m: float,
                             margen_excavacion_m: float = 0.30, cuantia_acero_kg_m3=None) -> dict:
    tipo = estructura.tipo
    p = estructura.parametros
    if tipo == "alcantarilla":
        d = p.get("diametro")
        longitud_m = p.get("longitud", 10.0)
        if not d:
            raise bg.GeometriaNoDisponibleError("falta el diámetro de la alcantarilla")
        xs, zs = bg.perfil_circular(d)
        r = metrados_cascara(xs, zs, True, longitud_m, espesor_muro_m, margen_excavacion_m, cuantia_acero_kg_m3)
        etiqueta = f"D = {d:.2f} m"
    elif tipo == "vertedero":
        longitud_m = p.get("longitud", 5.0)
        xs, zs = bg.perfil_muro_nominal()
        r = metrados_area_solida(xs, zs, longitud_m, material="concreto (muro nominal)",
                                  es_concreto=True, cuantia_acero_kg_m3=cuantia_acero_kg_m3)
        r["nota"] = ("muro NOMINAL (alto=1.5 m, espesor=0.3 m) -- la Pestaña 8 no registra las "
                     "dimensiones reales del muro del vertedero.")
        etiqueta = f"longitud de cresta = {longitud_m:.2f} m"
    elif tipo == "orificio":
        area = p.get("area", 0.5)
        lado = math.sqrt(max(area, 1e-6))
        xs, zs = bg.perfil_muro_nominal(alto=max(lado * 1.8, 1.5))
        longitud_m = lado
        r = metrados_area_solida(xs, zs, longitud_m, material="concreto (muro nominal)",
                                  es_concreto=True, cuantia_acero_kg_m3=cuantia_acero_kg_m3)
        r["nota"] = "muro NOMINAL -- la Pestaña 8 no registra las dimensiones reales del muro/orificio."
        etiqueta = f"área = {area:.3f} m²"
    else:
        raise bg.GeometriaNoDisponibleError(f"tipo de estructura de Pestaña 8 no reconocido: «{tipo}»")
    r.update({"nombre": estructura.nombre, "tipo": f"{tipo} (Pestaña 8, esquemático)",
              "longitud_m": round(longitud_m, 2), "geometria": etiqueta})
    return r
