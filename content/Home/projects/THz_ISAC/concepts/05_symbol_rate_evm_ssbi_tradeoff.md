---
title: Symbol-Rate EVM, SNR, and SSBI Trade-off
is_public: false
updated: 2026-07-22
---

# Symbol rate에 따른 EVM, SNR 및 SSBI 분석

## 1. 분석 목적

논문용 symbol-rate figure는 동일한 32QAM DFT-s-OFDM 신호에 대해 다음 결과를 비교한다.

1. 실험에서 측정한 EVM
2. 대역폭 잡음만 고려한 이론적 SNR과 SSBI를 추가한 SINR
3. `isac_gui.py`의 전체 time-domain simulation EVM

Figure 생성 코드는 `code/plot_evm_tradeoff_gui.py`이며 기본 simulation preset은
`code/data/isac_sim_params_20260720.json`이다. 모든 EVM은 power-domain quantity로 변환한 후
합성하며, plot에서는 EVM 등가값인 `-SNR`과 `-SINR`을 EVM 축에 표시한다.

## 2. 이론 모델

수신 신호 전력이 일정하고 white receiver noise가 지배적이면 noise power는 대역폭에 비례한다.

```math
N(B)=kTBF, \qquad
\mathrm{SNR}(B)=\mathrm{SNR}(B_0)-10\log_{10}\frac{B}{B_0}.
```

AWGN 채널에서는 정규화 EVM과 SNR 사이에 다음 근사가 성립한다.

```math
\mathrm{EVM}^2 \simeq \frac{1}{\mathrm{SNR}}, \qquad
\mathrm{EVM}_{\mathrm{dB}}\simeq-\mathrm{SNR}_{\mathrm{dB}}.
```

SSBI를 독립적인 interference power로 모델링하면

```math
\frac{1}{\mathrm{SINR}(B)}
=\frac{1}{\mathrm{SNR}(B)}+\frac{1}{\mathrm{SIR}_{\mathrm{SSBI}}(B)},
```

이고 EVM domain에서는

```math
\mathrm{EVM}_{\mathrm{SINR}}^2
=\mathrm{EVM}_{\mathrm{SNR}}^2+\mathrm{EVM}_{\mathrm{SSBI}}^2.
```

이론 SNR 선은 2/4 GBd 측정점에 `10log10(B)` 기울기를 constrained fitting하여 정한다.
SSBI 항은 additive noise를 끈 MZM Taylor + ZBD square-law simulation에서 얻되, 4 GBd의
고정 nonlinear floor를 제거하고 symbol-rate에 따라 증가하는 excess power만 사용한다. 따라서
저속에서는 의도적으로 `SINR = SNR`이며, 고속에서만 두 선이 분리된다.

### 2.1 2 GBd와 20 GBd EVM 차이 검산

전체 simulation EVM은 AWGN만의 EVM이 아니라 독립적인 error-power 성분의 합이다.

```math
\mathrm{EVM}_{\mathrm{full}}^2(B)
=\mathrm{EVM}_{\mathrm{AWGN}}^2(B)
+\mathrm{EVM}_{\mathrm{det}}^2(B),
```

여기서 `det`는 additive noise를 끈 상태에도 남는 MZM Taylor 비선형성, ZBD square-law
distortion, in-band SSBI 및 DSP residual을 포함한다. 동일한 32QAM preset과 seed를 사용한
ablation에서 결정론적 floor는 2 GBd에서 약 -29.1 dB, 20 GBd에서 약 -27.0 dB였다.
사용자가 확인한 full EVM -24.7 dB와 -16.4 dB에서 이 floor를 power domain으로 빼면
AWGN-associated EVM은 각각 약 -26.7 dB와 -16.8 dB이다. 차이는 약 9.9 dB로,
대역폭 비 `20/2=10`에 따른 이론적 10-dB noise 증가와 일치한다.

따라서 full EVM 차이가 약 8.3 dB인 것은 symbol-rate가 noise bandwidth에 반영되지 않은
결과가 아니다. 2 GBd에서는 -29.1-dB deterministic floor가 AWGN error와 비교적 가까워
합산 penalty가 크고, 20 GBd에서는 AWGN이 -27.0-dB floor보다 훨씬 커 상대적 penalty가
작기 때문이다. 전체 EVM에 정확히 10 dB 차이를 강제하면 이 nonlinear floor를 이중으로
제거하게 된다.

## 3. 32QAM 비교 결과

아래 simulation은 4개 random seed의 EVM error power를 평균한 결과다.

