# Quartz Vault — 사용 안내

이 vault는 연구 노트와 코드를 관리하는 Obsidian + Quartz 저장소입니다.

## 폴더 구조

```
content/Home/
├── CLAUDE.md                    ← 전역 규칙 (모든 프로젝트에 적용)
├── concepts/                    ← 프로젝트 독립적인 공통 이론
└── projects/
     ├── THz_ISAC/               ← 광자 THz 전이중 ISAC 프로젝트 (270 GHz)
     │    ├── HANDOFF.md         ← THz ISAC 기술 컨텍스트 및 로컬 규칙
     │    ├── code/              ← Python/MATLAB 코드
     │    ├── concepts/          ← THz ISAC 특화 이론 노트
     │    └── logs/              ← 실험 기록
     └── FSO_Link/               ← (향후 프로젝트)
          └── code/
```

## Claude Code 시작 방법

```bash
cd C:\Users\sungminjo\quartz
claude
```

Claude Code는 `content/Home/CLAUDE.md`에서 전역 규칙을 읽습니다.
프로젝트 작업 시에는 해당 프로젝트의 `HANDOFF.md`를 먼저 읽도록 지시하세요:

> "Read content/Home/projects/THz_ISAC/HANDOFF.md, then ..."

## THz ISAC 첫 작업 제안 (HANDOFF.md §8 참조)

- [ ] 수신기 DSP 체인 (`code/dsp/`) — 0~10단계 Python 모듈
- [ ] 링크 버짓 / SINR 시뮬레이터 (`code/sim/`)
- [ ] AWG 파형 생성기 (`code/awg/`) — M8194A 포맷
- [ ] 캡처 + DSP 자동화 글루 (`code/bench/`)

## 주의사항

광출력을 높이기 전 반드시 **NICT UTC-PD (IOD-PMJ-13001)** 데이터시트의
역바이어스 전압 및 최대 광전류 한계를 확인하세요. 바이어스 먼저, 광입력 나중.
