"""이미지 목록 위젯 — 라벨링/추론(+존분석) 공용. 검색 / 정렬 / 폴더 트리(재귀 스캔) +
(옵션) 라벨 상태 아이콘/범례/정렬 + (옵션) 파일·폴더 추가/삭제.

라벨링 탭 구 `app/widgets/image_browser.py`(제거됨)의 상태 아이콘·추가/삭제 로직을
`show_status_icons`/`editable` 생성자 플래그로 포팅해 통합했다:
  - `show_status_icons=False`(기본, 추론 탭 동작 불변): 상태 아이콘(●/✓/○) 없이
    파일명만 표시, 상태 정렬 모드 없음.
  - `editable=False`(기본, 추론 탭 동작 불변): 파일추가/폴더추가/삭제 버튼 없음,
    `SingleSelection` 유지.
  - `load_folder()` 는 `Path.rglob()` 으로 하위 폴더를 재귀적으로 스캔하고,
    트리도 실제 디렉터리 중첩 구조를 그대로 반영한다(다단계 폴더 포함) — 구
    `image_browser.py` 의 `reload()`는 최상위 1단계만 스캔했었다(BUG-005로
    죽은 기능이었던 폴더 그룹핑, 이 컴포넌트는 반복하지 않는다).
"""
from __future__ import annotations

import shutil
from collections import defaultdict
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QTreeWidgetItemIterator, QLabel, QLineEdit, QComboBox,
    QPushButton, QFileDialog, QMessageBox, QProgressBar, QApplication,
)
from PyQt6.QtGui import QColor, QFont, QKeyEvent
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QSize, QThread, QEvent, QObject

from app.core.annotation_store import get_label_status
from app.core.file_io import retry_on_permission_error
from app.core.i18n import t
from app.core.logger import get_logger
from app.core import project as _project
from app.widgets.icons import icon as svg_icon, pixmap as svg_pixmap

log = get_logger(__name__)

SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}

_SEARCH_DEBOUNCE_MS = 200

# 정렬 기준 (mode_key, 표시 레이블) — status_* 2종은 show_status_icons=True일 때만 추가
_SORT_MODES = [
    ("name_asc",  "파일명 ↑"),
    ("name_desc", "파일명 ↓"),
    ("date_new",  "최근 수정순"),
    ("date_old",  "오래된 수정순"),
    ("folder",    "폴더"),
]

_TREE_STYLE = """
QTreeWidget {
    border: none;
    background: #111418;
    outline: none;
}
QTreeWidget::item {
    height: 22px;
    padding-left: 2px;
}
QTreeWidget::item:selected {
    background: #1e3a5f;
    color: #e5e7eb;
}
QTreeWidget::item:hover:!selected {
    background: #1f2937;
}
"""

_PATH_ROLE = Qt.ItemDataRole.UserRole

# icon name, color — show_status_icons=True일 때 트리/범례에 사용 (image_browser.py 포팅)
_STATUS_ICON_SIZE  = 14   # 트리 안 아이콘
_LEGEND_ICON_SIZE  = 12   # 범례 아이콘 — 트리보다 작음(원래부터 다른 치수, 통일하지 않음)
_STATUS_STYLE = {
    "labeled":   ("status_dot",  "#10b981"),
    "ok":        ("check",       "#60a5fa"),
    "unlabeled": ("status_ring", "#4b5563"),
}
_STATUS_KEY = {"labeled": 2, "ok": 1, "unlabeled": 0}

# NOTE: QFont()은 QApplication 생성 후에만 안전 — 모듈 레벨 생성 금지, 지연 생성.
_folder_font: QFont | None = None


def _get_folder_font() -> QFont:
    global _folder_font
    if _folder_font is None:
        _folder_font = QFont()
        _folder_font.setBold(True)
    return _folder_font


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


