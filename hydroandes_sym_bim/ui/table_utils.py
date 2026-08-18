# -*- coding: utf-8 -*-
"""
ui/table_utils.py

Utilidades de ajuste automático de tamaño para QTableWidget, usadas desde
plugin_dialog.py para corregir dos problemas recurrentes de la interfaz:

1. ALTO: varias tablas de resultados se construyen con 0 filas y se
   pueblan recién cuando el usuario ejecuta un cálculo, pero nunca
   recalculan su alto después de eso -- se quedan con el alto por
   defecto de Qt (pensado para 0 filas), mostrando solo 2-3 de las N
   filas reales con un scroll interno diminuto y fácil de pasar por
   alto (caso reportado: tabla_distribuciones de la pestaña "Pmax24h",
   con 9 distribuciones ajustadas pero solo 2-3 visibles a la vez sin
   agrandar la ventana ni hacer scroll dentro de la tabla).
2. ANCHO: tablas con TODAS sus columnas en modo ResizeToContents (sin
   ninguna en modo Stretch que absorba el espacio sobrante) pueden sumar
   un ancho natural mayor que el de la ventana cuando alguna columna
   tiene texto largo o de longitud variable (nombres de uso de suelo,
   observaciones, conclusiones de un test estadístico, etc.), forzando
   scroll horizontal en toda la pestaña -- se ve "más ancha que la
   ventana principal".

Ambas funciones son puro PyQt (sin lógica de negocio de ningún módulo de
core/), para poder llamarlas desde cualquier pestaña sin duplicar código.
"""
from qgis.PyQt.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView, QPushButton


def ajustar_alto_tabla(tabla: QTableWidget, filas_visibles_max: int = 12, alto_minimo: int = 70) -> None:
    """
    Recalcula el alto mínimo de `tabla` para que se vean todas sus filas
    actuales sin scroll interno, hasta un máximo de `filas_visibles_max`
    (más allá de eso se permite scroll interno a propósito, para que una
    tabla muy larga -p.ej. la de 30 parámetros de morfometría- no empuje
    el resto de la pestaña fuera de vista).

    IMPORTANTE: debe llamarse cada vez que cambia rowCount() (justo
    después de poblar la tabla con resultados), no solo una vez al
    construirla -- ese es precisamente el bug que corrige.

    Nunca reduce el alto mínimo por debajo del que ya tuviera la tabla
    (p.ej. si algún llamador ya fijó un mínimo generoso a mano): solo
    lo aumenta si el contenido real lo necesita.
    """
    tabla.resizeRowsToContents()
    n_filas = tabla.rowCount()
    alto_header = tabla.horizontalHeader().height()
    if n_filas:
        n_filas_a_medir = min(n_filas, filas_visibles_max)
        alto_filas = sum(tabla.rowHeight(i) for i in range(n_filas_a_medir))
    else:
        # Tabla aún vacía (p.ej. recién construida, antes del primer
        # cálculo): reservar espacio para ~3 filas tipo, para que no
        # colapse a un tamaño casi invisible antes de tener resultados.
        alto_filas = tabla.verticalHeader().defaultSectionSize() * 3
    marco = 2 * tabla.frameWidth()
    alto_calculado = alto_header + alto_filas + marco + 6
    alto_final = max(alto_minimo, alto_calculado, tabla.minimumHeight())
    tabla.setMinimumHeight(alto_final)
    if n_filas > filas_visibles_max:
        # Más filas que el máximo visible: se limita el alto máximo para
        # no dejar que la tabla crezca sin límite; el resto de filas
        # queda accesible con el scroll interno propio de la tabla.
        tabla.setMaximumHeight(alto_final)
    else:
        tabla.setMaximumHeight(16777215)  # sin límite (por defecto de Qt)


def limitar_ancho_tabla(tabla: QTableWidget, ancho_maximo: int = 900) -> None:
    """
    Limita el ancho máximo de `tabla` a `ancho_maximo` píxeles, para
    tablas tipo "matriz" (todas sus columnas son datos igual de
    relevantes, sin una columna de texto largo a la que aplicarle el
    patrón de columna elástica) que además pueden crecer sin límite en
    número de columnas o filas por acción del usuario (ejemplo:
    tabla_comparacion_distribuciones, que agrega una columna por cada
    "T-Diseño" que el usuario quiera comparar, sin tope).

    Con el ancho ya limitado, es la propia tabla la que muestra su
    scroll horizontal interno cuando el contenido no cabe -- en vez de
    forzar a toda la pestaña (y a la ventana) a ensancharse con ella,
    que es el síntoma reportado ("se ve más ancha que la ventana
    principal").
    """
    tabla.setMaximumWidth(ancho_maximo)


