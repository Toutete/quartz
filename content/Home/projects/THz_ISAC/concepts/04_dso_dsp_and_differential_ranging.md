---
title: DSO DSP 및 차동 거리 측정 워크플로우
is_public: false
---

# DSO DSP 및 차동 거리 측정 워크플로우

## 1. 현재 상태

최근 LFM-QAM DSO 측정 결과는 SNR 한계에 거의 도달했다.

| 항목 | 결과 | 해석 |
|---|---:|---|
| SNR | 25.25 dB | 캡처된 수신 신호의 대역 내 SNR |
| EVM | -24.12 dB | SNR 한계 대비 약 1.1 dB 손실 |
| 파형 | LFM-QAM / 16QAM | 현재 DSO DSP가 거의 정상 동작 중 |

AWGN 지배 링크에서는 RMS EVM이 대략 다음 관계를 따른다.

$$
\mathrm{EVM}_{dB} \approx -\mathrm{SNR}_{dB}
$$

따라서 SNR이 약 25 dB일 때 EVM이 -24 dB 수준이면 충분히 타당하다. 이전의 -16 dB 수준 EVM은 LFM-QAM 파형 자체의 피할 수 없는 upper bound가 아니라, dechirp 이후 채널 보정 및 심볼 복구 DSP가 부족해서 발생한 손실로 보는 것이 맞다.

## 2. 차동 거리 측정 개념

현재 셋업에서 절대 거리를 바로 측정하기는 어렵다. DSO trigger/pre-trigger latency, AWG 출력 latency, trigger cable delay, DSO channel skew, 장비 내부 delay가 모두 측정 delay에 포함되기 때문이다.

따라서 절대 delay를 모두 제거하려 하기보다, 기준 위치와 이동 후 위치의 차이를 보는 차동 측정 방식을 사용한다.

## 3. Trigger Reference Path

계획 중인 구성은 다음과 같다.

```text
AWG M8194A dual-channel mode
  CH1 또는 선택한 RF 출력 채널  -> ISAC / communication waveform path
  CH2                         -> DSO CH3 reference trigger path

DSO
  선택한 RX channel             -> received ISAC waveform
  CH3                         -> reference trigger input
```

3 m RF trigger cable은 대략 12-15 ns의 전기적 delay를 만든다. 이 delay는 0이 아니지만, 케이블을 움직이거나 구부리지 않고 같은 상태로 유지하면 공통 상수항으로 취급할 수 있다.

기준 위치의 측정 delay:

$$
\tau_0 = \tau_{\mathrm{path},0} + \tau_{\mathrm{sys}}
$$

이동 후 위치의 측정 delay:

$$
\tau_1 = \tau_{\mathrm{path},1} + \tau_{\mathrm{sys}}
$$

두 값을 빼면

$$
\Delta \tau = \tau_1 - \tau_0
             = \tau_{\mathrm{path},1} - \tau_{\mathrm{path},0}
$$

가 되어 시스템 공통 delay는 1차적으로 소거된다.

단, 이것을 "오차 리스크 0%"라고 표현하는 것은 과하다. trigger jitter, 케이블 bending, 온도 drift, AWG/DSO clock drift, stage repeatability는 여전히 남는다. 다만 큰 고정 delay가 변위 측정을 지배하지 않게 되는 것이 핵심이다.

## 4. One-Way와 Monostatic 거리 변환

거리 변환식은 측정 geometry에 따라 달라진다.

### One-way LOS

AWG/송신부에서 수신부까지 한 번만 전파되는 direct LOS 이동량은

$$
\Delta R = c \Delta \tau
$$

를 사용한다.

### Monostatic Radar

송신부에서 target까지 갔다가 다시 돌아오는 monostatic radar echo는 왕복 경로이므로

$$
\Delta R = \frac{c \Delta \tau}{2}
$$

를 사용한다.

GUI에는 이를 위해 `Range Mode`를 추가했다.

- `One-way LOS (c)`
- `Monostatic radar (c/2)`

## 5. Range Resolution과 미세 변위 추적

대역폭으로 결정되는 고전적 range resolution은 다음과 같다.

Monostatic radar:

$$
\Delta R_{\mathrm{mono}} = \frac{c}{2B}
$$

One-way LOS:

$$
\Delta R_{\mathrm{one-way}} = \frac{c}{B}
$$

예시는 다음과 같다.

