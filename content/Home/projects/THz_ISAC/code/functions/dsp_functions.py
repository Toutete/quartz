import numpy as np

def rrc_filter(span_sym, alpha, ts, fs):
    t = np.arange(-span_sym, span_sym + 1) / fs
    h = np.zeros(len(t))
    for i, tc in enumerate(t):
        if tc == 0: 
            h[i] = 1.0 + alpha * (4 / np.pi - 1)
        elif abs(tc) == ts / (4 * alpha): 
            h[i] = (alpha / np.sqrt(2)) * (((1 + 2 / np.pi) * np.sin(np.pi / (4 * alpha))) + ((1 - 2 / np.pi) * np.cos(np.pi / (4 * alpha))))
        else: 
            h[i] = (np.sin(np.pi * tc / ts * (1 - alpha)) + 4 * alpha * tc / ts * np.cos(np.pi * tc / ts * (1 + alpha))) / (np.pi * tc / ts * (1 - (4 * alpha * tc / ts) ** 2))
    return h / np.sum(h)

def bits_per_symbol(modulation: str) -> int:
    """Returns the number of bits per symbol for a given modulation."""
    mod = modulation.strip().upper()
    if '16QAM' in mod:
        return 4
    elif 'QPSK' in mod:
        return 2
    return 1

def prbs_bits_lfsr(n: int, length: int) -> np.ndarray:
    """Generates PRBS bits using a simple LFSR simulation."""
    if n not in [7, 9, 11, 15, 20, 23]:
        n = 11 # Default
    
    # Simple LFSR taps for common PRBS
    taps = {7: [6, 5], 9: [8, 4], 11: [10, 8], 15: [14, 13], 20: [19, 2], 23: [22, 17]}
    
    state = np.ones(n, dtype=np.uint8)
    bits = np.zeros(length, dtype=np.uint8)
    
    for i in range(length):
        bits[i] = state[-1]
        feedback = np.bitwise_xor.reduce([state[t-1] for t in taps[n]])
        state = np.roll(state, 1)
        state[0] = feedback
        
    return bits

def bits_to_qam_symbols(bits: np.ndarray, modulation: str) -> np.ndarray:
    """Converts bits to QAM symbols (placeholder)."""
    bps = bits_per_symbol(modulation)
    num_symbols = len(bits) // bps
    
    # Generate random complex symbols for placeholder
    rng = np.random.default_rng()
    symbols = rng.standard_normal(num_symbols) + 1j * rng.standard_normal(num_symbols)
    
    # Normalize to have roughly unit power
    return symbols / np.sqrt(np.mean(np.abs(symbols)**2))

def hard_bits_from_symbols(symbols: np.ndarray, modulation: str) -> np.ndarray:
    """Performs hard decision and converts symbols to bits (placeholder)."""
    bps = bits_per_symbol(modulation)
    num_bits = len(symbols) * bps
    return np.random.randint(0, 2, num_bits, dtype=np.uint8)

def normalize_iq_for_awg(iq_signal: np.ndarray) -> np.ndarray:
    """Normalizes complex IQ signal for AWG (returns tuple of real arrays)."""
    i_sig = np.real(iq_signal)
    q_sig = np.imag(iq_signal)
    max_abs = np.max([np.max(np.abs(i_sig)), np.max(np.abs(q_sig))])
    if max_abs == 0:
        return (i_sig, q_sig)
    return i_sig / max_abs, q_sig / max_abs

def normalize_real_for_awg(real_signal: np.ndarray) -> np.ndarray:
    """Normalizes a real signal to the range [-1, 1]."""
    max_abs = np.max(np.abs(real_signal))
    if max_abs == 0:
        return real_signal
    return real_signal / max_abs

def simple_lms_equalizer(rx_symbols: np.ndarray, ref_symbols: np.ndarray, num_taps: int, mu: float) -> np.ndarray:
    """Placeholder for an LMS equalizer."""
    print("Warning: Using placeholder 'simple_lms_equalizer'. Returns input signal.")
    return rx_symbols

def apply_cross_polarization_sic(rx_signal: np.ndarray, tx_ref: np.ndarray, num_taps: int, mu: float, lam: float, max_lag: int, adapt_len: int | None) -> tuple[np.ndarray, dict]:
    """Placeholder for cross-polarization SIC."""
    print("Warning: Using placeholder 'apply_cross_polarization_sic'. Returns input signal.")
    return rx_signal, {"sic_db": 0.0, "lag_samples": 0}

