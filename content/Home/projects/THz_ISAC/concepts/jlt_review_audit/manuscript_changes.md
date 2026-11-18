# JLT 원고 교체 문구

TVT 제출본의 식과 절 번호를 위치 표지로 사용했습니다. 아래 문구는 독립 분석 결과를 반영한 내부 작성안입니다. 그림과 데이터의 원본 연결이 남은 경우 적용 범위를 각 항목에 적었습니다.

## M00 Abstract · 동작 범위와 검증된 결과

> We demonstrate a shared-aperture photonic 280-GHz architecture that reuses residual transmit leakage as a reference for square-law detection of the monostatic echo. The same transmitted waveform supports the downlink and sensing. In the available 20-GBd 32-cross-QAM record, reference-aided demodulation gives a gross line rate of 100 Gb/s, an rms EVM of −15.77 dB, and a hard-decision BER of 3.875%. For a separate 15-GBd ranging record near 1.10 m, regularized channel-response processing increases the target-to-median-background contrast while preserving the estimated target position.

Figs. 5/6 최종 매핑이 일치하면 이 수치를 초록에 사용합니다. 83.3 Gb/s 및 2% BER 통과 문장은 실제 송·수신 mapping과 FEC 근거 확보 후 재평가합니다.

## M01 Introduction · 적용 범위와 동기

> Here, monostatic full duplex denotes transmission of a downlink waveform while receiving its echo through a shared aperture. The architecture uses the residual leakage after passive isolation to supply the reference field at the detector. The existing 280-GHz photonic link provides the operating band and a platform for evaluating wideband sensing with an aligned static target.

## M02 Receiver setup and operating region · 평균과 피크

> With the reported average residual SI of approximately −33 dBm at the LNA input, a typical LNA gain of 13 dB and an assumed 1–2 dB interstage loss imply approximately −22 to −21 dBm at the ZBD input. The resulting 1–2 dB average margin to the reported compression criterion must be considered together with the modulation crest factor and the frequency-dependent receiver response. A power sweep of the installed receiver is required to establish its usable square-law region.

수치는 송신 −10 dBm을 전체전력으로 해석한 경우입니다. 캐리어 해석의 약 0.21 dB 차이도 [예산표](receiver_power_budget.csv)에 포함합니다.

## M03 Contributions · 구체적인 시스템 기여

> The system integrates a photonic 280-GHz transmitter, a shared-aperture duplexer, and a detector that combines the residual transmit reference with the echo. We derive the phase-conditioned detector response, evaluate the conditions that bound useful reference power, and describe the post-detection processing used to extract range from the recorded waveform.

## M04 Signal model · 계수와 위상 평균

> Let \(a=\sqrt{P_{\mathrm{SI}}}\) and \(b=\sqrt{P_{\mathrm{ec}}}e^{-j\phi}\) denote the carrier fields at the same receiver plane. The undelayed and delayed coefficients are \(C_0=(a+b)^*a\) and \(C_\tau=(a+b)^*b\). The delayed real-IF power is \(2m^2|C_\tau|^2\) for a unit-power data waveform. The term proportional to \(\cos\phi\) vanishes under the stated phase average. The differential phase remains in a single acquisition.

## M05 SI normalization · 검파 후 처리

> The leakage and echo mix in the square-law detector. In post-detection DSP, the recorded CFR is divided by its occupied-bin complex mean and the constant baseline is subtracted. The scalar operation removes a common complex factor and the constant subtraction removes the zero-delay aperture response. The frequency-dependent front-end response can remain in the resulting range profile.

## M06 Multipath · 단일 경로 근사

> With multiple leakage paths, the receiver input contains a coherent sum of the delayed leakage fields and the target echo. The strength of the carrier reference and the shape of the estimated baseline depend on both the relative phases and delays. A dominant leakage path provides the basis for the two-path approximation. In an independent synthetic sweep, stronger secondary leakage paths produced additional peaks and constructive or destructive reference interference.

시뮬레이션 가정과 grid는 [다중경로 결과](multipath_sensitivity.csv)에 있습니다.

## M07 Sensing and communication SINR · 잡음 기준면

