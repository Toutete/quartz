---
title: THz ISAC 시스템 구조
is_public: false
---
본 논문의 핵심
1. CP generation 
2. Full-duplex THz ISAC 실증 (ISAC waveform 으로 통신/radar 동시 입증)
3. Free-running lasers + ZBD (SIM)

fig. 1. V2X senario of Full-duplex monostatic THz ISAC
fig. 2. 제안하는 THz ISAC 시스템의 block diagram
![[Pasted image 20260708160638.png]]
Fig. 3. 측정 셋업 + 사진 (DSP, optical spectrum (SSB), electrical spectrum (SSBI를 피할 수 있고 DC block 등으로 ADC 포화 방지) + 2 CH 동시 결과 사진?
fig. 4. OMT simulation 및 측정 결과 (안테나)
fig. 5. 측졍 결과 1
fig. 6. 측졍 결과 2
fig. 7. 측졍 결과 3


Simulation 결과
1. PAPR (OFDM vs DFT-s-OFDM vs LFM-QAM) for UTC-PD (Pin vs Pout curve), 16QAM 이상
2. DFT-s-OFDM 통신 성능 vs amplitude ratio rho

측정 결과
1. EVM + range resolution vs Bandwidth ? bandwidth 로 보여줄게 있나?
	1. Trade-off 를 보여줄 수 있음, low symbol rate: high EVM, low resolution
2. EVM vs photocurrent (16QAM, 32QAM)
	1. SNR-limited 시스템 > PA, 고이득 안테나로 더 장거리가 가능함, 또한 고효율 소자 개발의 필요성 제시
3. 거리에 따른 SNR (통신, Radar) 
	1. 이것을 통해 통신은 SNR limited 됨, 반면 radar는 processing gain 으로 인해 더 먼 거리에 대해 가능함 (DFT-s-OFDM 의 단점이 있음에도)
4. 2 Gbaud vs 20 Gbaud rate 에 대한 range profile 비교 (7 mm RX 이동을 detection 가능함)
5. EVM vs FDE taps 개수


TX: two free-running lasers - UTC-PD - OMT - TX Antenna 

one-way RX (C1): UTC-PD output (Tx THz power) - OMT (THz insertion loss) -(TX Antenna - wireless link - Rx antenna) (Rx THz Power of one-way RX) - OMT (THz insertion loss) - THz LNA - ZBD - Drive Amp - cable, adapter, DC block, etc. loss - DSO C1

Monostatic Radar RX (C2): UTC-PD output (Tx THz power) - OMT (THz insertion loss) -(TX Antenna - wireless link - RX antenna (Radar target RCS) - wireless link - Tx Antenna)  -  OMT (THz insertion loss) - THz LNA -ZBD - Drive amp - cable, adapter, DC block, etc. loss - DSO C2





Introduction
2025 TVT (Millimeter-Wave Dual-Circularly Polarized Wide-Angle Scanning Antenna Array for Vehicular Communication Systems)
What’s more, it is well known that satellite signals are easily interfered by useless signals when crossing the atmosphere, resulting in a poor transmission quality. Therefore, circularly polarized (CP) antennas are usually used in vehicle-to-satellite communication because they can receive electromagnetic waves of arbitrary polarization, avoiding polarization mismatch between the receiver and transmitter, and have a significant effect in resisting multipath fading [9], [10]. Therefore, the study of highperformance CP phased array antenna provides great technical support for current and future vehicle-to-satellite communication systems. At present, narrow axial ratio bandwidth (ARBW), impedance bandwidth (IMBW) and poor scanning performance are still the main limitations in practical applications, which should be carefully addressed.




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
     │  MZM 광 DSB 생성 후 WSS로 한쪽 sideband 제거: UTC-PD 입력은 SSB
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
