# -*- coding: utf-8 -*-
"""
core/raster_stats.py

Lectura de arrays del MDE (recortado a la cuenca) con GDAL/numpy, para
alimentar los grupos 1 (elevaciones) y 4 (pendiente/curva hipsométrica)
de morphometry.py. Se usa `osgeo.gdal` porque viene incluido con QGIS
(no es una dependencia adicional que el usuario deba instalar).
"""
import numpy as np
from osgeo import gdal


def leer_array_valido(ruta_raster: str) -> np.ndarray:
    """Devuelve un array 1D con todos los píxeles válidos (sin nodata)
    de la banda 1 del ráster indicado."""
    ds = gdal.Open(ruta_raster)
    if ds is None:
        raise RuntimeError(f"No se pudo abrir el ráster: {ruta_raster}")
    banda = ds.GetRasterBand(1)
    nodata = banda.GetNoDataValue()
    arr = banda.ReadAsArray().astype("float64")
    ds = None
    if nodata is not None:
        arr = arr[arr != nodata]
    arr = arr[~np.isnan(arr)]
    return arr.ravel()


def valor_en_punto(ruta_raster: str, x: float, y: float) -> float:
    """Muestrea el valor de la banda 1 en la coordenada (x, y), que debe
    estar en el mismo CRS que el ráster."""
    ds = gdal.Open(ruta_raster)
    if ds is None:
        raise RuntimeError(f"No se pudo abrir el ráster: {ruta_raster}")
    gt = ds.GetGeoTransform()
    banda = ds.GetRasterBand(1)

    col = int((x - gt[0]) / gt[1])
    row = int((y - gt[3]) / gt[5])

    if col < 0 or row < 0 or col >= ds.RasterXSize or row >= ds.RasterYSize:
        ds = None
        raise ValueError("El punto de salida cae fuera de la extensión del ráster.")

    valor = banda.ReadAsArray(col, row, 1, 1)[0][0]
    nodata = banda.GetNoDataValue()
    ds = None
    if nodata is not None and valor == nodata:
        raise ValueError("El punto de salida cae en una celda sin datos (nodata) del MDE.")
    return float(valor)
