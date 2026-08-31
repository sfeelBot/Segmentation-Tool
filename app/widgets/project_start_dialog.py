"""앱 시작 시 또는 프로젝트 전환 시 보여주는 프로젝트 선택 다이얼로그."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QFileDialog, QMessageBox,
    QInputDialog, QGroupBox, QMenu,
)
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtCore import Qt

from app.core import project as proj
from app.core.i18n import t
from app.core.logger import get_logger
from app.widgets.project_export_dialog import ProjectExportDialog
from app.widgets.project_import_dialog import ProjectImportDialog

log = get_logger(__name__)


class ProjectStartDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("project.title"))
        self.setMinimumSize(520, 460)
        self._build_ui()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        # ── 헤더 ─────────────────────────────────────────────────────────────
        header = QLabel("Segmentation Model UI")
        hf = QFont()
        hf.setPointSize(18)
        hf.setBold(True)
        header.setFont(hf)
        header.setStyleSheet("color:#60a5fa;")
        root.addWidget(header)

        sub = QLabel(t("project.welcome"))
        sub.setStyleSheet("color:#9ca3af;")
        root.addWidget(sub)

        # ── 액션 버튼 두 개 ───────────────────────────────────────────────────
        action_row = QHBoxLayout()
        action_row.setSpacing(10)

        self._btn_new = QPushButton(t("project.new"))
        self._btn_new.setToolTip(t("project.new.tip"))
        self._btn_new.setStyleSheet(
            "QPushButton { padding:16px 18px; font-size:14px; font-weight:bold;"
            " background:#065f46; border:1px solid #10b981; border-radius:8px; }"
            "QPushButton:hover { background:#047857; }"
        )
        self._btn_new.clicked.connect(self._on_new)
        action_row.addWidget(self._btn_new, stretch=1)

        self._btn_open = QPushButton(t("project.open"))
        self._btn_open.setToolTip(t("project.open.tip"))
        self._btn_open.setStyleSheet(
            "QPushButton { padding:16px 18px; font-size:14px; font-weight:bold;"
            " background:#1e3a5f; border:1px solid #60a5fa; border-radius:8px; }"
            "QPushButton:hover { background:#1e40af; }"
        )
        self._btn_open.clicked.connect(self._on_open)
        action_row.addWidget(self._btn_open, stretch=1)
        root.addLayout(action_row)

        # ── 가져오기(zip 백업 복원) — 별도 줄, 보조 액션 ─────────────────────
        import_row = QHBoxLayout()
        self._btn_import = QPushButton(t("project_import.action"))
        self._btn_import.setToolTip(t("project_import.action.tip"))
        self._btn_import.clicked.connect(self._on_import)
        import_row.addWidget(self._btn_import)
        import_row.addStretch()
        root.addLayout(import_row)

        # ── 최근 프로젝트 ────────────────────────────────────────────────────
        recent_box = QGroupBox(t("project.recent"))
        rl = QVBoxLayout(recent_box)
        self._recent_list = QListWidget()
        self._recent_list.itemDoubleClicked.connect(self._on_recent_double_clicked)
        self._recent_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._recent_list.customContextMenuRequested.connect(self._on_recent_context_menu)
        rl.addWidget(self._recent_list)
        self._populate_recent()
        root.addWidget(recent_box, stretch=1)

    def _populate_recent(self) -> None:
        self._recent_list.clear()
        recents = proj.recent(max_count=10)
        if not recents:
            ph = QListWidgetItem(t("project.recent.empty"))
            ph.setForeground(QColor("#6b7280"))
            ph.setFlags(ph.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self._recent_list.addItem(ph)
            return
        for p in recents:
            meta_file = p / "project.json"
            name = p.name
            updated = ""
            try:
                if meta_file.exists():
                    import json
                    m = json.loads(meta_file.read_text(encoding="utf-8"))
                    if "updated_at" in m:
                        updated = f"   ·   {_format_date(m['updated_at'])}"
            except Exception:
                pass
            label = f"{name}{updated}\n        {p}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, str(p))
            self._recent_list.addItem(item)

    # ── 슬롯 ─────────────────────────────────────────────────────────────────

    def _on_new(self) -> None:
        name, ok = QInputDialog.getText(
            self, t("project.new"), t("project.new.prompt")
        )
        if not ok or not name.strip():
            return
        try:
            p = proj.create(name.strip())
            proj.set_current(p)
            self.accept()
        except Exception as e:
            log.exception("프로젝트 생성 실패")
            QMessageBox.critical(self, t("project.new.error"), str(e))

    def _on_open(self) -> None:
        start_dir = str(proj.get_projects_root())
        path = QFileDialog.getExistingDirectory(
            self, t("project.open"), start_dir
        )
        if not path:
            return
        self._try_open(Path(path))

    def _on_recent_double_clicked(self, item: QListWidgetItem) -> None:
        path_str = item.data(Qt.ItemDataRole.UserRole)
        if not path_str:
            return
        self._try_open(Path(path_str))

    def _on_recent_context_menu(self, pos) -> None:
        item = self._recent_list.itemAt(pos)
        if item is None:
            return
        path_str = item.data(Qt.ItemDataRole.UserRole)
        if not path_str:
            return
        menu = QMenu(self)
        act_export = menu.addAction(t("project_export.action"))
        act_export.setToolTip(t("project_export.action.tip"))
        chosen = menu.exec(self._recent_list.mapToGlobal(pos))
        if chosen == act_export:
            self._on_export_project(Path(path_str))

    def _on_import(self) -> None:
        zip_path, _ = QFileDialog.getOpenFileName(
            self, t("project_import.choose_zip"), str(proj.get_projects_root()),
            "Zip Archives (*.zip)",
        )
        if not zip_path:
            return
        dlg = ProjectImportDialog(Path(zip_path), parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._populate_recent()

    def _on_export_project(self, path: Path) -> None:
        if not path.exists():
            QMessageBox.warning(self, t("project_export.title"), t("project_export.project_missing"))
            self._populate_recent()
            return
        dlg = ProjectExportDialog(path, parent=self)
        dlg.exec()

    def _try_open(self, path: Path) -> None:
        try:
            p = proj.open_existing(path)
            proj.set_current(p)
            self.accept()
        except Exception as e:
            log.exception(f"프로젝트 열기 실패: {path}")
            QMessageBox.critical(self, t("project.open.error"), str(e))


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────

def _format_date(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return iso
