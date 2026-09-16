from __future__ import annotations

import dataclasses
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
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

    from ai_pd_model import AIPDNet
except Exception:
    torch = None
    nn = None
    DataLoader = None
    TensorDataset = None
    AIPDNet = None


@dataclass
class ColleagueMultiPDConfig:
    hv57_ground_cn2_A: float = 5e-14
    wavelength_m: float = 1550e-9
    link_distance_m: float = 800.0
    zenith_angle_deg: float = 0.0
    ground_altitude_m: float = 0.0
    leo_altitude_m: float = 800.0
    ogs_aperture_diameter_m: float = 0.60
    ogs_tx_eff_diameter_m: float = 0.12
    leo_aperture_diameter_m: float = 0.08
    rx_exit_pupil_diameter_m: float = 0.010
    rx_lens_diameter_m: float = 0.05
    beam_reducer_ratio: float = 10.0
    tx_beam_waist_ratio: float = 0.7
    outer_scale_m: float = 100.0
    inner_scale_m: float = 0.01
    n_screens: int = 3
    n_subharmonics: int = 5
    grid_mode: str = "medium"
    n_time_frames: int = 24
    seed_base: int = 42
    tx_power_dbm: float = 37.0
    active_system_loss_db: float = 3.0
    receiver_responsivity: float = 1.0
    receiver_nep_density: float = 1e-11
    datarate_bps: float = 10e9
    pd_rows: int = 2
    pd_cols: int = 4
    pd_spacing_m: float = 1.0e-3
    pd_radius_m: float = 0.25e-3
    microlens_gain: float = 1.0
    adc_bits: int = 8
    adc_full_scale_a: float = 50e-6
    current_noise_rms_a: float = 20e-9
    samples_per_frame: int = 16
    qam_order: int = 4
    evm_floor_pct: float = 2.0
    outage_evm_pct: float = 20.0
    fade_outage_pct: float = 1.0
    fair_total_aperture: bool = False
    cnn_time_window: int = 6
    cnn_epochs: int = 8
    cnn_width: int = 16
    cnn_lr: float = 2e-3
    cnn_snr_weight: float = 0.2


def dbm_to_w(dbm: float) -> float:
    return 10.0 ** ((dbm - 30.0) / 10.0)


def w_to_dbm(watts):
    return 10.0 * np.log10(np.maximum(watts, 1e-30)) + 30.0


def qam_ber_from_evm(evm_pct):
    snr_eff = (100.0 / np.maximum(evm_pct, 0.1)) ** 2
    return 0.5 * erfc(np.sqrt(np.maximum(snr_eff / 2.0, 0.0)))


def pd_grid_positions(rows: int, cols: int, spacing_m: float):
    x0 = (cols - 1) * spacing_m * 0.5
    y0 = (rows - 1) * spacing_m * 0.5
    return [(c * spacing_m - x0, r * spacing_m - y0) for r in range(rows) for c in range(cols)]


def _make_spatial_grid(cfg: ColleagueMultiPDConfig, tc: TurbulenceConfig):
    base = SpatialGrid(
        tx_aperture_m=cfg.ogs_aperture_diameter_m,
        rx_aperture_m=cfg.rx_lens_diameter_m,
        fried_parameter_m=tc.fried_parameter_m,
    )
    mode = cfg.grid_mode.lower().strip()
    if mode == "small":
        span_factor, min_span, cap_n = 2.0, 0.20, 128
    elif mode == "large":
        span_factor, min_span, cap_n = 6.0, 0.42, 512
    else:
        span_factor, min_span, cap_n = 3.0, 0.30, 256
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
    tc = TurbulenceConfig(
        link_geometry=geo,
        wavelength_m=cfg.wavelength_m,
        outer_scale_m=cfg.outer_scale_m,
        inner_scale_m=cfg.inner_scale_m,
        cn2_profile=hv57_cn2_profile(A=cfg.hv57_ground_cn2_A),
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
        exit_pupil_diameter_m=cfg.rx_exit_pupil_diameter_m,
    )
    fso = FSOChannel(tx_optics=tx_optics, rx_optics=rx_optics, turbulence=tc, geometry=geo)
    return fso, geo, tc, tx_optics, rx_optics


def _pd_power_from_intensity(intensity, coords, dx_out, positions, radius):
    x, y = np.meshgrid(coords, coords, indexing="ij")
    powers = []
    masks = []
    for px, py in positions:
        mask = ((x - px) ** 2 + (y - py) ** 2) <= radius**2
        powers.append(float(np.sum(intensity * mask) * dx_out**2))
        masks.append(mask)
    return np.asarray(powers, dtype=float), masks


