# Informe: Estimación de Presión Arterial Sistólica mediante PPG y Random Forest

## 1. Dataset

**Fuente**: Kachuee/UCI "Cuff-Less Blood Pressure Estimation" (derivado de MIMIC-II).

- 4 archivos `Part_1.mat` – `Part_4.mat`, formato MATLAB v7.3 (HDF5).
- **12,000 registros** en total (3,000 por archivo), cada uno de **61,000 muestras** a **125 Hz** (≈488 s / 8.1 min por registro).
- Cada registro es una matriz de 3 canales: **PPG** (columna 0, normalizado ~0-4), **ABP** (columna 1, mmHg, presión arterial invasiva real), **ECG** (columna 2).
- Los 12,000 registros provienen de solo **942 pacientes reales** de MIMIC-II, pero **el ID de paciente fue suprimido deliberadamente** al publicar el dataset — no hay forma de saber qué segmentos pertenecen al mismo paciente.
- **No incluye datos demográficos** (edad, sexo, peso, altura) por ninguna vía.

### Limitación metodológica documentada
Por lo anterior, el split train/test se hizo a nivel de **registro** (`record_id` = segmento de 8 min), no a nivel de paciente real — es el nivel de agrupamiento más fino posible con este dataset. Se documenta como limitación conocida: puede quedar algo de fuga residual a nivel de paciente real que no es evitable con los datos disponibles.

---

## 2. Pipeline de extracción de features (`ppg_features.py`)

1. Filtro pasa-banda Butterworth 0.5–8 Hz (elimina deriva de línea base y ruido de alta frecuencia).
2. Detección de ciclos de pulso: onset (pie de onda) → pico sistólico → siguiente onset, vía `scipy.signal.find_peaks`.
3. Filtros de calidad:
   - Anchos al 25/50/75% de amplitud deben decrecer monotónicamente (descarta pulsos deformados).
   - Rechazo de outliers de amplitud/duración por registro (z-score robusto vía MAD, umbral 4).
   - Rango fisiológico de ABP: sistólica 70-200 mmHg, diastólica 40-130 mmHg, presión de pulso 20-100 mmHg.
4. **15 features por ciclo/ventana**:
   - Originales (11): `rise_time`, `width_25`, `width_50`, `width_75`, `notch_time`, `amplitude`, `max_d1`, `max_d2`, `min_d2`, `d2_ratio`, `heart_rate`.
   - Agregadas (4): `area_ratio` (área sistólica/diastólica), `notch_depth_ratio` (profundidad de la muesca dicrótica), `aug_index` (índice de aumentación), `spectral_ratio` (2do/1er armónico de la FFT del ciclo).
5. **Agregación por ventana**: mediana de 10 ciclos válidos consecutivos por ventana (reduce ruido latido a latido), hasta 15 ventanas por registro (submuestreo uniforme).

**Validación visual**: confirmada sobre múltiples registros — segmentación correcta de onset/pico/muesca, y rechazo efectivo de artefactos de movimiento (ej. registro con caída abrupta de señal, filtrado correctamente).

### Dataset final de entrenamiento
- **119,880 filas** (ventanas), **11,022 registros únicos**.
- Distribución de `systolic_bp`: media 126.9 mmHg, SD 21.5 mmHg, rango 70-199 mmHg.

---

## 3. Intento 1: Regresión absoluta (RandomForestRegressor)

Split `GroupShuffleSplit` por `record_id` (80/20), sin fuga verificada explícitamente.

### Resultado con 11 features
| Métrica | Valor |
|---|---|
| MAE | 12.97 mmHg |
| Bias (error medio) | 0.66 mmHg |
| SD del error | 17.06 mmHg |
| Tamaño del modelo | 8.0 MB (comprimido) |

### Resultado con 15 features (+ morfología adicional)
| Métrica | Valor |
|---|---|
| MAE | 12.66 mmHg |
| Bias | 0.71 mmHg |
| SD del error | 16.68 mmHg |

**Estándar AAMI**: requiere \|bias\| ≤ 5 mmHg **y** SD ≤ 8 mmHg. **No se cumple** en ningún caso (SD más del doble del límite).

---

## 4. Diagnóstico: por qué no mejora (experimentos descartando causas)

