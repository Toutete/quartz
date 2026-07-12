# Photonic THz Full-Duplex ISAC — Signal Model & SI-Referenced Range Detection

> Consolidated technical note. Covers the system, the ZBD signal model, the SI /
> echo / homodyne structure, the origin of amplitude and range-profile fluctuations,
> and the full derivation of the single-shot **SI-normalized** range profile,
> mapped line-by-line to the simulation code (`isac_unified_gui.py`).

---

## 1. System overview

Cost-effective photonic THz full-duplex ISAC at **J-band (270 GHz)**. Two
free-running DFB lasers beat on a UTC-PD to synthesize the carrier; a
dual-circular-polarization OMT duplexes a single aperture (RHCP transmit / LHCP
echo). The OMT's finite isolation deliberately leaks a controlled self-interference
(SI) that acts as a **self-homodyne local oscillator** pumping a zero-bias detector
(ZBD). SIM (subcarrier intensity modulation) places data at an IF clear of SSBI.

**Signal chain**

```
AWG -> (+29 dB amp) -> (-10 dB atten) -> MZM -> Coupler(+LD2)
   -> WSS(SSB) -> EDFA -> UTC-PD -> THz PA -> OMT -> Horn ==RHCP==> target
   target ==LHCP echo==> Horn -> OMT -> THz LNA -> ZBD -> DSO
```

**Key hardware**

| Block | Model | Notes |
|---|---|---|
| MZM | iXblue MXAN-LN-40 | X-cut; Vπ,DC≈6.5 V; Vπ,RF@20GHz≈7 V; abs-max opt +20 dBm / RF +28 dBm / bias ±20 V |
| UTC-PD | NICT IOD-PMJ-13001 | reverse bias first, then ramp light; ~−7 mA, ~−10 dBm THz |
| ZBD | VDI WR3.4ZBD | zero-bias, responsivity ≈2200 V/W, 220–330 GHz |
| AWG | Keysight M8194A | 120 GSa/s, ≤0.8 Vpp(se)/1.6 Vpp(diff) |
| DSO | Keysight UXR0404A | 40 GHz BW, 256 GSa/s all-4-ch, 10-bit |
| Lasers | 2× free-running DFB | f1−f2 = 270 GHz (e.g. 193.410 & 193.140 THz) |

---

## 2. Frequency plan and SSB

- THz carrier = OMT centre **270 GHz**; both THz tones inside OMT band (245–295 GHz).
- **SSB chosen** (via WSS filtering) to avoid direct-detection power fading and use
  the band efficiently. SSB is a standard IM-DD practice, not a novelty by itself.
- Example (from measured optical spectrum): LO = 193.13 THz, MZM carrier = 193.41 THz,
  IF ≈ 12 GHz; WSS keeps the lower sideband. UTC-PD then produces THz tones at
  **268 GHz (LSB beat)** and **280 GHz (carrier beat)**, midpoint 274 GHz, IF = 12 GHz.
- SSBI-avoidance guard for the general SIM case: `f_IF > 3B/2`.

**CSPR (carrier-to-signal power ratio).** `CSPR ∝ 1/m²` where `m` is the MZM
modulation index. Typical optimum for IM-DD SIM is **≈ 6–13 dB** (e.g. a companion
ETRI paper uses ~13 dB at m≈0.2). A too-high CSPR (e.g. 20 dB, m≈0.1) starves the
data sideband and makes the link-budget SNR look far better than the measured EVM.
For 32-QAM the optimum sits slightly higher (≈13–16 dB) because the denser
constellation needs more linearity; verify by a CSPR sweep against EVM.

---

## 3. ZBD signal model

### 3.1 Input

$$V_{ZBD}(t) = V_{SI}(t) + V_{echo}(t)$$

$$V_{SI}(t)=\alpha_{SI}\,s(t)\,e^{j(\omega_c t+\phi(t))},\qquad
  V_{echo}(t)=\beta_{ec}\,s(t-\tau)\,e^{j(\omega_c(t-\tau)+\phi(t-\tau))}$$

- `α_SI = 10^(−ISO/20)` — SI amplitude (OMT isolation)
- `β_ec = 10^(−L_radar/20)` — echo amplitude (radar equation)
- `ω_c` — 270 GHz carrier (free-running → drifts)
- `φ(t)` — laser phase noise; `τ = 2R/c` — round-trip delay

