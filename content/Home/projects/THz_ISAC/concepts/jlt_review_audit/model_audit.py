"""Independent complex-envelope checks and the original Table I calculation."""

from dataclasses import asdict, replace
import csv
import json

import numpy as np
from scipy.optimize import brentq
from scipy.signal import fftconvolve
from scipy.stats import ncx2

from capture_audit import C, CODE, OUT, plt, sha256, write_csv
from functions.dsp_functions import bits_to_qam_symbols, hard_bits_from_symbols
from isac_gui_v2 import SimConfig, run_isac_sim


SEED = 20261118
FS = 120e9
IF = 11e9
M2 = 10 ** (-13 / 10)
M = np.sqrt(M2)
N = 10 ** (-63 / 10)
FLOOR = 10 ** (-89 / 10)
GP = 10 ** (30.1 / 10)
KAPPA = 0.06
L = 10 ** (2.3 / 10)
G = 10 ** (33 / 10)
WAVELENGTH = C / 280e9


def db(value):
    return 10 * np.log10(value)


def delay(x, samples):
    if samples == 0:
        return x.copy()
    if float(samples).is_integer():
        samples = int(samples)
        return np.pad(x, (samples, 0))[:len(x)]
    # Zero extension prevents end-to-start interference in the retained stream.
    n = 1 << int(np.ceil(np.log2(2 * len(x))))
    freq = np.fft.fftfreq(n)
    return np.fft.ifft(np.fft.fft(x, n) * np.exp(-2j * np.pi * freq * samples))[:len(x)]


def known_frame():
    path = next((CODE / "data/captures/range_1100mm").glob("Data_range*Iph7.npz"))
    with np.load(path, allow_pickle=False) as z:
        return z["tx__tx_bb_matrix"], z["tx__dft_active_bins"]


def paper_link(r, power_dbm, rcs_dbsm):
    tx = 10 ** (power_dbm / 10)
    sigma = 10 ** (rcs_dbsm / 10)
    return (tx * G**2 * WAVELENGTH**2 * sigma / ((4 * np.pi)**3 * L**2 * r**4),
            tx * G**2 * WAVELENGTH**2 / ((4 * np.pi)**2 * L**2 * r**2))


def sensing(si, echo):
    return GP * 2 * M2 * (si * echo + echo**2) / (FLOOR + 2 * N * (si + echo) + KAPPA * M2**2 * si**2)