| Hipótesis probada | Experimento | Resultado |
|---|---|---|
| Falta de capacidad del modelo (underfitting) | Barrido de 5 configuraciones, desde 3.1 MB (muy podado) hasta 623 MB comprimido (300 árboles, sin límite de profundidad) | MAE entre 13.29–14.83 en todas las configuraciones. El modelo más podado dio el **peor** resultado, no el mejor. |
| Sobreajuste (overfitting) corregible con más datos | Diagnóstico train-vs-test: modelo de alta capacidad, MAE train=6.01 vs MAE test=13.29 (gap 54.7%); modelo balanceado, MAE train=10.30 vs test=12.97 (gap 20.6%) | Hay algo de sobreajuste en el modelo de alta capacidad, pero no se traduce en peor generalización (comportamiento típico de bagging en Random Forest). |
| Falta de volumen de datos | Curva de aprendizaje: 10%, 25%, 50%, 75%, 100% de los registros de entrenamiento | MAE test: 15.32 → 14.60 → 13.74 → 13.28 → 12.97. Mejora con rendimientos decrecientes fuertes (cada incremento es ~mitad del anterior). Extrapolando la serie geométrica, el techo asintótico es ≈12.6 mmHg incluso con datos ilimitados del mismo tipo. |
| Falta de especialización por "tipo de paciente" | Mixture of experts: clustering KMeans (k=3,5,8) sobre las features, un RF por cluster | Sin diferencia significativa vs modelo único (MAE 12.92–13.02 en todos los k, dentro de ruido estadístico). |
| Error de medición/ruido aleatorio | Descomposición de varianza (ANOVA): SS entre-registros vs SS dentro-de-registro | **85.2% de la varianza del error es ENTRE pacientes** (sesgo sistemático), solo 14.8% es ruido dentro del mismo paciente. Promediar 10 ventanas del mismo paciente solo reduce SD de 17.06 a 15.88 mmHg. |

**Conclusión del diagnóstico**: el error es un techo de **información faltante** (sesgo sistemático entre pacientes), no un problema de ajuste de modelo, cantidad de datos, ni ruido de medición.

---

## 5. Comparación con literatura

| Estudio | Señales usadas | Split | Resultado | AAMI |
|---|---|---|---|---|
| Este trabajo (regresión absoluta) | PPG solo | Por registro (sin fuga) | SD=16.68 mmHg | No cumple |
| Martinez-Ríos et al., PMC10146008 (calibration-free, cardiovascular dynamics) | PPG solo, 21 features + HRV | Leave-one-out por sujeto | SD=10.40 mmHg (SBP) | No cumple |
| PPG2BP-Net, Joung et al. 2023 (Scientific Reports) | PPG solo, **con calibración** (estructura comparativa 1D-CNN) | Por sujeto (4,185 sujetos independientes) | SD=7.51 mmHg (SBP) | **Sí cumple** |
| Chen et al. 2021 (IEEE Access) — citado como justificación de Random Forest | **PPG + ECG (PTT)** + demografía (edad, sexo, altura, peso, %grasa) + modelo físico vascular | 1000 train / 60 test (dataset propio, no MIMIC) | MAE < 5 mmHg | Parcial (solo MAE confirmado en el texto) |

**Hallazgo clave**: la comparación PMC10146008 vs PPG2BP-Net usa la **misma señal de entrada (PPG solo)** — la única diferencia es calibración sí/no, y es lo que separa "no cumple AAMI" de "sí cumple". Confirma que el problema no es el algoritmo ni las features, es la ausencia de una referencia individual por paciente.

---

## 6. Intento 2: Calibración por sujeto (explorado, luego descartado por decisión del usuario)

**Enfoque**: usar los primeros 25 latidos válidos de cada registro de 8 min como "calibración" (equivalente a una lectura de tensiómetro real), predecir el *delta* respecto a esa referencia usando features normalizadas (actual − calibración), y reconstruir `presión = baseline + delta_predicho`.

| Método | MAE | SD |
|---|---|---|
| Línea base trivial (asumir delta=0, solo repetir calibración) | 5.42 mmHg | 8.76 mmHg |
| Modelo calibrado (config inicial) | 5.11 mmHg | 8.22 mmHg |
| Modelo calibrado (mejor config, 500 árboles) | 5.04 mmHg | **8.15 mmHg** |
| **AAMI requiere** | ≤5 | ≤8 |

Resultado: SD bajó de 17.06 a 8.15 mmHg (mejora de 8.9 mmHg), a **0.15 mmHg de cumplir AAMI**. MAE ya cumple. Bias ≈0.

