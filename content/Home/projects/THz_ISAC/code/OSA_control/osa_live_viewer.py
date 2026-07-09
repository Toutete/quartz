import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# Import the existing OSA control library functions
from osa_control import (
    resolve_sweep_config,
    open_osa,
    configure_osa,
    acquire_spectrum,
    wavelength_to_frequency_thz,
    center_frequency_from_wavelength,
    center_wavelength_from_frequency,
    C_LIGHT
)

class OSALiveViewerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.title("OSA Live Viewer")
        self.geometry("1100x700")
        
        self.style = ttk.Style(self)
        try:
            self.style.theme_use("clam")
        except Exception:
            pass
            
        self.configure(bg="#f4f6f9")
        
        # Connection Variables
        self.resource_var = tk.StringVar(value="GPIB0::1::INSTR")
        
        # Sweep Variables
        self.center_freq_var = tk.DoubleVar(value=193.4) # THz (approx 1550.1 nm)
        self.span_thz_var = tk.DoubleVar(value=0.5) # THz
        self.res_ghz_var = tk.DoubleVar(value=10.0) # GHz
        self.wait_s_var = tk.DoubleVar(value=10.0)
        
        self.is_acquiring = False
        
        self._build_ui()
        
    def _build_ui(self):
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Left Panel for Controls
        control_frame = ttk.Frame(main_frame, width=320)
        control_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        
        # --- Connection ---
        conn_group = ttk.LabelFrame(control_frame, text="Instrument Connection", padding=10)
        conn_group.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(conn_group, text="VISA Resource:").pack(anchor="w")
        ttk.Entry(conn_group, textvariable=self.resource_var).pack(fill=tk.X, pady=(0, 5))
        
        ttk.Button(conn_group, text="Test Connection", command=self.test_connection).pack(fill=tk.X)
        
        # --- Sweep Settings ---
        sweep_group = ttk.LabelFrame(control_frame, text="Sweep Settings", padding=10)
        sweep_group.pack(fill=tk.X, pady=(0, 10))
        
        # Center Frequency (THz)
        ttk.Label(sweep_group, text="Center Frequency (THz):").pack(anchor="w")
        freq_frame = ttk.Frame(sweep_group)
        freq_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Entry(freq_frame, textvariable=self.center_freq_var, width=15).pack(side=tk.LEFT)
        self.wl_hint_lbl = ttk.Label(freq_frame, text="(-- nm)", foreground="#64748b")
        self.wl_hint_lbl.pack(side=tk.LEFT, padx=5)
        self.center_freq_var.trace_add("write", self._update_wl_hint)
        self._update_wl_hint()
        
        # Span (THz)
        ttk.Label(sweep_group, text="Span (THz):").pack(anchor="w")
        ttk.Entry(sweep_group, textvariable=self.span_thz_var).pack(fill=tk.X, pady=(0, 5))
        
        # Resolution (GHz)
        ttk.Label(sweep_group, text="Resolution (GHz):").pack(anchor="w")
        ttk.Entry(sweep_group, textvariable=self.res_ghz_var).pack(fill=tk.X, pady=(0, 5))
        
        # Wait Time (s)
        ttk.Label(sweep_group, text="Sweep Wait Time (s):").pack(anchor="w")
        ttk.Entry(sweep_group, textvariable=self.wait_s_var).pack(fill=tk.X, pady=(0, 10))
        
        # Acquire Button
        self.btn_acquire = ttk.Button(control_frame, text="Acquire Spectrum", command=self.acquire_data)
        self.btn_acquire.pack(fill=tk.X, pady=(5, 0))
        
        # Save Button
        self.btn_save = ttk.Button(control_frame, text="Save Data (.csv & .png)", command=self.save_data, state=tk.DISABLED)
        self.btn_save.pack(fill=tk.X, pady=(5, 0))
        
        # Load Button
        self.btn_load = ttk.Button(control_frame, text="Load Data (.csv)", command=self.load_data)
        self.btn_load.pack(fill=tk.X, pady=(5, 10))
        
        # Right Panel for Plot
        plot_frame = ttk.Frame(main_frame)
        plot_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        self.fig, self.ax = plt.subplots(figsize=(8, 5))
        self.fig.patch.set_facecolor('#f4f6f9')
        self.ax.set_facecolor('#ffffff')
        
        self.canvas = FigureCanvasTkAgg(self.fig, master=plot_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        
        # Debug Console
        debug_frame = ttk.LabelFrame(self, text="Debug Console", padding=5)
        debug_frame.pack(side=tk.BOTTOM, fill=tk.BOTH, padx=10, pady=10, expand=False)
        self.debug_text = scrolledtext.ScrolledText(debug_frame, height=6, wrap=tk.WORD, font=("Consolas", 9))
        self.debug_text.pack(fill=tk.BOTH, expand=True)
        
        self._setup_blank_plot()

    def _update_wl_hint(self, *args):
        try:
            f_thz = float(self.center_freq_var.get())
            if f_thz > 0:
                wl_nm = center_wavelength_from_frequency(f_thz)
                self.wl_hint_lbl.config(text=f"({wl_nm:.2f} nm)")
            else:
                self.wl_hint_lbl.config(text="(-- nm)")
        except ValueError:
            self.wl_hint_lbl.config(text="(-- nm)")

    def _setup_blank_plot(self):
        self.ax.clear()
        self.ax.set_title("Optical Spectrum vs Frequency", fontsize=12, fontweight='bold', color="#1e293b")
        self.ax.set_xlabel("Frequency [THz]", fontsize=10)
        self.ax.set_ylabel("Power [dBm]", fontsize=10)
        self.ax.grid(True, alpha=0.35)
        self.fig.tight_layout()
        self.canvas.draw_idle()

    def test_connection(self):
        resource = self.resource_var.get().strip()
        
        def worker():
            try:
                rm, inst = open_osa(resource, timeout_ms=5000)
                idn = inst.query("*IDN?")
                inst.close()
                rm.close()
                self.after(0, lambda: messagebox.showinfo("Success", f"Connection OK!\nInstrument: {idn.strip()}"))
            except Exception as e:
                self.after(0, lambda m=str(e): messagebox.showerror("Connection Failed", f"Could not connect to {resource}:\n{m}"))
                
        threading.Thread(target=worker, daemon=True).start()
        
    def acquire_data(self):
        if self.is_acquiring:
            return
            
        try:
            center_freq_thz = float(self.center_freq_var.get())
            span_thz = float(self.span_thz_var.get())
            res_ghz = float(self.res_ghz_var.get())
            resource = self.resource_var.get()
        except ValueError:
            messagebox.showerror("Invalid Input", "Please enter valid numeric values for Frequency, Span, and Resolution.")
            return
            
        resource = self.resource_var.get().strip()
        
        self.is_acquiring = True
        self.btn_acquire.config(state=tk.DISABLED, text="Acquiring...")
        
        def worker():
            try:
                config = resolve_sweep_config(
                    center_frequency_thz=center_freq_thz,
                    span_ghz=span_thz * 1000.0,
                    resolution_ghz=res_ghz,
                    resource=resource,
                    trace="TRA",
                    single_sweep=True,
                    wait_s=self.wait_s_var.get(),
                    timeout_ms=60_000
                )
                self.after(0, lambda: self._log_debug(f"Config: Center={config.center_wavelength_nm:.2f}nm, Span={config.span_nm:.2f}nm, Res={config.resolution_nm:.3f}nm"))
                
                self.after(0, lambda: self._log_debug("Opening resource..."))
                rm, inst = open_osa(config.resource, timeout_ms=config.timeout_ms)
                try:
                    self.after(0, lambda: self._log_debug("Flushing buffer..."))
                    # 1. Flush any stale data left in the read buffer (e.g. leftover IDN strings)
                    inst.clear()
                    old_timeout = inst.timeout
                    inst.timeout = 200
                    flushed_lines = 0
                    for _ in range(10):
                        try:
                            res = inst.read()
                            flushed_lines += 1
                            if not res.strip():
                                break
                        except Exception:
                            break
                    inst.timeout = old_timeout
                    self.after(0, lambda: self._log_debug(f"Flushed {flushed_lines} lines."))
                    
                    self.after(0, lambda: self._log_debug("Configuring OSA for sweep..."))
                    configure_osa(inst, config)
                    
                    self.after(0, lambda: self._log_debug(f"Waiting {config.wait_s}s for sweep..."))
                    import time
                    time.sleep(config.wait_s)
                        
                    self.after(0, lambda: self._log_debug("Acquiring spectrum data..."))
                    wavelength_nm, power_dbm = acquire_spectrum(inst, config.trace)
                    
                    self.after(0, lambda: self._log_debug(f"Acquired {len(wavelength_nm)} points."))
                    self.after(0, lambda: self._log_debug(f"Parsed {len(wavelength_nm)} points."))
                    
                    n_pts = min(len(wavelength_nm), len(power_dbm))
                    wavelength_nm = wavelength_nm[:n_pts]
                    power_dbm = power_dbm[:n_pts]
                    
                    # Strictly filter out any garbage data (like the points count header e.g. 501, 10201)
                    center_wl = config.center_wavelength_nm
                    span = config.span_nm
                    valid_mask = (wavelength_nm >= center_wl - span - 5.0) & (wavelength_nm <= center_wl + span + 5.0)
                    
                    wavelength_nm = wavelength_nm[valid_mask]
                    power_dbm = power_dbm[valid_mask]
                    
                    if len(wavelength_nm) == 0:
                        raise ValueError(f"No valid data in the expected wavelength range.\nRaw X snippet: {x_raw[:40]}")
                        
                    self.after(0, lambda: self._log_debug("Data acquisition successful."))

                finally:
                    try:
                        inst.close()
                    except: pass
                    try:
                        rm.close()
                    except: pass
                    
                self.after(0, lambda w=wavelength_nm, p=power_dbm, c=center_freq_thz: self._plot_data(w, p, c))
                
            except Exception as e:
                self.after(0, lambda m=str(e): self._log_debug(f"ERROR: {m}"))
                self.after(0, lambda m=str(e): messagebox.showerror("Acquisition Failed", f"Error during acquisition:\n{m}"))
            finally:
                self.after(0, self._reset_acquire_btn)
                
        threading.Thread(target=worker, daemon=True).start()
        
    def _log_debug(self, msg):
        self.debug_text.insert(tk.END, msg + "\n")
        self.debug_text.see(tk.END)
        print(msg)

    def _reset_acquire_btn(self):
        self.is_acquiring = False
        self.btn_acquire.config(state=tk.NORMAL, text="Acquire Spectrum")
        
    def on_closing(self):
        import sys
        self.destroy()
        sys.exit(0)
        
    def _plot_data(self, wavelength_nm, power_dbm, target_center_freq_thz):
        self.ax.clear()
        
        if len(wavelength_nm) == 0 or len(power_dbm) == 0:
            messagebox.showwarning("No Data", "Received empty trace from OSA.")
            self._setup_blank_plot()
        # Convert Wavelength to Frequency
        freq_thz = wavelength_to_frequency_thz(wavelength_nm)
        
        # Filter out instrument's invalid data markers (-210 dBm)
        valid = power_dbm > -150
        freq_thz = freq_thz[valid]
        power_dbm = power_dbm[valid]
        wavelength_nm = wavelength_nm[valid]
        
        if len(freq_thz) == 0:
            messagebox.showwarning("No Data", "All received data points were invalid (-210 dBm floor).")
            self._setup_blank_plot()
            return
            
        # Store for saving
        self.last_freq_thz = freq_thz
        self.last_power_dbm = power_dbm
        self.last_wavelength_nm = wavelength_nm
        self.btn_save.config(state=tk.NORMAL)
        
        # Sort values ascending by frequency
        order = np.argsort(freq_thz)
        freq_thz = freq_thz[order]
        power_dbm = power_dbm[order]
        wavelength_nm = wavelength_nm[order]
        
        # Better plot styling for paper
        self.ax.plot(freq_thz, power_dbm, color="#1d4ed8", linewidth=1.5, alpha=0.9)
        self.ax.set_title("Optical Spectrum vs Frequency", fontsize=14, fontweight='bold', color="#1e293b", pad=15)
        self.ax.set_xlabel("Frequency [THz]", fontsize=11, fontweight='500')
        self.ax.set_ylabel("Power [dBm]", fontsize=11, fontweight='500')
        self.ax.grid(True, alpha=0.4, linestyle='--')
        
        # Automatically set Y limits to make noise floor look realistic
        ymax = np.max(power_dbm) + 5
        ymin = max(np.min(power_dbm) - 10, -100) # Floor at -100 if data goes lower
        self.ax.set_ylim(ymin, ymax)
        
        # Explicitly set X-axis limits based on the swept range
        span_thz_approx = float(self.span_thz_var.get())
        f_min = target_center_freq_thz - (span_thz_approx / 2) * 1.1
        f_max = target_center_freq_thz + (span_thz_approx / 2) * 1.1
            
        # Fallback to actual data bounds if approximation is way off
        if len(freq_thz) > 0:
            f_min = min(f_min, freq_thz.min() - 0.02)
            f_max = max(f_max, freq_thz.max() + 0.02)
            
        self.ax.set_xlim([f_min, f_max])
        
        # Add center marker
        self.ax.axvline(target_center_freq_thz, color="#dc2626", linestyle="--", linewidth=1.0, label=f"Center ({target_center_freq_thz:.3f} THz)")
        
        # Annotate Peak
        peak_idx = int(np.argmax(power_dbm))
        self.ax.annotate(
            f"Peak: {freq_thz[peak_idx]:.3f} THz\n{power_dbm[peak_idx]:.1f} dBm",
            xy=(freq_thz[peak_idx], power_dbm[peak_idx]),
            xytext=(10, 10),
            textcoords="offset points",
            fontsize=9,
            bbox=dict(boxstyle="round", facecolor="white", alpha=0.8, edgecolor="#94a3b8"),
        )
        
        self.ax.legend(loc="upper right")
        
        # Setup marker elements
        self.marker_anno = self.ax.annotate(
            "", xy=(0, 0), xytext=(10, 10),
            textcoords="offset points",
            fontsize=9,
            bbox=dict(boxstyle="round", facecolor="yellow", alpha=0.8, edgecolor="#d97706"),
            arrowprops=dict(arrowstyle="->", connectionstyle="arc3"),
            visible=False
        )
        self.marker_line = self.ax.axvline(x=0, color='#d97706', linestyle=':', visible=False)
        self.marker_point, = self.ax.plot([], [], marker='o', color='#d97706', visible=False)
        
        if hasattr(self, 'cid_click'):
            self.canvas.mpl_disconnect(self.cid_click)
        self.cid_click = self.canvas.mpl_connect('button_press_event', self.on_click_plot)
        
        # Add secondary axis for Wavelength
        try:
            self.ax.secondary_xaxis("top", functions=(
                lambda f: center_wavelength_from_frequency(f),
                lambda w: center_frequency_from_wavelength(w)
            )).set_xlabel("Wavelength [nm]", fontsize=10)
        except Exception:
            pass # Ignore warning if limits cross 0
            
        self.fig.tight_layout()
        self.canvas.draw_idle()
        
    def save_data(self):
        if not hasattr(self, 'last_freq_thz'):
            return
            
        from tkinter import filedialog
        from pathlib import Path
        import csv
        
        file_path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            title="Save Spectrum Data"
        )
        if not file_path:
            return
            
        try:
            # Save CSV
            with open(file_path, mode='w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(["Frequency [THz]", "Wavelength [nm]", "Power [dBm]"])
                for f_val, w_val, p_val in zip(self.last_freq_thz, self.last_wavelength_nm, self.last_power_dbm):
                    writer.writerow([f"{f_val:.6f}", f"{w_val:.6f}", f"{p_val:.2f}"])
            
            # Save Image
            png_path = str(Path(file_path).with_suffix(".png"))
            self.fig.savefig(png_path, dpi=300, bbox_inches='tight')
            
            self._log_debug(f"Data successfully saved to {file_path} and {png_path}")
            messagebox.showinfo("Saved", f"Data and plot saved successfully:\n{file_path}\n{png_path}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save data: {e}")

    def load_data(self):
        from tkinter import filedialog
        import csv
        
        file_path = filedialog.askopenfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            title="Load Spectrum Data"
        )
        if not file_path:
            return
            
        try:
            freqs, wls, powers = [], [], []
            with open(file_path, mode='r') as f:
                reader = csv.reader(f)
                header = next(reader, None) # skip header
                for row in reader:
                    if len(row) >= 3:
                        try:
                            f_val = float(row[0])
                            w_val = float(row[1])
                            p_val = float(row[2])
                            freqs.append(f_val)
                            wls.append(w_val)
                            powers.append(p_val)
                        except ValueError:
                            continue
            
            if not freqs:
                raise ValueError("No valid data found in the CSV.")
                
            freq_thz = np.array(freqs)
            wavelength_nm = np.array(wls)
            power_dbm = np.array(powers)
            
            # Infer center frequency and span roughly from the data range
            data_span = freq_thz.max() - freq_thz.min()
            center_freq = (freq_thz.min() + freq_thz.max()) / 2.0
            
            # Update GUI to reflect loaded data roughly
            self.center_freq_var.set(round(center_freq, 4))
            self.span_thz_var.set(round(data_span, 4))
            
            self._plot_data(wavelength_nm, power_dbm, center_freq)
            self._log_debug(f"Loaded data from {file_path}")
            messagebox.showinfo("Load Success", f"Loaded data from:\n{file_path}\n(Left click on graph to show marker, right click to clear)")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load data: {e}")
            self._log_debug(f"ERROR: {e}")

    def on_click_plot(self, event):
        if not event.inaxes == self.ax:
            return
        if not hasattr(self, 'last_freq_thz') or len(self.last_freq_thz) == 0:
            return
            
        # Left click to set marker, right click to clear
        if event.button == 3: # Right click
            self.marker_point.set_visible(False)
            self.marker_line.set_visible(False)
            self.marker_anno.set_visible(False)
            self.canvas.draw_idle()
            return
            
        x_click = event.xdata
        idx = np.argmin(np.abs(self.last_freq_thz - x_click))
        x_nearest = self.last_freq_thz[idx]
        y_nearest = self.last_power_dbm[idx]
        
        self.marker_point.set_data([x_nearest], [y_nearest])
        self.marker_point.set_visible(True)
        
        self.marker_line.set_xdata([x_nearest, x_nearest])
        self.marker_line.set_visible(True)
        
        self.marker_anno.xy = (x_nearest, y_nearest)
        self.marker_anno.set_text(f"{x_nearest:.3f} THz\n{y_nearest:.1f} dBm")
        self.marker_anno.set_visible(True)
        
        self.canvas.draw_idle()

if __name__ == "__main__":
    app = OSALiveViewerApp()
    app.mainloop()
