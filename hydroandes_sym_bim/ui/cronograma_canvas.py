# -*- coding: utf-8 -*-
"""
ui/cronograma_canvas.py

Módulo "Programación y Cronogramas" -- diagrama de Gantt de alto
impacto, a partir de core/cronograma.py::Cronograma.calcular() /
resumen_actividades(). Mismo patrón que ui/bim_canvas.py y
ui/presupuesto_canvas.py (FigureCanvas + chart_style).

Cada actividad es una barra horizontal desde su Inicio Temprano (ES)
hasta su Fin Temprano (EF); la RUTA CRÍTICA se resalta en rojo (sin
holgura -- cualquier atraso ahí atrasa todo el proyecto), el resto en
azul con su holgura dibujada como una franja punteada más clara desde
EF hasta LF (cuánto puede atrasarse esa actividad sin afectar la fecha
final). Fechas reales en el eje X (no solo "día 1, día 2...").
"""
try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
except ImportError:
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.dates as mdates

from .chart_style import aplicar_estilo_graficos

aplicar_estilo_graficos()

_COLOR_CRITICA = "#c0392b"
_COLOR_NORMAL = "#2c6fa8"
_COLOR_HOLGURA = "#a9c6e0"


class CronogramaCanvas(FigureCanvas):
    """Diagrama de Gantt -- ver docstring del módulo."""

    def __init__(self, parent=None, width=7.6, height=6.0, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.ax = self.fig.add_subplot(111)
        super().__init__(self.fig)
        self.setParent(parent)
        self.setMinimumSize(int(width * dpi), int(height * dpi))

    def graficar_gantt(self, cronograma, resumen: dict, max_actividades: int = 40):
        """`cronograma`: instancia de core.cronograma.Cronograma YA
        calculada (cronograma.calcular() ya ejecutado). `resumen`: el
        dict que devolvió calcular(). Muestra como máximo
        `max_actividades` (las de ES más temprano) para no saturar el
        gráfico en cronogramas grandes -- use la tabla de resultados
        para ver el resto."""
        self.ax.clear()
        filas = cronograma.resumen_actividades()[:max_actividades]
        if not filas:
            self.ax.text(0.5, 0.5, "Sin actividades", ha="center", va="center",
                          transform=self.ax.transAxes)
            self.fig.tight_layout()
            self.draw()
            return

        filas = list(reversed(filas))  # primera actividad arriba
        etiquetas = [f"{f['codigo']} {f['nombre']}"[:45] for f in filas]
        y = list(range(len(filas)))

        for i, f in enumerate(filas):
            es_num = mdates.date2num(f["es_fecha"])
            ef_num = mdates.date2num(f["ef_fecha"])
            lf_num = mdates.date2num(f["lf_fecha"])
            color = _COLOR_CRITICA if f["critica"] else _COLOR_NORMAL
            self.ax.barh(i, ef_num - es_num, left=es_num, height=0.55,
                         color=color, edgecolor="#3B3B3B", linewidth=0.4, zorder=3)
            if not f["critica"] and f["holgura_dias"] and f["holgura_dias"] > 0:
                self.ax.barh(i, lf_num - ef_num, left=ef_num, height=0.55,
                             color=_COLOR_HOLGURA, edgecolor="#3B3B3B", linewidth=0.3,
                             hatch="//", alpha=0.6, zorder=2)

        self.ax.set_yticks(y)
        self.ax.set_yticklabels(etiquetas, fontsize=7.5)
        self.ax.xaxis_date()
        self.fig.autofmt_xdate(rotation=30, ha="right")
        self.ax.xaxis.set_major_formatter(mdates.DateFormatter("%d-%b-%y"))
        self.ax.grid(True, axis="x", linestyle=":", alpha=0.5)
        self.ax.set_axisbelow(True)

        self.ax.plot([], [], color=_COLOR_CRITICA, linewidth=8, label="Ruta crítica (holgura = 0)")
        self.ax.plot([], [], color=_COLOR_NORMAL, linewidth=8, label="Actividad normal")
        self.ax.plot([], [], color=_COLOR_HOLGURA, linewidth=8, alpha=0.6, label="Holgura disponible")
        self.ax.legend(loc="lower right", fontsize=7.5, framealpha=0.9)

        recorte = (f" (mostrando {max_actividades} de {resumen['n_actividades']})"
                   if resumen["n_actividades"] > max_actividades else "")
        self.ax.set_title(
            f"{cronograma.nombre} -- Diagrama de Gantt{recorte}\n"
            f"Duración total: {resumen['duracion_total_dias']:.0f} días "
            f"({resumen['fecha_inicio']:%d-%b-%Y} a {resumen['fecha_fin']:%d-%b-%Y}) -- "
            f"{resumen['n_actividades_criticas']} actividad(es) en la ruta crítica",
            fontsize=9.5)
        self.fig.tight_layout()
        self.draw()
