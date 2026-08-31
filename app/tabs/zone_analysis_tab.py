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
from pathlib import Path

import numpy as np
from PIL import Image
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileDialog,
    QMessageBox, QGroupBox, QPlainTextEdit, QTextEdit, QLineEdit, QComboBox,
    QSplitter, QSlider, QSpinBox, QListWidget, QListWidgetItem,
    QProgressDialog, QProgressBar, QToolBar,
)
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal, QSize
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
    export_zone_percentages_to_excel, apply_manual_strokes,
)
from app.core import zone_state_store as zstate
from app.core.logger import get_logger
from app.core.device_info import prompt_gpu_availability
from app.widgets.zone_canvas import ZoneCanvas
from app.widgets.inference_image_list import InferenceImageList
from app.widgets.zone_batch_result_dialog import ZoneBatchResultDialog
from app.widgets.icons import icon as svg_icon

log = get_logger(__name__)

# threshold 초기 고정값 — 설정 UI는 만들지 않음(YAGNI), 나중에 바꾸고 싶으면 이 상수만 수정
_DEFAULT_MIN_CONFIDENCE = 0.0
_DEFAULT_MIN_PIXEL_SIZE = 0
_PREVIEW_MAX_DIM = 2048


class _ZoneInferenceWorker(QThread):
    result_ready = pyqtSignal(object, object, int, int)
    failed = pyqtSignal(object, str)

    def __init__(self, model, paths: list[Path], checkpoint_path: Path,
                 mode: str) -> None:
        super().__init__()
        self._model = model
        self._paths = paths
        self._checkpoint_path = checkpoint_path
        self._mode = mode

    def run(self) -> None:
        total = len(self._paths)
        for done, path in enumerate(self._paths, 1):
            try:
                kwargs = dict(
                    model=self._model, image_path=path,
                    checkpoint_path=self._checkpoint_path,
                    opacity=0.5, classes=None,
                )
                result = (engine.run_sliding_window(**kwargs)
                          if self._mode == "sliding_window" else engine.run(**kwargs))
                self.result_ready.emit(path, result, done, total)
            except Exception as exc:
                self.failed.emit(path, str(exc))


class _ZoneBatchWorker(QThread):
    progress = pyqtSignal(object, str, object, int, int)
    completed = pyqtSignal(object)

    def __init__(self, model, paths: list[Path], checkpoint_path: Path,
                 cached_results: dict[Path, InferenceResult], mode: str,
                 circles_ref: list[tuple[float, float, float]],
                 ref_size: tuple[int, int], sensitivity: float,
                 classes: list[ClassDef], target_cid: int,
                 min_confidence: float, min_pixel_size: int) -> None:
        super().__init__()
        self._model = model
        self._paths = paths
        self._checkpoint_path = checkpoint_path
        self._cached_results = cached_results
        self._mode = mode
        self._circles_ref = circles_ref
        self._ref_size = ref_size
        self._sensitivity = sensitivity
        self._classes = classes
        self._target_cid = target_cid
        self._min_confidence = min_confidence
        self._min_pixel_size = min_pixel_size

    def run(self) -> None:
        rows: list[tuple[str, str, float]] = []
        prepared = None
        if any(path not in self._cached_results for path in self._paths):
            try:
                prepared = engine.prepare_inference(self._model, self._checkpoint_path)
            except Exception as exc:
                self.progress.emit(self._checkpoint_path, "error", str(exc), 0, len(self._paths))
                self.completed.emit(rows)
                return

        total = len(self._paths)
        for done, path in enumerate(self._paths, 1):
            if self.isInterruptionRequested():
                break
            self.progress.emit(path, "processing", None, done - 1, total)
            try:
                result = self._cached_results.get(path)
                if result is None:
                    result = engine.run(
                        model=self._model, image_path=path,
                        checkpoint_path=self._checkpoint_path, classes=self._classes,
                        min_confidence=self._min_confidence,
                        min_pixel_size=self._min_pixel_size, opacity=0.5,
                        prepared=prepared,
                    )
                h, w = result.raw_class_map.shape
                if self._mode == "per_image":
                    with Image.open(str(path)) as im:
                        rgb = np.array(im.convert("RGB"))
                    circles = detect_circles(rgb[:, :, ::-1].copy(), sensitivity=self._sensitivity)
                else:
                    circles = _scale_circles(self._circles_ref, self._ref_size, (w, h))
                if not circles:
                    self.progress.emit(path, "done", "원 없음", done, total)
                    continue

                target_mask = result.class_map == self._target_cid
                previous = zstate.load_state(path)
                if previous is not None:
                    if previous["removed_blob_ids"]:
                        labels, _ = compute_blob_labels(target_mask)
                        target_mask = target_mask & ~np.isin(labels, list(previous["removed_blob_ids"]))
                    target_mask = apply_manual_strokes(target_mask, previous["manual_strokes"])
                state = previous or {
                    "removed_blob_ids": set(), "erase_strokes": [], "manual_strokes": [],
                }
                state["circles"] = [
                    (idx, cx, cy, r) for idx, (cx, cy, r) in enumerate(circles)
                ]
                zstate.save_state(path, state)

                zones = zones_from_circles(
                    [Circle(idx, cx, cy, r) for idx, (cx, cy, r) in enumerate(circles)], (h, w)
                )
                percentages = [zone_stats(zone.mask, target_mask) for zone in zones]
                rows.extend((path.name, zone.name, pct) for zone, pct in zip(zones, percentages))
                badge = f"{percentages[-1]:.1f}%" if percentages else None
                self.progress.emit(path, "done", badge, done, total)
                del result, target_mask, zones
            except Exception as exc:
                log.exception(f"존 분석 일괄 처리 실패 — image={path}")
                self.progress.emit(path, "error", str(exc), done, total)
        self.completed.emit(rows)