class _FolderImportWorker(QThread):
    """editable=True 전용 — 폴더 추가 시 백그라운드로 이미지 복사(image_browser.py 포팅)."""
    progress = pyqtSignal(int, int, str)   # done, total, filename
    finished = pyqtSignal(int, int)        # copied, skipped

    def __init__(self, sources: list[Path], parent=None) -> None:
        super().__init__(parent)
        self._sources = sources

    def run(self) -> None:
        _project.images_dir().mkdir(parents=True, exist_ok=True)
        copied = skipped = 0
        total = len(self._sources)
        for i, src in enumerate(self._sources):
            self.progress.emit(i, total, src.name)
            dst = _project.images_dir() / src.name
            if dst.exists():
                skipped += 1
            else:
                try:
                    retry_on_permission_error(lambda: shutil.copy2(src, dst))
                    copied += 1
                except (PermissionError, OSError) as e:
                    log.warning(f"이미지 복사 실패 — 건너뜀: {src} → {dst}: {e}")
                    skipped += 1
        self.finished.emit(copied, skipped)


class InferenceImageList(QWidget):
    """검색·정렬·폴더 트리를 지원하는 이미지 목록 위젯 (라벨링/추론/존분석 공용)."""

    image_selected  = pyqtSignal(Path)
    image_deleted   = pyqtSignal(Path)   # editable=True일 때만 실제 발행
    display_changed = pyqtSignal()   # 필터·정렬·목록 갱신 시 매번 emit (선택 경로 불변 케이스 포함)

    def __init__(self, parent=None, *, show_status_icons: bool = False,
                 editable: bool = False) -> None:
        super().__init__(parent)
        self._show_status_icons = show_status_icons
        self._editable = editable

        self._root: Path | None = None          # load_folder() 로 지정된 스캔 루트
        self._all_paths: list[Path] = []         # 필터·정렬 전 전체 이미지
        self._paths: list[Path] = []             # 현재 표시 중인 이미지 (필터+정렬 후)
        self._path_to_item: dict[Path, QTreeWidgetItem] = {}
        # show_status_icons=False면 항상 빈 dict — refresh_item/refresh_items가 조용히 no-op
        self._status_cache: dict[Path, str] = {}
        self._sort_modes = list(_SORT_MODES)
        if show_status_icons:
            self._sort_modes += [
                ("status_done", t("browser.sort.status_done")),
                ("status_todo", t("browser.sort.status_todo")),
            ]
        self._sort_mode = "name_asc"
        self._filter_text = ""
        self._mutation_guard = lambda: True
        self._import_worker: _FolderImportWorker | None = None
        self._search_debounce = QTimer(self)
        self._search_debounce.setSingleShot(True)
        self._search_debounce.setInterval(_SEARCH_DEBOUNCE_MS)
        self._search_debounce.timeout.connect(self._apply_display)
        self._build_ui()

    def set_mutation_guard(self, guard) -> None:
        self._mutation_guard = guard

    # ── UI 구성 ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # ── 제목 + (editable) 추가/삭제 버튼 — 한 줄에 병합(세로 공간 절약) ──────
        top = QHBoxLayout()
        top.addWidget(QLabel(t("ui.image_browser") if self._editable else "이미지 목록"))
        if self._editable:
            top.addStretch()
            self._btn_add        = QPushButton(t("ui.add_file"))
            self._btn_add_folder = QPushButton(t("ui.add_folder"))
            self._btn_del        = QPushButton(t("ui.delete"))
            self._btn_add.setToolTip(t("ui.add_file.tip"))
            self._btn_add_folder.setToolTip(t("ui.add_folder.tip"))
            self._btn_del.setToolTip(t("ui.delete.tip"))
            top.addWidget(self._btn_add)
            top.addWidget(self._btn_add_folder)
            top.addWidget(self._btn_del)
        layout.addLayout(top)

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("파일명 검색...")
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.setStyleSheet(
            "QLineEdit { background:#111418; border:1px solid #374151; "
            "border-radius:4px; padding:3px 6px; color:#e5e7eb; font-size:11px; }"
        )
        self._search_edit.textChanged.connect(self._on_search_changed)
        layout.addWidget(self._search_edit)

        sort_row = QHBoxLayout()
        sort_lbl = QLabel("정렬:")
        sort_lbl.setStyleSheet("font-size:11px; color:#9ca3af;")
        sort_row.addWidget(sort_lbl)
        self._sort_combo = QComboBox()
        self._sort_combo.setStyleSheet("font-size:11px;")
        for _, label in self._sort_modes:
            self._sort_combo.addItem(label)
        self._sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        sort_row.addWidget(self._sort_combo, stretch=1)
        layout.addLayout(sort_row)

        self._tree = QTreeWidget()
        self._tree.setColumnCount(1)
        self._tree.setHeaderHidden(True)
        self._tree.setSelectionMode(
            QTreeWidget.SelectionMode.ExtendedSelection if self._editable
            else QTreeWidget.SelectionMode.SingleSelection
        )
        self._tree.setRootIsDecorated(True)
        self._tree.setIndentation(16)
        self._tree.setUniformRowHeights(True)
        if self._show_status_icons:
            self._tree.setIconSize(QSize(_STATUS_ICON_SIZE, _STATUS_ICON_SIZE))
        self._tree.setStyleSheet(_TREE_STYLE)
        self._tree.currentItemChanged.connect(self._on_current_item_changed)
        self._tree.installEventFilter(self)   # Ctrl+C 파일명 복사 (#17) — 항상 설치
        layout.addWidget(self._tree, stretch=1)

        if self._show_status_icons:
            legend = QHBoxLayout()
            legend.setSpacing(3)
            for icon_name, color, label in [
                ("status_dot",  "#10b981", t("browser.legend_labeled")),
                ("check",       "#60a5fa", t("browser.legend_ok")),
                ("status_ring", "#4b5563", t("browser.legend_unlabeled")),
            ]:
                icon_lbl = QLabel()
                icon_lbl.setPixmap(svg_pixmap(icon_name, color, _LEGEND_ICON_SIZE))
                legend.addWidget(icon_lbl)
                text_lbl = QLabel(label)
                text_lbl.setStyleSheet(f"font-size:10px; color:{color}; margin-right:6px;")
                legend.addWidget(text_lbl)
            legend.addStretch()
            layout.addLayout(legend)

        if self._editable:
            self._progress = QProgressBar()
            self._progress.setRange(0, 100)
            self._progress.setTextVisible(False)
            self._progress.setFixedHeight(6)
            self._progress.hide()
            layout.addWidget(self._progress)

            self._lbl_status = QLabel()
            self._lbl_status.setStyleSheet("color:#9ca3af; font-size:11px;")
            self._lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._lbl_status.hide()
            layout.addWidget(self._lbl_status)

            self._btn_add.clicked.connect(self._on_add)
            self._btn_add_folder.clicked.connect(self._on_add_folder)
            self._btn_del.clicked.connect(self.delete_selected)

    # ── 공개 API ──────────────────────────────────────────────────────────────

    def load_folder(self, root: Path) -> None:
        """root 이하를 재귀적으로 스캔(rglob)해 전체 목록 갱신.

        하위 폴더 구조가 그대로 트리에 반영된다 (폴더 정렬 모드 선택 시).
        """
        self._root = root
        self._all_paths = sorted(
            p for p in root.rglob("*")
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS
        )
        if self._show_status_icons:
            self._status_cache = {p: get_label_status(p) for p in self._all_paths}
        self._apply_display()

    def load_files(self, paths: list[Path]) -> None:
        """파일 대화상자로 개별 선택된 파일들 — 공통 루트가 없어 폴더 그룹핑은
        직속 부모 폴더명 기준 1단계만 적용."""
        self._root = None
        self._all_paths = sorted(paths)
        if self._show_status_icons:
            self._status_cache = {p: get_label_status(p) for p in self._all_paths}
        self._apply_display()

    def reload(self) -> None:
        """self._root 가 설정돼 있으면 load_folder() 재호출 (편의 메서드)."""
        if self._root is not None:
            self.load_folder(self._root)

    def clear(self) -> None:
        self._root = None
        self._all_paths = []
        if self._show_status_icons:
            self._status_cache = {}
        self._apply_display()

    def count(self) -> int:
        return len(self._paths)

    def paths(self) -> list[Path]:
        """현재 표시 중(필터+정렬 후)인 전체 이미지 경로 — 일괄 처리용."""
        return list(self._paths)

    def current_path(self) -> Path | None:
        return self._get_item_path(self._tree.currentItem())

    def current_display_index(self) -> int:
        path = self.current_path()
        if path is None:
            return -1
        try:
            return self._paths.index(path)
        except ValueError:
            return -1

    def selected_paths(self) -> list[Path]:
        """Selected images in current display order, falling back to current."""
        selected = {
            path for item in self._tree.selectedItems()
            if (path := self._get_item_path(item)) is not None
        }
        ordered = [path for path in self._paths if path in selected]
        if ordered:
            return ordered
        current = self.current_path()
        return [current] if current is not None else []

    def has_list_focus(self) -> bool:
        """트리 위젯에 키보드 포커스가 있는지."""
        return self._tree.hasFocus()

    def is_importing(self) -> bool:
        return self._import_worker is not None and self._import_worker.isRunning()

    def refresh_item(self, path: Path) -> None:
        """어노테이션 저장 후 해당 항목의 상태 아이콘·색상만 갱신.
        show_status_icons=False면 상태 캐시가 없어 즉시 no-op."""
        if not self._show_status_icons:
            return
        status = get_label_status(path)
        self._status_cache[path] = status
        item = self._path_to_item.get(path)
        if item is None:
            return
        icon_name, color = _STATUS_STYLE[status]
        item.setIcon(0, svg_icon(icon_name, color, _STATUS_ICON_SIZE))
        item.setForeground(0, QColor(color))

    def refresh_items(self, paths: list[Path]) -> None:
        """Refresh known statuses and reapply sorting without rescanning the project."""
        if not self._show_status_icons:
            return
        for path in paths:
            if path in self._status_cache:
                status = get_label_status(path)
                self._status_cache[path] = status
                if self._sort_mode not in ("status_done", "status_todo"):
                    item = self._path_to_item.get(path)
                    if item is not None:
                        icon_name, color = _STATUS_STYLE[status]
                        item.setIcon(0, svg_icon(icon_name, color, _STATUS_ICON_SIZE))
                        item.setForeground(0, QColor(color))
        if self._sort_mode in ("status_done", "status_todo"):
            self._apply_display()

    def delete_selected(self) -> None:
        """선택된 이미지(들) 삭제. editable=False면 아무 동작 안 함(버튼 자체도 없음).
        삭제 버튼 클릭과 키보드 Delete 경로가 모두 이 메서드를 호출."""
        if not self._editable:
            return
        if not self._mutation_guard():
            return
        selected_paths = [
            self._get_item_path(item)
            for item in self._tree.selectedItems()
            if self._get_item_path(item) is not None
        ]
        if not selected_paths:
            return

        n = len(selected_paths)
        if n == 1:
            msg = t("browser.delete_confirm_single").format(name=selected_paths[0].name)
        else:
            preview = ", ".join(p.name for p in selected_paths[:3])
            if n > 3:
                preview += t("browser.delete_more_suffix").format(n=n - 3)
            msg = t("browser.delete_confirm_multi").format(n=n, preview=preview)

        reply = QMessageBox.question(
            self, t("browser.delete_confirm_title"), msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        ann_dir = _project.annotations_dir()
        deleted: set[Path] = set()
        for p in selected_paths:
            try:
                ann_path = ann_dir / f"{p.stem}.json"
                if ann_path.exists():
                    ann_path.unlink()
                self.image_deleted.emit(p)
                p.unlink()
                deleted.add(p)
            except Exception:
                continue

        # 삭제된 항목만 캐시에서 제거 — reload()(전체 재스캔)를 다시 부르면
        # 남은 이미지 수에 비례한 비용이 드는데, 이미 상태를 알고 있는 항목이라
        # 재조회가 불필요하다.
        self._all_paths = [p for p in self._all_paths if p not in deleted]
        for p in deleted:
            self._status_cache.pop(p, None)
        self._apply_display()

    def navigate(self, step: int) -> None:
        """현재 이미지에서 step 만큼 이동 (±1). 접힌 폴더는 자동 펼침."""
        if not self._paths:
            return
        idx = self.current_display_index()
        if idx == -1:
            self._select_by_index(0)
            return
        new_idx = max(0, min(idx + step, len(self._paths) - 1))
        if new_idx != idx:
            self._select_by_index(new_idx)

    # ── 이벤트 필터 ───────────────────────────────────────────────────────────

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """_tree 전용 — Ctrl+C 로 선택된 항목들의 파일명을 클립보드에 복사 (#17)."""
        if (obj is self._tree and event.type() == QEvent.Type.KeyPress
                and isinstance(event, QKeyEvent)
                and event.key() == Qt.Key.Key_C
                and event.modifiers() == Qt.KeyboardModifier.ControlModifier):
            self._copy_selected_names()
            return True
        return super().eventFilter(obj, event)

    def _copy_selected_names(self) -> None:
        names = [
            p.name for item in self._tree.selectedItems()
            if (p := self._get_item_path(item)) is not None
        ]
        if names:
            QApplication.clipboard().setText("\n".join(names))

    # ── 슬롯 ─────────────────────────────────────────────────────────────────

    def _on_current_item_changed(self, current: QTreeWidgetItem | None, _previous) -> None:
        path = self._get_item_path(current)
        if path is not None:
            self.image_selected.emit(path)

    def _on_search_changed(self, text: str) -> None:
        self._filter_text = text.strip()
        self._search_debounce.start()

    def _on_sort_changed(self, idx: int) -> None:
        self._sort_mode = self._sort_modes[idx][0]
        self._apply_display()

    def _on_add(self) -> None:
        if not self._mutation_guard():
            return
        files, _ = QFileDialog.getOpenFileNames(
            self, t("browser.add_file_dialog_title"), "",
            "Images (*.jpg *.jpeg *.png *.bmp *.tiff *.tif)"
        )
        if not files:
            return
        for f in files:
            src = Path(f)
            dst = _project.images_dir() / src.name
            if dst.exists():
                continue
            try:
                retry_on_permission_error(lambda: shutil.copy2(src, dst))
            except (PermissionError, OSError) as e:
                log.exception(f"이미지 추가 실패: {src} → {dst}")
                QMessageBox.critical(self, t("ui.add_file"), str(e))
                return
        self.reload()

    def _on_add_folder(self) -> None:
        if not self._mutation_guard():
            return
        folder = QFileDialog.getExistingDirectory(self, t("browser.add_folder_dialog_title"))
        if not folder:
            return
        sources = sorted(
            p for p in Path(folder).iterdir()
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS
        )
        if not sources:
            QMessageBox.information(self, t("browser.no_images_title"),
                t("browser.no_images_msg"))
            return

        self._set_buttons_enabled(False)
        self._progress.setRange(0, len(sources))
        self._progress.setValue(0)
        self._progress.show()
        self._lbl_status.setText(t("browser.copying").format(done=0, total=len(sources)))
        self._lbl_status.show()

        self._import_worker = _FolderImportWorker(sources, parent=self)
        self._import_worker.progress.connect(self._on_import_progress)
        self._import_worker.finished.connect(self._on_import_finished)
        self._import_worker.start()

    # ── 임포트 워커 슬롯 ──────────────────────────────────────────────────────

    def _on_import_progress(self, done: int, total: int, name: str) -> None:
        self._progress.setValue(done)
        self._lbl_status.setText(f"{done} / {total}  {name}")

    def _on_import_finished(self, copied: int, skipped: int) -> None:
        self._progress.hide()
        self._lbl_status.hide()
        self._set_buttons_enabled(True)
        self.reload()
        msg = t("browser.import_done_msg").format(n=copied)
        if skipped:
            msg += t("browser.import_skipped_suffix").format(n=skipped)
        QMessageBox.information(self, t("browser.import_done_title"), msg)

    def _set_buttons_enabled(self, enabled: bool) -> None:
        self._btn_add.setEnabled(enabled)
        self._btn_add_folder.setEnabled(enabled)
        self._btn_del.setEnabled(enabled)

    # ── 내부 헬퍼 ─────────────────────────────────────────────────────────────

    def _get_item_path(self, item: QTreeWidgetItem | None) -> Path | None:
        if item is None:
            return None
        data = item.data(0, _PATH_ROLE)
        return data if isinstance(data, Path) else None

    def _select_by_index(self, idx: int) -> None:
        if not (0 <= idx < len(self._paths)):
            return
        item = self._path_to_item.get(self._paths[idx])
        if item is None:
            return
        parent = item.parent()
        while parent is not None:
            if not parent.isExpanded():
                parent.setExpanded(True)
            parent = parent.parent()
        self._tree.setCurrentItem(item)
        self._tree.scrollToItem(item)

    def _make_leaf_item(self, path: Path, display_name: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem()
        item.setText(0, display_name)
        if self._show_status_icons:
            status = self._status_cache.get(path) or get_label_status(path)
            icon_name, color = _STATUS_STYLE[status]
            item.setIcon(0, svg_icon(icon_name, color, _STATUS_ICON_SIZE))
            item.setForeground(0, QColor(color))
        else:
            item.setForeground(0, QColor("#e5e7eb"))
        item.setData(0, _PATH_ROLE, path)   # ← Path 를 아이템에 직접 저장
        return item

    def _make_folder_item(self, folder_name: str, count: int) -> QTreeWidgetItem:
        item = QTreeWidgetItem()
        item.setText(0, f"  {folder_name}  ({count})")
        item.setIcon(0, svg_icon("folder", "#60a5fa", 14))
        item.setForeground(0, QColor("#60a5fa"))
        item.setBackground(0, QColor("#1a2235"))
        item.setFont(0, _get_folder_font())
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)   # 선택 불가, 펼침만 가능
        return item

    def _build_folder_tree(self, paths: list[Path]) -> None:
        if self._root is not None:
            self._build_nested_tree(paths, self._root)
        else:
            self._build_flat_group_tree(paths)

    def _build_nested_tree(self, paths: list[Path], root: Path) -> None:
        """root 기준 실제 하위 폴더 구조를 그대로(다단계 중첩) 재현."""
        folder_counts: dict[tuple[str, ...], int] = defaultdict(int)
        for p in paths:
            parts = p.relative_to(root).parts
            for i in range(1, len(parts)):
                folder_counts[parts[:i]] += 1

        folder_items: dict[tuple[str, ...], QTreeWidgetItem] = {}

        def get_folder_item(parts: tuple[str, ...]) -> QTreeWidgetItem:
            cached = folder_items.get(parts)
            if cached is not None:
                return cached
            item = self._make_folder_item(parts[-1], folder_counts[parts])
            if len(parts) == 1:
                self._tree.addTopLevelItem(item)
            else:
                get_folder_item(parts[:-1]).addChild(item)
            item.setExpanded(True)
            folder_items[parts] = item
            return item

        for p in paths:
            parts = p.relative_to(root).parts
            leaf = self._make_leaf_item(p, parts[-1])
            if len(parts) == 1:
                self._tree.addTopLevelItem(leaf)
            else:
                get_folder_item(parts[:-1]).addChild(leaf)
            self._path_to_item[p] = leaf

    def _build_flat_group_tree(self, paths: list[Path]) -> None:
        """공통 루트가 없는 개별 파일 선택 — 직속 부모 폴더명 1단계 그룹핑."""
        groups: dict[str, list[Path]] = defaultdict(list)
        for p in paths:
            groups[p.parent.name].append(p)

        if len(groups) <= 1:
            for p in paths:
                item = self._make_leaf_item(p, p.name)
                self._tree.addTopLevelItem(item)
                self._path_to_item[p] = item
            return

        for folder_name in sorted(groups.keys()):
            imgs = groups[folder_name]
            folder_item = self._make_folder_item(folder_name, len(imgs))
            self._tree.addTopLevelItem(folder_item)
            folder_item.setExpanded(True)
            for p in imgs:
                child = self._make_leaf_item(p, p.name)
                folder_item.addChild(child)
                self._path_to_item[p] = child

    def _number_items(self) -> None:
        """트리에 실제로 보이는 순서(펼침 상태 무관)대로 이미지 항목에 전체 통번호를 접두.

        폴더 헤더 아이템은 UserRole 에 Path 가 없어 자동으로 건너뛰어진다.
        """
        idx = 1
        it = QTreeWidgetItemIterator(self._tree)
        while it.value():
            item = it.value()
            if self._get_item_path(item) is not None:
                item.setText(0, f"{idx}. {item.text(0)}")
                idx += 1
            it += 1

    def _apply_display(self) -> None:
        cur_idx = self.current_display_index()
        cur_path: Path | None = (
            self._paths[cur_idx] if 0 <= cur_idx < len(self._paths) else None
        )
        selected_paths = set(self.selected_paths()) if self._editable else set()

        # ── 필터 ─────────────────────────────────────────────────────────────
        text = self._filter_text.lower()
        filtered = [
            p for p in self._all_paths
            if not text or text in p.name.lower()
        ]

        # ── 정렬 ─────────────────────────────────────────────────────────────
        if self._sort_mode == "name_asc":
            filtered.sort(key=lambda p: p.name.lower())
        elif self._sort_mode == "name_desc":
            filtered.sort(key=lambda p: p.name.lower(), reverse=True)
        elif self._sort_mode == "date_new":
            filtered.sort(key=_mtime, reverse=True)
        elif self._sort_mode == "date_old":
            filtered.sort(key=_mtime)
        elif self._sort_mode == "folder":
            filtered.sort(key=lambda p: (str(p.parent).lower(), p.name.lower()))
        elif self._sort_mode == "status_done":
            filtered.sort(key=lambda p: (
                -_STATUS_KEY.get(self._status_cache.get(p, "unlabeled"), 0), p.name.lower()
            ))
        elif self._sort_mode == "status_todo":
            filtered.sort(key=lambda p: (
                _STATUS_KEY.get(self._status_cache.get(p, "unlabeled"), 0), p.name.lower()
            ))

        self._paths = filtered

        # ── 트리 재구성 (시그널 차단) ─────────────────────────────────────────
        self._tree.blockSignals(True)
        self._tree.clear()
        self._path_to_item.clear()

        if self._sort_mode == "folder":
            self._build_folder_tree(filtered)
        else:
            for p in filtered:
                item = self._make_leaf_item(p, p.name)
                self._tree.addTopLevelItem(item)
                self._path_to_item[p] = item

        self._number_items()

        # ── 선택 복원 ─────────────────────────────────────────────────────────
        new_item: QTreeWidgetItem | None = None
        if cur_path and cur_path in self._path_to_item:
            new_item = self._path_to_item[cur_path]
        elif filtered:
            new_item = self._path_to_item.get(filtered[0])

        if new_item is not None:
            self._tree.setCurrentItem(new_item)
        for path in selected_paths:
            item = self._path_to_item.get(path)
            if item is not None:
                item.setSelected(True)
        self._tree.blockSignals(False)

        if new_item is not None:
            new_path = self._get_item_path(new_item)
            if new_path is not None and new_path != cur_path:
                self.image_selected.emit(new_path)

        self.display_changed.emit()
