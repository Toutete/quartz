# 280 GHz ISAC 실측 재처리와 JLT 수정 근거

2026-11-18 · TVT 제출본 검토 및 JLT 투고 준비용

**JLT에서 가장 먼저 정정할 부분은 파일럿 사용, 20 GBd BER 판정, Fig. 7의 센싱 지표입니다.** 저장 파형은 Zadoff–Chu 성분을 가중치 \(\rho_{\rm ZC}=0.20\)으로 중첩했습니다. 20 GBd 파일은 100 Gb/s gross를 뒷받침하지만 실제 비트 매핑의 BER은 3.875%입니다. 1.10 m 후보에서는 거리 피크와 CFR의 대비 개선을 재처리로 확인했고, Fig. 7의 절대 센싱 SINR 일치와 공동 거리 주장을 확인할 paired sweep·교정 기록은 미확보입니다.

## 원고와 캡처의 대응

제출 PDF는 인쇄된 주장·식·그림의 기준입니다. JLT 대응 Word 파일의 영문과 교체안은 검토 자료로 사용했습니다. Codex 실행은 사용자 지정 핸드오프의 A00–A10을 따랐습니다. 분석은 로컬에서 이루어졌고 계측기의 새 측정과 원고 파일 편집은 포함되지 않았습니다.

| 그림 또는 조건 | 이번에 확인한 근거 | JLT에서의 처리 |
|---|---|---|
| TVT Fig. 2–3 | PDF Table I 식의 명목 재계산과 독립 파형 검증을 각각 실행. −35 dBm SI에서 Fig. 2 이득은 15.07 dB. Fig. 3에서 −10 dBm TX, −10 dBsm의 통신·센싱·공동 거리는 각각 1.037, 1.672, 1.037 m. | 이론값으로 유지. PA/고 SI에는 ZBD 입력 동작 한계와 피크 여유를 함께 표시. |
| TVT Fig. 5 | 대역폭 캡처 15개 C1 재복조. 20 GBd 32-QAM의 EVM −15.768 dB, 1,984/51,200 bit errors(3.875%). 저장 BER도 3.875%. | 측정 EVM, 측정 BER 및 100 Gb/s gross 표기. −15.75 dB는 원고의 quasi-Gray AWGN 기준으로 명시. 2% 통과 및 83.3 Gb/s 정보율은 해당 FEC의 별도 근거 필요. |
| TVT Fig. 6 | 1.10 m C2 후보에서 같은 원시 파형의 전 송신 참조 정합 필터와 정규화 CFR은 1.0975 m. 대비 20.12 → 33.34 dB. 원고의 20.2 → 31.8 dB 수치를 재현하는 최종 창·좌표 보정·코드 버전은 미확인. | 재처리 수치와 창·마스크를 함께 사용하거나 원본 그림의 재현 입력 확보. 전체 개선을 물리적 SI 혼합 이득으로 해석하지 않음. |
| TVT Fig. 7 | 동일 폴더의 1.10 m 원시 기록 두 개를 재처리. Record A는 C1 BER 6.35%와 C2 대비 9.48 dB. C2 피크가 뚜렷한 Record B의 C1 저장 지표는 N/A이며 오프라인 복조도 무작위 수준의 BER을 반환. | 거리별 paired C1/C2와 원래 선택 기준 확보 전에는 공동 1.1 m 및 절대 모델 일치 서술 보류. A와 B는 각각 6.5 mA 파일과 이름에 Iph7이 붙은 파일. [Fig. 7 근거와 모델 분리](figures/fig7_evidence_audit.png) |
| TVT Fig. 8 | 20 GBd/32-QAM 파일에 저장된 C2 정합 필터 기준 위치 1011.519 mm, 이후 1004.091 mm, 차이 −7.428 mm. 이번 전체 TX CFR 재처리 피크는 1021.25 mm. | 저장 결과는 한 거리 셀 규모의 이동에 대한 후보 근거. 원고의 CFR 쌍 1012.5/1005.0 mm 재현에는 두 위치의 원시 파일, 캘리퍼, 거리축 보정, 그림 코드를 연결해야 함. |

대역폭 15개, 1.10 m 후보 2개, 광전류 10개에 대해 파일 해시, C1/C2 원시 배열 해시, 캡처 설정과 재처리 결과를 기록했습니다. 1.10 m 거리 파일은 이름에 Iph7이 있지만 저장 광전류는 6.5 mA입니다. data/range의 별도 15 GBd Range 파일은 동일한 C1과 C2 원시 배열을 포함해 반복 관측으로 세지 않았습니다. 20 GBd 두 채널은 같은 파일에 있고 샘플 간격도 일치합니다. 이 파일의 C1/C2 시간축 시작 차이는 −2.896 ps이며, 장비 capture ID와 단일 트리거 로그는 파일에 없습니다. 제출본의 동시 취득 서술을 검증하려면 해당 acquisition provenance를 연결해야 합니다. [캡처 인벤토리](capture_inventory.csv) · [중복 배열 판정](additional_range_inventory.csv)

## 검토 결론

