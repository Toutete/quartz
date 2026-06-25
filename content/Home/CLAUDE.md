# CLAUDE.md — Global Rules

이 vault는 연구 노트 및 코드 저장소입니다. 어떤 프로젝트를 작업하든 아래 규칙을 엄격히 따르세요.

---

## 1. 폴더 구조 원칙

```
content/Home/
├── CLAUDE.md                  ← 전역 규칙 (이 파일)
├── concepts/                  ← 프로젝트에 종속되지 않는 공통 이론
└── projects/
     └── {ProjectName}/
          ├── HANDOFF.md       ← 해당 프로젝트의 기술 컨텍스트 (로컬 규칙)
          ├── code/            ← 해당 프로젝트의 코드 (.py, .m 등)
          │    ├── functions/  ← 공통 DSP·AWG·DSO 함수 패키지
          │    ├── tx/         ← AWG SCPI 드라이버
          │    ├── rx/         ← DSO 캡처·복조 드라이버
          │    ├── sim/        ← 시뮬레이션·S-파라미터 파일
          │    └── bench/      ← 측정 자동화 스크립트
          ├── concepts/        ← 프로젝트 특화 이론 노트
          └── logs/            ← 실험 기록
```

### 구조적 분리 및 코드 저장 규칙

- **코드 경로**: `projects/[프로젝트명]/code/`
- **이론 경로**: `projects/[프로젝트명]/concepts/`
- Python/MATLAB 등 실행 코드는 **현재 다루고 있는 프로젝트**의 `code/` 하위 폴더에 저장할 것.
- 데이터 분석 시 생성되는 무거운 파일 (`*.csv`, `*.hdf5`, `*.mat`, 플롯 이미지 등)은 `code/data/`에 저장할 것.
- `venv/`, `.venv/`, `__pycache__/` 폴더는 절대 vault 안에 만들지 말 것 (`.gitignore`로 차단됨).
- 이론/원리 설명은 `concepts/` 하위의 마크다운 파일로 작성할 것.
- 노트 하단에 코드 파일의 상대 경로 링크를 반드시 추가하세요.
- 새 프로젝트 시작 시 `projects/{ProjectName}/` 폴더와 `HANDOFF.md`를 먼저 생성하세요.
- 프로젝트 특화 기술 컨텍스트·배경 지식은 **CLAUDE.md가 아닌 해당 프로젝트의 HANDOFF.md**에 기록합니다.

---

## 2. 수식 표현 (LaTeX)

- 모든 수학 공식·방정식은 반드시 LaTeX 문법을 사용합니다.
- 인라인 수식: `$E = mc^2$`
- 블록 수식: `$$...$$` (중앙 정렬)

---

## 3. Frontmatter

- 웹에 공개할 이론 노트에는 frontmatter에 `is_public: true`를 추가합니다.

---

## 4. 배포 (Git)

- 파일 생성·수정 완료 후 반드시 아래 순서로 GitHub에 반영합니다:
  ```bash
  git add .
  git commit -m "[변경 요약]"
  git push origin main
  ```
