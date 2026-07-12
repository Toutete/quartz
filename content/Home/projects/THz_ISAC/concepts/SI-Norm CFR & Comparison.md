
## Part 1 — SI-normalized range detection (code-applied equations)

### 1.1 ZBD input and square-law output

$$V_{ZBD}(t)=V_{SI}(t)+V_{echo}(t)$$

$$V_{SI}=\alpha_{SI},s(t),e^{j(\omega_c t+\phi(t))},\qquad V_{echo}=\beta_{ec},s(t-\tau),e^{j(\omega_c(t-\tau)+\phi(t-\tau))}$$

$$V_{out}=\mathcal R,|V_{ZBD}|^2 =\mathcal R\big[\underbrace{\alpha_{SI}^2|s(t)|^2}_{(A)\ \text{SI},\ \tau=0} +\underbrace{\beta_{ec}^2|s(t-\tau)|^2}_{(B)\ \text{echo}} +\underbrace{2\alpha_{SI}\beta_{ec},\mathrm{Re}{s(t)s^*(t-\tau)e^{j(\omega_c\tau+\Delta\phi)}}}_{(C)\ \text{homodyne}}\big]$$

with `α_SI = 10^(−ISO/20)`, `β_ec = 10^(−L_radar/20)`, `τ = 2R/c`, `Δφ = φ(t)−φ(t−τ)`.

### 1.2 CFR estimate (single capture)

$$H(f)=\frac{Y(f)}{S(f)} =\underbrace{\alpha_{SI}e^{j\psi}}_{\text{flat, }\tau\approx0} +\underbrace{\beta_{ec}e^{j\psi}e^{-j2\pi(f+f_c)\tau}}_{\text{echo}}$$

`ψ` = common per-capture carrier phase, `f_c` = drifting carrier. SI and echo carry the **same** `e^{jψ}`.

### 1.3 SI normalization (the key step)

$$H_{SI}=\frac{\sum_f w,H(f)}{\sum_f w}\approx\alpha_{SI}e^{j\psi},\qquad \boxed{;\tilde H(f)=\frac{H(f)}{H_{SI}}-1=\frac{\beta_{ec}}{\alpha_{SI}},e^{-j2\pi(f+f_c)\tau};}$$

Dividing by the flat SI cancels `e^{jψ}` → **coherent fading removed**. DC re-removal: `H̃' = H̃ − mean_w(H̃)`.

### 1.4 Range estimate — two equivalent readouts

**(a) Phase-slope** (drift-immune; `f_c τ` is constant in `f`, drops out of the slope):

$$\hat\tau=-\frac{1}{2\pi}\frac{d,\angle\tilde H}{df},\qquad \hat R=\frac{c\hat\tau}{2}$$

**(b) Delay-matched profile** (what the GUI plots):

