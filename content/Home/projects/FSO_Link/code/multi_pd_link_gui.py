import csv
import queue
import threading
import traceback
from pathlib import Path

import numpy as np
import tkinter as tk
from tkinter import filedialog, ttk

import matplotlib

matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib.patches import Circle, Rectangle

from fso_engine import FSOEngineConfig, run_fso_receiver, w_to_dbm


HERE = Path(__file__).resolve().parent
EXTERNAL_FSO = HERE / "external" / "FSO-simulator"


class MultiPDLinkGUI:
    def __init__(self, master):
        self.master = master
        self.master.title("Physics-Informed FSO Multi-PD Receiver")
        self.master.geometry("1680x980")
        self.inputs = {}
        self.queue = queue.Queue()
        self.result = None
        self._busy = False
        self._playing = False
        self._play_job = None
        self._optical_artists = None

        self._build_layout()
        self._poll_queue()

    def _build_layout(self):
        self.side = ttk.Frame(self.master, padding=10, width=405)
        self.side.pack(side=tk.LEFT, fill=tk.Y)

        ttk.Label(
            self.side,
            text="FSO Physics Engine + 4x4 APD Receiver",
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor=tk.W)
        connected = (EXTERNAL_FSO / "channel" / "fso_channel.py").exists()
        ttk.Label(
            self.side,
            text="Physics engine: integrated and ready" if connected else "Physics engine dependency not installed",
            foreground=("green" if connected else "red"),
        ).pack(anchor=tk.W, pady=(2, 8))

        control_shell = ttk.Frame(self.side)
        control_shell.pack(fill=tk.BOTH, expand=True)
        self.control_canvas = tk.Canvas(control_shell, width=385, height=625, highlightthickness=0)
        self.control_scroll = ttk.Scrollbar(control_shell, orient="vertical", command=self.control_canvas.yview)
        self.control_frame = ttk.Frame(self.control_canvas)
        self.control_frame.bind(
            "<Configure>",
            lambda _event: self.control_canvas.configure(scrollregion=self.control_canvas.bbox("all")),
        )
        self.control_canvas.create_window((0, 0), window=self.control_frame, anchor="nw")
        self.control_canvas.configure(yscrollcommand=self.control_scroll.set)
        self.control_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.control_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self._add_group(
            "FSO channel and frozen-flow time axis",
            [
                ("link_direction", "Link direction", "downlink", ("downlink", "uplink")),
                ("link_distance_m", "FSO distance (m)", "20000"),
                ("wavelength_nm", "Wavelength (nm)", "1550"),
                ("tx_aperture_mm", "TX lens diameter (mm)", "70"),
                ("tx_divergence_urad", "TX full divergence (urad)", "28"),
                ("tx_antenna_gain_db", "TX antenna gain (dB)", "103.1"),
                ("hv57_ground_cn2_A", "HV57 ground Cn2 A", "5e-14"),
                ("n_screens", "Phase screens", "3"),
                ("grid_mode", "Grid mode", "medium", ("small", "medium", "large")),
                ("n_time_frames", "Time frames", "32"),
                ("frame_interval_ms", "Frame interval (ms)", "1"),
                ("wind_speed_mps", "Wind speed (m/s)", "5"),
                ("wind_direction_deg", "Wind direction (deg)", "0"),
                ("seed_base", "Phase-screen seed", "42"),
                ("zenith_angle_deg", "Zenith angle (deg)", "0"),
                ("tx_power_dbm", "TX power (dBm)", "20"),
                ("active_system_loss_db", "Additional optical loss (dB)", "30"),
                ("datarate_gbps", "Data rate (Gbps)", "10"),
            ],
        )
        self._add_group(
            "Receiver optics and PD array",
            [
                ("rx_lens_diameter_mm", "RX lens diameter (mm)", "203.2"),
                ("rx_antenna_gain_db", "RX antenna gain (dB)", "112.3"),
                ("telescope_focal_length_mm", "Telescope focal length (mm)", "2032"),
                ("central_obstruction_pct", "Central obstruction (diameter %)", "31"),
                ("collimator_focal_length_mm", "Collimator focal length (mm)", "75"),
                ("collimated_pupil_mm", "Collimated pupil diameter (mm)", "7.5"),
                ("relay_output_pupil_mm", "Relay output pupil (mm)", "1.0"),
                ("pd_rows", "PD rows", "4"),
                ("pd_cols", "PD columns", "4"),
                ("pd_pitch_um", "APD pitch (um)", "250"),
                ("integrated_lens_um", "Integrated lens diameter (um)", "100"),
                ("active_junction_um", "Active junction diameter (um)", "25"),
                ("external_mla_enabled", "External MLA? (0/1)", "0"),
                ("external_mla_fill_factor", "External MLA fill factor", "0.95"),
                ("external_mla_efficiency", "External MLA efficiency", "0.85"),
            ],
        )
        self._add_group(
            "ADC, link metrics, and CNN",
            [
                ("responsivity_a_w", "Responsivity (A/W)", "0.9"),
                ("apd_bandwidth_ghz", "APD bandwidth (GHz)", "20"),
                ("apd_symbol_rate_gbaud", "APD symbol rate (Gbaud)", "28"),
                ("adc_bits", "ADC bits", "8"),
                ("adc_full_scale_ua", "ADC full-scale (uA)", "50"),
                ("samples_per_frame", "ADC samples/frame", "16"),
                ("modulation_order", "QAM order", "4"),
                ("current_noise_na", "Current noise RMS (nA)", "20"),
                ("evm_floor_pct", "EVM floor (%)", "2"),
                ("outage_evm_pct", "Outage EVM threshold (%)", "20"),
                ("fade_outage_pct", "Fade outage target (%)", "1"),
                ("cnn_time_window", "CNN time window", "6"),
                ("cnn_epochs", "CNN epochs", "8"),
                ("cnn_width", "CNN width", "16"),
                ("cnn_lr", "CNN learning rate", "2e-3"),
                ("cnn_snr_weight", "CNN SNR loss weight", "0.2"),
                ("cnn_physics_weight", "Power-conservation loss", "0.05"),
                ("cnn_r0_weight", "CNN r0 loss weight", "0.1"),
            ],
        )

        buttons = ttk.Frame(self.side)
        buttons.pack(fill=tk.X, pady=(8, 4))
        self.run_btn = ttk.Button(buttons, text="Run Integrated Simulation", command=self.run)
        self.run_btn.pack(fill=tk.X, ipady=4)
        ttk.Button(buttons, text="Export Results CSV", command=self.export_metrics).pack(fill=tk.X, pady=(3, 0))

        self.progress = ttk.Progressbar(self.side, mode="indeterminate")
        self.progress.pack(fill=tk.X, pady=(8, 4))
        self.status = tk.StringVar(value="Ready")
        ttk.Label(self.side, textvariable=self.status, wraplength=380, foreground="blue").pack(anchor=tk.W)

        self.tree = ttk.Treeview(self.side, columns=("metric", "value"), show="headings", height=12)
        self.tree.heading("metric", text="Metric")
        self.tree.heading("value", text="Value")
        self.tree.column("metric", width=195)
        self.tree.column("value", width=180, anchor=tk.E)
        self.tree.pack(fill=tk.X, pady=(8, 0))

        self.notebook = ttk.Notebook(self.master)
        self.notebook.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        self.tab_optics = ttk.Frame(self.notebook)
        self.tab_adc = ttk.Frame(self.notebook)
        self.tab_metrics = ttk.Frame(self.notebook)
        self.tab_cnn = ttk.Frame(self.notebook)
        self.tab_spatial = ttk.Frame(self.notebook)
        self.tab_log = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_optics, text="Optical Path and PD Array")
        self.notebook.add(self.tab_adc, text="PD Current and ADC")
        self.notebook.add(self.tab_metrics, text="EVM / BER / Outage")
        self.notebook.add(self.tab_cnn, text="CNN Predictor")
        self.notebook.add(self.tab_spatial, text="r0 and Spatial Strategy")
        self.notebook.add(self.tab_log, text="Log")

        frame_bar = ttk.Frame(self.tab_optics, padding=(8, 5))
        frame_bar.pack(fill=tk.X)
        ttk.Button(frame_bar, text="Previous", command=lambda: self._step_frame(-1)).pack(side=tk.LEFT)
        self.play_btn = ttk.Button(frame_bar, text="Play", command=self._toggle_play)
        self.play_btn.pack(side=tk.LEFT, padx=4)
        ttk.Button(frame_bar, text="Next", command=lambda: self._step_frame(1)).pack(side=tk.LEFT)
        self.frame_value = tk.DoubleVar(value=0.0)
        self.frame_scale = ttk.Scale(
            frame_bar,
            from_=0,
            to=1,
            variable=self.frame_value,
            command=self._on_frame_change,
        )
        self.frame_scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)
        self.frame_label = tk.StringVar(value="Frame - / -")
        ttk.Label(frame_bar, textvariable=self.frame_label, width=24).pack(side=tk.RIGHT)

        self.fig_optics = Figure(figsize=(11.8, 8.2), dpi=100, constrained_layout=True)
        self.canvas_optics = FigureCanvasTkAgg(self.fig_optics, master=self.tab_optics)
        self.canvas_optics.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        self.fig_adc = Figure(figsize=(11.8, 7.8), dpi=100, constrained_layout=True)
        self.canvas_adc = FigureCanvasTkAgg(self.fig_adc, master=self.tab_adc)
        self.canvas_adc.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        self.fig_metrics = Figure(figsize=(11.8, 7.8), dpi=100, constrained_layout=True)
        self.canvas_metrics = FigureCanvasTkAgg(self.fig_metrics, master=self.tab_metrics)
        self.canvas_metrics.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        self.fig_cnn = Figure(figsize=(11.8, 7.8), dpi=100, constrained_layout=True)
        self.canvas_cnn = FigureCanvasTkAgg(self.fig_cnn, master=self.tab_cnn)
        self.canvas_cnn.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        self.fig_spatial = Figure(figsize=(11.8, 7.8), dpi=100, constrained_layout=True)
        self.canvas_spatial = FigureCanvasTkAgg(self.fig_spatial, master=self.tab_spatial)
        self.canvas_spatial.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        self.log_text = tk.Text(self.tab_log, height=20, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        self._append_log("Ready. The integrated FSO engine uses split-step propagation and a 4x4 APD receiver.")
        self._draw_empty()

    def _add_group(self, title, rows):
        box = ttk.LabelFrame(self.control_frame, text=title, padding=8)
        box.pack(fill=tk.X, pady=5)
        for item in rows:
            key, label, default = item[:3]
            row = ttk.Frame(box)
            row.pack(fill=tk.X, pady=2)
            ttk.Label(row, text=label, width=30).pack(side=tk.LEFT)
            if len(item) == 4:
                widget = ttk.Combobox(row, width=12, values=item[3], state="readonly")
                widget.set(default)
            else:
                widget = ttk.Entry(row, width=14)
                widget.insert(0, default)
            widget.pack(side=tk.RIGHT)
            self.inputs[key] = widget

    def _get_float(self, key):
        return float(self.inputs[key].get().strip())

    def _get_int(self, key):
        return int(float(self.inputs[key].get().strip()))

    def _append_log(self, text):
        self.log_text.insert(tk.END, text.rstrip() + "\n")
        self.log_text.see(tk.END)

    def _config_from_inputs(self):
        return FSOEngineConfig(
            link_direction=self.inputs["link_direction"].get().strip(),
            link_distance_m=self._get_float("link_distance_m"),
            wavelength_m=self._get_float("wavelength_nm") * 1e-9,
            tx_aperture_diameter_m=self._get_float("tx_aperture_mm") * 1e-3,
            tx_divergence_full_angle_rad=self._get_float("tx_divergence_urad") * 1e-6,
            tx_antenna_gain_db=self._get_float("tx_antenna_gain_db"),
            hv57_ground_cn2_A=self._get_float("hv57_ground_cn2_A"),
            n_screens=self._get_int("n_screens"),
            grid_mode=self.inputs["grid_mode"].get().strip(),
            n_time_frames=self._get_int("n_time_frames"),
            frame_interval_s=self._get_float("frame_interval_ms") * 1e-3,
            wind_speed_mps=self._get_float("wind_speed_mps"),
            wind_direction_deg=self._get_float("wind_direction_deg"),
            seed_base=self._get_int("seed_base"),
            zenith_angle_deg=self._get_float("zenith_angle_deg"),
            tx_power_dbm=self._get_float("tx_power_dbm"),
            active_system_loss_db=self._get_float("active_system_loss_db"),
            datarate_bps=self._get_float("datarate_gbps") * 1e9,
            rx_lens_diameter_m=self._get_float("rx_lens_diameter_mm") * 1e-3,
            rx_antenna_gain_db=self._get_float("rx_antenna_gain_db"),
            telescope_focal_length_m=self._get_float("telescope_focal_length_mm") * 1e-3,
            central_obstruction_ratio=self._get_float("central_obstruction_pct") / 100.0,
            collimator_focal_length_m=self._get_float("collimator_focal_length_mm") * 1e-3,
            collimated_pupil_diameter_m=self._get_float("collimated_pupil_mm") * 1e-3,
            pupil_relay_output_diameter_m=self._get_float("relay_output_pupil_mm") * 1e-3,
            pd_rows=self._get_int("pd_rows"),
            pd_cols=self._get_int("pd_cols"),
            pd_pitch_m=self._get_float("pd_pitch_um") * 1e-6,
            pd_integrated_lens_diameter_m=self._get_float("integrated_lens_um") * 1e-6,
            pd_active_junction_diameter_m=self._get_float("active_junction_um") * 1e-6,
            external_mla_enabled=bool(self._get_int("external_mla_enabled")),
            external_mla_fill_factor=self._get_float("external_mla_fill_factor"),
            external_mla_efficiency=self._get_float("external_mla_efficiency"),
            receiver_responsivity=self._get_float("responsivity_a_w"),
            apd_bandwidth_hz=self._get_float("apd_bandwidth_ghz") * 1e9,
            apd_symbol_rate_baud=self._get_float("apd_symbol_rate_gbaud") * 1e9,
            adc_bits=self._get_int("adc_bits"),
            adc_full_scale_a=self._get_float("adc_full_scale_ua") * 1e-6,
            samples_per_frame=self._get_int("samples_per_frame"),
            qam_order=self._get_int("modulation_order"),
            current_noise_rms_a=self._get_float("current_noise_na") * 1e-9,
            evm_floor_pct=self._get_float("evm_floor_pct"),
            outage_evm_pct=self._get_float("outage_evm_pct"),
            fade_outage_pct=self._get_float("fade_outage_pct"),
            cnn_time_window=self._get_int("cnn_time_window"),
            cnn_epochs=self._get_int("cnn_epochs"),
            cnn_width=self._get_int("cnn_width"),
            cnn_lr=self._get_float("cnn_lr"),
            cnn_snr_weight=self._get_float("cnn_snr_weight"),
            cnn_physics_weight=self._get_float("cnn_physics_weight"),
            cnn_r0_weight=self._get_float("cnn_r0_weight"),
        )

    def _draw_empty(self):
        for fig, canvas in [
            (self.fig_optics, self.canvas_optics),
            (self.fig_adc, self.canvas_adc),
            (self.fig_metrics, self.canvas_metrics),
            (self.fig_cnn, self.canvas_cnn),
            (self.fig_spatial, self.canvas_spatial),
        ]:
            fig.clear()
            ax = fig.add_subplot(1, 1, 1)
            ax.text(0.5, 0.5, "Run the integrated simulation", ha="center", va="center", transform=ax.transAxes)
            ax.set_axis_off()
            canvas.draw()

    def run(self):
        if self._busy:
            return
        try:
            cfg = self._config_from_inputs()
        except Exception as exc:
            self.status.set("Input error. See Log tab.")
            self._append_log("Input error:\n" + "".join(traceback.format_exception_only(type(exc), exc)))
            self.notebook.select(self.tab_log)
            return
        self._stop_playback()
        self._busy = True
        self.run_btn.configure(state=tk.DISABLED)
        self.progress.start(12)
        self.status.set("Running split-step propagation, frozen-flow sequence, APD/ADC, and CNN...")
        self._append_log(
            f"Run started: {cfg.link_direction}, L={cfg.link_distance_m:g} m, "
            f"lambda={cfg.wavelength_m*1e9:.1f} nm, Cn2={cfg.hv57_ground_cn2_A:.3e}, "
            f"dt={cfg.frame_interval_s*1e3:.3f} ms, wind={cfg.wind_speed_mps:g} m/s, "
            f"PD={cfg.pd_rows}x{cfg.pd_cols}, output pupil={cfg.pupil_relay_output_diameter_m*1e3:g} mm"
        )

        def worker():
            try:
                self.queue.put(("result", run_fso_receiver(cfg)))
            except Exception:
                self.queue.put(("error", traceback.format_exc()))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                self._busy = False
                self.run_btn.configure(state=tk.NORMAL)
                self.progress.stop()
                if kind == "result":
                    self.result = payload
                    self.status.set("Done")
                    self._append_log("Run finished successfully.")
                    self._update_all()
                    self.notebook.select(self.tab_optics)
                else:
                    self.status.set("Error. See Log tab.")
                    self._append_log("Run error:\n" + payload)
                    self.notebook.select(self.tab_log)
        except queue.Empty:
            pass
        self.master.after(120, self._poll_queue)

    def _update_all(self):
        n_frames = len(self.result["frame_times_s"])
        self.frame_scale.configure(to=max(n_frames - 1, 1))
        self.frame_value.set(n_frames // 2)
        self._optical_artists = None
        self.fig_optics.set_layout_engine("constrained")
        self._update_summary()
        self._plot_optical(n_frames // 2)
        self._plot_adc()
        self._plot_metrics()
        self._plot_cnn()
        self._plot_spatial()

    def _update_summary(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        r = self.result
        rows = [
            ("Physics engine", "integrated split-step FSO"),
            ("Link direction", r["link_direction"]),
            ("TX / RX altitude", f"{r['tx_altitude_m']/1e3:.1f} / {r['rx_altitude_m']/1e3:.1f} km"),
            ("Link distance", f"{r['configured_link_distance_m']:.1f} m"),
            ("TX beam waist", f"{r['tx_beam_waist_m']*1e3:.2f} mm"),
            ("Modeled TX full divergence", f"{r['modeled_tx_divergence_full_angle_rad']*1e6:.2f} urad"),
            ("TX antenna gain", f"{r['tx_antenna_gain_db']:.1f} dB (ideal {r['tx_ideal_aperture_gain_db']:.2f})"),
            ("RX antenna gain", f"{r['rx_antenna_gain_db']:.1f} dB (ideal {r['rx_ideal_aperture_gain_db']:.2f})"),
            ("Free-space path loss", f"{r['free_space_path_loss_db']:.1f} dB"),
            ("Scalar link-budget RX", f"{r['link_budget_rx_power_dbm']:.1f} dBm"),
            ("r0", f"{r['r0_m'] * 100:.2f} cm"),
            ("Equivalent subaperture", f"{r['equivalent_subaperture_m'] * 1e3:.1f} mm"),
            ("r0 / subaperture", f"{r['spatial_strategy']['r0_to_subaperture_ratio']:.3f}"),
            ("Spatial regime", r["spatial_strategy"]["regime"]),
            ("Collimated pupil", f"{r['collimated_pupil_diameter_m'] * 1e3:.2f} mm"),
            ("Relay output pupil", f"{r['pupil_relay_output_diameter_m'] * 1e3:.2f} mm"),
            ("Pupil relay ratio", f"{r['pupil_relay_ratio']:.2f}x"),
            ("Greenwood frequency", f"{r['greenwood_hz']:.1f} Hz"),
            ("Rytov variance", f"{r['rytov_variance']:.3e}"),
            ("Scintillation index", f"{r['scintillation_index']:.3e}"),
            ("Lag-1 time correlation", f"{r['temporal_correlation_lag1']:.3f}"),
            ("Mean aperture capture", f"{100*np.mean(r['aperture_capture_fraction']):.2f} %"),
            ("Mean Strehl ratio", f"{np.mean(r['strehl_ratio']):.3f}"),
            ("Mean PD-array power", f"{np.mean(r['total_pd_power_dbm']):.2f} dBm"),
            (
                "CNN r0 estimate",
                f"{r['cnn'].get('estimated_r0_m', float('nan')) * 1e3:.2f} mm (single-condition calibration)",
            ),
            (
                "One-stream capacity",
                f"{r['spatial_strategy']['mean_diversity_capacity_bps_hz']:.2f} bit/s/Hz",
            ),
            (
                "Independent-channel proxy",
                f"{r['spatial_strategy']['mean_parallel_capacity_proxy_bps_hz']:.2f} bit/s/Hz",
            ),
            ("Max BPM power error", f"{np.max(r['parseval_error']):.2e}"),
        ]
        for name in ("Single center PD", "MRC oracle", "CNN predictive"):
            if name in r["metrics"]:
                metric = r["metrics"][name]
                rows.append((f"{name} EVM", f"{metric['mean_evm_pct']:.2f} %"))
                rows.append((f"{name} BER", f"{metric['mean_ber']:.3e}"))
        for key, value in rows:
            self.tree.insert("", tk.END, values=(key, value))

    def _selected_frame(self):
        if self.result is None:
            return 0
        return int(np.clip(round(self.frame_value.get()), 0, len(self.result["frame_times_s"]) - 1))

    def _on_frame_change(self, _value=None):
        if self.result is not None:
            self._plot_optical(self._selected_frame())

    def _step_frame(self, step):
        if self.result is None:
            return
        n_frames = len(self.result["frame_times_s"])
        self.frame_value.set((self._selected_frame() + step) % n_frames)
        self._plot_optical(self._selected_frame())

    def _toggle_play(self):
        if self.result is None:
            return
        if self._playing:
            self._stop_playback()
        else:
            self._playing = True
            self.play_btn.configure(text="Pause")
            self._advance_playback()

    def _stop_playback(self):
        self._playing = False
        if hasattr(self, "play_btn"):
            self.play_btn.configure(text="Play")
        if self._play_job is not None:
            self.master.after_cancel(self._play_job)
            self._play_job = None

    def _advance_playback(self):
        if not self._playing or self.result is None:
            return
        self._step_frame(1)
        self._play_job = self.master.after(300, self._advance_playback)

    def _plot_optical(self, frame):
        r = self.result
        cfg = r["cfg"]
        initializing = self._optical_artists is None
        time_ms = r["frame_times_s"] * 1e3
        pd_frame = r["pd_rx_power_w"][frame].reshape(cfg.pd_rows, cfg.pd_cols)
        pd_dbm = w_to_dbm(pd_frame)

        if initializing:
            self.fig_optics.clear()
            ax_rx = self.fig_optics.add_subplot(2, 2, 1)
            ax_heat = self.fig_optics.add_subplot(2, 2, 2)
            ax_reduced = self.fig_optics.add_subplot(2, 2, 3)
            ax_trace = self.fig_optics.add_subplot(2, 2, 4)

            x_rx = r["coords_receiver"] * 1e3
            x_reduced = r["coords_out"] * 1e3
            extent_rx = [x_rx[0], x_rx[-1], x_rx[0], x_rx[-1]]
            extent_reduced = [x_reduced[0], x_reduced[-1], x_reduced[0], x_reduced[-1]]
            lens_radius_mm = r["rx_lens_radius_m"] * 1e3
            obstruction_radius_mm = r["rx_obstruction_radius_m"] * 1e3
            reduced_radius_mm = r["reduced_lens_radius_m"] * 1e3
            reduced_obstruction_mm = r["reduced_obstruction_radius_m"] * 1e3

            image_rx = ax_rx.imshow(
                r["receiver_power_density_w_m2"][frame].T,
                extent=extent_rx,
                origin="lower",
                cmap="magma",
                vmin=0.0,
                vmax=r["receiver_power_density_scale_max_w_m2"],
            )
            ax_rx.add_patch(Circle(
                (0.0, 0.0), lens_radius_mm, fill=False, edgecolor="lime",
                linewidth=1.6, linestyle="--", label="203.2 mm entrance pupil",
            ))
            ax_rx.add_patch(Circle(
                (0.0, 0.0), obstruction_radius_mm, fill=False, edgecolor="cyan",
                linewidth=1.3, linestyle="--", label="31% central obstruction",
            ))
            rx_zoom = min(lens_radius_mm * 1.18, max(abs(x_rx[0]), abs(x_rx[-1])))
            ax_rx.set(xlim=(-rx_zoom, rx_zoom), ylim=(-rx_zoom, rx_zoom), xlabel="x (mm)", ylabel="y (mm)")
            ax_rx.set_title("1. Receiver plane with annular telescope aperture")
            ax_rx.set_aspect("equal", adjustable="box")
            ax_rx.legend(loc="upper right", fontsize=7)
            self.fig_optics.colorbar(
                image_rx, ax=ax_rx, fraction=0.046, pad=0.03,
                label="Optical power density (W/m^2), fixed for run",
            )

            image_reduced = ax_reduced.imshow(
                r["reduced_power_density_w_m2"][frame].T,
                extent=extent_reduced,
                origin="lower",
                cmap="magma",
                vmin=0.0,
                vmax=r["reduced_power_density_scale_max_w_m2"],
            )
            ax_reduced.add_patch(Circle(
                (0.0, 0.0), reduced_radius_mm, fill=False, edgecolor="lime",
                linewidth=1.6, linestyle="--", label="1.0 mm reduced pupil",
            ))
            ax_reduced.add_patch(Circle(
                (0.0, 0.0), reduced_obstruction_mm, fill=False, edgecolor="cyan",
                linewidth=1.3, linestyle="--", label="Reduced central obstruction",
            ))
            pitch_mm = cfg.pd_pitch_m * 1e3
            lens_radius_pd_mm = cfg.pd_integrated_lens_diameter_m * 0.5e3
            junction_radius_mm = cfg.pd_active_junction_diameter_m * 0.5e3
            for pd_index, (px, py) in enumerate(r["pd_positions"]):
                ax_reduced.add_patch(Circle(
                    (px * 1e3, py * 1e3), lens_radius_pd_mm, fill=False,
                    edgecolor="deepskyblue", linewidth=1.0, linestyle="--",
                    label="100 um integrated lens" if pd_index == 0 else None,
                ))
                ax_reduced.add_patch(Circle(
                    (px * 1e3, py * 1e3), junction_radius_mm, fill=False,
                    edgecolor="white", linewidth=0.6,
                    label="25 um APD junction" if pd_index == 0 else None,
                ))
                if cfg.external_mla_enabled:
                    clear_mm = pitch_mm * np.sqrt(cfg.external_mla_fill_factor)
                    ax_reduced.add_patch(Rectangle(
                        (px * 1e3 - clear_mm / 2.0, py * 1e3 - clear_mm / 2.0),
                        clear_mm, clear_mm, fill=False, edgecolor="yellow",
                        linewidth=0.8, linestyle=":",
                        label="External MLA clear aperture" if pd_index == 0 else None,
                    ))
            reduced_zoom = min(
                max(reduced_radius_mm * 1.15, pitch_mm * 2.2),
                max(abs(x_reduced[0]), abs(x_reduced[-1])),
            )
            ax_reduced.set(
                xlim=(-reduced_zoom, reduced_zoom), ylim=(-reduced_zoom, reduced_zoom),
                xlabel="x (mm)", ylabel="y (mm)",
            )
            ax_reduced.set_title("2. 7.5 mm to 1.0 mm pupil relay and 4x4 APD sampling")
            ax_reduced.set_aspect("equal", adjustable="box")
            ax_reduced.legend(loc="lower right", fontsize=6)
            self.fig_optics.colorbar(
                image_reduced, ax=ax_reduced, fraction=0.046, pad=0.03,
                label="Optical power density (W/m^2), fixed for run",
            )

            pd_dbm_all = w_to_dbm(r["pd_rx_power_w"])
            heat_min = float(np.min(pd_dbm_all))
            heat_max = float(np.max(pd_dbm_all))
            heat_pad = max(0.5, 0.05 * (heat_max - heat_min))
            heat = ax_heat.imshow(
                pd_dbm, cmap="viridis", origin="lower",
                vmin=heat_min - heat_pad, vmax=heat_max + heat_pad,
            )
            ax_heat.set_title("3. Per-APD received optical power")
            ax_heat.set_xlabel("APD column")
            ax_heat.set_ylabel("APD row")
            heat_texts = []
            for row in range(cfg.pd_rows):
                for col in range(cfg.pd_cols):
                    heat_texts.append(ax_heat.text(
                        col, row, f"{pd_dbm[row, col]:.1f}",
                        ha="center", va="center", color="white", fontsize=8,
                    ))
            self.fig_optics.colorbar(heat, ax=ax_heat, fraction=0.046, pad=0.03, label="dBm, fixed for run")

            trace_dbm = w_to_dbm(r["pd_rx_power_w"])
            for pd_index in range(min(trace_dbm.shape[1], 16)):
                ax_trace.plot(time_ms, trace_dbm[:, pd_index], linewidth=1.0, label=f"PD{pd_index}")
            frame_line = ax_trace.axvline(time_ms[frame], color="black", linestyle="--", linewidth=1.0)
            trace_min = float(np.min(trace_dbm))
            trace_max = float(np.max(trace_dbm))
            trace_pad = max(0.5, 0.08 * (trace_max - trace_min))
            ax_trace.set_ylim(trace_min - trace_pad, trace_max + trace_pad)
            ax_trace.set_xlim(time_ms[0], time_ms[-1] if len(time_ms) > 1 else time_ms[0] + 1.0)
            ax_trace.set_title("4. APD optical-power traces from frozen-flow turbulence")
            ax_trace.set_xlabel("Time (ms)")
            ax_trace.set_ylabel("Received power (dBm)")
            ax_trace.grid(alpha=0.25)
            ax_trace.legend(ncol=4, fontsize=7)

            self.fig_optics.suptitle(
                f"{r['link_direction'].upper()}: annular entrance pupil -> 7.5 mm collimated pupil -> 1.0 mm 4x4 APD plane",
                fontsize=12,
            )
            self._optical_artists = {
                "rx": image_rx,
                "reduced": image_reduced,
                "heat": heat,
                "heat_texts": heat_texts,
                "frame_line": frame_line,
            }
        else:
            self._optical_artists["rx"].set_data(r["receiver_power_density_w_m2"][frame].T)
            self._optical_artists["reduced"].set_data(r["reduced_power_density_w_m2"][frame].T)
            self._optical_artists["heat"].set_data(pd_dbm)
            for text_artist, value in zip(self._optical_artists["heat_texts"], pd_dbm.flat):
                text_artist.set_text(f"{value:.1f}")
            self._optical_artists["frame_line"].set_xdata([time_ms[frame], time_ms[frame]])

        self.frame_label.set(f"Frame {frame + 1}/{len(time_ms)}   t={time_ms[frame]:.2f} ms")
        if initializing:
            self.canvas_optics.draw()
            self.fig_optics.set_layout_engine("none")
        else:
            self.canvas_optics.draw_idle()

    def _plot_adc(self):
        r = self.result
        cfg = r["cfg"]
        signal = r["adc"]
        self.fig_adc.clear()
        ax_current = self.fig_adc.add_subplot(2, 1, 1)
        ax_codes = self.fig_adc.add_subplot(2, 1, 2)
        n_plot = min(8, signal["current_a"].shape[0])
        sample_dt_ms = cfg.frame_interval_s * 1e3 / max(cfg.samples_per_frame, 1)
        sample_time = np.arange(signal["current_a"].shape[1]) * sample_dt_ms

        for pd_index in range(n_plot):
            ax_current.plot(sample_time, signal["current_a"][pd_index] * 1e6, linewidth=0.9, label=f"PD{pd_index}")
        ax_current.set_title("Photocurrent at each ADC input")
        ax_current.set_xlabel("Time (ms)")
        ax_current.set_ylabel("Current (uA)")
        ax_current.grid(alpha=0.25)
        ax_current.legend(ncol=4, fontsize=8)

        for pd_index in range(n_plot):
            ax_codes.step(sample_time, signal["adc_codes"][pd_index], where="mid", linewidth=0.9, label=f"PD{pd_index}")
        saturation = 100.0 * np.mean(signal["adc_codes"] >= (2**cfg.adc_bits - 1))
        ax_codes.set_title(f"Per-channel ADC codes (saturation {saturation:.2f}%)")
        ax_codes.set_xlabel("Time (ms)")
        ax_codes.set_ylabel("ADC code")
        ax_codes.grid(alpha=0.25)
        ax_codes.legend(ncol=4, fontsize=8)
        self.canvas_adc.draw()

    def _plot_metrics(self):
        r = self.result
        cfg = r["cfg"]
        times_ms = r["frame_times_s"] * 1e3
        names = list(r["metrics"])
        self.fig_metrics.clear()
        axes = [self.fig_metrics.add_subplot(2, 3, index + 1) for index in range(6)]

        for name in names:
            traces = r["performance_traces"][name]
            axes[0].plot(times_ms, traces["evm_pct"], linewidth=1.1, label=name)
            axes[1].semilogy(times_ms, np.maximum(traces["ber"], 1e-15), linewidth=1.1, label=name)
        axes[0].axhline(cfg.outage_evm_pct, color="black", linestyle="--", linewidth=1.0, label="outage threshold")
        axes[0].set(title="EVM over time", xlabel="Time (ms)", ylabel="EVM (%)")
        axes[1].set(title=f"Approximate {cfg.qam_order}-QAM BER over time", xlabel="Time (ms)", ylabel="BER")
        for ax in axes[:2]:
            ax.grid(alpha=0.25)
            ax.legend(fontsize=7)

        values = [100.0 * r["metrics"][name]["outage_probability"] for name in names]
        axes[2].bar(names, values)
        axes[2].set(title="Outage probability", ylabel="P(EVM > threshold) (%)")

        values = [r["metrics"][name]["required_fade_margin_db"] for name in names]
        axes[3].bar(names, values)
        axes[3].set(title=f"Required fade margin at {cfg.fade_outage_pct:g}%", ylabel="dB")

        axes[4].plot(times_ms, r["total_pd_power_dbm"], color="tab:green", linewidth=1.2)
        axes[4].set(title="Total PD-array received optical power", xlabel="Time (ms)", ylabel="dBm")

        values = [r["metrics"][name]["mean_snr_db"] for name in names]
        axes[5].bar(names, values)
        axes[5].set(title="Mean electrical SNR after combining", ylabel="dB")

        for ax in axes[2:]:
            ax.grid(axis="y", alpha=0.25)
        for ax in (axes[2], axes[3], axes[5]):
            ax.tick_params(axis="x", rotation=24, labelsize=7)
        self.canvas_metrics.draw()

    def _plot_cnn(self):
        r = self.result
        cnn = r["cnn"]
        self.fig_cnn.clear()
        axes = [self.fig_cnn.add_subplot(2, 2, index + 1) for index in range(4)]
        if not cnn.get("available"):
            for ax in axes:
                ax.set_axis_off()
            axes[0].text(0.5, 0.5, cnn.get("error", "CNN was not trained."), ha="center", va="center", transform=axes[0].transAxes)
            self.canvas_cnn.draw()
            return

        history = cnn["history"]
        epochs = [item["epoch"] for item in history]
        axes[0].plot(epochs, [item["loss"] for item in history], marker="o", label="total loss")
        axes[0].plot(epochs, [item["mse"] for item in history], marker="s", label="next-power MSE")
        axes[0].plot(epochs, [item["physics_loss"] for item in history], marker="^", label="power consistency")
        axes[0].plot(epochs, [item["r0_loss"] for item in history], marker="d", label="r0 ratio loss")
        axes[0].set(title="Physics-informed temporal CNN training", xlabel="Epoch", ylabel="Loss")
        axes[0].grid(alpha=0.25)
        axes[0].legend(fontsize=8)

        pred = cnn["pred_norm_power"][-1]
        truth = cnn["true_norm_power"][-1]
        weights = cnn["weights"][-1].reshape(r["cfg"].pd_rows, r["cfg"].pd_cols)
        vmax = max(float(np.max(pred)), float(np.max(truth)), 1e-9)
        maps = [
            (axes[1], pred, "Predicted next-frame normalized PD power", 0.0, vmax),
            (axes[2], truth, "Actual next-frame normalized PD power", 0.0, vmax),
            (axes[3], weights, "CNN predictive combining weights", 0.0, max(float(np.max(weights)), 1e-9)),
        ]
        for ax, values, title, vmin, vmax_map in maps:
            image = ax.imshow(values, cmap="viridis", origin="lower", vmin=vmin, vmax=vmax_map)
            ax.set_title(title)
            ax.set_xlabel("PD column")
            ax.set_ylabel("PD row")
            for row in range(values.shape[0]):
                for col in range(values.shape[1]):
                    ax.text(col, row, f"{values[row, col]:.2f}", ha="center", va="center", color="white", fontsize=8)
            self.fig_cnn.colorbar(image, ax=ax, fraction=0.046, pad=0.03)
        self.canvas_cnn.draw()

    def _plot_spatial(self):
        r = self.result
        cfg = r["cfg"]
        strategy = r["spatial_strategy"]
        cnn = r["cnn"]
        rows, cols = cfg.pd_rows, cfg.pd_cols
        self.fig_spatial.clear()
        axes = [self.fig_spatial.add_subplot(2, 2, index + 1) for index in range(4)]

        true_r0_mm = r["r0_m"] * 1e3
        estimated_r0_mm = cnn.get("estimated_r0_m", np.nan) * 1e3
        subaperture_mm = strategy["equivalent_subaperture_m"] * 1e3
        axes[0].bar(
            ["Simulator r0", "CNN r0", "Subaperture"],
            [true_r0_mm, estimated_r0_mm, subaperture_mm],
            color=["tab:blue", "tab:orange", "tab:gray"],
        )
        short_recommendation = {
            "strong turbulence": "Use outage-robust or predictive MRC",
            "transition": "Keep diversity; test spatial-mode independence",
            "weak turbulence": "Multiplexing requires independent TX modes",
        }.get(strategy["regime"], "Use measured channel statistics")
        axes[0].set_title(
            f"{strategy['regime']}  |  r0/Dsub={strategy['r0_to_subaperture_ratio']:.2f}\n"
            f"{short_recommendation}",
            fontsize=10,
        )
        axes[0].set_ylabel("Length (mm)")
        axes[0].grid(axis="y", alpha=0.25)
        axes[0].tick_params(axis="x", rotation=12)

        maps = [
            (
                axes[1],
                strategy["outage_robust_weights"].reshape(rows, cols),
                "Outage-robust diversity weights",
            ),
            (
                axes[2],
                strategy["capacity_power_allocation_weights"].reshape(rows, cols),
                "Independent-channel capacity allocation",
            ),
        ]
        for ax, values, title in maps:
            image = ax.imshow(values, cmap="viridis", origin="lower", vmin=0.0)
            ax.set(title=title, xlabel="APD column", ylabel="APD row")
            for row in range(rows):
                for col in range(cols):
                    ax.text(col, row, f"{values[row, col]:.2f}", ha="center", va="center", color="white", fontsize=8)
            self.fig_spatial.colorbar(image, ax=ax, fraction=0.046, pad=0.03)

        times_ms = r["frame_times_s"] * 1e3
        axes[3].plot(
            times_ms,
            strategy["diversity_capacity_bps_hz"],
            label="One-stream MRC capacity",
            linewidth=1.2,
        )
        axes[3].plot(
            times_ms,
            strategy["parallel_capacity_proxy_bps_hz"],
            label="Independent-channel proxy",
            linewidth=1.2,
        )
        axes[3].set(
            title="Spectral-efficiency comparison\nProxy requires independent TX modes and an H matrix",
            xlabel="Time (ms)",
            ylabel="bit/s/Hz",
        )
        axes[3].grid(alpha=0.25)
        axes[3].legend(fontsize=8)
        self.canvas_spatial.draw()

    def export_metrics(self):
        if self.result is None:
            self.status.set("Run the simulation before exporting.")
            return
        path = filedialog.asksaveasfilename(
            title="Save integrated FSO results",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            initialfile="fso_multi_pd_results.csv",
        )
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as file_handle:
            writer = csv.writer(file_handle)
            writer.writerow([
                "method",
                "mean_evm_pct",
                "p95_evm_pct",
                "mean_ber",
                "outage_probability",
                "required_fade_margin_db",
                "mean_rx_power_dbm",
                "mean_effective_power_dbm",
                "mean_snr_db",
                "valid_frames",
            ])
            for name, metric in self.result["metrics"].items():
                writer.writerow([name] + [metric[key] for key in (
                    "mean_evm_pct",
                    "p95_evm_pct",
                    "mean_ber",
                    "outage_probability",
                    "required_fade_margin_db",
                    "mean_rx_power_dbm",
                    "mean_effective_power_dbm",
                    "mean_snr_db",
                    "valid_frames",
                )])
        self.status.set(f"Saved: {path}")


def main():
    root = tk.Tk()
    MultiPDLinkGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