def limitar_ancho_boton(boton: QPushButton, margen_px: int = 24) -> None:
    """
    Limita el ancho máximo de `boton` al que necesita su propio texto
    (sizeHint) más un margen, para el caso de botones agregados como
    única fila de un QFormLayout: `form.addRow(boton)` (sin una etiqueta
    de la izquierda) los agrega con QFormLayout.SpanningRole en vez de
    FieldRole, así que el setFieldGrowthPolicy(FieldsStayAtSizeHint) que
    ya tienen los 49 formularios del plugin (desde la v0.2.33) NO les
    aplica -- Qt los estira a todo el ancho de la fila por defecto,
    viéndose desproporcionadamente grandes/gruesos frente al resto de la
    interfaz. Debe llamarse después de crear el botón (su sizeHint ya
    depende del texto final).
    """
    boton.setMaximumWidth(boton.sizeHint().width() + margen_px)


def aplicar_columna_elastica(tabla: QTableWidget, indice_columna_larga: int, anchos_fijos: dict = None) -> None:
    """
    Aplica el patrón "columnas angostas fijas + una columna de texto largo
    en Stretch" (ya usado desde la v0.2.35 en tabla_morfo/tabla_tc/
    tabla_distribuciones): la columna `indice_columna_larga` (la de texto
    más largo o de longitud más variable, p.ej. "Observación",
    "Conclusión", "Uso de suelo") se lleva el espacio sobrante, y el
    resto de columnas queda en ResizeToContents -- o en un ancho fijo
    explícito vía `anchos_fijos` (dict opcional {índice: ancho_px}).

    Esto evita que la suma de columnas en ResizeToContents supere el
    ancho de la ventana cuando esa columna contiene texto de longitud
    variable, sin perder la legibilidad (ResizeToContents) del resto.
    """
    cabecera = tabla.horizontalHeader()
    for col in range(tabla.columnCount()):
        if col == indice_columna_larga:
            cabecera.setSectionResizeMode(col, QHeaderView.Stretch)
        elif anchos_fijos and col in anchos_fijos:
            cabecera.setSectionResizeMode(col, QHeaderView.Fixed)
            tabla.setColumnWidth(col, anchos_fijos[col])
        else:
            cabecera.setSectionResizeMode(col, QHeaderView.ResizeToContents)


def crear_tabla_parametros(con_comentario: bool = True) -> QTableWidget:
    """
    Crea una QTableWidget vacía con el formato estándar de "cuadro de
    resultado" del plugin: Parámetro | Valor | Unidad [| Comentario].
    Reemplaza el patrón anterior (un único QLabel de texto plano
    multilínea, con estilo font-family: monospace) usado en ~14 pestañas
    distintas para mostrar los resultados de un cálculo -- mismo espíritu
    que las tablas Parámetro/Símbolo/Valor/Unidad ya usadas en
    tabla_morfo (Pestaña 2), pero sin columna de símbolo (los resultados
    de estas páginas no tienen un símbolo algebraico corto por parámetro).

    con_comentario=False omite la 4ta columna, para resultados sin
    necesidad de una nota/advertencia por fila.
    """
    n_cols = 4 if con_comentario else 3
    tabla = QTableWidget(0, n_cols)
    encabezados = ["Parámetro", "Valor", "Unidad"] + (["Comentario"] if con_comentario else [])
    tabla.setHorizontalHeaderLabels(encabezados)
    cabecera = tabla.horizontalHeader()
    cabecera.setSectionResizeMode(0, QHeaderView.ResizeToContents)
    cabecera.setSectionResizeMode(1, QHeaderView.ResizeToContents)
    cabecera.setSectionResizeMode(2, QHeaderView.Fixed)
    tabla.setColumnWidth(2, 90)
    if con_comentario:
        # "Comentario" es la única columna de texto potencialmente largo
        # (advertencias, notas); se lleva el espacio sobrante -- mismo
        # patrón que aplicar_columna_elastica().
        cabecera.setSectionResizeMode(3, QHeaderView.Stretch)
    return tabla


def poblar_tabla_parametros(tabla: QTableWidget, filas, filas_visibles_max: int = 16) -> None:
    """
    Llena `tabla` (creada con crear_tabla_parametros) con `filas`: una
    tupla (parametro, valor, unidad) o (parametro, valor, unidad,
    comentario) por fila -- el comentario se ignora si `tabla` no tiene
    4ta columna. `valor` puede ser cualquier tipo: los float se formatean
    con 4 cifras significativas (:.4g), el resto con str().

    Recalcula también el alto de la tabla (ver ajustar_alto_tabla) para
    que se vea completa sin scroll interno, hasta `filas_visibles_max`.
    """
    tabla.setRowCount(0)
    tiene_comentario = tabla.columnCount() > 3
    for fila in filas:
        parametro, valor, unidad = fila[0], fila[1], fila[2]
        comentario = fila[3] if len(fila) > 3 else ""
        row = tabla.rowCount()
        tabla.insertRow(row)
        tabla.setItem(row, 0, QTableWidgetItem(str(parametro)))
        valor_str = f"{valor:.4g}" if isinstance(valor, float) else str(valor)
        tabla.setItem(row, 1, QTableWidgetItem(valor_str))
        tabla.setItem(row, 2, QTableWidgetItem(str(unidad)))
        if tiene_comentario:
            tabla.setItem(row, 3, QTableWidgetItem(str(comentario)))
    ajustar_alto_tabla(tabla, filas_visibles_max=filas_visibles_max)
