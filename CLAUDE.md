# Segmentation Model UI — 프로젝트 개요

PyTorch 세그멘테이션 모델을 위한 로컬 데스크탑 GUI.
사용자가 임의의 `nn.Module` 아키텍처 코드를 붙여넣으면
라벨링 → 학습 → 추론 전 과정을 단일 앱에서 수행한다.

---

## 기술 스택

| 역할 | 라이브러리 |
|------|------------|
| GUI | PyQt6 |
| 딥러닝 | PyTorch 2.3+, torchvision |
| 손실 그래프 | matplotlib (FigureCanvasQTAgg) |
| 이미지 처리 | Pillow, OpenCV, numpy |
| 데이터 증강 | Albumentations |
| 코드 검증 | Python `ast` 모듈 (내장) |

---

## 디렉토리 구조

```
segmentation model/
├── main.py               # 진입점 — QApplication 생성, data/ 디렉토리 초기화
├── requirements.txt
├── CLAUDE.md             # 이 파일
├── QA.md                 # 버그·VOC 추적
│
├── app/
│   ├── main_window.py    # QMainWindow + QTabWidget (4개 탭)
│   ├── tabs/
│   │   ├── model_tab.py      # 모델 코드 입력·검증·로드
│   │   ├── labeling_tab.py   # 이미지 + 어노테이션 캔버스
│   │   ├── training_tab.py   # 하이퍼파라미터 + 학습 제어 + 손실 그래프
│   │   └── inference_tab.py  # 체크포인트 선택 + 추론 결과 뷰어
│   ├── widgets/
│   │   ├── annotation_canvas.py  # QGraphicsView — 폴리곤·브러시·지우개
│   │   ├── class_panel.py        # 클래스 목록·색상
│   │   ├── image_browser.py      # 썸네일 브라우저
│   │   ├── loss_chart.py         # 실시간 손실 그래프
│   │   ├── config_form.py        # 하이퍼파라미터 폼
│   │   └── overlay_viewer.py     # 추론 결과 오버레이
│   └── core/
│       ├── model_validator.py    # AST 기반 코드 검사
│       ├── model_loader.py       # 제한적 exec + nn.Module 탐색
│       ├── dataset.py            # SegmentationDataset
│       ├── trainer.py            # QThread 학습 루프
│       ├── metrics.py            # IoU, Dice
│       ├── augmentations.py      # Albumentations 파이프라인 빌더
│       ├── inference_engine.py   # 추론 + 마스크 컬러화
│       └── annotation_store.py   # JSON 어노테이션 읽기·쓰기
│
├── data/                 # 런타임 데이터 (gitignore)
│   ├── images/
│   ├── annotations/
│   ├── checkpoints/
│   └── user_models/
│
├── docs/
│   ├── AI_MODEL.md
│   ├── GUI.md
│   ├── PROCESS.md
│   ├── SECURITY.md
│   ├── ANNOTATION_FORMAT.md
│   ├── CHANGELOG.md
│   ├── roadmap.md          # 탭/기능별 진행 상태 (살아있는 문서)
│   ├── decisions-needed.md # 사용자 결정 대기 목록 (살아있는 문서)
│   └── agents/              # 역할별 append-only 작업 로그 (leader/planning/design/implementation/verification-log.md)
│
└── .claude/
    └── agents/               # 서브에이전트 정의 (planner/designer/implementer/verifier/deployer.md)
```

---

## 운영 방식: Harness Engineering

이 프로젝트는 리더(메인 세션) + 서브에이전트 체계로 운영한다. 리더는 사용자와의 대화 창구이자
오케스트레이터이며, 실제 작업은 서브에이전트에 위임하는 것을 원칙으로 한다.

### 리더 규칙

1. 사용자가 요구사항을 말하면, **먼저 이해한 내용을 요약해 사용자에게 확인받은 뒤에만** 서브에이전트에 작업을 분배한다.
2. 리더는 기획/디자인/구현/검증/배포 작업을 가능한 한 직접 수행하지 않고 해당 서브에이전트(Agent 도구, `subagent_type`)를 호출한다. 사소한 1~2줄 수정이나 조사성 질문 답변처럼 위임이 과한 경우는 리더가 직접 처리해도 된다.
3. 세션 시작 시 `git fetch`로 `origin/main` 변경 여부를 확인한다. 새 커밋이 있으면 사용자에게 알리고 pull 여부를 확인한다.
4. `git push` 등 외부로 나가는 액션은 사용자의 명시적 확인 후에만 진행한다 (자동 push 금지). 커밋 자체는 아래 "Git 커밋 규칙"대로 즉시 수행한다.
5. 리더도 서브에이전트와 동일하게 `docs/agents/leader-log.md`에 로그를 남긴다. 기록 대상은 서브에이전트 산출물 자체가 아니라 **오케스트레이션 흐름**이다: 사용자 요청 → 어떤 서브에이전트에 무엇을 언제·왜 맡겼는지 → 결과 → 커밋/푸시 등 외부 액션. `leader-log.md` 맨 위 "현재 상황 요약" 절은 append가 아니라 매번 덮어쓰는 살아있는 요약이다 — 그 아래 날짜별 로그는 append-only.
6. 사용자 결정이 필요한 지점을 발견하면 `docs/decisions-needed.md`에 추가한다. 실제 결정이 나면 즉시 삭제한다(근거는 관련 문서·`leader-log.md`에 남으므로 이력은 보존). "추후 논의"로만 답한 경우는 삭제하지 않고 "보류된 항목" 절로 옮긴다.
7. `docs/roadmap.md`(탭/기능별 진행 상태)는 `decisions-needed.md`와 같은 살아있는 문서다 — 상태가 바뀔 때마다 리더가 직접 갱신한다(체크박스 토글, 완료 항목 정리). append-only가 아니므로 과거 상태를 지우고 최신으로 덮어써도 된다 — 상세 이력은 `docs/agents/*-log.md`, `QA.md`, `docs/CHANGELOG.md`에 이미 남는다.

