---
title: OMT S-파라미터 시뮬레이션
is_public: false
---

# OMT S-파라미터 시뮬레이션

## 1. 개요

`sim/back2back_sim.py`는 단일 OMT의 S9P 측정 데이터로부터
Back-to-Back(B2B) 배치의 성능을 **행렬 예측**하고,
12포트 EM 시뮬레이션 결과와 비교합니다.

### 사용 데이터 파일

| 파일 | 내용 | 포트 수 |
|------|------|---------|
| `OMT_Square.s9p` | 사각형 OMT 단일 소자 S-파라미터 | 9 |
| `OMT_CW.s9p` | CW형 OMT 단일 소자 S-파라미터 | 9 |
| `OMT_S2S_180deg.s12p` | Square OMT B2B 180° EM 시뮬 | 12 |
| `OMT_S_CW_S_180deg.s12p` | CW OMT B2B 180° EM 시뮬 | 12 |

## 2. OMT 포트 구조

S9P 단일 OMT 포트 인덱스 매핑 (0-based):

```
[0, 1, 2]: Circular 3 포트 (내부 — 공통 원형 도파관)
[3, 4, 5]: Rectangular 1 포트 (외부 — RHCP 편파)
[6, 7, 8]: Rectangular 2 포트 (외부 — LHCP 편파)
```

편파 분해:

$$S_{co} = \frac{S_{0,3} - j\,S_{1,3}}{\sqrt{2}} \quad \text{(동편파, Co-pol)}$$

$$S_{cross} = \frac{S_{0,3} + j\,S_{1,3}}{\sqrt{2}} \quad \text{(교차편파, Cross-pol)}$$

## 3. GSM (Generalized Scattering Matrix) 결합

두 OMT를 Back-to-Back 배치할 때 Redheffer Star Product를 사용합니다.

### 행렬 분할

단일 OMT의 S-행렬을 내부 포트($A$)와 외부 포트($B$)로 분할:

$$\mathbf{S} = \begin{bmatrix} \mathbf{S}_{AA} & \mathbf{S}_{AB} \\ \mathbf{S}_{BA} & \mathbf{S}_{BB} \end{bmatrix}$$

- $\mathbf{S}_{AA}$: 6×6 (외부 포트 간)
- $\mathbf{S}_{BB}$: 3×3 (내부 포트 간)
- $\mathbf{S}_{AB}$, $\mathbf{S}_{BA}$: 교차 전달

### 원형 도파관 위상 보정

두 OMT 사이 원형 도파관 길이 $L$ mm, TE11 모드 위상 정수:

$$\beta = \frac{2\pi f}{c}\sqrt{1 - \left(\frac{f_c}{f}\right)^2}$$

위상 천이 행렬:

$$[\mathbf{T}_{WG}]_{ii} = e^{-j\beta L}$$

### Redheffer Star Product

$$\boldsymbol{\Gamma} = \left(\mathbf{I} - \mathbf{S}_{BB}\,\mathbf{T}_{WG}\,\mathbf{S}_{BB}\,\mathbf{T}_{WG}\right)^{-1}$$

B2B 전달 행렬:

$$\mathbf{S}_{21,sys} = \mathbf{S}_{AB}\,\mathbf{T}_{WG}\,\boldsymbol{\Gamma}\,\mathbf{S}_{BA}$$

입력 반사:

$$\mathbf{S}_{11,sys} = \mathbf{S}_{AA} + \mathbf{S}_{AB}\,\mathbf{T}_{WG}\,\boldsymbol{\Gamma}\,\mathbf{S}_{BB}\,\mathbf{T}_{WG}\,\mathbf{S}_{BA}$$

## 4. 시뮬레이션 실행

```bash
cd content/Home/projects/THz_ISAC/code
venv\Scripts\activate
python sim\back2back_sim.py
```

출력 결과:
- `back2back_fig1_single_omt.png` — 단일 OMT Co/Cross-pol 응답
- `back2back_fig2_b2b_compare.png` — B2B 행렬 예측 vs EM 시뮬레이션
- `back2back_fig3_rl_iso.png` — Return Loss + Isolation (행렬 vs EM)
- 콘솔: 260~320 GHz 대역 내 평균/최대 오차 및 RMS

### 비교 지표 (260~320 GHz)

| 지표 | 의미 |
|------|------|
| mean\|Δ\| | 예측과 EM의 평균 절대 오차 (dB) |
| max\|Δ\| | 최대 절대 오차 (dB) |
| RMS | 오차 RMS (dB) |

## 5. 의존 라이브러리

- **`scikit-rf`**: `rf.Network`로 `.s9p`, `.s12p` 파일 로드 및 S-파라미터 처리
- **`numpy`**: 행렬 연산 (`np.linalg.inv`, `@` 연산자)
- **`matplotlib`**: 결과 시각화 및 PNG 저장

```python
import skrf as rf

ntw = rf.Network("OMT_Square.s9p")
S = ntw.s           # shape: (N_freq, 9, 9)
freq = ntw.f / 1e9  # GHz
```

## 6. 향후 개선 방향

- [ ] 원형 도파관 길이 자동 최적화 (측정-예측 오차 최소화)
- [ ] TE21 모드 크로스커플링 항 추가
- [ ] 다중 OMT 타입 동시 비교 자동화
- [ ] SINR 링크 버짓 모델(`HANDOFF.md §7`)과 연동

## 7. 관련 노트

- [[00_system_architecture]] — 시스템 내 OMT 역할 (격리도 골디락스 조건)
- [[../HANDOFF]] — §7 링크 버짓/SINR 모델, OMT 격리도 [20, 30] dB 조건
