# System Model Validation 계산 및 물리 검증

이 문서는 `isac_gui.py`의 세 번째 탭인 **System Model Validation**에서
사용하는 계산, 기준면, 거리 법칙, processing gain, 임계값 및 논문용 그림
생성 경로를 정리한다. 기준 코드는 2026-07-23 점검본이다.

## 1. 검증 범위

세 번째 탭의 네 그림을 대상으로 한다.

1. Communication/Sensing SINR versus range
2. EVM versus symbol rate
3. Sensing SINR versus SI power
4. ISAC range versus effective RCS

여기서 range \(R\)는 레이더 전파 경로 길이 \(2R\)가 아니라 **표적까지의
one-way target range**이다. C2 delay에는 자동으로 \(\tau=2R/c\)가 적용된다.

### 1.1 이번 감사에서 수정한 오류

1. LNA waveform에 이미 포함된 thermal/LNA noise를 IF amplifier에서
   \(kTBF G\)로 다시 더하던 중복을 제거했다. IF stage에는
   \(kTB(F_{\mathrm{IF}}-1)G/L_{\mathrm{cable}}\)만 추가한다.
2. real IF noise voltage에 complex-noise용 \(1/2\) factor를 사용하던 오류를
   수정했다.
3. C1 RF power의 \(R^{-2}\) 법칙을 ZBD output-power SINR에 그대로 쓰던
   reference-plane 오류를 수정했다. output-noise SNR은 \(R^{-4}\)이다.
4. EVM-equivalent SINR과 physical noise SNR을 분리하고
   \(1/\mathrm{SINR}=1/\mathrm{SNR}+1/\mathrm{SIR}\)로 결합해 residual을
   noise와 중복 합산하지 않도록 했다.
5. SI-on/off가 같은 input NF를 사용하더라도 square-law 이후 noise가 달라지는
   점을 반영해 detector-output noise reference를 각각 저장한다.
6. 기본 JSON의 direct effective RCS \(-4.28\) dBsm을 시작 시
   \(-19.10\) dBsm coupled model로 덮어쓰던 코드를 제거했다.
7. 현재 simulation과 일치하는 detector reference가 없으면 legacy 기본
   숫자로 논문 곡선을 그리지 않고 NaN으로 무효화한다.
8. GUI 초기 화면은
   `isac_validation_reference_20260723.json`의 재현 가능한 physical-simulation
   reference를 사용한다. 저장된 config fingerprint가 현재 `SimConfig`와
   완전히 일치할 때만 로드하며, 불일치하면 `Range Sweep`을 요구한다.

## 2. THz link budget

파장과 one-way free-space path loss는

\[
\lambda=\frac{c}{f_c},\qquad
L_{\mathrm{FS}}(R)=\left(\frac{4\pi R}{\lambda}\right)^2
\]

이다. 코드에서는 dB 단위로

\[
L_{\mathrm{FS,dB}}=20\log_{10}\left(\frac{4\pi Rf_c}{c}\right)
\]

를 사용한다.

### 2.1 C1 communication channel

\[
P_{\mathrm{C1,RF}}(R)
=P_t\frac{G_tG_r}{L_{\mathrm{FS}}(R)}
\frac{1-|\Gamma|^2}{L_{\mathrm{OMT}}^2}.
\]

따라서 C1 RF 수신전력은 \(R^{-2}\)이다. 단, C1도 ZBD square-law
검출을 사용하므로 고정된 detector-output noise에 대한 **출력 신호전력**은
\(P_{\mathrm{C1,RF}}^2\propto R^{-4}\)이다.

### 2.2 C2 monostatic sensing channel

\[
P_{\mathrm{ec}}(R)
=\frac{P_tG_tG_r\lambda^2\sigma_{\mathrm{eff}}}
{(4\pi)^3R^4L_{\mathrm{OMT}}^2}.
\]

따라서 echo RF power는 \(R^{-4}\), echo RF field는 \(R^{-2}\)이다.
`Direct effective RCS` 모드에서는 입력한 \(\sigma_{\mathrm{eff}}\)를 그대로
사용한다. `Coupled antenna` 모드에서는

