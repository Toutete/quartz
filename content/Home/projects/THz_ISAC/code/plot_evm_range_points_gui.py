"""Plot measured EVM and sensing SINR points versus manually assigned range.

The default dataset is the three NPZ files in ``data/EVM_range``.  EVM is
recomputed from the saved raw C1 capture using the same DFT-s-OFDM demodulation
helpers used by ``isac_gui.py`` via ``remeasure_cpe_evm.py``. Sensing SINR is
read from the saved metric by default, with an optional range-profile fallback.

This GUI intentionally shows measured points only.  It does not draw simulated,
extrapolated, SI-on/off reference, or threshold curves.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from read_range_data import collect_range_results, infer_processing_gain_db, metric_map, to_float
from remeasure_cpe_evm import remeasure


APP_DIR = Path(__file__).resolve().parent
DEFAULT_DIR = APP_DIR / "data" / "EVM_range"


@dataclass
class Point:
    path: Path
    label: str
    range_mm: float
    evm_db: float
    radar_snr_db: float
    radar_pre_snr_db: float
    radar_post_snr_db: float
    processing_gain_db: float
    evm_source: str
    radar_source: str


def db_normalize(profile_db: np.ndarray) -> np.ndarray:
    y = np.asarray(profile_db, dtype=float).reshape(-1)
    finite = np.isfinite(y)
    if not np.any(finite):
        return y
    return y - float(np.nanmax(y[finite]))


def metric_float(path: Path, *keys: str) -> float:
    with np.load(path, allow_pickle=True) as loaded:
        metrics = metric_map(loaded)
    for key in keys:
        value = to_float(metrics.get(key, {}).get("value", float("nan")))
        if math.isfinite(value):
            return value
    return float("nan")


def evm_from_file(path: Path, mode: str) -> tuple[float, str]:
    stored = metric_float(path, "evm_db")
    if mode == "Stored metric":
        if math.isfinite(stored):
            return stored, "stored evm_db"
        sinr = metric_float(path, "evm_snr", "sinr_com_db")
        if math.isfinite(sinr):
            return -sinr, "derived from EVM/SINR"

    try:
        row = remeasure(path, channel="C1")
        key_by_mode = {
            "Re-demod": "redemod_evm_db",
            "Block CPE": "block_cpe_evm_db",
            "Complex gain": "block_complex_gain_evm_db",
            "Stored metric": "redemod_evm_db",
        }
        key = key_by_mode.get(mode, "redemod_evm_db")
        value = float(row.get(key, float("nan")))
        if math.isfinite(value):
            return value, key
    except Exception:
        pass

    if math.isfinite(stored):
        return stored, "stored evm_db fallback"

    sinr = metric_float(path, "evm_snr", "sinr_com_db")
    if math.isfinite(sinr):
        return -sinr, "derived from EVM/SINR"
    return float("nan"), "N/A"


def radar_snr_from_profile(path: Path, range_mm: float, use_reference: bool) -> tuple[float, str]:
    target_m = range_mm * 1e-3
    try:
        with np.load(path, allow_pickle=True) as loaded:
            results = collect_range_results(loaded)
        result = next(
            (item for item in results if str(item.get("channel", item.get("ch", ""))).strip().upper() == "C2"),
            results[0] if results else {},
        )
        if use_reference:
            x = np.asarray(result.get("ref_rng", []), dtype=float).reshape(-1)
            y = db_normalize(np.asarray(result.get("ref_prof_db", []), dtype=float).reshape(-1))
            source = "reference profile"
        else:
            x = np.asarray(result.get("rng", []), dtype=float).reshape(-1)
            y = db_normalize(np.asarray(result.get("prof_db", []), dtype=float).reshape(-1))
            source = "range profile"
        n = min(len(x), len(y))
        if n < 8:
            return float("nan"), "profile unavailable"
        x = x[:n]
        y = y[:n]
        finite = np.isfinite(x) & np.isfinite(y)
        roi = finite & (np.abs(x - target_m) <= 0.04)
        if np.count_nonzero(roi) >= 4:
            roi_idx = np.flatnonzero(roi)
            pk = int(roi_idx[int(np.nanargmax(y[roi]))])
        elif np.count_nonzero(finite) >= 4:
            finite_idx = np.flatnonzero(finite)
            pk = int(finite_idx[int(np.nanargmax(y[finite]))])
            source += " global peak"
        else:
            return float("nan"), "profile invalid"
        floor = finite & (np.abs(x - x[pk]) > 0.025)
        if np.count_nonzero(floor) < 4:
            return float("nan"), "profile floor unavailable"
        return float(y[pk] - np.nanmedian(y[floor])), source
    except Exception:
        return float("nan"), "profile error"


def c2_processing_gain_db(path: Path) -> float:
    try:
        with np.load(path, allow_pickle=True) as loaded:
            results = collect_range_results(loaded)
            result = next(
                (item for item in results if str(item.get("channel", item.get("ch", ""))).strip().upper() == "C2"),
                results[0] if results else {},
            )
            return float(infer_processing_gain_db(result, loaded))
    except Exception:
        return float("nan")


def radar_snr_from_file(path: Path, range_mm: float, source_mode: str, use_reference: bool) -> tuple[float, str]:
    metric = metric_float(path, "snr_com_db_c2", "snr_rad_db")
    prof, source = radar_snr_from_profile(path, range_mm, use_reference)
    pg = c2_processing_gain_db(path)

    if source_mode == "C2 pre-DSP metric":
        if math.isfinite(metric):
            return metric, "C2 pre-DSP metric"
        return prof, f"C2 post-processing fallback ({source})"

    if source_mode == "C2 post-proc PG-corrected":
        if math.isfinite(prof) and math.isfinite(pg):
            return prof - pg, f"C2 post-processing - PG ({source}, PG={pg:.1f} dB)"
        if math.isfinite(metric):
            return metric, "C2 pre-DSP metric fallback"
        return float("nan"), source

    if source_mode == "C2 post-proc profile":
        if math.isfinite(prof):
            return prof, f"C2 post-processing profile ({source})"
        if math.isfinite(metric):
            return metric, "C2 pre-DSP metric fallback"
        return float("nan"), source

    # Backward-compatible aliases.
    if source_mode == "Metric":
        if math.isfinite(metric):
            return metric, "C2 pre-DSP metric"
        return prof, f"C2 post-processing fallback ({source})"

    if math.isfinite(prof):
        return prof, f"C2 post-processing profile ({source})"
    if math.isfinite(metric):
        return metric, "C2 pre-DSP metric fallback"
    return float("nan"), source


def default_specs() -> list[tuple[str, Path, float, bool]]:
    return [
        (
            "Data, 1014 mm",
            DEFAULT_DIR / "Data_fIF11_fsym15_P-8_fRF280_DFT-s-OFDM_32QAM_Iph6.5.npz",
            1014.0,
            False,
        ),
        (
            "Data_range, 1099 mm",
            DEFAULT_DIR / "Data_range_fIF11_fsym15_P-8_fRF280_DFT-s-OFDM_32QAM_Iph7.npz",
            1099.0,
            False,
        ),
        (
            "Range, 1014 mm",
            DEFAULT_DIR / "Range_fIF11_fsym15_P-8_fRF280_DFT-s-OFDM_32QAM_Iph6.5.npz",
            1014.0,
            False,
        ),
        (
            "Range, 1006 mm",
            DEFAULT_DIR / "Range_fIF11_fsym15_P-8_fRF280_DFT-s-OFDM_32QAM_Iph6.5.npz",
            1006.0,
            True,
        ),
    ]


def build_point(
    label: str,
    path: Path,
    range_mm: float,
    evm_mode: str,
    radar_mode: str,
    use_reference: bool = False,
) -> Point:
    evm_db, evm_source = evm_from_file(path, evm_mode)
    radar_db, radar_source = radar_snr_from_file(path, range_mm, radar_mode, use_reference)
    radar_pre_db = metric_float(path, "snr_com_db_c2", "snr_rad_db")
    radar_post_db, _ = radar_snr_from_profile(path, range_mm, use_reference)
    pg_db = c2_processing_gain_db(path)
    return Point(
        path=path,
        label=label,
        range_mm=float(range_mm),
        evm_db=float(evm_db),
        radar_snr_db=float(radar_db),
        radar_pre_snr_db=float(radar_pre_db),
        radar_post_snr_db=float(radar_post_db),
        processing_gain_db=float(pg_db),
        evm_source=evm_source,
        radar_source=radar_source,
    )


def launch_gui() -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, simpledialog, ttk

    import matplotlib as mpl
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
    from matplotlib.figure import Figure
    from matplotlib.ticker import MultipleLocator

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
    root.title("EVM and Sensing SINR vs Range")
    root.geometry("1120x760")

    points: list[Point] = []
    evm_mode_var = tk.StringVar(value="Re-demod")
    radar_mode_var = tk.StringVar(value="C2 post-proc profile")
    x_min_var = tk.StringVar(value="980")
    x_max_var = tk.StringVar(value="1120")
    x_step_var = tk.StringVar(value="20")
    out_var = tk.StringVar(value=str(DEFAULT_DIR / "evm_sensing_sinr_vs_range.png"))
    status_var = tk.StringVar(value="Load defaults to plot measured EVM_range points.")

    root.columnconfigure(1, weight=1)
    root.rowconfigure(0, weight=1)
    left = ttk.Frame(root, padding=10)
    left.grid(row=0, column=0, sticky="ns")
    right = ttk.Frame(root, padding=(0, 10, 10, 10))
    right.grid(row=0, column=1, sticky="nsew")
    right.columnconfigure(0, weight=1)
    right.rowconfigure(0, weight=1)

    ctrl = ttk.LabelFrame(left, text="Controls", padding=8)
    ctrl.grid(row=0, column=0, sticky="new")

    ttk.Label(ctrl, text="EVM source").grid(row=0, column=0, sticky="w", pady=2)
    ttk.Combobox(
        ctrl,
        textvariable=evm_mode_var,
        values=("Re-demod", "Block CPE", "Complex gain", "Stored metric"),
        width=15,
        state="readonly",
    ).grid(row=0, column=1, sticky="ew", pady=2)
    ttk.Label(ctrl, text="Sensing SINR").grid(row=1, column=0, sticky="w", pady=2)
    ttk.Combobox(
        ctrl,
        textvariable=radar_mode_var,
        values=("C2 post-proc profile", "C2 pre-DSP metric", "C2 post-proc PG-corrected"),
        width=24,
        state="readonly",
    ).grid(row=1, column=1, sticky="ew", pady=2)
    for row, (label, var) in enumerate(
        (
            ("X min [mm]", x_min_var),
            ("X max [mm]", x_max_var),
            ("X step [mm]", x_step_var),
        ),
        start=2,
    ):
        ttk.Label(ctrl, text=label).grid(row=row, column=0, sticky="w", pady=2)
        ttk.Entry(ctrl, textvariable=var, width=12).grid(row=row, column=1, sticky="ew", pady=2)

    btns = ttk.Frame(ctrl)
    btns.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(8, 0))
    btns.columnconfigure((0, 1), weight=1)

    point_list = tk.Listbox(left, width=54, height=12)
    point_list.grid(row=1, column=0, sticky="new", pady=(8, 0))

    fig = Figure(figsize=(7.3, 5.8), dpi=110)
    axes = fig.subplots(2, 1, sharex=True)
    canvas = FigureCanvasTkAgg(fig, master=right)
    canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
    toolbar = NavigationToolbar2Tk(canvas, right, pack_toolbar=False)
    toolbar.grid(row=1, column=0, sticky="ew")

    out_frame = ttk.Frame(left)
    out_frame.grid(row=2, column=0, sticky="ew", pady=(8, 0))
    out_frame.columnconfigure(0, weight=1)
    ttk.Entry(out_frame, textvariable=out_var).grid(row=0, column=0, sticky="ew")

    def f(var: tk.StringVar, default: float) -> float:
        try:
            out = float(var.get())
            return out if math.isfinite(out) else default
        except Exception:
            return default

    def refresh_list() -> None:
        point_list.delete(0, tk.END)
        for p in points:
            pg_text = f", PG={p.processing_gain_db:.1f} dB" if math.isfinite(p.processing_gain_db) else ""
            point_list.insert(
                tk.END,
                f"{p.label}: x={p.range_mm:.0f} mm, EVM={p.evm_db:.2f} dB, Sensing={p.radar_snr_db:.2f} dB{pg_text}",
            )

    def redraw() -> None:
        ax_evm, ax_snr = axes
        for ax in axes:
            ax.clear()
            ax.grid(True, which="major", color="#cbd5e1", linewidth=0.5, alpha=0.85)
            for side in ("top", "right", "bottom", "left"):
                ax.spines[side].set_visible(True)
                ax.spines[side].set_linewidth(0.8)
            ax.tick_params(direction="in", top=True, right=True, width=0.8)

        if points:
            colors = ["#111827", "#2563eb", "#dc2626", "#0f766e", "#7c3aed", "#b45309"]
            markers = ["o", "s", "D", "^", "v", "P"]
            for idx, p in enumerate(points):
                color = colors[idx % len(colors)]
                marker = markers[idx % len(markers)]
                label = p.label
                ax_evm.scatter(p.range_mm, p.evm_db, s=42, marker=marker, color=color, label=label, zorder=5)
                ax_snr.scatter(p.range_mm, p.radar_snr_db, s=42, marker=marker, color=color, label=label, zorder=5)
                ax_evm.annotate(f"{p.range_mm:.0f}", (p.range_mm, p.evm_db), xytext=(4, 5), textcoords="offset points", fontsize=7)
                ax_snr.annotate(f"{p.range_mm:.0f}", (p.range_mm, p.radar_snr_db), xytext=(4, 5), textcoords="offset points", fontsize=7)

        xmin = f(x_min_var, 980.0)
        xmax = f(x_max_var, 1120.0)
        if xmax <= xmin:
            xmax = xmin + 10.0

        ax_evm.set_ylabel("EVM (dB)")
        ax_snr.set_ylabel("Sensing SINR (dB)")
        ax_snr.set_xlabel("Range (mm)")
        xstep = f(x_step_var, 20.0)
        for ax in axes:
            ax.set_xlim(xmin, xmax)
            if xstep > 0:
                ax.xaxis.set_major_locator(MultipleLocator(xstep))
        if points:
            ax_evm.legend(loc="best", frameon=True, facecolor="white", edgecolor="#cbd5e1", framealpha=0.9)
            ax_snr.legend(loc="best", frameon=True, facecolor="white", edgecolor="#cbd5e1", framealpha=0.9)
        fig.tight_layout()
        canvas.draw_idle()
        status_var.set(f"{len(points)} measured point(s), EVM={evm_mode_var.get()}, Sensing={radar_mode_var.get()}")

    def load_defaults() -> None:
        points.clear()
        errors: list[str] = []
        for label, path, range_mm, use_ref in default_specs():
            try:
                points.append(build_point(label, path, range_mm, evm_mode_var.get(), radar_mode_var.get(), use_ref))
            except Exception as exc:
                errors.append(f"{path.name}: {exc}")
        refresh_list()
        redraw()
        if errors:
            messagebox.showwarning("Load defaults", "\n".join(errors), parent=root)

    def load_one() -> None:
        path_str = filedialog.askopenfilename(
            parent=root,
            title="Load NPZ",
            initialdir=str(DEFAULT_DIR),
            filetypes=[("NumPy save data", "*.npz"), ("All files", "*.*")],
        )
        if not path_str:
            return
        try:
            range_mm = float(simpledialog.askstring("Range", "x value in mm:", parent=root) or "nan")
            label = Path(path_str).stem[:24]
            points.append(build_point(label, Path(path_str), range_mm, evm_mode_var.get(), radar_mode_var.get()))
            refresh_list()
            redraw()
        except Exception as exc:
            messagebox.showerror("Load NPZ", str(exc), parent=root)

    def clear() -> None:
        points.clear()
        refresh_list()
        redraw()

    def recompute() -> None:
        specs = [(p.label, p.path, p.range_mm, "reference" in p.radar_source.lower()) for p in points]
        points.clear()
        for label, path, range_mm, use_ref in specs:
            try:
                points.append(build_point(label, path, range_mm, evm_mode_var.get(), radar_mode_var.get(), use_ref))
            except Exception as exc:
                messagebox.showwarning("Recompute", f"{path.name}: {exc}", parent=root)
        refresh_list()
        redraw()

    def save_fig() -> None:
        out = filedialog.asksaveasfilename(
            parent=root,
            title="Save figure",
            initialdir=str(Path(out_var.get()).expanduser().parent),
            initialfile=Path(out_var.get()).name,
            defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("PDF", "*.pdf"), ("SVG", "*.svg"), ("All files", "*.*")],
        )
        if not out:
            return
        out_var.set(out)
        fig.savefig(out, dpi=600, bbox_inches="tight")
        status_var.set(f"Saved figure: {out}")

    def save_csv() -> None:
        out = filedialog.asksaveasfilename(
            parent=root,
            title="Save CSV",
            initialdir=str(DEFAULT_DIR),
            initialfile="evm_sensing_sinr_vs_range.csv",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("All files", "*.*")],
        )
        if not out:
            return
        with open(out, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=[
                    "label", "file", "range_mm", "evm_db", "radar_snr_db",
                    "radar_pre_snr_db", "radar_post_snr_db", "processing_gain_db",
                    "evm_source", "radar_source",
                ],
            )
            writer.writeheader()
            for p in points:
                writer.writerow({
                    "label": p.label,
                    "file": str(p.path),
                    "range_mm": p.range_mm,
                    "evm_db": p.evm_db,
                    "radar_snr_db": p.radar_snr_db,
                    "radar_pre_snr_db": p.radar_pre_snr_db,
                    "radar_post_snr_db": p.radar_post_snr_db,
                    "processing_gain_db": p.processing_gain_db,
                    "evm_source": p.evm_source,
                    "radar_source": p.radar_source,
                })
        status_var.set(f"Saved CSV: {out}")

    ttk.Button(btns, text="Load Defaults", command=load_defaults).grid(row=0, column=0, sticky="ew", padx=(0, 3))
    ttk.Button(btns, text="Load NPZ", command=load_one).grid(row=0, column=1, sticky="ew", padx=(3, 0))
    ttk.Button(btns, text="Recompute", command=recompute).grid(row=1, column=0, sticky="ew", padx=(0, 3), pady=(4, 0))
    ttk.Button(btns, text="Clear", command=clear).grid(row=1, column=1, sticky="ew", padx=(3, 0), pady=(4, 0))
    ttk.Button(out_frame, text="Save Fig.", command=save_fig).grid(row=0, column=1, padx=(5, 0))
    ttk.Button(out_frame, text="Save CSV", command=save_csv).grid(row=0, column=2, padx=(5, 0))
    ttk.Label(left, textvariable=status_var, wraplength=360).grid(row=3, column=0, sticky="ew", pady=(8, 0))

    for var in (evm_mode_var, radar_mode_var, x_min_var, x_max_var, x_step_var):
        var.trace_add("write", lambda *_: redraw())

    load_defaults()
    root.mainloop()


def main() -> None:
    launch_gui()


if __name__ == "__main__":
    main()
