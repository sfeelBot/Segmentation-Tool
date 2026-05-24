import shutil
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QFileDialog, QMessageBox, QProgressBar,
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
        self._paths: list[Path] = []
        self._import_worker: _FolderImportWorker | None = None
        self._build_ui()
        self.reload()

    # ── UI 구성 ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

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

        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self._list.currentRowChanged.connect(self._on_row_changed)
        layout.addWidget(self._list)

        # 범례
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

    # ── 공개 ──────────────────────────────────────────────────────────────────

    def reload(self) -> None:
        _project.images_dir().mkdir(parents=True, exist_ok=True)
        prev_path = self._paths[self._list.currentRow()] \
            if 0 <= self._list.currentRow() < len(self._paths) else None

        self._paths = sorted(
            p for pat in SUPPORTED
            for p in _project.images_dir().glob(pat)
        )
        self._list.clear()
        for p in self._paths:
            self._list.addItem(self._make_item(p))

        # 선택 복원
        if prev_path and prev_path in self._paths:
            self._list.setCurrentRow(self._paths.index(prev_path))
        elif self._paths:
            row = min(max(self._list.currentRow(), 0), len(self._paths) - 1)
            self._list.setCurrentRow(row)

    def refresh_item(self, path: Path) -> None:
        """어노테이션 저장 후 해당 항목의 상태 표시만 갱신."""
        try:
            idx = self._paths.index(path)
        except ValueError:
            return
        item = self._list.item(idx)
        if item is None:
            return
        status = get_label_status(path)
        sym, color = _STATUS_STYLE[status]
        item.setText(f"{sym}  {path.name}")
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
                   f"(어노테이션도 함께 삭제됩니다)")
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
                # 파일이 잠겨있거나 권한 문제 — 개별 실패는 무시하고 계속
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

    # ── 내부 ─────────────────────────────────────────────────────────────────

    def _make_item(self, path: Path) -> QListWidgetItem:
        status = get_label_status(path)
        sym, color = _STATUS_STYLE[status]
        item = QListWidgetItem(f"{sym}  {path.name}")
        item.setForeground(QColor(color))
        return item

    def _set_buttons_enabled(self, enabled: bool) -> None:
        self._btn_add.setEnabled(enabled)
        self._btn_add_folder.setEnabled(enabled)
        self._btn_del.setEnabled(enabled)
