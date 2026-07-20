---
title: Symbol-Rate EVM/Resolution Trade-off and SSBI Verification
is_public: false
updated: 2026-07-15
---

# Symbol Rate에 따른 EVM/Resolution Trade-off 및 SSBI 검증

이 문서는 논문 Fig. 3의 symbol-rate/EVM/range-resolution trade-off를 설명하고,
낮은 symbol rate의 EVM floor와 높은 symbol rate의 SSBI 영향을 현재 `Data*.npz`
capture로 어디까지 검증할 수 있는지 정리한다.

> [!important] 현재 핵심 결론
>
> - 낮은 symbol rate의 열화를 **DSO quantization noise만으로 확정할 수 없다**.
> - 기존 복조기는 CPE/SRO/CFO를 이미 충분히 보상하며, 추가 block-CPE 보상에 따른 EVM
>   개선은 최대 0.001 dB 수준이다.
> - 2/4 GBaud에는 out-of-band noise로 설명되지 않는 약 25~27 dB의
>   `AWG + DSO + in-band distortion` residual floor가 존재한다.
> - 높은 symbol rate에서는 guard-band 축소와 passband 비대칭이 SSBI 증가를 지지하지만,
>   현재 capture만으로 SSBI 절대 power를 다른 impairment와 완전히 분리하지는 못했다.
> - `snr_com_db`는 엄밀한 in-band SNR이 아니라 **out-of-band noise-floor 기반 진단값**이다.
> - Photocurrent가 시간에 따라 느리게 변하므로 파일명의 `Iph`와 수동 기록값은 capture 시점의
>   정확한 photocurrent로 사용할 수 없다. 기존 photocurrent 기반 비교와 기울기는 무효/보류한다.
> - Known full-TX-reference LOOCV LS를 적용해도 2 GBaud EVM은 약 −25 dB에 머물렀다.
>   따라서 저속 floor는 제거 가능한 ZC channel-estimation bias가 주원인은 아니다.
> - 현재 저장 EVM pipeline은 이미 full-reference/ref-FDE 후보를 사용한다. 순수 ZC-pilot-only
>   receiver의 EVM으로 해석하면 안 된다.
> - `isac_gui.py`의 component-level 물리 시뮬레이션(`run_isac_sim`)이 4~20 GBaud 측정 EVM을
>   0.1~0.3 dB 이내로, 2 GBaud도 약 1 dB 이내로 재현한다. **저속 구간은 LNA/IF-amp 열잡음과
>   ZBD NEP가 지배**하고(둘이 합쳐 모든 symbol rate에서 거의 일정하게 ~4 dB 기여), **고속
>   구간의 추가 열화는 MZM 3차 광비선형성(=SSBI의 물리적 대응) 때문**이다 — 이 항만 켜둔
>   "electronic-noise-free bound"가 2 GBaud −31.8 dB에서 20 GBaud −21.1 dB로 단조 열화한다.
> - AWG DAC 양자화를 이상적인 균일 quantizer로 모델에 추가하고 ENOB을 4~8 bit로 스윕했지만,
>   2 GBaud만 선택적으로 열화시키지 않았다(오히려 20 GBaud가 약간 더 민감했다). 따라서
>   AWG PAPR 기반 DAC 가설은 이 형태로는 **기각**된다. 자세한 내용은 6절 참고.
> - EVM vs photocurrent(4.5~7 mA, 15/16 GBaud)는 `log10(Iph)` 대비 −20~−22 dB/decade로 깨끗하게
>   선형이다(R²=0.95~0.996) — quadratic UTC-PD photomixing 하 AWGN 이론(−20 dB/decade)과 거의
>   일치한다. 다만 ZBD square-law 물리 시뮬레이션은 더 가파른 −28 dB/decade를 예측해, 실측이
>   이보다 완만한 것은 photocurrent와 무관한 고정 floor의 존재를 정성적으로 다시 지지한다.
>   절대 기울기 보정치로는 여전히 미확정(current-capture 비동기화, 4.5절).

---

## 0. 가장 먼저 필요한 추가 측정 및 분석

현재 데이터의 가장 큰 한계는 AWG, DSO, optical link, SSBI가 한 capture에 모두 포함되어 있고,
photocurrent가 capture와 동기화되어 기록되지 않았다는 점이다. 아래 순서로 분석/측정해야 한다.

### 0.1 완료된 최우선 분석: full-TX-reference estimator 대조

Photocurrent를 사용하지 않고 지금 바로 수행할 수 있는 최우선 분석이다. 동일 raw waveform에
대해 현재의 superimposed-ZC-pilot channel estimator와 known full-TX-reference LS estimator를
각각 적용하고 다음 값을 비교한다.

- 전체 EVM 및 subcarrier별 EVM
- cross-capture shared-error correlation
- channel ripple와 residual PSD
- pilot 제거 전/후 error
- 동일 TX sequence에서 재현되는 error-vector component

분석 결과 full-reference LOOCV에서도 약 25~27 dB floor가 유지됐고, 저장 EVM 대비 개선되지
않았다. 반면 현재 block 수와 `rho=0.2`에서 ZC-only LOOCV는 data contamination 때문에
−3~−13 dB 수준으로 실패했다. 상세 결과는 3.6절에 정리한다.

따라서 다음 실제 우선순위는 0.2절의 측정 신뢰성 복구와 0.3절의 electrical loopback이다.

### 0.2 측정 신뢰성 복구: photocurrent 동시 logging과 안정화

현재 파일명의 `Iph7`, `Iph7.4`, `Iph7.6` 등은 nominal/수동 기록값으로만 취급한다. 서로 다른
capture를 photocurrent가 동일하거나 다르다고 가정해 비교해서는 안 된다. 앞으로는 다음을
DSO trigger와 같은 timestamp로 저장해야 한다.

- capture 전/중/후 photocurrent raw trace
- capture 구간의 mean, standard deviation, min/max 및 linear drift slope
- optical carrier power, signal power 및 가능하면 CSPR
- 장비 warm-up 시간과 설정 변경 후 settling time
- DSO trigger timestamp와 current meter timestamp

측정은 current가 사전 정의한 안정도(예: capture 구간 변화 <0.5%)에 들어온 뒤 시작하고,
조건 순서는 randomized/interleaved 방식으로 배치한다. 안정도 조건을 만족하지 못한 capture는
EVM-vs-current 또는 SSBI power-scaling 분석에서 제외한다.

