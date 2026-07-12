---
title: THz ISAC 시스템 구조
is_public: false
---

| Aspect             | Matched filter (classical)                  | SI-normalized CFR (this work)                                 |
| ------------------ | ------------------------------------------- | ------------------------------------------------------------- |
| Core op            | 1 correlation `Σ y·s*`                      | CFR division `H/H_SI` + phase slope / 1 IDFT                  |
| Ops/scale          | `O(N log N)` (FFT correlation)              | `O(N log N)` CFR + `O(N)` division + `O(N log N)` delay match |
| Extra state        | none                                        | SI reference `H_SI` (weighted mean, `O(N)`)                   |
| Carrier assumption | **coherent, known/stable phase**            | **free-running OK** — SI supplies the phase reference         |
| Extra hardware     | often OPLL / comb / shared-LO for coherence | **none** — SI leakage is the built-in LO                      |
| Per-capture fading | severe if carrier drifts                    | removed by `H/H_SI`                                           |
| Moving target      | fine (single shot)                          | fine (single shot)                                            |

**Bottom line:** the _arithmetic_ complexity is essentially the same order as a matched filter (both dominated by FFT-length transforms). The saving is in **hardware/coherence cost**: SI normalization replaces the phase-locking hardware (OPLL/comb/wavemeter) that a coherent matched filter would otherwise need at 270 GHz with free-running lasers. The added software cost is one `O(N)` division and the SI mean — negligible.
### 3.2 Comparison table

| Criterion                    | LFM-QAM                   | OFDM                                  | DFT-s-OFDM                         |
| ---------------------------- | ------------------------- | ------------------------------------- | ---------------------------------- |
| Range method                 | de-chirp / matched filter | subcarrier channel division + IDFT    | precoder-inverted channel division |
| Processing gain              | very high (chirp TBWP)    | high (N subcarriers)                  | high, minus spreading overhead     |
| PAPR                         | low–moderate              | **high**                              | **low** (its main advantage)       |
| Sensing sidelobes            | excellent (chirp)         | excellent                             | slightly worse (spreading)         |
| Comms spectral eff.          | moderate                  | high                                  | high                               |
| Data-independence of profile | good                      | **very good** (division removes data) | good after de-spreading            |
| Doppler / moving target      | excellent (classic radar) | good (2-D DFT)                        | good but more processing           |
| Impl. complexity             | moderate                  | moderate                              | higher (extra DFT stages)          |
| Best fit                     | radar-centric ISAC        | comms-centric ISAC, rich sensing      | uplink / power-limited nodes       |

본 논문의 핵심 수식 정리

$$V_{ZBD}(t)=V_{SI}(t)+V_{echo}(t)$$

$$V_{SI}=\alpha_{SI},s(t),e^{j(\omega_c t+\phi(t))},\qquad V_{echo}=\beta_{ec},s(t-\tau),e^{j(\omega_c(t-\tau)+\phi(t-\tau))}$$

$$V_{out}=\mathcal R,|V_{ZBD}|^2 =\mathcal R\big[\underbrace{\alpha_{SI}^2|s(t)|^2}_{(A)\ \text{SI},\ \tau=0} +\underbrace{\beta_{ec}^2|s(t-\tau)|^2}_{(B)\ \text{echo}} +\underbrace{2\alpha_{SI}\beta_{ec},\mathrm{Re}{s(t)s^*(t-\tau)e^{j(\omega_c\tau+\Delta\phi)}}}_{(C)\ \text{homodyne}}\big]$$


### 1.2 CFR estimate (single capture)

$$H(f)=\frac{Y(f)}{S(f)} =\underbrace{\alpha_{SI}e^{j\psi}}_{\text{flat, }\tau\approx0} +\underbrace{\beta_{ec}e^{j\psi}e^{-j2\pi(f+f_c)\tau}}_{\text{echo}}$$

`ψ` = common per-capture carrier phase, `f_c` = drifting carrier. SI and echo carry the **same** `e^{jψ}`.

