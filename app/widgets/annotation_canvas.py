"""어노테이션 캔버스 — QPainter 기반 Polygon / Brush / Eraser / Select / Pan 도구."""
import copy
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PyQt6.QtWidgets import QWidget, QInputDialog
from PyQt6.QtGui import (
    QPainter, QPixmap, QImage, QColor, QPen, QBrush,
    QPolygonF, QCursor, QKeySequence,
)
from PyQt6.QtCore import Qt, QPointF, QRectF, QTimer, QThread, pyqtSignal

from app.core import annotation_store as store
from app.core.annotation_store import AnnotationItem
from app.core.i18n import t
from app.core.perf_logger import profiler as _perf


class _OverlayWorker(QThread):
    """백그라운드에서 어노테이션 오버레이 QImage 를 빌드 — 메인 스레드 비블로킹.

    brush_mask 는 bbox(cv2.boundingRect)로 잘라 실제 어노테이션 크기만큼만
    resize/dilate/합성한다(GitHub #6-B) — 전체 이미지 크기 배열을 매번 통째로
    처리하던 것보다 어노테이션이 작을수록(실사용 대다수) 훨씬 빠르다.
    # ponytail: 그래도 매 rebuild마다 어노테이션 n개 전체를 다시 훑는 O(n) 구조는
    # 그대로다(bbox 계산 자체도 배열 전체를 1회 스캔) — 어노테이션 수백 개 이상에서
    # 여전히 체감 지연이 남는다면, 다음 단계는 어노테이션별 렌더링 결과(bbox+ARGB
    # 타일)를 캐시하고 변경된 것만 다시 그리는 방식(요구: mask 변경 시점마다 버전
    # 무효화를 놓치지 않게 처리 — annotation_canvas.py의 mask in-place 수정 지점
    # 여러 곳을 전부 추적해야 해서 리스크가 커 이번 라운드에서는 보류).
    """
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
                # bbox 밖은 항상 0이므로, 전체 이미지 크기(예: 20MP) 배열이 아니라
                # 어노테이션이 실제로 차지하는 영역만 잘라 resize/dilate 한다 — 대형
                # 이미지에서 어노테이션 개수가 많아질수록 개당 비용이 이미지 해상도에
                # 비례해 커지던 것을 어노테이션 크기에 비례하도록 낮춘다 (GitHub #6-B).
                bbox = _mask_bbox(ann.mask)
                if bbox is None:
                    continue
                x0, y0, x1, y1 = bbox
                sub = ann.mask[y0:y1, x0:x1]
                if sc < 0.99:
                    # crop을 독립적으로 resize하면 전체 프레임을 한 번에 resize할 때와
                    # 비교해 경계에서 최대 1px 반올림 차이가 날 수 있다(NEAREST 리샘플링
                    # 특성상 수학적으로 불가피). 오버레이는 편집용 미리보기일 뿐이고
                    # 저장되는 마스크 데이터(RLE)는 그대로이므로 감수한다 — 검증:
                    # scratchpad/check_overlay_correctness.py (경계 1px 이내 근사 확인).
                    ox = int(round(x0 * sc)); oy = int(round(y0 * sc))
                    sub_w = max(1, int(round(x1 * sc)) - ox)
                    sub_h = max(1, int(round(y1 * sc)) - oy)
                    scaled_sub = cv2.resize(
                        sub, (sub_w, sub_h), interpolation=cv2.INTER_NEAREST
                    )
                    p.save(); p.resetTransform()
                    _draw_mask_on_painter(p, scaled_sub, color, ox=ox, oy=oy)
                    if selected:
                        kernel = np.ones((3, 3), np.uint8)
                        border = cv2.dilate(scaled_sub, kernel, iterations=1) - scaled_sub
                        _draw_mask_on_painter(p, border, QColor(255, 255, 255, 210), ox=ox, oy=oy)
                    p.restore()
                else:
                    _draw_mask_on_painter(p, sub, color, ox=x0, oy=y0)
                    if selected:
                        kernel = np.ones((3, 3), np.uint8)
                        border = cv2.dilate(sub, kernel, iterations=1) - sub
                        _draw_mask_on_painter(p, border, QColor(255, 255, 255, 210), ox=x0, oy=y0)

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

_IMAGE_CACHE_SIZE = 2      # 최근 방문 이미지 LRU 캐시 최대 장수 (대형 원본 메모리 고려, 확장 금지)


@dataclass
class _ImageCacheEntry:
    """load_image() 재방문 시 재사용할 이미지별 파생 상태 묶음.
    QPixmap 하나만 캐시하면 display_pixmap/pixel_image 재계산 비용이 남으므로 함께 묶는다."""
    pixmap: QPixmap
    img_w: int
    img_h: int
    overlay_scale: float
    mtime: float                              # 캐시 무효화 판정용 (파일 외부 교체 감지)
    pixel_image: QImage | None = None
    display_pixmap: QPixmap | None = None
    display_pixmap_key: tuple = (-1.0, 0)


