"""Reproduce the ax_compare panel's Matched-filtering vs Normalized-CFR
curves (default fsym15 comparison files) and report ROI PSLR for both.

Not part of the paper figure pipeline -- a one-off verification script for
the roi_pslr_db() helper added to plot_range_capacity_figure.py.
"""

from __future__ import annotations

import numpy as np

from pathlib import Path

from plot_range_capacity_figure import (
    C,
    default_data_range_compare_path,
    default_range_dir,
    estimate_capture_profiles,
    load_case,
    roi_pslr_db,
    roi_psnr_db,
    target_roi_m,
)

CHANNEL = "C2"
SI_AXIS = np.linspace(0.0, 2.0, 4096)

# default_compare_capture_path() is a "Data_" capture -- it has no saved
# matched-filter range profile (rng/prof_db). The black "Matched filtering"
# curve in the GUI comes from whichever "Range_*.npz" file the user loaded
# for fsym~15; use the one that ships alongside the default compare files.
MF_SOURCE = default_range_dir() / "Range_fIF11_fsym15_P-8_fRF280_DFT-s-OFDM_32QAM_Iph6.5.npz"

mf_case = load_case(MF_SOURCE, "Matched filtering", CHANNEL, SI_AXIS)
_, _, norm_rng, norm_prof = estimate_capture_profiles(
    default_data_range_compare_path(), CHANNEL, SI_AXIS, C / 2.0
)

lo_m, hi_m = target_roi_m()
print(f"ROI: {lo_m * 1e3:.0f}-{hi_m * 1e3:.0f} mm\n")

for label, xr, yr in (
    ("Matched filtering", mf_case.mf_range_m, mf_case.mf_profile_db),
    ("Normalized CFR", norm_rng, norm_prof),
):
    pslr, peak_x, side_x = roi_pslr_db(xr, yr)
    psnr = roi_psnr_db(xr, yr)
    print(f"{label}:")
    print(f"  PSLR = {pslr:.2f} dB  (peak {peak_x * 1e3:.1f} mm, sidelobe {side_x * 1e3:.1f} mm)")
    print(f"  PSNR (peak vs. ROI median floor) = {psnr:.2f} dB")
