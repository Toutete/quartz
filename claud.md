# THz ISAC GUI DSP Debug Notes

## Context

- Main file: `content/Home/projects/THz_ISAC/code/isac_unified_gui.py`
- Related DSP file: `content/Home/projects/THz_ISAC/code/functions/dsp_functions.py`
- Keysight reference files checked:
  - `content/Home/projects/THz_ISAC/code/iqmain.m`
  - `content/Home/projects/THz_ISAC/code/iqmod.m`
  - `content/Home/projects/THz_ISAC/code/iqdownload_M8194A.m`
- Hardware/test path discussed: AWG-to-DSO communication capture using Keysight M8194A AWG and Keysight UXR/DSO capture.
- User observation: measured SNR is high, around 20-27 dB, but EVM is very poor and BER often cannot be computed.

## Symptoms Seen In GUI

- QPSK/16QAM demodulation showed poor EVM despite high measured SNR.
- Earlier examples:
  - QPSK: EVM around `-7.18 dB`, BER `N/A`.
  - 16QAM: EVM around `-5.85 dB`, BER `N/A`.
  - Later QPSK after attempted fixes: constellation collapsed toward the origin or one quadrant, BER around `0.45-0.49` or `N/A`.
- Latest screenshot/log showed:
  - SNR around `20.49 dB`
  - EVM around `-11.63 dB`
  - BER `N/A`
  - QAM preamble peak around `0.394`, mean around `0.112`
  - `QAM CFO/SRO refined sync` low: `sync=0.163`, `pre=0.067`
  - `TX-reference data lock` very low: about `0.009`
  - `PRBS fallback` low: about `0.061`
  - GUI fell back to decision-directed constellation only.

## Main Working Hypotheses

1. Exact IF and symbol-rate assumptions are too brittle.
   - The original demod path assumed exact `IF=10 GHz` and exact integer `nps=120` for `120 GSa/s / 1 GBd`.
   - Any residual CFO or symbol-rate offset can break reference/preamble correlation while the spectrum and SNR still look good.

2. Keysight IQTools can alter actual waveform parameters.
   - In `iqmod.m`, carrier offset is quantized to an integer number of cycles over the waveform length:
     - `cy = round(len * carrierOffset(i) / sampleRate)`
     - actual carrier offset becomes `cy * sampleRate / len`.
   - In arbitrary-resample mode, IQTools adjusts waveform length to AWG segment granularity and may change effective sample rate:
     - `newLenUpper/Lower`
     - `sampleRateUpper/Lower`
     - `iqdata = iqresample(iqdata, newLen)`
   - In `iqdownload_M8194A.m`, the M8194A raster sample rate is set with `:FREQuency:RASTer`.

3. TX reference mismatch is likely.
   - GUI-generated QAM mode inserts Zadoff-Chu preambles before PRBS data.
   - Keysight IQTools built-in QAM/PRBS may generate pure PRBS without the GUI's preamble.
   - Even when both say "PRBS11", bit order, initial state, inversion, and symbol mapping can differ.
   - A persistent preamble correlation around `0.39` with data/PRBS correlation near zero suggests a fake/random preamble peak, not a true frame lock.

4. Decision-directed fallback was unsafe for QPSK.
   - The QPSK decision-directed cleanup previously allowed wide-linear correction.
   - Wide-linear correction can collapse a PSK constellation into a single cluster or quadrant.

## Implemented Changes

### TX Metadata

- Added payload fields in `isac_unified_gui.py`:
  - `symbol_rate_actual`
  - `iqtools_if_freq`
  - `iqtools_carrier_cycles`
- Purpose: log requested vs actual/quantized values so AWG/DSP mismatch is visible.

### QAM Reference Handling

- Added deterministic QAM reference rebuild when DSO demod modulation differs from TX payload modulation.
- Added stale-reference checks including PRBS number.

### CFO/SRO-Tolerant QAM Sync

- Added fractional symbol sampling helper.
- Added QAM frame refinement that jointly searches:
  - frame start
  - residual CFO
  - samples/symbol offset in ppm
- CFO is estimated using reference-aided phase slope rather than only a coarse frequency grid.
- Fine search now considers multiple top coarse candidates, not just the single best coarse candidate.

### PRBS Fallback

- Added PRBS candidate generation beyond GUI's LFSR:
  - GUI LFSR
  - standard PN-style variants
  - IQTools-like `last-one` variants
- Added CFO-robust differential correlation for PRBS offset search.
- Added linear phase correction before BER/score estimation.
- Reduced PRBS fallback search space and cached reference windows so the live GUI does not become too slow.

