# AI 기반 Multi-PD FSO 수신기 통합 설계 정리

작성일: 2026-09-17

## 1. 연구 목표

본 연구의 목표는 지상-위성 FSO 링크에서 대기 난류로 발생하는
scintillation, beam wander, spatial fading을 여러 개의 photodetector로
관측하고, 미래 채널 상태를 CNN으로 예측하여 FPGA에서 실시간 combining
weight를 적용하는 수신기를 구현하는 것이다.

최종 신호 흐름은 다음과 같다.

```text
Satellite optical transmitter
-> atmospheric turbulence
-> ground receiver telescope and pupil relay
-> 4x4 APD array
-> 16-channel TIA / ADC or power monitor
-> FPGA time-window buffer
-> CNN/DPU inference
-> predicted future APD power and combining weights
-> FPGA weighted combiner / equalizer
-> demodulation
-> SNR, EVM, BER, outage evaluation
```

핵심 연구 질문은 다음과 같다.

1. 단일 PD보다 4x4 APD array가 outage와 fade margin을 개선하는가?
2. 현재 APD power의 시간 패턴으로 다음 시점의 channel power를 예측할 수 있는가?
3. CNN-predicted weight가 EGC, selection combining, conventional MRC보다 유리한가?
4. PD 관측값으로 Fried parameter `r0`와 난류 regime을 추정할 수 있는가?
5. 강난류에서는 diversity를, 약난류에서는 독립 spatial mode를 이용할 수 있는가?
6. 학습된 작은 CNN을 FPGA에서 low-bit inference로 실시간 실행할 수 있는가?

## 2. Training과 Inference의 구분

### 2.1 Offline training

CNN parameter를 찾는 과정은 PC/GPU에서 수행한다.

```text
physical simulation or measured dataset
-> CNN forward
-> prediction and communication loss
-> backpropagation
-> optimizer update
-> trained CNN parameters
```

Backpropagation에는 activation 저장, gradient 계산, Conv backward, optimizer
state가 필요하다. 따라서 초기 연구와 수업 프로젝트에서는 FPGA training보다
PC/GPU training이 구현 난이도와 개발 속도 측면에서 유리하다.

### 2.2 Online inference

FPGA에서는 학습된 CNN parameter를 고정하고 forward inference만 수행한다.

```text
recent 4x4 APD power window
-> quantized CNN/DPU
-> next-frame APD power prediction
-> normalized combining weights
-> weighted sum and communication DSP
```

FPGA의 장점은 training 자체보다 deterministic latency, streaming 처리,
fixed-point 연산, 낮은 전력, ADC/DSP와의 직접 연결에 있다.

### 2.3 두 종류의 weight

`weight`라는 용어는 반드시 구분해야 한다.

- CNN parameter: Conv filter, BatchNorm parameter, linear-layer weight와 bias이다.
  Offline training 후 고정되어 FPGA DPU에 저장된다.
- Combining weight: 16개 APD 신호를 어떤 비율로 합칠지 정하는 계수이다.
  채널 상태에 따라 시간적으로 변하며 CNN의 출력이 될 수 있다.

CNN training은 CNN parameter를 찾는 과정이고, online CNN inference는 현재 또는
미래 채널에 적합한 combining weight를 생성하는 과정이다.

## 3. CNN과 기존 DSP의 관계

CNN이 FPGA receiver DSP 전체를 대체하는 것으로 보면 안 된다. 현재 권장 구조에서
CNN은 channel prediction과 weight control을 담당한다.

CNN이 담당하는 기능:

- 다음 시점의 APD별 power prediction
- combining weight prediction
- `r0` 또는 turbulence regime 보조 추정
- future fade 또는 outage 위험 예측

기존 DSP로 유지해야 하는 기능:

- ADC sampling과 channel synchronization
- gain, offset, delay calibration
- weighted sum
- equalization과 timing recovery
- carrier recovery 또는 direct-detection demodulation
- EVM, BER, SNR 측정

초기 PoC에서는 `CNN predictor + conventional weighted combiner` 구조가 가장
검증 가능성이 높다. Raw sample에서 bit를 직접 출력하는 end-to-end neural receiver는
후속 연구 항목이다.

## 4. 물리 시뮬레이션

통합 엔진은 다음 물리를 사용한다.

- von Karman spectrum 기반 phase screen
- split-step beam propagation
- Taylor frozen-flow hypothesis 기반 시간 상관
- uplink/downlink 선택
- receiver-plane intensity와 pupil-plane power 보존형 축소
- APD aperture integration
- detector current, noise, ADC quantization

