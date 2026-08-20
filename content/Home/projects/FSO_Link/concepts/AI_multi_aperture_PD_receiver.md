# AI 기반 Multi-Aperture PD Receiver 개념 정리

## 목적

지상-위성 FSO 링크에서 대기 난류는 수신면 intensity fluctuation, beam wander, aperture coupling loss를 만든다. 단일 photodiode 수신기는 특정 위치의 fade에 취약하므로, 여러 PD를 공간적으로 배치하고 각 PD 신호를 독립 채널로 처리한 뒤 FPGA/DSP에서 적응 가중 결합하는 구조가 필요하다.

본 프로젝트의 목표는 다음 구조를 검증하는 것이다.

```text
Turbulent optical field
  -> spatial PD array
  -> per-PD ADC/DSP channels
  -> CNN/AI predictor
  -> predicted future PD power / physical state
  -> adaptive combining weights
  -> FPGA weighted combiner
```

## 전체 청사진

1. PD array 공간 배치
   - 기본 baseline은 `rows x cols` 격자 배치이다.
   - 각 PD는 수신 렌즈/개구의 특정 위치 또는 focal-plane coupling channel로 모델링한다.
   - 초기 실험은 `2 x 4` 배열, 20 mm spacing을 사용한다.
   - 후속 연구에서는 중심 밀집형, ring형, hexagonal packing, nonuniform optimized placement를 비교한다.

2. 학습 단계
   - 난류 조건을 무작위로 샘플링한다.
   - 예: `Cn2`, 전파 거리, wind speed, beam waist, phase-screen seed.
   - headless simulator가 각 조건에서 PD별 time trace를 생성한다.
   - 입력은 최근 PD power window이다.
   - label은 미래 PD power, oracle combining weight, 물리 파라미터이다.

3. 예측 단계
   - FPGA 또는 host가 최근 PD power window를 만든다.
   - CNN이 다음 시점의 PD별 power map을 예측한다.
   - 예측 power를 normalize하여 combiner weight로 변환한다.
   - weight는 Q1.15 등 fixed-point coefficient로 양자화해 FPGA DSP slice에서 적용한다.

4. Simulation pretraining
   - 실측 데이터를 바로 많이 얻기 어렵기 때문에 simulation으로 먼저 pretraining한다.
   - coarse grid/낮은 해상도에서 많은 조건을 학습하고, 고해상도/고충실도 simulation으로 fine-tuning한다.
   - 최종적으로 실측 trace로 domain adaptation한다.

## 학습이 잘되고 있는지 판단하는 법

loss 하나만 보면 부족하다. 다음 지표를 함께 봐야 한다.

- `val_loss`: overfitting 없이 validation loss가 감소하는지 확인한다.
- `power_log_mse`: 미래 PD별 power 예측 오차이다.
- `weight_mse`: 예측 weight와 oracle weight의 평균제곱오차이다.
- `weight_cosine_mean`: 예측 weight vector와 oracle weight vector의 방향 유사도이다.
- `weight_top1_match`: 가장 강한 PD channel을 맞추는 비율이다.
- `pred_vs_equal_gain_db_mean`: AI weight가 equal combining 대비 실제 dB 이득을 주는지 확인한다.
- `oracle_vs_equal_gain_db_mean`: 현재 PD array와 채널 조건에서 얻을 수 있는 최대 이득의 기준선이다.
- `pred_vs_oracle_gap_db_mean`: AI combiner가 oracle 대비 얼마나 손해 보는지 나타낸다.

따라서 좋은 학습의 조건은 다음과 같다.

```text
validation loss decreases
AND weight_cosine_mean increases
AND pred_vs_equal_gain_db_mean > 0 dB
AND pred_vs_oracle_gap_db_mean approaches 0 dB
```

현재 smoke test에서는 pipeline 검증만 수행했으므로 좋은 성능을 기대하면 안 된다. 실제 연구용 평가는 수천~수만 개 simulation sample과 별도 test condition set이 필요하다.

## Zernike coefficients 활용

일반적인 CNN 기반 wavefront estimation에서는 CCD/SH-WFS 이미지에서 Zernike coefficient를 회귀한다. 이 접근은 FSO PD array에도 보조 학습 신호로 유용하다.

다만 PD array는 wavefront 전체 이미지를 직접 관측하지 않고 sparse power measurement만 얻는다. 따라서 Zernike coefficient를 단독 target으로 두면 ill-posed 문제가 생길 수 있다. 추천 구조는 multi-task learning이다.

```text
PD power time window
  -> CNN / temporal model
     -> future PD power map
     -> combining weight map
     -> auxiliary physical parameters
     -> auxiliary low-order Zernike coefficients
```

low-order Zernike mode는 특히 중요하다.

- tip/tilt: beam wander와 PD channel imbalance에 직접 연결된다.
- defocus: focal coupling 변화와 연결된다.
- astigmatism/coma: 비대칭 aperture coupling과 연결된다.

