"""Estimate the asymmetric SSBI contribution from DFT-s-OFDM captures.

For each active subcarrier, fit the known desired-signal and square-law SSBI
templates to the received block,

    Y[m, k] = H[k] X[m, k] + G[k] Q[m, k] + N[m, k],

where Q is generated from |x(t)|^2 and shifted through the same IF
downconversion as the receiver.  The reduction in degrees-of-freedom-corrected
residual power when Q is added is reported as an identifiable SSBI lower
bound.  It excludes SSBI components collinear with X and model mismatch.
"""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path
from typing import Any

import numpy as np

from isac_gui import DsoPanel
from read_range_data import unpack


DEFAULT_DATA_DIR = Path(__file__).resolve().parent / "data" / "captures" / "bandwidth"


def _payload(loaded: np.lib.npyio.NpzFile) -> dict[str, Any]:
    return {key.removeprefix("tx__"): unpack(loaded[key]) for key in loaded.files if key.startswith("tx__")}


def estimate_capture(path: Path, channel: str = "C1") -> dict[str, float | str]:
    """Estimate effective SNR and asymmetric SSBI for one capture."""
    with np.load(path, allow_pickle=True) as loaded:
        pl = _payload(loaded)
        signal_key = f"rx__{channel}__sig"
        fs_key = f"rx__{channel}__fs"
        if signal_key not in loaded.files or fs_key not in loaded.files:
            raise ValueError(f"{path.name}: missing {signal_key}/{fs_key}")
        raw = np.asarray(loaded[signal_key], dtype=np.float64).reshape(-1)
        fs_rx = float(unpack(loaded[fs_key]))

    panel = object.__new__(DsoPanel)
    panel._log = lambda _message: None
    rx_bb, fs_ref = panel._rx_to_baseband(raw, fs_rx, pl)
    rx_mat, tx_mat, _, _, _, _, _, _, _ = panel._frame_sync_and_reshape(rx_bb, fs_ref, pl)

    n_fft = int(pl.get("dft_n_fft", 0))
    active_bins = np.asarray(pl.get("dft_active_bins", []), dtype=np.int64).reshape(-1)
    n_blocks = min(rx_mat.shape[0], tx_mat.shape[0])
    if n_fft <= 0 or len(active_bins) < 16 or n_blocks < 3:
        raise ValueError(f"{path.name}: insufficient DFT-s-OFDM reference or blocks")

    rx_rows = rx_mat[:n_blocks, :n_fft]
    tx_rows = tx_mat[:n_blocks, :n_fft]
    y = np.fft.fft(rx_rows, axis=1)[:, active_bins]
    x = np.fft.fft(tx_rows, axis=1)[:, active_bins]

    # Direct-detection square-law template.  A real |x|^2 term is centered at
    # physical DC; receiver mixing by -f_IF shifts its positive-frequency
    # lobe toward the lower side of the desired complex-baseband passband.
    if_hz = float(pl.get("iqtools_if_freq", pl.get("if_freq", 0.0)))
    t_block = np.arange(n_fft, dtype=np.float64) / fs_ref
    intensity = np.abs(tx_rows) ** 2
    intensity -= np.mean(intensity, axis=1, keepdims=True)
    q_down = 2.0 * intensity * np.exp(-1j * 2.0 * np.pi * if_hz * t_block)[np.newaxis, :]
    q = np.fft.fft(q_down, axis=1)[:, active_bins]

    x_energy = np.sum(np.abs(x) ** 2, axis=0)
    h = np.sum(y * np.conj(x), axis=0) / (x_energy + 1e-30)
    predicted = x * h[np.newaxis, :]
    residual = y - predicted

    # Unbiased residual variance for one fitted complex channel coefficient.
    signal_power = np.mean(np.abs(predicted) ** 2, axis=0)
    residual_power = np.sum(np.abs(residual) ** 2, axis=0) / max(n_blocks - 1, 1)
    freq_hz = np.fft.fftfreq(n_fft, d=1.0 / fs_ref)[active_bins]

    # Diagnostic only: remove one common complex gain/phase per block after
    # the frequency response fit.  A large improvement indicates block-scale
    # CPE/clock drift that a PSD noise-floor SNR cannot observe.
    predicted_cpe = np.empty_like(predicted)
    for block in range(n_blocks):
        den = float(np.vdot(predicted[block], predicted[block]).real) + 1e-30
        common = np.vdot(predicted[block], y[block]) / den
        predicted_cpe[block] = common * predicted[block]
    residual_cpe = y - predicted_cpe
    cpe_corrected_snr_db = 10.0 * math.log10(
        float(np.sum(np.abs(predicted_cpe) ** 2)) /
        max(float(np.sum(np.abs(residual_cpe) ** 2)), np.finfo(float).tiny)
    )

    order = np.argsort(freq_hz)
    freq_hz = freq_hz[order]
    signal_power = signal_power[order]
    residual_power = residual_power[order]
    valid = np.isfinite(signal_power) & np.isfinite(residual_power) & (signal_power > 1e-30)
    near = valid & (freq_hz < 0.0)
    far = valid & (freq_hz > 0.0)
    if np.count_nonzero(near) < 8 or np.count_nonzero(far) < 8:
        raise ValueError(f"{path.name}: active bins do not span both sides of DC")

    # Match each near-DC bin to the far-side residual-to-signal ratio at the
    # same |baseband frequency|.  This cancels common DSO/AWGN while retaining
    # the expected lower-side SSBI excess.
    far_freq = freq_hz[far]
    far_ratio = residual_power[far] / signal_power[far]
    far_order = np.argsort(far_freq)
    baseline_ratio_near = np.interp(
        np.abs(freq_hz[near]), far_freq[far_order], far_ratio[far_order],
        left=float(far_ratio[far_order][0]), right=float(far_ratio[far_order][-1]),
    )
    baseline_power_near = baseline_ratio_near * signal_power[near]
    excess_power_near = np.maximum(residual_power[near] - baseline_power_near, 0.0)

    total_signal = float(np.sum(signal_power[valid]))
    total_error = float(np.sum(residual_power[valid]))
    ssbi_excess = float(np.sum(excess_power_near))
    baseline_error = max(total_error - ssbi_excess, np.finfo(float).tiny)
    effective_snr_db = 10.0 * math.log10(total_signal / max(total_error, np.finfo(float).tiny))
    ssbi_sir_lb_db = 10.0 * math.log10(total_signal / max(ssbi_excess, np.finfo(float).tiny))
    ssbi_penalty_db = 10.0 * math.log10(total_error / baseline_error)

    near_ratio = float(np.sum(residual_power[near]) / np.sum(signal_power[near]))
    far_ratio_total = float(np.sum(residual_power[far]) / np.sum(signal_power[far]))
    asymmetry_db = 10.0 * math.log10(near_ratio / max(far_ratio_total, np.finfo(float).tiny))

    # Nested complex LS regression: compare X-only against [X,Q].  Scaling
    # SSE by its residual degrees of freedom removes the automatic apparent
    # improvement that an extra regressor would obtain from fitting noise.
    noise_power_two_template = np.zeros(y.shape[1], dtype=np.float64)
    usable_q = np.zeros(y.shape[1], dtype=bool)
    for k in range(y.shape[1]):
        xk = x[:, k]
        qk = q[:, k]
        xnorm = float(np.linalg.norm(xk))
        qnorm = float(np.linalg.norm(qk))
        if xnorm <= 1e-15 or qnorm <= 1e-10 * xnorm:
            noise_power_two_template[k] = residual_power[k]
            continue
        design = np.column_stack((xk / xnorm, qk / qnorm))
        if np.linalg.cond(design) > 30.0:
            noise_power_two_template[k] = residual_power[k]
            continue
        beta, *_ = np.linalg.lstsq(design, y[:, k], rcond=None)
        residual_two = y[:, k] - design @ beta
        noise_power_two_template[k] = float(np.sum(np.abs(residual_two) ** 2)) / max(n_blocks - 2, 1)
        usable_q[k] = True

    # Only bins where the physical Q template is identifiable participate in
    # the SSBI estimate.  P_X is the X-only impairment; P_N is the residual
    # after also fitting Q.  Their positive difference is identifiable SSBI.
    fit_mask = valid & usable_q
    if np.count_nonzero(fit_mask) < 4:
        template_ssbi_power = 0.0
        template_noise_power = float(np.sum(residual_power[valid]))
    else:
        x_only_error = float(np.sum(residual_power[fit_mask]))
        template_noise_power = float(np.sum(noise_power_two_template[fit_mask]))
        template_ssbi_power = max(x_only_error - template_noise_power, 0.0)
    template_signal_power = float(np.sum(signal_power[fit_mask])) if np.any(fit_mask) else total_signal
    template_sir_db = (
        10.0 * math.log10(template_signal_power / template_ssbi_power)
        if template_ssbi_power > 0.0 else float("inf")
    )
    template_penalty_db = 10.0 * math.log10(
        (template_noise_power + template_ssbi_power) /
        max(template_noise_power, np.finfo(float).tiny)
    )

    return {
        "file": path.name,
        "modulation": str(pl.get("modulation", "?")),
        "symbol_rate_gbaud": float(pl.get("symbol_rate_actual", pl.get("symbol_rate", 0.0))) * 1e-9,
        "blocks": float(n_blocks),
        "effective_snr_db": effective_snr_db,
        "cpe_corrected_snr_db": cpe_corrected_snr_db,
        "cpe_penalty_db": cpe_corrected_snr_db - effective_snr_db,
        "near_far_residual_db": asymmetry_db,
        "asymmetry_ssbi_sir_lower_bound_db": ssbi_sir_lb_db,
        "asymmetry_ssbi_penalty_db": ssbi_penalty_db,
        "template_bins": float(np.count_nonzero(fit_mask)),
        "ssbi_sir_lower_bound_db": template_sir_db,
        "ssbi_penalty_db": template_penalty_db,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--modulation", default="16QAM")
    parser.add_argument("--channel", default="C1")
    parser.add_argument("--out", type=Path, default=DEFAULT_DATA_DIR / "subcarrier_ssbi_estimates.csv")
    args = parser.parse_args()

    paths = sorted(args.data_dir.glob(f"Data*DFT-s-OFDM*{args.modulation}*.npz"))
    if not paths:
        parser.error(f"no matching captures in {args.data_dir}")

    rows: list[dict[str, float | str]] = []
    print(f"{'GBaud':>7} {'SNR':>8} {'CPE gain':>9} {'near-far':>10} {'SSBI SIR>':>11} {'penalty':>9}")
    for path in paths:
        try:
            row = estimate_capture(path, channel=args.channel)
        except Exception as exc:
            print(f"SKIP {path.name}: {exc}")
            continue
        rows.append(row)
        print(
            f"{float(row['symbol_rate_gbaud']):7.2f} "
            f"{float(row['effective_snr_db']):8.2f} "
            f"{float(row['cpe_penalty_db']):9.2f} "
            f"{float(row['near_far_residual_db']):10.2f} "
            f"{float(row['ssbi_sir_lower_bound_db']):11.2f} "
            f"{float(row['ssbi_penalty_db']):9.2f}"
        )

    if not rows:
        raise SystemExit("No captures could be estimated")
    rows.sort(key=lambda row: float(row["symbol_rate_gbaud"]))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Saved: {args.out}")


if __name__ == "__main__":
    main()
