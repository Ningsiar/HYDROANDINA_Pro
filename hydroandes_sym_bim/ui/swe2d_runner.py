# -*- coding: utf-8 -*-
"""
ui/swe2d_runner.py

Ejecución de la simulación 2D en un HILO SECUNDARIO.

MOTIVO: una simulación de aguas someras son decenas de miles de pasos de
tiempo. Ejecutarla en el hilo de la interfaz deja QGIS congelado —sin
repintar, sin responder, con el aspecto de haberse colgado— durante todo
ese rato, y sin posibilidad de cancelar. Peor aún: Windows marca la
ventana como «no responde» y el usuario puede matar QGIS a mitad del
cálculo.

Aquí la simulación corre en un QThread y se comunica por señales, que es
la forma segura en Qt de tocar la interfaz desde otro hilo: los widgets
solo pueden modificarse desde el hilo principal, y una señal cruza esa
frontera correctamente. Por eso el worker NO toca ningún widget: emite
datos, y el diálogo decide qué pintar.

CAPTURA DE INSTANTES. Guardar el estado en cada paso agotaría la
memoria (miles de pasos × una matriz completa cada uno). Se captura a
intervalos de tiempo SIMULADO, que es lo que hace falta para animar la
inundación en QGIS sin llenar la RAM.
"""
import numpy as np

from qgis.PyQt.QtCore import QThread, pyqtSignal

from ..core import swe2d


class SimulacionSwe2DWorker(QThread):
    """
    Hilo de simulación.

    Señales:
      progreso(porcentaje, tiempo_s, calado_max, area_ha)
      terminado(simulador, resumen)
      fallo(mensaje)
      mensaje(texto)
    """

    progreso = pyqtSignal(int, float, float, float)
    terminado = pyqtSignal(object, object)
    fallo = pyqtSignal(str)
    mensaje = pyqtSignal(str)

    def __init__(self, configuracion, parent=None):
        super().__init__(parent)
        self.configuracion = configuracion
        self._cancelado = False
        self.simulador = None
        self.resumen = None
        self.instantes = []

    def cancelar(self):
        """Cancelación cooperativa: se marca la bandera y el bucle sale
        en el siguiente aviso de progreso. No se mata el hilo -- abortar
        un hilo a la fuerza deja los arrays a medio escribir y el estado
        del simulador inservible."""
        self._cancelado = True

    def run(self):
        try:
            cfg = self.configuracion
            self.mensaje.emit("Preparando el dominio de cálculo…")

            sim = swe2d.SimuladorSwe2D(
                cfg["zb"], cfg["dx"], cfg["dy"],
                n_manning=cfg.get("n_manning", 0.035),
                esquema=cfg.get("esquema", "inercia_local"),
                cfl=cfg.get("cfl", 0.7),
                dt_maximo=cfg.get("dt_maximo", 10.0),
                h_inicial=cfg.get("h_inicial"))
            sim.lluvia_mm_h = cfg.get("lluvia_mm_h", 0.0)

            for entrada in cfg.get("entradas", []):
                sim.agregar_entrada(**entrada)
            for estructura in cfg.get("estructuras", []):
                sim.agregar_estructura(estructura)
            if cfg.get("salida_por_bordes", True):
                sim.salida_por_bordes()
            # Sección(es) de control/descarga (p.ej. el punto de salida
            # real de la cuenca) -- ver swe2d.agregar_seccion_control().
            # Se agregan DESPUÉS de salida_por_bordes(): agregar_salida()
            # deduplica, así que el orden no afecta el balance, pero si
            # una sección cae fuera del dominio activo (Swe2DError) se
            # avisa por mensaje en vez de abortar toda la simulación --
            # las demás condiciones de contorno siguen siendo válidas.
            for seccion in cfg.get("secciones_control", []):
                try:
                    sim.agregar_seccion_control(**seccion)
                except swe2d.Swe2DError as e:
                    self.mensaje.emit(f"Aviso: no se pudo agregar la sección de control: {e}")

            self.simulador = sim
            tiempo_total = float(cfg["tiempo_total_s"])
            intervalo_captura = float(cfg.get("intervalo_captura_s", 0.0))
            intervalo_aviso = max(tiempo_total / 200.0, 1.0)

            self.mensaje.emit(
                f"Simulando {tiempo_total:.0f} s con el esquema "
                f"«{sim.esquema.replace('_', ' ')}»…")

            proximo_aviso = 0.0
            proxima_captura = 0.0
            while sim.tiempo < tiempo_total:
                if self._cancelado:
                    self.mensaje.emit(
                        f"Cancelado por el usuario en t = {sim.tiempo:.1f} s.")
                    break
                sim.avanzar()

                if intervalo_captura > 0 and sim.tiempo >= proxima_captura:
                    self._capturar(sim)
                    proxima_captura = sim.tiempo + intervalo_captura

                if sim.tiempo >= proximo_aviso:
                    porcentaje = min(100, int(sim.tiempo / tiempo_total * 100))
                    area_ha = float(np.sum(sim.h > swe2d.H_SECO) *
                                    sim.dx * sim.dy / 10000.0)
                    self.progreso.emit(porcentaje, sim.tiempo,
                                       float(sim.h_max.max()), area_ha)
                    proximo_aviso = sim.tiempo + intervalo_aviso

            # Instante final siempre, aunque no caiga en el intervalo:
            # es el estado que el usuario ve como «resultado».
            if intervalo_captura > 0:
                self._capturar(sim)

            self.resumen = sim.resumen()
            self.progreso.emit(100, sim.tiempo, float(sim.h_max.max()),
                               float(np.sum(sim.h_max > swe2d.H_SECO) *
                                     sim.dx * sim.dy / 10000.0))
            self.terminado.emit(sim, self.resumen)

        except Exception as e:                     # noqa: BLE001
            import traceback
            self.fallo.emit(f"{e}\n\n{traceback.format_exc()}")

    def _capturar(self, sim):
        """
        Guarda (t, h, vx, vy) para poder animar el resultado en QGIS.

        Las componentes se piden al simulador en vez de recalcularlas
        aquí: es él quien sabe que la velocidad debe evaluarse en las
        caras y no dividiendo el caudal de celda por su calado (ver
        SimuladorSwe2D.componentes_velocidad). Duplicar esa lógica sería
        la vía directa a que la animación mostrara velocidades distintas
        de las del mapa de máximos.

        Se COPIA el calado: sin copiar, todos los instantes apuntarían al
        mismo buffer y la animación mostraría el último estado repetido.
        """
        vx, vy = sim.componentes_velocidad()
        self.instantes.append((sim.tiempo, sim.h.copy(), vx, vy))


