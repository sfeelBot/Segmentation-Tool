"""존 분석 탭 캔버스 — 이미지 + 추론 오버레이 표시 + 원(circle) 검출/편집.

`overlay_viewer.OverlayViewer`의 줌/팬 QPainter 패턴을 그대로 상속해 재사용한다
(QGraphicsView가 아니라 QWidget + paintEvent 커스텀 구현 관례). 원 데이터는
항상 "원본 이미지 픽셀 좌표"로 보관하고(추후 라운드 3 zone_metrics 계산과
동일 좌표계), 화면에는 오버레이 픽스맵 스케일 + 줌/팬을 거쳐 투영한다 —
오버레이 픽스맵 자체가 `_MAX_OVERLAY_DIM` 관례로 다운스케일될 수 있기 때문
(`inference_engine._colorize_and_blend` 참고).

편집: 원 중심 드래그 = 이동, 테두리 드래그 = 반지름 조절, 빈 곳 드래그 = 신규
생성, 선택 후 Delete/우클릭 메뉴 = 삭제. 폴리곤 정점 편집은 없음(스펙 확정 —
원 모델만 다룸).
"""
import math
from dataclasses import dataclass

from PyQt6.QtWidgets import QMenu
from PyQt6.QtGui import QPainter, QPen, QColor
from PyQt6.QtCore import Qt, QPointF, pyqtSignal

from app.widgets.overlay_viewer import OverlayViewer

_CENTER_HIT_PX = 10.0   # 중심(이동) 판정 반경 — 화면 픽셀
_BORDER_HIT_PX = 8.0    # 테두리(반지름 조절) 판정 허용 오차 — 화면 픽셀
_MIN_CREATE_R_PX = 6.0  # 이보다 작게 드래그하고 놓으면 생성 취소

_COLOR_NORMAL = QColor(0, 230, 140)
_COLOR_SELECTED = QColor(255, 200, 0)


@dataclass
class _CircleItem:
    id: int
    cx: float
    cy: float
    r: float


