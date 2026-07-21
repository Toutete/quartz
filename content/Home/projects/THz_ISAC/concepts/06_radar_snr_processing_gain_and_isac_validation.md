---
title: Radar SINR, Processing Gain, and ISAC Distance Validation
is_public: false
updated: 2026-07-20
---

# Radar SINR, Processing Gain, and ISAC Distance Validation

## 1. Why radar SNR can look much larger than communication SNR

The radar number shown after range detection is not the same quantity as the
communication EVM-implied SNR.  Communication SNR is evaluated before any radar
matched filtering, while the radar range profile is obtained after correlating
the received C2 waveform with a known reference waveform.

For a coherent/reference-aided range processor, the approximate processing gain is

```math
G_p \simeq 10\log_{10}(N_\mathrm{chirp}N_\mathrm{ref}) \quad [\mathrm{dB}]
```

For the current saved C2 range captures,

```math
N_\mathrm{chirp}=15,\quad N_\mathrm{ref}=8192
```

so

```math
G_p = 10\log_{10}(15\times8192) \simeq 50.9\ \mathrm{dB}.
```

This does not mean that the RF received power increased by 50.9 dB.  It means
that the detection statistic after matched filtering has a much lower effective
noise variance per range bin than the raw C2 IF waveform.

## 2. SNR definitions now used in `isac_gui.py`

### C1 communication channel

C1 is the one-way communication receiver channel.  EVM is computed from the C1
demodulation chain.  The communication-quality metric used for the
distance-validation model is the EVM-implied effective SINR:

```math
\mathrm{SINR}_{comm,eff} = -\mathrm{EVM}_{dB}.
```

This assumes RMS EVM in dB, `EVM_dB = 20log10(EVM_rms)`, with unit average
constellation power.  The phrase **EVM-implied effective SINR** is therefore more
accurate than calling it a separately measured electrical SNR, because it
includes residual DSP error, phase noise, nonlinear distortion, and in-band
receiver noise.

### C2 radar channel: pre-DSP band SNR

C2 is the monostatic radar receiver channel.  Before range processing, the code
stores the C2 in-band signal-to-noise ratio as

```text
radar_pre_snr_db_c2
```

This is derived from C2 band power and integrated noise power:

```math
\mathrm{SNR}_{C2,pre}
= P_{C2,\mathrm{band}} - P_{C2,\mathrm{noise}}
\quad [\mathrm{dB}].
```

This value should be compared with the measured received IF power, e.g. around
`-35` to `-43 dBm`, because it is still a waveform/band-domain metric.

### C2 radar channel: post-processing range-profile SNR

After matched filtering or CFR-based range processing, the radar detection metric is

```text
snr_rad_post_db_c2
snr_rad_db
```

where

```math
\mathrm{SNR}_{rad,post}
= P_\mathrm{target\ bin} - \mathrm{median}(P_\mathrm{profile\ floor})
\quad [\mathrm{dB}].
```

In code this is evaluated on the normalized range profile as target peak minus
the median profile floor, excluding the target neighborhood and the SI guard
region.  This is best interpreted as a **post-processing radar detection SNR**
or **range-profile SNR**, not as raw RF input SNR.

The code also stores

```text
radar_processing_gain_db_c2
snr_rad_pg_corrected_db_c2
```

with

```math
\mathrm{SNR}_{rad,PG-corrected}
= \mathrm{SNR}_{rad,post} - G_p.
```

This PG-corrected value is only a diagnostic.  It should not be used as the
radar detection metric because the detector actually operates after processing.

## 3. Why C2 must be used for radar

The system uses

- `C1`: one-way communication path
- `C2`: monostatic radar path

Therefore radar sensing metrics must come from C2.  The updated `isac_gui.py`
sets:

```text
radar_pre_snr_db_c2       # C2 before range processing
snr_rad_post_db_c2        # C2 after range processing
snr_rad_db                # representative radar SNR, now C2 post-processing
```

