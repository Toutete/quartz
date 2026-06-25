# THz ISAC Testbed — Handoff Document

> THz ISAC 프로젝트의 전체 기술 컨텍스트를 담은 로컬 규칙 파일입니다.
> 전역 규칙은 `content/Home/CLAUDE.md`를 참조하세요.
> 이 파일은 모든 하드웨어 사양, 바이어스 절차, DSP 체인의 **근거(reasoning)**를 포함합니다.

---

## 0. 환경 설정 (새 컴퓨터 세팅)

### 필수 사전 설치
- Python 3.10 이상
- Git
- (계측기 직접 연결 시) Keysight IO Libraries Suite

### 저장소 클론 및 Python 환경 구성

```bash
git clone https://github.com/Toutete/quartz.git
cd quartz/content/Home/projects/THz_ISAC/code
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

### Claude Code로 자동 세팅

Claude Code CLI 설치 후 `quartz/` 에서 `claude` 실행, 아래와 같이 지시:

> "`https://github.com/Toutete/quartz.git` 를 클론하고,
> `content/Home/projects/THz_ISAC/code/` 에서 venv 만들고
> requirements.txt 설치한 다음 isac_unified_gui.py 실행해줘"

### 스크립트별 실행 방법

`code/` 폴더를 반드시 작업 디렉토리로 설정해야 합니다 (상대 import 때문).

```bash
cd content/Home/projects/THz_ISAC/code
venv\Scripts\activate

python isac_unified_gui.py              # 통합 TX·RX·SIC GUI
python envelope_detector_si_gui.py      # 엔벨로프 검출·시뮬레이션 GUI
python sim\back2back_sim.py             # OMT S-파라미터 시뮬레이션 (계측기 불필요)
python rx\dso_demod.py --mode sim       # 오프라인 복조 테스트
```

### 이론 노트 위치

각 모듈의 원리는 `concepts/` 폴더 참조:

| 파일 | 내용 |
|------|------|
| `concepts/00_system_architecture.md` | 전체 신호 흐름 및 시스템 구조 |
| `concepts/01_tx_signal_generation.md` | TX 파형 생성 및 AWG 연동 |
| `concepts/02_rx_demodulation.md` | DSO 캡처 및 DSP 복조 체인 |
| `concepts/03_omt_simulation.md` | OMT S-파라미터 시뮬레이션 |

---

## Quick Reference

### 하드웨어 요약

| Block | Model | Key specs |
|-------|-------|-----------|
| MZM | iXblue **MXAN-LN-40** | Vπ,DC ≈ 6.5 V; Vπ,RF@10GHz ≈ 6 V; X-cut; IL 3.5 dB; ER 25 dB; abs-max: optical +20 dBm, RF +28 dBm, bias ±20 V |
| UTC-PD | NICT **IOD-PMJ-13001** | J-band (270 GHz); 역방향 바이어스 ≈ −1 V (데이터시트 필수 확인); 현재 ~−7 mA, ~−10 dBm THz 출력 |
| ZBD | VDI **WR3.4ZBD** | 영바이어스; 감도 ≈ 2200 V/W; WR3.4 도파관 (220–330 GHz) |
| AWG | Keysight **M8194A** | 120 GSa/s; 45 GHz BW; 8-bit; ≤ 0.8 Vpp(se) / 1.6 Vpp(diff) |
| DSO | Keysight **UXR0404A** | 40 GHz BW; 256 GSa/s (4채널 동시, 속도 손실 없음); 10-bit; ENOB ≤ 8.7; 최대 2 Gpts |
| Lasers | 2× free-running DFB | f1 − f2 = 270 GHz (예: 193.410 THz & 193.140 THz) |

### 신호 체인

```
AWG(M8194A) → Amp(+29 dB) → 10 dB atten → MZM(MXAN-LN-40) → Coupler(+LD2)
  → EDFA → UTC-PD(IOD-PMJ-13001) → THz PA → OMT → Horn  ══RHCP══▶  target
  target ══LHCP══▶ Horn → OMT → THz LNA → ZBD(WR3.4) → LNA → DSO(UXR0404A)
```

### 주파수 계획

| 항목 | 값 |
|------|-----|
| THz 반송파 | **270 GHz** (= LD1 − LD2 비트) |
| SIM IF | **15 GHz** (데이터 대역 [10, 20] GHz, 10 GBaud 16-QAM, B = 5 GHz) |
| SSBI 바닥 | [0, 10] GHz → IF 조건: $f_{IF} > \frac{3B}{2}$ |
| 현재 브링업 | 10 GHz 단일 톤 (DSB), ZBD 출력 예상 = DC + 10 GHz 톤 |

### 핵심 바이어스 설정

