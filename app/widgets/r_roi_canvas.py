"""R 분석 탭 캔버스 — 이미지 표시 + ROI(사각형 1개) 편집 + 마스크 보정.

`overlay_viewer.OverlayViewer`의 줌/팬 QPainter 패턴을 그대로 상속(zone_canvas.py와
동일 관례). ROI는 항상 "원본 이미지 픽셀 좌표"로 보관하고 화면에는 오버레이 픽스맵
스케일 + 줌/팬을 거쳐 투영한다(zone_canvas의 원 좌표 변환과 동일 원리).

이 파일은 `zone_canvas.py`의 구조(드래그 생성/이동/리사이즈 상태머신, 브러시 지우기/
그리기 스탬프, 경량 undo 스택, 150ms 아님 — 여기선 디바운스 없음, debounce는
threshold 슬라이더 쪽 책임)를 **상속이 아니라 복사 포팅**한 것이다 — 원(circle)
특화 기하 수학을 사각형(rect) 8-handle 리사이즈로 바꾼 것 외에는 브러시 스탬프/
undo 메커니즘이 동일하다(스펙 요구사항 7, "원↔임의 블롭 모양 수학이 다르기 때문").

블랍 삭제 모드는 없다(R 분석 탭엔 해당 개념이 없음) — 모드는 "roi"(기본, ROI 편집)
| "brush_draw" | "brush_erase" | "pan" 4가지뿐.
"""
import math

import numpy as np
from PyQt6.QtGui import QPainter, QPen, QColor, QImage, QKeySequence
from PyQt6.QtCore import Qt, QPointF, QRectF, QRect, pyqtSignal

from app.widgets.overlay_viewer import OverlayViewer
from app.core import zone_metrics

_HANDLE_PX = 8.0        # 리사이즈 핸들 히트 판정 반경 — 화면 픽셀
_MIN_CREATE_PX = 6.0    # 이보다 작게 생성 드래그하면 취소

_COLOR_ROI = QColor(250, 204, 21)           # amber-400 — 마스크/브러시 색과 구분
_COLOR_DRAW = QColor(96, 165, 250, 110)     # zone_canvas._COLOR_DRAW 재사용(accent blue)
_COLOR_ERASE = QColor(156, 163, 175, 110)   # zone_canvas._COLOR_ERASE 재사용
_COLOR_MASK = (34, 197, 94, 90)             # 검출된(+보정된) 마스크 오버레이, green-500

# 핸들별 (고정 변(fixed), 이동 변(movable)) — "roi edges" = {left, top, right, bottom}
# 딕셔너리(x,y,w,h 아님, 리사이즈 중 좌/상/우/하 중 일부만 갱신하는 편이 간단하다).
_HANDLE_FIXED_MOVABLE: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "nw": (("right", "bottom"), ("left", "top")),
    "n":  (("left", "right", "bottom"), ("top",)),
    "ne": (("left", "bottom"), ("right", "top")),
    "e":  (("left", "top", "bottom"), ("right",)),
    "se": (("left", "top"), ("right", "bottom")),
    "s":  (("left", "right", "top"), ("bottom",)),
    "sw": (("right", "top"), ("left", "bottom")),
    "w":  (("top", "right", "bottom"), ("left",)),
}