If no range profile has been computed yet, `snr_rad_db` may temporarily fall back
to the C2 pre-DSP band SNR, but the metric note explicitly marks it as fallback.
For final comparison, press **Detect Range** and use the post-processing C2 value.

The plotted distance is the physical target range `R`, not the total propagation
length.  For C2, the simulator and range estimator internally use the round-trip
delay

```math
\tau_{C2}=\frac{2R}{c},
```

and the range profile reports

```math
R=\frac{c\tau_{C2}}{2}.
```

Thus a target placed 1 m away should be plotted at 1 m, even though the
propagation path length is 2 m.  The link budget still uses the round-trip radar
loss through the `2*FSPL - RCS gain` term.

The effective RCS used by the simulator is

```math
\sigma_{eff}
=\sigma_{struct}\eta_{pol}
+\frac{\lambda^2G_t^2|\Gamma|^2\eta_{pol}}{4\pi}.
```

`sigma_struct` is already an area in square metres, so target antenna gain and
load reflection are not applied to it again.  Those factors appear only in the
antenna-mode reradiation term.  Applying them to both terms would double-count
target gain and artificially inflate the C2 echo power.

## 4. SI on/off comparison

With SI-assisted homodyne sensing, the useful target beat term scales with the SI
carrier amplitude.  The echo RF power itself follows the monostatic radar law
`1/R^4`, while the echo RF field amplitude follows `1/R^2`.  In a ZBD
SI-assisted homodyne detector, the useful IF voltage is proportional to
`SI amplitude x echo amplitude`; therefore the displayed C2 IF electrical power
and post-processing radar SINR follow approximately

```math
\mathrm{SNR}_{sens,on}(R)
= \mathrm{SNR}_{0}
-40\log_{10}\left(\frac{R}{R_0}\right).
```

If SI is removed, the homodyne gain is also removed.  The remaining direct
detection/self-beat radar term is a square-law echo-only term.  Its ZBD output
electrical power follows approximately `1/R^8`:

```math
\mathrm{SNR}_{sens,off}(R)
\propto \frac{1}{R^8}.
```

In the GUI, this comparison is not produced by manually applying a fixed
penalty.  The SI-on and SI-off cases are generated by re-running the simulator
while sweeping the OMT isolation.  The default SI-on isolation is `24 dB`, and
the default SI-off isolation is `1000 dB`.

## 5. ISAC range validation with rho

The current validation model compares two constraints:

```math
\mathrm{SNR}_{comm}(R,\rho)
\propto \frac{1-\rho}{R^2}
```

and

```math
\mathrm{SNR}_{sens,on}(R,\rho)
= A_{hom}\frac{\rho}{\rho_0}\left(\frac{R_0}{R}\right)^4
+ B_{self}\left(\frac{\rho}{\rho_0}\right)^2
\left(\frac{R_0}{R}\right)^8.
```

Here, `A_hom` is the SI-echo homodyne contribution and `B_self` is the
echo-only square-law contribution, both expressed as linear post-processing
SINR at the reference point `(R0, rho0)`.  The SI-off branch contains only the
second term.  With a linear required SINR `gamma_s`, the exact SI-on maximum
distance follows by setting `x=(R/R0)^4`:

```math
\gamma_s x^2-A_{hom}(\rho/\rho_0)x
-B_{self}(\rho/\rho_0)^2=0,
```

```math
R_{sens,on,max}=R_0\left[
\frac{A_{hom}(\rho/\rho_0)+
\sqrt{A_{hom}^2(\rho/\rho_0)^2+4\gamma_sB_{self}(\rho/\rho_0)^2}}
{2\gamma_s}\right]^{1/4}.
```

The no-SI solution is

```math
R_{sens,off,max}=R_0\left[
\frac{B_{self}(\rho/\rho_0)^2}{\gamma_s}
\right]^{1/8}.
```

