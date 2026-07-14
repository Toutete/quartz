"""Diagnostic: overlay raw RX baseband spectra across symbol rates to check
whether (a) the far out-of-band noise floor is roughly constant with B
(consistent with a DSO/instrument-limited floor) and (b) a growing pedestal
appears near DC/IF as B increases (the SSBI signature).

Not part of the paper figure pipeline -- a one-off investigation script.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from read_range_data import compute_raw_spectrum, unpack

DATA_DIR = Path(__file__).resolve().parent / "data" / "captures" / "bandwidth"

F_IF_GHZ = 11.0
FILES = [
    ("2 GBaud", "Data_fIF11_fsym2_P-8_fRF280_DFT-s-OFDM_16QAM_Iph7.npz", 2.0),
    ("4 GBaud", "Data_fIF11_fsym4_P-8_fRF280_DFT-s-OFDM_16QAM_Iph7.npz", 4.0),
    ("8 GBaud", "Data_fIF11_fsym8_P-8_fRF280_DFT-s-OFDM_16QAM_Iph7.npz", 8.0),
    ("12 GBaud", "Data_fIF11_fsym12_P-8_fRF280_DFT-s-OFDM_16QAM_Iph7.npz", 12.0),
    ("20 GBaud", "Data_fIF11_fsym20_P-9_fRF280_DFT-s-OFDM_16QAM_Iph7.npz", 20.0),
]

fig, (ax_full, ax_zoom) = plt.subplots(1, 2, figsize=(11, 4.2), dpi=140)
colors = ["#16a34a", "#eab308", "#dc2626", "#7c3aed", "#9333ea"]

noise_floor_report = []
for (label, fname, baud), color in zip(FILES, colors):
    path = DATA_DIR / fname
    with np.load(path, allow_pickle=True) as d:
        sig = np.asarray(d["rx__C1__sig"], dtype=float).reshape(-1)
        fs = float(unpack(d["rx__C1__fs"]))
    freq_ghz, mag_db = compute_raw_spectrum(sig, fs)
    ax_full.plot(freq_ghz, mag_db, lw=0.8, color=color, label=label, alpha=0.85)
    ax_zoom.plot(freq_ghz, mag_db, lw=0.8, color=color, label=label, alpha=0.85)

    # Reference noise floor: bands immediately adjacent to the occupied
    # passband (edge-3..edge-1 GHz below, edge+1..edge+3 GHz above), which is
    # where the "5/15 GHz for 2 GBaud" flat floor sits -- clear of the near-DC
    # SSBI pedestal and the ~22 GHz harmonic.
    edge_lo = F_IF_GHZ - baud / 2.0
    edge_hi = F_IF_GHZ + baud / 2.0
    ref_mask = ((freq_ghz >= edge_lo - 3.0) & (freq_ghz <= edge_lo - 1.0)) | \
               ((freq_ghz >= edge_hi + 1.0) & (freq_ghz <= edge_hi + 3.0))
    noise_floor_db = float(np.median(mag_db[ref_mask])) if np.any(ref_mask) else float("nan")

    # SSBI window: a narrow near-DC band (0.05-1.5 GHz), capped to stay >=1 GHz
    # below the passband's lower edge. Fixed width so the comparison across B
    # isn't diluted by averaging over an ever-wider DC-to-passband gap.
    ssbi_hi = min(1.5, edge_lo - 1.0)
    if ssbi_hi > 0.3:
        ssbi_mask = (freq_ghz >= 0.05) & (freq_ghz <= ssbi_hi)
        ssbi_db = float(np.median(mag_db[ssbi_mask]))
    else:
        ssbi_db = float("nan")  # window degenerate: SSBI has swamped the guard band

    ax_zoom.axvspan(edge_lo - 3.0, edge_lo - 1.0, color=color, alpha=0.08)
    noise_floor_report.append((label, noise_floor_db, ssbi_db,
                                (ssbi_db - noise_floor_db) if math.isfinite(ssbi_db) else float("nan")))

ax_full.set_title("Full raw spectrum (C1)")
ax_full.set_xlabel("Frequency (GHz)")
ax_full.set_ylabel("Magnitude (dB rel.)")
ax_full.set_xlim(0, 30)
ax_full.grid(alpha=0.3)
ax_full.legend(fontsize=8)

ax_zoom.set_title("Zoom: DC..IF region (SSBI pedestal check)")
ax_zoom.set_xlabel("Frequency (GHz)")
ax_zoom.set_ylabel("Magnitude (dB rel.)")
ax_zoom.set_xlim(0, 14)
ax_zoom.axvline(11.0, color="k", lw=0.9, ls="--", label="f_IF=11 GHz")
ax_zoom.grid(alpha=0.3)
ax_zoom.legend(fontsize=8)

fig.tight_layout()
out = DATA_DIR / "ssbi_noise_floor_check.png"
fig.savefig(out, bbox_inches="tight")
print(f"Saved: {out}")
print("\nEdge-adjacent noise floor vs near-DC SSBI window:")
for label, noise_floor_db, ssbi_db, excess in noise_floor_report:
    print(f"  {label}: noise_floor={noise_floor_db:.2f} dB, SSBI_window={ssbi_db:.2f} dB, excess={excess:+.2f} dB")