class RRoiCanvas(OverlayViewer):
    """이미지 표시 + ROI 사각형 편집 + 브러시 보정 캔버스."""

    roi_changed = pyqtSignal()      # 드래그 중 매 프레임(이동/리사이즈/생성)
    roi_committed = pyqtSignal()    # 드래그 완료 — 탭이 재검출을 트리거하는 지점
    erase_changed = pyqtSignal()    # 브러시 스트로크가 끝났을 때 1회(데이터 재계산 트리거)
    mask_changed = pyqtSignal()     # 화면에 그려지는 effective_mask()가 바뀔 때마다
    overlay_toggle_requested = pyqtSignal()   # F키 — 탭이 show/hide 액션을 토글

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._img_orig_w = 0
        self._img_orig_h = 0
        self._mode: str = "roi"

        # ── ROI 상태머신 ─────────────────────────────────────────────────────
        self._roi_edges: dict[str, float] | None = None   # {"left","top","right","bottom"}, 원본 좌표
        self._drag_mode: str | None = None    # None | "move" | "resize" | "create"
        self._resize_handle: str | None = None
        self._fixed_edges: dict[str, float] = {}
        self._movable_edges: tuple[str, ...] = ()
        self._press_orig_pt: QPointF | None = None
        self._move_snapshot: dict[str, float] | None = None

        # ── 검출된/보정된 마스크(원본 해상도 bool) ───────────────────────────────
        self._detected_mask: np.ndarray | None = None
        self._mask_image: QImage | None = None
        self._mask_alpha = 90   # _COLOR_MASK 기본 alpha(0~255) — set_mask_opacity()로 조절
        self._mask_visible = True   # 화면 표시 여부만 — effective_mask()/데이터는 영향 없음

        # ── effective_mask() 증분 캐시(P0 성능) ──────────────────────────────
        # 스트로크를 1개 커밋할 때마다 누적된 manual_strokes 전체를 처음부터
        # 재생하면 O(누적 포인트 수) 비용이 매 커밋마다 커진다(검증 2026-10-27).
        # 대신 "마지막으로 계산한 결과"를 들고 있다가 새로 추가된 스트로크만
        # 그 결과 위에 덧적용한다 — apply_manual_strokes()가 스트로크를 순서대로
        # last-write-wins로 적용하는 구조라 수학적으로 전체 재생과 동일한 결과.
        self._mask_cache_base: np.ndarray | None = None   # 캐시가 유효한 detected_mask(identity 비교)
        self._mask_cache_n_strokes = 0                     # 캐시에 이미 반영된 manual_strokes 개수
        self._mask_cache_result: np.ndarray | None = None

        # ── 브러시 그리기/지우기(zone_canvas R3-3 포팅) ──────────────────────────
        self._manual_strokes: list[tuple[bool, list[tuple[float, float, float]]]] = []
        self._erase_strokes: list[list[tuple[float, float, float]]] = []   # erase_mask() 전용 레거시 합집합
        self._erase_mask_np: np.ndarray | None = None
        self._stroke_overlay: QImage | None = None
        self._erase_brush_size = 30
        self._current_stroke: list[tuple[float, float, float]] = []
        self._last_erase_pos: QPointF | None = None
        self._erasing = False

        # ── Undo(zone_canvas R3-4 포팅, 경량 스냅샷뿐) ───────────────────────────
        self._undo_stack: list[dict] = []

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # ── 공개 API — 이미지/ROI ────────────────────────────────────────────────

    def set_image_size(self, orig_w: int, orig_h: int) -> None:
        self._img_orig_w = orig_w
        self._img_orig_h = orig_h

    def set_roi(self, rect: QRect | None) -> None:
        self._push_undo()
        self._roi_edges = self._edges_from_rect(rect) if rect is not None else None
        self.update()
        self.roi_changed.emit()
        self.roi_committed.emit()

    def get_roi(self) -> QRect | None:
        if self._roi_edges is None:
            return None
        x, y, w, h = self._normalized_tuple(self._roi_edges)
        return QRect(int(round(x)), int(round(y)), int(round(w)), int(round(h)))

    # ── 공개 API — 모드 ──────────────────────────────────────────────────────

    def set_brush_erase_mode(self, enabled: bool) -> None:
        self._mode = "brush_erase" if enabled else "roi"
        self.update()

    def set_brush_draw_mode(self, enabled: bool) -> None:
        self._mode = "brush_draw" if enabled else "roi"
        self.update()

    def set_pan_mode(self, enabled: bool) -> None:
        self._mode = "pan" if enabled else "roi"
        self.update()

    def set_erase_brush_size(self, size: int) -> None:
        self._erase_brush_size = max(1, min(size, 200))

    def erase_brush_size(self) -> int:
        return self._erase_brush_size

    # ── 공개 API — 마스크 ────────────────────────────────────────────────────

    def set_detected_mask(self, mask: np.ndarray | None) -> None:
        """탭이 `r_analysis_metrics.detect_contour_mask()` 결과를 반영할 때 호출.
        수동 그리기/지우기 스트로크는 그대로 유지된다(이미지 전환이 아니라 같은
        이미지의 재검출이므로 — threshold/ROI 조정 시 반복 호출됨)."""
        self._detected_mask = mask
        self._rebuild_mask_image()
        self.update()
        self.mask_changed.emit()

    def erase_mask(self) -> np.ndarray | None:
        """지운 영역만의 bool 마스크(원본 좌표) — zone_canvas.erase_mask()와 동일 getter 패턴."""
        return self._erase_mask_np

    def set_mask_opacity(self, alpha_0_255: int) -> None:
        """검출 마스크 오버레이 투명도 조절(0~255). 세션 동안 값 유지 — 새 마스크를
        set_detected_mask()로 갈아끼워도 다음 호출까지 그대로 적용된다."""
        self._mask_alpha = max(0, min(255, alpha_0_255))
        self._rebuild_mask_image()
        self.update()

    def set_mask_overlay_visible(self, visible: bool) -> None:
        """검출 마스크 오버레이를 화면에 그릴지 여부만 전환(데이터/boundary 편집에는
        영향 없음) — 라벨링 탭의 어노테이션 show/hide와 동일한 눈 아이콘 토글용."""
        self._mask_visible = visible
        self.update()

    def mask_opacity(self) -> int:
        return self._mask_alpha

    def effective_mask(self) -> np.ndarray | None:
        """검출 마스크 + 수동 그리기/지우기 반영 최종 마스크(면적 계산용).

        P0 성능: `_mask_cache_base`가 지금 `_detected_mask`와 같은 배열이고(식별
        비교 — `set_detected_mask()`가 재검출마다 새 배열을 넘기므로 충분) 지금까지
        캐시에 반영된 스트로크 수가 현재 `_manual_strokes` 길이 이하면, 새로 추가된
        스트로크만 캐시 결과 위에 덧적용한다(전체 재생 금지). 그 외(검출 마스크가
        바뀜, undo/세션 로드로 스트로크 수가 줄어듬)는 처음부터 전체 재계산한다
        — 이 경우도 O(그 시점 전체 스트로크 수) 1회일 뿐, 매 커밋마다 커지진 않는다.
        """
        if self._detected_mask is None:
            self._invalidate_mask_cache()
            return None
        if (self._mask_cache_base is self._detected_mask
                and self._mask_cache_n_strokes <= len(self._manual_strokes)):
            new_strokes = self._manual_strokes[self._mask_cache_n_strokes:]
            if new_strokes:
                self._mask_cache_result = zone_metrics.apply_manual_strokes(
                    self._mask_cache_result, new_strokes
                )
                self._mask_cache_n_strokes = len(self._manual_strokes)
            return self._mask_cache_result
        self._mask_cache_result = self.apply_manual_strokes(self._detected_mask)
        self._mask_cache_base = self._detected_mask
        self._mask_cache_n_strokes = len(self._manual_strokes)
        return self._mask_cache_result

    def _invalidate_mask_cache(self) -> None:
        self._mask_cache_base = None
        self._mask_cache_n_strokes = 0
        self._mask_cache_result = None

    def apply_manual_strokes(self, mask: np.ndarray) -> np.ndarray:
        """zone_canvas.apply_manual_strokes()와 동일한 얇은 래퍼 —
        `zone_metrics.apply_manual_strokes()`(순수 함수)에 위임."""
        return zone_metrics.apply_manual_strokes(mask, self._manual_strokes)

    # ── Undo ─────────────────────────────────────────────────────────────────

    def _push_undo(self) -> None:
        self._undo_stack.append(self.get_state())

    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    def undo(self) -> None:
        if not self._undo_stack:
            return
        snap = self._undo_stack.pop()
        self.set_state(snap)

    def get_state(self) -> dict:
        return {
            "roi": self._normalized_tuple(self._roi_edges) if self._roi_edges else None,
            "erase_strokes": list(self._erase_strokes),
            "manual_strokes": list(self._manual_strokes),
        }

    def set_state(self, state: dict) -> None:
        roi = state.get("roi")
        self._roi_edges = self._edges_from_tuple(tuple(roi)) if roi else None
        self._erase_strokes = list(state.get("erase_strokes", []))
        self._manual_strokes = list(state.get("manual_strokes", []))
        self._invalidate_mask_cache()   # undo/세션 로드 — 스트로크 리스트가 통째로
        # 교체되므로 개수만 보는 캐시 휴리스틱을 믿지 않고 안전하게 전체 재계산한다.
        self._replay_erase_strokes()
        self._rebuild_stroke_overlay()
        self._rebuild_mask_image()
        self._drag_mode = None
        self._resize_handle = None
        self._current_stroke = []
        self._last_erase_pos = None
        self._erasing = False
        self.update()
        self.roi_changed.emit()
        self.roi_committed.emit()
        self.erase_changed.emit()
        self.mask_changed.emit()

    # ── 좌표 변환(원본 이미지 스케일 <-> 화면 스케일, zone_canvas 패턴 포팅) ─────

    def _orig_scale(self) -> tuple[float, float]:
        if self._pixmap is None or self._img_orig_w <= 0 or self._img_orig_h <= 0:
            return (1.0, 1.0)
        return (self._pixmap.width() / self._img_orig_w, self._pixmap.height() / self._img_orig_h)

    def _orig_to_screen_point(self, x: float, y: float) -> QPointF:
        sx, sy = self._orig_scale()
        return QPointF(x * sx * self._zoom + self._pan.x(), y * sy * self._zoom + self._pan.y())

    def _screen_to_orig(self, pt: QPointF) -> QPointF:
        sx, sy = self._orig_scale()
        px = (pt.x() - self._pan.x()) / self._zoom
        py = (pt.y() - self._pan.y()) / self._zoom
        return QPointF(px / sx if sx > 0 else px, py / sy if sy > 0 else py)

    # ── ROI 사각형 좌표 헬퍼 ─────────────────────────────────────────────────

    @staticmethod
    def _normalized_tuple(edges: dict[str, float]) -> tuple[float, float, float, float]:
        x0, x1 = sorted((edges["left"], edges["right"]))
        y0, y1 = sorted((edges["top"], edges["bottom"]))
        return (x0, y0, x1 - x0, y1 - y0)

    @staticmethod
    def _edges_from_tuple(t: tuple[float, float, float, float]) -> dict[str, float]:
        x, y, w, h = t
        return {"left": x, "top": y, "right": x + w, "bottom": y + h}

    def _edges_from_rect(self, rect: QRect) -> dict[str, float]:
        return self._edges_from_tuple((float(rect.x()), float(rect.y()),
                                        float(rect.width()), float(rect.height())))

    def _screen_rect(self) -> QRectF | None:
        if self._roi_edges is None:
            return None
        x, y, w, h = self._normalized_tuple(self._roi_edges)
        return QRectF(self._orig_to_screen_point(x, y), self._orig_to_screen_point(x + w, y + h))

    def _handle_points(self, rect: QRectF) -> dict[str, QPointF]:
        cx, cy = rect.center().x(), rect.center().y()
        return {
            "nw": rect.topLeft(), "n": QPointF(cx, rect.top()), "ne": rect.topRight(),
            "e": QPointF(rect.right(), cy), "se": rect.bottomRight(), "s": QPointF(cx, rect.bottom()),
            "sw": rect.bottomLeft(), "w": QPointF(rect.left(), cy),
        }

    def _hit_test(self, pt: QPointF) -> tuple[str, str | None] | None:
        rect = self._screen_rect()
        if rect is None:
            return None
        for name, hp in self._handle_points(rect).items():
            if math.hypot(pt.x() - hp.x(), pt.y() - hp.y()) <= _HANDLE_PX:
                return ("resize", name)
        if rect.contains(pt):
            return ("move", None)
        return None

    def _begin_resize(self, handle: str) -> None:
        fixed_names, movable_names = _HANDLE_FIXED_MOVABLE[handle]
        self._fixed_edges = {name: self._roi_edges[name] for name in fixed_names}
        self._movable_edges = movable_names
        self._resize_handle = handle

    def _update_resize(self, orig_pt: QPointF) -> None:
        edges = dict(self._fixed_edges)
        for name in self._movable_edges:
            edges[name] = orig_pt.x() if name in ("left", "right") else orig_pt.y()
        self._roi_edges = edges

    def _update_move(self, orig_pt: QPointF) -> None:
        dx = orig_pt.x() - self._press_orig_pt.x()
        dy = orig_pt.y() - self._press_orig_pt.y()
        snap = self._move_snapshot
        self._roi_edges = {
            "left": snap["left"] + dx, "right": snap["right"] + dx,
            "top": snap["top"] + dy, "bottom": snap["bottom"] + dy,
        }

    # ── 브러시 스탬프(zone_canvas._erase_stamp 등 포팅, 블랍 라벨 의존 제거) ─────

    def _erase_mask_shape(self) -> tuple[int, int]:
        return (self._img_orig_h, self._img_orig_w)

    def _erase_stamp(self, cx: float, cy: float, r: float) -> None:
        h, w = self._erase_mask_shape()
        if h <= 0 or w <= 0:
            return
        if self._erase_mask_np is None:
            self._erase_mask_np = np.zeros((h, w), dtype=bool)
        cxi, cyi, ri = int(cx), int(cy), max(1, int(r))
        y0, y1 = max(0, cyi - ri), min(h, cyi + ri + 1)
        x0, x1 = max(0, cxi - ri), min(w, cxi + ri + 1)
        if x1 <= x0 or y1 <= y0:
            return
        ys, xs = np.ogrid[y0:y1, x0:x1]
        circle = (ys - cyi) ** 2 + (xs - cxi) ** 2 <= ri ** 2
        self._erase_mask_np[y0:y1, x0:x1][circle] = True

    def _erase_paint_at(self, img_pt: QPointF) -> None:
        r = max(1, self._erase_brush_size // 2)
        self._erase_stamp(img_pt.x(), img_pt.y(), r)
        self._current_stroke.append((img_pt.x(), img_pt.y(), float(r)))

    def _erase_paint_stroke(self, img_pt: QPointF) -> None:
        if self._last_erase_pos is None:
            self._erase_paint_at(img_pt)
            self._last_erase_pos = img_pt
            return
        x0, y0 = self._last_erase_pos.x(), self._last_erase_pos.y()
        x1, y1 = img_pt.x(), img_pt.y()
        dx, dy = x1 - x0, y1 - y0
        dist = (dx * dx + dy * dy) ** 0.5
        r = max(1, self._erase_brush_size // 2)
        step = max(1.0, r * 0.4)
        if dist <= step:
            self._erase_paint_at(img_pt)
        else:
            n = max(1, int(dist / step))
            inv = 1.0 / n
            for i in range(1, n + 1):
                t = i * inv
                self._erase_paint_at(QPointF(x0 + dx * t, y0 + dy * t))
        self._last_erase_pos = img_pt

    def _replay_erase_strokes(self) -> None:
        h, w = self._erase_mask_shape()
        if h <= 0 or w <= 0 or not self._erase_strokes:
            self._erase_mask_np = None
            return
        mask = np.zeros((h, w), dtype=bool)
        for stroke in self._erase_strokes:
            for cx, cy, r in stroke:
                mask |= zone_metrics.disk_mask(cx, cy, r, (h, w))
        self._erase_mask_np = mask

    def _ensure_stroke_overlay(self) -> None:
        if self._pixmap is None:
            return
        size = self._pixmap.size()
        if self._stroke_overlay is None or self._stroke_overlay.size() != size:
            self._stroke_overlay = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
            self._stroke_overlay.fill(Qt.GlobalColor.transparent)

    def _rasterize_stroke(self, draw: bool, stroke: list[tuple[float, float, float]]) -> None:
        self._ensure_stroke_overlay()
        if self._stroke_overlay is None:
            return
        sx, sy = self._orig_scale()
        s = (sx + sy) / 2
        p = QPainter(self._stroke_overlay)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_COLOR_DRAW if draw else _COLOR_ERASE)
        for cx, cy, r in stroke:
            p.drawEllipse(QPointF(cx * sx, cy * sy), r * s, r * s)
        p.end()

    def _rebuild_stroke_overlay(self) -> None:
        self._stroke_overlay = None
        if self._pixmap is None:
            return
        for draw, stroke in self._manual_strokes:
            self._rasterize_stroke(draw, stroke)

    # ── 마스크 오버레이(임의 블롭 모양, zone_canvas엔 없던 신규 렌더링) ──────────

    def _rebuild_mask_image(self) -> None:
        mask = self.effective_mask()
        if mask is None or not mask.any():
            self._mask_image = None
            return
        h, w = mask.shape
        rgba = np.zeros((h, w, 4), dtype=np.uint8)
        rgba[mask] = (*_COLOR_MASK[:3], self._mask_alpha)
        img = QImage(rgba.data, w, h, w * 4, QImage.Format.Format_RGBA8888)
        self._mask_image = img.copy()   # numpy 버퍼와 분리(생명주기 안전)

    def _paint_mask_overlay(self, p: QPainter) -> None:
        if not self._mask_visible:
            return
        if self._mask_image is None:
            return
        sx, sy = self._orig_scale()
        p.save()
        p.translate(self._pan)
        p.scale(self._zoom * sx, self._zoom * sy)
        p.drawImage(0, 0, self._mask_image)
        p.restore()

    def _paint_stroke_preview(self, p: QPainter) -> None:
        if self._stroke_overlay is not None:
            p.save()
            p.translate(self._pan)
            p.scale(self._zoom, self._zoom)
            p.drawImage(0, 0, self._stroke_overlay)
            p.restore()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_COLOR_DRAW if self._mode == "brush_draw" else _COLOR_ERASE)
        for cx, cy, r in self._current_stroke:
            sx, sy = self._orig_scale()
            s = (sx + sy) / 2
            center = self._orig_to_screen_point(cx, cy)
            radius = r * s * self._zoom
            p.drawEllipse(center, radius, radius)

    def _paint_roi(self, p: QPainter) -> None:
        rect = self._screen_rect()
        if rect is None:
            return
        pen = QPen(_COLOR_ROI, 2)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(rect)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_COLOR_ROI)
        for hp in self._handle_points(rect).values():
            p.drawRect(QRectF(hp.x() - 4, hp.y() - 4, 8, 8))

    # ── paintEvent ───────────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._pixmap is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._paint_mask_overlay(p)
        if self._manual_strokes or self._current_stroke:
            self._paint_stroke_preview(p)
        self._paint_roi(p)
        p.end()

    # ── 마우스 ───────────────────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        if self._mode == "pan":
            super().mousePressEvent(event)
            return
        if self._mode in ("brush_draw", "brush_erase"):
            if event.button() == Qt.MouseButton.LeftButton and self._pixmap is not None:
                self._push_undo()
                self._current_stroke = []
                self._last_erase_pos = None
                self._erasing = True
                img_pt = self._screen_to_orig(QPointF(event.position()))
                self._erase_paint_stroke(img_pt)
                self.update()
            else:
                super().mousePressEvent(event)
            return
        if self._pixmap is None or event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self._push_undo()
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        pt = QPointF(event.position())
        orig_pt = self._screen_to_orig(pt)
        self._press_orig_pt = orig_pt
        hit = self._hit_test(pt)
        if hit is not None:
            kind, handle = hit
            if kind == "move":
                self._drag_mode = "move"
                self._move_snapshot = dict(self._roi_edges)
            else:
                self._begin_resize(handle)
                self._drag_mode = "resize"
        else:
            self._roi_edges = self._edges_from_tuple((orig_pt.x(), orig_pt.y(), 0.0, 0.0))
            self._begin_resize("se")
            self._drag_mode = "create"
        self.update()
        self.roi_changed.emit()

    def mouseMoveEvent(self, event) -> None:
        if self._mode == "pan":
            super().mouseMoveEvent(event)
            return
        if self._mode in ("brush_draw", "brush_erase"):
            if self._erasing and (event.buttons() & Qt.MouseButton.LeftButton):
                img_pt = self._screen_to_orig(QPointF(event.position()))
                self._erase_paint_stroke(img_pt)
                self.update()
            else:
                super().mouseMoveEvent(event)
            return
        if self._drag_mode is None:
            super().mouseMoveEvent(event)
            return
        orig_pt = self._screen_to_orig(QPointF(event.position()))
        if self._drag_mode == "move":
            self._update_move(orig_pt)
        else:   # "resize" | "create"
            self._update_resize(orig_pt)
        self.update()
        self.roi_changed.emit()

    def mouseReleaseEvent(self, event) -> None:
        if self._mode == "pan":
            super().mouseReleaseEvent(event)
            return
        if self._mode in ("brush_draw", "brush_erase"):
            if self._erasing:
                if self._current_stroke:
                    stroke_entry = (self._mode == "brush_draw", self._current_stroke)
                    self._manual_strokes.append(stroke_entry)
                    self._rasterize_stroke(*stroke_entry)
                    if self._mode == "brush_erase":
                        self._erase_strokes.append(self._current_stroke)
                self._current_stroke = []
                self._last_erase_pos = None
                self._erasing = False
                self._rebuild_mask_image()
                self.update()
                self.erase_changed.emit()
                self.mask_changed.emit()
            else:
                super().mouseReleaseEvent(event)
            return
        if self._drag_mode == "create" and self._roi_edges is not None:
            x, y, w, h = self._normalized_tuple(self._roi_edges)
            sx, sy = self._orig_scale()
            screen_w, screen_h = w * sx * self._zoom, h * sy * self._zoom
            if screen_w < _MIN_CREATE_PX or screen_h < _MIN_CREATE_PX:
                if self._undo_stack:
                    snap = self._undo_stack.pop()
                    roi = snap["roi"]
                    self._roi_edges = self._edges_from_tuple(tuple(roi)) if roi else None
            else:
                self._roi_edges = self._edges_from_tuple((x, y, w, h))
        elif self._drag_mode in ("resize", "move") and self._roi_edges is not None:
            self._roi_edges = self._edges_from_tuple(self._normalized_tuple(self._roi_edges))
        self._drag_mode = None
        self._resize_handle = None
        super().mouseReleaseEvent(event)
        self.update()
        self.roi_changed.emit()
        self.roi_committed.emit()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_F and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            self.overlay_toggle_requested.emit()
            return
        if event.matches(QKeySequence.StandardKey.Undo):
            self.undo()
            return
        super().keyPressEvent(event)


