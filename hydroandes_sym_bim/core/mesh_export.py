# -*- coding: utf-8 -*-
"""
core/mesh_export.py

Exportación de los resultados del solver 2D (core/swe2d.py) a los
formatos que QGIS entiende de forma NATIVA, sin plugins de terceros:

  * Malla SMS 2DM (.2dm) — la geometría, leída por MDAL (Mesh Data
    Abstraction Library), el motor de mallas incorporado en QGIS. Es el
    mismo formato que usan SMS, HEC-RAS 2D y BASEMENT.
  * Conjuntos de datos ASCII (.dat) — los resultados sobre esa malla,
    escalares (calado, velocidad, peligrosidad) y vectoriales
    (velocidad con dirección), con o sin variación en el tiempo.
  * GeoTIFF — los mapas de máximos, para quien prefiera trabajar en
    ráster (álgebra de mapas, reclasificación de peligro).

POR QUÉ MALLA Y NO SOLO RÁSTER: cargada como QgsMeshLayer, la serie
temporal se reproduce con el Controlador Temporal nativo de QGIS —
animación del avance de la inundación, flechas de velocidad, perfiles
en un corte— sin exportar un ráster por instante. Un ráster de máximos
responde «hasta dónde llegó»; la malla temporal responde «cuándo llegó
y con qué velocidad», que es lo que hace falta para justificar un plazo
de evacuación o el dimensionamiento de una obra de paso.

NOTA SOBRE LA NUMERACIÓN: 2DM es 1-indexado y ordena los nodos de cada
elemento en sentido ANTIHORARIO. Un orden horario produce elementos con
área negativa que MDAL carga pero representa mal (celdas invisibles o
volteadas). El sentido correcto depende de la orientación del ráster:
como en un GeoTIFF la fila 0 es la del NORTE, la Y decrece con la fila,
y el orden antihorario en coordenadas de terreno es el que se aplica
aquí.
"""
import os
import warnings
import numpy as np


class MeshExportError(Exception):
    pass


def _malla_de_grilla(n_filas, n_columnas, x_min, y_max, dx, dy, activo=None):
    """
    Construye nodos y elementos de una grilla regular, VECTORIZADO.

    Se evita a propósito el bucle en Python celda a celda: una malla de
    1000x1000 son 10^6 elementos y 10^6 nodos, y construirla con bucles
    tarda minutos, mientras que con NumPy son décimas de segundo.

    activo: máscara booleana (n_filas, n_columnas). Las celdas fuera del
        dominio no generan elemento, para no exportar la mitad de un
        rectángulo vacío alrededor de la cuenca.
    """
    n_nodos_x = n_columnas + 1
    n_nodos_y = n_filas + 1

    # Coordenadas de los nodos (esquinas de celda).
    ix = np.arange(n_nodos_x)
    iy = np.arange(n_nodos_y)
    malla_x, malla_y = np.meshgrid(ix, iy)
    xs = x_min + malla_x * dx
    ys = y_max - malla_y * dy
    nodos = np.column_stack([xs.ravel(), ys.ravel()])

    # Índices de los 4 nodos de cada celda (1-indexado para 2DM).
    filas_celda, cols_celda = np.meshgrid(np.arange(n_filas), np.arange(n_columnas),
                                           indexing="ij")
    # Esquinas: superior-izquierda, superior-derecha, inferior-derecha,
    # inferior-izquierda en índices de fila/columna.
    n_si = filas_celda * n_nodos_x + cols_celda + 1
    n_sd = n_si + 1
    n_id = (filas_celda + 1) * n_nodos_x + cols_celda + 2
    n_ii = n_id - 1
    # Antihorario en coordenadas de terreno (Y hacia arriba): partiendo
    # de la esquina inferior-izquierda.
    elementos = np.column_stack([n_ii.ravel(), n_id.ravel(), n_sd.ravel(), n_si.ravel()])

    if activo is not None:
        elementos = elementos[activo.ravel()]

    return nodos, elementos


