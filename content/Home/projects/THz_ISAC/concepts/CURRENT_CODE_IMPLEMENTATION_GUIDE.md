# Current Code Implementation Guide

> 기준일: 2026-08-03
> Canonical implementation: `code/isac_gui_v2.py`
> 목적: 현재 코드의 탭 구조, 계산 경로, metric 기준면, 측정 저장 형식과 제한사항을 한 문서에서 추적

이 문서는 현재 구현을 설명한다. 논문 수식의 기준 문서는 [CURRENT_PAPER_SYSTEM_MODEL.md](CURRENT_PAPER_SYSTEM_MODEL.md)다. 과거 `concepts/*.md`와 `code/isac_gui.py`는 현재 구현 판단의 기준으로 사용하지 않는다.

## 1. 실행 구조

Entry point는 `main()`이며 `UnifiedApp`이 세 탭을 연결한다.

| Tab | Class | 역할 |
|---|---|---|
| TX Design & Simulation | `IsacTxSimPanel`, `PhotonicIsacSimPanel` | AWG waveform 생성과 시간영역 photonic/THz/ZBD simulation |
| DSO Live Capture | `DsoPanel` | DSO 획득, spectrum/EVM/range/CFR 처리, measurement campaign, NPZ 저장 |
| System Model Validation | `SystemModelValidationPanel` | distance sweep, symbol-rate sweep, closed-form Fig. 2/3, 측정 overlay |

세 탭은 `UnifiedApp.runtime` dictionary와 직접 panel reference를 통해 연결된다.

## 2. 핵심 함수 지도

| Function | 역할 |
|---|---|
| `run_isac_sim()` | 첫 번째 탭 시간영역 simulation 전체 실행 |
| `calc_isac_link_budget()` | one-way 및 monostatic RF link budget |
| `calc_sec2_sensing_sinr()` | 한 지점의 ZBD-output ideal sensing SINR |
| `estimate_mmse_sensing_efficiency()` | waveform 통계로 $\eta_d$ 계산 |
| `sensing_waveform_utilization()` | full-waveform에서는 $\eta_d$, legacy에서는 $\rho$ 반환 |
| `si_normalized_cfr_delay_profile()` | simulation의 SI-normalized CFR profile |
| `DsoPanel._compute_channel_response_for_signal()` | DSO capture의 CFR 계산 |
| `DsoPanel._range_process_channel()` | matched-filter/CFR range processing과 profile metric |
| `SystemModelValidationPanel._closed_form_theory_context()` | Fig. 2/3 공통 RF/검파기 계수 구성 |
| `SystemModelValidationPanel._si_power_sweep_curves()` | sensing SINR versus SI power |
| `SystemModelValidationPanel._rmax_vs_effective_rcs()` | communication/sensing/ISAC range versus RCS |
| `SystemModelValidationPanel._run_distance_sweep()` | 첫 번째 탭 waveform simulation의 range sweep |

## 3. Canonical configuration

`SimConfig`는 첫 번째 탭 계산의 typed configuration이다. 중요한 기준은 다음과 같다.

- `utcpd_target_dbm`: PA 이전 UTC-PD total THz output
- `thz_pa_enable`, `thz_pa_gain_db`: optional ideal THz PA의 on/off와 gain
- `cspr_db`: effective CSPR
- `omt_iso_db`: net TX-to-LNA SI isolation
- `omt_il_db`: one-pass duplexer insertion loss
- `target_effective_rcs_dbsm`: direct effective RCS
- `radar_proc_gain_eff_db`: waveform utilization 이전 coherent $G_p$
- `sensing_reference_mode`: 기본 `full_waveform_mmse`
- `sensing_mmse_regularization`: $\varepsilon$
- `sensing_ssbi_fraction`: $\kappa$
- `sensing_residual_ceiling_db`: practical post-processing ceiling
- `c1/c2_drive_gain_db`, `c1/c2_cable_loss_db`: ZBD 뒤 IF/DSO chain

