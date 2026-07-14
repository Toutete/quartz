"""Compare ZC-pilot and known-full-TX DFT-s-OFDM channel estimators.

The full-reference estimator is evaluated leave-one-block-out (LOOCV): the
frequency-selective channel is fitted on all other known TX/RX blocks, then
used to recover the held-out block.  This prevents the zero-residual result
that would occur if every subcarrier were fitted and evaluated on the same
block.  One complex scalar per block is removed from both paths so the result
compares frequency-selective channel-estimation error rather than CPE/gain.
"""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path
from typing import Any

import numpy as np

from isac_gui import DsoPanel
from read_range_data import metric_map, to_float, unpack


DEFAULT_DATA_DIR = Path(__file__).resolve().parent / "data" / "captures"


def _payload(loaded: np.lib.npyio.NpzFile) -> dict[str, Any]:
    return {key.removeprefix("tx__"): unpack(loaded[key]) for key in loaded.files if key.startswith("tx__")}


def _smooth_complex(values: np.ndarray, weight: np.ndarray | None = None) -> np.ndarray:
    values = np.asarray(values, dtype=np.complex128).reshape(-1)
    if len(values) < 5:
        return values.copy()
    valid = np.isfinite(values.real) & np.isfinite(values.imag)
    if np.count_nonzero(valid) < 4:
        return np.ones_like(values)
    index = np.arange(len(values), dtype=float)
    filled = np.interp(index, index[valid], values.real[valid]) + 1j * np.interp(
        index, index[valid], values.imag[valid]
    )
    window = int(np.clip(len(values) // 32, 5, 65))
    if window % 2 == 0:
        window += 1
    if window >= len(values):
        return filled
    kernel = np.hanning(window)
    kernel /= np.sum(kernel) + 1e-30
    weights = np.ones(len(values)) if weight is None else np.maximum(np.asarray(weight, float), 0.0)
    pad = window // 2
    denominator = np.convolve(np.pad(weights, pad, mode="edge"), kernel, mode="valid")
    real = np.convolve(np.pad(filled.real * weights, pad, mode="edge"), kernel, mode="valid")
    imag = np.convolve(np.pad(filled.imag * weights, pad, mode="edge"), kernel, mode="valid")
    return (real + 1j * imag) / (denominator + 1e-30)


def _correct_to_reference(estimate: np.ndarray, reference: np.ndarray) -> np.ndarray:
    """Remove linear phase and one complex gain, identically for both paths."""
    estimate = np.asarray(estimate, dtype=np.complex128).reshape(-1).copy()
    reference = np.asarray(reference, dtype=np.complex128).reshape(-1)
    pair = estimate * np.conj(reference)
    valid = np.abs(pair) > 1e-12
    if np.count_nonzero(valid) >= 2:
        index = np.arange(len(estimate), dtype=float)
        slope, intercept = np.polyfit(index[valid], np.unwrap(np.angle(pair[valid])), 1)
        estimate *= np.exp(-1j * (slope * index + intercept))
    gain = np.vdot(estimate, reference) / (np.vdot(estimate, estimate).real + 1e-30)
    return gain * estimate


def _fit_full_reference_channel(x: np.ndarray, y: np.ndarray, iterations: int = 4) -> np.ndarray:
    """Fit Y[m,k] = c[m] H[k] X[m,k] with alternating complex LS."""
    block_gain = np.ones(x.shape[0], dtype=np.complex128)
    channel = np.ones(x.shape[1], dtype=np.complex128)
    weight = np.sum(np.abs(x) ** 2, axis=0)
    for _ in range(max(1, iterations)):
        design = block_gain[:, None] * x
        channel_raw = np.sum(np.conj(design) * y, axis=0) / (np.sum(np.abs(design) ** 2, axis=0) + 1e-30)
        channel = _smooth_complex(channel_raw, weight)
        predicted = x * channel[None, :]
        block_gain = np.sum(np.conj(predicted) * y, axis=1) / (
            np.sum(np.abs(predicted) ** 2, axis=1) + 1e-30
        )
        normalization = np.mean(np.abs(block_gain))
        if normalization > 1e-15:
            block_gain /= normalization
            channel *= normalization
    return channel


def _symbols_from_channel(
    y_active: np.ndarray,
    channel: np.ndarray,
    pilot_active: np.ndarray,
    data_scale: float,
    data_fraction: float,
    n_data: int,
) -> np.ndarray:
    data_active = (y_active / (channel + 1e-30) - pilot_active) / data_fraction
    spread = data_active * data_scale
    return np.fft.ifft(spread * np.sqrt(n_data))[:n_data]


def compare_capture(path: Path, channel_name: str = "C1") -> dict[str, float | str]:
    with np.load(path, allow_pickle=True) as loaded:
        pl = _payload(loaded)
        raw = np.asarray(loaded[f"rx__{channel_name}__sig"], dtype=np.float64).reshape(-1)
        fs_rx = float(unpack(loaded[f"rx__{channel_name}__fs"]))
        stored_evm_db = to_float(metric_map(loaded).get("evm_db", {}).get("value", float("nan")))

    panel = object.__new__(DsoPanel)
    panel._log = lambda _message: None
    rx_bb, fs_ref = panel._rx_to_baseband(raw, fs_rx, pl)
    rx_mat, tx_mat, tx_symbols, _, _, _, _, _, _ = panel._frame_sync_and_reshape(rx_bb, fs_ref, pl)

    active_bins = np.asarray(pl.get("dft_active_bins", []), dtype=np.int64).reshape(-1)
    pilot = np.asarray(pl.get("dft_zc_pilot", []), dtype=np.complex128).reshape(-1)
    scales = np.asarray(pl.get("dft_data_scale", []), dtype=float).reshape(-1)
    n_fft = int(pl.get("dft_n_fft", len(pilot)))
    n_data = int(pl.get("dft_n_data", len(active_bins)))
    rho = float(np.clip(float(pl.get("amplitude_ratio_rho", 0.2)), 0.0, 0.95))
    n_blocks = min(rx_mat.shape[0], tx_mat.shape[0], tx_symbols.shape[0], len(scales))
    if n_blocks < 3 or n_fft <= 0 or len(active_bins) != n_data or len(pilot) != n_fft:
        raise ValueError(f"{path.name}: incomplete DFT-s-OFDM references or fewer than three blocks")

    y = np.fft.fft(rx_mat[:n_blocks, :n_fft], axis=1)[:, active_bins]
    x = np.fft.fft(tx_mat[:n_blocks, :n_fft], axis=1)[:, active_bins]
    reference = np.asarray(tx_symbols[:n_blocks, :n_data], dtype=np.complex128)
    pilot_active = np.sqrt(max(rho, 1e-12)) * np.fft.fft(pilot)[active_bins]
    data_fraction = np.sqrt(max(1.0 - rho, 1e-12))

    zc_rows: list[np.ndarray] = []
    full_rows: list[np.ndarray] = []
    for test_block in range(n_blocks):
        scale = float(scales[test_block]) if scales[test_block] > 0 else 1.0

        train = np.arange(n_blocks) != test_block

        # ZC-only LOOCV: estimate the common channel from the repeated pilot
        # in every other block.  Different data blocks act as contamination
        # that is suppressed by cross-block LS averaging and smoothing.
        zc_reference = np.tile(pilot_active, (np.count_nonzero(train), 1))
        zc_channel = _fit_full_reference_channel(zc_reference, y[train])
        predicted_pilot = pilot_active * zc_channel
        zc_test_gain = np.vdot(predicted_pilot, y[test_block]) / (
            np.vdot(predicted_pilot, predicted_pilot).real + 1e-30
        )
        zc_estimate = _symbols_from_channel(
            y[test_block], zc_test_gain * zc_channel, pilot_active, scale, data_fraction, n_data
        )
        zc_rows.append(_correct_to_reference(zc_estimate, reference[test_block]))

        # Known-full-TX LOOCV: fit frequency response on every other block.
        full_channel = _fit_full_reference_channel(x[train], y[train])
        predicted_test = x[test_block] * full_channel
        test_gain = np.vdot(predicted_test, y[test_block]) / (
            np.vdot(predicted_test, predicted_test).real + 1e-30
        )
        full_estimate = _symbols_from_channel(
            y[test_block], test_gain * full_channel, pilot_active, scale, data_fraction, n_data
        )
        full_rows.append(_correct_to_reference(full_estimate, reference[test_block]))

    zc = np.asarray(zc_rows)
    full = np.asarray(full_rows)
    reference = reference[:n_blocks]
    reference_power = float(np.mean(np.abs(reference) ** 2)) + 1e-30
    zc_evm = float(np.sqrt(np.mean(np.abs(zc - reference) ** 2) / reference_power))
    full_evm = float(np.sqrt(np.mean(np.abs(full - reference) ** 2) / reference_power))
    return {
        "file": path.name,
        "relative_parent": path.parent.name,
        "modulation": str(pl.get("modulation", "?")),
        "symbol_rate_gbaud": float(pl.get("symbol_rate_actual", 0.0)) * 1e-9,
        "if_ghz": float(pl.get("if_freq", 0.0)) * 1e-9,
        "rx_fs_gsa": fs_rx * 1e-9,
        "blocks": float(n_blocks),
        "stored_evm_db": stored_evm_db,
        "zc_pilot_evm_db": float(20.0 * np.log10(zc_evm + 1e-30)),
        "full_tx_loocv_evm_db": float(20.0 * np.log10(full_evm + 1e-30)),
        "full_tx_improvement_db": float(20.0 * np.log10(zc_evm / max(full_evm, 1e-30))),
    }


def _candidate_paths(data_dir: Path, modulation: str, max_rate_gbaud: float) -> list[Path]:
    paths: list[Path] = []
    for path in sorted(data_dir.rglob("Data*.npz")):
        try:
            with np.load(path, allow_pickle=True) as loaded:
                mod = str(unpack(loaded["tx__modulation"])) if "tx__modulation" in loaded.files else ""
                rate = (
                    float(unpack(loaded["tx__symbol_rate_actual"])) * 1e-9
                    if "tx__symbol_rate_actual" in loaded.files
                    else float("inf")
                )
            if mod.strip().upper() == modulation.strip().upper() and rate <= max_rate_gbaud:
                paths.append(path)
        except Exception:
            continue
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--modulation", default="16QAM")
    parser.add_argument("--max-symbol-rate-gbaud", type=float, default=8.0)
    parser.add_argument("--channel", default="C1")
    parser.add_argument("--out", type=Path, default=DEFAULT_DATA_DIR / "dfts_channel_estimator_comparison.csv")
    args = parser.parse_args()

    rows: list[dict[str, float | str]] = []
    print(f"{'GBaud':>7} {'IF':>5} {'stored':>9} {'ZC':>9} {'full-LOO':>10} {'gain':>8}")
    for path in _candidate_paths(args.data_dir, args.modulation, args.max_symbol_rate_gbaud):
        try:
            row = compare_capture(path, args.channel)
        except Exception as exc:
            print(f"SKIP {path.name}: {exc}")
            continue
        rows.append(row)
        print(
            f"{float(row['symbol_rate_gbaud']):7.2f} "
            f"{float(row['if_ghz']):5.1f} "
            f"{float(row['stored_evm_db']):9.2f} "
            f"{float(row['zc_pilot_evm_db']):9.2f} "
            f"{float(row['full_tx_loocv_evm_db']):10.2f} "
            f"{float(row['full_tx_improvement_db']):+8.2f}"
        )

    if not rows:
        raise SystemExit("No capture could be compared")
    rows.sort(key=lambda row: (float(row["symbol_rate_gbaud"]), float(row["if_ghz"]), str(row["file"])))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Saved: {args.out}")


if __name__ == "__main__":
    main()
