package com.vigia.app

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Paint
import android.graphics.Color as ColorAndroid
import android.net.Uri
import android.os.Bundle
import android.util.Patterns
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.google.firebase.auth.FirebaseAuth
import com.google.firebase.auth.FirebaseAuthInvalidCredentialsException
import com.google.firebase.auth.FirebaseAuthUserCollisionException
import com.google.firebase.auth.FirebaseAuthWeakPasswordException
import com.google.firebase.auth.UserProfileChangeRequest
import com.vigia.app.data.AlertaHistorial
import com.vigia.app.data.ThingSpeakClient
import com.vigia.app.data.Vitales
import com.vigia.app.data.categoriaPuntos
import com.vigia.app.data.colorPorTotal
import com.vigia.app.data.puntosHr
import com.vigia.app.data.puntosRr
import com.vigia.app.data.puntosSpo2
import com.vigia.app.data.puntosTemp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import java.text.SimpleDateFormat
import java.util.Locale
import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import androidx.annotation.RequiresApi
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import java.io.File

// Paleta de colores de la app. Se usa en vez de colores sueltos para que
// toda la UI comparta la misma identidad visual (fondo, tarjetas, acentos).
object VigiaColors {
    val Navy = Color(0xFF2C3E6B)
    val Teal = Color(0xFF6FC3C3)
    val LoginCard = Color(0xFFBFD9EE)
    val Background = Color(0xFFF7FAFD)
}

// Se usa solo si aun no ha llegado ningun dato de la Raspberry (datos.nodoId == null).
// En cuanto llega el primer feed, el nodo mostrado se toma de field7 (ver nodoMostrado()).
const val NODO_ID_FALLBACK = "pi3-001"
const val CAMA_PACIENTE = "Cama 1"

// Si pasan mas de 150s (2.5 min) sin ningun campo nuevo, se asume que el nodo
// esta desconectado. Da margen al ciclo de rotacion de ThingSpeak (7 campos * 15s = 105s).
const val UMBRAL_CONEXION_MS = 150_000L

// El nombre del nodo ya no esta quemado en la app: se lee del campo field7
// (node_id) que publica la Raspberry via SenML. Mientras no llegue ese dato
// (primer arranque, sin conexion) se muestra el fallback de arriba.
fun nodoMostrado(datos: Vitales): String = datos.nodoId ?: NODO_ID_FALLBACK

// "Conectado" no depende del sensor ni del valor de los signos vitales,
// solo de que haya llegado algun campo nuevo desde ThingSpeak hace menos
// de UMBRAL_CONEXION_MS. Si la Raspberry deja de publicar (se cae el script,
// se pierde el WiFi, falla el MQTT), este valor pasa a false con el tiempo.
fun estaConectado(datos: Vitales): Boolean {
    val masReciente = listOfNotNull(
        datos.hrMillis, datos.spo2Millis, datos.tempMillis,
        datos.rrMillis, datos.paMillis, datos.news2Millis
    ).maxOrNull() ?: return false
    return System.currentTimeMillis() - masReciente < UMBRAL_CONEXION_MS
}

// Las 5 pantallas de la app. La navegacion se maneja con un simple estado
// (no con Navigation Compose) porque el flujo es lineal y pequeño.
enum class Pantalla { LOGIN, REGISTRO, HOME, DETALLE, PERFIL }

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme {
                Surface(modifier = Modifier.fillMaxSize(), color = VigiaColors.Background) {
                    VigiaApp()
                }
            }
        }
    }
}

