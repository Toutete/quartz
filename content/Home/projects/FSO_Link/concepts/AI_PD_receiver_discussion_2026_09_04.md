# AI 기반 Multi-Aperture PD Receiver 논의 정리

## 배경

현재 목표는 지상-위성 FSO 링크에서 대기 난류로 인한 intensity fluctuation, beam wander, aperture coupling loss를 줄이기 위해 multi-aperture 또는 multi-PD receiver를 구성하고, FPGA에서 실시간 adaptive combining을 수행하는 것이다.

수업 맥락에서는 `NPU 설계와 FPGA 구현` 과정을 듣고 있으며, 현재 단계는 PyTorch 모델 설계 및 학습이고, 다음 단계는 RTL 또는 DPU 형태로 FPGA 구현하는 것이다.

## 핵심 시스템 구조

최종적으로 원하는 구조는 다음과 같다.

```text
Optical source / satellite FSO beam
-> Atmospheric turbulence
-> Multi-aperture lens / PD array
-> TIA + ADC
-> FPGA sample buffer
-> CNN / DPU inference
-> combining weight or channel-state estimate
-> FPGA DSP combiner / equalizer
-> demodulation
-> SNR, EVM, BER, outage improvement
```

## Training과 Inference 구분

중요한 구분은 training과 inference이다.

```text
Training:
모델 parameter 자체를 찾는 과정
forward + loss + backpropagation + optimizer update

Inference:
이미 학습된 model parameter를 사용해 현재 입력에 대한 출력만 계산
forward only
```

일반적으로 FPGA는 CNN 전체 training보다는 inference와 실시간 DSP에 더 적합하다. CNN training은 PC/GPU에서 수행하고, 학습된 parameter를 FPGA에 넣어 DPU로 실행하는 방식이 현실적이다.

## 두 종류의 Weight

논의 중 혼동될 수 있는 부분은 weight라는 말이 두 가지 의미로 쓰인다는 점이다.

```text
CNN parameter:
Conv filter, linear layer weight, bias
training 후 고정됨
FPGA DPU 내부에 저장됨

Combining weight:
PD1, PD2, ..., PDN 신호를 어떤 비율로 합칠지 정하는 계수
현재 채널 상태에 따라 바뀔 수 있음
CNN/DPU의 출력이 될 수 있음
```

따라서 FPGA에 넣는 것은 학습된 CNN parameter이고, FPGA DPU는 실시간 PD 입력을 보고 combining weight를 출력한다.

## Offline Training 구상

offline training은 PC에서 다음과 같이 수행한다.

```text
대기 난류 simulation
  - optical wave propagation
  - von Karman PSD-based phase screen
  - split-step Fourier method
  - Taylor frozen-flow hypothesis

-> pupil image / received power distribution
-> 가상의 PD array aperture integration
-> PD별 power vector 또는 time window 생성
-> CNN 입력
-> future PD power 또는 combining weight 출력
-> loss 계산
-> backpropagation으로 CNN parameter 학습
```

여기서 cost는 CNN의 직접 출력이라기보다, CNN 출력이 좋은지 평가하는 목적함수로 두는 것이 자연스럽다.

```text
적절한 형태:
PD power window -> CNN -> combining weights
combining weights 적용 -> SNR/EVM/BER/outage 기반 loss 또는 proxy loss

덜 적절한 형태:
PD power window -> CNN -> cost only
```

초기 구현에서는 oracle combining weight를 label로 두고 supervised learning을 수행하는 것이 가장 단순하다.

```text
oracle weight = future PD power 기반 MRC-like normalized weight
loss = future power MSE + weight MSE + physical parameter MSE
```

## Online FPGA Implementation

online 구현에서는 실제 PD array의 current가 TIA/ADC를 거쳐 FPGA에 들어온다.

```text
PD current/power samples
-> log normalization or fixed-point scaling
-> recent time window buffer
-> FPGA CNN/DPU
-> predicted future PD power or combining weight
-> Q-format quantized coefficient
-> weighted combining / equalization
```

CNN은 기존 adaptive combining을 완전히 대체한다기보다, 우선은 adaptive weight estimation/control logic을 대체하는 것으로 보는 것이 안정적이다.

```text
CNN/DPU가 대체하기 좋은 부분:
어떤 PD channel에 더 큰 weight를 줄지 결정하는 부분

여전히 필요한 DSP 부분:
ADC sampling
sample alignment
gain normalization
weighted sum
timing recovery
carrier recovery
demodulation
BER/EVM/SNR measurement
```

더 공격적인 neural receiver 구조도 가능하다.

```text
raw multi-PD samples -> neural receiver -> symbol/bit output
```

하지만 이는 수업 프로젝트나 초기 연구로는 범위가 크므로, 먼저 `PD power window -> combining weights` 구조를 완성하는 것이 좋다.

## FPGA Training에 대한 결론

FPGA에서 CNN 전체 training도 이론적으로는 가능하지만, backpropagation과 optimizer까지 구현해야 하므로 복잡도가 크다.

```text
필요한 연산:
Conv forward
Conv backward
ReLU backward
Pooling backward
Linear backward
gradient memory
activation storage
optimizer update
```

반면 inference는 다음 정도로 작아진다.

```text
Conv
BatchNorm folded into Conv
ReLU
Pooling or stride
Linear
Quantize / clip / scale
```

따라서 FPGA는 학습된 모델의 inference, adaptive DSP, fixed-point streaming 처리에 집중하는 것이 좋다.

## Random Search 방식

CNN 전체 parameter를 무작위로 바꿔가며 최적 weight를 찾는 것은 weight 수가 너무 많아 비효율적이다.

