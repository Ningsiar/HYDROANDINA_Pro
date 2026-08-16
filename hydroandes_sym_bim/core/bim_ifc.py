# -*- coding: utf-8 -*-
"""
core/bim_ifc.py

Exportación IFC (Módulo BIM, fase 3 de 3) -- genera un archivo .ifc
(Industry Foundation Classes, IFC4) con la geometría 3D real de la
estructura seleccionada MÁS sus metrados como propiedades del elemento
(Pset_HydroAndesMetrados), listo para federar en Revit, Navisworks,
ArchiCAD, Tekla, BIM Vision, o cualquier otro software que lea IFC --
el estándar abierto para esto. No existe forma de generar un .rvt
nativo de Revit fuera del propio Revit (Autodesk no lo permite desde
software externo).

Reutiliza EXACTAMENTE la misma geometría que el render 3D
(ui/bim_canvas.py) y los mismos metrados (core/bim_metrados.py), a
través de core/bim_geometry.py -- así el archivo IFC nunca puede
desincronizarse de lo que el usuario vio en pantalla ni de las
cantidades que ya revisó.

Para estructuras tipo "cascara" (canal/alcantarilla/sumidero) se
exporta el material SÓLIDO real (concreto envolviendo el contorno
mojado con el espesor indicado -- ver
core/bim_geometry.py::perfil_solido_cascara), no el vacío por donde
pasa el agua.

Import perezoso de ifcopenshell (igual que python-docx/openpyxl en
core/table_export.py): si no está instalado, se informa con un mensaje
claro en vez de romper el resto del plugin.
"""
import math

from . import bim_geometry as bg
from . import bim_metrados as bmet


def _requerir_ifcopenshell():
    try:
        import ifcopenshell
        import ifcopenshell.api
    except ImportError as e:
        raise ImportError(
            "Falta la librería 'ifcopenshell' para exportar a IFC. Instálela en el Python de "
            "QGIS con: python-qgis.bat -m pip install ifcopenshell"
        ) from e
    return ifcopenshell


def _crear_archivo_base(ifcopenshell_mod, nombre_proyecto, autor, organizacion):
    ifc = ifcopenshell_mod.api.run("project.create_file", version="IFC4")
    proyecto = ifcopenshell_mod.api.run(
        "root.create_entity", ifc, ifc_class="IfcProject", name=nombre_proyecto)
    # Metros explícitos -- sin esto, unit.assign_unit() por defecto deja
    # el archivo en MILÍMETROS (habitual en IFC, pero aquí todo el
    # plugin trabaja en metros; declararlo evita cualquier confusión al
    # inspeccionar los valores crudos del archivo).
    ifcopenshell_mod.api.run("unit.assign_unit", ifc, length={"is_metric": True, "raw": "METERS"})
    if autor or organizacion:
        try:
            persona = ifcopenshell_mod.api.run("owner.add_person", ifc, family_name=autor or "")
            org = ifcopenshell_mod.api.run("owner.add_organisation", ifc, name=organizacion or "")
            ifcopenshell_mod.api.run(
                "owner.add_person_and_organisation", ifc, person=persona, organisation=org)
        except Exception:
            pass  # metadatos de autoría -- no crítico si falla en alguna versión de ifcopenshell
    sitio = ifcopenshell_mod.api.run("root.create_entity", ifc, ifc_class="IfcSite", name="Sitio")
    edificio = ifcopenshell_mod.api.run(
        "root.create_entity", ifc, ifc_class="IfcBuilding", name="Estructura hidráulica")
    nivel = ifcopenshell_mod.api.run(
        "root.create_entity", ifc, ifc_class="IfcBuildingStorey", name="Nivel 0")
    ifcopenshell_mod.api.run("aggregate.assign_object", ifc, relating_object=proyecto, products=[sitio])
    ifcopenshell_mod.api.run("aggregate.assign_object", ifc, relating_object=sitio, products=[edificio])
    ifcopenshell_mod.api.run("aggregate.assign_object", ifc, relating_object=edificio, products=[nivel])
    contexto = ifcopenshell_mod.api.run("context.add_context", ifc, context_type="Model")
    subcontexto = ifcopenshell_mod.api.run(
        "context.add_context", ifc, context_type="Model", context_identifier="Body",
        target_view="MODEL_VIEW", parent=contexto)
    return ifc, nivel, subcontexto


