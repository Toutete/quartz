from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.constants import pi

from fso_engine import Receiver_Array, SSFM_Channel


@dataclass
class MultiPDConfig:
    distance_m: float = 800.0
    cn2: float = 1e-15
    n_screens: int = 5
    wind_speed_m_s: float = 15.0
    wavelength_m: float = 1550e-9
    beam_waist_m: float = 1.0e-3
    grid_n: int = 128
    frames: int = 32
    display_width_m: float = 1.2
    tx_power_dbm: float = 10.0
    seed: int = 42
    pd_rows: int = 2
    pd_cols: int = 4
    pd_spacing_m: float = 20e-3
    lens_radius_m: float = 20e-3
    pd_active_radius_m: float = 30e-6
    focal_length_m: float = 50e-3
    responsivity_a_w: float = 0.9
    adc_bits: int = 8
    adc_full_scale_a: float = 5e-6
    samples_per_symbol: int = 8
    output_samples_per_symbol: int = 1
    num_symbols: int = 1024
    modulation_order: int = 4
    symbol_rate_baud: float = 1e9
    modulation_depth: float = 0.35
    current_noise_rms_a: float = 5e-9
    snr_ref_db: float = 25.0
    evm_floor_pct: float = 2.0
    outage_evm_pct: float = 20.0
    fade_outage_pct: float = 1.0
    fair_total_aperture: bool = False


def dbm_to_w(dbm: float) -> float:
    return 10.0 ** ((dbm - 30.0) / 10.0)


def w_to_dbm(watts):
    return 10.0 * np.log10(np.maximum(watts, 1e-30)) + 30.0


def pd_grid_positions(rows: int, cols: int, spacing_m: float):
    x_offset = (cols - 1) * spacing_m * 0.5
    y_offset = (rows - 1) * spacing_m * 0.5
    coords = []
    for r in range(rows):
        for c in range(cols):
            coords.append((c * spacing_m - x_offset, r * spacing_m - y_offset))
    return coords


def simulation_width_m(cfg: MultiPDConfig) -> float:
    beam_spot = cfg.beam_waist_m * np.sqrt(
        1.0 + (cfg.wavelength_m * cfg.distance_m / (pi * cfg.beam_waist_m**2)) ** 2
    )
    if cfg.cn2 > 0:
        k0 = 2.0 * pi / cfg.wavelength_m
        rho0 = (0.423 * (k0**2) * cfg.cn2 * cfg.distance_m) ** (-0.6)
        turb_spread = cfg.distance_m * cfg.wavelength_m / rho0
    else:
        turb_spread = 0.0
    array_span = max(cfg.pd_rows, cfg.pd_cols) * cfg.pd_spacing_m + 4.0 * cfg.lens_radius_m
    return max(cfg.display_width_m, array_span, 4.0 * np.sqrt(beam_spot**2 + turb_spread**2))


def scale_fields_to_power(fields: np.ndarray, d_obs_m: float, tx_power_dbm: float):
    dx = d_obs_m / fields.shape[0]
    tx_power_w = dbm_to_w(tx_power_dbm)
    frame_power = np.sum(np.abs(fields) ** 2, axis=(0, 1)) * (dx**2) + 1e-30
    scaled = fields * np.sqrt(tx_power_w / frame_power)[None, None, :]
    return scaled, dx


def qam_constellation(order: int) -> np.ndarray:
    if order == 4:
        pts = np.array([-1 - 1j, -1 + 1j, 1 - 1j, 1 + 1j], dtype=np.complex128)
    else:
        side = int(np.sqrt(order))
        if side * side != order:
            side = 4
        vals = np.arange(-(side - 1), side, 2)
        pts = np.array([x + 1j * y for y in vals for x in vals], dtype=np.complex128)
    return pts / np.sqrt(np.mean(np.abs(pts) ** 2))


