# System Model (paper-ready)

Clean, rigorous formulation for a paper's *System Model* section. The optical
carrier-to-signal ratio is folded into a single carrier coefficient so the equations stay
readable; it is named once where it matters (the communication sideband).

Signal flow:
**optical fields → THz field → ZBD square-law → DC-block + IF bandpass → CFR (channel
estimation) → {communication branch, sensing branch} → SNR / range.**

---

## A. Transmitted optical and THz signals

Two free-running lasers provide a local-oscillator tone and a data-modulated tone:

$$E_1(t)=E_1\,e^{j(2\pi f_1 t+\theta_1(t))},\qquad
E_2(t)=\big[E_2+s(t)\big]\,e^{j(2\pi f_2 t+\theta_2(t))},$$

where `E_2` is the unmodulated optical carrier and `s(t)` the intensity-modulated data
sideband, occupying an intermediate-frequency (IF) passband of bandwidth `B` centred at
`f_IF`. The data waveform superimposes a deterministic sensing pilot and random payload,

$$s(t)=\sqrt{\rho}\,p(t)+\sqrt{1-\rho}\,d(t),\qquad 0\le\rho\le1,$$

with `p(t)` a unit-power deterministic pilot (e.g. Zadoff–Chu) and `d(t)` the payload;
`ρ` is the sensing/communication power-split ratio.

Optical heterodyning in the UTC-PD yields the THz field at `ω_c=2\pi(f_1-f_2)`:

$$E_{\mathrm{THz}}(t)=\eta\,E_1\big[E_2+s(t)\big]\,e^{j(\omega_c t+\Delta\theta(t))}
= A_c\Big[1+\kappa\,s(t)\Big]e^{j(\omega_c t+\Delta\theta(t))},$$

$$A_c\triangleq\eta E_1E_2\ (\text{carrier amplitude}),\qquad
\kappa\triangleq 1/E_2,\qquad \Delta\theta(t)\triangleq\theta_1(t)-\theta_2(t).$$

`Δθ(t)` is the **common** laser phase noise; `κ` measures the sideband-to-carrier ratio
(`κ²⟨|s|²⟩ = 1/CSPR`). The carrier coefficient `A_c` and the small parameter `κ` are the
only places the carrier/sideband balance enters — CSPR need not appear again until the
communication SNR.

---

## B. Received signals at the monostatic ZBD

The zero-bias detector receives the transmit leakage through the OMT (self-interference,
delay ≈ 0) plus the target echo (delay `τ=2R/c`):

$$V_{\mathrm{ZBD}}(t)=V_{\mathrm{SI}}(t)+V_{\mathrm{ec}}(t),$$
$$V_{\mathrm{SI}}(t)=\alpha\,A_c\big[1+\kappa s(t)\big]e^{j(\omega_c t+\Delta\theta(t))},$$
$$V_{\mathrm{ec}}(t)=\beta\,A_c\big[1+\kappa s(t-\tau)\big]e^{j(\omega_c(t-\tau)+\Delta\theta(t-\tau))},$$

with `α=10^{-\mathrm{ISO}/20}` (OMT isolation) and `β=10^{-L(R)/20}=\sqrt{K}/R^{2}` (radar
equation, `K=P_tG_tG_r\lambda^2\sigma_{\mathrm{eff}}/(4\pi)^3`).

---

## C. Square-law detection, DC block and IF bandpass

The ZBD output is `V_{\mathrm{out}}(t)=\mathcal R\,|V_{\mathrm{ZBD}}(t)|^2`. Expanding and
grouping by frequency:

$$V_{\mathrm{out}}=\mathcal R\Big[\underbrace{(\alpha^2+\beta^2)A_c^2+\dots}_{\text{DC terms}}
+\underbrace{2\mathcal R\{\dots\}\ \text{at }f_{\mathrm{IF}}}_{\text{IF passband}}
+\underbrace{\text{SSBI}}_{\sim 2B}\Big].$$

A DC block removes the `|A_c|^2` bias terms — including the carrier×carrier product
`2\alpha\beta A_c^2\cos(\omega_c\tau+\Delta\phi)`, which is time-invariant for fixed `τ`
and therefore falls at DC. A digital bandpass filter retains only the IF passband. The
surviving IF signal is the **carrier×sideband** beat:

$$y(t)=\mathcal R A_c^2\kappa\Big[\alpha\,s(t)+\beta\,e^{j\omega_c\tau}s(t-\tau)\Big]+n(t)+
\underbrace{O(\kappa^2)}_{\text{SSBI, }1/\mathrm{CSPR}},$$

where `Δφ(τ)=Δθ(t)-Δθ(t-τ)` (self-homodyne residual, →0 as τ→0) and `n(t)` is detector
noise. The first term is the SI-borne copy of the data (zero delay); the second is the
echo-borne, delayed copy carrying the range through both `e^{j\omega_c\tau}` and the
group delay of `s(t-\tau)`.

---

## D. Channel estimation (CFR)

Dividing the received IF spectrum by the known transmit spectrum `S(f)` gives the channel
frequency response

