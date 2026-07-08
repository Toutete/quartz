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
    if '64QAM' in mod:
        return 6
    if '32QAM' in mod:
        return 5
    if '16QAM' in mod:
        return 4
    elif '8PSK' in mod:
        return 3
    elif 'QPSK' in mod:
        return 2
    return 1

# Standard 3-bit Gray sequence: natural binary index -> Gray-coded phase index,
# so adjacent 8PSK constellation points differ by exactly one bit.
_PSK8_GRAY_LUT = np.array([0, 1, 3, 2, 6, 7, 5, 4], dtype=np.int64)
_PSK8_GRAY_INV = np.zeros(8, dtype=np.int64)
_PSK8_GRAY_INV[_PSK8_GRAY_LUT] = np.arange(8)

def _gray_to_binary_int(gray: np.ndarray) -> np.ndarray:
    out = np.asarray(gray, dtype=np.int64).copy()
    shift = 1
    while shift < 64:
        out ^= out >> shift
        shift <<= 1
    return out

def _bits_to_rect_qam_symbols(b: np.ndarray, i_bits: int, q_bits: int) -> np.ndarray:
    i_word = np.zeros(len(b), dtype=np.int64)
    q_word = np.zeros(len(b), dtype=np.int64)
    for k in range(i_bits):
        i_word = (i_word << 1) | b[:, k].astype(np.int64)
    for k in range(q_bits):
        q_word = (q_word << 1) | b[:, i_bits + k].astype(np.int64)

    i_idx = _gray_to_binary_int(i_word)
    q_idx = _gray_to_binary_int(q_word)
    i_levels = np.arange(-(2 ** i_bits - 1), 2 ** i_bits, 2, dtype=np.float64)
    q_levels = np.arange(-(2 ** q_bits - 1), 2 ** q_bits, 2, dtype=np.float64)
    syms = i_levels[i_idx] + 1j * q_levels[q_idx]
    grid = (i_levels[:, None] + 1j * q_levels[None, :]).reshape(-1)
    norm = np.sqrt(np.mean(np.abs(grid) ** 2))
    return (syms / norm).astype(np.complex128)

def _qam32_cross_points() -> np.ndarray:
    rows = (
        (5.0, (-3.0, -1.0, 1.0, 3.0)),
        (3.0, (-5.0, -3.0, -1.0, 1.0, 3.0, 5.0)),
        (1.0, (-5.0, -3.0, -1.0, 1.0, 3.0, 5.0)),
        (-1.0, (-5.0, -3.0, -1.0, 1.0, 3.0, 5.0)),
        (-3.0, (-5.0, -3.0, -1.0, 1.0, 3.0, 5.0)),
        (-5.0, (-3.0, -1.0, 1.0, 3.0)),
    )
    pts = np.array([i + 1j * q for q, i_vals in rows for i in i_vals], dtype=np.complex128)
    return pts / np.sqrt(np.mean(np.abs(pts) ** 2))

def _bits_to_32cross_qam_symbols(b: np.ndarray) -> np.ndarray:
    b = np.asarray(b, dtype=np.uint8)
    if b.size == 0:
        return np.array([], dtype=np.complex128)
    if b.ndim != 2 or b.shape[1] != 5:
        b = b.reshape(-1, 5)
    idx = (
        (b[:, 0].astype(np.int64) << 4)
        | (b[:, 1].astype(np.int64) << 3)
        | (b[:, 2].astype(np.int64) << 2)
        | (b[:, 3].astype(np.int64) << 1)
        | b[:, 4].astype(np.int64)
    )
    return _qam32_cross_points()[idx]

def _hard_bits_from_32cross_qam(symbols: np.ndarray) -> np.ndarray:
    syms = np.asarray(symbols, dtype=np.complex128)
    const = _qam32_cross_points()
    dist = np.abs(syms[:, None] - const[None, :])
    idx = np.argmin(dist, axis=1).astype(np.int64)
    bits = np.empty(5 * len(syms), dtype=np.uint8)
    bits[0::5] = (idx >> 4) & 1
    bits[1::5] = (idx >> 3) & 1
    bits[2::5] = (idx >> 2) & 1
    bits[3::5] = (idx >> 1) & 1
    bits[4::5] = idx & 1
    return bits

