# Effective RCS 기반 ISAC Range 및 C2 Spectrum 모델링 정리

## 1. 논의 목적

기존의 `ISAC range vs. power-allocation ratio` 그래프를 `ISAC range vs. Effective RCS`로 변경하고, 통신 수신 안테나가 동시에 반사 표적 역할을 하는 시스템의 물리 모델을 일관되게 정리한다. 또한 simulation의 C1/C2 spectrum에 표시되는 band power의 정의와 실제 측정 C2 spectrum의 주파수 선택성을 해석한다.

## 2. 통신 수신과 안테나 반사의 결합

표적 안테나 급전부의 반사계수를 \(\Gamma\)라고 하면 입사 전력은 통신 수신기에 흡수되는 성분과 재방사되는 성분으로 나뉜다.

\[
P_{\mathrm{incident}}
=
(1-|\Gamma|^2)P_{\mathrm{incident}}
+
|\Gamma|^2P_{\mathrm{incident}}.
\]

따라서 통신 수신 전력은

\[
P_{\mathrm{rx}}(R)
=
(1-|\Gamma|^2)
\frac{P_tG_tG_c\lambda^2}{(4\pi)^2R^2}
\]

로 모델링한다. 이에 대응하는 mismatch loss는

\[
L_{\Gamma}
=
-10\log_{10}(1-|\Gamma|^2)\quad\mathrm{dB}
\]

이다.

안테나 모드 RCS는

\[
\sigma_{\mathrm{ant}}
=
\frac{\lambda^2G_{\mathrm{tar}}^2}{4\pi}
|\Gamma|^2\eta_{\mathrm{pol}}
\]

로 나타낼 수 있다. 구조 산란을 포함하면 단순화된 coupled-antenna 모델은

\[
\sigma_{\mathrm{eff}}
=
\sigma_{\mathrm{str}}+\sigma_{\mathrm{ant}}
\]

이다. 현재 simulation은 구조 RCS 기본값으로 \(\sigma_{\mathrm{str}}=0.01\,\mathrm{m^2}\)를 사용한다.

### 물리적 주의사항

구조 모드와 안테나 모드는 본질적으로 복소 전계이므로, 정확한 총 RCS에는 두 산란장의 상대 위상에 따른 constructive/destructive interference가 포함될 수 있다. 위 식의 단순 합은 위상 평균 또는 incoherent addition에 가까운 근사다.

각 성분의 크기와 위상을 독립적으로 방어하기 어려운 논문 분석에서는, 실제 관측 방향에서 측정되거나 가정된 총 산란량을 하나의 \(\sigma_{\mathrm{eff}}\)로 사용하는 것이 더 견고하다. 여기에는 다음 효과가 모두 포함된 것으로 해석한다.

- 잔여 안테나 부정합
- 구조 산란
- 입사각과 관측각
- 편파 손실
- 주파수 의존성
- 안테나 모드와 구조 모드 사이의 위상 간섭

## 3. Effective RCS sweep의 해석

세 번째 탭의 Effective RCS sweep에서 \(\sigma_{\mathrm{eff}}\)는 설계 변수가 아니라 시나리오 또는 불확실성 변수로 직접 사용한다. 각 sweep 점에서 \(\sigma_{\mathrm{eff}}\)로부터 \(\Gamma\)를 역산하지 않는다.

따라서 현재 설정된 \(\Gamma\)와 통신 accepted-power fraction은 sweep 전체에서 고정되며,

\[
R_{\max}^{\mathrm{comm}}(\sigma_{\mathrm{eff}})
=\mathrm{constant}
\]

가 된다. 단, 서로 다른 \(\rho\) 패널에서는 데이터 전력 할당이 다르므로 communication range가 달라질 수 있다.

현재 표시 조건은 다음과 같다.

- \(P_t=0\,\mathrm{dBm}\)
- 세 번째 탭에 입력된 단일 \(\rho\) 값
- Effective RCS 범위: 기본적으로 \(-30\)–\(0\,\mathrm{dBsm}\)

그래프에는 다음 네 trace를 표시한다.

1. Communication range
2. Sensing range with SI
3. Sensing range without SI
4. ISAC range with SI

기준 RCS 값을 나타내는 별도의 수직선이나 text annotation은 표시하지 않는다.

## 4. SI 유무에 따른 sensing SINR

SI reference가 존재할 때 phase-averaged ZBD target power에는 SI--echo cross-beat와 echo self-beat가 모두 존재한다.

\[
\mathrm{SINR}_{\mathrm{sens}}^{\mathrm{with\ SI}}
=
G_p\frac{2m^2\rho\left[P_{\mathrm{SI}}P_{\mathrm{ec}}(R)+P_{\mathrm{ec}}^2(R)\right]}{P_0N}.
\]

따라서 exact with-SI SINR은 \(R^{-4}\) cross-beat와 \(R^{-8}\) self-beat의 합이다. 장거리에서 \(P_{\mathrm{SI}}\gg P_{\mathrm{ec}}\)일 때만 \(R^{-4}\) 근사가 지배적이다.

SI reference가 없으면 echo self-beat만 사용한다.

\[
\mathrm{SINR}_{\mathrm{sens}}^{\mathrm{w/o\ SI}}(\rho,R)
=
G_p\frac{2m^2\rho P_{\mathrm{ec}}^2(R)}{N},
\]

따라서 \(R^{-8}\)로 감소한다. Noise-limited 조건에서 두 SINR의 비는