class AnnotationCanvas(QWidget):
    annotation_saved   = pyqtSignal()
    selection_changed  = pyqtSignal(list)   # list[str] — 선택된 annotation_id 목록
    pixel_hovered      = pyqtSignal(int, int, int, int, int)  # x, y, r, g, b
    brush_size_changed = pyqtSignal(int)    # 브러시 크기 변경 (더블클릭 다이얼로그 → 툴바 스핀박스 동기화)

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
        self._overlay_visible: bool = True  # 어노테이션 표시/숨김 토글
        # 종료 중인 워커 Python 참조 보관 — GC가 실행 중 QThread를 파괴하는 크래시 방지
        self._dying_workers: list = []

        # ── 성능 최적화 상태 ─────────────────────────────────────────────────
        # Display pixmap 캐시 — 현재 zoom 에 맞게 미리 축소해 CPU blit 비용 감소
        self._display_pixmap: QPixmap | None = None
        self._display_pixmap_key: tuple = (-1.0, 0)  # (zoom_bucket, channel)
        # 채널 뷰 (0=원본, 1=R, 2=G, 3=B)
        self._display_channel: int = 0
        # 픽셀 값 읽기용 QImage 캐시
        self._pixel_image: QImage | None = None

        # 이미지 전환 LRU 캐시 — 최근 방문 이미지의 QPixmap + 파생 상태 재사용
        self._image_cache: OrderedDict[Path, _ImageCacheEntry] = OrderedDict()

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
        self._save_threads: set[threading.Thread] = set()
        self._save_threads_lock = threading.Lock()
        self._mutation_guard = lambda: True

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(400, 300)

    # ── 공개 API ──────────────────────────────────────────────────────────────

    # overlay 를 최대 이 크기로 제한 (20MP 이미지에서 80MB → 13MB 로 감소)
    _MAX_OVERLAY_DIM = 2048

    def set_mutation_guard(self, guard) -> None:
        self._mutation_guard = guard

    def _store_current_into_cache(self) -> None:
        """현재 이미지의 최신 파생 상태(display_pixmap/pixel_image)를 캐시 엔트리에 반영.
        load_image() 가 다른 이미지로 전환하기 직전에 호출 — 재방문 시 그대로 재사용."""
        if self._image_path is None:
            return
        entry = self._image_cache.get(self._image_path)
        if entry is None:
            return
        entry.display_pixmap = self._display_pixmap
        entry.display_pixmap_key = self._display_pixmap_key
        entry.pixel_image = self._pixel_image

    def load_image(self, path: Path) -> None:
        # 이전 이미지의 미저장 변경 즉시 저장
        if self._save_timer.isActive() and self._image_path is not None:
            self._save_timer.stop()
            self._do_save()
        # 이전 이미지의 파생 상태(display_pixmap/pixel_image)를 캐시에 반영 — 재방문 대비
        self._store_current_into_cache()
        # smooth 스케일 워커/타이머 취소 — 구 이미지 작업이 새 이미지 상태를 덮어쓰는 크래시 방지
        self._smooth_timer.stop()
        self._retire_worker(self._smooth_worker, interrupt=False)
        self._smooth_worker = None
        self._cancel_polygon()
        self._finish_brush()
        self._image_path = path

        t_total = _perf.mark("load_image_total")

        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = None

        cached = self._image_cache.get(path)
        if cached is not None and mtime is not None and cached.mtime == mtime:
            # 캐시 히트 — 재디코딩·파생 상태 재계산 생략
            t0 = _perf.mark("load_image_pixmap")
            self._pixmap = cached.pixmap
            _perf.end("load_image_pixmap", t0)
            self._img_w = cached.img_w
            self._img_h = cached.img_h
            self._overlay_scale = cached.overlay_scale
            self._display_pixmap = cached.display_pixmap
            self._display_pixmap_key = cached.display_pixmap_key
            self._pixel_image = cached.pixel_image
            self._image_cache.move_to_end(path)
            if self._pixel_image is None:
                QTimer.singleShot(150, self._cache_pixel_image)
        else:
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

            if mtime is not None:
                self._image_cache[path] = _ImageCacheEntry(
                    pixmap=self._pixmap, img_w=self._img_w, img_h=self._img_h,
                    overlay_scale=self._overlay_scale, mtime=mtime,
                )
                self._image_cache.move_to_end(path)
                while len(self._image_cache) > _IMAGE_CACHE_SIZE:
                    self._image_cache.popitem(last=False)

        t0 = _perf.mark("load_image_annotations")
        self._annotations = store.load(path)
        _perf.end("load_image_annotations", t0)

        _perf.end("load_image_total", t_total)
        _perf.ctx.update({
            "img_w": self._img_w, "img_h": self._img_h,
            "ov_scale": self._overlay_scale,
        })

        self._selected_ids.clear()
        # 이전 이미지의 오버레이는 크기/스케일이 다른 이미지 것이라 재사용하면
        # 어긋난 어노테이션이 잠깐 겹쳐 보인다 — 이미지 전환 시에는 즉시 비운다
        # (같은 이미지 내 편집 시에는 _invalidate_overlay()가 새 오버레이가
        # 준비될 때까지 기존 것을 그대로 유지한다).
        self._overlay = None
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
        self._retire_worker(self._overlay_worker, interrupt=True)
        self._overlay_worker = None
        self._retire_worker(self._smooth_worker, interrupt=False)
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
        self.brush_size_changed.emit(self._brush_size)

    def undo(self) -> None:
        if not self._mutation_guard():
            return
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
        if not self._mutation_guard():
            return
        if not self._annotations:
            return
        self._push_undo()
        self._annotations.clear()
        self._cancel_polygon()
        self._selected_ids.clear()
        self._invalidate_overlay()
        self._schedule_save()
        self.update()

    def toggle_overlay_visible(self) -> None:
        """어노테이션 오버레이 표시/숨김 토글."""
        self._overlay_visible = not self._overlay_visible
        self.update()

    def toggle_ok(self) -> None:
        if not self._mutation_guard():
            return
        if self._image_path is None:
            return
        current = store.get_ok(self._image_path)
        store.set_ok(self._image_path, not current, self._img_w, self._img_h)
        self.annotation_saved.emit()

    def change_selected_class(self, class_id: int) -> None:
        """선택된 어노테이션의 클래스를 변경하고 같은 클래스끼리 재병합."""
        if not self._mutation_guard() or not self._selected_ids:
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
        if not self._mutation_guard():
            return
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
            if not (self._overlay_worker and self._overlay_worker.isRunning()):
                t0 = _perf.mark("overlay_rebuild")
                self._start_overlay_worker()
                _perf.end("overlay_rebuild", t0)
        if self._overlay is not None and self._overlay_visible:
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
        if self._pan_active:
            # 드래그 중 휠 줌: mouseMoveEvent가 절대 오프셋 기준으로
            # self._pan을 재계산하므로, 그 기준점도 새 줌 결과로 갱신해야
            # 다음 move 이벤트가 줌 이전 상태로 되돌리지 않는다.
            self._pan_start_mouse = mouse_canvas
            self._pan_start_offset = QPointF(self._pan)
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

        if self._tool not in (TOOL_PAN, TOOL_SELECT) and not self._mutation_guard():
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
        if self._tool != TOOL_PAN and not self._mutation_guard():
            return
        if self._tool == TOOL_POLYGON and len(self._poly_pts) >= 3:
            self._close_polygon()
        elif self._tool in (TOOL_BRUSH, TOOL_BRUSH_FILL, TOOL_ERASER, TOOL_ERASER_FLOOD):
            # 더블클릭의 첫 클릭이 이미 mousePressEvent/mouseReleaseEvent를 거쳐
            # 원치 않는 미세 스트로크를 어노테이션으로 커밋했으므로 되돌린다.
            self.undo()
            size, ok = QInputDialog.getInt(
                self, t("tool.brush_size_dialog.title"), t("tool.brush_size_dialog.label"),
                self._brush_size, 1, 200,
            )
            if ok:
                self.set_brush_size(size)

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
                        if not self._mutation_guard():
                            self._press_img_pos = None
                            return
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
        bbox = _polygon_bbox(ann.points, self._img_w, self._img_h, margin=1)
        if bbox is not None and self._polygon_has_same_class_contact(ann, bbox):
            poly_mask = _rasterize_polygon(ann.points, self._img_w, self._img_h)
            self._rasterize_polygons_touching(poly_mask, ann.class_id, bbox)
            converted = next(
                (a for a in self._annotations if a.annotation_id == ann.annotation_id), None
            )
            if converted is not None:
                self._resolve_overlap_and_merge(converted, bbox)
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
                if self._brush_bbox is not None:
                    self._rasterize_polygons_touching(
                        self._brush_np, self._class_id, tuple(self._brush_bbox)
                    )
                    merged_bbox = _mask_bbox(self._brush_np, margin=1)
                    self._brush_bbox = list(merged_bbox) if merged_bbox is not None else None
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
        self._is_painting = False
        self._last_paint_pos = None
        self._invalidate_overlay()
        if save:
            self._schedule_save()

    def _fill_enclosed(self) -> None:
        """브러시 궤적으로 실제 닫힌 영역의 내부만 채운다 (시작·끝점을 억지로 잇지 않음).
        같은 클래스의 기존 어노테이션 경계도 "벽"으로 참여시켜, 이미 라벨링된 영역
        옆에 이어 그리는 것만으로 폐곡선을 완성할 수 있게 한다 (GitHub #15).
        기존 어노테이션이 차지하던 픽셀은 순증분에서 제외 — 경계 역할만 하고
        annotation_id 흡수는 일어나지 않는다(병합은 커밋 후 _consolidate_class_region 몫)."""
        if self._brush_np is None or not self._brush_np.any():
            return

        stroke_bbox = self._brush_bbox
        if stroke_bbox is None:
            filled = _floodfill_interior(self._brush_np)
            if filled is not None:
                self._brush_np = filled
                bbox = _mask_bbox(filled, margin=1)
                self._brush_bbox = list(bbox) if bbox is not None else None
            return

        h, w = self._brush_np.shape
        radius = max(1, self._brush_size // 2)
        pad = radius  # 확정 파라미터: 브러시 반경의 1배
        sx0, sy0, sx1, sy1 = stroke_bbox
        qx0, qy0 = max(0, sx0 - pad), max(0, sy0 - pad)
        qx1, qy1 = min(w, sx1 + pad), min(h, sy1 + pad)

        # ── 후보 축소 — 먼저 작은 query bbox만 확인한다. 모든 기존 마스크에
        # _mask_bbox()를 호출하면 마스크마다 전체 이미지를 스캔해, 먼 어노테이션
        # 수에 비례하는 지연이 생긴다. tight bbox는 실제 근처 후보에만 계산한다. ──
        candidates: list[np.ndarray] = []
        cand_bboxes: list[tuple[int, int, int, int]] = []
        for ann in self._annotations:
            if ann.class_id != self._class_id or ann.type != "brush_mask" or ann.mask is None:
                continue
            if not ann.mask[qy0:qy1, qx0:qx1].any():
                continue
            bbox = _mask_bbox(ann.mask, margin=0)
            if bbox is None:
                continue
            candidates.append(ann.mask)
            cand_bboxes.append(bbox)

        if not candidates:
            filled = _floodfill_interior(self._brush_np)
            if filled is not None:
                self._brush_np = filled
                bbox = _mask_bbox(filled, margin=1)
                self._brush_bbox = list(bbox) if bbox is not None else None
            return

        # ── 로컬 작업 캔버스 = (스트로크 bbox ∪ 후보 bbox) padding — 네 모서리가
        # 전부 벽이면 패딩 2배로 재시도(최대 3회), 그래도 실패하면 전체-이미지 폴백 ──
        ux0, uy0, ux1, uy1 = sx0, sy0, sx1, sy1
        for ax0, ay0, ax1, ay1 in cand_bboxes:
            ux0, uy0 = min(ux0, ax0), min(uy0, ay0)
            ux1, uy1 = max(ux1, ax1), max(uy1, ay1)

        cur_pad = pad
        for _attempt in range(3):
            lx0, ly0 = max(0, ux0 - cur_pad), max(0, uy0 - cur_pad)
            lx1, ly1 = min(w, ux1 + cur_pad), min(h, uy1 + cur_pad)

            existing_local = np.zeros((ly1 - ly0, lx1 - lx0), dtype=np.uint8)
            for m in candidates:
                existing_local |= m[ly0:ly1, lx0:lx1]

            walls_local = self._brush_np[ly0:ly1, lx0:lx1] | existing_local
            filled_local = _floodfill_interior(walls_local)
            if filled_local is not None:
                new_local = filled_local & (existing_local == 0)
                result = np.zeros_like(self._brush_np)
                result[ly0:ly1, lx0:lx1] = new_local
                self._brush_np = result
                bbox = _mask_bbox(result, margin=1)
                self._brush_bbox = list(bbox) if bbox is not None else None
                return

            cur_pad *= 2

        # 로컬 사각형으로도 시드를 못 찾은 경우(패딩 확장 3회 실패) — 안전 폴백
        filled = _floodfill_interior(self._brush_np)
        if filled is not None:
            self._brush_np = filled
            bbox = _mask_bbox(filled, margin=1)
            self._brush_bbox = list(bbox) if bbox is not None else None

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

    def _rasterize_polygons_touching(
        self,
        region_mask: np.ndarray,
        class_id: int | None = None,
        bbox: tuple[int, int, int, int] | None = None,
    ) -> None:
        """영역과 닿는 폴리곤만 마스크로 변환한다.

        class_id가 지정된 #12 경로는 겹침과 4-neighbor 접촉을 인정한다. 지우개가
        사용하는 하위 호환 경로(class_id=None)는 기존처럼 실제 겹침만 인정한다.
        후보 검사는 bbox 크기의 로컬 배열에서 수행하고, 접촉이 확인된 폴리곤에만
        전체 이미지 크기 마스크를 할당한다.
        """
        if bbox is None:
            bbox = _mask_bbox(region_mask, margin=1 if class_id is not None else 0)
        if bbox is None:
            return

        region_bbox = tuple(int(v) for v in bbox)
        changed = True
        while changed:
            changed = False
            for i, ann in enumerate(self._annotations):
                if ann.type != "polygon" or len(ann.points) < 3:
                    continue
                if class_id is not None and ann.class_id != class_id:
                    continue
                poly_bbox = _polygon_bbox(
                    ann.points, self._img_w, self._img_h,
                    margin=1 if class_id is not None else 0,
                )
                if poly_bbox is None or not _bboxes_intersect(region_bbox, poly_bbox):
                    continue
                if not _polygon_touches_mask_local(
                    ann.points, region_mask, region_bbox,
                    include_four_neighbor=class_id is not None,
                ):
                    continue
                poly_mask = _rasterize_polygon(ann.points, self._img_w, self._img_h)
                self._annotations[i] = AnnotationItem(
                    annotation_id=ann.annotation_id,
                    class_id=ann.class_id,
                    type="brush_mask",
                    order=ann.order,
                    mask=poly_mask,
                    width=self._img_w,
                    height=self._img_h,
                )
                if class_id is not None:
                    region_mask |= poly_mask
                    merged_bbox = _mask_bbox(region_mask, margin=1)
                    if merged_bbox is not None:
                        region_bbox = merged_bbox
                changed = True

    def _polygon_has_same_class_contact(
        self, new_ann: AnnotationItem, bbox: tuple[int, int, int, int]
    ) -> bool:
        """새 폴리곤이 같은 클래스의 확정 어노테이션과 실제로 닿는지 확인."""
        local_mask = _rasterize_polygon_local(new_ann.points, bbox)
        x0, y0, x1, y1 = bbox
        for ann in self._annotations:
            if ann is new_ann or ann.class_id != new_ann.class_id:
                continue
            if ann.type == "brush_mask" and ann.mask is not None:
                if _local_masks_touch(local_mask, ann.mask[y0:y1, x0:x1], True):
                    return True
            elif ann.type == "polygon" and len(ann.points) >= 3:
                other_bbox = _polygon_bbox(ann.points, self._img_w, self._img_h, margin=1)
                if other_bbox is None or not _bboxes_intersect(bbox, other_bbox):
                    continue
                ux0, uy0 = min(x0, other_bbox[0]), min(y0, other_bbox[1])
                ux1, uy1 = max(x1, other_bbox[2]), max(y1, other_bbox[3])
                union_bbox = (ux0, uy0, ux1, uy1)
                new_local = _rasterize_polygon_local(new_ann.points, union_bbox)
                other_local = _rasterize_polygon_local(ann.points, union_bbox)
                if _local_masks_touch(new_local, other_local, True):
                    return True
        return False

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

    def _resolve_overlap_and_merge(
        self, new_ann: AnnotationItem,
        bbox: tuple[int, int, int, int] | None = None,
    ) -> None:
        """픽셀 독점성 보장 + 같은 클래스 연결 영역 병합.
        brush_bbox 를 활용해 칠한 영역만 처리 → 20MP 전체 스캔 방지."""
        if new_ann.type != "brush_mask" or new_ann.mask is None:
            return

        bb = bbox if bbox is not None else self._brush_bbox
        if bb is None:
            return
        x0, y0, x1, y1 = int(bb[0]), int(bb[1]), int(bb[2]), int(bb[3])

        new_sub  = new_ann.mask[y0:y1, x0:x1]
        if not new_sub.any():
            return
        new_bool = new_sub != 0

        t0 = _perf.mark("resolve_bbox_overlap")
        # ── 1. 픽셀 독점성 — bbox 영역만 처리 (전체 20MP 대신 수천 픽셀) ──────
        # zero-out 이전 bbox 안에 픽셀이 있었는지 함께 기록 — 아래 _has_pixels 에서
        # "정말 필요한 경우"에만 전체 스캔으로 폴백하도록 좁히는 데 사용.
        had_bbox_pixels: dict[str, bool] = {}
        for ann in self._annotations:
            if ann is not new_ann and ann.type == "brush_mask" and ann.mask is not None:
                sub = ann.mask[y0:y1, x0:x1]
                had_bbox_pixels[ann.annotation_id] = bool(sub.any())
                sub[new_bool] = 0

        # ── 2. 빈 마스크 제거 — bbox 로 단락 평가, 예외적인 경우만 전체 스캔 ────
        def _has_pixels(a: AnnotationItem) -> bool:
            if a.type != "brush_mask" or a.mask is None:
                return True
            sub = a.mask[y0:y1, x0:x1]
            if sub.any():          # bbox에 픽셀 있으면 즉시 True (fast path)
                return True
            # bbox 안이 비어 있음. zero-out 이전에도 비어 있었다면(=겹침 없었음)
            # 저장된 어노테이션은 항상 non-empty 라는 불변식에 의해 bbox 밖 어딘가에
            # 픽셀이 있다는 것이 보장되므로 전체 스캔 없이 non-empty 로 단정한다.
            if not had_bbox_pixels.get(a.annotation_id, True):
                return True
            # 겹침이 있었고 zero-out 으로 bbox 안이 완전히 비워진 예외적인 경우에만
            # bbox 밖에 남은 픽셀이 있는지 전체 스캔으로 확인 (20MP fallback, 드묾).
            return bool(a.mask.any())

        self._annotations = [a for a in self._annotations if _has_pixels(a)]
        _perf.end("resolve_bbox_overlap", t0)

        # ── 3. 같은 클래스 연결 병합 — bbox 내부 connectedComponents만 ─────────
        t0 = _perf.mark("consolidate_region")
        self._consolidate_class_region(new_ann.class_id, x0, y0, x1, y1)
        _perf.end("consolidate_region", t0)

        # 병합/픽셀 독점 처리로 제거된 어노테이션 ID가 선택 상태에 남지 않게 한다.
        # 도구 전환은 기존 선택을 유지하므로 select → brush 경로에서 실제로 발생 가능하다.
        live_ids = {a.annotation_id for a in self._annotations}
        valid_selected = self._selected_ids & live_ids
        if valid_selected != self._selected_ids:
            self._selected_ids = valid_selected
            self.selection_changed.emit(list(self._selected_ids))

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
        # 캔버스 밖까지 밀려나 마스크가 전량 0이 된 brush_mask는 제거한다 (BUG-003).
        # 남겨두면 렌더링되지 않는 빈 어노테이션이 다음 이미지 전환 전까지 목록에
        # 유령 항목으로 남는다.
        empty_ids = {
            a.annotation_id for a in self._annotations
            if a.type == "brush_mask" and a.mask is not None and not a.mask.any()
        }
        if empty_ids:
            self._annotations = [a for a in self._annotations if a.annotation_id not in empty_ids]
            self._selected_ids -= empty_ids
        self._invalidate_overlay()

    # ── 내부 — 기타 ──────────────────────────────────────────────────────────

    def _delete_selected_or_last(self) -> None:
        if not self._mutation_guard():
            return
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

    def _snapshot_annotations(self) -> list[AnnotationItem]:
        """self._annotations 의 독립적인 딥카피 동등물을 numpy 네이티브 복사로 생성.
        copy.deepcopy는 numpy 배열을 pickle 경로(__reduce__)로 복사해 .copy()(memcpy)
        보다 훨씬 느리다 — brush_mask 전체 해상도 마스크가 여러 개 있으면 체감 지연의
        직접 원인이었다(GitHub 성능 리포트). points는 튜플 리스트라 얕은 리스트 복사로도
        완전히 독립적(튜플은 불변, 원본 리스트를 in-place mutate하는 코드 없음 — grep 확인됨)."""
        return [
            AnnotationItem(
                annotation_id=a.annotation_id,
                class_id=a.class_id,
                type=a.type,
                order=a.order,
                points=list(a.points),
                mask=(a.mask.copy() if a.mask is not None else None),
                width=a.width,
                height=a.height,
            )
            for a in self._annotations
        ]

    def _push_undo(self) -> None:
        # 대형 이미지 + brush_mask 수백 개 상태에서 스냅샷이 메모리 부족으로 실패할
        # 수 있다(BUG-014, 실측 재현됨). 근본 원인은 어노테이션별 전체 해상도 마스크
        # 저장 구조라 이번엔 재설계하지 않는다 — 대신 실패 시 앱이 죽는 대신 이번
        # undo 스텝만 건너뛰고 편집은 계속되게 한다.
        # numpy의 _ArrayMemoryError는 MemoryError의 서브클래스라 별도 import 없이 잡힌다.
        try:
            snap = self._snapshot_annotations()
        except MemoryError as exc:
            from app.core.logger import get_logger
            get_logger(__name__).warning(
                f"undo 스냅샷 생성 실패(메모리 부족) — 이번 편집은 undo 불가: {exc}"
            )
            return
        self._undo_stack.append(snap)
        if len(self._undo_stack) > 30:
            self._undo_stack.pop(0)

    def _schedule_save(self) -> None:
        self._save_timer.start()

    def wait_for_pending_saves(self) -> None:
        """학습 시작 전 이미 실행 중인 백그라운드 저장이 끝날 때까지 기다린다."""
        while True:
            with self._save_threads_lock:
                pending = list(self._save_threads)
            if not pending:
                return
            for worker in pending:
                worker.join()

    def _do_save(self, sync: bool = False) -> None:
        if self._image_path is None or self._pixmap is None:
            return
        # 리스트만 shallow 복사 — mask 배열은 rle_encode 가 읽기만 하므로 복사 불필요
        path = self._image_path
        w, h = self._img_w, self._img_h
        anns_snap = list(self._annotations)

        def _save() -> None:
            try:
                store.save(path, anns_snap, w, h)
            except Exception as exc:
                from app.core.logger import get_logger
                get_logger(__name__).error(f"저장 실패: {exc}")

        if sync:
            # 이 저장 직후 같은 파일을 또 건드리는 호출(예: toggle_ok())이 있는 경우
            # 백그라운드 스레드와 경쟁하면 나중에 끝나는 쪽이 먼저 쪽을 덮어써
            # 사이드바 상태 캐시가 stale해질 수 있다(BUG-012) — 동기 실행으로 순서를 보장한다.
            self.wait_for_pending_saves()
            _save()
        else:
            def _save_async() -> None:
                try:
                    _save()
                finally:
                    current = threading.current_thread()
                    with self._save_threads_lock:
                        self._save_threads.discard(current)

            worker = threading.Thread(target=_save_async, daemon=True)
            with self._save_threads_lock:
                self._save_threads.add(worker)
            worker.start()
        self.annotation_saved.emit()

    # ── 내부 — 렌더링 ─────────────────────────────────────────────────────────

    def _retire_worker(self, worker, *, interrupt: bool) -> None:
        """실행 중인 워커를 안전하게 은퇴시킨다.
        Python 참조를 _dying_workers 에 보관해 QThread가 실행 중인 채로 GC 되지 않도록 한다."""
        if worker is None or not worker.isRunning():
            return
        if interrupt:
            worker.requestInterruption()
        try:
            worker.done.disconnect()
        except (RuntimeError, TypeError):
            pass  # 이미 disconnect 되었거나 signal 없는 타입
        self._dying_workers.append(worker)
        worker.finished.connect(lambda _w=worker: self._dying_workers.remove(_w)
                                if _w in self._dying_workers else None)

    def _invalidate_overlay(self) -> None:
        # 진행 중인 워커가 있으면 안전하게 은퇴 (GC 크래시 방지)
        self._retire_worker(self._overlay_worker, interrupt=True)
        self._overlay_worker = None
        # 기존 오버레이(self._overlay)는 여기서 비우지 않는다 — 즉시 None으로
        # 만들면 새 오버레이가 준비되기 전까지의 paintEvent들이 어노테이션
        # 없이 그려져 "깜빡임"으로 보인다(GitHub #6-A). 새 오버레이가 도착하면
        # _on_overlay_done()이 교체하므로, 그 전까지는 stale 오버레이를 그대로
        # 보여준다 — 같은 이미지 내 편집(브러시/폴리곤/지우개/선택 등)에서는
        # 이전 프레임과 거의 동일해 자연스럽다. (이미지 자체가 바뀌는 경우는
        # load_image()에서 별도로 self._overlay = None 처리한다.)
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
        # sender 가드: 이미 은퇴한 구 워커의 queued 시그널 무시
        if self.sender() is not self._overlay_worker:
            return
        self._overlay       = QPixmap.fromImage(img)
        self._overlay_dirty = False
        # done.emit() 직후 run()이 리턴하지만 QThread.finished 는 아직 미발송일 수 있다.
        # _retire_worker 로 Python 참조를 _dying_workers 에 이관 → finished 후 GC 허용.
        self._retire_worker(self._overlay_worker, interrupt=False)
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
            color = QColor(156, 163, 175)   # 앱 표준 중립 회색(#9ca3af) — 삭제 경고색(빨강) 대신
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
        # 이전 워커가 아직 실행 중이면 안전하게 은퇴
        self._retire_worker(self._smooth_worker, interrupt=False)
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
        # self.sender()로 방출한 워커 확인 — 구 워커가 새 워커 참조를 덮어쓰는 버그 방지
        sender = self.sender()
        if sender is not self._smooth_worker:
            # 이미 은퇴한 구 워커의 결과 — 무시
            return
        current_bucket = round(self._zoom * 10) / 10
        if abs(bucket - current_bucket) < 0.05:
            base = QPixmap.fromImage(scaled_image)
            self._display_pixmap = (
                self._apply_channel_filter(base, self._display_channel)
                if self._display_channel > 0 else base
            )
            self._display_pixmap_key = (bucket, self._display_channel)
            self.update()
        # run()이 리턴했어도 QThread.finished 미발송 가능 → retire 후 None
        self._retire_worker(self._smooth_worker, interrupt=False)
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

def _polygon_bbox(
    points: list[tuple[float, float]], image_w: int, image_h: int, margin: int = 0
) -> tuple[int, int, int, int] | None:
    if len(points) < 3:
        return None
    pts = np.asarray([[int(x), int(y)] for x, y in points], dtype=np.int32)
    x, y, w, h = cv2.boundingRect(pts)
    if w == 0 or h == 0:
        return None
    return (
        max(0, x - margin), max(0, y - margin),
        min(image_w, x + w + margin), min(image_h, y + h + margin),
    )


def _bboxes_intersect(
    a: tuple[int, int, int, int], b: tuple[int, int, int, int]
) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _rasterize_polygon_local(
    points: list[tuple[float, float]], bbox: tuple[int, int, int, int]
) -> np.ndarray:
    x0, y0, x1, y1 = bbox
    local = np.zeros((y1 - y0, x1 - x0), dtype=np.uint8)
    pts = np.asarray(
        [[int(x) - x0, int(y) - y0] for x, y in points], dtype=np.int32
    )
    cv2.fillPoly(local, [pts], 1)
    return local


def _rasterize_polygon(
    points: list[tuple[float, float]], image_w: int, image_h: int
) -> np.ndarray:
    mask = np.zeros((image_h, image_w), dtype=np.uint8)
    pts = np.asarray([[int(x), int(y)] for x, y in points], dtype=np.int32)
    cv2.fillPoly(mask, [pts], 1)
    return mask


def _local_masks_touch(
    first: np.ndarray, second: np.ndarray, include_four_neighbor: bool
) -> bool:
    first_bool = first != 0
    second_bool = second != 0
    if (first_bool & second_bool).any():
        return True
    if not include_four_neighbor:
        return False
    return bool(
        (first_bool[1:, :] & second_bool[:-1, :]).any()
        or (first_bool[:-1, :] & second_bool[1:, :]).any()
        or (first_bool[:, 1:] & second_bool[:, :-1]).any()
        or (first_bool[:, :-1] & second_bool[:, 1:]).any()
    )


def _polygon_touches_mask_local(
    points: list[tuple[float, float]],
    region_mask: np.ndarray,
    region_bbox: tuple[int, int, int, int],
    include_four_neighbor: bool,
) -> bool:
    poly_bbox = _polygon_bbox(
        points, region_mask.shape[1], region_mask.shape[0],
        margin=1 if include_four_neighbor else 0,
    )
    if poly_bbox is None or not _bboxes_intersect(region_bbox, poly_bbox):
        return False
    x0, y0 = min(region_bbox[0], poly_bbox[0]), min(region_bbox[1], poly_bbox[1])
    x1, y1 = max(region_bbox[2], poly_bbox[2]), max(region_bbox[3], poly_bbox[3])
    local_bbox = (x0, y0, x1, y1)
    polygon_local = _rasterize_polygon_local(points, local_bbox)
    region_local = region_mask[y0:y1, x0:x1]
    return _local_masks_touch(polygon_local, region_local, include_four_neighbor)

def _mask_bbox(mask: np.ndarray, margin: int = 1) -> tuple[int, int, int, int] | None:
    """0이 아닌 영역의 바운딩 박스를 반환 (margin px 여유 포함, 이미지 경계로 클리핑).
    margin=1 은 dilate(3x3, iterations=1)가 필요로 하는 테두리 1px을 확보하기 위함 —
    원본 전체 프레임에서 dilate 했을 때와 동일한 결과가 나오도록 보장한다.
    빈 마스크(전부 0)면 None.
    cv2.boundingRect 사용 — np.where(전체 배열 스캔)보다 대형 이미지에서 수배 빠름
    (실측: 5472×3648 배열에서 np.where 29ms vs cv2.boundingRect 2ms)."""
    x, y, w, h = cv2.boundingRect(mask)
    if w == 0 or h == 0:
        return None
    ih, iw = mask.shape
    x0 = max(0, x - margin)
    y0 = max(0, y - margin)
    x1 = min(iw, x + w + margin)
    y1 = min(ih, y + h + margin)
    return x0, y0, x1, y1


def _floodfill_interior(walls: np.ndarray) -> np.ndarray | None:
    """walls(0/1)의 네 모서리 중 벽이 아닌 곳을 시드로 외부를 flood fill 하고,
    채워지지 않은 나머지(경계+내부)를 반환한다. 네 모서리가 전부 벽이면 시드를
    못 찾아 None(호출자가 폴백 여부를 판단하도록 위임)."""
    h, w = walls.shape
    seed = None
    for sy, sx in [(0, 0), (0, w - 1), (h - 1, 0), (h - 1, w - 1)]:
        if walls[sy, sx] == 0:
            seed = (sx, sy)
            break
    if seed is None:
        return None

    temp = walls.copy()
    ff_mask = np.zeros((h + 2, w + 2), dtype=np.uint8)
    cv2.floodFill(temp, ff_mask, seed, 2)
    return (temp != 2).astype(np.uint8)


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