For a required pre-FEC communication threshold and a required radar detection
threshold, the communication and sensing maximum ranges are

```math
R_{comm,max}(\rho),\qquad R_{sens,max}(\rho).
```

The ISAC operating range is then

```math
R_{ISAC,max}(\rho)
= \min(R_{comm,max}(\rho), R_{sens,max}(\rho)).
```

This is the cleanest way to support the paper claim:

> The amplitude/power split `rho` balances communication EVM and SI-assisted
> radar detection, increasing the joint ISAC range under simultaneous EVM and
> radar-SNR constraints.

## 6. Practical recommendation for figures

Use the following labels:

- Communication panel: `Effective SINR` (`-EVM_dB` for measured EVM points)
- Radar panel: `Radar SINR`
- Diagnostic table/CSV: include `C2 pre-DSP SNR`, `Processing gain`, and
  `PG-corrected SNR`

Avoid comparing `post-processing radar SNR` directly to raw C2 received power or
communication EVM without stating the processing gain, because those quantities
live in different domains.

## 7. Current GUI behavior for simulation-vs-measurement validation

The **System Model Validation** tab now performs a direct distance sweep using
the same simulator as the first simulation tab.  For each distance, the GUI runs
two cases:

- SI on, with the user-entered OMT isolation, default `24 dB`
- SI off, with very large OMT isolation, default `1000 dB`

At each distance point, it records simulated communication EVM, raw C2 in-band
power, C2 target-excess power, SIC/residual C2 in-band power, and radar SNR.  The measured points are
plotted only as open symbols for
comparison.

For the displayed distance-sweep curves, the C2 target-excess power is converted
to a phase-averaged distance-law trend around the metric reference distance.
This avoids plotting single-shot coherent fading/ripple from the carrier phase
of `|SI+echo|^2` as if it were a fundamental distance law.
The SI-assisted target trend is constrained as a nonnegative power sum of the
echo self-beat term and the SI-echo homodyne term, so the representative SI-on
curve cannot fall below the no-SI echo-only curve.
The maximum-distance-vs-rho plot uses the same ZBD target-power law.  Its SI-on
distance is obtained from the exact positive sum of the `1/R^4` homodyne term
and the `1/R^8` echo-self-beat term.  It therefore approaches the
`40 dB/decade` law when homodyne detection dominates, while retaining the
steeper self-beat contribution near the reference point.  The no-SI distance
uses the `80 dB/decade` output-power law.

The default communication measurement markers are the user-provided 15-GBaud
32QAM EVM points:

| Range | EVM | EVM-implied SNR |
|---:|---:|---:|
| 900 mm | -18.46 dB | 18.46 dB |
| 1000 mm | -17.49 dB | 17.49 dB |
| 1100 mm | -16.31 dB | 16.31 dB |

The same tab now also loads C2 radar measurement markers from
`code/data/EVM_range` when the GUI starts or when **Clear Meas.** is pressed.
The current built-in radar markers are:

| Saved file | Range marker | Radar metric used |
|---|---:|---:|
| `Data_fIF11_fsym15_P-8_fRF280_DFT-s-OFDM_32QAM_Iph6.5.npz` | 1014 mm | 7.70 dB, pre-DSP fallback because no C2 profile is stored |
| `Data_range_fIF11_fsym15_P-8_fRF280_DFT-s-OFDM_32QAM_Iph7.npz` | 1099 mm | 20.56 dB, C2 post-processing range-profile SNR |
| `Range_fIF11_fsym15_P-8_fRF280_DFT-s-OFDM_32QAM_Iph6.5.npz` | 1014 mm | 5.32 dB, C2 post-processing range-profile SNR |
| `Range_fIF11_fsym15_P-8_fRF280_DFT-s-OFDM_32QAM_Iph6.5.npz` reference profile | 1006 mm | 6.70 dB, C2 post-processing reference-profile SNR |