| 항목 | 값 |
|------|-----|
| MZM DC 바이어스 | 직교점 ≈ **+3.25 V** (반드시 실측 후 적용) |
| MZM 변조 지수 | **m ≈ 0.2** → AWG ≈ **122 mVpp** |
| AWG → MZM 체인 | AWG → +29 dB 앰프 → −10 dB 감쇠기 → MZM (순이득 +19 dB) |
| UTC-PD 역바이어스 | **바이어스 먼저, 광입력 나중** (순서 절대 준수) |

---

## 1. System concept

Photonic THz full-duplex ISAC at **270 GHz (J-band)**. Core innovation:

- Two **free-running** DFB lasers beat on a UTC-PD to synthesize the 270 GHz carrier.
- A dual-circular-polarization **OMT** duplexes a single horn aperture: TX = RHCP,
  echo returns as LHCP (handedness flips on reflection) and routes to RX.
- The OMT's finite isolation deliberately **leaks ~25 dB-down SI** into RX. That
  leakage is used as a **self-homodyne LO** that pumps the **ZBD** square-law detector.
- Since SI leakage and echo share the same lasers, their phase noise is correlated
  and **cancels in the ZBD self-mixing** → no OFCG / PLL / digital carrier-phase
  recovery. Residual penalty `σ²_Δφ = 4π·Δν·τ` stays < 0.7 dB indoors.
- **SIM (subcarrier intensity modulation)** at 15 GHz IF keeps the data clear of the
  SSBI floor so a single HPF cleans it up.

---

## 2. Hardware inventory & datasheet-critical numbers

### 2.1 MZM — iXblue MXAN-LN-40
- X-cut LiNbO₃, analog intensity modulator, EO BW 28–30 GHz.
- **Vπ,DC** typ 6.5 V (max 7). **Vπ,RF@20GHz** typ 7 V (max 8). At 10 GHz, interpolate ≈ 6 V.
- IL 3.5 dB; DC extinction ratio ~25 dB; chirp ≈ 0 (X-cut).
- **Absolute max**: optical in +20 dBm; RF in +28 dBm; bias ±20 V; optical-in temp limits.
- S21 rolls off ~5 dB from DC→30 GHz (see datasheet p.5) — this is a real source of
  end-to-end frequency tilt even when the air channel is flat.

### 2.2 UTC-PD — NICT IOD-PMJ-13001
- J-band photonic THz source.
- Needs **reverse bias** (≈ −1 V typical — CONFIRM in NICT datasheet; do not assume).
- Currently ~ **−7 mA** photocurrent, ~ **−10 dBm** THz output.
- Saturation / space-charge sensitive; cap average photocurrent at datasheet max.
- **Never forward bias**: forward turn-on current → thermal runaway → permanent damage.

### 2.3 ZBD — VDI WR3.4ZBD
- Zero-bias Schottky detector, WR3.4 waveguide band (220–330 GHz).
- Responsivity ≈ **2200 V/W** (typ). Square-law.
- Sanity: −10 dBm (100 µW) in × 2200 V/W → 0.22 V → ≈ **−3 dBm** into 50 Ω.
  Against a −66 dBm SA noise floor that's ~63 dB margin — signal should be well clear.

### 2.4 AWG — Keysight M8194A
- 120 GSa/s, 45 GHz analog BW, **8-bit** DAC.
- **Amplitude ≤ 0.8 Vpp(se) / 1.6 Vpp(diff)**, voltage window −1.0…+2.5 V.
- 8-bit over 0.8 Vpp(se) → 1 LSB ≈ 3.1 mV. Using only ~122 mVpp wastes resolution
  (≈5 bits used). Prefer driving AWG higher and padding after the amp if the amp
  stays linear; otherwise accept the resolution hit.

### 2.5 DSO — Keysight UXR0404A
- 40 GHz BW, **256 GSa/s on all 4 channels simultaneously** (no interleave penalty),
  10-bit, ENOB ≤ 8.7, up to 2 Gpts.
- Multi-channel: **no sample-rate loss**. Use **CH1 + CH3** for best isolation.
- Memory is shared across active channels (2-ch → more depth/ch than 4-ch).

### 2.6 Lasers
- Two free-running DFBs, **f1 − f2 = 270 GHz**.
- Worked example: λ1 = 1550.891 nm (193.410 THz), λ2 = 1552.062 nm (193.140 THz).
- Tuning sensitivity (typical DFB): ~12.5 GHz/°C, ~1.25 GHz/mA. To hold 270 ± 1 GHz,
  control temperature to ≈ ±0.08 °C. Monitor beat on SA and trim TEC/current.

---

## 3. Bias & drive — the part most likely to bite

