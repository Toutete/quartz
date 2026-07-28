# ISAC Simulation and Theory Model Validation

검증 대상은 `code/isac_gui_v2.py`의 첫 번째 탭 파형 시뮬레이션, 세 번째 탭의 거리 sweep 및 두 closed-form 그림, 그리고 `concepts/sec2.tex`의 수식이다. 수치 예시는 2026-07-28 현재 기본 이론 조건을 사용한다.

## 1. 결론

전체적인 전파 법칙과 square-law 검파기의 거리 스케일링은 합리적이다. 특히 다음 관계와 최대 거리 해는 정확하다.

- 통신 RF 수신전력: (P_{\rm rx}\propto R^{-2})
- monostatic echo RF 전력: (P_{\rm ec}\propto \sigma_{\rm eff}R^{-4})
- SI--echo cross-beat power: (P_{\rm SI}P_{\rm ec}\propto R^{-4})
- echo self-beat power: (P_{\rm ec}^{2}\propto R^{-8})
- 두 sensing range의 RCS 의존성: (R_{\max}\propto\sigma_{\rm eff}^{1/4})
- ISAC range: (\min(R_{\max}^{\rm comm},R_{\max}^{\rm sens}))

이번 검증에서 코드 오류 네 개를 수정했다.

1. 세 번째 탭 이론 링크에 누락된 OMT 삽입손실 (2L_{\rm OMT}\)를 추가했다.
2. GUI의 UTC-PD 전력이 total carrier-plus-sideband power인 점을 반영해, square-law 식에는 carrier power (P_c=P_{t,\rm tot}/(1+m^2))를 사용하도록 통일했다.
3. ZBD 뒤에 위치한 IF amplifier NF를 RF LNA와 Friis 합성하던 처리를 제거했다. IF amplifier 잡음은 (N)이 아니라 검파 후 고정 바닥 (N_{d,0})에 속한다.
4. communication square-law desired power에 누락됐던 계수 2를 복원했다. sensing echo self-beat와 마찬가지로 unit-power complex waveform의 desired AC power는 (2m^2P_{\rm rx}^2)이다.

다만 현재 `sec2.tex`는 최신 코드와 동일한 모델이 아니다. 논문은 여전히 pilot power allocation (\rho)를 사용하지만, 코드는 기본적으로 full-waveform MMSE sensing을 사용한다. 또한 논문의 (N_{d,0}=-97.5\) dB(mW\(^2\))는 현재 GUI 기본 NEP로부터 계산되는 (-89.0\) dB(mW\(^2\))와 일치하지 않는다. 이 두 항목은 논문 그림을 확정하기 전에 반드시 하나의 정의로 통일해야 한다.

## 2. 기준면과 전력 정의

모든 closed-form RF power는 LNA 입력 기준이다. GUI의 `Operating THz P_t`는 UTC-PD의 total RF output이다.

### 2.1 Carrier power

코드에서

\[
m^2=10^{-\mathrm{CSPR}/10},\qquad
P_c=\frac{P_{t,\rm tot}}{1+m^2}.
\]

CSPR (=13) dB이면 (m^2=0.05012), carrier fraction은 0.95227 또는 (-0.2124) dB이다. 따라서 total TX가 (-10) dBm이고 net isolation이 25 dB이면 이론식의 SI carrier power는 (-35.212) dBm이다.

### 2.2 SI, echo, communication power

(L_{\rm OMT}=10^{IL_{\rm OMT}/10})을 one-pass power loss라 하면,

\[
P_{\rm SI}=P_c10^{-\mathrm{ISO}/10},
\]

\[
P_{\rm ec}(R)=
\frac{P_cG_tG_r\lambda^2\sigma_{\rm eff}}
{(4\pi)^3R^4L_{\rm OMT}^2},
\]

\[
P_{\rm rx}(R)=
\frac{P_cG_tG_c\lambda^2}
{(4\pi)^2R^2L_{\rm OMT}^2}.
\]

`Net SI isolation`은 이미 TX port에서 LNA input까지 측정된 net 값으로 정의한다. 그러므로 SI 경로에 OMT loss를 다시 더하면 중복이다. 반면 echo와 remote communication은 송신 및 수신 방향으로 OMT를 각각 한 번 통과하므로 (L_{\rm OMT}^{-2}), 즉 (2IL_{\rm OMT}) dB가 필요하다.

