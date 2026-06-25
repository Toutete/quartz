import numpy as np
import skrf as rf
import matplotlib.pyplot as plt
from pathlib import Path

def cascade_omts_vdi(S_single, wg_length_mm=None, freq_ghz=None):
    """
    VDI 측정 구조(Rect-Cir-Rect)를 위한 GSM 결합 함수
    S_single: 단일 OMT의 S9P 데이터 (N_freq, 9, 9)
    """
    num_f = S_single.shape[0]
    
    # 인덱스 설정 (요청하신 맵핑)
    # [0,1,2]: Cir 3 (내부) | [3,4,5]: Rect 1 (외부) | [6,7,8]: Rect 2 (외부)
    int_idx = np.array([0, 1, 2])
    ext_idx = np.array([3, 4, 5, 6, 7, 8])
    
    # 1. 단일 소자 행렬 분할
    S_AA = S_single[:, ext_idx[:, None], ext_idx]
    S_AB = S_single[:, ext_idx[:, None], int_idx]
    S_BA = S_single[:, int_idx[:, None], ext_idx]
    S_BB = S_single[:, int_idx[:, None], int_idx]
    
    # 2. 중간 원형 도파관 효과 (Phase Shift) 추가
    # 별도의 S-parameter 파일이 없다면 위상 천이 행렬 생성
    if wg_length_mm is not None and freq_ghz is not None:
        # 270GHz 대역 TE11 모드의 위상 정수 계산 (간략화)
        c = 299792458
        fc = 175e9 # 원형 도파관 TE11 Cutoff 예시
        beta = 2 * np.pi * (freq_ghz * 1e9) / c * np.sqrt(1 - (fc/(freq_ghz*1e9))**2)
        phi = np.exp(-1j * beta * (wg_length_mm / 1000))
        
        # 중간 도파관 S-행렬 (2포트 멀티모드)
        T_WG = np.zeros((num_f, 3, 3), dtype=complex)
        for i in range(3): T_WG[:, i, i] = phi
    else:
        T_WG = np.repeat(np.eye(3, dtype=complex)[None, :, :], num_f, axis=0) # 거리 0인 경우
    
    # 3. GSM 결합 수식 (Redheffer Star Product)
    I = np.eye(3).reshape(1, 3, 3)
    # OMT_A와 OMT_B(동일소자) 결합
    Gamma = np.linalg.inv(I - S_BB @ T_WG @ S_BB @ T_WG)
    
    # 송신측(OMT A) 외부포트 -> 수신측(OMT B) 외부포트 전송
    S21_sys = S_AB @ T_WG @ Gamma @ S_BA 
    # 송신측(OMT A) 외부포트에서 본 입력 반사(리턴로스/동측 아이솔레이션 계산에 사용)
    S11_sys = S_AA + S_AB @ T_WG @ Gamma @ S_BB @ T_WG @ S_BA
    
    return S21_sys, S11_sys

def db20(x, floor_db=-140.0):
    mag = np.maximum(np.abs(x), 10 ** (floor_db / 20.0))
    return 20.0 * np.log10(mag)


def interp_measured_to_pred(freq_pred_ghz, ntw_meas, out_port, in_port):
    freq_meas_ghz = ntw_meas.f / 1e9
    meas_db = db20(ntw_meas.s[:, out_port, in_port])
    return np.interp(freq_pred_ghz, freq_meas_ghz, meas_db)


def summarize_delta(freq_ghz, pred_db, meas_db, band_low=260.0, band_high=320.0):
    mask = (freq_ghz >= band_low) & (freq_ghz <= band_high)
    delta = pred_db[mask] - meas_db[mask]
    return {
        'mean_abs': float(np.mean(np.abs(delta))),
        'max_abs': float(np.max(np.abs(delta))),
        'rms': float(np.sqrt(np.mean(delta ** 2))),
    }


def run_case(single_name, b2b_name, case_label, freq_window=(260.0, 320.0)):
    base = Path(__file__).resolve().parent
    single_ntw = rf.Network(str(base / single_name))
    b2b_ntw = rf.Network(str(base / b2b_name))

    freqs_ghz = single_ntw.f / 1e9
    pred_s21, pred_s11 = cascade_omts_vdi(single_ntw.s, wg_length_mm=0.0, freq_ghz=freqs_ghz)

    # 단일 OMT (Rect1 입력 -> 원형편파 성분) 검증용
    # 6x6 기준 index 0=Rect1_TE10, index 3=Rect2_TE10
    single_co_db = db20((single_ntw.s[:, 0, 3] - 1j * single_ntw.s[:, 1, 3]) / np.sqrt(2.0))
    single_cross_db = db20((single_ntw.s[:, 0, 3] + 1j * single_ntw.s[:, 1, 3]) / np.sqrt(2.0))

    # B2B 예측(행렬) 기준
    # 사용자 피드백 반영: co/cross 라벨을 기존 대비 교정(서로 스왑)
    pred_co_db = db20(pred_s21[:, 3, 0])
    pred_cross_db = db20(pred_s21[:, 0, 0])

    # 입력 리턴로스/동측 아이솔레이션 (행렬 예측)
    pred_rl_db = db20(pred_s11[:, 0, 0])
    pred_iso_db = db20(pred_s11[:, 3, 0])

    # 12포트 EM(B2B) 기준 포트 선택: in=1번, co=10번, cross=7번 (1-based)
    meas_co_db = interp_measured_to_pred(freqs_ghz, b2b_ntw, out_port=9, in_port=0)
    meas_cross_db = interp_measured_to_pred(freqs_ghz, b2b_ntw, out_port=6, in_port=0)
    meas_rl_db = interp_measured_to_pred(freqs_ghz, b2b_ntw, out_port=0, in_port=0)
    meas_iso_db = interp_measured_to_pred(freqs_ghz, b2b_ntw, out_port=3, in_port=0)

    low, high = freq_window
    co_stats = summarize_delta(freqs_ghz, pred_co_db, meas_co_db, low, high)
    cross_stats = summarize_delta(freqs_ghz, pred_cross_db, meas_cross_db, low, high)

    return {
        'label': case_label,
        'freqs_ghz': freqs_ghz,
        'single_co_db': single_co_db,
        'single_cross_db': single_cross_db,
        'pred_co_db': pred_co_db,
        'pred_cross_db': pred_cross_db,
        'pred_rl_db': pred_rl_db,
        'pred_iso_db': pred_iso_db,
        'meas_co_db': meas_co_db,
        'meas_cross_db': meas_cross_db,
        'meas_rl_db': meas_rl_db,
        'meas_iso_db': meas_iso_db,
        'co_stats': co_stats,
        'cross_stats': cross_stats,
    }


