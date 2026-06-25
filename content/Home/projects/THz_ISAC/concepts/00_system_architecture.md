---
title: THz ISAC 시스템 구조
is_public: false
---

# THz ISAC 시스템 구조

## 1. 전체 신호 흐름

```
[AWG M8194A]
     │  I/Q 기저대역 (10 GBaud 16-QAM @ 15 GHz SIM IF)
     ▼
[Amp +29 dB] → [Atten -10 dB]
     │  net +19 dB, AWG ≈ 122 mVpp → MZM +7.7 dBm
     ▼
[MZM iXblue MXAN-LN-40]  ← DC bias controller (quadrature +3.25 V)
     │  광 DSB: f_c, f_c ± 15 GHz
     ▼
[광 커플러]  ← LD2 (193.140 THz, f1-f2 = 270 GHz)
     │
     ▼
[UTC-PD NICT IOD-PMJ-13001]  (역바이어스 ≈ -1 V)
     │  THz: 255 / 270 / 285 GHz (-10 dBm)
     ▼
[THz PA]
     ▼
[OMT] ── RHCP ──▶  [Horn] ══════════▶ Target
                                            │
                   [Horn] ◀══════════ LHCP (반사, 핸드니스 반전)
                     │
[OMT] ─ LHCP 수신 ─┘  (SI 누설 ~25 dB down = 자기동조 LO)
     │
     ▼
[THz LNA]
     │
     ▼
[ZBD VDI WR3.4ZBD]  ← SI 누설이 self-homodyne LO로 작동
     │  제곱법칙 검파: DC + 15 GHz (원하는 신호) + 30 GHz
     ▼
[LNA + BPF]
     │
     ▼
[DSO Keysight UXR0404A]  (256 GSa/s, 40 GHz BW)
     │
     ▼
[오프라인 DSP 처리]
```

## 2. 핵심 물리 원리

### 자기동조(Self-Homodyne) 위상잡음 상쇄

OMT의 유한한 격리도(~24.8 dB)가 SI 누설을 ZBD로 흘립니다.
이 누설과 에코는 **동일한 두 레이저**에서 비롯되므로 위상잡음이 상관 관계에 있습니다.

ZBD 제곱법칙 출력:

$$v_{out}(t) \propto |E_{SI}(t) + E_{echo}(t)|^2$$

전개하면:

$$v_{out}(t) = |E_{SI}|^2 + |E_{echo}|^2 + 2\,\text{Re}\left[E_{SI}^*(t)\,E_{echo}(t)\right]$$

교차항의 위상잡음:

$$\Delta\phi(t) = \phi_{SI}(t) - \phi_{echo}(t) \approx \phi_{laser}(t) - \phi_{laser}(t-\tau) \approx 0 \quad (\tau \ll \Delta\nu^{-1})$$

실내 거리 기준 잔류 패널티:

$$\sigma^2_{\Delta\phi} = 4\pi \cdot \Delta\nu \cdot \tau < 0.7\,\text{dB}$$

따라서 OFCG, PLL, 디지털 위상 복원이 불필요합니다.

### SIM (Subcarrier Intensity Modulation)

ZBD는 제곱법칙 소자이므로 기저대역에 SSBI(Signal-Signal Beat Interference) 성분이 발생합니다.
SSBI 바닥 주파수 범위: $[0,\, B]$ Hz.

SIM은 데이터를 IF = 15 GHz로 옮겨 SSBI를 회피합니다:

$$f_{IF} > \frac{3B}{2}$$

단순 HPF 하나로 SSBI를 -40 dB 이하로 제거할 수 있습니다.

### OMT 격리도 골디락스 조건

| 격리도 | 문제 |
|--------|------|
| < 20 dB | SI 누설이 너무 커 → LNA 포화 |
| 20~30 dB | ✅ 최적: LNA 여유 + ZBD 적정 펌핑 |
| > 30 dB | ZBD 언더펌핑 → 변환 이득 저하 |

현재 측정값: **24.8 dB** (LNA P1dB 대비 4.8 dB 여유)

## 3. 소프트웨어 모듈 구조

```
code/
├── isac_unified_gui.py        ← 통합 GUI (TX + RX + SIC 탭)
├── envelope_detector_si_gui.py ← 시뮬레이션 전용 GUI
├── functions/
│   ├── awg_functions.py       ← AWG TCP/SCPI 드라이버
│   ├── dso_functions.py       ← DSO SCPI/VICP 드라이버
│   └── dsp_functions.py       ← DSP 알고리즘 (변조/복조/SIC)
├── tx/
│   └── keysight_awg.py        ← pyvisa 기반 AWG 드라이버
├── rx/
│   └── dso_demod.py           ← LFM-QAM 복조 스크립트
├── sim/
│   ├── back2back_sim.py       ← OMT S-파라미터 시뮬레이션
│   ├── compare_meas_sim.py    ← 측정/시뮬레이션 비교
│   └── *.s9p / *.s12p         ← OMT S-파라미터 데이터
└── bench/
    ├── pm5b_zero_probe.py     ← 파워미터 영점 조정
    ├── scg_shf.py             ← SHF 신호 발생기 제어
    └── shf_SGX_PM5_meas_v2.py ← SGX + PM5 자동 측정
```

## 4. 관련 노트

- [[01_tx_signal_generation]] — TX 파형 생성 및 AWG 연동
- [[02_rx_demodulation]] — DSO 캡처 및 복조 DSP 체인
- [[03_omt_simulation]] — OMT S-파라미터 시뮬레이션
- [[../HANDOFF]] — 하드웨어 사양 및 바이어스 설정 상세