### 0.3 AWG와 DSO residual EVM 분리

동일한 11 GHz IF, 동일 DFT-s-OFDM waveform, 동일 input power에서 다음 세 가지를 측정한다.

| 측정 구성                | 분리되는 항목                 | 핵심 결과     |
| ------------------------ | ----------------------------- | ------------- |
| M8194A → 고성능 VSA      | AWG DAC/clock/spur residual   | `EVM_AWG`     |
| Low-EVM VSG → UXR        | DSO ADC/noise/jitter residual | `EVM_DSO`     |
| M8194A → UXR direct coax | AWG+DSO+DSP floor             | `EVM_AWG+DSO` |

가능하면 같은 신호를 splitter로 VSA와 UXR에 동시에 넣는다. 각 조건은 최소 20회 반복하고
평균, 표준편차, clipping 여부, 실제 RMS/peak voltage를 함께 저장한다.

### 0.4 동일 DSP 대역에서 noise-state capture

`snr_com_db`처럼 out-of-band PSD median을 사용하는 대신, 실제 통신 복조와 동일한
downconversion/LPF를 통과한 in-band noise를 측정해야 한다.

1. DSO 입력 50 Ω termination
2. Optical carrier on, AWG modulation off
3. AWG on, zero/tone waveform
4. 정상 DFT-s-OFDM waveform

각 단계의 차이로 다음 항목을 추정한다.

| 차분  | 추정 항목                                   |
| ----- | ------------------------------------------- |
| 1     | DSO 자체 noise/ADC floor                    |
| 2 − 1 | shot noise, RIN, optical/LO phase noise     |
| 3 − 2 | AWG spur, MZM 및 link distortion            |
| 4 − 3 | modulation-dependent distortion와 SSBI 후보 |

가장 좋은 in-band 지표는 알려진 TX reference를 동기·equalization한 뒤의 residual이다.

```math
e(t)=y(t)-\hat{h}(t)*x(t), \qquad
\mathrm{SNR}_{res}=10\log_{10}\frac{P_{\hat{h}*x}}{P_e}
```

### 0.5 DSO vertical scale와 analog bandwidth sweep

현재 2 GBaud capture는 UXR 256 GSa/s, 100 mV/div이며 raw peak가 약 242 mV이다.
clipping을 피하면서 full scale을 최대한 사용하는 75~100 mV/div 부근과 200 mV/div를
비교한다. 2 GBaud에서는 11 GHz IF 신호가 통과하는 범위에서 13~16/20/40 GHz analog
bandwidth도 비교한다.

- V/div 또는 bandwidth 감소로 EVM이 개선되면 DSO noise/ENOB 영향
- 변화가 거의 없으면 AWG 또는 link/DSP distortion 가능성 증가
- vertical scale은 peak뿐 아니라 rare peak와 trigger transient까지 포함해 clipping 확인
- 모든 조건에서 0.2절의 동시 photocurrent trace를 저장해 drift를 nuisance variable로 제거

### 0.6 공통 clock 및 block-duration 대조 측정

AWG와 DSO를 공통 10 MHz reference에 lock한 경우와 free-running인 경우를 비교한다.
같은 2 GBaud에서 active subcarrier 수와 block 수를 바꾸는 대조군도 필요하다.

| 변경 변수                      | 원인 판정 기준                                       |
| ------------------------------ | ---------------------------------------------------- |
| Common 10 MHz reference on/off | EVM 개선 시 clock/SRO/CPE 영향                       |
| Active bins 128/256/512/1024   | 좁은 subcarrier spacing에서 악화되면 phase-noise/ICI |
| Block 수 1/2/4/8               | record가 길수록 악화되면 residual clock drift        |
| 동일 `B`, 다른 block duration  | block duration 의존 시 phase tracking 한계           |

### 0.7 SSBI template 및 controlled-power capture 보강

현재 파일당 DFT block 수가 대략 5~17개라 `X`와 `|X|^2`를 독립 regressor로 분리하기
부족하다. 다음 capture에는 최소 50~100개의 서로 다른 data block, per-capture CFR/pilot,
공통 clock 상태, DSO scale/bandwidth, 동기화된 photocurrent trace, optical carrier power 및
CSPR을 저장해야 한다.

Power sweep은 current가 자연 drift하도록 기다리는 방식이 아니라 optical attenuation/carrier
power를 의도적으로 설정하고 안정화 후 측정해야 한다. 각 power point 사이에 reference point를
다시 측정하는 interleaved sequence(예: A-B-A-C-A)를 사용해 slow drift를 추정·보정한다.

---

## 1. Fig. 3의 물리적 목적

광대역에서 SSBI가 문제가 되는 핵심은 SSBI 총 power 자체보다 고정 IF에서 guard-band가
줄어들어 desired passband와 SSBI spectrum이 겹친다는 점이다.

```math
\text{guard margin}=f_{IF}-B/2
```

`f_IF=11 GHz`일 때:

| Symbol rate | Occupied BW `B` | Guard margin `f_IF-B/2` |
| ----------- | --------------- | ----------------------- |
| 2 GBaud     | ~2 GHz          | ~10 GHz                 |
| 8 GBaud     | ~8 GHz          | ~7 GHz                  |
| 12 GBaud    | ~12 GHz         | ~5 GHz                  |
| 20 GBaud    | ~20 GHz         | **~1 GHz**              |

Fig. 3은 다음 두 관계를 함께 보여준다.

- symbol rate 증가 → range resolution `c/(2B)` 개선
- symbol rate 증가 → additive noise bandwidth 증가 및 고속 구간의 effective SSBI 증가

---

## 2. 현재 GUI figure와 이론선의 정의

현재 스크립트는 [plot_evm_tradeoff_gui.py](../code/plot_evm_tradeoff_gui.py)이다.
실행하면 GUI가 바로 열리고 curve/marker 클릭으로 값을 읽을 수 있다.

GUI control:

- `AWGN SNR @ 2 GBd`
- `DSO/ADC SNR floor`
- `SSBI penalty @ 20 GBd`
- `Reset`, `Save`

AWGN과 고정 equipment floor는 power domain에서 합산한다.

```math
\frac{1}{\mathrm{SINR}_{baseline}(B)}=
\frac{1}{\mathrm{SNR}_{AWGN}(B)}+
\frac{1}{\mathrm{SNR}_{equipment}}
```

