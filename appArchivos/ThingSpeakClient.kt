package com.vigia.app.data

import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.TimeZone

// Snapshot de los ultimos valores conocidos de cada signo vital, cada uno
// con su propia marca de tiempo (millis) porque, al rotar un campo por
// mensaje en ThingSpeak, no todos se actualizan al mismo tiempo.
data class Vitales(
    val hr: String? = null,
    val hrMillis: Long? = null,
    val spo2: String? = null,
    val spo2Millis: Long? = null,
    val temp: String? = null,
    val tempMillis: Long? = null,
    val rr: String? = null,
    val rrMillis: Long? = null,
    val paPuntos: String? = null,
    val paMillis: Long? = null,
    val news2Total: String? = null,
    val news2Millis: Long? = null,
    val nodoId: String? = null
)

// Un punto del historico de alertas: hora y puntaje NEWS-2 total en ese momento.
data class AlertaHistorial(val millis: Long, val total: Int)

object ThingSpeakClient {
    private const val CHANNEL_ID = "xxxxxxxx"
    //le puse xxxxxxxx para no publicar las credenciales
    private const val READ_API_KEY = "xxxxxxxx"

    // results=30: suficiente para reconstruir el valor mas reciente de los
    // 7 campos aunque ThingSpeak solo reciba uno por mensaje (rotacion).
    private const val URL_FEEDS =
        "https://api.thingspeak.com/channels/$CHANNEL_ID/feeds.json?api_key=$READ_API_KEY&results=30"
    // results=200: ventana mas grande para graficar el historico y buscar alertas pasadas.
    private const val URL_FEEDS_HISTORIAL =
        "https://api.thingspeak.com/channels/$CHANNEL_ID/feeds.json?api_key=$READ_API_KEY&results=200"

    // ThingSpeak devuelve las fechas en este formato ISO-8601 en UTC.
    private val formatoFecha = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US).apply {
        timeZone = TimeZone.getTimeZone("UTC")
    }

    // org.json's optString devuelve el texto literal "null" en vez de null
    // de Kotlin cuando el campo es JSON null. Esta funcion lo corrige.
    private fun JSONObject.stringOrNull(key: String): String? {
        return if (isNull(key)) null else optString(key, null)
    }

    private fun parseFecha(texto: String): Long? {
        return try {
            formatoFecha.parse(texto)?.time
        } catch (e: Exception) {
            null
        }
    }

    // Llamada HTTP generica: trae el JSON de ThingSpeak y devuelve solo
    // el arreglo "feeds" (las filas de datos), que es lo que usan las
    // funciones de abajo.
    private fun obtenerFeeds(url: String): JSONArray {
        val texto = URL(url).openConnection().let { conn ->
            conn as HttpURLConnection
            conn.inputStream.bufferedReader().use { it.readText() }
        }
        return JSONObject(texto).getJSONArray("feeds")
    }

    // Reconstruye el ultimo valor conocido de cada uno de los 7 campos.
    // Como la Raspberry publica un solo campo por mensaje (round-robin),
    // recorre las ultimas 30 filas de atras hacia adelante (mas nuevo
    // primero) y se queda con la PRIMERA ocurrencia no nula de cada campo:
    // esa es su valor y hora mas recientes, sin importar que los demas
    // campos de esa misma fila esten vacios.
    fun fetchLatest(): Vitales {
        val feeds = obtenerFeeds(URL_FEEDS)

        var hr: String? = null; var hrMillis: Long? = null
        var spo2: String? = null; var spo2Millis: Long? = null
        var temp: String? = null; var tempMillis: Long? = null
        var rr: String? = null; var rrMillis: Long? = null
        var paPuntos: String? = null; var paMillis: Long? = null
        var news2Total: String? = null; var news2Millis: Long? = null
        var nodoId: String? = null

        for (i in feeds.length() - 1 downTo 0) {
            val entrada = feeds.getJSONObject(i)
            val fecha = entrada.optString("created_at", null)?.let { parseFecha(it) }

            if (hr == null) entrada.stringOrNull("field1")?.let { hr = it; hrMillis = fecha }
            if (spo2 == null) entrada.stringOrNull("field2")?.let { spo2 = it; spo2Millis = fecha }
            if (temp == null) entrada.stringOrNull("field3")?.let { temp = it; tempMillis = fecha }
            if (rr == null) entrada.stringOrNull("field4")?.let { rr = it; rrMillis = fecha }
            if (paPuntos == null) entrada.stringOrNull("field5")?.let { paPuntos = it; paMillis = fecha }
            if (news2Total == null) entrada.stringOrNull("field6")?.let { news2Total = it; news2Millis = fecha }
            // field7 (node_id) no cambia de valor, asi que no necesita su propia marca de tiempo.
            if (nodoId == null) entrada.stringOrNull("field7")?.let { nodoId = it }
        }

        return Vitales(
            hr, hrMillis, spo2, spo2Millis, temp, tempMillis, rr, rrMillis,
            paPuntos, paMillis, news2Total, news2Millis, nodoId
        )
    }

    // Trae solo las lecturas donde el NEWS-2 total fue >= umbral (alerta
    // real), de la mas reciente a la mas antigua, hasta un maximo de filas.
    fun fetchHistorialAlertas(umbral: Int = 5, maximo: Int = 10): List<AlertaHistorial> {
        val feeds = obtenerFeeds(URL_FEEDS_HISTORIAL)
        val alertas = mutableListOf<AlertaHistorial>()

        for (i in feeds.length() - 1 downTo 0) {
            val entrada = feeds.getJSONObject(i)
            val totalStr = entrada.stringOrNull("field6") ?: continue
            val total = totalStr.toIntOrNull() ?: continue
            if (total < umbral) continue
            val fecha = entrada.optString("created_at", null)?.let { parseFecha(it) } ?: continue
            alertas.add(AlertaHistorial(fecha, total))
            if (alertas.size >= maximo) break
        }
        return alertas
    }

    // Trae el historico COMPLETO del puntaje NEWS-2 (no solo las alertas),
    // en orden cronologico, para dibujar la grafica de tendencia. takeLast
    // se queda con los "maximo" mas recientes ya en orden correcto para graficar.
    fun fetchHistorialNews2Total(maximo: Int = 30): List<AlertaHistorial> {
        val feeds = obtenerFeeds(URL_FEEDS_HISTORIAL)
        val lista = mutableListOf<AlertaHistorial>()
        for (i in 0 until feeds.length()) {
            val entrada = feeds.getJSONObject(i)
            val totalStr = entrada.stringOrNull("field6") ?: continue
            val total = totalStr.toIntOrNull() ?: continue
            val fecha = entrada.optString("created_at", null)?.let { parseFecha(it) } ?: continue
            lista.add(AlertaHistorial(fecha, total))
        }
        return lista.takeLast(maximo)
    }
}