def _simulate_colleague_uplink_sequence(cfg: ColleagueMultiPDConfig):
    fso, geo, tc, tx_optics, rx_optics = _build_channel(cfg)
    sg = _make_spatial_grid(cfg, tc)

    lam = tc.wavelength_m
    z_total = cfg.link_distance_m
    z_atm = min(z_total, tc.z_turbulence_m)
    z_vac = max(0.0, z_total - z_atm)
    w0 = tx_optics.beam_waist_m
    z_R = np.pi * w0**2 / lam
    r0 = tc.fried_parameter_m
    w_exit = w0 * np.sqrt(1.0 + (z_atm / z_R) ** 2)
    dx = sg.x_step_m
    n_min = int(np.ceil(max(3.0 * w_exit, 3.0 * r0) / dx))
    n = int(2 ** np.ceil(np.log2(max(n_min, 16))))
    n = min(n, 512)

    coords = (np.arange(n) - (n - 1) / 2.0) * dx
    x, y = np.meshgrid(coords, coords, indexing="ij")
    r2 = x**2 + y**2
    r = np.sqrt(r2)
    phase_fres = np.exp(1j * np.pi * r2 / (lam * z_vac)) if z_vac > 1e-9 else None

    r_tx = tx_optics.aperture_diameter_m / 2.0
    e_raw = np.exp(-r2 / w0**2)
    e_tx = e_raw * (r <= r_tx)
    p_in = float(np.sum(e_tx**2) * dx**2)
    e_in = (e_tx / np.sqrt(p_in + 1e-30)).astype(np.complex128)
    field_in = np.zeros((2, n, n, 1), dtype=np.complex128)
    field_in[0, :, :, 0] = e_in
    field_in[1, :, :, 0] = e_in

    reducer = max(float(cfg.beam_reducer_ratio), 1.0)
    array_half = max(cfg.pd_rows, cfg.pd_cols) * cfg.pd_spacing_m * 0.5 + 2.2 * cfg.pd_radius_m
    r_lens = cfg.rx_lens_diameter_m / 2.0
    positions = pd_grid_positions(cfg.pd_rows, cfg.pd_cols, cfg.pd_spacing_m)

    if z_vac > 1e-9:
        span_out = max(4.0 * r_lens / reducer, 2.0 * array_half)
        n_out = 128
        dx_out = span_out / n_out
        coords_out = (np.arange(n_out) - (n_out - 1) / 2.0) * dx_out
        out_mode = "far-field Zoom-DFT + reducer coordinates"
    else:
        n_out = n
        coords_out = coords / reducer
        dx_out = dx / reducer
        out_mode = "receiver-plane BPM + beam reducer"
    positions = pd_grid_positions(cfg.pd_rows, cfg.pd_cols, cfg.pd_spacing_m)

    tc_vac = dataclasses.replace(tc, n_screens=0)
    field_ref, _ = fso._propagate_numerical_segment_full_field(
        field_in, z_atm, n, dx, lam, tc_vac, geo
    )
    lens_mask_in = (r <= r_lens)
    if z_vac > 1e-9:
        e_ref = fso._propagate_far_field_zoom(
            field_ref[0, :, :, 0] * phase_fres, dx, dx_out, n_out, z_vac, lam
        )
        i_ref = np.abs(e_ref) ** 2
    else:
        i_ref = (np.abs(field_ref[0, :, :, 0]) ** 2) * lens_mask_in * reducer**2
    ref_pd_power, pd_masks = _pd_power_from_intensity(i_ref, coords_out, dx_out, positions, cfg.pd_radius_m)

    intensity_seq = np.zeros((cfg.n_time_frames, n_out, n_out), dtype=np.float32)
    pd_power = np.zeros((cfg.n_time_frames, len(positions)), dtype=np.float64)
    wander_xy = np.zeros((cfg.n_time_frames, 2), dtype=np.float64)
    total_power = np.zeros(cfg.n_time_frames, dtype=np.float64)

    xo, yo = np.meshgrid(coords_out, coords_out, indexing="ij")
    for i in range(cfg.n_time_frames):
        field_t, _ = fso._propagate_numerical_segment_full_field(
            field_in, z_atm, n, dx, lam, tc, geo, seed=cfg.seed_base + i
        )
        if z_vac > 1e-9:
            e_ff = fso._propagate_far_field_zoom(
                field_t[0, :, :, 0] * phase_fres, dx, dx_out, n_out, z_vac, lam
            )
            inten = np.abs(e_ff) ** 2
        else:
            inten = (np.abs(field_t[0, :, :, 0]) ** 2) * lens_mask_in * reducer**2
        intensity_seq[i] = inten.astype(np.float32)
        pd_power[i], _ = _pd_power_from_intensity(inten, coords_out, dx_out, positions, cfg.pd_radius_m)
        pd_power[i] *= max(float(cfg.microlens_gain), 0.0)
        norm = float(np.sum(inten) * dx_out**2) + 1e-30
        wander_xy[i, 0] = float(np.sum(xo * inten) * dx_out**2 / norm)
        wander_xy[i, 1] = float(np.sum(yo * inten) * dx_out**2 / norm)
        total_power[i] = norm

    return {
        "fso": fso,
        "geo": geo,
        "tc": tc,
        "spatial_grid": sg,
        "coords_out": coords_out,
        "dx_out": dx_out,
        "pd_positions": positions,
        "pd_masks": pd_masks,
        "ref_pd_power": ref_pd_power,
        "intensity_seq": intensity_seq,
        "pd_power": pd_power,
        "wander_xy_m": wander_xy,
        "total_power": total_power,
        "r0_m": tc.fried_parameter_m,
        "greenwood_hz": tc.greenwood_freq_hz,
        "link_distance_m": geo.link_distance_m,
        "configured_link_distance_m": cfg.link_distance_m,
        "bpm_n": n,
        "bpm_dx_m": dx,
        "far_n": n_out,
        "far_dx_m": dx_out,
        "output_plane_mode": out_mode,
        "beam_reducer_ratio": reducer,
        "rx_lens_diameter_m": cfg.rx_lens_diameter_m,
    }


