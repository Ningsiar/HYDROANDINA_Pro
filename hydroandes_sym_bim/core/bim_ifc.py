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
from . import bim_refuerzo as bref


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


# Metrados de refuerzo (claves de core/bim_refuerzo.py::calcular_refuerzo) ->
# nombre de propiedad IFC, fase 5.
_MAPA_PROPIEDADES_REFUERZO = {
    "caso_gobernante": "CasoGobernante",
    "momento_diseno_kN_m_por_m": "MomentoDiseno_kNm_por_m",
    "barra_principal": "BarraPrincipal",
    "espaciamiento_principal_cm": "EspaciamientoPrincipal_cm",
    "as_principal_cm2_m": "AsPrincipal_cm2_por_m",
    "barra_temperatura": "BarraTemperatura",
    "espaciamiento_temperatura_cm": "EspaciamientoTemperatura_cm",
    "as_temperatura_cm2_m": "AsTemperatura_cm2_por_m",
    "peso_acero_principal_kg": "PesoAceroPrincipal_kg",
    "peso_acero_temperatura_kg": "PesoAceroTemperatura_kg",
    "peso_acero_total_kg": "PesoAceroTotal_kg",
    "cortante_cumple": "CortanteCumple",
}


def _agregar_pset_refuerzo(ifc, ifcopenshell_mod, elemento, resultado_refuerzo: dict):
    propiedades = {clave_ifc: resultado_refuerzo[clave_origen]
                   for clave_origen, clave_ifc in _MAPA_PROPIEDADES_REFUERZO.items()
                   if clave_origen in resultado_refuerzo}
    propiedades["Metodo"] = resultado_refuerzo.get("metodo", "")
    propiedades["Nota"] = (
        "Diseño de refuerzo PRELIMINAR (E.060/E.030) generado por HydroAndes SYM BIM -- "
        "no reemplaza la revisión de un ingeniero estructural/geotécnico colegiado."
    )
    pset = ifcopenshell_mod.api.run("pset.add_pset", ifc, product=elemento, name="Pset_HydroAndesRefuerzo")
    ifcopenshell_mod.api.run("pset.edit_pset", ifc, pset=pset, properties=propiedades)


def _longitud_polilinea(puntos):
    total = 0.0
    for a, b in zip(puntos, puntos[1:]):
        total += math.dist(a, b)
    return total


def _crear_representacion_barra(ifc, subcontexto, puntos_3d, radio_m):
    puntos_ifc = [ifc.create_entity("IfcCartesianPoint", Coordinates=(float(x), float(y), float(z)))
                  for (x, y, z) in puntos_3d]
    directriz = ifc.create_entity("IfcPolyline", Points=puntos_ifc)
    solido = ifc.create_entity("IfcSweptDiskSolid", Directrix=directriz, Radius=float(radio_m))
    return ifc.create_entity(
        "IfcShapeRepresentation", ContextOfItems=subcontexto, RepresentationIdentifier="Body",
        RepresentationType="AdvancedSweptSolid", Items=[solido])


def _agregar_barra_refuerzo(ifc, ifcopenshell_mod, nivel, subcontexto, nombre, puntos_3d,
                             radio_m, area_cm2, predefined_type="MAIN"):
    """Crea UNA IfcReinforcingBar con geometría real (IfcSweptDiskSolid
    barrida a lo largo de `puntos_3d`) -- radio_m constante, sin
    empalmes ni ganchos (disposición esquemática, ver docstring de
    core/bim_refuerzo.py::geometria_barras_refuerzo)."""
    if len(puntos_3d) < 2 or radio_m <= 0:
        return None
    barra = ifcopenshell_mod.api.run(
        "root.create_entity", ifc, ifc_class="IfcReinforcingBar", name=nombre)
    longitud_m = _longitud_polilinea(puntos_3d)
    try:
        barra.NominalDiameter = round(radio_m * 2000.0, 1)  # radio (m) -> diámetro (mm)
        barra.CrossSectionArea = round(area_cm2 / 10000.0, 6)  # cm² -> m²
        barra.BarLength = round(longitud_m, 3)
        barra.PredefinedType = predefined_type
    except Exception:
        pass  # atributos opcionales -- no crítico si el esquema de la versión difiere
    ifcopenshell_mod.api.run("spatial.assign_container", ifc, relating_structure=nivel, products=[barra])
    ifcopenshell_mod.api.run("geometry.edit_object_placement", ifc, product=barra)
    representacion = _crear_representacion_barra(ifc, subcontexto, puntos_3d, radio_m)
    ifcopenshell_mod.api.run("geometry.assign_representation", ifc, product=barra, representation=representacion)
    return barra


