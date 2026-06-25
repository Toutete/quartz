---
title: TX 신호 생성 및 AWG 연동
is_public: false
---

# TX 신호 생성 및 AWG 연동

## 1. TX 신호 생성 흐름

```
PRBS 비트열
    │  prbs_bits_lfsr(n=11, length)
    ▼
QAM 심볼 매핑
    │  bits_to_qam_symbols() — 16-QAM Gray 코딩
    ▼
RRC 펄스 성형
    │  α = 0.35, 오버샘플링 비율 = AWG fs / Baud rate
    ▼
SIM 업컨버전
    │  s(t) = Re[x(t) · exp(j2π·f_IF·t)],  f_IF = 15 GHz
    ▼
정규화 → int16
    │  normalize_real_for_awg() → _normalize_to_int16()
    ▼
AWG 다운로드 (TCP/SCPI)
```

## 2. SIM (Subcarrier Intensity Modulation) 원리

기저대역 복소 신호 $x(t)$를 IF $f_{IF}$로 업컨버전:

$$s_{TX}(t) = \text{Re}\left[x(t)\,e^{j2\pi f_{IF} t}\right]$$

이 실수 신호가 MZM을 통해 광 강도를 변조합니다.
UTC-PD 및 ZBD의 제곱법칙 검파 후 기저대역으로 복원됩니다:

$$v_{det}(t) \propto s_{TX}^2(t) \xrightarrow{BPF@f_{IF}} \frac{1}{2}|x(t)|^2 + \text{Re}\left[x^2(t)\,e^{j4\pi f_{IF}t}\right]$$

HPF로 SSBI($[0, B]$ 영역)를 제거하면 원하는 신호만 남습니다.

### SSBI 회피 조건

$$f_{IF} > \frac{3B}{2}$$

- $B = 5$ GHz (10 GBaud, RRC 롤오프 포함)
- 최소 $f_{IF} > 7.5$ GHz → **15 GHz 사용** (충분한 여유)
- 신호 대역: $[10, 20]$ GHz

## 3. MZM 변조 지수

MZM 전송 함수 (X-cut, 직교점 바이어스):

$$E_{out}(t) = E_{in} \cos\!\left(\frac{\pi\,V(t)}{2\,V_\pi}\right)$$

변조 지수 $m$:

$$m = \frac{\pi\,V_{RF,peak}}{2\,V_\pi}$$

| 변수 | 값 |
|------|-----|
| $V_\pi$ (10 GHz) | ≈ 6 V |
| 목표 $m$ | 0.2 (선형 동작 보장) |
| $V_{RF,peak}$ | $\approx 0.2 \times 2V_\pi / \pi \approx 0.76$ V |
| AWG 출력 | ≈ 122 mVpp |
| 구동 체인 | AWG → +29 dB 앰프 → −10 dB 감쇠기 → MZM |

> ⚠ $m \approx \pi/2$까지 올리면 $\cos^2$ 비선형 → **16-QAM 파괴**. 반드시 $m \leq 0.3$ 유지.

## 4. AWG 연동 (SCPI over TCP)

### 연결 방식

`awg_functions.py`의 `AwgSocketController`는 Raw TCP 소켓으로 SCPI를 전송합니다.
pyvisa 없이도 동작하며, IEEE 488.2 바이너리 블록 형식으로 파형 데이터를 전송합니다.

```
VISA 주소: TCPIP0::<host>::<port>::SOCKET
기본 포트: 60007 (Keysight M8194A/M8195A)
```

### 파형 다운로드 SCPI 시퀀스

```python
*RST                            # 초기화
:FREQ:RAST <fs>                 # 샘플링 레이트 설정
:OUTP{ch} OFF                   # 출력 비활성화
:TRAC{ch}:DEL:ALL               # 기존 세그먼트 삭제
:TRAC{ch}:DEF 1,<N>             # 세그먼트 1 정의 (N샘플)
:TRAC{ch}:DATA 1,0 #<d><len><bytes>  # IEEE 488.2 바이너리 블록 전송
*OPC?                           # 전송 완료 대기
:TRAC{ch}:SEL 1                 # 세그먼트 선택
:VOLT{ch} <Vpp>                 # 진폭 설정
:OUTP{ch} ON                    # 출력 활성화
:INIT:IMM                       # 즉시 실행
```

### 데이터 형식

```python
# float64 [-1, 1] → int16 변환
sig_i16 = (sig / np.max(np.abs(sig)) * 32767).astype(np.int16)
raw_bytes = sig_i16.tobytes()

# IEEE 488.2 헤더: #<자릿수><바이트수><데이터>
# 예: 100,000 샘플 × 2 bytes = 200,000 bytes
# 헤더: #6200000
```

### Keysight M8194A 스펙 제한

| 항목 | 제한 |
|------|------|
| 최대 샘플링 레이트 | 120 GSa/s |
| 아날로그 BW | 45 GHz |
| DAC 해상도 | 8-bit |
| 최대 진폭 | 0.8 Vpp (단측) / 1.6 Vpp (차동) |
| 전압 윈도우 | −1.0 ~ +2.5 V |

## 5. 코드 파일

- `code/functions/awg_functions.py` — Raw TCP SCPI 드라이버 (`AwgSocketController`, `download_to_awg`)
- `code/functions/dsp_functions.py` — 변조 함수 (`prbs_bits_lfsr`, `bits_to_qam_symbols`, `normalize_iq_for_awg`)
- `code/tx/keysight_awg.py` — pyvisa 기반 드라이버 (대안)
- `code/isac_unified_gui.py` — `IsacTxSimPanel` 클래스 (GUI에서 TX 제어)

## 6. 관련 노트

- [[00_system_architecture]] — 전체 신호 흐름
- [[02_rx_demodulation]] — 수신 및 복조
- [[../HANDOFF]] — §3 바이어스·구동 설정 상세