\[
\sigma_{\mathrm{eff}}\simeq \sigma_{\mathrm{str}}
+\frac{\lambda^2G_{\mathrm{tar}}^2|\Gamma|^2\eta_{\mathrm{pol}}}{4\pi}
\]

의 incoherent power sum을 사용한다. 두 모델을 동시에 적용하지 않는다.

## 3. ZBD square-law target terms

C2 ZBD 입력을 SI와 echo의 합으로 쓰면

\[
v_{\mathrm{in}}=v_{\mathrm{SI}}+v_{\mathrm{ec}},\qquad
y=\mathcal R\frac{|v_{\mathrm{in}}|^2}{Z_0}.
\]

DC/SI-only 항을 제거한 target-dependent 항은 echo self-beat와
SI--echo cross-beat이다.

\[
y_{\mathrm{tar}}\propto |v_{\mathrm{ec}}|^2
+2\Re\{v_{\mathrm{SI}}v_{\mathrm{ec}}^*\}.
\]

코드는 cross term의 in-phase와 quadrature 성분을 각각 계산한 뒤

\[
P_{\mathrm{cross}}
=\frac{P_I+P_Q}{2}
\]

로 phase-average한다. 따라서 carrier phase에 따른 인위적인 null/ripple을
ISAC-range bound에 넣지 않는다.

거리 법칙은 다음과 같다.

\[
P_{\mathrm{cross}}\propto P_{\mathrm{SI}}P_{\mathrm{ec}}
\propto R^{-4},
\qquad
P_{\mathrm{self}}\propto P_{\mathrm{ec}}^2
\propto R^{-8}.
\]

따라서

\[
\gamma_{\mathrm{sens,on}}(R)=\frac{C_4}{R^4}
+\frac{C_{8,\mathrm{on}}}{R^8},
\qquad
\gamma_{\mathrm{sens,off}}(R)=\frac{C_{8,\mathrm{off}}}{R^8}.
\]

target power 자체는 SI-on에서 cross term이 더해지므로 SI-off보다 작지 않다.
동일한 output-noise reference라면
\(\gamma_{\mathrm{sens,on}}\ge\gamma_{\mathrm{sens,off}}\)도 성립한다.
실제 코드는 다음 절처럼 SI-on/off detector noise를 따로 전파한다.

## 4. Detector-output noise reference

논문용 sensing SINR에서는 RF power product를 입력 thermal noise와 직접
나누지 않는다. RF product와 detector-output noise는 차원이 다르기 때문이다.

코드는 한 physical simulation reference point에서 다음을 분리한다.

- deterministic C2 target: SI--echo cross-beat와 echo self-beat
- deterministic SI-only component
- physical receiver-noise residual

physical residual은

\[
n_d(t)=y_{\mathrm{C2,SIC}}(t)-y_{\mathrm{C2,deterministic}}(t)
\]

로 얻고, 동일한 IF band에서 적분해 \(N_d\)를 계산한다. 이 residual에는
LNA thermal noise, ZBD NEP, IF-amplifier excess noise, DSO noise 및
signal--noise beating이 포함된다. deterministic SI와 target은 포함하지 않는다.

입력 thermal-noise PSD와 receiver NF는 SI-on/off에 공통이다. 그러나 ZBD
출력에서는 SI-on일 때 \(2\Re\{v_{\mathrm{SI}}n^*\}\) beating이 추가되므로,
detector-output noise \(N_{d,\mathrm{on}}\)과
\(N_{d,\mathrm{off}}\)는 일반적으로 같지 않다. 코드는 reference range에서
두 값을 각각 한 번 구한 뒤 거리 sweep 동안 고정한다. 동일한 input NF를
두 번 넣는 것이 아니라, 같은 입력 잡음이 서로 다른 square-law operating
point를 통과한 결과를 보존하는 것이다.

IF amplifier 자체 추가 잡음은

\[
N_{\mathrm{IF,add}}
=kTB(F_{\mathrm{IF}}-1)\frac{G_{\mathrm{IF}}}{L_{\mathrm{cable}}}
\]

로 계산한다. 앞단 noise가 이미 LNA waveform에 있으므로 \(kTBF G\) 전체를
다시 더하지 않는다. 이 수정은 thermal noise의 중복 계산과 cable-loss 누락을
동시에 방지한다.

## 5. Processing gain과 \(\rho\)