def _snr_factors(power_w: np.ndarray, cfg: ColleagueMultiPDConfig, cnn_weights=None):
    p = np.asarray(power_w, dtype=float)
    n_frames, n_pd = p.shape
    positions = np.asarray(pd_grid_positions(cfg.pd_rows, cfg.pd_cols, cfg.pd_spacing_m))
    center_idx = int(np.argmin(np.sum(positions**2, axis=1)))
    ref = float(np.mean(p[:, center_idx]) + 1e-30)
    if cfg.fair_total_aperture and n_pd > 0:
        p = p / n_pd
        ref = ref / n_pd

    factors = {
        "Single center PD": p[:, center_idx] / ref,
        "Selection": np.max(p, axis=1) / ref,
        "EGC": (np.sum(np.sqrt(np.maximum(p, 0.0)), axis=1) ** 2) / (n_pd * ref + 1e-30),
        "MRC oracle": np.sum(p, axis=1) / ref,
    }
    optical_fraction = {
        "Single center PD": p[:, center_idx],
        "Selection": np.max(p, axis=1),
        "EGC": factors["EGC"] * ref,
        "MRC oracle": np.sum(p, axis=1),
    }
    if cnn_weights is not None:
        w = np.asarray(cnn_weights, dtype=float)
        h = np.sqrt(np.maximum(p[-len(w) :], 0.0))
        factors["CNN predicted"] = (np.sum(w * h, axis=1) ** 2) / (
            np.sum(w**2, axis=1) * ref + 1e-30
        )
        optical_fraction["CNN predicted"] = factors["CNN predicted"] * ref
    return factors, center_idx, optical_fraction


def _link_metrics(factors: dict[str, np.ndarray], optical_fraction: dict[str, np.ndarray], cfg: ColleagueMultiPDConfig):
    tx_power_w = dbm_to_w(cfg.tx_power_dbm)
    sys_loss = 10 ** (-cfg.active_system_loss_db / 10.0)
    bw = max(cfg.datarate_bps * 0.75, 1.0)
    i_noise = cfg.receiver_nep_density * np.sqrt(bw)
    # The far-field integration returns received optical power fraction for a
    # unit-power transmitted field. This mirrors the colleague simulator's fixed
    # noise-floor style: turbulence changes signal power while receiver noise
    # stays fixed.
    metrics = {}
    for name, fac in factors.items():
        fac = np.maximum(np.asarray(fac, dtype=float), 1e-9)
        rx_power_w = tx_power_w * sys_loss * np.asarray(optical_fraction[name], dtype=float)
        i_sig = cfg.receiver_responsivity * rx_power_w
        snr_arr = (i_sig / (i_noise + 1e-30)) ** 2
        evm = np.sqrt((100.0 / np.sqrt(np.maximum(snr_arr, 1e-30))) ** 2 + cfg.evm_floor_pct**2)
        evm = np.minimum(evm, 100.0)
        ber = qam_ber_from_evm(evm)
        norm = fac / (np.mean(fac) + 1e-30)
        q = np.percentile(norm, cfg.fade_outage_pct)
        mean_rx_w = float(np.mean(rx_power_w))
        metrics[name] = {
            "mean_evm_pct": float(np.mean(evm)),
            "p95_evm_pct": float(np.percentile(evm, 95.0)),
            "mean_ber": float(np.mean(ber)),
            "outage_probability": float(np.mean(evm > cfg.outage_evm_pct)),
            "required_fade_margin_db": float(-10.0 * np.log10(max(q, 1e-12))),
            "mean_rx_power_dbm": float(w_to_dbm(mean_rx_w)),
            "mean_snr_db": float(10.0 * np.log10(max(np.mean(snr_arr), 1e-30))),
        }
    return metrics


