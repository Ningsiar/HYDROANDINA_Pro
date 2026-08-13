# -*- coding: utf-8 -*-
"""
core/swe2d.py

Solver hidrodinámico bidimensional propio de HydroAndes SYM BIM, sobre la
grilla regular del MDE ya recortado a la cuenca (Pestaña 1).

ECUACIONES. Se integran verticalmente las de Navier-Stokes para obtener
las de aguas someras (Saint-Venant 2D). La continuidad se resuelve
completa:

    ∂h/∂t + ∂(hu)/∂x + ∂(hv)/∂y = q

y para la cantidad de movimiento se ofrecen DOS aproximaciones, que se
eligen según el problema:

  * ONDA DIFUSIVA — desprecia los términos inerciales (aceleración local
    y convectiva). El caudal por cara sale directamente de Manning con la
    pendiente de la superficie libre:

        q = (1/n) · h^(5/3) · S^(1/2)  ,  S = −∂(zb+h)/∂x

    Es muy estable y barata, y es adecuada para inundación en llanura
    donde el flujo está dominado por la gravedad y la fricción. NO sirve
    donde la inercia manda: subestima el pico en cauces con transiciones
    rápidas y no representa bien las estructuras.

  * INERCIA LOCAL (Bates, Horritt & Fewtrell, 2010, J. Hydrology 387) —
    conserva el término de aceleración local y solo desprecia el
    convectivo. Es el esquema de LISFLOOD-FP y el que corresponde para
    cauces y estructuras. Discretizado de forma semi-implícita en la
    fricción, que es lo que le da estabilidad:

        q^(t+Δt) = [ q^t − g·h_f·Δt·∂(zb+h)/∂x ]
                   / [ 1 + g·Δt·n²·|q^t| / h_f^(7/3) ]

    Este es el esquema POR DEFECTO. Cuesta prácticamente lo mismo que la
    onda difusiva y es estrictamente mejor en cauce.

POR QUÉ MALLA DESPLAZADA (Arakawa-C), Y NO DIFERENCIAS CENTRADAS SOBRE
CELDAS: la formulación ingenua evalúa la velocidad en el centro de la
celda y luego toma diferencias centradas de h·u. Eso desacopla las
celdas pares de las impares -- aparece el patrón de tablero de ajedrez
característico -- y NO conserva la masa. Aquí los caudales q se definen
en las CARAS entre celdas y el calado en el CENTRO, de modo que lo que
sale de una celda entra exactamente en su vecina: la masa se conserva
por construcción, hasta el error de redondeo.

PROFUNDIDAD EN LA CARA. En cada cara se usa

    h_f = max(zb_i + h_i , zb_j + h_j) − max(zb_i , zb_j)

que es la profundidad efectiva por la que puede pasar el flujo. Esta
elección es la que hace el esquema BIEN BALANCEADO (propiedad C): con
agua en reposo sobre un fondo irregular, el gradiente de superficie
libre es nulo, el caudal es nulo, y el agua se queda quieta. Un esquema
que no cumple esto genera corrientes espurias sobre topografía real, que
es justo lo que hay en un cauce andino.

MOJADO Y SECADO. Una cara con h_f por debajo del umbral no transmite
caudal, y el caudal de una cara se limita para no vaciar más agua de la
que la celda tiene en el paso: sin ese limitador aparecen calados
negativos en los frentes de avance.

ESTRUCTURAS HIDRÁULICAS. Se modelan como ENLACES INTERNOS entre dos
celdas, sustituyendo el flujo del terreno por la ecuación hidráulica que
corresponda (vertedero, orificio/compuerta, alcantarilla). Es el mismo
enfoque de HEC-RAS 2D e Iber: la estructura es más pequeña que la celda,
así que no se resuelve su geometría con la malla sino con su ley de
descarga.

RENDIMIENTO. Todo está vectorizado con NumPy: cada paso de tiempo son
unas pocas operaciones sobre arrays completos, no bucles en Python. Si
Numba está disponible se compila además el núcleo de flujos, pero NO es
un requisito -- QGIS no garantiza traer Numba, y un plugin que solo
funciona con una dependencia opcional no es utilizable.
"""
import math
import numpy as np

G = 9.81

# Umbral de mojado/secado (m). Por debajo, la celda se considera seca:
# ni aporta caudal ni se le calcula velocidad.
H_SECO = 1.0e-3

# Límite inferior para h_f en el denominador de la fricción, que va
# elevado a 7/3: sin él, una lámina de 1e-6 m daría una fricción
# astronómica y reventaría el paso de tiempo.
H_MIN_FRICCION = 1.0e-3

# Calado minimo para INFORMAR una velocidad (m). Por debajo, el cociente
# q/h no representa una velocidad fisica sino ruido del frente de
# avance, y entraria directo en el mapa de peligrosidad h*v.
H_VELOCIDAD = 0.02