$$P(\tau')=\frac{1}{\sum_f w}\Big|\sum_f w(f),\tilde H'(f),e^{j2\pi f\tau'}\Big|,\qquad \hat R=\frac{c}{2},\arg\max_{\tau'}P(\tau')$$

**Confidence:** coherence `γ = |Σ w e^{j∠H̃'}| / Σ w ∈ [0,1]`.

### 1.5 Single-shot property

All of the above use **one** capture's `H(f)` (`num_frames = 1`): no frame integration, so a moving target is not smeared, and no re-measurement is needed.

### 1.6 Code map (`isac_unified_gui.py`)

|Equation|Code|Line|
|---|---|---|
|`H = Y/S`|`_estimate_lfm_cfr`|10129|
|`H_SI = Σw·H/Σw`|`si_ref`|2382|
|`H̃ = H/H_SI − 1`|`residual`|2393|
|DC removal|`residual −= mean_w`|2394|
|`P(τ') =|Σ w H̃' e^{j2πfτ'}|`|
|`R̂ = c τ̂/2`, argmax|`peak_m`|2405–2406|
|`γ`|`coherence`|2407–2408|
|phase-slope `τ̂`|`_differential_delay_from_cfr`|10471|

---

## Part 2 — Complexity/cost vs the standard matched filter

The classical monostatic pipeline is **matched filter (pulse compression)**: correlate the received signal with the known TX waveform; the peak position gives τ. It assumes a coherent transmitter/receiver (a stable, known carrier phase).

| Aspect             | Matched filter (classical)                  | SI-normalized CFR (this work)                                 |
| ------------------ | ------------------------------------------- | ------------------------------------------------------------- |
| Core op            | 1 correlation `Σ y·s*`                      | CFR division `H/H_SI` + phase slope / 1 IDFT                  |
| Ops/scale          | `O(N log N)` (FFT correlation)              | `O(N log N)` CFR + `O(N)` division + `O(N log N)` delay match |
| Extra state        | none                                        | SI reference `H_SI` (weighted mean, `O(N)`)                   |
| Carrier assumption | **coherent, known/stable phase**            | **free-running OK** — SI supplies the phase reference         |
| Extra hardware     | often OPLL / comb / shared-LO for coherence | **none** — SI leakage is the built-in LO                      |
| Per-capture fading | severe if carrier drifts                    | removed by `H/H_SI`                                           |
| Moving target      | fine (single shot)                          | fine (single shot)                                            |

**Bottom line:** the _arithmetic_ complexity is essentially the same order as a matched filter (both dominated by FFT-length transforms). The saving is in **hardware/coherence cost**: SI normalization replaces the phase-locking hardware (OPLL/comb/wavemeter) that a coherent matched filter would otherwise need at 270 GHz with free-running lasers. The added software cost is one `O(N)` division and the SI mean — negligible.

---

## Part 3 — LFM-QAM vs OFDM vs DFT-s-OFDM (waveform + range-detection comparison)

### 3.1 How each does range detection

- **LFM-QAM** — a linear-FM chirp carries QAM data. Sensing = **de-chirp / matched filter (stretch processing)**: mix with a reference chirp, the beat frequency maps to range. Very mature radar processing; large time-bandwidth product gives high processing gain. Comms rides on the chirp (lower spectral efficiency than pure data waveforms).
- **OFDM** — data on many subcarriers. Sensing = **channel division** in frequency: `H(f) = Y(f)/X(f)` per subcarrier, then IDFT over subcarriers → range profile (the "symbol-division" / Sturm-Wiesbeck method). Naturally data-independent after division; clean range–Doppler via 2-D DFT. High PAPR.
- **DFT-s-OFDM** — OFDM with a DFT precoder (SC-FDMA); **low PAPR** (good for power efficiency / UE / photonic front-ends). Sensing = same frequency-domain channel-division idea as OFDM, but the extra DFT spreading must be inverted, so the effective per-subcarrier SNR and sidelobe behaviour differ; range processing is a bit more involved and its sensing sidelobes are less ideal than plain OFDM.

### 3.2 Comparison table

| Criterion                    | LFM-QAM                   | OFDM                                  | DFT-s-OFDM                         |
| ---------------------------- | ------------------------- | ------------------------------------- | ---------------------------------- |
| Range method                 | de-chirp / matched filter | subcarrier channel division + IDFT    | precoder-inverted channel division |
| Processing gain              | very high (chirp TBWP)    | high (N subcarriers)                  | high, minus spreading overhead     |
| PAPR                         | low–moderate              | **high**                              | **low** (its main advantage)       |
| Sensing sidelobes            | excellent (chirp)         | excellent                             | slightly worse (spreading)         |
| Comms spectral eff.          | moderate                  | high                                  | high                               |
| Data-independence of profile | good                      | **very good** (division removes data) | good after de-spreading            |
| Doppler / moving target      | excellent (classic radar) | good (2-D DFT)                        | good but more processing           |
| Impl. complexity             | moderate                  | moderate                              | higher (extra DFT stages)          |
| Best fit                     | radar-centric ISAC        | comms-centric ISAC, rich sensing      | uplink / power-limited nodes       |

### 3.3 Where the SI-normalized method sits

The SI-normalized CFR method is **waveform-agnostic** — it is a _receiver-side_ technique layered on top of whatever waveform provides the CFR `H(f)`:

- With **LFM-QAM** (this system's SIM/chirp path), `H(f)` comes from the de-chirp/CFR estimate; SI normalization then removes the free-running carrier phase before the phase-slope/delay-match readout.
- With **OFDM / DFT-s-OFDM**, `H(f)` is already the per-subcarrier channel; the same `H/H_SI − 1` step would remove a common carrier-phase term in a self-homodyne, free-running front-end.

So relative to the three waveforms, this work does **not** replace their range methods; it **adds a self-homodyne phase-reference layer** that lets any of them run with free-running lasers and a ZBD — trading the usual coherence hardware (OPLL/comb) for a one-line division `H/H_SI`.

### 3.4 Accuracy notes

- Range **resolution** for all three is set by bandwidth, `δR = c/2B` — the waveform choice does not change this; it changes sidelobes, PAPR, and processing gain.
- Range **accuracy** (peak/slope estimation) improves with SNR and processing gain; LFM's large TBWP and OFDM's clean division give the best raw sidelobe behaviour, DFT-s-OFDM slightly worse due to spreading.
- The SI-normalized step does not improve resolution; it **restores** the detectable peak that free-running carrier drift would otherwise fade away, and makes the range estimate **drift-immune**. Its accuracy gain is in _robustness/stability_, not in the fundamental `c/2B` limit.

---

## One-line takeaways

1. **Arithmetic cost** of SI-normalized detection ≈ a matched filter (FFT-order); the real saving is replacing coherence hardware with a `H/H_SI` division.
2. **LFM-QAM** = best radar heritage/sidelobes; **OFDM** = cleanest data-independent division, high PAPR; **DFT-s-OFDM** = low PAPR for power-limited nodes, slightly harder sensing.
3. Resolution is `c/2B` for all; SI normalization adds **drift immunity and fade removal**, not resolution — a receiver-side layer usable with any of the three waveforms in a free-running self-homodyne front-end.