```math
\mathrm{SNR}_{AWGN}(B)=
\mathrm{SNR}_{ref}-10\log_{10}(B/B_{ref})
```

그 뒤 측정 EVM에서 baseline을 제외한 monotonic effective-SSBI penalty를 적용한다.

```math
\mathrm{SINR}_{total,dB}(B)=
\mathrm{SINR}_{baseline,dB}(B)-P_{SSBI,effective}(B)
```

기본 penalty anchor는 2/4/8/10/12/15/17/20 GBaud에서 대략
`0/0.74/2.17/2.32/2.45/2.85/3.17/3.44 dB`이다. PCHIP 보간을 사용해 단조 증가하도록
했으며, 이전의 hard-overlap 모델 `max(0, 1.5B-f_IF)`에서 나타난 8 GBaud 부근의 인공적인
급변을 제거했다.

> [!warning] 모델 해석
> 이 penalty는 SSBI만 독립적으로 측정한 값이 아니라, AWGN+고정 floor로 설명되지 않는
> **effective residual penalty**이다. 그러므로 논문에서는 `effective SSBI` 또는
> `SSBI-associated excess penalty`로 표현하는 것이 안전하다. GUI의 `DSO/ADC floor`도
> 현재 증거상 순수 DSO가 아니라 AWG+DSO+in-band distortion floor로 해석해야 한다.

정적 논문용 figure만 저장할 때는 다음을 사용한다.

```bash
python plot_evm_tradeoff_gui.py --no-show
```

---

## 3. 낮은 symbol rate의 Spectral SNR–EVM 차이

### 3.1 `snr_com_db`의 실제 정의

`snr_com_db`는 신호 대역 밖 PSD의 median을 noise density로 선택하고 이를 신호 bandwidth만큼
곱해 noise power를 추정한다. 따라서 다음 항목을 놓친다.

- in-band deterministic spur
- AWG/ADC nonlinearity
- phase-noise skirt와 ICI
- residual synchronization error
- signal-dependent distortion
- out-of-band와 다른 in-band noise coloration

따라서 `snr_com_db`는 theoretical SNR이나 EVM-equivalent SNR이 아니라
`OOB-noise-floor SNR`로 부르는 것이 정확하다.

### 3.2 저속 구간의 실측 gap

| Modulation | Symbol rate | `snr_com_db` |  EVM-SNR |         Gap |
| ---------- | ----------: | -----------: | -------: | ----------: |
| 16QAM      |     2 GBaud |     30.39 dB | 25.22 dB | **5.17 dB** |
| 16QAM      |     4 GBaud |     26.16 dB | 23.22 dB | **2.93 dB** |
| 32QAM      |     2 GBaud |     29.86 dB | 25.16 dB | **4.69 dB** |
| 32QAM      |     4 GBaud |     28.33 dB | 23.37 dB | **4.96 dB** |

2 GBaud 16QAM의 경우 OOB SNR이 예측하는 EVM은 약 3.02%지만 실제 EVM은 약 5.48%이다.
독립 impairment라고 가정하면 OOB noise로 설명되지 않는 등가 residual은 약 4.58%이다.

```math
\mathrm{EVM}_{excess}=
\sqrt{\mathrm{EVM}_{measured}^2-\mathrm{EVM}_{OOB-noise}^2}
\approx4.58\%
```

2/4 GBaud에서 계산한 residual은 대략 25~27 dB floor에 해당한다. 저속에서 bandwidth noise가
감소해도 이 floor 아래로 EVM이 개선되지 않는 형태이며, 현재로서는
`AWG + DSO + in-band distortion`의 합으로 봐야 한다.

### 3.3 CPE를 추가 보상한 EVM 재측정

[remeasure_cpe_evm.py](../code/remeasure_cpe_evm.py)로 모든 raw capture를 다시 복조했다.
기존 pipeline과 동일한 SRO/CFO 보정, reference-aided phase tracking, FDE를 적용한 뒤
DFT block마다 추가 phase-only CPE 보상과 oracle complex-gain 보상을 적용했다.

#### 16QAM

| GBaud | 저장 EVM | 재복조 EVM | 추가 block-CPE 후 |  CPE 개선 |
| ----: | -------: | ---------: | ----------------: | --------: |
|     2 |   −25.22 |     −25.22 |            −25.22 | <0.001 dB |
|     4 |   −23.22 |     −23.22 |            −23.22 | <0.001 dB |
|     8 |   −20.68 |     −20.68 |            −20.69 |  0.001 dB |
|    10 |   −19.66 |     −19.66 |            −19.66 | <0.001 dB |
|    12 |   −18.49 |     −18.49 |            −18.49 | <0.001 dB |
|    15 |   −17.42 |     −17.42 |            −17.42 | <0.001 dB |
|    17 |   −16.90 |     −16.90 |            −16.90 | <0.001 dB |
|    20 |   −15.94 |     −15.94 |            −15.94 | <0.001 dB |

#### 32QAM 요약

2/4/8/10/12/17/20 GBaud 전 구간에서 추가 CPE 개선은 최대 0.001 dB였다. Block별 amplitude와
phase를 모두 oracle로 보정해도 최대 개선은 약 0.003 dB였다.

따라서 **CPE를 더 보상하면 OOB SNR에 가까워진다는 가설은 현재 데이터에서 기각**된다.
기존 DSP가 이미 CPE를 사실상 충분히 제거했다.

초기 frequency-domain residual 분석에서는 2 GBaud에서 block별 complex correction으로
1.49 dB가 개선됐지만, 이는 DFT despreading과 최종 equalization 전의 지표이며 amplitude/channel
fitting까지 포함한다. 최종 constellation EVM 개선량으로 해석하면 안 된다.

재측정 결과:

- [cpe_evm_remeasurement.csv](../code/data/captures/bandwidth/cpe_evm_remeasurement.csv)
- [cpe_evm_remeasurement_32qam.csv](../code/data/captures/bandwidth/cpe_evm_remeasurement_32qam.csv)

### 3.4 장비 한계 가설의 현재 상태

- M8194A는 8-bit DAC이며 finite ENOB/SFDR를 가지므로 AWG residual floor가 유력하다.
- 2 GBaud AWG waveform의 PAPR은 약 10.9 dB라 평균 DAC range 사용률이 낮다.
- UXR capture는 100 mV/div이고 raw peak 약 242 mV라 vertical range 최적화 여지가 있다.
- 그러나 UXR nominal broadband noise를 2 GHz에 단순 환산한 값만으로는 25 dB EVM floor를
  전부 설명하기 어렵다.

