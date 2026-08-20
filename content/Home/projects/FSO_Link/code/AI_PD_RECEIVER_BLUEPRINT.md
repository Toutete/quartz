# AI-Assisted Multi-Aperture PD Receiver Blueprint

## Goal

Build a ground-satellite FSO receiver that reduces turbulence-induced fading by placing multiple photodiodes in the receiver pupil/focal geometry, digitizing each PD as an independent FPGA channel, and using a CNN predictor to assign adaptive combining weights.

## Signal Chain

1. Optical front-end
   - Receiver aperture or lens array collects the distorted wavefront.
   - PDs are placed at predefined spatial coordinates.
   - Each PD produces one electrical channel.

2. FPGA/DSP front-end
   - Per-channel TIA/ADC samples are aligned in time.
   - DC removal, gain calibration, and optional matched filtering are applied.
   - A short window of recent channel powers is formed:
     `(time_window, pd_rows, pd_cols)`.

3. AI estimator
   - CNN input: log-normalized recent PD powers.
   - Output A: next-step/future PD power map.
   - Output B: physical state estimate such as `log10(Cn2)`, range, wind speed, beam waist, `r0`, and Rytov variance.

4. Adaptive combiner
   - Predicted future powers are converted to nonnegative weights.
   - FPGA applies Q1.15 fixed-point weights to PD channels.
   - Baseline rule is MRC-like weighting:
     `w_i = P_i_hat / sum(P_hat)`.

## Training Stage

1. Generate many simulated turbulence cases.
   - Randomize `Cn2`, range, wind speed, waist, and phase-screen seeds.
   - Use the current `fso_engine.py` first.
   - Later replace the simulator boundary with HCIPy/AOtools/LightPipes if higher fidelity is needed.

2. Save supervised samples.
   - Input: recent PD power window.
   - Label 1: future PD power map.
   - Label 2: optimal combining weight map.
   - Label 3: physical parameters.

3. Train CNN.
   - Loss = future-power MSE + weight-map MSE + physical-parameter MSE.
   - The saved checkpoint includes normalization statistics.

## Prediction Stage

1. FPGA or host accumulates the latest PD power window.
2. CNN predicts future channel powers and turbulence state.
3. Predicted powers are normalized into weights.
4. Weights are quantized to Q1.15 for FPGA DSP.
5. Weighted channels are summed.

## Commands

Install AI dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-ai.txt
```

Generate a small dataset:

```powershell
.\.venv\Scripts\python.exe .\ai_pd_dataset.py --out ai_pd_data --num-sims 20 --grid-n 256
```

Train:

```powershell
.\.venv\Scripts\python.exe .\train_ai_pd.py --data ai_pd_data --epochs 30
```

Export for FPGA toolchains:

```powershell
.\.venv\Scripts\python.exe .\export_ai_pd_onnx.py --checkpoint ai_pd_runs\best_ai_pd.pt
```

Run prediction from measured/simulated traces:

```powershell
.\.venv\Scripts\python.exe .\predict_ai_pd_weights.py --checkpoint ai_pd_runs\best_ai_pd.pt --input traces.npy
```

`traces.npy` shape must be `(pd_rows, pd_cols, frames)`.

## FPGA Notes

- Keep the first model small. The included CNN uses depthwise separable convolutions and fixed output sizes.
- Export ONNX, then quantize with the FPGA vendor flow or convert weights manually.
- The final combiner coefficients can be represented as unsigned Q1.15 values.
- Start with host-side AI inference and FPGA-side weighted combining. Move inference onto FPGA only after validating latency and accuracy.

