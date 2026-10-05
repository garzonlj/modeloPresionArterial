import numpy as np
from scipy.signal import butter, filtfilt, find_peaks


def estimate_respiratory_rate(ir_raw, fs, min_rpm=6, max_rpm=30):
    ir_raw = np.asarray(ir_raw, dtype=float)
    duration_s = len(ir_raw) / fs
    if duration_s < 20:
        return None

    low = min_rpm / 60.0
    high = max_rpm / 60.0
    nyq = fs / 2.0
    b, a = butter(3, [low / nyq, high / nyq], btype="band")
    resp_signal = filtfilt(b, a, ir_raw)

    if np.std(resp_signal) < 1e-6:
        return None

    min_dist = int(fs * 60.0 / max_rpm)
    peaks, _ = find_peaks(resp_signal, distance=min_dist, prominence=np.std(resp_signal) * 0.3)

    rpm = len(peaks) / (duration_s / 60.0)
    if not (min_rpm <= rpm <= max_rpm):
        return None
    return float(rpm)
