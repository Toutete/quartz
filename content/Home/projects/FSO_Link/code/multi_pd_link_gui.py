import csv
import os
import queue
import subprocess
import sys
import threading
import traceback
from pathlib import Path

import numpy as np
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import matplotlib

matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib.patches import Circle

from multi_pd_link import MultiPDConfig, run_multi_pd_link, w_to_dbm


HERE = Path(__file__).resolve().parent
EXTERNAL_FSO = HERE / "external" / "FSO-simulator"


class MultiPDLinkGUI:
    def __init__(self, master):
        self.master = master
        self.master.title("Multi-PD FSO Receiver Link GUI")
        self.master.geometry("1640x940")
        self.inputs = {}
        self.queue = queue.Queue()
        self.result = None
        self._busy = False

        self._build_layout()
        self._poll_queue()

    def _build_layout(self):
        self.side = ttk.Frame(self.master, padding=10, width=390)
        self.side.pack(side=tk.LEFT, fill=tk.Y)

        ttk.Label(
            self.side,
            text="Multi-PD FSO Receiver",
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor=tk.W)
        status = "connected" if (EXTERNAL_FSO / "fso_simulator.py").exists() else "not found"
        ttk.Label(
            self.side,
            text=f"Colleague FSO simulator: {status}",
            foreground=("green" if status == "connected" else "red"),
        ).pack(anchor=tk.W, pady=(2, 8))

        self.control_canvas = tk.Canvas(self.side, width=370, height=610, highlightthickness=0)
        self.control_scroll = ttk.Scrollbar(self.side, orient="vertical", command=self.control_canvas.yview)
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
            "SSFM turbulence",
            [
                ("distance_m", "Distance L (m)", "800"),
                ("cn2", "Cn2", "1e-15"),
                ("n_screens", "Phase screens", "5"),
                ("wind_speed_m_s", "Wind speed (m/s)", "15"),
                ("beam_waist_mm", "Beam waist w0 (mm)", "1.0"),
                ("grid_n", "Grid N", "128"),
                ("frames", "Frames", "32"),
                ("display_width_cm", "Plane width (cm)", "120"),
                ("tx_power_dbm", "Tx power (dBm)", "10"),
                ("seed", "Random seed", "42"),
            ],
        )
        self._add_group(
            "Photodetector array",
            [
                ("pd_rows", "PD rows", "2"),
                ("pd_cols", "PD columns", "4"),
                ("pd_spacing_mm", "PD spacing (mm)", "20"),
                ("lens_radius_mm", "Lens radius (mm)", "20"),
                ("pd_active_radius_um", "PD active radius (um)", "30"),
                ("focal_length_mm", "Focal length (mm)", "50"),
                ("fair_total_aperture", "Fixed total aperture? (0/1)", "0"),
            ],
        )
        self._add_group(
            "ADC and DSP",
            [
                ("responsivity_a_w", "Responsivity (A/W)", "0.9"),
                ("adc_bits", "ADC bits", "8"),
                ("adc_full_scale_ua", "ADC full-scale (uA)", "5"),
                ("samples_per_symbol", "Input samples/symbol", "8"),
                ("num_symbols", "Symbols", "1024"),
                ("modulation_order", "QAM order", "4"),
                ("modulation_depth", "IM/DD modulation depth", "0.35"),
                ("current_noise_na", "Current noise RMS (nA)", "5"),
                ("snr_ref_db", "Reference SNR (dB)", "25"),
                ("evm_floor_pct", "EVM floor (%)", "2"),
                ("outage_evm_pct", "Outage EVM threshold (%)", "20"),
                ("fade_outage_pct", "Fade outage target (%)", "1"),
            ],
        )

        btns = ttk.Frame(self.side)
        btns.pack(fill=tk.X, pady=(8, 4))
        self.run_btn = ttk.Button(btns, text="Run Multi-PD + ADC", command=self.run)
        self.run_btn.pack(fill=tk.X, ipady=4)
        ttk.Button(btns, text="Open Colleague Baseline GUI", command=self.open_external_gui).pack(fill=tk.X, pady=3)
        ttk.Button(btns, text="Export Metrics CSV", command=self.export_metrics).pack(fill=tk.X)

        self.progress = ttk.Progressbar(self.side, mode="indeterminate")
        self.progress.pack(fill=tk.X, pady=(8, 4))
        self.status = tk.StringVar(value="Ready")
        ttk.Label(self.side, textvariable=self.status, wraplength=360, foreground="blue").pack(anchor=tk.W)

        self.tree = ttk.Treeview(self.side, columns=("metric", "value"), show="headings", height=11)
        self.tree.heading("metric", text="Metric")
        self.tree.heading("value", text="Value")
        self.tree.column("metric", width=210)
        self.tree.column("value", width=130, anchor=tk.E)
        self.tree.pack(fill=tk.X, pady=(8, 0))

        self.notebook = ttk.Notebook(self.master)
        self.notebook.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        self.tab_plane = ttk.Frame(self.notebook)
        self.tab_adc = ttk.Frame(self.notebook)
        self.tab_metrics = ttk.Frame(self.notebook)
        self.tab_constellation = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_plane, text="Plane and PD Array")
        self.notebook.add(self.tab_adc, text="PD Current and ADC")
        self.notebook.add(self.tab_metrics, text="EVM / Outage / Fade Margin")
        self.notebook.add(self.tab_constellation, text="DSP Constellation")

        self.fig_plane = Figure(figsize=(10.8, 7.0), dpi=100)
        self.ax_plane = self.fig_plane.add_subplot(1, 2, 1)
        self.ax_heat = self.fig_plane.add_subplot(1, 2, 2)
        self.canvas_plane = FigureCanvasTkAgg(self.fig_plane, master=self.tab_plane)
        self.canvas_plane.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        self.fig_adc = Figure(figsize=(10.8, 7.0), dpi=100)
        self.ax_current = self.fig_adc.add_subplot(2, 1, 1)
        self.ax_codes = self.fig_adc.add_subplot(2, 1, 2)
        self.canvas_adc = FigureCanvasTkAgg(self.fig_adc, master=self.tab_adc)
        self.canvas_adc.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        self.fig_metrics = Figure(figsize=(10.8, 7.0), dpi=100)
        self.ax_evm = self.fig_metrics.add_subplot(2, 2, 1)
        self.ax_out = self.fig_metrics.add_subplot(2, 2, 2)
        self.ax_margin = self.fig_metrics.add_subplot(2, 2, 3)
        self.ax_power = self.fig_metrics.add_subplot(2, 2, 4)
        self.canvas_metrics = FigureCanvasTkAgg(self.fig_metrics, master=self.tab_metrics)
        self.canvas_metrics.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        self.fig_const = Figure(figsize=(10.8, 7.0), dpi=100)
        self.ax_single = self.fig_const.add_subplot(1, 2, 1)
        self.ax_mrc = self.fig_const.add_subplot(1, 2, 2)
        self.canvas_const = FigureCanvasTkAgg(self.fig_const, master=self.tab_constellation)
        self.canvas_const.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        self._draw_empty()

    def _add_group(self, title, rows):
        box = ttk.LabelFrame(self.control_frame, text=title, padding=8)
        box.pack(fill=tk.X, pady=5)
        for key, label, default in rows:
            row = ttk.Frame(box)
            row.pack(fill=tk.X, pady=2)
            ttk.Label(row, text=label, width=29).pack(side=tk.LEFT)
            ent = ttk.Entry(row, width=14)
            ent.insert(0, default)
            ent.pack(side=tk.RIGHT)
            self.inputs[key] = ent

    def _get_float(self, key):
        return float(self.inputs[key].get().strip())

    def _get_int(self, key):
        return int(float(self.inputs[key].get().strip()))

    def _config_from_inputs(self):
        return MultiPDConfig(
            distance_m=self._get_float("distance_m"),
            cn2=self._get_float("cn2"),
            n_screens=self._get_int("n_screens"),
            wind_speed_m_s=self._get_float("wind_speed_m_s"),
            beam_waist_m=self._get_float("beam_waist_mm") * 1e-3,
            grid_n=self._get_int("grid_n"),
            frames=self._get_int("frames"),
            display_width_m=self._get_float("display_width_cm") / 100.0,
            tx_power_dbm=self._get_float("tx_power_dbm"),
            seed=self._get_int("seed"),
            pd_rows=self._get_int("pd_rows"),
            pd_cols=self._get_int("pd_cols"),
            pd_spacing_m=self._get_float("pd_spacing_mm") * 1e-3,
            lens_radius_m=self._get_float("lens_radius_mm") * 1e-3,
            pd_active_radius_m=self._get_float("pd_active_radius_um") * 1e-6,
            focal_length_m=self._get_float("focal_length_mm") * 1e-3,
            fair_total_aperture=bool(self._get_int("fair_total_aperture")),
            responsivity_a_w=self._get_float("responsivity_a_w"),
            adc_bits=self._get_int("adc_bits"),
            adc_full_scale_a=self._get_float("adc_full_scale_ua") * 1e-6,
            samples_per_symbol=self._get_int("samples_per_symbol"),
            num_symbols=self._get_int("num_symbols"),
            modulation_order=self._get_int("modulation_order"),
            modulation_depth=self._get_float("modulation_depth"),
            current_noise_rms_a=self._get_float("current_noise_na") * 1e-9,
            snr_ref_db=self._get_float("snr_ref_db"),
            evm_floor_pct=self._get_float("evm_floor_pct"),
            outage_evm_pct=self._get_float("outage_evm_pct"),
            fade_outage_pct=self._get_float("fade_outage_pct"),
        )

    def _draw_empty(self):
        for ax in [
            self.ax_plane,
            self.ax_heat,
            self.ax_current,
            self.ax_codes,
            self.ax_evm,
            self.ax_out,
            self.ax_margin,
            self.ax_power,
            self.ax_single,
            self.ax_mrc,
        ]:
            ax.clear()
            ax.text(0.5, 0.5, "Run simulation", ha="center", va="center", transform=ax.transAxes)
        for fig, canvas in [
            (self.fig_plane, self.canvas_plane),
            (self.fig_adc, self.canvas_adc),
            (self.fig_metrics, self.canvas_metrics),
            (self.fig_const, self.canvas_const),
        ]:
            fig.tight_layout()
            canvas.draw()

    def run(self):
        if self._busy:
            return
        try:
            cfg = self._config_from_inputs()
        except Exception as exc:
            messagebox.showerror("Input error", str(exc))
            return
        self._busy = True
        self.run_btn.configure(state=tk.DISABLED)
        self.progress.start(12)
        self.status.set("Running SSFM turbulence, PD array, ADC, and DSP metrics...")

        def worker():
            try:
                self.queue.put(("result", run_multi_pd_link(cfg)))
            except Exception:
                self.queue.put(("error", traceback.format_exc()))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "result":
                    self.result = payload
                    self._busy = False
                    self.run_btn.configure(state=tk.NORMAL)
                    self.progress.stop()
                    self.status.set("Done")
                    self._update_all()
                elif kind == "error":
                    self._busy = False
                    self.run_btn.configure(state=tk.NORMAL)
                    self.progress.stop()
                    self.status.set("Error")
                    messagebox.showerror("Error", payload)
        except queue.Empty:
            pass
        self.master.after(120, self._poll_queue)

    def _update_all(self):
        self._update_summary()
        self._plot_plane()
        self._plot_adc()
        self._plot_metrics()
        self._plot_constellation()

    def _update_summary(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        r = self.result
        rows = [
            ("r0 total", f"{r['r0_total_m'] * 100:.2f} cm"),
            ("Rytov per screen", f"{r['rytov_dz']:.3e}"),
            ("Propagation", r["propagation_mode"]),
            ("Substeps/screen", str(r["substeps_per_screen"])),
            ("Alias metric", f"{r['alias_metric']:.3f}"),
        ]
        for name in ("Single center PD", "MRC", "Oracle"):
            m = r["metrics"][name]
            rows.append((f"{name} EVM mean", f"{m['mean_evm_pct']:.2f} %"))
            rows.append((f"{name} outage", f"{100*m['outage_probability']:.2f} %"))
        for k, v in rows:
            self.tree.insert("", tk.END, values=(k, v))

    def _plot_plane(self):
        r = self.result
        self.fig_plane.clear()
        self.ax_plane = self.fig_plane.add_subplot(1, 2, 1)
        self.ax_heat = self.fig_plane.add_subplot(1, 2, 2)
        fields = r["fields"]
        x = r["x_arr"] * 100.0
        power = r["power_w"]
        frame = fields.shape[2] // 2
        intensity = np.abs(fields[:, :, frame]) ** 2
        extent = [x[0], x[-1], x[0], x[-1]]

        self.ax_plane.clear()
        im = self.ax_plane.imshow(intensity, extent=extent, origin="lower", cmap="magma")
        for idx, (px, py) in enumerate(r["pd_positions"]):
            circ = Circle((px * 100.0, py * 100.0), r["cfg"].lens_radius_m * 100.0, fill=False, ec="cyan", lw=1.2)
            self.ax_plane.add_patch(circ)
            self.ax_plane.text(px * 100.0, py * 100.0, str(idx), color="white", ha="center", va="center", fontsize=8)
        self.ax_plane.set_title("Receiver Plane Intensity + PD Apertures")
        self.ax_plane.set_xlabel("x (cm)")
        self.ax_plane.set_ylabel("y (cm)")
        self.fig_plane.colorbar(im, ax=self.ax_plane, fraction=0.046, pad=0.04)

        self.ax_heat.clear()
        grid = np.mean(power, axis=1).reshape(r["cfg"].pd_rows, r["cfg"].pd_cols)
        hm = self.ax_heat.imshow(w_to_dbm(grid), cmap="viridis", origin="lower")
        self.ax_heat.set_title("Mean PD Optical Power (dBm)")
        for rr in range(r["cfg"].pd_rows):
            for cc in range(r["cfg"].pd_cols):
                self.ax_heat.text(cc, rr, f"{w_to_dbm(grid[rr, cc]):.1f}", ha="center", va="center", color="white", fontsize=9)
        self.ax_heat.set_xlabel("PD column")
        self.ax_heat.set_ylabel("PD row")
        self.fig_plane.colorbar(hm, ax=self.ax_heat, fraction=0.046, pad=0.04)
        self.fig_plane.tight_layout()
        self.canvas_plane.draw()

    def _plot_adc(self):
        r = self.result
        sig = r["signal"]
        n_plot = min(8, sig["current_a"].shape[0])
        t = np.arange(sig["current_a"].shape[1]) / max(r["cfg"].samples_per_symbol, 1)

        self.ax_current.clear()
        for i in range(n_plot):
            self.ax_current.plot(t, sig["current_a"][i] * 1e6, lw=1.0, label=f"PD{i}")
        self.ax_current.set_title("Per-PD Photocurrent Before ADC")
        self.ax_current.set_xlabel("Symbol index")
        self.ax_current.set_ylabel("Current (uA)")
        self.ax_current.grid(alpha=0.25)
        self.ax_current.legend(ncol=4, fontsize=8)

        self.ax_codes.clear()
        show = min(240, sig["adc_codes"].shape[1])
        for i in range(n_plot):
            self.ax_codes.step(np.arange(show), sig["adc_codes"][i, :show], where="mid", lw=1.0, label=f"PD{i}")
        self.ax_codes.set_title("ADC Output Codes")
        self.ax_codes.set_xlabel("ADC sample")
        self.ax_codes.set_ylabel("Code")
        self.ax_codes.grid(alpha=0.25)
        self.ax_codes.legend(ncol=4, fontsize=8)
        self.fig_adc.tight_layout()
        self.canvas_adc.draw()

    def _plot_metrics(self):
        r = self.result
        names = list(r["metrics"].keys())
        evm = [r["metrics"][n]["mean_evm_pct"] for n in names]
        out = [100.0 * r["metrics"][n]["outage_probability"] for n in names]
        margin = [r["metrics"][n]["required_fade_margin_db"] for n in names]
        power = [r["metrics"][n]["mean_rx_power_dbm"] for n in names]

        for ax, vals, title, ylabel in [
            (self.ax_evm, evm, "Mean EVM", "EVM (%)"),
            (self.ax_out, out, "Outage Probability", "P(EVM > threshold) (%)"),
            (self.ax_margin, margin, "Required Fade Margin", "dB"),
            (self.ax_power, power, "Average Received Power", "dBm"),
        ]:
            ax.clear()
            ax.bar(names, vals, color=["#607d8b", "#26a69a", "#42a5f5", "#7e57c2", "#ef5350"])
            ax.set_title(title)
            ax.set_ylabel(ylabel)
            ax.tick_params(axis="x", rotation=25)
            ax.grid(axis="y", alpha=0.25)
        self.fig_metrics.tight_layout()
        self.canvas_metrics.draw()

    def _plot_constellation(self):
        r = self.result
        sig = r["signal"]
        tx = sig["tx_symbols"]
        single = sig["rx_symbols"]["Single center PD"]
        mrc = sig["rx_symbols"]["MRC"]
        n = min(1200, len(tx))

        for ax, rx, title in [
            (self.ax_single, single, "Single Center PD DSP Output"),
            (self.ax_mrc, mrc, "MRC Multi-PD DSP Output"),
        ]:
            ax.clear()
            ax.scatter(np.real(rx[:n]), np.imag(rx[:n]), s=8, alpha=0.35, label="Rx")
            ax.scatter(np.real(tx[:n]), np.imag(tx[:n]), s=16, marker="x", color="black", label="Tx ideal")
            ax.set_aspect("equal", adjustable="box")
            ax.set_title(title)
            ax.set_xlabel("I")
            ax.set_ylabel("Q")
            ax.grid(alpha=0.25)
            ax.legend(loc="upper right")
        self.fig_const.tight_layout()
        self.canvas_const.draw()

    def export_metrics(self):
        if self.result is None:
            messagebox.showinfo("No result", "Run a simulation first.")
            return
        path = filedialog.asksaveasfilename(
            title="Save metrics CSV",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            initialfile="multi_pd_metrics.csv",
        )
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["method", "mean_evm_pct", "p95_evm_pct", "outage_probability", "required_fade_margin_db", "mean_rx_power_dbm", "mean_snr_db"])
            for name, m in self.result["metrics"].items():
                writer.writerow([
                    name,
                    m["mean_evm_pct"],
                    m["p95_evm_pct"],
                    m["outage_probability"],
                    m["required_fade_margin_db"],
                    m["mean_rx_power_dbm"],
                    m["mean_snr_db"],
                ])
        self.status.set(f"Saved metrics: {path}")

    def open_external_gui(self):
        gui = EXTERNAL_FSO / "fso_simulator_gui.py"
        if not gui.exists():
            messagebox.showerror("Missing simulator", f"Cannot find {gui}")
            return
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        subprocess.Popen([sys.executable, str(gui)], cwd=str(EXTERNAL_FSO), env=env)
        self.status.set("Opened colleague FSO baseline GUI.")


def main():
    root = tk.Tk()
    app = MultiPDLinkGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
