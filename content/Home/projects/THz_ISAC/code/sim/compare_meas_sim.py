try:
    import numpy as np
    import pandas as pd
    import matplotlib.pyplot as plt
    import skrf as rf
except ImportError as e:
    print("스크립트 실행에 필요한 라이브러리가 설치되지 않았습니다.")
    print("터미널에서 아래 명령어를 실행하여 라이브러리를 설치해주세요:")
    print("pip install numpy pandas matplotlib scikit-rf")
    print(f"\n에러 상세 정보: {e}")
    input("설치를 완료한 후 Enter 키를 눌러 스크립트를 종료하세요...")
    exit()

from pathlib import Path

def read_meas_csv(filepath):
    df = pd.read_csv(filepath)
    return df['Frequency (GHz)'].values, df['Power (dBm)'].values

def db20(x, floor_db=-140.0):
    mag = np.maximum(np.abs(x), 10 ** (floor_db / 20.0))
    return 20.0 * np.log10(mag)

def main():
    # 경로 설정
    base_dir = Path(__file__).resolve().parent.parent
    data_dir = base_dir / "data"
    omt_dir = base_dir / "OMT"

    # 1. Thru 측정 결과 읽기 (Reference)
    thru_file = data_dir / "new_thru_0dbm_2.csv"
    freq_thru, p_thru = read_meas_csv(thru_file)

    # Thru를 이용한 Calibration (Insertion Loss 변환 함수)
    def calibrate_meas(freq_dut, p_dut):
        p_thru_interp = np.interp(freq_dut, freq_thru, p_thru)
        return p_dut - p_thru_interp

    # ==========================================
    # [1] 180deg Setup (Simulation vs Measurement)
    # ==========================================
    # EM Simulation 읽기 (s12p)
    s12p_file = omt_dir / "OMT_S_CW_S_180deg.s12p"
    b2b_ntw = rf.Network(str(s12p_file))
    freq_sim = b2b_ntw.f / 1e9

    # S-parameter 데이터 추출 (dB 변환)
    # 12포트 EM(B2B) 기준: in=0, co=9, cross=6, RL=0, iso=3 (0-based index)
    sim_co_db = db20(b2b_ntw.s[:, 9, 0])
    sim_cross_db = db20(b2b_ntw.s[:, 6, 0])
    sim_rl_db = db20(b2b_ntw.s[:, 0, 0])
    sim_iso_db = db20(b2b_ntw.s[:, 3, 0])

    # 180deg 측정 데이터 파일
    file_1to3_180 = data_dir / "long_1TO3_180deg_1.csv"
    file_1to4_180 = data_dir / "long_1TO4_180deg_1.csv"
    file_1to2_180 = data_dir / "long_1TO2_180deg_1.csv" # Isolation

    fig1, axes1 = plt.subplots(1, 2, figsize=(14, 5))
    fig1.suptitle("180deg Setup: EM Simulation vs Measurement", fontsize=14)

    # Co/Cross-pol Plot
    axes1[0].plot(freq_sim, sim_co_db, label='Sim Co-pol (S10,1)')
    axes1[0].plot(freq_sim, sim_cross_db, label='Sim Cross-pol (S7,1)')
    
    if file_1to3_180.exists() and file_1to4_180.exists():
        f_1to3_180, p_1to3_180 = read_meas_csv(file_1to3_180)
        f_1to4_180, p_1to4_180 = read_meas_csv(file_1to4_180)

        cal_1to3_180 = calibrate_meas(f_1to3_180, p_1to3_180)
        cal_1to4_180 = calibrate_meas(f_1to4_180, p_1to4_180)

        # 평균 Loss를 비교하여 Co-pol, Cross-pol 구분 (Loss가 더 작은 쪽이 Co-pol)
        if np.mean(cal_1to3_180) > np.mean(cal_1to4_180):
            meas_co, meas_cross = cal_1to3_180, cal_1to4_180
            label_co, label_cross = "Meas Co-pol (1TO3)", "Meas Cross-pol (1TO4)"
        else:
            meas_co, meas_cross = cal_1to4_180, cal_1to3_180
            label_co, label_cross = "Meas Co-pol (1TO4)", "Meas Cross-pol (1TO3)"

        axes1[0].plot(f_1to3_180, meas_co, '--', label=label_co)
        axes1[0].plot(f_1to4_180, meas_cross, '--', label=label_cross)

    axes1[0].set_title("Co-pol and Cross-pol")
    axes1[0].set_xlabel("Frequency (GHz)")
    axes1[0].set_ylabel("Magnitude (dB)")
    axes1[0].grid(True, alpha=0.5)
    axes1[0].legend()

    # Return Loss / Isolation Plot
    axes1[1].plot(freq_sim, sim_rl_db, label='Sim Return Loss (S1,1)')
    axes1[1].plot(freq_sim, sim_iso_db, label='Sim Isolation (S4,1)')

    if file_1to2_180.exists():
        f_1to2_180, p_1to2_180 = read_meas_csv(file_1to2_180)
        cal_1to2_180 = calibrate_meas(f_1to2_180, p_1to2_180)
        axes1[1].plot(f_1to2_180, cal_1to2_180, '--', label='Meas Isolation (1TO2)')
        
    axes1[1].set_title("Return Loss and Isolation")
    axes1[1].set_xlabel("Frequency (GHz)")
    axes1[1].set_ylabel("Magnitude (dB)")
    axes1[1].grid(True, alpha=0.5)
    axes1[1].legend()
    fig1.tight_layout()

    # ==========================================
    # [2] 0deg Setup (Simulation vs Measurement)
    # ==========================================
    # EM Simulation 읽기 (s12p)
    s12p_file_0 = omt_dir / "OMT_S_CW_S_0deg.s12p"
    b2b_ntw_0 = rf.Network(str(s12p_file_0))
    freq_sim_0 = b2b_ntw_0.f / 1e9

    sim_co_0_db = db20(b2b_ntw_0.s[:, 9, 0])
    sim_cross_0_db = db20(b2b_ntw_0.s[:, 6, 0])
    sim_rl_0_db = db20(b2b_ntw_0.s[:, 0, 0])
    sim_iso_0_db = db20(b2b_ntw_0.s[:, 3, 0])

    file_1to3_0 = data_dir / "long_1TO3_0deg_1.csv"
    file_1to4_0 = data_dir / "long_1TO4_0deg_1.csv"
    file_1to2_0 = data_dir / "long_1TO2_0deg_1.csv" # Isolation

    fig2, axes2 = plt.subplots(1, 2, figsize=(14, 5))
    fig2.suptitle("0deg Setup: EM Simulation vs Measurement", fontsize=14)

    # Co/Cross-pol Plot
    axes2[0].plot(freq_sim_0, sim_co_0_db, label='Sim Co-pol (S10,1)')
    axes2[0].plot(freq_sim_0, sim_cross_0_db, label='Sim Cross-pol (S7,1)')

    if file_1to3_0.exists() and file_1to4_0.exists():
        f_1to3_0, p_1to3_0 = read_meas_csv(file_1to3_0)
        f_1to4_0, p_1to4_0 = read_meas_csv(file_1to4_0)

        cal_1to3_0 = calibrate_meas(f_1to3_0, p_1to3_0)
        cal_1to4_0 = calibrate_meas(f_1to4_0, p_1to4_0)

        if np.mean(cal_1to3_0) > np.mean(cal_1to4_0):
            meas_co_0, meas_cross_0 = cal_1to3_0, cal_1to4_0
            label_co_0, label_cross_0 = "Meas Co-pol (1TO3)", "Meas Cross-pol (1TO4)"
        else:
            meas_co_0, meas_cross_0 = cal_1to4_0, cal_1to3_0
            label_co_0, label_cross_0 = "Meas Co-pol (1TO4)", "Meas Cross-pol (1TO3)"

        axes2[0].plot(f_1to3_0, meas_co_0, '--', label=label_co_0)
        axes2[0].plot(f_1to4_0, meas_cross_0, '--', label=label_cross_0)

    axes2[0].set_title("Co-pol and Cross-pol")
    axes2[0].set_xlabel("Frequency (GHz)")
    axes2[0].set_ylabel("Magnitude (dB)")
    axes2[0].grid(True, alpha=0.5)
    axes2[0].legend()

    # Return Loss / Isolation Plot
    axes2[1].plot(freq_sim_0, sim_rl_0_db, label='Sim Return Loss (S1,1)')
    axes2[1].plot(freq_sim_0, sim_iso_0_db, label='Sim Isolation (S4,1)')

    if file_1to2_0.exists():
        f_1to2_0, p_1to2_0 = read_meas_csv(file_1to2_0)
        cal_1to2_0 = calibrate_meas(f_1to2_0, p_1to2_0)
        axes2[1].plot(f_1to2_0, cal_1to2_0, '--', label='Meas Isolation (1TO2)')

    axes2[1].set_title("Return Loss and Isolation")
    axes2[1].set_xlabel("Frequency (GHz)")
    axes2[1].set_ylabel("Magnitude (dB)")
    axes2[1].grid(True, alpha=0.5)
    axes2[1].legend()
    fig2.tight_layout()

    # 결과 저장
    fig1.savefig(omt_dir / 'compare_180deg_sim_vs_meas.png', dpi=160)
    fig2.savefig(omt_dir / 'compare_0deg_sim_vs_meas.png', dpi=160)
    print(f"Plots saved to {omt_dir}")

    plt.show()

if __name__ == '__main__':
    main()