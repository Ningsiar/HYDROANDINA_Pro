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


def leer_elevacion_2d(ruta_raster: str):
    """Devuelve (array_2d, dx, dy) del ráster indicado: la matriz 2D de
    elevación completa (con np.nan en las celdas sin dato) y el tamaño
    de celda en X e Y (m), leído de la geotransformada -- para
    alimentar visores 3D (ui/dem_relief_3d_canvas.py,
    ui/swe2d_canvas.py) que necesitan la malla completa, a diferencia
    de leer_array_valido() (que aplana y descarta la posición de cada
    celda)."""
    ds = gdal.Open(ruta_raster)
    if ds is None:
        raise RuntimeError(f"No se pudo abrir el ráster: {ruta_raster}")
    banda = ds.GetRasterBand(1)
    nodata = banda.GetNoDataValue()
    arr = banda.ReadAsArray().astype("float64")
    gt = ds.GetGeoTransform()
    ds = None
    if nodata is not None:
        arr = np.where(arr == nodata, np.nan, arr)
    dx = abs(gt[1])
    dy = abs(gt[5])
    return arr, dx, dy


def proyectar_lineas_a_malla_local(ruta_raster: str, partes_xy):
    """
    Convierte una o varias polilíneas dadas en coordenadas REALES (mismo
    CRS que `ruta_raster`, típicamente la red de drenaje ya delineada)
    al sistema de coordenadas "local" que usa la malla 3D de
    ui.dem_relief_3d_canvas.DemRelieve3DCanvas.plot_dem() -- origen en la
    esquina superior-izquierda del ráster, eje X = columna*dx, eje
    Y = fila*dy -- y muestrea la cota Z (vecino más cercano) en cada
    vértice, lista para superponer el río sobre el relieve
    (DemRelieve3DCanvas.agregar_rio()).

    partes_xy: lista de polilíneas, cada una una lista de (x, y) reales
        (p.ej. una por cada tramo/feature de la capa de red de drenaje,
        para no unir con una línea recta dos cauces que no están
        conectados entre sí).

    Devuelve una lista paralela de (x_local, y_local, z) -- arrays de
    numpy -- una tupla por cada polilínea de entrada con al menos un
    vértice válido; los vértices fuera del ráster o sobre celdas sin
    dato se omiten (no se insertan como NaN, para no cortar la línea con
    huecos).
    """
    ds = gdal.Open(ruta_raster)
    if ds is None:
        raise RuntimeError(f"No se pudo abrir el ráster: {ruta_raster}")
    gt = ds.GetGeoTransform()
    banda = ds.GetRasterBand(1)
    nodata = banda.GetNoDataValue()
    arr = banda.ReadAsArray().astype("float64")
    n_cols, n_filas = ds.RasterXSize, ds.RasterYSize
    ds = None
    dx, dy = abs(gt[1]), abs(gt[5])

    resultado = []
    for parte in partes_xy:
        xs_local, ys_local, zs = [], [], []
        for x, y in parte:
            col_f = (x - gt[0]) / gt[1]
            row_f = (y - gt[3]) / gt[5]
            col_i, row_i = int(round(col_f)), int(round(row_f))
            if col_i < 0 or col_i >= n_cols or row_i < 0 or row_i >= n_filas:
                continue
            z = arr[row_i, col_i]
            if (nodata is not None and z == nodata) or np.isnan(z):
                continue
            xs_local.append(col_f * dx)
            ys_local.append(row_f * dy)
            zs.append(float(z))
        if len(xs_local) >= 2:
            resultado.append((np.array(xs_local), np.array(ys_local), np.array(zs)))
    return resultado


def exportar_raster_a_ascii(ruta_entrada: str, ruta_salida: str):
    """
    Convierte un ráster (típicamente el MDE) a formato ESRI ASCII Grid
    (.asc) -- texto plano, el formato más portable para abrirlo en otro
    software GIS/CAD (ArcGIS, SAGA, Civil 3D, Global Mapper, etc.) sin
    depender del driver GeoTIFF.
    """
    ds_entrada = gdal.Open(ruta_entrada)
    if ds_entrada is None:
        raise RuntimeError(f"No se pudo abrir el ráster de entrada: {ruta_entrada}")
    driver = gdal.GetDriverByName("AAIGrid")
    if driver is None:
        ds_entrada = None
        raise RuntimeError("El driver GDAL 'AAIGrid' (ESRI ASCII Grid) no está disponible en esta instalación.")
    ds_salida = driver.CreateCopy(ruta_salida, ds_entrada)
    if ds_salida is None:
        ds_entrada = None
        raise RuntimeError(f"No se pudo escribir el archivo ASCII: {ruta_salida}")
    ds_entrada = None
    ds_salida = None


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


