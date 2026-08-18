# -*- coding: utf-8 -*-
"""
core/modflow6_bridge.py

Puente hacia MODFLOW 6 REAL (USGS), vía FloPy, como alternativa de
mayor rigor al solver propio de core/groundwater_flow.py -- a pedido
expreso del usuario ("Fase 3" de la mejora hidrogeológica, tras
comparar el solver casero con su material de un curso de modelamiento
MODFLOW 6/FloPy).

POR QUÉ UN MÓDULO SEPARADO Y NO REEMPLAZAR groundwater_flow.py: MODFLOW
6 es un código de terceros (USGS, dominio público) que requiere (1) el
paquete FloPy instalado (`pip install flopy` -- NO viene con QGIS, a
diferencia de numpy/matplotlib/GDAL) y (2) el ejecutable mf6.exe
-- se incluye empaquetado en bin/mf6.exe (Windows x64, v6.0.4, USGS,
dominio público). Si FloPy no está instalado, este módulo lanza un
error claro con la instrucción de instalación en vez de romper el
resto del plugin (el import de flopy se hace DENTRO de la función, no
al importar este módulo).

CONVENCIÓN DE ENTRADA: se reutilizan EXACTAMENTE los mismos diccionarios
(capa,fila,col) que ya usa
core/groundwater_flow.py::resolver_flujo_multicapa_permanente() --
condiciones_borde, fuentes_sumideros, condiciones_rio, condiciones_dren
-- así la Pestaña 19 puede alimentar el solver propio o este puente a
MODFLOW 6 real con LOS MISMOS DATOS ya ingresados por el usuario, sin
un segundo juego de campos que puedan divergir.

DIFERENCIA CLAVE con el solver propio: el solver propio trabaja en
términos de TRANSMISIVIDAD T (=K·b) y no necesita cotas reales de las
capas (resuelve un dominio abstracto). MODFLOW 6 es un código de grilla
3D real: necesita la conductividad hidráulica K y la geometría vertical
real (cota superior del modelo y cota inferior -- botm -- de cada
capa), de ahí los parámetros adicionales top_m/botm_m/k_por_capa de
construir_y_ejecutar_modelo() frente a resolver_flujo_multicapa_permanente().
"""
import os

import numpy as np

RUTA_MF6_EXE = os.path.join(os.path.dirname(__file__), "..", "bin", "mf6.exe")


class Modflow6Error(Exception):
    pass


def _importar_flopy():
    try:
        import flopy
    except ImportError as e:
        raise Modflow6Error(
            "FloPy no está instalado en este Python. Ejecute 'pip install flopy' en el mismo intérprete "
            "de Python que usa QGIS (Configuración > Panel de Python > Instalar paquetes, o desde la "
            "consola: <ruta de QGIS>/apps/Python3XX/python.exe -m pip install flopy) y vuelva a intentarlo."
        ) from e
    return flopy


_VERSION_MF6_CACHE = None


def _version_mf6() -> str:
    """Versión real del mf6.exe empaquetado, leída de 'mf6.exe -v' (en
    vez de un número fijo en el código -- así no queda desactualizado
    si se reemplaza el ejecutable, como ya pasó una vez en este mismo
    módulo: el mf6.exe original aportado por el usuario, v6.0.4 de
    2019, resultó incompatible con el formato de archivos de FloPy
    actual, y se reemplazó por un v6.7.0 obtenido con la herramienta
    oficial `get-modflow` de FloPy)."""
    global _VERSION_MF6_CACHE
    if _VERSION_MF6_CACHE is None:
        try:
            import subprocess
            r = subprocess.run([RUTA_MF6_EXE, "-v"], capture_output=True, text=True, timeout=15)
            # Salida típica: "mf6.exe: 6.7.0 02/05/2026"
            _VERSION_MF6_CACHE = r.stdout.strip().split(":", 1)[-1].strip().split()[0]
        except Exception:
            _VERSION_MF6_CACHE = "?"
    return _VERSION_MF6_CACHE


def verificar_disponibilidad() -> dict:
    """Estado de las dos piezas que necesita este puente -- para que la
    UI pueda avisar con claridad ANTES de que el usuario arme todo un
    modelo y recién ahí se entere de que falta algo."""
    try:
        flopy = _importar_flopy()
        flopy_disponible, flopy_version = True, getattr(flopy, "__version__", "?")
    except Modflow6Error:
        flopy_disponible, flopy_version = False, None
    return {
        "flopy_disponible": flopy_disponible, "flopy_version": flopy_version,
        "mf6_disponible": os.path.isfile(RUTA_MF6_EXE), "mf6_ruta": RUTA_MF6_EXE,
    }