// Composable raiz: controla que pantalla se muestra, mantiene los datos
// mas recientes del paciente (datos) y decide si mostrar la alerta critica.
// Al estar arriba de todo, el polling y la alerta funcionan sin importar
// en que pantalla este el usuario (Home, Detalle o Perfil).
@Composable
fun VigiaApp() {
    var pantalla by remember { mutableStateOf(Pantalla.LOGIN) }
    var datos by remember { mutableStateOf(Vitales()) }
    var alertaCerrada by remember { mutableStateOf(false) }

    // Solo se hace polling mientras el usuario esta "dentro" de la app
    // (con sesion iniciada); en Login/Registro no tiene sentido consultar.
    val sesionActiva = pantalla == Pantalla.HOME || pantalla == Pantalla.DETALLE || pantalla == Pantalla.PERFIL

    // Consulta ThingSpeak cada 10 segundos mientras haya sesion activa.
    // Los errores de red se ignoran (se mantienen los ultimos datos buenos)
    // para que un corte de internet momentaneo no rompa la pantalla.
    LaunchedEffect(sesionActiva) {
        while (sesionActiva) {
            try {
                datos = withContext(Dispatchers.IO) { ThingSpeakClient.fetchLatest() }
            } catch (_: Exception) {
            }
            delay(10000)
        }
    }

    // Traduce cada signo vital a puntos NEWS-2 (0-3) para saber cuales
    // estan en nivel critico (3 puntos) y armar el mensaje de la alerta.
    val pHr = puntosHr(datos.hr?.toIntOrNull())
    val pSpo2 = puntosSpo2(datos.spo2?.toIntOrNull())
    val pTemp = puntosTemp(datos.temp?.toDoubleOrNull())
    val pRr = puntosRr(datos.rr?.toIntOrNull())
    val pPa = datos.paPuntos?.toIntOrNull()

    val causas = mutableListOf<String>()
    if (pHr == 3) causas.add("Frecuencia cardíaca anormal (${datos.hr} bpm)")
    if (pSpo2 == 3) causas.add("Saturación de oxígeno crítica (${datos.spo2}%)")
    if (pTemp == 3) causas.add("Temperatura crítica (${datos.temp}°C)")
    if (pRr == 3) causas.add("Frecuencia respiratoria crítica (${datos.rr} rpm)")
    if (pPa == 3) causas.add("Presión arterial en riesgo alto")

    // Es critico si algun signo individual esta en 3 puntos, o si el
    // puntaje NEWS-2 total llega a 7 o mas (umbral clinico de riesgo alto).
    val total = datos.news2Total?.toIntOrNull()
    val esCritico = causas.isNotEmpty() || (total != null && total >= 7)

    // Si el paciente deja de estar critico, se "re-arma" la alerta para
    // que la proxima vez que vuelva a ser critico, se muestre de nuevo
    // (si no se hiciera esto, quedaria cerrada para siempre tras el primer ACEPTAR).
    if (!esCritico && alertaCerrada) {
        alertaCerrada = false
    }

    when (pantalla) {
        Pantalla.LOGIN -> LoginScreen(
            onLoginSuccess = { pantalla = Pantalla.HOME },
            onIrARegistro = { pantalla = Pantalla.REGISTRO }
        )
        Pantalla.REGISTRO -> RegistroScreen(
            onRegistroExitoso = { pantalla = Pantalla.HOME },
            onVolver = { pantalla = Pantalla.LOGIN }
        )
        Pantalla.HOME -> HomeScreen(
            datos = datos,
            onAbrirPaciente = { pantalla = Pantalla.DETALLE },
            onAbrirPerfil = { pantalla = Pantalla.PERFIL }
        )
        Pantalla.DETALLE -> VitalsScreen(datos = datos, onVolver = { pantalla = Pantalla.HOME })
        Pantalla.PERFIL -> ProfileScreen(
            onVolver = { pantalla = Pantalla.HOME },
            onLogout = { pantalla = Pantalla.LOGIN }
        )
    }

    // Alerta global: se dibuja encima de cualquier pantalla (Home, Detalle
    // o Perfil) porque vive en VigiaApp y no dentro de una pantalla puntual.
    // onDismissRequest vacio = no se puede cerrar tocando fuera, solo con ACEPTAR.
    if (esCritico && !alertaCerrada) {
        AlertDialog(
            onDismissRequest = { },
            containerColor = Color(0xFFF44336),
            title = { Text("¡ALERTA CRÍTICA!", color = Color.White) },
            text = {
                Column {
                    Text("Nodo ${nodoMostrado(datos)} — Puntaje NEWS-2: ${total ?: "—"}", color = Color.White)
                    if (causas.isNotEmpty()) {
                        Spacer(modifier = Modifier.height(8.dp))
                        Text("Causa:", color = Color.White)
                        causas.forEach { Text("• $it", color = Color.White) }
                    }
                }
            },
            confirmButton = {
                TextButton(onClick = { alertaCerrada = true }) {
                    Text("ACEPTAR", color = Color.White)
                }
            }
        )
    }
}

// Valida formato de correo con el patron estandar de Android.
@RequiresApi(Build.VERSION_CODES.FROYO)
fun emailValido(email: String): Boolean =
    Patterns.EMAIL_ADDRESS.matcher(email).matches()

// Reglas de contraseña pedidas por el profesor: al menos una mayuscula
// y un caracter que no sea letra ni numero (especial).
fun passwordTieneMayuscula(password: String): Boolean = password.any { it.isUpperCase() }
fun passwordTieneCaracterEspecial(password: String): Boolean = password.any { !it.isLetterOrDigit() }

// Traduce las excepciones de Firebase Auth a mensajes en español,
// entendibles para el usuario en vez del texto tecnico en ingles.
fun mensajeErrorRegistro(e: Exception?): String = when (e) {
    is FirebaseAuthWeakPasswordException -> "La contraseña debe tener al menos 6 caracteres"
    is FirebaseAuthInvalidCredentialsException -> "El correo no tiene un formato válido (ej: nombre@dominio.com)"
    is FirebaseAuthUserCollisionException -> "Ya existe una cuenta registrada con ese correo"
    else -> "Error: ${e?.message}"
}

