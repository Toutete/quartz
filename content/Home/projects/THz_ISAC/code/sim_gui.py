from __future__ import annotations
from dataclasses import dataclass
import tkinter as tk
from tkinter import messagebox, ttk
import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from scipy.signal import welch, hilbert, fftconvolve

@dataclass
class SimConfig:
    fs_gsps: float = 100.0
    frame_len: int = 4096
    num_frames: int = 100
    step_ns: float = 20.0

    linewidth_mhz: float = 0.1
    baud_gbaud: float = 10.0
    if_ghz: float = 10.0
    rf_carrier_ghz: float = 270.0
    waveform: str = "16QAM"
    chirp_bw_ghz: float = 2.0
    
    coherence_mode: str = "Free-running"
    rx_mode: str = "Mixer"
    si_enable: bool = True
    carrier_wander_enable: bool = True
    carrier_wander_mhz: float = 300.0
    
    # 💡 하드웨어 및 레이더 물리 파라미터 
    utcpd_target_dbm: float = -25.0
    pa_gain_db: float = 24.0
    pa_p1db_dbm: float = -1.0
    lna_gain_db: float = 14.0
    lna_nf_db: float = 8.0
    zbd_responsivity_vpw: float = 2200.0
    zbd_nep_pw_sqrt_hz: float = 12.0
    if_amp_gain_db: float = 20.0
    if_amp_nf_db: float = 5.0
    omt_iso_db: float = 25.0
    ant_gain_dbi: float = 25.0
    target_rcs_sqm: float = 1.0
    target_dist_m: float = 1.0  # Default 1m

    # 내부 계산 변수
    tx_power_dbm: float = 0.0
    path_loss_db: float = 0.0
    delay_ns: float = 0.0

def rrc_filter(span_sym, alpha, ts, fs):
    t = np.arange(-span_sym, span_sym + 1) / fs
    h = np.zeros(len(t))
    for i, tc in enumerate(t):
        if tc == 0: h[i] = 1.0 + alpha * (4 / np.pi - 1)
        elif abs(tc) == ts / (4 * alpha): h[i] = (alpha / np.sqrt(2)) * (((1 + 2 / np.pi) * np.sin(np.pi / (4 * alpha))) + ((1 - 2 / np.pi) * np.cos(np.pi / (4 * alpha))))
        else: h[i] = (np.sin(np.pi * tc / ts * (1 - alpha)) + 4 * alpha * tc / ts * np.cos(np.pi * tc / ts * (1 + alpha))) / (np.pi * tc / ts * (1 - (4 * alpha * tc / ts) ** 2))
    return h / np.sum(h)

def generate_phase_noise(n, lw, fs):
    return np.cumsum(np.random.normal(0, np.sqrt(2 * np.pi * lw / fs), n))

def calc_psd(sig, fs):
    f, p = welch(sig, fs, nperseg=min(2048, len(sig)), return_onesided=False)
    p_v2hz = np.fft.fftshift(p)
    p_w_hz = p_v2hz / 50.0
    p_dbm_hz = 10 * np.log10(p_w_hz * 1e3 + 1e-30)
    return np.fft.fftshift(f), p_dbm_hz

def calc_power_dbm(sig, R=50.0):
    """Time-domain RMS Power 계산 (into 50 ohms)"""
    p_w = np.mean(np.abs(sig)**2) / R
    return 10 * np.log10(p_w + 1e-20) + 30.0

def qam16_hard_demod(symbols):
    const = np.array([-3-3j, -3-1j, -3+1j, -3+3j, -1-3j, -1-1j, -1+1j, -1+3j, 1-3j, 1-1j, 1+1j, 1+3j, 3-3j, 3-1j, 3+1j, 3+3j]) / np.sqrt(10.0)
    return np.argmin(np.abs(symbols[:, None] - const[None, :]), axis=1)


def estimate_measured_evm_percent(evm_db):
    if np.isfinite(evm_db):
        return 100.0 * (10.0 ** (evm_db / 20.0))
    return np.nan

