# -*- coding: utf-8 -*-
"""
ui/swe2d_animation.py

Arma una animación GIF de la evolución del calado a partir de los
instantes capturados durante la simulación 2D (ver
ui/swe2d_runner.py::SimulacionSwe2DWorker._capturar, y el
"Intervalo de captura para la animación" de la Pestaña 8), reutilizando
el mismo MapaCalado2DCanvas de los resultados estáticos -- un frame por
instante, mismo fondo/leyenda que el mapa de calados máximos, para que
la animación se lea igual que el resto de resultados.

Se eligió GIF (reproducible con QMovie, parte de Qt, sin dependencias ni
codecs adicionales) en vez de MP4/WebM: un video real necesitaría
ffmpeg instalado aparte, que no viene con QGIS y no se puede dar por
garantizado en el equipo del usuario. Pillow (PIL), en cambio, se
importa de forma perezosa -- igual que python-docx/openpyxl/docxtpl en
el resto del plugin -- y basta para ensamblar el GIF.
"""
import io

from .swe2d_canvas import MapaCalado2DCanvas


class AnimacionSwe2DError(Exception):
    pass


def _requerir_pillow():
    try:
        from PIL import Image
        return Image
    except ImportError as e:
        raise AnimacionSwe2DError(
            "Pillow no está instalado en el intérprete de Python de QGIS. Ejecute "
            "'pip install Pillow' desde el OSGeo4W Shell (Windows) o el terminal con el "
            "Python de QGIS (Linux/Mac), y vuelva a intentar."
        ) from e


def generar_gif_calado(instantes, simulador, ruta_gif: str, paso: int = 1,
                        duracion_frame_ms: int = 200, dpi: int = 90) -> dict:
    """
    instantes: lista de (t, h, vx, vy) -- SimulacionSwe2DWorker.instantes,
        disponible tras ejecutar la simulación con intervalo de captura
        mayor que 0.
    simulador: el SimuladorSwe2D ya terminado (zb, dx, dy, activo,
        entradas, estructuras -- el mismo fondo del mapa de máximos).
    paso: usar 1 de cada `paso` instantes capturados, para acortar el GIF
        sin tener que volver a simular con un intervalo de captura mayor.
        El instante FINAL siempre se incluye, caiga o no en el paso.
    duracion_frame_ms: milisegundos que se muestra cada cuadro.
    dpi: resolución de cada cuadro -- deliberadamente baja: un GIF de
        calidad de impresión pesaría varios MB por cuadro sin aportar
        nada a la escala en la que se ve dentro del plugin.

    Devuelve {'ruta', 'n_frames', 'duracion_total_s'}.
    """
    if not instantes:
        raise AnimacionSwe2DError(
            "No hay instantes capturados. Active la captura (intervalo mayor que 0, sección 5 "
            "de la pestaña) y vuelva a ejecutar la simulación antes de generar la animación.")
    Image = _requerir_pillow()

    paso = max(int(paso), 1)
    seleccionados = list(instantes[::paso])
    if seleccionados[-1] is not instantes[-1]:
        seleccionados.append(instantes[-1])

    canvas = MapaCalado2DCanvas(width=7.6, height=5.6, dpi=dpi)
    frames = []
    for t, h, _vx, _vy in seleccionados:
        canvas.plot_mapa(h, simulador.zb, simulador.dx, simulador.dy,
                          activo=simulador.activo, entradas=simulador.entradas,
                          estructuras=simulador.estructuras,
                          titulo=f"t = {t:,.0f} s", etiqueta_barra="Calado (m)")
        buffer = io.BytesIO()
        canvas.fig.savefig(buffer, format="png", dpi=dpi, bbox_inches="tight")
        buffer.seek(0)
        frames.append(Image.open(buffer).convert("RGB"))
        buffer.close()

    frames[0].save(
        ruta_gif, format="GIF", save_all=True, append_images=frames[1:],
        duration=duracion_frame_ms, loop=0, optimize=True,
    )
    return {
        "ruta": ruta_gif,
        "n_frames": len(frames),
        "duracion_total_s": len(frames) * duracion_frame_ms / 1000.0,
    }
