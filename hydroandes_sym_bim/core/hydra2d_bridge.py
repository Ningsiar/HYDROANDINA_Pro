# -*- coding: utf-8 -*-
"""
core/hydra2d_bridge.py

Puente hacia el plugin HYDRA2DGPU (Aaron Sprague, licencia MIT,
https://github.com/aspragueumkc/hydra2dgpu) para el modelamiento
hidráulico 2D por ecuaciones de aguas someras con solucionador de
volúmenes finitos acelerado por CUDA.

POR QUÉ UN PUENTE Y NO CÓDIGO COPIADO: se sigue el mismo patrón que
core/cn_generator_bridge.py ya usa con el plugin curve_number_generator.
HYDRA2DGPU se mantiene como una dependencia externa instalada por el
usuario, de modo que (a) no se duplica un solucionador de decenas de
miles de líneas que habría que mantener sincronizado, (b) las mejoras y
correcciones de su autor llegan solas, y (c) no se asumen las
obligaciones de redistribución de su licencia. HydroAndes Sym BIM aporta la
integración: alimentar el modelo con lo que ya calculó (MDE delineado,
hidrograma de diseño, número de curva) y presentar los resultados con su
propio formato.

ARQUITECTURA DE HYDRA2DGPU, Y LO QUE IMPLICA PARA EL PUENTE:
a diferencia de curve_number_generator, HYDRA2DGPU NO registra
algoritmos en el marco de Processing de QGIS -- no hay un
`processing.run("hydra:...")` que invocar. Es un plugin de DIÁLOGO: su
clase HydraQgisPlugin expone run(), que abre su propia ventana de
trabajo (swe2d.workbench), y todo el flujo ocurre allí. En consecuencia
este puente NO puede ejecutar la simulación de forma desatendida; lo que
hace es:

  1. DETECTAR si el plugin está instalado, activo y con su backend
     compilado disponible (el solucionador es una extensión C++/CUDA que
     se instala como wheel aparte, así que "el plugin está" y "el motor
     funciona" son dos cosas distintas que hay que comprobar por
     separado -- si no, el usuario recibiría un fallo incomprensible al
     lanzar la simulación).
  2. PREPARAR los insumos desde los resultados de HydroAndes Sym BIM.
  3. LANZAR su ventana de trabajo.
  4. LEER los resultados que deja en disco para mostrarlos con el
     formato del resto del plugin.

REQUISITOS DEL MOTOR (documentados por su autor): QGIS 3.28+, Python
3.12+, GPU NVIDIA con Compute Capability >= 7.5 y un driver compatible
con el runtime CUDA 12 que el propio wheel incorpora -- NO hace falta
instalar el CUDA Toolkit a mano.
"""
import os
from typing import Optional


NOMBRE_PLUGIN = "HYDRA2DGPU"
URL_PROYECTO = "https://github.com/aspragueumkc/hydra2dgpu"


class Hydra2DNoDisponible(Exception):
    """El plugin o su motor no están disponibles. El mensaje explica cuál
    de los dos falta y qué hacer, porque las acciones son distintas."""


def _carpeta_plugins_qgis() -> Optional[str]:
    try:
        from qgis.core import QgsApplication
        return os.path.join(QgsApplication.qgisSettingsDirPath(), "python", "plugins")
    except Exception:
        return None