def nominal_curves():
    p_si_dbm = np.linspace(-60, -20, 161)
    p_si = 10 ** (p_si_dbm / 10)
    echo, _ = paper_link(1.0, -10, -10)
    with_si = db(sensing(p_si, echo))
    weak = db(GP * 2 * M2 * p_si * echo / FLOOR)
    ideal_without_si = float(db(sensing(0.0, echo)))
    write_csv("fig2_table_i.csv", [dict(lna_si_dbm=x, sensing_eq12_db=y, weak_echo_fixed_floor_eq14_db=w,
                                       echo_only_eq13_db=ideal_without_si, zbd_input_dbm_loss_1dB=x + 12,
                                       zbd_input_dbm_loss_2dB=x + 11)
                                   for x, y, w in zip(p_si_dbm, with_si, weak)])
    fig, ax = plt.subplots(figsize=(5.5, 3.5), layout="constrained")
    ax.plot(p_si_dbm, with_si, label="Eq. (12)")
    ax.plot(p_si_dbm, weak, ls="--", color="0.5", label="Eq. (14)")
    ax.axhline(ideal_without_si, ls=":", color="#AC4E22", label="Echo only")
    ax.axvspan(-32, -20, color="#AC4E22", alpha=0.14, label="ZBD average bound reached (1 dB loss)")
    ax.axvline(-35, color="0.3", ls=":")
    ax.axhline(13.2, color="0.3", ls="-.", lw=0.9)
    ax.set(xlabel="SI carrier power at LNA input (dBm)", ylabel="Modeled sensing SINR (dB)", xlim=(-60, -20))
    ax.legend(fontsize=7)
    fig.savefig(OUT / "figures/fig2_table_i_headroom.png", dpi=220)
    plt.close(fig)

    ranges = np.geomspace(0.02, 100, 30000)
    rows_rcs = []
    fig, axes = plt.subplots(1, 2, figsize=(8, 3.5), layout="constrained", sharey=True)
    for ax, pt in zip(axes, (-10.0, 0.0)):
        for rcs in np.linspace(-30, 0, 121):
            echo, rx = paper_link(ranges, pt, rcs)
            si = 10 ** ((pt - 25) / 10)
            comm = 2 * M2 * rx**2 / (FLOOR + 2 * N * rx + KAPPA * M2**2 * rx**2)
            rc = np.interp(15.75, db(comm)[::-1], ranges[::-1])
            rw = np.interp(13.2, db(sensing(si, echo))[::-1], ranges[::-1])
            ro = np.interp(13.2, db(sensing(0, echo))[::-1], ranges[::-1])
            rows_rcs.append(dict(carrier_tx_dbm=pt, rcs_dbsm=rcs, comm_m=rc, sensing_si_m=rw,
                                 sensing_echo_only_m=ro, joint_m=min(rc, rw)))
        panel = [x for x in rows_rcs if x["carrier_tx_dbm"] == pt]
        for key, label, color, line in (("comm_m", "Communication", "#176B87", ":"),
                                         ("sensing_si_m", "Sensing with SI", "#AC4E22", "-"),
                                         ("sensing_echo_only_m", "Echo-only sensing", "#39795F", "--"),
                                         ("joint_m", "Joint ISAC", "black", "-.")):
            ax.semilogy([x["rcs_dbsm"] for x in panel], [x[key] for x in panel], line, color=color, label=label)
        ax.set(xlabel="Effective RCS (dBsm)", title=f"TX carrier power {pt:g} dBm", ylim=(0.1, 5))
    axes[0].set_ylabel("Calculated maximum range (m)")
    axes[1].legend(fontsize=7)
    fig.savefig(OUT / "figures/fig3_table_i.png", dpi=220)
    plt.close(fig)
    write_csv("fig3_table_i.csv", rows_rcs)


def boundary_audit(tx, bins):
    _, n = tx.shape
    freq = np.fft.fftfreq(n)[bins]
    tx_f = np.fft.fft(tx, axis=-1)[:, bins]
    n_delay = np.arange(-1024, 1201) / FS
    detect = np.exp(2j * np.pi * np.outer(n_delay * FS, freq)) / len(freq)
    rows = []
    for tau in (0, 480, 800, 880.5, 1024):
        ideal = np.exp(-2j * np.pi * freq * tau)
        for cp in (0, 800, 1024):
            stream = np.column_stack((tx[:, -cp:], tx)).ravel() if cp else tx.ravel()
            shifted = delay(stream, tau).reshape(len(tx), n + cp)[:, cp:]
            y = np.fft.fft(shifted[1:], axis=-1)[:, bins]
            x = tx_f[1:]
            h = np.sum(y * x.conj(), axis=0) / np.sum(np.abs(x)**2, axis=0)
            err = np.sum(np.abs(y - x * ideal) ** 2) / np.sum(np.abs(x * ideal) ** 2)
            estimate = n_delay[np.argmax(np.abs(detect @ h))] * FS
            rows.append(dict(kind="blockwise_fft", cp_samples=cp, true_delay_samples=tau,
                             unguarded_leading_samples=max(0, int(np.ceil(tau)) - cp),
                             individual_blocks_model_nmse=err,
                             combined_cfr_nmse=np.mean(np.abs(h - ideal)**2),
                             estimate_samples=estimate, range_bias_mm=(estimate - tau) / FS * C / 2 * 1e3))
        stream = tx.ravel()
        y_full = delay(stream, tau)
        corr = np.abs(fftconvolve(y_full, stream.conj()[::-1], mode="full"))
        j = int(np.argmax(corr))
        fractional = 0.5 * (corr[j - 1] - corr[j + 1]) / (corr[j - 1] - 2 * corr[j] + corr[j + 1])
        estimate = j - (len(stream) - 1) + fractional
        rows.append(dict(kind="full_record_linear_matched_filter", true_delay_samples=tau, estimate_samples=estimate,
                         range_bias_mm=(estimate - tau) / FS * C / 2 * 1e3))
    write_csv("fft_boundary_simulation.csv", rows)