def _poligono(ifc, xs, zs):
    puntos = list(zip(xs, zs))
    if puntos[0] != puntos[-1]:
        puntos = puntos + [puntos[0]]  # IfcPolyline cerrada: primer punto == último
    return ifc.create_entity(
        "IfcPolyline",
        Points=[ifc.create_entity("IfcCartesianPoint", Coordinates=(float(x), float(z)))
                for x, z in puntos])


def _agregar_elemento(ifc, ifcopenshell_mod, nivel, subcontexto, nombre,
                       xs_poligono, zs_poligono, xs_hueco, zs_hueco, longitud_m):
    elemento = ifcopenshell_mod.api.run(
        "root.create_entity", ifc, ifc_class="IfcBuildingElementProxy", name=nombre)
    ifcopenshell_mod.api.run("spatial.assign_container", ifc, relating_structure=nivel, products=[elemento])
    ifcopenshell_mod.api.run("geometry.edit_object_placement", ifc, product=elemento)

    outer = _poligono(ifc, xs_poligono, zs_poligono)
    if xs_hueco is not None:
        inner = _poligono(ifc, xs_hueco, zs_hueco)
        perfil = ifc.create_entity("IfcArbitraryProfileDefWithVoids", ProfileType="AREA",
                                    OuterCurve=outer, InnerCurves=[inner])
    else:
        perfil = ifc.create_entity("IfcArbitraryClosedProfileDef", ProfileType="AREA", OuterCurve=outer)

    representacion = ifcopenshell_mod.api.run(
        "geometry.add_profile_representation", ifc, context=subcontexto,
        profile=perfil, depth=float(longitud_m))
    ifcopenshell_mod.api.run("geometry.assign_representation", ifc, product=elemento, representation=representacion)
    return elemento


# Metrados (claves de core/bim_metrados.py) -> nombre de propiedad IFC.
_MAPA_PROPIEDADES_METRADOS = {
    "volumen_concreto_m3": "VolumenConcreto_m3",
    "area_encofrado_m2": "AreaEncofrado_m2",
    "volumen_excavacion_m3": "VolumenExcavacion_m3",
    "volumen_m3": "Volumen_m3",
    "peso_acero_estimado_kg": "PesoAceroEstimado_kg",
    "cuantia_acero_kg_m3": "CuantiaAcero_kg_m3",
    "espesor_muro_m": "EspesorMuroLosa_m",
    "perimetro_mojado_m": "PerimetroMojado_m",
    "area_transversal_m2": "AreaTransversal_m2",
    "material": "Material",
    "geometria": "Geometria",
    "longitud_m": "Longitud_m",
}


def _agregar_pset_metrados(ifc, ifcopenshell_mod, elemento, metrados: dict):
    propiedades = {clave_ifc: metrados[clave_origen]
                   for clave_origen, clave_ifc in _MAPA_PROPIEDADES_METRADOS.items()
                   if clave_origen in metrados}
    propiedades["Nota"] = (
        "Cantidades preliminares generadas por HydroAndes SYM BIM -- NO son diseño estructural. "
        "El espesor de muro/losa y la cuantía de acero son asunciones del usuario."
    )
    pset = ifcopenshell_mod.api.run("pset.add_pset", ifc, product=elemento, name="Pset_HydroAndesMetrados")
    ifcopenshell_mod.api.run("pset.edit_pset", ifc, pset=pset, properties=propiedades)