### Equalizer / Symbol Correction

- Updated `sc_fde_equalizer` in `functions/dsp_functions.py`:
  - centered feed-forward equalizer
  - diagonal loading
  - safer alignment
- Added multiple equalization/reference correction candidates in GUI demod.
- Disabled wide-linear correction for PSK-like modes in the main equalizer candidate selection.

### Latest Fix After Screenshot

- Fixed `_decision_directed_symbol_cleanup` so QPSK/BPSK/8PSK do not use wide-linear correction.
- Added `_blind_qam_symbol_stream_from_mf`.
  - It searches the full matched-filter output instead of trusting a fake preamble frame.
  - It chooses timing phase/window using blind constellation quality.
  - It uses M-th power phase/frequency cleanup for PSK modes.
  - It penalizes one-cluster candidates using constellation entropy.
- If QAM/PRBS reference lock fails, the GUI now shows a blind decision-directed constellation and keeps BER as `N/A`.
- In blind metric mode, SC-FDE is disabled so blind EVM is not artificially improved by training on its own decisions.

## Validation Already Run

- `python -m py_compile content/Home/projects/THz_ISAC/code/isac_unified_gui.py content/Home/projects/THz_ISAC/code/functions/dsp_functions.py`
  - Passed.
- `git diff --check`
  - Passed.
- Synthetic QPSK CFO/SRO refinement:
  - Example: `+18 MHz`, `+1500 ppm`
  - Lock successful.
- Synthetic 16QAM CFO/SRO refinement:
  - Example: `-23 MHz`, `-1200 ppm`
  - Lock successful.
- Synthetic PRBS fallback:
  - GUI PRBS and IQTools-like PRBS candidates both locked with score near `1.0`.
- Synthetic blind QPSK fallback:
  - Recovered blind constellation with EVM around `-14 dB`, entropy around `1.0`.
- Synthetic blind QPSK fallback with clock-like drift:
  - Example: `1000 ppm` SRO plus non-linear phase drift.
  - Recovered with blind EVM around `-12.7 dB`, entropy around `1.0`.

## Important Current Interpretation

- The current real capture still does not match the GUI TX reference.
- `preamble_corr ~0.39` is not enough to claim frame lock because data and PRBS correlation are near zero.
- If the latest blind fallback still produces a one-cluster constellation, the issue is probably not only DSP reference mismatch.
- Possible non-DSP causes to check:
  - AWG is outputting a tone or wrong segment rather than the intended modulated waveform.
  - DSO channel or scaling is wrong.
  - AWG output mode differs from GUI assumption, e.g. built-in IQTools waveform vs GUI-generated Real IF waveform.
  - Actual modulation/data pattern is not the GUI PRBS/preamble reference.
  - IF sign/sideband or I/Q conjugation differs.

## Clock Reference Note

- User asked whether having no shared AWG-DSO reference clock can be the problem.
- Short answer: yes, it can contribute significantly.
- In this measurement, the 10 GHz IF is generated by the AWG sample clock and sampled by the DSO sample clock. If the instruments are free-running, the receiver can see:
  - residual CFO,
  - symbol-rate/sample-rate offset,
  - accumulated timing drift,
  - phase wander across the capture.
- Latest real log included `blind CFO=-671.39 kHz`. At a 10 GHz IF, that is about `67 ppm` equivalent frequency error if caused by clock mismatch.
- Added another blind-DSP update after this discussion:
  - vectorized fractional symbol sampler,
  - SRO candidate search in blind QPSK recovery,
  - block-wise M-th-power PSK phase tracking,
  - `blind_sro=... ppm` in the no-lock blind fallback log.
- For clean BER/EVM, lock AWG and DSO to the same 10 MHz reference when possible.

## Logs To Check Next

After restarting the GUI and demodulating again, inspect these log lines:

- `QAM CFO/SRO refined sync: ...`
  - If `sync`, `pre`, and `data` stay very low, the TX reference is not matching the capture.
- `PRBS fallback probe: score=... mode=...`
  - If mode shows `iqtools-last-one-*` and score is high, BER should become available.
  - If score remains near zero, PRBS/reference mismatch is still present.
- `No reliable QAM/PRBS lock; showing blind decision-directed constellation only...`
  - Check `blind_evm`, `blind_sro`, and `entropy`.
  - Entropy near `1.0` means four QPSK states are present.
  - Entropy near `0.0` means the capture is effectively one-cluster/one-state.

## Practical Next Steps

