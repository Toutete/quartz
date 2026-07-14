---
title: DSO DSP and Differential Ranging Workflow
is_public: false
updated: 2026-07-13
---

# DSO DSP 및 Differential Ranging 최신 정리

이 문서는 현재 `isac_unified_gui.py`의 DSO 측정 탭에서 실제로 수행되는 DSP 절차를 기준으로 정리한 최신 버전이다. 대상은 DSO로 획득한 실수 IF 파형이며, TX 생성 시 저장된 payload/reference를 이용해 spectrum/SNR 측정, 동기화, 복조, 채널 추정, range detection, zero-reference 기반 differential ranging을 수행한다.

핵심 전제는 다음과 같다.

- DSO 입력은 real IF waveform이다.
- DSP 기준 샘플레이트는 DSO 샘플레이트가 아니라 TX payload의 `fs`이다.
- 복조와 range는 항상 TX reference payload와 현재 GUI 파라미터의 일관성을 확인한 뒤 수행한다.
- DFT-s-OFDM의 equalization 탭 수는 현재 GUI 기본값 및 사용 조건 기준 `1`이다. 따라서 현재 DSO demod 경로의 Post-EQ는 긴 FIR/FDE가 아니라 one-tap complex LS correction에 해당한다.
- range display는 zero reference를 저장해도 절대 range axis를 유지한다. zero reference는 overlay 및 differential range/CFR 계산에만 사용된다.

---

## 1. DSO 데이터 및 TX reference

DSO capture는 선택 채널별로 다음 형태로 runtime에 저장된다.

```text
rx_multi[ch] = {
  "sig": real_voltage_samples,
  "t": time_axis,
  "fs": dso_sample_rate
}
```

Full-duplex display는 최대 2개 채널을 표시한다.

- C1 또는 첫 번째 row: one-way LOS range, range scale = `c`
- C2 또는 두 번째 row: monostatic radar range, range scale = `c/2`

TX reference payload는 다음 정보를 제공한다.

- waveform type: `QAM`, `LFM-QAM`, `DFT-s-OFDM`
- TX baseband matrix: `tx_bb_matrix`
- TX symbol matrix: `tx_sym_matrix`
- sample rate: `fs`
- IF: `if_freq`, `iqtools_if_freq`
- symbol rate: `symbol_rate`, `symbol_rate_actual`
- QAM RRC taps/preamble 또는 DFT-s-OFDM pilot/active-bin metadata

DSO demod/range/CFR 실행 전에는 `_sync_dsp_params_from_payload`, `_assert_dsp_payload_consistent`, `_warn_if_tx_reference_stale`를 통해 GUI 값과 payload의 symbol rate, modulation, IF, waveform type이 맞는지 확인한다.

---

## 2. Spectrum, noise density, noise power, SNR

DSO Spectrum은 raw real waveform에 Welch PSD를 적용해서 계산한다.

```math
S_v(f) = \text{Welch}(v[n])
```

50 ohm 기준 전력 spectral density는 다음과 같다.

```math
PSD_{dBm/Hz}(f)
= 10\log_{10}\left({S_v(f) \over 50\Omega \cdot 1\text{ mW}}\right)
```

즉 spectrum plot에서 보이는 noise floor 값, 예를 들어 `-130 dBm/Hz`, 는 noise density `N_0`이다. 이 값 자체는 전체 noise power가 아니다.

신호 분석 대역은 waveform type에 따라 결정된다.

- DFT-s-OFDM: active IFFT bin bandwidth

```math
B_{\text{ana}} = f_s {N_{\text{active}} \over N_{\text{FFT}}}
```

- 일반 QAM/SC: symbol rate와 RRC roll-off 기반 occupied bandwidth

```math
B_{\text{ana}} \approx R_s(1+\beta)
```

- LFM-QAM: chirp bandwidth와 symbol bandwidth를 함께 반영