기본 downlink 조건은 다음과 같다.

| 항목 | 기본값 |
|---|---:|
| TX power | 20 dBm |
| Link distance | 20 km |
| Wavelength | 1550 nm |
| TX aperture | 70 mm |
| TX full-angle divergence | 28 urad |
| TX antenna gain cross-check | 103.1 dB |
| RX aperture | 203.2 mm |
| RX antenna gain cross-check | 112.3 dB |

현재 연구 모델에서는 중앙 차폐 효과를 사용하지 않는다. 수신 개구는 이상적인
203.2 mm 원형 aperture로 모델링하며, 축소 pupil과 APD power에도 중앙 shadow가
적용되지 않는다. 엔진의 obstruction parameter는 향후 실제 telescope 민감도 비교를
위한 선택 기능으로만 남긴다.

## 5. 광 수신부와 4x4 APD 사양

수신부의 기준 구조는 다음과 같다.

```text
203.2 mm receiver aperture
-> 75 mm collimator
-> approximately 7.5 mm collimated pupil
-> adjustable 4f pupil relay
-> 1.0 mm reduced pupil
-> optional external MLA
-> 4x4 APD array
```

APD array 기준값:

| 항목 | 값 |
|---|---:|
| Array | 4 rows x 4 columns |
| Pitch | 250 um |
| Grid width | 1.0 mm |
| Integrated lens diameter | 100 um |
| Active junction diameter | 25 um nominal |
| Electrical bandwidth | 20 GHz |
| Symbol-rate target | 28 Gbaud/channel |
| External MLA fill factor | 95% 이상 목표 |

외부 MLA가 없으면 100 um integrated lens와 250 um pitch의 기하학적 fill factor는
약 12.6%이며 약 9 dB의 이상적 기하학 손실이 발생한다. 외부 MLA를 사용하면 각
250 um cell의 광을 integrated lens로 전달할 수 있지만, 실제 효율은 alignment,
local wavefront tilt, diffraction, compound lens 설계에 의해 결정된다.

## 6. CNN 입력과 출력

### 6.1 입력

CNN 입력은 한 장의 pupil image가 아니라, ADC에서 복원한 최근 APD power window이다.

```text
input shape = [batch, time_window, 4, 4]
```

각 frame은 16개 APD power를 평균 power로 정규화한 뒤 log scale로 변환한다. FPGA
구현에서는 동일한 연산을 fixed-point 또는 LUT 기반으로 근사해야 한다.

### 6.2 출력

현재 모델은 multi-task output을 사용한다.

1. 다음 frame의 4x4 normalized power map
2. power prediction에서 계산한 nonnegative combining weights
3. `log10(r0 / Dsub)` 형태의 보조 물리 출력

`Dsub`는 4x4 pupil sampling 기준 telescope-equivalent subaperture 크기이다.

```text
Dsub = 203.2 mm / 4 = 50.8 mm
```

### 6.3 Loss

GUI 내 간단 학습은 다음 항목을 사용한다.

```text
total loss
= next-power log MSE
+ SNR proxy loss
+ total-power consistency loss
+ r0-ratio regression loss
```

SNR이나 EVM은 CNN의 단순 출력 label이 아니라, predicted weight를 실제 future
channel에 적용했을 때 평가되는 목적함수 또는 differentiable proxy로 사용하는 것이
자연스럽다.

## 7. Fried parameter r0 추정

PD time trace로 `r0`를 추정하는 것은 가능하지만 조건이 있다.

한 개 `Cn2` 조건의 simulation만 사용하면 모든 sample의 `r0` label이 동일하다.
이 경우 CNN은 일반적인 `r0` estimator가 아니라 해당 조건의 상수를 학습할 수 있다.
따라서 GUI에 표시되는 `r0`는 single-condition calibration 결과로 해석해야 한다.

일반화 가능한 `r0` estimator를 만들려면 다음 조건이 필요하다.

- 여러 `Cn2`와 `r0` 조건
- 여러 wind speed와 direction
- 여러 phase-screen seed
- pointing residual과 receiver noise 변화
- simulation별로 분리된 train/validation/test set
- 가능하면 실측 데이터 fine-tuning

현재 offline dataset은 simulation ID를 저장한다. 학습과 검증은 동일 simulation의
시간 window를 무작위로 섞지 않고, 전체 turbulence realization 단위로 분리한다.
평가에서는 `r0_mae_mm`와 `r0_mape_pct`를 확인한다.

