import subprocess
import sys
from pathlib import Path

from PyQt6.QtWidgets import (
    QMainWindow, QTabWidget, QStatusBar, QLabel, QPushButton, QWidget, QHBoxLayout,
)
from PyQt6.QtCore import Qt

from app.tabs.model_tab import ModelTab
from app.tabs.labeling_tab import LabelingTab
from app.tabs.training_tab import TrainingTab
from app.tabs.inference_tab import InferenceTab
from app.widgets.settings_dialog import SettingsDialog
from app.widgets.export_dialog import ExportDialog
from app.core.i18n import t
from app.core import project as _project


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._switch_requested = False

        proj = _project.current()
        proj_name = proj.name if proj else "—"
        self.setWindowTitle(f"Segmentation Model UI  ·  🧠 {proj_name}")
        self.resize(1280, 800)

        self._tabs = QTabWidget()
        self._model_tab     = ModelTab()
        self._labeling_tab  = LabelingTab()
        self._training_tab  = TrainingTab()
        self._inference_tab = InferenceTab()

        self._tabs.addTab(self._labeling_tab,  t("tab.labeling"))
        self._tabs.addTab(self._training_tab,  t("tab.training"))
        self._tabs.addTab(self._inference_tab, t("tab.inference"))
        self._tabs.addTab(self._model_tab,     t("tab.model"))

        # ── 우측 상단 코너 위젯: 프로젝트명 + 전환 + 설정 ──────────────────
        corner = QWidget()
        cl = QHBoxLayout(corner)
        cl.setContentsMargins(0, 0, 8, 0)
        cl.setSpacing(4)

        self._lbl_project = QLabel(f"🗂  {proj_name}")
        self._lbl_project.setStyleSheet(
            "color:#60a5fa; font-weight:bold; padding:4px 8px;"
        )
        self._lbl_project.setToolTip(
            t("menu.project.tip").format(name=proj_name)
            + (f"\n{proj.path}" if proj else "")
        )
        cl.addWidget(self._lbl_project)

        self._btn_switch = QPushButton("🔄")
        self._btn_switch.setFlat(True)
        self._btn_switch.setToolTip(t("project.switch.tip"))
        self._btn_switch.setFixedWidth(30)
        self._btn_switch.setStyleSheet(
            "QPushButton { font-size:15px; padding:4px; }"
            "QPushButton:hover { background:#374151; border-radius:4px; }"
        )
        self._btn_switch.clicked.connect(self._on_switch_project)
        cl.addWidget(self._btn_switch)

        self._btn_open_folder = QPushButton("📁")
        self._btn_open_folder.setFlat(True)
        self._btn_open_folder.setToolTip(t("project.open_folder"))
        self._btn_open_folder.setFixedWidth(30)
        self._btn_open_folder.setStyleSheet(
            "QPushButton { font-size:15px; padding:4px; }"
            "QPushButton:hover { background:#374151; border-radius:4px; }"
        )
        self._btn_open_folder.clicked.connect(self._on_open_project_folder)
        cl.addWidget(self._btn_open_folder)

        self._btn_export = QPushButton(t("menu.export"))
        self._btn_export.setFlat(True)
        self._btn_export.setToolTip(t("menu.export.tip"))
        self._btn_export.setFixedWidth(30)
        self._btn_export.setStyleSheet(
            "QPushButton { font-size:15px; padding:4px; }"
            "QPushButton:hover { background:#374151; border-radius:4px; }"
        )
        self._btn_export.clicked.connect(self._on_open_export)
        cl.addWidget(self._btn_export)

        self._btn_settings = QPushButton(t("menu.settings"))
        self._btn_settings.setToolTip(t("menu.settings.tip"))
        self._btn_settings.setFlat(True)
        self._btn_settings.setFixedWidth(36)
        self._btn_settings.setStyleSheet(
            "QPushButton { font-size:18px; padding:4px 8px; }"
            "QPushButton:hover { background:#374151; border-radius:4px; }"
        )
        self._btn_settings.clicked.connect(self._on_open_settings)
        cl.addWidget(self._btn_settings)

        self._tabs.setCornerWidget(corner, Qt.Corner.TopRightCorner)

        self.setCentralWidget(self._tabs)

        self._status_label = QLabel(f"프로젝트: {proj_name}  ({proj.path if proj else '—'})")
        status_bar = QStatusBar()
        status_bar.addWidget(self._status_label)
        self.setStatusBar(status_bar)

    def set_status(self, message: str) -> None:
        self._status_label.setText(message)

    def _on_open_settings(self) -> None:
        dlg = SettingsDialog(self)
        dlg.exec()

    def _on_open_export(self) -> None:
        if _project.current() is None:
            return
        dlg = ExportDialog(self)
        dlg.exec()

    def closeEvent(self, event) -> None:
        from PyQt6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self, t("ui.close_confirm_title"),
            t("ui.close_confirm_msg"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            event.accept()
        else:
            event.ignore()

    def _on_switch_project(self) -> None:
        """main() 의 while 루프로 돌아가 다이얼로그를 다시 띄운다."""
        self._switch_requested = True
        self.close()

    def _on_open_project_folder(self) -> None:
        proj = _project.current()
        if proj is None:
            return
        folder = proj.path.resolve()
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer.exe", str(folder)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception:
            pass
