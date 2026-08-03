# Current Paper System Model

> 기준일: 2026-08-03
> 목적: 현재 논의가 반영된 논문용 시스템 및 수학 모델의 단일 기준 문서
> 적용 범위: self-interference-assisted monostatic full-duplex THz ISAC, ZBD square-law receiver, full-waveform sensing

이 문서는 `concepts` 폴더의 과거 메모를 대체하는 현재 기준이다. 논문 원고를 수정할 때는 이 문서의 full-waveform 모델과 파라미터를 우선한다.

현재 구현과 metric/save key의 대응은 [CURRENT_CODE_IMPLEMENTATION_GUIDE.md](CURRENT_CODE_IMPLEMENTATION_GUIDE.md)를 따른다.

## 1. 시스템 개요

시스템은 하나의 알려진 communication waveform을 통신과 monostatic sensing에 동시에 사용한다.

1. 광 송신부가 data-bearing optical signal과 optical LO를 UTC-PD에서 photomixing한다.
2. UTC-PD 출력은 필요하면 선형 THz PA로 증폭되며, 최종 THz 출력은 duplexer와 송신 안테나를 통해 방사된다.
3. 통신 수신기 C1은 one-way THz link를 수신한다.
4. sensing 수신기 C2는 동일 장치에서 duplexer leakage인 self-interference(SI)와 target echo를 함께 수신한다.
5. C2의 SI는 제거 대상인 동시에 echo와 beating하여 square-law detector의 homodyne reference 역할을 한다.
6. ZBD 출력은 IF/baseband amplifier와 cable을 거쳐 DSO에서 획득된다.

핵심 주장은 SI와 echo의 cross-beat가 echo-only self-beat보다 유리한 거리 법칙을 만든다는 것이다.

| 성분 | RF power law | ZBD desired-output power law |
|---|---:|---:|
| One-way communication | $P_{\rm rx}\propto R^{-2}$ | $P_{\rm rx}^2\propto R^{-4}$ |
| Echo | $P_{\rm ec}\propto R^{-4}$ | $P_{\rm ec}^2\propto R^{-8}$ |
| SI-echo cross-beat | $P_{\rm SI}P_{\rm ec}$ | $R^{-4}$ |

따라서 SI-assisted sensing은 weak-echo 조건에서 sensing SINR의 거리 의존성을 $R^{-8}$에서 $R^{-4}$로 완화한다.

## 2. 기본 송신 신호

현재 기본 모델에서는 별도의 sensing pilot에 전력을 분할하지 않는다. 평균 전력이 1인 알려진 communication waveform $d(t)$를 그대로 sensing reference로 사용한다.

$$
x(t)=\sqrt{P_c}\,[1+m d(t)]e^{j2\pi f_ct},
\qquad \mathbb E[|d(t)|^2]=1.
$$

$m^2$는 carrier-to-signal power ratio의 역수로 둔다.

$$
m^2=10^{-\mathrm{CSPR}/10}.
$$

UTC-PD total output을 $P_{\rm UTC}$, PA gain을 $G_{\rm PA}$라 하면 final TX reference-plane power는

$$
P_{t,\rm tot}=\begin{cases}
P_{\rm UTC}, & \text{PA off},\\
P_{\rm UTC}G_{\rm PA}, & \text{PA on}.
\end{cases}
$$

GUI simulation은 두 경우를 명시적으로 분리한다. 이론 그림의 $P_{t,\rm tot}$는 PA 유무와 무관하게 final TX reference plane의 carrier와 sideband를 포함한 total THz power다. 이론식의 carrier power는

$$
P_c=\frac{P_{t,\rm tot}}{1+m^2}
$$

로 변환한다. CSPR이 13 dB이면 $m^2=0.05012$이고 carrier fraction은 0.95227이다.

### 2.1 Full-waveform 원칙

- 통신 데이터 $d(t)$는 monostatic transmitter에 알려져 있다.
- sensing은 전체 transmit spectrum $D_k$를 사용한다.
- 기본 모델에는 $\rho$ 또는 $(1-\rho)$가 없다.
- $\rho$는 과거 pilot-only 구현의 비교 및 processing-gain 측정용 legacy parameter로만 남긴다.

