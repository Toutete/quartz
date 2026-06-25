---
title: RX 캡처 및 DSP 복조 체인
is_public: false
---

# RX 캡처 및 DSP 복조 체인

## 1. DSO 캡처 흐름

```
ZBD 출력 (DC + 15 GHz 신호 + 30 GHz)
    │
    ▼
[DSO] 캡처
    │  SCPI: :WAVeform:DATA? → IEEE 488.2 바이너리 블록
    │  raw int16 → voltage 변환
    ▼
[오프라인 DSP]  ← .csv / .hdf5 / .npz 파일로 전달
```

## 2. 지원 DSO 및 연결 프로토콜

`dso_functions.py`의 `create_dso_controller()` 팩토리 함수로 선택:

| DSO | 프로토콜 | 포트 | 클래스 |
|-----|----------|------|--------|
| Keysight UXR0404A | Raw SCPI | 5025 | `KeysightUxrDso` |
| LeCroy / Teledyne LabMaster | VICP | 1861 | `LecroyVicpDso` |
| 오프라인 테스트 | — | — | `DummyDsoController` |

### Keysight UXR0404A 스펙

| 항목 | 값 |
|------|-----|
| 아날로그 BW | 40 GHz |
| 샘플링 레이트 | 256 GSa/s (4채널 동시, 속도 손실 없음) |
| ADC 해상도 | 10-bit (ENOB ≤ 8.7) |
| 메모리 | 최대 2 Gpts |
| 권장 채널 쌍 | CH1 + CH3 (격리도 최적) |

### 샘플링 레이트 전략

신호 대역 ≤ 20 GHz이면 낮은 $f_s$로 긴 캡처가 유리합니다:

$$T_{capture} = \frac{N_{pts}}{f_s}$$

예: 2 Gpts / 30 GSa/s = **67 µs** 캡처 → FFT 분해능 $\Delta f = f_s / N = 15$ Hz

| 모드 | 권장 $f_s$ | 이유 |
|------|-----------|------|
| 톤 브링업 | 30 GSa/s | 긴 캡처, 높은 주파수 분해능 |
| 16-QAM 광대역 | 50~60 GSa/s | 나이퀴스트 > 2 × 20 GHz |

### Keysight SCPI 캡처 시퀀스

```python
:WAVeform:SOURce CHAN{n}
:WAVeform:FORmat WORD          # int16
:WAVeform:BYTeorder LSBFirst   # little-endian
:WAVeform:UNSigned OFF         # 부호있는 정수
:WAVeform:PREamble?            # 스케일링 정보 (x_inc, y_inc 등)
:WAVeform:DATA?                # 파형 데이터 (IEEE 488.2 바이너리 블록)
```

전압 변환:
$$V[n] = (raw_{i16}[n] - y_{ref}) \times y_{inc} + y_{orig}$$

### VICP 프레임 구조 (LeCroy)

```
byte 0-1: 0x01 0x01  (버전)
byte 2  : 0x09       (DATA + EOI)
byte 3  : sequence number (1-255)
bytes 4-7: payload 길이 (big-endian uint32)
```

## 3. DSP 복조 체인 (10단계)

### 단계별 처리

| 순서 | 단계 | 방법 | 근거 |
|------|------|------|------|
| 0 | DC 제거 | `signal -= signal.mean()` | ZBD 제곱법칙의 강한 DC 항 |
| 1 | 대역 제한 | FIR BPF [10, 20] GHz | SNR 향상, 앨리어싱 방지 |
| 2 | SIM 다운컨버전 | $\times e^{-j2\pi f_{IF} t}$ → LPF | 기저대역으로 복원 |
| 3 | 정합 필터 | RRC (TX와 동일 파라미터) | ISI 최소화, SNR 최대화 |
| 4 | **프레임 동기** | Zadoff-Chu + 교차상관 | CAZAC 날카로운 피크 |
| 5 | **타이밍 동기** | Gardner TED 또는 다상 보간 | 반송파 위상 독립적 |
| 6 | 잔류 CFO/위상 | 파일럿 기반 선형 위상 보정 | ZBD가 레이저 위상잡음 이미 제거 |
| 7 | 채널 추정 | LS (파일럿 블록) | 실내 LoS ≈ 평탄한 채널 |
| 8 | 등화 | FIR MMSE (3~5탭) 또는 1탭 SC-FDE | 평탄 채널에 적합 |
| 9 | 정규화 | AGC / 스케일 | 16-QAM은 진폭 정보 포함 |
| 10 | 디매핑 + 성능 | 16-QAM Gray 결정, EVM/BER | 성능 평가 |