ideal coherent processing gain은

\[
G_{p,\mathrm{ideal}}=BT_p
=B\frac{N_p}{R_s}.
\]

\(B\simeq R_s\)이고 \(N_p=1024\)가 고정이면 baud rate가 변해도
\(G_{p,\mathrm{ideal}}\simeq1024=30.10\) dB이다. 대역폭만 바꾸고
symbol rate 또는 pilot length를 고정하지 않는 경우에는 이 값도 바뀐다.

논문 그림은 기본적으로

\[
G_{p,\mathrm{eff}}=26.0\ \mathrm{dB}
\]

를 사용하며, 코드에서 ideal \(BT_p\)보다 커지지 않도록 제한한다.

detector target power는 unit-power 전체 waveform에서 얻는다. System Model의
sensing pilot power만 사용하기 위해 sensing SINR에 \(\rho\)를 정확히 한 번
적용한다.

\[
\gamma_{\mathrm{sens},q}
=\rho G_{p,\mathrm{eff}}
\frac{P_{\mathrm{target,det},q}}{N_{d,q}},
\qquad q\in\{\mathrm{on},\mathrm{off}\}.
\]

dB 단위에서는

\[
\gamma_{\mathrm{sens},q,\mathrm{dB}}
=P_{\mathrm{target,det},q,\mathrm{dBm}}-N_{d,q,\mathrm{dBm}}
+G_{p,\mathrm{eff,dB}}+10\log_{10}\rho.
\]

target power에 \(\rho\)를 넣은 뒤 processing 단계에서 다시 넣는 중복 계산은
허용하지 않는다.

## 6. Sensing threshold와 maximum range

single-look noncoherent complex detector에서

\[
P_d=Q_1\left(\sqrt{2\gamma},\sqrt{-2\ln P_{fa}}\right)
\]

를 사용한다. \(P_d=0.9,\ P_{fa}=10^{-6}\)을 역산하면

\[
\gamma_{\mathrm{th}}=13.1835\ \mathrm{dB}
\]

이며 GUI의 13.2 dB는 이를 반올림한 값이다.

\(\gamma R^8-C_4R^4-C_{8,\mathrm{on}}=0\)의 양의 해는

\[
R_{\max}^{\mathrm{sens,on}}
=\left[
\frac{C_4+\sqrt{C_4^2+
4\gamma_{\mathrm{th}}C_{8,\mathrm{on}}}}
{2\gamma_{\mathrm{th}}}
\right]^{1/4},
\]

\[
R_{\max}^{\mathrm{sens,off}}
=\left(\frac{C_{8,\mathrm{off}}}{\gamma_{\mathrm{th}}}\right)^{1/8}.
\]

동일한 echo self-beat numerator에 대해
\(C_{8,\mathrm{off}}=C_{8,\mathrm{on}}
N_{d,\mathrm{on}}/N_{d,\mathrm{off}}\)이다.

RCS가 10 dB 증가하면 두 sensing range 모두
\(10^{10/40}=1.778\)배 증가한다.

## 7. Communication SINR와 maximum range

표시하는 communication quantity는 equalized EVM으로부터 얻은
EVM-equivalent SINR이다.

\[
\gamma_{\mathrm{comm,eq}}=\frac{1}{\mathrm{EVM}_{\mathrm{rms}}^2},
\qquad
\gamma_{\mathrm{comm,eq,dB}}=-\mathrm{EVM}_{\mathrm{dB}}.
\]

이는 residual distortion, synchronization 및 one-tap FDE 오차를 포함하는
effective SINR이며, 순수 AWGN SNR과 동일하다고 주장하지 않는다.

reference simulation point에서 EVM-equivalent SINR
\(\gamma_{c,0}\)과 physical detector-noise SNR \(\gamma_{N,0}\)을 별도로
구한다. residual-interference SIR은

\[
\frac{1}{\gamma_{I,0}}
=\max\left(
\frac{1}{\gamma_{c,0}}-\frac{1}{\gamma_{N,0}},0
\right)
\]

으로 분리한다. 이때

\[
q_d=\frac{1-\rho}{1-\rho_0},\qquad
q_P=\left(\frac{P_t}{P_{t,0}}\right)^2,\qquad
q_m=\frac{m^2}{m_0^2}
\]