## 3. 공통 RF 기준면

Closed-form의 모든 RF power는 **LNA input** 기준이다.

### 3.1 Self-interference

Net SI isolation $I_{\rm SI}$는 final TX reference plane에서 LNA input까지의 port-to-port isolation이다.

$$
P_{\rm SI}=P_c10^{-I_{\rm SI}/10}.
$$

Net isolation에 duplexer loss를 다시 더하면 중복이다.

### 3.2 Monostatic echo

$L_{\rm dup}=10^{IL_{\rm dup}/10}$를 one-pass power loss라 하면

$$
P_{\rm ec}(R)=
\frac{P_cG_tG_r\lambda^2\sigma_{\rm eff}}
{(4\pi)^3R^4L_{\rm dup}^2}.
$$

Echo는 송신과 수신에서 duplexer를 각각 통과하므로 $2IL_{\rm dup}$ dB가 적용된다.

### 3.3 Communication link

$$
P_{\rm rx}(R)=
\frac{P_cG_tG_c\lambda^2}
{(4\pi)^2R^2L_{\rm dup}^2}.
$$

여기서 $G_c$는 remote communication antenna gain이다.

## 4. Effective RCS

$\sigma_{\rm eff}$는 논문 그림에서 직접 사용하는 scenario-level scalar다. 다음 효과를 모두 포함할 수 있다.

- horn aperture의 structural RCS
- antenna-mode reradiation
- polarization mismatch
- target alignment와 aspect
- fixture와 주변 구조의 결맞음 효과

이론 그림은 이를 하나의 direct effective RCS로 사용한다. Structural RCS와 antenna-mode RCS를 비결맞음 전력합으로 분해하는 것은 근사이며, 측정 없이 두 성분을 유일하게 분리할 수 없다.

Range detection, calibrated TX power, complete receiver calibration, processing gain을 알고 있다면 다음 monostatic radar equation을 역산하여 $\sigma_{\rm eff}$를 추정할 수 있다.

$$
\sigma_{\rm eff}=
\frac{P_{\rm ec}(4\pi)^3R^4L_{\rm dup}^2}
{P_cG_tG_r\lambda^2}.
$$

단, ZBD와 IF/DSO를 포함한 complete input-referred calibration 없이는 DSO band power를 $P_{\rm ec}$로 직접 해석할 수 없다.

## 5. ZBD square-law signal model

LNA input의 sensing RF envelope를

$$
r(t)=r_{\rm SI}(t)+r_{\rm ec}(t)+n(t)
$$

로 두면 ZBD는 $|r(t)|^2$에 비례하여 응답한다. Target-dependent desired terms은

$$
|r_{\rm SI}+r_{\rm ec}|^2
=|r_{\rm SI}|^2+|r_{\rm ec}|^2
+2\Re\{r_{\rm SI}r_{\rm ec}^*\}
$$

에서 얻는다.

- $|r_{\rm SI}|^2$: range-zero 부근의 SI self-beat, target desired term이 아님
- $|r_{\rm ec}|^2$: echo self-beat, $P_{\rm ec}^2$
- $2\Re\{r_{\rm SI}r_{\rm ec}^*\}$: SI-echo cross-beat, $P_{\rm SI}P_{\rm ec}$

Single carrier phase에서는 cross-beat가 보강 또는 상쇄될 수 있다. 이론 range law와 Fig. 2/3은 quadrature phase average를 사용하여 nonnegative target power envelope를 계산한다.

## 6. Detector-output noise model

### 6.1 RF thermal noise

LNA input의 integrated RF noise power는

$$
N=kT_0F_{\rm LNA}B \quad [\mathrm{mW}]
$$

이다. IF amplifier는 ZBD 뒤에 있으므로 RF Friis cascade의 $F_{\rm LNA}$에 포함하지 않는다.

### 6.2 Fixed detector floor

Detector-output power-product 단위의 고정 바닥은

$$
N_{d,0}=
\eta_{nn}N^2+
\frac{\mathrm{NEP}_{\rm ZBD}^2B}{G_{\rm LNA}^2}
+N_{\rm post,eq}
\quad [\mathrm{mW}^2].
$$

