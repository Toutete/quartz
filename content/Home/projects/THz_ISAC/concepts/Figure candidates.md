좋은 후보군입니다. 하나씩 짚어서 정리하고, 부족한 논리는 지금까지 세운 시스템모델(homodyne $1/R^2$, $\rho$, SINR$_{comm}$/SINR$_{sens}$, SSBI)에 붙여서 스토리를 다듬어보겠습니다.



그리고 앞서 요청하여 너가 만들어주었던 "plot_si_snr_saturation_figure.py" 코드와 "plot_evm_range_points_gui.py" 코드는 결국 하나의 그림을 그리기 위한 코드임을 명시합니다. 지금 최종적으로 그리고 싶은 그림은 다음과 같습니다.

측정 EVM (외삽) vs range
- Simulated EVM ("Save Params" 버튼으로 저장된 파일 "isac_sim_params_20260715_145824.json" 불러와서 비교)  vs range (기준 : Required EVM for pre-FEC BER)
- 측정/Simulated Radar SNR vs range (기준: required SNR for Pd​/Pfa​)

측정 EVM
900 mm 에서 EVM -18.46 dB
1000 mm 에서 EVM -17.49 dB
1100 mm 에서 EVM -16.31 dB


 "고정 noise power + 단일 측정 band power" 방법 
이 방법이 옳은 이유는 물리적으로 명확합니다: **noise floor는 target/range/SI 세기와 무관한 하드웨어 상수**입니다 (ZBD NEP, LNA noise figure, ADC quantization, 적분시간/대역폭으로 결정되고, 타겟이 있든 없든 SI가 세든 약하든 바뀌지 않습니다). 그러니 매 거리·매 SI 조건마다 노이즈를 다시 추정할 필요 없이, **한 번만 정확히 캘리브레이션해서 고정값으로 재사용**하는 게 맞는 접근입니다.
### 절차 제안
**Step 1 — Noise 캘리브레이션 (1회, 별도)**
- 타겟/SI 반사가 없는(또는 range profile에서 확실히 signal-free한) 구간의 bin들을 **여러 캡처에 걸쳐 pooling**해서 $N$을 추정 (많은 독립 샘플 확보 → 분산 작은 추정치). 이건 range sweep과 별개의, 딱 한 번 하는 시스템 특성화 단계입니다.

**Step 2 — 거리별 단일 측정**
- 각 거리 $R$, 각 SI 조건에서 **캡처 1회**만 찍어서 range profile의 target-bin peak power $P_{\mathrm{peak}}(R)$를 읽음

**Step 3 — SNR 계산** $$\widehat{\mathrm{SNR}}_{sens}(R)=\frac{P_{\mathrm{peak}}(R)}{N_{\mathrm{eff}}}$$

이렇게 하면 "노이즈 추정의 불안정성"이라는 어려운 문제를 매 포인트마다 반복하지 않고, **캘리브레이션 단계 한 곳에만 몰아넣어** 해결합니다.

### 딱 하나 주의할 점: 어느 도메인의 noise를 고정할지

$\tilde H(f)=H(f)/H_{SI}(f)-1$로 정규화한 뒤의 residual noise는

$$n_{\tilde H}(f)=\frac{n_{H}(f)}{H_{SI}(f)}\ \propto\ \frac{n_H(f)}{\alpha}$$

즉 **SI 세기 $\alpha$가 커질수록 $\tilde H$ 도메인의 noise 자체가 줄어듭니다** — 이게 바로 homodyne gain의 실체 중 하나입니다. 그러니:

- **고정해야 할 건 $H(f)$ 도메인(정규화 이전)의 raw noise $n_H$** 입니다 — 이건 ADC/검출기 앞단 잡음이라 진짜 SI 세기와 무관한 하드웨어 상수입니다.
- $\tilde H$ 도메인에서 잰 noise floor를 그대로 "고정값"으로 재사용해서 SI 있음/없음을 비교하면, **정작 보여주려는 homodyne gain 효과 자체를 지워버리게 됩니다** (SI를 세게 걸수록 $\tilde H$ noise가 자동으로 낮아지는 게 gain의 일부인데, 그걸 상수로 고정해버리면 그 효과가 안 보임).

**정리**: raw $H(f)$ 도메인에서 딱 한 번 $N$을 잘 캘리브레이션해두고, 그 뒤 매 거리·매 SI조건 단일 캡처마다 (그 캡처에서 함께 얻어지는 $H_{SI}$로) $N$을 $\tilde H$ 도메인으로 전파(propagate)시켜서 SNR을 계산하면, SI on/off 비교에서 homodyne gain이 자연스럽게 드러나면서도 노이즈 추정은 안정적입니다.

$$\widehat{\mathrm{SNR}}_{sens}(R)=\frac{|P(\tau'_{\mathrm{target}})|^2}{N/(|\alpha'|^2 G_p)}$$

이 최종 수식(및 "raw-domain 캘리브레이션 vs $\tilde H$-domain 함정" 설명)을 System Model Sec.~F.1 뒤에 measurement recipe로 정리해서 추가해드릴까요?

