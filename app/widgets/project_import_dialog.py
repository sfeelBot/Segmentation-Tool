"""zip 백업 파일에서 프로젝트를 복원(가져오기) — `project_export_dialog.py`(내보내기)의
대칭 짝. 압축 해제(파일 I/O)는 `_ProjectImportWorker.run()` 안에서 수행하고,
검증·경로 계산·zip slip 방지는 전부 Qt 비의존 `app/core/project_export.py`에 있다.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QMessageBox,
)
from PyQt6.QtCore import pyqtSignal, QThread

from app.core import project as proj
from app.core.project_export import (
    ProjectImportCancelled, ProjectImportResult, ProjectZipError, import_project_zip,
)
from app.core.i18n import t
from app.core.logger import get_logger

log = get_logger(__name__)


class _ProjectImportWorker(QThread):
    """`_ProjectExportWorker`와 동일한 패턴 — 진행률 시그널 + 성공 여부를 포함한
    finished 시그널 하나로 결과 전달."""

    progress = pyqtSignal(int, int, str)   # done, total, filename
    finished = pyqtSignal(bool, str)       # success, message

    def __init__(self, zip_path: Path, dest_root: Path, parent=None) -> None:
        super().__init__(parent)
        self._zip_path = zip_path
        self._dest_root = dest_root
        self._cancel_requested = False
        self.result: ProjectImportResult | None = None

    def cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        try:
            result = import_project_zip(
                self._zip_path,
                self._dest_root,
                progress_cb=lambda done, total, name: self.progress.emit(done, total, name),
                should_cancel=lambda: self._cancel_requested,
            )
        except ProjectImportCancelled:
            self.finished.emit(False, t("project_import.cancelled"))
            return
        except ProjectZipError as e:
            log.warning(f"프로젝트 가져오기 검증 실패: {e}")
            self.finished.emit(False, t("project_import.invalid_zip").format(reason=str(e)))
            return
        except Exception as e:
            log.exception("프로젝트 가져오기 실패")
            self.finished.emit(False, str(e))
            return

        self.result = result
        msg = t("project_import.done").format(name=result.dir_name, n=result.extracted)
        if result.skipped:
            msg += "\n" + t("project_import.skipped_warning").format(n=result.skipped)
        self.finished.emit(True, msg)


class ProjectImportDialog(QDialog):
    """zip 파일 경로를 받아 `get_projects_root()` 하위로 가져온다."""

    def __init__(self, zip_path: Path, parent=None) -> None:
        super().__init__(parent)
        self._zip_path = Path(zip_path)
        self._dest_root = proj.get_projects_root()
        self._worker: _ProjectImportWorker | None = None
        self._imported_ok = False

        self.setWindowTitle(t("project_import.title"))
        self.setMinimumWidth(560)
        self._build_ui()

    # ── UI 구성 ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(16, 16, 16, 16)

        header = QLabel(f"📥  {self._zip_path.name}")
        header.setStyleSheet("font-weight:bold; font-size:13px;")
        root.addWidget(header)
        path_lbl = QLabel(str(self._zip_path))
        path_lbl.setStyleSheet("color:#6b7280; font-size:11px;")
        path_lbl.setWordWrap(True)
        root.addWidget(path_lbl)

        dest_lbl = QLabel(t("project_import.dest_root") + f": {self._dest_root}")
        dest_lbl.setStyleSheet("color:#9ca3af; font-size:11px;")
        dest_lbl.setWordWrap(True)
        root.addWidget(dest_lbl)

        hint = QLabel(t("project_import.hint"))
        hint.setStyleSheet("color:#9ca3af; font-size:11px;")
        hint.setWordWrap(True)
        root.addWidget(hint)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.hide()
        root.addWidget(self._progress)

        self._lbl_status = QLabel("")
        self._lbl_status.setStyleSheet("color:#9ca3af;")
        root.addWidget(self._lbl_status)

        btn_row = QHBoxLayout()
        self._btn_cancel = QPushButton(t("project_import.cancel"))
        self._btn_cancel.clicked.connect(self._on_cancel_running)
        self._btn_cancel.hide()
        btn_row.addWidget(self._btn_cancel)
        btn_row.addStretch()
        self._btn_close = QPushButton(t("common.close"))
        self._btn_close.clicked.connect(self.reject)
        self._btn_run = QPushButton(t("project_import.run"))
        self._btn_run.setStyleSheet("background:#065f46; font-weight:bold;")
        self._btn_run.clicked.connect(self._on_run)
        btn_row.addWidget(self._btn_close)
        btn_row.addWidget(self._btn_run)
        root.addLayout(btn_row)

    # ── 슬롯 ─────────────────────────────────────────────────────────────────

    def _on_run(self) -> None:
        if not self._zip_path.exists():
            QMessageBox.critical(self, t("project_import.failed"), t("project_import.zip_missing"))
            return

        self._set_running(True)
        self._worker = _ProjectImportWorker(self._zip_path, self._dest_root, parent=self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_cancel_running(self) -> None:
        if self._worker is not None:
            self._worker.cancel()

    def _on_progress(self, done: int, total: int, name: str) -> None:
        self._progress.setMaximum(total)
        self._progress.setValue(done)
        self._lbl_status.setText(f"{done} / {total}  {name}")

    def _on_finished(self, ok: bool, message: str) -> None:
        self._set_running(False)
        if ok:
            self._imported_ok = True
            log.info(f"프로젝트 가져오기 완료: {message}")
            if self._worker is not None and self._worker.result is not None:
                proj.add_recent(self._worker.result.project.path)
            QMessageBox.information(self, t("project_import.title"), message)
            self.accept()
        else:
            log.warning(f"프로젝트 가져오기 실패/취소: {message}")
            if message != t("project_import.cancelled"):
                QMessageBox.critical(self, t("project_import.failed"), message)
            self._lbl_status.setText(message)

    # ── Qt 이벤트 ────────────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(3000)
        event.accept()

    # ── 헬퍼 ─────────────────────────────────────────────────────────────────

    def _set_running(self, running: bool) -> None:
        self._btn_run.setEnabled(not running)
        self._btn_close.setEnabled(not running)
        self._btn_cancel.setVisible(running)
        self._progress.setVisible(running)
        if not running:
            self._progress.setValue(0)