\[
\frac{\mathrm{SINR}_{\mathrm{with\ SI}}}
{\mathrm{SINR}_{\mathrm{w/o\ SI}}}
=
1+\frac{P_{\mathrm{SI}}}{P_{\mathrm{ec}}(R)}
\]

가 된다. 흔히 사용하는 \(P_{\mathrm{SI}}/P_{\mathrm{ec}}\)는 with-SI 식에서도 self-beat를 생략한 장거리 근사이다. exact 식에서는 with-SI sensing range가 without-SI보다 작아질 수 없다.

Effective RCS에 대한 with-SI sensing range의 scaling은

\[
R_{\max}^{\mathrm{sens,SI}}
\propto
\sigma_{\mathrm{eff}}^{1/4}
\]

이므로 RCS가 \(40\,\mathrm{dB}\) 증가하면 sensing range가 한 decade 증가한다.

세 번째 탭의 이 그래프는 실제 distance sweep 결과가 아니라 simulation parameter에 기반한 결정론적 link-budget 계산으로 그린다. `Redraw` 버튼으로 즉시 갱신하며 별도의 physical range sweep은 필요하지 않다.

## 5. C1/C2 Spectrum의 band power 정의

분석 대역은 IF 중심주파수 \(f_{\mathrm{IF}}\)와 occupied bandwidth \(B\)로 정의한다.

\[
\mathcal{B}
=
\left[f_{\mathrm{IF}}-\frac{B}{2},
f_{\mathrm{IF}}+\frac{B}{2}\right].
\]

화면에 표시된 raw PSD의 적분 전력은

\[
P_{\mathrm{raw,band}}
=
\int_{\mathcal{B}}S_{\mathrm{raw}}(f)\,df
\]

이다.

### C1 표시값

- `Raw band`: 화면의 C1 raw PSD를 분석 대역에서 적분한 총 전력
- `Signal (noise-sub.)`: raw band power에서 추정 잡음전력을 뺀 신호 전력

### C2 표시값

- `Raw band`: 화면의 C2 raw PSD를 분석 대역에서 적분한 총 전력
- ZBD 모드의 `Target (phase-avg.)`: target에 의해 발생한 결정론적 성분만 분리한 전력
- Mixer 모드의 `Coherent (noise-sub.)`: coherent output에서 잡음을 차감한 전력

## 6. C2 Target Band Power의 의미

ZBD 모드의 C2 target band power는 화면에 보이는 raw spectrum의 단순 적분값이 아니다. Simulation 내부에서 target-related 성분을 분리하고 미지의 반송파 위상에 대해 평균한 값이다.

\[
P_{\mathrm{C2,target}}
=
P_{\mathrm{echo,self}}
+
\frac{1}{2}
\left(
P_{\mathrm{SI\text{-}echo,I}}
+
P_{\mathrm{SI\text{-}echo,Q}}
\right).
\]

이 값에는 다음 성분이 포함되지 않는다.

- 수신기 및 DSO 잡음
- SI-only self-beat
- Target과 무관한 distortion 또는 SSBI

따라서 다음 두 값을 구분해야 한다.

\[
P_{\mathrm{raw,band}}
\neq
P_{\mathrm{C2,target}}.
\]

Simulation C1/C2 spectrum에는 두 정의가 혼동되지 않도록 각각의 값을 그래프 내부에 함께 표시한다.

세 번째 탭의 `C2 raw IF-band power vs range` 그래프는 측정 spectrum의 raw band integral과 simulation의 `c2_raw_band_metrics["raw_band_power_dbm"]`를 직접 비교한다. Sensing SINR는 이 raw total power가 아니라 분리된 target-only power, noise power와 effective processing gain으로 계산한다. SI-only 및 noise background가 지배하면 raw band power가 거의 일정하더라도 target-only power와 sensing SINR는 거리에 따라 크게 변할 수 있다.

## 7. 실제 측정 C2 spectrum의 주파수 선택성

측정된 C2 spectrum의 주파수 선택성을 자유공간 multipath 하나만으로 설명하기는 어렵다. 측정 결과는 대략 다음 요소의 합성 결과로 보아야 한다.

\[
S_{\mathrm{C2,meas}}(f)
=
|H_{\mathrm{IF}}(f)|^2
\left[
S_{\mathrm{SI,self}}(f)
+S_{\mathrm{echo,self}}(f)
+S_{\mathrm{SI\text{-}echo}}(f)
\right]
+S_n(f).
\]

가능성이 높은 원인은 다음과 같다.

1. ZBD square-law detection에 의한 spectral convolution/correlation
2. 송신 waveform과 photonic transmitter의 비평탄한 spectrum
3. ZBD responsivity와 IF amplifier의 주파수 응답
4. Cable, DC block, connector와 DSO 입력의 전달함수
5. Impedance mismatch에 의한 standing-wave ripple
6. SI와 echo 사이의 coherent cross-beat

첨부된 측정 그래프에서 분석 band 경계는 spectrum을 잘라내는 filter가 아니라 표시용 marker다. 따라서 상단 band edge 이후의 하강은 단순한 plotting mask가 아니라 캡처 신호 또는 하드웨어 응답에 실제로 존재하는 현상이다.

## 8. SI–echo 간섭 가능성

SI와 echo 사이의 간섭은 C2의 frequency selectivity를 만드는 유력한 원인이다. 동시에 이 시스템에서는 제거 대상인 간섭만이 아니라 의도된 sensing mechanism이기도 하다.

ZBD 입력을

\[
x(t)=x_{\mathrm{SI}}(t)+x_{\mathrm{ec}}(t)
\]

라고 하면 square-law 출력은