### 3.1 MZM DC bias (quadrature)
- Quadrature = max linearity for 16-QAM. V_quad = V_null + Vπ,DC/2 ≈ **+3.25 V** (typ),
  but **measure** via DC sweep (RF off, sweep bias, record optical power, find P_max/P_min;
  2·Vπ,DC = ΔV between them).
- **Use a real dither-lock bias controller** (e.g. iXblue MBC). A plain DC source has no
  feedback loop and cannot track LiNbO₃ thermal/aging drift. "ditherless" controllers
  still have active feedback — also fine. A bench DC supply alone is NOT equivalent.
- For this self-homodyne architecture, stay at **quadrature** (carrier retained) — do
  NOT go to null (carrier-suppressed) or the 270 GHz heterodyne beat weakens/vanishes.
- Dither tone: pick 1–10 kHz, far from the 10–20 GHz signal band so it never folds in.
- Never leave the bias electrode floating — ground it or keep it on the controller.

### 3.2 MZM RF drive (16-QAM linearity)
- Target modulation index **m ≈ 0.2** (range 0.1–0.3). `m = π·V_RF,peak / (2·Vπ,RF)`.
- At Vπ,RF(10 GHz) ≈ 6 V: V_RF,peak ≈ 0.76 V → **+7.7 dBm** into the MZM.
- Watch the V_peak vs Vpp trap: V_RF,peak = 1.4 V ⇒ 2.8 Vpp.
- Chain: AWG → **+29 dB amp** → **−10 dB atten** → MZM. Net = +19 dB.
  - For m = 0.2 (MZM +7.7 dBm) → **AWG ≈ −11.3 dBm = 122 mVpp**.
  - m = 0.1 → 61 mVpp; m = 0.3 → 204 mVpp. All within M8194A range.
  - **Amp must deliver +17.7 dBm** (before the 10 dB pad). Verify amp P1dB ≥ that with
    margin; a saturated amp pre-distorts before the MZM and no equalizer can undo it.
- If m is pushed to ~Vπ (m ≈ π/2 ≈ 1.57) the MZM cos² folds → heavy harmonics; OK-ish for
  a single tone (sidebands grow) but **destroys 16-QAM**. Keep small for QAM.

### 3.3 UTC-PD bias
- **Order matters**: apply reverse bias first (light off), check dark current, then ramp
  optical power up slowly while watching photocurrent. Bias-before-light avoids space-charge
  buildup with a weak field.
- Stay under the datasheet's max average photocurrent. Use a current-limited bias source.
- Confirm pinout (cathode/anode) so the diode is truly reverse-biased.

---

## 4. Signal-path physics (verified in conversation)

- MZM at quadrature with a 10 GHz tone → DSB: optical lines at f_c, f_c±10 GHz.
- Couple LD2 (270 GHz away) → UTC-PD square-law → THz lines at **260 / 270 / 280 GHz**
  (270 = carrier, ±10 GHz = sidebands).
- ZBD square-law on those three tones → **DC** (each self-beat) + **10 GHz** (carrier×each
  sideband, the wanted term) + **20 GHz** (USB×LSB). So the bring-up expectation
  "DC + 10 GHz tone" is correct.
- The 10 GHz term arrives via two paths (carrier×USB and carrier×LSB); their relative phase
  depends on MZM bias and LD relative phase, so holding quadrature maximizes it.

### Troubleshooting if the tone is buried at the SA noise floor
Expected ZBD out ≈ −3 dBm vs −66 dBm floor ⇒ should be visible. If not, check, in order:
1. UTC-PD reverse bias actually applied; photocurrent present (~ −7 mA seen).
2. Two-laser beat actually at 270 GHz (monitor/trim TEC & current).
3. **WR3.4 waveguide flange alignment** — small misalignment = tens of dB loss.
4. SA center freq at 10 GHz; RBW not so narrow the tone is skipped.
5. ZBD video output cabling/connectors (SMA), and DSO/SA band-limit settings.

---

## 5. DSO capture strategy

- No multi-channel sample-rate penalty → use CH1 + CH3 if two channels needed.
- For a ≤ 20 GHz baseband/IF signal, **lower fs and capture longer**:
  - `T_capture = Memory / fs`. e.g. 2 Gpts / 30 GSa/s ≈ 67 µs.
  - Benefits: finer FFT resolution (Δf = fs/N), more averaging, less post-proc data.
  - Constraints: keep `fs > 2 × f_max` (Nyquist); apply a band-limit filter before
    lowering fs so 40 GHz-wide front-end noise doesn't alias back in.
- Tone bring-up: fs ≈ 30 GSa/s, long record, band-limit ~20 GHz.
- Wideband 16-QAM ([10,20] GHz): fs ≈ 50–60 GSa/s.

---

