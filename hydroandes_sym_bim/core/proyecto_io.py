# -*- coding: utf-8 -*-
"""
core/proyecto_io.py

Guardar/Cargar PROYECTO COMPLETO en un único archivo .json portátil --
sin dependencias de Qt (funciones puras, ver ui/plugin_dialog.py para
la recolección/aplicación del estado real de los widgets).

FORMATO: un JSON con metadatos (versión de formato, versión del
plugin, nombre de proyecto, fecha) más una sección "datos" de
estructura libre (la definen los llamadores -- este módulo no conoce
el contenido de Presupuesto/Cronograma/etc., solo el sobre que los
envuelve, para poder validar el archivo antes de intentar aplicarlo).

ALCANCE: el archivo es PORTÁTIL (un solo .json, cópielo a cualquier
nube -- Google Drive, OneDrive -- manualmente) pero NO hay integración
nativa con ninguna API de nube (OAuth/credenciales quedan fuera del
alcance de un plugin de QGIS) -- si necesita sincronización automática,
guarde el proyecto dentro de una carpeta ya sincronizada por el
cliente de escritorio de su nube (Drive/OneDrive), que es como
cualquier otro programa de escritorio logra ese resultado sin pedirle
sus credenciales a un plugin de terceros.

QUÉ CUBRE (a criterio de qué secciones son "estado de proyecto" que el
usuario reingresa entre sesiones, no derivado de un archivo externo que
ya se reimporta directamente -- ver docstring de
plugin_dialog.py::_recopilar_estado_proyecto): Presupuesto (insumos,
partidas, APUs, resumen), Cronograma (actividades), Fórmula
Polinómica (monomios), Estabilidad de Muros y Diseño de Zapatas
(parámetros de entrada). NO cubre las Pestañas 1-8 (Hidrología/
Hidráulica), que típicamente se re-derivan de un MDE/CSV/NetCDF externo
que el usuario vuelve a cargar directamente -- ampliable a futuro si
se requiere.
"""
import datetime
import json

FORMATO_PROYECTO = "hydroandes_sym_bim_proyecto"
VERSION_FORMATO = 1


class ProyectoIOError(Exception):
    """Archivo de proyecto inexistente, corrupto, de un formato no
    reconocido, o de una versión de formato más nueva que la que este
    plugin sabe leer -- el mensaje explica cuál de estas falla."""


def guardar_proyecto(ruta: str, datos: dict, nombre_proyecto: str = "", version_plugin: str = "") -> None:
    """Escribe `datos` (dict de estructura libre, ver docstring del
    módulo) envuelto en el sobre con metadatos, como JSON legible
    (indent=2, UTF-8) -- un archivo de texto plano, revisable a mano
    y llevable a cualquier nube manualmente."""
    sobre = {
        "formato": FORMATO_PROYECTO,
        "version_formato": VERSION_FORMATO,
        "version_plugin": version_plugin,
        "nombre_proyecto": nombre_proyecto,
        "fecha_guardado": datetime.datetime.now().isoformat(timespec="seconds"),
        "datos": datos,
    }
    try:
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(sobre, f, indent=2, ensure_ascii=False)
    except OSError as e:
        raise ProyectoIOError(f"no se pudo escribir el archivo «{ruta}»: {e}")


def cargar_proyecto(ruta: str) -> dict:
    """Lee y valida el sobre del archivo de proyecto, y devuelve el
    sobre COMPLETO (con "datos" adentro) -- el llamador es quien sabe
    cómo aplicar cada sección de "datos" a sus propios widgets."""
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            sobre = json.load(f)
    except OSError as e:
        raise ProyectoIOError(f"no se pudo leer el archivo «{ruta}»: {e}")
    except json.JSONDecodeError as e:
        raise ProyectoIOError(f"«{ruta}» no es un JSON válido -- {e}")
    if not isinstance(sobre, dict) or sobre.get("formato") != FORMATO_PROYECTO:
        raise ProyectoIOError(
            f"«{ruta}» no es un archivo de proyecto de HydroAndes SYM BIM (falta o no coincide "
            f"la marca de formato).")
    version = sobre.get("version_formato")
    if not isinstance(version, int) or version > VERSION_FORMATO:
        raise ProyectoIOError(
            f"«{ruta}» fue guardado con una versión de formato ({version}) más nueva que la que "
            f"esta versión del plugin sabe leer ({VERSION_FORMATO}) -- actualice el plugin.")
    if "datos" not in sobre:
        raise ProyectoIOError(f"«{ruta}» no tiene la sección «datos» -- archivo corrupto o incompleto.")
    return sobre
