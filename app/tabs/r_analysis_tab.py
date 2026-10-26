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

from pathlib import Path

import cv2
from PyQt6.QtCore import QEvent, QSize, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel, QListWidget,
    QListWidgetItem, QMessageBox, QProgressDialog, QPushButton, QSpinBox,
    QSplitter, QTableWidget, QTableWidgetItem, QToolBar, QVBoxLayout, QWidget,
)

from app.core import r_cell_store as r_store
from app.core.logger import get_logger
from app.core.r_analysis_metrics import cell_rollup, contour_area, detect_contour_mask
from app.core.zone_metrics import apply_manual_strokes
from app.widgets.icons import icon as svg_icon
from app.widgets.r_batch_result_dialog import RBatchResultDialog
from app.widgets.r_cell_panel import RCellPanel
from app.widgets.r_roi_canvas import RRoiCanvas
from app.widgets.r_settings_panel import RSettingsPanel
from app.widgets.r_step_indicator import RStepIndicator

log = get_logger(__name__)

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


def _default_session() -> dict:
    return {
        "version": 1, "cells": {}, "global_roi": None,
        "threshold": 128, "denominator": 0.0, "spec_lower": 0.0, "spec_upper": 0.0,
    }


def _default_image_data() -> dict:
    return {"roi_override": None, "manual_strokes": [], "area": 0}


