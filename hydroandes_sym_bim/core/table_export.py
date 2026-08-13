# -*- coding: utf-8 -*-
"""
core/table_export.py

Exportación genérica de un QTableWidget a CSV o XLSX, y texto TSV
(separado por tabulaciones, el formato que Excel/Sheets reconocen al
pegar) para copiar al portapapeles. Es el motor detrás del botón de
descarga flotante que ui/export_overlay.py agrega a TODAS las tablas de
resultados del plugin (item 9 del pedido: "todas las tablas... deben
tener un botón de descarga").

openpyxl se importa de forma perezosa, igual que python-docx en
core/report_generator.py, para no romper el resto del plugin si falta en
el intérprete de Python de QGIS.
"""
import csv
import os


class TableExportError(Exception):
    pass


def _filas_desde_tabla(tabla, incluir_encabezados: bool = True):
    """Lee un QTableWidget (o cualquier objeto con la misma interfaz
    mínima: rowCount/columnCount/item/horizontalHeaderItem) fila por fila
    como texto plano -- es exactamente lo que el usuario VE en pantalla,
    ya con el formateo que cada pestaña aplicó a cada celda."""
    filas = []
    n_col = tabla.columnCount()
    if incluir_encabezados:
        encabezados = []
        for c in range(n_col):
            item_encabezado = tabla.horizontalHeaderItem(c)
            encabezados.append(item_encabezado.text() if item_encabezado else f"Col {c + 1}")
        filas.append(encabezados)
    for r in range(tabla.rowCount()):
        fila = []
        for c in range(n_col):
            item = tabla.item(r, c)
            fila.append(item.text() if item else "")
        filas.append(fila)
    return filas


def exportar_tabla_a_csv(tabla, ruta: str) -> str:
    """delimiter=';' -- con ',' como separador decimal (configuración
    regional en español) Excel interpreta mal un CSV separado por comas;
    ';' es lo que Excel en español espera por defecto."""
    filas = _filas_desde_tabla(tabla)
    os.makedirs(os.path.dirname(ruta) or ".", exist_ok=True)
    with open(ruta, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerows(filas)
    return ruta


def _sanitizar_nombre_hoja(nombre: str) -> str:
    """Excel prohíbe : \\ / ? * [ ] en el nombre de una hoja y limita a 31
    caracteres."""
    for caracter in ":\\/?*[]":
        nombre = nombre.replace(caracter, "_")
    nombre = nombre.strip() or "Datos"
    return nombre[:31]


def exportar_tabla_a_xlsx(tabla, ruta: str, nombre_hoja: str = "Datos") -> str:
    try:
        import openpyxl
        from openpyxl.styles import Font
    except ImportError as e:
        raise TableExportError(
            "openpyxl no está instalado en el intérprete de Python de QGIS. Ejecute "
            "'pip install openpyxl' desde el OSGeo4W Shell (Windows) o el terminal con el "
            "Python de QGIS (Linux/Mac), y vuelva a intentar."
        ) from e
    filas = _filas_desde_tabla(tabla)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = _sanitizar_nombre_hoja(nombre_hoja)
    for fila in filas:
        ws.append(fila)
    if filas:
        for celda in ws[1]:
            celda.font = Font(bold=True)
        for columna in ws.columns:
            ancho = max((len(str(c.value)) for c in columna if c.value is not None), default=8)
            ws.column_dimensions[columna[0].column_letter].width = min(max(ancho + 2, 8), 45)
    os.makedirs(os.path.dirname(ruta) or ".", exist_ok=True)
    wb.save(ruta)
    return ruta


def texto_tsv_desde_tabla(tabla) -> str:
    """Texto separado por tabulaciones -- lo que Excel/Sheets reconocen al
    pegar con Ctrl+V -- para el botón "Copiar" del overlay flotante."""
    filas = _filas_desde_tabla(tabla)
    return "\n".join("\t".join(celda for celda in fila) for fila in filas)
