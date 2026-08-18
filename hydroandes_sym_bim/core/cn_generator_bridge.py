# -*- coding: utf-8 -*-
"""
core/cn_generator_bridge.py

Puente hacia el plugin de terceros "Curve Number Generator" (Abdul
Raheem Siddiqui, https://github.com/ar-siddiqui/curve_number_generator),
disponible en el repositorio oficial de plugins de QGIS, que es el que
el usuario pidió emplear para automatizar el Número de Curva a partir
de ESA WorldCover + HYSOGs250m (ORNL).

TRANSPARENCIA IMPORTANTE:

  Este módulo NO reimplementa ese plugin ni asume nombres exactos de
  parámetros/algoritmo que no se pudieron verificar en este entorno (sin
  QGIS real ni ese plugin instalado disponibles para inspeccionar en
  vivo). En cambio, DESCUBRE el algoritmo dinámicamente en el registro
  de Processing de QGIS en tiempo de ejecución (buscando por
  coincidencias de texto en el id/nombre del algoritmo y de sus
  parámetros), para no arriesgar una clave de parámetro adivinada mal
  que rompa la ejecución silenciosamente o con un error confuso.

  Esto significa que la integración es "mejor esfuerzo": si el autor del
  plugin cambia los nombres de sus parámetros en una versión futura, la
  coincidencia por palabras clave debería seguir funcionando (busca
  "area"/"aoi", "lookup", "hydrologic"+"condition", "antecedent"/"arc"),
  pero no hay garantía absoluta. Se valida explícitamente qué se
  encontró y se informa con claridad si algo no pudo emparejarse con
  confianza, en vez de fallar en silencio con un resultado incorrecto.

REQUISITO: el plugin "Curve Number Generator" debe estar instalado y
habilitado en QGIS (Complementos > Administrar e instalar complementos >
buscar "Curve Number Generator"). Si no lo está, `buscar_algoritmo_cn()`
devuelve None y la pestaña 3 debe ofrecer el método propio
(core/landcover_soils.py, ESA WorldCover vía STAC + HSG manual) como
alternativa.
"""
from typing import Optional


class CnGeneratorBridgeError(Exception):
    pass


def buscar_algoritmo_cn():
    """
    Busca en el registro de Processing de QGIS el algoritmo del plugin
    'Curve Number Generator' (global, ESA+ORNL). Devuelve el objeto
    QgsProcessingAlgorithm encontrado, o None si el plugin no está
    instalado/habilitado.
    """
    from qgis.core import QgsApplication
    registro = QgsApplication.processingRegistry()
    candidatos = []
    for alg in registro.algorithms():
        id_lower = alg.id().lower()
        nombre_lower = alg.displayName().lower()
        if "curve_number" in id_lower or "curvenumber" in id_lower:
            candidatos.append(alg)
        elif "curve number" in nombre_lower and ("esa" in nombre_lower or "ornl" in nombre_lower
                                                  or "global" in nombre_lower):
            candidatos.append(alg)
    if not candidatos:
        return None
    # Preferir el que mencione explícitamente "global" (el que combina
    # ESA WorldCover + HYSOGs250m automáticamente, que es el pedido);
    # si no, el primero encontrado.
    for alg in candidatos:
        if "global" in alg.id().lower() or "global" in alg.displayName().lower():
            return alg
    return candidatos[0]


def _encontrar_parametro(alg, claves_incluir, claves_excluir=()):
    """Busca en alg.parameterDefinitions() el primer parámetro cuyo
    nombre contenga alguna de claves_incluir y ninguna de claves_excluir
    (comparación insensible a mayúsculas)."""
    for definicion in alg.parameterDefinitions():
        nombre = definicion.name().lower()
        descripcion = definicion.description().lower()
        texto = nombre + " " + descripcion
        if any(c in texto for c in claves_excluir):
            continue
        if any(c in texto for c in claves_incluir):
            return definicion.name()
    return None


def _encontrar_salida(alg, claves_incluir, claves_excluir=()):
    for definicion in alg.outputDefinitions():
        nombre = definicion.name().lower()
        descripcion = definicion.description().lower()
        texto = nombre + " " + descripcion
        if any(c in texto for c in claves_excluir):
            continue
        if any(c in texto for c in claves_incluir):
            return definicion.name()
    return None


def inspeccionar_parametros(alg) -> dict:
    """
    Introspecciona el algoritmo encontrado y devuelve un dict con las
    claves de parámetro/salida identificadas por coincidencia de
    palabras clave (ver advertencia de transparencia en el docstring del
    módulo). Cualquier valor None indica que no se pudo identificar ese
    parámetro/salida con confianza.
    """
    return {
        "param_area": _encontrar_parametro(alg, ["area", "aoi", "boundary", "polygon", "interest"]),
        "param_lookup": _encontrar_parametro(alg, ["lookup"]),
        "param_hydrologic_condition": _encontrar_parametro(
            alg, ["hydrologic condition", "hydrologiccondition", "condition"],
            claves_excluir=["antecedent", "runoff condition", "arc"]
        ),
        "param_arc": _encontrar_parametro(alg, ["antecedent", " arc", "arc "]),
        "salida_esa": _encontrar_salida(alg, ["esa", "world cover", "worldcover", "land cover"]),
        "salida_hsg": _encontrar_salida(alg, ["hsg", "hydrologic soil group", "soil group"]),
        "salida_cn_raster": _encontrar_salida(
            alg, ["curve number", "curve_number", "cn"], claves_excluir=["vector"]
        ),
        "salida_cn_vector": _encontrar_salida(
            alg, ["curve number", "curve_number", "cn"], claves_excluir=[]
        ) if _encontrar_salida(alg, ["vector"]) else None,
    }