`omt_*`는 과거 저장 파일/API 호환을 위해 남긴 legacy 내부 key이며, 사용자 표시와 논문 용어는 `duplexer`로 통일한다. Canonical default는 UTC-PD output $-10$ dBm과 PA off다. PA on 및 gain 10 dB를 선택하면 final TX output은 0 dBm이 된다. 공통값은 system antenna/lens gain 33 dBi, bare 17-mm target-horn gain 25 dBi, duplexer loss 2 dB/pass, net isolation 25 dB, effective RCS $-8$ dBsm, $\kappa=0.06$이다. Direct effective-RCS mode에서는 target horn gain을 다시 곱하지 않으며, 25 dBi 값은 coupled-antenna mode에서만 쓰인다.

GUI preset과 dataclass default는 반드시 같지는 않다. 실제 simulation은 GUI field를 읽어 `SimConfig`를 구성하므로 논문 수치를 재현할 때는 저장한 JSON preset을 함께 보관해야 한다.

## 4. 첫 번째 탭 계산 순서

### 4.1 TX waveform

`IsacTxSimPanel._generate_tx_signal()`은 waveform과 AWG reference를 생성하고 `data/current_tx_ref.npz`에 저장한다.

DFT-s-OFDM 기본 구성에서는

- QAM symbols 생성
- DFT spreading 및 active-bin mapping
- optional ZC pilot과 data 합성
- real IF upconversion
- AWG segment alignment 및 DAC quantization

을 수행한다.

Full-waveform sensing mode에서도 송신 payload에 legacy $\rho$/pilot metadata가 남을 수 있지만 sensing reference는 complete `tx_bb_matrix`다.

### 4.2 Photonic and THz chain

`run_isac_sim()`의 주요 순서는 다음과 같다.

1. AWG waveform과 MZM drive metric 계산
2. MZM third-order Taylor response와 DSB/optional SSB optical field 생성
3. Laser phase noise와 optional carrier wander 적용
4. UTC-PD photomixing 후 `utcpd_target_dbm`으로 정규화하고, PA on이면 `thz_pa_gain_db`를 한 번 적용
5. Net duplexer SI와 delayed monostatic echo 생성
6. C1 one-way communication path 생성
7. LNA gain 및 complex RF thermal noise 추가
8. Memoryless ZBD square-law detection
9. ZBD NEP, IF filtering, drive amplifier/cable gain, IF excess noise, DSO analog noise 적용
10. Communication equalization/EVM, C2 target/noise decomposition, range/CFR 처리

### 4.3 Link budget 기준면

`calc_isac_link_budget()`의 C1/C2 RF power는 LNA input 기준이다.

- SI path: `omt_iso_db`만 적용하고 duplexer insertion loss를 재적용하지 않음
- Echo/C1 path: duplexer two-pass loss 적용
- IF chain: RF link power를 바꾸지 않고 ZBD 뒤 waveform amplitude만 변경

## 5. 첫 번째 탭 sensing metric

첫 번째 탭에는 서로 다른 세 sensing metric이 있다.

### 5.1 `sec2_sensing_sinr_db`

- 함수: `calc_sec2_sensing_sinr()`
- 기준면: ZBD-output ideal detector power-product
- 용도: 세 번째 탭 closed-form과 같은 물리식 비교
- C2 post-detector cable loss: 영향 없음
- 기본 반환 `sinr_db`: raw ideal value
- `effective_sinr_db`: optional residual ceiling 적용값

### 5.2 `radar_snr_db` / `snr_rad_post_db_c2`

- 기준면: DSO-input target/noise power에서 시작한 practical predicted post-processing SINR
- target power: phase-averaged SI-echo cross term과 echo self term
- noise: simulation waveform에서 deterministic component를 뺀 residual
- coherent $G_p$와 waveform utilization 적용
- practical residual ceiling 적용
- C2 IF gain/cable loss: 후단 DSO noise가 존재하면 영향 가능

GUI 표기는 `C2 Practical post-proc SINR`다.

### 5.3 `range_profile_contrast_db_c2`

- 실제 normalized CFR 또는 matched-filter range profile의 target peak와 floor 차이
- processing gain을 별도로 더하는 analytical SINR가 아님
- waveform sidelobe, sparse/deep bins, scalar SI normalization, finite record와 phase realization에 영향받음

GUI 표기는 `C2 CFR Target/Floor`다.

세 값은 동일할 필요가 없다.

## 6. C2 IF cable loss 처리

