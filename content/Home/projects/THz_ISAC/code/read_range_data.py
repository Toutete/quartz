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
            channel = result.get("ch", result.get("channel", ""))
            row = {
                "file": str(path),
                "created": created,
                "role": role,
                "range_index": result.get("index", ""),
                "channel": channel,
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
                "band_power_dbm": channel_metric_value(metrics, "band_power_dbm", str(channel)),
                "radar_snr_db": metrics.get("snr_rad_db", {}).get("value", channel_metric_value(metrics, "snr_com_db", str(channel))),
                "comm_snr_db": channel_metric_value(metrics, "snr_com_db", str(channel)),
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


def filename_token(text: str) -> str:
    token = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(text).strip())
    return token.strip("._") or "data"


def channels_in_npz(loaded: np.lib.npyio.NpzFile) -> list[str]:
    channels: list[str] = []
    if "rx_channels" in loaded.files:
        channels.extend(str(unpack(x)).strip().upper() for x in np.asarray(loaded["rx_channels"]).reshape(-1))
    for key in loaded.files:
        match = re.match(r"^rx__(C\d+)__sig$", key, re.IGNORECASE)
        if match:
            channels.append(match.group(1).upper())
    if not channels and "rx_sig" in loaded.files:
        channels.append(str(unpack(loaded["rx_primary_channel"])).strip().upper() if "rx_primary_channel" in loaded.files else "C1")
    out: list[str] = []
    for ch in channels:
        if ch and ch not in out:
            out.append(ch)
    return out


def promote_metric_channel(payload: dict[str, np.ndarray], channel: str) -> None:
    if "metric_keys" not in payload or "metric_values" not in payload:
        return
    channel = channel.strip().lower()
    if not channel:
        return
    keys = [str(unpack(x)) for x in np.asarray(payload["metric_keys"]).reshape(-1)]

    def replace_base(base_key: str, source_key: str) -> None:
        if base_key not in keys or source_key not in keys:
            return
        base_i = keys.index(base_key)
        src_i = keys.index(source_key)
        for arr_key in ("metric_values", "metric_units", "metric_notes", "metric_categories"):
            if arr_key in payload:
                arr = np.asarray(payload[arr_key]).copy()
                if base_i < len(arr) and src_i < len(arr):
                    arr[base_i] = arr[src_i]
                    payload[arr_key] = arr
        if "metric_labels" in payload:
            labels = np.asarray(payload["metric_labels"]).copy()
            if base_i < len(labels):
                labels[base_i] = labels[src_i] if src_i < len(labels) else base_key
                payload["metric_labels"] = labels

    replace_base("band_power_dbm", f"band_power_dbm_{channel}")
    replace_base("snr_com_db", f"snr_com_db_{channel}")
    replace_base("noise_floor_dbmhz", f"noise_floor_dbmhz_{channel}")
    if channel == "c2":
        replace_base("snr_rad_db", f"snr_com_db_{channel}")


def filter_range_summary_for_channel(payload: dict[str, np.ndarray], channel: str) -> None:
    if "range_summary_channels" not in payload:
        return
    channels = [str(unpack(x)).strip().upper() for x in np.asarray(payload["range_summary_channels"]).reshape(-1)]
    keep = [i for i, ch in enumerate(channels) if ch == channel]
    if not keep:
        for key in list(payload.keys()):
            if key.startswith("range_summary_"):
                payload.pop(key, None)
        return
    for key in list(payload.keys()):
        if not key.startswith("range_summary_"):
            continue
        arr = np.asarray(payload[key])
        if arr.ndim == 1 and len(arr) == len(channels):
            payload[key] = arr[keep]