if __name__ == "__main__":
    # ── self-check: Qt 비의존 상태머신 수학만 검증(위젯 생성 없이) ────────────
    edges = RRoiCanvas._edges_from_tuple((10.0, 20.0, 30.0, 40.0))
    assert edges == {"left": 10.0, "top": 20.0, "right": 40.0, "bottom": 60.0}
    assert RRoiCanvas._normalized_tuple(edges) == (10.0, 20.0, 30.0, 40.0)

    # 뒤집힌 edges(오른쪽 핸들을 왼쪽 경계보다 더 왼쪽으로 드래그)도 정규화되어야 함
    flipped = {"left": 50.0, "top": 10.0, "right": 5.0, "bottom": 30.0}
    assert RRoiCanvas._normalized_tuple(flipped) == (5.0, 10.0, 45.0, 20.0)

    # se 핸들 리사이즈: 고정=left/top, 이동=right/bottom
    fixed_names, movable_names = _HANDLE_FIXED_MOVABLE["se"]
    assert fixed_names == ("left", "top") and movable_names == ("right", "bottom")
    # nw 핸들은 반대
    fixed_names2, movable_names2 = _HANDLE_FIXED_MOVABLE["nw"]
    assert fixed_names2 == ("right", "bottom") and movable_names2 == ("left", "top")

    # set_mask_opacity(): 저장/클램프만 Qt 비의존적으로 검증(렌더링은 QImage 생성 필요해 생략)
    class _FakeCanvas:
        _mask_alpha = 90
        set_mask_opacity = RRoiCanvas.set_mask_opacity
        mask_opacity = RRoiCanvas.mask_opacity
        def _rebuild_mask_image(self): pass
        def update(self): pass
    fc = _FakeCanvas()
    fc.set_mask_opacity(35)
    assert fc.mask_opacity() == 35
    fc.set_mask_opacity(999)   # 클램프 상한
    assert fc.mask_opacity() == 255
    fc.set_mask_opacity(-10)   # 클램프 하한
    assert fc.mask_opacity() == 0

    # set_mask_overlay_visible(): 플래그 저장 + _paint_mask_overlay()가 숨김 시
    # 그리기를 건너뛰는지(painter에 손대지 않고 바로 return 하는지) 확인.
    class _FakeCanvas2:
        _mask_visible = True
        _mask_image = "not-none-sentinel"
        set_mask_overlay_visible = RRoiCanvas.set_mask_overlay_visible
        _paint_mask_overlay = RRoiCanvas._paint_mask_overlay
        def update(self): pass
    fc2 = _FakeCanvas2()
    fc2.set_mask_overlay_visible(False)
    assert fc2._mask_visible is False
    fc2._paint_mask_overlay(None)   # painter 미사용 경로 — None이어도 에러 없이 즉시 리턴
    fc2.set_mask_overlay_visible(True)
    assert fc2._mask_visible is True

    print("r_roi_canvas self-check OK")