For these saved range captures, the nominal coherent-length gain estimate is
approximately 50.89 dB.  It is reported as a diagnostic and is not added again
to the already post-processed target-to-profile-floor Radar SINR.  Adding it a
second time would overstate the measured radar performance.

**Sync Sim** reads the current first-tab configuration and copies its UTC-PD TX
output, SI-on isolation, rho, target distance, and available latest result into
the validation tab.  The validation curves are still generated by a fresh
distance sweep when **Run** is pressed.
Therefore:

- The current first-tab UI parameters are synchronized even if a single-point
  simulation has not just been run.
- Run the first tab first only when its latest single-point EVM/radar result is
  also needed as a reference readout.
- Press **Run** in the validation panel.  This sweeps `target_dist_m` and records
  the simulated metrics at each range.

The **Metric ref distance [m]** field is only a readout/calibration location.  With
the default `1.0 m`, the distance point closest to 1 m is used to display fixed C2
noise and effective processing gain.  It is not used as a mathematical anchor
for extrapolating the curves.

The visible GUI controls were therefore reduced to the quantities that directly
change the range-validation curves:

- range axis limits
- metric reference distance for readout, normally 1 m
- SI-on and SI-off OMT isolation
- `rho` at the reference point and `rho` for the plotted curve
- fixed C2 noise power
- radar processing gain used for the displayed sensing SNR
- minimum accepted C2 measurement power for filtering unreliable/default points
- communication and radar thresholds
- manual EVM points entered as `range_mm:EVM_dB`
- manual C2 SI-on/SI-off in-band power points entered as `range_mm:power_dBm`

Target peak power, SI amplitude, bandwidth, and plot-sampling density are no
longer exposed in this panel because they either were diagnostic quantities or
affected the plot only through a secondary path.  The radar curve now uses

```math
\mathrm{SNR}_{rad}(R)
=
P_{C2,\mathrm{IB}}(R)-N_{C2,\mathrm{IB}}+G_{p,\mathrm{eff}}
\quad [\mathrm{dB}],
```

where `N_C2,IB` is held fixed and `G_p,eff` is the processing gain/loss term used
for the displayed detection statistic.

## 8. How to prove the radar measurement is physically valid

Matching a simulated radar SNR to a measured radar SNR is not very strong
evidence by itself, because the post-processing radar SNR already includes
range-processing gain, windowing, profile normalization, and the selected floor
definition.  A stronger validation package is:

1. **Correct range localization**  
   The C2 peak should appear at the known target distance after applying the
   correct monostatic delay convention.

2. **Known displacement recovery**  
   If the target is moved by 7 mm, the estimated C2 peak displacement should move
   by 7 mm within the expected range-bin/interpolation uncertainty.

3. **Resolution scaling with bandwidth**  
   The measured main-lobe width should follow

   ```math
   \Delta R \simeq \frac{c}{2B}.
   ```

   This is the strongest evidence that the THz ultra-wideband radar processing is
   working as claimed.

