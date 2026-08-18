# -*- coding: utf-8 -*-
"""
ui/chart_style.py

Estilo visual COMÚN a todos los gráficos del plugin, con énfasis en que
las leyendas se lean de un vistazo.

MOTIVO: las leyendas se creaban con los valores por defecto de
matplotlib -- letra de 7-8 pt, sin marco o con un marco tenue, fondo
semitransparente -- y en gráficos densos como la curva Cota-Área-Volumen
quedaban en una esquina, diminutas y sin contraste. En un informe
impreso, una leyenda que no se lee obliga a adivinar qué serie es cuál,
que es justo lo contrario de lo que debe hacer.

CÓMO SE APLICA, Y POR QUÉ ASÍ: en vez de editar una por una las decenas
de llamadas a ax.legend() repartidas por los 14 módulos de lienzo -- con
el riesgo de romper alguna y sin garantía de que las futuras respeten el
criterio -- se fijan los parámetros por defecto de matplotlib
(rcParams). Cada leyenda que se cree a partir de ese momento, en
cualquier gráfico, hereda el estilo automáticamente, incluidas las que
se agreguen más adelante.

Los tamaños son deliberadamente conservadores: una leyenda de alto
impacto es la que se LEE, no la que tapa los datos. Se prioriza el
contraste (marco definido, fondo opaco) sobre el tamaño bruto.
"""

# Paleta coherente con ui/summary_box.py, para que gráficos y cuadros
# resumen se lean como parte del mismo sistema visual.
COLOR_BORDE = "#2c6fa8"
COLOR_FONDO = "#fbfdff"
COLOR_TEXTO = "#1a1a1a"

_aplicado = False


def aplicar_estilo_graficos(forzar: bool = False) -> bool:
    """
    Fija el estilo común de leyendas, rejilla y títulos para todos los
    gráficos del plugin. Idempotente: se puede llamar desde cada módulo
    de lienzo sin coste (solo actúa la primera vez), lo que permite
    invocarla en el import de cada uno sin coordinar quién lo hace.

    Devuelve True si aplicó el estilo, False si ya estaba aplicado.
    """
    global _aplicado
    if _aplicado and not forzar:
        return False
    try:
        import matplotlib
    except ImportError:
        return False

    matplotlib.rcParams.update({
        # --- LEYENDAS: el objetivo principal de este módulo ---
        "legend.fontsize": 9.5,          # antes 7-8 pt: ilegible al imprimir
        "legend.title_fontsize": 10,
        "legend.frameon": True,          # marco siempre, para separarla del fondo
        "legend.framealpha": 0.96,       # casi opaca: la rejilla no se transparenta detrás
        "legend.facecolor": COLOR_FONDO,
        "legend.edgecolor": COLOR_BORDE,
        "legend.fancybox": True,         # esquinas redondeadas, como los cuadros resumen
        "legend.shadow": False,          # la sombra ensucia al imprimir en blanco y negro
        "legend.borderpad": 0.6,         # aire interior: el texto no pega al marco
        "legend.labelspacing": 0.5,
        "legend.handlelength": 2.2,      # trazo de muestra largo: distingue línea de guiones
        "legend.borderaxespad": 0.8,
        # --- Ejes y títulos ---
        "axes.titlesize": 11.5,
        "axes.titleweight": "bold",
        "axes.labelsize": 9.5,
        "axes.edgecolor": "#555555",
        "xtick.labelsize": 8.5,
        "ytick.labelsize": 8.5,
        # --- Rejilla discreta: guía sin competir con las series ---
        "grid.color": "#c8c8c8",
        "grid.linestyle": ":",
        "grid.linewidth": 0.6,
        "figure.facecolor": "white",
        "savefig.facecolor": "white",
        "savefig.dpi": 150,
    })
    _aplicado = True
    return True


def leyenda_impacto(ax, titulo: str = None, loc: str = "best", ncol: int = 1,
                    fuera: bool = False):
    """
    Crea la leyenda de unos ejes con el estilo de alto impacto y, de
    forma opcional, un TÍTULO que explique qué se está comparando.

    El título es lo que más aporta cuando hay varias series: "Método de
    cálculo" o "Periodo de retorno" ahorran al lector tener que deducir
    qué distingue una curva de otra.

    fuera=True coloca la leyenda bajo el gráfico, para cuando hay tantas
    series que dentro taparían los datos.
    """
    manejadores, etiquetas = ax.get_legend_handles_labels()
    if not etiquetas:
        return None
    if fuera:
        leyenda = ax.legend(manejadores, etiquetas, title=titulo, ncol=ncol,
                            loc="upper center", bbox_to_anchor=(0.5, -0.15))
    else:
        leyenda = ax.legend(manejadores, etiquetas, title=titulo, ncol=ncol, loc=loc)
    if leyenda is not None:
        leyenda.get_frame().set_linewidth(1.4)
        if titulo:
            leyenda.get_title().set_fontweight("bold")
            leyenda.get_title().set_color(COLOR_BORDE)
    return leyenda
