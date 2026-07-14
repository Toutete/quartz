"""Read NPZ files saved by isac_unified_gui.py's "Save Range Data" button.

Examples
--------
Single file summary:
    python read_range_data.py path/to/Range_....npz

Batch folder summary and CSV export:
    python read_range_data.py path/to/range_folder --csv summary.csv --profiles-dir profiles
"""

from __future__ import annotations

import argparse
import csv
import math
import re
from pathlib import Path
from typing import Any

import numpy as np


RANGE_KEY_RE = re.compile(r"^range__(?P<idx>\d+)__(?P<channel>.+?)__(?P<field>.+)$")


def unpack(value: Any) -> Any:
    """Match the GUI helper: one-element arrays become scalars."""
    arr = np.asarray(value)
    if arr.shape == ():
        item = arr.item()
        return item.item() if hasattr(item, "item") else item
    if arr.shape == (1,):
        item = arr[0]
        return item.item() if hasattr(item, "item") else item
    return arr


def to_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return float("nan")


def to_positive_int(value: Any) -> int:
    value_f = to_float(value)
    if not math.isfinite(value_f) or value_f <= 0:
        return 0
    return int(value_f)


def value_to_text(value: Any) -> str:
    if isinstance(value, np.ndarray):
        return f"array shape={value.shape} dtype={value.dtype}"
    if isinstance(value, float) and math.isnan(value):
        return "N/A"
    return str(value)


def metric_map(loaded: np.lib.npyio.NpzFile) -> dict[str, dict[str, Any]]:
    if "metric_keys" not in loaded.files or "metric_values" not in loaded.files:
        return {}

    keys = np.asarray(loaded["metric_keys"]).reshape(-1)
    values = np.asarray(loaded["metric_values"]).reshape(-1)
    labels = (
        np.asarray(loaded["metric_labels"]).reshape(-1)
        if "metric_labels" in loaded.files
        else keys
    )
    units = (
        np.asarray(loaded["metric_units"]).reshape(-1)
        if "metric_units" in loaded.files
        else np.asarray([""] * len(keys))
    )

    out: dict[str, dict[str, Any]] = {}
    for i, raw_key in enumerate(keys):
        key = str(unpack(raw_key))
        out[key] = {
            "value": unpack(values[i]) if i < len(values) else "",
            "label": str(unpack(labels[i])) if i < len(labels) else key,
            "unit": str(unpack(units[i])) if i < len(units) else "",
        }
    return out


def zero_reference_result(loaded: np.lib.npyio.NpzFile, ch: str, index: int = 0) -> dict[str, Any]:
    ch = str(ch).strip().upper()
    prefix = f"range_zero__{ch}__"
    item: dict[str, Any] = {
        "index": index,
        "channel": ch,
        "ch": ch,
        "range_est_method": "store-zero-reference",
        "profile_source": "reference (Store Zero Ref.)",
    }

    for key in (
        "delay_s", "frame_start", "peak_lag", "frame_period_s", "fs",
        "profile_center_m", "abs_range_m", "range_mode",
        "range_scale_m_per_s", "range_resolution_m",
    ):
        npz_key = prefix + key
        if npz_key in loaded.files:
            item[key] = unpack(loaded[npz_key])

    ref_m = item.get("profile_center_m", item.get("abs_range_m", float("nan")))
    item["reference_range_m"] = ref_m
    item["display_range_m"] = ref_m
    item["est_range"] = ref_m

    prof_key = prefix + "profile_prof_db"
    lags_key = prefix + "profile_lags"
    if prof_key in loaded.files and lags_key in loaded.files:
        prof_db = np.asarray(loaded[prof_key], dtype=float).reshape(-1)
        lags = np.asarray(loaded[lags_key], dtype=float).reshape(-1)
        peak_lag = to_float(unpack(loaded[prefix + "profile_peak_lag"])) if prefix + "profile_peak_lag" in loaded.files else to_float(item.get("peak_lag"))
        fs = to_float(unpack(loaded[prefix + "profile_fs"])) if prefix + "profile_fs" in loaded.files else to_float(item.get("fs"))
        scale = to_float(item.get("range_scale_m_per_s"))
        center_m = to_float(unpack(loaded[prefix + "profile_center_m"])) if prefix + "profile_center_m" in loaded.files else to_float(ref_m)
        n = min(len(prof_db), len(lags))
        if n >= 1 and math.isfinite(fs) and fs > 0 and math.isfinite(scale):
            rel_rng = (lags[:n] - peak_lag) / fs * scale if math.isfinite(peak_lag) else lags[:n] / fs * scale
            item["rng"] = rel_rng + center_m if math.isfinite(center_m) else rel_rng
            item["prof_db"] = prof_db[:n]
    return item