4. **Range-law consistency**  
   With SI-assisted homodyne sensing, the target detection metric should follow
   approximately a `1/R^4` C2 ZBD output-power/SINR law after accounting for
   fixed processing gain.
   If SI is removed, the direct-detection/self-beat case should degrade closer
   to `1/R^8`.

   In the GUI this is checked using the saved C2 spectrum metric
   `band_power_dbm_c2` together with the simulated raw C2 in-band power sweep.
   With SI on, the raw C2 spectrum contains the SI self-beat floor plus the
   target-dependent SI-echo term.  At long distance it therefore converges to
   the SI floor instead of going to zero.

   ```math
   P_{C2,\mathrm{IB,on}}(R)
   \approx
   P_{\mathrm{SI,IB}}
   +
   P_{\mathrm{target,IB}}(R).
   ```

   Around 1 m, the stored preset can have SI and echo powers of comparable
   magnitude.  In that transition region, the ZBD square-law term
   `|SI+echo|^2` can show coherent constructive/destructive ripple as distance
   changes the carrier phase.  This single-shot ripple is a diagnostic artifact
   of a fixed phase realization and is not the same quantity as the
   phase-averaged radar distance law used for the final validation curve.

   The same panel also draws the SI-suppressed/direct-detection simulation:

   ```math
   P_{C2,\mathrm{IB,off}}(R)
   \approx
   P_{\mathrm{echo,self}}(R)
   +
   P_{\mathrm{noise,IB}}.
   ```

   This SI-off curve is generated by the simulator using very large OMT
   isolation, not by applying a hand-selected penalty.  It follows the
   echo-only trend until it reaches the fixed detector/IF/DSO noise floor.

   The radar SNR curve is not computed from raw C2 total band power.  Raw C2 band
   power is useful for validating SI floor and receiver noise saturation.  The
   distance-law curve uses C2 target-excess power:

   ```math
   P_{C2,\mathrm{target}}(R)
   =
   P_{C2}(\mathrm{SI}+\mathrm{echo};R)
   -
   P_{C2}(\mathrm{SI}).
   ```

   In the SI-off case this reduces to the echo-only ZBD output and therefore
   drops with the expected direct-detection/self-beat law until it is far below
   the measured raw noise floor.
   In the SI-on case, the representative curve is computed as

   ```math
   P_{C2,\mathrm{target,on}}(R)
   =
   P_{\mathrm{echo\ self}}(R)
   +
   P_{\mathrm{SI\mbox{-}echo}}(R),
   ```

   where both terms are nonnegative.  A single coherent phase realization can
   still show ripple in the raw diagnostic waveform, but the performance trend
   must not violate this power ordering.

   The GUI obtains the SI-echo term from the two orthogonal ZBD cross-term
   components.  If `I` and `Q` denote the filtered real and imaginary parts of
   `2 SI echo*`, the carrier-phase-averaged power is

   ```math
   \overline P_{SI\mbox{-}echo}
   =\frac{P_I+P_Q}{2}.
   ```

   Therefore **C2 Target Band Power (phase avg.)** is the correct link-budget
   quantity.  The separately retained coherent/raw metrics are diagnostics for
   phase fading and spectrum inspection, not the monotonic distance-law curve.

5. **Detection-statistic validation**  
   Report the target-bin statistic relative to the local profile floor/clutter
   distribution, not only the absolute power.  A CFAR-style threshold or a fixed
   `Pd/Pfa` threshold is more defensible than a visually selected peak.

## 9. Radar range limit: why PSLR alone is not enough

PSLR is a sidelobe-quality metric:

```math
\mathrm{PSLR}
= P_\mathrm{main\ peak}-P_\mathrm{largest\ sidelobe}
\quad [\mathrm{dB}].
```

It tells us whether the peak is clean and whether nearby sidelobes/clutter are
suppressed.  A measured PSLR of about 21 dB is good evidence that the selected
range profile is high quality at that measured distance.

However, PSLR alone does **not** define maximum radar range.  At a longer range,
the whole target response can drop toward the thermal/clutter/noise floor while
the relative sidelobe ratio remains similar.  Therefore a claim such as “21 dB
PSLR implies operation up to several meters” is not defensible without an
amplitude/SNR or detection-probability model.

A defensible radar range limit should be stated using one of these:

- **Post-processing C2 radar SNR / SCNR threshold**  
  Use target-bin power relative to calibrated noise-plus-clutter floor.

- **CFAR detection threshold**  
  Choose `Pfa`, estimate the local floor distribution, and report the range at
  which the measured/extrapolated target statistic still exceeds the threshold.

- **Detection probability target**  
  Report the maximum range satisfying a required `Pd` at a selected `Pfa`.

- **Range accuracy or displacement-resolution target**  
  Report the maximum range at which the peak location error remains below a
  required value, e.g. sub-centimeter displacement recovery.