- $\eta_{nn}N^2$: in-band noise-noise beat
- $\mathrm{NEP}_{\rm ZBD}^2B/G_{\rm LNA}^2$: LNA-input-referred ZBD floor
- $N_{\rm post,eq}$: IF amplifier와 DSO noise의 선택적 equivalent floor

이론-derived 방식과 measurement-calibrated 방식을 섞으면 안 된다.

- 이론-derived: NEP, bandwidth, LNA gain으로 $N_{d,0}$를 계산
- calibrated: 측정한 $N_{d,0}$를 직접 입력하고 NEP 항을 다시 더하지 않음

현재 이론 기본값 $B=20$ GHz, $F_{\rm LNA}=8$ dB, $G_{\rm LNA}=13$ dB, NEP $=5$ pW/$\sqrt{\rm Hz}$에서는 $N_{d,0}\simeq-89.01$ dB(mW$^2$)이다.

### 6.3 Signal-dependent noise

Sensing denominator는

$$
D=N_{d,0}+2N(P_{\rm SI}+P_{\rm ec})
+\kappa m^4P_{\rm SI}^2.
$$

- $2NP$: carrier-noise beat
- $\kappa m^4P_{\rm SI}^2$: in-band residual SSBI approximation
- $\kappa$: waveform, modulation, filter와 branch에 의존하는 effective in-band fraction

현재 nominal $\kappa=0.06$은 conservative parameter지만 operating point에서 항상 dominant하다는 뜻은 아니다.

RF thermal noise $N$의 단위는 mW이고 detector-output floor $N_{d,0}$의 단위는 mW$^2$이다. 따라서 예를 들어 $N=-63$ dBm과 $N_{d,0}=-89$ dB(mW$^2$)를 숫자만 비교하여 detector floor가 thermal noise보다 작다고 해석하면 안 된다. 두 항의 상대 중요도는 같은 detector-output 단위로 변환한 $N_{d,0}$와 $2NP$를 비교해야 한다.

## 7. Full-waveform MMSE sensing

Known transmit spectrum을 이용한 regularized CFR estimator는

$$
\widehat H_k=
\frac{Y_kD_k^*}{|D_k|^2+\varepsilon}.
$$

Occupied-bin 평균 $|D_k|^2$를 1로 정규화하고

$$
w_k=\frac{|D_k|^2}{|D_k|^2+\varepsilon}
$$

라 하면 coherent waveform efficiency는

$$
\eta_d(\varepsilon)=
\frac{1}{N}
\frac{\left(\sum_kw_k\right)^2}
{\sum_kw_k^2/|D_k|^2}.
$$

$\eta_d$는 자유 calibration factor가 아니라 waveform realization과 $\varepsilon$로 계산되는 값이다.

Nominal 32-QAM, $N=1024$, $\varepsilon=0.001$에서는

| Waveform | $10\log_{10}\eta_d$ |
|---|---:|
| OFDM | 약 $-3.45$ dB |
| DFT-s-OFDM | 약 $-7.27$ dB |

DFT-s-OFDM은 DFT spreading 후 주파수 표본에 deep null이 생길 수 있어 MMSE 역변환 효율이 낮다. 이는 PAPR 이점과 sensing inversion stability 사이의 waveform-design trade-off다.

## 8. Processing gain 정의

$G_p$는 waveform utilization 이전의 coherent time-bandwidth processing gain이다.

$$
G_p\le BT_{\rm obs}.
$$

Full-waveform의 net sensing gain은

$$
G_{\rm net}=\eta_dG_p,
$$

또는 dB 단위에서

$$
G_{\rm net,dB}=G_{p,\rm dB}+10\log_{10}\eta_d.
$$

Nominal $G_p=30.10$ dB와 $\eta_d=-7.27$ dB이면 $G_{\rm net}=22.83$ dB다. End-to-end measured gain을 $G_p$ 입력에 그대로 넣고 $\eta_d$를 다시 곱하면 이중 계상이다.

## 9. Sensing SINR

현재 논문 기본식은