def _agregar_barras_refuerzo(ifc, ifcopenshell_mod, nivel, subcontexto, geometria: dict) -> int:
    """Crea una IfcReinforcingBar real por cada barra física en
    `geometria` (ver core/bim_refuerzo.py::geometria_barras_refuerzo)
    -- así el modelo federado muestra el acero (costillas = barras
    principales de flexión, longitudinales = temperatura/repartición),
    no solo una propiedad de texto. Devuelve el número de barras
    creadas."""
    costillas = geometria.get("costillas") or []
    longitudinales = geometria.get("longitudinales") or []
    cerrado = bool(geometria.get("cerrado"))
    diam_principal_cm = geometria.get("diametro_principal_cm", 1.27)
    diam_temperatura_cm = geometria.get("diametro_temperatura_cm", 0.95)
    radio_principal_m = diam_principal_cm / 200.0
    radio_temperatura_m = diam_temperatura_cm / 200.0
    area_principal_cm2 = math.pi * (diam_principal_cm / 2.0) ** 2
    area_temperatura_cm2 = math.pi * (diam_temperatura_cm / 2.0) ** 2

    n_creadas = 0
    for i, costilla in enumerate(costillas):
        puntos = list(costilla)
        if cerrado and puntos and puntos[0] != puntos[-1]:
            puntos = puntos + [puntos[0]]
        barra = _agregar_barra_refuerzo(
            ifc, ifcopenshell_mod, nivel, subcontexto, f"Refuerzo principal {i + 1}",
            puntos, radio_principal_m, area_principal_cm2, predefined_type="MAIN")
        if barra is not None:
            n_creadas += 1
    for i, linea in enumerate(longitudinales):
        barra = _agregar_barra_refuerzo(
            ifc, ifcopenshell_mod, nivel, subcontexto, f"Refuerzo temperatura {i + 1}",
            list(linea), radio_temperatura_m, area_temperatura_cm2, predefined_type="USERDEFINED")
        if barra is not None:
            barra.ObjectType = "Acero de temperatura / repartición"
            n_creadas += 1
    return n_creadas


def exportar_ifc_pestana7(ruta: str, nombre: str, datos: dict, longitud_m: float, espesor_muro_m: float,
                           margen_excavacion_m: float = 0.30, cuantia_acero_kg_m3=None,
                           autor: str = "", organizacion: str = "", resultado_refuerzo: dict = None) -> dict:
    """Genera un archivo IFC para UNA estructura de Pestaña 7. Levanta
    ImportError si falta ifcopenshell, bim_geometry.GeometriaNoDisponibleError
    si faltan datos, o bim_metrados.MetradoNoAplicaError si el tipo no
    tiene geometría de material (Pontón/Puente). Devuelve el dict de
    metrados usado (mismo que ve el usuario en la tabla de la Pestaña 8b).

    Si se pasa `resultado_refuerzo` (dict de
    core/bim_refuerzo.py::calcular_refuerzo, tipos Canal/Alcantarilla/
    Sumidero solamente), se agregan además las barras de acero como
    IfcReinforcingBar reales -- geometría, no solo texto -- más un
    segundo Pset (Pset_HydroAndesRefuerzo) con el diseño estructural."""
    ifcopenshell_mod = _requerir_ifcopenshell()
    tipo = datos.get("tipo", "")

    # Se calculan los metrados PRIMERO: además de ir al Pset del IFC,
    # su misma cadena de validación (mismos tipos soportados, mismos
    # errores) es la que decide si hay o no geometría exportable --
    # evita mantener dos listas de "tipos soportados" por separado.
    metrados = bmet.metrados_desde_pestana7(nombre, datos, longitud_m, espesor_muro_m,
                                             margen_excavacion_m, cuantia_acero_kg_m3)

    xs_muro = zs_muro = None
    cerrado_muro = False
    if tipo == "Canal":
        xs, zs, _ = bg.perfil_canal_desde_datos(datos)
        xs_p, zs_p, xs_h, zs_h = bg.perfil_solido_cascara(xs, zs, cerrado=False, espesor=espesor_muro_m)
        xs_muro, zs_muro, cerrado_muro = xs, zs, False
    elif tipo == "Alcantarilla":
        xs, zs, _ = bg.perfil_alcantarilla_desde_datos(datos)
        xs_p, zs_p, xs_h, zs_h = bg.perfil_solido_cascara(xs, zs, cerrado=True, espesor=espesor_muro_m)
        xs_muro, zs_muro, cerrado_muro = xs, zs, True
    elif tipo == "Sumidero":
        xs, zs, _, _ = bg.perfil_sumidero(datos.get("L_m"), datos.get("y_m"))
        xs_p, zs_p, xs_h, zs_h = bg.perfil_solido_cascara(xs, zs, cerrado=True, espesor=espesor_muro_m)
        longitud_m = datos.get("L_m")
        xs_muro, zs_muro, cerrado_muro = xs, zs, True
    else:  # "Enrocado (RipRap)" / "Defensa Ribereña" -- categoría area_solida
        xs_p, zs_p, _, _, _ = bg.perfil_talud_enrocado(datos.get("D50_m"))
        xs_h = zs_h = None

    ifc, nivel, subcontexto = _crear_archivo_base(ifcopenshell_mod, nombre, autor, organizacion)
    elemento = _agregar_elemento(ifc, ifcopenshell_mod, nivel, subcontexto, nombre,
                                  xs_p, zs_p, xs_h, zs_h, longitud_m)
    _agregar_pset_metrados(ifc, ifcopenshell_mod, elemento, metrados)

    if resultado_refuerzo is not None and xs_muro is not None:
        geo = bref.geometria_barras_refuerzo(
            xs_muro, zs_muro, cerrado=cerrado_muro, longitud_m=longitud_m, espesor_muro_m=espesor_muro_m,
            espaciamiento_principal_cm=resultado_refuerzo["espaciamiento_principal_cm"],
            espaciamiento_temperatura_cm=resultado_refuerzo["espaciamiento_temperatura_cm"],
            diametro_barra=resultado_refuerzo.get("barra_principal", "1/2\""),
            diametro_barra_temperatura=resultado_refuerzo.get("barra_temperatura", "3/8\""))
        _agregar_barras_refuerzo(ifc, ifcopenshell_mod, nivel, subcontexto, geo)
        _agregar_pset_refuerzo(ifc, ifcopenshell_mod, elemento, resultado_refuerzo)

    ifc.write(ruta)
    return metrados


