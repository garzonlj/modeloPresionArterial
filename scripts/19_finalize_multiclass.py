import os
import json
import numpy as np
import pandas as pd
import joblib
from sklearn.ensemble import RandomForestClassifier

from ppg_features import FEATURE_NAMES

DATA_PATH = "data/features_dataset_windowed.csv"
MODEL_PATH = "models/news2_bp_classifier.pkl"
META_PATH = "models/news2_bp_classifier_meta.json"
RANDOM_STATE = 42
THRESHOLD_CLASS_3 = 0.20


def news2_points(sbp):
    sbp = np.asarray(sbp)
    points = np.zeros_like(sbp, dtype=int)
    points[sbp <= 90] = 3
    points[(sbp >= 91) & (sbp <= 100)] = 2
    points[(sbp >= 101) & (sbp <= 110)] = 1
    points[(sbp >= 111) & (sbp <= 219)] = 0
    points[sbp >= 220] = 3
    return points


def predict_news2_points(clf, X):
    proba = clf.predict_proba(X)
    pred = np.argmax(proba, axis=1)
    force_3 = proba[:, 3] >= THRESHOLD_CLASS_3
    pred[force_3] = 3
    return pred


df = pd.read_csv(DATA_PATH)
X = df[FEATURE_NAMES].values
y_points = news2_points(df["systolic_bp"].values)

print(f"Entrenando con dataset completo: {len(X)} filas, "
      f"{df['record_id'].nunique()} registros")
print(f"Distribucion de puntos: {np.bincount(y_points)}")

clf = RandomForestClassifier(
    n_estimators=300, max_depth=None, min_samples_leaf=10,
    class_weight="balanced", n_jobs=-1, random_state=RANDOM_STATE,
)
clf.fit(X, y_points)

joblib.dump(clf, MODEL_PATH, compress=3)
size_mb = os.path.getsize(MODEL_PATH) / (1024 * 1024)

meta = {
    "feature_names": FEATURE_NAMES,
    "tipo": "RandomForestClassifier multiclase (0/1/2/3 puntos NEWS-2 de presion sistolica)",
    "decision_rule": (
        "pred = argmax(proba); si proba[clase 3] >= 0.20, forzar prediccion = 3 "
        "(prioriza deteccion de casos severos, que disparan la regla de escalamiento "
        "individual de NEWS-2 independientemente del puntaje total)"
    ),
    "threshold_class_3": THRESHOLD_CLASS_3,
    "output": "puntos NEWS-2 de presion sistolica (0, 1, 2 o 3), para sumar al score NEWS-2 total",
    "evaluado_en_test_sin_fuga": {
        "sensibilidad_clase_3_default_argmax": "54.6%",
        "sensibilidad_clase_3_con_threshold_0.20": "70.0%",
        "falso_positivo_clase_3_con_threshold_0.20": "6.1% (de casos realmente normales)",
        "sensibilidad_riesgo_agregado_puntos>0": "72.1%",
        "exactitud_exacta_4_clases": "74.5%",
        "exactitud_tolerancia_1_punto": "92.7%",
    },
    "nota": (
        "Este modelo NO estima mmHg exactos. Clasifica el nivel de riesgo de presion "
        "sistolica en la escala NEWS-2 (0-3 puntos), pensado para sumarse a los otros "
        "6 parametros del score NEWS-2 total, no para usarse de forma aislada."
    ),
}
with open(META_PATH, "w", encoding="utf-8") as f:
    json.dump(meta, f, indent=2, ensure_ascii=False)

print(f"\nModelo guardado en: {MODEL_PATH} ({size_mb:.1f} MB)")
print(f"Metadata guardada en: {META_PATH}")
print(f"Umbral de clase 3: {THRESHOLD_CLASS_3}")
