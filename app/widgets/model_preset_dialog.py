"""AI 모델 프리셋 브라우저 팝업 — 모델 탭에서 불러오기 용."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QTextBrowser, QSplitter,
)
from PyQt6.QtCore import Qt

from app.model_presets import PRESETS, preset_by_key, load_preset_code
from app.core.i18n import t


class ModelPresetDialog(QDialog):
    """프리셋 목록 + 설명 + 에디터로 불러오기."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("AI 모델 프리셋 라이브러리")
        self.setMinimumSize(720, 500)
        self.selected_code: str | None = None
        self.selected_key:  str | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        header = QLabel("산업용 검사에 적합한 대표 세그멘테이션 모델 모음")
        header.setStyleSheet("color:#60a5fa; font-weight:bold; font-size:13px;")
        root.addWidget(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self._list = QListWidget()
        for p in PRESETS:
            item = QListWidgetItem(p.title)
            item.setData(Qt.ItemDataRole.UserRole, p.key)
            self._list.addItem(item)
        self._list.currentItemChanged.connect(self._on_list_changed)
        self._list.itemDoubleClicked.connect(self._on_load)
        splitter.addWidget(self._list)

        self._desc = QTextBrowser()
        self._desc.setStyleSheet(
            "QTextBrowser { background:#0f1419; border:1px solid #374151;"
            " border-radius:6px; padding:8px; }"
        )
        splitter.addWidget(self._desc)
        splitter.setSizes([260, 460])
        root.addWidget(splitter, stretch=1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._btn_cancel = QPushButton(t("common.cancel"))
        self._btn_cancel.clicked.connect(self.reject)
        self._btn_load = QPushButton("에디터에 불러오기")
        self._btn_load.setStyleSheet("background:#065f46; font-weight:bold; padding:6px 14px;")
        self._btn_load.setEnabled(False)
        self._btn_load.clicked.connect(self._on_load)
        btn_row.addWidget(self._btn_cancel)
        btn_row.addWidget(self._btn_load)
        root.addLayout(btn_row)

        if PRESETS:
            self._list.setCurrentRow(0)

    def _on_list_changed(self, item: QListWidgetItem, _prev) -> None:
        if not item:
            self._btn_load.setEnabled(False)
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        info = preset_by_key(key)
        if info is None:
            return
        self._desc.setHtml(
            f"<h2 style='color:#60a5fa; margin:0'>{info.title}</h2>"
            f"<p style='color:#93c5fd; margin:4px 0 12px 0;'>{info.tagline}</p>"
            f"<hr style='border:1px solid #374151'>"
            f"<p><b style='color:#e5e7eb'>활용</b><br>"
            f"<span style='color:#cbd5e1'>{info.use_case}</span></p>"
            f"<p><b style='color:#e5e7eb'>파라미터</b><br>"
            f"<span style='color:#cbd5e1'>{info.params}</span></p>"
            f"<p><b style='color:#34d399'>장점</b><br>"
            f"<span style='color:#cbd5e1'>{info.pros}</span></p>"
            f"<p><b style='color:#fbbf24'>단점</b><br>"
            f"<span style='color:#cbd5e1'>{info.cons}</span></p>"
        )
        self._btn_load.setEnabled(True)

    def _on_load(self, *_args) -> None:
        item = self._list.currentItem()
        if not item:
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        code = load_preset_code(key)
        if not code:
            return
        self.selected_key  = key
        self.selected_code = code
        self.accept()
