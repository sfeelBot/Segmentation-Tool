"""어노테이션 캔버스 — QPainter 기반 Polygon / Brush / Eraser / Select / Pan 도구."""
import copy
from pathlib import Path

import cv2
import numpy as np
from PyQt6.QtWidgets import QWidget
from PyQt6.QtGui import (
    QPainter, QPixmap, QImage, QColor, QPen, QBrush,
    QPolygonF, QCursor, QKeySequence,
)
from PyQt6.QtCore import Qt, QPointF, QRectF, QTimer, QThread, pyqtSignal

from app.core import annotation_store as store
from app.core.annotation_store import AnnotationItem
from app.core.perf_logger import profiler as _perf


class _OverlayWorker(QThread):
    """백그라운드에서 어노테이션 오버레이 QImage 를 빌드 — 메인 스레드 비블로킹."""
    done = pyqtSignal(object)   # QImage

    def __init__(
        self,
        annotations: list,
        img_w: int, img_h: int,
        overlay_scale: float,
        selected_ids: set,
        cls_map: dict,
    ) -> None:
        super().__init__()
        # shallow 복사 — 렌더링은 읽기 전용이므로 mask 배열 복사 불필요
        self._anns       = list(annotations)
        self._img_w      = img_w
        self._img_h      = img_h
        self._sc         = overlay_scale
        self._selected   = frozenset(selected_ids)
        self._cls_map    = dict(cls_map)

    def run(self) -> None:
        sc = self._sc
        ov_w = max(1, int(self._img_w * sc))
        ov_h = max(1, int(self._img_h * sc))

        img = QImage(ov_w, ov_h, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(sc, sc)

        for ann in self._anns:
            if self.isInterruptionRequested():
                break
            selected   = ann.annotation_id in self._selected
            alpha      = OVERLAY_SEL_ALPHA if selected else OVERLAY_ALPHA
            base_color = self._cls_map.get(ann.class_id, (200, 200, 200))
            color      = QColor(*base_color)
            color.setAlpha(alpha)

            if ann.type == "polygon" and len(ann.points) >= 3:
                poly = QPolygonF([QPointF(*pt) for pt in ann.points])
                p.setBrush(QBrush(color))
                pen_color = QColor(255, 255, 255) if selected else QColor(*base_color)
                p.setPen(QPen(pen_color, (3.0 if selected else 1.5) / sc))
                p.drawPolygon(poly)

            elif ann.type == "brush_mask" and ann.mask is not None:
                if sc < 0.99:
                    scaled_mask = cv2.resize(
                        ann.mask, (ov_w, ov_h), interpolation=cv2.INTER_NEAREST
                    )
                    p.save(); p.resetTransform()
                    _draw_mask_on_painter(p, scaled_mask, color)
                    if selected:
                        kernel = np.ones((3, 3), np.uint8)
                        border = cv2.dilate(scaled_mask, kernel, iterations=1) - scaled_mask
                        _draw_mask_on_painter(p, border, QColor(255, 255, 255, 210))
                    p.restore()
                else:
                    _draw_mask_on_painter(p, ann.mask, color)
                    if selected:
                        kernel = np.ones((3, 3), np.uint8)
                        border = cv2.dilate(ann.mask, kernel, iterations=1) - ann.mask
                        _draw_mask_on_painter(p, border, QColor(255, 255, 255, 210))

        p.end()
        if not self.isInterruptionRequested():
            self.done.emit(img)


class _SmoothScaleWorker(QThread):
    """백그라운드에서 QImage 고품질 스케일링 수행 — 메인 스레드 블로킹 없음."""
    done = pyqtSignal(object, float)   # (scaled QImage, bucket zoom)

    def __init__(self, src: QImage, dw: int, dh: int, bucket: float) -> None:
        super().__init__()
        self._src    = src
        self._dw     = dw
        self._dh     = dh
        self._bucket = bucket

    def run(self) -> None:
        scaled = self._src.scaled(
            self._dw, self._dh,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.done.emit(scaled, self._bucket)

TOOL_POLYGON      = "polygon"
TOOL_BRUSH        = "brush"
TOOL_BRUSH_FILL   = "brush_fill"
TOOL_ERASER       = "eraser"
TOOL_ERASER_FLOOD = "eraser_flood"
TOOL_SELECT       = "select"
TOOL_PAN          = "pan"

OVERLAY_ALPHA     = 140   # 일반 어노테이션 투명도
OVERLAY_SEL_ALPHA = 210   # 선택된 어노테이션 투명도
VERTEX_RADIUS = 5
MIN_ZOOM = 0.05
MAX_ZOOM = 20.0
_SNAP_PX  = 15            # 스냅-투-클로즈 판정 거리 (화면 픽셀)


class AnnotationCanvas(QWidget):
    annotation_saved   = pyqtSignal()
    selection_changed  = pyqtSignal(list)   # list[str] — 선택된 annotation_id 목록
    pixel_hovered      = pyqtSignal(int, int, int, int, int)  # x, y, r, g, b

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # 이미지
        self._pixmap: QPixmap | None = None
        self._img_w = self._img_h = 0
        self._image_path: Path | None = None

        # 어노테이션 목록
        self._annotations: list[AnnotationItem] = []
        self._undo_stack: list[list[AnnotationItem]] = []

        # 뷰 변환
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)

        # 도구 상태
        self._tool = TOOL_POLYGON
        self._class_id = 1
        self._brush_size = 20

        # 폴리곤 진행 중
        self._poly_pts: list[QPointF] = []
        self._cursor_img: QPointF = QPointF()
        self._poly_snap: bool = False   # 첫 꼭짓점 근처 — snap-to-close 활성

        # 브러시 진행 중
        self._brush_np: np.ndarray | None = None
        self._brush_trail: list[tuple[int, int]] = []   # TOOL_BRUSH_FILL 궤적
        self._brush_bbox: list[int] | None = None       # [x0, y0, x1, y1] — 실제로 칠해진 영역
        self._is_painting = False
        self._last_paint_pos: QPointF | None = None     # 보간용 직전 페인트 위치

        # 선택 도구
        self._selected_ids: set[str] = set()
        self._select_start: QPointF | None = None
        self._select_end:   QPointF | None = None
        self._select_active = False
        # 선택된 어노테이션 이동
        self._move_active = False
        self._move_last_img: QPointF | None = None
        # mousePress 시점에 기록 — move/select 모드는 드래그 시작 시점에 결정
        self._press_img_pos: QPointF | None = None
        self._press_hit_id:  str | None = None
        self._pending_rect:   bool = False   # 빈 공간에서 press → drag 시 rect select
        self._press_shift:    bool = False   # Shift 누른 상태로 press 했는지 — 누적 선택

        # 패닝
        self._pan_active = False
        self._pan_start_mouse = QPointF()
        self._pan_start_offset = QPointF()
        self._space_held = False

        # 오버레이 캐시 (GPU 가속되는 QPixmap 로 저장)
        self._overlay: QPixmap | None = None
        self._overlay_dirty = True
        self._overlay_scale: float = 1.0   # 실제 픽셀 vs 이미지 픽셀 비율
        self._overlay_worker: _OverlayWorker | None = None

        # ── 성능 최적화 상태 ─────────────────────────────────────────────────
        # Display pixmap 캐시 — 현재 zoom 에 맞게 미리 축소해 CPU blit 비용 감소
        self._display_pixmap: QPixmap | None = None
        self._display_pixmap_key: tuple = (-1.0, 0)  # (zoom_bucket, channel)
        # 채널 뷰 (0=원본, 1=R, 2=G, 3=B)
        self._display_channel: int = 0
        # 픽셀 값 읽기용 QImage 캐시
        self._pixel_image: QImage | None = None

        # Pan/zoom 중 repaint 30Hz 쓰로틀 (mousemove 마다 update() 방지)
        self._repaint_timer = QTimer(self)
        self._repaint_timer.setSingleShot(True)
        self._repaint_timer.setInterval(16)   # ~60Hz 최대
        self._repaint_timer.timeout.connect(self.update)
        self._repaint_pending = False
        # 움직임이 멈추면 smooth 품질로 display pixmap 재생성 (백그라운드)
        self._smooth_timer = QTimer(self)
        self._smooth_timer.setSingleShot(True)
        self._smooth_timer.setInterval(200)
        self._smooth_timer.timeout.connect(self._start_smooth_scale)
        self._smooth_worker: _SmoothScaleWorker | None = None

        # 자동 저장 타이머 (500ms 디바운스)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(500)
        self._save_timer.timeout.connect(self._do_save)

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(400, 300)

    # ── 공개 API ──────────────────────────────────────────────────────────────

    # overlay 를 최대 이 크기로 제한 (20MP 이미지에서 80MB → 13MB 로 감소)
    _MAX_OVERLAY_DIM = 2048

    def load_image(self, path: Path) -> None:
        self._cancel_polygon()
        self._finish_brush()
        self._image_path = path

        t_total = _perf.mark("load_image_total")

        t0 = _perf.mark("load_image_pixmap")
        self._pixmap = QPixmap(str(path))
        _perf.end("load_image_pixmap", t0)

        self._img_w = self._pixmap.width()
        self._img_h = self._pixmap.height()
        max_dim = max(self._img_w, self._img_h, 1)
        self._overlay_scale = min(1.0, self._MAX_OVERLAY_DIM / max_dim)
        self._display_pixmap = None
        self._display_pixmap_key = (-1.0, 0)
        self._pixel_image = None
        QTimer.singleShot(150, self._cache_pixel_image)

        t0 = _perf.mark("load_image_annotations")
        self._annotations = store.load(path)
        _perf.end("load_image_annotations", t0)

        _perf.end("load_image_total", t_total)
        _perf.ctx.update({
            "img_w": self._img_w, "img_h": self._img_h,
            "ov_scale": self._overlay_scale,
        })

        self._selected_ids.clear()
        self._invalidate_overlay()
        self._fit_view()
        self.update()

    def clear(self) -> None:
        self._pixmap = None
        self._image_path = None
        self._annotations.clear()
        self._undo_stack.clear()
        self._poly_pts.clear()
        self._selected_ids.clear()
        self._brush_np = None
        self._brush_bbox = None
        self._overlay = None
        self._display_pixmap = None
        self._display_pixmap_key = (-1.0, 0)
        self._pixel_image = None
        if self._overlay_worker and self._overlay_worker.isRunning():
            self._overlay_worker.requestInterruption()
            self._overlay_worker.done.disconnect()
            self._overlay_worker = None
        if self._smooth_worker and self._smooth_worker.isRunning():
            self._smooth_worker.done.disconnect()
            self._smooth_worker.quit()
            self._smooth_worker = None
        self.update()

    def set_tool(self, tool: str) -> None:
        if tool != self._tool:
            self._cancel_polygon()
            self._finish_brush()
        self._tool = tool
        if tool == TOOL_PAN:
            cur = Qt.CursorShape.OpenHandCursor
        elif tool == TOOL_SELECT:
            cur = Qt.CursorShape.CrossCursor
        else:
            cur = Qt.CursorShape.CrossCursor
        self.setCursor(QCursor(cur))

    def set_class_id(self, class_id: int) -> None:
        self._class_id = class_id

    def set_brush_size(self, size: int) -> None:
        self._brush_size = max(1, min(size, 200))

    def undo(self) -> None:
        if not self._undo_stack:
            return
        self._annotations = self._undo_stack.pop()
        self._cancel_polygon()
        self._finish_brush(save=False)
        self._selected_ids.clear()
        self._invalidate_overlay()
        self._schedule_save()
        self.update()

    def clear_all_annotations(self) -> None:
        if not self._annotations:
            return
        self._push_undo()
        self._annotations.clear()
        self._cancel_polygon()
        self._selected_ids.clear()
        self._invalidate_overlay()
        self._schedule_save()
        self.update()

    def toggle_ok(self) -> None:
        if self._image_path is None:
            return
        current = store.get_ok(self._image_path)
        store.set_ok(self._image_path, not current, self._img_w, self._img_h)
        self.annotation_saved.emit()

    def change_selected_class(self, class_id: int) -> None:
        """선택된 어노테이션의 클래스를 변경하고 같은 클래스끼리 재병합."""
        if not self._selected_ids:
            return
        self._push_undo()
        affected_classes: set[int] = set()
        for ann in self._annotations:
            if ann.annotation_id in self._selected_ids:
                affected_classes.add(ann.class_id)
                ann.class_id = class_id
        affected_classes.add(class_id)

        # 선택된 어노테이션들의 union bbox 계산 → 그 영역에서만 통합
        bx0, by0, bx1, by1 = self._img_w, self._img_h, 0, 0
        for ann in self._annotations:
            if ann.annotation_id in self._selected_ids and \
               ann.type == "brush_mask" and ann.mask is not None:
                ys, xs = np.where(ann.mask > 0)
                if len(xs):
                    bx0 = min(bx0, int(xs.min()))
                    by0 = min(by0, int(ys.min()))
                    bx1 = max(bx1, int(xs.max()) + 1)
                    by1 = max(by1, int(ys.max()) + 1)

        if bx0 < bx1 and by0 < by1:
            for cls in affected_classes:
                self._consolidate_class_region(cls, bx0, by0, bx1, by1)
        else:
            for cls in affected_classes:
                self._consolidate_class(cls)

        self._selected_ids.clear()
        self._invalidate_overlay()
        self._schedule_save()
        self.selection_changed.emit([])
        self.update()

    def select_annotation(self, ann_id: str) -> None:
        """어노테이션 목록에서 단일 항목 선택 (리스트 패널 → 캔버스 동기화)."""
        self._selected_ids = {ann_id} if ann_id else set()
        self._invalidate_overlay()
        self.update()

    def paste_annotations(self, annotations: list[AnnotationItem]) -> None:
        """이전 이미지의 어노테이션을 현재 이미지에 붙여넣기 (크기 자동 조정)."""
        self._push_undo()
        new_anns = []
        for a in copy.deepcopy(annotations):
            a.annotation_id = store.new_id()
            if a.type == "brush_mask" and a.mask is not None:
                if a.mask.shape != (self._img_h, self._img_w):
                    a.mask = cv2.resize(
                        a.mask, (self._img_w, self._img_h),
                        interpolation=cv2.INTER_NEAREST
                    )
                a.width, a.height = self._img_w, self._img_h
            new_anns.append(a)
        self._annotations = new_anns
        self._selected_ids.clear()
        self._invalidate_overlay()
        self._schedule_save()
        self.update()

    # ── paintEvent ───────────────────────────────────────────────────────────

    def paintEvent(self, _event) -> None:
        self._repaint_pending = False
        t_total = _perf.mark("paintEvent_total")
        _perf.ctx.update({
            "zoom": self._zoom,
            "n_anns": len(self._annotations),
        })

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(45, 45, 45))

        if self._pixmap is None:
            p.setPen(QColor(120, 120, 120))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "이미지를 선택하세요")
            _perf.end("paintEvent_total", t_total)
            _perf.tick()
            return

        p.translate(self._pan)
        p.scale(self._zoom, self._zoom)

        # ── 이미지 블리팅 ────────────────────────────────────────────────────
        t0 = _perf.mark("blit_image")
        p.drawPixmap(0, 0, self._img_w, self._img_h, self._get_display_pixmap())
        _perf.end("blit_image", t0)

        # ── 오버레이 ─────────────────────────────────────────────────────────
        if self._overlay_dirty:
            # 워커가 아직 없으면 (selection 변경 등) 백그라운드 시작
            if not (self._overlay_worker and self._overlay_worker.isRunning()):
                t0 = _perf.mark("overlay_rebuild")
                self._start_overlay_worker()
                _perf.end("overlay_rebuild", t0)
            # 완료 전까지는 오버레이 없이 이미지만 표시 (UI 블로킹 없음)
        if self._overlay is not None:
            t0 = _perf.mark("blit_overlay")
            ov_w = int(self._img_w * self._overlay_scale)
            ov_h = int(self._img_h * self._overlay_scale)
            p.drawPixmap(0, 0, self._img_w, self._img_h,
                         self._overlay, 0, 0, ov_w, ov_h)
            _perf.end("blit_overlay", t0)

        if self._brush_np is not None and self._is_painting:
            t0 = _perf.mark("draw_brush_layer")
            self._draw_brush_layer(p)
            _perf.end("draw_brush_layer", t0)

        if self._poly_pts:
            self._draw_wip_polygon(p)

        if self._select_active and self._select_start and self._select_end:
            self._draw_select_rect(p)

        _perf.end("paintEvent_total", t_total)
        _perf.tick()

    # ── 키보드 이벤트 ─────────────────────────────────────────────────────────

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self._cancel_polygon()
            self._selected_ids.clear()
            self._invalidate_overlay()
            self.selection_changed.emit([])
            self.update()
        elif key == Qt.Key.Key_Space:
            self._space_held = True
            self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
        elif event.matches(QKeySequence.StandardKey.Undo):
            self.undo()
        elif key == Qt.Key.Key_Delete:
            self._delete_selected_or_last()
        elif key in (Qt.Key.Key_BracketLeft, Qt.Key.Key_Minus):
            self.set_brush_size(self._brush_size - 5)
        elif key in (Qt.Key.Key_BracketRight, Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.set_brush_size(self._brush_size + 5)
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Space:
            self._space_held = False
            cur = Qt.CursorShape.CrossCursor if self._tool != TOOL_PAN else Qt.CursorShape.OpenHandCursor
            self.setCursor(QCursor(cur))
        else:
            super().keyReleaseEvent(event)

    # ── 마우스 이벤트 ─────────────────────────────────────────────────────────

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y()
        factor = 1.15 if delta > 0 else 1 / 1.15
        mouse_canvas = QPointF(event.position())
        mouse_img = self._c2i(mouse_canvas)
        self._zoom = max(MIN_ZOOM, min(MAX_ZOOM, self._zoom * factor))
        self._pan = mouse_canvas - QPointF(
            mouse_img.x() * self._zoom,
            mouse_img.y() * self._zoom,
        )
        self._schedule_repaint()

    def mousePressEvent(self, event) -> None:
        pos = QPointF(event.position())
        btn = event.button()

        # 패닝 시작 — 오른쪽 버튼 / Space+Left / Pan 도구 상태에서 Left
        if btn == Qt.MouseButton.RightButton or (
            btn == Qt.MouseButton.LeftButton and self._space_held
        ) or (btn == Qt.MouseButton.LeftButton and self._tool == TOOL_PAN):
            self._pan_active = True
            self._pan_start_mouse = pos
            self._pan_start_offset = QPointF(self._pan)
            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
            return

        if btn != Qt.MouseButton.LeftButton or self._pixmap is None:
            return

        img_pos = self._c2i(pos)

        if self._tool == TOOL_POLYGON:
            if self._poly_snap and len(self._poly_pts) >= 3:
                # 첫 꼭짓점 근처 클릭 → 닫기
                self._close_polygon()
            else:
                self._poly_pts.append(img_pos)
                self.update()

        elif self._tool in (TOOL_BRUSH, TOOL_BRUSH_FILL, TOOL_ERASER):
            self._push_undo()
            if self._brush_np is None:
                self._brush_np = np.zeros((self._img_h, self._img_w), dtype=np.uint8)
            else:
                if self._brush_bbox is not None:
                    x0, y0, x1, y1 = self._brush_bbox
                    self._brush_np[y0:y1, x0:x1] = 0
            self._brush_bbox = None
            self._is_painting = True
            self._last_paint_pos = img_pos   # 보간 기준점 초기화
            if self._tool == TOOL_BRUSH_FILL:
                self._brush_trail = [(int(img_pos.x()), int(img_pos.y()))]
            self._paint_circle(img_pos)
            self.update()

        elif self._tool == TOOL_ERASER_FLOOD:
            self._push_undo()
            self._flood_erase(img_pos)

        elif self._tool == TOOL_SELECT:
            # press 시점: 어느 어노테이션을 찍었는지만 기록.
            # 단일 선택은 즉시 반영, 모드(이동 / rect-select) 결정은 mouseMove 에서.
            shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            hit_id = self._hit_any_ann_id(img_pos)
            self._press_img_pos = img_pos
            self._press_hit_id  = hit_id
            self._pending_rect  = (hit_id is None)
            self._press_shift   = shift

            if hit_id is not None:
                if shift:
                    # Shift+Click — 이미 선택되어 있으면 해제, 아니면 추가
                    if hit_id in self._selected_ids:
                        self._selected_ids.discard(hit_id)
                    else:
                        self._selected_ids.add(hit_id)
                    self._invalidate_overlay()
                    self.selection_changed.emit(list(self._selected_ids))
                elif hit_id not in self._selected_ids:
                    # 일반 클릭 — 단일 선택으로 교체
                    self._selected_ids = {hit_id}
                    self._invalidate_overlay()
                    self.selection_changed.emit(list(self._selected_ids))
            self.update()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._tool == TOOL_POLYGON and len(self._poly_pts) >= 3:
            self._close_polygon()

    def mouseMoveEvent(self, event) -> None:
        pos = QPointF(event.position())
        img_pos = self._c2i(pos)
        self._cursor_img = img_pos

        # ── 픽셀 값 emit ────────────────────────────────────────────────────
        ix, iy = int(img_pos.x()), int(img_pos.y())
        if self._pixel_image is not None and 0 <= ix < self._img_w and 0 <= iy < self._img_h:
            c = QColor(self._pixel_image.pixel(ix, iy))
            self.pixel_hovered.emit(ix, iy, c.red(), c.green(), c.blue())

        # ── 폴리곤 스냅-투-클로즈 체크 ─────────────────────────────────────
        if self._tool == TOOL_POLYGON and len(self._poly_pts) >= 3:
            first = self._poly_pts[0]
            dx = (img_pos.x() - first.x()) * self._zoom
            dy = (img_pos.y() - first.y()) * self._zoom
            was_snap = self._poly_snap
            self._poly_snap = (dx * dx + dy * dy) < _SNAP_PX ** 2
            if was_snap != self._poly_snap:
                self.update()
        else:
            self._poly_snap = False

        if self._pan_active:
            delta = pos - self._pan_start_mouse
            self._pan = self._pan_start_offset + delta
            self._schedule_repaint()
            return

        buttons = event.buttons()
        if buttons & Qt.MouseButton.LeftButton:
            if self._is_painting:
                self._paint_stroke(img_pos)   # 선형 보간 → 빠른 이동에도 끊김 없음
                if self._tool == TOOL_BRUSH_FILL:
                    self._brush_trail.append((int(img_pos.x()), int(img_pos.y())))
                self.update()
            elif self._tool == TOOL_SELECT and self._press_img_pos is not None \
                    and not self._move_active and not self._select_active:
                # 드래그 임계치를 넘기면 move 또는 rect-select 모드 진입
                dxp = img_pos.x() - self._press_img_pos.x()
                dyp = img_pos.y() - self._press_img_pos.y()
                z   = max(self._zoom, 1e-6)
                thresh_img = 4.0 / z
                if (dxp * dxp + dyp * dyp) >= thresh_img * thresh_img:
                    if self._press_hit_id and self._press_hit_id in self._selected_ids:
                        # 선택된 어노테이션에서 드래그 → 이동
                        self._push_undo()
                        self._move_active = True
                        self._move_last_img = QPointF(self._press_img_pos)
                        self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
                    elif self._pending_rect:
                        # 빈 공간에서 드래그 → 다중 선택 사각형
                        self._select_start = QPointF(self._press_img_pos)
                        self._select_end   = img_pos
                        self._select_active = True
                        if not self._press_shift:
                            # Shift 없이 드래그하면 기존 선택 해제
                            self._selected_ids.clear()
                            self.selection_changed.emit([])
                        self._invalidate_overlay()
            if self._select_active:
                self._select_end = img_pos
                self.update()
            elif self._move_active and self._move_last_img is not None:
                dx = int(round(img_pos.x() - self._move_last_img.x()))
                dy = int(round(img_pos.y() - self._move_last_img.y()))
                if dx != 0 or dy != 0:
                    self._translate_selected(dx, dy)
                    self._move_last_img = QPointF(
                        self._move_last_img.x() + dx,
                        self._move_last_img.y() + dy,
                    )
                self.update()
        else:
            # 버튼 안 눌렸을 때: SELECT 도구에서 커서 피드백
            if self._tool == TOOL_SELECT and self._selected_ids and self._hit_selected(img_pos):
                self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
            elif self._tool == TOOL_SELECT:
                self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
            if self._tool == TOOL_POLYGON and self._poly_pts:
                self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() in (Qt.MouseButton.RightButton, Qt.MouseButton.LeftButton):
            if self._pan_active:
                self._pan_active = False
                cur = Qt.CursorShape.CrossCursor if self._tool != TOOL_PAN else Qt.CursorShape.OpenHandCursor
                self.setCursor(QCursor(cur))
                return

        if event.button() == Qt.MouseButton.LeftButton:
            if self._is_painting:
                self._finish_brush()
                self.update()
            elif self._select_active:
                rect = self._make_select_rect()
                new_ids = self._find_annotations_in_rect(rect)
                if self._press_shift:
                    # Shift+드래그 — 기존 선택에 누적
                    self._selected_ids = self._selected_ids | new_ids
                else:
                    self._selected_ids = new_ids
                self._select_active = False
                self._select_start = None
                self._select_end   = None
                self._invalidate_overlay()
                self.selection_changed.emit(list(self._selected_ids))
                self.update()
            elif self._move_active:
                self._move_active = False
                self._move_last_img = None
                self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
                self._schedule_save()
                self.update()
            elif self._tool == TOOL_SELECT and self._press_img_pos is not None:
                # 드래그 없이 단순 클릭
                if self._press_hit_id is None and not self._press_shift:
                    # 빈 공간 클릭 (Shift 없이) → 선택 해제
                    if self._selected_ids:
                        self._selected_ids.clear()
                        self._invalidate_overlay()
                        self.selection_changed.emit([])
                        self.update()
                # (어노테이션 클릭은 press 시점에 이미 선택 반영됨)

            # press 상태 리셋
            self._press_img_pos = None
            self._press_hit_id  = None
            self._pending_rect  = False
            self._press_shift   = False

    # ── 내부 — 폴리곤 ─────────────────────────────────────────────────────────

    def _close_polygon(self) -> None:
        if len(self._poly_pts) < 3:
            return
        self._push_undo()
        ann = AnnotationItem(
            annotation_id=store.new_id(),
            class_id=self._class_id,
            type="polygon",
            order=len(self._annotations),
            points=[(p.x(), p.y()) for p in self._poly_pts],
        )
        self._annotations.append(ann)
        self._poly_pts.clear()
        self._invalidate_overlay()
        self._schedule_save()
        self.update()

    def _cancel_polygon(self) -> None:
        self._poly_pts.clear()
        self.update()

    # ── 내부 — 브러시 ─────────────────────────────────────────────────────────

    def _paint_stroke(self, img_pos: QPointF) -> None:
        """이전 위치 → 현재 위치를 선형 보간해 원을 연속으로 그림.
        마우스를 빠르게 움직여도 끊기지 않고 이어짐."""
        if self._last_paint_pos is None:
            self._last_paint_pos = img_pos
            self._paint_circle(img_pos)
            return

        x0, y0 = self._last_paint_pos.x(), self._last_paint_pos.y()
        x1, y1 = img_pos.x(), img_pos.y()
        dx, dy = x1 - x0, y1 - y0
        dist = (dx * dx + dy * dy) ** 0.5

        # 보간 간격: 반지름의 40% — 완전히 겹쳐서 빈틈 없이
        r = max(1, self._brush_size // 2)
        step = max(1.0, r * 0.4)

        if dist <= step:
            self._paint_circle(img_pos)
        else:
            n = max(1, int(dist / step))
            inv = 1.0 / n
            for i in range(1, n + 1):
                t = i * inv
                self._paint_circle(QPointF(x0 + dx * t, y0 + dy * t))

        self._last_paint_pos = img_pos

    def _paint_circle(self, img_pos: QPointF) -> None:
        """브러시가 지나간 위치를 self._brush_np 에 1로 기록.
        해석은 _finish_brush 에서: 브러시→새 어노테이션, 지우개→해당 픽셀 제거."""
        if self._brush_np is None:
            return
        cx, cy = int(img_pos.x()), int(img_pos.y())
        r = max(1, self._brush_size // 2)
        h, w = self._img_h, self._img_w
        y0, y1 = max(0, cy - r), min(h, cy + r + 1)
        x0, x1 = max(0, cx - r), min(w, cx + r + 1)
        if x1 <= x0 or y1 <= y0:
            return
        ys, xs = np.ogrid[y0:y1, x0:x1]
        circle = (ys - cy) ** 2 + (xs - cx) ** 2 <= r ** 2
        self._brush_np[y0:y1, x0:x1][circle] = 1
        # bbox 증분 업데이트 — 나중에 렌더링 시 이 영역만 처리
        if self._brush_bbox is None:
            self._brush_bbox = [x0, y0, x1, y1]
        else:
            bb = self._brush_bbox
            if x0 < bb[0]: bb[0] = x0
            if y0 < bb[1]: bb[1] = y0
            if x1 > bb[2]: bb[2] = x1
            if y1 > bb[3]: bb[3] = y1

    def _finish_brush(self, save: bool = True) -> None:
        if self._brush_np is not None and self._brush_np.any():
            if self._tool == TOOL_ERASER:
                self._apply_eraser()
            else:
                if self._tool == TOOL_BRUSH_FILL:
                    self._fill_enclosed()
                ann = AnnotationItem(
                    annotation_id=store.new_id(),
                    class_id=self._class_id,
                    type="brush_mask",
                    order=len(self._annotations),
                    mask=self._brush_np.copy(),
                    width=self._img_w,
                    height=self._img_h,
                )
                self._annotations.append(ann)
                self._resolve_overlap_and_merge(ann)
        self._brush_np = None
        self._brush_bbox = None
        self._brush_trail = []
        self._is_painting = False
        self._last_paint_pos = None
        self._invalidate_overlay()
        if save:
            self._schedule_save()

    def _fill_enclosed(self) -> None:
        """브러시 궤적을 자동으로 닫고 내부를 채운다."""
        if self._brush_np is None or not self._brush_np.any():
            return

        mask = self._brush_np.copy()
        h, w = mask.shape

        # 시작점·끝점 연결 (작은 틈 자동 보정)
        if len(self._brush_trail) >= 2:
            thickness = max(1, self._brush_size)
            cv2.line(mask, self._brush_trail[0], self._brush_trail[-1], 1, thickness)

        # 외부에서 flood fill — 경계에 닫히지 않은 부분이 없으면 내부는 도달 불가
        seed = None
        for sy, sx in [(0, 0), (0, w - 1), (h - 1, 0), (h - 1, w - 1)]:
            if mask[sy, sx] == 0:
                seed = (sx, sy)
                break
        if seed is None:
            return

        temp = mask.copy()
        ff_mask = np.zeros((h + 2, w + 2), dtype=np.uint8)
        cv2.floodFill(temp, ff_mask, seed, 2)

        # 2가 아닌 픽셀 = 경계 + 내부 = 채워진 영역
        self._brush_np = (temp != 2).astype(np.uint8)

    def _apply_eraser(self) -> None:
        if self._brush_np is None or self._brush_bbox is None:
            return
        x0, y0, x1, y1 = self._brush_bbox
        sub = self._brush_np[y0:y1, x0:x1]
        if not sub.any():
            return
        # 지우개 영역과 겹치는 폴리곤을 brush_mask로 변환
        self._rasterize_polygons_touching(self._brush_np)
        sub_bool = sub != 0
        # bbox 서브영역만 처리
        for ann in self._annotations:
            if ann.type == "brush_mask" and ann.mask is not None:
                ann.mask[y0:y1, x0:x1][sub_bool] = 0
        # 빈 마스크 제거 — bbox 단락 평가
        self._annotations = [
            a for a in self._annotations
            if not (a.type == "brush_mask" and a.mask is not None
                    and not a.mask[y0:y1, x0:x1].any()
                    and not a.mask.any())
        ]

    def _rasterize_polygons_touching(self, region_mask: np.ndarray) -> None:
        """region_mask와 겹치는 폴리곤을 brush_mask 어노테이션으로 변환."""
        for i, ann in enumerate(self._annotations):
            if ann.type != "polygon" or len(ann.points) < 3:
                continue
            pts = np.array([[int(x), int(y)] for x, y in ann.points], dtype=np.int32)
            poly_mask = np.zeros((self._img_h, self._img_w), dtype=np.uint8)
            cv2.fillPoly(poly_mask, [pts], 1)
            if (poly_mask & region_mask).any():
                self._annotations[i] = AnnotationItem(
                    annotation_id=ann.annotation_id,
                    class_id=ann.class_id,
                    type="brush_mask",
                    order=ann.order,
                    mask=poly_mask,
                    width=self._img_w,
                    height=self._img_h,
                )

    def _flood_erase(self, img_pos: QPointF) -> None:
        cx, cy = int(img_pos.x()), int(img_pos.y())
        if not (0 <= cx < self._img_w and 0 <= cy < self._img_h):
            return

        # 클릭 지점의 클래스 탐색 — 폴리곤도 체크 (상위 레이어 우선)
        hit_class = None
        for ann in reversed(self._annotations):
            if ann.type == "brush_mask" and ann.mask is not None:
                if ann.mask[cy, cx] == 1:
                    hit_class = ann.class_id
                    break
            elif ann.type == "polygon" and len(ann.points) >= 3:
                pts = np.array([[int(x), int(y)] for x, y in ann.points], dtype=np.int32)
                pmask = np.zeros((self._img_h, self._img_w), dtype=np.uint8)
                cv2.fillPoly(pmask, [pts], 1)
                if pmask[cy, cx] == 1:
                    hit_class = ann.class_id
                    break
        if hit_class is None:
            return

        # 해당 클래스의 폴리곤을 brush_mask로 변환해 통일
        for i, ann in enumerate(self._annotations):
            if ann.class_id == hit_class and ann.type == "polygon" and len(ann.points) >= 3:
                pts = np.array([[int(x), int(y)] for x, y in ann.points], dtype=np.int32)
                pmask = np.zeros((self._img_h, self._img_w), dtype=np.uint8)
                cv2.fillPoly(pmask, [pts], 1)
                self._annotations[i] = AnnotationItem(
                    annotation_id=ann.annotation_id,
                    class_id=ann.class_id,
                    type="brush_mask",
                    order=ann.order,
                    mask=pmask,
                    width=self._img_w,
                    height=self._img_h,
                )

        # hit_class 마스크들의 non-zero 영역의 bbox 계산
        ys_all, xs_all = [], []
        for ann in self._annotations:
            if ann.class_id == hit_class and ann.type == "brush_mask" and ann.mask is not None:
                ys, xs = np.where(ann.mask > 0)
                if len(xs):
                    xs_all.extend([xs.min(), xs.max()])
                    ys_all.extend([ys.min(), ys.max()])

        if not xs_all:
            return
        bx0 = max(0, int(min(xs_all)))
        by0 = max(0, int(min(ys_all)))
        bx1 = min(self._img_w, int(max(xs_all)) + 1)
        by1 = min(self._img_h, int(max(ys_all)) + 1)

        # bbox 안에서만 connectedComponents
        combined = np.zeros((by1 - by0, bx1 - bx0), dtype=np.uint8)
        for ann in self._annotations:
            if ann.class_id == hit_class and ann.type == "brush_mask" and ann.mask is not None:
                combined |= ann.mask[by0:by1, bx0:bx1]

        _, labels_sub = cv2.connectedComponents(combined, connectivity=4)
        comp_id = int(labels_sub[cy - by0, cx - bx0])
        if comp_id == 0:
            return
        flood_sub = (labels_sub == comp_id)

        for ann in self._annotations:
            if ann.class_id == hit_class and ann.type == "brush_mask" and ann.mask is not None:
                ann.mask[by0:by1, bx0:bx1][flood_sub] = 0
        self._annotations = [
            a for a in self._annotations
            if not (a.type == "brush_mask" and a.mask is not None and not a.mask.any())
        ]
        self._invalidate_overlay()
        self._schedule_save()
        self.update()

    def _resolve_overlap_and_merge(self, new_ann: AnnotationItem) -> None:
        """픽셀 독점성 보장 + 같은 클래스 연결 영역 병합.
        brush_bbox 를 활용해 칠한 영역만 처리 → 20MP 전체 스캔 방지."""
        if new_ann.type != "brush_mask" or new_ann.mask is None:
            return

        bb = self._brush_bbox
        if bb is None:
            return
        x0, y0, x1, y1 = int(bb[0]), int(bb[1]), int(bb[2]), int(bb[3])

        new_sub  = new_ann.mask[y0:y1, x0:x1]
        if not new_sub.any():
            return
        new_bool = new_sub != 0

        t0 = _perf.mark("resolve_bbox_overlap")
        # ── 1. 픽셀 독점성 — bbox 영역만 처리 (전체 20MP 대신 수천 픽셀) ──────
        for ann in self._annotations:
            if ann is not new_ann and ann.type == "brush_mask" and ann.mask is not None:
                ann.mask[y0:y1, x0:x1][new_bool] = 0

        # ── 2. 빈 마스크 제거 — bbox 로 단락 평가 ─────────────────────────────
        def _has_pixels(a: AnnotationItem) -> bool:
            if a.type != "brush_mask" or a.mask is None:
                return True
            sub = a.mask[y0:y1, x0:x1]
            if sub.any():          # bbox에 픽셀 있으면 즉시 True (fast path)
                return True
            return bool(a.mask.any())  # bbox 비어있을 때만 전체 검사

        self._annotations = [a for a in self._annotations if _has_pixels(a)]
        _perf.end("resolve_bbox_overlap", t0)

        # ── 3. 같은 클래스 연결 병합 — bbox 내부 connectedComponents만 ─────────
        t0 = _perf.mark("consolidate_region")
        self._consolidate_class_region(new_ann.class_id, x0, y0, x1, y1)
        _perf.end("consolidate_region", t0)

    def _consolidate_class_region(
        self, class_id: int, x0: int, y0: int, x1: int, y1: int
    ) -> None:
        """bbox 영역만 connectedComponents 분석해 동일 클래스 마스크를 병합.
        - combined 배열 크기: bbox만큼 (수천 픽셀)
        - 경계 밖 픽셀: 원본 유지 (병합 시 |= 로 보존)
        """
        same = [a for a in self._annotations
                if a.class_id == class_id and a.type == "brush_mask" and a.mask is not None]
        if len(same) <= 1:
            return

        others = [a for a in self._annotations
                  if not (a.class_id == class_id and a.type == "brush_mask")]

        # bbox 크기의 결합 마스크만 생성 (핵심 최적화)
        combined_sub = np.zeros((y1 - y0, x1 - x0), dtype=np.uint8)
        for ann in same:
            combined_sub |= ann.mask[y0:y1, x0:x1]

        n, labels_sub = cv2.connectedComponents(combined_sub, connectivity=4)

        # 컴포넌트 수가 어노테이션 수 이상이면 합칠 것 없음
        if n - 1 >= len(same):
            return

        # Union-Find: 같은 bbox 컴포넌트에 속하는 어노테이션들을 그룹화
        parent = list(range(len(same)))

        def _find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def _union(a: int, b: int) -> None:
            ra, rb = _find(a), _find(b)
            if ra != rb:
                parent[rb] = ra

        for comp_id in range(1, n):
            comp_mask = (labels_sub == comp_id)
            members = [i for i, ann in enumerate(same)
                       if (ann.mask[y0:y1, x0:x1] & comp_mask).any()]
            for j in range(1, len(members)):
                _union(members[0], members[j])

        # 그룹별 전체 마스크 합산 (경계 밖 픽셀 보존)
        groups: dict[int, list[AnnotationItem]] = {}
        for i, ann in enumerate(same):
            groups.setdefault(_find(i), []).append(ann)

        merged = []
        for group_anns in groups.values():
            if len(group_anns) == 1:
                merged.append(group_anns[0])
            else:
                # 전체 마스크 OR — bbox 밖 픽셀도 보존
                new_mask = group_anns[0].mask.copy()
                for a in group_anns[1:]:
                    new_mask |= a.mask
                merged.append(AnnotationItem(
                    annotation_id=group_anns[0].annotation_id,
                    class_id=class_id,
                    type="brush_mask",
                    order=0,
                    mask=new_mask,
                    width=self._img_w,
                    height=self._img_h,
                ))

        self._annotations = others + merged
        for i, a in enumerate(self._annotations):
            a.order = i

    def _consolidate_class(self, class_id: int) -> None:
        """bbox 없이 전체 이미지 기준으로 병합 (class 변경 등 특수 케이스용)."""
        same = [a for a in self._annotations
                if a.class_id == class_id and a.type == "brush_mask" and a.mask is not None]
        if len(same) <= 1:
            return
        others = [a for a in self._annotations
                  if not (a.class_id == class_id and a.type == "brush_mask")]
        combined = np.zeros((self._img_h, self._img_w), dtype=np.uint8)
        for ann in same:
            combined |= ann.mask
        n, labels = cv2.connectedComponents(combined, connectivity=4)
        merged = []
        for comp_id in range(1, n):
            mask = (labels == comp_id).astype(np.uint8)
            merged.append(AnnotationItem(
                annotation_id=store.new_id(), class_id=class_id,
                type="brush_mask", order=0, mask=mask,
                width=self._img_w, height=self._img_h,
            ))
        self._annotations = others + merged
        for i, a in enumerate(self._annotations):
            a.order = i

    # ── 내부 — 선택 도구 ─────────────────────────────────────────────────────

    def _make_select_rect(self) -> QRectF:
        if not self._select_start or not self._select_end:
            return QRectF()
        x0 = min(self._select_start.x(), self._select_end.x())
        y0 = min(self._select_start.y(), self._select_end.y())
        x1 = max(self._select_start.x(), self._select_end.x())
        y1 = max(self._select_start.y(), self._select_end.y())
        return QRectF(x0, y0, x1 - x0, y1 - y0)

    def _find_annotations_in_rect(self, rect: QRectF) -> set[str]:
        found: set[str] = set()
        if rect.width() < 1 and rect.height() < 1:
            return found
        ix0 = max(0, int(rect.x()))
        iy0 = max(0, int(rect.y()))
        ix1 = min(self._img_w, int(rect.x() + rect.width()) + 1)
        iy1 = min(self._img_h, int(rect.y() + rect.height()) + 1)
        for ann in self._annotations:
            if ann.type == "brush_mask" and ann.mask is not None:
                if ix1 > ix0 and iy1 > iy0 and ann.mask[iy0:iy1, ix0:ix1].any():
                    found.add(ann.annotation_id)
            elif ann.type == "polygon":
                for px, py in ann.points:
                    if rect.contains(QPointF(px, py)):
                        found.add(ann.annotation_id)
                        break
        return found

    def _draw_select_rect(self, p: QPainter) -> None:
        rect = self._make_select_rect()
        if not rect.isValid():
            return
        pen = QPen(QColor(255, 220, 0), 1.5 / self._zoom)
        pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(QColor(255, 220, 0, 30))
        p.drawRect(rect)

    def _hit_selected(self, img_pos: QPointF) -> bool:
        """주어진 이미지 좌표가 선택된 어노테이션 위에 있는지."""
        x, y = int(img_pos.x()), int(img_pos.y())
        if not (0 <= x < self._img_w and 0 <= y < self._img_h):
            return False
        for ann in self._annotations:
            if ann.annotation_id not in self._selected_ids:
                continue
            if ann.type == "brush_mask" and ann.mask is not None:
                if ann.mask[y, x] == 1:
                    return True
            elif ann.type == "polygon" and len(ann.points) >= 3:
                pts = np.array([[int(px), int(py)] for px, py in ann.points], dtype=np.int32)
                if cv2.pointPolygonTest(pts, (float(x), float(y)), False) >= 0:
                    return True
        return False

    def _hit_any_ann_id(self, img_pos: QPointF) -> str | None:
        """주어진 좌표 위에 있는 어노테이션 중 가장 위(나중에 그려진) 것의 ID.
        없으면 None."""
        x, y = int(img_pos.x()), int(img_pos.y())
        if not (0 <= x < self._img_w and 0 <= y < self._img_h):
            return None
        for ann in reversed(self._annotations):
            if ann.type == "brush_mask" and ann.mask is not None:
                if ann.mask[y, x] == 1:
                    return ann.annotation_id
            elif ann.type == "polygon" and len(ann.points) >= 3:
                pts = np.array([[int(px), int(py)] for px, py in ann.points], dtype=np.int32)
                if cv2.pointPolygonTest(pts, (float(x), float(y)), False) >= 0:
                    return ann.annotation_id
        return None

    def _translate_selected(self, dx: int, dy: int) -> None:
        """선택된 어노테이션을 (dx, dy) 픽셀만큼 평행이동."""
        if dx == 0 and dy == 0:
            return
        M = np.float32([[1, 0, dx], [0, 1, dy]])
        for ann in self._annotations:
            if ann.annotation_id not in self._selected_ids:
                continue
            if ann.type == "polygon":
                ann.points = [(x + dx, y + dy) for x, y in ann.points]
            elif ann.type == "brush_mask" and ann.mask is not None:
                ann.mask = cv2.warpAffine(
                    ann.mask, M, (self._img_w, self._img_h),
                    flags=cv2.INTER_NEAREST, borderValue=0,
                )
        self._invalidate_overlay()

    # ── 내부 — 기타 ──────────────────────────────────────────────────────────

    def _delete_selected_or_last(self) -> None:
        if self._selected_ids:
            self._push_undo()
            self._annotations = [
                a for a in self._annotations
                if a.annotation_id not in self._selected_ids
            ]
            self._selected_ids.clear()
            self.selection_changed.emit([])
        elif self._annotations:
            self._push_undo()
            self._annotations.pop()
        else:
            return
        self._invalidate_overlay()
        self._schedule_save()
        self.update()

    def _push_undo(self) -> None:
        snap = copy.deepcopy(self._annotations)
        self._undo_stack.append(snap)
        if len(self._undo_stack) > 30:
            self._undo_stack.pop(0)

    def _schedule_save(self) -> None:
        self._save_timer.start()

    def _do_save(self) -> None:
        if self._image_path is None or self._pixmap is None:
            return
        import threading
        # 리스트만 shallow 복사 — mask 배열은 rle_encode 가 읽기만 하므로 복사 불필요
        path = self._image_path
        w, h = self._img_w, self._img_h
        anns_snap = list(self._annotations)

        def _save_thread():
            try:
                store.save(path, anns_snap, w, h)
            except Exception as exc:
                from app.core.logger import get_logger
                get_logger(__name__).error(f"백그라운드 저장 실패: {exc}")

        threading.Thread(target=_save_thread, daemon=True).start()
        self.annotation_saved.emit()

    # ── 내부 — 렌더링 ─────────────────────────────────────────────────────────

    def _invalidate_overlay(self) -> None:
        # 진행 중인 워커가 있으면 취소
        if self._overlay_worker and self._overlay_worker.isRunning():
            self._overlay_worker.requestInterruption()
            self._overlay_worker.done.disconnect()
            self._overlay_worker = None
        self._overlay = None
        self._overlay_dirty = True
        # 어노테이션 있으면 백그라운드로 즉시 빌드 시작
        if self._img_w > 0:
            self._start_overlay_worker()

    def _start_overlay_worker(self) -> None:
        """백그라운드에서 오버레이 빌드 시작."""
        if self._overlay_worker and self._overlay_worker.isRunning():
            return  # 이미 실행 중
        from app.core.annotation_store import load_classes
        cls_map = {c.class_id: c.color for c in load_classes()}
        self._overlay_worker = _OverlayWorker(
            self._annotations, self._img_w, self._img_h,
            self._overlay_scale, self._selected_ids, cls_map,
        )
        self._overlay_worker.done.connect(self._on_overlay_done)
        self._overlay_worker.start()

    def _on_overlay_done(self, img: QImage) -> None:
        """백그라운드 오버레이 빌드 완료 — QPixmap 변환 후 교체."""
        self._overlay       = QPixmap.fromImage(img)
        self._overlay_dirty = False
        self._overlay_worker = None
        self.update()

    def _rebuild_overlay(self) -> None:
        self._overlay_dirty = False
        if self._img_w == 0 or self._img_h == 0:
            self._overlay = None
            return

        sc = self._overlay_scale
        ov_w = max(1, int(self._img_w * sc))
        ov_h = max(1, int(self._img_h * sc))

        img = QImage(ov_w, ov_h, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # 좌표 변환: 이미지 좌표 → overlay 픽셀
        p.scale(sc, sc)

        from app.core.annotation_store import load_classes
        cls_map = {c.class_id: c.color for c in load_classes()}

        for ann in self._annotations:
            selected   = ann.annotation_id in self._selected_ids
            alpha      = OVERLAY_SEL_ALPHA if selected else OVERLAY_ALPHA
            base_color = cls_map.get(ann.class_id, (200, 200, 200))
            color      = QColor(*base_color)
            color.setAlpha(alpha)

            if ann.type == "polygon" and len(ann.points) >= 3:
                poly = QPolygonF([QPointF(*pt) for pt in ann.points])
                p.setBrush(QBrush(color))
                pen_w = (3.0 if selected else 1.5) / sc
                pen_color = QColor(255, 255, 255) if selected else QColor(*base_color)
                p.setPen(QPen(pen_color, pen_w))
                p.drawPolygon(poly)

            elif ann.type == "brush_mask" and ann.mask is not None:
                # 마스크를 overlay 해상도로 축소 후 그림 (p.scale 이 이미 적용 중)
                if sc < 0.99:
                    scaled_mask = cv2.resize(
                        ann.mask,
                        (ov_w, ov_h),
                        interpolation=cv2.INTER_NEAREST,
                    )
                    # scale 변환 임시 해제 후 픽셀 단위로 직접 그리기
                    p.save()
                    p.resetTransform()
                    _draw_mask_on_painter(p, scaled_mask, color)
                    if selected:
                        kernel = np.ones((3, 3), np.uint8)
                        border = cv2.dilate(scaled_mask, kernel, iterations=1) - scaled_mask
                        _draw_mask_on_painter(p, border, QColor(255, 255, 255, 210))
                    p.restore()
                else:
                    _draw_mask_on_painter(p, ann.mask, color)
                    if selected:
                        kernel = np.ones((3, 3), np.uint8)
                        border = cv2.dilate(ann.mask, kernel, iterations=1) - ann.mask
                        _draw_mask_on_painter(p, border, QColor(255, 255, 255, 210))

        p.end()
        self._overlay = QPixmap.fromImage(img)

    def _draw_brush_layer(self, p: QPainter) -> None:
        if self._brush_np is None or self._brush_bbox is None:
            return
        x0, y0, x1, y1 = self._brush_bbox
        if x1 <= x0 or y1 <= y0:
            return
        from app.core.annotation_store import load_classes
        cls_map = {c.class_id: c.color for c in load_classes()}
        color = QColor(*cls_map.get(self._class_id, (200, 200, 200)))
        if self._tool == TOOL_ERASER:
            color = QColor(255, 80, 80)
        color.setAlpha(OVERLAY_ALPHA)
        # 전체 이미지가 아닌 bbox 서브영역만 렌더링 — 거대 이미지에서 수백 배 빠름
        sub = self._brush_np[y0:y1, x0:x1]
        _draw_mask_on_painter(p, sub, color, ox=x0, oy=y0)

    def _draw_wip_polygon(self, p: QPainter) -> None:
        from app.core.annotation_store import load_classes
        cls_map = {c.class_id: c.color for c in load_classes()}
        color = QColor(*cls_map.get(self._class_id, (200, 200, 200)))

        pen = QPen(color, 1.5 / self._zoom)
        pen.setStyle(Qt.PenStyle.SolidLine)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)

        pts = self._poly_pts
        for i in range(len(pts) - 1):
            p.drawLine(pts[i], pts[i + 1])
        if pts:
            p.drawLine(pts[-1], self._cursor_img)

        vr = VERTEX_RADIUS / self._zoom
        p.setBrush(QBrush(color))
        for pt in pts:
            p.drawEllipse(pt, vr, vr)

        # 스냅-투-클로즈 표시 — 첫 꼭짓점 주위에 흰 원
        if self._poly_snap and len(pts) >= 3:
            snap_r = _SNAP_PX / self._zoom
            p.setPen(QPen(QColor(255, 255, 255), 2.5 / self._zoom))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(pts[0], snap_r, snap_r)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(255, 255, 255, 160)))
            p.drawEllipse(pts[0], vr * 1.4, vr * 1.4)

    # ── 내부 — 좌표 변환 ─────────────────────────────────────────────────────

    # ── 채널 뷰 + 픽셀 읽기 ──────────────────────────────────────────────────

    def set_channel(self, channel: int) -> None:
        """0=원본, 1=R, 2=G, 3=B. 선택 채널만 표시."""
        if self._display_channel == channel:
            return
        self._display_channel = channel
        self._display_pixmap = None
        self._display_pixmap_key = (-1.0, 0)
        self.update()

    def _cache_pixel_image(self) -> None:
        """픽셀 값 읽기용 QImage 를 백그라운드 없이 1회 캐싱 (load 직후 150ms 후 실행)."""
        if self._pixmap is not None:
            self._pixel_image = self._pixmap.toImage().convertToFormat(
                QImage.Format.Format_RGB888
            )

    def _apply_channel_filter(self, pixmap: QPixmap, channel: int) -> QPixmap:
        """channel 채널을 그레이스케일로 표시 (1=R, 2=G, 3=B).
        해당 채널의 밝기 값을 R=G=B 로 설정 → 흑백 강도 이미지."""
        qimg = pixmap.toImage().convertToFormat(QImage.Format.Format_RGB888)
        w, h = qimg.width(), qimg.height()
        ptr = qimg.bits()
        ptr.setsize(qimg.sizeInBytes())
        stride = qimg.bytesPerLine()
        arr = (np.frombuffer(ptr, dtype=np.uint8)
               .reshape(h, stride)[:, :w * 3]
               .reshape(h, w, 3).copy())
        ch = channel - 1          # R=0, G=1, B=2
        gray = arr[:, :, ch]      # 해당 채널 값만 추출
        result = np.empty_like(arr)
        result[:, :, 0] = gray    # R
        result[:, :, 1] = gray    # G  → 모두 같은 값 = 그레이스케일
        result[:, :, 2] = gray    # B
        out = QImage(result.tobytes(), w, h, w * 3, QImage.Format.Format_RGB888)
        return QPixmap.fromImage(out)

    def _get_display_pixmap(self) -> QPixmap:
        """현재 zoom 에 맞게 미리 축소된 pixmap 반환 (캐시됨).
        pan/zoom 중 FastTransformation, 정지 후 SmoothTransformation 으로 품질 보정."""
        if self._pixmap is None:
            return QPixmap()
        bucket = round(self._zoom * 10) / 10
        key = (bucket, self._display_channel)
        if self._display_pixmap is None or self._display_pixmap_key != key:
            t0 = _perf.mark("get_display_pixmap")
            if bucket < 0.9:
                dw = max(1, int(self._img_w * bucket))
                dh = max(1, int(self._img_h * bucket))
                base = self._pixmap.scaled(
                    dw, dh,
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.FastTransformation,
                )
            else:
                base = self._pixmap
            # 채널 필터 적용
            self._display_pixmap = (
                self._apply_channel_filter(base, self._display_channel)
                if self._display_channel > 0 else base
            )
            self._display_pixmap_key = key
            _perf.end("get_display_pixmap", t0)
        return self._display_pixmap

    def _start_smooth_scale(self) -> None:
        """pan/zoom 이 멈춘 후 백그라운드에서 Smooth 보간 시작 — 메인 스레드 비블로킹."""
        if self._pixmap is None:
            return
        bucket = round(self._zoom * 10) / 10
        if bucket >= 0.9:
            return
        # 이전 워커가 아직 실행 중이면 취소
        if self._smooth_worker and self._smooth_worker.isRunning():
            self._smooth_worker.done.disconnect()
            self._smooth_worker.quit()
            self._smooth_worker = None

        dw = max(1, int(self._img_w * bucket))
        dh = max(1, int(self._img_h * bucket))
        # QPixmap → QImage 변환은 메인 스레드에서 안전하게 수행
        src_image = self._pixmap.toImage()
        self._smooth_worker = _SmoothScaleWorker(src_image, dw, dh, bucket)
        self._smooth_worker.done.connect(self._on_smooth_done)
        self._smooth_worker.start()

    def _on_smooth_done(self, scaled_image: QImage, bucket: float) -> None:
        """백그라운드 스케일 완료 — 메인 스레드에서 QPixmap 으로 변환 후 적용."""
        current_bucket = round(self._zoom * 10) / 10
        if abs(bucket - current_bucket) < 0.05:
            base = QPixmap.fromImage(scaled_image)
            self._display_pixmap = (
                self._apply_channel_filter(base, self._display_channel)
                if self._display_channel > 0 else base
            )
            self._display_pixmap_key = (bucket, self._display_channel)
            self.update()
        self._smooth_worker = None

    def _schedule_repaint(self) -> None:
        """30Hz 로 쓰로틀된 repaint 예약. pan/zoom 중 과도한 update() 방지."""
        if not self._repaint_pending:
            self._repaint_pending = True
            self._repaint_timer.start()
        # 움직이는 동안 smooth 타이머 계속 리셋 → 멈추면 200ms 후 smooth 적용
        self._smooth_timer.start()

    def _c2i(self, canvas_pt: QPointF) -> QPointF:
        return QPointF(
            (canvas_pt.x() - self._pan.x()) / self._zoom,
            (canvas_pt.y() - self._pan.y()) / self._zoom,
        )

    def _fit_view(self) -> None:
        if self._img_w == 0 or self._img_h == 0:
            return
        w, h = self.width() or 800, self.height() or 600
        self._zoom = min(w / self._img_w, h / self._img_h) * 0.95
        self._pan = QPointF(
            (w - self._img_w * self._zoom) / 2,
            (h - self._img_h * self._zoom) / 2,
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._pixmap and not self._pan_active:
            self._fit_view()


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────

def _draw_mask_on_painter(p: QPainter, mask: np.ndarray, color: QColor,
                           ox: int = 0, oy: int = 0) -> None:
    """마스크(0/1 uint8) 를 단색 반투명 이미지로 변환해 (ox, oy) 위치에 그린다.
    ARGB32 는 little-endian 에서 메모리상 BGRA 순이므로 swizzle 없이 바로 구성."""
    h, w = mask.shape
    argb = np.empty((h, w, 4), dtype=np.uint8)
    argb[..., 0] = color.blue()
    argb[..., 1] = color.green()
    argb[..., 2] = color.red()
    argb[..., 3] = (mask != 0).astype(np.uint8) * color.alpha()
    qimg = QImage(argb.data, w, h, 4 * w, QImage.Format.Format_ARGB32)
    p.drawImage(ox, oy, qimg)
