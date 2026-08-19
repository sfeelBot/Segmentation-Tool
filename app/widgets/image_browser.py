import shutil
from collections import defaultdict
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QPushButton, QLabel, QFileDialog, QMessageBox, QProgressBar,
    QComboBox, QLineEdit,
)
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QTimer
from app.core.i18n import t

from app.core.annotation_store import get_label_status
from app.core import project as _project

SUPPORTED = ("*.jpg", "*.jpeg", "*.png", "*.bmp", "*.tiff", "*.tif")
SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}

_SEARCH_DEBOUNCE_MS = 200

# sym, text color
_STATUS_STYLE = {
    "labeled":   ("●", "#6ddf6d"),
    "ok":        ("✓", "#5ba8ff"),
    "unlabeled": ("○", "#999999"),
}

# 정렬 기준 (mode_key, 표시 레이블)
_SORT_MODES = [
    ("name_asc",    "파일명 ↑"),
    ("name_desc",   "파일명 ↓"),
    ("folder",      "폴더"),
    ("status_done", "완료↑"),
    ("status_todo", "미완료↑"),
]

_STATUS_KEY = {"labeled": 2, "ok": 1, "unlabeled": 0}

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
QTreeWidget::branch {
    background: #111418;
}
"""

# NOTE: QFont()은 QApplication 생성 후에만 안전하게 만들 수 있음.
# 모듈 레벨 생성 금지 → _make_folder_item() 안에서 지연 생성.
_folder_font: QFont | None = None


def _get_folder_font() -> QFont:
    """폴더 헤더용 굵은 폰트 — 최초 호출 시 생성 (QApplication 생성 후)."""
    global _folder_font
    if _folder_font is None:
        _folder_font = QFont()
        _folder_font.setBold(True)
    return _folder_font


# UserRole — QTreeWidgetItem 에 Path 를 직접 저장 (dict 키 대신)
_PATH_ROLE = Qt.ItemDataRole.UserRole


class _FolderImportWorker(QThread):
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
                    shutil.copy2(src, dst)
                    copied += 1
                except Exception:
                    skipped += 1
        self.finished.emit(copied, skipped)


class ImageBrowser(QWidget):
    image_selected = pyqtSignal(Path)
    image_deleted  = pyqtSignal(Path)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._all_paths: list[Path] = []      # 전체 이미지 (필터·정렬 전)
        self._paths: list[Path] = []          # 현재 표시 중인 이미지 (필터+정렬 후)
        # Path → QTreeWidgetItem (역방향 룩업용; QTreeWidgetItem→Path 는 UserRole 사용)
        self._path_to_item: dict[Path, QTreeWidgetItem] = {}
        # Path → label status ("labeled"/"ok"/"unlabeled") — reload() 시 전체 재구축,
        # refresh_item() 시 단건 갱신. get_label_status() 의 JSON 재파싱 비용을 줄이기 위한 캐시.
        self._status_cache: dict[Path, str] = {}
        self._sort_mode: str = "name_asc"
        self._filter_text: str = ""
        self._import_worker: _FolderImportWorker | None = None
        self._search_debounce = QTimer(self)
        self._search_debounce.setSingleShot(True)
        self._search_debounce.setInterval(_SEARCH_DEBOUNCE_MS)
        self._search_debounce.timeout.connect(self._apply_display)
        self._build_ui()
        self.reload()

    # ── UI 구성 ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # ── 상단 버튼 행 ──────────────────────────────────────────────────────
        top = QHBoxLayout()
        top.addWidget(QLabel(t("ui.image_browser")))
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

        # ── 검색 바 ───────────────────────────────────────────────────────────
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("🔍 파일명 검색...")
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.setStyleSheet(
            "QLineEdit { background:#111418; border:1px solid #374151; "
            "border-radius:4px; padding:3px 6px; color:#e5e7eb; font-size:11px; }"
        )
        self._search_edit.textChanged.connect(self._on_search_changed)
        layout.addWidget(self._search_edit)

        # ── 정렬 콤보 ─────────────────────────────────────────────────────────
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

        # ── 트리 위젯 ─────────────────────────────────────────────────────────
        self._tree = QTreeWidget()
        self._tree.setColumnCount(1)
        self._tree.setHeaderHidden(True)
        self._tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self._tree.setRootIsDecorated(True)
        self._tree.setIndentation(16)
        self._tree.setUniformRowHeights(True)
        self._tree.setStyleSheet(_TREE_STYLE)
        self._tree.currentItemChanged.connect(self._on_current_item_changed)
        layout.addWidget(self._tree)

        # ── 범례 ──────────────────────────────────────────────────────────────
        legend = QHBoxLayout()
        for sym, color, label in [("●", "#6ddf6d", "라벨링됨"),
                                   ("✓", "#5ba8ff", "OK"),
                                   ("○", "#999999", "미라벨")]:
            lbl = QLabel(f"<font color='{color}'>{sym}</font> {label}")
            lbl.setStyleSheet("font-size:10px;")
            legend.addWidget(lbl)
        legend.addStretch()
        layout.addLayout(legend)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(6)
        self._progress.hide()
        layout.addWidget(self._progress)

        self._lbl_status = QLabel()
        self._lbl_status.setStyleSheet("color:#888; font-size:11px;")
        self._lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_status.hide()
        layout.addWidget(self._lbl_status)

        self._btn_add.clicked.connect(self._on_add)
        self._btn_add_folder.clicked.connect(self._on_add_folder)
        self._btn_del.clicked.connect(self._on_delete)

    # ── 공개 API ──────────────────────────────────────────────────────────────

    def reload(self) -> None:
        """images_dir 를 스캔해 전체 목록 갱신 후 표시 재적용.
        dataset._collect_pairs 와 일관성을 위해 flat 스캔 사용."""
        _project.images_dir().mkdir(parents=True, exist_ok=True)
        self._all_paths = sorted(
            p for pat in SUPPORTED
            for p in _project.images_dir().glob(pat)
        )
        # 상태 캐시 전체 재구축 — 이미지당 get_label_status() 1회만 호출
        self._status_cache = {p: get_label_status(p) for p in self._all_paths}
        self._apply_display()

    def refresh_item(self, path: Path) -> None:
        """어노테이션 저장 후 해당 항목의 상태 아이콘·색상만 갱신."""
        status = get_label_status(path)
        self._status_cache[path] = status
        item = self._path_to_item.get(path)
        if item is None:
            return
        sym, color = _STATUS_STYLE[status]
        # 폴더 헤더 아래 자식이면 파일명만, 최상위면 상대경로
        display = path.name if item.parent() is not None else self._rel_name(path)
        item.setText(0, f"{sym}  {display}")
        item.setForeground(0, QColor(color))

    def current_path(self) -> Path | None:
        """현재 선택된 이미지 경로. 폴더 헤더 선택 시 None."""
        return self._get_item_path(self._tree.currentItem())

    def current_display_index(self) -> int:
        """현재 선택된 이미지의 _paths 인덱스. 없으면 -1."""
        path = self._get_item_path(self._tree.currentItem())
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

    def has_list_focus(self) -> bool:
        """트리 위젯에 키보드 포커스가 있는지."""
        return self._tree.hasFocus()

    # ── 슬롯 ─────────────────────────────────────────────────────────────────

    def _on_current_item_changed(self, current: QTreeWidgetItem | None,
                                 _previous) -> None:
        if current is None:
            return
        path = self._get_item_path(current)
        if path is not None:
            self.image_selected.emit(path)

    def _on_search_changed(self, text: str) -> None:
        self._filter_text = text.strip()
        # 디바운스 — keystroke마다 즉시 재적용하지 않고, 입력이 멈춘 뒤에만 _apply_display() 실행
        self._search_debounce.start()

    def _on_sort_changed(self, idx: int) -> None:
        self._sort_mode = _SORT_MODES[idx][0]
        self._apply_display()

    def _on_add(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "이미지 추가", "",
            "Images (*.jpg *.jpeg *.png *.bmp *.tiff *.tif)"
        )
        if not files:
            return
        for f in files:
            src = Path(f)
            dst = _project.images_dir() / src.name
            if dst.exists():
                continue
            shutil.copy2(src, dst)
        self.reload()

    def _on_add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "폴더 선택")
        if not folder:
            return
        sources = sorted(
            p for p in Path(folder).iterdir()
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS
        )
        if not sources:
            QMessageBox.information(self, "이미지 없음",
                "선택한 폴더에 지원되는 이미지가 없습니다.")
            return

        self._set_buttons_enabled(False)
        self._progress.setRange(0, len(sources))
        self._progress.setValue(0)
        self._progress.show()
        self._lbl_status.setText(f"0 / {len(sources)}  복사 중…")
        self._lbl_status.show()

        self._import_worker = _FolderImportWorker(sources, parent=self)
        self._import_worker.progress.connect(self._on_import_progress)
        self._import_worker.finished.connect(self._on_import_finished)
        self._import_worker.start()

    def _on_delete(self) -> None:
        """선택된 이미지(들) 삭제. 폴더 헤더는 제외하고 이미지 항목만."""
        selected_paths = [
            self._get_item_path(item)
            for item in self._tree.selectedItems()
            if self._get_item_path(item) is not None   # 폴더 헤더 제외
        ]
        if not selected_paths:
            return

        n = len(selected_paths)
        if n == 1:
            msg = (f"'{selected_paths[0].name}' 을 삭제하시겠습니까?\n"
                   "(어노테이션도 함께 삭제됩니다)")
        else:
            preview = ", ".join(p.name for p in selected_paths[:3])
            if n > 3:
                preview += f", … 외 {n - 3}개"
            msg = (f"선택한 {n}개 이미지를 모두 삭제하시겠습니까?\n\n"
                   f"{preview}\n\n(각 이미지의 어노테이션도 함께 삭제됩니다)")

        reply = QMessageBox.question(
            self, "삭제 확인", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        ann_dir = _project.annotations_dir()
        for p in selected_paths:
            try:
                ann_path = ann_dir / f"{p.stem}.json"
                if ann_path.exists():
                    ann_path.unlink()
                self.image_deleted.emit(p)
                p.unlink()
            except Exception:
                continue
        self.reload()

    # ── 임포트 워커 슬롯 ──────────────────────────────────────────────────────

    def _on_import_progress(self, done: int, total: int, name: str) -> None:
        self._progress.setValue(done)
        self._lbl_status.setText(f"{done} / {total}  {name}")

    def _on_import_finished(self, copied: int, skipped: int) -> None:
        self._progress.hide()
        self._lbl_status.hide()
        self._set_buttons_enabled(True)
        self.reload()
        msg = f"{copied}개 추가됨"
        if skipped:
            msg += f"  ({skipped}개 중복 건너뜀)"
        QMessageBox.information(self, "추가 완료", msg)

    # ── 내부 헬퍼 ─────────────────────────────────────────────────────────────

    def _get_item_path(self, item: QTreeWidgetItem | None) -> Path | None:
        """아이템의 UserRole 데이터로 Path 반환.
        폴더 헤더 아이템이면 None (UserRole 미설정)."""
        if item is None:
            return None
        data = item.data(0, _PATH_ROLE)
        return data if isinstance(data, Path) else None

    def _rel_name(self, path: Path) -> str:
        """images_dir 기준 상대 경로 문자열."""
        try:
            return str(path.relative_to(_project.images_dir()))
        except ValueError:
            return path.name

    def _make_tree_item(self, path: Path,
                        display_name: str | None = None) -> QTreeWidgetItem:
        """이미지 경로로 QTreeWidgetItem 생성 (상태 아이콘 + 색상 적용).

        display_name: 표시할 이름. None이면 images_dir 기준 상대경로 사용.
        Path는 UserRole에 직접 저장 (dict 키로 사용하지 않음).
        """
        status = self._status_cache.get(path) or get_label_status(path)
        sym, color = _STATUS_STYLE[status]
        label = display_name if display_name is not None else self._rel_name(path)
        item = QTreeWidgetItem()
        item.setText(0, f"{sym}  {label}")
        item.setForeground(0, QColor(color))
        item.setData(0, _PATH_ROLE, path)   # ← Path 를 아이템에 직접 저장
        return item

    def _make_folder_item(self, folder_name: str, count: int) -> QTreeWidgetItem:
        """폴더 헤더 QTreeWidgetItem 생성 — 선택 불가, 펼침만 가능.

        UserRole 을 설정하지 않아 _get_item_path() 가 None 을 반환함.
        """
        item = QTreeWidgetItem()
        item.setText(0, f"📁  {folder_name}  ({count})")
        item.setForeground(0, QColor("#60a5fa"))
        item.setBackground(0, QColor("#1a2235"))
        item.setFont(0, _get_folder_font())
        # ItemIsEnabled 만 설정 → 클릭해도 선택 안 됨, 펼침은 동작
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        return item

    def _select_by_index(self, idx: int) -> None:
        """_paths[idx] 를 선택하고, 접힌 폴더면 자동으로 펼침."""
        if not (0 <= idx < len(self._paths)):
            return
        item = self._path_to_item.get(self._paths[idx])
        if item is None:
            return
        parent = item.parent()
        if parent is not None and not parent.isExpanded():
            parent.setExpanded(True)
        self._tree.setCurrentItem(item)
        self._tree.scrollToItem(item)

    def _build_folder_tree(self, paths: list[Path]) -> None:
        """폴더 기준 그룹화 트리 구성.

        images_dir 직계 파일 → 최상위 아이템 (헤더 없음).
        하위폴더 파일          → 📁 폴더명 헤더 아래 (접기/펼치기 가능).
        """
        root_paths: list[Path] = []
        folder_groups: dict[str, list[Path]] = defaultdict(list)

        for p in paths:
            try:
                rel = p.relative_to(_project.images_dir())
                if len(rel.parts) == 1:
                    root_paths.append(p)
                else:
                    folder_groups[str(rel.parts[0])].append(p)
            except ValueError:
                root_paths.append(p)

        # 최상위 이미지 (폴더 헤더 없음)
        for p in root_paths:
            item = self._make_tree_item(p)
            self._tree.addTopLevelItem(item)
            self._path_to_item[p] = item

        # 하위폴더 그룹 (알파벳 순)
        for folder_name in sorted(folder_groups.keys()):
            imgs = folder_groups[folder_name]
            folder_item = self._make_folder_item(folder_name, len(imgs))
            self._tree.addTopLevelItem(folder_item)
            folder_item.setExpanded(True)   # 기본 펼침
            for p in imgs:
                # 폴더 헤더 아래에서는 파일명만 표시 (상위 헤더와 중복 방지)
                child = self._make_tree_item(p, display_name=p.name)
                folder_item.addChild(child)
                self._path_to_item[p] = child

    def _apply_display(self) -> None:
        """_all_paths 에 필터·정렬을 적용해 _paths + 트리 위젯 갱신."""
        # 현재 선택 기억
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
        elif self._sort_mode == "folder":
            filtered.sort(key=lambda p: (
                p.parent.name.lower(), p.name.lower()
            ))
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
                item = self._make_tree_item(p)
                self._tree.addTopLevelItem(item)
                self._path_to_item[p] = item

        # ── 선택 복원 ─────────────────────────────────────────────────────────
        new_item: QTreeWidgetItem | None = None
        if cur_path and cur_path in self._path_to_item:
            new_item = self._path_to_item[cur_path]
        elif filtered:
            new_item = self._path_to_item.get(filtered[0])

        if new_item is not None:
            self._tree.setCurrentItem(new_item)
        self._tree.blockSignals(False)

        # 선택 경로가 바뀐 경우에만 image_selected 발행
        if new_item is not None:
            new_path = self._get_item_path(new_item)
            if new_path is not None and new_path != cur_path:
                self.image_selected.emit(new_path)

    def _set_buttons_enabled(self, enabled: bool) -> None:
        self._btn_add.setEnabled(enabled)
        self._btn_add_folder.setEnabled(enabled)
        self._btn_del.setEnabled(enabled)