| Rate (GBd) | Measurement (dB) | SNR model (dB) | SINR model (dB) | Full simulation (dB) | Nonlinear-only bound (dB) |
|---:|---:|---:|---:|---:|---:|
| 2  | -25.56 | -26.17 | -26.17 | -26.76 | -29.11 |
| 4  | -23.77 | -23.16 | -23.16 | -25.23 | -29.04 |
| 8  | -20.76 | -20.15 | -20.15 | -23.25 | -29.05 |
| 10 | -19.50 | -19.18 | -19.18 | -22.48 | -29.05 |
| 12 | -18.61 | -18.39 | -18.39 | -21.86 | -29.01 |
| 15 | -17.49 | -17.42 | -17.38 | -20.96 | -28.54 |
| 17 | -16.50 | -16.88 | -16.81 | -20.43 | -28.09 |
| 20 | -15.80 | -16.17 | -16.05 | -19.66 | -27.10 |

측정 EVM에 대한 RMSE는 다음과 같다.

| 비교 모델 | RMSE |
|---|---:|
| SNR-only | 0.440 dB |
| SNR + SSBI SINR | 0.424 dB |
| Full time-domain simulation | 2.991 dB |

20 GBd에서 이론 SINR과 SNR의 차이는 약 0.125 dB다. 따라서 현재 데이터와 수정된 DSP
조건에서는 SSBI 증가 방향은 확인되지만, symbol-rate 열화의 지배 원인이라고 주장할 정도로
크지는 않다. 측정 EVM의 전체 기울기는 주로 `N proportional to B` 관계로 설명된다.

### 3.1 측정으로 제한할 수 있는 SSBI EVM penalty

현재 측정에는 동일한 수신 전력과 noise 조건에서 SSBI만 끈 대조군이 없다. 따라서 측정만으로
SSBI penalty를 다른 implementation impairment와 분리하여 직접 추정할 수는 없다. 대신 2/4 GBd
측정으로 fitting한 AWGN 기준선보다 고속 측정 EVM이 추가로 나빠진 양을, 모든 초과 열화를
SSBI로 귀속했을 때의 보수적인 상한으로 사용할 수 있다.

20 GBd에서 측정값과 SNR-only 기준은 각각

```math
\mathrm{EVM}_{\mathrm{meas,dB}}=-15.80\ \mathrm{dB},\qquad
\mathrm{EVM}_{\mathrm{SNR,dB}}=-16.17\ \mathrm{dB}
```

이므로 측정 기반 초과 penalty는

```math
\Delta_{\mathrm{excess,meas}}
=\mathrm{EVM}_{\mathrm{meas,dB}}-\mathrm{EVM}_{\mathrm{SNR,dB}}
=0.37\ \mathrm{dB}.
```

이를 EVM error-power domain에서 분리하면

```math
\mathrm{EVM}_{\mathrm{excess}}^2
=10^{-15.80/10}-10^{-16.17/10}
\simeq 2.15\times10^{-3},
```

이며, 이 초과 성분만의 등가 SIR은 약 `26.7 dB`다. 17 GBd에서도 같은 방식의 초과 penalty가
약 `0.38 dB`로 계산된다. 따라서 현재 측정이 허용하는 SSBI penalty 범위는 보수적으로

```math
0\le \Delta_{\mathrm{SSBI,meas}}(20\ \mathrm{GBd})\lesssim0.37\ \mathrm{dB}
```

로 표현할 수 있다. 그러나 이 `0.37 dB` 전체를 SSBI라고 주장해서는 안 된다. SNR-only 모델의
전체 RMSE가 `0.44 dB`이고, residual에는 colored noise, residual synchronization error,
frequency-dependent detector/IF response 및 equalization error가 함께 포함되기 때문이다.
또한 SSBI 항을 추가했을 때 RMSE 개선은 `0.440 dB`에서 `0.424 dB`로 `0.016 dB`에 불과하므로,
현재 측정만으로 SSBI EVM penalty가 통계적으로 분명히 분리되었다고 보기도 어렵다.

독립적인 MZM Taylor + ZBD square-law ablation이 이 초과 성분 중 SSBI로 귀속한 값은 20 GBd에서
약 `0.125 dB`다. 따라서 논문에서는 다음처럼 구분하는 것이 정확하다.

- **측정 기반 non-AWGN excess의 상한:** 약 `0.37 dB` at 20 GBd
- **모델이 분리한 SSBI-associated penalty:** 약 `0.125 dB` at 20 GBd
- **측정만으로 직접 식별된 SSBI penalty:** 현재 대조군이 없으므로 별도 식별 불가

Raw C1 spectrum의 near-DC half와 far-side half를 비교한 진단에서는 lower-minus-upper floor가
17 GBd에서 `+1.00 dB`, 20 GBd에서 `+2.76 dB`로 증가했다. 이는 고속에서 SSBI-like spectral
asymmetry가 증가한다는 보조 증거지만, half-band floor 차이는 per-subcarrier EVM이 아니므로
위 `0.125 dB` EVM penalty와 일대일로 대응하지 않는다.

## 4. 기존 simulation 일치에 대한 재해석

