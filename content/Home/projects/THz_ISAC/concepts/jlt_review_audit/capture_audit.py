"""Reprocess trusted local DSO NPZ captures and preserve acquisition provenance."""

import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import scipy
from scipy.signal import fftconvolve


OUT = Path(__file__).resolve().parent
ROOT = OUT.parent
CODE = ROOT / "content/Home/projects/THz_ISAC/code"
sys.path.insert(0, str(CODE))

from functions.dsp_functions import hard_bits_from_symbols
from isac_gui import DsoPanel as LegacyDsoPanel
from isac_gui_v2 import DsoPanel, calc_utcpd_output_dbm
from read_range_data import metric_map, to_float, unpack


C = 3e8
SECTIONS = ("bandwidth", "range_1100mm", "photocurrent")


def sha256(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def write_csv(name, rows):
    with (OUT / name).open("w", newline="", encoding="utf-8") as f:
        columns = list(dict.fromkeys(key for row in rows for key in row))
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def stored(z, key, otherwise=None):
    return unpack(z[key]) if key in z.files else otherwise


def reference_mode(pl):
    tx = pl["tx_bb_matrix"]
    pilot = pl["dft_zc_pilot"]
    coeffs = np.empty((len(tx), 2), dtype=complex)
    errors = np.empty(len(tx))
    for i, symbols in enumerate(pl["tx_sym_matrix"]):
        spectrum = np.zeros(tx.shape[1], dtype=complex)
        spectrum[pl["dft_active_bins"]] = np.fft.fft(symbols) / np.sqrt(len(symbols))
        data = np.fft.ifft(spectrum) / pl["dft_data_scale"][i]
        basis = np.column_stack((pilot, data))
        coeffs[i] = np.linalg.lstsq(basis, tx[i], rcond=None)[0]
        errors[i] = np.linalg.norm(tx[i] - basis @ coeffs[i]) / np.linalg.norm(tx[i])
    weights = np.mean(np.abs(coeffs) ** 2, axis=0)
    return weights[0] / weights.sum(), errors.max()


def c1_ber(raw, fs, pl):
    panel = object.__new__(LegacyDsoPanel)
    panel._log = lambda _: None
    bb, fs_ref = panel._rx_to_baseband(raw, fs, pl)
    rx, _, _, _, _, _, sps, _, _ = panel._frame_sync_and_reshape(bb, fs_ref, pl)
    est, ref, _ = panel._recover_dfts_ofdm_symbols(rx, pl)
    mod = pl["modulation"]
    ref_eq, est_eq, _, evm = panel._equalize_reference_candidates(
        est, ref, modulation=mod, sc_fde_taps=pl["offline_fde_taps"], sc_fde_enable=True,
        max_lag=max(4, int(sps)),
    )
    ref_bits = hard_bits_from_symbols(ref_eq, mod)
    est_bits = hard_bits_from_symbols(est_eq, mod)
    return len(ref_bits), int(np.count_nonzero(ref_bits != est_bits)), float(20 * np.log10(evm))


def delay_sum(freq, h, grid):
    return np.concatenate([
        np.exp(2j * np.pi * np.outer(grid[i:i + 160] / (C / 2), freq)) @ h / len(h)
        for i in range(0, len(grid), 160)
    ])


def profile_stats(grid, power, center, cell):
    roi = np.flatnonzero(np.abs(grid - center) <= 0.04)
    peak = roi[np.argmax(power[roi])]
    fixed = int(np.argmin(np.abs(grid - center)))
    floor = (grid >= 0.5) & (grid <= 2) & (np.abs(grid - center) > 2 * cell)
    paper_floor = (grid >= 0.5) & (grid <= 2) & (np.abs(grid - grid[peak]) > 2 * cell)
    median, mean = np.median(power[floor]), np.mean(power[floor])
    paper_median = np.median(power[paper_floor])

    def excess(ratio):
        return float(10 * np.log10(ratio - 1)) if ratio > 1 else None

    return dict(
        guided_peak_m=grid[peak], fixed_grid_m=grid[fixed], roi_grid_points=len(roi),
        floor_grid_points=int(np.sum(paper_floor)),
        raw_peak_power=power[peak], paper_mask_median_power=paper_median,
        common_mask_median_power=median, common_mask_mean_power=mean,
        guided_contrast_db=10 * np.log10(power[peak] / paper_median),
        eq19_db=excess(power[peak] / paper_median),
        fixed_eq19_db=excess(power[fixed] / median),
        guided_common_mask_eq19_db=excess(power[peak] / median),
        guided_common_mask_mean_excess_db=excess(power[peak] / mean),
        fixed_common_mask_mean_excess_db=excess(power[fixed] / mean),
        floor_mean_over_median_db=10 * np.log10(mean / median),
        guided_over_fixed_db=10 * np.log10(power[peak] / power[fixed]),
    )


def process_capture(path, group):
    relative = path.relative_to(CODE).as_posix()
    with np.load(path, allow_pickle=True) as z:
        pl = {k[4:]: unpack(z[k]) for k in z.files if k.startswith("tx__")}
        sig = z["rx__C2__sig"]
        c1 = z["rx__C1__sig"]
        t1, t2 = z["rx__C1__t"], z["rx__C2__t"]
        fs1 = float(stored(z, "rx__C1__fs"))
        fs2 = float(stored(z, "rx__C2__fs"))
        metrics = metric_map(z)
        saved_evm = to_float(metrics.get("evm_db", {}).get("value", "nan"))
        saved_ber = to_float(metrics.get("ber", {}).get("value", "nan"))
        saved_zero = stored(z, "range_zero__C2__profile_center_m")
        diff = None
        saved_c2_peak = None
        if "range_summary_channels" in z.files and "range_summary_diff_range_mm" in z.files:
            channel_idx = np.flatnonzero(z["range_summary_channels"] == "C2")
            if len(channel_idx):
                value = z["range_summary_diff_range_mm"][channel_idx[0]]
                diff = value if np.isfinite(value) else None
                saved_c2_peak = z["range_summary_peak_m"][channel_idx[0]]
        created = stored(z, "created")
        current = float(stored(z, "photocurrent_ma"))
        repeats = [key for key in z.files if key.startswith("repeat__")]
        fde_taps = int(stored(z, "dsp__sc_fde_taps", 1))
        zero_profile = None
        if all(key in z.files for key in ("range_zero__C2__profile_lags", "range_zero__C2__profile_prof_db", "range_zero__C2__profile_fs")):
            zero_profile = (
                z["range_zero__C2__profile_lags"] / float(stored(z, "range_zero__C2__profile_fs")) * (C / 2),
                z["range_zero__C2__profile_prof_db"],
            )

    panel = object.__new__(DsoPanel)
    panel._log = lambda _: None
    bb, fs_ref = panel._rx_to_baseband(sig, fs2, pl)
    rx, tx, _, _, n_rows, _, _, _, start = panel._frame_sync_and_reshape(bb, fs_ref, pl)
    if rx.shape != tx.shape:
        raise ValueError(f"Unmatched RX and TX block shapes in {relative}")
    bins = pl["dft_active_bins"]
    nfft = int(pl["dft_n_fft"])
    signed_bins = (bins + nfft // 2) % nfft - nfft // 2
    bandwidth = len(bins) * fs_ref / nfft
    pilot_fraction, fit_error = reference_mode(pl)
    n_ref, n_block_samples = pl["tx_bb_matrix"].shape
    gap = len(pl["tx_signal"]) - n_ref * nfft
    tx_sequence_error = np.max(np.abs(pl["tx_signal"] - pl["tx_bb_matrix"].ravel())) if gap == 0 else None
    awg_sequence = pl["awg_sig"]
    expected_awg = np.real(pl["tx_signal"] * np.exp(2j * np.pi * pl["iqtools_if_freq"] * np.arange(len(pl["tx_signal"])) / pl["fs"]))
    if len(awg_sequence) == len(expected_awg):
        awg_gain = np.dot(awg_sequence, expected_awg) / np.dot(expected_awg, expected_awg)
        awg_error = np.linalg.norm(awg_sequence - awg_gain * expected_awg) / np.linalg.norm(awg_sequence)
    else:
        awg_error = None
    center = 1.10 if group == "range_1100mm" else (1.014 if group == "photocurrent" else 1.0)
    if group == "bandwidth" and int(round(bandwidth / 1e9)) == 20 and pl["modulation"] == "32QAM":
        center = 1.005  # Fig. 8 reported moved location, fixed before C2 profile inspection.
    pl["offline_fde_taps"] = fde_taps
    count, errors, evm = c1_ber(c1, fs1, pl)
    row = dict(
        dataset=group, file=relative, sha256=sha256(path), exported_at=created,
        modulation=pl["modulation"], symbol_rate_gbaud=float(pl["symbol_rate_actual"]) / 1e9,
        occupied_bin_count=len(bins), occupied_bandwidth_ghz=bandwidth / 1e9,
        occupied_first_bin=int(signed_bins.min()), occupied_last_bin=int(signed_bins.max()),
        if_ghz=float(pl["iqtools_if_freq"]) / 1e9,
        rf_ghz=float(pl["fc"]) / 1e9, c1_dso_fs_gsa=fs1 / 1e9, c2_dso_fs_gsa=fs2 / 1e9,
        fft_fs_gsa=fs_ref / 1e9, c1_samples=len(c1), c2_samples=len(sig),
        c2_minus_c1_start_ps=(t2[0] - t1[0]) * 1e12,
        max_c1_c2_step_difference_ps=np.max(np.abs(np.diff(t2) - np.diff(t1))) * 1e12,
        nfft=nfft, c1_raw_sha256=hashlib.sha256(c1.tobytes()).hexdigest(), c2_raw_sha256=hashlib.sha256(sig.tobytes()).hexdigest(),
        subcarrier_spacing_mhz=fs_ref / nfft / 1e6, block_ns=nfft / fs_ref * 1e9,
        range_cell_mm=C / (2 * bandwidth) * 1e3, tx_reference_rows=n_ref,
        c2_dsp_rows=n_rows, c2_frame_start_sample=start, bb_row_samples=n_block_samples,
        tx_frame_samples=len(pl["tx_signal"]), awg_samples=len(awg_sequence),
        tx_samples_beyond_fft_rows=gap, tx_flatten_max_abs_error=tx_sequence_error,
        awg_reconstruction_rel_error=awg_error, excess_samples_per_row=n_block_samples - nfft,
        rho_metadata=pl["amplitude_ratio_rho"], fitted_pilot_component_power_fraction=pilot_fraction,
        waveform_fit_max_rel_error=fit_error, photocurrent_ma=current,
        awg_ch1_dbm=pl["awg_ch1_power_dbm"], fde_taps_saved=fde_taps,
        stored_c1_evm_db=saved_evm, stored_c1_ber=saved_ber, reprocessed_c1_evm_db=evm,
        c1_hard_bits=count, c1_hard_errors=errors, c1_reference_aided_ber=errors / count,
        c1_voltage_rms_v=float(np.std(c1)), c2_voltage_rms_v=float(np.std(sig)), range_zero_saved_c2_m=saved_zero,
        range_peak_saved_c2_m=saved_c2_peak, range_diff_saved_c2_mm=diff, repeat_keys=len(repeats),
        nominal_roi_center_m=center,
    )

    grid = np.arange(1601) * 0.00125
    lags = np.rint(grid * fs_ref / (C / 2)).astype(int)
    freq, h, _ = panel._estimate_lfm_cfr(rx, tx, fs_ref, 1e-3)
    scalar = np.mean(h)
    if abs(scalar) <= 1e-15:
        raise ValueError(f"Unresolved scalar CFR reference in {relative}")
    raw = delay_sum(freq, h, grid)
    kernel = delay_sum(freq, np.ones(len(freq)), grid)
    mf = np.mean([np.abs(fftconvolve(y, x.conj()[::-1])[nfft - 1 + lags]) ** 2 for x, y in zip(tx, rx)], axis=0)
    legacy_pilot = LegacyDsoPanel._dfts_ofdm_pilot_matrix(pl, n_rows)
    legacy_mf = np.mean([np.abs(fftconvolve(y, x.conj()[::-1])[nfft - 1 + lags]) ** 2 for x, y in zip(legacy_pilot, rx)], axis=0)
    power = {
        "matched_filter_full_tx": mf,
        "raw_cfr": np.abs(raw) ** 2,
        "scalar_division_only": np.abs(raw / scalar) ** 2,
        "scalar_and_baseline": np.abs(raw / scalar - kernel) ** 2,
        "matched_filter_legacy_pilot": legacy_mf,
    }
    results = []
    for method, values in power.items():
        stats = profile_stats(grid, values, center, C / (2 * bandwidth))
        results.append(dict(dataset=group, file=relative, method=method, center_m=center,
                            cfr_bins=len(freq), cfr_scalar_magnitude=abs(scalar), **stats))
    assert abs(results[1]["guided_contrast_db"] - results[2]["guided_contrast_db"]) < 1e-9
    return row, results, (grid, power, zero_profile)


def make_plots(inventory, profiles):
    figs = OUT / "figures"
    figs.mkdir(exist_ok=True)
    style = {"16QAM": ("#176B87", "o"), "32QAM": ("#AC4E22", "s")}
    fig, ax = plt.subplots(figsize=(6.4, 3.5), layout="constrained")
    for mod, (color, marker) in style.items():
        rows = sorted((x for x in inventory if x["dataset"] == "bandwidth" and x["modulation"] == mod),
                      key=lambda x: x["symbol_rate_gbaud"])
        ax.plot([x["symbol_rate_gbaud"] for x in rows], [x["reprocessed_c1_evm_db"] for x in rows],
                marker=marker, lw=1.4, color=color, label=mod)
    ax.axhline(-15.75, color="0.35", ls=":", label="32-QAM AWGN-equivalent criterion")
    ax.set(xlabel="Symbol rate (GBd)", ylabel="Reference-aided C1 EVM (dB)",
           xticks=[2, 4, 8, 10, 12, 15, 17, 20])
    ax.grid(alpha=0.18)
    ax.legend(fontsize=8)
    fig.savefig(figs / "bandwidth_evm.png", dpi=220)
    plt.close(fig)

    for key, name in [("range_1100mm", "fig6_candidate_processing"), ("bandwidth", "fig8_candidate_profile")]:
        grid, powers, zero_profile = profiles[key]
        fig, ax = plt.subplots(figsize=(6.4, 3.5), layout="constrained")
        if key == "bandwidth" and zero_profile is not None:
            x, y = zero_profile
            baseline = (x > 0.965) & (x < 1.055)
            ax.plot(x[baseline] * 1000, y[baseline] - y[baseline].max(), color="0.4", ls="--",
                    label="Saved reference matched filter")
        lo, hi = (0.90, 1.35) if key == "range_1100mm" else (0.965, 1.055)
        shown = (grid >= lo) & (grid <= hi)
        for method, label, color in (
            ("matched_filter_full_tx", "Reprocessed matched filter", "#176B87"),
            ("scalar_and_baseline", "Reprocessed normalized CFR", "#AC4E22"),
        ):
            p = powers[method]
            ax.plot(grid[shown] * 1000, 10 * np.log10(p[shown] / p[shown].max()), color=color, lw=1.1, label=label)
        if key == "bandwidth":
            p = powers["matched_filter_legacy_pilot"]
            ax.plot(grid[shown] * 1000, 10 * np.log10(p[shown] / p[shown].max()), color="#39795F", lw=1.1,
                    label="Reprocessed pilot matched filter")
        ax.set(xlabel="Range on SI-aligned sample grid (mm)", ylabel="Relative profile power (dB)", ylim=(-42, 2))
        ax.grid(alpha=0.18)
        ax.legend(fontsize=8, loc="lower left")
        fig.savefig(figs / f"{name}.png", dpi=220)
        plt.close(fig)

    fig, (ax_evm, ax_cfr) = plt.subplots(1, 2, figsize=(8.0, 3.4), layout="constrained")
    electrical = {x["file"]: x for x in profiles["photocurrent"]}
    for mod, (color, marker) in style.items():
        rows = sorted((x for x in inventory if x["dataset"] == "photocurrent" and x["modulation"] == mod),
                      key=lambda x: x["photocurrent_ma"])
        current = [x["photocurrent_ma"] for x in rows]
        ax_evm.plot(current, [x["reprocessed_c1_evm_db"] for x in rows], marker=marker, color=color, label=mod)
        ax_cfr.plot(current, [electrical[x["file"]]["c2_cfr_contrast_db"] for x in rows], marker=marker, color=color, label=mod)
    ax_evm.set(xlabel="Photocurrent (mA)", ylabel="C1 EVM (dB)")
    ax_cfr.set(xlabel="Photocurrent (mA)", ylabel="C2 target-to-median contrast (dB)")
    for ax in (ax_evm, ax_cfr):
        ax.grid(alpha=0.18)
        ax.legend(fontsize=8)
    fig.savefig(figs / "photocurrent_reprocessing.png", dpi=220)
    plt.close(fig)


def main():
    inventory, ablation, figures = [], [], {}
    for group in SECTIONS:
        for path in sorted((CODE / "data/captures" / group).glob("Data*.npz")):
            row, results, profile = process_capture(path, group)
            inventory.append(row)
            ablation.extend(results)
            if (group == "range_1100mm" and path.name.startswith("Data_range")) or (
                group == "bandwidth" and row["modulation"] == "32QAM" and np.isclose(row["symbol_rate_gbaud"], 20)
            ):
                figures[group] = profile
            print(f"{group} {path.name} EVM {row['reprocessed_c1_evm_db']:.3f} dB", flush=True)
    write_csv("capture_inventory.csv", inventory)
    write_csv("processing_ablation.csv", ablation)
    cfr_by_file = {x["file"]: x for x in ablation if x["method"] == "scalar_and_baseline"}
    for group, name in [("photocurrent", "photocurrent_analysis.csv"), ("range_1100mm", "range_candidates.csv")]:
        rows = [dict(
            file=x["file"], modulation=x["modulation"], current_ma=x["photocurrent_ma"],
            modeled_utc_pd_power_dbm=calc_utcpd_output_dbm(x["photocurrent_ma"]),
            c1_evm_db=x["reprocessed_c1_evm_db"], c1_reference_aided_ber=x["c1_reference_aided_ber"],
            c2_voltage_rms_v=x["c2_voltage_rms_v"], c2_cfr_peak_m=cfr_by_file[x["file"]]["guided_peak_m"],
            c2_cfr_contrast_db=cfr_by_file[x["file"]]["guided_contrast_db"],
            c2_cfr_mean_excess_db=cfr_by_file[x["file"]]["guided_common_mask_mean_excess_db"],
        ) for x in inventory if x["dataset"] == group]
        write_csv(name, rows)
        if group == "photocurrent":
            figures[group] = rows
    duplicates = []
    for path in sorted((CODE / "data/range").glob("*.npz")):
        with np.load(path, allow_pickle=False) as z:
            if not all(key in z.files for key in ("rx__C1__sig", "rx__C2__sig")):
                continue
            hashes = [hashlib.sha256(z[f"rx__{ch}__sig"].tobytes()).hexdigest() for ch in ("C1", "C2")]
            matches = [x["file"] for x in inventory if (x["c1_raw_sha256"], x["c2_raw_sha256"]) == tuple(hashes)]
        duplicates.append(dict(file=path.relative_to(CODE).as_posix(), sha256=sha256(path),
                               raw_c1_sha256=hashes[0], raw_c2_sha256=hashes[1], identical_pair_in_scope="; ".join(matches)))
    write_csv("additional_range_inventory.csv", duplicates)
    make_plots(inventory, figures)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    model_revision = subprocess.check_output(["git", "log", "-1", "--format=%H", "--", str(CODE / "isac_gui_v2.py")], cwd=ROOT, text=True).strip()
    manifest = dict(
        date_local="2026-11-18", timezone="Asia/Seoul", git_head=revision, v2_file_revision=model_revision,
        code_sha256={str(p.relative_to(ROOT)): sha256(p) for p in (Path(__file__), CODE / "isac_gui.py", CODE / "isac_gui_v2.py", CODE / "remeasure_cpe_evm.py", CODE / "read_range_data.py", CODE / "functions/dsp_functions.py")},
        attachment_sha256={name: sha256(Path.home() / "Downloads" / name) for name in ("2026_TVT_SI_reuse_THz_ISAC.pdf", "JLT_revision_response_plan.docx", "JLT_review_response_Codex_handoff.md")},
        versions=dict(python=sys.version.split()[0], numpy=np.__version__, scipy=scipy.__version__, matplotlib=matplotlib.__version__),
        commands=["python -B jlt_review_audit/capture_audit.py", "python -B jlt_review_audit/model_audit.py",
                  "python -B content/Home/projects/THz_ISAC/code/remeasure_cpe_evm.py --modulation 32QAM --out jlt_review_audit/evm_32qam.csv",
                  "python -B content/Home/projects/THz_ISAC/code/remeasure_cpe_evm.py --modulation 16QAM --out jlt_review_audit/evm_16qam.csv"],
        capture_reprocessing_seed=None, synthetic_seed=20261118, v2_baseline_seed=0,
        capture_counts={g: sum(row["dataset"] == g for row in inventory) for g in SECTIONS},
        scoped_input_hashes="capture_inventory.csv", measurements="offline reprocessing only",
    )
    (OUT / "run_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
