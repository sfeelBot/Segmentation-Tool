"""뷰어 pan/zoom 순수 좌표계산 유틸 — `AnnotationCanvas`/`OverlayViewer` 공용.

상태를 갖지 않는다(stateless) — `_zoom`/`_pan` 등은 호출부가 그대로 보유하고,
이 모듈은 그 값을 받아 다음 값을 계산해 돌려주기만 한다.
"""
from __future__ import annotations

from PyQt6.QtCore import QPointF

MIN_ZOOM = 0.05
MAX_ZOOM = 20.0


def canvas_to_content(canvas_pt: QPointF, pan: QPointF, zoom: float) -> QPointF:
    """캔버스(화면) 좌표 → 콘텐츠(이미지) 좌표."""
    return QPointF(
        (canvas_pt.x() - pan.x()) / zoom,
        (canvas_pt.y() - pan.y()) / zoom,
    )


def wheel_zoom(
    mouse_canvas: QPointF, pan: QPointF, zoom: float, angle_delta_y: int,
    min_zoom: float = MIN_ZOOM, max_zoom: float = MAX_ZOOM,
) -> tuple[float, QPointF]:
    """휠 줌 — 마우스 위치의 콘텐츠 좌표가 고정되도록 새 zoom/pan을 계산."""
    factor = 1.15 if angle_delta_y > 0 else 1 / 1.15
    mouse_content = canvas_to_content(mouse_canvas, pan, zoom)
    new_zoom = max(min_zoom, min(max_zoom, zoom * factor))
    new_pan = mouse_canvas - QPointF(
        mouse_content.x() * new_zoom,
        mouse_content.y() * new_zoom,
    )
    return new_zoom, new_pan


def fit_view(
    view_w: int, view_h: int, content_w: float, content_h: float, margin: float = 0.95,
) -> tuple[float, QPointF]:
    """뷰 크기에 콘텐츠가 margin 비율로 들어차도록 zoom/pan 계산(중앙 정렬)."""
    zoom = min(view_w / content_w, view_h / content_h) * margin
    pan = QPointF(
        (view_w - content_w * zoom) / 2,
        (view_h - content_h * zoom) / 2,
    )
    return zoom, pan


def pan_drag(pan_start_offset: QPointF, pan_start_mouse: QPointF, current_mouse: QPointF) -> QPointF:
    """드래그 시작 시점의 pan 오프셋 + 마우스 이동량."""
    return pan_start_offset + (current_mouse - pan_start_mouse)
