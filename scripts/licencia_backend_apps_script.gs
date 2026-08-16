// ============================================================
// HydroAndes SYM BIM -- backend de licencia (Google Apps Script)
// ============================================================
// PLANTILLA -- copie TODO este archivo dentro del editor de Apps Script
// de una hoja de cálculo de Google nueva y AJUSTE CLAVE_SECRETA antes de
// desplegar (ver instrucciones abajo). No vuelva a pegar su versión ya
// personalizada (con el secreto real) en este repositorio.
//
// PASO 1 -- Hoja de cálculo:
//   Use la hoja "HydroAndes SYM BIM - Licencias" (Claude ya la creó con los
//   encabezados en la fila 1: id | primer_uso | ultimo_uso | usos |
//   licencia | notas | limite), o cree una propia con esos mismos
//   encabezados. El script usa la PRIMERA pestaña de la hoja, sea cual
//   sea su nombre -- no hace falta que se llame "Instalaciones".
//
//   Columna "limite" (G, opcional): déjela VACÍA para que esa
//   instalación use el límite general (LIMITE_USOS_GRATIS, más abajo).
//   Para darle a un invitado estratégico más usos gratis (50, 100, lo
//   que sea), escriba ese número en su fila, columna "limite" -- toma
//   efecto de inmediato, sin volver a desplegar nada. La fila de cada
//   instalación se crea sola en su primer uso, así que primero déjelo
//   abrir el plugin una vez y luego edite su límite ahí.
//
// PASO 2 -- Apps Script:
//   Extensiones > Apps Script. Borre el contenido de Code.gs y pegue
//   este archivo completo. Cambie CLAVE_SECRETA por un secreto largo y
//   único (por ejemplo, generado con `python -c "import secrets;
//   print(secrets.token_urlsafe(32))"`). Guarde el proyecto.
//
// PASO 3 -- Desplegar como aplicación web:
//   Implementar > Nueva implementación > tipo "Aplicación web".
//     Ejecutar como: Yo (su cuenta)
//     Quién tiene acceso: Cualquier usuario
//   Autorice los permisos que pida. Copie la URL resultante (termina en
//   /exec) y péguela en hydroandes_sym_bim/core/licencia.py, en la
//   constante URL_BACKEND_LICENCIA.
//
// PASO 4 -- Generar claves de licencia para un cliente:
//   Necesita el "id de instalación" de esa persona (se lo puede pedir --
//   aparece en el diálogo de licencia, o en
//   ~/.hydroandes_sym_bim_licencia/estado.json de su equipo). Con ese id,
//   corra scripts/generar_clave_licencia.py (fuera de este repo,
//   con la MISMA CLAVE_SECRETA que puso aquí) para obtener la clave que
//   le entrega al cliente.
//
// Para dar usos extra o resetear el contador de alguien a mano: abra la
// hoja de cálculo, busque su fila por "id", y edite la columna "usos"
// o "licencia" directamente.

var LIMITE_USOS_GRATIS = 10;
var CLAVE_SECRETA = "PON_AQUI_UN_SECRETO_LARGO_Y_UNICO"; // cambiar antes de desplegar; no compartir

function doPost(e) {
  var datos = JSON.parse(e.postData.contents);
  var accion = datos.accion;
  var id = String(datos.id || "").trim();
  if (!id) {
    return _json({ok: false, mensaje: "Falta el id de instalación."});
  }

  var hoja = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];
  var fila = _buscarOCrearFila(hoja, id);

  if (accion === "registrar_uso") {
    var usos = Number(hoja.getRange(fila, 4).getValue()) || 0;
    var licencia = hoja.getRange(fila, 5).getValue() === true;
    var limite = _limiteDeFila(hoja, fila);
    if (!licencia) {
      usos = usos + 1;
      hoja.getRange(fila, 4).setValue(usos);
    }
    hoja.getRange(fila, 3).setValue(new Date());
    return _json({
      ok: true, usos: usos, limite: limite,
      licencia_activada: licencia, bloqueado: (!licencia && usos > limite)
    });
  }

  if (accion === "consultar") {
    var usos2 = Number(hoja.getRange(fila, 4).getValue()) || 0;
    var licencia2 = hoja.getRange(fila, 5).getValue() === true;
    var limite2 = _limiteDeFila(hoja, fila);
    return _json({
      ok: true, usos: usos2, limite: limite2,
      licencia_activada: licencia2, bloqueado: (!licencia2 && usos2 > limite2)
    });
  }

  if (accion === "activar_licencia") {
    var clave = String(datos.clave || "").trim().toUpperCase().replace(/-/g, "");
    var esperada = _calcularClave(id);
    if (clave === esperada) {
      hoja.getRange(fila, 5).setValue(true);
      hoja.getRange(fila, 6).setValue("Licencia activada " + new Date());
      return _json({ok: true, licencia_activada: true, mensaje: "Licencia activada correctamente."});
    }
    return _json({ok: false, licencia_activada: false, mensaje: "Clave inválida para esta instalación."});
  }

  return _json({ok: false, mensaje: "Acción no reconocida: " + accion});
}

// Debe coincidir EXACTAMENTE con la lógica de
// scripts/generar_clave_licencia.py (mismo secreto, mismo HMAC-SHA256,
// mismos primeros 16 caracteres hexadecimales en mayúsculas).
function _calcularClave(id) {
  var firma = Utilities.computeHmacSha256Signature(id, CLAVE_SECRETA);
  var hex = firma.map(function (b) {
    var v = (b < 0) ? b + 256 : b;
    var s = v.toString(16);
    return s.length === 1 ? "0" + s : s;
  }).join("").toUpperCase();
  return hex.substring(0, 16);
}

// Límite efectivo de una fila: si la columna "limite" (G, 7) tiene un
// número mayor a 0, se usa ese (para invitados estratégicos con más
// usos gratis); si está vacía o no es un número válido, se usa el
// límite general LIMITE_USOS_GRATIS.
function _limiteDeFila(hoja, fila) {
  var valor = hoja.getRange(fila, 7).getValue();
  var numero = Number(valor);
  if (valor !== "" && !isNaN(numero) && numero > 0) {
    return numero;
  }
  return LIMITE_USOS_GRATIS;
}

function _buscarOCrearFila(hoja, id) {
  var datos = hoja.getDataRange().getValues();
  for (var i = 1; i < datos.length; i++) {
    if (String(datos[i][0]) === id) {
      return i + 1;
    }
  }
  var nuevaFila = hoja.getLastRow() + 1;
  hoja.getRange(nuevaFila, 1).setValue(id);
  hoja.getRange(nuevaFila, 2).setValue(new Date());
  hoja.getRange(nuevaFila, 4).setValue(0);
  hoja.getRange(nuevaFila, 5).setValue(false);
  return nuevaFila;
}

function _json(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