Zernike label은 simulator 내부 complex field에서 aperture phase를 추출하고 least-squares fitting으로 만들 수 있다. 이를 auxiliary loss로 넣으면 필요한 데이터 수를 줄이고, 모델이 물리적으로 말이 되는 latent representation을 학습하도록 돕는다.

## Physics-informed NN 방향

Maxwell equation 전체를 PINN loss로 직접 넣는 것은 계산량이 크고 FSO paraxial link에는 과도하다. 현실적인 출발점은 scalar paraxial wave equation, Fresnel propagation, Kolmogorov/von Karman turbulence prior를 loss나 regularization으로 넣는 것이다.

추천 physics-informed 항목은 다음과 같다.

- Energy consistency: 전파/결합 과정에서 총 optical power가 비물리적으로 변하지 않도록 제한한다.
- Measurement consistency: 예측한 wavefront 또는 predicted power map이 PD aperture integration 결과와 일치하도록 한다.
- Turbulence prior: phase/Zernike spectrum이 Kolmogorov 계열의 mode decay 경향을 갖도록 한다.
- Temporal frozen-flow consistency: wind-driven phase screen 이동에 맞는 시간적 변화를 유도한다.
- Smooth weight constraint: FPGA 적용 시 weight가 frame마다 불필요하게 크게 흔들리지 않도록 한다.

이 구조는 순수 black-box CNN보다 작은 데이터셋에서 안정적으로 학습될 가능성이 높다.

## Simulation 속도 문제

`fso_gui_v2.py`는 학습용이 아니라 시각화와 디버깅용 GUI이다. Matplotlib, Tkinter, animation, colorbar update가 포함되어 있어 학습 dataset 생성에는 느리다. 학습에는 반드시 headless generator를 사용해야 한다.

현재 구현은 다음 역할로 분리되어 있다.

- `fso_gui_v2.py`: 사람이 확인하는 시각화/디버깅 도구
- `fso_engine.py`: headless simulation engine
- `ai_pd_dataset.py`: simulation 기반 PD trace dataset 생성
- `train_ai_pd.py`: CNN 학습
- `eval_ai_pd.py`: combiner 성능 평가

학습 속도를 높이는 전략은 다음과 같다.

1. coarse pretraining
   - `grid_n=64~256`으로 많은 조건을 빠르게 생성한다.

2. selective high-fidelity simulation
   - 중요한 난류 regime 또는 실패 case만 `grid_n=512~1024`로 재생성한다.

3. cache
   - phase screen, PD geometry ROI, generated traces를 저장해 재사용한다.

4. on-the-fly와 offline 혼합
   - 처음에는 `.npz`/HDF5 offline dataset으로 재현성을 확보한다.
   - 이후 augmentation/on-the-fly generation으로 다양성을 늘린다.

5. 외부 simulator 교체
   - 현재 engine은 baseline이다.
   - 더 높은 신뢰도가 필요하면 AOtools/HCIPy/LightPipes 기반 phase screen 및 split-step propagation으로 교체한다.

## 구현된 baseline

현재 코드 폴더에는 다음 baseline이 있다.

- `ai_pd_dataset.py`: FSO simulation에서 PD array trace를 생성한다.
- `ai_pd_model.py`: 작은 FPGA-friendly CNN이다.
- `train_ai_pd.py`: power/weight/physics multi-task loss로 학습한다.
- `eval_ai_pd.py`: equal/oracle/AI combiner 성능을 비교한다.
- `predict_ai_pd_weights.py`: 학습 모델에서 Q1.15 FPGA weight를 출력한다.
- `export_ai_pd_onnx.py`: ONNX export를 수행한다.
- `ai_pd_combiner.py`: floating/fixed-point weight normalization과 combining helper를 제공한다.

검증된 실행 흐름은 다음과 같다.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-ai.txt
.\.venv\Scripts\python.exe .\ai_pd_dataset.py --out ai_pd_data --num-sims 100 --grid-n 256
.\.venv\Scripts\python.exe .\train_ai_pd.py --data ai_pd_data --epochs 30
.\.venv\Scripts\python.exe .\eval_ai_pd.py --checkpoint ai_pd_runs\best_ai_pd.pt --data ai_pd_data
.\.venv\Scripts\python.exe .\export_ai_pd_onnx.py --checkpoint ai_pd_runs\best_ai_pd.pt
```

## 다음 단계

1. Zernike fitting module 추가
   - 수신 aperture phase에서 low-order Zernike coefficient label을 생성한다.

2. physics consistency loss 추가
   - power conservation, measurement consistency, temporal smoothness를 학습 loss에 포함한다.

3. dataset fidelity 개선
   - 현재 baseline engine과 HCIPy/AOtools 기반 결과를 비교한다.

4. PD placement optimization
   - 같은 PD 개수에서 spacing/geometry에 따른 oracle gain을 비교한다.

5. FPGA prototype
   - 먼저 host inference + FPGA weighted combiner 구조로 검증한다.
   - 이후 ONNX/quantization flow를 통해 inference까지 FPGA로 내린다.