def receiver_audit(tx, bins):
    n = tx.shape[1]
    data = tx.ravel() / np.sqrt(np.mean(np.abs(tx.ravel()) ** 2))
    modulated = data * np.exp(2j * np.pi * IF * np.arange(len(data)) / FS)
    x = 1 + M * modulated
    papr_db = float(db(np.max(np.abs(x)**2) / np.mean(np.abs(x)**2)))
    headroom = []
    for label, tx_dbm, isolation in (("paper Table I carrier", -10, 25), ("paper apparatus carrier interpretation", -10, 23),
                                      ("paper apparatus total interpretation", -10 - db(1 + M2), 23),
                                      ("PA example carrier, assumed", 0, 25)):
        carrier_in = tx_dbm - isolation
        modulated_input = carrier_in + db(1 + M2)
        for loss in (1.0, 2.0):
            zbd_average = modulated_input + 13 - loss
            headroom.append(dict(condition=label, tx_carrier_dbm=tx_dbm, net_si_isolation_db=isolation,
                                 lna_carrier_dbm=carrier_in, lna_mean_total_dbm=modulated_input,
                                 modeled_si_papr_db=papr_db, lna_modeled_peak_dbm=modulated_input + papr_db,
                                 lna_mean_headroom_db=-20 - modulated_input, lna_modeled_peak_headroom_db=-20 - modulated_input - papr_db,
                                 lna_to_zbd_loss_db=loss, zbd_carrier_dbm=carrier_in + 13 - loss,
                                 zbd_mean_total_dbm=zbd_average, zbd_mean_headroom_db=-20 - zbd_average,
                                 zbd_modeled_peak_dbm=zbd_average + papr_db,
                                 zbd_modeled_peak_headroom_db=-20 - zbd_average - papr_db))
    write_csv("receiver_power_budget.csv", headroom)
    bench = CODE / "data/omt_meas_PM5"
    thru_f, thru_p = np.loadtxt(bench / "new_thru_0dbm_2.csv", delimiter=",", skiprows=1, unpack=True)
    traces = ["long_1TO3_180deg_1.csv", "long_1TO4_180deg_2.csv", "1to2_180deg_2.csv"]
    omt_rows = []
    for name in traces:
        f, p = np.loadtxt(bench / name, delimiter=",", skiprows=1, unpack=True)
        inside = (f >= 259) & (f <= 280) & (f >= thru_f.min()) & (f <= thru_f.max())
        for freq, value in zip(f[inside], p[inside] - np.interp(f[inside], thru_f, thru_p)):
            omt_rows.append(dict(trace=name, frequency_ghz=freq, thru_referenced_transfer_db=value,
                                 source="bench OMT path, link to installed TX-to-LNA path unconfirmed"))
    write_csv("omt_bench_transfer.csv", omt_rows)

    rng = np.random.default_rng(SEED)
    p_si = 10 ** (-35 / 10)
    echo_power, _ = paper_link(1.1, -10, -10)
    x_echo = delay(x, 880)
    echo_if = delay(modulated, 880)
    bandwidth = len(bins) * FS / n
    f = np.fft.fftfreq(len(x), 1 / FS)
    band = (np.abs(f - IF) < bandwidth / 2) | (np.abs(f + IF) < bandwidth / 2)

    def in_band_power(v):
        return np.sum(np.abs(np.fft.fft(v)[band]) ** 2) / len(v)**2

    term_rows = []
    ndraw = 24
    thermal_powers, thermal_without, one_image, two_images = [], [], [], []
    for theta in np.arange(8) * np.pi / 4:
        a = np.sqrt(p_si)
        b = np.sqrt(echo_power) * np.exp(1j * theta)
        ac = a + b
        s = a * x + b * x_echo
        guard = 880
        y0 = np.abs(s) ** 2
        predicted = abs(ac)**2 + 2 * M * np.real(ac.conjugate() * (a * modulated + b * echo_if)) + M2 * np.abs(a * modulated + b * echo_if)**2
        coeff = ac.conjugate() * b
        actual_echo_term = 2 * M * np.real(coeff * echo_if)
        term_rows.append(dict(phase_deg=np.rad2deg(theta), term="delayed_linear_IF",
                              simulated_power_mw2=in_band_power(actual_echo_term),
                              analytic_unfiltered_power_mw2=2 * M2 * abs(coeff)**2,
                              square_law_identity_max_abs_error_mw=float(np.max(np.abs(y0[guard:] - predicted[guard:])))))
    a = np.sqrt(p_si)
    signal = a * x + np.sqrt(echo_power) * x_echo
    for _ in range(ndraw):
        rf_noise_band = np.abs(f) < 30e9
        complex_white = rng.normal(size=len(x)) + 1j * rng.normal(size=len(x))
        white_f = np.fft.fft(complex_white)
        noise = np.fft.ifft(white_f * rf_noise_band)
        noise *= np.sqrt(N * 60e9 / 20e9 / np.mean(np.abs(noise)**2))
        thermal_powers.append(in_band_power(2 * np.real(signal.conj() * noise)))
        thermal_without.append(in_band_power(np.abs(noise)**2))
        for mask, out in ((band & (f > 0), one_image), (band, two_images)):
            image_noise = np.fft.ifft(white_f * mask)
            images = 1 if out is one_image else 2
            image_noise *= np.sqrt(images * N / np.mean(np.abs(image_noise)**2))
            out.append(in_band_power(2 * a * np.real(image_noise)))
    term_rows.extend([
        dict(term="carrier_and_sideband_noise_beat_phase_zero_both_images", simulated_power_mw2=np.mean(thermal_powers), analytic_unfiltered_power_mw2=2 * N * (p_si + echo_power)),
        dict(term="SI_carrier_noise_beat_one_image", simulated_power_mw2=np.mean(one_image), analytic_unfiltered_power_mw2=2 * N * p_si),
        dict(term="SI_carrier_noise_beat_two_images", simulated_power_mw2=np.mean(two_images), analytic_unfiltered_power_mw2=4 * N * p_si),
        dict(term="noise_noise_beat", simulated_power_mw2=np.mean(thermal_without)),
        dict(term="deterministic_SI_SSBI", simulated_power_mw2=in_band_power(M2 * p_si * np.abs(modulated)**2),
             analytic_unfiltered_power_mw2=KAPPA * M2**2 * p_si**2,
             inferred_inband_kappa=in_band_power(M2 * p_si * np.abs(modulated)**2) / (M2**2 * p_si**2)),
    ])
    write_csv("square_law_terms.csv", term_rows)
    return x