def estado_hydra2d() -> dict:
    """
    Diagnostica por separado las TRES condiciones que deben cumplirse, en
    vez de devolver un único booleano: cada una se corrige de una forma
    distinta y el usuario necesita saber cuál falla.

      instalado  -> la carpeta del plugin existe
      activo     -> QGIS lo cargó (aparece en el registro de plugins)
      motor      -> el paquete swe2d del backend es importable

    El tercero es el que más confunde en la práctica: el plugin puede
    estar perfectamente instalado y activo, y aun así no simular nada
    porque su wheel con el solucionador CUDA no se descargó.
    """
    estado = {
        "instalado": False, "activo": False, "motor_disponible": False,
        "banco_trabajo_disponible": False,
        "version": None, "ruta": None, "detalle_motor": None,
        "detalle_banco_trabajo": None,
    }

    carpeta = _carpeta_plugins_qgis()
    if carpeta:
        ruta = os.path.join(carpeta, NOMBRE_PLUGIN)
        if os.path.isdir(ruta):
            estado["instalado"] = True
            estado["ruta"] = ruta
            meta = os.path.join(ruta, "metadata.txt")
            if os.path.isfile(meta):
                try:
                    with open(meta, encoding="utf-8") as f:
                        for linea in f:
                            if linea.startswith("version="):
                                estado["version"] = linea.split("=", 1)[1].strip()
                                break
                except Exception:
                    pass

    try:
        from qgis.utils import plugins
        estado["activo"] = NOMBRE_PLUGIN in plugins
    except Exception:
        pass

    # El motor va en un entorno aparte (~/.hydra2dgpu) que el propio
    # instalador de HYDRA2DGPU añade al sys.path al activarse; por eso
    # esta comprobación solo es fiable con el plugin ya activo.
    #
    # SE COMPRUEBA hydra_swe2d, NO swe2d: son dos cosas distintas y
    # confundirlas da un falso "listo". `swe2d` es el paquete Python del
    # banco de trabajo, que puede importarse perfectamente sin que exista
    # el solucionador; `hydra_swe2d` es la extensión compilada C++/CUDA
    # que de verdad resuelve las ecuaciones. Es además exactamente lo que
    # comprueba HYDRA2DGPU en su propio _backend_available() antes de
    # abrir el banco de trabajo o lanzar su instalador, así que este
    # diagnóstico coincide con lo que hará el plugin al pulsar «Abrir».
    try:
        import importlib
        importlib.import_module("hydra_swe2d")
        estado["motor_disponible"] = True
    except Exception as e:
        estado["detalle_motor"] = str(e)

    # El paquete del banco de trabajo se reporta aparte: si falta ESTE
    # y no el solucionador, el problema es otro (instalación incompleta
    # del plugin, no del motor CUDA).
    try:
        import importlib
        importlib.import_module("swe2d")
        estado["banco_trabajo_disponible"] = True
    except Exception as e:
        estado["banco_trabajo_disponible"] = False
        estado["detalle_banco_trabajo"] = str(e)

    return estado


def mensaje_estado(estado: dict) -> str:
    """Texto explicativo del estado, con la acción concreta que toca."""
    if not estado["instalado"]:
        return (
            f"{NOMBRE_PLUGIN} no está instalado.\n\n"
            "Es un plugin independiente (Aaron Sprague, licencia MIT) que HydroAndes Sym BIM utiliza "
            "como motor de cálculo 2D, sin incorporar su código.\n\n"
            f"Descárguelo de {URL_PROYECTO} e instálelo desde «Complementos → Administrar e instalar "
            "complementos → Instalar a partir de un ZIP»."
        )
    if not estado["activo"]:
        return (
            f"{NOMBRE_PLUGIN} v{estado['version'] or '?'} está instalado pero NO activado.\n\n"
            "Actívelo en «Complementos → Administrar e instalar complementos → Instalados», "
            "marcando su casilla."
        )
    if not estado["motor_disponible"]:
        return (
            f"{NOMBRE_PLUGIN} v{estado['version'] or '?'} está activo, pero su MOTOR DE CÁLCULO no "
            "está disponible.\n\n"
            "El solucionador es una extensión compilada (C++/CUDA) que se instala como un paquete "
            "aparte: el plugin la descarga la primera vez que se abre su ventana. Abra "
            f"{NOMBRE_PLUGIN} desde su propio menú y deje que complete esa instalación.\n\n"
            "Requisitos del motor: GPU NVIDIA con Compute Capability ≥ 7.5 y un driver compatible con "
            "CUDA 12 (no hace falta instalar el CUDA Toolkit: el paquete lo incluye).\n\n"
            f"Detalle técnico: {estado['detalle_motor']}"
        )
    if not estado.get("banco_trabajo_disponible", True):
        return (
            f"{NOMBRE_PLUGIN} v{estado['version'] or '?'} tiene su motor de cálculo (hydra_swe2d) "
            "disponible, pero NO su paquete de banco de trabajo (swe2d).\n\n"
            "Es una instalación incompleta del plugin, no un problema del motor CUDA: reinstálelo "
            f"desde {URL_PROYECTO}.\n\n"
            f"Detalle técnico: {estado.get('detalle_banco_trabajo')}"
        )
    return (
        f"{NOMBRE_PLUGIN} v{estado['version'] or '?'} está instalado, activo y con su motor de "
        "cálculo (extensión compilada hydra_swe2d) disponible.\n\n"
        "IMPORTANTE — dónde aparece: el banco de trabajo de HYDRA2DGPU NO abre una ventana propia, "
        "se ACOPLA como panel dentro de la ventana principal de QGIS. Al pulsar «Abrir ventana de "
        "HYDRA2DGPU», esta ventana de HydroAndes Sym BIM se minimiza sola para que pueda verlo; si no, "
        "quedaría tapado detrás y parecería que no ocurrió nada."
    )


