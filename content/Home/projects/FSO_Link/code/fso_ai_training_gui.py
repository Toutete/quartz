import json
import queue
import threading
import traceback
from pathlib import Path

import numpy as np
import tkinter as tk
from tkinter import messagebox, ttk

import matplotlib

matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from scipy.constants import pi

from ai_pd_dataset import DatasetConfig, make_supervised_samples, sample_physics, simulate_pd_traces
from ai_pd_model import AIPDNet, weights_from_power_log
from fso_engine import ENGINE_BUILD_TAG, Receiver_Array, SSFM_Channel


try:
    import torch
    from torch import nn
    from torch.utils.data import DataLoader, Dataset, random_split
except Exception:
    torch = None
    nn = None
    DataLoader = None
    Dataset = object
    random_split = None


class InMemoryPDDataset(Dataset):
    def __init__(self, x, y_power_log, y_weight, y_phys):
        self.x = np.asarray(x, dtype=np.float32)
        self.y_power_log = np.asarray(y_power_log, dtype=np.float32)
        self.y_weight = np.asarray(y_weight, dtype=np.float32)
        self.y_phys = np.asarray(y_phys, dtype=np.float32)

    def __len__(self):
        return self.x.shape[0]

    def __getitem__(self, idx):
        return {
            "x": torch.from_numpy(self.x[idx]),
            "y_power_log": torch.from_numpy(self.y_power_log[idx]),
            "y_weight": torch.from_numpy(self.y_weight[idx]),
            "y_phys": torch.from_numpy(self.y_phys[idx]),
        }


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


def simulation_width_m(physics, lam, pupil_full_width_cm):
    beam_spot = physics["w0_m"] * np.sqrt(1.0 + (lam * physics["L"] / (pi * physics["w0_m"] ** 2)) ** 2)
    if physics["Cn2"] > 0:
        k0 = 2.0 * pi / lam
        rho0 = (0.423 * (k0**2) * physics["Cn2"] * physics["L"]) ** (-0.6)
        turb_spread = physics["L"] * lam / rho0
    else:
        turb_spread = 0.0
    return max(pupil_full_width_cm / 100.0, 4.0 * np.sqrt(beam_spot**2 + turb_spread**2))


def scale_fields_to_power(fields, d_obs, tx_power_dbm):
    dx = d_obs / fields.shape[0]
    tx_power_w = 10 ** ((tx_power_dbm - 30.0) / 10.0)
    frame_power = np.sum(np.abs(fields) ** 2, axis=(0, 1)) * (dx**2) + 1e-30
    return fields * np.sqrt(tx_power_w / frame_power)[None, None, :], dx