이전 simulation은 DFT-s-OFDM block 전체에 하나의 complex scalar gain만 적용했다. 이 경우
20 GBd 신호가 경험하는 MZM 30-GHz EO response의 대역 내 기울기가 보상되지 않아 EVM이
추가로 악화되었고, 이 열화가 측정 및 기존 SSBI curve와 우연히 가까웠다.

현재 simulation은 DSO receiver와 동일한 구조로 active frequency bin마다 channel coefficient를
추정한다.

```math
\widehat H[k]=\frac{Y[k]}{X[k]}, \qquad
\widehat X[k]=\frac{Y[k]}{\widehat H[k]}.
```

응답은 frequency 방향으로 smoothing한 뒤 각 active bin에 complex coefficient 하나를 적용한다.
이 수정 후 20 GBd simulation EVM이 개선되어 측정보다 약 3.9 dB 좋은 결과가 나왔다. 이것은
simulation에 실제 장비의 residual clock error, colored in-band noise, imperfect synchronization,
frequency-dependent detector/IF response 또는 기타 implementation loss가 충분히 포함되지 않았음을
뜻한다. 측정에 맞추기 위해 이러한 손실을 임의 penalty로 추가해서는 안 된다.

## 5. `one-tap FDE` 표현의 적합성

`one-tap FDE`는 논문에서 사용하기에 적합한 통상적 표현이다. 여기서 one tap은 전체 block에
scalar 하나를 곱한다는 뜻이 아니라, 각 frequency bin 또는 subcarrier마다 complex coefficient
하나를 적용한다는 뜻이다.

```math
\widehat X[k]=W[k]Y[k], \qquad W[k]\simeq\frac{1}{\widehat H[k]}.
```

코드에는 서로 다른 두 equalizer가 있으므로 논문과 GUI에서 혼동하면 안 된다.

- **DFT-s-OFDM one-tap FDE:** active bin별 `H[k]` 보상. 논문의 equalization 표현에 해당한다.
- **Post-EQ taps = 1:** 복원된 symbol stream 전체에 적용하는 scalar LS gain. FDE 자체가 아니라
  residual amplitude/phase normalization이다.

권장 논문 표현은 다음과 같다.

> After synchronization, a single complex equalization coefficient is applied per active frequency bin,
> followed by IDFT despreading. An optional symbol-domain scalar correction removes residual common gain
> and phase offsets before EVM evaluation.

측정 EVM pipeline은 offline 검증을 위해 known TX reference 기반 후보도 사용한다. 따라서 이 EVM은
완전 blind receiver 성능이 아니라 reference-aided experimental demodulation 성능으로 명시해야 한다.

## 6. Sensing processing gain 구분

System Model Validation 탭에는 서로 다른 목적의 processing gain 두 개가 존재한다.

### 6.1 Sensing SINR vs Range

측정 및 거리 sweep Sensing SINR에는 calibrated effective gain을 사용한다.

```math
G_{p,\mathrm{eff}}=21.9\ \mathrm{dB}.
```

이 값은 GUI parameter와 Sensing SINR figure 내부에 표시된다. Profile-domain implementation loss를
포함한 calibration 값이므로 ideal time-bandwidth product와 동일시하면 안 된다.

### 6.2 ISAC Range vs rho

이론적 ISAC Range bound에는

```math
G_{p,\mathrm{ideal}}=BT_p
=B\frac{N_p}{R_s}
```

를 사용한다. 기본값 `B=15 GHz`, `R_s=15 GBd`, `N_p=1024`에서는

```math
G_{p,\mathrm{ideal}}=10\log_{10}(1024)=30.10\ \mathrm{dB}.
```

따라서 논문에서는 `21.9 dB`를 measured/calibrated effective profile gain으로, `30.1 dB`를
ideal theoretical bound로 구분해야 한다.

## 7. 재현 방법

GUI에서 확인하고 저장하려면:

```powershell
python plot_evm_tradeoff_gui.py
```

4-seed simulation을 다시 계산해 정적 논문 그림을 저장하려면:

```powershell
python plot_evm_tradeoff_gui.py --no-show --sim-seeds 4 --force-resim
```

기본 실행은 parameter JSON과 `isac_gui.py` model fingerprint가 일치하면 저장된 simulation cache를
사용한다.

## 8. 최종 결론

1. 측정 EVM은 2--20 GBd에서 이론적인 bandwidth-noise law와 0.44 dB RMSE로 일치한다.
2. 20 GBd 측정의 non-AWGN excess 상한은 약 0.37 dB이고, 수정된 모델이 분리한 SSBI penalty는
   약 0.125 dB이므로 SSBI는 성능 열화의 주원인으로 식별되지 않는다.
3. 기존 simulation과 측정의 근접성 일부는 불완전한 scalar equalization에 의한 것이었다.
4. DSO와 simulation 모두 active-bin one-tap FDE로 통일했으며, 해당 용어는 논문에 적합하다.
5. full simulation이 측정보다 약 3 dB 낙관적이므로, 남은 실험 impairment를 별도로 규명해야 한다.