### 3.2 Square-law output

$$V_{out}=\mathcal{R}\,|V_{SI}+V_{echo}|^2
  =\mathcal{R}\big[\underbrace{|V_{SI}|^2}_{(A)}+\underbrace{|V_{echo}|^2}_{(B)}
   +\underbrace{2\,\mathrm{Re}\{V_{SI}V_{echo}^*\}}_{(C)}\big]$$

| Term | Expression | Delay | Phase noise | Role |
|---|---|---|---|---|
| (A) SI self | `α_SI²|s(t)|²` | 0 | `φ(t)−φ(t)=0` cancels | **0 m peak** |
| (B) echo self | `β_ec²|s(t−τ)|²` | τ | cancels | weak (`∝β²`) |
| (C) cross | `2α_SI β_ec Re{ s(t)s*(t−τ) e^{j(ω_c τ+Δφ)} }` | τ | `Δφ=φ(t)−φ(t−τ)` | **homodyne target peak** |

### 3.3 Homodyne gain (why SI helps, and what it is NOT)

The **target peak** at delay τ is `(B)+(C)`:

$$P_{target}\propto \beta_{ec}^2 + 2\alpha_{SI}\beta_{ec}.$$

- SI is **not required** for down-conversion — the echo's own carrier×sideband beat
  (term B, `∝β_ec²`) already yields an IF. But it is weak.
- With SI present and `α_SI ≫ β_ec`, the cross term (C, `∝α_SI β_ec`) dominates:
  the SI acts as a strong LO that **linearly** amplifies the weak echo. Gain `≈ α_SI/β_ec`,
  most decisive at long range (weak echo).
- **Range-decay signature:** homodyne (SI×echo) ⇒ `P_target ∝ 1/R²`;
  self-detection (echo²) ⇒ `1/R⁴`. Fitting the decay exponent `n` (≈2 vs ≈4)
  distinguishes them without removing SI — SI cannot be physically switched off in
  a monostatic link, so a **target-distance sweep with SI fixed** is the practical test.

### 3.4 Phase-noise cancellation

`Δφ(τ)=φ(t)−φ(t−τ)` has variance `σ² = 4π·Δν·τ`. For indoor range this is small
(<0.7 dB penalty). Terms (A) and (B) cancel phase noise exactly (same-time products);
only (C) keeps a residual `Δφ(τ)` that vanishes as `τ→0`. This is the self-homodyne
mechanism: **because SI and echo share the same lasers, their phase noise is
correlated and cancels in the ZBD**, so no OFCG/PLL/CPR is needed.

**Verification without linewidth hardware:** if measured `EVM ≈ 1/√SNR`
(EVM tracks the SNR prediction), the channel is AWGN-dominated and phase noise is
NOT dominant — i.e. self-homodyne is working. This is stronger than "no penalty at
low symbol rate" alone (which could merely reflect low-rate insensitivity).

---

## 4. Effective RCS when the target is the RX antenna

The radar RX (C2) path is: `UTC-PD → OMT → (TX ant → wireless → RX ant(=target) →
wireless → TX ant) → OMT → LNA → ZBD → DSO`. Matching the measured SI/target peak
ratio of **~5–10 dB** required `σ ≈ 3 m²` in the code's plain radar equation

$$L_{radar}=10\log_{10}\frac{(4\pi)^3R^4}{G_tG_r\lambda^2\sigma}.$$

That is **not** a physical scattering RCS: a 25 dBi corrugated horn's structural RCS
is ~0.01 m². The resolution:

$$\sigma_{eff}\approx \sigma_{struct}\times G_{target}\;\Rightarrow\;
  3\ \mathrm{m}^2 \approx 0.01\ \mathrm{m}^2 \times 316\ (25\ \mathrm{dBi}).$$

The RX-antenna **re-radiation gain (25 dBi)** is folded into σ. The echo magnitude
(hence SI/target ratio) is reproduced correctly, but the σ label is an *effective*
value. In a paper, state it as "target = RX horn (25 dBi); effective RCS = structural
RCS × antenna re-radiation gain", not as a bare 3 m² RCS.

### Peak-ratio formula (verified against code)