현재 waveform chain은

```text
c2_if_gain_lin = 10^((C2 drive gain - C2 cable loss)/20)
```

을 ZBD signal과 ZBD에서 이미 발생한 noise에 공통 적용한 뒤 DSO noise를 추가한다.

따라서

- flat scalar loss만 있고 후단 noise가 없으면 SINR 불변
- DSO fixed noise가 있으면 cable loss 증가 시 practical/CFR SINR 감소
- `calc_sec2_sensing_sinr()`의 ideal SINR는 불변

현재 IF amplifier excess noise는 net IF gain과 함께 scale된다. 실제 hardware 순서가 `ZBD -> cable -> IF amp -> DSO`라면 IF amplifier noise는 cable로 감쇠되면 안 되므로 noise ordering을 수정해야 한다. `ZBD -> IF amp -> cable -> DSO`라면 현재 가정에 더 가깝다. Passive cable thermal noise와 measured frequency response는 아직 직접 모델링하지 않는다.

## 7. Full-waveform reference 구현

`is_full_waveform_sensing()`은 mode 이름이 pilot/legacy로 시작하지 않으면 full-waveform으로 본다.

`DsoPanel._dfts_ofdm_pilot_matrix()`는

- Full TX mode: `None`을 반환하여 complete `tx_bb_matrix` 사용
- Pilot-only mode: $\sqrt\rho$가 적용된 ZC pilot matrix 반환

Full-waveform CFR는

$$
\widehat H_k=\frac{Y_kD_k^*}{|D_k|^2+\varepsilon}
$$

형태의 MMSE regularization을 사용한다. $\eta_d$는 `estimate_mmse_sensing_efficiency()`가 deterministic waveform statistics로 계산한다.

## 8. Processing gain 구현

GUI의 `Coherent Gp (pre-util.)`는 $G_p$만 의미한다.

```text
net waveform gain = coherent Gp + 10log10(eta_d)
```

Legacy에서는 `eta_d` 대신 `rho`다. `BT`는 coherent gain의 상한으로 적용된다.

주요 저장 key는 다음과 같다.

| Key | 의미 |
|---|---|
| `radar_processing_gain_db_c2` | utilization 이전 coherent $G_p$ |
| `radar_pilot_weighted_gain_db_c2` | 실제 net waveform gain |
| `radar_pre_snr_db_c2` | DSO-input pre-DSP target/noise SINR estimate |
| `processing_gain_definition` | `coherent_before_waveform_utilization` |

Net end-to-end gain을 coherent $G_p$ field에 직접 입력하면 $\eta_d$가 중복 적용된다.

## 9. Communication metric

첫 번째 탭의 communication metric은 equalized symbols로 계산한 EVM이다.

```text
Comm. SINR (= -EVM) = -EVM_dB
```

세 번째 탭의 distance sweep은 가능한 경우 첫 번째 탭 simulation의 EVM-implied SINR를 그대로 사용한다. Closed-form RCS figure의 communication range는 detector-output Eq.에 기반한 이상적 bound다. 따라서 같은 threshold를 사용해도 waveform EVM curve와 closed-form curve는 calculation path가 다르다.

## 10. DSO Live Capture

### 10.1 Capture data

DSO 획득은 channel별 raw waveform, time axis, sample rate를 보관한다. TX reference가 있으면 waveform, QAM symbols, block matrix, pilot, active bins와 configuration을 capture NPZ에 함께 저장한다.

`Save`는 재처리에 필요한 raw data와 현재 metric을 저장한다. `Save Range`는 range/CFR reference와 summary를 추가한다.

### 10.2 Spectrum and band metrics

- C1: communication band power, noise floor, EVM/SNR
- C2: raw total band power, SI-cancelled/coherent band power, target/noise estimate
- PSD와 integrated band power는 구분하여 저장

Band-power sensing estimate는 range-profile SINR와 별도다. 동일 band power라도 energy가 delay bin에 분산되면 CFR contrast는 달라진다.

### 10.3 Range processing

`_range_process_channel()`은

1. IF-to-baseband 변환
2. frame sync와 block reshape
3. selected sensing reference 구성
4. linear matched filtering
5. monostatic range axis 변환
6. target peak, local floor, PSLR와 floor IQR 계산
7. optional SI-normalized/differential CFR 계산