## 3. Detector-output noise model

### 3.1 RF noise

LNA 입력 기준 RF thermal noise는

\[
N=kT_0F_{\rm LNA}B \quad [\mathrm{mW}]
\]

이다. (B=20) GHz, (T_0=290) K, (F=8) dB이면 (N=-62.965) dBm이다.

### 3.2 Fixed detector floor

현재 이론 코드의 고정 바닥은

\[
N_{d,0}=\eta_{nn}N^2+
\frac{\mathrm{NEP}_{\rm ZBD}^2B}{G_{\rm LNA}^2}
+N_{\rm post,eq}
\quad [\mathrm{mW}^2]
\]

이다. 각 항은 detector-output power-product 기준이므로 (N)과 단위가 다르다.

기본값 (G_{\rm LNA}=13) dB, NEP (=5\) pW/\(\sqrt{\rm Hz}\), (B=20) GHz를 사용하면

- noise--noise beat: (-125.93) dB(mW\(^2\)), 전체의 0.020%
- ZBD NEP: (-89.01) dB(mW\(^2\)), 전체의 99.980%
- 기본 (N_{\rm post,eq}): 무시할 수 있도록 (-300) dB(mW\(^2\))
- 합계: (N_{d,0}=-89.009) dB(mW\(^2\))

따라서 `sec2.tex` 표의 (-97.5) dB(mW\(^2\))는 NEP 5 pW/\(\sqrt{\rm Hz}\)와 동시에 성립하지 않는다. 다른 항을 그대로 두면 (-97.5) dB(mW\(^2\))에 해당하는 effective NEP는 약 1.88 pW/\(\sqrt{\rm Hz}\)이다.

두 선택 중 하나를 사용해야 한다.

- 이론-derived 모델: NEP, LNA gain, bandwidth로 (N_{d,0})를 계산한다. 현재 코드의 기본 방식이다.
- measurement-calibrated 모델: 측정한 (N_{d,0})를 직접 사용하고 NEP 항을 다시 더하지 않는다.

### 3.3 Signal-dependent terms

검파기 분모의 주요 항은

\[
D=N_{d,0}+2N(P_{\rm SI}+P_{\rm ec})
+\kappa m^4P_{\rm SI}^2.
\]

여기서 (2NP)는 carrier--noise beat, (\kappa m^4P^2)는 in-band residual SSBI 근사이다. echo가 매우 약하므로 echo SSBI와 더 높은 차수의 SI--echo distortion은 생략한다.

IF amplifier와 DSO 잡음은 RF (N)에 Friis 합성할 수 없다. 첫 번째 탭 파형 시뮬레이션은 이들을 ZBD 뒤에서 직접 더한다. 세 번째 탭의 ideal 그림은 기본적으로 (N_{\rm post,eq}\simeq0)으로 두므로 실제 DSO 결과보다 낙관적일 수 있다.

## 4. Full-waveform sensing model

기본 모드는 별도 sensing pilot을 중첩하지 않고 알려진 전체 TX waveform을 사용한다.

\[
\widehat H_k=\frac{Y_kS_k^*}{|S_k|^2+\varepsilon}.
\]

MMSE regularization에 따른 coherent efficiency는 occupied-bin 평균 전력을 1로 정규화한 뒤

\[
w_k=\frac{|S_k|^2}{|S_k|^2+\varepsilon},\qquad
\eta_d=\frac{1}{N}
\frac{\left(\sum_kw_k\right)^2}
{\sum_kw_k^2/|S_k|^2}
\]

로 계산한다. 이 값은 자유 calibration parameter가 아니다. 32-QAM, (N=1024), (\varepsilon=0.001)에서 코드의 deterministic 평균은

- OFDM: (\eta_d=-3.45) dB
- DFT-s-OFDM: (\eta_d=-7.27) dB

이다. DFT spreading 후 주파수 표본에 deep null이 생기기 때문에 DFT-s-OFDM의 MMSE 역변환 효율이 더 낮다.

입력한 (G_p)와 (\eta_d)는 역할이 다르다.

- (G_p\): coherent time-bandwidth processing gain. 코드가 (BT\)를 상한으로 적용한다.
- (\eta_d\): waveform spectrum과 MMSE regularization에 의한 efficiency.