DSO 측정 탭의 band power, noise power, SNR 계산은 다음 순서이다.

1. 신호 대역 mask를 만든다.

```math
f \in [f_1, f_2]
```

2. raw in-band power를 PSD 적분으로 계산한다.

```math
P_{\text{raw}} = \sum_{f \in \text{band}} PSD_{\text{mW/Hz}}(f)\Delta f
```

3. noise density `N_0`를 정한다.

- stored noise floor가 있으면 그 값을 사용
- 없으면 current capture의 out-of-band PSD median 사용

```math
N_0 = \text{median}\{PSD_{\text{mW/Hz}}(f), f \notin \text{signal band}\}
```

4. noise power는 noise density를 분석 대역폭에 대해 적분한다.

```math
P_N = N_0 B_{\text{ana}}
```

5. signal-only band power는 raw in-band power에서 noise power를 뺀다.

```math
P_S = \max(P_{\text{raw}} - P_N, \epsilon)
```

6. SNR은 다음과 같이 계산한다.

```math
SNR_{\text{band}} = 10\log_{10}{P_S \over P_N}
```

따라서 table에 표시되는 값의 의미는 다음과 같이 구분된다.

| 항목 | 의미 | 단위 |
|---|---|---|
| Noise Density | PSD noise floor, 예: `-130 dBm/Hz` | dBm/Hz |
| Noise Power | `Noise Density + 10log10(Bana)` | dBm |
| Band Power | in-band raw power에서 noise power를 뺀 signal power | dBm |
| Band SNR | `Band Power / Noise Power` | dB |

주의: DFT-s-OFDM에서는 RRC filter가 적용되지 않으므로 `1.2 x symbol rate` 같은 RRC guard bandwidth를 noise power 계산에 쓰지 않는다. 현재 코드는 active-bin occupied bandwidth를 사용한다.

---

## 3. Real IF에서 complex baseband로 변환

DSO real IF signal `x[n]`은 `_rx_to_baseband`에서 다음 순서로 baseband가 된다.

### 3.1 DC 제거

```math
x_0[n] = x[n] - \mathbb{E}\{x[n]\}
```

### 3.2 complex mixing

기본 sideband sign은 `-1`이다.

```math
r_{\text{bb,high}}[n]
= 2x_0[n]\exp(-j2\pi f_{\text{IF}} n/f_{s,\text{DSO}})
```

여기서 `f_IF`는 가능하면 `iqtools_if_freq`, 아니면 `if_freq`를 사용한다.

### 3.3 TX reference sample rate로 resampling

DSO sample rate와 TX reference sample rate가 다르면 FFT 기반 complex resampling을 적용한다.

```math
r_{\text{bb}}[n] =
\text{Resample}\{r_{\text{bb,high}}\; ;\; f_{s,\text{DSO}}\rightarrow f_{s,\text{TX}}\}
```

### 3.4 baseband LPF

실수 IF downconversion 후 생기는 image와 넓은 잡음을 억제하기 위해 optional FFT LPF를 적용한다. cutoff는 waveform type별로 다르다.

- QAM: RRC occupied bandwidth보다 넓게 설정
- LFM-QAM: chirp half-bandwidth와 symbol transition bandwidth를 포함
- DFT-s-OFDM: active-bin occupied bandwidth 기반

DFT-s-OFDM의 cutoff는 현재 다음 형태이다.

```math
f_c = \min(0.65B_{\text{occupied}},\; 0.45f_s)
```

### 3.5 AGC normalization

복조 threshold, timing loop, slicer 안정성을 위해 RMS를 1로 정규화한다.

```math
r_{\text{bb}}[n] \leftarrow {r_{\text{bb}}[n] \over \sqrt{\mathbb{E}|r_{\text{bb}}[n]|^2}}
```

---

## 4. Frame synchronization

공통 frame sync는 `_frame_sync_and_reshape`에서 수행된다.

### 4.1 TX reference correlation

