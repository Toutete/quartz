import re

with open('c:/Users/user/quartz/content/Home/projects/THz_ISAC/code/isac_unified_gui.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. DSP Metrics Calculation Update
snr_old = r'''            bw_sig_hz    = \(f2_ghz - f1_ghz\) \* 1e9
            p_noise_mw   = nf_mwhz \* bw_sig_hz
            snr_db       = 10\.0 \* np\.log10\(max\(p_sig_mw / max\(p_noise_mw, 1e-30\), 1e-30\)\)

            self\.band_pwr_var\.set\(f"Band Power:  \{p_sig_dbm:\.2f\} dBm"\)'''

snr_new = '''            bw_sig_hz    = (f2_ghz - f1_ghz) * 1e9
            p_noise_mw   = nf_mwhz * bw_sig_hz
            
            p_sig_true_mw = max(p_sig_mw - p_noise_mw, 1e-30)
            p_sig_true_dbm = 10.0 * np.log10(p_sig_true_mw)
            
            snr_db       = 10.0 * np.log10(max(p_sig_true_mw / max(p_noise_mw, 1e-30), 1e-30))

            self.band_pwr_var.set(f"Band Power:  {p_sig_true_dbm:.2f} dBm")'''

content = re.sub(snr_old, snr_new, content)

# 2. Add DSO Sampling Rate control
dso_conn_old = r'''        ttk\.Label\(grp1, text="DSO Type"\)\.grid\(row=0, column=0, sticky="w", pady=3\)
        self\.dso_type_var = tk\.StringVar\(value="Keysight Infiniium"\)
        ttk\.Combobox\(grp1, textvariable=self\.dso_type_var, values=\["Keysight Infiniium", "Tektronix DPO", "Dummy"\], state="readonly", width=18\)\.grid\(row=0, column=1, sticky="w"\)'''

dso_conn_new = '''        ttk.Label(grp1, text="DSO Type").grid(row=0, column=0, sticky="w", pady=3)
        self.dso_type_var = tk.StringVar(value="Keysight Infiniium")
        ttk.Combobox(grp1, textvariable=self.dso_type_var, values=["Keysight Infiniium", "Tektronix DPO", "Dummy"], state="readonly", width=18).grid(row=0, column=1, sticky="w")
        
        ttk.Label(grp1, text="Sample Rate (GS/s)").grid(row=0, column=2, sticky="w", padx=(10, 0))
        self.dso_sr_var = tk.StringVar(value="256")
        ttk.Combobox(grp1, textvariable=self.dso_sr_var, values=["128", "256"], state="readonly", width=8).grid(row=0, column=3, sticky="w")'''

content = re.sub(dso_conn_old, dso_conn_new, content)

# 3. Apply DSO Sample Rate in capture
dso_capture_old = r'''                    if live:
                        dso\.run\(\)
                    wave = dso\.capture_channel\(ch\)
                    if live:'''

dso_capture_new = '''                    if live:
                        try:
                            srate_gsps = float(self.dso_sr_var.get())
                            dso.query(f":ACQ:SRAT {srate_gsps}E9")
                        except Exception as e:
                            self._log(f"[Conn] Failed to set sample rate: {e}")
                        dso.run()
                    wave = dso.capture_channel(ch)
                    if live:'''

content = re.sub(dso_capture_old, dso_capture_new, content)

# 4. Refactoring UI layout in UnifiedApp
unified_old = r'''        tx_sim_paned = ttk\.PanedWindow\(tab_tx_sim, orient=tk\.HORIZONTAL\)
        tx_sim_paned\.pack\(fill=tk\.BOTH, expand=True\)

        tx_left = ttk\.Frame\(tx_sim_paned\)
        sim_right = ttk\.Frame\(tx_sim_paned\)
        
        tx_sim_paned\.add\(tx_left, weight=1\)
        tx_sim_paned\.add\(sim_right, weight=3\)

        self\.tx_sim_panel = IsacTxSimPanel\(tx_left, runtime=self\.runtime, on_tx_generated=self\._on_reference_npz_ready\)
        self\.photonic_sim_panel = PhotonicIsacSimPanel\(
            sim_right,
            awg_source=self\.tx_sim_panel,
            show_awg_params=False,
        \)'''

unified_new = '''        tx_sim_paned = ttk.PanedWindow(tab_tx_sim, orient=tk.HORIZONTAL)
        tx_sim_paned.pack(fill=tk.BOTH, expand=True)

        # Single sidebar on the left for all controls
        controls_left = ttk.Frame(tx_sim_paned)
        # Main area on the right for all plots
        plots_right = ttk.Frame(tx_sim_paned)
        
        tx_sim_paned.add(controls_left, weight=1)
        tx_sim_paned.add(plots_right, weight=4)
        
        awg_control_frame = ttk.Frame(controls_left)
        awg_control_frame.pack(fill=tk.X)
        
        sim_control_frame = ttk.Frame(controls_left)
        sim_control_frame.pack(fill=tk.X, pady=(10, 0))

        self.tx_sim_panel = IsacTxSimPanel(awg_control_frame, runtime=self.runtime, on_tx_generated=self._on_reference_npz_ready)
        self.photonic_sim_panel = PhotonicIsacSimPanel(
            sim_control_frame,
            awg_source=self.tx_sim_panel,
            show_awg_params=False,
        )
        
        # Override the plot packing for PhotonicIsacSimPanel to go to plots_right
        # We will pack the canvas into plots_right
        self.photonic_sim_panel.canvas.get_tk_widget().pack_forget()
        self.photonic_sim_panel.canvas.get_tk_widget().pack(in_=plots_right, fill=tk.BOTH, expand=True)
        # Hide the empty right frame of PhotonicIsacSimPanel
        if hasattr(self.photonic_sim_panel, "right_frame"):
            self.photonic_sim_panel.right_frame.pack_forget()'''

content = re.sub(unified_old, unified_new, content)

# 5. AWG -> DSO Synchronization
# Add this inside UnifiedApp._on_reference_npz_ready
sync_old = r'''    def _on_reference_npz_ready\(self, file_path: str\) -> None:
        self\.dso_panel\._log\(f"\[App\] Internal TX Reference Updated: \{file_path\}"\)'''

sync_new = '''    def _on_reference_npz_ready(self, file_path: str) -> None:
        self.dso_panel._log(f"[App] Internal TX Reference Updated: {file_path}")
        
        # Auto-synchronize AWG parameters to DSO
        try:
            self.dso_panel.fc_var.set(self.tx_sim_panel.rf_var.get())
            self.dso_panel.sr_var.set(self.tx_sim_panel.symbol_rate_var.get())
            self.dso_panel.demod_mod_var.set(self.tx_sim_panel.modulation_var.get())
            
            # Auto-measure if connected, or at least log sync success
            self.dso_panel._log("[App] AWG parameters synced to DSO panel automatically.")
        except Exception as e:
            self.dso_panel._log(f"[App] Sync error: {e}")'''

content = re.sub(sync_old, sync_new, content)

# 6. Make sure PhotonicIsacSimPanel exposes its right_frame
# Let's replace the `right = ttk.Frame(main)` in PhotonicIsacSimPanel with `self.right_frame = ttk.Frame(main); right = self.right_frame`
content = re.sub(r'right = ttk\.Frame\(main\)', 'self.right_frame = ttk.Frame(main)\n        right = self.right_frame', content)

with open('c:/Users/user/quartz/content/Home/projects/THz_ISAC/code/isac_unified_gui.py', 'w', encoding='utf-8') as f:
    f.write(content)
