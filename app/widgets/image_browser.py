import shutil
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QPushButton, QLabel, QFileDialog, QMessageBox, QProgressBar,
    QComboBox, QLineEdit, QApplication,
)
from PyQt6.QtGui import QColor, QKeyEvent
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QTimer, QSize, QEvent, QObject
from app.core.i18n import t

from app.core.annotation_store import get_label_status
from app.core.file_io import retry_on_permission_error
from app.core.logger import get_logger
from app.core import project as _project
from app.widgets.icons import icon as svg_icon, pixmap as svg_pixmap

log = get_logger(__name__)

SUPPORTED = ("*.jpg", "*.jpeg", "*.png", "*.bmp", "*.tiff", "*.tif")
SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}

_SEARCH_DEBOUNCE_MS = 200

_STATUS_ICON_SIZE = 14

# icon name, color
_STATUS_STYLE = {
    "labeled":   ("status_dot",  "#10b981"),
    "ok":        ("check",       "#60a5fa"),
    "unlabeled": ("status_ring", "#4b5563"),
}

# 정렬 기준 mode_key — 표시 레이블은 i18n 키 "browser.sort.{mode_key}" 로 조회
# NOTE: "폴더" 그룹핑 모드는 지원하지 않음 — reload()가 images_dir() 비재귀 스캔만 하고
# 이미지 추가 경로도 전부 평탄 복사라 하위폴더 구조 자체가 만들어지지 않음 (BUG-005, QA.md 참고)
_SORT_MODE_KEYS = ["name_asc", "name_desc", "status_done", "status_todo"]

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
                    retry_on_permission_error(lambda: shutil.copy2(src, dst))
                    copied += 1
                except (PermissionError, OSError) as e:
                    log.warning(f"이미지 복사 실패 — 건너뜀: {src} → {dst}: {e}")
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
        self._mutation_guard = lambda: True
        self._search_debounce = QTimer(self)
        self._search_debounce.setSingleShot(True)
        self._search_debounce.setInterval(_SEARCH_DEBOUNCE_MS)
        self._search_debounce.timeout.connect(self._apply_display)
        self._build_ui()
        self.reload()

    def set_mutation_guard(self, guard) -> None:
        self._mutation_guard = guard

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
        self._search_edit.setPlaceholderText(t("browser.search_placeholder"))
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.setStyleSheet(
            "QLineEdit { background:#111418; border:1px solid #374151; "
            "border-radius:4px; padding:3px 6px; color:#e5e7eb; font-size:11px; }"
        )
        self._search_edit.textChanged.connect(self._on_search_changed)
        layout.addWidget(self._search_edit)

        # ── 정렬 콤보 ─────────────────────────────────────────────────────────
        sort_row = QHBoxLayout()
        sort_lbl = QLabel(t("browser.sort_label"))
        sort_lbl.setStyleSheet("font-size:11px; color:#9ca3af;")
        sort_row.addWidget(sort_lbl)
        self._sort_combo = QComboBox()
        self._sort_combo.setStyleSheet("font-size:11px;")
        for mode_key in _SORT_MODE_KEYS:
            self._sort_combo.addItem(t(f"browser.sort.{mode_key}"))
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
        self._tree.setIconSize(QSize(_STATUS_ICON_SIZE, _STATUS_ICON_SIZE))
        self._tree.setStyleSheet(_TREE_STYLE)
        self._tree.currentItemChanged.connect(self._on_current_item_changed)
        self._tree.installEventFilter(self)
        layout.addWidget(self._tree)

        # ── 범례 ──────────────────────────────────────────────────────────────
        legend = QHBoxLayout()
        legend.setSpacing(3)
        for icon_name, color, label in [
            ("status_dot",  "#10b981", t("browser.legend_labeled")),
            ("check",       "#60a5fa", t("browser.legend_ok")),
            ("status_ring", "#4b5563", t("browser.legend_unlabeled")),
        ]:
            icon_lbl = QLabel()
            icon_lbl.setPixmap(svg_pixmap(icon_name, color, 12))
            legend.addWidget(icon_lbl)
            text_lbl = QLabel(label)
            text_lbl.setStyleSheet(f"font-size:10px; color:{color}; margin-right:6px;")
            legend.addWidget(text_lbl)
        legend.addStretch()
        layout.addLayout(legend)

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
        icon_name, color = _STATUS_STYLE[status]
        item.setIcon(0, svg_icon(icon_name, color, _STATUS_ICON_SIZE))
        item.setText(0, self._rel_name(path))
        item.setForeground(0, QColor(color))

    def refresh_items(self, paths: list[Path]) -> None:
        """Refresh known statuses and reapply sorting without rescanning the project."""
        for path in paths:
            if path in self._status_cache:
                status = get_label_status(path)
                self._status_cache[path] = status
                if self._sort_mode in ("name_asc", "name_desc"):
                    item = self._path_to_item.get(path)
                    if item is not None:
                        icon_name, color = _STATUS_STYLE[status]
                        item.setIcon(0, svg_icon(icon_name, color, _STATUS_ICON_SIZE))
                        item.setText(0, self._rel_name(path))
                        item.setForeground(0, QColor(color))
        if self._sort_mode not in ("name_asc", "name_desc"):
            self._apply_display()

    def current_path(self) -> Path | None:
        """현재 선택된 이미지 경로. 선택 없으면 None."""
        return self._get_item_path(self._tree.currentItem())

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
        """현재 이미지에서 step 만큼 이동 (±1)."""
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
        self._sort_mode = _SORT_MODE_KEYS[idx]
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

    def _on_delete(self) -> None:
        if not self._mutation_guard():
            return
        """선택된 이미지(들) 삭제."""
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

        # 삭제된 항목만 캐시에서 제거 — reload()(전체 재스캔 + 이미지마다
        # get_label_status() 디스크 I/O)를 다시 부르면 남은 이미지 수에 비례한
        # 비용이 드는데, 이미 상태를 알고 있는 항목이라 재조회가 불필요하다.
        self._all_paths = [p for p in self._all_paths if p not in deleted]
        for p in deleted:
            self._status_cache.pop(p, None)
        self._apply_display()

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

    # ── 내부 헬퍼 ─────────────────────────────────────────────────────────────

    def _get_item_path(self, item: QTreeWidgetItem | None) -> Path | None:
        """아이템의 UserRole 데이터로 Path 반환. item이 None이거나 미설정이면 None."""
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
        icon_name, color = _STATUS_STYLE[status]
        label = display_name if display_name is not None else self._rel_name(path)
        item = QTreeWidgetItem()
        item.setIcon(0, svg_icon(icon_name, color, _STATUS_ICON_SIZE))
        item.setText(0, label)
        item.setForeground(0, QColor(color))
        item.setData(0, _PATH_ROLE, path)   # ← Path 를 아이템에 직접 저장
        return item

    def _select_by_index(self, idx: int) -> None:
        """_paths[idx] 를 선택."""
        if not (0 <= idx < len(self._paths)):
            return
        item = self._path_to_item.get(self._paths[idx])
        if item is None:
            return
        self._tree.setCurrentItem(item)
        self._tree.scrollToItem(item)

    def _apply_display(self) -> None:
        """_all_paths 에 필터·정렬을 적용해 _paths + 트리 위젯 갱신."""
        # 현재 선택 기억
        selected_paths = set(self.selected_paths())
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
        for path in selected_paths:
            item = self._path_to_item.get(path)
            if item is not None:
                item.setSelected(True)
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