\[
|x(t)|^2
=
|x_{\mathrm{SI}}(t)|^2
+|x_{\mathrm{ec}}(t)|^2
+2\operatorname{Re}
\left\{
x_{\mathrm{SI}}(t)x_{\mathrm{ec}}^*(t)
\right\}.
\]

마지막 항이 SI–echo cross-beat이며, SI-assisted sensing gain을 만드는 핵심 성분이다.

Echo를 SI의 지연된 복사본으로 근사하면

\[
X_{\mathrm{ec}}(f)
=
a(f)X_{\mathrm{SI}}(f)e^{-j2\pi f\tau}.
\]

두 신호의 합성 전력에는 다음과 같은 간섭항이 발생한다.

\[
|X_{\mathrm{SI}}(f)+X_{\mathrm{ec}}(f)|^2
=
|X_{\mathrm{SI}}(f)|^2
+|X_{\mathrm{ec}}(f)|^2
+2|X_{\mathrm{SI}}(f)||X_{\mathrm{ec}}(f)|
\cos\left(2\pi f\tau+\phi(f)\right).
\]

이상적인 단일 echo라면 ripple 간격은

\[
\Delta f\simeq\frac{1}{\tau}.
\]

Monostatic 표적의 왕복 지연 \(\tau=2R/c\)를 적용하면

\[
\boxed{\Delta f\simeq\frac{c}{2R}}.
\]

예상 ripple 간격은 다음과 같다.

| 표적 거리 | 왕복 지연 | 예상 ripple 간격 |
|---:|---:|---:|
| 0.5 m | 3.33 ns | 300 MHz |
| 1.0 m | 6.67 ns | 150 MHz |
| 2.0 m | 13.3 ns | 75 MHz |

다만 측정 그래프의 넓은 기울기, 큰 step 또는 광대역 융기를 단일 SI–echo 간섭만으로 설명하기는 어렵다.

- 빠르고 주기적인 ripple: SI–echo 지연 간섭 또는 cable reflection 가능성
- IF 중심 부근의 넓은 융기: cross-beat, 송신 spectrum 또는 IF gain peak 가능성
- 넓은 대역의 기울기와 step: ZBD/IF chain 및 sideband imbalance 가능성
- 대역 끝의 roll-off: detector, amplifier, cable 또는 DSO bandwidth 가능성

## 9. 원인 분리를 위한 권장 측정

다음 측정을 통해 SI–echo 간섭과 하드웨어 전달함수를 분리할 수 있다.

1. **TX off**: 수신기 및 DSO의 colored noise 측정
2. **Target 차단 또는 absorber 설치**: SI-only spectrum 측정
3. **Target 거리 변경**: ripple 간격과 위치가 \(c/(2R)\) 관계를 따르는지 확인
4. **IF cable 길이 변경**: ripple이 이동하면 cable standing wave로 판단
5. **IF center 변경**: 신호와 함께 이동하는 feature와 절대주파수에 고정된 하드웨어 feature 분리
6. **VNA 측정**: IF chain의 \(S_{21}\) 및 주요 연결부의 \(S_{11}\) 측정
7. **반복 평균**: Welch variance와 재현 가능한 deterministic ripple 분리

판단 기준은 다음과 같다.

- Target 거리에 따라 ripple이 이동: SI–echo 또는 free-space path 관련
- 모든 거리에서 동일한 모양: ZBD/IF chain/cable response 관련
- Target 차단 시 ripple 소멸: echo-related component
- Target 차단 후에도 유지: SI self-beat 또는 hardware response

## 10. 구현 및 검증 상태

현재 코드에는 다음 사항이 반영되어 있다.

- C1/C2 simulation spectrum에 band power 표시
- C2 raw band power와 phase-averaged target power 구분
- 세 번째 탭 C2 power의 measured-raw 대 simulated-raw 비교
- Effective RCS를 직접 사용하는 ISAC range 그래프
- Effective RCS sweep 중 고정된 \(\Gamma\)와 평탄한 communication range
- With-SI 및 without-SI sensing range의 결정론적 계산
- `Redraw` 버튼을 통한 세 번째 탭 그래프 갱신
- 작은 화면에서 세 번째 탭 제어부를 사용할 수 있도록 scroll 지원
- Effective processing gain을 사용자가 조절하고 `Redraw`로 cached target-power SINR에 적용

최종 점검에서는 `_fit_c2_power_slope()`에 누락된 `x`, `y` 초기화를 복구했다. 이 누락이 `Redraw` 마지막 validation 단계의 `name 'x' is not defined` 오류 원인이었다. 거리 span이 1.5배 미만이면 불안정한 기울기를 보고하지 않고, 그 이상이면 `log10(range)`에 대해 dBm 기울기를 적합한다. Python syntax 검사, 실제 Tk `Redraw` smoke test, 관련 회귀 테스트 11개가 통과했다. 또한 세 번째 탭 클래스에 중복 method 및 중복 GUI parameter key가 없음을 AST로 확인했다. 전체 test discovery는 계측기 제어용 선택 의존성인 `pyvisa`가 설치되지 않은 환경에서 하드웨어 모듈 import 단계가 제한된다.

## 11. 실제 측정 데이터에 의한 SI–echo 간섭 검증

분석 파일은 다음과 같다.

`code/data/captures/Data_fIF12_fsym20_P-5_fRF280_DFT-s-OFDM_32QAM_Iph7.8.npz`

주요 측정 조건은 다음과 같다.