### 워크플로우 순서

```
리더 → 기획(Planning) → 구현(Implementation) + 디자인(Design) 병행 → 검증(Verification) → 배포(Deployment)
```

- 각 단계 전환 시 리더가 이전 단계 산출물을 확인하고 다음 에이전트에게 컨텍스트를 전달한다.
- **구현 완료 후 검증 필수**: 구현 에이전트가 끝났다고 보고해도, 검증 에이전트가 실제로 앱을 구동(`python main.py` 또는 `run` 스킬)해 확인하기 전까지는 "완료"로 간주하지 않는다.
- **스파이크(선행검증)는 필요할 때만 끼워 넣는다**: 기술 선택지(라이브러리, 아키텍처) 사이에 실측 근거가 필요하면 결정을 미룬 채 진행하는 대신 스파이크 에이전트를 호출해 장단점을 정리시킨 뒤 사용자 결정을 받는다. 스파이크는 구현 이전에 수행하며 스스로 결정을 내리지 않는다.
- **검증 수준**: 기본은 정적 검토(코드 리뷰) + 실행 확인이다. 리더가 "주요 기능 추가"로 판단한 라운드는 검증 에이전트에게 라벨링/학습/추론 각 탭의 실제 UI 조작(골든 패스)까지 명시적으로 요청한다 — 사소한 버그 수정·문서 정정은 실행 확인만으로 충분.

### 로그 규칙 (리더 + 서브에이전트)

각 서브에이전트는 작업 시작/종료 시 `docs/agents/<role>-log.md`에 날짜, 작업 요약, 상태(진행중/완료/블로커)를 **추가**한다 — append-only, 기존 내용은 삭제하지 않는다. 리더도 같은 규칙으로 `docs/agents/leader-log.md`에 오케스트레이션 흐름을 기록한다.

| 역할 | 정의 파일 | 로그 파일 | 산출물 위치 |
|---|---|---|---|
| 리더 (Leader) | (메인 세션, 정의 파일 없음) | `docs/agents/leader-log.md` | — (오케스트레이션 기록) |
| 기획 (Planning) | `.claude/agents/planner.md` | `docs/agents/planning-log.md` | `docs/roadmap.md` |
| 스파이크 (Spike, 선행검증·필요 시에만) | `.claude/agents/spiker.md` | `docs/agents/spike-log.md` (필요 시 생성) | 관련 조사 문서 |
| 디자인 (Design) | `.claude/agents/designer.md` | `docs/agents/design-log.md` | UI 목업 / Artifact |
| 구현 (Implementation) | `.claude/agents/implementer.md` | `docs/agents/implementation-log.md` | (코드) |
| 검증 (Verification) | `.claude/agents/verifier.md` | `docs/agents/verification-log.md` | `QA.md` |
| 배포 (Deployment) | `.claude/agents/deployer.md` | `docs/agents/deployment-log.md` (필요 시 생성) | `docs/CHANGELOG.md`, git tag |

---

## Git / GitHub 연동

- 원격 저장소: `https://github.com/sfeelBot/Segmentation-Tool.git` (public, 기본 브랜치 `main`)
- 커밋은 의미 단위로 나눈다.
- **push는 사용자가 명시적으로 요청할 때만** 수행한다.
- 검증 단계 범위: 현재는 체크리스트 기반 수동 검증(`QA.md`). CI 자동화는 프로젝트가 안정화된 뒤 추가한다.
- 배포 에이전트 범위: 버전 태깅, CHANGELOG 갱신까지만 담당. PyInstaller 등 실행파일 패키징/배포는 범위 밖 (별도 논의).

### 에디션 브랜치 (feature/*, edition/*, variant/*)

일부 기능(예: 존 분석 탭 — 배터리 캡 녹 검사 전용 도구)은 범용 세그멘테이션 툴이 아닌
특정 용도 전용이라, main에 병합하지 않고 **별도로 계속 유지되는 브랜치**(에디션 브랜치)로
관리한다. 2026-08-25 `feature/zone-analysis-tab` 운영 중 확정된 규칙:

1. **에디션 브랜치 → main 역병합 금지.** main은 범용 기능만 유지한다.
2. **main → 에디션 브랜치 동기화는 전용 sync 브랜치 + PR로만 한다** (main을 PR head로 직접
   쓰지 않는다):
   ```
   git fetch origin
   git branch sync/main-into-<에디션명>-<날짜> origin/main
   git push -u origin sync/main-into-<에디션명>-<날짜>
   gh pr create --base <에디션 브랜치> --head sync/main-into-<에디션명>-<날짜> \
     --title "sync: main 업데이트 반영"
   ```
   main에 의미 있는 개선(버그 수정, 공통 기능 추가 등)이 쌓일 때마다 반복한다.
3. 같은 워킹 디렉토리를 여러 세션이 공유하면 `git checkout` 충돌이 생기므로, 에디션 브랜치
   작업은 `git worktree add <경로> <브랜치>`로 **별도 워크트리를 분리**해서 진행한다.
4. `docs/agents/*.md`, `docs/roadmap.md`, `QA.md` 는 append-only라 sync 시 자주 충돌하는데,
   기본 해법은 "양쪽 다 살리기"(두 항목 다 보존)다 — 내용을 버리지 않는다.
5. 버전 태그는 main의 `vX.Y.Z`와 구분되는 별도 체계를 쓴다 (예: `zone-vX.Y.Z`). 빌드도
   `build.spec`/`installer/setup.iss`의 앱 이름을 달리해 별도 installer로 만든다.
6. main 병합은 사용자가 명시적으로 결정하기 전까진 하지 않는다 — 기본은 "영구 분리".

## Git 커밋 규칙

> **코드 수정이 있을 때마다 반드시 커밋한다.**

- 기능 추가, 버그 수정, 성능 개선 등 **모든 코드 변경** 후 즉시 `git commit`
- 커밋 메시지 형식:
  ```
  feat: 새 기능 요약
  fix:  버그 수정 요약
  perf: 성능 개선
  docs: 문서만 변경
  refactor: 기능 변경 없는 코드 정리
  ```
- 버전 태그: 사용자 요청 단위 완료 시 `git tag -a vX.Y.Z`
- CHANGELOG 갱신: `docs/CHANGELOG.md` 에 버전·요청·구현 내용 기록

---

## 코딩 규칙

### Python
- Python 3.11+, 타입 힌트 필수
- 클래스: `PascalCase` / 함수·변수: `snake_case`
- QWidget 서브클래스는 `_build_ui()` 메서드에 UI 구성 집중
- 비즈니스 로직은 `app/core/`에 위치 — Qt 의존성 없이 작성
- QThread Worker: `run()` 안에서만 실행, 결과는 `Signal`로만 전달
- 외부 상태 변경은 Qt 시그널·슬롯을 통해서만 수행 (스레드 안전)

### 파일 저장
- 어노테이션: `data/annotations/{image_stem}.json` (1 이미지 = 1 JSON)
- 체크포인트: `data/checkpoints/epoch_{n:04d}.pt`
- 사용자 모델 코드: `data/user_models/model_{timestamp}.py`

### 오류 처리
- UI에서 발생한 예외는 `QMessageBox.critical()`로 표시
- `core/` 모듈은 예외를 그대로 raise — UI 레이어가 처리
- 학습 중 예외는 `TrainerWorker.training_error` 시그널로 전달

---

## 구현 단계

Phase 1~5(뼈대, 모델 로더, 라벨링, 학습, 추론)는 모두 완료됐고 이후로도 기능이 계속
추가되고 있다. 정적 표 대신 살아있는 문서인 [docs/roadmap.md](docs/roadmap.md)에서
탭/기능별 현재 상태를 관리한다.

---

## 환경 변수 (선택)

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `SEG_DATA_DIR` | `./data` | 데이터 루트 경로 |
| `SEG_DEFAULT_DEVICE` | `auto` | `auto` \| `cpu` \| `cuda` \| `mps` |
| `SEG_MAX_MODEL_KB` | `256` | 모델 코드 최대 크기 (KB) |

---

## 관련 문서

- [QA.md](QA.md) — 버그·VOC 추적
- [docs/AI_MODEL.md](docs/AI_MODEL.md) — 모델 계약·학습 파이프라인
- [docs/GUI.md](docs/GUI.md) — UI 컴포넌트·키맵
- [docs/PROCESS.md](docs/PROCESS.md) — 이미지 처리 파이프라인
- [docs/SECURITY.md](docs/SECURITY.md) — 모델 코드 샌드박스
- [docs/ANNOTATION_FORMAT.md](docs/ANNOTATION_FORMAT.md) — JSON 스키마
- [docs/roadmap.md](docs/roadmap.md) — 탭/기능별 진행 상태 (살아있는 문서)
- [docs/decisions-needed.md](docs/decisions-needed.md) — 사용자 결정 대기 목록 (살아있는 문서)
- [docs/agents/README.md](docs/agents/README.md) — 리더·기획·디자인·구현·검증·배포 역할별 작업 로그 워크플로우