class FSOAITrainingGUI:
    def __init__(self, master):
        self.master = master
        self.master.title("FSO AI Receiver Training GUI")
        self.master.geometry("1500x930")
        self.queue = queue.Queue()
        self.sim_result = None
        self.train_history = []
        self._busy = False

        self._build_layout()
        self._poll_queue()

    def _build_layout(self):
        self.side = ttk.Frame(self.master, padding=10, width=360)
        self.side.pack(side=tk.LEFT, fill=tk.Y)

        title = ttk.Label(self.side, text="AI Multi-PD FSO Receiver", font=("Segoe UI", 12, "bold"))
        title.pack(anchor=tk.W, pady=(0, 8))

        self.inputs = {}
        self._add_section("SSFM Simulation")
        for key, label, default in [
            ("L", "Distance L (m)", "800"),
            ("Cn2", "Cn2", "1e-15"),
            ("N_screens", "Phase screens", "5"),
            ("wind_speed", "Wind speed (m/s)", "15"),
            ("w0_mm", "Beam waist w0 (mm)", "1.0"),
            ("grid_n", "Grid N", "128"),
            ("frames", "Frames", "16"),
            ("pupil_full_width_cm", "Display zoom width (cm)", "120"),
            ("tx_power_dbm", "Tx power (dBm)", "10"),
        ]:
            self._entry(key, label, default)

        self._add_section("PD Array")
        for key, label, default in [
            ("pd_rows", "Rows", "2"),
            ("pd_cols", "Cols", "4"),
            ("pd_spacing_mm", "Spacing (mm)", "20"),
            ("lens_radius_mm", "Lens radius (mm)", "20"),
            ("pd_active_radius_um", "PD active radius (um)", "30"),
            ("focal_len_mm", "Focal length (mm)", "50"),
            ("time_window", "AI time window", "8"),
        ]:
            self._entry(key, label, default)

        self._add_section("CNN Training")
        for key, label, default in [
            ("train_sims", "Training sims", "4"),
            ("epochs", "Epochs", "8"),
            ("batch_size", "Batch size", "16"),
            ("cnn_width", "CNN width", "16"),
            ("lr", "Learning rate", "2e-4"),
            ("snr_weight", "SNR objective weight", "1.0"),
            ("aux_weight", "Aux loss weight", "0.02"),
            ("power_weight", "Power loss weight", "0.05"),
        ]:
            self._entry(key, label, default)

        ttk.Separator(self.side).pack(fill=tk.X, pady=10)
        self.run_sim_btn = ttk.Button(self.side, text="Run SSFM Simulation", command=self.run_simulation)
        self.run_sim_btn.pack(fill=tk.X, pady=3, ipady=4)
        self.train_btn = ttk.Button(self.side, text="Generate Dataset + Train CNN", command=self.run_training)
        self.train_btn.pack(fill=tk.X, pady=3, ipady=4)
        self.save_btn = ttk.Button(self.side, text="Save Current Dataset Snapshot", command=self.save_snapshot)
        self.save_btn.pack(fill=tk.X, pady=3)

        self.progress = ttk.Progressbar(self.side, mode="determinate")
        self.progress.pack(fill=tk.X, pady=(10, 4))
        self.status = tk.StringVar(value="Ready")
        ttk.Label(self.side, textvariable=self.status, wraplength=330, foreground="blue").pack(anchor=tk.W)

        self.metrics = tk.Text(self.side, height=12, width=42)
        self.metrics.pack(fill=tk.BOTH, expand=False, pady=(10, 0))
        self._set_metrics(
            {
                "engine": ENGINE_BUILD_TAG,
                "simulation": "not run",
                "training": "not run",
            }
        )

        self.notebook = ttk.Notebook(self.master)
        self.notebook.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        self.sim_tab = ttk.Frame(self.notebook)
        self.train_tab = ttk.Frame(self.notebook)
        self.model_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.sim_tab, text="Simulation and PD Trace")
        self.notebook.add(self.train_tab, text="CNN Training")
        self.notebook.add(self.model_tab, text="Model Structure")

        self._build_sim_tab()
        self._build_train_tab()
        self._build_model_tab()

    def _add_section(self, text):
        ttk.Separator(self.side).pack(fill=tk.X, pady=(10, 6))
        ttk.Label(self.side, text=text, font=("Segoe UI", 10, "bold")).pack(anchor=tk.W)

    def _entry(self, key, label, default):
        row = ttk.Frame(self.side)
        row.pack(fill=tk.X, pady=2)
        ttk.Label(row, text=label, width=24).pack(side=tk.LEFT)
        ent = ttk.Entry(row, width=12)
        ent.insert(0, default)
        ent.pack(side=tk.RIGHT)
        self.inputs[key] = ent

    def _build_sim_tab(self):
        toolbar = ttk.Frame(self.sim_tab, padding=6)
        toolbar.pack(fill=tk.X)
        ttk.Label(toolbar, text="Frame").pack(side=tk.LEFT)
        self.frame_var = tk.IntVar(value=0)
        self.frame_slider = ttk.Scale(toolbar, from_=0, to=0, orient=tk.HORIZONTAL, command=self._on_frame_slider)
        self.frame_slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)
        ttk.Button(toolbar, text="Update View", command=self._redraw_current_frame).pack(side=tk.LEFT, padx=4)
        self.frame_label = ttk.Label(toolbar, text="0 / 0")
        self.frame_label.pack(side=tk.RIGHT)

        self.fig_sim = Figure(figsize=(10, 7), dpi=100)
        self.ax_intensity = self.fig_sim.add_subplot(2, 2, 1)
        self.ax_phase = self.fig_sim.add_subplot(2, 2, 2)
        self.ax_pd_heat = self.fig_sim.add_subplot(2, 2, 3)
        self.ax_trace = self.fig_sim.add_subplot(2, 2, 4)
        self.fig_sim.tight_layout()
        self.canvas_sim = FigureCanvasTkAgg(self.fig_sim, master=self.sim_tab)
        self.canvas_sim.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self._draw_empty_sim()

    def _build_train_tab(self):
        self.fig_train = Figure(figsize=(10, 7), dpi=100)
        self.ax_loss = self.fig_train.add_subplot(2, 2, 1)
        self.ax_gain = self.fig_train.add_subplot(2, 2, 2)
        self.ax_weight = self.fig_train.add_subplot(2, 2, 3)
        self.ax_gap = self.fig_train.add_subplot(2, 2, 4)
        self.fig_train.tight_layout()
        self.canvas_train = FigureCanvasTkAgg(self.fig_train, master=self.train_tab)
        self.canvas_train.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self._draw_empty_training()

    def _build_model_tab(self):
        text = tk.Text(self.model_tab, wrap=tk.WORD, font=("Consolas", 10))
        text.pack(fill=tk.BOTH, expand=True)
        text.insert(
            tk.END,
            "Current GUI model\n"
            "=================\n\n"
            "Input:\n"
            "  PD power window shaped [batch, time_window, rows, cols]\n\n"
            "Network:\n"
            "  AIPDNet from ai_pd_model.py\n"
            "  Conv2d -> BatchNorm -> ReLU\n"
            "  depthwise Conv2d -> pointwise Conv2d -> BatchNorm -> ReLU\n"
            "  depthwise Conv2d -> pointwise Conv2d -> BatchNorm -> ReLU\n"
            "  power head: Linear -> ReLU -> Linear\n"
            "  physical-parameter head: AvgPool -> Linear -> ReLU -> Linear\n\n"
            "Training objective used by this GUI:\n"
            "  main: maximize power-domain SNR proxy gain over equal combining\n"
            "  optional stabilizers: future-power MSE, physics-label MSE\n\n"
            "Outputs:\n"
            "  future PD power map\n"
            "  combining weights from softmax(future power map)\n"
            "  physical state estimates\n\n"
            "Future extension:\n"
            "  add Zernike coefficient labels from aperture phase\n"
            "  add energy consistency and temporal smoothness losses\n"
            "  replace SNR proxy with EVM/BER-aware differentiable objective\n",
        )
        text.configure(state=tk.DISABLED)

    def _float(self, key):
        return float(self.inputs[key].get())

    def _int(self, key):
        return int(float(self.inputs[key].get()))

    def _config(self):
        return {
            "L": self._float("L"),
            "Cn2": self._float("Cn2"),
            "N_screens": max(1, self._int("N_screens")),
            "wind_speed": self._float("wind_speed"),
            "w0_m": self._float("w0_mm") / 1000.0,
            "grid_n": max(32, self._int("grid_n")),
            "frames": max(2, self._int("frames")),
            "pupil_full_width_cm": self._float("pupil_full_width_cm"),
            "tx_power_dbm": self._float("tx_power_dbm"),
            "pd_rows": max(1, self._int("pd_rows")),
            "pd_cols": max(1, self._int("pd_cols")),
            "pd_spacing_mm": self._float("pd_spacing_mm"),
            "lens_radius_mm": self._float("lens_radius_mm"),
            "pd_active_radius_um": self._float("pd_active_radius_um"),
            "focal_len_mm": self._float("focal_len_mm"),
            "time_window": max(2, self._int("time_window")),
        }

    def _dataset_config(self):
        cfg = self._config()
        return DatasetConfig(
            rows=cfg["pd_rows"],
            cols=cfg["pd_cols"],
            spacing_mm=cfg["pd_spacing_mm"],
            lens_radius_mm=cfg["lens_radius_mm"],
            pd_active_radius_um=cfg["pd_active_radius_um"],
            focal_len_mm=cfg["focal_len_mm"],
            time_window=cfg["time_window"],
            horizon=1,
            frames=max(cfg["frames"], cfg["time_window"] + 2),
            grid_n=cfg["grid_n"],
            n_screens=cfg["N_screens"],
            tx_power_dbm=cfg["tx_power_dbm"],
            pupil_full_width_cm=cfg["pupil_full_width_cm"],
            distance_min_m=max(1.0, cfg["L"] * 0.9),
            distance_max_m=max(2.0, cfg["L"] * 1.1),
            wind_min_m_s=max(0.1, cfg["wind_speed"] * 0.6),
            wind_max_m_s=max(0.2, cfg["wind_speed"] * 1.4),
            w0_min_mm=max(0.1, self._float("w0_mm") * 0.7),
            w0_max_mm=max(0.2, self._float("w0_mm") * 1.3),
        )

    def _set_busy(self, busy, message):
        self._busy = busy
        state = tk.DISABLED if busy else tk.NORMAL
        self.run_sim_btn.configure(state=state)
        self.train_btn.configure(state=state)
        self.save_btn.configure(state=state)
        self.status.set(message)

    def _set_metrics(self, values):
        self.metrics.configure(state=tk.NORMAL)
        self.metrics.delete("1.0", tk.END)
        for key, value in values.items():
            self.metrics.insert(tk.END, f"{key}: {value}\n")
        self.metrics.configure(state=tk.DISABLED)

    def _draw_empty_sim(self):
        for ax, title in [
            (self.ax_intensity, "Pupil power distribution"),
            (self.ax_phase, "Pupil phase"),
            (self.ax_pd_heat, "PD power map"),
            (self.ax_trace, "PD power traces vs time"),
        ]:
            ax.clear()
            ax.set_title(title)
            ax.text(0.5, 0.5, "Run simulation", ha="center", va="center", transform=ax.transAxes)
        self.canvas_sim.draw_idle()

    def _draw_empty_training(self):
        for ax, title in [
            (self.ax_loss, "Training objective"),
            (self.ax_gain, "SNR proxy gain"),
            (self.ax_weight, "Predicted combiner weights"),
            (self.ax_gap, "Oracle gap"),
        ]:
            ax.clear()
            ax.set_title(title)
            ax.text(0.5, 0.5, "Run training", ha="center", va="center", transform=ax.transAxes)
        self.canvas_train.draw_idle()

    def run_simulation(self):
        if self._busy:
            return
        try:
            cfg = self._config()
        except Exception as exc:
            messagebox.showerror("Input error", str(exc))
            return
        self._set_busy(True, "Running SSFM simulation...")
        self.progress.configure(value=0, maximum=100)
        threading.Thread(target=self._simulation_worker, args=(cfg,), daemon=True).start()

    def _simulation_worker(self, cfg):
        try:
            lam = 1550e-9
            physics = {
                "log_cn2": float(np.log10(cfg["Cn2"])) if cfg["Cn2"] > 0 else -99.0,
                "Cn2": cfg["Cn2"],
                "L": cfg["L"],
                "wind_speed": cfg["wind_speed"],
                "w0_m": cfg["w0_m"],
                "w0_mm": cfg["w0_m"] * 1000.0,
            }
            d_obs = simulation_width_m(physics, lam, cfg["pupil_full_width_cm"])
            params = {
                "N_screens": cfg["N_screens"],
                "lam": lam,
                "w0": cfg["w0_m"],
                "l0": 0.005,
                "L0": 50.0,
                "L": cfg["L"],
                "Cn2": cfg["Cn2"],
                "wind_speed": cfg["wind_speed"],
                "D_obs": d_obs,
                "delta_t": 0.5e-3,
                "n_frames": cfg["frames"],
                "N": cfg["grid_n"],
            }
            channel = SSFM_Channel(params)
            fields, x_arr, r0_total, rytov_dz = channel.generate_spatiotemporal_beams()
            fields_watt, dx = scale_fields_to_power(fields, d_obs, cfg["tx_power_dbm"])

            pd_positions = pd_grid_positions(cfg["pd_rows"], cfg["pd_cols"], cfg["pd_spacing_mm"])
            receiver = Receiver_Array(
                pd_positions,
                cfg["lens_radius_mm"] / 1000.0,
                cfg["pd_active_radius_um"] * 1e-6,
                cfg["focal_len_mm"] / 1000.0,
                x_arr,
                lam,
            )
            _norm, _combined, traces_abs, combined_abs = receiver.compute_focal_coupling(
                fields_watt, normalize=True, return_absolute=True
            )
            traces = np.asarray(traces_abs, dtype=np.float64).reshape(cfg["pd_rows"], cfg["pd_cols"], cfg["frames"])
            k0 = 2.0 * pi / lam
            rytov_total = 1.23 * cfg["Cn2"] * (k0 ** (7.0 / 6.0)) * (cfg["L"] ** (11.0 / 6.0))
            result = {
                "cfg": cfg,
                "fields": fields_watt,
                "x_arr": x_arr,
                "traces": traces,
                "combined_abs": np.asarray(combined_abs),
                "pd_positions": pd_positions,
                "r0_total": r0_total,
                "rytov_dz": rytov_dz,
                "rytov_total": rytov_total,
                "d_obs": d_obs,
                "dx": dx,
                "channel": {
                    "alias_metric": getattr(channel, "alias_metric", np.nan),
                    "substeps_per_screen": getattr(channel, "substeps_per_screen", np.nan),
                    "propagation_mode": getattr(channel, "propagation_mode", "unknown"),
                    "px_per_w0": getattr(channel, "px_per_w0", np.nan),
                },
            }
            self.queue.put(("sim_done", result))
        except Exception:
            self.queue.put(("error", traceback.format_exc()))

    def _on_frame_slider(self, _value):
        if self.sim_result is None:
            return
        frame = int(round(float(self.frame_slider.get())))
        self._draw_simulation(frame)

    def _redraw_current_frame(self):
        if self.sim_result is None:
            return
        self._draw_simulation(int(round(float(self.frame_slider.get()))))

    def _draw_simulation(self, frame=0):
        res = self.sim_result
        if res is None:
            return
        fields = res["fields"]
        traces = res["traces"]
        x_cm = res["x_arr"] * 100.0
        extent = [x_cm[0], x_cm[-1], x_cm[0], x_cm[-1]]
        frame = int(np.clip(frame, 0, fields.shape[2] - 1))
        self.frame_label.configure(text=f"{frame + 1} / {fields.shape[2]}")

        intensity = np.abs(fields[:, :, frame]) ** 2
        phase = np.angle(fields[:, :, frame])
        pd_map = traces[:, :, frame]
        times_ms = np.arange(traces.shape[2]) * 0.5

        self.ax_intensity.clear()
        im0 = self.ax_intensity.imshow(10 * np.log10(intensity * 1000 + 1e-30), extent=extent, origin="lower")
        self.ax_intensity.set_title("1-1 Pupil power distribution")
        self.ax_intensity.set_xlabel("x (cm)")
        self.ax_intensity.set_ylabel("y (cm)")
        for i, (x_m, y_m) in enumerate(res["pd_positions"]):
            self.ax_intensity.plot(x_m * 100.0, y_m * 100.0, "wo", ms=5, mec="black")
            self.ax_intensity.text(x_m * 100.0, y_m * 100.0, str(i + 1), color="black", fontsize=8)

        self.ax_phase.clear()
        self.ax_phase.imshow(phase, extent=extent, origin="lower", cmap="twilight")
        self.ax_phase.set_title("1-2 Pupil phase over time")
        self.ax_phase.set_xlabel("x (cm)")
        self.ax_phase.set_ylabel("y (cm)")
        try:
            view_width_cm = self._float("pupil_full_width_cm")
        except Exception:
            view_width_cm = float(res["cfg"]["pupil_full_width_cm"])
        view_half_cm = max(0.1, view_width_cm * 0.5)
        for ax in (self.ax_intensity, self.ax_phase):
            ax.set_xlim(-view_half_cm, view_half_cm)
            ax.set_ylim(-view_half_cm, view_half_cm)
            ax.set_aspect("equal", adjustable="box")

        self.ax_pd_heat.clear()
        self.ax_pd_heat.imshow(pd_map, origin="upper", cmap="viridis")
        self.ax_pd_heat.set_title("1-3 PD placement / current map")
        for r in range(pd_map.shape[0]):
            for c in range(pd_map.shape[1]):
                self.ax_pd_heat.text(c, r, f"{pd_map[r, c]:.1e}", ha="center", va="center", fontsize=8, color="white")
        self.ax_pd_heat.set_xticks(range(pd_map.shape[1]))
        self.ax_pd_heat.set_yticks(range(pd_map.shape[0]))

        self.ax_trace.clear()
        flat = traces.reshape(-1, traces.shape[2])
        for i, tr in enumerate(flat):
            self.ax_trace.plot(times_ms, 10 * np.log10(tr + 1e-30), lw=1.0, label=f"PD{i + 1}")
        self.ax_trace.plot(times_ms, 10 * np.log10(res["combined_abs"] + 1e-30), "k--", lw=1.5, label="sum")
        self.ax_trace.axvline(times_ms[frame], color="red", alpha=0.5)
        self.ax_trace.set_title("1-4 PD power trace vs time")
        self.ax_trace.set_xlabel("time (ms)")
        self.ax_trace.set_ylabel("power (dBW)")
        self.ax_trace.legend(fontsize=7, ncol=2)

        self.fig_sim.tight_layout()
        self.canvas_sim.draw_idle()

    def run_training(self):
        if self._busy:
            return
        if torch is None:
            messagebox.showerror("PyTorch missing", "PyTorch is not available in this Python environment.")
            return
        try:
            cfg = self._dataset_config()
            train_args = {
                "num_sims": max(1, self._int("train_sims")),
                "epochs": max(1, self._int("epochs")),
                "batch_size": max(1, self._int("batch_size")),
                "width": max(4, self._int("cnn_width")),
                "lr": self._float("lr"),
                "snr_weight": self._float("snr_weight"),
                "aux_weight": self._float("aux_weight"),
                "power_weight": self._float("power_weight"),
            }
        except Exception as exc:
            messagebox.showerror("Input error", str(exc))
            return
        self.train_history = []
        self._draw_empty_training()
        self._set_busy(True, "Generating training simulations...")
        self.progress.configure(value=0, maximum=train_args["num_sims"] + train_args["epochs"])
        threading.Thread(target=self._training_worker, args=(cfg, train_args), daemon=True).start()

    def _training_worker(self, cfg, train_args):
        try:
            rng = np.random.default_rng(23)
            buffers = {"x": [], "y_power_log": [], "y_weight": [], "y_phys": []}
            for i in range(train_args["num_sims"]):
                physics = sample_physics(rng, cfg)
                traces, meta = simulate_pd_traces(physics, cfg)
                xs, y_power, y_weight, y_phys = make_supervised_samples(traces, physics, meta, cfg, rng)
                buffers["x"].extend(xs)
                buffers["y_power_log"].extend(y_power)
                buffers["y_weight"].extend(y_weight)
                buffers["y_phys"].extend(y_phys)
                self.queue.put(("progress", i + 1, f"Generated sim {i + 1}/{train_args['num_sims']}"))

            dataset = InMemoryPDDataset(
                buffers["x"],
                buffers["y_power_log"],
                buffers["y_weight"],
                buffers["y_phys"],
            )
            if len(dataset) < 2:
                raise RuntimeError("Not enough samples. Increase frames or number of simulations.")

            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            n_val = max(1, int(len(dataset) * 0.2))
            n_train = len(dataset) - n_val
            train_ds, val_ds = random_split(dataset, [n_train, n_val], generator=torch.Generator().manual_seed(23))
            loader_train = DataLoader(train_ds, batch_size=train_args["batch_size"], shuffle=True)
            loader_val = DataLoader(val_ds, batch_size=train_args["batch_size"], shuffle=False)

            y_phys_all = torch.from_numpy(dataset.y_phys)
            phys_mean = y_phys_all.mean(dim=0).to(device)
            phys_std = y_phys_all.std(dim=0).clamp_min(1e-6).to(device)
            model = AIPDNet(
                time_window=dataset.x.shape[1],
                rows=dataset.x.shape[2],
                cols=dataset.x.shape[3],
                phys_dim=dataset.y_phys.shape[1],
                width=train_args["width"],
            ).to(device)
            opt = torch.optim.Adam(model.parameters(), lr=train_args["lr"])
            mse = nn.MSELoss()
            best = None
            best_val_loss = float("inf")
            local_history = []

            for epoch in range(1, train_args["epochs"] + 1):
                train_loss = self._run_snr_epoch(
                    model, loader_train, opt, device, phys_mean, phys_std, mse, train_args
                )
                val_metrics = self._eval_snr_epoch(model, loader_val, device, phys_mean, phys_std, mse, train_args)
                if val_metrics["loss"] < best_val_loss:
                    best_val_loss = val_metrics["loss"]
                    best = {
                        "model": model.state_dict(),
                        "model_args": {
                            "time_window": dataset.x.shape[1],
                            "rows": dataset.x.shape[2],
                            "cols": dataset.x.shape[3],
                            "phys_dim": dataset.y_phys.shape[1],
                            "width": train_args["width"],
                        },
                        "phys_mean": phys_mean.detach().cpu(),
                        "phys_std": phys_std.detach().cpu(),
                        "gui_training_args": train_args,
                    }
                row = {
                    "epoch": epoch,
                    "train_loss": train_loss,
                    **val_metrics,
                }
                local_history.append(row)
                self.queue.put(
                    (
                        "train_epoch",
                        train_args["num_sims"] + epoch,
                        row,
                        f"Epoch {epoch}/{train_args['epochs']}: gain={val_metrics['pred_vs_equal_gain_db']:.3f} dB",
                    )
                )

            out_dir = Path("ai_pd_gui_runs")
            out_dir.mkdir(parents=True, exist_ok=True)
            if best is not None:
                torch.save(best, out_dir / "best_ai_pd_gui.pt")
            with (out_dir / "last_gui_history.json").open("w", encoding="utf-8") as f:
                json.dump(local_history, f, indent=2)
            self.queue.put(("train_done", str(out_dir / "best_ai_pd_gui.pt"), len(dataset)))
        except Exception:
            self.queue.put(("error", traceback.format_exc()))

    def _run_snr_epoch(self, model, loader, optimizer, device, phys_mean, phys_std, mse, args):
        model.train()
        total = 0.0
        count = 0
        for batch in loader:
            batch = {k: v.to(device) for k, v in batch.items()}
            pred_power, pred_phys_norm = model(batch["x"])
            pred_weight = weights_from_power_log(pred_power)
            true_power_lin = torch.pow(10.0, batch["y_power_log"].reshape(batch["x"].shape[0], -1))
            pred_w_flat = pred_weight.reshape(batch["x"].shape[0], -1)
            pred_combined = torch.sum(pred_w_flat * true_power_lin, dim=1)
            equal_combined = torch.mean(true_power_lin, dim=1)
            snr_gain_db = 10.0 * torch.log10((pred_combined + 1e-12) / (equal_combined + 1e-12))
            loss_snr = -snr_gain_db.mean()
            loss_power = mse(pred_power, batch["y_power_log"])
            y_phys_norm = (batch["y_phys"] - phys_mean) / phys_std
            loss_aux = mse(pred_phys_norm, y_phys_norm)
            loss = args["snr_weight"] * loss_snr + args["power_weight"] * loss_power + args["aux_weight"] * loss_aux
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            bs = batch["x"].shape[0]
            total += float(loss.detach()) * bs
            count += bs
        return total / max(count, 1)

    def _eval_snr_epoch(self, model, loader, device, phys_mean, phys_std, mse, args):
        model.eval()
        totals = {
            "loss": 0.0,
            "power_mse": 0.0,
            "phys_mse": 0.0,
            "weight_mse": 0.0,
            "pred_vs_equal_gain_db": 0.0,
            "oracle_vs_equal_gain_db": 0.0,
            "pred_vs_oracle_gap_db": 0.0,
        }
        count = 0
        last_weight = None
        with torch.no_grad():
            for batch in loader:
                batch = {k: v.to(device) for k, v in batch.items()}
                pred_power, pred_phys_norm = model(batch["x"])
                pred_weight = weights_from_power_log(pred_power)
                true_power_lin = torch.pow(10.0, batch["y_power_log"].reshape(batch["x"].shape[0], -1))
                pred_w_flat = pred_weight.reshape(batch["x"].shape[0], -1)
                true_w_flat = batch["y_weight"].reshape(batch["x"].shape[0], -1)
                pred_combined = torch.sum(pred_w_flat * true_power_lin, dim=1)
                equal_combined = torch.mean(true_power_lin, dim=1)
                oracle_combined = torch.sum(true_w_flat * true_power_lin, dim=1)
                pred_gain = 10.0 * torch.log10((pred_combined + 1e-12) / (equal_combined + 1e-12))
                oracle_gain = 10.0 * torch.log10((oracle_combined + 1e-12) / (equal_combined + 1e-12))
                gap = oracle_gain - pred_gain
                loss_snr = -pred_gain.mean()
                loss_power = mse(pred_power, batch["y_power_log"])
                y_phys_norm = (batch["y_phys"] - phys_mean) / phys_std
                loss_aux = mse(pred_phys_norm, y_phys_norm)
                loss = args["snr_weight"] * loss_snr + args["power_weight"] * loss_power + args["aux_weight"] * loss_aux
                loss_weight = mse(pred_weight, batch["y_weight"])
                bs = batch["x"].shape[0]
                totals["loss"] += float(loss) * bs
                totals["power_mse"] += float(loss_power) * bs
                totals["phys_mse"] += float(loss_aux) * bs
                totals["weight_mse"] += float(loss_weight) * bs
                totals["pred_vs_equal_gain_db"] += float(pred_gain.mean()) * bs
                totals["oracle_vs_equal_gain_db"] += float(oracle_gain.mean()) * bs
                totals["pred_vs_oracle_gap_db"] += float(gap.mean()) * bs
                count += bs
                last_weight = pred_weight[0].detach().cpu().numpy().tolist()
        out = {k: v / max(count, 1) for k, v in totals.items()}
        out["last_weight"] = last_weight
        return out

    def _draw_training(self):
        hist = self.train_history
        if not hist:
            self._draw_empty_training()
            return
        epochs = [h["epoch"] for h in hist]
        self.ax_loss.clear()
        self.ax_loss.plot(epochs, [h["train_loss"] for h in hist], label="train")
        self.ax_loss.plot(epochs, [h["loss"] for h in hist], label="val")
        self.ax_loss.set_title("2 CNN objective")
        self.ax_loss.set_xlabel("epoch")
        self.ax_loss.set_ylabel("loss")
        self.ax_loss.legend()
        self.ax_loss.grid(True, alpha=0.3)

        self.ax_gain.clear()
        self.ax_gain.plot(epochs, [h["pred_vs_equal_gain_db"] for h in hist], label="AI vs equal")
        self.ax_gain.plot(epochs, [h["oracle_vs_equal_gain_db"] for h in hist], label="oracle vs equal")
        self.ax_gain.set_title("2-1 Performance improvement")
        self.ax_gain.set_xlabel("epoch")
        self.ax_gain.set_ylabel("SNR proxy gain (dB)")
        self.ax_gain.legend()
        self.ax_gain.grid(True, alpha=0.3)

        self.ax_weight.clear()
        weight = hist[-1].get("last_weight")
        if weight is not None:
            weight = np.asarray(weight, dtype=float)
            self.ax_weight.imshow(weight, origin="upper", cmap="viridis")
            for r in range(weight.shape[0]):
                for c in range(weight.shape[1]):
                    self.ax_weight.text(c, r, f"{weight[r, c]:.2f}", ha="center", va="center", color="white", fontsize=9)
        self.ax_weight.set_title("Predicted combining weights")

        self.ax_gap.clear()
        self.ax_gap.plot(epochs, [h["pred_vs_oracle_gap_db"] for h in hist], color="tab:red")
        self.ax_gap.set_title("Gap to oracle")
        self.ax_gap.set_xlabel("epoch")
        self.ax_gap.set_ylabel("oracle - AI (dB)")
        self.ax_gap.grid(True, alpha=0.3)

        self.fig_train.tight_layout()
        self.canvas_train.draw_idle()

    def save_snapshot(self):
        if self.sim_result is None:
            messagebox.showinfo("No simulation", "Run a simulation first.")
            return
        out = Path("ai_pd_gui_runs")
        out.mkdir(parents=True, exist_ok=True)
        path = out / "last_simulation_snapshot.npz"
        np.savez_compressed(
            path,
            traces=self.sim_result["traces"],
            combined_abs=self.sim_result["combined_abs"],
            x_arr=self.sim_result["x_arr"],
            cfg=json.dumps(self.sim_result["cfg"]),
        )
        self.status.set(f"Saved {path}")

    def _poll_queue(self):
        try:
            while True:
                item = self.queue.get_nowait()
                kind = item[0]
                if kind == "progress":
                    _, value, message = item
                    self.progress.configure(value=value)
                    self.status.set(message)
                elif kind == "sim_done":
                    self.sim_result = item[1]
                    n_frames = self.sim_result["fields"].shape[2]
                    self.frame_slider.configure(from_=0, to=n_frames - 1)
                    self.frame_slider.set(0)
                    self.progress.configure(value=100)
                    self._draw_simulation(0)
                    self._set_busy(False, "Simulation complete")
                    metrics = {
                        "simulation": "complete",
                        "grid": f"{self.sim_result['cfg']['grid_n']} x {self.sim_result['cfg']['grid_n']}",
                        "frames": self.sim_result["cfg"]["frames"],
                        "PD channels": int(np.prod(self.sim_result["traces"].shape[:2])),
                        "r0_total_m": f"{self.sim_result['r0_total']:.3e}",
                        "Rytov_total": f"{self.sim_result['rytov_total']:.3f}",
                        "propagation": self.sim_result["channel"]["propagation_mode"],
                        "alias_metric": f"{self.sim_result['channel']['alias_metric']:.3f}",
                    }
                    self._set_metrics(metrics)
                elif kind == "train_epoch":
                    _, value, row, message = item
                    self.progress.configure(value=value)
                    self.status.set(message)
                    self.train_history.append(row)
                    self._draw_training()
                    self._set_metrics(
                        {
                            "training": "running",
                            "epoch": row["epoch"],
                            "train_loss": f"{row['train_loss']:.4f}",
                            "val_loss": f"{row['loss']:.4f}",
                            "AI vs equal": f"{row['pred_vs_equal_gain_db']:.3f} dB",
                            "oracle vs equal": f"{row['oracle_vs_equal_gain_db']:.3f} dB",
                            "oracle gap": f"{row['pred_vs_oracle_gap_db']:.3f} dB",
                            "weight_mse": f"{row['weight_mse']:.4e}",
                        }
                    )
                elif kind == "train_done":
                    _, path, n_samples = item
                    self._set_busy(False, f"Training complete. Saved {path}")
                    self._set_metrics(
                        {
                            "training": "complete",
                            "samples": n_samples,
                            "checkpoint": path,
                            "last_AI_vs_equal": f"{self.train_history[-1]['pred_vs_equal_gain_db']:.3f} dB"
                            if self.train_history
                            else "n/a",
                            "last_oracle_gap": f"{self.train_history[-1]['pred_vs_oracle_gap_db']:.3f} dB"
                            if self.train_history
                            else "n/a",
                        }
                    )
                elif kind == "error":
                    self._set_busy(False, "Error")
                    messagebox.showerror("Error", item[1])
        except queue.Empty:
            pass
        self.master.after(200, self._poll_queue)


def main():
    root = tk.Tk()
    app = FSOAITrainingGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