## 6. Receiver DSP chain (implement in this order)

| # | Stage | Recommended method | Why |
|---|---|---|---|
| 0 | DC offset removal | subtract mean / DC-block | ZBD square-law has a strong DC term |
| 1 | Band-limit | FIR LP/BP to signal band | SNR up, anti-alias when fs lowered |
| 2 | Matched filter | RRC (paired with TX RRC) | min ISI, max SNR |
| 3 | **Frame sync** | **Zadoff-Chu preamble + cross-corr** | CAZAC → razor-sharp peak; batch-friendly offline |
| 4 | **Timing sync** | **Gardner TED** or oversample + polyphase interp | Gardner is carrier-phase independent; offline favors global interpolation search |
| 5 | Residual CFO/phase | pilot-aided linear phase fix | light — ZBD already cancels laser phase noise |
| 6 | Channel est. | **LS** (pilot); can be static | channel ~flat (indoor LoS), device tilt is LTI |
| 7 | Equalization | short FIR MMSE (3–5 tap) **or** 1-tap SC-FDE | flat-ish channel; grow taps/FFT only if needed; MMSE limits noise enhancement |
| 8 | Normalization | AGC / scale | 16-QAM carries amplitude info |
| 9 | Demap | 16-QAM Gray decision | bits out |
| 10 | Metrics | EVM / BER / SINR | performance |

Notes:
- **Nonlinear distortion is not equalizable** — fix by backing off MZM/PD/PA drive, not by
  adding taps.
- More taps (time domain) ⇔ larger FFT (SC-FDE): both raise frequency-selectivity-correcting
  power, but cost noise enhancement + estimation burden. Use only what the channel needs.
- Sensing path: cross-correlate TX vs RX SIM waveform → delay τ → `R = c·τ/2`; optional
  range-Doppler FFT for moving targets (at 270 GHz, 1.5 m/s ⇒ f_D ≈ 2.7 kHz, negligible
  within a symbol; ≈10° over 1024 symbols, single complex-multiply correction).

### Frame design suggestion
```
[ Zadoff-Chu preamble | known pilot block | 16-QAM data payload | ... ]
        ↑ frame+timing sync         ↑ channel est + residual phase
```

---

## 7. Link-budget / SINR model (for the simulator)

`SINR = P_sig / (P_N,LNA + P_N,ZBD + P_RIN + P_SSBI + P_Q)`

- `P_sig = 4·R²·G²·P_SI·P_Echo`
- `P_N,LNA = 4·R²·G²·P_SI·N_LNA`, `N_LNA = kT₀·B·NF` (NF = 8 dB) — dominant term
- `P_N,ZBD = NEP² · B`, NEP ≈ 5 pW/√Hz
- `P_RIN  = RIN · P_SI² · B`, RIN ≈ −150 dBc/Hz (DFB)
- `P_SSBI < −40 dB` rel. to signal after 12 GHz HPF
- `P_Q` negligible for ≥ 8-bit ADC
- **Limit**: as P_SI grows, SINR → `P_Echo / N_LNA` (LNA-NF bound, independent of ZBD NEP).
- OMT isolation "Goldilocks" window **[20, 30] dB**: below → LNA compresses; above → ZBD
  under-pumped. Measured OMT ≈ 24.8 dB sits ~4.8 dB below LNA P1dB — good.

---

## 8. TODO for Claude Code

코드는 `projects/THz_ISAC/code/` 하위에 저장합니다.

- [ ] **수신기 DSP** (`code/dsp/`): 0–10단계를 Python 모듈로 구현. UXR 캡처(CSV/HDF5) 입력 → EVM/BER + 성상도 출력.
- [ ] **링크 버짓 시뮬레이터** (`code/sim/`): §7 SINR 모델 구현. 범위·OMT 격리도·레이저 선폭 스윕. 통신 범위 ≈ 3.8 m, 레이더 범위 ≈ 1.9 m 재현.
- [ ] **파형 생성기** (`code/awg/`): SIM 파형 생성 (10 GHz 톤; 10 GBaud 16-QAM @ 15 GHz IF, RRC). M8194A 포맷 출력. §3.2의 m 및 Vpp 한계 적용.
- [ ] **캡처+DSP 자동화** (`code/bench/`): AWG 로드 → DSO 캡처 → 오프라인 DSP 오케스트레이션.
- [ ] 광출력 증가 전 **NICT UTC-PD 데이터시트 역바이어스 및 최대 광전류 한계 확인**.

## 9. Style / preferences for any writing tasks
- IEEEtran 2-column; concise active voice; no redundant equations; cross-reference instead
  of repeating; siunitx units; hedge experimentally-unconfirmed claims. (A paper draft and
  `ref.bib` already exist separately.)
