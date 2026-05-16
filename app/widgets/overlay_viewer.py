"""추론 결과 오버레이 뷰어 — 줌/패닝 + 투명도 슬라이더."""
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QSlider, QLabel
from PyQt6.QtGui import QPainter, QPixmap, QColor, QCursor
from PyQt6.QtCore import Qt, QPointF, pyqtSignal

MIN_ZOOM = 0.05
MAX_ZOOM = 20.0


class OverlayViewer(QWidget):
    opacity_changed = pyqtSignal(float)   # 0.0 ~ 1.0

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._pixmap: QPixmap | None = None

        self._zoom   = 1.0
        self._pan    = QPointF(0.0, 0.0)
        self._pan_active = False
        self._pan_start_mouse  = QPointF()
        self._pan_start_offset = QPointF()

        self._opacity = 0.5
        self.setMinimumSize(300, 200)

    # ── 공개 ─────────────────────────────────────────────────────────────────

    def set_pixmap(self, pixmap: QPixmap) -> None:
        self._pixmap = pixmap
        self._fit_view()
        self.update()

    def clear(self) -> None:
        self._pixmap = None
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
