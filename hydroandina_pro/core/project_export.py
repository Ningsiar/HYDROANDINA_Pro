# -*- coding: utf-8 -*-
"""
core/project_export.py

Guarda un "paquete de proyecto" portable: copia todas las capas
(ráster/vectoriales) generadas por el plugin a una carpeta local, las
vuelve a referenciar con rutas RELATIVAS dentro de un archivo de
proyecto QGIS (.qgz), y agrega junto a él el reporte Word y el Excel
completo con todos los resultados numéricos — todo en una sola carpeta
que se puede copiar/comprimir y abrir en otra máquina, sin que se rompan
los enlaces a las capas (el problema típico de compartir un proyecto de
QGIS con rutas absolutas).

Estructura generada en la carpeta de destino:
    <carpeta>/
        proyecto_hydroandes.qgz     (o el nombre que se indique)
        capas/
            cuenca.shp / .kml / .geojson
            red_drenaje.shp / .kml / .geojson
            mde_cuenca.tif
            cn_vectorizado.shp   (si se calculó CN automático)
        reporte_completo.docx       (si python-docx está disponible)
        resultados.xlsx             (si openpyxl está disponible)
        resultados_sesion.json      (todos los resultados numéricos en bruto)
"""
import json
import os
import shutil
from typing import Optional


class ProjectExportError(Exception):
    pass


def _copiar_capa_vectorial_a_carpeta(layer, carpeta_capas: str, nombre_base: str, exporters_mod):
    ruta_base = os.path.join(carpeta_capas, nombre_base)
    return exporters_mod.exportar_vector(layer, ruta_base)


def guardar_proyecto_portable(carpeta_destino: str, nombre_proyecto: str,
                               cuenca_layer=None, red_drenaje_layer=None, dem_clip_path: Optional[str] = None,
                               capas_extra: Optional[dict] = None,
                               contexto_reporte: Optional[dict] = None) -> dict:
    """
    capas_extra: dict opcional {nombre: QgsVectorLayer o QgsRasterLayer}
        para incluir capas adicionales (p.ej. el CN vectorizado del
        plugin Curve Number Generator).
    contexto_reporte: si se provee, además se genera el reporte Word y
        el Excel completo (mismo dict que espera
        core/report_generator.generar_reporte_word()).

    Devuelve un dict con las rutas de todo lo generado y una lista de
    advertencias no fatales (p.ej. si python-docx u openpyxl no están
    instalados, esas partes simplemente se omiten con una advertencia,
    en vez de hacer fallar todo el guardado).
    """
    from qgis.core import QgsProject, QgsRasterLayer
    from . import exporters

    os.makedirs(carpeta_destino, exist_ok=True)
    carpeta_capas = os.path.join(carpeta_destino, "capas")
    os.makedirs(carpeta_capas, exist_ok=True)

    advertencias = []
    rutas_generadas = {"capas": []}

    # --- Copiar capas a la carpeta local (rutas relativas al proyecto) ---
    if cuenca_layer is not None:
        try:
            r = _copiar_capa_vectorial_a_carpeta(cuenca_layer, carpeta_capas, "cuenca", exporters)
            rutas_generadas["capas"].extend(r.values())
        except Exception as e:
            advertencias.append(f"No se pudo copiar la capa de cuenca: {e}")

    if red_drenaje_layer is not None:
        try:
            r = _copiar_capa_vectorial_a_carpeta(red_drenaje_layer, carpeta_capas, "red_drenaje", exporters)
            rutas_generadas["capas"].extend(r.values())
        except Exception as e:
            advertencias.append(f"No se pudo copiar la red de drenaje: {e}")

    if dem_clip_path:
        try:
            ruta_tif = os.path.join(carpeta_capas, "mde_cuenca.tif")
            exporters.exportar_raster_tif(QgsRasterLayer(dem_clip_path, "dem_clip"), ruta_tif)
            rutas_generadas["capas"].append(ruta_tif)
        except Exception as e:
            advertencias.append(f"No se pudo copiar el MDE recortado: {e}")

    for nombre, capa in (capas_extra or {}).items():
        try:
            if hasattr(capa, "dataProvider") and capa.type() == capa.RasterLayer:
                ruta_tif = os.path.join(carpeta_capas, f"{nombre}.tif")
                exporters.exportar_raster_tif(capa, ruta_tif)
                rutas_generadas["capas"].append(ruta_tif)
            else:
                r = _copiar_capa_vectorial_a_carpeta(capa, carpeta_capas, nombre, exporters)
                rutas_generadas["capas"].extend(r.values())
        except Exception as e:
            advertencias.append(f"No se pudo copiar la capa adicional '{nombre}': {e}")

    # --- Guardar el proyecto QGIS con rutas relativas ---
    proyecto = QgsProject.instance()
    proyecto.writeEntry("Paths", "/Absolute", False)  # fuerza rutas relativas al archivo .qgz
    ruta_qgz = os.path.join(carpeta_destino, f"{nombre_proyecto}.qgz")
    exito = proyecto.write(ruta_qgz)
    if not exito:
        advertencias.append(
            "QgsProject.write() devolvió False; el .qgz puede no haberse guardado correctamente."
        )
    rutas_generadas["proyecto_qgz"] = ruta_qgz

    # --- Reporte Word + Excel + JSON de resultados en bruto ---
    if contexto_reporte:
        try:
            from . import report_generator
            ruta_docx = os.path.join(carpeta_destino, "reporte_completo.docx")
            report_generator.generar_reporte_word(ruta_docx, contexto_reporte)
            rutas_generadas["reporte_docx"] = ruta_docx
        except Exception as e:
            advertencias.append(f"No se generó el reporte Word: {e}")

        try:
            tablas_excel = _construir_tablas_para_excel(contexto_reporte)
            if tablas_excel:
                ruta_xlsx = os.path.join(carpeta_destino, "resultados.xlsx")
                exporters.exportar_tablas_excel(tablas_excel, ruta_xlsx)
                rutas_generadas["resultados_xlsx"] = ruta_xlsx
        except Exception as e:
            advertencias.append(f"No se generó el Excel de resultados: {e}")

        try:
            ruta_json = os.path.join(carpeta_destino, "resultados_sesion.json")
            with open(ruta_json, "w", encoding="utf-8") as f:
                json.dump(_limpiar_para_json(contexto_reporte), f, ensure_ascii=False, indent=2, default=str)
            rutas_generadas["resultados_json"] = ruta_json
        except Exception as e:
            advertencias.append(f"No se guardó el JSON de resultados de la sesión: {e}")

    rutas_generadas["advertencias"] = advertencias
    return rutas_generadas


