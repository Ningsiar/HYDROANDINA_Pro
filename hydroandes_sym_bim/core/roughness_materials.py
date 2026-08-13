# -*- coding: utf-8 -*-
"""
core/roughness_materials.py

Librería de valores TÍPICOS del coeficiente de rugosidad de Manning n por
material de revestimiento/tubería, para la Pestaña 7 (Diseño de
Estructuras Hidráulicas) -- el mismo espíritu que catálogos comerciales de
referencia (p.ej. las tablas de "Master Flow" u otros fabricantes de
tubería) y que las tablas clásicas de Chow (1959) y ASCE/AASHTO para
materiales de canal.

Son valores de PARTIDA editables, igual que el resto de tablas por
defecto del plugin (TABLA_USOS_ANDINOS_DEFAULT, TABLA_COEFICIENTES_C_DEFAULT):
al elegir un material se rellena el spinbox de n correspondiente, pero
sigue siendo editable a mano si el usuario tiene un valor de catálogo o de
ensayo propio más preciso.
"""
from typing import List, Tuple

# (nombre, n típico) -- ordenados de más liso a más rugoso dentro de cada
# familia (tubería cerrada primero, luego canal abierto/revestimiento).
TABLA_MATERIALES_N_DEFAULT: List[Tuple[str, float]] = [
    ("Vidrio / acrílico", 0.010),
    ("PVC / plástico liso", 0.010),
    ("Polietileno de alta densidad (HDPE) liso", 0.011),
    ("Fierro fundido dúctil (ductile iron)", 0.013),
    ("Acero liso soldado", 0.012),
    ("Acero corrugado", 0.024),
    ("Polietileno de alta densidad (HDPE) corrugado", 0.020),
    ("Concreto liso (acabado paleteado)", 0.012),
    ("Concreto centrifugado (tubería premoldeada)", 0.013),
    ("Concreto rugoso (encofrado de madera)", 0.017),
    ("Ladrillo revestido con mortero", 0.015),
    ("Mampostería de piedra careada (labrada)", 0.020),
    ("Mampostería de piedra sin carear", 0.032),
    ("Canal excavado en roca, irregular", 0.035),
    ("Canal de tierra, limpio y recto", 0.022),
    ("Canal de tierra con maleza y piedras sueltas", 0.035),
    ("Canal natural con vegetación densa", 0.060),
]