def split_npz_for_gui(path: Path, output_dir: Path) -> list[Path]:
    written: list[Path] = []
    with np.load(path, allow_pickle=True) as loaded:
        channels = channels_in_npz(loaded)
        for ch in channels:
            sig_key = f"rx__{ch}__sig"
            fs_key = f"rx__{ch}__fs"
            t_key = f"rx__{ch}__t"
            if sig_key in loaded.files and fs_key in loaded.files:
                sig = np.asarray(loaded[sig_key], dtype=np.float64).reshape(-1)
                fs = float(np.asarray(loaded[fs_key]).reshape(-1)[0])
                t = (
                    np.asarray(loaded[t_key], dtype=np.float64).reshape(-1)
                    if t_key in loaded.files
                    else np.arange(len(sig), dtype=np.float64) / fs
                )
            elif "rx_sig" in loaded.files and "rx_fs" in loaded.files:
                sig = np.asarray(loaded["rx_sig"], dtype=np.float64).reshape(-1)
                fs = float(np.asarray(loaded["rx_fs"]).reshape(-1)[0])
                t = (
                    np.asarray(loaded["rx_t"], dtype=np.float64).reshape(-1)
                    if "rx_t" in loaded.files
                    else np.arange(len(sig), dtype=np.float64) / fs
                )
            else:
                continue
            if len(t) != len(sig):
                t = np.arange(len(sig), dtype=np.float64) / fs

            payload: dict[str, np.ndarray] = {}
            for key in loaded.files:
                if key in {"rx_sig", "rx_t", "rx_fs", "rx_primary_channel", "rx_channels", "rx_channel_count", "rx_display_channels", "capture_channel"}:
                    continue
                rx_match = re.match(r"^rx__(C\d+)__", key, re.IGNORECASE)
                if rx_match and rx_match.group(1).upper() != ch:
                    continue
                range_match = RANGE_KEY_RE.match(key)
                if range_match and range_match.group("channel").upper() != ch:
                    continue
                zero_match = re.match(r"^range_zero__(C\d+)__", key, re.IGNORECASE)
                if zero_match and zero_match.group(1).upper() != ch:
                    continue
                payload[key] = np.asarray(loaded[key])

            payload["rx_sig"] = sig
            payload["rx_t"] = t
            payload["rx_fs"] = np.asarray([fs], dtype=np.float64)
            payload["rx_primary_channel"] = np.asarray([ch])
            payload["rx_channels"] = np.asarray([ch])
            payload["rx_channel_count"] = np.asarray([1], dtype=np.int64)
            payload["rx_display_channels"] = np.asarray([ch])
            payload["capture_channel"] = np.asarray([ch])
            payload[f"rx__{ch}__sig"] = sig
            payload[f"rx__{ch}__t"] = t
            payload[f"rx__{ch}__fs"] = np.asarray([fs], dtype=np.float64)
            payload["range_split_source_file"] = np.asarray([path.name])
            payload["range_split_channel"] = np.asarray([ch])
            if "range_zero_channels" in payload:
                payload["range_zero_channels"] = np.asarray([ch])
            if "range_result_channels" in payload:
                payload["range_result_channels"] = np.asarray([ch])
            promote_metric_channel(payload, ch)
            filter_range_summary_for_channel(payload, ch)

            output_dir.mkdir(parents=True, exist_ok=True)
            out_path = output_dir / f"{path.stem}_{ch}_gui.npz"
            np.savez_compressed(out_path, **payload)
            written.append(out_path)
    return written


def split_folder_for_gui(input_path: Path, output_dir: Path) -> list[Path]:
    written: list[Path] = []
    for path in iter_input_paths(input_path):
        written.extend(split_npz_for_gui(path, output_dir))
    return written


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


def channel_metric_value(metrics: dict[str, dict[str, Any]], base_key: str, channel: str) -> Any:
    ch = str(channel).strip().lower()
    if ch:
        channel_key = f"{base_key}_{ch}"
        if channel_key in metrics:
            return metrics[channel_key].get("value", float("nan"))
    return metrics.get(base_key, {}).get("value", float("nan"))