def apply_linear_rls_sic(rx_signal: np.ndarray, tx_ref: np.ndarray, num_taps: int, lam: float, max_lag: int, adapt_len: int | None) -> tuple[np.ndarray, dict]:
    """Placeholder for linear RLS SIC."""
    print("Warning: Using placeholder 'apply_linear_rls_sic'. Returns input signal.")
    return rx_signal, {"sic_db": 0.0, "lag_samples": 0}

def align_symbols_for_ber(ref_symbols: np.ndarray, est_symbols: np.ndarray, max_lag: int) -> tuple[np.ndarray, np.ndarray]:
    """
    Aligns estimated symbols to reference symbols by finding the best correlation lag.
    """
    if len(ref_symbols) == 0 or len(est_symbols) == 0:
        return np.array([]), np.array([])

    # Ensure they are 1D arrays
    ref = np.ravel(ref_symbols)
    est = np.ravel(est_symbols)

    best_lag = 0
    max_corr = 0
    # Simplified alignment: just trim to the same length for placeholder
    min_len = min(len(ref), len(est))
    ref_aligned = ref[:min_len]
    est_aligned = est[:min_len]
    
    print(f"Warning: Using simplified placeholder 'align_symbols_for_ber'.")
    return ref_aligned, est_aligned


def sc_fde_equalizer(rx_symbols, ref_symbols, num_taps=1, enable=True):
    import numpy as np
    from scipy.signal import lfilter
    if not enable or len(rx_symbols) == 0 or len(ref_symbols) == 0:
        return rx_symbols
        
    n_train = min(len(rx_symbols), len(ref_symbols))
    if n_train < 10:
        return rx_symbols
        
    rx_train = rx_symbols[:n_train]
    tx_train = ref_symbols[:n_train]
    
    if num_taps <= 1:
        a = np.vdot(rx_train, tx_train) / (np.vdot(rx_train, rx_train) + 1e-15)
        return a * rx_symbols
    else:
        # Time-domain LS FIR
        X = np.zeros((n_train - num_taps + 1, num_taps), dtype=np.complex128)
        for i in range(num_taps):
            X[:, i] = rx_train[num_taps - 1 - i : n_train - i]
        d = tx_train[num_taps - 1:]
        
        w, _, _, _ = np.linalg.lstsq(X, d, rcond=None)
        eq_sig = lfilter(w, [1.0], rx_symbols)
        delay = (num_taps - 1) // 2
        return np.roll(eq_sig, -delay)

