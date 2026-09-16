from __future__ import annotations

import dataclasses
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.constants import elementary_charge
from scipy.special import erfc


EXTERNAL_FSO = Path(__file__).resolve().parent / "external" / "FSO-simulator"
if str(EXTERNAL_FSO) not in sys.path:
    sys.path.insert(0, str(EXTERNAL_FSO))

from channel.fso_channel import FSOChannel  # noqa: E402
from channel.rx_optics import RxOptics  # noqa: E402
from channel.tx_optics import TxOptics  # noqa: E402
from core.general_config import LinkGeometry, SpatialGrid, TurbulenceConfig, hv57_cn2_profile  # noqa: E402


try:
    import torch
    from torch import nn
    from torch.utils.data import DataLoader, TensorDataset

    from ai_pd_model import AIPDNet, weights_from_power_log
except Exception:
    torch = None
    nn = None
    DataLoader = None
    TensorDataset = None
    AIPDNet = None
    weights_from_power_log = None


@dataclass
class ColleagueMultiPDConfig:
    """Configuration for the colleague-FSO-based Multi-PD receiver."""

    hv57_ground_cn2_A: float = 5e-14
    wavelength_m: float = 1550e-9
    link_distance_m: float = 800.0
    zenith_angle_deg: float = 0.0
    ground_altitude_m: float = 0.0
    ogs_aperture_diameter_m: float = 0.60
    ogs_tx_eff_diameter_m: float = 0.12
    tx_beam_waist_ratio: float = 0.7
    outer_scale_m: float = 100.0
    inner_scale_m: float = 0.01
    n_screens: int = 3
    n_subharmonics: int = 5
    grid_mode: str = "small"
    n_time_frames: int = 32
    frame_interval_s: float = 1e-3
    wind_speed_mps: float = 5.0
    wind_direction_deg: float = 0.0
    seed_base: int = 42
    tx_power_dbm: float = 37.0
    active_system_loss_db: float = 30.0
    receiver_responsivity: float = 0.9
    receiver_nep_density: float = 1e-11
    datarate_bps: float = 10e9
    rx_lens_diameter_m: float = 0.05
    beam_reducer_ratio: float = 10.0
    pd_rows: int = 2
    pd_cols: int = 4
    pd_spacing_m: float = 1.0e-3
    pd_radius_m: float = 0.25e-3
    microlens_enabled: bool = False
    microlens_efficiency: float = 0.85
    adc_bits: int = 8
    adc_full_scale_a: float = 50e-6
    current_noise_rms_a: float = 20e-9
    samples_per_frame: int = 16
    qam_order: int = 4
    evm_floor_pct: float = 2.0
    outage_evm_pct: float = 20.0
    fade_outage_pct: float = 1.0
    cnn_time_window: int = 6
    cnn_epochs: int = 8
    cnn_width: int = 16
    cnn_lr: float = 2e-3
    cnn_snr_weight: float = 0.2
    cnn_physics_weight: float = 0.05


def dbm_to_w(dbm: float) -> float:
    return 10.0 ** ((dbm - 30.0) / 10.0)


def w_to_dbm(watts):
    return 10.0 * np.log10(np.maximum(watts, 1e-30)) + 30.0


def qam_ber_from_snr(snr_linear, qam_order: int):
    """Gray-coded square M-QAM BER approximation from symbol SNR."""

    snr = np.maximum(np.asarray(snr_linear, dtype=float), 0.0)
    m = int(qam_order)
    if m == 2:
        return 0.5 * erfc(np.sqrt(snr))
    root = int(round(np.sqrt(m)))
    if m < 4 or root * root != m or (m & (m - 1)) != 0:
        raise ValueError("QAM order must be 2 or a square power of two (4, 16, 64, ...).")
    bits = np.log2(m)
    q_term = 0.5 * erfc(np.sqrt(3.0 * snr / (2.0 * (m - 1.0))))
    return np.minimum((4.0 / bits) * (1.0 - 1.0 / root) * q_term, 0.5)


