"""추론 결과 오버레이 뷰어 — 줌/패닝 + 투명도 슬라이더."""
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QSlider, QLabel
from PyQt6.QtGui import QPainter, QPixmap, QColor, QCursor
from PyQt6.QtCore import Qt, QPointF, pyqtSignal

from app.widgets.view_transform import MIN_ZOOM, MAX_ZOOM, wheel_zoom, fit_view, pan_drag


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

    def set_pixmap(self, pixmap: QPixmap, reset_view: bool = True) -> None:
        self._pixmap = pixmap
        if reset_view:
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
        delta = event.angleDelta().y()
        mc    = QPointF(event.position())
        self._zoom, self._pan = wheel_zoom(mc, self._pan, self._zoom, delta, MIN_ZOOM, MAX_ZOOM)
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
            self._pan_active       = True
            self._pan_start_mouse  = QPointF(event.position())
            self._pan_start_offset = QPointF(self._pan)
            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))

    def mouseMoveEvent(self, event) -> None:
        if self._pan_active:
            self._pan = pan_drag(self._pan_start_offset, self._pan_start_mouse, QPointF(event.position()))
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
        self._zoom, self._pan = fit_view(w, h, self._pixmap.width(), self._pixmap.height())


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
