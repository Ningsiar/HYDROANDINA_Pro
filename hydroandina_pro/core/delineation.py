# -*- coding: utf-8 -*-
"""
core/delineation.py

Orquesta la cadena de preprocesamiento hidrológico del MDE usando
algoritmos ya existentes en QGIS (GRASS/GDAL vía `processing.run`); aquí
NO se reimplementa D8 ni acumulación de flujo desde cero.

Cadena (dividida en 3 funciones independientes, para permitir el ajuste
del punto de salida a la red de drenaje ENTRE el cálculo del flujo y la
delineación de la cuenca — ver core/pour_point_snap.py):

  A. calcular_flujo(): relleno de sumideros -> dirección/acumulación de
     flujo -> ráster de cauces (grass7:r.fill.dir, grass7:r.watershed).
  B. delinear_desde_punto(): delineación de la cuenca desde el punto de
     salida YA AJUSTADO al cauce -> vectorización -> suavizado
     (grass7:r.water.outlet, gdal:polygonize, native:smoothgeometry).
  C. extraer_y_recortar_red(): vectorización y recorte de la red de
     drenaje completa a la cuenca (grass7:r.thin, grass7:r.to.vect,
     native:clip).

NOTA DE COMPATIBILIDAD (verificado en julio 2026): SAGA ya no viene
integrado por defecto en el núcleo de QGIS desde la 3.30 (requiere el
plugin comunitario "Processing Saga NextGen Provider"). Para no
introducir esa dependencia externa, toda la cadena usa únicamente
algoritmos GRASS (empaquetados con QGIS por defecto).

NOTA: "0.25 iteraciones offset" de la especificación original se
interpreta como ITERATIONS=1, OFFSET=0.25 (native:smoothgeometry espera
un entero >=1 de iteraciones y un offset continuo 0-0.5 por separado).

NOTA DE ROBUSTEZ #1 (v0.2.2): los algoritmos `native:*` con salida tipo
sink, con "TEMPORARY_OUTPUT", devuelven a veces un ID interno de capa
(no una ruta) que causó dos bugs distintos. Se corrigió generando rutas
de archivo GeoPackage EXPLÍCITAS con `QgsProcessingUtils.generateTempFilename()`
para smoothgeometry y clip, de modo que TODAS las salidas de la cadena
son siempre archivos reales en disco.

NOTA DE ROBUSTEZ #2 (v0.2.3, esta versión): reporte de "El punto de
salida cae fuera de la extensión del ráster de cauces" incluso con el
punto ya ajustado ("snap") a una celda de cauce válida del propio
ráster de cauces calculado. La causa más probable es que la "región"
interna de GRASS (una configuración de extensión/resolución de trabajo
que GRASS aplica a TODOS sus rásteres de salida, independientemente del
extent real del ráster de entrada) no coincidiera exactamente con la
extensión real del MDE en algún paso de la cadena (p. ej. por defecto,
QGIS calcula la región de forma automática en cada llamada a un
algoritmo GRASS individual, y pueden acumularse pequeñas discrepancias
de redondeo entre pasos sucesivos: r.fill.dir -> r.watershed ->
r.water.outlet). Se corrige fijando explícitamente
`GRASS_REGION_PARAMETER` (formato "xmin,xmax,ymin,ymax", documentado en
la referencia de RQGIS/QGIS) a la extensión real del MDE de entrada en
absolutamente TODAS las llamadas a algoritmos `grass7:*` de la cadena,
en vez de dejar que cada paso la determine de forma independiente.
"""
import processing
from qgis.core import QgsProcessingUtils


def _cellsize_kw(cellsize):
    """Devuelve el parámetro de resolución de GRASS solo si hay un valor;
    pasar None explícitamente haría que el algoritmo lo interprete como un
    valor inválido en vez de omitirlo."""
    return {"GRASS_REGION_CELLSIZE_PARAMETER": cellsize} if cellsize else {}


def _cellsize_dem(dem_layer) -> float:
    """
    Tamaño de celda nativo del MDE, para fijarlo explícitamente en los
    algoritmos GRASS.

    POR QUÉ HACE FALTA (v0.2.55): fijar solo GRASS_REGION_PARAMETER
    (la extensión) no basta. Si no se indica también la resolución, GRASS
    usa la suya por defecto y AJUSTA la extensión pedida para que encaje
    en un número entero de celdas de ESE tamaño -- con lo que los rásteres
    de salida (dirección, acumulación, cauces) pueden quedar desplazados
    hasta una celda respecto del MDE de entrada. Un punto de salida
    elegido cerca del borde entra entonces en el MDE pero cae fuera del
    ráster de cauces, produciendo el error "el punto de salida cae fuera
    de la extensión del ráster de cauces" sin causa aparente.
    """
    return abs(dem_layer.rasterUnitsPerPixelX())


