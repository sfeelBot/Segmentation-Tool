"""GitHub #9 회귀 테스트 — 팬 드래그 중 휠 줌 시 초점 유지 확인.

wheelEvent()가 커서 기준으로 self._zoom/self._pan을 갱신할 때,
드래그 중이면(_pan_active) mouseMoveEvent()가 참조하는 기준값
(_pan_start_mouse/_pan_start_offset)도 함께 갱신되는지 검증한다.
갱신되지 않으면 줌 직후의 mouseMoveEvent 한 번으로 pan이 줌 이전
기준으로 되돌아가 초점이 틀어진다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QApplication

from app.widgets.annotation_canvas import AnnotationCanvas


def test_wheel_zoom_updates_pan_anchor_during_drag() -> None:
    app = QApplication.instance() or QApplication(sys.argv)

    canvas = AnnotationCanvas()
    canvas._zoom = 1.0
    canvas._pan = QPointF(0.0, 0.0)

    # 팬 드래그가 진행 중인 상태를 흉내 낸다 (mousePressEvent 직후 상태).
    canvas._pan_active = True
    canvas._pan_start_mouse = QPointF(50.0, 50.0)
    canvas._pan_start_offset = QPointF(0.0, 0.0)

    cursor = QPointF(100.0, 80.0)
    img_before = canvas._c2i(cursor)

    event = QWheelEvent(
        cursor, cursor, QPoint(0, 0), QPoint(0, 120),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase, False,
    )
    canvas.wheelEvent(event)

    # 휠 지점 아래 이미지 좌표는 줌 전후로 그대로여야 한다.
    img_after = canvas._c2i(cursor)
    assert abs(img_after.x() - img_before.x()) < 1e-6
    assert abs(img_after.y() - img_before.y()) < 1e-6

    # 줌 직후 같은 지점에서 mouseMoveEvent가 발생해도(드래그가 이어질 때)
    # pan이 줌 이전 기준으로 되돌아가면 안 된다.
    delta = cursor - canvas._pan_start_mouse
    pan_after_move = canvas._pan_start_offset + delta
    assert abs(pan_after_move.x() - canvas._pan.x()) < 1e-6
    assert abs(pan_after_move.y() - canvas._pan.y()) < 1e-6

    print("OK: zoom-during-pan focal point preserved")


if __name__ == "__main__":
    test_wheel_zoom_updates_pan_anchor_during_drag()