따라서 full-waveform 모드에서는 (\eta_dG_p)를 사용하고 (\rho)를 다시 곱하지 않는다. 단, 실측 (G_p\)를 이미 MMSE 손실까지 포함한 end-to-end 값으로 얻었다면 (\eta_d)를 또 곱하면 중복이다. 현재 GUI의 `Sensing Gp,eff`는 **waveform utilization 이전의 coherent gain**으로 해석해야 한다.

## 5. Sensing SINR

현재 코드의 ideal detector-output 식은

\[
\boxed{
\gamma_{\rm sens}(R)=
\eta_dG_p
\frac{2m^2(P_{\rm SI}P_{\rm ec}+P_{\rm ec}^2)}
{N_{d,0}+2N(P_{\rm SI}+P_{\rm ec})
+\kappa m^4P_{\rm SI}^2}}
}.
\]

legacy pilot-only 모드에서만 (\eta_d\) 대신 (\rho)가 들어간다. `Practical ceiling`은 첫/세 번째 탭의 practical range curve에 병렬 SINR ceiling으로 적용될 수 있지만, ideal Fig. 3 raw 식에는 적용하지 않는다.

SI가 없으면

\[
\gamma_{\rm sens}^{\rm no\ SI}(R)=
\eta_dG_p\frac{2m^2P_{\rm ec}^2}
{N_{d,0}+2NP_{\rm ec}}.
\]

약한 echo 및 fixed-floor 한계에서는 (R^{-8})이고, SI cross-beat가 우세하면 (R^{-4})이다.

### 5.1 Sensing range의 exact closed form


\[
P_{\rm ec}=\frac{C}{R^4},\quad
K=2m^2\eta_dG_p,\quad u=R^4
\]

로 두고

\[
D_{\rm SI}=N_{d,0}+2NP_{\rm SI}
+\kappa m^4P_{\rm SI}^2
\]

라 하면 threshold (\gamma_{\rm th})의 방정식은

\[
a u^2+b u+c=0,
\]

\[
a=\gamma_{\rm th}D_{\rm SI},\quad
b=C(2\gamma_{\rm th}N-KP_{\rm SI}),\quad
c=-KC^2.
\]

코드는 cancellation에 강한 형태로 이 방정식의 양의 근을 계산한다. echo--noise beat까지 포함한 exact code equation과 일치한다.

## 6. Communication SINR

full-waveform 모드의 communication 식은

\[
\boxed{
\gamma_{\rm comm}(R)=
\frac{2m^2P_{\rm rx}^2}
{N_{d,0}+2NP_{\rm rx}+\kappa m^4P_{\rm rx}^2}}
}.
\]

legacy pilot superposition에서만 numerator에 (1-\rho)가 들어간다. 이 식의 극한은 다음과 같다.

- fixed-floor limited: (\gamma_{\rm comm}\propto P_{\rm rx}^2\propto R^{-4})
- carrier--noise limited: (\gamma_{\rm comm}\propto P_{\rm rx}\propto R^{-2})
- SSBI limited: (\gamma_{\rm comm}\to2/(\kappa m^2))

threshold (\gamma_c)에 필요한 carrier power는

\[
A_c=2m^2f_d-\gamma_c\kappa m^4,
\]

\[
P_{\rm req}=\frac{\gamma_cN+
\sqrt{(\gamma_cN)^2+A_c\gamma_cN_{d,0}}}{A_c},
\]

\[
R_{\max}^{\rm comm}=\sqrt{\frac{C_{\rm comm}}{P_{\rm req}}}.
\]

full-waveform에서는 (f_d=1), legacy 모드에서는 (f_d=1-\rho)이다. 코드의 quadratic 해와 일치한다. (A_c\le0)이면 SSBI ceiling이 threshold보다 낮으므로 통신 range를 0으로 처리하는 것도 타당하다.

## 7. Fig. 3: Sensing SINR vs SI power

고정 (R_0), 고정 (P_{\rm ec})에서 위 sensing 식을 (P_{\rm SI})에 대해 계산한다. 곡선의 네 구간은 다음과 같이 해석한다.