1. Restart the GUI so the latest code is loaded.
2. Acquire a fresh DSO capture and run Demodulate.
3. Copy the full demod log, especially the CFO/SRO, PRBS fallback, blind SRO, blind EVM, and entropy lines.
4. If blind entropy is low, verify AWG output segment and whether the AWG is playing the intended QAM waveform rather than a tone or stale segment.
5. If blind entropy is high but PRBS score is low, export or record the exact IQTools PRBS/data settings so the Python reference generator can be made bit-exact.
6. If possible, connect a common 10 MHz reference between AWG and DSO and repeat the same capture/demod flow.

## 2026-06-30 Follow-up

- Latest user log:
  - SNR around `20.6 dB`.
  - QPSK constellation appears, but EVM remains poor at about `-6.8 dB`.
  - `TX-reference data lock` and PRBS fallback score remain near zero.
  - Blind fallback reports high entropy, meaning the four QPSK states are present, but the actual captured stream is still not reference-locked.
- Interpretation:
  - Lack of shared AWG/DSO reference clock can cause CFO, SRO, timing drift, and phase wander.
  - However, the very low PRBS/reference score indicates that clock mismatch is not the only issue.
  - IQTools `iqmod.m` defaults to Root/RRC pulse shaping with `filterBeta=0.35`, while the Python GUI had QAM beta `0.25`.
  - A pulse-shaping mismatch can produce high SNR with poor EVM because the matched filter and timing eye are wrong.
- Code update:
  - QAM TX default RRC beta changed to `0.35` to match IQTools default.
  - DSO demod RRC beta default changed to `0.35`.
  - No-lock blind fallback now compares multiple receive filters:
    - payload RRC beta,
    - GUI beta,
    - IQTools beta `0.35`,
    - legacy beta `0.25`,
    - beta `0.50`,
    - raw baseband.
  - Blind fallback now also tests Gardner timing-recovery candidates instead of only fixed integer/symbol-step slicing.
  - Demod log now includes:
    - `blind_filter=...`
    - `blind_method=...`
- Validation:
  - `python -m py_compile content/Home/projects/THz_ISAC/code/isac_unified_gui.py content/Home/projects/THz_ISAC/code/functions/dsp_functions.py`
    - Passed.
  - `git diff --check`
    - Passed.
  - Synthetic QPSK case with TX beta `0.35` and primary demod beta `0.25` recovered with blind EVM around `-15.5 dB`, entropy `1.0`, using a Gardner timing candidate.

## 2026-06-30 Root-Cause Update

- Latest real capture after RRC beta update:
  - `blind_filter=payload-rrc0.35`
  - `blind_method=gardner/gain=0.0080`
  - `entropy=1.00`
  - EVM still only about `-7.9 dB`
- Interpretation:
  - RRC beta mismatch is no longer the dominant issue.
  - The persistent low `preamble_corr`, near-zero `data lock`, and PRBS score indicate the captured waveform is still not the same sample stream as the GUI reference.
  - The constellation looks like a QPSK square/ring, consistent with a corrupted or mismatched AWG sample stream.
- Found a major AWG download bug:
  - Python `functions/awg_functions.py` always downloaded `int16` samples.
  - Keysight `iqdownload_M8194A.m` sends M8194A direct-mode waveform samples as `int8(round(127*x))`.
  - Sending int16 words to an M8194A can corrupt the waveform byte stream while still producing a plausible RF spectrum.
- Code update:
  - Added `_normalize_to_int8`.
  - `download_to_awg()` now detects `M8194` in `*IDN?` and sends signed int8 samples for M8194A.
  - Non-M8194 AWGs keep the previous int16 path.
  - For M8194A, sample-rate range is set to HIGH/MED/LOW before `:FREQ:RAST`.
- Also fixed demod pre-LPF:
  - `Apply demod LPF` checkbox is now honored during demod.
  - Replaced the too-short 101-tap LPF with a zero-phase FFT raised-cosine mask.
  - QAM pre-LPF is now wider than the occupied RRC band, so it should not distort the symbol eye.
- Required next action:
  - Re-run `Download to AWG` so the M8194A receives the corrected int8 waveform.
  - Acquire a new DSO capture. Old captures from the int16 download path will still demodulate poorly.

## 2026-06-30 Additional AWG/Probe Fix

- User reported SNR near `30 dB` but EVM still around `-8 dB`, with slow/failed demod attempts.
- Interpretation:
  - This is not thermal-noise-limited behavior.
  - It indicates waveform/reference mismatch, stale/wrong AWG segment, AWG SCPI download format problems, or severe timing/phase corruption.