// Foto de perfil circular. Si uri es null (usuario sin foto) muestra un
// icono por defecto; si no, carga la imagen en segundo plano (Dispatchers.IO)
// para no bloquear la UI con la decodificacion del bitmap.
@Composable
fun FotoPerfil(uri: Uri?, tamaño: Dp) {
    val context = LocalContext.current
    var bitmap by remember(uri) { mutableStateOf<Bitmap?>(null) }

    LaunchedEffect(uri) {
        if (uri != null) {
            bitmap = withContext(Dispatchers.IO) {
                try {
                    context.contentResolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it) }
                } catch (e: Exception) {
                    null
                }
            }
        }
    }

    if (bitmap != null) {
        Image(
            bitmap = bitmap!!.asImageBitmap(),
            contentDescription = null,
            modifier = Modifier.size(tamaño).clip(CircleShape),
            contentScale = ContentScale.Crop
        )
    } else {
        Box(
            modifier = Modifier.size(tamaño).background(VigiaColors.LoginCard, CircleShape),
            contentAlignment = Alignment.Center
        ) {
            Icon(Icons.Filled.Person, contentDescription = null, tint = VigiaColors.Navy, modifier = Modifier.size(tamaño / 2))
        }
    }
}

// Pantalla de inicio de sesion con Firebase Auth (email + contraseña).
@Composable
fun LoginScreen(onLoginSuccess: () -> Unit, onIrARegistro: () -> Unit) {
    val auth = remember { FirebaseAuth.getInstance() }

    var email by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var mensaje by remember { mutableStateOf("") }
    var cargando by remember { mutableStateOf(false) }

    Column(
        modifier = Modifier.fillMaxSize().padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Spacer(modifier = Modifier.height(32.dp))

        Image(
            painter = painterResource(id = R.drawable.icono_vigia),
            contentDescription = null,
            modifier = Modifier.size(250.dp)
        )
        Spacer(modifier = Modifier.height(32.dp))

        Column(
            modifier = Modifier
                .fillMaxWidth()
                .weight(1f)
                .background(VigiaColors.LoginCard, RoundedCornerShape(30.dp))
                .padding(24.dp)
        ) {
            Text("Login", fontWeight = FontWeight.Bold, color = VigiaColors.Navy)
            OutlinedTextField(
                value = email,
                onValueChange = { email = it },
                modifier = Modifier.fillMaxWidth().background(Color.White, RoundedCornerShape(8.dp))
            )
            Spacer(modifier = Modifier.height(16.dp))
            Text("Contraseña", fontWeight = FontWeight.Bold, color = VigiaColors.Navy)
            OutlinedTextField(
                value = password,
                onValueChange = { password = it },
                visualTransformation = PasswordVisualTransformation(),
                modifier = Modifier.fillMaxWidth().background(Color.White, RoundedCornerShape(8.dp))
            )
            Spacer(modifier = Modifier.height(20.dp))

            // Validaciones en orden: primero campos vacios, luego formato
            // de correo, y solo si todo esta bien se llama a Firebase.
            Button(
                onClick = {
                    when {
                        email.isBlank() || password.isBlank() -> mensaje = "Completa correo y contraseña"
                        !emailValido(email) -> mensaje = "El correo no tiene un formato válido (ej: nombre@dominio.com)"
                        else -> {
                            cargando = true
                            auth.signInWithEmailAndPassword(email, password)
                                .addOnCompleteListener { task ->
                                    cargando = false
                                    if (task.isSuccessful) onLoginSuccess()
                                    else mensaje = mensajeErrorRegistro(task.exception)
                                }
                        }
                    }
                },
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(24.dp),
                colors = ButtonDefaults.buttonColors(containerColor = VigiaColors.Navy),
                enabled = !cargando
            ) { Text("iniciar") }

            Spacer(modifier = Modifier.height(8.dp))

            OutlinedButton(
                onClick = onIrARegistro,
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(24.dp)
            ) { Text("Registrarse") }
        }

        Spacer(modifier = Modifier.height(16.dp))
        if (mensaje.isNotEmpty()) Text(mensaje, color = Color.Red)
    }
}

