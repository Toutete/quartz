

Corrected and consolidated. Separates (A) limits inherent to CFR / channel-division ranging itself, from (B) limits specific to this photonic-THz self-homodyne system. Supersedes the earlier "SI-sidelobe-limited range" framing, which assumed a raw matched filter; the CFR-normalized path removes SI before profiling.

---

## 0. Key correction: SI has NO sidelobe problem in the CFR-normalized path

Raw matched filter: SI is a huge 0 m peak whose sidelobes mask weak targets.

CFR-normalized path: SI is the **flat component** of `H(f)`, extracted as `H_SI = Σw·H / Σw` and removed by the `−1`:

```
H(f)     = α_SI              + Σ_k β_k e^{−j2π(f+f_c)τ_k}
H/H_SI   = 1                 + Σ_k (β_k/α_SI) e^{−j2π(f+f_c)τ_k}
H/H_SI−1 =                     Σ_k (β_k/α_SI) e^{−j2π(f+f_c)τ_k}   ← SI GONE
```

So the range profile contains **no SI peak and no SI sidelobe**. The range limit is set by **noise**, as in a normal radar — not by an SI sidelobe floor. Increasing SI (homodyne gain) is then purely beneficial, up to the dynamic-range caveat below.

---

## A. Limits inherent to CFR / channel-division ranging

These apply to any `H(f)=Y/X` ranging method (Sturm–Wiesbeck family), not just ours.

1. **Resolution = c/2B.** Set by bandwidth. IDFT/phase-slope don't change it.
    
2. **Data-dependent sidelobes (payload ranging).** If ranging on random data symbols, the division `Y/X` amplifies noise where `|X|` is small and non-constant-modulus constellations raise sidelobes. Mitigations: pilots/constant-modulus, or mismatched filters (ROI-MMF, Yang et al. arXiv:2605.16831, 2026).
    
3. **Phase-slope readout assumes a single dominant target.** For `K>1`, `∠(Σ_k β_k e^{−j2πfτ_k})` is nonlinear in `f`, so a single slope is ambiguous. → Use the IDFT/delay-matching readout instead, which resolves multiple targets as separate sinc peaks at each `τ_k` (this is the standard Sturm–Wiesbeck output). **So "single-target" is a limit of the phase-slope readout, not of CFR itself.**
    
4. **Doppler needs a slow-time dimension.** One CFR gives range only. Velocity requires multiple symbols/blocks and a 2-D DFT (fast-time → range, slow-time → Doppler), per Sturm–Wiesbeck. A **single-shot** capture (num_frames=1) therefore trades away Doppler. This is a _design choice_, not a CFR defect: multi-symbol processing recovers Doppler at the cost of the single-shot / moving-target-no-smear property.
    
5. **Delay ambiguity / unambiguous range.** IDFT over discrete subcarriers gives an unambiguous delay window set by subcarrier spacing (`τ_max = 1/Δf`); beyond it, range wraps. Standard OFDM-radar constraint.
    
6. **CP / max-range coupling (if OFDM-framed).** If the waveform is OFDM/DFT-s-OFDM, round-trip delay beyond the cyclic prefix breaks orthogonality (ISI/ICI), capping sensing range independent of SNR. (Not applicable if using an LFM/SIM CFR without CP.)
    

---

## B. Limits specific to this system

### B1. Extraction / near-range / delay ambiguity

