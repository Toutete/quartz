---
title: Symbol-Rate EVM/Resolution Trade-off and SSBI Verification
is_public: false
updated: 2026-07-14
---

# Symbol Rate에 따른 EVM/Resolution Trade-off 및 SSBI 검증

이 문서는 논문 Fig. 3(EVM / range resolution / SINR vs symbol rate trade-off)의 설계 근거와,
"광대역에서 SSBI를 피할 수 없다"는 주장을 실측 데이터로 검증한 과정을 정리한다.

---

## 1. Fig. 3의 목적과 메커니즘

광대역(넓은 symbol rate `B`)에서 SSBI를 피할 수 없는 이유는 총 SSBI 전력이 커져서가 아니라,
SSBI가 DC 근처 `~2B` 폭으로 퍼지는데 IF 중심주파수 `f_IF`(가드밴드)가 하드웨어로 고정되어 있기
때문이다. `B`가 커져서 `B ≳ f_IF`가 되면 SSBI 스펙트럼이 신호 대역과 물리적으로 겹치기 시작한다.

```math
\text{guard margin} = f_{IF} - B/2
```

이 guard margin이 `B`가 커질수록 줄어드는 것이 핵심 메커니즘이며, `f_IF=11\,\text{GHz}` 기준
실측 스윕(2~20 GBaud)에서 다음과 같이 계산된다.

| Symbol rate | Occupied BW `B` | Guard margin `f_IF - B/2` |
|---|---|---|
| 2 GBaud | ~2 GHz | ~10 GHz |
| 8 GBaud | ~8 GHz | ~7 GHz |
| 12 GBaud | ~12 GHz | ~5 GHz |
| 20 GBaud | ~20 GHz | **~1 GHz** |

---

## 2. Fig. 3 최종 구성

데이터 출처: photocurrent 7 mA 고정, `fsym`=2/4/8/10/12/15/17/20 GBaud, 16QAM/32QAM,
DFT-s-OFDM. 값은 실험실 스프레드시트에서 그대로 transcribe.

2-panel, IEEE Transactions 스타일 (본문 title 없음, red=16QAM/blue=32QAM 고정색,
filled=16QAM / open=32QAM 마커):

- **(a) Measured EVM (dB) vs symbol rate**: 실측 EVM 곡선(16QAM, 32QAM) + 점선
  이론선(가장 낮은 symbol rate를 anchor로 `-10\log_{10}(B/B_{anchor})` 외삽, 고정 송신
  전력에서 noise power `N=N_0 B`가 대역폭에 선형 비례한다는 가정).
- **(b) Range resolution `c/2B` (mm) vs symbol rate**: 이론 계산선만 (측정 아님).

스크립트: [plot_evm_tradeoff_figure.py](../code/plot_evm_tradeoff_figure.py)
(`--source table`이 기본값이며 하드코딩된 실측 테이블을 그대로 사용; `--source npz`로
`data/captures/bandwidth`의 원본 npz 캡처에서 다시 추출하는 것도 가능).

---

## 3. SSBI vs DSO-noise 지배 구간 검증

사용자가 제기한 두 가설:

- **높은 symbol rate**: SSBI가 지배적일 것으로 의심
- **낮은 symbol rate**: DSO(계측기) 자체 노이즈가 지배적일 것으로 의심

이를 검증하기 위해 네 가지 독립적인 분석을 수행했다.

### 3.1 방법 A — Guard-band 기하학 (가장 확실, 노이즈 추정 불필요)

위 1절의 guard margin 표 자체가 반박 불가능한 정성적 증거다. `B`가 20 GBaud에 이르면
guard margin이 1 GHz까지 줄어들어, SSBI(0~B 부근)와 실제 passband가 물리적으로 근접한다.

### 3.2 방법 B — Spectral SNR vs EVM gap (가장 강력한 정량적 증거)

npz에 저장된 `snr_com_db`(Welch PSD 기반, **out-of-band** 노이즈 바닥으로 계산된 SNR)와
EVM 기반 SINR(`-EVM_dB`, 실제 복조 성능 — SSBI를 포함)을 비교.

| Symbol rate | EVM 기반 SINR | 실측 `snr_com_db` | gap |
|---|---|---|---|
| 2 GBaud | ~25.2 dB | ~30.1 dB | ~0 dB |
| 8 GBaud | ~20.2 dB | ~22.8 dB | ~2.5 dB |
| 12 GBaud | ~18.6 dB | ~22.6 dB | ~4.0 dB |
| 20 GBaud | ~15.9 dB | ~22.3 dB | ~6.4 dB |

