import os
import numpy as np
import joblib

from ppg_features import FEATURE_NAMES, process_record
from respiratory_rate import estimate_respiratory_rate

MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "models", "news2_bp_classifier.pkl")
THRESHOLD_CLASS_3 = 0.20
FS_MAX30100 = 100.0
MIN_CYCLES = 10
RR_MIN_SECONDS = 20


def load_bp_model(path=MODEL_PATH):
    return joblib.load(path)


def bp_points(clf, feat_vector):
    proba = clf.predict_proba(np.asarray([feat_vector]))[0]
    pred = int(np.argmax(proba))
    if proba[3] >= THRESHOLD_CLASS_3:
        pred = 3
    return pred


def median_feature_vector(cycles, n=MIN_CYCLES):
    chosen = cycles[-n:]
    return [float(np.median([c[0][name] for c in chosen])) for name in FEATURE_NAMES]


def estimate_bp_points(clf, ir_samples, fs=FS_MAX30100):
    if clf is None or len(ir_samples) < RR_MIN_SECONDS * fs:
        return None
    _, cycles = process_record(np.asarray(ir_samples, dtype=float), fs=fs, rescale=True)
    if len(cycles) < MIN_CYCLES:
        return None
    return bp_points(clf, median_feature_vector(cycles))


def estimate_rr(ir_samples, fs=FS_MAX30100):
    if len(ir_samples) < RR_MIN_SECONDS * fs:
        return None
    return estimate_respiratory_rate(np.asarray(ir_samples, dtype=float), fs)


def points_spo2(spo2):
    if spo2 is None or spo2 <= 0:
        return None
    if spo2 <= 91:
        return 3
    if spo2 <= 93:
        return 2
    if spo2 <= 95:
        return 1
    return 0


def points_hr(hr):
    if hr is None or hr <= 0:
        return None
    if hr <= 40:
        return 3
    if hr <= 50:
        return 1
    if hr <= 90:
        return 0
    if hr <= 110:
        return 1
    if hr <= 130:
        return 2
    return 3


def points_temp(temp_c):
    if temp_c is None or np.isnan(temp_c):
        return None
    if temp_c <= 35.0:
        return 3
    if temp_c <= 36.0:
        return 1
    if temp_c <= 38.0:
        return 0
    if temp_c <= 39.0:
        return 1
    return 2


def points_rr(rpm):
    if rpm is None:
        return None
    r = round(rpm)
    if r <= 8:
        return 3
    if r <= 11:
        return 1
    if r <= 20:
        return 0
    if r <= 24:
        return 2
    return 3


def points_oxygen(on_oxygen):
    return 2 if on_oxygen else 0


def points_consciousness(alert):
    return 0 if alert else 3


def aggregate_news2(points):
    available = {k: v for k, v in points.items() if v is not None}
    missing = [k for k, v in points.items() if v is None]
    total = sum(available.values())
    any_three = any(v == 3 for v in available.values())

    if any_three:
        level, code = "EVIDENTE (un parametro en 3 puntos): respuesta urgente", 4
    elif total >= 7:
        level, code = "ALTO: respuesta inmediata", 3
    elif total >= 5:
        level, code = "MEDIO: respuesta urgente", 2
    elif total >= 1:
        level, code = "BAJO: vigilar", 1
    else:
        level, code = "NORMAL", 0
    return {"total": total, "missing": missing, "level": level, "level_code": code}
