import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from scipy.constants import pi

from fso_engine import Receiver_Array, SSFM_Channel


@dataclass
class DatasetConfig:
    rows: int = 2
    cols: int = 4
    spacing_mm: float = 20.0
    origin_x_mm: float = 0.0
    origin_y_mm: float = 0.0
    lens_radius_mm: float = 20.0
    pd_active_radius_um: float = 30.0
    focal_len_mm: float = 50.0
    time_window: int = 12
    horizon: int = 1
    frames: int = 24
    grid_n: int = 256
    n_screens: int = 5
    wavelength_nm: float = 1550.0
    tx_power_dbm: float = 10.0
    pupil_full_width_cm: float = 120.0
    cn2_log10_min: float = -16.0
    cn2_log10_max: float = -13.5
    distance_min_m: float = 400.0
    distance_max_m: float = 2000.0
    wind_min_m_s: float = 1.0
    wind_max_m_s: float = 40.0
    w0_min_mm: float = 1.0
    w0_max_mm: float = 30.0
    l0_m: float = 0.005
    L0_m: float = 50.0
    delta_t_s: float = 0.5e-3
    noise_std_db: float = 0.15


def pd_grid_positions(rows, cols, spacing_mm, origin_x_mm=0.0, origin_y_mm=0.0):
    spacing_m = spacing_mm / 1000.0
    x0_m = origin_x_mm / 1000.0
    y0_m = origin_y_mm / 1000.0
    x_offset = (cols - 1) * spacing_m * 0.5
    y_offset = (rows - 1) * spacing_m * 0.5
    coords = []
    for r in range(rows):
        for c in range(cols):
            coords.append((x0_m + c * spacing_m - x_offset, y0_m + r * spacing_m - y_offset))
    return coords


def sample_physics(rng, cfg):
    log_cn2 = rng.uniform(cfg.cn2_log10_min, cfg.cn2_log10_max)
    L = rng.uniform(cfg.distance_min_m, cfg.distance_max_m)
    wind = rng.uniform(cfg.wind_min_m_s, cfg.wind_max_m_s)
    w0_mm = 10 ** rng.uniform(np.log10(cfg.w0_min_mm), np.log10(cfg.w0_max_mm))
    return {
        "log_cn2": float(log_cn2),
        "Cn2": float(10 ** log_cn2),
        "L": float(L),
        "wind_speed": float(wind),
        "w0_m": float(w0_mm / 1000.0),
        "w0_mm": float(w0_mm),
    }


def simulation_width_m(physics, cfg):
    lam = cfg.wavelength_nm * 1e-9
    w0 = physics["w0_m"]
    L = physics["L"]
    beam_spot = w0 * np.sqrt(1.0 + (lam * L / (pi * w0**2)) ** 2)
    k0 = 2.0 * pi / lam
    rho0 = (0.423 * (k0**2) * physics["Cn2"] * L) ** (-0.6)
    turb_spread = L * lam / rho0
    return max(cfg.pupil_full_width_cm / 100.0, 4.0 * np.sqrt(beam_spot**2 + turb_spread**2))


def simulate_pd_traces(physics, cfg):
    lam = cfg.wavelength_nm * 1e-9
    d_obs = simulation_width_m(physics, cfg)
    params = {
        "N_screens": cfg.n_screens,
        "lam": lam,
        "w0": physics["w0_m"],
        "l0": cfg.l0_m,
        "L0": cfg.L0_m,
        "L": physics["L"],
        "Cn2": physics["Cn2"],
        "wind_speed": physics["wind_speed"],
        "D_obs": d_obs,
        "delta_t": cfg.delta_t_s,
        "n_frames": cfg.frames,
        "N": cfg.grid_n,
    }
    channel = SSFM_Channel(params)
    fields, x_arr, r0_total, _rytov_dz = channel.generate_spatiotemporal_beams()

    dx = d_obs / cfg.grid_n
    tx_power_w = 10 ** ((cfg.tx_power_dbm - 30.0) / 10.0)
    frame_power = np.sum(np.abs(fields) ** 2, axis=(0, 1)) * (dx**2) + 1e-30
    fields_watt = fields * np.sqrt(tx_power_w / frame_power)[None, None, :]

    pd_positions = pd_grid_positions(cfg.rows, cfg.cols, cfg.spacing_mm, cfg.origin_x_mm, cfg.origin_y_mm)
    receiver = Receiver_Array(
        pd_positions,
        cfg.lens_radius_mm / 1000.0,
        cfg.pd_active_radius_um * 1e-6,
        cfg.focal_len_mm / 1000.0,
        x_arr,
        lam,
    )
    _norm, _combined, traces_abs, _combined_abs = receiver.compute_focal_coupling(
        fields_watt, normalize=True, return_absolute=True
    )
    traces = np.asarray(traces_abs, dtype=np.float64).reshape(cfg.rows, cfg.cols, cfg.frames)
    k0 = 2.0 * pi / lam
    rytov_total = 1.23 * physics["Cn2"] * (k0 ** (7.0 / 6.0)) * (physics["L"] ** (11.0 / 6.0))
    return traces, {
        "r0_m": float(r0_total),
        "rytov_total": float(rytov_total),
        "d_obs_m": float(d_obs),
        "dx_m": float(dx),
        "engine_px_per_w0": float(getattr(channel, "px_per_w0", np.nan)),
    }