을 수행한다.

Range-profile sensing SINR는 target peak power를 off-target median floor와 비교한다.

$$
\mathrm{SINR}_{\rm profile}=10\log_{10}
\left(\frac{P_{\rm peak}}{P_{\rm floor}}-1\right).
$$

이는 detector-output analytical SINR가 아니라 realized detection statistic이다.

### 10.4 Zero and target-off reference

`Store Zero Ref`는 channel별 peak lag, profile, CFR를 저장한다. 현재 normal detection은 absolute range axis를 유지하고 reference는 overlay와 differential range에 사용한다.

Frequency-dependent chain response 제거에는 absorber target-off SI-only CFR를 저장하고 pointwise ratio를 사용하는 것이 권장된다.

## 11. Measurement campaign

한 measurement set은 다음 네 상태를 같은 range, photocurrent, waveform 설정으로 묶는다.

| State | Hardware condition | 주 용도 |
|---|---|---|
| 1 RX Noise | UTC-PD dark, $I_{ph}\approx$nA | receiver/DSO noise |
| 2 Carrier Noise | 정상 photocurrent, AWG IF off | optical/UTC carrier-only noise |
| 3 SI-only | waveform on, target-off absorber | SI와 background baseline |
| 4 Target-on | waveform on, target present | communication 및 target excess |

추가 sweep은 다음을 지원한다.

- AWG-DSO direct point/sweep
- clock sync 상태
- AWG Vpp와 DSO voltage scale
- $N_p=128,256,512,1024$
- legacy $\rho$ sweep
- range와 photocurrent metadata

### 11.1 Campaign SNR

```text
Comm SNR = (C1 target-on - C1 RX-noise) / C1 RX-noise
Sensing pre-SINR = (C2 target-on - C2 SI-only) / C2 SI-only
```

모든 pair는 waveform, $N_p$, $\rho$, range, photocurrent가 일치해야 한다.

### 11.2 Processing-gain estimator

현재 `Estimate Processing Gain` workflow는 의도적으로 `Pilot-only (legacy)`를 강제한다.

$$
G_{p,\rm dB}=
\mathrm{SINR}_{post,\rm dB}-
\mathrm{SINR}_{pre,\rm dB}-10\log_{10}\rho.
$$

결과는 utilization 이전 coherent gain으로 저장된다. Full-waveform end-to-end gain을 직접 측정하는 별도 estimator는 아직 없다.

### 11.3 RCS estimator

현재 RCS estimator는 legacy campaign의 $\rho$와 estimated coherent gain을 사용하여 DSO-equivalent target power를 역산한다. `RX chain gain`은 ZBD square-law, IF chain, cable, DSO conversion을 모두 포함하는 input-referred calibration이어야 한다.

이 calibration이 없으면 RCS 결과는 절대값이 아니라 effective fitting parameter다. Full-waveform campaign용 RCS estimator로 일반화하려면 $\rho G_p$를 selected reference의 net gain $\eta_dG_p$로 바꿔야 한다.

## 12. 반복 측정과 저장 용량

반복 측정은 최적 trace 하나만 남기는 대신 summary와 representative raw를 함께 보관하는 방향이다.

- EVM/range/power 반복 결과의 median, spread, best/worst와 설정 저장
- measurement set JSON에는 각 record의 condition, hardware metadata, metrics, derived result 저장
- `Keep raw`가 꺼진 기본 측정은 summary/metadata만 유지하여 저장 용량 절감
- `Keep raw`가 켜진 record는 명시적 Save Set과 autosave 모두 raw arrays 포함 가능
- range summary에는 channel별 SINR, coherent/net gain, PSLR, range와 definition metadata 저장

Old NPZ에는 sensing reference mode와 processing-gain definition이 없을 수 있다. 이 경우 파일의 숫자만 보고 full-waveform gain인지 pilot-weighted gain인지 단정하면 안 된다.

## 13. 세 번째 탭

세 번째 탭에는 성격이 다른 calculation이 공존한다.

### 13.1 Range Sweep

`Range Sweep`은 첫 번째 탭 simulation configuration을 이용해 여러 range에서 `run_isac_sim()`을 새로 실행한다.

