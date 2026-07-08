#!/usr/bin/env python3
"""Probe DSB/ZBD power fading from repeated DSO captures.

This script is intentionally separate from the GUI.  It answers a narrower
question: does the received IF level move mainly as an amplitude fading process,
or can it be explained by simple frequency wandering?

Typical fixed-IF live run:

    python bench/power_fading_probe.py --host 192.168.1.4 --channel C1 \
        --fc-ghz 10 --bw-ghz 1.0 --n 50 --interval-s 0.5

Typical offline run from GUI-saved captures:

    python bench/power_fading_probe.py --npz data/captures/a.npz data/captures/b.npz \
        --channel C1 --fc-ghz 10 --bw-ghz 1.0

Optional IF-sweep fit from a CSV with columns if_ghz,power_dbm:

    python bench/power_fading_probe.py --sweep-csv if_sweep.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from scipy.optimize import curve_fit
from scipy.signal import welch


APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from functions.dso_functions import create_dso_controller, normalize_dso_type  # noqa: E402


R_LOAD_OHM = 50.0


@dataclass
class CaptureResult:
    label: str
    t_epoch: float
    fs_hz: float
    n_samples: int
    band_power_dbm: float
    lower_power_dbm: float
    upper_power_dbm: float
    centroid_ghz: float
    peak_freq_ghz: float
    noise_floor_dbmhz: float
    rms_dbv: float


def _dbm_from_watt(p_w: float) -> float:
    return 10.0 * np.log10(max(float(p_w), 1e-30) / 1e-3)


def _watt_from_dbm(p_dbm: np.ndarray | float) -> np.ndarray:
    return 1e-3 * np.power(10.0, np.asarray(p_dbm, dtype=np.float64) / 10.0)


def _compute_psd(sig: np.ndarray, fs_hz: float) -> tuple[np.ndarray, np.ndarray]:
    x = np.asarray(sig, dtype=np.float64).reshape(-1)
    if len(x) < 16:
        raise ValueError("Signal is too short for PSD analysis.")
    x = x - float(np.mean(x))
    nperseg = min(131072, max(1024, 2 ** int(np.floor(np.log2(len(x) // 4 or 1)))))
    nperseg = min(nperseg, len(x))
    f_hz, pxx_v2_hz = welch(
        x,
        fs=float(fs_hz),
        window="hann",
        nperseg=nperseg,
        noverlap=nperseg // 2,
        scaling="density",
        detrend=False,
    )
    pxx_w_hz = np.maximum(pxx_v2_hz / R_LOAD_OHM, 1e-30)
    return f_hz, pxx_w_hz


def _integrate_psd_watt(f_hz: np.ndarray, psd_w_hz: np.ndarray, mask: np.ndarray) -> float:
    if len(f_hz) < 2 or not np.any(mask):
        return 0.0
    df_hz = float(np.nanmedian(np.diff(f_hz)))
    return float(np.sum(psd_w_hz[mask]) * max(df_hz, 1.0))


def analyze_capture(
    sig: np.ndarray,
    fs_hz: float,
    fc_ghz: float,
    bw_ghz: float,
    label: str,
    t_epoch: float | None = None,
) -> CaptureResult:
    f_hz, psd_w_hz = _compute_psd(sig, fs_hz)
    fc_hz = float(fc_ghz) * 1e9
    bw_hz = float(bw_ghz) * 1e9
    lo_hz = max(0.0, fc_hz - 0.5 * bw_hz)
    hi_hz = min(0.5 * float(fs_hz), fc_hz + 0.5 * bw_hz)
    if hi_hz <= lo_hz:
        raise ValueError("Invalid analysis band. Check fc/bw/fs.")

    band = (f_hz >= lo_hz) & (f_hz <= hi_hz)
    lower = (f_hz >= lo_hz) & (f_hz < fc_hz)
    upper = (f_hz >= fc_hz) & (f_hz <= hi_hz)
    noise = ((f_hz >= max(0.5e9, hi_hz + 0.5 * bw_hz)) & (f_hz <= 0.5 * float(fs_hz)))
    if np.count_nonzero(noise) < 16:
        noise = ((f_hz >= 0.5e9) & (f_hz <= 0.5 * float(fs_hz)) & ~band)

    band_power_w = _integrate_psd_watt(f_hz, psd_w_hz, band)
    lower_power_w = _integrate_psd_watt(f_hz, psd_w_hz, lower)
    upper_power_w = _integrate_psd_watt(f_hz, psd_w_hz, upper)

    psd_band = psd_w_hz[band]
    f_band = f_hz[band]
    if len(f_band) == 0 or float(np.sum(psd_band)) <= 0:
        centroid_hz = float("nan")
        peak_hz = float("nan")
    else:
        centroid_hz = float(np.sum(f_band * psd_band) / np.sum(psd_band))
        peak_hz = float(f_band[int(np.argmax(psd_band))])

    noise_floor_w_hz = float(np.median(psd_w_hz[noise])) if np.any(noise) else float("nan")
    rms_v = float(np.sqrt(np.mean(np.asarray(sig, dtype=np.float64) ** 2)))
    rms_dbv = 20.0 * np.log10(max(rms_v, 1e-15))

    return CaptureResult(
        label=label,
        t_epoch=float(time.time() if t_epoch is None else t_epoch),
        fs_hz=float(fs_hz),
        n_samples=int(len(sig)),
        band_power_dbm=_dbm_from_watt(band_power_w),
        lower_power_dbm=_dbm_from_watt(lower_power_w),
        upper_power_dbm=_dbm_from_watt(upper_power_w),
        centroid_ghz=centroid_hz / 1e9,
        peak_freq_ghz=peak_hz / 1e9,
        noise_floor_dbmhz=10.0 * np.log10(max(noise_floor_w_hz, 1e-30) / 1e-3),
        rms_dbv=rms_dbv,
    )


def load_npz_signal(path: Path, channel: str) -> tuple[np.ndarray, float]:
    ch = channel.strip().upper()
    with np.load(path, allow_pickle=True) as data:
        sig_key = f"rx__{ch}__sig"
        fs_key = f"rx__{ch}__fs"
        if sig_key in data and fs_key in data:
            return np.asarray(data[sig_key], dtype=np.float64), float(np.asarray(data[fs_key]).reshape(-1)[0])
        if "rx_sig" in data and "rx_fs" in data:
            return np.asarray(data["rx_sig"], dtype=np.float64), float(np.asarray(data["rx_fs"]).reshape(-1)[0])
    raise ValueError(f"No waveform found in {path} for {channel}.")


def capture_live(args: argparse.Namespace) -> list[tuple[str, np.ndarray, float, float]]:
    out = []
    fallback_fs_hz = float(args.fallback_fs_gs) * 1e9
    max_samples = int(args.max_samples) if args.max_samples else None
    with create_dso_controller(
        dso_type=normalize_dso_type(args.dso_type),
        host=args.host,
        timeout_ms=int(args.timeout_ms),
    ) as dso:
        for idx in range(int(args.n)):
            if idx > 0 and float(args.interval_s) > 0:
                time.sleep(float(args.interval_s))
            t0 = time.time()
            try:
                _, sig, fs_hz = dso.capture(
                    channel=args.channel,
                    fallback_fs=fallback_fs_hz,
                    max_samples=max_samples,
                )
            except TypeError:
                _, sig, fs_hz = dso.capture(channel=args.channel, fallback_fs=fallback_fs_hz)
                if max_samples is not None:
                    sig = sig[:max_samples]
            out.append((f"live_{idx + 1:03d}", np.asarray(sig, dtype=np.float64), float(fs_hz), t0))
            print(f"[capture] {idx + 1}/{args.n}: N={len(sig):,}, fs={float(fs_hz)/1e9:.3f} GSa/s")
    return out


def write_results_csv(path: Path, rows: list[CaptureResult]) -> None:
    fields = list(CaptureResult.__dataclass_fields__.keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=fields)
        wr.writeheader()
        for r in rows:
            wr.writerow({k: getattr(r, k) for k in fields})


def _corr(x: np.ndarray, y: np.ndarray) -> float:
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    m = np.isfinite(x) & np.isfinite(y)
    if np.count_nonzero(m) < 3:
        return float("nan")
    return float(np.corrcoef(x[m], y[m])[0, 1])


def summarize_fixed_if(rows: list[CaptureResult], bw_ghz: float) -> dict[str, float | str]:
    p = np.asarray([r.band_power_dbm for r in rows], dtype=np.float64)
    lower = np.asarray([r.lower_power_dbm for r in rows], dtype=np.float64)
    upper = np.asarray([r.upper_power_dbm for r in rows], dtype=np.float64)
    c_mhz = np.asarray([r.centroid_ghz for r in rows], dtype=np.float64) * 1e3
    peak_mhz = np.asarray([r.peak_freq_ghz for r in rows], dtype=np.float64) * 1e3

    level_p2p_db = float(np.nanmax(p) - np.nanmin(p)) if len(p) else float("nan")
    centroid_p2p_mhz = float(np.nanmax(c_mhz) - np.nanmin(c_mhz)) if len(c_mhz) else float("nan")
    peak_p2p_mhz = float(np.nanmax(peak_mhz) - np.nanmin(peak_mhz)) if len(peak_mhz) else float("nan")
    level_centroid_corr = _corr(p, c_mhz)
    lower_upper_corr = _corr(lower, upper)
    bw_mhz = float(bw_ghz) * 1e3

    verdict = "inconclusive"
    if np.isfinite(level_p2p_db) and np.isfinite(centroid_p2p_mhz):
        if level_p2p_db >= 3.0 and centroid_p2p_mhz <= max(50.0, 0.05 * bw_mhz):
            verdict = "supports amplitude/power fading over simple frequency wandering"
        elif centroid_p2p_mhz > 0.15 * bw_mhz and abs(level_centroid_corr) > 0.5:
            verdict = "frequency wandering may be a major contributor"

    return {
        "level_p2p_db": level_p2p_db,
        "centroid_p2p_mhz": centroid_p2p_mhz,
        "peak_freq_p2p_mhz": peak_p2p_mhz,
        "level_centroid_corr": level_centroid_corr,
        "lower_upper_corr": lower_upper_corr,
        "verdict": verdict,
    }


def plot_fixed_if(path: Path, rows: list[CaptureResult], summary: dict[str, float | str]) -> None:
    x = np.arange(1, len(rows) + 1)
    p = np.asarray([r.band_power_dbm for r in rows], dtype=np.float64)
    lower = np.asarray([r.lower_power_dbm for r in rows], dtype=np.float64)
    upper = np.asarray([r.upper_power_dbm for r in rows], dtype=np.float64)
    centroid_mhz = (np.asarray([r.centroid_ghz for r in rows], dtype=np.float64) - np.nanmedian(
        np.asarray([r.centroid_ghz for r in rows], dtype=np.float64)
    )) * 1e3

    fig, axs = plt.subplots(2, 2, figsize=(11, 7), constrained_layout=True)
    axs[0, 0].plot(x, p, "o-", label="in-band power")
    axs[0, 0].set_xlabel("Capture index")
    axs[0, 0].set_ylabel("dBm")
    axs[0, 0].set_title("IF Band Power vs Time")
    axs[0, 0].grid(True, alpha=0.35)

    axs[0, 1].plot(x, centroid_mhz, "o-", color="#7c3aed")
    axs[0, 1].set_xlabel("Capture index")
    axs[0, 1].set_ylabel("MHz from median")
    axs[0, 1].set_title("Spectral Centroid Motion")
    axs[0, 1].grid(True, alpha=0.35)

    axs[1, 0].plot(x, lower, "o-", label="lower half")
    axs[1, 0].plot(x, upper, "o-", label="upper half")
    axs[1, 0].set_xlabel("Capture index")
    axs[1, 0].set_ylabel("dBm")
    axs[1, 0].set_title("Lower/Upper IF Half-Band Powers")
    axs[1, 0].legend()
    axs[1, 0].grid(True, alpha=0.35)

    axs[1, 1].scatter(centroid_mhz, p, s=28)
    axs[1, 1].set_xlabel("Centroid offset (MHz)")
    axs[1, 1].set_ylabel("Band power (dBm)")
    axs[1, 1].set_title(
        f"Power vs Frequency Motion\n"
        f"level p-p={summary['level_p2p_db']:.2f} dB, "
        f"centroid p-p={summary['centroid_p2p_mhz']:.1f} MHz"
    )
    axs[1, 1].grid(True, alpha=0.35)
    fig.suptitle(str(summary.get("verdict", "inconclusive")))
    fig.savefig(path, dpi=180)
    plt.close(fig)


def read_sweep_csv(path: Path) -> tuple[np.ndarray, np.ndarray]:
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError("Sweep CSV is empty.")
    keys = {k.lower().strip(): k for k in rows[0].keys()}
    f_key = keys.get("if_ghz") or keys.get("fc_ghz") or keys.get("freq_ghz") or keys.get("frequency_ghz")
    p_key = keys.get("power_dbm") or keys.get("band_power_dbm") or keys.get("rx_power_dbm")
    if not f_key or not p_key:
        raise ValueError("Sweep CSV needs columns if_ghz and power_dbm.")
    f_ghz = np.asarray([float(r[f_key]) for r in rows], dtype=np.float64)
    p_dbm = np.asarray([float(r[p_key]) for r in rows], dtype=np.float64)
    return f_ghz, p_dbm


def fit_dsb_sweep(f_ghz: np.ndarray, p_dbm: np.ndarray) -> dict[str, float]:
    f_hz = np.asarray(f_ghz, dtype=np.float64) * 1e9
    p_mw = np.maximum(_watt_from_dbm(p_dbm) / 1e-3, 1e-15)

    def model(f_hz_: np.ndarray, p0_mw: float, ripple_mw: float, tau_ns: float, phi: float) -> np.ndarray:
        tau_s = tau_ns * 1e-9
        return p0_mw + ripple_mw * np.cos(2.0 * np.pi * f_hz_ * tau_s + phi)

    p0 = float(np.mean(p_mw))
    ripple = max(1e-9, 0.5 * float(np.max(p_mw) - np.min(p_mw)))
    best = None
    for tau0_ns in np.geomspace(0.02, 50.0, 80):
        try:
            popt, _ = curve_fit(
                model,
                f_hz,
                p_mw,
                p0=[p0, ripple, float(tau0_ns), 0.0],
                bounds=([1e-12, -10.0 * p0, 0.001, -4.0 * np.pi],
                        [10.0 * p0, 10.0 * p0, 200.0, 4.0 * np.pi]),
                maxfev=20000,
            )
            pred = model(f_hz, *popt)
            mse = float(np.mean((p_mw - pred) ** 2))
            if best is None or mse < best[0]:
                best = (mse, popt, pred)
        except Exception:
            continue
    if best is None:
        raise RuntimeError("Could not fit DSB sweep model.")
    _, popt, pred_mw = best
    pred_dbm = _dbm_from_watt(pred_mw * 1e-3)
    ripple_p2p_db = float(np.nanmax(p_dbm) - np.nanmin(p_dbm))
    return {
        "p0_mw": float(popt[0]),
        "ripple_mw": float(popt[1]),
        "tau_ns": float(popt[2]),
        "phi_rad": float(popt[3]),
        "ripple_p2p_db": ripple_p2p_db,
        "fit_rmse_db": float(np.sqrt(np.mean((np.asarray(p_dbm) - pred_dbm) ** 2))),
    }


def plot_sweep_fit(path: Path, f_ghz: np.ndarray, p_dbm: np.ndarray, fit: dict[str, float]) -> None:
    f_dense = np.linspace(float(np.min(f_ghz)), float(np.max(f_ghz)), 1000)
    f_hz = f_dense * 1e9
    p0_mw = fit["p0_mw"]
    ripple_mw = fit["ripple_mw"]
    tau_s = fit["tau_ns"] * 1e-9
    phi = fit["phi_rad"]
    pred_mw = p0_mw + ripple_mw * np.cos(2.0 * np.pi * f_hz * tau_s + phi)
    pred_dbm = _dbm_from_watt(np.maximum(pred_mw, 1e-15) * 1e-3)

    fig, ax = plt.subplots(figsize=(8, 4.5), constrained_layout=True)
    ax.plot(f_ghz, p_dbm, "o", label="measured")
    ax.plot(f_dense, pred_dbm, "-", label=f"DSB fading fit, tau={fit['tau_ns']:.3g} ns")
    ax.set_xlabel("IF frequency (GHz)")
    ax.set_ylabel("Band power (dBm)")
    ax.set_title(f"IF Sweep Power Fading Fit, ripple={fit['ripple_p2p_db']:.2f} dB")
    ax.grid(True, alpha=0.35)
    ax.legend()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="", help="DSO host for live repeated captures.")
    ap.add_argument("--dso-type", default="keysight_uxr")
    ap.add_argument("--timeout-ms", type=int, default=10000)
    ap.add_argument("--channel", default="C1")
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--interval-s", type=float, default=0.5)
    ap.add_argument("--fallback-fs-gs", type=float, default=64.0)
    ap.add_argument("--max-samples", type=int, default=262144)
    ap.add_argument("--npz", nargs="*", default=[], help="GUI-saved capture NPZ files.")
    ap.add_argument("--fc-ghz", type=float, default=10.0, help="IF center frequency to analyze.")
    ap.add_argument("--bw-ghz", type=float, default=1.0, help="Integrated IF bandwidth.")
    ap.add_argument("--sweep-csv", default="", help="Optional IF sweep CSV with if_ghz,power_dbm.")
    ap.add_argument("--out-dir", default=str(APP_DIR / "data" / "power_fading"))
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")

    rows: list[CaptureResult] = []
    if args.npz:
        for path_s in args.npz:
            path = Path(path_s)
            sig, fs_hz = load_npz_signal(path, args.channel)
            rows.append(analyze_capture(sig, fs_hz, args.fc_ghz, args.bw_ghz, label=path.stem))
    elif args.host:
        for label, sig, fs_hz, t_epoch in capture_live(args):
            rows.append(analyze_capture(sig, fs_hz, args.fc_ghz, args.bw_ghz, label=label, t_epoch=t_epoch))

    if rows:
        csv_path = out_dir / f"power_fading_fixed_if_{stamp}.csv"
        png_path = out_dir / f"power_fading_fixed_if_{stamp}.png"
        write_results_csv(csv_path, rows)
        summary = summarize_fixed_if(rows, args.bw_ghz)
        plot_fixed_if(png_path, rows, summary)
        print("[fixed-if] saved:", csv_path)
        print("[fixed-if] saved:", png_path)
        print("[fixed-if] summary:")
        for k, v in summary.items():
            print(f"  {k}: {v}")

    if args.sweep_csv:
        f_ghz, p_dbm = read_sweep_csv(Path(args.sweep_csv))
        fit = fit_dsb_sweep(f_ghz, p_dbm)
        png_path = out_dir / f"power_fading_if_sweep_fit_{stamp}.png"
        plot_sweep_fit(png_path, f_ghz, p_dbm, fit)
        print("[if-sweep] saved:", png_path)
        print("[if-sweep] fit:")
        for k, v in fit.items():
            print(f"  {k}: {v}")

    if not rows and not args.sweep_csv:
        ap.error("Use --host for live capture, --npz for offline captures, or --sweep-csv for IF sweep fitting.")


if __name__ == "__main__":
    main()
