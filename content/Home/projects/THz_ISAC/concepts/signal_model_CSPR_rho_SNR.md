# Consolidated Signal Model: E_THz → V_ZBD → CFR → SI-Norm/IDFT → SNR

Full chain with both power ratios explicit: **CSPR** (optical carrier/sideband, MZM) and
**ρ** (digital pilot/data split, AWG). Ends with sensing and communication SNR / range,
both as functions of ρ and CSPR.

---

## 1. Optical fields and the two power ratios

$$E_1(t)=E_1\,e^{j[2\pi f_1 t+\theta_1(t)]}\ (\text{LO}),\qquad
E_2(t)=[E_2+s(t)]\,e^{j[2\pi f_2 t+\theta_2(t)]}\ (\text{MZM}).$$

**Digital waveform (ρ)** — the sideband carries a pilot(sensing)+data(comms) superposition:

$$s(t)=\sqrt{\rho}\,p(t)+\sqrt{1-\rho}\,d(t),\qquad
p=\text{ZC pilot (deterministic)},\ d=\text{data (random)}.$$

**Optical ratio (CSPR)** — carrier vs sideband at the MZM:

$$\mathrm{CSPR}=\frac{|E_2|^2}{\langle|s|^2\rangle}\ \Rightarrow\ \frac{s(t)}{E_2}\propto\frac{1}{\sqrt{\mathrm{CSPR}}}.$$

Both are independent knobs on different layers.

---

## 2. THz field (UTC-PD heterodyne)

$$E_{THz}(t)=E_1[E_2+s(t)]\,e^{j[\omega_c t+\Delta\theta(t)]},\qquad
\omega_c=2\pi(f_1-f_2),\ \Delta\theta=\theta_1-\theta_2.$$

Factor the carrier:

$$E_{THz}(t)=A_c\Big[1+\tfrac{s(t)}{E_2}\Big]e^{j[\omega_c t+\Delta\theta(t)]},\qquad
A_c=E_1E_2\ (\text{carrier amplitude}).$$

`Δθ = θ_1−θ_2` is the **common** laser phase (cancels in self-homodyne).

---

## 3. ZBD input: SI and echo

$$V_{SI}=\alpha_{SI}A_c\Big[1+\tfrac{s(t)}{E_2}\Big]e^{j[\omega_c t+\Delta\theta(t)]},\quad
V_{echo}=\beta_{ec}A_c\Big[1+\tfrac{s(t-\tau)}{E_2}\Big]e^{j[\omega_c(t-\tau)+\Delta\theta(t-\tau)]}.$$

`α_SI=10^{−ISO/20}`, `β_ec=10^{−L_radar/20}=√K/R²`, `τ=2R/c`.

---

## 4. ZBD square-law output

$$V_{out}=\mathcal R\,|V_{SI}+V_{echo}|^2
=\mathcal R\big[|V_{SI}|^2+|V_{echo}|^2+2\,\mathrm{Re}\{V_{SI}V_{echo}^*\}\big].$$

### Homodyne cross term (target-bearing)

$$2\,\mathrm{Re}\{V_{SI}V_{echo}^*\}
=2\alpha_{SI}\beta_{ec}A_c^2\,\mathrm{Re}\Big\{\big[1+\tfrac{s(t)}{E_2}\big]\big[1+\tfrac{s(t-\tau)}{E_2}\big]^*
e^{j(\omega_c\tau+\Delta\phi)}\Big\}.$$

Expanding the bracket, with `Δφ=Δθ(t)−Δθ(t−τ)`:

$$\big[1+\tfrac{s(t)}{E_2}\big]\big[1+\tfrac{s(t-\tau)}{E_2}\big]^*
=\underbrace{1}_{\text{car×car}}+\underbrace{\tfrac{s(t)}{E_2}+\tfrac{s^*(t-\tau)}{E_2}}_{\text{car×side }\propto1/\sqrt{\mathrm{CSPR}}}+\underbrace{\tfrac{s(t)s^*(t-\tau)}{E_2^2}}_{\text{side×side }\propto1/\mathrm{CSPR}}.$$