- communication: waveform EVM-implied SINR
- sensing simulation curve: first-tab practical sensing metric
- measured marker: manual EVM, C2 measurement, loaded captures

`Sync Sim`은 current first-tab parameters와 최신 result를 복사하지만 range curve 자체는 `Range Sweep`을 실행해야 갱신된다.

### 13.2 Fig. 2, ISAC range versus effective RCS

`_rmax_vs_effective_rcs()`는 analytical closed form을 사용한다.

- 논문용 ideal bound이므로 sensing waveform efficiency는 $\eta=1$
- AWG/DSO quantization, measured MMSE loss와 practical residual ceiling은 제외

- communication threshold quadratic
- sensing with SI의 $u=R^4$ quadratic
- sensing without SI
- joint range의 minimum

RCS point 수는 201로 고정되어 있다. Y축은 0.1에서 5 m의 log scale이다. Ideal Fig. 2/3은 $\eta=1$과 full communication power를 사용하므로 legacy $\rho$ 입력도 curve에 영향을 주지 않는다.

### 13.3 Fig. 3, sensing SINR versus SI power

`_si_power_sweep_curves()`는 LNA-input SI carrier power를 $-60$에서 $-20$ dBm까지 sweep한다.

이 그림도 ideal closed form이므로 $\eta=1$이며 AWG/DSO quantization을 포함하지 않는다. 첫 번째 `SINR vs range` 그림의 simulation/measurement curve에는 실제 waveform utilization과 receiver 구현 손실이 남는다.

반환 component는

- fixed floor
- SI-noise beat
- echo-noise beat
- SSBI
- with-SI curve
- no-SI floor
- ideal cross-beat/fixed-floor asymptote

를 포함한다. 현재 저장 그림에는 shading, linear guide와 operating marker를 그리지 않는다. GUI hover marker는 읽기 전용이며 저장 PNG에는 포함하지 않는다.

### 13.4 Figure saving

`Save Figures`는 기본적으로 다음 파일을 `code/data`에 600 dpi로 저장한다.

- `communication_sensing_sinr_vs_range.png`
- `evm_vs_symbol_rate.png`
- `isac_range_vs_effective_rcs.png`
- `sensing_sinr_vs_si_power.png`
- `sensing_sinr_vs_utcpd_photocurrent.png`

Legend 저장 여부는 별도 checkbox를 따른다.

## 14. Closed-form units

단위 혼합을 피하기 위한 규칙은 다음과 같다.

- RF powers $P_c,P_{\rm SI},P_{\rm ec},P_{\rm rx},N$: mW, LNA input
- Detector denominator $N_{d,0},2NP,\kappa m^4P^2$: mW$^2$
- Antenna gain, loss, isolation: linear power ratio로 변환 후 계산
- CSPR modulation index: $m^2=10^{-\mathrm{CSPR}/10}$
- Processing gain과 utilization: linear로 곱하고 마지막에 dB 변환
- Range equation: SI amplitude가 아니라 SI power 사용

## 15. Metric 이름과 해석

| GUI/Key | 해석 |
|---|---|
| `Comm SNR (EVM)` | equalized communication EVM의 음수 dB |
| `C2 ZBD-output ideal SINR` | Sec. II 한 지점 이론값 |
| `C2 Practical post-proc SINR` | DSO-input target/noise 기반 예측값 |
| `C2 CFR Target/Floor` | realized range-profile contrast |
| `C2 DSO-input Pre-DSP SINR` | utilization과 coherent gain을 제거한 DSO-plane estimate |
| `Coherent Gp (pre-util.)` | $G_p$ |
| `Net Waveform Gain` | $G_p+10\log_{10}\eta_d$ 또는 legacy $G_p+10\log_{10}\rho$ |
| `PSLR` | target peak 대 가장 큰 sidelobe |
| `Band Power` | selected IF band의 integrated electrical power |

## 16. 현재 모델의 제한