def synthetic_cfr(tx, bins, envelope):
    rng = np.random.default_rng(SEED)
    nb, n = tx.shape
    freq = np.fft.fftfreq(n, 1 / FS)[bins]
    tx_f = np.fft.fft(tx, axis=1)[:, bins]
    accumulated = np.sum(np.abs(tx_f)**2, axis=0)
    denominator = accumulated + 1e-3 * accumulated.mean()
    grid = np.arange(0, 2.001, 0.0025)
    basis = np.exp(2j * np.pi * np.outer(grid / (C / 2), freq)) / len(freq)
    center = 1.1
    fixed = int(np.argmin(np.abs(grid - center)))
    roi = np.abs(grid - center) <= 0.04
    cell = C / (2 * (len(bins) * FS / n))
    floor = (grid >= 0.5) & (np.abs(grid - center) > 2 * cell)
    if_phase = np.exp(-2j * np.pi * IF * np.arange(nb * n) / FS)
    p_si = 10 ** (-33 / 10)
    p_ec, _ = paper_link(center, -10, -7)
    a, b = np.sqrt(p_si), np.sqrt(p_ec) * np.exp(1j * 0.7)
    echo = delay(envelope, 880) * b
    si = a * envelope

    def detector(rf):
        detected = np.abs(rf) ** 2
        return 2 * (detected - detected.mean()) * if_phase

    def estimate(y):
        yk = np.fft.fft(y.reshape(nb, n), axis=1)[:, bins]
        return np.sum(yk * tx_f.conj(), axis=0) / denominator

    def normalized(h):
        return basis @ (h / np.mean(h) - 1)

    h0 = estimate(detector(si))
    h1 = estimate(detector(si + echo))
    clean_profile = normalized(h1)
    signal_fixed = abs((clean_profile - normalized(h0))[fixed])**2
    calibration = []
    repeats = []
    for sigma in (0.00002, 0.00007, 0.0002, 0.0007, 0.002, 0.01):
        scores = []
        noise_power = []
        h0_max_scores = []
        for index in range(48):
            noise = sigma * rng.normal(size=len(si))
            h_noise = estimate(2 * noise * if_phase)
            p1 = normalized(h1 + h_noise)
            p0 = normalized(h0 + h_noise)
            pow1, pow0 = np.abs(p1)**2, np.abs(p0)**2
            ratio = np.array([pow1[fixed] / np.median(pow1[floor]),
                              pow1[roi].max() / np.median(pow1[floor]),
                              pow1[fixed] / np.mean(pow1[floor]),
                              pow1[roi].max() / np.mean(pow1[floor])])
            score = [float(db(v - 1)) if v > 1 else np.nan for v in ratio]
            scores.append(score)
            noise_power.append(abs(p1[fixed] - clean_profile[fixed])**2)
            h0_max_scores.append(pow0[roi].max() / np.median(pow0[floor]))
            peak = grid[np.flatnonzero(roi)[int(np.argmax(pow1[roi]))]]
            repeats.append(dict(sigma_post_detect_mw=sigma, trial=index, true_range_m=center,
                                peak_m=peak, error_mm=(peak-center) * 1e3))
        score_array = np.array(scores)
        truth = float(db(signal_fixed / np.mean(noise_power)))
        row = dict(sigma_post_detect_mw=sigma, synthetic_trials=48, truth_fixed_output_sinr_db=truth,
                   h0_max_exceed_13p2_count=int(np.sum(np.array(h0_max_scores) > 1 + 10**(13.2 / 10))))
        for i, key in enumerate(("fixed_median", "guided_median", "fixed_mean", "guided_mean")):
            finite = score_array[:, i][np.isfinite(score_array[:, i])]
            row.update({f"{key}_invalid": 48 - len(finite), f"{key}_median_db": np.median(finite),
                        f"{key}_p05_db": np.quantile(finite, 0.05), f"{key}_p95_db": np.quantile(finite, 0.95),
                        f"{key}_median_minus_truth_db": np.median(finite) - truth})
        calibration.append(row)
    write_csv("metric_calibration.csv", calibration)
    write_csv("repeatability_simulated.csv", repeats)
    pfa, pd = 1e-6, 0.9
    awgn_gamma = brentq(lambda g: ncx2.sf(-2 * np.log(pfa), 2, 2 * g) - pd, 0, 100)
    (OUT / "awgn_single_cell.json").write_text(json.dumps(dict(pfa=pfa, pd=pd, sinr_db=float(db(awgn_gamma)),
        detector="one complex bin, known mean H0 noise power, nonfluctuating target"), indent=2) + "\n", encoding="utf-8")

    equal_reference = a * np.ones_like(envelope)
    pure_si_linear_if = 2 * M * np.real(np.conj(a + b) * b * delay((envelope - 1) / M, 880))
    pure_lo_linear_if = 2 * M * np.real(np.conj(equal_reference[0] + b) * b * delay((envelope - 1) / M, 880))
    assert np.array_equal(pure_si_linear_if, pure_lo_linear_if)
    write_csv("reference_baselines.csv", [dict(
        branch="ideal_residual_si" if with_reference else "ideal_echo_only", range_m=center,
        echo_dbm=db(p_ec), equal_reference_carrier_dbm=db(p_si) if with_reference else None,
        closed_form_sinr_db=db(sensing(p_si if with_reference else 0.0, p_ec)),
        phase_conditioned_desired_power_mw2=2 * M2 * abs((a if with_reference else 0.0) + b)**2 * abs(b)**2,
    ) for with_reference in (True, False)] + [dict(
        branch="ideal_separate_unmodulated_reference", range_m=center, echo_dbm=db(p_ec),
        equal_reference_carrier_dbm=db(p_si),
        phase_conditioned_desired_power_mw2=2 * M2 * abs(a + b)**2 * abs(b)**2,
        equal_delayed_linear_IF_max_abs_difference=float(np.max(abs(pure_si_linear_if - pure_lo_linear_if))),
    )])

    rows = []
    for rel_db in (-30, -20, -10, -3, 0):
        for tap_delay in (8, 32, 400, 880):
            tap = delay(envelope, tap_delay)
            for phase in np.arange(8) * np.pi / 4:
                extra = a * 10**(rel_db / 20) * np.exp(1j * phase)
                h = estimate(detector(si + extra * tap + echo))
                den = abs(h.mean())
                if den <= 1e-15:
                    rows.append(dict(tap_relative_db=rel_db, tap_delay_samples=tap_delay, phase_deg=np.rad2deg(phase), normalization_failure=True))
                    continue
                p = np.abs(normalized(h)) ** 2
                peak = grid[np.flatnonzero(roi)[int(np.argmax(p[roi]))]]
                blind_mask = grid >= 0.05
                blind = grid[np.flatnonzero(blind_mask)[int(np.argmax(p[blind_mask]))]]
                floor_median = np.median(p[floor])
                rows.append(dict(tap_relative_db=rel_db, tap_delay_samples=tap_delay, phase_deg=np.rad2deg(phase),
                                 carrier_ref_ratio_db=db(max(abs(a + extra)**2 / p_si, 1e-30)),
                                 cfr_scalar_plus_echo_relative_db=db(den**2 / abs(h1.mean())**2),
                                 near_cancellation=abs(a + extra) < a * 0.01, normalization_failure=False,
                                 guided_peak_m=peak, blind_peak_m=blind, guided_contrast_db=db(p[roi].max() / floor_median),
                                 guided_bias_mm=(peak - center) * 1e3))
    write_csv("multipath_sensitivity.csv", rows)


