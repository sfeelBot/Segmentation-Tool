# GUI — 컴포넌트 구조 및 UX 명세

## 탭 레이아웃

```
QMainWindow
└── QTabWidget
    ├── [0] Model     — ModelTab
    ├── [1] Labeling  — LabelingTab
    ├── [2] Training  — TrainingTab
    └── [3] Inference — InferenceTab
```

상태 표시: `QStatusBar` (하단) — 현재 상태 메시지

---

## 위젯 계층

### ModelTab
```
QVBoxLayout
├── QLabel (안내 문구)
├── QSplitter (Vertical)
│   ├── QPlainTextEdit (_editor) — 모델 코드 편집기
│   └── QTextEdit (_log, ReadOnly) — 검증·로드 결과 로그
└── QHBoxLayout
    ├── QPushButton "검증"
    └── QPushButton "로드" (검증 성공 후 활성화)
```

### LabelingTab (Phase 3)
```
QHBoxLayout
├── QWidget (Left Panel, 220px)
│   ├── ImageBrowser — 이미지 목록 + 업로드 버튼
│   └── ClassPanel   — 클래스 목록 + 색상 + 추가/삭제
└── QWidget (Center)
    ├── ToolBar — 도구 선택 버튼 (P/B/E/Pan)
    └── AnnotationCanvas — QGraphicsView
```

### TrainingTab (Phase 4)
```
QHBoxLayout
├── QScrollArea > ConfigForm (280px) — 하이퍼파라미터 폼
└── QVBoxLayout (Right)
    ├── QHBoxLayout — Start/Stop/Pause 버튼
    ├── LossChart   — matplotlib 캔버스 (train/val 곡선)
    └── MetricsTable — QTableWidget (클래스별 IoU, Dice)
```

### InferenceTab (Phase 5)
```
QVBoxLayout
├── QHBoxLayout (Top Controls)
│   ├── QComboBox — 체크포인트 선택
│   └── QPushButton "이미지 선택"
└── OverlayViewer — 원본 + 마스크 오버레이
    └── QSlider — 오버레이 투명도 (0–100%)
```

---

## 어노테이션 캔버스 (AnnotationCanvas)

### QGraphicsView 레이어 구조
```
QGraphicsScene
├── Layer 0: ImageItem          — 배경 이미지 (불투명)
├── Layer 1: AnnotationItems    — 저장된 어노테이션 (반투명)
└── Layer 2: DrawingItem        — 현재 그리는 중인 도형 (인터랙티브)
```

### 도구 키맵

| 키 | 동작 |
|----|------|
| `P` | Polygon 도구 |
| `B` | Brush 도구 |
| `E` | Eraser 도구 |
| `Space` | Pan 도구 (일시 전환) |
| `Ctrl+Z` | Undo |
| `Ctrl+Y` | Redo |
| `Escape` | 현재 작업 취소 |
| `Delete` | 선택된 어노테이션 삭제 |
| `+` / `-` | 브러시 크기 조절 |
| `[` / `]` | 브러시 크기 조절 (대안) |
| `Ctrl+S` | 어노테이션 저장 |

### 도구별 동작

**Polygon 모드**
- 클릭: 꼭짓점 추가
- 더블클릭: 폴리곤 닫기 + 저장
- Escape: 작업 중인 폴리곤 취소
- 닫힌 후: 클래스 색상으로 반투명 채우기

**Brush 모드**
- mousePress + mouseMove: 오프스크린 QImage에 페인팅
- mouseRelease: RLE 인코딩 후 어노테이션으로 저장
- 브러시 크기: 1–200px 범위

**Eraser 모드**
- Brush와 동일 동작, 기존 마스크를 빼냄 (destination-out)

**Pan 모드**
- 마우스 드래그로 캔버스 이동
- 마우스 휠: 줌 인/아웃

---

## QThread 시그널 흐름 (Training)

```
TrainingTab.btn_start.clicked
    └─> TrainerWorker.start()

TrainerWorker.epoch_done(epoch, train_loss, val_loss, metrics)
    └─> TrainingTab._on_epoch_done()
        ├─> LossChart.append_point(epoch, train_loss, val_loss)
        └─> MetricsTable.update_row(epoch, metrics)

TrainerWorker.training_error(message)
    └─> QMessageBox.critical()

TrainerWorker.training_finished()
    └─> TrainingTab._on_training_finished()
        └─> 버튼 상태 복구
```

---

## ConfigForm 필드 목록 (Phase 4)

| 필드 | 위젯 | 기본값 |
|------|------|--------|
| Epochs | QSpinBox (1–9999) | 50 |
| Batch Size | QSpinBox (1–128) | 4 |
| Image Size | QLineEdit "W,H" | 512,512 |
| Learning Rate | QDoubleSpinBox | 1e-4 |
| Optimizer | QComboBox | Adam |
| Weight Decay | QDoubleSpinBox | 0.0 |
| Loss Function | QComboBox | CrossEntropyLoss |
| Mixed Precision | QCheckBox | ✓ |
| Device | QComboBox (auto/cpu/cuda/mps) | auto |
| Checkpoint Every N | QSpinBox | 5 |
| Val Split | QDoubleSpinBox (0.1–0.5) | 0.2 |
| Augmentations | AugmentationPicker | 없음 |

---

## 색상 팔레트 (클래스별 기본값)

```python
DEFAULT_PALETTE = [
    (255,   0,   0),  # class 0 — Red
    (  0, 255,   0),  # class 1 — Green
    (  0,   0, 255),  # class 2 — Blue
    (255, 255,   0),  # class 3 — Yellow
    (255,   0, 255),  # class 4 — Magenta
    (  0, 255, 255),  # class 5 — Cyan
    (255, 128,   0),  # class 6 — Orange
    (128,   0, 255),  # class 7 — Purple
]
```