라 두면

\[
\gamma_N(R)=\gamma_{N,0}q_dq_Pq_m
\left(\frac{R_0}{R}\right)^4,
\qquad
\gamma_I=\gamma_{I,0}\frac{q_d}{q_m},
\]

\[
\frac{1}{\gamma_c(R)}
=\frac{1}{\gamma_N(R)}+\frac{1}{\gamma_I}
\]

이다. 요구 SINR을 \(\gamma_{\mathrm{req}}\)라 하면,
\(\gamma_I>\gamma_{\mathrm{req}}\)일 때만

\[
\gamma_{N,\mathrm{req}}
=\left(
\frac{1}{\gamma_{\mathrm{req}}}-\frac{1}{\gamma_I}
\right)^{-1}
\]

가 유한하며

\[
R_{\max}^{\mathrm{comm}}
=R_0\left[
\frac{\gamma_{N,0}q_dq_Pq_m}{\gamma_{N,\mathrm{req}}}
\right]^{1/4}.
\]

이는 C1 RF power가 \(R^{-2}\)인 것과 모순되지 않는다. ZBD 출력의 desired
power가 RF power의 제곱이기 때문에 noise-limited SNR은 \(R^{-4}\)가 된다.
EVM residual을 같은 noise에 다시 더하지 않고 SIR로 분리하므로 중복 계산도
방지한다.

## 8. EVM versus symbol rate

low-rate AWGN reference는 2/4 GBd measured EVM으로 offset을 정하고

\[
\mathrm{EVM}_{\mathrm{SNR,dB}}(B)
=-\mathrm{SNR}_{0,\mathrm{dB}}
+10\log_{10}(B/B_0)
\]

로 계산한다.

preview의 SINR curve는 EVM power domain에서

\[
\frac{1}{\mathrm{SINR}}
=\frac{1}{\mathrm{SNR}}+\frac{1}{\mathrm{SIR}},
\qquad
\mathrm{EVM}_{\mathrm{SINR}}^2
=\mathrm{EVM}_{\mathrm{SNR}}^2+\mathrm{EVM}_{\mathrm{SIR}}^2
\]

를 적용한다. low-rate deterministic residual은 제거하고 rate-dependent
excess만 SSBI-associated term으로 사용한다. 현재 저장 PNG에는 기존 요구대로
Measurement와 Theoretical SNR만 포함된다.

## 9. Sensing SINR versus SI power

This panel is a detector-calibrated analytical diagnostic at the reference
target range. The x-axis is the SI carrier power at the common LNA/ZBD input.
The same full-waveform reference used by the effective-RCS range figure
provides four C2-output quantities:

\[
P_{\mathrm{cross},0},\quad
P_{\mathrm{self},0},\quad
N_{\mathrm{on},0},\quad
N_{\mathrm{off},0}.
\]

They are respectively the phase-averaged SI--echo cross-beat power, echo
self-beat power, SI-on detector noise, and SI-off detector noise. For
\(s=P_{\mathrm{SI}}/P_{\mathrm{SI},0}\), the calibrated square-law scaling is

\[
P_{\mathrm{cross}}(s)=P_{\mathrm{cross},0}\,s\,qM_c,
\qquad
P_{\mathrm{self}}=P_{\mathrm{self},0}\,q^2M_c ,
\]

where

\[
q=
\frac{P_t}{P_{t,0}}
\times\frac{\sigma_{\mathrm{eff}}}{\sigma_{\mathrm{eff},0}}
\left(\frac{R_0}{R}\right)^4,
\qquad
M_c=10^{(\mathrm{CSPR}_0-\mathrm{CSPR})/10}.
\]

The SI-induced part of the C2-output noise is obtained from the SI-on/off
simulation ablation rather than recomputed at the RF-input reference plane:

\[
N_{\mathrm{C2}}(s)
=N_{\mathrm{base},0}
+\max(N_{\mathrm{on},0}-N_{\mathrm{off},0},0)s.
\]

Here \(N_{\mathrm{base},0}=\min(N_{\mathrm{on},0},N_{\mathrm{off},0})\);
the minimum prevents finite Monte-Carlo scatter from being interpreted as a
negative SI-induced noise contribution. For the packaged reference,
\(N_{\mathrm{on},0}>N_{\mathrm{off},0}\), so the baseline is exactly the
SI-off ablation.