$$\frac{P_{target}}{P_{SI}}\Big|_{dB}
  =10\log_{10}\frac{\beta_{ec}^2+2\alpha_{SI}\beta_{ec}}{\alpha_{SI}^2}
  \;\approx\; 6 - L_{radar} + \mathrm{ISO}\quad(\text{homodyne-dominant}).$$

Inverting for effective RCS:

$$\sigma_{eff}=\frac{(4\pi)^3R^4}{G_tG_r\lambda^2}\,
  10^{\frac{1}{10}\left(\frac{P_{target}}{P_{SI}}|_{dB}-6-\mathrm{ISO}\right)}.$$

Measured −5…−10 dB ⇒ `σ_eff ≈ 1.3–4 m²`, consistent with the 3 m² fit.

---

## 5. Amplitude fluctuation vs range-profile fading (two DIFFERENT effects)

Two distinct fluctuations were observed and must not be conflated.

### 5.1 Slow IF amplitude fluctuation (2–5 dB, seconds)

- **Not** DSB power fading (persisted after SSB), **not** polarization (all-PM fibre),
  **not** phase noise (slow, and low-symbol-rate EVM stable), **not** a few-hundred-MHz
  drift × device slope (quantitatively too small).
- **Structurally, the self-homodyne link is stable at a fixed geometry** if TX optical
  power is stable: `A_SI, A_ec ∝ P_TX`. So fluctuation enters only through TX optical
  power (laser / EDFA / UTC-PD coupling). ZBD square-law can amplify it (`|·|²`), but
  the root cause is the source.
- **Evidence it is a device issue, not the architecture:** swapping the laser reduced
  it from ~5 dB to ~2 dB. A structural cause could not be fixed by a component swap.
  Remaining ~2 dB is residual laser RIN/drift + UTC-PD photocurrent drift
  (observed 4 → 3.6 mA over ~10 min, thermal warm-up).

### 5.2 Range-profile peak fading (up to ~25 dB, per capture)

Different, larger effect. The target peak is the **cross term**
`∝ cos(ω_c τ + Δφ)`. At 270 GHz, `ω_c τ = 1800·2π` at 1 m, so a **few-hundred-MHz
carrier drift rotates this phase by hundreds of degrees**:

```
100 MHz drift → 240°,   300 MHz drift → 720°
```

Even at a fixed geometry (τ constant), the free-running carrier `f_c` drift makes
`cos(ω_c τ)` swing between +1 and 0, so the single-shot peak fades by tens of dB and
can sink into noise. This is coherent fading — a structural property of
**free-running + self-homodyne + 270 GHz** — reproduced in simulation. It is not a
device defect. The fix is signal processing (next section).

> Note the apparent paradox resolved: the same drift is **weak on IF amplitude**
> (flat device response) but **strong on the correlation phase** (`ω_c τ` is huge).

---

## 6. SI-referenced (SI-normalized) single-shot range detection

### 6.1 Why a channel frequency response (CFR)

A delay τ appears in the frequency domain as a **linear phase**:

$$s(t-\tau)\ \leftrightarrow\ S(f)\,e^{-j2\pi f\tau}.$$

Define the CFR by dividing the received spectrum by the transmitted one,
`H(f) = Y(f)/S(f)` (this is exactly what the code's `_estimate_lfm_cfr` does with the
LFM/SIM reference). Range then lives in the **phase slope** of `H(f)`, and — crucially —
SI normalization becomes a simple division.

For a single capture, the cross-term CFR is

$$H(f)=\underbrace{\alpha_{SI}\,e^{j\psi}}_{\text{SI},\ \tau=0\ \Rightarrow\ \text{flat}}
      +\underbrace{\beta_{ec}\,e^{j\psi}\,e^{-j2\pi (f+f_c)\tau}}_{\text{echo},\ \tau},$$

where `ψ` is the **common carrier phase offset of that capture** and `f_c` the
(drifting) carrier. Both SI and echo carry the SAME `e^{jψ}` — same instant, same carrier.

### 6.2 The problem in CFR form

The echo phase is `−2π(f_c + f)τ`. The `f_c τ` part drifts capture-to-capture and,
combined with `ψ`, produces the coherent fading of §5.2.

### 6.3 SI normalization (the key step)