$$H(f)=\frac{Y(f)}{S(f)}
=\underbrace{\alpha'}_{\text{SI, flat}}
+\underbrace{\beta'\,e^{-j2\pi(f+f_c)\tau}}_{\text{echo}},\qquad
\alpha'=\mathcal R A_c^2\kappa\,\alpha,\ \ \beta'=\mathcal R A_c^2\kappa\,\beta,$$

with `f_c=\omega_c/2\pi`. Both contributions share the common carrier amplitude and the
per-capture phase; the SI term is frequency-flat (`τ≈0`), the echo term carries the delay
as a linear phase.

---

## E. Two branches

### E.1 Communication branch

With strong SI (`α≫β`), the IF signal is an SI-referenced self-homodyne copy of the data:

$$y(t)\approx \mathcal R A_c^2\kappa\,\alpha\,s(t)\ \Rightarrow\
\hat s(t)=\text{Eq}\big[y(t)\big]\ \xrightarrow{\text{demap}}\ \hat d.$$

Equalization uses the flat SI response (`H_{\mathrm{SI}}`) or pilot `p(t)`; the payload
`d(t)` is then demodulated. The useful communication power scales with the sideband,
`\propto (1-\rho)\,A_c^2\kappa^2 = (1-\rho)A_c^2/\mathrm{CSPR}`.

### E.2 Sensing branch (SI-referenced ranging)

Estimate the flat SI component as the weighted mean and normalize:

$$H_{\mathrm{SI}}=\frac{\sum_f w(f)H(f)}{\sum_f w(f)}\approx\alpha',\qquad
\boxed{\ \tilde H(f)=\frac{H(f)}{H_{\mathrm{SI}}}-1=\frac{\beta}{\alpha}\,e^{-j2\pi(f+f_c)\tau}\ }$$

The common carrier amplitude and per-capture phase cancel in the ratio; the constant
`f_c\tau` term is absorbed into a phase offset. Range follows from either the phase slope
or an inverse DFT:

$$\hat\tau=-\frac{1}{2\pi}\frac{d\angle\tilde H}{df},\qquad
P(\tau')=\Big|\sum_f w(f)\,\tilde H'(f)\,e^{j2\pi f\tau'}\Big|,\qquad
\hat R=\frac{c}{2}\,\hat\tau,$$

with `\tilde H'` the DC-removed residual and coherence
`\gamma=|\sum_f w\,e^{j\angle\tilde H'}|/\sum_f w`. Because the SI is removed prior to
profiling, the range profile is free of an SI peak/sidelobe, and the estimate is immune to
free-running carrier drift (`f_c` drops out of the phase slope). Processing on a single
capture (`num_frames=1`) preserves moving targets.

---

## F. Performance metrics

**Communication SNR / range** (one-way, sideband-borne):

$$\mathrm{SNR}_{\mathrm{comm}}(R)=\frac{(1-\rho)\,A_c^2\,\kappa^2\,G_c}{R^{2}N_c}
=\frac{(1-\rho)\,A_c^2\,G_c}{\mathrm{CSPR}\,R^{2}N_c},\qquad
R_{\max}^{\mathrm{comm}}=\Big(\tfrac{(1-\rho)A_c^2G_c}{\mathrm{CSPR}\,N_c\gamma_c}\Big)^{1/2}.$$

**Sensing SNR / range** (SI-homodyne, pilot-driven, processing gain `G_p=T_pB`):

$$\mathrm{SNR}_{\mathrm{sens}}(R)=\frac{\rho\,G_p\,2\alpha\beta(R)\,A_c^2}{N}
=\frac{2\rho\,\alpha\,A_c^2\sqrt{K}\,G_p}{N\,R^{2}},\qquad
R_{\max}^{\mathrm{sens}}=\Big(\tfrac{2\rho\,\alpha\,A_c^2\sqrt{K}\,G_p}{N\,\gamma_{th}}\Big)^{1/2}.$$

**Joint ISAC range:**

$$\boxed{\ R_{\max}=\min\big(R_{\max}^{\mathrm{comm}},\,R_{\max}^{\mathrm{sens}}\big)\ }$$

with the two branches trading off through `ρ` (`R^{\mathrm{comm}}\!\propto\!\sqrt{1-\rho}`,
`R^{\mathrm{sens}}\!\propto\!\sqrt{\rho}`). At THz the communication constraint binds
(FSPL-limited), so the design minimizes `ρ` subject to a near-range sensing requirement
— a communication-centric operating point.

### Symbol table
| Symbol | Meaning |
|---|---|
| `A_c` | THz carrier amplitude, `A_c=\eta E_1E_2` |
| `κ` | sideband/carrier ratio, `κ=1/E_2`, `κ²⟨\|s\|²⟩=1/\mathrm{CSPR}` |
| `ρ` | sensing/comms power split (pilot fraction) |
| `α` | SI amplitude, `10^{-\mathrm{ISO}/20}` |
| `β` | echo amplitude, `\sqrt{K}/R^2` |
| `K` | radar budget const., `P_tG_tG_r\lambda^2\sigma_{\mathrm{eff}}/(4\pi)^3` |
| `G_p=T_pB` | sensing processing gain |
| `G_c, N_c, \gamma_c` | comms gain, noise, SNR threshold |
| `N, \gamma_{th}` | sensing noise, detection-SNR threshold |

---

## G. On CSPR notation (author note)

Rather than carrying CSPR through every line, fold the optical carrier into `A_c` and the
sideband weakness into `κ`. Then:
- Sensing depends on the **carrier reference** `A_c^2` (strong carrier → strong homodyne
  reference); CSPR never appears explicitly.
- Communication depends on the **sideband**, i.e. on `κ²=1/(\mathrm{CSPR}\langle|s|^2\rangle)`;
  introduce CSPR **once** here as `1/\mathrm{CSPR}`.

This keeps the derivation readable while making the physical trade-off explicit: a large
carrier fraction aids sensing (via `A_c`) but starves the communication sideband (via
`1/\mathrm{CSPR}`). One clean sentence suffices in the paper: *"the optical carrier serves
as the homodyne reference for sensing, while the sideband carries the payload; their ratio
(CSPR) thus trades sensing reference strength against communication SNR."*
