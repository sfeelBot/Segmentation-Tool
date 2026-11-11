"""R 분석(R Analysis) 탭 — 배터리 캡 녹 검사, 셀(cell) 단위 면적비 판정.

스펙: docs/specs/r-analysis-tab-2026-10-26.md. Zone 분석 탭과 나란히 쓰이는
완전 독립 도구(프로젝트 시스템 미사용, 이미지/세션 파일을 직접 연다).

이 파일은 이미 구현된 7개 부품(core 2 + widgets 5)을 조립하는 역할만 한다 —
비즈니스 로직(검출/ratio/판정)은 `app/core/r_analysis_metrics.py`에 있고,
이 탭은 그 결과를 Qt 위젯과 세션 JSON에 연결하는 접착 코드다.

핵심 설계 결정:
  - ROI는 전역 1개 + 이미지별 override(선택) — 둘 다 캔버스에 "지금 그려진
    사각형"을 `RSettingsPanel`의 버튼 클릭으로 커밋할 때만 세션에 저장된다
    (드래그 중 매 프레임 저장하지 않음, 요구사항 3).
  - 셀 R·판정은 `cell_rollup()`으로 셀당 1번만 계산 — 이미지별 개별 판정
    배지는 만들지 않는다(요구사항 6, 가장 중요한 설계 원칙).
  - 검출 3단계(현재 이미지/선택 셀/전체 셀)는 셀 1장 단위 연산을 재사용하되,
    여러 장을 처리하는 2·3단계만 `_RDetectWorker`(QThread)로 넘긴다.
"""
from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

import cv2
import numpy as np
from PyQt6.QtCore import QEvent, QSize, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QIcon, QImage, QPixmap
from PyQt6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel, QListWidget,
    QListWidgetItem, QMessageBox, QProgressDialog, QPushButton, QSlider,
    QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QToolBar, QVBoxLayout,
    QWidget,
)

from app.core import r_cell_store as r_store
from app.core.i18n import t
from app.core.logger import get_logger
from app.core.r_analysis_metrics import (
    apply_edits, cell_rollup, contour_area, detect_contour_mask, imread_unicode,
)
from app.widgets.brush_toolbar import BrushToolbar, TOOL_BRUSH, TOOL_ERASER, TOOL_PAN
from app.widgets.icons import icon as svg_icon
from app.widgets.r_batch_result_dialog import RBatchResultDialog
from app.widgets.r_cell_panel import RCellPanel
from app.widgets.r_roi_canvas import RRoiCanvas
from app.widgets.r_settings_panel import RSettingsPanel
from app.widgets.r_step_indicator import RStepIndicator

log = get_logger(__name__)

_TOOL_ROI = "roi"   # ROI 편집 — 호스트 로컬 도구, BrushToolbar 클러스터 소속 아님

_THUMB_PX = 56

_BADGE_PASS = (
    "background:#0d2318;border:2px solid #10b981;border-radius:6px;"
    "color:#34d399;font-weight:bold;font-size:14px;"
)
_BADGE_FAIL = (
    "background:#2a1215;border:2px solid #ef4444;border-radius:6px;"
    "color:#f87171;font-weight:bold;font-size:14px;"
)
_BADGE_NONE = (
    "background:#1a1d23;border:1px solid #4b5563;border-radius:6px;"
    "color:#9ca3af;font-weight:bold;font-size:13px;"
)

_IMAGE_CACHE_SIZE = 8   # 이미지 전환/재방문 시 cv2.imread 중복 디코드를 줄이는 LRU 상한
                        # (zone_analysis_tab의 R-PERF-1과 동일한 OrderedDict LRU 관례)


def _bgr_to_qpixmap(img: np.ndarray) -> QPixmap:
    """cv2(BGR) numpy 배열을 QPixmap으로 변환 — RGB 재정렬 없이 Format_BGR888을
    그대로 써서 `cv2.imread()`로 읽은 같은 파일을 `QPixmap()`으로 또 디코드하지
    않기 위함(P1 성능, 대형 이미지에서 전환당 이중 디코드 비용 제거)."""
    img = np.ascontiguousarray(img)
    h, w = img.shape[:2]
    qimg = QImage(img.data, w, h, img.strides[0], QImage.Format.Format_BGR888)
    return QPixmap.fromImage(qimg.copy())


def _default_session() -> dict:
    return {
        "version": 1, "cells": {}, "global_roi": None,
        "threshold": 128, "denominator": 0.0, "spec_lower": 0.0, "spec_upper": 0.0,
        "auto_detect": False,
    }


def _default_image_data() -> dict:
    return {"roi_override": None, "manual_strokes": [], "area": 0, "removed_blob_regions": []}


class _RDetectWorker(QThread):
    """여러 이미지를 cv2로 순차 검출하는 단일 워커 — 스펙 명시대로 Zone 탭의
    2-워커 CUDA 분리 구조는 불필요(여기엔 CUDA 추론이 없음, AI 모델 아님).
    run() 안에서만 cv2/numpy 연산을 하고 결과는 Signal로만 내보낸다."""

    image_done = pyqtSignal(str, int)     # path, area
    progress = pyqtSignal(int, int)        # done, total

    def __init__(
        self,
        # (path, roi, manual_strokes, removed_blob_regions) — 영역은 (x, y, w, h[, n])
        jobs: list[tuple[Path, tuple[int, int, int, int] | None, list, list]],
        threshold: int,
        auto_detect: bool,
    ) -> None:
        super().__init__()
        self._jobs = jobs
        self._threshold = threshold
        self._auto_detect = auto_detect

    def run(self) -> None:
        total = len(self._jobs)
        for done, (path, roi, manual_strokes, removed_regions) in enumerate(self._jobs, 1):
            if self.isInterruptionRequested():
                break
            try:
                img = imread_unicode(path)
                if img is not None:
                    # _compute_detected_mask()와 동일한 분기 — 자동검출 꺼짐 또는
                    # ROI 미지정이면 빈 마스크로 시작해 브러시 스트로크만으로 면적을 낸다.
                    if self._auto_detect and roi is not None:
                        mask = detect_contour_mask(img, roi, self._threshold)
                    else:
                        mask = np.zeros(img.shape[:2], dtype=bool)
                    # 캔버스 effective_mask()와 같은 함수 — 따로 계산하면 화면 면적과
                    # 일괄 검출 면적이 어긋난다(BUG-054).
                    mask = apply_edits(mask, manual_strokes, removed_regions)
                    self.image_done.emit(str(path), contour_area(mask))
            except Exception:
                log.exception(f"R 분석 일괄 검출 실패 — image={path}")
            self.progress.emit(done, total)