따라서 AWG 또는 DSO 중 하나를 단독 원인으로 선언하지 말고 0.3절의 electrical loopback으로
분리해야 한다.

### 3.5 상위 `captures` 폴더의 저속 데이터 교차검증

기존 `captures/bandwidth` 외에 상위 `captures`에 저장된 IF 12 GHz 저속 sweep을 추가로
분석했다. 이 데이터는 기존 sweep과 DSO 조건이 크게 달라 독립 대조군 역할을 한다.

| 데이터           |     IF |    DSO Fs |      Scale | 파일의 `Iph` label | 2-GBd OOB SNR | 2-GBd EVM |
| ---------------- | -----: | --------: | ---------: | -----------------: | ------------: | --------: |
| 기존 `bandwidth` | 11 GHz | 256 GSa/s | 100 mV/div |    7.0 mA (미검증) |      30.39 dB | −25.22 dB |
| 상위 `captures`  | 12 GHz |  64 GSa/s |  70 mV/div |    7.4 mA (미검증) |      29.29 dB | −25.43 dB |

DSO sample rate, vertical scale, IF 및 OOB floor가 바뀌었는데도 2 GBaud EVM은 0.21 dB 차이로
거의 동일하다. 다만 실제 photocurrent가 capture와 동기화되지 않았으므로 두 행이 같은 optical
operating point라는 보장은 없고, 이 비교의 증거 수준은 **시사적**으로 제한한다. OOB noise를
power-domain에서 제외한 residual SNR은 2 GBaud
세 파일에서 26.79/26.97/27.73 dB이고, 4~6 GBaud에서 대부분 25.0~27.5 dB이다. 따라서
약 26 dB의 저속 floor가 여러 장비 설정에서 반복된다는 관찰은 유지되지만, current drift를
통제한 재측정 전에는 이를 특정 DSO 설정보다 공통 AWG/waveform/link/DSP residual이라고
확정할 수 없다.

저장 voltage step도 기존 13.05 µV에서 새 데이터 9.58 µV로 작아졌지만 EVM floor는 유지됐다.
저장 TX waveform에 이상적인 DAC quantization만 적용한 대조 simulation은 다음 결과를 보였다.

| Ideal DAC bits | Recovered EVM |
| -------------: | ------------: |
|          4 bit |     −29.87 dB |
|          5 bit |     −36.94 dB |
|          6 bit |     −41.70 dB |
|          8 bit |     −45.56 dB |

따라서 **이상적인 8-bit code quantization 자체는 −25 dB floor를 설명하지 못한다**. 실제 AWG의
frequency-dependent ENOB, spur, memory/nonlinearity 또는 optical/electrical link distortion은
여전히 가능하다.

#### 동일 TX sequence의 error-vector 반복성

[analyze_low_rate_repeatability.py](../code/analyze_low_rate_repeatability.py)로 bit-identical TX QAM
matrix를 사용한 capture 쌍의 equalized error vector를 교차상관했다.

| GBaud | 비교 조건                      | Error correlation `ρ` | Shared-error EVM |
| ----: | ------------------------------ | --------------------: | ---------------: |
|     2 | IF 11/12 GHz, DSO 256/64 GSa/s |             **0.479** |        −28.46 dB |
|     4 | IF 11 vs 12 GHz                |           0.363~0.374 | −27.09~−26.88 dB |
|     4 | IF 12 GHz 반복쌍               |             **0.494** |        −25.13 dB |
|     8 | IF 11 vs 12 GHz                |           0.223~0.261 | −26.95~−26.16 dB |
|     8 | IF 12 GHz 반복쌍               |                 0.222 |        −26.63 dB |

순수 DSO/thermal/shot noise라면 서로 다른 capture의 complex error vector 상관은 0에 가까워야
한다. 2/4 GBaud에서 `ρ≈0.36~0.49`라는 결과는 error power의 상당 부분이 동일 waveform에서
반복되는 **deterministic, sequence-dependent distortion**임을 보여준다. 반면 constellation
point별 평균 error가 설명하는 비율은 약 4%뿐이므로 단순 memoryless AM/AM compression보다는
다음 원인이 더 유력하다.

- AWG/MZM/link의 frequency-selective 또는 memory distortion
- DSO ADC의 deterministic INL/DNL 또는 frequency-response distortion
- superimposed ZC pilot 제거 오차
- data-contaminated pilot/channel estimate의 bias
- DFT-s-OFDM block/FDE에 남는 deterministic waveform-dependent error

이 결과도 AWG와 DSP 중 어느 쪽인지 단독으로 분리하지는 못한다. Ideal waveform replay,
AWG→VSA 측정, 그리고 동일 raw waveform에 대한 alternative channel estimator 비교가 다음 단계다.

결과: [low_rate_error_repeatability.csv](../code/data/captures/low_rate_error_repeatability.csv)

### 3.6 ZC-pilot 대 known full-TX-reference channel estimator

[compare_dfts_channel_estimators.py](../code/compare_dfts_channel_estimators.py)로 동일 raw capture에
두 channel estimator를 적용했다.

#### 비교 방법

- **ZC-only LOOCV**: 평가 block을 제외한 다른 block의 반복 ZC pilot으로 channel을 추정한다.
  서로 다른 data block은 pilot estimate의 contamination으로 취급해 cross-block LS와 frequency
  smoothing으로 억제한다.
- **Full-TX LOOCV**: 평가 block을 제외한 다른 block의 알려진 전체 TX waveform으로
  `Y[m,k]=c[m]H[k]X[m,k]+N[m,k]`를 alternating LS로 추정한다.
- 평가 block마다 하나의 complex gain/CPE만 제거하고 frequency-selective channel은 training
  block에서만 얻는다.
- 같은 block의 `Y/X`로 channel을 추정하고 같은 block EVM을 계산하는 in-sample 방식은
  residual을 channel에 흡수하므로 사용하지 않는다.

```math
\hat H_k^{(-i)}=
\underset{H_k,c_m}{\arg\min}
\sum_{m\ne i}\left|Y_{m,k}-c_m H_k X_{m,k}\right|^2
```

#### 저속 16QAM 결과

