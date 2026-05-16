from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPlainTextEdit, QPushButton, QTextEdit, QSplitter,
    QFileDialog, QMessageBox,
)
from PyQt6.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat, QFont
from PyQt6.QtCore import Qt, QRegularExpression

from app.core.model_validator import validate
from app.core.model_loader import load_from_code, load_from_file, save_user_code
from app.widgets.model_preset_dialog import ModelPresetDialog


# ── 간단한 Python 구문 강조 ───────────────────────────────────────────────────

class _PythonHighlighter(QSyntaxHighlighter):
    _RULES: list[tuple[str, QColor]] = [
        (r"\b(import|from|as|class|def|return|if|else|elif|for|while"
         r"|pass|self|True|False|None|in|not|and|or|is|lambda|with"
         r"|raise|try|except|finally|yield|super)\b",
         QColor("#569CD6")),
        (r"\"[^\"]*\"|'[^']*'", QColor("#CE9178")),
        (r"#[^\n]*",            QColor("#6A9955")),
        (r"\b\d+(\.\d+)?\b",    QColor("#B5CEA8")),
        (r"\b(nn|torch|F)\b",   QColor("#4EC9B0")),
    ]

    def __init__(self, document):
        super().__init__(document)
        self._formats: list[tuple[QRegularExpression, QTextCharFormat]] = []
        for pattern, color in self._RULES:
            fmt = QTextCharFormat()
            fmt.setForeground(color)
            self._formats.append((QRegularExpression(pattern), fmt))

    def highlightBlock(self, text: str) -> None:
        for regex, fmt in self._formats:
            it = regex.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)


# ── ModelTab ─────────────────────────────────────────────────────────────────