def _construir_tablas_para_excel(contexto: dict) -> dict:
    """Aplana el contexto del reporte a hojas de Excel simples (mismo
    patrón que core/exporters.exportar_tablas_excel)."""
    tablas = {}
    morfo = contexto.get("morfometria_resultados") or {}
    if morfo:
        filas = []
        for grupo_key in ("g1", "g2", "g3", "g5", "g6"):
            grupo = morfo.get(grupo_key, {})
            for k, val in grupo.items():
                if k in ("interpretacion", "curva_hipsometrica", "mensaje_alerta") or isinstance(val, (list, dict)):
                    continue
                filas.append({"grupo": grupo_key, "parametro": k, "valor": val})
        if filas:
            tablas["morfometria"] = filas

    if contexto.get("cn_resultados"):
        tablas["curve_number"] = [contexto["cn_resultados"]]
    if contexto.get("desglose_cn"):
        tablas["cn_desglose_lulc_hsg"] = contexto["desglose_cn"]
    if contexto.get("tc_resultados"):
        tablas["tiempo_concentracion"] = [
            {"metodo": k, **{kk: vv for kk, vv in v.items()}} for k, v in contexto["tc_resultados"].items()
        ]
    if contexto.get("hidrograma_resultado"):
        hr = contexto["hidrograma_resultado"]
        if "tiempos_h" in hr:
            tablas["hidrograma_crecida"] = [
                {"tiempo_h": t, "caudal_m3s": q} for t, q in zip(hr["tiempos_h"], hr["caudal_m3s"])
            ]
    if contexto.get("resultados_frecuencia"):
        tablas["ajuste_distribuciones_precipitacion"] = [
            {"distribucion": r["nombre"], "D_ks": r["D_ks"], "D_critico": r["D_critico"],
             "pasa_ks": r["pasa_ks"], **r["parametros"]}
            for r in contexto["resultados_frecuencia"].values() if not r.get("error")
        ]
    if contexto.get("p24_disenio"):
        tablas["precipitaciones_diseno_p24"] = [
            {"periodo_retorno_anios": tr, "p24_mm": p} for tr, p in contexto["p24_disenio"].items()
        ]
    if contexto.get("resultados_hidraulica_drenaje"):
        tablas["hidraulica_y_drenaje"] = [
            {"estructura": nombre, **datos} for nombre, datos in contexto["resultados_hidraulica_drenaje"].items()
        ]
    return tablas


def _limpiar_para_json(obj):
    """Recorre el contexto y descarta objetos no serializables (capas de
    QGIS, etc.), dejando solo los datos numéricos/de texto."""
    if isinstance(obj, dict):
        limpio = {}
        for k, v in obj.items():
            if k == "rutas_imagenes":
                continue
            try:
                limpio[k] = _limpiar_para_json(v)
            except Exception:
                continue
        return limpio
    if isinstance(obj, (list, tuple)):
        return [_limpiar_para_json(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)