def _adc_from_pd_power(power_w: np.ndarray, cfg: ColleagueMultiPDConfig, rng):
    p = np.asarray(power_w, dtype=float)
    n_frames, n_pd = p.shape
    samples = max(1, int(cfg.samples_per_frame))
    current_frames = cfg.receiver_responsivity * p
    current_samples = np.repeat(current_frames, samples, axis=0).T
    if cfg.current_noise_rms_a > 0:
        current_samples = current_samples + rng.normal(0.0, cfg.current_noise_rms_a, current_samples.shape)
    levels = 2 ** max(int(cfg.adc_bits), 1)
    clipped = np.clip(current_samples, 0.0, cfg.adc_full_scale_a)
    codes = np.rint(clipped / max(cfg.adc_full_scale_a, 1e-30) * (levels - 1)).astype(np.int32)
    quantized = codes.astype(float) / (levels - 1) * cfg.adc_full_scale_a
    return {
        "current_a": current_samples,
        "adc_current_a": quantized,
        "adc_codes": codes,
    }


def train_temporal_cnn(power_w: np.ndarray, cfg: ColleagueMultiPDConfig):
    if torch is None or AIPDNet is None:
        return {"available": False, "history": [], "weights": None, "error": "PyTorch is not available."}

    p = np.asarray(power_w, dtype=np.float32)
    tw = max(2, int(cfg.cnn_time_window))
    rows, cols = int(cfg.pd_rows), int(cfg.pd_cols)
    if p.shape[0] <= tw + 1:
        return {"available": False, "history": [], "weights": None, "error": "Not enough frames for CNN training."}

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

    model = AIPDNet(time_window=tw, rows=rows, cols=cols, phys_dim=1, width=cfg.cnn_width)
    opt = torch.optim.Adam(model.parameters(), lr=cfg.cnn_lr)
    loader = DataLoader(TensorDataset(x, y, true_p), batch_size=min(16, len(x)), shuffle=True)
    history = []
    for epoch in range(max(1, int(cfg.cnn_epochs))):
        total = 0.0
        mse_total = 0.0
        snr_total = 0.0
        n_seen = 0
        for xb, yb, pb in loader:
            pred, _ = model(xb)
            mse = nn.functional.mse_loss(pred, yb)
            weights = torch.softmax(pred.reshape(pred.shape[0], -1), dim=1)
            h = torch.sqrt(torch.clamp(pb.reshape(pb.shape[0], -1), min=1e-9))
            snr_proxy = (torch.sum(weights * h, dim=1) ** 2) / (
                torch.sum(weights**2, dim=1) + 1e-9
            )
            snr_loss = -torch.mean(torch.log(snr_proxy + 1e-9))
            loss = mse + float(cfg.cnn_snr_weight) * snr_loss
            opt.zero_grad()
            loss.backward()
            opt.step()
            b = xb.shape[0]
            total += float(loss.detach()) * b
            mse_total += float(mse.detach()) * b
            snr_total += float(torch.mean(snr_proxy).detach()) * b
            n_seen += b
        history.append(
            {
                "epoch": epoch + 1,
                "loss": total / max(n_seen, 1),
                "mse": mse_total / max(n_seen, 1),
                "snr_proxy": snr_total / max(n_seen, 1),
            }
        )

    model.eval()
    with torch.no_grad():
        pred, _ = model(x)
        weights = torch.softmax(pred.reshape(pred.shape[0], -1), dim=1).cpu().numpy()
        pred_log = pred.cpu().numpy()
    return {
        "available": True,
        "history": history,
        "weights": weights,
        "pred_log": pred_log,
        "time_window": tw,
    }


def run_colleague_multi_pd_link(cfg: ColleagueMultiPDConfig):
    rng = np.random.default_rng(cfg.seed_base)
    seq = _simulate_colleague_uplink_sequence(cfg)
    cnn = train_temporal_cnn(seq["pd_power"], cfg) if cfg.cnn_epochs > 0 else {
        "available": False,
        "history": [],
        "weights": None,
        "error": "CNN training disabled.",
    }
    factors, center_idx, optical_fraction = _snr_factors(seq["pd_power"], cfg, cnn_weights=cnn.get("weights"))
    metrics = _link_metrics(factors, optical_fraction, cfg)
    adc = _adc_from_pd_power(seq["pd_power"], cfg, rng)
    return {
        **seq,
        "cfg": cfg,
        "cnn": cnn,
        "fading_factors": factors,
        "optical_fraction": optical_fraction,
        "metrics": metrics,
        "center_idx": center_idx,
        "adc": adc,
        "external_simulator_path": str(EXTERNAL_FSO),
    }
