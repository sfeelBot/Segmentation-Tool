"""Zone 탭 — 시나리오 7단계 진행 안내 위젯. 클릭 전환·잠금 없는 순수 표시용
(CLAUDE.md 디자인 원칙 "위저드 강제 금지" — 상태만 보여주고 아무 것도 막지 않는다)."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

_STEP_LABELS = [
    "① 체크포인트", "② 이미지", "③ 영역 설정", "④ 추론 실행",
    "⑤ 진행상황", "⑥ 결과 보정", "⑦ 결과 분석",
]
_DONE_BG, _DONE_FG = "#10b981", "#34d399"
_CUR_BG, _CUR_BORDER, _CUR_FG = "#1e3a5f", "#60a5fa", "#60a5fa"
_PENDING_FG = "#6b7280"


class ZoneStepIndicator(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            "background:#1f2329;border:1px solid #374151;border-radius:8px;"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 8, 18, 8)
        layout.setSpacing(0)
        self._circles: list[QLabel] = []
        self._captions: list[QLabel] = []
        self._lines: list[QFrame] = []
        for i, text in enumerate(_STEP_LABELS):
            col = QVBoxLayout()
            col.setSpacing(3)
            circle = QLabel()
            circle.setAlignment(Qt.AlignmentFlag.AlignCenter)
            caption = QLabel(text)
            caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
            caption.setStyleSheet("background:transparent;border:none;")
            col.addWidget(circle, alignment=Qt.AlignmentFlag.AlignCenter)
            col.addWidget(caption)
            wrap = QWidget()
            wrap.setLayout(col)
            wrap.setMinimumWidth(84)
            layout.addWidget(wrap)
            self._circles.append(circle)
            self._captions.append(caption)
            if i < len(_STEP_LABELS) - 1:
                line = QFrame()
                line.setFixedHeight(2)
                layout.addWidget(line, stretch=1)
                self._lines.append(line)
        self.set_state(1, set())

    def set_state(self, current: int, completed: set[int]) -> None:
        """current: 1~7 (현재/다음 추천 단계). completed: 완료로 표시할 단계 번호 집합."""
        for i in range(7):
            step = i + 1
            circle, caption = self._circles[i], self._captions[i]
            if step in completed:
                size = 24
                circle.setText("✓")
                circle.setStyleSheet(
                    f"border-radius:{size // 2}px;background:{_DONE_BG};"
                    "color:#0d1f16;font-weight:bold;border:none;"
                )
                caption.setStyleSheet(f"font-size:10.5px;color:{_DONE_FG};background:transparent;border:none;")
            elif step == current:
                size = 26
                circle.setText(str(step))
                circle.setStyleSheet(
                    f"border-radius:{size // 2}px;background:{_CUR_BG};"
                    f"border:2px solid {_CUR_BORDER};color:{_CUR_FG};font-weight:bold;"
                )
                caption.setStyleSheet(
                    f"font-size:11px;color:{_CUR_FG};font-weight:bold;background:transparent;border:none;"
                )
            else:
                size = 24
                circle.setText(str(step))
                circle.setStyleSheet(
                    f"border-radius:{size // 2}px;background:#1a1d23;"
                    f"border:1px solid #4b5563;color:{_PENDING_FG};"
                )
                caption.setStyleSheet(f"font-size:10.5px;color:{_PENDING_FG};background:transparent;border:none;")
            circle.setFixedSize(size, size)
        for i, line in enumerate(self._lines):
            left_done = (i + 1) in completed
            if left_done and (i + 2) in completed:
                color = _DONE_FG
            elif left_done and (i + 2) == current:
                color = _CUR_BORDER
            else:
                color = "#374151"
            line.setStyleSheet(f"background:{color};border:none;")