For this paper, the cleanest statement is:

> The maximum ISAC range is the smaller of the communication range satisfying the
> pre-FEC EVM/SNR requirement and the radar range satisfying the C2
> post-processing detection threshold.  PSLR is reported separately as evidence
> of range-profile quality and clutter/sidelobe suppression.

## 10. Recommended extra measurement for the `1/R^4` SI-assisted radar claim

The currently stored C2 in-band power points are clustered around 1.0-1.1 m.
That is enough to display the measured markers, but it is too narrow to make a
reliable slope claim.  The GUI therefore suppresses the measured slope fit unless
the loaded range span is at least 1.5x.

For a publishable `1/R^4` validation of the SI-assisted C2 ZBD output-power/SINR
law, save C2 captures at several distances with
the same waveform, same `rho`, same IF gain, same target, and same alignment.
Recommended distances:

```text
0.7 m, 1.0 m, 1.4 m, 2.0 m, 2.8 m
```

For each point, save the normal **Save Data** NPZ so that `band_power_dbm_c2` is
stored.  If possible, also save one target-absent/background capture with the
same settings.  Then the strongest metric is the background-subtracted in-band
power:

```math
P_{C2,\mathrm{target}}(R)
=
\int_{\mathrm{IB}}
\left[S_{C2}(f;R)-S_{C2,\mathrm{bg}}(f)\right]df.
```

Without a background capture, `band_power_dbm_c2` is still useful as a first
check, but it can include SI leakage, static clutter, and IF-chain drift.

Manual entry format in the GUI:

```text
Manual EVM [mm:dB]       900:-18.46, 1000:-17.49, 1100:-16.31
Manual C2 SI-on [mm:dBm] 700:-34.2, 1000:-38.0, 1400:-41.1
Manual C2 SI-off [mm:dBm] 700:-65.0, 1000:-71.2, 1400:-77.1
```

Numbers larger than 50 are interpreted as millimeters; values up to 50 are
interpreted as meters.

The GUI now draws the final paper-oriented validation panel with twin y axes:

- left y axis: effective communication SINR in blue
- right y axis: radar SINR in red
- linear distance axis, display default `0` to `2 m`
- distance min/max controls the calculation sweep, while plot x min/max controls
  only the displayed x-axis
- dotted blue/red simulation with SI, using the entered SI-on OMT isolation
- dotted black simulation without SI, using a very large SI-off OMT isolation
- open symbols for measured points

The measured extrapolation lines were removed.  Measurement points are shown only
as symbols.

The current implementation no longer builds the SI-on/no-SI curves by anchoring a
single reference point and extrapolating it.  Pressing **Run** in the validation
panel directly sweeps `target_dist_m` in the same simulator used by the first
simulation tab.  For each range point, the GUI records:

- communication effective SINR/EVM
- C2 in-band power
- C2 noise power
- pre-processing C2 SNR
- effective processing gain
- post-processing radar SNR

The SI comparison is made by sweeping the OMT isolation:

- **SI on:** default `24 dB`
- **SI off:** default `1000 dB`
- **Sweep TX power:** default `0 dBm`, applied directly to the UTC-PD RF output
  power used by the distance sweep

Pressing **Sync Sim** replaces the validation panel's sweep TX power, SI-on
isolation, and both rho fields with the current first-tab UTC-PD output,
`omt_iso_db`, and `pilot_rho`.  Therefore the default `0 dBm` is only the
pre-sync initial value.

Thus the no-SI curve corresponds to a true near-infinite-isolation simulation,
not to an arbitrary penalty factor.

The **Metric ref distance [m]** field is retained only as a calibration/readout
location.  The default `1.0 m` is useful because the available measured EVM/radar
points are around `1.0-1.1 m`.  During the sweep, the distance point closest to this
metric reference is used to populate the displayed fixed C2 noise and effective
processing gain fields.  It is not used as the mathematical anchor for the
distance curves.