class ModelTab(QWidget):
    """모델 아키텍처 코드를 입력·검증·로드하는 탭."""

    def __init__(self) -> None:
        super().__init__()
        self._loaded_model = None
        self._build_ui()

    # ── UI 구성 ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # ── 상단 툴바: 프리셋 팝업 / 파일 열기 ─────────────────────────────
        top = QHBoxLayout()
        top.addWidget(QLabel("PyTorch nn.Module 아키텍처 코드:"))
        top.addStretch()
        self._btn_preset = QPushButton("📚  AI 모델 프리셋…")
        self._btn_preset.setToolTip("프리셋 라이브러리를 열어 산업용 대표 모델을 에디터에 불러옵니다")
        self._btn_preset.setStyleSheet("background:#1e3a5f; font-weight:bold; padding:4px 12px;")
        self._btn_preset.clicked.connect(self._on_open_preset_dialog)
        top.addWidget(self._btn_preset)

        self._btn_open = QPushButton("📂  파일 열기 (.py)")
        top.addWidget(self._btn_open)
        root.addLayout(top)

        # ── 코드 편집기 / 로그 스플리터 ────────────────────────────────────────
        splitter = QSplitter(Qt.Orientation.Vertical)

        self._editor = QPlainTextEdit()
        self._editor.setFont(QFont("Consolas", 10))
        self._editor.setPlaceholderText(
            "import torch.nn as nn\n\n"
            "class MyModel(nn.Module):\n"
            "    def __init__(self, num_classes=2):\n"
            "        super().__init__()\n"
            "        self.conv = nn.Conv2d(3, num_classes, 3, padding=1)\n\n"
            "    def forward(self, x):\n"
            "        return self.conv(x)"
        )
        self._editor.setStyleSheet(
            "background:#0D1117; color:#D4D4D4; border:1px solid #374151;"
            "border-radius:6px; padding:4px;"
        )
        self._highlighter = _PythonHighlighter(self._editor.document())
        splitter.addWidget(self._editor)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setFont(QFont("Consolas", 9))
        self._log.setMaximumHeight(180)
        self._log.setStyleSheet(
            "background:#0A0E14; color:#C9D1D9; border:1px solid #374151;"
            "border-radius:6px; padding:4px;"
        )
        splitter.addWidget(self._log)
        splitter.setSizes([500, 180])

        root.addWidget(splitter, stretch=1)

        # ── 검증 / 로드 버튼 ──────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        self._btn_validate = QPushButton("🔎  검증 (Validate)")
        self._btn_load = QPushButton("✅  로드 (Load Model)")
        self._btn_load.setEnabled(False)
        self._btn_load.setStyleSheet("background:#065f46; font-weight:bold;")
        self._lbl_status = QLabel("")
        btn_row.addWidget(self._btn_validate)
        btn_row.addWidget(self._btn_load)
        btn_row.addStretch()
        btn_row.addWidget(self._lbl_status)
        root.addLayout(btn_row)

        # 시그널
        self._btn_open.clicked.connect(self._on_open_file)
        self._btn_validate.clicked.connect(self._on_validate)
        self._btn_load.clicked.connect(self._on_load)

    # ── 프리셋 팝업 ───────────────────────────────────────────────────────────

    def _on_open_preset_dialog(self) -> None:
        # 에디터에 내용이 있으면 덮어쓰기 확인
        if self._editor.toPlainText().strip():
            reply = QMessageBox.question(
                self, "에디터 내용 교체",
                "프리셋을 불러오면 에디터의 기존 코드가 덮어써집니다. 계속하시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        dlg = ModelPresetDialog(self)
        if dlg.exec() and dlg.selected_code:
            self._editor.setPlainText(dlg.selected_code)
            self._log_info(f"프리셋 불러옴: {dlg.selected_key}")

    # ── 기존 슬롯 ─────────────────────────────────────────────────────────────

    def _on_open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "모델 파일 선택", "", "Python Files (*.py)"
        )
        if not path:
            return
        self._editor.setPlainText(Path(path).read_text(encoding="utf-8"))
        self._log_info(f"파일 로드: {path}")

    def _on_validate(self) -> None:
        code = self._editor.toPlainText().strip()
        if not code:
            self._log_warn("코드가 비어 있습니다.")
            return

        self._log.clear()
        result = validate(code)

        for err in result.errors:
            self._log_error(err)
        for warn in result.warnings:
            self._log_warn(warn)

        if result.ok:
            self._log_ok(f"검증 통과 ✓  클래스: {result.model_class_name}")
            self._btn_load.setEnabled(True)
            self._lbl_status.setText(f"✓ {result.model_class_name}")
            self._lbl_status.setStyleSheet("color: #3fb950;")
        else:
            self._log_error(f"검증 실패 — {len(result.errors)}개 오류")
            self._btn_load.setEnabled(False)
            self._lbl_status.setText("✗ 검증 실패")
            self._lbl_status.setStyleSheet("color: #f85149;")

    def _on_load(self) -> None:
        code = self._editor.toPlainText().strip()
        self._log_info("모델 로드 중…")

        result = load_from_code(code)
        if not result.ok:
            self._log_error(f"로드 실패: {result.error}")
            self._lbl_status.setText("✗ 로드 실패")
            self._lbl_status.setStyleSheet("color: #f85149;")
            return

        save_user_code(code)
        self._loaded_model = result.model

        params_str = f"{result.num_params:,}"
        self._log_ok(
            f"로드 완료 ✓  클래스: {result.class_name}  파라미터: {params_str}"
        )
        self._lbl_status.setText(
            f"✓ {result.class_name} ({params_str} params)"
        )
        self._lbl_status.setStyleSheet("color: #3fb950;")

    # ── 로그 헬퍼 ─────────────────────────────────────────────────────────────

    def _log_ok(self, msg: str) -> None:
        self._log.append(f'<span style="color:#3fb950">[OK]  {msg}</span>')

    def _log_error(self, msg: str) -> None:
        self._log.append(f'<span style="color:#f85149">[ERR] {msg}</span>')

    def _log_warn(self, msg: str) -> None:
        self._log.append(f'<span style="color:#d29922">[WARN]{msg}</span>')

    def _log_info(self, msg: str) -> None:
        self._log.append(f'<span style="color:#79c0ff">[INFO]{msg}</span>')

    # ── 외부 접근 ─────────────────────────────────────────────────────────────

    @property
    def loaded_model(self):
        return self._loaded_model
