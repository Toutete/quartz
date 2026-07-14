"""Diagnostic: compare the lower-half (near-DC side) vs upper-half (far side)
of the occupied passband within the SAME capture's live raw spectrum.

Note: the stored "range_zero__*__cfr_*" fields turned out to be a STALE,
session-shared reference (bit-identical across different fsym files), not a
live per-capture channel estimate -- so this uses the raw RX waveform's own
PSD instead (rx__C1__sig, which is genuinely unique per file), split at the
IF center f_IF using each file's own symbol rate for the passband edges.

If SSBI concentrates near DC, the lower-half noise floor (valleys between
spectral features) should sit higher than the upper-half, with the gap
growing as B grows (guard margin f_IF-B/2 shrinks).

Not part of the paper figure pipeline -- a one-off investigation script.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from read_range_data import compute_raw_spectrum, to_float, unpack

DATA_DIR = Path(__file__).resolve().parent / "data" / "captures" / "bandwidth"
F_IF_GHZ = 11.0

FILES = [
    "Data_fIF11_fsym2_P-8_fRF280_DFT-s-OFDM_16QAM_Iph7.npz",
    "Data_fIF11_fsym4_P-8_fRF280_DFT-s-OFDM_16QAM_Iph7.npz",
    "Data_fIF11_fsym8_P-8_fRF280_DFT-s-OFDM_16QAM_Iph7.npz",
    "Data_fIF11_fsym10_P-8_fRF280_DFT-s-OFDM_16QAM_Iph7.npz",
    "Data_fIF11_fsym12_P-8_fRF280_DFT-s-OFDM_16QAM_Iph7.npz",
    "Data_fIF11_fsym15_P-7_fRF280_DFT-s-OFDM_16QAM_Iph7.npz",
    "Data_fIF11_fsym17_P-7_fRF280_DFT-s-OFDM_16QAM_Iph7.npz",
    "Data_fIF11_fsym20_P-9_fRF280_DFT-s-OFDM_16QAM_Iph7.npz",
]


def half_floor_db(freq_ghz: np.ndarray, mag_db: np.ndarray, lo: float, hi: float, pct: float) -> float:
    mask = (freq_ghz >= lo) & (freq_ghz <= hi)
    if np.count_nonzero(mask) < 8:
        return float("nan")
    return float(np.percentile(mag_db[mask], pct))


results: list[tuple[float, float]] = []
print(f"{'Symbol rate':<12}{'B (GHz)':>9}{'lower-floor':>14}{'upper-floor':>14}{'lower-upper':>14}")
for fname in FILES:
    path = DATA_DIR / fname
    with np.load(path, allow_pickle=True) as d:
        sig = np.asarray(d["rx__C1__sig"], dtype=float).reshape(-1)
        fs = float(unpack(d["rx__C1__fs"]))
        baud_hz = to_float(unpack(d["tx__symbol_rate_actual"])) if "tx__symbol_rate_actual" in d.files else float("nan")
    freq_ghz, mag_db = compute_raw_spectrum(sig, fs)
    b_ghz = baud_hz * 1e-9
    edge_lo, edge_hi = F_IF_GHZ - b_ghz / 2.0, F_IF_GHZ + b_ghz / 2.0

    # 5th-percentile "valley floor" within each half of the occupied band --
    # the closest thing to a local noise floor under a non-flat spectrum.
    lower_db = half_floor_db(freq_ghz, mag_db, edge_lo, F_IF_GHZ, 5.0)
    upper_db = half_floor_db(freq_ghz, mag_db, F_IF_GHZ, edge_hi, 5.0)
    diff = lower_db - upper_db if math.isfinite(lower_db) and math.isfinite(upper_db) else float("nan")
    label = f"{b_ghz:.3g} GBaud"
    print(f"{label:<12}{b_ghz:>9.2f}{lower_db:>14.2f}{upper_db:>14.2f}{diff:>+14.2f}")
    if math.isfinite(diff):
        results.append((b_ghz, diff))

fig, ax = plt.subplots(figsize=(5.2, 3.6), dpi=140)
b_vals, diffs = zip(*results)
ax.axhline(0.0, color="gray", lw=0.8, ls="--")
ax.plot(b_vals, diffs, "o-", color="#dc2626", lw=1.5, ms=6)
ax.set_xlabel("Symbol rate (GBaud)")
ax.set_ylabel("Lower-half $-$ upper-half floor (dB)")
ax.set_title("Passband asymmetry: near-DC side vs far side")
ax.grid(alpha=0.3)
fig.tight_layout()
out = DATA_DIR / "subcarrier_asymmetry.png"
fig.savefig(out, bbox_inches="tight")
print(f"\nSaved: {out}")