def estimar_coste(n_filas, n_columnas, tiempo_total_s, dx, dy, calado_tipico=1.0,
                  esquema="inercia_local", cfl=0.7, n_manning=0.035,
                  caudal_entrada_max=0.0):
    """
    Estima ANTES de lanzar cuántos pasos y cuánto tiempo va a costar.

    Es información necesaria, no un adorno: la diferencia entre los dos
    esquemas es de dos órdenes de magnitud, y un dominio de un millón de
    celdas con el esquema difusivo puede pasar de las horas. Vale más
    saberlo antes que descubrirlo a los veinte minutos.
    """
    celdas = n_filas * n_columnas
    paso_malla = min(dx, dy)

    dt_onda = cfl * paso_malla / (9.81 * max(calado_tipico, 0.01)) ** 0.5
    if esquema == "onda_difusiva":
        # Límite parabólico con una pendiente de superficie típica de
        # 0.001, que es del orden de lo que se da en llanura de
        # inundación; en cauce será aún más restrictivo.
        difusividad = (1.0 / n_manning) * (calado_tipico ** (5.0 / 3.0)) / (0.001 ** 0.5)
        dt = min(dt_onda, 0.25 * paso_malla ** 2 / max(difusividad, 1e-9))
    else:
        dt = dt_onda

    # El límite por las FUENTES suele ser el que manda cuando hay una
    # entrada concentrada, y omitirlo hacía que la estimación se quedara
    # corta varias veces -- justo el error que esta función existe para
    # evitar. Se replica el criterio de swe2d._paso_por_fuentes con el
    # calado típico indicado.
    if caudal_entrada_max > 0:
        incremento = max(swe2d.INCREMENTO_MIN_FUENTE,
                         swe2d.FRACCION_FUENTE * calado_tipico)
        dt = min(dt, incremento * dx * dy / caudal_entrada_max)

    pasos = int(tiempo_total_s / max(dt, 1e-6))
    # ~8 operaciones sobre arrays completos por paso; el rendimiento de
    # NumPy en esta clase de operación ronda 5e7 celdas·op/s en un equipo
    # de escritorio. Es una estimación de orden de magnitud, no una
    # promesa.
    segundos = pasos * celdas * 8.0 / 5.0e7
    return {
        "celdas": celdas,
        "dt_estimado_s": dt,
        "pasos_estimados": pasos,
        "segundos_estimados": segundos,
        "minutos_estimados": segundos / 60.0,
    }