수신 baseband와 TX reference template 간 normalized가 아닌 magnitude correlation을 계산한다.

```math
C[k] =
\left|
\sum_n r_{\text{bb}}[k+n]s_{\text{ref}}^*[n]
\right|
```

```math
k_0 = \arg\max_k C[k]
```

DFT-s-OFDM의 경우 한 block template만 쓰면 반복 pilot/block 때문에 중간 block에 lock될 수 있다. 따라서 capture가 충분히 길면 full-frame template를 사용한다.

### 4.2 reshape

frame start 이후 수신 baseband를 `n_chirps x pts_per_chirp` matrix로 reshape한다.

```math
R[i,n] = r_{\text{bb}}[k_0 + iN_{\text{frame}} + n]
```

### 4.3 SRO/CFO refinement

LFM-QAM 및 DFT-s-OFDM은 blind CFO를 frame sync 전에 적용하지 않는다. 이전 방식처럼 capture 초반부만 보고 CFO를 추정하면 DSO pre-trigger margin 때문에 noise/idle 구간에 lock될 수 있기 때문이다.

대신 frame 위치를 먼저 찾은 뒤 `_refine_lfm_frame_sro`가 TX full reference와 비교하여 SRO와 CFO를 함께 보정한다. refinement score가 충분하면 fractional sample indexing과 CFO correction을 적용한다.

```math
n' = n(1+\epsilon_{\text{SRO}})
```

```math
r'[n] = r[n']\exp(-j2\pi f_{\text{CFO}}n/f_s)
```

---

## 5. QAM demodulation

`waveform_type == "QAM"`인 경우의 DSO demod 경로이다.

### 5.1 blind CFO estimate

QAM rotational symmetry를 이용한 M-th power CFO estimate를 먼저 수행한다.

```math
z[n] = r[n]^M
```

M-th power spectrum peak로 coarse CFO를 추정한다. quality가 충분할 때만 보정한다.

### 5.2 RRC matched filtering

TX payload에 저장된 `qam_rrc_taps`로 matched filtering을 수행한다.

```math
y[n] = r[n] * h_{\text{RRC}}[n]
```

### 5.3 preamble timing search

각 sample phase에 대해 symbol-rate stream을 만들고, known ZC preamble과 correlation한다.

```math
C_p[k] =
{\left|\sum_m y[k+m]p^*[m]\right|
\over
\sqrt{\sum_m |p[m]|^2 \sum_m |y[k+m]|^2}}
```

최대 correlation이 preamble 위치와 sample phase를 결정한다.

### 5.4 frame candidate 및 timing recovery

반복 preamble이 있는 경우 각 preamble peak가 어느 row인지 알 수 없으므로 가능한 frame start 후보를 만든다. 후보마다 다음을 평가한다.

- direct symbol slicing
- Gardner timing recovery gain 후보: `0`, `0.0015`, `0.004`, `0.008`
- preamble lock score
- data lock score

timing score가 약한 경우 `_refine_qam_frame_cfo_sro`로 CFO/SRO/frame start를 다시 refine한다.

### 5.5 fallback

reference lock이 충분하지 않으면 다음 fallback을 시도한다.

- PRBS stream fallback
- blind QAM filter/symbol search
- conjugate/rotation/IQ correction candidate

---

## 6. DFT-s-OFDM demodulation

`waveform_type == "DFT-s-OFDM"`인 경우 `_recover_dfts_ofdm_symbols`가 block별로 symbol을 복원한다.

### 6.1 payload reference

필수 metadata는 다음이다.

- `dft_n_fft`
- `dft_n_data`
- `dft_active_bins`
- `dft_zc_pilot`
- `dft_data_scale`
- `amplitude_ratio_rho`
- `tx_sym_matrix`

pilot/data 결합은 다음 power split을 따른다.

```math
x[n] = \sqrt{\rho}\,p[n] + \sqrt{1-\rho}\,d[n]
```