def dbm_to_w(dbm: float) -> float:
    return 1e-3 * 10.0 ** (dbm / 10.0)


def w_to_dbm(watt: float) -> float:
    return 10.0 * math.log10(max(watt, 1e-30) / 1e-3)


def fspl_db(distance_m: float, rf_hz: float) -> float:
    return 20.0 * math.log10(4.0 * math.pi * max(distance_m, 1e-9) * rf_hz / 3e8)


def utcpd_output_dbm(photocurrent_ma: float) -> float:
    # Same calibration used by isac_unified_gui.py's simulation panel.
    return -10.0 + 20.0 * math.log10(max(photocurrent_ma, 1e-6) / 7.0)


def optional_float(text: str) -> float | None:
    text = str(text).strip()
    if text == "":
        return None
    try:
        value = float(text)
    except Exception:
        return None
    return value if math.isfinite(value) else None


def link_budget_from_row(row: dict[str, Any], params: dict[str, float]) -> list[tuple[str, float | str, str]]:
    band_dbm = to_float(row.get("band_power_dbm"))
    ch = str(row.get("channel", "")).strip().upper()
    range_m = to_float(row.get("range_peak_m"))
    if not math.isfinite(range_m) or range_m <= 0:
        range_m = to_float(row.get("reference_range_m"))
    range_m = max(range_m, 1e-9)

    ptx_dbm = params["tx_power_dbm"]
    rf_hz = params["rf_ghz"] * 1e9
    gt = params["tx_ant_gain_dbi"]
    gr = params["rx_ant_gain_dbi"]
    sigma = max(params["rcs_sqm"], 1e-12)
    lna_gain = params["lna_gain_db"]
    drive_gain = params["drive_amp_gain_db"]
    cable_loss = params["cable_loss_db"]
    conv_gain = params["homodyne_gain_db"]
    chain_gain = lna_gain + drive_gain + conv_gain - cable_loss
    lam = 3e8 / rf_hz

    one_way_loss = fspl_db(range_m, rf_hz)
    pr_one_way = ptx_dbm + gt + gr - one_way_loss
    pred_one_way_if = pr_one_way + chain_gain

    pr_mono = (
        ptx_dbm + gt + gr
        + 20.0 * math.log10(lam)
        + 10.0 * math.log10(sigma)
        - 30.0 * math.log10(4.0 * math.pi)
        - 40.0 * math.log10(range_m)
    )
    pred_mono_if = pr_mono + chain_gain

    if ch == "C1":
        selected_rf = pr_one_way
        selected_pred = pred_one_way_if
        selected_model = "C1 one-way"
    elif ch == "C2":
        selected_rf = pr_mono
        selected_pred = pred_mono_if
        selected_model = "C2 monostatic"
    else:
        selected_rf = pr_one_way
        selected_pred = pred_one_way_if
        selected_model = "one-way"

    inferred_conv = band_dbm - selected_rf - lna_gain - drive_gain + cable_loss
    inferred_rcs = float("nan")
    if ch == "C2" and math.isfinite(band_dbm):
        target_rf = band_dbm - chain_gain
        sigma_db = (
            target_rf - ptx_dbm - gt - gr
            - 20.0 * math.log10(lam)
            + 30.0 * math.log10(4.0 * math.pi)
            + 40.0 * math.log10(range_m)
        )
        inferred_rcs = 10.0 ** (sigma_db / 10.0)

    rows: list[tuple[str, float | str, str]] = [
        ("Selected model", selected_model, ""),
        ("Measured band power", band_dbm, "dBm"),
        ("Distance used", range_m * 1e3, "mm"),
        ("TX power", ptx_dbm, "dBm"),
        ("One-way FSPL", one_way_loss, "dB"),
        ("C1 RF at RX ant", pr_one_way, "dBm"),
        ("C1 predicted IF band", pred_one_way_if, "dBm"),
        ("C2 RF echo at RX ant", pr_mono, "dBm"),
        ("C2 predicted IF band", pred_mono_if, "dBm"),
        ("IF chain gain", chain_gain, "dB"),
        ("Meas - selected pred", band_dbm - selected_pred, "dB"),
        ("Inferred homodyne gain", inferred_conv, "dB"),
        ("Inferred RCS", inferred_rcs, "m^2"),
    ]
    return rows


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
        self.axis_vars = {
            "spec_xmin": tk.StringVar(value=""),
            "spec_xmax": tk.StringVar(value=""),
            "spec_ymin": tk.StringVar(value=""),
            "spec_ymax": tk.StringVar(value=""),
            "range_xmin": tk.StringVar(value=""),
            "range_xmax": tk.StringVar(value=""),
            "range_ymin": tk.StringVar(value=""),
            "range_ymax": tk.StringVar(value=""),
        }
        self.budget_vars = {
            "photocurrent_ma": tk.StringVar(value="7.0"),
            "tx_power_dbm": tk.StringVar(value="-10.0"),
            "rf_ghz": tk.StringVar(value="280.0"),
            "tx_ant_gain_dbi": tk.StringVar(value="25.0"),
            "rx_ant_gain_dbi": tk.StringVar(value="25.0"),
            "lna_gain_db": tk.StringVar(value="14.0"),
            "drive_amp_gain_db": tk.StringVar(value="20.0"),
            "cable_loss_db": tk.StringVar(value="0.0"),
            "homodyne_gain_db": tk.StringVar(value="0.0"),
            "rcs_sqm": tk.StringVar(value="1.0"),
        }
        self.use_iph_var = tk.BooleanVar(value=False)
        self.current_row_index: int | None = None

        top = ttk.Frame(root, padding=(8, 8, 8, 4))
        top.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(top, text="Folder").pack(side=tk.LEFT)
        ttk.Entry(top, textvariable=self.folder_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 6))
        ttk.Button(top, text="Browse", command=self.browse_folder).pack(side=tk.LEFT)
        ttk.Button(top, text="Reload", command=self.load_folder).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(top, text="Export CSV", command=self.export_csv).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(top, text="Split for GUI", command=self.split_for_gui).pack(side=tk.LEFT, padx=(6, 0))

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
        controls = ttk.Notebook(left)
        controls.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self._build_axis_controls(controls)
        self._build_budget_controls(controls)
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

    def _build_axis_controls(self, parent) -> None:
        frame = self.ttk.Frame(parent, padding=6)
        parent.add(frame, text="Axes")

        labels = [
            ("Spectrum X min/max", "spec_xmin", "spec_xmax"),
            ("Spectrum Y min/max", "spec_ymin", "spec_ymax"),
            ("Range X min/max", "range_xmin", "range_xmax"),
            ("Range Y min/max", "range_ymin", "range_ymax"),
        ]
        for r, (label, key_min, key_max) in enumerate(labels):
            self.ttk.Label(frame, text=label).grid(row=r, column=0, sticky="w", padx=(0, 6), pady=2)
            self.ttk.Entry(frame, textvariable=self.axis_vars[key_min], width=9).grid(row=r, column=1, sticky="ew", pady=2)
            self.ttk.Entry(frame, textvariable=self.axis_vars[key_max], width=9).grid(row=r, column=2, sticky="ew", pady=2)
        self.ttk.Button(frame, text="Apply", command=self.apply_axis_limits).grid(row=0, column=3, rowspan=2, sticky="nsew", padx=(8, 0))
        self.ttk.Button(frame, text="Auto", command=self.reset_axis_limits).grid(row=2, column=3, rowspan=2, sticky="nsew", padx=(8, 0))
        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(2, weight=1)

    def _build_budget_controls(self, parent) -> None:
        frame = self.ttk.Frame(parent, padding=6)
        parent.add(frame, text="Link Budget")

        entries = [
            ("Iph mA", "photocurrent_ma"),
            ("Ptx dBm", "tx_power_dbm"),
            ("RF GHz", "rf_ghz"),
            ("Gt dBi", "tx_ant_gain_dbi"),
            ("Gr dBi", "rx_ant_gain_dbi"),
            ("LNA dB", "lna_gain_db"),
            ("Drive dB", "drive_amp_gain_db"),
            ("Cable loss dB", "cable_loss_db"),
            ("Homodyne dB", "homodyne_gain_db"),
            ("RCS m^2", "rcs_sqm"),
        ]
        for i, (label, key) in enumerate(entries):
            r = i // 2
            c = (i % 2) * 2
            self.ttk.Label(frame, text=label).grid(row=r, column=c, sticky="w", padx=(0, 4), pady=2)
            entry = self.ttk.Entry(frame, textvariable=self.budget_vars[key], width=9)
            entry.grid(row=r, column=c + 1, sticky="ew", padx=(0, 8), pady=2)
            entry.bind("<Return>", lambda _event: self.update_link_budget())

        self.ttk.Checkbutton(
            frame,
            text="Use Iph -> Ptx",
            variable=self.use_iph_var,
            command=self.update_link_budget,
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(4, 2))
        self.ttk.Button(frame, text="Update", command=self.update_link_budget).grid(row=5, column=2, sticky="ew", padx=(0, 8), pady=(4, 2))
        self.ttk.Button(frame, text="Fit Homodyne", command=self.fit_homodyne_gain).grid(row=5, column=3, sticky="ew", pady=(4, 2))

        self.budget_tree = self.ttk.Treeview(frame, columns=("metric", "value", "unit"), show="headings", height=9)
        for name, label, width in (("metric", "Metric", 160), ("value", "Value", 110), ("unit", "Unit", 65)):
            self.budget_tree.heading(name, text=label)
            self.budget_tree.column(name, width=width, anchor=self.tk.W if name == "metric" else self.tk.CENTER)
        self.budget_tree.grid(row=6, column=0, columnspan=4, sticky="nsew", pady=(6, 0))
        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(3, weight=1)
        frame.rowconfigure(6, weight=1)

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
        self.ax_spectrum.set_xlim([0, 30])
        self.ax_spectrum.grid(True, alpha=0.3)
        self.ax_range.clear()
        self.ax_range.set_title("Range Profile")
        self.ax_range.set_xlabel("Range (mm)")
        self.ax_range.set_ylabel("Profile (dB)")
        self.ax_range.grid(True, alpha=0.3)
        self.plot_data = {}
        self.markers = {}
        self.canvas.draw_idle()

    def _apply_axis_pair(self, ax, xmin_key: str, xmax_key: str, ymin_key: str, ymax_key: str) -> None:
        xmin = optional_float(self.axis_vars[xmin_key].get())
        xmax = optional_float(self.axis_vars[xmax_key].get())
        ymin = optional_float(self.axis_vars[ymin_key].get())
        ymax = optional_float(self.axis_vars[ymax_key].get())
        if xmin is not None or xmax is not None:
            cur = ax.get_xlim()
            ax.set_xlim(xmin if xmin is not None else cur[0], xmax if xmax is not None else cur[1])
        if ymin is not None or ymax is not None:
            cur = ax.get_ylim()
            ax.set_ylim(ymin if ymin is not None else cur[0], ymax if ymax is not None else cur[1])

    def apply_axis_limits(self) -> None:
        self._apply_axis_pair(self.ax_spectrum, "spec_xmin", "spec_xmax", "spec_ymin", "spec_ymax")
        self._apply_axis_pair(self.ax_range, "range_xmin", "range_xmax", "range_ymin", "range_ymax")
        self.canvas.draw_idle()

    def reset_axis_limits(self) -> None:
        for var in self.axis_vars.values():
            var.set("")
        if self.current_row_index is not None:
            self.show_row(self.current_row_index)
        else:
            self.clear_plots()

    def budget_params(self) -> dict[str, float]:
        if self.use_iph_var.get():
            iph = to_float(self.budget_vars["photocurrent_ma"].get())
            if math.isfinite(iph) and iph > 0:
                self.budget_vars["tx_power_dbm"].set(f"{utcpd_output_dbm(iph):.3f}")
        params: dict[str, float] = {}
        defaults = {
            "tx_power_dbm": -10.0,
            "rf_ghz": 280.0,
            "tx_ant_gain_dbi": 25.0,
            "rx_ant_gain_dbi": 25.0,
            "lna_gain_db": 14.0,
            "drive_amp_gain_db": 20.0,
            "cable_loss_db": 0.0,
            "homodyne_gain_db": 0.0,
            "rcs_sqm": 1.0,
        }
        for key, default in defaults.items():
            value = to_float(self.budget_vars[key].get())
            params[key] = value if math.isfinite(value) else default
        return params

    def update_link_budget(self) -> None:
        if not hasattr(self, "budget_tree"):
            return
        self.budget_tree.delete(*self.budget_tree.get_children())
        if self.current_row_index is None or self.current_row_index >= len(self.rows):
            return
        row = self.rows[self.current_row_index]
        try:
            for metric, value, unit in link_budget_from_row(row, self.budget_params()):
                self.budget_tree.insert("", "end", values=(metric, fmt_cell(value, 4), unit))
        except Exception as exc:
            self.budget_tree.insert("", "end", values=("Link budget error", str(exc), ""))

    def fit_homodyne_gain(self) -> None:
        if self.current_row_index is None or self.current_row_index >= len(self.rows):
            return
        row = self.rows[self.current_row_index]
        rows = link_budget_from_row(row, self.budget_params())
        inferred = next((value for metric, value, _unit in rows if metric == "Inferred homodyne gain"), float("nan"))
        inferred_f = to_float(inferred)
        if math.isfinite(inferred_f):
            self.budget_vars["homodyne_gain_db"].set(f"{inferred_f:.3f}")
        self.update_link_budget()

    def on_select_row(self, _event=None) -> None:
        selection = self.summary_tree.selection()
        if not selection:
            return
        self.show_row(int(selection[0]))

    def show_row(self, index: int) -> None:
        if index < 0 or index >= len(self.rows):
            return
        self.current_row_index = index
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
        self.update_link_budget()
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

        self.apply_axis_limits()
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

    def split_for_gui(self) -> None:
        from tkinter import filedialog, messagebox

        folder = Path(self.folder_var.get()).expanduser()
        default_out = folder.parent / f"{folder.name}_gui_split"
        selected = filedialog.askdirectory(
            title="Select output folder for isac_unified_gui.py-compatible files",
            initialdir=str(default_out.parent),
        )
        out_dir = Path(selected) if selected else default_out
        try:
            written = split_folder_for_gui(folder, out_dir)
            self.status_var.set(f"Wrote {len(written)} GUI-compatible file(s): {out_dir}")
            messagebox.showinfo("Split complete", f"Wrote {len(written)} file(s)\n{out_dir}")
        except Exception as exc:
            messagebox.showerror("Split error", str(exc))


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
    parser.add_argument(
        "--split-for-gui",
        type=Path,
        help="Write C1/C2-split .npz files compatible with isac_unified_gui.py Load DSO Capture.",
    )
    args = parser.parse_args()

    if not (args.cli or args.csv or args.profiles_dir or args.list_keys or args.split_for_gui):
        launch_gui(args.input)
        return

    if args.split_for_gui:
        written = split_folder_for_gui(args.input, args.split_for_gui)
        print(f"Wrote {len(written)} GUI-compatible file(s) to {args.split_for_gui}")
        for path in written:
            print(path)
        if not (args.cli or args.csv or args.profiles_dir or args.list_keys):
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