- C1/C2 각각 196,608 samples
- Sampling rate: 256 GSa/s
- Capture duration: 768 ns
- IF: 12 GHz
- Symbol rate: 20 GBaud
- RF carrier: 280 GHz
- Waveform: DFT-s-OFDM 32QAM
- AWG power: −5 dBm
- Photocurrent: 7.8 mA
- 저장된 C2 range peak: 1.0125 m
- C2 band power: −30.745 dBm
- C2 SNR: 12.625 dB
- C2 PSLR: 1.554 dB

저장된 C2 range에 해당하는 monostatic 왕복 지연과 spectral ripple 간격은

\[
\tau=\frac{2R}{c}=6.750\ \mathrm{ns},
\qquad
\Delta f=\frac{1}{\tau}=148.148\ \mathrm{MHz}
\]

이다.

C2 log-PSD에서 0.5–2.0 GHz 폭의 smooth trend를 제거하고 delay-domain periodicity를 조사한 결과, 저장된 range 값을 사용하지 않은 blind search에서도 가장 강한 peak가 정확히 \(6.7500\) ns에서 검출되었다. 이를 거리로 환산하면

\[
R_{\mathrm{blind}}
=\frac{c\tau_{\mathrm{blind}}}{2}
=1.01250\ \mathrm{m}
\]

로 저장된 C2 range와 일치한다.

| 분석 대상 | 6.75 ns 성분 순위 | Delay-spectrum peak/background | Sinusoidal ripple amplitude |
|---|---:|---:|---:|
| TX AWG 기준파형 | 7위 | 2.99 | 0.190 dB |
| C1 | 4위 | 3.56 | 0.232 dB |
| C2 | **1위** | **26.94** | **2.564 dB** |
| C2/C1 log-PSD ratio | **1위** | **36.33** | **2.761 dB** |

Welch segment 길이 16,384/32,768/65,536 samples와 smoothing 폭 0.5/1.0/2.0 GHz를 조합한 9개 분석 조건 모두에서 C2의 가장 강한 delay peak는 6.750 ns였다.

전체 capture를 128 ns씩 여섯 구간으로 나눈 결과도 다음과 같다.

- 여섯 구간 모두 6.75 ns 성분이 1위
- 구간별 ripple phase: 약 70–83°
- Phase circular concentration: 0.9975

따라서 이 ripple은 periodogram variance가 아니라 capture 동안 안정적인 deterministic interference이다. 6.75 ns 단일 성분은 C2 detrended fine-ripple 분산의 약 32%, C2/C1 spectral-ratio fine-ripple 분산의 약 38%를 설명한다.

이 결과는 1.0125 m target echo와 SI 사이의 coherent cross-beat가 실제로 존재한다는 것을 강하게 지지한다. 다만 추가 측정 없이 동일한 지연을 가진 다른 고정 반사 경로를 완전히 배제할 수는 없다. 또한 C2 PSLR이 1.554 dB로 낮으므로 range profile에서 이 peak가 다른 peak를 압도한다고 보기는 어렵다.

## 12. 시간에 따른 amplitude fluctuation과 outage

### 12.1 고정된 간섭과 시간변화 간섭의 구분

SI–echo 간섭이 존재한다고 해서 항상 시간에 따른 큰 amplitude fluctuation이 발생하는 것은 아니다.

- SI 경로, target 거리, carrier phase가 안정적이면 간섭은 시간적으로 거의 고정된다.
- 이 경우에는 시간 fading보다 고정된 frequency ripple과 거리별 constructive/destructive response가 나타난다.
- Target motion, vibration, oscillator wander, phase noise 또는 산란 위상 변화가 있으면 상대 위상 \(\theta(t)\)가 변하면서 amplitude가 시간에 따라 출렁인다.

단일 실수 homodyne/ZBD projection의 target-dependent cross-beat를 단순화하면

\[
y_{\mathrm{cross}}(t)=A(t)\cos\theta(t)
\]

로 쓸 수 있다. 해당 전력은

\[
P_{\mathrm{cross}}(t)=A^2(t)\cos^2\theta(t)
\]

가 된다. 따라서 \(\theta=\pi/2+k\pi\)에서는 SI와 echo가 모두 존재하더라도 측정 quadrature가 null에 빠질 수 있다.

### 12.2 280 GHz에서의 거리 민감도

280 GHz의 파장은

\[
\lambda=\frac{c}{f_c}\simeq1.071\ \mathrm{mm}
\]

이다. Monostatic echo phase는

\[
\theta_R=\frac{4\pi R}{\lambda}
\]

로 변한다. Constructive maximum에서 첫 null까지 필요한 거리 변화는

\[
\Delta R_{\mathrm{max\rightarrow null}}
=\frac{\lambda}{8}
\simeq0.134\ \mathrm{mm}
\]

에 불과하다. \(\cos^2\theta\) power pattern의 거리 주기는

\[
\Delta R_{\mathrm{power}}=\frac{\lambda}{4}\simeq0.268\ \mathrm{mm}
\]

이다. 따라서 sub-millimeter vibration, target 표면의 미세 움직임 또는 mechanical drift도 느린 fading을 만들 수 있다.

일정한 radial velocity \(v\)가 있으면 monostatic Doppler는

\[
f_D=\frac{2v}{\lambda}
\]

이며, 상대 위상이 CPI 동안 크게 변하면 coherent integration loss와 Doppler spreading이 발생한다. Phase noise가 coherent integration gain과 detection threshold에 영향을 준다는 점은 mmWave radar에서도 보고되어 있다.

### 12.3 단일 quadrature의 이상적 outage 확률