def lfm_qam_rx_dsp_chain(rx_signal, fs, baud_rate, if_freq, chirp_signal=None, tx_ref_symbols=None, rrc_alpha=0.25, rx_mode="Mixer", sc_fde_enable=True, sc_fde_taps=1):
    import numpy as np
    from scipy.signal import firwin, lfilter, fftconvolve
    N_len = len(rx_signal)
    t = np.arange(N_len) / fs
    
    # 0. DC Removal
    sig = rx_signal - np.mean(rx_signal)
    
    # 1. Band-pass filtering
    bw_hz = baud_rate * (1 + rrc_alpha)
    if rx_mode == "Mixer":
        # Passband filter
        f_low = max(0.1e9, if_freq - bw_hz/2)
        f_high = min(fs/2 - 0.1e9, if_freq + bw_hz/2)
        taps = firwin(101, [f_low, f_high], fs=fs, pass_zero=False)
        sig = lfilter(taps, 1.0, sig)
        
        # 2. Downconversion
        rx_bb = sig * np.exp(-1j * 2.0 * np.pi * if_freq * t)
        taps_lpf = firwin(101, bw_hz/2, fs=fs)
        rx_bb = lfilter(taps_lpf, 1.0, rx_bb)
    else:
        # ZBD mode (Direct detection, so it's already baseband roughly, just LPF)
        taps_lpf = firwin(101, bw_hz/2, fs=fs)
        rx_bb = lfilter(taps_lpf, 1.0, sig)
        rx_bb = rx_bb + 0j
        
    sps = int(round(fs / baud_rate))
    
    # 3. Matched Filter (RRC)
    if chirp_signal is None:
        h_rrc = rrc_filter(span_sym=8*sps, alpha=rrc_alpha, ts=1.0/baud_rate, fs=fs)
        rx_bb = fftconvolve(rx_bb, h_rrc, mode='same')
    else:
        # For LFM-QAM (chirp_signal != None), RRC is bypassed at TX, so bypass here too
        pass
        
    # Dechirp if LFM-QAM
    if chirp_signal is not None:
        # The transmitted signal has `chirp_signal` repeating every chirp.
        # However, precise dechirping before sync is complex without knowing frame bounds.
        # We perform a rough dechirp on the entire sequence if it's a single chirp length 
        # or tile it. For now, we tile the chirp to match rx_bb length.
        reps = int(np.ceil(len(rx_bb) / max(len(chirp_signal), 1)))
        full_chirp = np.tile(chirp_signal, reps)[:len(rx_bb)]
        # We don't dechirp blindly here because of unknown propagation delay (which causes a beat frequency).
        # We will let the SC-FDE equalizer handle the residual phase if it's small, 
        # or we just rely on the user's manual processing.
        # As a basic implementation:
        rx_bb = rx_bb * np.conj(full_chirp)
    
    # 4. Frame Sync (Zadoff-Chu Cross-Correlation)
    train_len = len(tx_ref_symbols)
    zc_seq = tx_ref_symbols[:63]
    
    rx_bb_1sps = rx_bb[::sps]
    corr = fftconvolve(rx_bb_1sps, np.conj(zc_seq[::-1]), mode="valid")
    if len(corr) == 0:
        return None, None, float("nan")
        
    peak_idx = int(np.argmax(np.abs(corr)))
    
    if peak_idx + train_len > len(rx_bb_1sps):
        return None, None, float("nan")
        
    # 5. Timing Sync (Gardner-like/TED approximated by argmax correlation)
    # Actually, we use the peak_idx for timing.
    sym_rx = rx_bb_1sps[peak_idx:peak_idx+len(tx_ref_symbols)]
    tx_ref = tx_ref_symbols[:len(sym_rx)]
    
    if len(sym_rx) < 200:
        return None, None, float("nan")
        
    # 6. Residual CFO/Phase (Pilot-based)
    g0 = 63
    g1 = min(train_len, g0 + 200) 
    if g1 > g0:
        if rx_mode == "Mixer":
            ph = np.unwrap(np.angle(sym_rx * np.conj(tx_ref) + 1e-15))
            ph_s = np.convolve(ph, np.ones(11)/11, mode="same")
            sym_rx_ph = sym_rx * np.exp(-1j * ph_s)
            
            # 7. Channel Estimation (LS) & 8. Equalization (SC-FDE)
            r_fit = sym_rx_ph[g0:g1]
            t_fit = tx_ref[g0:g1]
            A = np.column_stack((r_fit, np.conj(r_fit)))
            coef, _, _, _ = np.linalg.lstsq(A, t_fit, rcond=None)
            sym_rx_ph = coef[0] * sym_rx_ph + coef[1] * np.conj(sym_rx_ph)
            eq_all = sc_fde_equalizer(sym_rx_ph, tx_ref, num_taps=sc_fde_taps, enable=sc_fde_enable)
        else:
            eq_all = sc_fde_equalizer(sym_rx, tx_ref, num_taps=sc_fde_taps, enable=sc_fde_enable)
            
        # 9. Normalization (AGC)
        scale = np.sqrt(np.mean(np.abs(tx_ref[g0:g1])**2) / (np.mean(np.abs(eq_all[g0:g1])**2) + 1e-15))
        eq_all *= scale
        
        # 10. Demapping + Performance
        err = eq_all[g0:g1] - t_fit
        nmse = np.mean(np.abs(err) ** 2) / (np.mean(np.abs(t_fit) ** 2) + 1e-15)
        evm_db = 20 * np.log10(np.sqrt(nmse) + 1e-15)
        
        return eq_all, tx_ref, evm_db
        
    return None, None, float("nan")


def generate_zadoff_chu(N: int, u: int):
    import numpy as np
    n = np.arange(N)
    return np.exp(-1j * np.pi * u * n * (n + 1) / N)
