"""Plot the EVM / range-resolution trade-off figure vs symbol rate.

Default data source is the hardcoded measured EVM table (photocurrent 7 mA,
16QAM / 32QAM, fsym=2..20 GBaud) transcribed from the lab spreadsheet.
Produces a 2-panel IEEE-Transactions-style figure and, by default, opens an
interactive GUI:

  (a) Measured EVM (dB) vs symbol rate, one curve per modulation, an
      AWGN-only reference, and an effective theoretical EVM obtained by
      adding AWGN and DSO/ADC quantization noise in the power domain, followed
      by the measured symbol-rate-dependent effective SSBI penalty.
  (b) Range resolution c/(2B) (mm) vs symbol rate -- theory only.

Two other data sources remain available for cross-checking against raw
captures: --source npz (data/captures/bandwidth/Data_fIF*_fsym*.npz, which
also carries a Welch-PSD spectral SNR) and --source excel (the exp_data.xlsx
back-to-back "direct cable" sweep).

Examples
--------
python plot_evm_tradeoff_figure.py --out data/fig3_evm_tradeoff.png
python plot_evm_tradeoff_figure.py --source npz --out data/fig3_from_npz.png
python plot_evm_tradeoff_figure.py --no-show  # save without opening the GUI
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Any

import numpy as np

from read_range_data import metric_map, to_float, unpack

C = 3e8


def load_measured_table() -> dict[str, dict[str, np.ndarray]]:
    """EVM (dB) vs symbol rate (GBaud), photocurrent 7 mA, transcribed as-is
    from the lab spreadsheet (DFT-s-OFDM, rho known per FEC-threshold note)."""
    data = {
        "16QAM": {2: -25.22, 4: -23.22, 8: -20.18, 10: -19.66, 12: -18.49, 15: -17.42, 17: -16.9, 20: -15.94},
        "32QAM": {2: -25.16, 4: -23.37, 8: -20.06, 10: -19.8, 12: -18.71, 15: -17.49, 17: -16.5, 20: -15.77},
    }
    series: dict[str, dict[str, np.ndarray]] = {}
    for label, rows in data.items():
        sr = np.asarray(sorted(rows.keys()), dtype=float)
        evm = np.asarray([rows[k] for k in sorted(rows.keys())], dtype=float)
        series[label] = {"symbol_rate_gbaud": sr, "evm_db": evm}
    return series


def default_npz_dir() -> Path:
    return Path(__file__).resolve().parent / "data" / "captures" / "bandwidth"


def default_excel_path() -> Path:
    return Path(__file__).resolve().parent.parent / "exp_data.xlsx"


def get_npz_scalar(loaded: np.lib.npyio.NpzFile, key: str, default: Any = "") -> Any:
    if key not in loaded.files:
        return default
    try:
        return unpack(loaded[key])
    except Exception:
        return default


def load_capture_folder(npz_dir: Path) -> dict[str, dict[str, np.ndarray]]:
    """Read all Data_fIF*_fsym*.npz captures in npz_dir, grouped by modulation.

    Each capture stores one EVM value (communication demod result) plus the
    TX symbol rate, modulation, waveform type and launch power as scalars.
    """
    paths = sorted(npz_dir.glob("Data_fIF*_fsym*.npz"))
    if not paths:
        raise ValueError(f"No Data_fIF*_fsym*.npz files found in {npz_dir}")

    by_mod: dict[str, list[tuple[float, float, float, float]]] = {}
    for path in paths:
        with np.load(path, allow_pickle=True) as loaded:
            metrics = metric_map(loaded)
            evm_db = to_float(metrics.get("evm_db", {}).get("value", float("nan")))
            comm_snr_db = to_float(metrics.get("snr_com_db", {}).get("value", float("nan")))
            baud_hz = to_float(get_npz_scalar(loaded, "tx__symbol_rate_actual", float("nan")))
            mod = str(get_npz_scalar(loaded, "tx__modulation", "?"))
            power_dbm = to_float(get_npz_scalar(loaded, "tx__awg_ch1_power_dbm", float("nan")))
        if not (math.isfinite(evm_db) and math.isfinite(baud_hz) and baud_hz > 0):
            continue
        by_mod.setdefault(mod, []).append((baud_hz * 1e-9, evm_db, power_dbm, comm_snr_db))

    series: dict[str, dict[str, np.ndarray]] = {}
    for mod, rows in by_mod.items():
        rows.sort(key=lambda r: r[0])
        arr = np.asarray(rows, dtype=float)
        series[mod] = {
            "symbol_rate_gbaud": arr[:, 0],
            "evm_db": arr[:, 1],
            "power_dbm": arr[:, 2],
            "comm_snr_db": arr[:, 3],
        }
    return series


def load_symbol_rate_table_excel(excel_path: Path, sheet: str) -> dict[str, dict[str, np.ndarray]]:
    """Parse the "Symbol rate (GB)" sub-table from the "direct cable" sheet.

    The sheet mixes multiple small tables; this locates the header row
    whose cells contain "Symbol rate" and "DFT-s-OFDM"/"LFM-QAM", then reads
    numeric rows below it until the symbol-rate column goes blank.
    """
    import openpyxl

    wb = openpyxl.load_workbook(excel_path, data_only=True)
    ws = wb[sheet]
    rows = list(ws.iter_rows(values_only=True))

    header_row_idx = None
    sr_col = dfts_col = lfm_col = None
    for i, row in enumerate(rows):
        for j, cell in enumerate(row):
            if isinstance(cell, str) and "symbol rate" in cell.lower():
                header_row_idx = i
                sr_col = j
        if header_row_idx == i:
            for j, cell in enumerate(row):
                if not isinstance(cell, str):
                    continue
                low = cell.lower()
                if "dft-s-ofdm" in low or "dfts-ofdm" in low or "dft-s ofdm" in low:
                    dfts_col = j
                elif "lfm" in low:
                    lfm_col = j
            break

    if header_row_idx is None or sr_col is None:
        raise ValueError(f'No "Symbol rate" header found on sheet "{sheet}" of {excel_path}')

    symbol_rate: list[float] = []
    evm_dfts: list[float] = []
    evm_lfm: list[float] = []
    for row in rows[header_row_idx + 1:]:
        sr_val = row[sr_col] if sr_col < len(row) else None
        if sr_val is None or not isinstance(sr_val, (int, float)):
            break
        symbol_rate.append(float(sr_val))
        evm_dfts.append(_to_float(row[dfts_col]) if dfts_col is not None and dfts_col < len(row) else float("nan"))
        evm_lfm.append(_to_float(row[lfm_col]) if lfm_col is not None and lfm_col < len(row) else float("nan"))

    sr = np.asarray(symbol_rate, dtype=float)
    series: dict[str, dict[str, np.ndarray]] = {}
    for label, evm in (("DFT-s-OFDM ($\\rho$=0.2)", evm_dfts), ("LFM-QAM", evm_lfm)):
        evm_arr = np.asarray(evm, dtype=float)
        valid = np.isfinite(sr) & np.isfinite(evm_arr)
        if np.any(valid):
            series[label] = {"symbol_rate_gbaud": sr[valid], "evm_db": evm_arr[valid]}
    return series


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return float("nan")


def resolution_mm(baud_gbaud: np.ndarray) -> np.ndarray:
    b_hz = np.asarray(baud_gbaud, dtype=float) * 1e9
    return C / (2.0 * b_hz) * 1e3


def thermal_only_sinr_db(baud_gbaud: np.ndarray, anchor_baud: float, anchor_sinr_db: float) -> np.ndarray:
    b = np.asarray(baud_gbaud, dtype=float)
    return anchor_sinr_db - 10.0 * np.log10(b / anchor_baud)


def ssbi_penalty_db(
    baud_gbaud: np.ndarray,
    penalty_at_reference_db: float,
    reference_gbaud: float,
) -> np.ndarray:
    """Smooth monotonic effective-SSBI penalty measured from the captures.

    The normalized anchors follow the residual impairment in the measured EVM
    table after removing the default AWGN+DSO contribution.  They are also
    consistent with the increasing spectral-SNR/EVM gap reported in
    05_symbol_rate_evm_ssbi_tradeoff.md.  PCHIP avoids the artificial hard
    overlap kink of the previous model while preserving monotonicity.
    """
    from scipy.interpolate import PchipInterpolator

    b = np.asarray(baud_gbaud, dtype=float)
    rate_fraction = np.array([0.0, 0.10, 0.20, 0.40, 0.60, 0.75, 0.85, 1.0], dtype=float)
    penalty_fraction = np.array(
        [0.0, 0.0, 0.739 / 3.438, 2.168 / 3.438, 2.447 / 3.438,
         2.849 / 3.438, 3.171 / 3.438, 1.0],
        dtype=float,
    )
    interpolator = PchipInterpolator(rate_fraction, penalty_fraction, extrapolate=False)
    normalized_rate = np.clip(b / reference_gbaud, 0.0, 1.0)
    return penalty_at_reference_db * np.asarray(interpolator(normalized_rate), dtype=float)


def effective_sinr_db(
    baud_gbaud: np.ndarray,
    reference_gbaud: float,
    awgn_snr_at_reference_db: float,
    dso_snr_db: float,
    ssbi_penalty_at_max_db: float,
    max_gbaud: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return total SINR, AWGN SNR and effective SSBI penalty in dB.

    DSO/ADC quantization noise is represented by a bandwidth-independent SNR
    floor.  AWGN and DSO powers are summed first; the measured SSBI penalty is
    then applied to that baseline SINR.
    """
    awgn_db = thermal_only_sinr_db(baud_gbaud, reference_gbaud, awgn_snr_at_reference_db)
    baseline_inverse_sinr = (
        np.power(10.0, -awgn_db / 10.0)
        + 10.0 ** (-dso_snr_db / 10.0)
    )
    baseline_sinr_db = -10.0 * np.log10(baseline_inverse_sinr)
    penalty_db = ssbi_penalty_db(baud_gbaud, ssbi_penalty_at_max_db, max_gbaud)
    return baseline_sinr_db - penalty_db, awgn_db, penalty_db