def ejecutar_cn_generator(cuenca_layer, context, feedback,
                           condicion_hidrologica: str = "Fair",
                           arc: str = "II") -> dict:
    """
    Ejecuta el algoritmo del plugin 'Curve Number Generator' sobre la
    cuenca delimitada, y calcula el CN_II ponderado por área a partir de
    su salida vectorizada (cada polígono trae su propio valor de CN).

    Lanza CnGeneratorBridgeError con un mensaje explicando exactamente
    qué no se pudo hacer (plugin no encontrado, parámetro no
    identificado, salida vectorizada no disponible, etc.) — nunca fallla
    en silencio ni inventa un resultado.
    """
    import processing

    alg = buscar_algoritmo_cn()
    if alg is None:
        raise CnGeneratorBridgeError(
            "El plugin 'Curve Number Generator' (ar-siddiqui) no está instalado/habilitado en "
            "esta instalación de QGIS. Instálelo desde Complementos > Administrar e instalar "
            "complementos > busque 'Curve Number Generator', y vuelva a intentar. Mientras tanto "
            "puede usar el método alternativo (ESA WorldCover + HSG manual) de esta misma pestaña."
        )

    parametros_encontrados = inspeccionar_parametros(alg)
    if parametros_encontrados["param_area"] is None:
        raise CnGeneratorBridgeError(
            f"Se encontró el algoritmo '{alg.displayName()}' ({alg.id()}) pero no se pudo "
            "identificar con confianza cuál de sus parámetros corresponde al área de interés. "
            "Es posible que el autor del plugin haya cambiado los nombres de los parámetros; "
            "revise core/cn_generator_bridge.py (_encontrar_parametro) y ajuste las palabras "
            "clave de búsqueda, o ejecute el algoritmo manualmente desde la Caja de Herramientas "
            "de Processing con el nombre indicado arriba."
        )
    if parametros_encontrados["salida_cn_vector"] is None:
        raise CnGeneratorBridgeError(
            f"Se encontró el algoritmo '{alg.displayName()}' ({alg.id()}) y su parámetro de área "
            f"de interés ('{parametros_encontrados['param_area']}'), pero no se pudo identificar "
            "con confianza cuál de sus salidas es el 'Curve Number (Vectorized)' necesario para "
            "ponderar el CN por área. Ejecute el algoritmo manualmente desde la Caja de "
            "Herramientas de Processing para revisar los nombres exactos de sus salidas."
        )

    parametros_ejecucion = {parametros_encontrados["param_area"]: cuenca_layer}
    if parametros_encontrados["param_hydrologic_condition"]:
        parametros_ejecucion[parametros_encontrados["param_hydrologic_condition"]] = condicion_hidrologica
    if parametros_encontrados["param_arc"]:
        parametros_ejecucion[parametros_encontrados["param_arc"]] = arc
    # Todas las salidas se piden igual (rutas temporales), para poder
    # inspeccionar también ESA WorldCover y HSG si el usuario los quiere ver.
    for clave_salida in ("salida_esa", "salida_hsg", "salida_cn_raster", "salida_cn_vector"):
        nombre_param = parametros_encontrados[clave_salida]
        if nombre_param:
            parametros_ejecucion[nombre_param] = "TEMPORARY_OUTPUT"

    resultado_alg = processing.run(alg.id(), parametros_ejecucion, context=context, feedback=feedback)

    from .qgis_layer_utils import obtener_capa
    ruta_cn_vector = resultado_alg.get(parametros_encontrados["salida_cn_vector"])
    if not ruta_cn_vector:
        raise CnGeneratorBridgeError(
            "El algoritmo se ejecutó pero no devolvió la salida vectorizada del Número de Curva "
            "(revise el registro de Processing para más detalles)."
        )
    capa_cn_vector = obtener_capa(ruta_cn_vector, context, es_raster=False, nombre="cn_vectorizado")

    # Identificar el campo de CN dentro de la capa vectorizada (búsqueda
    # por nombre, ya que tampoco se pudo verificar el nombre exacto del
    # campo sin el plugin instalado).
    campos = [f.name() for f in capa_cn_vector.fields()]
    campo_cn = next((f for f in campos if f.lower() in ("cn", "curve_number", "curvenumber")), None)
    if campo_cn is None:
        campo_cn = next((f for f in campos if "cn" in f.lower()), None)
    if campo_cn is None:
        raise CnGeneratorBridgeError(
            f"La capa vectorizada de CN se generó, pero no se encontró un campo de número de "
            f"curva reconocible entre sus campos: {campos}."
        )

    area_total = 0.0
    suma_ponderada = 0.0
    desglose = []
    for feat in capa_cn_vector.getFeatures():
        geom = feat.geometry()
        if geom is None or geom.isEmpty():
            continue
        area_m2 = geom.area()
        cn_val = feat[campo_cn]
        if cn_val is None:
            continue
        area_total += area_m2
        suma_ponderada += area_m2 * float(cn_val)
        desglose.append({"area_km2": round(area_m2 / 1e6, 4), "cn": float(cn_val)})

    if area_total <= 0:
        raise CnGeneratorBridgeError(
            "La capa vectorizada de CN no tiene área válida (revise que la cuenca delimitada "
            "efectivamente se solape con los datasets ESA WorldCover / HYSOGs250m)."
        )

    cn_ii_ponderado = suma_ponderada / area_total
    desglose.sort(key=lambda d: d["area_km2"], reverse=True)
    return {
        "cn_ii_ponderado": round(cn_ii_ponderado, 2),
        "area_total_km2": round(area_total / 1e6, 4),
        "desglose": desglose,
        "algoritmo_usado": alg.displayName(),
        "capa_cn_vectorizada": capa_cn_vector,
    }