// Pantalla de registro: nombre, correo, contraseña y foto de perfil
// (camara o galeria). Crea el usuario en Firebase Auth y le asigna
// nombre/foto con updateProfile (sin usar Firebase Storage).
@RequiresApi(Build.VERSION_CODES.KITKAT)
@Composable
fun RegistroScreen(onRegistroExitoso: () -> Unit, onVolver: () -> Unit) {
    val auth = remember { FirebaseAuth.getInstance() }
    val context = LocalContext.current

    var nombre by remember { mutableStateOf("") }
    var email by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var fotoUri by remember { mutableStateOf<Uri?>(null) }
    var uriTemporal by remember { mutableStateOf<Uri?>(null) }
    var mensaje by remember { mutableStateOf("") }
    var cargando by remember { mutableStateOf(false) }

    // Selector de galeria: el sistema entrega directamente el Uri de la foto elegida.
    val selectorGaleria = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.PickVisualMedia()
    ) { uri -> if (uri != null) fotoUri = uri }

    // La camara necesita un archivo destino creado de antemano (uriTemporal);
    // si la foto se toma con exito, esa se vuelve la foto de perfil.
    val lanzadorCamara = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.TakePicture()
    ) { exito -> if (exito) fotoUri = uriTemporal }

    // Si el permiso de camara no estaba concedido, se pide aqui y, si lo
    // aceptan, se lanza la camara de inmediato (sin que el usuario tenga
    // que tocar el boton una segunda vez).
    val lanzadorPermisoCamara = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission()
    ) { concedido ->
        if (concedido) {
            val nuevoUri = crearArchivoImagenTemporal(context)
            uriTemporal = nuevoUri
            lanzadorCamara.launch(nuevoUri)
        } else {
            mensaje = "Se necesita permiso de cámara para tomar la foto"
        }
    }

    Column(
        modifier = Modifier.fillMaxSize().padding(24.dp).verticalScroll(rememberScrollState()),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Row(modifier = Modifier.fillMaxWidth()) {
            IconButton(onClick = onVolver) {
                Icon(Icons.Filled.ArrowBack, contentDescription = "Volver", tint = VigiaColors.Navy)
            }
        }

        Text("Crear cuenta", fontSize = 24.sp, fontWeight = FontWeight.Bold, color = VigiaColors.Navy)
        Spacer(modifier = Modifier.height(16.dp))

        FotoPerfil(uri = fotoUri, tamaño = 100.dp)
        Spacer(modifier = Modifier.height(8.dp))

        Row {
            OutlinedButton(onClick = {
                // Si ya hay permiso, va directo a la camara; si no, lo pide primero.
                val permisoActual = ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA)
                if (permisoActual == PackageManager.PERMISSION_GRANTED) {
                    val nuevoUri = crearArchivoImagenTemporal(context)
                    uriTemporal = nuevoUri
                    lanzadorCamara.launch(nuevoUri)
                } else {
                    lanzadorPermisoCamara.launch(Manifest.permission.CAMERA)
                }
            }) { Text("Tomar foto") }

            Spacer(modifier = Modifier.width(8.dp))

            OutlinedButton(onClick = {
                selectorGaleria.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly))
            }) { Text("Galería") }
        }

        Spacer(modifier = Modifier.height(16.dp))

        OutlinedTextField(
            value = nombre,
            onValueChange = { nombre = it },
            label = { Text("Nombre completo") },
            modifier = Modifier.fillMaxWidth()
        )
        Spacer(modifier = Modifier.height(8.dp))
        OutlinedTextField(
            value = email,
            onValueChange = { email = it },
            label = { Text("Correo") },
            supportingText = { Text("Formato: nombre@dominio.com") },
            modifier = Modifier.fillMaxWidth()
        )
        Spacer(modifier = Modifier.height(8.dp))
        OutlinedTextField(
            value = password,
            onValueChange = { password = it },
            label = { Text("Contraseña") },
            visualTransformation = PasswordVisualTransformation(),
            supportingText = { Text("Mínimo 6 caracteres, con una mayúscula y un carácter especial") },
            modifier = Modifier.fillMaxWidth()
        )

        Spacer(modifier = Modifier.height(20.dp))

        // Validaciones en cascada: se detiene en la primera que falle y
        // muestra su mensaje especifico. Solo si todas pasan, crea la cuenta.
        Button(
            onClick = {
                when {
                    nombre.isBlank() -> mensaje = "Escribe tu nombre"
                    !emailValido(email) -> mensaje = "El correo no tiene un formato válido (ej: nombre@dominio.com)"
                    password.length < 6 -> mensaje = "La contraseña debe tener al menos 6 caracteres"
                    !passwordTieneMayuscula(password) -> mensaje = "La contraseña debe tener al menos una letra mayúscula"
                    !passwordTieneCaracterEspecial(password) -> mensaje = "La contraseña debe tener al menos un carácter especial (ej: !@#$%)"
                    else -> {
                        cargando = true
                        auth.createUserWithEmailAndPassword(email, password)
                            .addOnCompleteListener { task ->
                                if (task.isSuccessful) {
                                    // setPhotoUri guarda solo la referencia al Uri local/galeria,
                                    // no sube el archivo a ningun servidor (no se usa Firebase Storage).
                                    val actualizacion = UserProfileChangeRequest.Builder()
                                        .setDisplayName(nombre)
                                        .apply { fotoUri?.let { setPhotoUri(it) } }
                                        .build()
                                    auth.currentUser?.updateProfile(actualizacion)
                                        ?.addOnCompleteListener {
                                            cargando = false
                                            onRegistroExitoso()
                                        }
                                } else {
                                    cargando = false
                                    mensaje = mensajeErrorRegistro(task.exception)
                                }
                            }
                    }
                }
            },
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(24.dp),
            colors = ButtonDefaults.buttonColors(containerColor = VigiaColors.Navy),
            enabled = !cargando
        ) { Text("Registrarse") }

        Spacer(modifier = Modifier.height(12.dp))
        if (mensaje.isNotEmpty()) Text(mensaje, color = Color.Red)
    }
}