def make_figure(series: dict[str, dict[str, np.ndarray]], args: argparse.Namespace) -> None:
    import matplotlib

    if not args.show:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import NullFormatter, ScalarFormatter

    plt.rcParams.update({
        "font.family": "Times New Roman",
        "mathtext.fontset": "stix",
        "axes.labelsize": 9,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "legend.fontsize": 7.5,
        "xtick.direction": "in",
        "ytick.direction": "in",
        "xtick.top": True,
        "ytick.right": True,
        "axes.linewidth": 0.8,
    })

    if not series:
        raise ValueError("No measured (symbol rate, EVM) series to plot.")

    # Pure, unambiguous red/blue per modulation; filled vs. open marker is the
    # second (color-independent) code, so curves are legible in grayscale too.
    color_cycle = ["red", "blue", "#0f766e", "#b45309"]
    labels = sorted(series.keys())
    colors = {label: color_cycle[i % len(color_cycle)] for i, label in enumerate(labels)}
    open_marker = {label: (i % 2 == 1) for i, label in enumerate(labels)}

    all_sr = np.concatenate([series[label]["symbol_rate_gbaud"] for label in labels])

    x_lo = min(0.8, all_sr.min() * 0.8)
    model_max_gbaud = max(args.xmax_gbaud, float(all_sr.max()))
    x_hi = model_max_gbaud * 1.05
    x_theory = np.geomspace(x_lo, x_hi, 200)

    interactive = bool(args.show)
    figure_height = 4.35 if interactive else 3.0
    fig, (ax_main, ax_res) = plt.subplots(1, 2, figsize=(7.16, figure_height), dpi=args.dpi)

    def marker_kwargs(label: str) -> dict[str, Any]:
        color = colors[label]
        if open_marker[label]:
            return {"marker": "o", "markerfacecolor": "none", "markeredgecolor": color}
        return {"marker": "o", "markerfacecolor": color, "markeredgecolor": color}

    for label in labels:
        sr_v = series[label]["symbol_rate_gbaud"]
        evm_v = series[label]["evm_db"]
        measured_line, = ax_main.plot(
            sr_v, evm_v, "-", color=colors[label], lw=1.4, ms=6, mew=1.3,
            label=f"Measured EVM ({label})", picker=6, **marker_kwargs(label)
        )
        measured_line._cursor_label = f"Measured {label}"  # type: ignore[attr-defined]

    reference_gbaud = float(args.snr_reference_gbaud)

    def calculate_theory(snr_db: float, dso_snr_db: float, ssbi_penalty_db_value: float) -> tuple[np.ndarray, np.ndarray]:
        total_db, awgn_db, _ = effective_sinr_db(
            x_theory,
            reference_gbaud=reference_gbaud,
            awgn_snr_at_reference_db=snr_db,
            dso_snr_db=dso_snr_db,
            ssbi_penalty_at_max_db=ssbi_penalty_db_value,
            max_gbaud=model_max_gbaud,
        )
        return -total_db, -awgn_db

    theory_evm_db, awgn_evm_db = calculate_theory(args.snr_db, args.dso_snr_db, args.ssbi_penalty_db)
    awgn_line, = ax_main.plot(
        x_theory, awgn_evm_db, ":", color="0.45", lw=1.2,
        label="AWGN only", picker=5,
    )
    total_line, = ax_main.plot(
        x_theory, theory_evm_db, "--", color="black", lw=1.7,
        label="Theory: AWGN + DSO + effective SSBI", picker=5,
    )
    awgn_line._cursor_label = "AWGN only"  # type: ignore[attr-defined]
    total_line._cursor_label = "AWGN + DSO + effective SSBI"  # type: ignore[attr-defined]

    ax_main.set_ylabel("EVM (dB)")

    resolution_line, = ax_res.plot(
        x_theory, resolution_mm(x_theory), "-", color="blue", lw=1.4,
        label="$c/2B$ (theory)", picker=5,
    )
    resolution_line._cursor_label = "Range resolution"  # type: ignore[attr-defined]
    ax_res.set_ylabel("Range resolution (mm)")
    ax_res.set_yscale("log")

    tick_candidates = sorted(set(np.round(all_sr, 6).tolist()) | {1.0, 2.0, 4.0, 8.0, 10.0, 20.0})
    tick_candidates = [t for t in tick_candidates if x_lo * 0.99 <= t <= x_hi * 1.01]
    for ax in (ax_main, ax_res):
        ax.set_xscale("log")
        ax.set_xlim(x_lo, x_hi)
        ax.set_xticks(tick_candidates)
        ax.xaxis.set_major_formatter(ScalarFormatter())
        ax.xaxis.set_minor_formatter(NullFormatter())
        ax.set_xlabel("Symbol rate (GBaud)")
        ax.grid(True, alpha=0.3, which="major")
        ax.legend(loc="best", frameon=False)

    # Native Matplotlib data cursor: click any marker or curve to read its
    # nearest value.  This avoids an extra mplcursors dependency.
    cursor_annotations: dict[Any, Any] = {}

    def on_pick(event: Any) -> None:
        line = event.artist
        if not hasattr(line, "get_xdata") or not len(event.ind):
            return
        mouse_x = event.mouseevent.xdata
        indices = np.asarray(event.ind, dtype=int)
        xdata = np.asarray(line.get_xdata(), dtype=float)
        ydata = np.asarray(line.get_ydata(), dtype=float)
        idx = int(indices[0] if mouse_x is None else indices[np.argmin(np.abs(xdata[indices] - mouse_x))])
        old = cursor_annotations.pop(line.axes, None)
        if old is not None:
            old.remove()
        label = getattr(line, "_cursor_label", line.get_label())
        y_unit = "mm" if line.axes is ax_res else "dB"
        annotation = line.axes.annotate(
            f"{label}\n{xdata[idx]:.3g} GBaud, {ydata[idx]:.3g} {y_unit}",
            xy=(xdata[idx], ydata[idx]), xytext=(9, 12), textcoords="offset points",
            fontsize=8, bbox={"boxstyle": "round,pad=0.3", "fc": "white", "alpha": 0.92},
            arrowprops={"arrowstyle": "->", "lw": 0.8},
        )
        cursor_annotations[line.axes] = annotation
        fig.canvas.draw_idle()

    fig.canvas.mpl_connect("pick_event", on_pick)

    if interactive:
        from matplotlib.widgets import Button, Slider

        fig.subplots_adjust(bottom=0.31, left=0.09, right=0.98, top=0.96, wspace=0.30)
        slider_left, slider_width = 0.14, 0.55
        snr_ax = fig.add_axes((slider_left, 0.18, slider_width, 0.035))
        dso_ax = fig.add_axes((slider_left, 0.125, slider_width, 0.035))
        ssbi_ax = fig.add_axes((slider_left, 0.07, slider_width, 0.035))
        snr_slider = Slider(snr_ax, f"AWGN SNR @ {reference_gbaud:g} GBd (dB)", 15.0, 45.0,
                            valinit=args.snr_db, valstep=0.1)
        dso_slider = Slider(dso_ax, "DSO/ADC SNR floor (dB)", 15.0, 50.0,
                            valinit=args.dso_snr_db, valstep=0.1)
        ssbi_slider = Slider(ssbi_ax, f"SSBI penalty @ {model_max_gbaud:g} GBd (dB)", 0.0, 12.0,
                             valinit=args.ssbi_penalty_db, valstep=0.1)

        def update_theory(_value: float) -> None:
            total_y, awgn_y = calculate_theory(snr_slider.val, dso_slider.val, ssbi_slider.val)
            total_line.set_ydata(total_y)
            awgn_line.set_ydata(awgn_y)
            for annotation in cursor_annotations.values():
                annotation.remove()
            cursor_annotations.clear()
            ax_main.relim()
            ax_main.autoscale_view(scalex=False, scaley=True)
            fig.canvas.draw_idle()

        for slider in (snr_slider, dso_slider, ssbi_slider):
            slider.on_changed(update_theory)

        reset_ax = fig.add_axes((0.76, 0.135, 0.09, 0.055))
        save_ax = fig.add_axes((0.87, 0.135, 0.09, 0.055))
        reset_button = Button(reset_ax, "Reset")
        save_button = Button(save_ax, "Save")

        def reset(_event: Any) -> None:
            snr_slider.reset()
            dso_slider.reset()
            ssbi_slider.reset()

        def save_current(_event: Any) -> None:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(args.out, bbox_inches="tight")
            print(f"Saved current GUI figure: {args.out}")

        reset_button.on_clicked(reset)
        save_button.on_clicked(save_current)
        fig.text(0.755, 0.075, "Click a marker/curve\nto read its value", fontsize=8, color="0.25")
    else:
        fig.tight_layout()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out, bbox_inches="tight")
    print(f"Saved: {args.out}")
    if args.show:
        plt.show()
    else:
        plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=("table", "npz", "excel"), default="table", help="Data source for measured EVM")
    parser.add_argument("--npz-dir", type=Path, default=default_npz_dir(), help="Folder with Data_fIF*_fsym*.npz captures")
    parser.add_argument("--excel", type=Path, default=default_excel_path(), help="Path to exp_data.xlsx")
    parser.add_argument("--sheet", type=str, default="direct cable", help="Sheet name containing the symbol-rate sweep")
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "data" / "fig3_evm_tradeoff.png")
    parser.add_argument("--xmax-gbaud", type=float, dest="xmax_gbaud", default=20.0, help="Upper x-limit for the theory curves")
    parser.add_argument("--snr-db", type=float, default=30.1,
                        help="AWGN-only SNR at --snr-reference-gbaud (default: measured 2-GBaud spectral SNR)")
    parser.add_argument("--snr-reference-gbaud", type=float, default=2.0,
                        help="Reference symbol rate for --snr-db")
    parser.add_argument("--dso-snr-db", type=float, default=27.0,
                        help="Bandwidth-independent DSO/ADC quantization-noise SNR floor")
    parser.add_argument("--ssbi-penalty-db", "--ssbi-sir-db", dest="ssbi_penalty_db",
                        type=float, default=3.44,
                        help="effective measured SSBI penalty at --xmax-gbaud")
    parser.add_argument("--dpi", type=int, default=300)
    display_group = parser.add_mutually_exclusive_group()
    display_group.add_argument("--show", dest="show", action="store_true",
                               help="Open the interactive GUI (default)")
    display_group.add_argument("--no-show", "--save-only", dest="show", action="store_false",
                               help="Save the static publication figure without opening a GUI")
    parser.set_defaults(show=True)
    args = parser.parse_args()

    if args.snr_reference_gbaud <= 0 or args.xmax_gbaud <= 0:
        parser.error("symbol-rate parameters must be positive")
    if args.ssbi_penalty_db < 0:
        parser.error("--ssbi-penalty-db must be non-negative")

    if args.source == "table":
        series = load_measured_table()
    elif args.source == "npz":
        series = load_capture_folder(args.npz_dir)
    else:
        series = load_symbol_rate_table_excel(args.excel, args.sheet)
    make_figure(series, args)


if __name__ == "__main__":
    main()