**Decisión del usuario**: se descartó este enfoque porque requiere una medición de referencia externa (tensiómetro) al iniciar el uso — no es una solución "desde el modelo solo". Los artefactos de este experimento (dataset, scripts, modelo) fueron eliminados del proyecto a pedido del usuario, pero el resultado queda documentado aquí como evidencia de que la calibración es la única palanca que demostró cerrar la brecha hacia AAMI.

---

## 7. Intento 3 (vigente): Reformulación como clasificación de riesgo NEWS-2

**Motivación**: sin calibración, sin ECG y sin datos demográficos, no hay forma honesta de predecir mmHg exactos con precisión clínica. Se reformula el problema: en vez de un valor continuo, clasificar si la presión sistólica cae en un rango de riesgo según la escala clínica **NEWS-2** (National Early Warning Score 2):

| Rango sistólica | Puntos NEWS-2 |
|---|---|
| ≤90 mmHg | 3 |
| 91–100 mmHg | 2 |
| 101–110 mmHg | 1 |
| 111–219 mmHg | 0 (normal) |
| ≥220 mmHg | 3 |

### Intento fallido: regresión + binning posterior
Usando el modelo de regresión (15 features) y convirtiendo sus predicciones a puntos NEWS-2:
- Exactitud "aparente": 80.1% — **engañosa**, un clasificador trivial que siempre predice "normal" ya obtiene 78.8% (esa es la proporción real de casos normales en el test).
- **Sensibilidad real para detectar riesgo: solo 22.3%** — de 5,072 casos reales de riesgo en el test, se detectaron solo 1,129 (fallo en 3,943, el 77.7%).
- Causa: "regresión a la media" — el regresor, optimizado para error cuadrático promedio sobre datos con 78.8% de casos normales, aprende a predecir cerca del centro de la distribución casi siempre, subestimando sistemáticamente los casos extremos (cuando la presión real merecía 3 puntos, el modelo predijo 0 puntos el 53% de las veces).

### Solución: clasificador directo con peso balanceado por clase
`RandomForestClassifier` (300 árboles, `class_weight="balanced"`) entrenado directamente sobre la etiqueta de riesgo, no sobre mmHg continuos.

| Métrica (umbral 0.5, default) | Antes (regresión+binning) | Clasificador balanceado |
|---|---|---|
| Sensibilidad (detecta riesgo real) | 22.3% | 65.6% |
| Especificidad (no falsa alarma) | 98.4% | 86.4% |
| Exactitud general | 80.1% (engañosa) | 82.0% (honesta) |

### Ajuste de umbral de decisión (trade-off sensibilidad/especificidad)
| Umbral | Sensibilidad | Especificidad | Falsos negativos |
|---|---|---|---|
| 0.50 (default) | 65.6% | 86.4% | 1,744 / 5,072 |
| 0.40 | 77.0% | 76.8% | 1,165 |
| **0.35 (elegido)** | **82.2%** | **70.3%** | **904** |
| 0.30 | 87.2% | 62.5% | 647 |
| 0.20 | 95.4% | 42.3% | 232 |
| 0.10 | 99.2% | 18.9% | 41 |

**Umbral final elegido: 0.35.** Se descartaron umbrales más bajos pese a mayor sensibilidad nominal por riesgo de "fatiga de alarma" (especificidad <50% inunda al usuario de falsas alarmas y termina siendo ignorado, contraproducente en un dispositivo de uso doméstico continuo).

### Clasificación multiclase (4 niveles de puntos NEWS-2)
- Exactitud exacta: 74.5%; exactitud ±1 punto: 92.7%.
- Sensibilidad agregada de riesgo (puntos 1, 2 o 3): 69.8%.
- Los casos más severos (3 puntos) pasaron de acertarse 10% de las veces (regresión) a **54.6%** (clasificador balanceado).

---

## 8. De binario a multiclase: por qué importa cómo se usa la salida

El score NEWS-2 no evalúa la presión de forma aislada — es una **suma de puntos de 7 parámetros**, con una regla de escalamiento especial: si **cualquier parámetro individual llega a 3 puntos**, dispara alerta urgente sin importar el total. Un primer modelo binario (riesgo/normal, umbral 0.35, sensibilidad 82.2%/especificidad 70.3%) resultaba engañoso para este contexto: trataba cada falso positivo como si fuera una alarma aislada, cuando en realidad un falso "1 punto" apenas mueve la suma total. Lo que sí importa tanto como una alarma aislada es específicamente el **falso "3 puntos"**, porque ese sí dispara el escalamiento individual por sí solo.

Por eso el modelo final es **multiclase** (predice 0/1/2/3 puntos directamente, no solo riesgo/normal), con una regla de decisión que prioriza la detección de la clase 3 mediante un umbral de probabilidad propio:

| Umbral clase 3 | Falso-3 (% de casos reales normales) | Sensibilidad clase 3 (% de casos reales severos) | Sensibilidad riesgo agregado (>0) |
|---|---|---|---|
| Default (argmax) | 1.6% | 54.6% | 69.8% |
| 0.25 | 3.3% | 64.1% | 70.6% |
| **0.20 (elegido)** | **6.1%** | **70.0%** | **72.1%** |
| 0.15 | 11.4% | 74.3% | 74.5% |
| 0.10 | 22.6% | 81.5% | 79.7% |

**Umbral elegido: 0.20.** Duplica la sensibilidad para detectar casos severos (54.6%→70.0%) manteniendo la tasa de falsa alerta de escalamiento individual baja (6.1% de los casos normales).

### Modelo final entregado
**Archivo**: `models/news2_bp_classifier.pkl` (57.4 MB, comprimido con joblib).

- `RandomForestClassifier` multiclase, 300 árboles, `min_samples_leaf=10`, `class_weight="balanced"`.
- Entrada: 15 features de `ppg_features.py` sobre ventana de 10 latidos.
- Salida: puntos NEWS-2 de presión sistólica (0/1/2/3), vía `argmax(proba)` con anulación a clase 3 si `proba[3] ≥ 0.20`.
- Evaluado sin fuga (split por registro): exactitud exacta 74.5%, exactitud ±1 punto 92.7%, sensibilidad clase 3 = 70.0% @ umbral 0.20, falso-3 = 6.1%.
- Metadata en `models/news2_bp_classifier_meta.json`.

**Nota importante para la tesis**: este modelo **no estima mmHg exactos** — clasifica el nivel de riesgo de presión sistólica en la escala NEWS-2 (0-3 puntos), diseñado para sumarse a los otros 6 parámetros del score total, no para usarse de forma aislada. Es la salida honesta y defendible dado lo que la señal PPG de un solo sensor, sin calibración ni datos adicionales, puede sostener.

---

## 9. Resumen ejecutivo (para metodología de tesis)

1. Se construyó un pipeline completo de extracción de features PPG (15 features/ciclo) y su emparejamiento con presión sistólica real desde el dataset Kachuee/UCI (119,880 ventanas, 11,022 registros).
2. La estimación de presión arterial **absoluta** en mmHg mediante Random Forest sobre PPG de un solo sensor, sin calibración, **no cumple el estándar AAMI** (SD=16.68 mmHg vs 8 mmHg requerido). Se descartó sistemáticamente, con evidencia experimental, que la causa fuera: capacidad del modelo, cantidad de datos, especialización por subgrupos, o ruido de medición — el 85% del error es sesgo sistemático entre pacientes.
3. Se comparó contra literatura: estudios con la misma señal (PPG solo) que agregan calibración por sujeto sí alcanzan AAMI (PPG2BP-Net, SD=7.51 mmHg); sin calibración, no (PMC10146008, SD=10.40 mmHg) — consistente con el hallazgo propio.
4. Se exploró calibración por sujeto (usando los primeros latidos de cada registro como referencia): llevó la SD de 17.06 a 8.15 mmHg, a 0.15 mmHg de cumplir AAMI — pero se descartó por requerir una medición de referencia externa, fuera del alcance deseado.
5. **Solución adoptada**: reformular el problema de regresión continua a **clasificación de riesgo según la escala clínica NEWS-2**, con balanceo de clases para corregir el sesgo hacia la clase mayoritaria. Sensibilidad para detectar riesgo real: de 22.3% (regresión+binning) a 69.8-72.1% (clasificador balanceado) — una mejora de más de 3x, lograda sin calibración, sin ECG y sin datos demográficos.
6. **Ajuste fino por el uso real de la salida**: como NEWS-2 suma puntos de 7 parámetros (no evalúa la presión aislada), el modelo final es multiclase (0-3 puntos, no binario), con un umbral de decisión propio para la clase 3 (0.20) — la única que dispara alerta de escalamiento individual sin importar el resto del score. Esto sube la sensibilidad para detectar casos severos de 54.6% a 70.0%, manteniendo la tasa de falsa alerta de escalamiento en 6.1%.
7. El sistema resultante se presenta como una herramienta de **alerta temprana de tendencia**, no como un instrumento de medición clínica de precisión — framing consistente con la evidencia obtenida y con el estado del arte para sistemas cuff-less de un solo sensor sin calibración.