- Additional AWG SCPI fixes:
  - `write_binary_block()` now does not insert a space before the IEEE block when the header ends with a comma.
  - M8194A waveform upload now uses IQTools-like `:TRACe#:DATA 1,0,` before the binary block.
  - M8194A DAC mode is configured before sample-rate setup:
    - `FOUR` if channels include 2/3 or more than two channels,
    - otherwise `DUAL`.
  - Segment delete now follows IQTools style: `:TRACe#:DELete 1`, with expected delete errors drained.
  - Added SCPI error checks after sample-rate setup, segment define, waveform upload, and output enable.
- Added raw waveform sanity probe:
  - Demod now logs `raw AWG waveform lock: corr=...`.
  - If this correlation is low, the captured DSO waveform does not match the GUI's saved/downloaded AWG waveform before any DSP demodulation.
  - If this correlation is high but QAM demod is poor, then the remaining bug is inside RX DSP.
- Next diagnostic threshold:
  - Direct AWG-to-DSO should produce a strong raw waveform correlation.
  - If `raw AWG waveform lock` is below roughly `0.5`, focus on AWG segment/download/channel/clock/capture settings.
  - If it is high, inspect CFO/SRO/preamble lock and matched-filter timing.

## 2026-06-30 DAC Mode Regression Fix

- User reported a download error:
  - `Error while trying to access channel 4. This channel is disabled in DAC output mode DUAL.`
- Cause:
  - The new M8194A SCPI setup incorrectly selected `:INST:DACM DUAL` when only channel 4 was selected.
  - This disabled channel 4 on the user's instrument.
  - Sending `*RST` to M8194A during download could also disturb the DAC output mode unnecessarily.
- Fix:
  - M8194A downloads no longer send `*RST`.
  - If selected channels include `2`, `3`, or `4`, or if more than one channel is selected, the downloader sets `:INST:DACM FOUR`.
  - For channel 1 only, the downloader leaves the current DAC output mode unchanged.
  - Added a log line: `M8194A: setting DAC output mode FOUR for channels [...]`.

## 2026-06-30 GUI Settings / Auto-Sync Update

- User observed good EVM (`-27 dB`) and BER `0`, then asked what changed and requested an ON/OFF control.
- Main reason the result improved:
  - The DSO demod path started using the TX reference's actual symbol rate and modulation from the AWG panel.
  - The log line `[App] Symbol rate & modulation synced from AWG panel.` confirms this.
  - The real evidence is that QAM preamble correlation jumped to about `0.998`; demod is no longer running blind fallback.
- Added DSO UI control:
  - `Sync symbol/mod from AWG`
  - Default `ON`.
  - When OFF, the DSO panel keeps the user's manually selected symbol rate and modulation.
- DSO connection/settings:
  - Added a shared DSO settings helper.
  - Test Connection and Acquire now apply GUI settings including:
    - channel display and vertical scale,
    - DSO sample rate,
    - acquisition points,
    - derived timebase range,
    - FFT source/display,
    - FFT vertical offset/range from GUI spectrum scale fields,
    - split display layout when supported.
- AWG download:
  - Added `:ABORt` before deleting/defining segments to avoid `Operation not allowed while instrument is started`.

## 2026-06-30 PRBS / LFM-QAM Fix

- User reported:
  - 16QAM TX/demod shows only eight constellation points.
  - LFM-QAM waveform on DSO shows multiple harmonic tones and triangular noise-like spectrum.
  - LFM-QAM simulation demodulation fails.
- Root causes found:
  - `prbs_bits_lfsr()` used a PRBS11 tap/orientation combination that produced only eight 16QAM 4-bit groups.
  - TX generation made a short PRBS symbol period and tiled symbols; higher-order QAM should generate the required bit stream first, then map bits to symbols.
  - QAM waveform used RRC pulse shaping, but LFM-QAM used rectangular `np.repeat()` symbols before multiplying by the chirp.
  - Simulation demod checked `cfg.waveform == "LFM-16QAM"`, while the GUI uses `LFM-QAM`.
- Fixes:
  - Rewrote `prbs_bits_lfsr()` with standard PRBS taps and consistent Fibonacci orientation.
  - TX generation now creates the required number of PRBS bits for the requested symbol count before QAM mapping.
  - LFM-QAM TX now applies RRC pulse shaping before multiplying by the LFM chirp.
  - LFM-QAM DSO demod and simulation demod now apply the same RRC matched filter after dechirp.
  - Simulation LFM demod condition changed to any waveform containing `LFM`.
- Validation:
  - PRBS11 16QAM now uses all 16 constellation points.
  - LFM-QAM simulation default test demodulates with finite EVM, e.g. around `-17.8 dB`, SER around `5.9e-4`, `N≈20377`.