그러나 작은 수의 DSP parameter에는 유용할 수 있다.

```text
적합한 대상:
8개 PD combining weight
equalizer tap 일부
gain calibration coefficient
threshold
마지막 layer 일부
```

실용적인 hybrid 구조는 다음과 같다.

```text
PC:
CNN 전체 parameter를 backpropagation으로 학습

FPGA:
CNN inference 수행
소수의 combining/equalizer coefficient는 LMS/RLS/gradient-free 방식으로 실시간 보정
```

## FINN / Vitis AI / Custom DPU

FINN은 quantized neural network를 FPGA용 network-specific accelerator로 자동 생성하는 framework이다. Vitis AI DPU는 AMD/Xilinx 계열에서 제공하는 범용 deep-learning inference engine에 가깝다.

```text
Custom DPU:
Conv/ReLU/Pooling/Linear datapath를 직접 구현
수업용, 구조 이해용으로 좋음

FINN:
quantized CNN 전체에 맞는 streaming accelerator 자동 생성
빠른 prototype과 성능 비교에 좋음

Vitis AI DPU:
지원되는 모델을 quantization/compiler flow로 FPGA/SoC에 배포
```

수업에서는 custom DPU를 직접 구현하는 의미가 있고, 연구 prototype에서는 FINN 또는 Vitis AI를 활용하는 것이 합리적이다.

## QONNX와 Quantization-Aware Training

QONNX는 quantized neural network 정보를 담을 수 있도록 확장된 ONNX 계열 중간 표현이다.

```text
PyTorch/Brevitas quantized model
-> QONNX
-> FINN
-> FPGA accelerator
```

Quantization-aware training은 학습 중 forward path에서 rounding/clipping/low-bit 효과를 흉내내어, 나중에 FPGA fixed-point 또는 integer inference로 옮겼을 때 성능 손실을 줄이는 방법이다.

일반적으로 quantization 대상은 다음을 포함한다.

```text
input activation
weight
intermediate activation
output
```

다만 accumulator는 보통 더 큰 bit-width를 사용한다.

```text
8-bit input x 8-bit weight -> 16-bit multiply
many terms accumulated -> 24-bit or 32-bit accumulator
next layer output -> 다시 8-bit or fixed-point로 requantization
```

## RIS DoA 논문과의 유사성

An et al.의 RIS DoA 논문은 다음 구조를 가진다.

```text
RF source
-> antenna + Rotman lens
-> 6개 power detector
-> ADC
-> MCU
-> FCN inference로 distance/angle 추정
-> precomputed RIS bias codebook 선택
-> RIS bias voltage 제어
-> received power 향상
```

이 구조는 본 FSO receiver 구상과 방법론적으로 유사하다.

```text
RIS 논문:
RF sensor power distribution -> FCN -> DoA/distance -> RIS bias control

FSO 목표:
PD current/power distribution -> CNN/DPU -> channel state or combining weight -> FPGA combiner/equalizer control
```

차이점은 RIS 논문은 저속 control loop이므로 MCU로 충분하지만, FSO receiver는 고속 ADC와 실시간 통신 DSP가 필요하므로 FPGA가 더 적합하다는 점이다.

## PINN + CNN + Zernike 확장

더 똑똑한 모델은 가능하다. 다만 처음부터 full PINN으로 가기보다 baseline CNN 위에 물리 보조항을 얹는 방식이 좋다.

추천 구조:

```text
main task:
PD power window -> combining weights

auxiliary tasks:
PD power window -> future PD power
PD power window -> log10(Cn2), wind speed, beam waist, r0, Rytov variance
PD power window -> low-order Zernike coefficients
```

Zernike coefficient는 simulator 내부의 received aperture phase에서 least-squares fitting으로 만들 수 있다.

중요한 low-order mode:

```text
tip/tilt:
beam wander와 PD imbalance에 직접 연결

defocus:
focal coupling 변화와 연결

astigmatism/coma:
비대칭 aperture coupling과 연결
```

Physics-informed loss 후보:

```text
energy consistency:
예측 power의 총량이 비물리적으로 변하지 않도록 제한

measurement consistency:
예측 field/power map이 PD aperture integration과 일치하도록 제한

turbulence prior:
Zernike spectrum이 Kolmogorov-like decay를 갖도록 유도

temporal smoothness:
combining weight가 frame마다 과하게 튀지 않도록 제한
```

## 현재 구현 상태

현재 `code` 폴더에는 이미 다음 baseline이 있다.

```text
fso_engine.py
ai_pd_dataset.py
ai_pd_model.py
train_ai_pd.py
eval_ai_pd.py
predict_ai_pd_weights.py
export_ai_pd_onnx.py
ai_pd_combiner.py
```

추가된 확장 파일:

```text
zernike_tools.py
physics_losses.py
```

현재 가장 현실적인 다음 단계:

```text
1. 현재 ai_pd_dataset.py로 작은 dataset 생성
2. train_ai_pd.py로 CNN baseline 학습
3. eval_ai_pd.py로 oracle/equal/AI combiner metric 확인
4. simulator에서 aperture phase를 저장하도록 fso_engine.py 또는 dataset generator 확장
5. zernike_tools.py로 Zernike labels 생성
6. ai_pd_model.py에 Zernike auxiliary head 추가
7. physics_losses.py를 train loop에 점진적으로 연결
```

## 발표/보고서용 한 문장

```text
The proposed receiver uses a CNN-based FPGA DPU to infer near-optimal combining coefficients from multi-PD power distributions generated by atmospheric turbulence, while the FPGA DSP datapath applies the coefficients for real-time weighted combining and communication performance improvement.
```

