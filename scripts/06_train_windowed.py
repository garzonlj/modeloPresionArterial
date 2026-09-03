import os
import numpy as np
import pandas as pd
import joblib
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import GroupShuffleSplit
from sklearn.metrics import mean_absolute_error

from ppg_features import FEATURE_NAMES

DATA_PATH = "data/features_dataset_windowed.csv"
MODEL_PATH = "models/rf_systolic_bp_windowed.pkl"
RANDOM_STATE = 42
TEST_SIZE = 0.2

df = pd.read_csv(DATA_PATH)
print(f"Dataset: {len(df)} filas, {df['record_id'].nunique()} registros unicos")

X = df[FEATURE_NAMES].values
y = df["systolic_bp"].values
groups = df["record_id"].values

gss = GroupShuffleSplit(n_splits=1, test_size=TEST_SIZE, random_state=RANDOM_STATE)
train_idx, test_idx = next(gss.split(X, y, groups))
X_train, X_test = X[train_idx], X[test_idx]
y_train, y_test = y[train_idx], y[test_idx]

overlap = set(groups[train_idx]) & set(groups[test_idx])
assert len(overlap) == 0, f"Fuga de datos: {len(overlap)} record_id en ambos splits"
print(f"Train: {len(X_train)} filas ({pd.Series(groups[train_idx]).nunique()} registros)")
print(f"Test:  {len(X_test)} filas ({pd.Series(groups[test_idx]).nunique()} registros)")
print("OK: sin overlap de record_id entre train y test")

model = RandomForestRegressor(
    n_estimators=100,
    max_depth=None,
    min_samples_leaf=30,
    n_jobs=-1,
    random_state=RANDOM_STATE,
)
model.fit(X_train, y_train)

y_pred = model.predict(X_test)
error = y_pred - y_test

mae = mean_absolute_error(y_test, y_pred)
mean_err = np.mean(error)
std_err = np.std(error)

print("\n=== Resultados en test (ventanas de 10 latidos, sin fuga) ===")
print(f"MAE: {mae:.2f} mmHg")
print(f"Error medio (bias): {mean_err:.2f} mmHg")
print(f"Desviacion estandar del error: {std_err:.2f} mmHg")

print("\n=== Comparacion con estandar AAMI ===")
cumple_media = abs(mean_err) <= 5
cumple_std = std_err <= 8
print(f"  |error medio| = {abs(mean_err):.2f} mmHg -> {'CUMPLE' if cumple_media else 'NO CUMPLE'}")
print(f"  desviacion estandar = {std_err:.2f} mmHg -> {'CUMPLE' if cumple_std else 'NO CUMPLE'}")
print(f"  Resultado: {'CUMPLE AAMI' if (cumple_media and cumple_std) else 'NO CUMPLE AAMI'}")

print("\n=== Importancia de features ===")
importancias = sorted(zip(FEATURE_NAMES, model.feature_importances_), key=lambda x: -x[1])
for name, imp in importancias:
    print(f"  {name:12s} {imp:.4f}")

joblib.dump(model, MODEL_PATH, compress=3)
size_mb = os.path.getsize(MODEL_PATH) / (1024 * 1024)
print(f"\nModelo guardado en: {MODEL_PATH} ({size_mb:.1f} MB)")