// Crea un archivo temporal en cache donde la camara va a guardar la foto,
// y devuelve un Uri "seguro" via FileProvider (la camara no puede escribir
// directo a un File:// por restricciones de Android).
fun crearArchivoImagenTemporal(context: android.content.Context): Uri {
    val archivo = File.createTempFile("foto_", ".jpg", context.cacheDir)
    return FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", archivo)
}

// Convierte una marca de tiempo absoluta en un texto relativo ("hace 5s",
// "hace 2min"), para mostrar que tan reciente es cada lectura.
fun tiempoRelativo(millis: Long?): String {
    if (millis == null) return "sin datos"
    val segundos = (System.currentTimeMillis() - millis) / 1000
    return when {
        segundos < 60 -> "hace ${segundos}s"
        segundos < 3600 -> "hace ${segundos / 60}min"
        else -> "hace ${segundos / 3600}h"
    }
}

// Grafica de lineas del historico de NEWS-2, dibujada a mano con Canvas
// (sin libreria externa de graficos). Dibuja lineas guia, puntos, la curva
// y las etiquetas de hora al inicio y al final del eje X.
@Composable
fun GraficaNews2(puntos: List<AlertaHistorial>) {
    if (puntos.size < 2) {
        Text("Aún no hay suficiente historial para graficar", color = Color.Gray, fontSize = 12.sp)
        return
    }
    // Escala vertical dinamica: el maximo del eje se adapta al peor
    // puntaje visto, con un piso de 5 para que la grafica no se vea
    // "toda arriba" cuando los valores son bajos.
    val maxValor = (puntos.maxOf { it.total }.coerceAtLeast(5)) + 1
    val formatoHora = remember { SimpleDateFormat("HH:mm", Locale.getDefault()) }

    Column {
        Text("Puntaje NEWS-2 (escala 0 a $maxValor)", fontSize = 11.sp, color = Color.Gray)

        Canvas(modifier = Modifier.fillMaxWidth().height(180.dp).padding(top = 8.dp)) {
            val margenIzq = 28.dp.toPx()
            val margenAbajo = 20.dp.toPx()
            val anchoGrafico = size.width - margenIzq
            val altoGrafico = size.height - margenAbajo

            val paintEje = Paint().apply {
                color = ColorAndroid.GRAY
                textSize = 10.sp.toPx()
            }

            // Lineas horizontales de referencia en 0, la mitad y el maximo,
            // cada una con su numero al lado izquierdo.
            val niveles = listOf(0, maxValor / 2, maxValor)
            niveles.forEach { nivel ->
                val y = altoGrafico - (nivel / maxValor.toFloat()) * altoGrafico
                drawLine(
                    color = Color.LightGray,
                    start = Offset(margenIzq, y),
                    end = Offset(size.width, y),
                    strokeWidth = 1f
                )
                drawContext.canvas.nativeCanvas.drawText(nivel.toString(), 0f, y + 4.dp.toPx(), paintEje)
            }

            // Un punto por cada lectura del historico, unidos con una linea.
            val pasoX = anchoGrafico / (puntos.size - 1)
            val path = Path()
            puntos.forEachIndexed { i, p ->
                val x = margenIzq + i * pasoX
                val y = altoGrafico - (p.total / maxValor.toFloat()) * altoGrafico
                if (i == 0) path.moveTo(x, y) else path.lineTo(x, y)
                drawCircle(color = VigiaColors.Navy, radius = 4.dp.toPx(), center = Offset(x, y))
            }
            drawPath(path, color = VigiaColors.Teal, style = Stroke(width = 3.dp.toPx()))

            // Hora del primer y ultimo punto, para ubicar el rango temporal
            // de la grafica sin tener que etiquetar cada punto individual.
            drawContext.canvas.nativeCanvas.drawText(
                formatoHora.format(puntos.first().millis), margenIzq, size.height, paintEje
            )
            val textoUltimo = formatoHora.format(puntos.last().millis)
            drawContext.canvas.nativeCanvas.drawText(
                textoUltimo, size.width - paintEje.measureText(textoUltimo), size.height, paintEje
            )
        }
    }
}