def stock_v2():
    cfg = SimConfig()
    rows = []
    for si in (True, False):
        res = run_isac_sim(replace(cfg, si_enable=si))
        keys = ("evm_db", "sec2_sensing_sinr_db", "radar_snr_db", "range_profile_contrast_db",
                "sensing_waveform_utilization", "pilot_weighted_processing_gain_db")
        rows.append(dict(si_on=si, **{k: float(res[k]) for k in keys}))
    (OUT / "v2_baseline.json").write_text(json.dumps(dict(config=asdict(cfg), operating_points=rows), indent=2) + "\n", encoding="utf-8")


def legacy_awgn_check():
    rng = np.random.default_rng(SEED)
    labels = ((np.arange(32)[:, None] >> np.arange(4, -1, -1)) & 1).astype(np.uint8)
    points = bits_to_qam_symbols(labels.ravel(), "32QAM")
    separation = np.abs(points[:, None] - points[None, :])
    closest = np.triu(np.isclose(separation, np.min(separation[separation > 0])), 1)
    left, right = np.where(closest)
    hamming = np.count_nonzero(labels[left] != labels[right], axis=1)
    rows = []
    for snr_db in (15.75, 15.767767267472552, 17.0, 18.0, 19.0):
        errors = count = 0
        for _ in range(10):
            ids = rng.integers(0, 32, 40_000)
            noise = (rng.normal(size=len(ids)) + 1j * rng.normal(size=len(ids))) * np.sqrt(10**(-snr_db / 10) / 2)
            bits = hard_bits_from_symbols(points[ids] + noise, "32QAM")
            errors += int(np.count_nonzero(bits != labels[ids].ravel()))
            count += len(bits)
        rows.append(dict(awgn_snr_db=snr_db, simulated_legacy_mapping_ber=errors / count,
                         hard_errors=errors, bits=count, nearest_edges=len(hamming),
                         nearest_edges_one_bit=int(np.count_nonzero(hamming == 1)),
                         nearest_edges_mean_bits=float(np.mean(hamming))))
    write_csv("legacy_32qam_awgn.csv", rows)