### 6.2 block-wise pilot CFO search

각 DFT-s-OFDM block에서 pilot lock을 최대화하도록 CFO grid를 탐색한다.

```math
\hat f_{\text{CFO}}
= \arg\max_f
{\left|\langle \sqrt{\rho}p[n], y[n]e^{-j2\pi fn/f_s}\rangle\right|
\over
\sqrt{E_pE_y}}
```

grid 범위는 symbol rate 기반으로 제한되며 대략 `±1 MHz`에서 `±12 MHz` 범위 안에 들어간다.

### 6.3 pilot 기반 channel estimate

active subcarrier에서 pilot 성분을 이용해 channel을 추정한다.

```math
H_{\text{pilot}}[k]
= {Y[k] \over \sqrt{\rho}P[k]}
```

필요하면 scalar pilot channel, smoothed vector channel, reference-aided update, decision-directed update를 평가한다.

### 6.4 data symbol recovery

channel equalization 후 pilot active component를 제거하고 DFT-spread symbol을 inverse DFT로 복원한다.

```math
\hat D_{\text{active}}[k]
= {1 \over \sqrt{1-\rho}}
\left(
{Y[k] \over \hat H[k]}
- \sqrt{\rho}P[k]
\right)
```

```math
\hat a[m]
= \text{IDFT}\{\hat D_{\text{active}}[k]\}
```

### 6.5 sideband/conjugate retry

복조 lock이 약할 때 다음 후보를 비교한다.

- default
- default + conjugate
- LPF off
- opposite sideband
- opposite sideband + conjugate

후보 score는 payload lock, pilot lock, min pilot lock, block 수를 조합하여 선택한다.

---

## 7. LFM-QAM demodulation

`waveform_type == "LFM-QAM"`은 chirp와 communication symbol이 같은 frame을 공유한다.

### 7.1 frame sync

공통 `_frame_sync_and_reshape`로 TX chirp reference에 lock한다.

### 7.2 dechirp

수신 frame과 base chirp conjugate를 곱한다.

```math
z[n] = r[n]c_{\text{chirp}}^*[n]
```

### 7.3 integrate-and-dump

symbol interval마다 평균을 내어 QAM symbol을 얻는다.

```math
\hat a[m]
= {1 \over N_s}
\sum_{n=mN_s}^{(m+1)N_s-1} z[n]
```

### 7.4 preamble 기반 phase/CFO 보정

preamble 구간에서 common phase와 residual phase slope를 추정한다.

```math
e[m] = \hat a[m]a_{\text{ref}}^*[m]
```

```math
\angle e[m] \approx \phi_0 + \alpha m
```

이를 전체 symbol stream에 보정한다.

---

## 8. Symbol correction 및 Post-EQ

복원된 symbol은 `_equalize_reference_candidates`에서 reference symbol과 비교되며, 여러 후보 중 EVM이 가장 낮은 경로를 선택한다.

### 8.1 alignment

먼저 reference와 estimated symbols 사이 lag를 작은 범위에서 정렬한다.

```math
\ell^* = \arg\max_\ell
{\left|\langle \hat a[n+\ell], a_{\text{ref}}[n]\rangle\right|
\over
\sqrt{E_{\hat a}E_a}}
```

### 8.2 phase correction

training/reference 구간에서 linear phase를 fitting한다.

```math
\angle(\hat a[n]a_{\text{ref}}^*[n])
\approx \alpha n + \phi
```

```math
\hat a[n] \leftarrow \hat a[n]e^{-j(\alpha n+\phi)}
```

### 8.3 widely-linear IQ correction

QAM 계열에서는 IQ imbalance 보정을 위해 다음 LS fit을 적용할 수 있다.

```math
a_{\text{ref}}[n]
\approx
c_1\hat a[n] + c_2\hat a^*[n] + c_0
```

PSK 계열(BPSK/QPSK/8PSK)은 widely-linear correction을 제한한다.