def collect_range_results(loaded: np.lib.npyio.NpzFile) -> list[dict[str, Any]]:
    by_result: dict[tuple[int, str], dict[str, Any]] = {}
    for key in loaded.files:
        match = RANGE_KEY_RE.match(key)
        if not match:
            continue
        idx = int(match.group("idx"))
        channel = match.group("channel").upper()
        field = match.group("field")
        item = by_result.setdefault((idx, channel), {"index": idx, "channel": channel})
        item[field] = unpack(loaded[key])

    results = [by_result[k] for k in sorted(by_result)]
    if results:
        return results

    if "range_summary_channels" not in loaded.files:
        if "range_zero_channels" in loaded.files:
            channels = [str(unpack(x)).strip().upper() for x in np.asarray(loaded["range_zero_channels"]).reshape(-1)]
            return [zero_reference_result(loaded, ch, i) for i, ch in enumerate(channels)]
        return []

    channels = np.asarray(loaded["range_summary_channels"]).reshape(-1)
    modes = np.asarray(loaded["range_summary_modes"]).reshape(-1) if "range_summary_modes" in loaded.files else []
    methods = np.asarray(loaded["range_summary_methods"]).reshape(-1) if "range_summary_methods" in loaded.files else []
    peaks = np.asarray(loaded["range_summary_peak_m"]).reshape(-1) if "range_summary_peak_m" in loaded.files else []
    displays = np.asarray(loaded["range_summary_display_m"]).reshape(-1) if "range_summary_display_m" in loaded.files else []
    mf_peaks = (
        np.asarray(loaded["range_summary_matched_filter_peak_m"]).reshape(-1)
        if "range_summary_matched_filter_peak_m" in loaded.files
        else []
    )
    pslr = np.asarray(loaded["range_summary_pslr_db"]).reshape(-1) if "range_summary_pslr_db" in loaded.files else []
    diff_mm = (
        np.asarray(loaded["range_summary_diff_range_mm"]).reshape(-1)
        if "range_summary_diff_range_mm" in loaded.files
        else []
    )
    coh = (
        np.asarray(loaded["range_summary_diff_cfr_coherence"]).reshape(-1)
        if "range_summary_diff_cfr_coherence" in loaded.files
        else []
    )

    for i, raw_ch in enumerate(channels):
        ch = str(unpack(raw_ch)).strip().upper()
        item: dict[str, Any] = {"index": i, "channel": ch, "ch": ch}
        if i < len(modes):
            item["range_mode"] = unpack(modes[i])
        if i < len(methods):
            item["range_est_method"] = unpack(methods[i])
        if i < len(peaks):
            item["est_range"] = unpack(peaks[i])
        if i < len(displays):
            item["display_range_m"] = unpack(displays[i])
        if i < len(mf_peaks):
            item["est_range_raw"] = unpack(mf_peaks[i])
        if i < len(pslr):
            item["pslr_db"] = unpack(pslr[i])
        if i < len(diff_mm):
            item["range_diff_mm"] = unpack(diff_mm[i])
        if i < len(coh):
            item["diff_coherence"] = unpack(coh[i])

        zero_item = zero_reference_result(loaded, ch, i)
        for key in ("rng", "prof_db", "reference_range_m"):
            if key in zero_item:
                item[key] = zero_item[key]
        if "rng" in item and "prof_db" in item:
            item["profile_source"] = "reference summary (Store Zero Ref.)"
        results.append(item)

    return results