// Pantalla principal: saludo, estado actual del paciente (NEWS-2), tarjeta
// resumen del nodo con su estado de conexion, e historico graficado.
@Composable
fun HomeScreen(datos: Vitales, onAbrirPaciente: () -> Unit, onAbrirPerfil: () -> Unit) {
    val usuario = FirebaseAuth.getInstance().currentUser
    val nombreDoctor = usuario?.displayName ?: usuario?.email ?: "Doctor/a"

    var historialNews2 by remember { mutableStateOf(listOf<AlertaHistorial>()) }

    // Se trae el historico una sola vez al entrar a la pantalla (no en
    // cada poll de 10s, porque son 200 registros y no cambia tan seguido).
    LaunchedEffect(Unit) {
        try {
            historialNews2 = withContext(Dispatchers.IO) { ThingSpeakClient.fetchHistorialNews2Total() }
        } catch (_: Exception) { }
    }

    val total = datos.news2Total?.toIntOrNull()
    val colorEstado = Color(colorPorTotal(total))
    val estadoTexto = when {
        total == null -> "Sin datos"
        total >= 7 -> "Crítico"
        total >= 5 -> "Riesgo medio"
        total >= 1 -> "Riesgo bajo"
        else -> "Estable"
    }
    val conectado = estaConectado(datos)

    Column(modifier = Modifier.fillMaxSize()) {
        // Banda superior con foto de perfil, saludo y tarjeta de estado actual.
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .background(VigiaColors.Teal, RoundedCornerShape(bottomStart = 24.dp, bottomEnd = 24.dp))
                .statusBarsPadding()
                .padding(20.dp)
        ) {
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                IconButton(onClick = onAbrirPerfil) {
                    FotoPerfil(uri = usuario?.photoUrl, tamaño = 36.dp)
                }
            }
            Text("Buenos días,", color = Color.White)
            Text(nombreDoctor, color = Color.White, fontSize = 20.sp, fontWeight = FontWeight.Bold)

            Spacer(modifier = Modifier.height(12.dp))
            Column(
                modifier = Modifier.background(Color.White, RoundedCornerShape(12.dp)).padding(12.dp)
            ) {
                Text("Estado actual", color = Color.Gray, fontSize = 12.sp)
                Text("NEWS-2: ${total ?: "—"} — $estadoTexto", color = colorEstado, fontWeight = FontWeight.Bold)
            }
        }

        Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
            Text("Pacientes a cargo", fontWeight = FontWeight.Bold, color = VigiaColors.Navy)
            Spacer(modifier = Modifier.height(8.dp))

            // Tarjeta del (unico) paciente a cargo: nodo, cama, nivel de
            // riesgo y, debajo, si el nodo esta conectado o no.
            Row(
                modifier = Modifier.fillMaxWidth().background(Color.White, RoundedCornerShape(12.dp)).padding(12.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text("Nodo ${nodoMostrado(datos)}", fontWeight = FontWeight.Bold, color = VigiaColors.Navy)
                    Text(CAMA_PACIENTE, color = Color.Gray, fontSize = 12.sp)
                }
                Column(horizontalAlignment = Alignment.End) {
                    Text(estadoTexto, color = colorEstado, fontWeight = FontWeight.Bold)
                    Text(
                        if (conectado) "Conectado" else "No conectado",
                        color = if (conectado) Color(0xFF4CAF50) else Color(0xFFF44336),
                        fontSize = 10.sp
                    )
                }
                Spacer(modifier = Modifier.width(8.dp))
                IconButton(onClick = onAbrirPaciente) {
                    Icon(Icons.Filled.Visibility, contentDescription = "Ver", tint = VigiaColors.Navy)
                }
            }

            Spacer(modifier = Modifier.height(24.dp))
            Text("Histórico NEWS-2", fontWeight = FontWeight.Bold, color = VigiaColors.Navy)
            GraficaNews2(historialNews2)
        }
    }
}

