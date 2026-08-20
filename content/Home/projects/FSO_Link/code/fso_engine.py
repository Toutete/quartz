# fso_engine.py
import numpy as np
from scipy import fft
from scipy.constants import pi

ENGINE_BUILD_TAG = "ssfm-midpoint-gaussian-v6-2026-08-19"

# =============================================================================
# Helper Mathematical Functions
# =============================================================================
def gen_phase_screen_sh(N, D, r0, L0, l0):
    df = 1.0 / D
    # Keep FFT indexing native (DC at [0,0]) to avoid shift/alignment mismatch.
    f_vec = fft.fftfreq(N, D / N)
    Fx, Fy = np.meshgrid(f_vec, f_vec)
    f = np.sqrt(Fx**2 + Fy**2); f[f == 0] = 1e-10
    
    PSD_phi = 0.023 * (r0**(-5./3.)) * (f**2 + (1./L0)**2)**(-11./6.) * np.exp(-(f*l0/5.92)**2)
    # Suppress FFT-corner bins with a soft circular taper to reduce square-grid artifacts.
    f_nyq = 0.5 / (D / N)
    circ_taper = np.exp(-((f / (0.90 * f_nyq + 1e-30))**12))
    PSD_phi = PSD_phi * circ_taper
    PSD_phi[0, 0] = 0
    
    cn = (np.random.randn(N, N) + 1j * np.random.randn(N, N)) / np.sqrt(2)
    # ifft2 includes 1/N^2 normalization, so scale back to preserve screen variance.
    phi_hi = np.real(fft.ifft2(cn * np.sqrt(PSD_phi))) * (N**2 * df)

    phi_lo = np.zeros((N, N))
    x_vec = (np.arange(N) - N // 2) * (D / N)

    # Isotropic subharmonic synthesis: avoid axis-biased 3x3 Cartesian tones.
    n_ang = 12
    for p in range(1, 4):
        D_p = 3**p * D
        f0 = 1.0 / D_p
        for m in range(n_ang):
            theta = (2 * pi * m) / n_ang
            fx_m = f0 * np.cos(theta)
            fy_m = f0 * np.sin(theta)
            f_m = np.sqrt(fx_m**2 + fy_m**2)
            if f_m < 1e-12:
                continue
            psd_m = 0.023 * (r0**(-5./3.)) * (f_m**2 + (1./L0)**2)**(-11./6.) * np.exp(-(f_m*l0/5.92)**2)
            c_m = (np.random.randn() + 1j * np.random.randn()) / np.sqrt(2)
            
            # Massive speedup: Use outer product instead of full 2D exponential meshgrid.
            phase_x = np.exp(1j * 2 * pi * fx_m * x_vec)
            phase_y = np.exp(1j * 2 * pi * fy_m * x_vec)
            plane_wave = np.outer(phase_y, phase_x)
            
            phi_lo += np.real(c_m * np.sqrt(psd_m) * f0 * plane_wave)
    
    phi = fft.fftshift(phi_hi) + phi_lo
    # Remove piston term so each screen has zero-mean phase.
    phi = phi - np.mean(phi)
    return phi

def rrcosfilter(N, alpha, sps_val):
    t = (np.arange(N, dtype=float) - (N - 1) / 2.0) / float(sps_val)
    h = np.zeros(N, dtype=float)

    if alpha < 0 or alpha > 1:
        raise ValueError("alpha must satisfy 0 <= alpha <= 1")

    near_zero = np.isclose(t, 0.0, atol=np.finfo(float).eps * 16)
    h[near_zero] = 1.0 - alpha + (4.0 * alpha / pi)

    if alpha > 0:
        t_sing = 1.0 / (4.0 * alpha)
        # Tie tolerance to sample spacing so behavior is stable across sps.
        sing_tol = 0.5 / max(float(sps_val), 1.0)
        near_sing = np.isclose(np.abs(t), t_sing, atol=sing_tol)
        h[near_sing] = (alpha / np.sqrt(2.0)) * (
            (1.0 + 2.0 / pi) * np.sin(pi / (4.0 * alpha))
            + (1.0 - 2.0 / pi) * np.cos(pi / (4.0 * alpha))
        )
    else:
        near_sing = np.zeros_like(t, dtype=bool)

    regular = ~(near_zero | near_sing)
    if np.any(regular):
        t_r = t[regular]
        num = np.sin(pi * t_r * (1.0 - alpha)) + 4.0 * alpha * t_r * np.cos(pi * t_r * (1.0 + alpha))
        den = pi * t_r * (1.0 - (4.0 * alpha * t_r) ** 2)
        h[regular] = num / den

    return h / np.sqrt(np.sum(h**2) + 1e-30)

# =============================================================================
# [Framework 1] QAM Modem Module
# =============================================================================
class QAM_Modem:
    def __init__(self, M=16):
        self.M = M
        self.ideal_symbols = [
            -3-3j, -3-1j, -3+1j, -3+3j,
            -1-3j, -1-1j, -1+1j, -1+3j,
             1-3j,  1-1j,  1+1j,  1+3j,
             3-3j,  3-1j,  3+1j,  3+3j
        ]
        self.ideal_symbols = np.array(self.ideal_symbols) / np.sqrt(np.mean(np.abs(self.ideal_symbols)**2))
        
    def generate_signal(self, num_symbols):
        return self.ideal_symbols[np.random.randint(0, self.M, num_symbols)]

    def demodulate_and_calc_evm(self, tx_symbols, rx_symbols):
        h_est = np.mean(rx_symbols / tx_symbols)
        if np.abs(h_est) < 1e-10: h_est = 1e-10 + 0j
        rx_eq = rx_symbols / h_est
        evm = np.sqrt(np.mean(np.abs(tx_symbols - rx_eq)**2))
        return rx_eq, evm

    def generate_rf_waveform(self, symbols, phase_offset=0.0):
        sps = 16
        fs = 800e6 * sps
        f_sub = 3e9 
        rrc_taps = rrcosfilter(6 * sps + 1, 0.5, sps)
        baseband = np.zeros(len(symbols) * sps, dtype=complex)
        baseband[::sps] = symbols
        tx_bb = np.convolve(baseband, rrc_taps, 'same')
        t = np.arange(len(tx_bb)) / fs
        rf_sig = np.real(tx_bb * np.exp(1j * (2 * pi * f_sub * t + phase_offset)))
        m_index = 0.4
        return t * 1e9, np.clip(1.0 + m_index * rf_sig, 0, None)

# =============================================================================
# [Framework 2] SSFM Atmospheric Channel Module
# =============================================================================
class SSFM_Channel:
    def __init__(self, params_dict):
        self.N_screens = params_dict['N_screens']
        self.lam = params_dict['lam']
        self.L = params_dict['L']
        self.Cn2 = params_dict['Cn2']
        self.w0 = params_dict['w0']
        self.l0 = params_dict['l0']
        self.L0 = params_dict['L0']
        self.wind_speed = params_dict['wind_speed']
        self.D = params_dict['D_obs']
        self.delta_t = params_dict['delta_t']
        self.n_frames = params_dict['n_frames']
        self.N = int(params_dict.get('N', 128))
        
        self.k0 = 2 * pi / self.lam
        self.dz = self.L / self.N_screens
        self.dx = self.D / self.N
        self.alias_metric = 0.0
        self.substeps_per_screen = 1
        self.fresnel_step_limit = 0.0
        self.phase_cycle_frames = 0
        self._asm_kernel_cache = {}
        self.propagation_mode = "fresnel"
        self.px_per_w0 = np.nan
        self.n_required_w0_8px = 0
        self.used_analytic_initial_gaussian = False

    def _phase_slice_periodic(self, phi_large, row_start, col_start):
        rows = np.arange(row_start, row_start + self.N) % phi_large.shape[0]
        cols = np.arange(col_start, col_start + self.N) % phi_large.shape[1]
        return np.take(np.take(phi_large, rows, axis=0), cols, axis=1)

    def _propagate_fresnel_step(self, field, H_prop_step):
        U_spec = fft.fft2(field)
        return fft.ifft2(U_spec * H_prop_step)

    def _get_asm_kernel(self, n_pad, dz, anti_alias_mask, start, end):
        key = (n_pad, round(dz, 12), round(self.dx, 15), round(self.k0, 12))
        if key in self._asm_kernel_cache:
            return self._asm_kernel_cache[key]

        f_pad = fft.fftfreq(n_pad, self.dx)
        Fx_pad, Fy_pad = np.meshgrid(f_pad, f_pad)
        kx = 2.0 * pi * Fx_pad
        ky = 2.0 * pi * Fy_pad
        kz_sq = np.maximum(0.0, self.k0**2 - kx**2 - ky**2)
        kz = np.sqrt(kz_sq)

        anti_alias_pad = np.zeros((n_pad, n_pad), dtype=float)
        anti_alias_pad[start:end, start:end] = anti_alias_mask
        H_asm = np.exp(1j * dz * kz) * anti_alias_pad
        self._asm_kernel_cache[key] = H_asm
        return H_asm

    def _propagate_asm_step_padded(self, field, dz, anti_alias_mask, pad_factor=2):
        n = field.shape[0]
        n_pad = int(2 ** np.ceil(np.log2(max(8, pad_factor * n))))
        start = (n_pad - n) // 2
        end = start + n

        U_pad = np.zeros((n_pad, n_pad), dtype=complex)
        U_pad[start:end, start:end] = field

        H_asm = self._get_asm_kernel(n_pad, dz, anti_alias_mask, start, end)

        U_spec_pad = fft.fft2(U_pad)
        U_prop_pad = fft.ifft2(U_spec_pad * H_asm)
        return U_prop_pad[start:end, start:end]

    def _gaussian_beam_field(self, X, Y, z):
        z_R = pi * self.w0**2 / self.lam
        r2 = X**2 + Y**2
        if abs(z) < 1e-15:
            return np.exp(-r2 / self.w0**2)

        wz = self.w0 * np.sqrt(1.0 + (z / z_R)**2)
        Rz = z * (1.0 + (z_R / z)**2)
        gouy = np.arctan2(z, z_R)
        amp = (self.w0 / wz) * np.exp(-r2 / (wz**2 + 1e-30))
        phase = np.exp(-1j * self.k0 * r2 / (2.0 * Rz + 1e-30)) * np.exp(1j * gouy)
        return amp * phase

    def generate_spatiotemporal_beams(self):
        # Allow GUI to fully control self.D, no hardcoded override.
        beam_spot_theory = self.w0 * np.sqrt(1.0 + (self.lam * self.L / (pi * self.w0**2))**2)
        self.dx = self.D / self.N
        self.required_D = 4.0 * beam_spot_theory
        self.used_D = self.D

        pixel_shift = int(max(1, round(self.wind_speed * self.delta_t / self.dx)))
        N_req = self.N + self.n_frames * pixel_shift
        # Clamp N_large to prevent memory explosion/slowdowns
        N_large = min(4096, 2**(int(np.ceil(np.log2(N_req)))))

        if self.Cn2 > 0:
            r0_dz = (0.423 * (self.k0**2) * self.Cn2 * self.dz)**(-3.0/5.0)
        else:
            r0_dz = np.inf
        phi_large_all = np.zeros((self.N_screens, N_large, N_large))
        if self.Cn2 > 0:
            for i in range(self.N_screens):
                phi_large_all[i] = gen_phase_screen_sh(N_large, self.dx*N_large, r0_dz, self.L0, self.l0)

        x_arr = (np.arange(self.N) - self.N // 2) * self.dx
        X, Y = np.meshgrid(x_arr, x_arr)
        self.px_per_w0 = self.w0 / max(self.dx, 1e-30)
        self.n_required_w0_8px = int(2 ** np.ceil(np.log2(max(64, np.ceil(self.D / (self.w0 / 8.0))))))

        # The GUI often uses a wide receiver-plane grid.  A millimeter-class
        # transmitter waist can then be sub-pixel at z=0, which makes the
        # source field numerically misleading.  Start from the analytic
        # Gaussian field at the first midpoint screen instead.
        z_first_screen = 0.5 * self.dz
        U_start = self._gaussian_beam_field(X, Y, z_first_screen)
        self.used_analytic_initial_gaussian = True

        # Fresnel sampling diagnostic (user-facing): aliasing risk grows as this exceeds 1.
        self.alias_metric = (self.lam * self.dz) / (self.N * self.dx**2)
        # Strict Fresnel step criterion: keep dz_step below N*dx^2/lambda.
        self.fresnel_step_limit = (self.N * self.dx**2) / self.lam
        substeps_alias = int(max(1, np.ceil(self.alias_metric / 0.5)))
        substeps_fresnel = int(max(1, np.ceil(self.dz / (0.95 * self.fresnel_step_limit + 1e-30))))
        self.substeps_per_screen = max(substeps_alias, substeps_fresnel)
        dz_step = self.dz / self.substeps_per_screen

        # Use native fftfreq ordering and plain fft2/ifft2 to avoid shift-induced center drift.
        f = fft.fftfreq(self.N, self.dx)
        Fx, Fy = np.meshgrid(f, f)
        f_sq = Fx**2 + Fy**2
        f_abs = np.sqrt(f_sq)

        # Circular anti-alias filtering suppresses square-grid corner artifacts.
        # Hard inscribed-disc mask removes corner bins, then soft roll-off reduces ringing.
        f_nyq = 0.5 / self.dx
        f_cut_hard = 0.95 * f_nyq
        f_cut_soft = 0.85 * f_nyq
        hard_mask = (f_abs <= f_cut_hard).astype(float)
        soft_mask = np.exp(-((f_abs / (f_cut_soft + 1e-30))**12))
        anti_alias_mask = hard_mask * soft_mask
        H_prop_step = np.exp(-1j * pi * self.lam * dz_step * f_sq) * anti_alias_mask

        used_asm_any = False

        def propagate_distance(field, distance):
            nonlocal used_asm_any
            if distance <= 0:
                return field
            alias_distance = (self.lam * distance) / (self.N * self.dx**2 + 1e-30)
            steps_alias = int(max(1, np.ceil(alias_distance / 0.5)))
            steps_fresnel = int(max(1, np.ceil(distance / (0.95 * self.fresnel_step_limit + 1e-30))))
            steps = max(steps_alias, steps_fresnel)
            step_distance = distance / steps
            use_asm_step = step_distance > 0.9 * self.fresnel_step_limit
            used_asm_any = used_asm_any or use_asm_step
            H_step = np.exp(-1j * pi * self.lam * step_distance * f_sq) * anti_alias_mask
            out = field
            for _ in range(steps):
                if use_asm_step:
                    out = self._propagate_asm_step_padded(out, step_distance, anti_alias_mask, pad_factor=2)
                else:
                    out = self._propagate_fresnel_step(out, H_step)
            return out

        # Circular absorbing window: preserve energy in most of the pupil
        # and only damp near the outer boundary to reduce wrap-around artifacts.
        r_edge = 0.5 * self.D
        R = np.sqrt(X**2 + Y**2)
        edge_window = np.exp(-((R / (r_edge * 0.95 + 1e-15))**30))

        # Ideal (no-turbulence) receiver field used for phase-aberration display.
        self.U_ideal = self._gaussian_beam_field(X, Y, self.L)

        saved_rx_fields = np.zeros((self.N, self.N, self.n_frames), dtype=complex)
        self.phase_cycle_frames = max(1, N_large // max(pixel_shift, 1))
        
        for t in range(self.n_frames):
            c_idx = (t * pixel_shift) % N_large
            r_idx = (N_large - self.N) // 2
            
            U_rx = U_start.copy()
            for i in range(self.N_screens):
                phi = self._phase_slice_periodic(phi_large_all[i], r_idx, c_idx)
                U_rx = U_rx * np.exp(1j * phi)
                distance_to_next_plane = self.dz if i < self.N_screens - 1 else 0.5 * self.dz
                U_rx = propagate_distance(U_rx, distance_to_next_plane)
                U_rx = U_rx * edge_window
            saved_rx_fields[:,:,t] = U_rx

        self.propagation_mode = "asm-padded" if used_asm_any else "fresnel"
        if self.Cn2 > 0:
            r0_total = (0.423 * (self.k0**2) * self.Cn2 * self.L)**(-3.0/5.0)
        else:
            r0_total = np.inf
        rytov_dz = 1.23 * self.Cn2 * (self.k0**(7.0/6.0)) * (self.dz**(11.0/6.0))
        
        return saved_rx_fields, x_arr, r0_total, rytov_dz

# =============================================================================
# [Framework 3] ROSA Geometric Receiver Array Module (Focal Plane Logic)
# =============================================================================
class Receiver_Array:
    def __init__(self, pd_positions, lens_r, pd_active_r, focal_len, x_arr, lam):
        self.num_pds = len(pd_positions)
        self.pd_active_r = pd_active_r
        self.focal_len = focal_len
        self.lam = lam
        self.N = len(x_arr)
        self.dx = x_arr[1] - x_arr[0]
        self.x_arr = x_arr
        
        # 1. 렌즈(Pupil) 면적 마스크
        X, Y = np.meshgrid(x_arr, x_arr)
        self.lens_masks = []
        for px, py in pd_positions:
            self.lens_masks.append(((X - px)**2 + (Y - py)**2) <= lens_r**2)
            
        # 2. 초점면(Focal Plane) 좌표계 및 고속 PD 수광면적(Active Area) 마스크
        self.du = (self.lam * self.focal_len) / (self.N * self.dx)
        u_arr = np.arange(-self.N/2, self.N/2) * self.du
        U, V = np.meshgrid(u_arr, u_arr)
        self.pd_active_mask = (U**2 + V**2) <= self.pd_active_r**2

        # 3. 렌즈별 ROI를 사전 계산해 전체 N x N FFT 반복을 줄입니다.
        self.pd_rois = []
        for mask in self.lens_masks:
            rows, cols = np.where(mask)
            if len(rows) == 0:
                self.pd_rois.append(None)
                continue

            y0, y1 = rows.min(), rows.max() + 1
            x0, x1 = cols.min(), cols.max() + 1
            roi_h = max(1, y1 - y0)
            roi_w = max(1, x1 - x0)
            n_fft = int(2 ** np.ceil(np.log2(max(8, 2 * max(roi_h, roi_w)))))

            du_local = (self.lam * self.focal_len) / (n_fft * self.dx)
            u_local = np.arange(-n_fft/2, n_fft/2) * du_local
            U_local, V_local = np.meshgrid(u_local, u_local)
            pd_active_mask_local = (U_local**2 + V_local**2) <= self.pd_active_r**2

            self.pd_rois.append({
                'y0': y0,
                'y1': y1,
                'x0': x0,
                'x1': x1,
                'local_mask': mask[y0:y1, x0:x1],
                'n_fft': n_fft,
                'du_local': du_local,
                'pd_active_mask_local': pd_active_mask_local,
            })

    def compute_focal_coupling(self, rx_fields_temporal, normalize=True, return_absolute=False):
        """렌즈로 빛을 모은 뒤 초점면(Focal plane) PD active area에 결합되는 전력을 계산합니다.

        Args:
            rx_fields_temporal: (N, N, T) 복소 수신장
            normalize: True면 채널별 평균 1로 정규화된 trace를 반환
            return_absolute: True면 절대 전력 trace(W 단위로 스케일된 입력장 기준)도 함께 반환
        """
        n_frames = rx_fields_temporal.shape[2]
        traces_abs = [np.zeros(n_frames) for _ in range(self.num_pds)]
        
        for t in range(n_frames):
            U_pupil = rx_fields_temporal[:,:,t]
            for i, roi in enumerate(self.pd_rois):
                if roi is None:
                    continue

                # 렌즈 주변 ROI만 추출해 패딩 FFT 수행
                y0, y1 = roi['y0'], roi['y1']
                x0, x1 = roi['x0'], roi['x1']
                U_patch = U_pupil[y0:y1, x0:x1] * roi['local_mask']

                n_fft = roi['n_fft']
                U_focal = fft.fftshift(fft.fft2(fft.ifftshift(U_patch), s=(n_fft, n_fft))) * (self.dx**2) / (1j * self.lam * self.focal_len)
                I_focal = np.abs(U_focal)**2
                
                # 초소형 고속 PD Active Area 안에 들어온 실제 전력 적분
                coupled_power = np.sum(I_focal[roi['pd_active_mask_local']]) * (roi['du_local']**2)
                traces_abs[i][t] = coupled_power

        # 절대 전력 결합(합산): 다중 개구에서 총 수집 전력 관점 지표
        trace_combined_abs = np.sum(traces_abs, axis=0) if self.num_pds > 0 else np.zeros(n_frames)

        if normalize:
            traces_out = []
            for i in range(self.num_pds):
                traces_out.append(traces_abs[i] / (np.mean(traces_abs[i]) + 1e-15))
            trace_combined_out = np.sum(traces_out, axis=0) / self.num_pds if self.num_pds > 0 else np.zeros(n_frames)
        else:
            traces_out = traces_abs
            trace_combined_out = trace_combined_abs

        if return_absolute:
            return traces_out, trace_combined_out, traces_abs, trace_combined_abs
        return traces_out, trace_combined_out