`snr_com_db`는 out-of-band 기준이라 in-band로 넘어온 SSBI를 못 잡아내는 반면 EVM은 그걸
전부 반영한다. gap이 **단조증가**하는 것이 SSBI가 `B`에 따라 점점 더 많이 passband로
새어 들어온다는 직접적 정량 증거다. (Fig. 3 본문에는 포함하지 않고, 검증/부록용으로 사용.)

### 3.3 방법 C — 근접-DC 스펙트럼 (SSBI 존재 확인)

DSO raw 스펙트럼(C1)에서 noise floor 기준을 passband 바로 옆(edge±1~3 GHz, 2 GBaud
기준으로는 대략 5/15 GHz 근방)으로 잡고, 근접-DC 창(0.05~1.5 GHz, passband lower edge보다
최소 1 GHz 아래로 제한)과 비교했다. 0 GHz 근처는 SSBI, ~22 GHz 근처는 harmonic으로 판단.

| Symbol rate | Noise floor | 근접-DC 창 | 초과분 |
|---|---|---|---|
| 2 GBaud | −91.0 dB | −77.4 dB | **+13.6 dB** |
| 4 GBaud | −91.1 dB | −79.6 dB | **+11.4 dB** |
| 8 GBaud | −87.3 dB | −85.2 dB | +2.1 dB |
| 12 GBaud | −87.5 dB | −85.8 dB | +1.7 dB |
| 20 GBaud | −90.0 dB | 측정 불가 (창이 passband에 잠식) | — |

DC 근처에 노이즈 바닥보다 11~14 dB 높은 실제 hump가 존재 — SSBI 존재 자체는 확인된다.
다만 이 초과분(PSD 레벨)은 `B`가 커질수록 오히려 줄어드는데, 이는 모순이 아니라 SSBI
총 전력이 대략 `B`와 무관(신호 세기의 제곱 항, `κ⁴` 성분)하고 `B`가 커지면 그 고정된
전력이 더 넓은 대역에 퍼져 PSD 레벨은 낮아지지만 passband와 겹치는 절대량은 늘어나는
그림과 일치한다. 즉 "SSBI 존재"는 이 스펙트럼이, "SSBI가 성능에 미치는 영향이 `B`에 따라
커진다"는 방법 B가 담당.

스크립트: [check_ssbi_noise_floor.py](../code/check_ssbi_noise_floor.py) (일회성 진단
스크립트, 논문 그림 파이프라인에는 포함되지 않음).

### 3.4 방법 E — Passband 내 lower/upper-half 비대칭 (가장 깔끔한 단일 지표)

DFT-s-OFDM은 pilot 기반 CFR을 쓰므로 subcarrier(주파수 bin)별 비교가 가능하다는 아이디어에서
출발. 다만 npz에 저장된 `range_zero__C1__cfr_h`를 확인해보니 **17 GBaud와 20 GBaud 파일에서
소수점까지 완전히 동일한 값**이 나왔다 — 이는 세션 중 한 번 저장된 정적 zero-reference가
여러 파일에 재사용된 것이며, 파일별 실제 채널 추정치가 아니다. 따라서 CFR 대신 각 파일에
고유하게 남아있는 raw RX 파형(`rx__C1__sig`)의 스펙트럼을 직접 사용했다.

방법: 각 capture의 실제 symbol rate로 passband 경계(`f_IF ± B/2`)를 계산하고, 이를
lower-half(`f_IF-B/2 ~ f_IF`, DC에 가까운 쪽)와 upper-half(`f_IF ~ f_IF+B/2`, 먼 쪽)로
나눈 뒤 각 절반의 5th-percentile magnitude(스펙트럼 골짜기 = 국소 noise floor 근사치)를 비교.

| Symbol rate | Lower-half floor | Upper-half floor | Lower − Upper |
|---|---|---|---|
| 2 GBaud | −73.4 dB | −71.7 dB | **−1.75 dB** |
| 4 GBaud | −76.5 dB | −75.6 dB | −0.93 dB |
| 8 GBaud | −77.6 dB | −77.2 dB | −0.43 dB |
| 10 GBaud | −78.6 dB | −78.4 dB | −0.27 dB |
| 12 GBaud | −78.8 dB | −78.6 dB | −0.25 dB |
| 15 GBaud | −79.5 dB | −79.4 dB | −0.14 dB |
| 17 GBaud | −79.6 dB | −80.6 dB | **+1.00 dB** |
| 20 GBaud | −79.0 dB | −81.7 dB | **+2.76 dB** |

**단조 증가하며 부호가 뒤집힌다**: 저 symbol rate에서는 lower-half가 오히려 upper-half보다
낮음(음수, 즉 DC쪽이 더 깨끗)이다가, symbol rate가 커질수록 그 차이가 계속 줄고 17 GBaud
부근에서 부호가 바뀌어 20 GBaud에서는 lower-half가 upper-half보다 2.76 dB 더 나빠진다.
이는 SSBI가 DC 쪽에서 passband 하단을 잠식한다는 그림과 정확히 일치하며, **다른 캡처와
비교할 필요 없이 캡처 하나 안에서 자기 완결적으로 검증**되는 가장 깔끔한 단일 지표다.