## 8. r0와 공간 처리 전략

현재 regime 판단에는 `r0 / Dsub`를 사용한다.

### 8.1 강난류

```text
r0 / Dsub < 1
```

한 subaperture보다 coherence length가 작다. 채널별 fade가 커질 수 있으므로 다음을
우선한다.

- selection combining baseline
- conventional instantaneous MRC
- 낮은 percentile power를 이용한 outage-robust fixed MRC
- CNN-predicted future MRC
- outage probability와 required fade margin 최소화

### 8.2 전이 영역

```text
1 <= r0 / Dsub < 2
```

Diversity를 기본으로 유지하면서 spatial mode independence와 channel correlation을
측정해야 한다.

### 8.3 약난류

```text
r0 / Dsub >= 2
```

Pupil coherence가 상대적으로 높다. 그러나 `r0`가 크다는 사실만으로 현재 16개 APD가
spatial multiplexing channel이 되는 것은 아니다.

현재 시스템은 한 개 optical beam과 한 개 data stream을 여러 APD가 관측한다. 따라서
16개 APD 출력은 기본적으로 diversity branch이다. 실제 spatial multiplexing gain을
얻으려면 다음이 필요하다.

- 복수의 독립 TX spatial mode 또는 복수 beam
- mode별 독립 data stream
- TX mode와 APD 사이의 channel matrix `H`
- channel rank와 singular value 검증
- coherent 또는 mode-selective receiver 구조

GUI의 water-filling 결과는 independent channel을 가정한 capacity proxy이다. 실제
multiplexing capacity나 upper bound로 단정할 수 없다. 현재 구조에서 직접 달성 가능한
capacity는 one-stream MRC SNR로 계산한 값이다.

## 9. Combining과 통신 지표

반드시 비교해야 할 baseline은 다음과 같다.

- Single center APD
- Selection combining
- Equal-gain combining
- Instantaneous oracle MRC
- Outage-robust fixed MRC
- CNN-predicted combining

평가 지표:

- Mean and percentile SNR
- EVM
- BER approximation
- Outage probability
- Required fade margin
- Mean received optical power
- Scintillation index
- Strehl ratio
- CNN prediction error
- Oracle 대비 combining loss

AI 방식은 conventional MRC와 비교해야 한다. CNN이 EGC만 이기고 MRC보다 나쁘다면
미래 예측 latency, hardware cost, outage 개선 측면에서 추가 근거가 필요하다.

## 10. Epoch 설정

Epoch는 데이터 개수보다 validation curve와 overfitting 여부로 결정해야 한다.

### 10.1 GUI single-condition 학습

- 권장 시작값: 20-30 epochs
- 현재 기본값: 30 epochs
- 30 epoch 이후에도 loss가 계속 감소할 때만 50까지 증가
- sample 수가 약 20-30개뿐이므로 높은 epoch는 쉽게 memorization을 만든다.

GUI 학습은 pipeline과 trend 확인용이며 최종 성능 수치로 사용하지 않는다.

### 10.2 Offline multi-condition 학습

- 최대 50-100 epochs 설정
- validation loss 기반 early stopping 사용
- 권장 patience: 8-10 epochs
- best validation checkpoint를 FPGA export에 사용

현재 offline trainer의 기본값은 최대 60 epochs, patience 8이다. 연구용 실행에서는
`--epochs 100 --patience 10`으로 충분한 상한을 주고 조기 종료시키는 방법을 권장한다.

## 11. Quantization과 FPGA 구현

Quantization-aware training은 학습 forward path에서 low-bit rounding과 clipping을
모사하여 FPGA 변환 후의 성능 손실을 줄이는 방법이다.

일반적인 quantization 대상:

- ADC/CNN input
- Conv와 Linear weight
- intermediate activation
- CNN output과 combining coefficient

Multiplier와 accumulator의 bit width는 구분해야 한다.

```text
8-bit activation x 8-bit weight
-> 16-bit product
-> 24-bit or 32-bit accumulator
-> requantized next-layer activation
```

FPGA 구현 선택지는 다음과 같다.

- Custom DPU: 수업에서 Conv, activation, pooling, linear RTL을 직접 이해하는 데 적합
- FINN: Brevitas/QONNX quantized network를 network-specific streaming hardware로 변환
- Vitis AI DPU: 지원 model을 AMD/Xilinx DPU에 배포