def prbs_bits_lfsr(n: int, length: int) -> np.ndarray:
    """Generate deterministic maximum-length PRBS bits.

    The previous PRBS11 implementation used a tap/orientation combination
    that only produced eight 16QAM nibbles when grouped four bits per symbol.
    Use the standard polynomial taps and one consistent Fibonacci orientation
    so higher-order QAM sees the full constellation.
    """
    if n not in [7, 9, 11, 15, 20, 23]:
        n = 11 # Default
    
    taps = {
        7: (7, 6),
        9: (9, 5),
        11: (11, 9),
        15: (15, 14),
        20: (20, 3),
        23: (23, 18),
    }
    
    state = np.ones(n, dtype=np.uint8)
    bits = np.zeros(length, dtype=np.uint8)
    
    for i in range(length):
        bits[i] = state[-1]
        feedback = np.uint8(0)
        for tap in taps[n]:
            feedback ^= state[n - tap]
        state[:-1] = state[1:]
        state[-1] = feedback
        
    return bits

def bits_to_qam_symbols(bits: np.ndarray, modulation: str) -> np.ndarray:
    """Gray-coded symbol mapping for BPSK, QPSK, 8PSK, 16/32/64QAM."""
    mod = modulation.strip().upper()
    bps = bits_per_symbol(mod)
    n_sym = len(bits) // bps
    if n_sym == 0:
        return np.array([], dtype=np.complex128)
    b = np.asarray(bits[:n_sym * bps], dtype=np.uint8).reshape(n_sym, bps)

    if 'BPSK' in mod:
        # 0→+1, 1→-1
        return (1.0 - 2.0 * b[:, 0].astype(np.float64)).astype(np.complex128)

    if 'QPSK' in mod:
        # Gray: b0→I, b1→Q; 0→+1/√2, 1→-1/√2
        I = (1.0 - 2.0 * b[:, 0].astype(np.float64)) / np.sqrt(2.0)
        Q = (1.0 - 2.0 * b[:, 1].astype(np.float64)) / np.sqrt(2.0)
        return (I + 1j * Q).astype(np.complex128)

    if '8PSK' in mod:
        # Gray-coded 8PSK: 3 bits -> natural binary index -> Gray-mapped phase
        # index k -> phase = 2*pi*k/8, unit modulus (constant envelope).
        bits_int = (b[:, 0].astype(np.int64) << 2) | (b[:, 1].astype(np.int64) << 1) | b[:, 2].astype(np.int64)
        phase_idx = _PSK8_GRAY_LUT[bits_int]
        phase = 2.0 * np.pi * phase_idx.astype(np.float64) / 8.0
        return np.exp(1j * phase).astype(np.complex128)

    if '16QAM' in mod:
        # Gray map per axis: (MSB,LSB)=(0,0)→-3, (0,1)→-1, (1,1)→+1, (1,0)→+3
        # Normalized by √10 so average power = 1
        def _gray_to_level(msb, lsb):
            sign = 2.0 * msb.astype(np.float64) - 1.0   # 0→-1, 1→+1
            mag  = 3.0 - 2.0 * lsb.astype(np.float64)   # 0→3,  1→1
            return sign * mag / np.sqrt(10.0)
        I = _gray_to_level(b[:, 0], b[:, 1])
        Q = _gray_to_level(b[:, 2], b[:, 3])
        return (I + 1j * Q).astype(np.complex128)

    if '32QAM' in mod:
        return _bits_to_32cross_qam_symbols(b)

    if '64QAM' in mod:
        return _bits_to_rect_qam_symbols(b, i_bits=3, q_bits=3)

    # Fallback: BPSK
    return (1.0 - 2.0 * b[:, 0].astype(np.float64)).astype(np.complex128)

def _rect_qam_hard_bits(symbols: np.ndarray, i_bits: int, q_bits: int) -> np.ndarray:
    syms = np.asarray(symbols, dtype=np.complex128)
    i_levels = np.arange(-(2 ** i_bits - 1), 2 ** i_bits, 2, dtype=np.float64)
    q_levels = np.arange(-(2 ** q_bits - 1), 2 ** q_bits, 2, dtype=np.float64)
    grid = (i_levels[:, None] + 1j * q_levels[None, :]).reshape(-1)
    norm = np.sqrt(np.mean(np.abs(grid) ** 2))
    I = np.real(syms) * norm
    Q = np.imag(syms) * norm
    i_idx = np.argmin(np.abs(I[:, None] - i_levels[None, :]), axis=1).astype(np.int64)
    q_idx = np.argmin(np.abs(Q[:, None] - q_levels[None, :]), axis=1).astype(np.int64)
    i_gray = i_idx ^ (i_idx >> 1)
    q_gray = q_idx ^ (q_idx >> 1)
    bps = i_bits + q_bits
    bits = np.empty(bps * len(syms), dtype=np.uint8)
    for k in range(i_bits):
        bits[k::bps] = (i_gray >> (i_bits - 1 - k)) & 1
    for k in range(q_bits):
        bits[i_bits + k::bps] = (q_gray >> (q_bits - 1 - k)) & 1
    return bits