| GBaud |     IF |  저장 EVM | ZC-only LOOCV | Full-TX LOOCV | Full-TX 대 저장값 |
| ----: | -----: | --------: | ------------: | ------------: | ----------------: |
|     2 | 11 GHz | −25.22 dB |      −3.02 dB |     −24.76 dB |      0.46 dB 악화 |
|     2 | 12 GHz | −25.43 dB |     −12.75 dB |     −24.98 dB |      0.45 dB 악화 |
|     4 | 11 GHz | −23.22 dB |     −12.55 dB |     −22.81 dB |      0.41 dB 악화 |
|     4 | 12 GHz | −22.49 dB |      −7.64 dB |     −21.78 dB |      0.71 dB 악화 |
|     4 | 12 GHz | −22.01 dB |     −12.49 dB |     −21.61 dB |      0.40 dB 악화 |
|     5 | 12 GHz | −22.50 dB |     −12.83 dB |     −22.08 dB |      0.42 dB 악화 |
|     6 | 12 GHz | −21.91 dB |     −12.41 dB |     −21.32 dB |      0.59 dB 악화 |
|     8 | 11 GHz | −20.68 dB |      −9.97 dB |     −20.82 dB |      0.14 dB 개선 |
|     8 | 12 GHz | −19.98 dB |      −9.55 dB |     −19.62 dB |      0.36 dB 악화 |
|     8 | 12 GHz | −20.20 dB |      −7.55 dB |     −19.81 dB |      0.39 dB 악화 |

#### 해석

1. **Full-TX LOOCV가 저속 EVM floor를 개선하지 못했다.** 2 GBaud에서 두 독립 capture 모두
   약 −25 dB에 머물렀다. 따라서 단순 ZC channel-estimation bias를 제거하면 OOB SNR
   29~30 dB에 접근한다는 가설은 기각된다.
2. 저장 EVM은 full-TX LOOCV보다 대부분 0.4~0.7 dB 좋다. 코드 확인 결과 현재
   `_recover_dfts_ofdm_symbols`는 `pilot-FDE`, `ref-scalar`, `ref-FDE`와 decision-directed 후보를
   exact TX reference metric으로 비교해 가장 좋은 경로를 선택한다. 즉 저장 EVM은 이미
   reference-aided이며, deployable ZC-only receiver 성능보다 낙관적이다.
3. ZC-only LOOCV가 매우 나쁜 이유는 pilot power ratio `rho=0.2`이고 유효 block이 약 5~10개라
   반복 pilot 평균만으로 data contamination을 충분히 제거하지 못하기 때문이다. ZC-only
   receiver를 사용하려면 pilot power/block 수 증가, pilot/data orthogonalization 또는 별도
   training block이 필요하다.
4. Full-TX LOOCV에서도 남는 약 25~27 dB floor는 AWG/DSO/link의 deterministic distortion,
   random in-band noise 및 full-reference 모델로 설명되지 않는 time-varying channel의 합이다.
   원인 분리는 0.2~0.4절의 동기 current logging, electrical loopback 및 noise-state 측정이
   필요하다.

결과: [dfts_channel_estimator_comparison.csv](../code/data/captures/dfts_channel_estimator_comparison.csv)

---

## 4. 높은 symbol rate의 SSBI 검증

### 4.1 Guard-band 기하학

`B` 증가에 따라 `f_IF-B/2`가 줄어드는 것은 정의상 확실하다. 20 GBaud에서 guard margin이
약 1 GHz까지 감소하므로 DC 주변 square-law spectrum과 desired passband의 overlap 가능성이
가장 크다.

### 4.2 근접-DC spectrum

Raw C1 spectrum에서 DC 근처 0.05~1.5 GHz와 passband 인접 noise floor를 비교했다.

| Symbol rate | Noise floor |                  근접-DC 창 |       초과분 |
| ----------- | ----------: | --------------------------: | -----------: |
| 2 GBaud     |    −91.0 dB |                    −77.4 dB | **+13.6 dB** |
| 4 GBaud     |    −91.1 dB |                    −79.6 dB | **+11.4 dB** |
| 8 GBaud     |    −87.3 dB |                    −85.2 dB |      +2.1 dB |
| 12 GBaud    |    −87.5 dB |                    −85.8 dB |      +1.7 dB |
| 20 GBaud    |    −90.0 dB | passband 잠식으로 측정 불가 |            — |

이는 DC 근처 square-law/SSBI 성분의 **존재**를 확인하지만, PSD 높이만으로 passband에 들어온
SSBI power를 정량화하지는 못한다. `B`가 증가하면 같은 distortion power가 더 넓게 퍼져
국소 PSD는 낮아질 수 있다.

### 4.3 Passband lower/upper-half 비대칭

저장된 `range_zero__C1__cfr_h`는 여러 파일에서 동일한 stale reference였으므로 사용하지 않고,
각 capture 고유의 `rx__C1__sig` raw spectrum을 사용했다.

| GBaud | Lower-half floor | Upper-half floor | Lower − Upper |
| ----: | ---------------: | ---------------: | ------------: |
|     2 |         −73.4 dB |         −71.7 dB |      −1.75 dB |
|     4 |         −76.5 dB |         −75.6 dB |      −0.93 dB |
|     8 |         −77.6 dB |         −77.2 dB |      −0.43 dB |
|    10 |         −78.6 dB |         −78.4 dB |      −0.27 dB |
|    12 |         −78.8 dB |         −78.6 dB |      −0.25 dB |
|    15 |         −79.5 dB |         −79.4 dB |      −0.14 dB |
|    17 |         −79.6 dB |         −80.6 dB |      +1.00 dB |
|    20 |         −79.0 dB |         −81.7 dB |  **+2.76 dB** |

17 GBaud 부근에서 부호가 바뀌고 20 GBaud에서 DC 쪽 lower half가 2.76 dB 더 나빠진다.
이는 high-`B`에서 SSBI가 passband 하단을 침범한다는 가설을 지지하는 강한 상대 지표다.
다만 signal spectral shape와 receiver response의 비대칭도 포함할 수 있으므로 절대 SSBI power는 아니다.

### 4.4 Subcarrier별 SSBI 정량 추정 시도와 한계

[estimate_subcarrier_ssbi.py](../code/estimate_subcarrier_ssbi.py)에서 두 estimator를 시험했다.

#### 모델 1: desired signal residual

```math
Y_{m,k}=H_kX_{m,k}+E_{m,k}
```

Subcarrier별 LS channel을 제거하고 lower/upper residual을 비교했지만 SSBI penalty가
2 GBaud 약 0.97 dB, 20 GBaud 약 0.52 dB로 나와 예상 경향과 반대였다. SSBI가 `X`와
상관된 성분이므로 `H_k` 추정에 흡수된 것이 주요 원인이다.