def pd_grid_positions(rows: int, cols: int, spacing_m: float):
    x0 = (cols - 1) * spacing_m * 0.5
    y0 = (rows - 1) * spacing_m * 0.5
    return [(c * spacing_m - x0, r * spacing_m - y0) for r in range(rows) for c in range(cols)]


def _validate_config(cfg: ColleagueMultiPDConfig):
    positive = {
        "link distance": cfg.link_distance_m,
        "wavelength": cfg.wavelength_m,
        "frame interval": cfg.frame_interval_s,
        "receiver lens diameter": cfg.rx_lens_diameter_m,
        "beam reducer ratio": cfg.beam_reducer_ratio,
        "PD spacing": cfg.pd_spacing_m,
        "PD radius": cfg.pd_radius_m,
        "ADC full scale": cfg.adc_full_scale_a,
        "data rate": cfg.datarate_bps,
    }
    for name, value in positive.items():
        if value <= 0:
            raise ValueError(f"{name} must be positive, got {value}.")
    if cfg.pd_rows < 1 or cfg.pd_cols < 1:
        raise ValueError("PD rows and columns must be at least one.")
    if cfg.n_time_frames < 3:
        raise ValueError("At least three time frames are required.")
    if cfg.n_screens < 0:
        raise ValueError("The number of phase screens cannot be negative.")
    if not 0.0 <= cfg.microlens_efficiency <= 1.0:
        raise ValueError("Microlens efficiency must be between 0 and 1.")
    qam_ber_from_snr(np.asarray([1.0]), cfg.qam_order)


def _make_spatial_grid(cfg: ColleagueMultiPDConfig, tc: TurbulenceConfig):
    base = SpatialGrid(
        tx_aperture_m=cfg.ogs_aperture_diameter_m,
        rx_aperture_m=cfg.rx_lens_diameter_m,
        fried_parameter_m=tc.fried_parameter_m,
    )
    mode = cfg.grid_mode.lower().strip()
    if mode == "small":
        span_factor, min_span, cap_n = 2.0, 0.20, 256
    elif mode == "large":
        span_factor, min_span, cap_n = 6.0, 0.42, 512
    elif mode == "medium":
        span_factor, min_span, cap_n = 3.0, 0.30, 384
    else:
        raise ValueError("Grid mode must be small, medium, or large.")
    dx = base.x_step_m
    r_ap = cfg.rx_lens_diameter_m / 2.0
    span = max(span_factor * tc.fried_parameter_m, 6.0 * r_ap, min_span)
    n = min(max(64, int(np.ceil(span / dx))), cap_n)
    return SpatialGrid.from_span_step(n * dx, dx)


def _build_channel(cfg: ColleagueMultiPDConfig):
    geo = LinkGeometry(
        tx_altitude_m=cfg.ground_altitude_m,
        rx_altitude_m=cfg.ground_altitude_m + cfg.link_distance_m,
        zenith_angle_deg=cfg.zenith_angle_deg,
    )
    wind_profile = np.asarray([[0.0, cfg.wind_speed_mps], [25_000.0, cfg.wind_speed_mps]])
    tc = TurbulenceConfig(
        link_geometry=geo,
        wavelength_m=cfg.wavelength_m,
        outer_scale_m=cfg.outer_scale_m,
        inner_scale_m=cfg.inner_scale_m,
        cn2_profile=hv57_cn2_profile(A=cfg.hv57_ground_cn2_A),
        wind_speed_profile=wind_profile,
        n_screens=cfg.n_screens,
        n_subharmonics=cfg.n_subharmonics,
        subharmonic_grid_size=5,
    )
    tx_optics = TxOptics(
        aperture_diameter_m=cfg.ogs_aperture_diameter_m,
        wavelength_m=cfg.wavelength_m,
        beam_waist_m=cfg.tx_beam_waist_ratio * (cfg.ogs_tx_eff_diameter_m / 2.0),
    )
    rx_optics = RxOptics(
        aperture_diameter_m=cfg.rx_lens_diameter_m,
        exit_pupil_diameter_m=cfg.rx_lens_diameter_m / cfg.beam_reducer_ratio,
    )
    fso = FSOChannel(tx_optics=tx_optics, rx_optics=rx_optics, turbulence=tc, geometry=geo)
    return fso, geo, tc, tx_optics