\[
\gamma_{\mathrm{sens}}(s)
=G_{p,\mathrm{eff}}\rho
\frac{P_{\mathrm{cross}}(s)+P_{\mathrm{self}}}
{N_{\mathrm{C2}}(s)} .
\]

This expression preserves the expected physics: the cross-beat contribution
is linear in SI power, the echo self-beat remains at finite SI-independent
power, and SI--noise beating can produce a high-SI plateau. The previous
implementation instead combined these detector-output powers with
\(N^2+2P_{\mathrm{SI}}N\) formed from an input-referred RF noise value. It
therefore counted SI--noise beating twice and mixed incompatible reference
planes.

The leakage-generated SI-SSBI term is not included in the default prediction.
Section II states that it is below the noise floor at the operating point, so
setting an unmeasured leakage coefficient to unity is neither a calibration
nor a physically justified penalty. It may be added later only with a
simulation ablation or measured in-band residual that fixes its coefficient.

The LNA \(P_{1\mathrm{dB}}\) line is still evaluated at the RF-input plane
using total SI, sideband, echo, and input-noise power. The shaded region beyond
that line is outside the linear model. For the packaged reference
\((-10~\mathrm{dBm},1~\mathrm{m},-4.28~\mathrm{dBsm})\), both the SI-power
figure and the effective-RCS calculation now give \(20.10\) dB. Analytical
propagation gives \(18.38\) dB at \(1.1\) m, above the \(13.2\)-dB detection
requirement. The saved \(1.1\)-m C2 range profile gives \(20.56\) dB, so the
corrected model is conservative by about \(2.18\) dB at that measured point
rather than being tens of decibels inconsistent with it.

### 9.1 Realizable UTC-PD photocurrent sweep

The independent SI-power sweep is retained as a theoretical diagnostic, but
the experimentally realizable control variable is UTC-PD photocurrent. Below
saturation, the GUI uses

\[
P_t(I_{\mathrm{ph}})
=P_{t,0}\left(\frac{I_{\mathrm{ph}}}{I_{\mathrm{ph},0}}\right)^2,
\qquad
P_{t,\mathrm{dBm}}
=-10+20\log_{10}\left(\frac{I_{\mathrm{ph}}}{7~\mathrm{mA}}\right).
\]

At fixed isolation, target range, RCS, CSPR, and \(\rho\), both the SI carrier
and echo RF powers scale with \(q=P_t/P_{t,0}\). Therefore the detector-output
cross and self terms both scale as \(q^2\):

\[
P_{\mathrm{cross}}(q)=q^2P_{\mathrm{cross},0},
\qquad
P_{\mathrm{self}}(q)=q^2P_{\mathrm{self},0}.
\]

The sensing prediction used in the photocurrent figure is

\[
\gamma_{\mathrm{sens,on}}(q)
=G_{p,\mathrm{eff}}\rho
\frac{q^2(P_{\mathrm{cross},0}+P_{\mathrm{self},0})}
{N_{\mathrm{base},0}
+q(N_{\mathrm{on},0}-N_{\mathrm{off},0})},
\]

while the no-SI curve retains only the echo self-beat and the SI-off detector
noise. Thus sensing SINR has a \(2\)-dB/dB low-power slope when the baseline
noise dominates and approaches a \(1\)-dB/dB slope when SI--noise beating
dominates.

The `Photocurrent SINR` button opens a separate two-panel figure so the
existing SI-power figure remains unchanged. Its primary x-axis is measured
photocurrent and its secondary x-axis is the calibrated equivalent THz Tx
power. The top panel compares communication simulation with measured
\(-\mathrm{EVM}_{\mathrm{dB}}\). The bottom panel compares with-SI and no-SI
sensing simulations with raw-C2 matched-filter SINR proxies.

The measured sensing markers are not copied from the saved C2 summary. Every
`rx__C2__sig` waveform in `data/captures/photocurrent` is downconverted,
resampled, synchronized, and matched-filtered again using its embedded
`tx__*` reference. All captures use the same \(1.014\)-m target ROI; this
prevents a weak target from being replaced by the \(0.05\)-m zero-guard edge.
The plotted proxy is the selected target-bin profile level relative to the
median out-of-guard profile background. Filled sensing markers exceed the
13.2-dB threshold; open markers are non-detections/low-confidence ROI peaks.

