import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import GroupShuffleSplit
from sklearn.metrics import accuracy_score, confusion_matrix, classification_report

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

print("=" * 60)
print("1. CLASIFICACION BINARIA: riesgo (>0 pts) vs normal (0 pts)")
print("=" * 60)
y_risk_train, y_risk_test = y_risk[train_idx], y_risk[test_idx]
print(f"Train: {np.bincount(y_risk_train)} (normal, riesgo)")
print(f"Test:  {np.bincount(y_risk_test)} (normal, riesgo)\n")

clf_bin = RandomForestClassifier(
    n_estimators=300, max_depth=None, min_samples_leaf=10,
    class_weight="balanced", n_jobs=-1, random_state=RANDOM_STATE,
)
clf_bin.fit(X_train, y_risk_train)
pred_risk = clf_bin.predict(X_test)

acc = accuracy_score(y_risk_test, pred_risk)
cm = confusion_matrix(y_risk_test, pred_risk)
tn, fp, fn, tp = cm.ravel()
sensibilidad = tp / (tp + fn)
especificidad = tn / (tn + fp)

print(f"Exactitud: {acc*100:.1f}%")
print(f"Matriz de confusion:\n{cm}")
print(f"Sensibilidad (detecta riesgo real): {sensibilidad*100:.1f}%  (antes: 22.3%)")
print(f"Especificidad (no da falsa alarma): {especificidad*100:.1f}%  (antes: 98.4%)")
print(f"Falsos negativos: {fn} de {tp+fn}")

print("\n" + "=" * 60)
print("2. CLASIFICACION MULTICLASE: 0/1/2/3 puntos NEWS-2")
print("=" * 60)
y_points_train, y_points_test = y_points[train_idx], y_points[test_idx]

clf_multi = RandomForestClassifier(
    n_estimators=300, max_depth=None, min_samples_leaf=10,
    class_weight="balanced", n_jobs=-1, random_state=RANDOM_STATE,
)
clf_multi.fit(X_train, y_points_train)
pred_points = clf_multi.predict(X_test)

acc_multi = accuracy_score(y_points_test, pred_points)
tol1 = np.mean(np.abs(y_points_test - pred_points) <= 1)
cm_multi = confusion_matrix(y_points_test, pred_points, labels=[0, 1, 2, 3])

print(f"Exactitud exacta: {acc_multi*100:.1f}%  (antes: 80.1%, pero enganosa por desbalance)")
print(f"Exactitud +-1 punto: {tol1*100:.1f}%")
print("Matriz de confusion (filas=real, columnas=predicho):")
print("        pred=0  pred=1  pred=2  pred=3")
for i, row in zip([0, 1, 2, 3], cm_multi):
    print(f"real={i}   {row[0]:6d}  {row[1]:6d}  {row[2]:6d}  {row[3]:6d}")

risk_real = y_points_test > 0
risk_pred = pred_points > 0
sens_multi = np.sum(risk_real & risk_pred) / np.sum(risk_real)
print(f"\nSensibilidad de riesgo (agregando 1,2,3 puntos): {sens_multi*100:.1f}%  (antes: 22.3%)")