SI is the **frequency-flat** part of `H(f)` (because `τ_SI ≈ 0`), so estimate it as the
weighted mean and divide:

$$H_{SI}=\frac{\sum_f w\,H(f)}{\sum_f w}\approx\alpha_{SI}e^{j\psi},
\qquad
\boxed{\tilde H(f)=\frac{H(f)}{H_{SI}}-1=\frac{\beta_{ec}}{\alpha_{SI}}\,e^{-j2\pi(f+f_c)\tau}}.$$

The common phase `e^{jψ}` **cancels in the division** — the per-capture fading is gone.

### 6.4 Carrier-drift immunity of the range estimate

$$\angle\tilde H(f)=\underbrace{-2\pi f\tau}_{\text{range slope}}
   \underbrace{-\,2\pi f_c\tau}_{\text{constant offset}}
\;\Rightarrow\;
\hat\tau=-\frac{1}{2\pi}\frac{d\,\angle\tilde H}{df},\quad \hat R=\frac{c\hat\tau}{2}.$$

`f_c τ` is constant in `f`, so it drops out of the slope: **range is immune to carrier
drift.**

### 6.5 Delay-matched profile (what the code plots)

Remove the residual DC, then delay-match:

$$\tilde H'(f)=\tilde H(f)-\frac{\sum_f w\,\tilde H}{\sum_f w},\qquad
P(\tau')=\frac{1}{\sum_f w}\Big|\sum_f w(f)\,\tilde H'(f)\,e^{j2\pi f\tau'}\Big|.$$

`P(τ')` peaks at `τ'=τ` ⇒ `R̂ = cτ/2`. Detection confidence:

$$\gamma=\frac{\big|\sum_f w\,e^{j\angle\tilde H'(f)}\big|}{\sum_f w}\in[0,1].$$

### 6.6 Single-shot completeness (num_frames = 1)

Everything above uses **one** capture's `H(f)`:

```
one capture H(f)
  -> H_SI = weighted mean            (extract SI)
  -> residual = H/H_SI − 1           (normalize; ψ cancels)
  -> DC removal
  -> delay matching -> peak -> range
  -> coherence γ (confidence)
```

No frame integration ⇒ **a moving target is not smeared**; the instantaneous τ is
captured. This is the required single-shot, motion-tolerant mode, and it works on the
already-recorded data (no re-measurement needed).

> Clarification on "multi-frame": the code also has an optional loop that splits ONE
> capture into several time frames and phase-aligns them via the SI phase
> (`corr·e^{−j·si_phase}`). That is intra-capture frame averaging (assumes a static
> target during the capture), **not** multi-capture averaging. For a moving target use
> `num_frames = 1` and the CFR path above.

---

## 7. Equation ↔ code map (`isac_unified_gui.py`)

| Quantity (equation) | Code | Line |
|---|---|---|
| `V_ZBD = V_SI + V_echo` | `v_si + v_echo` | 2681, 2686 |
| `α_SI = 10^(−ISO/20)`, `β_ec = 10^(−L/20)` | `alpha_si`, `beta_echo` (voltage) | 2677, 2678 |
| `V_out = R|V_ZBD|²` | `p_inst=|v_rx|²/50`, `v_det=R·p_inst` | 2718, 2719 |
| CFR `H(f)=Y/S` | `_estimate_lfm_cfr` | 10129 |
| `H_SI = Σw·H/Σw` (flat SI) | `si_ref = Σw·hc/Σw` | 2382 |
| `residual = H/H_SI − 1` | `residual = hc/si_ref − 1.0` | 2393 |
| DC removal | `residual −= Σw·residual/Σw` | 2394 |
| delay matching `Σ residual·e^{j2πfτ'}` | `amp = Σ(w·residual)·e^{j2πfτ'}` | 2401–2402 |
| `R̂ = c·τ̂/2` | `tau=r/(c/2)`, `peak_idx=argmax|amp|` | 2395, 2405–2406 |
| coherence `γ` | `coherence=|Σw·phase_unit|/Σw` | 2407–2408 |
| phase-slope differential range | `_differential_delay_from_cfr` | 10471 |
| target/SI ratio | `20log10(target/zero)` | 2963 |
| (intra-capture) SI phase align | `corr·e^{−j·si_phase}` | 2940–2942 |

Code adds practical robustness beyond the equations: amplitude-reliability weights,
DC re-removal, MAD-based robust phase-slope fit, chunked frequency×delay evaluation,
and the `SI Phase Coherence` quality readout.

---

## 8. Measurement-result narrative (for the paper)

1. **EVM vs photocurrent (16- & 32-QAM).** Monotonic EVM decrease up to 7 mA (stopped
   for device protection) ⇒ **SNR-limited within the measured range**. Showing 32-QAM
   deliberately proves nonlinearity headroom exists and SNR is the limit. Ties to
   self-homodyne: SNR-limited ⇒ phase noise / nonlinearity are not the floor.
2. **SNR/EVM vs distance (comm & radar).** Comm is SNR-limited (1/R²); radar reaches
   further via matched-filter processing gain `G_p = T·B` (radar SNR = SNR_in·G_p,
   independent of B, ∝ T) plus homodyne gain — even with DFT-s-OFDM's sensing
   drawbacks. Frame honestly: state the DFT-s-OFDM limitation and still show the reach.
3. **EVM + range resolution vs bandwidth.** Resolution `c/2B` may be given as a
   *calculated* value if labelled clearly and backed by at least one measured range
   profile (item 4). Meaningful mainly if 20 GBaud is an EVM/FEC limit, not an
   equipment limit.
4. **Range profile: 2 vs 20 GBaud.** Detecting a 7 mm RX shift validates `c/2B`.
5. **EVM vs FDE taps.** Saturation tap count reveals near-flat channel; the EVM floor
   is the SNR-limited residual. (1-tap SC-FDE ≈ FFT-size taps; grow only as selectivity
   demands; nonlinear distortion is NOT equalizable.)
6. **Full-duplex.** Simultaneous CH1(comm)+CH2(radar) capture, plus "no EVM/profile
   degradation under simultaneous operation" and OMT isolation, proves STAR operation.
7. **Circular polarization.** Co-/cross-pol isolation, axial ratio, and RHCP→LHCP
   handedness flip on reflection.
8. **Free-running stability.** `EVM ≈ 1/√SNR` (AWGN-dominant) + laser-swap improvement
   (5→2 dB) + no OFCG/PLL/CPR. Range fading handled by the SI-referenced single-shot
   processing of §6, presented with coherence γ and, where relevant, detection
   probability rather than a single fragile peak.

---

## 9. FEC / EVM thresholds (reference)

| Modulation | BER 1e-3 | 7% HD-FEC (3.8e-3) | 20% SD-FEC (2.4e-2) |
|---|---|---|---|
| 16-QAM | −16.5 dB / 15.0% | −15.0 dB / 17.8% | −11.7 dB / 26.0% |
| 32-QAM | −19.3 dB / 10.9% | −17.8 dB / 12.9% | −15.0 dB / 17.8% |

Symbol-rate examples (net, after FEC): 16-QAM 70 Gb/s @ 7% HD ⇒ 18.7 GBaud;
32-QAM 80 Gb/s @ 20% SD ⇒ 19.2 GBaud; 32-QAM 70 Gb/s ⇒ 14.98 GBaud (7% HD) /
16.8 GBaud (20% SD).

---

## 10. One-paragraph summary

Starting from `V_ZBD = V_SI + V_echo`, the ZBD square-law yields a homodyne cross term
whose CFR is `H(f) = α_SI e^{jψ} + β_ec e^{jψ} e^{−j2π(f+f_c)τ}`. Because SI and echo
share the same instantaneous carrier phase, **dividing by the flat SI component,
`H̃ = H/H_SI − 1 = (β_ec/α_SI) e^{−j2π(f+f_c)τ}`, cancels the common phase `e^{jψ}`**
(removing the tens-of-dB coherent fading) and leaves a pure delay term whose
**phase slope gives range, immune to carrier drift** (the constant `f_c τ` drops out of
the slope). The whole procedure completes on a **single capture** (`num_frames=1`), so
it needs no re-measurement and does not smear a moving target. The key idea — and the
system's novelty — is to use the self-interference not as an impairment to be cancelled
but as a **built-in phase reference**, achieving stable, instantaneous range detection
with free-running lasers and a ZBD, without OFCG, PLL, or wavemeter.
