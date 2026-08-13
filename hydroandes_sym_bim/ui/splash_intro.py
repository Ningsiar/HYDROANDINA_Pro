# -*- coding: utf-8 -*-
"""
ui/splash_intro.py

Pantalla de introducción que se muestra al abrir el plugin: reproduce
una animación GIF de portada (resources/splash.gif) mediante QMovie, y
opcionalmente el audio del video original (resources/splash_audio.*)
mediante QSoundEffect. Al terminar la animación, cierra automáticamente
para dar paso al diálogo principal.

POR QUÉ SE CAMBIÓ DE QMediaPlayer/QVideoWidget A QMovie (v0.2.16):
La versión anterior reproducía el video (.mp4) con QMediaPlayer +
QVideoWidget (módulo QtMultimedia/QtMultimediaWidgets). Ese enfoque
depende de que la build de Qt de QGIS incluya el módulo QtMultimedia Y
sus backends de códecs de video (FFmpeg/WMF/GStreamer según la
plataforma) — algo que NO todas las instalaciones de QGIS traen
incluido (es habitual que falte justamente en instalaciones Windows/
OSGeo4W, ya que QGIS en sí no necesita reproducir video). Si ese
backend falta, QMediaPlayer no reproduce nada visible y no siempre
emite un error claro, lo que explica que el video simplemente no se
viera pese a que el código en sí no fallaba.

QMovie, en cambio, es parte de QtGui (no de QtMultimedia): decodifica
el GIF por sí mismo, sin necesitar ningún backend/códec externo, así
que funciona en cualquier instalación de Qt sin excepción. El audio
(que si depende de QtMultimedia) se mantiene como algo "best-effort":
si no está disponible, la animación igual se reproduce, solo que sin
sonido — la parte visual (lo más importante) queda garantizada.

IMPORTANTE — ESTO ES PURAMENTE COSMÉTICO: quien llame a este módulo
(ver plugin.py) debe envolver su uso en un try/except amplio. Un splash
roto nunca debe impedir usar el plugin.

DIAGNÓSTICO: cualquier problema se registra en el panel "Registro de
mensajes" de QGIS, categoría "HydroAndes SYM BIM".
"""
import os

from qgis.core import Qgis, QgsMessageLog
from qgis.PyQt.QtCore import Qt, QUrl, QTimer, QSize
from qgis.PyQt.QtGui import QMovie
from qgis.PyQt.QtWidgets import QDialog, QLabel, QVBoxLayout

DURACION_MAXIMA_MS = 20000  # límite de seguridad por si el GIF no reporta su fin
CATEGORIA_LOG = "HydroAndes SYM BIM"


def _log(mensaje, nivel=Qgis.Info):
    try:
        QgsMessageLog.logMessage(mensaje, CATEGORIA_LOG, level=nivel)
    except Exception:
        pass


class SplashIntroVideo(QDialog):
    """Splash que reproduce resources/splash.gif (vía QMovie) y,
    opcionalmente, resources/splash_audio.wav (vía QSoundEffect, si
    QtMultimedia está disponible). Se cierra solo al terminar la
    animación, o antes si el usuario hace clic/pulsa una tecla."""

    def __init__(self, ruta_gif: str, ruta_audio: str = None, parent=None):
        super().__init__(parent, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setModal(True)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setCursor(Qt.PointingHandCursor)

        self._label = QLabel(self)
        self._label.setAlignment(Qt.AlignCenter)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._label)

        self._movie = QMovie(ruta_gif)
        if not self._movie.isValid():
            raise RuntimeError(f"No se pudo cargar/decodificar el GIF del splash: {ruta_gif}")
        self._label.setMovie(self._movie)

        tamano = self._movie.currentImage().size()
        if tamano.isEmpty():
            tamano = QSize(960, 540)
        # El GIF ya se genera a la resolución nativa del video (960x540),
        # así que se muestra a su tamaño real, sin reescalar.
        self._movie.setScaledSize(tamano)
        self.setFixedSize(tamano)

        self._movie.finished.connect(self.close)
        self._movie.frameChanged.connect(self._on_frame_changed)
        self._ultimo_frame = self._movie.frameCount() - 1

        self._reproductor_audio = self._intentar_reproducir_audio(ruta_audio) if ruta_audio else None

        self._movie.start()
        _log(f"Splash (QMovie) iniciado con: {ruta_gif}")

        QTimer.singleShot(DURACION_MAXIMA_MS, self.close)

    def _on_frame_changed(self, numero_frame):
        # Algunos formatios/backends de QMovie hacen loop del GIF en vez
        # de emitir 'finished'; se cierra manualmente al llegar al último
        # frame, como respaldo.
        if self._ultimo_frame > 0 and numero_frame >= self._ultimo_frame:
            self.close()

    def _intentar_reproducir_audio(self, ruta_audio: str):
        if not ruta_audio or not os.path.exists(ruta_audio):
            return None
        try:
            from qgis.PyQt.QtMultimedia import QSoundEffect
            efecto = QSoundEffect(self)
            efecto.setSource(QUrl.fromLocalFile(ruta_audio))
            efecto.setVolume(1.0)
            efecto.play()
            _log("Audio del splash reproducido vía QSoundEffect.")
            return efecto
        except Exception as e:
            _log(f"No se pudo reproducir el audio del splash (se omite, la animación sigue igual): {e}",
                 Qgis.Warning)
            return None

    def closeEvent(self, event):
        try:
            self._movie.stop()
        except Exception:
            pass
        try:
            if self._reproductor_audio is not None:
                self._reproductor_audio.stop()
        except Exception:
            pass
        super().closeEvent(event)

    def mousePressEvent(self, event):
        self.close()

    def keyPressEvent(self, event):
        self.close()