def _region_string(dem_layer) -> str:
    """
    Construye el string de región de GRASS ("xmin,xmax,ymin,ymax") a
    partir de la extensión real del MDE de entrada, para fijarla
    explícitamente en cada algoritmo grass7:* de la cadena y evitar que
    pasos sucesivos recalculen (y potencialmente desajusten) la región
    de forma independiente.
    """
    ext = dem_layer.extent()
    return f"{ext.xMinimum()},{ext.xMaximum()},{ext.yMinimum()},{ext.yMaximum()}"


def calcular_flujo(dem_layer, umbral_acumulacion=25, context=None, feedback=None):
    """
    Relleno de sumideros + dirección y acumulación de flujo D8 + ráster
    de cauces. Devuelve dict con 'raster_direccion', 'raster_acumulacion',
    'raster_cauces' (todas rutas de archivo reales) y 'region' (el string
    de región de GRASS ya calculado, para reutilizar en los pasos
    siguientes de la cadena sin recalcularlo).
    """
    region = _region_string(dem_layer)
    cellsize = _cellsize_dem(dem_layer)

    feedback.pushInfo("1/3 Rellenando sumideros (grass7:r.fill.dir)...")
    relleno = processing.run(
        "grass7:r.fill.dir",
        {"input": dem_layer, "format": 0, "output": "TEMPORARY_OUTPUT",
         "direction": "TEMPORARY_OUTPUT", "areas": "TEMPORARY_OUTPUT",
         "GRASS_REGION_PARAMETER": region,
         **_cellsize_kw(cellsize)},
        context=context, feedback=feedback, is_child_algorithm=True,
    )["output"]

    feedback.pushInfo("2/3 y 3/3 Dirección y acumulación de flujo (grass7:r.watershed)...")
    watershed = processing.run(
        "grass7:r.watershed",
        {
            "elevation": relleno,
            "threshold": umbral_acumulacion,
            "drainage": "TEMPORARY_OUTPUT",
            "accumulation": "TEMPORARY_OUTPUT",
            "stream": "TEMPORARY_OUTPUT",
            "GRASS_REGION_PARAMETER": region,
            **_cellsize_kw(cellsize),
        },
        context=context, feedback=feedback, is_child_algorithm=True,
    )

    return {
        "raster_direccion": watershed["drainage"],
        "raster_acumulacion": watershed["accumulation"],
        "raster_cauces": watershed["stream"],
        "region": region,
        "cellsize": cellsize,
    }


def delinear_desde_punto(raster_direccion, punto_xy, region, cellsize=None, context=None, feedback=None,
                          smooth_iterations=1, smooth_offset=0.25):
    """
    Delimita la cuenca aguas arriba de punto_xy=(x,y) usando el ráster de
    dirección de flujo ya calculado por calcular_flujo(). Se recomienda
    ajustar antes el punto con core.pour_point_snap.snap_a_cauce() usando
    raster_cauces, para evitar cuencas vacías por un punto mal ubicado.

    region: el string de región devuelto por calcular_flujo(), para
        fijar la misma región de GRASS en este paso (ver nota de
        robustez #2 en el docstring del módulo).

    Devuelve la RUTA de archivo (.gpkg) del polígono de cuenca suavizado.
    """
    x, y = punto_xy

    feedback.pushInfo("Delimitando la cuenca desde el punto de salida (grass7:r.water.outlet)...")
    cuenca_raster = processing.run(
        "grass7:r.water.outlet",
        {"input": raster_direccion, "coordinates": f"{x},{y}", "output": "TEMPORARY_OUTPUT",
         "GRASS_REGION_PARAMETER": region,
         **_cellsize_kw(cellsize)},
        context=context, feedback=feedback, is_child_algorithm=True,
    )["output"]

    feedback.pushInfo("Vectorizando el polígono de la cuenca (gdal:polygonize)...")
    poligono_bruto = processing.run(
        "gdal:polygonize",
        {"INPUT": cuenca_raster, "BAND": 1, "FIELD": "cuenca", "OUTPUT": "TEMPORARY_OUTPUT"},
        context=context, feedback=feedback, is_child_algorithm=True,
    )["OUTPUT"]

    feedback.pushInfo(f"Suavizando geometría (native:smoothgeometry, iteraciones={smooth_iterations}, offset={smooth_offset})...")
    ruta_cuenca_suavizada = QgsProcessingUtils.generateTempFilename("cuenca_suavizada.gpkg")
    cuenca_suavizada = processing.run(
        "native:smoothgeometry",
        {"INPUT": poligono_bruto, "ITERATIONS": smooth_iterations, "OFFSET": smooth_offset,
         "MAX_ANGLE": 180, "OUTPUT": ruta_cuenca_suavizada},
        context=context, feedback=feedback, is_child_algorithm=True,
    )["OUTPUT"]

    return cuenca_suavizada


