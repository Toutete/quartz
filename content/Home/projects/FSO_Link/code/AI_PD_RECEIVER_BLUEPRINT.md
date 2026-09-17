# Colleague FSO Multi-PD Receiver

## Purpose

This folder contains one FSO simulation path. The optical propagation engine is
the locally installed colleague simulator under `external/FSO-simulator`; the
former standalone SSFM GUIs and simplified channel engine have been removed.

The integrated receiver evaluates this chain:

```text
colleague von Karman phase screens + split-step BPM
    -> receiver-plane optical intensity
    -> circular receiver-lens aperture
    -> power-preserving beam reduction
    -> Multi-PD or PD-array collection
    -> responsivity, current noise, and per-channel ADC
    -> temporal CNN next-frame prediction
    -> digital combining
    -> SNR, EVM, BER, outage probability, and fade margin
```

## Time-Domain Physics

One set of colleague von Karman phase screens is generated for each run. The
screens are shifted between frames according to the configured wind speed,
wind direction, and frame interval. This is a discrete-grid Taylor frozen-flow
model, so adjacent frames are physically correlated rather than independent
random-seed realizations.

The GUI reports Fried parameter, Greenwood frequency, Rytov variance, Strehl
ratio, aperture capture, scintillation index, lag-one temporal correlation, and
split-step power-conservation error.

## Link Direction and Default Downlink

The GUI can run either direction. `downlink` places the transmitter at the
configured upper altitude and the receiver at ground level; `uplink` reverses
those endpoints. The order of the altitude-dependent phase screens is also
reversed, so this is not only a plot label.

The default downlink is:

- TX power: 20 dBm
- vertical distance: 20 km
- wavelength: 1550 nm
- TX lens diameter: 70 mm
- TX full-angle divergence: 28 urad
- TX antenna gain: 103.1 dB
- RX lens diameter: 203.2 mm
- RX antenna gain: 112.3 dB

The 28 urad value is interpreted as full-angle Gaussian divergence. The 70 mm
aperture clips the inferred 35.24 mm waist to 35.00 mm, giving a modeled full
angle of 28.19 urad. The ideal gains calculated from `20 log10(pi D/lambda)` are
103.04 dB and 112.29 dB, consistent with the specified link-budget gains.
Specified antenna gains are used only for the scalar link-budget cross-check;
they are not multiplied into the wave-optics result, where diffraction and
aperture collection are already modeled explicitly.

## Receiver Optics

The first GUI tab shows two synchronized optical planes for the selected time
frame:

1. Receiver-plane intensity before aperture clipping. The receiver lens is a
   green dashed circle.
2. The power-preserving reduced plane after clipping and demagnification. The
   reduced pupil is a green dashed circle and each PD active area is a cyan
   dashed circle.

When the microlens option is enabled, dotted square collection cells show the
area redirected to each PD. Microlens efficiency is limited to 0 through 1, so
the model cannot create optical power.

## CNN and Combining

The temporal CNN receives per-PD power reconstructed from quantized ADC
currents, not ideal simulator power. It predicts the next normalized PD power
map and derives nonnegative combining weights from that map.

The training objective contains:

- next-frame log-power error;
- an electrical-SNR proxy based on the predicted weights; and
- a total-power consistency term.

The communication comparison includes a center PD, selection combining, EGC,
oracle MRC, and the predictive CNN. Electrical SNR includes detector NEP,
configured current noise, shot noise, and ADC quantization noise. BER uses the
standard Gray-coded square M-QAM approximation.

`Additional optical loss` represents losses not contained in the normalized
wave-optics propagation, such as lens transmission, filter loss, coupling loss,
and deliberate attenuation before the TIA. Its default is 30 dB so the
high-optical-power 20 km example does not immediately saturate the default
50 uA ADC range.

## Install and Run

Install or update the colleague simulator:

```powershell
.\install_colleague_fso_simulator.ps1
```

Install Python dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-ai.txt
```

Run the single integrated GUI:

```powershell
.\run_multi_pd_link_gui.ps1
```

The default experiment is the 20 km downlink above at one selected `Cn2`. Use
the direction selector for uplink, and use the frame slider or Play control to
inspect the synchronized receiver plane, reduced plane, PD map, and PD power
traces.

## Offline Dataset and FPGA Export

`ai_pd_dataset.py` now calls the same colleague-based physical engine used by
the GUI. The remaining offline flow is:

```powershell
.\.venv\Scripts\python.exe .\ai_pd_dataset.py --out ai_pd_data --num-sims 20
.\.venv\Scripts\python.exe .\train_ai_pd.py --data ai_pd_data --epochs 30
.\.venv\Scripts\python.exe .\eval_ai_pd.py --data ai_pd_data --checkpoint ai_pd_runs\best_ai_pd.pt
.\.venv\Scripts\python.exe .\export_ai_pd_onnx.py --checkpoint ai_pd_runs\best_ai_pd.pt
```

For FPGA deployment, start with Q1.15 combining weights and host-side inference.
Move the compact CNN into the FPGA only after the optical and communication
metrics are validated against measured PD traces.