def main():
    cases = [
        ('OMT_Square.s9p', 'OMT_S2S_180deg.s12p', 'Square OMT Pair'),
        ('OMT_CW.s9p', 'OMT_S_CW_S_180deg.s12p', 'CW OMT Pair'),
    ]

    results = [run_case(*case) for case in cases]

    # Figure 1: 단일 OMT 결과
    fig1, axes1 = plt.subplots(1, 2, figsize=(14, 5), sharey=True)
    for ax, result in zip(axes1, results):
        f = result['freqs_ghz']
        ax.plot(f, result['single_co_db'], label='Single OMT Co')
        ax.plot(f, result['single_cross_db'], label='Single OMT Cross')
        ax.set_title(result['label'])
        ax.set_xlabel('Frequency (GHz)')
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8)
    axes1[0].set_ylabel('|S| (dB)')
    fig1.suptitle('Figure 1 - Single OMT Response')
    fig1.tight_layout()

    # Figure 2: Back-to-Back (Matrix vs EM)
    fig2, axes2 = plt.subplots(1, 2, figsize=(14, 5), sharey=True)
    for ax, result in zip(axes2, results):
        f = result['freqs_ghz']
        ax.plot(f, result['pred_co_db'], label='Matrix Co')
        ax.plot(f, result['meas_co_db'], '--', label='EM Co')
        ax.plot(f, result['pred_cross_db'], label='Matrix Cross')
        ax.plot(f, result['meas_cross_db'], '--', label='EM Cross')
        ax.set_title(result['label'])
        ax.set_xlabel('Frequency (GHz)')
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8)
    axes2[0].set_ylabel('|S| (dB)')
    fig2.suptitle('Figure 2 - Back-to-Back: Matrix vs EM')
    fig2.tight_layout()

    # Figure 3: Return Loss + Isolation (Matrix vs EM)
    fig3, axes3 = plt.subplots(1, 2, figsize=(14, 5), sharey=True)
    for ax, result in zip(axes3, results):
        f = result['freqs_ghz']
        ax.plot(f, result['pred_rl_db'], label='Matrix Return Loss (S11)')
        ax.plot(f, result['meas_rl_db'], '--', label='EM Return Loss (S11)')
        ax.plot(f, result['pred_iso_db'], label='Matrix Isolation (S41)')
        ax.plot(f, result['meas_iso_db'], '--', label='EM Isolation (S41)')
        ax.set_title(result['label'])
        ax.set_xlabel('Frequency (GHz)')
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8)
    axes3[0].set_ylabel('|S| (dB)')
    fig3.suptitle('Figure 3 - Return Loss and Isolation')
    fig3.tight_layout()

    out_dir = Path(__file__).resolve().parent
    fig1.savefig(out_dir / 'back2back_fig1_single_omt.png', dpi=160)
    fig2.savefig(out_dir / 'back2back_fig2_b2b_compare.png', dpi=160)
    fig3.savefig(out_dir / 'back2back_fig3_rl_iso.png', dpi=160)

    # 이전 단일 파일명도 유지 저장
    fig2.savefig(out_dir / 'back2back_comparison.png', dpi=160)

    print('=== OMT Back-to-Back Comparison Summary (260-320 GHz) ===')
    for result in results:
        print(f"[{result['label']}]")
        print(
            f"  Co-pol   | mean|Delta|={result['co_stats']['mean_abs']:.3f} dB, "
            f"max|Delta|={result['co_stats']['max_abs']:.3f} dB, "
            f"RMS={result['co_stats']['rms']:.3f} dB"
        )
        print(
            f"  Cross-pol| mean|Delta|={result['cross_stats']['mean_abs']:.3f} dB, "
            f"max|Delta|={result['cross_stats']['max_abs']:.3f} dB, "
            f"RMS={result['cross_stats']['rms']:.3f} dB"
        )

    print(f'Saved plot: {out_dir / "back2back_fig1_single_omt.png"}')
    print(f'Saved plot: {out_dir / "back2back_fig2_b2b_compare.png"}')
    print(f'Saved plot: {out_dir / "back2back_fig3_rl_iso.png"}')
    plt.show()


if __name__ == '__main__':
    main()