| Bandwidth | Monostatic resolution | One-way LOS resolution |
|---:|---:|---:|
| 1 GHz | 15 cm | 30 cm |
| 10 GHz | 1.5 cm | 3 cm |

반면 CFR phase slope 또는 carrier phase 기반 분석은 peak bin보다 훨씬 작은 sub-bin displacement tracking을 가능하게 한다. 이것은 두 개의 독립 target을 분리하는 range resolution 자체를 무한히 넘는다는 뜻은 아니다. 안정적인 단일 경로 또는 dominant path의 미세 변위를 고해상도로 추정하는 것이다.

## 6. 권장 측정 프로토콜

### Step 1. Reference 획득

1. 수신부 또는 target을 Position 0에 고정한다.
2. AWG CH2를 DSO CH3에 연결하여 reference trigger로 사용한다.
3. DSO에서 ISAC RX channel을 capture한다.
4. `Set Range Zero`를 누른다.
5. `Save Capture`로 기준 capture를 저장한다.

`Set Range Zero`는 다음을 저장한다.

- matched-filter peak delay를 0 m 기준으로 저장
- 기준 LFM-QAM channel frequency response, 즉 `H0(f)` 저장

### Step 2. Target 획득

1. stage를 원하는 거리만큼 이동한다.
2. 같은 trigger/reference 조건에서 capture한다.
3. 필요하면 `Save Capture`로 저장한다.
4. `ISAC De-chirp / Range`를 실행한다.

GUI는 다음을 계산한다.

- matched-filter peak 기반 range
- `Range Mode`에 따른 one-way 또는 monostatic scaling
- `H1(f) / H0(f)` phase slope 기반 차동 변위
- differential CFR coherence

### Step 3. Offline 재처리

`Load Capture`로 저장된 `.npz` 파일을 불러오면 실시간 DSO 없이도 같은 데이터로 demodulation과 range detection을 반복할 수 있다.

저장 파일에는 다음이 포함된다.

- `rx_sig`: DSO voltage waveform
- `rx_t`: time axis
- `rx_fs`: sampling rate
- GUI demod/range 설정
- 현재 TX reference payload (`tx__...` prefix)

Load 후에는 `Live DSO`가 자동으로 꺼지고, `Demodulate` 및 `ISAC De-chirp / Range`가 저장된 capture를 대상으로 실행된다.

## 7. 현재 DSO DSP 체인

현재 GUI의 DSO DSP는 `code/isac_unified_gui.py`에 구현되어 있다.

### 7.1 DSO 설정 및 Capture

DSO 연결 또는 capture 시 GUI는 다음 설정을 적용한다.

- DSO RX channel display 및 vertical scale
- DSO sample rate
- acquisition points 및 timebase range
- FFT source, offset, scale
- trigger source 및 trigger level
- Keysight UXR의 waveform/FFT split display layout

AWG CH2 -> DSO CH3 reference trigger를 위해 `Trigger Ch`와 `Trig Level (mV)` 설정을 추가했다.

### 7.2 Baseband 변환

DSO에서 받은 real waveform을 `x[n]`이라고 하면,

1. DC 제거

   $$
   x[n] \leftarrow x[n] - \mathrm{mean}(x[n])
   $$

2. Real IF downconversion

   $$
   r[n] = 2x[n]e^{-j2\pi f_{\mathrm{IF}} n/f_s}
   $$

3. TX/AWG reference sampling rate로 resampling
4. FFT-domain low-pass filtering
5. RMS normalization

LFM-QAM demod LPF는 QAM RRC 대역뿐 아니라 chirp sweep 대역을 포함하도록 설정한다.

$$
B_{\mathrm{LPF}} \gtrsim
\frac{B_{\mathrm{chirp}}}{2}
+ \frac{R_s(1+\beta)}{2}
$$

## 8. QAM Demodulation DSP

일반 QAM 경로는 다음 순서로 처리된다.

1. 현재 TX reference payload 로드
2. `Sync symbol/mod from AWG`가 켜져 있으면 AWG panel의 symbol rate 및 modulation을 DSO demod 설정에 반영
3. M-th power 기반 blind CFO 추정
4. RRC matched filtering
5. Zadoff-Chu preamble correlation으로 frame/timing lock
6. deterministic TX PRBS reference 기반 frame start, CFO, SRO refine
7. Gardner timing recovery
8. phase, IQ, widely-linear correction 후보 평가
9. SC-FDE 적용 여부별 후보 평가
10. EVM이 가장 낮고 유효한 equalization path 선택
11. deterministic PRBS/TX reference 기준 EVM 및 BER 계산