class RAnalysisTab(QWidget):
    """배터리 캡 녹 검사 — 셀(여러 이미지 묶음) 단위 면적비 검사 도구."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._session: dict = _default_session()
        self._session_path: Path | None = None
        self._cells: dict[str, list[Path]] = {}
        self._image_data_map: dict[str, dict] = {}
        self._current_cell: str | None = None
        self._current_image_path: Path | None = None
        self._detect_worker: _RDetectWorker | None = None
        self._progress: QProgressDialog | None = None
        self._image_cache: OrderedDict[str, np.ndarray] = OrderedDict()   # P1 성능(LRU)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(500)
        self._save_timer.timeout.connect(self._do_save)

        self._build_ui()
        self._refresh_settings_summary()
        self._refresh_right_panel()
        self._refresh_step_indicator()
        self._sync_detect_buttons_enabled()

    # ── UI 구성 ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        self._step_indicator = RStepIndicator()
        root.addWidget(self._step_indicator)

        session_row = QHBoxLayout()
        session_row.addWidget(QLabel(t("r.session_file_label")))
        self._lbl_session_path = QLabel(t("r.session_unset"))
        self._lbl_session_path.setStyleSheet("color:#9ca3af;font-size:11px;")
        session_row.addWidget(self._lbl_session_path, stretch=1)
        self._btn_session = QPushButton(t("r.btn_session"))
        self._btn_session.clicked.connect(self._on_open_session)
        session_row.addWidget(self._btn_session)
        root.addLayout(session_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_center_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 1)
        splitter.setSizes([260, 780, 240])
        root.addWidget(splitter, stretch=1)

        self._settings_dialog = RSettingsPanel(self)
        self._settings_dialog.settings_changed.connect(self._on_settings_changed)
        self._settings_dialog.roi_global_requested.connect(self._on_roi_global_requested)
        self._settings_dialog.roi_override_requested.connect(self._on_roi_override_requested)

    def _build_left_panel(self) -> QWidget:
        left = QWidget()
        layout = QVBoxLayout(left)
        layout.setContentsMargins(0, 0, 4, 0)

        self._cell_panel = RCellPanel()
        self._cell_panel.cell_selected.connect(self._on_cell_selected)
        self._cell_panel.cells_changed.connect(self._on_cells_changed)
        self._cell_panel.image_selected.connect(lambda p: self._set_current_image(Path(p)))
        layout.addWidget(self._cell_panel, stretch=1)

        card = QFrame()
        card.setStyleSheet("background:#1f2329;border:1px solid #374151;border-radius:8px;")
        card_layout = QVBoxLayout(card)
        card_layout.addWidget(QLabel(t("r.settings_summary_title")))
        self._lbl_settings_summary = QLabel("")
        self._lbl_settings_summary.setWordWrap(True)
        self._lbl_settings_summary.setStyleSheet("color:#9ca3af;font-size:11px;")
        card_layout.addWidget(self._lbl_settings_summary)
        layout.addWidget(card)

        btn_settings = QPushButton(t("r.btn_settings"))
        btn_settings.clicked.connect(lambda: self._settings_dialog.exec())
        layout.addWidget(btn_settings)

        left.setMinimumWidth(200)
        left.setMaximumWidth(340)
        return left

    def _build_center_panel(self) -> QWidget:
        center = QWidget()
        layout = QVBoxLayout(center)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._canvas = RRoiCanvas()
        self._canvas.installEventFilter(self)
        self._canvas.roi_changed.connect(self._update_undo_button_state)
        self._canvas.erase_changed.connect(self._update_undo_button_state)
        self._canvas.erase_changed.connect(self._on_canvas_edited)
        self._canvas.blob_deleted.connect(self._update_undo_button_state)
        self._canvas.blob_deleted.connect(lambda _id: self._on_canvas_edited())
        layout.addWidget(self._canvas, stretch=1)

        self._thumb_strip = QListWidget()
        self._thumb_strip.setViewMode(QListWidget.ViewMode.IconMode)
        self._thumb_strip.setFlow(QListWidget.Flow.LeftToRight)
        self._thumb_strip.setWrapping(False)
        self._thumb_strip.setIconSize(QSize(_THUMB_PX, _THUMB_PX))
        self._thumb_strip.setFixedHeight(_THUMB_PX + 28)
        self._thumb_strip.itemClicked.connect(
            lambda item: self._set_current_image(item.data(Qt.ItemDataRole.UserRole))
        )
        layout.addWidget(self._thumb_strip)

        self._build_edit_cluster()
        self._build_run_cluster()
        self._build_nav_cluster()
        self._build_opacity_cluster()
        # 세 클러스터(편집도구/실행버튼/탐색)의 최소폭 합만큼은 캔버스가 항상 확보하도록
        # 강제한다 — _position_overlays()의 42%/46%/잔여폭 분배는 이 폭 안에서만 동작을
        # 보장하고, 그보다 좁아지면 클러스터가 1px까지 눌려 사실상 클릭 불가능해진다
        # (BUG-050 재점검, 2026-11-09 — Zone 탭 BUG-048과 동일 패턴: 캔버스 자체에
        # setMinimumWidth를 둬 애초에 그 구간에 들어가지 못하게 함).
        min_canvas_w = (
            self._edit_cluster.minimumSizeHint().width()
            + self._run_cluster.minimumSizeHint().width()
            + self._nav_cluster.minimumSizeHint().width()
            + 4 * 8
        )
        self._canvas.setMinimumWidth(min_canvas_w)
        QTimer.singleShot(0, self._position_overlays)
        return center

    def _build_edit_cluster(self) -> None:
        cluster = QFrame(self._canvas)
        cluster.setStyleSheet(
            "background:rgba(31,35,41,215);border:1px solid #374151;border-radius:6px;"
        )
        layout = QHBoxLayout(cluster)
        layout.setContentsMargins(6, 4, 6, 4)

        toolbar = QToolBar()
        toolbar.setIconSize(QSize(18, 18))
        toolbar.setStyleSheet(
            "QToolBar QToolButton:checked { background:#1e3a5f; border:1px solid #60a5fa; color:#60a5fa; }"
        )

        # 공유 클러스터(브러시그리기/브러시지우기/이동/브러시크기/undo)는
        # app/widgets/brush_toolbar.py 의 BrushToolbar(show_delete_region=False)에서
        # 가져온다 — ROI 편집만 호스트 로컬로 유지(R분석 전용 도구, 영역삭제 개념
        # 없음). 라벨링/Zone 탭과 동일한 "양방향 set_tool()/tool_changed 수동
        # 동기화" 패턴(QActionGroup 대신).
        self._act_roi = QAction(svg_icon("tool_rect"), "", self)
        self._act_roi.setToolTip(t("r.tool_roi_tip"))
        self._act_roi.setCheckable(True)
        self._act_roi.setChecked(True)
        self._act_roi.triggered.connect(lambda: self._set_tool(_TOOL_ROI))

        self._brush_tools = BrushToolbar(toolbar, show_delete_region=False)
        self._brush_tools.act_brush.setToolTip(t("r.tool_brush_tip"))
        self._brush_tools.act_eraser.setToolTip(t("r.tool_eraser_tip"))
        self._brush_tools.act_pan.setToolTip(t("r.tool_pan_tip"))
        self._brush_tools.spin_brush_size.setValue(30)
        self._brush_tools.spin_brush_size.setSuffix(" px")
        self._brush_tools.spin_brush_size.setFixedWidth(80)

        toolbar.addAction(self._act_roi)
        toolbar.addAction(self._brush_tools.act_brush)
        toolbar.addAction(self._brush_tools.act_eraser)
        toolbar.addAction(self._brush_tools.act_pan)
        toolbar.addSeparator()
        self._act_undo = self._brush_tools.act_undo
        self._act_undo.setToolTip(t("r.undo_tip"))
        self._act_undo.setEnabled(False)
        toolbar.addAction(self._act_undo)

        self._act_overlay_visible = QAction(svg_icon("eye"), "", self)
        self._act_overlay_visible.setCheckable(True)
        self._act_overlay_visible.setChecked(True)
        self._act_overlay_visible.setToolTip(t("r.overlay_visible_tip") + " [F]")
        self._act_overlay_visible.toggled.connect(self._canvas.set_mask_overlay_visible)
        self._canvas.overlay_toggle_requested.connect(self._act_overlay_visible.toggle)
        toolbar.addAction(self._act_overlay_visible)

        self._active_tool: str = _TOOL_ROI
        layout.addWidget(toolbar)

        layout.addWidget(QLabel(t("r.brush_label")))
        layout.addWidget(self._brush_tools.spin_brush_size)

        self._brush_tools.tool_changed.connect(self._set_tool)
        self._brush_tools.undo_requested.connect(self._canvas.undo)
        self._brush_tools.spin_brush_size.valueChanged.connect(self._canvas.set_erase_brush_size)

        self._edit_cluster = cluster

    def _build_run_cluster(self) -> None:
        cluster = QFrame(self._canvas)
        cluster.setStyleSheet(
            "background:rgba(31,35,41,215);border:1px solid #374151;border-radius:6px;"
        )
        layout = QHBoxLayout(cluster)
        layout.setContentsMargins(6, 4, 6, 4)

        btn_current = QPushButton(t("r.btn_detect_current"))
        btn_current.clicked.connect(self._on_detect_current)
        layout.addWidget(btn_current)
        self._btn_detect_current = btn_current

        btn_cell = QPushButton(t("r.btn_detect_cell"))
        btn_cell.clicked.connect(self._on_detect_cell)
        layout.addWidget(btn_cell)
        self._btn_detect_cell = btn_cell

        btn_all = QPushButton(t("r.btn_detect_all"))
        btn_all.setStyleSheet(
            "background:#1e3a5f;border:1.5px solid #60a5fa;border-radius:5px;"
            "padding:4px 10px;color:#93c5fd;font-weight:bold;"
        )
        btn_all.clicked.connect(self._on_detect_all)
        layout.addWidget(btn_all)
        self._btn_detect_all = btn_all

        self._run_cluster = cluster

    def _build_nav_cluster(self) -> None:
        cluster = QFrame(self._canvas)
        cluster.setStyleSheet(
            "background:rgba(31,35,41,215);border:1px solid #374151;border-radius:6px;"
        )
        layout = QHBoxLayout(cluster)
        layout.setContentsMargins(6, 4, 6, 4)

        btn_prev = QPushButton("◀")
        btn_prev.setFixedWidth(28)
        btn_prev.clicked.connect(lambda: self._navigate(-1))
        layout.addWidget(btn_prev)

        self._lbl_nav = QLabel("- (0/0)")
        self._lbl_nav.setMinimumWidth(140)
        self._lbl_nav.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._lbl_nav)

        btn_next = QPushButton("▶")
        btn_next.setFixedWidth(28)
        btn_next.clicked.connect(lambda: self._navigate(1))
        layout.addWidget(btn_next)

        self._nav_cluster = cluster

    def _build_opacity_cluster(self) -> None:
        cluster = QFrame(self._canvas)
        cluster.setStyleSheet(
            "background:rgba(31,35,41,215);border:1px solid #374151;border-radius:6px;"
        )
        layout = QHBoxLayout(cluster)
        layout.setContentsMargins(6, 4, 6, 4)

        layout.addWidget(QLabel(t("common.overlay_opacity_label")))
        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setFixedWidth(120)
        self._opacity_slider.setRange(0, 100)
        self._opacity_slider.setValue(round(self._canvas.mask_opacity() / 255 * 100))
        self._lbl_opacity_pct = QLabel(f"{self._opacity_slider.value()}%")
        self._lbl_opacity_pct.setFixedWidth(36)
        layout.addWidget(self._opacity_slider)
        layout.addWidget(self._lbl_opacity_pct)
        self._opacity_slider.valueChanged.connect(self._on_mask_opacity_changed)

        self._opacity_cluster = cluster

    def _on_mask_opacity_changed(self, value: int) -> None:
        self._lbl_opacity_pct.setText(f"{value}%")
        # 디바운스 불필요 — set_mask_opacity()는 디스크 I/O나 모델 재실행 없이
        # 메모리의 numpy 마스크를 QImage로 다시 그리기만 하므로 드래그 중에도 가볍다.
        self._canvas.set_mask_opacity(round(value / 100 * 255))

    def _build_right_panel(self) -> QWidget:
        right = QWidget()
        layout = QVBoxLayout(right)
        layout.setContentsMargins(4, 0, 0, 0)

        summary_card = QFrame()
        summary_card.setStyleSheet("background:#1f2329;border:1px solid #374151;border-radius:8px;")
        summary_layout = QVBoxLayout(summary_card)
        summary_layout.addWidget(QLabel(t("r.overall_summary_title")))
        self._lbl_overall_summary = QLabel(
            t("r.overall_summary_format").format(passed=0, failed=0, untested=0, total=0)
        )
        self._lbl_overall_summary.setWordWrap(True)
        summary_layout.addWidget(self._lbl_overall_summary)
        layout.addWidget(summary_card)

        self._lbl_cell_title = QLabel(t("r.no_cell_selected"))
        self._lbl_cell_title.setStyleSheet("color:#60a5fa;font-weight:bold;")
        layout.addWidget(self._lbl_cell_title)

        self._lbl_cell_badge = QLabel("-")
        self._lbl_cell_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_cell_badge.setStyleSheet(_BADGE_NONE)
        self._lbl_cell_badge.setFixedHeight(40)
        layout.addWidget(self._lbl_cell_badge)

        lbl_ref = QLabel(t("r.ref_area_note"))
        lbl_ref.setStyleSheet("color:#6b7280;font-size:10.5px;")
        layout.addWidget(lbl_ref)
        self._cell_image_table = QTableWidget(0, 2)
        self._cell_image_table.setHorizontalHeaderLabels([t("r.col_image"), t("r.col_area")])
        self._cell_image_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._cell_image_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self._cell_image_table, stretch=1)

        btn_view_all = QPushButton(t("r.btn_view_all_excel"))
        btn_view_all.clicked.connect(self._on_view_all_results)
        layout.addWidget(btn_view_all)

        right.setMinimumWidth(180)
        right.setMaximumWidth(280)
        return right

    # ── 플로팅 오버레이 배치 ─────────────────────────────────────────────────

    def eventFilter(self, obj, event) -> bool:
        if obj is self._canvas and event.type() == QEvent.Type.Resize:
            self._position_overlays()
        return super().eventFilter(obj, event)

    def _position_overlays(self) -> None:
        margin = 8
        w = self._canvas.width()
        # 디자인 스펙 v4: 각 클러스터에 캔버스 폭 비례 max-width를 둬, 캔버스가 좁아져도
        # 세 클러스터의 영역이 서로 겹치지 않게 한다(BUG-044). 내부 버튼이 잘리는 건
        # 허용하되, 클러스터끼리 겹쳐 클릭이 막히는 상태는 만들지 않는다.
        #
        # run_cluster(현재 이미지 검출/일괄 검출/전체 셀 분석 — 핵심 실행 버튼)는
        # 남는 공간만 받다 보니 창이 좁아지면 폭 0까지 수축해 클릭이 막혔다(BUG-050).
        # edit/nav보다 run을 우선해 최소폭(sizeHint)을 보장하고, 공간이 부족하면
        # edit/nav를 42%/46% 비율보다 더 줄여서 양보시킨다.
        run_min = self._run_cluster.sizeHint().width()

        self._edit_cluster.setMaximumWidth(max(1, int(w * 0.42)))
        self._nav_cluster.setMaximumWidth(max(1, int(w * 0.46)))
        self._edit_cluster.adjustSize()
        self._nav_cluster.adjustSize()

        side_budget = max(1, w - run_min - 4 * margin)
        if self._edit_cluster.width() + self._nav_cluster.width() > side_budget:
            edit_share = max(1, int(side_budget * 0.42 / 0.88))
            nav_share = max(1, side_budget - edit_share)
            self._edit_cluster.setMaximumWidth(edit_share)
            self._nav_cluster.setMaximumWidth(nav_share)
            self._edit_cluster.adjustSize()
            self._nav_cluster.adjustSize()

        edit_right = margin + self._edit_cluster.width()
        nav_left = w - margin - self._nav_cluster.width()
        available_for_run = max(run_min, nav_left - margin - edit_right - margin)
        self._run_cluster.setMaximumWidth(available_for_run)
        self._run_cluster.adjustSize()

        self._edit_cluster.move(margin, margin)
        run_x = max(edit_right + margin, (w - self._run_cluster.width()) // 2)
        run_x = min(run_x, nav_left - margin - self._run_cluster.width())
        run_x = max(run_x, edit_right + margin)
        self._run_cluster.move(run_x, margin)
        # run_cluster가 run_min을 보장받느라 nav 쪽으로 겹칠 수 있는 극단적으로 좁은
        # 캔버스에서는, run을 피해 nav를 오른쪽으로 더 밀면 nav 전체가 캔버스 밖으로
        # 나가 완전히 사라진다(BUG-050과 같은 "클릭 불가" 클래스). 겹침 회피보다
        # "항상 캔버스 안에 보이는" 쪽을 우선해 nav_x를 캔버스 우측 경계로 clamp —
        # 이 경우 nav가 run의 꼬리를 덮으며 겹치는 건 허용(ponytail: 세 클러스터
        # 전부를 위한 폭이 모자란 근본 원인은 캔버스 자체 최소폭 보장, 필요해지면 추가).
        nav_x = max(nav_left, run_x + self._run_cluster.width() + margin)
        nav_x = min(nav_x, w - self._nav_cluster.width())
        self._nav_cluster.move(nav_x, margin)

        # 불투명도 슬라이더는 상단 3개 클러스터와 겹치지 않도록 좌측 하단에 별도 배치.
        self._opacity_cluster.adjustSize()
        self._opacity_cluster.move(margin, self._canvas.height() - margin - self._opacity_cluster.height())

    # ── 편집 도구 ────────────────────────────────────────────────────────────

    def _set_tool(self, tool: str) -> None:
        self._active_tool = tool
        self._act_roi.setChecked(tool == _TOOL_ROI)
        self._brush_tools.set_tool(tool)   # 클러스터 소속 아니면(ROI) 전체 unchecked
        if tool == TOOL_BRUSH:
            self._canvas.set_brush_draw_mode(True)
        elif tool == TOOL_ERASER:
            self._canvas.set_brush_erase_mode(True)
        elif tool == TOOL_PAN:
            self._canvas.set_pan_mode(True)
        else:
            # ponytail: RRoiCanvas엔 "roi 모드" 전용 setter가 없다 — set_X_mode(False)를
            # 아무거나 호출하면 _mode가 "roi"로 떨어지는 현재 구현을 그대로 이용한다
            # (캔버스에 4번째 setter를 새로 추가하는 건 과한 변경, 조립 단계 범위 밖).
            self._canvas.set_pan_mode(False)

    def _update_undo_button_state(self) -> None:
        self._act_undo.setEnabled(self._canvas.can_undo())

    def _on_canvas_edited(self) -> None:
        """브러시 그리기/지우기 스트로크가 끝났을 때(erase_changed) — 수동 보정을
        세션 데이터에 반영하고 면적/판정을 재계산한다(요구사항 7)."""
        if self._current_image_path is None:
            return
        state = self._canvas.get_state()
        data = self._image_data(self._current_image_path)
        data["manual_strokes"] = state["manual_strokes"]
        data["removed_blob_regions"] = state["removed_blob_regions"]
        eff = self._canvas.effective_mask()
        data["area"] = contour_area(eff) if eff is not None else 0
        self._refresh_right_panel()
        self._refresh_step_indicator()
        self._schedule_autosave()

    # ── 세션 파일 ────────────────────────────────────────────────────────────

    def _on_open_session(self) -> None:
        path_str, _ = QFileDialog.getSaveFileName(
            self, t("r.open_session_dialog_title"), "r_session.json", "JSON (*.json)",
            options=QFileDialog.Option.DontConfirmOverwrite,
        )
        if not path_str:
            return
        path = Path(path_str)
        if path.exists():
            # 기존 세션 파일을 선택 — 불러오기
            self._load_session(path)
        else:
            # 아직 없는 파일명을 지정 — "새로 만들기" 의도이므로 현재 작업은
            # 그대로 유지하고 이후 저장 위치만 바꾼다 (BUG-043)
            self._session_path = path
            self._lbl_session_path.setText(str(path))
            self._lbl_session_path.setStyleSheet("color:#e5e7eb;font-size:11px;")
            self._do_save()

    def _load_session(self, path: Path) -> None:
        self._session_path = path
        self._session = r_store.load(path)
        self._image_data_map.clear()
        cells: dict[str, list[Path]] = {}
        for cell_id, cdata in self._session.get("cells", {}).items():
            paths: list[Path] = []
            for img in cdata.get("images", []):
                p = Path(img["path"])
                paths.append(p)
                self._image_data_map[str(p)] = {
                    "roi_override": img.get("roi_override"),
                    "manual_strokes": img.get("manual_strokes", []),
                    "area": img.get("area", 0),
                    "removed_blob_regions": img.get("removed_blob_regions", []),
                }
            cells[cell_id] = paths
        self._cells = cells
        self._cell_panel.set_cells(cells)

        self._settings_dialog.set_threshold(self._session.get("threshold", 128))
        self._settings_dialog.set_denominator(self._session.get("denominator", 0.0))
        self._settings_dialog.set_spec_lower(self._session.get("spec_lower", 0.0))
        self._settings_dialog.set_spec_upper(self._session.get("spec_upper", 0.0))
        self._settings_dialog.set_auto_detect_enabled(self._session.get("auto_detect", False))

        self._current_cell = None
        self._current_image_path = None
        self._canvas.clear()
        self._lbl_session_path.setText(str(path))
        self._lbl_session_path.setStyleSheet("color:#e5e7eb;font-size:11px;")
        self._refresh_settings_summary()
        self._refresh_right_panel()
        self._refresh_step_indicator()
        self._sync_detect_buttons_enabled()

    def _do_save(self) -> None:
        if self._session_path is None:
            return
        self._sync_canvas_state_to_data()
        cells_payload: dict = {}
        for cell_id, paths in self._cells.items():
            images = []
            for p in paths:
                d = self._image_data(p)
                images.append({
                    "path": str(p),
                    "roi_override": list(d["roi_override"]) if d.get("roi_override") else None,
                    "manual_strokes": d.get("manual_strokes", []),
                    "area": d.get("area", 0),
                    "removed_blob_regions": d.get("removed_blob_regions", []),
                })
            cells_payload[cell_id] = {"images": images}
        self._session["cells"] = cells_payload
        try:
            r_store.save(self._session_path, self._session)
        except OSError as exc:
            log.warning(f"R 분석 세션 저장 실패 — {self._session_path}: {exc}")

    def _schedule_autosave(self) -> None:
        self._save_timer.start()

    def _sync_canvas_state_to_data(self) -> None:
        """roi_override는 여기서 동기화하지 않는다 — 설정 패널의 커밋 버튼을 눌러야만
        세션에 반영된다(요구사항 3, `_on_roi_global_requested`/`_on_roi_override_requested`)."""
        if self._current_image_path is None:
            return
        state = self._canvas.get_state()
        self._image_data(self._current_image_path)["manual_strokes"] = state["manual_strokes"]

    # ── 이미지 데이터 헬퍼 ────────────────────────────────────────────────────

    def _image_data(self, path: Path) -> dict:
        return self._image_data_map.setdefault(str(path), _default_image_data())

    def _cv2_imread_cached(self, path: Path) -> np.ndarray | None:
        """`imread_unicode()` 결과를 LRU로 캐싱 — 이미지 전환/threshold 재검출 때마다
        같은 대형 이미지를 반복 디코드하지 않는다(P1 성능)."""
        key = str(path)
        cached = self._image_cache.get(key)
        if cached is not None:
            self._image_cache.move_to_end(key)
            return cached
        img = imread_unicode(key)
        if img is not None:
            self._image_cache[key] = img
            if len(self._image_cache) > _IMAGE_CACHE_SIZE:
                self._image_cache.popitem(last=False)
        return img

    def _effective_roi(self, path: Path) -> tuple[int, int, int, int] | None:
        data = self._image_data(path)
        if data.get("roi_override"):
            return tuple(data["roi_override"])
        gr = self._session.get("global_roi")
        return tuple(gr) if gr else None

    def _compute_detected_mask(self, path: Path, img: np.ndarray) -> np.ndarray:
        """자동검출 켜짐+ROI 있음 -> 실제 검출. 그 외(자동검출 꺼짐, 또는 ROI 없음)는
        빈(all-False) 마스크 — None이 아니라 빈 배열이어야 effective_mask()가 브러시
        단독 결과를 반환한다(None이면 area가 무조건 0으로 강제됨, 핵심 버그 포인트)."""
        h, w = img.shape[:2]
        if self._settings_dialog.auto_detect_enabled():
            roi = self._effective_roi(path)
            if roi is not None:
                return detect_contour_mask(img, roi, self._settings_dialog.threshold())
        return np.zeros((h, w), dtype=bool)

    # ── 셀 패널 연동 ─────────────────────────────────────────────────────────

    def _on_cell_selected(self, cell_id: str) -> None:
        self._current_cell = cell_id
        if self._current_image_path not in self._cells.get(cell_id, []):
            self._clear_current_image()
        self._refresh_thumb_strip()
        self._refresh_right_panel()

    def _on_cells_changed(self) -> None:
        self._cells = self._cell_panel.get_cells()
        if self._current_cell is not None and self._current_image_path not in self._cells.get(self._current_cell, []):
            self._clear_current_image()
        self._refresh_thumb_strip()
        self._refresh_right_panel()
        self._refresh_step_indicator()
        self._schedule_autosave()

    # ── 현재 이미지(캔버스/좌측 목록/썸네일/네비게이션 공유 상태) ─────────────

    def _clear_current_image(self) -> None:
        """셀 전환/이미지 삭제로 현재 보던 이미지가 더 이상 유효하지 않을 때 호출.
        캔버스가 방금 지운/다른 셀의 이미지를 그대로 보여주면 "선택이 반영 안
        됐나?" 혼동을 준다(2026-11-09 레이아웃 점검 중 발견) — 빈 캔버스로 되돌림."""
        self._current_image_path = None
        self._canvas.blockSignals(True)
        try:
            self._canvas.clear()
            self._canvas.set_detected_mask(None)
            self._canvas.set_state({
                "roi": None, "erase_strokes": [], "manual_strokes": [],
                "removed_blob_regions": [],
            })
        finally:
            self._canvas.blockSignals(False)
        self._update_nav_label()
        self._update_undo_button_state()

    def _set_current_image(self, path: Path) -> None:
        if path != self._current_image_path:
            self._load_image(path)
        self._cell_panel.select_image(path)
        self._select_thumb(path)
        self._update_nav_label()
        self._refresh_right_panel()

    def _load_image(self, path: Path) -> None:
        self._sync_canvas_state_to_data()
        self._current_image_path = path
        img = self._cv2_imread_cached(path)
        if img is not None:
            h, w = img.shape[:2]
            pixmap = _bgr_to_qpixmap(img)
        else:
            pixmap = QPixmap(str(path))
            w, h = pixmap.width(), pixmap.height()
        data = self._image_data(path)
        roi = self._effective_roi(path)

        self._canvas.blockSignals(True)
        try:
            self._canvas.set_image_size(w, h)
            self._canvas.set_pixmap(pixmap)
            self._canvas.set_state({
                "roi": tuple(roi) if roi else None,
                "erase_strokes": [],   # ponytail: erase_mask() getter 전용 레거시 필드 — 현재
                                        # 화면 렌더링/면적 계산엔 쓰이지 않아 세션에 저장하지
                                        # 않는다(필요해지면 manual_strokes처럼 영속화 추가).
                "manual_strokes": data.get("manual_strokes", []),
                "removed_blob_regions": data.get("removed_blob_regions", []),
            })
            mask = self._compute_detected_mask(path, img) if img is not None else None
            self._canvas.set_detected_mask(mask)
        finally:
            self._canvas.blockSignals(False)

        eff = self._canvas.effective_mask()
        data["area"] = contour_area(eff) if eff is not None else 0
        self._update_undo_button_state()

    def _select_thumb(self, path: Path) -> None:
        for i in range(self._thumb_strip.count()):
            item = self._thumb_strip.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == path:
                self._thumb_strip.blockSignals(True)
                self._thumb_strip.setCurrentItem(item)
                self._thumb_strip.blockSignals(False)
                return

    def _navigate(self, step: int) -> None:
        if self._current_cell is None or self._current_image_path is None:
            return
        paths = self._cells.get(self._current_cell, [])
        if self._current_image_path not in paths:
            return
        idx = paths.index(self._current_image_path)
        new_idx = max(0, min(idx + step, len(paths) - 1))
        if new_idx != idx:
            self._set_current_image(paths[new_idx])

    def _update_nav_label(self) -> None:
        if self._current_cell is None or self._current_image_path is None:
            self._lbl_nav.setText("- (0/0)")
            return
        paths = self._cells.get(self._current_cell, [])
        try:
            idx = paths.index(self._current_image_path) + 1
        except ValueError:
            idx = 0
        self._lbl_nav.setText(f"{self._current_image_path.name} ({idx}/{len(paths)})")

    def _refresh_thumb_strip(self) -> None:
        self._thumb_strip.clear()
        if self._current_cell is None:
            return
        for p in self._cells.get(self._current_cell, []):
            pm = QPixmap(str(p)).scaled(
                _THUMB_PX, _THUMB_PX, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            item = QListWidgetItem(QIcon(pm), p.name)
            item.setData(Qt.ItemDataRole.UserRole, p)
            self._thumb_strip.addItem(item)
        if self._current_image_path is not None:
            self._select_thumb(self._current_image_path)

    # ── 검사 설정(threshold/분모/스펙/ROI) ───────────────────────────────────

    def _on_settings_changed(self) -> None:
        self._session["threshold"] = self._settings_dialog.threshold()
        self._session["denominator"] = self._settings_dialog.denominator()
        self._session["spec_lower"] = self._settings_dialog.spec_lower()
        self._session["spec_upper"] = self._settings_dialog.spec_upper()
        self._session["auto_detect"] = self._settings_dialog.auto_detect_enabled()
        if self._current_image_path is not None:
            self._run_and_display_detection(self._current_image_path)
        self._refresh_settings_summary()
        self._refresh_right_panel()
        self._sync_detect_buttons_enabled()
        self._schedule_autosave()

    def _on_roi_global_requested(self) -> None:
        roi = self._canvas.get_roi()
        if roi is None:
            QMessageBox.warning(self._settings_dialog, t("r.no_roi_title"), t("r.no_roi_msg"))
            return
        self._session["global_roi"] = [roi.x(), roi.y(), roi.width(), roi.height()]
        if self._current_image_path is not None:
            self._run_and_display_detection(self._current_image_path)
        self._refresh_settings_summary()
        self._refresh_right_panel()
        self._refresh_step_indicator()
        self._schedule_autosave()

    def _on_roi_override_requested(self) -> None:
        if self._current_image_path is None:
            QMessageBox.warning(self._settings_dialog, t("infer.no_image_title"), t("r.no_image_msg"))
            return
        roi = self._canvas.get_roi()
        if roi is None:
            QMessageBox.warning(self._settings_dialog, t("r.no_roi_title"), t("r.no_roi_msg"))
            return
        self._image_data(self._current_image_path)["roi_override"] = [roi.x(), roi.y(), roi.width(), roi.height()]
        self._run_and_display_detection(self._current_image_path)
        self._refresh_settings_summary()
        self._refresh_right_panel()
        self._refresh_step_indicator()
        self._schedule_autosave()

    def _refresh_settings_summary(self) -> None:
        s = self._session
        roi_desc = t("r.roi_global_set") if s.get("global_roi") else t("r.roi_unset")
        override_n = sum(1 for d in self._image_data_map.values() if d.get("roi_override"))
        if override_n:
            roi_desc += t("r.roi_override_suffix").format(n=override_n)
        if not self._settings_dialog.auto_detect_enabled():
            roi_desc += t("r_settings.auto_detect_off_suffix")
        self._lbl_settings_summary.setText(
            t("r.settings_summary_format").format(
                threshold=s.get('threshold', 128),
                denom=f"{s.get('denominator', 0.0):g}",
                lower=f"{s.get('spec_lower', 0.0):g}",
                upper=f"{s.get('spec_upper', 0.0):g}",
                roi_desc=roi_desc,
            )
        )

    # ── 검출 실행(3단계) ─────────────────────────────────────────────────────

    def _run_and_display_detection(self, path: Path) -> None:
        img = self._cv2_imread_cached(path)
        if img is None:
            self._canvas.set_detected_mask(None)
            return
        mask = self._compute_detected_mask(path, img)
        self._canvas.set_detected_mask(mask)
        eff = self._canvas.effective_mask()
        self._image_data(path)["area"] = contour_area(eff) if eff is not None else 0

    def _on_detect_current(self) -> None:
        if self._current_image_path is None:
            QMessageBox.information(self, t("infer.no_image_title"), t("r.no_image_msg"))
            return
        self._run_and_display_detection(self._current_image_path)
        self._refresh_right_panel()
        self._refresh_step_indicator()
        self._schedule_autosave()

    def _on_detect_cell(self) -> None:
        if self._current_cell is None:
            QMessageBox.information(self, t("r.no_cell_title"), t("r.no_cell_msg"))
            return
        self._run_batch_detect(self._cells.get(self._current_cell, []))

    def _on_detect_all(self) -> None:
        all_paths = [p for paths in self._cells.values() for p in paths]
        self._run_batch_detect(all_paths)

    def _run_batch_detect(self, paths: list[Path]) -> None:
        # BUG-045: 배치 검출이 진행 중일 때 같은(또는 다른) 배치 버튼을 다시 누르면
        # self._detect_worker/self._progress가 새 인스턴스로 덮어써지고 기존 워커의
        # 참조가 끊긴 채 백그라운드에서 계속 돌아 두 워커가 동시에 실행됐다 — 재진입 가드.
        if self._detect_worker is not None and self._detect_worker.isRunning():
            return
        if not paths:
            QMessageBox.information(self, t("infer.no_image_title"), t("r.no_images_to_detect_msg"))
            return
        # ROI 없는 이미지도 job에 포함 — roi=None이면 워커가 빈 마스크 + 브러시만으로
        # 면적을 계산한다(자동검출 꺼짐/ROI 미지정 워크플로도 일괄검출 가능해야 함).
        jobs = [
            (
                p, self._effective_roi(p), self._image_data(p).get("manual_strokes", []),
                self._image_data(p).get("removed_blob_regions", []),
            )
            for p in paths
        ]

        self._set_detect_buttons_enabled(False)
        self._progress = QProgressDialog(t("r.detecting_progress_label"), t("common.cancel"), 0, len(jobs), self)
        self._progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._detect_worker = _RDetectWorker(
            jobs, self._settings_dialog.threshold(), self._settings_dialog.auto_detect_enabled()
        )
        self._detect_worker.image_done.connect(self._on_detect_image_done)
        self._detect_worker.progress.connect(lambda done, _total: self._progress.setValue(done))
        self._progress.canceled.connect(self._detect_worker.requestInterruption)
        self._detect_worker.finished.connect(self._on_batch_detect_finished)
        self._detect_worker.start()
        self._progress.show()

    def _set_detect_buttons_enabled(self, enabled: bool) -> None:
        self._btn_detect_current.setEnabled(enabled)
        self._btn_detect_cell.setEnabled(enabled)
        self._btn_detect_all.setEnabled(enabled)

    def _sync_detect_buttons_enabled(self) -> None:
        """배치 검출이 실행 중일 때의 임시 비활성화(_set_detect_buttons_enabled)와는
        별개로, 설정 변경·세션 로드 시 이 메서드로 "정상 상태"의 enabled를 동기화한다.
        자동검출이 꺼져 있어도 "검출" 버튼은 유효하다 — manual_strokes(브러시)만으로
        면적을 재계산하는 동작이기 때문(자동검출 OFF가 기본값인 워크플로 지원)."""
        self._set_detect_buttons_enabled(True)

    def _on_detect_image_done(self, path_str: str, area: int) -> None:
        self._image_data_map.setdefault(path_str, _default_image_data())["area"] = area

    def _on_batch_detect_finished(self) -> None:
        if self._progress is not None:
            self._progress.close()
            self._progress = None
        self._sync_detect_buttons_enabled()
        if self._current_image_path is not None:
            self._run_and_display_detection(self._current_image_path)
        self._refresh_right_panel()
        self._refresh_step_indicator()
        self._schedule_autosave()

    # ── 셀 R·판정 + 우측 패널 ─────────────────────────────────────────────────

    def _cell_rollup(self, cell_id: str) -> dict:
        paths = self._cells.get(cell_id, [])
        areas = [self._image_data(p)["area"] for p in paths]
        rollup = cell_rollup(
            areas, self._settings_dialog.denominator(),
            self._settings_dialog.spec_lower(), self._settings_dialog.spec_upper(),
        )
        if rollup["image_count"] == 0:
            # ponytail: core cell_rollup()은 이미지 0장도 area합계 0으로 ratio/판정을
            # 계산한다(스펙 하한이 0이면 "합격"으로 오판) — "미검사"는 탭에서 보정.
            # 이미지가 있지만 아직 검출을 안 돌린 경우(area=0)까지는 구분 못 함 — 데이터
            # 모델에 "detected" 플래그가 없기 때문(YAGNI, 필요해지면 추가).
            rollup["pass_fail"] = None
        rollup["images"] = [(p.name, self._image_data(p)["area"]) for p in paths]
        return rollup

    def _refresh_right_panel(self) -> None:
        self._refresh_overall_summary()
        self._refresh_current_cell_block()

    def _refresh_overall_summary(self) -> None:
        passed = failed = untested = 0
        for cell_id in self._cells:
            rollup = self._cell_rollup(cell_id)
            self._cell_panel.set_cell_status(cell_id, rollup["pass_fail"])
            if rollup["pass_fail"] is True:
                passed += 1
            elif rollup["pass_fail"] is False:
                failed += 1
            else:
                untested += 1
        self._lbl_overall_summary.setText(
            t("r.overall_summary_format").format(
                passed=passed, failed=failed, untested=untested, total=len(self._cells),
            )
        )

    def _refresh_current_cell_block(self) -> None:
        cell_id = self._cell_panel.selected_cell()
        if cell_id is None:
            self._lbl_cell_title.setText(t("r.no_cell_selected"))
            self._lbl_cell_badge.setText("-")
            self._lbl_cell_badge.setStyleSheet(_BADGE_NONE)
            self._cell_image_table.setRowCount(0)
            return
        rollup = self._cell_rollup(cell_id)
        self._lbl_cell_title.setText(t("r.cell_title_selected").format(cell_id=cell_id))
        ratio = rollup["ratio"]
        ratio_txt = f"{ratio:.4f}" if ratio is not None else "N/A"
        pf = rollup["pass_fail"]
        if pf is True:
            self._lbl_cell_badge.setText(f"PASS  (R={ratio_txt})")
            self._lbl_cell_badge.setStyleSheet(_BADGE_PASS)
        elif pf is False:
            self._lbl_cell_badge.setText(f"FAIL  (R={ratio_txt})")
            self._lbl_cell_badge.setStyleSheet(_BADGE_FAIL)
        else:
            self._lbl_cell_badge.setText(t("r.untested_badge").format(ratio=ratio_txt))
            self._lbl_cell_badge.setStyleSheet(_BADGE_NONE)

        images = rollup["images"]
        self._cell_image_table.setRowCount(len(images))
        for r, (name, area) in enumerate(images):
            self._cell_image_table.setItem(r, 0, QTableWidgetItem(name))
            self._cell_image_table.setItem(r, 1, QTableWidgetItem(str(area)))

    def _on_view_all_results(self) -> None:
        cells_payload = {cid: self._cell_rollup(cid) for cid in self._cells}
        dlg = RBatchResultDialog(cells_payload, self)
        dlg.exec()

    # ── 스텝 인디케이터 ──────────────────────────────────────────────────────

    def _refresh_step_indicator(self) -> None:
        """순수 표시용 배너(클릭 이동 없음) — 완료 여부는 아래 조건의 가벼운
        근사치일 뿐 정밀 추적은 아니다(스텝 4/5는 사용자 판단이 필요해 자동
        완료 처리하지 않음, YAGNI)."""
        completed: set[int] = set()
        if self._cells:
            completed.add(1)
        has_roi = bool(self._session.get("global_roi")) or any(
            d.get("roi_override") for d in self._image_data_map.values()
        )
        if has_roi:
            completed.add(2)
        if any(d.get("area", 0) for d in self._image_data_map.values()):
            completed.add(3)
        current = min(max(completed, default=0) + 1, 5)
        self._step_indicator.set_state(current, completed)


if __name__ == "__main__":
    import os
    import sys

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)

    tab = RAnalysisTab()
    assert tab._cell_rollup("NOPE")["pass_fail"] is None   # 빈 셀 -> 미검사
    tab._cells = {"CELL-A": [Path("a.jpg"), Path("b.jpg")]}
    tab._image_data_map = {
        "a.jpg": {"roi_override": None, "manual_strokes": [], "area": 100},
        "b.jpg": {"roi_override": None, "manual_strokes": [], "area": 200},
    }
    tab._settings_dialog.set_denominator(300.0)
    tab._settings_dialog.set_spec_lower(0.9)
    tab._settings_dialog.set_spec_upper(1.1)
    rollup = tab._cell_rollup("CELL-A")
    assert rollup["sum_area"] == 300 and rollup["pass_fail"] is True, rollup

    tab._refresh_right_panel()
    assert "합격 1" in tab._lbl_overall_summary.text()

    # 오버레이 불투명도 슬라이더 — 기본값(90/255≈35%)과 변경 시 캔버스 반영 확인.
    assert tab._opacity_slider.value() == 35
    tab._opacity_slider.setValue(80)
    assert tab._canvas.mask_opacity() == round(80 / 100 * 255)

    # ROI 아이콘 — tool_select -> tool_rect 교체(에러 없이 생성되는지만 확인).
    assert not tab._act_roi.icon().isNull()

    # 검출 결과 show/hide — 눈 액션 toggled가 캔버스 플래그에 반영되는지,
    # F키 입력이 액션을 토글하는지(실제 keyPressEvent 호출로 시뮬레이션).
    assert tab._act_overlay_visible.isChecked() is True
    assert tab._canvas._mask_visible is True
    tab._act_overlay_visible.setChecked(False)
    assert tab._canvas._mask_visible is False
    from PyQt6.QtCore import QEvent as _QEvent
    from PyQt6.QtGui import QKeyEvent as _QKeyEvent
    f_press = _QKeyEvent(_QEvent.Type.KeyPress, Qt.Key.Key_F, Qt.KeyboardModifier.NoModifier)
    tab._canvas.keyPressEvent(f_press)
    assert tab._act_overlay_visible.isChecked() is True   # F키 -> toggle() -> 다시 표시
    assert tab._canvas._mask_visible is True

    # 자동 검출 OFF + ROI 미지정 + 브러시만으로 면적이 계산되는지(이번 라운드 핵심 버그 수정).
    dummy_img = np.zeros((100, 100, 3), dtype=np.uint8)
    dummy_path = Path("dummy_no_roi.jpg")
    assert tab._effective_roi(dummy_path) is None   # ROI 지정 안 함
    tab._settings_dialog.set_auto_detect_enabled(False)
    mask_off = tab._compute_detected_mask(dummy_path, dummy_img)
    assert mask_off.dtype == bool and not mask_off.any()   # 빈 마스크(None 아님)
    tab._canvas.set_image_size(100, 100)
    tab._canvas.set_detected_mask(mask_off)
    tab._canvas._manual_strokes = [(True, [(50.0, 50.0, 10.0)])]   # 브러시 1스트로크 직접 커밋
    eff_off = tab._canvas.effective_mask()
    assert eff_off is not None and eff_off.any(), "자동검출 OFF라도 브러시 영역만으로 effective_mask가 나와야 함"
    assert contour_area(eff_off) > 0

    # 자동검출을 다시 ON으로 켜도(ROI 여전히 없음) 검출 마스크 자체는 그대로 빈 상태 유지.
    tab._settings_dialog.set_auto_detect_enabled(True)
    mask_on_no_roi = tab._compute_detected_mask(dummy_path, dummy_img)
    assert not mask_on_no_roi.any(), "ROI 없으면 자동검출 ON이어도 검출 마스크는 비어야 함(기존 동작 유지)"

    # 검출 버튼 3개는 자동검출 on/off와 무관하게 항상 활성 — OFF일 때도 브러시
    # 기반 재계산이라는 유효한 동작이라 비활성화하면 안 됨(2026-11-09 요구사항).
    tab._settings_dialog.set_auto_detect_enabled(False)
    tab._on_settings_changed()
    assert tab._btn_detect_current.isEnabled() is True
    assert tab._btn_detect_cell.isEnabled() is True
    assert tab._btn_detect_all.isEnabled() is True
    tab._settings_dialog.set_auto_detect_enabled(True)
    tab._on_settings_changed()
    assert tab._btn_detect_current.isEnabled() is True

    # 일괄검출(_RDetectWorker)도 ROI 없이 브러시 스트로크만으로 면적을 낸다 —
    # roi=None job을 실제로 통과시켜 batch 경로가 단일 이미지 경로와 동일하게
    # 동작하는지 확인(요구사항: 자동검출 꺼짐이어도 일괄검출 가능해야 함).
    worker = _RDetectWorker(
        jobs=[(dummy_path, None, [(True, [(50.0, 50.0, 10.0)])], [])],
        threshold=128, auto_detect=False,
    )
    batch_results: list[tuple[str, int]] = []
    worker.image_done.connect(lambda path, area: batch_results.append((path, area)))
    cv2.imwrite(str(dummy_path), dummy_img)
    try:
        worker.run()   # QThread이지만 직접 run() 호출 — 이벤트 루프 없이 동기 검증
    finally:
        dummy_path.unlink(missing_ok=True)
    assert len(batch_results) == 1 and batch_results[0][1] > 0, \
        "ROI 없는 job도 브러시 스트로크로 면적 > 0이 나와야 함"

    # BUG-053: 한글 경로 이미지도 탭/워커 양쪽에서 디코드돼야 함(cv2.imread는 None을
    # 반환해 리터치 전체가 죽었다) — cv2.imwrite도 한글 경로를 못 써서 imencode로 만든다.
    kr_path = Path("r_한글_경로_테스트.png")
    cv2.imencode(".png", dummy_img)[1].tofile(str(kr_path))
    try:
        assert tab._cv2_imread_cached(kr_path) is not None, "한글 경로 이미지를 탭이 못 읽음"
        kr_worker = _RDetectWorker(
            jobs=[(kr_path, None, [(True, [(50.0, 50.0, 10.0)])], [])],
            threshold=128, auto_detect=False,
        )
        kr_results: list[int] = []
        kr_worker.image_done.connect(lambda _path, area: kr_results.append(area))
        kr_worker.run()
        assert kr_results and kr_results[0] > 0, "한글 경로 job도 image_done이 나와야 함"
    finally:
        kr_path.unlink(missing_ok=True)

    # 캔버스가 좁아져도 실행 버튼 클러스터가 폭 0으로 수축해 클릭 불가능해지면 안 됨(BUG-050).
    tab._canvas.resize(800, 600)
    tab._position_overlays()
    run_min_check = tab._run_cluster.sizeHint().width()
    assert tab._run_cluster.width() >= run_min_check, "실행 버튼 클러스터가 최소폭보다 작아지면 안 됨"
    assert tab._btn_detect_current.width() > 0, "좁은 창에서도 실행 버튼이 클릭 가능한 폭을 가져야 함(BUG-050)"

    # run_cluster가 최소폭을 보장받느라 nav_cluster를 캔버스 밖으로 밀어내면 안 됨
    # (run 폭을 보장하는 1차 수정이 nav를 안 보이게 만드는 2차 회귀를 낳았던 부분 —
    # 2026-11-09 재점검에서 발견, nav_x를 캔버스 우측 경계로 clamp해 수정).
    for canvas_w in (700, 500, 350, 250):
        tab._canvas.resize(canvas_w, 600)
        tab._position_overlays()
        actual_w = tab._canvas.width()   # RRoiCanvas 자체 최소폭보다 작게는 안 줄어듦
        assert tab._nav_cluster.geometry().right() <= actual_w, \
            f"nav_cluster가 캔버스 밖으로 밀려나면 안 됨(canvas_w={actual_w})"

    # 캔버스 자체에 세 클러스터 최소폭 합만큼 최소 너비를 강제해, 창을 아무리 좁혀도
    # 위 좁은-캔버스 보정 로직이 실제로 필요한 구간(클러스터가 1px로 짓눌리는 상태)에
    # 들어가지 못하게 한다(Zone 탭 BUG-048과 동일 패턴).
    expected_min = (
        tab._edit_cluster.minimumSizeHint().width()
        + tab._run_cluster.minimumSizeHint().width()
        + tab._nav_cluster.minimumSizeHint().width()
        + 32
    )
    assert tab._canvas.minimumWidth() == expected_min

    # 셀 전환/이미지 삭제로 현재 보던 이미지가 더 이상 유효하지 않으면 캔버스가
    # 이전 이미지를 계속 보여주지 말고 비워야 함(2026-11-09 레이아웃 점검 중 발견 —
    # "선택이 안 먹혔나?" 혼동 방지).
    stale_path = Path("stale_test.jpg")
    cv2.imwrite(str(stale_path), dummy_img)
    try:
        tab._cell_panel.set_cells({"CELL-STALE": [stale_path]})
        tab._on_cells_changed()
        tab._cell_panel._select_cell("CELL-STALE")
        tab._set_current_image(stale_path)
        assert tab._current_image_path == stale_path
        tab._cell_panel.set_cells({"CELL-STALE": []})
        tab._on_cells_changed()
        assert tab._current_image_path is None, "이미지가 전부 삭제되면 캔버스 현재 이미지도 비워야 함"
        assert tab._canvas.pixmap() is None, "현재 이미지가 없으면 캔버스도 빈 화면이어야 함(이전 이미지 잔상 금지)"
    finally:
        stale_path.unlink(missing_ok=True)

    # ── 골든 패스: 블랍 선택 → Delete → area 감소 → 저장/로드 왕복 후
    # removed_blob_regions 보존(스펙 "r-analysis-tab-roi-blob-select-delete") ──
    from PyQt6.QtCore import QEvent as _QEvent2, QPointF as _QPointF2
    from PyQt6.QtGui import QKeyEvent as _QKeyEvent2

    blob_path = Path("r_blob_golden_test.jpg")
    session_path = Path("r_blob_golden_session.json")
    other_path = Path("r_blob_golden_other.json")
    blob_img = np.zeros((60, 80, 3), dtype=np.uint8)
    blob_img[5:15, 5:15] = 255     # 블랍 A
    blob_img[5:15, 40:50] = 255    # 블랍 B
    cv2.imwrite(str(blob_path), blob_img)
    try:
        tab._session_path = None
        tab._cell_panel.set_cells({"CELL-BLOB": [blob_path]})
        tab._on_cells_changed()
        tab._cell_panel._select_cell("CELL-BLOB")
        tab._session["global_roi"] = [0, 0, 80, 60]
        tab._settings_dialog.set_auto_detect_enabled(True)
        tab._settings_dialog.set_threshold(128)
        tab._set_current_image(blob_path)
        assert tab._current_image_path == blob_path

        area_before = tab._image_data(blob_path)["area"]
        assert area_before > 0, "검출된 블랍이 있어야 area > 0"

        label = tab._canvas._blob_label_at(_QPointF2(10, 10))
        assert label is not None, "(10,10) 위치에 블랍 A가 검출돼야 함"
        tab._canvas._select_blob(label)
        del_evt = _QKeyEvent2(_QEvent2.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier)
        tab._canvas.keyPressEvent(del_evt)

        area_after = tab._image_data(blob_path)["area"]
        assert area_after < area_before, "블랍 삭제 후 area가 감소해야 함"
        assert len(tab._image_data(blob_path)["removed_blob_regions"]) == 1

        # BUG-054: 일괄 검출 워커도 삭제한 블랍을 빼야 함 — 캔버스 면적과 같아야 한다
        # (job에 removed_blob_regions가 안 실리면 삭제 전 면적으로 덮어써졌다).
        blob_data = tab._image_data(blob_path)
        blob_worker = _RDetectWorker(
            jobs=[(blob_path, tab._effective_roi(blob_path), blob_data["manual_strokes"],
                   blob_data["removed_blob_regions"])],
            threshold=128, auto_detect=True,
        )
        blob_results: list[int] = []
        blob_worker.image_done.connect(lambda _path, area: blob_results.append(area))
        blob_worker.run()
        assert blob_results == [contour_area(tab._canvas.effective_mask())] == [area_after], \
            (blob_results, area_after)

        # zone-v1.17.0: 삭제·브러시·삭제 후 재브러시·지우개가 섞여도 캔버스 == 워커.
        def _commit_stroke(draw: bool, x: float, y: float, r: float) -> None:
            # 캔버스 mouseReleaseEvent의 스트로크 커밋과 같은 순서(실제 마우스 경로는
            # r_roi_canvas self-check가 검증) — 여기선 탭/워커/세션 연동만 본다.
            tab._canvas._manual_strokes.append((draw, [(x, y, r)]))
            tab._canvas._rebuild_mask_image()
            tab._canvas.erase_changed.emit()

        def _worker_area() -> int:
            d = tab._image_data(blob_path)
            wk = _RDetectWorker(
                jobs=[(blob_path, tab._effective_roi(blob_path), d["manual_strokes"],
                       d["removed_blob_regions"])],
                threshold=128, auto_detect=True,
            )
            out: list[int] = []
            wk.image_done.connect(lambda _path, area: out.append(area))
            wk.run()
            return out[0]

        _commit_stroke(True, 52.0, 10.0, 3.0)    # 블랍 B(x=40..49)에 붙여 그림
        assert tab._image_data(blob_path)["area"] > area_after
        joined = tab._canvas._blob_label_at(_QPointF2(54, 10))
        assert joined is not None and joined == tab._canvas._blob_label_at(_QPointF2(45, 10))
        tab._canvas._select_blob(joined)
        tab._canvas.keyPressEvent(del_evt)        # 검출분 + 브러시분 통째로 삭제
        assert tab._image_data(blob_path)["area"] == 0 == _worker_area()
        _commit_stroke(True, 45.0, 10.0, 4.0)    # 삭제한 자리에 재브러시 — 살아나야 함
        _commit_stroke(False, 45.0, 10.0, 2.0)   # 지우개
        area_mixed = tab._image_data(blob_path)["area"]
        assert area_mixed > 0
        assert _worker_area() == contour_area(tab._canvas.effective_mask()) == area_mixed

        tab._session_path = session_path
        tab._do_save()
        assert session_path.exists()

        r_store.save(other_path, _default_session())
        tab._load_session(other_path)
        # 다른(관계없는) 세션으로 전환했을 때 이전 세션의 삭제 이력이 새어들면
        # 안 된다(image_data_map 자체는 설정 변경 시 재검출로 다시 채워질 수
        # 있음 — 기존 _load_session 순서의 별개 특성, 이번 기능 범위 밖).
        for d in tab._image_data_map.values():
            assert d.get("removed_blob_regions", []) == [], \
                "다른 세션에 이전 삭제 이력이 새어들면 안 됨"

        tab._load_session(session_path)
        restored = tab._image_data_map[str(blob_path)]
        # 삭제 영역 = [x, y, w, h, n(삭제 시점 스트로크 수)]
        assert restored["removed_blob_regions"] == [
            [5.0, 5.0, 10.0, 10.0, 0], [40.0, 5.0, 16.0, 10.0, 1],
        ], restored["removed_blob_regions"]
        assert len(restored["manual_strokes"]) == 3
        assert restored["area"] == area_mixed
        # 다시 열어 화면에 올려도 같은 면적으로 복원돼야 함(저장→로드 왕복).
        tab._cell_panel._select_cell("CELL-BLOB")
        tab._set_current_image(blob_path)
        assert contour_area(tab._canvas.effective_mask()) == area_mixed == _worker_area()

        # 기존(zone-v1.16.x) 세션 — 4-원소 영역 / 키 없음이 오류 없이 열리고, 결과가
        # 이전 버전 계산(삭제 영역 먼저 제외 → 스트로크 적용)과 같아야 함.
        from app.core.r_analysis_metrics import regions_mask as _regions_mask
        from app.core.zone_metrics import apply_manual_strokes as _apply_strokes
        legacy_strokes = [[True, [[10.0, 10.0, 3.0]]]]
        legacy_regions = [[5.0, 5.0, 10.0, 10.0]]
        r_store.save(other_path, {
            **_default_session(), "global_roi": [0, 0, 80, 60], "auto_detect": True,
            "cells": {
                "CELL-OLD": {"images": [{
                    "path": str(blob_path), "roi_override": None, "area": 0,
                    "manual_strokes": legacy_strokes, "removed_blob_regions": legacy_regions,
                }]},
                "CELL-OLDER": {"images": [{"path": "no_key.jpg", "manual_strokes": [], "area": 0}]},
            },
        })
        tab._load_session(other_path)
        tab._cell_panel._select_cell("CELL-OLD")
        tab._set_current_image(blob_path)
        legacy_det = detect_contour_mask(cv2.imread(str(blob_path)), (0, 0, 80, 60), 128)
        legacy_area = contour_area(_apply_strokes(
            legacy_det & ~_regions_mask(legacy_det.shape, legacy_regions), legacy_strokes
        ))
        assert 0 < legacy_area < contour_area(legacy_det)
        assert tab._image_data(blob_path)["area"] == legacy_area == _worker_area()
        assert tab._image_data(Path("no_key.jpg"))["removed_blob_regions"] == []
    finally:
        for p in (blob_path, session_path, other_path):
            p.unlink(missing_ok=True)

    print("r_analysis_tab self-check OK")
