"""존(Zone) 분석 탭 — 배터리 캡 녹 검사 도구.

기존 4탭(모델/라벨링/학습/추론)과 완전히 독립된 도구 — `app.core.project`의
프로젝트 시스템(images/annotations/checkpoints/user_models)을 사용하지 않는다.
이미지·체크포인트를 임의 경로에서 직접 열고, 그 자리에서 모델을 재구성해
추론한다. 자세한 스펙: docs/specs/zone-analysis-tab-2026-08-25.md

라운드 1: 이미지/체크포인트 로드 + 모델 재구성(preset 자동 / 커스텀 코드
붙여넣기) + 추론 실행 + 타겟(녹) 클래스 즉석 구성 + ZoneCanvas 순수 뷰어 표시.
라운드 2: 원(circle) 자동 검출(`circle_detector.py`) + 수동 편집(추가/이동/
반지름 조절/삭제) + 원 목록 사이드 패널.
라운드 3: `zone_metrics.py`(원판 마스크 차집합) 기반 존 리스트 패널 + 퍼센티지
실시간 계산·표시.
라운드 4: 블랍(연결요소) 클릭 삭제(`zone_metrics.compute_blob_labels`) + 존
퍼센티지 재계산. "블랍 삭제 모드" 토글로 원 편집과 클릭 해석을 분리.
라운드 R3-3: 픽셀 단위 브러시 지우기 모드 추가 — "블랍 삭제 모드"와 배타적인
3번째 캔버스 모드(`ZoneCanvas._mode`). 존 재계산은 스트로크가 끝날 때(release)
1회만 트리거(`erase_changed` 시그널).
라운드 R3-4: 통합 Undo(원편집+블랍삭제+브러시지우기) 툴바 버튼("실행 취소") 추가
— 실제 undo 스택/로직은 `ZoneCanvas`가 단일 출처로 보관(`undo()`/`can_undo()`).
라운드 R-ZONE-3: "Zone 결정 방법" 3-way 콤보(일괄 적용/일괄 적용 후 수정/장별
적용)로 기존 2-way 체크박스를 대체 + 이미지별 편집 상태를 이미지 옆 사이드카
(`{stem}.zone.json`, `zone_state_store.py`)에 디바운스(500ms) 자동 저장한다.
이미지 전환 시 사이드카가 있으면 복원, 없으면 빈 캔버스로 시작(자세한 설계는
docs/specs/zone-analysis-tab-batch-modes-and-perf-2026-08-30.md "요청 A" 참고).
"""
import queue
from pathlib import Path

import numpy as np
from PIL import Image
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileDialog,
    QMessageBox, QGroupBox, QPlainTextEdit, QTextEdit, QLineEdit, QComboBox,
    QSplitter, QSlider, QSpinBox, QListWidget, QListWidgetItem,
    QProgressDialog, QProgressBar, QToolBar, QFrame, QMenu,
)
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal, QSize, QElapsedTimer
from PyQt6.QtGui import QImage, QPixmap, QAction, QActionGroup
import torch.nn as nn

from app.core import inference_engine as engine
from app.core.inference_engine import (
    InferenceResult, load_checkpoint_meta, load_model_from_ckpt, model_source_label,
)
from app.core.model_validator import validate
from app.core.model_loader import load_from_code
from app.core.annotation_store import ClassDef, DEFAULT_PALETTE
from app.core.circle_detector import detect_circles
from app.core.zone_metrics import (
    Circle, zones_from_circles, zone_stats, compute_blob_labels,
    apply_manual_strokes, zone_blob_stats, ZoneBlobStat, scale_circles,
    max_blob_pixels_by_zone,
)
from app.core import zone_state_store as zstate
from app.core.i18n import t
from app.core.logger import get_logger
from app.core.device_info import prompt_gpu_availability
from app.widgets.zone_canvas import ZoneCanvas
from app.widgets.inference_image_list import InferenceImageList
from app.widgets.zone_batch_result_dialog import ZoneBatchResultDialog
from app.widgets.zone_recipe_dialog import ZoneRecipeDialog
from app.widgets.zone_step_indicator import ZoneStepIndicator
from app.widgets.icons import icon as svg_icon

log = get_logger(__name__)

# threshold 초기 고정값 — 설정 UI는 만들지 않음(YAGNI), 나중에 바꾸고 싶으면 이 상수만 수정
_DEFAULT_MIN_CONFIDENCE = 0.0
_DEFAULT_MIN_PIXEL_SIZE = 0
_PREVIEW_MAX_DIM = 2048


class _ZoneInferenceWorker(QThread):
    result_ready = pyqtSignal(object, object, int, int)
    failed = pyqtSignal(object, str)

    def __init__(self, model, paths: list[Path], checkpoint_path: Path) -> None:
        super().__init__()
        self._model = model
        self._paths = paths
        self._checkpoint_path = checkpoint_path

    def run(self) -> None:
        total = len(self._paths)
        for done, path in enumerate(self._paths, 1):
            try:
                kwargs = dict(
                    model=self._model, image_path=path,
                    checkpoint_path=self._checkpoint_path,
                    opacity=0.5, classes=None,
                )
                result = engine.run_sliding_window(**kwargs)
                self.result_ready.emit(path, result, done, total)
            except Exception as exc:
                self.failed.emit(path, str(exc))


class _ZoneBatchWorker(QThread):
    """BUG-030 수정: 워커 스레드에서는 CUDA 추론만 수행한다 — cv2/numpy 존·블랍
    후처리(`compute_blob_labels`/`zones_from_circles`/`detect_circles` 등)는 절대
    이 스레드 안에서 실행하면 안 된다("다른 스레드의 실 CUDA 추론 직후 같은 스레드에서
    cv2 후처리"가 `STATUS_STACK_BUFFER_OVERRUN` 하드크래시의 결정적 트리거로 격리됨,
    QA.md BUG-030). 후처리는 `image_inferred` 시그널을 받는 가벼운 중계 슬롯
    (`ZoneAnalysisTab._on_batch_image_ready`)을 거쳐 `_ZoneBatchPostWorker`(별도
    QThread, CUDA 비호출)로 넘어간다 — R-PERF-2(2026-10-07), 응답없음 완화."""
    progress = pyqtSignal(object, str, object, int, int)
    image_inferred = pyqtSignal(object, object, int, int)   # path, InferenceResult, done, total

    def __init__(self, model, paths: list[Path], checkpoint_path: Path,
                 cached_results: dict[Path, InferenceResult],
                 classes: list[ClassDef], min_confidence: float, min_pixel_size: int) -> None:
        super().__init__()
        self._model = model
        self._paths = paths
        self._checkpoint_path = checkpoint_path
        self._cached_results = cached_results
        self._classes = classes
        self._min_confidence = min_confidence
        self._min_pixel_size = min_pixel_size

    def run(self) -> None:
        prepared = None
        if any(path not in self._cached_results for path in self._paths):
            try:
                prepared = engine.prepare_inference(self._model, self._checkpoint_path)
            except Exception as exc:
                self.progress.emit(self._checkpoint_path, "error", str(exc), 0, len(self._paths))
                return

        total = len(self._paths)
        for done, path in enumerate(self._paths, 1):
            if self.isInterruptionRequested():
                break
            self.progress.emit(path, "processing", None, done - 1, total)
            try:
                result = self._cached_results.get(path)
                if result is None:
                    result = engine.run_sliding_window(
                        model=self._model, image_path=path,
                        checkpoint_path=self._checkpoint_path, classes=self._classes,
                        min_confidence=self._min_confidence,
                        min_pixel_size=self._min_pixel_size, opacity=0.5,
                        prepared=prepared,
                    )
                self.image_inferred.emit(path, result, done, total)
            except Exception as exc:
                log.exception(f"존 분석 일괄 처리(추론) 실패 — image={path}")
                self.progress.emit(path, "error", str(exc), done, total)


class _ZoneBatchPostWorker(QThread):
    """R-PERF-2(2026-10-07): `_ZoneBatchWorker`가 CUDA 추론을 마친 결과를 큐로
    받아 cv2/numpy 존·블랍 후처리(`_compute_zone_rows`)와 사이드카 저장을 전담하는
    두 번째 워커. CUDA를 절대 호출하지 않는다 — BUG-030 트리거는 "다른 스레드의 실
    CUDA 추론 직후 같은 스레드에서 cv2 후처리"뿐이므로, 이 스레드는 애초에 CUDA를
    호출하지 않아 그 조합 자체가 성립하지 않는다(QA.md BUG-030).

    `enqueue()`로 들어온 항목을 FIFO로 하나씩 처리하므로 처리 순서(결과/사이드카
    기록 순서)는 `_ZoneBatchWorker`가 넣은 순서(이미지 리스트 순서)와 동일하게
    보존된다 — 단일 스레드가 큐를 하나씩 소비하므로 레이스 없음."""
    row_computed = pyqtSignal(object, object, object, object, int, int)  # path, result, rows, blob_rows, done, total
    progress = pyqtSignal(object, str, object, int, int)   # path, status, detail, done, total

    def __init__(self, mode: str, circles_ref: list[tuple], ref_size: tuple[int, int],
                 sensitivity: float, target_cid: int) -> None:
        super().__init__()
        self._queue: queue.Queue = queue.Queue()
        self._mode = mode
        self._circles_ref = circles_ref
        self._ref_size = ref_size
        self._sensitivity = sensitivity
        self._target_cid = target_cid

    def enqueue(self, path: Path, result: InferenceResult, done: int, total: int) -> None:
        self._queue.put((path, result, done, total))

    def close(self) -> None:
        self._queue.put(None)   # sentinel — CUDA 워커가 끝났고 더 들어올 항목이 없음을 알림

    def run(self) -> None:
        while True:
            item = self._queue.get()
            if item is None or self.isInterruptionRequested():
                break
            path, result, done, total = item
            try:
                h, w = result.raw_class_map.shape
                if self._mode == "per_image":
                    with Image.open(str(path)) as im:
                        rgb = np.array(im.convert("RGB"))
                    circles = detect_circles(rgb[:, :, ::-1].copy(), sensitivity=self._sensitivity)
                else:
                    circles = scale_circles(self._circles_ref, self._ref_size, (w, h))
                if not circles:
                    self.progress.emit(path, "done", "원 없음", done, total)
                    continue

                previous = zstate.load_state(path)
                computed = _compute_zone_rows(path, result, self._target_cid, circles, previous)
                if computed is None:
                    self.progress.emit(path, "done", "원 없음", done, total)
                    continue
                rows, blob_rows = computed

                # circles는 모드에 따라 (cx,cy,r)(장별 자동검출) 또는 (cx,cy,r,name)
                # (기준 이미지 레시피 적용, *rest로 이름 보존)일 수 있다 — *rest로 흡수.
                state = previous or {
                    "removed_blob_ids": set(), "erase_strokes": [], "manual_strokes": [],
                }
                state["circles"] = [
                    (idx, cx, cy, r, rest[0] if rest else None)
                    for idx, (cx, cy, r, *rest) in enumerate(circles)
                ]
                zstate.save_state(path, state)

                self.row_computed.emit(path, result, rows, blob_rows, done, total)
            except Exception as exc:
                log.exception(f"존 분석 일괄 처리(후처리) 실패 — image={path}")
                self.progress.emit(path, "error", str(exc), done, total)