def run_isac_sim(cfg: SimConfig):
    fs = cfg.fs_gsps * 1e9
    frame_len, num_frames = int(cfg.frame_len), int(cfg.num_frames)
    step = max(int(fs * cfg.step_ns * 1e-9), 1)
    total_samples = frame_len + step * num_frames
    t = np.arange(total_samples) / fs

    baud_rate, f_if = cfg.baud_gbaud * 1e9, cfg.if_ghz * 1e9
    samples_per_sym = max(int(fs / baud_rate), 1)

    # 1. Baseband & IF Upconversion (Real)
    qam16_syms = np.array([-3-3j, -3-1j, -3+1j, -3+3j, -1-3j, -1-1j, -1+1j, -1+3j, 1-3j, 1-1j, 1+1j, 1+3j, 3-3j, 3-1j, 3+1j, 3+3j]) / np.sqrt(10.0)
    
    if cfg.waveform == "OFDM-16QAM":
        N_fft_ofdm = 2048
        N_cp = 256
        N_sym_total = N_fft_ofdm + N_cp
        num_ofdm_syms = total_samples // N_sym_total + 2
        active_sc = int((cfg.baud_gbaud * 1e9) / (fs / N_fft_ofdm))
        
        ofdm_bb = np.zeros(num_ofdm_syms * N_sym_total, dtype=complex)
        tx_ofdm_syms = []
        sym_idx_list = []
        
        for i in range(num_ofdm_syms):
            idx = np.random.randint(0, 16, active_sc)
            syms = qam16_syms[idx]
            tx_ofdm_syms.append(syms)
            sym_idx_list.append(idx)
            
            X = np.zeros(N_fft_ofdm, dtype=complex)
            start_idx = N_fft_ofdm//2 - active_sc//2
            X[start_idx : start_idx + active_sc] = syms
            
            X_shifted = np.fft.ifftshift(X)
            x_t = np.fft.ifft(X_shifted) * np.sqrt(N_fft_ofdm)
            
            x_sym = np.concatenate([x_t[-N_cp:], x_t])
            ofdm_bb[i*N_sym_total : (i+1)*N_sym_total] = x_sym
            
        bb_sig = ofdm_bb[:total_samples]
        symbols = np.concatenate(tx_ofdm_syms)
        sym_idx = np.concatenate(sym_idx_list)
        chirp = np.ones_like(t)
    else:
        sym_idx = np.random.randint(0, 16, int(total_samples / samples_per_sym) + 1)
        symbols = qam16_syms[sym_idx]
        upsampled = np.zeros(len(symbols) * samples_per_sym, dtype=complex)
        upsampled[::samples_per_sym] = symbols
        
        h_rrc = rrc_filter(200, 0.1, 1/baud_rate, fs)
        bb_sig = np.convolve(upsampled, h_rrc, mode="same")[:total_samples]
        
        if cfg.waveform == "LFM-16QAM":
            sweep_bw = max(cfg.chirp_bw_ghz, 0.01) * 1e9
            t0 = t - np.mean(t)
            k = sweep_bw / max(t[-1] - t[0], 1.0 / fs)
            chirp = np.exp(1j * np.pi * k * (t0 ** 2))
            bb_sig = bb_sig * chirp
        else:
            chirp = np.ones_like(t)

    x_if_cplx = bb_sig * np.exp(1j * 2 * np.pi * f_if * t)
    x_if_real = np.real(x_if_cplx)

    # MZM intensity modulation uses real IF drive -> optical DSB in both Mixer and ZBD modes.
    m = x_if_real / (np.max(np.abs(x_if_real)) + 1e-12)
    e_mod = 1.0 + 0.5 * m

    # 2. 광학적 결합 및 위상 잡음
    lw = cfg.linewidth_mhz * 1e6
    phi_1 = generate_phase_noise(total_samples, lw, fs)
    phi_2 = generate_phase_noise(total_samples, lw, fs)
    if cfg.coherence_mode == "Self-coherent": phi_2 = phi_1
    
    wander = np.cumsum(np.random.randn(total_samples))
    wander = (wander - np.mean(wander)) / (np.std(wander) + 1e-12) * (cfg.carrier_wander_mhz * 1e6 if cfg.carrier_wander_enable else 0)
    phi_wander = 2 * np.pi * np.cumsum(wander) / fs

    e_data = e_mod * np.exp(1j * phi_1)
    e_lo = 1.0 * np.exp(1j * (phi_2 + phi_wander))
    
    # 3. UTC-PD 비팅 & 전력 스케일링
    beat_raw = e_data * np.conj(e_lo)
    beat_pwr_w = np.mean(np.abs(beat_raw)**2) / 50.0
    target_w = 10**((cfg.utcpd_target_dbm - 30) / 10)
    beat_tx = beat_raw * np.sqrt(target_w / beat_pwr_w)
    
    # 4. THz PA 증폭 + P1dB 제한
    pa_gain_lin = 10**(cfg.pa_gain_db / 20.0)
    v_pa_out = beat_tx * pa_gain_lin
    p_pa_dbm = calc_power_dbm(v_pa_out)
    if p_pa_dbm > cfg.pa_p1db_dbm:
        v_pa_out *= 10 ** ((cfg.pa_p1db_dbm - p_pa_dbm) / 20.0)
    
    # 5. OMT Isolation 및 Radar Path Loss
    alpha_si = 10**(-cfg.omt_iso_db / 20.0)
    beta_echo = 10**(-cfg.path_loss_db / 20.0)
    delay_samp = int(cfg.delay_ns * 1e-9 * fs)
    
    v_si = v_pa_out * alpha_si if cfg.si_enable else np.zeros_like(v_pa_out)
    v_echo = np.zeros_like(v_pa_out)
    # [수정] RF 반송파에 의한 초고주파 위상 지연(Carrier Phase Shift) 현상 물리적 반영
    omega_c_tau = 2.0 * np.pi * (cfg.rf_carrier_ghz * 1e9) * (cfg.delay_ns * 1e-9)
    if delay_samp > 0: 
        v_echo[delay_samp:] = v_pa_out[:-delay_samp] * beta_echo * np.exp(-1j * omega_c_tau)
    else: 
        v_echo = v_pa_out * beta_echo * np.exp(-1j * omega_c_tau)
    
    # LNA 모델: gain + NF 기반 등가 열잡음
    v_lna_in = v_si + v_echo
    lna_gain_lin = 10 ** (cfg.lna_gain_db / 20.0)
    v_lna_sig = v_lna_in * lna_gain_lin
    n_in_dbm = -174.0 + 10 * np.log10(fs) + cfg.lna_nf_db
    n_out_w = 10 ** ((n_in_dbm + cfg.lna_gain_db - 30.0) / 10.0)
    n_out_vrms2 = n_out_w * 50.0
    awgn_lna = np.sqrt(n_out_vrms2 / 2.0) * (np.random.randn(total_samples) + 1j * np.random.randn(total_samples))
    v_rx_in = v_lna_sig + awgn_lna
    
    # 6. 수신 검파
    if cfg.rx_mode == "ZBD":
        p_inst_w = (np.abs(v_rx_in) ** 2) / 50.0
        v_det = cfg.zbd_responsivity_vpw * p_inst_w
        nep_w_sqrt_hz = cfg.zbd_nep_pw_sqrt_hz * 1e-12
        v_nep_rms = cfg.zbd_responsivity_vpw * nep_w_sqrt_hz * np.sqrt(fs / 2.0)
        v_det += np.random.normal(0.0, v_nep_rms, total_samples)
        v_rec = v_det - np.mean(v_det)
    else:
        v_mix_in = v_rx_in - v_si * lna_gain_lin
        v_rec = np.real(v_mix_in)

    # 6-2. IF Amp & Bandpass Filter (SSBI 억제 및 DSO 입력단 증폭)
    N_f = len(v_rec)
    f_axis = np.fft.fftfreq(N_f, 1/fs)
    bw_margin = (cfg.baud_gbaud / 2.0) + cfg.chirp_bw_ghz + 1.0 # 1GHz 마진
    
    # IF 대역통과 필터 (DC 기저대역 SSBI 및 20GHz 고조파 SSBI 완벽 제거)
    if_mask = (np.abs(f_axis) > (cfg.if_ghz - bw_margin)*1e9) & (np.abs(f_axis) < (cfg.if_ghz + bw_margin)*1e9)
    v_rec_filt = np.real(np.fft.ifft(np.fft.fft(v_rec) * if_mask))
    
    # IF Amp 증폭 및 잡음 추가
    if_gain_lin = 10**(cfg.if_amp_gain_db / 20.0)
    v_rec_amp = v_rec_filt * if_gain_lin
    n_if_w = 10**((-174.0 + 10*np.log10(fs) + cfg.if_amp_nf_db + cfg.if_amp_gain_db - 30.0) / 10.0)
    v_dso_in = v_rec_amp + np.sqrt(n_if_w * 50.0 / 2.0) * np.random.randn(N_f)
    
    v_rec = v_dso_in # 플롯 및 상호상관을 위해 교체
    v_demod = hilbert(v_dso_in) if cfg.rx_mode == "Mixer" else v_dso_in.astype(np.complex128)

    # 7. Range Profile & Delay Estimation
    if cfg.rx_mode == "ZBD":
        # ZBD destroys RF phase. Must correlate intensity envelopes!
        ref_sig = np.abs(v_pa_out)**2
        ref_sig = ref_sig - np.mean(ref_sig)
        
        # 기준 신호(Reference)도 동일하게 IF BPF 및 Amp Gain 통과
        ref_sig_filt = np.real(np.fft.ifft(np.fft.fft(ref_sig) * if_mask)) * if_gain_lin
        
        # Apply Digital Self-Interference Cancellation (SIC) for ZBD
        if cfg.si_enable:
            v_si_zbd_raw = cfg.zbd_responsivity_vpw * (np.abs(v_si * lna_gain_lin)**2) / 50.0
            v_si_zbd = v_si_zbd_raw - np.mean(v_si_zbd_raw)
            v_si_zbd = np.real(np.fft.ifft(np.fft.fft(v_si_zbd_raw) * if_mask)) * if_gain_lin
            radar_input = v_dso_in - v_si_zbd
        else:
            radar_input = v_dso_in
            
        ref_sig = ref_sig_filt
    else:
        # Mixer is coherent. Correlate complex RF envelopes.
        ref_sig = v_pa_out
        radar_input = v_dso_in

    N = len(radar_input)
    N_fft = 1
    while N_fft < 2 * N: N_fft *= 2
        
    tx_fft = np.fft.fft(ref_sig, N_fft)
    rx_fft = np.fft.fft(radar_input, N_fft)
    sync_corr = np.abs(np.fft.ifft(rx_fft * np.conj(tx_fft)))[:N]
    
    best_delay = int(np.argmax(sync_corr))
    
    if cfg.si_enable:
        demod_delay = 0  # Dominant signal is SI
    else:
        demod_delay = best_delay  # Dominant signal is Echo
    
    corr_db = 20.0 * np.log10(sync_corr + 1e-20)
    corr_db = corr_db - np.max(corr_db)
    
    range_axis = np.arange(N) * (3e8 / 2.0 / fs)
    valid_range = range_axis <= max(20.0, float(cfg.target_dist_m) * 2.5)
    range_axis = range_axis[valid_range]
    range_profile_db = corr_db[valid_range]

    # 8. Remote Comm Receiver (1-way Comm Path + DSP)
    # 레이더 Path Loss와 다른 1-way Friis 전송 손실 계산
    d = cfg.target_dist_m
    lam = 3e8 / (cfg.rf_carrier_ghz * 1e9)
    g_lin = 10 ** (cfg.ant_gain_dbi / 10.0)
    loss_com_lin = ((4 * np.pi) ** 2 * d ** 2) / (g_lin ** 2 * lam ** 2)
    path_loss_com_db = 10 * np.log10(loss_com_lin + 1e-30)
    beta_com = 10**(-path_loss_com_db / 20.0)
    delay_samp_com = int((d / 3e8 * 1e9) * 1e-9 * fs)
    
    v_com = np.zeros_like(v_pa_out)
    omega_c_tau_com = 2.0 * np.pi * (cfg.rf_carrier_ghz * 1e9) * (d / 3e8)
    if delay_samp_com > 0: 
        v_com[delay_samp_com:] = v_pa_out[:-delay_samp_com] * beta_com * np.exp(-1j * omega_c_tau_com)
    else: 
        v_com = v_pa_out * beta_com * np.exp(-1j * omega_c_tau_com)
        
    v_lna_sig_com = v_com * lna_gain_lin
    awgn_lna_com = np.sqrt(n_out_vrms2 / 2.0) * (np.random.randn(total_samples) + 1j * np.random.randn(total_samples))
    v_rx_in_com = v_lna_sig_com + awgn_lna_com
    
    if cfg.rx_mode == "ZBD":
        p_inst_w_com = (np.abs(v_rx_in_com) ** 2) / 50.0
        v_det_com = cfg.zbd_responsivity_vpw * p_inst_w_com
        v_det_com += np.random.normal(0.0, v_nep_rms, total_samples)
        v_rec_com = v_det_com - np.mean(v_det_com)
    else:
        # 원격 수신기는 로컬 LO와 무관한 독립적인 위상 잡음(Free-running) 발생
        lw_remote = cfg.linewidth_mhz * 1e6
        phi_remote = generate_phase_noise(total_samples, lw_remote, fs)
        wander_remote = np.cumsum(np.random.randn(total_samples))
        wander_remote = (wander_remote - np.mean(wander_remote)) / (np.std(wander_remote) + 1e-12) * (cfg.carrier_wander_mhz * 1e6 if cfg.carrier_wander_enable else 0)
        phi_remote_total = phi_remote + 2 * np.pi * np.cumsum(wander_remote) / fs
        v_mix_in_com = v_rx_in_com * np.exp(-1j * phi_remote_total)
        v_rec_com = np.real(v_mix_in_com)

    v_rec_filt_com = np.real(np.fft.ifft(np.fft.fft(v_rec_com) * if_mask))
    v_dso_in_com = v_rec_filt_com * if_gain_lin + np.sqrt(n_if_w * 50.0 / 2.0) * np.random.randn(N_f)
    v_demod_com = hilbert(v_dso_in_com) if cfg.rx_mode == "Mixer" else v_dso_in_com.astype(np.complex128)

    # 9. Demodulation (Remote Comm)
    lo_if = np.exp(-1j * 2 * np.pi * f_if * t)
    rx_bb_raw = v_demod_com * lo_if
    demod_delay = delay_samp_com
    
    evm_db, ser = float('nan'), float('nan')
    best_eq, best_tx, best_idx = None, None, None
    sym_eq = np.zeros(0, dtype=np.complex128)
    sym_tx = np.zeros(0, dtype=np.complex128)
    best_metric = np.inf

    if cfg.waveform == "OFDM-16QAM":
        lag_candidates = range(max(0, demod_delay - 5), demod_delay + 5)
        for lag in lag_candidates:
            temp_eq, temp_tx, temp_idx = [], [], []
            H_chan = None
            
            for i in range(num_ofdm_syms):
                start_idx = i * N_sym_total + lag
                if start_idx + N_sym_total > len(rx_bb_raw): break
                
                y_t = rx_bb_raw[start_idx + N_cp : start_idx + N_sym_total]
                if len(y_t) < N_fft_ofdm: break
                
                Y = np.fft.fftshift(np.fft.fft(y_t) / np.sqrt(N_fft_ofdm))
                start_sc = N_fft_ofdm//2 - active_sc//2
                rx_syms = Y[start_sc : start_sc + active_sc]
                tx_ref = tx_ofdm_syms[i]
                
                if H_chan is None:
                    # Symbol 0 as Preamble for Zero-Forcing Equalization
                    H_chan = rx_syms / (tx_ref + 1e-15)
                    H_chan = np.convolve(H_chan, np.ones(5)/5, mode='same') # Smooth
                else:
                    eq_syms = rx_syms / (H_chan + 1e-15)
                    # [DSP] OFDM CPE(Common Phase Error) 추적 및 보상 (위상 잡음 대응)
                    cpe = np.mean(eq_syms * np.conj(tx_ref))
                    eq_syms = eq_syms * np.exp(-1j * np.angle(cpe))
                    temp_eq.append(eq_syms)
                    temp_tx.append(tx_ref)
                    temp_idx.append(sym_idx_list[i])
            
            if temp_eq:
                teq = np.concatenate(temp_eq)
                ttx = np.concatenate(temp_tx)
                tidx = np.concatenate(temp_idx)
                nmse = np.mean(np.abs(teq - ttx)**2) / (np.mean(np.abs(ttx)**2) + 1e-15)
                if nmse < best_metric:
                    best_metric = nmse
                    best_eq, best_tx, best_idx = teq, ttx, tidx

    else:
        # QAM / LFM-QAM processing
        if cfg.waveform == "LFM-16QAM":
            local_chirp = np.zeros_like(chirp)
            if demod_delay > 0:
                local_chirp[demod_delay:] = chirp[:-demod_delay]
            else:
                local_chirp = chirp
            rx_bb_raw = rx_bb_raw * np.conj(local_chirp)
            
        rx_bb = np.convolve(rx_bb_raw, h_rrc, mode="same")

        delay_sym = int(round(demod_delay / max(samples_per_sym, 1)))
        lag_candidates = {max(delay_sym + d, 0) for d in range(-2, 3)}
        train_len = 2048

        for off in range(samples_per_sym):
            sym_stream = rx_bb[off::samples_per_sym]
            for lag in sorted(lag_candidates):
                if lag >= len(sym_stream): continue
                m = min(len(sym_stream) - lag, len(symbols))
                if m < 200: continue

                sym_rx = sym_stream[lag:lag + m]
                tx_ref = symbols[:m]

                g0 = 50
                g1 = min(m - 50, g0 + train_len)
                if g1 <= g0: continue

                if cfg.rx_mode == "Mixer":
                    # [DSP] Carrier wander & Phase noise tracking (Data-aided)
                    ph = np.unwrap(np.angle(sym_rx * np.conj(tx_ref) + 1e-15))
                    ph_s = np.convolve(ph, np.ones(11)/11, mode="same")
                    sym_rx = sym_rx * np.exp(-1j * ph_s)
                    
                    r_fit = sym_rx[g0:g1]
                    t_fit = tx_ref[g0:g1]
                    A = np.column_stack((r_fit, np.conj(r_fit)))
                    coef, _, _, _ = np.linalg.lstsq(A, t_fit, rcond=None)
                    eq_all = coef[0] * sym_rx + coef[1] * np.conj(sym_rx)
                else:
                    r_fit = sym_rx[g0:g1]
                    t_fit = tx_ref[g0:g1]
                    a = np.vdot(r_fit, t_fit) / (np.vdot(r_fit, r_fit) + 1e-15)
                    eq_all = a * sym_rx

                err = eq_all[g0:g1] - t_fit
                nmse = np.mean(np.abs(err) ** 2) / (np.mean(np.abs(t_fit) ** 2) + 1e-15)
                if nmse < best_metric:
                    best_metric = nmse
                    best_eq, best_tx, best_idx = eq_all, tx_ref, sym_idx[:m]

    if best_eq is not None:
        sym_eq, sym_tx = best_eq, best_tx
        evm = np.sqrt(best_metric)
        evm_db = 20 * np.log10(evm + 1e-15)
        rx_idx = qam16_hard_demod(sym_eq)
        ser = float(np.mean(best_idx != rx_idx))

    return {
        "fs": fs, "rf_c": cfg.rf_carrier_ghz * 1e9, "step": step, "frame_len": frame_len, "num_frames": num_frames,
        "e_data": e_data, "e_lo": e_lo, "v_pa_out": v_pa_out, 
        "v_rx_in_rad": v_rx_in, "v_si": v_si, "v_echo": v_echo, "v_rec_com": v_dso_in_com,
        "sym_tx": sym_tx, "sym_eq": sym_eq, "evm_db": evm_db, "ser": ser,
        "range_axis_m": range_axis, "range_profile_db": range_profile_db
    }