### 8.4 Post-EQ, FDE taps = 1

현재 DSO demod의 Post-EQ 탭 수는 `1`이다. `sc_fde_equalizer`에서 `num_taps <= 1`이면 다음 one-tap LS gain만 계산한다.

```math
g
= {\langle \hat a, a_{\text{ref}}\rangle
\over
\langle \hat a, \hat a\rangle}
```

```math
\hat a_{\text{eq}}[n] = g\hat a[n]
```

따라서 현재 설정은 frequency-selective multipath를 길게 equalize하는 multi-tap FDE가 아니다. 실제 의미는 residual complex gain/phase를 reference-aided로 맞추는 one-tap post correction이다.

### 8.5 EVM 및 BER

최종 선택된 candidate에 대해 EVM은 다음과 같이 계산한다.

```math
EVM_{\text{rms}}
=
\sqrt{
{\mathbb{E}|\hat a[n]-a_{\text{ref}}[n]|^2
\over
\mathbb{E}|a_{\text{ref}}[n]|^2}
}
```

```math
EVM_{dB} = 20\log_{10}(EVM_{\text{rms}})
```

BER은 hard decision bits와 reference bits를 비교해 계산한다.

---

## 9. Channel estimation, CFR

Channel response는 `_compute_channel_response_for_signal`과 `_estimate_lfm_cfr`에서 계산된다.

### 9.1 reference 선택

- DFT-s-OFDM: pilot matrix 사용
- 그 외: full TX baseband matrix 사용

DFT-s-OFDM range/CFR에서 full data waveform이 아니라 pilot reference를 쓰는 이유는 data symbol의 modulation 성분이 channel 추정에 섞이지 않게 하기 위함이다.

### 9.2 frequency-domain CFR estimate

RX/TX matrix row에 Hann window를 적용하고 FFT한다.

```math
Y_i(f) = \mathcal{F}\{w[n]r_i[n]\}
```

```math
X_i(f) = \mathcal{F}\{w[n]x_i[n]\}
```

여러 row/chirp를 합산한 LS channel은 다음이다.

```math
\hat H(f)
=
{\sum_i Y_i(f)X_i^*(f)
\over
\sum_i |X_i(f)|^2 + \epsilon}
```

TX spectral power가 충분한 frequency bin만 사용하며, frequency axis는 baseband offset을 RF display axis로 변환한다.

```math
f_{\text{RF}} = f_c + f_{\text{BB}}
```

### 9.3 CFR magnitude normalization

in-band median magnitude를 기준으로 normalization한다.

```math
|H|_{dB}
= 20\log_{10}
{|H(f)| \over \text{median}_{f\in band}|H(f)|}
```

ripple은 in-band magnitude의 95 percentile과 5 percentile 차이로 표시한다.

```math
Ripple_{dB}
= P_{95}(|H|_{dB}) - P_{5}(|H|_{dB})
```

### 9.4 group delay

in-band phase를 unwrap한 뒤 weighted line fitting을 수행한다.

```math
\angle H(f) \approx -2\pi f\tau_g + \phi_0
```

```math
\tau_g = -{1 \over 2\pi}{d\angle H(f)\over df}
```

range 환산은 row mode에 따라 다르다.

```math
R =
\begin{cases}
c\tau_g, & \text{one-way LOS} \\
{c\tau_g \over 2}, & \text{monostatic radar}
\end{cases}
```

---

## 10. Range detection

Range profile은 `_compute_isac_range_profile_for_signal`에서 matched filtering으로 계산된다.

### 10.1 reference 선택

CFR과 동일하게 reference를 선택한다.

- DFT-s-OFDM: repeated pilot matrix
- QAM/LFM-QAM: TX baseband matrix

### 10.2 matched filter profile

각 row/chirp마다 full correlation을 계산하고 평균한다.

```math
P_i[\ell]
=
\left|
\sum_n R_i[n]X_i^*[n-\ell]
\right|
```