def _rgb_to_qpixmap(rgb: np.ndarray) -> QPixmap:
    """플레인 RGB numpy 배열을 QPixmap으로 변환 — 추론 전 원본 미리보기 전용 (GH#14)."""
    rgb = np.ascontiguousarray(rgb)
    h, w, _ = rgb.shape
    qimg = QImage(rgb.data, w, h, w * 3, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qimg.copy())


def _compute_zone_rows(
    path: Path, result: InferenceResult, target_cid: int,
    circles: list[tuple], previous: dict | None,
) -> tuple[list[tuple[str, str, float]], list[tuple[str, ZoneBlobStat]]] | None:
    """(rows, blob_rows) — side effect 없음(저장은 호출부 책임).

    `_on_batch_image_inferred()`의 계산 핵심을 순수 함수로 추출(2026-10-03#8) —
    배치 처리/"전체 결과 보기"(`_on_view_all_results`) 둘 다 재사용한다."""
    if not circles:
        return None
    h, w = result.raw_class_map.shape
    ai_mask = result.class_map == target_cid
    if previous is not None and previous["removed_blob_ids"]:
        labels, _, _ = compute_blob_labels(ai_mask)
        ai_mask = ai_mask & ~np.isin(labels, list(previous["removed_blob_ids"]))
    final_mask = apply_manual_strokes(ai_mask, previous["manual_strokes"]) if previous else ai_mask
    zones = zones_from_circles(
        [Circle(idx, cx, cy, r, (rest[0] if rest else None))
         for idx, (cx, cy, r, *rest) in enumerate(circles)], (h, w)
    )
    percentages = [zone_stats(zone.mask, final_mask) for zone in zones]
    rows = [(path.name, zone.name, pct) for zone, pct in zip(zones, percentages)]
    blob_rows = [(path.name, s) for s in zone_blob_stats(zones, ai_mask, final_mask, result.confidence_map)]
    return rows, blob_rows