> The desired sensing and communication powers are defined in equivalent detector-output power-product units. The sensing numerator follows from the phase-conditioned \(C_\tau\) and a stated phase average. The communication branch uses the carrier–sideband self-beat of the one-way link. The carrier–noise coefficient depends on the accepted RF image bands and their integrated noise powers. The receiver floor, the in-band SSBI coefficient, and the coherent processing gain are specified at their respective reference planes.

실제 RF image·ENBW와 후처리 \(\kappa\)의 출처를 확정한 후 식 (12)/(16)의 계수와 부록을 맞춥니다. 독립 파형 실험의 pre-CFR 계수는 해당 장비의 교정값으로 이식하지 않습니다.

## M08 Fig. 6과 Fig. 7 · 측정 통계와 이론 곡선

> The range profile is evaluated using the target-to-median-background power ratio. The target is the strongest cell within ±40 mm of the nominal range, and the off-target floor is the median linear power over 0.5–2.0 m after excluding ±2 nominal range cells around the selected target. The corresponding excess ratio in Eq. (19) depends on the search and background mask. We report the fixed-cell and mean-background variants separately. Model SINR is shown with its own definition and units.

> For the available 1.10-m ranging record, the full-reference matched filter and normalized CFR both place the peak at 1.0975 m on the reprocessing grid. Their target-to-median-background contrasts are 20.12 and 33.34 dB, respectively.

Fig. 7에서는 실측 contrast와 모델 SINR의 축·패널을 명시합니다. 같은 지표의 수치 예측 또는 H0 교정이 확보되면 정량 일치와 경험적 검출 기준을 복원할 수 있습니다. 13.2 dB 선은 명목 AWGN 단일 셀에만 적용합니다.

## M09 Waveform, CP and measurement protocol · 캡처별 조건

> The archived 15-GBd ranging reference contains 15 consecutive 8192-sample blocks on the 120-GSa/s processing grid, each with 1024 active subcarriers. The archived 20-GBd record contains ten 6144-sample blocks. Neither archived frame contains a cyclic prefix. Each active block combines the communication data with a superimposed Zadoff–Chu component using a nominal component-power weight of 0.20. The stored C1 and C2 waveforms are sampled at 256 GSa/s and downconverted before resampling to the transmitter grid. Equation (18) uses rectangular block FFTs and an occupied-bin-referenced regularizer of \(10^{-3}\). A delayed echo crosses adjacent transmit blocks, so the diagonal subcarrier model is an approximation.

별도 시간 슬롯이나 주파수 자원을 쓰지 않았다는 문구는 실제 구성과 일치할 때 사용할 수 있습니다. Fig. 8의 이동 수치를 사용하려면 두 원시 기록, 물리 이동 기록과 보정을 함께 식별합니다.

## M10 Comparison and numerical checks · 공정한 기준

> The ideal echo-only calculation preserves the transmitted waveform and target echo while setting the leakage coupling to zero. At equal complex reference field and echo at the detector, a separately supplied homodyne reference gives the same delayed linear-IF term. The system comparison therefore reports reference delivery, dynamic range, bandwidth, and receive functions as separate attributes.

## M11 Discussion · 해석 범위

> The experiment uses a static, aligned receive horn as the reflecting target. The displacement experiment examines a shift on the scale of a bandwidth-limited range cell. Absolute range accuracy, target separability, and false-alarm and detection probabilities require dedicated acquisitions with calibrated positions, independent repeats, and target-absent records.

## M12 Conclusion · 근거 확보 범위

> The results illustrate how a residual transmit reference can be retained in a shared-aperture photonic ISAC receiver and used for square-law sensing during downlink transmission. The achievable reference level depends on the detector input range, the transmitted waveform, and the leakage channel. The archived captures also show why waveform metadata, bit labeling, and the definition of the reported sensing statistic matter when comparing measurements with the model.

## M13 Photocurrent · 조건부 추가 문구

> In the archived 15-GBd sweep, increasing the photocurrent improves the measured communication EVM for both recorded constellations. The 32-QAM sensing contrast varies nonmonotonically across the available records. Photocurrent changes both the echo and the leakage through the transmitted power. A calibrated \(P_t(I_{\mathrm{ph}})\) curve and repeated measurements are required to identify the underlying effects and establish the operating region.

수신기 선형성의 증거로 EVM 추세만 사용하지 않습니다. 별도 측정으로 확보될 때까지 photocurrent-controlled 동작을 제목의 중심 주장으로 쓰지 않습니다.
