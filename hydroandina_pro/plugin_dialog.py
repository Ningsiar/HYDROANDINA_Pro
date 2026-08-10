# -*- coding: utf-8 -*-
"""
plugin_dialog.py

Interfaz principal de HydroAndina Pro: QDialog con un QTabWidget de 4
pestañas, tal como lo especifica el encargo. Cada pestaña delega el
trabajo pesado a los módulos de core/; este archivo se limita a
recolectar inputs de los widgets, llamar al core, y volcar resultados
en tablas/gráficos.
"""
import os
import tempfile
import math

import numpy as np

from qgis.core import (
    QgsProject, QgsMapLayerProxyModel, QgsCoordinateReferenceSystem,
    QgsCoordinateTransform, QgsPointXY, QgsGeometry, QgsWkbTypes,
    QgsProcessingContext, QgsProcessingFeedback, QgsRasterLayer, QgsVectorLayer,
)
from qgis.gui import QgsMapLayerComboBox, QgsMapToolEmitPoint
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QFont
from qgis.PyQt.QtWidgets import (
    QDialog, QTabWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLabel, QLineEdit, QPushButton, QSpinBox, QDoubleSpinBox, QComboBox,
    QTableWidget, QTableWidgetItem, QFileDialog, QMessageBox, QRadioButton,
    QButtonGroup, QCheckBox, QWidget, QHeaderView, QPlainTextEdit, QTextBrowser,
    QApplication, QScrollArea, QStackedWidget,
)

from .core import (delineation, morphometry, curve_number, tc_methods, dem_download,
                    exporters, raster_stats, unit_hydrographs, frequency_analysis,
                    design_storm, precip_source, scs_storm_patterns, pour_point_snap,
                    main_channel, landcover_soils, dem_download_asf, hydraulic_structures,
                    cn_generator_bridge, report_generator, project_export,
                    quality_control, pmp_hershfield, direct_discharge_methods,
                    data_completion, areal_precipitation, water_yield, scour, soil_loss,
                    sediment_transport, debris_flow, climate_change, mean_flow_models, etp_methods,
                    low_flows, phabsim, groundwater_flow, well_hydraulics)
from .core.qgis_layer_utils import obtener_capa
from .ui.hypsometric_canvas import HypsometricCanvas
from .ui.hydrograph_canvas import HydrographCanvas
from .ui.frequency_canvas import FrequencyCanvas
from .ui.pasteable_table import TablaPegable
from .ui.cross_section_canvas import SeccionTransversalCanvas
from .ui.cav_canvas import CavCanvas
from .ui.qc_canvas import QcCanvas
from .ui.scour_canvas import ScourCanvas
from .ui.soil_loss_canvas import SoilLossCanvas
from .ui.sediment_canvas import SedimentCanvas
from .ui.debris_flow_canvas import DebrisFlowCanvas
from .ui.climate_canvas import ClimateCanvas
from .ui.mean_flow_canvas import MeanFlowCanvas
from .ui.low_flow_canvas import LowFlowCanvas
from .ui.phabsim_canvas import PhabsimCanvas
from .ui.groundwater_canvas import GroundwaterCanvas
from .ui.well_canvas import WellCanvas
from .ui.table_utils import (ajustar_alto_tabla, aplicar_columna_elastica, limitar_ancho_tabla,
                              limitar_ancho_boton)


def utm_epsg_for_lonlat(lon: float, lat: float) -> int:
    """Determina la zona UTM WGS84 (17S/18S/19S, Perú) a partir de la
    longitud del break point. Fórmula estándar de zona UTM; hemisferio
    sur asumido (coherente con el ámbito andino peruano del proyecto)."""
    zona = int((lon + 180) / 6) + 1
    return 32700 + zona  # EPSG 327xx = WGS84 / UTM zone xxS


# Nombre descriptivo de cada parámetro morfométrico, indexado por el
# símbolo abreviado que usan las funciones de core/morphometry.py. Se
# muestra en la columna "Parámetro" de la tabla de la Pestaña 2 (antes
# solo se repetía el símbolo abreviado en ambas columnas, corregido aquí).
NOMBRES_PARAMETROS_MORFOMETRIA = {
    # Grupo 1: básicos
    "A": "Área de la cuenca",
    "P": "Perímetro de la cuenca",
    "Lb": "Longitud axial (eje mayor del rectángulo envolvente mínimo)",
    "B": "Ancho medio de la cuenca (B = A / Lb)",
    "Zmax": "Elevación máxima",
    "Zmin": "Elevación mínima (en el punto de salida)",
    "Zmed": "Elevación media",
    "Z50": "Elevación mediana (percentil 50% de la curva hipsométrica)",
    "H": "Relieve total (H = Zmax − Zmin)",
    # Grupo 2: forma
    "Ff": "Factor de forma de Horton",
    "Re": "Razón de elongación de Schumm",
    "Rc": "Razón de circularidad de Miller",
    "Kc": "Coeficiente de compacidad de Gravelius",
    "Rf": "Razón de ajuste (longitud del cauce / perímetro)",
    "IS": "Índice de sinuosidad del cauce principal",
    "Sc": "Coeficiente de almacenamiento del cauce",
    "Af": "Factor de asimetría",
    # Grupo 3: cauce principal
    "Lc": "Longitud del cauce principal",
    "Zinicio": "Elevación de inicio del cauce (cabecera/naciente)",
    "Zfin": "Elevación de fin del cauce (punto de salida)",
    "Hc": "Desnivel del cauce principal",
    "Se": "Pendiente media del cauce (entre extremos)",
    "SLR": "Pendiente compensada — Regresión Lineal",
    "STS": "Pendiente compensada — Taylor-Schwartz",
    "Gc": "Gradiente del cauce principal",
    # Grupo 4: pendiente media de la cuenca
    "Scuenca_pct": "Pendiente media de la cuenca",
    "Scuenca_deg": "Pendiente media de la cuenca",
    # Grupo 5: red de drenaje
    "Lt": "Longitud total de la red de drenaje",
    "Dd": "Densidad de drenaje",
    "Fs": "Frecuencia de cauces",
    "Dt": "Textura de drenaje",
    "Id": "Intensidad de drenaje",
    "Lo": "Longitud de flujo superficial (overland flow)",
    "C": "Constante de mantenimiento del cauce",
    "If": "Número de infiltración",
    "Nu": "Número de corrientes",
    "Lm": "Longitud media de corrientes",
    "Omega": "Orden de la corriente (Strahler)",
    "Rb": "Razón de bifurcación (Strahler)",
    "Jd": "Densidad de uniones",
    # Grupo 6: relieve y riesgo
    "Rr": "Relieve relativo",
    "Rh": "Razón de relieve de Schumm",
    "Rn": "Número de rugosidad de Schumm",
    "Oc": "Coeficiente orográfico",
    "Im": "Índice de masividad de Richter",
    "Mel": "Número de rugosidad de Melton (riesgo de flujo de detritos)",
}

# Unidad de cada parámetro, para la columna "Unidad" de la tabla de la
# Pestaña 2 (antes ausente; los valores se mostraban sin unidad).
UNIDADES_PARAMETROS_MORFOMETRIA = {
    "A": "km²", "P": "km", "Lb": "km", "B": "km", "Zmax": "m s.n.m.", "Zmin": "m s.n.m.",
    "Zmed": "m s.n.m.", "Z50": "m s.n.m.", "H": "m",
    "Ff": "adimensional", "Re": "adimensional", "Rc": "adimensional", "Kc": "adimensional",
    "Rf": "adimensional", "IS": "adimensional", "Sc": "adimensional", "Af": "adimensional",
    "Lc": "km", "Zinicio": "m s.n.m.", "Zfin": "m s.n.m.", "Hc": "m",
    "Se": "m/m", "SLR": "m/m", "STS": "m/m", "Gc": "m/m",
    "Scuenca_pct": "%", "Scuenca_deg": "°",
    "Lt": "km", "Dd": "km/km²", "Fs": "cauces/km²", "Dt": "cauces/km", "Id": "adimensional",
    "Lo": "km", "C": "km²/km", "If": "adimensional", "Nu": "cauces", "Lm": "km",
    "Omega": "adimensional", "Rb": "adimensional", "Jd": "uniones/km²",
    "Rr": "m/km", "Rh": "adimensional", "Rn": "adimensional", "Oc": "adimensional",
    "Im": "m/km²", "Mel": "adimensional",
}

# Comentario/interpretación GENERAL de cada parámetro (qué mide y en qué
# rango típico se considera qué cosa), que se muestra siempre en la
# columna "Interpretación" además de cualquier interpretación dinámica
# calculada a partir del valor real (antes esta columna quedaba vacía
# para casi todos los parámetros salvo Ff).
INTERPRETACIONES_GENERALES_MORFOMETRIA = {
    "A": "Tamaño total de la cuenca; determina junto con la intensidad de lluvia la magnitud "
         "del caudal máximo (a mayor área, mayor caudal pico en términos absolutos, pero menor "
         "intensidad de lluvia promedio simultánea sobre toda la cuenca).",
    "P": "Longitud del divisor topográfico; junto con el área define la compacidad (Kc) y la "
         "circularidad (Rc) de la cuenca.",
    "Lb": "Dimensión más larga de la cuenca; usada para estimar Ff, Re y el ancho medio B.",
    "B": "Ancho promedio perpendicular al eje mayor; cuencas con B pequeño en relación a Lb son alargadas.",
    "Zmax": "Cota más alta dentro de la cuenca (naciente/divisoria); define, junto con Zmin, el relieve H.",
    "Zmin": "Cota en el punto de salida/control (break point); referencia para el relieve H y las "
            "pendientes del cauce (Se, S10-85).",
    "Zmed": "Cota promedio de toda la superficie de la cuenca; usada en el índice de masividad (Im) "
            "y el coeficiente orográfico (Oc).",
    "Z50": "Cota bajo la cual se encuentra el 50% del área de la cuenca (mediana de la curva "
           "hipsométrica); una Z50 cercana a Zmed indica una distribución de área-elevación simétrica.",
    "H": "Diferencia de cota entre la naciente y la salida; a mayor H para una misma longitud de "
         "cauce, mayor pendiente y mayor velocidad de respuesta (menor Tc).",
    "Ff": "Ff = A/Lb². Ff < 0.45 ⇒ cuenca alargada (respuesta más lenta, hidrograma más achatado); "
          "Ff más cercano a 0.79 (círculo) ⇒ cuenca más ensanchada (picos de crecida más pronunciados).",
    "Re": "Re = (2/√π)·(√A/Lb). Re < 0.50 ⇒ muy alargada; 0.50-0.70 ⇒ oblonga; Re > 0.70 ⇒ circular a oval.",
    "Rc": "Rc = 4πA/P². Rc → 1 indica forma circular (mayor riesgo de crecidas súbitas simultáneas "
          "desde toda la cuenca); Rc pequeño (<<1) indica cuenca alargada/irregular.",
    "Kc": "Kc = 0.28·P/√A. Kc = 1 sería un círculo perfecto; Kc > 1.75 se interpreta como forma "
          "rectangular-oblonga (menor tendencia a crecidas simultáneas de todos los tributarios).",
    "Rf": "Razón entre la longitud del cauce principal y el perímetro de la cuenca; complementa la "
          "lectura de Kc/Rc sobre la forma general.",
    "IS": "IS = Lc real / Lc en línea recta. IS ≤ 1.3 ⇒ cauce de baja sinuosidad (más recto, mayor "
          "energía/velocidad); IS > 1.3 ⇒ cauce sinuoso (más laminación natural de la crecida).",
    "Sc": "Coeficiente de almacenamiento potencial del cauce respecto al área y longitud total de la red.",
    "Af": "Compara el área de la cuenca a cada lado del cauce principal; requiere digitalizar ambos "
          "márgenes por separado, algo que este plugin no automatiza — déjelo en blanco o calcúlelo "
          "aparte si lo necesita.",
    "Lc": "Longitud del cauce principal, desde el punto de salida hasta la naciente; extraída "
          "automáticamente de la red de drenaje delineada (Pestaña 1) cuando está disponible, o el "
          "valor ingresado manualmente en esta pestaña como respaldo.",
    "Zinicio": "Cota de la naciente/cabecera del cauce principal (extremo aguas arriba).",
    "Zfin": "Cota del punto de salida/control del cauce principal (extremo aguas abajo, = Zmin).",
    "Hc": "Hc = Zinicio − Zfin; desnivel a lo largo del cauce principal (equivalente a H del Grupo 1 "
          "cuando el cauce principal define también el relieve total de la cuenca).",
    "Se": "Se = Hc/Lc; pendiente media del cauce entre sus dos extremos (la aproximación más simple, "
          "sensible a irregularidades puntuales del perfil).",
    "SLR": "Pendiente del cauce ajustada por regresión lineal sobre todo el perfil longitudinal "
           "muestreado (menos sensible que Se a un solo punto anómalo del perfil).",
    "STS": "Pendiente compensada de Taylor-Schwartz: promedia la velocidad de tramos homogéneos del "
           "perfil en vez de promediar pendientes directamente: STS = (Lc / Σ(li/√Si))². Suele ser el "
           "valor más representativo para alimentar métodos de tiempo de concentración (Pestaña 4).",
    "Gc": "Gradiente del cauce principal (= Se); Gc > 5% se considera régimen torrencial, típico de "
          "quebradas andinas de fuerte pendiente con alto potencial de arrastre de sedimentos/detritos.",
    "Scuenca_pct": "Pendiente media de todas las celdas del MDE dentro de la cuenca (no solo del "
                   "cauce); Scuenca > 30% se considera muy escarpada. Alimenta directamente el método "
                   "SCS Lag y otros de tiempo de concentración (Pestaña 4).",
    "Scuenca_deg": "El mismo valor de pendiente media de la cuenca, expresado en grados sexagesimales "
                   "en vez de porcentaje (tan(°) = pendiente en m/m).",
    "Lt": "Suma de longitudes de todos los tramos de la red de drenaje vectorizada dentro de la cuenca.",
    "Dd": "Dd = Lt/A. Dd < 0.5 km/km² ⇒ drenaje pobre (suelos muy permeables/vegetados); "
          "Dd > 3-4 km/km² ⇒ drenaje muy denso, típico de suelos poco permeables o terreno muy "
          "erosionable (mayor y más rápida generación de escorrentía).",
    "Fs": "Número de cauces (tramos de orden 1, aproximado) por unidad de área; junto con Dd forma "
          "la intensidad de drenaje (Id).",
    "Dt": "Número de cauces por unidad de longitud del perímetro; otra medida de qué tan ramificada "
          "está la red respecto al borde de la cuenca.",
    "Id": "Id = Fs/Dd. Valores altos indican una red con muchos cauces cortos (respuesta rápida); "
          "valores bajos, pocos cauces largos.",
    "Lo": "Lo = 1/(2·Dd); distancia promedio que recorre el agua como flujo laminar antes de "
          "concentrarse en un cauce definido — insumo típico para el método de Kerby.",
    "C": "Inverso de la densidad de drenaje (C = 1/Dd); área de cuenca necesaria para sostener 1 km "
         "de cauce (constante de mantenimiento del cauce, Schumm).",
    "If": "If = Dd·Fs; combina densidad y frecuencia de cauces en un solo índice de disección del "
          "terreno por la red de drenaje.",
    "Nu": "Número de corrientes (cauces de orden 1, aproximado) ingresado por el usuario a partir de "
          "la red de drenaje delineada (Pestaña 1); insumo directo de Fs, Dt e If.",
    "Lm": "Lm = Lt/Nu; longitud promedio de cada corriente de la red.",
    "Omega": "Orden jerárquico de Strahler del cauce de mayor orden en la red (1 = cauce sin "
             "afluentes). Este plugin identifica el cauce principal como un único tramo continuo "
             "(Ω = 1); una clasificación de orden completa por confluencias requiere digitalizar la "
             "red de drenaje completa con topología de afluentes, no solo el cauce principal.",
    "Rb": "Rb = N_órdenes(k) / N_órdenes(k+1); razón de bifurcación de Horton-Strahler entre órdenes "
          "sucesivos (típicamente 3-5 en cuencas naturales). Requiere la red de drenaje completa "
          "clasificada por orden, no disponible con el cauce principal único de este plugin.",
    "Jd": "Jd = N° de confluencias / A; densidad de uniones de la red. Requiere la red de drenaje "
          "completa con su topología de confluencias, no disponible con el cauce principal único de "
          "este plugin.",
    "Rr": "Rr = H/√A; mide qué tan abrupto es el relieve en relación al tamaño de la cuenca "
          "(valores altos ⇒ cuencas de montaña de fuerte pendiente, típico del ámbito andino).",
    "Rh": "Rh = H/Lb; pendiente promedio a lo largo del eje mayor de la cuenca.",
    "Rn": "Rn = Dd·H/1000; combina relieve y densidad de drenaje — valores altos se asocian a mayor "
          "potencial erosivo y de transporte de sedimentos.",
    "Oc": "Oc = (Zmed/1000)²/A; relaciona la elevación media al cuadrado con el área, un indicador "
          "orográfico de la influencia de la altitud sobre la respuesta hidrológica.",
    "Im": "Im = Zmed/A; índice de masividad de Richter, mayor en cuencas pequeñas y de alta montaña.",
    "Mel": "Mel = H/√(A en m²); umbral empírico Mel ≥ 0.60 asociado a alta probabilidad de flujos de "
           "detritos/huaicos (Melton, 1965; Jackson et al., 1987) — parámetro central para este plugin, "
           "orientado justamente a obras de protección contra flujos de detritos.",
}


class HydroAndinaProDialog(QDialog):

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle("HydroAndes Pro - Análisis Hidrológico Integral")
        # Por defecto, un QDialog de Qt solo trae el botón de cerrar (sin
        # minimizar/maximizar), a diferencia de una ventana normal. Se
        # habilitan explícitamente esos botones para poder minimizar la
        # ventana del plugin y maximizarla a pantalla completa.
        # NOTA: la posición/orden de los botones (minimizar, maximizar,
        # cerrar) la decide el sistema operativo/gestor de ventanas, no la
        # aplicación — en Windows y la mayoría de Linux aparecen en la
        # esquina superior DERECHA; en macOS, en la superior izquierda.
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint
            | Qt.WindowSystemMenuHint
        )
        self.resize(980, 720)

        # Hoja de estilos global: evita que combos, spinboxes y campos de
        # texto se estiren a todo el ancho de la ventana dentro de los
        # QFormLayout (ya usan FieldsStayAtSizeHint más abajo) — aquí se
        # pone además un ancho máximo razonable como red de seguridad para
        # widgets cuyo sizeHint natural siga siendo demasiado grande (p.ej.
        # QComboBox con textos de opción muy largos). Los QTableWidget no
        # se ven afectados: sus columnas deben seguir ocupando el ancho
        # disponible (Stretch), eso sí es lo correcto para tablas.
        self.setStyleSheet(self.styleSheet() + """
            QComboBox, QSpinBox, QDoubleSpinBox { max-width: 340px; }
            QLineEdit { max-width: 380px; }
        """)

        # --- estado compartido entre pestañas ---
        self.break_point_xy = None          # (x, y) en CRS del proyecto
        self.break_point_lonlat = None       # (lon, lat) para determinar UTM
        self.utm_crs = None
        self.dem_layer = None
        self.dem_clip_path = None
        self.cuenca_layer = None
        self.red_drenaje_layer = None
        self.morfometria_resultados = {}
        self.cn_resultados = None
        self.tc_resultados = {}
        self.hidrograma_resultado = {}
        self.serie_precip_anual = None
        self.resultados_frecuencia = {}
        self.mejor_ajuste_clave = None
        self.p24_disenio = {}
        self.periodos_retorno_actuales = []
        self.serie_qc_activa = None  # serie activa de la pestaña 6 (Precipitación Media Mensual)
        self.resultados_hidraulica_drenaje = {}  # nombre de estructura -> dict de resultados (pestaña 7)
        self.resultado_cav = {}  # curva Cota-Área-Volumen (pestaña 4)
        # --- Pestaña Socavación ---
        self.secciones_socavacion = {}       # nombre -> dict con todos los inputs de la sección
        self.contador_secciones_socavacion = 0
        self.nombre_seccion_socavacion_activa = None
        self.resultados_socavacion = {}      # nombre_seccion -> {nombre_metodo: dict resultado}
        self.diametros_socavacion = {}       # D16/D35/D50/D65/D84/D90/Dm/sigma_g calculados de la curva
        self.curva_granulometrica_socavacion = []  # lista ordenada (diametro_mm, %pasa)
        self.map_tool_socavacion = None
        self._primer_clic_seccion_socavacion = None
        # --- Pestaña Pérdida en Suelos (USLE/RUSLE) ---
        self.zonas_perdida_suelo = {}        # nombre -> dict con todos los inputs de la zona
        self.contador_zonas_perdida_suelo = 0
        self.nombre_zona_perdida_suelo_activa = None
        self.resultados_perdida_suelo = {}   # nombre_zona -> dict resultado (R,K,LS,C,P,A,clase)
        self.raster_perdida_suelo_resultado = None  # dict devuelto por soil_loss.calcular_raster_perdida_suelo
        # --- Pestaña Sedimentos en Suspensión y Transporte de Sedimentos ---
        self.secciones_sedimentos = {}
        self.contador_secciones_sedimentos = 0
        self.nombre_seccion_sedimentos_activa = None
        self.resultados_sedimentos = {}      # nombre_seccion -> dict resultado
        self.map_tool_sedimentos = None
        self._primer_clic_seccion_sedimentos = None
        # --- Pestaña Flujos Hiperconcentrados/Lodos/Detritos ---
        self.resultado_flujo_hiperconcentrado = None  # dict con clasificación, reología y métodos calculados
        # --- Pestaña Cambio Climático - Escenarios ---
        self.resultado_cambio_climatico = None  # dict con series delta-change por escenario
        self.resultado_correccion_sesgo = None   # dict con la corrección de sesgo aplicada
        # --- Pestaña Caudales Medios (Qm) ---
        self.resultado_simulacion_qm = None   # dict con la última simulación/calibración de caudales medios
        # --- Pestaña Caudales Mínimos ---
        self.resultado_caudales_minimos = {}  # nombre_metodo -> valor Q mínimo (m3/s), acumulado entre secciones
        # --- Pestaña Caudal Ecológico - PHABSIM ---
        self.estaciones_phabsim = {}          # nombre -> dict con ancho, sustrato_code, caudales/tirantes/velocidades de calibración
        self.contador_estaciones_phabsim = 0
        self.nombre_estacion_phabsim_activa = None
        self.resultado_curva_phabsim = None   # dict devuelto por phabsim.curva_caudal_wua + puntos notables
        # --- Pestaña Flujo Subterráneo ---
        self.resultado_flujo_subterraneo = None  # dict con cargas h, velocidades, convergencia
        # --- Pestaña Hidráulica de Pozos ---
        self.resultado_pozo = {}  # dict con resultados de las distintas secciones (Theis, Cooper-Jacob, perdidas, radios)
        # --- gestor de cuencas delimitadas (varias en la misma sesión) ---
        # Cada vez que se delimita una cuenca se guarda con un nombre
        # numerado secuencialmente ("Cuenca 1", "Cuenca 2", ...) en este
        # diccionario (que conserva el orden de inserción), y queda
        # disponible en el menú desplegable de la pestaña 1 para volver a
        # seleccionarla como la cuenca activa en cualquier momento.
        self.cuencas_guardadas = {}   # nombre -> snapshot de la delimitación
        self.contador_cuencas = 0
        self.nombre_cuenca_activa = None
        self.map_tool = None

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self._build_tab1()
        self._build_tab2()
        self._build_tab3()
        self._build_tab4()
        self._build_tab_precipitacion()
        self._build_tab_precipitacion_mensual()
        self._build_tab5()
        self._build_tab_hidraulica_drenaje()
        self._build_tab_modulos_avanzados()
        self._build_tab_socavacion()
        self._build_tab_perdida_suelos()
        self._build_tab_sedimentos()
        self._build_tab_flujos_hiperconcentrados()
        self._build_tab_cambio_climatico()
        self._build_tab_caudales_medios()
        self._build_tab_caudales_minimos()
        self._build_tab_phabsim()
        self._build_tab_flujo_subterraneo()
        self._build_tab_hidraulica_pozos()
        self._build_tab_exportacion()
        self._build_tab6()

    # ------------------------------------------------------------------
    # TAB 1: DEM Acquisition & Delineation
    # ------------------------------------------------------------------
    def _agregar_pestaña_con_scroll(self, tab_contenido: QWidget, titulo: str):
        """
        Envuelve el contenido de una pestaña en un QScrollArea antes de
        agregarla a self.tabs, para que gráficos y tablas no queden
        comprimidos verticalmente cuando el contenido de la pestaña es
        más alto que el espacio disponible en la ventana (antes se
        agregaba 'tab' directamente, sin scroll).
        """
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(tab_contenido)
        self.tabs.addTab(scroll, titulo)

    def _build_tab1(self):
        tab = QWidget()
        v = QVBoxLayout(tab)

        # --- Adquisición del MDE ---
        gb_dem = QGroupBox("1. MDE (Modelo Digital de Elevación)")
        f = QFormLayout(gb_dem)

        f.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.combo_dem = QgsMapLayerComboBox()
        self.combo_dem.setFilters(QgsMapLayerProxyModel.RasterLayer)
        f.addRow("MDE ya cargado en el proyecto:", self.combo_dem)

        h_api = QHBoxLayout()
        self.edit_api_key = QLineEdit()
        self.edit_api_key.setEchoMode(QLineEdit.Password)
        self.edit_api_key.setPlaceholderText("API Key de OpenTopography (opcional, solo si va a descargar)")
        h_api.addWidget(self.edit_api_key)
        self.combo_demtype = QComboBox()
        for clave, etiqueta in dem_download.DEMTYPES_DISPONIBLES.items():
            self.combo_demtype.addItem(etiqueta, clave)
        h_api.addWidget(self.combo_demtype)
        self.btn_descargar_dem = QPushButton("Descargar MDE (OpenTopography)")
        self.btn_descargar_dem.clicked.connect(self._on_descargar_dem)
        h_api.addWidget(self.btn_descargar_dem)
        f.addRow("Descargar MDE:", h_api)

        h_asf = QHBoxLayout()
        self.edit_asf_token = QLineEdit()
        self.edit_asf_token.setEchoMode(QLineEdit.Password)
        self.edit_asf_token.setPlaceholderText("Token de NASA Earthdata (urs.earthdata.nasa.gov > My Profile > Generate Token)")
        h_asf.addWidget(self.edit_asf_token)
        self.btn_descargar_dem_asf = QPushButton("Descargar MDE (ASF Vertex / Copernicus GLO-30)")
        self.btn_descargar_dem_asf.clicked.connect(self._on_descargar_dem_asf)
        h_asf.addWidget(self.btn_descargar_dem_asf)
        f.addRow("Descargar MDE (alternativa):", h_asf)
        lbl_hint_asf = QLabel(
            'Fuente alternativa a OpenTopography: <a href="https://search.asf.alaska.edu">search.asf.alaska.edu</a> '
            "(ASF DAAC / Vertex), Copernicus GLO-30. Requiere un token de NASA Earthdata Login "
            "(gratuito, distinto de la API Key de OpenTopography)."
        )
        lbl_hint_asf.setOpenExternalLinks(True)
        lbl_hint_asf.setWordWrap(True)
        lbl_hint_asf.setStyleSheet("color: #666; font-size: 9px;")
        f.addRow(lbl_hint_asf)

        v.addWidget(gb_dem)

        # --- AOI ---
        gb_aoi = QGroupBox("2. Área de interés (AOI) / límite aproximado")
        f2 = QFormLayout(gb_aoi)
        f2.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        h_aoi = QHBoxLayout()
        self.edit_aoi_path = QLineEdit()
        self.edit_aoi_path.setPlaceholderText("Ruta a .shp / .kml / .geojson (opcional)")
        h_aoi.addWidget(self.edit_aoi_path)
        btn_aoi = QPushButton("Examinar...")
        btn_aoi.clicked.connect(self._on_examinar_aoi)
        h_aoi.addWidget(btn_aoi)
        f2.addRow("Archivo AOI:", h_aoi)
        v.addWidget(gb_aoi)

        # --- Break point ---
        gb_bp = QGroupBox("3. Punto de salida (Break Point)")
        f3 = QFormLayout(gb_bp)
        f3.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        h_bp = QHBoxLayout()
        self.btn_break_point = QPushButton("Seleccionar en el mapa (clic)")
        self.btn_break_point.setCheckable(True)
        self.btn_break_point.clicked.connect(self._activar_map_tool)
        h_bp.addWidget(self.btn_break_point)
        self.edit_bp_coords = QLineEdit()
        self.edit_bp_coords.setReadOnly(True)
        self.edit_bp_coords.setPlaceholderText("(sin seleccionar todavía)")
        h_bp.addWidget(self.edit_bp_coords)
        f3.addRow("Coordenada:", h_bp)

        h_bp_file = QHBoxLayout()
        self.edit_bp_file_path = QLineEdit()
        self.edit_bp_file_path.setPlaceholderText("(alternativa) Ruta a un archivo SHP/KML/KMZ con el punto de salida")
        h_bp_file.addWidget(self.edit_bp_file_path)
        btn_bp_examinar = QPushButton("Examinar...")
        btn_bp_examinar.clicked.connect(self._on_examinar_bp_archivo)
        h_bp_file.addWidget(btn_bp_examinar)
        btn_bp_cargar = QPushButton("Cargar punto desde archivo")
        btn_bp_cargar.clicked.connect(self._on_cargar_bp_desde_archivo)
        h_bp_file.addWidget(btn_bp_cargar)
        f3.addRow("Desde archivo:", h_bp_file)

        lbl_hint_bp = QLabel(
            "Puede seleccionar el punto interactivamente haciendo clic en el mapa (esta ventana se "
            "oculta para que pueda ver el lienzo), o cargarlo desde un archivo vectorial "
            "(SHP/KML/KMZ/GeoJSON) que contenga un punto — se usa el primer punto encontrado."
        )
        lbl_hint_bp.setWordWrap(True)
        lbl_hint_bp.setStyleSheet("color: #666; font-size: 9px;")
        f3.addRow(lbl_hint_bp)
        v.addWidget(gb_bp)

        # --- Mapa web (basemap) con control de transparencia ---
        gb_mapa_web = QGroupBox("3b. Mapa web de referencia (opcional)")
        v_mw = QVBoxLayout(gb_mapa_web)
        _lbl_auto_1 = QLabel(
            "Añade un mapa web (OpenStreetMap u otro) como capa de fondo en el proyecto, con un "
            "control de transparencia para superponer el MDE y la red de drenaje encima sin perder "
            "la referencia geográfica. Útil para ubicar visualmente el punto de salida sobre la "
            "red, antes de delimitar."
        )
        _lbl_auto_1.setWordWrap(True)
        v_mw.addWidget(_lbl_auto_1)
        h_mw = QHBoxLayout()
        self.combo_basemap = QComboBox()
        self.combo_basemap.addItems([
            "OpenStreetMap", "Google Satellite", "Google Terrain", "ESRI World Imagery",
        ])
        h_mw.addWidget(self.combo_basemap)
        btn_agregar_basemap = QPushButton("Añadir mapa web al proyecto")
        btn_agregar_basemap.clicked.connect(self._on_agregar_basemap)
        h_mw.addWidget(btn_agregar_basemap)
        v_mw.addLayout(h_mw)

        h_transp = QHBoxLayout()
        h_transp.addWidget(QLabel("Transparencia del mapa web (%):"))
        from qgis.PyQt.QtWidgets import QSlider
        self.slider_transparencia_basemap = QSlider(Qt.Horizontal)
        self.slider_transparencia_basemap.setRange(0, 100)
        self.slider_transparencia_basemap.setValue(50)
        self.slider_transparencia_basemap.valueChanged.connect(self._on_cambiar_transparencia_basemap)
        h_transp.addWidget(self.slider_transparencia_basemap)
        self.lbl_transparencia_basemap = QLabel("50%")
        h_transp.addWidget(self.lbl_transparencia_basemap)
        v_mw.addLayout(h_transp)
        v.addWidget(gb_mapa_web)

        # --- Procesamiento en 2 pasos ---
        gb_run = QGroupBox("4. Procesamiento y delimitación (2 pasos)")
        f4 = QFormLayout(gb_run)
        f4.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        lbl_paso_a = QLabel(
            "<b>Paso A:</b> Genera la red de drenaje con orden de Strahler sobre el MDE. "
            "Esto le permite ver la red ANTES de delimitar, y elegir/ajustar el punto de salida "
            "sobre un cauce real visible en el mapa."
        )
        lbl_paso_a.setWordWrap(True)
        f4.addRow(lbl_paso_a)
        self.spin_umbral = QSpinBox()
        self.spin_umbral.setRange(1, 100000)
        self.spin_umbral.setValue(25)
        f4.addRow("Umbral de acumulación de flujo (celdas):", self.spin_umbral)

        self.btn_generar_red = QPushButton("Paso A: Generar red de drenaje (Stream Network)")
        self.btn_generar_red.clicked.connect(self._on_generar_red_drenaje)
        limitar_ancho_boton(self.btn_generar_red)
        f4.addRow(self.btn_generar_red)

        lbl_paso_b = QLabel(
            "<b>Paso B:</b> Con la red ya visible en el mapa, seleccione/ajuste el break point "
            "sobre un cauce, y pulse el botón de abajo para delimitar la cuenca desde ese punto."
        )
        lbl_paso_b.setWordWrap(True)
        f4.addRow(lbl_paso_b)

        self.spin_smooth_offset = QDoubleSpinBox()
        self.spin_smooth_offset.setRange(0.0, 0.5)
        self.spin_smooth_offset.setSingleStep(0.05)
        self.spin_smooth_offset.setValue(0.25)
        f4.addRow("Offset de suavizado de geometría:", self.spin_smooth_offset)

        self.check_snap_cauce = QCheckBox("Ajustar automáticamente el punto de salida al cauce más cercano")
        self.check_snap_cauce.setChecked(True)
        f4.addRow(self.check_snap_cauce)

        self.spin_radio_snap = QSpinBox()
        self.spin_radio_snap.setRange(1, 200)
        self.spin_radio_snap.setValue(15)
        f4.addRow("Radio de búsqueda del ajuste (n° de celdas del MDE):", self.spin_radio_snap)

        self.btn_run_delineation = QPushButton("Paso B: Delimitar cuenca desde el break point")
        self.btn_run_delineation.clicked.connect(self._on_run_delineation)
        limitar_ancho_boton(self.btn_run_delineation)
        f4.addRow(self.btn_run_delineation)

        self.lbl_estado_tab1 = QLabel("Estado: en espera de MDE + break point.")
        f4.addRow(self.lbl_estado_tab1)

        v.addWidget(gb_run)

        gb_cuencas = QGroupBox("5. Cuencas delimitadas en esta sesión")
        f5 = QFormLayout(gb_cuencas)
        f5.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        lbl_cuencas_guardadas = QLabel(
            "Cada vez que se delimita una cuenca queda guardada aquí con un nombre numerado "
            "secuencialmente (Cuenca 1, Cuenca 2, ...); seleccione cualquiera del menú para "
            "volver a activarla como la cuenca de trabajo para el resto de pestañas."
        )
        lbl_cuencas_guardadas.setWordWrap(True)
        f5.addRow(lbl_cuencas_guardadas)
        self.combo_cuenca_activa = QComboBox()
        self.combo_cuenca_activa.addItem("(ninguna cuenca delimitada todavía)")
        self.combo_cuenca_activa.currentIndexChanged.connect(self._on_cambiar_cuenca_activa)
        f5.addRow("Cuenca activa:", self.combo_cuenca_activa)
        v.addWidget(gb_cuencas)

        v.addStretch()

        self._agregar_pestaña_con_scroll(tab, "1. DEM y Delimitación")

    def _on_examinar_bp_archivo(self):
        ruta, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar punto de salida", "", "Vectores (*.shp *.kml *.kmz *.geojson *.json)"
        )
        if ruta:
            self.edit_bp_file_path.setText(ruta)

    def _on_cargar_bp_desde_archivo(self):
        ruta = self.edit_bp_file_path.text().strip()
        if not ruta or not os.path.exists(ruta):
            QMessageBox.warning(self, "Archivo no encontrado", "Seleccione primero un archivo con el punto de salida.")
            return
        try:
            capa = QgsVectorLayer(ruta, "bp_temp", "ogr")
            if not capa.isValid():
                raise RuntimeError("No se pudo leer el archivo vectorial.")
            feat = next(capa.getFeatures(), None)
            if feat is None:
                raise RuntimeError("El archivo no contiene ninguna entidad.")
            geom = feat.geometry()
            if geom is None or geom.isEmpty():
                raise RuntimeError("La primera entidad no tiene geometría.")
            punto = geom.asPoint() if not geom.isMultipart() else geom.asMultiPoint()[0]

            # Reproyectar a WGS84 para determinar la zona UTM (mismo flujo que la selección interactiva)
            from qgis.core import QgsCoordinateTransform, QgsCoordinateReferenceSystem
            wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
            xform = QgsCoordinateTransform(capa.crs(), wgs84, QgsProject.instance())
            punto_wgs = xform.transform(punto)
            self.break_point_lonlat = (punto_wgs.x(), punto_wgs.y())

            zona_utm = int((punto_wgs.x() + 180) / 6) + 1
            hemisferio = "S" if punto_wgs.y() < 0 else "N"
            epsg = 32700 + zona_utm if hemisferio == "S" else 32600 + zona_utm
            self.utm_crs = QgsCoordinateReferenceSystem(f"EPSG:{epsg}")
            xform_utm = QgsCoordinateTransform(capa.crs(), self.utm_crs, QgsProject.instance())
            punto_utm = xform_utm.transform(punto)
            self.break_point_xy = (punto_utm.x(), punto_utm.y())

            self.edit_bp_coords.setText(
                f"X={punto_utm.x():.2f}  Y={punto_utm.y():.2f}  ({self.utm_crs.authid()})  "
                f"[cargado desde {os.path.basename(ruta)}]"
            )
            self.lbl_estado_tab1.setText(
                f"Estado: break point cargado desde archivo. MDE se reproyectará a "
                f"{self.utm_crs.authid()} al ejecutar la delimitación."
            )
            QMessageBox.information(self, "Punto de salida cargado",
                                     f"Break point: X={punto_utm.x():.2f}, Y={punto_utm.y():.2f} "
                                     f"({self.utm_crs.authid()}), cargado desde {os.path.basename(ruta)}.")
        except Exception as e:
            QMessageBox.critical(self, "Error cargando el punto de salida", str(e))

    _BASEMAP_URLS = {
        "OpenStreetMap": "type=xyz&url=https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "Google Satellite": "type=xyz&url=https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
        "Google Terrain": "type=xyz&url=https://mt1.google.com/vt/lyrs=p&x={x}&y={y}&z={z}",
        "ESRI World Imagery": "type=xyz&url=https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    }

    def _on_agregar_basemap(self):
        nombre = self.combo_basemap.currentText()
        url = self._BASEMAP_URLS.get(nombre)
        if not url:
            return
        try:
            capa = QgsRasterLayer(url, nombre, "wms")
            if not capa.isValid():
                raise RuntimeError(f"No se pudo cargar el mapa web '{nombre}'. Verifique la conectividad a Internet.")
            QgsProject.instance().addMapLayer(capa, True)
            # Aplicar la transparencia actual del slider
            transparencia = self.slider_transparencia_basemap.value()
            capa.renderer().setOpacity(1.0 - transparencia / 100.0)
            capa.triggerRepaint()
            self._basemap_layer = capa
            self.lbl_estado_tab1.setText(f"Mapa web '{nombre}' añadido al proyecto.")
        except Exception as e:
            QMessageBox.critical(self, "Error añadiendo el mapa web", str(e))

    def _on_cambiar_transparencia_basemap(self, valor):
        self.lbl_transparencia_basemap.setText(f"{valor}%")
        capa = getattr(self, "_basemap_layer", None)
        if capa is not None and capa.isValid():
            capa.renderer().setOpacity(1.0 - valor / 100.0)
            capa.triggerRepaint()

    def _on_generar_red_drenaje(self):
        """Paso A: genera solo la red de drenaje (stream network) con
        orden de Strahler sobre el MDE, SIN delimitar ninguna cuenca
        todavía — esto le permite ver la red y elegir/ajustar el punto
        de salida sobre un cauce real visible en el mapa, antes de
        delimitar."""
        dem_layer = self.combo_dem.currentLayer()
        if dem_layer is None:
            QMessageBox.warning(self, "Falta el MDE", "Seleccione o cargue un MDE primero (paso 1).")
            return
        try:
            self.lbl_estado_tab1.setText("Estado: generando la red de drenaje (Paso A)...")
            QApplication.processEvents()
            context = QgsProcessingContext()
            feedback = QgsProcessingFeedback()

            # Reproyectar el MDE a UTM si se tiene la zona ya definida
            # (por la selección del break point o por la AOI), o usar el
            # MDE tal cual si aún no se seleccionó nada.
            if self.utm_crs is not None and dem_layer.crs() != self.utm_crs:
                import processing
                resultado_reproyeccion = processing.run(
                    "gdal:warpreproject",
                    {"INPUT": dem_layer, "SOURCE_CRS": dem_layer.crs(), "TARGET_CRS": self.utm_crs,
                     "OUTPUT": "TEMPORARY_OUTPUT"},
                    context=context, feedback=feedback, is_child_algorithm=True,
                )
                dem_layer = obtener_capa(resultado_reproyeccion["OUTPUT"], context, es_raster=True, nombre="mde_utm")

            self.dem_layer = dem_layer

            # Calcular flujo y generar la red de drenaje (reutilizando las
            # funciones de core.delineation que ya hacen esto como parte
            # de la cadena completa de delimitación).
            resultado_flujo = delineation.calcular_flujo(
                dem_layer, umbral_acumulacion=self.spin_umbral.value(),
                context=context, feedback=feedback,
            )

            resultado_red = delineation.extraer_y_recortar_red(
                resultado_flujo["raster_cauces"], ruta_cuenca_vector=None,
                region=resultado_flujo["region"],
                context=context, feedback=feedback,
            )
            capa_red = obtener_capa(resultado_red["red_drenaje_vector"], context, es_raster=False, nombre="red_drenaje_stream_network")
            QgsProject.instance().addMapLayer(capa_red)
            self.resultado_flujo_paso_a = resultado_flujo  # guardar para reutilizar en el Paso B
            self.lbl_estado_tab1.setText(
                "Estado: red de drenaje generada (Paso A completado). Ahora seleccione el punto de "
                "salida sobre un cauce visible en el mapa, y pulse el Paso B para delimitar la cuenca."
            )
            QMessageBox.information(self, "Paso A completado",
                                     "Red de drenaje generada y añadida al proyecto. Seleccione ahora el "
                                     "punto de salida sobre un cauce visible en el mapa.")
        except Exception as e:
            self.lbl_estado_tab1.setText("Estado: error en el Paso A (ver mensaje).")
            QMessageBox.critical(self, "Error generando la red de drenaje", str(e))

    def _on_examinar_aoi(self):
        ruta, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar AOI", "", "Vectores (*.shp *.kml *.geojson *.json)"
        )
        if ruta:
            self.edit_aoi_path.setText(ruta)

    def _on_descargar_dem(self):
        aoi_path = self.edit_aoi_path.text().strip()
        if not aoi_path or not os.path.exists(aoi_path):
            QMessageBox.warning(self, "AOI requerida",
                                 "Seleccione primero un archivo AOI (paso 2) para determinar el bounding box a descargar.")
            return
        try:
            capa = QgsVectorLayer(aoi_path, "aoi_temp", "ogr")
            if not capa.isValid():
                raise RuntimeError("No se pudo leer el archivo AOI.")
            extent = capa.extent()
            # Reproyectar a WGS84 si es necesario
            if capa.crs().authid() != "EPSG:4326":
                xform = QgsCoordinateTransform(capa.crs(), QgsCoordinateReferenceSystem("EPSG:4326"),
                                                QgsProject.instance())
                extent = xform.transformBoundingBox(extent)
            bbox = (extent.yMinimum(), extent.yMaximum(), extent.xMinimum(), extent.xMaximum())

            ruta_tif = dem_download.descargar_dem(
                bbox, self.edit_api_key.text().strip(),
                demtype=self.combo_demtype.currentData(),
            )
            capa_dem = QgsRasterLayer(ruta_tif, "MDE descargado")
            if not capa_dem.isValid():
                raise RuntimeError("El archivo descargado no es un ráster válido.")
            QgsProject.instance().addMapLayer(capa_dem)
            self.combo_dem.setLayer(capa_dem)
            QMessageBox.information(self, "Descarga completa", f"MDE guardado en:\n{ruta_tif}")
        except Exception as e:
            QMessageBox.critical(self, "Error al descargar el MDE", str(e))

    def _on_descargar_dem_asf(self):
        aoi_path = self.edit_aoi_path.text().strip()
        if not aoi_path or not os.path.exists(aoi_path):
            QMessageBox.warning(self, "AOI requerida",
                                 "Seleccione primero un archivo AOI (paso 2) para determinar el bounding box a descargar.")
            return
        try:
            capa = QgsVectorLayer(aoi_path, "aoi_temp", "ogr")
            if not capa.isValid():
                raise RuntimeError("No se pudo leer el archivo AOI.")
            extent = capa.extent()
            if capa.crs().authid() != "EPSG:4326":
                xform = QgsCoordinateTransform(capa.crs(), QgsCoordinateReferenceSystem("EPSG:4326"),
                                                QgsProject.instance())
                extent = xform.transformBoundingBox(extent)
            bbox = (extent.yMinimum(), extent.yMaximum(), extent.xMinimum(), extent.xMaximum())

            ruta_tif = dem_download_asf.descargar_dem_asf(bbox, self.edit_asf_token.text().strip())
            capa_dem = QgsRasterLayer(ruta_tif, "MDE descargado (ASF)")
            if not capa_dem.isValid():
                raise RuntimeError("El archivo descargado no es un ráster válido.")
            QgsProject.instance().addMapLayer(capa_dem)
            self.combo_dem.setLayer(capa_dem)
            QMessageBox.information(self, "Descarga completa", f"MDE guardado en:\n{ruta_tif}")
        except Exception as e:
            QMessageBox.critical(self, "Error al descargar el MDE desde ASF", str(e))

    def _activar_map_tool(self, checked):
        canvas = self.iface.mapCanvas()
        if checked:
            self.map_tool = QgsMapToolEmitPoint(canvas)
            self.map_tool.canvasClicked.connect(self._on_canvas_clicked)
            # Si el usuario cancela la selección sin llegar a hacer clic
            # (tecla Escape, o cambia a otra herramienta de QGIS desde la
            # barra de herramientas), este mismo mapa deja de ser la
            # herramienta activa; detectamos ese cambio para no dejar la
            # ventana del plugin oculta indefinidamente.
            canvas.mapToolSet.connect(self._on_map_tool_changed)
            canvas.setMapTool(self.map_tool)
            self.btn_break_point.setText("Haga clic en el mapa...")
            # Ocultar la ventana del plugin mientras se selecciona el punto,
            # para que no tape el lienzo justo donde el usuario necesita
            # hacer clic.
            self.hide()
        else:
            try:
                canvas.mapToolSet.disconnect(self._on_map_tool_changed)
            except TypeError:
                pass  # ya estaba desconectada
            canvas.unsetMapTool(self.map_tool)
            self.btn_break_point.setText("Seleccionar en el mapa (clic)")
            self._restaurar_ventana()

    def _on_map_tool_changed(self, herramienta_nueva, herramienta_anterior):
        """Se dispara cuando cambia la herramienta activa del lienzo. Si el
        cambio no vino de nuestro propio flujo normal (clic ya procesado en
        _on_canvas_clicked, que ya desconecta esta señal antes de cambiar de
        herramienta), significa que el usuario canceló la selección de otra
        forma (Escape, u otra herramienta de la barra de QGIS); restauramos
        la ventana igualmente para que no quede oculta."""
        if herramienta_nueva is not self.map_tool:
            self.btn_break_point.setChecked(False)
            self.btn_break_point.setText("Seleccionar en el mapa (clic)")
            self._restaurar_ventana()

    def _restaurar_ventana(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def _on_canvas_clicked(self, point, button):
        canvas = self.iface.mapCanvas()
        project_crs = canvas.mapSettings().destinationCrs()

        # Coordenadas en lon/lat, para determinar la zona UTM
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        xform_to_wgs84 = QgsCoordinateTransform(project_crs, wgs84, QgsProject.instance())
        punto_wgs84 = xform_to_wgs84.transform(point)
        self.break_point_lonlat = (punto_wgs84.x(), punto_wgs84.y())

        epsg_utm = utm_epsg_for_lonlat(*self.break_point_lonlat)
        self.utm_crs = QgsCoordinateReferenceSystem(f"EPSG:{epsg_utm}")

        xform_to_utm = QgsCoordinateTransform(project_crs, self.utm_crs, QgsProject.instance())
        punto_utm = xform_to_utm.transform(point)
        self.break_point_xy = (punto_utm.x(), punto_utm.y())

        self.edit_bp_coords.setText(
            f"X={punto_utm.x():.2f}  Y={punto_utm.y():.2f}  ({self.utm_crs.authid()})"
        )
        self.btn_break_point.setChecked(False)
        self._activar_map_tool(False)  # esto ya restaura la ventana (ver rama 'else' arriba)
        self.lbl_estado_tab1.setText("Estado: break point definido. MDE se reproyectará a "
                                      f"{self.utm_crs.authid()} al ejecutar la delimitación.")

    def _on_run_delineation(self):
        dem_layer = self.combo_dem.currentLayer()
        if dem_layer is None:
            QMessageBox.warning(self, "Falta el MDE", "Seleccione o descargue un MDE en el paso 1.")
            return
        if self.break_point_xy is None:
            QMessageBox.warning(self, "Falta el break point", "Seleccione el punto de salida en el mapa (paso 3).")
            return

        try:
            # Reproyectar el MDE a la zona UTM local si su CRS difiere
            if dem_layer.crs().authid() != self.utm_crs.authid():
                self.lbl_estado_tab1.setText(f"Reproyectando MDE a {self.utm_crs.authid()}...")
                import processing
                resultado_reproyeccion = processing.run(
                    "gdal:warpreproject",
                    {"INPUT": dem_layer, "TARGET_CRS": self.utm_crs, "OUTPUT": "TEMPORARY_OUTPUT"},
                )
                ruta_reproyectada = resultado_reproyeccion.get("OUTPUT")
                if not ruta_reproyectada:
                    raise RuntimeError(
                        "La reproyección del MDE (gdal:warpreproject) no devolvió una salida válida. "
                        "Verifique que GDAL esté correctamente instalado y que el MDE de entrada sea válido."
                    )
                dem_layer = QgsRasterLayer(ruta_reproyectada, "MDE_UTM")
                if not dem_layer.isValid():
                    raise RuntimeError(
                        f"El MDE reproyectado a {self.utm_crs.authid()} no es una capa ráster válida "
                        f"(ruta: {ruta_reproyectada}). Verifique el MDE de entrada."
                    )

            # Validación temprana: si el punto de salida cae fuera de la
            # extensión real del MDE, no tiene sentido ejecutar toda la
            # cadena de delineación (que puede tardar varios minutos) solo
            # para fallar al final. Se detecta y se informa de inmediato.
            extent_dem = dem_layer.extent()
            px, py = self.break_point_xy
            if not extent_dem.contains(QgsPointXY(px, py)):
                raise RuntimeError(
                    "El punto de salida (break point) cae fuera de la extensión del MDE "
                    f"(extensión del MDE en {self.utm_crs.authid()}: "
                    f"X=[{extent_dem.xMinimum():.1f}, {extent_dem.xMaximum():.1f}], "
                    f"Y=[{extent_dem.yMinimum():.1f}, {extent_dem.yMaximum():.1f}]; "
                    f"punto clicado: X={px:.1f}, Y={py:.1f}). Verifique que hizo clic dentro del área "
                    "cubierta por el MDE cargado, y que el MDE efectivamente cubre la subcuenca de interés."
                )

            self.dem_layer = dem_layer

            context = QgsProcessingContext()
            feedback = QgsProcessingFeedback()

            self.lbl_estado_tab1.setText("Calculando dirección y acumulación de flujo...")
            # Si el Paso A (generar red de drenaje) ya se ejecutó en esta
            # sesión, reutiliza su resultado de flujo en vez de recalcularlo
            # (ahorra tiempo, que puede ser significativo con MDE grandes).
            if getattr(self, "resultado_flujo_paso_a", None) is not None:
                flujo = self.resultado_flujo_paso_a
                self.lbl_estado_tab1.setText("Reutilizando el cálculo de flujo del Paso A...")
            else:
                flujo = delineation.calcular_flujo(
                    dem_layer, umbral_acumulacion=self.spin_umbral.value(),
                    context=context, feedback=feedback,
                )

            punto_delineacion = self.break_point_xy
            if self.check_snap_cauce.isChecked():
                self.lbl_estado_tab1.setText("Ajustando el punto de salida al cauce más cercano...")
                resultado_snap = pour_point_snap.snap_a_cauce(
                    flujo["raster_cauces"], *self.break_point_xy,
                    radio_celdas=self.spin_radio_snap.value(),
                )
                if not resultado_snap["encontrado"]:
                    raise RuntimeError(
                        "No se encontró ninguna celda de cauce dentro del radio de búsqueda alrededor del "
                        "punto de salida. Aumente el 'radio de búsqueda del ajuste' (paso 4), reduzca el "
                        "umbral de acumulación de flujo, o desmarque el ajuste automático y haga clic "
                        "manualmente sobre la red de drenaje visible (algoritmo '2. Extraer red de drenaje')."
                    )
                punto_delineacion = (resultado_snap["x"], resultado_snap["y"])
                self.lbl_estado_tab1.setText(
                    f"Punto ajustado {resultado_snap['distancia_m']:.1f} m respecto al clic original. "
                    "Delimitando la cuenca..."
                )

            resultado = {}
            resultado["cuenca_vector"] = delineation.delinear_desde_punto(
                flujo["raster_direccion"], punto_delineacion, flujo["region"],
                context=context, feedback=feedback,
                smooth_offset=self.spin_smooth_offset.value(),
            )
            resultado["red_drenaje_vector"] = delineation.extraer_y_recortar_red(
                flujo["raster_cauces"], resultado["cuenca_vector"], flujo["region"],
                context=context, feedback=feedback,
            )

            self.cuenca_layer = obtener_capa(resultado["cuenca_vector"], context, es_raster=False, nombre="cuenca")
            self.red_drenaje_layer = obtener_capa(resultado["red_drenaje_vector"], context, es_raster=False, nombre="red_drenaje")

            # Diagnóstico específico: si la cuenca delineada quedó vacía (0
            # entidades) A PESAR del ajuste automático del punto, la causa ya
            # no es la ubicación del clic (eso ya se corrigió arriba), sino
            # más probablemente un umbral de acumulación demasiado alto para
            # el tamaño de la cuenca, o un MDE de baja resolución.
            if self.cuenca_layer.featureCount() == 0:
                raise RuntimeError(
                    "La cuenca delineada quedó vacía (0 polígonos) incluso después de ajustar el punto de "
                    "salida al cauce más cercano. Pruebe: 1) reducir el umbral de acumulación de flujo "
                    "(paso 4) para generar una red de drenaje más densa; 2) verificar que el MDE cubra "
                    "realmente el área de la cuenca esperada; 3) verificar que el MDE tenga resolución "
                    "suficiente para representar el cauce en ese punto."
                )

            QgsProject.instance().addMapLayer(self.cuenca_layer)
            QgsProject.instance().addMapLayer(self.red_drenaje_layer)

            # Recortar el MDE a la cuenca para las estadísticas de los grupos 1 y 4
            dem_clip = delineation.clip_dem_a_cuenca(self.dem_layer, self.cuenca_layer,
                                                      context=context, feedback=feedback)
            dem_clip_layer = obtener_capa(dem_clip, context, es_raster=True, nombre="dem_clip")
            self.dem_clip_path = dem_clip_layer.source()

            # Cada delimitación exitosa se guarda como una nueva cuenca
            # numerada secuencialmente (Cuenca 1, Cuenca 2, ...) y queda
            # disponible en el menú desplegable de la sección 5, sin
            # perder las delimitaciones anteriores de la misma sesión.
            self.contador_cuencas += 1
            nombre_nuevo = f"Cuenca {self.contador_cuencas}"
            self.cuencas_guardadas[nombre_nuevo] = {
                "cuenca_layer": self.cuenca_layer,
                "red_drenaje_layer": self.red_drenaje_layer,
                "dem_layer": self.dem_layer,
                "dem_clip_path": self.dem_clip_path,
                "break_point_xy": self.break_point_xy,
            }
            self.nombre_cuenca_activa = nombre_nuevo
            self.combo_cuenca_activa.blockSignals(True)
            if self.combo_cuenca_activa.count() == 1 and \
                    self.combo_cuenca_activa.itemText(0).startswith("(ninguna"):
                self.combo_cuenca_activa.clear()
            self.combo_cuenca_activa.addItem(nombre_nuevo)
            self.combo_cuenca_activa.setCurrentIndex(self.combo_cuenca_activa.count() - 1)
            self.combo_cuenca_activa.blockSignals(False)

            self.lbl_estado_tab1.setText(
                f"Delimitación completa ({nombre_nuevo}). Pase a la pestaña 2 para calcular la morfometría."
            )
            QMessageBox.information(self, "Delimitación completa",
                                     f"Cuenca y red de drenaje generadas y añadidas al proyecto como '{nombre_nuevo}'.")
        except Exception as e:
            self.lbl_estado_tab1.setText("Error durante la delimitación (ver mensaje).")
            QMessageBox.critical(self, "Error en la delimitación", str(e))

    def _on_cambiar_cuenca_activa(self, indice: int):
        nombre = self.combo_cuenca_activa.itemText(indice)
        if nombre not in self.cuencas_guardadas:
            return  # el placeholder "(ninguna cuenca delimitada todavía)"

        estado = self.cuencas_guardadas[nombre]
        self.cuenca_layer = estado["cuenca_layer"]
        self.red_drenaje_layer = estado["red_drenaje_layer"]
        self.dem_layer = estado["dem_layer"]
        self.dem_clip_path = estado["dem_clip_path"]
        self.break_point_xy = estado["break_point_xy"]
        self.nombre_cuenca_activa = nombre

        # Los resultados calculados en las pestañas 2 en adelante (morfometría,
        # CN, Tc, hidrograma) son específicos de la cuenca con la que se
        # calcularon; al cambiar de cuenca activa se limpian para evitar
        # mostrar resultados de otra cuenca por error, y se le pide al
        # usuario recalcularlos para la cuenca recién seleccionada.
        self.morfometria_resultados = {}
        self.cn_resultados = None
        self.tc_resultados = {}
        self.hidrograma_resultado = {}

        # Limpieza visual de las tablas/gráficos de resultados de la
        # cuenca anterior, para no confundirlos con los de la cuenca
        # recién seleccionada (que aún no se han recalculado).
        for tabla in (getattr(self, "tabla_morfo", None), getattr(self, "tabla_amc", None),
                      getattr(self, "tabla_tc", None), getattr(self, "tabla_desglose_cn_auto", None)):
            if tabla is not None:
                try:
                    tabla.setRowCount(0) if tabla is not self.tabla_amc else tabla.clearContents()
                except Exception:
                    pass
        tabla_resumen_hipso = getattr(self, "tabla_resumen_hipsometrica", None)
        if tabla_resumen_hipso is not None:
            for col in range(tabla_resumen_hipso.columnCount()):
                tabla_resumen_hipso.setItem(1, col, QTableWidgetItem(""))
        if getattr(self, "canvas_hipsometrica", None) is not None:
            self.canvas_hipsometrica.ax.clear()
            self.canvas_hipsometrica.draw()

        self.lbl_estado_tab1.setText(
            f"Cuenca activa: {nombre}. Recalcule la morfometría (pestaña 2), el CN (pestaña 3), el "
            "Tc (pestaña 4) y el caudal (pestaña 6) para esta cuenca."
        )
        QMessageBox.information(
            self, "Cuenca activa cambiada",
            f"'{nombre}' es ahora la cuenca activa para el resto de pestañas. Los resultados de "
            "morfometría, CN, Tc e hidrograma de la cuenca anterior se limpiaron; recalcúlelos para "
            f"'{nombre}' en las pestañas correspondientes."
        )

    # ------------------------------------------------------------------
    # TAB 2: Morphometry & Drainage
    # ------------------------------------------------------------------
    def _build_tab2(self):
        tab = QWidget()
        v = QVBoxLayout(tab)

        h_top = QHBoxLayout()
        self.spin_lc_km = QDoubleSpinBox()
        self.spin_lc_km.setRange(0.001, 10000)
        self.spin_lc_km.setDecimals(3)
        h_top.addWidget(QLabel("Longitud del cauce principal Lc (km):"))
        h_top.addWidget(self.spin_lc_km)

        self.spin_lt_km = QDoubleSpinBox()
        self.spin_lt_km.setRange(0.001, 100000)
        self.spin_lt_km.setDecimals(3)
        h_top.addWidget(QLabel("Long. total de la red Lt (km):"))
        h_top.addWidget(self.spin_lt_km)

        self.spin_n_cauces = QSpinBox()
        self.spin_n_cauces.setRange(1, 100000)
        h_top.addWidget(QLabel("N° de cauces (Nu):"))
        h_top.addWidget(self.spin_n_cauces)

        self.btn_calc_morfo = QPushButton("Calcular parámetros morfométricos")
        self.btn_calc_morfo.clicked.connect(self._on_calcular_morfometria)
        h_top.addWidget(self.btn_calc_morfo)
        v.addLayout(h_top)

        self.tabla_morfo = QTableWidget(0, 5)
        self.tabla_morfo.setHorizontalHeaderLabels(["Parámetro", "Símbolo", "Valor", "Unidad", "Interpretación"])
        cabecera_morfo = self.tabla_morfo.horizontalHeader()
        # Antes las 5 columnas se repartían el ancho por igual (Stretch en
        # todas), dejando "Interpretación" comprimida pese a tener el texto
        # más largo. Ahora "Parámetro" e "Interpretación" son las únicas en
        # modo Stretch (se reparten el espacio sobrante, con más peso para
        # Interpretación al ser la más ancha en contenido), y
        # Símbolo/Valor/Unidad quedan con un ancho fijo angosto acorde a su
        # contenido corto.
        cabecera_morfo.setSectionResizeMode(0, QHeaderView.Interactive)
        cabecera_morfo.setSectionResizeMode(1, QHeaderView.Fixed)
        cabecera_morfo.setSectionResizeMode(2, QHeaderView.Fixed)
        cabecera_morfo.setSectionResizeMode(3, QHeaderView.Fixed)
        cabecera_morfo.setSectionResizeMode(4, QHeaderView.Stretch)
        self.tabla_morfo.setColumnWidth(0, 260)
        self.tabla_morfo.setColumnWidth(1, 55)
        self.tabla_morfo.setColumnWidth(2, 75)
        self.tabla_morfo.setColumnWidth(3, 75)
        v.addWidget(self.tabla_morfo)

        self._agregar_pestaña_con_scroll(tab, "2. Morfometría y drenaje")

    def _agregar_fila_morfo(self, nombre, simbolo, valor, interpretacion_dinamica="", clave_lookup=None):
        """
        clave_lookup: clave a usar para buscar unidad/interpretación en
        UNIDADES_PARAMETROS_MORFOMETRIA / INTERPRETACIONES_GENERALES_MORFOMETRIA,
        si es distinta del texto que se muestra en la columna "Símbolo"
        (caso de Scuenca: se muestra el mismo símbolo "Scuenca" en dos
        filas -- % y ° -- pero cada una necesita su propia unidad, así
        que se buscan con claves internas distintas "Scuenca_pct"/
        "Scuenca_deg"). Si no se indica, se usa `simbolo` como antes.
        """
        clave = clave_lookup if clave_lookup is not None else simbolo
        row = self.tabla_morfo.rowCount()
        self.tabla_morfo.insertRow(row)
        self.tabla_morfo.setItem(row, 0, QTableWidgetItem(str(nombre)))
        self.tabla_morfo.setItem(row, 1, QTableWidgetItem(str(simbolo)))
        valor_str = f"{valor:.3f}" if isinstance(valor, float) else str(valor)
        self.tabla_morfo.setItem(row, 2, QTableWidgetItem(valor_str))
        self.tabla_morfo.setItem(row, 3, QTableWidgetItem(UNIDADES_PARAMETROS_MORFOMETRIA.get(clave, "")))
        interpretacion_general = INTERPRETACIONES_GENERALES_MORFOMETRIA.get(clave, "")
        if interpretacion_dinamica and interpretacion_general:
            texto_final = f"{interpretacion_dinamica} — {interpretacion_general}"
        else:
            texto_final = interpretacion_dinamica or interpretacion_general
        self.tabla_morfo.setItem(row, 4, QTableWidgetItem(texto_final))

    def _agregar_titulo_grupo_morfo(self, titulo):
        """Inserta una fila de encabezado de sección (en negrita, ocupando
        las 5 columnas) dentro de tabla_morfo, para separar visualmente
        los 6 grupos de parámetros morfométricos."""
        row = self.tabla_morfo.rowCount()
        self.tabla_morfo.insertRow(row)
        item = QTableWidgetItem(titulo)
        fuente = item.font()
        fuente.setBold(True)
        item.setFont(fuente)
        self.tabla_morfo.setItem(row, 0, item)
        self.tabla_morfo.setSpan(row, 0, 1, self.tabla_morfo.columnCount())

    def _calcular_g3_g4(self, g1: dict):
        """
        Calcula los Grupos 3 (cauce principal) y 4 (pendiente de cuenca +
        curva hipsométrica), compartido entre la Pestaña 2 (donde ambos
        grupos se agregan a la tabla de resultados de morfometría) y la
        Pestaña 4 (Tc, que además usa Se/S10-85 como insumo directo y
        grafica la curva hipsométrica). Devuelve (g3 o None, g4 o None);
        si algo falla se avisa con un QMessageBox.warning y se devuelve
        None para ese grupo, sin interrumpir el resto del cálculo del
        llamador (antes esta lógica solo existía, duplicable, dentro de
        _on_calcular_tc).
        """
        g4 = None
        if self.dem_clip_path:
            try:
                z_array = raster_stats.leer_array_valido(self.dem_clip_path)
                slope_path = delineation.calcular_pendiente(QgsRasterLayer(self.dem_clip_path, "dem_clip"))
                slope_array = raster_stats.leer_array_valido(slope_path)
                g4 = morphometry.grupo4_pendiente_hipsometria(slope_array, z_array)
            except Exception as e_g4:
                QMessageBox.warning(self, "Pendiente media de la cuenca no disponible", str(e_g4))

        g3 = None
        if getattr(self, "red_drenaje_layer", None) is not None and getattr(self, "dem_layer", None) is not None \
                and self.break_point_xy is not None:
            try:
                perfil = main_channel.extraer_perfil_cauce_principal(
                    self.red_drenaje_layer, self.dem_layer, self.break_point_xy
                )
                # OJO con la convención: perfil["elevaciones_m"] está
                # ordenado desde la SALIDA (índice 0, cota BAJA) hasta la
                # NACIENTE (índice -1, cota ALTA). Pero
                # grupo3_cauce_principal() calcula hc = z_inicio - z_fin
                # esperando que "z_inicio" sea la NACIENTE (cota alta, de
                # donde "inicia" el río) y "z_fin" la SALIDA (cota baja) —
                # la convención inversa a la del array del perfil. Pasarlos
                # en el orden del array daba hc y Se NEGATIVOS; se corrige
                # aquí.
                g3 = morphometry.grupo3_cauce_principal(
                    lc_km=perfil["lc_km"],
                    z_inicio=float(perfil["elevaciones_m"][-1]),  # naciente (alta)
                    z_fin=float(perfil["elevaciones_m"][0]),      # salida (baja)
                    perfil_distancias_m=perfil["distancias_m"],
                    perfil_elevaciones_m=perfil["elevaciones_m"],
                )
                if g3["Se"] <= 0:
                    raise ValueError(
                        f"Se resultó no positivo ({g3['Se']}); revise que el punto de salida esté "
                        "bien ubicado sobre el cauce (pestaña 1)."
                    )
            except Exception as e_perfil:
                QMessageBox.warning(
                    self, "Perfil del cauce principal no disponible",
                    "No se pudo extraer automáticamente el perfil longitudinal del cauce principal "
                    f"({e_perfil}); Lc/Zinicio/Zfin/Hc/Se/SLR/STS/Gc no estarán disponibles (para el "
                    "cálculo de Tc en la pestaña 4 se usará la aproximación Se = H/Lc como respaldo). "
                    "Revise que la pestaña 1 haya generado la red de drenaje y que el punto de salida "
                    "esté definido."
                )
                g3 = None

        return g3, g4

    def _on_calcular_morfometria(self):
        if self.cuenca_layer is None or self.dem_clip_path is None:
            QMessageBox.warning(self, "Falta la delimitación",
                                 "Ejecute primero la delimitación en la pestaña 1.")
            return
        try:
            self.tabla_morfo.setRowCount(0)

            # --- geometría de la cuenca ---
            feat = next(self.cuenca_layer.getFeatures())
            geom = feat.geometry()
            area_m2 = geom.area()
            perimetro_m = geom.length()  # para geometrías de polígono, QgsGeometry.length()
            # devuelve el perímetro del anillo exterior (comportamiento documentado de PyQGIS).

            obb = geom.orientedMinimumBoundingBox()
            # obb = (QgsGeometry, area, angle, width, height) en QGIS 3.x
            _, _, _, ancho, alto = obb
            lb_m = max(ancho, alto)

            z_array = raster_stats.leer_array_valido(self.dem_clip_path)
            z_max = float(z_array.max())
            z_min_muestreado = raster_stats.valor_en_punto(self.dem_clip_path, *self.break_point_xy)
            z_min_real_dem = float(z_array.min())
            # El punto de salida (break point) debería, por definición,
            # ser el punto de menor cota de la cuenca delineada (o estar
            # muy cerca de serlo). Si el valor muestreado ahí resulta
            # notoriamente MAYOR que el mínimo real del MDE recortado, es
            # señal de que el punto de salida no quedó bien ajustado sobre
            # el cauce (p. ej. quedó sobre una ladera/cresta cercana), lo
            # que después hace fallar Giandotti y distorsiona H, Rr, Rh,
            # etc. En ese caso se usa el mínimo real del MDE como
            # respaldo, avisando al usuario en vez de fallar en silencio.
            if z_min_muestreado is None or (z_min_muestreado - z_min_real_dem) > max(0.02 * (z_max - z_min_real_dem), 5.0):
                QMessageBox.warning(
                    self, "Punto de salida posiblemente mal ajustado",
                    "La cota muestreada en el punto de salida "
                    f"({z_min_muestreado}) es notoriamente mayor que la cota mínima real del MDE "
                    f"recortado a la cuenca ({round(z_min_real_dem, 2)} m s.n.m.). Esto sugiere que "
                    "el punto de salida no quedó bien ajustado sobre el cauce (pestaña 1, ajuste al "
                    "cauce/pour point). Se usará el mínimo real del MDE como Z_min de respaldo; "
                    "verifique el punto de salida antes de un diseño definitivo."
                )
                z_min = z_min_real_dem
            else:
                z_min = z_min_muestreado

            # ================= GRUPO 1: parámetros básicos =================
            g1 = morphometry.grupo1_basicos(area_m2, perimetro_m, lb_m, z_max, z_min, z_array)
            self._agregar_titulo_grupo_morfo("1 — Parámetros básicos de la cuenca")
            for k, v in g1.items():
                self._agregar_fila_morfo(NOMBRES_PARAMETROS_MORFOMETRIA.get(k, k), k, v)

            # ================= GRUPO 2: forma e índices de forma =================
            lc_km = self.spin_lc_km.value()
            lt_km = self.spin_lt_km.value()
            g2 = morphometry.grupo2_forma(g1["A"], g1["Lb"], g1["P"], lc_km, lt_km)
            # morphometry.grupo2_forma() devuelve 'interpretacion' como una
            # lista en el orden [Ff, Re, Rc, Kc, IS]; se reparte cada texto
            # a la fila de su propio parámetro (antes se volcaban los 5
            # textos juntos únicamente en la fila de Ff).
            interpretaciones_g2 = {
                "Ff": g2["interpretacion"][0] if len(g2["interpretacion"]) > 0 else "",
                "Re": g2["interpretacion"][1] if len(g2["interpretacion"]) > 1 else "",
                "Rc": g2["interpretacion"][2] if len(g2["interpretacion"]) > 2 else "",
                "Kc": g2["interpretacion"][3] if len(g2["interpretacion"]) > 3 else "",
                "IS": g2["interpretacion"][4] if len(g2["interpretacion"]) > 4 else "",
            }
            self._agregar_titulo_grupo_morfo("2 — Parámetros de forma e índices de forma")
            for k, val in g2.items():
                if k == "interpretacion":
                    continue
                self._agregar_fila_morfo(NOMBRES_PARAMETROS_MORFOMETRIA.get(k, k), k, val,
                                          interpretaciones_g2.get(k, ""))
            # Factor de asimetría: requiere digitalizar ambos márgenes de la
            # cuenca por separado (no automatizado en este plugin); se deja
            # la fila con "—" en vez de omitirla, para que la estructura de
            # 6 grupos quede siempre completa.
            self._agregar_fila_morfo(NOMBRES_PARAMETROS_MORFOMETRIA["Af"], "Af", "—", clave_lookup="Af")

            # ================= GRUPOS 3 y 4: cauce principal y pendiente =================
            # Antes solo se calculaban al entrar a la Pestaña 4 (Tc); ahora
            # se calculan también aquí (mismo helper compartido) para que
            # la tabla de morfometría quede completa con los 6 grupos desde
            # el primer cálculo, sin tener que visitar otra pestaña.
            g3, g4 = self._calcular_g3_g4(g1)

            self._agregar_titulo_grupo_morfo("3 — Parámetros del cauce principal")
            if g3 is not None:
                for simbolo in ("Lc", "Zinicio", "Zfin", "Hc", "Se", "SLR", "STS"):
                    self._agregar_fila_morfo(NOMBRES_PARAMETROS_MORFOMETRIA[simbolo], simbolo, g3[simbolo])
                self._agregar_fila_morfo(NOMBRES_PARAMETROS_MORFOMETRIA["Gc"], "Gc", g3["Gc"], g3["interpretacion"])
            else:
                for simbolo in ("Lc", "Zinicio", "Zfin", "Hc", "Se", "SLR", "STS", "Gc"):
                    self._agregar_fila_morfo(NOMBRES_PARAMETROS_MORFOMETRIA[simbolo], simbolo, "—",
                                              "No disponible: no se pudo extraer el perfil del cauce "
                                              "(ver aviso anterior).")

            self._agregar_titulo_grupo_morfo("4 — Pendiente media de la cuenca")
            if g4 is not None:
                self._agregar_fila_morfo("Pendiente media de la cuenca", "Scuenca", g4["S_cuenca_pct"],
                                          g4["interpretacion"], clave_lookup="Scuenca_pct")
                self._agregar_fila_morfo("Pendiente media de la cuenca", "Scuenca", g4["S_cuenca_deg"],
                                          clave_lookup="Scuenca_deg")
            else:
                self._agregar_fila_morfo("Pendiente media de la cuenca", "Scuenca", "—", clave_lookup="Scuenca_pct")
                self._agregar_fila_morfo("Pendiente media de la cuenca", "Scuenca", "—", clave_lookup="Scuenca_deg")

            # ================= GRUPO 5: red de drenaje =================
            g5 = morphometry.grupo5_red_drenaje(lt_km, g1["A"], g1["P"], self.spin_n_cauces.value())
            self._agregar_titulo_grupo_morfo("5 — Parámetros de la red de drenaje")
            for k, v in g5.items():
                self._agregar_fila_morfo(NOMBRES_PARAMETROS_MORFOMETRIA.get(k, k), k, v)
            # Orden de Strahler, razón de bifurcación y densidad de uniones
            # requieren la red de drenaje completa clasificada por orden
            # (topología de afluentes); este plugin solo digitaliza/extrae
            # el cauce principal como un único tramo continuo, así que Ω se
            # informa como 1 y Rb/Jd quedan en "—" (ver interpretación).
            self._agregar_fila_morfo(NOMBRES_PARAMETROS_MORFOMETRIA["Omega"], "Ω", 1,
                                      "Cauce principal identificado (un solo tramo continuo).",
                                      clave_lookup="Omega")
            self._agregar_fila_morfo(NOMBRES_PARAMETROS_MORFOMETRIA["Rb"], "Rb", "—", clave_lookup="Rb")
            self._agregar_fila_morfo(NOMBRES_PARAMETROS_MORFOMETRIA["Jd"], "Jd", "—", clave_lookup="Jd")

            # ================= GRUPO 6: relieve =================
            g6 = morphometry.grupo6_relieve_riesgo(g1["H"], g1["A"], g1["Lb"], g5["Dd"], g1["Zmed"])
            self._agregar_titulo_grupo_morfo("6 — Parámetros de relieve")
            for k, v in g6.items():
                if k in ("alerta_flujo_detritos", "mensaje_alerta", "Mel"):
                    continue  # 'Mel' se agrega explícitamente abajo, con su mensaje de alerta
                self._agregar_fila_morfo(NOMBRES_PARAMETROS_MORFOMETRIA.get(k, k), k, v)
            self._agregar_fila_morfo("Número de rugosidad de Melton (riesgo de flujo de detritos)",
                                      "Mel", g6["Mel"], g6["mensaje_alerta"])

            # Guardar todo para exportación y para la pestaña 4 (Tc)
            self.morfometria_resultados = {"g1": g1, "g2": g2, "g5": g5, "g6": g6, "lc_km": lc_km}
            if g3 is not None:
                self.morfometria_resultados["g3"] = g3
            if g4 is not None:
                self.morfometria_resultados["g4"] = g4

            # Recalcula el alto de la tabla ahora que tiene ~45-50 filas (6
            # grupos completos + sus encabezados de sección): se construyó
            # con 0 filas y nunca recalculaba su alto, quedando con el alto
            # por defecto de Qt para 0 filas. Con un techo de 60 filas
            # visibles, la tabla completa se ve sin scroll interno propio
            # (el scroll de la pestaña, ya existente, se encarga del resto
            # si la ventana es más chica que el contenido).
            ajustar_alto_tabla(self.tabla_morfo, filas_visibles_max=60)

            if g6["alerta_flujo_detritos"]:
                QMessageBox.warning(self, "Alerta de flujo de detritos", g6["mensaje_alerta"])

        except Exception as e:
            QMessageBox.critical(self, "Error calculando morfometría", str(e))

    # ------------------------------------------------------------------
    # TAB 3: SCS Curve Number & Rainfall
    # ------------------------------------------------------------------
    def _build_tab3(self):
        tab = QWidget()
        v = QVBoxLayout(tab)

        _lbl_auto_2 = QLabel(
            "Matriz de uso de suelo x Grupo Hidrológico (A/B/C/D). Valores por defecto "
            "orientativos para condiciones altoandinas/Puna; edite el área (km²) de cada "
            "cobertura presente en su cuenca y verifique los CN contra una fuente local antes "
            "de un diseño definitivo."
        )
        _lbl_auto_2.setWordWrap(True)
        v.addWidget(_lbl_auto_2)

        # Columnas: Uso de suelo, CN-A..D, % cuenca (nueva, editable) y
        # Área (km²) -- el % permite distribuir el Área total ya calculada
        # en la Pestaña 2 (Morfometría) en vez de tener que calcular a mano
        # cuántos km² representa cada cobertura.
        self.tabla_cn = QTableWidget(len(curve_number.TABLA_USOS_ANDINOS_DEFAULT), 7)
        self.tabla_cn.setHorizontalHeaderLabels(
            ["Uso de suelo", "CN-A", "CN-B", "CN-C", "CN-D", "% cuenca", "Área (km²)"])
        for i, uso in enumerate(curve_number.TABLA_USOS_ANDINOS_DEFAULT):
            self.tabla_cn.setItem(i, 0, QTableWidgetItem(uso.nombre))
            self.tabla_cn.setItem(i, 1, QTableWidgetItem(str(uso.cn_a)))
            self.tabla_cn.setItem(i, 2, QTableWidgetItem(str(uso.cn_b)))
            self.tabla_cn.setItem(i, 3, QTableWidgetItem(str(uso.cn_c)))
            self.tabla_cn.setItem(i, 4, QTableWidgetItem(str(uso.cn_d)))
            self.tabla_cn.setItem(i, 5, QTableWidgetItem("0.0"))
            self.tabla_cn.setItem(i, 6, QTableWidgetItem("0.0"))
        # "Uso de suelo" tiene nombres largos (hasta ~49 caracteres, p.ej.
        # "Pastos naturales (ichu / ratio pobre-degradado)"), pero su ancho
        # NATURAL (ResizeToContents) ya cabe cómodo en la ventana (~700px
        # en total con las demás columnas) -- no hace falta que absorba el
        # espacio sobrante. La v0.2.36 le había puesto Stretch pensando que
        # ayudaba, pero eso la hacía ocupar TODO el ancho disponible del
        # viewport (mucho más de lo que su contenido necesita), viéndose
        # desproporcionada; se vuelve a ResizeToContents, con las columnas
        # numéricas en un ancho fijo angosto acorde a su contenido.
        cabecera_cn = self.tabla_cn.horizontalHeader()
        cabecera_cn.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        for col, ancho in ((1, 55), (2, 55), (3, 55), (4, 55), (5, 70), (6, 95)):
            cabecera_cn.setSectionResizeMode(col, QHeaderView.Fixed)
            self.tabla_cn.setColumnWidth(col, ancho)
        ajustar_alto_tabla(self.tabla_cn, filas_visibles_max=10)
        v.addWidget(self.tabla_cn)

        h_dist_pct = QHBoxLayout()
        self.btn_distribuir_area_pct = QPushButton(
            "Distribuir área por % (usa el Área total ya calculada en la Pestaña 2)"
        )
        self.btn_distribuir_area_pct.clicked.connect(self._on_distribuir_area_por_porcentaje)
        h_dist_pct.addWidget(self.btn_distribuir_area_pct)
        v.addLayout(h_dist_pct)
        self.lbl_estado_distribucion_pct = QLabel(
            "Ingrese el % de la cuenca que ocupa cada uso de suelo en la columna \"% cuenca\" "
            "(no hace falta que sumen exactamente 100%; se avisa si se desvían mucho) y pulse el "
            "botón para calcular el Área (km²) de cada fila automáticamente."
        )
        self.lbl_estado_distribucion_pct.setWordWrap(True)
        v.addWidget(self.lbl_estado_distribucion_pct)

        h = QHBoxLayout()
        h.addWidget(QLabel("Grupo hidrológico dominante para la ponderación simple:"))
        self.combo_grupo_hidrologico = QComboBox()
        self.combo_grupo_hidrologico.addItems(["A", "B", "C", "D"])
        self.combo_grupo_hidrologico.setCurrentText("C")
        h.addWidget(self.combo_grupo_hidrologico)
        self.btn_calc_cn = QPushButton("Calcular CN ponderado (AMC I/II/III)")
        self.btn_calc_cn.clicked.connect(self._on_calcular_cn)
        h.addWidget(self.btn_calc_cn)
        v.addLayout(h)

        self.tabla_amc = QTableWidget(1, 5)
        self.tabla_amc.setHorizontalHeaderLabels(["CN_I", "CN_II", "CN_III", "S (mm)", "Ia (mm)"])
        self.tabla_amc.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        v.addWidget(self.tabla_amc)

        gb_cn_generator = QGroupBox(
            "Generar CN automáticamente (RECOMENDADO) — plugin de terceros 'Curve Number Generator' "
            "(ESA & ORNL), de Abdul Raheem Siddiqui"
        )
        f_cng = QFormLayout(gb_cn_generator)
        f_cng.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        lbl_cn_generator_info = QLabel(
            "Requiere tener instalado el plugin <b>Curve Number Generator</b> (Complementos &gt; "
            "Administrar e instalar complementos &gt; busque 'Curve Number Generator'). Descarga "
            "automáticamente ESA WorldCover 2021 y HYSOGs250m (ORNL) para la cuenca delimitada, y "
            "calcula el CN directamente — no requiere indicar ningún ráster manualmente.\n"
            "Si el plugin no está instalado, use el método alternativo más abajo."
        )
        lbl_cn_generator_info.setWordWrap(True)
        f_cng.addRow(lbl_cn_generator_info)
        self.combo_cng_condicion = QComboBox()
        self.combo_cng_condicion.addItems(["Fair (recomendado si no está seguro)", "Poor", "Good"])
        f_cng.addRow("Condición hidrológica:", self.combo_cng_condicion)

        self.combo_cng_arc = QComboBox()
        self.combo_cng_arc.addItems(["II (recomendado si no está seguro)", "I", "III"])
        f_cng.addRow("Condición antecedente de humedad (ARC):", self.combo_cng_arc)

        self.btn_calc_cn_generator = QPushButton(
            "Generar CN automáticamente (ESA WorldCover + HYSOGs250m)"
        )
        self.btn_calc_cn_generator.clicked.connect(self._on_calcular_cn_generator_plugin)
        limitar_ancho_boton(self.btn_calc_cn_generator)
        f_cng.addRow(self.btn_calc_cn_generator)

        self.lbl_estado_cn_generator = QLabel("Estado: sin calcular.")
        self.lbl_estado_cn_generator.setWordWrap(True)
        f_cng.addRow(self.lbl_estado_cn_generator)

        v.addWidget(gb_cn_generator)

        gb_auto_cn = QGroupBox(
            "Método alternativo (si no tiene instalado el plugin 'Curve Number Generator'): LULC + "
            "Grupos Hidrológicos de Suelo por separado"
        )
        f_auto_cn = QFormLayout(gb_auto_cn)
        f_auto_cn.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        lbl_auto_cn_info = QLabel(
            "A. Uso y cobertura de suelo (LULC): ESA WorldCover 10 m, obtenido automáticamente vía "
            "el catálogo STAC de AWS Earth Search (recorte remoto a la cuenca, sin descargar el "
            "mosaico global completo).\n"
            "B. Grupo Hidrológico de Suelo (HSG A/B/C/D): HYSOGs250m (ORNL DAAC) — indique abajo la "
            "ruta local o URL del GeoTIFF (no se encontró un catálogo STAC público estable para "
            "este dataset; ver docstring de core/landcover_soils.py)."
        )
        lbl_auto_cn_info.setWordWrap(True)
        f_auto_cn.addRow(lbl_auto_cn_info)
        self.edit_hsg_ruta = QLineEdit()
        self.edit_hsg_ruta.setPlaceholderText(
            "Ruta local o URL http(s) al GeoTIFF de HYSOGs250m (p.ej. descargado de https://doi.org/10.3334/ORNLDAAC/1566)"
        )
        h_hsg = QHBoxLayout()
        h_hsg.addWidget(self.edit_hsg_ruta)
        btn_hsg = QPushButton("Examinar archivo local...")
        btn_hsg.clicked.connect(self._on_examinar_hsg)
        h_hsg.addWidget(btn_hsg)
        f_auto_cn.addRow("Ráster de HSG (A/B/C/D):", h_hsg)

        self.btn_calc_cn_automatico = QPushButton(
            "Obtener LULC + HSG automáticamente y calcular CN ponderado"
        )
        self.btn_calc_cn_automatico.clicked.connect(self._on_calcular_cn_automatico)
        limitar_ancho_boton(self.btn_calc_cn_automatico)
        f_auto_cn.addRow(self.btn_calc_cn_automatico)

        self.lbl_estado_cn_auto = QLabel("Estado: sin calcular.")
        self.lbl_estado_cn_auto.setWordWrap(True)
        f_auto_cn.addRow(self.lbl_estado_cn_auto)

        v.addWidget(gb_auto_cn)

        self.tabla_desglose_cn_auto = QTableWidget(0, 4)
        self.tabla_desglose_cn_auto.setHorizontalHeaderLabels(
            ["Uso de suelo (ESA WorldCover)", "Grupo hidrológico", "Área (km²)", "CN"]
        )
        # "Uso de suelo (ESA WorldCover)" trae nombres de clase de cobertura
        # de longitud variable; en Stretch absorbe el espacio sobrante y
        # evita que la suma de las 4 columnas supere el ancho de la ventana.
        aplicar_columna_elastica(self.tabla_desglose_cn_auto, indice_columna_larga=0,
                                  anchos_fijos={1: 110, 2: 90, 3: 55})
        v.addWidget(self.tabla_desglose_cn_auto)

        self._agregar_pestaña_con_scroll(tab, "3. Número de Curva SCS")

    def _on_calcular_cn_generator_plugin(self):
        if self.cuenca_layer is None:
            QMessageBox.warning(self, "Falta la delimitación",
                                 "Ejecute primero la delimitación en la pestaña 1.")
            return
        try:
            condicion = self.combo_cng_condicion.currentText().split(" ")[0]  # "Fair"/"Poor"/"Good"
            arc = self.combo_cng_arc.currentText().split(" ")[0]              # "II"/"I"/"III"

            self.lbl_estado_cn_generator.setText(
                "Estado: buscando el algoritmo del plugin 'Curve Number Generator'..."
            )
            QApplication.processEvents()
            context = QgsProcessingContext()
            feedback = QgsProcessingFeedback()

            resultado = cn_generator_bridge.ejecutar_cn_generator(
                self.cuenca_layer, context, feedback, condicion_hidrologica=condicion, arc=arc
            )

            self.tabla_desglose_cn_auto.setRowCount(0)
            for fila in resultado["desglose"]:
                r = self.tabla_desglose_cn_auto.rowCount()
                self.tabla_desglose_cn_auto.insertRow(r)
                self.tabla_desglose_cn_auto.setItem(r, 0, QTableWidgetItem("(polígono del plugin CN Generator)"))
                self.tabla_desglose_cn_auto.setItem(r, 1, QTableWidgetItem(""))
                self.tabla_desglose_cn_auto.setItem(r, 2, QTableWidgetItem(str(fila["area_km2"])))
                self.tabla_desglose_cn_auto.setItem(r, 3, QTableWidgetItem(str(fila["cn"])))
            ajustar_alto_tabla(self.tabla_desglose_cn_auto, filas_visibles_max=10)

            QgsProject.instance().addMapLayer(resultado["capa_cn_vectorizada"])

            cn_ii = resultado["cn_ii_ponderado"]
            amc = curve_number.condiciones_amc(cn_ii)
            self.cn_resultados = amc
            self.tabla_amc.setItem(0, 0, QTableWidgetItem(str(amc["CN_I"])))
            self.tabla_amc.setItem(0, 1, QTableWidgetItem(str(amc["CN_II"])))
            self.tabla_amc.setItem(0, 2, QTableWidgetItem(str(amc["CN_III"])))
            self.tabla_amc.setItem(0, 3, QTableWidgetItem(str(amc["S_mm"])))
            self.tabla_amc.setItem(0, 4, QTableWidgetItem(str(amc["Ia_mm"])))

            self.lbl_estado_cn_generator.setText(
                f"Estado: CN_II ponderado = {cn_ii} (algoritmo: {resultado['algoritmo_usado']}, "
                f"área total = {resultado['area_total_km2']} km², "
                f"{len(resultado['desglose'])} polígonos). Capa vectorizada añadida al proyecto."
            )
        except cn_generator_bridge.CnGeneratorBridgeError as e:
            self.lbl_estado_cn_generator.setText("Estado: no disponible (ver mensaje).")
            QMessageBox.warning(self, "Curve Number Generator no disponible", str(e))
        except Exception as e:
            self.lbl_estado_cn_generator.setText("Estado: error (ver mensaje).")
            QMessageBox.critical(self, "Error ejecutando Curve Number Generator", str(e))

    def _on_examinar_hsg(self):
        ruta, _ = QFileDialog.getOpenFileName(self, "Seleccionar ráster de HSG", "", "GeoTIFF (*.tif *.tiff)")
        if ruta:
            self.edit_hsg_ruta.setText(ruta)

    def _on_calcular_cn_automatico(self):
        if self.cuenca_layer is None:
            QMessageBox.warning(self, "Falta la delimitación",
                                 "Ejecute primero la delimitación en la pestaña 1.")
            return
        ruta_hsg = self.edit_hsg_ruta.text().strip()
        if not ruta_hsg:
            QMessageBox.warning(self, "Falta el ráster de HSG",
                                 "Indique la ruta local o URL del ráster de Grupos Hidrológicos de "
                                 "Suelo (HYSOGs250m u otro ya reclasificado a A/B/C/D).")
            return
        try:
            self.lbl_estado_cn_auto.setText("Estado: buscando y recortando ESA WorldCover (STAC)...")
            QApplication.processEvents()
            context = QgsProcessingContext()
            feedback = QgsProcessingFeedback()

            lulc_path = landcover_soils.obtener_lulc_esa_worldcover_recortado(
                self.cuenca_layer, context, feedback
            )
            self.lbl_estado_cn_auto.setText("Estado: recortando el ráster de HSG a la cuenca...")
            QApplication.processEvents()
            hsg_path = landcover_soils.obtener_hsg_recortado(ruta_hsg, self.cuenca_layer, context, feedback)

            self.lbl_estado_cn_auto.setText("Estado: cruzando LULC x HSG y ponderando el CN...")
            QApplication.processEvents()
            resultado = landcover_soils.calcular_cn_ponderado_automatico(lulc_path, hsg_path)

            self.tabla_desglose_cn_auto.setRowCount(0)
            for fila in resultado["desglose"]:
                r = self.tabla_desglose_cn_auto.rowCount()
                self.tabla_desglose_cn_auto.insertRow(r)
                self.tabla_desglose_cn_auto.setItem(r, 0, QTableWidgetItem(fila["lulc_nombre"]))
                self.tabla_desglose_cn_auto.setItem(r, 1, QTableWidgetItem(fila["hsg"]))
                self.tabla_desglose_cn_auto.setItem(r, 2, QTableWidgetItem(str(fila["area_km2"])))
                self.tabla_desglose_cn_auto.setItem(r, 3, QTableWidgetItem(str(fila["cn"])))
            ajustar_alto_tabla(self.tabla_desglose_cn_auto, filas_visibles_max=10)

            cn_ii = resultado["cn_ii_ponderado"]
            amc = curve_number.condiciones_amc(cn_ii)
            self.cn_resultados = amc
            self.tabla_amc.setItem(0, 0, QTableWidgetItem(str(amc["CN_I"])))
            self.tabla_amc.setItem(0, 1, QTableWidgetItem(str(amc["CN_II"])))
            self.tabla_amc.setItem(0, 2, QTableWidgetItem(str(amc["CN_III"])))
            self.tabla_amc.setItem(0, 3, QTableWidgetItem(str(amc["S_mm"])))
            self.tabla_amc.setItem(0, 4, QTableWidgetItem(str(amc["Ia_mm"])))

            self.lbl_estado_cn_auto.setText(
                f"Estado: CN_II ponderado = {cn_ii} (área total cruzada: {resultado['area_total_km2']} km², "
                f"{len(resultado['desglose'])} combinaciones LULC x HSG)."
            )
        except Exception as e:
            self.lbl_estado_cn_auto.setText("Estado: error (ver mensaje).")
            QMessageBox.critical(self, "Error obteniendo CN automático", str(e))

    def _on_distribuir_area_por_porcentaje(self):
        """
        Lee el % de la cuenca asignado a cada uso de suelo (columna "%
        cuenca") y calcula el Área (km²) de cada fila como
        Área_total_pestaña2 * % / 100, sobrescribiendo la columna "Área
        (km²)". El Área total se toma de self.morfometria_resultados
        (Grupo 1, calculado en la Pestaña 2) -- si todavía no se calculó
        la morfometría, se avisa y no se hace nada.
        """
        g1 = self.morfometria_resultados.get("g1") if self.morfometria_resultados else None
        if not g1:
            QMessageBox.warning(
                self, "Falta el área de la cuenca",
                "Calcule primero los parámetros morfométricos en la Pestaña 2 (Grupo 1: Área de la "
                "cuenca) antes de distribuir el área por porcentaje aquí."
            )
            return
        area_total_km2 = g1["A"]
        try:
            suma_pct = 0.0
            for row in range(self.tabla_cn.rowCount()):
                item_pct = self.tabla_cn.item(row, 5)
                texto_pct = item_pct.text().strip() if item_pct else ""
                pct = float(texto_pct) if texto_pct else 0.0
                suma_pct += pct
                area_fila = area_total_km2 * pct / 100.0
                self.tabla_cn.setItem(row, 6, QTableWidgetItem(f"{area_fila:.4f}"))
        except ValueError as e:
            QMessageBox.critical(self, "Error en la columna \"% cuenca\"",
                                  f"Revise que todas las celdas de % tengan valores numéricos válidos.\n{e}")
            return

        aviso_suma = ""
        if abs(suma_pct - 100.0) > 1.0:
            aviso_suma = f" Atención: los % ingresados suman {suma_pct:.1f}%, no 100% -- revise la matriz."
        self.lbl_estado_distribucion_pct.setText(
            f"Área distribuida: {area_total_km2:.4f} km² (Pestaña 2) repartida según el % de cada fila "
            f"(suma de %: {suma_pct:.1f}%).{aviso_suma}"
        )

    def _on_calcular_cn(self):
        try:
            usos = []
            for row in range(self.tabla_cn.rowCount()):
                nombre = self.tabla_cn.item(row, 0).text()
                cn_a = int(self.tabla_cn.item(row, 1).text())
                cn_b = int(self.tabla_cn.item(row, 2).text())
                cn_c = int(self.tabla_cn.item(row, 3).text())
                cn_d = int(self.tabla_cn.item(row, 4).text())
                area = float(self.tabla_cn.item(row, 6).text())
                usos.append(curve_number.UsoSuelo(nombre, cn_a, cn_b, cn_c, cn_d, area))

            grupo = self.combo_grupo_hidrologico.currentText()
            cn_ii = curve_number.cn_ponderado(usos, grupo)
            resultado = curve_number.condiciones_amc(cn_ii)
            self.cn_resultados = resultado

            self.tabla_amc.setItem(0, 0, QTableWidgetItem(str(resultado["CN_I"])))
            self.tabla_amc.setItem(0, 1, QTableWidgetItem(str(resultado["CN_II"])))
            self.tabla_amc.setItem(0, 2, QTableWidgetItem(str(resultado["CN_III"])))
            self.tabla_amc.setItem(0, 3, QTableWidgetItem(str(resultado["S_mm"])))
            self.tabla_amc.setItem(0, 4, QTableWidgetItem(str(resultado["Ia_mm"])))

        except (ValueError, AttributeError) as e:
            QMessageBox.critical(self, "Error en la tabla de usos de suelo",
                                  f"Revise que todas las celdas de CN y área tengan valores numéricos válidos.\n{e}")
        except Exception as e:
            QMessageBox.critical(self, "Error calculando el número de curva", str(e))

    # ------------------------------------------------------------------
    # TAB 4: Hydraulics & Tc
    # ------------------------------------------------------------------
    def _build_tab4(self):
        tab = QWidget()
        v = QVBoxLayout(tab)

        h_top = QHBoxLayout()
        self.spin_s_cuenca_pct = QDoubleSpinBox()
        self.spin_s_cuenca_pct.setRange(0.01, 200)
        self.spin_s_cuenca_pct.setDecimals(2)
        h_top.addWidget(QLabel("Pendiente media de la cuenca (%) [Grupo 4]:"))
        h_top.addWidget(self.spin_s_cuenca_pct)
        lbl_auto_s = QLabel("(se autocompleta desde el MDE recortado al presionar \"Calcular\"; edite si lo desea)")
        lbl_auto_s.setStyleSheet("color: #666; font-size: 9px;")
        h_top.addWidget(lbl_auto_s)

        self.spin_coef_c = QDoubleSpinBox()
        self.spin_coef_c.setRange(0.0, 1.0)
        self.spin_coef_c.setSingleStep(0.05)
        self.spin_coef_c.setValue(0.5)
        h_top.addWidget(QLabel("Coef. de escorrentía C (solo método FAA):"))
        h_top.addWidget(self.spin_coef_c)

        self.btn_calc_tc = QPushButton("Calcular todos los métodos de Tc")
        self.btn_calc_tc.clicked.connect(self._on_calcular_tc)
        h_top.addWidget(self.btn_calc_tc)
        v.addLayout(h_top)

        gb_extra = QGroupBox(
            "Parámetros adicionales de métodos específicos (antes fijos en el código; "
            "ahora editables — esto es lo que corrige que varios métodos calcularan Tc=0 "
            "o valores no representativos por usar siempre un valor por defecto)"
        )
        f_extra = QFormLayout(gb_extra)

        f_extra.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.spin_n_kerby = QDoubleSpinBox()
        self.spin_n_kerby.setRange(0.02, 0.8)
        self.spin_n_kerby.setDecimals(3)
        self.spin_n_kerby.setValue(0.4)
        f_extra.addRow("Kerby — coef. de rugosidad n (superficie del tramo laminar):", self.spin_n_kerby)

        self.spin_l_overland_km = QDoubleSpinBox()
        self.spin_l_overland_km.setRange(0.0, 50.0)
        self.spin_l_overland_km.setDecimals(3)
        self.spin_l_overland_km.setSpecialValueText("(usar Lc completo)")
        f_extra.addRow("Kerby — long. de flujo laminar inicial L (km, 0 = usar Lc):", self.spin_l_overland_km)

        self.spin_lca_km = QDoubleSpinBox()
        self.spin_lca_km.setRange(0.0, 200.0)
        self.spin_lca_km.setDecimals(3)
        self.spin_lca_km.setSpecialValueText("(usar 0.5 * Lc)")
        f_extra.addRow("Snyder — distancia al centroide Lca (km, 0 = usar 0.5*Lc):", self.spin_lca_km)

        self.spin_ct_snyder = QDoubleSpinBox()
        self.spin_ct_snyder.setRange(0.5, 8.0)
        self.spin_ct_snyder.setDecimals(2)
        self.spin_ct_snyder.setValue(2.0)
        f_extra.addRow("Snyder — coeficiente Ct (1.8-2.2 típico EE.UU.; calibrar):", self.spin_ct_snyder)

        self.spin_phi_espey = QDoubleSpinBox()
        self.spin_phi_espey.setRange(0.3, 2.0)
        self.spin_phi_espey.setDecimals(2)
        self.spin_phi_espey.setValue(0.8)
        f_extra.addRow("Espey-Winslow — factor de canalización phi (0.6 natural - 1.3 revestido):", self.spin_phi_espey)

        self.spin_area_imperm = QDoubleSpinBox()
        self.spin_area_imperm.setRange(0.01, 1.0)
        self.spin_area_imperm.setDecimals(2)
        self.spin_area_imperm.setValue(0.10)
        f_extra.addRow("Espey-Winslow — fracción impermeable de la cuenca (0-1):", self.spin_area_imperm)

        self.spin_alpha_vh = QDoubleSpinBox()
        self.spin_alpha_vh.setRange(0.001, 1.0)
        self.spin_alpha_vh.setDecimals(3)
        self.spin_alpha_vh.setValue(0.04)
        f_extra.addRow("Ventura-Heras — coeficiente alpha (varía según fuente):", self.spin_alpha_vh)

        self.spin_intensidad_izzard = QDoubleSpinBox()
        self.spin_intensidad_izzard.setRange(1.0, 300.0)
        self.spin_intensidad_izzard.setValue(40.0)
        f_extra.addRow("Izzard — intensidad de lluvia de diseño (mm/h):", self.spin_intensidad_izzard)

        self.spin_retardo_izzard = QDoubleSpinBox()
        self.spin_retardo_izzard.setRange(0.007, 0.06)
        self.spin_retardo_izzard.setDecimals(3)
        self.spin_retardo_izzard.setValue(0.06)
        f_extra.addRow("Izzard — coef. de retardo (0.007 pavimento liso - 0.06 pastos densos):", self.spin_retardo_izzard)

        self.spin_p2_24h = QDoubleSpinBox()
        self.spin_p2_24h.setRange(1.0, 300.0)
        self.spin_p2_24h.setValue(35.0)
        f_extra.addRow("Onda Cinemática — precipitación de 2 años-24h P2 (mm):", self.spin_p2_24h)

        self.spin_n_manning_sheet = QDoubleSpinBox()
        self.spin_n_manning_sheet.setRange(0.01, 0.8)
        self.spin_n_manning_sheet.setDecimals(3)
        self.spin_n_manning_sheet.setValue(0.15)
        f_extra.addRow("Onda Cinemática — n de Manning para flujo laminar (TR-55):", self.spin_n_manning_sheet)

        v.addWidget(gb_extra)

        self.tabla_tc = QTableWidget(0, 6)
        self.tabla_tc.setHorizontalHeaderLabels(
            ["Adoptar", "Método", "Autor/Año", "Tc (h)", "Tc (min)", "tlag SCS (min)"]
        )
        # Antes las 6 columnas estaban en modo Stretch parejo, lo que
        # dejaba "Adoptar"/"Tc (h)"/"Tc (min)"/"tlag SCS (min)" (textos
        # cortos) desproporcionadamente anchas y "Método"/"Autor/Año"
        # (los textos más largos) apretadas. Ahora solo Método y
        # Autor/Año están en Stretch (se reparten el espacio sobrante);
        # el resto tiene un ancho fijo angosto acorde a su contenido.
        cabecera_tc = self.tabla_tc.horizontalHeader()
        cabecera_tc.setSectionResizeMode(0, QHeaderView.Fixed)
        cabecera_tc.setSectionResizeMode(1, QHeaderView.Stretch)
        cabecera_tc.setSectionResizeMode(2, QHeaderView.Stretch)
        cabecera_tc.setSectionResizeMode(3, QHeaderView.Fixed)
        cabecera_tc.setSectionResizeMode(4, QHeaderView.Fixed)
        cabecera_tc.setSectionResizeMode(5, QHeaderView.Fixed)
        self.tabla_tc.setColumnWidth(0, 60)
        self.tabla_tc.setColumnWidth(3, 70)
        self.tabla_tc.setColumnWidth(4, 75)
        self.tabla_tc.setColumnWidth(5, 95)
        # Antes la tabla quedaba con la altura por defecto de Qt (~5-6 filas
        # visibles) y había que hacer scroll DENTRO de la tabla además del
        # scroll de la pestaña, para ver los 14 métodos. Se fija una altura
        # que alcanza para mostrarlos todos de una vez.
        self.tabla_tc.setMinimumHeight(260)
        self.tabla_tc.verticalHeader().setDefaultSectionSize(24)
        v.addWidget(self.tabla_tc)
        self.grupo_radio_metodo = QButtonGroup(self)

        _lbl_auto_3 = QLabel(
            "Curva hipsométrica (Grupo 4) — eje X: % de área acumulada de la cuenca; "
            "eje Y: altitud real (m s.n.m.). Curva suavizada (interpolación monótona) "
            "para una lectura de alto impacto visual."
        )
        _lbl_auto_3.setWordWrap(True)
        v.addWidget(_lbl_auto_3)
        self.canvas_hipsometrica = HypsometricCanvas(self, width=6, height=4.6)
        v.addWidget(self.canvas_hipsometrica)

        v.addWidget(QLabel("Tabla resumen — altitud (m s.n.m.) interpolada cada 10% de área acumulada:"))
        self.tabla_resumen_hipsometrica = QTableWidget(2, 11)
        self.tabla_resumen_hipsometrica.setVerticalHeaderLabels(["Área acum. (%)", "Altitud (m s.n.m.)"])
        self.tabla_resumen_hipsometrica.setHorizontalHeaderLabels([str(p) for p in range(0, 101, 10)])
        self.tabla_resumen_hipsometrica.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla_resumen_hipsometrica.setMaximumHeight(90)
        for col, pct in enumerate(range(0, 101, 10)):
            self.tabla_resumen_hipsometrica.setItem(0, col, QTableWidgetItem(str(pct)))
        v.addWidget(self.tabla_resumen_hipsometrica)

        gb_cav = QGroupBox(
            "Curva Cota-Área-Volumen (C-A-V) — típica de estudios de embalses/presas, calculada "
            "sobre el mismo MDE recortado a la cuenca"
        )
        v_cav = QVBoxLayout(gb_cav)
        h_cav = QHBoxLayout()
        self.spin_cav_n_niveles = QSpinBox()
        self.spin_cav_n_niveles.setRange(5, 100)
        self.spin_cav_n_niveles.setValue(30)
        h_cav.addWidget(QLabel("N° de niveles de cota:"))
        h_cav.addWidget(self.spin_cav_n_niveles)
        self.btn_calcular_cav = QPushButton("Calcular curva C-A-V")
        self.btn_calcular_cav.clicked.connect(self._on_calcular_cav)
        h_cav.addWidget(self.btn_calcular_cav)
        v_cav.addLayout(h_cav)
        self.lbl_resultado_cav = QLabel("Resultado: sin calcular.")
        self.lbl_resultado_cav.setWordWrap(True)
        v_cav.addWidget(self.lbl_resultado_cav)
        self.canvas_cav = CavCanvas(self)
        v_cav.addWidget(self.canvas_cav)
        v.addWidget(gb_cav)

        _lbl_auto_4 = QLabel(
            "Nota: la exportación de la curva hipsométrica y de todos los demás resultados (todos "
            "los formatos, reporte Word y proyecto portable) se centralizó en la pestaña "
            "\"Exportar / Reportes\", justo antes de Créditos."
        )
        _lbl_auto_4.setWordWrap(True)
        v.addWidget(_lbl_auto_4)

        self._agregar_pestaña_con_scroll(tab, "4. Tiempo de concentración y Lag Time")

    def _on_calcular_cav(self):
        if not self.dem_clip_path:
            QMessageBox.warning(self, "Falta el MDE recortado",
                                 "Ejecute primero la delimitación (pestaña 1) y calcule la morfometría (pestaña 2).")
            return
        try:
            z_array = raster_stats.leer_array_valido(self.dem_clip_path)
            capa_dem = QgsRasterLayer(self.dem_clip_path, "dem_clip")
            pixel_area_m2 = abs(capa_dem.rasterUnitsPerPixelX() * capa_dem.rasterUnitsPerPixelY())
            resultado = morphometry.curva_cota_area_volumen(
                z_array, pixel_area_m2, n_niveles=self.spin_cav_n_niveles.value()
            )
            self.resultado_cav = resultado
            self.canvas_cav.plot_cav(resultado["curva"])
            self.lbl_resultado_cav.setText(
                f"Cota mín. = {resultado['z_min']} m s.n.m.   Cota máx. = {resultado['z_max']} m s.n.m.\n"
                f"Área total = {resultado['area_total_m2'] / 1e6:.4f} km²   "
                f"Volumen total embalsable = {resultado['volumen_total_m3'] / 1e6:.4f} hm³\n"
                f"{resultado['nota']}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Error calculando la curva C-A-V", str(e))

    def _on_exportar_hipsometrica(self):
        ruta, _ = QFileDialog.getSaveFileName(self, "Exportar curva hipsométrica", "curva_hipsometrica.png",
                                               "Imagen PNG (*.png)")
        if not ruta:
            return
        try:
            self.canvas_hipsometrica.guardar_figura(ruta)
            QMessageBox.information(self, "Exportado", f"Curva hipsométrica guardada en:\n{ruta}")
        except Exception as e:
            QMessageBox.critical(self, "Error exportando la curva hipsométrica", str(e))

    def _on_calcular_tc(self):
        if not self.morfometria_resultados:
            QMessageBox.warning(self, "Falta la morfometría",
                                 "Calcule primero los parámetros morfométricos en la pestaña 2.")
            return
        try:
            g1 = self.morfometria_resultados["g1"]

            # Grupos 3 (cauce principal) y 4 (pendiente de cuenca +
            # hipsometría): cálculo compartido con la Pestaña 2 (ver
            # _calcular_g3_g4). Se recalculan aquí en vez de reutilizar los
            # que ya haya guardado la Pestaña 2, para reflejar de inmediato
            # cualquier cambio hecho en la Pestaña 1 desde entonces.
            g3, g4 = self._calcular_g3_g4(g1)

            if g4 is not None:
                self.morfometria_resultados["g4"] = g4
                self.spin_s_cuenca_pct.setValue(g4["S_cuenca_pct"])
                self.canvas_hipsometrica.plot_curva(g4["curva_hipsometrica"])

                # Tabla resumen: altitud interpolada cada 10% de área acumulada
                datos_curva = sorted(g4["curva_hipsometrica"], key=lambda d: d["area_acumulada_pct"])
                xs = [d["area_acumulada_pct"] for d in datos_curva]
                ys = [d["elevacion_m"] for d in datos_curva]
                for col, pct in enumerate(range(0, 101, 10)):
                    altitud_interp = float(np.interp(pct, xs, ys))
                    self.tabla_resumen_hipsometrica.setItem(1, col, QTableWidgetItem(f"{altitud_interp:.1f}"))

            # Si el perfil real no estuvo disponible (g3 es None), se cae de
            # vuelta a la aproximación Se = H/Lc, con Lc = el ingresado
            # manualmente en la pestaña 2 (mismo respaldo que antes).
            lc_km_usado = self.morfometria_resultados["lc_km"]
            if g3 is not None:
                self.morfometria_resultados["g3"] = g3
                se_real, s1085_real = g3["Se"], g3["S10_85"]
                # Se usa también la longitud REAL del cauce extraída
                # automáticamente (consistente con Se/S10-85, ambas medidas
                # sobre el mismo perfil), en vez del valor ingresado
                # manualmente en la pestaña 2, que puede diferir y producir
                # resultados inconsistentes entre métodos que usan Lc y
                # métodos que usan Se/S10-85.
                lc_km_usado = g3["Lc"]
            else:
                se_real = g1["H"] / (lc_km_usado * 1000.0)
                s1085_real = se_real

            l_overland_km = self.spin_l_overland_km.value() or None
            lca_km = self.spin_lca_km.value() or None

            params = tc_methods.ParametrosCuenca(
                lc_km=lc_km_usado,
                se=se_real,
                s1085=s1085_real,
                area_km2=g1["A"],
                h_m=g1["H"],
                z_med=g1["Zmed"],
                z_min=g1["Zmin"],
                s_cuenca_pct=self.spin_s_cuenca_pct.value(),
                s_mm=self.cn_resultados["S_mm"] if self.cn_resultados else None,
                coef_escorrentia_c=self.spin_coef_c.value(),
                n_kerby=self.spin_n_kerby.value(),
                l_overland_km=l_overland_km,
                lca_km=lca_km,
                ct_snyder=self.spin_ct_snyder.value(),
                phi_espey=self.spin_phi_espey.value(),
                area_impermeable_frac=self.spin_area_imperm.value(),
                alpha_ventura_heras=self.spin_alpha_vh.value(),
                intensidad_lluvia_mm_h=self.spin_intensidad_izzard.value(),
                coef_retardo_izzard=self.spin_retardo_izzard.value(),
                p2_24h_mm=self.spin_p2_24h.value(),
                manning_n_sheet_flow=self.spin_n_manning_sheet.value(),
            )
            resultados = tc_methods.calcular_todos(params)
            self.tc_resultados = resultados

            self.tabla_tc.setRowCount(0)
            for nombre, datos in resultados.items():
                row = self.tabla_tc.rowCount()
                self.tabla_tc.insertRow(row)

                radio = QRadioButton()
                self.grupo_radio_metodo.addButton(radio, row)
                if "Témez" in nombre:
                    radio.setChecked(True)  # método recomendado por defecto (ANA/MTC Perú)
                self.tabla_tc.setCellWidget(row, 0, radio)

                self.tabla_tc.setItem(row, 1, QTableWidgetItem(nombre))
                self.tabla_tc.setItem(row, 2, QTableWidgetItem(datos["autor_anio"]))
                if datos["error"]:
                    self.tabla_tc.setItem(row, 3, QTableWidgetItem(f"ERROR: {datos['error']}"))
                    self.tabla_tc.setItem(row, 4, QTableWidgetItem(""))
                    self.tabla_tc.setItem(row, 5, QTableWidgetItem(""))
                else:
                    self.tabla_tc.setItem(row, 3, QTableWidgetItem(str(datos["Tc_horas"])))
                    self.tabla_tc.setItem(row, 4, QTableWidgetItem(str(datos["Tc_min"])))
                    self.tabla_tc.setItem(row, 5, QTableWidgetItem(str(datos["tlag_min"])))

        except Exception as e:
            QMessageBox.critical(self, "Error calculando Tc", str(e))

    # ------------------------------------------------------------------
    # TAB 5 (nueva): Precipitación Máxima 24h - análisis de frecuencia
    # ------------------------------------------------------------------
    def _build_tab_precipitacion(self):
        tab = QWidget()
        v = QVBoxLayout(tab)

        _lbl_auto_5 = QLabel(
            "Análisis de frecuencia de precipitación máxima en 24 horas: ajuste de distribuciones "
            "de probabilidad (Normal, Log-Normal, Gumbel, Log-Pearson III, GEV), prueba de bondad "
            "de ajuste de Kolmogorov-Smirnov, y precipitaciones de diseño para Tr = 2 a 1000 años. "
            "El resultado se enlaza automáticamente a la pestaña 6 para generar caudales máximos."
        )
        _lbl_auto_5.setWordWrap(True)
        v.addWidget(_lbl_auto_5)

        gb_fuente = QGroupBox("1. Fuente de datos: serie de máximos anuales P24h")
        f = QFormLayout(gb_fuente)

        f.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        h_csv = QHBoxLayout()
        self.edit_csv_serie = QLineEdit()
        self.edit_csv_serie.setPlaceholderText("Ruta a CSV con columnas 'anio' y 'p24_mm'")
        h_csv.addWidget(self.edit_csv_serie)
        btn_csv = QPushButton("Examinar...")
        btn_csv.clicked.connect(self._on_examinar_csv_serie)
        h_csv.addWidget(btn_csv)
        btn_cargar_csv = QPushButton("Cargar serie CSV")
        btn_cargar_csv.clicked.connect(self._on_cargar_serie_csv)
        h_csv.addWidget(btn_cargar_csv)
        f.addRow("Serie manual (SENAMHI u otra fuente):", h_csv)

        h_pisco = QHBoxLayout()
        self.edit_nc_path = QLineEdit()
        self.edit_nc_path.setPlaceholderText("Ruta a archivo NetCDF de PISCOp ya descargado")
        h_pisco.addWidget(self.edit_nc_path)
        btn_nc = QPushButton("Examinar...")
        btn_nc.clicked.connect(self._on_examinar_netcdf)
        h_pisco.addWidget(btn_nc)
        btn_cargar_nc = QPushButton("Extraer serie del píxel")
        btn_cargar_nc.clicked.connect(self._on_cargar_serie_pisco)
        h_pisco.addWidget(btn_cargar_nc)
        f.addRow("PISCOp (NetCDF descargado manualmente):", h_pisco)

        link_pisco = QTextBrowser()
        link_pisco.setOpenExternalLinks(True)
        link_pisco.setMaximumHeight(40)
        link_pisco.setHtml(
            '<a href="https://figshare.com/articles/dataset/High-resolution_grids_of_rainfall_for_Peru_-_PISCOp_v3_0_dataset/32411886">'
            "Descargar PISCOp v3.0 desde Figshare</a> (descarga manual; la página no permite "
            "descarga automática programática desde este plugin — ver nota en core/precip_source.py)."
        )
        f.addRow(link_pisco)

        self.lbl_estado_serie = QLabel("Estado: sin serie cargada.")
        f.addRow(self.lbl_estado_serie)
        v.addWidget(gb_fuente)

        gb_manual = QGroupBox("1b. O ingrese/pegue los datos directamente en esta tabla")
        v_manual = QVBoxLayout(gb_manual)
        _lbl_auto_6 = QLabel(
            "Escriba año y P24 (mm) en cada fila, o copie un rango de dos columnas desde Excel/LibreOffice "
            "y péguelo aquí con Ctrl+V (haga clic primero en la celda donde debe empezar el pegado)."
        )
        _lbl_auto_6.setWordWrap(True)
        v_manual.addWidget(_lbl_auto_6)

        self.tabla_entrada_manual = TablaPegable(30, 2)
        self.tabla_entrada_manual.setHorizontalHeaderLabels(["Año", "P24 (mm)"])
        # Antes: modo Stretch en una tabla de solo 2 columnas quedaba muy
        # ancha/descuadrada al ocupar todo el ancho de la pestaña. Se fija
        # un ancho de columna razonable y se limita el ancho total de la
        # tabla, en vez de estirarla a todo el contenedor.
        self.tabla_entrada_manual.horizontalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.tabla_entrada_manual.setColumnWidth(0, 90)
        self.tabla_entrada_manual.setColumnWidth(1, 110)
        self.tabla_entrada_manual.setMaximumWidth(230)
        # Antes la altura estaba limitada a 220 px (~9 filas visibles),
        # obligando a hacer scroll DENTRO de la tabla además del scroll de
        # la pestaña para revisar las 30 filas. Como la pestaña completa ya
        # se desplaza verticalmente, se le da a la tabla una altura que
        # alcanza para las 30 filas de una sola vez.
        self.tabla_entrada_manual.setMinimumHeight(360)
        self.tabla_entrada_manual.setMaximumHeight(16777215)  # sin límite (por defecto de Qt)
        v_manual.addWidget(self.tabla_entrada_manual)

        h_botones_tabla = QHBoxLayout()
        btn_agregar_fila = QPushButton("Agregar fila")
        btn_agregar_fila.clicked.connect(lambda: self.tabla_entrada_manual.setRowCount(self.tabla_entrada_manual.rowCount() + 1))
        h_botones_tabla.addWidget(btn_agregar_fila)

        btn_quitar_fila = QPushButton("Quitar fila seleccionada")
        btn_quitar_fila.clicked.connect(self._on_quitar_fila_tabla_manual)
        h_botones_tabla.addWidget(btn_quitar_fila)

        btn_limpiar_tabla = QPushButton("Limpiar tabla")
        btn_limpiar_tabla.clicked.connect(lambda: self.tabla_entrada_manual.clearContents())
        h_botones_tabla.addWidget(btn_limpiar_tabla)

        btn_usar_tabla = QPushButton("Usar datos de esta tabla")
        btn_usar_tabla.clicked.connect(self._on_usar_serie_manual)
        h_botones_tabla.addWidget(btn_usar_tabla)

        v_manual.addLayout(h_botones_tabla)
        v.addWidget(gb_manual)

        _lbl_auto_7 = QLabel(
            "Nota: el control de calidad y homogeneidad (Pettitt, Mann-Kendall, etc.) y la PMP de "
            "Hershfield se movieron a la nueva pestaña \"6. Precipitación Media Mensual\"."
        )
        _lbl_auto_7.setWordWrap(True)
        v.addWidget(_lbl_auto_7)

        gb_analisis = QGroupBox("2. Análisis de frecuencia")
        h_a = QHBoxLayout(gb_analisis)
        self.combo_alpha_ks = QComboBox()
        self.combo_alpha_ks.addItems(["0.10", "0.05", "0.01"])
        self.combo_alpha_ks.setCurrentText("0.05")
        h_a.addWidget(QLabel("Nivel de significancia KS (alpha):"))
        h_a.addWidget(self.combo_alpha_ks)
        self.btn_analizar_frecuencia = QPushButton("Ajustar distribuciones y calcular precipitaciones de diseño")
        self.btn_analizar_frecuencia.clicked.connect(self._on_analizar_frecuencia)
        h_a.addWidget(self.btn_analizar_frecuencia)
        v.addWidget(gb_analisis)

        self.tabla_distribuciones = QTableWidget(0, 5)
        self.tabla_distribuciones.setHorizontalHeaderLabels(
            ["Distribución", "Parámetros", "D (KS)", "D crítico", "¿Pasa KS?"]
        )
        # Antes las 5 columnas estaban en modo Stretch parejo, lo que
        # dejaba D(KS)/D crítico/¿Pasa KS? (textos cortos) demasiado
        # anchas y obligaba a usar scroll horizontal para ver "Parámetros"
        # completo. Ahora solo "Parámetros" se lleva el espacio sobrante;
        # el resto tiene un ancho fijo angosto acorde a su contenido.
        cabecera_dist = self.tabla_distribuciones.horizontalHeader()
        cabecera_dist.setSectionResizeMode(0, QHeaderView.Interactive)
        cabecera_dist.setSectionResizeMode(1, QHeaderView.Stretch)
        cabecera_dist.setSectionResizeMode(2, QHeaderView.Fixed)
        cabecera_dist.setSectionResizeMode(3, QHeaderView.Fixed)
        cabecera_dist.setSectionResizeMode(4, QHeaderView.Fixed)
        self.tabla_distribuciones.setColumnWidth(0, 220)
        self.tabla_distribuciones.setColumnWidth(2, 80)
        self.tabla_distribuciones.setColumnWidth(3, 80)
        self.tabla_distribuciones.setColumnWidth(4, 80)
        v.addWidget(self.tabla_distribuciones)

        self.canvas_frecuencia = FrequencyCanvas(self, width=6.5, height=4.8)
        v.addWidget(self.canvas_frecuencia)

        self.tabla_p24_tr = QTableWidget(1, len(frequency_analysis.PERIODOS_RETORNO_DEFAULT))
        self.tabla_p24_tr.setVerticalHeaderLabels(["P24 diseño (mm)"])
        self.tabla_p24_tr.setHorizontalHeaderLabels([f"Tr={tr}a" for tr in frequency_analysis.PERIODOS_RETORNO_DEFAULT])
        self.tabla_p24_tr.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla_p24_tr.setMaximumHeight(70)
        v.addWidget(self.tabla_p24_tr)

        gb_tdis = QGroupBox('"T - Diseño": periodo de retorno electivo (alternativa si el que necesita no está en la lista predeterminada)')
        h_tdis = QHBoxLayout(gb_tdis)
        self.spin_t_disenio = QSpinBox()
        self.spin_t_disenio.setRange(2, 10000)
        self.spin_t_disenio.setValue(140)
        h_tdis.addWidget(QLabel("Tr personalizado (años):"))
        h_tdis.addWidget(self.spin_t_disenio)
        self.btn_agregar_t_disenio = QPushButton("Calcular y agregar a las tablas/pestaña 6")
        self.btn_agregar_t_disenio.clicked.connect(self._on_agregar_t_disenio)
        h_tdis.addWidget(self.btn_agregar_t_disenio)
        v.addWidget(gb_tdis)

        _lbl_auto_8 = QLabel(
            "3. Comparación entre distribuciones — Pmax 24h (mm) vs. periodo de retorno Tr, para "
            "TODAS las distribuciones ajustadas (incluido cualquier T-Diseño agregado arriba). "
            "Use esta tabla y el gráfico para comparar las magnitudes entre distribuciones y decidir, "
            "con criterio hidrológico además del puramente estadístico (KS), cuál adoptar para el "
            "caudal máximo de diseño."
        )
        _lbl_auto_8.setWordWrap(True)
        v.addWidget(_lbl_auto_8)
        self.tabla_comparacion_distribuciones = QTableWidget(0, 0)
        v.addWidget(self.tabla_comparacion_distribuciones)

        self.canvas_comparacion_tr = FrequencyCanvas(self, width=6.5, height=4.8)
        v.addWidget(self.canvas_comparacion_tr)

        _lbl_auto_9 = QLabel(
            "Mismo gráfico anterior, pero con el eje de periodo de retorno en escala cartesiana "
            "(lineal) en vez de logarítmica:"
        )
        _lbl_auto_9.setWordWrap(True)
        v.addWidget(_lbl_auto_9)
        self.canvas_comparacion_tr_cartesiano = FrequencyCanvas(self, width=6.5, height=4.8)
        v.addWidget(self.canvas_comparacion_tr_cartesiano)

        self._agregar_pestaña_con_scroll(tab, "5. Precipitación Máx 24h")

    def _on_examinar_csv_serie(self):
        ruta, _ = QFileDialog.getOpenFileName(self, "Seleccionar CSV de serie anual", "", "CSV (*.csv)")
        if ruta:
            self.edit_csv_serie.setText(ruta)

    def _on_examinar_netcdf(self):
        ruta, _ = QFileDialog.getOpenFileName(self, "Seleccionar NetCDF de PISCOp", "", "NetCDF (*.nc)")
        if ruta:
            self.edit_nc_path.setText(ruta)

    def _on_cargar_serie_csv(self):
        ruta = self.edit_csv_serie.text().strip()
        if not ruta or not os.path.exists(ruta):
            QMessageBox.warning(self, "Ruta inválida", "Seleccione un archivo CSV válido.")
            return
        try:
            serie = precip_source.cargar_csv_serie_anual(ruta)
            self.serie_precip_anual = serie
            self.lbl_estado_serie.setText(
                f"Estado: serie cargada ({len(serie.valores_mm)} años, {min(serie.anios)}-{max(serie.anios)}). "
                f"Fuente: {serie.fuente}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Error cargando la serie CSV", str(e))

    def _on_cargar_serie_pisco(self):
        ruta = self.edit_nc_path.text().strip()
        if not ruta or not os.path.exists(ruta):
            QMessageBox.warning(self, "Ruta inválida", "Seleccione un archivo NetCDF válido.")
            return
        if self.break_point_lonlat is None:
            QMessageBox.warning(self, "Falta el break point",
                                 "Seleccione primero el punto de salida en la pestaña 1 (se usa su coordenada "
                                 "lon/lat para extraer el píxel de PISCOp más cercano).")
            return
        try:
            lon, lat = self.break_point_lonlat
            serie = precip_source.extraer_serie_anual_desde_netcdf(ruta, lon, lat)
            self.serie_precip_anual = serie
            self.lbl_estado_serie.setText(
                f"Estado: serie extraída de PISCOp ({len(serie.valores_mm)} años, "
                f"{min(serie.anios)}-{max(serie.anios)}). Fuente: {serie.fuente}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Error extrayendo del NetCDF", str(e))

    def _on_quitar_fila_tabla_manual(self):
        fila = self.tabla_entrada_manual.currentRow()
        if fila >= 0:
            self.tabla_entrada_manual.removeRow(fila)

    def _on_usar_serie_manual(self):
        try:
            filas_texto = []
            for fila in range(self.tabla_entrada_manual.rowCount()):
                item_anio = self.tabla_entrada_manual.item(fila, 0)
                item_valor = self.tabla_entrada_manual.item(fila, 1)
                filas_texto.append([
                    item_anio.text() if item_anio else "",
                    item_valor.text() if item_valor else "",
                ])
            serie = precip_source.construir_serie_desde_tabla(filas_texto)
            self.serie_precip_anual = serie
            self.lbl_estado_serie.setText(
                f"Estado: serie tomada de la tabla manual ({len(serie.valores_mm)} años, "
                f"{min(serie.anios)}-{max(serie.anios)})."
            )
        except Exception as e:
            QMessageBox.critical(self, "Error en la tabla de datos", str(e))

    def _obtener_serie_activa(self):
        if getattr(self, "serie_qc_activa", None):
            return self.serie_qc_activa
        if getattr(self, "serie_precip_anual", None):
            return self.serie_precip_anual.valores_mm
        QMessageBox.warning(self, "Falta la serie de datos",
                             "Cargue primero los datos en el paso 1 de esta pestaña (o una serie en la pestaña 5).")
        return None

    _CATEGORIAS_TEST = {
        "pettitt": "Cambio en media", "cusum": "Cambio en media", "buishand": "Cambio en media",
        "desviación acumulada": "Cambio en media", "worsley": "Cambio en media",
        "mann-kendall": "Tendencia", "spearman": "Tendencia", "regresión lineal": "Tendencia", "sen": "Tendencia",
        "rank-sum": "Diferencia 2 periodos", "t de student": "Diferencia 2 periodos",
        "mediana": "Aleatoriedad", "giro": "Aleatoriedad", "rangos": "Aleatoriedad", "autocorrelación": "Aleatoriedad",
        "doble masa": "Consistencia",
    }

    def _categoria_test(self, nombre: str) -> str:
        nombre_l = nombre.lower()
        for clave, categoria in self._CATEGORIAS_TEST.items():
            if clave in nombre_l:
                return categoria
        return "Otro"

    def _on_qc_generico(self, funcion_test, nombre: str):
        datos = self._obtener_serie_activa()
        if datos is None:
            return
        try:
            r = funcion_test(datos)
            texto = f"[{nombre}]\n" + "\n".join(f"  {k}: {v}" for k, v in r.items() if k != "nota")
            if "nota" in r:
                texto += f"\n  NOTA: {r['nota']}"
            self.lbl_resultado_qc.setText(texto)

            indice_marca = r.get("posicion_quiebre_candidata")
            linea_tendencia = None
            if "pendiente_por_periodo" in r and "intercepto" in r:
                linea_tendencia = (r["pendiente_por_periodo"], r["intercepto"])
            linea_horizontal, etiqueta_horizontal = None, ""
            if "mediana" in nombre.lower():
                linea_horizontal = float(np.median(datos))
                etiqueta_horizontal = "Mediana"

            self.canvas_qc.plot_serie_con_marca(
                datos, nombre, indice_marca=indice_marca,
                etiqueta_marca=f"Quiebre candidato (pos. {indice_marca})" if indice_marca else "",
                linea_tendencia=linea_tendencia, linea_horizontal=linea_horizontal,
                etiqueta_horizontal=etiqueta_horizontal,
            )

            clave_signif = next((k for k in r if "significativ" in k), None)
            estadistico_principal = ", ".join(
                f"{k}={v}" for k, v in r.items() if k in ("Z", "t", "S", "U_max", "Q", "Q_rescalado", "V_max", "rho", "r")
            )
            conclusion = "Sin dato"
            if clave_signif is not None:
                conclusion = "Significativo" if r[clave_signif] else "No significativo"
            self._agregar_fila_resumen_qc(nombre, self._categoria_test(nombre), estadistico_principal, conclusion)
        except quality_control.QualityControlError as e:
            QMessageBox.warning(self, "No se pudo calcular", str(e))

    def _on_qc_dos_periodos(self, funcion_test, nombre: str):
        datos = self._obtener_serie_activa()
        if datos is None:
            return
        try:
            mitad = len(datos) // 2
            periodo1, periodo2 = datos[:mitad], datos[mitad:]
            r = funcion_test(periodo1, periodo2)
            texto = (f"[{nombre}] (periodo 1: primeros {len(periodo1)} datos; "
                      f"periodo 2: últimos {len(periodo2)} datos)\n")
            texto += "\n".join(f"  {k}: {v}" for k, v in r.items())
            self.lbl_resultado_qc.setText(texto)

            self.canvas_qc.plot_dos_periodos(periodo1, periodo2, nombre)

            clave_signif = next((k for k in r if "significativ" in k), None)
            estadistico_principal = ", ".join(f"{k}={v}" for k, v in r.items() if k in ("Z", "t", "W"))
            conclusion = "Diferencia significativa" if clave_signif and r[clave_signif] else "Sin diferencia significativa"
            self._agregar_fila_resumen_qc(nombre, self._categoria_test(nombre), estadistico_principal, conclusion)
        except quality_control.QualityControlError as e:
            QMessageBox.warning(self, "No se pudo calcular", str(e))

    # ------------------------------------------------------------------
    # TAB 6: Precipitación Media Mensual (datos, completación/extensión,
    # control de calidad y homogeneidad, resumen)
    # ------------------------------------------------------------------
    def _build_tab_precipitacion_mensual(self):
        tab = QWidget()
        v = QVBoxLayout(tab)
        _lbl_auto_10 = QLabel(
            "<b>Precipitación Media Mensual</b> — ingreso de datos mensuales, completación/extensión "
            "de series, y control de calidad y homogeneidad (independiente de la serie de máximos "
            "anuales de la pestaña 5, aunque puede reutilizarla con el botón de abajo)."
        )
        _lbl_auto_10.setWordWrap(True)
        v.addWidget(_lbl_auto_10)

        gb_datos = QGroupBox("1. Datos de precipitación media mensual")
        v_datos = QVBoxLayout(gb_datos)
        _lbl_auto_11 = QLabel(
            "Una fila por año: columna Año + 12 columnas de meses (mm). Pegue directamente desde "
            "Excel/LibreOffice (Ctrl+V, haga clic primero en la celda donde debe empezar el pegado)."
        )
        _lbl_auto_11.setWordWrap(True)
        v_datos.addWidget(_lbl_auto_11)
        self.tabla_precip_mensual = TablaPegable(60, 13)
        self.tabla_precip_mensual.setHorizontalHeaderLabels(
            ["Año", "Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
        )
        self.tabla_precip_mensual.setMinimumHeight(300)
        v_datos.addWidget(self.tabla_precip_mensual)

        h_datos_btn = QHBoxLayout()
        btn_usar_tabla_mensual = QPushButton("Usar datos de esta tabla")
        btn_usar_tabla_mensual.clicked.connect(self._on_usar_tabla_precip_mensual)
        h_datos_btn.addWidget(btn_usar_tabla_mensual)
        btn_usar_serie_anual = QPushButton("(alternativa) Usar la serie anual ya cargada en la pestaña 5")
        btn_usar_serie_anual.clicked.connect(self._on_usar_serie_anual_como_qc)
        h_datos_btn.addWidget(btn_usar_serie_anual)
        v_datos.addLayout(h_datos_btn)

        self.lbl_estado_precip_mensual = QLabel("Estado: sin datos cargados.")
        v_datos.addWidget(self.lbl_estado_precip_mensual)
        v.addWidget(gb_datos)

        gb_completacion = QGroupBox("2. Completación y extensión de datos")
        v_comp = QVBoxLayout(gb_completacion)
        _lbl_auto_12 = QLabel(
            "Aplica sobre la serie mensual activa (paso 1). 'NaN' en la tabla se trata como dato "
            "faltante a completar."
        )
        _lbl_auto_12.setWordWrap(True)
        v_comp.addWidget(_lbl_auto_12)
        f_comp = QFormLayout()
        f_comp.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.spin_fourier_armonicos = QSpinBox(); self.spin_fourier_armonicos.setRange(1, 6); self.spin_fourier_armonicos.setValue(3)
        f_comp.addRow("N° de armónicos (Fourier):", self.spin_fourier_armonicos)
        self.spin_fourier_extension = QSpinBox(); self.spin_fourier_extension.setRange(0, 240); self.spin_fourier_extension.setValue(12)
        f_comp.addRow("Meses a extender hacia adelante (Fourier):", self.spin_fourier_extension)
        v_comp.addLayout(f_comp)
        h_comp_btn = QHBoxLayout()
        btn_fourier = QPushButton("Completar/extender por Fourier")
        btn_fourier.clicked.connect(self._on_completar_fourier)
        h_comp_btn.addWidget(btn_fourier)
        btn_wavelet = QPushButton("Completar por Wavelet")
        btn_wavelet.clicked.connect(self._on_completar_wavelet)
        h_comp_btn.addWidget(btn_wavelet)
        v_comp.addLayout(h_comp_btn)
        self.lbl_resultado_completacion_mensual = QLabel("Resultado: sin calcular.")
        self.lbl_resultado_completacion_mensual.setWordWrap(True)
        self.lbl_resultado_completacion_mensual.setStyleSheet("font-family: monospace;")
        v_comp.addWidget(self.lbl_resultado_completacion_mensual)
        v.addWidget(gb_completacion)

        gb_calidad = QGroupBox("3. Control de calidad y homogeneidad")
        v_cal = QVBoxLayout(gb_calidad)
        _lbl_auto_13 = QLabel(
            "Se aplica sobre la serie activa (paso 1, o la ya completada del paso 2). Cada test "
            "queda registrado en el cuadro resumen del final de la pestaña."
        )
        _lbl_auto_13.setWordWrap(True)
        v_cal.addWidget(_lbl_auto_13)
        h_cal_ref = QHBoxLayout()
        self.edit_serie_referencia_dm = QLineEdit()
        self.edit_serie_referencia_dm.setPlaceholderText(
            "Opcional, solo para Doble masa: valores de una serie de referencia separados por coma, "
            "misma longitud que la serie activa (p.ej. promedio de estaciones vecinas)."
        )
        h_cal_ref.addWidget(self.edit_serie_referencia_dm)
        v_cal.addLayout(h_cal_ref)

        v_cal.addWidget(QLabel("<b>① Quiebres de homogeneidad</b>"))
        h1 = QHBoxLayout()
        for etiqueta, slot in [("Pettitt", self._on_qc_pettitt), ("Distribución Free CUSUM", None),
                                 ("Cumulative Deviation", None), ("Worsley Likelihood Ratio", None),
                                 ("Doble masa", self._on_qc_doble_masa)]:
            btn = QPushButton(etiqueta)
            h1.addWidget(btn)
            if slot:
                btn.clicked.connect(slot)
        v_cal.addLayout(h1)
        # Reconectar explícitamente los botones de "cambio en media" (CUSUM/Buishand/Worsley)
        widgets_h1 = [h1.itemAt(i).widget() for i in range(h1.count())]
        widgets_h1[1].clicked.connect(lambda: self._on_qc_generico(quality_control.test_cusum_libre_distribucion, "CUSUM (libre de distribución)"))
        widgets_h1[2].clicked.connect(lambda: self._on_qc_generico(quality_control.test_desviacion_acumulada, "Desviación acumulada (Buishand)"))
        widgets_h1[3].clicked.connect(lambda: self._on_qc_generico(quality_control.test_worsley_likelihood_ratio, "Worsley (razón de verosimilitud)"))

        v_cal.addWidget(QLabel("<b>② Tendencias</b>"))
        h2 = QHBoxLayout()
        btn_mk = QPushButton("Mann-Kendall + Sen"); btn_mk.clicked.connect(self._on_qc_mann_kendall_sen); h2.addWidget(btn_mk)
        btn_spearman = QPushButton("Spearman's Rho")
        btn_spearman.clicked.connect(lambda: self._on_qc_generico(quality_control.test_spearman_rho, "Spearman's Rho"))
        h2.addWidget(btn_spearman)
        btn_regresion = QPushButton("Regresión Lineal")
        btn_regresion.clicked.connect(lambda: self._on_qc_generico(quality_control.test_regresion_lineal_tendencia, "Regresión Lineal"))
        h2.addWidget(btn_regresion)
        v_cal.addLayout(h2)

        v_cal.addWidget(QLabel("<b>③ Diferencia entre 2 periodos (divide la serie a la mitad)</b>"))
        h3 = QHBoxLayout()
        btn_ranksum = QPushButton("Rank-Sum")
        btn_ranksum.clicked.connect(lambda: self._on_qc_dos_periodos(quality_control.test_rank_sum, "Rank-Sum (Wilcoxon-Mann-Whitney)"))
        h3.addWidget(btn_ranksum)
        btn_ttest = QPushButton("Student's t test")
        btn_ttest.clicked.connect(lambda: self._on_qc_dos_periodos(quality_control.test_t_student, "t de Student (Welch)"))
        h3.addWidget(btn_ttest)
        v_cal.addLayout(h3)

        v_cal.addWidget(QLabel("<b>④ Aleatoriedad</b>"))
        h4 = QHBoxLayout()
        btn_cruces = QPushButton("Median Crossing")
        btn_cruces.clicked.connect(lambda: self._on_qc_generico(quality_control.test_cruces_mediana, "Cruces de la mediana"))
        h4.addWidget(btn_cruces)
        btn_giros = QPushButton("Turning Points")
        btn_giros.clicked.connect(lambda: self._on_qc_generico(quality_control.test_puntos_de_giro, "Puntos de giro"))
        h4.addWidget(btn_giros)
        btn_rangodiff = QPushButton("Rank Difference")
        btn_rangodiff.clicked.connect(lambda: self._on_qc_generico(quality_control.test_diferencia_rangos, "Diferencia de rangos"))
        h4.addWidget(btn_rangodiff)
        btn_autocorr = QPushButton("Autocorrelation")
        btn_autocorr.clicked.connect(lambda: self._on_qc_generico(quality_control.test_autocorrelacion, "Autocorrelación (lag-1)"))
        h4.addWidget(btn_autocorr)
        v_cal.addLayout(h4)

        self.lbl_resultado_qc = QLabel("Resultado: sin calcular.")
        self.lbl_resultado_qc.setWordWrap(True)
        self.lbl_resultado_qc.setStyleSheet("font-family: monospace;")
        v_cal.addWidget(self.lbl_resultado_qc)

        self.canvas_qc = QcCanvas(self)
        v_cal.addWidget(self.canvas_qc)
        v.addWidget(gb_calidad)

        gb_pmp = QGroupBox("4. Precipitación Máxima Probable (PMP) — método de Hershfield (opcional)")
        v_pmp = QVBoxLayout(gb_pmp)
        f_pmp = QFormLayout()
        f_pmp.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.spin_pmp_km = QDoubleSpinBox(); self.spin_pmp_km.setRange(1.0, 25.0); self.spin_pmp_km.setValue(15.0)
        f_pmp.addRow("Factor de frecuencia Km (15 = envolvente mundial OMM):", self.spin_pmp_km)
        self.check_pmp_hora_fija = QCheckBox("Aplicar factor de corrección por observación a hora fija (×1.13, WMO-No. 1045)")
        self.check_pmp_hora_fija.setChecked(True)
        f_pmp.addRow(self.check_pmp_hora_fija)
        v_pmp.addLayout(f_pmp)
        self.btn_calcular_pmp = QPushButton("Calcular PMP (Hershfield)")
        self.btn_calcular_pmp.clicked.connect(self._on_calcular_pmp)
        v_pmp.addWidget(self.btn_calcular_pmp)
        self.lbl_resultado_pmp = QLabel("Resultado: sin calcular.")
        self.lbl_resultado_pmp.setWordWrap(True)
        self.lbl_resultado_pmp.setStyleSheet("font-family: monospace;")
        v_pmp.addWidget(self.lbl_resultado_pmp)
        v.addWidget(gb_pmp)

        v.addWidget(QLabel("<b>5. Cuadro resumen</b> — todos los tests ejecutados en esta sesión:"))
        self.tabla_resumen_qc = QTableWidget(0, 4)
        self.tabla_resumen_qc.setHorizontalHeaderLabels(["Test", "Categoría", "Estadístico principal", "Conclusión"])
        # "Conclusión" trae una frase completa por test (longitud variable);
        # se deja en Stretch para que absorba el espacio sobrante, evitando
        # que la fila con la conclusión más larga empuje la tabla más allá
        # del ancho de la ventana (hasta 14 tests posibles, uno por fila).
        aplicar_columna_elastica(self.tabla_resumen_qc, indice_columna_larga=3,
                                  anchos_fijos={0: 190, 1: 150, 2: 140})
        v.addWidget(self.tabla_resumen_qc)

        self._agregar_pestaña_con_scroll(tab, "6. Precipitación Media Mensual")

    def _on_usar_tabla_precip_mensual(self):
        try:
            filas = []
            for row in range(self.tabla_precip_mensual.rowCount()):
                item_anio = self.tabla_precip_mensual.item(row, 0)
                if not item_anio or not item_anio.text().strip():
                    continue
                valores_fila = []
                for col in range(1, 13):
                    item = self.tabla_precip_mensual.item(row, col)
                    texto = item.text().strip() if item else ""
                    valores_fila.append(float("nan") if (not texto or texto.lower() == "nan") else float(texto))
                filas.append(valores_fila)
            if not filas:
                QMessageBox.warning(self, "Sin datos", "La tabla no tiene filas con datos.")
                return
            serie_plana = [v for fila in filas for v in fila]
            self.serie_qc_activa = serie_plana
            self.lbl_estado_precip_mensual.setText(
                f"Estado: serie activa cargada desde la tabla ({len(filas)} años, {len(serie_plana)} meses)."
            )
        except ValueError as e:
            QMessageBox.critical(self, "Error leyendo la tabla", str(e))

    def _on_usar_serie_anual_como_qc(self):
        if not getattr(self, "serie_precip_anual", None):
            QMessageBox.warning(self, "Falta la serie", "Cargue primero una serie en la pestaña 5.")
            return
        self.serie_qc_activa = list(self.serie_precip_anual.valores_mm)
        self.lbl_estado_precip_mensual.setText(
            f"Estado: serie activa = serie anual de P24h de la pestaña 5 ({len(self.serie_qc_activa)} datos)."
        )

    def _on_completar_fourier(self):
        if not getattr(self, "serie_qc_activa", None):
            QMessageBox.warning(self, "Falta la serie", "Cargue primero los datos en el paso 1.")
            return
        try:
            r = data_completion.completar_extender_fourier(
                self.serie_qc_activa, periodo=12, n_armonicos=self.spin_fourier_armonicos.value(),
                n_periodos_extension=self.spin_fourier_extension.value(),
            )
            self.serie_qc_activa = r["serie_completada"]
            self.lbl_resultado_completacion_mensual.setText(
                f"[Fourier] R² estacional = {r['r2_ajuste_estacional']}  ({r['n_armonicos']} armónicos)\n"
                f"Extensión ({self.spin_fourier_extension.value()} meses): {r['extension']}\n{r['nota']}"
            )
            self.canvas_qc.plot_serie_con_marca(self.serie_qc_activa, "Serie completada/extendida (Fourier)")
        except data_completion.DataCompletionError as e:
            QMessageBox.warning(self, "No se pudo completar", str(e))

    def _on_completar_wavelet(self):
        if not getattr(self, "serie_qc_activa", None):
            QMessageBox.warning(self, "Falta la serie", "Cargue primero los datos en el paso 1.")
            return
        try:
            r = data_completion.completar_extender_wavelet(self.serie_qc_activa)
            self.serie_qc_activa = r["serie_completada"]
            self.lbl_resultado_completacion_mensual.setText(f"[Wavelet] {r.get('nota', '')}")
            self.canvas_qc.plot_serie_con_marca(self.serie_qc_activa, "Serie completada (Wavelet)")
        except data_completion.DataCompletionError as e:
            QMessageBox.warning(self, "No se pudo completar", str(e))

    def _agregar_fila_resumen_qc(self, test, categoria, estadistico, conclusion):
        row = self.tabla_resumen_qc.rowCount()
        self.tabla_resumen_qc.insertRow(row)
        self.tabla_resumen_qc.setItem(row, 0, QTableWidgetItem(test))
        self.tabla_resumen_qc.setItem(row, 1, QTableWidgetItem(categoria))
        self.tabla_resumen_qc.setItem(row, 2, QTableWidgetItem(str(estadistico)))
        self.tabla_resumen_qc.setItem(row, 3, QTableWidgetItem(conclusion))
        # Hasta 14 tests posibles: se construyó con 0 filas y nunca
        # recalculaba su alto, quedando con el alto por defecto de Qt.
        ajustar_alto_tabla(self.tabla_resumen_qc, filas_visibles_max=14)

    def _on_qc_pettitt(self):
        datos = self._obtener_serie_activa()
        if datos is None:
            return
        try:
            r = quality_control.test_pettitt(datos)
            self.lbl_resultado_qc.setText(
                f"[Pettitt] Punto de cambio en la posición {r['indice_cambio']} "
                f"(U={r['U_max']}, p≈{r['p_valor_aprox']})\n"
                f"Media antes = {r['media_antes']}   Media después = {r['media_despues']}\n"
                f"{r['interpretacion']}"
            )
            self.canvas_qc.plot_serie_con_marca(
                datos, "Prueba de Pettitt", indice_marca=r["indice_cambio"],
                etiqueta_marca=f"Quiebre (pos. {r['indice_cambio']})"
            )
            self._agregar_fila_resumen_qc(
                "Pettitt", "Cambio en media", f"U={r['U_max']}, p≈{r['p_valor_aprox']}",
                "Quiebre significativo" if r["es_significativo_alpha_0_05"] else "Sin quiebre significativo"
            )
        except quality_control.QualityControlError as e:
            QMessageBox.warning(self, "No se pudo calcular", str(e))

    def _on_qc_mann_kendall_sen(self):
        datos = self._obtener_serie_activa()
        if datos is None:
            return
        try:
            mk = quality_control.test_mann_kendall(datos)
            sen = quality_control.pendiente_sen(datos)
            self.lbl_resultado_qc.setText(
                f"[Mann-Kendall] S={mk['S']}  Z={mk['Z']}  p={mk['p_valor']}  -> tendencia {mk['tendencia']}\n"
                f"[Sen] {sen['interpretacion']}"
            )
            media_serie = float(np.mean(datos))
            n = len(datos)
            intercepto_sen = media_serie - sen["pendiente_por_periodo"] * (n + 1) / 2.0
            self.canvas_qc.plot_serie_con_marca(
                datos, "Mann-Kendall + pendiente de Sen",
                linea_tendencia=(sen["pendiente_por_periodo"], intercepto_sen),
            )
            self._agregar_fila_resumen_qc(
                "Mann-Kendall", "Tendencia", f"S={mk['S']}, Z={mk['Z']}, p={mk['p_valor']}", f"Tendencia {mk['tendencia']}"
            )
        except quality_control.QualityControlError as e:
            QMessageBox.warning(self, "No se pudo calcular", str(e))

    def _on_qc_doble_masa(self):
        datos = self._obtener_serie_activa()
        if datos is None:
            return
        try:
            texto_ref = self.edit_serie_referencia_dm.text().strip()
            serie_ref = None
            if texto_ref:
                serie_ref = [float(x.strip()) for x in texto_ref.split(",") if x.strip()]
            r = quality_control.curva_doble_masa(datos, serie_ref)
            texto = f"[Doble masa] método: {r['metodo']}\n"
            if r["advertencia"]:
                texto += r["advertencia"] + "\n"
            texto += f"Pendientes de segmento (primeras 10): {r['pendientes_segmento'][:10]}"
            self.lbl_resultado_qc.setText(texto)

            self.canvas_qc.ax.clear()
            self.canvas_qc.ax.plot(r["acumulado_referencia"], r["acumulado_estacion"], "-o",
                                     color="#1F3864", markersize=3)
            self.canvas_qc.ax.set_xlabel("Acumulado de referencia")
            self.canvas_qc.ax.set_ylabel("Acumulado de la estación")
            self.canvas_qc.ax.set_title("Curva de doble masa", pad=12)
            self.canvas_qc.ax.grid(True, linestyle=":", linewidth=0.5)
            self.canvas_qc.fig.tight_layout()
            self.canvas_qc.draw()

            variacion_pendiente = (max(r["pendientes_segmento"], default=1) - min(r["pendientes_segmento"], default=1))
            self._agregar_fila_resumen_qc(
                "Doble masa", "Consistencia", f"variación de pendiente≈{round(variacion_pendiente, 2)}",
                "Ver gráfico (quiebres de pendiente = posibles inconsistencias)"
            )
        except (quality_control.QualityControlError, ValueError) as e:
            QMessageBox.warning(self, "No se pudo calcular", str(e))

    def _on_calcular_pmp(self):
        datos = self._obtener_serie_activa()
        if datos is None:
            return
        try:
            r = pmp_hershfield.calcular_pmp_hershfield(
                datos, km=self.spin_pmp_km.value(),
                factor_hora_fija=1.13 if self.check_pmp_hora_fija.isChecked() else 1.0,
            )
            self.lbl_resultado_pmp.setText(
                f"PMP 24h = {r['PMP_24h_mm']} mm  (≈{r['razon_pmp_sobre_max_observado']}× el máximo "
                f"observado de {r['valor_maximo_observado_mm']} mm en {r['n_anios']} años)\n"
                f"Media (sin el máximo) = {r['media_sin_maximo_mm']} mm   "
                f"Desv. std (sin el máximo) = {r['desv_std_sin_maximo_mm']} mm   "
                f"Km = {r['km_usado']}   factor hora fija = {r['factor_hora_fija_aplicado']}\n\n"
                f"NOTA: {r['nota']}"
            )
        except pmp_hershfield.PmpHershfieldError as e:
            QMessageBox.warning(self, "No se pudo calcular la PMP", str(e))

    def _on_analizar_frecuencia(self):
        if not getattr(self, "serie_precip_anual", None):
            QMessageBox.warning(self, "Falta la serie de datos",
                                 "Cargue primero una serie de máximos anuales (CSV o PISCOp).")
            return
        try:
            datos = self.serie_precip_anual.valores_mm
            alpha = float(self.combo_alpha_ks.currentText())
            resultados = frequency_analysis.analizar_todas(datos, alpha_ks=alpha)
            mejor = frequency_analysis.mejor_ajuste(resultados)
            self.resultados_frecuencia = resultados
            self.mejor_ajuste_clave = mejor
            # Lista de periodos de retorno vigente para las tablas/gráfico
            # de esta sesión de análisis; se reinicia a los predeterminados
            # cada vez que se corre un nuevo ajuste, y se puede ampliar con
            # el botón de "T-Diseño" sin tener que repetir el ajuste.
            self.periodos_retorno_actuales = list(frequency_analysis.PERIODOS_RETORNO_DEFAULT)

            self.tabla_distribuciones.setRowCount(0)
            for clave, r in resultados.items():
                row = self.tabla_distribuciones.rowCount()
                self.tabla_distribuciones.insertRow(row)
                nombre = r["nombre"] + ("  ★ mejor ajuste" if clave == mejor else "")
                self.tabla_distribuciones.setItem(row, 0, QTableWidgetItem(nombre))
                if r["error"]:
                    self.tabla_distribuciones.setItem(row, 1, QTableWidgetItem(f"ERROR: {r['error']}"))
                    self.tabla_distribuciones.setItem(row, 2, QTableWidgetItem(""))
                    self.tabla_distribuciones.setItem(row, 3, QTableWidgetItem(""))
                    self.tabla_distribuciones.setItem(row, 4, QTableWidgetItem(""))
                else:
                    params_str = ", ".join(f"{k}={v:.4f}" for k, v in r["parametros"].items())
                    self.tabla_distribuciones.setItem(row, 1, QTableWidgetItem(params_str))
                    self.tabla_distribuciones.setItem(row, 2, QTableWidgetItem(str(r["D_ks"])))
                    self.tabla_distribuciones.setItem(row, 3, QTableWidgetItem(str(r["D_critico"])))
                    self.tabla_distribuciones.setItem(row, 4, QTableWidgetItem("Sí" if r["pasa_ks"] else "No"))

            # Recalcula el alto de la tabla ahora que tiene filas (una por
            # distribución, hasta 9): se construyó con 0 filas y nunca
            # recalculaba su alto, quedando con el alto por defecto de Qt
            # para 0 filas -- solo se veían 2-3 distribuciones a la vez.
            ajustar_alto_tabla(self.tabla_distribuciones, filas_visibles_max=10)

            if mejor is None:
                QMessageBox.warning(self, "Sin ajuste válido",
                                     "Ninguna distribución pudo ajustarse a la serie proporcionada.")
                return

            dist_mejor = resultados[mejor]["distribucion"]
            disenio = frequency_analysis.precipitaciones_diseño(dist_mejor)
            self.p24_disenio = disenio

            for col, tr in enumerate(frequency_analysis.PERIODOS_RETORNO_DEFAULT):
                self.tabla_p24_tr.setItem(0, col, QTableWidgetItem(str(disenio[tr])))

            datos_ordenados = sorted(datos)
            self.canvas_frecuencia.plot_ajuste(datos_ordenados, resultados, mejor)
            self._actualizar_tabla_comparacion_tr()

            # Poblar automáticamente el selector de Tr en la pestaña de caudales (6)
            self.combo_tr_hidrograma.clear()
            for tr in frequency_analysis.PERIODOS_RETORNO_DEFAULT:
                self.combo_tr_hidrograma.addItem(f"Tr = {tr} años (P24 = {disenio[tr]} mm)", tr)

        except Exception as e:
            QMessageBox.critical(self, "Error en el análisis de frecuencia", str(e))

    def _on_agregar_t_disenio(self):
        if not getattr(self, "resultados_frecuencia", None):
            QMessageBox.warning(self, "Falta el análisis de frecuencia",
                                 "Ajuste primero las distribuciones (paso 2) antes de agregar un T-Diseño.")
            return
        tr = self.spin_t_disenio.value()
        if tr in self.periodos_retorno_actuales:
            QMessageBox.information(self, "Ya existe",
                                     f"Tr = {tr} años ya está incluido en la comparación.")
            return
        self.periodos_retorno_actuales.append(tr)
        self.periodos_retorno_actuales.sort()
        self._actualizar_tabla_comparacion_tr()

        mejor = self.mejor_ajuste_clave
        if mejor is not None:
            dist_mejor = self.resultados_frecuencia[mejor]["distribucion"]
            p24_tdis = round(dist_mejor.cuantil(1.0 - 1.0 / tr), 2)
            self.combo_tr_hidrograma.addItem(f"Tr = {tr} años (T-Diseño, P24 = {p24_tdis} mm)", tr)
            self.combo_tr_hidrograma.setCurrentIndex(self.combo_tr_hidrograma.count() - 1)
            QMessageBox.information(
                self, "T-Diseño agregado",
                f"Tr = {tr} años agregado a la tabla comparativa y disponible en la pestaña 6 "
                f"(P24 = {p24_tdis} mm con la distribución de mejor ajuste, {self.resultados_frecuencia[mejor]['nombre']})."
            )

    def _actualizar_tabla_comparacion_tr(self):
        """Repuebla la tabla y el gráfico comparativo Pmax24h vs Tr para
        todas las distribuciones ajustadas, usando la lista vigente de
        periodos de retorno (predeterminados + T-Diseño agregados)."""
        tabla_comp = frequency_analysis.tabla_comparacion_tr(
            self.resultados_frecuencia, self.periodos_retorno_actuales
        )
        trs_ordenados = self.periodos_retorno_actuales
        self.tabla_comparacion_distribuciones.setRowCount(len(tabla_comp))
        self.tabla_comparacion_distribuciones.setColumnCount(len(trs_ordenados))
        self.tabla_comparacion_distribuciones.setHorizontalHeaderLabels(
            [f"Tr={tr}a" for tr in trs_ordenados]
        )
        self.tabla_comparacion_distribuciones.setVerticalHeaderLabels(
            [self.resultados_frecuencia[clave]["nombre"] + ("  ★" if clave == self.mejor_ajuste_clave else "")
             for clave in tabla_comp]
        )
        for row, (clave, serie_tr) in enumerate(tabla_comp.items()):
            for col, tr in enumerate(trs_ordenados):
                self.tabla_comparacion_distribuciones.setItem(
                    row, col, QTableWidgetItem(str(serie_tr.get(tr, "")))
                )
        # Antes las columnas de Tr estaban en modo Stretch, estirándose a
        # todo el ancho disponible (columnas innecesariamente anchas para
        # un solo número). Ahora se ajustan al contenido, igual que la
        # columna de nombres de distribución (encabezado vertical).
        self.tabla_comparacion_distribuciones.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla_comparacion_distribuciones.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        # Esta tabla puede crecer sin límite en columnas (una por cada
        # "T-Diseño" agregado) y en filas (una por distribución, hasta 9).
        # Se limita su ancho máximo para que sea ella la que muestre scroll
        # horizontal interno en vez de ensanchar toda la pestaña, y se
        # recalcula su alto para que las distribuciones no queden
        # comprimidas con un scroll interno diminuto.
        limitar_ancho_tabla(self.tabla_comparacion_distribuciones, ancho_maximo=880)
        ajustar_alto_tabla(self.tabla_comparacion_distribuciones, filas_visibles_max=10)
        self.canvas_comparacion_tr.plot_comparacion_tr(tabla_comp, self.resultados_frecuencia,
                                                        self.mejor_ajuste_clave, escala_log=True)
        self.canvas_comparacion_tr_cartesiano.plot_comparacion_tr(tabla_comp, self.resultados_frecuencia,
                                                                    self.mejor_ajuste_clave, escala_log=False)

    # ------------------------------------------------------------------
    # TAB 6: Caudales empíricos (SCS / Snyder / Clark) - estilo HEC-HMS
    # ------------------------------------------------------------------
    def _build_tab5(self):
        tab = QWidget()
        v = QVBoxLayout(tab)

        _lbl_auto_14 = QLabel(
            "Estimación empírica de caudales de crecida por transformación lluvia-escorrentía, "
            "replicando los tres métodos que también ofrece HEC-HMS: SCS (triangular), Snyder y "
            "Clark (área-tiempo + embalse lineal). Requiere haber calculado la morfometría (pestaña 2) "
            "y, para las pérdidas por infiltración, el número de curva (pestaña 3)."
        )
        _lbl_auto_14.setWordWrap(True)
        v.addWidget(_lbl_auto_14)

        gb_auto = QGroupBox("Generar hietograma automáticamente desde la Pestaña 5 (Precipitación Máx 24h)")
        f_auto = QFormLayout(gb_auto)
        f_auto.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.combo_tr_hidrograma = QComboBox()
        self.combo_tr_hidrograma.addItem("(calcule primero la pestaña 5)", None)
        f_auto.addRow("Periodo de retorno Tr:", self.combo_tr_hidrograma)

        self.combo_metodo_desagregacion = QComboBox()
        self.combo_metodo_desagregacion.addItems([
            "Curva IDF genérica (bloques alternos)",
            "Patrón SCS Tipo I (aproximado)",
            "Patrón SCS Tipo II (aproximado)",
            "Patrón SCS Tipo III (aproximado)",
        ])
        self.combo_metodo_desagregacion.currentIndexChanged.connect(self._on_cambiar_metodo_desagregacion)
        f_auto.addRow("Método de desagregación temporal:", self.combo_metodo_desagregacion)

        self.spin_duracion_tormenta_h = QDoubleSpinBox()
        self.spin_duracion_tormenta_h.setRange(0.5, 48.0)
        self.spin_duracion_tormenta_h.setValue(6.0)
        self.lbl_duracion_tormenta = QLabel("Duración total de la tormenta (h), solo IDF (SCS usa 24h fijas):")
        f_auto.addRow(self.lbl_duracion_tormenta, self.spin_duracion_tormenta_h)

        self.spin_exponente_disagregacion = QDoubleSpinBox()
        self.spin_exponente_disagregacion.setRange(0.05, 0.50)
        self.spin_exponente_disagregacion.setSingleStep(0.01)
        self.spin_exponente_disagregacion.setValue(0.20)
        self.lbl_exponente_disagregacion = QLabel("Exponente de desagregación n (P(d)=P24·(d/1440)^n), solo IDF:")
        f_auto.addRow(self.lbl_exponente_disagregacion, self.spin_exponente_disagregacion)

        aviso_scs = QLabel(
            "Nota: los patrones SCS I/II/III aquí son una aproximación paramétrica de la forma general "
            "de cada tipo, no la tabla oficial NRCS (ver advertencia en core/scs_storm_patterns.py). "
            "Para un diseño definitivo, reemplace por la tabla oficial si la tiene disponible."
        )
        aviso_scs.setWordWrap(True)
        f_auto.addRow(aviso_scs)

        self.btn_generar_hietograma = QPushButton("Generar hietograma")
        self.btn_generar_hietograma.clicked.connect(self._on_generar_hietograma_automatico)
        limitar_ancho_boton(self.btn_generar_hietograma)
        f_auto.addRow(self.btn_generar_hietograma)

        v.addWidget(gb_auto)
        self._on_cambiar_metodo_desagregacion()


        gb_hieto = QGroupBox("Hietograma de diseño (incrementos de lluvia TOTAL, mm, separados por coma) — "
                              "se autocompleta con el botón de arriba, o edítelo/ingréselo manualmente")
        v_h = QVBoxLayout(gb_hieto)
        self.edit_hietograma = QPlainTextEdit()
        self.edit_hietograma.setPlaceholderText("Ej: 2,5,10,15,15,10,5,3,2,1,1,1  (un valor por intervalo Dt)")
        self.edit_hietograma.setMaximumHeight(60)
        v_h.addWidget(self.edit_hietograma)
        h_dt = QHBoxLayout()
        self.spin_dt_h = QDoubleSpinBox()
        self.spin_dt_h.setRange(0.05, 6.0)
        self.spin_dt_h.setSingleStep(0.25)
        self.spin_dt_h.setValue(0.5)
        h_dt.addWidget(QLabel("Duración del intervalo Dt (h):"))
        h_dt.addWidget(self.spin_dt_h)
        v_h.addLayout(h_dt)
        v.addWidget(gb_hieto)

        gb_metodo = QGroupBox("Método de transformación")
        h_m = QHBoxLayout(gb_metodo)
        self.combo_metodo_uh = QComboBox()
        self.combo_metodo_uh.addItems(["SCS (triangular)", "Snyder", "Clark (área-tiempo + embalse lineal)"])
        h_m.addWidget(self.combo_metodo_uh)

        self.spin_lca_km = QDoubleSpinBox()
        self.spin_lca_km.setRange(0.001, 500)
        self.spin_lca_km.setDecimals(3)
        h_m.addWidget(QLabel("Lca (km, solo Snyder):"))
        h_m.addWidget(self.spin_lca_km)

        self.spin_ct_snyder = QDoubleSpinBox()
        self.spin_ct_snyder.setRange(0.3, 8.0)
        self.spin_ct_snyder.setValue(2.0)
        h_m.addWidget(QLabel("Ct (Snyder):"))
        h_m.addWidget(self.spin_ct_snyder)

        self.spin_cp_snyder = QDoubleSpinBox()
        self.spin_cp_snyder.setRange(0.2, 1.0)
        self.spin_cp_snyder.setValue(0.6)
        h_m.addWidget(QLabel("Cp (Snyder):"))
        h_m.addWidget(self.spin_cp_snyder)

        self.spin_r_clark = QDoubleSpinBox()
        self.spin_r_clark.setRange(0.01, 200)
        self.spin_r_clark.setDecimals(3)
        h_m.addWidget(QLabel("R (h, solo Clark; por defecto = Tc):"))
        h_m.addWidget(self.spin_r_clark)

        v.addWidget(gb_metodo)

        self.btn_calc_hidrograma = QPushButton("Calcular hidrograma de crecida y caudal pico")
        self.btn_calc_hidrograma.clicked.connect(self._on_calcular_hidrograma)
        v.addWidget(self.btn_calc_hidrograma)

        self.lbl_resultado_qp = QLabel("Caudal pico: (aún no calculado)")
        v.addWidget(self.lbl_resultado_qp)

        self.canvas_hidrograma = HydrographCanvas(self, width=6.5, height=4.8)
        v.addWidget(self.canvas_hidrograma)

        gb_directos = QGroupBox(
            "Verificación cruzada — fórmulas de caudal máximo DIRECTO (Témez, Mac Math, Creager), "
            "para comparar contra el caudal SCS/Snyder/Clark de arriba"
        )
        v_dir = QVBoxLayout(gb_directos)
        _lbl_auto_15 = QLabel(
            "Use el botón para autocompletar C, I, A, Tc y S con los valores ya calculados en otras "
            "pestañas (ediítelos si lo desea antes de calcular)."
        )
        _lbl_auto_15.setWordWrap(True)
        v_dir.addWidget(_lbl_auto_15)
        f_dir = QFormLayout()
        f_dir.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.spin_dir_c = QDoubleSpinBox()
        self.spin_dir_c.setRange(0.01, 1.0)
        self.spin_dir_c.setValue(0.5)
        f_dir.addRow("Coeficiente de escorrentía C:", self.spin_dir_c)
        self.spin_dir_i = QDoubleSpinBox()
        self.spin_dir_i.setRange(0.1, 500.0)
        self.spin_dir_i.setValue(40.0)
        f_dir.addRow("Intensidad de lluvia I (mm/h, para duración Tc):", self.spin_dir_i)
        self.spin_dir_a = QDoubleSpinBox()
        self.spin_dir_a.setRange(0.001, 100000.0)
        self.spin_dir_a.setDecimals(3)
        f_dir.addRow("Área de la cuenca A (km²):", self.spin_dir_a)
        self.spin_dir_tc = QDoubleSpinBox()
        self.spin_dir_tc.setRange(0.01, 200.0)
        self.spin_dir_tc.setDecimals(3)
        f_dir.addRow("Tiempo de concentración Tc (h):", self.spin_dir_tc)
        self.spin_dir_s = QDoubleSpinBox()
        self.spin_dir_s.setRange(0.01, 100.0)
        self.spin_dir_s.setValue(5.0)
        f_dir.addRow("Pendiente media del cauce S (%):", self.spin_dir_s)
        self.spin_dir_creager_c = QDoubleSpinBox()
        self.spin_dir_creager_c.setRange(1.0, 150.0)
        self.spin_dir_creager_c.setValue(30.0)
        f_dir.addRow("Coeficiente envolvente de Creager (calibrar regionalmente):", self.spin_dir_creager_c)
        v_dir.addLayout(f_dir)

        h_dir_btn = QHBoxLayout()
        btn_autocompletar_dir = QPushButton("Autocompletar con A/Tc de otras pestañas")
        btn_autocompletar_dir.clicked.connect(self._on_autocompletar_caudales_directos)
        h_dir_btn.addWidget(btn_autocompletar_dir)
        btn_calc_dir = QPushButton("Calcular Témez / Mac Math / Creager")
        btn_calc_dir.clicked.connect(self._on_calcular_caudales_directos)
        h_dir_btn.addWidget(btn_calc_dir)
        v_dir.addLayout(h_dir_btn)

        self.lbl_resultado_caudales_directos = QLabel("Resultado: sin calcular.")
        self.lbl_resultado_caudales_directos.setWordWrap(True)
        self.lbl_resultado_caudales_directos.setStyleSheet("font-family: monospace;")
        v_dir.addWidget(self.lbl_resultado_caudales_directos)

        self.canvas_comparacion_qmax = HydrographCanvas(self, width=6.5, height=4.8)
        v_dir.addWidget(self.canvas_comparacion_qmax)
        v.addWidget(gb_directos)

        self._agregar_pestaña_con_scroll(tab, "7. Caudales Máximos SCS/Clark/Témez/Creager/MacMath")

    def _on_cambiar_metodo_desagregacion(self):
        es_idf = self.combo_metodo_desagregacion.currentIndex() == 0
        self.spin_exponente_disagregacion.setEnabled(es_idf)
        self.lbl_exponente_disagregacion.setEnabled(es_idf)
        self.spin_duracion_tormenta_h.setEnabled(es_idf)
        self.lbl_duracion_tormenta.setEnabled(es_idf)

    def _on_generar_hietograma_automatico(self):
        tr = self.combo_tr_hidrograma.currentData()
        if tr is None or not self.p24_disenio:
            QMessageBox.warning(self, "Falta el análisis de frecuencia",
                                 "Calcule primero el análisis de frecuencia en la pestaña 5 y elija un Tr.")
            return
        try:
            p24 = self.p24_disenio[tr]
            duracion_h = self.spin_duracion_tormenta_h.value()
            dt_h = self.spin_dt_h.value()
            metodo_idx = self.combo_metodo_desagregacion.currentIndex()

            if metodo_idx == 0:
                n_exp = self.spin_exponente_disagregacion.value()
                hietograma = design_storm.bloques_alternos(p24, duracion_h, dt_h, exponente_n=n_exp)
                descripcion_metodo = f"bloques alternos (IDF genérica, n={n_exp})"
            else:
                # IMPORTANTE: las curvas SCS Tipo I/II/III representan una
                # tormenta de 24 horas completas; NO deben comprimirse en la
                # duración corta de la pestaña (eso haría caer el 100% de P24
                # en esa ventana, sobrestimando enormemente el caudal pico).
                # Se genera siempre el hietograma de 24h completo, ignorando
                # el valor de 'duración total de la tormenta' (que solo aplica
                # al método IDF de bloques alternos).
                tipo_scs = {1: "I", 2: "II", 3: "III"}[metodo_idx]
                hietograma = scs_storm_patterns.hietograma_scs(p24, 24.0, dt_h, tipo=tipo_scs)
                descripcion_metodo = f"patrón SCS Tipo {tipo_scs} (aproximado, tormenta de 24h completa)"

            self.edit_hietograma.setPlainText(",".join(f"{v:.2f}" for v in hietograma))
            QMessageBox.information(
                self, "Hietograma generado",
                f"Hietograma de {len(hietograma)} intervalos generado por {descripcion_metodo} para Tr={tr} años "
                f"(P24={p24} mm, duración total={duracion_h} h). Lámina total del hietograma: "
                f"{sum(hietograma):.1f} mm (será igual a P24 solo si duracion_h=24h; con el método SCS a menor "
                "duración se toma el tramo correspondiente de la curva de 24h, y con IDF será menor que P24 por diseño)."
            )
        except Exception as e:
            QMessageBox.critical(self, "Error generando el hietograma", str(e))

    def _on_autocompletar_caudales_directos(self):
        if self.morfometria_resultados.get("g1"):
            self.spin_dir_a.setValue(self.morfometria_resultados["g1"]["A"])
        tc_seleccionado = None
        if self.tc_resultados:
            id_boton = self.grupo_radio_metodo.checkedId()
            if id_boton is not None and id_boton >= 0:
                nombres = list(self.tc_resultados.keys())
                if id_boton < len(nombres):
                    datos_tc = self.tc_resultados[nombres[id_boton]]
                    if not datos_tc.get("error"):
                        tc_seleccionado = datos_tc["Tc_horas"]
        if tc_seleccionado:
            self.spin_dir_tc.setValue(tc_seleccionado)
        if self.morfometria_resultados.get("g3"):
            self.spin_dir_s.setValue(self.morfometria_resultados["g3"]["Se"] * 100.0)
        elif self.morfometria_resultados.get("g4"):
            self.spin_dir_s.setValue(self.morfometria_resultados["g4"]["S_cuenca_pct"])
        QMessageBox.information(self, "Autocompletado", "Se autocompletaron A, Tc y S con los valores disponibles.")

    def _on_calcular_caudales_directos(self):
        try:
            r = direct_discharge_methods.comparar_metodos_directos(
                coef_escorrentia_c=self.spin_dir_c.value(), intensidad_mm_h=self.spin_dir_i.value(),
                area_km2=self.spin_dir_a.value(), tc_horas=self.spin_dir_tc.value(),
                pendiente_cauce_pct=self.spin_dir_s.value(), coeficiente_creager=self.spin_dir_creager_c.value(),
            )
            qp_scs = self.hidrograma_resultado.get("caudal_pico_m3s") if self.hidrograma_resultado else None
            texto = (
                f"Témez:     Q = {r['temez']['Q_m3_s']} m³/s   (K = {r['temez']['coeficiente_uniformidad_K']})\n"
                f"Mac Math:  Q = {r['mac_math']['Q_m3_s']} m³/s\n"
                f"Creager:   Q = {r['creager']['Q_m3_s']} m³/s   ({r['creager']['nota']})\n"
            )
            if qp_scs is not None:
                texto += f"\n(Comparar contra Qp = {qp_scs} m³/s obtenido arriba por SCS/Snyder/Clark)"
            self.resultados_hidraulica_drenaje["Caudales directos (Témez/Mac Math/Creager)"] = {
                "tipo": "Caudales directos", "Temez_Q_m3s": r["temez"]["Q_m3_s"],
                "MacMath_Q_m3s": r["mac_math"]["Q_m3_s"], "Creager_Q_m3s": r["creager"]["Q_m3_s"],
                "Qp_SCS_Snyder_Clark_m3s": qp_scs,
            }
            self.lbl_resultado_caudales_directos.setText(texto)

            nombres_metodos = ["Témez", "Mac Math", "Creager"]
            valores_metodos = [r["temez"]["Q_m3_s"], r["mac_math"]["Q_m3_s"], r["creager"]["Q_m3_s"]]
            if qp_scs is not None:
                metodo_hidrograma = self.hidrograma_resultado.get("metodo", "SCS/Snyder/Clark")
                nombres_metodos.insert(0, str(metodo_hidrograma))
                valores_metodos.insert(0, qp_scs)
            self.canvas_comparacion_qmax.plot_comparacion_metodos(nombres_metodos, valores_metodos)
        except direct_discharge_methods.DirectDischargeError as e:
            QMessageBox.warning(self, "No se pudo calcular", str(e))

    def _on_calcular_hidrograma(self):
        if not self.morfometria_resultados:
            QMessageBox.warning(self, "Falta la morfometría", "Calcule primero la morfometría en la pestaña 2.")
            return
        texto = self.edit_hietograma.toPlainText().strip()
        if not texto:
            QMessageBox.warning(self, "Falta el hietograma", "Ingrese el hietograma de diseño (incrementos de lluvia en mm).")
            return
        # Antes se exigía coma como ÚNICO separador válido (texto.split(",")),
        # lo que fallaba con "Hietograma inválido" si el texto tenía saltos
        # de línea, punto y coma, espacios extra, o texto suelto (p. ej.
        # unidades) pegado entre valores. Ahora se extraen directamente
        # todos los números (con signo y decimales opcionales) del texto,
        # sin importar qué separador se haya usado.
        import re
        tokens = re.findall(r"-?\d+(?:\.\d+)?", texto)
        if not tokens:
            QMessageBox.critical(
                self, "Hietograma inválido",
                "No se reconoció ningún valor numérico en el hietograma. Ingrese los incrementos "
                "de lluvia (mm) separados por coma, espacio o salto de línea, usando punto como "
                "separador decimal (ej: 2.5, 5.0, 10.2)."
            )
            return
        hietograma = [float(t) for t in tokens]

        if not self.cn_resultados:
            QMessageBox.warning(self, "Falta el número de curva",
                                 "Calcule primero el número de curva en la pestaña 3 (se usa S para las pérdidas).")
            return

        try:
            g1 = self.morfometria_resultados["g1"]
            lc_km = self.morfometria_resultados["lc_km"]
            dt_h = self.spin_dt_h.value()
            s_mm = self.cn_resultados["S_mm"]

            metodo_ui = self.combo_metodo_uh.currentText()
            if metodo_ui.startswith("SCS"):
                # tlag: se usa el de la pestaña 4 si ya se calculó Témez;
                # si no, se aproxima con H/Lc (misma aproximación de la pestaña 4).
                tl_h = None
                if self.tc_resultados:
                    for nombre, datos in self.tc_resultados.items():
                        if "Témez" in nombre and datos.get("tlag_min") is not None:
                            tl_h = datos["tlag_min"] / 60.0
                            break
                if tl_h is None:
                    se_aprox = g1["H"] / (lc_km * 1000.0)
                    tc_aprox_h = 0.01947 * ((lc_km * 1000.0) ** 0.77) * (se_aprox ** -0.385) / 60.0
                    tl_h = 0.6 * tc_aprox_h
                resultado = unit_hydrographs.hidrograma_de_crecida(
                    hietograma, dt_h, g1["A"], s_mm, "scs",
                    tlag_h=tl_h, duracion_efectiva_h=dt_h,
                )
            elif metodo_ui.startswith("Snyder"):
                lca = self.spin_lca_km.value() or (lc_km * 0.5)
                resultado = unit_hydrographs.hidrograma_de_crecida(
                    hietograma, dt_h, g1["A"], s_mm, "snyder",
                    l_km=lc_km, lca_km=lca, ct=self.spin_ct_snyder.value(), cp=self.spin_cp_snyder.value(),
                )
            else:  # Clark
                tc_h = None
                if self.tc_resultados:
                    for nombre, datos in self.tc_resultados.items():
                        if "Témez" in nombre and datos.get("Tc_horas") is not None:
                            tc_h = datos["Tc_horas"]
                            break
                if tc_h is None:
                    se_aprox = g1["H"] / (lc_km * 1000.0)
                    tc_h = 0.01947 * ((lc_km * 1000.0) ** 0.77) * (se_aprox ** -0.385) / 60.0
                r_h = self.spin_r_clark.value() or tc_h
                resultado = unit_hydrographs.hidrograma_de_crecida(
                    hietograma, dt_h, g1["A"], s_mm, "clark",
                    tc_h=tc_h, r_storage_h=r_h,
                )

            self.hidrograma_resultado = resultado
            self.hidrograma_resultado["metodo"] = metodo_ui
            self.lbl_resultado_qp.setText(
                f"Caudal pico Qp = {resultado['caudal_pico_m3s']} m³/s, en tiempo Tp = {resultado['tiempo_pico_h']} h "
                f"(lluvia total = {sum(hietograma):.1f} mm, lluvia efectiva = {sum(resultado['lluvia_efectiva_incr_mm']):.1f} mm)"
            )
            self.canvas_hidrograma.plot_hidrograma(
                resultado["tiempos_h"], resultado["caudal_m3s"], metodo_ui,
                resultado["caudal_pico_m3s"], resultado["tiempo_pico_h"],
            )

        except Exception as e:
            QMessageBox.critical(self, "Error calculando el hidrograma", str(e))

    # ------------------------------------------------------------------
    # TAB 7: Hidráulica y Drenaje
    # ------------------------------------------------------------------
    def _build_tab_hidraulica_drenaje(self):
        tab = QWidget()
        v = QVBoxLayout(tab)

        _lbl_auto_16 = QLabel(
            "<b>Hidráulica y Drenaje</b> — dimensionamiento/verificación de estructuras de drenaje. "
            "El caudal de entrada puede tomarse del caudal pico calculado en la pestaña 6, y la "
            "pendiente/rugosidad de referencia, de la morfometría (pestañas 1/2)."
        )
        _lbl_auto_16.setWordWrap(True)
        v.addWidget(_lbl_auto_16)

        h_sel = QHBoxLayout()
        h_sel.addWidget(QLabel("Estructura hidráulica:"))
        self.combo_tipo_estructura = QComboBox()
        self.combo_tipo_estructura.addItems([
            "Canales", "Vados / Badén", "Alcantarilla", "Enrocado (RipRap)",
            "Sumideros", "Cunetas de coronación", "Pontón", "Puente", "Defensa Ribereña",
        ])
        self.combo_tipo_estructura.currentIndexChanged.connect(
            lambda i: self.stack_estructura.setCurrentIndex(i)
        )
        h_sel.addWidget(self.combo_tipo_estructura)
        v.addLayout(h_sel)

        self.stack_estructura = QStackedWidget()
        self.stack_estructura.addWidget(self._pagina_canales("Canales"))
        self.stack_estructura.addWidget(self._pagina_canales("Vados / Badén (verificar como canal + borde libre a la calzada)"))
        self.stack_estructura.addWidget(self._pagina_alcantarilla())
        self.stack_estructura.addWidget(self._pagina_enrocado())
        self.stack_estructura.addWidget(self._pagina_sumidero())
        self.stack_estructura.addWidget(self._pagina_canales("Cunetas de coronación (mismo motor de canales, sección pequeña)"))
        self.stack_estructura.addWidget(self._pagina_borde_libre("Pontón"))
        self.stack_estructura.addWidget(self._pagina_borde_libre("Puente"))
        self.stack_estructura.addWidget(self._pagina_defensa_ribereña())
        v.addWidget(self.stack_estructura)

        self._agregar_pestaña_con_scroll(tab, "8. Hidráulica y Drenaje")

    def _fila_fuente_datos(self, layout: QFormLayout, prefijo: str):
        """Botones para tomar Q de la pestaña 6 y S/n de la morfometría,
        comunes a varias páginas de la pestaña 7."""
        h = QHBoxLayout()
        btn_q = QPushButton("Usar Qp de la pestaña 6 (caudal pico)")
        btn_q.clicked.connect(lambda: self._usar_qp_pestaña6(prefijo))
        h.addWidget(btn_q)
        btn_s = QPushButton("Usar pendiente de la morfometría")
        btn_s.clicked.connect(lambda: self._usar_pendiente_morfometria(prefijo))
        h.addWidget(btn_s)
        layout.addRow(h)

    def _usar_qp_pestaña6(self, prefijo: str):
        if not self.hidrograma_resultado:
            QMessageBox.warning(self, "Falta el caudal", "Calcule primero el hidrograma en la pestaña 6.")
            return
        spin = getattr(self, f"spin_{prefijo}_q", None)
        if spin is not None:
            spin.setValue(self.hidrograma_resultado["caudal_pico_m3s"])

    def _usar_pendiente_morfometria(self, prefijo: str):
        s_pct = None
        if self.morfometria_resultados.get("g4"):
            s_pct = self.morfometria_resultados["g4"]["S_cuenca_pct"]
        elif self.morfometria_resultados.get("g3"):
            s_pct = self.morfometria_resultados["g3"]["Se"] * 100.0
        if s_pct is None:
            QMessageBox.warning(self, "Falta la morfometría",
                                 "Calcule primero la pendiente en la pestaña 4 (Grupo 3/4).")
            return
        spin = getattr(self, f"spin_{prefijo}_s", None)
        if spin is not None:
            spin.setValue(s_pct / 100.0)  # de % a m/m

    # ---------------- Página: Canales (y Vados/Cunetas, mismo motor) ----------------
    def _pagina_canales(self, titulo: str) -> QWidget:
        pagina = QWidget()
        v = QVBoxLayout(pagina)
        v.addWidget(QLabel(f"<b>{titulo}</b> — sección de MÁXIMA EFICIENCIA HIDRÁULICA (Chow, 1959) "
                            "para Rectangular/Triangular/Trapezoidal; Parabólico y Gutter con fórmulas "
                            "estándar propias; Irregular a partir de una sección dada."))
        f = QFormLayout()

        f.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        combo_forma = QComboBox()
        combo_forma.addItems([
            "Rectangular (máx. eficiencia)", "Triangular (máx. eficiencia)",
            "Trapezoidal (máx. eficiencia)", "Trapezoidal (geometría dada)",
            "Parabólico", "Gutter / Cuneta vial (HEC-22)", "Irregular (sección dada)",
        ])
        f.addRow("Forma del canal:", combo_forma)

        spin_n = QDoubleSpinBox()
        spin_n.setRange(0.008, 0.2)
        spin_n.setDecimals(4)
        spin_n.setValue(0.014)
        f.addRow("Coef. de rugosidad de Manning n:", spin_n)

        spin_s = QDoubleSpinBox()
        spin_s.setRange(0.0001, 1.0)
        spin_s.setDecimals(5)
        spin_s.setValue(0.02)
        f.addRow("Pendiente longitudinal S (m/m):", spin_s)

        spin_q = QDoubleSpinBox()
        spin_q.setRange(0.001, 10000.0)
        spin_q.setDecimals(3)
        spin_q.setValue(1.0)
        f.addRow("Caudal de diseño Q (m³/s):", spin_q)

        spin_b = QDoubleSpinBox()
        spin_b.setRange(0.01, 50.0)
        spin_b.setDecimals(3)
        spin_b.setValue(1.0)
        f.addRow("b — solera (solo Trapezoidal geometría dada) (m):", spin_b)

        spin_z = QDoubleSpinBox()
        spin_z.setRange(0.0, 10.0)
        spin_z.setDecimals(3)
        spin_z.setValue(1.0)
        f.addRow("z — talud H:V (solo Trapezoidal geometría dada):", spin_z)

        spin_t = QDoubleSpinBox()
        spin_t.setRange(0.1, 50.0)
        spin_t.setDecimals(3)
        spin_t.setValue(2.0)
        f.addRow("T — ancho superior (solo Parabólico) (m):", spin_t)

        spin_sx = QDoubleSpinBox()
        spin_sx.setRange(0.001, 0.2)
        spin_sx.setDecimals(4)
        spin_sx.setValue(0.02)
        f.addRow("Sx — pendiente transversal de la vía (solo Gutter) (m/m):", spin_sx)

        v.addLayout(f)

        v.addWidget(QLabel("Sección estación-elevación (solo Irregular) — una fila por punto, de izquierda a derecha:"))
        tabla_puntos = TablaPegable(15, 2)
        tabla_puntos.setHorizontalHeaderLabels(["Estación (m)", "Cota (m)"])
        tabla_puntos.setMaximumHeight(160)
        v.addWidget(tabla_puntos)

        prefijo = f"canal_{id(pagina)}"
        setattr(self, f"combo_{prefijo}_forma", combo_forma)
        setattr(self, f"spin_{prefijo}_n", spin_n)
        setattr(self, f"spin_{prefijo}_s", spin_s)
        setattr(self, f"spin_{prefijo}_q", spin_q)
        setattr(self, f"spin_{prefijo}_b", spin_b)
        setattr(self, f"spin_{prefijo}_z", spin_z)
        setattr(self, f"spin_{prefijo}_t", spin_t)
        setattr(self, f"spin_{prefijo}_sx", spin_sx)
        setattr(self, f"tabla_{prefijo}_puntos", tabla_puntos)

        self._fila_fuente_datos(f, prefijo)

        btn_calc = QPushButton("Calcular")
        v.addWidget(btn_calc)

        lbl_resultado = QLabel("Resultado: sin calcular.")
        lbl_resultado.setWordWrap(True)
        lbl_resultado.setStyleSheet("font-family: monospace;")
        v.addWidget(lbl_resultado)
        setattr(self, f"lbl_{prefijo}_resultado", lbl_resultado)

        canvas_seccion = SeccionTransversalCanvas(pagina)
        v.addWidget(canvas_seccion)
        setattr(self, f"canvas_{prefijo}_seccion", canvas_seccion)

        btn_calc.clicked.connect(lambda: self._on_calcular_canal(prefijo))
        return pagina

    def _on_calcular_canal(self, prefijo: str):
        combo_forma = getattr(self, f"combo_{prefijo}_forma")
        n = getattr(self, f"spin_{prefijo}_n").value()
        s = getattr(self, f"spin_{prefijo}_s").value()
        q = getattr(self, f"spin_{prefijo}_q").value()
        forma = combo_forma.currentText()
        lbl = getattr(self, f"lbl_{prefijo}_resultado")
        try:
            if forma.startswith("Rectangular"):
                r = hydraulic_structures.canal_rectangular_maxima_eficiencia(n, s, q=q)
                extra = f"b = {r.geometria['b_m']} m (b = 2y)"
            elif forma.startswith("Triangular"):
                r = hydraulic_structures.canal_triangular_maxima_eficiencia(n, s, q=q)
                extra = f"z = {r.geometria['z']} (taludes a 45°)"
            elif forma == "Trapezoidal (máx. eficiencia)":
                r = hydraulic_structures.canal_trapezoidal_maxima_eficiencia(n, s, q=q)
                extra = f"b = {r.geometria['b_m']} m, z = {r.geometria['z']} (semihexágono)"
            elif forma == "Trapezoidal (geometría dada)":
                b = getattr(self, f"spin_{prefijo}_b").value()
                z = getattr(self, f"spin_{prefijo}_z").value()
                r = hydraulic_structures.canal_trapezoidal_general(n, s, b, z, q=q)
                extra = f"b = {b} m, z = {z} (ingresados por el usuario)"
            elif forma == "Parabólico":
                t = getattr(self, f"spin_{prefijo}_t").value()
                r = hydraulic_structures.canal_parabolico(n, s, t, q=q)
                extra = f"T = {t} m"
            elif forma.startswith("Gutter"):
                sx = getattr(self, f"spin_{prefijo}_sx").value()
                res = hydraulic_structures.cuneta_vial_hec22(n, s, sx, q=q)
                lbl.setText(
                    "Cuneta vial (FHWA HEC-22):\n"
                    f"  Ancho de inundación (spread) T = {res['spread_T_m']} m\n"
                    f"  Tirante en el borde = {res['tirante_borde_m']} m\n"
                    f"  Área = {res['area_m2']} m²   Velocidad = {res['velocidad_m_s']} m/s\n"
                    f"  Caudal = {res['caudal_m3_s']} m³/s"
                )
                canvas = getattr(self, f"canvas_{prefijo}_seccion")
                canvas.plot_triangular(1.0 / sx, res["tirante_borde_m"])
                self.resultados_hidraulica_drenaje[f"Canal/cuneta - {forma}"] = {
                    "tipo": "Canal (Gutter/cuneta vial HEC-22)", "forma": forma,
                    "n": n, "S": s, "Q_o_spread": q,
                    **{k: v for k, v in res.items() if k != "advertencia"},
                }
                return
            else:  # Irregular
                tabla_puntos = getattr(self, f"tabla_{prefijo}_puntos")
                puntos = []
                for row in range(tabla_puntos.rowCount()):
                    item_x = tabla_puntos.item(row, 0)
                    item_z = tabla_puntos.item(row, 1)
                    if item_x and item_z and item_x.text().strip() and item_z.text().strip():
                        puntos.append((float(item_x.text()), float(item_z.text())))
                if len(puntos) < 2:
                    raise hydraulic_structures.HydraulicError(
                        "Ingrese al menos 2 puntos de la sección estación-elevación."
                    )
                r = hydraulic_structures.canal_irregular(n, s, puntos, q=q)
                extra = f"{len(puntos)} puntos de sección ingresados"

            lbl.setText(
                f"{r.forma}  [{extra}]\n"
                f"  Tirante normal y = {r.y_m} m\n"
                f"  Área = {r.area_m2} m²   Perímetro mojado = {r.perimetro_m} m   "
                f"Radio hidráulico = {r.radio_hidraulico_m} m   Ancho superior = {r.ancho_superior_m} m\n"
                f"  Velocidad = {r.velocidad_m_s} m/s   Energía específica = {r.energia_especifica_m} m\n"
                f"  Número de Froude = {r.numero_froude}  ({r.tipo_flujo})\n"
                f"  Tirante crítico = {r.tirante_critico_m} m   Pendiente crítica = {r.pendiente_critica} m/m"
            )

            canvas = getattr(self, f"canvas_{prefijo}_seccion")
            if forma.startswith("Rectangular"):
                canvas.plot_rectangular(r.geometria["b_m"], r.y_m)
            elif forma.startswith("Triangular"):
                canvas.plot_triangular(r.geometria["z"], r.y_m)
            elif forma == "Trapezoidal (máx. eficiencia)":
                canvas.plot_trapezoidal(r.geometria["b_m"], r.geometria["z"], r.y_m,
                                         titulo="Sección trapezoidal (máx. eficiencia, semihexágono)")
            elif forma == "Trapezoidal (geometría dada)":
                canvas.plot_trapezoidal(r.geometria["b_m"], r.geometria["z"], r.y_m,
                                         titulo="Sección trapezoidal (geometría dada)")
            elif forma == "Parabólico":
                canvas.plot_parabolico(r.geometria["T_m"], r.y_m)
            else:  # Irregular
                canvas.plot_irregular(puntos, r.y_m)

            self.resultados_hidraulica_drenaje[f"Canal/cuneta - {forma}"] = {
                "tipo": "Canal", "forma": r.forma, "n": n, "S": s, "Q_m3s": q,
                "tirante_normal_m": r.y_m, "area_m2": r.area_m2, "perimetro_m": r.perimetro_m,
                "radio_hidraulico_m": r.radio_hidraulico_m, "ancho_superior_m": r.ancho_superior_m,
                "velocidad_m_s": r.velocidad_m_s, "energia_especifica_m": r.energia_especifica_m,
                "numero_froude": r.numero_froude, "tipo_flujo": r.tipo_flujo,
                "tirante_critico_m": r.tirante_critico_m, "pendiente_critica": r.pendiente_critica,
                **r.geometria,
            }
        except Exception as e:
            lbl.setText(f"ERROR: {e}")

    # ---------------- Página: Alcantarilla ----------------
    def _pagina_alcantarilla(self) -> QWidget:
        pagina = QWidget()
        v = QVBoxLayout(pagina)
        _lbl_auto_17 = QLabel(
            "<b>Alcantarilla</b> — capacidad en régimen uniforme (Manning). NO reemplaza la "
            "verificación de control de entrada (inlet control); ver advertencia en el resultado."
        )
        _lbl_auto_17.setWordWrap(True)
        v.addWidget(_lbl_auto_17)
        f = QFormLayout()
        f.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        combo_tipo = QComboBox()
        combo_tipo.addItems(["Circular (tubería)", "Rectangular (cajón)"])
        f.addRow("Tipo:", combo_tipo)

        spin_n = QDoubleSpinBox(); spin_n.setRange(0.008, 0.2); spin_n.setDecimals(4); spin_n.setValue(0.013)
        f.addRow("Coef. de Manning n:", spin_n)
        spin_s = QDoubleSpinBox(); spin_s.setRange(0.0001, 1.0); spin_s.setDecimals(5); spin_s.setValue(0.01)
        f.addRow("Pendiente S (m/m):", spin_s)
        spin_diametro = QDoubleSpinBox(); spin_diametro.setRange(0.1, 5.0); spin_diametro.setDecimals(3); spin_diametro.setValue(1.0)
        f.addRow("Diámetro D (solo circular) (m):", spin_diametro)
        spin_ancho = QDoubleSpinBox(); spin_ancho.setRange(0.1, 10.0); spin_ancho.setDecimals(3); spin_ancho.setValue(1.5)
        f.addRow("Ancho (solo cajón) (m):", spin_ancho)
        spin_alto = QDoubleSpinBox(); spin_alto.setRange(0.1, 10.0); spin_alto.setDecimals(3); spin_alto.setValue(1.2)
        f.addRow("Altura máxima (solo cajón) (m):", spin_alto)
        spin_y = QDoubleSpinBox(); spin_y.setRange(0.01, 5.0); spin_y.setDecimals(3); spin_y.setValue(0.6)
        f.addRow("Tirante de trabajo y (m):", spin_y)

        v.addLayout(f)

        btn = QPushButton("Calcular capacidad")
        v.addWidget(btn)
        lbl = QLabel("Resultado: sin calcular.")
        lbl.setWordWrap(True)
        lbl.setStyleSheet("font-family: monospace;")
        v.addWidget(lbl)

        self.canvas_alcant_seccion = SeccionTransversalCanvas(pagina)
        v.addWidget(self.canvas_alcant_seccion)

        self.spin_alcant_n, self.spin_alcant_s = spin_n, spin_s
        self.combo_alcant_tipo = combo_tipo
        self.spin_alcant_diametro, self.spin_alcant_ancho = spin_diametro, spin_ancho
        self.spin_alcant_alto, self.spin_alcant_y = spin_alto, spin_y
        self.lbl_alcant_resultado = lbl

        btn.clicked.connect(self._on_calcular_alcantarilla)
        return pagina

    def _on_calcular_alcantarilla(self):
        try:
            n, s, y = self.spin_alcant_n.value(), self.spin_alcant_s.value(), self.spin_alcant_y.value()
            if self.combo_alcant_tipo.currentText().startswith("Circular"):
                r = hydraulic_structures.alcantarilla_circular_capacidad(n, s, self.spin_alcant_diametro.value(), y)
                extra_pct = f"% de área llena = {r['porcentaje_lleno_area']}%"
                self.canvas_alcant_seccion.plot_circular(self.spin_alcant_diametro.value(), y)
            else:
                r = hydraulic_structures.alcantarilla_cajon_capacidad(
                    n, s, self.spin_alcant_ancho.value(), self.spin_alcant_alto.value(), y
                )
                extra_pct = f"% de altura llena = {r['porcentaje_lleno_altura']}%"
                self.canvas_alcant_seccion.plot_cajon(self.spin_alcant_ancho.value(), self.spin_alcant_alto.value(), y)
            self.lbl_alcant_resultado.setText(
                f"Área = {r['area_m2']} m²   Perímetro = {r['perimetro_m']} m   "
                f"Radio hidráulico = {r['radio_hidraulico_m']} m ({extra_pct})\n"
                f"Caudal (capacidad) = {r['caudal_m3_s']} m³/s   Velocidad = {r['velocidad_m_s']} m/s\n\n"
                f"ADVERTENCIA: {r['advertencia']}"
            )
            self.resultados_hidraulica_drenaje[f"Alcantarilla - {self.combo_alcant_tipo.currentText()}"] = {
                "tipo": "Alcantarilla", "subtipo": self.combo_alcant_tipo.currentText(),
                "n": n, "S": s, "tirante_m": y,
                **{k: v for k, v in r.items() if k != "advertencia"},
            }
        except Exception as e:
            self.lbl_alcant_resultado.setText(f"ERROR: {e}")

    # ---------------- Página: Enrocado (RipRap) ----------------
    def _pagina_enrocado(self) -> QWidget:
        pagina = QWidget()
        v = QVBoxLayout(pagina)
        _lbl_auto_18 = QLabel(
            "<b>Enrocado (RipRap)</b> — dimensionamiento por la ecuación de Isbash (1936). "
            "Verifique contra el método vigente en su localidad antes de un diseño definitivo "
            "(ver nota en el resultado)."
        )
        _lbl_auto_18.setWordWrap(True)
        v.addWidget(_lbl_auto_18)
        f = QFormLayout()
        f.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        spin_v = QDoubleSpinBox(); spin_v.setRange(0.1, 20.0); spin_v.setDecimals(3); spin_v.setValue(3.0)
        f.addRow("Velocidad de diseño V (m/s):", spin_v)
        spin_peso = QDoubleSpinBox(); spin_peso.setRange(20.0, 30.0); spin_peso.setDecimals(2); spin_peso.setValue(26.0)
        f.addRow("Peso específico de la roca (kN/m³):", spin_peso)
        combo_exposicion = QComboBox()
        combo_exposicion.addItems(["Roca expuesta a la corriente (C=1.20)", "Roca embebida/protegida en el talud (C=0.86)"])
        f.addRow("Condición de exposición:", combo_exposicion)
        v.addLayout(f)

        btn = QPushButton("Calcular D50")
        v.addWidget(btn)
        lbl = QLabel("Resultado: sin calcular.")
        lbl.setWordWrap(True)
        lbl.setStyleSheet("font-family: monospace;")
        v.addWidget(lbl)

        def calcular():
            try:
                expuesta = combo_exposicion.currentIndex() == 0
                r = hydraulic_structures.enrocado_isbash(spin_v.value(), spin_peso.value(), expuesta)
                lbl.setText(
                    f"D50 = {r['D50_m']} m ({r['D50_cm']} cm)\n"
                    f"Gravedad específica de la roca = {r['gravedad_especifica_roca']}   "
                    f"Coeficiente de Isbash C = {r['coeficiente_isbash']}\n\n"
                    f"NOTA: {r['nota']}"
                )
                self.resultados_hidraulica_drenaje["Enrocado (RipRap)"] = {
                    "tipo": "Enrocado (RipRap)", "V_m_s": spin_v.value(), "peso_esp_roca_kN_m3": spin_peso.value(),
                    "D50_m": r["D50_m"], "D50_cm": r["D50_cm"], "gravedad_especifica_roca": r["gravedad_especifica_roca"],
                }
            except Exception as e:
                lbl.setText(f"ERROR: {e}")

        btn.clicked.connect(calcular)
        return pagina

    # ---------------- Página: Sumideros ----------------
    def _pagina_sumidero(self) -> QWidget:
        pagina = QWidget()
        v = QVBoxLayout(pagina)
        _lbl_auto_19 = QLabel(
            "<b>Sumideros</b> — capacidad simplificada como vertedero de ventana (weir). El diseño "
            "completo según HEC-22 requiere coeficientes propios del tipo de reja/ventana utilizada."
        )
        _lbl_auto_19.setWordWrap(True)
        v.addWidget(_lbl_auto_19)
        f = QFormLayout()
        f.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        spin_l = QDoubleSpinBox(); spin_l.setRange(0.1, 5.0); spin_l.setDecimals(3); spin_l.setValue(0.6)
        f.addRow("Longitud de la ventana/reja L (m):", spin_l)
        spin_y = QDoubleSpinBox(); spin_y.setRange(0.01, 1.0); spin_y.setDecimals(3); spin_y.setValue(0.08)
        f.addRow("Tirante sobre el sumidero y (m):", spin_y)
        spin_cw = QDoubleSpinBox(); spin_cw.setRange(1.0, 2.5); spin_cw.setDecimals(2); spin_cw.setValue(1.66)
        f.addRow("Coeficiente de vertedero Cw:", spin_cw)
        v.addLayout(f)

        btn = QPushButton("Calcular capacidad de intercepción")
        v.addWidget(btn)
        lbl = QLabel("Resultado: sin calcular.")
        lbl.setWordWrap(True)
        lbl.setStyleSheet("font-family: monospace;")
        v.addWidget(lbl)

        def calcular():
            try:
                r = hydraulic_structures.sumidero_capacidad_vertedero(spin_l.value(), spin_y.value(), spin_cw.value())
                lbl.setText(
                    f"Caudal interceptado = {r['caudal_interceptado_m3_s']} m³/s\n\n"
                    f"ADVERTENCIA: {r['advertencia']}"
                )
                self.resultados_hidraulica_drenaje["Sumidero"] = {
                    "tipo": "Sumidero", "L_m": spin_l.value(), "y_m": spin_y.value(), "Cw": spin_cw.value(),
                    "caudal_interceptado_m3_s": r["caudal_interceptado_m3_s"],
                }
            except Exception as e:
                lbl.setText(f"ERROR: {e}")

        btn.clicked.connect(calcular)
        return pagina

    # ---------------- Página: Pontón / Puente (verificación de borde libre) ----------------
    def _pagina_borde_libre(self, nombre_estructura: str) -> QWidget:
        pagina = QWidget()
        v = QVBoxLayout(pagina)
        _lbl_auto_20 = QLabel(
            f"<b>{nombre_estructura}</b> — verificación hidráulica básica (borde libre/revancha). "
            "NO es un diseño estructural, geotécnico ni de cimentación; eso requiere un análisis "
            "adicional fuera del alcance de este plugin."
        )
        _lbl_auto_20.setWordWrap(True)
        v.addWidget(_lbl_auto_20)
        f = QFormLayout()
        f.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        spin_cota_agua = QDoubleSpinBox(); spin_cota_agua.setRange(0.0, 8000.0); spin_cota_agua.setDecimals(2); spin_cota_agua.setValue(0.0)
        f.addRow("Cota de agua de diseño (m s.n.m.):", spin_cota_agua)
        spin_cota_estructura = QDoubleSpinBox(); spin_cota_estructura.setRange(0.0, 8000.0); spin_cota_estructura.setDecimals(2); spin_cota_estructura.setValue(0.0)
        f.addRow(f"Cota inferior de la superestructura ({nombre_estructura.lower()}) (m s.n.m.):", spin_cota_estructura)
        spin_bl_min = QDoubleSpinBox(); spin_bl_min.setRange(0.1, 5.0); spin_bl_min.setDecimals(2); spin_bl_min.setValue(1.0 if nombre_estructura == "Puente" else 0.6)
        f.addRow("Borde libre mínimo requerido (m):", spin_bl_min)
        v.addLayout(f)

        btn = QPushButton("Verificar borde libre")
        v.addWidget(btn)
        lbl = QLabel("Resultado: sin calcular.")
        lbl.setWordWrap(True)
        lbl.setStyleSheet("font-family: monospace;")
        v.addWidget(lbl)

        def calcular():
            try:
                r = hydraulic_structures.verificar_borde_libre(
                    spin_cota_agua.value(), spin_cota_estructura.value(), spin_bl_min.value()
                )
                estado = "✔ CUMPLE" if r["cumple"] else "✘ NO CUMPLE"
                lbl.setText(
                    f"Borde libre disponible = {r['borde_libre_disponible_m']} m "
                    f"(mínimo requerido = {r['borde_libre_minimo_requerido_m']} m)   [{estado}]\n"
                    f"{r['mensaje']}\n\nNOTA: {r['nota']}"
                )
                self.resultados_hidraulica_drenaje[nombre_estructura] = {
                    "tipo": nombre_estructura, "cota_agua_m": spin_cota_agua.value(),
                    "cota_estructura_m": spin_cota_estructura.value(),
                    "borde_libre_disponible_m": r["borde_libre_disponible_m"], "cumple": r["cumple"],
                }
            except Exception as e:
                lbl.setText(f"ERROR: {e}")

        btn.clicked.connect(calcular)
        return pagina

    # ---------------- Página: Defensa Ribereña (borde libre + enrocado) ----------------
    def _pagina_defensa_ribereña(self) -> QWidget:
        pagina = QWidget()
        v = QVBoxLayout(pagina)
        _lbl_auto_21 = QLabel(
            "<b>Defensa Ribereña</b> — verificación de borde libre de la corona respecto al nivel de "
            "agua de diseño, y dimensionamiento del enrocado de protección del talud (Isbash). NO "
            "reemplaza el diseño geotécnico/estructural de la defensa."
        )
        _lbl_auto_21.setWordWrap(True)
        v.addWidget(_lbl_auto_21)
        f = QFormLayout()
        f.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        spin_cota_agua = QDoubleSpinBox(); spin_cota_agua.setRange(0.0, 8000.0); spin_cota_agua.setDecimals(2)
        f.addRow("Cota de agua de diseño (m s.n.m.):", spin_cota_agua)
        spin_cota_corona = QDoubleSpinBox(); spin_cota_corona.setRange(0.0, 8000.0); spin_cota_corona.setDecimals(2)
        f.addRow("Cota de corona de la defensa (m s.n.m.):", spin_cota_corona)
        spin_bl_min = QDoubleSpinBox(); spin_bl_min.setRange(0.1, 5.0); spin_bl_min.setDecimals(2); spin_bl_min.setValue(0.6)
        f.addRow("Borde libre mínimo requerido (m):", spin_bl_min)
        spin_v = QDoubleSpinBox(); spin_v.setRange(0.1, 20.0); spin_v.setDecimals(3); spin_v.setValue(3.0)
        f.addRow("Velocidad de diseño junto al talud V (m/s):", spin_v)
        spin_peso = QDoubleSpinBox(); spin_peso.setRange(20.0, 30.0); spin_peso.setDecimals(2); spin_peso.setValue(26.0)
        f.addRow("Peso específico de la roca (kN/m³):", spin_peso)
        v.addLayout(f)

        btn = QPushButton("Verificar")
        v.addWidget(btn)
        lbl = QLabel("Resultado: sin calcular.")
        lbl.setWordWrap(True)
        lbl.setStyleSheet("font-family: monospace;")
        v.addWidget(lbl)

        def calcular():
            try:
                r_bl = hydraulic_structures.verificar_borde_libre(
                    spin_cota_agua.value(), spin_cota_corona.value(), spin_bl_min.value()
                )
                r_rip = hydraulic_structures.enrocado_isbash(spin_v.value(), spin_peso.value(), roca_expuesta=True)
                estado = "✔ CUMPLE" if r_bl["cumple"] else "✘ NO CUMPLE"
                lbl.setText(
                    f"Borde libre disponible = {r_bl['borde_libre_disponible_m']} m   [{estado}]\n"
                    f"Enrocado de protección: D50 = {r_rip['D50_m']} m ({r_rip['D50_cm']} cm)\n\n"
                    f"NOTA: {r_bl['nota']}\n{r_rip['nota']}"
                )
                self.resultados_hidraulica_drenaje["Defensa Ribereña"] = {
                    "tipo": "Defensa Ribereña", "cota_agua_m": spin_cota_agua.value(),
                    "cota_corona_m": spin_cota_corona.value(),
                    "borde_libre_disponible_m": r_bl["borde_libre_disponible_m"], "cumple": r_bl["cumple"],
                    "D50_m": r_rip["D50_m"], "D50_cm": r_rip["D50_cm"],
                }
            except Exception as e:
                lbl.setText(f"ERROR: {e}")

        btn.clicked.connect(calcular)
        return pagina

    # ------------------------------------------------------------------
    # TAB 8: Módulos Avanzados (completación de datos, precipitación
    # areal, oferta hídrica)
    # ------------------------------------------------------------------
    def _build_tab_modulos_avanzados(self):
        tab = QWidget()
        v = QVBoxLayout(tab)
        _lbl_auto_22 = QLabel(
            "<b>Módulos Avanzados (Beta)</b> — completación de datos faltantes, precipitación areal "
            "multi-método, y oferta hídrica (disponibilidad de agua a largo plazo, en contraste con "
            "el resto del plugin orientado a crecidas). Requieren que usted pegue los datos "
            "directamente (no están conectados automáticamente a las demás pestañas)."
        )
        _lbl_auto_22.setWordWrap(True)
        v.addWidget(_lbl_auto_22)

        combo_modulo = QComboBox()
        combo_modulo.addItems(["Completación de Datos", "Precipitación Areal", "Oferta Hídrica"])
        v.addWidget(combo_modulo)

        stack = QStackedWidget()
        stack.addWidget(self._pagina_completacion_datos())
        stack.addWidget(self._pagina_precipitacion_areal())
        stack.addWidget(self._pagina_oferta_hidrica())
        combo_modulo.currentIndexChanged.connect(stack.setCurrentIndex)
        v.addWidget(stack)

        self._agregar_pestaña_con_scroll(tab, "9. Módulos Avanzados")

    def _pagina_completacion_datos(self) -> QWidget:
        pagina = QWidget()
        v = QVBoxLayout(pagina)
        _lbl_auto_23 = QLabel(
            "Una fila por estación: <b>nombre: valor1,valor2,...</b> (use 'NaN' para los datos "
            "faltantes a completar). Todas las estaciones deben tener la misma cantidad de valores."
        )
        _lbl_auto_23.setWordWrap(True)
        v.addWidget(_lbl_auto_23)
        self.edit_completacion_series = QPlainTextEdit()
        self.edit_completacion_series.setPlaceholderText(
            "A: 30.1,28.4,NaN,31.0,29.5\nB: 27.9,26.0,25.1,28.2,27.0\nC: 33.2,NaN,30.8,32.9,31.5"
        )
        self.edit_completacion_series.setMaximumHeight(120)
        v.addWidget(self.edit_completacion_series)

        f = QFormLayout()
        f.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.edit_completacion_coords = QLineEdit()
        self.edit_completacion_coords.setPlaceholderText("Solo para IDW — nombre:x,y; nombre:x,y; ... (metros)")
        f.addRow("Coordenadas (IDW):", self.edit_completacion_coords)
        self.edit_completacion_objetivo = QLineEdit()
        self.edit_completacion_objetivo.setPlaceholderText("Nombre exacto de la estación a completar")
        f.addRow("Estación objetivo:", self.edit_completacion_objetivo)
        v.addLayout(f)

        h = QHBoxLayout()
        for etiqueta, metodo in [("IDW", "idw"), ("Regresión Múltiple", "regresion"),
                                   ("Random Forest", "rf"), ("Vector Regional", "vr")]:
            btn = QPushButton(etiqueta)
            btn.clicked.connect(lambda checked, m=metodo: self._on_completar_datos(m))
            h.addWidget(btn)
        v.addLayout(h)

        self.lbl_resultado_completacion = QLabel("Resultado: sin calcular.")
        self.lbl_resultado_completacion.setWordWrap(True)
        self.lbl_resultado_completacion.setStyleSheet("font-family: monospace;")
        v.addWidget(self.lbl_resultado_completacion)
        return pagina

    def _parsear_series_multiestacion(self, texto: str) -> dict:
        series = {}
        for linea in texto.strip().splitlines():
            if ":" not in linea:
                continue
            nombre, valores_str = linea.split(":", 1)
            valores = [float(v.strip()) if v.strip().lower() != "nan" else float("nan")
                       for v in valores_str.split(",") if v.strip()]
            series[nombre.strip()] = valores
        if not series:
            raise ValueError("No se reconoció ninguna serie. Use el formato 'nombre: v1,v2,v3,...'.")
        return series

    def _on_completar_datos(self, metodo: str):
        try:
            series = self._parsear_series_multiestacion(self.edit_completacion_series.toPlainText())
            objetivo = self.edit_completacion_objetivo.text().strip()
            if metodo == "vr":
                r = data_completion.completar_vector_regional(series)
                self.lbl_resultado_completacion.setText(
                    f"[Vector Regional] índice regional por periodo: {r['indice_regional_por_periodo']}\n"
                    f"Series completadas: {r['series_completadas']}"
                )
                return
            if not objetivo:
                QMessageBox.warning(self, "Falta la estación objetivo", "Indique el nombre de la estación a completar.")
                return
            if metodo == "idw":
                coords = {}
                for par in self.edit_completacion_coords.text().split(";"):
                    if ":" in par:
                        nom, xy = par.split(":", 1)
                        x, y = xy.split(",")
                        coords[nom.strip()] = (float(x), float(y))
                r = data_completion.completar_idw(series, coords, objetivo)
                self.lbl_resultado_completacion.setText(f"[IDW] Serie completada de '{objetivo}': {r}")
            elif metodo == "regresion":
                r = data_completion.completar_regresion_multiple(series, objetivo)
                self.lbl_resultado_completacion.setText(
                    f"[Regresión Múltiple] R²={r['r2_ajuste']}  coeficientes={r['coeficientes']}\n"
                    f"Serie completada: {r['serie_completada']}"
                )
            else:  # rf
                r = data_completion.completar_random_forest(series, objetivo)
                self.lbl_resultado_completacion.setText(
                    f"[Random Forest] R²(entrenamiento)={r['r2_ajuste_entrenamiento']}  "
                    f"importancia={r['importancia_variables']}\nSerie completada: {r['serie_completada']}"
                )
        except (data_completion.DataCompletionError, ValueError) as e:
            QMessageBox.warning(self, "No se pudo completar", str(e))

    def _pagina_precipitacion_areal(self) -> QWidget:
        pagina = QWidget()
        v = QVBoxLayout(pagina)
        _lbl_auto_24 = QLabel(
            "Formato: <b>nombre: valor_mm, x, y</b> (una estación por fila, coordenadas en metros, "
            "mismo CRS proyectado que la cuenca). La cuenca se toma de la delimitación activa "
            "(pestaña 1)."
        )
        _lbl_auto_24.setWordWrap(True)
        v.addWidget(_lbl_auto_24)
        self.edit_areal_estaciones = QPlainTextEdit()
        self.edit_areal_estaciones.setPlaceholderText("A: 35.2, 450000, 8500000\nB: 28.9, 452000, 8503000\n...")
        self.edit_areal_estaciones.setMaximumHeight(120)
        v.addWidget(self.edit_areal_estaciones)

        h = QHBoxLayout()
        for etiqueta, metodo in [("Thiessen", "thiessen"), ("IDW", "idw"), ("RBF", "rbf"), ("Kriging Ordinario", "kriging")]:
            btn = QPushButton(etiqueta)
            btn.clicked.connect(lambda checked, m=metodo: self._on_calcular_precip_areal(m))
            h.addWidget(btn)
        v.addLayout(h)

        self.lbl_resultado_areal = QLabel("Resultado: sin calcular.")
        self.lbl_resultado_areal.setWordWrap(True)
        self.lbl_resultado_areal.setStyleSheet("font-family: monospace;")
        v.addWidget(self.lbl_resultado_areal)
        return pagina

    def _obtener_vertices_cuenca_activa(self):
        if self.cuenca_layer is None:
            raise ValueError("No hay una cuenca delimitada activa (pestaña 1).")
        feats = list(self.cuenca_layer.getFeatures())
        if not feats:
            raise ValueError("La capa de cuenca activa no tiene entidades.")
        geom = feats[0].geometry()
        poligono = geom.asMultiPolygon()[0][0] if geom.isMultipart() else geom.asPolygon()[0]
        return [(p.x(), p.y()) for p in poligono]

    def _parsear_estaciones_areal(self, texto: str):
        valores, coords = {}, {}
        for linea in texto.strip().splitlines():
            if ":" not in linea:
                continue
            nombre, resto = linea.split(":", 1)
            partes = [p.strip() for p in resto.split(",")]
            if len(partes) < 3:
                continue
            nombre = nombre.strip()
            valores[nombre] = float(partes[0])
            coords[nombre] = (float(partes[1]), float(partes[2]))
        if not valores:
            raise ValueError("No se reconoció ninguna estación. Use el formato 'nombre: valor, x, y'.")
        return valores, coords

    def _on_calcular_precip_areal(self, metodo: str):
        try:
            valores, coords = self._parsear_estaciones_areal(self.edit_areal_estaciones.toPlainText())
            vertices = self._obtener_vertices_cuenca_activa()
            if metodo == "thiessen":
                QMessageBox.information(
                    self, "Thiessen",
                    "El cálculo automático de polígonos de Thiessen recortados a la cuenca requiere "
                    "generarlos en el lienzo de QGIS (native:voronoipolygons + intersección). Genere "
                    "esa capa y use core.areal_precipitation.precipitacion_thiessen() con las áreas "
                    "resultantes; por ahora los otros 3 métodos (IDW/RBF/Kriging) no requieren ese paso."
                )
                return
            elif metodo == "idw":
                r = areal_precipitation.precipitacion_idw(valores, coords, vertices)
            elif metodo == "rbf":
                r = areal_precipitation.precipitacion_rbf(valores, coords, vertices)
            else:
                r = areal_precipitation.precipitacion_kriging_ordinario(valores, coords, vertices)
            self.lbl_resultado_areal.setText(
                f"[{metodo.upper()}] Precipitación areal = {r['precipitacion_areal_mm']} mm  "
                f"({r.get('n_puntos_grilla', '?')} puntos de grilla)"
                + (f"\nVariograma: {r['variograma_ajustado']}\n{r['nota']}" if "variograma_ajustado" in r else "")
            )
        except (areal_precipitation.ArealPrecipitationError, ValueError) as e:
            QMessageBox.warning(self, "No se pudo calcular", str(e))

    def _pagina_oferta_hidrica(self) -> QWidget:
        pagina = QWidget()
        v = QVBoxLayout(pagina)
        _lbl_auto_25 = QLabel(
            "<b>Oferta hídrica</b> — disponibilidad de agua a largo plazo (distinto del resto del "
            "plugin, orientado a crecidas). Los modelos 2 y 3 requieren calibración contra caudales "
            "observados para ser confiables; ver advertencias en cada resultado."
        )
        _lbl_auto_25.setWordWrap(True)
        v.addWidget(_lbl_auto_25)
        combo_modelo = QComboBox()
        combo_modelo.addItems(["Budyko/Fu (anual)", "Balance mensual simplificado (tipo GR2M)", "Lutz Scholz (estructura general)"])
        v.addWidget(combo_modelo)

        f = QFormLayout()
        f.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.spin_of_p = QDoubleSpinBox(); self.spin_of_p.setRange(1, 10000); self.spin_of_p.setValue(800)
        f.addRow("P anual (mm, solo Budyko):", self.spin_of_p)
        self.spin_of_pet = QDoubleSpinBox(); self.spin_of_pet.setRange(1, 10000); self.spin_of_pet.setValue(900)
        f.addRow("PET anual (mm, solo Budyko):", self.spin_of_pet)
        self.spin_of_w = QDoubleSpinBox(); self.spin_of_w.setRange(1.0, 10.0); self.spin_of_w.setValue(2.6)
        f.addRow("w de Fu (solo Budyko):", self.spin_of_w)
        v.addLayout(f)

        v.addWidget(QLabel("P y PET mensuales (mm), separados por coma, para los modelos 2 y 3:"))
        self.edit_of_p_mensual = QLineEdit()
        v.addWidget(self.edit_of_p_mensual)
        self.edit_of_etp_mensual = QLineEdit()
        v.addWidget(self.edit_of_etp_mensual)

        f2 = QFormLayout()
        f2.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.spin_of_x1 = QDoubleSpinBox(); self.spin_of_x1.setRange(1, 2000); self.spin_of_x1.setValue(200)
        f2.addRow("X1 - capacidad de producción (mm, modelo 2):", self.spin_of_x1)
        self.spin_of_x2 = QDoubleSpinBox(); self.spin_of_x2.setRange(0.1, 5.0); self.spin_of_x2.setValue(1.1)
        f2.addRow("X2 - coeficiente de intercambio (modelo 2):", self.spin_of_x2)
        self.spin_of_a = QDoubleSpinBox(); self.spin_of_a.setRange(0.0, 1.0); self.spin_of_a.setValue(0.3)
        f2.addRow("a - coef. de retención (0-1, modelo 3 Lutz Scholz):", self.spin_of_a)
        self.spin_of_b = QDoubleSpinBox(); self.spin_of_b.setRange(0.0, 1.0); self.spin_of_b.setValue(0.8)
        f2.addRow("b - coef. de agotamiento (0-1, modelo 3 Lutz Scholz):", self.spin_of_b)
        self.spin_of_area = QDoubleSpinBox(); self.spin_of_area.setRange(0.01, 100000); self.spin_of_area.setDecimals(3)
        f2.addRow("Área de la cuenca (km², modelo 3):", self.spin_of_area)
        v.addLayout(f2)

        btn_calc = QPushButton("Calcular")
        v.addWidget(btn_calc)
        self.lbl_resultado_oferta = QLabel("Resultado: sin calcular.")
        self.lbl_resultado_oferta.setWordWrap(True)
        self.lbl_resultado_oferta.setStyleSheet("font-family: monospace;")
        v.addWidget(self.lbl_resultado_oferta)

        btn_calc.clicked.connect(lambda: self._on_calcular_oferta_hidrica(combo_modelo.currentIndex()))
        return pagina

    def _on_calcular_oferta_hidrica(self, indice_modelo: int):
        try:
            if indice_modelo == 0:
                r = water_yield.balance_budyko_fu(self.spin_of_p.value(), self.spin_of_pet.value(), self.spin_of_w.value())
                self.lbl_resultado_oferta.setText(
                    f"Índice de aridez = {r['indice_aridez_PET_P']}\n"
                    f"AET = {r['AET_mm']} mm   Escorrentía = {r['escorrentia_mm']} mm   "
                    f"Coef. de escorrentía = {r['coeficiente_escorrentia']}"
                )
                return
            p_mensual = [float(x) for x in self.edit_of_p_mensual.text().split(",") if x.strip()]
            etp_mensual = [float(x) for x in self.edit_of_etp_mensual.text().split(",") if x.strip()]
            if not p_mensual or not etp_mensual:
                QMessageBox.warning(self, "Faltan datos", "Ingrese las series mensuales de P y PET separadas por coma.")
                return
            if indice_modelo == 1:
                r = water_yield.balance_mensual_simplificado(p_mensual, etp_mensual, self.spin_of_x1.value(), self.spin_of_x2.value())
                self.lbl_resultado_oferta.setText(
                    f"Caudal medio mensual = {r['caudal_medio_mensual_mm']} mm\n"
                    f"Caudal mensual: {r['caudal_mensual_mm']}\n\nNOTA: {r['nota']}"
                )
            else:
                r = water_yield.balance_lutz_scholz(p_mensual, etp_mensual, self.spin_of_a.value(),
                                                     self.spin_of_b.value(), self.spin_of_area.value())
                self.lbl_resultado_oferta.setText(
                    f"Caudal medio = {r['caudal_medio_m3s']} m³/s\nPersistencia: {r['persistencia']}\n"
                    f"Caudal mensual (m³/s): {r['caudal_mensual_m3s']}\n\nNOTA: {r['nota']}"
                )
        except (water_yield.WaterYieldError, ValueError) as e:
            QMessageBox.warning(self, "No se pudo calcular", str(e))

    # ------------------------------------------------------------------
    # TAB 10: Socavación (general, por contracción y local; cohesivos y
    # no cohesivos). Ver core/scour.py para las fórmulas y fuentes.
    # ------------------------------------------------------------------
    def _build_tab_socavacion(self):
        tab = QWidget()
        v = QVBoxLayout(tab)
        _lbl_auto_26 = QLabel(
            "<b>Socavación</b> — socavación GENERAL (Lischtvan-Lebediev cohesivo/no cohesivo, Lacey, "
            "Blench, Neill-Kellerhals), por CONTRACCIÓN (Laursen, agua clara / lecho móvil) y LOCAL en "
            "pilares (CSU/HEC-RAS, Froehlich). Ingrese la curva granulométrica para obtener D50/D36≈D35/"
            "D84 automáticamente (o ingréselos manualmente), cree una o más secciones transversales "
            "(desde el GIS mediante una línea trazada sobre el MDE, o pegando una tabla tipo Excel) y "
            "calcule con los métodos que aplique a su caso. Los resultados muestran la sección CON y SIN "
            "socavación, y un cuadro comparativo final entre métodos."
        )
        _lbl_auto_26.setWordWrap(True)
        v.addWidget(_lbl_auto_26)

        # ---------------- Curva granulométrica ----------------
        gb_granulo = QGroupBox("1. Curva granulométrica y diámetros característicos")
        v_g = QVBoxLayout(gb_granulo)
        _lbl_auto_27 = QLabel(
            "Pegue (Ctrl+V) desde Excel dos columnas: Diámetro (mm) y % que pasa. Ordénelas de menor "
            "a mayor diámetro (no es obligatorio, el cálculo las reordena)."
        )
        _lbl_auto_27.setWordWrap(True)
        v_g.addWidget(_lbl_auto_27)
        self.tabla_granulometria = TablaPegable(8, 2)
        self.tabla_granulometria.setHorizontalHeaderLabels(["Diámetro (mm)", "% que pasa"])
        self.tabla_granulometria.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla_granulometria.setMinimumHeight(200)
        v_g.addWidget(self.tabla_granulometria)

        h_g_btn = QHBoxLayout()
        btn_calc_diam = QPushButton("Calcular D16/D35/D50/D65/D84/D90 y Dm desde la curva")
        btn_calc_diam.clicked.connect(self._on_calcular_diametros_socavacion)
        h_g_btn.addWidget(btn_calc_diam)
        btn_graficar_granulo = QPushButton("Graficar curva granulométrica")
        btn_graficar_granulo.clicked.connect(self._on_graficar_granulometria)
        h_g_btn.addWidget(btn_graficar_granulo)
        v_g.addLayout(h_g_btn)

        f_diam = QFormLayout()
        f_diam.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.spin_d16 = QDoubleSpinBox(); self.spin_d16.setRange(0.0001, 5000); self.spin_d16.setDecimals(4)
        self.spin_d35 = QDoubleSpinBox(); self.spin_d35.setRange(0.0001, 5000); self.spin_d35.setDecimals(4)
        self.spin_d50 = QDoubleSpinBox(); self.spin_d50.setRange(0.0001, 5000); self.spin_d50.setDecimals(4)
        self.spin_d65 = QDoubleSpinBox(); self.spin_d65.setRange(0.0001, 5000); self.spin_d65.setDecimals(4)
        self.spin_d84 = QDoubleSpinBox(); self.spin_d84.setRange(0.0001, 5000); self.spin_d84.setDecimals(4)
        self.spin_d90 = QDoubleSpinBox(); self.spin_d90.setRange(0.0001, 5000); self.spin_d90.setDecimals(4)
        self.spin_dm_socavacion = QDoubleSpinBox(); self.spin_dm_socavacion.setRange(0.0001, 5000); self.spin_dm_socavacion.setDecimals(4)
        for etiqueta, spin in [("D16 (mm) — también editable manualmente:", self.spin_d16),
                               ("D35 ≈ D36 (mm):", self.spin_d35),
                               ("D50 (mm):", self.spin_d50),
                               ("D65 (mm):", self.spin_d65),
                               ("D84 (mm):", self.spin_d84),
                               ("D90 (mm):", self.spin_d90),
                               ("Dm — diámetro medio ponderado (mm), usado en Lischtvan-Lebediev/Lacey/Blench/Laursen:", self.spin_dm_socavacion)]:
            f_diam.addRow(etiqueta, spin)
        v_g.addLayout(f_diam)
        v.addWidget(gb_granulo)

        # ---------------- Material del lecho ----------------
        gb_material = QGroupBox("2. Tipo de material del lecho")
        f_mat = QFormLayout(gb_material)
        f_mat.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        h_tipo = QHBoxLayout()
        self.radio_no_cohesivo = QRadioButton("No cohesivo (arenas, gravas — usa Dm)")
        self.radio_cohesivo = QRadioButton("Cohesivo (limos/arcillas — usa peso específico seco γd)")
        self.radio_no_cohesivo.setChecked(True)
        grupo_tipo_suelo = QButtonGroup(self)
        grupo_tipo_suelo.addButton(self.radio_no_cohesivo)
        grupo_tipo_suelo.addButton(self.radio_cohesivo)
        h_tipo.addWidget(self.radio_no_cohesivo)
        h_tipo.addWidget(self.radio_cohesivo)
        f_mat.addRow(h_tipo)
        self.spin_gamma_d = QDoubleSpinBox()
        self.spin_gamma_d.setRange(0.5, 2.2)
        self.spin_gamma_d.setDecimals(2)
        self.spin_gamma_d.setValue(1.20)
        f_mat.addRow("γd — peso específico seco del suelo cohesivo (t/m³):", self.spin_gamma_d)
        v.addWidget(gb_material)

        # ---------------- Gestión de secciones transversales ----------------
        gb_secciones = QGroupBox("3. Secciones transversales de estudio (puede crear varias)")
        v_s = QVBoxLayout(gb_secciones)

        h_gen = QHBoxLayout()
        h_gen.addWidget(QLabel("Número de secciones a crear:"))
        self.spin_num_secciones_socavacion = QSpinBox()
        self.spin_num_secciones_socavacion.setRange(1, 30)
        self.spin_num_secciones_socavacion.setValue(1)
        h_gen.addWidget(self.spin_num_secciones_socavacion)
        btn_generar_secciones = QPushButton("Generar secciones")
        btn_generar_secciones.clicked.connect(self._on_generar_secciones_socavacion)
        h_gen.addWidget(btn_generar_secciones)
        h_gen.addWidget(QLabel("Sección activa:"))
        self.combo_seccion_socavacion_activa = QComboBox()
        self.combo_seccion_socavacion_activa.currentTextChanged.connect(self._on_cambiar_seccion_socavacion_activa)
        h_gen.addWidget(self.combo_seccion_socavacion_activa)
        v_s.addLayout(h_gen)

        h_origen = QHBoxLayout()
        h_origen.addWidget(QLabel("Origen de los datos de esta sección:"))
        self.combo_origen_seccion_socavacion = QComboBox()
        self.combo_origen_seccion_socavacion.addItems([
            "Manual (pegar tabla tipo Excel)", "Desde GIS (MDE + línea trazada en el mapa)"
        ])
        h_origen.addWidget(self.combo_origen_seccion_socavacion)
        self.combo_dem_socavacion = QgsMapLayerComboBox()
        self.combo_dem_socavacion.setFilters(QgsMapLayerProxyModel.RasterLayer)
        h_origen.addWidget(QLabel("MDE:"))
        h_origen.addWidget(self.combo_dem_socavacion)
        self.btn_trazar_seccion_socavacion = QPushButton("Trazar línea de sección en el mapa (2 clics)")
        self.btn_trazar_seccion_socavacion.setCheckable(True)
        self.btn_trazar_seccion_socavacion.clicked.connect(self._activar_map_tool_socavacion)
        h_origen.addWidget(self.btn_trazar_seccion_socavacion)
        v_s.addLayout(h_origen)

        _lbl_auto_28 = QLabel(
            "Estación, elevación del fondo y velocidad media de esa vertical (si la extrajo del GIS, "
            "la columna de velocidad queda vacía y debe completarla con los resultados de su cálculo "
            "hidráulico en el punto de interés; puede pegar una sola velocidad media en todas las filas)."
        )
        _lbl_auto_28.setWordWrap(True)
        v_s.addWidget(_lbl_auto_28)
        self.tabla_seccion_socavacion = TablaPegable(10, 3)
        self.tabla_seccion_socavacion.setHorizontalHeaderLabels(
            ["Estación (m)", "Elevación fondo (m s.n.m.)", "Velocidad media (m/s)"])
        self.tabla_seccion_socavacion.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla_seccion_socavacion.setMinimumHeight(220)
        v_s.addWidget(self.tabla_seccion_socavacion)

        f_hid = QFormLayout()
        f_hid.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.spin_q_socavacion = QDoubleSpinBox(); self.spin_q_socavacion.setRange(0.01, 200000); self.spin_q_socavacion.setDecimals(2); self.spin_q_socavacion.setValue(100.0)
        f_hid.addRow("Caudal de diseño Q (m³/s):", self.spin_q_socavacion)
        self.spin_be_socavacion = QDoubleSpinBox(); self.spin_be_socavacion.setRange(0.1, 5000); self.spin_be_socavacion.setDecimals(2); self.spin_be_socavacion.setValue(30.0)
        f_hid.addRow("Ancho efectivo Be (m):", self.spin_be_socavacion)
        self.spin_mu_socavacion = QDoubleSpinBox(); self.spin_mu_socavacion.setRange(0.5, 1.0); self.spin_mu_socavacion.setDecimals(3); self.spin_mu_socavacion.setValue(1.0)
        f_hid.addRow("Coeficiente de contracción μ (1.0 = sin contracción):", self.spin_mu_socavacion)
        self.spin_tr_socavacion = QDoubleSpinBox(); self.spin_tr_socavacion.setRange(2, 1000); self.spin_tr_socavacion.setDecimals(0); self.spin_tr_socavacion.setValue(100)
        f_hid.addRow("Periodo de retorno Tr (años, para β de Lischtvan-Lebediev):", self.spin_tr_socavacion)
        self.spin_nivel_agua_socavacion = QDoubleSpinBox(); self.spin_nivel_agua_socavacion.setRange(-1000, 9000); self.spin_nivel_agua_socavacion.setDecimals(2); self.spin_nivel_agua_socavacion.setValue(100.0)
        f_hid.addRow("Nivel de agua de diseño (m s.n.m.):", self.spin_nivel_agua_socavacion)
        v_s.addLayout(f_hid)
        btn_nivel_desde_tirante = QPushButton("Fijar nivel de agua = cota mínima de la sección + tirante medio")
        btn_nivel_desde_tirante.clicked.connect(self._on_fijar_nivel_agua_desde_tirante)
        v_s.addWidget(btn_nivel_desde_tirante)
        self.spin_tirante_medio_socavacion = QDoubleSpinBox()
        self.spin_tirante_medio_socavacion.setRange(0.01, 100)
        self.spin_tirante_medio_socavacion.setDecimals(2)
        self.spin_tirante_medio_socavacion.setValue(3.0)
        f_hid.addRow("Tirante medio de diseño (m), para el botón anterior:", self.spin_tirante_medio_socavacion)

        # -- socavación local (pilares) --
        gb_local = QGroupBox("Socavación local en pilar/estribo (opcional para esta sección)")
        self.chk_incluir_local_socavacion = QCheckBox("Incluir socavación local en esta sección")
        f_local = QFormLayout(gb_local)
        f_local.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        f_local.addRow(self.chk_incluir_local_socavacion)
        self.spin_estacion_pilar = QDoubleSpinBox(); self.spin_estacion_pilar.setRange(-10000, 10000); self.spin_estacion_pilar.setDecimals(2)
        f_local.addRow("Estación del pilar/estribo (m, dentro de la tabla):", self.spin_estacion_pilar)
        self.spin_ancho_pilar = QDoubleSpinBox(); self.spin_ancho_pilar.setRange(0.1, 30); self.spin_ancho_pilar.setDecimals(2); self.spin_ancho_pilar.setValue(1.5)
        f_local.addRow("Ancho de la pila a (m):", self.spin_ancho_pilar)
        self.spin_longitud_pilar = QDoubleSpinBox(); self.spin_longitud_pilar.setRange(0.1, 60); self.spin_longitud_pilar.setDecimals(2); self.spin_longitud_pilar.setValue(6.0)
        f_local.addRow("Longitud de la pila L (m):", self.spin_longitud_pilar)
        self.spin_angulo_ataque = QDoubleSpinBox(); self.spin_angulo_ataque.setRange(0, 90); self.spin_angulo_ataque.setDecimals(1)
        f_local.addRow("Ángulo de ataque del flujo θ (°):", self.spin_angulo_ataque)
        self.combo_forma_pilar = QComboBox()
        self.combo_forma_pilar.addItems(["Redonda/cilíndrica (K1=1.0, Kf=1.0)", "Cuadrada (K1=1.1, Kf=1.3)", "Aguda/afilada (K1=0.9, Kf=0.7)"])
        f_local.addRow("Forma de la nariz de la pila:", self.combo_forma_pilar)
        self.combo_condicion_lecho_csu = QComboBox()
        self.combo_condicion_lecho_csu.addItems(["Lecho plano / aguas claras (K3=1.1)", "Dunas medianas (K3=1.2)", "Dunas grandes (K3=1.3)"])
        f_local.addRow("Condición del lecho (K3, CSU):", self.combo_condicion_lecho_csu)
        self.spin_k4_acorazamiento = QDoubleSpinBox(); self.spin_k4_acorazamiento.setRange(0.4, 1.0); self.spin_k4_acorazamiento.setDecimals(2); self.spin_k4_acorazamiento.setValue(1.0)
        f_local.addRow("K4 — corrección por acorazamiento (1.0 si D50<2mm):", self.spin_k4_acorazamiento)
        v_s.addWidget(gb_local)

        # -- socavación por contracción --
        gb_contraccion = QGroupBox("Socavación por contracción — Laursen (opcional para esta sección)")
        self.chk_incluir_contraccion_socavacion = QCheckBox("Incluir socavación por contracción en esta sección")
        f_contr = QFormLayout(gb_contraccion)
        f_contr.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        f_contr.addRow(self.chk_incluir_contraccion_socavacion)
        self.combo_modo_laursen = QComboBox()
        self.combo_modo_laursen.addItems(["Automático (criterio de Shields, τ0 vs τc)", "Forzar agua clara", "Forzar lecho móvil"])
        f_contr.addRow("Modo:", self.combo_modo_laursen)
        self.spin_q1_contraccion = QDoubleSpinBox(); self.spin_q1_contraccion.setRange(0.01, 200000); self.spin_q1_contraccion.setDecimals(2); self.spin_q1_contraccion.setValue(100.0)
        f_contr.addRow("Q1 — caudal sección de aproximación (m³/s):", self.spin_q1_contraccion)
        self.spin_w1_contraccion = QDoubleSpinBox(); self.spin_w1_contraccion.setRange(0.1, 5000); self.spin_w1_contraccion.setDecimals(2); self.spin_w1_contraccion.setValue(40.0)
        f_contr.addRow("W1 — ancho sección de aproximación (m):", self.spin_w1_contraccion)
        self.spin_w2_contraccion = QDoubleSpinBox(); self.spin_w2_contraccion.setRange(0.1, 5000); self.spin_w2_contraccion.setDecimals(2); self.spin_w2_contraccion.setValue(25.0)
        f_contr.addRow("W2 — ancho de la sección contraída (m):", self.spin_w2_contraccion)
        self.spin_y1_contraccion = QDoubleSpinBox(); self.spin_y1_contraccion.setRange(0.01, 100); self.spin_y1_contraccion.setDecimals(2); self.spin_y1_contraccion.setValue(3.0)
        f_contr.addRow("y1 — tirante en la sección de aproximación (m):", self.spin_y1_contraccion)
        self.spin_pendiente_contraccion = QDoubleSpinBox(); self.spin_pendiente_contraccion.setRange(0.0001, 0.2); self.spin_pendiente_contraccion.setDecimals(4); self.spin_pendiente_contraccion.setValue(0.01)
        f_contr.addRow("Pendiente de la línea de energía S (m/m):", self.spin_pendiente_contraccion)
        self.spin_radio_hidraulico_contraccion = QDoubleSpinBox(); self.spin_radio_hidraulico_contraccion.setRange(0.01, 50); self.spin_radio_hidraulico_contraccion.setDecimals(2); self.spin_radio_hidraulico_contraccion.setValue(2.5)
        f_contr.addRow("Radio hidráulico R (m):", self.spin_radio_hidraulico_contraccion)
        self.spin_v_estrella_w = QDoubleSpinBox(); self.spin_v_estrella_w.setRange(0.01, 10); self.spin_v_estrella_w.setDecimals(2); self.spin_v_estrella_w.setValue(0.5)
        f_contr.addRow("V*/w (para k1 si se fuerza lecho móvil):", self.spin_v_estrella_w)
        v_s.addWidget(gb_contraccion)

        v.addWidget(gb_secciones)

        # ---------------- Métodos a calcular ----------------
        gb_metodos = QGroupBox("4. Métodos de cálculo a aplicar")
        h_met = QHBoxLayout(gb_metodos)
        v_gen = QVBoxLayout()
        v_gen.addWidget(QLabel("<b>General</b>"))
        self.chk_ll = QCheckBox("Lischtvan-Lebediev"); self.chk_ll.setChecked(True)
        self.chk_lacey = QCheckBox("Lacey"); self.chk_lacey.setChecked(True)
        self.chk_blench = QCheckBox("Blench"); self.chk_blench.setChecked(True)
        self.chk_neill = QCheckBox("Neill-Kellerhals")
        for c in (self.chk_ll, self.chk_lacey, self.chk_blench, self.chk_neill):
            v_gen.addWidget(c)
        h_met.addLayout(v_gen)
        v_loc = QVBoxLayout()
        v_loc.addWidget(QLabel("<b>Local (pilares)</b>"))
        self.chk_csu = QCheckBox("CSU / HEC-RAS")
        self.chk_froehlich = QCheckBox("Froehlich")
        v_loc.addWidget(self.chk_csu)
        v_loc.addWidget(self.chk_froehlich)
        h_met.addLayout(v_loc)
        v_contr = QVBoxLayout()
        v_contr.addWidget(QLabel("<b>Contracción</b>"))
        self.chk_laursen = QCheckBox("Laursen")
        v_contr.addWidget(self.chk_laursen)
        h_met.addLayout(v_contr)
        v.addWidget(gb_metodos)

        h_calc = QHBoxLayout()
        btn_calc_activa = QPushButton("Calcular Socavación — sección activa")
        btn_calc_activa.clicked.connect(lambda: self._on_calcular_socavacion(solo_activa=True))
        h_calc.addWidget(btn_calc_activa)
        btn_calc_todas = QPushButton("Calcular Socavación — TODAS las secciones")
        btn_calc_todas.clicked.connect(lambda: self._on_calcular_socavacion(solo_activa=False))
        h_calc.addWidget(btn_calc_todas)
        v.addLayout(h_calc)

        # ---------------- Resultados ----------------
        gb_resultados = QGroupBox("5. Resultados")
        v_r = QVBoxLayout(gb_resultados)
        self.tabla_resultados_socavacion = QTableWidget(0, 6)
        self.tabla_resultados_socavacion.setHorizontalHeaderLabels(
            ["Sección", "Método", "Tipo", "Profundidad ds (m)", "Cota socavada (m)", "Observación"])
        # "Observación" trae texto explicativo de longitud variable; se deja
        # en Stretch para que no empuje la tabla más allá del ancho de la
        # ventana cuando el método gobernante trae una nota más larga.
        aplicar_columna_elastica(self.tabla_resultados_socavacion, indice_columna_larga=5)
        self.tabla_resultados_socavacion.setMinimumHeight(200)
        v_r.addWidget(self.tabla_resultados_socavacion)

        h_ver = QHBoxLayout()
        h_ver.addWidget(QLabel("Ver sección:"))
        self.combo_ver_seccion_resultado = QComboBox()
        self.combo_ver_seccion_resultado.currentTextChanged.connect(self._on_actualizar_graficos_socavacion)
        h_ver.addWidget(self.combo_ver_seccion_resultado)
        h_ver.addWidget(QLabel("Método a graficar en la sección:"))
        self.combo_ver_metodo_resultado = QComboBox()
        self.combo_ver_metodo_resultado.currentTextChanged.connect(self._on_actualizar_grafico_seccion_socavacion)
        h_ver.addWidget(self.combo_ver_metodo_resultado)
        v_r.addLayout(h_ver)

        self.canvas_seccion_socavacion = ScourCanvas(width=7.4, height=5.0)
        v_r.addWidget(self.canvas_seccion_socavacion)
        self.canvas_comparacion_socavacion = ScourCanvas(width=7.4, height=4.6)
        v_r.addWidget(self.canvas_comparacion_socavacion)

        self.canvas_granulometria_socavacion = ScourCanvas(width=7.4, height=4.6)
        v_r.addWidget(self.canvas_granulometria_socavacion)

        v_r.addWidget(QLabel("<b>Cuadro resumen final:</b>"))
        self.texto_resumen_socavacion = QTextBrowser()
        self.texto_resumen_socavacion.setMinimumHeight(160)
        v_r.addWidget(self.texto_resumen_socavacion)

        v.addWidget(gb_resultados)
        self._agregar_pestaña_con_scroll(tab, "10. Socavación")

    # -- Curva granulométrica --
    def _leer_tabla_generica(self, tabla: "QTableWidget", n_cols: int):
        filas = []
        for i in range(tabla.rowCount()):
            valores = []
            vacio = True
            for j in range(n_cols):
                item = tabla.item(i, j)
                texto = item.text().strip() if item else ""
                if texto:
                    vacio = False
                valores.append(texto)
            if not vacio:
                filas.append(valores)
        return filas

    def _on_calcular_diametros_socavacion(self):
        filas = self._leer_tabla_generica(self.tabla_granulometria, 2)
        try:
            curva = []
            for d, p in filas:
                curva.append((float(d.replace(",", ".")), float(p.replace(",", "."))))
            self.curva_granulometrica_socavacion = scour.ordenar_curva(curva)
            self.diametros_socavacion = scour.calcular_diametros_caracteristicos(curva)
            d = self.diametros_socavacion
            self.spin_d16.setValue(d["D16"]); self.spin_d35.setValue(d["D35"]); self.spin_d50.setValue(d["D50"])
            self.spin_d65.setValue(d["D65"]); self.spin_d84.setValue(d["D84"]); self.spin_d90.setValue(d["D90"])
            self.spin_dm_socavacion.setValue(d["Dm"])
            QMessageBox.information(self, "Diámetros calculados",
                                     f"D50 = {d['D50']:.3f} mm, D84 = {d['D84']:.3f} mm, "
                                     f"Dm = {d['Dm']:.3f} mm, σg = {d['sigma_g']:.2f}")
        except (ValueError, scour.SocavacionError) as e:
            QMessageBox.warning(self, "No se pudo calcular",
                                 f"Revise la tabla de la curva granulométrica (diámetro mm, %pasa 0-100).\n{e}")

    def _on_graficar_granulometria(self):
        if not self.curva_granulometrica_socavacion:
            QMessageBox.warning(self, "Falta la curva",
                                 "Calcule primero los diámetros característicos desde la curva granulométrica.")
            return
        self.canvas_granulometria_socavacion.plot_curva_granulometrica(
            self.curva_granulometrica_socavacion, self.diametros_socavacion)

    # -- Gestión de secciones (mismo patrón que self.cuencas_guardadas) --
    def _leer_widgets_seccion_socavacion(self) -> dict:
        filas_tabla = self._leer_tabla_generica(self.tabla_seccion_socavacion, 3)
        estaciones, elevaciones, velocidades = [], [], []
        for fila in filas_tabla:
            est, elev = fila[0], fila[1]
            vel = fila[2] if len(fila) > 2 else ""
            try:
                estaciones.append(float(est.replace(",", ".")))
                elevaciones.append(float(elev.replace(",", ".")))
                velocidades.append(float(vel.replace(",", ".")) if vel else None)
            except ValueError:
                continue
        return {
            "estaciones": estaciones, "elevaciones": elevaciones, "velocidades": velocidades,
            "origen": self.combo_origen_seccion_socavacion.currentIndex(),
            "q": self.spin_q_socavacion.value(), "be": self.spin_be_socavacion.value(),
            "mu": self.spin_mu_socavacion.value(), "tr": self.spin_tr_socavacion.value(),
            "nivel_agua": self.spin_nivel_agua_socavacion.value(),
            "tirante_medio_diseño": self.spin_tirante_medio_socavacion.value(),
            "incluir_local": self.chk_incluir_local_socavacion.isChecked(),
            "estacion_pilar": self.spin_estacion_pilar.value(), "ancho_pilar": self.spin_ancho_pilar.value(),
            "longitud_pilar": self.spin_longitud_pilar.value(), "angulo_ataque": self.spin_angulo_ataque.value(),
            "forma_pilar_idx": self.combo_forma_pilar.currentIndex(),
            "condicion_lecho_idx": self.combo_condicion_lecho_csu.currentIndex(),
            "k4": self.spin_k4_acorazamiento.value(),
            "incluir_contraccion": self.chk_incluir_contraccion_socavacion.isChecked(),
            "modo_laursen_idx": self.combo_modo_laursen.currentIndex(),
            "q1": self.spin_q1_contraccion.value(), "w1": self.spin_w1_contraccion.value(),
            "w2": self.spin_w2_contraccion.value(), "y1_contraccion": self.spin_y1_contraccion.value(),
            "pendiente": self.spin_pendiente_contraccion.value(), "radio_hidraulico": self.spin_radio_hidraulico_contraccion.value(),
            "v_estrella_w": self.spin_v_estrella_w.value(),
        }

    def _escribir_widgets_seccion_socavacion(self, datos: dict):
        self.tabla_seccion_socavacion.setRowCount(max(len(datos.get("estaciones", [])), 10))
        for i, (est, elev, vel) in enumerate(zip(
                datos.get("estaciones", []), datos.get("elevaciones", []), datos.get("velocidades", []))):
            self.tabla_seccion_socavacion.setItem(i, 0, QTableWidgetItem(f"{est:.2f}"))
            self.tabla_seccion_socavacion.setItem(i, 1, QTableWidgetItem(f"{elev:.2f}"))
            if vel is not None:
                self.tabla_seccion_socavacion.setItem(i, 2, QTableWidgetItem(f"{vel:.3f}"))
        self.combo_origen_seccion_socavacion.setCurrentIndex(datos.get("origen", 0))
        self.spin_q_socavacion.setValue(datos.get("q", 100.0))
        self.spin_be_socavacion.setValue(datos.get("be", 30.0))
        self.spin_mu_socavacion.setValue(datos.get("mu", 1.0))
        self.spin_tr_socavacion.setValue(datos.get("tr", 100))
        self.spin_nivel_agua_socavacion.setValue(datos.get("nivel_agua", 100.0))
        self.spin_tirante_medio_socavacion.setValue(datos.get("tirante_medio_diseño", 3.0))
        self.chk_incluir_local_socavacion.setChecked(datos.get("incluir_local", False))
        self.spin_estacion_pilar.setValue(datos.get("estacion_pilar", 0.0))
        self.spin_ancho_pilar.setValue(datos.get("ancho_pilar", 1.5))
        self.spin_longitud_pilar.setValue(datos.get("longitud_pilar", 6.0))
        self.spin_angulo_ataque.setValue(datos.get("angulo_ataque", 0.0))
        self.combo_forma_pilar.setCurrentIndex(datos.get("forma_pilar_idx", 0))
        self.combo_condicion_lecho_csu.setCurrentIndex(datos.get("condicion_lecho_idx", 0))
        self.spin_k4_acorazamiento.setValue(datos.get("k4", 1.0))
        self.chk_incluir_contraccion_socavacion.setChecked(datos.get("incluir_contraccion", False))
        self.combo_modo_laursen.setCurrentIndex(datos.get("modo_laursen_idx", 0))
        self.spin_q1_contraccion.setValue(datos.get("q1", 100.0))
        self.spin_w1_contraccion.setValue(datos.get("w1", 40.0))
        self.spin_w2_contraccion.setValue(datos.get("w2", 25.0))
        self.spin_y1_contraccion.setValue(datos.get("y1_contraccion", 3.0))
        self.spin_pendiente_contraccion.setValue(datos.get("pendiente", 0.01))
        self.spin_radio_hidraulico_contraccion.setValue(datos.get("radio_hidraulico", 2.5))
        self.spin_v_estrella_w.setValue(datos.get("v_estrella_w", 0.5))

    def _on_generar_secciones_socavacion(self):
        n = self.spin_num_secciones_socavacion.value()
        if self.nombre_seccion_socavacion_activa:
            self.secciones_socavacion[self.nombre_seccion_socavacion_activa] = self._leer_widgets_seccion_socavacion()
        for _ in range(n):
            self.contador_secciones_socavacion += 1
            nombre = f"Sección {self.contador_secciones_socavacion}"
            self.secciones_socavacion[nombre] = {}
        self.combo_seccion_socavacion_activa.blockSignals(True)
        self.combo_seccion_socavacion_activa.clear()
        self.combo_seccion_socavacion_activa.addItems(list(self.secciones_socavacion.keys()))
        self.combo_seccion_socavacion_activa.blockSignals(False)
        if self.secciones_socavacion:
            nombre_primera = list(self.secciones_socavacion.keys())[0]
            self.combo_seccion_socavacion_activa.setCurrentText(nombre_primera)
            self.nombre_seccion_socavacion_activa = nombre_primera
            self._escribir_widgets_seccion_socavacion(self.secciones_socavacion[nombre_primera])

    def _on_cambiar_seccion_socavacion_activa(self, nombre_nuevo: str):
        if not nombre_nuevo:
            return
        if self.nombre_seccion_socavacion_activa and self.nombre_seccion_socavacion_activa in self.secciones_socavacion:
            self.secciones_socavacion[self.nombre_seccion_socavacion_activa] = self._leer_widgets_seccion_socavacion()
        self.nombre_seccion_socavacion_activa = nombre_nuevo
        self._escribir_widgets_seccion_socavacion(self.secciones_socavacion.get(nombre_nuevo, {}))

    def _on_fijar_nivel_agua_desde_tirante(self):
        filas = self._leer_tabla_generica(self.tabla_seccion_socavacion, 3)
        elevaciones = []
        for fila in filas:
            try:
                elevaciones.append(float(fila[1].replace(",", ".")))
            except (ValueError, IndexError):
                continue
        if not elevaciones:
            QMessageBox.warning(self, "Falta la sección", "Ingrese primero la tabla de estación-elevación.")
            return
        nivel = min(elevaciones) + self.spin_tirante_medio_socavacion.value()
        self.spin_nivel_agua_socavacion.setValue(nivel)

    # -- Extracción de la sección desde el GIS (línea de 2 clics sobre el MDE) --
    def _activar_map_tool_socavacion(self, checked):
        canvas = self.iface.mapCanvas()
        if checked:
            self._primer_clic_seccion_socavacion = None
            self.map_tool_socavacion = QgsMapToolEmitPoint(canvas)
            self.map_tool_socavacion.canvasClicked.connect(self._on_canvas_clicked_socavacion)
            canvas.mapToolSet.connect(self._on_map_tool_changed_socavacion)
            canvas.setMapTool(self.map_tool_socavacion)
            self.btn_trazar_seccion_socavacion.setText("Clic en el INICIO de la sección...")
            self.hide()
        else:
            try:
                canvas.mapToolSet.disconnect(self._on_map_tool_changed_socavacion)
            except TypeError:
                pass
            canvas.unsetMapTool(self.map_tool_socavacion)
            self.btn_trazar_seccion_socavacion.setText("Trazar línea de sección en el mapa (2 clics)")
            self._restaurar_ventana()

    def _on_map_tool_changed_socavacion(self, herramienta_nueva, herramienta_anterior):
        if herramienta_nueva is not self.map_tool_socavacion:
            self.btn_trazar_seccion_socavacion.setChecked(False)
            self.btn_trazar_seccion_socavacion.setText("Trazar línea de sección en el mapa (2 clics)")
            self._restaurar_ventana()

    def _on_canvas_clicked_socavacion(self, punto, button):
        if self._primer_clic_seccion_socavacion is None:
            self._primer_clic_seccion_socavacion = QgsPointXY(punto)
            self.btn_trazar_seccion_socavacion.setText("Clic en el FIN de la sección...")
            return
        punto_inicio = self._primer_clic_seccion_socavacion
        punto_fin = QgsPointXY(punto)
        self._primer_clic_seccion_socavacion = None
        canvas = self.iface.mapCanvas()
        try:
            canvas.mapToolSet.disconnect(self._on_map_tool_changed_socavacion)
        except TypeError:
            pass
        canvas.unsetMapTool(self.map_tool_socavacion)
        self.btn_trazar_seccion_socavacion.setChecked(False)
        self.btn_trazar_seccion_socavacion.setText("Trazar línea de sección en el mapa (2 clics)")
        self._restaurar_ventana()

        dem_layer = self.combo_dem_socavacion.currentLayer()
        if dem_layer is None:
            QMessageBox.warning(self, "Falta el MDE", "Seleccione una capa ráster de MDE antes de trazar la sección.")
            return
        try:
            n_muestras = 30
            provider = dem_layer.dataProvider()
            distancia_total = punto_inicio.distance(punto_fin)
            if distancia_total <= 0:
                raise scour.SocavacionError("La línea trazada tiene longitud cero.")
            estaciones, elevaciones = [], []
            for i in range(n_muestras + 1):
                frac = i / n_muestras
                x = punto_inicio.x() + frac * (punto_fin.x() - punto_inicio.x())
                y = punto_inicio.y() + frac * (punto_fin.y() - punto_inicio.y())
                resultado = provider.identify(QgsPointXY(x, y), 1)  # QgsRaster.IdentifyFormatValue = 1
                valor = None
                if resultado.isValid():
                    valores = resultado.results()
                    if valores:
                        valor = list(valores.values())[0]
                if valor is None:
                    continue
                estaciones.append(frac * distancia_total)
                elevaciones.append(float(valor))
            if len(estaciones) < 2:
                raise scour.SocavacionError("No se pudo muestrear el MDE a lo largo de la línea trazada.")
            self.tabla_seccion_socavacion.setRowCount(max(len(estaciones), 10))
            for i, (est, elev) in enumerate(zip(estaciones, elevaciones)):
                self.tabla_seccion_socavacion.setItem(i, 0, QTableWidgetItem(f"{est:.2f}"))
                self.tabla_seccion_socavacion.setItem(i, 1, QTableWidgetItem(f"{elev:.2f}"))
            QMessageBox.information(self, "Sección extraída del MDE",
                                     f"Se muestrearon {len(estaciones)} puntos a lo largo de {distancia_total:.1f} m.\n"
                                     "Complete ahora la columna de Velocidad media (m/s) por vertical.")
        except scour.SocavacionError as e:
            QMessageBox.warning(self, "No se pudo extraer la sección", str(e))

    # -- Cálculo de socavación --
    def _forma_pilar_k1_kf(self, idx: int):
        return [(1.0, 1.0), (1.1, 1.3), (0.9, 0.7)][idx]

    def _condicion_lecho_k3(self, idx: int):
        return [1.1, 1.2, 1.3][idx]

    def _on_calcular_socavacion(self, solo_activa: bool):
        if not self.diametros_socavacion and self.spin_d50.value() <= 0.0001:
            QMessageBox.warning(self, "Falta la granulometría",
                                 "Ingrese al menos D50 (calculado desde la curva o manualmente).")
            return
        if self.nombre_seccion_socavacion_activa:
            self.secciones_socavacion[self.nombre_seccion_socavacion_activa] = self._leer_widgets_seccion_socavacion()

        nombres_a_calcular = ([self.nombre_seccion_socavacion_activa] if solo_activa
                               else list(self.secciones_socavacion.keys()))
        cohesivo = self.radio_cohesivo.isChecked()
        gamma_d = self.spin_gamma_d.value()
        dm_mm = self.spin_dm_socavacion.value() if self.spin_dm_socavacion.value() > 0 else self.spin_d50.value()
        d50_mm = self.spin_d50.value() if self.spin_d50.value() > 0 else dm_mm

        self.tabla_resultados_socavacion.setRowCount(0)
        filas_reporte = []
        for nombre in nombres_a_calcular:
            if not nombre:
                continue
            datos = self.secciones_socavacion.get(nombre, {})
            estaciones = datos.get("estaciones", [])
            elevaciones = datos.get("elevaciones", [])
            velocidades = datos.get("velocidades", [])
            if len(estaciones) < 2:
                continue
            nivel_agua = datos.get("nivel_agua", 100.0)
            q = datos.get("q", 100.0)
            be = datos.get("be", 30.0)
            mu = datos.get("mu", 1.0)
            tr = datos.get("tr", 100.0)
            velocidad_media = next((v for v in velocidades if v is not None), None) or (q / (be * max(nivel_agua - min(elevaciones), 0.1)))

            resultados_metodo = {}
            perfiles_metodo = {}

            if self.chk_ll.isChecked():
                try:
                    perfil = scour.perfil_socavado_lischtvan_lebediev(
                        estaciones, elevaciones, nivel_agua, q, be, mu, tr, cohesivo,
                        dm_mm=dm_mm, gamma_d_tm3=gamma_d)
                    resultados_metodo["Lischtvan-Lebediev"] = perfil["ds_max_m"]
                    perfiles_metodo["Lischtvan-Lebediev"] = perfil
                except scour.SocavacionError as e:
                    filas_reporte.append((nombre, "Lischtvan-Lebediev", "General", None, None, f"Error: {e}"))

            if self.chk_lacey.isChecked():
                try:
                    dsm = scour.lacey_scour_depth(q, be, dm_mm)
                    perfil = scour.aplicar_descenso_uniforme(estaciones, elevaciones, nivel_agua, dsm)
                    resultados_metodo["Lacey"] = perfil["ds_max_m"]
                    perfiles_metodo["Lacey"] = perfil
                except scour.SocavacionError as e:
                    filas_reporte.append((nombre, "Lacey", "General", None, None, f"Error: {e}"))

            if self.chk_blench.isChecked():
                try:
                    dsm = scour.blench_scour_depth(q, be, dm_mm)
                    perfil = scour.aplicar_descenso_uniforme(estaciones, elevaciones, nivel_agua, dsm)
                    resultados_metodo["Blench"] = perfil["ds_max_m"]
                    perfiles_metodo["Blench"] = perfil
                except scour.SocavacionError as e:
                    filas_reporte.append((nombre, "Blench", "General", None, None, f"Error: {e}"))

            if self.chk_neill.isChecked():
                try:
                    y_eq = scour.neill_kellerhals_scour_depth(q, be, d50_mm)
                    perfil = scour.aplicar_descenso_uniforme(estaciones, elevaciones, nivel_agua, y_eq)
                    resultados_metodo["Neill-Kellerhals"] = perfil["ds_max_m"]
                    perfiles_metodo["Neill-Kellerhals"] = perfil
                except scour.SocavacionError as e:
                    filas_reporte.append((nombre, "Neill-Kellerhals", "General", None, None, f"Error: {e}"))

            estacion_pilar = datos.get("estacion_pilar", 0.0)
            ys_local_max = None
            if datos.get("incluir_local"):
                k1, kf = self._forma_pilar_k1_kf(datos.get("forma_pilar_idx", 0))
                k3 = self._condicion_lecho_k3(datos.get("condicion_lecho_idx", 0))
                y1_local = max(nivel_agua - min(elevaciones), 0.1)
                k2 = scour.k2_angulo_ataque(datos.get("angulo_ataque", 0.0), datos.get("longitud_pilar", 6.0),
                                             datos.get("ancho_pilar", 1.5))
                if self.chk_csu.isChecked():
                    r = scour.csu_pier_scour(y1_local, velocidad_media, datos.get("ancho_pilar", 1.5),
                                              k1_forma=k1, k2_angulo=k2, k3_lecho=k3, k4_acorazamiento=datos.get("k4", 1.0))
                    resultados_metodo["CSU / HEC-RAS"] = r["ys_m"]
                    ys_local_max = max(ys_local_max or 0, r["ys_m"])
                    filas_reporte.append((nombre, "CSU / HEC-RAS", "Local (pilar)", r["ys_m"], None,
                                          f"Fr1={r['Fr1']:.2f}, ys/y1={r['ys_sobre_y1']:.2f}"))
                if self.chk_froehlich.isChecked():
                    r = scour.froehlich_pier_scour(y1_local, velocidad_media, datos.get("ancho_pilar", 1.5),
                                                    d50_mm, kf_forma=kf, theta_grados=datos.get("angulo_ataque", 0.0),
                                                    longitud_pila_m=datos.get("longitud_pilar", 6.0))
                    resultados_metodo["Froehlich"] = r["ys_m"]
                    ys_local_max = max(ys_local_max or 0, r["ys_m"])
                    filas_reporte.append((nombre, "Froehlich", "Local (pilar)", r["ys_m"], None,
                                          f"Fr1={r['Fr1']:.2f}, a'={r['a_proyectada_m']:.2f} m"))

            if datos.get("incluir_contraccion") and self.chk_laursen.isChecked():
                modo_idx = datos.get("modo_laursen_idx", 0)
                lecho_movil = None
                if modo_idx == 0:
                    tau = scour.tension_tangencial_y_shields(datos.get("radio_hidraulico", 2.5),
                                                              datos.get("pendiente", 0.01), d50_mm)
                    lecho_movil = tau["lecho_movil"]
                elif modo_idx == 2:
                    lecho_movil = True
                else:
                    lecho_movil = False
                if lecho_movil:
                    k1_exp = scour.clasificar_k1_laursen(datos.get("v_estrella_w", 0.5))
                    r = scour.laursen_contraccion_lecho_movil(
                        datos.get("q1", q), q, datos.get("w1", be * 1.3), datos.get("w2", be),
                        datos.get("y1_contraccion", 3.0), k1_exp)
                else:
                    r = scour.laursen_contraccion_agua_clara(q, datos.get("w2", be), dm_mm,
                                                              datos.get("y1_contraccion", 3.0))
                resultados_metodo["Laursen (contracción)"] = r["ds_m"]
                filas_reporte.append((nombre, "Laursen (contracción)", "Contracción", r["ds_m"], None,
                                      r["metodo"]))

            for metodo, perfil in perfiles_metodo.items():
                filas_reporte.append((nombre, metodo, "General", perfil["ds_max_m"], perfil["cota_socavada_max"], ""))

            resumen = scour.resumen_comparativo(resultados_metodo)
            self.resultados_socavacion[nombre] = {
                "resultados_metodo": resultados_metodo, "perfiles_metodo": perfiles_metodo,
                "resumen": resumen, "nivel_agua": nivel_agua, "estacion_pilar": estacion_pilar,
                "ys_local_max": ys_local_max,
            }

        for nombre, metodo, tipo, ds, cota, obs in filas_reporte:
            fila = self.tabla_resultados_socavacion.rowCount()
            self.tabla_resultados_socavacion.insertRow(fila)
            self.tabla_resultados_socavacion.setItem(fila, 0, QTableWidgetItem(nombre))
            self.tabla_resultados_socavacion.setItem(fila, 1, QTableWidgetItem(metodo))
            self.tabla_resultados_socavacion.setItem(fila, 2, QTableWidgetItem(tipo))
            self.tabla_resultados_socavacion.setItem(fila, 3, QTableWidgetItem(f"{ds:.2f}" if ds is not None else "—"))
            self.tabla_resultados_socavacion.setItem(fila, 4, QTableWidgetItem(f"{cota:.2f}" if cota is not None else "—"))
            self.tabla_resultados_socavacion.setItem(fila, 5, QTableWidgetItem(obs))

        self.combo_ver_seccion_resultado.blockSignals(True)
        self.combo_ver_seccion_resultado.clear()
        self.combo_ver_seccion_resultado.addItems(list(self.resultados_socavacion.keys()))
        self.combo_ver_seccion_resultado.blockSignals(False)
        self._actualizar_texto_resumen_socavacion()
        if self.resultados_socavacion:
            self.combo_ver_seccion_resultado.setCurrentIndex(0)
            self._on_actualizar_graficos_socavacion(self.combo_ver_seccion_resultado.currentText())

    def _on_actualizar_graficos_socavacion(self, nombre_seccion: str):
        if not nombre_seccion or nombre_seccion not in self.resultados_socavacion:
            return
        r = self.resultados_socavacion[nombre_seccion]
        self.combo_ver_metodo_resultado.blockSignals(True)
        self.combo_ver_metodo_resultado.clear()
        self.combo_ver_metodo_resultado.addItems(list(r["perfiles_metodo"].keys()) or ["(solo socavación local/contracción)"])
        self.combo_ver_metodo_resultado.blockSignals(False)
        if r["perfiles_metodo"]:
            self.combo_ver_metodo_resultado.setCurrentIndex(0)
            self._on_actualizar_grafico_seccion_socavacion(self.combo_ver_metodo_resultado.currentText())
        nombres_metodos = list(r["resultados_metodo"].keys())
        valores = list(r["resultados_metodo"].values())
        if nombres_metodos:
            self.canvas_comparacion_socavacion.plot_comparacion_metodos(
                nombres_metodos, valores, metodo_gobernante=r["resumen"].get("metodo_gobernante"))

    def _on_actualizar_grafico_seccion_socavacion(self, nombre_metodo: str):
        nombre_seccion = self.combo_ver_seccion_resultado.currentText()
        if not nombre_seccion or nombre_seccion not in self.resultados_socavacion:
            return
        r = self.resultados_socavacion[nombre_seccion]
        perfil = r["perfiles_metodo"].get(nombre_metodo)
        datos_seccion = self.secciones_socavacion.get(nombre_seccion, {})
        if perfil:
            self.canvas_seccion_socavacion.plot_seccion_socavacion(
                perfil["estaciones"], perfil["elevaciones_originales"], perfil["elevaciones_socavadas"],
                r["nivel_agua"], nombre_seccion=nombre_seccion, nombre_metodo=nombre_metodo,
                estacion_local=r.get("estacion_pilar") if r.get("ys_local_max") else None,
                ys_local=r.get("ys_local_max"), ancho_pila=datos_seccion.get("ancho_pilar"))
        elif datos_seccion.get("estaciones"):
            self.canvas_seccion_socavacion.plot_seccion_socavacion(
                datos_seccion["estaciones"], datos_seccion["elevaciones"], datos_seccion["elevaciones"],
                r["nivel_agua"], nombre_seccion=nombre_seccion, nombre_metodo="",
                estacion_local=r.get("estacion_pilar") if r.get("ys_local_max") else None,
                ys_local=r.get("ys_local_max"), ancho_pila=datos_seccion.get("ancho_pilar"))

    def _actualizar_texto_resumen_socavacion(self):
        html = "<h3>Cuadro resumen final de socavación</h3>"
        for nombre, r in self.resultados_socavacion.items():
            resumen = r["resumen"]
            if not resumen:
                continue
            html += (f"<p><b>{nombre}</b><br>"
                     f"Método gobernante (mayor profundidad, criterio de diseño conservador): "
                     f"<b>{resumen['metodo_gobernante']}</b><br>"
                     f"Profundidad de socavación de diseño recomendada: "
                     f"<b>{resumen['ds_diseño_recomendado_m']:.2f} m</b><br>"
                     f"Promedio entre métodos: {resumen['promedio_m']:.2f} m &nbsp;|&nbsp; "
                     f"Rango: {resumen['minimo_m']:.2f} – {resumen['maximo_m']:.2f} m<br>"
                     f"Cota de fondo socavado de diseño: "
                     f"{r['nivel_agua'] - resumen['ds_diseño_recomendado_m']:.2f} m s.n.m.</p><hr>")
        html += ("<p style='color:#666666'>NOTA: se recomienda adoptar el valor MÁXIMO entre los métodos "
                 "aplicables como profundidad de diseño (criterio conservador estándar en ingeniería de "
                 "socavación), salvo justificación técnica específica para adoptar otro criterio.</p>")
        self.texto_resumen_socavacion.setHtml(html)

    # ------------------------------------------------------------------
    # TAB 11: Pérdida en Suelos (USLE/RUSLE). Ver core/soil_loss.py.
    # ------------------------------------------------------------------
    def _build_tab_perdida_suelos(self):
        tab = QWidget()
        v = QVBoxLayout(tab)
        _lbl_auto_29 = QLabel(
            "<b>Pérdida en Suelos (USLE/RUSLE)</b> — A = R·K·LS·C·P. Calcule cada factor por el método "
            "que disponga (directo, fórmula empírica, o tabla), para una o varias zonas/parcelas de "
            "estudio, y compare. También puede ESPACIALIZAR el factor LS y el resultado final como un "
            "ráster real usando el MDE ya delimitado en la Pestaña 1 (pendiente + acumulación de flujo)."
        )
        _lbl_auto_29.setWordWrap(True)
        v.addWidget(_lbl_auto_29)

        # ---------------- Gestión de zonas ----------------
        gb_zonas = QGroupBox("1. Zonas / parcelas de estudio")
        v_z = QVBoxLayout(gb_zonas)
        h_gen = QHBoxLayout()
        h_gen.addWidget(QLabel("Número de zonas a crear:"))
        self.spin_num_zonas_suelo = QSpinBox(); self.spin_num_zonas_suelo.setRange(1, 30); self.spin_num_zonas_suelo.setValue(1)
        h_gen.addWidget(self.spin_num_zonas_suelo)
        btn_generar_zonas = QPushButton("Generar zonas")
        btn_generar_zonas.clicked.connect(self._on_generar_zonas_suelo)
        h_gen.addWidget(btn_generar_zonas)
        h_gen.addWidget(QLabel("Zona activa:"))
        self.combo_zona_suelo_activa = QComboBox()
        self.combo_zona_suelo_activa.currentTextChanged.connect(self._on_cambiar_zona_suelo_activa)
        h_gen.addWidget(self.combo_zona_suelo_activa)
        v_z.addLayout(h_gen)
        v.addWidget(gb_zonas)

        # ---------------- Factor R ----------------
        gb_r = QGroupBox("2. Factor R — Erosividad de la lluvia")
        f_r = QFormLayout(gb_r)
        f_r.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.combo_modo_r = QComboBox()
        self.combo_modo_r.addItems(["Directo (ya tengo R, MJ·mm/(ha·h·año))",
                                     "Wischmeier-Smith (desde P anual, mm)",
                                     "Fournier Modificado (desde P mensual, pegar tabla)"])
        f_r.addRow("Método:", self.combo_modo_r)
        self.spin_r_directo = QDoubleSpinBox(); self.spin_r_directo.setRange(0, 30000); self.spin_r_directo.setDecimals(1); self.spin_r_directo.setValue(500.0)
        f_r.addRow("R directo:", self.spin_r_directo)
        self.spin_p_anual_r = QDoubleSpinBox(); self.spin_p_anual_r.setRange(1, 10000); self.spin_p_anual_r.setDecimals(1); self.spin_p_anual_r.setValue(800.0)
        f_r.addRow("P anual (mm), Wischmeier-Smith:", self.spin_p_anual_r)
        lbl_precip_fournier = QLabel("Precipitación mensual (mm), Fournier Modificado — pegue 12 valores:")
        lbl_precip_fournier.setWordWrap(True)
        f_r.addRow(lbl_precip_fournier)
        self.tabla_precip_mensual_suelo = TablaPegable(12, 2)
        self.tabla_precip_mensual_suelo.setHorizontalHeaderLabels(["Mes", "Precipitación (mm)"])
        meses = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
        for i, mes in enumerate(meses):
            self.tabla_precip_mensual_suelo.setItem(i, 0, QTableWidgetItem(mes))
        self.tabla_precip_mensual_suelo.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla_precip_mensual_suelo.setMinimumHeight(160)
        f_r.addRow(self.tabla_precip_mensual_suelo)
        v.addWidget(gb_r)

        # ---------------- Factor K ----------------
        gb_k = QGroupBox("3. Factor K — Erosionabilidad del suelo")
        f_k = QFormLayout(gb_k)
        f_k.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.combo_modo_k = QComboBox()
        self.combo_modo_k.addItems(["Directo (ya tengo K, t·ha·h/(ha·MJ·mm))", "Nomograma de Wischmeier-Smith"])
        f_k.addRow("Método:", self.combo_modo_k)
        self.spin_k_directo = QDoubleSpinBox(); self.spin_k_directo.setRange(0, 1); self.spin_k_directo.setDecimals(4); self.spin_k_directo.setValue(0.03)
        f_k.addRow("K directo:", self.spin_k_directo)
        self.spin_pct_limo_avf = QDoubleSpinBox(); self.spin_pct_limo_avf.setRange(0, 100); self.spin_pct_limo_avf.setDecimals(1); self.spin_pct_limo_avf.setValue(65.0)
        f_k.addRow("% limo + arena muy fina:", self.spin_pct_limo_avf)
        self.spin_pct_arcilla = QDoubleSpinBox(); self.spin_pct_arcilla.setRange(0, 100); self.spin_pct_arcilla.setDecimals(1); self.spin_pct_arcilla.setValue(15.0)
        f_k.addRow("% arcilla:", self.spin_pct_arcilla)
        self.spin_pct_materia_organica = QDoubleSpinBox(); self.spin_pct_materia_organica.setRange(0, 12); self.spin_pct_materia_organica.setDecimals(1); self.spin_pct_materia_organica.setValue(2.5)
        f_k.addRow("% materia orgánica:", self.spin_pct_materia_organica)
        self.combo_estructura_suelo = QComboBox()
        self.combo_estructura_suelo.addItems(["1 — Granular muy fina", "2 — Granular fina", "3 — Granular media/gruesa", "4 — Bloques/laminar/masiva"])
        f_k.addRow("Código de estructura:", self.combo_estructura_suelo)
        self.combo_permeabilidad_suelo = QComboBox()
        self.combo_permeabilidad_suelo.addItems(["1 — Rápida", "2 — Moderada a rápida", "3 — Moderada",
                                                  "4 — Lenta a moderada", "5 — Lenta", "6 — Muy lenta"])
        f_k.addRow("Código de permeabilidad:", self.combo_permeabilidad_suelo)
        v.addWidget(gb_k)

        # ---------------- Factor LS ----------------
        gb_ls = QGroupBox("4. Factor LS — Topográfico")
        f_ls = QFormLayout(gb_ls)
        f_ls.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.combo_modo_ls = QComboBox()
        self.combo_modo_ls.addItems(["Directo (ya tengo LS)", "Wischmeier-McCool (longitud de pendiente)",
                                      "Moore-Burch (área de contribución específica)"])
        f_ls.addRow("Método:", self.combo_modo_ls)
        self.spin_ls_directo = QDoubleSpinBox(); self.spin_ls_directo.setRange(0, 200); self.spin_ls_directo.setDecimals(3); self.spin_ls_directo.setValue(2.0)
        f_ls.addRow("LS directo:", self.spin_ls_directo)
        self.spin_pendiente_pct_suelo = QDoubleSpinBox(); self.spin_pendiente_pct_suelo.setRange(0.01, 200); self.spin_pendiente_pct_suelo.setDecimals(2); self.spin_pendiente_pct_suelo.setValue(15.0)
        f_ls.addRow("Pendiente (%):", self.spin_pendiente_pct_suelo)
        self.spin_longitud_pendiente = QDoubleSpinBox(); self.spin_longitud_pendiente.setRange(1, 2000); self.spin_longitud_pendiente.setDecimals(1); self.spin_longitud_pendiente.setValue(50.0)
        f_ls.addRow("Longitud de la pendiente λ (m), Wischmeier-McCool:", self.spin_longitud_pendiente)
        self.spin_area_contrib_especifica = QDoubleSpinBox(); self.spin_area_contrib_especifica.setRange(0.1, 1e7); self.spin_area_contrib_especifica.setDecimals(1); self.spin_area_contrib_especifica.setValue(200.0)
        f_ls.addRow("Área de contribución específica As (m²/m), Moore-Burch:", self.spin_area_contrib_especifica)
        v.addWidget(gb_ls)

        # ---------------- Factor C ----------------
        gb_c = QGroupBox("5. Factor C — Cobertura vegetal")
        f_c = QFormLayout(gb_c)
        f_c.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.combo_modo_c = QComboBox()
        self.combo_modo_c.addItems(["Tabla de cobertura", "Desde NDVI"])
        f_c.addRow("Método:", self.combo_modo_c)
        self.combo_cobertura_c = QComboBox()
        self.combo_cobertura_c.addItems(list(soil_loss.TABLA_C_COBERTURA.keys()))
        f_c.addRow("Tipo de cobertura:", self.combo_cobertura_c)
        self.spin_ndvi_c = QDoubleSpinBox(); self.spin_ndvi_c.setRange(-0.99, 0.99); self.spin_ndvi_c.setDecimals(3); self.spin_ndvi_c.setValue(0.5)
        f_c.addRow("NDVI (-1 a 1):", self.spin_ndvi_c)
        v.addWidget(gb_c)

        # ---------------- Factor P ----------------
        gb_p = QGroupBox("6. Factor P — Prácticas de conservación")
        f_p = QFormLayout(gb_p)
        f_p.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.combo_practica_p = QComboBox()
        self.combo_practica_p.addItems(list(soil_loss.TABLA_P_PRACTICAS.keys()))
        f_p.addRow("Práctica:", self.combo_practica_p)
        v.addWidget(gb_p)

        h_calc = QHBoxLayout()
        btn_calc_zona_activa = QPushButton("Calcular — zona activa")
        btn_calc_zona_activa.clicked.connect(lambda: self._on_calcular_perdida_suelo(solo_activa=True))
        h_calc.addWidget(btn_calc_zona_activa)
        btn_calc_todas_zonas = QPushButton("Calcular — TODAS las zonas")
        btn_calc_todas_zonas.clicked.connect(lambda: self._on_calcular_perdida_suelo(solo_activa=False))
        h_calc.addWidget(btn_calc_todas_zonas)
        v.addLayout(h_calc)

        # ---------------- Resultados tabulares ----------------
        gb_resultados = QGroupBox("7. Resultados por zona")
        v_r = QVBoxLayout(gb_resultados)
        self.tabla_resultados_suelo = QTableWidget(0, 8)
        self.tabla_resultados_suelo.setHorizontalHeaderLabels(
            ["Zona", "R", "K", "LS", "C", "P", "A (t/ha/año)", "Clasificación"])
        self.tabla_resultados_suelo.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla_resultados_suelo.setMinimumHeight(180)
        v_r.addWidget(self.tabla_resultados_suelo)

        h_ver = QHBoxLayout()
        h_ver.addWidget(QLabel("Ver zona (descomposición de factores):"))
        self.combo_ver_zona_suelo = QComboBox()
        self.combo_ver_zona_suelo.currentTextChanged.connect(self._on_actualizar_grafico_factores_suelo)
        h_ver.addWidget(self.combo_ver_zona_suelo)
        v_r.addLayout(h_ver)

        self.canvas_factores_suelo = SoilLossCanvas(width=7.4, height=5.0)
        v_r.addWidget(self.canvas_factores_suelo)
        self.canvas_comparacion_suelo = SoilLossCanvas(width=7.4, height=5.0)
        v_r.addWidget(self.canvas_comparacion_suelo)
        v.addWidget(gb_resultados)

        # ---------------- Espacialización SIG ----------------
        gb_sig = QGroupBox("8. Espacialización SIG (ráster real de A, opcional)")
        v_sig = QVBoxLayout(gb_sig)
        _lbl_auto_30 = QLabel(
            "Genera un ráster real de LS (Moore-Burch) a partir del MDE recortado a la cuenca (Pestaña 1: "
            "pendiente + acumulación de flujo D8), y lo combina con los factores R, K, C, P (uniformes, "
            "tomados de la zona activa ya calculada) en el ráster final de pérdida de suelo, que se agrega "
            "al lienzo de QGIS."
        )
        _lbl_auto_30.setWordWrap(True)
        v_sig.addWidget(_lbl_auto_30)
        h_sig1 = QHBoxLayout()
        self.spin_umbral_acumulacion_suelo = QSpinBox(); self.spin_umbral_acumulacion_suelo.setRange(1, 100000); self.spin_umbral_acumulacion_suelo.setValue(100)
        h_sig1.addWidget(QLabel("Umbral de acumulación (celdas, define la densidad de cauces):"))
        h_sig1.addWidget(self.spin_umbral_acumulacion_suelo)
        btn_calc_ls_raster = QPushButton("1) Calcular ráster de LS (Moore-Burch) desde el MDE de la Pestaña 1")
        btn_calc_ls_raster.clicked.connect(self._on_calcular_ls_raster)
        h_sig1.addWidget(btn_calc_ls_raster)
        v_sig.addLayout(h_sig1)

        h_sig2 = QHBoxLayout()
        btn_calc_raster_final = QPushButton("2) Generar ráster de pérdida de suelo (A) con R/K/C/P de la zona activa")
        btn_calc_raster_final.clicked.connect(self._on_calcular_raster_perdida_suelo)
        h_sig2.addWidget(btn_calc_raster_final)
        v_sig.addLayout(h_sig2)

        self.canvas_mapa_suelo = SoilLossCanvas(width=7.4, height=5.4)
        v_sig.addWidget(self.canvas_mapa_suelo)
        v.addWidget(gb_sig)

        v.addWidget(QLabel("<b>Cuadro resumen final:</b>"))
        self.texto_resumen_suelo = QTextBrowser()
        self.texto_resumen_suelo.setMinimumHeight(160)
        v.addWidget(self.texto_resumen_suelo)

        self._agregar_pestaña_con_scroll(tab, "11. Pérdida en Suelos")

    # -- Gestión de zonas (mismo patrón que secciones de socavación) --
    def _leer_widgets_zona_suelo(self) -> dict:
        filas_precip = self._leer_tabla_generica(self.tabla_precip_mensual_suelo, 2)
        precip_mensual = []
        for fila in filas_precip:
            try:
                precip_mensual.append(float(fila[1].replace(",", ".")))
            except (ValueError, IndexError):
                precip_mensual.append(0.0)
        return {
            "modo_r": self.combo_modo_r.currentIndex(), "r_directo": self.spin_r_directo.value(),
            "p_anual_r": self.spin_p_anual_r.value(), "precip_mensual": precip_mensual,
            "modo_k": self.combo_modo_k.currentIndex(), "k_directo": self.spin_k_directo.value(),
            "pct_limo_avf": self.spin_pct_limo_avf.value(), "pct_arcilla": self.spin_pct_arcilla.value(),
            "pct_materia_organica": self.spin_pct_materia_organica.value(),
            "estructura_idx": self.combo_estructura_suelo.currentIndex(),
            "permeabilidad_idx": self.combo_permeabilidad_suelo.currentIndex(),
            "modo_ls": self.combo_modo_ls.currentIndex(), "ls_directo": self.spin_ls_directo.value(),
            "pendiente_pct": self.spin_pendiente_pct_suelo.value(),
            "longitud_pendiente": self.spin_longitud_pendiente.value(),
            "area_contrib_especifica": self.spin_area_contrib_especifica.value(),
            "modo_c": self.combo_modo_c.currentIndex(), "cobertura": self.combo_cobertura_c.currentText(),
            "ndvi": self.spin_ndvi_c.value(), "practica": self.combo_practica_p.currentText(),
        }

    def _escribir_widgets_zona_suelo(self, datos: dict):
        self.combo_modo_r.setCurrentIndex(datos.get("modo_r", 0))
        self.spin_r_directo.setValue(datos.get("r_directo", 500.0))
        self.spin_p_anual_r.setValue(datos.get("p_anual_r", 800.0))
        precip = datos.get("precip_mensual", [])
        for i in range(12):
            valor = precip[i] if i < len(precip) else None
            if valor:
                self.tabla_precip_mensual_suelo.setItem(i, 1, QTableWidgetItem(f"{valor:.1f}"))
        self.combo_modo_k.setCurrentIndex(datos.get("modo_k", 0))
        self.spin_k_directo.setValue(datos.get("k_directo", 0.03))
        self.spin_pct_limo_avf.setValue(datos.get("pct_limo_avf", 65.0))
        self.spin_pct_arcilla.setValue(datos.get("pct_arcilla", 15.0))
        self.spin_pct_materia_organica.setValue(datos.get("pct_materia_organica", 2.5))
        self.combo_estructura_suelo.setCurrentIndex(datos.get("estructura_idx", 0))
        self.combo_permeabilidad_suelo.setCurrentIndex(datos.get("permeabilidad_idx", 0))
        self.combo_modo_ls.setCurrentIndex(datos.get("modo_ls", 0))
        self.spin_ls_directo.setValue(datos.get("ls_directo", 2.0))
        self.spin_pendiente_pct_suelo.setValue(datos.get("pendiente_pct", 15.0))
        self.spin_longitud_pendiente.setValue(datos.get("longitud_pendiente", 50.0))
        self.spin_area_contrib_especifica.setValue(datos.get("area_contrib_especifica", 200.0))
        self.combo_modo_c.setCurrentIndex(datos.get("modo_c", 0))
        if datos.get("cobertura"):
            self.combo_cobertura_c.setCurrentText(datos["cobertura"])
        self.spin_ndvi_c.setValue(datos.get("ndvi", 0.5))
        if datos.get("practica"):
            self.combo_practica_p.setCurrentText(datos["practica"])

    def _on_generar_zonas_suelo(self):
        n = self.spin_num_zonas_suelo.value()
        if self.nombre_zona_perdida_suelo_activa:
            self.zonas_perdida_suelo[self.nombre_zona_perdida_suelo_activa] = self._leer_widgets_zona_suelo()
        for _ in range(n):
            self.contador_zonas_perdida_suelo += 1
            nombre = f"Zona {self.contador_zonas_perdida_suelo}"
            self.zonas_perdida_suelo[nombre] = {}
        self.combo_zona_suelo_activa.blockSignals(True)
        self.combo_zona_suelo_activa.clear()
        self.combo_zona_suelo_activa.addItems(list(self.zonas_perdida_suelo.keys()))
        self.combo_zona_suelo_activa.blockSignals(False)
        if self.zonas_perdida_suelo:
            nombre_primera = list(self.zonas_perdida_suelo.keys())[0]
            self.combo_zona_suelo_activa.setCurrentText(nombre_primera)
            self.nombre_zona_perdida_suelo_activa = nombre_primera
            self._escribir_widgets_zona_suelo(self.zonas_perdida_suelo[nombre_primera])

    def _on_cambiar_zona_suelo_activa(self, nombre_nuevo: str):
        if not nombre_nuevo:
            return
        if self.nombre_zona_perdida_suelo_activa and self.nombre_zona_perdida_suelo_activa in self.zonas_perdida_suelo:
            self.zonas_perdida_suelo[self.nombre_zona_perdida_suelo_activa] = self._leer_widgets_zona_suelo()
        self.nombre_zona_perdida_suelo_activa = nombre_nuevo
        self._escribir_widgets_zona_suelo(self.zonas_perdida_suelo.get(nombre_nuevo, {}))

    # -- Cálculo --
    def _calcular_r_zona(self, datos: dict) -> float:
        if datos["modo_r"] == 0:
            return datos["r_directo"]
        elif datos["modo_r"] == 1:
            return soil_loss.r_wischmeier_smith(datos["p_anual_r"])
        else:
            return soil_loss.r_arnoldus_fournier(datos["precip_mensual"])["R"]

    def _calcular_k_zona(self, datos: dict) -> float:
        if datos["modo_k"] == 0:
            return datos["k_directo"]
        r = soil_loss.k_wischmeier_nomograma(
            datos["pct_limo_avf"], datos["pct_arcilla"], datos["pct_materia_organica"],
            datos["estructura_idx"] + 1, datos["permeabilidad_idx"] + 1)
        return r["K_SI"]

    def _calcular_ls_zona(self, datos: dict) -> float:
        if datos["modo_ls"] == 0:
            return datos["ls_directo"]
        elif datos["modo_ls"] == 1:
            return soil_loss.ls_wischmeier_mccool(datos["longitud_pendiente"], datos["pendiente_pct"])["LS"]
        else:
            return soil_loss.ls_moore_burch(datos["area_contrib_especifica"], datos["pendiente_pct"])

    def _calcular_c_zona(self, datos: dict) -> float:
        if datos["modo_c"] == 0:
            return soil_loss.TABLA_C_COBERTURA.get(datos["cobertura"], 0.1)
        return soil_loss.c_desde_ndvi(datos["ndvi"])

    def _calcular_p_zona(self, datos: dict) -> float:
        return soil_loss.TABLA_P_PRACTICAS.get(datos["practica"], 1.0)

    def _on_calcular_perdida_suelo(self, solo_activa: bool):
        if self.nombre_zona_perdida_suelo_activa:
            self.zonas_perdida_suelo[self.nombre_zona_perdida_suelo_activa] = self._leer_widgets_zona_suelo()
        nombres = ([self.nombre_zona_perdida_suelo_activa] if solo_activa
                   else list(self.zonas_perdida_suelo.keys()))

        self.tabla_resultados_suelo.setRowCount(0)
        for nombre in nombres:
            if not nombre:
                continue
            datos = self.zonas_perdida_suelo.get(nombre, {})
            if not datos:
                continue
            try:
                r = self._calcular_r_zona(datos)
                k = self._calcular_k_zona(datos)
                ls = self._calcular_ls_zona(datos)
                c = self._calcular_c_zona(datos)
                p = self._calcular_p_zona(datos)
                a = soil_loss.perdida_suelo(r, k, ls, c, p)
                clase = soil_loss.clasificar_erosion(a)
            except soil_loss.SoilLossError as e:
                QMessageBox.warning(self, f"No se pudo calcular {nombre}", str(e))
                continue
            self.resultados_perdida_suelo[nombre] = {"R": r, "K": k, "LS": ls, "C": c, "P": p, "A": a, "clase": clase}
            fila = self.tabla_resultados_suelo.rowCount()
            self.tabla_resultados_suelo.insertRow(fila)
            valores_fila = [nombre, f"{r:.2f}", f"{k:.4f}", f"{ls:.3f}", f"{c:.3f}", f"{p:.2f}", f"{a:.2f}", clase]
            for j, val in enumerate(valores_fila):
                self.tabla_resultados_suelo.setItem(fila, j, QTableWidgetItem(val))

        self.combo_ver_zona_suelo.blockSignals(True)
        self.combo_ver_zona_suelo.clear()
        self.combo_ver_zona_suelo.addItems(list(self.resultados_perdida_suelo.keys()))
        self.combo_ver_zona_suelo.blockSignals(False)
        if self.resultados_perdida_suelo:
            self.combo_ver_zona_suelo.setCurrentIndex(0)
            self._on_actualizar_grafico_factores_suelo(self.combo_ver_zona_suelo.currentText())
        nombres_ok = list(self.resultados_perdida_suelo.keys())
        valores_a = [self.resultados_perdida_suelo[n]["A"] for n in nombres_ok]
        if valores_a:
            self.canvas_comparacion_suelo.plot_comparacion_zonas(nombres_ok, valores_a)
        self._actualizar_texto_resumen_suelo()

    def _on_actualizar_grafico_factores_suelo(self, nombre_zona: str):
        if not nombre_zona or nombre_zona not in self.resultados_perdida_suelo:
            return
        r = self.resultados_perdida_suelo[nombre_zona]
        self.canvas_factores_suelo.plot_factores(nombre_zona, r["R"], r["K"], r["LS"], r["C"], r["P"], r["A"])

    def _actualizar_texto_resumen_suelo(self):
        html = "<h3>Cuadro resumen final — Pérdida de suelo (USLE/RUSLE)</h3><table border='1' cellpadding='4' cellspacing='0'>"
        html += "<tr><th>Zona</th><th>R</th><th>K</th><th>LS</th><th>C</th><th>P</th><th>A (t/ha/año)</th><th>Clasificación</th></tr>"
        for nombre, r in self.resultados_perdida_suelo.items():
            html += (f"<tr><td>{nombre}</td><td>{r['R']:.2f}</td><td>{r['K']:.4f}</td><td>{r['LS']:.3f}</td>"
                     f"<td>{r['C']:.3f}</td><td>{r['P']:.2f}</td><td><b>{r['A']:.2f}</b></td><td>{r['clase']}</td></tr>")
        html += "</table>"
        if self.raster_perdida_suelo_resultado:
            rr = self.raster_perdida_suelo_resultado
            html += (f"<p><b>Espacialización SIG:</b> media = {rr['media_t_ha_ano']:.2f} t/ha/año, "
                     f"máximo = {rr['maximo_t_ha_ano']:.2f} t/ha/año, área total = {rr['area_total_ha']:.1f} ha<br>"
                     "Área por clase: " + ", ".join(f"{k}: {v:.1f} ha" for k, v in rr["area_por_clase_ha"].items()) + "</p>")
        html += ("<p style='color:#666666'>NOTA: verifique los coeficientes regionales (especialmente el "
                 "factor R de Fournier) contra la referencia de su institución antes de un diseño definitivo.</p>")
        self.texto_resumen_suelo.setHtml(html)

    # -- Espacialización SIG --
    def _on_calcular_ls_raster(self):
        if not self.dem_clip_path:
            QMessageBox.warning(self, "Falta el MDE",
                                 "Delimite primero una cuenca en la Pestaña 1 (se usa el MDE recortado).")
            return
        try:
            context = QgsProcessingContext()
            feedback = QgsProcessingFeedback()
            dem_layer = QgsRasterLayer(self.dem_clip_path, "dem_clip")
            resultado = soil_loss.preparar_ls_raster_moore_burch(
                dem_layer, umbral_acumulacion=self.spin_umbral_acumulacion_suelo.value(),
                context=context, feedback=feedback)
            self._ls_raster_calculado = resultado
            QMessageBox.information(self, "Ráster de LS calculado",
                                     f"LS promedio = {resultado['ls_promedio']:.2f}, "
                                     f"LS máximo = {resultado['ls_maximo']:.2f}\n"
                                     f"Tamaño de celda = {resultado['tamano_celda_m']:.1f} m")
        except (soil_loss.SoilLossError, Exception) as e:
            QMessageBox.critical(self, "Error al calcular el ráster de LS", str(e))

    def _on_calcular_raster_perdida_suelo(self):
        ls_calc = getattr(self, "_ls_raster_calculado", None)
        if not ls_calc:
            QMessageBox.warning(self, "Falta el ráster de LS",
                                 "Calcule primero el ráster de LS (paso 1) en esta misma sección.")
            return
        nombre_zona = self.nombre_zona_perdida_suelo_activa
        if not nombre_zona or nombre_zona not in self.resultados_perdida_suelo:
            QMessageBox.warning(self, "Falta calcular la zona activa",
                                 "Calcule primero R/K/C/P de la zona activa (sección 7) para usarlos aquí.")
            return
        r = self.resultados_perdida_suelo[nombre_zona]
        try:
            resultado = soil_loss.calcular_raster_perdida_suelo(
                ls_calc["ls_raster_path"], r["R"], r["K"], r["C"], r["P"])
            self.raster_perdida_suelo_resultado = resultado
            capa_raster = QgsRasterLayer(resultado["raster_path"], f"Pérdida de suelo USLE — {nombre_zona}")
            if capa_raster.isValid():
                QgsProject.instance().addMapLayer(capa_raster)
            from osgeo import gdal
            ds = gdal.Open(resultado["raster_path"])
            array_a = ds.GetRasterBand(1).ReadAsArray().astype("float64")
            nodata = ds.GetRasterBand(1).GetNoDataValue()
            ds = None
            if nodata is not None:
                import numpy as np
                array_a = np.where(array_a == nodata, np.nan, array_a)
            self.canvas_mapa_suelo.plot_mapa_clasificado(array_a, resultado["area_por_clase_ha"])
            self._actualizar_texto_resumen_suelo()
            QMessageBox.information(self, "Ráster de pérdida de suelo generado",
                                     f"Media = {resultado['media_t_ha_ano']:.2f} t/ha/año\n"
                                     f"Máximo = {resultado['maximo_t_ha_ano']:.2f} t/ha/año\n"
                                     "Capa agregada al lienzo de QGIS.")
        except (soil_loss.SoilLossError, Exception) as e:
            QMessageBox.critical(self, "Error al generar el ráster de pérdida de suelo", str(e))

    # ------------------------------------------------------------------
    # TAB 12: Sedimentos en Suspensión y Transporte de Sedimentos.
    # Ver core/sediment_transport.py.
    # ------------------------------------------------------------------
    def _build_tab_sedimentos(self):
        tab = QWidget()
        v = QVBoxLayout(tab)
        _lbl_auto_31 = QLabel(
            "<b>Sedimentos en Suspensión y Transporte de Sedimentos</b> — inicio del movimiento "
            "(tensión tangencial τ0 vs. crítica de Shields), carga de FONDO (Meyer-Peter y Müller, "
            "Einstein-Brown, Bagnold), carga en SUSPENSIÓN (perfil de Rouse / Lane y Kalinske, integrado "
            "numéricamente) y carga TOTAL (Engelund y Hansen, Yang, Ackers y White). Cree una o más "
            "secciones (GIS o tabla manual pegable) en el punto de interés, con sus propiedades "
            "hidráulicas y de sedimento."
        )
        _lbl_auto_31.setWordWrap(True)
        v.addWidget(_lbl_auto_31)

        # ---------------- Gestión de secciones ----------------
        gb_secciones = QGroupBox("1. Secciones transversales de estudio")
        v_s = QVBoxLayout(gb_secciones)
        h_gen = QHBoxLayout()
        h_gen.addWidget(QLabel("Número de secciones a crear:"))
        self.spin_num_secciones_sedimentos = QSpinBox(); self.spin_num_secciones_sedimentos.setRange(1, 30); self.spin_num_secciones_sedimentos.setValue(1)
        h_gen.addWidget(self.spin_num_secciones_sedimentos)
        btn_generar = QPushButton("Generar secciones")
        btn_generar.clicked.connect(self._on_generar_secciones_sedimentos)
        h_gen.addWidget(btn_generar)
        h_gen.addWidget(QLabel("Sección activa:"))
        self.combo_seccion_sedimentos_activa = QComboBox()
        self.combo_seccion_sedimentos_activa.currentTextChanged.connect(self._on_cambiar_seccion_sedimentos_activa)
        h_gen.addWidget(self.combo_seccion_sedimentos_activa)
        v_s.addLayout(h_gen)

        h_origen = QHBoxLayout()
        h_origen.addWidget(QLabel("Origen de esta sección:"))
        self.combo_origen_seccion_sedimentos = QComboBox()
        self.combo_origen_seccion_sedimentos.addItems([
            "Manual (pegar tabla tipo Excel)", "Desde GIS (MDE + línea trazada en el mapa)"])
        h_origen.addWidget(self.combo_origen_seccion_sedimentos)
        self.combo_dem_sedimentos = QgsMapLayerComboBox()
        self.combo_dem_sedimentos.setFilters(QgsMapLayerProxyModel.RasterLayer)
        h_origen.addWidget(QLabel("MDE:"))
        h_origen.addWidget(self.combo_dem_sedimentos)
        self.btn_trazar_seccion_sedimentos = QPushButton("Trazar línea de sección en el mapa (2 clics)")
        self.btn_trazar_seccion_sedimentos.setCheckable(True)
        self.btn_trazar_seccion_sedimentos.clicked.connect(self._activar_map_tool_sedimentos)
        h_origen.addWidget(self.btn_trazar_seccion_sedimentos)
        v_s.addLayout(h_origen)

        self.tabla_seccion_sedimentos = TablaPegable(10, 3)
        self.tabla_seccion_sedimentos.setHorizontalHeaderLabels(
            ["Estación (m)", "Elevación fondo (m s.n.m.)", "Velocidad media (m/s, opcional)"])
        self.tabla_seccion_sedimentos.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla_seccion_sedimentos.setMinimumHeight(200)
        v_s.addWidget(self.tabla_seccion_sedimentos)

        f_hid = QFormLayout()
        f_hid.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.spin_q_sedimentos = QDoubleSpinBox(); self.spin_q_sedimentos.setRange(0.001, 200000); self.spin_q_sedimentos.setDecimals(3); self.spin_q_sedimentos.setValue(45.0)
        f_hid.addRow("Caudal Q (m³/s):", self.spin_q_sedimentos)
        self.spin_v_sedimentos = QDoubleSpinBox(); self.spin_v_sedimentos.setRange(0.01, 30); self.spin_v_sedimentos.setDecimals(3); self.spin_v_sedimentos.setValue(1.5)
        f_hid.addRow("Velocidad media V (m/s):", self.spin_v_sedimentos)
        self.spin_r_sedimentos = QDoubleSpinBox(); self.spin_r_sedimentos.setRange(0.01, 100); self.spin_r_sedimentos.setDecimals(3); self.spin_r_sedimentos.setValue(1.2)
        f_hid.addRow("Radio hidráulico R (m):", self.spin_r_sedimentos)
        self.spin_b_sedimentos = QDoubleSpinBox(); self.spin_b_sedimentos.setRange(0.1, 5000); self.spin_b_sedimentos.setDecimals(2); self.spin_b_sedimentos.setValue(25.0)
        f_hid.addRow("Ancho de fondo b (m):", self.spin_b_sedimentos)
        self.spin_s_sedimentos = QDoubleSpinBox(); self.spin_s_sedimentos.setRange(0.00001, 0.5); self.spin_s_sedimentos.setDecimals(5); self.spin_s_sedimentos.setValue(0.0010)
        f_hid.addRow("Pendiente de la línea de energía S (m/m):", self.spin_s_sedimentos)
        v_s.addLayout(f_hid)

        f_sed = QFormLayout()
        f_sed.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.spin_d50_sedimentos = QDoubleSpinBox(); self.spin_d50_sedimentos.setRange(0.001, 500); self.spin_d50_sedimentos.setDecimals(3); self.spin_d50_sedimentos.setValue(0.5)
        f_sed.addRow("D50 del lecho (mm):", self.spin_d50_sedimentos)
        self.spin_rho_s_sedimentos = QDoubleSpinBox(); self.spin_rho_s_sedimentos.setRange(1800, 3200); self.spin_rho_s_sedimentos.setDecimals(0); self.spin_rho_s_sedimentos.setValue(2650)
        f_sed.addRow("Densidad de partícula ρs (kg/m³):", self.spin_rho_s_sedimentos)
        self.combo_modo_ws = QComboBox()
        self.combo_modo_ws.addItems(["Calcular (Van Rijn, 1984)", "Ingresar manualmente"])
        f_sed.addRow("Velocidad de caída ws:", self.combo_modo_ws)
        self.spin_ws_manual = QDoubleSpinBox(); self.spin_ws_manual.setRange(0.0001, 5); self.spin_ws_manual.setDecimals(5); self.spin_ws_manual.setValue(0.02)
        f_sed.addRow("ws manual (m/s):", self.spin_ws_manual)
        self.spin_ca_concentracion = QDoubleSpinBox(); self.spin_ca_concentracion.setRange(0.00001, 0.1); self.spin_ca_concentracion.setDecimals(5); self.spin_ca_concentracion.setValue(0.00100)
        f_sed.addRow("Concentración de referencia Ca (fracción vol., muestreador de campo):", self.spin_ca_concentracion)
        self.spin_a_relativo = QDoubleSpinBox(); self.spin_a_relativo.setRange(0.01, 0.5); self.spin_a_relativo.setDecimals(3); self.spin_a_relativo.setValue(0.05)
        f_sed.addRow("Altura de referencia a/h:", self.spin_a_relativo)
        self.spin_eb_bagnold = QDoubleSpinBox(); self.spin_eb_bagnold.setRange(0.01, 0.5); self.spin_eb_bagnold.setDecimals(3); self.spin_eb_bagnold.setValue(0.15)
        f_sed.addRow("eb — eficiencia de Bagnold:", self.spin_eb_bagnold)
        self.spin_tan_alpha_bagnold = QDoubleSpinBox(); self.spin_tan_alpha_bagnold.setRange(0.1, 1.2); self.spin_tan_alpha_bagnold.setDecimals(3); self.spin_tan_alpha_bagnold.setValue(0.63)
        f_sed.addRow("tan(α) — fricción dinámica de Bagnold:", self.spin_tan_alpha_bagnold)
        v_s.addLayout(f_sed)
        v.addWidget(gb_secciones)

        # ---------------- Métodos ----------------
        gb_metodos = QGroupBox("2. Métodos de cálculo a aplicar")
        h_met = QHBoxLayout(gb_metodos)
        v_fondo = QVBoxLayout(); v_fondo.addWidget(QLabel("<b>Carga de fondo</b>"))
        self.chk_mpm = QCheckBox("Meyer-Peter y Müller"); self.chk_mpm.setChecked(True)
        self.chk_einstein_brown = QCheckBox("Einstein-Brown")
        self.chk_bagnold = QCheckBox("Bagnold")
        for c in (self.chk_mpm, self.chk_einstein_brown, self.chk_bagnold):
            v_fondo.addWidget(c)
        h_met.addLayout(v_fondo)
        v_susp = QVBoxLayout(); v_susp.addWidget(QLabel("<b>Suspensión</b>"))
        self.chk_rouse = QCheckBox("Rouse / Lane y Kalinske"); self.chk_rouse.setChecked(True)
        v_susp.addWidget(self.chk_rouse)
        h_met.addLayout(v_susp)
        v_total = QVBoxLayout(); v_total.addWidget(QLabel("<b>Carga total</b>"))
        self.chk_engelund_hansen = QCheckBox("Engelund y Hansen"); self.chk_engelund_hansen.setChecked(True)
        self.chk_yang = QCheckBox("Yang")
        self.chk_ackers_white = QCheckBox("Ackers y White")
        for c in (self.chk_engelund_hansen, self.chk_yang, self.chk_ackers_white):
            v_total.addWidget(c)
        h_met.addLayout(v_total)
        v.addWidget(gb_metodos)

        h_calc = QHBoxLayout()
        btn_calc_activa = QPushButton("Calcular — sección activa")
        btn_calc_activa.clicked.connect(lambda: self._on_calcular_sedimentos(solo_activa=True))
        h_calc.addWidget(btn_calc_activa)
        btn_calc_todas = QPushButton("Calcular — TODAS las secciones")
        btn_calc_todas.clicked.connect(lambda: self._on_calcular_sedimentos(solo_activa=False))
        h_calc.addWidget(btn_calc_todas)
        v.addLayout(h_calc)

        # ---------------- Resultados ----------------
        gb_resultados = QGroupBox("3. Resultados")
        v_r = QVBoxLayout(gb_resultados)
        self.tabla_resultados_sedimentos = QTableWidget(0, 5)
        self.tabla_resultados_sedimentos.setHorizontalHeaderLabels(
            ["Sección", "Método", "Tipo", "Tasa de transporte", "Observación"])
        # "Observación" trae texto explicativo de longitud variable (p.ej.
        # la advertencia de Einstein-Brown cuando Psi<1); en Stretch para
        # que no empuje la tabla más allá del ancho de la ventana.
        aplicar_columna_elastica(self.tabla_resultados_sedimentos, indice_columna_larga=4)
        self.tabla_resultados_sedimentos.setMinimumHeight(200)
        v_r.addWidget(self.tabla_resultados_sedimentos)

        h_ver = QHBoxLayout()
        h_ver.addWidget(QLabel("Ver sección:"))
        self.combo_ver_seccion_sedimentos = QComboBox()
        self.combo_ver_seccion_sedimentos.currentTextChanged.connect(self._on_actualizar_graficos_sedimentos)
        h_ver.addWidget(self.combo_ver_seccion_sedimentos)
        h_ver.addWidget(QLabel("Método a graficar en la sección:"))
        self.combo_ver_metodo_sedimentos = QComboBox()
        self.combo_ver_metodo_sedimentos.currentTextChanged.connect(self._on_actualizar_grafico_seccion_sedimentos)
        h_ver.addWidget(self.combo_ver_metodo_sedimentos)
        v_r.addLayout(h_ver)

        self.canvas_seccion_sedimentos = SedimentCanvas(width=7.4, height=5.0)
        v_r.addWidget(self.canvas_seccion_sedimentos)

        self.canvas_comparacion_fondo_sedimentos = SedimentCanvas(width=7.4, height=4.6)
        v_r.addWidget(self.canvas_comparacion_fondo_sedimentos)
        self.canvas_comparacion_total_sedimentos = SedimentCanvas(width=7.4, height=4.6)
        v_r.addWidget(self.canvas_comparacion_total_sedimentos)

        self.canvas_perfil_rouse_sedimentos = SedimentCanvas(width=7.4, height=4.8)
        v_r.addWidget(self.canvas_perfil_rouse_sedimentos)

        v.addWidget(gb_resultados)

        v.addWidget(QLabel("<b>Cuadro resumen final:</b>"))
        self.texto_resumen_sedimentos = QTextBrowser()
        self.texto_resumen_sedimentos.setMinimumHeight(160)
        v.addWidget(self.texto_resumen_sedimentos)

        self._agregar_pestaña_con_scroll(tab, "12. Sedimentos en Suspensión y Transporte")

    # -- Gestión de secciones (mismo patrón que socavación) --
    def _leer_widgets_seccion_sedimentos(self) -> dict:
        filas = self._leer_tabla_generica(self.tabla_seccion_sedimentos, 3)
        estaciones, elevaciones, velocidades = [], [], []
        for fila in filas:
            est, elev = fila[0], fila[1]
            vel = fila[2] if len(fila) > 2 else ""
            try:
                estaciones.append(float(est.replace(",", ".")))
                elevaciones.append(float(elev.replace(",", ".")))
                velocidades.append(float(vel.replace(",", ".")) if vel else None)
            except ValueError:
                continue
        return {
            "estaciones": estaciones, "elevaciones": elevaciones, "velocidades": velocidades,
            "origen": self.combo_origen_seccion_sedimentos.currentIndex(),
            "q": self.spin_q_sedimentos.value(), "v": self.spin_v_sedimentos.value(),
            "r": self.spin_r_sedimentos.value(), "b": self.spin_b_sedimentos.value(),
            "s": self.spin_s_sedimentos.value(), "d50": self.spin_d50_sedimentos.value(),
            "rho_s": self.spin_rho_s_sedimentos.value(), "modo_ws": self.combo_modo_ws.currentIndex(),
            "ws_manual": self.spin_ws_manual.value(), "ca": self.spin_ca_concentracion.value(),
            "a_relativo": self.spin_a_relativo.value(), "eb": self.spin_eb_bagnold.value(),
            "tan_alpha": self.spin_tan_alpha_bagnold.value(),
        }

    def _escribir_widgets_seccion_sedimentos(self, datos: dict):
        self.tabla_seccion_sedimentos.setRowCount(max(len(datos.get("estaciones", [])), 10))
        for i, (est, elev, vel) in enumerate(zip(
                datos.get("estaciones", []), datos.get("elevaciones", []), datos.get("velocidades", []))):
            self.tabla_seccion_sedimentos.setItem(i, 0, QTableWidgetItem(f"{est:.2f}"))
            self.tabla_seccion_sedimentos.setItem(i, 1, QTableWidgetItem(f"{elev:.2f}"))
            if vel is not None:
                self.tabla_seccion_sedimentos.setItem(i, 2, QTableWidgetItem(f"{vel:.3f}"))
        self.combo_origen_seccion_sedimentos.setCurrentIndex(datos.get("origen", 0))
        self.spin_q_sedimentos.setValue(datos.get("q", 45.0))
        self.spin_v_sedimentos.setValue(datos.get("v", 1.5))
        self.spin_r_sedimentos.setValue(datos.get("r", 1.2))
        self.spin_b_sedimentos.setValue(datos.get("b", 25.0))
        self.spin_s_sedimentos.setValue(datos.get("s", 0.0010))
        self.spin_d50_sedimentos.setValue(datos.get("d50", 0.5))
        self.spin_rho_s_sedimentos.setValue(datos.get("rho_s", 2650))
        self.combo_modo_ws.setCurrentIndex(datos.get("modo_ws", 0))
        self.spin_ws_manual.setValue(datos.get("ws_manual", 0.02))
        self.spin_ca_concentracion.setValue(datos.get("ca", 0.001))
        self.spin_a_relativo.setValue(datos.get("a_relativo", 0.05))
        self.spin_eb_bagnold.setValue(datos.get("eb", 0.15))
        self.spin_tan_alpha_bagnold.setValue(datos.get("tan_alpha", 0.63))

    def _on_generar_secciones_sedimentos(self):
        n = self.spin_num_secciones_sedimentos.value()
        if self.nombre_seccion_sedimentos_activa:
            self.secciones_sedimentos[self.nombre_seccion_sedimentos_activa] = self._leer_widgets_seccion_sedimentos()
        for _ in range(n):
            self.contador_secciones_sedimentos += 1
            nombre = f"Sección {self.contador_secciones_sedimentos}"
            self.secciones_sedimentos[nombre] = {}
        self.combo_seccion_sedimentos_activa.blockSignals(True)
        self.combo_seccion_sedimentos_activa.clear()
        self.combo_seccion_sedimentos_activa.addItems(list(self.secciones_sedimentos.keys()))
        self.combo_seccion_sedimentos_activa.blockSignals(False)
        if self.secciones_sedimentos:
            nombre_primera = list(self.secciones_sedimentos.keys())[0]
            self.combo_seccion_sedimentos_activa.setCurrentText(nombre_primera)
            self.nombre_seccion_sedimentos_activa = nombre_primera
            self._escribir_widgets_seccion_sedimentos(self.secciones_sedimentos[nombre_primera])

    def _on_cambiar_seccion_sedimentos_activa(self, nombre_nuevo: str):
        if not nombre_nuevo:
            return
        if self.nombre_seccion_sedimentos_activa and self.nombre_seccion_sedimentos_activa in self.secciones_sedimentos:
            self.secciones_sedimentos[self.nombre_seccion_sedimentos_activa] = self._leer_widgets_seccion_sedimentos()
        self.nombre_seccion_sedimentos_activa = nombre_nuevo
        self._escribir_widgets_seccion_sedimentos(self.secciones_sedimentos.get(nombre_nuevo, {}))

    # -- Extracción GIS (idéntico patrón al de socavación, estado propio) --
    def _activar_map_tool_sedimentos(self, checked):
        canvas = self.iface.mapCanvas()
        if checked:
            self._primer_clic_seccion_sedimentos = None
            self.map_tool_sedimentos = QgsMapToolEmitPoint(canvas)
            self.map_tool_sedimentos.canvasClicked.connect(self._on_canvas_clicked_sedimentos)
            canvas.mapToolSet.connect(self._on_map_tool_changed_sedimentos)
            canvas.setMapTool(self.map_tool_sedimentos)
            self.btn_trazar_seccion_sedimentos.setText("Clic en el INICIO de la sección...")
            self.hide()
        else:
            try:
                canvas.mapToolSet.disconnect(self._on_map_tool_changed_sedimentos)
            except TypeError:
                pass
            canvas.unsetMapTool(self.map_tool_sedimentos)
            self.btn_trazar_seccion_sedimentos.setText("Trazar línea de sección en el mapa (2 clics)")
            self._restaurar_ventana()

    def _on_map_tool_changed_sedimentos(self, herramienta_nueva, herramienta_anterior):
        if herramienta_nueva is not self.map_tool_sedimentos:
            self.btn_trazar_seccion_sedimentos.setChecked(False)
            self.btn_trazar_seccion_sedimentos.setText("Trazar línea de sección en el mapa (2 clics)")
            self._restaurar_ventana()

    def _on_canvas_clicked_sedimentos(self, punto, button):
        if self._primer_clic_seccion_sedimentos is None:
            self._primer_clic_seccion_sedimentos = QgsPointXY(punto)
            self.btn_trazar_seccion_sedimentos.setText("Clic en el FIN de la sección...")
            return
        punto_inicio = self._primer_clic_seccion_sedimentos
        punto_fin = QgsPointXY(punto)
        self._primer_clic_seccion_sedimentos = None
        canvas = self.iface.mapCanvas()
        try:
            canvas.mapToolSet.disconnect(self._on_map_tool_changed_sedimentos)
        except TypeError:
            pass
        canvas.unsetMapTool(self.map_tool_sedimentos)
        self.btn_trazar_seccion_sedimentos.setChecked(False)
        self.btn_trazar_seccion_sedimentos.setText("Trazar línea de sección en el mapa (2 clics)")
        self._restaurar_ventana()

        dem_layer = self.combo_dem_sedimentos.currentLayer()
        if dem_layer is None:
            QMessageBox.warning(self, "Falta el MDE", "Seleccione una capa ráster de MDE antes de trazar la sección.")
            return
        try:
            n_muestras = 30
            provider = dem_layer.dataProvider()
            distancia_total = punto_inicio.distance(punto_fin)
            if distancia_total <= 0:
                raise sediment_transport.SedimentTransportError("La línea trazada tiene longitud cero.")
            estaciones, elevaciones = [], []
            for i in range(n_muestras + 1):
                frac = i / n_muestras
                x = punto_inicio.x() + frac * (punto_fin.x() - punto_inicio.x())
                y = punto_inicio.y() + frac * (punto_fin.y() - punto_inicio.y())
                resultado = provider.identify(QgsPointXY(x, y), 1)
                valor = None
                if resultado.isValid():
                    valores = resultado.results()
                    if valores:
                        valor = list(valores.values())[0]
                if valor is None:
                    continue
                estaciones.append(frac * distancia_total)
                elevaciones.append(float(valor))
            if len(estaciones) < 2:
                raise sediment_transport.SedimentTransportError("No se pudo muestrear el MDE a lo largo de la línea trazada.")
            self.tabla_seccion_sedimentos.setRowCount(max(len(estaciones), 10))
            for i, (est, elev) in enumerate(zip(estaciones, elevaciones)):
                self.tabla_seccion_sedimentos.setItem(i, 0, QTableWidgetItem(f"{est:.2f}"))
                self.tabla_seccion_sedimentos.setItem(i, 1, QTableWidgetItem(f"{elev:.2f}"))
            QMessageBox.information(self, "Sección extraída del MDE",
                                     f"Se muestrearon {len(estaciones)} puntos a lo largo de {distancia_total:.1f} m.\n"
                                     "Complete la columna de Velocidad media (m/s) si desea variarla por vertical.")
        except sediment_transport.SedimentTransportError as e:
            QMessageBox.warning(self, "No se pudo extraer la sección", str(e))

    # -- Cálculo --
    def _on_calcular_sedimentos(self, solo_activa: bool):
        if self.nombre_seccion_sedimentos_activa:
            self.secciones_sedimentos[self.nombre_seccion_sedimentos_activa] = self._leer_widgets_seccion_sedimentos()
        nombres = ([self.nombre_seccion_sedimentos_activa] if solo_activa
                   else list(self.secciones_sedimentos.keys()))

        self.tabla_resultados_sedimentos.setRowCount(0)
        filas_reporte = []
        for nombre in nombres:
            if not nombre:
                continue
            datos = self.secciones_sedimentos.get(nombre, {})
            estaciones = datos.get("estaciones", [])
            elevaciones = datos.get("elevaciones", [])
            if len(estaciones) < 2:
                continue
            q, v_media, r, b, s = datos.get("q", 45), datos.get("v", 1.5), datos.get("r", 1.2), datos.get("b", 25), datos.get("s", 0.001)
            d50 = datos.get("d50", 0.5)
            rho_s = datos.get("rho_s", 2650)
            gamma_agua = 9810.0

            if datos.get("modo_ws", 0) == 0:
                ws = sediment_transport.velocidad_caida_van_rijn(d50, rho_s)
            else:
                ws = datos.get("ws_manual", 0.02)

            tau0 = sediment_transport.tension_tangencial(gamma_agua, r, s)
            shields = sediment_transport.shields_critico_van_rijn(d50, rho_s)
            u_estrella = math.sqrt(9.81 * r * s)

            resultados_metodo = {}
            resultados_fondo, resultados_total = {}, {}

            if self.chk_mpm.isChecked():
                res = sediment_transport.meyer_peter_muller(tau0, d50, rho_s)
                resultados_fondo["Meyer-Peter y Müller"] = res["qb_m3_s_m"]
                filas_reporte.append((nombre, "Meyer-Peter y Müller", "Fondo", f"{res['qb_m3_s_m']:.5g} m³/s/m",
                                      f"θ={res['theta']:.3f}, θc={res['theta_c']:.4f}"))
            if self.chk_einstein_brown.isChecked():
                res = sediment_transport.einstein_brown(tau0, r, s, d50, rho_s)
                resultados_fondo["Einstein-Brown"] = res["qb_m3_s_m"]
                filas_reporte.append((nombre, "Einstein-Brown", "Fondo", f"{res['qb_m3_s_m']:.5g} m³/s/m",
                                      res.get("advertencia") or f"Ψ={res['Psi']:.3f}"))
            if self.chk_bagnold.isChecked():
                res = sediment_transport.bagnold_carga_fondo(tau0, v_media, datos.get("eb", 0.15),
                                                              datos.get("tan_alpha", 0.63), rho_s)
                resultados_fondo["Bagnold"] = res["qb_m3_s_m"]
                filas_reporte.append((nombre, "Bagnold", "Fondo", f"{res['qb_m3_s_m']:.5g} m³/s/m",
                                      f"ω={res['omega_W_m2']:.2f} W/m²"))

            if self.chk_rouse.isChecked():
                h_medio = max(q / (v_media * b), 0.1) if v_media > 0 and b > 0 else r
                res = sediment_transport.carga_suspension_rouse(h_medio, u_estrella, ws, datos.get("ca", 0.001),
                                                                  datos.get("a_relativo", 0.05))
                resultados_metodo["Rouse / Lane y Kalinske"] = res["qs_m3_s_m"]
                filas_reporte.append((nombre, "Rouse / Lane y Kalinske", "Suspensión", f"{res['qs_m3_s_m']:.5g} m³/s/m",
                                      f"Z={res['Z_rouse']:.3f}"))
                self._ultimo_perfil_rouse = res

            if self.chk_engelund_hansen.isChecked():
                res = sediment_transport.engelund_hansen(tau0, v_media, r, s, d50, rho_s)
                resultados_total["Engelund y Hansen"] = res["qt_m3_s_m"]
                filas_reporte.append((nombre, "Engelund y Hansen", "Total", f"{res['qt_m3_s_m']:.5g} m³/s/m",
                                      f"Cf={res['Cf']:.4f}, θ={res['theta']:.3f}"))
            if self.chk_yang.isChecked():
                res = sediment_transport.yang_1973_concentracion(v_media, s, u_estrella, ws, d50, q, b)
                if res.get("qt_m3_s_m") is not None:
                    resultados_total["Yang"] = res["qt_m3_s_m"]
                filas_reporte.append((nombre, "Yang", "Total",
                                      f"{res.get('qt_m3_s_m', 0):.5g} m³/s/m" if res.get("transporte_activo") else "0 (sin transporte)",
                                      f"Ct={res.get('Ct_ppm', 0):.1f} ppm" if res.get("Ct_ppm") else "V<Vcr"))
            if self.chk_ackers_white.isChecked():
                try:
                    res = sediment_transport.ackers_white(v_media, r, d50, rho_s)
                    resultados_total["Ackers y White"] = res["qt_m3_s_m"]
                    filas_reporte.append((nombre, "Ackers y White", "Total", f"{res['qt_m3_s_m']:.5g} m³/s/m",
                                          f"Dgr={res['Dgr']:.2f}, Fgr={res['Fgr']:.3f}"))
                except sediment_transport.SedimentTransportError as e:
                    filas_reporte.append((nombre, "Ackers y White", "Total", "—", f"Error: {e}"))

            resultados_metodo.update(resultados_fondo)
            resultados_metodo.update(resultados_total)
            resumen = sediment_transport.resumen_comparativo(resultados_metodo)
            self.resultados_sedimentos[nombre] = {
                "estaciones": estaciones, "elevaciones": elevaciones,
                "resultados_metodo": resultados_metodo, "resultados_fondo": resultados_fondo,
                "resultados_total": resultados_total, "resumen": resumen,
                "tau0": tau0, "tau_critico": shields["tau_critico_Pa"],
                "hay_transporte": tau0 > shields["tau_critico_Pa"],
                "perfil_rouse": getattr(self, "_ultimo_perfil_rouse", None),
            }

        for nombre, metodo, tipo, tasa, obs in filas_reporte:
            fila = self.tabla_resultados_sedimentos.rowCount()
            self.tabla_resultados_sedimentos.insertRow(fila)
            for j, val in enumerate([nombre, metodo, tipo, tasa, obs]):
                self.tabla_resultados_sedimentos.setItem(fila, j, QTableWidgetItem(str(val)))

        self.combo_ver_seccion_sedimentos.blockSignals(True)
        self.combo_ver_seccion_sedimentos.clear()
        self.combo_ver_seccion_sedimentos.addItems(list(self.resultados_sedimentos.keys()))
        self.combo_ver_seccion_sedimentos.blockSignals(False)
        self._actualizar_texto_resumen_sedimentos()
        if self.resultados_sedimentos:
            self.combo_ver_seccion_sedimentos.setCurrentIndex(0)
            self._on_actualizar_graficos_sedimentos(self.combo_ver_seccion_sedimentos.currentText())

    def _on_actualizar_graficos_sedimentos(self, nombre_seccion: str):
        if not nombre_seccion or nombre_seccion not in self.resultados_sedimentos:
            return
        r = self.resultados_sedimentos[nombre_seccion]
        self.combo_ver_metodo_sedimentos.blockSignals(True)
        self.combo_ver_metodo_sedimentos.clear()
        self.combo_ver_metodo_sedimentos.addItems(list(r["resultados_metodo"].keys()))
        self.combo_ver_metodo_sedimentos.blockSignals(False)
        if r["resultados_metodo"]:
            self.combo_ver_metodo_sedimentos.setCurrentIndex(0)
            self._on_actualizar_grafico_seccion_sedimentos(self.combo_ver_metodo_sedimentos.currentText())
        if r["resultados_fondo"]:
            self.canvas_comparacion_fondo_sedimentos.plot_comparacion_metodos(
                list(r["resultados_fondo"].keys()), list(r["resultados_fondo"].values()),
                titulo="Comparación — carga de fondo",
                metodo_gobernante=max(r["resultados_fondo"], key=lambda k: r["resultados_fondo"][k]))
        if r["resultados_total"]:
            self.canvas_comparacion_total_sedimentos.plot_comparacion_metodos(
                list(r["resultados_total"].keys()), list(r["resultados_total"].values()),
                titulo="Comparación — carga total",
                metodo_gobernante=max(r["resultados_total"], key=lambda k: r["resultados_total"][k]))
        if r.get("perfil_rouse"):
            pr = r["perfil_rouse"]
            self.canvas_perfil_rouse_sedimentos.plot_perfil_rouse(
                pr["perfil_y"], pr["perfil_concentracion"], pr["perfil_velocidad"], pr["Z_rouse"])

    def _on_actualizar_grafico_seccion_sedimentos(self, nombre_metodo: str):
        nombre_seccion = self.combo_ver_seccion_sedimentos.currentText()
        if not nombre_seccion or nombre_seccion not in self.resultados_sedimentos or not nombre_metodo:
            return
        r = self.resultados_sedimentos[nombre_seccion]
        tasa_valor = r["resultados_metodo"].get(nombre_metodo, 0.0)
        elevaciones = r["elevaciones"]
        cota_agua_aprox = min(elevaciones) + self.spin_r_sedimentos.value() if elevaciones else 0
        tasa_por_estacion = [tasa_valor if z <= cota_agua_aprox else 0.0 for z in elevaciones]
        self.canvas_seccion_sedimentos.plot_seccion_transporte(
            r["estaciones"], elevaciones, tasa_por_estacion,
            nombre_seccion=nombre_seccion, nombre_metodo=nombre_metodo)

    def _actualizar_texto_resumen_sedimentos(self):
        html = "<h3>Cuadro resumen final — Transporte de sedimentos</h3>"
        for nombre, r in self.resultados_sedimentos.items():
            resumen = r["resumen"]
            html += f"<p><b>{nombre}</b><br>"
            html += (f"τ0 = {r['tau0']:.2f} Pa, τ crítico = {r['tau_critico']:.3f} Pa → "
                     f"{'<b>HAY transporte activo</b>' if r['hay_transporte'] else 'sin transporte (τ0 &lt; τ crítico)'}<br>")
            if resumen:
                html += (f"Método gobernante (mayor tasa): <b>{resumen['metodo_gobernante']}</b><br>"
                         f"Tasa de diseño recomendada: <b>{resumen['qt_diseño_recomendado']:.4g} m³/s/m</b><br>"
                         f"Promedio: {resumen['promedio']:.4g} m³/s/m &nbsp;|&nbsp; "
                         f"Rango: {resumen['minimo']:.4g} – {resumen['maximo']:.4g} m³/s/m</p><hr>")
            else:
                html += "</p><hr>"
        html += ("<p style='color:#666666'>NOTA: contraste siempre entre los métodos de fondo, suspensión y "
                 "total calculados; las diferencias entre fórmulas (especialmente Einstein-Brown en régimen "
                 "de transporte muy alto) son esperables y reflejan las distintas hipótesis de cada método.</p>")
        self.texto_resumen_sedimentos.setHtml(html)

    # ------------------------------------------------------------------
    # TAB 13: Flujos Hiperconcentrados/Lodos/Detritos. Ver core/debris_flow.py.
    # ------------------------------------------------------------------
    def _build_tab_flujos_hiperconcentrados(self):
        tab = QWidget()
        v = QVBoxLayout(tab)
        _lbl_auto_32 = QLabel(
            "<b>Flujos Hiperconcentrados / Lodos / Detritos</b> — clasificación por concentración "
            "volumétrica Cv, reología de Bingham (directa o estimación empírica de Julien y Lan), factor "
            "de amplificación por sedimento (bulking factor) y cálculo de tirante/velocidad por "
            "O'Brien y Julien (resistencia general) y Takahashi (velocidad crítica de detritos maduros). "
            "El cálculo manual sirve como validación preliminar; el diseño definitivo requiere modelación "
            "2D (FLO-2D, HEC-RAS ≥6.0, RAMMS)."
        )
        _lbl_auto_32.setWordWrap(True)
        v.addWidget(_lbl_auto_32)

        gb_clasif = QGroupBox("1. Caracterización y clasificación del flujo")
        f_clasif = QFormLayout(gb_clasif)
        f_clasif.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.spin_cv_flujo = QDoubleSpinBox(); self.spin_cv_flujo.setRange(0.1, 99.0); self.spin_cv_flujo.setDecimals(1); self.spin_cv_flujo.setValue(50.0)
        f_clasif.addRow("Concentración volumétrica de sedimentos Cv (%):", self.spin_cv_flujo)
        self.spin_gamma_s_flujo = QDoubleSpinBox(); self.spin_gamma_s_flujo.setRange(15000, 32000); self.spin_gamma_s_flujo.setDecimals(0); self.spin_gamma_s_flujo.setValue(26000)
        f_clasif.addRow("Peso específico de sólidos γs (N/m³):", self.spin_gamma_s_flujo)
        self.spin_gamma_w_flujo = QDoubleSpinBox(); self.spin_gamma_w_flujo.setRange(9000, 10500); self.spin_gamma_w_flujo.setDecimals(0); self.spin_gamma_w_flujo.setValue(9810)
        f_clasif.addRow("Peso específico del agua γw (N/m³):", self.spin_gamma_w_flujo)
        btn_clasificar = QPushButton("Clasificar flujo")
        btn_clasificar.clicked.connect(self._on_clasificar_flujo)
        limitar_ancho_boton(btn_clasificar)
        f_clasif.addRow(btn_clasificar)
        v.addWidget(gb_clasif)
        self.canvas_clasificacion_flujo = DebrisFlowCanvas(width=7.2, height=3.2)
        v.addWidget(self.canvas_clasificacion_flujo)

        gb_reologia = QGroupBox("2. Parámetros reológicos (Bingham)")
        f_reo = QFormLayout(gb_reologia)
        f_reo.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.combo_modo_reologia = QComboBox()
        self.combo_modo_reologia.addItems(["Directo (ya tengo τy y μp de ensayo)",
                                            "Estimación empírica de Julien y Lan (1991)"])
        f_reo.addRow("Método:", self.combo_modo_reologia)
        self.spin_tau_y_directo = QDoubleSpinBox(); self.spin_tau_y_directo.setRange(0, 5000); self.spin_tau_y_directo.setDecimals(2); self.spin_tau_y_directo.setValue(90.0)
        f_reo.addRow("τy directo (Pa):", self.spin_tau_y_directo)
        self.spin_mu_p_directo = QDoubleSpinBox(); self.spin_mu_p_directo.setRange(0, 500); self.spin_mu_p_directo.setDecimals(3); self.spin_mu_p_directo.setValue(0.3)
        f_reo.addRow("μp directo (Pa·s):", self.spin_mu_p_directo)
        v.addWidget(gb_reologia)
        lbl_julien_lan = QLabel("<i>Coeficientes de Julien-Lan (dependen del tipo de suelo/arcilla de la cuenca "
                                 "— calibre con ensayos de viscosímetro cuando sea posible):</i>")
        lbl_julien_lan.setWordWrap(True)
        f_reo.addRow(lbl_julien_lan)
        self.spin_alpha1_julien = QDoubleSpinBox(); self.spin_alpha1_julien.setRange(0.0001, 10); self.spin_alpha1_julien.setDecimals(4); self.spin_alpha1_julien.setValue(0.0500)
        f_reo.addRow("α1 (τy):", self.spin_alpha1_julien)
        self.spin_beta1_julien = QDoubleSpinBox(); self.spin_beta1_julien.setRange(0.1, 30); self.spin_beta1_julien.setDecimals(2); self.spin_beta1_julien.setValue(15.0)
        f_reo.addRow("β1 (τy):", self.spin_beta1_julien)
        self.spin_alpha2_julien = QDoubleSpinBox(); self.spin_alpha2_julien.setRange(0.0001, 10); self.spin_alpha2_julien.setDecimals(4); self.spin_alpha2_julien.setValue(0.0020)
        f_reo.addRow("α2 (μp):", self.spin_alpha2_julien)
        self.spin_beta2_julien = QDoubleSpinBox(); self.spin_beta2_julien.setRange(0.1, 30); self.spin_beta2_julien.setDecimals(2); self.spin_beta2_julien.setValue(10.0)
        f_reo.addRow("β2 (μp):", self.spin_beta2_julien)

        gb_geom = QGroupBox("3. Caudal, geometría y parámetros de cálculo")
        f_geom = QFormLayout(gb_geom)
        f_geom.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.spin_q_liquido_flujo = QDoubleSpinBox(); self.spin_q_liquido_flujo.setRange(0.01, 20000); self.spin_q_liquido_flujo.setDecimals(2); self.spin_q_liquido_flujo.setValue(30.0)
        f_geom.addRow("Caudal líquido de diseño Q (m³/s):", self.spin_q_liquido_flujo)
        self.spin_b_flujo = QDoubleSpinBox(); self.spin_b_flujo.setRange(0.5, 500); self.spin_b_flujo.setDecimals(2); self.spin_b_flujo.setValue(20.0)
        f_geom.addRow("Ancho del canal b (m, sección rectangular equivalente):", self.spin_b_flujo)
        self.spin_s_flujo = QDoubleSpinBox(); self.spin_s_flujo.setRange(0.001, 0.9); self.spin_s_flujo.setDecimals(4); self.spin_s_flujo.setValue(0.0300)
        f_geom.addRow("Pendiente del cauce S (m/m):", self.spin_s_flujo)
        self.spin_n_td_flujo = QDoubleSpinBox(); self.spin_n_td_flujo.setRange(0.001, 0.5); self.spin_n_td_flujo.setDecimals(4); self.spin_n_td_flujo.setValue(0.0500)
        f_geom.addRow("n_td — rugosidad turbulento-dispersiva (O'Brien-Julien):", self.spin_n_td_flujo)
        self.spin_d_flujo = QDoubleSpinBox(); self.spin_d_flujo.setRange(0.1, 2000); self.spin_d_flujo.setDecimals(1); self.spin_d_flujo.setValue(50.0)
        f_geom.addRow("Diámetro medio de partículas gruesas d (mm, Takahashi):", self.spin_d_flujo)
        self.spin_cmax_flujo = QDoubleSpinBox(); self.spin_cmax_flujo.setRange(0.4, 0.75); self.spin_cmax_flujo.setDecimals(3); self.spin_cmax_flujo.setValue(0.650)
        f_geom.addRow("Cmax — concentración máxima de empaquetamiento:", self.spin_cmax_flujo)
        self.spin_ai_flujo = QDoubleSpinBox(); self.spin_ai_flujo.setRange(0.001, 1.0); self.spin_ai_flujo.setDecimals(4); self.spin_ai_flujo.setValue(0.0200)
        f_geom.addRow("a_i — constante empírica del lecho (Takahashi):", self.spin_ai_flujo)
        v.addWidget(gb_geom)

        gb_metodos = QGroupBox("4. Métodos a calcular")
        h_met = QHBoxLayout(gb_metodos)
        self.chk_obrien_julien = QCheckBox("O'Brien y Julien (resistencia general)"); self.chk_obrien_julien.setChecked(True)
        self.chk_takahashi = QCheckBox("Takahashi (velocidad crítica de detritos)"); self.chk_takahashi.setChecked(True)
        h_met.addWidget(self.chk_obrien_julien)
        h_met.addWidget(self.chk_takahashi)
        v.addWidget(gb_metodos)

        btn_calcular_flujo = QPushButton("Calcular flujo hiperconcentrado/lodos/detritos")
        btn_calcular_flujo.clicked.connect(self._on_calcular_flujo_hiperconcentrado)
        v.addWidget(btn_calcular_flujo)

        gb_resultados = QGroupBox("5. Resultados")
        v_r = QVBoxLayout(gb_resultados)
        self.tabla_resultados_flujo = QTableWidget(0, 5)
        self.tabla_resultados_flujo.setHorizontalHeaderLabels(
            ["Método", "Tirante h (m)", "Velocidad V (m/s)", "Froude", "Observación"])
        # "Observación" trae texto explicativo de longitud variable; en
        # Stretch para que no empuje la tabla más allá del ancho de la
        # ventana.
        aplicar_columna_elastica(self.tabla_resultados_flujo, indice_columna_larga=4)
        self.tabla_resultados_flujo.setMinimumHeight(150)
        v_r.addWidget(self.tabla_resultados_flujo)

        self.canvas_reologia_flujo = DebrisFlowCanvas(width=7.2, height=4.4)
        v_r.addWidget(self.canvas_reologia_flujo)
        self.canvas_comparacion_flujo = DebrisFlowCanvas(width=7.2, height=4.8)
        v_r.addWidget(self.canvas_comparacion_flujo)
        v.addWidget(gb_resultados)

        v.addWidget(QLabel("<b>Cuadro resumen final — mejor propuesta:</b>"))
        self.texto_resumen_flujo = QTextBrowser()
        self.texto_resumen_flujo.setMinimumHeight(150)
        v.addWidget(self.texto_resumen_flujo)

        self._agregar_pestaña_con_scroll(tab, "13. Flujos Hiperconcentrados/Lodos/Detritos")

    def _on_clasificar_flujo(self):
        cv = self.spin_cv_flujo.value() / 100.0
        try:
            clasificacion = debris_flow.clasificar_flujo(cv)
            self.canvas_clasificacion_flujo.plot_clasificacion(cv, clasificacion)
        except debris_flow.DebrisFlowError as e:
            QMessageBox.warning(self, "No se pudo clasificar", str(e))

    def _on_calcular_flujo_hiperconcentrado(self):
        cv = self.spin_cv_flujo.value() / 100.0
        gamma_s = self.spin_gamma_s_flujo.value()
        gamma_w = self.spin_gamma_w_flujo.value()
        try:
            clasificacion = debris_flow.clasificar_flujo(cv)
            gamma_m = debris_flow.peso_especifico_mezcla(cv, gamma_w, gamma_s)
            bulking = debris_flow.caudal_mezcla(self.spin_q_liquido_flujo.value(), cv)
            q_mezcla = bulking["Q_mezcla_m3s"]

            if self.combo_modo_reologia.currentIndex() == 0:
                tau_y = self.spin_tau_y_directo.value()
                mu_p = self.spin_mu_p_directo.value()
            else:
                reologia = debris_flow.reologia_bingham_empirica(
                    cv, self.spin_alpha1_julien.value(), self.spin_beta1_julien.value(),
                    self.spin_alpha2_julien.value(), self.spin_beta2_julien.value())
                tau_y, mu_p = reologia["tau_y_Pa"], reologia["mu_p_Pa_s"]

            resultados = {}
            filas = []
            if self.chk_obrien_julien.isChecked():
                try:
                    r = debris_flow.resolver_tirante_obrien_julien(
                        q_mezcla, self.spin_b_flujo.value(), self.spin_s_flujo.value(),
                        tau_y, mu_p, self.spin_n_td_flujo.value(), gamma_m)
                    fr = debris_flow.numero_froude(r["V_m_s"], r["h_m"])
                    r["Froude"] = fr
                    resultados["O'Brien y Julien"] = r
                    filas.append(("O'Brien y Julien", r["h_m"], r["V_m_s"], fr,
                                  f"Sf verificado={r['Sf']:.4f}"))
                except debris_flow.DebrisFlowError as e:
                    filas.append(("O'Brien y Julien", None, None, None, f"Error: {e}"))
            if self.chk_takahashi.isChecked():
                try:
                    theta_grados = math.degrees(math.atan(self.spin_s_flujo.value()))
                    r = debris_flow.resolver_tirante_takahashi(
                        q_mezcla, self.spin_b_flujo.value(), self.spin_d_flujo.value(), cv,
                        theta_grados, self.spin_cmax_flujo.value(), self.spin_ai_flujo.value())
                    fr = debris_flow.numero_froude(r["V_m_s"], r["h_m"])
                    r["Froude"] = fr
                    resultados["Takahashi"] = r
                    filas.append(("Takahashi", r["h_m"], r["V_m_s"], fr,
                                  f"λ={r['lambda_concentracion_lineal']:.2f}"))
                except debris_flow.DebrisFlowError as e:
                    filas.append(("Takahashi", None, None, None, f"Error: {e}"))

            self.tabla_resultados_flujo.setRowCount(0)
            for metodo, h, vel, fr, obs in filas:
                fila = self.tabla_resultados_flujo.rowCount()
                self.tabla_resultados_flujo.insertRow(fila)
                valores = [metodo, f"{h:.3f}" if h is not None else "—",
                          f"{vel:.3f}" if vel is not None else "—",
                          f"{fr:.3f}" if fr is not None else "—", obs]
                for j, val in enumerate(valores):
                    self.tabla_resultados_flujo.setItem(fila, j, QTableWidgetItem(val))

            self.canvas_clasificacion_flujo.plot_clasificacion(cv, clasificacion)
            self.canvas_reologia_flujo.plot_reologia_bingham(tau_y, mu_p)
            if resultados:
                nombres = list(resultados.keys())
                tirantes = [resultados[n]["h_m"] for n in nombres]
                velocidades = [resultados[n]["V_m_s"] for n in nombres]
                mejor = debris_flow.seleccionar_mejor_propuesta(clasificacion, resultados)
                self.canvas_comparacion_flujo.plot_comparacion_metodos(
                    nombres, tirantes, velocidades, metodo_recomendado=mejor.get("metodo_recomendado"))
            else:
                mejor = {}

            self.resultado_flujo_hiperconcentrado = {
                "cv": cv, "clasificacion": clasificacion, "gamma_m": gamma_m, "bulking": bulking,
                "tau_y": tau_y, "mu_p": mu_p, "resultados": resultados, "mejor": mejor,
            }
            self._actualizar_texto_resumen_flujo()
        except debris_flow.DebrisFlowError as e:
            QMessageBox.critical(self, "Error en el cálculo", str(e))

    def _actualizar_texto_resumen_flujo(self):
        r = self.resultado_flujo_hiperconcentrado
        if not r:
            return
        html = "<h3>Cuadro resumen final — Flujo hiperconcentrado/lodos/detritos</h3>"
        html += (f"<p>Clasificación: <b>{r['clasificacion']}</b> (Cv = {r['cv']*100:.1f}%)<br>"
                 f"γ mezcla = {r['gamma_m']:.0f} N/m³<br>"
                 f"τy = {r['tau_y']:.2f} Pa, μp = {r['mu_p']:.4f} Pa·s<br>"
                 f"Factor de amplificación BF = {r['bulking']['BF']:.2f} → "
                 f"Q mezcla de diseño = <b>{r['bulking']['Q_mezcla_m3s']:.2f} m³/s</b></p>")
        html += "<table border='1' cellpadding='4' cellspacing='0'><tr><th>Método</th><th>h (m)</th><th>V (m/s)</th><th>Froude</th></tr>"
        for nombre, res in r["resultados"].items():
            html += f"<tr><td>{nombre}</td><td>{res['h_m']:.2f}</td><td>{res['V_m_s']:.2f}</td><td>{res['Froude']:.2f}</td></tr>"
        html += "</table>"
        mejor = r.get("mejor")
        if mejor:
            html += (f"<p><b>Mejor propuesta recomendada: {mejor['metodo_recomendado']}</b><br>"
                     f"{mejor['motivo']}</p>")
        html += ("<p style='color:#666666'>NOTA: cálculo de validación preliminar. Para el diseño "
                 "definitivo de obras de protección, use modelación numérica 2D (FLO-2D, HEC-RAS ≥6.0, "
                 "RAMMS) calibrada con el estudio geotécnico y granulométrico de la cuenca.</p>")
        self.texto_resumen_flujo.setHtml(html)

    # ------------------------------------------------------------------
    # TAB 14: Cambio Climático - Escenarios. Ver core/climate_change.py.
    # ------------------------------------------------------------------
    def _build_tab_cambio_climatico(self):
        tab = QWidget()
        v = QVBoxLayout(tab)
        _lbl_auto_33 = QLabel(
            "<b>Cambio Climático - Escenarios</b> — marco CMIP6 (SSP-RCP, experimentos DECK) como "
            "referencia, y dos herramientas de cálculo: aplicación de deltas de cambio climático a su "
            "serie histórica (delta-change, a partir de anomalías que usted ya obtuvo de un informe "
            "CMIP6/CORDEX) y corrección de sesgo/escalamiento estadístico (bias correction) de series de "
            "un modelo climático contra sus observaciones locales."
        )
        _lbl_auto_33.setWordWrap(True)
        v.addWidget(_lbl_auto_33)

        gb_marco = QGroupBox("0. Marco de referencia CMIP6 (informativo)")
        v_marco = QVBoxLayout(gb_marco)
        self.texto_marco_cmip6 = QTextBrowser()
        self.texto_marco_cmip6.setMinimumHeight(160)
        html_marco = "<b>Escenarios SSP-RCP (forzamiento radiativo hacia 2100):</b><ul>"
        for nombre, info in climate_change.ESCENARIOS_SSP_RCP.items():
            html_marco += f"<li><b>{nombre}</b> ({info['forzamiento_w_m2_2100']} W/m²): {info['descripcion']}</li>"
        html_marco += "</ul><b>Experimentos núcleo DECK:</b><ul>"
        for nombre, desc in climate_change.EXPERIMENTOS_DECK.items():
            html_marco += f"<li><b>{nombre}</b>: {desc}</li>"
        html_marco += ("</ul><p style='color:#666666'>Este módulo no descarga NetCDF de ESGF; aplica los "
                       "deltas/series que usted ya obtuvo de un informe CMIP6/CORDEX o del IPCC WGI "
                       "Interactive Atlas a su propia serie observada.</p>")
        self.texto_marco_cmip6.setHtml(html_marco)
        v_marco.addWidget(self.texto_marco_cmip6)
        v.addWidget(gb_marco)

        # ---------------- Delta-change ----------------
        gb_delta = QGroupBox("1. Método Delta-Change — aplicar anomalías CMIP6 a su serie base")
        v_delta = QVBoxLayout(gb_delta)
        _lbl_auto_34 = QLabel(
            "Pegue la precipitación (mm) y temperatura (°C) mensual BASE (histórica/observada), y las "
            "anomalías (delta) de cada escenario: precipitación en % de cambio, temperatura en °C de "
            "cambio absoluto. Deje en blanco los escenarios que no vaya a usar."
        )
        _lbl_auto_34.setWordWrap(True)
        v_delta.addWidget(_lbl_auto_34)
        v_delta.addWidget(QLabel("<b>Precipitación</b> — P base (mm) y Δ% por escenario:"))
        self.tabla_delta_precipitacion = TablaPegable(12, 6)
        self.tabla_delta_precipitacion.setHorizontalHeaderLabels(
            ["Mes", "P base (mm)", "Δ% SSP1-2.6", "Δ% SSP2-4.5", "Δ% SSP3-7.0", "Δ% SSP5-8.5"])
        for i, mes in enumerate(climate_change.MESES):
            self.tabla_delta_precipitacion.setItem(i, 0, QTableWidgetItem(mes))
        self.tabla_delta_precipitacion.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla_delta_precipitacion.setMinimumHeight(200)
        v_delta.addWidget(self.tabla_delta_precipitacion)

        v_delta.addWidget(QLabel("<b>Temperatura</b> — T base (°C) y ΔT (°C) por escenario:"))
        self.tabla_delta_temperatura = TablaPegable(12, 6)
        self.tabla_delta_temperatura.setHorizontalHeaderLabels(
            ["Mes", "T base (°C)", "ΔT SSP1-2.6", "ΔT SSP2-4.5", "ΔT SSP3-7.0", "ΔT SSP5-8.5"])
        for i, mes in enumerate(climate_change.MESES):
            self.tabla_delta_temperatura.setItem(i, 0, QTableWidgetItem(mes))
        self.tabla_delta_temperatura.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla_delta_temperatura.setMinimumHeight(200)
        v_delta.addWidget(self.tabla_delta_temperatura)

        btn_aplicar_delta = QPushButton("Aplicar Delta-Change a los 4 escenarios")
        btn_aplicar_delta.clicked.connect(self._on_aplicar_delta_change)
        v_delta.addWidget(btn_aplicar_delta)

        self.canvas_regimen_precip_cc = ClimateCanvas(width=7.4, height=4.6)
        v_delta.addWidget(self.canvas_regimen_precip_cc)
        self.canvas_regimen_temp_cc = ClimateCanvas(width=7.4, height=4.6)
        v_delta.addWidget(self.canvas_regimen_temp_cc)

        self.canvas_cambio_precip_cc = ClimateCanvas(width=7.4, height=4.4)
        v_delta.addWidget(self.canvas_cambio_precip_cc)
        self.canvas_cambio_temp_cc = ClimateCanvas(width=7.4, height=4.4)
        v_delta.addWidget(self.canvas_cambio_temp_cc)
        v.addWidget(gb_delta)

        # ---------------- Corrección de sesgo ----------------
        gb_sesgo = QGroupBox("2. Corrección de sesgo / Escalamiento estadístico (bias correction)")
        v_sesgo = QVBoxLayout(gb_sesgo)
        _lbl_auto_35 = QLabel(
            "Pegue 3 series mensuales de precipitación: Observado (histórico), Modelo crudo (histórico, "
            "del GCM/RCM sin corregir) y Modelo futuro (crudo, a corregir). El método corrige el sesgo "
            "sistemático del modelo contra sus observaciones locales."
        )
        _lbl_auto_35.setWordWrap(True)
        v_sesgo.addWidget(_lbl_auto_35)
        self.tabla_correccion_sesgo = TablaPegable(12, 4)
        self.tabla_correccion_sesgo.setHorizontalHeaderLabels(
            ["Mes", "Observado histórico", "Modelo histórico (crudo)", "Modelo futuro (crudo)"])
        for i, mes in enumerate(climate_change.MESES):
            self.tabla_correccion_sesgo.setItem(i, 0, QTableWidgetItem(mes))
        self.tabla_correccion_sesgo.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla_correccion_sesgo.setMinimumHeight(200)
        v_sesgo.addWidget(self.tabla_correccion_sesgo)

        h_metodo_sesgo = QHBoxLayout()
        h_metodo_sesgo.addWidget(QLabel("Variable:"))
        self.combo_variable_sesgo = QComboBox()
        self.combo_variable_sesgo.addItems(["Precipitación (corrección multiplicativa)",
                                             "Temperatura (corrección aditiva)"])
        h_metodo_sesgo.addWidget(self.combo_variable_sesgo)
        btn_escalamiento_lineal = QPushButton("Aplicar escalamiento lineal")
        btn_escalamiento_lineal.clicked.connect(lambda: self._on_corregir_sesgo("lineal"))
        h_metodo_sesgo.addWidget(btn_escalamiento_lineal)
        btn_mapeo_cuantiles = QPushButton("Aplicar mapeo de cuantiles")
        btn_mapeo_cuantiles.clicked.connect(lambda: self._on_corregir_sesgo("cuantiles"))
        h_metodo_sesgo.addWidget(btn_mapeo_cuantiles)
        v_sesgo.addLayout(h_metodo_sesgo)

        self.canvas_correccion_sesgo_cc = ClimateCanvas(width=7.4, height=4.8)
        v_sesgo.addWidget(self.canvas_correccion_sesgo_cc)
        v.addWidget(gb_sesgo)

        v.addWidget(QLabel("<b>Cuadro resumen final:</b>"))
        self.texto_resumen_cc = QTextBrowser()
        self.texto_resumen_cc.setMinimumHeight(160)
        v.addWidget(self.texto_resumen_cc)

        self._agregar_pestaña_con_scroll(tab, "14. Cambio Climático - Escenarios")

    def _leer_columna_tabla(self, tabla, columna, n_filas=12):
        valores = []
        for i in range(n_filas):
            item = tabla.item(i, columna)
            texto = item.text().strip() if item else ""
            try:
                valores.append(float(texto.replace(",", ".")) if texto else None)
            except ValueError:
                valores.append(None)
        return valores

    def _on_aplicar_delta_change(self):
        p_base = self._leer_columna_tabla(self.tabla_delta_precipitacion, 1)
        t_base = self._leer_columna_tabla(self.tabla_delta_temperatura, 1)
        if any(x is None for x in p_base) or any(x is None for x in t_base):
            QMessageBox.warning(self, "Faltan datos", "Complete los 12 meses de P base y T base.")
            return
        nombres_escenarios = climate_change.listar_escenarios()
        series_p = {"Base (histórico)": p_base}
        series_t = {"Base (histórico)": t_base}
        resumen_p, resumen_t = {}, {}
        for i, nombre in enumerate(nombres_escenarios):
            col = 2 + i
            deltas_p = self._leer_columna_tabla(self.tabla_delta_precipitacion, col)
            deltas_t = self._leer_columna_tabla(self.tabla_delta_temperatura, col)
            if any(d is None for d in deltas_p) or any(d is None for d in deltas_t):
                continue
            p_fut = climate_change.aplicar_delta_precipitacion(p_base, deltas_p)
            t_fut = climate_change.aplicar_delta_temperatura(t_base, deltas_t)
            series_p[nombre] = p_fut
            series_t[nombre] = t_fut
            resumen_p[nombre] = climate_change.resumen_cambio_anual(p_base, p_fut, es_precipitacion=True)
            resumen_t[nombre] = climate_change.resumen_cambio_anual(t_base, t_fut, es_precipitacion=False)

        if len(series_p) <= 1:
            QMessageBox.warning(self, "Faltan escenarios",
                                 "Complete al menos un escenario (columnas de Δ%/ΔT) para calcular.")
            return

        self.canvas_regimen_precip_cc.plot_regimen_mensual(series_p, variable="Precipitación", unidad="mm")
        self.canvas_regimen_temp_cc.plot_regimen_mensual(series_t, variable="Temperatura", unidad="°C")

        nombres_calc = [n for n in resumen_p.keys()]
        cambios_p = [resumen_p[n]["cambio_pct"] for n in nombres_calc]
        cambios_t = [resumen_t[n]["cambio_absoluto"] for n in nombres_calc]
        self.canvas_cambio_precip_cc.plot_cambio_anual(nombres_calc, cambios_p, variable="Precipitación", unidad="%")
        self.canvas_cambio_temp_cc.plot_cambio_anual(nombres_calc, cambios_t, variable="Temperatura", unidad="°C")

        self.resultado_cambio_climatico = {"series_p": series_p, "series_t": series_t,
                                            "resumen_p": resumen_p, "resumen_t": resumen_t}
        self._actualizar_texto_resumen_cc()

    def _on_corregir_sesgo(self, metodo: str):
        obs = self._leer_columna_tabla(self.tabla_correccion_sesgo, 1)
        mod_hist = self._leer_columna_tabla(self.tabla_correccion_sesgo, 2)
        mod_fut = self._leer_columna_tabla(self.tabla_correccion_sesgo, 3)
        if any(x is None for x in obs) or any(x is None for x in mod_hist) or any(x is None for x in mod_fut):
            QMessageBox.warning(self, "Faltan datos", "Complete las 3 series de 12 meses.")
            return
        es_precip = self.combo_variable_sesgo.currentIndex() == 0
        variable = "Precipitación" if es_precip else "Temperatura"
        unidad = "mm" if es_precip else "°C"
        try:
            if metodo == "lineal":
                if es_precip:
                    res = climate_change.escalamiento_lineal_precipitacion(obs, mod_hist, mod_fut)
                else:
                    res = climate_change.escalamiento_lineal_temperatura(obs, mod_hist, mod_fut)
                serie_corregida = res["serie_corregida"]
            else:
                res = climate_change.mapeo_cuantiles(obs, mod_hist, mod_fut)
                serie_corregida = res["serie_corregida"]
            self.canvas_correccion_sesgo_cc.plot_correccion_sesgo(
                climate_change.MESES, obs, mod_fut, serie_corregida, variable=variable, unidad=unidad)
            self.resultado_correccion_sesgo = {"metodo": metodo, "variable": variable,
                                                "obs": obs, "modelo_futuro_crudo": mod_fut,
                                                "serie_corregida": serie_corregida}
            self._actualizar_texto_resumen_cc()
        except climate_change.ClimateChangeError as e:
            QMessageBox.warning(self, "No se pudo corregir el sesgo", str(e))

    def _actualizar_texto_resumen_cc(self):
        html = "<h3>Cuadro resumen final — Cambio Climático</h3>"
        if self.resultado_cambio_climatico:
            html += "<p><b>Delta-Change:</b></p><table border='1' cellpadding='4' cellspacing='0'>"
            html += "<tr><th>Escenario</th><th>Δ Precipitación anual</th><th>ΔT anual</th></tr>"
            rp = self.resultado_cambio_climatico["resumen_p"]
            rt = self.resultado_cambio_climatico["resumen_t"]
            for nombre in rp:
                html += (f"<tr><td>{nombre}</td><td>{rp[nombre]['cambio_pct']:+.1f}%</td>"
                         f"<td>{rt[nombre]['cambio_absoluto']:+.2f} °C</td></tr>")
            html += "</table>"
        if self.resultado_correccion_sesgo:
            r = self.resultado_correccion_sesgo
            html += (f"<p><b>Corrección de sesgo ({r['metodo']}, {r['variable']}):</b> serie corregida "
                     f"lista para usar como forzante climática futura del modelo hidrológico "
                     f"(pestañas de Caudales Medios/Mínimos).</p>")
        if not self.resultado_cambio_climatico and not self.resultado_correccion_sesgo:
            html += "<p>Aún no se ha calculado ningún escenario.</p>"
        html += ("<p style='color:#666666'>NOTA: los deltas y series de modelo deben provenir de un "
                 "informe CMIP6/CORDEX o del IPCC WGI Interactive Atlas para la zona de estudio; este "
                 "módulo los aplica a su serie observada, no los genera.</p>")
        self.texto_resumen_cc.setHtml(html)

    # ------------------------------------------------------------------
    # TAB 15: Caudales Medios (Qm). Ver core/mean_flow_models.py y
    # core/etp_methods.py. Modelos fieles al Manual Técnico de RS MINERVE
    # (CREALP/HydroCosmos, v2.25): Lutz Scholz (simplificado), GR2M, GR4J,
    # HBV, SAC-SMA, Snow-SD, Runoff (SWMM), GSM y SOCONT.
    # ------------------------------------------------------------------
    def _build_tab_caudales_medios(self):
        tab = QWidget()
        v = QVBoxLayout(tab)
        _lbl_auto_36 = QLabel(
            "<b>Caudales Medios (Qm)</b> — modelos precipitación-escorrentía fieles al Manual Técnico "
            "de RS MINERVE (CREALP/HydroCosmos, v2.25): Lutz Scholz (simplificado), GR2M, GR4J, HBV, "
            "SAC-SMA, Snow-SD, <b>Runoff (SWMM)</b>, <b>GSM</b> (nieve+glaciar) y <b>SOCONT</b> "
            "(nieve+GR3+SWMM). El paso de tiempo (mensual/diario/otro) y la variable de entrada "
            "(P, T, ETP) son configurables; la ETP puede pegarse directamente o calcularse por Turc, "
            "McGuinness-Bordne, Oudin o un valor uniforme. Calibrador genérico (Nelder-Mead) contra "
            "aforos, con los 10 indicadores de desempeño del Capítulo 3 del manual."
        )
        _lbl_auto_36.setWordWrap(True)
        v.addWidget(_lbl_auto_36)

        gb_modelo = QGroupBox("1. Selección del modelo y parámetros")
        v_modelo = QVBoxLayout(gb_modelo)
        h_sel = QHBoxLayout()
        h_sel.addWidget(QLabel("Modelo:"))
        self.combo_modelo_qm = QComboBox()
        self.combo_modelo_qm.addItems(list(mean_flow_models.MODELOS_DISPONIBLES.keys()))
        self.combo_modelo_qm.currentTextChanged.connect(self._on_cambiar_modelo_qm)
        h_sel.addWidget(self.combo_modelo_qm)
        v_modelo.addLayout(h_sel)

        self.tabla_parametros_qm = QTableWidget(0, 4)
        self.tabla_parametros_qm.setHorizontalHeaderLabels(["Parámetro", "Valor inicial", "Mínimo (calibración)", "Máximo (calibración)"])
        # "Parámetro" trae nombres de coeficientes de modelo de longitud
        # variable (distintos entre Lutz Scholz, GR2M, GR4J, HBV, SAC-SMA,
        # SNOW-SD...); en Stretch para no forzar scroll horizontal en la
        # pestaña cuando el modelo elegido tiene nombres más largos.
        aplicar_columna_elastica(self.tabla_parametros_qm, indice_columna_larga=0)
        self.tabla_parametros_qm.horizontalHeader().setStretchLastSection(False)
        self.tabla_parametros_qm.setMinimumHeight(220)
        v_modelo.addWidget(self.tabla_parametros_qm)
        v.addWidget(gb_modelo)

        # ---------------- Serie de entrada ----------------
        gb_series = QGroupBox("2. Serie de entrada (pegar tabla tipo Excel)")
        v_series = QVBoxLayout(gb_series)
        _lbl_auto_37 = QLabel(
            "Columnas: Año, Mes (1-12), Día (opcional, solo para paso diario — deje 15 para mensual), "
            "P (mm/paso), T media (°C, requerida por modelos con nieve: HBV, Snow-SD, GSM, SOCONT), "
            "ETP (mm/paso — puede pegarla o calcularla abajo), Q obs (m³/s, opcional, para calibrar)."
        )
        _lbl_auto_37.setWordWrap(True)
        v_series.addWidget(_lbl_auto_37)
        self.tabla_series_qm = TablaPegable(60, 7)
        self.tabla_series_qm.setHorizontalHeaderLabels(
            ["Año", "Mes", "Día", "P (mm)", "T media (°C)", "ETP (mm)", "Q obs (m³/s)"])
        self.tabla_series_qm.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla_series_qm.setMinimumHeight(260)
        v_series.addWidget(self.tabla_series_qm)

        f_geom_qm = QFormLayout()
        f_geom_qm.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.spin_area_qm = QDoubleSpinBox(); self.spin_area_qm.setRange(0.01, 500000); self.spin_area_qm.setDecimals(2); self.spin_area_qm.setValue(250.0)
        f_geom_qm.addRow("Área de la cuenca (km²) — usada por los modelos en lámina (mm):", self.spin_area_qm)
        self.spin_duracion_paso_qm = QDoubleSpinBox(); self.spin_duracion_paso_qm.setRange(1, 366); self.spin_duracion_paso_qm.setDecimals(2); self.spin_duracion_paso_qm.setValue(30.44)
        f_geom_qm.addRow("Duración de cada paso (días; 30.44=mensual, 1=diario):", self.spin_duracion_paso_qm)
        v_series.addLayout(f_geom_qm)
        v.addWidget(gb_series)

        # ---------------- Cálculo de ETP ----------------
        gb_etp = QGroupBox("3. Cálculo de ETP (opcional — Manual RS MINERVE, ec. A.9 a A.18)")
        f_etp = QFormLayout(gb_etp)
        f_etp.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.combo_metodo_etp_qm = QComboBox()
        self.combo_metodo_etp_qm.addItems([
            "Ingresar/pegar directamente en la tabla", "Turc (1955/1961)",
            "McGuinness-Bordne (1972)", "Oudin (2004)", "ETP Uniforme"])
        f_etp.addRow("Método:", self.combo_metodo_etp_qm)
        self.spin_latitud_qm = QDoubleSpinBox(); self.spin_latitud_qm.setRange(-90, 90); self.spin_latitud_qm.setDecimals(2); self.spin_latitud_qm.setValue(-13.0)
        f_etp.addRow("Latitud (°, solo Oudin):", self.spin_latitud_qm)
        self.spin_rg_qm = QDoubleSpinBox(); self.spin_rg_qm.setRange(0.5, 10.0); self.spin_rg_qm.setDecimals(2); self.spin_rg_qm.setValue(5.0)
        f_etp.addRow("Rg — radiación global (kWh/m²/día, constante; solo Turc/McGuinness — "
                     "RS MINERVE la obtiene de la malla NASA SSE, aquí se ingresa manualmente):", self.spin_rg_qm)
        self.spin_valor_uniforme_etp_qm = QDoubleSpinBox(); self.spin_valor_uniforme_etp_qm.setRange(0, 20); self.spin_valor_uniforme_etp_qm.setDecimals(2); self.spin_valor_uniforme_etp_qm.setValue(3.0)
        f_etp.addRow("Valor uniforme (mm/día, solo ETP Uniforme):", self.spin_valor_uniforme_etp_qm)
        self.spin_coeff_etp_qm = QDoubleSpinBox(); self.spin_coeff_etp_qm.setRange(0.5, 2.0); self.spin_coeff_etp_qm.setDecimals(2); self.spin_coeff_etp_qm.setValue(1.0)
        f_etp.addRow("CoeffETP — coeficiente corrector multiplicativo:", self.spin_coeff_etp_qm)
        btn_calcular_etp_qm = QPushButton("Calcular columna ETP con el método seleccionado")
        btn_calcular_etp_qm.clicked.connect(self._on_calcular_etp_qm)
        limitar_ancho_boton(btn_calcular_etp_qm)
        f_etp.addRow(btn_calcular_etp_qm)
        v.addWidget(gb_etp)

        h_calc = QHBoxLayout()
        btn_simular_qm = QPushButton("Simular con parámetros actuales")
        btn_simular_qm.clicked.connect(lambda: self._on_simular_qm(calibrar=False))
        h_calc.addWidget(btn_simular_qm)
        btn_calibrar_qm = QPushButton("Calibrar con aforos (Nelder-Mead) y simular")
        btn_calibrar_qm.clicked.connect(lambda: self._on_simular_qm(calibrar=True))
        h_calc.addWidget(btn_calibrar_qm)
        v.addLayout(h_calc)

        gb_resultados = QGroupBox("4. Resultados")
        v_r = QVBoxLayout(gb_resultados)
        self.canvas_hidrograma_qm = MeanFlowCanvas(width=7.6, height=4.6)
        v_r.addWidget(self.canvas_hidrograma_qm)
        self.canvas_dispersion_qm = MeanFlowCanvas(width=7.4, height=5.0)
        v_r.addWidget(self.canvas_dispersion_qm)
        self.canvas_calibracion_parametros_qm = MeanFlowCanvas(width=7.4, height=5.0)
        v_r.addWidget(self.canvas_calibracion_parametros_qm)
        v.addWidget(gb_resultados)

        v.addWidget(QLabel("<b>Cuadro resumen final:</b>"))
        self.texto_resumen_qm = QTextBrowser()
        self.texto_resumen_qm.setMinimumHeight(220)
        v.addWidget(self.texto_resumen_qm)

        self._on_cambiar_modelo_qm(self.combo_modelo_qm.currentText())
        self._agregar_pestaña_con_scroll(tab, "15. Caudales Medios (Qm)")

    def _on_cambiar_modelo_qm(self, nombre_modelo: str):
        info = mean_flow_models.MODELOS_DISPONIBLES.get(nombre_modelo)
        if not info:
            return
        params = info["parametros"]
        self.tabla_parametros_qm.setRowCount(len(params))
        for i, (nombre, valor, minimo, maximo) in enumerate(params):
            self.tabla_parametros_qm.setItem(i, 0, QTableWidgetItem(nombre))
            self.tabla_parametros_qm.setItem(i, 1, QTableWidgetItem(f"{valor:g}"))
            self.tabla_parametros_qm.setItem(i, 2, QTableWidgetItem(f"{minimo:g}"))
            self.tabla_parametros_qm.setItem(i, 3, QTableWidgetItem(f"{maximo:g}"))

    def _leer_parametros_tabla_qm(self):
        n = self.tabla_parametros_qm.rowCount()
        nombres, valores, minimos, maximos = [], [], [], []
        for i in range(n):
            nombres.append(self.tabla_parametros_qm.item(i, 0).text())
            valores.append(float(self.tabla_parametros_qm.item(i, 1).text().replace(",", ".")))
            minimos.append(float(self.tabla_parametros_qm.item(i, 2).text().replace(",", ".")))
            maximos.append(float(self.tabla_parametros_qm.item(i, 3).text().replace(",", ".")))
        return nombres, valores, minimos, maximos

    def _leer_serie_qm(self):
        n = self.tabla_series_qm.rowCount()
        anios, meses, dias, p, t_media, etp, q_obs = [], [], [], [], [], [], []
        for i in range(n):
            item_precip = self.tabla_series_qm.item(i, 3)
            if not item_precip or not item_precip.text().strip():
                continue

            def _leer(col, entero=False):
                item = self.tabla_series_qm.item(i, col)
                texto = item.text().strip() if item else ""
                if not texto:
                    return None
                valor = float(texto.replace(",", "."))
                return int(valor) if entero else valor

            anios.append(_leer(0, entero=True) or 2000)
            meses.append(_leer(1, entero=True) or 1)
            dias.append(_leer(2, entero=True) or 15)
            p.append(_leer(3))
            t_media.append(_leer(4))
            etp.append(_leer(5))
            q_obs.append(_leer(6))
        return anios, meses, dias, p, t_media, etp, q_obs

    def _on_calcular_etp_qm(self):
        anios, meses, dias, p, t_media, etp_actual, q_obs = self._leer_serie_qm()
        if not p:
            QMessageBox.warning(self, "Faltan datos", "Ingrese primero Año, Mes y P en la tabla de la serie.")
            return
        if any(t is None for t in t_media):
            QMessageBox.warning(self, "Falta temperatura",
                                 "Los métodos de ETP requieren la columna T media completa.")
            return
        metodo_idx = self.combo_metodo_etp_qm.currentIndex()
        if metodo_idx == 0:
            QMessageBox.information(self, "Método directo",
                                     "Seleccione Turc, McGuinness-Bordne, Oudin o ETP Uniforme para calcular; "
                                     "con 'Ingresar/pegar directamente' complete la columna ETP a mano.")
            return
        coeff = self.spin_coeff_etp_qm.value()
        duracion = self.spin_duracion_paso_qm.value()
        etp_mm_paso = []
        for anio, mes, dia, t in zip(anios, meses, dias, t_media):
            if metodo_idx == 1:  # Turc (mm/mes directo)
                valor = etp_methods.turc(t, self.spin_rg_qm.value(), mes, coeff)
                if abs(duracion - 30.44) > 5:  # si el paso no es ~mensual, prorratea por día
                    valor = valor / 30.44 * duracion
            elif metodo_idx == 2:  # McGuinness-Bordne (mm/día)
                valor = etp_methods.mcguinness_bordne(t, self.spin_rg_qm.value(), coeff) * duracion
            elif metodo_idx == 3:  # Oudin (mm/día)
                valor = etp_methods.oudin(t, self.spin_latitud_qm.value(), anio, mes, dia, coeff) * duracion
            else:  # Uniforme (mm/día)
                valor = etp_methods.etp_uniforme(self.spin_valor_uniforme_etp_qm.value(), coeff) * duracion
            etp_mm_paso.append(valor)
        for i, valor in enumerate(etp_mm_paso):
            self.tabla_series_qm.setItem(i, 5, QTableWidgetItem(f"{valor:.2f}"))
        QMessageBox.information(self, "ETP calculada", f"Se calculó la ETP para {len(etp_mm_paso)} pasos.")

    def _on_simular_qm(self, calibrar: bool):
        nombre_modelo = self.combo_modelo_qm.currentText()
        info = mean_flow_models.MODELOS_DISPONIBLES[nombre_modelo]
        try:
            nombres_param, valores, minimos, maximos = self._leer_parametros_tabla_qm()
            anios, meses, dias, p, t_media, etp, q_obs = self._leer_serie_qm()
            if len(p) < 3:
                QMessageBox.warning(self, "Faltan datos", "Ingrese al menos 3 pasos de P.")
                return
            area = self.spin_area_qm.value()
            duracion = self.spin_duracion_paso_qm.value()
            requiere_t = info["requiere_temperatura"]
            requiere_fecha = info["requiere_fecha"]
            salida_directa_m3s = info["salida_m3s_directo"]
            if requiere_t and any(t is None for t in t_media):
                QMessageBox.warning(self, "Falta temperatura",
                                     "Este modelo requiere la columna T media completa (todos los pasos).")
                return
            etp_completa = [e if e is not None else 0.0 for e in etp]
            t_completa = [t if t is not None else 0.0 for t in t_media]
            dias_juliano = ([etp_methods.dia_juliano(a, m, d) for a, m, d in zip(anios, meses, dias)]
                             if requiere_fecha else None)
            pasos_label = [f"{a}-{m:02d}" if d == 15 else f"{a}-{m:02d}-{d:02d}" for a, m, d in zip(anios, meses, dias)]

            def simular(params):
                return info["func"](params, p, etp_completa, t_completa, dias_juliano, duracion)

            q_obs_validos = [x for x in q_obs if x is not None]
            usar_calibracion = calibrar and len(q_obs_validos) == len(p) and len(p) > 0

            if usar_calibracion:
                def func_sim_m3s(params):
                    q = simular(params)
                    return q if salida_directa_m3s else mean_flow_models.serie_mm_a_m3s(q, area, duracion)

                resultado_cal = mean_flow_models.calibrar_nelder_mead(
                    func_sim_m3s, q_obs, x0=valores, limites=list(zip(minimos, maximos)))
                valores_calibrados = resultado_cal["parametros_calibrados"]
                for i, val in enumerate(valores_calibrados):
                    self.tabla_parametros_qm.setItem(i, 1, QTableWidgetItem(f"{val:g}"))
                q_sim_m3s = resultado_cal["q_sim"]
                metricas = resultado_cal["metricas"]
                self.canvas_calibracion_parametros_qm.plot_calibracion_parametros(
                    nombres_param, valores, valores_calibrados)
            else:
                if calibrar:
                    QMessageBox.warning(self, "Faltan aforos",
                                         "Para calibrar, complete la columna Q obs en TODOS los pasos ingresados.")
                q_bruto = simular(valores)
                q_sim_m3s = q_bruto if salida_directa_m3s else mean_flow_models.serie_mm_a_m3s(q_bruto, area, duracion)
                metricas = mean_flow_models.metricas_ajuste(q_obs_validos, q_sim_m3s) if len(q_obs_validos) == len(p) else None
                valores_calibrados = valores

            self.canvas_hidrograma_qm.plot_hidrograma(
                pasos_label, q_sim_m3s, q_obs=q_obs if len(q_obs_validos) == len(p) else None, nombre_modelo=nombre_modelo)
            if len(q_obs_validos) == len(p):
                self.canvas_dispersion_qm.plot_dispersión_obs_sim(
                    q_obs, q_sim_m3s, r2=metricas.get("Pearson") ** 2 if metricas and metricas.get("Pearson") == metricas.get("Pearson") else None,
                    nse=metricas.get("Nash") if metricas else None)

            self.resultado_simulacion_qm = {
                "modelo": nombre_modelo, "q_sim": q_sim_m3s, "q_obs": q_obs, "metricas": metricas,
                "calibrado": usar_calibracion,
                "parametros_finales": list(zip(nombres_param, valores_calibrados)),
            }
            self._actualizar_texto_resumen_qm()
        except (mean_flow_models.MeanFlowError, ValueError) as e:
            QMessageBox.critical(self, "Error en la simulación", str(e))

    def _actualizar_texto_resumen_qm(self):
        r = self.resultado_simulacion_qm
        if not r:
            return
        html = f"<h3>Cuadro resumen final — Caudales Medios ({r['modelo']})</h3>"
        html += f"<p>{'Modelo CALIBRADO contra aforos' if r['calibrado'] else 'Simulación con parámetros ingresados (sin calibrar)'}</p>"
        html += "<table border='1' cellpadding='4' cellspacing='0'><tr><th>Parámetro</th><th>Valor final</th></tr>"
        for nombre, valor in r["parametros_finales"]:
            html += f"<tr><td>{nombre}</td><td>{valor:.4g}</td></tr>"
        html += "</table>"
        if r["metricas"]:
            m = r["metricas"]
            html += ("<p><b>Indicadores de desempeño vs. aforos (Capítulo 3, Manual RS MINERVE):</b></p>"
                     "<table border='1' cellpadding='4' cellspacing='0'>"
                     "<tr><th>Nash</th><th>Nash-ln</th><th>Pearson</th><th>KGE</th><th>Bias Score</th>"
                     "<th>RRMSE</th><th>RVB</th><th>NPE</th><th>PSS</th><th>OA</th></tr>"
                     f"<tr><td>{m['Nash']:.3f}</td><td>{m['Nash_ln']:.3f}</td><td>{m['Pearson']:.3f}</td>"
                     f"<td>{m['KGE']:.3f}</td><td>{m['BiasScore']:.3f}</td><td>{m['RRMSE']:.3f}</td>"
                     f"<td>{m['RVB']:.3f}</td><td>{m['NPE']:.3f}</td><td>{m['PSS']:.3f}</td>"
                     f"<td>{m['OA']:.3f}</td></tr></table>")
        q_sim = r["q_sim"]
        html += (f"<p>Caudal medio simulado: {sum(q_sim)/len(q_sim):.3f} m³/s "
                 f"(mín {min(q_sim):.3f}, máx {max(q_sim):.3f} m³/s)</p>")
        html += ("<p style='color:#666666'>NOTA: valide siempre el modelo contra un periodo de aforos "
                 "independiente (validación) además del periodo de calibración. Turc y McGuinness-Bordne "
                 "requieren Rg (radiación global) que RS MINERVE obtiene de la malla NASA SSE; aquí se "
                 "ingresa manualmente como valor constante. PSS/OA usan por defecto el caudal medio "
                 "observado como umbral de excedencia.</p>")
        self.texto_resumen_qm.setHtml(html)

    # ------------------------------------------------------------------
    # TAB 16: Caudales Mínimos. Ver core/low_flows.py.
    # ------------------------------------------------------------------
    def _build_tab_caudales_minimos(self):
        tab = QWidget()
        v = QVBoxLayout(tab)
        _lbl_auto_38 = QLabel(
            "<b>Caudales Mínimos</b> — Curva de Duración de Caudales (persistencia, Q95), método de "
            "Tennant/Montana (caudal ecológico como % del Qma), análisis de frecuencia de mínimos "
            "(Weibull y Gumbel de mínimos) y transferencia por cuenca homóloga para cuencas sin "
            "información. El criterio conservador para no comprometer el ecosistema es adoptar el "
            "<b>mínimo</b> valor entre los métodos aplicables (a diferencia de socavación, donde se "
            "adopta el máximo)."
        )
        _lbl_auto_38.setWordWrap(True)
        v.addWidget(_lbl_auto_38)

        # ---------------- Curva de duración ----------------
        gb_cdc = QGroupBox("1. Curva de Duración de Caudales (CDC) / Persistencia")
        v_cdc = QVBoxLayout(gb_cdc)
        v_cdc.addWidget(QLabel("Pegue la serie de caudales (diarios o mensuales, una columna, mínimo 5 datos):"))
        self.tabla_caudales_cdc = TablaPegable(60, 1)
        self.tabla_caudales_cdc.setHorizontalHeaderLabels(["Caudal (m³/s)"])
        self.tabla_caudales_cdc.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla_caudales_cdc.setMinimumHeight(200)
        v_cdc.addWidget(self.tabla_caudales_cdc)
        h_cdc = QHBoxLayout()
        h_cdc.addWidget(QLabel("Percentil de persistencia a extraer (%):"))
        self.spin_percentil_cdc = QDoubleSpinBox(); self.spin_percentil_cdc.setRange(1, 99); self.spin_percentil_cdc.setDecimals(0); self.spin_percentil_cdc.setValue(95)
        h_cdc.addWidget(self.spin_percentil_cdc)
        btn_calcular_cdc = QPushButton("Calcular curva de duración y Q persistencia")
        btn_calcular_cdc.clicked.connect(self._on_calcular_cdc)
        h_cdc.addWidget(btn_calcular_cdc)
        v_cdc.addLayout(h_cdc)
        self.canvas_cdc = LowFlowCanvas(width=7.4, height=4.6)
        v_cdc.addWidget(self.canvas_cdc)
        v.addWidget(gb_cdc)

        # ---------------- Tennant ----------------
        gb_tennant = QGroupBox("2. Método de Tennant (Montana)")
        f_tennant = QFormLayout(gb_tennant)
        f_tennant.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.spin_qma_tennant = QDoubleSpinBox(); self.spin_qma_tennant.setRange(0.001, 200000); self.spin_qma_tennant.setDecimals(3); self.spin_qma_tennant.setValue(5.0)
        f_tennant.addRow("Caudal medio anual Qma (m³/s):", self.spin_qma_tennant)
        btn_qma_desde_cdc = QPushButton("Usar el promedio de la serie de la sección 1")
        btn_qma_desde_cdc.clicked.connect(self._on_usar_qma_desde_cdc)
        limitar_ancho_boton(btn_qma_desde_cdc)
        f_tennant.addRow(btn_qma_desde_cdc)
        self.spin_pct_estiaje_tennant = QDoubleSpinBox(); self.spin_pct_estiaje_tennant.setRange(1, 100); self.spin_pct_estiaje_tennant.setDecimals(0); self.spin_pct_estiaje_tennant.setValue(10)
        f_tennant.addRow("% Qma en época de estiaje (Perú: típico 10%):", self.spin_pct_estiaje_tennant)
        self.spin_pct_normal_tennant = QDoubleSpinBox(); self.spin_pct_normal_tennant.setRange(1, 100); self.spin_pct_normal_tennant.setDecimals(0); self.spin_pct_normal_tennant.setValue(30)
        f_tennant.addRow("% Qma en época normal:", self.spin_pct_normal_tennant)
        btn_calcular_tennant = QPushButton("Calcular Tennant/Montana")
        btn_calcular_tennant.clicked.connect(self._on_calcular_tennant)
        limitar_ancho_boton(btn_calcular_tennant)
        f_tennant.addRow(btn_calcular_tennant)
        v.addWidget(gb_tennant)
        self.canvas_tennant = LowFlowCanvas(width=7.4, height=3.2)
        v.addWidget(self.canvas_tennant)

        # ---------------- Frecuencia de mínimos ----------------
        gb_frecuencia = QGroupBox("3. Análisis de frecuencia de caudales mínimos anuales")
        v_frec = QVBoxLayout(gb_frecuencia)
        v_frec.addWidget(QLabel("Pegue la serie de caudales MÍNIMOS ANUALES (uno por año, mínimo 5 años):"))
        self.tabla_minimos_anuales = TablaPegable(40, 1)
        self.tabla_minimos_anuales.setHorizontalHeaderLabels(["Q mínimo anual (m³/s)"])
        self.tabla_minimos_anuales.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla_minimos_anuales.setMinimumHeight(180)
        v_frec.addWidget(self.tabla_minimos_anuales)
        h_frec = QHBoxLayout()
        self.chk_weibull_minimos = QCheckBox("Weibull"); self.chk_weibull_minimos.setChecked(True)
        self.chk_gumbel_minimos = QCheckBox("Gumbel de mínimos"); self.chk_gumbel_minimos.setChecked(True)
        h_frec.addWidget(self.chk_weibull_minimos)
        h_frec.addWidget(self.chk_gumbel_minimos)
        h_frec.addWidget(QLabel("Periodo de retorno de diseño Tr (años):"))
        self.spin_tr_diseno_minimos = QDoubleSpinBox(); self.spin_tr_diseno_minimos.setRange(2, 1000); self.spin_tr_diseno_minimos.setDecimals(0); self.spin_tr_diseno_minimos.setValue(10)
        h_frec.addWidget(self.spin_tr_diseno_minimos)
        btn_calcular_frecuencia = QPushButton("Ajustar y calcular")
        btn_calcular_frecuencia.clicked.connect(self._on_calcular_frecuencia_minimos)
        h_frec.addWidget(btn_calcular_frecuencia)
        v_frec.addLayout(h_frec)
        self.canvas_frecuencia_minimos = LowFlowCanvas(width=7.4, height=4.6)
        v_frec.addWidget(self.canvas_frecuencia_minimos)
        v.addWidget(gb_frecuencia)

        # ---------------- Transferencia por cuenca homóloga ----------------
        gb_homologa = QGroupBox("4. Transferencia por cuenca homóloga (cuencas sin información)")
        f_homologa = QFormLayout(gb_homologa)
        f_homologa.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.spin_q_min_homologa = QDoubleSpinBox(); self.spin_q_min_homologa.setRange(0.001, 200000); self.spin_q_min_homologa.setDecimals(3); self.spin_q_min_homologa.setValue(1.0)
        f_homologa.addRow("Q mínimo de la cuenca homóloga (m³/s):", self.spin_q_min_homologa)
        self.spin_area_estudio_homologa = QDoubleSpinBox(); self.spin_area_estudio_homologa.setRange(0.01, 500000); self.spin_area_estudio_homologa.setDecimals(2); self.spin_area_estudio_homologa.setValue(100.0)
        f_homologa.addRow("Área de la cuenca en estudio (km²):", self.spin_area_estudio_homologa)
        self.spin_area_homologa = QDoubleSpinBox(); self.spin_area_homologa.setRange(0.01, 500000); self.spin_area_homologa.setDecimals(2); self.spin_area_homologa.setValue(95.0)
        f_homologa.addRow("Área de la cuenca homóloga (km²):", self.spin_area_homologa)
        btn_calcular_homologa = QPushButton("Calcular por transferencia de áreas")
        btn_calcular_homologa.clicked.connect(self._on_calcular_transferencia_homologa)
        limitar_ancho_boton(btn_calcular_homologa)
        f_homologa.addRow(btn_calcular_homologa)
        v.addWidget(gb_homologa)

        btn_comparar_todos = QPushButton("Comparar TODOS los métodos calculados")
        btn_comparar_todos.clicked.connect(self._on_comparar_metodos_minimos)
        v.addWidget(btn_comparar_todos)
        self.canvas_comparacion_minimos = LowFlowCanvas(width=7.6, height=4.8)
        v.addWidget(self.canvas_comparacion_minimos)

        v.addWidget(QLabel("<b>Cuadro resumen final:</b>"))
        self.texto_resumen_minimos = QTextBrowser()
        self.texto_resumen_minimos.setMinimumHeight(160)
        v.addWidget(self.texto_resumen_minimos)

        self._agregar_pestaña_con_scroll(tab, "16. Caudales Mínimos")

    def _leer_columna_unica(self, tabla):
        valores = []
        for i in range(tabla.rowCount()):
            item = tabla.item(i, 0)
            texto = item.text().strip() if item else ""
            if texto:
                try:
                    valores.append(float(texto.replace(",", ".")))
                except ValueError:
                    continue
        return valores

    def _on_calcular_cdc(self):
        caudales = self._leer_columna_unica(self.tabla_caudales_cdc)
        try:
            cdc = low_flows.curva_duracion(caudales)
            percentil = self.spin_percentil_cdc.value()
            q_persistencia = low_flows.caudal_persistencia(caudales, percentil)
            self.canvas_cdc.plot_curva_duracion(cdc["prob_excedencia_pct"], cdc["caudales_ordenados"],
                                                 percentil, q_persistencia)
            self.resultado_caudales_minimos[f"Q{percentil:.0f} (persistencia)"] = q_persistencia
            QMessageBox.information(self, "Curva de duración calculada",
                                     f"Q{percentil:.0f} = {q_persistencia:.4f} m³/s")
        except low_flows.LowFlowError as e:
            QMessageBox.warning(self, "No se pudo calcular", str(e))

    def _on_usar_qma_desde_cdc(self):
        caudales = self._leer_columna_unica(self.tabla_caudales_cdc)
        if not caudales:
            QMessageBox.warning(self, "Falta la serie", "Ingrese primero la serie de caudales en la sección 1.")
            return
        self.spin_qma_tennant.setValue(sum(caudales) / len(caudales))

    def _on_calcular_tennant(self):
        try:
            q_ma = self.spin_qma_tennant.value()
            pct_estiaje = self.spin_pct_estiaje_tennant.value()
            pct_normal = self.spin_pct_normal_tennant.value()
            resultado = low_flows.tennant_caudal_ecologico(q_ma, pct_estiaje, pct_normal)
            self.canvas_tennant.plot_tennant(q_ma, pct_estiaje, resultado["Q_estiaje_m3s"],
                                              pct_normal, resultado["Q_normal_m3s"])
            self.resultado_caudales_minimos["Tennant (estiaje)"] = resultado["Q_estiaje_m3s"]
            self.resultado_caudales_minimos["Tennant (normal)"] = resultado["Q_normal_m3s"]
            QMessageBox.information(self, "Tennant/Montana calculado",
                                     f"Q estiaje = {resultado['Q_estiaje_m3s']:.4f} m³/s "
                                     f"({resultado['categoria_estiaje']})\n"
                                     f"Q normal = {resultado['Q_normal_m3s']:.4f} m³/s ({resultado['categoria_normal']})")
        except low_flows.LowFlowError as e:
            QMessageBox.warning(self, "No se pudo calcular", str(e))

    def _on_calcular_frecuencia_minimos(self):
        minimos = self._leer_columna_unica(self.tabla_minimos_anuales)
        periodos = [2, 5, 10, 20, 25, 50, 100]
        try:
            q_weibull, q_gumbel = None, None
            if self.chk_weibull_minimos.isChecked():
                w = low_flows.ajustar_weibull_minimos(minimos)
                q_weibull = [low_flows.caudal_tr_weibull(w, tr) for tr in periodos]
                q_tr_diseno_w = low_flows.caudal_tr_weibull(w, self.spin_tr_diseno_minimos.value())
                self.resultado_caudales_minimos[f"Weibull (Tr={self.spin_tr_diseno_minimos.value():.0f} años)"] = q_tr_diseno_w
            if self.chk_gumbel_minimos.isChecked():
                g = low_flows.ajustar_gumbel_minimos(minimos)
                q_gumbel = [low_flows.caudal_tr_gumbel_minimos(g, tr) for tr in periodos]
                q_tr_diseno_g = low_flows.caudal_tr_gumbel_minimos(g, self.spin_tr_diseno_minimos.value())
                self.resultado_caudales_minimos[f"Gumbel mínimos (Tr={self.spin_tr_diseno_minimos.value():.0f} años)"] = q_tr_diseno_g
            self.canvas_frecuencia_minimos.plot_frecuencia_minimos(periodos, q_weibull, q_gumbel)
            QMessageBox.information(self, "Frecuencia de mínimos calculada",
                                     "Ajuste completado; revise la gráfica y el cuadro resumen.")
        except low_flows.LowFlowError as e:
            QMessageBox.warning(self, "No se pudo ajustar", str(e))

    def _on_calcular_transferencia_homologa(self):
        try:
            q_transfer = low_flows.transferencia_cuenca_homologa(
                self.spin_q_min_homologa.value(), self.spin_area_estudio_homologa.value(),
                self.spin_area_homologa.value())
            self.resultado_caudales_minimos["Transferencia cuenca homóloga"] = q_transfer
            QMessageBox.information(self, "Transferencia calculada", f"Q mínimo estimado = {q_transfer:.4f} m³/s")
        except low_flows.LowFlowError as e:
            QMessageBox.warning(self, "No se pudo calcular", str(e))

    def _on_comparar_metodos_minimos(self):
        if not self.resultado_caudales_minimos:
            QMessageBox.warning(self, "Sin resultados", "Calcule al menos un método en las secciones anteriores.")
            return
        resumen = low_flows.resumen_comparativo(self.resultado_caudales_minimos)
        nombres = list(self.resultado_caudales_minimos.keys())
        valores = list(self.resultado_caudales_minimos.values())
        self.canvas_comparacion_minimos.plot_comparacion_metodos(
            nombres, valores, metodo_critico=resumen.get("metodo_mas_restrictivo"))

        html = "<h3>Cuadro resumen final — Caudales Mínimos</h3><table border='1' cellpadding='4' cellspacing='0'>"
        html += "<tr><th>Método</th><th>Q mínimo (m³/s)</th></tr>"
        for nombre, valor in self.resultado_caudales_minimos.items():
            html += f"<tr><td>{nombre}</td><td>{valor:.4f}</td></tr>"
        html += "</table>"
        html += (f"<p><b>Método más restrictivo (criterio conservador para el ecosistema):</b> "
                 f"{resumen['metodo_mas_restrictivo']}<br>"
                 f"<b>Caudal mínimo recomendado: {resumen['q_minimo_recomendado_m3s']:.4f} m³/s</b><br>"
                 f"Promedio entre métodos: {resumen['promedio_m3s']:.4f} m³/s &nbsp;|&nbsp; "
                 f"Rango: {resumen['minimo_m3s']:.4f} – {resumen['maximo_m3s']:.4f} m³/s</p>")
        html += ("<p style='color:#666666'>NOTA: Gumbel de mínimos puede dar valores negativos o poco "
                 "realistas para periodos de retorno muy altos (limitación conocida de esta distribución "
                 "no acotada aplicada a un fenómeno físicamente acotado en cero) — en ese caso prefiera "
                 "Weibull. Ajuste el % ecológico mínimo exigido según la normativa sectorial vigente "
                 "(ANA u otra autoridad competente) antes de un uso definitivo.</p>")
        self.texto_resumen_minimos.setHtml(html)

    # ------------------------------------------------------------------
    # TAB 17: Caudal Ecológico - Metodología USGS PHABSIM. Ver core/phabsim.py.
    # ------------------------------------------------------------------
    def _build_tab_phabsim(self):
        tab = QWidget()
        v = QVBoxLayout(tab)
        _lbl_auto_39 = QLabel(
            "<b>Caudal Ecológico — Metodología USGS PHABSIM</b> — acopla un módulo hidráulico (tirante "
            "y velocidad vs. caudal en cada estación de un transecto, ajustado desde mediciones de campo "
            "en varios caudales de calibración) con un módulo de hábitat (curvas de idoneidad HSI de "
            "velocidad, profundidad y sustrato de la especie objetivo), obteniendo el Área Útil Ponderada "
            "(WUA, m²/km) en función del caudal. <i>Las curvas HSI deben ser ingresadas por usted "
            "(de su estudio de campo, cuenca homóloga, o bibliografía validada por un biólogo/ecólogo) — "
            "este módulo no trae curvas precargadas de ninguna especie.</i>"
        )
        _lbl_auto_39.setWordWrap(True)
        v.addWidget(_lbl_auto_39)

        # ---------------- Curvas HSI ----------------
        gb_hsi = QGroupBox("1. Curvas de Idoneidad de Hábitat (HSI) de la especie objetivo")
        v_hsi = QVBoxLayout(gb_hsi)
        h_hsi_tablas = QHBoxLayout()
        v_hsi_v = QVBoxLayout(); v_hsi_v.addWidget(QLabel("<b>Velocidad</b> (m/s, idoneidad 0-1):"))
        self.tabla_hsi_velocidad = TablaPegable(8, 2)
        self.tabla_hsi_velocidad.setHorizontalHeaderLabels(["Velocidad (m/s)", "Idoneidad (0-1)"])
        ajustar_alto_tabla(self.tabla_hsi_velocidad, filas_visibles_max=10)
        v_hsi_v.addWidget(self.tabla_hsi_velocidad)
        h_hsi_tablas.addLayout(v_hsi_v)
        v_hsi_d = QVBoxLayout(); v_hsi_d.addWidget(QLabel("<b>Profundidad</b> (m, idoneidad 0-1):"))
        self.tabla_hsi_profundidad = TablaPegable(8, 2)
        self.tabla_hsi_profundidad.setHorizontalHeaderLabels(["Tirante (m)", "Idoneidad (0-1)"])
        ajustar_alto_tabla(self.tabla_hsi_profundidad, filas_visibles_max=10)
        v_hsi_d.addWidget(self.tabla_hsi_profundidad)
        h_hsi_tablas.addLayout(v_hsi_d)
        v_hsi_s = QVBoxLayout(); v_hsi_s.addWidget(QLabel("<b>Sustrato</b> (código, idoneidad 0-1):"))
        self.tabla_hsi_sustrato = TablaPegable(8, 2)
        self.tabla_hsi_sustrato.setHorizontalHeaderLabels(["Código sustrato", "Idoneidad (0-1)"])
        ajustar_alto_tabla(self.tabla_hsi_sustrato, filas_visibles_max=10)
        v_hsi_s.addWidget(self.tabla_hsi_sustrato)
        h_hsi_tablas.addLayout(v_hsi_s)
        v_hsi.addLayout(h_hsi_tablas)
        h_referencia = QHBoxLayout()
        h_referencia.addWidget(QLabel("Cargar curva de <b>referencia orientativa</b> (plantilla, NO validada):"))
        self.combo_curva_referencia_phabsim = QComboBox()
        self.combo_curva_referencia_phabsim.addItems(phabsim.listar_curvas_referencia())
        h_referencia.addWidget(self.combo_curva_referencia_phabsim)
        btn_cargar_referencia = QPushButton("Cargar como punto de partida")
        btn_cargar_referencia.clicked.connect(self._on_cargar_curva_referencia_phabsim)
        h_referencia.addWidget(btn_cargar_referencia)
        v_hsi.addLayout(h_referencia)
        _lbl_auto_40 = QLabel(
            "<span style='color:#B3261E'><b>Advertencia:</b> las curvas de referencia son plantillas "
            "ILUSTRATIVAS con la forma típica descrita en la ecología general de cada especie/gremio "
            "(especies de manglares de Tumbes, Lago Titicaca, ríos altoandinos, ríos de la costa, y "
            "especies amazónicas) — NO son curvas HSI validadas de una especie, cuenca o población en "
            "particular. Para especies lénticas/pelágicas (Ispi) la velocidad es poco discriminante en "
            "aguas abiertas, y para especies estuarinas/de manglar la escala de sustrato tipo Brusven no "
            "capta bien la cobertura vegetal/raíces — ambas limitaciones se documentan en el código. "
            "Consulte al IIAP, IMARPE, o estudios ANA/SENACE de proyectos específicos para una curva "
            "validada, y reemplace esta plantilla con datos de campo o bibliografía específica revisada "
            "por un biólogo/ecólogo antes de sustentar un expediente técnico.</span>")
        _lbl_auto_40.setWordWrap(True)
        v_hsi.addWidget(_lbl_auto_40)
        btn_graficar_hsi = QPushButton("Graficar curvas HSI")
        btn_graficar_hsi.clicked.connect(self._on_graficar_hsi_phabsim)
        v_hsi.addWidget(btn_graficar_hsi)
        self.canvas_hsi_phabsim = PhabsimCanvas(width=7.6, height=3.4)
        v_hsi.addWidget(self.canvas_hsi_phabsim)
        v.addWidget(gb_hsi)

        # ---------------- Estaciones del transecto ----------------
        gb_estaciones = QGroupBox("2. Estaciones del transecto (mínimo 2 caudales de calibración medidos en campo por estación)")
        v_est = QVBoxLayout(gb_estaciones)
        h_gen = QHBoxLayout()
        h_gen.addWidget(QLabel("Número de estaciones a crear:"))
        self.spin_num_estaciones_phabsim = QSpinBox(); self.spin_num_estaciones_phabsim.setRange(1, 40); self.spin_num_estaciones_phabsim.setValue(5)
        h_gen.addWidget(self.spin_num_estaciones_phabsim)
        btn_generar_estaciones = QPushButton("Generar estaciones")
        btn_generar_estaciones.clicked.connect(self._on_generar_estaciones_phabsim)
        h_gen.addWidget(btn_generar_estaciones)
        h_gen.addWidget(QLabel("Estación activa:"))
        self.combo_estacion_phabsim_activa = QComboBox()
        self.combo_estacion_phabsim_activa.currentTextChanged.connect(self._on_cambiar_estacion_phabsim_activa)
        h_gen.addWidget(self.combo_estacion_phabsim_activa)
        v_est.addLayout(h_gen)

        f_est = QFormLayout()
        f_est.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.spin_ancho_estacion_phabsim = QDoubleSpinBox(); self.spin_ancho_estacion_phabsim.setRange(0.01, 200); self.spin_ancho_estacion_phabsim.setDecimals(2); self.spin_ancho_estacion_phabsim.setValue(1.0)
        f_est.addRow("Ancho de celda representado por esta estación (m):", self.spin_ancho_estacion_phabsim)
        self.spin_sustrato_estacion_phabsim = QDoubleSpinBox(); self.spin_sustrato_estacion_phabsim.setRange(1, 10); self.spin_sustrato_estacion_phabsim.setDecimals(0); self.spin_sustrato_estacion_phabsim.setValue(4)
        f_est.addRow("Código de sustrato (ej. escala de Brusven, 1-8):", self.spin_sustrato_estacion_phabsim)
        v_est.addLayout(f_est)

        v_est.addWidget(QLabel("Caudales de calibración medidos en campo (mínimo 2, recomendado ≥3 — bajo/medio/alto):"))
        self.tabla_calibracion_phabsim = TablaPegable(5, 3)
        self.tabla_calibracion_phabsim.setHorizontalHeaderLabels(
            ["Caudal de calibración (m³/s)", "Tirante medido (m)", "Velocidad medida (m/s)"])
        self.tabla_calibracion_phabsim.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla_calibracion_phabsim.setMinimumHeight(160)
        v_est.addWidget(self.tabla_calibracion_phabsim)
        v.addWidget(gb_estaciones)

        # ---------------- Cálculo de la curva Q-WUA ----------------
        gb_calculo = QGroupBox("3. Cálculo de la curva Caudal-WUA")
        f_calc = QFormLayout(gb_calculo)
        f_calc.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.spin_q_min_phabsim = QDoubleSpinBox(); self.spin_q_min_phabsim.setRange(0.001, 10000); self.spin_q_min_phabsim.setDecimals(3); self.spin_q_min_phabsim.setValue(0.1)
        f_calc.addRow("Caudal mínimo a evaluar (m³/s):", self.spin_q_min_phabsim)
        self.spin_q_max_phabsim = QDoubleSpinBox(); self.spin_q_max_phabsim.setRange(0.01, 10000); self.spin_q_max_phabsim.setDecimals(3); self.spin_q_max_phabsim.setValue(20.0)
        f_calc.addRow("Caudal máximo a evaluar (m³/s):", self.spin_q_max_phabsim)
        self.spin_porcentaje_umbral_phabsim = QDoubleSpinBox(); self.spin_porcentaje_umbral_phabsim.setRange(10, 99); self.spin_porcentaje_umbral_phabsim.setDecimals(0); self.spin_porcentaje_umbral_phabsim.setValue(80)
        f_calc.addRow("% del WUA máximo para el caudal ecológico de estiaje:", self.spin_porcentaje_umbral_phabsim)
        v.addWidget(gb_calculo)
        btn_calcular_phabsim = QPushButton("Calcular curva Caudal-WUA (todas las estaciones)")
        btn_calcular_phabsim.clicked.connect(self._on_calcular_phabsim)
        v.addWidget(btn_calcular_phabsim)

        gb_resultados = QGroupBox("4. Resultados")
        v_r = QVBoxLayout(gb_resultados)
        self.canvas_q_wua_phabsim = PhabsimCanvas(width=7.6, height=4.8)
        v_r.addWidget(self.canvas_q_wua_phabsim)
        h_ver = QHBoxLayout()
        h_ver.addWidget(QLabel("Ver composición por estación en Q =:"))
        self.combo_q_composicion_phabsim = QComboBox()
        self.combo_q_composicion_phabsim.addItems(["Q óptimo", "Q ecológico (% umbral)", "Q punto de inflexión"])
        self.combo_q_composicion_phabsim.currentTextChanged.connect(self._on_actualizar_composicion_phabsim)
        h_ver.addWidget(self.combo_q_composicion_phabsim)
        v_r.addLayout(h_ver)
        self.canvas_composicion_phabsim = PhabsimCanvas(width=7.6, height=4.2)
        v_r.addWidget(self.canvas_composicion_phabsim)
        v.addWidget(gb_resultados)

        v.addWidget(QLabel("<b>Cuadro resumen final:</b>"))
        self.texto_resumen_phabsim = QTextBrowser()
        self.texto_resumen_phabsim.setMinimumHeight(180)
        v.addWidget(self.texto_resumen_phabsim)

        self._agregar_pestaña_con_scroll(tab, "17. Caudal Ecológico - PHABSIM")

    def _leer_curva_hsi(self, tabla):
        curva = []
        for i in range(tabla.rowCount()):
            item_x = tabla.item(i, 0)
            item_y = tabla.item(i, 1)
            if item_x and item_y and item_x.text().strip() and item_y.text().strip():
                try:
                    curva.append((float(item_x.text().replace(",", ".")), float(item_y.text().replace(",", "."))))
                except ValueError:
                    continue
        return curva

    def _on_cargar_curva_referencia_phabsim(self):
        nombre = self.combo_curva_referencia_phabsim.currentText()
        curvas = phabsim.CURVAS_REFERENCIA_ORIENTATIVAS.get(nombre)
        if not curvas:
            return

        def _llenar(tabla, pares):
            tabla.setRowCount(max(len(pares), 8))
            for i, (x, y) in enumerate(pares):
                tabla.setItem(i, 0, QTableWidgetItem(f"{x:g}"))
                tabla.setItem(i, 1, QTableWidgetItem(f"{y:g}"))
            # Esta carga cambia rowCount directamente (sin pasar por el
            # pegado de TablaPegable), así que necesita su propio recálculo
            # de alto: algunas curvas de referencia traen más de 8 puntos.
            ajustar_alto_tabla(tabla, filas_visibles_max=10)

        _llenar(self.tabla_hsi_velocidad, curvas["velocidad"])
        _llenar(self.tabla_hsi_profundidad, curvas["profundidad"])
        _llenar(self.tabla_hsi_sustrato, curvas["sustrato"])
        QMessageBox.information(self, "Curva de referencia cargada",
                                 f"Se cargó '{nombre}' como punto de partida orientativo.\n\n"
                                 "Recuerde: esta plantilla NO está validada — reemplácela con datos de "
                                 "campo o bibliografía específica antes de un uso definitivo.")
        self._on_graficar_hsi_phabsim()

    def _on_graficar_hsi_phabsim(self):
        v_curva = self._leer_curva_hsi(self.tabla_hsi_velocidad)
        d_curva = self._leer_curva_hsi(self.tabla_hsi_profundidad)
        s_curva = self._leer_curva_hsi(self.tabla_hsi_sustrato)
        if len(v_curva) < 2 or len(d_curva) < 2 or len(s_curva) < 2:
            QMessageBox.warning(self, "Faltan datos", "Ingrese al menos 2 puntos en cada curva HSI.")
            return
        self.canvas_hsi_phabsim.plot_curvas_hsi(v_curva, d_curva, s_curva)

    # -- Gestión de estaciones (mismo patrón que socavación/sedimentos) --
    def _leer_widgets_estacion_phabsim(self) -> dict:
        filas = []
        for i in range(self.tabla_calibracion_phabsim.rowCount()):
            item_q = self.tabla_calibracion_phabsim.item(i, 0)
            item_h = self.tabla_calibracion_phabsim.item(i, 1)
            item_v = self.tabla_calibracion_phabsim.item(i, 2)
            if item_q and item_h and item_v and item_q.text().strip():
                try:
                    filas.append((float(item_q.text().replace(",", ".")), float(item_h.text().replace(",", ".")),
                                 float(item_v.text().replace(",", "."))))
                except ValueError:
                    continue
        return {
            "ancho": self.spin_ancho_estacion_phabsim.value(),
            "sustrato_code": self.spin_sustrato_estacion_phabsim.value(),
            "calibracion": filas,
        }

    def _escribir_widgets_estacion_phabsim(self, datos: dict):
        self.spin_ancho_estacion_phabsim.setValue(datos.get("ancho", 1.0))
        self.spin_sustrato_estacion_phabsim.setValue(datos.get("sustrato_code", 4))
        self.tabla_calibracion_phabsim.setRowCount(max(len(datos.get("calibracion", [])), 5))
        for i, (q, h, vel) in enumerate(datos.get("calibracion", [])):
            self.tabla_calibracion_phabsim.setItem(i, 0, QTableWidgetItem(f"{q:g}"))
            self.tabla_calibracion_phabsim.setItem(i, 1, QTableWidgetItem(f"{h:g}"))
            self.tabla_calibracion_phabsim.setItem(i, 2, QTableWidgetItem(f"{vel:g}"))

    def _on_generar_estaciones_phabsim(self):
        n = self.spin_num_estaciones_phabsim.value()
        if self.nombre_estacion_phabsim_activa:
            self.estaciones_phabsim[self.nombre_estacion_phabsim_activa] = self._leer_widgets_estacion_phabsim()
        for _ in range(n):
            self.contador_estaciones_phabsim += 1
            nombre = f"E{self.contador_estaciones_phabsim}"
            self.estaciones_phabsim[nombre] = {}
        self.combo_estacion_phabsim_activa.blockSignals(True)
        self.combo_estacion_phabsim_activa.clear()
        self.combo_estacion_phabsim_activa.addItems(list(self.estaciones_phabsim.keys()))
        self.combo_estacion_phabsim_activa.blockSignals(False)
        if self.estaciones_phabsim:
            nombre_primera = list(self.estaciones_phabsim.keys())[0]
            self.combo_estacion_phabsim_activa.setCurrentText(nombre_primera)
            self.nombre_estacion_phabsim_activa = nombre_primera
            self._escribir_widgets_estacion_phabsim(self.estaciones_phabsim[nombre_primera])

    def _on_cambiar_estacion_phabsim_activa(self, nombre_nuevo: str):
        if not nombre_nuevo:
            return
        if self.nombre_estacion_phabsim_activa and self.nombre_estacion_phabsim_activa in self.estaciones_phabsim:
            self.estaciones_phabsim[self.nombre_estacion_phabsim_activa] = self._leer_widgets_estacion_phabsim()
        self.nombre_estacion_phabsim_activa = nombre_nuevo
        self._escribir_widgets_estacion_phabsim(self.estaciones_phabsim.get(nombre_nuevo, {}))

    def _on_calcular_phabsim(self):
        if self.nombre_estacion_phabsim_activa:
            self.estaciones_phabsim[self.nombre_estacion_phabsim_activa] = self._leer_widgets_estacion_phabsim()

        curva_v = self._leer_curva_hsi(self.tabla_hsi_velocidad)
        curva_d = self._leer_curva_hsi(self.tabla_hsi_profundidad)
        curva_s = self._leer_curva_hsi(self.tabla_hsi_sustrato)
        if len(curva_v) < 2 or len(curva_d) < 2 or len(curva_s) < 2:
            QMessageBox.warning(self, "Faltan las curvas HSI", "Ingrese las 3 curvas HSI en la sección 1.")
            return

        estaciones_calculo = []
        try:
            for nombre, datos in self.estaciones_phabsim.items():
                calibracion = datos.get("calibracion", [])
                if len(calibracion) < 2:
                    continue
                caudales_cal = [c[0] for c in calibracion]
                tirantes_cal = [c[1] for c in calibracion]
                velocidades_cal = [c[2] for c in calibracion]
                ajuste = phabsim.ajustar_estacion(caudales_cal, tirantes_cal, velocidades_cal)
                estaciones_calculo.append({"nombre": nombre, "ancho": datos.get("ancho", 1.0),
                                           "sustrato_code": datos.get("sustrato_code", 4), "ajuste": ajuste})
            if not estaciones_calculo:
                QMessageBox.warning(self, "Faltan datos",
                                     "Ingrese al menos 2 caudales de calibración (Q, H, V) en al menos una estación.")
                return

            curva = phabsim.curva_caudal_wua(estaciones_calculo, curva_v, curva_d, curva_s,
                                              self.spin_q_min_phabsim.value(), self.spin_q_max_phabsim.value())
            optimo = phabsim.encontrar_caudal_optimo(curva)
            umbral = phabsim.encontrar_caudal_umbral_pct(curva, self.spin_porcentaje_umbral_phabsim.value())
            inflexion = phabsim.encontrar_punto_inflexion(curva)

            self.canvas_q_wua_phabsim.plot_curva_q_wua(
                curva["caudales"], curva["wua"], optimo["Q_optimo_m3s"], optimo["WUA_maximo_m2_km"],
                umbral["Q_umbral_m3s"], umbral["WUA_en_umbral_m2_km"], umbral["porcentaje"],
                inflexion["Q_inflexion_m3s"], inflexion["WUA_en_inflexion_m2_km"])

            self.resultado_curva_phabsim = {
                "curva": curva, "optimo": optimo, "umbral": umbral, "inflexion": inflexion,
                "estaciones_calculo": estaciones_calculo, "curva_v": curva_v, "curva_d": curva_d, "curva_s": curva_s,
            }
            self._on_actualizar_composicion_phabsim(self.combo_q_composicion_phabsim.currentText())
            self._actualizar_texto_resumen_phabsim()
        except phabsim.PhabsimError as e:
            QMessageBox.warning(self, "No se pudo calcular", str(e))

    def _on_actualizar_composicion_phabsim(self, opcion: str):
        r = self.resultado_curva_phabsim
        if not r:
            return
        if opcion == "Q óptimo":
            q = r["optimo"]["Q_optimo_m3s"]
        elif opcion == "Q ecológico (% umbral)":
            q = r["umbral"]["Q_umbral_m3s"]
        else:
            q = r["inflexion"]["Q_inflexion_m3s"]
        resultado = phabsim.calcular_wua(r["estaciones_calculo"], r["curva_v"], r["curva_d"], r["curva_s"], q)
        nombres = [d["estacion"] for d in resultado["detalle"]]
        aportes = [d["aporte_m2_m"] for d in resultado["detalle"]]
        self.canvas_composicion_phabsim.plot_composicion_estaciones(nombres, aportes, q)

    def _actualizar_texto_resumen_phabsim(self):
        r = self.resultado_curva_phabsim
        if not r:
            return
        html = "<h3>Cuadro resumen final — Caudal Ecológico (PHABSIM)</h3>"
        html += (f"<p><b>Caudal óptimo (máximo hábitat disponible):</b> {r['optimo']['Q_optimo_m3s']:.3f} m³/s "
                 f"(WUA = {r['optimo']['WUA_maximo_m2_km']:.0f} m²/km)<br>"
                 f"<b>Caudal ecológico de estiaje ({r['umbral']['porcentaje']:.0f}% del WUA máximo):</b> "
                 f"{r['umbral']['Q_umbral_m3s']:.3f} m³/s (WUA = {r['umbral']['WUA_en_umbral_m2_km']:.0f} m²/km)<br>"
                 f"<b>Punto de inflexión de la curva:</b> {r['inflexion']['Q_inflexion_m3s']:.3f} m³/s "
                 f"(WUA = {r['inflexion']['WUA_en_inflexion_m2_km']:.0f} m²/km)</p>")
        html += ("<p style='color:#666666'>NOTA: en época de estiaje severo, cuando mantener el caudal "
                 "óptimo no es hidrológicamente viable, la ANA evalúa el punto de quiebre/inflexión de la "
                 "curva WUA como referencia; el umbral porcentual es un criterio práctico alternativo. "
                 "El expediente ante la ANA debe incluir línea base hidrológica (persistencia 75%/95%, "
                 "ver Pestaña Caudales Mínimos), justificación biológica de la especie objetivo, y firmas "
                 "de un Ingeniero (modelación hidráulica) y un Biólogo/Ecólogo (interpretación del hábitat).</p>")
        self.texto_resumen_phabsim.setHtml(html)

    # ------------------------------------------------------------------
    # TAB 18: Flujo Subterráneo. Ver core/groundwater_flow.py.
    # ------------------------------------------------------------------
    def _build_tab_flujo_subterraneo(self):
        tab = QWidget()
        v = QVBoxLayout(tab)
        _lbl_auto_41 = QLabel(
            "<b>Flujo Subterráneo</b> — Ley de Darcy, flujo 1D entre dos puntos (confinado y no "
            "confinado/Dupuit), y un <b>solver 2D real</b> de flujo subterráneo en régimen permanente "
            "(diferencias finitas, Gauss-Seidel/SOR) para acuíferos confinados homogéneos o con "
            "transmisividad variable por celda. <i>No reemplaza a MODFLOW/FEFLOW para modelos 3D "
            "transitorios y heterogéneos — para eso siga las fases: modelo conceptual, discretización, "
            "selección de software, calibración con piezómetros de campo. La hidráulica de POZOS "
            "específica (Thiem, Theis, radio de influencia) está en la siguiente pestaña.</i>"
        )
        _lbl_auto_41.setWordWrap(True)
        v.addWidget(_lbl_auto_41)

        # ---------------- Ley de Darcy ----------------
        gb_darcy = QGroupBox("1. Ley de Darcy")
        f_darcy = QFormLayout(gb_darcy)
        f_darcy.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.spin_k_darcy = QDoubleSpinBox(); self.spin_k_darcy.setRange(1e-9, 1.0); self.spin_k_darcy.setDecimals(8); self.spin_k_darcy.setValue(0.0001)
        f_darcy.addRow("Conductividad hidráulica K (m/s):", self.spin_k_darcy)
        self.spin_gradiente_darcy = QDoubleSpinBox(); self.spin_gradiente_darcy.setRange(0.00001, 1.0); self.spin_gradiente_darcy.setDecimals(5); self.spin_gradiente_darcy.setValue(0.01)
        f_darcy.addRow("Gradiente hidráulico dh/dl (m/m):", self.spin_gradiente_darcy)
        self.spin_area_darcy = QDoubleSpinBox(); self.spin_area_darcy.setRange(0.01, 1e7); self.spin_area_darcy.setDecimals(2); self.spin_area_darcy.setValue(50.0)
        f_darcy.addRow("Área de la sección transversal (m²):", self.spin_area_darcy)
        self.spin_porosidad_darcy = QDoubleSpinBox(); self.spin_porosidad_darcy.setRange(0.01, 0.6); self.spin_porosidad_darcy.setDecimals(3); self.spin_porosidad_darcy.setValue(0.25)
        f_darcy.addRow("Porosidad efectiva ne:", self.spin_porosidad_darcy)
        btn_calcular_darcy = QPushButton("Calcular")
        btn_calcular_darcy.clicked.connect(self._on_calcular_darcy)
        limitar_ancho_boton(btn_calcular_darcy)
        f_darcy.addRow(btn_calcular_darcy)
        self.texto_resultado_darcy = QLabel("—")
        f_darcy.addRow("Resultado:", self.texto_resultado_darcy)
        v.addWidget(gb_darcy)

        # ---------------- Flujo 1D ----------------
        gb_1d = QGroupBox("2. Flujo 1D entre dos puntos")
        f_1d = QFormLayout(gb_1d)
        f_1d.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.combo_tipo_acuifero_1d = QComboBox()
        self.combo_tipo_acuifero_1d.addItems(["Confinado (usa Transmisividad T)", "No confinado / libre (Dupuit, usa K)"])
        f_1d.addRow("Tipo de acuífero:", self.combo_tipo_acuifero_1d)
        self.spin_t_o_k_1d = QDoubleSpinBox(); self.spin_t_o_k_1d.setRange(1e-8, 10.0); self.spin_t_o_k_1d.setDecimals(6); self.spin_t_o_k_1d.setValue(0.005)
        f_1d.addRow("T (m²/s) si confinado, o K (m/s) si no confinado:", self.spin_t_o_k_1d)
        self.spin_h1_1d = QDoubleSpinBox(); self.spin_h1_1d.setRange(-1000, 9000); self.spin_h1_1d.setDecimals(2); self.spin_h1_1d.setValue(100.0)
        f_1d.addRow("Carga h1 aguas arriba (m):", self.spin_h1_1d)
        self.spin_h2_1d = QDoubleSpinBox(); self.spin_h2_1d.setRange(-1000, 9000); self.spin_h2_1d.setDecimals(2); self.spin_h2_1d.setValue(95.0)
        f_1d.addRow("Carga h2 aguas abajo (m):", self.spin_h2_1d)
        self.spin_longitud_1d = QDoubleSpinBox(); self.spin_longitud_1d.setRange(0.1, 100000); self.spin_longitud_1d.setDecimals(2); self.spin_longitud_1d.setValue(500.0)
        f_1d.addRow("Longitud L (m):", self.spin_longitud_1d)
        self.spin_ancho_1d = QDoubleSpinBox(); self.spin_ancho_1d.setRange(0.1, 100000); self.spin_ancho_1d.setDecimals(2); self.spin_ancho_1d.setValue(200.0)
        f_1d.addRow("Ancho del frente de flujo (m):", self.spin_ancho_1d)
        btn_calcular_1d = QPushButton("Calcular Q")
        btn_calcular_1d.clicked.connect(self._on_calcular_flujo_1d)
        limitar_ancho_boton(btn_calcular_1d)
        f_1d.addRow(btn_calcular_1d)
        self.texto_resultado_1d = QLabel("—")
        f_1d.addRow("Resultado:", self.texto_resultado_1d)
        v.addWidget(gb_1d)

        # ---------------- Solver 2D ----------------
        gb_2d = QGroupBox("3. Solver 2D de flujo subterráneo en régimen permanente")
        f_2d = QFormLayout(gb_2d)
        f_2d.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.spin_filas_2d = QSpinBox(); self.spin_filas_2d.setRange(3, 100); self.spin_filas_2d.setValue(21)
        f_2d.addRow("Número de filas de la malla:", self.spin_filas_2d)
        self.spin_columnas_2d = QSpinBox(); self.spin_columnas_2d.setRange(3, 100); self.spin_columnas_2d.setValue(21)
        f_2d.addRow("Número de columnas de la malla:", self.spin_columnas_2d)
        self.spin_dx_2d = QDoubleSpinBox(); self.spin_dx_2d.setRange(0.1, 10000); self.spin_dx_2d.setDecimals(2); self.spin_dx_2d.setValue(25.0)
        f_2d.addRow("Tamaño de celda dx (m):", self.spin_dx_2d)
        self.spin_dy_2d = QDoubleSpinBox(); self.spin_dy_2d.setRange(0.1, 10000); self.spin_dy_2d.setDecimals(2); self.spin_dy_2d.setValue(25.0)
        f_2d.addRow("Tamaño de celda dy (m):", self.spin_dy_2d)
        self.spin_t_2d = QDoubleSpinBox(); self.spin_t_2d.setRange(1e-6, 10.0); self.spin_t_2d.setDecimals(5); self.spin_t_2d.setValue(0.02)
        f_2d.addRow("Transmisividad T homogénea (m²/s):", self.spin_t_2d)
        self.spin_espesor_2d = QDoubleSpinBox(); self.spin_espesor_2d.setRange(0.1, 1000); self.spin_espesor_2d.setDecimals(2); self.spin_espesor_2d.setValue(10.0)
        f_2d.addRow("Espesor saturado (m, para el campo de velocidades):", self.spin_espesor_2d)
        v.addWidget(gb_2d)

        h_bordes = QHBoxLayout()
        self.chk_borde_izq = QCheckBox("Borde izquierdo, h ="); self.chk_borde_izq.setChecked(True)
        self.spin_h_borde_izq = QDoubleSpinBox(); self.spin_h_borde_izq.setRange(-1000, 9000); self.spin_h_borde_izq.setDecimals(2); self.spin_h_borde_izq.setValue(50.0)
        h_bordes.addWidget(self.chk_borde_izq); h_bordes.addWidget(self.spin_h_borde_izq)
        self.chk_borde_der = QCheckBox("Borde derecho, h ="); self.chk_borde_der.setChecked(True)
        self.spin_h_borde_der = QDoubleSpinBox(); self.spin_h_borde_der.setRange(-1000, 9000); self.spin_h_borde_der.setDecimals(2); self.spin_h_borde_der.setValue(48.0)
        h_bordes.addWidget(self.chk_borde_der); h_bordes.addWidget(self.spin_h_borde_der)
        self.chk_borde_sup = QCheckBox("Borde superior, h ="); self.chk_borde_sup.setChecked(True)
        self.spin_h_borde_sup = QDoubleSpinBox(); self.spin_h_borde_sup.setRange(-1000, 9000); self.spin_h_borde_sup.setDecimals(2); self.spin_h_borde_sup.setValue(50.0)
        h_bordes.addWidget(self.chk_borde_sup); h_bordes.addWidget(self.spin_h_borde_sup)
        self.chk_borde_inf = QCheckBox("Borde inferior, h ="); self.chk_borde_inf.setChecked(True)
        self.spin_h_borde_inf = QDoubleSpinBox(); self.spin_h_borde_inf.setRange(-1000, 9000); self.spin_h_borde_inf.setDecimals(2); self.spin_h_borde_inf.setValue(48.0)
        h_bordes.addWidget(self.chk_borde_inf); h_bordes.addWidget(self.spin_h_borde_inf)
        v.addLayout(h_bordes)
        v.addWidget(QLabel("Bordes no marcados quedan SIN FLUJO (Neumann cero). Los checkboxes fijan carga "
                            "uniforme (Dirichlet) en todo ese borde de la malla."))

        v.addWidget(QLabel("Fuentes/sumideros adicionales (pozos, recarga puntual) — fila, columna (0-index), Q (m³/s; + recarga, − bombeo):"))
        self.tabla_fuentes_2d = TablaPegable(10, 3)
        self.tabla_fuentes_2d.setHorizontalHeaderLabels(["Fila", "Columna", "Q (m³/s)"])
        self.tabla_fuentes_2d.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla_fuentes_2d.setMinimumHeight(160)
        v.addWidget(self.tabla_fuentes_2d)

        btn_resolver_2d = QPushButton("Resolver flujo subterráneo 2D")
        btn_resolver_2d.clicked.connect(self._on_resolver_flujo_2d)
        v.addWidget(btn_resolver_2d)

        self.canvas_mapa_2d = GroundwaterCanvas(width=7.6, height=5.4)
        v.addWidget(self.canvas_mapa_2d)
        self.canvas_convergencia_2d = GroundwaterCanvas(width=7.6, height=3.6)
        v.addWidget(self.canvas_convergencia_2d)

        # ---------------- Calibración ----------------
        gb_calib = QGroupBox("4. Calibración: cargas simuladas vs. observadas en pozos")
        v_calib = QVBoxLayout(gb_calib)
        v_calib.addWidget(QLabel("Pozos de observación — fila, columna (dentro de la malla resuelta), h observado (m):"))
        self.tabla_calibracion_2d = TablaPegable(10, 3)
        self.tabla_calibracion_2d.setHorizontalHeaderLabels(["Fila", "Columna", "H observado (m)"])
        self.tabla_calibracion_2d.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla_calibracion_2d.setMinimumHeight(160)
        v_calib.addWidget(self.tabla_calibracion_2d)
        btn_calibrar_2d = QPushButton("Comparar con las cargas simuladas")
        btn_calibrar_2d.clicked.connect(self._on_calibrar_flujo_2d)
        v_calib.addWidget(btn_calibrar_2d)
        self.canvas_calibracion_2d = GroundwaterCanvas(width=6.4, height=5.4)
        v_calib.addWidget(self.canvas_calibracion_2d)
        v.addWidget(gb_calib)

        v.addWidget(QLabel("<b>Cuadro resumen final:</b>"))
        self.texto_resumen_flujo_subterraneo = QTextBrowser()
        self.texto_resumen_flujo_subterraneo.setMinimumHeight(150)
        v.addWidget(self.texto_resumen_flujo_subterraneo)

        self._agregar_pestaña_con_scroll(tab, "18. Flujo Subterráneo")

    def _on_calcular_darcy(self):
        k = self.spin_k_darcy.value()
        i = self.spin_gradiente_darcy.value()
        a = self.spin_area_darcy.value()
        ne = self.spin_porosidad_darcy.value()
        v_darcy = groundwater_flow.velocidad_darcy(k, i)
        q = groundwater_flow.caudal_darcy(k, a, i)
        v_real = groundwater_flow.velocidad_lineal_promedio(v_darcy, ne)
        self.texto_resultado_darcy.setText(
            f"v Darcy = {v_darcy:.3e} m/s | Q = {q:.3e} m³/s | v real en poros = {v_real:.3e} m/s")

    def _on_calcular_flujo_1d(self):
        try:
            h1, h2 = self.spin_h1_1d.value(), self.spin_h2_1d.value()
            l = self.spin_longitud_1d.value()
            ancho = self.spin_ancho_1d.value()
            valor = self.spin_t_o_k_1d.value()
            if self.combo_tipo_acuifero_1d.currentIndex() == 0:
                q = groundwater_flow.caudal_1d_confinado(valor, h1, h2, l, ancho)
                self.texto_resultado_1d.setText(f"Q (confinado) = {q:.5f} m³/s")
            else:
                q = groundwater_flow.caudal_1d_dupuit(valor, h1, h2, l, ancho)
                self.texto_resultado_1d.setText(f"Q (Dupuit, no confinado) = {q:.5f} m³/s")
        except groundwater_flow.GroundwaterError as e:
            QMessageBox.warning(self, "No se pudo calcular", str(e))

    def _leer_tabla_fila_col_valor(self, tabla):
        pares = {}
        for i in range(tabla.rowCount()):
            item_f = tabla.item(i, 0)
            item_c = tabla.item(i, 1)
            item_v = tabla.item(i, 2)
            if item_f and item_c and item_v and item_f.text().strip():
                try:
                    fila = int(float(item_f.text().replace(",", ".")))
                    col = int(float(item_c.text().replace(",", ".")))
                    valor = float(item_v.text().replace(",", "."))
                    pares[(fila, col)] = valor
                except ValueError:
                    continue
        return pares

    def _on_resolver_flujo_2d(self):
        try:
            n_filas = self.spin_filas_2d.value()
            n_columnas = self.spin_columnas_2d.value()
            dx, dy = self.spin_dx_2d.value(), self.spin_dy_2d.value()
            t = self.spin_t_2d.value()

            condiciones = {}
            if self.chk_borde_izq.isChecked():
                for i in range(n_filas):
                    condiciones[(i, 0)] = self.spin_h_borde_izq.value()
            if self.chk_borde_der.isChecked():
                for i in range(n_filas):
                    condiciones[(i, n_columnas - 1)] = self.spin_h_borde_der.value()
            if self.chk_borde_sup.isChecked():
                for j in range(n_columnas):
                    condiciones[(0, j)] = self.spin_h_borde_sup.value()
            if self.chk_borde_inf.isChecked():
                for j in range(n_columnas):
                    condiciones[(n_filas - 1, j)] = self.spin_h_borde_inf.value()
            if not condiciones:
                QMessageBox.warning(self, "Faltan condiciones de borde",
                                     "Fije al menos un borde con carga conocida (Dirichlet).")
                return

            fuentes = self._leer_tabla_fila_col_valor(self.tabla_fuentes_2d)

            resultado = groundwater_flow.resolver_flujo_2d_permanente(
                n_filas, n_columnas, dx, dy, t, condiciones, fuentes, tol_m=1e-6, max_iter=20000)
            h = resultado["cargas_h"]
            velocidades = groundwater_flow.calcular_velocidades_darcy_2d(h, t, self.spin_espesor_2d.value(), dx, dy)
            pozos_coords = [((fila, col), f"Q={valor:+.3f}") for (fila, col), valor in fuentes.items()]

            self.canvas_mapa_2d.plot_mapa_cargas(h, dx, dy, velocidades["vx"], velocidades["vy"], pozos_coords)
            self.canvas_convergencia_2d.plot_convergencia(resultado["historial_residuo"], 1e-6)

            self.resultado_flujo_subterraneo = {"h": h, "resultado": resultado, "velocidades": velocidades,
                                                "n_filas": n_filas, "n_columnas": n_columnas, "dx": dx, "dy": dy}
            self._actualizar_texto_resumen_flujo_subterraneo()
            if not resultado["convergio"]:
                QMessageBox.warning(self, "No convergió completamente",
                                     f"Se alcanzó el máximo de iteraciones con un residuo de "
                                     f"{resultado['residuo_final_m']:.2e} m. Aumente max_iter o revise la malla.")
        except groundwater_flow.GroundwaterError as e:
            QMessageBox.critical(self, "Error en el solver", str(e))

    def _on_calibrar_flujo_2d(self):
        if not self.resultado_flujo_subterraneo:
            QMessageBox.warning(self, "Falta resolver el flujo 2D", "Resuelva primero el flujo 2D en la sección 3.")
            return
        h = self.resultado_flujo_subterraneo["h"]
        pozos = []
        for i in range(self.tabla_calibracion_2d.rowCount()):
            item_f = self.tabla_calibracion_2d.item(i, 0)
            item_c = self.tabla_calibracion_2d.item(i, 1)
            item_h = self.tabla_calibracion_2d.item(i, 2)
            if item_f and item_c and item_h and item_f.text().strip():
                try:
                    pozos.append((int(float(item_f.text())), int(float(item_c.text())), float(item_h.text().replace(",", "."))))
                except ValueError:
                    continue
        if not pozos:
            QMessageBox.warning(self, "Faltan datos", "Ingrese al menos un pozo de observación.")
            return
        try:
            diag = groundwater_flow.comparar_cargas_observadas(h, pozos)
            h_obs = [d["h_observado_m"] for d in diag["detalle"]]
            h_sim = [d["h_simulado_m"] for d in diag["detalle"]]
            self.canvas_calibracion_2d.plot_calibracion(h_obs, h_sim, diag["rmse_m"])
            self.resultado_flujo_subterraneo["calibracion"] = diag
            self._actualizar_texto_resumen_flujo_subterraneo()
        except groundwater_flow.GroundwaterError as e:
            QMessageBox.warning(self, "No se pudo calibrar", str(e))

    def _actualizar_texto_resumen_flujo_subterraneo(self):
        r = self.resultado_flujo_subterraneo
        if not r:
            return
        h = r["h"]
        html = "<h3>Cuadro resumen final — Flujo Subterráneo</h3>"
        html += (f"<p>Malla: {r['n_filas']} x {r['n_columnas']} celdas ({r['dx']:.1f} x {r['dy']:.1f} m)<br>"
                 f"Convergencia: {'Sí' if r['resultado']['convergio'] else 'NO — revisar'} "
                 f"en {r['resultado']['iteraciones']} iteraciones (residuo final = {r['resultado']['residuo_final_m']:.2e} m)<br>"
                 f"Carga mínima simulada: {h.min():.3f} m &nbsp;|&nbsp; Carga máxima: {h.max():.3f} m</p>")
        if r.get("calibracion"):
            html += f"<p><b>RMSE de calibración:</b> {r['calibracion']['rmse_m']:.4f} m</p>"
        html += ("<p style='color:#666666'>NOTA: este solver resuelve el flujo subterráneo GENERAL en "
                 "régimen permanente (diferencias finitas 2D validadas contra la solución analítica 1D). "
                 "Para régimen transitorio, múltiples capas, recarga variable en el tiempo, o geología "
                 "compleja, use MODFLOW/FEFLOW calibrado con piezómetros de campo.</p>")
        self.texto_resumen_flujo_subterraneo.setHtml(html)

    # ------------------------------------------------------------------
    # TAB 19: Hidráulica de Pozos. Ver core/well_hydraulics.py.
    # ------------------------------------------------------------------
    def _build_tab_hidraulica_pozos(self):
        tab = QWidget()
        v = QVBoxLayout(tab)
        _lbl_auto_42 = QLabel(
            "<b>Hidráulica de Pozos</b> — régimen permanente (Thiem confinado, Dupuit-Thiem libre), "
            "régimen variable (Theis con la función de pozo W(u), y su simplificación de Cooper-Jacob), "
            "pérdidas de carga en el pozo (ensayo escalonado sw=B·Q+C·Q²), y radio de influencia por "
            "varios métodos con selección de la <b>mejor propuesta</b> según la jerarquía de exactitud "
            "de la bibliografía (prueba de bombeo real &gt; Theis &gt; fórmulas empíricas)."
        )
        _lbl_auto_42.setWordWrap(True)
        v.addWidget(_lbl_auto_42)

        # ---------------- Régimen permanente ----------------
        gb_permanente = QGroupBox("1. Régimen permanente (Thiem / Dupuit-Thiem)")
        f_perm = QFormLayout(gb_permanente)
        f_perm.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.combo_tipo_acuifero_pozo = QComboBox()
        self.combo_tipo_acuifero_pozo.addItems(["Confinado (Thiem)", "Libre / no confinado (Dupuit-Thiem)"])
        f_perm.addRow("Tipo de acuífero:", self.combo_tipo_acuifero_pozo)
        self.combo_modo_permanente = QComboBox()
        self.combo_modo_permanente.addItems(["Calcular caudal Q (dados T o K)", "Calcular T o K (calibración con 2 pozos de observación)"])
        f_perm.addRow("Modo:", self.combo_modo_permanente)
        self.spin_q_permanente = QDoubleSpinBox(); self.spin_q_permanente.setRange(0.0001, 10.0); self.spin_q_permanente.setDecimals(5); self.spin_q_permanente.setValue(0.05)
        f_perm.addRow("Caudal de bombeo Q (m³/s):", self.spin_q_permanente)
        self.spin_t_o_k_permanente = QDoubleSpinBox(); self.spin_t_o_k_permanente.setRange(1e-8, 10.0); self.spin_t_o_k_permanente.setDecimals(6); self.spin_t_o_k_permanente.setValue(0.005)
        f_perm.addRow("T (m²/s, confinado) o K (m/s, libre):", self.spin_t_o_k_permanente)
        self.spin_r1_permanente = QDoubleSpinBox(); self.spin_r1_permanente.setRange(0.01, 10000); self.spin_r1_permanente.setDecimals(2); self.spin_r1_permanente.setValue(10.0)
        f_perm.addRow("r1 — distancia al pozo de observación 1 (m):", self.spin_r1_permanente)
        self.spin_r2_permanente = QDoubleSpinBox(); self.spin_r2_permanente.setRange(0.01, 10000); self.spin_r2_permanente.setDecimals(2); self.spin_r2_permanente.setValue(100.0)
        f_perm.addRow("r2 — distancia al pozo de observación 2 (m):", self.spin_r2_permanente)
        self.spin_s1_h1_permanente = QDoubleSpinBox(); self.spin_s1_h1_permanente.setRange(-1000, 9000); self.spin_s1_h1_permanente.setDecimals(3); self.spin_s1_h1_permanente.setValue(2.5)
        f_perm.addRow("s1 (descenso en r1, confinado) o h1 (nivel en r1, libre):", self.spin_s1_h1_permanente)
        self.spin_s2_h2_permanente = QDoubleSpinBox(); self.spin_s2_h2_permanente.setRange(-1000, 9000); self.spin_s2_h2_permanente.setDecimals(3); self.spin_s2_h2_permanente.setValue(1.2)
        f_perm.addRow("s2 (descenso en r2, confinado) o h2 (nivel en r2, libre):", self.spin_s2_h2_permanente)
        btn_calcular_permanente = QPushButton("Calcular")
        btn_calcular_permanente.clicked.connect(self._on_calcular_regimen_permanente)
        limitar_ancho_boton(btn_calcular_permanente)
        f_perm.addRow(btn_calcular_permanente)
        self.texto_resultado_permanente = QLabel("—")
        f_perm.addRow("Resultado:", self.texto_resultado_permanente)
        v.addWidget(gb_permanente)

        # ---------------- Régimen variable: Theis ----------------
        gb_theis = QGroupBox("2. Régimen variable — Theis (curva de descenso teórica)")
        f_theis = QFormLayout(gb_theis)
        f_theis.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.spin_q_theis = QDoubleSpinBox(); self.spin_q_theis.setRange(0.0001, 10.0); self.spin_q_theis.setDecimals(5); self.spin_q_theis.setValue(0.05)
        f_theis.addRow("Caudal de bombeo Q (m³/s):", self.spin_q_theis)
        self.spin_t_theis = QDoubleSpinBox(); self.spin_t_theis.setRange(1e-8, 10.0); self.spin_t_theis.setDecimals(6); self.spin_t_theis.setValue(0.008)
        f_theis.addRow("Transmisividad T (m²/s):", self.spin_t_theis)
        self.spin_s_theis = QDoubleSpinBox(); self.spin_s_theis.setRange(1e-6, 0.5); self.spin_s_theis.setDecimals(6); self.spin_s_theis.setValue(0.0003)
        f_theis.addRow("Coeficiente de almacenamiento S:", self.spin_s_theis)
        self.spin_r_theis = QDoubleSpinBox(); self.spin_r_theis.setRange(0.01, 10000); self.spin_r_theis.setDecimals(2); self.spin_r_theis.setValue(30.0)
        f_theis.addRow("Distancia r al pozo de observación (m):", self.spin_r_theis)
        self.spin_t_max_theis = QDoubleSpinBox(); self.spin_t_max_theis.setRange(60, 31536000); self.spin_t_max_theis.setDecimals(0); self.spin_t_max_theis.setValue(86400)
        f_theis.addRow("Tiempo máximo a graficar (s):", self.spin_t_max_theis)
        btn_calcular_theis = QPushButton("Graficar curva de descenso (Theis)")
        btn_calcular_theis.clicked.connect(self._on_calcular_theis)
        limitar_ancho_boton(btn_calcular_theis)
        f_theis.addRow(btn_calcular_theis)
        v.addWidget(gb_theis)

        v.addWidget(QLabel("<b>Calibración con datos medidos en campo — Cooper-Jacob</b> "
                            "(pegue pares tiempo-descenso de un ensayo de bombeo):"))
        self.tabla_cooper_jacob = TablaPegable(15, 2)
        self.tabla_cooper_jacob.setHorizontalHeaderLabels(["Tiempo (s)", "Descenso medido (m)"])
        self.tabla_cooper_jacob.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla_cooper_jacob.setMinimumHeight(200)
        v.addWidget(self.tabla_cooper_jacob)
        btn_ajustar_cooper_jacob = QPushButton("Ajustar Cooper-Jacob (obtener T y S)")
        btn_ajustar_cooper_jacob.clicked.connect(self._on_ajustar_cooper_jacob)
        v.addWidget(btn_ajustar_cooper_jacob)

        self.canvas_theis = WellCanvas(width=7.6, height=4.4)
        v.addWidget(self.canvas_theis)
        self.canvas_cooper_jacob = WellCanvas(width=7.6, height=4.4)
        v.addWidget(self.canvas_cooper_jacob)

        # ---------------- Pérdidas de pozo ----------------
        gb_perdidas = QGroupBox("3. Pérdidas de carga en el pozo (ensayo de bombeo escalonado)")
        v_perd = QVBoxLayout(gb_perdidas)
        v_perd.addWidget(QLabel("Pegue los escalones de caudal y su descenso total en el pozo:"))
        self.tabla_ensayo_escalonado = TablaPegable(6, 2)
        self.tabla_ensayo_escalonado.setHorizontalHeaderLabels(["Caudal Q (m³/s)", "Descenso total sw (m)"])
        self.tabla_ensayo_escalonado.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla_ensayo_escalonado.setMinimumHeight(160)
        v_perd.addWidget(self.tabla_ensayo_escalonado)
        h_perd = QHBoxLayout()
        btn_ajustar_perdidas = QPushButton("Ajustar B y C")
        btn_ajustar_perdidas.clicked.connect(self._on_ajustar_perdidas_pozo)
        h_perd.addWidget(btn_ajustar_perdidas)
        h_perd.addWidget(QLabel("Caudal de diseño para evaluar pérdidas (m³/s):"))
        self.spin_q_diseno_perdidas = QDoubleSpinBox(); self.spin_q_diseno_perdidas.setRange(0.0001, 10.0); self.spin_q_diseno_perdidas.setDecimals(5); self.spin_q_diseno_perdidas.setValue(0.05)
        h_perd.addWidget(self.spin_q_diseno_perdidas)
        v_perd.addLayout(h_perd)
        self.canvas_ensayo_escalonado = WellCanvas(width=7.6, height=4.4)
        v_perd.addWidget(self.canvas_ensayo_escalonado)
        self.texto_resultado_perdidas = QLabel("—")
        v_perd.addWidget(self.texto_resultado_perdidas)
        v.addWidget(gb_perdidas)

        # ---------------- Radio de influencia ----------------
        gb_radio = QGroupBox("4. Radio de influencia")
        f_radio = QFormLayout(gb_radio)
        f_radio.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.spin_sw_radio = QDoubleSpinBox(); self.spin_sw_radio.setRange(0.01, 500); self.spin_sw_radio.setDecimals(3); self.spin_sw_radio.setValue(2.0)
        f_radio.addRow("sw — abatimiento en el pozo (m):", self.spin_sw_radio)
        self.spin_k_radio = QDoubleSpinBox(); self.spin_k_radio.setRange(1e-8, 1.0); self.spin_k_radio.setDecimals(7); self.spin_k_radio.setValue(0.0001)
        f_radio.addRow("K — conductividad hidráulica (m/s):", self.spin_k_radio)
        self.spin_h_radio = QDoubleSpinBox(); self.spin_h_radio.setRange(0.1, 1000); self.spin_h_radio.setDecimals(2); self.spin_h_radio.setValue(15.0)
        f_radio.addRow("H — espesor saturado antes del bombeo (m, Kusakin):", self.spin_h_radio)
        self.chk_usar_theis_radio = QCheckBox("Incluir radio de Theis (usa T, S, t de la sección 2)")
        self.chk_usar_theis_radio.setChecked(True)
        f_radio.addRow(self.chk_usar_theis_radio)
        self.chk_usar_prueba_radio = QCheckBox("Incluir radio de prueba de bombeo (el más exacto)")
        f_radio.addRow(self.chk_usar_prueba_radio)
        self.spin_s_prueba_radio = QDoubleSpinBox(); self.spin_s_prueba_radio.setRange(0.001, 500); self.spin_s_prueba_radio.setDecimals(3); self.spin_s_prueba_radio.setValue(0.5)
        f_radio.addRow("s medido en un pozo de observación a distancia r (sección 1, m):", self.spin_s_prueba_radio)
        btn_calcular_radios = QPushButton("Calcular y comparar radios de influencia")
        btn_calcular_radios.clicked.connect(self._on_calcular_radios_influencia)
        limitar_ancho_boton(btn_calcular_radios)
        f_radio.addRow(btn_calcular_radios)
        v.addWidget(gb_radio)
        self.canvas_comparacion_radios = WellCanvas(width=7.6, height=4.4)
        v.addWidget(self.canvas_comparacion_radios)

        v.addWidget(QLabel("<b>Cuadro resumen final:</b>"))
        self.texto_resumen_pozo = QTextBrowser()
        self.texto_resumen_pozo.setMinimumHeight(180)
        v.addWidget(self.texto_resumen_pozo)

        self._agregar_pestaña_con_scroll(tab, "19. Hidráulica de Pozos")

    def _on_calcular_regimen_permanente(self):
        try:
            confinado = self.combo_tipo_acuifero_pozo.currentIndex() == 0
            calcular_caudal = self.combo_modo_permanente.currentIndex() == 0
            q = self.spin_q_permanente.value()
            valor = self.spin_t_o_k_permanente.value()
            r1, r2 = self.spin_r1_permanente.value(), self.spin_r2_permanente.value()
            v1, v2 = self.spin_s1_h1_permanente.value(), self.spin_s2_h2_permanente.value()

            if confinado:
                if calcular_caudal:
                    ds = well_hydraulics.descenso_diferencial_thiem_confinado(q, valor, r1, r2)
                    self.texto_resultado_permanente.setText(f"s1-s2 = {ds:.4f} m (con T = {valor:.5f} m²/s)")
                    self.resultado_pozo["T_thiem"] = valor
                else:
                    t = well_hydraulics.transmisividad_thiem_confinado(q, v1, v2, r1, r2)
                    self.texto_resultado_permanente.setText(f"T = {t:.6f} m²/s")
                    self.spin_t_theis.setValue(t)
                    self.resultado_pozo["T_thiem"] = t
            else:
                if calcular_caudal:
                    q_calc = well_hydraulics.caudal_dupuit_thiem_libre(valor, v1, v2, r1, r2)
                    self.texto_resultado_permanente.setText(f"Q = {q_calc:.5f} m³/s (con K = {valor:.6f} m/s)")
                    self.resultado_pozo["K_dupuit"] = valor
                else:
                    k = well_hydraulics.conductividad_dupuit_thiem_libre(q, v1, v2, r1, r2)
                    self.texto_resultado_permanente.setText(f"K = {k:.7f} m/s")
                    self.spin_k_radio.setValue(k)
                    self.resultado_pozo["K_dupuit"] = k
            self._actualizar_texto_resumen_pozo()
        except well_hydraulics.WellHydraulicsError as e:
            QMessageBox.warning(self, "No se pudo calcular", str(e))

    def _on_calcular_theis(self):
        try:
            q = self.spin_q_theis.value()
            t = self.spin_t_theis.value()
            s = self.spin_s_theis.value()
            r = self.spin_r_theis.value()
            t_max = self.spin_t_max_theis.value()
            tiempos = np.logspace(math.log10(t_max / 1000.0), math.log10(t_max), 60)
            descensos = [well_hydraulics.descenso_theis(q, t, s, r, float(ti))["s_m"] for ti in tiempos]
            self.canvas_theis.plot_descenso_tiempo(tiempos.tolist(), descensos)
            self.resultado_pozo["theis"] = {"tiempos": tiempos.tolist(), "descensos": descensos, "Q": q, "T": t, "S": s, "r": r}
            self._actualizar_texto_resumen_pozo()
        except well_hydraulics.WellHydraulicsError as e:
            QMessageBox.warning(self, "No se pudo calcular", str(e))

    def _on_ajustar_cooper_jacob(self):
        tiempos, descensos = [], []
        for i in range(self.tabla_cooper_jacob.rowCount()):
            item_t = self.tabla_cooper_jacob.item(i, 0)
            item_s = self.tabla_cooper_jacob.item(i, 1)
            if item_t and item_s and item_t.text().strip():
                try:
                    tiempos.append(float(item_t.text().replace(",", ".")))
                    descensos.append(float(item_s.text().replace(",", ".")))
                except ValueError:
                    continue
        if len(tiempos) < 3:
            QMessageBox.warning(self, "Faltan datos", "Ingrese al menos 3 pares tiempo-descenso.")
            return
        try:
            q = self.spin_q_theis.value()
            r = self.spin_r_theis.value()
            ajuste = well_hydraulics.ajustar_cooper_jacob(tiempos, descensos, q, r)
            self.canvas_cooper_jacob.plot_cooper_jacob(tiempos, descensos, ajuste["t0_s"], ajuste["pendiente"],
                                                        -ajuste["pendiente"] * math.log10(ajuste["t0_s"]))
            self.spin_t_theis.setValue(ajuste["T_m2s"])
            self.spin_s_theis.setValue(ajuste["S"])
            self.resultado_pozo["cooper_jacob"] = ajuste
            QMessageBox.information(self, "Cooper-Jacob ajustado",
                                     f"T = {ajuste['T_m2s']:.6f} m²/s, S = {ajuste['S']:.6f}\n"
                                     "(valores cargados automáticamente en la sección 2 para Theis/radio de influencia)")
            self._actualizar_texto_resumen_pozo()
        except well_hydraulics.WellHydraulicsError as e:
            QMessageBox.warning(self, "No se pudo ajustar", str(e))

    def _on_ajustar_perdidas_pozo(self):
        caudales, descensos = [], []
        for i in range(self.tabla_ensayo_escalonado.rowCount()):
            item_q = self.tabla_ensayo_escalonado.item(i, 0)
            item_s = self.tabla_ensayo_escalonado.item(i, 1)
            if item_q and item_s and item_q.text().strip():
                try:
                    caudales.append(float(item_q.text().replace(",", ".")))
                    descensos.append(float(item_s.text().replace(",", ".")))
                except ValueError:
                    continue
        if len(caudales) < 2:
            QMessageBox.warning(self, "Faltan datos", "Ingrese al menos 2 escalones de caudal.")
            return
        try:
            ajuste = well_hydraulics.ajustar_perdidas_pozo(caudales, descensos)
            self.canvas_ensayo_escalonado.plot_ensayo_escalonado(caudales, descensos, ajuste["B"], ajuste["C"])
            q_diseno = self.spin_q_diseno_perdidas.value()
            perdidas = well_hydraulics.perdidas_pozo(ajuste["B"], ajuste["C"], q_diseno)
            self.texto_resultado_perdidas.setText(
                f"B = {ajuste['B']:.2f} s/m² | C = {ajuste['C']:.2f} s²/m⁵ — "
                f"a Q={q_diseno:.4f} m³/s: pérdida acuífero = {perdidas['perdida_acuifero_m']:.3f} m, "
                f"pérdida pozo = {perdidas['perdida_pozo_m']:.3f} m, sw total = {perdidas['sw_total_m']:.3f} m, "
                f"eficiencia = {perdidas['eficiencia_pct']:.1f}%")
            self.resultado_pozo["perdidas"] = {**ajuste, **perdidas, "Q_diseno": q_diseno}
            if self.chk_usar_theis_radio.isChecked() or True:
                self.spin_sw_radio.setValue(perdidas["sw_total_m"])
            self._actualizar_texto_resumen_pozo()
        except well_hydraulics.WellHydraulicsError as e:
            QMessageBox.warning(self, "No se pudo ajustar", str(e))

    def _on_calcular_radios_influencia(self):
        try:
            sw = self.spin_sw_radio.value()
            k = self.spin_k_radio.value()
            h = self.spin_h_radio.value()
            resultados = {
                "Sichardt": well_hydraulics.radio_influencia_sichardt(sw, k),
                "Kusakin": well_hydraulics.radio_influencia_kusakin(sw, h, k),
            }
            hay_theis, hay_prueba = False, False
            if self.chk_usar_theis_radio.isChecked() and self.resultado_pozo.get("theis"):
                th = self.resultado_pozo["theis"]
                resultados["Theis"] = well_hydraulics.radio_influencia_theis(th["T"], th["tiempos"][-1], th["S"])
                hay_theis = True
            if self.chk_usar_prueba_radio.isChecked():
                t_disponible = self.resultado_pozo.get("cooper_jacob", {}).get("T_m2s") or self.resultado_pozo.get("T_thiem")
                if t_disponible:
                    resultados["Prueba de bombeo"] = well_hydraulics.radio_influencia_prueba_bombeo(
                        t_disponible, self.spin_q_theis.value(), self.spin_r_theis.value(), self.spin_s_prueba_radio.value())
                    hay_prueba = True
                else:
                    QMessageBox.warning(self, "Falta T",
                                         "Calcule T primero (Thiem en la sección 1, o Cooper-Jacob en la sección 2).")

            mejor = well_hydraulics.seleccionar_mejor_radio_influencia(resultados, hay_prueba, hay_theis)
            self.canvas_comparacion_radios.plot_comparacion_radios(
                list(resultados.keys()), list(resultados.values()), mejor.get("metodo_recomendado"))
            self.resultado_pozo["radios"] = {"resultados": resultados, "mejor": mejor}
            self._actualizar_texto_resumen_pozo()
        except well_hydraulics.WellHydraulicsError as e:
            QMessageBox.warning(self, "No se pudo calcular", str(e))

    def _actualizar_texto_resumen_pozo(self):
        r = self.resultado_pozo
        html = "<h3>Cuadro resumen final — Hidráulica de Pozos</h3>"
        if r.get("cooper_jacob"):
            cj = r["cooper_jacob"]
            html += f"<p><b>Cooper-Jacob:</b> T = {cj['T_m2s']:.6f} m²/s, S = {cj['S']:.6f}</p>"
        if r.get("perdidas"):
            p = r["perdidas"]
            html += (f"<p><b>Pérdidas de pozo:</b> B = {p['B']:.2f}, C = {p['C']:.2f} — "
                     f"a Q={p['Q_diseno']:.4f} m³/s: sw total = {p['sw_total_m']:.3f} m, "
                     f"eficiencia = {p['eficiencia_pct']:.1f}%</p>")
        if r.get("radios"):
            html += "<table border='1' cellpadding='4' cellspacing='0'><tr><th>Método</th><th>R (m)</th></tr>"
            for nombre, valor in r["radios"]["resultados"].items():
                html += f"<tr><td>{nombre}</td><td>{valor:.2f}</td></tr>"
            html += "</table>"
            mejor = r["radios"]["mejor"]
            html += (f"<p><b>Mejor propuesta: {mejor['metodo_recomendado']}</b> — "
                     f"R = {mejor['R_recomendado_m']:.2f} m<br>{mejor['motivo']}</p>")
        if not r:
            html += "<p>Aún no se ha calculado ninguna sección.</p>"
        html += ("<p style='color:#666666'>NOTA: la función de pozo W(u) se calculó con las aproximaciones "
                 "racionales estándar de Abramowitz & Stegun, verificadas contra scipy.special.exp1 con "
                 "error prácticamente nulo en todo el rango.</p>")
        self.texto_resumen_pozo.setHtml(html)

    # ------------------------------------------------------------------
    # TAB 20 (penúltima, antes de Créditos): Exportar / Reportes
    # ------------------------------------------------------------------
    def _build_tab_exportacion(self):
        tab = QWidget()
        v = QVBoxLayout(tab)

        _lbl_auto_43 = QLabel(
            "<b>Exportar / Reportes</b> — todas las exportaciones de resultados de las pestañas 1 "
            "a 7 quedan centralizadas aquí, en un solo lugar. Cada botón reúne los resultados "
            "calculados hasta el momento en la sesión actual (lo que aún no se haya calculado en "
            "alguna pestaña simplemente se omite de esa sección)."
        )
        _lbl_auto_43.setWordWrap(True)
        v.addWidget(_lbl_auto_43)

        gb_completo = QGroupBox(
            "Exportación completa (recomendado) — reporte descriptivo en Word, archivos nativos/"
            "editables (Excel y demás), y proyecto portable para abrir en otra máquina"
        )
        v_c = QVBoxLayout(gb_completo)

        h1 = QHBoxLayout()
        self.btn_generar_reporte_word = QPushButton("Generar reporte Word completo (pestañas 1-7)")
        self.btn_generar_reporte_word.clicked.connect(self._on_generar_reporte_word)
        h1.addWidget(self.btn_generar_reporte_word)
        v_c.addLayout(h1)

        h2 = QHBoxLayout()
        self.btn_exportar = QPushButton("Exportar todo — archivos nativos/editables (SHP/KML/GeoJSON/TIF/XLSX/CSV)")
        self.btn_exportar.clicked.connect(self._on_exportar_todo)
        h2.addWidget(self.btn_exportar)
        v_c.addLayout(h2)

        h3 = QHBoxLayout()
        self.btn_guardar_proyecto_portable = QPushButton(
            "Guardar proyecto portable (capas + reporte Word + Excel, para abrir en otra máquina)"
        )
        self.btn_guardar_proyecto_portable.clicked.connect(self._on_guardar_proyecto_portable)
        h3.addWidget(self.btn_guardar_proyecto_portable)
        v_c.addLayout(h3)
        v.addWidget(gb_completo)

        gb_individual = QGroupBox("Exportaciones individuales")
        v_i = QVBoxLayout(gb_individual)
        h4 = QHBoxLayout()
        self.btn_exportar_hipsometrica = QPushButton("Exportar curva hipsométrica (PNG) — pestaña 4")
        self.btn_exportar_hipsometrica.clicked.connect(self._on_exportar_hipsometrica)
        h4.addWidget(self.btn_exportar_hipsometrica)
        v_i.addLayout(h4)
        v.addWidget(gb_individual)

        v.addStretch()
        self._agregar_pestaña_con_scroll(tab, "20. Exportar / Reportes")

    # ------------------------------------------------------------------
    # TAB 6: Créditos
    # ------------------------------------------------------------------
    def _build_tab6(self):
        tab = QWidget()
        v = QVBoxLayout(tab)
        v.addStretch()

        texto = QTextBrowser()
        texto.setOpenExternalLinks(True)
        texto.setHtml(
            """
            <div style="text-align:center; font-family: sans-serif;">
                <h2 style="color:#1F3864;">HydroAndes Pro</h2>
                <p style="font-size:11pt;">Plugin de análisis hidrológico integral de caudales máximos
                para cuencas andinas del Perú.</p>
                <p style="font-size:9pt; color:#888;">Versión 0.2.6</p>
                <hr>
                <p style="font-size:12pt; margin-top:20px;"><b>Ningsiar Braulio Lima Usnayo</b></p>
                <p style="font-size:10pt; color:#444;">
                    Ing. Civil / M.Sc. Hydrology and Water Research Management /<br>
                    Mg (C). Ing. Civil con mención en Hidráulica y Medio Ambiente /<br>
                    Ph.D. (C) Computational Hydraulics
                </p>
                <p style="font-size:10pt; color:#444; margin-top:6px;">
                    Catedrático en la Maestría en Recursos Hídricos, EPG Ing. Civil – UNSAAC
                </p>
                <p style="font-size:9pt; color:#666; margin-top:8px;">
                    ningsiar.lima@unsaac.edu.pe / ningsiar.lima@edu.uah.es &nbsp;·&nbsp; GitHub: @Ningsiar
                </p>
                <p style="margin-top:16px; font-size:9pt; color:#666;">
                    Desarrollo del motor hidrológico y de la interfaz del plugin,<br>
                    para CORPORATIVO CONSTRUCTIVO LIMA BERLÍN SRL.
                </p>
                <p style="margin-top:12px; font-size:9pt; color:#888;">
                    Cusco, Agosto 2026
                </p>
            </div>
            """
        )
        v.addWidget(texto)
        v.addStretch()
        self._agregar_pestaña_con_scroll(tab, "Créditos")

    # ------------------------------------------------------------------
    # Exportación
    # ------------------------------------------------------------------
    def _construir_contexto_reporte(self, carpeta_temporal_imagenes: str) -> dict:
        """Reúne en un solo dict todos los resultados calculados hasta el
        momento en las 7 pestañas, más las rutas a los gráficos ya
        dibujados en la interfaz (exportados a PNG en
        carpeta_temporal_imagenes), listo para pasar a
        core.report_generator.generar_reporte_word() y a
        core.project_export.guardar_proyecto_portable()."""
        os.makedirs(carpeta_temporal_imagenes, exist_ok=True)
        rutas_imagenes = {}

        def _guardar(nombre_atributo_canvas, clave):
            canvas = getattr(self, nombre_atributo_canvas, None)
            if canvas is not None and hasattr(canvas, "fig"):
                try:
                    ruta = os.path.join(carpeta_temporal_imagenes, f"{clave}.png")
                    canvas.fig.savefig(ruta, dpi=200, bbox_inches="tight")
                    rutas_imagenes[clave] = ruta
                except Exception:
                    pass

        _guardar("canvas_hipsometrica", "hipsometrica")
        _guardar("canvas_cav", "cav")
        _guardar("canvas_frecuencia", "frecuencia")
        _guardar("canvas_comparacion_tr", "comparacion_tr")
        _guardar("canvas_comparacion_tr_cartesiano", "comparacion_tr_cartesiano")
        _guardar("canvas_hidrograma", "hidrograma")

        return {
            "nombre_cuenca": self.nombre_cuenca_activa or "(sin nombre)",
            "break_point_xy": self.break_point_xy,
            "morfometria_resultados": self.morfometria_resultados,
            "resultado_cav": self.resultado_cav,
            "cn_resultados": self.cn_resultados,
            "desglose_cn": [
                {"lulc_nombre": self.tabla_desglose_cn_auto.item(r, 0).text() if self.tabla_desglose_cn_auto.item(r, 0) else "",
                 "hsg": self.tabla_desglose_cn_auto.item(r, 1).text() if self.tabla_desglose_cn_auto.item(r, 1) else "",
                 "area_km2": self.tabla_desglose_cn_auto.item(r, 2).text() if self.tabla_desglose_cn_auto.item(r, 2) else "",
                 "cn": self.tabla_desglose_cn_auto.item(r, 3).text() if self.tabla_desglose_cn_auto.item(r, 3) else ""}
                for r in range(self.tabla_desglose_cn_auto.rowCount())
            ] if hasattr(self, "tabla_desglose_cn_auto") and self.tabla_desglose_cn_auto.rowCount() else None,
            "tc_resultados": self.tc_resultados,
            "resultados_frecuencia": self.resultados_frecuencia,
            "mejor_ajuste_clave": self.mejor_ajuste_clave,
            "p24_disenio": self.p24_disenio,
            "hidrograma_resultado": self.hidrograma_resultado,
            "resultados_hidraulica_drenaje": self.resultados_hidraulica_drenaje,
            "rutas_imagenes": rutas_imagenes,
        }

    def _on_generar_reporte_word(self):
        ruta, _ = QFileDialog.getSaveFileName(self, "Guardar reporte Word", "reporte_hydroandes.docx",
                                               "Documento Word (*.docx)")
        if not ruta:
            return
        try:
            carpeta_tmp = tempfile.mkdtemp(prefix="hydroandina_reporte_")
            contexto = self._construir_contexto_reporte(carpeta_tmp)
            report_generator.generar_reporte_word(ruta, contexto)
            QMessageBox.information(self, "Reporte generado", f"Reporte Word guardado en:\n{ruta}")
        except report_generator.ReportGeneratorError as e:
            QMessageBox.warning(self, "python-docx no disponible", str(e))
        except Exception as e:
            QMessageBox.critical(self, "Error generando el reporte Word", str(e))

    def _on_guardar_proyecto_portable(self):
        carpeta = QFileDialog.getExistingDirectory(
            self, "Seleccionar carpeta donde crear el proyecto portable"
        )
        if not carpeta:
            return
        try:
            carpeta_tmp = tempfile.mkdtemp(prefix="hydroandina_reporte_")
            contexto = self._construir_contexto_reporte(carpeta_tmp)
            nombre_proyecto = (self.nombre_cuenca_activa or "proyecto_hydroandes").replace(" ", "_")

            capas_extra = {}
            # Si se calculó CN automático (Curve Number Generator), su capa
            # vectorizada ya quedó añadida al proyecto de QGIS; se busca
            # por nombre para incluirla también en el paquete portable.
            for capa in QgsProject.instance().mapLayers().values():
                if capa.name() == "cn_vectorizado":
                    capas_extra["cn_vectorizado"] = capa
                    break

            resultado = project_export.guardar_proyecto_portable(
                carpeta, nombre_proyecto,
                cuenca_layer=self.cuenca_layer, red_drenaje_layer=self.red_drenaje_layer,
                dem_clip_path=self.dem_clip_path, capas_extra=capas_extra,
                contexto_reporte=contexto,
            )
            mensaje = f"Proyecto portable guardado en:\n{carpeta}\n\n"
            mensaje += f"- Proyecto QGIS: {os.path.basename(resultado.get('proyecto_qgz', ''))}\n"
            if resultado.get("reporte_docx"):
                mensaje += f"- Reporte Word: {os.path.basename(resultado['reporte_docx'])}\n"
            if resultado.get("resultados_xlsx"):
                mensaje += f"- Excel de resultados: {os.path.basename(resultado['resultados_xlsx'])}\n"
            mensaje += f"- {len(resultado.get('capas', []))} archivos de capas en la subcarpeta 'capas/'\n"
            if resultado.get("advertencias"):
                mensaje += "\nAdvertencias (no fatales):\n- " + "\n- ".join(resultado["advertencias"])
            QMessageBox.information(self, "Proyecto portable guardado", mensaje)
        except Exception as e:
            QMessageBox.critical(self, "Error guardando el proyecto portable", str(e))

    def _on_exportar_todo(self):
        carpeta = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta de exportación")
        if not carpeta:
            return
        try:
            rutas_generadas = []

            if self.cuenca_layer is not None:
                r = exporters.exportar_vector(self.cuenca_layer, os.path.join(carpeta, "cuenca"))
                rutas_generadas.extend(r.values())
            if self.red_drenaje_layer is not None:
                r = exporters.exportar_vector(self.red_drenaje_layer, os.path.join(carpeta, "red_drenaje"))
                rutas_generadas.extend(r.values())
            if self.dem_clip_path:
                ruta_tif = os.path.join(carpeta, "mde_cuenca.tif")
                exporters.exportar_raster_tif(QgsRasterLayer(self.dem_clip_path, "dem_clip"), ruta_tif)
                rutas_generadas.append(ruta_tif)

            tablas = {}
            if self.morfometria_resultados:
                filas = []
                for grupo_key in ("g1", "g2", "g5", "g6"):
                    grupo = self.morfometria_resultados.get(grupo_key, {})
                    for k, val in grupo.items():
                        if k == "interpretacion":
                            continue
                        filas.append({"grupo": grupo_key, "parametro": k, "valor": val})
                tablas["morfometria"] = filas
            if self.cn_resultados:
                tablas["curve_number"] = [self.cn_resultados]
            if self.tc_resultados:
                tablas["tiempo_concentracion"] = [
                    {"metodo": k, **{kk: vv for kk, vv in v.items()}} for k, v in self.tc_resultados.items()
                ]
            if self.hidrograma_resultado:
                tablas["hidrograma_crecida"] = [
                    {"tiempo_h": t, "caudal_m3s": q}
                    for t, q in zip(self.hidrograma_resultado["tiempos_h"], self.hidrograma_resultado["caudal_m3s"])
                ]
            if self.resultados_frecuencia:
                tablas["ajuste_distribuciones_precipitacion"] = [
                    {"distribucion": r["nombre"], "D_ks": r["D_ks"], "D_critico": r["D_critico"],
                     "pasa_ks": r["pasa_ks"], **r["parametros"]}
                    for r in self.resultados_frecuencia.values() if not r["error"]
                ]
            if self.p24_disenio:
                tablas["precipitaciones_diseno_p24"] = [
                    {"periodo_retorno_anios": tr, "p24_mm": p} for tr, p in self.p24_disenio.items()
                ]

            if tablas:
                rutas_generadas.extend(exporters.exportar_tablas_csv(tablas, carpeta))
                try:
                    ruta_xlsx = exporters.exportar_tablas_excel(tablas, os.path.join(carpeta, "resultados.xlsx"))
                    rutas_generadas.append(ruta_xlsx)
                except RuntimeError as e:
                    QMessageBox.warning(self, "Excel no generado", str(e))

            QMessageBox.information(self, "Exportación completa",
                                     f"Se generaron {len(rutas_generadas)} archivos en:\n{carpeta}")
        except Exception as e:
            QMessageBox.critical(self, "Error exportando resultados", str(e))