상대 위상이 장시간에 걸쳐 \([0,2\pi)\)에서 균일하다고 가정하고 phase-averaged SINR를 \(\bar\gamma\)라고 하면, cross-beat가 지배적인 단일 실수 채널의 순간 SINR는

\[
\gamma(\theta)=2\bar\gamma\cos^2\theta
\]

로 정규화할 수 있다. Threshold를 \(\gamma_{\mathrm{th}}\)라고 할 때 이상적인 outage 확률은

\[
P_{\mathrm{out}}
=\Pr[\gamma<\gamma_{\mathrm{th}}]
=\frac{2}{\pi}
\sin^{-1}\!\sqrt{
\frac{\gamma_{\mathrm{th}}}{2\bar\gamma}}
\]

이며 \(0<\gamma_{\mathrm{th}}<2\bar\gamma\) 범위에서 성립한다.

예를 들어 target cross-beat만 존재하는 이상화된 단일 quadrature에서는 다음과 같다.

| 평균 SINR margin | 이상적 outage 확률 |
|---:|---:|
| 0 dB | 50.0% |
| 3 dB | 약 33.3% |
| 10 dB | 약 14.4% |
| 20 dB | 약 4.5% |

실제 시스템에서는 echo self-beat, noise, frequency diversity와 시간 평균이 null에 floor를 제공하므로 이 표를 그대로 실제 outage로 사용해서는 안 된다. 그러나 phase-averaged SINR만으로 reliability를 판단하면 위험하다는 점은 분명하다.

### 12.4 CPI보다 느린 변화와 빠른 변화

- \(\theta(t)\)가 CPI보다 느리게 변하면 한 CPI 전체가 deep fade에 머물 수 있어 missed detection 또는 burst outage가 발생한다.
- CPI 안에서 빠르게 변하면 단순한 고정 null보다는 spectral broadening과 coherent integration loss가 발생한다.
- Doppler/phase를 정확히 추정하고 보상하면 coherent gain을 회복할 수 있지만, 단일 quadrature가 정확한 null에 놓이면 추정할 신호 자체가 부족하므로 diversity가 필요하다.

실제 NPZ capture는 768 ns에 불과하다. 이 구간에서는 6.75 ns ripple phase가 매우 안정적이었으나, Hz–kHz 수준의 target motion, vibration 또는 장기 carrier drift에 따른 outage를 이 파일 하나로 평가할 수는 없다.

## 13. Radar 관점의 방어 전략

### 13.1 최우선: quadrature 또는 phase diversity

두 직교 관측값을

\[
y_I=A\cos\theta,
\qquad
y_Q=A\sin\theta
\]

로 얻을 수 있으면

\[
y_I^2+y_Q^2=A^2
\]

가 되어 carrier phase null을 제거할 수 있다. 구현 방법은 다음과 같다.

- 90° hybrid와 두 detector를 이용한 실제 I/Q 수신
- SI reference phase를 0°/90°로 전환하여 두 pulse 또는 두 frame을 측정
- Photonic phase shifter 또는 서로 다른 reference delay를 이용한 phase diversity
- 여러 phase state를 순환하고 noncoherent power combining 수행

일반적인 quadrature Doppler radar에서도 I/Q 채널은 한 채널이 null일 때 다른 채널이 정보를 유지하도록 사용된다.

### 13.2 Frequency diversity와 subband combining

SI–echo 위상은 주파수에 따라 \(2\pi f\tau\)로 변하므로 wideband 전체가 동시에 null이 되지는 않는다. 다음 처리가 효과적이다.

- 대역을 여러 subband로 나누고 각 subband의 magnitude 또는 SINR를 추정
- 위상 보상 후 maximum-ratio combining
- Deep-fade subband의 weight를 낮추는 robust combining
- Carrier-frequency hopping 또는 두 개 이상의 RF carrier 사용
- Complex CFR를 추정한 뒤 SI-normalized CFR로 delay processing

단순히 실수 전압을 대역 전체에서 더하면 서로 다른 subband가 상쇄될 수 있으므로 power-domain 또는 phase-compensated combining이 필요하다.

### 13.3 Time, spatial 및 polarization diversity

- 여러 CPI를 noncoherent하게 누적하고 Doppler tracking 후 결합
- 서로 다른 antenna 또는 관측각의 range profile 결합
- Orthogonal polarization channel 사용
- Staggered PRI 또는 phase-coded repeated pilot 사용

한 경로가 null이어도 모든 diversity branch가 동시에 null일 가능성을 낮추는 것이 목적이다.

### 13.4 SI reference의 크기와 dynamic range 제어

SI는 homodyne gain을 제공하지만 무조건 클수록 좋은 것은 아니다.

- SI가 너무 약하면 cross-beat gain이 부족하다.
- SI가 너무 강하면 LNA/ZBD/IF amplifier/ADC saturation과 SI self-beat, SSBI 및 phase-noise skirt가 증가한다.
- Target-dependent cross term을 보존하면서 SI-only 성분을 제거해야 한다.

따라서 OMT isolation, analog attenuation 및 digital SIC를 함께 이용해 reference를 detector의 선형 범위 안에 유지해야 한다. Digital SIC는 SI-only self-beat를 제거할 수 있지만 target 정보를 포함한 SI–echo cross term까지 제거해서는 안 된다.

### 13.5 Outage-aware detection metric

논문 및 simulation에서는 평균 SINR뿐 아니라 다음 지표를 함께 제시하는 것이 바람직하다.

- Phase별 SINR CDF
- 1%, 5% 또는 10% percentile sensing SINR
- \(P_D\) at fixed \(P_{FA}\)
- Phase/motion에 대한 outage probability
- Coherent integration loss
- Multi-CPI detection persistence
- Detector saturation probability