def infer_processing_gain_db(result: dict[str, Any], loaded: np.lib.npyio.NpzFile) -> float:
    """Estimate matched-filter coherent processing gain from saved dimensions.

    The GUI does not currently save a scalar named "processing_gain_db".
    For range profiles, a practical processing-gain estimate is
    10*log10(number of coherent samples).  Prefer the saved per-chirp length
    and chirp count; otherwise fall back to the TX waveform length.
    """
    n_chirps = to_positive_int(result.get("n_chirps", float("nan")))
    pts_per_chirp = to_positive_int(result.get("pts_per_chirp", float("nan")))
    if n_chirps > 0 and pts_per_chirp > 0:
        return 10.0 * math.log10(n_chirps * pts_per_chirp)

    ref_len = to_positive_int(result.get("ref_len", float("nan")))
    if ref_len > 0:
        return 10.0 * math.log10(ref_len)

    if "tx__tx_signal" in loaded.files:
        n = int(np.asarray(loaded["tx__tx_signal"]).size)
        if n > 0:
            return 10.0 * math.log10(n)
    return float("nan")


def extract_file(path: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    with np.load(path, allow_pickle=True) as loaded:
        metrics = metric_map(loaded)
        ranges = collect_range_results(loaded)

        if not ranges:
            ranges = [{"index": 0, "channel": str(unpack(loaded["rx_primary_channel"])) if "rx_primary_channel" in loaded.files else ""}]

        created = value_to_text(unpack(loaded["created"])) if "created" in loaded.files else ""
        role = value_to_text(unpack(loaded["range_save_role"])) if "range_save_role" in loaded.files else ""

        rows: list[dict[str, Any]] = []
        for result in ranges:
            row = {
                "file": str(path),
                "created": created,
                "role": role,
                "range_index": result.get("index", ""),
                "channel": result.get("ch", result.get("channel", "")),
                "reference_range_m": result.get(
                    "reference_range_m",
                    result.get("zero_ref_center_m", result.get("profile_center_m", float("nan"))),
                ),
                "reference_range_mm": to_float(
                    result.get(
                        "reference_range_m",
                        result.get("zero_ref_center_m", result.get("profile_center_m", float("nan"))),
                    )
                )
                * 1e3,
                "range_peak_m": result.get(
                    "display_range_m",
                    result.get("est_range", metrics.get("range_peak_m", {}).get("value", float("nan"))),
                ),
                "range_peak_mm": to_float(
                    result.get(
                        "display_range_m",
                        result.get("est_range", metrics.get("range_peak_m", {}).get("value", float("nan"))),
                    )
                )
                * 1e3,
                "band_power_dbm": metrics.get("band_power_dbm", {}).get("value", float("nan")),
                "radar_snr_db": metrics.get("snr_rad_db", {}).get("value", float("nan")),
                "comm_snr_db": metrics.get("snr_com_db", {}).get("value", float("nan")),
                "evm_db": metrics.get("evm_db", {}).get("value", float("nan")),
                "evm_pct": metrics.get("evm_pct", {}).get("value", float("nan")),
                "processing_gain_db_est": infer_processing_gain_db(result, loaded),
                "pslr_db": result.get("pslr_db", metrics.get("pslr_db", {}).get("value", float("nan"))),
                "range_diff_mm": result.get("range_diff_mm", float("nan")),
                "range_mode": result.get("range_mode", ""),
                "range_est_method": result.get("range_est_method", ""),
                "rng": np.asarray(result.get("rng", []), dtype=float).reshape(-1),
                "prof_db": np.asarray(result.get("prof_db", []), dtype=float).reshape(-1),
                "ref_rng": np.asarray(result.get("ref_rng", []), dtype=float).reshape(-1),
                "ref_prof_db": np.asarray(result.get("ref_prof_db", []), dtype=float).reshape(-1),
                "profile_source": result.get("profile_source", "measurement"),
            }
            rows.append(row)
    return rows, metrics


def iter_input_paths(input_path: Path) -> list[Path]:
    if input_path.is_file():
        return [input_path]
    return sorted(input_path.glob("*.npz"))


def print_summary(rows: list[dict[str, Any]]) -> None:
    cols = [
        "file",
        "channel",
        "role",
        "range_peak_mm",
        "reference_range_mm",
        "range_diff_mm",
        "band_power_dbm",
        "radar_snr_db",
        "comm_snr_db",
        "evm_db",
        "evm_pct",
        "processing_gain_db_est",
        "pslr_db",
    ]
    print("\t".join(cols))
    for row in rows:
        printable = []
        for col in cols:
            value = row.get(col, "")
            if col == "file":
                value = Path(str(value)).name
            printable.append(value_to_text(value))
        print("\t".join(printable))


def write_summary_csv(rows: list[dict[str, Any]], path: Path) -> None:
    fieldnames = [
        "file",
        "created",
        "role",
        "range_index",
        "channel",
        "reference_range_m",
        "reference_range_mm",
        "range_peak_m",
        "range_peak_mm",
        "band_power_dbm",
        "radar_snr_db",
        "comm_snr_db",
        "evm_db",
        "evm_pct",
        "processing_gain_db_est",
        "pslr_db",
        "range_diff_mm",
        "range_mode",
        "range_est_method",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: value_to_text(row.get(name, "")) for name in fieldnames})