def _rgb_to_qpixmap(rgb: np.ndarray) -> QPixmap:
    """플레인 RGB numpy 배열을 QPixmap으로 변환 — 추론 전 원본 미리보기 전용 (GH#14)."""
    rgb = np.ascontiguousarray(rgb)
    h, w, _ = rgb.shape
    qimg = QImage(rgb.data, w, h, w * 3, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qimg.copy())


def _scale_circles(
    circles: list[tuple[float, float, float]],
    from_size: tuple[int, int],
    to_size: tuple[int, int],
) -> list[tuple[float, float, float]]:
    """원 좌표를 기준 이미지 크기에서 대상 이미지 크기로 비례 스케일한다."""
    fw, fh = from_size
    tw, th = to_size
    if fw <= 0 or fh <= 0 or (fw, fh) == (tw, th):
        return list(circles)
    sx, sy = tw / fw, th / fh
    return [(cx * sx, cy * sy, r * (sx + sy) / 2) for cx, cy, r in circles]


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
        self._worker: _ZoneInferenceWorker | None = None
        self._batch_worker: _ZoneBatchWorker | None = None
        self._batch_progress: QProgressDialog | None = None
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
        self._build_ui()

    # ── UI 구성 ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # ── 상단 툴바 (승인된 목업 순서, Artifact 984ea900 — 이번 세션엔 Artifact
        #    도구가 없어 스펙 문서 "승인된 UI 레이아웃" 절 서술을 그대로 따름):
        #    체크포인트 상태+열기 / ▶ 추론 실행 / 타겟클래스 / AI신뢰도 / 픽셀 threshold /
        #    (민감도 — 자동검출의 파라미터라 바로 옆에 배치) / 자동검출 / 블랍삭제모드.
        #    (오프라인 원 검출 테스트는 2026-08-30 요청으로 삭제됨.) 이미지 열기는
        #    좌측 패널로 이동(C-1). ─
        # 두 줄로 분리(BUG-021 수정) — 한 줄에 다 욱여넣으면 최소폭이 1588px까지
        # 벌어져 MainWindow 코딩된 기본 크기(1280x800)를 조용히 무시하고 더 넓게
        # 뜸(main_window.py의 resize() 호출과 실제 동작이 어긋나는 버그였음).
        toolbar_row1 = QHBoxLayout()
        toolbar_row2 = QHBoxLayout()

        self._btn_ckpt = QPushButton("체크포인트 열기 (.pt)…")
        toolbar_row1.addWidget(self._btn_ckpt)
        self._lbl_ckpt = QLabel("선택된 체크포인트 없음")
        self._lbl_ckpt.setStyleSheet("color:#9ca3af;")
        toolbar_row1.addWidget(self._lbl_ckpt)

        self._btn_run = QPushButton("▶  추론 실행")
        self._btn_run.setStyleSheet("font-weight:bold; padding:4px 12px;")
        toolbar_row1.addWidget(self._btn_run)

        self._infer_mode = QComboBox()
        self._infer_mode.addItem("resize", "resize")
        self._infer_mode.addItem("sliding window", "sliding_window")
        self._infer_mode.setCurrentIndex(self._infer_mode.findData("sliding_window"))
        self._infer_mode.setToolTip("패치 학습 모델은 sliding window를 선택하세요")
        toolbar_row1.addWidget(self._infer_mode)

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
        toolbar_row2.addWidget(self._edit_toolbar)

        toolbar_row2.addStretch()
        root.addLayout(toolbar_row1)
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
        open_row = QHBoxLayout()
        self._btn_image = QPushButton("이미지 열기…")
        self._btn_folder = QPushButton("폴더 열기…")
        open_row.addWidget(self._btn_image)
        open_row.addWidget(self._btn_folder)
        left_layout.addLayout(open_row)
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

        # 중앙 — 캔버스 (가능한 한 크게)
        self._canvas = ZoneCanvas()
        splitter.addWidget(self._canvas)

        # 우측 — 원/존 목록 (R2/R3 로직 그대로, 컨테이너 위치만 이동)
        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(4, 0, 0, 0)
        side_layout.addWidget(QLabel("검출된 원 (반지름 오름차순)"))
        self._circle_list = QListWidget()
        side_layout.addWidget(self._circle_list, stretch=1)
        side_layout.addWidget(QLabel("존별 타겟 클래스 비율 (%)"))
        self._zone_list = QListWidget()
        self._zone_list.setToolTip("클릭하면 캔버스에서 해당 존이 하이라이트됩니다")
        side_layout.addWidget(self._zone_list, stretch=1)
        self._btn_export_single = QPushButton("Excel로 내보내기")
        self._btn_export_single.setToolTip("현재 화면에 표시된 존 목록(이미지 1장)을 xlsx로 저장합니다")
        side_layout.addWidget(self._btn_export_single)
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

    # ── 슬롯 — 이미지 / 체크포인트 선택 (C-1) ────────────────────────────────

    def _on_select_image(self) -> None:
        """다중 파일 선택 — inference_tab._on_select_file과 동일 패턴."""
        paths, _ = QFileDialog.getOpenFileNames(
            self, "이미지 선택", "",
            "Images (*.jpg *.jpeg *.png *.bmp *.tiff *.tif)"
        )
        if not paths:
            return
        self._img_list.clear_status()
        self._img_list.load_files([Path(p) for p in paths])
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
        self._img_list.clear_status()
        self._img_list.load_folder(Path(folder))
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
        except Exception:
            self._image_size = (0, 0)
            self._original_pixmap = None
            self._canvas.set_image_size(*self._image_size)
            self._canvas.clear()
            for action in self._tool_group.actions():
                action.setEnabled(False)
        self._btn_detect.setEnabled(False)   # 새 이미지는 아직 추론 전 -- 원 자동검출은 불가
        self._canvas.set_blob_data(None, None)
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
        self._ckpt_path = Path(path)
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

        paths = self._img_list.paths() or [self._image_path]
        self._results.clear()
        self._btn_run.setEnabled(False)
        self._btn_run.setText("추론 중…")
        self._infer_progress.setRange(0, len(paths))
        self._infer_progress.setValue(0)
        self._infer_progress.show()
        self._worker = _ZoneInferenceWorker(
            self._model, paths, self._ckpt_path, self._infer_mode.currentData()
        )
        self._worker.result_ready.connect(self._on_inference_result)
        self._worker.failed.connect(
            lambda path, message: log.error(f"존 분석 추론 실패 — {path}: {message}")
        )
        self._worker.finished.connect(self._on_inference_finished)
        self._worker.start()

    def _on_inference_result(self, path: Path, result: InferenceResult,
                             done: int, total: int) -> None:
        self._results[path] = result
        self._infer_progress.setValue(done)
        self._infer_progress.setFormat(f"{done} / {total}")
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

    # ── 타겟(녹) 클래스 즉석 구성 (판단 4) ────────────────────────────────────

    def _setup_target_classes(self, result: InferenceResult) -> None:
        ids = sorted(int(i) for i in set(result.raw_class_map.ravel().tolist()) if i != 0)
        self._detected_ids = ids
        self._btn_detect.setEnabled(True)   # 추론 완료 -- 캔버스에 배경 pixmap이 생겨 원이 보임

        self._target_name_edit.hide()
        self._target_combo.hide()

        if not ids:
            self._lbl_target_info.setText("배경 외 클래스가 검출되지 않았습니다.")
            self._show_overlay_state()
            self._target_class_id = None
            self._canvas.set_blob_data(None, None)
            self._act_circle.setChecked(True)
            self._on_edit_tool_changed(self._act_circle)
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
        try:
            result = engine.refilter(
                self._last_result.raw_class_map,
                self._last_result.confidence_map,
                self._image_path,
                min_confidence=self._conf_slider.value() / 100.0,
                min_pixel_size=self._min_px_spin.value(),
                opacity=0.5,
                classes=classes,
            )
            self._last_result = result
            self._target_class_id = cid
            self._show_overlay_state()
            # 타겟 클래스가 (재)선택될 때마다 블랍 라벨맵을 새로 계산한다 — 라벨
            # id는 마스크에 종속적이라 클래스가 바뀌면 이전 삭제 이력은 무의미
            # (`ZoneCanvas.set_blob_data`가 삭제 이력도 함께 초기화).
            # class_map(threshold 적용 후)을 기준으로 삼아야 한다 — raw_class_map을
            # 쓰면 AI신뢰도/픽셀크기 threshold가 존 퍼센티지·블랍 계산에 전혀
            # 반영되지 않는 버그가 된다(오버레이 화면만 바뀌고 숫자는 그대로).
            target_mask = result.class_map == cid
            labels, stats = compute_blob_labels(target_mask)
            self._canvas.set_blob_data(labels, stats)
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
            self._canvas.set_pixmap(self._last_result.overlay_pixmap, preserve_view=True)
        elif self._original_pixmap is not None:
            self._canvas.set_pixmap(self._original_pixmap, preserve_view=True)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_F and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            self._toggle_overlay()
            event.accept()
            return
        super().keyPressEvent(event)

    # ── 슬롯 — 존(zone) 퍼센티지 계산/표시 (라운드 3) ────────────────────────

    def _current_target_mask(self) -> np.ndarray | None:
        """타겟 클래스 마스크에서 삭제된 블랍(라운드 4)을 배경 처리해 제외한
        "표시 마스크"(스펙 "블랍 삭제" 절). 삭제 이력·라벨맵은 `ZoneCanvas`가
        단일 출처로 들고 있다(`removed_blob_ids()`/`blob_labels()` — 원 선택/존
        하이라이트와 동일한 getter 패턴, BUG-018/019 재발 방지)."""
        if self._last_result is None or self._target_class_id is None:
            return None
        mask = self._last_result.class_map == self._target_class_id
        removed = self._canvas.removed_blob_ids()
        labels = self._canvas.blob_labels()
        if removed and labels is not None:
            mask = mask & ~np.isin(labels, list(removed))
        return self._canvas.apply_manual_strokes(mask)

    def _on_blob_deleted(self, _label_id: int) -> None:
        # ZoneCanvas가 이미 removed_blob_ids에 반영·재도색까지 마친 뒤 emit한다
        # (라운드 3의 circles_changed와 동일하게, 여기선 재계산만 트리거).
        self._recompute_zones()

    # ── 슬롯 — 3-way 모드 배타(원편집/블랍삭제/브러시지우기, R3-3) ────────────
    # `QButtonGroup` 같은 새 추상화 없이 버튼 2개가 서로를 끄는 2줄짜리 상호배제로
    # 충분하다(스펙 판단 2, "원편집"은 둘 다 꺼진 기본 상태로 암묵적으로 표현).

    def _on_edit_tool_changed(self, action: QAction) -> None:
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

    def _compute_zone_percentages(self) -> list[tuple[str, float]]:
        """(존이름, 퍼센티지) 목록 — 원/추론결과/타겟클래스 중 하나라도 없으면 빈 리스트.

        `_recompute_zones()`(사이드 패널 표시)와 단일 이미지 Excel 내보내기(R3-1)가
        공유하는 헬퍼(스펙 판단 3, 순수 추출 — 동작 변화 없음).
        """
        circles_raw = self._canvas.circles_with_ids()   # 반지름 오름차순 (id, cx, cy, r)
        if not circles_raw or self._last_result is None or self._target_class_id is None:
            return []
        circles = [Circle(cid, cx, cy, r) for cid, cx, cy, r in circles_raw]
        h, w = self._last_result.raw_class_map.shape
        zones = zones_from_circles(circles, (h, w))
        target_mask = self._current_target_mask()
        return [(zone.name, zone_stats(zone.mask, target_mask)) for zone in zones]

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
        for zone_name, pct in pct_rows:
            self._zone_list.addItem(f"{zone_name}  —  {pct:.2f}%")
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

    # ── 슬롯 — 단일 이미지 Excel 내보내기 (R3-1) ─────────────────────────────

    def _on_export_single(self) -> None:
        """일괄 처리를 거치지 않은 현재 화면(이미지 1장) 존 목록을 xlsx로 저장.

        신규 core 함수 없음 — `export_zone_percentages_to_excel()`(R-C 3c에서
        일괄 처리용으로 이미 신설됨, 범용 long rows를 받음)을 그대로 재사용한다.
        """
        rows = self._compute_zone_percentages()
        if not rows or self._image_path is None:
            QMessageBox.information(
                self, "내보낼 결과 없음", "먼저 원을 정의하고 추론을 실행하세요."
            )
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Excel로 내보내기", "zones.xlsx", "Excel (*.xlsx)"
        )
        if not path:
            return
        excel_rows = [(self._image_path.name, name, pct) for name, pct in rows]
        try:
            export_zone_percentages_to_excel(excel_rows, Path(path))
        except Exception as exc:
            log.exception("존 분석 단일 이미지 Excel 내보내기 실패")
            QMessageBox.critical(self, "내보내기 오류", str(exc))
            return
        QMessageBox.information(
            self, "내보내기 완료", f"{len(excel_rows)}개 행을 내보냈습니다."
        )

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
        for i, (circle_id, cx, cy, r) in enumerate(self._canvas.circles_with_ids(), start=1):
            item = QListWidgetItem(f"원 {i}  r={r:.1f}px  중심=({cx:.0f}, {cy:.0f})")
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
        self._batch_progress = QProgressDialog(
            "존 분석 일괄 처리 중…", "취소", 0, len(targets), self
        )
        self._batch_progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._batch_progress.setMinimumDuration(0)
        self._batch_worker = _ZoneBatchWorker(
            self._model, targets, self._ckpt_path, cached, mode, circles_ref,
            (ref_w, ref_h), sensitivity, target_classes, target_cid,
            min_confidence, min_pixel_size,
        )
        self._batch_progress.canceled.connect(self._batch_worker.requestInterruption)
        self._batch_worker.progress.connect(self._on_batch_progress)
        self._batch_worker.completed.connect(self._on_batch_completed)
        self._batch_worker.finished.connect(self._on_batch_finished)
        self._batch_worker.start()

    def _on_batch_progress(self, path: Path, status: str, detail,
                           done: int, total: int) -> None:
        if self._batch_progress is not None:
            self._batch_progress.setMaximum(total)
            self._batch_progress.setValue(done)
            self._batch_progress.setLabelText(f"{done} / {total}  {path.name}")
        if status == "processing":
            self._img_list.set_item_status(path, "processing")
        elif status == "error":
            log.error(f"존 분석 일괄 처리 실패 — {path}: {detail}")
            self._img_list.set_item_status(path, "done", badge="오류")
        else:
            self._img_list.set_item_status(path, "done", badge=detail)

    def _on_batch_completed(self, rows: list[tuple[str, str, float]]) -> None:
        if self._batch_progress is not None:
            self._batch_progress.close()
            self._batch_progress = None
        if not rows:
            QMessageBox.information(self, "결과 없음", "처리된 결과가 없습니다.")
            return
        ZoneBatchResultDialog(rows, self).exec()

    def _on_batch_finished(self) -> None:
        self._batch_worker = None
        self._update_batch_button_state()
