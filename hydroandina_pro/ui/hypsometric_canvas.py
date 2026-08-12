# -*- coding: utf-8 -*-
"""
ui/hypsometric_canvas.py

Widget de matplotlib embebido en PyQt para graficar la curva
hipsométrica dentro de la Pestaña 4 del diálogo.

NOTA DE COMPATIBILIDAD (QGIS 3.x vs 4.x): QGIS 4.0 (marzo 2026) migró su
UI de Qt5 a Qt6. matplotlib.backends.backend_qt5agg NO funciona bajo
Qt6/PyQt6. Desde matplotlib 3.5, existe el backend genérico
`backend_qtagg` que detecta automáticamente el binding Qt activo
(PyQt5, PyQt6, PySide2 o PySide6), por lo que este módulo funciona sin
cambios tanto en QGIS 3.28-3.44 (Qt5) como en QGIS 4.0+ (Qt6).
"""
try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
except ImportError:
    # Fallback para versiones antiguas de matplotlib sin backend genérico
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

# Estilo comun de leyendas y ejes (ui/chart_style.py). Es idempotente,
# asi que cada lienzo puede invocarlo sin coordinarse con los demas.
from .chart_style import aplicar_estilo_graficos

aplicar_estilo_graficos()


class HypsometricCanvas(FigureCanvas):

    def __init__(self, parent=None, width=6, height=4.6, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.ax = self.fig.add_subplot(111)
        super().__init__(self.fig)
        self.setParent(parent)
        # Tamaño mínimo = el figsize configurado (en píxeles, a dpi). Sin
        # esto, un QScrollArea con widgetResizable=True puede encoger este
        # widget por debajo de su tamaño natural cuando la ventana del
        # plugin es más angosta que el gráfico, deformando el dibujo; con
        # el mínimo fijado, en su lugar aparece una barra de desplazamiento
        # horizontal y el gráfico conserva su forma y proporciones.
        self.setMinimumSize(int(width * dpi), int(height * dpi))

    def plot_curva(self, curva_hipsometrica: list, titulo: str = "Curva hipsométrica"):
        """
        curva_hipsometrica: lista de dicts con 'area_acumulada_pct' y
        'elevacion_m', como los produce
        core.morphometry.grupo4_pendiente_hipsometria().

        Eje X: % de área acumulada de la cuenca sobre cada umbral de cota.
        Eje Y: altitud real (m s.n.m.) — NO elevación relativa (%).
        La curva se dibuja suavizada (interpolación monótona PCHIP si
        scipy está disponible; si no, spline cúbica simple de numpy como
        respaldo) para una lectura de mayor impacto visual, sin alterar
        los puntos de datos originales (que también se marcan).
        """
        import numpy as np

        self.ax.clear()
        # Orden ascendente por área acumulada para que la interpolación
        # monótona funcione correctamente.
        datos = sorted(curva_hipsometrica, key=lambda d: d["area_acumulada_pct"])
        x = np.array([d["area_acumulada_pct"] for d in datos], dtype=float)
        y = np.array([d["elevacion_m"] for d in datos], dtype=float)

        # Eliminar posibles duplicados exactos en X (requeridos por PCHIP)
        x_unico, indices_unicos = np.unique(x, return_index=True)
        y_unico = y[indices_unicos]

        if x_unico.size < 2:
            # Cota prácticamente uniforme en toda la cuenca (posible con un
            # MDE muy grueso sobre una cuenca muy chica, o de relieve casi
            # nulo): no hay suficiente variación de área acumulada para
            # interpolar una curva. Antes esto hacía fallar
            # PchipInterpolator con una excepción sin capturar ("x must
            # contain at least 2 elements"); ahora se informa en el propio
            # gráfico en vez de romper el cálculo.
            self.ax.text(
                0.5, 0.5,
                "Cota casi uniforme en toda la cuenca:\nno hay variación suficiente para "
                "trazar la curva hipsométrica.",
                ha="center", va="center", transform=self.ax.transAxes, fontsize=9.5,
                color="#B3261E", wrap=True,
            )
            self.ax.set_xlabel("Área acumulada (%)")
            self.ax.set_ylabel("Altitud (m s.n.m.)")
            self.ax.set_title(titulo, pad=12)
            self.fig.tight_layout()
            self.draw()
            return

        x_denso = np.linspace(x_unico.min(), x_unico.max(), 300)
        try:
            from scipy.interpolate import PchipInterpolator
            interpolador = PchipInterpolator(x_unico, y_unico)
            y_denso = interpolador(x_denso)
        except ImportError:
            # Respaldo sin scipy: interpolación lineal (menos "suave" pero
            # sin overshoot ni dependencias externas).
            y_denso = np.interp(x_denso, x_unico, y_unico)

        self.ax.plot(x_denso, y_denso, "-", linewidth=2.4, color="#1F6F54", zorder=2,
                     solid_capstyle="round")
        self.ax.fill_between(x_denso, y_denso, y_denso.min(), color="#1F6F54", alpha=0.12, zorder=1)
        self.ax.scatter(x_unico, y_unico, s=22, color="#0B3D2E", zorder=3,
                        label="Datos (20 intervalos de elevación)")

        self.ax.set_xlabel("Área acumulada (%)")
        self.ax.set_ylabel("Altitud (m s.n.m.)")
        self.ax.set_title(titulo, pad=12)
        self.ax.set_xticks(range(0, 101, 10))
        self.ax.grid(True, which="major", axis="x", linestyle=":", linewidth=0.6, color="#999999")
        self.ax.grid(True, which="major", axis="y", linestyle=":", linewidth=0.5)
        self.ax.set_xlim(0, 100)
        # Leyenda debajo del gráfico (no "upper right") para que nunca
        # se superponga con la curva ni con el título.
        self.ax.legend(fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.13), ncol=1, frameon=False)
        self.fig.tight_layout()
        self.draw()

    def guardar_figura(self, ruta_png: str):
        """Exporta la curva hipsométrica actualmente dibujada a un PNG de
        alta resolución (300 dpi), para incluir en el expediente técnico."""
        self.fig.savefig(ruta_png, dpi=300, bbox_inches="tight")
