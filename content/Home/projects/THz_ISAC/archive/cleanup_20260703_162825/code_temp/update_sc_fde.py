import re

with open('c:/Users/user/quartz/content/Home/projects/THz_ISAC/code/isac_unified_gui.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update imports
content = content.replace('simple_lms_equalizer', 'sc_fde_equalizer')

# 2. Add UI controls to PhotonicIsacSimPanel
ui_sim = '''        ttk.Label(grp, text="Target Dist [m]").grid(row=24, column=0, sticky="w", pady=2)
        self.params["target_dist_m"] = tk.StringVar(value="1.0")
        self.params["target_dist_m"].trace_add("write", self._update_table)
        ttk.Entry(grp, textvariable=self.params["target_dist_m"], width=10).grid(row=24, column=1, sticky="w")
        
        self.sc_fde_enable_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(grp, text="Enable SC-FDE", variable=self.sc_fde_enable_var).grid(row=25, column=0, columnspan=2, sticky="w", pady=2)
        ttk.Label(grp, text="SC-FDE Taps").grid(row=26, column=0, sticky="w", pady=2)
        self.sc_fde_taps_var = tk.StringVar(value="21")
        ttk.Entry(grp, textvariable=self.sc_fde_taps_var, width=10).grid(row=26, column=1, sticky="w")'''

content = re.sub(r'ttk\.Label\(grp, text="Target Dist \[m\]"\)\.grid\(row=24.*?width=10\)\.grid\(row=24, column=1, sticky="w"\)', ui_sim, content, flags=re.DOTALL)


# 3. Add UI controls to DsoPanel
ui_dso = '''        self.filter_overlay_var = tk.BooleanVar(value=True)
        self.filter_enable_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(grp2, text="Show filtered spectrum", variable=self.filter_overlay_var,
                        command=self._plot_spectrum_and_time).grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Checkbutton(grp2, text="Apply demod LPF", variable=self.filter_enable_var).grid(
            row=4, column=2, columnspan=2, sticky="w", padx=(10, 0), pady=(6, 0))
            
        self.sc_fde_enable_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(grp2, text="Enable SC-FDE", variable=self.sc_fde_enable_var).grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Label(grp2, text="SC-FDE Taps").grid(row=5, column=2, sticky="w", padx=(10, 0), pady=(6, 0))
        self.sc_fde_taps_var = tk.StringVar(value="21")
        ttk.Entry(grp2, textvariable=self.sc_fde_taps_var, width=10).grid(row=5, column=3, sticky="w", pady=(6, 0))'''

content = re.sub(r'self\.filter_overlay_var = tk\.BooleanVar\(value=True\).*?padx=\(10, 0\), pady=\(6, 0\)\)', ui_dso, content, flags=re.DOTALL)


# 4. Replace sc_fde_equalizer calls in _run_sim
# Old calls look like: sc_fde_equalizer(qam_est, qam_ref, num_taps=21, mu=0.005)
# We want to use the UI variables instead.
sc_call_1 = r'sc_fde_equalizer\(qam_est, qam_ref, num_taps=21, mu=0\.005\)'
sc_call_new_1 = r'sc_fde_equalizer(qam_est, qam_ref, num_taps=int(_parse_float_input(self.sc_fde_taps_var.get(), "SC-FDE Taps")), enable=self.sc_fde_enable_var.get())'
content = re.sub(sc_call_1, sc_call_new_1, content)

sc_call_2 = r'sc_fde_equalizer\(sym_rx, tx_ref, num_taps=21, mu=0\.05\)'
sc_call_new_2 = r'sc_fde_equalizer(sym_rx, tx_ref, num_taps=int(_parse_float_input(self.sc_fde_taps_var.get(), "SC-FDE Taps")), enable=self.sc_fde_enable_var.get())'
content = re.sub(sc_call_2, sc_call_new_2, content)

# 5. Update DsoPanel._on_demodulate to pass UI variables
dsp_call = r'''lfm_qam_rx_dsp_chain\(
                    rx_signal=sig,
                    fs=fs,
                    baud_rate=sr,
                    if_freq=fc,
                    chirp_signal=chirp_sig,
                    tx_ref_symbols=tx_ref,
                    rrc_alpha=beta,
                    rx_mode="Mixer"
                \)'''

dsp_call_new = '''lfm_qam_rx_dsp_chain(
                    rx_signal=sig,
                    fs=fs,
                    baud_rate=sr,
                    if_freq=fc,
                    chirp_signal=chirp_sig,
                    tx_ref_symbols=tx_ref,
                    rrc_alpha=beta,
                    rx_mode="Mixer",
                    sc_fde_enable=self.sc_fde_enable_var.get(),
                    sc_fde_taps=max(1, int(_parse_float_input(self.sc_fde_taps_var.get(), "SC-FDE Taps")))
                )'''

content = re.sub(dsp_call, dsp_call_new, content)

with open('c:/Users/user/quartz/content/Home/projects/THz_ISAC/code/isac_unified_gui.py', 'w', encoding='utf-8') as f:
    f.write(content)
