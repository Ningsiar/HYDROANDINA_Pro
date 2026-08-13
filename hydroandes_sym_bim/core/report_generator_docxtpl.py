# -*- coding: utf-8 -*-
"""
core/report_generator_docxtpl.py

Reporte Word "con plantilla y selección de secciones" (item 9 del
pedido): usa docxtpl/Jinja2 sobre la plantilla
hydroandes_sym_bim/resources/plantilla_reporte.docx (ver
scripts/build_report_template.py para su origen versionado), en vez de
armar el documento completo a mano como hace
core/report_generator.py::generar_reporte_word().

Las dos secciones de contenido (tablas/imágenes) son EXACTAMENTE las
mismas funciones de core/report_generator.py::SECCIONES_REPORTE -- solo
cambia dónde se vuelca cada una: aquí, en el .docx de un "subdoc" de
docxtpl (doc.new_subdoc().docx, que expone la misma API de python-docx
que un Document normal) que se inserta en la plantilla en el marcador
{{ subdoc_<clave> }} correspondiente, solo si esa sección fue elegida
por el usuario.

REQUIERE docxtpl (que a su vez requiere docxcompose para new_subdoc()) y
python-docx, además de openpyxl si se quieren adjuntar hojas de cálculo
-- no forma parte de qgis.core, se importa de forma perezosa igual que en
report_generator.py.
"""
import os
from datetime import datetime

from .report_generator import SECCIONES_REPORTE, ReportGeneratorError

RUTA_PLANTILLA_DEFECTO = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resources", "plantilla_reporte.docx"
)


def _requerir_docxtpl():
    try:
        import docxtpl
        return docxtpl
    except ImportError as e:
        raise ReportGeneratorError(
            "docxtpl no está instalado en el intérprete de Python de QGIS. Ejecute "
            "'pip install docxtpl docxcompose' desde el OSGeo4W Shell (Windows) o el terminal con "
            "el Python de QGIS (Linux/Mac), y vuelva a intentar."
        ) from e


def generar_reporte_word_plantilla(ruta_docx: str, contexto: dict, secciones_incluidas,
                                    ruta_plantilla: str = None) -> str:
    """
    ruta_docx: dónde guardar el reporte generado.
    contexto: el mismo dict que usa generar_reporte_word() (ver su
        docstring) -- además puede traer "recomendacion_hidraulica_texto"
        (el texto de dlg.lbl_recomendacion_hidraulica, item 7) para
        incluirlo en la sección de Hidráulica y Drenaje.
    secciones_incluidas: lista/conjunto de claves ('dem', 'morfometria',
        'cn', 'tc', 'frecuencia', 'caudales', 'hidraulica') a incluir en
        el reporte -- las que no estén aquí se omiten POR COMPLETO (ni
        siquiera aparece el título de la sección), a diferencia de
        generar_reporte_word() que siempre muestra las 7 con una nota si
        falta el cálculo.
    ruta_plantilla: por defecto, resources/plantilla_reporte.docx.
    """
    docxtpl = _requerir_docxtpl()
    if not os.path.exists(ruta_plantilla or RUTA_PLANTILLA_DEFECTO):
        raise ReportGeneratorError(
            f"No se encontró la plantilla del reporte en:\n{ruta_plantilla or RUTA_PLANTILLA_DEFECTO}\n"
            "Genérela una vez con 'python-qgis.bat hydroandes_sym_bim/scripts/build_report_template.py'."
        )

    doc = docxtpl.DocxTemplate(ruta_plantilla or RUTA_PLANTILLA_DEFECTO)
    incluidas = set(secciones_incluidas)

    contexto_jinja = {
        "nombre_cuenca": contexto.get("nombre_cuenca") or "(sin nombre)",
        "fecha_generacion": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "nombre_empresa": contexto.get("nombre_empresa") or "CORPORATIVO CONSTRUCTIVO LIMA BERLÍN SRL",
    }
    for clave, _titulo, funcion in SECCIONES_REPORTE:
        se_incluye = clave in incluidas
        contexto_jinja[f"incluir_{clave}"] = se_incluye
        if se_incluye:
            subdoc = doc.new_subdoc()
            try:
                funcion(subdoc.docx, contexto)
            except Exception as e:
                subdoc.docx.add_paragraph(f"(No se pudo generar esta sección: {e})")
            contexto_jinja[f"subdoc_{clave}"] = subdoc
        else:
            contexto_jinja[f"subdoc_{clave}"] = ""

    try:
        doc.render(contexto_jinja)
    except Exception as e:
        raise ReportGeneratorError(f"Error al aplicar la plantilla del reporte: {e}") from e

    os.makedirs(os.path.dirname(ruta_docx) or ".", exist_ok=True)
    doc.save(ruta_docx)
    return ruta_docx
