package com.vigia.app.data

// Como se muestra en la UI un nivel de puntos NEWS-2 (0-3): texto + color.
data class Categoria(val etiqueta: String, val colorHex: Long)

// Traduce el puntaje NEWS-2 de un signo individual (0 a 3) a una
// categoria visual. 3 (el maximo) se agrupa junto con cualquier valor
// mayor como "Riesgo alto" por seguridad (else cubre 3 y cualquier otro caso).
fun categoriaPuntos(puntos: Int): Categoria = when (puntos) {
    0 -> Categoria("Normal", 0xFF4CAF50)
    1 -> Categoria("Riesgo bajo", 0xFFFFC107)
    2 -> Categoria("Riesgo medio", 0xFFFF9800)
    else -> Categoria("Riesgo alto", 0xFFF44336)
}

// Puntos NEWS-2 segun frecuencia cardiaca (bpm). La tabla NEWS-2 castiga
// tanto bradicardia (muy lento) como taquicardia (muy rapido); el rango
// normal (51-90) es el unico que da 0 puntos.
fun puntosHr(hr: Int?): Int? = hr?.let {
    when {
        it <= 40 -> 3
        it <= 50 -> 1
        it <= 90 -> 0
        it <= 110 -> 1
        it <= 130 -> 2
        else -> 3
    }
}

// Puntos NEWS-2 segun SpO2 (%). Mientras mas baja la saturacion de
// oxigeno, mayor el puntaje (peor el estado).
fun puntosSpo2(spo2: Int?): Int? = spo2?.let {
    when {
        it <= 91 -> 3
        it <= 93 -> 2
        it <= 95 -> 1
        else -> 0
    }
}

// Puntos NEWS-2 segun temperatura corporal (°C). Tanto la hipotermia
// (muy baja) como la fiebre alta dan puntos; el rango 36.1-38.0 es normal.
fun puntosTemp(temp: Double?): Int? = temp?.let {
    when {
        it <= 35.0 -> 3
        it <= 36.0 -> 1
        it <= 38.0 -> 0
        it <= 39.0 -> 1
        else -> 2
    }
}

// Puntos NEWS-2 segun frecuencia respiratoria (rpm). El rango normal
// (9-20) da 0; por fuera de ahi, mas puntos mientras mas alejado.
fun puntosRr(rr: Int?): Int? = rr?.let {
    when {
        it <= 8 -> 3
        it <= 11 -> 1
        it <= 20 -> 0
        it <= 24 -> 2
        else -> 3
    }
}

// Color segun el puntaje NEWS-2 TOTAL (no el de un signo individual):
// gris si aun no hay datos, y de verde a rojo segun los umbrales clinicos
// de riesgo (>=7 critico, >=5 riesgo medio, >=1 riesgo bajo, 0 estable).
fun colorPorTotal(total: Int?): Long = when {
    total == null -> 0xFF9E9E9E
    total >= 7 -> 0xFFF44336
    total >= 5 -> 0xFFFF9800
    total >= 1 -> 0xFFFFC107
    else -> 0xFF4CAF50
}