- **파형과 FFT**. 무CP를 실제 AWG 샘플에서 확인했습니다. 15 GBd 거리 후보는 120 GSa/s, 8,192점, 1,024개 활성 bin, 15개 블록입니다. 20 GBd 후보는 6,144점, 10개 블록입니다. 무CP에서 지연 반사파가 앞 블록 꼬리를 창 안으로 가져오므로 식 (8)은 근사입니다. 결합 CFR과 full-record 선형 지연 기준을 독립 검증했습니다. [파형·FFT 보고서](waveform_fft_audit.md)
- **BER와 비트 매핑**. 저장된 20 GBd 참조 심볼을 구버전 32-cross-QAM 매핑으로 역변환해 PRBS15와 일치함을 확인했습니다. 이 매핑은 성상도 점의 자연 이진 인덱스를 사용하며 최근접 쌍 52개 중 16개가 1비트 차이입니다. 이 매핑을 사용한 독립 AWGN 실험에서 15.75 dB의 BER도 3.586%였습니다. −15.75 dB 기준의 맵과 출처를 원고에 명시하고, 송신기의 실제 비트 매핑과 사용한 FEC를 일치시켜야 합니다. 추가 블록 단위 참조 보조 위상 보정 효과는 대역폭 재처리에서 작았습니다. [32-QAM 재복조](evm_32qam.csv) · [레거시 매핑 AWGN 확인](legacy_32qam_awgn.csv)
- **센싱 지표**. 1.10 m 거리 후보의 CFR 대비는 33.34 dB, 식 (19)의 중앙값 기반 excess는 33.33 dB, 같은 피크와 공통 배경 마스크의 평균 기반 excess는 26.10 dB였습니다. 독립 기준 거리 셀의 중앙값 기반 excess는 32.42 dB입니다. 고정된 스칼라 나눗셈은 대비를 바꾸지 않았습니다. 상수 기준선을 뺀 뒤의 대비는 raw CFR 대비 0.22 dB 낮았습니다. 정합 필터→CFR의 개선을 보고하고, 두 수학적 단계와 RF 혼합 효과를 구분해야 합니다. [처리 방법별 실측값](processing_ablation.csv) · [센싱 지표 시뮬레이션](metric_calibration.csv)
- **전력 여유**. 논문 장치 숫자로 환산한 ZBD 평균 입력 여유는 약 1–2 dB입니다. 저장 파형과 이상적 13 dB CSPR로 계산한 SI 포락선 PAPR은 3.95 dB입니다. 이 계산은 평균과 피크 여유를 구분해야 하는 이유를 보여주며, 압축 발생 여부는 실제 장치 입력과 transfer curve로 확인해야 합니다. 명목 Fig. 2의 LNA 입력 축 기준에서 LNA→ZBD 손실 1–2 dB를 가정하면 캐리어 평균 기준 ZBD 경계는 약 −32∼−31 dBm입니다. 전체 변조 전력과 포락선 피크로 계산할 때 경계는 더 낮아집니다. [수신기 전력 예산](receiver_power_budget.csv) · [Fig. 2 재계산](figures/fig2_table_i_headroom.png)
- **광전류**. 16-QAM 5→7 mA에서 EVM은 −14.45→−17.59 dB였습니다. 32-QAM 4.5→6.5 mA에서 −13.48→−16.57 dB였습니다. 32-QAM C2 대비는 5.0 mA에서 13.77 dB, 5.5 mA에서 5.11 dB로 단조 증가하지 않았습니다. 파일별 1회 표본이며, 15 GBd 자료의 시뮬레이터 UTC-PD 전력은 7 mA에서 −10 dBm을 앵커로 둔 \(I_{\rm ph}^2\) 모델입니다. 독립 THz 전력·CSPR·잡음·수신기 여유 교정 전에는 광전류로 잔류 SI만 제어했다고 해석할 수 없습니다. [광전류 재처리](photocurrent_analysis.csv) · [광전류 그림](figures/photocurrent_reprocessing.png)

## 결과 파일과 실행

| 자료 | 내용 |
|---|---|
| [심사 대응표](reviewer_status.md) | AE와 R1–R3의 14개 의견, 남은 측정 및 저자 확인사항 |
| [영문 교체 문구](manuscript_changes.md) | M00–M13 적용 위치와 근거 |
| [기준 구조 및 수식 검증](baseline_comparison.md) | Eqs. (7), (12), (16), noise reference plane, 비교군, 합성 실험 한계 |
| [파라미터 감사](parameter_audit.csv) | 논문 수치, 코드·캡처에서 확인한 값, 교정 대기 상태 |
| [재현 매니페스트](run_manifest.json) | 파일 및 코드 해시, 환경, seed, 실행 명령 |
| [대역폭 EVM](figures/bandwidth_evm.png) · [Fig. 6 재처리](figures/fig6_candidate_processing.png) · [Fig. 7 증거](figures/fig7_evidence_audit.png) · [Fig. 8 후보](figures/fig8_candidate_profile.png) · [Fig. 3 재계산](figures/fig3_table_i.png) | 분리된 실측 재처리 및 이론 그림. Fig. 7 왼쪽 패널은 보고된 실험 전력, RCS, 29.8 dB 이득과 Table I의 나머지 계수를 명시적으로 혼용한 민감도 계산. |

저장소 루트에서 당시 가상환경의 Python을 사용합니다.

~~~
$isacPython = Join-Path $env:LOCALAPPDATA 'THz_ISAC\venv\Scripts\python.exe'
$env:OPENBLAS_NUM_THREADS = '1'
$env:OMP_NUM_THREADS = '1'
& $isacPython -B jlt_review_audit/capture_audit.py
& $isacPython -B jlt_review_audit/model_audit.py
~~~

캡처 파이프라인은 신뢰하는 로컬 NPZ만 대상으로 합니다. EVM/BER는 저장된 참조를 사용하는 결정 방식입니다. processing_ablation의 전력은 방식별 임의 스케일의 선형값이며, 비율만 방식 사이에서 비교할 수 있습니다. 고정 셀 excess의 공란은 로그 인자가 양수가 아닌 경우입니다. 합성 재처리는 seed 20261118로 실행했습니다. 코드 회귀 테스트는 65개 중 64개 통과, 시작 프리셋 JSON이 필요한 1개 skip입니다. 실제 독립 표적, target-off/SI-off 반복 취득과 JLT 원본 그림 코드가 필요한 결과는 [심사 대응표](reviewer_status.md)에 있습니다.
