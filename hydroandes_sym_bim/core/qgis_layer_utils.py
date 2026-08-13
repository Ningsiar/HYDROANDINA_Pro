# -*- coding: utf-8 -*-
"""
core/qgis_layer_utils.py

CORRECCIÓN DE BUG (reportado como 'NoneType' object has no attribute
'source'): al ejecutar algoritmos de Processing encadenados con
`is_child_algorithm=True`, solo las salidas de tipo
`QgsProcessingParameterFeatureSink` (típicas de algoritmos `native:*`,
como `native:smoothgeometry` o `native:clip`) quedan registradas en el
`QgsProcessingContext` y son recuperables con `context.takeResultLayer()`.

Los algoritmos de los proveedores GDAL y GRASS (`gdal:polygonize`,
`gdal:cliprasterbymasklayer`, `gdal:slope`, `grass7:r.*`, etc.) NO
registran su salida como sink: devuelven directamente una RUTA DE
ARCHIVO en disco. Llamar a `context.takeResultLayer()` sobre esa ruta
devuelve `None`, y cualquier código que después intente usar esa capa
(p. ej. `capa.source()`) falla con exactamente el error reportado.

Esta función centraliza la resolución correcta de ambos casos, para no
tener que recordar en cada punto de llamada cuál de los dos
comportamientos aplica.
"""
from qgis.core import QgsRasterLayer, QgsVectorLayer


def obtener_capa(valor_salida, context, es_raster: bool = False, nombre: str = "capa_temporal"):
    """
    Resuelve el valor de salida de un algoritmo de Processing ejecutado
    con is_child_algorithm=True a una QgsMapLayer utilizable, sin
    importar si el algoritmo de origen es native:* (sink registrado en
    el contexto) o gdal:*/grass7:* (ruta de archivo en disco).

    valor_salida: el valor devuelto por processing.run(...)[clave],
        típicamente un ID de capa (str) o una ruta de archivo (str).
    context: el mismo QgsProcessingContext usado en processing.run().
    es_raster: True si se espera una capa ráster, False si es vectorial.
    nombre: nombre a asignar a la capa si debe cargarse desde archivo.

    Lanza RuntimeError con un mensaje explícito si no se pudo resolver
    ninguna de las dos vías (para evitar el error genérico de atributo
    sobre NoneType y en su lugar dar un diagnóstico claro).
    """
    if valor_salida is None:
        raise RuntimeError(
            "El algoritmo de Processing no devolvió ninguna salida (valor None). "
            "Revise el panel de registro de Processing para ver si un paso previo "
            "de la cadena falló silenciosamente (p. ej. proveedor GRASS no habilitado)."
        )

    # Vía 1: la salida ya está registrada como capa temporal en el contexto
    # (comportamiento normal de algoritmos native:* con QgsProcessingParameterFeatureSink).
    capa = context.takeResultLayer(valor_salida)
    if capa is not None:
        return capa

    # Vía 2: la salida es una ruta de archivo en disco (comportamiento normal
    # de algoritmos gdal:* y grass7:*, que no usan el mecanismo de sink).
    if es_raster:
        capa = QgsRasterLayer(valor_salida, nombre)
    else:
        capa = QgsVectorLayer(valor_salida, nombre, "ogr")

    if not capa.isValid():
        raise RuntimeError(
            f"No se pudo resolver la salida del algoritmo ('{valor_salida}') ni como capa "
            "registrada en el contexto ni como ruta de archivo válida. Antes de revisar la "
            "instalación de GRASS/GDAL (Configuración > Procesos > Proveedores), considere que la "
            "causa más frecuente es que un paso ANTERIOR de la cadena haya producido una capa vacía "
            "(p. ej. una cuenca de 0 polígonos por un break point mal ubicado), lo que hace fallar "
            "silenciosamente este paso posterior. Revise el panel de registro de Processing "
            "(ícono de historial) para ver en qué paso exacto se generó una salida vacía."
        )
    return capa
