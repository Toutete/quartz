import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import pyvisa
import time
import threading
import serial
import math
import os
import csv
import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure


class MeasureApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Sub-THz Auto Measurement Tool")

        self.rm = pyvisa.ResourceManager()
        self.current_data = {"freq": [], "dbm": []}
        self.loaded_data = {"freq": [], "dbm": []}
        self._is_rf_on = False

        self.create_widgets()

    # ------------------------------------------------------------------ #
    #  UI Build                                                            #
    # ------------------------------------------------------------------ #

    def create_widgets(self):
        self.root.grid_columnconfigure(1, weight=3)
        self.root.grid_rowconfigure(1, weight=1)

        self._build_connection_frame()
        self._build_notebook()
        self._build_plot_frame()

    def _build_connection_frame(self):
        frame_conn = ttk.LabelFrame(self.root, text="Instrument Connections")
        frame_conn.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="ew")

        # SHF
        frame_shf = ttk.LabelFrame(frame_conn, text="SHF 78120B (Signal Generator)")
        frame_shf.grid(row=0, column=0, padx=8, pady=5, sticky="ew")

        ttk.Label(frame_shf, text="Address (COMx / VISA):").grid(row=0, column=0, padx=5, pady=4, sticky="e")
        self.entry_shf_addr = ttk.Entry(frame_shf, width=20)
        self.entry_shf_addr.insert(0, "COM8")
        self.entry_shf_addr.grid(row=0, column=1, padx=5, pady=4)

        ttk.Label(frame_shf, text="Baud:").grid(row=0, column=2, padx=5, pady=4, sticky="e")
        self.entry_shf_baud = ttk.Entry(frame_shf, width=8)
        self.entry_shf_baud.insert(0, "9600")
        self.entry_shf_baud.grid(row=0, column=3, padx=5, pady=4)

        self.btn_shf_connect = ttk.Button(frame_shf, text="Connect", command=self.start_shf_check_thread)
        self.btn_shf_connect.grid(row=0, column=4, padx=8, pady=4)

        self.lbl_shf_status = ttk.Label(frame_shf, text="● Disconnected", foreground="red")
        self.lbl_shf_status.grid(row=0, column=5, padx=5, pady=4)

        # PM5B
        frame_pm5b = ttk.LabelFrame(frame_conn, text="VDI PM5B (Power Meter)")
        frame_pm5b.grid(row=0, column=1, padx=8, pady=5, sticky="ew")

        ttk.Label(frame_pm5b, text="COM Port:").grid(row=0, column=0, padx=5, pady=4, sticky="e")
        self.entry_pm5b_port = ttk.Entry(frame_pm5b, width=10)
        self.entry_pm5b_port.insert(0, "COM4")
        self.entry_pm5b_port.grid(row=0, column=1, padx=5, pady=4)

        self.btn_pm5b_connect = ttk.Button(frame_pm5b, text="Connect", command=self.start_pm5b_check_thread)
        self.btn_pm5b_connect.grid(row=0, column=2, padx=8, pady=4)

        self.lbl_pm5b_status = ttk.Label(frame_pm5b, text="● Disconnected", foreground="red")
        self.lbl_pm5b_status.grid(row=0, column=3, padx=5, pady=4)

        self.btn_pm5b_zero = ttk.Button(frame_pm5b, text="PM5B Zeroing", command=self.start_pm5b_zero_thread)
        self.btn_pm5b_zero.grid(row=0, column=4, padx=8, pady=4)

        ttk.Label(frame_conn, text="* AUTO 입력 시 SHF를 VISA 리소스에서 자동 탐색",
                  foreground="gray").grid(row=1, column=0, columnspan=2, padx=8, pady=(0, 4), sticky="w")

    def _build_notebook(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.grid(row=1, column=0, padx=10, pady=5, sticky="nsew")

        tab_sig = ttk.Frame(self.notebook)
        self.notebook.add(tab_sig, text="  Signal Generator  ")
        self._build_siggen_tab(tab_sig)

        tab_sweep = ttk.Frame(self.notebook)
        self.notebook.add(tab_sweep, text="  Power Sweep Measurement  ")
        self._build_sweep_tab(tab_sweep)

    def _build_siggen_tab(self, parent):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True, padx=20, pady=20)

        # --- Frequency ---
        ttk.Label(frame, text="Frequency (GHz):", font=("Arial", 11)).grid(
            row=0, column=0, padx=10, pady=12, sticky="e")
        self.entry_siggen_freq = ttk.Entry(frame, width=16, font=("Arial", 11))
        self.entry_siggen_freq.insert(0, "18.333333")
        self.entry_siggen_freq.grid(row=0, column=1, padx=5, pady=12)
        self.btn_set_freq = ttk.Button(frame, text="Set Freq", width=10,
                                       command=self.action_set_shf_freq)
        self.btn_set_freq.grid(row=0, column=2, padx=8, pady=12)
        self.lbl_applied_freq = ttk.Label(frame, text="Applied: --", foreground="gray", width=24)
        self.lbl_applied_freq.grid(row=0, column=3, padx=5, pady=12, sticky="w")

        # --- Power ---
        ttk.Label(frame, text="Output Power (dBm):", font=("Arial", 11)).grid(
            row=1, column=0, padx=10, pady=12, sticky="e")
        self.entry_shf_power = ttk.Entry(frame, width=16, font=("Arial", 11))
        self.entry_shf_power.insert(0, "0.0")
        self.entry_shf_power.grid(row=1, column=1, padx=5, pady=12)
        self.btn_set_power = ttk.Button(frame, text="Set Power", width=10,
                                        command=self.action_set_shf_power)
        self.btn_set_power.grid(row=1, column=2, padx=8, pady=12)
        self.lbl_applied_power = ttk.Label(frame, text="Applied: --", foreground="gray", width=24)
        self.lbl_applied_power.grid(row=1, column=3, padx=5, pady=12, sticky="w")

        # --- RF Toggle ---
        ttk.Separator(frame, orient="horizontal").grid(
            row=2, column=0, columnspan=4, sticky="ew", pady=8)

        self.btn_shf_rf_toggle = ttk.Button(frame, text="RF  ON / OFF  Toggle",
                                             width=22, command=self.toggle_shf_rf)
        self.btn_shf_rf_toggle.grid(row=3, column=0, columnspan=2, padx=10, pady=12, sticky="w")

        self.lbl_rf_led = tk.Label(frame, text="⚫ OFF", fg="gray", font=("Arial", 14, "bold"))
        self.lbl_rf_led.grid(row=3, column=2, columnspan=2, padx=10, pady=12, sticky="w")

    def _build_sweep_tab(self, parent):
        # --- Parameters ---
        frame_params = ttk.LabelFrame(parent, text="Measurement Parameters")
        frame_params.pack(fill="x", padx=10, pady=10)

        ttk.Label(frame_params, text="SGX Start Freq (GHz):").grid(
            row=0, column=0, padx=8, pady=5, sticky="e")
        self.entry_sgx_start = ttk.Entry(frame_params, width=12)
        self.entry_sgx_start.insert(0, "220.0")
        self.entry_sgx_start.grid(row=0, column=1, padx=5, pady=5, sticky="w")
        self.entry_sgx_start.bind("<KeyRelease>", self._update_shf_freq_display)

        ttk.Label(frame_params, text="→ SHF:").grid(row=0, column=2, padx=2, sticky="e")
        self.lbl_shf_start = ttk.Label(frame_params, text="18.333333 GHz",
                                        foreground="blue", width=18)
        self.lbl_shf_start.grid(row=0, column=3, padx=5, pady=5, sticky="w")

        ttk.Label(frame_params, text="SGX Stop Freq (GHz):").grid(
            row=1, column=0, padx=8, pady=5, sticky="e")
        self.entry_sgx_stop = ttk.Entry(frame_params, width=12)
        self.entry_sgx_stop.insert(0, "320.0")
        self.entry_sgx_stop.grid(row=1, column=1, padx=5, pady=5, sticky="w")
        self.entry_sgx_stop.bind("<KeyRelease>", self._update_shf_freq_display)

        ttk.Label(frame_params, text="→ SHF:").grid(row=1, column=2, padx=2, sticky="e")
        self.lbl_shf_stop = ttk.Label(frame_params, text="26.666667 GHz",
                                       foreground="blue", width=18)
        self.lbl_shf_stop.grid(row=1, column=3, padx=5, pady=5, sticky="w")

        ttk.Label(frame_params, text="Number of Points:").grid(
            row=2, column=0, padx=8, pady=5, sticky="e")
        self.entry_num_points = ttk.Entry(frame_params, width=12)
        self.entry_num_points.insert(0, "11")
        self.entry_num_points.grid(row=2, column=1, padx=5, pady=5, sticky="w")

        ttk.Label(frame_params, text="(SHF freq = SGX / 12)", foreground="gray").grid(
            row=2, column=2, columnspan=2, padx=5, pady=5, sticky="w")

        ttk.Label(frame_params, text="PM5B Scale:").grid(
            row=3, column=0, padx=8, pady=5, sticky="e")
        frame_scale = ttk.Frame(frame_params)
        frame_scale.grid(row=3, column=1, columnspan=3, padx=5, pady=5, sticky="w")
        self.combo_pm5b_range = ttk.Combobox(
            frame_scale, values=["200 uW", "2 mW", "20 mW", "200 mW"], width=10, state="readonly")
        self.combo_pm5b_range.current(1)
        self.combo_pm5b_range.pack(side="left")
        self.combo_pm5b_range.bind("<<ComboboxSelected>>", self.on_scale_changed)
        self.btn_set_scale = ttk.Button(frame_scale, text="Set", width=4,
                                        command=self.action_set_pm5b_scale)
        self.btn_set_scale.pack(side="left", padx=2)
        self.lbl_applied_scale = ttk.Label(frame_scale, text="(Applied: Unknown)", foreground="gray")
        self.lbl_applied_scale.pack(side="left", padx=2)

        ttk.Label(frame_params, text="Settling Time (sec):").grid(
            row=4, column=0, padx=8, pady=5, sticky="e")
        self.entry_delay = ttk.Entry(frame_params, width=12)
        self.entry_delay.insert(0, "5.0")
        self.entry_delay.grid(row=4, column=1, padx=5, pady=5, sticky="w")

        # --- Controls ---
        frame_ctrl = ttk.Frame(parent)
        frame_ctrl.pack(fill="x", padx=10, pady=5)

        self.btn_run = ttk.Button(frame_ctrl, text="RUN MEASUREMENT",
                                  command=self.start_measurement_thread)
        self.btn_run.grid(row=0, column=0, padx=5, pady=5)

        self.btn_stop = ttk.Button(frame_ctrl, text="STOP",
                                   command=self.stop_measurement, state="disabled")
        self.btn_stop.grid(row=0, column=1, padx=5, pady=5)

        self.lbl_status = ttk.Label(frame_ctrl, text="Ready", foreground="blue")
        self.lbl_status.grid(row=0, column=2, padx=12, pady=5)

        ttk.Label(frame_ctrl, text="Latest:").grid(row=0, column=3, padx=5, pady=5)
        self.lbl_result = ttk.Label(frame_ctrl, text="-- / --",
                                    font=("Arial", 12, "bold"), foreground="red")
        self.lbl_result.grid(row=0, column=4, padx=5, pady=5)

        # --- Results Table ---
        frame_table = ttk.LabelFrame(parent, text="PM5 Measurement Table")
        frame_table.pack(fill="both", expand=True, padx=10, pady=5)

        self.tree_results = ttk.Treeview(
            frame_table,
            columns=("idx", "sgx", "shf", "mw", "dbm"),
            show="headings",
            height=10,
        )
        self.tree_results.heading("idx", text="#")
        self.tree_results.heading("sgx", text="SGX Out Freq (GHz)")
        self.tree_results.heading("shf", text="SHF SigGen Freq (GHz)")
        self.tree_results.heading("mw", text="PM5 Power (mW)")
        self.tree_results.heading("dbm", text="PM5 Power (dBm)")
        self.tree_results.column("idx", width=40, anchor="center")
        self.tree_results.column("sgx", width=140, anchor="center")
        self.tree_results.column("shf", width=160, anchor="center")
        self.tree_results.column("mw", width=120, anchor="center")
        self.tree_results.column("dbm", width=120, anchor="center")
        self.tree_results.pack(fill="both", expand=True, padx=5, pady=5)

    def _build_plot_frame(self):
        frame_plot = ttk.Frame(self.root)
        frame_plot.grid(row=0, column=1, rowspan=2, padx=10, pady=10, sticky="nsew")

        frame_data_ops = ttk.Frame(frame_plot)
        frame_data_ops.pack(side=tk.TOP, fill=tk.X, pady=5)

        ttk.Label(frame_data_ops, text="Save Name:").pack(side=tk.LEFT, padx=5)
        self.entry_save_name = ttk.Entry(frame_data_ops, width=15)
        self.entry_save_name.insert(0, "meas_data")
        self.entry_save_name.pack(side=tk.LEFT, padx=5)

        ttk.Button(frame_data_ops, text="Save Data", command=self.save_data).pack(
            side=tk.LEFT, padx=5)
        ttk.Button(frame_data_ops, text="Load Data (Thru)", command=self.load_data).pack(
            side=tk.LEFT, padx=5)

        self.var_cal = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame_data_ops, text="Apply Calibration",
                        variable=self.var_cal, command=self.update_plot).pack(side=tk.LEFT, padx=5)

        self.lbl_loaded_file = ttk.Label(frame_data_ops, text="Loaded: None", foreground="blue")
        self.lbl_loaded_file.pack(side=tk.LEFT, padx=5)

        self.fig = Figure(figsize=(6, 5), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_title("Power vs Frequency")
        self.ax.set_xlabel("Frequency (GHz)")
        self.ax.set_ylabel("Power (dBm)")
        self.ax.grid(True)

        self.canvas = FigureCanvasTkAgg(self.fig, master=frame_plot)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(side=tk.BOTTOM, fill=tk.BOTH, expand=True)

    # ------------------------------------------------------------------ #
    #  Live freq label update                                             #
    # ------------------------------------------------------------------ #

    def _update_shf_freq_display(self, *_):
        try:
            self.lbl_shf_start.config(text=f"{float(self.entry_sgx_start.get()) / 12:.6f} GHz")
        except ValueError:
            self.lbl_shf_start.config(text="--")
        try:
            self.lbl_shf_stop.config(text=f"{float(self.entry_sgx_stop.get()) / 12:.6f} GHz")
        except ValueError:
            self.lbl_shf_stop.config(text="--")

    # ------------------------------------------------------------------ #
    #  Connection — SHF (independent)                                     #
    # ------------------------------------------------------------------ #

    def start_shf_check_thread(self):
        self.btn_shf_connect.config(state="disabled")
        self.lbl_shf_status.config(text="● Checking...", foreground="orange")
        t = threading.Thread(target=self.check_shf_connection)
        t.daemon = True
        t.start()

    def check_shf_connection(self):
        try:
            shf_inst = self._open_shf_inst(timeout=3000)
            try:
                response = shf_inst.query("CLKSRC:FREQUENCY=?;")
            except Exception:
                response = "No response"
            try:
                is_on = self._read_shf_rf_state(shf_inst)
                if is_on is not None:
                    self.root.after(0, lambda on=is_on: self.update_rf_led(on))
            except Exception:
                pass
            self.root.after(0, lambda: self.lbl_shf_status.config(
                text="● Connected", foreground="green"))
            self.root.after(0, lambda r=response: messagebox.showinfo(
                "SHF Connection", f"SHF 78120B Connected\nResponse: {r}"))
            shf_inst.close()
        except Exception as e:
            self.root.after(0, lambda: self.lbl_shf_status.config(
                text="● Disconnected", foreground="red"))
            self.root.after(0, lambda err=e: messagebox.showerror(
                "SHF Connection Error", f"SHF 78120B 연결 실패:\n{err}"))
        finally:
            self.root.after(0, lambda: self.btn_shf_connect.config(state="normal"))

    # ------------------------------------------------------------------ #
    #  Connection — PM5B (independent)                                    #
    # ------------------------------------------------------------------ #

    def start_pm5b_check_thread(self):
        self.btn_pm5b_connect.config(state="disabled")
        self.lbl_pm5b_status.config(text="● Checking...", foreground="orange")
        t = threading.Thread(target=self.check_pm5b_connection)
        t.daemon = True
        t.start()

    def check_pm5b_connection(self):
        try:
            pm5b_port = self.normalize_com_port(self.entry_pm5b_port.get())
            pm5b_inst, baud, used_cmd, _ = self.open_pm5b_serial(pm5b_port, timeout_sec=2.0)
            range_str = self.combo_pm5b_range.get()
            ind_rng = {"200 uW": 1, "2 mW": 2, "20 mW": 3, "200 mW": 4}.get(range_str, 3)
            self.set_pm5b_range(pm5b_inst, ind_rng)
            self.root.after(0, lambda: self.lbl_pm5b_status.config(
                text="● Connected", foreground="green"))
            self.root.after(0, lambda p=pm5b_port, b=baud, c=used_cmd: messagebox.showinfo(
                "PM5B Connection",
                f"VDI PM5B Connected\nPort: {p}\nBaud: {b}\nCommand: {c}\nRange: {range_str}"))
            if pm5b_inst and pm5b_inst.is_open:
                pm5b_inst.close()
        except Exception as e:
            self.root.after(0, lambda: self.lbl_pm5b_status.config(
                text="● Disconnected", foreground="red"))
            self.root.after(0, lambda err=e: messagebox.showerror(
                "PM5B Connection Error", f"VDI PM5B 연결 실패:\n{err}"))
        finally:
            self.root.after(0, lambda: self.btn_pm5b_connect.config(state="normal"))

    # ------------------------------------------------------------------ #
    #  SigGen actions                                                      #
    # ------------------------------------------------------------------ #

    def action_set_shf_freq(self):
        t = threading.Thread(target=self._routine_set_shf_freq)
        t.daemon = True
        t.start()

    def _routine_set_shf_freq(self):
        shf_inst = None
        try:
            self.root.after(0, lambda: self.btn_set_freq.config(state="disabled"))
            shf_inst = self._open_shf_inst(timeout=2000)
            freq_ghz = float(self.entry_siggen_freq.get())
            freq_hz = int(freq_ghz * 1e9)
            self._shf_send_cmd(shf_inst, f"CLKSRC:FREQUENCY={freq_hz};")
            time.sleep(0.1)
            try:
                import re
                resp = self._shf_query_cmd(shf_inst, "CLKSRC:FREQUENCY=?;", local_timeout=500)
                m = re.search(r"[-+]?[0-9]*\.?[0-9]+", resp)
                applied_str = f"{float(m.group(0)) / 1e9:.6f} GHz" if m else f"{freq_ghz:.6f} GHz"
            except Exception:
                applied_str = f"{freq_ghz:.6f} GHz"
            self.root.after(0, lambda ap=applied_str: self.lbl_applied_freq.config(
                text=f"Applied: {ap}", foreground="blue"))
        except Exception as e:
            self.root.after(0, lambda err=e: messagebox.showerror("SHF Freq Set Error", str(err)))
        finally:
            if shf_inst:
                try:
                    shf_inst.close()
                except Exception:
                    pass
            self.root.after(0, lambda: self.btn_set_freq.config(state="normal"))

    def action_set_shf_power(self):
        t = threading.Thread(target=self._routine_set_shf_power)
        t.daemon = True
        t.start()

    def _routine_set_shf_power(self):
        shf_inst = None
        try:
            self.root.after(0, lambda: self.btn_set_power.config(state="disabled"))
            shf_inst = self._open_shf_inst(timeout=2000)
            power = float(self.entry_shf_power.get())
            self._shf_send_cmd(shf_inst, f"CLKSRC:AMPLITUDE={power};")
            time.sleep(0.1)
            try:
                import re
                resp = shf_inst.query("CLKSRC:AMPLITUDE=?;").strip()
                if "=" in resp:
                    resp = resp.split("=")[-1].strip(";")
                m = re.search(r"[-+]?[0-9]*\.?[0-9]+", resp)
                applied_str = f"{float(m.group(0)):.1f} dBm" if m else f"{power:.1f} dBm"
            except Exception:
                applied_str = f"{power:.1f} dBm"
            self.root.after(0, lambda ap=applied_str: self.lbl_applied_power.config(
                text=f"Applied: {ap}", foreground="blue"))
        except Exception as e:
            self.root.after(0, lambda err=e: messagebox.showerror("SHF Power Set Error", str(err)))
        finally:
            if shf_inst:
                try:
                    shf_inst.close()
                except Exception:
                    pass
            self.root.after(0, lambda: self.btn_set_power.config(state="normal"))

    def toggle_shf_rf(self):
        t = threading.Thread(target=self._routine_toggle_shf_rf)
        t.daemon = True
        t.start()

    def _routine_toggle_shf_rf(self):
        shf_inst = None
        try:
            self.root.after(0, lambda: self.btn_shf_rf_toggle.config(state="disabled"))
            shf_inst = self._open_shf_inst(timeout=3000)
            new_state = not getattr(self, "_is_rf_on", False)
            power = float(self.entry_shf_power.get()) if new_state else None
            self._set_shf_state_robust(shf_inst, new_state, power)
            self.root.after(0, lambda on=new_state: self.update_rf_led(on))
        except Exception as e:
            self.root.after(0, lambda err=e: messagebox.showerror("SHF Control Error", str(err)))
        finally:
            if shf_inst:
                time.sleep(0.5)
                try:
                    shf_inst.close()
                except Exception:
                    pass
            self.root.after(0, lambda: self.btn_shf_rf_toggle.config(state="normal"))

    # ------------------------------------------------------------------ #
    #  PM5B zeroing                                                        #
    # ------------------------------------------------------------------ #

    def start_pm5b_zero_thread(self):
        self.btn_pm5b_zero.config(state="disabled")
        self.lbl_status.config(text="PM5B Zeroing...", foreground="orange")
        t = threading.Thread(target=self.pm5b_zero_routine)
        t.daemon = True
        t.start()

    def pm5b_zero_routine(self):
        pm5b_inst = None
        shf_inst = None
        try:
            pm5b_port = self.normalize_com_port(self.entry_pm5b_port.get())
            try:
                shf_inst = self._open_shf_inst(timeout=3000)
                self._set_shf_state_robust(shf_inst, False)
                self.root.after(0, lambda: self.update_rf_led(False))
            except Exception:
                shf_inst = None

            time.sleep(20.0)

            pm5b_inst, baud, _, _ = self.open_pm5b_serial(pm5b_port, timeout_sec=3.0)
            range_str = self.combo_pm5b_range.get()
            ind_rng = {"200 uW": 1, "2 mW": 2, "20 mW": 3, "200 mW": 4}.get(range_str, 3)
            self.set_pm5b_range(pm5b_inst, ind_rng)
            used_cmd, probe = self.zero_pm5b_binary(pm5b_inst)

            self.root.after(0, lambda p=pm5b_port, b=baud, c=used_cmd, pr=probe: messagebox.showinfo(
                "PM5B Zeroing",
                f"PM5B Zeroing 완료\nPort: {p}\nBaud: {b}\nCmd: {c}\nProbe: {pr}"))
        except Exception as e:
            self.root.after(0, lambda err=e: messagebox.showerror("PM5B Zeroing Error", str(err)))
        finally:
            for inst in (shf_inst, pm5b_inst):
                if inst:
                    try:
                        inst.close()
                    except Exception:
                        pass
            self.root.after(0, lambda: self.btn_pm5b_zero.config(state="normal"))
            self.root.after(0, lambda: self.lbl_status.config(text="Ready", foreground="blue"))

    # ------------------------------------------------------------------ #
    #  Sweep measurement                                                   #
    # ------------------------------------------------------------------ #

    def start_measurement_thread(self):
        self._stop_flag = False
        self.btn_run.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.btn_pm5b_zero.config(state="disabled")
        self.lbl_status.config(text="Measuring...", foreground="orange")
        self.lbl_result.config(text="-- / --")
        self.clear_results_table()
        t = threading.Thread(target=self.measurement_routine)
        t.daemon = True
        t.start()

    def stop_measurement(self):
        self._stop_flag = True
        self.btn_stop.config(state="disabled")
        self.lbl_status.config(text="Stopping...", foreground="red")

    def measurement_routine(self):
        shf_inst = None
        pm5b_inst = None
        try:
            pm5b_port = self.normalize_com_port(self.entry_pm5b_port.get())
            sgx_start = float(self.entry_sgx_start.get())
            sgx_stop = float(self.entry_sgx_stop.get())
            num_points = int(self.entry_num_points.get())
            delay_sec = float(self.entry_delay.get())

            if num_points <= 0:
                raise ValueError("Number of Points는 1 이상이어야 합니다.")
            if sgx_stop < sgx_start:
                raise ValueError("SGX Stop Freq는 Start Freq보다 크거나 같아야 합니다.")
            if delay_sec < 0:
                raise ValueError("Settling Time은 0 이상이어야 합니다.")

            if num_points == 1:
                sgx_freqs = [sgx_start]
            else:
                step = (sgx_stop - sgx_start) / (num_points - 1)
                sgx_freqs = [sgx_start + i * step for i in range(num_points)]

            self.current_data = {"freq": [], "dbm": []}
            self.root.after(0, self.update_plot)

            shf_inst = self._open_shf_inst(timeout=5000)
            shf_power = float(self.entry_shf_power.get())
            self._set_shf_state_robust(shf_inst, True, shf_power)
            self.root.after(0, lambda: self.update_rf_led(True))

            pm5b_inst, _, _, _ = self.open_pm5b_serial(pm5b_port, timeout_sec=3.0)
            range_str = self.combo_pm5b_range.get()
            ind_rng = {"200 uW": 1, "2 mW": 2, "20 mW": 3, "200 mW": 4}.get(range_str, 3)
            self.set_pm5b_range(pm5b_inst, ind_rng)

            for i, sgx_freq in enumerate(sgx_freqs, start=1):
                if getattr(self, "_stop_flag", False):
                    self.root.after(0, lambda: self.lbl_status.config(
                        text="Measurement Stopped", foreground="red"))
                    break

                shf_freq = sgx_freq / 12.0
                self._shf_send_cmd(shf_inst, f"CLKSRC:FREQUENCY={int(shf_freq * 1e9)};")
                time.sleep(0.05)

                try:
                    import re
                    resp = self._shf_query_cmd(shf_inst, "CLKSRC:FREQUENCY=?;", local_timeout=500)
                    m = re.search(r"[-+]?[0-9]*\.?[0-9]+", resp)
                    actual_shf_ghz = float(m.group(0)) / 1e9 if m else shf_freq
                except Exception:
                    actual_shf_ghz = shf_freq

                self.root.after(0, lambda idx=i, total=len(sgx_freqs), sf=sgx_freq, af=actual_shf_ghz:
                                self.lbl_status.config(
                                    text=f"Measuring... ({idx}/{total})  SGX {sf:.3f} GHz  →  SHF {af:.6f} GHz",
                                    foreground="orange"))

                time.sleep(delay_sec)
                try:
                    measured_w, measured_dbm = self.read_pm5b_power_dbm(pm5b_inst, ind_rng)
                    measured_mw = measured_w * 1000.0
                except Exception:
                    measured_mw = None
                    measured_dbm = None

                self.root.after(0, lambda idx=i, sf=sgx_freq, hf=actual_shf_ghz,
                                mw=measured_mw, dbm=measured_dbm:
                                self.add_result_row(idx, sf, hf, mw, dbm))

                if measured_mw is not None and measured_dbm is not None:
                    result_text = f"{measured_mw:.4f} mW  /  {measured_dbm:.2f} dBm"
                    self.current_data["freq"].append(sgx_freq)
                    self.current_data["dbm"].append(measured_dbm)
                    self.root.after(0, self.update_plot)
                elif measured_mw is not None:
                    result_text = f"{measured_mw:.4f} mW  /  Under Range"
                else:
                    result_text = "PM5B Read Error"

                self.root.after(0, lambda txt=result_text: self.lbl_result.config(text=txt))

        except Exception as e:
            self.root.after(0, lambda err=e: messagebox.showerror("Measurement Error", str(err)))
        finally:
            if shf_inst:
                try:
                    self._set_shf_state_robust(shf_inst, False)
                    self.root.after(0, lambda: self.update_rf_led(False))
                    shf_inst.close()
                except Exception:
                    pass
            if pm5b_inst:
                try:
                    pm5b_inst.close()
                except Exception:
                    pass
            self.root.after(0, lambda: self.btn_run.config(state="normal"))
            self.root.after(0, lambda: self.btn_stop.config(state="disabled"))
            self.root.after(0, lambda: self.btn_pm5b_zero.config(state="normal"))
            if not getattr(self, "_stop_flag", False):
                self.root.after(0, lambda: self.lbl_status.config(text="Ready", foreground="blue"))

    # ------------------------------------------------------------------ #
    #  PM5B Scale                                                          #
    # ------------------------------------------------------------------ #

    def action_set_pm5b_scale(self):
        t = threading.Thread(target=self._routine_set_pm5b_scale)
        t.daemon = True
        t.start()

    def _routine_set_pm5b_scale(self):
        pm5b_inst = None
        try:
            self.root.after(0, lambda: self.btn_set_scale.config(state="disabled"))
            pm5b_port = self.normalize_com_port(self.entry_pm5b_port.get())
            pm5b_inst, _, _, _ = self.open_pm5b_serial(pm5b_port, timeout_sec=2.0)
            range_str = self.combo_pm5b_range.get()
            ind_rng = {"200 uW": 1, "2 mW": 2, "20 mW": 3, "200 mW": 4}.get(range_str, 3)
            self.set_pm5b_range(pm5b_inst, ind_rng)
            self.root.after(0, lambda rs=range_str: self.lbl_applied_scale.config(
                text=f"(Applied: {rs})", foreground="blue"))
        except Exception as e:
            self.root.after(0, lambda err=e: messagebox.showerror("PM5B Scale Error", str(err)))
        finally:
            if pm5b_inst:
                try:
                    pm5b_inst.close()
                except Exception:
                    pass
            self.root.after(0, lambda: self.btn_set_scale.config(state="normal"))

    def on_scale_changed(self, *_):
        settling = {"200 uW": "31.0", "2 mW": "5.0", "20 mW": "1.0", "200 mW": "0.4"}
        self.entry_delay.delete(0, tk.END)
        self.entry_delay.insert(0, settling.get(self.combo_pm5b_range.get(), "5.0"))

    # ------------------------------------------------------------------ #
    #  Plot & Data                                                         #
    # ------------------------------------------------------------------ #

    def update_plot(self):
        self.ax.clear()
        self.ax.set_title("Power vs Frequency")
        self.ax.set_xlabel("Frequency (GHz)")
        self.ax.grid(True)

        if (self.var_cal.get()
                and self.loaded_data["freq"]
                and self.current_data["freq"]):
            cal_dbm = [p - np.interp(f, self.loaded_data["freq"], self.loaded_data["dbm"])
                       for f, p in zip(self.current_data["freq"], self.current_data["dbm"])]
            self.ax.plot(self.current_data["freq"], cal_dbm, "b.-", label="Calibrated Data")
            self.ax.set_ylabel("Relative Power / S21 (dB)")
        else:
            if self.loaded_data["freq"]:
                self.ax.plot(self.loaded_data["freq"], self.loaded_data["dbm"],
                             "r.-", label="Loaded Data (Thru)")
            if self.current_data["freq"]:
                self.ax.plot(self.current_data["freq"], self.current_data["dbm"],
                             "b.-", label="Current Data")
            self.ax.set_ylabel("Power (dBm)")

        if self.loaded_data["freq"] or self.current_data["freq"]:
            self.ax.legend()
        self.canvas.draw()

    def save_data(self):
        if not self.current_data["freq"]:
            messagebox.showwarning("Save Data", "No measurement data to save.")
            return
        name = self.entry_save_name.get().strip() or "data"
        os.makedirs("data", exist_ok=True)
        file_path = os.path.join("data", f"{name}.csv")
        try:
            with open(file_path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["Frequency (GHz)", "Power (dBm)"])
                for freq, dbm in zip(self.current_data["freq"], self.current_data["dbm"]):
                    writer.writerow([freq, dbm])
            messagebox.showinfo("Save Data", f"Data saved to {file_path}")
        except Exception as e:
            messagebox.showerror("Save Data Error", str(e))

    def load_data(self):
        file_path = filedialog.askopenfilename(
            initialdir="data", title="Select Data File",
            filetypes=(("CSV Files", "*.csv"), ("All Files", "*.*")))
        if not file_path:
            return
        try:
            freqs, dbms = [], []
            with open(file_path, "r") as f:
                reader = csv.reader(f)
                next(reader, None)
                for row in reader:
                    if len(row) >= 2:
                        try:
                            freqs.append(float(row[0]))
                            dbms.append(float(row[1]))
                        except ValueError:
                            pass
            if freqs:
                idx = np.argsort(freqs)
                self.loaded_data["freq"] = np.array(freqs)[idx].tolist()
                self.loaded_data["dbm"] = np.array(dbms)[idx].tolist()
                self.lbl_loaded_file.config(text=f"Loaded: {os.path.basename(file_path)}")
                self.update_plot()
            else:
                messagebox.showwarning("Load Data", "No valid data found in file.")
        except Exception as e:
            messagebox.showerror("Load Data Error", str(e))

    # ------------------------------------------------------------------ #
    #  Results table helpers                                               #
    # ------------------------------------------------------------------ #

    def clear_results_table(self):
        for row in self.tree_results.get_children():
            self.tree_results.delete(row)

    def add_result_row(self, idx, sgx_freq, shf_freq, mw, dbm):
        self.tree_results.insert("", "end", values=(
            idx,
            f"{sgx_freq:.3f}",
            f"{shf_freq:.6f}",
            f"{mw:.6f}" if mw is not None else "ERR",
            f"{dbm:.3f}" if dbm is not None else "ERR",
        ))

    # ------------------------------------------------------------------ #
    #  RF LED                                                              #
    # ------------------------------------------------------------------ #

    def update_rf_led(self, is_on):
        self._is_rf_on = is_on
        if is_on:
            self.lbl_rf_led.config(text="🟢 ON", fg="green")
        else:
            self.lbl_rf_led.config(text="⚫ OFF", fg="gray")

    # ------------------------------------------------------------------ #
    #  SHF instrument helpers                                             #
    # ------------------------------------------------------------------ #

    def resolve_shf_address(self):
        shf_addr = self.entry_shf_addr.get().strip()
        if shf_addr and shf_addr.upper() != "AUTO":
            if shf_addr.upper().startswith("COM"):
                suffix = shf_addr[3:].strip()
                if suffix.isdigit():
                    return f"ASRL{int(suffix)}::INSTR"
            return shf_addr

        resources = self.rm.list_resources()
        for addr in resources:
            if not addr.startswith(("USB", "TCPIP", "GPIB", "ASRL")):
                continue
            inst = None
            try:
                inst = self.rm.open_resource(addr)
                inst.timeout = 2000
                if "ASRL" in addr:
                    try:
                        baud = int(self.entry_shf_baud.get().strip())
                    except (ValueError, AttributeError):
                        baud = 115200
                    inst.baud_rate = baud
                    inst.data_bits = 8
                    inst.parity = pyvisa.constants.Parity.none
                    inst.stop_bits = pyvisa.constants.StopBits.one
                    inst.flow_control = pyvisa.constants.ControlFlow.none
                inst.write_termination = "\n"
                inst.read_termination = "\n"
                resp = inst.query("CLKSRC:FREQUENCY=?;").strip()
                if resp:
                    self.root.after(0, lambda a=addr: self.entry_shf_addr.delete(0, tk.END))
                    self.root.after(0, lambda a=addr: self.entry_shf_addr.insert(0, a))
                    return addr
            except Exception:
                pass
            finally:
                if inst:
                    try:
                        inst.close()
                    except Exception:
                        pass

        raise RuntimeError("SHF 78120B를 찾지 못했습니다. 주소를 직접 입력해 주세요.")

    def _open_shf_inst(self, timeout=3000):
        shf_addr = self.resolve_shf_address()
        inst = self.rm.open_resource(shf_addr)
        inst.timeout = timeout
        if "ASRL" in shf_addr:
            try:
                baud = int(self.entry_shf_baud.get().strip())
            except (ValueError, AttributeError):
                baud = 115200
            inst.baud_rate = baud
            inst.data_bits = 8
            inst.parity = pyvisa.constants.Parity.none
            inst.stop_bits = pyvisa.constants.StopBits.one
            inst.flow_control = pyvisa.constants.ControlFlow.none
        inst.write_termination = "\n"
        inst.read_termination = "\n"
        if "ASRL" in shf_addr:
            time.sleep(1.0)
        return inst

    def _shf_write_cmd(self, shf_inst, cmd):
        import datetime
        log_path = os.path.join(os.path.dirname(__file__), "shf_comm_debug.log")
        addr = getattr(shf_inst, "resource_name", str(shf_inst))
        t = datetime.datetime.now().isoformat()
        try:
            bw = shf_inst.write(cmd)
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(f"{t} WRITE {addr} -> {cmd!r} bytes={bw}\n")
        except Exception as ex:
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(f"{t} WRITE-ERR {addr} -> {cmd!r} ERR={ex}\n")

    def _shf_query_cmd(self, shf_inst, cmd, local_timeout=500):
        import datetime
        log_path = os.path.join(os.path.dirname(__file__), "shf_comm_debug.log")
        addr = getattr(shf_inst, "resource_name", str(shf_inst))
        t = datetime.datetime.now().isoformat()
        old_timeout = getattr(shf_inst, "timeout", None)
        shf_inst.timeout = local_timeout
        try:
            resp = shf_inst.query(cmd).strip()
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(f"{t} QUERY {addr} -> {cmd!r} RESP={resp!r}\n")
            return resp
        except Exception as ex:
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(f"{t} QUERY-ERR {addr} -> {cmd!r} ERR={ex}\n")
            return ""
        finally:
            if old_timeout is not None:
                shf_inst.timeout = old_timeout

    def _shf_send_cmd(self, shf_inst, cmd):
        self._shf_write_cmd(shf_inst, cmd)
        return ""

    def _normalize_shf_state_response(self, response):
        text = str(response).strip().upper().replace(";", "")
        if "=" in text:
            text = text.split("=")[-1].strip()
        return text

    def _response_to_bool(self, response):
        text = self._normalize_shf_state_response(response)
        if text in ("1", "ON", "TRUE"):
            return True
        if text in ("0", "OFF", "FALSE"):
            return False
        return None

    def _read_shf_rf_state(self, shf_inst):
        for cmd in ("CLKSRC:OUTPUT=?;", "OUTP?", "OUTP:STAT?"):
            resp = self._shf_query_cmd(shf_inst, cmd, local_timeout=500)
            if resp:
                state = self._response_to_bool(resp)
                if state is not None:
                    return state
        return None

    def _set_shf_state_robust(self, shf_inst, turn_on, power=None):
        target = "ON" if turn_on else "OFF"
        self._shf_send_cmd(shf_inst, f"CLKSRC:OUTPUT={target};")
        time.sleep(0.3)
        if turn_on and power is not None:
            self._shf_send_cmd(shf_inst, f"CLKSRC:AMPLITUDE={power};")
            time.sleep(0.1)
        is_on = self._read_shf_rf_state(shf_inst)
        if is_on is not None:
            return (turn_on and is_on) or (not turn_on and not is_on)
        return True

    # ------------------------------------------------------------------ #
    #  PM5B helpers                                                        #
    # ------------------------------------------------------------------ #

    def normalize_com_port(self, raw_port):
        port = (raw_port or "").strip().upper()
        if not port:
            raise ValueError("PM5B COM Port가 비어 있습니다. 예: COM4")
        if port.startswith("COM"):
            suffix = port[3:].strip()
            if not suffix.isdigit():
                raise ValueError(f"잘못된 COM 포트 형식: {raw_port}")
            return f"COM{int(suffix)}"
        if port.isdigit():
            return f"COM{int(port)}"
        raise ValueError(f"잘못된 COM 포트 형식: {raw_port}")

    def _serial_readline(self, ser):
        line = ser.readline()
        return line.decode(errors="ignore").strip() if line else ""

    def _pm5b_build_cmd(self, c1, c2, c3=0):
        return bytes([ord(c1), ord(c2), c3, 0, 0, 0, 0, 13])

    def _pm5b_flush_input(self, ser):
        try:
            ser.reset_input_buffer()
        except Exception:
            pass

    def _pm5b_read_exact(self, ser, nbytes):
        data = bytearray()
        deadline = time.time() + (ser.timeout if ser.timeout else 2.0)
        while len(data) < nbytes and time.time() < deadline:
            chunk = ser.read(nbytes - len(data))
            if chunk:
                data.extend(chunk)
            else:
                break
        if len(data) != nbytes:
            raise RuntimeError(f"PM5B read timeout: expected {nbytes}, got {len(data)}")
        return bytes(data)

    def parse_pm5b_watts_from_ascii(self, text):
        import re
        m = re.search(r"[-+]?[0-9]*\.?[0-9]+([eE][-+]?[0-9]+)?", text)
        if not m:
            raise ValueError(f"PM5B ASCII parse failed: {text}")
        return float(m.group(0))

    def set_pm5b_range(self, ser, ind_rng):
        if ind_rng not in (1, 2, 3, 4):
            raise ValueError("PM5B range index must be 1..4")
        cmds = [f"RANGE {ind_rng}", f"RANG {ind_rng}"]
        extra = {1: ["SENS:POW:RANG 200UW", "SCALE 200UW"],
                 2: ["SENS:POW:RANG 2MW",   "SCALE 2MW"],
                 3: ["SENS:POW:RANG 20MW",  "SCALE 20MW"],
                 4: ["SENS:POW:RANG 200MW", "SCALE 200MW"]}
        cmds.extend(extra.get(ind_rng, []))
        for cmd in cmds:
            try:
                ser.reset_input_buffer()
                ser.write((cmd + "\r").encode())
                ser.flush()
                time.sleep(0.12)
                probe = self._serial_read_response(ser)
                return cmd, probe
            except Exception:
                pass
        return None, "No response"

    def zero_pm5b_binary(self, ser):
        try:
            cmd = self._pm5b_build_cmd("!", "S", ord("Z"))
            self._pm5b_flush_input(ser)
            ser.write(cmd)
            ser.flush()
            time.sleep(1.0)
            try:
                ack = self._pm5b_read_exact(ser, 1)[0]
                return "!SZ", "ACK" if ack == 0x06 else f"ACK=0x{ack:02X}"
            except Exception:
                time.sleep(0.5)
                return "!SZ", self._serial_read_response(ser)
        except Exception as e:
            raise RuntimeError(f"PM5B zero failed: {e}")

    def read_pm5b_power_dbm(self, ser, ind_rng):
        settling_times = [31.0, 5.0, 1.0, 0.4]
        range_max_w = [200e-6, 2e-3, 20e-3, 200e-3]
        if ind_rng not in (1, 2, 3, 4):
            raise ValueError("PM5B range index must be 1..4")

        time.sleep(settling_times[ind_rng - 1])

        try:
            cmd_query = self._pm5b_build_cmd("?", "D", ord("1"))
            self._pm5b_flush_input(ser)
            ser.write(cmd_query)
            ser.flush()
            response = self._pm5b_read_exact(ser, 6)
            if response[1] == ord("D"):
                raw_count = int.from_bytes(response[2:4], byteorder="little", signed=True)
                p_watts = float(raw_count) * 2.0 * range_max_w[ind_rng - 1] / 59576.0
                if p_watts <= 0:
                    return p_watts, None
                return p_watts, 10.0 * math.log10(p_watts * 1000.0)
        except Exception:
            pass

        for q_cmd in ("MEAS?", "PWR?", "READ?"):
            try:
                ascii_resp = self.query_pm5b(ser, q_cmd)
                if ascii_resp:
                    w = self.parse_pm5b_watts_from_ascii(ascii_resp)
                    dbm = 10.0 * math.log10(w * 1000.0) if w > 0 else None
                    return w, dbm
            except Exception:
                pass

        raise RuntimeError("Failed to read PM5B power (no valid response)")

    def _serial_read_response(self, ser, settle_sec=0.05):
        end_time = time.time() + (ser.timeout if ser.timeout else 2.0)
        chunks = []
        time.sleep(settle_sec)
        while time.time() < end_time:
            waiting = getattr(ser, "in_waiting", 0)
            chunk = ser.read(waiting) if waiting else ser.read(1)
            if chunk:
                chunks.append(chunk)
                if b"\n" in chunk or b"\r" in chunk:
                    break
            elif chunks:
                break
        return b"".join(chunks).replace(b"\r", b"\n").decode(errors="ignore").strip()

    def query_pm5b(self, ser, command):
        ser.reset_input_buffer()
        ser.write((command + "\r").encode())
        ser.flush()
        return self._serial_read_response(ser)

    def open_pm5b_serial(self, com_port, timeout_sec=3.0):
        baud_candidates = [115200, 921600, 57600, 38400, 19200, 9600]
        cmd_candidates = ["READ?", "MEAS?", "PWR?", "IDN?", "*IDN?"]
        debug_logs = []
        for baud in baud_candidates:
            ser = None
            try:
                ser = serial.Serial(
                    port=com_port, baudrate=baud,
                    bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    timeout=timeout_sec, write_timeout=timeout_sec)
                time.sleep(0.12)
                for cmd in cmd_candidates:
                    try:
                        resp = self.query_pm5b(ser, cmd)
                        if resp:
                            return ser, baud, cmd, resp
                    except Exception:
                        debug_logs.append(f"baud={baud}, cmd={cmd}, fail")
                return ser, baud, None, ""
            except Exception as open_err:
                debug_logs.append(f"baud={baud}, open_err={open_err}")
                if ser and ser.is_open:
                    ser.close()
        raise RuntimeError(
            "PM5B 시리얼 연결 실패\n" + "\n".join(debug_logs[-8:]))


if __name__ == "__main__":
    root = tk.Tk()
    app = MeasureApp(root)
    root.mainloop()