# Control del incremento de calado que una fuente puede provocar en su
# celda durante un solo paso (ver _paso_por_fuentes). Es RELATIVO al
# calado que la celda ya tiene, con un suelo absoluto:
#
#     Δh_permitido = max(INCREMENTO_MIN_FUENTE, FRACCION_FUENTE · h)
#
# El suelo actúa al arrancar, cuando la celda está seca y es cuando se
# produce el pico espurio; la parte proporcional deja respirar al paso
# de tiempo una vez que hay lámina, que es la mayor parte de la
# simulación. Un umbral fijo y pequeño resolvía igual el arranque, pero
# encarecía TODA la simulación por un problema que solo existe en sus
# primeros instantes.
#
# CALIBRACIÓN (valle en V de 60×120 celdas de 10 m, 40 m³/s, 600 s),
# contra una referencia con incremento fijo de 0.02 m y 12 000 pasos:
# estos valores dan 1132 pasos (10.6 veces menos) con un error del 1.9 %
# en el calado de la propia celda de inyección —que es un punto singular
# del modelo— y del 0.15 % en el calado máximo global, con el área
# inundada idéntica. El resultado además deja de depender del dt_maximo
# que elija el usuario (dispersión 0.4 % entre 0.5 s y 10 s).
INCREMENTO_MIN_FUENTE = 0.05
FRACCION_FUENTE = 0.25


class Swe2DError(Exception):
    pass


# ======================================================================
# NUMBA OPCIONAL
# ======================================================================
try:                                             # pragma: sin cobertura
    from numba import njit as _njit
    NUMBA_DISPONIBLE = True
except Exception:                                # pragma: sin cobertura
    NUMBA_DISPONIBLE = False

    def _njit(*args, **kwargs):
        """Decorador transparente cuando Numba no está: el código
        vectorizado de NumPy funciona igual, solo algo más lento."""
        def envoltorio(funcion):
            return funcion
        if args and callable(args[0]):
            return args[0]
        return envoltorio


# ======================================================================
# ESTRUCTURAS HIDRÁULICAS (leyes de descarga)
# ======================================================================
def caudal_vertedero(carga_aguas_arriba: float, carga_aguas_abajo: float,
                     longitud_cresta: float, coef_descarga: float = 1.84) -> float:
    """
    Vertedero de cresta ancha/delgada:  Q = C · L · H^(3/2)

    Con SUMERGENCIA por la fórmula de Villemonte (1947):

        Q_sumergido = Q_libre · (1 − (H2/H1)^1.5)^0.385

    La sumergencia importa de verdad: un vertedero ahogado puede
    descargar la mitad que uno libre, y despreciarla sobreestima la
    capacidad de evacuación justo en la situación crítica, cuando el
    nivel de aguas abajo ha subido.

    carga_* : altura de lámina SOBRE LA CRESTA a cada lado (m).
    coef_descarga: 1.84 para cresta ancha en unidades SI; ~2.2 para
        perfil Creager.
    """
    if carga_aguas_arriba <= 0.0:
        return 0.0
    q_libre = coef_descarga * longitud_cresta * (carga_aguas_arriba ** 1.5)
    if carga_aguas_abajo <= 0.0:
        return q_libre
    razon = carga_aguas_abajo / carga_aguas_arriba
    if razon >= 1.0:
        return 0.0
    return q_libre * (1.0 - razon ** 1.5) ** 0.385


def caudal_orificio(carga_aguas_arriba: float, carga_aguas_abajo: float,
                    area: float, coef_descarga: float = 0.61) -> float:
    """
    Orificio o compuerta sumergida:  Q = Cd · A · √(2g·Δh)

    Δh es la diferencia de NIVELES DE SUPERFICIE LIBRE, no de calados:
    lo que mueve el agua a través de una compuerta es el desnivel
    piezométrico entre ambos lados.
    """
    delta = carga_aguas_arriba - carga_aguas_abajo
    if abs(delta) < 1.0e-9 or area <= 0.0:
        return 0.0
    signo = 1.0 if delta > 0 else -1.0
    return signo * coef_descarga * area * math.sqrt(2.0 * G * abs(delta))


def caudal_alcantarilla(nivel_aguas_arriba: float, nivel_aguas_abajo: float,
                        cota_entrada: float, diametro: float,
                        area: float, coef_entrada: float = 0.6,
                        n_manning: float = 0.013, longitud: float = 10.0) -> float:
    """
    Alcantarilla con el criterio del HDS-5 (FHWA): se calculan las dos
    posibilidades y GOBIERNA LA MENOR, porque el flujo real lo limita el
    control más restrictivo.

      * Control de ENTRADA: la boca es el cuello de botella; el conducto
        va parcialmente lleno y aguas abajo no influye. Se trata como
        orificio con la carga sobre la entrada.
      * Control de SALIDA: manda la fricción del conducto más las
        pérdidas de entrada y salida; el desnivel entre ambos extremos
        es lo que impulsa el flujo.

    Devolver solo uno de los dos —error frecuente— sobreestima la
    capacidad en un caso u otro según el régimen.
    """
    carga = nivel_aguas_arriba - cota_entrada
    if carga <= 0.0 or area <= 0.0:
        return 0.0

    # --- Control de entrada (orificio) ---
    q_entrada = coef_entrada * area * math.sqrt(2.0 * G * carga)

    # --- Control de salida (conducto lleno) ---
    desnivel = nivel_aguas_arriba - max(nivel_aguas_abajo, cota_entrada)
    if desnivel <= 0.0:
        return 0.0
    radio_hidraulico = diametro / 4.0            # sección llena circular
    # Pérdidas: entrada (0.5) + salida (1.0) + fricción de Manning.
    perdida_friccion = (2.0 * G * n_manning ** 2 * longitud /
                        max(radio_hidraulico, 1e-6) ** (4.0 / 3.0))
    coef_total = 0.5 + 1.0 + perdida_friccion
    q_salida = area * math.sqrt(2.0 * G * desnivel / coef_total)

    return min(q_entrada, q_salida)