7. **H_SI extraction needs `B·τ ≫ 1`, and fails at `τ = k/Δf`.** SI is separated as the flat part of `H(f)`. Two failure modes: (a) **near-range blind zone** — a target too close to zero delay (τ→0) is also nearly flat and leaks into `H_SI`, so it cannot be separated (scale `τ ~ 1/B`; B=10 GHz → ~1.5 cm one-way). (b) **delay ambiguity** — when the round-trip delay equals an integer multiple of `1/Δf` (Δf = frequency-bin spacing), `e^{−j2πfτ}` completes whole turns across bins and again looks _constant_, so the target merges into `H_SI` and vanishes from the profile. Unambiguous delay window `τ_max = 1/Δf` (e.g. Δf=0.5 GHz → τ_max=2 ns → R wraps every 30 cm). Worked example (B=2 GHz, f_c=11 GHz, 5 bins, Δf=0.5 GHz): a target at τ=2 ns=1/Δf is invisible; at τ=0.5 ns it is cleanly recovered. Mitigate by narrower Δf (more bins) and by keeping the target inside `(1/B, 1/Δf)`.

### B2. Detector

8. **Low ZBD sensitivity.** Square-law conversion loss + NEP set the noise `N` and cap absolute range. Partly offset by the SI homodyne gain (`2α_SI β_ec` vs echo-only `β_ec²`), but below coherent reception.

### B3. Self-interference dependence

9. **SI must exist and be stable enough to be the reference.** If OMT isolation is so high (or geometry nulls leakage) that SI ≈ noise, the phase reference and the homodyne LO both weaken → normalization degrades. There is a _minimum_ useful SI, not a maximum (opposite of conventional SIC intuition).
10. **SI dynamic range / quantization.** With SI ≫ echo, `β/α_SI` is tiny, so ADC bits and numerical precision limit how weak an echo survives the division. This — not an SI sidelobe — is the real "strong-SI" penalty. (Sets an _effective_ upper bound on useful SI given ADC ENOB.)

### B4. Phase-noise residual — SOLVED, and an ADVANTAGE over mixer receivers

11. **Not a limitation; a strength.** Because both THz tones come from the same two lasers, their phase noise is common and cancels in the ZBD self-mixing product; SI normalization additionally cancels the common carrier phase `ψ` so the range estimate is carrier-drift-immune. A **mixer/coherent** receiver would instead inject its own LO phase noise (worse for free-running sources). The residual `σ²_Δφ = 4π Δν τ` from the SI–echo time offset survives only as a long-range asymptotic term (τ→0 ⇒ →0) and is negligible in the operating regime. → List phase noise as a **resolved item / advantage**, not a limitation.

### B5. (removed) Amplitude drift is a DEVICE issue, not a system limitation

12. The 2–5 dB IF amplitude fluctuation was traced to the optical source (laser/EDFA/UTC-PD power), proven by the laser swap improving it from ~5 dB to ~2 dB. The self-homodyne architecture itself is amplitude-stable at fixed geometry (`A_SI, A_ec ∝ P_TX`). → **Not** a limitation of the proposed method; it is removed by a stable source / warm-up / power monitoring. (Kept here only as a measurement note, not a structural limit.)

### B6. Experimental (this campaign)

13. **Few distance points (1, 1.1 m).** `1/R²` (homodyne) vs `1/R⁴` (self-detect) separation and `R_max` rely on extrapolation.
14. **RX antenna as target.** `σ_eff ≈ σ_struct × G_target` (25 dBi re-radiation folded in); report as effective RCS, not a bare physical RCS.
15. **Single capture only.** The single-shot / moving-target claim is argued, not yet demonstrated on a genuinely moving target (and no Doppler measured — see A4).

---

## C. The actual range limit of this system

With SI removed by normalization, the limit is the ordinary **noise limit** (plus a dynamic-range caveat), NOT an SI sidelobe:

$$\mathrm{SNR}_{radar}(R)=\frac{G_p,2,\alpha_{SI},\beta_{ec}(R)}{N},\qquad \beta_{ec}(R)=\frac{\sqrt{K}}{R^2}.$$

$$\boxed{R_{\max}=\left(\frac{2,\alpha_{SI},\sqrt{K},G_p}{N,\gamma_{th}}\right)^{1/2}}$$

Symbols:

- `α_SI = 10^{−ISO/20}` — SI amplitude (OMT isolation). **Larger helps** (homodyne gain), bounded above only by ADC dynamic range (B10), not by sidelobes.
- `β_ec = √K/R²` — echo amplitude; radar-equation `1/R²` amplitude decay.
- `K = P_tx G_t G_r λ² σ_eff /(4π)³` — lumped budget constant (radar eq. minus `R⁴`).
- `N` — noise power: ZBD NEP + thermal `kT₀BF` + ADC quantization.
- `γ_th` — detection-threshold SNR for target `P_d`/`P_fa` (e.g. ~13 dB).
- `G_p = T·B` — matched-filter/IDFT processing gain (TBWP).

Consequences:

- `R_max ∝ (α_SI G_p / N)^{1/2}` → improved by **more SI, more integration (T·B), lower NEP**. Bandwidth `B` sets resolution but cancels in radar SNR (SNR_in ∝ 1/B, G_p ∝ B).
- Because SI has no sidelobe penalty here, **radar reach can exceed the comm reach** (comm is SNR-limited with no processing gain), consistent with the "sensing goes farther" claim — now without an SI-sidelobe caveat.

---

## E. References for radar SNR / processing gain

The `G_p = T·B` (time-bandwidth product) processing gain and matched-filter SNR used in section C are standard radar results:

1. **M. A. Richards**, _Fundamentals of Radar Signal Processing_, 2nd ed., McGraw-Hill, 2014 — matched filter, pulse compression, `G_p = BT` (the primary reference).
2. **M. A. Richards, J. A. Scheer, W. A. Holm (eds.)**, _Principles of Modern Radar: Basic Principles_, SciTech, 2010.
3. **N. Levanon, E. Mozeson**, _Radar Signals_, Wiley, 2004 — ambiguity functions, sidelobes, matched filtering per waveform.
4. **G. L. Turin**, "An introduction to matched filters," _IRE Trans. Inf. Theory_ 6(3), 311–329, 1960 — origin of the matched filter.
5. **R. Middleton**, "Dechirp-on-receive linearly frequency modulated radar as a matched-filter detector," _IEEE Trans. AES_ 48(3), 2716–2718, 2012 — LFM de-chirp as matched filter (relevant to the LFM/SIM path).

For the CFR/OFDM-radar SNR and single-target accuracy (CRB) specifically: 6. **C. Sturm, W. Wiesbeck**, _Proc. IEEE_ 99(7), 1236–1259, 2011 (as in the CFR note). 7. **M. Braun, C. Sturm, F. K. Jondral**, "On the single-target accuracy of OFDM radar algorithms," _IEEE PIMRC_ 2011, 794–798.

---

## F. Honest one-paragraph framing

This system's range detection inherits the standard CFR/Sturm–Wiesbeck limits (resolution `c/2B`, multi-target via IDFT, Doppler only with slow-time, unambiguous-range from subcarrier spacing) and adds a self-homodyne twist: the OMT self-interference is the **phase reference**, so `H/H_SI−1` cancels free-running carrier-phase drift and, as a bonus, removes SI from the range profile (no SI sidelobe floor). Phase noise is a **strength, not a limit** — common-mode cancellation in the ZBD plus SI normalization beats a mixer receiver that would add its own LO phase noise. Amplitude fluctuation is a **device issue** (source power), proven by the laser swap, not a property of the architecture. The genuine remaining limits are therefore (i) **ZBD sensitivity / noise** setting absolute `R_max`, (ii) a **near-range blind zone / delay ambiguity** because SI and targets at `τ ≈ 0` or `τ = k/Δf` are spectrally indistinguishable, (iii) an **SI dynamic-range** upper bound from ADC ENOB, and (iv) the **single-shot ↔ Doppler** trade-off (a design choice, not a defect). Resolution, multi-target, carrier-drift immunity, and phase-noise robustness are _not_ limits — they are handled by bandwidth, the IDFT readout, SI normalization, and self-homodyne common-mode cancellation respectively.