class ZoneCanvas(OverlayViewer):
    """추론 오버레이 표시 + 원 검출 결과 편집 캔버스."""

    circles_changed = pyqtSignal()          # 원 목록이 바뀔 때마다 (추가/이동/삭제 등)
    circle_selected = pyqtSignal(object)    # 선택된 원 id (없으면 None)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._circles: list[_CircleItem] = []
        self._next_id = 1
        self._selected_id: int | None = None
        self._drag_mode: str | None = None   # None | "move" | "resize" | "create"
        self._img_orig_w = 0
        self._img_orig_h = 0
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)   # 클릭 후 Delete 키 삭제를 받으려면 필요

    # ── 공개 API ─────────────────────────────────────────────────────────────

    def set_image_size(self, orig_w: int, orig_h: int) -> None:
        """원본 이미지 픽셀 크기 — 원 좌표(원본 스케일) <-> 오버레이 픽스맵 좌표 변환에 사용."""
        self._img_orig_w = orig_w
        self._img_orig_h = orig_h

    def clear_circles(self) -> None:
        self._circles = []
        self._selected_id = None
        self.update()
        self.circles_changed.emit()
        self.circle_selected.emit(None)

    def set_circles(self, circles: list[tuple[float, float, float]]) -> None:
        """(cx, cy, r) 리스트로 전체 교체 — 자동 검출 결과 반영용."""
        self._circles = [
            _CircleItem(self._next_id + i, cx, cy, r) for i, (cx, cy, r) in enumerate(circles)
        ]
        self._next_id += len(circles)
        self._selected_id = None
        self.update()
        self.circles_changed.emit()

    def get_circles(self) -> list[tuple[float, float, float]]:
        """반지름 오름차순 (cx, cy, r) 리스트."""
        return [(c.cx, c.cy, c.r) for c in sorted(self._circles, key=lambda c: c.r)]

    def circles_with_ids(self) -> list[tuple[int, float, float, float]]:
        """사이드 패널 등 id가 필요한 UI용 — 반지름 오름차순 (id, cx, cy, r)."""
        return [(c.id, c.cx, c.cy, c.r) for c in sorted(self._circles, key=lambda c: c.r)]

    def select_circle(self, circle_id: int | None) -> None:
        """사이드 패널 클릭 등 외부에서 선택 상태만 동기화(드래그 없음)."""
        self._selected_id = circle_id
        self.update()

    def remove_selected(self) -> None:
        if self._selected_id is None:
            return
        self._circles = [c for c in self._circles if c.id != self._selected_id]
        self._selected_id = None
        self.update()
        self.circles_changed.emit()
        self.circle_selected.emit(None)

    # ── 좌표 변환 (원본 이미지 스케일 <-> 픽스맵 스케일 <-> 화면 스케일) ────────

    def _orig_scale(self) -> tuple[float, float]:
        if self._pixmap is None or self._img_orig_w <= 0 or self._img_orig_h <= 0:
            return (1.0, 1.0)
        return (self._pixmap.width() / self._img_orig_w, self._pixmap.height() / self._img_orig_h)

    def _orig_to_screen(self, cx: float, cy: float, r: float) -> tuple[QPointF, float]:
        sx, sy = self._orig_scale()
        center = QPointF(
            cx * sx * self._zoom + self._pan.x(),
            cy * sy * self._zoom + self._pan.y(),
        )
        radius = r * ((sx + sy) / 2) * self._zoom
        return center, radius

    def _screen_to_orig(self, pt: QPointF) -> QPointF:
        sx, sy = self._orig_scale()
        px = (pt.x() - self._pan.x()) / self._zoom
        py = (pt.y() - self._pan.y()) / self._zoom
        return QPointF(px / sx if sx > 0 else px, py / sy if sy > 0 else py)

    def _screen_len_to_orig_r(self, screen_len: float) -> float:
        sx, sy = self._orig_scale()
        s = (sx + sy) / 2
        pixmap_len = screen_len / self._zoom
        return pixmap_len / s if s > 0 else pixmap_len

    # ── 히트 테스트 ──────────────────────────────────────────────────────────

    def _hit_test(self, pt: QPointF) -> tuple[int, str] | None:
        """반지름이 작은 원부터 검사 — 동심원이라 중심이 겹칠 때 안쪽 원 우선 선택."""
        for item in sorted(self._circles, key=lambda c: c.r):
            center, r_screen = self._orig_to_screen(item.cx, item.cy, item.r)
            d = math.hypot(pt.x() - center.x(), pt.y() - center.y())
            if d <= _CENTER_HIT_PX:
                return item.id, "move"
            if abs(d - r_screen) <= _BORDER_HIT_PX:
                return item.id, "resize"
        return None

    def _find(self, circle_id: int) -> _CircleItem | None:
        for c in self._circles:
            if c.id == circle_id:
                return c
        return None

    # ── paintEvent ───────────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._pixmap is None or not self._circles:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for item in sorted(self._circles, key=lambda c: c.r):
            center, r = self._orig_to_screen(item.cx, item.cy, item.r)
            color = _COLOR_SELECTED if item.id == self._selected_id else _COLOR_NORMAL
            pen = QPen(color, 2 if item.id == self._selected_id else 1.5)
            pen.setCosmetic(True)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(center, r, r)
            p.setBrush(color)
            p.drawEllipse(center, 4, 4)
        p.end()

    # ── 마우스 ───────────────────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        if self._pixmap is None or event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        pt = QPointF(event.position())
        hit = self._hit_test(pt)
        if hit is not None:
            circle_id, mode = hit
            self._selected_id = circle_id
            self._drag_mode = mode
            self.circle_selected.emit(circle_id)
        else:
            center = self._screen_to_orig(pt)
            new_id = self._next_id
            self._next_id += 1
            self._circles.append(_CircleItem(new_id, center.x(), center.y(), 0.0))
            self._selected_id = new_id
            self._drag_mode = "create"
            self.circle_selected.emit(new_id)
        self.update()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_mode is None or self._selected_id is None:
            super().mouseMoveEvent(event)
            return
        item = self._find(self._selected_id)
        if item is None:
            return
        pt = QPointF(event.position())
        if self._drag_mode == "move":
            moved = self._screen_to_orig(pt)
            item.cx, item.cy = moved.x(), moved.y()
        else:  # "resize" | "create"
            center, _ = self._orig_to_screen(item.cx, item.cy, item.r)
            dist_screen = math.hypot(pt.x() - center.x(), pt.y() - center.y())
            item.r = max(0.0, self._screen_len_to_orig_r(dist_screen))
        self.update()
        self.circles_changed.emit()

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_mode == "create" and self._selected_id is not None:
            item = self._find(self._selected_id)
            if item is not None:
                _, r_screen = self._orig_to_screen(item.cx, item.cy, item.r)
                if r_screen < _MIN_CREATE_R_PX:
                    self._circles.remove(item)
                    self._selected_id = None
                    self.circle_selected.emit(None)
        self._drag_mode = None
        super().mouseReleaseEvent(event)
        self.update()
        self.circles_changed.emit()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self._selected_id is not None:
            self.remove_selected()
        else:
            super().keyPressEvent(event)

    def contextMenuEvent(self, event) -> None:
        if self._pixmap is None:
            return
        pt = QPointF(event.pos())
        hit = self._hit_test(pt)
        if hit is None:
            return
        circle_id, _ = hit
        self._selected_id = circle_id
        self.circle_selected.emit(circle_id)
        self.update()
        menu = QMenu(self)
        delete_action = menu.addAction("원 삭제")
        chosen = menu.exec(event.globalPos())
        if chosen == delete_action:
            self.remove_selected()
