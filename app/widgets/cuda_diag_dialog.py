"""CUDA 진단 결과를 보여주는 팝업 다이얼로그."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel,
    QPushButton, QTextBrowser, QVBoxLayout,
)
from PyQt6.QtCore import Qt

from app.core.cuda_diag import CudaDiagResult, DiagStatus, run_cuda_diagnostics


# status → (아이콘 HTML, 행 배경색)
_ROW_STYLE: dict[DiagStatus, tuple[str, str]] = {
    DiagStatus.OK:   ('<span style="color:#6ddf6d;font-weight:bold;">&#10003;</span>', "#0d1f0d"),
    DiagStatus.FAIL: ('<span style="color:#f87171;font-weight:bold;">&#10007;</span>', "#1f0d0d"),
    DiagStatus.WARN: ('<span style="color:#fbbf24;font-weight:bold;">&#9888;</span>',  "#1f1a0d"),
    DiagStatus.INFO: ('<span style="color:#60a5fa;">&#9432;</span>',                   "#0d1120"),
}


def _esc(s: str) -> str:
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace("\n", "<br>"))


def _build_html(result: CudaDiagResult) -> str:
    # 상단 요약 배너
    if result.cuda_available:
        banner = (
            '<div style="background:#14532d;color:#6ee7b7;padding:10px 14px;'
            'border-radius:6px;font-weight:bold;font-size:13px;margin-bottom:12px;">'
            '&#10003;&nbsp; CUDA 정상 사용 가능</div>'
        )
    else:
        banner = (
            f'<div style="background:#450a0a;color:#fca5a5;padding:10px 14px;'
            f'border-radius:6px;font-weight:bold;font-size:13px;margin-bottom:12px;">'
            f'&#10007;&nbsp; CUDA 사용 불가 &mdash; {_esc(result.root_cause)}</div>'
        )

    # 진단 항목 행들
    rows_html = []
    for item in result.items:
        icon, bg = _ROW_STYLE[item.status]
        detail_html = ""
        if item.detail:
            detail_html += (
                f'<div style="color:#9ca3af;margin:3px 0 0 22px;font-size:11px;">'
                f'{_esc(item.detail)}</div>'
            )
        if item.fix:
            detail_html += (
                f'<div style="color:#fbbf24;margin:2px 0 4px 22px;font-size:11px;">'
                f'&#8594; {_esc(item.fix)}</div>'
            )
        rows_html.append(
            f'<div style="background:{bg};border-radius:4px;'
            f'padding:5px 10px;margin-bottom:3px;">'
            f'{icon}&nbsp;<b style="color:#d1d5db;">{_esc(item.name)}</b>'
            f'<span style="color:#e5e7eb;">: {_esc(item.value)}</span>'
            f'{detail_html}'
            f'</div>'
        )

    # 권장 해결 방법 박스
    fixes_html = ""
    if result.fix_summary:
        items_li = "".join(
            f'<li style="margin:3px 0;color:#d6d3d1;">{_esc(f)}</li>'
            for f in result.fix_summary
        )
        fixes_html = (
            '<div style="background:#1c1917;border:1px solid #78350f;'
            'border-radius:6px;padding:10px 14px;margin-top:12px;">'
            '<div style="color:#fbbf24;font-weight:bold;margin-bottom:6px;">'
            '&#128161; 권장 해결 방법</div>'
            f'<ul style="margin:0;padding-left:20px;">{items_li}</ul>'
            '</div>'
        )

    return (
        '<html><body style="background:#111827;color:#e5e7eb;'
        "font-family:'Segoe UI',Arial,sans-serif;font-size:12px;\">"
        + banner
        + "".join(rows_html)
        + fixes_html
        + "</body></html>"
    )


def _build_plain(result: CudaDiagResult) -> str:
    lines: list[str] = []
    prefix = {
        DiagStatus.OK:   "[OK  ]",
        DiagStatus.FAIL: "[FAIL]",
        DiagStatus.WARN: "[WARN]",
        DiagStatus.INFO: "[INFO]",
    }
    if result.root_cause:
        lines.append(f"ROOT CAUSE: {result.root_cause}")
        lines.append("")
    for item in result.items:
        lines.append(f"{prefix[item.status]} {item.name}: {item.value}")
        if item.detail:
            for dl in item.detail.splitlines():
                lines.append(f"       {dl}")
        if item.fix:
            lines.append(f"    -> {item.fix}")
    if result.fix_summary:
        lines.append("")
        lines.append("=== 권장 해결 방법 ===")
        for f in result.fix_summary:
            lines.append(f"  - {f}")
    return "\n".join(lines)


class CudaDiagDialog(QDialog):
    """CUDA 진단 결과 팝업. result=None 이면 진단을 내부에서 실행한다."""

    def __init__(self, result: CudaDiagResult | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("CUDA / GPU 환경 진단")
        self.setMinimumSize(640, 520)
        self.resize(720, 580)
        self.setWindowFlags(
            self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint
        )
        self._result = result if result is not None else run_cuda_diagnostics()
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(12, 12, 12, 12)

        # 제목 행
        title_row = QHBoxLayout()
        title_lbl = QLabel("CUDA / GPU 환경 진단")
        title_lbl.setStyleSheet(
            "font-size:14px;font-weight:bold;color:#e5e7eb;"
        )
        title_row.addWidget(title_lbl)
        title_row.addStretch()

        btn_rerun = QPushButton("&#8635; 재진단")
        btn_rerun.setToolTip("진단을 다시 실행합니다")
        btn_rerun.clicked.connect(self._rerun)
        title_row.addWidget(btn_rerun)
        layout.addLayout(title_row)

        # 본문 뷰어
        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(False)
        self._browser.setStyleSheet(
            "background:#111827;border:1px solid #374151;border-radius:6px;"
        )
        self._browser.setHtml(_build_html(self._result))
        layout.addWidget(self._browser)

        # 하단 버튼 행
        btn_row = QHBoxLayout()
        btn_copy = QPushButton("클립보드 복사")
        btn_copy.setToolTip("진단 결과를 텍스트로 복사합니다")
        btn_copy.clicked.connect(self._copy)
        btn_row.addWidget(btn_copy)
        btn_row.addStretch()
        btn_close = QPushButton("닫기")
        btn_close.setDefault(True)
        btn_close.setFixedWidth(80)
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

    def _rerun(self) -> None:
        self._result = run_cuda_diagnostics()
        self._browser.setHtml(_build_html(self._result))

    def _copy(self) -> None:
        QApplication.clipboard().setText(_build_plain(self._result))


def show_cuda_diag(parent=None, result: CudaDiagResult | None = None) -> None:
    """CUDA 진단 다이얼로그를 열고 닫힐 때까지 기다린다."""
    dlg = CudaDiagDialog(result=result, parent=parent)
    dlg.exec()