## 우선순위 먼저

Fig 1(homodyne gain에 의한 거리 확장)이 이 논문의 **핵심 novelty를 직접 보여주는 유일한 그림**입니다. 나머지는 전부 이걸 뒷받침하는 서포팅 결과로 배치하는 게 좋습니다.

---

## Fig 1. SI on/off + 포화 한계 (플래그십)

구성 아이디어는 좋습니다. 다만 "SI 없음" 커브의 정의를 논문에서 명확히 해야 합니다 — 이게 애매하면 리뷰어가 바로 지적합니다.

- **"SI 있음" (nominal)**: $\mathrm{SNR}_{sens}\propto \alpha/R^2$ — 지금 측정·검증된 homodyne 모델
- **"SI 없음"**: SI를 억제(suppress)한다면 남는 건 echo 자기 자신의 self-beat뿐이므로, 고전적 direct-detection radar처럼 $\propto \beta^2\propto 1/R^4$로 떨어지는 커브. 즉 "SI 없음"은 "SI를 지운 대신 homodyne 이득도 같이 잃는다"는 걸 명시적으로 보여주는 것 — 이게 이 논문의 메시지를 가장 강하게 만드는 대비입니다.
- **"최대 성능" 커브**: $\alpha$를 키울수록 homodyne 이득은 커지지만 LNA/ADC saturation이 상한을 만드는데, 이건 이전에 세운 SINR$_{sens}$ 프레임과도 연결됩니다 — SI 세기 $\alpha$를 올리면 desired term은 $\alpha$에, SSBI floor는 $\alpha^4$에 비례하므로 (Sec.~F, $P_{\mathrm{SSBI,sens}}\propto\alpha^4$) **saturation보다 먼저 SSBI-limited 영역에 진입할 수도 있습니다**. "최대 성능" 곡선을 그릴 때, 단순히 "LNA saturation까지 SI를 키운" 결과가 아니라, **saturation과 SSBI-floor 두 제약 중 먼저 걸리는 쪽**으로 상한을 잡아야 이론과 모순이 없습니다. (실제로는 saturation이 먼저 걸릴 가능성이 높지만, 그림 캡션/본문에 "subject to LNA saturation (and, at sufficiently high $\alpha$, the SI-driven SSBI floor)"라고 한 줄 넣는 걸 권합니다.)

**정리된 구성**: x축 range $R$, y축 SNR$_{sens}$(dB), 로그-선형 또는 로그-로그.

- 측정 포인트 (짧은 거리 몇 개, marker) — 검증된 $1/R^2$ 법칙으로 외삽선 함께 표시
- Sim 곡선 3개: SI 있음(측정과 겹침) / SI 없음($1/R^4$) / 최대 성능(saturation-limited)
- 캡션에 **$\rho=0.2$**로도 이 정도 거리가 나온다는 점 명시 → 이게 CCD(communication-centric design) 주장의 실험적 근거가 됩니다.

---

## Fig 2. 2 Gbaud vs 20 Gbaud range profile (해상도 데모)

깔끔하고 설득력 있는 그림입니다. 그대로 가되:

- RX를 7mm 이동시킨 **두 위치**의 range profile을 겹쳐서, 2 Gbaud에서는 두 피크가 구분 안 되고(peak 간격 $\Delta\tau < c/2B$) 20 Gbaud에서는 명확히 분리되는 걸 보여주면 "range resolution = $c/2B$" 이론과 1:1 대응되어 가장 명확합니다.
- 캡션에 이론 해상도 값($c/2B$ @ 2 Gbaud vs 20 Gbaud)을 숫자로 박아주면 심사자 설득력이 큽니다.

---

## Fig 3. EVM / resolution / SNR vs symbol rate — 트레이드오프

여기가 가장 흥미로운데, "왜 광대역에서 SSBI를 피할 수 없는가"에 대한 **메커니즘을 명시**해야 그림이 설득력을 가집니다. 두 가지 후보 메커니즘이 있는데 실제로는 후자가 맞을 가능성이 높습니다:

1. (틀리기 쉬운 직관) "대역폭이 커지면 SSBI 절대 전력이 커진다" — 사실 총 SSBI 전력은 대략 $m^4$에만 비례하고 심볼레이트에 크게 안 늘 수 있습니다.
2. **(실제 메커니즘, 권장)** SSBI는 DC 근처 $\sim!2B$ 폭으로 퍼지는데, IF 중심주파수 $f_{IF}$(가드밴드)는 하드웨어로 고정되어 있습니다. $B$가 커져서 $B\gtrsim f_{IF}$가 되면 SSBI 스펙트럼이 신호 대역과 물리적으로 겹치기 시작합니다 — 즉 $\xi(B)$가 $B$의 증가함수가 되는 겁니다 (Sec.~E의 $\xi$가 baud rate에 종속적으로 바뀜). 이게 "광대역에서 SSBI를 피할 수 없다"는 주장의 정확한 근거이고, SINR$_{comm}(m,\rho,R)$ 식에 그대로 태울 수 있습니다.