### 1.3 SI normalization (the key step)

$$H_{SI}=\frac{\sum_f w,H(f)}{\sum_f w}\approx\alpha_{SI}e^{j\psi},\qquad \boxed{;\tilde H(f)=\frac{H(f)}{H_{SI}}-1=\frac{\beta_{ec}}{\alpha_{SI}},e^{-j2\pi(f+f_c)\tau};}$$

Dividing by the flat SI cancels `e^{jψ}` → **coherent fading removed**. DC re-removal: `H̃' = H̃ − mean_w(H̃)`.

### 1.4 Range estimate — two equivalent readouts

**(a) Phase-slope** (drift-immune; `f_c τ` is constant in `f`, drops out of the slope):

$$\hat\tau=-\frac{1}{2\pi}\frac{d,\angle\tilde H}{df},\qquad \hat R=\frac{c\hat\tau}{2}$$

(b) IDFT/delay-matching (다중 target)

정규화된 CFR을 delay 영역으로 역변환합니다.

$$p(\tau') = \int \tilde{H}(f),e^{j2\pi f\tau'},df = \sum_{k}\frac{\beta_k}{\alpha_{SI}}\int e^{-j2\pi(f+f_c)\tau_k}e^{j2\pi f\tau'}df$$

$$= \sum_k \frac{\beta_k}{\alpha_{SI}}e^{-j2\pi f_c\tau_k}\int e^{j2\pi f(\tau'-\tau_k)}df$$

유한 대역 B에서 적분하면:

$$\boxed{p(\tau') = \sum_k \frac{\beta_k}{\alpha_{SI}},e^{-j2\pi f_c\tau_k},B,\text{sinc}\big(B(\tau'-\tau_k)\big)}$$

각 target이 **자기 지연 τ_k에서 sinc peak**를 만듭니다. 이산 형태(코드 구현):

$$p[\tau'] = \sum_{n} w[n],\tilde{H}[n],e^{j2\pi f_n\tau'}$$

$$\hat{R}_k = \frac{c}{2}\cdot{\tau' : |p(\tau')| \text{ has a peak}}$$

**다중 target을 다루는 이유:** IDFT는 각 지수 성분을 자기 위치의 peak로 분리하므로, K개 target이 K개 peak로 나타납니다. 이것이 Sturm-Wiesbeck의 핵심입니다.



## C. The actual range limit of this system

With SI removed by normalization, the limit is the ordinary **noise limit** (plus a dynamic-range caveat), NOT an SI sidelobe:

$$\mathrm{SNR}_{radar}(R)=\frac{G_p,2,\alpha_{SI},\beta_{ec}(R)}{N},\qquad \beta_{ec}(R)=\frac{\sqrt{K}}{R^2}.$$

$$\boxed{R_{\max}=\left(\frac{2,\alpha_{SI},\sqrt{K},G_p}{N,\gamma_{th}}\right)^{1/2}}$$

Symbols:

- `α_SI = 10^{−ISO/20}` — SI amplitude (OMT isolation). **Larger helps** (homodyne gain), bounded above only by ADC dynamic range (B10), not by sidelobes.
- `β_ec = √K/R²` — echo amplitude; radar-equation `1/R²` amplitude decay.
- `K = P_tx G_t G_r λ² σ_eff /(4π)³` — lumped budget constant (radar eq. minus `R⁴`).
- `N` — noise power: ZBD NEP + thermal `kT₀BF` + ADC quantization.
- `γ_th` — detection-threshold SNR for target `P_d`/`P_fa` (e.g. ~13 dB).
- `G_p = T·B` — matched-filter/IDFT processing gain (TBWP).


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

RX1 (C1): RX1 Antenna - OMT - THz LNA - ZBD - (bias tee + adaptor) - Drive Amp -cable - DSO 

RX2 (C2): RX1 Antenna으로부터 반사된 신호 - TX Antenna - OMT - THz LNA - ZBD - cable - Drive Amp - cable - DSO





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