class ZoneAnalysisTab(QWidget):
    """이미지 파일 + 체크포인트 파일을 직접 열어 추론하는 독립 도구."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._image_path: Path | None = None
        self._ckpt_path: Path | None = None
        self._model: nn.Module | None = None
        self._last_result: InferenceResult | None = None
        self._original_pixmap: QPixmap | None = None
        self._overlay_visible = True
        self._results: dict[Path, InferenceResult] = {}
        # R-PERF-1: (target_cid, min_confidence, min_pixel_size) 키로 refilter+
        # compute_blob_labels 결과를 캐싱 — 같은 이미지를 같은 조합으로 재방문할 때
        # 디스크 재디코딩+cv2 connected-components 중복 계산을 스킵한다.
        self._target_cache: dict[Path, tuple[tuple, InferenceResult, np.ndarray, list]] = {}
        self._worker: _ZoneInferenceWorker | None = None
        self._batch_worker: _ZoneBatchWorker | None = None
        self._post_worker: _ZoneBatchPostWorker | None = None   # R-PERF-2: cv2 후처리 전용 QThread
        self._batch_progress: QProgressDialog | None = None
        # R-PERF-2: cv2/numpy 존·블랍 후처리 결과(메인 스레드에서 누적, _post_worker가 채움)
        self._batch_rows: list[tuple[str, str, float]] = []
        self._batch_blob_rows: list[tuple[str, ZoneBlobStat]] = []
        self._detected_ids: list[int] = []   # raw_class_map의 배경(0) 제외 고유 클래스 id
        self._target_class_id: int | None = None   # 현재 선택된 타겟(녹) 클래스 id
        self._target_classes: list[ClassDef] | None = None   # 일괄 처리(3b)에서 고정 재사용
        self._image_size: tuple[int, int] = (0, 0)   # (w, h) — 원본 이미지 픽셀 크기
        self._threshold_timer = QTimer(self)
        self._threshold_timer.setSingleShot(True)
        self._threshold_timer.setInterval(150)
        self._threshold_timer.timeout.connect(self._on_target_changed)
        # ── R-ZONE-3: 사이드카 자동 저장(디바운스) ─────────────────────────────
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(500)
        self._save_timer.timeout.connect(self._flush_state)
        self._save_failed_once = False   # 세션당 1회만 저장 실패 팝업(판단 6)
        self._ckpt_auto_selected = False
        self._step6_touched = False   # 브러시 그리기/지우기/블랍삭제를 1번이라도 했는가
        self._result_viewed = False   # 결과 분석 팝업을 1번이라도 열었는가
        self._build_ui()
        self._refresh_step_indicator()

    # ── UI 구성 ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        self._step_indicator = ZoneStepIndicator()
        root.addWidget(self._step_indicator)

        # ── 상단 툴바 (승인된 목업 순서, Artifact 984ea900 — 이번 세션엔 Artifact
        #    도구가 없어 스펙 문서 "승인된 UI 레이아웃" 절 서술을 그대로 따름):
        #    체크포인트 상태+열기 / ▶ 추론 실행 / 타겟클래스 / AI신뢰도 / 픽셀 threshold /
        #    (민감도 — 자동검출의 파라미터라 바로 옆에 배치) / 자동검출 / 블랍삭제모드.
        #    (오프라인 원 검출 테스트는 2026-08-30 요청으로 삭제됨.) 이미지 열기는
        #    좌측 패널로 이동(C-1). ─
        # 두 줄로 분리(BUG-021 수정) — 한 줄에 다 욱여넣으면 최소폭이 1588px까지
        # 벌어져 MainWindow 코딩된 기본 크기(1280x800)를 조용히 무시하고 더 넓게
        # 뜸(main_window.py의 resize() 호출과 실제 동작이 어긋나는 버그였음).
        ckpt_card = QFrame()
        ckpt_card.setStyleSheet(
            "background:#1f2329;border:1px solid #374151;border-radius:8px;"
        )
        toolbar_row1 = QHBoxLayout(ckpt_card)
        toolbar_row1.setContentsMargins(14, 7, 14, 7)
        toolbar_row2 = QHBoxLayout()

        self._btn_ckpt = QPushButton("체크포인트 열기 (.pt)…")
        toolbar_row1.addWidget(self._btn_ckpt)
        self._lbl_ckpt_dot = QLabel("●")
        self._lbl_ckpt_dot.setStyleSheet("color:#34d399;font-size:15px;background:transparent;border:none;")
        toolbar_row1.addWidget(self._lbl_ckpt_dot)
        self._lbl_ckpt = QLabel("선택된 체크포인트 없음")
        self._lbl_ckpt.setStyleSheet("color:#9ca3af;")
        toolbar_row1.addWidget(self._lbl_ckpt)
        self._lbl_ckpt_badge = QLabel("자동 선택됨")
        self._lbl_ckpt_badge.setStyleSheet(
            "color:#34d399;font-size:11px;background:#0d2318;"
            "border:1px solid #10b981;border-radius:4px;padding:1px 6px;"
        )
        self._lbl_ckpt_badge.hide()
        toolbar_row1.addWidget(self._lbl_ckpt_badge)

        self._infer_progress = QProgressBar()
        self._infer_progress.setFixedWidth(110)
        self._infer_progress.hide()
        toolbar_row1.addWidget(self._infer_progress)

        toolbar_row1.addWidget(QLabel("타겟(녹) 클래스:"))
        self._target_name_edit = QLineEdit()
        self._target_name_edit.setPlaceholderText("클래스 이름 (예: 녹)")
        self._target_name_edit.setFixedWidth(120)
        self._target_name_edit.hide()
        toolbar_row1.addWidget(self._target_name_edit)
        self._target_combo = QComboBox()
        self._target_combo.setFixedWidth(160)
        self._target_combo.hide()
        toolbar_row1.addWidget(self._target_combo)
        toolbar_row1.addStretch()
        lbl_mode = QLabel("추론 방식: <b style='color:#cbd5e1'>sliding window</b> (고정)")
        lbl_mode.setStyleSheet("color:#9ca3af;font-size:11px;background:transparent;border:none;")
        toolbar_row1.addWidget(lbl_mode)
        self._btn_run = QPushButton("▶  추론 실행")
        self._btn_run.setStyleSheet(
            "background:#1e3a5f;border:1.5px solid #60a5fa;border-radius:5px;"
            "padding:6px 18px;color:#93c5fd;font-weight:bold;font-size:13.5px;"
        )
        toolbar_row1.addWidget(self._btn_run)

        toolbar_row2.addWidget(QLabel("AI 신뢰도:"))
        self._conf_slider = QSlider(Qt.Orientation.Horizontal)
        self._conf_slider.setRange(0, 100)
        self._conf_slider.setValue(int(_DEFAULT_MIN_CONFIDENCE * 100))
        self._conf_slider.setFixedWidth(90)
        self._conf_slider.setToolTip("blob(연결 영역)의 평균 신뢰도가 이 값 미만이면 배경으로 제거")
        toolbar_row2.addWidget(self._conf_slider)
        self._lbl_confidence = QLabel(f"{self._conf_slider.value()}%")
        self._lbl_confidence.setFixedWidth(32)
        toolbar_row2.addWidget(self._lbl_confidence)

        toolbar_row2.addWidget(QLabel("픽셀 threshold:"))
        self._min_px_spin = QSpinBox()
        self._min_px_spin.setRange(0, 100000)
        self._min_px_spin.setValue(_DEFAULT_MIN_PIXEL_SIZE)
        self._min_px_spin.setSuffix(" px")
        self._min_px_spin.setFixedWidth(90)
        self._min_px_spin.setToolTip("blob 면적(픽셀 수)이 이 값 미만이면 배경으로 제거")
        toolbar_row2.addWidget(self._min_px_spin)

        toolbar_row2.addWidget(QLabel("민감도:"))
        self._sensitivity_slider = QSlider(Qt.Orientation.Horizontal)
        self._sensitivity_slider.setRange(0, 100)
        self._sensitivity_slider.setValue(50)
        self._sensitivity_slider.setFixedWidth(90)
        self._sensitivity_slider.setToolTip("원 자동 검출 민감도(아래 '자동 검출' 버튼의 파라미터)")
        toolbar_row2.addWidget(self._sensitivity_slider)
        self._lbl_sensitivity = QLabel("50%")
        self._lbl_sensitivity.setFixedWidth(32)
        toolbar_row2.addWidget(self._lbl_sensitivity)
        self._btn_detect = QPushButton("자동 검출")
        self._btn_detect.setEnabled(False)
        self._btn_detect.setToolTip("추론을 먼저 실행하면 검출된 원이 캔버스에 표시됩니다")
        toolbar_row2.addWidget(self._btn_detect)

        self._edit_toolbar = QToolBar()
        self._edit_toolbar.setIconSize(QSize(20, 20))
        self._edit_toolbar.setStyleSheet(
            "QToolBar QToolButton { min-width:36px; min-height:30px; padding:4px 8px; }"
        )
        self._tool_group = QActionGroup(self)
        self._tool_group.setExclusive(True)

        def tool_action(icon_name: str, text: str, mode: str) -> QAction:
            action = QAction(svg_icon(icon_name), "", self)
            action.setToolTip(text)
            action.setCheckable(True)
            action.setData(mode)
            self._tool_group.addAction(action)
            self._edit_toolbar.addAction(action)
            return action

        self._act_circle = tool_action("tool_polygon", "원 편집", "circle")
        self._act_brush_draw = tool_action("tool_brush", "브러시로 타겟 영역 그리기", "brush_draw")
        self._act_brush_erase = tool_action("tool_eraser", "브러시로 타겟 영역 지우기", "brush_erase")
        self._act_blob_delete = tool_action("tool_eraser_flood", "클릭한 연결 블랍 삭제", "blob_delete")
        self._act_pan = tool_action("tool_pan", "화면 이동", "pan")
        self._act_circle.setChecked(True)
        self._active_tool_action: QAction = self._act_circle
        for action in self._tool_group.actions():
            action.setEnabled(False)
        self._edit_toolbar.addSeparator()
        self._edit_toolbar.addWidget(QLabel("브러시 크기:"))
        self._erase_brush_spin = QSpinBox()
        self._erase_brush_spin.setRange(1, 200)
        self._erase_brush_spin.setValue(30)
        self._erase_brush_spin.setSuffix(" px")
        self._erase_brush_spin.setFixedWidth(90)
        self._erase_brush_spin.setToolTip("그리기/지우기 브러시 지름(원본 이미지 픽셀 단위)")
        self._erase_brush_spin.setEnabled(False)
        self._edit_toolbar.addWidget(self._erase_brush_spin)

        self._edit_toolbar.addSeparator()
        self._act_undo = self._edit_toolbar.addAction(svg_icon("undo"), "")
        self._act_undo.setEnabled(False)
        self._act_undo.setToolTip("원/그리기/지우기/블랍 삭제를 시간순으로 되돌립니다 (Ctrl+Z)")

        toolbar_row2.addStretch()
        root.addWidget(ckpt_card)
        root.addLayout(toolbar_row2)

        self._lbl_model_info = QLabel("")
        self._lbl_model_info.setStyleSheet(
            "color:#9ca3af; font-size:11px; padding:2px 4px;"
            "background:#1a1d23; border-radius:3px;"
        )
        root.addWidget(self._lbl_model_info)

        self._lbl_target_info = QLabel("추론을 먼저 실행하세요")
        self._lbl_target_info.setStyleSheet("color:#9ca3af; font-size:11px;")
        root.addWidget(self._lbl_target_info)

        # ── 커스텀 모델 코드 박스 (툴바 아래, preset이 아닌 체크포인트일 때만 노출) ──
        self._code_box = QGroupBox("모델 아키텍처 코드 (이 체크포인트는 프리셋이 아님)")
        code_layout = QVBoxLayout(self._code_box)
        self._code_editor = QPlainTextEdit()
        self._code_editor.setPlaceholderText(
            "import torch.nn as nn\n\nclass MyModel(nn.Module):\n    ..."
        )
        code_layout.addWidget(self._code_editor)
        code_btn_row = QHBoxLayout()
        self._btn_validate = QPushButton("검증 (Validate)")
        self._btn_load_code = QPushButton("로드 (Load Model)")
        self._btn_load_code.setEnabled(False)
        code_btn_row.addWidget(self._btn_validate)
        code_btn_row.addWidget(self._btn_load_code)
        code_btn_row.addStretch()
        code_layout.addLayout(code_btn_row)
        self._code_log = QTextEdit()
        self._code_log.setReadOnly(True)
        self._code_log.setMaximumHeight(80)
        code_layout.addWidget(self._code_log)
        self._code_box.hide()
        root.addWidget(self._code_box)

        # ── 좌·중·우 3분할 ───────────────────────────────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)   # BUG-020 수정 — 다른 탭 스플리터(BUG-008)와 동일 조치

        # 좌측 패널(C-1/3a) — 폴더/다중파일 열기 + 경로 표시 + InferenceImageList
        # (추론 탭과 공유하는 완전 독립 위젯, inference_tab.py의 _list_panel/_img_list
        # 구성을 그대로 이식) + 배치 처리 컨트롤(체크박스+버튼, 3b).
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 4, 0)
        header_row = QHBoxLayout()
        self._lbl_images_header = QLabel("② 이미지")
        self._lbl_images_header.setStyleSheet("color:#60a5fa;font-weight:bold;background:transparent;border:none;")
        header_row.addWidget(self._lbl_images_header)
        header_row.addStretch()
        self._btn_image = QPushButton(t("ui.add_file"))
        self._btn_image.setToolTip(t("ui.add_file.tip"))
        self._btn_folder = QPushButton(t("ui.add_folder"))
        self._btn_folder.setToolTip(t("ui.add_folder.tip"))
        header_row.addWidget(self._btn_image)
        header_row.addWidget(self._btn_folder)
        left_layout.addLayout(header_row)
        self._lbl_folder_path = QLabel("선택된 이미지 없음")
        self._lbl_folder_path.setStyleSheet("color:#9ca3af; font-size:11px;")
        self._lbl_folder_path.setWordWrap(True)
        left_layout.addWidget(self._lbl_folder_path)
        self._img_list = InferenceImageList()
        self._img_list.set_multi_select(True)   # "선택 이미지 일괄 처리" 대상 지정용 배선(3b)
        self._img_list.hide()   # count<=1 이면 숨김 — 단일 이미지 워크플로우 회귀 없음
        left_layout.addWidget(self._img_list, stretch=1)

        # ── 배치 컨트롤 (3b) — 좌측 패널 하단, 발견성 개선을 위해 그룹박스로 묶음 ──
        self._batch_box = QGroupBox("Zone 결정 방법")
        batch_layout = QVBoxLayout(self._batch_box)
        self._mode_combo = QComboBox()
        self._mode_combo.addItem("일괄 적용", "apply_all")
        self._mode_combo.addItem("일괄 적용 후 수정", "apply_all_edit")
        self._mode_combo.addItem("장별 적용(이미지별 개별)", "per_image")
        self._mode_combo.setToolTip(
            "일괄 적용: 기준 이미지의 원을 나머지 전체에 그대로 적용\n"
            "일괄 적용 후 수정: 위와 동일하게 적용 후 이미지별로 열어 직접 수정(자동 저장)\n"
            "장별 적용: 이미지마다 원을 개별 자동 검출(민감도 슬라이더 값 사용)"
        )
        batch_layout.addWidget(self._mode_combo)
        self._btn_recipe = QPushButton(svg_icon("tool_polygon"), "원(Zone) 설정...")
        self._btn_recipe.setStyleSheet(
            "background:#2b313a;border:1px solid #60a5fa;border-radius:5px;"
            "padding:6px 8px;color:#93c5fd;"
        )
        self._btn_recipe.setToolTip(
            "레시피(저장된 원 집합)를 불러오거나 새로 만들어 기준 이미지에 적용합니다.\n"
            "'장별 적용' 모드에서는 이미지마다 개별 자동 검출을 쓰므로 표시되지 않습니다."
        )
        batch_layout.addWidget(self._btn_recipe)
        self._btn_batch = QPushButton("▶ 선택 이미지 일괄 처리 (0장)")
        self._btn_batch.setEnabled(False)
        self._btn_batch.setToolTip(
            "목록에 2장 이상 있고, 기준(현재 로드된) 이미지에 원이 1개 이상 정의돼 있어야 합니다\n"
            "(Ctrl/Shift로 여러 장 고르면 그 부분집합만 처리 — 정확히 1장만 골라도 목록 전체가 "
            "처리됩니다. 1장만 확인하려면 그 이미지를 클릭해 캔버스에서 직접 확인하세요.)"
        )
        batch_layout.addWidget(self._btn_batch)
        self._lbl_batch_condition = QLabel("필요 조건: 추론 실행 · 원 1개 이상 · 이미지 2장 이상")
        self._lbl_batch_condition.setStyleSheet("color:#9ca3af; font-size:11px;")
        self._lbl_batch_condition.setWordWrap(True)
        batch_layout.addWidget(self._lbl_batch_condition)
        left_layout.addWidget(self._batch_box)

        left.setMinimumWidth(180)
        left.setMaximumWidth(260)
        splitter.addWidget(left)

        # 중앙 — 캔버스 전용 헤더(편집 툴바 + 정렬 버튼) + 캔버스 (가능한 한 크게)
        self._canvas = ZoneCanvas()

        canvas_panel = QWidget()
        canvas_layout = QVBoxLayout(canvas_panel)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        canvas_layout.setSpacing(0)
        canvas_panel.setStyleSheet(
            "background:#1f2329;border:1px solid #374151;border-radius:8px;"
        )

        toolbar_header = QWidget()
        toolbar_header.setStyleSheet("background:#1f2329;border:none;border-bottom:1px solid #374151;")
        toolbar_header_layout = QHBoxLayout(toolbar_header)
        toolbar_header_layout.setContentsMargins(8, 5, 8, 5)
        toolbar_header_layout.addWidget(self._edit_toolbar)
        self._lbl_wheel_hint = QLabel("휠: 화면 줌 · Alt+휠: 선택한 원 지름 조절")
        self._lbl_wheel_hint.setStyleSheet("color:#9ca3af;font-size:10.5px;")
        toolbar_header_layout.addWidget(self._lbl_wheel_hint)
        toolbar_header_layout.addStretch()
        self._btn_align = QPushButton("정렬(중심 맞추기)")
        self._btn_align.setToolTip("모든 원의 중심을 평균 중심으로 맞춥니다(반지름은 그대로).")
        toolbar_header_layout.addWidget(self._btn_align)
        canvas_layout.addWidget(toolbar_header)
        canvas_layout.addWidget(self._canvas, stretch=1)

        splitter.addWidget(canvas_panel)

        # 우측 — 원/존 목록 (R2/R3 로직 그대로, 컨테이너 위치만 이동)
        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(4, 0, 0, 0)
        side_layout.addWidget(QLabel("검출된 원 (반지름 오름차순)"))
        self._circle_list = QListWidget()
        self._circle_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._circle_list.customContextMenuRequested.connect(self._on_circle_list_context_menu)
        side_layout.addWidget(self._circle_list, stretch=1)
        side_layout.addWidget(QLabel("존별 타겟 클래스 비율 (%)"))
        self._zone_list = QListWidget()
        self._zone_list.setToolTip("클릭하면 캔버스에서 해당 존이 하이라이트됩니다")
        side_layout.addWidget(self._zone_list, stretch=1)
        self._lbl_selected_blob = QLabel("")
        self._lbl_selected_blob.setWordWrap(True)
        self._lbl_selected_blob.setStyleSheet("color:#fbbf24; font-size:11px;")
        side_layout.addWidget(self._lbl_selected_blob)
        self._btn_export_single = QPushButton("현재 이미지 결과 보기")
        self._btn_export_single.setStyleSheet(
            "background:#1e3a5f;border:1.5px solid #60a5fa;border-radius:5px;"
            "padding:7px 8px;color:#93c5fd;font-weight:bold;"
        )
        self._btn_export_single.setToolTip("현재 화면에 표시된 존 목록(이미지 1장)을 표로 보고 Excel/클립보드로 내보냅니다")
        side_layout.addWidget(self._btn_export_single)
        self._btn_view_all = QPushButton("전체 결과 보기")
        self._btn_view_all.setToolTip(
            "이번 세션에서 추론을 실행한 모든 이미지를 모아서 봅니다.\n"
            "(세션 메모리 기반 — 과거 세션 결과나 미추론 이미지는 제외됩니다.)"
        )
        self._btn_view_all.setEnabled(False)
        side_layout.addWidget(self._btn_view_all)
        side.setMinimumWidth(160)
        side.setMaximumWidth(220)
        splitter.addWidget(side)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([200, 700, 180])
        root.addWidget(splitter, stretch=1)

        # ── 시그널 ───────────────────────────────────────────────────────────
        self._btn_image.clicked.connect(self._on_select_image)
        self._btn_folder.clicked.connect(self._on_select_folder)
        self._img_list.image_selected.connect(self._on_list_image_selected)
        self._img_list.selection_changed.connect(self._update_batch_button_label)
        self._img_list.display_changed.connect(self._update_batch_button_label)
        self._img_list.display_changed.connect(self._update_batch_button_state)
        self._img_list.images_removed.connect(self._on_images_removed)
        self._btn_recipe.clicked.connect(self._on_open_recipe_dialog)
        self._mode_combo.currentIndexChanged.connect(self._on_batch_mode_changed)
        self._on_batch_mode_changed()   # 초기 모드 기준 버튼 표시 상태 반영
        self._btn_batch.clicked.connect(self._on_batch_process)
        self._btn_ckpt.clicked.connect(self._on_select_checkpoint)
        self._btn_validate.clicked.connect(self._on_validate)
        self._btn_load_code.clicked.connect(self._on_load_code)
        self._btn_run.clicked.connect(self._on_run)
        self._target_name_edit.editingFinished.connect(self._on_target_changed)
        self._target_combo.currentIndexChanged.connect(self._on_target_changed)
        self._btn_detect.clicked.connect(self._on_auto_detect)
        self._sensitivity_slider.valueChanged.connect(
            lambda v: self._lbl_sensitivity.setText(f"{v}%")
        )
        self._conf_slider.valueChanged.connect(
            lambda v: self._lbl_confidence.setText(f"{v}%")
        )
        self._conf_slider.valueChanged.connect(lambda _v: self._threshold_timer.start())
        self._min_px_spin.valueChanged.connect(lambda _v: self._threshold_timer.start())
        self._btn_align.clicked.connect(self._canvas.align_centers)
        self._canvas.circles_changed.connect(self._refresh_circle_list)
        self._canvas.circles_committed.connect(self._recompute_zones)
        self._canvas.circles_changed.connect(self._update_batch_button_state)
        # R-ZONE-3: 원편집/블랍삭제/브러시스트로크 3개 시그널 전부 편집마다
        # 디바운스 타이머를 재시작(annotation_canvas.py의 자동 저장 패턴과 동일).
        self._canvas.circles_changed.connect(lambda: self._save_timer.start())
        self._canvas.blob_deleted.connect(lambda _id: self._save_timer.start())
        self._canvas.erase_changed.connect(lambda: self._save_timer.start())
        self._canvas.circle_selected.connect(self._on_canvas_circle_selected)
        self._canvas.zone_clicked.connect(self._on_canvas_zone_clicked)
        self._canvas.blob_deleted.connect(self._on_blob_deleted)
        self._canvas.blob_clicked.connect(self._on_canvas_blob_clicked)
        self._tool_group.triggered.connect(self._on_edit_tool_changed)
        self._erase_brush_spin.valueChanged.connect(self._canvas.set_erase_brush_size)
        self._canvas.erase_changed.connect(self._recompute_zones)
        self._canvas.overlay_toggle_requested.connect(self._toggle_overlay)
        self._act_undo.triggered.connect(self._canvas.undo)
        # Undo 버튼 활성/비활성 갱신 — 신규 시그널을 발명하지 않고 상태를 바꿀 수
        # 있는 기존 세 시그널(원변경/블랍삭제/지우기)에 편승한다(스펙 판단 1).
        self._canvas.circles_changed.connect(self._update_undo_button_state)
        self._canvas.blob_deleted.connect(self._update_undo_button_state)
        self._canvas.erase_changed.connect(self._update_undo_button_state)
        self._circle_list.currentRowChanged.connect(self._on_list_row_selected)
        self._zone_list.currentRowChanged.connect(self._on_zone_row_selected)
        self._btn_export_single.clicked.connect(self._on_export_single)
        self._btn_view_all.clicked.connect(self._on_view_all_results)
        # 스텝 인디케이터 — 신규 시그널 없이 기존 호출부에 편승(주석 위 Undo 관례와 동일 패턴).
        self._canvas.circles_changed.connect(self._refresh_step_indicator)
        self._canvas.blob_deleted.connect(lambda _id: self._mark_step6_touched())
        self._canvas.erase_changed.connect(self._mark_step6_touched)

    # ── 슬롯 — 이미지 / 체크포인트 선택 (C-1) ────────────────────────────────

    def _on_select_image(self) -> None:
        """다중 파일 선택 — inference_tab._on_select_file과 동일 패턴."""
        paths, _ = QFileDialog.getOpenFileNames(
            self, "이미지 선택", "",
            "Images (*.jpg *.jpeg *.png *.bmp *.tiff *.tif)"
        )
        if not paths:
            return
        self._img_list.load_files([Path(p) for p in paths], append=True)
        self._lbl_folder_path.setText(
            f"{len(paths)}개 파일 선택됨" if len(paths) > 1 else str(Path(paths[0]).parent)
        )
        self._lbl_folder_path.setStyleSheet("color:#e5e7eb; font-size:11px;")
        self._after_list_load()

    def _on_select_folder(self) -> None:
        """폴더 열기 — 하위 폴더 포함 재귀 스캔(InferenceImageList.load_folder)."""
        folder = QFileDialog.getExistingDirectory(self, "폴더 선택")
        if not folder:
            return
        self._img_list.load_folder(Path(folder), append=True)
        if self._img_list.count() == 0:
            QMessageBox.information(
                self, "이미지 없음", "선택한 폴더(하위 폴더 포함)에 지원되는 이미지가 없습니다."
            )
            return
        self._lbl_folder_path.setText(folder)
        self._lbl_folder_path.setStyleSheet("color:#e5e7eb; font-size:11px;")
        self._after_list_load()

    def _after_list_load(self) -> None:
        # 목록은 이미지가 2장 이상일 때만 표시 — 단일 이미지 워크플로우는 목록
        # 없이 그대로 동작(회귀 없음, 스펙 C-1 명시).
        self._img_list.setVisible(self._img_list.count() > 1)
        self._lbl_images_header.setText(f"② 이미지 ({self._img_list.count()})")
        self._refresh_step_indicator()

    def _on_images_removed(self, removed: list[Path]) -> None:
        """목록에서 이미지가 제거됐을 때 — 추론 결과 캐시를 정리하고, 현재
        로드된 이미지가 삭제 대상이면 캔버스를 비운다(메모리/상태 누수 방지)."""
        for p in removed:
            self._results.pop(p, None)
            self._target_cache.pop(p, None)
        if self._image_path in removed:
            self._image_path = None
            self._last_result = None
            self._image_size = (0, 0)
            self._original_pixmap = None
            self._canvas.set_image_size(*self._image_size)
            self._canvas.clear()
            for action in self._tool_group.actions():
                action.setEnabled(False)
            self._btn_detect.setEnabled(False)
            self._canvas.set_blob_data(None, None)
            self._canvas.set_highlight_rect(None)
            self._lbl_selected_blob.setText("")
        self._lbl_images_header.setText(f"② 이미지 ({self._img_list.count()})")
        self._refresh_step_indicator()

    def _on_list_image_selected(self, path: Path) -> None:
        """목록에서 이미지를 클릭(단일 선택 또는 load_folder/load_files 직후 자동
        선택)했을 때 — 기존 단일 이미지 로드 로직 그대로 재사용. 자동 추론은
        실행하지 않는다(스펙 명시 — 수동 '▶ 추론 실행' 트리거 유지).

        R-ZONE-3: 이미지 전환 전 이전 이미지의 편집 상태를 동기 flush하고,
        새 이미지는 타겟 클래스 구성 이후 사이드카가 있으면 복원한다."""
        if (self._image_path is not None and self._image_path != path
                and self._save_timer.isActive()):
            self._save_timer.stop()
            self._flush_state()   # 전환 전 동기 flush(annotation_canvas.load_image()와 동일 패턴)
        self._image_path = path
        self._last_result = self._results.get(path)
        try:
            with Image.open(str(path)) as im:
                rgb_im = im.convert("RGB")
                self._image_size = rgb_im.size   # (w, h)
                rgb_im.thumbnail((_PREVIEW_MAX_DIM, _PREVIEW_MAX_DIM), Image.BILINEAR)
                preview_rgb = np.array(rgb_im)
            self._canvas.set_image_size(*self._image_size)
            self._original_pixmap = _rgb_to_qpixmap(preview_rgb)
            self._canvas.set_pixmap(self._original_pixmap)
            self._act_circle.setEnabled(True)
            self._act_pan.setEnabled(True)
            # 7-2: 자동 검출/원 편집은 추론 결과와 무관하게 이미지만 로드되면
            # 바로 쓸 수 있다(detect_circles()는 원본 이미지만 참조) — 영역
            # 설정을 추론 전에 할 수 있어야 한다는 재설계 요구사항과 일치.
            self._btn_detect.setEnabled(True)
        except Exception:
            self._image_size = (0, 0)
            self._original_pixmap = None
            self._canvas.set_image_size(*self._image_size)
            self._canvas.clear()
            for action in self._tool_group.actions():
                action.setEnabled(False)
            self._btn_detect.setEnabled(False)
        self._canvas.set_blob_data(None, None)
        self._canvas.set_highlight_rect(None)
        self._lbl_selected_blob.setText("")
        self._act_circle.setChecked(True)
        self._on_edit_tool_changed(self._act_circle)
        for action in (self._act_brush_draw, self._act_brush_erase, self._act_blob_delete):
            action.setEnabled(False)
        self._update_undo_button_state()   # set_blob_data가 undo 스택을 비웠으므로 즉시 반영
        if self._last_result is not None:
            self._setup_target_classes(self._last_result)   # set_blob_data(labels,stats) 재호출
        # R-ZONE-3: 사이드카 복원은 반드시 _setup_target_classes() 이후에 수행해야
        # 한다 — set_blob_data()가 manual_strokes/undo 스택을 초기화하므로, 순서가
        # 바뀌면 방금 복원한 상태를 다시 지워버리는 사고가 난다(스펙 "순서 주의").
        cached = zstate.load_state(path)
        if cached is not None:
            self._canvas.set_state(cached)
        else:
            self._canvas.clear_circles()     # 사이드카 없으면 기존처럼 빈 캔버스

    def _flush_state(self) -> None:
        """현재 이미지의 편집 상태를 사이드카에 즉시 저장 — 디바운스 타이머
        콜백 또는 이미지 전환 직전 동기 호출 둘 다 이 함수 하나로 처리
        (`annotation_canvas.py`의 `_do_save()`와 동일 역할, R-ZONE-3 판단 1)."""
        if self._image_path is None:
            return
        try:
            zstate.save_state(self._image_path, self._canvas.get_state())
        except OSError as exc:
            log.warning(f"Zone 상태 저장 실패 — {self._image_path}: {exc}")
            if not self._save_failed_once:   # 세션당 1회만 표면화(판단 6)
                self._save_failed_once = True
                QMessageBox.warning(
                    self, "저장 실패",
                    f"{self._image_path.parent} 폴더에 편집 내용을 저장하지 못했습니다"
                    "(읽기 전용 등). 이후 실패는 조용히 로그에만 남습니다."
                )

    def _on_select_checkpoint(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "체크포인트 선택", "", "Checkpoint (*.pt)"
        )
        if not path:
            return
        self._ckpt_auto_selected = False
        self._apply_checkpoint(Path(path))

    def set_default_checkpoint(self, path: Path | None) -> None:
        """탭 진입 시 외부(추론 탭)에서 넘겨주는 기본값 — 이미 사용자가 뭔가
        선택해둔 상태(self._ckpt_path is not None)면 아무 것도 하지 않는다."""
        if path is None or self._ckpt_path is not None:
            return
        self._ckpt_auto_selected = True
        self._apply_checkpoint(path)

    def _apply_checkpoint(self, path: Path) -> None:
        self._ckpt_path = path
        self._lbl_ckpt.setText(self._ckpt_path.name)
        self._lbl_ckpt.setStyleSheet("color:#e5e7eb;")
        self._model = None
        self._code_box.hide()

        meta = load_checkpoint_meta(self._ckpt_path)
        label = model_source_label(meta.model_source)

        if meta.model_source.startswith("preset:"):
            model = load_model_from_ckpt(self._ckpt_path)
            if model is not None:
                self._model = model
                self._lbl_model_info.setText(f"{label}  (자동 준비됨)")
                self._lbl_model_info.setStyleSheet(
                    "color:#34d399; font-size:11px; padding:2px 4px;"
                )
            else:
                self._lbl_model_info.setText(f"{label} 프리셋 로드 실패 — 아래에 코드를 붙여넣으세요")
                self._lbl_model_info.setStyleSheet(
                    "color:#f87171; font-size:11px; padding:2px 4px;"
                )
                self._code_box.show()
        else:
            reason = "사용자 정의 모델" if meta.model_source == "loaded" else "모델 정보 없는 체크포인트"
            self._lbl_model_info.setText(
                f"{reason} — 이 체크포인트를 학습한 모델 코드를 아래에 붙여넣고 Validate → Load 하세요"
            )
            self._lbl_model_info.setStyleSheet(
                "color:#fbbf24; font-size:11px; padding:2px 4px;"
            )
            self._code_box.show()

        self._lbl_ckpt_badge.setVisible(self._ckpt_auto_selected)
        self._refresh_step_indicator()

    # ── 슬롯 — 커스텀 모델 코드 (Validate → Load, save_user_code 호출 안 함) ──

    def _on_validate(self) -> None:
        code = self._code_editor.toPlainText().strip()
        self._code_log.clear()
        if not code:
            self._log_code("[WARN] 코드가 비어 있습니다.", "#fbbf24")
            return
        result = validate(code)
        for err in result.errors:
            self._log_code(f"[ERR] {err}", "#f87171")
        for warn in result.warnings:
            self._log_code(f"[WARN] {warn}", "#fbbf24")
        if result.ok:
            self._log_code(f"[OK] 검증 통과 — 클래스: {result.model_class_name}", "#10b981")
            self._btn_load_code.setEnabled(True)
        else:
            self._log_code(f"[ERR] 검증 실패 — {len(result.errors)}개 오류", "#f87171")
            self._btn_load_code.setEnabled(False)

    def _on_load_code(self) -> None:
        code = self._code_editor.toPlainText().strip()
        result = load_from_code(code)   # save_user_code() 호출하지 않음 — 세션 메모리에만 유지
        if not result.ok:
            self._log_code(f"[ERR] 로드 실패: {result.error}", "#f87171")
            return
        self._model = result.model
        self._log_code(
            f"[OK] 로드 완료 — 클래스: {result.class_name}  파라미터: {result.num_params:,}",
            "#10b981",
        )
        self._lbl_model_info.setText(f"{result.class_name}  (커스텀 모델 로드됨)")
        self._lbl_model_info.setStyleSheet(
            "color:#34d399; font-size:11px; padding:2px 4px;"
        )

    def _log_code(self, msg: str, color: str) -> None:
        self._code_log.append(f'<span style="color:{color}">{msg}</span>')

    # ── 슬롯 — 추론 실행 ──────────────────────────────────────────────────────

    def _on_run(self) -> None:
        if self._image_path is None:
            QMessageBox.warning(self, "이미지 없음", "이미지를 먼저 선택하세요.")
            return
        if self._ckpt_path is None:
            QMessageBox.warning(self, "체크포인트 없음", "체크포인트를 먼저 선택하세요.")
            return
        if self._model is None:
            QMessageBox.warning(
                self, "모델 없음",
                "모델이 준비되지 않았습니다. 프리셋이 아닌 체크포인트라면 코드를 "
                "붙여넣고 Validate → Load 하세요.",
            )
            return

        if not prompt_gpu_availability(self, "존 분석"):
            return

        if not self._canvas.get_circles():
            reply = QMessageBox.question(
                self, "영역 없음",
                "영역(원)이 설정되지 않았습니다. 그래도 추론을 진행하시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        paths = self._img_list.paths() or [self._image_path]
        self._results.clear()
        self._target_cache.clear()   # R-PERF-1: 새 추론 세션 — 이전 캐시는 전부 무의미
        self._btn_view_all.setEnabled(bool(self._results))
        self._btn_run.setEnabled(False)
        self._btn_run.setText("추론 중…")
        self._infer_progress.setRange(0, len(paths))
        self._infer_progress.setValue(0)
        self._infer_progress.setFormat("0/%d (0%%)" % len(paths))
        self._infer_progress.setToolTip("")
        self._infer_progress.show()
        self._infer_elapsed = QElapsedTimer()
        self._infer_elapsed.start()
        self._worker = _ZoneInferenceWorker(
            self._model, paths, self._ckpt_path
        )
        self._worker.result_ready.connect(self._on_inference_result)
        self._worker.failed.connect(
            lambda path, message: log.error(f"존 분석 추론 실패 — {path}: {message}")
        )
        self._worker.finished.connect(self._on_inference_finished)
        self._worker.start()
        self._refresh_step_indicator()

    def _on_inference_result(self, path: Path, result: InferenceResult,
                             done: int, total: int) -> None:
        self._results[path] = result
        self._btn_view_all.setEnabled(bool(self._results))
        self._infer_progress.setValue(done)
        self._infer_progress.setFormat(f"{done}/{total} (%p%)")   # 폭(110px) 유지 — 바 안엔 퍼센트까지만
        if done > 0:
            avg_ms = self._infer_elapsed.elapsed() / done
            remain_s = max(0, avg_ms * (total - done) / 1000.0)
            m, s = divmod(int(remain_s), 60)
            eta_txt = f"예상 남은 시간: 약 {m}분 {s}초" if m else f"예상 남은 시간: 약 {s}초"
            self._infer_progress.setToolTip(eta_txt)   # ETA는 호버로 확인(디자인 확인 2026-10-03#3)
        if path == self._image_path:
            self._last_result = result
            self._setup_target_classes(result)

    def _on_inference_finished(self) -> None:
        self._btn_run.setEnabled(True)
        self._btn_run.setText("▶  전체 추론 실행")
        self._infer_progress.setFormat(
            f"완료 {len(self._results)} / {self._infer_progress.maximum()}"
        )
        self._worker = None
        self._refresh_step_indicator()

    # ── 타겟(녹) 클래스 즉석 구성 (판단 4) ────────────────────────────────────

    def _setup_target_classes(self, result: InferenceResult) -> None:
        ids = sorted(int(i) for i in set(result.raw_class_map.ravel().tolist()) if i != 0)
        self._detected_ids = ids
        # 7-2: _btn_detect는 이미지 로드 시점에 이미 활성화돼 있다(추론 결과와
        # 무관) — 여기서 다시 건드리지 않는다.

        self._target_name_edit.hide()
        self._target_combo.hide()

        if not ids:
            self._lbl_target_info.setText("배경 외 클래스가 검출되지 않았습니다.")
            self._show_overlay_state()
            self._target_class_id = None
            self._canvas.set_blob_data(None, None)
            self._canvas.set_highlight_rect(None)
            self._lbl_selected_blob.setText("")
            self._act_circle.setChecked(True)
            self._on_edit_tool_changed(self._act_circle)
            # 7-2: _btn_detect는 블랍 마스크와 무관(detect_circles는 원본 이미지만
            # 참조)하므로 타겟 클래스가 없어도 비활성화하지 않는다 — BUG-031 당시의
            # 제약은 "추론 전엔 원 설정 불가"라는 구UX 전제에 묶여 있던 것으로,
            # 재설계(7-2)로 그 전제 자체가 제거됨.
            for action in (self._act_brush_draw, self._act_brush_erase, self._act_blob_delete):
                action.setEnabled(False)
            self._update_undo_button_state()   # set_blob_data가 undo 스택을 비웠으므로 즉시 반영
            self._recompute_zones()
            return

        if len(ids) == 1:
            self._target_name_edit.blockSignals(True)
            self._target_name_edit.setText("class_1")
            self._target_name_edit.blockSignals(False)
            self._target_name_edit.show()
            self._lbl_target_info.setText(f"클래스 1개 검출됨 (id={ids[0]}) — 이름 수정 가능")
        else:
            self._target_combo.blockSignals(True)
            self._target_combo.clear()
            for i, cid in enumerate(ids):
                self._target_combo.addItem(f"class_{i + 1} (id={cid})", cid)
            self._target_combo.blockSignals(False)
            self._target_combo.show()
            self._lbl_target_info.setText(f"클래스 {len(ids)}개 검출됨 — 타겟을 선택하세요")

        self._on_target_changed()

    def _on_target_changed(self) -> None:
        if self._last_result is None or not self._detected_ids:
            return

        if len(self._detected_ids) == 1:
            cid = self._detected_ids[0]
            name = self._target_name_edit.text().strip() or "class_1"
        else:
            cid = self._target_combo.currentData()
            if cid is None:
                return
            idx = self._target_combo.currentIndex()
            name = f"class_{idx + 1}"

        classes = [
            ClassDef(0, "background", DEFAULT_PALETTE[0]),
            ClassDef(cid, name, DEFAULT_PALETTE[cid % len(DEFAULT_PALETTE)]),
        ]
        self._target_classes = classes   # 일괄 처리(3b)가 모든 이미지에 고정으로 재사용
        min_confidence = self._conf_slider.value() / 100.0
        min_pixel_size = self._min_px_spin.value()
        cache_key = (cid, min_confidence, min_pixel_size)
        cached = self._target_cache.get(self._image_path)
        try:
            if cached is not None and cached[0] == cache_key:
                # R-PERF-1: 캐시 적중 — refilter(디스크 재디코딩 포함)/
                # compute_blob_labels(cv2 connected-components) 재계산을 스킵한다.
                _, result, labels, stats = cached
            else:
                result = engine.refilter(
                    self._last_result.raw_class_map,
                    self._last_result.confidence_map,
                    self._image_path,
                    min_confidence=min_confidence,
                    min_pixel_size=min_pixel_size,
                    opacity=0.5,
                    classes=classes,
                )
                # 타겟 클래스가 (재)선택될 때마다 블랍 라벨맵을 새로 계산한다 — 라벨
                # id는 마스크에 종속적이라 클래스가 바뀌면 이전 삭제 이력은 무의미
                # (`ZoneCanvas.set_blob_data`가 삭제 이력도 함께 초기화).
                # class_map(threshold 적용 후)을 기준으로 삼아야 한다 — raw_class_map을
                # 쓰면 AI신뢰도/픽셀크기 threshold가 존 퍼센티지·블랍 계산에 전혀
                # 반영되지 않는 버그가 된다(오버레이 화면만 바뀌고 숫자는 그대로).
                target_mask = result.class_map == cid
                labels, stats, _ = compute_blob_labels(target_mask)
                self._target_cache[self._image_path] = (cache_key, result, labels, stats)
            self._last_result = result
            self._target_class_id = cid
            self._show_overlay_state()
            self._canvas.set_blob_data(labels, stats)
            self._canvas.set_highlight_rect(None)
            self._lbl_selected_blob.setText("")
            for action in (self._act_brush_draw, self._act_brush_erase, self._act_blob_delete):
                action.setEnabled(True)
            self._update_undo_button_state()   # set_blob_data가 undo 스택을 비웠으므로 즉시 반영
            self._recompute_zones()
        except Exception as exc:
            log.exception("존 분석 타겟 클래스 재필터링 실패")
            QMessageBox.critical(self, "재필터링 오류", str(exc))

    def _toggle_overlay(self) -> None:
        self._overlay_visible = not self._overlay_visible
        self._show_overlay_state()

    def _show_overlay_state(self) -> None:
        if self._overlay_visible and self._last_result is not None:
            self._canvas.set_pixmap(
                QPixmap.fromImage(self._last_result.overlay_image), preserve_view=True
            )
        elif self._original_pixmap is not None:
            self._canvas.set_pixmap(self._original_pixmap, preserve_view=True)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_F and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            self._toggle_overlay()
            event.accept()
            return
        super().keyPressEvent(event)

    # ── 슬롯 — 존(zone) 퍼센티지 계산/표시 (라운드 3) ────────────────────────

    def _ai_and_final_masks(self) -> tuple[np.ndarray | None, np.ndarray | None]:
        """(ai_mask, final_mask) — R3 Excel blob 내보내기가 둘을 구분해서 써야 해서
        `_current_target_mask()`를 두 단계로 분리한 리팩터링(기존 동작 100% 보존).

        `ai_mask`: 타겟 클래스 마스크에서 삭제된 블랍(라운드 4)을 배경 처리해 제외한
        "표시 마스크"(스펙 "블랍 삭제" 절) — 수동 스트로크 반영 *전*. 삭제 이력·
        라벨맵은 `ZoneCanvas`가 단일 출처로 들고 있다(`removed_blob_ids()`/
        `blob_labels()` — 원 선택/존 하이라이트와 동일한 getter 패턴, BUG-018/019
        재발 방지). `final_mask`: `ai_mask`에 수동 그리기/지우기까지 반영한 최종 마스크
        (기존 `_current_target_mask()`가 반환하던 것과 동일)."""
        if self._last_result is None or self._target_class_id is None:
            return None, None
        ai_mask = self._last_result.class_map == self._target_class_id
        removed = self._canvas.removed_blob_ids()
        labels = self._canvas.blob_labels()
        if removed and labels is not None:
            ai_mask = ai_mask & ~np.isin(labels, list(removed))
        final_mask = self._canvas.apply_manual_strokes(ai_mask)
        return ai_mask, final_mask

    def _current_target_mask(self) -> np.ndarray | None:
        return self._ai_and_final_masks()[1]

    def _on_blob_deleted(self, _label_id: int) -> None:
        # ZoneCanvas가 이미 removed_blob_ids에 반영·재도색까지 마친 뒤 emit한다
        # (라운드 3의 circles_changed와 동일하게, 여기선 재계산만 트리거).
        self._recompute_zones()

    # ── 슬롯 — 3-way 모드 배타(원편집/블랍삭제/브러시지우기, R3-3) ────────────
    # `QButtonGroup` 같은 새 추상화 없이 버튼 2개가 서로를 끄는 2줄짜리 상호배제로
    # 충분하다(스펙 판단 2, "원편집"은 둘 다 꺼진 기본 상태로 암묵적으로 표현).

    def _on_edit_tool_changed(self, action: QAction) -> None:
        if action is self._active_tool_action and action is not self._act_circle:
            # 요청5 — 활성 도구를 다시 클릭하면 토글 비활성화, 기본(원편집)으로 복귀.
            self._act_circle.setChecked(True)   # QActionGroup이 이전 액션을 자동으로 unchecked 처리
            action = self._act_circle
        self._active_tool_action = action
        mode = action.data()
        self._canvas.set_blob_delete_mode(mode == "blob_delete")
        if mode != "blob_delete":
            self._canvas.set_brush_draw_mode(mode == "brush_draw")
        if mode not in ("blob_delete", "brush_draw"):
            self._canvas.set_brush_erase_mode(mode == "brush_erase")
        if mode == "pan":
            self._canvas.set_pan_mode(True)
        self._erase_brush_spin.setEnabled(mode in ("brush_draw", "brush_erase"))

    # ── 슬롯 — Undo (R3-4) ────────────────────────────────────────────────────

    def _update_undo_button_state(self) -> None:
        self._act_undo.setEnabled(self._canvas.can_undo())

    # ── 스텝 인디케이터 (Artifact 조정 — 순수 표시용, 전환 강제 없음) ─────────

    def _compute_step_state(self) -> tuple[int, set[int]]:
        done = {
            1: self._ckpt_path is not None,
            2: self._image_path is not None or self._img_list.count() >= 1,
            3: len(self._canvas.get_circles()) >= 1,
            4: self._last_result is not None or bool(self._results),
        }
        done[5] = done[4]   # "진행상황"은 결과가 있으면 이미 끝난 것으로 간주(아래 러닝 중 예외)
        done[6] = self._step6_touched
        done[7] = self._result_viewed
        if self._worker is not None or self._batch_worker is not None or self._post_worker is not None:
            return 5, {k for k in (1, 2, 3, 4) if done[k]}   # 추론 진행 중엔 강제로 5번 강조
        completed = {k for k, v in done.items() if v}
        current = next((k for k in range(1, 8) if k not in completed), 7)
        return current, completed

    def _refresh_step_indicator(self) -> None:
        current, completed = self._compute_step_state()
        self._step_indicator.set_state(current, completed)

    def _mark_step6_touched(self) -> None:
        self._step6_touched = True
        self._refresh_step_indicator()

    def _compute_zone_percentages(self) -> list[tuple[str, float]]:
        """(존이름, 퍼센티지) 목록 — 원/추론결과/타겟클래스 중 하나라도 없으면 빈 리스트.

        `_recompute_zones()`(사이드 패널 표시)와 단일 이미지 Excel 내보내기(R3-1)가
        공유하는 헬퍼(스펙 판단 3, 순수 추출 — 동작 변화 없음).
        """
        circles_raw = self._canvas.circles_with_ids()   # 반지름 오름차순 (id, cx, cy, r, name)
        if not circles_raw or self._last_result is None or self._target_class_id is None:
            return []
        circles = [Circle(cid, cx, cy, r, name) for cid, cx, cy, r, name in circles_raw]
        h, w = self._last_result.raw_class_map.shape
        zones = zones_from_circles(circles, (h, w))
        target_mask = self._current_target_mask()
        return [(zone.name, zone_stats(zone.mask, target_mask)) for zone in zones]

    def _compute_zone_blob_rows(self) -> list[tuple[str, ZoneBlobStat]]:
        """R3 — 단일 이미지 Excel 내보내기용 (이미지파일명, ZoneBlobStat) 목록."""
        if self._image_path is None:
            return []
        circles_raw = self._canvas.circles_with_ids()
        if not circles_raw or self._last_result is None or self._target_class_id is None:
            return []
        circles = [Circle(cid, cx, cy, r, name) for cid, cx, cy, r, name in circles_raw]
        h, w = self._last_result.raw_class_map.shape
        zones = zones_from_circles(circles, (h, w))
        ai_mask, final_mask = self._ai_and_final_masks()
        if ai_mask is None:
            return []
        stats = zone_blob_stats(zones, ai_mask, final_mask, self._last_result.confidence_map)
        return [(self._image_path.name, s) for s in stats]

    def _make_zone_row_widget(self, zone_name: str, pct: float, max_px: int) -> QWidget:
        color = "#fbbf24" if pct >= 10.0 else "#34d399"   # 임계값은 시각 구분용 — 기존 판정 로직과 무관
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(6, 4, 6, 4)
        v.setSpacing(3)
        top = QHBoxLayout()
        lbl_name = QLabel(zone_name)
        lbl_pct = QLabel(f"{pct:.1f}%")
        lbl_pct.setStyleSheet(f"color:{color};font-weight:bold;")
        top.addWidget(lbl_name)
        top.addStretch()
        top.addWidget(lbl_pct)
        v.addLayout(top)
        # 색상바 + "최대 blob" 텍스트를 같은 행에 배치(디자인 확인 2026-10-03#4) —
        # 완전히 새 줄을 추가하면 우측 패널(폭 160~220px)의 세로 공간을 더 갉아먹는다.
        bar_row = QHBoxLayout()
        bar_row.setContentsMargins(0, 0, 0, 0)
        bar_row.setSpacing(6)
        bar_bg = QWidget()
        bar_bg.setFixedHeight(6)
        bar_bg.setStyleSheet("background:#1a1d23;border-radius:3px;")
        bar_layout = QHBoxLayout(bar_bg)
        bar_layout.setContentsMargins(0, 0, 0, 0)
        fill = QWidget()
        fill.setStyleSheet(f"background:{color};border-radius:3px;")
        bar_layout.addWidget(fill, stretch=max(1, round(min(pct, 100))))
        if pct < 100:
            spacer = QWidget()
            bar_layout.addWidget(spacer, stretch=max(1, round(100 - min(pct, 100))))
        bar_row.addWidget(bar_bg, stretch=1)
        lbl_max = QLabel(f"최대 {max_px:,}px")
        lbl_max.setStyleSheet("color:#9ca3af;font-size:9.5px;")
        bar_row.addWidget(lbl_max, alignment=Qt.AlignmentFlag.AlignVCenter)
        v.addLayout(bar_row)
        return w

    def _recompute_zones(self) -> None:
        # circles_changed 는 원 드래그 이동/반지름조절 중에도 mouseMoveEvent마다 emit된다
        # (BUG-018과 동일한 근본 원인) -- blockSignals 없이 clear()+재구성하면 QListWidget의
        # currentRow가 -1로 리셋되며 그 currentRowChanged(-1)이 _on_zone_row_selected를 타고
        # 캔버스 존 하이라이트까지 지워버린다. 재구성 전 현재 하이라이트를 읽어두고 재구성
        # 후 복원한다(_refresh_circle_list의 selected_id 복원과 동일 패턴).
        highlighted = self._canvas.highlighted_zone()
        self._zone_list.blockSignals(True)
        self._zone_list.clear()
        pct_rows = self._compute_zone_percentages()
        if not pct_rows:
            self._zone_list.blockSignals(False)
            self._canvas.set_highlighted_zone(None)
            return
        blob_rows = self._compute_zone_blob_rows()   # 기존 함수 재사용(R3 단일 이미지 Excel용)
        max_blobs = max_blob_pixels_by_zone(blob_rows) if blob_rows else {}
        image_name = self._image_path.name if self._image_path else ""
        for zone_name, pct in pct_rows:
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 48))
            max_px = max_blobs.get((image_name, zone_name), 0)
            self._zone_list.addItem(item)
            self._zone_list.setItemWidget(item, self._make_zone_row_widget(zone_name, pct, max_px))
        if highlighted is not None and 0 <= highlighted < self._zone_list.count():
            self._zone_list.setCurrentRow(highlighted)
        else:
            self._zone_list.setCurrentRow(-1)
            if highlighted is not None:
                self._canvas.set_highlighted_zone(None)   # 존 개수가 바뀌어 인덱스가 더 이상 유효하지 않음
        self._zone_list.blockSignals(False)

    def _on_canvas_zone_clicked(self, zone_index: int) -> None:
        self._zone_list.blockSignals(True)
        self._zone_list.setCurrentRow(zone_index)
        self._zone_list.blockSignals(False)

    def _on_zone_row_selected(self, row: int) -> None:
        self._canvas.set_highlighted_zone(row if row >= 0 else None)

    def _on_canvas_blob_clicked(self, x: int, y: int) -> None:
        ai_mask, final_mask = self._ai_and_final_masks()
        if final_mask is None or self._last_result is None:
            return
        h, w = final_mask.shape
        if not (0 <= y < h and 0 <= x < w) or not final_mask[y, x]:
            self._canvas.set_highlight_rect(None)
            self._lbl_selected_blob.setText("")
            return
        labels, _, _ = compute_blob_labels(final_mask)
        label_id = int(labels[y, x])
        if label_id == 0:
            self._canvas.set_highlight_rect(None)
            self._lbl_selected_blob.setText("")
            return
        circles = [Circle(cid, cx, cy, r, name) for cid, cx, cy, r, name in self._canvas.circles_with_ids()]
        zones = zones_from_circles(circles, (h, w))
        blob_rows = zone_blob_stats(zones, ai_mask, final_mask, self._last_result.confidence_map)
        blob = next((b for b in blob_rows if b.blob_id == label_id), None)
        if blob is None:
            self._canvas.set_highlight_rect(None)
            self._lbl_selected_blob.setText("")
            return
        self._canvas.highlight_blob_bbox(blob.bbox_x, blob.bbox_y, blob.bbox_w, blob.bbox_h)
        score_txt = f"{blob.ai_score * 100:.1f}%" if blob.ai_score is not None else "N/A(수동 편집)"
        self._lbl_selected_blob.setText(
            f"선택된 블랍 — 존: {blob.zone_name} · 면적 {blob.pixel_count}px · AI 점수 {score_txt}"
        )

    # ── 슬롯 — 단일 이미지 Excel 내보내기 (R3-1) ─────────────────────────────

    def _on_export_single(self) -> None:
        """일괄 처리를 거치지 않은 현재 화면(이미지 1장) 존 목록 — 배치 경로와
        동일한 `ZoneBatchResultDialog`를 재사용(2026-10-01 재설계, 라운드 F)해
        화면에 먼저 표로 보여준 뒤, 다이얼로그 안에서 Excel/클립보드로 내보낸다
        (신규 core 함수 없음, 단일/배치 양쪽이 같은 코드 경로를 타 중복 로직 제거)."""
        rows = self._compute_zone_percentages()
        if not rows or self._image_path is None:
            QMessageBox.information(
                self, "내보낼 결과 없음", "먼저 원을 정의하고 추론을 실행하세요."
            )
            return
        excel_rows = [(self._image_path.name, name, pct) for name, pct in rows]
        blob_rows = self._compute_zone_blob_rows()
        self._result_viewed = True
        self._refresh_step_indicator()
        ZoneBatchResultDialog(excel_rows, blob_rows, self).exec()

    def _on_view_all_results(self) -> None:
        """2026-10-03#8 — 이번 세션에서 추론을 실행한 모든 이미지를 모아서 본다.
        AI 마스크(InferenceResult)는 세션 메모리에만 있어 과거 세션/미추론 이미지는
        집계할 수 없다(재추론 자동 트리거 없음, YAGNI) — 그런 이미지는 제외하고
        안내 팝업 1회만 띄운다."""
        if self._target_class_id is None:
            QMessageBox.information(self, "준비 안 됨", "먼저 추론을 실행하고 타겟 클래스를 확정하세요.")
            return
        self._flush_state()   # 현재 이미지의 편집 상태를 사이드카에 먼저 반영(비교 대상 최신화)
        all_rows: list[tuple[str, str, float]] = []
        all_blob_rows: list[tuple[str, ZoneBlobStat]] = []
        skipped: list[str] = []
        for path in self._img_list.paths():
            result = self._results.get(path)
            if result is None:
                skipped.append(path.name)
                continue
            previous = zstate.load_state(path)
            # BUG-036: 사이드카의 "circles"는 (id, cx, cy, r, name) — ZoneCanvas.get_state()/
            # _ZoneBatchPostWorker.run()이 항상 id를 맨 앞에 저장한다(get_circles()와 다른
            # 스키마). id를 자르지 않고 그대로 넘기면 _compute_zone_rows()가 cx 자리에
            # id를, name 자리에 실제 반지름(float)을 받아 zone_name_sort_key()에서
            # TypeError로 크래시한다(QA.md BUG-036).
            circles = (self._canvas.get_circles() if path == self._image_path
                       else [c[1:] for c in (previous or {}).get("circles", [])])
            computed = _compute_zone_rows(path, result, self._target_class_id, circles, previous)
            if computed is None:
                continue
            rows, blob_rows = computed
            all_rows.extend(rows)
            all_blob_rows.extend(blob_rows)
        if not all_rows:
            QMessageBox.information(self, "결과 없음", "이번 세션에서 추론을 실행한 이미지가 없습니다.")
            return
        if skipped:
            QMessageBox.information(
                self, "일부 제외됨",
                f"이번 세션에서 추론하지 않은 {len(skipped)}장은 제외했습니다.\n"
                "(과거 세션 결과는 재추론 전까지 복원할 수 없습니다 — 먼저 추론을 실행하세요.)",
            )
        self._result_viewed = True
        self._refresh_step_indicator()
        ZoneBatchResultDialog(all_rows, all_blob_rows, self).exec()

    # ── 슬롯 — 원(circle) 자동 검출 (라운드 2) ──────────────────────────────

    def _on_auto_detect(self) -> None:
        if self._image_path is None:
            QMessageBox.warning(self, "이미지 없음", "이미지를 먼저 선택하세요.")
            return
        sensitivity = self._sensitivity_slider.value() / 100.0
        try:
            with Image.open(str(self._image_path)) as im:
                rgb = np.array(im.convert("RGB"))
            bgr = rgb[:, :, ::-1].copy()
            circles = detect_circles(bgr, sensitivity=sensitivity)
        except Exception as exc:
            log.exception(f"존 분석 원 자동 검출 실패 — image={self._image_path}")
            QMessageBox.critical(self, "자동 검출 오류", str(exc))
            return
        self._canvas.set_circles(circles)
        if not circles:
            QMessageBox.information(self, "검출 결과 없음", "원을 찾지 못했습니다. 민감도를 조절하거나 수동으로 추가하세요.")

    # ── 슬롯 — 레시피 팝업(7-3) ─────────────────────────────────────────────

    def _on_batch_mode_changed(self) -> None:
        """'장별 적용' 모드는 이미지마다 개별 자동검출을 쓰므로 레시피 버튼이
        의미가 없다(스펙 7-3 — 일괄 적용/일괄 적용 후 수정 모드에서만 표시)."""
        mode = self._mode_combo.currentData()
        self._btn_recipe.setVisible(mode in ("apply_all", "apply_all_edit"))

    def _on_open_recipe_dialog(self) -> None:
        if self._image_path is None or self._original_pixmap is None:
            QMessageBox.warning(self, "이미지 없음", "이미지를 먼저 선택하세요.")
            return
        existing = self._canvas.get_circles()
        if existing:
            reply = QMessageBox.question(
                self, "기존 원 발견", "기존 원을 레시피로 교체하시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        dialog = ZoneRecipeDialog(self._original_pixmap, self._image_size, self)
        if dialog.exec():
            scaled = scale_circles(
                dialog.result_circles(), dialog.result_ref_size(), self._image_size
            )
            self._canvas.set_circles(scaled)

    # ── 슬롯 — 원 목록 사이드 패널 <-> 캔버스 선택 동기화 ───────────────────

    def _refresh_circle_list(self) -> None:
        # circles_changed 는 클릭 선택 직후(드래그 없는 단순 선택 포함)에도 매번
        # 발생한다(mouseReleaseEvent 가 무조건 emit) -- clear() 로 리스트를 통째로
        # 재구성하면 QListWidget 의 currentRow 가 -1 로 리셋돼 캔버스 선택과 사이드
        # 패널 하이라이트가 어긋난다(BUG). 재구성 후 캔버스의 현재 선택을 그대로
        # 복원해 양방향 동기화를 유지한다.
        selected = self._canvas.selected_id()
        self._circle_list.blockSignals(True)
        self._circle_list.clear()
        selected_row = -1
        for i, (circle_id, cx, cy, r, name) in enumerate(self._canvas.circles_with_ids(), start=1):
            label = f"{name}  r={r:.1f}px  중심=({cx:.0f}, {cy:.0f})" if name else \
                f"원 {i}  r={r:.1f}px  중심=({cx:.0f}, {cy:.0f})"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, circle_id)
            self._circle_list.addItem(item)
            if circle_id == selected:
                selected_row = i - 1
        self._circle_list.setCurrentRow(selected_row)
        self._circle_list.blockSignals(False)

    def _on_canvas_circle_selected(self, circle_id) -> None:
        self._circle_list.blockSignals(True)
        for i in range(self._circle_list.count()):
            item = self._circle_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == circle_id:
                self._circle_list.setCurrentRow(i)
                break
        else:
            self._circle_list.setCurrentRow(-1)
        self._circle_list.blockSignals(False)

    def _on_list_row_selected(self, row: int) -> None:
        if row < 0:
            self._canvas.select_circle(None)
            return
        item = self._circle_list.item(row)
        circle_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        self._canvas.select_circle(circle_id)

    def _on_circle_list_context_menu(self, pos) -> None:
        """우클릭 "삭제" — 2번 항목에서 되돌린 상시 아이콘과 반대 패턴을 또
        추가하지 않도록 우클릭 메뉴만 둔다. 신규 삭제 로직 없이 기존
        `ZoneCanvas.remove_selected()`를 재사용(선택 동기화 후 호출)."""
        item = self._circle_list.itemAt(pos)
        if item is None:
            return
        circle_id = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        action = menu.addAction("삭제")
        if menu.exec(self._circle_list.viewport().mapToGlobal(pos)) == action:
            self._canvas.select_circle(circle_id)   # remove_selected()는 _selected_id 기준
            self._canvas.remove_selected()

    # ── 슬롯 — 배치(일괄) 처리 (스펙 판단 C-2, R-C 3b) ───────────────────────

    def _update_batch_button_state(self) -> None:
        """목록 2장 이상 + 기준 이미지에 원 1개 이상 정의돼야 활성화(스펙 그대로)."""
        has_circles = len(self._canvas.get_circles()) >= 1
        enough_images = self._img_list.count() > 1
        self._btn_batch.setEnabled(has_circles and enough_images)

    def _update_batch_button_label(self) -> None:
        n = len(self._img_list.selected_paths())
        self._btn_batch.setText(f"▶ 선택 이미지 일괄 처리 ({n}장)")

    def _confirm_existing_zones(self, count: int) -> str:
        box = QMessageBox(QMessageBox.Icon.Question, "기존 존 발견",
                          f"선택 이미지 중 {count}장에 기존 존이 있습니다.", parent=self)
        replace = box.addButton("기존 존을 대체하고 전체 적용", QMessageBox.ButtonRole.AcceptRole)
        missing_only = box.addButton("존 없는 이미지만 적용", QMessageBox.ButtonRole.ActionRole)
        box.addButton("취소", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is replace:
            return "replace"
        if box.clickedButton() is missing_only:
            return "missing_only"
        return "cancel"

    def _on_batch_process(self) -> None:
        if (self._last_result is None or self._target_class_id is None
                or self._target_classes is None or self._model is None
                or self._ckpt_path is None):
            QMessageBox.warning(
                self, "준비 안 됨",
                "먼저 기준 이미지에서 추론을 실행하고 타겟 클래스를 확정하세요.",
            )
            return
        circles_ref = self._canvas.get_circles()   # (cx, cy, r) 반지름 오름차순, 원본 좌표
        if not circles_ref:
            QMessageBox.warning(self, "원 없음", "기준 이미지에 원을 1개 이상 정의하세요.")
            return

        ref_w, ref_h = self._image_size
        mode = self._mode_combo.currentData()
        # apply_all·apply_all_edit 둘 다 기준 원을 스케일 적용, per_image만 개별 자동검출.
        sensitivity = self._sensitivity_slider.value() / 100.0
        min_confidence = self._conf_slider.value() / 100.0
        min_pixel_size = self._min_px_spin.value()
        target_classes = self._target_classes
        target_cid = self._target_class_id

        targets = self._img_list.selected_paths()
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._flush_state()
        existing = [p for p in targets if (zstate.load_state(p) or {}).get("circles")]
        if existing:
            choice = self._confirm_existing_zones(len(existing))
            if choice == "missing_only":
                existing_set = set(existing)
                targets = [p for p in targets if p not in existing_set]
            elif choice != "replace":
                return
        if not targets or not prompt_gpu_availability(self, "존 분석"):
            return

        cached = {p: self._results[p] for p in targets if p in self._results}
        if self._image_path in targets and self._last_result is not None:
            cached[self._image_path] = self._last_result
        self._btn_batch.setEnabled(False)
        # R-PERF-2: 존/블랍 후처리는 CUDA 워커(_batch_worker)가 아니라 전용 cv2
        # 워커(_post_worker)에서 수행 — 모드/기준 원/민감도/타겟 cid는 그 워커의
        # 생성자 인자로 직접 넘긴다(메인 스레드 self에 보관할 필요 없음).
        self._batch_rows = []
        self._batch_blob_rows = []
        self._batch_progress = QProgressDialog(
            "존 분석 일괄 처리 중…", "취소", 0, len(targets), self
        )
        self._batch_progress.setWindowTitle("일괄 처리 진행 중")
        self._batch_progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._batch_progress.setMinimumDuration(0)
        self._batch_elapsed = QElapsedTimer()
        self._batch_elapsed.start()
        self._batch_worker = _ZoneBatchWorker(
            self._model, targets, self._ckpt_path, cached,
            target_classes, min_confidence, min_pixel_size,
        )
        self._post_worker = _ZoneBatchPostWorker(
            mode, circles_ref, (ref_w, ref_h), sensitivity, target_cid,
        )
        self._batch_progress.canceled.connect(self._batch_worker.requestInterruption)
        self._batch_progress.canceled.connect(self._post_worker.requestInterruption)
        self._batch_worker.progress.connect(self._on_batch_progress)
        self._batch_worker.image_inferred.connect(self._on_batch_image_ready)
        # CUDA 워커가 끝나면 cv2 워커에 "더 들어올 항목 없음"을 알린다(큐에 남은
        # 항목은 계속 처리됨) — 최종 완료 판정은 _post_worker.finished 기준(아래).
        self._batch_worker.finished.connect(self._post_worker.close)
        self._post_worker.progress.connect(self._on_batch_progress)
        self._post_worker.row_computed.connect(self._on_batch_row_computed)
        self._post_worker.finished.connect(self._on_batch_finished)
        self._batch_worker.start()
        self._post_worker.start()
        self._refresh_step_indicator()

    def _on_batch_progress(self, path: Path, status: str, detail,
                           done: int, total: int) -> None:
        # `QProgressDialog.setValue()`는 내부적으로 `processEvents()`를 호출해
        # 이미 큐에 쌓인 `finished` 시그널을 재진입(reentrant)으로 먼저 처리할 수
        # 있다 — 그 핸들러(`_on_batch_finished`)가 `self._batch_progress`를
        # None으로 바꾸므로, 매번 `self._batch_progress`를 다시 읽지 말고 로컬
        # 변수 하나로 스냅샷해 이후 호출 전체에 일관되게 사용한다.
        dlg = self._batch_progress
        if dlg is not None:
            dlg.setMaximum(total)
            dlg.setValue(done)
            eta_txt = ""
            if done > 0:
                avg_ms = self._batch_elapsed.elapsed() / done
                remain_s = max(0, avg_ms * (total - done) / 1000.0)
                m, s = divmod(int(remain_s), 60)
                eta_txt = f"\n예상 남은 시간: 약 {m}분 {s}초" if m else f"\n예상 남은 시간: 약 {s}초"
            dlg.setLabelText(f"{done} / {total}  {path.name}{eta_txt}")
        if status == "processing":
            self._img_list.set_item_status(path, "processing")
        elif status == "error":
            log.error(f"존 분석 일괄 처리 실패 — {path}: {detail}")
            self._img_list.set_item_status(path, "done", badge="오류")
        else:
            self._img_list.set_item_status(path, "done", badge=detail)

    def _on_batch_image_ready(self, path: Path, result: InferenceResult,
                              done: int, total: int) -> None:
        """R-PERF-2: `_ZoneBatchWorker.image_inferred`의 가벼운 중계 슬롯 —
        무거운 cv2 후처리는 절대 여기서 하지 않고 `_post_worker`(전용 QThread)에
        큐잉만 하고 즉시 반환한다(메인 스레드 블로킹 없음)."""
        if self._post_worker is not None:
            self._post_worker.enqueue(path, result, done, total)

    def _on_batch_row_computed(self, path: Path, result: InferenceResult,
                               rows: list[tuple[str, str, float]],
                               blob_rows: list[tuple[str, ZoneBlobStat]],
                               done: int, total: int) -> None:
        """R-PERF-2: `_ZoneBatchPostWorker.row_computed` 수신 — 가벼운 dict/list
        누적 + Qt 위젯 호출만 담당(기존 `_on_batch_image_inferred()`에서 cv2 계산을
        떼어내고 남은 UI 갱신 부분). cv2 후처리 자체는 이미 `_post_worker`(cv2 전용
        QThread)에서 끝난 뒤이므로 메인 스레드에서 해도 안전하다."""
        self._results[path] = result   # BUG(2026-10-03#1): _on_inference_result()와 동일하게
                                        # 캐시해야 이미지 전환 시 우측 존 비율 패널이 복원된다.
        self._btn_view_all.setEnabled(bool(self._results))
        self._batch_rows.extend(rows)
        self._batch_blob_rows.extend(blob_rows)
        badge = f"{rows[-1][2]:.1f}%" if rows else None
        self._on_batch_progress(path, "done", badge, done, total)

    def _on_batch_finished(self) -> None:
        # R-PERF-2: 최종 완료 판정은 _post_worker.finished(cv2 큐가 다 빈 뒤) 기준
        # — CUDA 워커(_batch_worker)가 먼저 끝나도 cv2 후처리 큐에 항목이 남아있을
        # 수 있으므로, 더 늦게 끝나는 쪽을 기준으로 삼아야 _batch_rows/_batch_blob_rows가
        # 누락 없이 전부 채워진 상태로 결과 다이얼로그를 연다.
        if self._batch_progress is not None:
            self._batch_progress.close()
            self._batch_progress = None
        rows, blob_rows = self._batch_rows, self._batch_blob_rows
        self._batch_worker = None
        self._post_worker = None
        self._update_batch_button_state()
        self._refresh_step_indicator()
        if not rows:
            QMessageBox.information(self, "결과 없음", "처리된 결과가 없습니다.")
            return
        self._result_viewed = True
        self._refresh_step_indicator()
        ZoneBatchResultDialog(rows, blob_rows, self).exec()