def quantize_unipolar(x: np.ndarray, bits: int, full_scale: float):
    if bits <= 0:
        return x.copy(), np.zeros_like(x, dtype=np.int32)
    levels = 2**bits
    clipped = np.clip(x, 0.0, full_scale)
    codes = np.rint(clipped / max(full_scale, 1e-30) * (levels - 1)).astype(np.int32)
    quantized = codes.astype(float) / (levels - 1) * full_scale
    return quantized, codes


def combine_fading_factors(power_w: np.ndarray, cfg: MultiPDConfig):
    power_w = np.asarray(power_w, dtype=float)
    n_pd = power_w.shape[0]
    center_idx = int(np.argmin(np.sum(np.asarray(pd_grid_positions(cfg.pd_rows, cfg.pd_cols, cfg.pd_spacing_m)) ** 2, axis=1)))
    reference = float(np.mean(power_w[center_idx]) + 1e-30)
    scale = n_pd if cfg.fair_total_aperture and n_pd > 0 else 1.0
    p_eff = power_w / scale
    reference_eff = reference / scale

    single = p_eff[center_idx] / reference_eff
    selection = np.max(p_eff, axis=0) / reference_eff
    egc = (np.sum(np.sqrt(np.maximum(p_eff, 0.0)), axis=0) ** 2) / (n_pd * reference_eff + 1e-30)
    mrc = np.sum(p_eff, axis=0) / reference_eff
    oracle = mrc.copy()
    factors = {
        "Single center PD": single,
        "Selection": selection,
        "EGC": egc,
        "MRC": mrc,
        "Oracle": oracle,
    }
    optical_power = {
        "Single center PD": p_eff[center_idx],
        "Selection": np.max(p_eff, axis=0),
        "EGC": egc * reference_eff,
        "MRC": mrc * reference_eff,
        "Oracle": oracle * reference_eff,
    }
    return factors, optical_power, center_idx


def link_metrics_from_power(power_w: np.ndarray, cfg: MultiPDConfig):
    factors, optical_power, center_idx = combine_fading_factors(power_w, cfg)
    snr_ref = 10.0 ** (cfg.snr_ref_db / 10.0)
    metrics = {}
    for name, s in factors.items():
        s = np.maximum(np.asarray(s, dtype=float), 1e-9)
        evm = np.sqrt((100.0 / np.sqrt(snr_ref * s)) ** 2 + cfg.evm_floor_pct**2)
        evm = np.minimum(evm, 100.0)
        norm = s / (np.mean(s) + 1e-30)
        q = np.percentile(norm, cfg.fade_outage_pct)
        metrics[name] = {
            "mean_evm_pct": float(np.mean(evm)),
            "p95_evm_pct": float(np.percentile(evm, 95.0)),
            "outage_probability": float(np.mean(evm > cfg.outage_evm_pct)),
            "required_fade_margin_db": float(-10.0 * np.log10(max(q, 1e-12))),
            "mean_rx_power_w": float(np.mean(optical_power[name])),
            "mean_rx_power_dbm": float(w_to_dbm(np.mean(optical_power[name]))),
            "mean_snr_db": float(10.0 * np.log10(max(np.mean(snr_ref * s), 1e-30))),
        }
    return metrics, factors, center_idx