## 14. 현재 simulation 반영 수준 감사

### 14.1 잘 반영된 부분

현재 `isac_gui.py`의 waveform simulation에는 다음 물리가 포함되어 있다.

1. SI와 echo가 동일한 송신 waveform에서 생성된다.
2. Echo에는 왕복 delay와 \(\exp(-j2\pi f_c\tau)\) carrier phase가 적용된다.
3. ZBD 입력에서

   \[
   |v_{\mathrm{SI}}+v_{\mathrm{echo}}+n|^2
   \]

   를 직접 계산하므로 SI self-beat, echo self-beat와 SI–echo cross-beat가 raw C2 waveform에 포함된다.
4. Free-running laser phase noise와 optional carrier-frequency wander가 송신 waveform에 포함되고, delayed echo와 SI 사이의 differential phase에도 반영된다.
5. Target cross term을 real/imaginary 두 직교 성분으로 분리하여 phase-averaged target band power를 계산한다.
6. Raw C2 spectrum과 range profile에는 실제 선택된 carrier phase의 constructive/destructive interference가 남아 있다.

따라서 **단일 simulation realization의 raw waveform에는 SI–echo interference가 구현되어 있다.**

### 14.2 제한적으로 반영되거나 빠진 부분

그러나 reliability와 outage 관점에서는 다음이 빠져 있다.

- Independent random initial target/scattering phase
- Target motion, Doppler와 micro-motion
- 시간에 따라 변하는 range와 RCS scintillation
- Multipath별 amplitude, delay와 phase
- 실제 측정된 ZBD/IF-chain 전달함수
- Calibrated carrier-wander 및 measured phase-noise spectrum
- Phase Monte Carlo와 sensing-SINR CDF
- \(P_D/P_{FA}\), CFAR 및 outage metric
- Detector/LNA/ADC saturation의 확률적 평가
- 실제 하드웨어 I/Q 또는 switched-phase diversity

특히 세 번째 탭의 Effective-RCS range 그래프와 distance sweep은 quadrature 두 성분의 평균

\[
\mathbb{E}_{\theta}
\left[(A\cos\theta+B\sin\theta)^2\right]
=\frac{A^2+B^2}{2}
\]

을 사용한다. 이것은 phase-independent mean envelope를 계산하는 데 적합하지만 단일 real ZBD channel의 deep fade와 outage를 제거한 optimistic metric이다.

### 14.3 현재 기본 설정에 대한 수치 점검

현재 waveform model을 280 GHz, \(R=1.0125\) m, 15 kHz laser linewidth 조건에서 noise 없이 frame별로 확인한 결과는 다음과 같다.

| Coherence | 10 MHz wander | Frame phase 표준편차 | 관찰 결과 |
|---|---:|---:|---|
| Self-coherent | Off | 0 rad | 완전히 고정된 constructive state |
| Free-running | Off | 0.015 rad | 거의 고정됨 |
| Self-coherent | On | 0.419 rad | 유의한 amplitude 변화 |
| Free-running | On | 0.420 rad | 유의한 amplitude 변화 |

15 kHz linewidth와 6.75 ns의 짧은 differential delay에서는 common-source phase noise가 대부분 상쇄되므로 자체적으로 큰 frame fading을 만들지 않았다. 10 MHz carrier wander를 켜면 약 1.48 rad의 frame phase range가 발생했지만, 이 값은 측정으로 calibration된 parameter가 아니라 GUI의 고정 가정이다.

또한 \(R=1.0125\) m는 280 GHz에서 carrier 왕복 phase가 정수 cycle에 해당해 simulation이 우연히 constructive state에서 시작한다. Random initial scattering phase가 없으므로 기본 결과가 favorable phase에 고정될 수 있다.

### 14.4 최종 판정

현재 simulation 반영 수준은 다음과 같이 요약된다.

| 평가 항목 | 반영 수준 |
|---|---|
| SI–echo cross-beat의 순간 waveform | 잘 반영 |
| 고정 delay에 따른 spectral ripple | 잘 반영 |
| Laser phase noise의 differential effect | 부분 반영 |
| 임의 carrier wander | 부분 반영, calibration 없음 |
| Phase-averaged sensing range | 잘 반영 |
| 단일 real-channel deep fade | Raw waveform에만 존재 |
| Time-varying target/micro-motion | 미반영 |
| Outage probability/Pd | 미반영 |
| Physical quadrature diversity | 미반영 |

즉, **평균 link budget과 phase-averaged range 분석에는 적합하지만 radar reliability 또는 outage를 주장하기에는 부족하다.**

## 15. 권장 simulation 확장

논문을 강화하려면 기존 평균 range 그래프를 유지하면서 별도의 `Phase/Outage Robustness` 분석을 추가하는 것이 좋다.

1. 각 Monte Carlo trial에서 \(\theta_0\sim\mathcal{U}(0,2\pi)\)를 생성한다.
2. \(R(t)=R_0+vt+x_{\mathrm{vib}}(t)\)로 Doppler와 vibration을 모델링한다.
3. Optional measured phase-noise/wander PSD를 적용한다.
4. Single-real, ideal-I/Q, two-phase switched receiver를 비교한다.
5. 각 방식에 대해 mean/5th-percentile SINR와 outage probability를 계산한다.
6. Fixed \(P_{FA}\)에서 \(P_D\)와 coherent integration loss를 표시한다.
7. Frequency-subband combining 유무를 비교한다.

권장 그래프는 다음과 같다.