1. 매우 낮은 SI: echo self-beat (P_{\rm ec}^2)가 남아 있어 평탄하다.
2. cross-beat와 fixed floor 지배: numerator가 (P_{\rm SI}P_{\rm ec})이므로 기울기가 약 1 dB/dB이다.
3. carrier--noise beat 지배: numerator와 denominator가 모두 (P_{\rm SI})에 비례해 포화한다.
4. SSBI 지배: denominator가 (P_{\rm SI}^2)이므로 약 (-1) dB/dB로 감소한다.

수정된 기본값, (R_0=1.1) m와 (\sigma=-8) dBsm에서:

- (P_{\rm ec}=-50.05) dBm
- operating (P_{\rm SI}=-35.21) dBm
- ideal power-ratio homodyne gain: 14.84 dB
- no-SI SINR: 1.72 dB
- operating sensing SINR: 15.72 dB
- 실제 curve gain: 약 14.00 dB
- carrier--noise transition: 약 (-29.05) dBm
- SSBI transition: 약 (-25.70) dBm
- curve maximum: 약 (-25.8) dBm에서 19.91 dB

operating point의 denominator 비율은 fixed floor 79.1%, carrier--noise beat 19.2%, echo--noise 0.63%, SSBI 1.00%이다. 따라서 이 기본 조건은 아직 주로 fixed-floor/noise-limited이며, (\kappa=0.069)의 SSBI가 operating point를 지배하지 않는다.

Fig. 3에 표시된 LNA (P_{1\rm dB})는 유효 범위 경계일 뿐이다. closed-form 식과 파형 시뮬레이션 모두 실제 gain compression 곡선을 계산하지 않는다. 경계를 넘은 곡선은 물리적인 예측값으로 사용하면 안 된다.

## 8. Fig. 2: ISAC range vs effective RCS

기본값 (P_{t,\rm tot}=-10) dBm, CSPR 13 dB, (G_t=G_r=33) dBi, OMT 1.9 dB/pass, (N_{d,0}=-89.01) dB(mW\(^2\)), (kappa=0.069), (\sigma=-8) dBsm에서:

- (R_{\max}^{\rm comm}=1.104) m
- (R_{\max}^{\rm sens}\), with SI (=1.268) m
- (R_{\max}^{\rm sens}\), without SI (=0.788) m
- (R_{\max}^{\rm ISAC}=1.104) m

이 값은 square-law communication desired power의 계수 2와 OMT two-pass loss를 모두 적용한 결과다. 계수 2를 누락한 이전 코드는 0.857 m를 표시했지만, 동일한 15-GBd simulation 조건과 OMT 2.3 dB/pass를 적용하면 corrected closed-form range는 1.102 m이며 1.1 m waveform EVM 결과와 일치한다.

한편 (N_{d,0}=-97.5) dB(mW\(^2\))를 독립적인 calibrated floor로 사용하면 동일한 20-GBd 기본 link의 통신 range는 약 1.46 m가 된다. 따라서 이 floor를 사용하려면 실제 receiver bandwidth와 EVM 결과에 맞춰 다른 noise 항도 함께 재보정해야 한다.

full-waveform 모드에서는 (\rho)가 통신 및 sensing range에 영향을 주지 않는 것이 의도된 결과다. legacy pilot-only 모드에서만 communication의 (1-\rho)와 sensing의 (\rho) trade-off가 남는다.

## 9. 첫 번째 탭 파형 시뮬레이션

### 9.1 포함된 항

첫 번째 탭은 closed-form보다 상세하며 다음을 시간영역에서 계산한다.

- QAM/OFDM/DFT-s-OFDM waveform과 AWG DAC quantization
- MZM third-order Taylor model, EO bandwidth, CSPR calibration
- optical tones와 UTC-PD photomixing, total THz output normalization
- laser linewidth와 선택적 carrier wander
- one-way Friis 및 monostatic radar link, OMT two-pass loss
- net SI isolation
- complex LNA thermal noise와 LNA gain
- memoryless ZBD square-law detection
- ZBD NEP, IF filter, IF amplifier excess noise, DSO analog noise
- SI self-beat cancellation, phase-averaged echo/cross target power
- communication equalization/EVM, matched-filter 및 CFR range processing

따라서 첫 번째 탭의 `Comm. SINR (= -EVM)`과 세 번째 탭의 closed-form communication SINR는 같은 물리량을 목표로 하지만 같은 계산은 아니다. 첫 번째 탭은 waveform realization과 DSP를 포함하고, Fig. 2는 ideal detector-output bound를 사용한다.