#### 모델 2: square-law template 추가

```math
Y_{m,k}=H_kX_{m,k}+G_kQ_{m,k}+N_{m,k},
\qquad Q(t)=|x(t)|^2-\mathrm{mean}
```

이 모델은 8 GBaud에서 약 0.83 dB만 검출하고 10~20 GBaud에서는 거의 0 dB를 반환했다.
실제 optical/electrical channel이 단순 `|x|^2` template을 변형하고, block 수가 적으며,
`X`와 `Q`의 collinearity가 커서 `G_k`를 안정적으로 식별하지 못했다.

따라서 현재 estimator 결과는 **identifiable lower bound/진단값**일 뿐, 논문에서 SSBI 절대
power로 사용하면 안 된다. 0.7절의 capture 보강 또는 carrier-off/CSPR 대조 측정이 필요하다.

### 4.5 Photocurrent sweep — current drift로 인해 절대 보정 근거에서는 제외, 그러나 추세는 물리적으로 유의미

16QAM 15 GBaud, 32QAM 16 GBaud 실측 (32QAM 행은 과거 버전에서 "15 GBaud"로 잘못 표기되어
있었다 — 원본 스프레드시트 헤더 기준 16 GBaud로 정정):

| 기록된 `Iph` label (mA, 미검증) | 16QAM EVM (dB) | 32QAM EVM (dB) |
| ------------------------------: | -------------: | -------------: |
|                             4.5 |         −13.78 |         −13.48 |
|                             5.0 |         −14.45 |         −13.68 |
|                             5.5 |         −15.55 |         −14.53 |
|                             6.0 |         −16.22 |         −15.39 |
|                             6.5 |         −16.90 |         −16.57 |
|                             7.0 |         −17.59 |         −17.49 |

위 표의 photocurrent는 capture 시점에 동기화된 값이 아니며 실제 current가 시간에 따라 느리게
변했다. 따라서 **절대 기울기를 정량 보정치로 사용하는 것은 여전히 보류**한다 — capture 순서에
따른 다른 drift(온도, 정렬 등)가 우연히 같은 방향으로 겹쳤을 가능성을 배제할 수 없다. 다만 아래
분석은 이 데이터가 순수 노이즈가 아니라 **물리적으로 그럴듯한 추세**를 담고 있다는 근거를
제공하므로, 재측정의 우선순위를 정하는 데는 참고할 수 있다.

**EVM(dB) vs `log10(Iph)` 선형 fit** ([plot_evm_photocurrent_figure.py](../code/plot_evm_photocurrent_figure.py)):

| 계열 | Fit 기울기 [dB/decade] | R² |
| --- | ---: | ---: |
| 16QAM @ 15 GBaud | −20.2 | 0.996 |
| 32QAM @ 16 GBaud | −21.8 | 0.947 |

UTC-PD photomixing은 `calc_utcpd_output_dbm`에서 `P_THz ∝ Iph²` (quadratic law)이므로, 시스템이
순수 열잡음(AWGN)-limited라면 이론적으로 −20 dB/decade가 나와야 한다. 측정 기울기(−20.2,
−21.8 dB/decade)는 이 예측과 거의 정확히 일치하며, R²가 0.95~0.996으로 매우 높아 6개 점이
우연이 아니라 뚜렷한 단조 관계를 따른다.

`isac_gui.run_isac_sim`으로 같은 조건(rx_mode=ZBD, 동일 파라미터 프리셋)에서 photocurrent만
스윕하면:

| 계열 | Sim EVM @ 4.5 mA | Sim EVM @ 7.0 mA | Sim fit 기울기 |
| --- | ---: | ---: | ---: |
| 16QAM @ 15 GBaud | −12.08 dB | −17.50 dB | −28.3 dB/decade |
| 32QAM @ 16 GBaud | −11.76 dB | −17.15 dB | −28.1 dB/decade |

7 mA 지점은 측정과 0.1~0.3 dB 이내로 맞지만(6.1절 baseline 재현도와 일관), **시뮬레이션의
기울기(약 −28 dB/decade)가 측정 기울기(약 −20~−22 dB/decade)보다 뚜렷이 가파르다.** ZBD는
square-law(envelope) detector라서 순수 선형-detection AWGN 이론(−20 dB/decade)보다 가파른
반응이 예상되는데, 실측은 오히려 더 완만하다. 이는 6.4절에서 확인한 것과 같은 방향의
현상이다 — **photocurrent에 무관한 고정 floor(0.3~0.4절에서 분리하려는 AWG/DSO/link
residual)가 존재하면, photocurrent를 올려도 그 floor 밑으로는 개선이 안 되므로 실측 곡선이
이상적인 square-law 예측보다 완만해진다.** 즉 이 기울기 차이 자체가 "저속·중간 symbol rate
floor"가 실재한다는 독립적인 정성적 증거로 볼 수 있다.

재측정은 0.2절의 동시 current logging과 안정도 조건을 만족하고, 0.7절의 interleaved power
sequence를 사용한 경우에만 절대 보정 근거로 채택한다. 다만 위 fit이 이미 상당히 깨끗하므로,
동기화된 재측정에서도 비슷한 기울기가 재현될 가능성이 높다.

---

## 5. 증거 수준과 논문 표현

| 주장                                     | 현재 증거                            | 판정                 |
| ---------------------------------------- | ------------------------------------ | -------------------- |
| `B` 증가 시 guard margin 감소            | 기하학적 정의                        | **확정**             |
| High-`B`에서 DC 쪽 passband 열화         | lower/upper 비대칭 −1.75→+2.76 dB    | **강하게 지지**      |
| DC 근처 square-law/SSBI 성분 존재        | DC hump 11~14 dB 초과                | **확인**             |
| SSBI 절대 power가 `B`에 따라 증가        | subcarrier estimator 불안정          | **미확정**           |
| 2 GBaud 열화의 원인이 CPE                | 추가 CPE 개선 <0.001 dB              | **기각**             |
| 2 GBaud floor의 원인이 ZC estimator bias | Full-TX LOOCV도 약 −25 dB            | **주원인 가설 기각** |
| 현재 저장 EVM이 ZC-only receiver 성능    | ref-FDE/full-reference 후보를 사용   | **아님**             |
| 2 GBaud 열화의 원인이 DSO 단독           | 분리 측정 없음                       | **미확정**           |
| 저속에 고정 equipment/in-band floor 존재 | residual 약 25~27 dB                 | **강하게 지지**      |
| EVM의 photocurrent 의존성/기울기         | current와 capture 비동기, slow drift | **무효/재측정 필요** |
| `snr_com_db`가 true in-band SNR          | OOB median 기반 계산                 | **아님**             |