## 9. LFM-QAM Demodulation DSP

### 9.1 배경: TDM에서 shared waveform으로

이전 LFM-QAM은 TDM 구조였다 — 프레임 안에서 ZC preamble chirp + pilot chirp만 레이더 처리 이득을 얻고, 나머지 data chirp는 통신 전용이었다. 지금의 LFM-QAM은 이 TDM 분리를 없앤 **shared-waveform ISAC 신호**다. 프레임 전체를 하나의 연속된 LFM chirp로 사용하면서 그 위에 PSK 데이터를 위상으로만 얹는다.

$$
s(t) = \exp\!\left[j\pi(2f_0 t + u t^2) + j\phi_k(t)\right]
$$

여기서 $u$는 chirp slope, $\phi_k(t)$는 심볼 구간 동안 위상을 유지하는 (zero-order-hold) PSK 심볼 위상이다. RRC 등 진폭 pulse shaping은 적용하지 않는다 — pulse shaping은 진폭 리플을 만들어 constant-envelope 특성을 깨뜨리기 때문이다. 따라서 매 샘플에서 $|s[n]| = 1$이 정확히 유지되고, MZM/UTC-PD에 최대 전력으로 구동할 수 있다.

프레임 전체가 하나의 chirp이므로 (`n_chirps = 1`), 100% duty cycle로 정합 필터 처리 이득을 얻는다 — 이전처럼 overhead chirp 비율만큼만 레이더에 쓰이는 것이 아니라 캡처 전체가 레이더 펄스로 동작한다. Modulation은 PSK(BPSK/QPSK/8PSK)로 제한된다 — QAM은 진폭이 변하므로 constant envelope과 양립할 수 없다.

### 9.2 기존 chirp 기반 코드의 재사용

`_frame_sync_and_reshape`, `_refine_lfm_frame_sro`/`_sample_fractional_symbol_indices`, `_estimate_lfm_cfr`, `_differential_delay_from_cfr`, `_compute_isac_range_profile_for_signal`는 모두 `n_chirps`/`pts_per_chirp` 기준의 일반화된 코드다. TX payload를 `n_chirps=1`, `tx_bb_matrix` shape `(1, N)`, `base_chirp`를 프레임 전체 길이의 chirp phase ramp로 구성하면, 위 함수들은 **코드 수정 없이** 그대로 동작한다. 특히 `_compute_isac_range_profile_for_signal`의 `for i in range(n_chirps)` 정합 필터 루프는 `n_chirps=1`일 때 프레임 전체에 대한 단일 matched filter로 자연스럽게 축소되는데, 이것이 곧 100% duty cycle 레이더 처리 이득이다.

단, `_estimate_lfm_cfr`의 chirp 간 평균(ensemble averaging)은 row가 1개이므로 사라진다 (평균 대신 단일 노이즈 있는 bin별 비율이 된다). 대신 프레임 전체 길이의 FFT를 쓰므로 주파수 분해능은 훨씬 좋아진다 — 실측 전까지는 이 trade-off가 순이익인지 아직 검증되지 않은 v1 주의사항으로 남겨둔다 (CFR bin 개수, phase-slope fit coherence를 로그로 남겨 확인할 것).

### 9.3 PSK 심볼 복구

데이터는 RRC로 성형되지 않은 rectangular (zero-order-hold) 위상 스텝이므로, RRC matched filter가 존재하지 않는다. Rectangular pulse에 대한 정합 필터는 심볼 구간(`n_per_sym` 샘플)에 대한 boxcar integrate-and-dump다.

DSP 순서:

1. TX reference payload 로드 (`tx_bb_matrix`, `tx_sym_matrix`, `base_chirp`, PSK preamble metadata)
2. raw AWG waveform lock probe로 capture와 AWG record의 일치 여부 진단
3. `_frame_sync_and_reshape` (`n_chirps=1`)로 프레임 동기화 + SRO/CFO refine
4. Dechirp: $y[n] = r[n] \cdot c^*_{\mathrm{chirp}}[n]$
5. Boxcar integrate-and-dump로 심볼률 심볼 스트림 복구
6. 프레임 앞부분의 알려진 PSK preamble(Zadoff-Chu 위상을 가장 가까운 PSK 성상점에 매핑해 생성)로 잔차 위상/CFO를 1차 선형 피팅으로 추정 및 보정
7. SC-FDE 및 phase/IQ 후보 equalization (`sc_fde_equalizer`, `_equalize_reference_candidates` — 기존 코드 그대로 재사용, 심볼 스트림 형태에 특정 pulse shape을 가정하지 않으므로 변경 불필요)
8. EVM 및 BER 계산