def extraer_y_recortar_red(raster_cauces, ruta_cuenca_vector, region, cellsize=None,
                            context=None, feedback=None):
    """
    Vectoriza el ráster de cauces completo y, si se provee una cuenca,
    lo recorta a ella. Si ruta_cuenca_vector es None, devuelve la red
    completa sin recortar (útil para el Paso A de la pestaña 1, donde
    se genera la red ANTES de delimitar ninguna cuenca).
    Devuelve la RUTA de archivo (.gpkg) de la red resultante.
    """
    feedback.pushInfo("Vectorizando la red de drenaje...")
    cauces_delgados = processing.run(
        "grass7:r.thin", {"input": raster_cauces, "output": "TEMPORARY_OUTPUT",
                          "GRASS_REGION_PARAMETER": region,
         **_cellsize_kw(cellsize)},
        context=context, feedback=feedback, is_child_algorithm=True,
    )["output"]
    red_vector = processing.run(
        "grass7:r.to.vect", {"input": cauces_delgados, "type": 0, "output": "TEMPORARY_OUTPUT",
                             "GRASS_REGION_PARAMETER": region,
         **_cellsize_kw(cellsize)},
        context=context, feedback=feedback, is_child_algorithm=True,
    )["output"]

    if ruta_cuenca_vector is None:
        # Sin cuenca: devolver la red completa sin recortar
        ruta_red_completa = QgsProcessingUtils.generateTempFilename("red_drenaje_completa.gpkg")
        processing.run(
            "native:savefeatures", {"INPUT": red_vector, "OUTPUT": ruta_red_completa},
            context=context, feedback=feedback, is_child_algorithm=True,
        )
        return {"red_drenaje_vector": ruta_red_completa}

    feedback.pushInfo("Recortando la red de drenaje a la cuenca...")
    ruta_red_recortada = QgsProcessingUtils.generateTempFilename("red_drenaje_recortada.gpkg")
    red_recortada = processing.run(
        "native:clip", {"INPUT": red_vector, "OVERLAY": ruta_cuenca_vector, "OUTPUT": ruta_red_recortada},
        context=context, feedback=feedback, is_child_algorithm=True,
    )["OUTPUT"]

    return red_recortada


def diagnosticar_nodata(ruta_o_capa) -> dict:
    """
    Cuenta las celdas SIN DATO de un MDE y su porcentaje sobre el total.

    Se separa del relleno para poder INFORMAR antes de modificar nada: si
    el MDE viene con un 30% de vacíos, rellenarlos es posible pero el
    resultado es en buena parte interpolado, y el usuario debe saberlo
    antes de calcular parámetros sobre él.
    """
    from osgeo import gdal
    import numpy as np

    ruta = ruta_o_capa if isinstance(ruta_o_capa, str) else ruta_o_capa.source()
    ds = gdal.Open(ruta)
    if ds is None:
        raise RuntimeError(f"No se pudo abrir el MDE para diagnosticar sus vacíos: {ruta}")
    banda = ds.GetRasterBand(1)
    nodata = banda.GetNoDataValue()
    arr = banda.ReadAsArray()
    total = arr.size
    ds = None

    if nodata is not None:
        n_vacias = int(np.sum(arr == nodata))
    else:
        # Sin valor sin-dato declarado solo se pueden detectar los NaN de
        # los rásteres en punto flotante; los rellenos con un entero
        # arbitrario son indetectables sin más información, y se advierte.
        n_vacias = int(np.sum(np.isnan(arr.astype("float64"))))

    porcentaje = (n_vacias / total * 100.0) if total else 0.0
    return {
        "nodata_declarado": nodata,
        "celdas_totales": total,
        "celdas_sin_dato": n_vacias,
        "porcentaje_sin_dato": round(porcentaje, 4),
        "tiene_vacios": n_vacias > 0,
        "advertencia": (
            "El MDE no declara valor sin-dato, así que solo se pudieron detectar celdas NaN. Si el "
            "ráster usa un entero convencional (0, -32768) como relleno sin declararlo, esos huecos "
            "pasarán inadvertidos y contaminarán las estadísticas."
            if nodata is None else None
        ),
    }