QONNX는 quantization 정보를 보존하는 ONNX 계열 intermediate representation이다.
연구 PoC에서는 PyTorch/Brevitas QAT, QONNX, FINN 흐름이 custom RTL과 비교 가능한
현실적인 선택이다.

## 12. 권장 FPGA 단계

### 단계 1: Host inference와 FPGA combiner

- PC에서 CNN inference
- FPGA는 16-channel calibration과 weighted sum 담당
- floating-point와 fixed-point combining 결과 비교

### 단계 2: Quantized CNN inference

- input/weight/activation bit-width sweep
- Q1.15 또는 적절한 combining coefficient format 결정
- ONNX/QONNX export와 co-simulation

### 단계 3: FPGA DPU 통합

- CNN inference를 FPGA로 이동
- ADC input buffer와 DPU streaming 연결
- predicted weight update rate와 DSP sample rate 분리

### 단계 4: 실측 adaptation

- simulation-pretrained model을 실제 APD trace로 fine-tuning
- channel gain mismatch, TIA noise, ADC offset, delay skew 포함
- 실시간 EVM/BER/outage 비교

## 13. GUI의 현재 역할

GUI는 다음을 한 화면의 tab으로 제공한다.

1. Receiver-plane optical power density
2. 1.0 mm reduced pupil과 4x4 APD geometry
3. 시간에 따른 16개 APD power
4. APD current와 ADC code
5. EVM, BER, outage, fade margin 비교
6. CNN training curve와 future power prediction
7. `r0`, turbulence regime, diversity/capacity strategy

Optical image의 color scale, APD heatmap scale, trace y-axis는 run 전체에서 고정된다.
프레임 변경 시 axes와 colorbar를 재생성하지 않고 image data와 time cursor만 갱신한다.
따라서 물리적 변화와 plotting autoscale 변화를 혼동하지 않는다.

## 14. 코드 구성

| 파일 | 역할 |
|---|---|
| `code/fso_engine.py` | Wave optics, APD, ADC, CNN, communication engine |
| `code/multi_pd_link_gui.py` | 통합 GUI |
| `code/ai_pd_dataset.py` | Multi-condition offline dataset 생성 |
| `code/ai_pd_model.py` | FPGA-friendly temporal CNN |
| `code/train_ai_pd.py` | Group-split training과 early stopping |
| `code/eval_ai_pd.py` | Power, weight, communication, r0 평가 |
| `code/export_ai_pd_onnx.py` | ONNX export |
| `code/predict_ai_pd_weights.py` | FPGA용 combining weight 생성 |
| `code/test_fso_engine.py` | 물리 보존과 engine regression test |

## 15. 권장 실험 순서

1. 난류가 없는 조건에서 power conservation과 APD geometry를 검증한다.
2. 하나의 `Cn2`에서 frozen-flow time trace가 매끄럽고 상관성을 갖는지 확인한다.
3. Single, selection, EGC, MRC의 기준 성능을 확보한다.
4. 여러 `Cn2`, wind, seed로 offline dataset을 생성한다.
5. CNN future-power와 `r0` multi-task model을 학습한다.
6. 완전히 분리된 simulation realization에서 평가한다.
7. CNN이 MRC 또는 oracle future-MRC에 얼마나 접근하는지 측정한다.
8. Quantization 전후 성능 차이를 측정한다.
9. Host inference와 FPGA fixed-point combiner를 연결한다.
10. 실제 4x4 APD/TIA/ADC trace로 domain adaptation한다.

## 16. 현재 결론

1. PC/GPU offline training과 FPGA online inference의 역할 분리가 가장 현실적이다.
2. CNN의 1차 역할은 DSP 전체 대체가 아니라 future channel/weight prediction이다.
3. `r0` 추정은 multi-condition dataset과 realization 단위 분리가 있을 때 의미가 있다.
4. 강난류에서는 outage-robust spatial diversity가 핵심이다.
5. 약난류라고 해서 단일 빔 APD array가 자동으로 spatial multiplexing을 제공하지 않는다.
6. 실제 multiplexing 검증에는 independent TX mode와 channel matrix가 필요하다.
7. GUI 30 epochs는 기능 확인용이고, 최종 모델은 early stopping을 사용한 offline 학습으로 결정한다.
8. 최종 연구 성능은 CNN 대 EGC가 아니라 CNN 대 conventional/oracle MRC로 판단해야 한다.
