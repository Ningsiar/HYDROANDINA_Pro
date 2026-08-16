# -*- coding: utf-8 -*-
"""
ui/zapatas_canvas.py

Diagrama de alto impacto para el diseño de una zapata aislada (ver
core/zapatas.py) -- dos paneles: PLANTA (B×L acotada, columna
centrada, malla de refuerzo inferior en ambas direcciones con su
espaciamiento) y CORTE (perfil h, recubrimiento, peralte efectivo d,
varilla de anclaje/dowel, diagrama de presión de contacto uniforme
bajo la zapata), más un cuadro de estado (cumple/no cumple) de cada
verificación estructural. Mismo patrón que
ui/estabilidad_muros_canvas.py (FigureCanvas + chart_style)."""
try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
except ImportError:
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle

from .chart_style import aplicar_estilo_graficos

aplicar_estilo_graficos()

_COLOR_CONCRETO = "#B5B2AC"
_COLOR_COLUMNA = "#7d7d7d"
_COLOR_ACERO = "#c0392b"
_COLOR_OK = "#1e8449"
_COLOR_FALLA = "#c0392b"
_COLOR_PRESION = "#f4b183"


class ZapataCanvas(FigureCanvas):
    """Diagrama planta + corte de la zapata -- ver docstring del módulo."""

    def __init__(self, parent=None, width=9.4, height=5.4, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.ax_planta = self.fig.add_subplot(121)
        self.ax_corte = self.fig.add_subplot(122)
        super().__init__(self.fig)
        self.setParent(parent)
        self.setMinimumSize(int(width * dpi), int(height * dpi))

    def graficar(self, resultado: dict, b_columna_m: float, h_columna_m: float):
        """`resultado`: dict de core.zapatas.disenar_zapata_aislada().
        `b_columna_m`/`h_columna_m`: dimensiones de la columna (m), no
        vienen en `resultado` porque ese dict solo guarda cm derivados
        -- se pasan aparte para dibujar la columna a escala real."""
        self.ax_planta.clear()
        self.ax_corte.clear()

        b = resultado["b_zapata_m"]
        l = resultado["l_zapata_m"]  # noqa: E741
        h_cm = resultado["peralte_zapata_cm"]
        h_m = h_cm / 100.0
        d_cm = resultado["peralte_efectivo_cm"]
        s_cm = resultado["espaciamiento_sugerido_cm"]
        barra = resultado["barra_sugerida"]

        # ==================================================================
        # PANEL 1: PLANTA
        # ==================================================================
        ax = self.ax_planta
        ax.add_patch(Rectangle((0, 0), b, l, facecolor=_COLOR_CONCRETO, edgecolor="#3B3B3B",
                                linewidth=1.2, zorder=2))
        x0_col, y0_col = (b - b_columna_m) / 2.0, (l - h_columna_m) / 2.0
        ax.add_patch(Rectangle((x0_col, y0_col), b_columna_m, h_columna_m,
                                facecolor=_COLOR_COLUMNA, edgecolor="#2b2b2b", linewidth=1.0, zorder=4))
        ax.text(b / 2.0, l / 2.0, "columna", fontsize=6.5, color="white", ha="center", va="center", zorder=5)

        # malla de refuerzo inferior (ambas direcciones), espaciamiento real si es numerico
        if s_cm:
            paso_m = s_cm / 100.0
            recub_m = 0.075
            n_x = int((b - 2 * recub_m) / paso_m) + 1
            n_y = int((l - 2 * recub_m) / paso_m) + 1
            for i in range(n_x):
                x = recub_m + i * paso_m
                if x <= b - recub_m:
                    ax.plot([x, x], [recub_m, l - recub_m], color=_COLOR_ACERO, linewidth=0.6, zorder=3, alpha=0.85)
            for j in range(n_y):
                y = recub_m + j * paso_m
                if y <= l - recub_m:
                    ax.plot([recub_m, b - recub_m], [y, y], color=_COLOR_ACERO, linewidth=0.6, zorder=3, alpha=0.85)
            ax.text(b * 0.02, -l * 0.12, f"Ø{barra} @ {s_cm:.0f} cm (ambas direcciones, refuerzo inferior)",
                    fontsize=7.5, color=_COLOR_ACERO)

        # cotas B y L
        ax.annotate("", xy=(0, -l * 0.22), xytext=(b, -l * 0.22),
                    arrowprops=dict(arrowstyle="<->", color="#333333", lw=0.8))
        ax.text(b / 2.0, -l * 0.28, f"B = {b:.2f} m", fontsize=8, ha="center")
        ax.annotate("", xy=(-b * 0.14, 0), xytext=(-b * 0.14, l),
                    arrowprops=dict(arrowstyle="<->", color="#333333", lw=0.8))
        ax.text(-b * 0.22, l / 2.0, f"L = {l:.2f} m", fontsize=8, ha="center", rotation=90, va="center")

        ax.set_xlim(-b * 0.35, b * 1.15)
        ax.set_ylim(-l * 0.40, l * 1.15)
        ax.set_aspect("equal", adjustable="box")
        ax.set_title("Planta -- refuerzo inferior", fontsize=9.5)
        ax.set_xlabel("(m)")
        ax.set_ylabel("(m)")

        # ==================================================================
        # PANEL 2: CORTE
        # ==================================================================
        axc = self.ax_corte
        axc.add_patch(Rectangle((0, 0), b, h_m, facecolor=_COLOR_CONCRETO, edgecolor="#3B3B3B",
                                 linewidth=1.2, zorder=2))
        # columna (stub) sobre la zapata
        x0c = (b - b_columna_m) / 2.0
        h_stub = h_m * 0.9
        axc.add_patch(Rectangle((x0c, h_m), b_columna_m, h_stub, facecolor=_COLOR_COLUMNA,
                                 edgecolor="#2b2b2b", linewidth=1.0, zorder=4))
        # dowels (varillas de anclaje) -- 2 simbolicas en los bordes de la columna
        for xd in (x0c + b_columna_m * 0.15, x0c + b_columna_m * 0.85):
            axc.plot([xd, xd], [h_m * 0.08, h_m + h_stub * 0.7], color=_COLOR_ACERO, linewidth=1.4, zorder=5)
        # recubrimiento + peralte efectivo (linea de acero inferior)
        recub_m = 0.075
        axc.plot([recub_m, b - recub_m], [recub_m, recub_m], color=_COLOR_ACERO, linewidth=1.6, zorder=5)
        axc.annotate("", xy=(b * 1.06, 0), xytext=(b * 1.06, h_m),
                     arrowprops=dict(arrowstyle="<->", color="#333333", lw=0.8))
        axc.text(b * 1.10, h_m / 2.0, f"h = {h_cm:.0f} cm\n(d = {d_cm:.1f} cm)",
                  fontsize=7.5, va="center")

        # diagrama de presion de contacto (uniforme, carga axial centrada)
        q_neta = resultado["q_neta_amplificada_kg_cm2"]
        y_base = -h_m * 0.12
        alto_diag = h_m * 0.30
        axc.fill([0, 0, b, b], [y_base, y_base - alto_diag, y_base - alto_diag, y_base],
                 color=_COLOR_PRESION, alpha=0.65, zorder=1)
        axc.plot([0, 0, b, b], [y_base, y_base - alto_diag, y_base - alto_diag, y_base],
                 color="#555555", linewidth=1.0, zorder=3)
        axc.text(b / 2.0, y_base - alto_diag - h_m * 0.08, f"q = {q_neta:.2f} kg/cm²  (uniforme, carga axial)",
                  fontsize=7.5, ha="center", color="#555555")

        axc.set_xlim(-b * 0.08, b * 1.35)
        axc.set_ylim(y_base - alto_diag - h_m * 0.25, h_m + h_stub * 1.15)
        axc.set_aspect("equal", adjustable="box")
        axc.set_title("Corte -- transferencia de fuerzas", fontsize=9.5)
        axc.set_xlabel("(m)")

        # ==================================================================
        # CUADRO DE ESTADO
        # ==================================================================
        items_estado = [
            ("Peralte mínimo", resultado["peralte_zapata_cm"], resultado["peralte_minimo_cm"],
             resultado["cumple_peralte_minimo"]),
            ("Cortante 1 dirección", resultado["cortante_1d"]["vu_kg"],
             resultado["cortante_1d"]["phi_vc_kg"] or 0.0, resultado["cortante_1d"]["cumple"]),
            ("Punzonamiento", resultado["punzonamiento"]["vu_kg"], resultado["punzonamiento"]["phi_vc_kg"],
             resultado["punzonamiento"]["cumple"]),
        ]
        texto_estado = "VERIFICACIONES (E.060 Cap. 15)\n"
        for nombre, valor, limite, cumple in items_estado:
            marca = "OK" if cumple else "NO CUMPLE"
            texto_estado += f"[{marca}] {nombre}: {valor:.1f} / {limite:.1f}\n"
        todo_ok = all(c for _, _, _, c in items_estado)
        color_caja = _COLOR_OK if todo_ok else _COLOR_FALLA
        self.fig.text(0.5, 0.005, texto_estado.strip(), fontsize=7.6, va="bottom", ha="center",
                      family="monospace",
                      bbox=dict(boxstyle="round", facecolor="white", edgecolor=color_caja, linewidth=1.5))

        titulo_ok = "CUMPLE TODAS LAS VERIFICACIONES" if todo_ok else "NO CUMPLE ALGUNA VERIFICACIÓN"
        self.fig.suptitle(f"Diseño de Zapata Aislada {b:.2f}×{l:.2f} m -- {titulo_ok}",
                           fontsize=10.5, color=color_caja, fontweight="bold")
        self.fig.tight_layout(rect=(0, 0.11, 1, 0.94))
        self.draw()