def write_profile_csvs(rows: list[dict[str, Any]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for row in rows:
        rng = row.get("rng")
        prof_db = row.get("prof_db")
        if not isinstance(rng, np.ndarray) or not isinstance(prof_db, np.ndarray):
            continue
        n = min(len(rng), len(prof_db))
        if n == 0:
            continue
        stem = Path(str(row["file"])).stem
        channel = str(row.get("channel", "ch")).replace(" ", "_")
        out_path = output_dir / f"{stem}_{channel}_range_profile.csv"
        with out_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["range_m", "range_mm", "profile_db"])
            for r_m, p_db in zip(rng[:n], prof_db[:n]):
                writer.writerow([r_m, r_m * 1e3, p_db])


def load_raw_channels(path: Path) -> dict[str, dict[str, Any]]:
    channels: dict[str, dict[str, Any]] = {}
    with np.load(path, allow_pickle=True) as loaded:
        if "rx_channels" in loaded.files:
            for raw_ch in np.asarray(loaded["rx_channels"]).reshape(-1):
                ch = str(unpack(raw_ch)).strip().upper()
                sig_key = f"rx__{ch}__sig"
                fs_key = f"rx__{ch}__fs"
                t_key = f"rx__{ch}__t"
                if sig_key not in loaded.files or fs_key not in loaded.files:
                    continue
                sig = np.asarray(loaded[sig_key], dtype=float).reshape(-1)
                fs = to_float(unpack(loaded[fs_key]))
                t = (
                    np.asarray(loaded[t_key], dtype=float).reshape(-1)
                    if t_key in loaded.files
                    else np.arange(len(sig), dtype=float) / fs
                )
                channels[ch] = {"sig": sig, "fs": fs, "t": t}

        if not channels and "rx_sig" in loaded.files and "rx_fs" in loaded.files:
            ch = str(unpack(loaded["rx_primary_channel"])).strip().upper() if "rx_primary_channel" in loaded.files else "RX"
            sig = np.asarray(loaded["rx_sig"], dtype=float).reshape(-1)
            fs = to_float(unpack(loaded["rx_fs"]))
            t = (
                np.asarray(loaded["rx_t"], dtype=float).reshape(-1)
                if "rx_t" in loaded.files
                else np.arange(len(sig), dtype=float) / fs
            )
            channels[ch or "RX"] = {"sig": sig, "fs": fs, "t": t}
    return channels


def compute_raw_spectrum(sig: np.ndarray, fs: float, max_fft: int = 262144) -> tuple[np.ndarray, np.ndarray]:
    sig = np.asarray(sig, dtype=float).reshape(-1)
    if len(sig) < 8 or not math.isfinite(fs) or fs <= 0:
        return np.asarray([]), np.asarray([])
    n = min(len(sig), max_fft)
    start = max(0, (len(sig) - n) // 2)
    x = sig[start:start + n]
    x = x - float(np.mean(x))
    win = np.hanning(len(x))
    spec = np.fft.rfft(x * win)
    freq_ghz = np.fft.rfftfreq(len(x), d=1.0 / fs) / 1e9
    mag = np.abs(spec) / max(float(np.sum(win)), 1e-30)
    mag_db = 20.0 * np.log10(np.maximum(mag, 1e-18))
    return freq_ghz, mag_db


def fmt_cell(value: Any, digits: int = 3) -> str:
    value = unpack(value)
    if isinstance(value, np.ndarray):
        return f"array {value.shape}"
    if isinstance(value, (float, int, np.floating, np.integer)):
        value_f = float(value)
        if not math.isfinite(value_f):
            return "N/A"
        if abs(value_f) >= 1000 or (0 < abs(value_f) < 0.001):
            return f"{value_f:.{digits}e}"
        return f"{value_f:.{digits}f}"
    text = str(value)
    return "N/A" if text.lower() == "nan" else text


def metric_value(metrics: dict[str, dict[str, Any]], key: str) -> Any:
    return metrics.get(key, {}).get("value", float("nan"))


class RangeDataViewer:
    summary_columns = [
        ("file", "File", 260),
        ("channel", "Ch", 55),
        ("role", "Role", 80),
        ("range_peak_mm", "Meas mm", 90),
        ("reference_range_mm", "Ref mm", 90),
        ("range_diff_mm", "Diff mm", 85),
        ("band_power_dbm", "Band dBm", 85),
        ("radar_snr_db", "Radar SNR", 85),
        ("comm_snr_db", "Comm SNR", 85),
        ("evm_db", "EVM dB", 75),
        ("processing_gain_db_est", "Proc Gain", 85),
        ("pslr_db", "PSLR", 70),
    ]

    detail_metrics = [
        ("range_peak_mm", "Range Peak", "mm"),
        ("reference_range_mm", "Reference Range", "mm"),
        ("range_diff_mm", "Range Difference", "mm"),
        ("band_power_dbm", "Band Power", "dBm"),
        ("radar_snr_db", "Radar SNR", "dB"),
        ("comm_snr_db", "Communication SNR", "dB"),
        ("evm_db", "EVM", "dB"),
        ("evm_pct", "EVM", "%"),
        ("processing_gain_db_est", "Processing Gain", "dB est."),
        ("pslr_db", "PSLR", "dB"),
        ("range_mode", "Range Mode", ""),
        ("range_est_method", "Range Method", ""),
        ("profile_source", "Profile Source", ""),
        ("role", "Saved Role", ""),
    ]

    def __init__(self, root, initial_folder: Path):
        import tkinter as tk
        from tkinter import ttk
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
        from matplotlib.figure import Figure

        self.tk = tk
        self.ttk = ttk
        self.root = root
        self.root.title("ISAC Saved Range Data Viewer")
        self.root.geometry("1380x850")
        self.folder_var = tk.StringVar(value=str(initial_folder))
        self.status_var = tk.StringVar(value="Select a folder containing saved .npz files.")
        self.rows: list[dict[str, Any]] = []
        self.metrics_by_file: dict[str, dict[str, dict[str, Any]]] = {}
        self.plot_data: dict[Any, tuple[np.ndarray, np.ndarray, str, str]] = {}
        self.markers: dict[Any, list[Any]] = {}

        top = ttk.Frame(root, padding=(8, 8, 8, 4))
        top.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(top, text="Folder").pack(side=tk.LEFT)
        ttk.Entry(top, textvariable=self.folder_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 6))
        ttk.Button(top, text="Browse", command=self.browse_folder).pack(side=tk.LEFT)
        ttk.Button(top, text="Reload", command=self.load_folder).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(top, text="Export CSV", command=self.export_csv).pack(side=tk.LEFT, padx=(6, 0))

        main = ttk.PanedWindow(root, orient=tk.HORIZONTAL)
        main.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8, pady=(2, 8))

        left = ttk.Frame(main)
        main.add(left, weight=2)
        right = ttk.PanedWindow(main, orient=tk.VERTICAL)
        main.add(right, weight=3)

        self.summary_tree = ttk.Treeview(
            left,
            columns=[name for name, _, _ in self.summary_columns],
            show="headings",
            selectmode="browse",
            height=24,
        )
        for name, label, width in self.summary_columns:
            self.summary_tree.heading(name, text=label)
            anchor = tk.W if name == "file" else tk.CENTER
            self.summary_tree.column(name, width=width, minwidth=45, anchor=anchor, stretch=(name == "file"))
        yscroll = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self.summary_tree.yview)
        xscroll = ttk.Scrollbar(left, orient=tk.HORIZONTAL, command=self.summary_tree.xview)
        self.summary_tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.summary_tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        self.summary_tree.bind("<<TreeviewSelect>>", self.on_select_row)

        detail_frame = ttk.Frame(right)
        right.add(detail_frame, weight=1)
        self.detail_tree = ttk.Treeview(detail_frame, columns=("metric", "value", "unit"), show="headings", height=11)
        for name, label, width in (("metric", "Metric", 190), ("value", "Value", 160), ("unit", "Unit", 90)):
            self.detail_tree.heading(name, text=label)
            self.detail_tree.column(name, width=width, anchor=tk.W if name == "metric" else tk.CENTER)
        self.detail_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        detail_scroll = ttk.Scrollbar(detail_frame, orient=tk.VERTICAL, command=self.detail_tree.yview)
        detail_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.detail_tree.configure(yscrollcommand=detail_scroll.set)

        plot_frame = ttk.Frame(right)
        right.add(plot_frame, weight=4)
        self.fig = Figure(figsize=(9, 6), dpi=100)
        self.ax_spectrum = self.fig.add_subplot(211)
        self.ax_range = self.fig.add_subplot(212)
        self.fig.tight_layout(pad=2.4)
        self.canvas = FigureCanvasTkAgg(self.fig, master=plot_frame)
        toolbar = NavigationToolbar2Tk(self.canvas, plot_frame, pack_toolbar=False)
        toolbar.update()
        toolbar.pack(side=tk.TOP, fill=tk.X)
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.canvas.mpl_connect("button_press_event", self.on_plot_click)

        status = ttk.Label(root, textvariable=self.status_var, anchor=tk.W, padding=(8, 0, 8, 6))
        status.pack(side=tk.BOTTOM, fill=tk.X)

        self.load_folder()

    def browse_folder(self) -> None:
        from tkinter import filedialog

        selected = filedialog.askdirectory(
            title="Select folder containing saved Range .npz files",
            initialdir=self.folder_var.get() or str(Path(__file__).resolve().parent),
        )
        if selected:
            self.folder_var.set(selected)
            self.load_folder()

    def load_folder(self) -> None:
        from tkinter import messagebox

        folder = Path(self.folder_var.get()).expanduser()
        self.summary_tree.delete(*self.summary_tree.get_children())
        self.detail_tree.delete(*self.detail_tree.get_children())
        self.rows = []
        self.metrics_by_file = {}
        self.clear_plots()

        paths = iter_input_paths(folder)
        if not paths:
            self.status_var.set(f"No .npz files found: {folder}")
            return

        failed: list[str] = []
        for path in paths:
            try:
                rows, metrics = extract_file(path)
                self.metrics_by_file[str(path)] = metrics
                self.rows.extend(rows)
            except Exception as exc:
                failed.append(f"{path.name}: {exc}")

        for i, row in enumerate(self.rows):
            values = []
            for name, _, _ in self.summary_columns:
                value = row.get(name, "")
                if name == "file":
                    value = Path(str(value)).name
                values.append(fmt_cell(value))
            self.summary_tree.insert("", "end", iid=str(i), values=values)

        if self.rows:
            self.summary_tree.selection_set("0")
            self.summary_tree.focus("0")
            self.show_row(0)

        msg = f"Loaded {len(self.rows)} result row(s) from {len(paths)} file(s)."
        if failed:
            msg += f" Failed: {len(failed)}"
            messagebox.showwarning("Some files could not be read", "\n".join(failed[:8]))
        self.status_var.set(msg)

    def clear_plots(self) -> None:
        self.ax_spectrum.clear()
        self.ax_spectrum.set_title("Raw Spectrum")
        self.ax_spectrum.set_xlabel("Frequency (GHz)")
        self.ax_spectrum.set_ylabel("Magnitude (dB rel.)")
        self.ax_spectrum.grid(True, alpha=0.3)
        self.ax_range.clear()
        self.ax_range.set_title("Range Profile")
        self.ax_range.set_xlabel("Range (mm)")
        self.ax_range.set_ylabel("Profile (dB)")
        self.ax_range.grid(True, alpha=0.3)
        self.plot_data = {}
        self.markers = {}
        self.canvas.draw_idle()

    def on_select_row(self, _event=None) -> None:
        selection = self.summary_tree.selection()
        if not selection:
            return
        self.show_row(int(selection[0]))

    def show_row(self, index: int) -> None:
        if index < 0 or index >= len(self.rows):
            return
        row = self.rows[index]
        path = Path(str(row["file"]))
        metrics = self.metrics_by_file.get(str(path), {})

        self.detail_tree.delete(*self.detail_tree.get_children())
        for key, label, unit in self.detail_metrics:
            value = row.get(key, metric_value(metrics, key))
            self.detail_tree.insert("", "end", values=(label, fmt_cell(value, 4), unit))

        for key, item in metrics.items():
            if key in {m[0] for m in self.detail_metrics}:
                continue
            label = item.get("label", key)
            value = item.get("value", "")
            unit = item.get("unit", "")
            self.detail_tree.insert("", "end", values=(label, fmt_cell(value, 4), unit))

        self.plot_row(row)
        self.status_var.set(f"Selected {path.name} / {row.get('channel', '')}. Click a plot to place a value marker.")

    def plot_row(self, row: dict[str, Any]) -> None:
        self.ax_spectrum.clear()
        self.ax_range.clear()
        self.plot_data = {}
        self.markers = {}

        path = Path(str(row["file"]))
        channel = str(row.get("channel", "")).strip().upper()
        try:
            raw_channels = load_raw_channels(path)
        except Exception:
            raw_channels = {}

        raw = raw_channels.get(channel) if channel in raw_channels else (next(iter(raw_channels.values())) if raw_channels else None)
        if raw:
            freq_ghz, mag_db = compute_raw_spectrum(raw["sig"], raw["fs"])
            if len(freq_ghz):
                raw_ch = channel if channel in raw_channels else next(iter(raw_channels.keys()))
                self.ax_spectrum.plot(freq_ghz, mag_db, lw=0.9, color="#2563eb")
                self.ax_spectrum.set_title(f"Raw Spectrum ({raw_ch})")
                self.plot_data[self.ax_spectrum] = (freq_ghz, mag_db, "GHz", "dB rel.")
            else:
                self.ax_spectrum.text(0.5, 0.5, "No valid raw spectrum", ha="center", va="center", transform=self.ax_spectrum.transAxes)
        else:
            self.ax_spectrum.text(0.5, 0.5, "No raw RX data in file", ha="center", va="center", transform=self.ax_spectrum.transAxes)
        self.ax_spectrum.set_xlabel("Frequency (GHz)")
        self.ax_spectrum.set_ylabel("Magnitude (dB rel.)")
        self.ax_spectrum.grid(True, alpha=0.3)

        rng = np.asarray(row.get("rng", []), dtype=float).reshape(-1)
        prof_db = np.asarray(row.get("prof_db", []), dtype=float).reshape(-1)
        n = min(len(rng), len(prof_db))
        if n:
            x_mm = rng[:n] * 1e3
            y_db = prof_db[:n]
            self.ax_range.plot(x_mm, y_db, lw=1.0, color="#b45309", label="profile")
            if "ref_rng" in row and "ref_prof_db" in row:
                ref_rng = np.asarray(row.get("ref_rng", []), dtype=float).reshape(-1)
                ref_prof = np.asarray(row.get("ref_prof_db", []), dtype=float).reshape(-1)
                nr = min(len(ref_rng), len(ref_prof))
                if nr:
                    self.ax_range.plot(ref_rng[:nr] * 1e3, ref_prof[:nr], lw=0.9, color="#64748b", alpha=0.75, label="reference")
                    self.ax_range.legend(loc="best")
            source = str(row.get("profile_source", "measurement"))
            self.ax_range.set_title(f"Range Profile ({row.get('channel', '')}, {source})")
            self.plot_data[self.ax_range] = (x_mm, y_db, "mm", "dB")
            if np.any(np.isfinite(y_db)):
                peak_idx = int(np.nanargmax(y_db))
                self.add_marker(self.ax_range, x_mm[peak_idx], y_db[peak_idx], "peak")
        else:
            self.ax_range.text(0.5, 0.5, "No range profile saved for this row", ha="center", va="center", transform=self.ax_range.transAxes)
            self.ax_range.set_title("Range Profile")
        self.ax_range.set_xlabel("Range (mm)")
        self.ax_range.set_ylabel("Profile (dB)")
        self.ax_range.grid(True, alpha=0.3)

        self.fig.tight_layout(pad=2.4)
        self.canvas.draw_idle()

    def on_plot_click(self, event) -> None:
        if event.inaxes not in self.plot_data or event.xdata is None:
            return
        ax = event.inaxes
        x, y, x_unit, y_unit = self.plot_data[ax]
        if len(x) == 0:
            return
        idx = int(np.nanargmin(np.abs(x - event.xdata)))
        x0 = float(x[idx])
        y0 = float(y[idx])
        self.add_marker(ax, x0, y0, "marker")
        self.status_var.set(f"Marker: x={x0:.6g} {x_unit}, y={y0:.6g} {y_unit}")
        self.canvas.draw_idle()

    def add_marker(self, ax, x: float, y: float, label: str) -> None:
        for artist in self.markers.get(ax, []):
            try:
                artist.remove()
            except Exception:
                pass
        text = f"{label}\nx={x:.4g}\ny={y:.4g}"
        line = ax.axvline(x, color="#dc2626", lw=0.9, ls="--")
        point = ax.scatter([x], [y], color="#dc2626", s=32, zorder=5)
        note = ax.annotate(
            text,
            xy=(x, y),
            xytext=(8, 10),
            textcoords="offset points",
            fontsize=8,
            bbox={"boxstyle": "round,pad=0.25", "fc": "white", "ec": "#dc2626", "alpha": 0.9},
            arrowprops={"arrowstyle": "->", "color": "#dc2626", "lw": 0.8},
        )
        self.markers[ax] = [line, point, note]

    def export_csv(self) -> None:
        from tkinter import filedialog, messagebox

        if not self.rows:
            messagebox.showwarning("No data", "Load a folder first.")
            return
        out = filedialog.asksaveasfilename(
            title="Save summary CSV",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialfile="range_summary.csv",
        )
        if not out:
            return
        try:
            write_summary_csv(self.rows, Path(out))
            self.status_var.set(f"Saved CSV: {out}")
        except Exception as exc:
            messagebox.showerror("Export error", str(exc))


