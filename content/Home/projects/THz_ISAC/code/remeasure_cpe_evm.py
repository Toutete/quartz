"""Re-demodulate saved DFT-s-OFDM captures and test extra block CPE removal.

The normal receiver already performs reference-aided phase tracking and FDE.
This script reproduces that path, then applies an additional oracle phase-only
correction (and, separately, a complex-gain correction) once per DFT block.
The oracle results are upper bounds because every transmitted block is known.
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


DEFAULT_DATA_DIR = Path(__file__).resolve().parent / "data" / "captures" / "bandwidth"


def _payload(loaded: np.lib.npyio.NpzFile) -> dict[str, Any]:
    return {key.removeprefix("tx__"): unpack(loaded[key]) for key in loaded.files if key.startswith("tx__")}


def _evm_db(estimate: np.ndarray, reference: np.ndarray) -> float:
    estimate = np.asarray(estimate, dtype=np.complex128)
    reference = np.asarray(reference, dtype=np.complex128)
    return float(20.0 * np.log10(
        np.sqrt(np.mean(np.abs(estimate - reference) ** 2) /
                (np.mean(np.abs(reference) ** 2) + 1e-30)) + 1e-30
    ))


def remeasure(path: Path, channel: str = "C1") -> dict[str, float | str]:
    with np.load(path, allow_pickle=True) as loaded:
        pl = _payload(loaded)
        raw = np.asarray(loaded[f"rx__{channel}__sig"], dtype=np.float64).reshape(-1)
        fs_rx = float(unpack(loaded[f"rx__{channel}__fs"]))
        stored_evm_db = to_float(metric_map(loaded).get("evm_db", {}).get("value", float("nan")))

    panel = object.__new__(DsoPanel)
    panel._log = lambda _message: None
    rx_bb, fs_ref = panel._rx_to_baseband(raw, fs_rx, pl)
    rx_mat, _, _, _, _, _, nps, _, _ = panel._frame_sync_and_reshape(rx_bb, fs_ref, pl)
    estimate, reference, diag = panel._recover_dfts_ofdm_symbols(rx_mat, pl)

    modulation = str(pl.get("modulation", "16QAM"))
    sc_fde_taps = max(1, int(float(pl.get("sc_fde_taps", 1))))
    ref_eq, est_eq, eq_mode, normal_evm_rms = panel._equalize_reference_candidates(
        estimate, reference,
        modulation=modulation,
        sc_fde_taps=sc_fde_taps,
        sc_fde_enable=True,
        max_lag=max(4, int(nps)),
    )
    normal_evm_db = float(20.0 * np.log10(normal_evm_rms + 1e-30))

    n_data = int(pl.get("dft_n_data", 0))
    n_blocks = min(int(diag.get("blocks", 0)), len(ref_eq) // max(n_data, 1), len(est_eq) // max(n_data, 1))
    if n_data <= 0 or n_blocks <= 0:
        raise ValueError(f"{path.name}: no complete equalized DFT blocks")
    ref_rows = np.asarray(ref_eq[:n_blocks * n_data]).reshape(n_blocks, n_data)
    est_rows = np.asarray(est_eq[:n_blocks * n_data]).reshape(n_blocks, n_data)

    phase_rows = np.empty_like(est_rows)
    gain_rows = np.empty_like(est_rows)
    phases: list[float] = []
    for row, (est, ref) in enumerate(zip(est_rows, ref_rows)):
        cross = np.vdot(ref, est)
        phase = float(np.angle(cross))
        phases.append(phase)
        phase_rows[row] = est * np.exp(-1j * phase)
        gain = np.vdot(est, ref) / (np.vdot(est, est).real + 1e-30)
        gain_rows[row] = gain * est

    phase_evm_db = _evm_db(phase_rows, ref_rows)
    gain_evm_db = _evm_db(gain_rows, ref_rows)
    phase_spread_deg = float(np.std(np.unwrap(np.asarray(phases))) * 180.0 / np.pi)
    return {
        "file": path.name,
        "modulation": modulation,
        "symbol_rate_gbaud": float(pl.get("symbol_rate_actual", 0.0)) * 1e-9,
        "blocks": float(n_blocks),
        "stored_evm_db": stored_evm_db,
        "redemod_evm_db": normal_evm_db,
        "block_cpe_evm_db": phase_evm_db,
        "block_cpe_improvement_db": normal_evm_db - phase_evm_db,
        "block_complex_gain_evm_db": gain_evm_db,
        "block_complex_gain_improvement_db": normal_evm_db - gain_evm_db,
        "block_phase_spread_deg": phase_spread_deg,
        "eq_mode": eq_mode,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--modulation", default="16QAM")
    parser.add_argument("--channel", default="C1")
    parser.add_argument("--max-symbol-rate-gbaud", type=float, default=float("inf"))
    parser.add_argument("--out", type=Path, default=DEFAULT_DATA_DIR / "cpe_evm_remeasurement.csv")
    args = parser.parse_args()

    candidates = sorted(args.data_dir.rglob("Data*.npz"))
    paths: list[Path] = []
    for path in candidates:
        try:
            with np.load(path, allow_pickle=True) as loaded:
                modulation = str(unpack(loaded["tx__modulation"])) if "tx__modulation" in loaded.files else ""
                symbol_rate = (
                    float(unpack(loaded["tx__symbol_rate_actual"])) * 1e-9
                    if "tx__symbol_rate_actual" in loaded.files else float("nan")
                )
            if modulation.strip().upper() != args.modulation.strip().upper():
                continue
            if not math.isfinite(symbol_rate) or symbol_rate > args.max_symbol_rate_gbaud:
                continue
            paths.append(path)
        except Exception:
            continue
    rows: list[dict[str, float | str]] = []
    print(f"{'GBaud':>7} {'stored':>9} {'redemod':>9} {'+CPE':>9} {'gain':>7} {'+gain':>9}")
    for path in paths:
        try:
            row = remeasure(path, channel=args.channel)
        except Exception as exc:
            print(f"SKIP {path.name}: {exc}")
            continue
        rows.append(row)
        print(
            f"{float(row['symbol_rate_gbaud']):7.2f} "
            f"{float(row['stored_evm_db']):9.2f} "
            f"{float(row['redemod_evm_db']):9.2f} "
            f"{float(row['block_cpe_evm_db']):9.2f} "
            f"{float(row['block_cpe_improvement_db']):7.3f} "
            f"{float(row['block_complex_gain_improvement_db']):9.3f}"
        )

    if not rows:
        raise SystemExit("No capture could be remeasured")
    rows.sort(key=lambda row: float(row["symbol_rate_gbaud"]))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Saved: {args.out}")


if __name__ == "__main__":
    main()