def exportar_2dm(ruta_2dm, zb, dx, dy, x_min, y_max, activo=None):
    """
    Escribe la geometría de la malla en formato SMS 2DM.

    zb: cotas de fondo (n_filas, n_columnas). La cota del nodo se toma
        como la media de las celdas que lo rodean, que es lo correcto
        para una malla de nodos aunque el cálculo sea en centros: usar
        la cota de una celda cualquiera introduce un desfase de media
        celda en el terreno representado.
    """
    zb = np.asarray(zb, dtype=np.float64)
    n_filas, n_columnas = zb.shape
    nodos, elementos = _malla_de_grilla(n_filas, n_columnas, x_min, y_max, dx, dy, activo)

    # Cota de nodo = media de las celdas adyacentes, con relleno en el
    # borde replicando la celda de contorno.
    zb_relleno = np.pad(np.where(np.isfinite(zb), zb, np.nan), 1, mode="edge")
    ventanas = np.stack([zb_relleno[:-1, :-1], zb_relleno[:-1, 1:],
                          zb_relleno[1:, :-1], zb_relleno[1:, 1:]])
    # Un nodo rodeado íntegramente de celdas sin dato no tiene cota que
    # promediar; nanmean avisa de la rebanada vacía. Se silencia porque
    # es el caso esperado en el contorno del dominio y el nan_to_num de
    # abajo ya le asigna un valor: no es un error que deba llegar al
    # registro de QGIS en cada exportación.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        with np.errstate(invalid="ignore"):
            z_nodos = np.nanmean(ventanas, axis=0)
    z_nodos = np.nan_to_num(z_nodos, nan=0.0).ravel()

    if len(z_nodos) != len(nodos):
        raise MeshExportError(
            f"Desajuste al construir la malla: {len(nodos)} nodos frente a "
            f"{len(z_nodos)} cotas. Es un error interno del exportador.")

    lineas = ["MESH2D"]
    lineas.extend(
        f"ND {i + 1} {x:.4f} {y:.4f} {z:.4f}"
        for i, (x, y, z) in enumerate(zip(nodos[:, 0], nodos[:, 1], z_nodos)))
    lineas.extend(
        f"E4Q {i + 1} {a} {b} {c} {d} 1"
        for i, (a, b, c, d) in enumerate(elementos))

    with open(ruta_2dm, "w", encoding="utf-8") as f:
        f.write("\n".join(lineas))
        f.write("\n")
    return {"ruta": ruta_2dm, "nodos": len(nodos), "elementos": len(elementos)}


def exportar_dataset_escalar(ruta_dat, nombre, valores_por_tiempo, tiempos,
                             n_nodos, n_elementos, activo=None,
                             en_centros: bool = True):
    """
    Escribe un conjunto de datos ASCII de MDAL (.dat) asociado a la malla.

    valores_por_tiempo: lista de arrays 2D, uno por instante.
    tiempos: lista de tiempos en HORAS (es la unidad que MDAL espera en
        la cabecera TS de este formato).
    en_centros=True: los valores están en el centro de cada celda, así
        que el dataset se declara sobre ELEMENTOS (ND 0 en la cabecera).
        Es lo que corresponde a un esquema de volúmenes finitos: fingir
        que están en los nodos obligaría a interpolar e inventaría
        suavidad que el cálculo no tiene.
    """
    with open(ruta_dat, "w", encoding="utf-8") as f:
        f.write("DATASET\n")
        f.write("OBJTYPE \"mesh2d\"\n")
        f.write("BEGSCL\n")
        f.write(f"ND {n_nodos}\n")
        f.write(f"NC {n_elementos}\n")
        f.write(f"NAME \"{nombre}\"\n")
        for t, valores in zip(tiempos, valores_por_tiempo):
            datos = np.asarray(valores, dtype=np.float64)
            if activo is not None:
                datos = datos[activo]
            datos = datos.ravel()
            f.write(f"TS 0 {t:.6f}\n")
            f.write("\n".join(f"{v:.6f}" for v in datos))
            f.write("\n")
        f.write("ENDDS\n")
    return ruta_dat