Term magnitudes (e.g. CSPR 13 dB): 1 : 0.224 : 0.050. The **carrier×carrier** term
dominates and carries the range phase `e^{j(\omega_c\tau+\Delta\phi)}`; the reference
strength scales with `A_c^2` (i.e. with CSPR).

---

## 5. Channel frequency response (CFR)

Estimating `H(f)=Y(f)/S(f)` (code `_estimate_lfm_cfr`), the carrier-dominant part gives

$$H(f)=\underbrace{\alpha_{SI}A_c\,e^{j\psi}}_{\text{SI, }\tau\approx0\ (\text{flat})}
+\underbrace{\beta_{ec}A_c\,e^{j\psi}\,e^{-j2\pi(f+f_c)\tau}}_{\text{echo}},$$

`ψ` = common per-capture carrier phase, `f_c` = drifting carrier. Both SI and echo carry
the same `A_c` and `e^{jψ}`.

---

## 6. SI normalization (removes A_c, ψ, drift)

$$H_{SI}=\frac{\sum_f w\,H}{\sum_f w}\approx\alpha_{SI}A_c e^{j\psi},\qquad
\boxed{\tilde H(f)=\frac{H}{H_{SI}}-1=\frac{\beta_{ec}}{\alpha_{SI}}\,e^{-j2\pi(f+f_c)\tau}}.$$

`A_c` and `e^{jψ}` are common → **cancel** (CSPR drops out of the *phase*; it remains in
the *absolute SNR* via `A_c^2`). `f_c\tau` is constant in `f` → range is **drift-immune**.

---

## 7. Range readout (phase-slope or IDFT)

**Phase-slope (single target):**
$$\hat\tau=-\frac{1}{2\pi}\frac{d\,\angle\tilde H}{df},\qquad \hat R=\frac{c\hat\tau}{2}.$$