논문에서는 다음처럼 제한적으로 표현하는 것이 안전하다.

> At low symbol rates, the EVM is limited by an approximately bandwidth-independent
> residual measurement/transceiver floor that cannot yet be assigned uniquely to the
> AWG or DSO. At high symbol rates, the shrinking IF guard band and the observed
> near-DC-side passband asymmetry support an increasing SSBI-associated penalty.

Photocurrent-dependent scaling은 current trace가 capture와 동기화된 재측정을 확보하기 전까지
논문 근거와 fitting에서 제외한다.

---

## 6. `isac_gui.py` 물리 시뮬레이션 기반 교차검증

측정과 별개로 `isac_gui.py`의 component-level 시뮬레이션(`run_isac_sim`)이 저장된 GUI 파라미터
프리셋([isac_sim_params_20260715_145824.json](../code/data/isac_sim_params_20260715_145824.json),
16QAM/32QAM DFT-s-OFDM, ZBD 수신, free-running coherence)으로 실제 측정 EVM을 얼마나 재현하는지
확인했다. One-way comm 경로만 사용하므로 radar self-interference/RCS 등 복잡한 항은 관여하지
않는다.

### 6.1 Baseline 재현도

시드 4개 평균(block 수는 실측과 동일하게 baud당 5~17개):

| GBaud | 측정 (16QAM) | Sim baseline | 측정 (32QAM) | Sim baseline |
| ----: | -----------: | -----------: | -----------: | -----------: |
|     2 |       −25.22 |       −26.24 |       −25.16 |       −26.31 |
|     4 |       −23.22 |       −23.47 |       −23.37 |       −23.50 |
|     8 |       −20.68 |       −20.45 |       −19.76 |       −20.43 |
|    10 |       −19.66 |       −19.44 |       −19.80 |       −19.42 |
|    12 |       −18.49 |       −18.55 |       −18.71 |       −18.56 |
|    15 |       −17.42 |       −17.51 |       −17.49 |       −17.49 |
|    17 |       −16.90 |       −16.88 |       −16.50 |       −16.89 |
|    20 |       −15.94 |       −16.05 |       −15.77 |       −16.05 |

4~20 GBaud 전 구간이 0.1~0.7 dB 이내로 맞는다. 즉 이미 알려진 장비 스펙(LNA/IF-amp NF, ZBD
responsivity/NEP, DSO ADC noise, laser linewidth, MZM Vpi/bias/EO 대역폭)만으로 measured EVM
곡선의 형태 대부분이 설명된다 — 미지의 메커니즘을 가정할 필요가 없다.

### 6.2 Impairment ablation: 무엇이 dominant한가

각 impairment를 개별적으로 최소화하고 baseline과의 EVM 차이(dB)를 봤다
([sim_evm_impairment_sweep.py](../code/sim_evm_impairment_sweep.py),
[sim_impairment_sweep_16QAM.csv](../code/data/sim_impairment_sweep_16QAM.csv),
[sim_impairment_sweep_32QAM.csv](../code/data/sim_impairment_sweep_32QAM.csv)):

| 제거한 impairment | 2 GBaud 개선 | 20 GBaud 개선 | Symbol rate 의존성 |
| ------------------------------ | -----------: | ------------: | -------------------------- |
| LNA + IF-amp 열잡음 (NF→0) | 2.06 dB | 1.87 dB | 거의 flat |
| ZBD NEP | 1.85 dB | 1.73 dB | 거의 flat |
| DSO ADC 양자화 잡음 | 0.22 dB | 0.20 dB | 거의 flat |
| AWG DAC 양자화 (8→16 bit) | 0.01 dB | 0.01 dB | 무시 가능 |
| Laser phase noise + carrier wander | ~0.00 dB | ~0.00 dB | 무시 가능 |

**결론: AWGN 성격의 항(열잡음 + ZBD NEP)이 모든 symbol rate에서 지배적이며, 합쳐서 약 4 dB의
거의 고정된 예산을 차지한다.** 이는 baud에 무관하게 균일하므로 "2/4 GBaud만 유독 나쁜" 현상을
설명하지 못한다. 두 양자화 항(AWG DAC, DSO ADC)은 현재 스펙에서는 부차적이다. ZBD 구조상
(square-law envelope detector) narrow-linewidth laser phase noise/carrier wander에는 거의
영향받지 않는다.

### 6.3 SSBI의 물리적 대응: MZM 비선형성만 남긴 bound

위 표의 모든 잡음원(열잡음, ZBD NEP, DSO/AWG 양자화, phase noise)을 동시에 최소화하면 남는
것은 MZM의 3차 Taylor-model 광비선형성뿐이다. 이 "electronic-noise-free bound"는 symbol rate에
따라 뚜렷하게 나빠진다.

| GBaud | MZM-비선형성-only bound |
| ----: | -----------------------: |
|     2 |                  −31.8 dB |
|     4 |                  −29.7 dB |
|     8 |                  −26.6 dB |
|    10 |                  −25.4 dB |
|    12 |                  −24.3 dB |
|    15 |                  −23.0 dB |
|    17 |                  −22.2 dB |
|    20 |                  −21.1 dB |

2→20 GBaud 사이 10.7 dB나 열화한다. 즉 **SSBI의 물리적 대응물인 MZM 비선형성은 baud-selective
하며, guard-band가 줄어드는 고속 구간에서만 유의미**하다: 2 GBaud에서는 bound가 baseline보다
5.5 dB 낮아(=noise floor 대비 무시 가능) AWGN이 완전히 지배하지만, 20 GBaud에서는 bound와
baseline의 차이가 약 5 dB로 좁혀져 MZM 비선형성이 총 열화의 상당 부분을 차지하기 시작한다.
이는 1절의 guard-margin 논리 및 4.3절의 passband 비대칭 반전(17→20 GBaud)과 정확히 같은
그림이다.

### 6.4 2 GBaud만의 ~1 dB gap: AWG DAC 양자화 가설 기각

