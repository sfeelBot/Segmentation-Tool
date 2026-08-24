"""설정 다이얼로그 — 언어 선택, 로그 경로 확인 등."""
import subprocess
import sys
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QPushButton, QGroupBox, QMessageBox, QLineEdit,
    QApplication, QWidget, QTableWidget, QTableWidgetItem, QHeaderView,
    QTabWidget, QFileDialog,
)
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtCore import Qt, QSize

from app.core.i18n import (
    TRANSLATIONS, get_language, set_language, save_settings, t,
)
from app.core.logger import log_file_path, error_log_file_path
from app.core.perf_logger import PERF_LOG
from app.core.project import get_projects_root, set_projects_root, default_projects_root
from app.widgets.icons import icon as svg_icon


LANG_DISPLAY = {
    "ko": "🇰🇷  한국어",
    "en": "🇺🇸  English",
}

SHORTCUTS: list[tuple[str, str]] = [
    # ── 도구 (왼손 QWER 배치) ────────────────────────────────────────────
    ("Q",               "sc.polygon"),
    ("W",               "sc.brush"),
    ("E",               "sc.brush_fill"),
    ("R",               "sc.eraser"),
    ("D",               "sc.eraser_flood"),
    ("A",               "sc.select"),
    ("S",               "sc.pan"),
    # ── 뷰 ─────────────────────────────────────────────────────────────
    ("G",               "sc.ok_toggle"),
    ("F",               "sc.ann_visible"),
    ("T",               "sc.fullscreen"),
    ("1 / 2 / 3 / 4",  "sc.channel_orig"),
    # ── 이미지 이동 ─────────────────────────────────────────────────────
    ("Z",               "sc.prev_image"),
    ("X",               "sc.next_image"),
    # ── 액션 ────────────────────────────────────────────────────────────
    ("V",               "sc.copy_prev"),
    ("Ctrl + Z",        "sc.undo"),
    ("Del",             "sc.delete"),
    ("Esc",             "sc.cancel"),
    # ── 캔버스 조작 ─────────────────────────────────────────────────────
    ("Space + drag",    "sc.space_pan"),
    ("우클릭 + drag",   "sc.rmb_pan"),
    ("휠",              "sc.wheel_zoom"),
    ("[  /  -",         "sc.brush_smaller"),
    ("]  /  +",         "sc.brush_bigger"),
    ("더블클릭",        "sc.polygon_close"),
    ("드래그 (선택 후)", "sc.move_drag"),
]


class SettingsDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("settings.title"))
        self.setMinimumSize(560, 560)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        tabs = QTabWidget()
        tabs.addTab(self._build_general_tab(),   "일반")
        tabs.addTab(self._build_paths_tab(),     "경로")
        tabs.addTab(self._build_shortcut_tab(),  t("settings.shortcuts"))
        tabs.addTab(self._build_logs_tab(),      t("settings.logs"))
        layout.addWidget(tabs, stretch=1)

        # ── 하단 Save/Cancel ─────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._btn_cancel = QPushButton(t("common.cancel"))
        self._btn_save   = QPushButton(t("common.save"))
        self._btn_save.setStyleSheet("background:#065f46; font-weight:bold;")
        self._btn_cancel.clicked.connect(self.reject)
        self._btn_save.clicked.connect(self._on_save)
        btn_row.addWidget(self._btn_cancel)
        btn_row.addWidget(self._btn_save)
        layout.addLayout(btn_row)

    # ── 탭별 ─────────────────────────────────────────────────────────────────

    def _build_general_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(10)

        lang_box = QGroupBox(t("settings.language"))
        lang_layout = QVBoxLayout(lang_box)
        lang_layout.setSpacing(6)
        self._lang_combo = QComboBox()
        for code in TRANSLATIONS.keys():
            self._lang_combo.addItem(LANG_DISPLAY.get(code, code), code)
        idx = self._lang_combo.findData(get_language())
        if idx >= 0:
            self._lang_combo.setCurrentIndex(idx)
        lang_layout.addWidget(self._lang_combo)

        hint = QLabel(t("settings.language.hint"))
        hint.setStyleSheet("color:#9ca3af; font-size:11px;")
        hint.setWordWrap(True)
        lang_layout.addWidget(hint)

        lay.addWidget(lang_box)
        lay.addStretch()
        return w

    def _build_paths_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(10)

        proj_box = QGroupBox("프로젝트 저장 경로")
        pl = QVBoxLayout(proj_box)

        desc = QLabel(
            "새 프로젝트를 만들 때 기본으로 사용하는 폴더입니다.\n"
            "기존 프로젝트 데이터는 이동되지 않습니다."
        )
        desc.setStyleSheet("color:#9ca3af; font-size:11px;")
        desc.setWordWrap(True)
        pl.addWidget(desc)

        path_row = QHBoxLayout()
        self._projects_root_field = QLineEdit(str(get_projects_root()))
        self._projects_root_field.setReadOnly(True)
        self._projects_root_field.setStyleSheet(
            "font-family: Consolas, 'Courier New', monospace; font-size:11px;"
        )
        path_row.addWidget(self._projects_root_field, stretch=1)

        btn_browse = QPushButton("찾아보기")
        btn_browse.clicked.connect(self._on_browse_projects_root)
        path_row.addWidget(btn_browse)

        btn_reset = QPushButton("↺  기본값")
        btn_reset.setToolTip("앱 폴더 내 'projects/' 로 초기화")
        btn_reset.clicked.connect(self._on_reset_projects_root)
        path_row.addWidget(btn_reset)

        pl.addLayout(path_row)
        lay.addWidget(proj_box)
        lay.addStretch()
        return w

    def _on_browse_projects_root(self) -> None:
        from pathlib import Path
        current = str(get_projects_root())
        folder = QFileDialog.getExistingDirectory(
            self, "프로젝트 기본 저장 폴더 선택", current
        )
        if folder:
            self._projects_root_field.setText(folder)
            set_projects_root(Path(folder))
            QMessageBox.information(
                self, "저장 완료",
                f"프로젝트 기본 경로가 변경되었습니다.\n\n{folder}\n\n"
                "다음 번 '새 프로젝트' 생성 시부터 이 경로를 사용합니다."
            )

    def _on_reset_projects_root(self) -> None:
        default = default_projects_root()
        self._projects_root_field.setText(str(default))
        set_projects_root(default)
        QMessageBox.information(
            self, "초기화 완료",
            f"프로젝트 기본 경로를 기본값으로 되돌렸습니다.\n\n{default}"
        )

    def _build_shortcut_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(6)

        hint = QLabel(t("settings.shortcuts.hint"))
        hint.setStyleSheet("color:#9ca3af; font-size:11px;")
        lay.addWidget(hint)

        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(["키", "기능"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.setShowGrid(False)
        table.setAlternatingRowColors(True)
        hdr = table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

        mono = QFont("Consolas", 10)
        mono.setBold(True)
        for key, desc_key in SHORTCUTS:
            row = table.rowCount()
            table.insertRow(row)
            key_item = QTableWidgetItem(f"  {key}  ")
            key_item.setFont(mono)
            key_item.setForeground(QColor("#60a5fa"))
            key_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(row, 0, key_item)
            desc_item = QTableWidgetItem(t(desc_key))
            desc_item.setForeground(QColor("#e5e7eb"))
            table.setItem(row, 1, desc_item)
        lay.addWidget(table)
        return w

    def _build_logs_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(8)

        hint = QLabel(t("settings.logs.hint"))
        hint.setStyleSheet("color:#9ca3af; font-size:11px;")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        lay.addWidget(self._build_path_row(
            t("settings.logs.all"),
            log_file_path().resolve(),
            accent="#60a5fa",
        ))
        lay.addWidget(self._build_path_row(
            t("settings.logs.errors"),
            error_log_file_path().resolve(),
            accent="#fbbf24",
        ))
        lay.addWidget(self._build_path_row(
            "성능 로그 (perf.log)",
            PERF_LOG.resolve(),
            accent="#a78bfa",
        ))

        folder_row = QHBoxLayout()
        folder_row.addStretch()
        self._btn_open_folder = QPushButton(t("settings.logs.open_folder"))
        self._btn_open_folder.clicked.connect(self._on_open_log_folder)
        folder_row.addWidget(self._btn_open_folder)
        lay.addLayout(folder_row)

        lay.addStretch()
        return w

    def _build_path_row(self, label: str, path: Path, accent: str) -> QWidget:
        """라벨 + 경로 입력(readonly) + 복사 버튼을 한 묶음 위젯으로."""
        container = QWidget()
        wrap = QVBoxLayout(container)
        wrap.setContentsMargins(0, 0, 0, 0)
        wrap.setSpacing(2)

        lbl = QLabel(label)
        lbl.setStyleSheet(f"color:{accent}; font-size:12px; font-weight:bold;")
        wrap.addWidget(lbl)

        row = QHBoxLayout()
        row.setSpacing(4)
        field = QLineEdit(str(path))
        field.setReadOnly(True)
        field.setStyleSheet(
            "font-family: Consolas, 'Courier New', monospace; "
            "font-size:11px; color:#e5e7eb;"
        )
        field.setCursorPosition(0)
        row.addWidget(field, stretch=1)

        btn_copy = QPushButton()
        btn_copy.setIcon(svg_icon("clipboard"))
        btn_copy.setIconSize(QSize(14, 14))
        btn_copy.setFixedWidth(36)
        btn_copy.setToolTip(t("settings.logs.copy_path"))
        btn_copy.clicked.connect(lambda _=False, p=str(path): self._on_copy(p, btn_copy))
        row.addWidget(btn_copy)

        wrap.addLayout(row)
        return container

    # ── 슬롯 ─────────────────────────────────────────────────────────────────

    def _on_save(self) -> None:
        new_lang = self._lang_combo.currentData()
        old_lang = get_language()

        if new_lang != old_lang:
            save_settings({"language": new_lang})
            set_language(new_lang)
            QMessageBox.information(
                self,
                t("settings.restart_title"),
                t("settings.restart_msg"),
            )
        self.accept()

    def _on_copy(self, path_str: str, btn: QPushButton) -> None:
        QApplication.clipboard().setText(path_str)
        orig = btn.text()
        btn.setText("✓")
        # 다이얼로그 재열람 시 자연스럽게 리셋됨 — 별도 타이머 생략

    def _on_open_log_folder(self) -> None:
        folder = log_file_path().resolve().parent
        folder.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer.exe", str(folder)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception:
            pass