$$
\boxed{
\gamma_{\rm sens}(R)=
\eta_dG_p
\frac{2m^2\left(P_{\rm SI}P_{\rm ec}+P_{\rm ec}^2\right)}
{N_{d,0}+2N(P_{\rm SI}+P_{\rm ec})
+\kappa m^4P_{\rm SI}^2}
}.
$$

SI가 없으면

$$
\boxed{
\gamma_{\rm sens}^{\rm no\ SI}(R)=
\eta_dG_p
\frac{2m^2P_{\rm ec}^2}
{N_{d,0}+2NP_{\rm ec}}
}.
$$

Weak echo 조건에서

- with SI: $\gamma_{\rm sens}\propto P_{\rm ec}\propto R^{-4}$
- without SI: $\gamma_{\rm sens}\propto P_{\rm ec}^2\propto R^{-8}$

이다.

## 10. Communication SINR

Full-waveform communication branch는 별도 sensing power allocation을 하지 않는다.

$$
\boxed{
\gamma_{\rm comm}(R)=
\frac{2m^2P_{\rm rx}^2}
{N_{d,0}+2NP_{\rm rx}+\kappa m^4P_{\rm rx}^2}
}.
$$

거리 및 noise regime별 극한은 다음과 같다.

- fixed-floor limited: $\gamma_{\rm comm}\propto R^{-4}$
- carrier-noise limited: $\gamma_{\rm comm}\propto R^{-2}$
- SSBI limited: $\gamma_{\rm comm}\rightarrow2/(\kappa m^2)$

통신 threshold $\gamma_c$에서 필요한 received carrier power는

$$
A_c=2m^2-\gamma_c\kappa m^4,
$$

$$
P_{\rm req}=
\frac{\gamma_cN+
\sqrt{(\gamma_cN)^2+A_c\gamma_cN_{d,0}}}
{A_c},
$$

$$
R_{\max}^{\rm comm}=
\sqrt{\frac{C_{\rm comm}}{P_{\rm req}}},
\qquad P_{\rm rx}=\frac{C_{\rm comm}}{R^2}.
$$

$A_c\le0$이면 SSBI ceiling이 threshold보다 낮다.

## 11. Maximum sensing and ISAC range

$P_{\rm ec}=C/R^4$, $u=R^4$, $K=2m^2\eta_dG_p$로 두면 sensing threshold $\gamma_{\rm th}$는

$$
au^2+bu+c=0
$$

으로 정리된다.

$$
a=\gamma_{\rm th}
\left(N_{d,0}+2NP_{\rm SI}+\kappa m^4P_{\rm SI}^2\right),
$$

$$
b=C\left(2\gamma_{\rm th}N-KP_{\rm SI}\right),
\qquad c=-KC^2.
$$

양의 근 $u_+$에 대해

$$
R_{\max}^{\rm sens}=u_+^{1/4}.
$$

Joint ISAC range는

$$
\boxed{
R_{\max}^{\rm ISAC}=
\min\left(R_{\max}^{\rm comm},R_{\max}^{\rm sens}\right)
}.
$$

두 sensing branch 모두 $R_{\max}\propto\sigma_{\rm eff}^{1/4}$가 된다. No-SI branch도 $P_{\rm ec}^2\propto\sigma^2R^{-8}$이므로 같은 fourth-root RCS scaling을 갖는다.

## 12. 논문 그림 해석

### 12.1 ISAC range versus effective RCS

Fig. 2는 propagation 및 square-law scaling을 보이기 위한 ideal closed-form bound로 두며 $\eta_d=1$을 사용한다. AWG/DSO quantization과 measured waveform inversion loss는 포함하지 않는다.

그림에는 다음 네 곡선을 사용한다.

- $R_{\max}^{\rm comm}$
- $R_{\max}^{\rm sens}$ with SI
- $R_{\max}^{\rm sens}$ without SI
- $R_{\max}^{\rm ISAC}$ with SI

