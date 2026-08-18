import sys
import types


def _inject_dummy_qgis():
    """Inyecta módulos mínimos de `qgis` en sys.modules para permitir importar
    `hydroandes_sym_bim.plugin_dialog` en entornos de test sin QGIS.
    """
    qgis = types.ModuleType("qgis")
    core = types.ModuleType("qgis.core")
    gui = types.ModuleType("qgis.gui")
    PyQt = types.ModuleType("qgis.PyQt")
    QtCore = types.ModuleType("qgis.PyQt.QtCore")
    QtGui = types.ModuleType("qgis.PyQt.QtGui")
    QtWidgets = types.ModuleType("qgis.PyQt.QtWidgets")

    # atributos usados en imports del módulo real (no necesitan implementación)
    for name in [
        "QgsProject", "QgsMapLayerProxyModel", "QgsCoordinateReferenceSystem",
        "QgsCoordinateTransform", "QgsPointXY", "QgsGeometry", "QgsWkbTypes",
        "QgsProcessingContext", "QgsProcessingFeedback", "QgsRasterLayer",
        "QgsVectorLayer", "QgsApplication", "Qgis", "QgsMessageLog",
    ]:
        setattr(core, name, object)

    for name in ["QgsMapLayerComboBox", "QgsMapToolEmitPoint"]:
        setattr(gui, name, object)

    class DummyQt:
        WindowMinimizeButtonHint = 0
        WindowMaximizeButtonHint = 0
        WindowSystemMenuHint = 0

    QtCore.Qt = DummyQt
    QtGui.QFont = object

    for name in [
        "QDialog", "QTabWidget", "QVBoxLayout", "QHBoxLayout", "QFormLayout",
        "QGroupBox", "QLabel", "QLineEdit", "QPushButton", "QSpinBox",
        "QDoubleSpinBox", "QComboBox", "QTableWidget", "QTableWidgetItem",
        "QFileDialog", "QMessageBox", "QRadioButton", "QButtonGroup",
        "QCheckBox", "QWidget", "QHeaderView", "QPlainTextEdit",
        "QTextBrowser", "QApplication", "QScrollArea", "QStackedWidget",
        "QFrame", "QGridLayout",
    ]:
        setattr(QtWidgets, name, type(name, (), {}))

    PyQt.QtCore = QtCore
    PyQt.QtGui = QtGui
    PyQt.QtWidgets = QtWidgets

    sys.modules.setdefault('qgis', qgis)
    sys.modules.setdefault('qgis.core', core)
    sys.modules.setdefault('qgis.gui', gui)
    sys.modules.setdefault('qgis.PyQt', PyQt)
    sys.modules.setdefault('qgis.PyQt.QtCore', QtCore)
    sys.modules.setdefault('qgis.PyQt.QtGui', QtGui)
    sys.modules.setdefault('qgis.PyQt.QtWidgets', QtWidgets)


def test_utm_epsg_for_lonlat_basic():
    _inject_dummy_qgis()
    from hydroandes_sym_bim.plugin_dialog import utm_epsg_for_lonlat

    # Zona esperada para Perú central/occidental
    assert utm_epsg_for_lonlat(-75.0, -10.0) == 32717
    assert utm_epsg_for_lonlat(-70.0, -12.0) == 32718
    assert utm_epsg_for_lonlat(-81.0,  -9.0) == 32716


def test_utm_epsg_for_lonlat_edges():
    _inject_dummy_qgis()
    from hydroandes_sym_bim.plugin_dialog import utm_epsg_for_lonlat

    # Valores extremos y límites de zona
    assert utm_epsg_for_lonlat(179.9, 0.0) == 32760
    assert utm_epsg_for_lonlat(-180.0, 0.0) == 32701