def hard_bits_from_symbols(symbols: np.ndarray, modulation: str) -> np.ndarray:
    """Hard-decision demapping for BPSK, QPSK, 8PSK, 16/32/64QAM."""
    mod = modulation.strip().upper()
    syms = np.asarray(symbols, dtype=np.complex128)

    if 'BPSK' in mod:
        return (np.real(syms) < 0.0).astype(np.uint8)

    if 'QPSK' in mod:
        b0 = (np.real(syms) < 0.0).astype(np.uint8)
        b1 = (np.imag(syms) < 0.0).astype(np.uint8)
        return np.stack([b0, b1], axis=1).reshape(-1)

    if '8PSK' in mod:
        phase = np.mod(np.angle(syms), 2.0 * np.pi)
        phase_idx = np.round(phase / (2.0 * np.pi / 8.0)).astype(np.int64) % 8
        bits_int = _PSK8_GRAY_INV[phase_idx]
        n = len(syms)
        bits = np.empty(3 * n, dtype=np.uint8)
        bits[0::3] = (bits_int >> 2) & 1
        bits[1::3] = (bits_int >> 1) & 1
        bits[2::3] = bits_int & 1
        return bits

    if '16QAM' in mod:
        # Undo normalization: decision thresholds at 0 and ±2/√10
        norm = np.sqrt(10.0)
        I = np.real(syms) * norm
        Q = np.imag(syms) * norm

        def _level_to_gray(v):
            msb = (v > 0.0).astype(np.uint8)           # positive half → MSB=1
            lsb = (np.abs(v) < 2.0).astype(np.uint8)   # inner levels → LSB=1
            return msb, lsb

        bi0, bi1 = _level_to_gray(I)
        bq0, bq1 = _level_to_gray(Q)
        n = len(syms)
        bits = np.empty(4 * n, dtype=np.uint8)
        bits[0::4] = bi0
        bits[1::4] = bi1
        bits[2::4] = bq0
        bits[3::4] = bq1
        return bits

    if '32QAM' in mod:
        return _hard_bits_from_32cross_qam(syms)

    if '64QAM' in mod:
        return _rect_qam_hard_bits(syms, i_bits=3, q_bits=3)

    return (np.real(syms) < 0.0).astype(np.uint8)

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
    """Cross-correlation alignment: find lag in [-max_lag, +max_lag] maximising |<ref[lag:], est>|."""
    ref = np.ravel(np.asarray(ref_symbols, dtype=np.complex128))
    est = np.ravel(np.asarray(est_symbols, dtype=np.complex128))
    if len(ref) == 0 or len(est) == 0:
        return np.array([], dtype=np.complex128), np.array([], dtype=np.complex128)

    if max_lag <= 0:
        n = min(len(ref), len(est))
        return ref[:n].copy(), est[:n].copy()

    # lag > 0: ref is ahead by lag samples → align ref[lag:] with est[:]
    # lag < 0: est is ahead by |lag| samples → align ref[:] with est[-lag:]
    best_lag = 0
    best_c = -1.0
    for lag in range(-max_lag, max_lag + 1):
        if lag >= 0:
            n_ov = min(len(ref) - lag, len(est))
            if n_ov < 4:
                continue
            n = min(n_ov, 1024)
            c = float(np.abs(np.dot(ref[lag:lag + n], np.conj(est[:n]))))
        else:
            n_ov = min(len(ref), len(est) + lag)   # lag<0 so +lag = -|lag|
            if n_ov < 4:
                continue
            n = min(n_ov, 1024)
            c = float(np.abs(np.dot(ref[:n], np.conj(est[-lag:-lag + n]))))
        if c > best_c:
            best_c = c
            best_lag = lag

    if best_lag >= 0:
        r_out = ref[best_lag:]
        n_out = min(len(r_out), len(est))
        return r_out[:n_out].copy(), est[:n_out].copy()
    else:
        e_out = est[-best_lag:]
        n_out = min(len(ref), len(e_out))
        return ref[:n_out].copy(), e_out[:n_out].copy()


