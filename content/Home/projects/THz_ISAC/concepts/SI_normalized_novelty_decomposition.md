# Novelty Decomposition — SI-Normalized Range Detection (with references)

Is "SI-normalized single-shot range detection" an established technique or new here?
Answer: **the individual building blocks are all established; the specific combination
— using the OMT self-interference (SI) leakage as a per-capture phase reference to
make free-running self-homodyne THz range detection carrier-drift-immune in a
monostatic full-duplex ISAC link — is what is new.** Below, each component is
separated into "prior art" vs "novel here", with references.

> Caveat: this is a structured literature scan, not an exhaustive patent/paper
> novelty search. Before claiming novelty in the paper, do a formal search on the exact
> combination (self-homodyne + SI-as-phase-reference + monostatic ISAC ranging).

---

## Component-by-component

### 1. Two free-running lasers → THz via photomixing (UTC-PD)
**Established (very mature).** Optical heterodyning of two free-running lasers on a
UTC-PD is the standard photonic-THz generation method.
- Refs: Nagatsuma-era optical heterodyne THz; the ETRI companion paper
  (Sung et al., *IEEE TTHZ* 2026) uses the same free-running two-laser + UTC-PD scheme.

### 2. Self-mixing / self-heterodyne in a square-law detector cancels laser phase noise
**Established — this is a known result, not new.** Because both THz tones originate
from the same two lasers, their phase/frequency noise is common and cancels in the
square-law (SBD/ZBD) mixing product. This is exactly the mechanism your system relies
on for phase-noise-insensitive detection.
- **Key ref:** Ultra-low-phase-noise photonic THz imaging via two-tone square-law
  detection — explicitly states the two THz tones share the same free-running lasers
  so "the cross-correlation ... leads to a complete cancellation of these phase-noise
  components in the IF signal." (Opt. Express 28, 29631, 2020.)
- Related: "self-referenced homodyne detection" with "inherent common-mode phase noise
  rejection" (e.g. microwave impedance microscopy, Nat. commun-adjacent work, 2024).
- Related radar-side: envelope-detection RoF with optical heterodyne is known to be
  "phase-noise-insensitive" (Aldaya et al., IEEE PTL 25, 2193, 2013).

### 3. Transmitting a carrier/LO tone with the signal so a square-law detector recovers phase (LO-as-reference)
**Established.** Sending an LO/carrier tone alongside the data and reconstructing
amplitude+phase from a single square-law detector is the basis of the Kramers–Kronig
(KK) receiver, including its THz version.
- **Key ref:** Harter, Koos et al., "Generalized Kramers–Kronig receiver for coherent
  THz communications," *Nat. Photonics* 14, 601 (2020); KK origin: Mecozzi et al.,
  *Optica* 3, 1220 (2016).
- Distinction: KK uses a *transmitted* CW tone as the reference. Your system uses the
  *self-interference leakage* (already present in a monostatic full-duplex link) as the
  reference — you don't spend spectrum/hardware to add a reference tone.

### 4. CFR / "channel division" for range (divide RX spectrum by TX spectrum, then IDFT)
**Established (standard OFDM-radar processing).** Dividing received by transmitted
symbols to get the channel and IDFT-ing to a range profile is the Sturm–Wiesbeck
"symbol-division" / reciprocal-filtering method, widely used in OFDM-ISAC.
- **Key refs:** C. Sturm & W. Wiesbeck, "Waveform design and signal processing aspects
  for fusion of wireless communications and radar sensing," *Proc. IEEE* 99, 1236
  (2011); reciprocal filtering `g = y/x` for range–Doppler maps (numerous OFDM-ISAC
  papers). Data-dependent sidelobe issues and mismatched-filter fixes are active work
  (e.g. ROI-MMF, arXiv:2605.16831, 2026).
- Your phase-slope readout of the CFR and delay-matched profile are within this
  established family.

### 5. SSBI (signal–signal beat) carrying sensing information / "SI as useful, not just noise"
**Recently established (closest prior art in spirit).** The idea that the square-law
beat interference, usually treated as destructive, actually *carries* sensing
information and can be exploited has been published for self-coherent THz ISAC.
- **Key ref (closest):** "Signal–Signal Beating Interference: From Destructive to
  Constructive for Photonic THz Integrated Sensing and Communication System Using
  Self-Coherent OFDM" — self-coherent 144-GHz ISAC, 20 Gb/s, 1.94-cm ranging, using
  SSBI constructively. (Related to the KK/self-coherent ISAC line.)
- Distinction: that work reuses the *signal's own* beat (SSBI) in a **one-way
  comms-style self-coherent** link. Yours uses the **monostatic radar SI leakage** as
  the reference in a **full-duplex ISAC** link, and specifically to null carrier-drift
  fading of the *radar echo* range peak.

### 6. Self-interference cancellation (SIC) in monostatic full-duplex radar/ISAC
**Established — but the OPPOSITE intent.** Almost all monostatic/full-duplex ISAC work
treats SI as something to **cancel** (analog/digital SIC, antenna isolation, RIS-aided
SIC, waveform-domain separability).
- Refs: full-duplex ISAC SIC surveys and methods (e.g. waveform-domain SIC OFDM/AFDM,
  arXiv:2510.12912, 2025; RIS-enabled SIC for monostatic OFDM-ISAC, 2025; FMCW TX-leakage
  cancellation transceivers at 140 GHz, 2022).
