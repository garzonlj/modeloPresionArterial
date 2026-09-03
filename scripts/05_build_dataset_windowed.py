import time
import h5py
import numpy as np
import pandas as pd

from ppg_features import process_record, FEATURE_NAMES, FS_TARGET

PARTS = ["Part_1", "Part_2", "Part_3", "Part_4"]
WINDOW_SIZE = 10
MAX_WINDOWS_PER_RECORD = 15
SYSTOLIC_RANGE = (70, 200)
DIASTOLIC_RANGE = (40, 130)
PULSE_PRESSURE_RANGE = (20, 100)

OUT_PATH = "data/features_dataset_windowed.csv"


def evenly_subsample(items, k):
    n = len(items)
    if n <= k:
        return items
    idxs = np.linspace(0, n - 1, k).round().astype(int)
    idxs = sorted(set(idxs.tolist()))
    return [items[i] for i in idxs]


def build_windows(valid_cycles, window=WINDOW_SIZE, max_windows=MAX_WINDOWS_PER_RECORD):
    n = len(valid_cycles)
    windows = []
    for start in range(0, n - window + 1, window):
        chunk = valid_cycles[start:start + window]
        agg = {name: float(np.median([c[0][name] for c in chunk])) for name in FEATURE_NAMES}
        agg_sys = float(np.median([c[1] for c in chunk]))
        agg_dia = float(np.median([c[2] for c in chunk]))
        windows.append((agg, agg_sys, agg_dia))
    return evenly_subsample(windows, max_windows)


def main():
    rows = []
    t0 = time.time()
    total_records = 0

    for part in PARTS:
        path = f"data/raw/{part}.mat"
        with h5py.File(path, "r") as f:
            ds = f[part]
            n_records = ds.shape[0]
            for idx in range(n_records):
                mat = f[ds[idx][0]][()]
                ppg_raw = mat[:, 0]
                abp = mat[:, 1]

                _, cycles = process_record(ppg_raw, fs=FS_TARGET)

                valid = []
                for feats, onset, peak, next_onset in cycles:
                    seg = abp[onset:next_onset + 1]
                    systolic = float(np.max(seg))
                    diastolic = float(np.min(seg))
                    pp = systolic - diastolic
                    if not (SYSTOLIC_RANGE[0] <= systolic <= SYSTOLIC_RANGE[1]):
                        continue
                    if not (DIASTOLIC_RANGE[0] <= diastolic <= DIASTOLIC_RANGE[1]):
                        continue
                    if not (PULSE_PRESSURE_RANGE[0] <= pp <= PULSE_PRESSURE_RANGE[1]):
                        continue
                    valid.append((feats, systolic, diastolic))

                windows = build_windows(valid)

                record_id = f"{part}_{idx}"
                for agg, agg_sys, agg_dia in windows:
                    row = dict(agg)
                    row["systolic_bp"] = agg_sys
                    row["diastolic_bp"] = agg_dia
                    row["record_id"] = record_id
                    row["part"] = part
                    rows.append(row)

                total_records += 1
                if total_records % 1000 == 0:
                    dt = time.time() - t0
                    print(f"[{total_records}/12000] registros | {len(rows)} filas | {dt/60:.1f} min", flush=True)

    df = pd.DataFrame(rows, columns=FEATURE_NAMES + ["systolic_bp", "diastolic_bp", "record_id", "part"])
    df.to_csv(OUT_PATH, index=False)

    dt = time.time() - t0
    print("\n=== Resumen ===")
    print(f"Registros procesados: {total_records}")
    print(f"Ventanas (filas) finales: {len(df)}")
    print(f"Registros unicos con al menos 1 ventana: {df['record_id'].nunique()}")
    print(f"Tiempo total: {dt/60:.1f} min")
    print(f"Guardado en: {OUT_PATH}")


if __name__ == "__main__":
    main()