def sc_fde_equalizer(rx_symbols, ref_symbols, num_taps=21, enable=True):
    import numpy as np

    rx = np.asarray(rx_symbols, dtype=np.complex128).reshape(-1)
    ref = np.asarray(ref_symbols, dtype=np.complex128).reshape(-1)
    if not enable or len(rx) == 0 or len(ref) == 0:
        return rx

    num_taps = max(1, int(num_taps))
        
    n_train = min(len(rx), len(ref))
    if n_train < num_taps * 2:
        return rx
        
    rx_train = rx[:n_train]
    tx_train = ref[:n_train]
    
    if num_taps <= 1:
        a = np.vdot(rx_train, tx_train) / (np.vdot(rx_train, rx_train).real + 1e-15)
        return a * rx

    # Centered feed-forward equalizer.  Row n estimates ref[n] from
    # rx[n-delay] ... rx[n+post], so the returned stream stays sample-aligned.
    delay = num_taps // 2
    post = num_taps - delay - 1
    row_start = delay
    row_stop = n_train - post
    n_rows = row_stop - row_start
    if n_rows < max(num_taps, 8):
        return rx

    X = np.empty((n_rows, num_taps), dtype=np.complex128)
    for tap in range(num_taps):
        src_start = row_start - delay + tap
        X[:, tap] = rx_train[src_start:src_start + n_rows]
    d = tx_train[row_start:row_start + n_rows]

    # Small diagonal loading keeps the LS solution stable when the training
    # sequence has deep spectral notches or when decision-directed refs are used.
    xhx = X.conj().T @ X
    xhd = X.conj().T @ d
    reg = 1e-4 * (float(np.trace(xhx).real) / max(num_taps, 1) + 1e-15)
    try:
        w = np.linalg.solve(xhx + reg * np.eye(num_taps, dtype=np.complex128), xhd)
    except np.linalg.LinAlgError:
        w, _, _, _ = np.linalg.lstsq(X, d, rcond=None)

    left = delay
    right = post
    if len(rx) > 1:
        rx_pad = np.pad(rx, (left, right), mode="edge")
    else:
        rx_pad = np.pad(rx, (left, right), mode="constant")

    try:
        windows = np.lib.stride_tricks.sliding_window_view(rx_pad, num_taps)
        y = windows @ w
    except Exception:
        y = np.empty_like(rx)
        for n in range(len(rx)):
            y[n] = np.dot(rx_pad[n:n + num_taps], w)

    a = np.vdot(y[:n_train], ref[:n_train]) / (np.vdot(y[:n_train], y[:n_train]).real + 1e-15)
    return a * y

def lfm_qam_rx_dsp_chain(rx_signal, fs, baud_rate, if_freq, chirp_signal=None, tx_ref_symbols=None, rrc_alpha=0.25, rx_mode="Mixer", sc_fde_enable=True, sc_fde_taps=1):
    import numpy as np
    from scipy.signal import firwin, lfilter, fftconvolve
    N_len = len(rx_signal)
    t = np.arange(N_len) / fs
    
    # 0. DC Removal
    sig = rx_signal - np.mean(rx_signal)
    
    # 1. Band-pass filtering
    bw_hz = baud_rate * (1 + rrc_alpha)
    nyq = fs / 2.0
    if rx_mode == "Mixer":
        # Passband filter — clamp to valid firwin range
        f_low = float(np.clip(if_freq - bw_hz / 2, 1e6, nyq - 1e6))
        f_high = float(np.clip(if_freq + bw_hz / 2, f_low + 1e6, nyq - 1e6))
        if f_low < f_high:
            taps = firwin(101, [f_low, f_high], fs=fs, pass_zero=False)
            sig = lfilter(taps, 1.0, sig)

        # 2. Downconversion
        rx_bb = sig * np.exp(-1j * 2.0 * np.pi * if_freq * t)
        lpf_cut = float(np.clip(bw_hz / 2, 1e6, nyq - 1e6))
        taps_lpf = firwin(101, lpf_cut, fs=fs)
        rx_bb = lfilter(taps_lpf, 1.0, rx_bb)
    else:
        # ZBD mode (Direct detection, so it's already baseband roughly, just LPF)
        lpf_cut = float(np.clip(bw_hz / 2, 1e6, nyq - 1e6))
        taps_lpf = firwin(101, lpf_cut, fs=fs)
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
