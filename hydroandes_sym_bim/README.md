# HydroAndes SYM BIM - Plugin QGIS

## v0.2.66: control de calidad, completación y regionalización ampliados; validación de grillas (CHIRPS/IMERG) vs. estación (núcleo, aún sin pestaña propia en la interfaz)

A partir de nueva bibliografía y de scripts de análisis estadístico
hidrológico (R/Python) revisados en esta sesión, se amplían los módulos
`core/quality_control.py`, `core/data_completion.py` y
`core/precip_source.py`, y se agregan dos módulos nuevos:
`core/regionalization.py` y `core/gridded_validation.py`. Todo lo
agregado es lógica pura (numpy), **verificada con datos sintéticos en
este entorno** (no hay QGIS disponible aquí, igual que el resto del
núcleo matemático del plugin) — **aún no está conectado a ninguna
pestaña de la interfaz** (`plugin_dialog.py`); queda como trabajo
pendiente de la próxima iteración (ver "Próximo paso sugerido" abajo).

- **`core/quality_control.py`**:
  - `test_anderson_darling()`: prueba de normalidad de Anderson-Darling
    (caso 3, corrección de D'Agostino & Stephens 1986). **No** se
    implementó Shapiro-Wilk: sus coeficientes exactos del algoritmo
    AS R94 (Royston) no se pudieron verificar con certeza en este
    entorno y una implementación con coeficientes incorrectos sería
    peor que no tenerla; use Anderson-Darling aquí, o
    `scipy.stats.shapiro` si su intérprete de Python de QGIS tiene
    scipy instalado.
  - `test_mann_kendall_estacional()`: Mann-Kendall estacional (Hirsch,
    Slack & Smith, 1982) para series mensuales — evita falsos
    positivos/negativos de tendencia causados por el propio ciclo
    estacional (lo que sí puede pasar al aplicar Mann-Kendall simple,
    ya existente, directamente sobre una serie mensual sin desestacionalizar).
  - `corregir_por_quiebre()`: homogeneiza una serie a partir de un punto
    de quiebre ya detectado (Pettitt/Buishand/Worsley, ya existentes),
    ajustando el segmento posterior a la media del anterior — el mismo
    criterio de corrección usado por Wang Qiuxiang et al. (2012) al
    homogeneizar 2415 estaciones de precipitación diaria en China.
  - `funcion_autocorrelacion_parcial()`: PACF completa (recursión de
    Durbin-Levinson), en vez de un solo lag a la vez como el
    `test_autocorrelacion()` ya existente.
- **`core/data_completion.py`**: `seleccionar_estaciones_por_correlacion()`
  + `completar_regresion_multiple_seleccionada()`: filtran las
  estaciones predictoras de la Regresión Múltiple (ya existente) a solo
  las que superan un umbral de correlación (0.70 por defecto — el mismo
  umbral de Wang Qiuxiang et al., 2012), en vez de usar siempre todas
  las estaciones vecinas disponibles como predictoras.
- **`core/precip_source.py`**: la extracción NetCDF, antes exclusiva de
  PISCOp, se generalizó (`extraer_serie_diaria_desde_netcdf()`) a
  cualquier grilla lon/lat/time compatible — en particular **CHIRPS
  v2.0** e **IMERG/GPM V07B**, con su nombre de variable ya agregado a
  la autodetección. `extraer_serie_anual_desde_netcdf()` (la que usa la
  Pestaña 5) sigue funcionando exactamente igual, ahora apoyada en esta
  función genérica.
- **`core/regionalization.py`** (nuevo): regionalización de
  precipitación/temperatura en función de altitud/latitud/longitud —
  correlación con significancia, regresión (simple o múltiple) con IC
  95%, predicción en puntos nuevos (p.ej. centroide de una subcuenca), y
  una corrección local de los residuos por IDW — una aproximación
  práctica a co-kriging sin necesidad de ajustar un variograma, según la
  comparación de métodos de interpolación de precipitación para la
  República de Bashkortostan, Federación Rusa (WSEAS Trans. Environment
  and Development, 2014).
- **`core/gridded_validation.py`** (nuevo): valida un producto grillado
  (CHIRPS, IMERG, ERA5-Land, PISCOp) contra una estación, con métricas
  continuas (NSE, KGE con su descomposición r/alpha/beta, PBIAS, RMSE,
  R, y clasificación de desempeño de Moriasi et al. 2007) y métricas
  categóricas de detección de lluvia (POD, FAR, FBI, HSS) — estas
  últimas siguiendo el mismo enfoque de un estudio reciente (2025) de
  validación de CHIRPS/IMERG en la cuenca del río Ambato, Ecuador, un
  contexto andino comparable al de este proyecto.

**Próximo paso sugerido** (no incluido en esta iteración): exponer estas
funciones en la interfaz (una pestaña/subpestaña de "Control de Calidad
y Completación" y otra de "Regionalización"), y conectar
`gridded_validation` a un flujo que descargue o lea directamente CHIRPS
o IMERG (hoy requiere que el usuario ya tenga el NetCDF descargado,
igual que PISCOp). Ver también la sección "Historial de versiones" en
`metadata.txt` para el registro completo dentro del plugin.

## v0.2.6: entrada manual de P24 en tabla editable, con copiar/pegar estilo Excel

La Pestaña 5 (Precipitación Máx 24h) ahora tiene una tercera vía de
adquisición de datos, además de CSV y PISCOp: una tabla editable de dos
columnas (Año, P24 en mm) donde se puede escribir directamente o **pegar
un rango de dos columnas copiado desde Excel/LibreOffice con Ctrl+V**
(y copiar de vuelta con Ctrl+C).

Implementación: `ui/pasteable_table.py` define `TablaPegable`, una
subclase de `QTableWidget` que intercepta `Ctrl+V`/`Ctrl+C` y parsea el
texto del portapapeles en el formato estándar de hojas de cálculo
(filas separadas por salto de línea, columnas por tabulador). La
función de parseo (`parsear_texto_portapapeles`) es pura — sin
dependencias de Qt — y se probó en este entorno con los tres formatos
de salto de línea que puede producir un copiado real desde Excel
(`\n`, `\r\n` de Windows, `\r` de Mac clásico), incluyendo el caso
típico de una línea vacía sobrante al final del rango copiado.

`core/precip_source.py` se refactorizó para compartir la validación de
la serie (longitud mínima recomendada, consistencia año/valor) entre
las tres vías de entrada mediante una función común
(`construir_serie_anual`), y se agregó `construir_serie_desde_tabla`
para convertir las filas de texto crudo de la tabla en una serie
válida, con manejo explícito de filas vacías (se ignoran) y filas a
medio completar (se reporta el número de fila exacto con el error).

## v0.2.5: la columna "Parámetro" mostraba solo el símbolo abreviado

Bug encontrado: en `_on_calcular_morfometria`, las cuatro llamadas que
pueblan la tabla de morfometría hacían `self._agregar_fila_morfo(k, k, v)`,
pasando la misma clave abreviada del diccionario (p. ej. "A", "P", "Lb")
como argumento tanto de "nombre" (columna Parámetro) como de "símbolo"
(columna Símbolo) — nunca se usaba una descripción completa. Se agregó
`NOMBRES_PARAMETROS_MORFOMETRIA`, un diccionario con el nombre
descriptivo de cada uno de los 30 parámetros mostrados en la Pestaña 2
(p. ej. "A" → "Área de la cuenca"), verificado para cubrir exactamente
las claves que producen los grupos 1, 2, 5 y 6 de `core/morphometry.py`.
De paso se eliminó una fila duplicada del índice de Melton (aparecía dos
veces: una sin interpretación y otra con el mensaje de alerta).

## v0.2.4: la ventana ya no tapa el lienzo al seleccionar el punto de salida

Como el diálogo del plugin es una ventana no modal, quedaba flotando
sobre el lienzo justo cuando el usuario necesitaba ver el mapa para
hacer clic en el punto de salida. Ahora:

- Al pulsar "Seleccionar en el mapa (clic)" (Pestaña 1, Paso 3), la
  ventana del plugin se **oculta automáticamente**.
- Al hacer clic en el mapa, la ventana **reaparece sola**, con el punto
  ya cargado en el campo de coordenadas.
- Si el usuario cancela la selección de otra forma (tecla Escape,
  cambiar a otra herramienta de la barra de QGIS) sin llegar a hacer
  clic, la ventana también se restaura automáticamente (se detecta el
  cambio de herramienta activa del lienzo mediante la señal
  `mapToolSet`), para que nunca quede oculta indefinidamente.

## v0.2.3: "El punto de salida cae fuera de la extensión del ráster de cauces"

Este error podía aparecer incluso con el punto ya ajustado ("snap") a
una celda de cauce válida del propio ráster de cauces recién calculado
— lo cual, en principio, no debería ocurrir. La explicación más
plausible: GRASS aplica internamente una "región" de trabajo (extensión
+ resolución) a cada ráster de salida, y por defecto QGIS recalcula esa
región de forma independiente en cada llamada a un algoritmo `grass7:*`;
esto puede introducir pequeñas discrepancias de extensión entre pasos
sucesivos de la cadena (`r.fill.dir` → `r.watershed` → `r.water.outlet`),
de modo que un punto válido para el ráster de un paso podía quedar
justo fuera del ráster de otro paso calculado con una región
ligeramente distinta.

**Corrección**: se fija explícitamente `GRASS_REGION_PARAMETER` (verificado
el formato correcto, "xmin,xmax,ymin,ymax") a la extensión real del MDE
de entrada en TODAS las llamadas a algoritmos `grass7:*` de la cadena
(`r.fill.dir`, `r.watershed`, `r.water.outlet`, `r.thin`, `r.to.vect`),
en vez de dejar que cada paso la determine de forma independiente.

**Además**, se agregó una validación temprana: antes de ejecutar toda la
cadena de delineación (que puede tardar varios minutos), el plugin
verifica que el punto de salida caiga dentro de la extensión real del
MDE cargado, y si no es así, lo informa de inmediato con las
coordenadas exactas de ambos (el punto clicado y los límites del MDE),
en vez de fallar minutos después dentro del ajuste al cauce.

## v0.2.2: corrección de raíz — ajuste automático del punto de salida

Las dos rondas de bugs anteriores ('NoneType' object has no attribute
'source', y "Delimitador de entrada no válido: <número gigante>")
compartían la misma causa de fondo: los algoritmos `native:*` con salida
tipo sink, al recibir "TEMPORARY_OUTPUT", devuelven un ID interno de
capa (a veces un entero de hasta 20 dígitos) que solo es resoluble con
`context.takeResultLayer()` — nunca como ruta de archivo. Cuando ese ID
no se resolvía por alguna razón (versión de QGIS, contexto no coincidente,
etc.), el código intentaba tratarlo como una ruta/URI, lo que generaba
errores confusos y en un caso incluso el aviso "delimitador no válido"
de QGIS intentando interpretar el número como un delimitador de texto.

**Corrección de raíz**: en vez de "TEMPORARY_OUTPUT" para los pasos
`native:smoothgeometry` y `native:clip`, ahora se generan rutas de
archivo GeoPackage EXPLÍCITAS con `QgsProcessingUtils.generateTempFilename()`.
Así, absolutamente todas las salidas de la cadena de delineación son
siempre archivos reales en disco — nunca IDs de capa de contexto — y se
cargan de forma uniforme y determinista, sin ambigüedad posible.

**Además**, se implementó el ajuste automático ("snap") del punto de
salida a la celda de cauce más cercana (`core/pour_point_snap.py`),
para atacar la causa raíz de por qué la cuenca salía vacía en primer
lugar: el break point rara vez cae exactamente sobre la celda correcta
del ráster de dirección D8 con solo un clic en el mapa. Ahora, antes de
delinear, el plugin busca automáticamente la celda de cauce más cercana
dentro de un radio configurable (por defecto 15 celdas del MDE) y
delinea desde ahí, informando al usuario cuántos metros se movió el
punto. Esto está activado por defecto (casilla en la Pestaña 1, Paso 4)
y puede desactivarse si se prefiere el comportamiento anterior.

La cadena de delineación se refactorizó de una función monolítica a 3
funciones independientes (`calcular_flujo`, `delinear_desde_punto`,
`extraer_y_recortar_red`) precisamente para poder insertar el ajuste
del punto entre el cálculo del flujo y la delineación de la cuenca.

## Nuevo diagnóstico (v0.2.1): "No se pudo resolver la salida del algoritmo... OUTPUT.tif"

Este mensaje (distinto y más específico que el bug de la v0.2.0, señal
de que aquella corrección sí está funcionando) generalmente NO significa
que falte GRASS o GDAL. La causa más frecuente es que **la cuenca
delineada haya quedado vacía (0 polígonos)**, típicamente porque el
punto de salida (break point) no cayó exactamente sobre una celda de
alta acumulación de flujo del ráster de dirección D8 — basta con estar
a 1-2 celdas de distancia de la línea de cauce real para que
`r.water.outlet` devuelva una cuenca vacía, lo que hace fallar
silenciosamente el recorte del MDE varios pasos después (de ahí que el
error apareciera en el paso de `gdal:cliprasterbymasklayer`, no en los
pasos de GRASS anteriores, que sí se habían ejecutado correctamente).

**Se agregó una verificación explícita**: ahora, si la cuenca queda
vacía, el plugin lo detecta inmediatamente después de delinearla (antes
de llegar al recorte del MDE) y muestra un mensaje que señala esta causa
directamente, con 3 soluciones a probar en orden:
1. Reducir el umbral de acumulación de flujo (paso 4 de la Pestaña 1)
   para generar una red de drenaje más densa.
2. Volver a hacer clic en el break point procurando ubicarlo exactamente
   sobre una línea de la red de drenaje (cárguela primero con el
   algoritmo "2. Extraer red de drenaje" para verla en el lienzo antes
   de hacer clic).
3. Verificar que el MDE tenga resolución suficiente para representar el
   cauce en ese punto (un MDE de 90m puede no resolver quebradas
   pequeñas).

## Si le sigue apareciendo "'NoneType' object has no attribute 'source'" después de esta corrección

Auditamos todo el código de nuevo: la única línea que llama `.source()`
(en `_on_run_delineation`) está protegida por `obtener_capa()`, que
**nunca devuelve None** — o entrega una capa válida, o lanza un
`RuntimeError` con un mensaje explicativo distinto y más claro. Si
usted sigue viendo el mensaje genérico original exacto, la causa casi
segura es que **QGIS todavía está cargando una versión anterior del
plugin**, no la de este paquete. Pasos para confirmarlo y resolverlo:

1. **Verifique la versión cargada**: abra el plugin y vaya a la
   pestaña **"7. Créditos"**. Debe decir "Versión 0.2.0" y mencionar
   la Pestaña 5 de Precipitación. Si no ve esa pestaña 5
   ("Precipitación Máx 24h") en su plugin, tiene la versión vieja
   instalada.
2. **Elimine por completo la carpeta anterior del plugin** en su
   directorio de perfiles de QGIS (no sobrescriba encima; bórrela
   entera primero) — ver rutas típicas más abajo en este documento.
3. **Extraiga el .zip nuevo** en esa misma ubicación.
4. **Cierre QGIS por completo y vuelva a abrirlo** (no basta con
   deshabilitar/habilitar el plugin: Python puede mantener módulos ya
   importados en memoria). Si tiene instalado el plugin **Plugin
   Reloader**, también sirve para forzar la recarga sin reiniciar QGIS.
5. Si después de estos pasos el problema persiste, comparta el mensaje de
   error completo (puede ser distinto y más específico ahora) y en qué
   paso exacto de la Pestaña 1 ocurre.

## Corrección de bug reportado: "'NoneType' object has no attribute 'source'"

**Causa raíz encontrada y corregida:** al ejecutar algoritmos de
Processing encadenados (`is_child_algorithm=True`), solo las salidas de
tipo `native:*` (que usan `QgsProcessingParameterFeatureSink`, como
`native:smoothgeometry` o `native:clip`) quedan registradas en el
`QgsProcessingContext` y son recuperables con `context.takeResultLayer()`.

Los algoritmos de GDAL y GRASS (`gdal:polygonize`,
`gdal:cliprasterbymasklayer`, `grass7:r.*`) **no** registran su salida
como sink: devuelven directamente una ruta de archivo en disco. Llamar
`context.takeResultLayer()` sobre esa ruta devuelve `None`, y el
siguiente `.source()` sobre `None` produce exactamente el error
reportado. Esto ocurría en el paso de recorte del MDE
(`gdal:cliprasterbymasklayer`) dentro de `_on_run_delineation`.

**Solución aplicada:** se creó `core/qgis_layer_utils.py` con una
función `obtener_capa()` que intenta primero `context.takeResultLayer()`
y, si devuelve `None`, carga la capa directamente desde la ruta de
archivo con `QgsRasterLayer`/`QgsVectorLayer`. Se reemplazaron todas las
llamadas directas a `context.takeResultLayer()` en `plugin_dialog.py`
por esta función robusta.

## Novedades de esta versión

- **Pestaña 5 (nueva): "Precipitación Máx 24h"** — análisis de
  frecuencia de precipitación máxima en 24 horas:
  - Adquisición de datos: serie manual (CSV año/P24) o extracción desde
    un archivo NetCDF de PISCOp ya descargado (ver limitación de
    descarga automática más abajo).
  - Ajuste de 5 distribuciones (Normal, Log-Normal, Gumbel, Log-Pearson
    III, GEV) con prueba de bondad de ajuste de Kolmogorov-Smirnov y
    selección automática del mejor ajuste.
  - Precipitaciones de diseño para Tr = 2, 5, 10, 25, 50, 100, 250, 500,
    1000 años.
  - **Enlazada a la Pestaña 6**: el Tr elegido alimenta automáticamente
    la generación del hietograma de diseño para el cálculo de caudales.
- **Pestaña 6 (antes Pestaña 5)**: ahora permite elegir entre dos
  métodos de desagregación temporal para construir el hietograma a
  partir de P24:
  - **Curva IDF genérica (bloques alternos)**: escalamiento potencial
    tipo Sherman, duración de tormenta configurable.
  - **Patrón SCS Tipo I / II / III**: curvas adimensionales de 24h.
    **Advertencia de fidelidad**: son una aproximación paramétrica de la
    forma general de cada tipo, NO la tabla oficial tabulada de NRCS
    TR-55 Apéndice B (no se pudo verificar esa tabla verbatim en este
    entorno — ver docstring de `core/scs_storm_patterns.py`). Incluye un
    mecanismo (`cargar_tabla_oficial_csv()`) para sustituir por la tabla
    oficial si el usuario la tiene disponible.
- **Corrección de bug**: ver sección anterior.

## ¿En qué versiones de QGIS corre?

**Rango recomendado: QGIS 3.28 a 3.44** (declarado en `metadata.txt` como
`qgisMinimumVersion=3.28`). Esto es lo que verifiqué al 19 de julio de 2026:

- **QGIS 3.44** es la última versión de la serie 3.x y sigue siendo la
  rama LTR (long term release) recomendada para producción; su soporte
  LTR se extiende hasta que QGIS 4.2 tome ese rol, previsto para octubre
  de 2026. Es el entorno más seguro para correr este plugin hoy.
- **QGIS 4.0 "Norrköping"** se lanzó el 6 de marzo de 2026 y migró el
  núcleo de Qt5 a Qt6. No es todavía la LTR (esa será la 4.2, ~octubre
  2026), así que para uso en producción se recomienda esperar o probar
  4.0 en paralelo antes de migrar. El código de este plugin **ya está
  escrito de forma compatible con ambas ramas**: usa `qgis.PyQt` (el
  shim de compatibilidad de QGIS) en vez de importar `PyQt5` directo, y
  el canvas de matplotlib usa el backend genérico `backend_qtagg` (con
  reserva a `backend_qt5agg` si hiciera falta) en vez de forzar Qt5. Aun
  así, no se pudo probar en un QGIS 4.0 real en este entorno — verifíquelo
  usted antes de un uso en producción bajo 4.x.
- **SAGA ya no viene integrado por defecto desde QGIS 3.30** (fue
  retirado del núcleo; ahora requiere instalar el plugin de terceros
  "Processing Saga NextGen Provider"). Por eso la cadena de delineación
  se reescribió para usar **solo algoritmos GRASS** (`grass7:r.fill.dir`
  en vez de `saga:fillsinkswangliu`), que sí siguen empaquetados con
  QGIS por defecto en todas las versiones mencionadas arriba. Esto evita
  que el plugin dependa de un proveedor que el usuario podría no tener
  instalado.
- **Versiones anteriores a 3.28** (p. ej. 3.16, 3.22): no se probaron, y
  algunas funciones de `QgsProcessingParameterPoint`/`QgsGeometry.
  orientedMinimumBoundingBox()` usadas aquí requieren APIs relativamente
  recientes de PyQGIS; es posible que necesiten ajustes menores.

Implementación funcional del análisis hidrológico integral especificado:
delineación desde MDE, 6 grupos de morfometría, número de curva SCS, y
tiempo de concentración por múltiples métodos, con exportación
multi-formato.

## Verificación realizada antes de la entrega

Los módulos matemáticos puros (`core/morphometry.py`, `core/tc_methods.py`,
`core/curve_number.py`) **se probaron en este entorno con datos sintéticos
y con los valores reales de la subcuenca Acomayo** ya calculados en
conversaciones previas — el método de Kirpich métrico dio Tc = 87.3 min,
exactamente igual al valor obtenido manualmente antes. Los módulos que
dependen de `qgis.core`/`qgis.gui` (delineación, diálogo, exportadores)
**no se pudieron ejecutar aquí** porque no hay un entorno QGIS disponible
en este sistema; solo se verificó que compilan sin errores de sintaxis.
Pruébelos primero con una cuenca pequeña antes de un uso en producción.

## Diferencias respecto a la especificación original (leer antes de usar)

1. **Kirpich con unidades corregidas.** La especificación pedía
   `Tc = 0.0078 * (Lc_km*1000)^0.77 * Se^-0.385`. El coeficiente 0.0078
   corresponde a la versión de Kirpich con longitud en **pies**, no en
   metros; aplicarlo a metros sobreestima Tc en ~3.6x. Se implementó la
   versión métrica estándar (coeficiente 0.01947, la misma que ya usamos
   para Acomayo). La versión literal del prompt se conserva como
   `kirpich_prompt_literal` solo para trazabilidad, marcada "no
   recomendado".

2. **SCS Lag con unidades corregidas.** La fórmula requiere la retención
   potencial S en **pulgadas**, no en milímetros como sugería la
   redacción `(S_mm+1)^0.7`. El código recibe S en mm (como lo entrega el
   módulo de número de curva) y lo convierte internamente.

3. **"20 métodos de Tc".** Se implementaron y verificaron **15 métodos**
   (los 10 explícitos del encargo + Ven Te Chow, FAA, Espey-Winslow, y
   Snyder convertido a Tc-equivalente). No se completaron los 20
   inventando coeficientes de fórmulas históricas que no se pudieron
   verificar con certeza (Clark solo tiene sentido como transformación a
   hidrograma, no como fórmula de Tc — ver punto 7). La arquitectura de
   registro (`@registrar_metodo`) está lista para añadir cada método
   adicional en cuanto se verifique su fórmula contra una fuente
   primaria; ver el docstring de `core/tc_methods.py`.

   **Advertencia de aplicabilidad para la subcuenca Acomayo (24.94 km²):**
   - **Snyder** fue calibrado para cuencas de 26 a 26,000 km² (10 a 10,000
     mi²); Acomayo está en el límite inferior de ese rango, y el Tc
     equivalente calculado (≈10.8 h) es notoriamente más alto que el resto
     de métodos (~1.5-4 h) — trátelo con cautela, no como referencia.
   - **Espey-Winslow** fue calibrado para cuencas urbanas pequeñas con
     pendientes de canal entre 0.64% y 1.04% e impermeabilidad ≥2.7%;
     una subcuenca andina natural de 8.6% de pendiente y 0% de
     impermeabilidad está fuera de su rango de calibración, y la
     literatura reporta que es, de hecho, el método con peor desempeño
     comparativo en estudios de validación. Se incluyó por ser
     explícitamente solicitado, no porque se recomiende para Acomayo.

4. **"0.25 iteraciones" de suavizado.** `native:smoothgeometry` no acepta
   un número fraccionario de iteraciones (parámetro entero ≥ 1). Se
   interpretó como 1 iteración con offset = 0.25 (offset sí es un
   parámetro continuo válido 0–0.5), y quedó configurable en la interfaz.

5. **Orden de Strahler.** La red vectorizada no trae un atributo de
   dirección de flujo; el orden se infiere asumiendo que cada tramo fluye
   desde su extremo de mayor elevación al de menor elevación (muestreada
   del MDE). Es una aproximación razonable pero no equivalente a usar el
   ráster de dirección D8 directamente (mejora sugerida más abajo).

6. **Descarga de MDE (OpenTopography).** El código del endpoint sigue el
   formato público documentado por OpenTopography, pero **no se pudo
   probar con una petición real** (sin acceso a red en este entorno).
   Pruébelo primero con un bounding box pequeño y una API Key válida.

7. **Clark no es una fórmula de Tc, es un método de transformación.**
   A diferencia de Kirpich/Témez/Snyder (que dan un número de Tc), Clark
   (1945) construye un hidrograma completo a partir de una curva
   área-tiempo y un tránsito por embalse lineal (parámetro de
   almacenamiento R), usando el Tc calculado por cualquier otro método
   como insumo. Por eso Clark se implementó en `core/unit_hydrographs.py`
   y aparece en la **Pestaña 5** (junto con SCS y Snyder) como método de
   estimación de CAUDALES, no en la tabla de Tc de la Pestaña 4.

## Verificación de las fórmulas de la Pestaña 5 (SCS/Snyder/Clark)

Antes de codificarlas se verificaron por búsqueda contra múltiples
fuentes independientes (no se completaron de memoria):

- **SCS triangular**: tp = D/2 + tlag; Qp = 2.08·A/tp (m³/s por mm, A en
  km²); Tb = 2.67·tp. Estándar USDA-NRCS, consistente con HEC-HMS.
- **Snyder (SI)**: tp = 0.75·Ct·(L·Lca)^0.3 (h); tr = tp/5.5; qp =
  2.75·Cp/tp (m³/s/km²); Tb = 5.56/qp. Ct≈1.8-2.2, Cp≈0.4-0.8 (requieren
  calibración regional; los valores por defecto en la interfaz son
  genéricos, no específicos de Acomayo).
- **Clark**: curva área-tiempo por defecto Ai/A=1.414·(Ti/Tc)^1.5 (Ti/Tc
  ≤0.5) y Ai/A=1-1.414·(1-Ti/Tc)^1.5 (Ti/Tc>0.5); tránsito por embalse
  lineal con R como parámetro de calibración (sin datos de aforo, se usa
  R≈Tc como punto de partida, editable en la interfaz).
- Las tres se probaron en este entorno con datos sintéticos y con los
  parámetros reales de Acomayo; los tres métodos corrieron sin errores y
  dieron órdenes de magnitud de caudal pico razonables entre sí (con la
  dispersión esperada entre métodos, coherente con estudios comparativos
  publicados).



## Instalación

Copie la carpeta `hydroandes_sym_bim/` al directorio de plugins de QGIS (ver
rutas típicas en el README del plugin anterior de este mismo proyecto) y
habilite "complementos experimentales" antes de activarlo.

### Dependencia adicional opcional

La exportación a Excel requiere `openpyxl`, que no viene con QGIS por
defecto. La extracción de series desde NetCDF de PISCOp (Pestaña 5)
requiere `xarray` y `netCDF4`:
```
# Windows (OSGeo4W Shell) / Linux-Mac (terminal con el Python de QGIS)
pip install openpyxl xarray netCDF4
```
Si no están instalados, el resto del plugin funciona igual; solo fallan
(con mensaje explicativo) las funciones que los requieren. La carga de
series desde CSV manual (alternativa siempre disponible) no necesita
ninguna de estas dos dependencias.

### Complementos de Processing requeridos

GRASS debe estar habilitado en Processing (Configuración > Proveedores);
suele venir activo por defecto. La cadena de delineación
(`core/delineation.py`) depende únicamente de `grass7:r.fill.dir`,
`grass7:r.watershed`, `grass7:r.water.outlet`, `grass7:r.thin` y
`grass7:r.to.vect` — SAGA ya no es una dependencia (ver nota de
compatibilidad al inicio de este documento).

## Flujo de uso

1. **Pestaña 1**: cargue o descargue el MDE, opcionalmente indique un AOI,
   haga clic en el mapa para fijar el break point, ajuste el umbral de
   acumulación y ejecute la delineación.
2. **Pestaña 2**: ingrese Lc, Lt y Nu (medidos sobre la red de drenaje
   resultante; un desarrollo futuro puede automatizar esta lectura desde
   `red_drenaje_layer`) y calcule la morfometría.
3. **Pestaña 3**: ajuste las áreas de la matriz de uso de suelo x grupo
   hidrológico y calcule CN_I/II/III.
4. **Pestaña 4**: calcule los métodos de Tc, revise la curva
   hipsométrica, marque el método adoptado, y exporte todo.
5. **Pestaña 5**: cargue una serie de máximos anuales P24h (CSV manual
   o extracción de PISCOp), ajuste las distribuciones, y obtenga las
   precipitaciones de diseño por periodo de retorno.
6. **Pestaña 6**: elija Tr (poblado automáticamente desde la pestaña 5),
   elija el método de desagregación (IDF o SCS I/II/III), genere el
   hietograma con un clic, y calcule el hidrograma de crecida (SCS,
   Snyder o Clark) y el caudal pico.
7. **Pestaña 7**: créditos.

## Próximas mejoras sugeridas (no incluidas en este esqueleto)

- Calcular Lc, Lt y Nu automáticamente desde `red_drenaje_layer` en vez
  de pedirlos como entrada manual en la pestaña 2.
- Usar el ráster de dirección D8 (`raster_direccion`, ya generado por
  `preprocesar_y_delinear`) para un orden de Strahler exacto en vez de la
  aproximación por elevación.
- Segmentación real del perfil longitudinal del cauce (Grupo 3: S10-85,
  Taylor-Schwartz) muestreando el MDE a lo largo de la geometría del
  cauce principal, en vez de requerir el perfil como entrada.
- Persistir resultados de sesión (guardar/cargar un proyecto de análisis
  en JSON) para no perder la matriz de CN o los métodos de Tc al cerrar
  QGIS.