Full-waveform 기본 모델에서는 $\rho=0.2/0.8$ 두 패널이 필요 없다. Communication range가 평탄하게 joint range를 제한하고, 매우 작은 RCS에서 sensing bound가 joint range를 제한하는 구조를 보여주는 단일 그림이 적절하다. 그 평탄값은 $P_{t,\rm tot}$를 비롯한 nominal parameter에 따라 달라지므로 그림에 사용한 TX reference-plane power를 반드시 함께 명시한다.

### 12.2 Sensing SINR versus SI power

고정 range $R_0$와 고정 echo power에서 SI power만 sweep한다.

Fig. 3도 ideal processing을 가정하여 $\eta_d=1$로 둔다. 따라서 이 곡선은 first-tab waveform simulation이나 measured SINR와 직접 일치시키는 calibration curve가 아니다.

1. 매우 낮은 SI: echo self-beat 때문에 평탄
2. Cross-beat와 fixed floor 지배: 약 $+1$ dB/dB
3. Carrier-noise beat 지배: numerator와 denominator가 모두 $P_{\rm SI}$에 비례하여 포화
4. SSBI 지배: denominator가 $P_{\rm SI}^2$에 비례하여 감소

이 그림의 x축은 LNA input의 SI carrier power다. $P_{t,\rm tot}=0$ dBm, CSPR 13 dB, net isolation 25 dB이면 carrier SI는 정확히 $-25$ dBm이 아니라 $-25.21$ dBm이다. 이는 total power에서 carrier fraction $1/(1+m^2)$을 한 번 적용하기 때문이다. LNA $P_{1\rm dB}$는 식의 유효 범위 경계일 뿐이며 현재 모델은 compression 이후를 예측하지 않는다.

PA가 0 dBm까지 선형이라는 가정 아래 이론식은 증가한 echo, communication power와 SI power, carrier-noise beat 및 SSBI를 반영한다. 다만 PA AM-AM/AM-PM, added noise/phase noise, spectral regrowth, waveform peak/PAPR, duplexer power dependence, LNA/ZBD compression 및 DSO clipping은 포함하지 않는다. 특히 평균 SI가 약 $-25.21$ dBm이면 $P_{1\rm dB}=-20$ dBm 대비 평균 여유가 약 5.2 dB뿐이므로 high-PAPR waveform의 peak linearity는 별도로 검증해야 한다.

## 13. 기준면별 SINR 구분

세 metric을 같은 값으로 해석하면 안 된다.

| Metric | 기준면 | Post-detector cable loss 영향 |
|---|---|---|
| ZBD-output ideal SINR | Sec. II detector-output power-product | 없음 |
| DSO-input practical SINR | IF chain과 DSO noise 포함 | 있음 |
| CFR target/floor | 실제 waveform range profile | 있음 |

Flat scalar voltage gain $a$만 있다면

$$
\frac{|a|^2S_d}{|a|^2N_d}=\frac{S_d}{N_d}
$$

이므로 cable loss는 ideal detector-output SINR을 바꾸지 않는다. DSO 기준에서는

$$
\gamma_{\rm DSO}=
\frac{|a|^2S_d}{|a|^2N_d+N_{\rm post}+N_{\rm DSO}}
$$

이므로 후단 고정 잡음 때문에 practical SINR이 저하될 수 있다. Frequency-selective cable response는 CFR ripple과 sidelobe에도 영향을 준다.

## 14. SI-referenced CFR의 범위

Single-capture scalar normalization

$$
H(f)/\overline H_{\rm SI}-1
$$

은 common scalar gain과 phase만 제거한다. Frequency-dependent transfer function $A(f)$와 group delay를 완전히 제거하지 못한다.

논문에서 frequency-selective chain calibration을 주장하려면 다음 중 하나가 필요하다.

- Occupied band에서 $A(f)$가 충분히 flat하다는 측정
- Target-off absorber로 얻은 $H_{\rm SI}(f)$와 pointwise ratio
- 별도 through/S-parameter calibration

Absolute range와 신뢰도 높은 CFR에는 target-off SI-only reference가 권장된다.

## 15. Nominal 이론 파라미터

