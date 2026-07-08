import numpy as np
from pathlib import Path
import sys

# Add the project directory to sys.path so we can import modules
sys.path.append(str(Path(__file__).parent))

from functions.dsp_functions import (
    sc_fde_equalizer,
    generate_zadoff_chu,
    bits_to_qam_symbols,
    align_symbols_for_ber,
    hard_bits_from_symbols,
)
from isac_unified_gui import IsacTxSimPanel, DsoPanel

def test_demod_qam():
    print("Testing QAM demodulation...")
    fs = 120e9
    sym_rate = 1e9
    nps = int(fs / sym_rate)
    n_sym = 1000
    if_freq = 0.0

    # 1. Generate QAM symbols
    np.random.seed(42)
    bits = np.random.randint(0, 2, n_sym * 2)
    syms = bits_to_qam_symbols(bits, "QPSK")
    
    # Prepend ZC sequence for QAM frame sync
    zc = generate_zadoff_chu(63, 25)
    tx_syms = np.concatenate([zc, syms])

    # RRC Filtering
    rrc_taps = DsoPanel._rrc_filter(nps, beta=0.25, span=6)
    up = np.zeros(len(tx_syms) * nps, dtype=np.complex128)
    up[::nps] = tx_syms
    tx_bb = np.convolve(up, rrc_taps, mode="full")

    # Construct payload
    pl = {
        "waveform_type": "QAM",
        "modulation": "QPSK",
        "fs": fs,
        "symbol_rate": sym_rate,
        "sps": nps,
        "if_freq": if_freq,
        "qam_preamble_symbols": zc,
        "qam_rrc_taps": rrc_taps,
        "tx_sym_matrix": tx_syms,
        "n_chirps": 1,
        "n_sym_per_chirp": len(tx_syms),
    }

    # Simulate RX
    rx = tx_bb.copy()
    if if_freq > 0:
        t = np.arange(len(rx)) / fs
        rx = np.real(rx * np.exp(1j * 2 * np.pi * if_freq * t))
    
    # Inject delay and noise
    delay = 1500
    rx = np.pad(rx, (delay, 1000))
    rx += np.random.randn(len(rx)) * 0.01 + 1j * np.random.randn(len(rx)) * 0.01
    
    import tkinter as tk
    root = tk.Tk()
    dso = DsoPanel(root, None)
    
    rx_bb, fs_ref = dso._rx_to_baseband(rx, fs, pl)
    
    # QAM frame sync
    up_tmpl = np.zeros(len(zc) * nps, dtype=np.complex128)
    up_tmpl[::nps] = zc
    qam_template = np.convolve(up_tmpl, rrc_taps, mode="full")

    from scipy.signal import fftconvolve
    corr = np.abs(fftconvolve(rx_bb, np.conj(qam_template[::-1]), mode="valid"))
    frame_start = int(np.argmax(corr))
    
    print(f"Actual Delay: {delay}, Estimated Frame Start: {frame_start}")

    total_pts = pl["n_chirps"] * pl["n_sym_per_chirp"] * nps
    rx_frame = rx_bb[frame_start : frame_start + total_pts]
    
    rx_mf = np.convolve(rx_frame, rrc_taps, mode="same")
    
    delay_sps = (len(rrc_taps) - 1) // 2
    rx_mf_sync = rx_mf[delay_sps:] if delay_sps < len(rx_mf) else rx_mf
    
    syms_est = IsacTxSimPanel._gardner_timing_recovery(rx_mf_sync, sps=nps, n_symbols=pl["n_chirps"] * pl["n_sym_per_chirp"])
    
    print(f"First 5 expected symbols: {tx_syms[:5]}")
    print(f"First 5 Gardner symbols: {syms_est[:5]}")
    
    print(f"Number of estimated symbols: {len(syms_est)}, expected: {len(tx_syms)}")
    
    # Align and test
    ref_al, est_al = align_symbols_for_ber(tx_syms, syms_est, max_lag=nps * 4)
    print(f"Aligned lengths: {len(ref_al)} and {len(est_al)}")
    
    # Calculate EVM
    err = est_al - ref_al
    evm_rms = np.sqrt(np.mean(np.abs(err) ** 2) / np.mean(np.abs(ref_al) ** 2))
    print(f"EVM: {evm_rms*100:.2f}%")
    root.destroy()