def valor_en_punto(ruta_raster: str, x: float, y: float,
                   radio_busqueda_celdas: int = 15, devolver_detalle: bool = False):
    """
    Muestrea el valor de la banda 1 en la coordenada (x, y), que debe
    estar en el mismo CRS que el ráster.

    POR QUÉ BUSCA LA CELDA VÁLIDA MÁS CERCANA, Y NO SOLO LA EXACTA: el
    punto de salida de una cuenca está, por definición, en su BORDE. Al
    recortar el MDE con el polígono de la cuenca, GDAL descarta las
    celdas cuyo centro cae fuera del polígono, así que la celda del punto
    de salida queda como nodata con muchísima frecuencia -- no por un
    error del usuario ni por un MDE defectuoso, sino por cómo funciona el
    recorte. Fallar ahí interrumpía todo el cálculo morfométrico por una
    celda de diferencia.

    Tomar la celda válida más próxima es correcto desde el punto de vista
    físico: a la resolución típica de un MDE (12-30 m), la celda vecina
    del punto de salida difiere en centímetros de cota, muy por debajo
    del error vertical del propio MDE. Lo que NO sería correcto es
    inventar un valor o devolver cero en silencio, así que el detalle de
    a qué distancia se encontró queda disponible para avisar.

    Si el punto cae fuera de la extensión pero a menos de
    `radio_busqueda_celdas`, se acerca al borde y se busca desde ahí:
    también es el caso del punto de salida justo en el límite. Más lejos
    que eso sí es un problema real (normalmente un desajuste de CRS) y se
    informa como tal.

    devolver_detalle=True devuelve (valor, detalle) con la distancia a la
    que se encontró la celda usada.
    """
    ds = gdal.Open(ruta_raster)
    if ds is None:
        raise RuntimeError(f"No se pudo abrir el ráster: {ruta_raster}")
    gt = ds.GetGeoTransform()
    banda = ds.GetRasterBand(1)
    nodata = banda.GetNoDataValue()
    n_cols, n_filas = ds.RasterXSize, ds.RasterYSize
    tam_x, tam_y = abs(gt[1]), abs(gt[5])

    col = int((x - gt[0]) / gt[1])
    row = int((y - gt[3]) / gt[5])

    if (col < -radio_busqueda_celdas or row < -radio_busqueda_celdas or
            col >= n_cols + radio_busqueda_celdas or row >= n_filas + radio_busqueda_celdas):
        ds = None
        raise ValueError(
            "El punto de salida cae fuera de la extensión del ráster.\n\n"
            "Suele indicar que el punto y el MDE están en CRS distintos: verifique que el punto de "
            "salida se tomó sobre el MDE ya reproyectado a la zona UTM local."
        )

    # Punto en el borde exterior: se acerca al ráster y se busca desde ahí.
    col_busqueda = min(max(col, 0), n_cols - 1)
    row_busqueda = min(max(row, 0), n_filas - 1)

    col0 = max(0, col_busqueda - radio_busqueda_celdas)
    fila0 = max(0, row_busqueda - radio_busqueda_celdas)
    ancho = min(n_cols, col_busqueda + radio_busqueda_celdas + 1) - col0
    alto = min(n_filas, row_busqueda + radio_busqueda_celdas + 1) - fila0

    ventana = banda.ReadAsArray(col0, fila0, ancho, alto).astype("float64")
    ds = None

    valido = ~np.isnan(ventana)
    if nodata is not None:
        valido &= (ventana != nodata)
    # Un MDE recortado no tiene cotas negativas ni el -9999 de relleno:
    # si el nodata no viniera declarado en la cabecera, este filtro evita
    # devolver el valor de relleno como si fuera una elevación real.
    valido &= (ventana > -9000.0)

    if not valido.any():
        raise ValueError(
            "No hay ninguna celda con dato del MDE en el entorno del punto de salida "
            f"({radio_busqueda_celdas} celdas a la redonda).\n\n"
            "Active el relleno de celdas NoData en la Pestaña 1 y vuelva a delimitar la cuenca."
        )

    # Posición del punto REAL dentro de la ventana. Puede caer fuera de
    # ella si el punto estaba fuera del ráster: se usa igual como origen
    # de las distancias, para que la distancia informada sea la que
    # separa el punto pedido de la celda que finalmente se usó, y no una
    # medida desde el borde al que se acercó la búsqueda.
    fila_rel, col_rel = row - fila0, col - col0
    dentro = (0 <= fila_rel < alto) and (0 <= col_rel < ancho)

    if dentro and valido[fila_rel, col_rel]:
        valor = float(ventana[fila_rel, col_rel])
        detalle = {"celda_exacta": True, "distancia_celdas": 0.0, "distancia_m": 0.0}
    else:
        filas_v, cols_v = np.nonzero(valido)
        # Distancia real en metros: con un píxel no cuadrado, contar
        # celdas elegiría la celda equivocada.
        d2 = (((filas_v - fila_rel) * tam_y) ** 2 + ((cols_v - col_rel) * tam_x) ** 2)
        i = int(np.argmin(d2))
        valor = float(ventana[filas_v[i], cols_v[i]])
        detalle = {
            "celda_exacta": False,
            "distancia_celdas": float(np.hypot(filas_v[i] - fila_rel, cols_v[i] - col_rel)),
            "distancia_m": float(np.sqrt(d2[i])),
        }

    return (valor, detalle) if devolver_detalle else valor
