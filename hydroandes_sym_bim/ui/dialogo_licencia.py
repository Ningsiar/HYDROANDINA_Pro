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

Diseño "de alto impacto": cabecera de marca, título destacado y una
tarjeta de contacto con fondo propio que resalta teléfono/correo/empresa
-- pensado para que un cliente que ve este diálogo entienda de un
vistazo qué pasó y a quién contactar, sin tener que leer un bloque de
texto plano.
"""
import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QFont, QPixmap
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QMessageBox, QFrame,
)

from ..core import licencia

# Contacto que se muestra al usuario para comprar/renovar la licencia.
CONTACTO_TELEFONO = "+51 984440128"
CONTACTO_EMAIL = "corporativoconstructivo@gmail.com"
EMPRESA_LICENCIA = "CORPORATIVO CONSTRUCTIVO LIMA BERLIN SRL"
EMPRESA_UBICACION = "Cusco - Perú"

# Icono de marca del plugin (el mismo que usa el menú Complementos de QGIS
# y la barra de herramientas -- ver plugin.py) y logo de la empresa (el
# isotipo real de CORPORATIVO CONSTRUCTIVO LIMA BERLIN SRL, provisto por
# el cliente). La carga es defensiva a propósito -- si algún día el
# archivo faltara o estuviera dañado, la tarjeta de contacto simplemente
# se muestra sin imagen, sin romper el diálogo.
_DIR_PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUTA_ICONO_PLUGIN = os.path.join(_DIR_PLUGIN, "icon.png")
RUTA_LOGO_EMPRESA = os.path.join(_DIR_PLUGIN, "resources", "logo_empresa.png")

_COLOR_MARCA = "#0b3d63"
_COLOR_TARJETA_FONDO = "#eef5fc"
_COLOR_TARJETA_BORDE = "#c3ddf2"
_COLOR_TARJETA_TEXTO_SECUNDARIO = "#3a5875"


def _pixmap_o_none(ruta: str, alto: int):
    """Carga un QPixmap escalado a `alto` px, o None si el archivo no
    existe o no es una imagen válida -- nunca lanza excepción."""
    if not ruta or not os.path.exists(ruta):
        return None
    try:
        pix = QPixmap(ruta)
    except Exception:
        return None
    if pix.isNull():
        return None
    return pix.scaledToHeight(alto, Qt.SmoothTransformation)


class DialogoLicenciaAgotada(QDialog):

    def __init__(self, estado: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("HydroAndes SYM BIM — Licencia")
        self.setMinimumWidth(560)
        self._licencia_activada = bool(estado.get("licencia_activada", False))
        bloqueado = bool(estado.get("bloqueado"))

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # ------------------------------------------------------------
        # Cabecera de marca (franja de color con el icono del plugin)
        # ------------------------------------------------------------
        cabecera = QFrame()
        cabecera.setStyleSheet(f"QFrame {{ background-color: {_COLOR_MARCA}; }}")
        h_cab = QHBoxLayout(cabecera)
        h_cab.setContentsMargins(24, 16, 24, 16)
        h_cab.setSpacing(12)

        pix_icono = _pixmap_o_none(RUTA_ICONO_PLUGIN, 40)
        if pix_icono is not None:
            lbl_icono = QLabel()
            lbl_icono.setPixmap(pix_icono)
            h_cab.addWidget(lbl_icono)

        lbl_marca = QLabel("HydroAndes SYM BIM")
        f_marca = QFont()
        f_marca.setPointSize(14)
        f_marca.setBold(True)
        lbl_marca.setFont(f_marca)
        lbl_marca.setStyleSheet("color: #ffffff;")
        h_cab.addWidget(lbl_marca)
        h_cab.addStretch()
        v.addWidget(cabecera)

        # ------------------------------------------------------------
        # Cuerpo (con márgenes normales)
        # ------------------------------------------------------------
        cuerpo = QFrame()
        vc = QVBoxLayout(cuerpo)
        vc.setContentsMargins(24, 20, 24, 20)
        vc.setSpacing(12)

        titulo = "La fase de prueba gratuita se agotó" if bloqueado else "Activar licencia"
        lbl_titulo = QLabel(titulo)
        f_titulo = QFont()
        f_titulo.setPointSize(13)
        f_titulo.setBold(True)
        lbl_titulo.setFont(f_titulo)
        lbl_titulo.setWordWrap(True)
        lbl_titulo.setStyleSheet(f"color: {_COLOR_MARCA};")
        vc.addWidget(lbl_titulo)

        if bloqueado:
            texto_uso = (
                f"Este plugin incluye {estado.get('limite', licencia.LIMITE_USOS_GRATIS)} usos "
                f"gratuitos y ya se registraron {estado.get('usos', '?')}."
            )
            texto_intro_contacto = "Si desea una licencia permanente por el software, contáctenos:"
        else:
            texto_uso = (
                f"Usos registrados: {estado.get('usos', '?')} de "
                f"{estado.get('limite', licencia.LIMITE_USOS_GRATIS)} gratuitos."
            )
            texto_intro_contacto = (
                "Si ya tiene una clave de licencia, ingrésela abajo. Si desea adquirir una "
                "licencia permanente, contáctenos:"
            )

        lbl_uso = QLabel(texto_uso)
        lbl_uso.setWordWrap(True)
        vc.addWidget(lbl_uso)

        lbl_intro_contacto = QLabel(texto_intro_contacto)
        lbl_intro_contacto.setWordWrap(True)
        vc.addWidget(lbl_intro_contacto)

        # ------------------------------------------------------------
        # Tarjeta de contacto -- alto impacto: fondo propio, logo (si
        # está disponible), teléfono y correo en negrita y más grandes.
        # ------------------------------------------------------------
        tarjeta = QFrame()
        tarjeta.setStyleSheet(
            f"QFrame {{ background-color: {_COLOR_TARJETA_FONDO}; "
            f"border: 1px solid {_COLOR_TARJETA_BORDE}; border-radius: 6px; }}")
        h_tarjeta = QHBoxLayout(tarjeta)
        h_tarjeta.setContentsMargins(16, 14, 16, 14)
        h_tarjeta.setSpacing(14)

        pix_logo = _pixmap_o_none(RUTA_LOGO_EMPRESA, 64)
        if pix_logo is not None:
            lbl_logo = QLabel()
            lbl_logo.setPixmap(pix_logo)
            lbl_logo.setAlignment(Qt.AlignTop)
            h_tarjeta.addWidget(lbl_logo)

        v_datos = QVBoxLayout()
        v_datos.setSpacing(4)
        f_dato = QFont()
        f_dato.setPointSize(11)
        f_dato.setBold(True)

        lbl_tel = QLabel(f"\U0001F4DE  {CONTACTO_TELEFONO}  (Perú)")
        lbl_tel.setFont(f_dato)
        lbl_tel.setStyleSheet(f"color: {_COLOR_MARCA};")
        v_datos.addWidget(lbl_tel)

        lbl_correo = QLabel(f"✉  {CONTACTO_EMAIL}")
        lbl_correo.setFont(f_dato)
        lbl_correo.setStyleSheet(f"color: {_COLOR_MARCA};")
        lbl_correo.setWordWrap(True)
        v_datos.addWidget(lbl_correo)

        lbl_empresa = QLabel(f"Desarrollado por {EMPRESA_LICENCIA} — {EMPRESA_UBICACION}")
        lbl_empresa.setWordWrap(True)
        lbl_empresa.setStyleSheet(f"color: {_COLOR_TARJETA_TEXTO_SECUNDARIO}; font-style: italic;")
        v_datos.addWidget(lbl_empresa)

        h_tarjeta.addLayout(v_datos, 1)
        vc.addWidget(tarjeta)

        if estado.get("origen") == "local":
            lbl_offline = QLabel(
                "⚠ No se pudo contactar al servidor de licencias -- se está usando el registro "
                "local. Conecte a internet para sincronizar.")
            lbl_offline.setWordWrap(True)
            lbl_offline.setStyleSheet("color: #8a5a00;")
            vc.addWidget(lbl_offline)

        linea = QFrame()
        linea.setFrameShape(QFrame.HLine)
        linea.setStyleSheet("color: #d5d5d5;")
        vc.addWidget(linea)

        lbl_clave_titulo = QLabel("¿Ya cuenta con una clave de licencia?")
        f_clave_titulo = QFont()
        f_clave_titulo.setBold(True)
        lbl_clave_titulo.setFont(f_clave_titulo)
        vc.addWidget(lbl_clave_titulo)

        h_clave = QHBoxLayout()
        h_clave.addWidget(QLabel("Clave:"))
        self.edit_clave = QLineEdit()
        self.edit_clave.setPlaceholderText("XXXX-XXXX-XXXX-XXXX")
        h_clave.addWidget(self.edit_clave)
        vc.addLayout(h_clave)

        self.lbl_estado_activacion = QLabel("")
        self.lbl_estado_activacion.setWordWrap(True)
        vc.addWidget(self.lbl_estado_activacion)

        h_botones = QHBoxLayout()
        self.btn_activar = QPushButton("Activar")
        self.btn_activar.setDefault(True)
        self.btn_activar.clicked.connect(self._on_activar)
        h_botones.addWidget(self.btn_activar)
        h_botones.addStretch()
        self.btn_cerrar = QPushButton("Cerrar" if bloqueado else "Continuar sin activar")
        self.btn_cerrar.clicked.connect(self.reject)
        h_botones.addWidget(self.btn_cerrar)
        vc.addLayout(h_botones)

        v.addWidget(cuerpo)

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
