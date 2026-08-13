# -*- coding: utf-8 -*-
"""
ui/hydrograph_canvas.py

Widget de matplotlib embebido para graficar el hidrograma de crecida
resultante (Pestaña 5).

NOTA DE COMPATIBILIDAD: ver ui/hypsometric_canvas.py — se usa el backend
genérico backend_qtagg para funcionar tanto en QGIS 3.x (Qt5) como 4.x (Qt6).
"""
try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
except ImportError:
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

# Estilo comun de leyendas y ejes (ui/chart_style.py). Es idempotente,
# asi que cada lienzo puede invocarlo sin coordinarse con los demas.
from .chart_style import aplicar_estilo_graficos

aplicar_estilo_graficos()


class HydrographCanvas(FigureCanvas):

    def __init__(self, parent=None, width=6.5, height=4.8, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.ax = self.fig.add_subplot(111)
        super().__init__(self.fig)
        self.setParent(parent)
        # Ver comentario equivalente en ui/hypsometric_canvas.py: evita que
        # el QScrollArea deforme el gráfico al angostar la ventana.
        self.setMinimumSize(int(width * dpi), int(height * dpi))

    def plot_hidrograma(self, tiempos_h, caudal_m3s, metodo: str, qp: float, tp: float):
        import numpy as np

        self.ax.clear()

        tiempos_h = np.asarray(tiempos_h, dtype=float)
        caudal_m3s = np.asarray(caudal_m3s, dtype=float)

        # El hidrograma se calcula con el Dt del hietograma de entrada
        # (frecuentemente 0.5-1 h), lo que da un aspecto de tramos rectos/
        # "quebrado" al graficarlo directo. Para una lectura de más impacto
        # visual, se interpola a un paso de tiempo mucho más fino (PCHIP,
        # que no genera sobreoscilaciones espurias entre puntos, a
        # diferencia de un spline cúbico común) SOLO para el dibujo; los
        # valores calculados (Qp, Tp, la tabla, la exportación) no cambian.
        if len(tiempos_h) >= 3:
            t_fino = np.linspace(tiempos_h.min(), tiempos_h.max(), max(len(tiempos_h) * 12, 300))
            try:
                from scipy.interpolate import PchipInterpolator
                q_fino = PchipInterpolator(tiempos_h, caudal_m3s)(t_fino)
            except ImportError:
                q_fino = np.interp(t_fino, tiempos_h, caudal_m3s)
            q_fino = np.clip(q_fino, 0.0, None)  # el caudal no puede ser negativo
        else:
            t_fino, q_fino = tiempos_h, caudal_m3s

        self.ax.plot(t_fino, q_fino, linewidth=2.0, color="#1F3864")
        self.ax.fill_between(t_fino, q_fino, alpha=0.12, color="#1F3864")
        self.ax.plot(tiempos_h, caudal_m3s, "o", markersize=3, color="#5B7FB5",
                     label="Valores calculados (Dt del hietograma)")
        self.ax.axvline(tp, linestyle=":", color="#B3261E", linewidth=1)
        self.ax.annotate(f"Qp = {qp:.1f} m³/s", (tp, qp), textcoords="offset points",
                          xytext=(8, 10), fontsize=9, color="#B3261E",
                          bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.75))
        self.ax.set_xlabel("Tiempo (h)")
        self.ax.set_ylabel("Caudal (m³/s)")
        self.ax.set_title(f"Hidrograma de crecida - método {metodo}", pad=12)
        # Margen superior extra para que la etiqueta de Qp (que suele caer
        # cerca del punto más alto de la curva) nunca choque con el título.
        self.ax.set_ylim(0, max(q_fino.max(), caudal_m3s.max()) * 1.18)
        self.ax.grid(True, linestyle=":", linewidth=0.5)
        self.ax.legend(fontsize=8, loc="upper right")
        self.fig.tight_layout()
        self.draw()

    # Paleta por familia de métodos, para que en el gráfico comparativo se
    # distinga de un vistazo de qué tipo es cada barra (ver plot_comparacion_metodos).
    COLORES_FAMILIA = {
        "Lluvia-escorrentía": "#1F3864",
        "Directo": "#2E7D32",
        "Envolvente": "#B3261E",
        "Escuela regional": "#8B5CF6",
        "Complementario": "#EF9F27",
        "Aforo indirecto": "#0E7490",
    }

    def plot_hietograma(self, hietograma_mm, dt_h, descripcion=""):
        """
        Hietograma de diseño en barras, con la lamina acumulada en un eje
        secundario y el intervalo del pico resaltado.

        Se muestra JUNTO a los valores numericos porque una lista de
        incrementos no deja ver la forma de la tormenta -- y la forma es
        justamente lo que distingue un patron SCS Tipo II de un Tipo IA
        con la misma lamina total, y lo que determina el caudal punta.
        """
        self.fig.clear()
        self.ax = self.fig.add_subplot(111)
        n = len(hietograma_mm)
        if n == 0:
            self.draw()
            return
        tiempos = [i * dt_h for i in range(n)]
        idx_pico = max(range(n), key=lambda i: hietograma_mm[i])
        colores = ["#B3261E" if i == idx_pico else "#1F3864" for i in range(n)]

        self.ax.bar(tiempos, hietograma_mm, width=dt_h * 0.9, align="edge",
                    color=colores, label="Incremento de lluvia")
        self.ax.set_xlabel("Tiempo (h)")
        self.ax.set_ylabel("Lluvia por intervalo (mm)")
        self.ax.invert_yaxis()   # convencion hidrologica: la lluvia cae desde arriba
        self.ax.grid(True, axis="y", linestyle=":", linewidth=0.5)

        acumulada, suma = [], 0.0
        for v in hietograma_mm:
            suma += v
            acumulada.append(suma)
        ax2 = self.ax.twinx()
        ax2.plot([t + dt_h for t in tiempos], acumulada, "-o", markersize=3,
                 linewidth=1.8, color="#2E7D32", label="Lámina acumulada")
        ax2.set_ylabel("Lámina acumulada (mm)", color="#2E7D32")
        ax2.tick_params(axis="y", labelcolor="#2E7D32")

        self.ax.annotate(
            f"pico {hietograma_mm[idx_pico]:.2f} mm\nen t = {tiempos[idx_pico]:.2f} h",
            xy=(tiempos[idx_pico] + dt_h / 2, hietograma_mm[idx_pico]),
            textcoords="offset points", xytext=(10, 14), fontsize=8.5, color="#B3261E",
            bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#B3261E", alpha=0.9))

        l1, e1 = self.ax.get_legend_handles_labels()
        l2, e2 = ax2.get_legend_handles_labels()
        self.ax.legend(l1 + l2, e1 + e2, loc="lower right")
        titulo = f"Hietograma de diseño — total {suma:.1f} mm en {n} intervalos de {dt_h} h"
        if descripcion:
            titulo += f"\n{descripcion}"
        self.ax.set_title(titulo, pad=12)
        self.fig.tight_layout()
        self.draw()

    def plot_separacion_flujo_base(self, caudal_total, flujo_base, escorrentia_directa,
                                     metodo, bfi, etiqueta_x="Paso de tiempo"):
        """
        Hidrograma observado con el flujo base separado de la escorrentía
        directa, en áreas apiladas: la franja inferior es el flujo base y
        la superior la escorrentía directa, de modo que la altura total
        es siempre el caudal observado.
        """
        self.fig.clear()
        self.ax = self.fig.add_subplot(111)
        x = list(range(len(caudal_total)))

        self.ax.fill_between(x, 0, flujo_base, color="#2E7D32", alpha=0.55, label="Flujo base")
        self.ax.fill_between(x, flujo_base, caudal_total, color="#1F3864", alpha=0.40,
                              label="Escorrentía directa")
        self.ax.plot(x, caudal_total, linewidth=1.8, color="#0D2440", label="Caudal observado total")
        self.ax.plot(x, flujo_base, linewidth=1.6, color="#1B5E20")

        self.ax.set_xlabel(etiqueta_x)
        self.ax.set_ylabel("Caudal (m³/s)")
        self.ax.set_title(f"Separación de flujo base — {metodo}   (BFI = {bfi:.3f})", pad=12)
        self.ax.set_ylim(0, max(caudal_total) * 1.15 if caudal_total else 1)
        self.ax.grid(True, linestyle=":", linewidth=0.5)
        self.ax.legend(fontsize=8, loc="upper right")
        self.fig.tight_layout()
        self.draw()

    def plot_transito(self, tiempos_h, caudal_entrada, caudal_salida, metodo,
                       qp_entrada, qp_salida, atenuacion_pct, retardo_h,
                       almacenamiento_m3=None):
        """
        Hidrograma de ENTRADA vs. SALIDA de un tránsito de avenidas, con
        la atenuación del pico y el retardo anotados. Si se pasa el
        almacenamiento (tránsito en vaso por Puls), se dibuja en un eje
        secundario para ver cómo el embalse se llena y se vacía.
        """
        self.fig.clear()
        self.ax = self.fig.add_subplot(111)

        n = min(len(tiempos_h), len(caudal_entrada), len(caudal_salida))
        t = list(tiempos_h[:n])
        qe = list(caudal_entrada[:n])
        qs = list(caudal_salida[:n])

        self.ax.plot(t, qe, linewidth=2.0, color="#B3261E", label="Entrada al tramo")
        self.ax.plot(t, qs, linewidth=2.0, color="#1F3864", label="Salida (transitado)")
        # El área entre ambas curvas es, visualmente, la atenuación.
        self.ax.fill_between(t, qs, qe, where=[a >= b for a, b in zip(qe, qs)],
                              alpha=0.15, color="#B3261E", interpolate=True)
        self.ax.fill_between(t, qs, alpha=0.10, color="#1F3864")

        idx_e = qe.index(max(qe))
        idx_s = qs.index(max(qs))
        self.ax.plot([t[idx_e]], [qe[idx_e]], "o", color="#B3261E", markersize=5)
        self.ax.plot([t[idx_s]], [qs[idx_s]], "o", color="#1F3864", markersize=5)
        self.ax.annotate(
            f"Atenuación: {atenuacion_pct:.1f}%\nRetardo: {retardo_h:.2f} h\n"
            f"{qp_entrada:.1f} → {qp_salida:.1f} m³/s",
            xy=(t[idx_s], qs[idx_s]), textcoords="offset points", xytext=(14, -6), fontsize=8.5,
            bbox=dict(boxstyle="round,pad=0.35", fc="white", ec="#999999", alpha=0.88),
        )

        self.ax.set_xlabel("Tiempo (h)")
        self.ax.set_ylabel("Caudal (m³/s)")
        self.ax.set_ylim(0, max(max(qe), max(qs)) * 1.22)
        self.ax.grid(True, linestyle=":", linewidth=0.5)
        self.ax.set_title(f"Tránsito de avenida — {metodo}", pad=12)

        if almacenamiento_m3:
            almacenado = list(almacenamiento_m3[:n])
            ax2 = self.ax.twinx()
            ax2.plot(t[:len(almacenado)], [s / 1e6 for s in almacenado],
                     linestyle="--", linewidth=1.4, color="#2E7D32", label="Almacenamiento")
            ax2.set_ylabel("Almacenamiento (hm³)", color="#2E7D32")
            ax2.tick_params(axis="y", labelcolor="#2E7D32")
            ax2.set_ylim(0, max(almacenado) / 1e6 * 1.25 if max(almacenado) > 0 else 1)
            lineas1, etiquetas1 = self.ax.get_legend_handles_labels()
            lineas2, etiquetas2 = ax2.get_legend_handles_labels()
            self.ax.legend(lineas1 + lineas2, etiquetas1 + etiquetas2, fontsize=8, loc="upper right")
        else:
            self.ax.legend(fontsize=8.5, loc="upper right")

        self.fig.tight_layout()
        self.draw()

    def plot_comparacion_metodos(self, nombres, valores, titulo="Comparación de métodos de caudal máximo",
                                  familias=None, umbral_horizontal=9):
        """Gráfico de barras comparando el Qp obtenido por distintos
        métodos (SCS/Snyder/Clark, Témez, Creager, envolventes, ...).

        Con pocos métodos usa barras VERTICALES (lectura clásica, con la
        etiqueta de valor sobre cada barra). A partir de `umbral_horizontal`
        métodos cambia automáticamente a barras HORIZONTALES ordenadas de
        mayor a menor: con ~30 métodos las etiquetas del eje X en vertical
        se solapan y se vuelven ilegibles, mientras que en horizontal cada
        nombre tiene su propia línea y la comparación de magnitudes es
        inmediata.

        `familias` (opcional): lista paralela a `nombres` con la familia de
        cada método (ver COLORES_FAMILIA), para colorear las barras por tipo
        y agregar una leyenda -- así el orden por magnitud no hace perder la
        información de a qué grupo pertenece cada método.
        """
        self.fig.clear()
        self.ax = self.fig.add_subplot(111)
        if not nombres:
            self.draw()
            return

        if familias and len(familias) == len(nombres):
            colores = [self.COLORES_FAMILIA.get(f, "#666666") for f in familias]
        else:
            paleta = ["#1F3864", "#2E7D32", "#B3261E", "#8B5CF6", "#EF9F27"]
            colores = [paleta[i % len(paleta)] for i in range(len(nombres))]
            familias = None

        if len(nombres) < umbral_horizontal:
            barras = self.ax.bar(nombres, valores, color=colores)
            self.ax.bar_label(barras, fmt="%.1f", padding=4, fontsize=9)
            # Margen superior extra (20%) para que las etiquetas de las
            # barras más altas queden dentro del área de trazado y no
            # choquen con el título.
            self.ax.set_ylim(0, (max(valores) if valores else 1) * 1.2)
            self.ax.set_ylabel("Caudal Qp (m³/s)")
            self.ax.tick_params(axis="x", rotation=15)
            self.ax.grid(True, axis="y", linestyle=":", linewidth=0.5)
        else:
            # Ordenado de mayor a menor y dibujado de abajo hacia arriba,
            # para que el método de mayor caudal quede arriba del todo.
            orden = sorted(range(len(valores)), key=lambda i: valores[i])
            nombres_ord = [nombres[i] for i in orden]
            valores_ord = [valores[i] for i in orden]
            colores_ord = [colores[i] for i in orden]
            posiciones = range(len(nombres_ord))
            barras = self.ax.barh(list(posiciones), valores_ord, color=colores_ord)
            self.ax.set_yticks(list(posiciones))
            self.ax.set_yticklabels(nombres_ord, fontsize=8)
            self.ax.bar_label(barras, fmt="%.1f", padding=3, fontsize=7.5)
            self.ax.set_xlim(0, (max(valores) if valores else 1) * 1.18)
            self.ax.set_xlabel("Caudal Qp (m³/s)")
            self.ax.grid(True, axis="x", linestyle=":", linewidth=0.5)
            # Con muchos métodos la figura por defecto queda apretada:
            # se le da ~0.30 pulgadas de alto por método (mínimo el alto
            # original) para que las etiquetas nunca se solapen.
            alto_necesario = max(self.fig.get_figheight(), 1.6 + 0.30 * len(nombres_ord))
            self.fig.set_figheight(alto_necesario)
            self.setMinimumHeight(int(alto_necesario * self.fig.dpi))

        if familias:
            from matplotlib.patches import Patch
            vistas = []
            for f in familias:
                if f not in vistas:
                    vistas.append(f)
            self.ax.legend(
                handles=[Patch(facecolor=self.COLORES_FAMILIA.get(f, "#666666"), label=f) for f in vistas],
                fontsize=7.5, loc="lower right", framealpha=0.9,
            )

        self.ax.set_title(titulo, pad=14)
        self.fig.tight_layout()
        self.draw()