The resulting comparison should be interpreted as follows:

- communication measurements approach the detector-reference simulation
  smoothly as photocurrent increases;
- at 6.5 and 7 mA, the 16QAM raw-C2 values are 19.60 and 19.55 dB, versus
  phase-averaged simulations of 18.65 and 19.84 dB;
- the remaining raw-C2 points, including the 32QAM series, lie around
  3--6 dB and are not monotonic with photocurrent.

Consequently the phase-averaged calculation is a plausible upper-envelope
link budget, but it does not predict every single coherent capture.
SI--echo phase/frequency-selective fading can produce deep sensing outages
even while communication improves monotonically. The low raw-C2 markers
must not be fitted away or presented as independent calibrated absolute
SINR measurements.

### 9.2 Previous C2 raw-band diagnostic

raw C2 curve는

\[
P_{\mathrm{raw}}=P_{\mathrm{background}}+P_{\mathrm{target}}
\]

이다. SI-on에서는 range-independent SI/noise background 때문에 먼 거리에서
평탄해질 수 있다. 이 raw total이 평탄하다고 echo가 \(R^{-4}\) 법칙을 위반한
것은 아니다.

Sensing SINR에는 raw total을 사용하지 않고 분리한 target-only power를
사용한다. SI-on target은 \(R^{-4}+R^{-8}\), SI-off target은 \(R^{-8}\)이다.

### 9.3 Measured sensing-SINR markers

The three measured C2 raw-band powers and one absolute profile-SINR
measurement do not share the simulator's detector-noise reference plane.
Therefore, the GUI does not subtract simulated noise from measured raw power.
Instead, it preserves the absolute profile-SINR anchor and transfers only the
measured relative power difference:

\[
\widehat{\gamma}_{\mathrm{sens},i,\mathrm{dB}}
=\gamma_{\mathrm{sens},0,\mathrm{dB}}
+P_{\mathrm{raw},i,\mathrm{dBm}}
-P_{\mathrm{raw},0,\mathrm{dBm}}.
\]

The resulting three symbols are anchor-based relative estimates. They are not
three independently calibrated absolute SINR measurements. A separately
measured SI-only/background power would be required for linear-domain
background subtraction.

## 10. ISAC range

\[
R_{\max}^{\mathrm{ISAC}}
=\min\left(R_{\max}^{\mathrm{comm}},
R_{\max}^{\mathrm{sens,on}}\right).
\]

effective-RCS sweep에서 communication curve가 수평인 이유는 RCS만 scenario
variable로 바꾸고 communication load factor \(|\Gamma|\)는 고정하기 때문이다.
RCS로부터 \(|\Gamma|\)를 역추정해 C1에 다시 적용하지 않는다.

### 10.1 Range Sweep의 데이터 경로

- Communication SINR: 각 range에서 실제 full waveform simulation의 EVM을
  다시 계산한다.
- C2 raw band power: 각 range의 full waveform spectrum integral을 사용한다.
- Sensing SINR: reference range의 phase-averaged target component와 physical
  noise를 얻은 뒤 \(R^{-4}+R^{-8}\) 법칙으로 전파한다.
- Effective-RCS figure: 같은 detector reference에서 RCS만 analytical scaling한다.

따라서 sensing curve는 carrier phase에 따른 coherent ripple을 보여주는 raw
sample curve가 아니라, 논문 link-budget에 해당하는 phase-averaged envelope이다.
이를 단순히 모든 distance의 raw simulation output이라고 표현하면 안 된다.

## 11. 2026-07-23 numerical sanity check

`isac_sim_params_20260720.json`의 direct effective RCS를 강제로 coupled
model로 덮어쓰지 않고, \(R_0=1\) m, \(P_t=-10\) dBm, isolation 24 dB,
direct effective RCS \(-4.28\) dBsm, seed 0으로 계산한 결과:

- EVM-equivalent communication SINR: 약 17.84 dB
- C1 physical detector-noise SNR: 약 18.81 dB
- residual-interference SIR: 약 24.81 dB
- C2 phase-averaged target: 약 \(-37.2\) dBm
- C2 SI-on detector-noise residual: 약 \(-38.24\) dBm
- C2 SI-off detector-noise residual: 약 \(-38.97\) dBm
- SI--echo cross term: 약 \(-37.4\) dBm
- echo self-beat: 약 \(-50.8\) dBm
- SI-assisted target gain over self-beat: 약 13.6 dB

\(\rho=0.2,\ G_{p,\mathrm{eff}}=26\) dB 및 13.2-dB threshold를 적용한
동일 seed sanity check에서는 \(R_{\max}^{\mathrm{comm}}\approx1.15\) m,
\(R_{\max}^{\mathrm{sens,on}}\approx1.47\) m,
\(R_{\max}^{\mathrm{sens,off}}\approx0.84\) m이므로
\(R_{\max}^{\mathrm{ISAC}}\approx1.15\) m이다. 이는 1 m 이상에서 수행한
range detection과 모순되지 않는다. 이 operating point에서는 SI-on range가
SI-off range보다 크다. 일반적으로 target power는 SI-on이 작아질 수 없지만,
SI--noise beating이 지나치게 크면 SINR/range 개선까지 보장되지는 않는다.
정확한 숫자는 seed, selected RCS, current TX operating point
및 full simulation에서 갱신한 detector reference에 따라 달라진다.

자동 수치 검증 결과:

- \(P_t\) 10 dB 증가: fixed-noise square-law target power 20 dB 증가
- cross-dominant SI-on range: 약 \(100^{1/4}=3.162\)배 증가
- self-beat-only range: \(100^{1/8}=1.778\)배 증가
- RCS 10 dB 증가: sensing range 1.778배 증가
- equal output-noise 조건의 모든 tested \(\rho\)에서
  \(R_{\mathrm{sens,on}}\ge R_{\mathrm{sens,off}}\)

## 12. 남아 있는 모델 한계

다음은 오류가 아니라 논문에서 명시해야 하는 validity boundary이다.

1. LNA/ZBD/ADC compression 또는 hard saturation은 현재 waveform model에
   명시적 transfer curve로 구현되어 있지 않다. \(P_t=0\) dBm은 THz PA를
   가정한 unsaturated what-if upper bound이다.
2. MZM은 third-order Taylor model이고 UTC-PD power는 saturation 이전의
   \(P_{\mathrm{THz}}\propto I_{\mathrm{ph}}^2\) calibration이다.
3. analytical range scaling은 한 operating point에서 detector reference를
   고정한다. \(P_t\), isolation 또는 receiver gain을 바꾸면 signal--noise
   beating도 바뀌므로 반드시 `Range Sweep`으로 reference를 다시 생성해야 한다.
4. sensing bound는 single-target LOS, stationary clutter, phase-averaged
   cross term 및 range-independent residual background를 가정한다.
5. 26 dB effective processing gain은 ideal 30.10 dB보다 낮춘 assumed
   implementation value이며 직접 측정된 보편 상수가 아니다.
6. measured range-profile SINR과 detector pre-processing SINR은 기준면이
   다르다. measured profile point에 processing gain을 다시 더하지 않는다.

## 13. 중복 및 누락 방지 체크리스트

- \(P_t\): UTC-PD/virtual PA output에 한 번 적용
- RCS: direct override 또는 coupled-antenna model 중 하나만 적용
- OMT loss: outgoing/incoming 두 pass 적용
- \(\rho\): sensing pilot selection에 한 번, communication data에 \(1-\rho\)
- \(G_{p,\mathrm{eff}}\): detector pre-SINR 뒤 한 번
- C2 noise: deterministic SI/target 제외, physical residual만 적분
- C2 SI-on/off noise: 공통 input NF에서 각각의 square-law output으로 전파
- C2 target: raw total이 아니라 cross+self target-only 사용
- SI-on: cross+self, SI-off: self only
- ISAC range: communication과 SI-on sensing range의 minimum
- threshold: communication 15.75 dB, sensing 13.2 dB
- detector reference: 현재 UI의 `SimConfig`와 마지막 실행 config가 같을 때만
  `Sync Sim`으로 재사용; 다르면 `Range Sweep` 전까지 range bound를 무효화