def simulate_adc_and_symbols(power_w: np.ndarray, cfg: MultiPDConfig, rng: np.random.Generator):
    n_pd, n_frames = power_w.shape
    n_symbols = max(16, int(cfg.num_symbols))
    sps = max(1, int(cfg.samples_per_symbol))
    n_samples = n_symbols * sps

    const = qam_constellation(cfg.modulation_order)
    tx_idx = rng.integers(0, len(const), n_symbols)
    tx_symbols = const[tx_idx]
    drive = np.repeat(np.real(tx_symbols), sps)
    drive = drive / (np.max(np.abs(drive)) + 1e-30)

    frame_x = np.linspace(0.0, 1.0, n_frames)
    sample_x = np.linspace(0.0, 1.0, n_samples)
    symbol_x = np.linspace(0.0, 1.0, n_symbols)

    power_samples = np.vstack([np.interp(sample_x, frame_x, power_w[i]) for i in range(n_pd)])
    current_dc = cfg.responsivity_a_w * power_samples
    current = current_dc * (1.0 + cfg.modulation_depth * drive[None, :])
    if cfg.current_noise_rms_a > 0:
        current = current + rng.normal(0.0, cfg.current_noise_rms_a, current.shape)
    adc_current, adc_codes = quantize_unipolar(current, cfg.adc_bits, cfg.adc_full_scale_a)

    power_symbols = np.vstack([np.interp(symbol_x, frame_x, power_w[i]) for i in range(n_pd)])
    metrics, factors, center_idx = link_metrics_from_power(power_w, cfg)
    factor_symbols = {
        name: np.interp(symbol_x, frame_x, values) for name, values in factors.items()
    }
    rx_symbols = {}
    snr_ref = 10.0 ** (cfg.snr_ref_db / 10.0)
    for name in ("Single center PD", "MRC", "Oracle"):
        snr_sym = np.maximum(snr_ref * factor_symbols[name], 1e-9)
        noise = (
            rng.normal(0.0, 1.0, n_symbols) + 1j * rng.normal(0.0, 1.0, n_symbols)
        ) / np.sqrt(2.0 * snr_sym)
        rx_symbols[name] = tx_symbols + noise

    return {
        "tx_symbols": tx_symbols,
        "rx_symbols": rx_symbols,
        "power_samples_w": power_samples,
        "current_a": current,
        "adc_current_a": adc_current,
        "adc_codes": adc_codes,
        "center_idx": center_idx,
        "metrics": metrics,
    }


def run_multi_pd_link(cfg: MultiPDConfig):
    rng = np.random.default_rng(cfg.seed)
    np.random.seed(cfg.seed)

    d_obs = simulation_width_m(cfg)
    channel = SSFM_Channel(
        {
            "N_screens": cfg.n_screens,
            "lam": cfg.wavelength_m,
            "L": cfg.distance_m,
            "Cn2": cfg.cn2,
            "w0": cfg.beam_waist_m,
            "l0": 1e-3,
            "L0": 100.0,
            "wind_speed": cfg.wind_speed_m_s,
            "D_obs": d_obs,
            "delta_t": 1e-3,
            "n_frames": cfg.frames,
            "N": cfg.grid_n,
        }
    )
    fields, x_arr, r0_total, rytov_dz = channel.generate_spatiotemporal_beams()
    fields, dx = scale_fields_to_power(fields, d_obs, cfg.tx_power_dbm)

    pd_positions = pd_grid_positions(cfg.pd_rows, cfg.pd_cols, cfg.pd_spacing_m)
    rx_array = Receiver_Array(
        pd_positions,
        cfg.lens_radius_m,
        cfg.pd_active_radius_m,
        cfg.focal_length_m,
        x_arr,
        cfg.wavelength_m,
    )
    traces_norm, combined_norm, traces_abs, combined_abs = rx_array.compute_focal_coupling(
        fields, normalize=False, return_absolute=True
    )
    power_w = np.asarray(traces_abs, dtype=float)
    metrics, factors, center_idx = link_metrics_from_power(power_w, cfg)
    signal = simulate_adc_and_symbols(power_w, cfg, rng)

    return {
        "cfg": cfg,
        "fields": fields,
        "x_arr": x_arr,
        "dx": dx,
        "pd_positions": pd_positions,
        "power_w": power_w,
        "combined_power_w": np.asarray(combined_abs, dtype=float),
        "metrics": metrics,
        "fading_factors": factors,
        "center_idx": center_idx,
        "signal": signal,
        "r0_total_m": float(r0_total),
        "rytov_dz": float(rytov_dz),
        "alias_metric": float(channel.alias_metric),
        "substeps_per_screen": int(channel.substeps_per_screen),
        "propagation_mode": channel.propagation_mode,
        "external_simulator_path": str(Path(__file__).parent / "external" / "FSO-simulator"),
    }