```math
P[\ell] = {1\over N}\sum_i P_i[\ell]
```

lag axis는 다음과 같다.

```math
\ell \in [-(N_{\text{ref}}-1),\; N_{\text{frame}}-1]
```

range axis는 absolute mode에서 다음과 같다.

```math
R[\ell] = {\ell \over f_s}\cdot S_R
```

여기서 `S_R`은 one-way row에서는 `c`, monostatic row에서는 `c/2`이다.

### 10.3 peak selection

기본 peak는 matched-filter profile의 최대값이다. 다만 row/mode별 예외가 있다.

- one-way row: peak가 negative range에 있으면 positive range에서 가장 강한 peak를 선택한다.
- monostatic row: zero 근처 self-interference peak를 먼저 식별하고, guard 밖의 target peak를 선택한다.

monostatic zero guard는 최소 `0.05 m`, 또는 range resolution의 2배 정도로 설정된다.

### 10.4 peak refinement

선택된 peak 주변에서 centroid refinement를 수행한다.

```math
\hat R
=
{\sum_{k\in \Omega} R_k w_k
\over
\sum_{k\in \Omega} w_k}
```

가중치는 local floor를 뺀 matched-filter magnitude를 사용한다.

### 10.5 range resolution

분석 대역폭 기준 range resolution은 다음이다.

```math
\Delta R =
{S_R \over B_{\text{ana}}}
```

따라서 one-way와 monostatic은 같은 bandwidth에서도 resolution scale이 다르다.

### 10.6 PSLR

PSLR은 main peak 주변 guard bin을 제외한 sidelobe 최대값과 비교한다.

```math
PSLR_{dB}
= 20\log_{10}
{P_{\text{peak}} \over P_{\text{sidelobe,max}}}
```

---

## 11. Zero reference 및 differential ranging

`Store Zero Ref`는 현재 capture를 기준 상태로 저장한다. 저장되는 값은 channel별이다.

```text
lfm_range_zero_by_ch[ch] = {
  delay_s,
  frame_start,
  peak_lag,
  frame_period_s,
  profile,
  cfr,
  abs_range_m,
  range_mode,
  range_resolution_m,
  fs
}
```

중요한 점은 zero reference를 저장해도 이후 range plot의 x-axis는 relative로 이동하지 않는다는 것이다. 현재 구현은 absolute range axis를 유지하고, 저장된 reference profile을 overlay하며, displacement는 별도 metric으로 계산한다.

---

## 12. Peak-based differential range

저장된 zero reference가 있으면 current peak와 reference peak를 비교해 displacement를 계산할 수 있다.

```math
\Delta R_{\text{peak}}
= R_{\text{current peak}} - R_{\text{reference peak}}
```

다만 repeated frame에서는 frame sync가 이웃 frame에 lock될 수 있으므로 absolute record index보다 frame 내부 `peak_lag` 기준 비교가 더 안정적이다. 현재 zero reference 저장 시 `peak_lag`를 함께 저장하는 이유가 이것이다.

---

## 13. CFR phase-slope 기반 differential range

CFR 기반 differential range는 matched-filter peak 위치보다 더 미세한 displacement 추정에 사용된다.

### 13.1 CFR ratio

current CFR과 zero-reference CFR의 ratio를 만든다.

```math
G(f)
=
{\hat H_{\text{cur}}(f)
\over
\hat H_{\text{ref}}(f)}
```

### 13.2 differential phase slope

ratio phase를 unwrap하고 weighted line fitting을 수행한다.

```math
\angle G(f)
\approx -2\pi f\Delta\tau + \phi_0
```

```math
\Delta\tau
=
-{1\over 2\pi}
{d\angle G(f)\over df}
```

### 13.3 reliability weighting

fit weight는 TX spectral weight와 current/reference CFR amplitude reliability를 함께 반영한다.

