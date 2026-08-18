# -*- coding: utf-8 -*-
"""
HydroAndes Sym BIM - clase principal del plugin.
Responsable únicamente del ciclo de vida QGIS (registro de menú/toolbar
y apertura del diálogo). Toda la lógica de negocio vive en core/ y toda
la interfaz en plugin_dialog.py.
"""
import os
from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtGui import QIcon


class HydroAndesSymBimPlugin:

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions = []
        self.menu = "&HydroAndes Sym BIM"
        self.dialog = None

    def initGui(self):
        icon_path = os.path.join(self.plugin_dir, "icon.png")
        action = QAction(QIcon(icon_path), "HydroAndes Sym BIM - Análisis Hidrológico", self.iface.mainWindow())
        action.triggered.connect(self.run)
        self.iface.addPluginToMenu(self.menu, action)
        self.iface.addToolBarIcon(action)
        self.actions.append(action)

    def unload(self):
        for action in self.actions:
            self.iface.removePluginMenu(self.menu, action)
            self.iface.removeToolBarIcon(action)
        if self.dialog is not None:
            self.dialog.close()
            self.dialog = None

    def run(self):
        # Import diferido: evita cargar PyQt/matplotlib hasta que el
        # usuario realmente abre el plugin (arranque de QGIS más rápido).
        from .plugin_dialog import HydroAndesSymBimDialog
        self._mostrar_splash_si_es_posible()
        if self.dialog is None:
            self.dialog = HydroAndesSymBimDialog(self.iface)
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def _mostrar_splash_si_es_posible(self):
        """Pantalla de introducción (reproduce resources/splash.gif vía
        QMovie, con resources/splash_audio.wav de fondo si QtMultimedia
        está disponible, y se cierra sola al terminar). Es puramente
        cosmética: cualquier error aquí se ignora en silencio (el plugin
        continúa abriendo el diálogo principal con normalidad — un
        splash roto nunca debe impedir usar el plugin), pero SÍ se deja
        registrado en el panel "Registro de mensajes" de QGIS (categoría
        "HydroAndes Sym BIM") para poder diagnosticar sin adivinar si algo
        no funciona."""
        from qgis.core import Qgis, QgsMessageLog
        try:
            from .ui.splash_intro import SplashIntroVideo
            ruta_gif = os.path.join(self.plugin_dir, "resources", "splash.gif")
            ruta_audio = os.path.join(self.plugin_dir, "resources", "splash_audio.wav")
            if not os.path.exists(ruta_gif):
                QgsMessageLog.logMessage(
                    f"No se encontró el GIF del splash en: {ruta_gif}",
                    "HydroAndes Sym BIM", level=Qgis.Warning
                )
                return

            splash = SplashIntroVideo(ruta_gif, ruta_audio if os.path.exists(ruta_audio) else None,
                                       parent=self.iface.mainWindow())
            try:
                splash.exec_()
            except AttributeError:
                splash.exec()  # PyQt6/Qt6 (QGIS 4.0+): exec_ puede no existir
        except Exception as e:
            QgsMessageLog.logMessage(
                f"El splash de introducción no pudo mostrarse (se omite y se abre el plugin "
                f"normalmente): {type(e).__name__}: {e}",
                "HydroAndes Sym BIM", level=Qgis.Warning
            )