사용자가 GUI에서 직접 읽은 값(2/4/15/20 GBaud = −26.3/−23.5/−17.5/−16.0 dB)은 baseline
시뮬레이션과 거의 일치했지만, 측정값과 비교하면 2 GBaud만 약 1 dB 차이가 난다(4~20 GBaud는
0.1 dB 이내). PAPR이 높은 low-rate DFT-s-OFDM 파형이 AWG DAC의 실효 dynamic range를 더 적게
쓸 것이라는 가설로 `awg_dac_bits` 파라미터를 추가하고(`isac_gui.py`의
`apply_awg_dac_quantization`, 파형 자체 peak 기준 균일 quantizer) ENOB을 4~8 bit로 낮춰봤다.

| ENOB [bit] | 2 GBaud EVM | 20 GBaud EVM |
| ---------: | ----------: | -----------: |
|         8 |     −26.24 dB |     −16.04 dB |
|         6 |     −26.13 dB |     −15.94 dB |
|         5 |     −25.89 dB |     −15.63 dB |
|         4 |     −24.96 dB |     −14.63 dB |

ENOB을 낮추면 두 rate가 거의 동일하게(오히려 20 GBaud가 살짝 더) 나빠진다 — 2 GBaud만 선택적으로
나빠지는 효과가 없다. **따라서 "낮은 symbol rate의 높은 PAPR 때문에 AWG DAC 양자화가 더
문제된다"는 가설은 이 형태로는 기각한다.** 남은 ~1 dB gap은 특정 impairment로 재현되지 않으며,
3.5절에서 이미 관찰된 것처럼 서로 다른 장비 조건에서도 저속 floor가 0.2~0.7 dB 수준으로
흔들리는 것과 같은 **측정 스캐터 범위 안**일 가능성이 높다 — 5개 DFT block만 평균하는 조건에서는
특히 그렇다.

### 6.5 다음 물리 측정 제안: AWG→DSO 직결 + Vpp sweep

0.3절의 "AWG+DSO 분리 측정" 계획을 이 결과가 더 구체화한다. 현재 모델대로라면 MZM/UTC-PD/LNA/ZBD를
모두 제거하고 AWG를 RF 케이블로 DSO에 직결하면, 남는 건 AWG DAC + 케이블 + DSO 프론트엔드/ADC뿐이고
시뮬레이션상 이 조합은 EVM에 0.2~0.3 dB만 기여해야 한다 — 즉 직결 측정은 optical/RF chain 전체
없이도 훨씬 낮은(예: −35 dB 이하) EVM이 나와야 한다는 것이 현재 모델의 예측이다.

Vpp를 sweep하면서 이 직결 구성으로 raw data를 측정하는 것은 **의미가 있고, 지금 시점에서 가장
결정적인 다음 측정**이다. 두 가지 상반된 결과가 가능하며 각각이 강하게 판별적이다.

- **직결 EVM이 −25~−27 dB 근처에서 floor를 보이면** (Vpp를 아무리 최적화해도), 현재 시뮬레이션이
  AWG/DSO 기여를 과소평가하고 있다는 뜻이다 — 실제 AWG의 non-ideal ENOB, DNL/INL, 주파수 의존
  spur, 또는 DSO clock jitter처럼 지금 모델에 없는 항을 추가해야 한다.
- **직결 EVM이 뚜렷하게 더 좋으면** (예: −35 dB 이상), 현재 모델의 결론 — 저속 floor는
  LNA/ZBD 열잡음이 지배하고 AWG/DSO는 부차적이다 — 이 확인된다.

Vpp sweep 자체는 quantization-limited 영역(신호가 작을수록 step 대비 SNR 저하)과 고정
noise-floor-limited 영역(신호 크기와 무관하게 일정한 EVM)을 구분하는 표준적인 진단이므로, 한
symbol rate만이 아니라 **2 GBaud와 15~20 GBaud 양쪽에서** 수행해 low-rate floor가 순수 전기
경로만으로 재현되는지 확인해야 한다. 0.2절의 photocurrent 동시 logging 문제와 무관하게 지금
바로 수행할 수 있는 측정이라는 점도 우선순위를 높인다.

관련 코드: [sim_evm_impairment_sweep.py](../code/sim_evm_impairment_sweep.py) (ablation 스윕),
`isac_gui.py`의 `apply_awg_dac_quantization`/`SimConfig.awg_dac_bits` (AWG DAC 양자화 모델),
[plot_evm_tradeoff_gui.py](../code/plot_evm_tradeoff_gui.py) (측정+물리 시뮬레이션 결합 Fig. 3).

---

## 관련 파일

- [plot_evm_tradeoff_gui.py](../code/plot_evm_tradeoff_gui.py) — 측정 EVM + `isac_gui.run_isac_sim` 물리 시뮬레이션 결합 Fig. 3 GUI
- [plot_evm_photocurrent_figure.py](../code/plot_evm_photocurrent_figure.py) — EVM vs photocurrent 측정+fit+물리 시뮬레이션 비교 (4.5절)
- [sim_evm_impairment_sweep.py](../code/sim_evm_impairment_sweep.py) — impairment별 ablation 스윕(6절), `sim_impairment_sweep_{16,32}QAM.csv` 생성
- [remeasure_cpe_evm.py](../code/remeasure_cpe_evm.py) — 저장 raw capture의 CPE 보상 EVM 재측정
- [analyze_low_rate_repeatability.py](../code/analyze_low_rate_repeatability.py) — 동일 TX sequence의 cross-capture error 상관 분석
- [compare_dfts_channel_estimators.py](../code/compare_dfts_channel_estimators.py) — ZC-only와 full-TX LOOCV LS channel estimator 비교
- [estimate_subcarrier_ssbi.py](../code/estimate_subcarrier_ssbi.py) — subcarrier residual 및 square-law template SSBI 진단
- [check_ssbi_noise_floor.py](../code/check_ssbi_noise_floor.py) — 근접-DC spectrum 진단
- [check_subcarrier_ssbi.py](../code/check_subcarrier_ssbi.py) — passband lower/upper-half 비대칭
- [read_range_data.py](../code/read_range_data.py) — NPZ metric/spectrum 공통 함수
- [system_model_paper_ready.md](system_model_paper_ready.md) — SSBI/SINR 수식 유도
- [04_dso_dsp_and_differential_ranging.md](04_dso_dsp_and_differential_ranging.md) — DSO/DSP 및 `snr_com_db` 파이프라인