def fig7_audit():
    ranges = np.linspace(0.7, 1.35, 131)
    echo, rx = paper_link(ranges, -10, -7)
    p_si = 10 ** (-33 / 10)
    rf_noise = 0.75 * N  # 15 GHz relative to the nominal 20 GHz.
    net_gain = 10 ** (29.8 / 10)
    comm = 2 * M2 * rx**2 / (FLOOR + 2 * rf_noise * rx + KAPPA * M2**2 * rx**2)
    sens_with = net_gain * 2 * M2 * (p_si * echo + echo**2) / (
        FLOOR + 2 * rf_noise * (p_si + echo) + KAPPA * M2**2 * p_si**2
    )
    sens_without = net_gain * 2 * M2 * echo**2 / (FLOOR + 2 * rf_noise * echo)
    write_csv("fig7_model_sensitivity.csv", [
        dict(range_m=r, eq12_with_si_db=db(sw), eq13_echo_only_db=db(so), eq16_comm_db=db(co))
        for r, sw, so, co in zip(ranges, sens_with, sens_without, comm)
    ])
    with (OUT / "processing_ablation.csv").open(encoding="utf-8") as src:
        rows = [r for r in csv.DictReader(src) if r["dataset"] == "range_1100mm" and r["method"] == "scalar_and_baseline"]
    fig, (model, records) = plt.subplots(1, 2, figsize=(8.8, 3.5), layout="constrained")
    model.plot(ranges, db(sens_with), label="Sensing with SI")
    model.plot(ranges, db(sens_without), ls="--", label="Echo-only sensing")
    model.plot(ranges, db(comm), ls=":", color="black", label="Communication")
    model.set(title="Model sensitivity calculation", xlabel="Range (m)", ylabel="Model SINR (dB)")
    model.legend(fontsize=8)
    fields = [
        ("eq19_db", "ROI peak / median excess"),
        ("fixed_eq19_db", "Fixed cell / median excess"),
        ("guided_common_mask_mean_excess_db", "ROI peak / mean excess"),
    ]
    for i, (key, label) in enumerate(fields):
        records.bar(np.arange(len(rows)) + (i - 1) * 0.22, [float(r[key]) for r in rows], width=0.20, label=label)
    records.set(title="Reprocessed 1.10 m C2 records", ylabel="Profile statistic (dB)",
                xticks=np.arange(len(rows)), xticklabels=["Record A", "Record B"])
    records.set_ylim(0, 41)
    records.legend(fontsize=7, loc="upper left")
    fig.savefig(OUT / "figures/fig7_evidence_audit.png", dpi=220)
    plt.close(fig)


def main():
    (OUT / "figures").mkdir(exist_ok=True)
    tx, bins = known_frame()
    nominal_curves()
    boundary_audit(tx, bins)
    envelope = receiver_audit(tx, bins)
    synthetic_cfr(tx, bins, envelope)
    stock_v2()
    legacy_awgn_check()
    fig7_audit()
    manifest = OUT / "run_manifest.json"
    if manifest.exists():
        values = json.loads(manifest.read_text(encoding="utf-8"))
        values["code_sha256"]["jlt_review_audit/model_audit.py"] = sha256(OUT / "model_audit.py")
        values["omt_bench_sha256"] = {p.name: sha256(p) for p in (CODE / "data/omt_meas_PM5").glob("*.csv")}
        manifest.write_text(json.dumps(values, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