// Pantalla de perfil del doctor: foto, nombre/correo, cantidad de
// pacientes a cargo, historico de alertas criticas y boton de cerrar sesion.
@Composable
fun ProfileScreen(onVolver: () -> Unit, onLogout: () -> Unit) {
    val usuario = FirebaseAuth.getInstance().currentUser
    val nombreDoctor = usuario?.displayName ?: usuario?.email ?: "Doctor/a"
    var historial by remember { mutableStateOf(listOf<AlertaHistorial>()) }
    val formatoHora = remember { SimpleDateFormat("HH:mm", Locale.getDefault()) }

    // Historico de alertas (solo lecturas con NEWS-2 >= umbral), tambien
    // cargado una sola vez al entrar a la pantalla.
    LaunchedEffect(Unit) {
        try {
            historial = withContext(Dispatchers.IO) { ThingSpeakClient.fetchHistorialAlertas() }
        } catch (_: Exception) { }
    }

    Column(modifier = Modifier.fillMaxSize()) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .background(VigiaColors.Teal, RoundedCornerShape(bottomStart = 24.dp, bottomEnd = 24.dp))
                .statusBarsPadding()
                .padding(20.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Row(modifier = Modifier.fillMaxWidth()) {
                IconButton(onClick = onVolver) {
                    Icon(Icons.Filled.ArrowBack, contentDescription = "Volver", tint = Color.White)
                }
            }
            FotoPerfil(uri = usuario?.photoUrl, tamaño = 90.dp)
            Spacer(modifier = Modifier.height(8.dp))
            Text(nombreDoctor, color = Color.White, fontSize = 18.sp, fontWeight = FontWeight.Bold)
            if (usuario?.displayName != null) {
                Text(usuario.email ?: "", color = Color.White, fontSize = 12.sp)
            }
        }

        Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
            Text("Número de pacientes", color = Color.Gray, fontSize = 12.sp)
            // Fijo en 1 porque el proyecto actual solo tiene un nodo/paciente;
            // en un despliegue futuro con varios nodos esto vendria de una consulta.
            Text("1 paciente a cargo", fontSize = 22.sp, fontWeight = FontWeight.Bold, color = VigiaColors.Navy)

            Spacer(modifier = Modifier.height(16.dp))
            Text("Histórico de detecciones", fontWeight = FontWeight.Bold, color = VigiaColors.Navy)
            Spacer(modifier = Modifier.height(8.dp))

            if (historial.isEmpty()) {
                Text("Sin alertas registradas", color = Color.Gray)
            } else {
                historial.forEach { alerta ->
                    Row(
                        modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text(formatoHora.format(alerta.millis), color = VigiaColors.Navy)
                        Spacer(modifier = Modifier.width(8.dp))
                        Text("Puntuación NEWS2", modifier = Modifier.weight(1f), color = VigiaColors.Navy)
                        Box(
                            modifier = Modifier.background(Color(colorPorTotal(alerta.total)), RoundedCornerShape(12.dp))
                                .padding(horizontal = 8.dp, vertical = 2.dp)
                        ) {
                            Text("Score: ${alerta.total}", color = Color.White, fontSize = 12.sp)
                        }
                    }
                }
            }

            Spacer(modifier = Modifier.height(24.dp))
            Button(
                onClick = {
                    FirebaseAuth.getInstance().signOut()
                    onLogout()
                },
                modifier = Modifier.fillMaxWidth(),
                colors = ButtonDefaults.buttonColors(containerColor = Color(0xFFF44336))
            ) { Text("Cerrar Sesión") }
        }
    }
}