The effective processing gain is computed as

```math
G_{p,\mathrm{eff}}
=
\mathrm{SNR}_{rad,post}
-
\mathrm{SNR}_{C2,pre}.
```

This effective value is intentionally different from the ideal coherent gain
`10log10(N_chirp N_ref)` when the measured range profile is clutter/floor limited.

GUI workflow:

1. Load the desired first-tab simulation parameters, then press **Sync Sim** to
   copy its UTC-PD TX output, SI-on isolation, rho, waveform, and receiver
   parameters into the validation sweep.
2. Set **SI-on isolation [dB]** and **SI-off isolation [dB]**.  The defaults are
   `24 dB` and `1000 dB` before synchronization.
3. Set **Metric ref distance [m]** to the measured reference distance, usually
   `1.0 m`.
4. Press **Run**.  The GUI sweeps target distance, runs both SI-on and SI-off
   simulations, and plots the resulting effective SINR, C2 target power, and
   radar SINR against the measured open-symbol markers.

Only **Run Sweep**, **Sync Sim**, and **Load Params JSON** execute the physical
distance simulation.  **Load Save Data**, **Clear Meas.**, **Redraw**, and Enter
or focus-out on the plot-limit fields redraw the cached sweep without rerunning
the simulator.

The **C2 meas min [dBm]** field filters SI-on C2 band-power markers.  The current
default `-40 dBm` removes the weaker saved points that were not controlled well
enough for the final range-law figure.  Set this field lower, or leave it blank,
if those points should be shown.  The default is now blank so loaded measurement
points are visible unless the user explicitly applies a cutoff.

The default radar requirement is `13.2 dB`.  It is a configurable required
post-processing Radar SINR associated with an assumed probability of detection
`P_D` and probability of false alarm `P_FA`; it is not a universal radar
constant.  A paper must state the selected `P_D`, `P_FA`, integration rule, and
detector/CFAR model when using this threshold.  The standard notation is
`P_D/P_FA`, not `P_A/P_FD`.

Measured Radar SINR symbols use the saved C2 range-profile target-to-floor
metric directly.  Simulation noise and processing-gain fields do not move a
saved measurement symbol.  C2 power is converted to Radar SINR only for manual
power points that do not contain a saved range-profile Radar SINR.

Saved `band_power_dbm_c2` is an integrated C2 in-band quantity.  It can be the
same for two captures even when the target energy is distributed differently
across delay bins or the clutter/profile floor is different.  Radar SINR is a
target-bin-to-profile-floor metric, so equal C2 band power does not imply equal
Radar SINR.

The maximum-distance-versus-rho panel reports both sensing cases.  The SI-on
branch uses the nonnegative phase-averaged sum `rho/R^4 + rho^2/R^8`; the no-SI
echo-self-beat branch uses `rho^2/R^8`.  The reference distance is always added
to the physical sweep grid, so a neighboring coarse sample is never relabeled
as the reference anchor.  The rho anchor stored with the sweep is also reused
when producing the analytical trade-off.  Separate `Radar SI on`, `Radar no
SI`, and `Joint SI on` curves are drawn when a valid no-SI sweep is available.

The first simulation tab applies `code/data/isac_sim_params_20260720.json` as
its startup preset without running the simulator.  The GUI overrides the preset
isolation with the paper-figure default of `24 dB`
SI-on OMT isolation.  The validation panel starts with the following paper
measurement set:

- communication EVM: `1000:-17.49`, `1100:-16.21`, `1200:-15.1` in mm:dB
- C2 band power: `1000:-38.3`, `1100:-40.6`, `1200:-42.4` in mm:dBm
- one saved C2 range-profile/Radar SINR measurement at `1100 mm`

Manual C2 entries replace a saved point only at the same distance; entering
the default 1100 mm point therefore replaces the saved point at that distance.