그림: [subcarrier_asymmetry.png](../code/data/captures/bandwidth/subcarrier_asymmetry.png)
스크립트: [check_subcarrier_ssbi.py](../code/check_subcarrier_ssbi.py)

### 3.5 방법 D — Photocurrent 스윕 log-log 기울기 (15 GBaud, 32QAM)

15 GBaud 고정, photocurrent(launch power)를 4.5→7 mA로 스윕한 실측 EVM:

| Photocurrent (mA) | EVM (dB) |
|---|---|
| 4.5 | −13.48 |
| 5.0 | −13.68 |
| 5.5 | −14.53 |
| 6.0 | −15.39 |
| 6.5 | −16.57 |
| 7.0 | −17.49 |

고정 노이즈(DSO/열잡음) 지배 모델이면 `\text{EVM}_{dB} \propto -20\log_{10}(I)`이므로
구간별 기울기(`\Delta\text{EVM}_{dB} / \Delta[20\log_{10}(I)]`)가 어디서나 약 **−1**이어야
한다.

| 구간 | 기울기 (dB/dB) |
|---|---|
| 4.5→5 mA | **−0.22** |
| 5→5.5 mA | −1.02 |
| 5.5→6 mA | −1.15 |
| 6→6.5 mA | −1.69 |
| 6.5→7 mA | −1.44 |

낮은 photocurrent(4.5→5 mA)에서 기울기가 −0.22로 훨씬 얕다 — photocurrent를 올려도
기대만큼 EVM이 개선되지 않는다는 뜻이며, 신호 세기와 함께 커지는 잡음(SSBI 후보)이
그 구간을 지배한다는 신호다. Photocurrent가 더 오르면 기울기가 −1을 넘어서며 정상화된다.

15 GBaud는 이미 SSBI가 의심되는 고대역이므로, 이 결과는 "SSBI가 낮은 photocurrent에서
상대적으로 더 지배적"이라는 가설과 일치한다.

**결정적 대조군 (미확보)**: 동일한 photocurrent 스윕을 **낮은 symbol rate(예: 2 GBaud)**
에서 수행. 만약 2 GBaud에서는 전 구간 기울기가 거의 −1로 일정하다면(SSBI 영향 없이
순수 고정노이즈 지배), 그것이 "낮은 symbol rate는 DSO 노이즈만 지배, SSBI는 안 보인다"는
가설의 직접적 대조 증거가 된다. 현재 미보유.

---

## 4. 종합 정리

| 근거 | 확실성 | 결론 |
|---|---|---|
| A. Guard-band 기하학 | 확실 (정의상) | `B`↑ → guard margin↓, 20 GBaud에서 ~1 GHz까지 축소 |
| B. Spectral SNR vs EVM gap | 강함 (정량적, 기존 데이터로 계산 가능) | gap 0→6.4 dB 단조증가, SSBI가 out-of-band SNR 추정을 빠져나감 |
| C. 근접-DC 스펙트럼 | 중간 (SSBI 존재 확인, B-의존성은 간접) | 11~14 dB 초과 hump 확인, PSD 레벨 자체는 B와 반비례(총 전력 고정 가정과 일치) |
| E. Passband lower/upper-half 비대칭 | 강함 (단일 캡처 내 자기완결적, 부호 반전) | −1.75 dB(2 GBaud) → +2.76 dB(20 GBaud)로 단조증가, 17 GBaud 부근에서 부호 반전 |
| D. Photocurrent 기울기 (15 GBaud) | 시사적 (대조군 없음) | 저전류에서 얕은 기울기, SSBI 후보와 일치하나 저symbol rate 대조군 필요 |

---

## 관련 파일

- [plot_evm_tradeoff_figure.py](../code/plot_evm_tradeoff_figure.py) — Fig. 3 생성 스크립트
- [check_ssbi_noise_floor.py](../code/check_ssbi_noise_floor.py) — 근접-DC SSBI 스펙트럼 진단 스크립트
- [check_subcarrier_ssbi.py](../code/check_subcarrier_ssbi.py) — passband lower/upper-half 비대칭 진단 스크립트
- [read_range_data.py](../code/read_range_data.py) — npz 메트릭/스펙트럼 추출 공통 함수
- [system_model_paper_ready.md](system_model_paper_ready.md) — SSBI/SINR 수식 유도 원본
- [04_dso_dsp_and_differential_ranging.md](04_dso_dsp_and_differential_ranging.md) — `snr_com_db` 계산 파이프라인(Sec. 2)
