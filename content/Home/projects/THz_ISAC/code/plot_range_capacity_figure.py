"""Plot THz ISAC high-resolution ranging figures from saved range NPZ files.

The input files are the .npz files created by the DSO tab's "Save Range"
button in isac_gui.py / isac_unified_gui.py.  Each saved range file can already
contain both the stored reference profile (`ref_rng`, `ref_prof_db`,
`range_zero__...`) and the current moved-target profile (`rng`, `prof_db`).
The script extracts only the selected radar channel, usually C2, and plots both
the matched-filter range profile and the normalized CFR delay profile.

Example
-------
python plot_range_capacity_figure.py ^
  --b2 data/range/Range_fIF11_fsym2_P-10_fRF280_DFT-s-OFDM_16QAM_IphNA.npz ^
  --b20 data/range/Range_fIF11_fsym20_P-10_fRF280_DFT-s-OFDM_16QAM_Iph6.9.npz ^
  --out data/range/thz_range_capacity.png ^
  --zoom-x-mm 900 1100 --zoom-y-db -40 10
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from read_range_data import (
    collect_range_results,
    infer_processing_gain_db,
    metric_map,
    to_float,
    unpack,
)


C = 3e8


@dataclass
class RangeCase:
    label: str
    path: Path
    baud_gbaud: float
    waveform: str
    modulation: str
    range_peak_m: float
    range_diff_mm: float
    pslr_db: float
    radar_snr_db: float
    radar_snr_source: str
    processing_gain_db: float
    resolution_formula_mm: float
    resolution_saved_mm: float
    mf_range_m: np.ndarray
    mf_profile_db: np.ndarray
    ref_mf_range_m: np.ndarray
    ref_mf_profile_db: np.ndarray
    si_range_m: np.ndarray
    si_profile_db: np.ndarray
    ref_si_range_m: np.ndarray
    ref_si_profile_db: np.ndarray
    raw_cfr_range_m: np.ndarray
    raw_cfr_profile_db: np.ndarray
    ref_raw_cfr_range_m: np.ndarray
    ref_raw_cfr_profile_db: np.ndarray
    ref_norm_cfr_range_m: np.ndarray
    ref_norm_cfr_profile_db: np.ndarray
    cfr_freqs_hz: np.ndarray
    cfr_h: np.ndarray
    cfr_weight: np.ndarray
    range_scale_m_per_s: float
    si_peak_m: float
    si_coherence: float


def normalize_db(profile_db: np.ndarray) -> np.ndarray:
    y = np.asarray(profile_db, dtype=float).reshape(-1)
    finite = np.isfinite(y)
    if not np.any(finite):
        return y
    return y - float(np.nanmax(y[finite]))


def target_roi_m() -> tuple[float, float]:
    return (1.08, 1.12)


def roi_psnr_db(xr_m: np.ndarray, yr_db: np.ndarray, guard_m: float = 0.025) -> float:
    x = np.asarray(xr_m, dtype=float).reshape(-1)
    y = normalize_db(np.asarray(yr_db, dtype=float).reshape(-1))
    n = min(len(x), len(y))
    if n < 8:
        return float("nan")
    x = x[:n]
    y = y[:n]
    lo_m, hi_m = target_roi_m()
    roi = np.isfinite(x) & np.isfinite(y) & (x >= lo_m) & (x <= hi_m)
    if np.count_nonzero(roi) < 8:
        return float("nan")
    roi_idx = np.flatnonzero(roi)
    pk = int(roi_idx[int(np.nanargmax(y[roi_idx]))])
    floor_mask = roi & (np.abs(x - x[pk]) > guard_m)
    if np.count_nonzero(floor_mask) < 4:
        floor_mask = roi
    return float(y[pk] - np.nanmedian(y[floor_mask]))


def roi_pslr_db(
    xr_m: np.ndarray, yr_db: np.ndarray, guard_m: float = 0.006
) -> tuple[float, float, float]:
    """Peak-to-sidelobe ratio inside the ROI: main peak vs. the highest
    *local maximum* elsewhere in the ROI (outside a small guard around the
    peak) -- not just the peak vs. the median floor (that's roi_psnr_db).
    Returns (pslr_db, peak_range_m, sidelobe_range_m)."""
    x = np.asarray(xr_m, dtype=float).reshape(-1)
    y = normalize_db(np.asarray(yr_db, dtype=float).reshape(-1))
    n = min(len(x), len(y))
    if n < 8:
        return float("nan"), float("nan"), float("nan")
    x = x[:n]
    y = y[:n]
    lo_m, hi_m = target_roi_m()
    roi = np.isfinite(x) & np.isfinite(y) & (x >= lo_m) & (x <= hi_m)
    if np.count_nonzero(roi) < 8:
        return float("nan"), float("nan"), float("nan")
    roi_idx = np.flatnonzero(roi)
    pk = int(roi_idx[int(np.nanargmax(y[roi_idx]))])
    peak_val, peak_x = float(y[pk]), float(x[pk])

    side_idx = roi_idx[np.abs(x[roi_idx] - peak_x) > guard_m]
    if len(side_idx) < 3:
        return float("nan"), peak_x, float("nan")
    local_max = [
        i for i in side_idx
        if 0 < i < n - 1 and y[i] >= y[i - 1] and y[i] >= y[i + 1]
    ]
    if not local_max:
        local_max = list(side_idx)
    side_i = local_max[int(np.nanargmax(y[local_max]))]
    return peak_val - float(y[side_i]), peak_x, float(x[side_i])


def default_compare_capture_path() -> Path:
    return default_range_dir() / "Data_fIF11_fsym15_P-7_fRF280_DFT-s-OFDM_16QAM_Iph7.npz"


def default_data_range_compare_path() -> Path:
    return default_range_dir() / "Data_range_fIF11_fsym15_P-8_fRF280_DFT-s-OFDM_32QAM_Iph7.npz"


def get_npz_scalar(loaded: np.lib.npyio.NpzFile, key: str, default: Any = "") -> Any:
    if key not in loaded.files:
        return default
    try:
        return unpack(loaded[key])
    except Exception:
        return default


def metric_float(metrics: dict[str, dict[str, Any]], *keys: str) -> tuple[float, str]:
    for key in keys:
        if key not in metrics:
            continue
        value = to_float(metrics[key].get("value", float("nan")))
        if math.isfinite(value):
            return value, key
    return float("nan"), ""


def infer_baud_gbaud(path: Path, loaded: np.lib.npyio.NpzFile) -> float:
    for key, scale in (("sr_ghz", 1.0), ("tx__symbol_rate_actual", 1e-9), ("tx__symbol_rate", 1e-9)):
        value = to_float(get_npz_scalar(loaded, key, float("nan")))
        if math.isfinite(value) and value > 0:
            return value * scale
    match = re.search(r"fsym([0-9]+(?:\.[0-9]+)?)", path.stem, flags=re.IGNORECASE)
    if match:
        try:
            return float(match.group(1))
        except Exception:
            pass
    return float("nan")


def resolution_formula_mm(baud_gbaud: float) -> float:
    if not math.isfinite(baud_gbaud) or baud_gbaud <= 0:
        return float("nan")
    return C / (2.0 * baud_gbaud * 1e9) * 1e3


def select_channel_result(results: list[dict[str, Any]], channel: str) -> dict[str, Any]:
    channel_u = channel.strip().upper()
    for item in results:
        ch = str(item.get("ch", item.get("channel", ""))).strip().upper()
        if ch == channel_u:
            return item
    if not results:
        raise ValueError(f"No range result is stored for channel {channel_u}.")
    return results[0]


def si_normalized_cfr_delay_profile(
    freqs_hz: np.ndarray,
    h: np.ndarray,
    weight: np.ndarray | None,
    range_axis_m: np.ndarray,
    range_scale_m_per_s: float,
) -> tuple[np.ndarray, np.ndarray, float, float]:
    f = np.asarray(freqs_hz, dtype=float).reshape(-1)
    hc = np.asarray(h, dtype=np.complex128).reshape(-1)
    r = np.asarray(range_axis_m, dtype=float).reshape(-1)
    n = min(len(f), len(hc))
    if n < 16 or len(r) < 4 or not math.isfinite(range_scale_m_per_s) or range_scale_m_per_s <= 0:
        return np.zeros(0), np.zeros(0), float("nan"), float("nan")
    f = f[:n]
    hc = hc[:n]
    if weight is None:
        w = np.ones(n, dtype=float)
    else:
        w = np.asarray(weight, dtype=float).reshape(-1)[:n]
        if len(w) < n:
            w = np.pad(w, (0, n - len(w)), constant_values=0.0)
    valid = (
        np.isfinite(f)
        & np.isfinite(hc.real)
        & np.isfinite(hc.imag)
        & np.isfinite(w)
        & (w > 0.0)
        & (np.abs(hc) > 1e-15)
    )
    if np.count_nonzero(valid) < 16:
        return np.zeros(0), np.zeros(0), float("nan"), float("nan")
    f = f[valid]
    hc = hc[valid]
    w = w[valid]
    w = w / (np.nanmax(w) + 1e-15)
    good = w >= 0.03
    if np.count_nonzero(good) >= 16:
        f = f[good]
        hc = hc[good]
        w = w[good]
    si_ref = np.sum(w * hc) / (np.sum(w) + 1e-15)
    if (not np.isfinite(si_ref.real)) or abs(si_ref) <= 1e-15:
        si_ref = np.median(hc)
    if (not np.isfinite(si_ref.real)) or abs(si_ref) <= 1e-15:
        return np.zeros(0), np.zeros(0), float("nan"), float("nan")

    residual = hc / (si_ref + 1e-15) - 1.0
    residual = residual - np.sum(w * residual) / (np.sum(w) + 1e-15)
    tau = r / float(range_scale_m_per_s)
    amp = np.zeros(len(tau), dtype=np.complex128)
    for i0 in range(0, len(tau), 512):
        tt = tau[i0:i0 + 512]
        phase = np.exp(1j * 2.0 * np.pi * f[:, np.newaxis] * tt[np.newaxis, :])
        amp[i0:i0 + 512] = np.sum((w * residual)[:, np.newaxis] * phase, axis=0)
    mag = np.abs(amp) / (np.sum(w) + 1e-15)
    profile_db = 20.0 * np.log10(mag / (np.nanmax(mag) + 1e-30) + 1e-30)
    peak_idx = int(np.nanargmax(mag)) if len(mag) else 0
    phase_unit = residual / (np.abs(residual) + 1e-15)
    coherence = float(np.abs(np.sum(w * phase_unit)) / (np.sum(w) + 1e-15))
    return r, profile_db, float(r[peak_idx]) if len(r) else float("nan"), coherence


def raw_cfr_delay_profile(
    freqs_hz: np.ndarray,
    h: np.ndarray,
    weight: np.ndarray | None,
    range_axis_m: np.ndarray,
    range_scale_m_per_s: float,
) -> tuple[np.ndarray, np.ndarray]:
    f = np.asarray(freqs_hz, dtype=float).reshape(-1)
    hc = np.asarray(h, dtype=np.complex128).reshape(-1)
    r = np.asarray(range_axis_m, dtype=float).reshape(-1)
    n = min(len(f), len(hc))
    if n < 16 or len(r) < 4 or not math.isfinite(range_scale_m_per_s) or range_scale_m_per_s <= 0:
        return np.zeros(0), np.zeros(0)
    f = f[:n]
    hc = hc[:n]
    if weight is None:
        w = np.ones(n, dtype=float)
    else:
        w = np.asarray(weight, dtype=float).reshape(-1)[:n]
        if len(w) < n:
            w = np.pad(w, (0, n - len(w)), constant_values=0.0)
    valid = (
        np.isfinite(f)
        & np.isfinite(hc.real)
        & np.isfinite(hc.imag)
        & np.isfinite(w)
        & (w > 0.0)
        & (np.abs(hc) > 1e-15)
    )
    if np.count_nonzero(valid) < 16:
        return np.zeros(0), np.zeros(0)
    f = f[valid]
    hc = hc[valid]
    w = w[valid]
    w = w / (np.nanmax(w) + 1e-15)
    good = w >= 0.03
    if np.count_nonzero(good) >= 16:
        f = f[good]
        hc = hc[good]
        w = w[good]

    tau = r / float(range_scale_m_per_s)
    amp = np.zeros(len(tau), dtype=np.complex128)
    for i0 in range(0, len(tau), 512):
        tt = tau[i0:i0 + 512]
        phase = np.exp(1j * 2.0 * np.pi * f[:, np.newaxis] * tt[np.newaxis, :])
        amp[i0:i0 + 512] = np.sum((w * hc)[:, np.newaxis] * phase, axis=0)
    mag = np.abs(amp) / (np.sum(w) + 1e-15)
    profile_db = 20.0 * np.log10(mag / (np.nanmax(mag) + 1e-30) + 1e-30)
    return r, profile_db


def compute_si_from_result(result: dict[str, Any], range_axis_m: np.ndarray) -> tuple[np.ndarray, np.ndarray, float, float]:
    freqs = np.asarray(result.get("cfr_freqs_hz", []), dtype=float).reshape(-1)
    h = np.asarray(result.get("cfr_h", []), dtype=np.complex128).reshape(-1)
    w = np.asarray(result.get("cfr_weight", []), dtype=float).reshape(-1)
    scale = to_float(result.get("range_scale_m_per_s", C / 2.0))
    if len(freqs) >= 16 and len(h) == len(freqs):
        return si_normalized_cfr_delay_profile(freqs, h, w if len(w) else None, range_axis_m, scale)

    saved_rng = np.asarray(result.get("si_cfr_rng", []), dtype=float).reshape(-1)
    saved_prof = np.asarray(result.get("si_cfr_prof_db", []), dtype=float).reshape(-1)
    if len(saved_rng) >= 4 and len(saved_rng) == len(saved_prof):
        return saved_rng, normalize_db(saved_prof), to_float(result.get("si_cfr_peak_m", float("nan"))), to_float(result.get("si_cfr_coherence", float("nan")))
    return np.zeros(0), np.zeros(0), float("nan"), float("nan")


def compute_raw_cfr_from_result(result: dict[str, Any], range_axis_m: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    freqs = np.asarray(result.get("cfr_freqs_hz", []), dtype=float).reshape(-1)
    h = np.asarray(result.get("cfr_h", []), dtype=np.complex128).reshape(-1)
    w = np.asarray(result.get("cfr_weight", []), dtype=float).reshape(-1)
    scale = to_float(result.get("range_scale_m_per_s", C / 2.0))
    return raw_cfr_delay_profile(freqs, h, w if len(w) else None, range_axis_m, scale)


def compute_si_from_zero(loaded: np.lib.npyio.NpzFile, channel: str, range_axis_m: np.ndarray) -> tuple[np.ndarray, np.ndarray, float, float]:
    ch = channel.strip().upper()
    prefix = f"range_zero__{ch}__"
    freq_key = prefix + "cfr_freqs"
    h_key = prefix + "cfr_h"
    w_key = prefix + "cfr_weight"
    if freq_key not in loaded.files or h_key not in loaded.files:
        return np.zeros(0), np.zeros(0), float("nan"), float("nan")
    freqs = np.asarray(loaded[freq_key], dtype=float).reshape(-1)
    h = np.asarray(loaded[h_key], dtype=np.complex128).reshape(-1)
    w = np.asarray(loaded[w_key], dtype=float).reshape(-1) if w_key in loaded.files else None
    scale = to_float(get_npz_scalar(loaded, prefix + "range_scale_m_per_s", C / 2.0))
    return si_normalized_cfr_delay_profile(freqs, h, w, range_axis_m, scale)


def compute_raw_cfr_from_zero(loaded: np.lib.npyio.NpzFile, channel: str, range_axis_m: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    ch = channel.strip().upper()
    prefix = f"range_zero__{ch}__"
    freq_key = prefix + "cfr_freqs"
    h_key = prefix + "cfr_h"
    w_key = prefix + "cfr_weight"
    if freq_key not in loaded.files or h_key not in loaded.files:
        return np.zeros(0), np.zeros(0)
    freqs = np.asarray(loaded[freq_key], dtype=float).reshape(-1)
    h = np.asarray(loaded[h_key], dtype=np.complex128).reshape(-1)
    w = np.asarray(loaded[w_key], dtype=float).reshape(-1) if w_key in loaded.files else None
    scale = to_float(get_npz_scalar(loaded, prefix + "range_scale_m_per_s", C / 2.0))
    return raw_cfr_delay_profile(freqs, h, w, range_axis_m, scale)


def compute_reference_normalized_cfr_from_result(
    loaded: np.lib.npyio.NpzFile,
    result: dict[str, Any],
    channel: str,
    range_axis_m: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    ch = channel.strip().upper()
    prefix = f"range_zero__{ch}__"
    ref_freq_key = prefix + "cfr_freqs"
    ref_h_key = prefix + "cfr_h"
    if ref_freq_key not in loaded.files or ref_h_key not in loaded.files:
        return np.zeros(0), np.zeros(0)

    f_cur = np.asarray(result.get("cfr_freqs_hz", []), dtype=float).reshape(-1)
    h_cur = np.asarray(result.get("cfr_h", []), dtype=np.complex128).reshape(-1)
    w_cur = np.asarray(result.get("cfr_weight", []), dtype=float).reshape(-1)
    f_ref = np.asarray(loaded[ref_freq_key], dtype=float).reshape(-1)
    h_ref = np.asarray(loaded[ref_h_key], dtype=np.complex128).reshape(-1)
    n = min(len(f_cur), len(h_cur))
    if n < 16 or len(f_ref) < 16 or len(h_ref) < 16:
        return np.zeros(0), np.zeros(0)
    f_cur = f_cur[:n]
    h_cur = h_cur[:n]
    valid_ref = np.isfinite(f_ref) & np.isfinite(h_ref.real) & np.isfinite(h_ref.imag)
    if np.count_nonzero(valid_ref) < 16:
        return np.zeros(0), np.zeros(0)
    order = np.argsort(f_ref[valid_ref])
    f_ref_s = f_ref[valid_ref][order]
    h_ref_s = h_ref[valid_ref][order]
    h_ref_i = np.interp(f_cur, f_ref_s, h_ref_s.real) + 1j * np.interp(f_cur, f_ref_s, h_ref_s.imag)
    h_ratio = h_cur / (h_ref_i + 1e-15) - 1.0
    scale = to_float(result.get("range_scale_m_per_s", get_npz_scalar(loaded, prefix + "range_scale_m_per_s", C / 2.0)))
    return raw_cfr_delay_profile(f_cur, h_ratio, w_cur if len(w_cur) else None, range_axis_m, scale)


def profile_snr_db(result: dict[str, Any]) -> float:
    rng = np.asarray(result.get("rng", []), dtype=float).reshape(-1)
    prof = np.asarray(result.get("prof_db", []), dtype=float).reshape(-1)
    n = min(len(rng), len(prof))
    if n < 16:
        return float("nan")
    rng = rng[:n]
    prof = normalize_db(prof[:n])
    peak_m = to_float(result.get("display_range_m", result.get("est_range", float("nan"))))
    if math.isfinite(peak_m):
        peak_idx = int(np.nanargmin(np.abs(rng - peak_m)))
    else:
        peak_idx = int(np.nanargmax(prof))
    dr = float(np.nanmedian(np.abs(np.diff(np.sort(rng[np.isfinite(rng)]))))) if np.count_nonzero(np.isfinite(rng)) > 2 else 0.001
    res_m = to_float(result.get("range_resolution_m", float("nan")))
    guard_m = max(0.02, 3.0 * res_m if math.isfinite(res_m) and res_m > 0 else 8.0 * dr)
    zero_exclude_m = to_float(result.get("zero_exclude_m", float("nan")))
    side = np.isfinite(rng) & np.isfinite(prof) & (np.abs(rng - rng[peak_idx]) > guard_m)
    if math.isfinite(zero_exclude_m) and zero_exclude_m > 0:
        side &= rng > zero_exclude_m
    if np.count_nonzero(side) < 8:
        return float("nan")
    return float(prof[peak_idx] - np.nanmedian(prof[side]))


def load_case(path: Path, label: str, channel: str, si_range_axis_m: np.ndarray) -> RangeCase:
    path = path.expanduser().resolve()
    with np.load(path, allow_pickle=True) as loaded:
        metrics = metric_map(loaded)
        results = collect_range_results(loaded)
        result = select_channel_result(results, channel)

        baud = infer_baud_gbaud(path, loaded)
        waveform = str(get_npz_scalar(loaded, "tx__waveform_type", get_npz_scalar(loaded, "modulation", "")))
        modulation = str(get_npz_scalar(loaded, "tx__modulation", get_npz_scalar(loaded, "modulation", "")))
        rng = np.asarray(result.get("rng", []), dtype=float).reshape(-1)
        prof = normalize_db(np.asarray(result.get("prof_db", []), dtype=float).reshape(-1))
        cfr_freqs_hz = np.asarray(result.get("cfr_freqs_hz", []), dtype=float).reshape(-1)
        cfr_h = np.asarray(result.get("cfr_h", []), dtype=np.complex128).reshape(-1)
        cfr_weight = np.asarray(result.get("cfr_weight", []), dtype=float).reshape(-1)
        range_scale = to_float(result.get("range_scale_m_per_s", C / 2.0))
        ref_rng = np.asarray(result.get("ref_rng", []), dtype=float).reshape(-1)
        ref_prof = normalize_db(np.asarray(result.get("ref_prof_db", []), dtype=float).reshape(-1))
        si_rng, si_prof, si_peak, si_coh = compute_si_from_result(result, si_range_axis_m)
        si_prof = normalize_db(si_prof)
        ref_si_rng, ref_si_prof, _, _ = compute_si_from_zero(loaded, channel, si_range_axis_m)
        ref_si_prof = normalize_db(ref_si_prof)
        raw_cfr_rng, raw_cfr_prof = compute_raw_cfr_from_result(result, si_range_axis_m)
        raw_cfr_prof = normalize_db(raw_cfr_prof)
        ref_raw_cfr_rng, ref_raw_cfr_prof = compute_raw_cfr_from_zero(loaded, channel, si_range_axis_m)
        ref_raw_cfr_prof = normalize_db(ref_raw_cfr_prof)
        ref_norm_cfr_rng, ref_norm_cfr_prof = compute_reference_normalized_cfr_from_result(
            loaded, result, channel, si_range_axis_m
        )
        ref_norm_cfr_prof = normalize_db(ref_norm_cfr_prof)

        radar_snr, snr_key = metric_float(
            metrics,
            f"snr_rad_db_{channel.lower()}",
            "snr_rad_db",
            f"snr_com_db_{channel.lower()}",
            "radar_snr_db",
            "snr_com_db",
        )
        snr_source = snr_key
        if not math.isfinite(radar_snr):
            radar_snr = profile_snr_db(result)
            snr_source = "range-profile median"
        proc_gain = infer_processing_gain_db(result, loaded)
        saved_res_m = to_float(result.get("range_resolution_m", float("nan")))
        return RangeCase(
            label=label,
            path=path,
            baud_gbaud=baud,
            waveform=waveform,
            modulation=modulation,
            range_peak_m=to_float(result.get("display_range_m", result.get("est_range", float("nan")))),
            range_diff_mm=to_float(result.get("range_diff_mm", float("nan"))),
            pslr_db=to_float(result.get("pslr_db", float("nan"))),
            radar_snr_db=radar_snr,
            radar_snr_source=snr_source,
            processing_gain_db=proc_gain,
            resolution_formula_mm=resolution_formula_mm(baud),
            resolution_saved_mm=saved_res_m * 1e3 if math.isfinite(saved_res_m) else float("nan"),
            mf_range_m=rng,
            mf_profile_db=prof,
            ref_mf_range_m=ref_rng,
            ref_mf_profile_db=ref_prof,
            si_range_m=si_rng,
            si_profile_db=si_prof,
            ref_si_range_m=ref_si_rng,
            ref_si_profile_db=ref_si_prof,
            raw_cfr_range_m=raw_cfr_rng,
            raw_cfr_profile_db=raw_cfr_prof,
            ref_raw_cfr_range_m=ref_raw_cfr_rng,
            ref_raw_cfr_profile_db=ref_raw_cfr_prof,
            ref_norm_cfr_range_m=ref_norm_cfr_rng,
            ref_norm_cfr_profile_db=ref_norm_cfr_prof,
            cfr_freqs_hz=cfr_freqs_hz,
            cfr_h=cfr_h,
            cfr_weight=cfr_weight,
            range_scale_m_per_s=range_scale,
            si_peak_m=si_peak,
            si_coherence=si_coh,
        )


def plot_profile(ax, x_m: np.ndarray, y_db: np.ndarray, label: str, xlim_m: tuple[float, float], **kwargs: Any) -> None:
    x = np.asarray(x_m, dtype=float).reshape(-1)
    y = np.asarray(y_db, dtype=float).reshape(-1)
    n = min(len(x), len(y))
    if n < 2:
        return
    x = x[:n]
    y = y[:n]
    mask = np.isfinite(x) & np.isfinite(y) & (x >= xlim_m[0]) & (x <= xlim_m[1])
    if np.count_nonzero(mask) < 2:
        return
    ax.plot(x[mask], y[mask], label=label, **kwargs)


def plot_zoom_profile(ax, x_m: np.ndarray, y_db: np.ndarray, label: str, **kwargs: Any) -> None:
    x = np.asarray(x_m, dtype=float).reshape(-1) * 1e3
    y = np.asarray(y_db, dtype=float).reshape(-1)
    n = min(len(x), len(y))
    if n < 2:
        return
    ax.plot(x[:n], y[:n], label=label, **kwargs)


def write_summary_csv(cases: list[RangeCase], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "label",
        "file",
        "baud_gbaud",
        "waveform",
        "modulation",
        "range_peak_mm",
        "range_diff_mm",
        "resolution_formula_mm",
        "resolution_saved_mm",
        "c2_radar_snr_db",
        "c2_radar_snr_source",
        "processing_gain_db",
        "pslr_db",
        "si_cfr_peak_mm",
        "si_cfr_coherence",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for case in cases:
            writer.writerow({
                "label": case.label,
                "file": str(case.path),
                "baud_gbaud": case.baud_gbaud,
                "waveform": case.waveform,
                "modulation": case.modulation,
                "range_peak_mm": case.range_peak_m * 1e3,
                "range_diff_mm": case.range_diff_mm,
                "resolution_formula_mm": case.resolution_formula_mm,
                "resolution_saved_mm": case.resolution_saved_mm,
                "c2_radar_snr_db": case.radar_snr_db,
                "c2_radar_snr_source": case.radar_snr_source,
                "processing_gain_db": case.processing_gain_db,
                "pslr_db": case.pslr_db,
                "si_cfr_peak_mm": case.si_peak_m * 1e3,
                "si_cfr_coherence": case.si_coherence,
            })


def make_figure(cases: list[RangeCase], args: argparse.Namespace) -> None:
    import matplotlib

    if not args.show:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colors = ["#64748b", "#dc2626", "#2563eb", "#0f766e", "#b45309", "#7c3aed"]
    fig, axes = plt.subplots(2, 2, figsize=(12.2, 7.8), dpi=args.dpi)
    ax_mf, ax_si, ax_zoom_mf, ax_zoom_si = axes.reshape(-1)

    profile_xlim = (float(args.profile_x_m[0]), float(args.profile_x_m[1]))
    zoom_xlim = (float(args.zoom_x_mm[0]), float(args.zoom_x_mm[1]))
    zoom_ylim = (float(args.zoom_y_db[0]), float(args.zoom_y_db[1]))
    profile_ylim = (float(args.profile_y_db[0]), float(args.profile_y_db[1]))

    for idx, case in enumerate(cases):
        color = colors[idx % len(colors)]
        if "gbaud" in case.label.lower() or not math.isfinite(case.baud_gbaud):
            full_label = case.label
        else:
            full_label = f"{case.label} ({case.baud_gbaud:.3g} GBaud)"
        if len(case.mf_range_m):
            plot_profile(ax_mf, case.mf_range_m, case.mf_profile_db, full_label, profile_xlim, color=color, lw=1.25)
        if len(case.si_range_m):
            plot_profile(ax_si, case.si_range_m, case.si_profile_db, full_label, profile_xlim, color=color, lw=1.25)

    move_case = next((c for c in cases if "move" in c.label.lower() or "1011" in c.label), None)
    if move_case is None and cases:
        finite_baud = [c for c in cases if math.isfinite(c.baud_gbaud)]
        move_case = max(finite_baud, key=lambda c: c.baud_gbaud) if finite_baud else cases[-1]
    ref_case = next((c for c in cases if "ref" in c.label.lower() or "1018" in c.label), None)
    if ref_case is None and move_case is not None and len(move_case.ref_mf_range_m):
        plot_zoom_profile(ax_zoom_mf, move_case.ref_mf_range_m, move_case.ref_mf_profile_db, f"reference {args.ref_mm:g} mm", color="#64748b", lw=1.3, ls="--")
    elif ref_case is not None:
        plot_zoom_profile(ax_zoom_mf, ref_case.mf_range_m, ref_case.mf_profile_db, f"reference {args.ref_mm:g} mm", color="#64748b", lw=1.3, ls="--")

    if move_case is not None:
        plot_zoom_profile(ax_zoom_mf, move_case.mf_range_m, move_case.mf_profile_db, f"moved {args.move_mm:g} mm", color="#dc2626", lw=1.35)

    if ref_case is None and move_case is not None and len(move_case.ref_si_range_m):
        plot_zoom_profile(ax_zoom_si, move_case.ref_si_range_m, move_case.ref_si_profile_db, f"reference {args.ref_mm:g} mm", color="#64748b", lw=1.3, ls="--")
    elif ref_case is not None:
        plot_zoom_profile(ax_zoom_si, ref_case.si_range_m, ref_case.si_profile_db, f"reference {args.ref_mm:g} mm", color="#64748b", lw=1.3, ls="--")

    if move_case is not None:
        plot_zoom_profile(ax_zoom_si, move_case.si_range_m, move_case.si_profile_db, f"moved {args.move_mm:g} mm", color="#dc2626", lw=1.35)

    for ax in (ax_zoom_mf, ax_zoom_si):
        ax.axvline(float(args.ref_mm), color="#64748b", lw=0.9, ls=":")
        ax.axvline(float(args.move_mm), color="#dc2626", lw=0.9, ls=":")
        ax.annotate(
            f"{abs(float(args.ref_mm) - float(args.move_mm)):.1f} mm",
            xy=((float(args.ref_mm) + float(args.move_mm)) * 0.5, zoom_ylim[1] - 3.0),
            ha="center",
            va="top",
            fontsize=20,
        )

    ax_mf.set_title("Matched-filter range profile")
    ax_si.set_title("Normalized CFR delay profile")
    ax_zoom_mf.set_title("20 GBaud single-shot displacement, matched filter")
    ax_zoom_si.set_title("20 GBaud single-shot displacement, normalized CFR")

    for ax in (ax_mf, ax_si):
        ax.set_xlim(*profile_xlim)
        ax.set_ylim(*profile_ylim)
        ax.set_xlabel("Range (m)")
        ax.set_ylabel("Normalized magnitude (dB)")
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=20)

    for ax in (ax_zoom_mf, ax_zoom_si):
        ax.set_xlim(*zoom_xlim)
        ax.set_ylim(*zoom_ylim)
        ax.set_xlabel("Range (mm)")
        ax.set_ylabel("Normalized magnitude (dB)")
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=20)

    fig.suptitle("High-Resolution Ranging Capacity of THz ISAC", fontsize=20, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out, bbox_inches="tight")
    if args.show:
        plt.show()
    else:
        plt.close(fig)


def add_case_arg(parser: argparse.ArgumentParser, name: str, help_text: str) -> None:
    parser.add_argument(name, type=Path, default=None, help=help_text)


def build_cases(args: argparse.Namespace) -> list[tuple[str, Path]]:
    specs: list[tuple[str, Path]] = []
    if args.b2:
        specs.append(("2 GBaud", args.b2))
    if args.b20:
        specs.append(("20 GBaud", args.b20))
    if args.ref:
        specs.append((f"reference {args.ref_mm:g} mm", args.ref))
    if args.move:
        specs.append((f"moved {args.move_mm:g} mm", args.move))
    for item in args.case or []:
        if "=" in item:
            label, raw_path = item.split("=", 1)
            specs.append((label.strip(), Path(raw_path.strip())))
        else:
            path = Path(item)
            specs.append((path.stem, path))
    seen: set[tuple[str, str]] = set()
    deduped: list[tuple[str, Path]] = []
    for label, path in specs:
        key = (label, str(path))
        if key in seen:
            continue
        seen.add(key)
        deduped.append((label, path))
    return deduped


def default_range_dir() -> Path:
    return Path(__file__).resolve().parent / "data" / "range"


def parse_pair_text(text: str, fallback: tuple[float, float]) -> tuple[float, float]:
    try:
        parts = [p for p in re.split(r"[\s,;]+", str(text).strip()) if p]
        if len(parts) != 2:
            return fallback
        a = float(parts[0])
        b = float(parts[1])
        if not (math.isfinite(a) and math.isfinite(b)) or a == b:
            return fallback
        return (min(a, b), max(a, b))
    except Exception:
        return fallback


def infer_baud_for_path(path: Path) -> float:
    try:
        with np.load(path, allow_pickle=True) as loaded:
            return infer_baud_gbaud(path, loaded)
    except Exception:
        return float("nan")


def estimate_lfm_cfr(rx_mat: np.ndarray, tx_mat: np.ndarray, fs: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rx = np.asarray(rx_mat, dtype=np.complex128)
    tx = np.asarray(tx_mat, dtype=np.complex128)
    n_rows = min(rx.shape[0] if rx.ndim == 2 else 0, tx.shape[0] if tx.ndim == 2 else 0)
    if n_rows <= 0:
        return np.zeros(0), np.zeros(0, dtype=np.complex128), np.zeros(0)
    n = min(rx.shape[1], tx.shape[1])
    if n < 16 or fs <= 0:
        return np.zeros(0), np.zeros(0, dtype=np.complex128), np.zeros(0)
    rx = rx[:n_rows, :n]
    tx = tx[:n_rows, :n]
    win = np.hanning(n).astype(np.float64)
    rx_f = np.fft.fft(rx * win[np.newaxis, :], axis=1)
    tx_f = np.fft.fft(tx * win[np.newaxis, :], axis=1)
    sxx = np.sum(np.abs(tx_f) ** 2, axis=0)
    h = np.sum(rx_f * np.conj(tx_f), axis=0) / (sxx + 1e-15)
    freqs = np.fft.fftfreq(n, d=1.0 / float(fs))
    power = sxx / (float(np.max(sxx)) + 1e-15)
    mask = power > 1e-3
    if np.count_nonzero(mask) < 16:
        mask = power > 1e-4
    if np.count_nonzero(mask) < 16:
        return np.zeros(0), np.zeros(0, dtype=np.complex128), np.zeros(0)
    idx = np.argsort(freqs[mask])
    return freqs[mask][idx], h[mask][idx], power[mask][idx]


def estimate_normalized_cfr_from_capture(
    path: Path,
    channel: str,
    range_axis_m: np.ndarray,
    range_scale_m_per_s: float,
) -> tuple[np.ndarray, np.ndarray]:
    from fractions import Fraction
    from scipy.signal import fftconvolve, resample_poly

    path = path.expanduser().resolve()
    if not path.exists():
        return np.zeros(0), np.zeros(0)
    ch = channel.strip().upper() or "C2"
    with np.load(path, allow_pickle=True) as loaded:
        rx_key = f"rx__{ch}__sig"
        fs_key = f"rx__{ch}__fs"
        if rx_key not in loaded.files:
            rx_key = "rx_sig"
        if fs_key not in loaded.files:
            fs_key = "rx_fs"
        if rx_key not in loaded.files or fs_key not in loaded.files or "tx__awg_sig" not in loaded.files:
            return np.zeros(0), np.zeros(0)
        rx = np.asarray(loaded[rx_key], dtype=np.float64).reshape(-1)
        rx_fs = float(np.asarray(loaded[fs_key]).reshape(-1)[0])
        tx = np.asarray(loaded["tx__awg_sig"], dtype=np.float64).reshape(-1)
        tx_fs = float(np.asarray(loaded["tx__fs"]).reshape(-1)[0]) if "tx__fs" in loaded.files else rx_fs
        n_chirps = int(np.asarray(loaded["tx__n_chirps"]).reshape(-1)[0]) if "tx__n_chirps" in loaded.files else 1

    if len(rx) < 16 or len(tx) < 16 or rx_fs <= 0 or tx_fs <= 0 or n_chirps <= 0:
        return np.zeros(0), np.zeros(0)
    rx = rx - float(np.mean(rx))
    tx = tx - float(np.mean(tx))
    if abs(rx_fs - tx_fs) / max(rx_fs, tx_fs) > 1e-9:
        ratio = Fraction(tx_fs / rx_fs).limit_denominator(1000)
        rx = resample_poly(rx, ratio.numerator, ratio.denominator)
    if len(rx) < len(tx):
        rx = np.pad(rx, (0, len(tx) - len(rx)))
    corr = np.abs(fftconvolve(rx, tx[::-1], mode="valid"))
    start = int(np.argmax(corr)) if len(corr) else 0
    seg = rx[start:start + len(tx)]
    if len(seg) < len(tx):
        seg = np.pad(seg, (0, len(tx) - len(seg)))
    pts_per = len(tx) // n_chirps
    if pts_per < 16:
        return np.zeros(0), np.zeros(0)
    usable = pts_per * n_chirps
    freqs, h, w = estimate_lfm_cfr(seg[:usable].reshape(n_chirps, pts_per), tx[:usable].reshape(n_chirps, pts_per), tx_fs)
    rng, prof, _, _ = si_normalized_cfr_delay_profile(freqs, h, w, range_axis_m, range_scale_m_per_s)
    return rng, normalize_db(prof)


def estimate_capture_profiles(
    path: Path,
    channel: str,
    range_axis_m: np.ndarray,
    range_scale_m_per_s: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    from fractions import Fraction
    from scipy.signal import fftconvolve, resample_poly

    path = path.expanduser().resolve()
    if not path.exists():
        return np.zeros(0), np.zeros(0), np.zeros(0), np.zeros(0)
    ch = channel.strip().upper() or "C2"
    with np.load(path, allow_pickle=True) as loaded:
        rx_key = f"rx__{ch}__sig"
        fs_key = f"rx__{ch}__fs"
        if rx_key not in loaded.files:
            rx_key = "rx_sig"
        if fs_key not in loaded.files:
            fs_key = "rx_fs"
        if rx_key not in loaded.files or fs_key not in loaded.files or "tx__awg_sig" not in loaded.files:
            return np.zeros(0), np.zeros(0), np.zeros(0), np.zeros(0)
        rx = np.asarray(loaded[rx_key], dtype=np.float64).reshape(-1)
        rx_fs = float(np.asarray(loaded[fs_key]).reshape(-1)[0])
        tx = np.asarray(loaded["tx__awg_sig"], dtype=np.float64).reshape(-1)
        tx_fs = float(np.asarray(loaded["tx__fs"]).reshape(-1)[0]) if "tx__fs" in loaded.files else rx_fs
        n_chirps = int(np.asarray(loaded["tx__n_chirps"]).reshape(-1)[0]) if "tx__n_chirps" in loaded.files else 1
        center_m = float("nan")
        if "range_summary_channels" in loaded.files and "range_summary_display_m" in loaded.files:
            channels = [str(unpack(v)).strip().upper() for v in np.asarray(loaded["range_summary_channels"]).reshape(-1)]
            displays = np.asarray(loaded["range_summary_display_m"], dtype=float).reshape(-1)
            if ch in channels:
                idx = channels.index(ch)
                if idx < len(displays):
                    center_m = float(displays[idx])
        if not math.isfinite(center_m):
            center_m = 1.0

    if len(rx) < 16 or len(tx) < 16 or rx_fs <= 0 or tx_fs <= 0 or n_chirps <= 0:
        return np.zeros(0), np.zeros(0), np.zeros(0), np.zeros(0)
    rx = rx - float(np.mean(rx))
    tx = tx - float(np.mean(tx))
    if abs(rx_fs - tx_fs) / max(rx_fs, tx_fs) > 1e-9:
        ratio = Fraction(tx_fs / rx_fs).limit_denominator(1000)
        rx = resample_poly(rx, ratio.numerator, ratio.denominator)
    if len(rx) < len(tx):
        rx = np.pad(rx, (0, len(tx) - len(rx)))
    corr = np.abs(fftconvolve(rx, tx[::-1], mode="valid"))
    start = int(np.argmax(corr)) if len(corr) else 0
    seg = rx[start:start + len(tx)]
    if len(seg) < len(tx):
        seg = np.pad(seg, (0, len(tx) - len(seg)))
    pts_per = len(tx) // n_chirps
    if pts_per < 16:
        return np.zeros(0), np.zeros(0), np.zeros(0), np.zeros(0)
    usable = pts_per * n_chirps
    rx_mat = seg[:usable].reshape(n_chirps, pts_per)
    tx_mat = tx[:usable].reshape(n_chirps, pts_per)

    corr_acc = np.zeros(2 * pts_per - 1, dtype=np.float64)
    for idx in range(n_chirps):
        corr_acc += np.abs(fftconvolve(rx_mat[idx], tx_mat[idx][::-1], mode="full"))
    corr_acc /= max(n_chirps, 1)
    lags = np.arange(-(pts_per - 1), pts_per, dtype=np.float64)
    mf_rng = center_m + lags / tx_fs * range_scale_m_per_s
    mf_prof = 20.0 * np.log10(corr_acc / (np.nanmax(corr_acc) + 1e-30) + 1e-30)

    freqs, h, w = estimate_lfm_cfr(rx_mat, tx_mat, tx_fs)
    norm_rng, norm_prof, _, _ = si_normalized_cfr_delay_profile(freqs, h, w, range_axis_m, range_scale_m_per_s)
    return mf_rng, normalize_db(mf_prof), norm_rng, normalize_db(norm_prof)


def specs_from_selected_paths(paths: list[Path]) -> list[tuple[str, Path]]:
    enriched: list[tuple[float, Path]] = []
    unknown: list[Path] = []
    for path in paths:
        baud = infer_baud_for_path(path)
        if math.isfinite(baud) and baud > 0:
            enriched.append((baud, path))
        else:
            unknown.append(path)
    enriched.sort(key=lambda item: item[0])
    specs = [(f"{baud:.3g} GBaud", path) for baud, path in enriched]
    specs.extend((path.stem, path) for path in unknown)
    return specs


def prompt_cases_gui(args: argparse.Namespace) -> bool:
    """Open an interactive preview GUI; saving is optional."""
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
        import matplotlib as mpl
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
        from matplotlib.figure import Figure
        from matplotlib.ticker import MultipleLocator
    except Exception as exc:
        print(f"GUI is unavailable: {exc}")
        return False

    mpl.rcParams.update({
        "font.family": "Times New Roman",
        "mathtext.fontset": "stix",
        "axes.titlesize": 9,
        "axes.labelsize": 9,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "legend.fontsize": 8,
    })

    def _path_display(path: Path) -> str:
        baud = infer_baud_for_path(path)
        if math.isfinite(baud):
            return f"{baud:.3g} GBaud  |  {path.name}"
        return path.name

    def _auto_paths() -> list[Path]:
        return [path for _, path in auto_discover_specs(args.channel)]

    root = None
    try:
        root = tk.Tk()
        root.title("THz ISAC Range Capacity Figure")
        root.geometry("1500x760")
        root.minsize(1180, 680)

        selected_paths: list[Path] = []
        current_cases: list[RangeCase] = []
        capture_profile_cache: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = {}
        result = {"handled": False}
        initial_dir = str(default_range_dir())
        filetypes = [("Saved range data", "*.npz"), ("All files", "*.*")]

        channel_var = tk.StringVar(value=str(args.channel))
        out_var = tk.StringVar(value=str(args.out))
        csv_var = tk.StringVar(value=str(args.summary_csv or ""))
        cfr_norm_var = tk.StringVar(value="SI norm")
        reference_source_var = tk.StringVar(value="Embedded reference")
        x_unit_var = tk.StringVar(value="mm")
        x_range_var = tk.StringVar(value=f"{args.zoom_x_mm[0]} {args.zoom_x_mm[1]}")
        y_range_var = tk.StringVar(value=f"{args.zoom_y_db[0]} {args.zoom_y_db[1]}")
        x_grid_var = tk.StringVar(value="50")
        y_grid_var = tk.StringVar(value="10")
        dpi_var = tk.StringVar(value=str(args.dpi))
        si_bins_var = tk.StringVar(value=str(args.si_bins))
        status_var = tk.StringVar(
            value="Select one or more Range_*.npz files. Each file already contains reference + moved/current profiles."
        )

        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        header = ttk.Frame(root, padding=(12, 10, 12, 6))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(
            header,
            text="High-Resolution Ranging Capacity Figure",
            font=("Segoe UI", 14, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="Use saved Save Range NPZ files. For zoom, the highest-baud file's embedded reference/current pair is used.",
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))

        main = ttk.PanedWindow(root, orient=tk.HORIZONTAL)
        main.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 8))

        left = ttk.Frame(main, padding=(0, 0, 8, 0))
        center = ttk.Frame(main, padding=(8, 0, 8, 0))
        right = ttk.Frame(main, padding=(8, 0, 0, 0))
        main.add(left, weight=3)
        main.add(center, weight=8)
        main.add(right, weight=3)

        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)
        ttk.Label(left, text="Saved range NPZ files").grid(row=0, column=0, sticky="w")
        list_frame = ttk.Frame(left)
        list_frame.grid(row=1, column=0, sticky="nsew", pady=(4, 6))
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)
        file_list = tk.Listbox(list_frame, height=12, activestyle="dotbox")
        file_list.grid(row=0, column=0, sticky="nsew")
        yscroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=file_list.yview)
        yscroll.grid(row=0, column=1, sticky="ns")
        file_list.configure(yscrollcommand=yscroll.set)

        def refresh_list() -> None:
            file_list.delete(0, tk.END)
            for path in selected_paths:
                file_list.insert(tk.END, _path_display(path))
            labels = ["Embedded reference"] + [label for label, _ in specs_from_selected_paths(selected_paths)]
            try:
                ref_combo.configure(values=labels)
                if reference_source_var.get() not in labels:
                    reference_source_var.set(labels[0])
            except Exception:
                pass

        def add_files() -> None:
            raw = filedialog.askopenfilenames(
                title="Select saved Range NPZ file(s)",
                initialdir=initial_dir,
                filetypes=filetypes,
                parent=root,
            )
            for name in raw:
                path = Path(name)
                if path not in selected_paths:
                    selected_paths.append(path)
            refresh_list()
            status_var.set(f"Selected {len(selected_paths)} file(s).")

        def remove_selected() -> None:
            for idx in reversed(file_list.curselection()):
                try:
                    selected_paths.pop(int(idx))
                except Exception:
                    pass
            refresh_list()
            status_var.set(f"Selected {len(selected_paths)} file(s).")

        def clear_files() -> None:
            selected_paths.clear()
            refresh_list()
            status_var.set("File list cleared.")

        def auto_find() -> None:
            selected_paths.clear()
            selected_paths.extend(_auto_paths())
            refresh_list()
            status_var.set(f"Auto-selected {len(selected_paths)} Range file(s) from {default_range_dir()}.")

        btns = ttk.Frame(left)
        btns.grid(row=2, column=0, sticky="ew")
        ttk.Button(btns, text="Add NPZ...", command=add_files).pack(side=tk.LEFT)
        ttk.Button(btns, text="Auto Find 2/15/20 GBaud", command=auto_find).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(btns, text="Remove", command=remove_selected).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(btns, text="Clear", command=clear_files).pack(side=tk.LEFT, padx=(6, 0))

        center.rowconfigure(0, weight=1)
        center.columnconfigure(0, weight=1)
        fig = Figure(figsize=(11.8, 4.8), dpi=100)
        ax_compare = fig.add_subplot(131)
        ax_low = fig.add_subplot(132)
        ax_high = fig.add_subplot(133)
        for ax_i in (ax_compare, ax_low, ax_high):
            ax_i.set_xlabel("Range (mm)")
            ax_i.set_ylabel("Norm. mag. (dB)")
            ax_i.grid(True, alpha=0.3)
        canvas = FigureCanvasTkAgg(fig, master=center)
        toolbar = NavigationToolbar2Tk(canvas, center, pack_toolbar=False)
        toolbar.update()
        toolbar.grid(row=1, column=0, sticky="ew")
        canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")

        right.columnconfigure(1, weight=1)

        def add_entry(row: int, label: str, var: tk.StringVar, width: int = 24) -> None:
            ttk.Label(right, text=label).grid(row=row, column=0, sticky="w", pady=3)
            ttk.Entry(right, textvariable=var, width=width).grid(row=row, column=1, sticky="ew", pady=3)

        add_entry(0, "Channel", channel_var)
        ttk.Label(right, text="2nd/3rd norm").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Combobox(
            right,
            textvariable=cfr_norm_var,
            values=("SI norm",),
            state="disabled",
            width=22,
        ).grid(row=1, column=1, sticky="ew", pady=3)
        ttk.Label(right, text="Reference").grid(row=2, column=0, sticky="w", pady=3)
        ref_combo = ttk.Combobox(
            right,
            textvariable=reference_source_var,
            values=("Embedded reference",),
            state="readonly",
            width=22,
        )
        ref_combo.grid(row=2, column=1, sticky="ew", pady=3)
        ttk.Label(right, text="X unit").grid(row=3, column=0, sticky="w", pady=3)
        ttk.Combobox(
            right,
            textvariable=x_unit_var,
            values=("mm", "m"),
            state="readonly",
            width=22,
        ).grid(row=3, column=1, sticky="ew", pady=3)
        add_entry(4, "X range", x_range_var)
        add_entry(5, "Y range [dB]", y_range_var)
        add_entry(6, "X grid step", x_grid_var)
        add_entry(7, "Y grid step [dB]", y_grid_var)
        add_entry(8, "CFR bins", si_bins_var)
        add_entry(9, "Save DPI", dpi_var)

        def browse_out() -> None:
            out = filedialog.asksaveasfilename(
                title="Save range-capacity figure",
                initialdir=initial_dir,
                initialfile=Path(out_var.get() or "thz_range_capacity.png").name,
                defaultextension=".png",
                filetypes=[
                    ("PNG image", "*.png"),
                    ("PDF", "*.pdf"),
                    ("SVG", "*.svg"),
                    ("All files", "*.*"),
                ],
                parent=root,
            )
            if out:
                out_var.set(out)

        def browse_csv() -> None:
            out = filedialog.asksaveasfilename(
                title="Save summary CSV",
                initialdir=initial_dir,
                initialfile="thz_range_capacity.csv",
                defaultextension=".csv",
                filetypes=[("CSV", "*.csv"), ("All files", "*.*")],
                parent=root,
            )
            if out:
                csv_var.set(out)

        ttk.Label(right, text="Output figure").grid(row=10, column=0, sticky="w", pady=(10, 3))
        out_row = ttk.Frame(right)
        out_row.grid(row=10, column=1, sticky="ew", pady=(10, 3))
        out_row.columnconfigure(0, weight=1)
        ttk.Entry(out_row, textvariable=out_var).grid(row=0, column=0, sticky="ew")
        ttk.Button(out_row, text="...", width=3, command=browse_out).grid(row=0, column=1, padx=(4, 0))

        ttk.Label(right, text="Summary CSV").grid(row=11, column=0, sticky="w", pady=3)
        csv_row = ttk.Frame(right)
        csv_row.grid(row=11, column=1, sticky="ew", pady=3)
        csv_row.columnconfigure(0, weight=1)
        ttk.Entry(csv_row, textvariable=csv_var).grid(row=0, column=0, sticky="ew")
        ttk.Button(csv_row, text="...", width=3, command=browse_csv).grid(row=0, column=1, padx=(4, 0))

        hint = ttk.Label(
            right,
            text=(
                "Compare panel overlays MF and normalized CFR profiles.\n"
                "MF: selected Range NPZ, dotted: 1000 mm Data capture, solid blue: Data_range CFR."
            ),
            wraplength=330,
            foreground="#475569",
        )
        hint.grid(row=12, column=0, columnspan=2, sticky="ew", pady=(10, 4))

        actions = ttk.Frame(root, padding=(12, 0, 12, 8))
        actions.grid(row=2, column=0, sticky="ew")
        actions.columnconfigure(0, weight=1)
        ttk.Label(actions, textvariable=status_var).grid(row=0, column=0, sticky="w")

        def load_current_cases() -> list[RangeCase]:
            if not selected_paths:
                raise ValueError("Add at least one saved Range NPZ file.")
            x_rng = parse_pair_text(x_range_var.get(), (900.0, 1100.0))
            user_x_max_m = max(x_rng) * (1e-3 if x_unit_var.get() == "mm" else 1.0)
            x_max_m = max(user_x_max_m, 2.0)
            si_axis = np.linspace(0.0, max(x_max_m, 0.1), max(256, int(float(si_bins_var.get()))))
            return [
                load_case(path, label, channel_var.get().strip() or "C2", si_axis)
                for label, path in specs_from_selected_paths(selected_paths)
            ]

        def display_reference_case(cases: list[RangeCase]) -> RangeCase | None:
            selected = reference_source_var.get()
            if selected == "Embedded reference":
                return None
            for case in cases:
                if case.label == selected:
                    return case
            return None

        def subtract_reference_profile(
            x_m: np.ndarray,
            y_db: np.ndarray,
            ref_x_m: np.ndarray,
            ref_y_db: np.ndarray,
        ) -> tuple[np.ndarray, np.ndarray]:
            x = np.asarray(x_m, dtype=float).reshape(-1)
            y = np.asarray(y_db, dtype=float).reshape(-1)
            n = min(len(x), len(y))
            if n < 2:
                return x, y
            xr = np.asarray(ref_x_m, dtype=float).reshape(-1)
            yr = np.asarray(ref_y_db, dtype=float).reshape(-1)
            nr = min(len(xr), len(yr))
            if nr < 2:
                return x, y
            order = np.argsort(xr[:nr])
            ref_interp = np.interp(x[:n], xr[:nr][order], yr[:nr][order])
            return x[:n], y[:n] - ref_interp

        def cfr_arrays(
            case: RangeCase,
            reference: bool = False,
            global_reference: RangeCase | None = None,
        ) -> tuple[np.ndarray, np.ndarray]:
            mode = cfr_norm_var.get()
            if mode == "Reference norm":
                if global_reference is not None:
                    if reference:
                        x = global_reference.raw_cfr_range_m
                        return x, np.zeros_like(np.asarray(x, dtype=float))
                    return subtract_reference_profile(
                        case.raw_cfr_range_m,
                        case.raw_cfr_profile_db,
                        global_reference.raw_cfr_range_m,
                        global_reference.raw_cfr_profile_db,
                    )
                if reference:
                    x = case.ref_raw_cfr_range_m if len(case.ref_raw_cfr_range_m) else case.raw_cfr_range_m
                    return x, np.zeros_like(np.asarray(x, dtype=float))
                return case.ref_norm_cfr_range_m, case.ref_norm_cfr_profile_db
            if mode == "SI norm":
                return (
                    case.ref_si_range_m if reference else case.si_range_m,
                    case.ref_si_profile_db if reference else case.si_profile_db,
                )
            return (
                case.ref_raw_cfr_range_m if reference else case.raw_cfr_range_m,
                case.ref_raw_cfr_profile_db if reference else case.raw_cfr_profile_db,
            )

        def draw_preview() -> None:
            try:
                current_cases.clear()
                current_cases.extend(load_current_cases())
                for ax_i in (ax_compare, ax_low, ax_high):
                    ax_i.clear()
                x_rng = parse_pair_text(x_range_var.get(), (900.0, 1100.0))
                y_rng = parse_pair_text(y_range_var.get(), (-50.0, 10.0))
                x_scale = 1e3 if x_unit_var.get() == "mm" else 1.0
                x_unit = x_unit_var.get()
                colors = ["#64748b", "#dc2626", "#2563eb", "#0f766e", "#b45309", "#7c3aed"]
                compare_x_rng = (800.0, 1600.0) if x_unit == "mm" else (0.8, 1.6)
                def parse_step(text: str) -> float:
                    try:
                        return float(str(text).strip())
                    except Exception:
                        return float("nan")
                x_grid_step = parse_step(x_grid_var.get())
                y_grid_step = parse_step(y_grid_var.get())
                compare_x_grid_step = 200.0 if x_unit == "mm" else 0.2

                def plot_gui_profile(
                    ax_plot,
                    xr_m: np.ndarray,
                    yr_db: np.ndarray,
                    label: str,
                    x_window: tuple[float, float] | None = None,
                    max_points: int | None = None,
                    **kwargs: Any,
                ) -> None:
                    window = x_rng if x_window is None else x_window
                    x = np.asarray(xr_m, dtype=float).reshape(-1) * x_scale
                    y = np.asarray(yr_db, dtype=float).reshape(-1)
                    n = min(len(x), len(y))
                    if n < 2:
                        return
                    mask = (
                        np.isfinite(x[:n])
                        & np.isfinite(y[:n])
                        & (x[:n] >= window[0])
                        & (x[:n] <= window[1])
                    )
                    if np.count_nonzero(mask) >= 2:
                        xp = x[:n][mask]
                        yp = y[:n][mask]
                        if max_points is not None and max_points > 2 and len(xp) > max_points:
                            idx = np.linspace(0, len(xp) - 1, max_points, dtype=int)
                            xp = xp[idx]
                            yp = yp[idx]
                        ax_plot.plot(xp, yp, label=label, **kwargs)

                def normalized_cfr_display_profile(xr_m: np.ndarray, yr_db: np.ndarray) -> np.ndarray:
                    return normalize_db(yr_db)

                def shade_target_roi(ax_plot) -> None:
                    lo_m, hi_m = target_roi_m()
                    ax_plot.axvspan(
                        lo_m * x_scale,
                        hi_m * x_scale,
                        color="#bbf7d0",
                        alpha=0.24,
                        linewidth=0,
                        zorder=0,
                    )
                    ax_plot.text(
                        0.5 * (lo_m + hi_m) * x_scale,
                        9.0,
                        "ROI",
                        ha="center",
                        va="top",
                        fontsize=11,
                        color="#166534",
                    )

                def capture_compare_profiles(
                    case: RangeCase,
                    path: Path | None = None,
                ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
                    ref_path = path if path is not None else default_compare_capture_path()
                    key = f"{channel_var.get().strip().upper()}::{ref_path}::{len(case.si_range_m)}"
                    if key not in capture_profile_cache:
                        axis = case.si_range_m if len(case.si_range_m) else np.linspace(0.0, 2.0, 4096)
                        capture_profile_cache[key] = estimate_capture_profiles(
                            ref_path,
                            channel_var.get().strip() or "C2",
                            axis,
                            case.range_scale_m_per_s,
                        )
                    return capture_profile_cache[key]

                def profile_min_in_window(
                    xr_m: np.ndarray,
                    yr_db: np.ndarray,
                    x_window: tuple[float, float],
                ) -> float:
                    x = np.asarray(xr_m, dtype=float).reshape(-1) * x_scale
                    y = np.asarray(yr_db, dtype=float).reshape(-1)
                    n = min(len(x), len(y))
                    if n < 2:
                        return float("nan")
                    mask = (
                        np.isfinite(x[:n])
                        & np.isfinite(y[:n])
                        & (x[:n] >= x_window[0])
                        & (x[:n] <= x_window[1])
                    )
                    if np.count_nonzero(mask) < 2:
                        return float("nan")
                    return float(np.nanmin(y[:n][mask]))

                def peak_point(
                    xr_m: np.ndarray,
                    yr_db: np.ndarray,
                    x_window: tuple[float, float],
                ) -> tuple[float, float]:
                    x = np.asarray(xr_m, dtype=float).reshape(-1) * x_scale
                    y = np.asarray(yr_db, dtype=float).reshape(-1)
                    n = min(len(x), len(y))
                    if n < 2:
                        return float("nan"), float("nan")
                    mask = (
                        np.isfinite(x[:n])
                        & np.isfinite(y[:n])
                        & (x[:n] >= x_window[0])
                        & (x[:n] <= x_window[1])
                    )
                    if np.count_nonzero(mask) < 2:
                        return float("nan"), float("nan")
                    xv = x[:n][mask]
                    yv = y[:n][mask]
                    idx = int(np.nanargmax(yv))
                    return float(xv[idx]), float(yv[idx])

                def peak_label(px: float) -> str:
                    if x_unit == "mm":
                        return f"{px:.0f} mm"
                    return f"{px:.3f} m"

                def mark_peak(
                    ax_plot,
                    xr_m: np.ndarray,
                    yr_db: np.ndarray,
                    x_window: tuple[float, float],
                    color: str,
                    y_window: tuple[float, float],
                    text_offset_db: float = 0.0,
                ) -> None:
                    px, _ = peak_point(xr_m, yr_db, x_window)
                    if not math.isfinite(px):
                        return
                    ax_plot.axvline(px, color=color, linestyle="--", linewidth=0.85, alpha=0.95)
                    y0, y1 = y_window
                    ypos = min(y1 - 2.0, y0 + 2.0 + text_offset_db)
                    ax_plot.text(
                        px,
                        ypos,
                        peak_label(px),
                        color=color,
                        ha="center",
                        va="bottom",
                        fontsize=8,
                        bbox={"fc": "white", "ec": "none", "alpha": 0.75, "pad": 0.6},
                    )

                def annotate_peak_value(
                    ax_plot,
                    xr_m: np.ndarray,
                    yr_db: np.ndarray,
                    x_window: tuple[float, float],
                    y_window: tuple[float, float],
                    color: str,
                    x_offset: float = 0.0,
                    y_offset_db: float = 2.0,
                ) -> None:
                    px, py = peak_point(xr_m, yr_db, x_window)
                    if not (math.isfinite(px) and math.isfinite(py)):
                        return
                    y0, y1 = y_window
                    ypos = min(y1 - 2.0, max(y0 + 2.0, py + y_offset_db))
                    ax_plot.text(
                        px + x_offset,
                        ypos,
                        peak_label(px),
                        color=color,
                        ha="center",
                        va="bottom",
                        fontsize=8,
                        bbox={"fc": "white", "ec": "none", "alpha": 0.78, "pad": 0.6},
                        zorder=25,
                    )

                def mm_window(lo_mm: float, hi_mm: float) -> tuple[float, float]:
                    return (lo_mm, hi_mm) if x_unit == "mm" else (lo_mm * 1e-3, hi_mm * 1e-3)

                def closest_case(target_gbaud: float) -> RangeCase | None:
                    finite = [c for c in current_cases if math.isfinite(c.baud_gbaud)]
                    if finite:
                        return min(finite, key=lambda c: abs(c.baud_gbaud - target_gbaud))
                    return current_cases[0] if current_cases else None

                def style_ieee_axis(
                    ax_plot,
                    xlim: tuple[float, float],
                    ylim: tuple[float, float],
                    legend: bool = True,
                    x_step_override: float | None = None,
                    legend_loc: str = "best",
                ) -> None:
                    ax_plot.set_xlim(*xlim)
                    ax_plot.set_ylim(*ylim)
                    ax_plot.set_xlabel(f"Range ({x_unit})")
                    ax_plot.set_ylabel("Normalized magnitude (dB)")
                    x_step = x_grid_step if x_step_override is None else x_step_override
                    if math.isfinite(x_step) and x_step > 0:
                        ax_plot.xaxis.set_major_locator(MultipleLocator(x_step))
                    if math.isfinite(y_grid_step) and y_grid_step > 0:
                        ax_plot.yaxis.set_major_locator(MultipleLocator(y_grid_step))
                    ax_plot.grid(True, which="major", color="#cbd5e1", linewidth=0.45, alpha=0.75)
                    for side in ("top", "right", "bottom", "left"):
                        ax_plot.spines[side].set_visible(True)
                        ax_plot.spines[side].set_linewidth(0.8)
                    ax_plot.tick_params(direction="in", top=True, right=True, width=0.8)
                    try:
                        ax_plot.set_box_aspect(1)
                    except Exception:
                        pass
                    if legend:
                        handles, labels = ax_plot.get_legend_handles_labels()
                        if handles:
                            ax_plot.legend(
                                handles,
                                labels,
                                frameon=True,
                                loc=legend_loc,
                                fontsize=8,
                                facecolor="white",
                                edgecolor="#cbd5e1",
                                framealpha=0.9,
                            )

                finite_baud = [c for c in current_cases if math.isfinite(c.baud_gbaud)]
                low_case = closest_case(2.0)
                mid_case = closest_case(15.0)
                high_case = closest_case(20.0)
                compare_case = mid_case
                global_ref = display_reference_case(current_cases)

                if compare_case is not None:
                    _, _, cap_norm_rng, cap_norm_prof = capture_compare_profiles(compare_case)
                    _, _, extra_norm_rng, extra_norm_prof = capture_compare_profiles(
                        compare_case,
                        default_data_range_compare_path(),
                    )
                    if len(cap_norm_rng) < 2:
                        cap_norm_rng, cap_norm_prof = compare_case.si_range_m, compare_case.si_profile_db
                    compare_y_rng = (-50.0, 10.0)
                    plot_gui_profile(
                        ax_compare,
                        compare_case.mf_range_m,
                        compare_case.mf_profile_db,
                        "Matched filtering",
                        x_window=compare_x_rng,
                        color="#000000",
                        lw=1.25,
                        zorder=4,
                    )
                    plot_gui_profile(
                        ax_compare,
                        cap_norm_rng,
                        normalized_cfr_display_profile(cap_norm_rng, cap_norm_prof),
                        "_nolegend_",
                        x_window=compare_x_rng,
                        max_points=850,
                        color="#0000ff",
                        lw=1.0,
                        ls="--",
                        alpha=0.78,
                        zorder=2,
                    )
                    plot_gui_profile(
                        ax_compare,
                        extra_norm_rng,
                        normalized_cfr_display_profile(extra_norm_rng, extra_norm_prof),
                        "Normalized CFR",
                        x_window=compare_x_rng,
                        max_points=850,
                        color="#0000ff",
                        lw=1.15,
                        alpha=0.92,
                        zorder=3,
                    )
                    annotate_peak_value(
                        ax_compare,
                        extra_norm_rng,
                        normalized_cfr_display_profile(extra_norm_rng, extra_norm_prof),
                        mm_window(1050.0, 1150.0),
                        compare_y_rng,
                        "#0000ff",
                        y_offset_db=1.0,
                    )
                    annotate_peak_value(
                        ax_compare,
                        cap_norm_rng,
                        normalized_cfr_display_profile(cap_norm_rng, cap_norm_prof),
                        mm_window(950.0, 1050.0),
                        compare_y_rng,
                        "#0000ff",
                        y_offset_db=4.0,
                    )
                    psnr_values = [
                        ("MF", roi_psnr_db(compare_case.mf_range_m, compare_case.mf_profile_db)),
                        ("Norm. CFR/Data", roi_psnr_db(cap_norm_rng, cap_norm_prof)),
                        ("Norm. CFR/Data_range", roi_psnr_db(extra_norm_rng, extra_norm_prof)),
                    ]
                    psnr_text = "\n".join(
                        f"{label}: {value:.1f} dB" if math.isfinite(value) else f"{label}: N/A"
                        for label, value in psnr_values
                    )
                    pslr_values = [
                        ("Matched filtering", roi_pslr_db(compare_case.mf_range_m, compare_case.mf_profile_db)),
                        ("Normalized CFR", roi_pslr_db(extra_norm_rng, extra_norm_prof)),
                    ]
                    pslr_text = "\n".join(
                        (
                            f"{label}: {pslr:.1f} dB (peak {peak_x * 1e3:.0f} mm, "
                            f"sidelobe {side_x * 1e3:.0f} mm)"
                        )
                        if math.isfinite(pslr)
                        else f"{label}: N/A"
                        for label, (pslr, peak_x, side_x) in pslr_values
                    )
                else:
                    psnr_text = ""
                    pslr_text = ""
                    compare_y_rng = (-50.0, 10.0)

                def plot_ref_and_moved(ax_plot, case: RangeCase | None) -> None:
                    if case is None:
                        return
                    xr_ref = case.ref_si_range_m if len(case.ref_si_range_m) else case.si_range_m
                    yr_ref = case.ref_si_profile_db if len(case.ref_si_profile_db) else case.si_profile_db
                    xr_cur = case.si_range_m
                    yr_cur = case.si_profile_db
                    yr_ref_plot = normalized_cfr_display_profile(xr_ref, yr_ref)
                    yr_cur_plot = normalized_cfr_display_profile(xr_cur, yr_cur)
                    plot_gui_profile(
                        ax_plot,
                        xr_ref,
                        yr_ref_plot,
                        "Reference",
                        color="#111827",
                        lw=1.2,
                        ls="--",
                    )
                    plot_gui_profile(
                        ax_plot,
                        xr_cur,
                        yr_cur_plot,
                        "Moved",
                        color="#dc2626",
                        lw=1.25,
                    )
                    mark_peak(ax_plot, xr_ref, yr_ref_plot, x_rng, "#111827", y_rng, text_offset_db=0.0)
                    mark_peak(ax_plot, xr_cur, yr_cur_plot, x_rng, "#dc2626", y_rng, text_offset_db=5.0)

                plot_ref_and_moved(ax_low, low_case)
                plot_ref_and_moved(ax_high, high_case)

                finite_baud = [c for c in current_cases if math.isfinite(c.baud_gbaud)]
                shade_target_roi(ax_compare)
                style_ieee_axis(
                    ax_compare,
                    compare_x_rng,
                    compare_y_rng,
                    x_step_override=compare_x_grid_step,
                    legend_loc="upper right",
                )
                style_ieee_axis(ax_low, x_rng, y_rng)
                style_ieee_axis(ax_high, x_rng, y_rng, legend=False)
                fig.tight_layout()
                canvas.draw_idle()
                status = f"Preview updated: {len(current_cases)} case(s)."
                if psnr_text:
                    status += "  ROI PSNR: " + psnr_text.replace("\n", " | ")
                if pslr_text:
                    status += "  |  ROI PSLR: " + pslr_text.replace("\n", " | ")
                status_var.set(status)
            except Exception as exc:
                messagebox.showerror("Preview error", str(exc), parent=root)

        def save_preview() -> None:
            try:
                if not current_cases:
                    draw_preview()
                out_path = Path(out_var.get()).expanduser()
                out_path.parent.mkdir(parents=True, exist_ok=True)
                fig.set_dpi(max(72, int(float(dpi_var.get()))))
                fig.savefig(out_path, bbox_inches="tight")
                if csv_var.get().strip():
                    write_summary_csv(current_cases, Path(csv_var.get()).expanduser())
                status_var.set(f"Saved: {out_path}")
            except Exception as exc:
                messagebox.showerror("Save error", str(exc), parent=root)

        def save_single_axis(ax_obj, suffix: str) -> None:
            try:
                if not current_cases:
                    draw_preview()
                base = Path(out_var.get() or "thz_range_capacity.png").expanduser()
                suggested = base.with_name(f"{base.stem}_{suffix}{base.suffix or '.png'}")
                out = filedialog.asksaveasfilename(
                    title=f"Save {suffix} panel",
                    initialdir=str(suggested.parent),
                    initialfile=suggested.name,
                    defaultextension=suggested.suffix or ".png",
                    filetypes=[
                        ("PNG image", "*.png"),
                        ("PDF", "*.pdf"),
                        ("SVG", "*.svg"),
                        ("All files", "*.*"),
                    ],
                    parent=root,
                )
                if not out:
                    return
                canvas.draw()
                renderer = canvas.get_renderer()
                extent = ax_obj.get_tightbbox(renderer).expanded(1.08, 1.12)
                extent = extent.transformed(fig.dpi_scale_trans.inverted())
                out_path = Path(out).expanduser()
                out_path.parent.mkdir(parents=True, exist_ok=True)
                fig.savefig(out_path, dpi=max(72, int(float(dpi_var.get()))), bbox_inches=extent)
                status_var.set(f"Saved panel: {out_path}")
            except Exception as exc:
                messagebox.showerror("Save panel error", str(exc), parent=root)

        ttk.Button(actions, text="Preview", command=draw_preview).grid(row=0, column=1, padx=(8, 0))
        ttk.Button(actions, text="Save Figure", command=save_preview).grid(row=0, column=2, padx=(6, 0))
        ttk.Button(actions, text="Save Compare", command=lambda: save_single_axis(ax_compare, "compare")).grid(row=0, column=3, padx=(6, 0))
        ttk.Button(actions, text="Save 2G", command=lambda: save_single_axis(ax_low, "2gbaud")).grid(row=0, column=4, padx=(6, 0))
        ttk.Button(actions, text="Save 20G", command=lambda: save_single_axis(ax_high, "20gbaud")).grid(row=0, column=5, padx=(6, 0))
        ttk.Button(actions, text="Close", command=root.destroy).grid(row=0, column=6, padx=(6, 0))

        auto_find()
        root.after(200, draw_preview)
        root.mainloop()
        result["handled"] = True
        args._gui_handled = True
        return True
    except Exception as exc:
        print(f"GUI failed: {exc}")
        return False
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass


def auto_discover_specs(channel: str = "C2") -> list[tuple[str, Path]]:
    """Fallback for systems without Tk: pick closest 2/15/20 GBaud C2 files."""
    candidates: list[tuple[float, Path]] = []
    range_paths = sorted(default_range_dir().glob("Range*.npz"))
    if not range_paths:
        range_paths = sorted(default_range_dir().glob("range*.npz"))
    if not range_paths:
        range_paths = sorted(default_range_dir().glob("*.npz"))
    for path in range_paths:
        try:
            with np.load(path, allow_pickle=True) as loaded:
                results = collect_range_results(loaded)
                channels = {
                    str(item.get("ch", item.get("channel", ""))).strip().upper()
                    for item in results
                }
                if channel.strip().upper() not in channels:
                    continue
                baud = infer_baud_gbaud(path, loaded)
                if math.isfinite(baud) and baud > 0:
                    candidates.append((baud, path))
        except Exception:
            continue

    def closest(target: float) -> Path | None:
        if not candidates:
            return None
        baud, path = min(candidates, key=lambda item: abs(item[0] - target))
        if abs(baud - target) > max(1.0, 0.35 * target):
            return None
        return path

    specs: list[tuple[str, Path]] = []
    b2 = closest(2.0)
    b15 = closest(15.0)
    b20 = closest(20.0)
    if b2 is not None:
        specs.append(("2 GBaud", b2))
    if b15 is not None and b15 not in {b2}:
        specs.append(("15 GBaud", b15))
    if b20 is not None and b20 not in {b2, b15}:
        specs.append(("20 GBaud", b20))
    return specs


def main() -> None:
    default_out = default_range_dir() / "thz_range_capacity.png"
    parser = argparse.ArgumentParser(
        description="Create THz ISAC range-capacity plots from saved range NPZ files.",
    )
    add_case_arg(parser, "--b2", "Saved C2 range NPZ for the low-bandwidth, e.g. 2 GBaud, case.")
    add_case_arg(parser, "--b20", "Saved C2 range NPZ for the high-bandwidth case. This file may contain both reference and moved profiles.")
    add_case_arg(parser, "--ref", "Optional legacy separate reference NPZ. Usually not needed for Save Range files.")
    add_case_arg(parser, "--move", "Optional legacy separate moved-target NPZ. Usually not needed for Save Range files.")
    parser.add_argument(
        "--case",
        action="append",
        help="Additional case as LABEL=path.npz. Can be repeated.",
    )
    parser.add_argument("--channel", default="C2", help="Radar channel to extract. Default: C2.")
    parser.add_argument("--out", type=Path, default=default_out, help=f"Output figure path. Default: {default_out}")
    parser.add_argument("--summary-csv", type=Path, default=None, help="Optional CSV summary output path.")
    parser.add_argument("--profile-x-m", nargs=2, type=float, default=(0.0, 3.0), metavar=("MIN", "MAX"))
    parser.add_argument("--profile-y-db", nargs=2, type=float, default=(-50.0, 3.0), metavar=("MIN", "MAX"))
    parser.add_argument("--zoom-x-mm", nargs=2, type=float, default=(900.0, 1100.0), metavar=("MIN", "MAX"))
    parser.add_argument("--zoom-y-db", nargs=2, type=float, default=(-50.0, 10.0), metavar=("MIN", "MAX"))
    parser.add_argument("--ref-mm", type=float, default=1018.0, help="Reference position marker in mm.")
    parser.add_argument("--move-mm", type=float, default=1011.0, help="Moved position marker in mm.")
    parser.add_argument("--si-bins", type=int, default=4096, help="Range bins for normalized CFR recomputation.")
    parser.add_argument("--dpi", type=int, default=220)
    parser.add_argument("--show", action="store_true", help="Display the figure after saving.")
    parser.add_argument("--no-gui", action="store_true", help="Do not open file dialogs when no cases are provided.")
    args = parser.parse_args()

    ran_bare = len(sys.argv) == 1
    if ran_bare and not args.no_gui:
        if prompt_cases_gui(args):
            if bool(getattr(args, "_gui_handled", False)):
                return
        else:
            print("No GUI selection was made; trying automatic discovery in data/range.")

    specs = build_cases(args)
    if not specs:
        specs = auto_discover_specs(args.channel)
    if not specs:
        raise SystemExit(
            "Provide at least one saved range case, for example --b2 file.npz --b20 file.npz.\n"
            "A Save Range NPZ already contains both reference and moved/current profiles.\n"
            "If you want file dialogs, run without arguments on a Python installation with tkinter/Tcl enabled."
        )

    range_max_m = max(float(args.profile_x_m[1]), float(args.zoom_x_mm[1]) * 1e-3, 2.0)
    si_axis = np.linspace(0.0, range_max_m, max(256, int(args.si_bins)))
    cases = [load_case(path, label, args.channel, si_axis) for label, path in specs]

    make_figure(cases, args)
    if args.summary_csv:
        write_summary_csv(cases, args.summary_csv)

    print(f"Saved figure: {args.out}")
    if args.summary_csv:
        print(f"Saved summary CSV: {args.summary_csv}")
    for case in cases:
        print(
            f"{case.label}: {case.baud_gbaud:.3g} GBaud, "
            f"peak={case.range_peak_m * 1e3:.3f} mm, "
            f"dR={case.range_diff_mm:.3f} mm"
        )


if __name__ == "__main__":
    main()