def exportar_ifc_pestana7(ruta: str, nombre: str, datos: dict, longitud_m: float, espesor_muro_m: float,
                           margen_excavacion_m: float = 0.30, cuantia_acero_kg_m3=None,
                           autor: str = "", organizacion: str = "") -> dict:
    """Genera un archivo IFC para UNA estructura de Pestaña 7. Levanta
    ImportError si falta ifcopenshell, bim_geometry.GeometriaNoDisponibleError
    si faltan datos, o bim_metrados.MetradoNoAplicaError si el tipo no
    tiene geometría de material (Pontón/Puente). Devuelve el dict de
    metrados usado (mismo que ve el usuario en la tabla de la Pestaña 8b)."""
    ifcopenshell_mod = _requerir_ifcopenshell()
    tipo = datos.get("tipo", "")

    # Se calculan los metrados PRIMERO: además de ir al Pset del IFC,
    # su misma cadena de validación (mismos tipos soportados, mismos
    # errores) es la que decide si hay o no geometría exportable --
    # evita mantener dos listas de "tipos soportados" por separado.
    metrados = bmet.metrados_desde_pestana7(nombre, datos, longitud_m, espesor_muro_m,
                                             margen_excavacion_m, cuantia_acero_kg_m3)

    if tipo == "Canal":
        xs, zs, _ = bg.perfil_canal_desde_datos(datos)
        xs_p, zs_p, xs_h, zs_h = bg.perfil_solido_cascara(xs, zs, cerrado=False, espesor=espesor_muro_m)
    elif tipo == "Alcantarilla":
        xs, zs, _ = bg.perfil_alcantarilla_desde_datos(datos)
        xs_p, zs_p, xs_h, zs_h = bg.perfil_solido_cascara(xs, zs, cerrado=True, espesor=espesor_muro_m)
    elif tipo == "Sumidero":
        xs, zs, _, _ = bg.perfil_sumidero(datos.get("L_m"), datos.get("y_m"))
        xs_p, zs_p, xs_h, zs_h = bg.perfil_solido_cascara(xs, zs, cerrado=True, espesor=espesor_muro_m)
        longitud_m = datos.get("L_m")
    else:  # "Enrocado (RipRap)" / "Defensa Ribereña" -- categoría area_solida
        xs_p, zs_p, _, _, _ = bg.perfil_talud_enrocado(datos.get("D50_m"))
        xs_h = zs_h = None

    ifc, nivel, subcontexto = _crear_archivo_base(ifcopenshell_mod, nombre, autor, organizacion)
    elemento = _agregar_elemento(ifc, ifcopenshell_mod, nivel, subcontexto, nombre,
                                  xs_p, zs_p, xs_h, zs_h, longitud_m)
    _agregar_pset_metrados(ifc, ifcopenshell_mod, elemento, metrados)
    ifc.write(ruta)
    return metrados


def exportar_ifc_pestana8(ruta: str, estructura, espesor_muro_m: float,
                           margen_excavacion_m: float = 0.30, cuantia_acero_kg_m3=None,
                           autor: str = "", organizacion: str = "") -> dict:
    """Genera un archivo IFC para UNA estructura de Pestaña 8
    (core.swe2d.Estructura). Ver exportar_ifc_pestana7 para el
    comportamiento de errores."""
    ifcopenshell_mod = _requerir_ifcopenshell()
    tipo = estructura.tipo
    p = estructura.parametros

    metrados = bmet.metrados_desde_pestana8(estructura, espesor_muro_m, margen_excavacion_m, cuantia_acero_kg_m3)

    if tipo == "alcantarilla":
        longitud_m = p.get("longitud", 10.0)
        xs, zs = bg.perfil_circular(p.get("diametro"))
        xs_p, zs_p, xs_h, zs_h = bg.perfil_solido_cascara(xs, zs, cerrado=True, espesor=espesor_muro_m)
    elif tipo == "vertedero":
        longitud_m = p.get("longitud", 5.0)
        xs_p, zs_p = bg.perfil_muro_nominal()
        xs_h = zs_h = None
    else:  # "orificio"
        area = p.get("area", 0.5)
        longitud_m = math.sqrt(max(area, 1e-6))
        xs_p, zs_p = bg.perfil_muro_nominal(alto=max(longitud_m * 1.8, 1.5))
        xs_h = zs_h = None

    ifc, nivel, subcontexto = _crear_archivo_base(ifcopenshell_mod, estructura.nombre, autor, organizacion)
    elemento = _agregar_elemento(ifc, ifcopenshell_mod, nivel, subcontexto, estructura.nombre,
                                  xs_p, zs_p, xs_h, zs_h, longitud_m)
    _agregar_pset_metrados(ifc, ifcopenshell_mod, elemento, metrados)
    ifc.write(ruta)
    return metrados