def _pd_power_from_intensity(intensity, coords, dx_out, positions, cfg):
    x, y = np.meshgrid(coords, coords, indexing="ij")
    powers = []
    active_masks = []
    collection_masks = []
    half_pitch = cfg.pd_spacing_m * 0.5
    for px, py in positions:
        active = ((x - px) ** 2 + (y - py) ** 2) <= cfg.pd_radius_m**2
        if cfg.microlens_enabled:
            collection = (np.abs(x - px) < half_pitch) & (np.abs(y - py) < half_pitch)
            efficiency = cfg.microlens_efficiency
        else:
            collection = active
            efficiency = 1.0
        powers.append(float(np.sum(intensity * collection) * dx_out**2 * efficiency))
        active_masks.append(active)
        collection_masks.append(collection)
    return np.asarray(powers, dtype=float), active_masks, collection_masks


def _propagate_with_frozen_screens(
    fso,
    field_in,
    screens,
    shifts,
    z_prop_length,
    n,
    dx,
    wavelength,
):
    """Use the colleague split-step BPM with Taylor-shifted phase screens."""

    if z_prop_length <= 0:
        return field_in.copy(), 0.0
    field = field_in.copy()
    p_start = float(np.sum(np.abs(field) ** 2) * dx**2)
    z_max_step = n * dx**2 / wavelength
    if screens:
        z_layer = z_prop_length / len(screens)
        n_sub = max(1, int(np.ceil(z_layer / (2.0 * z_max_step))))
        dz_sub = z_layer / (2.0 * n_sub)
        for screen, (shift_x, shift_y) in zip(screens, shifts):
            for _ in range(n_sub):
                field = fso._fresnel_propagate(field, dx, dz_sub, wavelength)
            shifted = np.roll(screen, shift=(shift_x, shift_y), axis=(0, 1))
            field *= shifted[np.newaxis, :, :, np.newaxis]
            for _ in range(n_sub):
                field = fso._fresnel_propagate(field, dx, dz_sub, wavelength)
    else:
        n_steps = max(1, int(np.ceil(z_prop_length / z_max_step)))
        dz_step = z_prop_length / n_steps
        for _ in range(n_steps):
            field = fso._fresnel_propagate(field, dx, dz_step, wavelength)
    p_end = float(np.sum(np.abs(field) ** 2) * dx**2)
    return field, abs(p_end - p_start) / (p_start + 1e-30)


def _lag1_correlation(values):
    arr = np.asarray(values, dtype=float)
    if len(arr) < 3 or np.std(arr[:-1]) <= 1e-30 or np.std(arr[1:]) <= 1e-30:
        return float("nan")
    return float(np.corrcoef(arr[:-1], arr[1:])[0, 1])