새로 추가된 함수는 `DsoPanel._recover_lfm_qam_symbols_integrate_and_dump()` 하나뿐이다. 이전 TDM 구조 전용이던 pilot-chirp 채널추정/Gardner 코드(`_recover_chirp_symbols`, `_smooth_complex_gain`)는 더 이상 쓰이지 않아 삭제했다.

### 9.4 v1 범위

- PSK order: BPSK/QPSK/8PSK 지원 (`dsp_functions.py`에 Gray-coded 8PSK 매핑 추가).
- Range/Doppler: 1D range profile은 기존 코드로 그대로 계산됨. Range-Doppler map(2D)은 아직 구현하지 않음 (OFDM-ZC 쪽에서 필요해질 때 같이 검토).
- 검증 순서: 시뮬레이션 loopback → 실측 DSO capture (frame_start 반복 안정성, CFR coherence, PSLR, range 정확도 확인) 순으로 진행한다.

## 10. Range / Detection DSP

Range path는 수신 frame과 알려진 TX waveform 사이의 matched filtering을 사용한다.

Per-chirp correlation:

$$
R_i[\ell] = \sum_n r_i[n]s_i^*[n-\ell]
$$

평균 range profile:

$$
R[\ell] =
\frac{1}{N_{\mathrm{chirp}}}
\sum_i |R_i[\ell]|
$$

Range axis는 `Range Mode`에 따라 다음 중 하나를 사용한다.

One-way:

$$
R = c\tau
$$

Monostatic:

$$
R = \frac{c\tau}{2}
$$

`Set Range Zero` 전에는 frame-sync peak 기준 relative range로 표시한다. `Set Range Zero` 후에는 저장된 matched-filter peak delay를 빼고 표시한다.

## 11. Differential CFR Phase-Slope Estimator

`Set Range Zero`에서 기준 CFR을 저장한다.

$$
H_0(f) =
\frac{Y_0(f)X^*(f)}{|X(f)|^2}
$$

이후 capture에서

$$
\frac{H_1(f)}{H_0(f)}
\approx A(f)e^{-j2\pi f\Delta\tau}
$$

이므로 phase slope에서 delay 변화를 추정한다.

$$
\Delta\tau =
-\frac{1}{2\pi}
\frac{d}{df}
\angle\left(\frac{H_1(f)}{H_0(f)}\right)
$$

거리 변화는 `Range Mode`에 따라

$$
\Delta R =
\begin{cases}
c\Delta\tau, & \text{one-way LOS} \\
\frac{c\Delta\tau}{2}, & \text{monostatic radar}
\end{cases}
$$

로 계산한다.

GUI 로그 예시는 다음 형태이다.

```text
[ISAC] differential CFR: dTau=... ps  dR=... mm  coherence=...  mode=...
```

`coherence`는 differential CFR phase consistency를 나타내는 진단 지표이다. 1에 가까울수록 phase slope 추정이 안정적이다.

## 12. 실험 시 주의사항

- AWG CH2 -> DSO CH3 trigger는 time origin을 안정화하지만, 모든 delay uncertainty를 제거하지는 않는다.
- Differential ranging은 trigger cable, connector, DSO trigger setting, AWG output path가 기준 capture와 target capture 사이에서 변하지 않는다고 가정한다.
- 절대 거리 측정에는 여전히 reference calibration이 필요하다.
- Range resolution 주장은 bandwidth-limited formula를 기준으로 해야 한다.
- Sub-mm 결과를 주장할 때는 CFR phase slope 또는 carrier phase 기반 displacement tracking으로 표현하고, SNR, coherence, 반복 측정 표준편차, stage ground truth를 함께 제시해야 한다.

## 13. Full-Duplex DSO Display Plan

Full-duplex 시연에서는 DSO CH1과 CH2를 동시에 capture하고, 같은 trigger 기준에서 두 채널을 나란히 비교한다.

GUI dashboard는 2 x 4 layout을 사용한다.

