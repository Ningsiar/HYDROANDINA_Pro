# -*- coding: utf-8 -*-
"""
core/licencia.py

Límite de 10 usos gratuitos con validación remota (Google Apps Script) y
desbloqueo con clave de licencia.

CÓMO FUNCIONA:
  1. Cada instalación (equipo) tiene un ID estable -- el MachineGuid de
     Windows si se puede leer del registro, o si no un UUID generado una
     sola vez y cacheado localmente (Linux/Mac, o si el registro no es
     legible).
  2. Cada vez que se abre el plugin (plugin.py::run(), ANTES de construir
     el diálogo principal) se llama a consultar_y_registrar_uso(), que le
     pide al backend remoto (una hoja de cálculo de Google con un Apps
     Script delante, ver scripts/licencia_backend_apps_script.gs) que
     sume 1 al contador de ESA instalación y diga si ya se pasó del
     límite. El backend es la fuente de verdad: aunque alguien borre el
     caché local, el conteo real vive en la hoja de cálculo del
     desarrollador.
  3. Si no hay conexión, se cae al CACHÉ LOCAL (mismo límite, aplicado
     sin el servidor) -- así no se castiga a un usuario legítimo sin
     internet en ese momento, pero el conteo local también existe y
     también bloquea si se agota estando offline.
  4. Una clave de licencia (HMAC-SHA256 del id de instalación con un
     secreto que solo tiene el desarrollador -- ver
     scripts/licencia_backend_apps_script.gs y el generador de claves,
     ninguno de los dos vive en este repo) se valida en el propio
     backend, nunca en el plugin: el plugin nunca conoce el secreto, así
     que no se puede extraer del código fuente distribuido.

URL_BACKEND_LICENCIA se deja vacía a propósito: hasta que el desarrollador
despliegue su Apps Script y pegue aquí la URL, _hay_backend_configurado()
devuelve False y el plugin no aplica ningún límite (evita que el plugin
quede inutilizable en máquinas de desarrollo/prueba antes de terminar de
configurar el backend).
"""
import json
import os
import platform
import re
import time
import urllib.request
import urllib.error
import uuid
from typing import Optional

LIMITE_USOS_GRATIS = 10

# Pegar aquí la URL de la implementación del Apps Script (termina en
# /exec) una vez desplegada -- ver scripts/licencia_backend_apps_script.gs.
URL_BACKEND_LICENCIA = ""

_TIMEOUT_RED_S = 6.0


class LicenciaError(Exception):
    pass


def _hay_backend_configurado() -> bool:
    return bool(URL_BACKEND_LICENCIA.strip())


# ======================================================================
# ID de instalación
# ======================================================================
def _machine_guid_windows() -> Optional[str]:
    if platform.system() != "Windows":
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                             r"SOFTWARE\Microsoft\Cryptography") as clave:
            valor, _tipo = winreg.QueryValueEx(clave, "MachineGuid")
            return str(valor).strip() or None
    except Exception:
        return None  # sin permisos, clave inexistente, u otra versión de Windows -- se usa el respaldo


def _ruta_cache_licencia() -> str:
    """Fuera de la carpeta del plugin a propósito: debe sobrevivir a
    desinstalar/reinstalar o actualizar el plugin, que borra y vuelve a
    copiar todo hydroandina_pro/."""
    base = os.path.join(os.path.expanduser("~"), ".hydroandina_pro_licencia")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "estado.json")


def _leer_cache() -> dict:
    ruta = _ruta_cache_licencia()
    if not os.path.exists(ruta):
        return {}
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _escribir_cache(datos: dict):
    ruta = _ruta_cache_licencia()
    try:
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=2)
    except OSError:
        pass  # si no se puede escribir (permisos, disco lleno), se sigue igual con lo que había en memoria


def obtener_id_instalacion() -> str:
    """ID estable de esta instalación: MachineGuid de Windows si se puede
    leer (sobrevive a borrar el caché local), o si no un UUID generado
    una sola vez y cacheado en disco."""
    guid_windows = _machine_guid_windows()
    if guid_windows:
        return f"win-{guid_windows}"

    cache = _leer_cache()
    if cache.get("id_instalacion"):
        return cache["id_instalacion"]

    nuevo_id = f"gen-{uuid.uuid4()}"
    cache["id_instalacion"] = nuevo_id
    _escribir_cache(cache)
    return nuevo_id