class ISACGui:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("THz ISAC Physics Simulator (Distance & Power Calcs)")
        self.root.geometry("1500x950")
        self.after_id, self.frame_idx, self.data = None, 0, None
        self.params = {}
        
        self.status_var = tk.StringVar(value="Ready")
        self.demod_var = tk.StringVar()
        self.anim_ms = tk.IntVar(value=100)
        self.carrier_wander_enable_var = tk.BooleanVar(value=True)
        self.si_enable_var = tk.BooleanVar(value=True)
        self.rx_mode_var = tk.StringVar(value="Mixer")
        self.coherence_var = tk.StringVar(value="Free-running")
        
        self._build_ui()
        self._init_plot()
        self._update_table()

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill=tk.BOTH, expand=True)
        left = ttk.Frame(main)
        left.pack(side=tk.LEFT, fill=tk.Y)
        right = ttk.Frame(main)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 0))

        grp = ttk.LabelFrame(left, text="Simulation Parameters", padding=8)
        grp.pack(fill=tk.X)
        
        def add_p(row, key, label, val):
            ttk.Label(grp, text=label).grid(row=row, column=0, sticky="w", pady=2)
            self.params[key] = tk.StringVar(value=val)
            e = ttk.Entry(grp, textvariable=self.params[key], width=10)
            e.grid(row=row, column=1, sticky="w")
            return e

        add_p(0, "fs_gsps", "Sample Rate [GS/s]", "100")
        add_p(1, "linewidth_mhz", "Laser Linewidth [MHz]", "0.1")
        add_p(2, "baud_gbaud", "Baud Rate [Gbaud]", "10")
        add_p(3, "if_ghz", "IF Freq [GHz]", "10")
        ttk.Label(grp, text="TX Waveform").grid(row=4, column=0, sticky="w", pady=2)
        self.waveform_var = tk.StringVar(value="16QAM")
        ttk.Combobox(grp, textvariable=self.waveform_var, values=["16QAM", "LFM-16QAM", "OFDM-16QAM"], width=12, state="readonly").grid(row=4, column=1)
        add_p(5, "chirp_bw_ghz", "Chirp BW [GHz]", "2.0")
        
        ttk.Checkbutton(grp, text="Enable Carrier Wander", variable=self.carrier_wander_enable_var).grid(row=6, column=0, columnspan=2, sticky="w", pady=4)
        ttk.Checkbutton(grp, text="Enable SI Leakage", variable=self.si_enable_var).grid(row=7, column=0, columnspan=2, sticky="w", pady=2)
        ttk.Label(grp, text="Coherence Mode").grid(row=8, column=0, sticky="w", pady=2)
        ttk.Combobox(grp, textvariable=self.coherence_var, values=["Free-running", "Self-coherent"], width=12).grid(row=8, column=1)
        ttk.Label(grp, text="RX Front-end").grid(row=9, column=0, sticky="w", pady=2)
        ttk.Combobox(grp, textvariable=self.rx_mode_var, values=["Mixer", "ZBD"], width=12).grid(row=9, column=1)
        
        ttk.Separator(grp, orient="horizontal").grid(row=10, column=0, columnspan=2, sticky="ew", pady=5)
        add_p(11, "utcpd_dbm", "UTC-PD Output [dBm]", "-25.0")
        add_p(12, "pa_gain_db", "THz PA Gain [dB]", "24.0")
        add_p(13, "pa_p1db_dbm", "PA P1dB Out [dBm]", "-1.0")
        add_p(14, "lna_gain_db", "LNA Gain [dB]", "14.0")
        add_p(15, "lna_nf_db", "LNA NF [dB]", "8.0")
        add_p(16, "zbd_resp_vpw", "ZBD Resp. [V/W]", "2200")
        add_p(17, "zbd_nep_pw", "ZBD NEP [pW/sqrtHz]", "12")
        add_p(18, "if_amp_gain_db", "IF Amp Gain [dB]", "20.0")
        add_p(19, "if_amp_nf_db", "IF Amp NF [dB]", "5.0")
        add_p(20, "dso_noise_dbm", "DSO Noise [dBm]", "-50.0")
        add_p(21, "ant_gain_dbi", "Antenna Gain [dBi]", "25.0")
        add_p(22, "omt_iso_db", "OMT Isolation [dB]", "25.0")
        add_p(23, "rcs_sqm", "Target RCS [m²]", "1.0")
        
        ttk.Label(grp, text="Target Dist [m]").grid(row=24, column=0, sticky="w", pady=2)
        self.params["target_dist_m"] = tk.StringVar(value="1.0")
        self.params["target_dist_m"].trace_add("write", self._update_table)
        ttk.Entry(grp, textvariable=self.params["target_dist_m"], width=10).grid(row=24, column=1, sticky="w")

        # 실시간 계산 테이블
        tf = ttk.LabelFrame(left, text="Calculated Physics Parameters", padding=5)
        tf.pack(fill=tk.X, pady=10)
        self.table = ttk.Treeview(tf, columns=("Value", "Unit"), show="tree headings", height=15)
        self.table.heading("#0", text="Parameter"); self.table.heading("Value", text="Value"); self.table.heading("Unit", text="Unit")
        self.table.column("#0", width=120); self.table.column("Value", width=60, anchor="center"); self.table.column("Unit", width=40, anchor="center")
        self.table.pack(fill=tk.X)
        self.rows = {
            "tx": self.table.insert("", "end", text="Antenna TX Power", values=("0.00", "dBm")),
            "delay": self.table.insert("", "end", text="Radar Echo Delay", values=("0.00", "ns")),
            "loss": self.table.insert("", "end", text="Radar Path Loss", values=("0.00", "dB")),
            "echo": self.table.insert("", "end", text="Radar Echo Power", values=("0.00", "dBm")),
            "si": self.table.insert("", "end", text="Local SI Power", values=("0.00", "dBm")),
            "lna": self.table.insert("", "end", text="LNA Out (Sig)", values=("0.00", "dBm")),
            "lna_total": self.table.insert("", "end", text="LNA Out (Total)", values=("0.00", "dBm")),
            "noise": self.table.insert("", "end", text="LNA Noise", values=("0.00", "dBm")),
            "zbd": self.table.insert("", "end", text="ZBD Noise", values=("0.00", "V")),
            "sinr": self.table.insert("", "end", text="Radar SINR", values=("0.00", "dB")),
            "comm_loss": self.table.insert("", "end", text="Comm Path Loss", values=("0.00", "dB")),
            "comm_rx": self.table.insert("", "end", text="Comm Rx Power", values=("0.00", "dBm")),
            "comm_snr": self.table.insert("", "end", text="Comm SNR", values=("0.00", "dB")),
            "evm_est": self.table.insert("", "end", text="Comm EVM", values=("N/A", "dB")),
            "evm_pct": self.table.insert("", "end", text="Comm EVM", values=("N/A", "%")),
        }

        ctrl = ttk.LabelFrame(left, text="Control", padding=8)
        ctrl.pack(fill=tk.X)
        ttk.Button(ctrl, text="1. Run Simulation", command=self.run_simulation).pack(fill=tk.X)
        ttk.Button(ctrl, text="2. Start Animation", command=self.start_animation).pack(fill=tk.X, pady=4)
        ttk.Button(ctrl, text="3. Stop Animation", command=self.stop_animation).pack(fill=tk.X, pady=4)

        self.fig = Figure(figsize=(10.5, 7.2), dpi=100)
        self.canvas = FigureCanvasTkAgg(self.fig, master=right)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        ttk.Label(right, textvariable=self.demod_var, foreground="#114488", font=("Arial", 12, "bold")).pack(pady=5)

    def _update_table(self, *args):
        try:
            d = float(self.params["target_dist_m"].get())
            tx_raw_dbm = float(self.params['utcpd_dbm'].get()) + float(self.params['pa_gain_db'].get())
            pa_p1db = float(self.params['pa_p1db_dbm'].get())
            tx_dbm = min(tx_raw_dbm, pa_p1db)
            delay_ns = (2.0 * d) / 3e8 * 1e9
            
            lam = 3e8 / 270e9
            g_lin = 10**(float(self.params["ant_gain_dbi"].get()) / 10.0)
            rcs = float(self.params["rcs_sqm"].get())
            loss_lin = ((4*np.pi)**3 * d**4) / (g_lin**2 * lam**2 * rcs)
            loss_db = 10 * np.log10(loss_lin + 1e-30)
            
            echo_dbm = tx_dbm - loss_db
            si_enable = bool(self.si_enable_var.get())
            si_dbm = tx_dbm - float(self.params["omt_iso_db"].get()) if si_enable else -300.0
            lna_out_dbm = max(echo_dbm, si_dbm) + float(self.params["lna_gain_db"].get())
            lna_noise_dbm = -174.0 + 10 * np.log10(float(self.params["fs_gsps"].get()) * 1e9) + float(self.params["lna_nf_db"].get()) + float(self.params["lna_gain_db"].get())
            zbd_noise_v = float(self.params["zbd_resp_vpw"].get()) * float(self.params["zbd_nep_pw"].get()) * 1e-12 * np.sqrt(float(self.params["fs_gsps"].get()) * 1e9 / 2.0)

            # Link-budget SINR approximation at LNA output (gain term cancels out).
            p_echo_lin = 10 ** (echo_dbm / 10.0)
            p_si_lin = 10 ** (si_dbm / 10.0)
            p_noise_in_dbm = -174.0 + 10 * np.log10(float(self.params["fs_gsps"].get()) * 1e9) + float(self.params["lna_nf_db"].get())
            p_noise_lin = 10 ** (p_noise_in_dbm / 10.0)
            sinr_lin = p_echo_lin / (p_si_lin + p_noise_lin + 1e-30)
            sinr_db = 10 * np.log10(sinr_lin + 1e-30)

            p_echo_out_lin = p_echo_lin * 10 ** (float(self.params["lna_gain_db"].get()) / 10.0)
            p_si_out_lin = p_si_lin * 10 ** (float(self.params["lna_gain_db"].get()) / 10.0)
            p_noise_out_lin = 10 ** (lna_noise_dbm / 10.0)
            lna_total_dbm = 10 * np.log10(p_echo_out_lin + p_si_out_lin + p_noise_out_lin + 1e-30)

            loss_com_lin = ((4*np.pi)**2 * d**2) / (g_lin**2 * lam**2)
            loss_com_db = 10 * np.log10(loss_com_lin + 1e-30)
            comm_dbm = tx_dbm - loss_com_db
            p_comm_lin = 10 ** (comm_dbm / 10.0)
            com_snr_db = 10 * np.log10(p_comm_lin / (p_noise_lin + 1e-30) + 1e-30)

            # Measured EVM is updated after simulation run.
            
            self.table.item(self.rows["tx"], values=(f"{tx_dbm:.1f}", "dBm"))
            self.table.item(self.rows["delay"], values=(f"{delay_ns:.2f}", "ns"))
            self.table.item(self.rows["loss"], values=(f"{loss_db:.1f}", "dB"))
            self.table.item(self.rows["echo"], values=(f"{echo_dbm:.1f}", "dBm"))
            self.table.item(self.rows["si"], values=((f"{si_dbm:.1f}" if si_enable else "OFF"), ("dBm" if si_enable else "-")))
            self.table.item(self.rows["lna"], values=(f"{lna_out_dbm:.1f}", "dBm"))
            self.table.item(self.rows["lna_total"], values=(f"{lna_total_dbm:.1f}", "dBm"))
            self.table.item(self.rows["noise"], values=(f"{lna_noise_dbm:.1f}", "dBm"))
            self.table.item(self.rows["zbd"], values=(f"{zbd_noise_v:.3e}", "V"))
            self.table.item(self.rows["sinr"], values=(f"{sinr_db:.2f}", "dB"))
            if "comm_loss" in self.rows:
                self.table.item(self.rows["comm_loss"], values=(f"{loss_com_db:.1f}", "dB"))
            if "comm_rx" in self.rows:
                self.table.item(self.rows["comm_rx"], values=(f"{comm_dbm:.1f}", "dBm"))
            if "comm_snr" in self.rows:
                self.table.item(self.rows["comm_snr"], values=(f"{com_snr_db:.2f}", "dB"))
            self.table.item(self.rows["evm_est"], values=("N/A", "dB"))
            self.table.item(self.rows["evm_pct"], values=("N/A", "%"))
        except Exception as e:
            print(f"Update table error: {e}")

    def _cfg_from_ui(self) -> SimConfig:
        cfg = SimConfig(
            fs_gsps=float(self.params["fs_gsps"].get()),
            linewidth_mhz=float(self.params["linewidth_mhz"].get()),
            baud_gbaud=float(self.params["baud_gbaud"].get()),
            if_ghz=float(self.params["if_ghz"].get()),
            rf_carrier_ghz=270.0,
            waveform=self.waveform_var.get().strip(),
            chirp_bw_ghz=max(float(self.params["chirp_bw_ghz"].get()), 0.01),
            coherence_mode=self.coherence_var.get().strip(),
            rx_mode=self.rx_mode_var.get().strip(),
            si_enable=bool(self.si_enable_var.get()),
            carrier_wander_enable=bool(self.carrier_wander_enable_var.get()),
            carrier_wander_mhz=300.0,
            utcpd_target_dbm=float(self.params["utcpd_dbm"].get()),
            pa_gain_db=float(self.params["pa_gain_db"].get()),
            pa_p1db_dbm=float(self.params["pa_p1db_dbm"].get()),
            lna_gain_db=float(self.params["lna_gain_db"].get()),
            lna_nf_db=float(self.params["lna_nf_db"].get()),
            zbd_responsivity_vpw=float(self.params["zbd_resp_vpw"].get()),
            zbd_nep_pw_sqrt_hz=float(self.params["zbd_nep_pw"].get()),
            if_amp_gain_db=float(self.params["if_amp_gain_db"].get()),
            if_amp_nf_db=float(self.params["if_amp_nf_db"].get()),
            omt_iso_db=float(self.params["omt_iso_db"].get()),
            ant_gain_dbi=float(self.params["ant_gain_dbi"].get()),
            target_rcs_sqm=float(self.params["rcs_sqm"].get()),
            target_dist_m=max(float(self.params["target_dist_m"].get()), 0.1),
        )

        cfg.delay_ns = (2.0 * cfg.target_dist_m) / 3e8 * 1e9
        cfg.path_loss_db = 10 * np.log10(((4 * np.pi) ** 3 * cfg.target_dist_m ** 4) / ((10 ** (cfg.ant_gain_dbi / 10.0)) ** 2 * (3e8 / (cfg.rf_carrier_ghz * 1e9)) ** 2 * max(cfg.target_rcs_sqm, 1e-6)) + 1e-30)
        cfg.tx_power_dbm = cfg.utcpd_target_dbm + cfg.pa_gain_db
        return cfg

    def _init_plot(self):
        self.fig.clear()
        gs = self.fig.add_gridspec(2, 3)
        self.axes = [self.fig.add_subplot(gs[0,0]), self.fig.add_subplot(gs[0,1]), self.fig.add_subplot(gs[1,0]), self.fig.add_subplot(gs[1,1])]
        self.ax_range = self.fig.add_subplot(gs[0,2])
        self.ax_const = self.fig.add_subplot(gs[1,2])
        self.lines = []
        titles = ["1) Opt. Spectrum (MZM & LO)", "2) THz PA Output (TX Antenna)", "3) Local LNA Out (Radar)", "4) Remote IF Amp Out (Comm)"]
        colors = ["purple", "red", "orange", "blue"]
        
        for i, ax in enumerate(self.axes):
            if i == 2:
                line, = ax.plot([], [], lw=1.5, color=colors[i], label="Total")
                self.l_si, = ax.plot([], [], lw=1.2, color="green", linestyle="--", label="SI")
                self.l_echo, = ax.plot([], [], lw=1.2, color="magenta", linestyle=":", label="Echo")
                ax.legend(loc="upper right", fontsize=8)
            else:
                line, = ax.plot([], [], lw=1.5, color=colors[i], label="Signal")
                ax.legend(loc="upper right", fontsize=8)
            self.lines.append(line)
            ax.set_title(titles[i])
            ax.grid(True, alpha=0.45)
            ax.set_ylabel("PSD [dBm/Hz]")
            
        self.l_lo, = self.axes[0].plot([], [], lw=1.2, color="black", label="Opt. LO")
        self.axes[0].legend(loc="upper right", fontsize=8)
        self.ax_range.set_title("5) Range Profile")
        self.ax_range.set_xlabel("Range [m]")
        self.ax_range.set_ylabel("Magnitude [dB]")
        self.ax_range.grid(True, alpha=0.45)
        self.ax_range.set_xlim(0, 10)

        self.ax_const.set_title("6) 16-QAM Constellation")
        self.ax_const.set_xlim(-1.8, 1.8); self.ax_const.set_ylim(-1.8, 1.8)
        self.ax_const.grid(True, alpha=0.45)
        self.fig.tight_layout()

    def run_simulation(self) -> None:
        try:
            self.stop_animation()
            self._update_table()  # 레이더 파라미터 테이블 갱신
            cfg = self._cfg_from_ui()
            
            # 시뮬레이션 백엔드 실행
            self.data = run_isac_sim(cfg)
            
            # ─────────────────────────────────────────────────────────
            # 1. X축 범위 완벽 자동화 (주파수 대역 기반)
            # ─────────────────────────────────────────────────────────
            c = cfg.rf_carrier_ghz
            # IF 주파수와 데이터 레이트(Baud)를 합쳐 여유있는 Span 계산
            span = cfg.if_ghz + (cfg.baud_gbaud / 2.0) + 5.0
            
            # 광 스펙트럼: Data(193.4 THz)부터 LO 반송파(193.4 + c THz)까지 동적 조절
            self.axes[0].set_xlim(193.35, 193.40 + (c / 1000.0) + 0.05)
            self.axes[1].set_xlim(c - span, c + span)
            self.axes[2].set_xlim(c - span, c + span)
            self.axes[3].set_xlim(0.0, span)

            # ─────────────────────────────────────────────────────────
            # 2. Y축 고정: 링크버짓 기반 절대 전력 레벨로 설정
            # ─────────────────────────────────────────────────────────
            fs = self.data["fs"]
            bw_db = 10 * np.log10(fs)
            p_pa_dbm = min(cfg.utcpd_target_dbm + cfg.pa_gain_db, cfg.pa_p1db_dbm)
            p_si_dbm = p_pa_dbm - cfg.omt_iso_db
            p_echo_dbm = p_pa_dbm - cfg.path_loss_db
            p_lna_sig_dbm = max(p_si_dbm, p_echo_dbm) + cfg.lna_gain_db
            p_lna_noise_dbm = -174.0 + bw_db + cfg.lna_nf_db + cfg.lna_gain_db

            # PSD( dBm/Hz ) 축으로 변환 시 대역폭 항 제거
            pa_psd_dbmhz = p_pa_dbm - bw_db
            lna_sig_psd_dbmhz = p_lna_sig_dbm - bw_db
            lna_noise_psd_dbmhz = p_lna_noise_dbm - bw_db

            self.axes[0].set_ylim(pa_psd_dbmhz - 80, pa_psd_dbmhz + 20)
            self.axes[1].set_ylim(pa_psd_dbmhz - 80, pa_psd_dbmhz + 20)
            self.axes[2].set_ylim(lna_noise_psd_dbmhz - 10, lna_sig_psd_dbmhz + 20)
            self.axes[3].set_ylim(lna_noise_psd_dbmhz - 20, lna_sig_psd_dbmhz + 20)

            # ─────────────────────────────────────────────────────────
            # 3. Constellation 그래프 자동 스케일링 및 업데이트
            # ─────────────────────────────────────────────────────────
            self.ax_const.cla()
            self.ax_const.set_title("6) Constellation (16-QAM)")
            self.ax_const.grid(True, alpha=0.45)
            
            sym_eq = np.asarray(self.data.get("sym_eq", []))
            sym_tx = np.asarray(self.data.get("sym_tx", []))
            
            if len(sym_eq) > 0: 
                self.ax_const.scatter(np.real(sym_eq[:2000]), np.imag(sym_eq[:2000]), s=8, alpha=0.6)
            if len(sym_tx) > 0: 
                self.ax_const.scatter(np.real(sym_tx[:2000]), np.imag(sym_tx[:2000]), s=22, marker="x", color="red")
            
            # 사용자가 요청한 고정 크기 [-1.5, 1.5]
            self.ax_const.set_xlim(-1.5, 1.5)
            self.ax_const.set_ylim(-1.5, 1.5)
            self.ax_const.set_aspect("equal", adjustable="box")

            # 결과 수치 표기
            evm_db = float(self.data.get("evm_db", float('nan')))
            ser = float(self.data.get("ser", float('nan')))
            
            if np.isfinite(evm_db):
                self.demod_var.set(f"16-QAM Demod: EVM={evm_db:.1f} dB | SER={ser:.4f}")
                evm_pct = estimate_measured_evm_percent(evm_db)
                self.table.item(self.rows["evm_est"], values=(f"{evm_db:.2f}", "dB"))
                self.table.item(self.rows["evm_pct"], values=(f"{evm_pct:.2f}", "%"))
            else:
                self.demod_var.set(f"Comm Demod: N/A ({cfg.rx_mode})")
                self.table.item(self.rows["evm_est"], values=("N/A", "dB"))
                self.table.item(self.rows["evm_pct"], values=("N/A", "%"))

            self._update_range_profile()

            self.frame_idx = 0
            self._update_frame()

        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _update_range_profile(self):
        if not self.data:
            return
        self.ax_range.cla()
        self.ax_range.set_title("5) Range Profile")
        self.ax_range.set_xlabel("Range [m]")
        self.ax_range.set_ylabel("Magnitude [dB]")
        self.ax_range.grid(True, alpha=0.45)

        rng = np.asarray(self.data.get("range_axis_m", []))
        prof = np.asarray(self.data.get("range_profile_db", []))
        if len(rng) > 0:
            max_range = max(10.0, float(np.max(rng)))
            m = rng <= max_range
            self.ax_range.plot(rng[m], prof[m], color="teal", lw=1.3)
            self.ax_range.set_xlim(0.0, max_range)
            max_prof = np.max(prof[m]) if np.any(m) else 0.0
            self.ax_range.set_ylim(-40.0, max_prof + 10.0)
            
    def _update_frame(self):
        if not self.data: return
        fs, rf_c, step, flen = self.data["fs"], self.data["rf_c"], self.data["step"], self.data["frame_len"]
        s, e = self.frame_idx * step, self.frame_idx * step + flen

        # Plot 1: Optical
        f, p_mzm = calc_psd(self.data["e_data"][s:e], fs)
        _, p_lo = calc_psd(self.data["e_lo"][s:e], fs)
        self.lines[0].set_data((f + 193.4e12)/1e12, p_mzm)
        self.l_lo.set_data((f + 193.4e12 + rf_c)/1e12, p_lo)
        
        # Plot 2: PA Output
        f, p_pa = calc_psd(self.data["v_pa_out"][s:e], fs)
        pwr_tx = calc_power_dbm(self.data["v_pa_out"][s:e])
        self.lines[1].set_data((f + rf_c)/1e9, p_pa)
        self.lines[1].set_label(f"PA Out ({pwr_tx:.1f} dBm)")
        
        # Plot 3: LNA Output
        f, p_rx = calc_psd(self.data["v_rx_in_rad"][s:e], fs)
        _, p_si = calc_psd(self.data["v_si"][s:e], fs)
        _, p_echo = calc_psd(self.data["v_echo"][s:e], fs)
        self.lines[2].set_data((f + rf_c)/1e9, p_rx)
        self.l_si.set_data((f + rf_c)/1e9, p_si)
        self.l_echo.set_data((f + rf_c)/1e9, p_echo)
        
        pwr_si = calc_power_dbm(self.data["v_si"][s:e])
        pwr_echo = calc_power_dbm(self.data["v_echo"][s:e])
        pwr_total = calc_power_dbm(self.data["v_rx_in_rad"][s:e])
        self.lines[2].set_label(f"Radar Total ({pwr_total:.1f} dBm)")
        self.l_si.set_label(f"SI ({pwr_si:.1f} dBm)")
        self.l_echo.set_label(f"Echo ({pwr_echo:.1f} dBm)")
        self.axes[1].legend(loc="upper right", fontsize=8); self.axes[2].legend(loc="upper right", fontsize=8)

        # Plot 4: Baseband Comm
        f, p_bb = calc_psd(self.data["v_rec_com"][s:e], fs)
        self.lines[3].set_data(f[f>=0]/1e9, p_bb[f>=0])
        self.lines[3].set_label("Remote IF Out")
        self.axes[3].legend(loc="upper right", fontsize=8)

        self.canvas.draw_idle()
        self.frame_idx = (self.frame_idx + 1) % self.data["num_frames"]

    def start_animation(self):
        if not self.data: return
        if not self.after_id: self._schedule_next_frame()

    def _schedule_next_frame(self):
        self._update_frame()
        self.after_id = self.root.after(self.anim_ms.get(), self._schedule_next_frame)

    def stop_animation(self):
        if self.after_id:
            self.root.after_cancel(self.after_id)
            self.after_id = None

if __name__ == "__main__":
    root = tk.Tk()
    app = ISACGui(root)
    root.mainloop()