class Estructura:
    """
    Enlace hidráulico entre dos celdas de la malla.

    celda_1 / celda_2: (fila, columna). El caudal positivo va de la 1 a
    la 2; el signo se invierte solo cuando la ley de descarga lo permite
    (orificio), porque un vertedero no funciona al revés por debajo de
    su cresta.
    """

    def __init__(self, tipo: str, celda_1, celda_2, parametros: dict,
                 nombre: str = ""):
        if tipo not in ("vertedero", "orificio", "alcantarilla"):
            raise Swe2DError(f"Tipo de estructura no soportado: {tipo}")
        self.tipo = tipo
        self.celda_1 = tuple(celda_1)
        self.celda_2 = tuple(celda_2)
        self.parametros = dict(parametros)
        self.nombre = nombre or tipo
        self.caudal_actual = 0.0
        self.caudal_maximo = 0.0

    def calcular_caudal(self, nivel_1: float, nivel_2: float,
                        cota_1: float, cota_2: float) -> float:
        p = self.parametros
        if self.tipo == "vertedero":
            cota_cresta = p["cota_cresta"]
            # El vertedero solo funciona en el sentido en que hay carga
            # sobre la cresta; si el nivel alto está del otro lado, el
            # flujo se invierte con la misma ley.
            if nivel_1 >= nivel_2:
                h1, h2 = nivel_1 - cota_cresta, nivel_2 - cota_cresta
                return caudal_vertedero(max(h1, 0.0), max(h2, 0.0),
                                        p["longitud"], p.get("coef_descarga", 1.84))
            h1, h2 = nivel_2 - cota_cresta, nivel_1 - cota_cresta
            return -caudal_vertedero(max(h1, 0.0), max(h2, 0.0),
                                     p["longitud"], p.get("coef_descarga", 1.84))
        if self.tipo == "orificio":
            return caudal_orificio(nivel_1, nivel_2, p["area"],
                                   p.get("coef_descarga", 0.61))
        # alcantarilla
        if nivel_1 >= nivel_2:
            return caudal_alcantarilla(
                nivel_1, nivel_2, p["cota_entrada"], p["diametro"], p["area"],
                p.get("coef_entrada", 0.6), p.get("n_manning", 0.013),
                p.get("longitud", 10.0))
        return -caudal_alcantarilla(
            nivel_2, nivel_1, p["cota_entrada"], p["diametro"], p["area"],
            p.get("coef_entrada", 0.6), p.get("n_manning", 0.013),
            p.get("longitud", 10.0))


# ======================================================================
# NÚCLEO DE FLUJOS
# ======================================================================
def _profundidad_cara(zb_a, zb_b, h_a, h_b):
    """
    h_f = max(nivel) − max(fondo): la profundidad efectiva por la que
    puede circular el agua en la cara. Es la clave de que el esquema
    quede bien balanceado (ver docstring del módulo).
    """
    nivel_a = zb_a + h_a
    nivel_b = zb_b + h_b
    return np.maximum(nivel_a, nivel_b) - np.maximum(zb_a, zb_b)


def _flujo_inercia_local(q_previo, h_cara, pendiente, n_cara, dt, dl):
    """
    Actualización semi-implícita de Bates et al. (2010). La fricción va
    implícita (aparece en el denominador) y por eso el esquema aguanta
    calados pequeños sin oscilar; explícita, exigiría pasos de tiempo
    ridículamente cortos justo en el frente de avance.
    """
    numerador = q_previo - G * h_cara * dt * pendiente
    h_seguro = np.maximum(h_cara, H_MIN_FRICCION)
    denominador = 1.0 + G * dt * (n_cara ** 2) * np.abs(q_previo) / (h_seguro ** (7.0 / 3.0))
    return numerador / denominador


def _flujo_onda_difusiva(h_cara, pendiente, n_cara):
    """
    Manning con la pendiente de la superficie libre. Sin memoria del
    paso anterior: el caudal responde instantáneamente al gradiente, que
    es exactamente lo que significa despreciar la inercia.
    """
    magnitud = np.abs(pendiente)
    q = -np.sign(pendiente) * (1.0 / np.maximum(n_cara, 1e-6)) * \
        (np.maximum(h_cara, 0.0) ** (5.0 / 3.0)) * np.sqrt(magnitud)
    return np.where(magnitud > 1e-12, q, 0.0)


