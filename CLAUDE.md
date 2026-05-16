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
└── docs/
    ├── AI_MODEL.md
    ├── GUI.md
    ├── PROCESS.md
    ├── SECURITY.md
    └── ANNOTATION_FORMAT.md
```

---

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

| Phase | 내용 | 상태 |
|-------|------|------|
| 1 | 뼈대: 디렉토리, main.py, 4개 탭 stub, 문서 | ✅ 완료 |
| 2 | 모델 로더 탭: AST 검증 + 제한적 exec + UI | ✅ 완료 |
| 3 | 라벨링 탭: 캔버스, 클래스 패널, JSON 저장 | ✅ 완료 |
| 4 | 학습 탭: Dataset, QThread 학습, 실시간 그래프 | ✅ 완료 |
| 5 | 추론 탭: 체크포인트 로드, 오버레이 뷰어 | ✅ 완료 |

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