### 9.2 주의할 차이

1. **C2 detector-output SINR와 CFR contrast는 다른 metric이다.** 전자는 분리한 target band power와 receiver-noise power에 (\eta_dG_p)를 적용한 phase-averaged link metric이다. 후자는 실제 range profile의 peak-to-floor 또는 peak-to-sidelobe contrast다. 둘이 같은 dB가 될 필요가 없다.
2. **Cross-beat carrier phase를 평균한다.** single capture에서는 SI--echo 상대 위상에 따라 target power가 변할 수 있다. phase-averaged 값은 range law를 검증하기 위한 envelope이지 한 번의 DSO trace를 그대로 예측하는 값이 아니다.
3. **Communication DSP가 낙관적이다.** 저장된 TX data를 알고 있고 여러 timing lag 중 최적 NMSE를 선택한다. 이는 oracle/offline equalization에 가깝다. 실제 remote receiver에는 별도 preamble/DMRS, synchronization overhead와 estimation error가 필요하다.
4. **CFR processing grid가 완전히 동일하지 않다.** DSO full-waveform CFR은 complete DFT-s-OFDM block에 rectangular FFT를 사용하지만, 첫 번째 탭의 표시용 CFR profile은 whole-record Hann FFT를 사용한다. 따라서 이론 (\eta_d), DSO CFR, simulation CFR의 sidelobe와 deep-null noise enhancement가 정확히 같지 않다.
5. **DSO ADC clipping/quantization은 미구현이다.** AWG quantization과 DSO analog noise는 있지만, DSO full-scale clipping 및 ENOB quantization은 직접 적용하지 않는다.
6. **LNA/ZBD compression은 미구현이다.** (P_{1\rm dB})는 이론 그림의 경계선일 뿐이며 시뮬레이션 LNA는 선형이다.

## 10. SI-referenced CFR의 중요한 가정

현재 `si_normalized_cfr_delay_profile()`은 한 capture의 (H(f))에서 weighted scalar mean을 SI reference로 구하고

\[
H(f)/\overline H_{\rm SI}-1
\]

을 계산한다. 이는 common scalar gain/phase는 제거하지만 frequency-dependent (A(f))는 제거하지 못한다.

따라서 `sec2.tex`의 다음 주장은 현재 single-capture 코드만으로는 일반적으로 성립하지 않는다.

- band averaging만으로 (H_{\rm SI}(f)=A(f)e^{j\phi}\sqrt{P_{\rm SI}}) 전체를 얻는다는 주장
- frequency-selective (A(f))의 group delay까지 완전히 제거해 absolute range를 얻는다는 주장

이 주장이 성립하려면 다음 중 하나가 필요하다.

- (A(f))가 occupied band에서 충분히 flat하다는 명시적 가정과 검증
- target-off/SI-only reference에서 (H_{\rm SI}(f))를 주파수별로 저장한 후 pointwise ratio
- calibrated through response를 이용한 주파수별 de-embedding

현재 DSO 코드의 differential CFR/zero-reference 경로는 두 번째 방법을 지원한다. 신뢰도 높은 absolute range에는 absorber target-off reference를 사용하는 것이 가장 안전하다.

## 11. `sec2.tex`와 코드의 불일치

논문을 최신 코드에 맞추려면 다음을 수정해야 한다.

1. `Power Allocation`의 (s=\sqrt\rho p+\sqrt{1-\rho}d)를 기본 모델에서 제거하거나 legacy 비교로 이동한다.
2. sensing 식의 (\rho G_p)를 (\eta_d(\varepsilon)G_p)로 변경한다.
3. communication 식의 (1-\rho)를 full-waveform 기본식에서 제거한다.
4. unregularized (Y/S) 대신 MMSE (YS^*/(|S|^2+\varepsilon))를 기술한다.
5. (P_t)가 total인지 carrier인지 명시한다. total이면 (P_c=P_t/(1+m^2)) 변환이 필요하다.
6. echo와 communication Friis 식에 OMT two-pass loss를 넣거나, (P_t)를 post-OMT power로 다시 정의한다.
7. sensing denominator에 코드가 포함하는 (2NP_{\rm ec})를 추가하거나 weak-echo 생략임을 명시한다.
8. (N_{d,0}=-97.5) dB(mW\(^2\))와 NEP 기반 (-89.0) dB(mW\(^2\)) 중 하나를 선택하고 산출 근거를 표에 적는다.
9. scalar SI normalization으로 제거 가능한 것은 common scalar phase/gain뿐임을 명시하고, (A(f)) 제거에는 target-off calibration이 필요하다고 수정한다.
10. Fig. 2의 (\rho=0.2/0.8) 두 패널은 full-waveform 기본 모델에서 의미가 없다. 단일 RCS sweep이 자연스럽다.