def test_demod_lfm_qam():
    print("\nTesting LFM-QAM demodulation...")
    fs = 120e9
    sym_rate = 1e9
    nps = int(fs / sym_rate)
    n_sym = 100
    n_chirps = 5
    if_freq = 0.0

    np.random.seed(42)
    # Preamble chirp, 1 Pilot chirp, (n_chirps-2) Data chirps
    n_ovhd = 2
    zc = generate_zadoff_chu(63, 25)
    tx_sym_matrix = np.zeros((n_chirps, n_sym), dtype=np.complex128)
    tx_sym_matrix[0, :len(zc)] = zc
    tx_sym_matrix[0, len(zc):] = zc[0] # Pad
    tx_sym_matrix[1, :] = bits_to_qam_symbols(np.random.randint(0, 2, n_sym*2), "QPSK")
    for i in range(2, n_chirps):
        tx_sym_matrix[i, :] = bits_to_qam_symbols(np.random.randint(0, 2, n_sym*2), "QPSK")

    # Generate chirp
    t_chirp = np.arange(n_sym * nps) / fs
    bw = sym_rate / 2
    from scipy.signal import chirp
    base_chirp = chirp(t_chirp, f0=-bw/2, t1=t_chirp[-1], f1=bw/2, method='linear') * np.exp(1j * 2 * np.pi * (-bw/2) * t_chirp)
    # The above is not exact, let's just use a random complex base chirp
    base_chirp = np.exp(1j * 2 * np.pi * 0.1 * t_chirp)
    
    tx_bb_matrix = np.repeat(tx_sym_matrix, nps, axis=1) * base_chirp[np.newaxis, :]
    tx_bb = tx_bb_matrix.reshape(-1)

    pl = {
        "waveform_type": "LFM-QAM",
        "modulation": "QPSK",
        "fs": fs,
        "symbol_rate": sym_rate,
        "sps": nps,
        "if_freq": if_freq,
        "tx_bb_matrix": tx_bb_matrix,
        "tx_sym_matrix": tx_sym_matrix,
        "base_chirp": base_chirp,
        "n_chirps": n_chirps,
        "n_sym_per_chirp": n_sym,
        "n_overhead_chirps": n_ovhd,
    }

    # Simulate RX
    rx = tx_bb.copy()
    delay = 1500
    rx = np.pad(rx, (delay, 1000))
    rx += np.random.randn(len(rx)) * 0.01 + 1j * np.random.randn(len(rx)) * 0.01
    
    import tkinter as tk
    root = tk.Tk()
    dso = DsoPanel(root, None)
    
    rx_bb, fs_ref = dso._rx_to_baseband(rx, fs, pl)
    
    rx_mat, tx_bb_mat, tx_sym_mat, _base_chirp, _n_chirps, _n_sym, _nps, pts_per_chirp, frame_start = \
        dso._frame_sync_and_reshape(rx_bb, fs_ref, pl)
        
    print(f"Actual Delay: {delay}, Estimated Frame Start: {frame_start}")
    
    dechirped_mat = rx_mat * np.conj(_base_chirp)[np.newaxis, :]
    
    # Do exactly what _on_demodulate does for LFM-QAM
    pilot_ref = tx_sym_mat[1]
    pilot_raw = dechirped_mat[1]
    best_nmse = np.inf
    for phase in range(max(1, _nps)):
        cand_p = pilot_raw[phase::_nps][:_n_sym]
        if len(cand_p) < _n_sym: continue
        den_p = np.sum(np.abs(cand_p) ** 2) + 1e-15
        h_p = np.sum(pilot_ref * np.conj(cand_p)) / den_p
        nmse_p = float(np.mean(np.abs(h_p * cand_p - pilot_ref) ** 2) / (np.mean(np.abs(pilot_ref) ** 2) + 1e-15))
        if nmse_p < best_nmse:
            best_nmse, best_phase = nmse_p, phase
            
    print(f"Best Phase: {best_phase}")
    pilot_rx = dechirped_mat[1, best_phase::_nps][:_n_sym]
    den_h = np.sum(np.abs(pilot_rx) ** 2) + 1e-15
    h_est = np.sum(tx_sym_mat[1] * np.conj(pilot_rx)) / den_h

    data_raw = dechirped_mat[n_ovhd:, best_phase::_nps]
    if data_raw.shape[1] >= _n_sym: data_raw = data_raw[:, :_n_sym]
    else: data_raw = np.pad(data_raw, ((0, 0), (0, _n_sym - data_raw.shape[1])))
    
    qam_est = (data_raw * h_est).reshape(-1)
    qam_ref = tx_sym_mat[n_ovhd:].reshape(-1)
    
    ref_al, est_al = align_symbols_for_ber(qam_ref, qam_est, max_lag=_nps * 4)
    print(f"Aligned lengths: {len(ref_al)} and {len(est_al)}")
    err = est_al - ref_al
    evm_rms = np.sqrt(np.mean(np.abs(err) ** 2) / np.mean(np.abs(ref_al) ** 2))
    print(f"LFM-QAM EVM (Before Equalizer): {evm_rms*100:.2f}%")
    
    est_eq = sc_fde_equalizer(est_al, ref_al, num_taps=21, enable=True)
    ref_fin, est_fin = align_symbols_for_ber(ref_al, est_eq, max_lag=4)
    err2 = est_fin - ref_fin
    evm_rms2 = np.sqrt(np.mean(np.abs(err2) ** 2) / np.mean(np.abs(ref_fin) ** 2))
    print(f"LFM-QAM EVM (After Equalizer): {evm_rms2*100:.2f}%")
    
    root.destroy()

if __name__ == "__main__":
    test_demod_qam()
    test_demod_lfm_qam()