def exportar_dataset_vectorial(ruta_dat, nombre, vx_por_tiempo, vy_por_tiempo,
                               tiempos, n_nodos, n_elementos, activo=None):
    """
    Dataset VECTORIAL (.dat) para dibujar flechas de velocidad en QGIS.

    Se exporta aparte del escalar porque la dirección del flujo es lo que
    permite leer un mapa de inundación como un fenómeno y no como una
    mancha: dónde se concentra la corriente, por dónde ataca a un
    estribo, hacia dónde evacuar.
    """
    with open(ruta_dat, "w", encoding="utf-8") as f:
        f.write("DATASET\n")
        f.write("OBJTYPE \"mesh2d\"\n")
        f.write("BEGVEC\n")
        f.write(f"ND {n_nodos}\n")
        f.write(f"NC {n_elementos}\n")
        f.write(f"NAME \"{nombre}\"\n")
        for t, vx, vy in zip(tiempos, vx_por_tiempo, vy_por_tiempo):
            ax = np.asarray(vx, dtype=np.float64)
            ay = np.asarray(vy, dtype=np.float64)
            if activo is not None:
                ax, ay = ax[activo], ay[activo]
            f.write(f"TS 0 {t:.6f}\n")
            f.write("\n".join(f"{a:.6f} {b:.6f}" for a, b in zip(ax.ravel(), ay.ravel())))
            f.write("\n")
        f.write("ENDDS\n")
    return ruta_dat


def exportar_geotiff(ruta_tif, matriz, dx, dy, x_min, y_max, wkt_crs=None,
                     nodata=-9999.0):
    """
    Escribe una matriz como GeoTIFF georreferenciado, para los mapas de
    máximos (calado, velocidad, peligrosidad).
    """
    try:
        from osgeo import gdal, osr
    except ImportError:
        raise MeshExportError(
            "No se pudo importar GDAL para escribir el GeoTIFF. GDAL viene con QGIS, "
            "así que este error solo aparece fuera de QGIS.")

    matriz = np.asarray(matriz, dtype=np.float64)
    filas, columnas = matriz.shape
    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(ruta_tif, columnas, filas, 1, gdal.GDT_Float32,
                       options=["COMPRESS=DEFLATE", "TILED=YES"])
    if ds is None:
        raise MeshExportError(f"No se pudo crear el archivo: {ruta_tif}")
    ds.SetGeoTransform((x_min, dx, 0.0, y_max, 0.0, -dy))
    if wkt_crs:
        srs = osr.SpatialReference()
        srs.ImportFromWkt(wkt_crs)
        ds.SetProjection(srs.ExportToWkt())
    banda = ds.GetRasterBand(1)
    banda.SetNoDataValue(nodata)
    banda.WriteArray(np.where(np.isfinite(matriz), matriz, nodata))
    banda.FlushCache()
    ds = None
    return ruta_tif