def exportar_ifc_pestana8(ruta: str, estructura, espesor_muro_m: float,
                           margen_excavacion_m: float = 0.30, cuantia_acero_kg_m3=None,
                           autor: str = "", organizacion: str = "", resultado_refuerzo: dict = None) -> dict:
    """Genera un archivo IFC para UNA estructura de Pestaña 8
    (core.swe2d.Estructura). Ver exportar_ifc_pestana7 para el
    comportamiento de errores y de `resultado_refuerzo`."""
    ifcopenshell_mod = _requerir_ifcopenshell()
    tipo = estructura.tipo
    p = estructura.parametros

    metrados = bmet.metrados_desde_pestana8(estructura, espesor_muro_m, margen_excavacion_m, cuantia_acero_kg_m3)

    xs_muro = zs_muro = None
    cerrado_muro = False
    if tipo == "alcantarilla":
        longitud_m = p.get("longitud", 10.0)
        xs, zs = bg.perfil_circular(p.get("diametro"))
        xs_p, zs_p, xs_h, zs_h = bg.perfil_solido_cascara(xs, zs, cerrado=True, espesor=espesor_muro_m)
        xs_muro, zs_muro, cerrado_muro = xs, zs, True
    elif tipo == "vertedero":
        longitud_m = p.get("longitud", 5.0)
        xs_p, zs_p = bg.perfil_muro_nominal()
        xs_h = zs_h = None
        xs_muro, zs_muro, cerrado_muro = xs_p, zs_p, True
    else:  # "orificio"
        area = p.get("area", 0.5)
        longitud_m = math.sqrt(max(area, 1e-6))
        xs_p, zs_p = bg.perfil_muro_nominal(alto=max(longitud_m * 1.8, 1.5))
        xs_h = zs_h = None
        xs_muro, zs_muro, cerrado_muro = xs_p, zs_p, True

    ifc, nivel, subcontexto = _crear_archivo_base(ifcopenshell_mod, estructura.nombre, autor, organizacion)
    elemento = _agregar_elemento(ifc, ifcopenshell_mod, nivel, subcontexto, estructura.nombre,
                                  xs_p, zs_p, xs_h, zs_h, longitud_m)
    _agregar_pset_metrados(ifc, ifcopenshell_mod, elemento, metrados)

    if resultado_refuerzo is not None and xs_muro is not None:
        geo = bref.geometria_barras_refuerzo(
            xs_muro, zs_muro, cerrado=cerrado_muro, longitud_m=longitud_m, espesor_muro_m=espesor_muro_m,
            espaciamiento_principal_cm=resultado_refuerzo["espaciamiento_principal_cm"],
            espaciamiento_temperatura_cm=resultado_refuerzo["espaciamiento_temperatura_cm"],
            diametro_barra=resultado_refuerzo.get("barra_principal", "1/2\""),
            diametro_barra_temperatura=resultado_refuerzo.get("barra_temperatura", "3/8\""))
        _agregar_barras_refuerzo(ifc, ifcopenshell_mod, nivel, subcontexto, geo)
        _agregar_pset_refuerzo(ifc, ifcopenshell_mod, elemento, resultado_refuerzo)

    ifc.write(ruta)
    return metrados
