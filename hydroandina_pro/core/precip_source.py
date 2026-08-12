# -*- coding: utf-8 -*-
"""
core/precip_source.py

Adquisición de la serie de precipitación máxima anual en 24 horas, por
tres vías:

  1. Extracción desde un archivo NetCDF de PISCOp (v2.1, v3.0, o similar)
     ya descargado localmente por el usuario, en el píxel más cercano a
     una coordenada (lon, lat).
  2. Importación desde un CSV (anio, p24_mm), p. ej. proveniente de una
     estación SENAMHI o de un análisis externo.
  3. Entrada/pegado manual en una tabla editable de la interfaz (ver
     ui/pasteable_table.py), con soporte de copiar/pegar estilo Excel.

SOBRE LA DESCARGA AUTOMÁTICA DESDE FIGSHARE (transparencia importante):
el enlace de figshare compartido es la página de un artículo/dataset, no
la URL directa de descarga de un archivo .nc específico, y esa página
no pudo abrirse en este entorno (bloqueo de bot de figshare al intentar
leerla programáticamente). Por esa razón, este módulo NO implementa una
descarga automática no verificable desde figshare: en su lugar, se pide
al usuario descargar manualmente el archivo NetCDF desde la página del
dataset (enlace en la interfaz) y cargarlo aquí. El formato NetCDF de
PISCOp (dimensiones time/latitude/longitude, un archivo por variable) SÍ
está documentado y verificado contra múltiples publicaciones (Aybar et
al., 2020; Huerta et al., 2022); lo que no se pudo verificar es el
nombre exacto de la variable de precipitación en el archivo v3.0
específico, por lo que se intenta autodetectar entre varios nombres
comunes y se deja como parámetro editable si falla.

Requiere xarray (o netCDF4 como respaldo) instalado en el intérprete de
Python de QGIS para la vía 1; se importa de forma perezosa con un
mensaje de error explicativo si no está disponible (igual que openpyxl
en exporters.py). Las vías 2 y 3 no requieren dependencias adicionales.

DESDE ESTA VERSIÓN: extraer_serie_diaria_desde_netcdf() generaliza la
extracción de píxel-más-cercano a CUALQUIER grilla lon/lat/time, no solo
PISCOp -- en particular CHIRPS v2.0 (Funk et al., 2015, "The climate
hazards infrared precipitation with stations - a new environmental
record for monitoring extremes") e IMERG/GPM V07B (misión conjunta
NASA-JAXA). Esto habilita comparar/validar el dato grillado contra una
estación (ver core/gridded_validation.py) usando la misma ruta de
extracción que ya se usaba para la Pestaña 5.
"""
import csv
from dataclasses import dataclass
from typing import List, Optional


NOMBRES_VARIABLE_PROBABLES = ["precip", "pr", "z", "Band1", "prec", "precipitation", "precipitationCal"]
# 'precip' cubre además CHIRPS v2.0 (Funk et al., 2015, "The climate hazards infrared
# precipitation with stations..."); 'precipitation'/'precipitationCal' cubren IMERG/GPM
# (Huffman et al., "GPM IMERG Final Precipitation L3 1 day", V07B) -- ver
# extraer_serie_diaria_desde_netcdf() más abajo, que generaliza la extracción para
# cualquiera de estas fuentes grilladas, no solo PISCOp.


@dataclass
class SerieAnual:
    anios: List[int]
    valores_mm: List[float]
    fuente: str


@dataclass
class SerieDiaria:
    fechas: List[str]  # ISO 'YYYY-MM-DD'
    valores_mm: List[float]
    fuente: str
    variable_detectada: str


