"""프로젝트 전체를 zip으로 내보내기(백업) — 라벨 포맷 변환용 `export_dialog.py`와는
별개 기능이다. 이쪽은 프로젝트 원본(images/annotations/classes.json/project.json,
선택적으로 checkpoints/user_models)을 그대로 zip으로 패키징한다.

프로젝트를 열지 않은 상태(`project_start_dialog.py`의 최근 프로젝트 목록)에서도
호출할 수 있도록 `Project(path)`를 직접 구성해서 사용하고, `open_existing()`/
`set_current()`처럼 프로젝트 폴더에 부수효과(메타 파일 생성 등)를 남기지 않는다.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QFileDialog, QGroupBox, QProgressBar, QMessageBox,
)
from PyQt6.QtCore import pyqtSignal, QThread

from app.core.project import Project
from app.core.project_export import collect_export_entries, default_export_filename
from app.core.i18n import t
from app.core.logger import get_logger

log = get_logger(__name__)


class _ProjectExportWorker(QThread):
    """`_FolderImportWorker`(image_browser.py)와 동일한 패턴 — 진행률 시그널 +
    완료/에러를 하나의 finished 시그널(성공 여부 포함)로 전달."""

    progress = pyqtSignal(int, int, str)   # done, total, filename
    finished = pyqtSignal(bool, str)       # success, message (성공 요약 또는 에러 메시지)

    def __init__(
        self,
        project: Project,
        zip_path: Path,
        include_checkpoints: bool,
        include_user_models: bool,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._project = project
        self._zip_path = zip_path
        self._include_checkpoints = include_checkpoints
        self._include_user_models = include_user_models
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        try:
            if not self._project.path.exists():
                self.finished.emit(False, t("project_export.project_missing"))
                return

            entries = collect_export_entries(
                self._project, self._include_checkpoints, self._include_user_models,
            )
            total = len(entries)
            if total == 0:
                self.finished.emit(False, t("export.no_data"))
                return

            self._zip_path.parent.mkdir(parents=True, exist_ok=True)
            written = 0
            with zipfile.ZipFile(self._zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for i, (abs_path, arcname) in enumerate(entries, 1):
                    if self._cancel_requested:
                        break
                    self.progress.emit(i, total, abs_path.name)
                    try:
                        zf.write(abs_path, arcname)
                        written += 1
                    except OSError as e:
                        log.warning(f"내보내기 중 파일 건너뜀: {abs_path} ({e})")

            if self._cancel_requested:
                self._zip_path.unlink(missing_ok=True)
                self.finished.emit(False, t("project_export.cancelled"))
                return

            self.finished.emit(True, t("project_export.done").format(
                n=written, path=str(self._zip_path)))
        except Exception as e:
            log.exception("프로젝트 내보내기 실패")
            self._zip_path.unlink(missing_ok=True)
            self.finished.emit(False, str(e))


class ProjectExportDialog(QDialog):
    def __init__(self, project_path: Path, parent=None) -> None:
        super().__init__(parent)
        self._project = Project(Path(project_path).resolve())
        self._zip_path: Path | None = None
        self._worker: _ProjectExportWorker | None = None

        self.setWindowTitle(t("project_export.title"))
        self.setMinimumWidth(560)
        self._build_ui()

    # ── UI 구성 ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(16, 16, 16, 16)

        header = QLabel(f"🧠  {self._project.name}")
        header.setStyleSheet("font-weight:bold; font-size:13px;")
        root.addWidget(header)
        path_lbl = QLabel(str(self._project.path))
        path_lbl.setStyleSheet("color:#6b7280; font-size:11px;")
        path_lbl.setWordWrap(True)
        root.addWidget(path_lbl)

        box = QGroupBox("📦  " + t("project_export.title"))
        lay = QVBoxLayout(box)

        always = QLabel(t("project_export.always_included"))
        always.setStyleSheet("color:#9ca3af; font-size:11px;")
        always.setWordWrap(True)
        lay.addWidget(always)

        self._chk_ckpt = QCheckBox(t("project_export.include_ckpt"))
        self._chk_ckpt.setChecked(False)
        lay.addWidget(self._chk_ckpt)

        self._chk_models = QCheckBox(t("project_export.include_models"))
        self._chk_models.setChecked(True)
        lay.addWidget(self._chk_models)

        models_hint = QLabel(t("project_export.models_hint"))
        models_hint.setStyleSheet("color:#9ca3af; font-size:11px; margin-left:20px;")
        models_hint.setWordWrap(True)
        lay.addWidget(models_hint)

        out_row = QHBoxLayout()
        out_row.addWidget(QLabel(t("project_export.output") + ":"))
        self._lbl_out = QLabel("—")
        self._lbl_out.setStyleSheet("color:#60a5fa;")
        self._lbl_out.setWordWrap(True)
        out_row.addWidget(self._lbl_out, stretch=1)
        btn_pick = QPushButton("📂  " + t("project_export.choose_path"))
        btn_pick.clicked.connect(self._on_pick_path)
        out_row.addWidget(btn_pick)
        lay.addLayout(out_row)

        root.addWidget(box)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.hide()
        root.addWidget(self._progress)

        self._lbl_status = QLabel("")
        self._lbl_status.setStyleSheet("color:#9ca3af;")
        root.addWidget(self._lbl_status)

        btn_row = QHBoxLayout()
        self._btn_cancel = QPushButton(t("project_export.cancel"))
        self._btn_cancel.clicked.connect(self._on_cancel_running)
        self._btn_cancel.hide()
        btn_row.addWidget(self._btn_cancel)
        btn_row.addStretch()
        self._btn_close = QPushButton(t("common.close"))
        self._btn_close.clicked.connect(self.reject)
        self._btn_run = QPushButton(t("project_export.run"))
        self._btn_run.setStyleSheet("background:#065f46; font-weight:bold;")
        self._btn_run.clicked.connect(self._on_run)
        btn_row.addWidget(self._btn_close)
        btn_row.addWidget(self._btn_run)
        root.addLayout(btn_row)

    # ── 슬롯 ─────────────────────────────────────────────────────────────────

    def _on_pick_path(self) -> None:
        start = str(self._project.path.parent / default_export_filename(self._project))
        path, _ = QFileDialog.getSaveFileName(
            self, t("project_export.choose_path"), start, "Zip Archives (*.zip)",
        )
        if path:
            if not path.lower().endswith(".zip"):
                path += ".zip"
            self._zip_path = Path(path)
            self._lbl_out.setText(str(self._zip_path))

    def _on_run(self) -> None:
        if self._zip_path is None:
            QMessageBox.warning(self, t("project_export.title"), t("project_export.choose_first"))
            return
        if not self._project.path.exists():
            QMessageBox.critical(self, t("project_export.failed"), t("project_export.project_missing"))
            return

        self._set_running(True)
        self._worker = _ProjectExportWorker(
            self._project,
            self._zip_path,
            include_checkpoints=self._chk_ckpt.isChecked(),
            include_user_models=self._chk_models.isChecked(),
            parent=self,
        )
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
            log.info(f"프로젝트 내보내기 완료: {self._zip_path}")
            QMessageBox.information(self, t("project_export.title"), message)
            self.accept()
        else:
            log.warning(f"프로젝트 내보내기 실패/취소: {message}")
            if message != t("project_export.cancelled"):
                QMessageBox.critical(self, t("project_export.failed"), message)
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