## 12. 남아 있는 근사와 누락

| 항목 | 현재 처리 | 영향/권고 |
|---|---|---|
| (\kappa) | C1/C2에 같은 0.069 사용 | waveform, filter, branch별로 (\kappa_{\rm comm},\kappa_{\rm sens})를 별도 측정하는 것이 정확함 |
| noise--noise overlap | (\eta_{nn}=1) | detector/IF bandwidth convolution에 따른 계수이므로 보수적 상한에 가까움 |
| (N_{\rm post,eq}) | ideal figure에서 사실상 0 | IF amp/DSO를 포함하는 practical curve에는 별도 calibration 필요 |
| RCS | direct scalar (\sigma_{\rm eff}) | aspect, polarization, coherent structural/antenna-mode phase를 포함하지 않음 |
| multipath/clutter | ideal figure에 없음 | target-off 및 여러 range background 측정 필요 |
| atmospheric absorption | 없음 | 1 m에서는 대체로 작지만 정확한 280-GHz link budget에는 습도 기반 흡수 추가 가능 |
| antenna/OMT frequency response | scalar gain/loss | 20-GHz-wide CFR의 group delay와 ripple에는 measured S-parameter가 필요 |
| LNA/ZBD nonlinearity | 경계만 표시 | high-SI curve에는 measured AM/AM 또는 compression model 필요 |
| phase noise | simulation에 Wiener model | 실제 common/non-common laser 구성 및 measured linewidth로 검증 필요 |
| ordinary comm training | oracle TX reference 사용 | full-waveform sensing과 별개로 remote comm preamble overhead 필요 |

## 13. 자동 검증 항목

회귀 테스트가 확인하는 항목은 다음과 같다.

- first-tab Sec. II metric과 third-tab SI curve의 동일 조건 일치
- communication square-law desired term의 계수 (2m^2P_{\rm rx}^2)
- OMT loss 1 dB/pass 증가 시 echo 및 communication coefficient가 각각 2 dB 감소
- net SI power에는 OMT loss가 중복 적용되지 않음
- IF amplifier NF 변화가 LNA-input RF (N)을 바꾸지 않음
- full-waveform range가 legacy (\rho)와 무관함
- legacy mode의 (\rho/(1-\rho)) trade-off 유지
- sensing range의 (\sigma^{1/4}) scaling
- processing gain이 sensing range에만 작용함
- symbol rate에 대해 (N\propto B), (N^2\propto B^2), NEP term (\propto B)
- (\kappa m^4) scaling
- SI sweep의 low-SI floor, linear rise, carrier-noise saturation, SSBI roll-off
- MMSE (\eta_d)의 OFDM/DFT-s-OFDM waveform 통계

## 14. 최종 평가

closed-form의 핵심 주제인 "SI cross-beat로 sensing range law가 (R^{-8})에서 (R^{-4})로 완화된다"는 물리적으로 타당하다. range quadratic과 communication threshold 해도 정확하다. 수정 후 코드의 기준면과 단위는 일관적이다.

현재 결과를 논문의 절대 수치로 사용하기 전에 가장 중요한 작업은 다음 세 가지다.

1. (N_{d,0})를 NEP-derived (-89.0) dB(mW\(^2\))로 쓸지, calibrated (-97.5) dB(mW\(^2\))로 쓸지 확정한다.
2. 논문을 full-waveform (\eta_dG_p) 모델로 바꾸고 남아 있는 (\rho)를 제거한다.
3. target-off SI-only CFR로 (A(f))를 주파수별 보정해 scalar SI-reference 가정을 검증한다.

이 세 항목을 확정하면 Fig. 2/3은 단순한 직관용 이론 그림으로서 충분히 방어 가능하고, 첫 번째 탭은 그 이론에서 벗어나는 waveform/DSP/receiver 구현 손실을 분해하는 simulation 도구로 사용할 수 있다.