def construir_serie_anual(anios: List[int], valores_mm: List[float], fuente: str,
                           minimo_anios_recomendado: int = 10) -> SerieAnual:
    """
    Construye y valida una SerieAnual a partir de listas ya parseadas de
    años y valores de P24 (mm), sin importar su origen (CSV, tabla
    editada manualmente, NetCDF). Centraliza la validación de longitud
    mínima de la serie para que todas las vías de adquisición de datos
    (CSV, tabla manual, PISCOp) apliquen el mismo criterio.
    """
    if len(anios) != len(valores_mm):
        raise ValueError(
            f"El número de años ({len(anios)}) no coincide con el número de valores de P24 "
            f"({len(valores_mm)}); revise que no haya filas con una sola columna completada."
        )
    if len(valores_mm) < minimo_anios_recomendado:
        raise ValueError(
            f"La serie tiene solo {len(valores_mm)} años; un análisis de frecuencia confiable "
            "para periodos de retorno largos (250-1000 años) requiere idealmente 25-30+ años "
            "de registro. Los resultados con series cortas deben tomarse con cautela."
        )
    return SerieAnual(list(anios), list(valores_mm), fuente)


def cargar_csv_serie_anual(ruta_csv: str, columna_anio: str = "anio",
                            columna_valor: str = "p24_mm") -> SerieAnual:
    """
    Carga una serie de máximos anuales ya calculada desde un CSV con
    encabezado, p. ej.:
        anio,p24_mm
        1990,58.4
        1991,63.1
        ...
    """
    anios, valores = [], []
    with open(ruta_csv, newline="", encoding="utf-8") as f:
        lector = csv.DictReader(f)
        if columna_anio not in lector.fieldnames or columna_valor not in lector.fieldnames:
            raise ValueError(
                f"El CSV debe tener columnas '{columna_anio}' y '{columna_valor}'. "
                f"Columnas encontradas: {lector.fieldnames}"
            )
        for fila in lector:
            anios.append(int(fila[columna_anio]))
            valores.append(float(fila[columna_valor]))

    return construir_serie_anual(anios, valores, f"CSV manual: {ruta_csv}")


def construir_serie_desde_tabla(filas_texto: List[List[str]]) -> SerieAnual:
    """
    Construye una SerieAnual a partir de filas de texto crudo tomadas
    directamente de una tabla editable en la interfaz (dos columnas:
    año, P24 en mm) — la misma vía usada tanto si el usuario escribió
    los valores a mano como si los pegó desde Excel/LibreOffice.

    Ignora silenciosamente las filas completamente vacías (comunes al
    final de una tabla con más filas de las que el usuario llenó), pero
    reporta un error claro si una fila tiene solo una de las dos
    columnas completadas (dato a medio ingresar).
    """
    anios, valores = [], []
    for n_fila, celdas in enumerate(filas_texto, start=1):
        celdas = celdas + ["", ""]  # asegurar al menos 2 elementos
        texto_anio, texto_valor = celdas[0].strip(), celdas[1].strip()

        if not texto_anio and not texto_valor:
            continue  # fila vacía, se ignora

        if bool(texto_anio) != bool(texto_valor):
            raise ValueError(
                f"Fila {n_fila} de la tabla tiene solo una de las dos columnas completada "
                f"(año='{texto_anio}', P24='{texto_valor}'). Complete ambas o deje la fila vacía."
            )

        try:
            anios.append(int(float(texto_anio)))
        except ValueError:
            raise ValueError(f"Fila {n_fila}: el año '{texto_anio}' no es un número entero válido.")
        try:
            valores.append(float(texto_valor))
        except ValueError:
            raise ValueError(f"Fila {n_fila}: el valor de P24 '{texto_valor}' no es un número válido.")

    return construir_serie_anual(anios, valores, "Tabla ingresada manualmente en la interfaz")