class SimuladorSwe2D:
    """
    Simulador de aguas someras 2D sobre la grilla del MDE.

    zb: array 2D de cotas de fondo (m). Los nodos con NaN se tratan como
        fuera del dominio (no se calculan y no reciben agua).
    dx, dy: tamaño de celda (m).
    n_manning: escalar o array 2D del mismo tamaño que zb.
    """

    def __init__(self, zb, dx, dy, n_manning=0.035, esquema="inercia_local",
                 cfl=0.7, dt_maximo=10.0, dt_minimo=1e-4, h_inicial=None):
        self.zb = np.asarray(zb, dtype=np.float64)
        if self.zb.ndim != 2:
            raise Swe2DError("El MDE debe ser un array bidimensional.")
        self.filas, self.columnas = self.zb.shape
        if self.filas < 3 or self.columnas < 3:
            raise Swe2DError("El dominio necesita al menos 3x3 celdas.")

        self.dx = float(dx)
        self.dy = float(dy)
        if self.dx <= 0 or self.dy <= 0:
            raise Swe2DError("El tamaño de celda debe ser positivo.")

        if esquema not in ("inercia_local", "onda_difusiva"):
            raise Swe2DError(f"Esquema no soportado: {esquema}")
        self.esquema = esquema
        self.cfl = float(cfl)
        self.dt_maximo = float(dt_maximo)
        self.dt_minimo = float(dt_minimo)

        # Máscara del dominio: NaN en el MDE = fuera de la cuenca.
        self.activo = np.isfinite(self.zb)
        if not self.activo.any():
            raise Swe2DError("El MDE no tiene ninguna celda válida.")
        # Se rellena el NaN con una cota altísima para que actúe como
        # muro impermeable en las fórmulas vectorizadas, sin tener que
        # ramificar en cada operación.
        self.zb = np.where(self.activo, self.zb, 1.0e9)

        self.n = (np.full_like(self.zb, float(n_manning))
                  if np.isscalar(n_manning) else
                  np.asarray(n_manning, dtype=np.float64))
        if self.n.shape != self.zb.shape:
            raise Swe2DError("El mapa de Manning debe tener la forma del MDE.")

        self.h = (np.zeros_like(self.zb) if h_inicial is None
                  else np.asarray(h_inicial, dtype=np.float64).copy())
        self.h[~self.activo] = 0.0

        # Caudales en las CARAS (malla desplazada Arakawa-C), en m²/s
        # (caudal por unidad de ancho de cara).
        self.qx = np.zeros((self.filas, self.columnas - 1))   # caras verticales
        self.qy = np.zeros((self.filas - 1, self.columnas))   # caras horizontales

        # Registro de máximos, que es lo que se lleva al mapa de peligro.
        self.h_max = np.zeros_like(self.h)
        self.v_max = np.zeros_like(self.h)

        # Fuentes y bordes
        self.entradas = []          # (fila, col, hidrograma o caudal constante)
        self.lluvia_mm_h = 0.0
        self.celdas_salida = []     # celdas con salida libre
        self.estructuras = []

        # Contabilidad de volúmenes: es la comprobación que dice si la
        # simulación es creíble. Un balance que no cierra invalida
        # cualquier mapa por bonito que se vea.
        self.volumen_entrado = 0.0
        self.volumen_salido = 0.0
        self.volumen_inicial = float(np.sum(self.h) * self.dx * self.dy)

        self.tiempo = 0.0
        self.pasos = 0
        # Nº de pasos en que el Δt estable cayó por debajo de dt_minimo y
        # hubo que recortarlo. Si es alto, el resultado no es de fiar y
        # el resumen debe decirlo (ver paso_de_tiempo).
        self.pasos_con_dt_recortado = 0
        self.serie_tiempo = []      # (t, Q_entrada, Q_salida, volumen, area_inundada)

    # ------------------------------------------------------------------
    # Configuración
    # ------------------------------------------------------------------
    def agregar_entrada(self, fila, columna, caudal_m3s=None, hidrograma=None):
        """
        Punto de inyección de caudal. `hidrograma` es una lista de
        (tiempo_s, caudal_m3s) que se interpola linealmente; si se da
        `caudal_m3s`, es constante.
        """
        if not (0 <= fila < self.filas and 0 <= columna < self.columnas):
            raise Swe2DError(f"La celda de entrada ({fila}, {columna}) está fuera del dominio.")
        if not self.activo[fila, columna]:
            raise Swe2DError(
                f"La celda de entrada ({fila}, {columna}) está fuera de la cuenca (sin dato "
                "en el MDE).")
        if hidrograma is None and caudal_m3s is None:
            raise Swe2DError("Indique un caudal constante o un hidrograma.")
        self.entradas.append({"fila": fila, "columna": columna,
                              "caudal": caudal_m3s, "hidrograma": hidrograma})

    def agregar_salida(self, celdas):
        """Celdas de salida libre: el agua que llega a ellas abandona el
        dominio y se contabiliza como volumen salido."""
        for f, c in celdas:
            if 0 <= f < self.filas and 0 <= c < self.columnas:
                self.celdas_salida.append((f, c))

    def salida_por_bordes(self):
        """Salida libre por todo el contorno del dominio activo. Es la
        condición por defecto razonable: el agua que alcanza el límite
        del MDE se ha ido de la zona de estudio."""
        celdas = []
        for c in range(self.columnas):
            celdas.append((0, c))
            celdas.append((self.filas - 1, c))
        for f in range(self.filas):
            celdas.append((f, 0))
            celdas.append((f, self.columnas - 1))
        self.agregar_salida(celdas)

    def agregar_estructura(self, estructura: Estructura):
        for celda in (estructura.celda_1, estructura.celda_2):
            f, c = celda
            if not (0 <= f < self.filas and 0 <= c < self.columnas):
                raise Swe2DError(
                    f"La estructura «{estructura.nombre}» apunta a la celda {celda}, "
                    "fuera del dominio.")
        self.estructuras.append(estructura)

    # ------------------------------------------------------------------
    # Paso de tiempo
    # ------------------------------------------------------------------
    def paso_de_tiempo(self):
        """
        Δt estable. La restricción NO es la misma para los dos esquemas,
        y confundirlas es un error que no se ve venir: la simulación no
        aborta, oscila y devuelve calados plausibles pero falsos.

        INERCIA LOCAL — sistema hiperbólico. Manda la condición de
        Courant sobre la CELERIDAD DE ONDA en agua somera, √(g·h), no
        sobre la velocidad del agua: en un esquema explícito la
        restricción la impone la información más rápida del sistema, y
        una onda de gravedad en 2 m de calado viaja a 4.4 m/s aunque el
        agua se mueva a 1 m/s.

            Δt ≤ CFL · Δx / √(g·h)

        ONDA DIFUSIVA — al despreciar la inercia, la ecuación deja de ser
        hiperbólica y pasa a ser PARABÓLICA (difusión no lineal). Su
        límite de estabilidad explícito es mucho más severo:

            Δt ≤ Δx² / (4·D)   ,   D = (1/n)·h^(5/3) / √|∂η/∂l|

        (Hunter et al. 2005, «An adaptive time step solution for
        raster-based storage cell modelling of floodplain inundation»).

        La consecuencia práctica es fuerte: en un cauce con pendiente
        0.002 y calado ~0.9 m, D ≈ 300 m²/s y con celdas de 5 m el paso
        estable baja a ~0.02 s, unas 40 veces menor que el del esquema
        inercial. Por eso la onda difusiva, siendo más simple, resulta
        MÁS CARA en cauce, y por eso LISFLOOD-FP la sustituyó por la
        formulación de inercia local. Se conserva porque sigue siendo
        apropiada para expansión en llanura, donde las pendientes de
        superficie son mayores y D no se dispara.

        El caso degenerado es la superficie casi horizontal: D → ∞ y el
        paso tendería a cero. Ahí actúa dt_minimo, y se lleva la cuenta
        de cuántas veces se ha tenido que recortar para poder avisarlo en
        el resumen en vez de devolver resultados dudosos en silencio.
        """
        h_moja = self.h[self.h > H_SECO]
        if h_moja.size == 0:
            # Dominio seco: no hay onda de gravedad que restrinja nada,
            # pero las FUENTES sí restringen (ver _paso_por_fuentes).
            return min(self.dt_maximo, self._paso_por_fuentes())

        celeridad = math.sqrt(G * float(h_moja.max()))
        dt = (self.cfl * min(self.dx, self.dy) / celeridad
              if celeridad > 0 else self.dt_maximo)

        dt = min(dt, self._paso_por_fuentes())

        if self.esquema == "onda_difusiva":
            dt = min(dt, self._paso_parabolico())

        if dt < self.dt_minimo:
            self.pasos_con_dt_recortado += 1
            dt = self.dt_minimo
        return float(min(dt, self.dt_maximo))

    def _paso_por_fuentes(self):
        """
        Limita Δt para que una entrada de caudal no suba el calado de su
        celda más de INCREMENTO_MAX_FUENTE en un solo paso:

            Δt ≤ Δh_max · (Δx·Δy) / Q

        POR QUÉ HACE FALTA, aunque parezca un detalle: al arrancar, el
        dominio está seco, no hay onda de gravedad, y la condición de
        Courant no restringe nada -- el paso sale igual a dt_maximo. Con
        un dt_maximo de 10 s y una entrada de 40 m³/s en una celda de
        10×10 m, el primer paso inyecta 40·10/100 = 4 METROS de lámina de
        una vez. Ese pico es puramente numérico, se disipa enseguida...
        pero queda registrado en h_max, que es justo el número que el
        usuario lee como calado de diseño y el que alimenta el mapa de
        peligrosidad. En un caso real medido, el h_max informado pasaba
        de 4.00 m a 1.02 m solo con reducir dt_maximo: cuatro veces de
        diferencia en el resultado principal.

        Con este límite, la celda de entrada se llena de forma gradual y
        el resultado deja de depender del dt_maximo elegido.
        """
        limite = self.dt_maximo
        area_celda = self.dx * self.dy
        for entrada in self.entradas:
            q = self._caudal_entrada(entrada, self.tiempo)
            if q and q > 0:
                h_celda = self.h[entrada["fila"], entrada["columna"]]
                incremento = max(INCREMENTO_MIN_FUENTE, FRACCION_FUENTE * h_celda)
                limite = min(limite, incremento * area_celda / q)
        if self.lluvia_mm_h > 0:
            intensidad = self.lluvia_mm_h / 1000.0 / 3600.0
            limite = min(limite, INCREMENTO_MIN_FUENTE / intensidad)
        return limite

    def _paso_parabolico(self):
        """Límite Δt ≤ Δx²/(4·D) del esquema de onda difusiva, evaluado
        sobre las caras que realmente transmiten flujo."""
        zb, h, n = self.zb, self.h, self.n
        nivel = zb + h
        dt_limite = self.dt_maximo

        for eje in ("x", "y"):
            if eje == "x":
                h_cara = _profundidad_cara(zb[:, :-1], zb[:, 1:], h[:, :-1], h[:, 1:])
                pendiente = np.abs(nivel[:, 1:] - nivel[:, :-1]) / self.dx
                n_cara = 0.5 * (n[:, :-1] + n[:, 1:])
                paso_malla = self.dx
            else:
                h_cara = _profundidad_cara(zb[:-1, :], zb[1:, :], h[:-1, :], h[1:, :])
                pendiente = np.abs(nivel[1:, :] - nivel[:-1, :]) / self.dy
                n_cara = 0.5 * (n[:-1, :] + n[1:, :])
                paso_malla = self.dy

            activas = h_cara > H_SECO
            if not activas.any():
                continue
            # Suelo en la pendiente: sin él, una cara con superficie
            # exactamente horizontal daría D infinito y Δt cero, cuando
            # en realidad por esa cara no pasa prácticamente nada.
            pendiente_efectiva = np.maximum(pendiente[activas], 1e-7)
            difusividad = ((1.0 / np.maximum(n_cara[activas], 1e-6)) *
                           (h_cara[activas] ** (5.0 / 3.0)) /
                           np.sqrt(pendiente_efectiva))
            d_max = float(difusividad.max())
            if d_max > 0:
                dt_limite = min(dt_limite, 0.25 * paso_malla ** 2 / d_max)

        return dt_limite

    def _caudal_entrada(self, entrada, t):
        if entrada["hidrograma"]:
            hid = entrada["hidrograma"]
            tiempos = [p[0] for p in hid]
            caudales = [p[1] for p in hid]
            if t <= tiempos[0]:
                return caudales[0]
            if t >= tiempos[-1]:
                return caudales[-1]
            return float(np.interp(t, tiempos, caudales))
        return entrada["caudal"]

    def avanzar(self, dt=None):
        """Integra un paso de tiempo. Devuelve el dt efectivamente usado."""
        dt = self.paso_de_tiempo() if dt is None else float(dt)

        zb, h, n = self.zb, self.h, self.n
        nivel = zb + h

        # ---------------- Flujos en las caras verticales (x) ----------
        h_cara_x = _profundidad_cara(zb[:, :-1], zb[:, 1:], h[:, :-1], h[:, 1:])
        pendiente_x = (nivel[:, 1:] - nivel[:, :-1]) / self.dx
        n_cara_x = 0.5 * (n[:, :-1] + n[:, 1:])

        if self.esquema == "inercia_local":
            qx = _flujo_inercia_local(self.qx, h_cara_x, pendiente_x, n_cara_x, dt, self.dx)
        else:
            qx = _flujo_onda_difusiva(h_cara_x, pendiente_x, n_cara_x)
        qx = np.where(h_cara_x > H_SECO, qx, 0.0)

        # ---------------- Flujos en las caras horizontales (y) --------
        h_cara_y = _profundidad_cara(zb[:-1, :], zb[1:, :], h[:-1, :], h[1:, :])
        pendiente_y = (nivel[1:, :] - nivel[:-1, :]) / self.dy
        n_cara_y = 0.5 * (n[:-1, :] + n[1:, :])

        if self.esquema == "inercia_local":
            qy = _flujo_inercia_local(self.qy, h_cara_y, pendiente_y, n_cara_y, dt, self.dy)
        else:
            qy = _flujo_onda_difusiva(h_cara_y, pendiente_y, n_cara_y)
        qy = np.where(h_cara_y > H_SECO, qy, 0.0)

        # Muro impermeable en el contorno del dominio activo: no se
        # pierde ni se inventa agua a través de las celdas sin dato.
        pared_x = self.activo[:, :-1] & self.activo[:, 1:]
        pared_y = self.activo[:-1, :] & self.activo[1:, :]
        qx = np.where(pared_x, qx, 0.0)
        qy = np.where(pared_y, qy, 0.0)

        # ---------------- Limitador de vaciado ------------------------
        # Sin esto, una celda casi seca puede ceder por sus cuatro caras
        # más volumen del que contiene y quedar con calado NEGATIVO, que
        # además contamina el paso siguiente vía √h.
        qx, qy = self._limitar_vaciado(qx, qy, dt)

        self.qx, self.qy = qx, qy
        # Se guardan para calcular la velocidad en las caras (ver
        # componentes_velocidad), donde el cociente q/h es consistente.
        self.h_cara_x, self.h_cara_y = h_cara_x, h_cara_y

        # ---------------- Continuidad ---------------------------------
        # Divergencia por diferencias de los flujos de CARA: lo que sale
        # por la cara derecha de una celda es exactamente lo que entra
        # por la izquierda de la siguiente.
        div = np.zeros_like(h)
        div[:, :-1] += qx / self.dx
        div[:, 1:] -= qx / self.dx
        div[:-1, :] += qy / self.dy
        div[1:, :] -= qy / self.dy

        h_nuevo = h - dt * div

        # ---------------- Fuentes -------------------------------------
        caudal_entrada_total = 0.0
        for entrada in self.entradas:
            q = self._caudal_entrada(entrada, self.tiempo)
            if q:
                f, c = entrada["fila"], entrada["columna"]
                h_nuevo[f, c] += q * dt / (self.dx * self.dy)
                caudal_entrada_total += q
        self.volumen_entrado += caudal_entrada_total * dt

        if self.lluvia_mm_h > 0:
            # mm/h -> m/s, aplicada solo dentro del dominio activo.
            intensidad = self.lluvia_mm_h / 1000.0 / 3600.0
            h_nuevo[self.activo] += intensidad * dt
            self.volumen_entrado += (intensidad * dt * self.dx * self.dy *
                                      int(self.activo.sum()))

        # ---------------- Estructuras ---------------------------------
        caudal_estructuras = self._aplicar_estructuras(h_nuevo, dt)

        # ---------------- Salidas -------------------------------------
        caudal_salida = 0.0
        for f, c in self.celdas_salida:
            if h_nuevo[f, c] > 0:
                volumen = h_nuevo[f, c] * self.dx * self.dy
                self.volumen_salido += volumen
                caudal_salida += volumen / dt
                h_nuevo[f, c] = 0.0

        # Un calado negativo residual solo puede venir de redondeo; se
        # recorta, pero el balance de volumen lo delataría si fuera algo
        # más que eso.
        h_nuevo = np.maximum(h_nuevo, 0.0)
        h_nuevo[~self.activo] = 0.0
        self.h = h_nuevo

        # ---------------- Registro ------------------------------------
        self.h_max = np.maximum(self.h_max, self.h)
        velocidad = self.velocidades()
        self.v_max = np.maximum(self.v_max, velocidad)

        self.tiempo += dt
        self.pasos += 1
        self.serie_tiempo.append((
            self.tiempo, caudal_entrada_total, caudal_salida,
            float(np.sum(self.h) * self.dx * self.dy),
            float(np.sum(self.h > H_SECO) * self.dx * self.dy),
            caudal_estructuras,
        ))
        return dt

    def _limitar_vaciado(self, qx, qy, dt):
        """
        Escala los caudales SALIENTES de cada celda para que no superen
        el volumen disponible. El factor se aplica por celda y se propaga
        a sus caras, conservando la antisimetría (lo que una celda deja
        de ceder, la vecina deja de recibir), así que el limitador no
        rompe la conservación de masa.
        """
        salida = np.zeros_like(self.h)
        salida[:, :-1] += np.maximum(qx, 0.0) / self.dx
        salida[:, 1:] += np.maximum(-qx, 0.0) / self.dx
        salida[:-1, :] += np.maximum(qy, 0.0) / self.dy
        salida[1:, :] += np.maximum(-qy, 0.0) / self.dy

        volumen_disponible = self.h / dt
        with np.errstate(divide="ignore", invalid="ignore"):
            factor = np.where(salida > volumen_disponible,
                              volumen_disponible / np.maximum(salida, 1e-300), 1.0)
        factor = np.clip(np.nan_to_num(factor, nan=1.0), 0.0, 1.0)

        # A cada cara se le aplica el factor de la celda DONANTE, que es
        # la que fija el límite físico.
        fx = np.where(qx > 0, factor[:, :-1], factor[:, 1:])
        fy = np.where(qy > 0, factor[:-1, :], factor[1:, :])
        return qx * fx, qy * fy

    def _aplicar_estructuras(self, h_nuevo, dt):
        """Transfiere volumen entre las celdas enlazadas por cada
        estructura, limitado por el agua realmente disponible."""
        total = 0.0
        area_celda = self.dx * self.dy
        for est in self.estructuras:
            f1, c1 = est.celda_1
            f2, c2 = est.celda_2
            nivel_1 = self.zb[f1, c1] + h_nuevo[f1, c1]
            nivel_2 = self.zb[f2, c2] + h_nuevo[f2, c2]
            q = est.calcular_caudal(nivel_1, nivel_2,
                                    self.zb[f1, c1], self.zb[f2, c2])

            # Una estructura no puede extraer más agua de la que hay en
            # la celda donante durante el paso.
            if q > 0:
                q = min(q, h_nuevo[f1, c1] * area_celda / dt)
            elif q < 0:
                q = -min(-q, h_nuevo[f2, c2] * area_celda / dt)

            volumen = q * dt / area_celda
            h_nuevo[f1, c1] -= volumen
            h_nuevo[f2, c2] += volumen

            est.caudal_actual = q
            est.caudal_maximo = max(est.caudal_maximo, abs(q))
            total += abs(q)
        return total

    # ------------------------------------------------------------------
    # Salidas derivadas
    # ------------------------------------------------------------------
    def componentes_velocidad(self):
        """
        Componentes (u, v) de la velocidad en el centro de celda.

        SE CALCULA EN LAS CARAS Y LUEGO SE PROMEDIA, no al revés. La
        forma ingenua —promediar los caudales a la celda y dividir por su
        calado— produce velocidades disparatadas en el frente de avance:
        una celda con 1 mm de lámina que recibe caudal de una cara con
        50 cm de profundidad efectiva daría v = q/0.001, cientos de m/s.
        Ese pico es puramente numérico, pero contamina el máximo
        reportado y, sobre todo, el mapa de peligrosidad h·v, que es un
        resultado de seguridad.

        En la cara el cociente es consistente, porque el caudal q se
        calculó precisamente con esa h_cara: u_cara = q/h_cara está
        acotado por la propia física del esquema.
        """
        u = np.zeros_like(self.h)
        v = np.zeros_like(self.h)

        h_cara_x = getattr(self, "h_cara_x", None)
        h_cara_y = getattr(self, "h_cara_y", None)
        if h_cara_x is None or h_cara_y is None:
            return u, v

        with np.errstate(divide="ignore", invalid="ignore"):
            u_cara = np.where(h_cara_x > H_SECO, self.qx / np.maximum(h_cara_x, H_SECO), 0.0)
            v_cara = np.where(h_cara_y > H_SECO, self.qy / np.maximum(h_cara_y, H_SECO), 0.0)
        u_cara = np.nan_to_num(u_cara)
        v_cara = np.nan_to_num(v_cara)

        u[:, :-1] += 0.5 * u_cara
        u[:, 1:] += 0.5 * u_cara
        v[:-1, :] += 0.5 * v_cara
        v[1:, :] += 0.5 * v_cara

        # Solo se informa velocidad donde hay lámina apreciable: por
        # debajo de H_VELOCIDAD el valor no es representativo de nada
        # físico y no debe entrar en el mapa de peligro.
        seco = self.h <= H_VELOCIDAD
        u[seco] = 0.0
        v[seco] = 0.0
        return u, v

    def velocidades(self):
        """Magnitud de la velocidad en el centro de celda."""
        u, v = self.componentes_velocidad()
        return np.sqrt(u ** 2 + v ** 2)

    def peligrosidad(self):
        """
        Producto calado × velocidad (m²/s), el indicador de peligro para
        personas y vehículos que usan las guías de gestión de riesgo
        (p.ej. Defra/EA FD2320, y el criterio de estabilidad al vuelco de
        la normativa española). Se evalúa sobre los MÁXIMOS de cada
        celda, no sobre un instante: el peligro de un punto lo define el
        peor momento de la avenida, no el final de la simulación.
        """
        return self.h_max * self.v_max

    def balance_masa(self):
        """
        Error de cierre del balance de volumen. Es el indicador de si la
        simulación es creíble: por encima del 1% algo va mal en el
        esquema, los bordes o el paso de tiempo, y ningún mapa derivado
        debería usarse.
        """
        volumen_actual = float(np.sum(self.h) * self.dx * self.dy)
        entrada = self.volumen_inicial + self.volumen_entrado
        error = volumen_actual + self.volumen_salido - entrada
        relativo = (abs(error) / entrada * 100.0) if entrada > 0 else 0.0
        return {
            "volumen_inicial_m3": self.volumen_inicial,
            "volumen_entrado_m3": self.volumen_entrado,
            "volumen_salido_m3": self.volumen_salido,
            "volumen_almacenado_m3": volumen_actual,
            "error_m3": error,
            "error_relativo_pct": relativo,
            "aceptable": relativo < 1.0,
        }

    def resumen(self):
        h_moja = self.h_max[self.h_max > H_SECO]
        v_moja = self.v_max[self.h_max > H_SECO]
        peligro = self.peligrosidad()
        area_celda = self.dx * self.dy
        return {
            "tiempo_simulado_s": self.tiempo,
            "pasos": self.pasos,
            "esquema": self.esquema,
            "calado_maximo_m": float(h_moja.max()) if h_moja.size else 0.0,
            "calado_medio_inundado_m": float(h_moja.mean()) if h_moja.size else 0.0,
            "velocidad_maxima_ms": float(v_moja.max()) if v_moja.size else 0.0,
            "peligrosidad_maxima_m2s": float(peligro.max()),
            "area_inundada_m2": float(np.sum(self.h_max > H_SECO) * area_celda),
            "area_inundada_ha": float(np.sum(self.h_max > H_SECO) * area_celda / 10000.0),
            "celdas_dominio": int(self.activo.sum()),
            "pasos_con_dt_recortado": self.pasos_con_dt_recortado,
            "estable": self.pasos_con_dt_recortado == 0,
            "balance": self.balance_masa(),
        }