class _RDetectWorker(QThread):
    """여러 이미지를 cv2로 순차 검출하는 단일 워커 — 스펙 명시대로 Zone 탭의
    2-워커 CUDA 분리 구조는 불필요(여기엔 CUDA 추론이 없음, AI 모델 아님).
    run() 안에서만 cv2/numpy 연산을 하고 결과는 Signal로만 내보낸다."""

    image_done = pyqtSignal(str, int)     # path, area
    progress = pyqtSignal(int, int)        # done, total

    def __init__(self, jobs: list[tuple[Path, tuple[int, int, int, int], list]], threshold: int) -> None:
        super().__init__()
        self._jobs = jobs
        self._threshold = threshold

    def run(self) -> None:
        total = len(self._jobs)
        for done, (path, roi, manual_strokes) in enumerate(self._jobs, 1):
            if self.isInterruptionRequested():
                break
            try:
                img = cv2.imread(str(path))
                if img is not None:
                    mask = detect_contour_mask(img, roi, self._threshold)
                    if manual_strokes:
                        mask = apply_manual_strokes(mask, manual_strokes)
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

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(500)
        self._save_timer.timeout.connect(self._do_save)

        self._build_ui()
        self._refresh_settings_summary()
        self._refresh_right_panel()
        self._refresh_step_indicator()

    # ── UI 구성 ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        self._step_indicator = RStepIndicator()
        root.addWidget(self._step_indicator)

        session_row = QHBoxLayout()
        session_row.addWidget(QLabel("세션 파일:"))
        self._lbl_session_path = QLabel("미지정 — 저장하려면 선택하세요")
        self._lbl_session_path.setStyleSheet("color:#9ca3af;font-size:11px;")
        session_row.addWidget(self._lbl_session_path, stretch=1)
        self._btn_session = QPushButton("세션 열기/새로 만들기...")
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
        card_layout.addWidget(QLabel("검사 설정 요약"))
        self._lbl_settings_summary = QLabel("")
        self._lbl_settings_summary.setWordWrap(True)
        self._lbl_settings_summary.setStyleSheet("color:#9ca3af;font-size:11px;")
        card_layout.addWidget(self._lbl_settings_summary)
        layout.addWidget(card)

        btn_settings = QPushButton("검사 설정 열기/조정...")
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
        self._tool_group = QActionGroup(self)
        self._tool_group.setExclusive(True)

        def tool_action(icon_name: str, tip: str, mode: str) -> QAction:
            action = QAction(svg_icon(icon_name), "", self)
            action.setToolTip(tip)
            action.setCheckable(True)
            action.setData(mode)
            self._tool_group.addAction(action)
            toolbar.addAction(action)
            return action

        act_roi = tool_action("tool_select", "ROI 편집(사각형 생성/이동/리사이즈)", "roi")
        tool_action("tool_brush", "브러시로 영역 그리기", "brush_draw")
        tool_action("tool_eraser", "브러시로 영역 지우기", "brush_erase")
        tool_action("tool_pan", "화면 이동", "pan")
        act_roi.setChecked(True)
        self._tool_group.triggered.connect(self._on_tool_changed)
        layout.addWidget(toolbar)

        layout.addWidget(QLabel("브러시:"))
        brush_spin = QSpinBox()
        brush_spin.setRange(1, 200)
        brush_spin.setValue(30)
        brush_spin.setSuffix(" px")
        brush_spin.setFixedWidth(80)
        brush_spin.valueChanged.connect(self._canvas.set_erase_brush_size)
        layout.addWidget(brush_spin)

        self._btn_undo = QPushButton()
        self._btn_undo.setIcon(svg_icon("undo"))
        self._btn_undo.setToolTip("실행 취소 (Ctrl+Z)")
        self._btn_undo.setEnabled(False)
        self._btn_undo.clicked.connect(self._canvas.undo)
        layout.addWidget(self._btn_undo)

        self._edit_cluster = cluster

    def _build_run_cluster(self) -> None:
        cluster = QFrame(self._canvas)
        cluster.setStyleSheet(
            "background:rgba(31,35,41,215);border:1px solid #374151;border-radius:6px;"
        )
        layout = QHBoxLayout(cluster)
        layout.setContentsMargins(6, 4, 6, 4)

        btn_current = QPushButton("현재 이미지 검출")
        btn_current.clicked.connect(self._on_detect_current)
        layout.addWidget(btn_current)
        self._btn_detect_current = btn_current

        btn_cell = QPushButton("선택 셀 전체 일괄 검출")
        btn_cell.clicked.connect(self._on_detect_cell)
        layout.addWidget(btn_cell)
        self._btn_detect_cell = btn_cell

        btn_all = QPushButton("▶ 전체 셀 분석")
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

    def _build_right_panel(self) -> QWidget:
        right = QWidget()
        layout = QVBoxLayout(right)
        layout.setContentsMargins(4, 0, 0, 0)

        summary_card = QFrame()
        summary_card.setStyleSheet("background:#1f2329;border:1px solid #374151;border-radius:8px;")
        summary_layout = QVBoxLayout(summary_card)
        summary_layout.addWidget(QLabel("전체 셀 요약"))
        self._lbl_overall_summary = QLabel("합격 0  ·  불합격 0  ·  미검사 0  (전체 0셀)")
        self._lbl_overall_summary.setWordWrap(True)
        summary_layout.addWidget(self._lbl_overall_summary)
        layout.addWidget(summary_card)

        self._lbl_cell_title = QLabel("선택된 셀 없음")
        self._lbl_cell_title.setStyleSheet("color:#60a5fa;font-weight:bold;")
        layout.addWidget(self._lbl_cell_title)

        self._lbl_cell_badge = QLabel("-")
        self._lbl_cell_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_cell_badge.setStyleSheet(_BADGE_NONE)
        self._lbl_cell_badge.setFixedHeight(40)
        layout.addWidget(self._lbl_cell_badge)

        lbl_ref = QLabel("이미지별 면적(참고) — 개별 판정 없음")
        lbl_ref.setStyleSheet("color:#6b7280;font-size:10.5px;")
        layout.addWidget(lbl_ref)
        self._cell_image_table = QTableWidget(0, 2)
        self._cell_image_table.setHorizontalHeaderLabels(["이미지", "면적"])
        self._cell_image_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._cell_image_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self._cell_image_table, stretch=1)

        btn_view_all = QPushButton("전체 결과 보기 (Excel)")
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
        self._edit_cluster.setMaximumWidth(max(1, int(w * 0.42)))
        self._nav_cluster.setMaximumWidth(max(1, int(w * 0.46)))
        self._edit_cluster.adjustSize()
        self._nav_cluster.adjustSize()

        edit_right = margin + self._edit_cluster.width()
        nav_left = w - margin - self._nav_cluster.width()
        available_for_run = max(1, nav_left - margin - edit_right - margin)
        self._run_cluster.setMaximumWidth(available_for_run)
        self._run_cluster.adjustSize()

        self._edit_cluster.move(margin, margin)
        run_x = max(edit_right + margin, (w - self._run_cluster.width()) // 2)
        run_x = min(run_x, nav_left - margin - self._run_cluster.width())
        run_x = max(run_x, edit_right + margin)
        self._run_cluster.move(run_x, margin)
        self._nav_cluster.move(max(nav_left, run_x + self._run_cluster.width() + margin), margin)

    # ── 편집 도구 ────────────────────────────────────────────────────────────

    def _on_tool_changed(self, action: QAction) -> None:
        mode = action.data()
        if mode == "brush_draw":
            self._canvas.set_brush_draw_mode(True)
        elif mode == "brush_erase":
            self._canvas.set_brush_erase_mode(True)
        elif mode == "pan":
            self._canvas.set_pan_mode(True)
        else:
            # ponytail: RRoiCanvas엔 "roi 모드" 전용 setter가 없다 — set_X_mode(False)를
            # 아무거나 호출하면 _mode가 "roi"로 떨어지는 현재 구현을 그대로 이용한다
            # (캔버스에 4번째 setter를 새로 추가하는 건 과한 변경, 조립 단계 범위 밖).
            self._canvas.set_pan_mode(False)

    def _update_undo_button_state(self) -> None:
        self._btn_undo.setEnabled(self._canvas.can_undo())

    def _on_canvas_edited(self) -> None:
        """브러시 그리기/지우기 스트로크가 끝났을 때(erase_changed) — 수동 보정을
        세션 데이터에 반영하고 면적/판정을 재계산한다(요구사항 7)."""
        if self._current_image_path is None:
            return
        state = self._canvas.get_state()
        data = self._image_data(self._current_image_path)
        data["manual_strokes"] = state["manual_strokes"]
        eff = self._canvas.effective_mask()
        data["area"] = contour_area(eff) if eff is not None else 0
        self._refresh_right_panel()
        self._refresh_step_indicator()
        self._schedule_autosave()

    # ── 세션 파일 ────────────────────────────────────────────────────────────

    def _on_open_session(self) -> None:
        path_str, _ = QFileDialog.getSaveFileName(
            self, "세션 파일 열기/새로 만들기", "r_session.json", "JSON (*.json)",
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
                }
            cells[cell_id] = paths
        self._cells = cells
        self._cell_panel.set_cells(cells)

        self._settings_dialog.set_threshold(self._session.get("threshold", 128))
        self._settings_dialog.set_denominator(self._session.get("denominator", 0.0))
        self._settings_dialog.set_spec_lower(self._session.get("spec_lower", 0.0))
        self._settings_dialog.set_spec_upper(self._session.get("spec_upper", 0.0))

        self._current_cell = None
        self._current_image_path = None
        self._canvas.clear()
        self._lbl_session_path.setText(str(path))
        self._lbl_session_path.setStyleSheet("color:#e5e7eb;font-size:11px;")
        self._refresh_settings_summary()
        self._refresh_right_panel()
        self._refresh_step_indicator()

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

    def _effective_roi(self, path: Path) -> tuple[int, int, int, int] | None:
        data = self._image_data(path)
        if data.get("roi_override"):
            return tuple(data["roi_override"])
        gr = self._session.get("global_roi")
        return tuple(gr) if gr else None

    # ── 셀 패널 연동 ─────────────────────────────────────────────────────────

    def _on_cell_selected(self, cell_id: str) -> None:
        self._current_cell = cell_id
        self._refresh_thumb_strip()
        self._refresh_right_panel()

    def _on_cells_changed(self) -> None:
        self._cells = self._cell_panel.get_cells()
        self._refresh_thumb_strip()
        self._refresh_right_panel()
        self._refresh_step_indicator()
        self._schedule_autosave()

    # ── 현재 이미지(캔버스/좌측 목록/썸네일/네비게이션 공유 상태) ─────────────

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
        img = cv2.imread(str(path))
        pixmap = QPixmap(str(path))
        if img is not None:
            h, w = img.shape[:2]
        else:
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
            })
            if img is not None and roi is not None:
                mask = detect_contour_mask(img, roi, self._settings_dialog.threshold())
                self._canvas.set_detected_mask(mask)
            else:
                self._canvas.set_detected_mask(None)
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
        if self._current_image_path is not None:
            self._run_and_display_detection(self._current_image_path)
        self._refresh_settings_summary()
        self._refresh_right_panel()
        self._schedule_autosave()

    def _on_roi_global_requested(self) -> None:
        roi = self._canvas.get_roi()
        if roi is None:
            QMessageBox.warning(self._settings_dialog, "ROI 없음", "먼저 캔버스에서 ROI를 지정하세요.")
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
            QMessageBox.warning(self._settings_dialog, "이미지 없음", "먼저 이미지를 선택하세요.")
            return
        roi = self._canvas.get_roi()
        if roi is None:
            QMessageBox.warning(self._settings_dialog, "ROI 없음", "먼저 캔버스에서 ROI를 지정하세요.")
            return
        self._image_data(self._current_image_path)["roi_override"] = [roi.x(), roi.y(), roi.width(), roi.height()]
        self._run_and_display_detection(self._current_image_path)
        self._refresh_settings_summary()
        self._refresh_right_panel()
        self._refresh_step_indicator()
        self._schedule_autosave()

    def _refresh_settings_summary(self) -> None:
        s = self._session
        roi_desc = "전역 ROI 지정됨" if s.get("global_roi") else "ROI 미지정"
        override_n = sum(1 for d in self._image_data_map.values() if d.get("roi_override"))
        if override_n:
            roi_desc += f" (개별 보정 {override_n}장)"
        self._lbl_settings_summary.setText(
            f"Threshold: {s.get('threshold', 128)}\n"
            f"분모: {s.get('denominator', 0.0):g}\n"
            f"스펙: {s.get('spec_lower', 0.0):g} ~ {s.get('spec_upper', 0.0):g}\n"
            f"{roi_desc}"
        )

    # ── 검출 실행(3단계) ─────────────────────────────────────────────────────

    def _run_and_display_detection(self, path: Path) -> None:
        img = cv2.imread(str(path))
        roi = self._effective_roi(path)
        if img is None or roi is None:
            self._canvas.set_detected_mask(None)
            return
        mask = detect_contour_mask(img, roi, self._settings_dialog.threshold())
        self._canvas.set_detected_mask(mask)
        eff = self._canvas.effective_mask()
        self._image_data(path)["area"] = contour_area(eff) if eff is not None else 0

    def _on_detect_current(self) -> None:
        if self._current_image_path is None:
            QMessageBox.information(self, "이미지 없음", "먼저 이미지를 선택하세요.")
            return
        self._run_and_display_detection(self._current_image_path)
        self._refresh_right_panel()
        self._refresh_step_indicator()
        self._schedule_autosave()

    def _on_detect_cell(self) -> None:
        if self._current_cell is None:
            QMessageBox.information(self, "셀 없음", "먼저 좌측에서 셀을 선택하세요.")
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
            QMessageBox.information(self, "이미지 없음", "검출할 이미지가 없습니다.")
            return
        jobs = []
        for p in paths:
            roi = self._effective_roi(p)
            if roi is not None:
                jobs.append((p, roi, self._image_data(p).get("manual_strokes", [])))
        if not jobs:
            QMessageBox.information(self, "ROI 없음", "ROI가 지정된 이미지가 없습니다.")
            return

        self._set_detect_buttons_enabled(False)
        self._progress = QProgressDialog("검출 중...", "취소", 0, len(jobs), self)
        self._progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._detect_worker = _RDetectWorker(jobs, self._settings_dialog.threshold())
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

    def _on_detect_image_done(self, path_str: str, area: int) -> None:
        self._image_data_map.setdefault(path_str, _default_image_data())["area"] = area

    def _on_batch_detect_finished(self) -> None:
        if self._progress is not None:
            self._progress.close()
            self._progress = None
        self._set_detect_buttons_enabled(True)
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
            f"합격 {passed}  ·  불합격 {failed}  ·  미검사 {untested}  (전체 {len(self._cells)}셀)"
        )

    def _refresh_current_cell_block(self) -> None:
        cell_id = self._cell_panel.selected_cell()
        if cell_id is None:
            self._lbl_cell_title.setText("선택된 셀 없음")
            self._lbl_cell_badge.setText("-")
            self._lbl_cell_badge.setStyleSheet(_BADGE_NONE)
            self._cell_image_table.setRowCount(0)
            return
        rollup = self._cell_rollup(cell_id)
        self._lbl_cell_title.setText(f"현재 선택된 셀 — {cell_id}")
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
            self._lbl_cell_badge.setText(f"미검사  (R={ratio_txt})")
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

    print("r_analysis_tab self-check OK")