- Sensing SINR CDF: single-real vs I/Q vs phase switching
- Outage probability vs Effective RCS
- Outage probability vs carrier wander 또는 vibration amplitude
- 5th-percentile sensing range vs Effective RCS
- Coherent integration loss vs target velocity/CPI

기존 Effective-RCS 그래프는 `ideal phase-averaged envelope`임을 명시하고, 별도의 percentile/outage 그래프를 reliability 결과로 제시하는 구성이 가장 명확하다.

## 16. Ideal 대비 effective processing gain

이상적인 coherent processing gain은

\[
G_{p,\mathrm{ideal}}=BT_p
\]

이며, 현재 조건 $B=15\,\mathrm{GHz}$, $N_p=1024$, $T_p=N_p/R_s$, $R_s=15\,\mathrm{GBd}$에서는 $30.10\,\mathrm{dB}$이다. 이는 모든 pilot sample이 완전한 시간·주파수·위상 정렬 상태로 coherent하게 합쳐진다는 상한선이므로 실제 range 계산에 그대로 쓰는 것은 낙관적이다.

저장된 기본 C2 NPZ에서는 1024 active subcarrier 중 CFR mask를 통과한 bin이 908개이고, 저장된 weight에 대한 equivalent independent-bin count는

\[
N_{\mathrm{eff}}=\frac{(\sum_k w_k)^2}{\sum_k w_k^2}=526.5,
\qquad 10\log_{10}N_{\mathrm{eff}}=27.21\,\mathrm{dB}
\]

이다. 이 값은 masking과 nonuniform weighting을 반영한 데이터 기반 상한이다. 따라서 기준값은 이보다 1.21 dB 낮은 $G_{p,\mathrm{eff}}=26.0\,\mathrm{dB}$로 둔다. 이는 이상적 gain에 대해 $4.10\,\mathrm{dB}$의 aggregate processing loss를 허용한다. 대응하는 coherent efficiency는

\[
\eta_p=\frac{G_{p,\mathrm{eff}}}{G_{p,\mathrm{ideal}}}
=10^{(26.0-30.10)/10}=0.389
\]

이다. CFR mask와 weight가 설명하는 손실은 $N_{\mathrm{eff}}$에 이미 포함되어 있으므로 window/bin 손실을 다시 빼지 않는다. 27.21 dB와 26.0 dB 사이의 1.21 dB margin만 synchronization/reference mismatch, 잔여 phase error 및 구현 손실로 둔다. 단일 NPZ만으로 이 margin의 각 원인을 독립 식별할 수 없으므로 26.0 dB는 직접 측정된 절대값이 아니라 assumed baseline으로 명시한다. 기존 21.9 dB는 profile-domain PSLR 예시에서 유래한 값이어서 processing gain으로 재사용하지 않는다.

| 항목 | 권장값 | 해석 |
|---|---:|---|
| Ideal upper bound | 30.10 dB | $BT_p$, 완전 coherent 상한 |
| Weighted-bin bound | 27.21 dB | 저장된 CFR weight의 $N_{\mathrm{eff}}=526.5$ |
| Assumed effective baseline | 26.0 dB | 모든 sensing SINR 및 ISAC-range 계산에 적용 |
| Aggregate loss | 4.10 dB | ideal 대비 practical loss |
| Coherent efficiency | 0.389 | ideal linear gain의 38.9% |
| Sensitivity interval | 24--28 dB | 결과의 processing-gain 불확실성 범위 |

Exact SI-assisted sensing은 \(R^{-4}\)와 \(R^{-8}\) 항의 합이므로 processing gain에 대한 range 민감도는 cross-beat 지배 시 \(G_p^{1/4}\), self-beat 지배 시 \(G_p^{1/8}\) 사이에 있다. 따라서 26.0 dB의 range는 ideal 30.10 dB 결과의

\[
10^{(26.0-30.10)/40}=0.790
\]

배 이상이고, self-beat limit의 \(10^{(26.0-30.10)/80}=0.889\)배 이하이다. Without-SI는 후자의 0.889가 정확한 비율이다. Communication range에는 sensing processing gain이 적용되지 않는다.

GUI에서는 ideal gain을 read-only 상한으로 표시하고, effective gain은 편집 가능하게 둔다. 입력값이 $BT_p$를 넘으면 계산에는 ideal bound가 적용되어 구현 효율이 1을 초과하지 않는다. `Redraw`를 누르면 cached target-only sensing SINR와 Effective-RCS 기반 sensing/ISAC range에 새 값이 반영된다.

## 17. 최종 물리·수학 모델 감사

세 번째 탭의 최종 계산 경로는 다음과 같이 정리하였다.

| Branch | 구현식 | 거리 법칙 | Effective-RCS 법칙 |
|---|---|---:|---:|
| Communication | \((1-\rho)m^2P_tG_c/(NR^2)\) | \(R^{-2}\) | RCS sweep과 무관 |
| Sensing with SI | \(2\rho m^2G_{p,\mathrm{eff}}[P_{\mathrm{SI}}P_{\mathrm{ec}}+P_{\mathrm{ec}}^2]/(P_0N)\) | \(R^{-4}+R^{-8}\) | \(\sigma_{\mathrm{eff}}+\sigma_{\mathrm{eff}}^2\) |
| Sensing without SI | \(2\rho m^2G_{p,\mathrm{eff}}P_{\mathrm{ec}}^2/(P_0N)\) | \(R^{-8}\) | \(\sigma_{\mathrm{eff}}^2\) |

여기서 \(P_0=1\) mW는 코드가 모든 power를 mW 숫자로 계산할 때 필요한 명시적 normalization reference이다. 따라서 range scaling은 다음과 같다.

