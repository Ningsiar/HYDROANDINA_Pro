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

try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as _FigureCanvasQTAgg
except ImportError:
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as _FigureCanvasQTAgg

from qgis.core import (
    QgsProject, QgsMapLayerProxyModel, QgsCoordinateReferenceSystem,
    QgsCoordinateTransform, QgsPointXY, QgsGeometry, QgsWkbTypes,
    QgsProcessingContext, QgsProcessingFeedback, QgsRasterLayer, QgsVectorLayer,
    QgsFeature, QgsField,
)
from qgis.gui import QgsMapLayerComboBox, QgsMapToolEmitPoint
from qgis.PyQt.QtCore import Qt, QVariant
from qgis.PyQt.QtGui import QFont, QColor, QMovie
from qgis.PyQt.QtWidgets import (
    QDialog, QTabWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLabel, QLineEdit, QPushButton, QSpinBox, QDoubleSpinBox, QComboBox,
    QTableWidget, QTableWidgetItem, QFileDialog, QMessageBox, QRadioButton,
    QButtonGroup, QCheckBox, QWidget, QHeaderView, QPlainTextEdit, QTextBrowser,
    QApplication, QScrollArea, QStackedWidget, QFrame, QGridLayout, QProgressBar,
)

from .core import (delineation, morphometry, curve_number, tc_methods, dem_download,
                    exporters, raster_stats, unit_hydrographs, frequency_analysis,
                    design_storm, precip_source, scs_storm_patterns, pour_point_snap,
                    main_channel, landcover_soils, dem_download_asf, hydraulic_structures,
                    cn_generator_bridge, report_generator, report_generator_docxtpl, project_export,
                    quality_control, pmp_hershfield, direct_discharge_methods, flood_routing, baseflow, infiltration,
                    data_completion, areal_precipitation, water_yield, scour, soil_loss,
                    sediment_transport, debris_flow, climate_change, mean_flow_models, etp_methods,
                    low_flows, phabsim, groundwater_flow, well_hydraulics, idf_curves,
                    regionalization, gridded_validation, swe2d, mesh_export,
                    runoff_coefficient, roughness_methods, roughness_materials)
from .core.qgis_layer_utils import obtener_capa
from .ui.hypsometric_canvas import HypsometricCanvas
from .ui.hydrograph_canvas import HydrographCanvas
from .ui.frequency_canvas import FrequencyCanvas, DiagnosticoDistribucionCanvas
from .ui.idf_canvas import IdfCanvas
from .ui.infiltration_canvas import InfiltrationCanvas
from .ui.summary_box import CuadroResumenImpacto, ResumenFinal, centrar_en_layout
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
from .ui.regionalization_canvas import RegionalizacionCanvas, ValidacionGrilladaCanvas
from .ui.swe2d_canvas import (MapaCalado2DCanvas, MapaPeligrosidadCanvas,
                               HidrogramasSwe2DCanvas, PerfilSwe2DCanvas,
                               TerrenoCalado3DCanvas)
from .ui.swe2d_runner import SimulacionSwe2DWorker, estimar_coste
from .ui import swe2d_animation
from .ui.table_utils import (ajustar_alto_tabla, aplicar_columna_elastica, limitar_ancho_tabla,
                              limitar_ancho_boton, crear_tabla_parametros, poblar_tabla_parametros)
from .ui import export_overlay


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

# Símbolo griego + descripción breve de cada parámetro de las 9
# distribuciones de probabilidad ajustadas en la Pestaña 5 (columna
# "Parámetros" de tabla_distribuciones), indexado por (clave de la
# distribución -- las mismas de core.frequency_analysis.
# DISTRIBUCIONES_DISPONIBLES --, clave interna del parámetro en
# DistribucionAjustada.parametros). Antes se mostraban tal cual las
# claves en código ("mu", "sigma", "alpha"...) sin indicar qué
# representa cada una -- y "alpha"/"u" significan cosas DISTINTAS según
# la distribución (p.ej. alpha es forma en Gamma, pero escala en Gumbel
# y GEV), así que el mapeo es por distribución, no global.
SIMBOLOS_PARAMETROS_DISTRIBUCION = {
    "normal": {"mu": "μ (media)", "sigma": "σ (desviación estándar)"},
    "lognormal2": {"mu_log": "μ (media de ln X)", "sigma_log": "σ (desv. estándar de ln X)"},
    "lognormal3": {"x0": "x₀ (límite inferior)", "mu_log": "μ (media de ln(X−x₀))",
                   "sigma_log": "σ (desv. estándar de ln(X−x₀))"},
    "gumbel": {"u": "u (posición/moda)", "alpha": "α (escala)"},
    "loggumbel": {"u_log": "u (posición de ln X)", "alpha_log": "α (escala de ln X)"},
    "gamma2": {"alpha": "α (forma)", "beta": "β (escala)"},
    "gamma3_pearson3": {"media": "x̄ (media)", "s": "S (desviación estándar)",
                         "sesgo": "Cs (coeficiente de asimetría)"},
    "logpearson3": {"media_log10": "x̄ (media de log₁₀X)", "s_log10": "S (desv. estándar de log₁₀X)",
                     "sesgo_log10": "Cs (sesgo de log₁₀X)"},
    "gev": {"xi": "ξ (posición)", "alpha": "α (escala)", "kappa": "κ (forma)"},
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


class Swe2DEntradaInvalida(Exception):
    """Datos incompletos o mal formados en las tablas de la Pestaña 8.
    Se distingue de un error del solver para poder avisar al usuario con
    un mensaje que le diga qué corregir, en vez de un volcado tecnico."""


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
        self.metodo_ajuste_usado = "momentos_l"
        self.transito_resultado = {}
        self.bandas_confianza_resultado = {}
        self.flujo_base_resultado = {}
        self.no_estacionario_resultado = {}
        self.infiltracion_resultado = {}
        self.cuadros_infiltracion = {}
        self.canvas_por_metodo_infiltracion = {}
        self.resultados_infiltracion_por_metodo = {}
        self.p24_disenio = {}
        self.periodos_retorno_actuales = []
        self.idf_resultados = {}  # curvas/ecuaciones IDF derivadas de p24_disenio (pestaña 5)
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
        self.capa_estructuras_2d = None   # capa de líneas (memoria) de estructuras 2D insertadas desde el mapa (item 8)
        self._primer_clic_estructura_2d = None
        self.map_tool_estructura_2d = None
        self._primer_clic_corte_2d = None
        self.map_tool_corte_2d = None

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self._build_tab1()
        self._build_tab2()
        self._build_tab3()
        self._build_tab4()
        self._build_tab_precipitacion()
        self._build_tab5()
        self._build_tab_hidraulica_drenaje()
        self._build_tab_simulacion_2d()
        self._build_tab_modulos_avanzados()
        self._build_tab_socavacion()
        self._build_tab_perdida_suelos()
        self._build_tab_sedimentos()
        self._build_tab_flujos_hiperconcentrados()
        self._build_tab_cambio_climatico()
        # Precipitacion Media Mensual se ubica junto al bloque de caudales
        # medios/minimos/ecologico, que es donde se consume, en vez de
        # partir la secuencia del diseño de avenidas (Pestañas 5-8).
        self._build_tab_precipitacion_mensual()
        self._build_tab_caudales_medios()
        self._build_tab_caudales_minimos()
        self._build_tab_phabsim()
        self._build_tab_flujo_subterraneo()
        self._build_tab_hidraulica_pozos()
        self._build_tab_exportacion()
        self._build_tab6()

        # Item 9 del pedido: "todas las tablas, gráficos y cuadros de
        # resumen final deben tener un botón de descarga". En vez de
        # tocar cada uno de los ~21 métodos _build_tab*() de arriba, se
        # recorre el diálogo YA CONSTRUIDO una sola vez y se le agrega el
        # botón flotante a cada tabla/gráfico/resumen encontrado (ver
        # _habilitar_descargas_universales).
        self._habilitar_descargas_universales()

    def _habilitar_descargas_universales(self):
        """Agrega el botón flotante de descarga (Excel/CSV/copiar en
        tablas; PNG/JPG en gráficos; copiar/TXT/HTML en cuadros de
        resumen) a TODO lo que ya esté construido en el diálogo. Cubre
        las ~21 pestañas de una sola vez -- y cualquier tabla/gráfico que
        se agregue después, con solo llamar esto de nuevo."""
        for tabla in self.findChildren(QTableWidget):
            nombre = tabla.objectName() or "tabla"
            export_overlay.agregar_boton_descarga_tabla(tabla, nombre_base=nombre)
        for canvas in self.findChildren(_FigureCanvasQTAgg):
            export_overlay.agregar_boton_descarga_grafico(canvas, nombre_base="grafico")
        for texto in self.findChildren(ResumenFinal):
            export_overlay.agregar_boton_descarga_texto(texto, nombre_base="resumen")
        for cuadro in self.findChildren(CuadroResumenImpacto):
            export_overlay.agregar_boton_descarga_texto(cuadro, nombre_base="resumen_impacto")

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

        # --- Relleno de celdas SIN DATO (voids) del MDE ---
        self.check_rellenar_nodata = QCheckBox(
            "Rellenar las celdas SIN DATO del MDE antes de procesar (recomendado)")
        self.check_rellenar_nodata.setChecked(True)
        f4.addRow(self.check_rellenar_nodata)
        lbl_nodata = QLabel(
            "Los MDE descargados (SRTM, ASTER, Copernicus) traen huecos sin dato por sombra de radar o "
            "nubosidad, frecuentes justo en terreno abrupto como el altoandino. <b>No es lo mismo que "
            "el relleno de sumideros</b> que el plugin ya hace: aquel elimina depresiones cerradas "
            "(celdas CON dato más bajas que sus vecinas) para que el flujo no quede atrapado, pero no "
            "toca los huecos vacíos. Sin rellenarlos, la dirección de flujo no puede propagarse a "
            "través de ellos, la cuenca sale recortada o partida, y las cotas y pendientes se calculan "
            "sobre una muestra con agujeros.<br><br>"
            "<b>Tenga presente que el relleno INTERPOLA</b>, es decir, estima cotas donde no las hay: "
            "en esas celdas el resultado no es una medición. El plugin le informa qué porcentaje del "
            "MDE estaba vacío y cuánto se rellenó, para que pueda juzgarlo."
        )
        lbl_nodata.setWordWrap(True)
        f4.addRow(lbl_nodata)
        self.spin_nodata_distancia = QSpinBox()
        self.spin_nodata_distancia.setRange(1, 2000)
        self.spin_nodata_distancia.setValue(100)
        f4.addRow("Radio máximo de búsqueda para interpolar (celdas):", self.spin_nodata_distancia)
        self.spin_nodata_suavizado = QSpinBox()
        self.spin_nodata_suavizado.setRange(0, 20)
        self.spin_nodata_suavizado.setValue(2)
        f4.addRow("Pasadas de suavizado del parche (evita bordes artificiales):",
                   self.spin_nodata_suavizado)

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

            dem_layer, self.diagnostico_nodata = self._rellenar_nodata_si_procede(
                dem_layer, context, feedback)
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
                region=resultado_flujo["region"], cellsize=resultado_flujo.get("cellsize"),
                context=context, feedback=feedback,
            )
            capa_red = obtener_capa(resultado_red["red_drenaje_vector"], context, es_raster=False, nombre="red_drenaje_stream_network")
            QgsProject.instance().addMapLayer(capa_red)
            # El Paso A tambien produce una red medible: se vuelca a la
            # Pestaña 2 sin esperar a delimitar la cuenca, para que quien
            # solo genere la red ya tenga Lt y Nu reales en vez de los
            # minimos del rango.
            self.red_drenaje_layer = capa_red
            self._autocompletar_red_drenaje_pestana2()
            self.resultado_flujo_paso_a = resultado_flujo  # guardar para reutilizar en el Paso B
            # Se guarda tambien el CRS en que se calculo: el Paso B solo puede
            # reutilizarlo si coincide con el suyo (ver la nota en _on_run_delineation).
            self.crs_flujo_paso_a = dem_layer.crs().authid()
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

    def _autocompletar_red_drenaje_pestana2(self):
        """
        Mide la red de drenaje delineada y rellena Lt (longitud total) y Nu
        (número de cauces) de la Pestaña 2.

        Lt se obtiene sumando la longitud de TODAS las entidades de la capa
        de red, y Nu contando esas entidades. Ambos se miden en el CRS de
        la capa, que a estas alturas de la cadena ya es la zona UTM local
        (metros), de modo que la longitud es métrica y no angular -- medir
        en grados daría un número sin sentido físico.

        Si la medición falla por cualquier motivo, se deja el valor que
        hubiera y no se interrumpe la delimitación: es una comodidad, no un
        paso crítico de la cadena.
        """
        capa = getattr(self, "red_drenaje_layer", None)
        if capa is None or not capa.isValid():
            return None
        try:
            longitud_total_m = 0.0
            n_cauces = 0
            for entidad in capa.getFeatures():
                geometria = entidad.geometry()
                if geometria is None or geometria.isEmpty():
                    continue
                longitud_total_m += geometria.length()
                n_cauces += 1
            if n_cauces == 0:
                return None

            lt_km = longitud_total_m / 1000.0
            self.spin_lt_km.setValue(lt_km)
            self.spin_n_cauces.setValue(n_cauces)
            # Lc (cauce principal) ya lo calcula la cadena de delimitación;
            # se traslada aquí para no dejar el único campo restante en su
            # mínimo mientras los otros dos quedan medidos.
            lc_km = (self.morfometria_resultados or {}).get("lc_km")
            if lc_km:
                self.spin_lc_km.setValue(lc_km)

            self.lbl_estado_tab1.setText(
                f"Red de drenaje medida: Lt = {lt_km:.3f} km en {n_cauces} cauces "
                "(volcado a la Pestaña 2)."
            )
            return {"lt_km": lt_km, "n_cauces": n_cauces}
        except Exception:
            return None

    def _zona_utm_desde_capa(self, capa):
        """
        Zona UTM que corresponde al CENTRO de una capa, devuelta como
        (QgsCoordinateReferenceSystem, lon, lat).

        POR QUÉ EXISTE (v0.2.57): la zona se derivaba solo de la longitud
        del punto clicado. Si esa longitud sale mal por cualquier motivo
        (un CRS de proyecto inconsistente, un punto cargado desde un
        archivo con CRS mal declarado, o un cambio de CRS entre el clic y
        el cálculo), TODA la cadena se ejecuta en una zona equivocada y
        los síntomas aparecen mucho más abajo y sin relación aparente con
        la causa -- se observó un caso real en el que un MDE de Sicuani
        (lon -71.2, zona 19S) acabó reproyectado a la zona 3S, cuyo
        meridiano central está en -165° (en el Pacífico), produciendo
        eastings de 13 millones de metros y un "punto fuera del MDE" cuyo
        origen era imposible de adivinar desde el mensaje.
        El MDE es el dato autoritativo del análisis: su centro define sin
        ambigüedad la zona en la que hay que trabajar.
        """
        extent = capa.extent()
        centro = QgsPointXY(extent.center().x(), extent.center().y())
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        if capa.crs() != wgs84:
            centro = QgsCoordinateTransform(
                capa.crs(), wgs84, QgsProject.instance()).transform(centro)
        lon, lat = centro.x(), centro.y()
        zona = int((lon + 180) / 6) + 1
        epsg = (32700 if lat < 0 else 32600) + zona
        return QgsCoordinateReferenceSystem(f"EPSG:{epsg}"), lon, lat

    def _rellenar_nodata_si_procede(self, dem_layer, context, feedback):
        """
        Diagnostica los vacíos del MDE y los rellena si el usuario lo pidió.
        Devuelve la capa (rellenada o la original) y deja el informe en la
        barra de estado.

        Se informa SIEMPRE del porcentaje de vacíos, incluso cuando el
        relleno está desactivado: saber que el MDE tiene un 20% de huecos
        explica de antemano por qué la cuenca puede salir partida, en vez
        de dejar que el usuario lo descubra por un error posterior.
        """
        try:
            diag = delineation.diagnosticar_nodata(dem_layer)
        except Exception:
            return dem_layer, None  # el diagnóstico nunca debe bloquear el proceso

        if diag.get("advertencia"):
            self.lbl_estado_tab1.setText("Aviso: " + diag["advertencia"])
        if not diag["tiene_vacios"]:
            return dem_layer, diag
        if not self.check_rellenar_nodata.isChecked():
            QMessageBox.warning(
                self, "El MDE tiene celdas sin dato",
                f"El MDE tiene {diag['celdas_sin_dato']:,} celdas sin dato "
                f"({diag['porcentaje_sin_dato']:.2f}% del total) y el relleno está DESACTIVADO.\n\n"
                "La dirección de flujo no puede propagarse a través de esos huecos: la cuenca puede "
                "salir recortada o partida, y las cotas y pendientes se calcularán sobre una muestra "
                "incompleta. Active «Rellenar las celdas SIN DATO» en el paso 4."
            )
            return dem_layer, diag

        self.lbl_estado_tab1.setText(
            f"Rellenando {diag['celdas_sin_dato']:,} celdas sin dato "
            f"({diag['porcentaje_sin_dato']:.2f}% del MDE)...")
        ruta_rellenada = delineation.rellenar_nodata(
            dem_layer, distancia_maxima_px=self.spin_nodata_distancia.value(),
            iteraciones_suavizado=self.spin_nodata_suavizado.value(),
            context=context, feedback=feedback,
        )
        capa_rellenada = obtener_capa(ruta_rellenada, context, es_raster=True, nombre="mde_sin_vacios")

        diag_despues = delineation.diagnosticar_nodata(capa_rellenada)
        diag["porcentaje_tras_relleno"] = diag_despues["porcentaje_sin_dato"]
        diag["celdas_tras_relleno"] = diag_despues["celdas_sin_dato"]

        if diag_despues["tiene_vacios"]:
            # Quedan huecos: son más anchos que el radio de búsqueda.
            QMessageBox.warning(
                self, "Quedaron celdas sin dato tras el relleno",
                f"Se rellenaron {diag['celdas_sin_dato'] - diag_despues['celdas_sin_dato']:,} celdas, "
                f"pero aún quedan {diag_despues['celdas_sin_dato']:,} "
                f"({diag_despues['porcentaje_sin_dato']:.2f}%).\n\n"
                "Esos huecos son más anchos que el doble del radio de búsqueda. Aumente el «radio "
                "máximo de búsqueda para interpolar» en el paso 4 y vuelva a ejecutar, o consiga un "
                "MDE de mejor cobertura para la zona."
            )
        elif diag["porcentaje_sin_dato"] > 5.0:
            # Se rellenó todo, pero una fracción alta del MDE es ahora
            # interpolada: hay que decirlo antes de que se use en diseño.
            QMessageBox.warning(
                self, "Buena parte del MDE quedó interpolada",
                f"Se rellenaron todas las celdas sin dato, pero eran el "
                f"{diag['porcentaje_sin_dato']:.2f}% del MDE.\n\n"
                "Esa fracción de las cotas NO es una medición, sino una interpolación desde los bordes "
                "de los huecos. Los parámetros morfométricos y el caudal de diseño que se deriven "
                "heredan esa incertidumbre: verifique la cobertura del MDE antes de un diseño "
                "definitivo."
            )
        return capa_rellenada, diag

    def _on_run_delineation(self):
        dem_layer = self.combo_dem.currentLayer()
        if dem_layer is None:
            QMessageBox.warning(self, "Falta el MDE", "Seleccione o descargue un MDE en el paso 1.")
            return
        if self.break_point_xy is None:
            QMessageBox.warning(self, "Falta el break point", "Seleccione el punto de salida en el mapa (paso 3).")
            return

        try:
            # La zona UTM de trabajo se toma del MDE, no del punto: ver la
            # nota de _zona_utm_desde_capa. Si la que se dedujo al marcar el
            # punto no coincide, se corrige aquí y se rehace la conversión
            # del punto a partir de su longitud/latitud guardadas.
            crs_utm_mde, lon_mde, lat_mde = self._zona_utm_desde_capa(dem_layer)
            if self.utm_crs is None or self.utm_crs.authid() != crs_utm_mde.authid():
                zona_previa = self.utm_crs.authid() if self.utm_crs else "ninguna"
                self.utm_crs = crs_utm_mde
                if self.break_point_lonlat:
                    lon_bp, lat_bp = self.break_point_lonlat
                    punto_corregido = QgsCoordinateTransform(
                        QgsCoordinateReferenceSystem("EPSG:4326"), self.utm_crs,
                        QgsProject.instance()).transform(QgsPointXY(lon_bp, lat_bp))
                    self.break_point_xy = (punto_corregido.x(), punto_corregido.y())
                self.lbl_estado_tab1.setText(
                    f"Zona UTM corregida a {crs_utm_mde.authid()} según el centro del MDE "
                    f"(lon {lon_mde:.4f}, lat {lat_mde:.4f}); antes era {zona_previa}."
                )
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
                # Se informa también en LONGITUD/LATITUD, que es donde el
                # problema se ve de inmediato: comparar dos pares de
                # coordenadas UTM no dice nada si la zona misma es la
                # equivocada, mientras que en grados se detecta al instante
                # si el punto y el MDE están en sitios distintos del planeta.
                lon_bp = lat_bp = None
                if self.break_point_lonlat:
                    lon_bp, lat_bp = self.break_point_lonlat
                detalle_grados = (
                    f"\n\nEn coordenadas geográficas:\n"
                    f"  MDE (centro):   lon {lon_mde:.4f}, lat {lat_mde:.4f}\n"
                    f"  Punto de salida: lon {lon_bp:.4f}, lat {lat_bp:.4f}"
                    if lon_bp is not None else ""
                )
                if lon_bp is not None and abs(lon_bp - lon_mde) > 1.0:
                    detalle_grados += (
                        "\n\nEl punto y el MDE están en longitudes muy distintas: el punto de salida no "
                        "corresponde a este MDE. Vuelva a marcarlo sobre el MDE cargado."
                    )
                raise RuntimeError(
                    "El punto de salida (break point) cae fuera de la extensión del MDE.\n\n"
                    f"Zona de trabajo: {self.utm_crs.authid()} (deducida del centro del MDE)\n"
                    f"Extensión del MDE:  X=[{extent_dem.xMinimum():.1f}, {extent_dem.xMaximum():.1f}], "
                    f"Y=[{extent_dem.yMinimum():.1f}, {extent_dem.yMaximum():.1f}]\n"
                    f"Punto de salida:    X={px:.1f}, Y={py:.1f}"
                    + detalle_grados
                )

            context = QgsProcessingContext()
            feedback = QgsProcessingFeedback()

            # El relleno de vacíos va ANTES de calcular el flujo: si el MDE
            # tiene huecos, la dirección de flujo no puede propagarse a
            # través de ellos y la cuenca sale recortada o partida.
            dem_layer, self.diagnostico_nodata = self._rellenar_nodata_si_procede(
                dem_layer, context, feedback)
            self.dem_layer = dem_layer

            self.lbl_estado_tab1.setText("Calculando dirección y acumulación de flujo...")
            # Si el Paso A (generar red de drenaje) ya se ejecutó en esta
            # sesión, reutiliza su resultado de flujo en vez de recalcularlo
            # (ahorra tiempo, que puede ser significativo con MDE grandes).
            #
            # PERO SOLO SI SE CALCULÓ EN EL MISMO CRS (corrección v0.2.56).
            # El Paso A trabaja con el MDE tal como está en el proyecto, que
            # puede estar en cualquier CRS (p.ej. EPSG:3857 si viene de un
            # servicio web), mientras que el break point se convierte SIEMPRE
            # a la zona UTM local y este Paso B reproyecta el MDE a esa misma
            # zona. Reutilizar a ciegas el resultado del Paso A comparaba
            # entonces un punto en UTM (X del orden de 2.5e5) contra un
            # ráster de cauces en Web Mercator (X del orden de -7.9e6): el
            # punto quedaba a millones de metros del ráster y el snap fallaba
            # SIEMPRE con "el punto de salida cae fuera de la extensión del
            # ráster de cauces", sin importar dónde se hiciera clic.
            crs_paso_a = getattr(self, "crs_flujo_paso_a", None)
            crs_actual = dem_layer.crs().authid()
            flujo_cacheado = getattr(self, "resultado_flujo_paso_a", None)
            if flujo_cacheado is not None and crs_paso_a == crs_actual:
                flujo = flujo_cacheado
                self.lbl_estado_tab1.setText("Reutilizando el cálculo de flujo del Paso A...")
            elif flujo_cacheado is not None:
                self.lbl_estado_tab1.setText(
                    f"El Paso A se calculó en {crs_paso_a} y la delimitación trabaja en {crs_actual}: "
                    "recalculando el flujo en el CRS correcto..."
                )
                flujo = delineation.calcular_flujo(
                    dem_layer, umbral_acumulacion=self.spin_umbral.value(),
                    context=context, feedback=feedback,
                )
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
                cellsize=flujo.get("cellsize"),
                context=context, feedback=feedback,
                smooth_offset=self.spin_smooth_offset.value(),
            )
            resultado["red_drenaje_vector"] = delineation.extraer_y_recortar_red(
                flujo["raster_cauces"], resultado["cuenca_vector"], flujo["region"],
                cellsize=flujo.get("cellsize"),
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

            # Autocompletar Lt y Nu de la Pestaña 2 midiendo la red recién
            # delineada. Antes había que teclearlos, y al no hacerlo se
            # quedaban en el MÍNIMO de su rango (Lt = 0.001 km, Nu = 1) --
            # que Qt muestra cuando un spinbox no recibe valor. Con un metro
            # de red de drenaje, TODO el Grupo 5 de la morfometría salía sin
            # sentido: densidad de drenaje, textura, longitud de flujo
            # superficial, coeficiente de almacenamiento y número de
            # infiltración se calculan a partir de Lt.
            self._autocompletar_red_drenaje_pestana2()

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

    def _renumerar_tabla_morfo(self):
        """
        Numera en la cabecera vertical SOLO las filas de parámetro,
        dejando en blanco las de encabezado de sección (1 — Parámetros
        básicos, 2 — Forma, etc.).

        MOTIVO: `tabla_morfo` nunca fija encabezados verticales propios,
        así que Qt le pone el suyo por defecto (1, 2, 3... para CADA
        fila insertada). Eso numera también las 6 filas de título de
        sección como si fueran un parámetro más, y el número que ve el
        usuario al final ("fila 45") no coincide con la cantidad real de
        parámetros de la tabla. Una fila de encabezado se reconoce
        porque `_agregar_titulo_grupo_morfo` la fusiona (columnSpan > 1);
        se detecta así, en vez de llevar la cuenta aparte, para no poder
        desincronizarse si algún grupo cambia de orden más adelante.
        """
        etiquetas = []
        contador = 0
        for fila in range(self.tabla_morfo.rowCount()):
            if self.tabla_morfo.columnSpan(fila, 0) > 1:
                etiquetas.append("")
            else:
                contador += 1
                etiquetas.append(str(contador))
        self.tabla_morfo.setVerticalHeaderLabels(etiquetas)

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
            # Avisos NO fatales acumulados durante el cálculo. Se muestran
            # juntos al final: encadenar un diálogo modal por cada aviso
            # obliga a cerrar ventanas antes de ver ningún resultado.
            self._avisos_morfometria = []

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
            # El muestreo NUNCA debe interrumpir la morfometría: si algo
            # sale mal en el punto de salida hay un respaldo perfectamente
            # válido (el mínimo real del MDE ya recortado a la cuenca), así
            # que se degrada a él en vez de abortar el cálculo completo.
            z_min_real_dem = float(z_array.min())
            detalle_muestreo = None
            try:
                z_min_muestreado, detalle_muestreo = raster_stats.valor_en_punto(
                    self.dem_clip_path, *self.break_point_xy, devolver_detalle=True)
            except Exception as e:
                z_min_muestreado = None
                self._avisos_morfometria.append(
                    f"No se pudo muestrear la cota en el punto de salida ({e}). Se usó la cota "
                    f"mínima del MDE recortado, {round(z_min_real_dem, 2)} m s.n.m.")
            # El punto de salida (break point) debería, por definición,
            # ser el punto de menor cota de la cuenca delineada (o estar
            # muy cerca de serlo). Si el valor muestreado ahí resulta
            # notoriamente MAYOR que el mínimo real del MDE recortado, es
            # señal de que el punto de salida no quedó bien ajustado sobre
            # el cauce (p. ej. quedó sobre una ladera/cresta cercana), lo
            # que después hace fallar Giandotti y distorsiona H, Rr, Rh,
            # etc. En ese caso se usa el mínimo real del MDE como
            # respaldo, avisando al usuario en vez de fallar en silencio.
            if z_min_muestreado is None:
                z_min = z_min_real_dem
            elif (z_min_muestreado - z_min_real_dem) > max(0.02 * (z_max - z_min_real_dem), 5.0):
                self._avisos_morfometria.append(
                    f"La cota muestreada en el punto de salida ({round(z_min_muestreado, 2)} m) es "
                    f"notoriamente mayor que la cota mínima del MDE recortado a la cuenca "
                    f"({round(z_min_real_dem, 2)} m s.n.m.). Sugiere que el punto de salida no quedó "
                    "bien ajustado sobre el cauce (Pestaña 1, ajuste al cauce). Se usó el mínimo real "
                    "del MDE como Z_min; verifique el punto de salida antes de un diseño definitivo.")
                z_min = z_min_real_dem
            else:
                z_min = z_min_muestreado
                # La celda exacta del punto de salida suele quedar fuera del
                # recorte (el punto está en el borde de la cuenca). Se toma la
                # válida más próxima y se informa: a 12-30 m de resolución la
                # diferencia de cota es menor que el error del propio MDE,
                # pero el usuario debe saber que no es la celda exacta.
                if detalle_muestreo and not detalle_muestreo["celda_exacta"]:
                    self._avisos_morfometria.append(
                        "La celda exacta del punto de salida no tenía dato en el MDE recortado "
                        "(es lo normal: el punto de salida está en el borde de la cuenca y el "
                        "recorte descarta las celdas cuyo centro queda fuera del polígono). Se usó "
                        f"la celda con dato más cercana, a {detalle_muestreo['distancia_m']:.1f} m "
                        f"({detalle_muestreo['distancia_celdas']:.0f} celdas), con cota "
                        f"{round(z_min_muestreado, 2)} m s.n.m.")

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
                # Las advertencias de plausibilidad se muestran EN LA PROPIA
                # FILA del parámetro afectado, no solo en un mensaje aparte:
                # un valor corrupto que se ve normal en la tabla se copia a un
                # informe sin que nadie lo note.
                avisos_g4 = g4.get("advertencias") or []
                comentario_pct = g4["interpretacion"]
                if avisos_g4:
                    comentario_pct = "*** VALOR NO FIABLE *** " + avisos_g4[0]
                self._agregar_fila_morfo("Pendiente media de la cuenca", "Scuenca", g4["S_cuenca_pct"],
                                          comentario_pct, clave_lookup="Scuenca_pct")
                self._agregar_fila_morfo("Pendiente media de la cuenca", "Scuenca", g4["S_cuenca_deg"],
                                          clave_lookup="Scuenca_deg")
                if avisos_g4:
                    QMessageBox.warning(
                        self, "Resultados morfométricos no fiables",
                        "El cálculo detectó valores imposibles, que indican un problema en los datos de "
                        "entrada y NO deben usarse para diseño:\n\n- " + "\n\n- ".join(avisos_g4)
                    )
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
            self._renumerar_tabla_morfo()

            if g6["alerta_flujo_detritos"]:
                QMessageBox.warning(self, "Alerta de flujo de detritos", g6["mensaje_alerta"])

            # Los avisos no fatales van AL FINAL y juntos: la tabla ya está
            # completa detrás del diálogo, así que el usuario los lee con los
            # resultados a la vista en vez de antes de ver ninguno.
            if self._avisos_morfometria:
                QMessageBox.information(
                    self, "Morfometría calculada — observaciones",
                    "La morfometría se calculó completa. Tenga en cuenta:\n\n- "
                    + "\n\n- ".join(self._avisos_morfometria))

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
        #
        # Se agrega UNA fila más al final para el TOTAL acumulado de "%
        # cuenca" y "Área (km²)": el usuario necesita ver de un vistazo si
        # el reparto por coberturas realmente suma 100% y si el área
        # repartida coincide con la de la Pestaña 2, sin tener que sumar a
        # mano. self._n_filas_uso_suelo_cn guarda cuántas de las filas son
        # de DATO (las demás rutinas que leen la tabla deben iterar solo
        # hasta ahí, no hasta rowCount(), para no tratar la fila TOTAL
        # como si fuera una cobertura más).
        self._n_filas_uso_suelo_cn = len(curve_number.TABLA_USOS_ANDINOS_DEFAULT)
        self.tabla_cn = QTableWidget(self._n_filas_uso_suelo_cn + 1, 7)
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

        fila_total = self._n_filas_uso_suelo_cn
        item_total = QTableWidgetItem("TOTAL")
        fuente_total = item_total.font()
        fuente_total.setBold(True)
        item_total.setFont(fuente_total)
        item_total.setFlags(item_total.flags() & ~Qt.ItemIsEditable)
        self.tabla_cn.setItem(fila_total, 0, item_total)
        for col in (1, 2, 3, 4):
            relleno = QTableWidgetItem("")
            relleno.setFlags(relleno.flags() & ~Qt.ItemIsEditable)
            self.tabla_cn.setItem(fila_total, col, relleno)
        for col in (5, 6):
            # Placeholder: el valor real lo escribe _actualizar_totales_tabla_cn()
            # apenas termine de construirse la pestaña. No editable: es un
            # resultado calculado, no un dato que el usuario deba tocar.
            celda_total = QTableWidgetItem("0.0")
            celda_total.setFont(fuente_total)
            celda_total.setFlags(celda_total.flags() & ~Qt.ItemIsEditable)
            self.tabla_cn.setItem(fila_total, col, celda_total)
        self.tabla_cn.itemChanged.connect(self._on_tabla_cn_item_changed)
        self._actualizar_totales_tabla_cn()
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

        # =============================================================
        # MODELOS DE INFILTRACIÓN ALTERNATIVOS AL NÚMERO DE CURVA
        # =============================================================
        gb_infil = QGroupBox(
            "Modelos de infiltración alternativos — Green-Ampt, Horton, Philip, "
            "Kostiakov / Kostiakov-Lewis y Holtan")
        v_inf = QVBoxLayout(gb_infil)
        lbl_inf = QLabel(
            "El número de curva de arriba es un método <b>agregado de evento</b>: su abstracción "
            "depende solo de la lámina acumulada, así que <b>dos tormentas con la misma lámina total "
            "dan la misma lluvia efectiva</b> aunque una sea corta e intensa y la otra larga y suave. "
            "Los modelos de esta sección comparan la <b>intensidad</b> de cada intervalo contra la "
            "capacidad de infiltración del momento, por lo que sí las distinguen — y en cuencas "
            "altoandinas, donde las tormentas convectivas son cortas e intensas, esa diferencia va "
            "directa al caudal de diseño.<br><br>"
            "El modelo que elija aquí queda disponible en el desplegable de <b>pérdidas de la Pestaña 7"
            "</b>, donde se resta del hietograma para obtener la lluvia efectiva que alimenta el "
            "hidrograma unitario:  "
            "<code>hietograma → [pérdidas] → lluvia efectiva → HU → Qp</code>"
        )
        lbl_inf.setWordWrap(True)
        v_inf.addWidget(lbl_inf)

        v_inf.addWidget(QLabel(
            "<b>Hietograma de prueba</b> (incrementos de lluvia total en mm, separados por coma). "
            "Sirve para explorar y calibrar los modelos aquí; el cálculo definitivo usa el hietograma "
            "de la Pestaña 6."))
        h_hieto_inf = QHBoxLayout()
        self.edit_hietograma_infiltracion = QLineEdit("2,4,8,15,28,22,14,9,6,4,3,2")
        h_hieto_inf.addWidget(self.edit_hietograma_infiltracion)
        h_hieto_inf.addWidget(QLabel("Δt (h):"))
        self.spin_dt_infiltracion = QDoubleSpinBox()
        self.spin_dt_infiltracion.setRange(0.05, 6.0)
        self.spin_dt_infiltracion.setSingleStep(0.25)
        self.spin_dt_infiltracion.setValue(0.5)
        h_hieto_inf.addWidget(self.spin_dt_infiltracion)
        v_inf.addLayout(h_hieto_inf)

        h_sync_inf = QHBoxLayout()
        btn_sync_hieto_inf = QPushButton(
            "Usar el hietograma de diseño de la Pestaña 6 (misma forma y duración)")
        btn_sync_hieto_inf.clicked.connect(self._on_sincronizar_hietograma_infiltracion)
        limitar_ancho_boton(btn_sync_hieto_inf)
        h_sync_inf.addWidget(btn_sync_hieto_inf)
        h_sync_inf.addStretch()
        v_inf.addLayout(h_sync_inf)

        h_sel_inf = QHBoxLayout()
        h_sel_inf.addWidget(QLabel("Modelo:"))
        self.combo_modelo_infiltracion = QComboBox()
        for _txt, _clave in (
                ("SCS — Número de Curva (usa el S calculado arriba)", "scs_cn"),
                ("Green-Ampt (1911) — físicamente basado", "green_ampt"),
                ("Horton (1940) — empírico exponencial", "horton"),
                ("Philip (1957) — sorptividad + gravedad", "philip"),
                ("Kostiakov / Kostiakov-Lewis (1932)", "kostiakov"),
                ("Holtan (USDA-HL) — por almacenamiento disponible", "holtan"),
                ("Richards 1D (van Genuchten) — física completa", "richards")):
            self.combo_modelo_infiltracion.addItem(_txt, _clave)
        self.combo_modelo_infiltracion.currentIndexChanged.connect(
            lambda: self.stack_infiltracion.setCurrentIndex(
                self.combo_modelo_infiltracion.currentIndex()))
        h_sel_inf.addWidget(self.combo_modelo_infiltracion)
        h_sel_inf.addStretch()
        v_inf.addLayout(h_sel_inf)

        self.stack_infiltracion = QStackedWidget()

        # -- SCS — Número de Curva --
        _p, _f = self._nueva_pagina_infiltracion()
        _l = QLabel(
            "Usa la retención potencial máxima <b>S</b> del número de curva calculado en la sección "
            "superior de esta pestaña: no requiere parámetros adicionales aquí.<br><br>"
            "A diferencia de los otros seis, es un <b>método agregado de evento</b>: su abstracción "
            "depende solo de la lámina acumulada, no de la intensidad instantánea. Por eso no tiene "
            "curva de capacidad de infiltración, y su gráfico omite esa curva en vez de dibujar una "
            "línea inventada. Dos tormentas con la misma lámina total le dan el mismo resultado aunque "
            "una sea corta e intensa y la otra larga y suave — que es justamente la limitación que los "
            "demás modelos vienen a cubrir.")
        _l.setWordWrap(True); _f.addRow(_l)
        self._cerrar_pagina_infiltracion(_p, _f, "scs_cn")

        # -- Green-Ampt --
        _p, _f = self._nueva_pagina_infiltracion()
        self.combo_textura_ga3 = QComboBox()
        for _clave, (_n, _k, _psi, _po) in infiltration.PARAMETROS_GREEN_AMPT.items():
            self.combo_textura_ga3.addItem(f"{_n}  (K={_k} mm/h, ψ={_psi} mm, θe={_po})", _clave)
        self.combo_textura_ga3.setCurrentIndex(2)
        self.combo_textura_ga3.currentIndexChanged.connect(self._on_textura_ga3)
        _f.addRow("Clase textural (Rawls et al., 1983):", self.combo_textura_ga3)
        self.spin_ga3_k = QDoubleSpinBox(); self.spin_ga3_k.setRange(0.01, 500.0)
        self.spin_ga3_k.setDecimals(3); self.spin_ga3_k.setValue(10.9)
        _f.addRow("Conductividad saturada K (mm/h):", self.spin_ga3_k)
        self.spin_ga3_psi = QDoubleSpinBox(); self.spin_ga3_psi.setRange(1.0, 1000.0)
        self.spin_ga3_psi.setDecimals(2); self.spin_ga3_psi.setValue(110.1)
        _f.addRow("Succión del frente húmedo ψ (mm):", self.spin_ga3_psi)
        self.spin_ga3_dth = QDoubleSpinBox(); self.spin_ga3_dth.setRange(0.01, 1.0)
        self.spin_ga3_dth.setDecimals(3); self.spin_ga3_dth.setValue(0.412)
        _f.addRow("Déficit de humedad Δθ:", self.spin_ga3_dth)
        self._cerrar_pagina_infiltracion(_p, _f, "green_ampt")

        # -- Horton --
        _p, _f = self._nueva_pagina_infiltracion()
        self.combo_grupo_ho3 = QComboBox()
        for _g, (_d, _f0, _fc) in infiltration.PARAMETROS_HORTON.items():
            self.combo_grupo_ho3.addItem(f"{_d}  (f0={_f0}, fc={_fc} mm/h)", _g)
        self.combo_grupo_ho3.setCurrentIndex(1)
        self.combo_grupo_ho3.currentIndexChanged.connect(self._on_grupo_ho3)
        _f.addRow("Grupo hidrológico de suelo (el de arriba):", self.combo_grupo_ho3)
        self.spin_ho3_f0 = QDoubleSpinBox(); self.spin_ho3_f0.setRange(1.0, 1000.0)
        self.spin_ho3_f0.setValue(200.0)
        _f.addRow("Capacidad inicial f₀ (mm/h):", self.spin_ho3_f0)
        self.spin_ho3_fc = QDoubleSpinBox(); self.spin_ho3_fc.setRange(0.1, 500.0)
        self.spin_ho3_fc.setValue(13.0)
        _f.addRow("Capacidad final f_c (mm/h):", self.spin_ho3_fc)
        self.spin_ho3_k = QDoubleSpinBox(); self.spin_ho3_k.setRange(0.1, 20.0)
        self.spin_ho3_k.setDecimals(3); self.spin_ho3_k.setValue(infiltration.K_HORTON_DEFAULT)
        _f.addRow("Constante de decaimiento k (1/h; usual 2-7):", self.spin_ho3_k)
        self._cerrar_pagina_infiltracion(_p, _f, "horton")

        # -- Philip --
        _p, _f = self._nueva_pagina_infiltracion()
        self.spin_ph_s = QDoubleSpinBox(); self.spin_ph_s.setRange(1.0, 500.0)
        self.spin_ph_s.setDecimals(2); self.spin_ph_s.setValue(60.0)
        _f.addRow("Sorptividad S (mm/h^0.5):", self.spin_ph_s)
        self.spin_ph_a = QDoubleSpinBox(); self.spin_ph_a.setRange(0.01, 200.0)
        self.spin_ph_a.setDecimals(3); self.spin_ph_a.setValue(5.0)
        _f.addRow("Factor de gravedad A (mm/h; ≈0.38–0.8·Ks):", self.spin_ph_a)
        _l = QLabel(
            "Solución analítica simplificada de la ecuación de Richards: separa la fase dominada por "
            "la succión capilar (S) de la dominada por la gravedad (A). Ojo: f(t) diverge en t=0, así "
            "que el plugin usa la capacidad MEDIA de cada intervalo, que es el valor comparable con la "
            "intensidad media del mismo intervalo.")
        _l.setWordWrap(True); _f.addRow(_l)
        self._cerrar_pagina_infiltracion(_p, _f, "philip")

        # -- Kostiakov --
        _p, _f = self._nueva_pagina_infiltracion()
        self.spin_ko_a = QDoubleSpinBox(); self.spin_ko_a.setRange(0.1, 500.0)
        self.spin_ko_a.setDecimals(2); self.spin_ko_a.setValue(40.0)
        _f.addRow("Coeficiente a (de ensayo de infiltrómetro):", self.spin_ko_a)
        self.spin_ko_b = QDoubleSpinBox(); self.spin_ko_b.setRange(0.01, 0.99)
        self.spin_ko_b.setDecimals(3); self.spin_ko_b.setValue(0.5)
        _f.addRow("Exponente b (0 < b < 1):", self.spin_ko_b)
        self.spin_ko_fc = QDoubleSpinBox(); self.spin_ko_fc.setRange(0.0, 200.0)
        self.spin_ko_fc.setDecimals(2); self.spin_ko_fc.setValue(8.0)
        _f.addRow("f_c de Lewis (mm/h; 0 = Kostiakov estándar):", self.spin_ko_fc)
        _l = QLabel(
            "Con f_c = 0 se obtiene el Kostiakov original, cuyo defecto conocido es que la capacidad "
            "tiende a CERO al crecer el tiempo — físicamente imposible, ningún suelo deja de infiltrar. "
            "La variante de Lewis (f_c > 0) lo corrige, y es la recomendable en tormentas largas.")
        _l.setWordWrap(True); _f.addRow(_l)
        self._cerrar_pagina_infiltracion(_p, _f, "kostiakov")

        # -- Holtan --
        _p, _f = self._nueva_pagina_infiltracion()
        self.spin_hol_a = QDoubleSpinBox(); self.spin_hol_a.setRange(0.05, 3.0)
        self.spin_hol_a.setDecimals(3); self.spin_hol_a.setValue(0.5)
        _f.addRow("Índice de cobertura a (rango bibliográfico 0.1–1.0):", self.spin_hol_a)
        self.spin_hol_gi = QDoubleSpinBox(); self.spin_hol_gi.setRange(0.05, 1.0)
        self.spin_hol_gi.setDecimals(3); self.spin_hol_gi.setValue(0.8)
        _f.addRow("Índice de crecimiento de la planta GI (0–1):", self.spin_hol_gi)
        self.spin_hol_sa = QDoubleSpinBox(); self.spin_hol_sa.setRange(1.0, 1000.0)
        self.spin_hol_sa.setValue(80.0)
        _f.addRow("Almacenamiento disponible en raíces SA (mm):", self.spin_hol_sa)
        self.spin_hol_d = QDoubleSpinBox(); self.spin_hol_d.setRange(0.5, 3.0)
        self.spin_hol_d.setDecimals(2); self.spin_hol_d.setValue(1.4)
        _f.addRow("Exponente d (habitual 1.4):", self.spin_hol_d)
        self.spin_hol_fc = QDoubleSpinBox(); self.spin_hol_fc.setRange(0.1, 200.0)
        self.spin_hol_fc.setValue(10.0)
        _f.addRow("Infiltración final f_c (mm/h):", self.spin_hol_fc)
        _l = QLabel(
            "Único de los seis que NO depende del tiempo ni de la infiltración acumulada, sino del "
            "almacenamiento que aún queda libre en la zona radicular. Por eso es el único que "
            "representa la RECUPERACIÓN de capacidad entre eventos (en los demás la capacidad solo "
            "puede decaer). Atención: la formulación original es en pulgadas; el plugin convierte "
            "internamente, así que 'a' conserva su rango bibliográfico de 0.1–1.0 y SA se ingresa en mm.")
        _l.setWordWrap(True); _f.addRow(_l)
        self._cerrar_pagina_infiltracion(_p, _f, "holtan")

        # -- Richards 1D --
        _p, _f = self._nueva_pagina_infiltracion()
        self.combo_textura_vg = QComboBox()
        for _clave, (_n, _tr, _ts, _al, _nv, _ks) in infiltration.PARAMETROS_VAN_GENUCHTEN.items():
            self.combo_textura_vg.addItem(
                f"{_n}  (θr={_tr}, θs={_ts}, α={_al} 1/cm, n={_nv}, Ks={_ks} cm/h)", _clave)
        self.combo_textura_vg.setCurrentIndex(2)
        self.combo_textura_vg.currentIndexChanged.connect(self._on_textura_vg)
        _f.addRow("Clase textural (Carsel & Parrish, 1988):", self.combo_textura_vg)
        self.spin_vg_tr = QDoubleSpinBox(); self.spin_vg_tr.setRange(0.0, 0.5)
        self.spin_vg_tr.setDecimals(4); self.spin_vg_tr.setValue(0.065)
        _f.addRow("Humedad residual θr:", self.spin_vg_tr)
        self.spin_vg_ts = QDoubleSpinBox(); self.spin_vg_ts.setRange(0.1, 0.9)
        self.spin_vg_ts.setDecimals(4); self.spin_vg_ts.setValue(0.41)
        _f.addRow("Humedad saturada θs:", self.spin_vg_ts)
        self.spin_vg_alpha = QDoubleSpinBox(); self.spin_vg_alpha.setRange(0.0001, 1.0)
        self.spin_vg_alpha.setDecimals(4); self.spin_vg_alpha.setValue(0.075)
        _f.addRow("α de van Genuchten (1/cm):", self.spin_vg_alpha)
        self.spin_vg_n = QDoubleSpinBox(); self.spin_vg_n.setRange(1.01, 5.0)
        self.spin_vg_n.setDecimals(3); self.spin_vg_n.setValue(1.89)
        _f.addRow("n de van Genuchten (> 1):", self.spin_vg_n)
        self.spin_vg_ks = QDoubleSpinBox(); self.spin_vg_ks.setRange(0.001, 100.0)
        self.spin_vg_ks.setDecimals(4); self.spin_vg_ks.setValue(4.42)
        _f.addRow("Conductividad saturada Ks (cm/h):", self.spin_vg_ks)
        self.spin_vg_prof = QDoubleSpinBox(); self.spin_vg_prof.setRange(100.0, 10000.0)
        self.spin_vg_prof.setValue(1500.0)
        _f.addRow("Profundidad de la columna simulada (mm):", self.spin_vg_prof)
        self.spin_vg_celdas = QSpinBox(); self.spin_vg_celdas.setRange(10, 200)
        self.spin_vg_celdas.setValue(40)
        _f.addRow("Número de celdas de la malla:", self.spin_vg_celdas)
        self.spin_vg_succion = QDoubleSpinBox(); self.spin_vg_succion.setRange(-50000.0, -1.0)
        self.spin_vg_succion.setValue(-1000.0)
        _f.addRow("Succión inicial del perfil (mm, negativa):", self.spin_vg_succion)
        _l = QLabel(
            "El más riguroso de los seis: resuelve la ecuación de Richards en forma mixta con "
            "iteración de Picard modificada (Celia et al., 1990) y volúmenes finitos, que es la "
            "formulación conservativa en masa. <b>Límite medido:</b> converge en suelos de textura "
            "gruesa a media (arena, arena franca, franco arenoso, franco, limo, franco arcillo-limoso) "
            "con error de balance de 0 a 4.5·10⁻⁴ mm. En suelos muy finos, cuya Ks queda uno o dos "
            "órdenes por debajo de la intensidad de la lluvia, el frente se vuelve casi discontinuo y "
            "la iteración no converge: en ese caso el plugin avisa y lo razonable es usar Green-Ampt, "
            "que está formulado precisamente para un frente abrupto. Es también el más lento.")
        _l.setWordWrap(True); _f.addRow(_l)
        self._cerrar_pagina_infiltracion(_p, _f, "richards")

        v_inf.addWidget(self.stack_infiltracion)

        h_btn_inf = QHBoxLayout()
        btn_calc_inf = QPushButton("Calcular el modelo seleccionado")
        btn_calc_inf.clicked.connect(self._on_calcular_infiltracion)
        limitar_ancho_boton(btn_calc_inf)
        h_btn_inf.addWidget(btn_calc_inf)
        btn_comp_inf = QPushButton("Comparar TODOS los modelos")
        btn_comp_inf.clicked.connect(self._on_comparar_infiltracion_todos)
        limitar_ancho_boton(btn_comp_inf)
        h_btn_inf.addWidget(btn_comp_inf)
        h_btn_inf.addStretch()
        v_inf.addLayout(h_btn_inf)

        self.tabla_resultado_infiltracion = crear_tabla_parametros()
        v_inf.addWidget(self.tabla_resultado_infiltracion)
        v_inf.addWidget(QLabel(
            "<b>Comparación entre modelos</b> (se llena con el botón «Comparar TODOS los modelos»):"))
        self.canvas_infiltracion = InfiltrationCanvas(self, width=7.0, height=5.4)
        v_inf.addWidget(self.canvas_infiltracion)
        v.addWidget(gb_infil)

        v.addWidget(QLabel("<b>Cuadro resumen final de la pestaña:</b>"))
        self.texto_resumen_pestana3 = ResumenFinal()
        v.addWidget(self.texto_resumen_pestana3)

        self._agregar_pestaña_con_scroll(
            tab, "3. Métodos de pérdida SCS-CN / Horton / Green-Ampt / otros")

    # ------------------------------------------------------------------
    # Modelos de infiltración (Pestaña 3)
    # ------------------------------------------------------------------
    def _nueva_pagina_infiltracion(self):
        """
        Crea una página del selector de modelos con la estructura común:
        formulario de parámetros arriba, y debajo (los añade
        _cerrar_pagina_infiltracion) su propio cuadro resumen de impacto
        y su propio gráfico. Cada método tiene los suyos en vez de
        compartir uno solo, para poder compararlos alternando el
        desplegable sin perder el contexto de cada uno.
        """
        pagina = QWidget()
        contenedor = QVBoxLayout(pagina)
        formulario = QFormLayout()
        formulario.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        contenedor.addLayout(formulario)
        return pagina, formulario

    def _cerrar_pagina_infiltracion(self, pagina, formulario, clave):
        """Añade a la página su cuadro de impacto y su gráfico, los
        registra por clave de método y la inserta en el stack."""
        contenedor = pagina.layout()
        cuadro = CuadroResumenImpacto(ancho_maximo=680)
        cuadro.actualizar(
            titulo="SIN CALCULAR",
            valor_principal="—",
            subtitulo="Pulse «Calcular el modelo seleccionado» para obtener la lluvia efectiva",
            tipo="info")
        centrar_en_layout(cuadro, contenedor)
        canvas = InfiltrationCanvas(self, width=6.9, height=4.3)
        contenedor.addWidget(canvas)
        self.cuadros_infiltracion[clave] = cuadro
        self.canvas_por_metodo_infiltracion[clave] = canvas
        self.stack_infiltracion.addWidget(pagina)

    def _actualizar_cuadro_infiltracion(self, clave, r):
        """Vuelca el resultado de un modelo en su cuadro de alto impacto.
        El color comunica el régimen: verde si casi todo infiltra, ámbar
        si la escorrentía es apreciable y rojo si domina la escorrentía,
        que es la condición crítica para el caudal de diseño."""
        cuadro = self.cuadros_infiltracion.get(clave)
        if cuadro is None:
            return
        coef = r["coeficiente_escorrentia"]
        tipo = "exito" if coef < 0.15 else ("atencion" if coef < 0.40 else "alerta")
        metricas = [
            ("Lluvia total", f"{r['lluvia_total_mm']:.1f} mm"),
            ("Infiltrado", f"{r['infiltracion_total_mm']:.1f} mm"),
            ("Coef. escorrentía", f"{coef:.3f}"),
            ("Encharcamiento",
             f"t = {r['tiempo_encharcamiento_h']} h" if r.get("hubo_encharcamiento") else "no hubo"),
        ]
        cuadro.actualizar(
            titulo=r["metodo"].upper(),
            valor_principal=f"Lluvia efectiva = {r['lluvia_efectiva_total_mm']:.2f} mm",
            subtitulo="es la lámina que alimenta el hidrograma unitario y fija el caudal pico",
            metricas=metricas,
            leyenda=("balance de masa verificado: infiltración + efectiva = lluvia total  "
                     f"(error {r['error_balance_masa_mm']:.1e} mm)"),
            tipo=tipo)

    def _actualizar_resumen_final_pestana3(self):
        """Cuadro resumen final de la Pestaña 3: reúne el número de curva
        (si se calculó) y todos los modelos de infiltración ya
        ejecutados, ordenados por la lluvia efectiva que producen, que es
        lo que se traslada al caudal de diseño."""
        html = "<h3>Cuadro resumen final — Métodos de pérdida</h3>"
        hay_algo = False

        if self.cn_resultados:
            hay_algo = True
            cn = self.cn_resultados
            html += (
                "<p><b>Número de Curva SCS</b><br>"
                f"CN = <b>{cn.get('CN_ponderado', cn.get('CN', '—'))}</b> &nbsp;|&nbsp; "
                f"S = {cn.get('S_mm', '—')} mm &nbsp;|&nbsp; "
                f"Abstracción inicial Ia = {round(0.2 * cn['S_mm'], 2) if cn.get('S_mm') else '—'} mm</p>"
            )

        if self.resultados_infiltracion_por_metodo:
            hay_algo = True
            ordenados = sorted(self.resultados_infiltracion_por_metodo.items(),
                               key=lambda kv: kv[1]["lluvia_efectiva_total_mm"], reverse=True)
            html += ("<hr><p><b>Modelos de infiltración calculados</b> "
                     "(ordenados por lluvia efectiva, de mayor a menor):</p>"
                     "<table cellpadding='4' style='border-collapse:collapse'>"
                     "<tr style='background:#eef5fb'><th align='left'>Modelo</th>"
                     "<th align='right'>Lluvia efectiva</th><th align='right'>Infiltrado</th>"
                     "<th align='right'>Coef. escorrentía</th><th align='left'>Encharcamiento</th></tr>")
            for _clave, r in ordenados:
                ench = (f"t = {r['tiempo_encharcamiento_h']} h"
                        if r.get("hubo_encharcamiento") else "no hubo")
                html += (
                    f"<tr><td>{r['metodo']}</td>"
                    f"<td align='right'><b>{r['lluvia_efectiva_total_mm']:.2f} mm</b></td>"
                    f"<td align='right'>{r['infiltracion_total_mm']:.2f} mm</td>"
                    f"<td align='right'>{r['coeficiente_escorrentia']:.3f}</td>"
                    f"<td>{ench}</td></tr>")
            html += "</table>"

            efectivas = [r["lluvia_efectiva_total_mm"] for _, r in ordenados]
            if len(efectivas) > 1:
                dispersion = max(efectivas) - min(efectivas)
                relativa = dispersion / max(efectivas) * 100.0 if max(efectivas) else 0.0
                html += (
                    f"<p><b>Dispersión entre modelos: {dispersion:.2f} mm ({relativa:.1f}%).</b> "
                    "La lluvia efectiva se traslada de forma casi proporcional al caudal pico, así que "
                    "esta cifra es aproximadamente la incertidumbre que introduce la ELECCIÓN DEL "
                    "MODELO en el caudal de diseño — con frecuencia mayor que la de otros parámetros a "
                    "los que se dedica mucho más esfuerzo.</p>")

        if not hay_algo:
            html += ("<p style='color:#666666'>Aún no se ha calculado ningún método de pérdida en esta "
                     "pestaña.</p>")
        else:
            html += (
                "<p style='color:#666666'>El modelo que elija aquí queda disponible en el desplegable "
                "de pérdidas de la Pestaña 7, donde se resta del hietograma de diseño para obtener la "
                "lluvia efectiva que alimenta el hidrograma unitario. Mantenga el mismo modelo y los "
                "mismos parámetros de forma consistente a lo largo de todo el estudio.</p>")
        self.texto_resumen_pestana3.setHtml(html)

    def _on_textura_ga3(self):
        clave = self.combo_textura_ga3.currentData()
        if clave in infiltration.PARAMETROS_GREEN_AMPT:
            _n, k, psi, poro = infiltration.PARAMETROS_GREEN_AMPT[clave]
            self.spin_ga3_k.setValue(k)
            self.spin_ga3_psi.setValue(psi)
            self.spin_ga3_dth.setValue(poro)

    def _on_textura_vg(self):
        clave = self.combo_textura_vg.currentData()
        if clave in infiltration.PARAMETROS_VAN_GENUCHTEN:
            _n, tr, ts, al, nv, ks = infiltration.PARAMETROS_VAN_GENUCHTEN[clave]
            self.spin_vg_tr.setValue(tr); self.spin_vg_ts.setValue(ts)
            self.spin_vg_alpha.setValue(al); self.spin_vg_n.setValue(nv)
            self.spin_vg_ks.setValue(ks)

    def _on_grupo_ho3(self):
        grupo = self.combo_grupo_ho3.currentData()
        if grupo in infiltration.PARAMETROS_HORTON:
            _d, f0, fc = infiltration.PARAMETROS_HORTON[grupo]
            self.spin_ho3_f0.setValue(f0)
            self.spin_ho3_fc.setValue(fc)

    def _leer_hietograma_infiltracion(self):
        import re
        texto = self.edit_hietograma_infiltracion.text().strip()
        return [float(t) for t in re.findall(r"-?\d+(?:\.\d+)?", texto)]

    def _on_sincronizar_hietograma_infiltracion(self):
        """
        Copia el hietograma de PRUEBA de esta pestaña desde el hietograma
        de DISEÑO real de la Pestaña 6 (misma forma, mismos incrementos,
        mismo Δt) -- así los modelos de infiltración se ven y se calibran
        sobre la misma duración de tormenta que el caudal de diseño
        termina usando, en vez de sobre el hietograma de 12 intervalos ×
        0.5 h que trae el campo por defecto, que puede durar mucho menos
        (o más) que la tormenta real del proyecto.
        """
        if not hasattr(self, "edit_hietograma"):
            QMessageBox.warning(
                self, "Pestaña 6 no disponible",
                "No se encontró el hietograma de la Pestaña 6 en esta sesión.")
            return
        try:
            hietograma = self._leer_hietograma_actual()
        except Exception:
            hietograma = []
        if not hietograma:
            QMessageBox.warning(
                self, "Sin hietograma en la Pestaña 6",
                "Genere primero el hietograma de diseño en la Pestaña 6 (sección de transformación "
                "lluvia-escorrentía) antes de sincronizarlo aquí.")
            return
        self.edit_hietograma_infiltracion.setText(",".join(f"{v:.2f}" for v in hietograma))
        self.spin_dt_infiltracion.setValue(self.spin_dt_h.value())
        QMessageBox.information(
            self, "Hietograma sincronizado",
            f"Se copiaron {len(hietograma)} intervalos de Δt={self.spin_dt_h.value()} h "
            f"({len(hietograma) * self.spin_dt_h.value():.1f} h de duración total) desde la "
            "Pestaña 6.")

    def parametros_infiltracion(self, clave=None):
        """Parámetros del modelo de infiltración configurado en la
        Pestaña 3, para que la Pestaña 7 pueda reutilizarlos sin duplicar
        los controles."""
        clave = clave or self.combo_modelo_infiltracion.currentData()
        if clave == "scs_cn":
            return {}  # no tiene parámetros propios: usa el S del número de curva
        if clave == "green_ampt":
            return {"conductividad_k_mm_h": self.spin_ga3_k.value(),
                    "succion_psi_mm": self.spin_ga3_psi.value(),
                    "deficit_humedad": self.spin_ga3_dth.value()}
        if clave == "horton":
            return {"f0_mm_h": self.spin_ho3_f0.value(), "fc_mm_h": self.spin_ho3_fc.value(),
                    "k_decaimiento": self.spin_ho3_k.value()}
        if clave == "philip":
            return {"sorptividad_mm_h05": self.spin_ph_s.value(),
                    "factor_gravedad_a_mm_h": self.spin_ph_a.value()}
        if clave == "kostiakov":
            return {"coef_a": self.spin_ko_a.value(), "exponente_b": self.spin_ko_b.value(),
                    "fc_mm_h": self.spin_ko_fc.value()}
        if clave == "richards":
            return {"theta_r": self.spin_vg_tr.value(), "theta_s": self.spin_vg_ts.value(),
                    "alpha_1_cm": self.spin_vg_alpha.value(), "n_vg": self.spin_vg_n.value(),
                    "ks_cm_h": self.spin_vg_ks.value(),
                    "profundidad_columna_mm": self.spin_vg_prof.value(),
                    "n_celdas": self.spin_vg_celdas.value(),
                    "succion_inicial_mm": self.spin_vg_succion.value()}
        if clave == "holtan":
            return {"coef_a": self.spin_hol_a.value(),
                    "indice_crecimiento_gi": self.spin_hol_gi.value(),
                    "almacenamiento_disponible_mm": self.spin_hol_sa.value(),
                    "fc_mm_h": self.spin_hol_fc.value(),
                    "exponente_d": self.spin_hol_d.value()}
        return {}

    def _ejecutar_modelo_infiltracion(self, clave, hietograma, dt_h):
        params = self.parametros_infiltracion(clave)
        if clave == "scs_cn":
            # El S viene de la sección de número de curva de esta misma pestaña.
            s_mm = (self.cn_resultados or {}).get("S_mm")
            return infiltration.perdidas_scs_cn(hietograma, dt_h, s_mm)
        funciones = {
            "green_ampt": infiltration.infiltracion_green_ampt,
            "horton": infiltration.infiltracion_horton,
            "philip": infiltration.infiltracion_philip,
            "kostiakov": infiltration.infiltracion_kostiakov,
            "holtan": infiltration.infiltracion_holtan,
            "richards": infiltration.infiltracion_richards_1d,
        }
        return funciones[clave](hietograma, dt_h, **params)

    def _filas_resultado_infiltracion(self, r):
        filas = [
            ("Modelo", r["metodo"], ""),
            ("Lluvia total del hietograma", r["lluvia_total_mm"], "mm"),
            ("Infiltración total (pérdidas)", r["infiltracion_total_mm"], "mm"),
            ("Lluvia efectiva (escurre)", r["lluvia_efectiva_total_mm"], "mm",
             "es la que alimenta el hidrograma unitario y determina el Qp"),
            ("Coeficiente de escorrentía", r["coeficiente_escorrentia"], "",
             "lluvia efectiva / lluvia total"),
        ]
        if r.get("hubo_encharcamiento"):
            filas.append(("Inicio del encharcamiento", r["tiempo_encharcamiento_h"], "h",
                           "desde aquí la intensidad supera la capacidad de infiltración"))
        else:
            filas.append(("Encharcamiento", "no se alcanzó", "",
                           "toda la lluvia infiltró: este modelo/parámetros no generan escorrentía"))
        filas.append(("Balance de masa", r["error_balance_masa_mm"], "mm",
                       "infiltración + lluvia efectiva = lluvia total (debe ser 0)"))
        return filas

    def _on_calcular_infiltracion(self):
        hietograma = self._leer_hietograma_infiltracion()
        if not hietograma:
            QMessageBox.warning(self, "Falta el hietograma",
                                 "Ingrese el hietograma de prueba (incrementos de lluvia en mm).")
            return
        try:
            dt_h = self.spin_dt_infiltracion.value()
            clave = self.combo_modelo_infiltracion.currentData()
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                r = self._ejecutar_modelo_infiltracion(clave, hietograma, dt_h)
            finally:
                QApplication.restoreOverrideCursor()
            self.infiltracion_resultado = r
            self.resultados_infiltracion_por_metodo[clave] = r
            poblar_tabla_parametros(self.tabla_resultado_infiltracion,
                                     self._filas_resultado_infiltracion(r))
            # Cada método actualiza SU cuadro de impacto y SU gráfico.
            self._actualizar_cuadro_infiltracion(clave, r)
            canvas = self.canvas_por_metodo_infiltracion.get(clave)
            if canvas is not None:
                canvas.plot_hietograma_separado(r, dt_h)
            self._actualizar_resumen_final_pestana3()
        except infiltration.InfiltrationError as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "No se pudo calcular", str(e))

    def _on_comparar_infiltracion_todos(self):
        hietograma = self._leer_hietograma_infiltracion()
        if not hietograma:
            QMessageBox.warning(self, "Falta el hietograma",
                                 "Ingrese el hietograma de prueba (incrementos de lluvia en mm).")
            return
        dt_h = self.spin_dt_infiltracion.value()
        resultados, filas, errores = [], [], []
        # El número de curva se incluye en la comparación solo si ya se
        # calculó arriba, para poder contrastar contra el método que el
        # plugin usa por defecto.
        if self.cn_resultados:
            from .core.unit_hydrographs import lluvia_efectiva_incremental
            efectiva = lluvia_efectiva_incremental(hietograma, self.cn_resultados["S_mm"])
            total = sum(hietograma)
            resultados.append({
                "metodo": "SCS — Número de Curva",
                "lluvia_efectiva_incr_mm": list(efectiva),
                "infiltracion_incr_mm": [p - e for p, e in zip(hietograma, efectiva)],
                "capacidad_infiltracion_mm_h": [None] * len(efectiva),
                "lluvia_total_mm": round(total, 3),
                "lluvia_efectiva_total_mm": round(sum(efectiva), 3),
                "coeficiente_escorrentia": round(sum(efectiva) / total, 4) if total else 0.0,
                "hubo_encharcamiento": False,
            })
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for clave in ("green_ampt", "horton", "philip", "kostiakov", "holtan", "richards"):
                try:
                    r_i = self._ejecutar_modelo_infiltracion(clave, hietograma, dt_h)
                    resultados.append(r_i)
                    self.resultados_infiltracion_por_metodo[clave] = r_i
                    self._actualizar_cuadro_infiltracion(clave, r_i)
                    canvas_i = self.canvas_por_metodo_infiltracion.get(clave)
                    if canvas_i is not None:
                        canvas_i.plot_hietograma_separado(r_i, dt_h)
                except infiltration.InfiltrationError as e:
                    errores.append(f"{clave}: {e}")
        finally:
            QApplication.restoreOverrideCursor()
        if not resultados:
            QMessageBox.warning(self, "Sin resultados",
                                 "Ningún modelo pudo calcularse:\n\n" + "\n".join(errores))
            return
        for r in resultados:
            filas.append((f"Lluvia efectiva — {r['metodo']}", r["lluvia_efectiva_total_mm"], "mm",
                           f"coeficiente de escorrentía = {r['coeficiente_escorrentia']}"))
        efectivas = [r["lluvia_efectiva_total_mm"] for r in resultados]
        filas.append(
            ("Dispersión entre modelos", round(max(efectivas) - min(efectivas), 3), "mm",
             "la lluvia efectiva se traslada de forma casi proporcional al caudal pico: esta "
             "dispersión es, aproximadamente, la incertidumbre del Qp por la elección del modelo"))
        poblar_tabla_parametros(self.tabla_resultado_infiltracion, filas)
        self.canvas_infiltracion.plot_comparacion_metodos(resultados, dt_h)
        self._actualizar_resumen_final_pestana3()
        if errores:
            QMessageBox.information(
                self, "Algunos modelos no se calcularon", "\n\n".join(errores))

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
            for row in range(self._n_filas_uso_suelo_cn):
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
        # setItem() de cada fila ya disparó itemChanged y recalculó la fila
        # TOTAL en cada vuelta del bucle; se fuerza una última vez para
        # que quede exacta tras el aviso de suma (defensivo, no hay coste
        # apreciable con ~7 filas).
        self._actualizar_totales_tabla_cn()

    def _on_tabla_cn_item_changed(self, item):
        """Recalcula la fila TOTAL cada vez que el usuario edita a mano
        una celda de % o de Área en tabla_cn (pegado, escritura directa),
        no solo cuando pulsa el botón de distribuir por %."""
        if item.row() == self._n_filas_uso_suelo_cn:
            return  # la propia fila TOTAL se actualiza más abajo, sin recursión
        if item.column() in (5, 6):
            self._actualizar_totales_tabla_cn()

    def _actualizar_totales_tabla_cn(self):
        """
        Escribe en la fila TOTAL la suma de "% cuenca" y de "Área (km²)"
        de las filas de dato (0..self._n_filas_uso_suelo_cn - 1).

        El % acumulado se colorea: verde si queda dentro de ±1% de 100
        (mismo margen que ya usaba el aviso de _on_distribuir_area_por_porcentaje),
        rojo si se aleja -- así el usuario ve de un vistazo, sin leer
        ningún mensaje, si el reparto de coberturas está completo.
        """
        suma_pct = 0.0
        suma_area = 0.0
        for row in range(self._n_filas_uso_suelo_cn):
            for col, acumulador in ((5, "pct"), (6, "area")):
                item = self.tabla_cn.item(row, col)
                texto = item.text().strip() if item else ""
                if not texto:
                    continue
                try:
                    valor = float(texto)
                except ValueError:
                    continue  # celda a medio editar; se ignora en la suma, no se interrumpe
                if acumulador == "pct":
                    suma_pct += valor
                else:
                    suma_area += valor

        fila_total = self._n_filas_uso_suelo_cn
        # blockSignals: escribir en la fila TOTAL dispara itemChanged, que
        # volvería a llamar a este mismo método -- no es una recursión
        # infinita (la guarda de _on_tabla_cn_item_changed ya ignora la
        # fila TOTAL), pero sí un recálculo redundante en cada celda.
        self.tabla_cn.blockSignals(True)
        try:
            item_pct = self.tabla_cn.item(fila_total, 5)
            item_area = self.tabla_cn.item(fila_total, 6)
            if item_pct is not None:
                item_pct.setText(f"{suma_pct:.1f}")
                color = QColor("#1B5E20") if abs(suma_pct - 100.0) <= 1.0 else QColor("#B3261E")
                item_pct.setForeground(color)
            if item_area is not None:
                item_area.setText(f"{suma_area:.4f}")
        finally:
            self.tabla_cn.blockSignals(False)

    def _on_calcular_cn(self):
        try:
            usos = []
            for row in range(self._n_filas_uso_suelo_cn):
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
        self.spin_coef_c.setDecimals(3)
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

        self.spin_lca_km_tc = QDoubleSpinBox()
        self.spin_lca_km_tc.setRange(0.0, 200.0)
        self.spin_lca_km_tc.setDecimals(3)
        self.spin_lca_km_tc.setSpecialValueText("(usar 0.5 * Lc)")
        f_extra.addRow("Snyder — distancia al centroide Lca (km, 0 = usar 0.5*Lc):", self.spin_lca_km_tc)

        self.spin_ct_snyder_tc = QDoubleSpinBox()
        self.spin_ct_snyder_tc.setRange(0.5, 8.0)
        self.spin_ct_snyder_tc.setDecimals(2)
        self.spin_ct_snyder_tc.setValue(2.0)
        f_extra.addRow("Snyder — coeficiente Ct (1.8-2.2 típico EE.UU.; calibrar):", self.spin_ct_snyder_tc)

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
        # scroll de la pestaña, para ver los 14-16 métodos. Un
        # setMinimumHeight(260) fijo tampoco alcanzaba (260 px / 24 px por
        # fila ≈ 11 filas visibles, menos que los 14 métodos + fila de
        # Promedio). Se usa ajustar_alto_tabla() -- el mismo helper que ya
        # dimensiona el resto de tablas de resultados del plugin -- llamado
        # en _on_calcular_tc() DESPUÉS de insertar las filas, para que se
        # ajuste al conteo real de métodos y no a un número fijo que puede
        # quedarse corto si se agregan más adelante.
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
        self.tabla_resultado_cav = crear_tabla_parametros()
        v_cav.addWidget(self.tabla_resultado_cav)
        self.canvas_cav = CavCanvas(self)
        v_cav.addWidget(self.canvas_cav)
        v.addWidget(gb_cav)

        # ==================================================================
        # COEFICIENTE DE ESCORRENTÍA POR DIFERENTES MÉTODOS
        # ==================================================================
        gb_esc = QGroupBox(
            "Coeficiente de escorrentía C — métodos de cálculo (además del manual)"
        )
        v_esc = QVBoxLayout(gb_esc)
        lbl_esc_intro = QLabel(
            "El coeficiente de escorrentía C (arriba, «Coef. de escorrentía C — solo método FAA») "
            "trae por defecto <b>0.5</b>: un valor de referencia GENÉRICO, a mitad del rango habitual "
            "0.1-0.9 del Método Racional, sin corresponder a ninguna cobertura ni suelo en particular "
            "-- es un punto de partida a reemplazar, no una estimación. Esta sección ofrece dos formas "
            "trazables de llegar a un C con sustento: <b>ponderado por cobertura</b> (mismo espíritu "
            "que la tabla de Número de Curva de la Pestaña 3) y <b>derivado del Número de Curva ya "
            "calculado</b> (C = Q/P con la MISMA ecuación SCS-CN que el resto del plugin, no una "
            "fórmula de conversión aparte)."
        )
        lbl_esc_intro.setWordWrap(True)
        v_esc.addWidget(lbl_esc_intro)

        h_esc_sel = QHBoxLayout()
        h_esc_sel.addWidget(QLabel("Método:"))
        self.combo_metodo_c = QComboBox()
        self.combo_metodo_c.addItem("Ponderado por uso de suelo / cobertura", "ponderado")
        self.combo_metodo_c.addItem("Desde el Número de Curva (Pestaña 3)", "desde_cn")
        self.combo_metodo_c.currentIndexChanged.connect(
            lambda: self.stack_metodo_c.setCurrentIndex(self.combo_metodo_c.currentIndex()))
        h_esc_sel.addWidget(self.combo_metodo_c)
        h_esc_sel.addStretch()
        v_esc.addLayout(h_esc_sel)

        self.stack_metodo_c = QStackedWidget()

        # -- Página: ponderado por cobertura --
        _pag_pond = QWidget()
        _v_pond = QVBoxLayout(_pag_pond)
        _v_pond.addWidget(QLabel(
            "Edite el <b>Área (km²)</b> de cada cobertura presente en su cuenca (0 = no está presente) "
            "y, si lo desea, el C de cada fila -- son valores ORIENTATIVOS de uso extendido en "
            "ingeniería hidrológica para el Método Racional, no un valor normativo fijo."))
        self.tabla_coef_c_ponderado = TablaPegable(len(runoff_coefficient.TABLA_COEFICIENTES_C_DEFAULT), 3)
        self.tabla_coef_c_ponderado.setHorizontalHeaderLabels(["Cobertura", "C", "Área (km²)"])
        for _i, (_nombre, _c_tip, _c_min, _c_max) in enumerate(runoff_coefficient.TABLA_COEFICIENTES_C_DEFAULT):
            self.tabla_coef_c_ponderado.setItem(_i, 0, QTableWidgetItem(_nombre))
            self.tabla_coef_c_ponderado.setItem(_i, 1, QTableWidgetItem(str(_c_tip)))
            self.tabla_coef_c_ponderado.setItem(_i, 2, QTableWidgetItem("0.0"))
        aplicar_columna_elastica(self.tabla_coef_c_ponderado, indice_columna_larga=0)
        ajustar_alto_tabla(self.tabla_coef_c_ponderado, filas_visibles_max=12)
        _v_pond.addWidget(self.tabla_coef_c_ponderado)
        self.stack_metodo_c.addWidget(_pag_pond)

        # -- Página: desde el CN --
        _pag_cn = QWidget()
        _f_cn = QFormLayout(_pag_cn)
        _f_cn.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.spin_c_desde_cn_p = QDoubleSpinBox()
        self.spin_c_desde_cn_p.setRange(0.1, 1000.0)
        self.spin_c_desde_cn_p.setValue(60.0)
        _f_cn.addRow("Lámina de diseño P (mm, típicamente el P24 de la Pestaña 5):", self.spin_c_desde_cn_p)
        _lbl_cn_s = QLabel("(la retención potencial máxima S se toma del Número de Curso "
                           "ya calculado en la Pestaña 3; calcúlelo ahí primero)")
        _lbl_cn_s.setWordWrap(True)
        _f_cn.addRow(_lbl_cn_s)
        self.stack_metodo_c.addWidget(_pag_cn)

        v_esc.addWidget(self.stack_metodo_c)

        h_esc_btn = QHBoxLayout()
        btn_autocompletar_c = QPushButton("Autocompletar P24 (Pestaña 5)")
        btn_autocompletar_c.clicked.connect(self._on_autocompletar_coef_c)
        limitar_ancho_boton(btn_autocompletar_c)
        h_esc_btn.addWidget(btn_autocompletar_c)
        btn_calc_c = QPushButton("Calcular C")
        btn_calc_c.clicked.connect(self._on_calcular_coef_c)
        limitar_ancho_boton(btn_calc_c)
        h_esc_btn.addWidget(btn_calc_c)
        self.btn_usar_c = QPushButton("Usar este C arriba (Método Racional)")
        self.btn_usar_c.clicked.connect(self._on_usar_coef_c_calculado)
        self.btn_usar_c.setEnabled(False)
        limitar_ancho_boton(self.btn_usar_c)
        h_esc_btn.addWidget(self.btn_usar_c)
        h_esc_btn.addStretch()
        v_esc.addLayout(h_esc_btn)

        self.cuadro_coef_c = CuadroResumenImpacto(ancho_maximo=720)
        self.cuadro_coef_c.actualizar(
            titulo="C SIN CALCULAR", valor_principal="—",
            subtitulo="Elija un método y pulse «Calcular C»")
        centrar_en_layout(self.cuadro_coef_c, v_esc)
        self.tabla_resultado_coef_c = crear_tabla_parametros()
        v_esc.addWidget(self.tabla_resultado_coef_c)
        v.addWidget(gb_esc)

        # ==================================================================
        # COEFICIENTE DE RUGOSIDAD DE MANNING POR DIFERENTES MÉTODOS
        # ==================================================================
        gb_rug = QGroupBox(
            "Coeficiente de rugosidad de Manning n — métodos de cálculo (además del manual de Kerby)"
        )
        v_rug = QVBoxLayout(gb_rug)
        lbl_rug_intro = QLabel(
            "El n de Kerby (arriba) también admite un valor manual sin sustento trazable. Esta sección "
            "ofrece cuatro familias de método reconocidas en hidráulica fluvial: "
            "<b>granulométricos</b> (relacionan n con el tamaño del sedimento del lecho), el "
            "<b>aditivo de Cowan</b> (ajusta un n base por inspección visual del tramo, sin "
            "granulometría), <b>logarítmico de Keulegan</b> (de la mecánica de fluidos, base de los "
            "modelos 2D tipo Iber/TELEMAC), y <b>ponderación en secciones compuestas</b> (cuando la "
            "rugosidad cambia entre el cauce principal y la llanura de inundación). La quinta familia "
            "-- calibración inversa contra marcas de agua, o clasificación satelital NDVI -- no se "
            "calcula aquí: la primera exige un modelo hidráulico ya corrido con datos de campo, y la "
            "segunda un ráster de cobertura ya clasificado; son flujos de trabajo con insumos propios, "
            "no una fórmula que este botón pueda completar sin ellos."
        )
        lbl_rug_intro.setWordWrap(True)
        v_rug.addWidget(lbl_rug_intro)

        h_rug_sel = QHBoxLayout()
        h_rug_sel.addWidget(QLabel("Método:"))
        self.combo_metodo_n = QComboBox()
        self.combo_metodo_n.addItem("Granulométrico (Strickler / Limerinos / Meyer-Peter & Müller / Bray)",
                                    "granulometrico")
        self.combo_metodo_n.addItem("Aditivo de Cowan (1956)", "cowan")
        self.combo_metodo_n.addItem("Logarítmico de Keulegan", "keulegan")
        self.combo_metodo_n.addItem("Ponderación en secciones compuestas (Horton-Einstein / Lotter)",
                                    "compuesta")
        self.combo_metodo_n.currentIndexChanged.connect(
            lambda: self.stack_metodo_n.setCurrentIndex(self.combo_metodo_n.currentIndex()))
        h_rug_sel.addWidget(self.combo_metodo_n)
        h_rug_sel.addStretch()
        v_rug.addLayout(h_rug_sel)

        self.stack_metodo_n = QStackedWidget()

        # -- Página: granulométrico --
        _pag_gran = QWidget()
        _f_gran = QFormLayout(_pag_gran)
        _f_gran.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        _lbl_gran = QLabel(
            "Ingrese los datos que tenga (de tamizado o conteo Wolman); se calculan todos los métodos "
            "para los que haya datos suficientes y se omiten los demás. 0 = sin dato.")
        _lbl_gran.setWordWrap(True)
        _f_gran.addRow(_lbl_gran)
        self.spin_gran_d50 = QDoubleSpinBox(); self.spin_gran_d50.setRange(0.0, 5.0)
        self.spin_gran_d50.setDecimals(4); self.spin_gran_d50.setValue(0.050)
        _f_gran.addRow("d50 (m, para Strickler y Bray):", self.spin_gran_d50)
        self.spin_gran_d84 = QDoubleSpinBox(); self.spin_gran_d84.setRange(0.0, 5.0)
        self.spin_gran_d84.setDecimals(4); self.spin_gran_d84.setValue(0.100)
        _f_gran.addRow("d84 (m, para Limerinos):", self.spin_gran_d84)
        self.spin_gran_d90 = QDoubleSpinBox(); self.spin_gran_d90.setRange(0.0, 5.0)
        self.spin_gran_d90.setDecimals(4); self.spin_gran_d90.setValue(0.120)
        _f_gran.addRow("d90 (m, para Meyer-Peter & Müller):", self.spin_gran_d90)
        self.spin_gran_rh = QDoubleSpinBox(); self.spin_gran_rh.setRange(0.0, 500.0)
        self.spin_gran_rh.setDecimals(3); self.spin_gran_rh.setValue(1.2)
        _f_gran.addRow("Radio hidráulico Rh (m, para Limerinos):", self.spin_gran_rh)
        self.stack_metodo_n.addWidget(_pag_gran)

        # -- Página: Cowan --
        _pag_cowan = QWidget()
        _f_cowan = QFormLayout(_pag_cowan)
        _f_cowan.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.combo_cowan_n0 = QComboBox()
        for _k, (_lo, _hi) in roughness_methods.COWAN_N0_MATERIAL_BASE.items():
            self.combo_cowan_n0.addItem(f"{_k} ({_lo}-{_hi})", (_lo + _hi) / 2.0)
        _f_cowan.addRow("n₀ — material base del canal:", self.combo_cowan_n0)
        self.combo_cowan_n1 = QComboBox()
        for _k, (_lo, _hi) in roughness_methods.COWAN_N1_IRREGULARIDAD.items():
            self.combo_cowan_n1.addItem(f"{_k} ({_lo}-{_hi})", (_lo + _hi) / 2.0)
        _f_cowan.addRow("n₁ — irregularidad de la superficie:", self.combo_cowan_n1)
        self.combo_cowan_n2 = QComboBox()
        for _k, (_lo, _hi) in roughness_methods.COWAN_N2_VARIACION_SECCION.items():
            self.combo_cowan_n2.addItem(f"{_k} ({_lo}-{_hi})", (_lo + _hi) / 2.0)
        _f_cowan.addRow("n₂ — variación de la sección transversal:", self.combo_cowan_n2)
        self.combo_cowan_n3 = QComboBox()
        for _k, (_lo, _hi) in roughness_methods.COWAN_N3_OBSTRUCCIONES.items():
            self.combo_cowan_n3.addItem(f"{_k} ({_lo}-{_hi})", (_lo + _hi) / 2.0)
        _f_cowan.addRow("n₃ — efecto de obstrucciones:", self.combo_cowan_n3)
        self.combo_cowan_n4 = QComboBox()
        for _k, (_lo, _hi) in roughness_methods.COWAN_N4_VEGETACION.items():
            self.combo_cowan_n4.addItem(f"{_k} ({_lo}-{_hi})", (_lo + _hi) / 2.0)
        _f_cowan.addRow("n₄ — vegetación:", self.combo_cowan_n4)
        self.combo_cowan_m5 = QComboBox()
        for _k, _v in roughness_methods.COWAN_M5_MEANDRIZACION.items():
            self.combo_cowan_m5.addItem(f"{_k} (m5={_v})", _v)
        _f_cowan.addRow("m₅ — grado de meandrización:", self.combo_cowan_m5)
        self.stack_metodo_n.addWidget(_pag_cowan)

        # -- Página: Keulegan --
        _pag_keu = QWidget()
        _f_keu = QFormLayout(_pag_keu)
        _f_keu.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.spin_keu_ks = QDoubleSpinBox(); self.spin_keu_ks.setRange(0.001, 5.0)
        self.spin_keu_ks.setDecimals(4); self.spin_keu_ks.setValue(0.150)
        _f_keu.addRow("Altura de aspereza de Nikuradse ks (m):", self.spin_keu_ks)
        self.stack_metodo_n.addWidget(_pag_keu)

        # -- Página: secciones compuestas --
        _pag_comp = QWidget()
        _v_comp = QVBoxLayout(_pag_comp)
        _v_comp.addWidget(QLabel(
            "Una fila por subsección (p.ej. cauce principal + llanuras izquierda/derecha). El radio "
            "hidráulico total, si lo deja en 0, se DERIVA de las propias subsecciones "
            "(A_total/P_total) — es la forma geométricamente consistente; solo indíquelo si cuenta con "
            "un valor propio medido en campo."))
        self.tabla_secciones_compuestas = TablaPegable(3, 3)
        self.tabla_secciones_compuestas.setHorizontalHeaderLabels(
            ["Perímetro mojado Pi (m)", "Radio hidráulico Rhi (m)", "n de la subsección"])
        ajustar_alto_tabla(self.tabla_secciones_compuestas, filas_visibles_max=8)
        _v_comp.addWidget(self.tabla_secciones_compuestas)
        _h_comp_rh = QHBoxLayout()
        _h_comp_rh.addWidget(QLabel("Radio hidráulico TOTAL de la sección (m, 0 = derivarlo):"))
        self.spin_comp_rh_total = QDoubleSpinBox()
        self.spin_comp_rh_total.setRange(0.0, 500.0)
        self.spin_comp_rh_total.setDecimals(3)
        self.spin_comp_rh_total.setSpecialValueText("(derivar de las subsecciones)")
        _h_comp_rh.addWidget(self.spin_comp_rh_total)
        _h_comp_rh.addStretch()
        _v_comp.addLayout(_h_comp_rh)
        self.stack_metodo_n.addWidget(_pag_comp)

        v_rug.addWidget(self.stack_metodo_n)

        h_rug_btn = QHBoxLayout()
        btn_calc_n = QPushButton("Calcular n")
        btn_calc_n.clicked.connect(self._on_calcular_coef_n)
        limitar_ancho_boton(btn_calc_n)
        h_rug_btn.addWidget(btn_calc_n)
        self.btn_usar_n = QPushButton("Usar este n arriba (Kerby)")
        self.btn_usar_n.clicked.connect(self._on_usar_coef_n_calculado)
        self.btn_usar_n.setEnabled(False)
        limitar_ancho_boton(self.btn_usar_n)
        h_rug_btn.addWidget(self.btn_usar_n)
        h_rug_btn.addStretch()
        v_rug.addLayout(h_rug_btn)

        self.cuadro_coef_n = CuadroResumenImpacto(ancho_maximo=720)
        self.cuadro_coef_n.actualizar(
            titulo="n SIN CALCULAR", valor_principal="—",
            subtitulo="Elija un método y pulse «Calcular n»")
        centrar_en_layout(self.cuadro_coef_n, v_rug)
        self.tabla_resultado_coef_n = crear_tabla_parametros()
        v_rug.addWidget(self.tabla_resultado_coef_n)
        v.addWidget(gb_rug)

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
            poblar_tabla_parametros(self.tabla_resultado_cav, [
                ("Cota mínima", resultado["z_min"], "m s.n.m."),
                ("Cota máxima", resultado["z_max"], "m s.n.m."),
                ("Área total", resultado["area_total_m2"] / 1e6, "km²"),
                ("Volumen total embalsable", resultado["volumen_total_m3"] / 1e6, "hm³", resultado["nota"]),
            ])
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

    # ------------------------------------------------------------------
    # Coeficiente de escorrentía C — métodos de cálculo
    # ------------------------------------------------------------------
    def _on_autocompletar_coef_c(self):
        tr_sel, p24_sel = self._tr_diseno_seleccionado()
        if tr_sel is None:
            QMessageBox.warning(
                self, "Falta el análisis de frecuencia",
                "Calcule primero el análisis de frecuencia en la Pestaña 5 y elija un Tr.")
            return
        self.spin_c_desde_cn_p.setValue(p24_sel)
        QMessageBox.information(
            self, "Autocompletado",
            f"P = {p24_sel} mm (P24 del Tr elegido en la Pestaña 6, Tr={tr_sel}).")

    def _on_calcular_coef_c(self):
        metodo = self.combo_metodo_c.currentData()
        try:
            if metodo == "ponderado":
                coberturas = []
                for fila in range(self.tabla_coef_c_ponderado.rowCount()):
                    item_area = self.tabla_coef_c_ponderado.item(fila, 2)
                    texto_area = item_area.text().strip() if item_area else ""
                    if not texto_area:
                        continue
                    area = float(texto_area.replace(",", "."))
                    if area <= 0:
                        continue
                    nombre = self.tabla_coef_c_ponderado.item(fila, 0).text()
                    c_val = float(self.tabla_coef_c_ponderado.item(fila, 1).text().replace(",", "."))
                    coberturas.append((nombre, area, c_val))
                if not coberturas:
                    QMessageBox.warning(
                        self, "Sin coberturas",
                        "Ingrese el área (km²) de al menos una cobertura (columna «Área (km²)»).")
                    return
                r = runoff_coefficient.coeficiente_escorrentia_ponderado(coberturas)
                self.coef_c_calculado = r["C_ponderado"]
                filas = [("C ponderado", r["C_ponderado"], "adim.",
                         f"{r['n_coberturas']} coberturas, área total {r['area_total_km2']} km²")]
                for d in r["detalle"]:
                    filas.append((d["cobertura"], d["C"], "", f"{d['porcentaje']}% del área ({d['area_km2']} km²)"))
                poblar_tabla_parametros(self.tabla_resultado_coef_c, filas, filas_visibles_max=15)
                subtitulo = f"Ponderado por {r['n_coberturas']} coberturas, {r['area_total_km2']} km²"
            else:  # desde_cn
                if not self.cn_resultados:
                    QMessageBox.warning(
                        self, "Falta el Número de Curva",
                        "Calcule primero el Número de Curva en la Pestaña 3.")
                    return
                r = runoff_coefficient.coeficiente_escorrentia_desde_cn(
                    self.spin_c_desde_cn_p.value(), self.cn_resultados["S_mm"])
                self.coef_c_calculado = r["C_desde_CN"]
                poblar_tabla_parametros(self.tabla_resultado_coef_c, [
                    ("C desde el Número de Curva", r["C_desde_CN"], "adim.", r["nota"]),
                    ("Lámina de diseño P", r["P_mm"], "mm"),
                    ("Retención potencial máxima S", r["S_mm"], "mm", "Pestaña 3"),
                    ("Abstracción inicial Ia", r["Ia_mm"], "mm"),
                    ("Escorrentía directa Q", r["Q_mm"], "mm"),
                    ("Pérdidas totales (Ia + infiltración)", r["perdidas_mm"], "mm"),
                ])
                subtitulo = f"P={r['P_mm']} mm, S={r['S_mm']} mm (Pestaña 3)"

            self.btn_usar_c.setEnabled(True)
            tipo = "exito" if 0.15 <= self.coef_c_calculado <= 0.85 else "atencion"
            self.cuadro_coef_c.actualizar(
                titulo="COEFICIENTE DE ESCORRENTÍA CALCULADO",
                valor_principal=f"C = {self.coef_c_calculado:.3f}",
                subtitulo=subtitulo,
                metricas=[("Método", "Ponderado por cobertura" if metodo == "ponderado" else "Desde CN")],
                leyenda="pulse «Usar este C arriba» para aplicarlo al Método Racional (Pestaña 4)",
                tipo=tipo)
        except (runoff_coefficient.RunoffCoefficientError, ValueError) as e:
            QMessageBox.warning(self, "No se pudo calcular C", str(e))
        except Exception as e:
            QMessageBox.critical(self, "Error calculando el coeficiente de escorrentía", str(e))

    def _on_usar_coef_c_calculado(self):
        if getattr(self, "coef_c_calculado", None) is None:
            return
        self.spin_coef_c.setValue(self.coef_c_calculado)
        QMessageBox.information(
            self, "Aplicado",
            f"C = {self.coef_c_calculado:.3f} aplicado como «Coef. de escorrentía C» arriba.")

    # ------------------------------------------------------------------
    # Coeficiente de rugosidad de Manning n — métodos de cálculo
    # ------------------------------------------------------------------
    def _on_calcular_coef_n(self):
        metodo = self.combo_metodo_n.currentData()
        try:
            if metodo == "granulometrico":
                r = roughness_methods.comparar_metodos_granulometricos(
                    d50_m=self.spin_gran_d50.value() or None,
                    d84_m=self.spin_gran_d84.value() or None,
                    d90_m=self.spin_gran_d90.value() or None,
                    radio_hidraulico_m=self.spin_gran_rh.value() or None,
                )
                valores = [d["n"] for d in r["resultados"].values()]
                n_final = sum(valores) / len(valores)
                self.coef_n_calculado = n_final
                filas = [("n promedio de los métodos disponibles", round(n_final, 4), "adim.",
                         f"{len(valores)} de 3 métodos calculados")]
                for datos in r["resultados"].values():
                    filas.append((datos["metodo"], datos["n"], "", datos.get("nota", "")))
                if r["omitidos"]:
                    filas.append(("Omitidos por falta de dato", "; ".join(r["omitidos"]), ""))
                subtitulo = f"promedio de {len(valores)} método(s) granulométrico(s)"
            elif metodo == "cowan":
                r = roughness_methods.n_cowan(
                    n0=self.combo_cowan_n0.currentData(), n1=self.combo_cowan_n1.currentData(),
                    n2=self.combo_cowan_n2.currentData(), n3=self.combo_cowan_n3.currentData(),
                    n4=self.combo_cowan_n4.currentData(), m5=self.combo_cowan_m5.currentData(),
                )
                self.coef_n_calculado = r["n"]
                f = r["factores"]
                filas = [
                    ("n de Cowan", r["n"], "adim.", f"suma de factores = {r['suma_factores']}"),
                    ("n₀ (material base)", f["n0"], ""), ("n₁ (irregularidad)", f["n1"], ""),
                    ("n₂ (variación de sección)", f["n2"], ""), ("n₃ (obstrucciones)", f["n3"], ""),
                    ("n₄ (vegetación)", f["n4"], ""), ("m₅ (meandrización)", f["m5"], ""),
                ]
                subtitulo = "Método aditivo de Cowan (1956)"
            elif metodo == "keulegan":
                r = roughness_methods.n_keulegan(self.spin_keu_ks.value())
                self.coef_n_calculado = r["n"]
                filas = [("n de Keulegan", r["n"], "adim.", f"ks = {r['ks_m']} m")]
                subtitulo = "Logarítmico de Keulegan"
            else:  # compuesta
                subsecciones = []
                for fila in range(self.tabla_secciones_compuestas.rowCount()):
                    items = [self.tabla_secciones_compuestas.item(fila, c) for c in range(3)]
                    textos = [it.text().strip() if it else "" for it in items]
                    if not all(textos):
                        continue
                    p_i, rh_i, n_i = (float(t.replace(",", ".")) for t in textos)
                    subsecciones.append((p_i, rh_i, n_i))
                if not subsecciones:
                    QMessageBox.warning(
                        self, "Sin subsecciones",
                        "Ingrese al menos una fila completa (perímetro, radio hidráulico, n).")
                    return
                rh_total = self.spin_comp_rh_total.value() or None
                r_he = roughness_methods.n_equivalente_horton_einstein(
                    [(p, n) for p, _, n in subsecciones])
                r_lot = roughness_methods.n_equivalente_lotter(subsecciones, rh_total)
                self.coef_n_calculado = r_he["n_equivalente"]
                filas = [
                    ("Horton-Einstein (velocidad media igual)", r_he["n_equivalente"], "adim."),
                    ("Lotter (caudal = suma de parciales)", r_lot["n_equivalente"], "adim.",
                     f"Rh_total usado = {r_lot['radio_hidraulico_total_m']} m"),
                ]
                for i, (p_i, rh_i, n_i) in enumerate(subsecciones, 1):
                    filas.append((f"Subsección {i}", n_i, "", f"P={p_i} m, Rh={rh_i} m"))
                subtitulo = f"{len(subsecciones)} subsecciones (Horton-Einstein adoptado arriba)"

            poblar_tabla_parametros(self.tabla_resultado_coef_n, filas, filas_visibles_max=15)
            self.btn_usar_n.setEnabled(True)
            self.cuadro_coef_n.actualizar(
                titulo="COEFICIENTE DE RUGOSIDAD CALCULADO",
                valor_principal=f"n = {self.coef_n_calculado:.4f}",
                subtitulo=subtitulo,
                leyenda="pulse «Usar este n arriba» para aplicarlo a Kerby",
                tipo="exito" if 0.015 <= self.coef_n_calculado <= 0.15 else "atencion")
        except (roughness_methods.RoughnessError, ValueError) as e:
            QMessageBox.warning(self, "No se pudo calcular n", str(e))
        except Exception as e:
            QMessageBox.critical(self, "Error calculando el coeficiente de rugosidad", str(e))

    def _on_usar_coef_n_calculado(self):
        if getattr(self, "coef_n_calculado", None) is None:
            return
        self.spin_n_kerby.setValue(self.coef_n_calculado)
        QMessageBox.information(
            self, "Aplicado",
            f"n = {self.coef_n_calculado:.4f} aplicado como coeficiente de rugosidad de Kerby arriba.")

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
            lca_km = self.spin_lca_km_tc.value() or None

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
                ct_snyder=self.spin_ct_snyder_tc.value(),
                phi_espey=self.spin_phi_espey.value(),
                area_impermeable_frac=self.spin_area_imperm.value(),
                alpha_ventura_heras=self.spin_alpha_vh.value(),
                intensidad_lluvia_mm_h=self.spin_intensidad_izzard.value(),
                coef_retardo_izzard=self.spin_retardo_izzard.value(),
                p2_24h_mm=self.spin_p2_24h.value(),
                manning_n_sheet_flow=self.spin_n_manning_sheet.value(),
            )
            resultados = tc_methods.calcular_todos(params)
            # Se ordenan de menor a mayor Tc (los métodos con error, sin un
            # Tc_horas válido, quedan al final). self.tc_resultados se
            # guarda YA en este orden -- no solo la tabla -- porque
            # _usar_qp_pestaña6/_on_autocompletar_caudales_directos ubican
            # el método adoptado como
            # list(self.tc_resultados.keys())[checkedId()], y ese índice
            # debe seguir correspondiendo exactamente a la fila de la tabla.
            resultados_ordenados = dict(
                sorted(resultados.items(),
                       key=lambda kv: kv[1]["Tc_horas"] if kv[1]["Tc_horas"] is not None else float("inf"))
            )
            self.tc_resultados = resultados_ordenados

            self.tabla_tc.setRowCount(0)
            for nombre, datos in resultados_ordenados.items():
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

            # Fila final informativa con el promedio de los métodos sin
            # error (sin radio button propio: es un valor de referencia,
            # no un método adoptable como Tc de diseño).
            validos = [d for d in resultados_ordenados.values() if not d["error"]]
            if validos:
                row = self.tabla_tc.rowCount()
                self.tabla_tc.insertRow(row)
                prom_tc_h = sum(d["Tc_horas"] for d in validos) / len(validos)
                prom_tc_min = sum(d["Tc_min"] for d in validos) / len(validos)
                prom_tlag_min = sum(d["tlag_min"] for d in validos) / len(validos)
                item_nombre = QTableWidgetItem(f"Promedio ({len(validos)} métodos)")
                fuente = item_nombre.font()
                fuente.setBold(True)
                item_nombre.setFont(fuente)
                self.tabla_tc.setItem(row, 1, item_nombre)
                self.tabla_tc.setItem(row, 2, QTableWidgetItem("—"))
                self.tabla_tc.setItem(row, 3, QTableWidgetItem(f"{prom_tc_h:.3f}"))
                self.tabla_tc.setItem(row, 4, QTableWidgetItem(f"{prom_tc_min:.1f}"))
                self.tabla_tc.setItem(row, 5, QTableWidgetItem(f"{prom_tlag_min:.1f}"))

            # +2 de margen sobre el conteo real de filas: sin él, la última
            # fila (el Promedio) queda justo al borde y algunos estilos de
            # QGIS recortan un par de píxeles del borde inferior.
            ajustar_alto_tabla(self.tabla_tc, filas_visibles_max=self.tabla_tc.rowCount() + 2)

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

        # Los 4 botones se agregan a un QHBoxLayout sin ningún addStretch();
        # QPushButton admite crecer horizontalmente por defecto (política
        # Minimum, no Fixed), así que sin un tope explícito se repartían
        # todo el ancho sobrante de la fila a partes iguales, viéndose
        # mucho más anchos de lo que su texto necesita.
        h_botones_tabla = QHBoxLayout()
        btn_agregar_fila = QPushButton("Agregar fila")
        btn_agregar_fila.clicked.connect(lambda: self.tabla_entrada_manual.setRowCount(self.tabla_entrada_manual.rowCount() + 1))
        limitar_ancho_boton(btn_agregar_fila)
        h_botones_tabla.addWidget(btn_agregar_fila)

        btn_quitar_fila = QPushButton("Quitar fila seleccionada")
        btn_quitar_fila.clicked.connect(self._on_quitar_fila_tabla_manual)
        limitar_ancho_boton(btn_quitar_fila)
        h_botones_tabla.addWidget(btn_quitar_fila)

        btn_limpiar_tabla = QPushButton("Limpiar tabla")
        btn_limpiar_tabla.clicked.connect(lambda: self.tabla_entrada_manual.clearContents())
        limitar_ancho_boton(btn_limpiar_tabla)
        h_botones_tabla.addWidget(btn_limpiar_tabla)

        btn_usar_tabla = QPushButton("Usar datos de esta tabla")
        btn_usar_tabla.clicked.connect(self._on_usar_serie_manual)
        limitar_ancho_boton(btn_usar_tabla)
        h_botones_tabla.addWidget(btn_usar_tabla)
        h_botones_tabla.addStretch()

        v_manual.addLayout(h_botones_tabla)
        v.addWidget(gb_manual)

        gb_analisis = QGroupBox("2. Análisis de frecuencia")
        v_analisis = QVBoxLayout(gb_analisis)
        h_a = QHBoxLayout()
        v_analisis.addLayout(h_a)
        self.combo_alpha_ks = QComboBox()
        self.combo_alpha_ks.addItems(["0.10", "0.05", "0.01"])
        self.combo_alpha_ks.setCurrentText("0.05")
        h_a.addWidget(QLabel("Nivel de significancia (alpha):"))
        h_a.addWidget(self.combo_alpha_ks)

        self.combo_metodo_ajuste = QComboBox()
        self.combo_metodo_ajuste.addItem("Momentos-L (Hosking) — recomendado", "momentos_l")
        self.combo_metodo_ajuste.addItem("Momentos ordinarios (clásico)", "momentos")
        h_a.addWidget(QLabel("Método de ajuste:"))
        h_a.addWidget(self.combo_metodo_ajuste)

        self.btn_analizar_frecuencia = QPushButton("Ajustar distribuciones y calcular precipitaciones de diseño")
        self.btn_analizar_frecuencia.clicked.connect(self._on_analizar_frecuencia)
        limitar_ancho_boton(self.btn_analizar_frecuencia)
        h_a.addWidget(self.btn_analizar_frecuencia)
        h_a.addStretch()

        lbl_metodo_ajuste = QLabel(
            "<b>Método de ajuste de parámetros:</b> los <b>momentos ordinarios</b> (media, desviación y "
            "sesgo) elevan las desviaciones al cuadrado y al cubo, así que un solo dato extremo pesa "
            "muchísimo — y estas series son, por construcción, series de valores extremos, a menudo de "
            "solo 20-40 años. El coeficiente de sesgo muestral es especialmente inestable en muestras "
            "cortas. Los <b>momentos-L</b> son combinaciones lineales de los estadísticos de orden "
            "(ningún dato entra elevado a una potencia): son mucho más robustos ante valores atípicos y "
            "menos sesgados en series cortas, y son hoy el estándar en análisis regional de frecuencias "
            "(Hosking &amp; Wallis, 1997). La GEV de este plugin ya se ajustaba así desde el inicio; "
            "desde la v0.2.48 las otras 8 distribuciones también pueden hacerlo. Cambie el método y "
            "vuelva a ajustar para comparar el efecto sobre su propia serie."
        )
        lbl_metodo_ajuste.setWordWrap(True)
        v_analisis.addWidget(lbl_metodo_ajuste)
        v.addWidget(gb_analisis)

        lbl_pruebas_bondad = QLabel(
            "Cada distribución se somete a <b>tres</b> pruebas de bondad de ajuste, no solo a "
            "Kolmogorov-Smirnov: <b>KS</b> mide la máxima distancia entre la curva teórica y la "
            "empírica (es más sensible al CENTRO de la distribución), <b>Anderson-Darling</b> pondera "
            "mucho más las COLAS, y <b>Chi-cuadrado</b> compara frecuencias por clases equiprobables. "
            "La diferencia importa: la precipitación de diseño se lee en la cola alta (Tr=100, 500, "
            "1000 años), así que una distribución puede pasar KS holgadamente y aun así ajustar mal "
            "justo donde se la va a usar — caso verificado en pruebas de este plugin, donde KS aceptó "
            "una Normal para datos claramente log-normales y AD/χ² la rechazaron. Un asterisco (*) "
            "junto a AD indica que su valor crítico es el del caso general y por tanto <i>permisivo</i>, "
            "porque para esa distribución la bibliografía no publica uno específico para parámetros "
            "estimados de la propia muestra."
        )
        lbl_pruebas_bondad.setWordWrap(True)
        v.addWidget(lbl_pruebas_bondad)

        self.tabla_distribuciones = QTableWidget(0, 8)
        self.tabla_distribuciones.setHorizontalHeaderLabels(
            ["Distribución", "Parámetros", "D (KS)", "D crít.", "A² (AD)", "A² crít.",
             "χ² (p-valor)", "Pruebas que pasa"]
        )
        # Los símbolos ya identifican la prueba a quien conoce las siglas
        # (D=Kolmogorov-Smirnov, A²=Anderson-Darling, χ²=Chi-cuadrado),
        # pero no a simple vista -- se deja el nombre completo en el
        # tooltip de cada encabezado, sin gastar ancho de columna en
        # texto largo que ya está resuelto por el símbolo.
        for _col, _tip in ((2, "Prueba de Kolmogorov-Smirnov: estadístico D (máxima distancia entre "
                              "la distribución empírica y la ajustada)."),
                            (3, "Kolmogorov-Smirnov: valor D crítico al nivel de significancia elegido. "
                              "Pasa la prueba si D < D crítico."),
                            (4, "Prueba de Anderson-Darling: estadístico A² (da más peso a las colas "
                              "que Kolmogorov-Smirnov)."),
                            (5, "Anderson-Darling: valor A² crítico. Pasa la prueba si A² < A² crítico."),
                            (6, "Prueba de Chi-cuadrado (χ²): p-valor de la bondad de ajuste por clases "
                              "de frecuencia. Pasa la prueba si p-valor ≥ 0.05.")):
            self.tabla_distribuciones.horizontalHeaderItem(_col).setToolTip(_tip)
        # Antes las 5 columnas estaban en modo Stretch parejo, lo que
        # dejaba D(KS)/D crítico/¿Pasa KS? (textos cortos) demasiado
        # anchas y obligaba a usar scroll horizontal para ver "Parámetros"
        # completo. Ahora solo "Parámetros" se lleva el espacio sobrante;
        # el resto tiene un ancho fijo angosto acorde a su contenido.
        cabecera_dist = self.tabla_distribuciones.horizontalHeader()
        cabecera_dist.setSectionResizeMode(0, QHeaderView.Interactive)
        cabecera_dist.setSectionResizeMode(1, QHeaderView.Stretch)
        for _col_fija in (2, 3, 4, 5, 6, 7):
            cabecera_dist.setSectionResizeMode(_col_fija, QHeaderView.Fixed)
        self.tabla_distribuciones.setColumnWidth(0, 200)
        for _col_fija, _ancho in ((2, 70), (3, 70), (4, 70), (5, 70), (6, 95), (7, 150)):
            self.tabla_distribuciones.setColumnWidth(_col_fija, _ancho)
        v.addWidget(self.tabla_distribuciones)

        self.canvas_frecuencia = FrequencyCanvas(self, width=6.5, height=4.8)
        v.addWidget(self.canvas_frecuencia)

        # ---------- Diagnóstico gráfico de la distribución ----------
        gb_diag = QGroupBox(
            "Diagnóstico gráfico de la distribución — densidad, distribución, supervivencia, "
            "riesgo, riesgo acumulado, P-P y Q-Q"
        )
        v_diag = QVBoxLayout(gb_diag)
        lbl_diag = QLabel(
            "El gráfico de arriba compara los CUANTILES de cada distribución; este panel diagnostica "
            "UNA distribución elegida con las seis funciones estándar de un análisis de frecuencia: "
            "<b>densidad</b> f(x) contra el histograma de los datos; <b>distribución</b> F(x) contra la "
            "probabilidad empírica; <b>supervivencia</b> S(x)=1−F(x), la probabilidad de EXCEDENCIA; "
            "<b>riesgo</b> instantáneo h(x)=f(x)/S(x) y <b>riesgo acumulado</b> H(x)=−ln S(x), del "
            "análisis de supervivencia (una cola pesada se ve como h(x) creciente en vez de plano); y "
            "<b>P-P/Q-Q</b>, que separan dónde falla el ajuste: el P-P se aleja de la diagonal si falla "
            "en el CUERPO de los datos, el Q-Q si falla en las COLAS — la zona que más importa para "
            "periodos de retorno grandes."
        )
        lbl_diag.setWordWrap(True)
        v_diag.addWidget(lbl_diag)

        h_diag = QHBoxLayout()
        h_diag.addWidget(QLabel("Distribución a diagnosticar:"))
        self.combo_dist_diagnostico = QComboBox()
        self.combo_dist_diagnostico.addItem("(la de mejor ajuste)", None)
        h_diag.addWidget(self.combo_dist_diagnostico)
        btn_diag = QPushButton("Generar diagnóstico gráfico")
        btn_diag.clicked.connect(self._on_generar_diagnostico_distribucion)
        limitar_ancho_boton(btn_diag)
        h_diag.addWidget(btn_diag)
        h_diag.addStretch()
        v_diag.addLayout(h_diag)

        self.canvas_diagnostico_distribucion = DiagnosticoDistribucionCanvas(self)
        v_diag.addWidget(self.canvas_diagnostico_distribucion)
        v.addWidget(gb_diag)

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

        # ------- Análisis de frecuencia no estacionario -------
        gb_no_est = QGroupBox("Análisis de frecuencia NO ESTACIONARIO (tendencia en la serie)")
        v_ne = QVBoxLayout(gb_no_est)
        lbl_ne = QLabel(
            "El análisis clásico supone <b>estacionariedad</b>: que la distribución de la que provienen "
            "los máximos anuales es la misma todos los años. Si la serie tiene tendencia (cambio "
            "climático, cambio de uso del suelo, o un cambio de emplazamiento o instrumento en la "
            "estación), ese supuesto se rompe y el «Tr=100 años» deja de tener un valor único. Aquí se "
            "ajusta Normal o Gumbel con <b>tendencia lineal en el parámetro de posición</b>.<br><br>"
            "<b>Léase antes de usarlo en un diseño:</b> (1) una tendencia ajustada <b>no debe "
            "extrapolarse</b> lejos del periodo observado — proyectar 50 años a partir de 30 de datos no "
            "tiene respaldo; los años posteriores al último observado se marcan como extrapolación. "
            "(2) Debe ser <b>estadísticamente significativa</b> (se reporta el p-valor) y, sobre todo, "
            "tener una <b>causa física identificada</b>: una tendencia causada por un cambio de "
            "emplazamiento es un problema de datos que se corrige en el control de calidad, no una "
            "señal a modelar. (3) <b>No hay consenso</b> en la comunidad hidrológica sobre usar modelos "
            "no estacionarios en diseño (ver Serinaldi &amp; Kilsby 2015; Montanari &amp; Koutsoyiannis "
            "2014). Trate esto como un <b>análisis de sensibilidad</b> frente al valor estacionario, no "
            "como su reemplazo automático."
        )
        lbl_ne.setWordWrap(True)
        v_ne.addWidget(lbl_ne)

        h_ne = QHBoxLayout()
        h_ne.addWidget(QLabel("Distribución:"))
        self.combo_no_estacionario = QComboBox()
        self.combo_no_estacionario.addItem("Gumbel con tendencia en ξ", "gumbel")
        self.combo_no_estacionario.addItem("Normal con tendencia en μ", "normal")
        h_ne.addWidget(self.combo_no_estacionario)
        h_ne.addWidget(QLabel("Año inicial de la serie:"))
        self.spin_anio_inicial = QSpinBox()
        self.spin_anio_inicial.setRange(1900, 2100)
        self.spin_anio_inicial.setValue(1990)
        h_ne.addWidget(self.spin_anio_inicial)
        self.btn_no_estacionario = QPushButton("Analizar tendencia")
        self.btn_no_estacionario.clicked.connect(self._on_analizar_no_estacionario)
        limitar_ancho_boton(self.btn_no_estacionario)
        h_ne.addWidget(self.btn_no_estacionario)
        h_ne.addStretch()
        v_ne.addLayout(h_ne)

        self.tabla_no_estacionario = crear_tabla_parametros()
        v_ne.addWidget(self.tabla_no_estacionario)

        self.tabla_sensibilidad_no_est = QTableWidget(0, 5)
        self.tabla_sensibilidad_no_est.setHorizontalHeaderLabels(
            ["Tr (años)", "Estacionario (mm)", "Primer año (mm)", "Último año (mm)",
             "Último + 20 años (mm) — EXTRAPOLACIÓN"])
        for _c in range(5):
            self.tabla_sensibilidad_no_est.horizontalHeader().setSectionResizeMode(
                _c, QHeaderView.ResizeToContents)
        # SIN limitar_ancho_tabla: a diferencia de tabla_comparacion_distribuciones
        # (que gana una columna por cada T-Diseño que el usuario agregue, sin
        # tope), esta tiene siempre 5 columnas fijas -- no hay riesgo de que
        # crezca sin control, así que capar su ancho solo la recortaba sin
        # necesidad y obligaba a un scroll horizontal interno para ver la
        # última columna (justo la de la extrapolación, la más importante).
        h_tabla_ne = QHBoxLayout()
        h_tabla_ne.addWidget(self.tabla_sensibilidad_no_est)
        h_tabla_ne.addStretch()
        v_ne.addLayout(h_tabla_ne)

        self.cuadro_no_estacionario = CuadroResumenImpacto(ancho_maximo=700)
        self.cuadro_no_estacionario.actualizar(
            titulo="SIN ANALIZAR", valor_principal="—",
            subtitulo="Pulse «Analizar tendencia» para evaluar la estacionariedad de la serie")
        centrar_en_layout(self.cuadro_no_estacionario, v_ne)
        self.canvas_no_estacionario = FrequencyCanvas(self, width=6.8, height=6.2)
        v_ne.addWidget(self.canvas_no_estacionario)
        v.addWidget(gb_no_est)

        # ------- Bandas de confianza (bootstrap) -------
        gb_bandas = QGroupBox("Bandas de confianza de la precipitación de diseño (bootstrap)")
        v_bandas = QVBoxLayout(gb_bandas)
        lbl_bandas = QLabel(
            "El análisis de arriba devuelve <b>un único valor</b> de P24 por periodo de retorno, y esa "
            "cifra pasa tal cual al caudal de diseño y al dimensionamiento de la obra — como si fuera "
            "exacta. No lo es: se estimó con una muestra de unas pocas decenas de años, y con otra "
            "muestra igual de válida habría salido distinta. La incertidumbre además <b>crece con el "
            "periodo de retorno</b>: extrapolar a Tr=500 años con 30 datos es mucho más incierto que "
            "estimar Tr=5. El bootstrap la cuantifica remuestreando la serie observada con reposición "
            "y reajustando la distribución cada vez.<br><br>"
            "<b>Límite importante:</b> el bootstrap mide la incertidumbre por tener POCOS DATOS, no el "
            "error por haber elegido una distribución equivocada. Si la distribución no es la adecuada, "
            "la banda puede salir estrecha y centrada en el valor incorrecto — léala junto con las tres "
            "pruebas de bondad de ajuste, y compare las bandas de distintas distribuciones entre sí."
        )
        lbl_bandas.setWordWrap(True)
        v_bandas.addWidget(lbl_bandas)

        f_bandas = QFormLayout()
        f_bandas.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.combo_dist_bandas = QComboBox()
        self.combo_dist_bandas.addItem("(la de mejor ajuste)", None)
        f_bandas.addRow("Distribución:", self.combo_dist_bandas)
        self.spin_bootstrap_n = QSpinBox()
        self.spin_bootstrap_n.setRange(200, 20000)
        self.spin_bootstrap_n.setSingleStep(500)
        self.spin_bootstrap_n.setValue(2000)
        f_bandas.addRow("Número de remuestreos bootstrap:", self.spin_bootstrap_n)
        self.combo_nivel_confianza = QComboBox()
        for _txt, _val in (("90%", 0.90), ("95%", 0.95), ("99%", 0.99)):
            self.combo_nivel_confianza.addItem(_txt, _val)
        f_bandas.addRow("Nivel de confianza:", self.combo_nivel_confianza)
        v_bandas.addLayout(f_bandas)

        self.btn_calcular_bandas = QPushButton("Calcular bandas de confianza")
        self.btn_calcular_bandas.clicked.connect(self._on_calcular_bandas_confianza)
        limitar_ancho_boton(self.btn_calcular_bandas)
        v_bandas.addWidget(self.btn_calcular_bandas)

        self.tabla_bandas_confianza = QTableWidget(0, 6)
        self.tabla_bandas_confianza.setHorizontalHeaderLabels(
            ["Tr (años)", "Límite inferior", "Estimación central", "Límite superior",
             "Amplitud (mm)", "Amplitud (% del central)"])
        for _c in range(6):
            self.tabla_bandas_confianza.horizontalHeader().setSectionResizeMode(_c, QHeaderView.ResizeToContents)
        # SIN limitar_ancho_tabla: son siempre 6 columnas fijas (no crece
        # con la acción del usuario como sí lo hace tabla_comparacion_
        # distribuciones), así que el tope de 760 px solo la recortaba sin
        # necesidad -- con encabezados como "Amplitud (% del central)" el
        # ancho natural ya supera eso, y obligaba a scroll horizontal
        # interno para ver las últimas columnas.
        h_tabla_bandas = QHBoxLayout()
        h_tabla_bandas.addWidget(self.tabla_bandas_confianza)
        h_tabla_bandas.addStretch()
        v_bandas.addLayout(h_tabla_bandas)

        self.canvas_bandas_confianza = FrequencyCanvas(self, width=6.8, height=4.8)
        v_bandas.addWidget(self.canvas_bandas_confianza)
        v.addWidget(gb_bandas)

        # ---------------- 4. Curvas IDF ----------------
        gb_idf = QGroupBox("4. Curvas Intensidad-Duración-Frecuencia (IDF)")
        v_idf = QVBoxLayout(gb_idf)
        lbl_idf_info = QLabel(
            "Curvas IDF derivadas de las precipitaciones de diseño P24h(Tr) de arriba, para los "
            "periodos de retorno ya establecidos, mediante el mismo escalamiento potencial de "
            "Sherman P(d) = P24h·(d/1440min)^n usado para desagregar el hietograma en la pestaña 6 "
            "(exponente n editable abajo). El plugin no cuenta con series sub-diarias (pluviograma) "
            "para calibrar una curva IDF real observada en la zona; si dispone de una curva IDF "
            "regional oficial (SENAMHI/ANA) para su cuenca, debe preferirla para un diseño definitivo."
        )
        lbl_idf_info.setWordWrap(True)
        v_idf.addWidget(lbl_idf_info)

        f_idf = QFormLayout()
        f_idf.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.spin_exponente_idf = QDoubleSpinBox()
        self.spin_exponente_idf.setRange(0.05, 0.50)
        self.spin_exponente_idf.setSingleStep(0.01)
        self.spin_exponente_idf.setValue(0.20)
        f_idf.addRow("Exponente n de Sherman (mismo tipo que en la pestaña 6):", self.spin_exponente_idf)
        v_idf.addLayout(f_idf)

        self.btn_calcular_idf = QPushButton("Calcular curvas y ecuaciones IDF")
        self.btn_calcular_idf.clicked.connect(self._on_calcular_idf)
        limitar_ancho_boton(self.btn_calcular_idf)
        v_idf.addWidget(self.btn_calcular_idf)

        v_idf.addWidget(QLabel("<b>Ecuación potencial por periodo de retorno</b> (i = a·t^b, t en minutos):"))
        self.tabla_ecuaciones_idf = QTableWidget(0, 5)
        self.tabla_ecuaciones_idf.setHorizontalHeaderLabels(["Tr (años)", "Ecuación", "a", "b", "R²"])
        # Las 5 columnas son valores cortos de formato fijo (ninguna es texto
        # libre de longitud variable) -- igual que tabla_comparacion_distribuciones,
        # se ajustan todas a su contenido y se limita el ancho total de la
        # tabla, en vez de usar una columna Stretch que las infla a todo el
        # ancho de la pestaña (reportado: columna "Ecuación" desproporcionada).
        for _col in range(self.tabla_ecuaciones_idf.columnCount()):
            self.tabla_ecuaciones_idf.horizontalHeader().setSectionResizeMode(_col, QHeaderView.ResizeToContents)
        limitar_ancho_tabla(self.tabla_ecuaciones_idf, ancho_maximo=560)
        h_tabla_idf_centrada = QHBoxLayout()
        h_tabla_idf_centrada.addWidget(self.tabla_ecuaciones_idf)
        h_tabla_idf_centrada.addStretch()
        v_idf.addLayout(h_tabla_idf_centrada)

        # ---- Cuadro resumen enmarcado y centrado: ecuación IDF combinada ----
        frame_idf_resumen = QFrame()
        frame_idf_resumen.setObjectName("frameIdfResumen")
        frame_idf_resumen.setFrameShape(QFrame.StyledPanel)
        frame_idf_resumen.setStyleSheet(
            "QFrame#frameIdfResumen {"
            "  border: 2px solid #2c6fa8;"
            "  border-radius: 10px;"
            "  background-color: #eef5fb;"
            "}"
        )
        v_idf_resumen = QVBoxLayout(frame_idf_resumen)
        v_idf_resumen.setContentsMargins(16, 12, 16, 14)
        v_idf_resumen.setSpacing(6)

        lbl_idf_resumen_titulo = QLabel("ECUACIÓN IDF COMBINADA")
        lbl_idf_resumen_titulo.setAlignment(Qt.AlignCenter)
        lbl_idf_resumen_titulo.setStyleSheet(
            "font-weight: bold; font-size: 10.5pt; color: #1a4a70; letter-spacing: 1px;"
        )
        v_idf_resumen.addWidget(lbl_idf_resumen_titulo)

        lbl_idf_resumen_sub = QLabel("(ajustada sobre todos los puntos (Tr, t, i) de todas las curvas a la vez)")
        lbl_idf_resumen_sub.setAlignment(Qt.AlignCenter)
        lbl_idf_resumen_sub.setStyleSheet("font-size: 8pt; color: #4a4a4a; font-style: italic;")
        lbl_idf_resumen_sub.setWordWrap(True)
        v_idf_resumen.addWidget(lbl_idf_resumen_sub)

        linea_idf_1 = QFrame()
        linea_idf_1.setFrameShape(QFrame.HLine)
        linea_idf_1.setStyleSheet("color: #b9d3e6;")
        v_idf_resumen.addWidget(linea_idf_1)

        self.lbl_ecuacion_idf_combinada = QLabel("i = K · Trᵐ / tⁿ   —   sin calcular todavía")
        self.lbl_ecuacion_idf_combinada.setAlignment(Qt.AlignCenter)
        self.lbl_ecuacion_idf_combinada.setWordWrap(True)
        self.lbl_ecuacion_idf_combinada.setStyleSheet(
            "font-family: 'Consolas', 'Courier New', monospace; font-size: 13pt; font-weight: bold; "
            "color: #0d3757; padding: 4px 0px;"
        )
        v_idf_resumen.addWidget(self.lbl_ecuacion_idf_combinada)

        linea_idf_2 = QFrame()
        linea_idf_2.setFrameShape(QFrame.HLine)
        linea_idf_2.setStyleSheet("color: #b9d3e6;")
        v_idf_resumen.addWidget(linea_idf_2)

        grid_idf_params = QGridLayout()
        grid_idf_params.setHorizontalSpacing(28)
        grid_idf_params.setVerticalSpacing(2)
        _etiquetas_idf = [
            ("K (coef. de intensidad)", "lbl_idf_param_k"),
            ("m (exp. de Tr)", "lbl_idf_param_m"),
            ("n (exp. de t)", "lbl_idf_param_n"),
            ("R² (bondad de ajuste)", "lbl_idf_param_r2"),
        ]
        for col, (texto_desc, nombre_attr) in enumerate(_etiquetas_idf):
            lbl_desc = QLabel(texto_desc)
            lbl_desc.setAlignment(Qt.AlignCenter)
            lbl_desc.setStyleSheet("font-size: 7.7pt; color: #4a4a4a;")
            lbl_desc.setWordWrap(True)
            grid_idf_params.addWidget(lbl_desc, 0, col)
            lbl_val = QLabel("—")
            lbl_val.setAlignment(Qt.AlignCenter)
            lbl_val.setStyleSheet("font-size: 11pt; font-weight: bold; color: #0d3757;")
            setattr(self, nombre_attr, lbl_val)
            grid_idf_params.addWidget(lbl_val, 1, col)
        h_idf_grid_centrado = QHBoxLayout()
        h_idf_grid_centrado.addStretch()
        h_idf_grid_centrado.addLayout(grid_idf_params)
        h_idf_grid_centrado.addStretch()
        v_idf_resumen.addLayout(h_idf_grid_centrado)

        lbl_idf_leyenda = QLabel("i: intensidad (mm/h)  ·  Tr: periodo de retorno (años)  ·  t: duración (min)")
        lbl_idf_leyenda.setAlignment(Qt.AlignCenter)
        lbl_idf_leyenda.setStyleSheet("font-size: 7.7pt; color: #6a6a6a; font-style: italic;")
        lbl_idf_leyenda.setWordWrap(True)
        v_idf_resumen.addWidget(lbl_idf_leyenda)

        h_idf_resumen_centrado = QHBoxLayout()
        h_idf_resumen_centrado.addStretch()
        h_idf_resumen_centrado.addWidget(frame_idf_resumen, stretch=0)
        h_idf_resumen_centrado.addStretch()
        v_idf.addLayout(h_idf_resumen_centrado)

        self.canvas_idf_log = IdfCanvas(self, width=7.6, height=5.2)
        v_idf.addWidget(self.canvas_idf_log)

        lbl_idf_cartesiano = QLabel(
            "Mismas curvas IDF, en escala cartesiana (para ver la forma real, muy curvada -- se "
            "aplanan rápido a duraciones largas -- que la escala log-log de arriba no deja apreciar):"
        )
        lbl_idf_cartesiano.setWordWrap(True)
        v_idf.addWidget(lbl_idf_cartesiano)
        self.canvas_idf_cartesiano = IdfCanvas(self, width=7.6, height=5.2)
        v_idf.addWidget(self.canvas_idf_cartesiano)

        # ---- Métodos alternativos de generación de curvas IDF ----
        gb_metodos_idf = QGroupBox(
            "5. Otros métodos de generación de curvas IDF — Dyck-Peschke (Grobe), "
            "Frederich Bell (1969) e IILA-SENAMHI-UNI (1983)")
        v_mi = QVBoxLayout(gb_metodos_idf)
        lbl_mi = QLabel(
            "Las curvas de arriba usan el escalamiento genérico de Sherman con el exponente n que usted "
            "elija. Estos tres métodos se apoyan en información distinta y son los más usados en la "
            "práctica peruana, así que conviene compararlos antes de adoptar uno para diseño:<br><br>"
            "<b>Dyck y Peschke (Grobe)</b> — es el mismo escalamiento pero con n fijado en 0.25. No "
            "requiere calibrar nada: se aplica directo sobre la P24h. Su límite es el mismo: un "
            "exponente único no distingue el régimen pluviográfico de una región a otra.<br>"
            "<b>Frederich Bell (1969)</b> — deducido de lluvias convectivas de varias regiones del "
            "mundo. Necesita como referencia la lluvia de 60 min y 10 años; si no la tiene, el plugin "
            "la estima de su P24h(10 años). <b>Válido solo para 5–120 min y 2–100 años</b>: fuera de "
            "ese rango el plugin lo advierte en vez de callarlo.<br>"
            "<b>IILA-SENAMHI-UNI (1983)</b> — el estudio oficial de la hidrología del Perú. Sus "
            "parámetros a, K, b y n son <b>REGIONALES por subzona pluviométrica</b>: debe tomarlos de "
            "esa publicación para su cuenca. El plugin no los supone ni los inventa, porque unos "
            "parámetros arbitrarios darían curvas de aspecto creíble y sin ningún respaldo."
        )
        lbl_mi.setWordWrap(True)
        v_mi.addWidget(lbl_mi)

        f_mi = QFormLayout()
        f_mi.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.spin_bell_p60 = QDoubleSpinBox()
        self.spin_bell_p60.setRange(0.0, 500.0)
        self.spin_bell_p60.setDecimals(3)
        self.spin_bell_p60.setValue(0.0)
        f_mi.addRow("Bell — P(60 min, 10 años) en mm (0 = estimar desde la P24h):", self.spin_bell_p60)
        self.spin_iila_a = QDoubleSpinBox()
        self.spin_iila_a.setRange(0.0, 500.0)
        self.spin_iila_a.setDecimals(3)
        self.spin_iila_a.setValue(0.0)
        f_mi.addRow("IILA — parámetro a (0 = omitir este método):", self.spin_iila_a)
        self.spin_iila_k = QDoubleSpinBox()
        self.spin_iila_k.setRange(0.0, 5.0)
        self.spin_iila_k.setDecimals(4)
        self.spin_iila_k.setValue(0.5530)
        f_mi.addRow("IILA — parámetro K:", self.spin_iila_k)
        self.spin_iila_b = QDoubleSpinBox()
        self.spin_iila_b.setRange(0.0, 10.0)
        self.spin_iila_b.setDecimals(4)
        self.spin_iila_b.setValue(0.4000)
        f_mi.addRow("IILA — parámetro b (h):", self.spin_iila_b)
        self.spin_iila_n = QDoubleSpinBox()
        self.spin_iila_n.setRange(0.01, 1.5)
        self.spin_iila_n.setDecimals(4)
        self.spin_iila_n.setValue(0.2540)
        f_mi.addRow("IILA — parámetro n:", self.spin_iila_n)
        self.combo_tr_comparacion_idf = QComboBox()
        f_mi.addRow("Periodo de retorno para comparar los métodos:", self.combo_tr_comparacion_idf)
        v_mi.addLayout(f_mi)

        self.btn_metodos_idf = QPushButton("Generar y comparar los métodos de IDF")
        self.btn_metodos_idf.clicked.connect(self._on_calcular_metodos_idf)
        limitar_ancho_boton(self.btn_metodos_idf)
        v_mi.addWidget(self.btn_metodos_idf)

        self.cuadro_metodos_idf = CuadroResumenImpacto(ancho_maximo=760)
        self.cuadro_metodos_idf.actualizar(
            titulo="SIN CALCULAR", valor_principal="—",
            subtitulo="Compara la intensidad de diseño que da cada método para el mismo Tr")
        centrar_en_layout(self.cuadro_metodos_idf, v_mi)

        self.tabla_metodos_idf = crear_tabla_parametros()
        v_mi.addWidget(self.tabla_metodos_idf)
        self.canvas_metodos_idf_log = IdfCanvas(self, width=7.4, height=4.8)
        v_mi.addWidget(self.canvas_metodos_idf_log)
        v_mi.addWidget(QLabel("Mismas curvas en escala cartesiana:"))
        self.canvas_metodos_idf_cart = IdfCanvas(self, width=7.4, height=4.8)
        v_mi.addWidget(self.canvas_metodos_idf_cart)
        v_idf.addWidget(gb_metodos_idf)

        v.addWidget(gb_idf)

        self._agregar_pestaña_con_scroll(tab, "5. Precipitación Máx 24h")

    def _on_analizar_no_estacionario(self):
        if not self.serie_precip_anual:
            QMessageBox.warning(self, "Falta la serie",
                                 "Cargue primero la serie anual de precipitación máxima en 24h.")
            return
        try:
            datos = self.serie_precip_anual.valores_mm
            anio0 = self.spin_anio_inicial.value()
            anios = list(range(anio0, anio0 + len(datos)))
            tipo = self.combo_no_estacionario.currentData()
            comp = frequency_analysis.comparar_estacionario_vs_no_estacionario(
                datos, anios, tipo, periodos_retorno=self.periodos_retorno_actuales)
            modelo = comp["modelo"]
            self.no_estacionario_resultado = comp

            filas = [
                ("Modelo", modelo["nombre"], ""),
                ("Periodo analizado", f"{modelo['anio_inicial']}–{modelo['anio_final']}", "",
                 f"{modelo['n_datos']} años"),
                ("Tendencia estimada", modelo["tendencia_por_decada"], "mm/década"),
                ("p-valor de la tendencia", modelo["p_valor_tendencia"], "",
                 "significativa al 5%" if modelo["tendencia_significativa_5pct"]
                 else "NO significativa al 5%: no hay evidencia para abandonar el análisis estacionario"),
                ("R² de la tendencia", modelo["r2_tendencia"], "",
                 "fracción de la varianza de la serie explicada por la tendencia"),
                ("Conclusión", "—", "", modelo["conclusion"]),
            ]
            if modelo.get("advertencia_gl"):
                filas.append(("Advertencia", "—", "", modelo["advertencia_gl"]))
            poblar_tabla_parametros(self.tabla_no_estacionario, filas)

            self.tabla_sensibilidad_no_est.setRowCount(0)
            a_ini, a_fin, a_ext = comp["anios_evaluacion"]
            self.tabla_sensibilidad_no_est.setHorizontalHeaderLabels(
                ["Tr (años)", "Estacionario (mm)", f"{a_ini} (mm)", f"{a_fin} (mm)",
                 f"{a_ext} (mm) — EXTRAPOLACIÓN"])
            for tr in comp["periodos_retorno"]:
                f = comp["tabla"][tr]
                fila = self.tabla_sensibilidad_no_est.rowCount()
                self.tabla_sensibilidad_no_est.insertRow(fila)
                self.tabla_sensibilidad_no_est.setItem(fila, 0, QTableWidgetItem(str(tr)))
                self.tabla_sensibilidad_no_est.setItem(
                    fila, 1, QTableWidgetItem(f"{f['estacionario']:.2f}"))
                for col, anio in enumerate((a_ini, a_fin, a_ext), start=2):
                    d = f[anio]
                    item = QTableWidgetItem(
                        f"{d['valor']:.2f}  ({d['diferencia_vs_estacionario_pct']:+.1f}%)")
                    if d["es_extrapolacion"]:
                        item.setToolTip(
                            "Año posterior al último observado: la tendencia se está EXTRAPOLANDO. "
                            "Nada garantiza que siga siendo lineal ni que persista.")
                    self.tabla_sensibilidad_no_est.setItem(fila, col, item)
            ajustar_alto_tabla(self.tabla_sensibilidad_no_est, filas_visibles_max=self.tabla_sensibilidad_no_est.rowCount() + 2)

            # Cuadro de impacto: la conclusión es lo que debe verse primero,
            # y el color comunica si hay o no evidencia para abandonar el
            # análisis estacionario.
            significativa = modelo["tendencia_significativa_5pct"]
            tr_ref = 100 if 100 in comp["periodos_retorno"] else comp["periodos_retorno"][-1]
            fila_ref = comp["tabla"][tr_ref]
            dif_ultimo = fila_ref[a_fin]["diferencia_vs_estacionario_pct"]
            self.cuadro_no_estacionario.actualizar(
                titulo="ANÁLISIS DE FRECUENCIA NO ESTACIONARIO",
                valor_principal=(f"Tendencia = {modelo['tendencia_por_decada']:+.2f} mm/década"
                                  + ("  (SIGNIFICATIVA)" if significativa else "  (no significativa)")),
                subtitulo=(f"{modelo['nombre']} · periodo {modelo['anio_inicial']}–"
                            f"{modelo['anio_final']} ({modelo['n_datos']} años)"),
                metricas=[("p-valor", f"{modelo['p_valor_tendencia']:.4f}"),
                           ("R² de la tendencia", f"{modelo['r2_tendencia']:.4f}"),
                           (f"P24 estacionaria (Tr={tr_ref})", f"{fila_ref['estacionario']:.1f} mm"),
                           (f"Cambio en {a_fin}", f"{dif_ultimo:+.1f}%")],
                leyenda=("hay evidencia estadística de tendencia: verifique que tenga causa física "
                          "antes de usarla en diseño" if significativa else
                          "sin evidencia suficiente: use el valor ESTACIONARIO como valor de diseño"),
                tipo="atencion" if significativa else "exito",
            )
            self.canvas_no_estacionario.plot_no_estacionario(comp, datos, anios)
        except Exception as e:
            QMessageBox.critical(self, "Error en el análisis no estacionario", str(e))

    def _on_calcular_metodos_idf(self):
        if not self.p24_disenio:
            QMessageBox.warning(
                self, "Falta el análisis de frecuencia",
                "Calcule primero el análisis de frecuencia (sección 2) para obtener las P24h de diseño.")
            return
        try:
            p24_por_tr = dict(self.p24_disenio)
            periodos = sorted(p24_por_tr.keys())

            # Bell necesita P(60min,10años). Si el usuario no la aporta, se
            # estima desde la P24h de 10 años -- y se deja constancia de que
            # es una estimación, no un dato medido.
            p60 = self.spin_bell_p60.value()
            p60_estimada = False
            if p60 <= 0:
                tr_ref = 10 if 10 in p24_por_tr else min(periodos, key=lambda t: abs(t - 10))
                p60 = idf_curves.p60_10_desde_p24(p24_por_tr[tr_ref])
                p60_estimada = True

            parametros_iila = None
            if self.spin_iila_a.value() > 0:
                parametros_iila = {
                    "parametro_a": self.spin_iila_a.value(), "parametro_k": self.spin_iila_k.value(),
                    "parametro_b": self.spin_iila_b.value(), "parametro_n": self.spin_iila_n.value(),
                }

            resultados = idf_curves.comparar_metodos_idf(
                p24_por_tr, exponente_sherman=self.spin_exponente_idf.value(),
                p60_10_mm=p60, parametros_iila=parametros_iila,
            )
            self.metodos_idf_resultado = resultados

            # El desplegable de Tr se rellena con los periodos disponibles.
            tr_actual = self.combo_tr_comparacion_idf.currentData()
            self.combo_tr_comparacion_idf.blockSignals(True)
            self.combo_tr_comparacion_idf.clear()
            for tr in periodos:
                self.combo_tr_comparacion_idf.addItem(f"{tr} años", tr)
            if tr_actual in periodos:
                self.combo_tr_comparacion_idf.setCurrentIndex(periodos.index(tr_actual))
            elif 100 in periodos:
                self.combo_tr_comparacion_idf.setCurrentIndex(periodos.index(100))
            self.combo_tr_comparacion_idf.blockSignals(False)
            tr_comp = self.combo_tr_comparacion_idf.currentData() or periodos[-1]

            # Tabla e intensidades a 60 min, que es la duración de
            # referencia habitual para comparar métodos entre sí.
            filas, intensidades_60 = [], {}
            for clave, datos in resultados.items():
                curva = (datos.get("curvas") or {}).get(tr_comp) or []
                i60 = next((i for d, i in curva if abs(d - 60.0) < 1e-9), None)
                if i60 is not None:
                    intensidades_60[datos["nombre"]] = i60
                comentario = ""
                if clave == "bell":
                    comentario = ("P(60min,10años) = "
                                  f"{datos['P60_10_mm']} mm"
                                  + (" (ESTIMADA desde la P24h)" if p60_estimada else " (aportada)"))
                    if datos.get("advertencias"):
                        comentario += " — " + datos["advertencias"][0]
                elif clave == "iila":
                    pa = datos["parametros"]
                    comentario = (f"a={pa['a']}, K={pa['K']}, b={pa['b']}, n={pa['n']} — "
                                  "parámetros REGIONALES: verifique que sean los de su subzona")
                filas.append((f"Intensidad a 60 min — {datos['nombre']}",
                               round(i60, 3) if i60 is not None else "—", "mm/h", comentario))
            if len(intensidades_60) > 1:
                vmax, vmin = max(intensidades_60.values()), min(intensidades_60.values())
                filas.append(
                    ("Dispersión entre métodos", round(vmax - vmin, 3), "mm/h",
                     f"{(vmax - vmin) / vmax * 100:.1f}% — la intensidad se traslada de forma "
                     "prácticamente proporcional al caudal de diseño"))
            poblar_tabla_parametros(self.tabla_metodos_idf, filas)

            if intensidades_60:
                nombre_max = max(intensidades_60, key=intensidades_60.get)
                nombre_min = min(intensidades_60, key=intensidades_60.get)
                vmax, vmin = intensidades_60[nombre_max], intensidades_60[nombre_min]
                dispersion_pct = (vmax - vmin) / vmax * 100 if vmax else 0.0
                self.cuadro_metodos_idf.actualizar(
                    titulo=f"INTENSIDAD DE DISEÑO A 60 MIN — Tr = {tr_comp} AÑOS",
                    valor_principal=f"{vmin:.1f} – {vmax:.1f} mm/h  según el método",
                    subtitulo=f"{len(intensidades_60)} métodos comparados sobre la misma P24h",
                    metricas=[("Máxima", f"{vmax:.1f} mm/h"), ("Mínima", f"{vmin:.1f} mm/h"),
                               ("Dispersión", f"{dispersion_pct:.1f}%"),
                               ("Métodos", str(len(intensidades_60)))],
                    leyenda=f"máxima: {nombre_max}  ·  mínima: {nombre_min}",
                    tipo="alerta" if dispersion_pct > 40 else
                         ("atencion" if dispersion_pct > 20 else "exito"),
                )

            self.canvas_metodos_idf_log.plot_comparacion_metodos_idf(resultados, tr_comp, escala_log=True)
            self.canvas_metodos_idf_cart.plot_comparacion_metodos_idf(resultados, tr_comp, escala_log=False)

            avisos = (resultados.get("bell") or {}).get("advertencias") or []
            if avisos:
                QMessageBox.information(
                    self, "Avisos del método de Bell", "\n\n".join(avisos))
        except Exception as e:
            QMessageBox.critical(self, "Error generando las curvas IDF", str(e))

    def _on_generar_diagnostico_distribucion(self):
        if not self.resultados_frecuencia:
            QMessageBox.warning(
                self, "Falta el análisis de frecuencia",
                "Ajuste primero las distribuciones (sección 2 de esta pestaña).")
            return
        clave = self.combo_dist_diagnostico.currentData() or self.mejor_ajuste_clave
        if not clave or self.resultados_frecuencia.get(clave, {}).get("error"):
            QMessageBox.warning(self, "Sin distribución",
                                 "No hay una distribución válida seleccionada.")
            return
        try:
            resultado = self.resultados_frecuencia[clave]
            diagnostico = frequency_analysis.diagnostico_distribucion(
                self.serie_precip_anual.valores_mm, resultado["distribucion"], n_puntos=300)
            self.canvas_diagnostico_distribucion.plot_diagnosticos(diagnostico, resultado["nombre"])
        except ValueError as e:
            QMessageBox.warning(self, "No se pudo generar el diagnóstico", str(e))
        except Exception as e:
            QMessageBox.critical(self, "Error generando el diagnóstico gráfico", str(e))

    def _on_calcular_bandas_confianza(self):
        if not self.resultados_frecuencia:
            QMessageBox.warning(
                self, "Falta el análisis de frecuencia",
                "Ajuste primero las distribuciones (sección 2 de esta pestaña).")
            return
        clave = self.combo_dist_bandas.currentData() or self.mejor_ajuste_clave
        if not clave:
            QMessageBox.warning(self, "Sin distribución", "No hay una distribución válida seleccionada.")
            return
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                bandas = frequency_analysis.bandas_confianza_bootstrap(
                    self.serie_precip_anual.valores_mm, clave,
                    periodos_retorno=self.periodos_retorno_actuales,
                    n_remuestreos=self.spin_bootstrap_n.value(),
                    nivel_confianza=self.combo_nivel_confianza.currentData(),
                    metodo=self.metodo_ajuste_usado,
                )
            finally:
                QApplication.restoreOverrideCursor()

            self.bandas_confianza_resultado = bandas
            self.tabla_bandas_confianza.setRowCount(0)
            for tr in bandas["periodos_retorno"]:
                lim = bandas["limites"][tr]
                fila = self.tabla_bandas_confianza.rowCount()
                self.tabla_bandas_confianza.insertRow(fila)
                self.tabla_bandas_confianza.setItem(fila, 0, QTableWidgetItem(str(tr)))
                if lim["inferior"] is None:
                    for _c, _t in ((1, "—"), (2, f"{lim['central']:.2f}"), (3, "—"), (4, "—"), (5, "—")):
                        self.tabla_bandas_confianza.setItem(fila, _c, QTableWidgetItem(_t))
                    continue
                for _c, _t in ((1, f"{lim['inferior']:.2f}"), (2, f"{lim['central']:.2f}"),
                                (3, f"{lim['superior']:.2f}"), (4, f"{lim['amplitud']:.2f}"),
                                (5, f"{lim['amplitud_relativa_pct']:.1f}%")):
                    self.tabla_bandas_confianza.setItem(fila, _c, QTableWidgetItem(_t))
            ajustar_alto_tabla(self.tabla_bandas_confianza, filas_visibles_max=self.tabla_bandas_confianza.rowCount() + 2)

            self.canvas_bandas_confianza.plot_bandas_confianza(
                bandas, datos_observados=self.serie_precip_anual.valores_mm, escala_log=True)

            if bandas.get("advertencia_fallidos"):
                QMessageBox.warning(self, "Bootstrap poco fiable", bandas["advertencia_fallidos"])
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Error calculando las bandas de confianza", str(e))

    def _on_calcular_idf(self):
        if not self.p24_disenio:
            QMessageBox.warning(
                self, "Falta el análisis de frecuencia",
                "Calcule primero el análisis de frecuencia (sección 2, arriba en esta pestaña) para "
                "obtener las precipitaciones de diseño P24h(Tr) de los periodos de retorno establecidos."
            )
            return
        try:
            exponente_n = self.spin_exponente_idf.value()
            p24_por_tr = dict(self.p24_disenio)
            datos_por_tr = idf_curves.tabla_idf(p24_por_tr, exponente_n)

            ecuaciones_por_tr = {}
            self.tabla_ecuaciones_idf.setRowCount(0)
            for tr in sorted(p24_por_tr.keys()):
                eq = idf_curves.ajustar_ecuacion_potencial(
                    [d for d, i in datos_por_tr[tr]], [i for d, i in datos_por_tr[tr]]
                )
                ecuaciones_por_tr[tr] = eq
                row = self.tabla_ecuaciones_idf.rowCount()
                self.tabla_ecuaciones_idf.insertRow(row)
                self.tabla_ecuaciones_idf.setItem(row, 0, QTableWidgetItem(f"{tr}"))
                self.tabla_ecuaciones_idf.setItem(
                    row, 1, QTableWidgetItem(f"i = {eq['a']:.3f} · t^{eq['b']:.4f}"))
                self.tabla_ecuaciones_idf.setItem(row, 2, QTableWidgetItem(f"{eq['a']:.4f}"))
                self.tabla_ecuaciones_idf.setItem(row, 3, QTableWidgetItem(f"{eq['b']:.4f}"))
                self.tabla_ecuaciones_idf.setItem(row, 4, QTableWidgetItem(f"{eq['r2']:.5f}"))
            ajustar_alto_tabla(self.tabla_ecuaciones_idf, filas_visibles_max=12)

            combinada = idf_curves.ajustar_idf_combinada(p24_por_tr, exponente_n)
            self.lbl_ecuacion_idf_combinada.setText(
                f"i = {combinada['K']:.3f} · Tr^{combinada['m']:.4f} / t^{combinada['n_exp']:.4f}"
            )
            self.lbl_idf_param_k.setText(f"{combinada['K']:.3f}")
            self.lbl_idf_param_m.setText(f"{combinada['m']:.4f}")
            self.lbl_idf_param_n.setText(f"{combinada['n_exp']:.4f}")
            self.lbl_idf_param_r2.setText(f"{combinada['r2']:.5f}")

            self.canvas_idf_log.plot_curvas_idf(datos_por_tr, ecuaciones_por_tr, escala_log=True)
            self.canvas_idf_cartesiano.plot_curvas_idf(datos_por_tr, ecuaciones_por_tr, escala_log=False)

            self.idf_resultados = {
                "exponente_n": exponente_n, "p24_por_tr": p24_por_tr,
                "ecuaciones_por_tr": ecuaciones_por_tr, "combinada": combinada,
            }
        except Exception as e:
            QMessageBox.critical(self, "Error calculando las curvas IDF", str(e))

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

    def _on_qc_mann_kendall_estacional(self):
        datos = self._obtener_serie_activa()
        if datos is None:
            return
        periodo = self.spin_qc_periodo_estacional.value()
        try:
            r = quality_control.test_mann_kendall_estacional(datos, periodo)
            filas = [
                ("S total (suma de las S de cada estación)", r["S_total"], ""),
                ("Varianza de S total", r["var_S_total"], ""),
                ("Estadístico Z", r["Z"], ""),
                ("p-valor", r["p_valor"], "",
                 "significativa (α=0.05)" if r["es_significativa_alpha_0_05"]
                 else "no significativa (α=0.05)"),
                ("Tendencia", r["tendencia"], "", f"periodo estacional = {periodo}"),
            ]
            # detalle_por_estacion viene como estructura anidada: se
            # aplana a una fila por sub-estación en vez de volcar el
            # diccionario crudo en una celda, que sería ilegible.
            detalle = r.get("detalle_por_estacion")
            if isinstance(detalle, dict):
                elementos = detalle.items()
            else:
                elementos = enumerate(detalle or [], start=1)
            for clave, valor in elementos:
                if isinstance(valor, dict):
                    resumen = ", ".join(f"{k}={v}" for k, v in valor.items())
                else:
                    resumen = str(valor)
                filas.append((f"Sub-serie {clave}", resumen, ""))
            poblar_tabla_parametros(self.tabla_resultado_qc, filas, filas_visibles_max=24)

            self.canvas_qc.plot_serie_con_marca(
                datos, f"Mann-Kendall estacional (periodo {periodo}) — Z = {r['Z']}, "
                       f"p = {r['p_valor']}")
        except quality_control.QualityControlError as e:
            QMessageBox.warning(self, "Mann-Kendall estacional", str(e))

    def _on_qc_pacf(self):
        datos = self._obtener_serie_activa()
        if datos is None:
            return
        max_lag = self.spin_qc_max_lag.value()
        try:
            r = quality_control.funcion_autocorrelacion_parcial(datos, max_lag)
            pacf = r["pacf_por_lag"]
            limite = r["limite_significancia_aprox_95"]
            significativos = r["lags_significativos"]
            filas = [("Límite de significancia 95%", limite, "",
                      "aproximación ±1.96/√n; fuera de esta banda hay dependencia serial"),
                     ("Lags significativos", significativos or "ninguno", "",
                      r["interpretacion"])]
            for lag in sorted(int(k) for k in pacf):
                valor = pacf[lag] if lag in pacf else pacf[str(lag)]
                if lag == 0:
                    continue
                filas.append((f"PACF lag {lag}", valor, "",
                              "SIGNIFICATIVO" if abs(valor) > limite else ""))
            poblar_tabla_parametros(self.tabla_resultado_qc, filas, filas_visibles_max=24)
            self.canvas_qc.plot_pacf(pacf, limite, significativos)
        except quality_control.QualityControlError as e:
            QMessageBox.warning(self, "Autocorrelación parcial", str(e))

    def _on_qc_corregir_quiebre(self):
        datos = self._obtener_serie_activa()
        if datos is None:
            return
        # El usuario indica la posición en base 1 (como la reportan
        # Pettitt/CUSUM en la tabla); el módulo trabaja con índice base 0.
        indice = self.spin_qc_indice_quiebre.value() - 1
        if not 0 < indice < len(datos):
            QMessageBox.warning(
                self, "Posición de quiebre no válida",
                f"La posición debe estar entre 2 y {len(datos)} para dejar datos a ambos lados "
                f"del quiebre (la serie activa tiene {len(datos)} valores).")
            return
        metodo = self.combo_qc_metodo_correccion.currentData()
        try:
            r = quality_control.corregir_por_quiebre(datos, indice, metodo)
            serie_corregida = [v for v in r["serie_corregida"] if v is not None]
            poblar_tabla_parametros(self.tabla_resultado_qc, [
                ("Método de corrección", r["metodo"], ""),
                ("Media del segmento anterior al quiebre", r["media_antes"], ""),
                ("Media del segmento posterior (original)", r["media_despues_original"], ""),
                ("Media del segmento posterior (corregida)", r["media_despues_corregida"], "",
                 "debe coincidir con la media del segmento anterior"),
                ("Ajuste aplicado", r["ajuste_aplicado"], "",
                 "diferencia restada" if metodo == "aditivo" else "factor multiplicado"),
                ("Valores corregidos", len(serie_corregida), ""),
                ("Advertencia", r["advertencia"], ""),
            ], filas_visibles_max=10)

            # La serie corregida pasa a ser la activa: encadenar el resto
            # de pruebas sobre ella es justo el flujo de trabajo (corregir
            # el quiebre y volver a comprobar homogeneidad).
            self.serie_qc_activa = serie_corregida
            self.canvas_qc.plot_serie_con_marca(
                serie_corregida,
                f"Serie corregida por quiebre ({r['metodo']}) en la posición {indice + 1}",
                indice_marca=indice,
                etiqueta_marca=f"Quiebre corregido (pos. {indice + 1})")
            QMessageBox.information(
                self, "Serie corregida",
                "La serie corregida quedó como serie activa de esta pestaña: puede volver a "
                "aplicar las pruebas de homogeneidad de ① para comprobar que el quiebre "
                "desapareció.\n\nDocumente en el informe que estos valores son CORREGIDOS, no "
                "observados directamente.")
        except (quality_control.QualityControlError, ValueError) as e:
            QMessageBox.warning(self, "Corrección por quiebre", str(e))

    def _on_qc_generico(self, funcion_test, nombre: str):
        datos = self._obtener_serie_activa()
        if datos is None:
            return
        try:
            r = funcion_test(datos)
            poblar_tabla_parametros(self.tabla_resultado_qc, [
                (k, v, "") for k, v in r.items() if k != "nota"
            ] + ([("Nota", r["nota"], "")] if "nota" in r else []))

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
            poblar_tabla_parametros(self.tabla_resultado_qc, [
                ("Periodo 1", f"primeros {len(periodo1)} datos", ""),
                ("Periodo 2", f"últimos {len(periodo2)} datos", ""),
            ] + [(k, v, "") for k, v in r.items()])

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
        limitar_ancho_boton(btn_usar_tabla_mensual)
        h_datos_btn.addWidget(btn_usar_tabla_mensual)
        btn_usar_serie_anual = QPushButton("(alternativa) Usar la serie anual ya cargada en la pestaña 5")
        btn_usar_serie_anual.clicked.connect(self._on_usar_serie_anual_como_qc)
        limitar_ancho_boton(btn_usar_serie_anual)
        h_datos_btn.addWidget(btn_usar_serie_anual)
        h_datos_btn.addStretch()
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
        self.tabla_resultado_completacion_mensual = crear_tabla_parametros()
        v_comp.addWidget(self.tabla_resultado_completacion_mensual)
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

        v_cal.addWidget(QLabel("<b>⑤ Normalidad, estacionalidad, dependencia serial y corrección</b>"))
        _lbl_qc5 = QLabel(
            "Anderson-Darling comprueba si la serie es normal, requisito de varias pruebas "
            "paramétricas. Mann-Kendall estacional detecta tendencia SIN que la estacionalidad la "
            "enmascare (compara cada mes contra el mismo mes de otros años). La PACF revela "
            "dependencia serial: si existe, Mann-Kendall y Pettitt pierden confiabilidad porque "
            "asumen independencia. La corrección por quiebre homogeneiza la media de los dos "
            "segmentos separados por un salto detectado en ①."
        )
        _lbl_qc5.setWordWrap(True)
        v_cal.addWidget(_lbl_qc5)

        h5 = QHBoxLayout()
        btn_ad = QPushButton("Anderson-Darling (normalidad)")
        btn_ad.clicked.connect(lambda: self._on_qc_generico(
            quality_control.test_anderson_darling, "Anderson-Darling (normalidad)"))
        h5.addWidget(btn_ad)
        h5.addWidget(QLabel("Periodo estacional:"))
        self.spin_qc_periodo_estacional = QSpinBox()
        self.spin_qc_periodo_estacional.setRange(2, 24)
        self.spin_qc_periodo_estacional.setValue(12)
        self.spin_qc_periodo_estacional.setToolTip(
            "12 para series mensuales, 4 para trimestrales.")
        h5.addWidget(self.spin_qc_periodo_estacional)
        btn_mk_est = QPushButton("Mann-Kendall estacional")
        btn_mk_est.clicked.connect(self._on_qc_mann_kendall_estacional)
        h5.addWidget(btn_mk_est)
        h5.addStretch()
        v_cal.addLayout(h5)

        h6 = QHBoxLayout()
        h6.addWidget(QLabel("Lag máximo PACF:"))
        self.spin_qc_max_lag = QSpinBox()
        self.spin_qc_max_lag.setRange(1, 60)
        self.spin_qc_max_lag.setValue(12)
        h6.addWidget(self.spin_qc_max_lag)
        btn_pacf = QPushButton("Autocorrelación parcial (PACF)")
        btn_pacf.clicked.connect(self._on_qc_pacf)
        h6.addWidget(btn_pacf)
        h6.addWidget(QLabel("Posición del quiebre:"))
        self.spin_qc_indice_quiebre = QSpinBox()
        self.spin_qc_indice_quiebre.setRange(1, 100000)
        self.spin_qc_indice_quiebre.setValue(1)
        self.spin_qc_indice_quiebre.setToolTip(
            "Posición (1 = primer dato) desde la que empieza el segundo segmento. Use la que "
            "reporta Pettitt/CUSUM/Buishand en ①.")
        h6.addWidget(self.spin_qc_indice_quiebre)
        self.combo_qc_metodo_correccion = QComboBox()
        self.combo_qc_metodo_correccion.addItem("Aditivo (resta la diferencia de medias)", "aditivo")
        self.combo_qc_metodo_correccion.addItem("Multiplicativo (escala por la razón de medias)",
                                                 "multiplicativo")
        h6.addWidget(self.combo_qc_metodo_correccion)
        btn_corregir = QPushButton("Corregir por quiebre")
        btn_corregir.clicked.connect(self._on_qc_corregir_quiebre)
        h6.addWidget(btn_corregir)
        h6.addStretch()
        v_cal.addLayout(h6)

        self.tabla_resultado_qc = crear_tabla_parametros()
        v_cal.addWidget(self.tabla_resultado_qc)

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
        self.tabla_resultado_pmp = crear_tabla_parametros()
        v_pmp.addWidget(self.tabla_resultado_pmp)
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

        # =============================================================
        # REGIONALIZACIÓN vs. COVARIABLE (altitud / latitud / longitud)
        # =============================================================
        gb_reg = QGroupBox("Regionalización de la precipitación frente a una covariable")
        v_reg = QVBoxLayout(gb_reg)
        lbl_reg = QLabel(
            "Ajusta la relación entre la precipitación de varias estaciones y una <b>covariable</b> "
            "física — típicamente la <b>altitud</b>, que en los Andes explica buena parte de la "
            "variación espacial — para poder estimarla en puntos SIN estación. Devuelve la correlación "
            "con su significancia, la regresión con intervalo de confianza al 95%, y la predicción en "
            "los puntos que indique.<br><br>"
            "Incluye además una <b>corrección local de residuos por IDW</b>: tras aplicar la regresión, "
            "reparte el error que queda en cada estación hacia los puntos vecinos. Es una aproximación "
            "práctica al co-kriging sin tener que ajustar un variograma, y suele mejorar bastante la "
            "estimación cuando hay estaciones cerca del punto buscado."
        )
        lbl_reg.setWordWrap(True)
        v_reg.addWidget(lbl_reg)

        v_reg.addWidget(QLabel(
            "<b>Estaciones</b> — pegue desde Excel: nombre, valor de la variable (p.ej. precipitación "
            "media anual en mm), covariable (p.ej. altitud en m), X e Y en el CRS del proyecto:"))
        self.tabla_regionalizacion = TablaPegable(8, 5)
        self.tabla_regionalizacion.setHorizontalHeaderLabels(
            ["Estación", "Variable (mm)", "Covariable (m)", "X", "Y"])
        aplicar_columna_elastica(self.tabla_regionalizacion, indice_columna_larga=0)
        ajustar_alto_tabla(self.tabla_regionalizacion, filas_visibles_max=10)
        v_reg.addWidget(self.tabla_regionalizacion)

        v_reg.addWidget(QLabel(
            "<b>Puntos a estimar</b> (opcional) — nombre, covariable, X, Y:"))
        self.tabla_puntos_regionalizacion = TablaPegable(4, 4)
        self.tabla_puntos_regionalizacion.setHorizontalHeaderLabels(
            ["Punto", "Covariable (m)", "X", "Y"])
        aplicar_columna_elastica(self.tabla_puntos_regionalizacion, indice_columna_larga=0)
        ajustar_alto_tabla(self.tabla_puntos_regionalizacion, filas_visibles_max=8)
        v_reg.addWidget(self.tabla_puntos_regionalizacion)

        h_reg_btn = QHBoxLayout()
        self.check_correccion_residual = QCheckBox(
            "Aplicar corrección local de residuos por IDW (recomendado si hay estaciones cercanas)")
        self.check_correccion_residual.setChecked(True)
        v_reg.addWidget(self.check_correccion_residual)
        btn_reg = QPushButton("Regionalizar")
        btn_reg.clicked.connect(self._on_regionalizar)
        limitar_ancho_boton(btn_reg)
        h_reg_btn.addWidget(btn_reg)
        h_reg_btn.addStretch()
        v_reg.addLayout(h_reg_btn)

        self.cuadro_regionalizacion = CuadroResumenImpacto(ancho_maximo=720)
        self.cuadro_regionalizacion.actualizar(
            titulo="SIN REGIONALIZAR", valor_principal="—",
            subtitulo="Ingrese las estaciones y pulse «Regionalizar»")
        centrar_en_layout(self.cuadro_regionalizacion, v_reg)
        self.tabla_resultado_regionalizacion = crear_tabla_parametros()
        v_reg.addWidget(self.tabla_resultado_regionalizacion)
        self.canvas_regionalizacion = RegionalizacionCanvas()
        v_reg.addWidget(self.canvas_regionalizacion)
        v.addWidget(gb_reg)

        # =============================================================
        # VALIDACIÓN DE PRODUCTO GRILLADO CONTRA ESTACIÓN
        # =============================================================
        gb_val = QGroupBox("Validación de un producto grillado (CHIRPS / IMERG / ERA5-Land / PISCOp)")
        v_val = QVBoxLayout(gb_val)
        lbl_val = QLabel(
            "Compara la serie de un producto grillado con la de una estación real para decidir si "
            "puede usarse donde no hay medición. Calcula <b>métricas continuas</b> (NSE, KGE, PBIAS, "
            "RMSE, R) con la clasificación de Moriasi et al. (2007), y <b>métricas categóricas de "
            "detección de lluvia</b> (POD, FAR, FBI, HSS).<br><br>"
            "La distinción importa: un producto puede acertar el <i>volumen</i> mensual y aun así "
            "fallar en <i>qué días</i> llovió — o al revés. Las continuas miden lo primero y las "
            "categóricas lo segundo, y para diseño hidrológico ambas cosas cuentan."
        )
        lbl_val.setWordWrap(True)
        v_val.addWidget(lbl_val)

        v_val.addWidget(QLabel(
            "Series emparejadas — una fila por paso de tiempo: valor del producto grillado y valor "
            "observado en la estación (mm):"))
        self.tabla_validacion_grillada = TablaPegable(12, 2)
        self.tabla_validacion_grillada.setHorizontalHeaderLabels(
            ["Producto grillado (mm)", "Estación observada (mm)"])
        limitar_ancho_tabla(self.tabla_validacion_grillada, ancho_maximo=460)
        ajustar_alto_tabla(self.tabla_validacion_grillada, filas_visibles_max=10)
        h_val_tabla = QHBoxLayout()
        h_val_tabla.addWidget(self.tabla_validacion_grillada)
        h_val_tabla.addStretch()
        v_val.addLayout(h_val_tabla)

        f_val = QFormLayout()
        f_val.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.spin_umbral_deteccion = QDoubleSpinBox()
        self.spin_umbral_deteccion.setRange(0.0, 50.0)
        self.spin_umbral_deteccion.setDecimals(2)
        self.spin_umbral_deteccion.setValue(1.0)
        f_val.addRow("Umbral para considerar «día con lluvia» (mm):", self.spin_umbral_deteccion)
        v_val.addLayout(f_val)

        btn_val = QPushButton("Validar el producto grillado")
        btn_val.clicked.connect(self._on_validar_grillada)
        limitar_ancho_boton(btn_val)
        v_val.addWidget(btn_val)

        self.cuadro_validacion_grillada = CuadroResumenImpacto(ancho_maximo=720)
        self.cuadro_validacion_grillada.actualizar(
            titulo="SIN VALIDAR", valor_principal="—",
            subtitulo="Pegue las series emparejadas y pulse «Validar»")
        centrar_en_layout(self.cuadro_validacion_grillada, v_val)
        self.tabla_resultado_validacion = crear_tabla_parametros()
        v_val.addWidget(self.tabla_resultado_validacion)
        self.canvas_validacion_grillada = ValidacionGrilladaCanvas()
        v_val.addWidget(self.canvas_validacion_grillada)
        v.addWidget(gb_val)

        self._agregar_pestaña_con_scroll(tab, "15. Precipitación Media Mensual")

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
            poblar_tabla_parametros(self.tabla_resultado_completacion_mensual, [
                ("R² estacional (Fourier)", r["r2_ajuste_estacional"], "adim."),
                ("N° de armónicos", r["n_armonicos"], ""),
                (f"Extensión ({self.spin_fourier_extension.value()} meses)",
                 ", ".join(str(v) for v in r["extension"]), "mm", r["nota"]),
            ])
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
            poblar_tabla_parametros(self.tabla_resultado_completacion_mensual, [
                ("Método", "Wavelet", "", r.get("nota", "")),
            ])
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
            poblar_tabla_parametros(self.tabla_resultado_qc, [
                ("Punto de cambio (posición)", r["indice_cambio"], ""),
                ("Estadístico U máx.", r["U_max"], ""),
                ("p (aproximado)", r["p_valor_aprox"], ""),
                ("Media antes", r["media_antes"], ""),
                ("Media después", r["media_despues"], "", r["interpretacion"]),
            ])
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
            poblar_tabla_parametros(self.tabla_resultado_qc, [
                ("Mann-Kendall S", mk["S"], ""),
                ("Mann-Kendall Z", mk["Z"], ""),
                ("Mann-Kendall p", mk["p_valor"], "", f"Tendencia: {mk['tendencia']}"),
                ("Pendiente de Sen", sen["pendiente_por_periodo"], "por periodo", sen["interpretacion"]),
            ])
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
            poblar_tabla_parametros(self.tabla_resultado_qc, [
                ("Método", r["metodo"], "", r.get("advertencia", "")),
                ("Pendientes de segmento (primeras 10)",
                 ", ".join(str(v) for v in r["pendientes_segmento"][:10]), ""),
            ])

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
            poblar_tabla_parametros(self.tabla_resultado_pmp, [
                ("PMP 24h", r["PMP_24h_mm"], "mm"),
                ("Razón PMP / máximo observado", r["razon_pmp_sobre_max_observado"], "adim."),
                ("Máximo observado", r["valor_maximo_observado_mm"], "mm", f"en {r['n_anios']} años"),
                ("Media (sin el máximo)", r["media_sin_maximo_mm"], "mm"),
                ("Desv. estándar (sin el máximo)", r["desv_std_sin_maximo_mm"], "mm"),
                ("Km usado", r["km_usado"], "adim."),
                ("Factor hora fija aplicado", r["factor_hora_fija_aplicado"], "adim.", r["nota"]),
            ])
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
            metodo_ajuste = self.combo_metodo_ajuste.currentData() or "momentos_l"
            resultados = frequency_analysis.analizar_todas(datos, alpha_ks=alpha, metodo=metodo_ajuste)
            self.metodo_ajuste_usado = metodo_ajuste
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
                nombre = r["nombre"] + (
                    f"  ★ mejor ajuste ({frequency_analysis._cuenta_pruebas_pasadas(r)}/3 pruebas)"
                    if clave == mejor else "")
                self.tabla_distribuciones.setItem(row, 0, QTableWidgetItem(nombre))
                if r["error"]:
                    self.tabla_distribuciones.setItem(row, 1, QTableWidgetItem(f"ERROR: {r['error']}"))
                    for _col_vacia in range(2, 8):
                        self.tabla_distribuciones.setItem(row, _col_vacia, QTableWidgetItem(""))
                else:
                    simbolos = SIMBOLOS_PARAMETROS_DISTRIBUCION.get(clave, {})
                    params_str = ", ".join(
                        f"{simbolos.get(k, k)} = {v:.4f}" for k, v in r["parametros"].items()
                    )
                    self.tabla_distribuciones.setItem(row, 1, QTableWidgetItem(params_str))
                    self.tabla_distribuciones.setItem(row, 2, QTableWidgetItem(str(r["D_ks"])))
                    self.tabla_distribuciones.setItem(row, 3, QTableWidgetItem(str(r["D_critico"])))

                    ad = r.get("ad") or {}
                    if "pasa" in ad:
                        # El asterisco marca que el valor crítico es el del
                        # caso general (permisivo): ver la nota sobre AD
                        # arriba de la tabla y en core/frequency_analysis.py.
                        marca = "*" if ad.get("critico_aproximado") else ""
                        self.tabla_distribuciones.setItem(
                            row, 4, QTableWidgetItem(f"{ad['A2_modificado']}"))
                        item_ad_crit = QTableWidgetItem(f"{ad['A2_critico']}{marca}")
                        item_ad_crit.setToolTip(ad.get("tipo_critico", ""))
                        self.tabla_distribuciones.setItem(row, 5, item_ad_crit)
                    else:
                        self.tabla_distribuciones.setItem(row, 4, QTableWidgetItem("—"))
                        item_ad_err = QTableWidgetItem("—")
                        item_ad_err.setToolTip(str(ad.get("error", "")))
                        self.tabla_distribuciones.setItem(row, 5, item_ad_err)

                    chi = r.get("chi2") or {}
                    if "pasa" in chi:
                        item_chi = QTableWidgetItem(f"{chi['chi2']} (p={chi['p_valor']})")
                        item_chi.setToolTip(
                            f"χ² crítico = {chi['chi2_critico']}, {chi['grados_libertad']} grados de "
                            f"libertad, {chi['n_clases']} clases equiprobables con frecuencia esperada "
                            f"{chi['frecuencia_esperada_por_clase']} cada una"
                            + ("" if chi.get("frecuencia_esperada_suficiente")
                               else " — ATENCIÓN: por debajo del mínimo recomendado de 5, la prueba "
                                    "pierde validez con esta muestra tan corta")
                        )
                        self.tabla_distribuciones.setItem(row, 6, item_chi)
                    else:
                        item_chi_err = QTableWidgetItem("no aplicable")
                        item_chi_err.setToolTip(str(chi.get("error", "")))
                        self.tabla_distribuciones.setItem(row, 6, item_chi_err)

                    self.tabla_distribuciones.setItem(
                        row, 7, QTableWidgetItem(frequency_analysis.resumen_pruebas_bondad(r)))

            # Recalcula el alto de la tabla ahora que tiene filas (una por
            # distribución, hasta 9): se construyó con 0 filas y nunca
            # recalculaba su alto, quedando con el alto por defecto de Qt
            # para 0 filas -- solo se veían 2-3 distribuciones a la vez.
            ajustar_alto_tabla(self.tabla_distribuciones, filas_visibles_max=10)

            # Rellena el selector de distribución de las bandas de confianza
            # con las que sí se pudieron ajustar en esta corrida.
            self.combo_dist_bandas.blockSignals(True)
            self.combo_dist_bandas.clear()
            self.combo_dist_bandas.addItem("(la de mejor ajuste)", None)
            for clave_ok, datos_ok in resultados.items():
                if not datos_ok.get("error"):
                    self.combo_dist_bandas.addItem(datos_ok["nombre"], clave_ok)
            self.combo_dist_bandas.blockSignals(False)

            # Mismo repoblado para el selector del diagnóstico gráfico.
            self.combo_dist_diagnostico.blockSignals(True)
            self.combo_dist_diagnostico.clear()
            self.combo_dist_diagnostico.addItem("(la de mejor ajuste)", None)
            for clave_ok, datos_ok in resultados.items():
                if not datos_ok.get("error"):
                    self.combo_dist_diagnostico.addItem(datos_ok["nombre"], clave_ok)
            self.combo_dist_diagnostico.blockSignals(False)

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
        for _txt, _clave in (
                ("Curva IDF genérica (bloques alternos)", "idf_generica"),
                ("Dyck y Peschke / Grobe (n=0.25) — bloques alternos", "dyck_peschke"),
                ("Frederich Bell (1969) — bloques alternos", "bell"),
                ("IILA-SENAMHI-UNI (1983) — bloques alternos", "iila"),
                ("Patrón SCS Tipo I (aproximado)", "scs_I"),
                ("Patrón SCS Tipo IA (aproximado)", "scs_IA"),
                ("Patrón SCS Tipo II (aproximado)", "scs_II"),
                ("Patrón SCS Tipo III (aproximado)", "scs_III")):
            self.combo_metodo_desagregacion.addItem(_txt, _clave)
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

        self.cuadro_hietograma = CuadroResumenImpacto(ancho_maximo=700)
        self.cuadro_hietograma.actualizar(
            titulo="SIN HIETOGRAMA", valor_principal="—",
            subtitulo="Genérelo arriba o ingréselo a mano para ver su forma y su lámina")
        centrar_en_layout(self.cuadro_hietograma, v_h)
        self.canvas_hietograma = HydrographCanvas(self, width=6.5, height=3.8)
        v_h.addWidget(self.canvas_hietograma)
        # Al editar el hietograma a mano tambien se refresca el grafico, no
        # solo al generarlo con el boton.
        self.edit_hietograma.textChanged.connect(self._actualizar_grafico_hietograma)
        v.addWidget(gb_hieto)

        # ---------- Modelo de pérdidas por infiltración ----------
        gb_perdidas = QGroupBox("Modelo de pérdidas por infiltración (lluvia total → lluvia efectiva)")
        v_pe = QVBoxLayout(gb_perdidas)
        lbl_pe = QLabel(
            "Este es el eslabón que convierte el hietograma de arriba en la <b>lluvia efectiva</b> que "
            "alimenta el hidrograma unitario, y por tanto determina el caudal pico:<br>"
            "<code>hietograma → [PÉRDIDAS] → lluvia efectiva → hidrograma unitario → Qp</code><br><br>"
            "<b>SCS — Número de Curva</b> (el que usó siempre el plugin) es un método agregado de "
            "evento: la abstracción depende solo de la lámina acumulada, así que <b>dos tormentas con "
            "la misma lámina total dan la misma lluvia efectiva</b> aunque una sea corta e intensa y la "
            "otra larga y suave. <b>Green-Ampt</b> (físicamente basado: conductividad, succión del "
            "frente húmedo y déficit de humedad) y <b>Horton</b> (empírico, capacidad que decae "
            "exponencialmente) comparan la <b>intensidad</b> de cada intervalo contra la capacidad de "
            "infiltración del momento, así que sí distinguen ambos casos. En una prueba con dos "
            "tormentas de 115 mm, SCS-CN dio 71.1 mm de lluvia efectiva para las dos, mientras "
            "Green-Ampt dio 57.3 mm para la intensa y 8.7 mm para la suave. En cuencas altoandinas, "
            "donde las tormentas convectivas son cortas e intensas, esa diferencia va directa al "
            "caudal de diseño."
        )
        lbl_pe.setWordWrap(True)
        v_pe.addWidget(lbl_pe)

        h_pe = QHBoxLayout()
        h_pe.addWidget(QLabel("Modelo:"))
        self.combo_modelo_perdidas = QComboBox()
        self.combo_modelo_perdidas.addItem("SCS — Número de Curva (usa el S de la pestaña 3)", "scs")
        self.combo_modelo_perdidas.addItem("Green-Ampt (parámetros de la pestaña 3)", "green_ampt")
        self.combo_modelo_perdidas.addItem("Horton (parámetros de la pestaña 3)", "horton")
        self.combo_modelo_perdidas.addItem("Philip (parámetros de la pestaña 3)", "philip")
        self.combo_modelo_perdidas.addItem("Kostiakov / Kostiakov-Lewis (pestaña 3)", "kostiakov")
        self.combo_modelo_perdidas.addItem("Holtan (parámetros de la pestaña 3)", "holtan")
        h_pe.addWidget(self.combo_modelo_perdidas)
        h_pe.addStretch()
        v_pe.addLayout(h_pe)

        lbl_pe_ptr = QLabel(
            "<b>Los parámetros de cada modelo se configuran en la Pestaña 3</b> («Métodos de pérdida»), "
            "donde además puede graficarlos y compararlos sobre un hietograma de prueba. Aquí solo se "
            "elige cuál aplicar: el cálculo toma automáticamente los valores que tenga configurados "
            "allí, de modo que no haya dos juegos de campos que puedan divergir.")
        lbl_pe_ptr.setWordWrap(True)
        lbl_pe_ptr.setStyleSheet("color: #1a4a70;")
        v_pe.addWidget(lbl_pe_ptr)


        btn_comparar_perdidas = QPushButton("Comparar los 3 modelos de pérdidas con este hietograma")
        btn_comparar_perdidas.clicked.connect(self._on_comparar_modelos_perdidas)
        limitar_ancho_boton(btn_comparar_perdidas)
        v_pe.addWidget(btn_comparar_perdidas)
        self.tabla_comparacion_perdidas = crear_tabla_parametros()
        v_pe.addWidget(self.tabla_comparacion_perdidas)
        v.addWidget(gb_perdidas)

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

        self.tabla_resultado_qp = crear_tabla_parametros()
        v.addWidget(self.tabla_resultado_qp)

        self.canvas_hidrograma = HydrographCanvas(self, width=6.5, height=4.8)
        v.addWidget(self.canvas_hidrograma)

        # ---------------- Separación de flujo base ----------------
        gb_flujo_base = QGroupBox("Separación de flujo base de un hidrograma OBSERVADO")
        v_fb = QVBoxLayout(gb_flujo_base)
        lbl_fb = QLabel(
            "Descompone un hidrograma <b>aforado</b> en escorrentía directa (la respuesta rápida a la "
            "lluvia) y flujo base (el aporte sostenido del agua subterránea). Sirve para dos cosas "
            "concretas aquí: <b>(a) calibrar</b> el número de curva (pestaña 3) y los hidrogramas "
            "unitarios de arriba contra crecidas reales — esos métodos producen escorrentía DIRECTA, no "
            "caudal total, así que compararlos con un caudal aforado sin separar el flujo base "
            "sobreestima sistemáticamente el ajuste; y <b>(b)</b> obtener el <b>Índice de Flujo Base "
            "(BFI)</b>, descriptor de la capacidad de regulación natural de la cuenca.<br><br>"
            "<b>Advertencia metodológica:</b> la separación del flujo base <b>no tiene solución única</b> "
            "— no es una magnitud medible sino una construcción conceptual, y métodos (o parámetros) "
            "distintos dan resultados distintos, todos formalmente válidos. Por eso se calculan los "
            "tres a la vez: su coincidencia o divergencia es en sí misma información sobre cuán robusta "
            "es la separación en esa serie. Use un método y unos parámetros de forma consistente en "
            "todo un estudio, y repórtelos siempre."
        )
        lbl_fb.setWordWrap(True)
        v_fb.addWidget(lbl_fb)

        v_fb.addWidget(QLabel(
            "Serie de caudales observados (m³/s), un valor por paso de tiempo — pegue desde Excel:"))
        self.tabla_caudales_observados = TablaPegable(12, 1)
        self.tabla_caudales_observados.setHorizontalHeaderLabels(["Caudal observado (m³/s)"])
        # El ancho máximo se calcula a partir del ancho REAL que necesita el
        # texto del encabezado, no con un número fijo: con un tope fijo de
        # 260 px el título "Caudal observado (m³/s)" salía cortado con
        # puntos suspensivos (reportado por el usuario). Se mide el texto
        # con la métrica de la fuente de la cabecera y se le suma margen
        # para el indicador de orden y el borde.
        _cab_obs = self.tabla_caudales_observados.horizontalHeader()
        _cab_obs.setSectionResizeMode(0, QHeaderView.Stretch)
        _ancho_titulo = _cab_obs.fontMetrics().boundingRect("Caudal observado (m³/s)").width()
        _ancho_necesario = _ancho_titulo + 60 + self.tabla_caudales_observados.verticalHeader().width()
        self.tabla_caudales_observados.setMinimumWidth(_ancho_necesario)
        limitar_ancho_tabla(self.tabla_caudales_observados, ancho_maximo=max(300, _ancho_necesario))
        ajustar_alto_tabla(self.tabla_caudales_observados, filas_visibles_max=10)
        h_fb_tabla = QHBoxLayout()
        h_fb_tabla.addWidget(self.tabla_caudales_observados)
        h_fb_tabla.addStretch()
        v_fb.addLayout(h_fb_tabla)

        f_fb = QFormLayout()
        f_fb.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.spin_fb_filtro = QDoubleSpinBox()
        self.spin_fb_filtro.setRange(0.80, 0.999)
        self.spin_fb_filtro.setDecimals(3)
        self.spin_fb_filtro.setValue(0.925)
        f_fb.addRow("Parámetro de filtro a — Lyne-Hollick (típico 0.90-0.98):", self.spin_fb_filtro)
        self.spin_fb_pasadas = QSpinBox()
        self.spin_fb_pasadas.setRange(1, 9)
        self.spin_fb_pasadas.setValue(3)
        f_fb.addRow("Pasadas de filtrado — Lyne-Hollick (a más pasadas, menor flujo base):",
                     self.spin_fb_pasadas)
        self.spin_fb_recesion = QDoubleSpinBox()
        self.spin_fb_recesion.setRange(0.80, 0.999)
        self.spin_fb_recesion.setDecimals(3)
        self.spin_fb_recesion.setValue(0.980)
        f_fb.addRow("Constante de recesión a — Eckhardt (típico 0.95-0.99):", self.spin_fb_recesion)
        self.combo_fb_bfimax = QComboBox()
        for _clave, (_val, _desc) in baseflow.BFIMAX_RECOMENDADOS.items():
            self.combo_fb_bfimax.addItem(f"{_val:.2f} — {_desc}", _val)
        f_fb.addRow("BFImax — Eckhardt (gobierna el resultado: calíbrelo):", self.combo_fb_bfimax)
        self.spin_fb_intervalo = QSpinBox()
        self.spin_fb_intervalo.setRange(3, 99)
        self.spin_fb_intervalo.setValue(5)
        f_fb.addRow("Intervalo de mínimos locales (pasos; N=A^0.2 con A en mi²):", self.spin_fb_intervalo)
        v_fb.addLayout(f_fb)

        h_fb_btn = QHBoxLayout()
        btn_fb_intervalo = QPushButton("Estimar intervalo desde el área de la cuenca")
        btn_fb_intervalo.clicked.connect(self._on_estimar_intervalo_minimos)
        limitar_ancho_boton(btn_fb_intervalo)
        h_fb_btn.addWidget(btn_fb_intervalo)
        btn_fb_calc = QPushButton("Separar flujo base (los 3 métodos)")
        btn_fb_calc.clicked.connect(self._on_separar_flujo_base)
        limitar_ancho_boton(btn_fb_calc)
        h_fb_btn.addWidget(btn_fb_calc)
        h_fb_btn.addStretch()
        v_fb.addLayout(h_fb_btn)

        self.tabla_resultado_flujo_base = crear_tabla_parametros()
        v_fb.addWidget(self.tabla_resultado_flujo_base)
        self.canvas_flujo_base = HydrographCanvas(self, width=6.5, height=4.4)
        v_fb.addWidget(self.canvas_flujo_base)
        v.addWidget(gb_flujo_base)

        # ---------------- Tránsito de avenidas ----------------
        gb_transito = QGroupBox("Tránsito de avenidas (propagación del hidrograma aguas abajo)")
        v_tr = QVBoxLayout(gb_transito)
        lbl_tr_info = QLabel(
            "El hidrograma calculado arriba corresponde a la <b>salida de la cuenca</b>. Si la obra que "
            "está diseñando se ubica aguas abajo de ese punto — un puente varios kilómetros más abajo, "
            "una defensa ribereña en otro tramo, o aguas abajo de una laguna — usar ese caudal pico sin "
            "transitarlo <b>sobreestima el caudal de diseño</b>, porque ignora la atenuación que produce "
            "el almacenamiento del propio cauce o del vaso. <b>Muskingum-Cunge</b> es el método "
            "recomendado aquí porque deriva sus parámetros de la geometría e hidráulica del cauce, sin "
            "necesidad de calibrarlos con hidrogramas observados de entrada y salida (que rara vez "
            "existen en cuencas altoandinas). <b>Puls</b> es para tránsito en vaso/laguna. Son tránsitos "
            "hidrológicos: no resuelven Saint-Venant completo, así que no representan remanso ni flujo "
            "rápidamente variado — para eso hace falta un modelo hidrodinámico (HEC-RAS unsteady, Iber)."
        )
        lbl_tr_info.setWordWrap(True)
        v_tr.addWidget(lbl_tr_info)

        h_tr_metodo = QHBoxLayout()
        h_tr_metodo.addWidget(QLabel("Método:"))
        self.combo_metodo_transito = QComboBox()
        self.combo_metodo_transito.addItem("Muskingum-Cunge (recomendado)", "muskingum_cunge")
        self.combo_metodo_transito.addItem("Muskingum (K y X conocidos)", "muskingum")
        self.combo_metodo_transito.addItem("Puls modificado (tránsito en vaso)", "puls")
        self.combo_metodo_transito.currentIndexChanged.connect(self._on_cambiar_metodo_transito)
        h_tr_metodo.addWidget(self.combo_metodo_transito)
        h_tr_metodo.addStretch()
        v_tr.addLayout(h_tr_metodo)

        self.stack_transito = QStackedWidget()

        # --- Página Muskingum-Cunge ---
        pag_mc = QWidget()
        f_mc = QFormLayout(pag_mc)
        f_mc.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.spin_tr_longitud = QDoubleSpinBox()
        self.spin_tr_longitud.setRange(10.0, 500000.0)
        self.spin_tr_longitud.setDecimals(1)
        self.spin_tr_longitud.setValue(5000.0)
        f_mc.addRow("Longitud del tramo a transitar Δx (m):", self.spin_tr_longitud)
        self.spin_tr_ancho = QDoubleSpinBox()
        self.spin_tr_ancho.setRange(0.5, 5000.0)
        self.spin_tr_ancho.setValue(25.0)
        f_mc.addRow("Ancho superficial del cauce B (m):", self.spin_tr_ancho)
        self.spin_tr_pendiente = QDoubleSpinBox()
        self.spin_tr_pendiente.setRange(0.0001, 0.5)
        self.spin_tr_pendiente.setDecimals(4)
        self.spin_tr_pendiente.setValue(0.0200)
        f_mc.addRow("Pendiente del fondo S₀ (m/m):", self.spin_tr_pendiente)
        self.spin_tr_velocidad = QDoubleSpinBox()
        self.spin_tr_velocidad.setRange(0.1, 20.0)
        self.spin_tr_velocidad.setDecimals(3)
        self.spin_tr_velocidad.setValue(2.500)
        f_mc.addRow("Velocidad media del flujo V (m/s):", self.spin_tr_velocidad)
        self.stack_transito.addWidget(pag_mc)

        # --- Página Muskingum clásico ---
        pag_mk = QWidget()
        f_mk = QFormLayout(pag_mk)
        f_mk.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.spin_tr_k = QDoubleSpinBox()
        self.spin_tr_k.setRange(0.01, 500.0)
        self.spin_tr_k.setDecimals(3)
        self.spin_tr_k.setValue(2.000)
        f_mk.addRow("K — tiempo de viaje de la onda (h):", self.spin_tr_k)
        self.spin_tr_x = QDoubleSpinBox()
        self.spin_tr_x.setRange(0.0, 0.5)
        self.spin_tr_x.setDecimals(3)
        self.spin_tr_x.setSingleStep(0.05)
        self.spin_tr_x.setValue(0.200)
        f_mk.addRow("X — factor de ponderación (0 = máxima atenuación, 0.5 = traslación pura):",
                     self.spin_tr_x)
        lbl_mk_aviso = QLabel(
            "Requiere K y X calibrados con hidrogramas OBSERVADOS de entrada y salida del tramo. Si no "
            "los tiene, use Muskingum-Cunge, que los deriva de la geometría del cauce. El plugin avisa "
            "si la combinación de K, X y el Δt del hidrograma cae fuera del rango de estabilidad "
            "numérica (2·K·X ≤ Δt ≤ 2·K·(1−X)), donde el método puede dar oscilaciones sin sentido físico."
        )
        lbl_mk_aviso.setWordWrap(True)
        f_mk.addRow(lbl_mk_aviso)
        self.stack_transito.addWidget(pag_mk)

        # --- Página Puls ---
        pag_puls = QWidget()
        v_puls = QVBoxLayout(pag_puls)
        lbl_puls = QLabel(
            "Curva del embalse: una fila por punto, con el almacenamiento (m³) y la descarga (m³/s) "
            "que le corresponde. Debe cubrir hasta el nivel máximo esperado — si la crecida supera el "
            "último punto tabulado, el plugin lo advierte (normalmente significa que el vaso "
            "desbordaría por coronación)."
        )
        lbl_puls.setWordWrap(True)
        v_puls.addWidget(lbl_puls)
        self.tabla_curva_embalse = TablaPegable(6, 2)
        self.tabla_curva_embalse.setHorizontalHeaderLabels(["Almacenamiento (m³)", "Descarga (m³/s)"])
        for _fila, (_s, _o) in enumerate(
                [(0, 0), (200000, 5), (500000, 20), (900000, 45), (1400000, 80), (2000000, 125)]):
            self.tabla_curva_embalse.setItem(_fila, 0, QTableWidgetItem(str(_s)))
            self.tabla_curva_embalse.setItem(_fila, 1, QTableWidgetItem(str(_o)))
        limitar_ancho_tabla(self.tabla_curva_embalse, ancho_maximo=420)
        ajustar_alto_tabla(self.tabla_curva_embalse, filas_visibles_max=10)
        h_puls_tabla = QHBoxLayout()
        h_puls_tabla.addWidget(self.tabla_curva_embalse)
        h_puls_tabla.addStretch()
        v_puls.addLayout(h_puls_tabla)
        h_puls_btn = QHBoxLayout()
        btn_puls_fila = QPushButton("Agregar fila")
        btn_puls_fila.clicked.connect(
            lambda: self.tabla_curva_embalse.insertRow(self.tabla_curva_embalse.rowCount()))
        limitar_ancho_boton(btn_puls_fila)
        h_puls_btn.addWidget(btn_puls_fila)
        h_puls_btn.addStretch()
        v_puls.addLayout(h_puls_btn)
        f_puls = QFormLayout()
        f_puls.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.spin_tr_s_inicial = QDoubleSpinBox()
        self.spin_tr_s_inicial.setRange(0.0, 1e10)
        self.spin_tr_s_inicial.setDecimals(1)
        self.spin_tr_s_inicial.setValue(0.0)
        f_puls.addRow("Almacenamiento inicial del vaso (m³):", self.spin_tr_s_inicial)
        v_puls.addLayout(f_puls)
        self.stack_transito.addWidget(pag_puls)

        v_tr.addWidget(self.stack_transito)

        h_tr_btn = QHBoxLayout()
        btn_autocompletar_tr = QPushButton("Autocompletar con datos de la morfometría")
        btn_autocompletar_tr.clicked.connect(self._on_autocompletar_transito)
        limitar_ancho_boton(btn_autocompletar_tr)
        h_tr_btn.addWidget(btn_autocompletar_tr)
        btn_calc_tr = QPushButton("Transitar el hidrograma calculado arriba")
        btn_calc_tr.clicked.connect(self._on_calcular_transito)
        limitar_ancho_boton(btn_calc_tr)
        h_tr_btn.addWidget(btn_calc_tr)
        h_tr_btn.addStretch()
        v_tr.addLayout(h_tr_btn)

        self.tabla_resultado_transito = crear_tabla_parametros()
        v_tr.addWidget(self.tabla_resultado_transito)
        self.canvas_transito = HydrographCanvas(self, width=6.5, height=4.8)
        v_tr.addWidget(self.canvas_transito)
        v.addWidget(gb_transito)

        gb_directos = QGroupBox(
            "Verificación cruzada — fórmulas de caudal máximo DIRECTO (Racional, Témez, Mac Math, "
            "Creager), para comparar contra el caudal SCS/Snyder/Clark de arriba"
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

        self.tabla_resultado_caudales_directos = crear_tabla_parametros()
        v_dir.addWidget(self.tabla_resultado_caudales_directos)
        v.addWidget(gb_directos)

        gb_envolventes = QGroupBox(
            "Fórmulas envolventes / regionales adicionales (Dicken, Ryves, Inglis, Myer, Kresnik, "
            "Francou-Rodier, Ventura, Bürkli-Ziegler, Crippen & Bue, Iszkowski)"
        )
        v_env = QVBoxLayout(gb_envolventes)
        lbl_env_info = QLabel(
            "Catálogo de fórmulas ENVOLVENTES de distintas escuelas regionales: India/Commonwealth "
            "(Dicken, Ryves, Inglis), global/IAHS (Francou-Rodier), EE. UU. (Myer, Crippen & Bue/USGS), "
            "Europa central/alpina (Kresnik), Iberoamericana/Europa del Este (Ventura, Iszkowski) y "
            "drenaje urbano suizo (Bürkli-Ziegler). A diferencia de Témez/Mac Math/Creager de arriba, "
            "son en su mayoría curvas ajustadas contra crecidas MÁXIMAS OBSERVADAS de una región "
            "concreta: los coeficientes por defecto abajo son puntos de partida orientativos de la "
            "bibliografía general, NO valores calibrados para los Andes peruanos -- úselas como "
            "verificación de orden de magnitud / techo probable, no como caudal de diseño final sin "
            "calibración local. Reutilizan C, I, A y S ya ingresados arriba (S se toma como S%/100 en m/m)."
        )
        lbl_env_info.setWordWrap(True)
        v_env.addWidget(lbl_env_info)

        f_env = QFormLayout()
        f_env.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.spin_env_dicken = QDoubleSpinBox()
        self.spin_env_dicken.setRange(1.0, 30.0)
        self.spin_env_dicken.setValue(6.0)
        f_env.addRow("Coef. de Dicken C_D (6-9 interior, 14-28 costero/monzónico):", self.spin_env_dicken)
        self.spin_env_ryves = QDoubleSpinBox()
        self.spin_env_ryves.setRange(1.0, 15.0)
        self.spin_env_ryves.setValue(6.8)
        f_env.addRow("Coef. de Ryves C_R (6.8 interior, hasta 10.2 costero/montaña):", self.spin_env_ryves)
        self.spin_env_myer = QDoubleSpinBox()
        self.spin_env_myer.setRange(0.001, 1.0)
        self.spin_env_myer.setDecimals(3)
        self.spin_env_myer.setSingleStep(0.005)
        self.spin_env_myer.setValue(0.05)
        f_env.addRow("Coef. de Myer C_M (0.005-1.0; 1.0 = envolvente máxima histórica EE.UU.):", self.spin_env_myer)
        self.spin_env_kresnik = QDoubleSpinBox()
        self.spin_env_kresnik.setRange(0.1, 5.0)
        self.spin_env_kresnik.setValue(0.5)
        f_env.addRow("Coef. de Kresnik C_K (0.2 llana, 2.0-3.0 alpina):", self.spin_env_kresnik)
        self.spin_env_fr = QDoubleSpinBox()
        self.spin_env_fr.setRange(1.0, 7.0)
        self.spin_env_fr.setDecimals(2)
        self.spin_env_fr.setValue(5.1)
        f_env.addRow(
            "K de Francou-Rodier (2-3 árido, 4-5 templado/tropical, 5.5-6 extremo mundial):", self.spin_env_fr)
        self.spin_env_ventura = QDoubleSpinBox()
        self.spin_env_ventura.setRange(1.0, 60.0)
        self.spin_env_ventura.setValue(20.0)
        f_env.addRow("Coef. de Ventura C_v (10-40 según torrencialidad):", self.spin_env_ventura)
        self.spin_env_usgs_kr = QDoubleSpinBox()
        self.spin_env_usgs_kr.setRange(0.5, 200.0)
        self.spin_env_usgs_kr.setValue(7.0)
        f_env.addRow("kR de Crippen & Bue (USGS, multiplicador regional):", self.spin_env_usgs_kr)
        self.spin_env_usgs_b = QDoubleSpinBox()
        self.spin_env_usgs_b.setRange(0.10, 1.0)
        self.spin_env_usgs_b.setDecimals(3)
        self.spin_env_usgs_b.setValue(0.40)
        f_env.addRow("b de Crippen & Bue (exponente regional, típico 0.40-0.65):", self.spin_env_usgs_b)
        self.spin_env_iszkowski_ci = QDoubleSpinBox()
        self.spin_env_iszkowski_ci.setRange(0.01, 20.0)
        self.spin_env_iszkowski_ci.setDecimals(3)
        self.spin_env_iszkowski_ci.setValue(10.0)
        f_env.addRow("Ci de Iszkowski (coef. regional, sin rango bibliográfico acotado):", self.spin_env_iszkowski_ci)
        self.spin_env_iszkowski_m = QDoubleSpinBox()
        self.spin_env_iszkowski_m.setRange(0.001, 5.0)
        self.spin_env_iszkowski_m.setDecimals(3)
        self.spin_env_iszkowski_m.setValue(0.3)
        f_env.addRow("m de Iszkowski (factor de forma A/L² — «Autocompletar» lo trae de la Pestaña 2):",
                      self.spin_env_iszkowski_m)
        v_env.addLayout(f_env)

        h_env_btn = QHBoxLayout()
        btn_autocompletar_env = QPushButton("Autocompletar m de Iszkowski desde la morfometría")
        btn_autocompletar_env.clicked.connect(self._on_autocompletar_envolventes)
        limitar_ancho_boton(btn_autocompletar_env)
        h_env_btn.addWidget(btn_autocompletar_env)
        btn_calc_env = QPushButton("Calcular fórmulas envolventes")
        btn_calc_env.clicked.connect(self._on_calcular_caudales_envolventes)
        limitar_ancho_boton(btn_calc_env)
        h_env_btn.addWidget(btn_calc_env)
        h_env_btn.addStretch()
        v_env.addLayout(h_env_btn)

        self.tabla_resultado_envolventes = crear_tabla_parametros()
        v_env.addWidget(self.tabla_resultado_envolventes)
        v.addWidget(gb_envolventes)

        # ---------- Escuelas regionales adicionales ----------
        gb_escuelas = QGroupBox(
            "Escuelas regionales adicionales — Latinoamérica, Europa clásica y Norteamérica histórica "
            "(Santa María, Springall, Rocha, Lauterburg, Turazza, Murphy)"
        )
        v_esc = QVBoxLayout(gb_escuelas)
        lbl_esc_info = QLabel(
            "<b>Santa María (Chile)</b> y <b>Rocha (Brasil)</b> son las escuelas más cercanas al contexto de "
            "este plugin (vertiente andina / sudamericana) — aun así su coeficiente regional es justamente "
            "lo que absorbe la diferencia entre una cuenca chilena o brasileña y una altoandina peruana, "
            "así que deben calibrarse. <b>Turazza (Italia)</b> es la precursora del método racional: su "
            "factor 1/(1+0.05·Tc) REDUCE el caudal, al revés que la K de Témez que lo aumenta — compare "
            "ambos. <b>Murphy</b> NO tiene coeficiente regional: es una envolvente fija calibrada contra "
            "crecidas históricas del este de EE. UU., por lo que fuera de esa región es solo un techo "
            "histórico ajeno (esperable que salga muy por encima del resto, no lo tome como estimación "
            "transferible). Reutilizan A, S, C, I y Tc ya ingresados arriba.<br><br>"
            "<i>Possenti (Italia) y Kuichling (Nueva York) se retiraron de este cálculo: Possenti exige "
            "repartir el área entre zona montañosa y de valle, un dato que rara vez se tiene con soltura "
            "en una cuenca altoandina sin levantamiento de detalle, y Kuichling es una envolvente fija sin "
            "ningún coeficiente que la adapte fuera de Nueva York.</i>"
        )
        lbl_esc_info.setWordWrap(True)
        v_esc.addWidget(lbl_esc_info)

        f_esc = QFormLayout()
        f_esc.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.spin_esc_longitud = QDoubleSpinBox()
        self.spin_esc_longitud.setRange(0.01, 5000.0)
        self.spin_esc_longitud.setDecimals(3)
        self.spin_esc_longitud.setValue(10.0)
        f_esc.addRow("Longitud del cauce principal L (km, para Giandotti abajo):", self.spin_esc_longitud)
        self.spin_esc_p24 = QDoubleSpinBox()
        self.spin_esc_p24.setRange(1.0, 1000.0)
        self.spin_esc_p24.setValue(80.0)
        f_esc.addRow("Precipitación máxima en 24h P24 (mm, para Springall):", self.spin_esc_p24)
        self.spin_esc_santa_maria = QDoubleSpinBox()
        self.spin_esc_santa_maria.setRange(1.0, 80.0)
        self.spin_esc_santa_maria.setValue(25.0)
        f_esc.addRow("Coef. de Santa María C_s (15-40, vertiente andina):", self.spin_esc_santa_maria)
        self.spin_esc_springall = QDoubleSpinBox()
        self.spin_esc_springall.setRange(0.05, 1.0)
        self.spin_esc_springall.setDecimals(3)
        self.spin_esc_springall.setValue(0.50)
        f_esc.addRow("Coef. de Springall C_sp (0.20-0.80, cobertura/permeabilidad):", self.spin_esc_springall)
        self.spin_esc_rocha = QDoubleSpinBox()
        self.spin_esc_rocha.setRange(0.1, 15.0)
        self.spin_esc_rocha.setDecimals(3)
        self.spin_esc_rocha.setValue(2.5)
        f_esc.addRow("Coef. de Rocha C_r (1.5-5.0, factor regional brasileño):", self.spin_esc_rocha)
        self.spin_esc_lauterburg = QDoubleSpinBox()
        self.spin_esc_lauterburg.setRange(0.1, 6.0)
        self.spin_esc_lauterburg.setDecimals(3)
        self.spin_esc_lauterburg.setValue(1.0)
        f_esc.addRow("Coef. de Lauterburg C_l (0.8-2.5, climático/estacional):", self.spin_esc_lauterburg)
        v_esc.addLayout(f_esc)

        h_esc_btn = QHBoxLayout()
        btn_autocompletar_esc = QPushButton("Autocompletar L y P24 de otras pestañas")
        btn_autocompletar_esc.clicked.connect(self._on_autocompletar_escuelas_regionales)
        limitar_ancho_boton(btn_autocompletar_esc)
        h_esc_btn.addWidget(btn_autocompletar_esc)
        btn_calc_esc = QPushButton("Calcular escuelas regionales")
        btn_calc_esc.clicked.connect(self._on_calcular_escuelas_regionales)
        limitar_ancho_boton(btn_calc_esc)
        h_esc_btn.addWidget(btn_calc_esc)
        h_esc_btn.addStretch()
        v_esc.addLayout(h_esc_btn)

        self.tabla_resultado_escuelas = crear_tabla_parametros()
        v_esc.addWidget(self.tabla_resultado_escuelas)
        v.addWidget(gb_escuelas)

        # ---------- Métodos complementarios con datos adicionales ----------
        gb_complementarios = QGroupBox(
            "Métodos complementarios que requieren datos adicionales "
            "(Giandotti, Sokolovsky, Alekseev, Fuller, Gumbel-FFA, Talbot)"
        )
        v_comp = QVBoxLayout(gb_complementarios)
        lbl_comp_info = QLabel(
            "Estos necesitan información que las fórmulas de arriba no piden: cotas de la cuenca "
            "(Giandotti), lámina de escorrentía y duración de la crecida (Sokolovsky), parámetros "
            "climáticos y de vegetación (Alekseev), o directamente una SERIE DE CAUDALES AFORADOS "
            "(Fuller, Gumbel-FFA). <b>Si dispone de una estación de aforo en la cuenca, Fuller y "
            "Gumbel-FFA son la estimación más confiable de toda esta pestaña</b>, porque extrapolan a "
            "partir del caudal real del río en vez de una curva ajustada en otra región del mundo. "
            "<b>Talbot</b> es distinto a todos: NO devuelve un caudal sino el ÁREA DE SECCIÓN (m²) que "
            "requiere la obra de arte, por eso no aparece en el gráfico comparativo de caudales."
        )
        lbl_comp_info.setWordWrap(True)
        v_comp.addWidget(lbl_comp_info)

        f_comp = QFormLayout()
        f_comp.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.spin_comp_cota_media = QDoubleSpinBox()
        self.spin_comp_cota_media.setRange(0.0, 9000.0)
        self.spin_comp_cota_media.setValue(4000.0)
        f_comp.addRow("Cota media de la cuenca (m.s.n.m., Giandotti):", self.spin_comp_cota_media)
        self.spin_comp_cota_minima = QDoubleSpinBox()
        self.spin_comp_cota_minima.setRange(0.0, 9000.0)
        self.spin_comp_cota_minima.setValue(3500.0)
        f_comp.addRow("Cota mínima / de salida (m.s.n.m., Giandotti):", self.spin_comp_cota_minima)
        self.spin_comp_lambda_giandotti = QDoubleSpinBox()
        self.spin_comp_lambda_giandotti.setRange(0.01, 1.0)
        self.spin_comp_lambda_giandotti.setDecimals(3)
        self.spin_comp_lambda_giandotti.setValue(0.05)
        f_comp.addRow("λ de Giandotti (empírico, absorbe la conversión de unidades):",
                       self.spin_comp_lambda_giandotti)
        self.spin_comp_lamina_sokolovsky = QDoubleSpinBox()
        self.spin_comp_lamina_sokolovsky.setRange(0.1, 1000.0)
        self.spin_comp_lamina_sokolovsky.setValue(30.0)
        f_comp.addRow("Lámina de escorrentía h (mm, Sokolovsky; puede usar la lluvia efectiva de la Pestaña 6):",
                       self.spin_comp_lamina_sokolovsky)
        self.spin_comp_duracion_sokolovsky = QDoubleSpinBox()
        self.spin_comp_duracion_sokolovsky.setRange(0.1, 200.0)
        self.spin_comp_duracion_sokolovsky.setValue(2.0)
        f_comp.addRow("Duración de la crecida T (h, Sokolovsky):", self.spin_comp_duracion_sokolovsky)
        self.spin_comp_alekseev_hp = QDoubleSpinBox()
        self.spin_comp_alekseev_hp.setRange(0.001, 1.0)
        self.spin_comp_alekseev_hp.setDecimals(4)
        self.spin_comp_alekseev_hp.setValue(0.0850)
        f_comp.addRow("Hp de Alekseev (lámina de lluvia en METROS, no mm):", self.spin_comp_alekseev_hp)
        self.spin_comp_alekseev_n = QDoubleSpinBox()
        self.spin_comp_alekseev_n.setRange(0.1, 5.0)
        self.spin_comp_alekseev_n.setDecimals(3)
        self.spin_comp_alekseev_n.setValue(3.000)
        f_comp.addRow("n de Alekseev (exponente climático):", self.spin_comp_alekseev_n)
        self.spin_comp_alekseev_mu = QDoubleSpinBox()
        self.spin_comp_alekseev_mu.setRange(0.001, 1.0)
        self.spin_comp_alekseev_mu.setDecimals(3)
        # Por defecto, el MISMO coeficiente de escorrentía ya calculado
        # en la Pestaña 4 (self.spin_coef_c, construida antes que esta
        # pestaña): es la única estimación de cobertura/permeabilidad
        # que el usuario ya determinó con criterio para esta cuenca, en
        # vez de un valor genérico desconectado del resto del expediente.
        # El botón "Autocompletar" de abajo lo vuelve a sincronizar si
        # el usuario cambia el valor en la Pestaña 4 después.
        self.spin_comp_alekseev_mu.setValue(
            self.spin_coef_c.value() if hasattr(self, "spin_coef_c") else 0.500)
        f_comp.addRow("μ de Alekseev (vegetación/cobertura; por defecto = coef. de escorrentía, Pestaña 4):",
                       self.spin_comp_alekseev_mu)
        self.spin_comp_q_medio = QDoubleSpinBox()
        self.spin_comp_q_medio.setRange(0.0, 100000.0)
        self.spin_comp_q_medio.setDecimals(3)
        self.spin_comp_q_medio.setValue(0.0)
        f_comp.addRow("Media de caudales máximos anuales AFORADOS (m³/s; 0 = omitir Fuller y Gumbel-FFA):",
                       self.spin_comp_q_medio)
        self.spin_comp_q_desv = QDoubleSpinBox()
        self.spin_comp_q_desv.setRange(0.0, 100000.0)
        self.spin_comp_q_desv.setDecimals(3)
        self.spin_comp_q_desv.setValue(0.0)
        f_comp.addRow("Desviación estándar de esos caudales (m³/s, Gumbel-FFA):", self.spin_comp_q_desv)
        self.spin_comp_tr = QDoubleSpinBox()
        self.spin_comp_tr.setRange(1.01, 10000.0)
        self.spin_comp_tr.setValue(100.0)
        f_comp.addRow("Periodo de retorno Tr (años, para Fuller y Gumbel-FFA):", self.spin_comp_tr)
        self.spin_comp_talbot_ct = QDoubleSpinBox()
        self.spin_comp_talbot_ct.setRange(0.05, 2.0)
        self.spin_comp_talbot_ct.setDecimals(3)
        self.spin_comp_talbot_ct.setValue(0.200)
        f_comp.addRow("Ct de Talbot (~1.0 montañoso rocoso, ~0.2 llano permeable):", self.spin_comp_talbot_ct)
        v_comp.addLayout(f_comp)

        h_comp_btn = QHBoxLayout()
        btn_autocompletar_comp = QPushButton("Autocompletar cotas y lámina de otras pestañas")
        btn_autocompletar_comp.clicked.connect(self._on_autocompletar_complementarios)
        limitar_ancho_boton(btn_autocompletar_comp)
        h_comp_btn.addWidget(btn_autocompletar_comp)
        btn_calc_comp = QPushButton("Calcular métodos complementarios")
        btn_calc_comp.clicked.connect(self._on_calcular_metodos_complementarios)
        limitar_ancho_boton(btn_calc_comp)
        h_comp_btn.addWidget(btn_calc_comp)
        h_comp_btn.addStretch()
        v_comp.addLayout(h_comp_btn)

        self.tabla_resultado_complementarios = crear_tabla_parametros()
        v_comp.addWidget(self.tabla_resultado_complementarios)
        v.addWidget(gb_complementarios)

        gb_seccion_pendiente = QGroupBox(
            "Método indirecto Sección-Pendiente (aforo post-crecida, ecuación de Manning) + caudal crítico"
        )
        v_sp = QVBoxLayout(gb_seccion_pendiente)
        lbl_sp_info = QLabel(
            "A diferencia de las fórmulas de arriba (que ESTIMAN el caudal de diseño a partir de la "
            "cuenca), este es un método INDIRECTO de AFORO: reconstruye el caudal pico de una crecida "
            "YA OCURRIDA a partir de evidencia de campo levantada después del evento (marcas de agua, "
            "sección transversal y pendiente de la línea de energía medidas en el tramo), aplicando la "
            "ecuación de Manning. Útil para calibrar/verificar los coeficientes de las fórmulas "
            "envolventes de arriba contra un caudal real observado en la zona de estudio."
        )
        lbl_sp_info.setWordWrap(True)
        v_sp.addWidget(lbl_sp_info)

        f_sp = QFormLayout()
        f_sp.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.spin_sp_area = QDoubleSpinBox()
        self.spin_sp_area.setRange(0.01, 100000.0)
        self.spin_sp_area.setValue(3.0)
        f_sp.addRow("Área mojada A (m², medida en la sección aforada):", self.spin_sp_area)
        self.spin_sp_radio_h = QDoubleSpinBox()
        self.spin_sp_radio_h.setRange(0.01, 500.0)
        self.spin_sp_radio_h.setDecimals(3)
        self.spin_sp_radio_h.setValue(0.8)
        f_sp.addRow("Radio hidráulico R = A/P (m):", self.spin_sp_radio_h)
        self.spin_sp_pendiente = QDoubleSpinBox()
        self.spin_sp_pendiente.setRange(0.0001, 1.0)
        self.spin_sp_pendiente.setDecimals(4)
        self.spin_sp_pendiente.setValue(0.0100)
        f_sp.addRow("Pendiente de la línea de energía S (m/m):", self.spin_sp_pendiente)
        self.spin_sp_manning_n = QDoubleSpinBox()
        self.spin_sp_manning_n.setRange(0.010, 0.200)
        self.spin_sp_manning_n.setDecimals(3)
        self.spin_sp_manning_n.setValue(0.035)
        f_sp.addRow("Coeficiente de rugosidad de Manning n:", self.spin_sp_manning_n)
        self.spin_sp_area_critica = QDoubleSpinBox()
        self.spin_sp_area_critica.setRange(0.0, 100000.0)
        self.spin_sp_area_critica.setValue(0.0)
        f_sp.addRow("Área crítica Ac (m², opcional, 0 = no calcular Qc):", self.spin_sp_area_critica)
        self.spin_sp_ancho_critico = QDoubleSpinBox()
        self.spin_sp_ancho_critico.setRange(0.01, 1000.0)
        self.spin_sp_ancho_critico.setValue(10.0)
        f_sp.addRow("Ancho superficial crítico Bc (m, solo si Ac > 0):", self.spin_sp_ancho_critico)
        v_sp.addLayout(f_sp)

        btn_calc_sp = QPushButton("Calcular Sección-Pendiente / caudal crítico")
        btn_calc_sp.clicked.connect(self._on_calcular_seccion_pendiente)
        limitar_ancho_boton(btn_calc_sp)
        v_sp.addWidget(btn_calc_sp)

        self.tabla_resultado_seccion_pendiente = crear_tabla_parametros()
        v_sp.addWidget(self.tabla_resultado_seccion_pendiente)
        v.addWidget(gb_seccion_pendiente)

        v.addWidget(QLabel(
            "<b>Comparación gráfica — TODOS los métodos de caudal máximo calculados en esta pestaña</b> "
            "(se actualiza automáticamente al calcular cualquiera de los cuatro bloques de arriba: "
            "SCS/Snyder/Clark, Racional/Témez/Mac Math/Creager, las 10 fórmulas envolventes, y/o "
            "Sección-Pendiente/caudal crítico):"
        ))
        self.canvas_comparacion_qmax = HydrographCanvas(self, width=6.5, height=4.8)
        v.addWidget(self.canvas_comparacion_qmax)

        v.addWidget(QLabel("<b>Cuadro resumen final:</b>"))
        self.texto_resumen_caudales = ResumenFinal()
        v.addWidget(self.texto_resumen_caudales)
        self._actualizar_texto_resumen_caudales()

        self._agregar_pestaña_con_scroll(tab, "6. Caudales Máximos SCS/Clark/Témez/Creager/MacMath")

    def _actualizar_texto_resumen_caudales(self):
        """Cuadro resumen de la Pestaña 7: caudal pico por el método de
        transformación lluvia-escorrentía elegido (SCS/Snyder/Clark) y,
        si ya se calcularon, los 3 métodos directos (Témez/Mac Math/
        Creager) como verificación cruzada. Se llama automáticamente al
        calcular cualquiera de los dos."""
        html = "<h3>Cuadro resumen final — Caudales máximos</h3>"
        hay_algo = False
        if self.hidrograma_resultado:
            hay_algo = True
            r = self.hidrograma_resultado
            html += (
                f"<p><b>Transformación lluvia-escorrentía ({r.get('metodo', '')})</b><br>"
                f"Caudal pico Qp = <b>{r['caudal_pico_m3s']} m³/s</b> &nbsp;|&nbsp; "
                f"Tiempo pico Tp = {r['tiempo_pico_h']} h</p><hr>"
            )
        directos = self.resultados_hidraulica_drenaje.get("Caudales directos (Témez/Mac Math/Creager)")
        if directos:
            hay_algo = True
            html += (
                "<p><b>Métodos directos (verificación cruzada)</b><br>"
                f"Racional = {directos['Racional_Q_m3s']} m³/s &nbsp;|&nbsp; "
                f"Témez = {directos['Temez_Q_m3s']} m³/s &nbsp;|&nbsp; "
                f"Mac Math = {directos['MacMath_Q_m3s']} m³/s &nbsp;|&nbsp; "
                f"Creager = {directos['Creager_Q_m3s']} m³/s</p><hr>"
            )
        envolventes = self.resultados_hidraulica_drenaje.get(
            "Caudales envolventes (10 fórmulas regionales)"
        )
        if envolventes:
            hay_algo = True
            html += (
                "<p><b>Fórmulas envolventes / regionales (verificación cruzada)</b><br>"
                f"Dicken = {envolventes['dicken_Q_m3s']} m³/s &nbsp;|&nbsp; "
                f"Ryves = {envolventes['ryves_Q_m3s']} m³/s &nbsp;|&nbsp; "
                f"Inglis = {envolventes['inglis_Q_m3s']} m³/s &nbsp;|&nbsp; "
                f"Myer = {envolventes['myer_Q_m3s']} m³/s<br>"
                f"Kresnik = {envolventes['kresnik_Q_m3s']} m³/s &nbsp;|&nbsp; "
                f"Francou-Rodier = {envolventes['francou_rodier_Q_m3s']} m³/s &nbsp;|&nbsp; "
                f"Ventura = {envolventes['ventura_Q_m3s']} m³/s &nbsp;|&nbsp; "
                f"Bürkli-Ziegler = {envolventes['burkli_ziegler_Q_m3s']} m³/s<br>"
                f"Crippen & Bue = {envolventes['crippen_bue_Q_m3s']} m³/s &nbsp;|&nbsp; "
                f"Iszkowski = {envolventes['iszkowski_Q_m3s']} m³/s</p><hr>"
            )
        escuelas = self.resultados_hidraulica_drenaje.get("Caudales escuelas regionales (6 fórmulas)")
        if escuelas:
            hay_algo = True
            html += (
                "<p><b>Escuelas regionales (Latinoamérica / Europa clásica / Norteamérica histórica)</b><br>"
                f"Santa María = {escuelas['santa_maria_Q_m3s']} m³/s &nbsp;|&nbsp; "
                f"Springall = {escuelas['springall_Q_m3s']} m³/s &nbsp;|&nbsp; "
                f"Rocha = {escuelas['rocha_Q_m3s']} m³/s<br>"
                f"Lauterburg = {escuelas['lauterburg_Q_m3s']} m³/s &nbsp;|&nbsp; "
                f"Turazza = {escuelas['turazza_Q_m3s']} m³/s &nbsp;|&nbsp; "
                f"Murphy = {escuelas['murphy_Q_m3s']} m³/s</p><hr>"
            )
        complementarios = self.resultados_hidraulica_drenaje.get(
            "Caudales complementarios (Giandotti/Sokolovsky/...)")
        if complementarios:
            hay_algo = True
            partes = []
            for etiqueta, clave in [("Giandotti", "giandotti"), ("Sokolovsky", "sokolovsky"),
                                     ("Alekseev", "alekseev"),
                                     ("Fuller", "fuller"), ("Gumbel-FFA", "gumbel_ffa")]:
                if f"{clave}_Q_m3s" in complementarios:
                    partes.append(f"{etiqueta} = {complementarios[f'{clave}_Q_m3s']} m³/s")
            html += (
                "<p><b>Métodos complementarios (datos adicionales)</b><br>"
                + " &nbsp;|&nbsp; ".join(partes) + "</p><hr>"
            )
        seccion_pendiente = self.resultados_hidraulica_drenaje.get("Sección-Pendiente / caudal crítico")
        if seccion_pendiente:
            hay_algo = True
            html += (
                "<p><b>Método indirecto (aforo post-crecida)</b><br>"
                f"Sección-Pendiente (Manning) = {seccion_pendiente['Q_seccion_pendiente_m3s']} m³/s"
            )
            if seccion_pendiente.get("Q_critico_m3s") is not None:
                html += f" &nbsp;|&nbsp; Caudal crítico (Fr=1) = {seccion_pendiente['Q_critico_m3s']} m³/s"
            html += "</p><hr>"
        if not hay_algo:
            html += "<p style='color:#666666'>Aún no se ha calculado ningún caudal en esta pestaña.</p>"
        else:
            html += (
                "<p style='color:#666666'>NOTA: los métodos directos son una verificación cruzada de "
                "orden de magnitud, no reemplazan la transformación lluvia-escorrentía completa "
                "(SCS/Snyder/Clark) como caudal de diseño.</p>"
            )
        self.texto_resumen_caudales.setHtml(html)

    def _actualizar_grafico_hietograma(self, descripcion: str = ""):
        """
        Redibuja el gráfico del hietograma y su cuadro de impacto a partir
        del texto del campo, se haya generado con el botón o escrito a mano.

        Se conecta a textChanged para que el gráfico acompañe SIEMPRE a los
        valores: un hietograma editado a mano que ya no corresponde al
        gráfico mostrado sería peor que no tener gráfico.
        """
        try:
            hietograma = self._leer_hietograma_actual()
        except Exception:
            hietograma = []
        if not hietograma:
            self.cuadro_hietograma.actualizar(
                titulo="SIN HIETOGRAMA", valor_principal="—",
                subtitulo="Genérelo arriba o ingréselo a mano para ver su forma y su lámina")
            return
        dt_h = self.spin_dt_h.value()
        total = sum(hietograma)
        pico = max(hietograma)
        idx = hietograma.index(pico)
        intensidad_pico = pico / dt_h if dt_h else 0.0

        self.cuadro_hietograma.actualizar(
            titulo="HIETOGRAMA DE DISEÑO",
            valor_principal=f"Lámina total = {total:.1f} mm  en  {len(hietograma) * dt_h:.1f} h",
            subtitulo=descripcion or "es la tormenta que se transforma en el caudal de diseño",
            metricas=[("Intervalos", f"{len(hietograma)} × {dt_h} h"),
                       ("Pico", f"{pico:.2f} mm"),
                       ("Intensidad pico", f"{intensidad_pico:.1f} mm/h"),
                       ("Instante del pico", f"t = {idx * dt_h:.2f} h")],
            leyenda="la FORMA importa tanto como la lámina: fija el caudal punta",
            tipo="info")
        self.canvas_hietograma.plot_hietograma(hietograma, dt_h, descripcion)

    def _on_cambiar_metodo_desagregacion(self):
        # Los cuatro metodos basados en curva IDF usan el exponente y la
        # duracion; los patrones SCS no (siempre son de 24 h completas).
        clave_des = self.combo_metodo_desagregacion.currentData()
        es_idf = clave_des in ('idf_generica', 'dyck_peschke', 'bell', 'iila')
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
            clave = self.combo_metodo_desagregacion.currentData()

            if clave in ("idf_generica", "dyck_peschke", "bell", "iila"):
                # Los cuatro comparten el reparto por BLOQUES ALTERNOS; lo que
                # cambia es de dónde sale la curva IDF que los alimenta. Se
                # convierte cada método a su exponente de escalamiento
                # equivalente, que es el parámetro que consume design_storm.
                if clave == "dyck_peschke":
                    n_exp = 0.25   # exponente fijo del método (Dyck y Peschke, 1978)
                    descripcion_metodo = "bloques alternos sobre Dyck y Peschke / Grobe (n=0.25)"
                elif clave == "bell":
                    # Bell está calibrado para 5-120 min; para desagregar una
                    # tormenta de varias horas se usa el exponente equivalente
                    # que reproduce su relación de duraciones en ese rango.
                    n_exp = 0.25
                    descripcion_metodo = ("bloques alternos sobre Frederich Bell (1969); su rango "
                                          "validado es 5-120 min, verifique la duración elegida")
                elif clave == "iila":
                    n_exp = self.spin_iila_n.value() if hasattr(self, "spin_iila_n") else 0.254
                    descripcion_metodo = f"bloques alternos sobre IILA-SENAMHI-UNI (n={n_exp:.4f})"
                else:
                    n_exp = self.spin_exponente_disagregacion.value()
                    descripcion_metodo = f"bloques alternos (IDF genérica, n={n_exp})"
                hietograma = design_storm.bloques_alternos(p24, duracion_h, dt_h, exponente_n=n_exp)
            else:
                # IMPORTANTE: las curvas SCS representan una tormenta de 24 h
                # completas; NO deben comprimirse en una duración corta (eso
                # haría caer el 100% de P24 en esa ventana, sobrestimando
                # enormemente el caudal pico).
                tipo_scs = clave.replace("scs_", "")
                hietograma = scs_storm_patterns.hietograma_scs(p24, 24.0, dt_h, tipo=tipo_scs)
                descripcion_metodo = f"patrón SCS Tipo {tipo_scs} (aproximado, tormenta de 24h completa)"

            self.edit_hietograma.setPlainText(",".join(f"{v:.2f}" for v in hietograma))
            self._actualizar_grafico_hietograma(descripcion_metodo)
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
        mensajes = []
        if self.morfometria_resultados.get("g1"):
            self.spin_dir_a.setValue(self.morfometria_resultados["g1"]["A"])
            mensajes.append("A")
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
            mensajes.append("Tc")
        if self.morfometria_resultados.get("g3"):
            self.spin_dir_s.setValue(self.morfometria_resultados["g3"]["Se"] * 100.0)
            mensajes.append("S")
        elif self.morfometria_resultados.get("g4"):
            self.spin_dir_s.setValue(self.morfometria_resultados["g4"]["S_cuenca_pct"])
            mensajes.append("S")

        # Coeficiente de escorrentía C: el mismo ya determinado en la
        # Pestaña 4 (método FAA), en vez de dejar un valor genérico
        # desconectado del resto del expediente.
        if hasattr(self, "spin_coef_c"):
            self.spin_dir_c.setValue(self.spin_coef_c.value())
            mensajes.append("C (Pestaña 4)")

        # Intensidad de lluvia I: se evalúa la ecuación IDF combinada
        # (Pestaña 5) en t = Tc y en el Tr actualmente elegido, en vez de
        # dejar el valor genérico de 40 mm/h con el que arranca el
        # spinbox. Requiere haber calculado la IDF combinada en la
        # Pestaña 5 y tener un Tc > 0 disponible.
        combinada = (self.idf_resultados or {}).get("combinada")
        tr_sel, _ = self._tr_diseno_seleccionado()
        if combinada and tr_sel and self.spin_dir_tc.value() > 0:
            t_min = self.spin_dir_tc.value() * 60.0
            intensidad = combinada["K"] * (tr_sel ** combinada["m"]) / (t_min ** combinada["n_exp"])
            self.spin_dir_i.setValue(intensidad)
            mensajes.append(f"I = {intensidad:.2f} mm/h (curva IDF combinada, Tr={tr_sel}, t=Tc)")

        if not mensajes:
            QMessageBox.warning(
                self, "Nada que autocompletar",
                "Calcule primero la morfometría (pestaña 2), el Tc (pestaña 4) y/o la curva IDF "
                "combinada (pestaña 5)."
            )
            return
        QMessageBox.information(self, "Autocompletado", "Se autocompletó:\n- " + "\n- ".join(mensajes))

    def _on_calcular_caudales_directos(self):
        try:
            r = direct_discharge_methods.comparar_metodos_directos(
                coef_escorrentia_c=self.spin_dir_c.value(), intensidad_mm_h=self.spin_dir_i.value(),
                area_km2=self.spin_dir_a.value(), tc_horas=self.spin_dir_tc.value(),
                pendiente_cauce_pct=self.spin_dir_s.value(), coeficiente_creager=self.spin_dir_creager_c.value(),
            )
            qp_scs = self.hidrograma_resultado.get("caudal_pico_m3s") if self.hidrograma_resultado else None
            self.resultados_hidraulica_drenaje["Caudales directos (Témez/Mac Math/Creager)"] = {
                "tipo": "Caudales directos", "Racional_Q_m3s": r["racional"]["Q_m3_s"],
                "Temez_Q_m3s": r["temez"]["Q_m3_s"],
                "MacMath_Q_m3s": r["mac_math"]["Q_m3_s"], "Creager_Q_m3s": r["creager"]["Q_m3_s"],
                "Qp_SCS_Snyder_Clark_m3s": qp_scs,
            }
            filas_directos = [
                ("Racional (simple, sin K)", r["racional"]["Q_m3_s"], "m³/s",
                 "sin corrección de uniformidad -- compárese con Témez (mismo método + K)"),
                ("Témez", r["temez"]["Q_m3_s"], "m³/s", f"K = {r['temez']['coeficiente_uniformidad_K']}"),
                ("Mac Math", r["mac_math"]["Q_m3_s"], "m³/s"),
                ("Creager", r["creager"]["Q_m3_s"], "m³/s", r["creager"]["nota"]),
            ]
            if qp_scs is not None:
                filas_directos.append(
                    ("Qp SCS/Snyder/Clark (referencia, calculado arriba)", qp_scs, "m³/s")
                )
            poblar_tabla_parametros(self.tabla_resultado_caudales_directos, filas_directos)

            self._actualizar_grafico_comparacion_caudales()
            self._actualizar_texto_resumen_caudales()
            if hasattr(self, "texto_resumen_hidraulica"):
                self._actualizar_texto_resumen_hidraulica()
        except direct_discharge_methods.DirectDischargeError as e:
            QMessageBox.warning(self, "No se pudo calcular", str(e))

    def _on_autocompletar_envolventes(self):
        g2 = self.morfometria_resultados.get("g2")
        if not g2 or g2.get("Ff") is None:
            QMessageBox.warning(
                self, "Falta la morfometría",
                "Calcule primero el Grupo 2 (forma de la cuenca) en la Pestaña 2 — de ahí se toma "
                "Ff = A/Lb², el factor de forma que pide Iszkowski.")
            return
        self.spin_env_iszkowski_m.setValue(g2["Ff"])
        QMessageBox.information(
            self, "Autocompletado",
            f"m de Iszkowski = {g2['Ff']} (Ff = A/Lb² de la Pestaña 2, Grupo 2 — forma de la cuenca).")

    def _on_calcular_caudales_envolventes(self):
        try:
            pendiente_m_m = self.spin_dir_s.value() / 100.0
            r = direct_discharge_methods.comparar_metodos_envolventes(
                area_km2=self.spin_dir_a.value(), pendiente_m_m=pendiente_m_m,
                coef_escorrentia_c=self.spin_dir_c.value(), intensidad_mm_h=self.spin_dir_i.value(),
                coeficiente_dicken=self.spin_env_dicken.value(), coeficiente_ryves=self.spin_env_ryves.value(),
                coeficiente_myer=self.spin_env_myer.value(), coeficiente_kresnik=self.spin_env_kresnik.value(),
                k_francou_rodier=self.spin_env_fr.value(), coeficiente_ventura=self.spin_env_ventura.value(),
                k_regional_usgs=self.spin_env_usgs_kr.value(), exponente_b_usgs=self.spin_env_usgs_b.value(),
                coeficiente_iszkowski=self.spin_env_iszkowski_ci.value(),
                factor_forma_iszkowski=self.spin_env_iszkowski_m.value(),
            )
            self.resultados_hidraulica_drenaje[
                "Caudales envolventes (10 fórmulas regionales)"
            ] = {
                "tipo": "Caudales envolventes",
                **{f"{clave}_Q_m3s": datos["Q_m3_s"] for clave, datos in r.items()},
            }
            filas_env = [
                ("Dicken", r["dicken"]["Q_m3_s"], "m³/s", r["dicken"]["nota"]),
                ("Ryves", r["ryves"]["Q_m3_s"], "m³/s", r["ryves"]["nota"]),
                ("Inglis", r["inglis"]["Q_m3_s"], "m³/s", r["inglis"]["nota"]),
                ("Myer", r["myer"]["Q_m3_s"], "m³/s", r["myer"]["nota"]),
                ("Kresnik", r["kresnik"]["Q_m3_s"], "m³/s", r["kresnik"]["nota"]),
                ("Francou-Rodier", r["francou_rodier"]["Q_m3_s"], "m³/s", r["francou_rodier"]["nota"]),
                ("Ventura", r["ventura"]["Q_m3_s"], "m³/s", r["ventura"]["nota"]),
                ("Bürkli-Ziegler", r["burkli_ziegler"]["Q_m3_s"], "m³/s", r["burkli_ziegler"]["nota"]),
                ("Crippen & Bue (USGS)", r["crippen_bue"]["Q_m3_s"], "m³/s", r["crippen_bue"]["nota"]),
                ("Iszkowski", r["iszkowski"]["Q_m3_s"], "m³/s", r["iszkowski"]["nota"]),
            ]
            qp_scs = self.hidrograma_resultado.get("caudal_pico_m3s") if self.hidrograma_resultado else None
            if qp_scs is not None:
                filas_env.append(
                    ("Qp SCS/Snyder/Clark (referencia, calculado arriba)", qp_scs, "m³/s")
                )
            poblar_tabla_parametros(self.tabla_resultado_envolventes, filas_env)

            self._actualizar_grafico_comparacion_caudales()
            self._actualizar_texto_resumen_caudales()
            if hasattr(self, "texto_resumen_hidraulica"):
                self._actualizar_texto_resumen_hidraulica()
        except direct_discharge_methods.DirectDischargeError as e:
            QMessageBox.warning(self, "No se pudo calcular", str(e))

    def _parametros_perdidas_actuales(self):
        """
        Devuelve (modelo, params) según el selector de la Pestaña 7,
        listo para pasar a unit_hydrographs.hidrograma_de_crecida.

        Los parámetros se toman SIEMPRE de la Pestaña 3 (que es donde se
        configuran y calibran los modelos de pérdidas) en vez de duplicar
        los controles aquí: dos juegos de campos para lo mismo acabarían
        divergiendo y el usuario no sabría cuál se está aplicando.
        """
        modelo = self.combo_modelo_perdidas.currentData()
        if modelo in ("green_ampt", "horton", "philip", "kostiakov", "holtan"):
            return modelo, self.parametros_infiltracion(modelo)
        return "scs", None

    def _leer_hietograma_actual(self):
        import re
        texto = self.edit_hietograma.toPlainText().strip()
        return [float(t) for t in re.findall(r"-?\d+(?:\.\d+)?", texto)]

    def _on_comparar_modelos_perdidas(self):
        hietograma = self._leer_hietograma_actual()
        if not hietograma:
            QMessageBox.warning(self, "Falta el hietograma",
                                 "Genere o ingrese primero el hietograma de diseño (arriba).")
            return
        if not self.cn_resultados:
            QMessageBox.warning(
                self, "Falta el número de curva",
                "Calcule el número de curva en la pestaña 3 para poder comparar contra SCS-CN.")
            return
        try:
            dt_h = self.spin_dt_h.value()
            r = infiltration.comparar_modelos_perdidas(
                hietograma, dt_h,
                s_mm_scs=self.cn_resultados["S_mm"],
                green_ampt=self.parametros_infiltracion("green_ampt"),
                horton=self.parametros_infiltracion("horton"),
            )
            filas = [("Lluvia total del hietograma", sum(hietograma), "mm")]
            for clave in ("scs_cn", "green_ampt", "horton"):
                d = r[clave]
                comentario = f"coeficiente de escorrentía = {d['coeficiente_escorrentia']}"
                if d.get("hubo_encharcamiento"):
                    comentario += f"; encharcamiento a partir de t = {d['tiempo_encharcamiento_h']} h"
                filas.append((f"Lluvia efectiva — {d['metodo']}",
                               d["lluvia_efectiva_total_mm"], "mm", comentario))
            comp = r["comparacion"]
            filas.append(
                ("Dispersión entre modelos", comp["dispersion_mm"], "mm",
                 f"{comp['dispersion_relativa_pct']}% — {comp['nota']}"))
            poblar_tabla_parametros(self.tabla_comparacion_perdidas, filas)
        except infiltration.InfiltrationError as e:
            QMessageBox.warning(self, "No se pudo comparar", str(e))

    def _leer_caudales_observados(self):
        valores = []
        for fila in range(self.tabla_caudales_observados.rowCount()):
            item = self.tabla_caudales_observados.item(fila, 0)
            if item and item.text().strip():
                try:
                    valores.append(float(item.text().replace(",", ".")))
                except ValueError:
                    continue
        return valores

    def _on_estimar_intervalo_minimos(self):
        g1 = self.morfometria_resultados.get("g1")
        if not g1:
            QMessageBox.warning(self, "Falta la morfometría",
                                 "Calcule primero la morfometría (pestaña 2) para conocer el área.")
            return
        try:
            n = baseflow.intervalo_minimos_locales(g1["A"])
            self.spin_fb_intervalo.setValue(n)
            QMessageBox.information(
                self, "Intervalo estimado",
                f"Área de la cuenca = {g1['A']} km² ({g1['A'] * 0.386102:.1f} mi²).\n"
                f"Intervalo N = A^0.2 = {n} pasos de tiempo (redondeado al impar más próximo, "
                "según el procedimiento USGS/HYSEP)."
            )
        except baseflow.BaseflowError as e:
            QMessageBox.warning(self, "No se pudo estimar", str(e))

    def _on_separar_flujo_base(self):
        caudales = self._leer_caudales_observados()
        if len(caudales) < 3:
            QMessageBox.warning(
                self, "Faltan datos",
                "Ingrese al menos 3 caudales observados en la tabla (puede pegarlos desde Excel).")
            return
        try:
            r = baseflow.comparar_metodos_separacion(
                caudales,
                parametro_filtro=self.spin_fb_filtro.value(),
                n_pasadas=self.spin_fb_pasadas.value(),
                parametro_recesion=self.spin_fb_recesion.value(),
                bfi_max=self.combo_fb_bfimax.currentData(),
                intervalo_minimos=min(self.spin_fb_intervalo.value(), len(caudales)),
            )
            self.flujo_base_resultado = r
            comp = r["comparacion"]
            filas = []
            for clave in ("lyne_hollick", "eckhardt", "minimos_locales"):
                d = r[clave]
                filas.append((f"BFI — {d['metodo']}", d["BFI"], "",
                               f"{d['BFI_pct']}% del volumen es flujo base"))
            filas += [
                ("BFI promedio de los 3 métodos", comp["BFI_promedio"], ""),
                ("Dispersión entre métodos", comp["dispersion_BFI"], "",
                 comp["interpretacion_dispersion"]),
            ]
            # Se detalla el método de Eckhardt, que es el recomendado por
            # tener un tope físico (BFImax) en vez de depender del número
            # de pasadas como Lyne-Hollick.
            eck = r["eckhardt"]
            filas += [
                ("Caudal pico observado", eck["Qp_total_m3_s"], "m³/s"),
                ("Flujo base en el instante del pico (Eckhardt)",
                 eck["flujo_base_en_el_pico_m3_s"], "m³/s"),
                ("Escorrentía directa en el pico (Eckhardt)",
                 eck["escorrentia_directa_en_el_pico_m3_s"], "m³/s",
                 "es este valor, no el caudal total, el comparable con el Qp de los hidrogramas unitarios"),
                ("Interpretación del BFI", eck["BFI"], "", eck["interpretacion_bfi"]),
            ]
            poblar_tabla_parametros(self.tabla_resultado_flujo_base, filas)
            self.canvas_flujo_base.plot_separacion_flujo_base(
                eck["caudal_total_m3_s"], eck["flujo_base_m3_s"],
                eck["escorrentia_directa_m3_s"], eck["metodo"], eck["BFI"])
        except baseflow.BaseflowError as e:
            QMessageBox.warning(self, "No se pudo separar el flujo base", str(e))

    def _on_cambiar_metodo_transito(self):
        self.stack_transito.setCurrentIndex(self.combo_metodo_transito.currentIndex())

    def _on_autocompletar_transito(self):
        mensajes = []
        if self.morfometria_resultados.get("lc_km"):
            # Por defecto se propone transitar la mitad del cauce principal:
            # es un valor de arranque razonable cuando la obra está aguas
            # abajo, pero el usuario debe ajustarlo a su caso concreto.
            longitud_m = self.morfometria_resultados["lc_km"] * 1000.0 * 0.5
            self.spin_tr_longitud.setValue(longitud_m)
            mensajes.append(f"Longitud del tramo = {longitud_m:.0f} m (la mitad del cauce principal; ajústela).")
        g3 = self.morfometria_resultados.get("g3")
        if g3 and g3.get("Se"):
            self.spin_tr_pendiente.setValue(g3["Se"])
            mensajes.append(f"Pendiente del fondo = {g3['Se']:.4f} m/m (pendiente Se del cauce, pestaña 2).")
        elif self.morfometria_resultados.get("g4"):
            pendiente = self.morfometria_resultados["g4"]["S_cuenca_pct"] / 100.0
            self.spin_tr_pendiente.setValue(pendiente)
            mensajes.append(f"Pendiente = {pendiente:.4f} m/m (pendiente media de la cuenca).")
        if not mensajes:
            QMessageBox.warning(self, "Nada que autocompletar",
                                 "Calcule primero la morfometría en la pestaña 2.")
            return
        QMessageBox.information(
            self, "Autocompletado",
            "Se autocompletó:\n- " + "\n- ".join(mensajes) +
            "\n\nEl ancho superficial y la velocidad media debe ingresarlos usted (mídalos en campo o "
            "tómelos del dimensionamiento hidráulico de la pestaña 8)."
        )

    def _on_calcular_transito(self):
        if not self.hidrograma_resultado:
            QMessageBox.warning(
                self, "Falta el hidrograma",
                "Calcule primero el hidrograma de crecida en esta misma pestaña: el tránsito propaga "
                "ese hidrograma aguas abajo."
            )
            return
        try:
            entrada = self.hidrograma_resultado["caudal_m3s"]
            dt_h = self.spin_dt_h.value()
            metodo = self.combo_metodo_transito.currentData()

            if metodo == "muskingum_cunge":
                resultado = flood_routing.transitar_muskingum_cunge(
                    entrada, dt_h,
                    caudal_referencia_m3_s=self.hidrograma_resultado["caudal_pico_m3s"],
                    ancho_superficial_m=self.spin_tr_ancho.value(),
                    pendiente_fondo_m_m=self.spin_tr_pendiente.value(),
                    longitud_tramo_m=self.spin_tr_longitud.value(),
                    velocidad_media_m_s=self.spin_tr_velocidad.value(),
                )
            elif metodo == "muskingum":
                resultado = flood_routing.transitar_muskingum(
                    entrada, dt_h, k_horas=self.spin_tr_k.value(), x=self.spin_tr_x.value())
            else:
                almacenamientos, descargas = [], []
                for fila in range(self.tabla_curva_embalse.rowCount()):
                    it_s = self.tabla_curva_embalse.item(fila, 0)
                    it_o = self.tabla_curva_embalse.item(fila, 1)
                    if it_s and it_o and it_s.text().strip() and it_o.text().strip():
                        try:
                            almacenamientos.append(float(it_s.text().replace(",", ".")))
                            descargas.append(float(it_o.text().replace(",", ".")))
                        except ValueError:
                            continue
                if len(almacenamientos) < 2:
                    QMessageBox.warning(
                        self, "Curva del embalse incompleta",
                        "Ingrese al menos 2 puntos válidos (almacenamiento y descarga) en la tabla.")
                    return
                resultado = flood_routing.transitar_puls(
                    entrada, dt_h, almacenamientos, descargas,
                    almacenamiento_inicial_m3=self.spin_tr_s_inicial.value())

            self.transito_resultado = resultado
            p = resultado["parametros"]
            filas = [
                ("Método de tránsito", resultado["metodo"], ""),
                ("Caudal pico de ENTRADA al tramo", resultado["Qp_entrada_m3_s"], "m³/s"),
                ("Caudal pico de SALIDA (transitado)", resultado["Qp_salida_m3_s"], "m³/s",
                 "es el caudal de diseño en el punto de aguas abajo"),
                ("Atenuación del pico", resultado["atenuacion_m3_s"], "m³/s",
                 f"{resultado['atenuacion_pct']}% de reducción respecto a la entrada"),
                ("Retardo del pico", resultado["retardo_pico_h"], "h",
                 f"pico de entrada en t={resultado['tiempo_pico_entrada_h']} h, "
                 f"de salida en t={resultado['tiempo_pico_salida_h']} h"),
                ("Volumen de entrada", resultado["volumen_entrada_hm3"], "hm³"),
                ("Volumen de salida", resultado["volumen_salida_hm3"], "hm³",
                 f"error de conservación = {resultado['error_volumen_pct']}% "
                 f"({'correcto: el tránsito atenúa el pico pero no crea ni destruye agua' if resultado['conserva_volumen'] else 'ATENCIÓN: error alto, revise los parámetros'})"),
            ]
            if metodo == "muskingum_cunge":
                filas += [
                    ("K del tramo completo", p["K_total_h"], "h", "tiempo de viaje de la onda"),
                    ("Subtramos / refinamiento temporal",
                     f"{p['n_subtramos']} × {p['refinamiento_temporal']}", "",
                     f"discretización elegida para número de Courant = {p['numero_courant']} "
                     "(condición con la que el esquema es incondicionalmente estable)"),
                    ("X del subtramo", p["X_subtramo"], "", "derivado de la hidráulica del cauce"),
                    ("Celeridad de la onda", p["celeridad_m_s"], "m/s"),
                ]
            elif metodo == "muskingum":
                filas += [
                    ("K", p["K_h"], "h"), ("X", p["X"], ""),
                    ("Coeficientes C0 / C1 / C2",
                     f"{p['C0']:.4f} / {p['C1']:.4f} / {p['C2']:.4f}", "",
                     f"suma = {p['suma']:.6f} (debe ser exactamente 1)"),
                ]
            else:
                filas += [
                    ("Almacenamiento máximo alcanzado", resultado["almacenamiento_maximo_hm3"], "hm³"),
                    ("Puntos de la curva del embalse", p["puntos_curva_embalse"], ""),
                ]
            poblar_tabla_parametros(self.tabla_resultado_transito, filas)

            self.canvas_transito.plot_transito(
                resultado["tiempos_h"], resultado["caudal_entrada_m3_s"],
                resultado["caudal_salida_m3_s"], resultado["metodo"],
                resultado["Qp_entrada_m3_s"], resultado["Qp_salida_m3_s"],
                resultado["atenuacion_pct"], resultado["retardo_pico_h"],
                almacenamiento_m3=resultado.get("almacenamiento_m3"),
            )

            if resultado["estabilidad"]["advertencias"]:
                QMessageBox.warning(
                    self, "Advertencias del tránsito",
                    "El tránsito se calculó, pero con estas advertencias:\n\n- " +
                    "\n\n- ".join(resultado["estabilidad"]["advertencias"])
                )
        except flood_routing.FloodRoutingError as e:
            QMessageBox.warning(self, "No se pudo transitar", str(e))
        except Exception as e:
            QMessageBox.critical(self, "Error en el tránsito de avenidas", str(e))

    def _on_autocompletar_escuelas_regionales(self):
        mensajes = []
        if self.morfometria_resultados.get("lc_km"):
            self.spin_esc_longitud.setValue(self.morfometria_resultados["lc_km"])
            mensajes.append("L (longitud del cauce principal) desde la morfometría (pestaña 2).")
        tr_sel, p24_sel = self._tr_diseno_seleccionado()
        if tr_sel is not None:
            self.spin_esc_p24.setValue(p24_sel)
            mensajes.append(f"P24 = {p24_sel} mm (Tr={tr_sel} años, el elegido en el desplegable de "
                            "periodo de retorno de esta pestaña) desde la pestaña 5.")
        if not mensajes:
            QMessageBox.warning(
                self, "Nada que autocompletar",
                "Calcule primero la morfometría (pestaña 2) y/o el análisis de frecuencia (pestaña 5)."
            )
            return
        QMessageBox.information(self, "Autocompletado", "Se autocompletó:\n- " + "\n- ".join(mensajes))

    def _tr_diseno_seleccionado(self):
        """
        (Tr, P24) del periodo de retorno actualmente elegido en el
        desplegable "Periodo de retorno Tr" de esta pestaña
        (`combo_tr_hidrograma`), que es el mismo Tr con el que se generó
        el hietograma/hidrograma de diseño.

        POR QUÉ NO max(self.p24_disenio.keys()): así estaba antes, y
        como la lista estándar de periodos de retorno siempre incluye
        Tr=1000, todas las fórmulas de esta sección (escuelas regionales,
        Alekseev) quedaban calculadas SIEMPRE para Tr=1000 años, sin
        importar qué Tr hubiera elegido el usuario para el resto del
        diseño -- un caudal de una probabilidad de excedencia distinta a
        la que el proyecto realmente usa, calculado en silencio.

        Devuelve (None, None) si el usuario aún no calculó el análisis
        de frecuencia o no eligió un Tr.
        """
        tr = self.combo_tr_hidrograma.currentData()
        if tr is None or not self.p24_disenio:
            return None, None
        p24 = self.p24_disenio.get(tr)
        if p24 is None:
            # El Tr elegido es un T-Diseño personalizado que no quedó
            # registrado en p24_disenio (solo en el combo): se deriva de
            # la distribución de mejor ajuste, igual que al agregarlo.
            mejor = getattr(self, "mejor_ajuste_clave", None)
            if mejor and self.resultados_frecuencia.get(mejor):
                dist = self.resultados_frecuencia[mejor]["distribucion"]
                p24 = round(dist.cuantil(1.0 - 1.0 / tr), 2)
            else:
                return None, None
        return tr, p24

    def _on_calcular_escuelas_regionales(self):
        try:
            area_km2 = self.spin_dir_a.value()
            r = direct_discharge_methods.comparar_escuelas_regionales(
                area_km2=area_km2,
                pendiente_pct=self.spin_dir_s.value(), p24_mm=self.spin_esc_p24.value(),
                coef_escorrentia_c=self.spin_dir_c.value(), intensidad_mm_h=self.spin_dir_i.value(),
                tc_horas=self.spin_dir_tc.value(),
                coeficiente_santa_maria=self.spin_esc_santa_maria.value(),
                coeficiente_springall=self.spin_esc_springall.value(),
                coeficiente_rocha=self.spin_esc_rocha.value(),
                coeficiente_lauterburg=self.spin_esc_lauterburg.value(),
            )
            self.resultados_hidraulica_drenaje["Caudales escuelas regionales (6 fórmulas)"] = {
                "tipo": "Caudales escuelas regionales",
                **{f"{clave}_Q_m3s": datos["Q_m3_s"] for clave, datos in r.items()},
            }
            poblar_tabla_parametros(self.tabla_resultado_escuelas, [
                ("Santa María (Chile)", r["santa_maria"]["Q_m3_s"], "m³/s", r["santa_maria"]["nota"]),
                ("Springall (México)", r["springall"]["Q_m3_s"], "m³/s", r["springall"]["nota"]),
                ("Rocha (Brasil)", r["rocha"]["Q_m3_s"], "m³/s", r["rocha"]["nota"]),
                ("Lauterburg (Suiza)", r["lauterburg"]["Q_m3_s"], "m³/s", r["lauterburg"]["nota"]),
                ("Turazza (Italia)", r["turazza"]["Q_m3_s"], "m³/s",
                 f"factor de amortiguamiento = {r['turazza']['factor_amortiguamiento']} — {r['turazza']['nota']}"),
                ("Murphy (este de EE. UU.)", r["murphy"]["Q_m3_s"], "m³/s", r["murphy"]["nota"]),
            ])
            self._actualizar_grafico_comparacion_caudales()
            self._actualizar_texto_resumen_caudales()
            if hasattr(self, "texto_resumen_hidraulica"):
                self._actualizar_texto_resumen_hidraulica()
        except direct_discharge_methods.DirectDischargeError as e:
            QMessageBox.warning(self, "No se pudo calcular", str(e))

    def _on_autocompletar_complementarios(self):
        mensajes = []
        g1 = self.morfometria_resultados.get("g1")
        if g1:
            self.spin_comp_cota_media.setValue(g1["Zmed"])
            self.spin_comp_cota_minima.setValue(g1["Zmin"])
            mensajes.append(f"Cotas media ({g1['Zmed']} m) y mínima ({g1['Zmin']} m) desde la morfometría.")
        if self.hidrograma_resultado:
            lamina = sum(self.hidrograma_resultado.get("lluvia_efectiva_incr_mm", []))
            if lamina > 0:
                self.spin_comp_lamina_sokolovsky.setValue(lamina)
                mensajes.append(f"Lámina de escorrentía = {lamina:.2f} mm (lluvia efectiva del hidrograma).")
        tr_sel, p24_sel = self._tr_diseno_seleccionado()
        if tr_sel is not None:
            # Alekseev pide la lámina en METROS, no en mm.
            self.spin_comp_alekseev_hp.setValue(p24_sel / 1000.0)
            mensajes.append(f"Hp de Alekseev = {p24_sel / 1000.0:.4f} m (P24 del Tr elegido en el "
                            f"desplegable de esta pestaña, Tr={tr_sel}).")
        # μ (vegetación/cobertura) de Alekseev: por defecto, el mismo
        # coeficiente de escorrentía ya calculado en la Pestaña 4 -- es la
        # única estimación de cobertura/permeabilidad que el usuario ya
        # determinó con criterio para esta misma cuenca, en vez de dejar
        # un valor genérico desconectado del resto del expediente.
        if getattr(self, "spin_coef_c", None) is not None:
            self.spin_comp_alekseev_mu.setValue(self.spin_coef_c.value())
            mensajes.append(f"μ de Alekseev = {self.spin_coef_c.value()} (coeficiente de escorrentía "
                            "de la Pestaña 4).")
        if not mensajes:
            QMessageBox.warning(
                self, "Nada que autocompletar",
                "Calcule primero la morfometría (pestaña 2), el hidrograma (pestaña 7) y/o el análisis "
                "de frecuencia (pestaña 5)."
            )
            return
        QMessageBox.information(self, "Autocompletado", "Se autocompletó:\n- " + "\n- ".join(mensajes))

    def _on_calcular_metodos_complementarios(self):
        try:
            area_km2 = self.spin_dir_a.value()
            longitud_km = self.spin_esc_longitud.value()
            filas = []
            resultados = {"tipo": "Caudales complementarios"}

            r_gia = direct_discharge_methods.caudal_giandotti(
                area_km2=area_km2, longitud_cauce_km=longitud_km,
                cota_media_m=self.spin_comp_cota_media.value(),
                cota_minima_m=self.spin_comp_cota_minima.value(),
                p_max_mm=self.spin_esc_p24.value(),
                coeficiente_lambda=self.spin_comp_lambda_giandotti.value(),
            )
            resultados["giandotti_Q_m3s"] = r_gia["Q_m3_s"]
            filas.append(("Giandotti", r_gia["Q_m3_s"], "m³/s",
                           f"Tc de Giandotti = {r_gia['Tc_giandotti_h']} h — {r_gia['nota']}"))

            r_sok = direct_discharge_methods.caudal_sokolovsky(
                area_km2=area_km2, lamina_escorrentia_mm=self.spin_comp_lamina_sokolovsky.value(),
                duracion_horas=self.spin_comp_duracion_sokolovsky.value(),
            )
            resultados["sokolovsky_Q_m3s"] = r_sok["Q_m3_s"]
            filas.append(("Sokolovsky", r_sok["Q_m3_s"], "m³/s", r_sok["nota"]))

            r_ale = direct_discharge_methods.caudal_alekseev(
                area_km2=area_km2, tc_horas=self.spin_dir_tc.value(),
                hp_m=self.spin_comp_alekseev_hp.value(), n_clima=self.spin_comp_alekseev_n.value(),
                mu_vegetacion=self.spin_comp_alekseev_mu.value(),
            )
            resultados["alekseev_Q_m3s"] = r_ale["Q_m3_s"]
            filas.append(("Alekseev", r_ale["Q_m3_s"], "m³/s", r_ale["nota"]))

            # Fuller y Gumbel-FFA solo tienen sentido si el usuario aportó
            # la serie AFORADA de caudales máximos anuales.
            q_medio = self.spin_comp_q_medio.value()
            if q_medio > 0:
                r_ful = direct_discharge_methods.caudal_fuller(
                    caudal_medio_anual_m3_s=q_medio, area_km2=area_km2,
                    periodo_retorno_anios=self.spin_comp_tr.value(),
                )
                resultados["fuller_Q_m3s"] = r_ful["Q_m3_s"]
                filas.append(("Fuller", r_ful["Q_m3_s"], "m³/s",
                               f"factor Tr = {r_ful['factor_Tr']}, factor pico instantáneo = "
                               f"{r_ful['factor_pico_instantaneo']} — {r_ful['nota']}"))
                r_gum = direct_discharge_methods.caudal_gumbel_ffa(
                    media_caudales_m3_s=q_medio, desviacion_caudales_m3_s=self.spin_comp_q_desv.value(),
                    periodo_retorno_anios=self.spin_comp_tr.value(),
                )
                resultados["gumbel_ffa_Q_m3s"] = r_gum["Q_m3_s"]
                filas.append(("Gumbel-FFA (caudales aforados)", r_gum["Q_m3_s"], "m³/s",
                               f"KT = {r_gum['KT']} — {r_gum['nota']}"))
            else:
                filas.append(("Fuller / Gumbel-FFA", "no calculados", "—",
                               "Requieren la media (y desviación) de los caudales máximos anuales "
                               "AFORADOS; ingrésela arriba para habilitarlos."))

            r_tal = direct_discharge_methods.area_alcantarilla_talbot(
                area_ha=area_km2 * 100.0, coeficiente_ct=self.spin_comp_talbot_ct.value(),
            )
            filas.append(("Talbot — área de la obra de arte", r_tal["area_seccion_m2"], "m²",
                           f"NO es un caudal: es la sección requerida. {r_tal['nota']}"))

            self.resultados_hidraulica_drenaje["Caudales complementarios (Giandotti/Sokolovsky/...)"] = resultados
            poblar_tabla_parametros(self.tabla_resultado_complementarios, filas)
            self._actualizar_grafico_comparacion_caudales()
            self._actualizar_texto_resumen_caudales()
            if hasattr(self, "texto_resumen_hidraulica"):
                self._actualizar_texto_resumen_hidraulica()
        except direct_discharge_methods.DirectDischargeError as e:
            QMessageBox.warning(self, "No se pudo calcular", str(e))

    def _on_calcular_seccion_pendiente(self):
        try:
            r_sp = direct_discharge_methods.caudal_seccion_pendiente_manning(
                area_mojada_m2=self.spin_sp_area.value(), radio_hidraulico_m=self.spin_sp_radio_h.value(),
                pendiente_m_m=self.spin_sp_pendiente.value(), manning_n=self.spin_sp_manning_n.value(),
            )
            filas_sp = [
                ("Caudal (Sección-Pendiente, Manning)", r_sp["Q_m3_s"], "m³/s"),
                ("Velocidad media", r_sp["velocidad_m_s"], "m/s"),
            ]
            q_critico = None
            if self.spin_sp_area_critica.value() > 0:
                r_qc = direct_discharge_methods.caudal_critico(
                    area_critica_m2=self.spin_sp_area_critica.value(),
                    ancho_superficial_m=self.spin_sp_ancho_critico.value(),
                )
                q_critico = r_qc["Q_m3_s"]
                filas_sp.append(("Caudal crítico (Fr=1)", q_critico, "m³/s",
                                  "referencia de control de flujo del tramo aforado"))
            self.resultados_hidraulica_drenaje["Sección-Pendiente / caudal crítico"] = {
                "tipo": "Sección-Pendiente", "Q_seccion_pendiente_m3s": r_sp["Q_m3_s"], "Q_critico_m3s": q_critico,
            }
            poblar_tabla_parametros(self.tabla_resultado_seccion_pendiente, filas_sp)
            self._actualizar_grafico_comparacion_caudales()
            self._actualizar_texto_resumen_caudales()
            if hasattr(self, "texto_resumen_hidraulica"):
                self._actualizar_texto_resumen_hidraulica()
        except direct_discharge_methods.DirectDischargeError as e:
            QMessageBox.warning(self, "No se pudo calcular", str(e))

    def _actualizar_grafico_comparacion_caudales(self):
        """Gráfico de barras ÚNICO (Pestaña 7) que compara el caudal pico
        de TODOS los métodos ya calculados en esta pestaña -- SCS/Snyder/
        Clark, Racional/Témez/Mac Math/Creager, las 10 fórmulas
        envolventes/regionales y Sección-Pendiente/caudal crítico si se
        calcularon -- sin excepción y sin importar el orden en que el
        usuario los haya calculado (se llama al final de los botones de
        cálculo de esta pestaña, así que siempre refleja todo lo
        disponible en ese momento)."""
        nombres, valores, familias = [], [], []

        def _agregar(etiqueta, valor, familia):
            nombres.append(etiqueta)
            valores.append(valor)
            familias.append(familia)

        if self.hidrograma_resultado:
            _agregar(str(self.hidrograma_resultado.get("metodo", "SCS/Snyder/Clark")),
                     self.hidrograma_resultado["caudal_pico_m3s"], "Lluvia-escorrentía")
        directos = self.resultados_hidraulica_drenaje.get("Caudales directos (Témez/Mac Math/Creager)")
        if directos:
            for etiqueta, clave in [("Racional", "Racional_Q_m3s"), ("Témez", "Temez_Q_m3s"),
                                     ("Mac Math", "MacMath_Q_m3s"), ("Creager", "Creager_Q_m3s")]:
                _agregar(etiqueta, directos[clave], "Directo")
        envolventes = self.resultados_hidraulica_drenaje.get("Caudales envolventes (10 fórmulas regionales)")
        if envolventes:
            for etiqueta, clave in [("Dicken", "dicken"), ("Ryves", "ryves"), ("Inglis", "inglis"),
                                     ("Myer", "myer"), ("Kresnik", "kresnik"),
                                     ("Francou-Rodier", "francou_rodier"), ("Ventura", "ventura"),
                                     ("Bürkli-Ziegler", "burkli_ziegler"), ("Crippen & Bue", "crippen_bue"),
                                     ("Iszkowski", "iszkowski")]:
                _agregar(etiqueta, envolventes[f"{clave}_Q_m3s"], "Envolvente")
        escuelas = self.resultados_hidraulica_drenaje.get("Caudales escuelas regionales (6 fórmulas)")
        if escuelas:
            for etiqueta, clave in [("Santa María", "santa_maria"), ("Springall", "springall"),
                                     ("Rocha", "rocha"),
                                     ("Lauterburg", "lauterburg"), ("Turazza", "turazza"),
                                     ("Murphy", "murphy")]:
                _agregar(etiqueta, escuelas[f"{clave}_Q_m3s"], "Escuela regional")
        complementarios = self.resultados_hidraulica_drenaje.get(
            "Caudales complementarios (Giandotti/Sokolovsky/...)")
        if complementarios:
            # Fuller y Gumbel-FFA solo están presentes si el usuario aportó
            # la serie aforada; Talbot nunca entra (devuelve m², no m³/s).
            for etiqueta, clave in [("Giandotti", "giandotti"), ("Sokolovsky", "sokolovsky"),
                                     ("Alekseev", "alekseev"),
                                     ("Fuller", "fuller"), ("Gumbel-FFA", "gumbel_ffa")]:
                if f"{clave}_Q_m3s" in complementarios:
                    _agregar(etiqueta, complementarios[f"{clave}_Q_m3s"], "Complementario")
        seccion_pendiente = self.resultados_hidraulica_drenaje.get("Sección-Pendiente / caudal crítico")
        if seccion_pendiente:
            _agregar("Sección-Pendiente (aforo)", seccion_pendiente["Q_seccion_pendiente_m3s"],
                     "Aforo indirecto")
            if seccion_pendiente.get("Q_critico_m3s") is not None:
                _agregar("Caudal crítico", seccion_pendiente["Q_critico_m3s"], "Aforo indirecto")
        if nombres:
            self.canvas_comparacion_qmax.plot_comparacion_metodos(
                nombres, valores, titulo="Comparación de TODOS los métodos de caudal máximo",
                familias=familias,
            )

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

            modelo_perdidas, params_perdidas = self._parametros_perdidas_actuales()
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
                    modelo_perdidas=modelo_perdidas, params_perdidas=params_perdidas,
                    tlag_h=tl_h, duracion_efectiva_h=dt_h,
                )
            elif metodo_ui.startswith("Snyder"):
                lca = self.spin_lca_km.value() or (lc_km * 0.5)
                resultado = unit_hydrographs.hidrograma_de_crecida(
                    hietograma, dt_h, g1["A"], s_mm, "snyder",
                    modelo_perdidas=modelo_perdidas, params_perdidas=params_perdidas,
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
                    modelo_perdidas=modelo_perdidas, params_perdidas=params_perdidas,
                    tc_h=tc_h, r_storage_h=r_h,
                )

            self.hidrograma_resultado = resultado
            self.hidrograma_resultado["metodo"] = metodo_ui
            lluvia_efectiva_total = sum(resultado["lluvia_efectiva_incr_mm"])
            detalle = resultado.get("detalle_perdidas")
            nombre_perdidas = detalle["metodo"] if detalle else "SCS — Número de Curva"
            comentario_perdidas = (
                f"coeficiente de escorrentía = {detalle['coeficiente_escorrentia']}"
                + (f"; encharcamiento a partir de t = {detalle['tiempo_encharcamiento_h']} h"
                   if detalle.get("hubo_encharcamiento") else "; no se alcanzó el encharcamiento")
            ) if detalle else f"S = {s_mm:.1f} mm (pestaña 3)"
            poblar_tabla_parametros(self.tabla_resultado_qp, [
                ("Modelo de pérdidas usado", nombre_perdidas, "", comentario_perdidas),
                ("Caudal pico Qp", resultado["caudal_pico_m3s"], "m³/s"),
                ("Tiempo pico Tp", resultado["tiempo_pico_h"], "h"),
                ("Lluvia total", sum(hietograma), "mm"),
                ("Lluvia efectiva", lluvia_efectiva_total, "mm"),
                ("Volumen de escorrentía directa", resultado["volumen_escorrentia_directa_hm3"], "hm³"),
                ("Volumen de escorrentía directa", resultado["volumen_escorrentia_directa_m3"], "m³",
                 f"lámina equivalente = {resultado['lamina_efectiva_equivalente_mm']} mm "
                 f"(vs. lluvia efectiva = {lluvia_efectiva_total:.2f} mm, verificación de conservación de masa)"),
            ])
            self.canvas_hidrograma.plot_hidrograma(
                resultado["tiempos_h"], resultado["caudal_m3s"], metodo_ui,
                resultado["caudal_pico_m3s"], resultado["tiempo_pico_h"],
            )
            self._actualizar_grafico_comparacion_caudales()
            self._actualizar_texto_resumen_caudales()

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
            "Canales", "Alcantarilla", "Enrocado (RipRap)",
            "Sumideros", "Cunetas de coronación", "Pontón", "Puente", "Defensa Ribereña",
        ])
        self.combo_tipo_estructura.currentIndexChanged.connect(
            lambda i: self.stack_estructura.setCurrentIndex(i)
        )
        h_sel.addWidget(self.combo_tipo_estructura)
        v.addLayout(h_sel)

        self.stack_estructura = QStackedWidget()
        self.stack_estructura.addWidget(self._pagina_canales("Canales"))
        self.stack_estructura.addWidget(self._pagina_alcantarilla())
        self.stack_estructura.addWidget(self._pagina_enrocado())
        self.stack_estructura.addWidget(self._pagina_sumidero())
        self.stack_estructura.addWidget(self._pagina_canales("Cunetas de coronación (mismo motor de canales, sección pequeña)"))
        self.stack_estructura.addWidget(self._pagina_borde_libre("Pontón"))
        self.stack_estructura.addWidget(self._pagina_borde_libre("Puente"))
        self.stack_estructura.addWidget(self._pagina_defensa_ribereña())
        v.addWidget(self.stack_estructura)

        # Cuadro resumen: acumula TODAS las estructuras calculadas en esta
        # pestaña en esta sesión (no solo la que está visible en el
        # QStackedWidget en este momento), para tener de un vistazo todos
        # los parámetros obtenidos sin tener que ir estructura por
        # estructura. Se actualiza automáticamente al calcular cada una
        # (ver _actualizar_texto_resumen_hidraulica / _actualizar_tabla_comparativa_hidraulica).
        v.addWidget(QLabel(
            "<b>Cuadro comparativo final — todas las estructuras calculadas en esta sesión:</b>"))
        self.tabla_comparativa_hidraulica = QTableWidget(0, 9)
        self.tabla_comparativa_hidraulica.setHorizontalHeaderLabels([
            "Estructura", "Tipo", "n", "S (m/m)", "Q / Capacidad (m³/s)", "V (m/s)",
            "Qp objetivo (m³/s)", "¿Cumple?", "Comentario",
        ])
        self.tabla_comparativa_hidraulica.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla_comparativa_hidraulica.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.tabla_comparativa_hidraulica.horizontalHeader().setStretchLastSection(True)
        self.tabla_comparativa_hidraulica.verticalHeader().setVisible(False)
        v.addWidget(self.tabla_comparativa_hidraulica)

        self.lbl_recomendacion_hidraulica = QLabel()
        self.lbl_recomendacion_hidraulica.setWordWrap(True)
        self.lbl_recomendacion_hidraulica.setStyleSheet(
            "padding:8px; background:#EEF3F8; border:1px solid #B7CBE0; border-radius:4px;")
        v.addWidget(self.lbl_recomendacion_hidraulica)

        v.addWidget(QLabel(
            "<b>Detalle completo de cada estructura calculada</b> (todos los parámetros, no solo "
            "los de la tabla comparativa):"))
        self.texto_resumen_hidraulica = ResumenFinal()
        v.addWidget(self.texto_resumen_hidraulica)
        self._actualizar_texto_resumen_hidraulica()

        self._agregar_pestaña_con_scroll(tab, "7. Diseño Estructuras Hidráulicas")

    def _fila_fuente_datos(self, layout: QFormLayout, prefijo: str):
        """Botones para tomar Q de la pestaña 6, S de la morfometría (pestaña
        2) y n de la pestaña 4, comunes a varias páginas de la pestaña 7."""
        h = QHBoxLayout()
        btn_q = QPushButton("Usar Qp de la pestaña 6 (caudal pico)")
        btn_q.clicked.connect(lambda: self._usar_qp_pestaña6(prefijo))
        h.addWidget(btn_q)
        btn_s = QPushButton("Usar pendiente de la morfometría")
        btn_s.clicked.connect(lambda: self._usar_pendiente_morfometria(prefijo))
        h.addWidget(btn_s)
        btn_n = QPushButton("Usar n de la pestaña 4")
        btn_n.clicked.connect(lambda: self._usar_n_pestaña4(prefijo))
        h.addWidget(btn_n)
        layout.addRow(h)

    def _usar_n_pestaña4(self, prefijo: str):
        """Trae el coeficiente de rugosidad n desde la Pestaña 4: prioriza
        el último valor calculado con el catálogo de métodos (item 4:
        granulométrico/Cowan/Keulegan/sección compuesta) si ya se calculó
        en esta sesión, y si no cae al n de Kerby (el único n manual de
        esa pestaña)."""
        n, fuente = None, ""
        if getattr(self, "coef_n_calculado", None) is not None:
            n = self.coef_n_calculado
            fuente = "calculado en la Pestaña 4 con el catálogo de métodos de rugosidad"
        elif hasattr(self, "spin_n_kerby"):
            n = self.spin_n_kerby.value()
            fuente = "n de Kerby (Pestaña 4)"
        if n is None:
            QMessageBox.warning(
                self, "Falta el coeficiente n",
                "Calcule primero un n en la Pestaña 4 (sección «Coeficiente de rugosidad de "
                "Manning n — métodos de cálculo»), o ingrese al menos el n de Kerby.")
            return
        spin = getattr(self, f"spin_{prefijo}_n", None)
        if spin is not None:
            spin.setValue(n)
        else:
            QMessageBox.information(self, "n traído de la Pestaña 4", f"n = {n} ({fuente})")

    def _agregar_selector_material_n(self, layout: QFormLayout, spin_n: QDoubleSpinBox):
        """Desplegable con valores TÍPICOS de n por material de tubería o
        revestimiento (core.roughness_materials), a modo de catálogo de
        referencia estilo fabricante (p.ej. Master Flow) y de las tablas
        clásicas de Chow (1959)/ASCE. Al elegir un material se rellena el
        spinbox de n; el valor sigue siendo editable a mano después --
        es un punto de partida, no un valor normativo fijo."""
        combo_material = QComboBox()
        combo_material.addItem("(elegir material de referencia)", None)
        for nombre, n in roughness_materials.TABLA_MATERIALES_N_DEFAULT:
            combo_material.addItem(f"{nombre}  (n≈{n:.3f})", n)

        def _al_elegir(indice):
            valor = combo_material.itemData(indice)
            if valor is not None:
                spin_n.setValue(valor)

        combo_material.currentIndexChanged.connect(_al_elegir)
        layout.addRow("Material (referencia, opcional):", combo_material)
        return combo_material

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

    def _actualizar_texto_resumen_hidraulica(self):
        """Reconstruye el cuadro resumen HTML de la Pestaña 8 (Hidráulica y
        Drenaje) a partir de self.resultados_hidraulica_drenaje -- un
        diccionario compartido con la Pestaña 7 (Caudales directos), así
        que también puede incluir esa entrada si ya se calculó. Se llama
        automáticamente después de cada cálculo de cualquier estructura,
        para no depender de que el usuario pulse un botón aparte."""
        etiquetas = {
            "forma": "Forma", "n": "Manning n", "S": "Pendiente S (m/m)",
            "Q_m3s": "Q (m³/s)", "Q_o_spread": "Q (m³/s)",
            "tirante_normal_m": "Tirante normal (m)", "area_m2": "Área (m²)",
            "perimetro_m": "Perímetro (m)", "radio_hidraulico_m": "Radio hidráulico (m)",
            "ancho_superior_m": "Ancho superior (m)", "velocidad_m_s": "Velocidad (m/s)",
            "energia_especifica_m": "Energía específica (m)", "numero_froude": "Número de Froude",
            "tipo_flujo": "Tipo de flujo", "tirante_critico_m": "Tirante crítico (m)",
            "pendiente_critica": "Pendiente crítica (m/m)", "b_m": "b (m)", "z": "z (H:V)", "T_m": "T (m)",
            "subtipo": "Subtipo", "tirante_m": "Tirante (m)", "caudal_m3_s": "Caudal (m³/s)",
            "porcentaje_lleno_area": "% de área llena", "porcentaje_lleno_altura": "% de altura llena",
            "V_m_s": "Velocidad de diseño (m/s)", "peso_esp_roca_kN_m3": "Peso esp. de roca (kN/m³)",
            "D50_m": "D50 (m)", "D50_cm": "D50 (cm)", "gravedad_especifica_roca": "Gravedad específica de la roca",
            "L_m": "L (m)", "y_m": "Tirante (m)", "Cw": "Coeficiente de vertedero Cw",
            "caudal_interceptado_m3_s": "Caudal interceptado (m³/s)", "cota_agua_m": "Cota de agua (m s.n.m.)",
            "cota_estructura_m": "Cota de estructura (m s.n.m.)", "cota_corona_m": "Cota de corona (m s.n.m.)",
            "borde_libre_disponible_m": "Borde libre disponible (m)", "cumple": "¿Cumple?",
            "Temez_Q_m3s": "Q Témez (m³/s)", "MacMath_Q_m3s": "Q Mac Math (m³/s)",
            "Creager_Q_m3s": "Q Creager (m³/s)",
            "Qp_SCS_Snyder_Clark_m3s": "Qp SCS/Snyder/Clark (m³/s) [referencia]",
            "spread_T_m": "Ancho de inundación T (m)", "tirante_borde_m": "Tirante en el borde (m)",
            "Qp_objetivo_m3s": "Qp objetivo (pestaña 6) (m³/s)",
        }

        html = "<h3>Cuadro resumen final — Hidráulica y Drenaje</h3>"
        if not self.resultados_hidraulica_drenaje:
            html += "<p style='color:#666666'>Aún no se ha calculado ninguna estructura en esta sesión.</p>"
        for nombre, r in self.resultados_hidraulica_drenaje.items():
            partes = []
            for clave, valor in r.items():
                if clave == "tipo":
                    continue
                etiqueta = etiquetas.get(clave, clave.replace("_", " ").strip())
                if isinstance(valor, float):
                    valor_str = f"{valor:.4g}"
                elif isinstance(valor, bool):
                    valor_str = "Sí" if valor else "No"
                else:
                    valor_str = str(valor)
                partes.append(f"{etiqueta} = {valor_str}")
            html += f"<p><b>{nombre}</b><br>" + " &nbsp;|&nbsp; ".join(partes) + "</p><hr>"
        self.texto_resumen_hidraulica.setHtml(html)
        self._actualizar_tabla_comparativa_hidraulica()

    def _actualizar_tabla_comparativa_hidraulica(self):
        """Tabla comparativa (una fila por estructura calculada en la
        sesión) + una recomendación automática en texto. La recomendación
        solo compara DENTRO de categorías físicamente comparables entre sí
        (p.ej. canal contra canal, o alcantarilla contra alcantarilla) --
        comparar, por ejemplo, un canal contra la verificación de borde
        libre de un puente no tendría sentido hidráulico, así que esas
        categorías solo se revisan de forma individual (cumple/no cumple,
        velocidad dentro de un rango razonable)."""
        filas = []
        for nombre, r in self.resultados_hidraulica_drenaje.items():
            tipo = r.get("tipo", "")
            comentario_partes = []
            if "numero_froude" in r:
                comentario_partes.append(f"Fr={r['numero_froude']:.3g} ({r.get('tipo_flujo', '')})")
            if "porcentaje_lleno_area" in r:
                comentario_partes.append(f"{r['porcentaje_lleno_area']:.1f}% de área llena")
            if "porcentaje_lleno_altura" in r:
                comentario_partes.append(f"{r['porcentaje_lleno_altura']:.1f}% de altura llena")
            if "D50_cm" in r:
                comentario_partes.append(f"D50={r['D50_cm']:.1f} cm")
            if "borde_libre_disponible_m" in r:
                comentario_partes.append(f"BL disponible={r['borde_libre_disponible_m']:.2f} m")
            filas.append({
                "nombre": nombre, "tipo": tipo,
                "n": r.get("n"), "s": r.get("S"),
                "q": r.get("Q_m3s", r.get("caudal_m3_s", r.get("caudal_interceptado_m3_s", r.get("Q_o_spread")))),
                "v": r.get("velocidad_m_s", r.get("V_m_s")),
                "area": r.get("area_m2"),
                "qp_obj": r.get("Qp_objetivo_m3s"), "cumple": r.get("cumple"),
                "comentario": "; ".join(comentario_partes),
            })

        tabla = self.tabla_comparativa_hidraulica
        tabla.setRowCount(len(filas))
        for fila_idx, d in enumerate(filas):
            valores = [
                d["nombre"], d["tipo"],
                f"{d['n']:.4f}" if d["n"] is not None else "—",
                f"{d['s']:.5f}" if d["s"] is not None else "—",
                f"{d['q']:.4g}" if d["q"] is not None else "—",
                f"{d['v']:.3g}" if d["v"] is not None else "—",
                f"{d['qp_obj']:.4g}" if d["qp_obj"] is not None else "—",
                ("Sí" if d["cumple"] else "No") if d["cumple"] is not None else "—",
                d["comentario"] or "—",
            ]
            for col, val in enumerate(valores):
                item = QTableWidgetItem(str(val))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if col == 7 and d["cumple"] is not None:
                    item.setForeground(QColor("#1E8449") if d["cumple"] else QColor("#B3261E"))
                tabla.setItem(fila_idx, col, item)
        ajustar_alto_tabla(tabla, filas_visibles_max=max(len(filas), 1) + 1)
        tabla.resizeColumnsToContents()

        # -------------------- Recomendación automática --------------------
        partes_recomendacion = []
        if not filas:
            partes_recomendacion.append("Aún no se ha calculado ninguna estructura en esta sesión.")
        else:
            con_velocidad = [d for d in filas if d["v"] is not None]
            rapidas = [d for d in con_velocidad if d["v"] > 4.0]
            lentas = [d for d in con_velocidad if d["v"] < 0.4]
            if rapidas:
                partes_recomendacion.append(
                    "⚠ Velocidad alta (posible riesgo de erosión/socavación, V &gt; 4 m/s) en: " +
                    ", ".join(f"{d['nombre']} ({d['v']:.2f} m/s)" for d in rapidas) + ".")
            if lentas:
                partes_recomendacion.append(
                    "⚠ Velocidad baja (posible riesgo de sedimentación, V &lt; 0.4 m/s) en: " +
                    ", ".join(f"{d['nombre']} ({d['v']:.2f} m/s)" for d in lentas) + ".")

            no_cumplen_bl = [d for d in filas if d["cumple"] is False and
                              d["tipo"] in ("Pontón", "Puente", "Defensa Ribereña")]
            if no_cumplen_bl:
                partes_recomendacion.append(
                    "✘ NO cumplen el borde libre mínimo: " + ", ".join(d["nombre"] for d in no_cumplen_bl) + ".")

            conduccion = [d for d in filas if d["tipo"] in ("Canal", "Alcantarilla") or
                          str(d["tipo"]).startswith("Canal (Gutter")]
            if len(conduccion) >= 2:
                con_qp = [d for d in conduccion if d["qp_obj"] is not None]
                if con_qp:
                    cumplen = [d for d in con_qp if d["cumple"]]
                    if cumplen:
                        candidatos_area = [d for d in cumplen if d["area"] is not None]
                        if candidatos_area:
                            mejor = min(candidatos_area, key=lambda d: d["area"])
                            partes_recomendacion.append(
                                f"✔ De las estructuras de conducción que SÍ cumplen su Qp objetivo, "
                                f"«{mejor['nombre']}» es la más económica (menor área mojada = "
                                f"{mejor['area']:.3f} m², V={mejor['v']:.2f} m/s si está disponible).")
                        else:
                            partes_recomendacion.append(
                                "Hay estructuras de conducción que cumplen su Qp objetivo, pero falta el "
                                "área de alguna para comparar cuál es más económica.")
                    else:
                        partes_recomendacion.append(
                            "✘ NINGUNA de las estructuras de conducción con Qp objetivo definido lo "
                            "cumple todavía -- revise diámetro/ancho/alto o el tirante de trabajo.")
                else:
                    candidatos_v = [d for d in conduccion if d["v"] is not None]
                    if candidatos_v:
                        mejor = min(candidatos_v, key=lambda d: abs(d["v"] - 1.5))
                        partes_recomendacion.append(
                            f"De los canales calculados (dimensionados cada uno para su propio Q de "
                            f"diseño; no hay un «cumple/no cumple» que comparar entre ellos), "
                            f"«{mejor['nombre']}» tiene la velocidad más cercana a un rango típico "
                            f"no erosivo/no sedimentante (V={mejor['v']:.2f} m/s) -- verifique "
                            f"igualmente contra la norma local vigente.")
            elif len(conduccion) == 1:
                partes_recomendacion.append(
                    "Solo hay una estructura de conducción (canal o alcantarilla) calculada en esta "
                    "sesión; calcule al menos otra para obtener una recomendación comparativa.")

        if not partes_recomendacion:
            partes_recomendacion.append(
                "Sin observaciones automáticas adicionales para las estructuras calculadas -- revise "
                "igualmente la tabla comparativa de arriba.")
        self.lbl_recomendacion_hidraulica.setText(
            "<b>Recomendación / observaciones automáticas:</b><br>" + "<br>".join(partes_recomendacion))

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
        combo_material = self._agregar_selector_material_n(f, spin_n)

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
        setattr(self, f"combo_{prefijo}_material", combo_material)
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

        lbl_estado = QLabel("Estado: sin calcular.")
        lbl_estado.setWordWrap(True)
        v.addWidget(lbl_estado)
        setattr(self, f"lbl_{prefijo}_estado", lbl_estado)

        tabla_resultado = crear_tabla_parametros()
        v.addWidget(tabla_resultado)
        setattr(self, f"tabla_{prefijo}_resultado", tabla_resultado)

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
        lbl_estado = getattr(self, f"lbl_{prefijo}_estado")
        tabla_resultado = getattr(self, f"tabla_{prefijo}_resultado")
        try:
            if forma.startswith("Rectangular"):
                r = hydraulic_structures.canal_rectangular_maxima_eficiencia(n, s, q=q)
                extra = "b = 2y (máxima eficiencia)"
            elif forma.startswith("Triangular"):
                r = hydraulic_structures.canal_triangular_maxima_eficiencia(n, s, q=q)
                extra = "taludes a 45° (máxima eficiencia)"
            elif forma == "Trapezoidal (máx. eficiencia)":
                r = hydraulic_structures.canal_trapezoidal_maxima_eficiencia(n, s, q=q)
                extra = "semihexágono (máxima eficiencia)"
            elif forma == "Trapezoidal (geometría dada)":
                b = getattr(self, f"spin_{prefijo}_b").value()
                z = getattr(self, f"spin_{prefijo}_z").value()
                r = hydraulic_structures.canal_trapezoidal_general(n, s, b, z, q=q)
                extra = "geometría ingresada por el usuario"
            elif forma == "Parabólico":
                t = getattr(self, f"spin_{prefijo}_t").value()
                r = hydraulic_structures.canal_parabolico(n, s, t, q=q)
                extra = ""
            elif forma.startswith("Gutter"):
                sx = getattr(self, f"spin_{prefijo}_sx").value()
                res = hydraulic_structures.cuneta_vial_hec22(n, s, sx, q=q)
                lbl_estado.setText(f"Estado: calculado (Cuneta vial FHWA HEC-22). {res.get('advertencia', '')}")
                poblar_tabla_parametros(tabla_resultado, [
                    ("Ancho de inundación (spread) T", res["spread_T_m"], "m"),
                    ("Tirante en el borde", res["tirante_borde_m"], "m"),
                    ("Área", res["area_m2"], "m²"),
                    ("Velocidad", res["velocidad_m_s"], "m/s"),
                    ("Caudal", res["caudal_m3_s"], "m³/s"),
                ])
                canvas = getattr(self, f"canvas_{prefijo}_seccion")
                canvas.plot_triangular(1.0 / sx, res["tirante_borde_m"])
                self.resultados_hidraulica_drenaje[f"Canal/cuneta - {forma}"] = {
                    "tipo": "Canal (Gutter/cuneta vial HEC-22)", "forma": forma,
                    "n": n, "S": s, "Q_o_spread": q,
                    **{k: v for k, v in res.items() if k != "advertencia"},
                }
                self._actualizar_texto_resumen_hidraulica()
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

            lbl_estado.setText(f"Estado: calculado ({r.forma}).")
            poblar_tabla_parametros(tabla_resultado, [
                ("Forma", r.forma, "", extra),
                ("Tirante normal y", r.y_m, "m"),
                ("Área", r.area_m2, "m²"),
                ("Perímetro mojado", r.perimetro_m, "m"),
                ("Radio hidráulico", r.radio_hidraulico_m, "m"),
                ("Ancho superior", r.ancho_superior_m, "m"),
                ("Velocidad", r.velocidad_m_s, "m/s"),
                ("Energía específica", r.energia_especifica_m, "m"),
                ("Número de Froude", r.numero_froude, "adim.", r.tipo_flujo),
                ("Tirante crítico", r.tirante_critico_m, "m"),
                ("Pendiente crítica", r.pendiente_critica, "m/m"),
            ])

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
            self._actualizar_texto_resumen_hidraulica()
        except Exception as e:
            lbl_estado.setText(f"Estado: ERROR -- {e}")

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
        combo_material = self._agregar_selector_material_n(f, spin_n)
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
        spin_qp_objetivo = QDoubleSpinBox(); spin_qp_objetivo.setRange(0.0, 10000.0); spin_qp_objetivo.setDecimals(3)
        spin_qp_objetivo.setSpecialValueText("(sin verificar contra un Qp objetivo)")
        f.addRow("Qp objetivo a verificar (opcional) (m³/s):", spin_qp_objetivo)

        v.addLayout(f)

        h_fuente = QHBoxLayout()
        btn_qp = QPushButton("Usar Qp de la pestaña 6 (caudal pico)")
        btn_qp.clicked.connect(lambda: self.spin_alcant_qp_objetivo.setValue(
            self.hidrograma_resultado["caudal_pico_m3s"]) if self.hidrograma_resultado else
            QMessageBox.warning(self, "Falta el caudal", "Calcule primero el hidrograma en la pestaña 6."))
        h_fuente.addWidget(btn_qp)
        btn_s2 = QPushButton("Usar pendiente de la morfometría")
        btn_s2.clicked.connect(lambda: self._usar_pendiente_morfometria("alcant"))
        h_fuente.addWidget(btn_s2)
        btn_n2 = QPushButton("Usar n de la pestaña 4")
        btn_n2.clicked.connect(lambda: self._usar_n_pestaña4("alcant"))
        h_fuente.addWidget(btn_n2)
        v.addLayout(h_fuente)

        btn = QPushButton("Calcular capacidad")
        v.addWidget(btn)
        lbl_estado = QLabel("Estado: sin calcular.")
        lbl_estado.setWordWrap(True)
        v.addWidget(lbl_estado)

        self.canvas_alcant_seccion = SeccionTransversalCanvas(pagina)
        v.addWidget(self.canvas_alcant_seccion)
        self.tabla_alcant_resultado = crear_tabla_parametros()
        v.addWidget(self.tabla_alcant_resultado)

        self.spin_alcant_n, self.spin_alcant_s = spin_n, spin_s
        self.combo_alcant_tipo = combo_tipo
        self.combo_alcant_material = combo_material
        self.spin_alcant_diametro, self.spin_alcant_ancho = spin_diametro, spin_ancho
        self.spin_alcant_alto, self.spin_alcant_y = spin_alto, spin_y
        self.spin_alcant_qp_objetivo = spin_qp_objetivo
        self.lbl_alcant_resultado = lbl_estado

        btn.clicked.connect(self._on_calcular_alcantarilla)
        return pagina

    def _on_calcular_alcantarilla(self):
        try:
            n, s, y = self.spin_alcant_n.value(), self.spin_alcant_s.value(), self.spin_alcant_y.value()
            if self.combo_alcant_tipo.currentText().startswith("Circular"):
                r = hydraulic_structures.alcantarilla_circular_capacidad(n, s, self.spin_alcant_diametro.value(), y)
                etiqueta_pct, valor_pct = "% de área llena", r["porcentaje_lleno_area"]
                self.canvas_alcant_seccion.plot_circular(self.spin_alcant_diametro.value(), y)
            else:
                r = hydraulic_structures.alcantarilla_cajon_capacidad(
                    n, s, self.spin_alcant_ancho.value(), self.spin_alcant_alto.value(), y
                )
                etiqueta_pct, valor_pct = "% de altura llena", r["porcentaje_lleno_altura"]
                self.canvas_alcant_seccion.plot_cajon(self.spin_alcant_ancho.value(), self.spin_alcant_alto.value(), y)

            # Verificación opcional contra el Qp de diseño (pestaña 6): la
            # capacidad se calcula para el tirante de trabajo y ingresado,
            # así que "cumple" aquí significa que a ESE tirante ya se
            # transporta el Qp objetivo -- no es un dimensionamiento
            # automático del diámetro/tirante necesario.
            qp_obj = self.spin_alcant_qp_objetivo.value()
            fila_verificacion = []
            if qp_obj > 0:
                cumple_qp = r["caudal_m3_s"] >= qp_obj
                fila_verificacion = [
                    ("Qp objetivo (pestaña 6)", qp_obj, "m³/s"),
                    ("¿Capacidad ≥ Qp objetivo?", "Sí" if cumple_qp else "No", "",
                     "al tirante de trabajo y ingresado; si NO cumple, aumente D/ancho/alto o el "
                     "tirante de trabajo, y vuelva a calcular"),
                ]

            self.lbl_alcant_resultado.setText(f"Estado: calculado. {r['advertencia']}")
            poblar_tabla_parametros(self.tabla_alcant_resultado, [
                ("Área", r["area_m2"], "m²"),
                ("Perímetro", r["perimetro_m"], "m"),
                ("Radio hidráulico", r["radio_hidraulico_m"], "m"),
                (etiqueta_pct, valor_pct, "%"),
                ("Caudal (capacidad)", r["caudal_m3_s"], "m³/s"),
                ("Velocidad", r["velocidad_m_s"], "m/s"),
                *fila_verificacion,
            ])
            self.resultados_hidraulica_drenaje[f"Alcantarilla - {self.combo_alcant_tipo.currentText()}"] = {
                "tipo": "Alcantarilla", "subtipo": self.combo_alcant_tipo.currentText(),
                "n": n, "S": s, "tirante_m": y,
                **{k: v for k, v in r.items() if k != "advertencia"},
                **({"Qp_objetivo_m3s": qp_obj, "cumple": cumple_qp} if qp_obj > 0 else {}),
            }
            self._actualizar_texto_resumen_hidraulica()
        except Exception as e:
            self.lbl_alcant_resultado.setText(f"Estado: ERROR -- {e}")

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
        lbl_estado = QLabel("Estado: sin calcular.")
        lbl_estado.setWordWrap(True)
        v.addWidget(lbl_estado)

        self.canvas_enrocado = SeccionTransversalCanvas(pagina)
        v.addWidget(self.canvas_enrocado)
        tabla_resultado = crear_tabla_parametros()
        v.addWidget(tabla_resultado)

        def calcular():
            try:
                expuesta = combo_exposicion.currentIndex() == 0
                r = hydraulic_structures.enrocado_isbash(spin_v.value(), spin_peso.value(), expuesta)
                lbl_estado.setText("Estado: calculado.")
                poblar_tabla_parametros(tabla_resultado, [
                    ("D50", r["D50_m"], "m"),
                    ("D50", r["D50_cm"], "cm"),
                    ("Gravedad específica de la roca", r["gravedad_especifica_roca"], "adim."),
                    ("Coeficiente de Isbash C", r["coeficiente_isbash"], "adim.", r["nota"]),
                ])
                self.canvas_enrocado.plot_riprap_talud(spin_v.value(), r["D50_m"])
                self.resultados_hidraulica_drenaje["Enrocado (RipRap)"] = {
                    "tipo": "Enrocado (RipRap)", "V_m_s": spin_v.value(), "peso_esp_roca_kN_m3": spin_peso.value(),
                    "D50_m": r["D50_m"], "D50_cm": r["D50_cm"], "gravedad_especifica_roca": r["gravedad_especifica_roca"],
                }
                self._actualizar_texto_resumen_hidraulica()
            except Exception as e:
                lbl_estado.setText(f"Estado: ERROR -- {e}")

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
        spin_qp_objetivo = QDoubleSpinBox(); spin_qp_objetivo.setRange(0.0, 10000.0); spin_qp_objetivo.setDecimals(3)
        spin_qp_objetivo.setSpecialValueText("(sin verificar contra un Qp objetivo)")
        f.addRow("Qp objetivo a verificar (opcional) (m³/s):", spin_qp_objetivo)
        v.addLayout(f)

        btn_qp = QPushButton("Usar Qp de la pestaña 6 (caudal pico)")
        btn_qp.clicked.connect(lambda: spin_qp_objetivo.setValue(self.hidrograma_resultado["caudal_pico_m3s"])
                                if self.hidrograma_resultado else
                                QMessageBox.warning(self, "Falta el caudal", "Calcule primero el hidrograma en la pestaña 6."))
        v.addWidget(btn_qp)

        btn = QPushButton("Calcular capacidad de intercepción")
        v.addWidget(btn)
        lbl_estado = QLabel("Estado: sin calcular.")
        lbl_estado.setWordWrap(True)
        v.addWidget(lbl_estado)

        self.canvas_sumidero = SeccionTransversalCanvas(pagina)
        v.addWidget(self.canvas_sumidero)
        tabla_resultado = crear_tabla_parametros()
        v.addWidget(tabla_resultado)

        def calcular():
            try:
                r = hydraulic_structures.sumidero_capacidad_vertedero(spin_l.value(), spin_y.value(), spin_cw.value())
                qp_obj = spin_qp_objetivo.value()
                fila_verificacion = []
                cumple_qp = None
                if qp_obj > 0:
                    cumple_qp = r["caudal_interceptado_m3_s"] >= qp_obj
                    fila_verificacion = [
                        ("Qp objetivo (pestaña 6)", qp_obj, "m³/s"),
                        ("¿Intercepta el Qp objetivo?", "Sí" if cumple_qp else "No", "",
                         "si NO cumple, aumente L o agregue sumideros adicionales en serie"),
                    ]
                lbl_estado.setText(f"Estado: calculado. {r['advertencia']}")
                poblar_tabla_parametros(tabla_resultado, [
                    ("Caudal interceptado", r["caudal_interceptado_m3_s"], "m³/s"),
                    *fila_verificacion,
                ])
                self.canvas_sumidero.plot_ventana_sumidero(spin_l.value(), spin_y.value(), r["caudal_interceptado_m3_s"])
                self.resultados_hidraulica_drenaje["Sumidero"] = {
                    "tipo": "Sumidero", "L_m": spin_l.value(), "y_m": spin_y.value(), "Cw": spin_cw.value(),
                    "caudal_interceptado_m3_s": r["caudal_interceptado_m3_s"],
                    **({"Qp_objetivo_m3s": qp_obj, "cumple": cumple_qp} if qp_obj > 0 else {}),
                }
                self._actualizar_texto_resumen_hidraulica()
            except Exception as e:
                lbl_estado.setText(f"Estado: ERROR -- {e}")

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
        lbl_estado = QLabel("Estado: sin calcular.")
        lbl_estado.setWordWrap(True)
        v.addWidget(lbl_estado)

        canvas_bl = SeccionTransversalCanvas(pagina)
        v.addWidget(canvas_bl)
        setattr(self, f"canvas_bl_{nombre_estructura}", canvas_bl)  # referencia con nombre único (Pontón/Puente)
        tabla_resultado = crear_tabla_parametros()
        v.addWidget(tabla_resultado)

        def calcular():
            try:
                r = hydraulic_structures.verificar_borde_libre(
                    spin_cota_agua.value(), spin_cota_estructura.value(), spin_bl_min.value()
                )
                estado = "✔ CUMPLE" if r["cumple"] else "✘ NO CUMPLE"
                lbl_estado.setText(f"Estado: {estado} -- {r['mensaje']}")
                poblar_tabla_parametros(tabla_resultado, [
                    ("Borde libre disponible", r["borde_libre_disponible_m"], "m"),
                    ("Borde libre mínimo requerido", r["borde_libre_minimo_requerido_m"], "m"),
                    ("¿Cumple?", "Sí" if r["cumple"] else "No", "", r["nota"]),
                ])
                canvas_bl.plot_borde_libre(spin_cota_agua.value(), spin_cota_estructura.value(),
                                            spin_bl_min.value(), nombre_estructura, r["cumple"])
                self.resultados_hidraulica_drenaje[nombre_estructura] = {
                    "tipo": nombre_estructura, "cota_agua_m": spin_cota_agua.value(),
                    "cota_estructura_m": spin_cota_estructura.value(),
                    "borde_libre_disponible_m": r["borde_libre_disponible_m"], "cumple": r["cumple"],
                }
                self._actualizar_texto_resumen_hidraulica()
            except Exception as e:
                lbl_estado.setText(f"Estado: ERROR -- {e}")

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
        lbl_estado = QLabel("Estado: sin calcular.")
        lbl_estado.setWordWrap(True)
        v.addWidget(lbl_estado)

        self.canvas_defensa_bl = SeccionTransversalCanvas(pagina)
        v.addWidget(self.canvas_defensa_bl)
        self.canvas_defensa_riprap = SeccionTransversalCanvas(pagina)
        v.addWidget(self.canvas_defensa_riprap)
        tabla_resultado = crear_tabla_parametros()
        v.addWidget(tabla_resultado)

        def calcular():
            try:
                r_bl = hydraulic_structures.verificar_borde_libre(
                    spin_cota_agua.value(), spin_cota_corona.value(), spin_bl_min.value()
                )
                r_rip = hydraulic_structures.enrocado_isbash(spin_v.value(), spin_peso.value(), roca_expuesta=True)
                estado = "✔ CUMPLE" if r_bl["cumple"] else "✘ NO CUMPLE"
                lbl_estado.setText(f"Estado: {estado}")
                poblar_tabla_parametros(tabla_resultado, [
                    ("Borde libre disponible", r_bl["borde_libre_disponible_m"], "m", r_bl["nota"]),
                    ("¿Cumple?", "Sí" if r_bl["cumple"] else "No", ""),
                    ("D50 del enrocado de protección", r_rip["D50_m"], "m"),
                    ("D50 del enrocado de protección", r_rip["D50_cm"], "cm", r_rip["nota"]),
                ])
                self.canvas_defensa_bl.plot_borde_libre(spin_cota_agua.value(), spin_cota_corona.value(),
                                                         spin_bl_min.value(), "Defensa Ribereña (corona)", r_bl["cumple"])
                self.canvas_defensa_riprap.plot_riprap_talud(spin_v.value(), r_rip["D50_m"])
                self.resultados_hidraulica_drenaje["Defensa Ribereña"] = {
                    "tipo": "Defensa Ribereña", "cota_agua_m": spin_cota_agua.value(),
                    "cota_corona_m": spin_cota_corona.value(),
                    "borde_libre_disponible_m": r_bl["borde_libre_disponible_m"], "cumple": r_bl["cumple"],
                    "D50_m": r_rip["D50_m"], "D50_cm": r_rip["D50_cm"],
                }
                self._actualizar_texto_resumen_hidraulica()
            except Exception as e:
                lbl_estado.setText(f"Estado: ERROR -- {e}")

        btn.clicked.connect(calcular)
        return pagina

    # ------------------------------------------------------------------
    # TAB 8: Módulos Avanzados (completación de datos, precipitación
    # areal, oferta hídrica)
    # ------------------------------------------------------------------
    # ==================================================================
    # PESTAÑA 8 — HANDLERS
    # ==================================================================
    def _ruta_dem_2d(self):
        """Ráster de terreno a usar: el MDE recortado de la Pestaña 1 si
        la casilla está marcada, o la capa elegida en el desplegable."""
        if self.check_usar_dem_cuenca.isChecked() and self.dem_clip_path:
            return self.dem_clip_path, "MDE recortado a la cuenca (Pestaña 1)"
        capa = self.combo_dem_2d.currentLayer()
        if capa is None:
            return None, None
        return capa.source(), capa.name()

    def _on_cargar_dominio_2d(self):
        ruta, origen = self._ruta_dem_2d()
        if not ruta:
            QMessageBox.warning(
                self, "Falta el terreno",
                "Seleccione un ráster de terreno, o delimite la cuenca en la Pestaña 1 para usar "
                "su MDE recortado.")
            return
        try:
            from osgeo import gdal
            ds = gdal.Open(ruta)
            if ds is None:
                raise RuntimeError(f"No se pudo abrir el ráster: {ruta}")
            gt = ds.GetGeoTransform()
            banda = ds.GetRasterBand(1)
            nodata = banda.GetNoDataValue()
            arr = banda.ReadAsArray().astype(np.float64)
            wkt = ds.GetProjection()
            ds = None

            # NoData -> NaN: el solver lo interpreta como fuera del
            # dominio (muro impermeable), que es exactamente lo que es el
            # exterior de la cuenca.
            if nodata is not None:
                arr = np.where(arr == nodata, np.nan, arr)
            arr = np.where(arr < -9000.0, np.nan, arr)

            paso = self.spin_remuestreo_2d.value()
            if paso > 1:
                arr = arr[::paso, ::paso]
            dx = abs(gt[1]) * paso
            dy = abs(gt[5]) * paso
            x_min = gt[0]
            y_max = gt[3]

            if arr.shape[0] < 3 or arr.shape[1] < 3:
                QMessageBox.warning(
                    self, "Dominio demasiado pequeño",
                    f"Tras remuestrear con factor {paso} el dominio queda en "
                    f"{arr.shape[0]}x{arr.shape[1]} celdas. Reduzca el factor de remuestreo.")
                return

            self.dominio_2d = {
                "zb": arr, "dx": dx, "dy": dy, "x_min": x_min, "y_max": y_max,
                "wkt": wkt, "origen": origen, "paso": paso,
            }
            self.spin_fila_perfil_2d.setMaximum(arr.shape[0] - 1)
            self.spin_fila_perfil_2d.setValue(arr.shape[0] // 2)

            validas = int(np.sum(np.isfinite(arr)))
            z_validas = arr[np.isfinite(arr)]
            # El caudal de entrada entra en la estimación porque suele
            # ser el que fija el paso de tiempo (ver _paso_por_fuentes).
            caudal_max = 0.0
            for fila_tabla in range(self.tabla_entradas_2d.rowCount()):
                item = self.tabla_entradas_2d.item(fila_tabla, 2)
                if item and item.text().strip():
                    try:
                        caudal_max = max(caudal_max,
                                          float(item.text().replace(",", ".")))
                    except ValueError:
                        pass
            if caudal_max <= 0 and self.hidrograma_resultado:
                caudal_max = float(self.hidrograma_resultado.get("caudal_pico_m3s") or 0.0)

            coste = estimar_coste(
                arr.shape[0], arr.shape[1], self.spin_tiempo_2d.value(), dx, dy,
                esquema=self.combo_esquema_2d.currentData(),
                cfl=self.spin_cfl_2d.value(), n_manning=self.spin_manning_2d.value(),
                caudal_entrada_max=caudal_max)

            poblar_tabla_parametros(self.tabla_dominio_2d, [
                ("Origen del terreno", origen, ""),
                ("Filas × columnas de la malla", f"{arr.shape[0]} × {arr.shape[1]}", "celdas",
                 f"factor de remuestreo aplicado: {paso}"),
                ("Tamaño de celda", f"{dx:.2f} × {dy:.2f}", "m"),
                ("Celdas dentro del dominio", validas, "",
                 f"{validas / arr.size * 100:.1f} % del rectángulo; el resto es NoData"),
                ("Extensión del dominio", f"{arr.shape[1] * dx:.0f} × {arr.shape[0] * dy:.0f}", "m"),
                ("Cota mínima", round(float(z_validas.min()), 2), "m s.n.m."),
                ("Cota máxima", round(float(z_validas.max()), 2), "m s.n.m."),
                ("Paso de tiempo estimado", round(coste["dt_estimado_s"], 4), "s",
                 "para un calado típico de 1 m; el real se recalcula en cada paso"),
                ("Pasos de tiempo estimados", f"{coste['pasos_estimados']:,}", ""),
                ("Tiempo de cálculo estimado", round(coste["minutos_estimados"], 1), "min",
                 "orden de magnitud, no una promesa: depende del equipo"),
            ], filas_visibles_max=12)

            # El color advierte del coste ANTES de lanzar: una simulación
            # de horas conviene detectarla ahora y no a los veinte
            # minutos de espera.
            minutos = coste["minutos_estimados"]
            tipo = "exito" if minutos < 3 else ("atencion" if minutos < 20 else "alerta")
            self.cuadro_dominio_2d.actualizar(
                titulo="DOMINIO DE CÁLCULO 2D",
                valor_principal=f"{arr.shape[0]} × {arr.shape[1]} celdas de {dx:.1f} m",
                subtitulo=origen,
                metricas=[("Celdas activas", f"{validas:,}"),
                           ("Δt estimado", f"{coste['dt_estimado_s']:.3f} s"),
                           ("Pasos", f"{coste['pasos_estimados']:,}"),
                           ("Cálculo estimado", f"{minutos:.1f} min")],
                leyenda=("Coste razonable: puede ejecutar directamente." if tipo == "exito" else
                          ("Coste apreciable: considere subir el factor de remuestreo para tantear "
                           "y afinar después." if tipo == "atencion" else
                           "COSTE MUY ALTO. Suba el factor de remuestreo o reduzca el tiempo "
                           "simulado antes de ejecutar; recuerde que al duplicar la resolución el "
                           "coste se multiplica por ocho.")),
                tipo=tipo)
        except Exception as e:
            QMessageBox.critical(self, "Error al cargar el dominio", str(e))

    def _on_entrada_automatica_2d(self):
        """
        Sitúa la entrada en la celda de mayor cota del dominio activo,
        que en un MDE recortado a la cuenca es la cabecera. Es un punto
        de partida razonable para tantear, no un sustituto de situar la
        entrada donde el proyecto la requiere.
        """
        if not getattr(self, "dominio_2d", None):
            QMessageBox.warning(self, "Falta el dominio",
                                 "Cargue primero el dominio de cálculo.")
            return
        zb = self.dominio_2d["zb"]
        validas = np.isfinite(zb)
        # Se excluye el borde: una entrada en el contorno se vaciaría de
        # inmediato por la condición de salida libre.
        interior = np.zeros_like(validas)
        interior[1:-1, 1:-1] = True
        candidatas = validas & interior
        if not candidatas.any():
            QMessageBox.warning(self, "Dominio sin interior",
                                 "El dominio no tiene celdas interiores válidas.")
            return
        z = np.where(candidatas, zb, -np.inf)
        fila, columna = np.unravel_index(int(np.argmax(z)), z.shape)
        self.tabla_entradas_2d.setItem(0, 0, QTableWidgetItem(str(int(fila))))
        self.tabla_entradas_2d.setItem(0, 1, QTableWidgetItem(str(int(columna))))
        self.tabla_entradas_2d.setItem(0, 2, QTableWidgetItem("0"))
        QMessageBox.information(
            self, "Entrada situada",
            f"Entrada colocada en la fila {fila}, columna {columna} "
            f"(cota {zb[fila, columna]:.2f} m s.n.m.), la celda más alta del interior del "
            "dominio.\n\nCon caudal 0 y la casilla marcada, se usará el hidrograma de la "
            "Pestaña 6.")

    def _leer_entradas_2d(self):
        """Lee la tabla de entradas y adjunta el hidrograma de la Pestaña
        6 a las que tengan caudal 0."""
        hidrograma = None
        if self.check_hidrograma_p6.isChecked() and self.hidrograma_resultado:
            tiempos = self.hidrograma_resultado.get("tiempos_h") or []
            caudales = self.hidrograma_resultado.get("caudal_m3s") or []
            if tiempos and caudales:
                n = min(len(tiempos), len(caudales))
                hidrograma = [(tiempos[i] * 3600.0, caudales[i]) for i in range(n)]

        entradas = []
        for fila in range(self.tabla_entradas_2d.rowCount()):
            celdas = []
            for col in range(3):
                item = self.tabla_entradas_2d.item(fila, col)
                celdas.append(item.text().strip() if item else "")
            if not celdas[0] or not celdas[1]:
                continue
            try:
                f = int(float(celdas[0]))
                c = int(float(celdas[1]))
                q = float(celdas[2].replace(",", ".")) if celdas[2] else 0.0
            except ValueError:
                raise Swe2DEntradaInvalida(
                    f"La fila {fila + 1} de la tabla de entradas tiene valores no numéricos.")
            if q > 0:
                entradas.append({"fila": f, "columna": c, "caudal_m3s": q})
            elif hidrograma:
                entradas.append({"fila": f, "columna": c, "hidrograma": hidrograma})
            else:
                raise Swe2DEntradaInvalida(
                    f"La entrada de la fila {fila + 1} tiene caudal 0 y no hay hidrograma "
                    "disponible de la Pestaña 6. Indique un caudal o calcule antes el "
                    "hidrograma de diseño.")
        return entradas

    def _leer_estructuras_2d(self):
        """Construye los objetos Estructura desde la tabla."""
        estructuras = []
        for fila in range(self.tabla_estructuras_2d.rowCount()):
            valores = []
            for col in range(8):
                item = self.tabla_estructuras_2d.item(fila, col)
                valores.append(item.text().strip() if item else "")
            if not valores[1]:
                continue
            tipo = valores[1].lower()
            try:
                f1, c1 = int(float(valores[2])), int(float(valores[3]))
                f2, c2 = int(float(valores[4])), int(float(valores[5]))
                p1 = float(valores[6].replace(",", "."))
                extras = [float(x.replace(",", ".")) for x in valores[7].split(";") if x.strip()]
            except (ValueError, IndexError):
                raise Swe2DEntradaInvalida(
                    f"La estructura de la fila {fila + 1} tiene parámetros no numéricos o "
                    "incompletos.")

            nombre = valores[0] or f"{tipo} {fila + 1}"
            if tipo == "vertedero":
                if not extras:
                    raise Swe2DEntradaInvalida(
                        f"El vertedero «{nombre}» necesita la longitud de cresta en "
                        "«Parámetro 2 / 3».")
                parametros = {"cota_cresta": p1, "longitud": extras[0],
                              "coef_descarga": extras[1] if len(extras) > 1 else 1.84}
            elif tipo == "orificio":
                parametros = {"area": p1,
                              "coef_descarga": extras[0] if extras else 0.61}
            elif tipo == "alcantarilla":
                if not extras:
                    raise Swe2DEntradaInvalida(
                        f"La alcantarilla «{nombre}» necesita el diámetro en «Parámetro 2 / 3».")
                diametro = extras[0]
                parametros = {"cota_entrada": p1, "diametro": diametro,
                              "area": math.pi * diametro ** 2 / 4.0,
                              "longitud": extras[1] if len(extras) > 1 else 10.0}
            else:
                raise Swe2DEntradaInvalida(
                    f"Tipo de estructura no reconocido en la fila {fila + 1}: «{valores[1]}». "
                    "Use «vertedero», «orificio» o «alcantarilla».")

            estructuras.append(swe2d.Estructura(tipo, (f1, c1), (f2, c2), parametros, nombre))
        return estructuras

    # ------------------------------------------------------------------
    # Insertar estructura 2D desde el mapa (item 8, fase 1): 2 clics ->
    # fila/columna de la malla, fila en tabla_estructuras_2d, y feature en
    # una capa de líneas exportable. Mismo patrón de QgsMapToolEmitPoint
    # que _on_canvas_clicked (Pestaña 1) y las secciones de socavación.
    # ------------------------------------------------------------------
    def _fila_columna_desde_punto_2d(self, punto: QgsPointXY):
        dom = self.dominio_2d
        columna = int((punto.x() - dom["x_min"]) / dom["dx"])
        fila = int((dom["y_max"] - punto.y()) / dom["dy"])
        return fila, columna

    def _valor_atributo_o_none(self, feature, nombre_campo):
        """feature[nombre_campo] normalizado: None tanto si el atributo es
        el None de Python como si es un QVariant NULL (lo que devuelve un
        campo vacío de un feature dibujado a mano con las herramientas de
        QGIS) -- sin esto, `valor or default` no dispara el default porque
        un QVariant NULL no es "is None" en Python."""
        valor = feature[nombre_campo]
        if valor is None:
            return None
        if isinstance(valor, QVariant) and valor.isNull():
            return None
        return valor

    def _activar_map_tool_estructura_2d(self, checked):
        canvas = self.iface.mapCanvas()
        if checked:
            if not getattr(self, "dominio_2d", None):
                QMessageBox.warning(
                    self, "Falta el dominio",
                    "Cargue primero el dominio de cálculo (sección 1) -- se necesita su "
                    "geotransformación para convertir el clic del mapa a fila/columna de la malla.")
                self.btn_marcar_estructura_2d.setChecked(False)
                return
            self._primer_clic_estructura_2d = None
            self.map_tool_estructura_2d = QgsMapToolEmitPoint(canvas)
            self.map_tool_estructura_2d.canvasClicked.connect(self._on_canvas_clicked_estructura_2d)
            canvas.mapToolSet.connect(self._on_map_tool_changed_estructura_2d)
            canvas.setMapTool(self.map_tool_estructura_2d)
            self.btn_marcar_estructura_2d.setText("Clic en el INICIO de la estructura...")
            self.hide()
        else:
            if self.map_tool_estructura_2d is not None:
                try:
                    canvas.mapToolSet.disconnect(self._on_map_tool_changed_estructura_2d)
                except TypeError:
                    pass
                canvas.unsetMapTool(self.map_tool_estructura_2d)
            self.btn_marcar_estructura_2d.setText(
                "📍 Marcar los 2 puntos de la estructura en el mapa (clic inicio → clic fin)")
            self._restaurar_ventana()

    def _on_map_tool_changed_estructura_2d(self, herramienta_nueva, herramienta_anterior):
        if herramienta_nueva is not self.map_tool_estructura_2d:
            self.btn_marcar_estructura_2d.setChecked(False)
            self.btn_marcar_estructura_2d.setText(
                "📍 Marcar los 2 puntos de la estructura en el mapa (clic inicio → clic fin)")
            self._restaurar_ventana()

    def _on_canvas_clicked_estructura_2d(self, punto, button):
        if self._primer_clic_estructura_2d is None:
            self._primer_clic_estructura_2d = QgsPointXY(punto)
            self.btn_marcar_estructura_2d.setText("Clic en el FIN de la estructura...")
            return
        punto_inicio = self._primer_clic_estructura_2d
        punto_fin = QgsPointXY(punto)
        self._primer_clic_estructura_2d = None

        canvas = self.iface.mapCanvas()
        if self.map_tool_estructura_2d is not None:
            try:
                canvas.mapToolSet.disconnect(self._on_map_tool_changed_estructura_2d)
            except TypeError:
                pass
            canvas.unsetMapTool(self.map_tool_estructura_2d)
        self.btn_marcar_estructura_2d.setChecked(False)
        self.btn_marcar_estructura_2d.setText(
            "📍 Marcar los 2 puntos de la estructura en el mapa (clic inicio → clic fin)")
        self._restaurar_ventana()

        fila1, col1 = self._fila_columna_desde_punto_2d(punto_inicio)
        fila2, col2 = self._fila_columna_desde_punto_2d(punto_fin)
        nombre = self.edit_insertar_nombre_2d.text().strip() or \
            f"Estructura {self.tabla_estructuras_2d.rowCount() + 1}"
        tipo = self.combo_insertar_tipo_2d.currentText()
        param1 = self.spin_insertar_param1_2d.value()
        param2_3 = self.edit_insertar_param23_2d.text().strip()

        self._agregar_fila_estructura_2d(nombre, tipo, fila1, col1, fila2, col2, param1, param2_3)
        self._agregar_feature_capa_estructuras_2d(
            nombre, tipo, fila1, col1, fila2, col2, param1, param2_3, punto_inicio, punto_fin)
        self.edit_insertar_nombre_2d.clear()
        self.lbl_estado_estructuras_2d.setText(
            f"Estado: «{nombre}» ({tipo}) insertada -- fila={fila1},col={col1} → fila={fila2},col={col2}.")

    def _primera_fila_vacia_o_nueva(self, tabla, columna_clave: int = 1):
        """Devuelve el índice de la primera fila SIN datos en `columna_clave`
        (para reaprovechar filas en blanco de una TablaPegable creada con
        varias filas vacías por defecto), o agrega una fila nueva al final
        si no encuentra ninguna."""
        for fila in range(tabla.rowCount()):
            item = tabla.item(fila, columna_clave)
            if not item or not item.text().strip():
                return fila
        fila_nueva = tabla.rowCount()
        tabla.setRowCount(fila_nueva + 1)
        return fila_nueva

    def _agregar_fila_estructura_2d(self, nombre, tipo, fila1, col1, fila2, col2, param1, param2_3):
        fila = self._primera_fila_vacia_o_nueva(self.tabla_estructuras_2d, columna_clave=1)
        valores = [nombre, tipo, str(fila1), str(col1), str(fila2), str(col2),
                   f"{param1:g}", param2_3]
        for col, valor in enumerate(valores):
            self.tabla_estructuras_2d.setItem(fila, col, QTableWidgetItem(valor))
        ajustar_alto_tabla(self.tabla_estructuras_2d, filas_visibles_max=8)

    def _capa_sigue_en_proyecto(self, capa) -> bool:
        if capa is None:
            return False
        try:
            return QgsProject.instance().mapLayer(capa.id()) is not None
        except RuntimeError:
            return False  # el objeto C++ subyacente ya fue eliminado (capa quitada del panel)

    def _obtener_capa_estructuras_2d(self):
        """Capa de líneas (memoria) que acumula TODAS las estructuras
        insertadas desde el mapa o importadas desde otra capa en esta
        sesión -- se crea la primera vez que hace falta y se reutiliza
        mientras siga en el proyecto (si el usuario la borra del panel de
        capas, se vuelve a crear vacía en el próximo insert)."""
        if not self._capa_sigue_en_proyecto(self.capa_estructuras_2d):
            crs = QgsProject.instance().crs()
            capa = QgsVectorLayer(f"LineString?crs={crs.authid()}",
                                   "Estructuras 2D (HydroAndina Pro)", "memory")
            proveedor = capa.dataProvider()
            proveedor.addAttributes([
                QgsField("nombre", QVariant.String),
                QgsField("tipo", QVariant.String),
                QgsField("fila1", QVariant.Int), QgsField("col1", QVariant.Int),
                QgsField("fila2", QVariant.Int), QgsField("col2", QVariant.Int),
                QgsField("parametro1", QVariant.Double),
                QgsField("param2_3", QVariant.String),
            ])
            capa.updateFields()
            QgsProject.instance().addMapLayer(capa)
            self.capa_estructuras_2d = capa
        return self.capa_estructuras_2d

    def _agregar_feature_capa_estructuras_2d(self, nombre, tipo, fila1, col1, fila2, col2,
                                              param1, param2_3, punto_inicio, punto_fin):
        capa = self._obtener_capa_estructuras_2d()
        feat = QgsFeature(capa.fields())
        feat.setGeometry(QgsGeometry.fromPolylineXY([punto_inicio, punto_fin]))
        feat.setAttributes([nombre, tipo, int(fila1), int(col1), int(fila2), int(col2),
                             float(param1), param2_3])
        capa.dataProvider().addFeature(feat)
        capa.updateExtents()
        capa.triggerRepaint()

    def _on_importar_estructuras_desde_lineas(self):
        """Lee cada feature de línea de la capa elegida, convierte su
        primer y último vértice a fila/columna con la geotransformación
        del dominio, y agrega una fila por feature -- para no tener que
        marcar de a una cuando ya existe una capa digitalizada (p.ej. el
        eje de varias alcantarillas de un mismo proyecto)."""
        if not getattr(self, "dominio_2d", None):
            QMessageBox.warning(self, "Falta el dominio",
                                 "Cargue primero el dominio de cálculo (sección 1).")
            return
        capa_origen = self.combo_capa_lineas_estructuras_2d.currentLayer()
        if capa_origen is None:
            QMessageBox.warning(self, "Falta la capa", "Elija una capa de líneas para importar.")
            return
        tipo = self.combo_insertar_tipo_2d.currentText()
        param1 = self.spin_insertar_param1_2d.value()
        param2_3 = self.edit_insertar_param23_2d.text().strip()
        importadas = 0
        for feature in capa_origen.getFeatures():
            geom = feature.geometry()
            if geom is None or geom.isEmpty():
                continue
            vertices = [v for v in geom.vertices()]
            if len(vertices) < 2:
                continue
            punto_inicio = QgsPointXY(vertices[0])
            punto_fin = QgsPointXY(vertices[-1])
            fila1, col1 = self._fila_columna_desde_punto_2d(punto_inicio)
            fila2, col2 = self._fila_columna_desde_punto_2d(punto_fin)
            campos_texto = [f.name().lower() for f in feature.fields()]
            nombre = None
            for candidato in ("nombre", "name", "id"):
                if candidato in campos_texto:
                    valor = feature[feature.fields()[campos_texto.index(candidato)].name()]
                    if valor:
                        nombre = str(valor)
                        break
            nombre = nombre or f"Estructura {self.tabla_estructuras_2d.rowCount() + 1}"
            self._agregar_fila_estructura_2d(nombre, tipo, fila1, col1, fila2, col2, param1, param2_3)
            self._agregar_feature_capa_estructuras_2d(
                nombre, tipo, fila1, col1, fila2, col2, param1, param2_3, punto_inicio, punto_fin)
            importadas += 1
        if importadas == 0:
            QMessageBox.warning(self, "Nada que importar",
                                 "La capa elegida no tiene features de línea con al menos 2 vértices.")
            return
        self.lbl_estado_estructuras_2d.setText(
            f"Estado: {importadas} estructura(s) importada(s) desde «{capa_origen.name()}» "
            f"(tipo «{tipo}» y parámetros del formulario aplicados a todas -- edítelas en la tabla "
            "si alguna necesita valores distintos).")

    def _on_exportar_capa_estructuras_2d(self):
        if not self._capa_sigue_en_proyecto(self.capa_estructuras_2d) or \
                self.capa_estructuras_2d.featureCount() == 0:
            QMessageBox.warning(self, "Sin estructuras insertadas",
                                 "Inserte al menos una estructura desde el mapa (o impórtelas desde "
                                 "una capa de líneas) antes de exportar.")
            return
        ruta_base, _ = QFileDialog.getSaveFileName(
            self, "Exportar capa de estructuras 2D", "estructuras_2d", "ESRI Shapefile (*.shp)")
        if not ruta_base:
            return
        ruta_base = ruta_base[:-4] if ruta_base.lower().endswith(".shp") else ruta_base
        try:
            salidas = exporters.exportar_vector(self.capa_estructuras_2d, ruta_base)
            QMessageBox.information(
                self, "Capa exportada",
                "Estructuras exportadas a:\n" + "\n".join(salidas.values()))
        except Exception as e:
            QMessageBox.critical(self, "Error exportando la capa", str(e))

    # -- Dibujar estructuras con el mouse (item 8, fase 2): en vez de
    # reimplementar un rubber-band de digitalización propio, se reutilizan
    # las herramientas nativas de QGIS (edición + "Añadir entidad de
    # línea") sobre la MISMA capa que ya acumula lo insertado por clic o
    # importado de otra capa (self.capa_estructuras_2d) -- así hay una
    # sola fuente de verdad, y "Sincronizar" recalcula fila/columna desde
    # la geometría dibujada y reconstruye la tabla de simulación entera.
    def _on_habilitar_dibujo_estructuras_2d(self):
        if not getattr(self, "dominio_2d", None):
            QMessageBox.warning(
                self, "Falta el dominio",
                "Cargue primero el dominio de cálculo (sección 1) -- se necesita su "
                "geotransformación para poder sincronizar fila/columna después de dibujar.")
            return
        capa = self._obtener_capa_estructuras_2d()
        if not capa.isEditable():
            capa.startEditing()
        try:
            self.iface.setActiveLayer(capa)
        except Exception:
            pass
        QMessageBox.information(
            self, "Capa lista para dibujar",
            "La capa «Estructuras 2D (HydroAndina Pro)» quedó activa y en modo edición.\n\n"
            "Use la herramienta «Añadir entidad de línea» de la barra de digitalización de QGIS "
            "para dibujar cada estructura (varios clics para seguir un trazado curvo; doble clic "
            "o Enter para terminarla). En el formulario que aparece al terminar cada línea, "
            "complete nombre/tipo/parametro1/param2_3 -- deje fila1/col1/fila2/col2 en 0, se "
            "calculan solos al pulsar «Sincronizar» cuando termine de dibujar."
        )

    def _on_sincronizar_estructuras_2d_desde_capa(self):
        if not getattr(self, "dominio_2d", None):
            QMessageBox.warning(self, "Falta el dominio",
                                 "Cargue primero el dominio de cálculo (sección 1).")
            return
        if not self._capa_sigue_en_proyecto(self.capa_estructuras_2d):
            QMessageBox.warning(self, "Sin capa de estructuras",
                                 "Todavía no hay ninguna estructura dibujada ni insertada.")
            return

        capa = self.capa_estructuras_2d
        editando_ya = capa.isEditable()
        if not editando_ya:
            capa.startEditing()

        idx_fila1 = capa.fields().indexOf("fila1")
        idx_col1 = capa.fields().indexOf("col1")
        idx_fila2 = capa.fields().indexOf("fila2")
        idx_col2 = capa.fields().indexOf("col2")

        filas_tabla = []
        for feature in capa.getFeatures():
            geom = feature.geometry()
            if geom is None or geom.isEmpty():
                continue
            vertices = [v for v in geom.vertices()]
            if len(vertices) < 2:
                continue
            punto_inicio = QgsPointXY(vertices[0])
            punto_fin = QgsPointXY(vertices[-1])
            fila1, col1 = self._fila_columna_desde_punto_2d(punto_inicio)
            fila2, col2 = self._fila_columna_desde_punto_2d(punto_fin)
            capa.changeAttributeValue(feature.id(), idx_fila1, fila1)
            capa.changeAttributeValue(feature.id(), idx_col1, col1)
            capa.changeAttributeValue(feature.id(), idx_fila2, fila2)
            capa.changeAttributeValue(feature.id(), idx_col2, col2)

            nombre = self._valor_atributo_o_none(feature, "nombre") or f"Estructura {len(filas_tabla) + 1}"
            tipo = self._valor_atributo_o_none(feature, "tipo") or self.combo_insertar_tipo_2d.currentText()
            param1_valor = self._valor_atributo_o_none(feature, "parametro1")
            param1 = float(param1_valor) if param1_valor is not None else 0.0
            param2_3 = self._valor_atributo_o_none(feature, "param2_3") or ""
            filas_tabla.append((nombre, tipo, fila1, col1, fila2, col2, param1, param2_3))

        if not editando_ya:
            capa.commitChanges()

        if not filas_tabla:
            QMessageBox.warning(self, "Nada que sincronizar",
                                 "La capa de estructuras no tiene ninguna geometría con al menos "
                                 "2 vértices.")
            return

        # La tabla de simulación se reconstruye ENTERA desde la capa, para
        # que sea la única fuente de verdad y no queden filas de
        # estructuras que ya se borraron de la capa.
        n_filas_tabla = max(len(filas_tabla), 4)
        self.tabla_estructuras_2d.setRowCount(n_filas_tabla)
        for fila_idx, (nombre, tipo, fila1, col1, fila2, col2, param1, param2_3) in enumerate(filas_tabla):
            valores = [nombre, tipo, str(fila1), str(col1), str(fila2), str(col2),
                       f"{param1:g}", param2_3]
            for col, valor in enumerate(valores):
                self.tabla_estructuras_2d.setItem(fila_idx, col, QTableWidgetItem(str(valor)))
        for fila_idx in range(len(filas_tabla), n_filas_tabla):
            for col in range(8):
                self.tabla_estructuras_2d.setItem(fila_idx, col, None)
        ajustar_alto_tabla(self.tabla_estructuras_2d, filas_visibles_max=8)

        self.lbl_estado_estructuras_2d.setText(
            f"Estado: {len(filas_tabla)} estructura(s) sincronizada(s) desde la capa -- la tabla "
            "de simulación se reconstruyó completa a partir de la capa.")

    def _on_guardar_edicion_estructuras_2d(self):
        if not self._capa_sigue_en_proyecto(self.capa_estructuras_2d):
            QMessageBox.warning(self, "Sin capa de estructuras", "Todavía no hay ninguna capa de estructuras.")
            return
        capa = self.capa_estructuras_2d
        if not capa.isEditable():
            QMessageBox.information(self, "Nada que guardar", "La capa no está en modo edición.")
            return
        if capa.commitChanges():
            QMessageBox.information(self, "Cambios guardados",
                                     "Se guardaron los cambios de la capa de estructuras.")
        else:
            QMessageBox.warning(self, "No se pudo guardar",
                                 "Revise los errores de edición de la capa (panel de mensajes de QGIS).")

    def _on_ejecutar_simulacion_2d(self):
        if not getattr(self, "dominio_2d", None):
            QMessageBox.warning(self, "Falta el dominio",
                                 "Cargue primero el dominio de cálculo (sección 1).")
            return
        try:
            entradas = self._leer_entradas_2d()
            estructuras = self._leer_estructuras_2d()
        except Swe2DEntradaInvalida as e:
            QMessageBox.warning(self, "Datos de entrada incompletos", str(e))
            return

        if not entradas and self.spin_lluvia_2d.value() <= 0:
            QMessageBox.warning(
                self, "Sin forzamiento",
                "No hay ninguna entrada de caudal ni lluvia sobre malla: la simulación no "
                "tendría agua que mover. Añada una entrada o una intensidad de lluvia.")
            return

        dominio = self.dominio_2d
        configuracion = {
            "zb": dominio["zb"], "dx": dominio["dx"], "dy": dominio["dy"],
            "n_manning": self.spin_manning_2d.value(),
            "esquema": self.combo_esquema_2d.currentData(),
            "cfl": self.spin_cfl_2d.value(),
            "dt_maximo": self.spin_dt_max_2d.value(),
            "tiempo_total_s": self.spin_tiempo_2d.value(),
            "entradas": entradas,
            "estructuras": estructuras,
            "lluvia_mm_h": self.spin_lluvia_2d.value(),
            "salida_por_bordes": self.check_salida_bordes_2d.isChecked(),
            "intervalo_captura_s": self.spin_captura_2d.value(),
        }

        self.btn_simular_2d.setEnabled(False)
        self.btn_cancelar_2d.setEnabled(True)
        self.barra_progreso_2d.setValue(0)
        self.lbl_estado_2d.setText("Estado: iniciando…")

        self.worker_2d = SimulacionSwe2DWorker(configuracion)
        self.worker_2d.progreso.connect(self._on_progreso_simulacion_2d)
        self.worker_2d.terminado.connect(self._on_terminada_simulacion_2d)
        self.worker_2d.fallo.connect(self._on_fallo_simulacion_2d)
        self.worker_2d.mensaje.connect(
            lambda t: self.lbl_estado_2d.setText(f"Estado: {t}"))
        self.worker_2d.start()

    def _on_cancelar_simulacion_2d(self):
        if getattr(self, "worker_2d", None):
            self.worker_2d.cancelar()
            self.lbl_estado_2d.setText("Estado: cancelando…")

    def _on_progreso_simulacion_2d(self, porcentaje, tiempo_s, calado_max, area_ha):
        self.barra_progreso_2d.setValue(porcentaje)
        self.lbl_estado_2d.setText(
            f"Estado: t = {tiempo_s:,.0f} s ({porcentaje} %)  ·  calado máx. "
            f"{calado_max:.3f} m  ·  área inundada {area_ha:.2f} ha")

    def _on_fallo_simulacion_2d(self, mensaje):
        self.btn_simular_2d.setEnabled(True)
        self.btn_cancelar_2d.setEnabled(False)
        self.lbl_estado_2d.setText("Estado: la simulación falló.")
        QMessageBox.critical(self, "Error en la simulación 2D", mensaje)

    def _on_terminada_simulacion_2d(self, simulador, resumen):
        """
        Vuelca los resultados a la interfaz.

        TODO EL CUERPO VA PROTEGIDO a propósito. Este método se ejecuta
        como respuesta a una señal emitida desde el hilo de simulación, y
        una excepción que escape de aquí no produce un traceback de
        Python: atraviesa el código C++ de Qt que está emitiendo la señal
        y ABORTA EL PROCESO. En la práctica eso significa que QGIS se
        cierra de golpe, sin mensaje y sin guardar el proyecto.
        Ya ocurrió una vez durante el desarrollo (un nombre de atributo
        pisado por otra pestaña), y el síntoma fue exactamente ese: QGIS
        desaparecía sin dejar rastro de la causa.
        """
        try:
            self._volcar_resultados_2d(simulador, resumen)
        except Exception as e:                     # noqa: BLE001
            import traceback
            self.btn_simular_2d.setEnabled(True)
            self.btn_cancelar_2d.setEnabled(False)
            self.lbl_estado_2d.setText(
                "Estado: la simulación terminó, pero falló al mostrar los resultados.")
            QMessageBox.critical(
                self, "Error al mostrar los resultados 2D",
                f"La simulación se completó, pero ocurrió un error al volcar los resultados "
                f"a la interfaz:\n\n{e}\n\n{traceback.format_exc()}")

    def _volcar_resultados_2d(self, simulador, resumen):
        self.btn_simular_2d.setEnabled(True)
        self.btn_cancelar_2d.setEnabled(False)
        self.simulador_2d = simulador
        self.resumen_2d = resumen
        self.lbl_estado_2d.setText(
            f"Estado: terminada. {resumen['pasos']:,} pasos en "
            f"{resumen['tiempo_simulado_s']:,.0f} s simulados.")

        balance = resumen["balance"]
        peligro = simulador.peligrosidad()
        clasificacion = mesh_export.clasificar_peligrosidad(peligro)
        self.clasificacion_peligro_2d = clasificacion

        filas = [
            ("Esquema numérico", resumen["esquema"].replace("_", " "), ""),
            ("Tiempo simulado", round(resumen["tiempo_simulado_s"], 1), "s"),
            ("Pasos de tiempo", f"{resumen['pasos']:,}", "",
             f"Δt medio = {resumen['tiempo_simulado_s'] / max(resumen['pasos'], 1):.4f} s"),
            ("Calado máximo", round(resumen["calado_maximo_m"], 3), "m"),
            ("Calado medio en zona inundada", round(resumen["calado_medio_inundado_m"], 3), "m"),
            ("Velocidad máxima", round(resumen["velocidad_maxima_ms"], 3), "m/s"),
            ("Peligrosidad máxima h·v", round(resumen["peligrosidad_maxima_m2s"], 3), "m²/s",
             "clases de la guía FD2320 (Defra/Environment Agency)"),
            ("Área inundada", round(resumen["area_inundada_ha"], 3), "ha"),
            ("Celdas del dominio", f"{resumen['celdas_dominio']:,}", ""),
        ]
        for clase in clasificacion["reparto"]:
            filas.append((f"Área en peligro {clase['clase']}",
                          round(clase["porcentaje"], 2), "%", clase["descripcion"]))
        filas.extend([
            ("Volumen entrado", round(balance["volumen_entrado_m3"], 2), "m³"),
            ("Volumen almacenado", round(balance["volumen_almacenado_m3"], 2), "m³"),
            ("Volumen salido", round(balance["volumen_salido_m3"], 2), "m³"),
            ("Error de balance de masa", round(balance["error_relativo_pct"], 6), "%",
             "ACEPTABLE (< 1 %)" if balance["aceptable"]
             else "NO ACEPTABLE: no use estos resultados"),
        ])
        if not resumen.get("estable", True):
            filas.append((
                "Pasos con Δt recortado", resumen["pasos_con_dt_recortado"], "",
                "el paso estable cayó por debajo del mínimo: baje el CFL o use inercia local"))
        poblar_tabla_parametros(self.tabla_resultado_2d, filas, filas_visibles_max=26)

        if simulador.estructuras:
            filas_est = []
            for est in simulador.estructuras:
                filas_est.append((
                    f"{est.nombre} ({est.tipo})", round(est.caudal_maximo, 4), "m³/s",
                    f"celdas {est.celda_1} ↔ {est.celda_2}; "
                    f"caudal final {est.caudal_actual:.4f} m³/s"))
            poblar_tabla_parametros(self.tabla_estructuras_resultado_2d, filas_est,
                                     filas_visibles_max=10)
        else:
            poblar_tabla_parametros(self.tabla_estructuras_resultado_2d, [
                ("Sin estructuras definidas", "—", "",
                 "añádalas en la sección 4 para obtener sus caudales")])

        # El estado del cuadro lo decide el BALANCE DE MASA, no lo
        # espectacular del calado: un resultado que no cierra masa no es
        # utilizable por muy verosímil que parezca el mapa.
        tipo = "exito" if balance["aceptable"] and resumen.get("estable", True) else "alerta"
        self.cuadro_resultado_2d.actualizar(
            titulo="SIMULACIÓN HIDRÁULICA 2D",
            valor_principal=f"h_máx = {resumen['calado_maximo_m']:.3f} m   ·   "
                            f"v_máx = {resumen['velocidad_maxima_ms']:.3f} m/s",
            subtitulo=f"{resumen['area_inundada_ha']:.2f} ha inundadas en "
                      f"{resumen['tiempo_simulado_s']:,.0f} s simulados "
                      f"({resumen['esquema'].replace('_', ' ')})",
            metricas=[("Área inundada", f"{resumen['area_inundada_ha']:.2f} ha"),
                       ("Peligro h·v máx", f"{resumen['peligrosidad_maxima_m2s']:.2f} m²/s"),
                       ("Pasos", f"{resumen['pasos']:,}"),
                       ("Error de masa", f"{balance['error_relativo_pct']:.4f} %")],
            leyenda=("El balance de masa cierra: los resultados son consistentes y pueden usarse "
                      "para dimensionar." if tipo == "exito" else
                      "EL BALANCE DE MASA NO CIERRA o el paso de tiempo tuvo que recortarse. "
                      "Baje el número de Courant, use el esquema de inercia local, o remuestree "
                      "el terreno más grueso. NO utilice estos resultados para diseño."),
            tipo=tipo)

        self.canvas_mapa_calado_swe2d.plot_mapa(
            simulador.h_max, simulador.zb, simulador.dx, simulador.dy,
            activo=simulador.activo, entradas=simulador.entradas,
            estructuras=simulador.estructuras)
        self.canvas_peligro_2d.plot_peligrosidad(
            peligro, clasificacion, simulador.zb, simulador.dx, simulador.dy,
            activo=simulador.activo)
        self.canvas_hidrogramas_2d.plot_series(simulador.serie_tiempo, balance=balance)
        self._on_actualizar_perfil_2d()

        self._actualizar_resumen_final_2d()

    def _on_actualizar_perfil_2d(self):
        simulador = getattr(self, "simulador_2d", None)
        if simulador is None:
            return
        fila = min(self.spin_fila_perfil_2d.value(), simulador.h_max.shape[0] - 1)
        zb_linea = np.where(simulador.activo[fila], simulador.zb[fila], np.nan)
        self.canvas_perfil_2d.plot_perfil(
            np.nan_to_num(zb_linea, nan=float(np.nanmin(zb_linea)) if np.any(np.isfinite(zb_linea))
                          else 0.0),
            simulador.h_max[fila], simulador.dx,
            titulo=f"Perfil por la fila {fila} — calado máximo alcanzado")

    def _actualizar_resumen_final_2d(self):
        resumen = getattr(self, "resumen_2d", None)
        if resumen is None:
            return
        balance = resumen["balance"]
        clasificacion = getattr(self, "clasificacion_peligro_2d", None)
        simulador = self.simulador_2d

        filas_peligro = ""
        if clasificacion:
            filas_peligro = "".join(
                f"<tr><td style='padding:2px 10px;'>"
                f"<span style='background:{c['color']};padding:0 8px;'>&nbsp;</span> "
                f"{c['clase']}</td>"
                f"<td style='padding:2px 10px;text-align:right;'><b>{c['porcentaje']:.1f} %</b></td>"
                f"<td style='padding:2px 10px;'>{c['descripcion']}</td></tr>"
                for c in clasificacion["reparto"])

        filas_estructuras = "".join(
            f"<li><b>{est.nombre}</b> ({est.tipo}): caudal máximo "
            f"{est.caudal_maximo:.3f} m³/s</li>"
            for est in simulador.estructuras) or "<li>No se definieron estructuras.</li>"

        color_balance = "#1B5E20" if balance["aceptable"] else "#7A1712"
        self.resumen_final_2d.setHtml(f"""
        <h3 style="margin:0 0 6px 0;color:#1a4a70;">SIMULACIÓN HIDRÁULICA 2D — RESUMEN FINAL</h3>
        <p style="margin:2px 0;"><b>Modelo:</b> aguas someras 2D en volúmenes finitos sobre malla
        desplazada, esquema de <b>{resumen['esquema'].replace('_', ' ')}</b>, sobre
        {resumen['celdas_dominio']:,} celdas de {simulador.dx:.1f} × {simulador.dy:.1f} m.
        {resumen['pasos']:,} pasos de tiempo para {resumen['tiempo_simulado_s']:,.0f} s simulados.</p>

        <p style="margin:8px 0 2px 0;"><b>Resultados hidráulicos</b></p>
        <ul style="margin:2px 0;">
          <li>Calado máximo: <b>{resumen['calado_maximo_m']:.3f} m</b>
              (medio en zona inundada: {resumen['calado_medio_inundado_m']:.3f} m)</li>
          <li>Velocidad máxima: <b>{resumen['velocidad_maxima_ms']:.3f} m/s</b></li>
          <li>Área inundada: <b>{resumen['area_inundada_ha']:.3f} ha</b></li>
          <li>Peligrosidad máxima h·v: <b>{resumen['peligrosidad_maxima_m2s']:.3f} m²/s</b></li>
        </ul>

        <p style="margin:8px 0 2px 0;"><b>Reparto del peligro (guía FD2320)</b></p>
        <table style="border-collapse:collapse;">{filas_peligro}</table>

        <p style="margin:8px 0 2px 0;"><b>Estructuras hidráulicas</b></p>
        <ul style="margin:2px 0;">{filas_estructuras}</ul>

        <p style="margin:8px 0 2px 0;"><b>Verificación del modelo</b></p>
        <p style="margin:2px 0;">Entró {balance['volumen_entrado_m3']:,.1f} m³, quedaron
        almacenados {balance['volumen_almacenado_m3']:,.1f} m³ y salieron
        {balance['volumen_salido_m3']:,.1f} m³. Error de cierre:
        <b style="color:{color_balance};">{balance['error_relativo_pct']:.6f} %</b>
        {'(aceptable)' if balance['aceptable'] else '(NO ACEPTABLE — no use estos resultados)'}.</p>
        <p style="margin:6px 0 0 0;font-size:8pt;color:#5a5a5a;"><i>El balance de masa es el
        control de calidad de una simulación 2D: mide si el modelo conserva el agua que se le
        entrega. Un mapa de inundación verosímil con un balance que no cierra es un mapa
        equivocado, y por eso se comprueba antes que ningún otro resultado.</i></p>
        """)

    def _on_exportar_resultados_2d(self):
        simulador = getattr(self, "simulador_2d", None)
        if simulador is None:
            QMessageBox.warning(self, "Sin resultados",
                                 "Ejecute primero una simulación.")
            return
        carpeta = QFileDialog.getExistingDirectory(
            self, "Carpeta donde guardar los resultados 2D")
        if not carpeta:
            return
        try:
            dominio = self.dominio_2d
            instantes = getattr(self.worker_2d, "instantes", None) if \
                getattr(self, "worker_2d", None) else None
            rutas = mesh_export.exportar_resultados_completos(
                simulador, carpeta, "hydroandina_2d",
                dominio["x_min"], dominio["y_max"],
                instantes=instantes, wkt_crs=dominio.get("wkt"))

            filas = [("Malla (SMS 2DM)", os.path.basename(rutas["malla_2dm"]), "",
                      f"{rutas['nodos']:,} nodos y {rutas['elementos']:,} elementos")]
            if "calado_dat" in rutas:
                filas.append(("Serie temporal de calado", os.path.basename(rutas["calado_dat"]),
                              "", f"{len(instantes)} instantes capturados"))
                filas.append(("Serie temporal de velocidad",
                              os.path.basename(rutas["velocidad_dat"]), "",
                              "dataset vectorial: flechas de dirección del flujo"))
            for clave, etiqueta in (("calado_max_tif", "Calado máximo (GeoTIFF)"),
                                     ("velocidad_max_tif", "Velocidad máxima (GeoTIFF)"),
                                     ("peligrosidad_tif", "Peligrosidad h·v (GeoTIFF)")):
                filas.append((etiqueta, os.path.basename(rutas[clave]), ""))
            poblar_tabla_parametros(self.tabla_exportacion_2d, filas, filas_visibles_max=8)

            cargadas = self._cargar_resultados_2d_en_qgis(rutas)
            QMessageBox.information(
                self, "Resultados exportados",
                f"Resultados guardados en:\n{carpeta}\n\n"
                f"Se cargaron {cargadas} capas en el proyecto.\n\n"
                "Para animar la inundación: seleccione la capa de malla, active el Controlador "
                "Temporal de QGIS (icono del reloj) y reprodúzcala. En las propiedades de la capa "
                "puede activar las flechas de velocidad.")
        except Exception as e:
            QMessageBox.critical(self, "Error al exportar", str(e))

    def _cargar_resultados_2d_en_qgis(self, rutas):
        """Carga la malla con sus datasets y los GeoTIFF de máximos."""
        proyecto = QgsProject.instance()
        cargadas = 0
        try:
            from qgis.core import QgsMeshLayer
            capa_malla = QgsMeshLayer(rutas["malla_2dm"], "Simulación 2D — malla", "mdal")
            if capa_malla.isValid():
                # addDatasets() es el método de QgsMeshLayer para asociar
                # conjuntos de datos a una malla ya cargada. Se comprueba
                # su existencia porque el nombre ha cambiado entre
                # versiones de QGIS, y un AttributeError aquí dejaría al
                # usuario con la malla sin resultados y sin explicación.
                for clave in ("calado_dat", "velocidad_dat"):
                    if clave not in rutas:
                        continue
                    if hasattr(capa_malla, "addDatasets"):
                        capa_malla.addDatasets(rutas[clave])
                    else:
                        capa_malla.dataProvider().addDataset(rutas[clave])
                proyecto.addMapLayer(capa_malla)
                cargadas += 1
        except Exception:
            # Que falle la capa de malla no debe impedir cargar los
            # ráster de máximos, que son el resultado principal.
            pass

        for clave, nombre in (("calado_max_tif", "Calado máximo (m)"),
                               ("velocidad_max_tif", "Velocidad máxima (m/s)"),
                               ("peligrosidad_tif", "Peligrosidad h·v (m²/s)")):
            if clave in rutas:
                capa = QgsRasterLayer(rutas[clave], nombre)
                if capa.isValid():
                    proyecto.addMapLayer(capa)
                    cargadas += 1
        return cargadas

    # -- Video de la simulación (item 8, fase 3): GIF armado a partir de
    # los instantes capturados por el worker, reproducido embebido con
    # QMovie (parte de Qt, sin códecs ni ffmpeg de por medio). --
    def _on_generar_animacion_2d(self):
        instantes = getattr(self.worker_2d, "instantes", None) if getattr(self, "worker_2d", None) else None
        simulador = getattr(self, "simulador_2d", None)
        if not instantes or simulador is None:
            QMessageBox.warning(
                self, "Sin instantes capturados",
                "Ejecute la simulación con «Intervalo de captura para la animación» mayor que 0 "
                "(sección 5) antes de generar el video.")
            return
        try:
            carpeta_tmp = tempfile.mkdtemp(prefix="hydroandina_video_2d_")
            ruta_tmp = os.path.join(carpeta_tmp, "animacion_2d.gif")
            info = swe2d_animation.generar_gif_calado(
                instantes, simulador, ruta_tmp,
                paso=self.spin_paso_animacion_2d.value(),
                duracion_frame_ms=self.spin_duracion_frame_2d.value())
            self._ruta_animacion_2d_actual = info["ruta"]
            self.movie_animacion_2d.stop()
            self.movie_animacion_2d.setFileName(info["ruta"])
            self.movie_animacion_2d.start()
            self.btn_pausar_animacion_2d.setEnabled(True)
            self.btn_pausar_animacion_2d.setText("⏸ Pausar")
            self.btn_guardar_animacion_2d.setEnabled(True)
            self.lbl_estado_video_2d.setText(
                f"Estado: animación generada -- {info['n_frames']} cuadros, "
                f"~{info['duracion_total_s']:.1f} s de reproducción por vuelta (se repite en bucle).")
        except swe2d_animation.AnimacionSwe2DError as e:
            QMessageBox.warning(self, "No se pudo generar la animación", str(e))
        except Exception as e:
            QMessageBox.critical(self, "Error generando la animación", str(e))

    def _on_pausar_reanudar_animacion_2d(self):
        en_pausa = self.movie_animacion_2d.state() == QMovie.Paused
        self.movie_animacion_2d.setPaused(not en_pausa)
        self.btn_pausar_animacion_2d.setText("▶ Reanudar" if not en_pausa else "⏸ Pausar")

    def _on_guardar_animacion_2d(self):
        ruta_actual = getattr(self, "_ruta_animacion_2d_actual", None)
        if not ruta_actual or not os.path.exists(ruta_actual):
            QMessageBox.warning(self, "Sin animación", "Genere primero la animación.")
            return
        ruta_destino, _ = QFileDialog.getSaveFileName(
            self, "Guardar animación de la simulación 2D", "animacion_2d.gif", "GIF (*.gif)")
        if not ruta_destino:
            return
        try:
            import shutil
            shutil.copyfile(ruta_actual, ruta_destino)
            QMessageBox.information(self, "Animación guardada", f"Guardada en:\n{ruta_destino}")
        except Exception as e:
            QMessageBox.critical(self, "Error guardando la animación", str(e))

    # -- Visualización 3D (item 8, fase 4a) --
    def _on_generar_vista_3d_2d(self):
        simulador = getattr(self, "simulador_2d", None)
        if simulador is None:
            QMessageBox.warning(self, "Sin resultados", "Ejecute primero una simulación.")
            return
        try:
            self.canvas_3d_2d.plot_terreno_calado(
                simulador.zb, simulador.h_max, simulador.dx, simulador.dy, activo=simulador.activo)
            self.lbl_estado_3d_2d.setText(
                "Estado: vista 3D generada -- arrastre con el mouse para rotar, use los botones "
                "para acercar/alejar o restablecer la vista.")
        except Exception as e:
            QMessageBox.critical(self, "Error generando la vista 3D", str(e))

    def _on_zoom_3d_2d(self, factor: float):
        self.canvas_3d_2d.zoom(factor)

    def _on_restablecer_vista_3d_2d(self):
        self.canvas_3d_2d.restablecer_vista()

    # -- Corte transversal interactivo (item 8, fase 4b) --
    def _activar_map_tool_corte_2d(self, checked):
        canvas = self.iface.mapCanvas()
        if checked:
            if not getattr(self, "dominio_2d", None) or getattr(self, "simulador_2d", None) is None:
                QMessageBox.warning(
                    self, "Falta la simulación",
                    "Cargue el dominio (sección 1) y ejecute una simulación antes de trazar el "
                    "corte transversal.")
                self.btn_marcar_corte_2d.setChecked(False)
                return
            self._primer_clic_corte_2d = None
            self.map_tool_corte_2d = QgsMapToolEmitPoint(canvas)
            self.map_tool_corte_2d.canvasClicked.connect(self._on_canvas_clicked_corte_2d)
            canvas.mapToolSet.connect(self._on_map_tool_changed_corte_2d)
            canvas.setMapTool(self.map_tool_corte_2d)
            self.btn_marcar_corte_2d.setText("Clic en el INICIO del corte...")
            self.hide()
        else:
            if self.map_tool_corte_2d is not None:
                try:
                    canvas.mapToolSet.disconnect(self._on_map_tool_changed_corte_2d)
                except TypeError:
                    pass
                canvas.unsetMapTool(self.map_tool_corte_2d)
            self.btn_marcar_corte_2d.setText(
                "📏 Marcar línea de corte en el mapa (clic inicio → clic fin)")
            self._restaurar_ventana()

    def _on_map_tool_changed_corte_2d(self, herramienta_nueva, herramienta_anterior):
        if herramienta_nueva is not self.map_tool_corte_2d:
            self.btn_marcar_corte_2d.setChecked(False)
            self.btn_marcar_corte_2d.setText(
                "📏 Marcar línea de corte en el mapa (clic inicio → clic fin)")
            self._restaurar_ventana()

    def _muestrear_linea_grilla(self, array2d, fila1, col1, fila2, col2, n_puntos=None):
        """Muestrea `array2d` (zb, h_max, ...) a lo largo de la línea recta
        entre (fila1,col1) y (fila2,col2) en coordenadas de malla, con
        vecino más cercano (suficiente para un corte diagnóstico -- no es
        un valor de diseño de precisión). n_puntos se autocalcula a partir
        de la longitud de la línea en celdas si no se indica."""
        filas, columnas = array2d.shape
        if n_puntos is None:
            n_puntos = max(int(round(math.hypot(fila2 - fila1, col2 - col1))) + 1, 2)
        valores = []
        for i in range(n_puntos):
            frac = i / (n_puntos - 1) if n_puntos > 1 else 0.0
            f = min(max(int(round(fila1 + frac * (fila2 - fila1))), 0), filas - 1)
            c = min(max(int(round(col1 + frac * (col2 - col1))), 0), columnas - 1)
            valores.append(float(array2d[f, c]))
        return valores, n_puntos

    def _on_canvas_clicked_corte_2d(self, punto, button):
        if self._primer_clic_corte_2d is None:
            self._primer_clic_corte_2d = QgsPointXY(punto)
            self.btn_marcar_corte_2d.setText("Clic en el FIN del corte...")
            return
        punto_inicio = self._primer_clic_corte_2d
        punto_fin = QgsPointXY(punto)
        self._primer_clic_corte_2d = None

        canvas = self.iface.mapCanvas()
        if self.map_tool_corte_2d is not None:
            try:
                canvas.mapToolSet.disconnect(self._on_map_tool_changed_corte_2d)
            except TypeError:
                pass
            canvas.unsetMapTool(self.map_tool_corte_2d)
        self.btn_marcar_corte_2d.setChecked(False)
        self.btn_marcar_corte_2d.setText(
            "📏 Marcar línea de corte en el mapa (clic inicio → clic fin)")
        self._restaurar_ventana()

        fila1, col1 = self._fila_columna_desde_punto_2d(punto_inicio)
        fila2, col2 = self._fila_columna_desde_punto_2d(punto_fin)
        try:
            self._procesar_corte_transversal_2d(fila1, col1, fila2, col2)
        except Exception as e:
            QMessageBox.critical(self, "Error procesando el corte transversal", str(e))

    def _procesar_corte_transversal_2d(self, fila1, col1, fila2, col2):
        simulador = self.simulador_2d
        zb_linea, n_puntos = self._muestrear_linea_grilla(simulador.zb, fila1, col1, fila2, col2)
        h_linea, _ = self._muestrear_linea_grilla(simulador.h_max, fila1, col1, fila2, col2, n_puntos)
        longitud_m = math.hypot((fila2 - fila1) * simulador.dy, (col2 - col1) * simulador.dx)
        paso_m = longitud_m / max(n_puntos - 1, 1)

        self.canvas_corte_transversal_2d.plot_perfil(
            zb_linea, h_linea, paso_m,
            titulo=f"Corte transversal — fila {fila1},col {col1} → fila {fila2},col {col2}")

        fila_medio = min(max(int(round((fila1 + fila2) / 2.0)), 0), simulador.zb.shape[0] - 1)
        col_medio = min(max(int(round((col1 + col2) / 2.0)), 0), simulador.zb.shape[1] - 1)

        instantes = getattr(self.worker_2d, "instantes", None) if getattr(self, "worker_2d", None) else None
        if instantes:
            tiempos = [instante[0] for instante in instantes]
            calados_punto = [float(instante[1][fila_medio, col_medio]) for instante in instantes]
            self.canvas_hidrograma_punto_2d.plot_hidrograma_puntual(
                tiempos, calados_punto,
                etiqueta=f"fila {fila_medio}, columna {col_medio} (punto medio del corte)")
        else:
            self.canvas_hidrograma_punto_2d.fig.clear()
            self.canvas_hidrograma_punto_2d.draw()

        vx_final, vy_final = simulador.componentes_velocidad()
        v_medio = math.hypot(float(vx_final[fila_medio, col_medio]), float(vy_final[fila_medio, col_medio]))

        poblar_tabla_parametros(self.tabla_corte_transversal_2d, [
            ("Punto de inicio", f"fila {fila1}, columna {col1}", ""),
            ("Punto final", f"fila {fila2}, columna {col2}", ""),
            ("Longitud del corte", round(longitud_m, 2), "m"),
            ("Puntos muestreados", n_puntos, ""),
            ("Calado máximo en el punto medio", round(float(h_linea[n_puntos // 2]), 3), "m"),
            ("Calado máximo a lo largo de todo el corte", round(max(h_linea), 3), "m"),
            ("Velocidad en el punto medio (estado final)", round(v_medio, 3), "m/s",
             "instantánea al terminar la simulación, no la máxima alcanzada durante el cálculo"),
            ("Instantes capturados disponibles", len(instantes) if instantes else 0, "",
             "para el gráfico de calado en el tiempo -- 0 si no se activó la captura antes de simular"),
        ])

        self.lbl_estado_corte_2d.setText(
            f"Estado: corte trazado -- {n_puntos} puntos muestreados a lo largo de {longitud_m:.1f} m.")

    # ==================================================================
    # PESTAÑA 8 — SIMULACIÓN HIDRÁULICA 2D DE ESTRUCTURAS
    # ==================================================================
    def _build_tab_simulacion_2d(self):
        """
        Simulación bidimensional propia (core/swe2d.py) sobre la grilla
        del MDE, orientada a cauces y a estructuras hidráulicas.

        No depende de ningún plugin externo ni de GPU: el solver está
        vectorizado con NumPy, que es lo único que QGIS garantiza.
        """
        tab = QWidget()
        v = QVBoxLayout(tab)

        lbl_intro = QLabel(
            "<b>Simulación hidrodinámica bidimensional</b> por las ecuaciones de aguas someras "
            "(Saint-Venant 2D), resueltas en volúmenes finitos sobre la grilla del MDE con malla "
            "desplazada, y con las estructuras hidráulicas incorporadas como enlaces internos.<br><br>"
            "A diferencia del cálculo 1D de la Pestaña 7, aquí el flujo se resuelve en planta: es "
            "lo que se necesita para <b>manchas de inundación</b>, para flujo que se desborda del "
            "cauce y se reparte lateralmente, y para evaluar el <b>peligro por calado y velocidad</b> "
            "aguas arriba y abajo de una obra."
        )
        lbl_intro.setWordWrap(True)
        v.addWidget(lbl_intro)

        # ---------------- 1. DOMINIO ----------------
        gb_dom = QGroupBox("1. Dominio de cálculo (terreno)")
        v_dom = QVBoxLayout(gb_dom)
        lbl_dom = QLabel(
            "El terreno define la malla: cada celda del ráster es un volumen de control. "
            "Puede usar el MDE recortado a la cuenca de la Pestaña 1 o cualquier ráster cargado "
            "(por ejemplo un levantamiento topográfico de detalle del tramo de la obra).<br><br>"
            "<b>El factor de remuestreo es la decisión más importante de esta pestaña.</b> El coste "
            "crece con el número de celdas Y con el número de pasos de tiempo, y al reducir el "
            "tamaño de celda a la mitad se cuadruplican las celdas y además se reduce a la mitad el "
            "paso estable: el coste se multiplica por ocho. Empiece grueso para tantear y afine solo "
            "cuando la configuración esté decidida."
        )
        lbl_dom.setWordWrap(True)
        v_dom.addWidget(lbl_dom)

        f_dom = QFormLayout()
        f_dom.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.combo_dem_2d = QgsMapLayerComboBox()
        self.combo_dem_2d.setFilters(QgsMapLayerProxyModel.RasterLayer)
        self.combo_dem_2d.setAllowEmptyLayer(True)
        f_dom.addRow("Ráster de terreno:", self.combo_dem_2d)

        self.check_usar_dem_cuenca = QCheckBox(
            "Usar el MDE recortado a la cuenca de la Pestaña 1 (recomendado)")
        self.check_usar_dem_cuenca.setChecked(True)
        f_dom.addRow("", self.check_usar_dem_cuenca)

        self.spin_remuestreo_2d = QSpinBox()
        self.spin_remuestreo_2d.setRange(1, 20)
        self.spin_remuestreo_2d.setValue(4)
        self.spin_remuestreo_2d.setToolTip(
            "1 = resolución original. 4 = una de cada 4 celdas en cada dirección "
            "(16 veces menos celdas).")
        f_dom.addRow("Factor de remuestreo (1 = resolución original):", self.spin_remuestreo_2d)
        v_dom.addLayout(f_dom)

        h_dom_btn = QHBoxLayout()
        btn_cargar_dom = QPushButton("Cargar dominio y estimar coste")
        btn_cargar_dom.clicked.connect(self._on_cargar_dominio_2d)
        limitar_ancho_boton(btn_cargar_dom)
        h_dom_btn.addWidget(btn_cargar_dom)
        h_dom_btn.addStretch()
        v_dom.addLayout(h_dom_btn)

        self.cuadro_dominio_2d = CuadroResumenImpacto(ancho_maximo=760)
        self.cuadro_dominio_2d.actualizar(
            titulo="DOMINIO SIN CARGAR", valor_principal="—",
            subtitulo="Seleccione el terreno y pulse «Cargar dominio»")
        centrar_en_layout(self.cuadro_dominio_2d, v_dom)
        self.tabla_dominio_2d = crear_tabla_parametros()
        v_dom.addWidget(self.tabla_dominio_2d)
        v.addWidget(gb_dom)

        # ---------------- 2. RUGOSIDAD ----------------
        gb_rug = QGroupBox("2. Rugosidad de Manning")
        v_rug = QVBoxLayout(gb_rug)
        lbl_rug = QLabel(
            "La rugosidad controla la resistencia al flujo y, con ella, el calado y la velocidad. "
            "Un valor uniforme sirve para un primer tanteo; para un cauce real conviene distinguir "
            "al menos el lecho de las márgenes, porque la llanura de inundación con vegetación "
            "puede tener el triple de <i>n</i> que el cauce y eso cambia por completo el reparto "
            "del caudal entre ambos."
        )
        lbl_rug.setWordWrap(True)
        v_rug.addWidget(lbl_rug)

        f_rug = QFormLayout()
        f_rug.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.spin_manning_2d = QDoubleSpinBox()
        self.spin_manning_2d.setRange(0.008, 0.300)
        self.spin_manning_2d.setDecimals(3)
        self.spin_manning_2d.setSingleStep(0.005)
        self.spin_manning_2d.setValue(0.035)
        f_rug.addRow("Manning n uniforme:", self.spin_manning_2d)

        self.combo_manning_ref_2d = QComboBox()
        for etiqueta, valor in (
                ("Cauce natural limpio y recto — 0.030", 0.030),
                ("Cauce natural con piedras y malezas — 0.045", 0.045),
                ("Cauce de montaña con cantos rodados — 0.050", 0.050),
                ("Torrentera andina con bloques grandes — 0.070", 0.070),
                ("Hormigón acabado (canal/obra) — 0.014", 0.014),
                ("Mampostería de piedra — 0.025", 0.025),
                ("Llanura de pastos cortos — 0.030", 0.030),
                ("Llanura con matorral denso — 0.080", 0.080),
                ("Zona urbanizada (edificaciones) — 0.120", 0.120)):
            self.combo_manning_ref_2d.addItem(etiqueta, valor)
        self.combo_manning_ref_2d.currentIndexChanged.connect(
            lambda: self.spin_manning_2d.setValue(self.combo_manning_ref_2d.currentData()))
        f_rug.addRow("Valores de referencia (Chow, 1959):", self.combo_manning_ref_2d)
        v_rug.addLayout(f_rug)
        v.addWidget(gb_rug)

        # ---------------- 3. CONDICIONES DE CONTORNO ----------------
        gb_bc = QGroupBox("3. Condiciones de contorno y forzamiento")
        v_bc = QVBoxLayout(gb_bc)
        lbl_bc = QLabel(
            "<b>Entradas de caudal:</b> pegue una fila por punto de inyección con su fila y columna "
            "en la malla (se muestran en el cuadro del dominio) y el caudal en m³/s. Deje el caudal "
            "en 0 y marque la casilla de abajo para usar en su lugar el hidrograma de diseño de la "
            "Pestaña 6, que es lo habitual para una avenida de proyecto.<br><br>"
            "<b>Salida:</b> por defecto el agua que alcanza el borde del dominio lo abandona y se "
            "contabiliza. Es la condición razonable cuando el MDE cubre la zona de estudio completa."
        )
        lbl_bc.setWordWrap(True)
        v_bc.addWidget(lbl_bc)

        self.tabla_entradas_2d = TablaPegable(4, 3)
        self.tabla_entradas_2d.setHorizontalHeaderLabels(
            ["Fila (0 = norte)", "Columna (0 = oeste)", "Caudal (m³/s)"])
        limitar_ancho_tabla(self.tabla_entradas_2d, ancho_maximo=520)
        ajustar_alto_tabla(self.tabla_entradas_2d, filas_visibles_max=6)
        h_ent = QHBoxLayout()
        h_ent.addWidget(self.tabla_entradas_2d)
        h_ent.addStretch()
        v_bc.addLayout(h_ent)

        h_ent_btn = QHBoxLayout()
        btn_entrada_auto = QPushButton("Situar la entrada en el punto más alto del cauce")
        btn_entrada_auto.clicked.connect(self._on_entrada_automatica_2d)
        limitar_ancho_boton(btn_entrada_auto)
        h_ent_btn.addWidget(btn_entrada_auto)
        h_ent_btn.addStretch()
        v_bc.addLayout(h_ent_btn)

        self.check_hidrograma_p6 = QCheckBox(
            "Usar el hidrograma de diseño de la Pestaña 6 en las entradas con caudal 0")
        self.check_hidrograma_p6.setChecked(True)
        v_bc.addWidget(self.check_hidrograma_p6)

        f_bc = QFormLayout()
        f_bc.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.spin_lluvia_2d = QDoubleSpinBox()
        self.spin_lluvia_2d.setRange(0.0, 500.0)
        self.spin_lluvia_2d.setDecimals(2)
        self.spin_lluvia_2d.setValue(0.0)
        self.spin_lluvia_2d.setToolTip(
            "Lluvia uniforme aplicada a todo el dominio (rain-on-grid). 0 = sin lluvia.")
        f_bc.addRow("Lluvia sobre malla (mm/h):", self.spin_lluvia_2d)
        v_bc.addLayout(f_bc)

        self.check_salida_bordes_2d = QCheckBox(
            "Salida libre por el borde del dominio (desmarque para dominio cerrado)")
        self.check_salida_bordes_2d.setChecked(True)
        v_bc.addWidget(self.check_salida_bordes_2d)
        v.addWidget(gb_bc)

        # ---------------- 4. ESTRUCTURAS ----------------
        gb_est = QGroupBox("4. Estructuras hidráulicas")
        v_est = QVBoxLayout(gb_est)
        lbl_est = QLabel(
            "Las estructuras se modelan como <b>enlaces internos</b> entre dos celdas, sustituyendo "
            "el flujo del terreno por su ley de descarga. Es el mismo enfoque de HEC-RAS 2D e Iber, "
            "y responde a un hecho geométrico: la obra es más pequeña que la celda, así que no se "
            "resuelve con la malla sino con su ecuación hidráulica.<br><br>"
            "<b>Vertedero</b> — Q = C·L·H<sup>3/2</sup>, con sumergencia de Villemonte. Parámetros: "
            "cota de cresta (m), longitud (m), C (1.84 cresta ancha; 2.2 perfil Creager).<br>"
            "<b>Orificio / compuerta</b> — Q = Cd·A·√(2g·Δh). Parámetros: área (m²), Cd (0.61), y un "
            "tercer valor no usado (escriba 0).<br>"
            "<b>Alcantarilla</b> — criterio HDS-5: se calcula el control de entrada y el de salida y "
            "gobierna el menor. Parámetros: cota de entrada (m), diámetro (m), longitud (m)."
        )
        lbl_est.setWordWrap(True)
        v_est.addWidget(lbl_est)

        self.tabla_estructuras_2d = TablaPegable(4, 8)
        self.tabla_estructuras_2d.setHorizontalHeaderLabels(
            ["Nombre", "Tipo", "Fila 1", "Col 1", "Fila 2", "Col 2",
             "Parámetro 1", "Parámetro 2 / 3"])
        aplicar_columna_elastica(self.tabla_estructuras_2d, indice_columna_larga=0)
        ajustar_alto_tabla(self.tabla_estructuras_2d, filas_visibles_max=8)
        v_est.addWidget(self.tabla_estructuras_2d)
        lbl_est_ayuda = QLabel(
            "<i>Tipo: escriba «vertedero», «orificio» o «alcantarilla». En «Parámetro 1» ponga la "
            "cota de cresta / el área / la cota de entrada; en «Parámetro 2 / 3», la longitud y el "
            "coeficiente separados por punto y coma (p.ej. «12; 1.84»), o el diámetro y la longitud "
            "para una alcantarilla (p.ej. «1.2; 15»).</i>")
        lbl_est_ayuda.setWordWrap(True)
        v_est.addWidget(lbl_est_ayuda)

        # -- Insertar estructura desde el mapa (item 8): en vez de adivinar
        # fila/columna a mano, se marca la estructura con 2 clics sobre el
        # mapa (mismo patrón de QgsMapToolEmitPoint que ya usan la Pestaña 1
        # y las secciones de socavación/sedimentos) y se agrega la fila
        # sola. Cada estructura insertada así también queda en una capa de
        # líneas exportable, para tenerla como capa GIS del proyecto.
        gb_insertar = QGroupBox("Insertar estructura desde el mapa (opcional)")
        v_ins = QVBoxLayout(gb_insertar)
        lbl_ins = QLabel(
            "Complete el tipo y los parámetros abajo, marque los 2 puntos de la estructura en el "
            "mapa (clic de inicio, clic de fin) y se agrega sola una fila a la tabla de arriba con "
            "la fila/columna correctas -- ya no hay que calcularlas a mano. También puede importar "
            "varias de una vez desde una capa de líneas ya digitalizada, o exportar todas las "
            "insertadas aquí a un shapefile."
        )
        lbl_ins.setWordWrap(True)
        v_ins.addWidget(lbl_ins)

        f_ins = QFormLayout()
        f_ins.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.edit_insertar_nombre_2d = QLineEdit()
        self.edit_insertar_nombre_2d.setPlaceholderText("(opcional -- se numera sola si se deja vacío)")
        f_ins.addRow("Nombre:", self.edit_insertar_nombre_2d)
        self.combo_insertar_tipo_2d = QComboBox()
        self.combo_insertar_tipo_2d.addItems(["vertedero", "orificio", "alcantarilla"])
        f_ins.addRow("Tipo:", self.combo_insertar_tipo_2d)
        self.spin_insertar_param1_2d = QDoubleSpinBox()
        self.spin_insertar_param1_2d.setRange(-1000.0, 100000.0)
        self.spin_insertar_param1_2d.setDecimals(3)
        f_ins.addRow("Parámetro 1 (cota de cresta / área / cota de entrada):", self.spin_insertar_param1_2d)
        self.edit_insertar_param23_2d = QLineEdit()
        self.edit_insertar_param23_2d.setPlaceholderText("p.ej. 12;1.84  o  1.2;15")
        f_ins.addRow("Parámetro 2 / 3 (longitud;C  o  diámetro;longitud):", self.edit_insertar_param23_2d)
        v_ins.addLayout(f_ins)

        self.btn_marcar_estructura_2d = QPushButton(
            "📍 Marcar los 2 puntos de la estructura en el mapa (clic inicio → clic fin)")
        self.btn_marcar_estructura_2d.setCheckable(True)
        self.btn_marcar_estructura_2d.toggled.connect(self._activar_map_tool_estructura_2d)
        v_ins.addWidget(self.btn_marcar_estructura_2d)

        h_lineas = QHBoxLayout()
        h_lineas.addWidget(QLabel("O importar desde una capa de líneas ya digitalizada:"))
        self.combo_capa_lineas_estructuras_2d = QgsMapLayerComboBox()
        self.combo_capa_lineas_estructuras_2d.setFilters(QgsMapLayerProxyModel.LineLayer)
        self.combo_capa_lineas_estructuras_2d.setAllowEmptyLayer(True)
        h_lineas.addWidget(self.combo_capa_lineas_estructuras_2d)
        btn_importar_lineas_2d = QPushButton("Importar filas desde esta capa")
        btn_importar_lineas_2d.clicked.connect(self._on_importar_estructuras_desde_lineas)
        h_lineas.addWidget(btn_importar_lineas_2d)
        v_ins.addLayout(h_lineas)

        h_export_est = QHBoxLayout()
        btn_exportar_capa_estructuras_2d = QPushButton(
            "💾 Exportar capa de estructuras insertadas (SHP / KML / GeoJSON)")
        btn_exportar_capa_estructuras_2d.clicked.connect(self._on_exportar_capa_estructuras_2d)
        h_export_est.addWidget(btn_exportar_capa_estructuras_2d)
        h_export_est.addStretch()
        v_ins.addLayout(h_export_est)

        lbl_dibujar = QLabel(
            "<b>O dibujar libremente con el mouse</b> -- para trazar una estructura curva "
            "siguiendo un cauce o una vía, en vez de solo el inicio y el fin: habilite la edición "
            "aquí, dibuje con la herramienta «Añadir entidad de línea» de la barra de "
            "digitalización de QGIS (varios clics para seguir el trazado; doble clic o Enter para "
            "terminar la línea), y sincronice para que la fila/columna se calculen solas y la tabla "
            "de arriba se reconstruya con lo que haya dibujado."
        )
        lbl_dibujar.setWordWrap(True)
        v_ins.addWidget(lbl_dibujar)

        h_dibujar = QHBoxLayout()
        btn_habilitar_dibujo_2d = QPushButton("🖊 Habilitar edición para dibujar")
        btn_habilitar_dibujo_2d.clicked.connect(self._on_habilitar_dibujo_estructuras_2d)
        h_dibujar.addWidget(btn_habilitar_dibujo_2d)
        btn_sincronizar_estructuras_2d = QPushButton(
            "🔄 Sincronizar fila/columna y la tabla desde lo dibujado")
        btn_sincronizar_estructuras_2d.clicked.connect(self._on_sincronizar_estructuras_2d_desde_capa)
        h_dibujar.addWidget(btn_sincronizar_estructuras_2d)
        btn_guardar_edicion_2d = QPushButton("Guardar cambios de la capa")
        btn_guardar_edicion_2d.clicked.connect(self._on_guardar_edicion_estructuras_2d)
        h_dibujar.addWidget(btn_guardar_edicion_2d)
        v_ins.addLayout(h_dibujar)

        self.lbl_estado_estructuras_2d = QLabel("Estado: ninguna estructura insertada desde el mapa todavía.")
        self.lbl_estado_estructuras_2d.setWordWrap(True)
        v_ins.addWidget(self.lbl_estado_estructuras_2d)

        v_est.addWidget(gb_insertar)
        v.addWidget(gb_est)

        # ---------------- 5. CONTROL NUMÉRICO ----------------
        gb_num = QGroupBox("5. Esquema y control numérico")
        v_num = QVBoxLayout(gb_num)
        lbl_num = QLabel(
            "<b>Inercia local</b> (Bates, Horritt &amp; Fewtrell, 2010) conserva la aceleración local "
            "y solo desprecia la convectiva. Es el esquema de LISFLOOD-FP y el que corresponde para "
            "cauces y estructuras. <b>Es el recomendado y además el más rápido.</b><br><br>"
            "<b>Onda difusiva</b> desprecia toda la inercia. Al hacerlo la ecuación deja de ser "
            "hiperbólica y pasa a ser parabólica, cuyo límite de estabilidad explícito "
            "(Δt ≤ Δx²/4D) es mucho más severo: en un cauce típico exige pasos unas 40 veces "
            "menores. Resulta pues más simple pero MÁS CARA, y subestima el pico donde la inercia "
            "importa. Se ofrece para expansión en llanura, no para cauce."
        )
        lbl_num.setWordWrap(True)
        v_num.addWidget(lbl_num)

        f_num = QFormLayout()
        f_num.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.combo_esquema_2d = QComboBox()
        self.combo_esquema_2d.addItem("Inercia local (recomendado)", "inercia_local")
        self.combo_esquema_2d.addItem("Onda difusiva", "onda_difusiva")
        f_num.addRow("Esquema numérico:", self.combo_esquema_2d)

        self.spin_tiempo_2d = QDoubleSpinBox()
        self.spin_tiempo_2d.setRange(10.0, 604800.0)
        self.spin_tiempo_2d.setDecimals(0)
        self.spin_tiempo_2d.setValue(3600.0)
        f_num.addRow("Tiempo total de simulación (s):", self.spin_tiempo_2d)

        self.spin_cfl_2d = QDoubleSpinBox()
        self.spin_cfl_2d.setRange(0.05, 1.0)
        self.spin_cfl_2d.setDecimals(2)
        self.spin_cfl_2d.setValue(0.70)
        self.spin_cfl_2d.setToolTip(
            "Número de Courant. Bájelo si aparecen oscilaciones o el balance de masa no cierra.")
        f_num.addRow("Número de Courant (CFL):", self.spin_cfl_2d)

        self.spin_dt_max_2d = QDoubleSpinBox()
        self.spin_dt_max_2d.setRange(0.01, 300.0)
        self.spin_dt_max_2d.setDecimals(2)
        self.spin_dt_max_2d.setValue(10.0)
        f_num.addRow("Paso de tiempo máximo (s):", self.spin_dt_max_2d)

        self.spin_captura_2d = QDoubleSpinBox()
        self.spin_captura_2d.setRange(0.0, 86400.0)
        self.spin_captura_2d.setDecimals(0)
        self.spin_captura_2d.setValue(300.0)
        self.spin_captura_2d.setToolTip(
            "Cada cuánto se guarda un instante para animar el resultado en QGIS. "
            "0 = no guardar instantes (solo los mapas de máximos).")
        f_num.addRow("Intervalo de captura para la animación (s):", self.spin_captura_2d)
        v_num.addLayout(f_num)
        v.addWidget(gb_num)

        # ---------------- 6. EJECUCIÓN ----------------
        gb_run = QGroupBox("6. Ejecución")
        v_run = QVBoxLayout(gb_run)
        h_run = QHBoxLayout()
        self.btn_simular_2d = QPushButton("▶  Ejecutar simulación 2D")
        self.btn_simular_2d.setStyleSheet(
            "background-color: #1F3864; color: white; font-weight: bold; padding: 8px;")
        self.btn_simular_2d.clicked.connect(self._on_ejecutar_simulacion_2d)
        limitar_ancho_boton(self.btn_simular_2d)
        h_run.addWidget(self.btn_simular_2d)
        self.btn_cancelar_2d = QPushButton("■  Cancelar")
        self.btn_cancelar_2d.clicked.connect(self._on_cancelar_simulacion_2d)
        self.btn_cancelar_2d.setEnabled(False)
        limitar_ancho_boton(self.btn_cancelar_2d)
        h_run.addWidget(self.btn_cancelar_2d)
        h_run.addStretch()
        v_run.addLayout(h_run)

        self.barra_progreso_2d = QProgressBar()
        self.barra_progreso_2d.setValue(0)
        v_run.addWidget(self.barra_progreso_2d)
        self.lbl_estado_2d = QLabel("Estado: en espera.")
        self.lbl_estado_2d.setWordWrap(True)
        v_run.addWidget(self.lbl_estado_2d)
        v.addWidget(gb_run)

        # ---------------- 7. RESULTADOS ----------------
        gb_res = QGroupBox("7. Resultados")
        v_res = QVBoxLayout(gb_res)
        self.cuadro_resultado_2d = CuadroResumenImpacto(ancho_maximo=760)
        self.cuadro_resultado_2d.actualizar(
            titulo="SIN SIMULAR", valor_principal="—",
            subtitulo="Ejecute la simulación para ver los resultados")
        centrar_en_layout(self.cuadro_resultado_2d, v_res)

        self.tabla_resultado_2d = crear_tabla_parametros()
        v_res.addWidget(self.tabla_resultado_2d)

        v_res.addWidget(QLabel("<b>Mapa de calados máximos sobre el relieve</b>"))
        self.canvas_mapa_calado_swe2d = MapaCalado2DCanvas()
        v_res.addWidget(self.canvas_mapa_calado_swe2d)

        v_res.addWidget(QLabel("<b>Peligrosidad h·v y reparto del área inundada</b>"))
        self.canvas_peligro_2d = MapaPeligrosidadCanvas()
        v_res.addWidget(self.canvas_peligro_2d)

        v_res.addWidget(QLabel("<b>Evolución temporal y cierre del balance de masa</b>"))
        self.canvas_hidrogramas_2d = HidrogramasSwe2DCanvas()
        v_res.addWidget(self.canvas_hidrogramas_2d)

        v_res.addWidget(QLabel("<b>Perfil por una fila de la malla</b>"))
        f_perf = QFormLayout()
        f_perf.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.spin_fila_perfil_2d = QSpinBox()
        self.spin_fila_perfil_2d.setRange(0, 100000)
        self.spin_fila_perfil_2d.valueChanged.connect(self._on_actualizar_perfil_2d)
        f_perf.addRow("Fila de la malla para el perfil longitudinal:", self.spin_fila_perfil_2d)
        v_res.addLayout(f_perf)
        self.canvas_perfil_2d = PerfilSwe2DCanvas()
        v_res.addWidget(self.canvas_perfil_2d)

        self.tabla_estructuras_resultado_2d = crear_tabla_parametros()
        v_res.addWidget(QLabel("<b>Caudales por las estructuras</b>"))
        v_res.addWidget(self.tabla_estructuras_resultado_2d)
        v.addWidget(gb_res)

        # ---------------- 8. EXPORTACIÓN ----------------
        gb_exp = QGroupBox("8. Exportación a QGIS")
        v_exp = QVBoxLayout(gb_exp)
        lbl_exp = QLabel(
            "Exporta la malla en formato <b>SMS 2DM</b> con los resultados como conjuntos de datos, "
            "que QGIS lee de forma nativa con MDAL —el mismo motor que usa para HEC-RAS 2D—, más los "
            "mapas de máximos en GeoTIFF.<br><br>"
            "Cargada como capa de malla, la serie temporal se reproduce con el <b>Controlador "
            "Temporal</b> de QGIS: animación del avance de la inundación y flechas de velocidad. Un "
            "ráster de máximos responde «hasta dónde llegó»; la malla temporal responde «cuándo "
            "llegó y con qué velocidad», que es lo que hace falta para justificar un plazo de "
            "evacuación o el dimensionado de una obra de paso."
        )
        lbl_exp.setWordWrap(True)
        v_exp.addWidget(lbl_exp)

        h_exp = QHBoxLayout()
        btn_exportar_2d = QPushButton("Exportar resultados y cargarlos en QGIS")
        btn_exportar_2d.clicked.connect(self._on_exportar_resultados_2d)
        limitar_ancho_boton(btn_exportar_2d)
        h_exp.addWidget(btn_exportar_2d)
        h_exp.addStretch()
        v_exp.addLayout(h_exp)
        self.tabla_exportacion_2d = crear_tabla_parametros()
        v_exp.addWidget(self.tabla_exportacion_2d)
        v.addWidget(gb_exp)

        # ---------------- 9. VIDEO DE LA SIMULACIÓN ----------------
        gb_video = QGroupBox("9. Video de la simulación (animación GIF)")
        v_video = QVBoxLayout(gb_video)
        lbl_video_intro = QLabel(
            "Arma una animación de la evolución del calado a partir de los instantes capturados "
            "durante la simulación (requiere haber corrido con «Intervalo de captura» mayor que 0 "
            "en la sección 5), y la reproduce aquí mismo. Se genera como GIF -- reproducible con "
            "las herramientas propias de Qt, sin depender de códecs de video externos ni de tener "
            "ffmpeg instalado."
        )
        lbl_video_intro.setWordWrap(True)
        v_video.addWidget(lbl_video_intro)

        f_video = QFormLayout()
        f_video.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.spin_paso_animacion_2d = QSpinBox()
        self.spin_paso_animacion_2d.setRange(1, 50)
        self.spin_paso_animacion_2d.setValue(1)
        self.spin_paso_animacion_2d.setToolTip(
            "Usar 1 de cada N instantes capturados -- súbalo para acortar el GIF sin volver a "
            "simular con un intervalo de captura mayor. El instante final siempre se incluye.")
        f_video.addRow("Usar 1 de cada N instantes capturados:", self.spin_paso_animacion_2d)
        self.spin_duracion_frame_2d = QSpinBox()
        self.spin_duracion_frame_2d.setRange(20, 2000)
        self.spin_duracion_frame_2d.setValue(200)
        self.spin_duracion_frame_2d.setSuffix(" ms")
        f_video.addRow("Duración de cada cuadro:", self.spin_duracion_frame_2d)
        v_video.addLayout(f_video)

        h_video_btn = QHBoxLayout()
        btn_generar_animacion_2d = QPushButton("🎬 Generar animación")
        btn_generar_animacion_2d.clicked.connect(self._on_generar_animacion_2d)
        limitar_ancho_boton(btn_generar_animacion_2d)
        h_video_btn.addWidget(btn_generar_animacion_2d)
        self.btn_pausar_animacion_2d = QPushButton("⏸ Pausar")
        self.btn_pausar_animacion_2d.clicked.connect(self._on_pausar_reanudar_animacion_2d)
        self.btn_pausar_animacion_2d.setEnabled(False)
        h_video_btn.addWidget(self.btn_pausar_animacion_2d)
        self.btn_guardar_animacion_2d = QPushButton("💾 Guardar animación como…")
        self.btn_guardar_animacion_2d.clicked.connect(self._on_guardar_animacion_2d)
        self.btn_guardar_animacion_2d.setEnabled(False)
        h_video_btn.addWidget(self.btn_guardar_animacion_2d)
        h_video_btn.addStretch()
        v_video.addLayout(h_video_btn)

        self.lbl_animacion_2d = QLabel("(genere la animación para verla aquí)")
        self.lbl_animacion_2d.setAlignment(Qt.AlignCenter)
        self.lbl_animacion_2d.setMinimumSize(320, 240)
        self.lbl_animacion_2d.setStyleSheet(
            "background-color: #1a1a1a; color: #bbbbbb; border: 1px solid #666666;")
        self.movie_animacion_2d = QMovie()
        self.lbl_animacion_2d.setMovie(self.movie_animacion_2d)
        h_video_centrado = QHBoxLayout()
        h_video_centrado.addStretch()
        h_video_centrado.addWidget(self.lbl_animacion_2d)
        h_video_centrado.addStretch()
        v_video.addLayout(h_video_centrado)

        self.lbl_estado_video_2d = QLabel("Estado: ninguna animación generada todavía.")
        self.lbl_estado_video_2d.setWordWrap(True)
        v_video.addWidget(self.lbl_estado_video_2d)
        v.addWidget(gb_video)

        # ---------------- 10. VISUALIZACIÓN 3D ----------------
        gb_3d = QGroupBox("10. Visualización 3D del terreno y el calado")
        v_3d = QVBoxLayout(gb_3d)
        lbl_3d = QLabel(
            "Superficie 3D del terreno con el calado máximo superpuesto -- arrastre con el mouse "
            "sobre el gráfico para rotar la vista, y use los botones para acercar/alejar/"
            "restablecer. Por rendimiento, la malla se muestra submuestreada (una simulación real "
            "tiene demasiadas celdas para una superficie 3D interactiva); alcanza para ubicar la "
            "mancha de inundación sobre el relieve real de la cuenca."
        )
        lbl_3d.setWordWrap(True)
        v_3d.addWidget(lbl_3d)

        h_3d_btn = QHBoxLayout()
        btn_generar_3d_2d = QPushButton("🗺 Generar vista 3D")
        btn_generar_3d_2d.clicked.connect(self._on_generar_vista_3d_2d)
        limitar_ancho_boton(btn_generar_3d_2d)
        h_3d_btn.addWidget(btn_generar_3d_2d)
        btn_acercar_3d_2d = QPushButton("🔍+ Acercar")
        btn_acercar_3d_2d.clicked.connect(lambda: self._on_zoom_3d_2d(0.8))
        h_3d_btn.addWidget(btn_acercar_3d_2d)
        btn_alejar_3d_2d = QPushButton("🔍− Alejar")
        btn_alejar_3d_2d.clicked.connect(lambda: self._on_zoom_3d_2d(1.25))
        h_3d_btn.addWidget(btn_alejar_3d_2d)
        btn_restablecer_3d_2d = QPushButton("Restablecer vista")
        btn_restablecer_3d_2d.clicked.connect(self._on_restablecer_vista_3d_2d)
        h_3d_btn.addWidget(btn_restablecer_3d_2d)
        h_3d_btn.addStretch()
        v_3d.addLayout(h_3d_btn)

        self.canvas_3d_2d = TerrenoCalado3DCanvas()
        v_3d.addWidget(self.canvas_3d_2d)
        self.lbl_estado_3d_2d = QLabel("Estado: sin generar todavía.")
        self.lbl_estado_3d_2d.setWordWrap(True)
        v_3d.addWidget(self.lbl_estado_3d_2d)
        v.addWidget(gb_3d)

        # ---------------- 11. CORTE TRANSVERSAL INTERACTIVO ----------------
        gb_corte = QGroupBox("11. Corte transversal interactivo")
        v_corte = QVBoxLayout(gb_corte)
        lbl_corte = QLabel(
            "Marque una línea sobre el mapa (2 clics) para obtener el corte transversal del "
            "terreno y el calado máximo a lo largo de ella, y la evolución del calado EN EL "
            "TIEMPO en el punto medio de esa línea (a partir de los instantes capturados -- "
            "requiere haber simulado con «Intervalo de captura» mayor que 0, sección 5)."
        )
        lbl_corte.setWordWrap(True)
        v_corte.addWidget(lbl_corte)

        self.btn_marcar_corte_2d = QPushButton(
            "📏 Marcar línea de corte en el mapa (clic inicio → clic fin)")
        self.btn_marcar_corte_2d.setCheckable(True)
        self.btn_marcar_corte_2d.toggled.connect(self._activar_map_tool_corte_2d)
        v_corte.addWidget(self.btn_marcar_corte_2d)

        self.tabla_corte_transversal_2d = crear_tabla_parametros()
        v_corte.addWidget(self.tabla_corte_transversal_2d)

        v_corte.addWidget(QLabel("<b>Perfil del corte (terreno + calado máximo)</b>"))
        self.canvas_corte_transversal_2d = PerfilSwe2DCanvas(width=8.4, height=4.0)
        v_corte.addWidget(self.canvas_corte_transversal_2d)

        v_corte.addWidget(QLabel("<b>Calado en el tiempo, en el punto medio del corte</b>"))
        self.canvas_hidrograma_punto_2d = HidrogramasSwe2DCanvas(width=8.4, height=3.6)
        v_corte.addWidget(self.canvas_hidrograma_punto_2d)

        self.lbl_estado_corte_2d = QLabel("Estado: ningún corte trazado todavía.")
        self.lbl_estado_corte_2d.setWordWrap(True)
        v_corte.addWidget(self.lbl_estado_corte_2d)
        v.addWidget(gb_corte)

        self.resumen_final_2d = ResumenFinal(alto_minimo=120)
        self.resumen_final_2d.setHtml(
            "<i>El resumen final de la simulación 2D aparecerá aquí cuando ejecute el modelo.</i>")
        v.addWidget(QLabel("<b>Cuadro resumen final — Simulación Hidráulica 2D</b>"))
        v.addWidget(self.resumen_final_2d)

        v.addStretch()
        self._agregar_pestaña_con_scroll(tab, "8. Simulación Hidráulica 2D Estructuras")

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

        self.tabla_resultado_completacion = crear_tabla_parametros()
        v.addWidget(self.tabla_resultado_completacion)
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
                poblar_tabla_parametros(self.tabla_resultado_completacion, [
                    ("Método", "Vector Regional", ""),
                    ("Índice regional por periodo", str(r["indice_regional_por_periodo"]), ""),
                    ("Series completadas", str(r["series_completadas"]), ""),
                ])
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
                poblar_tabla_parametros(self.tabla_resultado_completacion, [
                    ("Método", "IDW", ""),
                    (f"Serie completada de '{objetivo}'", str(r), ""),
                ])
            elif metodo == "regresion":
                r = data_completion.completar_regresion_multiple(series, objetivo)
                poblar_tabla_parametros(self.tabla_resultado_completacion, [
                    ("Método", "Regresión Múltiple", ""),
                    ("R² de ajuste", r["r2_ajuste"], "adim."),
                    ("Coeficientes", str(r["coeficientes"]), ""),
                    ("Serie completada", str(r["serie_completada"]), ""),
                ])
            else:  # rf
                r = data_completion.completar_random_forest(series, objetivo)
                poblar_tabla_parametros(self.tabla_resultado_completacion, [
                    ("Método", "Random Forest", ""),
                    ("R² (entrenamiento)", r["r2_ajuste_entrenamiento"], "adim."),
                    ("Importancia de variables", str(r["importancia_variables"]), ""),
                    ("Serie completada", str(r["serie_completada"]), ""),
                ])
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

        self.tabla_resultado_areal = crear_tabla_parametros()
        v.addWidget(self.tabla_resultado_areal)
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
            filas_areal = [
                ("Método", metodo.upper(), ""),
                ("Precipitación areal", r["precipitacion_areal_mm"], "mm"),
                ("Puntos de grilla", r.get("n_puntos_grilla", "?"), ""),
            ]
            if "variograma_ajustado" in r:
                filas_areal.append(("Variograma ajustado", str(r["variograma_ajustado"]), "", r.get("nota", "")))
            poblar_tabla_parametros(self.tabla_resultado_areal, filas_areal)
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
        self.tabla_resultado_oferta = crear_tabla_parametros()
        v.addWidget(self.tabla_resultado_oferta)

        btn_calc.clicked.connect(lambda: self._on_calcular_oferta_hidrica(combo_modelo.currentIndex()))
        return pagina

    def _on_calcular_oferta_hidrica(self, indice_modelo: int):
        try:
            if indice_modelo == 0:
                r = water_yield.balance_budyko_fu(self.spin_of_p.value(), self.spin_of_pet.value(), self.spin_of_w.value())
                poblar_tabla_parametros(self.tabla_resultado_oferta, [
                    ("Índice de aridez (PET/P)", r["indice_aridez_PET_P"], "adim."),
                    ("AET", r["AET_mm"], "mm"),
                    ("Escorrentía", r["escorrentia_mm"], "mm"),
                    ("Coeficiente de escorrentía", r["coeficiente_escorrentia"], "adim."),
                ])
                return
            p_mensual = [float(x) for x in self.edit_of_p_mensual.text().split(",") if x.strip()]
            etp_mensual = [float(x) for x in self.edit_of_etp_mensual.text().split(",") if x.strip()]
            if not p_mensual or not etp_mensual:
                QMessageBox.warning(self, "Faltan datos", "Ingrese las series mensuales de P y PET separadas por coma.")
                return
            if indice_modelo == 1:
                r = water_yield.balance_mensual_simplificado(p_mensual, etp_mensual, self.spin_of_x1.value(), self.spin_of_x2.value())
                poblar_tabla_parametros(self.tabla_resultado_oferta, [
                    ("Caudal medio mensual", r["caudal_medio_mensual_mm"], "mm"),
                    ("Caudal mensual", str(r["caudal_mensual_mm"]), "mm", r["nota"]),
                ])
            else:
                r = water_yield.balance_lutz_scholz(p_mensual, etp_mensual, self.spin_of_a.value(),
                                                     self.spin_of_b.value(), self.spin_of_area.value())
                poblar_tabla_parametros(self.tabla_resultado_oferta, [
                    ("Caudal medio", r["caudal_medio_m3s"], "m³/s"),
                    ("Persistencia", str(r["persistencia"]), ""),
                    ("Caudal mensual", str(r["caudal_mensual_m3s"]), "m³/s", r["nota"]),
                ])
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
        self.texto_resumen_socavacion = ResumenFinal()
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
        self.texto_resumen_suelo = ResumenFinal()
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
        self.texto_resumen_sedimentos = ResumenFinal()
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
        self.texto_resumen_flujo = ResumenFinal()
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
        self.texto_marco_cmip6 = ResumenFinal()
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
        self.texto_resumen_cc = ResumenFinal()
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
    # ------------------------------------------------------------------
    # Regionalización y validación de productos grillados (Pestaña 15)
    # ------------------------------------------------------------------
    def _leer_tabla_numerica(self, tabla, columnas_texto=(0,)):
        """
        Lee una TablaPegable devolviendo una lista de filas. Las columnas
        indicadas en `columnas_texto` se conservan como cadena (nombres) y
        el resto se convierte a float; las filas incompletas se omiten en
        vez de propagar un None que reventaría el cálculo más adelante.
        """
        filas = []
        for i in range(tabla.rowCount()):
            fila, completa = [], True
            for j in range(tabla.columnCount()):
                item = tabla.item(i, j)
                texto = item.text().strip() if item else ""
                if not texto:
                    completa = False
                    break
                if j in columnas_texto:
                    fila.append(texto)
                else:
                    try:
                        fila.append(float(texto.replace(",", ".")))
                    except ValueError:
                        completa = False
                        break
            if completa and fila:
                filas.append(fila)
        return filas

    def _on_regionalizar(self):
        filas = self._leer_tabla_numerica(self.tabla_regionalizacion)
        # regresion_regionalizacion() exige n >= k+3 estaciones; con una
        # covariable eso son 4. Se avisa aquí con un mensaje entendible
        # en vez de dejar que salte la excepción del módulo de cálculo.
        if len(filas) < 4:
            QMessageBox.warning(
                self, "Faltan estaciones",
                "Se necesitan al menos 4 estaciones completas (estación, variable, covariable, X, Y) "
                "para ajustar la regresión con una incertidumbre mínimamente estimable.")
            return
        try:
            nombres = [f[0] for f in filas]
            valores = [f[1] for f in filas]
            covariable = [f[2] for f in filas]
            coordenadas = {f[0]: (f[3], f[4]) for f in filas}
            if len(coordenadas) != len(nombres):
                QMessageBox.warning(self, "Estaciones repetidas",
                                    "Hay nombres de estación duplicados; cada estación debe tener un "
                                    "nombre único.")
                return

            corr = regionalization.correlacion_con_covariable(valores, covariable)
            modelo = regionalization.regresion_regionalizacion(
                valores, {"covariable": covariable}, nombres)

            puntos = self._leer_tabla_numerica(self.tabla_puntos_regionalizacion)
            con_idw = bool(puntos) and self.check_correccion_residual.isChecked()
            valores_puntos, detalle_puntos = [], []
            if puntos:
                cov_puntos = {"covariable": [p[1] for p in puntos]}
                if con_idw:
                    salida = regionalization.regionalizar_con_correccion_residual(
                        valores, {"covariable": covariable}, coordenadas, nombres,
                        cov_puntos, [(p[2], p[3]) for p in puntos])
                    detalle_puntos = salida["resultados_por_punto"]
                    valores_puntos = [d["valor_regionalizado"] for d in detalle_puntos]
                else:
                    valores_puntos = regionalization.predecir_en_puntos(modelo, cov_puntos)

            self.regionalizacion_resultado = {"correlacion": corr, "modelo": modelo,
                                               "puntos": valores_puntos,
                                               "detalle_puntos": detalle_puntos}

            r = corr["r"]
            p_val = corr["p_valor"]
            significativa = corr["significativa_alpha_0_05"]
            r2 = modelo["r2"]

            filas_res = [
                ("Estaciones usadas", modelo["n_estaciones"], ""),
                ("Correlación de Pearson r", r, "", f"t = {corr['t']}"),
                ("p-valor de la correlación", p_val, "",
                 "significativa (α=0.05)" if significativa else "NO significativa (α=0.05)"),
                ("R² de la regresión", r2, "", modelo["nota_r2"]),
            ]
            for coef in modelo["coeficientes"]:
                filas_res.append((
                    f"Coeficiente — {coef['termino']}", coef["coeficiente"], "",
                    f"IC 95%: [{coef['ic_95_inferior']}, {coef['ic_95_superior']}]  "
                    f"(error std {coef['error_std']})"))
            for nombre in nombres:
                res = modelo["residuos"][nombre]
                filas_res.append((
                    f"Residuo — {nombre}", res["residuo"], "mm",
                    f"observado {res['observado']} vs. predicho {res['predicho']}"
                    + (f"  ·  estandarizado {res['residuo_estandarizado']}"
                       if res["residuo_estandarizado"] is not None else "")))
            for i, valor_pt in enumerate(valores_puntos):
                nombre_pt = puntos[i][0]
                if con_idw:
                    d = detalle_puntos[i]
                    comentario = (f"tendencia {d['tendencia_regresion']} "
                                  f"+ corrección IDW {d['correccion_residual_idw']}")
                else:
                    comentario = "solo tendencia de la regresión (sin corrección de residuos)"
                filas_res.append((f"Estimación — {nombre_pt}", valor_pt, "mm", comentario))
            poblar_tabla_parametros(self.tabla_resultado_regionalizacion, filas_res,
                                     filas_visibles_max=24)

            self.cuadro_regionalizacion.actualizar(
                titulo="REGIONALIZACIÓN FRENTE A LA COVARIABLE",
                valor_principal=f"r = {r:.4f}      R² = {r2:.4f}",
                subtitulo=f"{modelo['n_estaciones']} estaciones"
                           + (f" · {len(valores_puntos)} punto(s) estimado(s)"
                              if valores_puntos else " · sin puntos a estimar"),
                metricas=[("Estaciones", str(modelo["n_estaciones"])),
                           ("p-valor", f"{p_val:.4f}"),
                           ("Corrección IDW", "sí" if con_idw else "no"),
                           ("Puntos estimados", str(len(valores_puntos)))],
                leyenda=("Relación significativa (p < 0.05): la covariable explica parte de la "
                          "variación espacial y el modelo puede usarse para estimar en puntos sin "
                          "estación, dentro del rango de covariable observado."
                          if significativa else
                          "Relación NO significativa (p ≥ 0.05): la covariable no explica la "
                          "variación entre estaciones. Considere dividir en subregiones más "
                          "homogéneas (p.ej. por vertiente) antes de extrapolar."),
                tipo="exito" if significativa else "atencion")

            self.canvas_regionalizacion.plot_regionalizacion(
                covariable, valores, nombres, modelo,
                puntos_covariable=[p[1] for p in puntos] if puntos else None,
                puntos_valores=valores_puntos or None,
                puntos_nombres=[p[0] for p in puntos] if puntos else None,
                etiqueta_covariable="Covariable (p.ej. altitud, m s.n.m.)",
                etiqueta_variable="Variable regionalizada (mm)")
        except Exception as e:
            QMessageBox.critical(self, "Error en la regionalización", str(e))

    def _on_validar_grillada(self):
        filas = self._leer_tabla_numerica(self.tabla_validacion_grillada, columnas_texto=())
        if len(filas) < 5:
            QMessageBox.warning(
                self, "Faltan datos",
                "Se necesitan al menos 5 pares (producto grillado, estación) para calcular métricas "
                "con sentido.")
            return
        try:
            sim = [f[0] for f in filas]
            obs = [f[1] for f in filas]
            salida = gridded_validation.validar_serie_gridded_vs_estacion(
                sim, obs, umbral_deteccion_mm=self.spin_umbral_deteccion.value())
            self.validacion_grillada_resultado = salida

            cont = salida["metricas_continuas"]
            cat = salida["metricas_categoricas"]
            nse, pbias = cont["NSE"], cont["PBIAS_pct"]
            clasif = cont["desempeno_moriasi_2007"]

            filas_res = [("Pares válidos comparados", cont["n_pares"], "",
                           "exclusión pareada: se descartan los pasos sin dato en alguna de las series")]
            etiquetas = [
                ("NSE", "", "Nash-Sutcliffe: 1 = perfecto; 0 = igual que usar la media observada"),
                ("KGE", "", "Kling-Gupta: combina correlación, variabilidad y sesgo"),
                ("KGE_r_correlacion", "", "componente r del KGE"),
                ("KGE_alpha_variabilidad", "", "componente α: >1 el grillado es más variable"),
                ("KGE_beta_sesgo", "", "componente β: >1 el grillado sobreestima el volumen"),
                ("PBIAS_pct", "%", "sesgo porcentual: positivo = el grillado sobreestima"),
                ("RMSE", "mm", "error cuadrático medio, en unidades de la variable"),
                ("MAE", "mm", "error absoluto medio"),
                ("R_pearson", "", "correlación lineal grillado-estación"),
                ("R2", "", "coeficiente de determinación"),
            ]
            for clave, unidad, desc in etiquetas:
                if cont.get(clave) is not None:
                    filas_res.append((clave.replace("_", " "), cont[clave], unidad, desc))
            filas_res.append(("Clasificación de desempeño", clasif, "",
                               "bandas de Moriasi et al. (2007) sobre NSE y PBIAS"))

            tabla_cont = cat["tabla_contingencia"]
            filas_res.append(("Umbral de día con lluvia", cat["umbral_mm"], "mm",
                               "1.0 mm/día es el umbral estándar en validación de productos satelitales"))
            for clave, etiqueta in (("aciertos_hits", "Aciertos (hits)"),
                                     ("falsas_alarmas", "Falsas alarmas"),
                                     ("fallos_misses", "Fallos (misses)"),
                                     ("correctos_sin_lluvia", "Correctos sin lluvia")):
                filas_res.append((etiqueta, tabla_cont[clave], "pasos", ""))
            for clave, desc in (("POD", "probabilidad de detección: fracción de días con lluvia acertados"),
                                 ("FAR", "falsas alarmas: lluvia detectada que no ocurrió (0 = ideal)"),
                                 ("FBI", "sesgo de frecuencia: >1 sobre-detecta días de lluvia"),
                                 ("HSS", "destreza frente al acierto esperado por azar")):
                if cat.get(clave) is not None:
                    filas_res.append((clave, cat[clave], "", desc))
            poblar_tabla_parametros(self.tabla_resultado_validacion, filas_res,
                                     filas_visibles_max=26)

            # El color comunica la decisión práctica: NSE es el criterio
            # más extendido para aceptar o rechazar una serie grillada.
            tipo = "alerta"
            if nse is not None:
                tipo = "exito" if nse > 0.5 else ("atencion" if nse > 0.0 else "alerta")
            self.cuadro_validacion_grillada.actualizar(
                titulo="VALIDACIÓN DEL PRODUCTO GRILLADO",
                valor_principal=f"NSE = {nse:.4f}" if nse is not None else "NSE no calculable",
                subtitulo=f"Desempeño: {clasif}",
                metricas=[("KGE", f"{cont['KGE']:.4f}" if cont.get("KGE") is not None else "—"),
                           ("PBIAS", f"{pbias:.2f} %" if pbias is not None else "—"),
                           ("RMSE", f"{cont['RMSE']:.2f} mm"),
                           ("POD", f"{cat['POD']:.3f}" if cat.get("POD") is not None else "—"),
                           ("FAR", f"{cat['FAR']:.3f}" if cat.get("FAR") is not None else "—")],
                leyenda=("NSE > 0.5: el producto reproduce aceptablemente la serie observada y puede "
                          "usarse donde no hay estación, revisando además POD/FAR."
                          if tipo == "exito" else
                          ("NSE entre 0 y 0.5: mejor que usar la media observada, pero con reservas "
                           "para diseño; contrástelo con el PBIAS antes de emplearlo."
                           if tipo == "atencion" else
                           "NSE ≤ 0: el producto NO es mejor que usar la media observada. No lo use "
                           "sin corrección de sesgo previa.")),
                tipo=tipo)

            self.canvas_validacion_grillada.plot_validacion(sim, obs, cont, cat)
        except Exception as e:
            QMessageBox.critical(self, "Error en la validación", str(e))

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
        self.texto_resumen_qm = ResumenFinal()
        v.addWidget(self.texto_resumen_qm)

        self._on_cambiar_modelo_qm(self.combo_modelo_qm.currentText())
        self._agregar_pestaña_con_scroll(tab, "16. Caudales Medios (Qm)")

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
        self.texto_resumen_minimos = ResumenFinal()
        v.addWidget(self.texto_resumen_minimos)

        self._agregar_pestaña_con_scroll(tab, "17. Caudales Mínimos")

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
        self.texto_resumen_phabsim = ResumenFinal()
        v.addWidget(self.texto_resumen_phabsim)

        self._agregar_pestaña_con_scroll(tab, "18. Caudal Ecológico - PHABSIM")

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
        self.texto_resumen_flujo_subterraneo = ResumenFinal()
        v.addWidget(self.texto_resumen_flujo_subterraneo)

        self._agregar_pestaña_con_scroll(tab, "19. Flujo Subterráneo")

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
        self.texto_resumen_pozo = ResumenFinal()
        v.addWidget(self.texto_resumen_pozo)

        self._agregar_pestaña_con_scroll(tab, "20. Hidráulica de Pozos")

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

        gb_plantilla = QGroupBox(
            "Reporte Word con plantilla — elija qué secciones incluir (docxtpl)"
        )
        v_p = QVBoxLayout(gb_plantilla)
        v_p.addWidget(QLabel(
            "A diferencia del botón de arriba (que siempre arma las 7 secciones, con una nota si "
            "alguna aún no se calculó), aquí puede elegir cuáles incluir: las que no marque no "
            "aparecen en el documento. Usa la misma información y una plantilla Word editable "
            "(hydroandina_pro/resources/plantilla_reporte.docx) en vez de un documento armado desde "
            "cero, para poder ajustar membrete/estilos corporativos sin tocar el código del plugin."
        ))
        self.checks_secciones_reporte = {}
        grid_secciones = QGridLayout()
        for i, (clave, titulo, _funcion) in enumerate(report_generator.SECCIONES_REPORTE):
            check = QCheckBox(titulo)
            check.setChecked(True)
            self.checks_secciones_reporte[clave] = check
            grid_secciones.addWidget(check, i // 2, i % 2)
        v_p.addLayout(grid_secciones)
        self.btn_generar_reporte_word_plantilla = QPushButton(
            "Generar reporte Word con plantilla (secciones marcadas)"
        )
        self.btn_generar_reporte_word_plantilla.clicked.connect(self._on_generar_reporte_word_plantilla)
        v_p.addWidget(self.btn_generar_reporte_word_plantilla)
        v.addWidget(gb_plantilla)

        v.addStretch()
        self._agregar_pestaña_con_scroll(tab, "21. Exportar / Reportes")

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
            "recomendacion_hidraulica_texto": self._texto_plano_desde_html(
                self.lbl_recomendacion_hidraulica.text()
            ) if hasattr(self, "lbl_recomendacion_hidraulica") else None,
            "rutas_imagenes": rutas_imagenes,
        }

    def _texto_plano_desde_html(self, html: str) -> str:
        """Convierte el HTML simple (negritas, <br>) de un QLabel a texto
        plano con saltos de línea, para insertarlo como párrafos en el
        reporte Word (Word no debe mostrar etiquetas HTML literales)."""
        import re
        texto = re.sub(r"<br\s*/?>", "\n", html)
        texto = re.sub(r"<[^>]+>", "", texto)
        return texto.strip()

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

    def _on_generar_reporte_word_plantilla(self):
        secciones_incluidas = [clave for clave, check in self.checks_secciones_reporte.items()
                                if check.isChecked()]
        if not secciones_incluidas:
            QMessageBox.warning(self, "Ninguna sección marcada",
                                 "Marque al menos una sección para incluir en el reporte.")
            return
        ruta, _ = QFileDialog.getSaveFileName(self, "Guardar reporte Word (con plantilla)",
                                               "reporte_hydroandina_pro.docx", "Documento Word (*.docx)")
        if not ruta:
            return
        try:
            carpeta_tmp = tempfile.mkdtemp(prefix="hydroandina_reporte_")
            contexto = self._construir_contexto_reporte(carpeta_tmp)
            report_generator_docxtpl.generar_reporte_word_plantilla(ruta, contexto, secciones_incluidas)
            QMessageBox.information(self, "Reporte generado", f"Reporte Word guardado en:\n{ruta}")
        except report_generator.ReportGeneratorError as e:
            QMessageBox.warning(self, "No se pudo generar el reporte", str(e))
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
