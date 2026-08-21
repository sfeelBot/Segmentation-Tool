from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QLabel, QComboBox, QSpinBox,
    QFileDialog, QMessageBox, QTableWidget,
    QTableWidgetItem, QGroupBox, QSplitter, QHeaderView,
    QApplication,
)
from PyQt6.QtGui import QColor
from PyQt6.QtCore import Qt, QSize

from app.widgets.icons import icon as svg_icon

from app.core import inference_engine as engine
from app.core.inference_engine import (
    InferenceResult, list_checkpoints, load_checkpoint_meta, CheckpointMeta,
    load_model_from_ckpt, model_source_label,
)
from app.core.logger import get_logger
from app.core.device_info import prompt_gpu_availability
from app.widgets.overlay_viewer import OverlayViewerPanel
from app.widgets.inference_image_list import InferenceImageList

log = get_logger(__name__)

_SPLITTER_STYLE = (
    "QSplitter::handle { background:#374151; }"
    "QSplitter::handle:hover { background:#60a5fa; }"
)


class InferenceTab(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._image_path: Path | None = None
        self._last_result: InferenceResult | None = None
        self._ckpt_metas: list[CheckpointMeta] = []
        self._auto_model = None   # 체크포인트 선택 시 자동으로 결정된 모델
        self._build_ui()

    # ── UI 구성 ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(6)

        # ── 상단↔뷰어 서브스플리터 ────────────────────────────────────────────
        outer_splitter = QSplitter(Qt.Orientation.Vertical)
        outer_splitter.setChildrenCollapsible(False)
        outer_splitter.setHandleWidth(5)
        outer_splitter.setStyleSheet(_SPLITTER_STYLE)

        # ── 상단 영역 (파일 컨트롤 + 추론 방식 + 체크포인트 테이블) ────────────
        top_widget = QWidget()
        top_widget.setMinimumHeight(140)
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(6)

        ctrl = QHBoxLayout()
        self._btn_file = QPushButton("파일 선택…")
        self._btn_folder = QPushButton("폴더 선택…")
        ctrl.addWidget(self._btn_file)
        ctrl.addWidget(self._btn_folder)

        self._lbl_count = QLabel("")
        self._lbl_count.setStyleSheet("color:#9ca3af; min-width:80px;")
        ctrl.addWidget(self._lbl_count)

        ctrl.addStretch()

        self._btn_run = QPushButton("▶  추론 실행")
        self._btn_run.setStyleSheet("font-weight:bold; padding:4px 12px;")
        ctrl.addWidget(self._btn_run)
        top_layout.addLayout(ctrl)

        # ── 추론 방식 ─────────────────────────────────────────────────────────
        infer_mode_row = QHBoxLayout()
        infer_mode_row.addWidget(QLabel("추론 방식:"))
        self._infer_mode = QComboBox()
        self._infer_mode.addItem("resize        (전체 이미지 축소)", "resize")
        self._infer_mode.addItem("sliding_window (패치 학습 모델용, 원본 해상도)", "sliding_window")
        self._infer_mode.setToolTip(
            "resize: 이미지 전체를 학습 크기로 줄여서 한 번에 추론\n"
            "sliding_window: 원본 해상도로 패치를 겹쳐가며 추론 후 병합\n"
            "  → random_crop 으로 학습한 모델엔 sliding_window 권장"
        )
        infer_mode_row.addWidget(self._infer_mode, stretch=1)
        infer_mode_row.addWidget(QLabel("오버랩:"))
        self._overlap_spin = QSpinBox()
        self._overlap_spin.setRange(0, 256)
        self._overlap_spin.setValue(64)
        self._overlap_spin.setSuffix(" px")
        self._overlap_spin.setFixedWidth(80)
        self._overlap_spin.setToolTip("패치 간 겹치는 픽셀 수 (sliding_window 모드)")
        infer_mode_row.addWidget(self._overlap_spin)
        top_layout.addLayout(infer_mode_row)

        # ── 체크포인트 테이블 ──────────────────────────────────────────────────
        ckpt_header = QHBoxLayout()
        ckpt_header.addWidget(QLabel("체크포인트 선택"))
        ckpt_header.addStretch()
        self._btn_refresh = QPushButton("↺ 새로고침")
        self._btn_refresh.setFixedWidth(80)
        ckpt_header.addWidget(self._btn_refresh)
        top_layout.addLayout(ckpt_header)

        self._ckpt_table = QTableWidget(0, 5)
        self._ckpt_table.setHorizontalHeaderLabels(
            ["파일명", "모델", "Epoch", "Val Loss", "IoU"]
        )
        self._ckpt_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._ckpt_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._ckpt_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        hdr = self._ckpt_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        top_layout.addWidget(self._ckpt_table, stretch=1)

        # 선택된 체크포인트의 모델 정보 표시
        self._lbl_model_info = QLabel("— 체크포인트를 선택하세요")
        self._lbl_model_info.setStyleSheet(
            "color:#9ca3af; font-size:11px; padding:2px 4px;"
            "background:#1a1d23; border-radius:3px;"
        )
        top_layout.addWidget(self._lbl_model_info)

        outer_splitter.addWidget(top_widget)

        # ── 메인 영역 (이미지 목록 | 뷰어 | 범례) ────────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(5)
        splitter.setStyleSheet(_SPLITTER_STYLE)
        splitter.setMinimumHeight(200)

        # 이미지 목록 (폴더 선택 시 표시)
        self._list_panel = QWidget()
        list_layout = QVBoxLayout(self._list_panel)
        list_layout.setContentsMargins(0, 0, 0, 0)
        self._img_list = InferenceImageList()
        list_layout.addWidget(self._img_list, stretch=1)

        # 이동 버튼
        nav = QHBoxLayout()
        self._btn_prev = QPushButton("◀ 이전")
        self._btn_next = QPushButton("다음 ▶")
        self._lbl_nav = QLabel("0 / 0")
        self._lbl_nav.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nav.addWidget(self._btn_prev)
        nav.addWidget(self._lbl_nav, stretch=1)
        nav.addWidget(self._btn_next)
        list_layout.addLayout(nav)

        self._list_panel.setMinimumWidth(140)
        self._list_panel.hide()   # 단일 파일 모드에선 숨김
        splitter.addWidget(self._list_panel)

        # 뷰어
        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        filename_row = QHBoxLayout()
        filename_row.setContentsMargins(0, 0, 0, 0)
        self._lbl_filename = QLabel("선택된 이미지 없음")
        self._lbl_filename.setStyleSheet("color:#9ca3af; padding:2px 4px;")
        filename_row.addWidget(self._lbl_filename)

        self._btn_copy_filename = QPushButton()
        self._btn_copy_filename.setIcon(svg_icon("clipboard"))
        self._btn_copy_filename.setIconSize(QSize(14, 14))
        self._btn_copy_filename.setFixedSize(22, 22)
        self._btn_copy_filename.setFlat(True)
        self._btn_copy_filename.setToolTip("파일명 복사")
        self._btn_copy_filename.setStyleSheet("QPushButton{border:none;padding:0;}")
        self._btn_copy_filename.clicked.connect(self._on_copy_filename)
        filename_row.addWidget(self._btn_copy_filename)
        filename_row.addStretch()
        center_layout.addLayout(filename_row)
        self._viewer_panel = OverlayViewerPanel()
        center_layout.addWidget(self._viewer_panel, stretch=1)
        splitter.addWidget(center)

        # 범례
        right = QWidget()
        right.setMinimumWidth(160)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(4, 0, 4, 0)
        legend_box = QGroupBox("클래스 범례")
        legend_inner = QVBoxLayout(legend_box)
        self._legend_table = QTableWidget(0, 3)
        self._legend_table.setHorizontalHeaderLabels(["색상", "클래스", "비율(%)"])
        self._legend_table.horizontalHeader().setStretchLastSection(True)
        self._legend_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._legend_table.setColumnWidth(0, 32)
        self._legend_table.setColumnWidth(1, 80)
        legend_inner.addWidget(self._legend_table)
        right_layout.addWidget(legend_box)
        right_layout.addStretch()
        splitter.addWidget(right)

        splitter.setStretchFactor(1, 1)
        outer_splitter.addWidget(splitter)

        outer_splitter.setSizes([300, 10000])   # 기존 stretch 비율 재현(상단 고정폭 상당, 메인 영역 우선)
        outer_splitter.setStretchFactor(0, 0)
        outer_splitter.setStretchFactor(1, 1)
        root.addWidget(outer_splitter, stretch=1)

        # ── 시그널 연결 ───────────────────────────────────────────────────────
        self._btn_refresh.clicked.connect(self._refresh_checkpoints)
        self._btn_file.clicked.connect(self._on_select_file)
        self._btn_folder.clicked.connect(self._on_select_folder)
        self._btn_run.clicked.connect(self._on_run)
        self._btn_prev.clicked.connect(self._on_prev)
        self._btn_next.clicked.connect(self._on_next)
        self._img_list.image_selected.connect(self._on_image_selected)
        self._img_list.display_changed.connect(self._update_nav_label)
        self._viewer_panel.opacity_changed.connect(self._on_opacity_changed)
        self._ckpt_table.doubleClicked.connect(lambda: self._on_run())
        # 체크포인트 선택 → 즉시 모델 결정
        self._ckpt_table.selectionModel().selectionChanged.connect(
            lambda *_: self._on_ckpt_selected()
        )

        self._refresh_checkpoints()

    # ── 슬롯 — 이미지 선택 ───────────────────────────────────────────────────

    def _on_select_file(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "이미지 선택", "",
            "Images (*.jpg *.jpeg *.png *.bmp *.tiff *.tif)"
        )
        if not paths:
            return
        self._img_list.load_files([Path(p) for p in paths])
        self._after_load()

    def _on_select_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "폴더 선택")
        if not folder:
            return
        self._img_list.load_folder(Path(folder))
        if self._img_list.count() == 0:
            QMessageBox.information(self, "이미지 없음",
                "선택한 폴더(하위 폴더 포함)에 지원되는 이미지가 없습니다.")
            return
        self._after_load()

    def _after_load(self) -> None:
        count = self._img_list.count()
        self._list_panel.setVisible(count > 1)
        self._lbl_count.setText(f"{count}개 이미지")
        self._update_nav_label()

    def _on_image_selected(self, path: Path) -> None:
        self._image_path = path
        self._lbl_filename.setText(path.name)
        self._lbl_filename.setStyleSheet("color:#e5e7eb; padding:2px 4px;")
        self._update_nav_label()

    def _on_copy_filename(self) -> None:
        if self._image_path is None:
            return
        QApplication.clipboard().setText(self._image_path.name)

    def _update_nav_label(self) -> None:
        idx = self._img_list.current_display_index()
        total = self._img_list.count()
        self._lbl_nav.setText(f"{idx + 1} / {total}" if idx >= 0 else f"0 / {total}")

    def _on_prev(self) -> None:
        self._img_list.navigate(-1)

    def _on_next(self) -> None:
        self._img_list.navigate(1)

    # ── 슬롯 — 체크포인트 선택 ──────────────────────────────────────────────

    def _on_ckpt_selected(self) -> None:
        """체크포인트를 선택할 때 model_source 를 읽어 모델을 즉시 결정."""
        self._auto_model = None
        ckpt_path = self._get_selected_ckpt()
        if ckpt_path is None:
            self._lbl_model_info.setText("— 체크포인트를 선택하세요")
            self._lbl_model_info.setStyleSheet(
                "color:#9ca3af; font-size:11px; padding:2px 4px;"
            )
            return

        idx = self._ckpt_table.selectionModel().selectedRows()[0].row()
        meta = self._ckpt_metas[idx] if 0 <= idx < len(self._ckpt_metas) else None
        source = meta.model_source if meta else ""
        model_label = model_source_label(source)

        if source.startswith("preset:"):
            # 프리셋 모델 → 즉시 인스턴스화
            model = load_model_from_ckpt(ckpt_path)
            if model is not None:
                self._auto_model = model
                self._lbl_model_info.setText(f"{model_label}  (자동 준비됨)")
                self._lbl_model_info.setStyleSheet(
                    "color:#34d399; font-size:11px; padding:2px 4px;"
                )
                log.info(f"추론 모델 자동 설정: {model_label}  ({ckpt_path.name})")
            else:
                self._lbl_model_info.setText(f"{model_label} 프리셋 로드 실패")
                self._lbl_model_info.setStyleSheet(
                    "color:#f87171; font-size:11px; padding:2px 4px;"
                )
        elif source == "loaded":
            # 사용자가 Model 탭에서 직접 로드한 모델 → Model 탭 필요
            self._lbl_model_info.setText(
                f"{model_label}  —  Model 탭에 같은 모델이 로드되어 있어야 합니다"
            )
            self._lbl_model_info.setStyleSheet(
                "color:#fbbf24; font-size:11px; padding:2px 4px;"
            )
        else:
            # 구형 체크포인트 (model_source 정보 없음)
            self._lbl_model_info.setText(
                "모델 정보 없는 체크포인트 — Model 탭에서 모델을 로드해 주세요"
            )
            self._lbl_model_info.setStyleSheet(
                "color:#fbbf24; font-size:11px; padding:2px 4px;"
            )

    # ── 슬롯 — 추론 ──────────────────────────────────────────────────────────

    def _on_run(self) -> None:
        if self._image_path is None:
            QMessageBox.warning(self, "이미지 없음", "이미지를 선택하세요.")
            return
        ckpt_path: Path | None = self._get_selected_ckpt()
        if ckpt_path is None:
            QMessageBox.warning(self, "체크포인트 없음",
                "학습을 완료하거나 체크포인트를 선택하세요.")
            return

        # 모델: 체크포인트 선택 시 이미 결정된 _auto_model 우선
        # "loaded" 타입이면 Model 탭에서 직접 제공해야 함
        model = self._auto_model or self._get_model()
        if model is None:
            QMessageBox.warning(self, "모델 없음",
                "이 체크포인트는 Model 탭에서 직접 로드한 아키텍처로 학습됐습니다.\n"
                "Model 탭에서 같은 모델 코드를 로드한 뒤 다시 시도하세요.")
            return

        if not prompt_gpu_availability(self, "추론"):
            return

        self._btn_run.setEnabled(False)
        self._btn_run.setText("추론 중…")
        try:
            mode = self._infer_mode.currentData()
            if mode == "sliding_window":
                result = engine.run_sliding_window(
                    model           = model,
                    image_path      = self._image_path,
                    checkpoint_path = ckpt_path,
                    overlap         = self._overlap_spin.value(),
                    opacity         = self._viewer_panel.opacity,
                )
            else:
                result = engine.run(
                    model           = model,
                    image_path      = self._image_path,
                    checkpoint_path = ckpt_path,
                    opacity         = self._viewer_panel.opacity,
                )
            self._last_result = result
            self._viewer_panel.viewer.set_pixmap(result.overlay_pixmap)
            self._update_legend(result)
        except Exception as exc:
            log.exception(f"추론 실패 — image={self._image_path}, ckpt={ckpt_path}")
            QMessageBox.critical(self, "추론 오류", str(exc))
        finally:
            self._btn_run.setEnabled(True)
            self._btn_run.setText("▶  추론 실행")

    def _on_opacity_changed(self, opacity: float) -> None:
        if self._image_path is None:
            return
        ckpt_path: Path | None = self._get_selected_ckpt()
        model = self._auto_model or self._get_model()
        if ckpt_path is None or model is None:
            return
        try:
            result = engine.run(
                model           = model,
                image_path      = self._image_path,
                checkpoint_path = ckpt_path,
                opacity         = opacity,
            )
            self._last_result = result
            self._viewer_panel.viewer.set_pixmap(result.overlay_pixmap)
        except Exception:
            pass

    # ── 슬롯 — 체크포인트 ────────────────────────────────────────────────────

    def _refresh_checkpoints(self) -> None:
        self._ckpt_metas = [
            load_checkpoint_meta(p) for p in list_checkpoints()
        ]
        self._ckpt_table.setRowCount(0)
        for meta in self._ckpt_metas:
            row = self._ckpt_table.rowCount()
            self._ckpt_table.insertRow(row)
            self._ckpt_table.setItem(row, 0, QTableWidgetItem(meta.path.name))
            self._ckpt_table.setItem(row, 1, QTableWidgetItem(
                model_source_label(meta.model_source)
            ))
            self._ckpt_table.setItem(row, 2, QTableWidgetItem(
                str(meta.epoch) if meta.epoch else "—"
            ))
            self._ckpt_table.setItem(row, 3, QTableWidgetItem(
                f"{meta.val_loss:.4f}" if meta.val_loss == meta.val_loss else "—"
            ))
            self._ckpt_table.setItem(row, 4, QTableWidgetItem(
                f"{meta.mean_iou:.4f}" if meta.mean_iou == meta.mean_iou else "—"
            ))
        # 가장 최근 체크포인트 자동 선택
        if self._ckpt_metas:
            self._ckpt_table.selectRow(len(self._ckpt_metas) - 1)

    def _get_selected_ckpt(self) -> Path | None:
        rows = self._ckpt_table.selectionModel().selectedRows()
        if not rows:
            return None
        idx = rows[0].row()
        if 0 <= idx < len(self._ckpt_metas):
            return self._ckpt_metas[idx].path
        return None

    # ── 내부 ─────────────────────────────────────────────────────────────────

    def _update_legend(self, result: InferenceResult) -> None:
        self._legend_table.setRowCount(0)
        for stat in result.class_stats:
            row = self._legend_table.rowCount()
            self._legend_table.insertRow(row)
            color_item = QTableWidgetItem()
            color_item.setBackground(QColor(*stat.color))
            self._legend_table.setItem(row, 0, color_item)
            self._legend_table.setItem(row, 1, QTableWidgetItem(stat.name))
            self._legend_table.setItem(row, 2, QTableWidgetItem(f"{stat.pixel_pct:.1f}"))

    def _get_model(self):
        win = self.window()
        if hasattr(win, "_model_tab"):
            return win._model_tab.loaded_model
        return None
