import os
import re
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from scipy.constants import e, epsilon_0, pi


class HybridFSOGUI:
    def __init__(self, master):
        self.master = master
        self.master.title("Hybrid FSO Simulator")
        self.master.geometry("1680x980")

        self.inputs = {}

        self._build_layout()
        self._draw_schematic()

    def _build_layout(self):
        self.left = ttk.Frame(self.master, width=430, padding=10)
        self.left.pack(side=tk.LEFT, fill=tk.Y)

        self.right = ttk.Frame(self.master, padding=10)
        self.right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        self._build_controls(self.left)
        self._build_results(self.left)
        self._build_tabs(self.right)

    def _build_controls(self, parent):
        ttk.Label(parent, text="[ Hybrid FSO Parameters ]", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 8))

        self.control_canvas = tk.Canvas(parent, borderwidth=0, highlightthickness=0, width=410, height=560)
        self.control_scroll = ttk.Scrollbar(parent, orient="vertical", command=self.control_canvas.yview)
        self.control_frame = ttk.Frame(self.control_canvas)

        self.control_frame.bind(
            "<Configure>",
            lambda _e: self.control_canvas.configure(scrollregion=self.control_canvas.bbox("all")),
        )
        self.control_canvas.create_window((0, 0), window=self.control_frame, anchor="nw")
        self.control_canvas.configure(yscrollcommand=self.control_scroll.set)

        self.control_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=False)
        self.control_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self._add_group(
            "Phase 1: Optical",
            [
                ("tx_power_dbm", "Tx Power (dBm)", "10"),
                ("wavelength_nm", "Wavelength (nm)", "1550"),
                ("beam_waist_mm", "Beam Waist w0 (mm)", "1"),
                ("distance_m", "Tx-Rx Distance (m)", "800"),
                ("rx_beam_diam_mm", "Beam Diameter @Rx (mm)", "800"),
                ("rx_lens_diam_mm", "Rx Lens Diameter (mm)", "127"),
                ("optical_loss_db", "Reducer/Optics Loss (dB)", "1"),
                ("coupling_loss_db", "PD Coupling Loss (dB)", "3"),
                ("pd_diam_um", "PD Diameter (um)", "30"),
                ("pd_x_mm", "PD x position (mm)", "0"),
                ("pd_y_mm", "PD y position (mm)", "0"),
            ],
        )

        self._add_group(
            "Phase 2: PD + TIA + Weight",
            [
                ("responsivity_aw", "PD Responsivity (A/W)", "0.9"),
                ("pd_eps_r", "InGaAs Relative Permittivity", "13.9"),
                ("pd_depletion_um", "PD Depletion Width d (um)", "2"),
                ("tia_rin_ohm", "TIA Input Impedance Rin (ohm)", "50"),
                ("carrier_vsat_cm_s", "Carrier Saturation v_sat (cm/s)", "1e7"),
                ("tia_gain_db", "TIA Gain (dB)", "30"),
                ("tia_diff_transimp_ohm", "TIA Diff Transimpedance (ohm)", "4700"),
                ("tia_in_noise_pa", "TIA In Noise (pA/sqrt(Hz))", "10"),
                ("tia_out_ohm", "TIA Output Impedance (ohm)", "50"),
                ("weight_gain_db", "Weight Gain/Atten (dB)", "-5"),
                ("weight_nf_db", "Weight NF (dB)", "6"),
                ("ampm_deg_per_db", "AM-to-PM (deg/dB)", "2.0"),
            ],
        )

        self._add_group(
            "SNP / Response Files",
            [
                ("resp_freq_file", "Resp-vs-Frequency (.csv)", ""),
                ("tia_s2p_file", "TIA Touchstone (.s2p/.s3p)", ""),
                ("weight_s2p_file", "Weight Touchstone (.s2p)", ""),
            ],
            allow_browse=True,
        )

        self._add_group(
            "Phase 3: DSO / DSP",
            [
                ("if_freq_ghz", "IF Frequency (GHz)", "20"),
                ("fs_ghz", "DSO Sample Rate (GHz)", "100"),
                ("duration_ns", "Capture Duration (ns)", "100"),
                ("num_symbols", "Symbol Count", "800"),
                ("mod_order", "QAM Order (4/16)", "4"),
            ],
        )

        btn_row = ttk.Frame(self.control_frame)
        btn_row.pack(fill=tk.X, pady=(8, 5))
        self.btn_run = ttk.Button(btn_row, text="Run Full Hybrid Simulation", command=self.run_simulation)
        self.btn_run.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4), ipady=5)

        self.status_var = tk.StringVar(value="Status: Ready")
        ttk.Label(parent, textvariable=self.status_var, foreground="blue", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(8, 0))

    def _add_group(self, title, rows, allow_browse=False):
        group = ttk.LabelFrame(self.control_frame, text=title, padding=8)
        group.pack(fill=tk.X, pady=5)

        for key, label, default in rows:
            row = ttk.Frame(group)
            row.pack(fill=tk.X, pady=2)

            ttk.Label(row, text=label, width=31).pack(side=tk.LEFT)

            entry = ttk.Entry(row, width=22)
            entry.insert(0, default)
            entry.pack(side=tk.RIGHT)
            self.inputs[key] = entry

            if allow_browse and key.endswith("_file"):
                ttk.Button(row, text="...", width=3, command=lambda k=key: self._browse_file(k)).pack(side=tk.RIGHT, padx=(3, 0))

    def _browse_file(self, key):
        path = filedialog.askopenfilename(title="Select File")
        if path:
            self.inputs[key].delete(0, tk.END)
            self.inputs[key].insert(0, path)

    def _build_results(self, parent):
        ttk.Separator(parent, orient="horizontal").pack(fill=tk.X, pady=8)
        ttk.Label(parent, text="[ Key Results ]", font=("Segoe UI", 10, "bold")).pack(anchor="w")

        cols = ("Metric", "Value", "Unit")
        self.tree = ttk.Treeview(parent, columns=cols, show="headings", height=10)
        self.tree.pack(fill=tk.X, pady=(6, 0))

        for col in cols:
            self.tree.heading(col, text=col)
        self.tree.column("Metric", width=215, anchor=tk.W)
        self.tree.column("Value", width=95, anchor=tk.E)
        self.tree.column("Unit", width=90, anchor=tk.CENTER)

    def _build_tabs(self, parent):
        self.notebook = ttk.Notebook(parent)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self.tab_optical = ttk.Frame(self.notebook)
        self.tab_circuit = ttk.Frame(self.notebook)
        self.tab_dso = ttk.Frame(self.notebook)
        self.tab_schematic = ttk.Frame(self.notebook)

        self.notebook.add(self.tab_optical, text="Phase 1 Optical")
        self.notebook.add(self.tab_circuit, text="Phase 2 Circuit/RF")
        self.notebook.add(self.tab_dso, text="Phase 3 DSO/DSP")
        self.notebook.add(self.tab_schematic, text="Schematic View")

        self.fig_opt = plt.Figure(figsize=(11, 7), dpi=100)
        self.ax_opt_beam = self.fig_opt.add_subplot(2, 2, 1)
        self.ax_opt_bars = self.fig_opt.add_subplot(2, 2, 2)
        self.ax_opt_fill = self.fig_opt.add_subplot(2, 2, 3)
        self.ax_opt_text = self.fig_opt.add_subplot(2, 2, 4)
        self.canvas_opt = FigureCanvasTkAgg(self.fig_opt, master=self.tab_optical)
        self.canvas_opt.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        self.fig_cir = plt.Figure(figsize=(11, 7), dpi=100)
        self.ax_cir_power = self.fig_cir.add_subplot(2, 2, 1)
        self.ax_cir_snr = self.fig_cir.add_subplot(2, 2, 2)
        self.ax_cir_phase = self.fig_cir.add_subplot(2, 2, 3)
        self.ax_cir_noise = self.fig_cir.add_subplot(2, 2, 4)
        self.canvas_cir = FigureCanvasTkAgg(self.fig_cir, master=self.tab_circuit)
        self.canvas_cir.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        self.fig_dso = plt.Figure(figsize=(11, 7), dpi=100)
        self.ax_dso_time = self.fig_dso.add_subplot(2, 2, 1)
        self.ax_dso_spec = self.fig_dso.add_subplot(2, 2, 2)
        self.ax_dso_const = self.fig_dso.add_subplot(2, 2, 3)
        self.ax_dso_metrics = self.fig_dso.add_subplot(2, 2, 4)
        self.canvas_dso = FigureCanvasTkAgg(self.fig_dso, master=self.tab_dso)
        self.canvas_dso.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        self.schematic_canvas = tk.Canvas(self.tab_schematic, bg="#05080d", highlightthickness=0)
        self.schematic_canvas.pack(fill=tk.BOTH, expand=True)
        self.schematic_canvas.bind("<Configure>", lambda _e: self._draw_schematic())

    def _get_float(self, key):
        return float(self.inputs[key].get().strip())

    def _get_int(self, key):
        return int(float(self.inputs[key].get().strip()))

    def _dbm_to_w(self, dbm):
        return 10 ** ((dbm - 30.0) / 10.0)

    def _w_to_dbm(self, watts):
        return 10.0 * np.log10(np.maximum(watts, 1e-30)) + 30.0

    def _touchstone_freq_scale(self, unit):
        lut = {"hz": 1.0, "khz": 1e3, "mhz": 1e6, "ghz": 1e9}
        return lut.get(unit.lower(), 1.0)

    def _parse_touchstone_s21_db(self, file_path, target_hz):
        if not file_path or not os.path.isfile(file_path):
            return None

        ext = os.path.splitext(file_path)[1].lower()
        m = re.match(r"\.s(\d+)p", ext)
        if not m:
            return None
        n_ports = int(m.group(1))

        freq_scale = 1e9
        data_fmt = "ma"

        freqs = []
        s21_db = []

        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("!"):
                    continue
                if line.startswith("#"):
                    toks = line[1:].strip().split()
                    if len(toks) >= 3:
                        freq_scale = self._touchstone_freq_scale(toks[0])
                        data_fmt = toks[2].lower()
                    continue

                vals = line.split("!")[0].strip().split()
                need = 1 + 2 * n_ports * n_ports
                if len(vals) < need:
                    continue

                nums = [float(v) for v in vals[:need]]
                freq_hz = nums[0] * freq_scale

                # Touchstone order index for S21 in 0-based (to=2, from=1).
                s21_idx = 1
                base = 1 + 2 * s21_idx
                a = nums[base]
                b = nums[base + 1]

                if data_fmt == "db":
                    val_db = a
                elif data_fmt == "ma":
                    val_db = 20.0 * np.log10(np.maximum(a, 1e-30))
                elif data_fmt == "ri":
                    mag = np.hypot(a, b)
                    val_db = 20.0 * np.log10(np.maximum(mag, 1e-30))
                else:
                    continue

                freqs.append(freq_hz)
                s21_db.append(val_db)

        if not freqs:
            return None

        freqs = np.array(freqs)
        s21_db = np.array(s21_db)
        idx = int(np.argmin(np.abs(freqs - target_hz)))
        return float(s21_db[idx])

    def _parse_resp_file_scale(self, file_path, target_hz):
        # Expected CSV: frequency_hz, responsivity_A_per_W
        if not file_path or not os.path.isfile(file_path):
            return 1.0

        try:
            data = np.loadtxt(file_path, delimiter=",", comments="#")
            if data.ndim == 1 or data.shape[1] < 2:
                return 1.0
            freq = data[:, 0]
            resp = data[:, 1]
            if len(freq) == 0:
                return 1.0
            idx = int(np.argmin(np.abs(freq - target_hz)))
            ref = np.maximum(resp[0], 1e-30)
            return float(np.maximum(resp[idx], 1e-30) / ref)
        except Exception:
            return 1.0

    def _simulate_optical_phase(self, p):
        p_tx_w = self._dbm_to_w(p["tx_power_dbm"])
        lam = p["wavelength_nm"] * 1e-9
        w0 = p["beam_waist_mm"] * 1e-3
        z = p["distance_m"]

        z_r = pi * (w0 ** 2) / lam
        w_z = w0 * np.sqrt(1.0 + (z / z_r) ** 2)

        beam_area_rx = pi * (w_z ** 2)

        # User-specified beam diameter at Rx for link-budget stage computation.
        w_l_user = 0.5 * p["rx_beam_diam_mm"] * 1e-3
        lens_r = 0.5 * p["rx_lens_diam_mm"] * 1e-3
        a_lens = pi * (lens_r ** 2)
        # Gaussian encircled power at lens aperture: Pcap = Ptx*(1-exp(-2*r^2/w^2)).
        capture_frac = 1.0 - np.exp(-2.0 * lens_r * lens_r / np.maximum(w_l_user * w_l_user, 1e-30))
        capture_frac = float(np.clip(capture_frac, 0.0, 1.0))
        p_cap = p_tx_w * capture_frac

        p_after_optics = p_cap * (10 ** (-p["optical_loss_db"] / 10.0))
        p_pd_real = p_after_optics * (10 ** (-p["coupling_loss_db"] / 10.0))

        pd_r = 0.5 * p["pd_diam_um"] * 1e-6
        a_pd = pi * (pd_r ** 2)

        x_pd = p["pd_x_mm"] * 1e-3
        y_pd = p["pd_y_mm"] * 1e-3
        r2 = x_pd * x_pd + y_pd * y_pd

        # Local intensity estimate from propagated Gaussian footprint (diagnostic).
        i_pd_local = (2.0 * p_cap / np.maximum(pi * w_z * w_z, 1e-30)) * np.exp(-2.0 * r2 / np.maximum(w_z * w_z, 1e-30))
        p_rx_pd_local = i_pd_local * a_pd

        fspl_db = 20.0 * np.log10((4.0 * pi * z) / lam)
        rx_friis_dbm = p["tx_power_dbm"] - fspl_db
        p_rx_pathloss_w = p_tx_w * (lam / (4.0 * pi * z)) ** 2

        theta_half_rad = lam / np.maximum(pi * w0, 1e-30)
        theta_full_rad = 2.0 * theta_half_rad

        return {
            "p_tx_w": p_tx_w,
            "lam": lam,
            "w0": w0,
            "z": z,
            "z_r": z_r,
            "w_z": w_z,
            "beam_area_rx": beam_area_rx,
            "w_l_user": w_l_user,
            "a_lens": a_lens,
            "a_pd": a_pd,
            "lens_capture": capture_frac,
            "p_cap": p_cap,
            "p_after_optics": p_after_optics,
            "p_rx_pd_w": p_pd_real,
            "i_pd_local": i_pd_local,
            "p_rx_pd_local": p_rx_pd_local,
            "fspl_db": fspl_db,
            "rx_friis_dbm": rx_friis_dbm,
            "p_rx_pathloss_w": p_rx_pathloss_w,
            "theta_half_rad": theta_half_rad,
            "theta_full_rad": theta_full_rad,
        }

    def _simulate_circuit_phase(self, p, opt):
        pd_r = p["responsivity_aw"]
        target_hz = p["if_freq_ghz"] * 1e9

        resp_scale = self._parse_resp_file_scale(self.inputs["resp_freq_file"].get().strip(), target_hz)
        pd_r_eff = pd_r * resp_scale

        p_rx = opt["p_rx_pd_w"]
        i_photo = pd_r_eff * p_rx
        # Assume full-scale sinusoidal modulation around photocurrent for RMS signal current.
        i_sig_rms = np.maximum(i_photo, 0.0) / np.sqrt(2.0)

        # PD capacitance and bandwidth model:
        # 1) Cj = eps0 * eps_r * A / d
        # 2) f_RC = 1/(2*pi*Rin*Cj)
        # 3) f_tr ~= 0.44/tau_tr, tau_tr = d / v_sat
        # 4) f_3dB = 1 / sqrt((1/f_RC)^2 + (1/f_tr)^2)
        a_pd_m2 = np.maximum(opt["a_pd"], 1e-30)
        d_dep_m = np.maximum(p["pd_depletion_um"] * 1e-6, 1e-12)
        eps_r = np.maximum(p["pd_eps_r"], 1e-12)
        c_j = epsilon_0 * eps_r * a_pd_m2 / d_dep_m

        r_in = np.maximum(p["tia_rin_ohm"], 1e-12)
        tau_rc = r_in * c_j
        f_rc = 1.0 / np.maximum(2.0 * pi * tau_rc, 1e-30)

        v_sat_m_s = np.maximum(p["carrier_vsat_cm_s"] * 1e-2, 1e-3)
        tau_tr = d_dep_m / v_sat_m_s
        f_tr = 0.44 / np.maximum(tau_tr, 1e-30)

        bw_hz = 1.0 / np.sqrt((1.0 / np.maximum(f_rc, 1e-30)) ** 2 + (1.0 / np.maximum(f_tr, 1e-30)) ** 2)

        # Noise terms: shot noise + TIA input-referred current noise.
        i_shot_rms = np.sqrt(2.0 * e * np.maximum(i_photo, 0.0) * np.maximum(bw_hz, 1.0))
        i_tia_density = p["tia_in_noise_pa"] * 1e-12

        i_tia_rms = i_tia_density * np.sqrt(np.maximum(bw_hz, 1.0))
        i_total_noise_rms = np.sqrt(i_shot_rms * i_shot_rms + i_tia_rms * i_tia_rms)

        snr_pd_lin = (i_sig_rms * i_sig_rms) / np.maximum(i_shot_rms * i_shot_rms, 1e-30)
        snr_tia_in_lin = (i_sig_rms * i_sig_rms) / np.maximum(i_total_noise_rms * i_total_noise_rms, 1e-30)
        nf_tia_db = 10.0 * np.log10(np.maximum(snr_pd_lin / np.maximum(snr_tia_in_lin, 1e-30), 1e-30))

        g_tia_db = p["tia_gain_db"]
        g_tia_file = self._parse_touchstone_s21_db(self.inputs["tia_s2p_file"].get().strip(), target_hz)
        if g_tia_file is not None:
            g_tia_db = g_tia_file

        g_w_db = p["weight_gain_db"]
        g_w_file = self._parse_touchstone_s21_db(self.inputs["weight_s2p_file"].get().strip(), target_hz)
        if g_w_file is not None:
            g_w_db = g_w_file

        nf_w_db = np.abs(g_w_db) if g_w_db < 0 else p["weight_nf_db"]

        # Convert signal current RMS to equivalent stage powers.
        r_tia = np.maximum(p["tia_diff_transimp_ohm"], 1e-12)
        p_pd_in = (i_sig_rms * i_sig_rms) * r_tia
        p_tia_out = p_pd_in * (10 ** (g_tia_db / 10.0))
        p_w_out = p_tia_out * (10 ** (g_w_db / 10.0))

        snr_pd_db = 10.0 * np.log10(np.maximum(snr_pd_lin, 1e-30))
        snr_tia_out_db = 10.0 * np.log10(np.maximum(snr_tia_in_lin, 1e-30))
        snr_out_db = snr_tia_out_db - nf_w_db

        phase_error_deg = p["ampm_deg_per_db"] * np.abs(g_w_db)

        stage_power_dbm = {
            "PD input": float(self._w_to_dbm(p_pd_in)),
            "TIA output": float(self._w_to_dbm(p_tia_out)),
            "Weight output": float(self._w_to_dbm(p_w_out)),
        }
        stage_snr_db = {
            "PD": float(snr_pd_db),
            "TIA out": float(snr_tia_out_db),
            "Weight out": float(snr_out_db),
        }

        return {
            "p_pd_in": p_pd_in,
            "p_w_out": p_w_out,
            "snr_out_db": snr_out_db,
            "stage_power_dbm": stage_power_dbm,
            "stage_snr_db": stage_snr_db,
            "phase_error_deg": phase_error_deg,
            "g_tia_db": g_tia_db,
            "g_w_db": g_w_db,
            "nf_tia_db": nf_tia_db,
            "nf_w_db": nf_w_db,
            "i_photo": i_photo,
            "i_sig_rms": i_sig_rms,
            "i_shot_rms": i_shot_rms,
            "i_tia_rms": i_tia_rms,
            "i_total_noise_rms": i_total_noise_rms,
            "resp_scale": resp_scale,
            "bw_hz": bw_hz,
            "c_j": c_j,
            "tau_rc": tau_rc,
            "f_rc": f_rc,
            "tau_tr": tau_tr,
            "f_tr": f_tr,
        }

    def _qam_constellation(self, m_order):
        if m_order == 4:
            pts = np.array([-1 - 1j, -1 + 1j, 1 - 1j, 1 + 1j])
        else:
            pts = np.array(
                [
                    -3 - 3j,
                    -3 - 1j,
                    -3 + 1j,
                    -3 + 3j,
                    -1 - 3j,
                    -1 - 1j,
                    -1 + 1j,
                    -1 + 3j,
                    1 - 3j,
                    1 - 1j,
                    1 + 1j,
                    1 + 3j,
                    3 - 3j,
                    3 - 1j,
                    3 + 1j,
                    3 + 3j,
                ]
            )
        return pts / np.sqrt(np.mean(np.abs(pts) ** 2))

    def _simulate_dso_dsp_phase(self, p, cir, rng):
        fs = p["fs_ghz"] * 1e9
        f_if = p["if_freq_ghz"] * 1e9
        dur = p["duration_ns"] * 1e-9
        n_samples = max(2000, int(fs * dur))

        m_order = int(p["mod_order"])
        if m_order not in (4, 16):
            m_order = 4

        sps = 8
        n_symbols = max(200, min(p["num_symbols"], n_samples // sps))
        n_samples = n_symbols * sps
        t = np.arange(n_samples) / fs

        const = self._qam_constellation(m_order)
        tx_idx = rng.integers(0, len(const), n_symbols)
        tx_sym = const[tx_idx]

        i_up = np.repeat(np.real(tx_sym), sps)
        q_up = np.repeat(np.imag(tx_sym), sps)
        tx_bb = i_up + 1j * q_up

        tx_rf = np.real(tx_bb * np.exp(1j * 2.0 * pi * f_if * t))

        p_out_w = cir["p_w_out"]
        v_rms = np.sqrt(np.maximum(p_out_w, 1e-24) * np.maximum(p["tia_out_ohm"], 1e-12))
        v_pk = np.sqrt(2.0) * v_rms

        tx_rf_norm = tx_rf / np.sqrt(np.mean(tx_rf * tx_rf) + 1e-24)
        rx_sig = v_pk * tx_rf_norm

        snr_lin = 10 ** (cir["snr_out_db"] / 10.0)
        noise_var = np.var(rx_sig) / np.maximum(snr_lin, 1e-30)
        noise = np.sqrt(noise_var) * rng.standard_normal(n_samples)
        rx = rx_sig + noise

        i_mix = 2.0 * rx * np.cos(2.0 * pi * f_if * t)
        q_mix = -2.0 * rx * np.sin(2.0 * pi * f_if * t)

        kernel = np.ones(sps) / sps
        i_lp = np.convolve(i_mix, kernel, mode="same")
        q_lp = np.convolve(q_mix, kernel, mode="same")

        sample_idx = np.arange(sps // 2, n_samples, sps)
        rx_sym = i_lp[sample_idx] + 1j * q_lp[sample_idx]

        d = np.abs(rx_sym[:, None] - const[None, :])
        dec_idx = np.argmin(d, axis=1)

        evm = np.sqrt(np.mean(np.abs(rx_sym - tx_sym) ** 2) / np.mean(np.abs(tx_sym) ** 2))
        evm_db = 20.0 * np.log10(np.maximum(evm, 1e-12))
        ser = np.mean(dec_idx != tx_idx)

        bits_per_sym = int(np.log2(m_order))
        ber_est = ser / max(bits_per_sym / 2.0, 1.0)

        spec = np.fft.rfft(rx)
        freqs = np.fft.rfftfreq(len(rx), 1.0 / fs)
        spec_db = 20.0 * np.log10(np.maximum(np.abs(spec) / len(rx), 1e-12))

        return {
            "t": t,
            "rx": rx,
            "freqs": freqs,
            "spec_db": spec_db,
            "tx_sym": tx_sym,
            "rx_sym": rx_sym,
            "evm": evm,
            "evm_db": evm_db,
            "ser": ser,
            "ber_est": ber_est,
        }

    def _update_plots(self, p, opt, cir, dso):
        self.ax_opt_beam.clear()
        self.ax_opt_bars.clear()
        self.ax_opt_fill.clear()
        self.ax_opt_text.clear()

        z = np.linspace(0.0, p["distance_m"], 200)
        z_r = opt["z_r"]
        w0 = opt["w0"]
        wz = w0 * np.sqrt(1.0 + (z / z_r) ** 2)
        self.ax_opt_beam.plot(z, wz * 1e3, color="#1f77b4", lw=2.2, label="Beam radius")
        self.ax_opt_beam.axhline(0.5 * p["rx_lens_diam_mm"], color="#ff7f0e", lw=2.0, ls="--", label="Rx lens radius")
        self.ax_opt_beam.axhline(opt["w_l_user"] * 1e3, color="#8e24aa", lw=1.8, ls=":", label="Rx beam radius (user)")
        self.ax_opt_beam.set_title("Beam vs Rx Lens")
        self.ax_opt_beam.set_xlabel("Distance (m)")
        self.ax_opt_beam.set_ylabel("Radius (mm)")
        self.ax_opt_beam.grid(alpha=0.3)
        self.ax_opt_beam.legend(loc="upper left")

        p_cap_dbm = self._w_to_dbm(opt["p_cap"])
        p_after_optics_dbm = self._w_to_dbm(opt["p_after_optics"])
        p_pd_dbm = self._w_to_dbm(opt["p_rx_pd_w"])
        self.ax_opt_bars.bar(["Captured", "After Optics", "PD Realistic"], [p_cap_dbm, p_after_optics_dbm, p_pd_dbm], color=["#26a69a", "#5c6bc0", "#455a64"])
        self.ax_opt_bars.set_title("Optical Power Flow (Stage)")
        self.ax_opt_bars.set_ylabel("Power (dBm)")
        self.ax_opt_bars.grid(axis="y", alpha=0.3)

        self.ax_opt_fill.bar(["Lens capture", "A_PD / A_lens"], [opt["lens_capture"], opt["a_pd"] / np.maximum(opt["a_lens"], 1e-30)], color=["#8e24aa", "#6d4c41"])
        self.ax_opt_fill.set_ylim(0, 1.05)
        self.ax_opt_fill.set_title("Geometric Factors")
        self.ax_opt_fill.grid(axis="y", alpha=0.3)

        self.ax_opt_text.axis("off")
        txt = (
            f"Friis FSPL: {opt['fspl_db']:.2f} dB\n"
            f"Friis Rx (isotropic): {opt['rx_friis_dbm']:.2f} dBm\n"
            f"Rx total (path loss only): {self._w_to_dbm(opt['p_rx_pathloss_w']):.2f} dBm\n"
            f"Divergence half-angle: {opt['theta_half_rad']*1e3:.3f} mrad\n"
            f"Divergence full-angle: {opt['theta_full_rad']*1e3:.3f} mrad\n"
            f"P_cap = P_tx*(1-exp(-2*r^2/w^2)): {self._w_to_dbm(opt['p_cap']):.2f} dBm\n"
            f"After optics loss: {self._w_to_dbm(opt['p_after_optics']):.2f} dBm\n"
            f"PD realistic (coupling loss): {self._w_to_dbm(opt['p_rx_pd_w']):.2f} dBm\n"
            f"Beam radius at Rx: {opt['w_z']*1e3:.2f} mm\n"
            f"I(x_PD, y_PD) local: {opt['i_pd_local']:.3e} W/m^2\n"
            f"P_rx local ~= I(x_PD,y_PD)*A_PD: {self._w_to_dbm(opt['p_rx_pd_local']):.2f} dBm"
        )
        self.ax_opt_text.text(0.02, 0.95, txt, va="top", fontsize=10)
        self.fig_opt.tight_layout()
        self.canvas_opt.draw()

        self.ax_cir_power.clear()
        self.ax_cir_snr.clear()
        self.ax_cir_phase.clear()
        self.ax_cir_noise.clear()

        stage_names = list(cir["stage_power_dbm"].keys())
        stage_power = list(cir["stage_power_dbm"].values())
        stage_snr = list(cir["stage_snr_db"].values())

        self.ax_cir_power.plot(stage_names, stage_power, marker="o", lw=2.2, color="#00897b")
        self.ax_cir_power.set_title("Cascaded Signal Power")
        self.ax_cir_power.set_ylabel("Power (dBm)")
        self.ax_cir_power.grid(alpha=0.3)

        self.ax_cir_snr.plot(stage_names, stage_snr, marker="o", lw=2.2, color="#3949ab")
        self.ax_cir_snr.set_title("Cascaded SNR")
        self.ax_cir_snr.set_ylabel("SNR (dB)")
        self.ax_cir_snr.grid(alpha=0.3)

        self.ax_cir_phase.bar(["AM-to-PM"], [cir["phase_error_deg"]], color="#f57c00")
        self.ax_cir_phase.set_title("Weight Phase Error")
        self.ax_cir_phase.set_ylabel("deg")
        self.ax_cir_phase.grid(axis="y", alpha=0.25)

        self.ax_cir_noise.bar(
            ["I_signal_rms", "I_shot_rms", "I_TIA_rms", "I_noise_total_rms"],
            [cir["i_sig_rms"] * 1e6, cir["i_shot_rms"] * 1e6, cir["i_tia_rms"] * 1e6, cir["i_total_noise_rms"] * 1e6],
            color=["#2e7d32", "#ef6c00", "#6a1b9a", "#c62828"],
        )
        self.ax_cir_noise.set_title("Current Domain")
        self.ax_cir_noise.set_ylabel("uA")
        self.ax_cir_noise.grid(axis="y", alpha=0.25)

        self.fig_cir.tight_layout()
        self.canvas_cir.draw()

        self.ax_dso_time.clear()
        self.ax_dso_spec.clear()
        self.ax_dso_const.clear()
        self.ax_dso_metrics.clear()

        n_show = min(2500, len(dso["rx"]))
        self.ax_dso_time.plot(dso["t"][:n_show] * 1e9, dso["rx"][:n_show], color="#1565c0", lw=1.3)
        self.ax_dso_time.set_title("DSO Time Scope")
        self.ax_dso_time.set_xlabel("Time (ns)")
        self.ax_dso_time.set_ylabel("Voltage (V)")
        self.ax_dso_time.grid(alpha=0.3)

        f_lim = p["if_freq_ghz"] * 2.5
        mask = dso["freqs"] <= f_lim * 1e9
        self.ax_dso_spec.plot(dso["freqs"][mask] / 1e9, dso["spec_db"][mask], color="#d32f2f", lw=1.2)
        self.ax_dso_spec.set_title("Spectrum")
        self.ax_dso_spec.set_xlabel("Frequency (GHz)")
        self.ax_dso_spec.set_ylabel("Magnitude (dBV rel.)")
        self.ax_dso_spec.grid(alpha=0.3)

        self.ax_dso_const.scatter(np.real(dso["rx_sym"]), np.imag(dso["rx_sym"]), s=12, alpha=0.45, color="#2e7d32")
        self.ax_dso_const.scatter(np.real(dso["tx_sym"]), np.imag(dso["tx_sym"]), s=24, marker="x", color="#000000")
        self.ax_dso_const.set_title("Constellation (Tx vs Rx)")
        self.ax_dso_const.set_xlabel("I")
        self.ax_dso_const.set_ylabel("Q")
        self.ax_dso_const.set_aspect("equal", adjustable="box")
        self.ax_dso_const.grid(alpha=0.3)

        self.ax_dso_metrics.axis("off")
        metric_txt = (
            f"Output SNR: {cir['snr_out_db']:.2f} dB\n"
            f"EVM: {dso['evm_db']:.2f} dB\n"
            f"SER: {dso['ser']:.4e}\n"
            f"BER est.: {dso['ber_est']:.4e}"
        )
        self.ax_dso_metrics.text(0.03, 0.95, metric_txt, va="top", fontsize=10)

        self.fig_dso.tight_layout()
        self.canvas_dso.draw()

    def _update_results_table(self, opt, cir, dso):
        rows = [
            ("Divergence half-angle", f"{opt['theta_half_rad']*1e3:.3f}", "mrad"),
            ("Divergence full-angle", f"{opt['theta_full_rad']*1e3:.3f}", "mrad"),
            ("Rx total (path loss)", f"{self._w_to_dbm(opt['p_rx_pathloss_w']):.2f}", "dBm"),
            ("Captured by lens", f"{self._w_to_dbm(opt['p_cap']):.2f}", "dBm"),
            ("After optics loss", f"{self._w_to_dbm(opt['p_after_optics']):.2f}", "dBm"),
            ("Rx power at PD (real)", f"{self._w_to_dbm(opt['p_rx_pd_w']):.2f}", "dBm"),
            ("PD photocurrent (DC)", f"{cir['i_photo']*1e6:.3f}", "uA"),
            ("Signal current (RMS)", f"{cir['i_sig_rms']*1e6:.3f}", "uA"),
            ("PD junction Cj", f"{cir['c_j']*1e15:.3f}", "fF"),
            ("RC time constant", f"{cir['tau_rc']*1e12:.3f}", "ps"),
            ("RC-limited BW", f"{cir['f_rc']/1e9:.3f}", "GHz"),
            ("Transit time", f"{cir['tau_tr']*1e12:.3f}", "ps"),
            ("Transit-limited BW", f"{cir['f_tr']/1e9:.3f}", "GHz"),
            ("PD BW (combined)", f"{cir['bw_hz']/1e9:.3f}", "GHz"),
            ("TIA NF (computed)", f"{cir['nf_tia_db']:.2f}", "dB"),
            ("Weight NF (applied)", f"{cir['nf_w_db']:.2f}", "dB"),
            ("TIA gain (effective)", f"{cir['g_tia_db']:.2f}", "dB"),
            ("Weight gain (effective)", f"{cir['g_w_db']:.2f}", "dB"),
            ("Final RF power", f"{self._w_to_dbm(cir['p_w_out']):.2f}", "dBm"),
            ("Final SNR", f"{cir['snr_out_db']:.2f}", "dB"),
            ("DSP EVM", f"{dso['evm_db']:.2f}", "dB"),
        ]

        for item in self.tree.get_children():
            self.tree.delete(item)
        for row in rows:
            self.tree.insert("", tk.END, values=row)

    def _draw_triangle(self, x, y, size, outline="#0e3d5a", fill=""):
        pts = [x, y, x, y + size, x + size * 0.85, y + size * 0.5]
        self.schematic_canvas.create_polygon(pts, outline=outline, fill=fill, width=3)

    def _draw_schematic(self):
        if not hasattr(self, "schematic_canvas"):
            return

        cv = self.schematic_canvas
        cv.delete("all")

        w = max(cv.winfo_width(), 900)
        h = max(cv.winfo_height(), 600)

        cv.create_rectangle(0, 0, w, h, fill="#05080d", outline="")

        header = "[Optical Signal] -> PD -> TIA -> Analog Weight (VGA/VVA) -> DSO"
        cv.create_text(18, 20, anchor="nw", fill="#f2f2f2", font=("Segoe UI", 14, "bold"), text=header)

        y = h * 0.48
        tri_size = 70
        x_pd = 120
        x_tia = 310
        x_w = 510
        x_dso = 720

        self._draw_triangle(x_pd, y - tri_size * 0.5, tri_size, outline="#0b3f5f")
        self._draw_triangle(x_tia, y - tri_size * 0.5, tri_size, outline="#0b3f5f", fill="#e9edf2")
        self._draw_triangle(x_w, y - tri_size * 0.5, tri_size, outline="#0b3f5f", fill="#e9edf2")

        cv.create_line(x_tia + 8, y + tri_size * 0.38, x_tia + tri_size + 10, y - tri_size * 0.38, fill="#111111", width=4)
        cv.create_line(x_w + 8, y + tri_size * 0.38, x_w + tri_size + 10, y - tri_size * 0.38, fill="#111111", width=4)

        cv.create_line(x_pd + tri_size + 12, y, x_tia - 12, y, fill="#4a90a4", width=3, arrow=tk.LAST)
        cv.create_line(x_tia + tri_size + 12, y, x_w - 12, y, fill="#4a90a4", width=3, arrow=tk.LAST)

        dso_w = 170
        dso_h = 110
        cv.create_rectangle(x_dso, y - dso_h * 0.5, x_dso + dso_w, y + dso_h * 0.5, fill="#f0f0f0", outline="#0b3f5f", width=3)
        cv.create_text(x_dso + dso_w / 2, y, text="DSO\nDSP", fill="#121212", font=("Segoe UI", 24, "bold"))
        cv.create_line(x_w + tri_size + 12, y, x_dso - 12, y, fill="#4a90a4", width=3, arrow=tk.LAST)

        cv.create_text(16, h - 30, anchor="sw", fill="#98a9b3", font=("Segoe UI", 10), text="Single-channel chain. SNP files set frequency-dependent gain if provided.")

    def run_simulation(self):
        try:
            p = {
                "tx_power_dbm": self._get_float("tx_power_dbm"),
                "wavelength_nm": self._get_float("wavelength_nm"),
                "beam_waist_mm": self._get_float("beam_waist_mm"),
                "distance_m": self._get_float("distance_m"),
                "rx_beam_diam_mm": self._get_float("rx_beam_diam_mm"),
                "rx_lens_diam_mm": self._get_float("rx_lens_diam_mm"),
                "optical_loss_db": self._get_float("optical_loss_db"),
                "coupling_loss_db": self._get_float("coupling_loss_db"),
                "pd_diam_um": self._get_float("pd_diam_um"),
                "pd_x_mm": self._get_float("pd_x_mm"),
                "pd_y_mm": self._get_float("pd_y_mm"),
                "responsivity_aw": self._get_float("responsivity_aw"),
                "pd_eps_r": self._get_float("pd_eps_r"),
                "pd_depletion_um": self._get_float("pd_depletion_um"),
                "tia_rin_ohm": self._get_float("tia_rin_ohm"),
                "carrier_vsat_cm_s": self._get_float("carrier_vsat_cm_s"),
                "tia_gain_db": self._get_float("tia_gain_db"),
                "tia_diff_transimp_ohm": self._get_float("tia_diff_transimp_ohm"),
                "tia_in_noise_pa": self._get_float("tia_in_noise_pa"),
                "tia_out_ohm": self._get_float("tia_out_ohm"),
                "weight_gain_db": self._get_float("weight_gain_db"),
                "weight_nf_db": self._get_float("weight_nf_db"),
                "ampm_deg_per_db": self._get_float("ampm_deg_per_db"),
                "if_freq_ghz": self._get_float("if_freq_ghz"),
                "fs_ghz": self._get_float("fs_ghz"),
                "duration_ns": self._get_float("duration_ns"),
                "num_symbols": self._get_int("num_symbols"),
                "mod_order": self._get_int("mod_order"),
            }

            self.status_var.set("Status: Running Phase 1/2/3 simulation...")
            self.master.update_idletasks()

            opt = self._simulate_optical_phase(p)
            cir = self._simulate_circuit_phase(p, opt)

            # Fixed seed keeps EVM/spectrum stable across repeated runs with same inputs.
            rng = np.random.default_rng(20260403)
            dso = self._simulate_dso_dsp_phase(p, cir, rng)

            self._update_plots(p, opt, cir, dso)
            self._update_results_table(opt, cir, dso)
            self._draw_schematic()

            self.status_var.set("Status: Completed - Hybrid simulation and schematic updated")
        except Exception as exc:
            messagebox.showerror("Simulation Error", str(exc))
            self.status_var.set("Status: Error")


def main():
    root = tk.Tk()
    app = HybridFSOGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