- Distinction: you **keep** SI and **use it as an LO/phase reference** rather than
  cancelling it. This inversion (SI as resource, not impairment) is the conceptual
  novelty, shared in spirit only with the SSBI-constructive line (item 5).

### 7. Making free-running-laser radar coherent WITHOUT a comb/OPLL
**Two camps in prior art; yours is a third (processing-only) route.**
- Hardware route (established): stabilize the source — self-injection-locked lasers,
  OPLL, optical frequency comb, wavemeter. E.g. Kittlaus et al., "A low-noise photonic
  heterodyne synthesizer and its application to mm-wave radar," *Nat. Commun.* 12, 4397
  (2021) — self-injection-locked lasers remove ranging/Doppler artifacts in a 95-GHz
  FMCW radar.
- Reference-PD route (established): add a reference photodiode + electrical LO to strip
  phase-noise terms (the two-tone imaging paper, item 2).
- **Your route (the novel combination):** no comb, no OPLL, no wavemeter, no reference
  PD — the **in-band SI leakage itself** is the phase reference, applied in the digital
  CFR domain (`H/H_SI`) for **single-shot** range that is immune to carrier drift.

---

## What is genuinely new here (the claimable contribution)

Putting the pieces together, the novel contribution is **not** any single equation but
the **specific system-level combination**:

1. In a **monostatic full-duplex photonic-THz ISAC** link with **free-running lasers**
   and a **ZBD**, deliberately retain the **OMT self-interference** as a self-homodyne LO.
2. Recognize that SI and the radar echo share the **same instantaneous carrier phase**,
   so the **CFR normalization `H̃ = H/H_SI − 1`** cancels the common per-capture phase
   `e^{jψ}` and makes the **range estimate immune to free-running carrier drift**.
3. Achieve this **single-shot (num_frames = 1)** — no multi-capture averaging, no comb,
   no OPLL, no wavemeter — so it works on already-recorded data and does not smear a
   moving target.

The closest prior art is the **SSBI-constructive self-coherent THz ISAC** line (item 5)
and the **KK / LO-as-reference** receivers (item 3); the key differentiators are
(i) using **monostatic SI leakage** (not a transmitted CW tone or the signal's own SSBI)
as the reference, and (ii) targeting **carrier-drift-immune single-shot radar ranging**
in a full-duplex link, rather than comms phase recovery.

---

## Suggested framing for the paper

- Do **not** claim "we invented self-homodyne phase-noise cancellation" (item 2 is
  established) or "we invented channel-division ranging" (item 4 is Sturm–Wiesbeck).
- **Do** claim: "we repurpose the monostatic self-interference as a built-in phase
  reference and show, analytically and experimentally, that SI-referenced CFR
  normalization yields single-shot, carrier-drift-immune range detection with
  free-running lasers and a ZBD, eliminating the comb/OPLL/wavemeter otherwise required."
- Cite items 2, 3, 4, 5, 6, 7 as the lineage; position against item 5 (SSBI-constructive)
  and item 6 (SIC-as-cancellation) as the two nearest contrasts.

---

## Reference list (for convenience)

1. C. Sturm and W. Wiesbeck, "Waveform design and signal processing aspects for fusion
   of wireless communications and radar sensing," *Proc. IEEE*, 99(7), 1236–1259, 2011.
2. Two-tone square-law THz imaging with complete phase-noise cancellation,
   *Opt. Express* 28(20), 29631, 2020.
3. T. Harter et al. (C. Koos), "Generalized Kramers–Kronig receiver for coherent THz
   communications," *Nat. Photonics* 14, 601–606, 2020. (arXiv:1907.03630)
4. A. Mecozzi et al., "Kramers–Kronig coherent receiver," *Optica* 3(11), 1220, 2016.
5. "Signal–Signal Beating Interference: From Destructive to Constructive … Self-Coherent
   OFDM" photonic THz ISAC (self-coherent 144 GHz, 20 Gb/s, 1.94 cm ranging).
6. E. A. Kittlaus et al., "A low-noise photonic heterodyne synthesizer and its
   application to millimeter-wave radar," *Nat. Commun.* 12, 4397, 2021.
7. I. Aldaya et al., "Phase-insensitive RF envelope detection allows optical heterodyning
   of MHz-linewidth signals," *IEEE Photon. Technol. Lett.* 25(22), 2193, 2013.
8. M. Sung et al., "Efficient Uplink Configuration for 6G Fronthaul in Photonic THz
   Communications via Optical Carrier Sharing," *IEEE Trans. THz Sci. Technol.*, 2026.
9. Waveform-domain SIC for full-duplex ISAC (OFDM/AFDM), arXiv:2510.12912, 2025.
10. RIS-enabled SIC in monostatic OFDM-ISAC, 2025; ROI mismatched-filter OFDM-ISAC
    ranging, arXiv:2605.16831, 2026.

> Exact bibliographic details of items 2 and 5 should be verified on IEEE Xplore /
> Optica before inclusion; titles/venues above are from the literature scan.