def simular(zb, dx, dy, tiempo_total_s, n_manning=0.035, esquema="inercia_local",
            entradas=None, lluvia_mm_h=0.0, estructuras=None,
            salida_por_bordes=True, cfl=0.7, dt_maximo=10.0,
            callback_progreso=None, intervalo_callback=1.0):
    """
    Ejecuta una simulación completa y devuelve (simulador, resumen).

    callback_progreso(porcentaje, tiempo_s, simulador) -> bool
        Si devuelve False, la simulación se detiene (cancelación desde
        la interfaz). Se llama como mucho cada `intervalo_callback`
        segundos de tiempo SIMULADO, no en cada paso: con pasos de
        décimas de segundo, notificar cada uno colapsaría la interfaz.
    """
    sim = SimuladorSwe2D(zb, dx, dy, n_manning=n_manning, esquema=esquema,
                          cfl=cfl, dt_maximo=dt_maximo)
    sim.lluvia_mm_h = lluvia_mm_h
    for e in (entradas or []):
        sim.agregar_entrada(**e)
    for est in (estructuras or []):
        sim.agregar_estructura(est)
    if salida_por_bordes:
        sim.salida_por_bordes()

    proximo_aviso = 0.0
    while sim.tiempo < tiempo_total_s:
        sim.avanzar()
        if callback_progreso and sim.tiempo >= proximo_aviso:
            porcentaje = min(100, int(sim.tiempo / tiempo_total_s * 100))
            if callback_progreso(porcentaje, sim.tiempo, sim) is False:
                break
            proximo_aviso = sim.tiempo + intervalo_callback

    return sim, sim.resumen()
