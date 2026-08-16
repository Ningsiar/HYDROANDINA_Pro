# -*- coding: utf-8 -*-
"""
ui/presupuesto_canvas.py

Módulo "Presupuesto, APU e Insumos" -- fase 2 (interfaz): gráfico de
alto impacto de la composición de costos, a partir de
core/presupuesto.py::Presupuesto.resumen() y
Presupuesto.relacion_insumos(). Dos paneles:
  - Barras horizontales con las partidas de mayor peso sobre el Costo
    Directo (top N), para ver de un vistazo dónde está el dinero.
  - Dona con la composición por tipo de insumo (Mano de Obra,
    Materiales, Equipos, Herramienta Manual, Subcontratos).
Mismo patrón que ui/bim_canvas.py (FigureCanvas + chart_style), sin
depender de nada de core/ directamente -- recibe los dicts ya
calculados.
"""
try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
except ImportError:
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from .chart_style import aplicar_estilo_graficos

aplicar_estilo_graficos()

_COLOR_POR_TIPO = {
    "Mano de Obra": "#2c6fa8",
    "Materiales": "#d9822b",
    "Equipos": "#4c9a5b",
    "Herramienta Manual": "#a63d5c",
    "Subcontratos": "#7a5ea8",
}


class PresupuestoCanvas(FigureCanvas):
    """Gráfico de alto impacto de la composición de costos de un
    Presupuesto -- ver docstring del módulo."""

    def __init__(self, parent=None, width=7.6, height=5.0, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.ax_barras = self.fig.add_subplot(121)
        self.ax_dona = self.fig.add_subplot(122)
        super().__init__(self.fig)
        self.setParent(parent)
        self.setMinimumSize(int(width * dpi), int(height * dpi))

    def graficar_composicion(self, resumen: dict, relacion_insumos: list, top_n: int = 12):
        """`resumen`: dict de Presupuesto.resumen() (usa "composicion" y
        "costo_directo"). `relacion_insumos`: lista de
        Presupuesto.relacion_insumos() (se agrupa por "tipo")."""
        self.ax_barras.clear()
        self.ax_dona.clear()

        # --- Panel izquierdo: top N partidas por peso sobre el Costo Directo ---
        composicion = sorted(resumen.get("composicion", []), key=lambda f: f["parcial"], reverse=True)
        top = composicion[:top_n]
        if top:
            etiquetas = [f"{f['codigo']} {f['descripcion']}"[:42] for f in reversed(top)]
            valores = [f["parcial"] for f in reversed(top)]
            pcts = [f["pct_costo_directo"] for f in reversed(top)]
            barras = self.ax_barras.barh(etiquetas, valores, color="#2c6fa8")
            for barra, pct, valor in zip(barras, pcts, valores):
                self.ax_barras.text(
                    barra.get_width() * 1.01, barra.get_y() + barra.get_height() / 2,
                    f"{valor:,.0f} ({pct:.1f}%)", va="center", fontsize=7.5)
            self.ax_barras.set_xlabel("Parcial (S/.)")
            titulo_top = f"Top {len(top)} partidas" if len(composicion) > top_n else "Partidas"
            self.ax_barras.set_title(f"{titulo_top} por Costo Directo", fontsize=10)
            self.ax_barras.tick_params(axis="y", labelsize=7.5)
        else:
            self.ax_barras.text(0.5, 0.5, "Sin partidas", ha="center", va="center", transform=self.ax_barras.transAxes)

        # --- Panel derecho: composición por tipo de insumo (dona) ---
        costos_por_tipo = {}
        for fila in relacion_insumos:
            costos_por_tipo[fila["tipo"]] = costos_por_tipo.get(fila["tipo"], 0.0) + fila["costo_total"]
        costos_por_tipo = {t: c for t, c in costos_por_tipo.items() if c > 0}
        if costos_por_tipo:
            tipos = list(costos_por_tipo.keys())
            valores = [costos_por_tipo[t] for t in tipos]
            colores = [_COLOR_POR_TIPO.get(t, "#888888") for t in tipos]
            wedges, _texts, autotexts = self.ax_dona.pie(
                valores, colors=colores, autopct="%1.1f%%", pctdistance=0.8,
                wedgeprops={"width": 0.4, "edgecolor": "white"}, startangle=90,
                textprops={"fontsize": 8})
            for at in autotexts:
                at.set_color("white")
                at.set_fontweight("bold")
            self.ax_dona.legend(wedges, tipos, loc="upper center", bbox_to_anchor=(0.5, -0.02),
                                 fontsize=7.5, ncol=1)
            self.ax_dona.set_title("Composición por tipo de insumo", fontsize=10)
        else:
            self.ax_dona.text(0.5, 0.5, "Sin insumos", ha="center", va="center", transform=self.ax_dona.transAxes)

        self.fig.tight_layout()
        self.draw()
