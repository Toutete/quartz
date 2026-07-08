import re

with open('c:/Users/user/quartz/content/Home/projects/THz_ISAC/code/isac_unified_gui.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. IsacTxSimPanel: Remove 'Generate TX Signal' and 'Download to AWG'
content = re.sub(
    r'ttk\.Button\(btn_frame_hw, text="Generate TX Signal".*?\.pack\(side=tk\.LEFT\)',
    '',
    content
)
content = re.sub(
    r'ttk\.Button\(btn_frame_hw, text="Download to AWG".*?\.pack\(side=tk\.LEFT, padx=\(8, 0\)\)',
    '',
    content
)

# 2. Add more variables to trace_add in IsacTxSimPanel
trace_orig = r'for var in \[self.prbs_n_var, self.fs_var, self.symbol_rate_var, self.chirp_len_var\]:\n\s+var.trace_add\("write", lambda \*_: self._check_memory_limit\(\)\)'
trace_new = '''for var in [self.prbs_n_var, self.fs_var, self.symbol_rate_var, self.chirp_len_var, self.modulation_var, self.waveform_var, self.if_var]:
                    var.trace_add("write", lambda *_: [self._check_memory_limit(), self._on_generate()])'''
content = re.sub(trace_orig, trace_new, content)

# 3. Remove duplicate params from PhotonicIsacSimPanel._build_ui
content = re.sub(r'add_p\(0, "fs_gsps", "Sample Rate \[GS/s\]", "100"\)', r'# removed fs_gsps', content)
content = re.sub(r'add_p\(2, "baud_gbaud", "Baud Rate \[Gbaud\]", "10"\)', r'# removed baud_gbaud', content)
content = re.sub(r'add_p\(3, "if_ghz", "IF Freq \[GHz\]", "10"\)', r'# removed if_ghz', content)

# Careful with waveform
content = re.sub(
    r'ttk\.Label\(grp, text="TX Waveform"\)\.grid\(row=4, column=0, sticky="w", pady=2\)\n\s+self\.waveform_var = tk\.StringVar\(value="16QAM"\)\n\s+ttk\.Combobox\(grp, textvariable=self\.waveform_var, values=\["16QAM", "LFM-16QAM", "OFDM-16QAM"\], width=12, state="readonly"\)\.grid\(row=4, column=1\)',
    r'self.waveform_var = tk.StringVar(value="16QAM") # Hidden, managed by awg',
    content
)

content = re.sub(r'add_p\(5, "chirp_bw_ghz", "Chirp BW \[GHz\]", "2\.0"\)', r'# removed chirp_bw_ghz', content)

# 4. Remove Comm EVM %, ZBD noise, LNA noise from KPI rows
content = re.sub(r'"noise":\s+self\.table\.insert\("", "end", text="LNA Noise",\s+values=\("0\.00", "dBm"\)\),\n', '', content)
content = re.sub(r'"zbd":\s+self\.table\.insert\("", "end", text="ZBD Noise",\s+values=\("0\.00", "V"\)\),\n', '', content)
content = re.sub(r'"evm_est":\s+self\.table\.insert\("", "end", text="Comm EVM",\s+values=\("N/A",  "dB"\)\),\n', '', content)
content = re.sub(r'"evm_pct":\s+self\.table\.insert\("", "end", text="Comm EVM %",\s+values=\("N/A",  "%"\)\),\n', '', content)

# 5. Remove updating them in _update_table
content = re.sub(r'self\.table\.item\(self\.rows\["noise"\], values=\(f"\{lna_noise_dbm:\.1f\}", "dBm"\)\)\n', '', content)
content = re.sub(r'self\.table\.item\(self\.rows\["zbd"\], values=\(f"\{zbd_noise_v:\.3e\}", "V"\)\)\n', '', content)
content = re.sub(r'self\.table\.item\(self\.rows\["evm_est"\], values=\("N/A", "dB"\)\)\n', '', content)
content = re.sub(r'self\.table\.item\(self\.rows\["evm_pct"\], values=\("N/A", "%"\)\)\n', '', content)

# 6. Adjust _cfg_from_ui to read from awg_source
cfg_orig = '''def _cfg_from_ui(self) -> SimConfig:
        cfg = SimConfig(
            fs_gsps=float(self.params["fs_gsps"].get()),
            linewidth_mhz=float(self.params["linewidth_mhz"].get()),
            baud_gbaud=float(self.params["baud_gbaud"].get()),
            if_ghz=float(self.params["if_ghz"].get()),
            rf_carrier_ghz=270.0,
            waveform=self.waveform_var.get().strip(),
            chirp_bw_ghz=max(float(self.params["chirp_bw_ghz"].get()), 0.01),'''

cfg_new = '''def _cfg_from_ui(self) -> SimConfig:
        awg = self.awg_source
        cfg = SimConfig(
            fs_gsps=float(awg.fs_var.get()) if awg else 100.0,
            linewidth_mhz=float(self.params["linewidth_mhz"].get()),
            baud_gbaud=float(awg.symbol_rate_var.get()) if awg else 10.0,
            if_ghz=float(awg.if_var.get()) if awg else 10.0,
            rf_carrier_ghz=float(awg.rf_var.get()) if awg else 270.0,
            waveform=awg.waveform_var.get().strip() if awg else "LFM-QAM",
            chirp_bw_ghz=float(awg.symbol_rate_var.get()) if awg else 2.0,'''
content = content.replace(cfg_orig, cfg_new)

# 7. Update UnifiedApp plot size and layout weights
content = content.replace('tx_sim_paned.add(sim_right, weight=2)', 'tx_sim_paned.add(sim_right, weight=3)')
content = content.replace('self.fig = Figure(figsize=(10.5, 7.2), dpi=100)', 'self.fig = Figure(figsize=(8, 8), dpi=100)')

with open('c:/Users/user/quartz/content/Home/projects/THz_ISAC/code/isac_unified_gui.py', 'w', encoding='utf-8') as f:
    f.write(content)
