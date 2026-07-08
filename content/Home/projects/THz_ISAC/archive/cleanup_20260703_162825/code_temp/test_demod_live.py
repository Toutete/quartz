import numpy as np
import tkinter as tk
from isac_unified_gui import UnifiedApp

def test_demod():
    root = tk.Tk()
    app = UnifiedApp(root)
    
    app.tx_sim_panel.modulation_var.set("QPSK")
    app.tx_sim_panel.symbol_rate_var.set("1.0")
    app.tx_sim_panel.mode_var.set("Real IF")
    app.tx_sim_panel.if_var.set("2.0")
    app.tx_sim_panel.waveform_var.set("QAM")
    app.tx_sim_panel.fs_var.set("8.0")
    
    pl = app.tx_sim_panel._generate_tx_signal()
    app.runtime["tx_payload"] = pl
    
    app.photonic_sim_panel.rx_mode_var.set("Baseband (Direct)")
    app.photonic_sim_panel.si_enable_var.set(False)
    app.photonic_sim_panel.delay_var.set("0.5")
    
    t, y_raw, y_bb, fs, meta = app.photonic_sim_panel._build_simulated_rx()
    dso = app.dso_panel
    dso._rx_sig = y_raw
    dso._rx_fs = fs
    
    from isac_unified_gui import _align_symbols_for_ber
    from functions.dsp_functions import sc_fde_equalizer
    from scipy.signal import fftconvolve
    
    rx_bb, fs_ref = dso._rx_to_baseband(y_raw, float(fs), pl)
    
    mod = str(pl.get("modulation", "QAM")).strip()
    waveform_type = str(pl.get("waveform_type", "QAM")).strip()
    nps = int(pl.get("sps", 1))
    sc_fde_taps = int(dso.sc_fde_taps_var.get())
    sc_fde_enable = bool(dso.sc_fde_enable_var.get())
    
    print(f"Demodulating {waveform_type} {mod} with {nps} sps. SC-FDE={sc_fde_enable} ({sc_fde_taps} taps)")
    
    qam_preamble_symbols = np.asarray(pl.get("qam_preamble_symbols", []), dtype=np.complex128).reshape(-1)
    qam_rrc_taps = np.asarray(pl.get("qam_rrc_taps", [1.0]), dtype=np.float64).reshape(-1)
    up = np.zeros(len(qam_preamble_symbols) * nps, dtype=np.complex128)
    up[::nps] = qam_preamble_symbols
    qam_template = np.convolve(up, qam_rrc_taps, mode="full")

    corr = np.abs(fftconvolve(rx_bb, np.conj(qam_template[::-1]), mode="valid"))
    frame_start = int(np.argmax(corr))
    
    n_chirps = int(pl.get("n_chirps", 1))
    n_sym_per_chirp = int(pl.get("n_sym_per_chirp", 0))
    preamble_pts = len(qam_preamble_symbols) * nps
    data_start = frame_start + preamble_pts
    
    total_pts = n_chirps * n_sym_per_chirp * nps
    rx_frame = rx_bb[data_start : data_start + total_pts]
    
    rx_mf = np.convolve(rx_frame, qam_rrc_taps, mode="same")

    delay_sps = (len(qam_rrc_taps) - 1) // 2
    rx_mf_sync = rx_mf[delay_sps:] if delay_sps < len(rx_mf) else rx_mf
    
    from isac_unified_gui import IsacTxSimPanel
    syms_est = IsacTxSimPanel._gardner_timing_recovery(rx_mf_sync, sps=nps, n_symbols=n_chirps * n_sym_per_chirp)
    qam_est = syms_est[:n_chirps * n_sym_per_chirp]
    qam_ref = np.asarray(pl.get("tx_sym_matrix")).reshape(-1)
    
    qam_ref_al, qam_est_al = _align_symbols_for_ber(qam_ref, qam_est, max_lag=max(16, nps * 4))
    
    if len(qam_est_al) > 4:
        ph = np.unwrap(np.angle(qam_est_al * np.conj(qam_ref_al) + 1e-15))
        k = np.arange(len(ph), dtype=np.float64)
        slope, intercept = np.polyfit(k, ph, deg=1)
        qam_est_al = qam_est_al * np.exp(-1j * (slope * k + intercept))
        
    qam_est_eq = sc_fde_equalizer(qam_est_al, qam_ref_al, num_taps=sc_fde_taps, enable=sc_fde_enable)
    qam_ref_fin, qam_est_fin = _align_symbols_for_ber(qam_ref_al, qam_est_eq, max_lag=max(4, nps))

    err = qam_est_fin - qam_ref_fin
    evm_rms = float(np.sqrt(np.mean(np.abs(err) ** 2) / (np.mean(np.abs(qam_ref_fin) ** 2) + 1e-15)))
    evm_db  = 20.0 * np.log10(evm_rms + 1e-15)
    
    print(f"Final EVM: {evm_db:.2f} dB")
    
if __name__ == "__main__":
    test_demod()
