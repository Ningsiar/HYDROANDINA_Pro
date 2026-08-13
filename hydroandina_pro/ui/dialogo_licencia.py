# -*- coding: utf-8 -*-
"""
ui/dialogo_licencia.py

Diálogo que se muestra en dos casos:
  1. Se agotaron los 10 usos gratuitos -- BLOQUEA el acceso al plugin
     (plugin.py no construye HydroAndinaProDialog mientras este diálogo
     esté abierto y no se haya activado una licencia válida).
  2. El usuario quiere activar su licencia antes de agotar el límite
     (mismo diálogo, mismo flujo, solo cambia el texto introductorio).

Deliberadamente NO valida la clave aquí: la envía tal cual al backend
(core/licencia.py::activar_licencia) y actúa sobre la respuesta -- el
plugin nunca conoce el secreto con el que se generan las claves válidas.
"""
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QMessageBox,
)

from ..core import licencia

# Contacto que se muestra al usuario para comprar/renovar la licencia --
# AJUSTAR antes de distribuir el plugin.
CONTACTO_LICENCIA = "ningsiar.lima@unsaac.edu.pe"


class DialogoLicenciaAgotada(QDialog):

    def __init__(self, estado: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("HydroAndina Pro — Licencia")
        self.setMinimumWidth(440)
        self._licencia_activada = bool(estado.get("licencia_activada", False))

        v = QVBoxLayout(self)

        if estado.get("bloqueado"):
            titulo = "Se agotaron los usos gratuitos de HydroAndina Pro"
            cuerpo = (
                f"Este plugin incluye {estado.get('limite', licencia.LIMITE_USOS_GRATIS)} usos "
                f"gratuitos. Ya se registraron {estado.get('usos', '?')}.<br><br>"
                f"Para seguir usándolo, ingrese su clave de licencia abajo, o escriba a "
                f"<b>{CONTACTO_LICENCIA}</b> para adquirir una."
            )
        else:
            titulo = "Activar licencia de HydroAndina Pro"
            cuerpo = (
                f"Usos registrados: {estado.get('usos', '?')} de "
                f"{estado.get('limite', licencia.LIMITE_USOS_GRATIS)} gratuitos.<br><br>"
                f"Si ya tiene una clave de licencia, ingrésela abajo. Si no, puede seguir usando "
                f"el plugin hasta agotar los usos gratuitos, o escribir a "
                f"<b>{CONTACTO_LICENCIA}</b> para adquirir una."
            )

        lbl_titulo = QLabel(f"<h3>{titulo}</h3>")
        lbl_titulo.setWordWrap(True)
        v.addWidget(lbl_titulo)
        lbl_cuerpo = QLabel(cuerpo)
        lbl_cuerpo.setWordWrap(True)
        lbl_cuerpo.setTextFormat(Qt.RichText)
        v.addWidget(lbl_cuerpo)

        if estado.get("origen") == "local":
            lbl_offline = QLabel(
                "<i>No se pudo contactar al servidor de licencias -- se está usando el registro "
                "local. Conecte a internet para sincronizar.</i>")
            lbl_offline.setWordWrap(True)
            lbl_offline.setStyleSheet("color: #8a5a00;")
            v.addWidget(lbl_offline)

        h_clave = QHBoxLayout()
        h_clave.addWidget(QLabel("Clave de licencia:"))
        self.edit_clave = QLineEdit()
        self.edit_clave.setPlaceholderText("XXXX-XXXX-XXXX-XXXX")
        h_clave.addWidget(self.edit_clave)
        v.addLayout(h_clave)

        self.lbl_estado_activacion = QLabel("")
        self.lbl_estado_activacion.setWordWrap(True)
        v.addWidget(self.lbl_estado_activacion)

        h_botones = QHBoxLayout()
        self.btn_activar = QPushButton("Activar")
        self.btn_activar.clicked.connect(self._on_activar)
        h_botones.addWidget(self.btn_activar)
        h_botones.addStretch()
        self.btn_cerrar = QPushButton("Cerrar" if estado.get("bloqueado") else "Continuar sin activar")
        self.btn_cerrar.clicked.connect(self.reject)
        h_botones.addWidget(self.btn_cerrar)
        v.addLayout(h_botones)

    def licencia_quedo_activada(self) -> bool:
        return self._licencia_activada

    def _on_activar(self):
        clave = self.edit_clave.text().strip()
        if not clave:
            self.lbl_estado_activacion.setText("Ingrese una clave antes de activar.")
            return
        self.btn_activar.setEnabled(False)
        try:
            resultado = licencia.activar_licencia(clave)
        except licencia.LicenciaError as e:
            self.lbl_estado_activacion.setText(f"⚠ {e}")
            self.btn_activar.setEnabled(True)
            return
        finally:
            self.btn_activar.setEnabled(True)

        if resultado.get("ok") and resultado.get("licencia_activada"):
            self._licencia_activada = True
            QMessageBox.information(self, "Licencia activada",
                                     "Licencia activada correctamente. Gracias por su compra.")
            self.accept()
        else:
            self.lbl_estado_activacion.setText(
                f"⚠ {resultado.get('mensaje') or 'Clave inválida para esta instalación.'}")