def simulate_colleague_multi_pd_sequence(cfg: ColleagueMultiPDConfig):
    """Generate a time-correlated optical sequence and Multi-PD powers."""

    _validate_config(cfg)
    fso, geo, tc, tx_optics = _build_channel(cfg)
    sg = _make_spatial_grid(cfg, tc)

    wavelength = tc.wavelength_m
    z_total = cfg.link_distance_m
    z_atm = min(z_total, tc.z_turbulence_m)
    z_vac = max(0.0, z_total - z_atm)
    w0 = tx_optics.beam_waist_m
    z_rayleigh = np.pi * w0**2 / wavelength
    r0 = tc.fried_parameter_m
    w_exit = w0 * np.sqrt(1.0 + (z_atm / z_rayleigh) ** 2)
    dx = sg.x_step_m
    n_min = int(np.ceil(max(3.0 * w_exit, 3.0 * r0, 3.0 * cfg.rx_lens_diameter_m) / dx))
    n = int(2 ** np.ceil(np.log2(max(n_min, 64))))
    cap_n = 256 if cfg.grid_mode.lower().strip() == "small" else 512
    n = min(n, cap_n)

    coords_bpm = (np.arange(n) - (n - 1) / 2.0) * dx
    x_bpm, y_bpm = np.meshgrid(coords_bpm, coords_bpm, indexing="ij")
    radius_bpm = np.sqrt(x_bpm**2 + y_bpm**2)
    r_tx = tx_optics.aperture_diameter_m / 2.0
    e_raw = np.exp(-(x_bpm**2 + y_bpm**2) / w0**2)
    e_tx = e_raw * (radius_bpm <= r_tx)
    p_in = float(np.sum(e_tx**2) * dx**2)
    e_in = (e_tx / np.sqrt(p_in + 1e-30)).astype(np.complex128)
    field_in = np.zeros((2, n, n, 1), dtype=np.complex128)
    field_in[0, :, :, 0] = e_in
    field_in[1, :, :, 0] = e_in

    reducer = float(cfg.beam_reducer_ratio)
    r_lens = cfg.rx_lens_diameter_m / 2.0
    positions = pd_grid_positions(cfg.pd_rows, cfg.pd_cols, cfg.pd_spacing_m)
    array_radius = max(max(abs(px), abs(py)) for px, py in positions) + cfg.pd_spacing_m

    if z_vac > 1e-9:
        n_receiver = 192
        receiver_span = max(4.0 * r_lens, 2.2 * array_radius * reducer)
        dx_receiver = receiver_span / n_receiver
        coords_receiver = (np.arange(n_receiver) - (n_receiver - 1) / 2.0) * dx_receiver
        output_mode = "colleague BPM + vacuum Zoom-DFT + Rx beam reducer"
    else:
        n_receiver = n
        dx_receiver = dx
        coords_receiver = coords_bpm
        output_mode = "colleague split-step BPM + Rx beam reducer"
    coords_out = coords_receiver / reducer
    dx_out = dx_receiver / reducer
    xr, yr = np.meshgrid(coords_receiver, coords_receiver, indexing="ij")
    lens_mask_receiver = (xr**2 + yr**2) <= r_lens**2

    tc_no_turbulence = dataclasses.replace(tc, n_screens=0)
    field_ref, _ = fso._propagate_numerical_segment_full_field(
        field_in, z_atm, n, dx, wavelength, tc_no_turbulence, geo
    )
    if z_vac > 1e-9:
        field_ref_receiver = fso._propagate_far_field_zoom(
            field_ref, dx, dx_receiver, z_vac, wavelength
        )
    else:
        field_ref_receiver = field_ref
    reference_intensity = np.abs(field_ref_receiver[0, :, :, 0]) ** 2
    reference_aperture_field = field_ref_receiver[0, :, :, 0] * lens_mask_receiver
    reference_aperture_power = float(
        np.sum(np.abs(reference_aperture_field) ** 2) * dx_receiver**2
    ) + 1e-30

    base_screens = fso._make_phase_screens(
        n,
        dx,
        wavelength,
        tc.cn2_profile,
        geo.zenith_angle_deg,
        tc.n_screens,
        z_atm,
        tc.outer_scale_m,
        tc.inner_scale_m,
        n_subharmonics=tc.n_subharmonics,
        subharmonic_grid_size=tc.subharmonic_grid_size,
        seed=cfg.seed_base,
    ) if tc.n_screens > 0 else []

    frame_times = np.arange(cfg.n_time_frames, dtype=float) * cfg.frame_interval_s
    theta = np.deg2rad(cfg.wind_direction_deg)
    vx = cfg.wind_speed_mps * np.cos(theta)
    vy = cfg.wind_speed_mps * np.sin(theta)

    receiver_seq = np.zeros((cfg.n_time_frames, n_receiver, n_receiver), dtype=np.float32)
    reduced_seq = np.zeros_like(receiver_seq)
    pd_fraction = np.zeros((cfg.n_time_frames, len(positions)), dtype=np.float64)
    wander_xy = np.zeros((cfg.n_time_frames, 2), dtype=np.float64)
    aperture_fraction = np.zeros(cfg.n_time_frames, dtype=np.float64)
    strehl = np.zeros(cfg.n_time_frames, dtype=np.float64)
    parseval_error = np.zeros(cfg.n_time_frames, dtype=np.float64)
    screen_shift_pixels = np.zeros((cfg.n_time_frames, max(len(base_screens), 1), 2), dtype=int)

    xo, yo = np.meshgrid(coords_out, coords_out, indexing="ij")
    active_masks = collection_masks = None
    for frame_index, time_s in enumerate(frame_times):
        shifts = []
        for screen_index in range(len(base_screens)):
            shift_x = int(np.rint(vx * time_s / dx))
            shift_y = int(np.rint(vy * time_s / dx))
            shifts.append((shift_x, shift_y))
            screen_shift_pixels[frame_index, screen_index] = (shift_x, shift_y)
        field_t, parseval_error[frame_index] = _propagate_with_frozen_screens(
            fso, field_in, base_screens, shifts, z_atm, n, dx, wavelength
        )
        if z_vac > 1e-9:
            field_receiver = fso._propagate_far_field_zoom(
                field_t, dx, dx_receiver, z_vac, wavelength
            )
        else:
            field_receiver = field_t
        receiver_intensity = np.abs(field_receiver[0, :, :, 0]) ** 2
        reduced_intensity = receiver_intensity * lens_mask_receiver * reducer**2

        receiver_seq[frame_index] = receiver_intensity.astype(np.float32)
        reduced_seq[frame_index] = reduced_intensity.astype(np.float32)
        pd_fraction[frame_index], active_masks, collection_masks = _pd_power_from_intensity(
            reduced_intensity, coords_out, dx_out, positions, cfg
        )

        total_plane = float(np.sum(receiver_intensity) * dx_receiver**2) + 1e-30
        collected = float(np.sum(receiver_intensity * lens_mask_receiver) * dx_receiver**2)
        aperture_fraction[frame_index] = collected / total_plane
        aperture_field = field_receiver[0, :, :, 0] * lens_mask_receiver
        overlap = np.sum(aperture_field * np.conj(reference_aperture_field)) * dx_receiver**2
        strehl[frame_index] = float(
            np.abs(overlap) ** 2 / (collected * reference_aperture_power + 1e-30)
        )
        reduced_total = float(np.sum(reduced_intensity) * dx_out**2) + 1e-30
        wander_xy[frame_index, 0] = float(np.sum(xo * reduced_intensity) * dx_out**2 / reduced_total)
        wander_xy[frame_index, 1] = float(np.sum(yo * reduced_intensity) * dx_out**2 / reduced_total)

    tx_power_w = dbm_to_w(cfg.tx_power_dbm)
    system_transmission = 10.0 ** (-cfg.active_system_loss_db / 10.0)
    pd_rx_power_w = pd_fraction * tx_power_w * system_transmission
    total_pd_power = np.sum(pd_rx_power_w, axis=1)
    scintillation_index = float(np.var(total_pd_power) / (np.mean(total_pd_power) ** 2 + 1e-30))

    h = np.linspace(cfg.ground_altitude_m, cfg.ground_altitude_m + cfg.link_distance_m, 1000)
    cn2 = np.interp(h, tc.cn2_profile[:, 0], tc.cn2_profile[:, 1], left=0.0, right=0.0)
    cn2_equivalent = float(np.trapezoid(cn2, h) / max(cfg.link_distance_m, 1e-30))
    k = 2.0 * np.pi / cfg.wavelength_m
    rytov_variance = float(1.23 * cn2_equivalent * k ** (7.0 / 6.0) * cfg.link_distance_m ** (11.0 / 6.0))

    return {
        "fso": fso,
        "geo": geo,
        "tc": tc,
        "spatial_grid": sg,
        "coords_receiver": coords_receiver,
        "dx_receiver": dx_receiver,
        "coords_out": coords_out,
        "dx_out": dx_out,
        "pd_positions": positions,
        "pd_active_masks": active_masks,
        "pd_collection_masks": collection_masks,
        "receiver_intensity_seq": receiver_seq,
        "intensity_seq": reduced_seq,
        "pd_power_fraction": pd_fraction,
        "pd_rx_power_w": pd_rx_power_w,
        "pd_power": pd_rx_power_w,
        "frame_times_s": frame_times,
        "wander_xy_m": wander_xy,
        "aperture_capture_fraction": aperture_fraction,
        "strehl_ratio": strehl,
        "parseval_error": parseval_error,
        "screen_shift_pixels": screen_shift_pixels,
        "r0_m": tc.fried_parameter_m,
        "greenwood_hz": tc.greenwood_freq_hz,
        "rytov_variance": rytov_variance,
        "scintillation_index": scintillation_index,
        "temporal_correlation_lag1": _lag1_correlation(total_pd_power),
        "link_distance_m": geo.link_distance_m,
        "configured_link_distance_m": cfg.link_distance_m,
        "bpm_n": n,
        "bpm_dx_m": dx,
        "receiver_n": n_receiver,
        "receiver_dx_m": dx_receiver,
        "far_n": n_receiver,
        "far_dx_m": dx_out,
        "output_plane_mode": output_mode,
        "beam_reducer_ratio": reducer,
        "rx_lens_diameter_m": cfg.rx_lens_diameter_m,
        "rx_lens_radius_m": r_lens,
        "reduced_lens_radius_m": r_lens / reducer,
    }


