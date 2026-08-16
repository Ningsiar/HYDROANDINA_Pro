# -*- coding: utf-8 -*-
"""
ui/estabilidad_muros_canvas.py

Diagrama de cuerpo libre de alto impacto para la verificación de
estabilidad de un muro de contención en voladizo (ver
core/estabilidad_muros.py) -- geometría acotada, el empuje activo Pa
y el peso resultante N como vectores, y el diagrama de presiones de
contacto bajo la zapata (trapezoidal o rectangular equivalente si
e>B/6), con un cuadro de estado (cumple/no cumple) de cada
verificación. Mismo patrón que ui/bim_canvas.py (FigureCanvas +
chart_style).
"""
try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
except ImportError:
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.patches import Polygon, FancyArrow

from .chart_style import aplicar_estilo_graficos

aplicar_estilo_graficos()

_COLOR_CONCRETO = "#B5B2AC"
_COLOR_RELLENO = "#C9A876"
_COLOR_EMPUJE = "#c0392b"
_COLOR_PESO = "#2c6fa8"
_COLOR_OK = "#1e8449"
_COLOR_FALLA = "#c0392b"


class EstabilidadMurosCanvas(FigureCanvas):
    """Diagrama de cuerpo libre del muro -- ver docstring del módulo."""

    def __init__(self, parent=None, width=7.6, height=6.2, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.ax = self.fig.add_subplot(111)
        super().__init__(self.fig)
        self.setParent(parent)
        self.setMinimumSize(int(width * dpi), int(height * dpi))

    def graficar(self, resultado: dict, condicion: str = "estatico"):
        """`resultado`: dict de
        core.estabilidad_muros.verificar_muro_contencion(). `condicion`:
        "estatico" o "sismico" (si hay resultado sísmico disponible)."""
        self.ax.clear()
        geo = resultado["geometria"]
        datos = resultado[condicion]
        if datos is None:
            self.ax.text(0.5, 0.5, f"Sin resultado para la condición «{condicion}»",
                          ha="center", va="center", transform=self.ax.transAxes)
            self.fig.tight_layout()
            self.draw()
            return

        b_puntera = geo["b_puntera_m"]
        e_pantalla = geo["espesor_pantalla_m"]
        e_zapata = geo["espesor_zapata_m"]
        b_total = geo["b_total_m"]
        h_relleno = geo["h_total_m"] - e_zapata

        # --- zapata (rectángulo B x e_zapata, base en z=0) ---
        self.ax.add_patch(Polygon(
            [(0, 0), (b_total, 0), (b_total, e_zapata), (0, e_zapata)],
            closed=True, facecolor=_COLOR_CONCRETO, edgecolor="#3B3B3B", linewidth=0.8, zorder=3))
        # --- pantalla (sobre la zapata, entre puntera y talón) ---
        x0_pantalla = b_puntera
        self.ax.add_patch(Polygon(
            [(x0_pantalla, e_zapata), (x0_pantalla + e_pantalla, e_zapata),
             (x0_pantalla + e_pantalla, e_zapata + h_relleno), (x0_pantalla, e_zapata + h_relleno)],
            closed=True, facecolor=_COLOR_CONCRETO, edgecolor="#3B3B3B", linewidth=0.8, zorder=3))
        # --- relleno sobre el talón ---
        x0_talon = x0_pantalla + e_pantalla
        self.ax.add_patch(Polygon(
            [(x0_talon, e_zapata), (b_total, e_zapata), (b_total, e_zapata + h_relleno),
             (x0_talon, e_zapata + h_relleno)],
            closed=True, facecolor=_COLOR_RELLENO, edgecolor="#8a6d3b", linewidth=0.4, alpha=0.75, zorder=2))

        altura_total = e_zapata + h_relleno

        # --- empuje activo Pa (flecha horizontal, sentido puntera<-talón) ---
        brazo_pa = resultado["empuje_activo"]["brazo_pa_m"]
        y_pa = min(brazo_pa, altura_total * 0.95)
        largo_flecha = b_total * 0.35
        self.ax.add_patch(FancyArrow(
            b_total + largo_flecha, y_pa, -largo_flecha * 0.85, 0, width=altura_total * 0.012,
            head_width=altura_total * 0.045, head_length=largo_flecha * 0.18,
            color=_COLOR_EMPUJE, zorder=5, length_includes_head=True))
        self.ax.text(b_total + largo_flecha * 1.05, y_pa,
                      f"Pa={resultado['empuje_activo']['pa_kn_m']:.1f} kN/m",
                      fontsize=7.5, color=_COLOR_EMPUJE, va="center")

        # --- peso resultante N (flecha vertical en x_barra) ---
        x_barra = datos["excentricidad"]["x_barra_m"]
        y_top_n = altura_total * 1.12
        self.ax.add_patch(FancyArrow(
            x_barra, y_top_n, 0, -(y_top_n - e_zapata) * 0.85, width=b_total * 0.008,
            head_width=b_total * 0.03, head_length=(y_top_n - e_zapata) * 0.15,
            color=_COLOR_PESO, zorder=5, length_includes_head=True))
        self.ax.text(x_barra, y_top_n * 1.03, f"N={resultado['cargas_verticales_kn_m']['n_total']:.1f} kN/m",
                      fontsize=7.5, color=_COLOR_PESO, ha="center")

        # --- diagrama de presiones bajo la zapata ---
        q_max = datos["excentricidad"]["q_max_kpa"]
        q_min = datos["excentricidad"]["q_min_kpa"]
        escala_q = (altura_total * 0.5) / max(q_max, 1e-6)
        y_base_presion = -altura_total * 0.05
        self.ax.plot([0, 0, b_total, b_total],
                      [y_base_presion, y_base_presion - q_min * escala_q,
                       y_base_presion - q_max * escala_q, y_base_presion],
                      color="#555555", linewidth=1.2, zorder=4)
        self.ax.fill([0, 0, b_total, b_total],
                      [y_base_presion, y_base_presion - q_min * escala_q,
                       y_base_presion - q_max * escala_q, y_base_presion],
                      color="#f4b183", alpha=0.6, zorder=1)
        self.ax.text(0, y_base_presion - q_min * escala_q - altura_total * 0.03,
                      f"{q_min:.0f}", fontsize=7, ha="center", color="#555555")
        self.ax.text(b_total, y_base_presion - q_max * escala_q - altura_total * 0.03,
                      f"{q_max:.0f} kPa", fontsize=7, ha="center", color="#555555")

        # --- cotas de geometría ---
        self.ax.annotate("", xy=(0, -altura_total * 0.25), xytext=(b_total, -altura_total * 0.25),
                          arrowprops=dict(arrowstyle="<->", color="#333333", lw=0.8))
        self.ax.text(b_total / 2, -altura_total * 0.30, f"B = {b_total:.2f} m",
                      fontsize=7.5, ha="center")

        # --- cuadro de estado ---
        items_estado = [
            ("FS volteo", datos["fs_volteo"], datos["fs_volteo_minimo"], datos["cumple_volteo"]),
            ("FS deslizamiento", datos["fs_deslizamiento"], datos["fs_deslizamiento_minimo"],
             datos["cumple_deslizamiento"]),
            ("e ≤ B/6", datos["excentricidad"]["excentricidad_m"], b_total / 6.0,
             datos["excentricidad"]["cumple_e_b6"]),
            ("q_max ≤ q_adm", q_max, datos["presion_admisible_kpa"], datos["cumple_capacidad_portante"]),
        ]
        texto_estado = f"Condición: {condicion.upper()}\n"
        for nombre, valor, limite, cumple in items_estado:
            marca = "✓" if cumple else "✗"
            texto_estado += f"{marca} {nombre}: {valor:.2f} (mín./lím. {limite:.2f})\n"
        todo_cumple = all(c for _, _, _, c in items_estado)
        color_caja = _COLOR_OK if todo_cumple else _COLOR_FALLA
        self.ax.text(1.02, 0.98, texto_estado.strip(), transform=self.ax.transAxes, fontsize=7.8,
                      va="top", ha="left", family="monospace",
                      bbox=dict(boxstyle="round", facecolor="white", edgecolor=color_caja, linewidth=1.5))

        self.ax.set_xlim(-b_total * 0.1, b_total * 1.55)
        self.ax.set_ylim(-altura_total * 0.55, altura_total * 1.25)
        self.ax.set_aspect("equal", adjustable="box")
        self.ax.set_xlabel("(m)")
        self.ax.set_ylabel("(m)")
        titulo_ok = "CUMPLE TODAS LAS VERIFICACIONES" if todo_cumple else "NO CUMPLE ALGUNA VERIFICACIÓN"
        self.ax.set_title(f"Estabilidad de Muro de Contención -- {titulo_ok}", fontsize=9.5,
                           color=color_caja, fontweight="bold")
        self.fig.tight_layout()
        self.draw()