- \(R_{\mathrm{comm}}\propto[(1-\rho)P_t]^{1/2}\)
- \(R_{\mathrm{sens,SI}}\)는 \(C_4/R^4+C_8/R^8=\gamma_{\mathrm{th}}\)의 positive root
- \(R_{\mathrm{sens,noSI}}\propto[\rho G_{p,\mathrm{eff}}P_t^2\sigma_{\mathrm{eff}}^2]^{1/8}\)

두 sensing range 모두 \(\sigma_{\mathrm{eff}}^{1/4}\)에 정확히 비례한다. Exact with-SI range의 processing-gain 및 \(\rho\) 지수는 지배 항에 따라 \(1/8\)과 \(1/4\) 사이이며, without-SI는 \(1/8\)이다. Communication range가 Effective-RCS sweep에서 일정한 것은 effective RCS를 \(\Gamma\)로 역산하지 않고, 통신 load mismatch를 고정하기 때문이다.

감사 과정에서 수정한 오류는 다음과 같다.

- field product \(\alpha\beta\propto R^{-2}\)를 sensing SINR 자체로 사용하던 식을 power product \(P_{\mathrm{SI}}P_{\mathrm{ec}}\propto R^{-4}\)로 수정
- with-SI 식에서 echo self-beat를 누락해 낮은 TX power에서 without-SI range보다 작아지던 오류를 수정하고, $C_4/R^4+C_8/R^8$의 positive root로 교체
- ideal gain으로 계산한 뒤 effective-gain fourth-root correction을 다시 곱하던 이중 정규화 제거
- without-SI range를 with-SI limiting point에서 간접 추론하던 경로를 \(P_{\mathrm{ec}}^2\) 식의 직접 eighth-root 해로 교체
- raw C2 band power를 sensing SINR로 변환하던 fallback 제거
- target-only C2 power에 noise와 effective processing gain을 각각 한 번만 적용
- 동일 거리의 manual C2 band-power가 sensing-SINR 측정 record 전체를 제거하던 merge 오류 수정
- 실제 기본 C2 measurement NPZ 경로를 data/captures/range_1100mm으로 수정
- 사용되지 않던 legacy range-anchor, exploratory SDINR/rho GUI, 중복 handler와 숨은 중복 파라미터 제거

기본 C2 range-profile 측정값은 1.1 m에서 약 20.56 dB이며, absolute sensing-SINR anchor로 유지된다. 1.0/1.2 m의 raw SI-on band-power는 공통 background를 선형 전력에서 제거한 뒤 이 anchor에 대한 상대 변화로 환산하여 약 23.45/17.90 dB의 band-power-based estimate로 표시한다. Raw C2 plot에는 noise floor로 평탄해질 수 있는 raw total과 계속 감소하는 target/echo-only power를 함께 표시한다.

## 18. 최종 결론

1. 실제 C2 데이터에는 1.0125 m 왕복 지연과 정확히 일치하는 148.148 MHz ripple이 안정적으로 존재한다.
2. 이는 SI–echo coherent interference가 C2 frequency selectivity의 주요 원인임을 강하게 지지한다.
3. 고정 시스템에서는 이 간섭이 시간적으로 안정될 수 있지만, 280 GHz에서는 약 0.134 mm의 거리 변화만으로 maximum에서 null로 이동할 수 있다.
4. 단일 real homodyne/ZBD channel은 phase null로 인해 missed detection과 burst outage를 겪을 수 있다.
5. 가장 직접적인 방어는 실제 I/Q 또는 switched-phase diversity이며, frequency/time/spatial diversity와 outage-aware processing을 함께 사용해야 한다.
6. 현재 simulation은 raw waveform의 간섭은 구현하지만 phase-averaged 성능 그래프가 deep fade를 숨기므로 reliability simulation을 추가해야 한다.

## 19. 참고 자료

- M. T. Abuelma'atti, “Output spectrum computation for a square-law diode detector,” *IEEE Transactions on Instrumentation and Measurement*, 1989. <https://doi.org/10.1109/19.46407>
- Virginia Diodes, *Zero-Bias Detector Operational Manual*. <https://vadiodes.com/wp-content/uploads/2009/10/VDI-734_ZBD_Product_Manual.pdf>
- Rohde & Schwarz, *RF Fundamentals: Standing Waves, Uncertainty, Mismatch and VNA*. <https://cdn.rohde-schwarz.com/ymkt/na/content/RF_fundamentals_seminar_materials/3_RF_Fun_-_Standing_Waves_Unc-Mismatch_VNA.pdf>
- Keysight Technologies, *Time Domain Analysis Using a Network Analyzer*. <https://www.keysight.com/in/en/assets/7018-01451/application-notes/5989-5723.pdf>
- C. Levy, M. Pinchas, and Y. Pinhasi, “Coherent Integration Loss Due to Nonstationary Phase Noise in High-Resolution Millimeter-Wave Radars,” *Remote Sensing*, 2021. <https://doi.org/10.3390/rs13091755>
- K. Siddiq, M. K. Hobden, S. R. Pennock, and R. J. Watson, “Phase Noise in FMCW Radar Systems,” *IEEE Transactions on Aerospace and Electronic Systems*, 2019. <https://doi.org/10.1109/TAES.2018.2847999>
- C. Li et al., “Short-Range Noncontact Sensors for Healthcare and Other Emerging Applications: A Review,” null-point and quadrature radar discussion. <https://pmc.ncbi.nlm.nih.gov/articles/PMC5017335/>