def _adc_from_pd_power(power_w: np.ndarray, cfg: ColleagueMultiPDConfig, rng):
    p = np.asarray(power_w, dtype=float)
    n_frames, _n_pd = p.shape
    samples = max(1, int(cfg.samples_per_frame))
    signal_frames = cfg.receiver_responsivity * p
    signal_samples = np.repeat(signal_frames, samples, axis=0).T
    noisy_samples = signal_samples.copy()
    if cfg.current_noise_rms_a > 0:
        noisy_samples += rng.normal(0.0, cfg.current_noise_rms_a, noisy_samples.shape)
    levels = 2 ** max(int(cfg.adc_bits), 1)
    clipped = np.clip(noisy_samples, 0.0, cfg.adc_full_scale_a)
    codes = np.rint(clipped / cfg.adc_full_scale_a * (levels - 1)).astype(np.int32)
    quantized = codes.astype(float) / (levels - 1) * cfg.adc_full_scale_a
    frame_current = quantized.reshape(quantized.shape[0], n_frames, samples).mean(axis=2).T
    measured_power = frame_current / max(cfg.receiver_responsivity, 1e-30)
    return {
        "signal_current_a": signal_samples,
        "current_a": noisy_samples,
        "adc_current_a": quantized,
        "adc_codes": codes,
        "frame_current_a": frame_current,
        "measured_power_w": measured_power,
    }


