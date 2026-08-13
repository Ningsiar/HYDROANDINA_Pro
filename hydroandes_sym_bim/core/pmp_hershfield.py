# -*- coding: utf-8 -*-
"""
core/pmp_hershfield.py

Precipitación Máxima Probable (PMP) 24h por el método ESTADÍSTICO de
Hershfield (1961; revisado 1965), ampliamente usado como método de
estimación preliminar de PMP cuando no se dispone de un estudio de
maximización de tormentas observadas (método hidrometeorológico
completo, mucho más exigente en datos).

FÓRMULA (Hershfield, 1965):
    PMP = X_(n-1) + Km * S_(n-1)
  donde X_(n-1) y S_(n-1) son la media y la desviación estándar de la
  serie de máximos anuales EXCLUYENDO el valor máximo de la propia serie
  (para no auto-inflar el factor de frecuencia con el dato que se busca
  superar), y Km es el "factor de frecuencia" de Hershfield (WMO reporta
  un envolvente mundial de Km hasta ~15, valor comúnmente adoptado como
  referencia conservadora cuando no se cuenta con un Km regionalizado).

AJUSTE POR OBSERVACIÓN A HORA FIJA: si la serie proviene de lecturas
pluviométricas de una vez al día (p. ej. 07h a 07h), el máximo real de
24 h corridas suele ser mayor que el máximo del día calendario/lectura
fija. La OMM (WMO-No. 1045, "Manual on Estimation of Probable Maximum
Precipitation", 2009) documenta un factor de corrección estándar de
1.13 para este efecto.

TRANSPARENCIA IMPORTANTE:
  - Hershfield también propuso un ajuste adicional por longitud de
    registro (curvas para corregir Km según el número de años de datos,
    leídas de un gráfico en su publicación original) que NO se
    implementa aquí, porque sus coeficientes exactos no se pudieron
    verificar con la certeza necesaria para un cálculo de diseño de
    presas. Si el registro es corto (<25 años) o muy largo (>100 años),
    consulte la curva de ajuste por tamaño de muestra del WMO-No. 1045
    antes de un diseño definitivo.
  - Km=15 es un valor de referencia MUNDIAL conservador citado por la
    OMM; lo ideal es usar un Km regionalizado si existe un estudio local
    de PMP para la zona.
"""
from typing import List, Optional

import numpy as np


class PmpHershfieldError(Exception):
    pass


def calcular_pmp_hershfield(serie_p24h_anual: List[float], km: float = 15.0,
                             factor_hora_fija: Optional[float] = 1.13) -> dict:
    """
    serie_p24h_anual: máximos anuales de precipitación en 24h (mm).
    km: factor de frecuencia de Hershfield (por defecto 15, envolvente
        mundial conservadora citada por la OMM; ajústelo si cuenta con
        un valor regionalizado).
    factor_hora_fija: factor de corrección por observación a hora fija
        (por defecto 1.13, WMO-No. 1045); use None o 1.0 si la serie ya
        proviene de un registro continuo (pluviógrafo) sin ese sesgo.
    """
    x = np.asarray(serie_p24h_anual, dtype=float)
    n = len(x)
    if n < 10:
        raise PmpHershfieldError(
            "Se recomiendan al menos 10 años de datos para aplicar el método de Hershfield; la "
            f"serie proporcionada tiene {n}."
        )

    indice_max = int(np.argmax(x))
    valor_max = float(x[indice_max])
    x_sin_max = np.delete(x, indice_max)

    media_sin_max = float(np.mean(x_sin_max))
    desv_sin_max = float(np.std(x_sin_max, ddof=1))

    factor = factor_hora_fija if factor_hora_fija else 1.0
    media_ajustada = media_sin_max * factor
    desv_ajustada = desv_sin_max * factor

    pmp = media_ajustada + km * desv_ajustada

    return {
        "PMP_24h_mm": round(pmp, 1),
        "n_anios": n,
        "valor_maximo_observado_mm": round(valor_max, 1),
        "media_sin_maximo_mm": round(media_sin_max, 2),
        "desv_std_sin_maximo_mm": round(desv_sin_max, 2),
        "factor_hora_fija_aplicado": factor,
        "km_usado": km,
        "razon_pmp_sobre_max_observado": round(pmp / valor_max, 2) if valor_max > 0 else None,
        "nota": (
            "Método estadístico de Hershfield (1965), factor Km mundial conservador de la OMM "
            "(o el valor regionalizado que haya indicado). NO incluye el ajuste por longitud de "
            "registro de las curvas originales de Hershfield (no verificado con certeza suficiente "
            "para diseño de presas); verifique contra WMO-No. 1045 si el registro es muy corto o "
            "muy largo. Este es un método preliminar/de tamizado, no reemplaza un estudio completo "
            "de maximización hidrometeorológica de tormentas para el diseño final de una presa."
        ),
    }