| Row | Col 1 | Col 2 | Col 3 | Col 4 |
|---|---|---|---|---|
| Selected channel 1 | Time scope | Spectrum | Demod / constellation / status | Range profile |
| Selected channel 2 | Time scope | Spectrum | Demod / constellation / status | Range profile |

동작 방식:

- DSO channel checkbox에서 CH1, CH2를 모두 선택하면 두 row가 모두 채워진다.
- 하나만 선택하면 나머지 row는 빈 창으로 남긴다.
- 세 개 이상 선택하면 capture는 가능하지만 dashboard는 앞의 두 채널만 표시한다.
- Spectrum은 full-duplex 화면에서는 0-25 GHz 범위로 제한해서 보여준다.
- Demodulate는 현재 선택된 첫 번째 채널을 대상으로 실행한다. Range 버튼은 표시 중인 최대 두 채널에 대해 같은 TX reference로 range profile을 계산해 각 row에 표시한다.

Correlation plot은 기본 화면에 항상 띄울 필요가 없다. Frame sync correlation은 디버깅에는 유용하지만, full-duplex 시연 화면에서는 time/spectrum/demod/range를 가리는 부작용이 크다. 따라서 기본값은 숨김이며, 필요할 때만 `Show sync correlation` 옵션으로 표시한다.

Shared-waveform LFM-QAM도 (`n_chirps=1`인 채로) `n_chirps`/`tx_bb_matrix`/`base_chirp` 스키마를 동일하게 채우므로 (§9.2 참고), 이 2×4 대시보드와 `_apply_range_xlim`은 코드 변경 없이 그대로 동작한다.

## 14. Trigger / Clock Lock 판단 기준

Trigger와 clock이 제대로 잡혔는지는 correlation 그림 하나보다 다음 수치들이 더 중요하다.

### 14.1 Frame Start 안정성

동일 조건에서 반복 capture했을 때 `frame_start`가 거의 같은 위치에 있어야 한다.

- 안정적: 반복 capture 간 변화가 수 sample에서 수십 sample 이하
- 의심: 같은 setup에서 `frame_start`가 큰 폭으로 jumping

### 14.2 Sync Score

LFM-QAM frame sync 및 SRO refine 로그의 score를 본다.

```text
[Sync] LFM-QAM SRO refine: start=... sro=... ppm cfo=... kHz score=...
```

권장 해석:

- `score > 0.8`: 매우 양호
- `0.35 < score < 0.8`: 동작은 가능하지만 capture/trigger 상태 확인 필요
- `score < 0.35`: frame lock 신뢰도 낮음

### 14.3 SRO 및 CFO 안정성

공유 reference clock이 없으면 AWG와 DSO 사이에 sample-rate offset이 생길 수 있다. 현재 DSP는 이를 추정하고 보정한다.

확인할 항목:

- `sro`가 반복 capture에서 일정한지
- `cfo`가 작고 안정적인지
- 값 자체보다 run-to-run drift가 큰지 여부가 중요하다

### 14.4 Differential CFR Coherence

`Set Range Zero` 이후 target capture에서 다음 로그를 확인한다.

```text
[ISAC] differential CFR: dTau=... ps dR=... mm coherence=...
```

해석:

- `coherence`가 1에 가까울수록 `H1(f)/H0(f)` phase slope가 안정적이다.
- 낮은 coherence는 trigger instability, path 변화, SNR 부족, multipath 변화, 또는 clock drift를 의심해야 한다.

### 14.5 CH1/CH2 상대 delay drift

Full-duplex 시연에서는 CH1과 CH2의 frame_start 또는 peak delay 차이가 반복 capture에서 안정적인지 확인한다. 절대 delay는 calibration 전에는 의미가 작지만, CH1-CH2 상대 delay가 안정적이면 trigger 기준과 DSO capture timing이 잘 유지되고 있다는 강한 근거가 된다.

## 15. 관련 코드

- `code/isac_unified_gui.py`: GUI, DSO capture, demodulation, LFM-QAM range/DSP
- `code/functions/dso_functions.py`: DSO controller 및 waveform capture
- `code/functions/awg_functions.py`: AWG M8194A download/run/stop SCPI
- `code/functions/dsp_functions.py`: PRBS/QAM mapping, symbol alignment, SC-FDE, SIC helper

## 16. 관련 Concepts

- [[00_system_architecture]]
- [[01_tx_signal_generation]]
- [[02_rx_demodulation]]
- [[03_omt_simulation]]