def abrir_ventana_hydra2d():
    """
    Abre la ventana de trabajo de HYDRA2DGPU.

    Se invoca su método run() a través del registro de plugins de QGIS en
    vez de importar su módulo directamente: así se usa la MISMA instancia
    que QGIS ya inicializó (con su iface y su configuración), en lugar de
    crear una segunda en paralelo que competiría por el mismo estado.
    """
    estado = estado_hydra2d()
    if not (estado["instalado"] and estado["activo"]):
        raise Hydra2DNoDisponible(mensaje_estado(estado))

    from qgis.utils import plugins
    instancia = plugins.get(NOMBRE_PLUGIN)
    if instancia is None or not hasattr(instancia, "run"):
        raise Hydra2DNoDisponible(
            f"{NOMBRE_PLUGIN} figura como activo pero no expone su método run(). "
            "Reinicie QGIS y vuelva a intentarlo."
        )
    instancia.run()
    return True


def resumen_insumos_disponibles(morfometria: dict, cn_resultados: dict,
                                 hidrograma: dict, ruta_dem: str = None) -> dict:
    """
    Revisa qué insumos para el modelo 2D ya están calculados en
    HydroAndes Sym BIM, para poder decirle al usuario qué le falta ANTES de
    abrir la ventana de HYDRA2DGPU en vez de que lo descubra allí dentro.

    Devuelve un dict con cada insumo, si está disponible, su valor
    resumido y de qué pestaña procede.
    """
    area = (morfometria or {}).get("g1", {}).get("A")
    pendiente = None
    if morfometria and morfometria.get("g3"):
        pendiente = morfometria["g3"].get("Se")
    elif morfometria and morfometria.get("g4"):
        pct = morfometria["g4"].get("S_cuenca_pct")
        pendiente = pct / 100.0 if pct is not None else None

    cn = (cn_resultados or {}).get("CN_ponderado") or (cn_resultados or {}).get("CN")
    qp = (hidrograma or {}).get("caudal_pico_m3s")
    n_ordenadas = len((hidrograma or {}).get("caudal_m3s") or [])

    insumos = {
        "mde": {
            "disponible": bool(ruta_dem),
            "valor": os.path.basename(ruta_dem) if ruta_dem else None,
            "origen": "Pestaña 1 — DEM y Delimitación",
            "uso": "topografía de la malla de cálculo",
        },
        "area_cuenca": {
            "disponible": area is not None,
            "valor": f"{area} km²" if area is not None else None,
            "origen": "Pestaña 2 — Morfometría",
            "uso": "verificación de escala del dominio",
        },
        "pendiente": {
            "disponible": pendiente is not None,
            "valor": f"{pendiente:.4f} m/m" if pendiente is not None else None,
            "origen": "Pestaña 2 — Morfometría",
            "uso": "referencia para el paso de tiempo y la estabilidad",
        },
        "numero_curva": {
            "disponible": cn is not None,
            "valor": str(cn) if cn is not None else None,
            "origen": "Pestaña 3 — Métodos de pérdida",
            "uso": "pérdidas por infiltración en lluvia sobre malla (rain-on-grid)",
        },
        "hidrograma": {
            "disponible": qp is not None,
            "valor": (f"Qp = {qp} m³/s, {n_ordenadas} ordenadas" if qp is not None else None),
            "origen": "Pestaña 6 — Caudales Máximos",
            "uso": "condición de borde de entrada (hidrograma de crecida)",
        },
    }
    faltantes = [k for k, v in insumos.items() if not v["disponible"]]
    return {
        "insumos": insumos,
        "faltantes": faltantes,
        "completo": not faltantes,
        "n_disponibles": len(insumos) - len(faltantes),
        "n_total": len(insumos),
    }


def exportar_hidrograma_csv(hidrograma: dict, ruta_csv: str) -> str:
    """
    Escribe el hidrograma de diseño de la Pestaña 6 en un CSV de dos
    columnas (tiempo en horas, caudal en m³/s), que es el formato que
    HYDRA2DGPU admite para una condición de borde tipo hidrograma.

    Se exporta a un archivo en vez de intentar inyectarlo en memoria
    porque el flujo del otro plugin ocurre dentro de su propia ventana:
    un archivo es el punto de encuentro estable entre ambos.
    """
    tiempos = (hidrograma or {}).get("tiempos_h") or []
    caudales = (hidrograma or {}).get("caudal_m3s") or []
    if not tiempos or not caudales:
        raise Hydra2DNoDisponible(
            "No hay un hidrograma calculado que exportar. Calcúlelo primero en la Pestaña 6 "
            "(Caudales Máximos)."
        )
    n = min(len(tiempos), len(caudales))
    with open(ruta_csv, "w", encoding="utf-8", newline="") as f:
        f.write("tiempo_h,caudal_m3s\n")
        for i in range(n):
            f.write(f"{tiempos[i]:.6f},{caudales[i]:.6f}\n")
    return ruta_csv
