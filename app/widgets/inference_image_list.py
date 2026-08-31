"""추론 탭 전용 이미지 목록 — 검색 / 정렬 / 폴더 트리(재귀 스캔).

라벨링 탭 `app/widgets/image_browser.py` 의 `_make_tree_item`/`_make_folder_item`
패턴을 참고했지만 그대로 재사용하지는 않는다:
  - 추론 탭엔 라벨 상태 개념이 없으므로 상태 아이콘(●/✓/○) 없이 파일명만 표시하고,
    Path 는 UserRole 에만 저장한다.
  - `load_folder()` 는 `Path.rglob()` 으로 하위 폴더를 재귀적으로 스캔하고,
    트리도 실제 디렉터리 중첩 구조를 그대로 반영한다(다단계 폴더 포함).
    image_browser.py 의 기존 폴더 그룹핑은 `reload()`가 최상위 1단계만 스캔하고
    이미지 추가도 평탄 복사라 실제로는 트리거되지 않는 죽은 기능이었음이 QA.md
    BUG-005 로 밝혀졌다 — 이 컴포넌트는 그 실수를 반복하지 않는다.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QTreeWidgetItemIterator, QLabel, QLineEdit, QComboBox,
)
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtCore import Qt, pyqtSignal, QTimer

from app.widgets.icons import icon as svg_icon

SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}

_SEARCH_DEBOUNCE_MS = 200

# 정렬 기준 (mode_key, 표시 레이블) — image_browser.py 참고, 상태 정렬은 대상 없어 제외
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


class InferenceImageList(QWidget):
    """검색·정렬·폴더 트리를 지원하는 경량 이미지 목록 위젯 (추론 탭 전용)."""

    image_selected = pyqtSignal(Path)
    display_changed = pyqtSignal()   # 필터·정렬·목록 갱신 시 매번 emit (선택 경로 불변 케이스 포함)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._root: Path | None = None          # load_folder() 로 지정된 스캔 루트
        self._all_paths: list[Path] = []         # 필터·정렬 전 전체 이미지
        self._paths: list[Path] = []             # 현재 표시 중인 이미지 (필터+정렬 후)
        self._path_to_item: dict[Path, QTreeWidgetItem] = {}
        self._sort_mode = "name_asc"
        self._filter_text = ""
        self._search_debounce = QTimer(self)
        self._search_debounce.setSingleShot(True)
        self._search_debounce.setInterval(_SEARCH_DEBOUNCE_MS)
        self._search_debounce.timeout.connect(self._apply_display)
        self._build_ui()

    # ── UI 구성 ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        layout.addWidget(QLabel("이미지 목록"))

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
        for _, label in _SORT_MODES:
            self._sort_combo.addItem(label)
        self._sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        sort_row.addWidget(self._sort_combo, stretch=1)
        layout.addLayout(sort_row)

        self._tree = QTreeWidget()
        self._tree.setColumnCount(1)
        self._tree.setHeaderHidden(True)
        self._tree.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self._tree.setRootIsDecorated(True)
        self._tree.setIndentation(16)
        self._tree.setUniformRowHeights(True)
        self._tree.setStyleSheet(_TREE_STYLE)
        self._tree.currentItemChanged.connect(self._on_current_item_changed)
        layout.addWidget(self._tree, stretch=1)

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
        self._apply_display()

    def load_files(self, paths: list[Path]) -> None:
        """파일 대화상자로 개별 선택된 파일들 — 공통 루트가 없어 폴더 그룹핑은
        직속 부모 폴더명 기준 1단계만 적용."""
        self._root = None
        self._all_paths = sorted(paths)
        self._apply_display()

    def clear(self) -> None:
        self._root = None
        self._all_paths = []
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

    # ── 슬롯 ─────────────────────────────────────────────────────────────────

    def _on_current_item_changed(self, current: QTreeWidgetItem | None, _previous) -> None:
        path = self._get_item_path(current)
        if path is not None:
            self.image_selected.emit(path)

    def _on_search_changed(self, text: str) -> None:
        self._filter_text = text.strip()
        self._search_debounce.start()

    def _on_sort_changed(self, idx: int) -> None:
        self._sort_mode = _SORT_MODES[idx][0]
        self._apply_display()

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
        self._tree.blockSignals(False)

        if new_item is not None:
            new_path = self._get_item_path(new_item)
            if new_path is not None and new_path != cur_path:
                self.image_selected.emit(new_path)

        self.display_changed.emit()