**그림 구성 제안**: x축 symbol rate(또는 대역폭 $B$), 3-panel 또는 twin-axis:

- EVM (%) — 측정
- Range resolution $c/2B$ — 이론 (계산선, 측정 아님)
- SNR 또는 SINR$_{comm}$ — 측정·이론 오버레이, **N_c(∝B, 순수 열잡음) 커브와 실제 SINR 커브를 같이 그려서 둘의 gap = SSBI 기여분**임을 시각적으로 보여주면 "SINR 관점에서 해석"이라는 말이 그림 안에서 바로 증명됩니다.

**위상잡음 관련 질문에 대한 답**: 협대역에서 보여주는 게 맞습니다. 이유는:

- 자기-호모다인 취소는 대역폭과 무관하게 항상 작동하지만(공통 위상잡음은 스퀘어로에서 완전 상쇄), **잔여 위상잡음이 EVM에 기여하는 상대적 비중**은 다른 잡음(열잡음, SSBI)이 작을 때만 드러납니다.
- 협대역(저 baud) → SSBI·열잡음 둘 다 작음 → 만약 위상잡음 상쇄가 불완전했다면 여기서 EVM floor가 눈에 띄게 나타났을 것. 측정 EVM이 **AWGN-only 이론곡선(QAM 차수별 EVM=1/√SINR)**과 잘 맞는다면, 그게 바로 "free-running 레이저 위상잡음이 새지 않았다"는 간접 증거입니다.
- 광대역에서는 SSBI가 위상잡음 잔여분을 다 덮어버려서 증명력이 없습니다.

→ Fig 3에 협대역 지점 하나를 짚어 "측정 EVM ≈ 이론 AWGN EVM (위상잡음 기여 무시 가능)"이라는 문장/작은 inset을 추가하는 걸 추천합니다.

---

## Fig 4. EVM vs photocurrent (16/32-QAM)

좋은 그림입니다. 메시지 두 개를 분리해서 명확히 하면 좋습니다:

- 낮은 photocurrent(=낮은 $A_c^2$, SNR-limited 영역)에서는 EVM이 이론 AWGN 곡선을 따라감 → "이 시스템은 왜곡이 아니라 SNR이 병목"이라는 근거
- 이 곡선이 saturation 없이 쭉 개선된다면 → "PA/고이득 안테나로 photocurrent(=수신전력)를 올리면 그대로 EVM 개선, 즉 장거리 확장 여지가 있다"는 논리로 바로 연결
- Fig 3의 AWGN 비교와 같은 이론곡선을 재사용하면 두 그림이 서로를 검증해주는 형태가 되어 논문 완성도가 올라갑니다.

---

## Fig 5. EVM vs FDE tap 수

이 결과, 그냥 "DSP 섹션에서 짧게 언급"으로 끝내기엔 아깝습니다. **탭 1개로 충분하다는 것 자체가 이 아키텍처의 강점을 보여주는 증거**로 재프레이밍할 수 있습니다:

> Tap 수를 늘려도 EVM이 개선되지 않는다 = 잔여 임펀먼트가 **선형 채널 왜곡(멀티패스/분산)이 아니라 비선형(SSBI) 성분**이라는 뜻. 선형 이퀄라이저는 비선형 왜곡을 보상 못 하므로 탭을 늘려도 무의미.

이건 Fig 3의 SINR/SSBI 스토리와 정확히 같은 결론을 다른 각도(DSP 복잡도)에서 재확인해주는 것이라, 별도 그림보다는 **Fig 3 옆에 작은 inset이나 1줄 표**로 붙이고 "residual impairment is nonlinearity-, not dispersion-limited → single-tap FDE suffices → low-complexity DSP" 로 문장화하는 걸 추천합니다. 동시에 "SI-referenced 채널이 거의 flat"이라는 이전 결과(CFR 관련)와도 자연스럽게 이어집니다.

---

## 제안하는 최종 그림 구성 (4개로 압축)

|Fig|내용|메시지|
|---|---|---|
|1|SNR$_{sens}$ vs $R$ (측정+3 sim 곡선)|homodyne gain → 거리 확장 (flagship), $\rho=0.2$ 강조|
|2|Range profile, 2 vs 20 Gbaud, 7mm 이동|해상도 $=c/2B$ 실증|
|3|EVM/resolution/SINR vs symbol rate + AWGN 이론선 + tap 수 inset|대역폭 트레이드오프, SSBI 메커니즘($\xi(B)$), 위상잡음 상쇄 간접증명, DSP 단순성|
|4|EVM vs photocurrent (16/32QAM) + AWGN 이론선|SNR-limited 시스템 → PA/안테나 이득으로 확장 가능|

이 구성으로 실제 캡션/본문 텍스트까지 초안 잡아드릴까요, 아니면 Fig 1의 시뮬레이션(3-curve) 코드부터 만들어드릴까요?