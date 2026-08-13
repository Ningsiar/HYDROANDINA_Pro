# -*- coding: utf-8 -*-
"""
scripts/generar_clave_licencia.py

Genera una clave de licencia válida para UN id de instalación, con la
MISMA fórmula que verifica scripts/licencia_backend_apps_script.gs
(HMAC-SHA256(secreto, id), primeros 16 caracteres hexadecimales en
mayúsculas, agrupados de a 4 con guiones).

Uso administrativo, fuera del plugin distribuido -- este archivo se
versiona porque NUNCA contiene el secreto real: lo lee de la variable de
entorno HYDROANDINA_LICENCIA_SECRETO, que debe ser IDÉNTICA a
CLAVE_SECRETA en el Apps Script ya desplegado. No hardcodee el secreto
aquí ni lo suba a ningún repositorio.

    # PowerShell
    $env:HYDROANDINA_LICENCIA_SECRETO = "el-mismo-secreto-del-apps-script"
    python scripts/generar_clave_licencia.py <id_de_instalacion_del_cliente>
"""
import hashlib
import hmac
import os
import sys


def generar_clave(id_instalacion: str, secreto: str) -> str:
    firma = hmac.new(secreto.encode("utf-8"), id_instalacion.encode("utf-8"),
                      hashlib.sha256).hexdigest().upper()
    bloque = firma[:16]
    return "-".join(bloque[i:i + 4] for i in range(0, 16, 4))


def main():
    if len(sys.argv) != 2:
        print("Uso: python generar_clave_licencia.py <id_de_instalacion>")
        sys.exit(1)
    secreto = os.environ.get("HYDROANDINA_LICENCIA_SECRETO", "").strip()
    if not secreto:
        print("Falta la variable de entorno HYDROANDINA_LICENCIA_SECRETO "
              "(debe ser idéntica a CLAVE_SECRETA en el Apps Script desplegado).")
        sys.exit(1)
    id_instalacion = sys.argv[1].strip()
    clave = generar_clave(id_instalacion, secreto)
    print(f"Id de instalación: {id_instalacion}")
    print(f"Clave de licencia:  {clave}")


if __name__ == "__main__":
    main()
