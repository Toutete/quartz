import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from fso_engine import FSOEngineConfig, simulate_fso_sequence


PHYSICS_LABELS = [
    "log10_cn2",
    "distance_km",
    "wind_over_50_mps",
    "beam_waist_over_50_mm",
    "r0_m",
    "rytov_variance",
]


@dataclass
class DatasetConfig:
    rows: int = 4
    cols: int = 4
    pitch_um: float = 250.0
    origin_x_mm: float = 0.0
    origin_y_mm: float = 0.0
    rx_lens_diameter_mm: float = 203.2
    collimated_pupil_mm: float = 7.5
    relay_output_pupil_mm: float = 1.0
    central_obstruction_ratio: float = 0.31
    integrated_lens_diameter_um: float = 100.0
    active_junction_diameter_um: float = 25.0
    external_mla_enabled: bool = False
    external_mla_fill_factor: float = 0.95
    external_mla_efficiency: float = 0.85
    time_window: int = 12
    horizon: int = 1
    frames: int = 24
    grid_n: int = 256
    n_screens: int = 5
    wavelength_nm: float = 1550.0
    tx_power_dbm: float = 20.0
    cn2_log10_min: float = -16.0
    cn2_log10_max: float = -13.5
    distance_min_m: float = 20_000.0
    distance_max_m: float = 20_000.0
    wind_min_m_s: float = 1.0
    wind_max_m_s: float = 40.0
    w0_min_mm: float = 35.0
    w0_max_mm: float = 35.0
    l0_m: float = 0.005
    L0_m: float = 50.0
    delta_t_s: float = 0.5e-3
    noise_std_db: float = 0.15


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


def simulate_pd_traces(physics, cfg):
    grid_mode = "small" if cfg.grid_n <= 256 else "medium" if cfg.grid_n <= 384 else "large"
    sim_cfg = FSOEngineConfig(
        link_direction="downlink",
        hv57_ground_cn2_A=physics["Cn2"],
        wavelength_m=cfg.wavelength_nm * 1e-9,
        link_distance_m=physics["L"],
        tx_aperture_diameter_m=max(0.07, 2.2 * physics["w0_m"]),
        tx_divergence_full_angle_rad=(
            2.0 * cfg.wavelength_nm * 1e-9 / (np.pi * physics["w0_m"])
        ),
        outer_scale_m=cfg.L0_m,
        inner_scale_m=cfg.l0_m,
        n_screens=cfg.n_screens,
        grid_mode=grid_mode,
        n_time_frames=cfg.frames,
        frame_interval_s=cfg.delta_t_s,
        wind_speed_mps=physics["wind_speed"],
        tx_power_dbm=cfg.tx_power_dbm,
        rx_lens_diameter_m=cfg.rx_lens_diameter_mm * 1e-3,
        central_obstruction_ratio=cfg.central_obstruction_ratio,
        collimated_pupil_diameter_m=cfg.collimated_pupil_mm * 1e-3,
        pupil_relay_output_diameter_m=cfg.relay_output_pupil_mm * 1e-3,
        pd_rows=cfg.rows,
        pd_cols=cfg.cols,
        pd_pitch_m=cfg.pitch_um * 1e-6,
        pd_integrated_lens_diameter_m=cfg.integrated_lens_diameter_um * 1e-6,
        pd_active_junction_diameter_m=cfg.active_junction_diameter_um * 1e-6,
        external_mla_enabled=cfg.external_mla_enabled,
        external_mla_fill_factor=cfg.external_mla_fill_factor,
        external_mla_efficiency=cfg.external_mla_efficiency,
        cnn_epochs=0,
    )
    result = simulate_fso_sequence(sim_cfg)
    traces = result["pd_rx_power_w"].T.reshape(cfg.rows, cfg.cols, cfg.frames)
    return traces, {
        "r0_m": float(result["r0_m"]),
        "rytov_total": float(result["rytov_variance"]),
        "d_obs_m": float(result["coords_receiver"][-1] - result["coords_receiver"][0]),
        "dx_m": float(result["dx_receiver"]),
        "engine_px_per_w0": float(physics["w0_m"] / result["bpm_dx_m"]),
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
    config_payload = asdict(cfg)
    config_payload["physics_labels"] = PHYSICS_LABELS
    (out / "config.json").write_text(json.dumps(config_payload, indent=2), encoding="utf-8")
    rng = np.random.default_rng(seed)
    buffers = {"x": [], "y_power_log": [], "y_weight": [], "y_phys": [], "sim_id": []}
    shard_idx = 0

    def flush():
        nonlocal shard_idx, buffers
        if not buffers["x"]:
            return
        path = out / f"shard_{shard_idx:04d}.npz"
        np.savez_compressed(path, **{k: np.asarray(v) for k, v in buffers.items()})
        shard_idx += 1
        buffers = {"x": [], "y_power_log": [], "y_weight": [], "y_phys": [], "sim_id": []}

    for i in range(num_sims):
        physics = sample_physics(rng, cfg)
        traces, meta = simulate_pd_traces(physics, cfg)
        xs, y_power, y_weight, y_phys = make_supervised_samples(traces, physics, meta, cfg, rng)
        buffers["x"].extend(xs)
        buffers["y_power_log"].extend(y_power)
        buffers["y_weight"].extend(y_weight)
        buffers["y_phys"].extend(y_phys)
        buffers["sim_id"].extend([i] * len(xs))
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
    parser.add_argument("--rows", type=int, default=4)
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