def train_temporal_cnn(power_w: np.ndarray, cfg: ColleagueMultiPDConfig):
    if torch is None or AIPDNet is None or weights_from_power_log is None:
        return {"available": False, "history": [], "weights": None, "error": "PyTorch is not available."}

    p = np.asarray(power_w, dtype=np.float32)
    tw = max(2, int(cfg.cnn_time_window))
    rows, cols = int(cfg.pd_rows), int(cfg.pd_cols)
    if p.shape[0] - tw < 2:
        return {
            "available": False,
            "history": [],
            "weights": None,
            "error": "Increase time frames so at least two CNN targets remain after the time window.",
        }

    p_norm = p / (np.mean(p, axis=1, keepdims=True) + 1e-30)
    p_log = np.log10(np.maximum(p_norm, 1e-9)).reshape(p.shape[0], rows, cols)
    xs, ys, true_power = [], [], []
    for i in range(p_log.shape[0] - tw):
        xs.append(p_log[i : i + tw])
        ys.append(p_log[i + tw])
        true_power.append(p_norm[i + tw].reshape(rows, cols))
    x = torch.tensor(np.asarray(xs), dtype=torch.float32)
    y = torch.tensor(np.asarray(ys), dtype=torch.float32)
    true_p = torch.tensor(np.asarray(true_power), dtype=torch.float32)

    torch.manual_seed(cfg.seed_base)
    model = AIPDNet(time_window=tw, rows=rows, cols=cols, phys_dim=1, width=cfg.cnn_width)
    optimizer = torch.optim.Adam(model.parameters(), lr=cfg.cnn_lr)
    loader = DataLoader(TensorDataset(x, y, true_p), batch_size=min(16, len(x)), shuffle=True)
    history = []
    for epoch in range(max(1, int(cfg.cnn_epochs))):
        totals = {"loss": 0.0, "mse": 0.0, "snr": 0.0, "physics": 0.0, "count": 0}
        for xb, yb, pb in loader:
            pred, _ = model(xb)
            mse = nn.functional.mse_loss(pred, yb)
            weights = weights_from_power_log(pred).reshape(pred.shape[0], -1)
            signal = pb.reshape(pb.shape[0], -1)
            snr_proxy = (torch.sum(weights * signal, dim=1) ** 2) / (
                torch.sum(weights**2, dim=1) + 1e-9
            )
            snr_loss = -torch.mean(torch.log(snr_proxy + 1e-9))
            pred_power = torch.pow(10.0, torch.clamp(pred, -6.0, 6.0))
            physics_loss = nn.functional.mse_loss(
                pred_power.mean(dim=(1, 2)), pb.mean(dim=(1, 2))
            )
            loss = mse + cfg.cnn_snr_weight * snr_loss + cfg.cnn_physics_weight * physics_loss
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            batch_size = xb.shape[0]
            totals["loss"] += float(loss.detach()) * batch_size
            totals["mse"] += float(mse.detach()) * batch_size
            totals["snr"] += float(torch.mean(snr_proxy).detach()) * batch_size
            totals["physics"] += float(physics_loss.detach()) * batch_size
            totals["count"] += batch_size
        count = max(totals["count"], 1)
        history.append({
            "epoch": epoch + 1,
            "loss": totals["loss"] / count,
            "mse": totals["mse"] / count,
            "snr_proxy": totals["snr"] / count,
            "physics_loss": totals["physics"] / count,
        })

    model.eval()
    with torch.no_grad():
        pred, _ = model(x)
        weights = weights_from_power_log(pred).reshape(pred.shape[0], -1).cpu().numpy()
        pred_log = pred.cpu().numpy()
    return {
        "available": True,
        "history": history,
        "weights": weights,
        "pred_log": pred_log,
        "pred_norm_power": 10.0 ** np.clip(pred_log, -6.0, 6.0),
        "true_norm_power": np.asarray(true_power),
        "time_window": tw,
    }