// Pantalla de detalle: las 4 tarjetas de signos vitales (HR, SpO2, temp,
// RR), la categoria de presion arterial y el puntaje NEWS-2 total, cada
// uno con su "hace cuanto se actualizo".
@Composable
fun VitalsScreen(datos: Vitales, onVolver: () -> Unit) {
    val pHr = puntosHr(datos.hr?.toIntOrNull())
    val pSpo2 = puntosSpo2(datos.spo2?.toIntOrNull())
    val pTemp = puntosTemp(datos.temp?.toDoubleOrNull())
    val pRr = puntosRr(datos.rr?.toIntOrNull())
    val pPa = datos.paPuntos?.toIntOrNull()

    val total = datos.news2Total?.toIntOrNull()
    val causaCritica = pHr == 3 || pSpo2 == 3 || pTemp == 3 || pRr == 3 || pPa == 3

    // Mismo criterio de "critico" que en VigiaApp, pero aqui solo se usa
    // para pintar el indicador de estado de esta pantalla (no dispara la alerta).
    val (estadoTexto, estadoColor) = when {
        causaCritica || (total != null && total >= 7) -> "Crítico" to Color(0xFFF44336)
        total != null && total >= 5 -> "Riesgo medio" to Color(0xFFFF9800)
        total != null && total >= 1 -> "Riesgo bajo" to Color(0xFFFFC107)
        else -> "Estable" to Color(0xFF4CAF50)
    }

    Column(modifier = Modifier.fillMaxSize()) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .background(VigiaColors.Teal, RoundedCornerShape(bottomStart = 24.dp, bottomEnd = 24.dp))
                .statusBarsPadding()
                .padding(20.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            IconButton(onClick = onVolver) {
                Icon(Icons.Filled.ArrowBack, contentDescription = "Volver", tint = Color.White)
            }
            Column(modifier = Modifier.weight(1f)) {
                Text("Nodo ${nodoMostrado(datos)}", fontSize = 22.sp, fontWeight = FontWeight.Bold, color = Color.White)
                Text(CAMA_PACIENTE, color = Color.White)
            }
            Row(
                modifier = Modifier.background(Color.White, RoundedCornerShape(20.dp)).padding(horizontal = 12.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Box(modifier = Modifier.size(10.dp).background(estadoColor, CircleShape))
                Spacer(modifier = Modifier.width(6.dp))
                Text(estadoTexto, color = estadoColor, fontWeight = FontWeight.Bold)
            }
        }

        Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
            Row(modifier = Modifier.fillMaxWidth()) {
                TarjetaVital("Frecuencia cardiaca", datos.hr, "bpm", pHr, tiempoRelativo(datos.hrMillis), Color(0xFFE53935), Modifier.weight(1f))
                Spacer(modifier = Modifier.width(8.dp))
                TarjetaVital("Saturación de Oxígeno", datos.spo2, "%", pSpo2, tiempoRelativo(datos.spo2Millis), Color(0xFF29B6F6), Modifier.weight(1f))
            }
            Spacer(modifier = Modifier.height(8.dp))
            Row(modifier = Modifier.fillMaxWidth()) {
                TarjetaVital("Temperatura corporal", datos.temp, "°C", pTemp, tiempoRelativo(datos.tempMillis), Color(0xFFFF9800), Modifier.weight(1f))
                Spacer(modifier = Modifier.width(8.dp))
                // Presion arterial se muestra como categoria de riesgo (no en mmHg),
                // por eso esCategoriaDirecta=true y valor=null.
                TarjetaVital("Presión Arterial Sistólica", null, "", pPa, tiempoRelativo(datos.paMillis), VigiaColors.Navy, Modifier.weight(1f), esCategoriaDirecta = true)
            }
            Spacer(modifier = Modifier.height(8.dp))
            Row(modifier = Modifier.fillMaxWidth()) {
                TarjetaVital("Frecuencia Respiratoria", datos.rr, "rpm", pRr, tiempoRelativo(datos.rrMillis), Color(0xFF8E24AA), Modifier.weight(1f))
                Spacer(modifier = Modifier.weight(1f))
            }

            Spacer(modifier = Modifier.height(16.dp))
            Text(
                "Puntaje NEWS-2 total: ${datos.news2Total ?: "—"} (${tiempoRelativo(datos.news2Millis)})",
                fontWeight = FontWeight.Bold,
                color = VigiaColors.Navy
            )
        }
    }
}

// Tarjeta reutilizable para un signo vital: valor + unidad (o solo la
// categoria, si esCategoriaDirecta), etiqueta de riesgo con su color, y
// cuando se actualizo por ultima vez.
@Composable
fun TarjetaVital(
    nombre: String,
    valor: String?,
    unidad: String,
    puntos: Int?,
    actualizado: String,
    colorAcento: Color,
    modifier: Modifier = Modifier,
    esCategoriaDirecta: Boolean = false
) {
    val categoria = puntos?.let { categoriaPuntos(it) }

    Column(modifier = modifier.background(colorAcento.copy(alpha = 0.06f), RoundedCornerShape(12.dp))) {
        // Franja de color arriba de la tarjeta, a modo de acento visual.
        Box(
            modifier = Modifier.fillMaxWidth().height(4.dp)
                .background(colorAcento, RoundedCornerShape(topStart = 12.dp, topEnd = 12.dp))
        )
        Column(modifier = Modifier.padding(10.dp)) {
            Text(nombre, style = MaterialTheme.typography.labelSmall, color = Color.Gray)
            Spacer(modifier = Modifier.height(4.dp))
            if (!esCategoriaDirecta) {
                Row(verticalAlignment = Alignment.Bottom) {
                    Text("${valor ?: "—"}", fontSize = 26.sp, fontWeight = FontWeight.Bold, color = colorAcento)
                    Spacer(modifier = Modifier.width(4.dp))
                    Text(unidad, fontSize = 12.sp, color = Color.Gray, modifier = Modifier.padding(bottom = 4.dp))
                }
            }
            Spacer(modifier = Modifier.height(4.dp))
            if (categoria != null) {
                Box(
                    modifier = Modifier.background(Color(categoria.colorHex).copy(alpha = 0.15f), RoundedCornerShape(8.dp))
                        .padding(horizontal = 8.dp, vertical = 2.dp)
                ) {
                    Text(categoria.etiqueta, color = Color(categoria.colorHex), fontSize = 12.sp, fontWeight = FontWeight.Bold)
                }
            } else {
                Text("Sin datos", color = Color.Gray, fontSize = 12.sp)
            }
            Text(actualizado, style = MaterialTheme.typography.labelSmall, color = Color.LightGray)
        }
    }
}
