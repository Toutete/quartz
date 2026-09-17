# Physics-Informed FSO 4x4 APD Receiver

## Integrated Flow

`fso_engine.py` is the single simulation API used by the GUI, dataset generator,
and tests. It integrates the installed split-step wave-optics modules with the
receiver, ADC, CNN, and communication evaluation:

```text
von Karman phase screens + split-step BPM + Taylor frozen flow
    -> annular 203.2 mm telescope entrance pupil
    -> 7.5 mm collimated pupil
    -> adjustable pupil relay (1.0 mm nominal output)
    -> 4x4 APD array and optional external MLA
    -> per-channel photocurrent and ADC
    -> temporal CNN next-frame power and r0 heads
    -> diversity combining and communication metrics
```

## Default Downlink

- TX power: 20 dBm
- Distance: 20 km
- Wavelength: 1550 nm
- TX aperture: 70 mm
- TX full-angle divergence: 28 urad
- TX/RX antenna gain cross-check: 103.1/112.3 dB
- RX telescope: EdgeHD 8, 203.2 mm aperture, 2032 mm focal length
- Central obstruction: 31% by diameter

The GUI can also run the reverse uplink geometry. Specified antenna gains are
reported only as a scalar link-budget cross-check; the wave-optics power is not
multiplied by those gains a second time.

## Receiver PoC Specification

The default receiver follows
`../concepts/FSO_OGS_APD_Array_Receiver_PoC_Spec_2026-09-17.md`:

- AC254-075-C-class 75 mm collimator and approximately 7.5 mm pupil;
- 7.5:1 adjustable pupil relay with 1.0 mm nominal output;
- 4x4 APD20D1-class InGaAs array;
- 250 um pitch, 100 um integrated lens, and 25 um nominal junction;
- 20 GHz electrical bandwidth and 28 Gbaud/channel target;
- optional 250 um-pitch external MLA with at least 95% fill factor.

Without the external MLA, each channel collects through its 100 um integrated
lens. This gives a 12.6% geometric fill factor, approximately 9 dB below a full
250 um square cell. With the MLA enabled, the clear square lenslet area is
collected with the configured optical efficiency.

The central telescope obstruction is modeled as an annular mask before pupil
reduction. It therefore appears in the reduced pupil and changes the individual
APD powers instead of being represented only by a scalar loss.

## Stable Time Display

Receiver-plane and reduced-pupil plots use physical power density in W/m2. A
single scale is calculated for the complete run from TX power, modeled optical
loss, the no-turbulence reference, and the run-wide intensity distribution.
The APD heatmap and trace axes are likewise fixed for the complete run. Moving
the frame slider updates existing image artists; it does not recreate axes or
colorbars.

## CNN and Fried Parameter

The temporal CNN receives power reconstructed from quantized APD currents. It
predicts the next normalized 4x4 power map, produces predictive combining
weights, and has an auxiliary output for `log10(r0 / Dsub)`.

The GUI trains at one selected turbulence condition, so its displayed `r0`
estimate is a supervised single-condition calibration check. A useful estimator
must be trained and validated with `ai_pd_dataset.py` over multiple `Cn2`, wind,
distance, and seed values. The offline dataset already includes `r0` in its
physics labels. Each sample also carries a simulation ID, and `train_ai_pd.py`
splits training and validation by complete simulation rather than mixing time
windows from one realization. `eval_ai_pd.py` reports `r0` MAE and MAPE.

## Diversity and Multiplexing

The equivalent 4x4 telescope subaperture is 203.2/4 = 50.8 mm. The engine uses
`r0 / 50.8 mm` to report a regime:

- below 1: strong turbulence; emphasize outage-robust or predictive MRC;
- 1 to 2: transition; keep diversity and test mode independence;
- above 2: weak turbulence; spatial multiplexing may be investigated.

The current optical model sends one beam carrying one data stream. Its 16 APD
outputs therefore demonstrate spatial diversity, not spatial multiplexing. The
GUI reports both the one-stream MRC capacity and a water-filled independent-
channel capacity proxy. This proxy is not a bound and may be lower than MRC at
low SNR. It becomes an achievable multiplexing
metric only after independent TX spatial modes and a measured/simulated MIMO
channel matrix are added.

## Run

```powershell
.\install_fso_engine_dependency.ps1
.\.venv\Scripts\python.exe -m pip install -r requirements-ai.txt
.\run_multi_pd_link_gui.ps1
```

Offline training and FPGA export remain:

```powershell
.\.venv\Scripts\python.exe .\ai_pd_dataset.py --out ai_pd_data --num-sims 20
.\.venv\Scripts\python.exe .\train_ai_pd.py --data ai_pd_data --epochs 30
.\.venv\Scripts\python.exe .\eval_ai_pd.py --data ai_pd_data --checkpoint ai_pd_runs\best_ai_pd.pt
.\.venv\Scripts\python.exe .\export_ai_pd_onnx.py --checkpoint ai_pd_runs\best_ai_pd.pt
```