def _receiver_noise_variance(signal_current_a: np.ndarray, cfg: ColleagueMultiPDConfig):
    bandwidth_hz = max(cfg.datarate_bps * 0.75, 1.0)
    nep_current_rms = cfg.receiver_responsivity * cfg.receiver_nep_density * np.sqrt(bandwidth_hz)
    quant_rms = cfg.adc_full_scale_a / (2 ** max(cfg.adc_bits, 1) - 1) / np.sqrt(12.0)
    shot_var = 2.0 * elementary_charge * np.maximum(signal_current_a, 0.0) * bandwidth_hz
    return shot_var + nep_current_rms**2 + cfg.current_noise_rms_a**2 + quant_rms**2


def _method_weights(signal_current, measured_power, noise_var, cfg, cnn):
    n_frames, n_pd = signal_current.shape
    positions = np.asarray(pd_grid_positions(cfg.pd_rows, cfg.pd_cols, cfg.pd_spacing_m))
    center_idx = int(np.argmin(np.sum(positions**2, axis=1)))

    single = np.zeros((n_frames, n_pd), dtype=float)
    single[:, center_idx] = 1.0
    selection = np.zeros_like(single)
    selection[np.arange(n_frames), np.argmax(measured_power, axis=1)] = 1.0
    egc = np.ones_like(single)
    mrc = signal_current / np.maximum(noise_var, 1e-30)
    methods = {
        "Single center PD": single,
        "Selection": selection,
        "EGC": egc,
        "MRC oracle": mrc,
    }
    if cnn.get("available") and cnn.get("weights") is not None:
        predictive = np.full_like(single, np.nan)
        tw = int(cnn["time_window"])
        predictive[tw : tw + len(cnn["weights"])] = cnn["weights"]
        methods["CNN predictive"] = predictive
    return methods, center_idx


