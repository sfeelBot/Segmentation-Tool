import shutil
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QFileDialog, QMessageBox, QProgressBar,
    QComboBox, QLineEdit,
)
from PyQt6.QtGui import QColor
from PyQt6.QtCore import Qt, pyqtSignal, QThread
from app.core.i18n import t

from app.core.annotation_store import get_label_status
from app.core import project as _project

SUPPORTED = ("*.jpg", "*.jpeg", "*.png", "*.bmp", "*.tiff", "*.tif")
SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}

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

# 라벨링 상태 → 정렬용 키 (숫자 클수록 "완료")
_STATUS_KEY = {"labeled": 2, "ok": 1, "unlabeled": 0}


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
        self._all_paths: list[Path] = []    # 전체 이미지 (필터·정렬 전)
        self._paths: list[Path] = []        # 현재 표시 중인 이미지 (필터+정렬 후)
        self._sort_mode: str = "name_asc"
        self._filter_text: str = ""
        self._import_worker: _FolderImportWorker | None = None
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

        # ── 이미지 목록 ───────────────────────────────────────────────────────
        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self._list.currentRowChanged.connect(self._on_row_changed)
        layout.addWidget(self._list)

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
        dataset.py 의 _collect_pairs 와 동일하게 flat 스캔 — 하위폴더 이미지는 학습 대상
        에서 제외되므로 브라우저에서도 보이지 않도록 일관성을 유지한다."""
        _project.images_dir().mkdir(parents=True, exist_ok=True)
        self._all_paths = sorted(
            p for pat in SUPPORTED
            for p in _project.images_dir().glob(pat)
        )
        self._apply_display()

    def refresh_item(self, path: Path) -> None:
        """어노테이션 저장 후 해당 항목의 상태 아이콘·색상만 갱신.
        상태 기반 정렬 중이라도 아이콘만 업데이트하고 순서 재정렬은 하지 않는다.
        (어노테이션 저장마다 전체 JSON 재읽기 방지 — 이미지 수가 많을 때 성능 보호)"""
        try:
            idx = self._paths.index(path)
        except ValueError:
            return
        item = self._list.item(idx)
        if item is None:
            return
        status = get_label_status(path)
        sym, color = _STATUS_STYLE[status]
        item.setText(f"{sym}  {self._rel_name(path)}")
        item.setForeground(QColor(color))

    def current_path(self) -> Path | None:
        row = self._list.currentRow()
        if 0 <= row < len(self._paths):
            return self._paths[row]
        return None

    # ── 슬롯 ─────────────────────────────────────────────────────────────────

    def _on_row_changed(self, row: int) -> None:
        if 0 <= row < len(self._paths):
            self.image_selected.emit(self._paths[row])

    def _on_search_changed(self, text: str) -> None:
        self._filter_text = text.strip()
        self._apply_display()

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
        """선택된 이미지(들) 삭제. 여러 개 선택 시 한 번에 모두 삭제."""
        rows = sorted({self._list.row(it) for it in self._list.selectedItems()})
        paths = [self._paths[r] for r in rows if 0 <= r < len(self._paths)]
        if not paths:
            return

        n = len(paths)
        if n == 1:
            msg = (f"'{paths[0].name}' 을 삭제하시겠습니까?\n"
                   "(어노테이션도 함께 삭제됩니다)")
        else:
            preview = ", ".join(p.name for p in paths[:3])
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
        for p in paths:
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

    def _rel_name(self, path: Path) -> str:
        """images_dir 기준 상대 경로 문자열 (하위 폴더가 없으면 파일명만)."""
        try:
            rel = path.relative_to(_project.images_dir())
            return str(rel)
        except ValueError:
            return path.name

    def _make_item(self, path: Path) -> QListWidgetItem:
        status = get_label_status(path)
        sym, color = _STATUS_STYLE[status]
        item = QListWidgetItem(f"{sym}  {self._rel_name(path)}")
        item.setForeground(QColor(color))
        return item

    def _apply_display(self) -> None:
        """_all_paths 에 필터·정렬을 적용해 _paths 와 리스트 위젯을 갱신."""
        # 현재 선택 경로 기억 (정렬/필터 후 복원용)
        cur_row = self._list.currentRow()
        cur_path: Path | None = (
            self._paths[cur_row] if 0 <= cur_row < len(self._paths) else None
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
                -_STATUS_KEY.get(get_label_status(p), 0), p.name.lower()
            ))
        elif self._sort_mode == "status_todo":
            filtered.sort(key=lambda p: (
                _STATUS_KEY.get(get_label_status(p), 0), p.name.lower()
            ))

        self._paths = filtered

        # ── 리스트 위젯 갱신 (시그널 차단) ──────────────────────────────────
        self._list.blockSignals(True)
        self._list.clear()
        for p in filtered:
            self._list.addItem(self._make_item(p))

        # 선택 복원
        new_row = -1
        if cur_path and cur_path in self._paths:
            new_row = self._paths.index(cur_path)
        elif self._paths:
            new_row = 0

        if new_row >= 0:
            self._list.setCurrentRow(new_row)
        self._list.blockSignals(False)

        # 선택 경로가 바뀐 경우에만 image_selected 발행
        if new_row >= 0:
            new_path = self._paths[new_row]
            if new_path != cur_path:
                self.image_selected.emit(new_path)

    def _set_buttons_enabled(self, enabled: bool) -> None:
        self._btn_add.setEnabled(enabled)
        self._btn_add_folder.setEnabled(enabled)
        self._btn_del.setEnabled(enabled)
