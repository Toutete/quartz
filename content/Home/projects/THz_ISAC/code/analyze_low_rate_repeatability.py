"""Cross-correlate equalized error vectors from repeated low-rate captures.

Only capture pairs with bit-identical TX QAM matrices are compared.  A large
cross-capture error correlation indicates repeatable waveform/link/DSP
distortion; independent DSO/thermal/shot noise should average toward zero.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
from pathlib import Path
from typing import Any

import numpy as np

from isac_gui import DsoPanel
from read_range_data import unpack


DEFAULT_DATA_DIR = Path(__file__).resolve().parent / "data" / "captures"


def _payload(loaded: np.lib.npyio.NpzFile) -> dict[str, Any]:
    return {key.removeprefix("tx__"): unpack(loaded[key]) for key in loaded.files if key.startswith("tx__")}


def recover_equalized(path: Path, channel: str) -> dict[str, Any]:
    with np.load(path, allow_pickle=True) as loaded:
        pl = _payload(loaded)
        raw = np.asarray(loaded[f"rx__{channel}__sig"], dtype=np.float64).reshape(-1)
        fs_rx = float(unpack(loaded[f"rx__{channel}__fs"]))

    panel = object.__new__(DsoPanel)
    panel._log = lambda _message: None
    rx_bb, fs_ref = panel._rx_to_baseband(raw, fs_rx, pl)
    rx_mat, _, _, _, _, _, nps, _, _ = panel._frame_sync_and_reshape(rx_bb, fs_ref, pl)
    estimate, reference, _ = panel._recover_dfts_ofdm_symbols(rx_mat, pl)
    ref_eq, est_eq, _, evm_rms = panel._equalize_reference_candidates(
        estimate,
        reference,
        modulation=str(pl.get("modulation", "16QAM")),
        sc_fde_taps=max(1, int(float(pl.get("sc_fde_taps", 1)))),
        sc_fde_enable=True,
        max_lag=max(4, int(nps)),
    )
    tx_symbols = np.ascontiguousarray(np.asarray(pl.get("tx_sym_matrix", []), dtype=np.complex128))
    return {
        "path": path,
        "modulation": str(pl.get("modulation", "?")),
        "symbol_rate_gbaud": float(pl.get("symbol_rate_actual", 0.0)) * 1e-9,
        "if_ghz": float(pl.get("if_freq", 0.0)) * 1e-9,
        "rx_fs_gsa": fs_rx * 1e-9,
        "dso_scale_mv": str(pl.get("ch1_scale_mv", "")),
        "tx_hash": hashlib.sha256(tx_symbols.tobytes()).hexdigest(),
        "reference": ref_eq,
        "estimate": est_eq,
        "evm_db": float(20.0 * np.log10(evm_rms + 1e-30)),
    }


def compare(first: dict[str, Any], second: dict[str, Any], root: Path) -> dict[str, float | str]:
    n = min(len(first["reference"]), len(first["estimate"]), len(second["reference"]), len(second["estimate"]))
    error_a = np.asarray(first["estimate"][:n]) - np.asarray(first["reference"][:n])
    error_b = np.asarray(second["estimate"][:n]) - np.asarray(second["reference"][:n])
    power_a = float(np.vdot(error_a, error_a).real)
    power_b = float(np.vdot(error_b, error_b).real)
    cross = np.vdot(error_a, error_b)
    correlation = float(np.abs(cross) / np.sqrt(power_a * power_b + 1e-30))
    reference_power = float(np.mean(np.abs(first["reference"][:n]) ** 2))
    shared_error_ratio = float(np.abs(np.mean(error_a * np.conj(error_b))) / max(reference_power, 1e-30))
    return {
        "symbol_rate_gbaud": first["symbol_rate_gbaud"],
        "modulation": first["modulation"],
        "file_a": str(first["path"].relative_to(root)),
        "file_b": str(second["path"].relative_to(root)),
        "if_a_ghz": first["if_ghz"],
        "if_b_ghz": second["if_ghz"],
        "rx_fs_a_gsa": first["rx_fs_gsa"],
        "rx_fs_b_gsa": second["rx_fs_gsa"],
        "evm_a_db": first["evm_db"],
        "evm_b_db": second["evm_db"],
        "symbols_compared": float(n),
        "error_correlation": correlation,
        "shared_error_evm_db": float(10.0 * np.log10(max(shared_error_ratio, 1e-30))),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--modulation", default="16QAM")
    parser.add_argument("--max-symbol-rate-gbaud", type=float, default=8.0)
    parser.add_argument("--channel", default="C1")
    parser.add_argument("--out", type=Path, default=DEFAULT_DATA_DIR / "low_rate_error_repeatability.csv")
    args = parser.parse_args()

    captures: list[dict[str, Any]] = []
    for path in sorted(args.data_dir.rglob("Data*.npz")):
        try:
            with np.load(path, allow_pickle=True) as loaded:
                modulation = str(unpack(loaded["tx__modulation"])) if "tx__modulation" in loaded.files else ""
                symbol_rate_gbaud = (
                    float(unpack(loaded["tx__symbol_rate_actual"])) * 1e-9
                    if "tx__symbol_rate_actual" in loaded.files else float("inf")
                )
            if modulation.strip().upper() != args.modulation.strip().upper():
                continue
            if symbol_rate_gbaud > args.max_symbol_rate_gbaud:
                continue
            capture = recover_equalized(path, args.channel)
        except Exception as exc:
            print(f"SKIP {path.name}: {exc}")
            continue
        captures.append(capture)

    rows: list[dict[str, float | str]] = []
    for first, second in itertools.combinations(captures, 2):
        if first["symbol_rate_gbaud"] != second["symbol_rate_gbaud"] or first["tx_hash"] != second["tx_hash"]:
            continue
        row = compare(first, second, args.data_dir)
        rows.append(row)
        print(
            f"{float(row['symbol_rate_gbaud']):g} GBd  "
            f"rho={float(row['error_correlation']):.3f}  "
            f"shared EVM={float(row['shared_error_evm_db']):.2f} dB"
        )

    if not rows:
        raise SystemExit("No bit-identical repeated capture pairs were found")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Saved: {args.out}")


if __name__ == "__main__":
    main()
