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


def classify_with_priority_on_3(proba, thr_3):
    n = len(proba)
    pred = np.argmax(proba, axis=1)
    force_3 = proba[:, 3] >= thr_3
    pred[force_3] = 3
    return pred


df = pd.read_csv(DATA_PATH)
X = df[FEATURE_NAMES].values
y_sbp = df["systolic_bp"].values
y_points = news2_points(y_sbp)
groups = df["record_id"].values

gss = GroupShuffleSplit(n_splits=1, test_size=TEST_SIZE, random_state=RANDOM_STATE)
train_idx, test_idx = next(gss.split(X, y_sbp, groups))
X_train, X_test = X[train_idx], X[test_idx]
y_train, y_test = y_points[train_idx], y_points[test_idx]

clf = RandomForestClassifier(
    n_estimators=300, max_depth=None, min_samples_leaf=10,
    class_weight="balanced", n_jobs=-1, random_state=RANDOM_STATE,
)
clf.fit(X_train, y_train)
proba = clf.predict_proba(X_test)

n_real_0 = np.sum(y_test == 0)
n_real_3 = np.sum(y_test == 3)
n_real_risk = np.sum(y_test > 0)

print(f"Test: {len(y_test)} filas | real=0: {n_real_0} | real=3: {n_real_3} | real>0 (riesgo): {n_real_risk}\n")

print(f"{'thr_3':>6s} {'falso-3 (%real=0)':>18s} {'sens-3 (%real=3)':>17s} {'sens-riesgo (>0)':>17s}")
for thr_3 in [0.50, 0.35, 0.25, 0.20, 0.15, 0.10, 0.08, 0.05]:
    pred = classify_with_priority_on_3(proba, thr_3)

    falso_3 = np.mean(pred[y_test == 0] == 3) * 100
    sens_3 = np.mean(pred[y_test == 3] == 3) * 100
    sens_riesgo = np.mean(pred[y_test > 0] > 0) * 100

    print(f"{thr_3:6.2f} {falso_3:17.1f}% {sens_3:16.1f}% {sens_riesgo:16.1f}%")

print("\n=== Matriz de confusion con argmax puro (thr_3 implicito ~0.25-0.33 segun clase) ===")
pred_default = np.argmax(proba, axis=1)
cm = confusion_matrix(y_test, pred_default, labels=[0, 1, 2, 3])
print("        pred=0  pred=1  pred=2  pred=3")
for i, row in zip([0, 1, 2, 3], cm):
    print(f"real={i}   {row[0]:6d}  {row[1]:6d}  {row[2]:6d}  {row[3]:6d}")
