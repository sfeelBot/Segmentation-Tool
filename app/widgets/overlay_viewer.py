"""추론 결과 오버레이 뷰어 — 줌/패닝 + 투명도 슬라이더."""
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QSlider, QLabel
from PyQt6.QtGui import QPainter, QPixmap, QColor, QCursor, QPen
from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal

MIN_ZOOM = 0.05
MAX_ZOOM = 20.0

_CLICK_TOLERANCE_PX = 4.0
_COLOR_SELECTED = QColor(255, 200, 0)   # zone_canvas.py의 선택 색과 통일


class OverlayViewer(QWidget):
    opacity_changed = pyqtSignal(float)   # 0.0 ~ 1.0
    pixmap_clicked = pyqtSignal(QPointF)  # 픽스맵 좌표계 — 클릭(드래그 아님)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._pixmap: QPixmap | None = None

        self._zoom   = 1.0
        self._pan    = QPointF(0.0, 0.0)
        self._pan_active = False
        self._pan_start_mouse  = QPointF()
        self._pan_start_offset = QPointF()
        self._press_pos: QPointF | None = None
        self._highlight_rect: QRectF | None = None

        self._opacity = 0.5
        self.setMinimumSize(300, 200)

    # ── 공개 ─────────────────────────────────────────────────────────────────

    def pixmap(self) -> QPixmap | None:
        return self._pixmap

    def set_highlight_rect(self, rect: QRectF | None) -> None:
        """픽스맵 좌표계의 사각형을 저장해 paintEvent에서 하이라이트로 그린다."""
        self._highlight_rect = rect
        self.update()

    def set_pixmap(self, pixmap: QPixmap, reset_view: bool = True,
                   *, preserve_view: bool | None = None) -> None:
        """픽스맵 교체. 기존 zone 호출의 preserve_view도 호환한다."""
        if preserve_view is not None:
            reset_view = not preserve_view
        self._pixmap = pixmap
        if reset_view:
            self._highlight_rect = None
            self._fit_view()
        self.update()

    def clear(self) -> None:
        self._pixmap = None
        self._highlight_rect = None
        self.update()

    # ── paintEvent ───────────────────────────────────────────────────────────

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(30, 30, 30))
        if self._pixmap is None:
            p.setPen(QColor(100, 100, 100))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "추론 결과가 여기 표시됩니다")
            return
        p.translate(self._pan)
        p.scale(self._zoom, self._zoom)
        p.drawPixmap(0, 0, self._pixmap)
        if self._highlight_rect is not None:
            pen = QPen(_COLOR_SELECTED, 2)
            pen.setCosmetic(True)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(self._highlight_rect)

    # ── 마우스 / 휠 ──────────────────────────────────────────────────────────

    def wheelEvent(self, event) -> None:
        delta  = event.angleDelta().y()
        factor = 1.15 if delta > 0 else 1 / 1.15
        mc     = QPointF(event.position())
        mi     = QPointF(
            (mc.x() - self._pan.x()) / self._zoom,
            (mc.y() - self._pan.y()) / self._zoom,
        )
        self._zoom = max(MIN_ZOOM, min(MAX_ZOOM, self._zoom * factor))
        self._pan  = mc - QPointF(mi.x() * self._zoom, mi.y() * self._zoom)
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = QPointF(event.position())
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
            self._pan_active       = True
            self._pan_start_mouse  = QPointF(event.position())
            self._pan_start_offset = QPointF(self._pan)
            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))

    def mouseMoveEvent(self, event) -> None:
        if self._pan_active:
            delta      = QPointF(event.position()) - self._pan_start_mouse
            self._pan  = self._pan_start_offset + delta
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if (event.button() == Qt.MouseButton.LeftButton
                and self._press_pos is not None and self._pixmap is not None):
            moved = QPointF(event.position()) - self._press_pos
            if (moved.x() ** 2 + moved.y() ** 2) ** 0.5 <= _CLICK_TOLERANCE_PX:
                click = QPointF(event.position())
                pixmap_pt = QPointF(
                    (click.x() - self._pan.x()) / self._zoom,
                    (click.y() - self._pan.y()) / self._zoom,
                )
                self.pixmap_clicked.emit(pixmap_pt)
        self._press_pos = None
        self._pan_active = False
        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._pixmap:
            self._fit_view()

    # ── 내부 ─────────────────────────────────────────────────────────────────

    def _fit_view(self) -> None:
        if self._pixmap is None:
            return
        w = self.width()  or 800
        h = self.height() or 600
        self._zoom = min(w / self._pixmap.width(), h / self._pixmap.height()) * 0.95
        self._pan  = QPointF(
            (w - self._pixmap.width()  * self._zoom) / 2,
            (h - self._pixmap.height() * self._zoom) / 2,
        )


# ── 뷰어 + 슬라이더를 묶은 복합 위젯 ─────────────────────────────────────────

class OverlayViewerPanel(QWidget):
    opacity_changed = pyqtSignal(float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.viewer = OverlayViewer()
        layout.addWidget(self.viewer, stretch=1)

        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("오버레이 불투명도:"))
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(0, 100)
        self._slider.setValue(50)
        self._lbl_pct = QLabel("50%")
        self._lbl_pct.setFixedWidth(36)
        ctrl.addWidget(self._slider)
        ctrl.addWidget(self._lbl_pct)
        layout.addLayout(ctrl)

        self._slider.valueChanged.connect(self._on_slider)

    def _on_slider(self, value: int) -> None:
        self._lbl_pct.setText(f"{value}%")
        self.opacity_changed.emit(value / 100.0)

    @property
    def opacity(self) -> float:
        return self._slider.value() / 100.0
