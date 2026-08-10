# -*- coding: utf-8 -*-
"""
core/pour_point_snap.py

Ajuste automático ("snap") del punto de salida (break point) elegido por
el usuario a la celda de cauce más cercana del ráster de acumulación de
flujo, para evitar que la cuenca delineada salga vacía cuando el clic no
cae exactamente sobre la red de drenaje (causa raíz identificada tras el
reporte de "La cuenca delineada quedó vacía (0 polígonos)").

Este módulo separa deliberadamente la lógica de búsqueda (pura, sin
dependencias de GDAL, testeable con arrays de numpy normales) de la
lectura del ráster real (que sí requiere GDAL, disponible solo dentro
del intérprete de Python embebido en QGIS, no en un entorno de
desarrollo genérico).
"""
import math
from typing import Optional, Tuple

import numpy as np


def _indice_celda_mas_cercana(mascara_cauce: np.ndarray, fila_centro: int, col_centro: int,
                               radio_celdas: int) -> Optional[Tuple[int, int]]:
    """
    Busca, dentro de una ventana cuadrada de radio 'radio_celdas' celdas
    alrededor de (fila_centro, col_centro), la celda True más cercana en
    'mascara_cauce' (array 2D booleano: True = celda de cauce/alta
    acumulación). Devuelve (fila, col) de la celda encontrada, o None si
    no hay ninguna celda de cauce dentro del radio de búsqueda.

    La distancia se mide en celdas (Euclidiana); en caso de empate se
    elige la primera encontrada en el orden de recorrido (no afecta la
    distancia física real ya que están a igual distancia).
    """
    n_filas, n_cols = mascara_cauce.shape
    f0 = max(fila_centro - radio_celdas, 0)
    f1 = min(fila_centro + radio_celdas + 1, n_filas)
    c0 = max(col_centro - radio_celdas, 0)
    c1 = min(col_centro + radio_celdas + 1, n_cols)

    ventana = mascara_cauce[f0:f1, c0:c1]
    filas_validas, cols_validas = np.where(ventana)
    if filas_validas.size == 0:
        return None

    filas_abs = filas_validas + f0
    cols_abs = cols_validas + c0
    distancias2 = (filas_abs - fila_centro) ** 2 + (cols_abs - col_centro) ** 2
    idx_mas_cercano = int(np.argmin(distancias2))

    return int(filas_abs[idx_mas_cercano]), int(cols_abs[idx_mas_cercano])


def _pixel_a_mundo(fila: int, col: int, geotransform: Tuple[float, float, float, float, float, float]) -> Tuple[float, float]:
    """Convierte índices de celda (fila, col) al centro de la celda en
    coordenadas de mapa, usando el geotransform estándar de GDAL."""
    x_origen, ancho_px, _, y_origen, _, alto_px = geotransform
    x = x_origen + (col + 0.5) * ancho_px
    y = y_origen + (fila + 0.5) * alto_px
    return x, y


def _mundo_a_pixel(x: float, y: float, geotransform: Tuple[float, float, float, float, float, float]) -> Tuple[int, int]:
    x_origen, ancho_px, _, y_origen, _, alto_px = geotransform
    col = int((x - x_origen) / ancho_px)
    fila = int((y - y_origen) / alto_px)
    return fila, col


def snap_a_cauce(ruta_raster_cauces: str, x: float, y: float, radio_celdas: int = 15) -> dict:
    """
    Ajusta el punto (x, y) a la celda de cauce más cercana dentro del
    ráster de cauces (típicamente el 'stream' que produce
    grass7:r.watershed, donde las celdas de cauce tienen valor != nodata
    y el resto es nodata).

    radio_celdas: radio de búsqueda en número de celdas (no en metros);
        con un MDE de 30m y radio_celdas=15, el radio de búsqueda real es
        ~450 m. Auméntelo si el punto está más lejos del cauce mapeado.

    Devuelve un dict:
        {
            'encontrado': bool,
            'x': float, 'y': float,              # coordenadas ajustadas (o las originales si no se encontró)
            'distancia_m': float,                 # distancia del punto original al punto ajustado
            'x_original': float, 'y_original': float,
        }
    """
    from osgeo import gdal  # import perezoso: solo disponible dentro de QGIS

    ds = gdal.Open(ruta_raster_cauces)
    if ds is None:
        raise RuntimeError(f"No se pudo abrir el ráster de cauces para el ajuste del punto: {ruta_raster_cauces}")

    geotransform = ds.GetGeoTransform()
    banda = ds.GetRasterBand(1)
    nodata = banda.GetNoDataValue()
    arr = banda.ReadAsArray()
    ds = None

    if nodata is not None:
        mascara_cauce = arr != nodata
    else:
        mascara_cauce = arr > 0

    fila_centro, col_centro = _mundo_a_pixel(x, y, geotransform)
    n_filas, n_cols = mascara_cauce.shape
    if not (0 <= fila_centro < n_filas and 0 <= col_centro < n_cols):
        raise ValueError(
            "El punto de salida cae fuera de la extensión del ráster de cauces; "
            "verifique que el break point esté dentro del área del MDE."
        )

    resultado_indice = _indice_celda_mas_cercana(mascara_cauce, fila_centro, col_centro, radio_celdas)

    if resultado_indice is None:
        return {
            "encontrado": False, "x": x, "y": y, "distancia_m": None,
            "x_original": x, "y_original": y,
        }

    fila_snap, col_snap = resultado_indice
    x_snap, y_snap = _pixel_a_mundo(fila_snap, col_snap, geotransform)
    distancia_m = math.hypot(x_snap - x, y_snap - y)

    return {
        "encontrado": True, "x": x_snap, "y": y_snap, "distancia_m": distancia_m,
        "x_original": x, "y_original": y,
    }