def _expandir_por_capa(valor, n_capas: int, forma_completa) -> np.ndarray:
    """Igual criterio que resolver_flujo_multicapa_permanente(): acepta
    escalar, un valor por capa (n_capas,), o el array completo ya
    expandido (n_capas,n_filas,n_columnas)."""
    arr = np.asarray(valor, dtype=float)
    if arr.ndim == 0:
        return np.full(forma_completa, float(arr))
    if arr.ndim == 1:
        if arr.shape[0] != n_capas:
            raise Modflow6Error(f"Se esperaban {n_capas} valores (uno por capa), se recibieron {arr.shape[0]}.")
        salida = np.empty(forma_completa)
        for k in range(n_capas):
            salida[k] = arr[k]
        return salida
    if arr.shape != forma_completa:
        raise Modflow6Error(f"El array debe tener la forma {forma_completa} (o (n_capas,) o escalar).")
    return arr


def construir_y_ejecutar_modelo(nombre_modelo: str, carpeta_trabajo: str,
                                 n_capas: int, n_filas: int, n_columnas: int,
                                 dx_m: float, dy_m: float, top_m, botm_m,
                                 k_por_capa, condiciones_borde: dict,
                                 fuentes_sumideros: dict = None, condiciones_rio: dict = None,
                                 condiciones_dren: dict = None, recarga_m_s: float = None,
                                 icelltype=None, strt_m=None) -> dict:
    """
    Arma, escribe, EJECUTA (mf6.exe real) y lee de vuelta un modelo
    MODFLOW 6 de flujo subterráneo en régimen permanente, multicapa.

    nombre_modelo: nombre del modelo/simulación (se pasa a minúsculas y
        se recorta a 16 caracteres internamente -- MODFLOW 6 exige
        MODELNAME en minúsculas y de máximo 16 caracteres).
    carpeta_trabajo: carpeta donde se escriben los archivos del modelo
        (.nam, .dis, .npf, ... y los resultados .hds/.cbc) -- se crea
        si no existe.
    top_m: cota superior del modelo (m s.n.m.) -- escalar (uniforme) o
        array (n_filas,n_columnas).
    botm_m: cota inferior (botm) de CADA capa -- escalar, (n_capas,), o
        (n_capas,n_filas,n_columnas). DEBE ser estrictamente decreciente
        entre capas consecutivas (cada capa por debajo de la anterior).
    k_por_capa: conductividad hidráulica horizontal (m/s) -- escalar,
        (n_capas,), o (n_capas,n_filas,n_columnas).
    condiciones_borde/fuentes_sumideros/condiciones_rio/condiciones_dren:
        MISMO formato que resolver_flujo_multicapa_permanente() (ver
        docstring del módulo).
    recarga_m_s: recarga vertical uniforme (m/s) aplicada a la capa 0
        (paquete RCHA), o None si no aplica.
    icelltype: 0 (confinado) o 1 (convertible/libre) por capa -- escalar
        o (n_capas,); por defecto 1 en todas las capas (libre).
    strt_m: carga inicial (m) para arrancar la resolución -- por defecto
        igual a top_m en toda celda.

    Devuelve {"cargas_h": array (n_capas,n_filas,n_columnas), "exito":
    bool, "log": líneas del log de mf6.exe, "carpeta_trabajo": ...,
    "ruta_hds": ..., "mf6_version": ...}."""
    flopy = _importar_flopy()
    if not os.path.isfile(RUTA_MF6_EXE):
        raise Modflow6Error(
            f"No se encontró el ejecutable de MODFLOW 6 en {RUTA_MF6_EXE} -- reinstale el plugin.")
    if n_capas < 1 or n_filas < 2 or n_columnas < 2:
        raise Modflow6Error("n_capas debe ser >= 1 y la malla (n_filas, n_columnas) al menos 2x2.")
    if not condiciones_borde:
        raise Modflow6Error("Debe indicar al menos una condición de carga fija (CHD).")

    nombre_modelo = (nombre_modelo.lower().strip() or "modelo")[:16]  # MODFLOW 6 exige MODELNAME <= 16 caracteres
    forma = (n_capas, n_filas, n_columnas)
    botm_array = _expandir_por_capa(botm_m, n_capas, forma)
    for k in range(1, n_capas):
        if np.any(botm_array[k] >= botm_array[k - 1]):
            raise Modflow6Error(
                f"La cota inferior (botm) de la capa {k} debe quedar por DEBAJO de la de la capa {k - 1} "
                "en toda celda (las capas deben apilarse de arriba hacia abajo).")
    k_array = _expandir_por_capa(k_por_capa, n_capas, forma)
    icelltype_array = (np.ones(n_capas, dtype=int) if icelltype is None
                        else np.asarray(icelltype, dtype=int) if np.ndim(icelltype) else
                        np.full(n_capas, int(icelltype), dtype=int))
    strt_array = _expandir_por_capa(strt_m if strt_m is not None else top_m, n_capas, forma)

    os.makedirs(carpeta_trabajo, exist_ok=True)
    sim = flopy.mf6.MFSimulation(sim_name=nombre_modelo, exe_name=RUTA_MF6_EXE, version="mf6",
                                  sim_ws=carpeta_trabajo)
    flopy.mf6.ModflowTdis(sim, time_units="SECONDS", nper=1, perioddata=[(1.0, 1, 1.0)])
    ims = flopy.mf6.ModflowIms(sim, pname="ims", complexity="MODERATE", print_option="SUMMARY")
    gwf = flopy.mf6.ModflowGwf(sim, modelname=nombre_modelo, save_flows=True)
    sim.register_ims_package(ims, [gwf.name])

    idomain = np.ones(forma, dtype=int)
    flopy.mf6.ModflowGwfdis(gwf, nlay=n_capas, nrow=n_filas, ncol=n_columnas, delr=dx_m, delc=dy_m,
                             top=top_m, botm=botm_array, idomain=idomain, length_units="METERS")
    flopy.mf6.ModflowGwfic(gwf, strt=strt_array)
    flopy.mf6.ModflowGwfnpf(gwf, icelltype=icelltype_array, k=k_array, save_specific_discharge=True)

    chd_spd = [[(k, i, j), h] for (k, i, j), h in condiciones_borde.items()]
    flopy.mf6.ModflowGwfchd(gwf, stress_period_data=chd_spd)

    if fuentes_sumideros:
        wel_spd = [[(k, i, j), q] for (k, i, j), q in fuentes_sumideros.items()]
        flopy.mf6.ModflowGwfwel(gwf, stress_period_data=wel_spd)
    if condiciones_rio:
        riv_spd = [[(k, i, j), d["nivel"], d["conductancia"], d["fondo"]]
                   for (k, i, j), d in condiciones_rio.items()]
        flopy.mf6.ModflowGwfriv(gwf, stress_period_data=riv_spd)
    if condiciones_dren:
        drn_spd = [[(k, i, j), d["nivel"], d["conductancia"]] for (k, i, j), d in condiciones_dren.items()]
        flopy.mf6.ModflowGwfdrn(gwf, stress_period_data=drn_spd)
    if recarga_m_s:
        flopy.mf6.ModflowGwfrcha(gwf, recharge=recarga_m_s)

    flopy.mf6.ModflowGwfoc(
        gwf, budget_filerecord=f"{nombre_modelo}.cbc", head_filerecord=f"{nombre_modelo}.hds",
        saverecord=[("HEAD", "ALL"), ("BUDGET", "ALL")], printrecord=[("HEAD", "LAST"), ("BUDGET", "LAST")])

    sim.write_simulation()
    exito, buffer_log = sim.run_simulation(silent=True)
    log_lineas = [str(linea) for linea in buffer_log]
    if not exito:
        raise Modflow6Error(
            "MODFLOW 6 no convergió o falló la ejecución. Últimas líneas del log:\n" +
            "\n".join(log_lineas[-30:]))

    ruta_hds = os.path.join(carpeta_trabajo, f"{nombre_modelo}.hds")
    headobj = flopy.utils.HeadFile(ruta_hds)
    cargas_h = headobj.get_data()
    headobj.close()

    return {"cargas_h": np.asarray(cargas_h), "exito": exito, "log": log_lineas,
            "carpeta_trabajo": carpeta_trabajo, "ruta_hds": ruta_hds, "mf6_version": _version_mf6()}
