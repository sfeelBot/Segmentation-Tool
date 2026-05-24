from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout,
    QToolBar, QLabel, QSpinBox, QMessageBox,
    QListWidget, QListWidgetItem, QGroupBox,
    QPushButton, QButtonGroup,
)
from PyQt6.QtGui import QAction, QColor, QKeySequence, QShortcut, QFont
from PyQt6.QtCore import Qt, pyqtSignal

from app.widgets.annotation_canvas import (
    AnnotationCanvas,
    TOOL_POLYGON, TOOL_BRUSH, TOOL_BRUSH_FILL, TOOL_ERASER, TOOL_ERASER_FLOOD,
    TOOL_SELECT, TOOL_PAN,
)
from app.widgets.class_panel import ClassPanel
from app.widgets.image_browser import ImageBrowser
from app.widgets.auto_label_dialog import AutoLabelDialog
from app.widgets.log_panel import LogPanel
from app.core.i18n import t
from app.core.logger import get_logger

log = get_logger(__name__)


class LabelingTab(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._ann_list_updating = False   # 재진입 방지 플래그
        self._build_ui()
        self._connect_signals()

    # ── UI 구성 ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── 왼쪽: 이미지 브라우저 + 클래스 패널 (200px) ──────────────────────
        self._left_panel = QWidget()
        self._left_panel.setFixedWidth(200)
        left_layout = QVBoxLayout(self._left_panel)
        left_layout.setContentsMargins(4, 4, 4, 4)
        left_layout.setSpacing(6)

        self._image_browser = ImageBrowser()
        self._class_panel = ClassPanel()

        left_layout.addWidget(self._image_browser, stretch=3)
        left_layout.addWidget(self._class_panel, stretch=2)

        # ── 가운데: 툴바 + 캔버스 + 상태바 (stretch) ─────────────────────────
        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)

        self._canvas = AnnotationCanvas()
        center_layout.addWidget(self._build_toolbar())
        center_layout.addWidget(self._canvas)
        center_layout.addWidget(self._build_channel_strip())

        # ── 오른쪽: 어노테이션 목록 (180px) ─────────────────────────────────
        self._right_panel = QWidget()
        self._right_panel.setFixedWidth(180)
        right_layout = QVBoxLayout(self._right_panel)
        right_layout.setContentsMargins(4, 4, 4, 4)
        right_layout.setSpacing(4)

        ann_box = QGroupBox(t("labeling.ann_list"))
        ann_box_layout = QVBoxLayout(ann_box)
        ann_box_layout.setContentsMargins(4, 4, 4, 4)

        self._ann_list = QListWidget()
        self._ann_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        ann_box_layout.addWidget(self._ann_list)

        self._lbl_sel_hint = QLabel(t("labeling.sel_hint"))
        self._lbl_sel_hint.setStyleSheet("color:#888; font-size:10px;")
        self._lbl_sel_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_sel_hint.hide()
        ann_box_layout.addWidget(self._lbl_sel_hint)

        right_layout.addWidget(ann_box, stretch=2)

        # 어노테이션 목록 밑에 로그 패널
        self._log_panel = LogPanel()
        right_layout.addWidget(self._log_panel, stretch=3)

        root.addWidget(self._left_panel)
        root.addWidget(center, stretch=1)
        root.addWidget(self._right_panel)

    def _build_channel_strip(self) -> QWidget:
        """캔버스 하단 — 채널 토글 + 픽셀 값 표시 (초소형 스트립)."""
        strip = QWidget()
        strip.setFixedHeight(20)
        strip.setStyleSheet("background:#1a1d23; border-top:1px solid #374151;")
        lay = QHBoxLayout(strip)
        lay.setContentsMargins(6, 0, 6, 0)
        lay.setSpacing(3)

        small_font = QFont()
        small_font.setPointSize(8)
        btn_style = (
            "QPushButton{font-size:8px;padding:1px 5px;border:1px solid #4b5563;"
            "border-radius:3px;background:#1f2329;color:#9ca3af;}"
            "QPushButton:checked{background:#1e3a5f;color:#60a5fa;border-color:#60a5fa;}"
        )

        self._ch_group = QButtonGroup(self)
        self._ch_group.setExclusive(True)
        for label, ch, tip in [
            (t("labeling.ch_orig"), 0, t("labeling.ch_orig.tip")),
            (t("labeling.ch_r"),    1, t("labeling.ch_r.tip")),
            (t("labeling.ch_g"),    2, t("labeling.ch_g.tip")),
            (t("labeling.ch_b"),    3, t("labeling.ch_b.tip")),
        ]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setFixedHeight(16)
            btn.setFont(small_font)
            btn.setStyleSheet(btn_style)
            btn.setToolTip(tip)
            self._ch_group.addButton(btn, ch)
            lay.addWidget(btn)
        self._ch_group.button(0).setChecked(True)
        self._ch_group.idClicked.connect(self._canvas.set_channel)

        lay.addStretch()

        self._lbl_pixel = QLabel("—")
        self._lbl_pixel.setFont(small_font)
        self._lbl_pixel.setStyleSheet(
            "font-family:Consolas,'Courier New',monospace;"
            "font-size:9px; color:#6b7280;"
        )
        lay.addWidget(self._lbl_pixel)

        return strip

    def _build_toolbar(self) -> QToolBar:
        tb = QToolBar()
        tb.setMovable(False)

        def tool_action(emoji: str, tool: str, tip_key: str) -> QAction:
            act = QAction(emoji, self)
            act.setToolTip(t(tip_key))
            act.setCheckable(True)
            act.triggered.connect(lambda: self._set_tool(tool))
            return act

        self._act_polygon      = tool_action("📐", TOOL_POLYGON,      "tool.polygon.tip")
        self._act_brush        = tool_action("🖌",  TOOL_BRUSH,        "tool.brush.tip")
        self._act_brush_fill   = tool_action("🪣", TOOL_BRUSH_FILL,   "tool.brush_fill.tip")
        self._act_eraser       = tool_action("🧹", TOOL_ERASER,       "tool.eraser.tip")
        self._act_eraser_flood = tool_action("🧲", TOOL_ERASER_FLOOD, "tool.eraser_flood.tip")
        self._act_select       = tool_action("🔲", TOOL_SELECT,       "tool.select.tip")
        self._act_pan          = tool_action("✋", TOOL_PAN,          "tool.pan.tip")

        for act in (self._act_polygon, self._act_brush, self._act_brush_fill,
                    self._act_eraser, self._act_eraser_flood,
                    self._act_select, self._act_pan):
            tb.addAction(act)
        self._act_polygon.setChecked(True)

        # 툴바 버튼 스타일 — 이모지를 크게 표시
        tb.setStyleSheet(
            "QToolBar QToolButton { font-size:16px; min-width:36px; min-height:30px; padding:2px 6px; }"
        )

        tb.addSeparator()

        tb.addWidget(QLabel(t("tool.brush_size")))
        self._spin_brush = QSpinBox()
        self._spin_brush.setRange(1, 200)
        self._spin_brush.setValue(20)
        self._spin_brush.setFixedWidth(60)
        self._spin_brush.valueChanged.connect(self._canvas.set_brush_size)
        tb.addWidget(self._spin_brush)

        tb.addSeparator()

        act_undo = QAction("↶", self)
        act_undo.setToolTip(t("tool.undo.tip"))
        act_undo.setShortcut("Ctrl+Z")
        act_undo.triggered.connect(self._canvas.undo)
        tb.addAction(act_undo)

        act_clear = QAction("🗑", self)
        act_clear.setToolTip(t("tool.clear.tip"))
        act_clear.triggered.connect(self._on_clear_all)
        tb.addAction(act_clear)

        self._act_ann_visible = QAction("👁", self)
        self._act_ann_visible.setCheckable(True)
        self._act_ann_visible.setChecked(True)
        self._act_ann_visible.setToolTip(t("sc.ann_visible") + " [F]")
        self._act_ann_visible.toggled.connect(
            lambda checked: self._canvas.toggle_overlay_visible()
        )
        tb.addAction(self._act_ann_visible)

        tb.addSeparator()

        self._act_ok = QAction("✅", self)
        self._act_ok.setCheckable(True)
        self._act_ok.setToolTip(t("tool.ok.tip"))
        self._act_ok.triggered.connect(self._on_toggle_ok)
        tb.addAction(self._act_ok)

        tb.addSeparator()

        act_auto = QAction("✨", self)
        act_auto.setToolTip(t("tool.auto.tip"))
        act_auto.triggered.connect(self._on_auto_label)
        tb.addAction(act_auto)

        tb.addSeparator()

        self._act_fullscreen = QAction("🔳", self)
        self._act_fullscreen.setCheckable(True)
        self._act_fullscreen.setToolTip(t("tool.fullscreen.tip"))
        self._act_fullscreen.setShortcut(QKeySequence(Qt.Key.Key_T))
        self._act_fullscreen.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._act_fullscreen.toggled.connect(self._on_toggle_fullscreen)
        tb.addAction(self._act_fullscreen)
        self.addAction(self._act_fullscreen)

        return tb

    # ── 시그널 연결 ───────────────────────────────────────────────────────────

    def _connect_signals(self) -> None:
        self._image_browser.image_selected.connect(self._on_image_selected)
        self._image_browser.image_deleted.connect(self._on_image_deleted)
        self._class_panel.class_selected.connect(self._on_class_selected)
        self._canvas.annotation_saved.connect(self._on_annotation_saved)
        self._canvas.selection_changed.connect(self._on_canvas_selection_changed)
        self._ann_list.itemSelectionChanged.connect(self._on_ann_list_selection_changed)
        self._canvas.pixel_hovered.connect(self._on_pixel_hovered)

        # Delete 키는 캔버스 포커스 여부와 무관하게 동작
        del_sc = QShortcut(QKeySequence(Qt.Key.Key_Delete), self)
        del_sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        del_sc.activated.connect(self._on_delete_selected)

        # 이미지 이동 단축키 (캔버스 포커스일 때도 동작)
        for key in (Qt.Key.Key_PageUp,):
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(lambda: self._go_image(-1))
        for key in (Qt.Key.Key_PageDown,):
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(lambda: self._go_image(+1))

    # ── 슬롯 ─────────────────────────────────────────────────────────────────

    def _set_tool(self, tool: str) -> None:
        for act, t in [
            (self._act_polygon,      TOOL_POLYGON),
            (self._act_brush,        TOOL_BRUSH),
            (self._act_brush_fill,   TOOL_BRUSH_FILL),
            (self._act_eraser,       TOOL_ERASER),
            (self._act_eraser_flood, TOOL_ERASER_FLOOD),
            (self._act_select,       TOOL_SELECT),
            (self._act_pan,          TOOL_PAN),
        ]:
            act.setChecked(t == tool)
        self._canvas.set_tool(tool)
        self._lbl_sel_hint.setVisible(tool == TOOL_SELECT)

    def _on_toggle_fullscreen(self, checked: bool) -> None:
        self._left_panel.setVisible(not checked)
        self._right_panel.setVisible(not checked)

    def _on_pixel_hovered(self, x: int, y: int, r: int, g: int, b: int) -> None:
        self._lbl_pixel.setText(f"{x},{y}  R:{r}  G:{g}  B:{b}")

    def _on_delete_selected(self) -> None:
        """Del 키 — 포커스에 따라 다르게 동작:
        · 이미지 목록에 포커스 → 선택된 이미지 일괄 삭제
        · 그 외(캔버스, 어노테이션 목록 등) → 선택된 어노테이션 삭제"""
        try:
            if self._image_browser._list.hasFocus():
                self._image_browser._on_delete()
                return
        except Exception:
            pass
        self._canvas._delete_selected_or_last()

    def _on_class_selected(self, class_id: int) -> None:
        if self._canvas._tool == TOOL_SELECT and self._canvas._selected_ids:
            self._canvas.change_selected_class(class_id)
        else:
            self._canvas.set_class_id(class_id)

    def _on_image_selected(self, path: Path) -> None:
        self._canvas.load_image(path)
        log.info(f"이미지 열기: {path.name}")
        from app.core.annotation_store import get_ok
        self._act_ok.setChecked(get_ok(path))
        self._refresh_ann_list()

    def _on_image_deleted(self, path: Path) -> None:
        if self._canvas._image_path == path:
            self._canvas.clear()
            log.info(f"이미지 삭제됨: {path.name}")
            self._ann_list.clear()

    def _on_annotation_saved(self) -> None:
        n = len(self._canvas._annotations)
        path = self._canvas._image_path
        if path:
            log.info(f"{path.name}  — 어노테이션 {n}개 저장")
            self._image_browser.refresh_item(path)
            from app.core.annotation_store import get_ok
            self._act_ok.setChecked(get_ok(path))
        self._refresh_ann_list()

    def _on_canvas_selection_changed(self, ann_ids: list) -> None:
        """캔버스 선택 변경 → 어노테이션 목록 동기화."""
        if self._ann_list_updating:
            return
        self._ann_list_updating = True
        self._ann_list.clearSelection()
        id_set = set(ann_ids)
        for i in range(self._ann_list.count()):
            item = self._ann_list.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) in id_set:
                item.setSelected(True)
        self._ann_list_updating = False

    def _on_ann_list_selection_changed(self) -> None:
        """어노테이션 목록 선택 변경 → 캔버스 선택 동기화."""
        if self._ann_list_updating:
            return
        selected_ids = {
            item.data(Qt.ItemDataRole.UserRole)
            for item in self._ann_list.selectedItems()
        }
        self._canvas._selected_ids = selected_ids
        self._canvas._invalidate_overlay()
        self._canvas.update()

    def _on_clear_all(self) -> None:
        if self._canvas._image_path is None:
            return
        reply = QMessageBox.question(
            self, t("labeling.clear_title"),
            t("labeling.clear_msg"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._canvas.clear_all_annotations()

    def _on_toggle_ok(self) -> None:
        if self._canvas._image_path is None:
            self._act_ok.setChecked(False)
            return
        self._canvas.toggle_ok()

    def _on_auto_label(self) -> None:
        # 모델 미로드여도 '빠른 학습' 모드에서는 프리셋으로 자체 인스턴스 생성.
        model = self._get_model()
        dlg = AutoLabelDialog(model, parent=self)
        if dlg.exec():
            if self._canvas._image_path:
                self._canvas.load_image(self._canvas._image_path)
            self._image_browser.reload()
            log.info("오토 라벨링 완료 — 이미지를 선택해 결과를 확인하세요.")

    def _copy_prev_annotations(self) -> None:
        """이전 이미지의 어노테이션을 현재 이미지에 복사 (Ctrl+Shift+C)."""
        if self._canvas._image_path is None:
            return
        row = self._image_browser._list.currentRow()
        if row <= 0:
            log.warning("이전 이미지가 없어 복사를 건너뜁니다.")
            return
        prev_path = self._image_browser._paths[row - 1]
        from app.core import annotation_store as store
        prev_anns = store.load(prev_path)
        if not prev_anns:
            log.warning(f"이전 이미지 ({prev_path.name}) 에 어노테이션이 없습니다.")
            return
        self._canvas.paste_annotations(prev_anns)
        log.info(f"← {prev_path.name} 의 어노테이션 복사됨")

    # ── 어노테이션 목록 관리 ─────────────────────────────────────────────────

    def _refresh_ann_list(self) -> None:
        self._ann_list_updating = True
        self._ann_list.clear()
        from app.core.annotation_store import load_classes
        cls_map = {c.class_id: c for c in load_classes()}

        class_count: dict[int, int] = {}

        for ann in self._canvas._annotations:
            cls   = cls_map.get(ann.class_id)
            name  = cls.name  if cls else f"Class {ann.class_id}"
            color = cls.color if cls else (200, 200, 200)

            class_count[ann.class_id] = class_count.get(ann.class_id, 0) + 1
            idx = class_count[ann.class_id]

            # 폴리곤만 꼭짓점 평균으로 위치 계산 (numpy 불필요, 빠름)
            # brush_mask 는 np.where(20MP) 비용이 크므로 생략
            type_label = "Poly" if ann.type == "polygon" else "Mask"
            pos_info = ""
            if ann.type == "polygon" and ann.points:
                cx = int(sum(p[0] for p in ann.points) / len(ann.points))
                cy = int(sum(p[1] for p in ann.points) / len(ann.points))
                pos_info = f"  @({cx},{cy})  ·  {len(ann.points)}pts"

            item = QListWidgetItem(
                f"#{idx}  [{type_label}] {name}{pos_info}"
            )
            item.setData(Qt.ItemDataRole.UserRole, ann.annotation_id)
            item.setForeground(QColor(*color))
            item.setBackground(QColor(*color, 40))
            self._ann_list.addItem(item)

        self._ann_list_updating = False

    # ── 모델 접근 ─────────────────────────────────────────────────────────────

    def _get_model(self):
        win = self.window()
        if hasattr(win, "_model_tab"):
            return win._model_tab.loaded_model
        return None

    # ── 키보드 단축키 (탭 레벨) ───────────────────────────────────────────────

    def keyPressEvent(self, event) -> None:
        key  = event.key()
        mods = event.modifiers()
        no_mod = not (mods & (Qt.KeyboardModifier.ControlModifier |
                              Qt.KeyboardModifier.AltModifier |
                              Qt.KeyboardModifier.ShiftModifier))
        if key == Qt.Key.Key_Q:
            self._set_tool(TOOL_POLYGON)
        elif key == Qt.Key.Key_W:
            self._set_tool(TOOL_BRUSH)
        elif key == Qt.Key.Key_E:
            self._set_tool(TOOL_BRUSH_FILL)
        elif key == Qt.Key.Key_R:
            self._set_tool(TOOL_ERASER)
        elif key == Qt.Key.Key_D:
            self._set_tool(TOOL_ERASER_FLOOD)
        elif key == Qt.Key.Key_A:
            self._set_tool(TOOL_SELECT)
        elif key == Qt.Key.Key_S and no_mod:
            self._set_tool(TOOL_PAN)
        elif key == Qt.Key.Key_G:
            self._act_ok.trigger()
        elif key == Qt.Key.Key_F:
            self._act_ann_visible.toggle()
        elif key == Qt.Key.Key_V and no_mod:
            self._copy_prev_annotations()
        elif key == Qt.Key.Key_Z and no_mod:
            self._go_image(-1)
        elif key == Qt.Key.Key_X and no_mod:
            self._go_image(+1)
        elif key in (Qt.Key.Key_Up, Qt.Key.Key_PageUp):
            self._go_image(-1)
        elif key in (Qt.Key.Key_Down, Qt.Key.Key_PageDown):
            self._go_image(+1)
        elif key == Qt.Key.Key_1:
            self._set_channel(0)
        elif key == Qt.Key.Key_2:
            self._set_channel(1)
        elif key == Qt.Key.Key_3:
            self._set_channel(2)
        elif key == Qt.Key.Key_4:
            self._set_channel(3)
        else:
            super().keyPressEvent(event)

    def _set_channel(self, ch: int) -> None:
        """채널 전환 — 버튼 그룹과 동기화."""
        self._ch_group.button(ch).setChecked(True)
        self._canvas.set_channel(ch)

    def _go_image(self, step: int) -> None:
        """이미지 브라우저에서 step 만큼 상대 이동 (−1: 이전, +1: 다음)."""
        lst = self._image_browser._list
        cnt = lst.count()
        if cnt == 0:
            return
        row = max(0, min(lst.currentRow() + step, cnt - 1))
        if row != lst.currentRow():
            lst.setCurrentRow(row)