def make_supervised_samples(traces, physics, meta, cfg, rng):
    # traces: rows, cols, frames
    xs, y_power, y_weight, y_phys = [], [], [], []
    last_start = cfg.frames - cfg.time_window - cfg.horizon
    for t0 in range(max(1, last_start + 1)):
        hist = traces[:, :, t0 : t0 + cfg.time_window]
        future = traces[:, :, t0 + cfg.time_window + cfg.horizon - 1]
        mean_hist = np.mean(hist) + 1e-18

        if cfg.noise_std_db > 0:
            noise_db = rng.normal(0.0, cfg.noise_std_db, size=hist.shape)
            hist = hist * (10.0 ** (noise_db / 10.0))

        x = np.log10(hist / mean_hist + 1e-12).transpose(2, 0, 1)
        y = np.log10(future / mean_hist + 1e-12)
        p = np.maximum(future, 1e-18)
        w = p / (np.sum(p) + 1e-18)
        phys = np.asarray(
            [
                physics["log_cn2"],
                physics["L"] / 1000.0,
                physics["wind_speed"] / 50.0,
                physics["w0_mm"] / 50.0,
                meta["r0_m"],
                meta["rytov_total"],
            ],
            dtype=np.float32,
        )
        xs.append(np.clip(x, -4.0, 4.0).astype(np.float32))
        y_power.append(np.clip(y, -4.0, 4.0).astype(np.float32))
        y_weight.append(w.astype(np.float32))
        y_phys.append(phys)
    return xs, y_power, y_weight, y_phys


def generate_dataset(out_dir, num_sims, shard_size, seed, cfg):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "config.json").write_text(json.dumps(asdict(cfg), indent=2), encoding="utf-8")
    rng = np.random.default_rng(seed)
    buffers = {"x": [], "y_power_log": [], "y_weight": [], "y_phys": []}
    shard_idx = 0

    def flush():
        nonlocal shard_idx, buffers
        if not buffers["x"]:
            return
        path = out / f"shard_{shard_idx:04d}.npz"
        np.savez_compressed(path, **{k: np.asarray(v) for k, v in buffers.items()})
        shard_idx += 1
        buffers = {"x": [], "y_power_log": [], "y_weight": [], "y_phys": []}

    for i in range(num_sims):
        physics = sample_physics(rng, cfg)
        traces, meta = simulate_pd_traces(physics, cfg)
        xs, y_power, y_weight, y_phys = make_supervised_samples(traces, physics, meta, cfg, rng)
        buffers["x"].extend(xs)
        buffers["y_power_log"].extend(y_power)
        buffers["y_weight"].extend(y_weight)
        buffers["y_phys"].extend(y_phys)
        if len(buffers["x"]) >= shard_size:
            flush()
        print(f"[{i + 1}/{num_sims}] logCn2={physics['log_cn2']:.2f}, L={physics['L']:.0f} m, samples={len(xs)}")
    flush()


def main():
    parser = argparse.ArgumentParser(description="Generate PD-array AI training data from FSO simulations.")
    parser.add_argument("--out", default="ai_pd_data")
    parser.add_argument("--num-sims", type=int, default=20)
    parser.add_argument("--shard-size", type=int, default=256)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--rows", type=int, default=2)
    parser.add_argument("--cols", type=int, default=4)
    parser.add_argument("--frames", type=int, default=24)
    parser.add_argument("--time-window", type=int, default=12)
    parser.add_argument("--grid-n", type=int, default=256)
    args = parser.parse_args()

    cfg = DatasetConfig(
        rows=args.rows,
        cols=args.cols,
        frames=args.frames,
        time_window=args.time_window,
        grid_n=args.grid_n,
    )
    generate_dataset(args.out, args.num_sims, args.shard_size, args.seed, cfg)


if __name__ == "__main__":
    main()