### 프레임 구조

```
[ Zadoff-Chu Preamble | Pilot Block | 16-QAM Data | ... ]
        ↑                    ↑
   프레임·타이밍 동기      채널 추정 + 잔류 위상 보정
```

### Gardner TED (타이밍 오차 검출)

시각 $k$에서의 타이밍 오차 신호:

$$e[k] = \text{Re}\left[y\!\left(k - \tfrac{1}{2}\right)\!\left(y^*[k] - y^*[k-1]\right)\right]$$

이 오차를 PI 루프 필터에 통과시켜 샘플링 위상을 보정합니다.
ZBD가 레이저 위상잡음을 이미 상쇄했으므로 루프 부담이 최소화됩니다.

### MMSE 등화

주파수 도메인 MMSE:

$$W_{MMSE}(f) = \frac{H^*(f)}{|H(f)|^2 + \sigma_n^2 / \sigma_s^2}$$

- $H(f)$: LS 채널 추정 결과
- $\sigma_n^2 / \sigma_s^2 = 1/\text{SNR}$: 잡음 억제 파라미터

> ⚠ **비선형 왜곡은 등화 불가** — MZM/UTC-PD/앰프 구동 레벨을 낮춰서 해결.

## 4. SIC (자기 간섭 제거)

ZBD 자기동조 덕분에 위상잡음 SI는 이미 상쇄됩니다.
잔류 선형 SI를 제거하는 두 가지 알고리즘이 `dsp_functions.py`에 구현되어 있습니다 (현재 placeholder):

### 교차편광 SIC

OMT가 RHCP/LHCP로 TX/RX를 분리하지만, 유한한 격리도로 인해 잔류 SI가 남습니다.
SI 기준 신호(TX 레퍼런스)와 적응 필터로 제거:

```python
rx_clean, info = apply_cross_polarization_sic(
    rx_signal, tx_ref,
    num_taps=64, mu=1e-4, lam=0.999,
    max_lag=500, adapt_len=None
)
```

### 선형 RLS SIC

$$\mathbf{w}_{k+1} = \lambda^{-1}\mathbf{P}_k\,\mathbf{u}_k\,\xi_k^*$$

λ: 망각 인수 (≈ 0.999), 빠른 채널 변화에 대응

```python
rx_clean, info = apply_linear_rls_sic(
    rx_signal, tx_ref,
    num_taps=32, lam=0.999,
    max_lag=200, adapt_len=None
)
```

## 5. 레이더 감지 (Sensing Path)

TX 파형과 RX 파형의 교차 상관:

$$R(\tau) = \int s_{TX}(t)\,s_{RX}^*(t - \tau)\,dt$$

피크 지연 $\hat{\tau}$에서 거리 추정:

$$\hat{R} = \frac{c\,\hat{\tau}}{2}$$

도플러 보정 (이동 타깃):

- 270 GHz에서 1.5 m/s → $f_D \approx 2.7$ kHz
- 1024 심볼 동안 위상 회전 ≈ 10° → 복소 곱 한 번으로 보정

## 6. 코드 파일

- `code/functions/dso_functions.py` — DSO 드라이버 (`KeysightUxrDso`, `LecroyVicpDso`, `create_dso_controller`)
- `code/functions/dsp_functions.py` — DSP 알고리즘 (`align_symbols_for_ber`, `apply_linear_rls_sic` 등)
- `code/rx/dso_demod.py` — LFM-QAM 복조 독립 스크립트 (live / trc / sim 모드)
- `code/isac_unified_gui.py` — GUI RX 탭

## 7. 관련 노트

- [[00_system_architecture]] — 전체 신호 흐름
- [[01_tx_signal_generation]] — TX 파형 생성
- [[../HANDOFF]] — §5 DSO 캡처 전략, §6 수신기 DSP 체인 상세