| Parameter | Symbol | Nominal value |
|---|---|---:|
| RF carrier | $f_c$ | 280 GHz |
| UTC-PD THz output | $P_{\rm UTC}$ | $-10$ dBm |
| THz PA state/gain | -- | off / 10 dB when enabled |
| Final TX power, PA off/on | $P_{t,\rm tot}$ | $-10/0$ dBm |
| CSPR | CSPR | 13 dB |
| TX/RX antenna gain | $G_t,G_r$ | 33 dBi |
| Physical target horn gain | $G_{\rm horn}$ | 25 dBi |
| Target aperture diameter | $D_{\rm horn}$ | 17 mm |
| duplexer insertion loss | $IL_{\rm dup}$ | 2 dB/pass |
| Net SI isolation | $I_{\rm SI}$ | 25 dB |
| Effective RCS | $\sigma_{\rm eff}$ | $-8$ dBsm |
| Symbol/noise bandwidth | $B$ | 20 GHz |
| LNA gain/NF | $G_{\rm LNA},NF$ | 13/8 dB |
| ZBD NEP | NEP | 5 pW/$\sqrt{\rm Hz}$ |
| In-band SSBI fraction | $\kappa$ | 0.06 |
| MMSE regularization | $\varepsilon$ | 0.001 |
| Coherent gain before utilization | $G_p$ | 30.10 dB |
| DFT-s-OFDM utilization | $\eta_d$ | $-7.27$ dB |
| Communication threshold | $\gamma_c$ | 15.75 dB |
| Sensing threshold | $\gamma_{\rm th}$ | 13.20 dB |

Nominal 수치는 이론 그림의 일관된 예시이며 측정 calibration을 대신하지 않는다.

시스템의 33-dBi gain은 안테나와 두 렌즈를 포함한 link gain이고, target은 bare 25-dBi corrugated horn이다. Fig. 2/3은 target을 direct $\sigma_{\rm eff}=-8$ dBsm으로 사용하므로 target horn gain을 RCS에 다시 곱하지 않는다. `Coupled antenna` 모델을 선택할 때만 25-dBi target gain이 antenna-mode RCS 계산에 별도로 사용된다.

## 16. Legacy pilot-only 모델

Pilot-only 비교가 필요한 경우에만

$$
s(t)=\sqrt\rho p(t)+\sqrt{1-\rho}d(t)
$$

를 사용한다.

- sensing utilization: $\eta_d\rightarrow\rho$
- communication data fraction: $1\rightarrow1-\rho$
- measured coherent gain: $G_p=\mathrm{SINR}_{post}-\mathrm{SINR}_{pre}-10\log_{10}\rho$

이 모델은 현재 논문의 기본 방향이 아니며 appendix 또는 implementation comparison으로만 사용하는 것이 적절하다.

## 17. 논문 확정 전 필수 결정

1. 논문 원고에서 기본 $\rho$ 모델을 제거하고 full-waveform MMSE 식으로 변경한다.
2. $N_{d,0}$를 NEP-derived $-89.01$ dB(mW$^2$)로 둘지 calibrated value로 둘지 확정한다.
3. $\kappa_{\rm comm}$와 $\kappa_{\rm sens}$를 공통값으로 둘 근거를 제시하거나 분리한다.
4. Target-off SI-only CFR로 $A(f)$의 flatness 또는 pointwise calibration을 검증한다.
5. IF chain의 실제 순서가 `ZBD -> IF amp -> cable -> DSO`인지 `ZBD -> cable -> IF amp -> DSO`인지 명시한다.
6. LNA/ZBD compression, DSO ENOB와 clipping은 model limitation으로 명시한다.
7. Effective RCS는 direct scenario parameter인지 측정 역산값인지 표에 출처를 표시한다.

## 18. 논문에서 유지할 핵심 메시지

> A known communication waveform is reused as the monostatic sensing waveform without explicit pilot-power partitioning. Controlled self-interference acts as a square-law homodyne reference, producing an SI-echo cross-beat term proportional to $P_{\rm SI}P_{\rm ec}$. In the weak-echo regime, this changes the sensing distance law from the echo-only $R^{-8}$ dependence to an SI-assisted $R^{-4}$ dependence, while the joint ISAC range remains the minimum of the communication and sensing bounds.
