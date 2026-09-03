import numpy as np
from scipy.signal import butter, filtfilt, find_peaks

FS_TARGET = 125.0

REFERENCE_AMPLITUDE = 1.76

FEATURE_NAMES = [
    "rise_time",
    "width_25",
    "width_50",
    "width_75",
    "notch_time",
    "amplitude",
    "max_d1",
    "max_d2",
    "min_d2",
    "d2_ratio",
    "heart_rate",
    "area_ratio",
    "notch_depth_ratio",
    "aug_index",
    "spectral_ratio",
]


def bandpass_filter(sig, fs=FS_TARGET, low=0.5, high=8.0, order=4):
    nyq = fs / 2.0
    b, a = butter(order, [low / nyq, high / nyq], btype="band")
    return filtfilt(b, a, sig)


def normalize_to_reference_scale(ppg_filt, reference_amplitude=REFERENCE_AMPLITUDE):
    observed = np.percentile(ppg_filt, 95) - np.percentile(ppg_filt, 5)
    if observed < 1e-9:
        return ppg_filt
    factor = reference_amplitude / observed
    return ppg_filt * factor


def find_pulse_cycles(ppg_filt, fs=FS_TARGET, min_hr=40, max_hr=180):
    min_dist = int(fs * 60.0 / max_hr)
    peaks, _ = find_peaks(ppg_filt, distance=min_dist, prominence=np.std(ppg_filt) * 0.3)

    cycles = []
    for i in range(len(peaks) - 1):
        p0, p1 = peaks[i], peaks[i + 1]
        seg_start = peaks[i - 1] if i > 0 else max(0, p0 - int(fs))
        onset = seg_start + int(np.argmin(ppg_filt[seg_start:p0 + 1]))
        next_onset = p0 + int(np.argmin(ppg_filt[p0:p1 + 1]))

        dur = (next_onset - onset) / fs
        if dur <= 0:
            continue
        hr = 60.0 / ((next_onset - onset) / fs)
        if not (min_hr <= hr <= max_hr):
            continue
        cycles.append((onset, p0, next_onset))
    return cycles


def _crossing_time(x, level, idx_start, idx_end, fs):
    seg = x[idx_start:idx_end + 1]
    above = seg >= level
    idxs = np.where(np.diff(above.astype(int)) != 0)[0]
    if len(idxs) == 0:
        return None
    i = idxs[0]
    x0, x1 = seg[i], seg[i + 1]
    if x1 == x0:
        frac = 0.0
    else:
        frac = (level - x0) / (x1 - x0)
    return idx_start + i + frac


def extract_cycle_features(ppg_filt, onset, peak, next_onset, fs=FS_TARGET):
    foot_level = ppg_filt[onset]
    peak_level = ppg_filt[peak]
    amplitude = peak_level - foot_level
    if amplitude <= 0:
        return None

    rise_time = (peak - onset) / fs

    widths = {}
    for p in (0.25, 0.50, 0.75):
        level = foot_level + p * amplitude
        t_rise = _crossing_time(ppg_filt, level, onset, peak, fs)
        t_fall = _crossing_time(ppg_filt, level, peak, next_onset, fs)
        if t_rise is None or t_fall is None:
            return None
        widths[p] = (t_fall - t_rise) / fs

    if not (widths[0.25] >= widths[0.50] >= widths[0.75] > 0):
        return None

    post = ppg_filt[peak:next_onset + 1]
    if len(post) < 4:
        return None
    notch_rel, _ = find_peaks(-post, prominence=amplitude * 0.02)
    if len(notch_rel) > 0:
        notch_idx = peak + notch_rel[0]
        notch_time = (notch_idx - peak) / fs
    else:
        notch_time = (next_onset - peak) / (2 * fs)

    dt = 1.0 / fs
    cycle = ppg_filt[onset:next_onset + 1]
    d1 = np.gradient(cycle, dt)
    d2 = np.gradient(d1, dt)

    max_d1 = float(np.max(d1))
    max_d2 = float(np.max(d2))
    min_d2 = float(np.min(d2))
    d2_ratio = min_d2 / max_d2 if max_d2 != 0 else 0.0

    heart_rate = 60.0 / ((next_onset - onset) / fs)

    sys_area = float(np.trapezoid(ppg_filt[onset:peak + 1] - foot_level, dx=dt))
    dia_area = float(np.trapezoid(ppg_filt[peak:next_onset + 1] - foot_level, dx=dt))
    area_ratio = sys_area / dia_area if dia_area > 0 else 0.0

    notch_idx = min(peak + int(round(notch_time * fs)), next_onset)
    notch_level = ppg_filt[notch_idx]
    notch_depth_ratio = (peak_level - notch_level) / amplitude

    post_notch = ppg_filt[notch_idx:next_onset + 1]
    aug_index = 0.0
    if len(post_notch) >= 3:
        sec_rel, _ = find_peaks(post_notch, prominence=amplitude * 0.02)
        if len(sec_rel) > 0:
            sec_level = post_notch[sec_rel[0]]
            aug_index = (sec_level - foot_level) / amplitude
        else:
            aug_index = (notch_level - foot_level) / amplitude

    spectrum = np.abs(np.fft.rfft(cycle - np.mean(cycle)))
    if len(spectrum) > 2 and spectrum[1] > 1e-9:
        spectral_ratio = float(spectrum[2] / spectrum[1])
    else:
        spectral_ratio = 0.0

    return {
        "rise_time": rise_time,
        "width_25": widths[0.25],
        "width_50": widths[0.50],
        "width_75": widths[0.75],
        "notch_time": notch_time,
        "amplitude": float(amplitude),
        "max_d1": max_d1,
        "max_d2": max_d2,
        "min_d2": min_d2,
        "d2_ratio": float(d2_ratio),
        "heart_rate": float(heart_rate),
        "area_ratio": float(area_ratio),
        "notch_depth_ratio": float(notch_depth_ratio),
        "aug_index": float(aug_index),
        "spectral_ratio": spectral_ratio,
    }


def _reject_amplitude_duration_outliers(results, fs=FS_TARGET, mad_k=4.0):
    if len(results) < 8:
        return results

    amps = np.array([r[0]["amplitude"] for r in results])
    durs = np.array([(r[3] - r[1]) / fs for r in results])

    def robust_mask(x):
        med = np.median(x)
        mad = np.median(np.abs(x - med)) + 1e-9
        z = 0.6745 * (x - med) / mad
        return np.abs(z) <= mad_k

    mask = robust_mask(amps) & robust_mask(durs)
    return [r for r, keep in zip(results, mask) if keep]


def process_record(ppg_raw, fs=FS_TARGET, rescale=False):
    ppg_filt = bandpass_filter(ppg_raw, fs=fs)
    if rescale:
        ppg_filt = normalize_to_reference_scale(ppg_filt)
    cycles = find_pulse_cycles(ppg_filt, fs=fs)
    results = []
    for onset, peak, next_onset in cycles:
        feats = extract_cycle_features(ppg_filt, onset, peak, next_onset, fs=fs)
        if feats is not None:
            results.append((feats, onset, peak, next_onset))
    results = _reject_amplitude_duration_outliers(results, fs=fs)
    return ppg_filt, results