def extraer_serie_diaria_desde_netcdf(ruta_nc: str, lon: float, lat: float,
                                       nombre_variable: Optional[str] = None,
                                       nombre_fuente: Optional[str] = None) -> SerieDiaria:
    """
    Extrae la serie DIARIA completa de precipitación en el píxel más
    cercano a (lon, lat) de un archivo NetCDF con dimensiones
    lon/lat/time -- formato compartido por PISCOp, CHIRPS v2.0 (Funk et
    al., 2015) e IMERG/GPM V07B (Huffman et al., NASA/JAXA), entre otras
    grillas de precipitación. Generaliza la lógica de extracción que
    antes solo existía para PISCOp en extraer_serie_anual_desde_netcdf()
    (que ahora se apoya en esta función), y es la que usa
    core/gridded_validation.py para comparar el dato grillado contra una
    estación en el mismo periodo.

    NO SE PUDO PROBAR en este entorno (sin acceso a un archivo NetCDF
    real ni a red); la lógica de apertura/selección de píxel más cercano
    sigue el patrón estándar de xarray, pero pruébela primero con un
    archivo pequeño antes de un uso en producción. En particular, CHIRPS
    y algunas variantes de IMERG distribuyen un archivo por año/mes (no
    uno solo con toda la serie); si su flujo requiere concatenar varios
    archivos, hágalo con xr.open_mfdataset() antes o llame a esta
    función una vez por archivo y una los resultados.
    """
    try:
        import xarray as xr
    except ImportError as e:
        raise RuntimeError(
            "xarray no está instalado en el intérprete de Python de QGIS. "
            "Instálelo con 'pip install xarray netCDF4' desde el OSGeo4W Shell "
            "(Windows) o el terminal con el Python de QGIS (Linux/Mac)."
        ) from e

    ds = xr.open_dataset(ruta_nc)

    variable = nombre_variable
    if variable is None:
        for candidata in NOMBRES_VARIABLE_PROBABLES:
            if candidata in ds.data_vars:
                variable = candidata
                break
        if variable is None:
            variables_disponibles = list(ds.data_vars)
            ds.close()
            raise ValueError(
                f"No se pudo autodetectar la variable de precipitación. "
                f"Variables disponibles en el archivo: {variables_disponibles}. "
                "Especifique 'nombre_variable' explícitamente."
            )

    dim_lon = "longitude" if "longitude" in ds.coords else "lon"
    dim_lat = "latitude" if "latitude" in ds.coords else "lat"
    dim_tiempo = "time" if "time" in ds.coords else "z"

    punto = ds[variable].sel({dim_lon: lon, dim_lat: lat}, method="nearest")

    fechas = [str(t)[:10] for t in punto[dim_tiempo].values]
    valores = [float(v) for v in punto.values]
    ds.close()

    fuente = nombre_fuente or f"NetCDF: {ruta_nc}"
    return SerieDiaria(
        fechas, valores, f"{fuente} (var='{variable}', pixel más cercano a lon={lon}, lat={lat})", variable
    )


def extraer_serie_anual_desde_netcdf(ruta_nc: str, lon: float, lat: float,
                                      nombre_variable: Optional[str] = None) -> SerieAnual:
    """
    Extrae la serie de máximos anuales de precipitación diaria en el
    píxel más cercano a (lon, lat) de un archivo NetCDF de PISCOp (o
    cualquier grilla compatible; ver extraer_serie_diaria_desde_netcdf(),
    que hace la extracción propiamente dicha y que esta función usa
    internamente antes de resumir por máximo anual).
    """
    import numpy as _np

    diaria = extraer_serie_diaria_desde_netcdf(ruta_nc, lon, lat, nombre_variable, "PISCOp NetCDF")

    # Máximo anual: se agrupa por año calendario. Si el usuario requiere
    # año hidrológico (p. ej. ago-jul, típico en régimen andino con
    # estiaje/avenida bien diferenciados), debe desplazarse la fecha
    # antes de llamar a esta función (no se asume aquí un año
    # hidrológico específico para no imponer un supuesto no solicitado).
    anios_por_dia = _np.array([int(f[:4]) for f in diaria.fechas])
    valores = _np.array(diaria.valores_mm, dtype=float)
    anios_unicos = sorted(set(anios_por_dia.tolist()))
    max_por_anio = [float(_np.nanmax(valores[anios_por_dia == a])) for a in anios_unicos]

    return SerieAnual(anios_unicos, max_por_anio, diaria.fuente)