```math
w(f)
\propto
w_{\text{TX}}(f)
\min(|H_{\text{cur}}(f)|,\; |H_{\text{ref}}(f)|)
```

너무 낮은 weight bin은 제거하고, MAD 기반 residual rejection 후 다시 fitting한다.

### 13.4 coherence

phase-slope fit 이후 residual coherence를 계산한다.

```math
\eta
=
\left|
{\sum_f w(f)
{G(f)\over |G(f)|}
e^{-j(\hat a f+\hat b)}
\over
\sum_f w(f)}
\right|
```

coherence가 높을수록 differential CFR 결과를 신뢰할 수 있다.

현재 range display에서는 CFR differential coherence가 약 `0.20` 이상이면 표시용 relative range에 활용하고, `range_diff_mm` metric은 coherence가 더 높은 경우, 약 `0.35` 이상일 때 CFR 기반 값을 우선 사용한다. 그렇지 않으면 peak-reference 기반 displacement를 사용한다.

### 13.5 range conversion

```math
\Delta R =
\begin{cases}
c\Delta\tau, & \text{one-way LOS} \\
{c\Delta\tau \over 2}, & \text{monostatic radar}
\end{cases}
```

---

## 14. 현재 DSO DSP metric 요약

DSO 측정/복조/range 탭에서 의미 있는 metric은 다음과 같다.

| Metric | 계산 의미 |
|---|---|
| Noise Density | Welch PSD 기반 out-of-band median 또는 stored reference, dBm/Hz |
| Noise Power | `Noise Density`를 analysis bandwidth로 적분한 값, dBm |
| Band Power | in-band PSD 적분값에서 noise power를 뺀 값, dBm |
| Band SNR | `Band Power / Noise Power`, dB |
| EVM | reference symbol 대비 RMS error |
| BER | hard decision bit와 TX reference bit 비교 |
| Pilot Lock | DFT-s-OFDM pilot correlation quality |
| Payload Lock | recovered symbols와 reference payload의 lock score |
| CFR Ripple | in-band normalized CFR magnitude의 95%-5% spread |
| Group Range | CFR phase slope로 추정한 absolute group delay range |
| Range Peak | matched-filter peak 기반 range |
| PSLR | main peak 대비 최대 sidelobe |
| Range Diff | zero reference 대비 displacement, peak 또는 CFR 기반 |
| CFR Coherence | differential CFR phase-slope fit 신뢰도 |

---

## 15. 현재 구현상 해석 주의점

1. Spectrum의 noise floor `dBm/Hz`는 noise density이다. Noise power는 이 값을 bandwidth에 대해 적분해야 하므로 dBm 값이 달라진다.

2. DFT-s-OFDM은 RRC roll-off bandwidth를 쓰지 않는다. noise power, spectrum highlight, demod LPF는 active-bin occupied bandwidth를 기준으로 해석해야 한다.

3. Post-EQ taps가 `1`이면 multi-tap equalizer가 아니다. 현재 DSO demod에서 `FDE taps = 1`은 complex scalar LS 보정이다.

4. DFT-s-OFDM range/CFR은 data payload 전체가 아니라 pilot reference를 사용한다. 이는 data modulation이 range/CFR 추정에 섞이는 것을 줄이기 위한 구현이다.

5. LFM-QAM range는 chirp matched filtering과 dechirp-demod가 같은 frame reference를 공유한다.

6. Zero reference는 range axis를 shift하지 않는다. absolute range plot을 유지하면서 saved reference profile을 overlay하고, displacement는 `range_diff_mm` 및 differential CFR metric으로 따로 보고한다.

7. CFR differential range는 phase unwrap, weighted fitting, coherence threshold에 의존한다. bandwidth가 좁거나 CFR SNR이 낮으면 peak-based range가 더 안정적일 수 있다.

8. Monostatic row는 self-interference/near-zero peak가 강할 수 있으므로 guard 밖 target peak 선택 로직을 적용한다.