def rellenar_nodata(dem_layer, distancia_maxima_px: int = 100, iteraciones_suavizado: int = 2,
                     context=None, feedback=None):
    """
    Rellena las celdas sin dato de un MDE por interpolación (gdal:fillnodata,
    que usa ponderación inversa a la distancia desde los bordes del hueco y
    luego suaviza el parche).

    POR QUÉ HACE FALTA, Y POR QUÉ NO ES LO MISMO QUE r.fill.dir: el
    relleno de sumideros que ya aplica calcular_flujo() elimina
    DEPRESIONES cerradas -- celdas con dato, pero más bajas que todas sus
    vecinas -- para que el flujo D8 no quede atrapado. No toca las celdas
    SIN DATO. Los MDE descargados (SRTM, ASTER, Copernicus) traen vacíos
    por sombra de radar o nubosidad, frecuentes justo en terreno abrupto
    como el altoandino. Esos huecos rompen la cadena: la dirección de
    flujo no puede propagarse a través de ellos, la cuenca delineada sale
    recortada o partida, y las estadísticas del MDE (cotas, pendiente,
    curva hipsométrica) se calculan sobre una muestra con agujeros.

    distancia_maxima_px: radio máximo, en celdas, desde el que se buscan
        valores válidos para interpolar. Huecos más anchos que el doble de
        esta distancia quedan parcialmente sin rellenar.
    iteraciones_suavizado: pasadas de suavizado sobre el parche, para que
        no queden discontinuidades artificiales en el borde del hueco que
        luego aparecerían como pendientes falsas.

    TRANSPARENCIA: el relleno INTERPOLA, es decir, inventa cotas donde no
    las hay. Es necesario para que los algoritmos hidrológicos funcionen,
    pero el resultado en esas celdas no es una medición. Por eso
    diagnosticar_nodata() informa del porcentaje antes y después.
    """
    if distancia_maxima_px <= 0:
        raise ValueError("La distancia máxima de búsqueda debe ser mayor que 0 celdas.")
    return processing.run(
        "gdal:fillnodata",
        {"INPUT": dem_layer, "BAND": 1, "DISTANCE": distancia_maxima_px,
         "ITERATIONS": iteraciones_suavizado, "NO_MASK": False,
         "OUTPUT": QgsProcessingUtils.generateTempFilename("mde_relleno.tif")},
        context=context, feedback=feedback, is_child_algorithm=True,
    )["OUTPUT"]


# Valor sin-dato para el MDE recortado. Se elige -9999 por ser el
# convenio más extendido en MDE y quedar muy lejos de cualquier cota
# real de la Tierra (el punto más bajo emergido está a -430 m).
NODATA_MDE = -9999.0


def clip_dem_a_cuenca(dem_layer, cuenca_vector_layer, context=None, feedback=None):
    """
    Recorta y enmascara el MDE al polígono de cuenca (para estadísticas
    zonales, curva hipsométrica, pendiente media, etc.).

    *** POR QUÉ SE FIJA NODATA EXPLÍCITAMENTE (v0.2.58) ***
    Sin el parámetro NODATA, gdalwarp rellena con CERO las celdas del
    rectángulo envolvente que quedan FUERA del polígono de cuenca, y no
    las declara como sin-dato. Esos ceros entran entonces en las
    estadísticas como si fueran cotas reales: en una cuenca altoandina
    con cotas de 3525 a 4558 m, la cota mínima salía 0.0 m s.n.m. (caso
    real reportado). El daño no se queda ahí -- el relieve H = Zmax-Zmin
    pasaba de ~630 m a ~4558 m, y de H dependen la pendiente media de la
    cuenca, la curva hipsométrica y varios de los 14 métodos de tiempo de
    concentración, así que el error se propagaba a TODO el análisis
    aguas abajo, incluido el caudal de diseño.
    Al declarar NODATA, esas celdas quedan correctamente excluidas por
    core/raster_stats.leer_array_valido(), que ya filtraba el sin-dato
    pero no tenía ninguno que filtrar.
    """
    return processing.run(
        "gdal:cliprasterbymasklayer",
        {"INPUT": dem_layer, "MASK": cuenca_vector_layer, "CROP_TO_CUTLINE": True,
         "NODATA": NODATA_MDE, "OUTPUT": "TEMPORARY_OUTPUT"},
        context=context, feedback=feedback, is_child_algorithm=True,
    )["OUTPUT"]


def calcular_pendiente(dem_recortado, context=None, feedback=None):
    """Pendiente celda-a-celda en porcentaje (gdal:slope, SLOPE_FORMAT=1).

    Puede llamarse en modo standalone (context=None), en cuyo caso
    devuelve directamente la ruta del ráster de pendiente generado, o
    encadenado dentro de otro algoritmo pasando context/feedback.
    """
    params = {"INPUT": dem_recortado, "AS_PERCENT": True, "OUTPUT": "TEMPORARY_OUTPUT"}
    if context is not None:
        return processing.run("gdal:slope", params, context=context, feedback=feedback,
                               is_child_algorithm=True)["OUTPUT"]
    return processing.run("gdal:slope", params, feedback=feedback)["OUTPUT"]
