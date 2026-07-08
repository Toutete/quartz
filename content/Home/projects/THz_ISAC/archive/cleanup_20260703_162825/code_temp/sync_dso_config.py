import re

with open('c:/Users/user/quartz/content/Home/projects/THz_ISAC/code/isac_unified_gui.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update DsoPanel._on_test_connection to push settings to the hardware
test_conn_old = r'''                    idn = dso\.query\("\*IDN\?"\)
                self\._log\(f"\[Conn\] OK: \{idn\}"\)'''

test_conn_new = '''                    idn = dso.query("*IDN?")
                    
                    try:
                        # Sync Sample Rate
                        sr_val = self.dso_sr_var.get()
                        if sr_val != "Auto":
                            fs_dso_target = float(sr_val) * 1e9
                            dso.write(f":ACQuire:SRATe {fs_dso_target}")
                        
                        # Sync Channel & Windows
                        ch_str = self.ch_var.get().strip().upper()
                        ch_num = ch_str.replace("C", "").replace("HAN", "").replace("NEL", "")
                        if ch_num:
                            dso.write(f":CHANnel{ch_num}:DISPlay ON")
                            dso.write(f":DISPlay:WINDow1:SOURce CHANnel{ch_num}")
                            dso.write(f":FUNCtion1:FFT:SOURce1 CHANnel{ch_num}")
                            dso.write(":FUNCtion1:DISPlay ON")
                            dso.write(":DISPlay:WINDow2:SOURce FUNCtion1")
                        self._log("[Conn] DSO hardware settings applied.")
                    except Exception as ex:
                        self._log(f"[Conn] Warning: could not set all DSO params ({ex})")
                        
                self._log(f"[Conn] OK: {idn}")'''

content = re.sub(test_conn_old, test_conn_new, content)


# 2. Update UnifiedApp._on_reference_npz_ready to sync channel and trigger hardware update
sync_old = r'''            self\.dso_panel\.fc_var\.set\(self\.tx_sim_panel\.rf_var\.get\(\)\)
            self\.dso_panel\.sr_var\.set\(self\.tx_sim_panel\.symbol_rate_var\.get\(\)\)
            self\.dso_panel\.demod_mod_var\.set\(self\.tx_sim_panel\.modulation_var\.get\(\)\)
            
            # Auto-measure if connected, or at least log sync success
            self\.dso_panel\._log\("\[App\] AWG parameters synced to DSO panel automatically\."\)'''

sync_new = '''            self.dso_panel.fc_var.set(self.tx_sim_panel.rf_var.get())
            self.dso_panel.sr_var.set(self.tx_sim_panel.symbol_rate_var.get())
            self.dso_panel.demod_mod_var.set(self.tx_sim_panel.modulation_var.get())
            
            # Sync Channel automatically
            awg_ch = self.tx_sim_panel.ch_var.get().strip()
            if awg_ch:
                first_ch = awg_ch.split(',')[0].strip()
                if first_ch.isdigit():
                    self.dso_panel.ch_var.set(f"C{first_ch}")

            # Auto-apply DSO config to hardware
            self.dso_panel._on_test_connection()
            
            # Auto-measure if connected, or at least log sync success
            self.dso_panel._log("[App] AWG parameters synced to DSO panel automatically.")'''

content = re.sub(sync_old, sync_new, content)


# 3. Fix the "Update table error: 'fs_gsps'" issue which happens because 'fs_gsps' param is removed from self.params
fs_old = r'''            lna_noise_dbm = -174\.0 \+ 10 \* np\.log10\(float\(self\.params\["fs_gsps"\]\.get\(\)\) \* 1e9\) \+ float\(self\.params\["lna_nf_db"\]\.get\(\)\) \+ float\(self\.params\["lna_gain_db"\]\.get\(\)\)
            zbd_noise_v = float\(self\.params\["zbd_resp_vpw"\]\.get\(\)\) \* float\(self\.params\["zbd_nep_pw"\]\.get\(\)\) \* 1e-12 \* np\.sqrt\(float\(self\.params\["fs_gsps"\]\.get\(\)\) \* 1e9 / 2\.0\)'''

fs_new = '''            # Use AWG fs for bandwidth approximation since fs_gsps param was removed
            if getattr(self, "awg_fs_var", None):
                rx_bw_hz = float(self.awg_fs_var.get()) * 1e9
            else:
                rx_bw_hz = 120e9
            
            lna_noise_dbm = -174.0 + 10 * np.log10(rx_bw_hz) + float(self.params["lna_nf_db"].get()) + float(self.params["lna_gain_db"].get())
            zbd_noise_v = float(self.params["zbd_resp_vpw"].get()) * float(self.params["zbd_nep_pw"].get()) * 1e-12 * np.sqrt(rx_bw_hz / 2.0)'''

content = re.sub(fs_old, fs_new, content)

with open('c:/Users/user/quartz/content/Home/projects/THz_ISAC/code/isac_unified_gui.py', 'w', encoding='utf-8') as f:
    f.write(content)
