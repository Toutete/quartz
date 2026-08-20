# fso_gui.py
import tkinter as tk
from tkinter import ttk, messagebox
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.animation as animation
import matplotlib.patches as patches
from scipy.constants import pi
from skimage.restoration import unwrap_phase

from fso_engine import QAM_Modem, SSFM_Channel, Receiver_Array, ENGINE_BUILD_TAG

class FSOGUI:
    def __init__(self, master):
        self.master = master
        self.master.title("FSO GUI v2 (Time-Domain)")
        self.master.geometry("1600x950")
        self.ani = None
        self.is_playing = False
        self.cached_channel = None
        self.beam_cbar = None
        self.phase_cbar = None
        self.beam_vmin_dBm_m2 = -60.0
        self.beam_vmax_dBm_m2 = 10.0
        self._beam_scale_cache = {}
        self.lens_r_m = 0.02
        self.focal_len_m = 0.05
        self.pd_positions = [] 
        self.pd_artists = []   
        self.adding_pd = False
        self.setup_ui_layout()

    def setup_ui_layout(self):
        # --- Left Control Panel ---
        self.side_panel = ttk.Frame(self.master, width=380, padding=10)
        self.side_panel.pack(side=tk.LEFT, fill=tk.Y)
        
        ttk.Label(self.side_panel, text="[ System Parameters ]", font=("Segoe UI", 11, "bold")).pack(pady=(0, 10))
        self.inputs = {}
        params = [
            ("L", "Prop Distance (m)", "800"),
            ("Cn2", "Cn2 (Turbulence)", "1e-15"),
            ("N_screens", "Phase Screens", "5"),
            ("wind_speed", "Wind Speed (m/s)", "15.0"),
            ("w0_mm", "Gaussian Beam Waist w0 (mm)", "1.0"),
            ("tx_power_dbm", "Tx Optical Power (dBm)", "10"),
            ("beam_scale_gain", "Intensity Scale Gain", "1.0"),
            ("beam_vmin_dBm_m2", "Intensity Min [dBm/m^2] (<= -100 auto)", "-100"),
            ("beam_vmax_dBm_m2", "Intensity Max [dBm/m^2] (<= -100 auto)", "-100"),
            ("pd_active_r", "PD Active Radius (um)", "30.0"),
            ("gamma_th", "Outage Threshold (norm)", "0.3"),
            ("obs_time", "Obs Time (ms)", "20"),
            ("max_sim_frames", "Max Sim Frames", "40"),
            ("anim_frame_step", "Anim Frame Step", "1"),
            ("n_max", "Max Grid N (pow2)", "1024"),
            ("pupil_full_width_cm", "Pupil View Size (cm)", "120.0")
        ]
        for key, desc, default in params:
            frame = ttk.Frame(self.side_panel)
            frame.pack(fill=tk.X, pady=2)
            ttk.Label(frame, text=desc, width=28).pack(side=tk.LEFT)
            entry = ttk.Entry(frame, width=13)
            entry.insert(0, default)
            entry.pack(side=tk.RIGHT)
            self.inputs[key] = entry

        ttk.Separator(self.side_panel, orient='horizontal').pack(fill=tk.X, pady=10)
        ttk.Label(self.side_panel, text="[ PD Array Setup ]", font=("Segoe UI", 11, "bold")).pack(pady=(0, 5))

        pd_array_params = [
            ("pd_rows", "PD Rows", "2"),
            ("pd_cols", "PD Cols", "4"),
            ("pd_spacing_mm", "PD Spacing (mm)", "20"),
            ("pd_origin_x_mm", "Array Origin X (mm)", "0"),
            ("pd_origin_y_mm", "Array Origin Y (mm)", "0"),
        ]
        for key, desc, default in pd_array_params:
            frame = ttk.Frame(self.side_panel)
            frame.pack(fill=tk.X, pady=2)
            ttk.Label(frame, text=desc, width=28).pack(side=tk.LEFT)
            entry = ttk.Entry(frame, width=13)
            entry.insert(0, default)
            entry.pack(side=tk.RIGHT)
            self.inputs[key] = entry
        
        btn_frame = ttk.Frame(self.side_panel)
        btn_frame.pack(fill=tk.X, pady=5)
        self.btn_apply_array = ttk.Button(btn_frame, text="📐 Apply Array", command=self.apply_pd_array)
        self.btn_apply_array.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
        self.btn_add_pd = ttk.Button(btn_frame, text="✅ Add PD", command=self.toggle_add_pd)
        self.btn_add_pd.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
        self.btn_clear_pd = ttk.Button(btn_frame, text="🗑 Clear PDs", command=self.clear_pds)
        self.btn_clear_pd.pack(side=tk.RIGHT, expand=True, fill=tk.X, padx=2)
        
        ttk.Separator(self.side_panel, orient='horizontal').pack(fill=tk.X, pady=10)
        control_frame = ttk.Frame(self.side_panel)
        control_frame.pack(fill=tk.X, pady=10)
        self.btn_run = ttk.Button(control_frame, text="▶ Run Time-Domain Simulation", command=self.run_simulation)
        self.btn_run.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2, ipady=8)
        self.btn_pause = ttk.Button(control_frame, text="⏸ Pause", command=self.toggle_pause, state=tk.DISABLED)
        self.btn_pause.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=2, ipady=8)

        self.status_var = tk.StringVar(value="Status: Ready")
        ttk.Label(self.side_panel, textvariable=self.status_var, foreground="blue", font=("Segoe UI", 9, "bold")).pack(pady=(2, 8))

        self.pd_list_label = ttk.Label(self.side_panel, text="No PDs registered", foreground="purple")
        self.pd_list_label.pack(pady=(0, 6))

        # Result Table
        columns = ("Item", "Value", "Unit")
        self.tree_result = ttk.Treeview(self.side_panel, columns=columns, show="headings", height=8)
        self.tree_result.pack(fill=tk.X, pady=10)
        for col in columns: self.tree_result.heading(col, text=col)
        self.tree_result.column("Item", width=180, anchor=tk.W)
        self.tree_result.column("Value", width=80, anchor=tk.E)
        self.tree_result.column("Unit", width=80, anchor=tk.CENTER)

        # --- Right Notebook (single tab) ---
        self.notebook = ttk.Notebook(self.master)
        self.notebook.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Tab 1: Time-Domain (Animation)
        self.tab_time = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_time, text=" ⏳ Time-Domain ")

        self.time_toolbar = ttk.Frame(self.tab_time, padding=(4, 4))
        self.time_toolbar.pack(fill=tk.X)
        self.btn_run_time = ttk.Button(self.time_toolbar, text="▶ Run Time-Domain Simulation", command=self.run_time_simulation)
        self.btn_run_time.pack(side=tk.LEFT, padx=2)

        self.btn_play_anim = ttk.Button(self.time_toolbar, text="🎬 Play Animation", command=self.play_animation, state=tk.DISABLED)
        self.btn_play_anim.pack(side=tk.LEFT, padx=2)
        
        self.fig_time = plt.figure(figsize=(12, 8))
        self.fig_time.subplots_adjust(hspace=0.35, wspace=0.35)
        self.ax_beam = self.fig_time.add_subplot(2, 3, 1)
        self.ax_phase = self.fig_time.add_subplot(2, 3, 2)
        self.ax_phase_std = self.fig_time.add_subplot(2, 3, 3)
        self.ax_trace = self.fig_time.add_subplot(2, 3, 4)
        self.ax_scope = self.fig_time.add_subplot(2, 3, 5)
        self.ax_const = self.fig_time.add_subplot(2, 3, 6)
        
        self.canvas_time = FigureCanvasTkAgg(self.fig_time, master=self.tab_time)
        self.canvas_time.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.cid = self.canvas_time.mpl_connect('button_press_event', self.onclick)

        self.init_plots()

    def init_plots(self):
        self.ax_beam.set_title("Intensity")
        self.ax_phase.set_title("Phase Distribution")
        self.ax_phase_std.set_title("Phase Std [rad]")
        self._apply_pupil_axis_format()
        self.ax_trace.set_title("Truncation Loss Trace")
        self.ax_trace.set_xlabel("Time (ms)")
        self.ax_trace.set_ylabel("Received Power (dB)")
        self.ax_scope.set_title("Time-domain Signal (Scope View)")
        self.ax_scope.set_xlabel("Time (ns)")
        self.ax_scope.set_ylabel("Amplitude (a.u.)")
        self.ax_const.set_title("Constellation")
        self.ax_const.set_aspect('equal', adjustable='box')
        self.ax_const.set_xlabel("I")
        self.ax_const.set_ylabel("Q")

    def _apply_pupil_axis_format(self):
        for ax in [self.ax_beam, self.ax_phase, self.ax_phase_std]:
            ax.set_aspect('equal')
            ax.set_xlabel("x (cm)")
            ax.set_ylabel("y (cm)")
            ax.grid(True, linestyle=':', alpha=0.3)

    def _apply_rx_beam_scale(self, sim_params):
        beam_spot = sim_params['w0'] * np.sqrt(1 + (sim_params['lam'] * sim_params['L'] / (pi * sim_params['w0']**2))**2)
        rx_diameter_cm = 2 * beam_spot * 100.0
        rx_radius_cm = 0.5 * rx_diameter_cm
        
        # User defined view width
        half_width_cm = sim_params.get('display_full_width_cm', 100.0) / 2.0
        for ax in [self.ax_beam, self.ax_phase, self.ax_phase_std]:
            ax.set_xlim(-half_width_cm, half_width_cm)
            ax.set_ylim(-half_width_cm, half_width_cm)

        # 10-step visual scale referenced to Rx 1/e^2 diameter.
        for n in range(1, 11):
            ring = patches.Circle((0.0, 0.0), n * rx_radius_cm, edgecolor='white', facecolor='none', linestyle=':', lw=0.6, alpha=0.35)
            self.ax_beam.add_patch(ring)

    def _build_pd_array_from_inputs(self):
        rows = max(1, int(float(self.inputs["pd_rows"].get())))
        cols = max(1, int(float(self.inputs["pd_cols"].get())))
        spacing_m = max(0.0, float(self.inputs["pd_spacing_mm"].get()) / 1000.0)
        x0_m = float(self.inputs["pd_origin_x_mm"].get()) / 1000.0
        y0_m = float(self.inputs["pd_origin_y_mm"].get()) / 1000.0

        x_offset = (cols - 1) * spacing_m * 0.5
        y_offset = (rows - 1) * spacing_m * 0.5
        coords = []
        for r in range(rows):
            for c in range(cols):
                x = x0_m + c * spacing_m - x_offset
                y = y0_m + r * spacing_m - y_offset
                coords.append((x, y))
        return coords

    def apply_pd_array(self):
        try:
            self.pd_positions = self._build_pd_array_from_inputs()
            self._redraw_pd_artists()
            self.canvas_time.draw()
            self.status_var.set(f"Status: PD array applied ({len(self.pd_positions)} channels)")
        except Exception as e:
            messagebox.showerror("PD Array Error", str(e))

    def toggle_add_pd(self):
        self.adding_pd = True
        self.status_var.set("Status: Click beam plot to add a PD")
        self.btn_add_pd.configure(text="Waiting...", state=tk.DISABLED)

    def onclick(self, event):
        if self.adding_pd and event.inaxes == self.ax_beam:
            if event.xdata is None: return
            self.pd_positions.append((event.xdata/100.0, event.ydata/100.0))
            colors = ['cyan', 'yellow', 'lime', 'magenta', 'white']
            idx = len(self.pd_positions) - 1
            circle = patches.Circle(
                (event.xdata, event.ydata),
                self.lens_r_m*100.0,
                edgecolor=colors[idx % len(colors)],
                facecolor='none',
                linestyle='--',
                lw=1.5,
                label=f'PD{idx+1}'
            )
            self.ax_beam.add_patch(circle)
            self.pd_artists.append(circle)
            pd_text = "\n".join([f"PD{i+1}: ({x*1000:.1f}mm, {y*1000:.1f}mm)" for i, (x, y) in enumerate(self.pd_positions)])
            self.pd_list_label.config(text=pd_text if pd_text else "No PDs registered")
            self.ax_beam.legend(loc='upper right', fontsize='small')
            self.canvas_time.draw()
            self.btn_add_pd.configure(text="✅ Add PD", state=tk.NORMAL)
            self.status_var.set(f"Status: PD {idx+1} added")
            self.adding_pd = False

    def clear_pds(self):
        self.pd_positions = []
        for patch in self.pd_artists:
            try:
                patch.remove()
            except ValueError:
                pass
        self.pd_artists = []
        if self.ax_beam.legend_ is not None:
            self.ax_beam.legend_.remove()
        self.pd_list_label.config(text="No PDs registered")
        self.status_var.set("Status: PDs cleared")
        self.canvas_time.draw()

    def _stop_animation(self):
        if self.ani is not None:
            try:
                self.ani.event_source.stop()
            except Exception:
                pass
            self.ani = None
        self.is_playing = False
        self.btn_pause.config(state=tk.DISABLED, text="⏸ Pause")

    def _redraw_pd_artists(self):
        self.pd_artists = []
        colors = ['cyan', 'yellow', 'lime', 'magenta', 'white']
        for idx, (x_m, y_m) in enumerate(self.pd_positions):
            x_cm, y_cm = x_m * 100.0, y_m * 100.0
            circle = patches.Circle(
                (x_cm, y_cm),
                self.lens_r_m * 100.0,
                edgecolor=colors[idx % len(colors)],
                facecolor='none',
                linestyle='--',
                lw=1.5,
                label=f'PD{idx+1}'
            )
            self.ax_beam.add_patch(circle)
            self.pd_artists.append(circle)

        pd_text = "\n".join([f"PD{i+1}: ({x*1000:.1f}mm, {y*1000:.1f}mm)" for i, (x, y) in enumerate(self.pd_positions)])
        self.pd_list_label.config(text=pd_text if pd_text else "No PDs registered")
        if self.pd_artists:
            self.ax_beam.legend(loc='upper right', fontsize='small')

    def _reset_time_tab(self):
        self.ax_beam.clear()
        self.ax_phase.clear()
        self.ax_phase_std.clear()
        self.ax_trace.clear()
        self.ax_scope.clear()
        self.ax_const.clear()
        self.init_plots()
        self._redraw_pd_artists()

    def toggle_pause(self):
        if self.ani is None:
            return
        if self.is_playing:
            self.ani.event_source.stop()
            self.is_playing = False
            self.btn_pause.config(text="▶ Resume")
            self.status_var.set("Status: Paused")
        else:
            self.ani.event_source.start()
            self.is_playing = True
            self.btn_pause.config(text="⏸ Pause")
            self.status_var.set("Status: Running")

    def update_result_table(self, rows):
        for item in self.tree_result.get_children():
            self.tree_result.delete(item)
        for row in rows:
            self.tree_result.insert("", tk.END, values=row)

    def _parse_simulation_inputs(self):
        delta_t = 0.5e-3
        n_frames_raw = max(10, int(np.round(float(self.inputs["obs_time"].get()) / (delta_t * 1e3))))
        max_sim_frames = max(10, int(float(self.inputs["max_sim_frames"].get())))
        n_frames = min(n_frames_raw, max_sim_frames)
        lam_m = 1550e-9
        L_m = float(self.inputs["L"].get())
        w0_m = float(self.inputs["w0_mm"].get()) / 1000.0
        
        beam_spot_theory = w0_m * np.sqrt(1.0 + (lam_m * L_m / (pi * w0_m**2))**2)
        pupil_full_width_cm = float(self.inputs["pupil_full_width_cm"].get())
        Cn2 = float(self.inputs["Cn2"].get())
        
        # Estimate turbulence-induced long-term beam spreading
        k0 = 2.0 * pi / lam_m
        if Cn2 > 0:
            rho_0 = (0.423 * (k0**2) * Cn2 * L_m)**(-0.6)
            turb_spread = L_m * lam_m / rho_0
        else:
            turb_spread = 0.0
            
        effective_spot = np.sqrt(beam_spot_theory**2 + turb_spread**2)

        # Grid must be at least as large as the physical pupil view requested,
        # or large enough to capture the full turbulent beam spread
        d_obs = max(pupil_full_width_cm / 100.0, 4.0 * effective_spot)
        
        tx_power_dbm = float(self.inputs["tx_power_dbm"].get())
        beam_scale_gain = max(1e-6, float(self.inputs["beam_scale_gain"].get()))
        beam_vmin_override = float(self.inputs["beam_vmin_dBm_m2"].get())
        beam_vmax_override = float(self.inputs["beam_vmax_dBm_m2"].get())
        anim_frame_step = max(1, int(float(self.inputs["anim_frame_step"].get())))
        n_max_user = max(256, int(float(self.inputs["n_max"].get())))
        n_max_pow2 = int(2 ** np.ceil(np.log2(n_max_user)))
        n_max_pow2 = int(np.clip(n_max_pow2, 256, 16384))

        # For round-beam fidelity, target denser sampling across w0.
        target_dx = max(w0_m / 8.0, 1e-6)
        n_raw = int(np.ceil(d_obs / target_dx))
        n_pow2 = 2 ** int(np.ceil(np.log2(max(n_raw, 64))))
        n_grid = int(np.clip(n_pow2, 256, n_max_pow2))

        sim_params = {
            'N_screens': max(1, int(float(self.inputs["N_screens"].get()))),
            'lam': lam_m,
            'w0': w0_m,
            'l0': 0.005,
            'L0': 50.0,
            'L': L_m,
            'Cn2': float(self.inputs["Cn2"].get()),
            'wind_speed': float(self.inputs["wind_speed"].get()),
            'D_obs': d_obs,
            'display_full_width_cm': pupil_full_width_cm,
            'sim_full_width_cm': d_obs * 100.0,
            'delta_t': delta_t,
            'n_frames': n_frames,
            'n_frames_raw': n_frames_raw,
            'anim_frame_step': anim_frame_step,
            'N': n_grid,
            'n_max_pow2': n_max_pow2,
            'n_max_user': n_max_user,
            'tx_power_dbm': tx_power_dbm,
            'beam_scale_gain': beam_scale_gain,
            'beam_vmin_override_dBm_m2': beam_vmin_override,
            'beam_vmax_override_dBm_m2': beam_vmax_override,
            'required_sim_width_cm': d_obs * 100.0,
            'n_required_w0_8px': int(n_pow2),
        }
        gamma_th = float(self.inputs["gamma_th"].get())
        pd_active_r = float(self.inputs["pd_active_r"].get()) * 1e-6
        return sim_params, gamma_th, pd_active_r

    def _build_link_budget_rows(self, sim_params, r0_total, rytov_dz, pd_active_r_m, num_pds):
        lam = sim_params['lam']
        L = sim_params['L']
        w0 = sim_params['w0']
        dz = L / sim_params['N_screens']
        beam_spot = w0 * np.sqrt(1 + (lam * L / (pi * w0**2))**2)
        z_rayleigh = pi * w0**2 / lam
        full_divergence_rad = 2 * lam / (pi * w0)
        rx_beam_diameter = 2 * beam_spot
        k0 = 2 * pi / lam
        rytov_total = 1.23 * sim_params['Cn2'] * (k0**(7.0/6.0)) * (L**(11.0/6.0))
        pd_area_single = pi * pd_active_r_m**2
        pd_area_total = max(1, num_pds) * pd_area_single
        beam_area_rx = pi * beam_spot**2
        capture_eff = min(1.0, pd_area_total / (beam_area_rx + 1e-20))
        tx_mw = 10 ** (sim_params['tx_power_dbm'] / 10.0)
        rx_mw_theory = tx_mw * capture_eff
        rx_power_dbm = 10 * np.log10(rx_mw_theory + 1e-30)
        if rytov_total < 0.3:
            turb_regime = "Weak"
        elif rytov_total < 1.0:
            turb_regime = "Moderate"
        else:
            turb_regime = "Strong"
        dx_mm = (sim_params['D_obs'] / sim_params['N']) * 1000
        px_per_w0 = (w0 * 1000) / max(dx_mm, 1e-12)
        sampling_flag = "OK" if px_per_w0 >= 8 else "LOW - analytic source used"
        return [
            ("Tx Optical Power", f"{sim_params['tx_power_dbm']:.2f}", "dBm"),
            ("Input Beam Waist (w0)", f"{w0*1000:.2f}", "mm"),
            ("Rayleigh Range", f"{z_rayleigh:.1f}", "m"),
            ("Beam Divergence (Full)", f"{full_divergence_rad*1e3:.3f}", "mrad"),
            ("Rx Beam Diameter (1/e^2, Theory)", f"{rx_beam_diameter*1000:.2f}", "mm"),
            ("Rx Power (Theory)", f"{rx_power_dbm:.2f}", "dBm"),
            ("PD Active Area (single)", f"{pd_area_single*1e12:.2f}", "um^2"),
            ("PD Active Area (total)", f"{pd_area_total*1e12:.2f}", "um^2"),
            ("Capture Efficiency", f"{capture_eff:.3e}", "-"),
            ("Fried Parameter (r0)", f"{r0_total*1000:.2f}", "mm"),
            (f"Rytov Var (per-screen dz={dz:.1f}m)", f"{rytov_dz:.3f}", "-"),
            ("Rytov Var (L total)", f"{rytov_total:.3f}", turb_regime),
            ("Beam Spot Radius", f"{beam_spot*1000:.2f}", "mm"),
            ("Grid dx", f"{dx_mm:.3f}", "mm"),
            ("Pixels per w0", f"{px_per_w0:.2f}", sampling_flag),
            ("Grid N needed for 8 px/w0", f"{sim_params['n_required_w0_8px']}", "EA"),
            ("Grid N", f"{sim_params['N']}", "EA"),
            ("Grid N upper bound", f"{sim_params['n_max_pow2']}", "EA"),
            ("Grid N user input", f"{sim_params['n_max_user']}", "EA"),
            ("Sim Window Full Width", f"{sim_params['sim_full_width_cm']:.1f}", "cm"),
            ("Frames used / requested", f"{sim_params['n_frames']} / {sim_params['n_frames_raw']}", "EA"),
            ("Anim Frame Step", f"{sim_params['anim_frame_step']}", "-"),
        ]

    def _append_engine_diagnostics(self, rows, channel_data):
        alias_metric = channel_data.get('alias_metric', np.nan)
        substeps = channel_data.get('substeps_per_screen', 1)
        required_d = channel_data.get('required_D', np.nan)
        used_d = channel_data.get('used_D', np.nan)
        fresnel_limit = channel_data.get('fresnel_step_limit', np.nan)
        phase_cycle = channel_data.get('phase_cycle_frames', np.nan)
        prop_mode = channel_data.get('propagation_mode', 'unknown')
        px_per_w0_engine = channel_data.get('px_per_w0', np.nan)
        n_required_w0 = channel_data.get('n_required_w0_8px', np.nan)
        analytic_initial = channel_data.get('used_analytic_initial_gaussian', False)
        risk = "OK" if alias_metric <= 1.0 else "Risk"
        rows.extend([
            ("Engine Build", ENGINE_BUILD_TAG, "-"),
            ("Initial Gaussian Field", "analytic midpoint" if analytic_initial else "sampled z=0", "-"),
            ("Engine px per w0", f"{px_per_w0_engine:.2f}", "EA"),
            ("Engine N needed for 8 px/w0", f"{n_required_w0}", "EA"),
            ("Grid Width Required (engine)", f"{required_d*100:.1f}", "cm"),
            ("Grid Width Used (engine)", f"{used_d*100:.1f}", "cm"),
            ("Aliasing Metric (lambda*dz/(N*dx^2))", f"{alias_metric:.3f}", risk),
            ("Propagation Substeps per Screen", f"{substeps}", "EA"),
            ("Fresnel Step Limit", f"{fresnel_limit:.3e}", "m"),
            ("Propagation Mode", f"{prop_mode}", "-"),
            ("Phase Screen Cycle", f"{phase_cycle}", "frames"),
        ])
        return rows


    def _beam_scale_signature(self, sim_params):
        return (
            float(sim_params['L']),
            float(sim_params['w0']),
            float(sim_params['tx_power_dbm']),
            float(sim_params['lam']),
            float(sim_params.get('beam_scale_gain', 1.0)),
            float(sim_params.get('beam_vmin_override_dBm_m2', -100.0)),
            float(sim_params.get('beam_vmax_override_dBm_m2', -100.0)),
        )

    def _get_fixed_beam_scale(self, sim_params, x_arr, total_power_W, saved_rx_fields=None, dx_m=None):
        sig = self._beam_scale_signature(sim_params)
        if sig in self._beam_scale_cache:
            return self._beam_scale_cache[sig]

        # Turbulence-adaptive scenario scaling: map simulated intensity statistics
        # to absolute power-density using frame-wise total-power normalization.
        if saved_rx_fields is not None and dx_m is not None:
            intensity_cube = np.abs(saved_rx_fields) ** 2
            frame_power = np.sum(intensity_cube, axis=(0, 1)) * (dx_m**2) + 1e-30
            frame_scales = (total_power_W / frame_power)[None, None, :]
            power_density_W_m2 = intensity_cube * frame_scales
            power_density_dBm_m2 = 10 * np.log10(power_density_W_m2 * 1000 + 1e-30)

            vmax = float(np.percentile(power_density_dBm_m2, 99.9))
            if not np.isfinite(vmax) or vmax <= -100.0:
                vmax = 10.0
            
            # Avoid saturating the received Gaussian into a flat white disk.
            vmin = max(-100.0, vmax - 18.0)

            # User-adjustable intensity scale controls.
            gain = float(sim_params.get('beam_scale_gain', 1.0))
            # dB scale gain applied as shift. gain=1.0 -> +0dB shift, gain=10.0 -> +10dB shift.
            gain_dB = 10 * np.log10(gain + 1e-12)
            
            vmin_user = float(sim_params.get('beam_vmin_override_dBm_m2', -100.0))
            vmax_user = float(sim_params.get('beam_vmax_override_dBm_m2', -100.0))
            vmin = vmin if vmin_user <= -100.0 else vmin_user
            vmax = (vmax + gain_dB) if vmax_user <= -100.0 else vmax_user
            if vmax <= vmin:
                vmax = vmin + 1.0

            cfg = {
                'vmin': vmin,
                'vmax': vmax,
                'label': 'Power Density [dBm/m^2]',
            }
            self._beam_scale_cache[sig] = cfg
            self.beam_vmin_dBm_m2 = vmin
            self.beam_vmax_dBm_m2 = vmax
            return cfg

        beam_spot = sim_params['w0'] * np.sqrt(1.0 + (sim_params['lam'] * sim_params['L'] / (pi * sim_params['w0']**2))**2)
        xg, yg = np.meshgrid(x_arr, x_arr)
        r2 = xg**2 + yg**2

        # Reference received Gaussian beam profile from total received optical power.
        i_peak_w_m2 = (2.0 * total_power_W) / (pi * beam_spot**2 + 1e-30)
        i_ref_w_m2 = i_peak_w_m2 * np.exp(-2.0 * r2 / (beam_spot**2 + 1e-30))
        i_ref_dBm_m2 = 10 * np.log10(i_ref_w_m2 * 1000 + 1e-30)

        vmax = float(np.nanmax(i_ref_dBm_m2))
        vmin = max(-100.0, vmax - 18.0)
        
        gain = float(sim_params.get('beam_scale_gain', 1.0))
        gain_dB = 10 * np.log10(gain + 1e-12)
        
        vmin_user = float(sim_params.get('beam_vmin_override_dBm_m2', -100.0))
        vmax_user = float(sim_params.get('beam_vmax_override_dBm_m2', -100.0))
        vmin = vmin if vmin_user <= -100.0 else vmin_user
        vmax = (vmax + gain_dB) if vmax_user <= -100.0 else vmax_user
        if vmax <= vmin:
            vmax = vmin + 1.0

        cfg = {
            'vmin': vmin,
            'vmax': vmax,
            'label': 'Power Density [dBm/m^2]',
        }
        self._beam_scale_cache[sig] = cfg
        self.beam_vmin_dBm_m2 = vmin
        self.beam_vmax_dBm_m2 = vmax
        return cfg

    def _beam_display_config(self, field_complex, dx_m, total_power_W, fixed_scale):
        intensity = np.abs(field_complex) ** 2
        
        # Power matching
        current_power = np.sum(intensity) * (dx_m**2) + 1e-25
        power_density_W_m2 = intensity * (total_power_W / current_power)
        power_density_dBm_m2 = 10 * np.log10(power_density_W_m2 * 1000 + 1e-30)
            
        return power_density_dBm_m2, {
            'cmap': 'hot',
            'vmin': fixed_scale['vmin'],
            'vmax': fixed_scale['vmax'],
            'label': fixed_scale['label']
        }

    def _phase_display_config(self, field_complex, U_ideal=None):
        if U_ideal is not None:
            aberration_complex = field_complex * np.conj(U_ideal)
            phase_wrapped = np.angle(aberration_complex)
        else:
            phase_wrapped = np.angle(field_complex)
        try:
            phase = unwrap_phase(phase_wrapped)
            phase = phase - np.mean(phase)
        except Exception:
            phase = phase_wrapped

        vmax = float(np.max(np.abs(phase)))
        if vmax < 1e-3:
            vmax = 1.0
        return phase, {
            'cmap': 'viridis',
            'vmin': -vmax,
            'vmax': vmax,
            'label': 'Phase [rad]'
        }

    def _set_or_update_beam_colorbar(self, im, label_text):
        if self.beam_cbar is None:
            self.beam_cbar = self.fig_time.colorbar(im, ax=self.ax_beam, fraction=0.046, pad=0.04)
        else:
            self.beam_cbar.update_normal(im)
        self.beam_cbar.set_label(label_text)

    def _set_or_update_phase_colorbar(self, im, label_text):
        if self.phase_cbar is None:
            self.phase_cbar = self.fig_time.colorbar(im, ax=self.ax_phase, fraction=0.046, pad=0.04)
        else:
            self.phase_cbar.update_normal(im)
        self.phase_cbar.set_label(label_text)

    def _sim_signature(self, sim_params):
        return (
            sim_params['N_screens'], sim_params['lam'], sim_params['w0'], sim_params['l0'], sim_params['L0'],
            sim_params['L'], sim_params['Cn2'], sim_params['wind_speed'], sim_params['D_obs'],
            sim_params['delta_t'], sim_params['n_frames']
        )

    def _update_sampling_warning(self, sim_params):
        dx_mm = (sim_params['D_obs'] / sim_params['N']) * 1000
        px_per_w0 = (sim_params['w0'] * 1000) / max(dx_mm, 1e-12)
        if px_per_w0 < 8:
            self.status_var.set(f"Status: Warning - low z=0 sampling ({px_per_w0:.2f} px/w0); using analytic midpoint source.")
        elif sim_params['n_max_pow2'] < sim_params['n_max_user']:
            self.status_var.set(f"Status: N upper bound clipped to {sim_params['n_max_pow2']} for memory safety")
        elif sim_params['n_frames'] < sim_params['n_frames_raw']:
            self.status_var.set(f"Status: Frames capped for speed ({sim_params['n_frames']}/{sim_params['n_frames_raw']})")

    def _get_channel_data(self, sim_params):
        signature = self._sim_signature(sim_params)
        if self.cached_channel and self.cached_channel['signature'] == signature:
            return self.cached_channel

        channel = SSFM_Channel(sim_params)
        saved_rx_fields, x_arr, r0_total, rytov_dz = channel.generate_spatiotemporal_beams()
        self.cached_channel = {
            'signature': signature,
            'saved_rx_fields': saved_rx_fields,
            'x_arr': x_arr,
            'r0_total': r0_total,
            'rytov_dz': rytov_dz,
            'alias_metric': getattr(channel, 'alias_metric', np.nan),
            'substeps_per_screen': getattr(channel, 'substeps_per_screen', 1),
            'required_D': getattr(channel, 'required_D', np.nan),
            'used_D': getattr(channel, 'used_D', np.nan),
            'fresnel_step_limit': getattr(channel, 'fresnel_step_limit', np.nan),
            'phase_cycle_frames': getattr(channel, 'phase_cycle_frames', np.nan),
            'propagation_mode': getattr(channel, 'propagation_mode', 'unknown'),
            'px_per_w0': getattr(channel, 'px_per_w0', np.nan),
            'n_required_w0_8px': getattr(channel, 'n_required_w0_8px', np.nan),
            'used_analytic_initial_gaussian': getattr(channel, 'used_analytic_initial_gaussian', False),
            'U_ideal': getattr(channel, 'U_ideal', None),
        }
        return self.cached_channel

    def run_simulation(self):
        self.run_time_simulation()

    def run_time_simulation(self):
        self._stop_animation()
        self._reset_time_tab()
        self.btn_run.config(state=tk.DISABLED, text="Simulating...")
        self.btn_run_time.config(state=tk.DISABLED)
        self.status_var.set("Status: Running time-domain simulation...")
        self.master.update()

        try:
            sim_params, gamma_th, pd_active_r = self._parse_simulation_inputs()
            if len(self.pd_positions) == 0:
                # Do not auto-initialize PDs if none exist.
                # Just show beam and phase
                pass
            self._update_sampling_warning(sim_params)
            delta_t = sim_params['delta_t']
            n_frames = sim_params['n_frames']
            channel_data = self._get_channel_data(sim_params)
            saved_rx_fields = channel_data['saved_rx_fields']
            x_arr = channel_data['x_arr']
            r0_total = channel_data['r0_total']
            rytov_dz = channel_data['rytov_dz']
            U_ideal = channel_data.get('U_ideal', None)

            has_pds = len(self.pd_positions) > 0

            # -------------------------------------------------------------
            # [TAB 1 Logic] Time Domain & Truncation Loss (User's placement)
            # -------------------------------------------------------------
            receiver = Receiver_Array(self.pd_positions, self.lens_r_m, pd_active_r, self.focal_len_m, x_arr, sim_params['lam'])
            result_rows = self._build_link_budget_rows(sim_params, r0_total, rytov_dz, pd_active_r_m=pd_active_r, num_pds=receiver.num_pds)
            result_rows = self._append_engine_diagnostics(result_rows, channel_data)

            center_idx = len(x_arr) // 2
            center_trace = np.abs(saved_rx_fields[center_idx, center_idx, :]) ** 2
            scint_idx = np.var(center_trace) / (np.mean(center_trace) ** 2 + 1e-30)
            
            dx_m = sim_params['D_obs'] / sim_params['N']
            tx_power_W = 10 ** ((sim_params['tx_power_dbm'] - 30) / 10.0)
            beam_spot = sim_params['w0'] * np.sqrt(1 + (sim_params['lam'] * sim_params['L'] / (pi * sim_params['w0']**2))**2)
            fixed_scale = self._get_fixed_beam_scale(
                sim_params,
                x_arr,
                tx_power_W,
                saved_rx_fields=saved_rx_fields,
                dx_m=dx_m
            )

            if has_pds:
                # Scale fields so per-frame total power equals Tx power.
                # This enables physically interpretable coupled-power traces in watts.
                frame_power = np.sum(np.abs(saved_rx_fields) ** 2, axis=(0, 1)) * (dx_m**2) + 1e-30
                field_scale = np.sqrt(tx_power_W / frame_power)[None, None, :]
                saved_rx_fields_watt = saved_rx_fields * field_scale

                traces, trace_combined, traces_abs, trace_combined_abs = receiver.compute_focal_coupling(
                    saved_rx_fields_watt,
                    normalize=True,
                    return_absolute=True
                )
                outage_combined = np.sum(trace_combined < gamma_th) / n_frames
                pd_area_total = receiver.num_pds * pi * (pd_active_r**2)
                beam_area_rx = pi * beam_spot**2
                capture_eff = min(1.0, pd_area_total / (beam_area_rx + 1e-20))
                rx_mw_theory = (10 ** (sim_params['tx_power_dbm'] / 10.0)) * capture_eff
                rx_power_avg_dbm = 10*np.log10(rx_mw_theory + 1e-30) + 10*np.log10(np.mean(trace_combined) + 1e-15)
                rx_power_abs_avg_W = float(np.mean(trace_combined_abs))
                rx_ratio_db = 10.0 * np.log10((rx_power_abs_avg_W + 1e-30) / (tx_power_W + 1e-30))
                result_rows.append(("User Array Outage", f"{outage_combined:.4f}", "-") )
                result_rows.append(("Rx Power (Time Avg)", f"{rx_power_avg_dbm:.2f}", "dBm"))
                result_rows.append(("Rx/Tx Ratio (focal coupled)", f"{rx_ratio_db:.2f}", "dB"))

                modem = QAM_Modem(M=16)
                num_symbols = 120
                tx_symbols = modem.generate_signal(num_symbols)
                t_if, tx_wf = modem.generate_rf_waveform(tx_symbols[:20])

            if U_ideal is not None:
                aberration_fields = saved_rx_fields * np.conj(U_ideal)[:, :, None]
                phase_unwrapped = np.unwrap(np.angle(aberration_fields), axis=2)
            else:
                phase_unwrapped = np.unwrap(np.angle(saved_rx_fields), axis=2)
            phase_std_map = np.std(phase_unwrapped, axis=2)

            self.ax_trace.clear()
            self.ax_scope.clear()
            self.ax_const.clear()

            if has_pds:
                self.ax_trace.set_visible(True)
                self.ax_trace.set_title("Truncation Loss Trace")
                time_ms = np.arange(n_frames) * delta_t * 1e3
                for i in range(receiver.num_pds):
                    self.ax_trace.plot(time_ms, 10*np.log10(traces[i] + 1e-12), alpha=0.3)
                self.ax_trace.plot(time_ms, 10*np.log10(trace_combined + 1e-12), color='red', lw=2.5, label='Combined (EGC)')
                self.vl = self.ax_trace.axvline(time_ms[0], color='blue', linestyle='--')
                self.ax_trace.grid(True, alpha=0.3)
                self.ax_trace.set_xlabel("Time (ms)")
                self.ax_trace.set_ylabel("Received Power (dB, norm)")

                self.ax_scope.set_visible(True)
                self.ax_scope.set_title("Time-domain Signal (Scope View)")
                self.ax_scope.set_xlabel("Time (ns)")
                self.ax_scope.set_ylabel("Amplitude (a.u.)")
                self.line_scope, = self.ax_scope.plot(t_if, tx_wf, color='orange', lw=1.5)
                self.ax_scope.set_ylim(-0.2, 2.5)

                self.ax_const.set_visible(True)
                self.ax_const.set_title("Constellation")
                self.ax_const.set_aspect('equal', adjustable='box')
                rx_eq, evm = modem.demodulate_and_calc_evm(tx_symbols, tx_symbols + np.random.randn(len(tx_symbols))*0.1) # placeholder
                rx_eq = tx_symbols * (np.mean(trace_combined) + 1e-3) + np.random.randn(len(tx_symbols))*0.1 + 1j*np.random.randn(len(tx_symbols))*0.1 # fading sim
                self.scatter_const = self.ax_const.scatter(np.real(rx_eq), np.imag(rx_eq), color='blue', alpha=0.6, s=15)
                self.ax_const.set_xlim(-2.5, 2.5)
                self.ax_const.set_ylim(-2.5, 2.5)

            else:
                self.ax_trace.set_visible(True)
                self.ax_scope.set_visible(True)
                self.ax_const.set_visible(True)
                self.ax_trace.text(0.5, 0.5, "Add PD to view Trace", ha='center', va='center', transform=self.ax_trace.transAxes)
                self.ax_scope.text(0.5, 0.5, "Add PD to view Scope", ha='center', va='center', transform=self.ax_scope.transAxes)
                self.ax_const.text(0.5, 0.5, "Add PD to view Constellation", ha='center', va='center', transform=self.ax_const.transAxes)

            ext = [x_arr[0]*100.0, x_arr[-1]*100.0, x_arr[0]*100.0, x_arr[-1]*100.0]
            beam_disp0, disp_cfg = self._beam_display_config(saved_rx_fields[:, :, 0], dx_m, tx_power_W, fixed_scale)
            self.im_beam = self.ax_beam.imshow(
                beam_disp0,
                cmap=disp_cfg['cmap'],
                origin='lower',
                extent=ext,
                vmin=disp_cfg['vmin'],
                vmax=disp_cfg['vmax'],
                interpolation='nearest'
            )
            self._set_or_update_beam_colorbar(self.im_beam, disp_cfg['label'])

            phase_disp0, phase_cfg = self._phase_display_config(saved_rx_fields[:, :, 0], U_ideal)
            self.im_phase = self.ax_phase.imshow(
                phase_disp0,
                cmap=phase_cfg['cmap'],
                origin='lower',
                extent=ext,
                vmin=phase_cfg['vmin'],
                vmax=phase_cfg['vmax'],
                interpolation='nearest'
            )
            self._set_or_update_phase_colorbar(self.im_phase, phase_cfg['label'])
            
            self.im_phase_std = self.ax_phase_std.imshow(
                phase_std_map,
                cmap='viridis',
                origin='lower',
                extent=ext,
                vmin=0.0,
                vmax=2.0,
                interpolation='bilinear'
            )
            if not hasattr(self, 'phase_std_cbar') or self.phase_std_cbar is None:
                self.phase_std_cbar = self.fig_time.colorbar(self.im_phase_std, ax=self.ax_phase_std, fraction=0.046, pad=0.04)
            else:
                self.phase_std_cbar.update_normal(self.im_phase_std)
            self.phase_std_cbar.set_label('Phase Std [rad]')
            
            # Draw Fried Parameter r0 circle
            r0_cm = r0_total * 100.0
            self.r0_circle = patches.Circle((0.0, 0.0), r0_cm, edgecolor='green', facecolor='none', linestyle='--', lw=2.0, label=f'$r_0$ = {r0_cm:.1f} cm')
            self.ax_phase_std.add_patch(self.r0_circle)
            self.ax_phase_std.legend(loc='upper right')
            
            self._apply_rx_beam_scale(sim_params)
            self._redraw_pd_artists()

            def update(frame):
                beam_disp, disp_cfg_now = self._beam_display_config(saved_rx_fields[:, :, frame], dx_m, tx_power_W, fixed_scale)
                self.im_beam.set_data(beam_disp)
                self.im_beam.set_clim(disp_cfg_now['vmin'], disp_cfg_now['vmax'])

                phase_disp, phase_cfg_now = self._phase_display_config(saved_rx_fields[:, :, frame], U_ideal)
                self.im_phase.set_data(phase_disp)
                self.im_phase.set_clim(phase_cfg_now['vmin'], phase_cfg_now['vmax'])
                
                artists = [self.im_beam, self.im_phase]
                
                if has_pds:
                    self.vl.set_xdata([time_ms[frame], time_ms[frame]])
                    fade_val = trace_combined[frame]
                    self.line_scope.set_ydata(tx_wf * fade_val + np.random.randn(len(tx_wf))*0.02)
                    
                    rx_eq_temp = tx_symbols * fade_val + (np.random.randn(len(tx_symbols)) + 1j*np.random.randn(len(tx_symbols))) * 0.1
                    self.scatter_const.set_offsets(np.c_[np.real(rx_eq_temp), np.imag(rx_eq_temp)])
                    artists.extend([self.vl, self.line_scope, self.scatter_const])

                return artists + self.pd_artists

            self.fig_time.canvas.draw_idle()

            # Store animation lambda & arguments for the play_animation function 
            self._anim_playback_data = {
                'update_func': update,
                'anim_frames': range(0, n_frames, sim_params['anim_frame_step'])
            }
            
            self.canvas_time.draw()
            self.btn_play_anim.config(state=tk.NORMAL)
            self.status_var.set("Status: Time-domain simulation complete (Ready to play animation)")

            result_rows.append(("Scintillation Index (center)", f"{scint_idx:.3f}", "-"))
            result_rows.append(("Beam Display Range", f"[{self.beam_vmin_dBm_m2:.1f}, {self.beam_vmax_dBm_m2:.1f}]", "dBm/m^2"))
            if scint_idx < 0.03:
                result_rows.append(("Turbulence Visibility Hint", "Increase Cn2 or L for stronger scintillation", "-"))

            self.update_result_table(result_rows)

        except Exception as e:
            import traceback; traceback.print_exc()
            messagebox.showerror("Simulation Error", str(e))
            self.status_var.set("Status: Error occurred")
        finally:
            self.btn_run.config(state=tk.NORMAL, text="▶ Run Time-Domain Simulation")
            self.btn_run_time.config(state=tk.NORMAL)

    def play_animation(self):
        if not hasattr(self, '_anim_playback_data') or self._anim_playback_data is None:
            return

        # Stop existing anim if needed
        self._stop_animation()

        update_func = self._anim_playback_data['update_func']
        anim_frames = self._anim_playback_data['anim_frames']

        self.ani = animation.FuncAnimation(
            self.fig_time, update_func, frames=anim_frames, 
            interval=80, blit=False, cache_frame_data=False
        )
        self.canvas_time.draw()
        self.is_playing = True
        self.btn_pause.config(state=tk.NORMAL, text="⏸ Pause")
        self.status_var.set("Status: Playing Time-domain Animation")

if __name__ == "__main__":
    root = tk.Tk()
    app = FSOGUI(root)
    root.mainloop()