# ======================================================================
# Comunicación con el backend
# ======================================================================
def _peticion_post(accion: str, id_instalacion: str, extra: Optional[dict] = None) -> dict:
    cuerpo = {"accion": accion, "id": id_instalacion}
    if extra:
        cuerpo.update(extra)
    datos = json.dumps(cuerpo).encode("utf-8")
    peticion = urllib.request.Request(
        URL_BACKEND_LICENCIA, data=datos, method="POST",
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(peticion, timeout=_TIMEOUT_RED_S) as respuesta:
        cuerpo_respuesta = respuesta.read().decode("utf-8")
    return json.loads(cuerpo_respuesta)


def consultar_y_registrar_uso(id_instalacion: Optional[str] = None) -> dict:
    """
    Se llama UNA vez por apertura del plugin (item de licencia: "cada
    vez que se abre, se usa y se cierra" = 1 uso). Intenta el backend
    remoto primero (fuente de verdad); si falla la red, cae al caché
    local con la misma regla de límite.

    Devuelve: {'usos': int, 'limite': int, 'licencia_activada': bool,
    'bloqueado': bool, 'origen': 'remoto'|'local', 'error_red': str|None}
    """
    id_instalacion = id_instalacion or obtener_id_instalacion()

    if not _hay_backend_configurado():
        # Sin backend configurado todavía -> no se aplica ningún límite
        # (evita dejar el plugin inutilizable mientras se termina de
        # desplegar el Apps Script).
        return {"usos": 0, "limite": LIMITE_USOS_GRATIS, "licencia_activada": True,
                "bloqueado": False, "origen": "sin_backend", "error_red": None}

    try:
        resultado = _peticion_post("registrar_uso", id_instalacion)
        resultado.setdefault("origen", "remoto")
        resultado["error_red"] = None
        _escribir_cache({
            "id_instalacion": id_instalacion, "usos": resultado.get("usos", 0),
            "limite": resultado.get("limite", LIMITE_USOS_GRATIS),
            "licencia_activada": bool(resultado.get("licencia_activada", False)),
            "ultima_sincronizacion": time.time(),
        })
        return resultado
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
        cache = _leer_cache()
        if bool(cache.get("licencia_activada", False)):
            usos = cache.get("usos", 0)
        else:
            usos = int(cache.get("usos", 0)) + 1
        limite = cache.get("limite", LIMITE_USOS_GRATIS)
        licencia_activada = bool(cache.get("licencia_activada", False))
        cache.update({"id_instalacion": id_instalacion, "usos": usos, "limite": limite,
                      "licencia_activada": licencia_activada})
        _escribir_cache(cache)
        return {"usos": usos, "limite": limite, "licencia_activada": licencia_activada,
                "bloqueado": (not licencia_activada) and usos > limite,
                "origen": "local", "error_red": f"{type(e).__name__}: {e}"}


def activar_licencia(clave: str, id_instalacion: Optional[str] = None) -> dict:
    """Envía la clave al backend para validarla (el plugin nunca conoce
    el secreto -- lo verifica el propio backend). Devuelve
    {'ok': bool, 'mensaje': str, 'licencia_activada': bool}."""
    if not _hay_backend_configurado():
        raise LicenciaError(
            "El backend de licencias todavía no está configurado en este plugin "
            "(URL_BACKEND_LICENCIA vacía).")
    id_instalacion = id_instalacion or obtener_id_instalacion()
    clave_normalizada = re.sub(r"[^A-Za-z0-9]", "", clave).upper()
    if not clave_normalizada:
        raise LicenciaError("Ingrese la clave de licencia.")
    try:
        resultado = _peticion_post("activar_licencia", id_instalacion, {"clave": clave_normalizada})
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
        raise LicenciaError(
            f"No se pudo contactar al servidor de licencias ({type(e).__name__}: {e}). "
            "Verifique su conexión a internet e intente de nuevo."
        ) from e
    if resultado.get("ok") and resultado.get("licencia_activada"):
        cache = _leer_cache()
        cache.update({"id_instalacion": id_instalacion, "licencia_activada": True})
        _escribir_cache(cache)
    return resultado
