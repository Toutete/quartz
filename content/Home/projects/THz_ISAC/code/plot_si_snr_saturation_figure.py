"""GUI for SI-assisted sensing SNR range extrapolation.

This script builds the paper-style "SI on/off + saturation limit" figure.
Measured points are loaded from NPZ files saved by the DSO "Save" or
"Save Range" buttons.  The SI-on curve is calibrated from the loaded sensing
SNR points by a fixed 1/R^2 law.  The SI-off curve is the direct-detection
1/R^4 reference, and the maximum curve is the best SI boost subject to an
LNA/ADC saturation boost and an SI-driven SSBI floor.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from read_range_data import metric_map, to_float, unpack


APP_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = APP_DIR / "data" / "range"


@dataclass
class MeasurementPoint:
    path: Path
    label: str
    channel: str
    range_m: float
    snr_sens_db: float
    rho: float
    pslr_db: float


def finite_float(value: Any, default: float = float("nan")) -> float:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except Exception:
        return default


def npz_first_float(loaded: np.lib.npyio.NpzFile, key: str, default: float = float("nan")) -> float:
    if key not in loaded.files:
        return default
    try:
        arr = np.asarray(loaded[key]).reshape(-1)
        for item in arr:
            value = finite_float(unpack(item))
            if math.isfinite(value):
                return value
    except Exception:
        pass
    return default


def metric_float(metrics: dict[str, dict[str, Any]], *keys: str) -> float:
    for key in keys:
        if key not in metrics:
            continue
        value = finite_float(metrics[key].get("value", float("nan")))
        if math.isfinite(value):
            return value
    return float("nan")


def channel_index(loaded: np.lib.npyio.NpzFile, channel: str) -> int:
    if "range_summary_channels" not in loaded.files:
        return -1
    want = channel.strip().upper()
    channels = [str(unpack(x)).strip().upper() for x in np.asarray(loaded["range_summary_channels"]).reshape(-1)]
    if want in channels:
        return channels.index(want)
    return 0 if channels else -1


def range_summary_float(
    loaded: np.lib.npyio.NpzFile,
    channel: str,
    *keys: str,
) -> float:
    idx = channel_index(loaded, channel)
    if idx < 0:
        return float("nan")
    for key in keys:
        if key not in loaded.files:
            continue
        arr = np.asarray(loaded[key]).reshape(-1)
        if idx < len(arr):
            value = finite_float(unpack(arr[idx]))
            if math.isfinite(value):
                return value
    return float("nan")


def extract_measurement(path: Path, channel: str = "C2") -> MeasurementPoint:
    path = Path(path).expanduser().resolve()
    ch = channel.strip().upper() or "C2"
    with np.load(path, allow_pickle=True) as loaded:
        metrics = metric_map(loaded)
        ch_l = ch.lower()

        range_m = range_summary_float(
            loaded,
            ch,
            "range_summary_display_m",
            "range_summary_peak_m",
            "range_summary_matched_filter_peak_m",
        )
        if not math.isfinite(range_m):
            range_m = metric_float(metrics, f"range_peak_m_{ch_l}", "range_peak_m")

        snr_sens_db = metric_float(
            metrics,
            f"snr_rad_db_{ch_l}",
            "snr_rad_db",
            f"snr_com_db_{ch_l}",
        )

        rho = metric_float(metrics, "amplitude_ratio_rho")
        if not math.isfinite(rho):
            rho = npz_first_float(loaded, "tx__amplitude_ratio_rho")
        if not math.isfinite(rho):
            rho = npz_first_float(loaded, "dsp__pilot_rho")

        pslr_db = range_summary_float(loaded, ch, "range_summary_pslr_db")

    if not math.isfinite(range_m) or range_m <= 0:
        raise ValueError(f"{path.name}: could not extract a positive {ch} range.")
    if not math.isfinite(snr_sens_db):
        raise ValueError(f"{path.name}: could not extract sensing SNR.")

    return MeasurementPoint(
        path=path,
        label=path.stem,
        channel=ch,
        range_m=float(range_m),
        snr_sens_db=float(snr_sens_db),
        rho=float(rho) if math.isfinite(rho) else float("nan"),
        pslr_db=float(pslr_db) if math.isfinite(pslr_db) else float("nan"),
    )


def db_to_lin(db: np.ndarray | float) -> np.ndarray | float:
    return 10.0 ** (np.asarray(db) / 10.0)


def lin_to_db(x: np.ndarray | float) -> np.ndarray | float:
    return 10.0 * np.log10(np.maximum(np.asarray(x, dtype=float), 1e-300))


def make_curves(
    ranges_m: np.ndarray,
    points: list[MeasurementPoint],
    fit_from_points: bool,
    anchor_range_m: float,
    anchor_snr_db: float,
    si_off_penalty_db: float,
    sat_boost_db: float,
    ssbi_nominal_db: float,
    boost_points: int,
) -> dict[str, np.ndarray | float | str]:
    r = np.maximum(np.asarray(ranges_m, dtype=float), 1e-12)
    valid = [
        p for p in points
        if math.isfinite(p.range_m) and p.range_m > 0 and math.isfinite(p.snr_sens_db)
    ]

    if fit_from_points and valid:
        intercepts = np.asarray([p.snr_sens_db + 20.0 * math.log10(p.range_m) for p in valid])
        intercept_db = float(np.nanmedian(intercepts))
        source = f"fit from {len(valid)} point(s)"
    else:
        ar = max(anchor_range_m, 1e-12)
        intercept_db = float(anchor_snr_db + 20.0 * math.log10(ar))
        source = "manual anchor"

    snr_on_db = intercept_db - 20.0 * np.log10(r)
    ar = max(anchor_range_m, 1e-12)
    snr_on_anchor_db = intercept_db - 20.0 * math.log10(ar)
    si_off_anchor_db = snr_on_anchor_db - si_off_penalty_db
    snr_off_db = si_off_anchor_db - 40.0 * np.log10(r / ar)

    g_max = max(10.0 ** (sat_boost_db / 10.0), 1.0)
    n_boost = max(8, min(int(boost_points), 2000))
    boosts = np.geomspace(1.0, g_max, n_boost)
    ssbi0 = max(10.0 ** (ssbi_nominal_db / 10.0), 0.0)
    snr_on_lin = db_to_lin(snr_on_db)
    # The measured nominal curve already includes the present impairment state.
    # Extra SI boost improves the homodyne term linearly, while the additional
    # SI-induced SSBI floor grows as alpha^4.
    extra_ssbi = ssbi0 * np.maximum(boosts ** 4 - 1.0, 0.0)
    sinr_boost = snr_on_lin[:, None] * boosts[None, :] / (1.0 + extra_ssbi[None, :])
    snr_max_db = lin_to_db(np.nanmax(sinr_boost, axis=1))
    opt_boost_idx = np.nanargmax(sinr_boost, axis=1)
    opt_boost_db = lin_to_db(boosts[opt_boost_idx])

    return {
        "si_on_db": snr_on_db,
        "si_off_db": snr_off_db,
        "max_db": snr_max_db,
        "opt_boost_db": opt_boost_db,
        "intercept_db": intercept_db,
        "source": source,
    }


def launch_gui() -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    import matplotlib as mpl
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
    from matplotlib.figure import Figure
    from matplotlib.ticker import LogLocator, MultipleLocator, ScalarFormatter

    mpl.rcParams.update({
        "font.family": "Times New Roman",
        "mathtext.fontset": "stix",
        "axes.labelsize": 9,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "legend.fontsize": 8,
        "axes.linewidth": 0.8,
    })

    root = tk.Tk()
    root.title("SI-Assisted Sensing SNR Figure")
    root.geometry("1160x720")

    points: list[MeasurementPoint] = []

    vars_: dict[str, tk.StringVar] = {
        "channel": tk.StringVar(value="C2"),
        "r_min": tk.StringVar(value="0.2"),
        "r_max": tk.StringVar(value="100"),
        "n_points": tk.StringVar(value="500"),
        "anchor_range": tk.StringVar(value="1.0"),
        "anchor_snr": tk.StringVar(value="10.0"),
        "rho": tk.StringVar(value="0.20"),
        "si_off_penalty": tk.StringVar(value="25"),
        "sat_boost": tk.StringVar(value="30"),
        "ssbi_nominal": tk.StringVar(value="-35"),
        "boost_points": tk.StringVar(value="300"),
        "y_min": tk.StringVar(value="-40"),
        "y_max": tk.StringVar(value="50"),
        "out": tk.StringVar(value=str(DEFAULT_DATA_DIR / "si_on_off_saturation.png")),
    }
    fit_var = tk.BooleanVar(value=True)
    xscale_var = tk.StringVar(value="log")
    status_var = tk.StringVar(value="Load saved NPZ files to overlay measured points.")

    root.columnconfigure(1, weight=1)
    root.rowconfigure(0, weight=1)

    left = ttk.Frame(root, padding=10)
    left.grid(row=0, column=0, sticky="ns")
    right = ttk.Frame(root, padding=(0, 10, 10, 10))
    right.grid(row=0, column=1, sticky="nsew")
    right.columnconfigure(0, weight=1)
    right.rowconfigure(0, weight=1)

    ctrl = ttk.LabelFrame(left, text="Model / Figure Controls", padding=8)
    ctrl.grid(row=0, column=0, sticky="new")

    def add_entry(row: int, key: str, label: str, width: int = 11) -> None:
        ttk.Label(ctrl, text=label).grid(row=row, column=0, sticky="w", pady=2)
        ttk.Entry(ctrl, textvariable=vars_[key], width=width).grid(row=row, column=1, sticky="ew", pady=2)

    add_entry(0, "channel", "Channel")
    add_entry(1, "r_min", "Range min [m]")
    add_entry(2, "r_max", "Range max [m]")
    add_entry(3, "n_points", "Curve points")
    add_entry(4, "anchor_range", "Anchor R [m]")
    add_entry(5, "anchor_snr", "Anchor SNR [dB]")
    add_entry(6, "rho", "rho")
    add_entry(7, "si_off_penalty", "SI-off penalty [dB]")
    add_entry(8, "sat_boost", "Saturation boost [dB]")
    add_entry(9, "ssbi_nominal", "SSBI/N0 at nominal [dB]")
    add_entry(10, "boost_points", "SI boost samples")
    add_entry(11, "y_min", "Y min [dB]")
    add_entry(12, "y_max", "Y max [dB]")

    ttk.Checkbutton(ctrl, text="Fit SI-on from loaded points", variable=fit_var).grid(
        row=13, column=0, columnspan=2, sticky="w", pady=(6, 2)
    )
    ttk.Label(ctrl, text="X scale").grid(row=14, column=0, sticky="w", pady=2)
    ttk.Combobox(ctrl, textvariable=xscale_var, values=("log", "linear"), width=9, state="readonly").grid(
        row=14, column=1, sticky="ew", pady=2
    )

    btns = ttk.Frame(ctrl)
    btns.grid(row=15, column=0, columnspan=2, sticky="ew", pady=(8, 0))
    btns.columnconfigure((0, 1), weight=1)

    point_box = tk.Listbox(left, height=9, width=44)
    point_box.grid(row=1, column=0, sticky="new", pady=(8, 0))

    fig = Figure(figsize=(7.2, 4.9), dpi=110)
    ax = fig.add_subplot(111)
    canvas = FigureCanvasTkAgg(fig, master=right)
    canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
    toolbar = NavigationToolbar2Tk(canvas, right, pack_toolbar=False)
    toolbar.grid(row=1, column=0, sticky="ew")

    out_frame = ttk.Frame(left)
    out_frame.grid(row=2, column=0, sticky="ew", pady=(8, 0))
    out_frame.columnconfigure(0, weight=1)
    ttk.Entry(out_frame, textvariable=vars_["out"]).grid(row=0, column=0, sticky="ew")

    def get_float(key: str, default: float) -> float:
        value = finite_float(vars_[key].get(), default)
        return value if math.isfinite(value) else default

    def get_int(key: str, default: int) -> int:
        try:
            return int(float(vars_[key].get()))
        except Exception:
            return default

    def refresh_list() -> None:
        point_box.delete(0, tk.END)
        for idx, p in enumerate(points, start=1):
            rho_text = f", rho={p.rho:.2f}" if math.isfinite(p.rho) else ""
            point_box.insert(
                tk.END,
                f"{idx}. {p.label[:23]} | R={p.range_m:.3f} m | SNR={p.snr_sens_db:.2f} dB{rho_text}",
            )

    def ranges_axis() -> np.ndarray:
        r_min = max(get_float("r_min", 0.2), 1e-6)
        r_max = max(get_float("r_max", 100.0), r_min * 1.01)
        n_points = max(32, min(get_int("n_points", 500), 10000))
        if xscale_var.get() == "log":
            return np.geomspace(r_min, r_max, n_points)
        return np.linspace(r_min, r_max, n_points)

    def redraw() -> None:
        try:
            r = ranges_axis()
            curves = make_curves(
                r,
                points,
                fit_var.get(),
                get_float("anchor_range", 1.0),
                get_float("anchor_snr", 10.0),
                get_float("si_off_penalty", 25.0),
                get_float("sat_boost", 30.0),
                get_float("ssbi_nominal", -35.0),
                get_int("boost_points", 300),
            )

            ax.clear()
            ax.plot(r, curves["si_on_db"], color="#1d4ed8", linewidth=1.6, label="SI on (homodyne, 1/R^2)")
            ax.plot(r, curves["si_off_db"], color="#64748b", linewidth=1.35, linestyle="--", label="SI off (1/R^4)")
            ax.plot(r, curves["max_db"], color="#dc2626", linewidth=1.6, linestyle="-.", label="Maximum (sat./SSBI-limited)")

            valid = [p for p in points if math.isfinite(p.range_m) and math.isfinite(p.snr_sens_db)]
            if valid:
                ax.scatter(
                    [p.range_m for p in valid],
                    [p.snr_sens_db for p in valid],
                    s=36,
                    marker="o",
                    facecolor="white",
                    edgecolor="#111827",
                    linewidth=1.0,
                    zorder=8,
                    label="Measured",
                )
                for p in valid:
                    ax.annotate(
                        f"{p.range_m:.2f} m",
                        (p.range_m, p.snr_sens_db),
                        xytext=(4, 5),
                        textcoords="offset points",
                        fontsize=7,
                        color="#111827",
                    )

            if xscale_var.get() == "log":
                ax.set_xscale("log")
                ax.xaxis.set_major_locator(LogLocator(base=10.0, numticks=8))
                ax.xaxis.set_minor_locator(LogLocator(base=10.0, subs=np.arange(2, 10) * 0.1, numticks=80))
            else:
                step = (r[-1] - r[0]) / 5.0
                if step > 0:
                    ax.xaxis.set_major_locator(MultipleLocator(step))
            ax.xaxis.set_major_formatter(ScalarFormatter())

            y_min = get_float("y_min", -40.0)
            y_max = get_float("y_max", 50.0)
            if y_max <= y_min:
                y_max = y_min + 10.0
            ax.set_ylim(y_min, y_max)
            ax.set_xlim(float(r[0]), float(r[-1]))
            ax.set_xlabel("Range, R (m)")
            ax.set_ylabel("Sensing SNR (dB)")
            ax.grid(True, which="major", color="#cbd5e1", linewidth=0.55, alpha=0.85)
            ax.grid(True, which="minor", color="#e2e8f0", linewidth=0.35, alpha=0.6)
            for side in ("top", "right", "bottom", "left"):
                ax.spines[side].set_visible(True)
                ax.spines[side].set_linewidth(0.8)
            ax.tick_params(direction="in", top=True, right=True, width=0.8)
            ax.legend(loc="upper right", frameon=True, facecolor="white", edgecolor="#cbd5e1", framealpha=0.92)

            rho = get_float("rho", 0.20)
            ax.text(
                0.03,
                0.05,
                f"rho={rho:.2f}\nSI-off: homodyne gain removed",
                transform=ax.transAxes,
                ha="left",
                va="bottom",
                fontsize=8,
                bbox={"fc": "white", "ec": "#cbd5e1", "alpha": 0.88, "pad": 2.0},
            )

            fig.tight_layout()
            canvas.draw_idle()
            status_var.set(
                f"SI-on calibration: {curves['source']}  |  "
                f"intercept={float(curves['intercept_db']):.2f} dB re 1 m  |  "
                f"points={len(points)}"
            )
        except Exception as exc:
            status_var.set(f"Error: {exc}")
            messagebox.showerror("Plot error", str(exc), parent=root)

    def load_files() -> None:
        paths = filedialog.askopenfilenames(
            parent=root,
            title="Load saved DSO/Range NPZ files",
            initialdir=str(DEFAULT_DATA_DIR if DEFAULT_DATA_DIR.exists() else APP_DIR),
            filetypes=[("NumPy save data", "*.npz"), ("All files", "*.*")],
        )
        if not paths:
            return
        errors: list[str] = []
        ch = vars_["channel"].get().strip() or "C2"
        for raw in paths:
            try:
                point = extract_measurement(Path(raw), ch)
                points.append(point)
                if math.isfinite(point.rho):
                    vars_["rho"].set(f"{point.rho:.6g}")
            except Exception as exc:
                errors.append(str(exc))
        refresh_list()
        redraw()
        if errors:
            messagebox.showwarning("Some files skipped", "\n".join(errors[:8]), parent=root)

    def load_folder() -> None:
        folder = filedialog.askdirectory(
            parent=root,
            title="Load all NPZ files in folder",
            initialdir=str(DEFAULT_DATA_DIR if DEFAULT_DATA_DIR.exists() else APP_DIR),
        )
        if not folder:
            return
        errors: list[str] = []
        ch = vars_["channel"].get().strip() or "C2"
        for path in sorted(Path(folder).glob("*.npz")):
            try:
                points.append(extract_measurement(path, ch))
            except Exception as exc:
                errors.append(str(exc))
        refresh_list()
        redraw()
        if errors:
            status_var.set(f"Loaded {len(points)} point(s); skipped {len(errors)} file(s).")

    def clear_points() -> None:
        points.clear()
        refresh_list()
        redraw()

    def save_figure() -> None:
        out = filedialog.asksaveasfilename(
            parent=root,
            title="Save figure",
            initialfile=Path(vars_["out"].get()).name,
            initialdir=str(Path(vars_["out"].get()).expanduser().parent),
            defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("PDF", "*.pdf"), ("SVG", "*.svg"), ("All files", "*.*")],
        )
        if not out:
            return
        vars_["out"].set(out)
        fig.savefig(out, dpi=600, bbox_inches="tight")
        status_var.set(f"Saved figure: {out}")

    def save_csv() -> None:
        out = filedialog.asksaveasfilename(
            parent=root,
            title="Save loaded points CSV",
            initialdir=str(DEFAULT_DATA_DIR if DEFAULT_DATA_DIR.exists() else APP_DIR),
            initialfile="si_snr_points.csv",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("All files", "*.*")],
        )
        if not out:
            return
        with open(out, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=["file", "label", "channel", "range_m", "snr_sens_db", "rho", "pslr_db"],
            )
            writer.writeheader()
            for p in points:
                writer.writerow({
                    "file": str(p.path),
                    "label": p.label,
                    "channel": p.channel,
                    "range_m": p.range_m,
                    "snr_sens_db": p.snr_sens_db,
                    "rho": p.rho,
                    "pslr_db": p.pslr_db,
                })
        status_var.set(f"Saved CSV: {out}")

    ttk.Button(btns, text="Plot", command=redraw).grid(row=0, column=0, sticky="ew", padx=(0, 3))
    ttk.Button(btns, text="Load NPZ", command=load_files).grid(row=0, column=1, sticky="ew", padx=(3, 0))
    ttk.Button(btns, text="Load Folder", command=load_folder).grid(row=1, column=0, sticky="ew", padx=(0, 3), pady=(4, 0))
    ttk.Button(btns, text="Clear", command=clear_points).grid(row=1, column=1, sticky="ew", padx=(3, 0), pady=(4, 0))
    ttk.Button(out_frame, text="Save Fig.", command=save_figure).grid(row=0, column=1, padx=(5, 0))
    ttk.Button(out_frame, text="Save CSV", command=save_csv).grid(row=0, column=2, padx=(5, 0))

    ttk.Label(left, textvariable=status_var, wraplength=330).grid(row=3, column=0, sticky="ew", pady=(8, 0))

    for key, var in vars_.items():
        if key != "out":
            var.trace_add("write", lambda *_: redraw())
    fit_var.trace_add("write", lambda *_: redraw())
    xscale_var.trace_add("write", lambda *_: redraw())

    redraw()
    root.mainloop()


def main() -> None:
    launch_gui()


if __name__ == "__main__":
    main()