def launch_gui(initial_folder: Path) -> None:
    import tkinter as tk

    root = tk.Tk()
    RangeDataViewer(root, initial_folder)
    root.mainloop()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read range data saved by isac_unified_gui.py.",
    )
    default_input = Path(__file__).resolve().parent / "data" / "range"
    parser.add_argument(
        "input",
        type=Path,
        nargs="?",
        default=default_input,
        help=f"Saved .npz file or folder containing .npz files. Default: {default_input}",
    )
    parser.add_argument("--csv", type=Path, help="Optional summary CSV output path.")
    parser.add_argument("--profiles-dir", type=Path, help="Optional folder for per-file range profile CSVs.")
    parser.add_argument("--list-keys", action="store_true", help="Print raw NPZ keys for debugging.")
    parser.add_argument("--cli", action="store_true", help="Print a command-line summary instead of opening the GUI.")
    args = parser.parse_args()

    if not (args.cli or args.csv or args.profiles_dir or args.list_keys):
        launch_gui(args.input)
        return

    paths = iter_input_paths(args.input)
    if not paths:
        raise SystemExit(f"No .npz files found: {args.input}")

    all_rows: list[dict[str, Any]] = []
    for path in paths:
        if args.list_keys:
            with np.load(path, allow_pickle=True) as loaded:
                print(f"\n[{path}]")
                for key in loaded.files:
                    print(key)
        rows, _ = extract_file(path)
        all_rows.extend(rows)

    print_summary(all_rows)

    if args.csv:
        write_summary_csv(all_rows, args.csv)
        print(f"\nsummary CSV: {args.csv}")
    if args.profiles_dir:
        write_profile_csvs(all_rows, args.profiles_dir)
        print(f"range profile CSV folder: {args.profiles_dir}")


if __name__ == "__main__":
    main()
