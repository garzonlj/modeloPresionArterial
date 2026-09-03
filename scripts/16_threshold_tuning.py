import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import GroupShuffleSplit
from sklearn.metrics import confusion_matrix

from ppg_features import FEATURE_NAMES

DATA_PATH = "data/features_dataset_windowed.csv"
RANDOM_STATE = 42
TEST_SIZE = 0.2


def news2_points(sbp):
    sbp = np.asarray(sbp)
    points = np.zeros_like(sbp, dtype=int)
    points[sbp <= 90] = 3
    points[(sbp >= 91) & (sbp <= 100)] = 2
    points[(sbp >= 101) & (sbp <= 110)] = 1
    points[(sbp >= 111) & (sbp <= 219)] = 0
    points[sbp >= 220] = 3
    return points


df = pd.read_csv(DATA_PATH)
X = df[FEATURE_NAMES].values
y_sbp = df["systolic_bp"].values
y_points = news2_points(y_sbp)
y_risk = (y_points > 0).astype(int)
groups = df["record_id"].values

gss = GroupShuffleSplit(n_splits=1, test_size=TEST_SIZE, random_state=RANDOM_STATE)
train_idx, test_idx = next(gss.split(X, y_sbp, groups))
X_train, X_test = X[train_idx], X[test_idx]
y_risk_train, y_risk_test = y_risk[train_idx], y_risk[test_idx]

clf = RandomForestClassifier(
    n_estimators=300, max_depth=None, min_samples_leaf=10,
    class_weight="balanced", n_jobs=-1, random_state=RANDOM_STATE,
)
clf.fit(X_train, y_risk_train)
proba = clf.predict_proba(X_test)[:, 1]

print(f"{'Umbral':>8s} {'Sensibilidad':>13s} {'Especificidad':>14s} {'Exactitud':>10s} {'Falsos-':>8s}")
print(f"{'':>8s} {'(detecta)':>13s} {'(no molesta)':>14s} {'':>10s} {'Neg.':>8s}")
for thr in [0.5, 0.45, 0.40, 0.35, 0.30, 0.25, 0.20, 0.15, 0.10]:
    pred = (proba >= thr).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_risk_test, pred).ravel()
    sens = tp / (tp + fn)
    esp = tn / (tn + fp)
    acc = (tp + tn) / len(y_risk_test)
    print(f"{thr:8.2f} {sens*100:12.1f}% {esp*100:13.1f}% {acc*100:9.1f}% {fn:8d}")

print("\nRecomendacion: elegir el umbral mas bajo que aun mantenga una especificidad")
print("razonable (para no saturar de falsas alarmas), priorizando sensibilidad.")
