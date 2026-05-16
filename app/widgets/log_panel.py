"""라벨링 탭 우측 하단에 올라가는 컴팩트 로그 뷰어."""
from __future__ import annotations

import subprocess
import sys

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QPushButton,
)
from PyQt6.QtGui import QColor
from PyQt6.QtCore import Qt

from app.core.logger import bridge, log_file_path


LEVEL_COLOR = {
    "DEBUG":    "#6b7280",
    "INFO":     "#cbd5e1",
    "WARNING":  "#fbbf24",
    "ERROR":    "#f87171",
    "CRITICAL": "#dc2626",
}

LEVEL_ICON = {
    "DEBUG":    "·",
    "INFO":     "•",
    "WARNING":  "⚠",
    "ERROR":    "✖",
    "CRITICAL": "🚨",
}


class LogPanel(QWidget):
    MAX_ITEMS = 500

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build_ui()
        bridge.log_received.connect(self._on_log)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(3)

        header = QHBoxLayout()
        header.setContentsMargins(2, 0, 2, 0)
        title = QLabel("📝  로그")
        title.setStyleSheet("font-weight:bold; color:#60a5fa;")
        header.addWidget(title)
        header.addStretch()

        self._btn_clear = QPushButton("🧹")
        self._btn_clear.setFixedSize(24, 22)
        self._btn_clear.setToolTip("로그 지우기")
        self._btn_clear.clicked.connect(self._on_clear)
        header.addWidget(self._btn_clear)

        self._btn_open = QPushButton("📂")
        self._btn_open.setFixedSize(24, 22)
        self._btn_open.setToolTip(f"로그 파일이 있는 폴더 열기\n{log_file_path()}")
        self._btn_open.clicked.connect(self._on_open_file)
        header.addWidget(self._btn_open)
        root.addLayout(header)

        self._list = QListWidget()
        self._list.setStyleSheet(
            "QListWidget {"
            "  background:#0a0e14;"
            "  border:1px solid #374151;"
            "  border-radius:4px;"
            "  font-family: Consolas, 'Courier New', monospace;"
            "  font-size: 11px;"
            "}"
            "QListWidget::item { padding: 2px 4px; }"
        )
        self._list.setWordWrap(True)
        root.addWidget(self._list, stretch=1)

    # ── 슬롯 ─────────────────────────────────────────────────────────────────

    def _on_log(self, level: str, logger_name: str, msg: str) -> None:
        icon = LEVEL_ICON.get(level, "•")
        color = QColor(LEVEL_COLOR.get(level, "#cbd5e1"))

        # 너무 긴 로그는 한 줄로 잘라서 표시, 툴팁에 전체
        one_line = msg.split("\n")[0]
        if len(one_line) > 200:
            one_line = one_line[:197] + "…"
        item = QListWidgetItem(f"{icon}  {one_line}")
        item.setForeground(color)
        item.setToolTip(f"[{level}] {logger_name}\n{msg}")
        self._list.addItem(item)

        while self._list.count() > self.MAX_ITEMS:
            self._list.takeItem(0)
        self._list.scrollToBottom()

    def _on_clear(self) -> None:
        self._list.clear()

    def _on_open_file(self) -> None:
        path = log_file_path()
        folder = path.parent
        try:
            if sys.platform == "win32":
                if path.exists():
                    subprocess.Popen(["explorer.exe", "/select,", str(path)])
                else:
                    subprocess.Popen(["explorer.exe", str(folder)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", str(path) if path.exists() else str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception:
            pass