1. LNA와 ZBD gain compression은 구현하지 않고 $P_{1\rm dB}$ 경계만 표시한다.
2. DSO analog noise는 있으나 ADC clipping과 ENOB quantization은 직접 구현하지 않는다.
3. Cable은 scalar loss이며 measured amplitude/group-delay response가 없다.
4. Multipath, clutter, target aspect variation은 ideal figures에 없다.
5. Simulation communication DSP는 known TX와 best timing/NMSE를 사용하여 실제 remote receiver보다 낙관적일 수 있다.
6. Single-capture SI normalization은 frequency-selective $A(f)$를 제거하지 못한다.
7. $\kappa=0.06$을 C1/C2에 공통 적용하지만 branch별 측정값이 더 정확하다.
8. First-tab CFR와 DSO CFR의 FFT/window/grid가 완전히 같지 않다.
9. RCS estimator는 complete receiver calibration에 민감하며 현재 legacy campaign 식을 사용한다.
10. THz PA는 이상적인 power scaling으로만 흡수되며 AM-AM/AM-PM, added noise/phase noise, spectral regrowth와 output compression은 모델링하지 않는다.
11. 평균 SI가 약 $-25.21$ dBm일 때 LNA $P_{1\rm dB}=-20$ dBm까지 평균 여유는 약 5.2 dB이며 waveform peak/PAPR 여유는 별도 검증이 필요하다.

## 17. Regression tests

주요 test file은 다음과 같다.

- `test_isac_gui_v2_theory.py`
- `test_system_model_validation_math.py`
- `test_gamma_coupled_link.py`

검증 항목에는 다음이 포함된다.

- first/third-tab Sec. II 식 일치
- communication desired coefficient 2
- duplexer two-pass loss와 net SI isolation
- full-waveform의 $\rho$ 불변성
- $\eta_d$ 한 번 적용과 net gain
- $R_{\max}\propto\sigma^{1/4}$
- SI sweep의 floor, linear, saturation, SSBI roll-off
- detector-output SINR의 post-detector cable-loss 불변성
- 1.1 m communication threshold consistency

실행 예:

```powershell
cd C:\Users\user\quartz\content\Home\projects\THz_ISAC\code
python -m py_compile isac_gui_v2.py
python -m unittest -q test_isac_gui_v2_theory.py test_system_model_validation_math.py test_gamma_coupled_link.py
```

`test_system_model_validation_math.py`의 startup-preset test는 legacy `data/isac_sim_params_20260724_015432.json`이 없으면 skip된다. 이 파일의 유무는 현재 v2 모델 수식 검증과 무관하다.

## 18. 변경 시 점검 순서

1. Parameter의 기준면과 total/carrier power 정의 확인
2. Linear amplitude, linear power, dB 변환 확인
3. $\eta_d$, $\rho$, $G_p$ 중복 적용 여부 확인
4. SI path의 net isolation과 duplexer loss 중복 여부 확인
5. ZBD 전 RF noise와 ZBD 후 IF/DSO noise 분리
6. Ideal detector-output metric과 practical/CFR metric 분리
7. First-tab single point와 third-tab analytical operating point 비교
8. Range threshold equation을 원식에 대입하여 검산
9. Relevant unit tests 실행
10. NPZ schema에 새 metric의 definition/source metadata 저장

## 19. 현재 권장 workflow

### 논문 이론 그림

1. Third tab에서 `Full TX (MMSE)` 선택
2. $\varepsilon$, modulation, waveform, $G_p$, $\kappa$, NEP와 bandwidth 확정
3. `Sync Sim`으로 RF/link parameter 동기화
4. Fig. 2/3 closed-form redraw
5. `Save Figures`

### Simulation versus theory

1. First tab에서 deterministic seed로 simulation 실행
2. `C2 ZBD-output ideal SINR`, `Practical post-proc SINR`, `CFR Target/Floor`를 각각 기록
3. Third tab에서 `Sync Sim`
4. 동일 operating point의 closed-form component 확인
5. 차이를 waveform distortion, post-detector noise, phase, CFR floor로 분해

### 재측정

1. RX Noise
2. Carrier Noise
3. Target-off absorber SI-only
4. Target-on
5. 같은 setting에서 range/photocurrent sweep
6. Capture와 compact measurement set 저장
7. Target-off CFR pointwise calibration
8. Processing gain과 RCS는 gain definition 및 receiver calibration을 확인한 뒤 계산