def _link_performance(pd_rx_power_w, adc, cnn, cfg):
    power = np.asarray(pd_rx_power_w, dtype=float)
    signal_current = cfg.receiver_responsivity * power
    noise_var = _receiver_noise_variance(signal_current, cfg)
    methods, center_idx = _method_weights(
        signal_current, adc["measured_power_w"], noise_var, cfg, cnn
    )
    total_power_dbm = w_to_dbm(np.sum(power, axis=1))
    metrics = {}
    traces = {}
    for name, weight in methods.items():
        valid = np.all(np.isfinite(weight), axis=1)
        snr = np.full(power.shape[0], np.nan, dtype=float)
        effective_power = np.full(power.shape[0], np.nan, dtype=float)
        if np.any(valid):
            w = weight[valid]
            numerator = np.sum(w * signal_current[valid], axis=1) ** 2
            denominator = np.sum(w**2 * noise_var[valid], axis=1) + 1e-30
            snr[valid] = numerator / denominator
            w_norm = w / (np.sum(np.abs(w), axis=1, keepdims=True) + 1e-30)
            effective_power[valid] = np.sum(w_norm * power[valid], axis=1)
        evm = np.sqrt(10000.0 / np.maximum(snr, 1e-30) + cfg.evm_floor_pct**2)
        evm = np.minimum(evm, 100.0)
        ber = qam_ber_from_snr(snr, cfg.qam_order)
        finite = np.isfinite(snr)
        normalized_power = effective_power[finite] / (np.mean(effective_power[finite]) + 1e-30)
        q = np.percentile(normalized_power, cfg.fade_outage_pct)
        metrics[name] = {
            "mean_evm_pct": float(np.mean(evm[finite])),
            "p95_evm_pct": float(np.percentile(evm[finite], 95.0)),
            "mean_ber": float(np.mean(ber[finite])),
            "outage_probability": float(np.mean(evm[finite] > cfg.outage_evm_pct)),
            "required_fade_margin_db": float(-10.0 * np.log10(max(q, 1e-12))),
            "mean_rx_power_dbm": float(np.mean(total_power_dbm[finite])),
            "mean_effective_power_dbm": float(w_to_dbm(np.mean(effective_power[finite]))),
            "mean_snr_db": float(10.0 * np.log10(max(np.mean(snr[finite]), 1e-30))),
            "valid_frames": int(np.sum(finite)),
        }
        traces[name] = {
            "snr_db": 10.0 * np.log10(np.maximum(snr, 1e-30)),
            "evm_pct": evm,
            "ber": ber,
            "effective_power_dbm": w_to_dbm(effective_power),
        }
    return metrics, traces, center_idx, total_power_dbm


def run_colleague_multi_pd_link(cfg: ColleagueMultiPDConfig):
    rng = np.random.default_rng(cfg.seed_base + 100_000)
    sequence = simulate_colleague_multi_pd_sequence(cfg)
    adc = _adc_from_pd_power(sequence["pd_rx_power_w"], cfg, rng)
    cnn = train_temporal_cnn(adc["measured_power_w"], cfg) if cfg.cnn_epochs > 0 else {
        "available": False,
        "history": [],
        "weights": None,
        "error": "CNN training disabled.",
    }
    metrics, performance, center_idx, total_power_dbm = _link_performance(
        sequence["pd_rx_power_w"], adc, cnn, cfg
    )
    return {
        **sequence,
        "cfg": cfg,
        "cnn": cnn,
        "metrics": metrics,
        "performance_traces": performance,
        "center_idx": center_idx,
        "adc": adc,
        "total_pd_power_dbm": total_power_dbm,
        "external_simulator_path": str(EXTERNAL_FSO),
    }