def exportar_resultados_completos(simulador, carpeta, prefijo, x_min, y_max,
                                   instantes=None, wkt_crs=None,
                                   solo_dominio_activo=True):
    """
    Escribe el paquete completo de resultados: malla, datasets temporales
    de calado y velocidad, y GeoTIFF de los tres mapas de máximos.

    instantes: lista de (tiempo_s, h, vx, vy) capturada durante la
        simulación. Si es None, solo se exportan los máximos -- útil
        cuando no interesa la animación y sí el mapa de peligro.

    Devuelve un dict con las rutas escritas, para poder cargarlas en
    QGIS y decirle al usuario exactamente qué se generó.
    """
    if not os.path.isdir(carpeta):
        raise MeshExportError(f"La carpeta de salida no existe: {carpeta}")

    activo = simulador.activo if solo_dominio_activo else None
    zb_export = np.where(simulador.activo, simulador.zb, np.nan)

    rutas = {}
    ruta_2dm = os.path.join(carpeta, f"{prefijo}_malla.2dm")
    info_malla = exportar_2dm(ruta_2dm, zb_export, simulador.dx, simulador.dy,
                              x_min, y_max, activo=activo)
    rutas["malla_2dm"] = ruta_2dm
    rutas["nodos"] = info_malla["nodos"]
    rutas["elementos"] = info_malla["elementos"]

    if instantes:
        tiempos_h = [t / 3600.0 for t, _, _, _ in instantes]
        rutas["calado_dat"] = exportar_dataset_escalar(
            os.path.join(carpeta, f"{prefijo}_calado.dat"), "Calado (m)",
            [h for _, h, _, _ in instantes], tiempos_h,
            info_malla["nodos"], info_malla["elementos"], activo=activo)
        rutas["velocidad_dat"] = exportar_dataset_vectorial(
            os.path.join(carpeta, f"{prefijo}_velocidad.dat"), "Velocidad (m/s)",
            [vx for _, _, vx, _ in instantes], [vy for _, _, _, vy in instantes],
            tiempos_h, info_malla["nodos"], info_malla["elementos"], activo=activo)

    mascara = simulador.activo
    for clave, matriz, nombre in (
            ("calado_max_tif", simulador.h_max, "calado_maximo"),
            ("velocidad_max_tif", simulador.v_max, "velocidad_maxima"),
            ("peligrosidad_tif", simulador.peligrosidad(), "peligrosidad")):
        salida = np.where(mascara, matriz, np.nan)
        rutas[clave] = exportar_geotiff(
            os.path.join(carpeta, f"{prefijo}_{nombre}.tif"), salida,
            simulador.dx, simulador.dy, x_min, y_max, wkt_crs=wkt_crs)

    return rutas


# ----------------------------------------------------------------------
# Clasificación de peligrosidad
# ----------------------------------------------------------------------
# Umbrales de h·v (m²/s) para estabilidad de PERSONAS, según la guía
# británica FD2320 (Defra/Environment Agency) y recogidos de forma
# equivalente en la normativa española de zonificación de zonas
# inundables. Se usan sobre el máximo de cada celda, no sobre un
# instante: el peligro de un punto lo define el peor momento.
CLASES_PELIGROSIDAD = [
    (0.0,  "Baja",       "Precaución: inundación somera o lenta.",            "#c6e2ff"),
    (0.75, "Moderada",   "Peligroso para algunos (niños, personas mayores).", "#ffe08a"),
    (1.25, "Alta",       "Peligroso para la mayoría de las personas.",        "#ff9f45"),
    (2.5,  "Muy alta",   "Peligroso para todos, incluidos equipos de rescate.", "#d1332e"),
]


def clasificar_peligrosidad(matriz_hv, umbral_seco=1e-3):
    """
    Reparte el área inundada entre las clases de peligro y devuelve
    también la matriz de clases, lista para simbolizar en QGIS.
    """
    matriz = np.asarray(matriz_hv, dtype=np.float64)
    clases = np.zeros_like(matriz, dtype=np.int16)
    for indice, (umbral, _, _, _) in enumerate(CLASES_PELIGROSIDAD):
        clases[matriz >= umbral] = indice
    clases[matriz < umbral_seco] = -1        # seco

    total = int(np.sum(clases >= 0))
    reparto = []
    for indice, (umbral, nombre, descripcion, color) in enumerate(CLASES_PELIGROSIDAD):
        celdas = int(np.sum(clases == indice))
        reparto.append({
            "clase": nombre, "umbral_hv": umbral, "descripcion": descripcion,
            "color": color, "celdas": celdas,
            "porcentaje": (celdas / total * 100.0) if total else 0.0,
        })
    return {"clases": clases, "reparto": reparto, "celdas_inundadas": total}