**IDFT / delay-matching (multi-target), code path:** after DC removal
`H̃' = H̃ − mean_w(H̃)`,
$$P(\tau')=\frac{1}{\sum_f w}\Big|\sum_f w(f)\,\tilde H'(f)\,e^{j2\pi f\tau'}\Big|
=\Big|\sum_k\tfrac{\beta_k}{\alpha_{SI}}\,\mathrm{sinc}\big(B(\tau'-\tau_k)\big)\Big|,$$
$$\hat R_k=\frac{c}{2}\{\tau':P\text{ peaks}\},\qquad
\gamma=\frac{|\sum_f w\,e^{j\angle\tilde H'}|}{\sum_f w}\ (\text{coherence}).$$

Single capture (`num_frames=1`): no smearing of moving targets, no re-measurement.

---

## 8. Sensing SNR and range (ρ, CSPR explicit)

The deterministic pilot (fraction ρ) drives the range estimate; the homodyne reference is
`A_c^2` (CSPR). Processing gain `G_p=T_pB` (pilot time-bandwidth):

$$\boxed{\ \mathrm{SNR}_{sens}(R)=\frac{\rho\,G_p\,2\,\alpha_{SI}\,\beta_{ec}(R)\,A_c^2}{N},
\qquad \beta_{ec}(R)=\frac{\sqrt K}{R^2}\ }$$

Detection at `SNR_sens = γ_th`:

$$\boxed{\ R_{\max}^{sens}=\Big(\tfrac{2\,\rho\,\alpha_{SI}\,A_c^2\,\sqrt K\,G_p}{N\,\gamma_{th}}\Big)^{1/2}\ }$$

- **ρ** (pilot fraction) multiplies sensing SNR linearly.
- **CSPR** enters through `A_c^2` (carrier reference strength) and through `α_SI,β_ec`
  being carrier-beat amplitudes.
- No SI-sidelobe floor (normalization removes SI) → noise-limited; larger `ρ,A_c` help,
  bounded above only by ADC dynamic range and by comms (below).

---

## 9. Communication SNR and range (ρ, CSPR explicit)

Communications ride on the data sideband (fraction `1−ρ`). Sideband power
`P_side = A_c^2/CSPR` (since `s/E_2 ∝ 1/√CSPR`), one-way `1/R²`:

$$\boxed{\ \mathrm{SNR}_{comm}(R)=\frac{(1-\rho)\,P_{side}\,G_c}{R^2\,N_c}
=\frac{(1-\rho)\,A_c^2\,G_c}{\mathrm{CSPR}\,R^2\,N_c}\ }$$

`G_c` = comms processing/coding gain, `N_c` = comms-band noise. At the EVM/FEC threshold
`SNR_comm = γ_c`:

$$\boxed{\ R_{\max}^{comm}=\Big(\tfrac{(1-\rho)\,A_c^2\,G_c}{\mathrm{CSPR}\,N_c\,\gamma_c}\Big)^{1/2}\ }$$

- **ρ** appears as `(1−ρ)`: more data power (smaller ρ) → longer comms range.
- **CSPR** appears as `1/CSPR`: a very high CSPR starves the sideband → shorter comms
  range. (Trade-off: CSPR too low loses the sensing/homodyne reference `A_c^2`.)

---

## 10. The ρ trade-off (both ranges together)

$$R_{\max}^{sens}\propto\sqrt{\rho},\qquad R_{\max}^{comm}\propto\sqrt{1-\rho}.$$

Opposite monotonicities in ρ → a feasible band / single crossing. Design problem:

$$\max_\rho\ U(\rho)\quad\text{s.t.}\quad R_{\max}^{comm}(\rho)\ge R_c^{req},\
R_{\max}^{sens}(\rho)\ge R_r^{req}.$$

At THz the comms constraint binds (FSPL-limited, ~1 m) while sensing is near-range and
homodyne-aided, so the optimum pushes ρ **down**:

$$\rho^\star=\min\{\rho:\ R_{\max}^{sens}(\rho)\ge R_r^{req}\}\ \approx\ \text{small (code: 0.2)}.$$

This is the **Communication-Centric Design (CCD)** regime; ρ=0.2 gives data 80% / pilot
20%. Because SI normalization removes the SI sidelobe, sensing is met at very small ρ,
widening the comms-priority region.

### Two knobs, summarized
| Knob | Appears in `SNR_sens` | Appears in `SNR_comm` | THz setting |
|---|---|---|---|
| ρ (pilot/data) | `× ρ` | `× (1−ρ)` | small (~0.2), comms-priority |
| CSPR (carrier/side) | `× A_c²` (via reference) | `× 1/CSPR` | moderate (~13 dB) |

---

## 11. References

- Pilot/data power allocation for ISAC (utility = rate + radar CRB): ZF-beamforming ISAC,
  *Physical Communication* / ScienceDirect, 2023 (pilot-only radar reference, optimal PA).
- **Y. Zhang, F. Liu, T. Liu, S. Jin**, "Optimal Power Allocation for OFDM-based Ranging
  Using Random Communication Signals," arXiv:2504.18016, 2025 (deterministic–random
  tradeoff; ranging-sidelobe PA).
- Power allocation, monostatic ISAC with self-interference, minimize max range error under
  comms-SINR constraint: arXiv:2402.10660, 2024.
- SCD vs CCD taxonomy: OFDM-ISAC power allocation for ToA, arXiv:2502.08431, 2025.
- CFR ranging: **Sturm & Wiesbeck**, *Proc. IEEE* 99(7), 2011.
- Radar SNR / `G_p=BT`: **M. A. Richards**, *Fundamentals of Radar Signal Processing*, 2014.
- Self-homodyne phase-noise cancellation: **Dülme et al.**, *Opt. Express* 28(20), 29631,
  2020. LO-as-reference: **Harter/Koos et al.**, *Nat. Photonics* 14, 601, 2020.

> Both power ratios are kept distinct: CSPR is the optical carrier/sideband ratio at the
> MZM; ρ is the digital pilot/data split in the DFT-s-OFDM waveform. Earlier notes that
> equated them are superseded by this document.
