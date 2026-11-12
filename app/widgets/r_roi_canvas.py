"""R 분석 탭 캔버스 — 이미지 표시 + ROI(사각형 1개) 편집 + 마스크 보정.

`overlay_viewer.OverlayViewer`의 줌/팬 QPainter 패턴을 그대로 상속(zone_canvas.py와
동일 관례). ROI는 항상 "원본 이미지 픽셀 좌표"로 보관하고 화면에는 오버레이 픽스맵
스케일 + 줌/팬을 거쳐 투영한다(zone_canvas의 원 좌표 변환과 동일 원리).

이 파일은 `zone_canvas.py`의 구조(드래그 생성/이동/리사이즈 상태머신, 브러시 지우기/
그리기 스탬프, 경량 undo 스택, 150ms 아님 — 여기선 디바운스 없음, debounce는
threshold 슬라이더 쪽 책임)를 **상속이 아니라 복사 포팅**한 것이다 — 원(circle)
특화 기하 수학을 사각형(rect) 8-handle 리사이즈로 바꾼 것 외에는 브러시 스탬프/
undo 메커니즘이 동일하다(스펙 요구사항 7, "원↔임의 블롭 모양 수학이 다르기 때문").

별도의 "블랍 삭제 모드"는 없다 — 모드는 "roi"(기본, ROI 편집 + 블랍 클릭 선택 →
Delete) | "brush_draw" | "brush_erase" | "pan" 4가지뿐. 블랍은 유효 마스크(검출 −
삭제 + 브러시)의 연결 성분이라 브러시로 그린 영역도 선택·삭제된다.
"""
import math

import numpy as np
from PyQt6.QtGui import QPainter, QPen, QColor, QImage, QKeySequence, qRgba
from PyQt6.QtCore import Qt, QPointF, QRectF, QRect, pyqtSignal

from app.widgets.overlay_viewer import OverlayViewer
from app.core import zone_metrics
from app.core.r_analysis_metrics import apply_edits

_HANDLE_PX = 8.0        # 리사이즈 핸들 히트 판정 반경 — 화면 픽셀
_MIN_CREATE_PX = 6.0    # 이보다 작게 생성 드래그하면 취소
_CLICK_PX = 3.0         # ROI 안쪽 press~release 이동이 이 이하면 드래그가 아니라 클릭

_COLOR_ROI = QColor(45, 212, 191)           # teal-400 — 마스크/브러시 색과 구분. 기존
# amber(250,204,21)는 _COLOR_SELECTED(255,200,0)와 RGB 거리가 너무 가까워(디자인 검토
# 2026-11-10, 실제 스크린샷으로 비선택/선택 ROI가 육안 구분 불가 수준임을 확인) teal로
# 교체 — 선택색(노랑)과 색상환상 거리를 크게 벌려 선택 여부가 두께 변화 없이도 보인다.
_COLOR_DRAW = QColor(96, 165, 250, 110)     # zone_canvas._COLOR_DRAW 재사용(accent blue)
_COLOR_ERASE = QColor(156, 163, 175, 110)   # zone_canvas._COLOR_ERASE 재사용
_COLOR_MASK = (34, 197, 94, 90)             # 검출된(+보정된) 마스크 오버레이, green-500
_COLOR_SELECTED = QColor(255, 200, 0)       # 앱 표준 "선택" 색(zone_canvas._COLOR_SELECTED와 동일)

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
    blob_deleted = pyqtSignal(int)  # 선택된 블랍이 Delete로 삭제된 라벨 id (zone_canvas와 동일 시그니처)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._img_orig_w = 0
        self._img_orig_h = 0
        self._mode: str = "roi"

        # ── ROI 상태머신 ─────────────────────────────────────────────────────
        self._roi_edges: dict[str, float] | None = None   # {"left","top","right","bottom"}, 원본 좌표
        self._roi_selected: bool = False   # 선택된 ROI — Delete/Backspace로 삭제 가능
        self._drag_mode: str | None = None    # None | "move" | "resize" | "create"
        self._resize_handle: str | None = None
        self._fixed_edges: dict[str, float] = {}
        self._movable_edges: tuple[str, ...] = ()
        self._press_orig_pt: QPointF | None = None
        self._press_screen_pt: QPointF | None = None
        self._move_snapshot: dict[str, float] | None = None

        # ── 블랍 선택/삭제(설계 결정 2·3 — zone_canvas 블랍 삭제와 달리 "선택 후
        # Delete" 흐름, 영속 데이터는 라벨 id가 아니라 bbox 목록) ────────────────
        self._selected_blob_id: int | None = None
        self._blob_labels: np.ndarray | None = None   # (H, W) int32 라벨맵 — 파생값, 영속화 안 함
        self._blob_stats: np.ndarray | None = None     # [label] = [x, y, w, h, area] — 파생값
        self._blob_labels_src: np.ndarray | None = None   # 라벨맵을 계산한 유효 마스크(identity 비교)
        # (x, y, w, h, n) 원본 좌표 — n = 삭제 시점의 스트로크 개수(apply_edits 참고).
        # 기존 세션 파일의 4-원소(n 없음 = 0)도 그대로 들고 있는다. 진짜 상태.
        self._deleted_blob_regions: list[tuple[float, ...]] = []

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
        self._erase_strokes: list[list[tuple[float, float, float]]] = []   # 세션 erase_strokes 키 형식 유지용 레거시 목록
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
        이미지의 재검출이므로 — threshold/ROI 조정 시 반복 호출됨).

        `_deleted_blob_regions`(진짜 영속 데이터)는 리셋하지 않는다(설계 결정 3 —
        threshold 등 설정 변경마다 호출되는 이 메서드가 매번 삭제 이력을 지우면
        회귀가 생긴다). 라벨 id 기반 선택 상태만 리셋(엣지케이스 2)."""
        self._detected_mask = mask
        self._invalidate_mask_cache()   # 재검출 결과가 낡은 캐시에 가려지면 안 된다(BUG-056)
        self._selected_blob_id = None
        self.set_highlight_rect(None)
        self._rebuild_mask_image()
        self.update()
        self.mask_changed.emit()

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
        """검출 마스크 + 블랍 삭제 + 수동 그리기/지우기 반영 최종 마스크(면적 계산용).
        계산은 일괄 검출 워커와 같은 `apply_edits()` 하나 — 따로 계산하지 않는다(BUG-054).

        P0 성능: 캐시가 지금 `_detected_mask`와 같은 배열 기준이고(식별 비교 —
        `set_detected_mask()`가 재검출마다 새 배열을 넘기므로 충분) 캐시에 반영된
        스트로크 수가 현재 `_manual_strokes` 길이 이하면, 새로 추가된 스트로크만 캐시
        결과 위에 덧적용한다(전체 재생 금지 — 삭제 영역은 전부 캐시 시점 이전 것이라
        뒤에 붙는 스트로크엔 영향이 없다). 재검출/블랍 삭제/undo/세션 로드는
        `_invalidate_mask_cache()`를 거쳐 처음부터 1회 전체 재계산한다.

        반환 배열은 제자리 수정하지 않는다 — 내용이 바뀌면 항상 새 배열이라,
        `_ensure_blob_labels()`가 identity만으로 라벨맵이 낡았는지 판정한다."""
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
        self._mask_cache_result = apply_edits(
            self._detected_mask, self._manual_strokes, self._deleted_blob_regions
        )
        self._mask_cache_base = self._detected_mask
        self._mask_cache_n_strokes = len(self._manual_strokes)
        return self._mask_cache_result

    def _invalidate_mask_cache(self) -> None:
        self._mask_cache_base = None
        self._mask_cache_n_strokes = 0
        self._mask_cache_result = None

    # ── 블랍 선택/삭제(설계 결정 2·3·5 — ROI 클릭 판정 안에 통합, zone_canvas
    # 블랍 삭제와 달리 "선택 후 Delete" 흐름) ───────────────────────────────────

    def _ensure_blob_labels(self) -> None:
        """블랍 라벨맵을 **유효 마스크**(검출 − 삭제 + 브러시) 기준으로 지연 계산 —
        브러시로 그린 영역도 블랍이고, 지우개로 갈라진 영역은 별개 블랍이다.
        클릭 히트테스트 때만 호출하고, 유효 마스크 배열이 바뀌었을 때만 다시 돈다
        (opacity 슬라이더·마우스 이동 같은 고빈도 경로에서 connectedComponents 금지)."""
        mask = self.effective_mask()
        if mask is self._blob_labels_src:
            return
        self._blob_labels_src = mask
        if mask is None:
            self._blob_labels = self._blob_stats = None
        else:
            self._blob_labels, self._blob_stats, _ = zone_metrics.compute_blob_labels(mask)

    def _blob_label_at(self, pt: QPointF | None) -> int | None:
        self._ensure_blob_labels()
        if pt is None or self._blob_labels is None:
            return None
        x, y = int(pt.x()), int(pt.y())
        h, w = self._blob_labels.shape
        if not (0 <= y < h and 0 <= x < w):
            return None
        label = int(self._blob_labels[y, x])
        return label if label != 0 else None

    def _select_blob(self, label: int) -> None:
        """`ZoneCanvas.highlight_blob_bbox()` 1:1 포팅 — `_blob_stats[label]`의
        bbox를 픽스맵 좌표로 변환해 `set_highlight_rect()`에 넘긴다."""
        self._selected_blob_id = label
        self._roi_selected = False
        if self._blob_stats is not None and 0 <= label < len(self._blob_stats):
            sx, sy = self._orig_scale()
            x, y, w, h = (float(v) for v in self._blob_stats[label, :4])
            self.set_highlight_rect(QRectF(x * sx, y * sy, w * sx, h * sy))
        self.update()

    def _deselect_all(self) -> None:
        self._roi_selected = False
        self._selected_blob_id = None
        self.set_highlight_rect(None)
        self.update()

    def _delete_selected_blob(self) -> None:
        if self._selected_blob_id is None or self._blob_stats is None:
            return
        label = self._selected_blob_id
        if not (0 <= label < len(self._blob_stats)):
            return
        self._push_undo()
        # ponytail: bbox 근사(설계 결정 3의 알려진 한계) — bbox에 걸친 다른 블랍 픽셀도
        # 같이 지워진다. 재검출 뒤에도 삭제가 유지되려면 라벨 id가 아니라 좌표 영역이어야
        # 해서 bbox로 저장한다. 정확한 모양이 필요해지면 블랍 마스크(RLE) 저장으로 교체.
        x, y, w, h = (float(v) for v in self._blob_stats[label, :4])
        self._deleted_blob_regions.append((x, y, w, h, len(self._manual_strokes)))
        self._invalidate_mask_cache()
        self._rebuild_mask_image()
        self._selected_blob_id = None
        self.set_highlight_rect(None)
        self.update()
        self.blob_deleted.emit(label)
        self.mask_changed.emit()

    # ── Undo ─────────────────────────────────────────────────────────────────

    def _push_undo(self) -> None:
        self._undo_stack.append(self.get_state())

    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    def undo(self) -> None:
        if not self._undo_stack:
            return
        self._restore_state(self._undo_stack.pop())

    def get_state(self) -> dict:
        return {
            "roi": self._normalized_tuple(self._roi_edges) if self._roi_edges else None,
            "erase_strokes": list(self._erase_strokes),
            "manual_strokes": list(self._manual_strokes),
            "removed_blob_regions": list(self._deleted_blob_regions),
        }

    def set_state(self, state: dict) -> None:
        """외부에서 상태를 통째로 교체(이미지 전환/세션 로드) — 이전 이미지의 undo
        이력은 버린다(BUG-060: 남겨두면 Ctrl+Z가 옛 이미지 편집을 새 이미지에 적용)."""
        self._undo_stack.clear()
        self._restore_state(state)

    def clear(self) -> None:
        self._undo_stack.clear()
        super().clear()

    def _restore_state(self, state: dict) -> None:
        roi = state.get("roi")
        self._roi_edges = self._edges_from_tuple(tuple(roi)) if roi else None
        self._erase_strokes = list(state.get("erase_strokes", []))
        self._manual_strokes = list(state.get("manual_strokes", []))
        # 역호환: 기존 세션 파일엔 이 키가 없거나 4-원소(n 없음 = 0)일 수 있음(설계 결정 7).
        self._deleted_blob_regions = [tuple(r) for r in state.get("removed_blob_regions", [])]
        self._invalidate_mask_cache()   # undo/세션 로드 — 스트로크 리스트가 통째로
        # 교체되므로 개수만 보는 캐시 휴리스틱을 믿지 않고 안전하게 전체 재계산한다.
        self._rebuild_stroke_overlay()
        self._rebuild_mask_image()
        self._drag_mode = None
        self._resize_handle = None
        self._current_stroke = []
        self._last_erase_pos = None
        self._erasing = False
        # 선택 상태는 undo/영속 대상이 아님(설계 결정 7) — 이미지/셀 전환, undo
        # 시 항상 리셋(엣지케이스 4).
        self._roi_selected = False
        self._selected_blob_id = None
        self.set_highlight_rect(None)
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

    # ── 브러시 스탬프(zone_canvas 포팅, 블랍 라벨 의존 제거) ─────

    def _erase_paint_at(self, img_pt: QPointF) -> None:
        r = max(1, self._erase_brush_size // 2)
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
        # perf D8: RGBA 배열을 만들지 않고 bool 마스크를 Indexed8로 무복사 래핑 —
        # 색·알파는 컬러 테이블(0=투명, 1=마스크색). 버퍼는 _mask_image_buf로 수명 유지
        # (effective_mask() 결과는 제자리 수정되지 않는다). 불투명도 변경도 이 래핑을
        # 다시 할 뿐이라 비용 ≈0 — 기존 QImage에 setColorTable하면 detach 복사가 날 수 있다.
        if mask.dtype != bool:
            mask = mask.astype(bool)   # 0/255 uint8이면 인덱스 255가 테이블 밖
        buf = np.ascontiguousarray(mask).view(np.uint8)
        h, w = buf.shape
        img = QImage(buf.data, w, h, w, QImage.Format.Format_Indexed8)
        img.setColorTable([0, qRgba(*_COLOR_MASK[:3], self._mask_alpha)])
        self._mask_image_buf = buf
        self._mask_image = img

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

    def _paint_committed_strokes(self, p: QPainter) -> None:
        """커밋된 전체 스트로크 래스터 — 검출 마스크가 없을 때만(그 외엔 _mask_image가
        effective_mask()를 이미 반영하므로 이걸 또 그리면 이중 렌더링이 된다)."""
        if self._stroke_overlay is None:
            return
        p.save()
        p.translate(self._pan)
        p.scale(self._zoom, self._zoom)
        p.drawImage(0, 0, self._stroke_overlay)
        p.restore()

    def _paint_current_stroke(self, p: QPainter) -> None:
        """드래그 중(아직 커밋 안 됨)인 스트로크 — mask_image 유무와 무관하게 항상 미리보기."""
        if not self._current_stroke:
            return
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_COLOR_DRAW if self._mode == "brush_draw" else _COLOR_ERASE)
        for cx, cy, r in self._current_stroke:
            sx, sy = self._orig_scale()
            s = (sx + sy) / 2
            center = self._orig_to_screen_point(cx, cy)
            radius = r * s * self._zoom
            p.drawEllipse(center, radius, radius)

    def _paint_strokes(self, p: QPainter) -> None:
        """커밋된 스트로크(검출 마스크 없을 때만) + 드래그 중 스트로크(항상) 디스패치.
        로직을 분리해 self-check에서 QPainter 없이 검증 가능하게 했다.

        `_mask_image is None`으로 판정하면 안 된다 — 유효 마스크가 0px일 때도 None이라
        전부 지운 뒤 파랑/회색 스트로크가 잔상으로 남는다(BUG-055)."""
        if self._detected_mask is None:
            self._paint_committed_strokes(p)
        self._paint_current_stroke(p)

    def _paint_roi(self, p: QPainter) -> None:
        rect = self._screen_rect()
        if rect is None:
            return
        color = _COLOR_SELECTED if self._roi_selected else _COLOR_ROI
        pen = QPen(color, 4 if self._roi_selected else 2)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(rect)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
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
        self._paint_strokes(p)
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
        self._press_screen_pt = pt
        hit = self._hit_test(pt)
        if hit is not None:
            kind, handle = hit
            if kind == "move":
                self._drag_mode = "move"
                self._move_snapshot = dict(self._roi_edges)
            else:
                self._begin_resize(handle)
                self._drag_mode = "resize"
            # ROI 테두리/핸들/내부를 직접 클릭 — 즉시 선택 상태로(설계 결정 2).
            self._roi_selected = True
            self._selected_blob_id = None
            self.set_highlight_rect(None)
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
                # 유효 마스크가 바뀌면 블랍도 바뀐다 — 낡은 선택(bbox)을 들고 있지 않는다.
                self._selected_blob_id = None
                self.set_highlight_rect(None)
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
                # 드래그가 아니라 단순 클릭이었던 지점 — 블랍이 있으면 선택,
                # 없으면 전체 선택 해제(설계 결정 2).
                label = self._blob_label_at(self._press_orig_pt)
                if label:
                    self._select_blob(label)
                else:
                    self._deselect_all()
            else:
                self._roi_edges = self._edges_from_tuple((x, y, w, h))
                self._roi_selected = True   # 방금 만든 ROI는 선택 상태로 시작
                self._selected_blob_id = None
                self.set_highlight_rect(None)
        elif self._drag_mode in ("resize", "move") and self._roi_edges is not None:
            # ROI 안쪽을 드래그 없이 클릭했고 그 자리에 블랍이 있으면 ROI가 아니라 블랍
            # 선택 — 검출 결과는 전부 ROI 안에 있어서, 이게 없으면 블랍을 고를 수 없다.
            release = QPointF(event.position())
            label = None
            if (self._drag_mode == "move" and self._press_screen_pt is not None
                    and math.hypot(release.x() - self._press_screen_pt.x(),
                                   release.y() - self._press_screen_pt.y()) <= _CLICK_PX):
                label = self._blob_label_at(self._press_orig_pt)
            if label:
                if self._undo_stack:
                    self._undo_stack.pop()   # press에서 쌓은 스냅샷은 no-op
                self._roi_edges = dict(self._move_snapshot)   # 클릭 중 1~3px 손떨림 이동 취소
                self._select_blob(label)
            else:
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
        if self._mode == "roi" and event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            if self._selected_blob_id is not None:
                self._delete_selected_blob()
            elif self._roi_selected and self._roi_edges is not None:
                self.set_roi(None)   # 기존 메서드 — 내부에서 이미 _push_undo() 호출
                self._roi_selected = False
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

    # _paint_strokes(): 커밋 후(effective_mask 있음) 파란/회색 덧칠이 사라지고
    # 드래그 중 미리보기만 항상 그려지는지(사용자가 명시한 핵심 버그 수정) 확인.
    class _FakeCanvas3:
        _detected_mask = None
        _paint_strokes = RRoiCanvas._paint_strokes
        def __init__(self):
            self.calls = []
        def _paint_committed_strokes(self, p):
            self.calls.append("committed")
        def _paint_current_stroke(self, p):
            self.calls.append("current")
    fc3 = _FakeCanvas3()
    fc3._paint_strokes(None)   # 마스크 없음 → 커밋 래스터도 보여줘야(유일한 피드백)
    assert fc3.calls == ["committed", "current"]
    fc3b = _FakeCanvas3()
    fc3b._detected_mask = "detected"   # 검출 완료 → 커밋 래스터는 더 이상 그리지 않음
    fc3b._paint_strokes(None)
    assert fc3b.calls == ["current"]

    # ── self-check: 블랍 선택/삭제 + ROI 선택/삭제(실제 위젯, offscreen) ────────
    import os as _os
    import sys as _sys
    _os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import QEvent as _QEvent
    from PyQt6.QtGui import QKeyEvent as _QKeyEvent, QPixmap as _QPixmap
    from PyQt6.QtWidgets import QApplication as _QApplication

    _app = _QApplication.instance() or _QApplication(_sys.argv)

    h, w = 50, 60
    mask = np.zeros((h, w), dtype=bool)
    mask[5:15, 5:15] = True     # 블랍 A — 100px
    mask[5:15, 40:50] = True    # 블랍 B — 100px
    assert mask.sum() == 200

    canvas = RRoiCanvas()
    canvas.set_image_size(w, h)
    canvas.set_pixmap(_QPixmap(w, h))
    canvas.set_detected_mask(mask)

    def _label_at_bbox(c: RRoiCanvas, x: int, y: int) -> int:
        lbl = c._blob_label_at(QPointF(x, y))
        assert lbl is not None, f"({x},{y})에 블랍이 있어야 함"
        return lbl

    label_a = _label_at_bbox(canvas, 10, 10)
    label_b = _label_at_bbox(canvas, 45, 10)
    assert label_a != label_b

    # (1) _select_blob()/_deselect_all() 상태 전환.
    canvas._select_blob(label_b)
    assert canvas._selected_blob_id == label_b and canvas._roi_selected is False
    assert canvas._highlight_rect is not None
    canvas._deselect_all()
    assert canvas._selected_blob_id is None and canvas._highlight_rect is None

    # (2) 삭제 전후 effective_mask() 픽셀 수 감소 확인.
    count_before = int(canvas.effective_mask().sum())
    assert count_before == 200
    canvas._select_blob(label_a)
    canvas._delete_selected_blob()
    assert canvas._selected_blob_id is None   # 삭제 후 선택 해제됨
    count_after = int(canvas.effective_mask().sum())
    assert count_after == count_before - 100, (count_before, count_after)
    assert len(canvas._deleted_blob_regions) == 1

    # (3) 같은 블랍을 삭제한 뒤 다른 threshold로 재검출해도(set_detected_mask() 재호출)
    # _deleted_blob_regions가 살아있는지(설계 결정 3의 핵심 보장).
    mask2 = mask.copy()
    mask2[20:25, 20:25] = True   # 전혀 다른 위치에 새 블랍 하나 추가(threshold 변경 시뮬레이션)
    canvas.set_detected_mask(mask2)
    assert len(canvas._deleted_blob_regions) == 1, "재검출해도 삭제 이력이 유지돼야 함(설계 결정 3)"
    assert canvas._selected_blob_id is None   # 엣지케이스 2 — 재검출 시 선택 리셋

    # (4) Delete 키 디스패치 — 블랍 선택 상태에서 Delete → 블랍만 지워짐(ROI 안 지워짐).
    canvas.set_roi(QRect(0, 0, 5, 5))
    label_b2 = _label_at_bbox(canvas, 45, 10)
    canvas._select_blob(label_b2)
    regions_before = len(canvas._deleted_blob_regions)
    del_press = _QKeyEvent(_QEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier)
    canvas.keyPressEvent(del_press)
    assert len(canvas._deleted_blob_regions) == regions_before + 1
    assert canvas.get_roi() is not None, "블랍 삭제가 선택되지 않은 ROI까지 지우면 안 됨"

    # ROI 선택 상태에서 Delete → ROI만 지워짐.
    canvas._roi_selected = True
    canvas._selected_blob_id = None
    regions_before2 = len(canvas._deleted_blob_regions)
    canvas.keyPressEvent(del_press)
    assert canvas.get_roi() is None
    assert len(canvas._deleted_blob_regions) == regions_before2   # 블랍 삭제 이력은 그대로

    # 브러시/pan 모드에서는 Delete가 무동작(가드 확인, 엣지케이스 10).
    canvas.set_roi(QRect(0, 0, 5, 5))
    canvas._roi_selected = True
    canvas.set_pan_mode(True)
    canvas.keyPressEvent(del_press)
    assert canvas.get_roi() is not None, "roi 모드가 아니면 Delete가 ROI를 지우면 안 됨"
    canvas.set_pan_mode(False)

    # (5) BUG-055: 그린 뒤 전부 지워 유효 마스크가 0px(_mask_image None)이어도, 검출
    # 마스크(빈 배열)가 있는 한 파랑/회색 커밋 스트로크 폴백을 그리면 안 됨.
    ghost = RRoiCanvas()
    ghost.set_image_size(w, h)
    ghost.set_pixmap(_QPixmap(w, h))
    ghost.set_detected_mask(np.zeros((h, w), dtype=bool))   # 자동검출 OFF와 같은 상태
    ghost.set_state({
        "roi": None, "removed_blob_regions": [],
        "manual_strokes": [(True, [(30.0, 25.0, 5.0)]), (False, [(30.0, 25.0, 15.0)])],
    })
    assert not ghost.effective_mask().any() and ghost._mask_image is None
    ghost_calls: list[str] = []
    ghost._paint_committed_strokes = lambda p: ghost_calls.append("committed")
    ghost._paint_strokes(None)
    assert ghost_calls == [], "유효 마스크가 비어도 커밋 스트로크 잔상을 그리면 안 됨(BUG-055)"

    # BUG-056: 블랍 삭제 후 재검출(threshold/ROI 변경)하면 새 검출 결과가 반영돼야 한다.
    stale_m = np.zeros((h, w), dtype=bool)
    stale_m[5:15, 5:15] = True
    stale_m[5:15, 40:50] = True
    stale = RRoiCanvas()
    stale.set_image_size(w, h)
    stale.set_pixmap(_QPixmap(w, h))
    stale.set_detected_mask(stale_m)
    stale._select_blob(stale._blob_label_at(QPointF(10, 10)))
    stale._delete_selected_blob()
    stale_m2 = stale_m.copy()
    stale_m2[30:40, 20:30] = True
    stale.set_detected_mask(stale_m2)
    assert int(stale.effective_mask().sum()) == 200, "재검출 결과가 삭제 캐시에 가려지면 안 됨(BUG-056)"

    # ── zone-v1.17.0: 실제 마우스 이벤트로 브러시/클릭/드래그를 재현 ──────────────
    from PyQt6.QtGui import QMouseEvent as _QMouseEvent

    def _new_canvas(det: np.ndarray) -> RRoiCanvas:
        c = RRoiCanvas()
        c.set_image_size(w, h)
        c.set_pixmap(_QPixmap(w, h))
        c.set_detected_mask(det)
        return c

    def _drag(c: RRoiCanvas, x0: float, y0: float, x1: float | None = None, y1: float | None = None) -> None:
        """원본 좌표 (x0,y0)에서 press, (x1,y1)이 있으면 거기까지 move 후 release."""
        left, none = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton
        mods = Qt.KeyboardModifier.NoModifier
        p0 = c._orig_to_screen_point(x0, y0)
        p1 = p0 if x1 is None else c._orig_to_screen_point(x1, y1)
        c.mousePressEvent(_QMouseEvent(_QEvent.Type.MouseButtonPress, p0, p0, left, left, mods))
        if x1 is not None:
            c.mouseMoveEvent(_QMouseEvent(_QEvent.Type.MouseMove, p1, p1, none, left, mods))
        c.mouseReleaseEvent(_QMouseEvent(_QEvent.Type.MouseButtonRelease, p1, p1, left, none, mods))

    def _brush(c: RRoiCanvas, draw: bool, size: int, *pts: float) -> None:
        c.set_erase_brush_size(size)
        (c.set_brush_draw_mode if draw else c.set_brush_erase_mode)(True)
        _drag(c, *pts)
        c.set_pan_mode(False)   # roi 모드로 복귀

    def _area(c: RRoiCanvas) -> int:
        return int(c.effective_mask().sum())

    def _matches_full_replay(c: RRoiCanvas) -> bool:
        # 증분 캐시 결과 == 워커가 쓰는 apply_edits() 전체 재생 결과
        return np.array_equal(
            c.effective_mask(), apply_edits(c._detected_mask, c._manual_strokes, c._deleted_blob_regions)
        )

    # (6) 변경 2: 브러시만으로 그린 영역 → 클릭 선택 → Delete → 면적 0 → Ctrl+Z 복원
    # → 다시 삭제 후 같은 자리에 재브러시하면 새로 그린 부분은 살아남.
    bc = _new_canvas(np.zeros((h, w), dtype=bool))
    _brush(bc, True, 10, 30, 25)
    brushed = _area(bc)
    assert brushed > 0
    _drag(bc, 30, 25)   # ROI 없음 → 단순 클릭
    assert bc._selected_blob_id is not None, "브러시로 그린 영역도 블랍으로 선택돼야 함"
    bc.keyPressEvent(del_press)
    assert _area(bc) == 0 and bc._mask_image is None, "브러시 블랍 삭제 후 면적 0이어야 함"
    assert bc._deleted_blob_regions[-1][4] == 1   # 삭제 시점 스트로크 수
    bc.undo()
    assert _area(bc) == brushed and bc._deleted_blob_regions == [], "Ctrl+Z로 삭제가 되돌려져야 함"
    _drag(bc, 30, 25)
    bc.keyPressEvent(del_press)
    assert _area(bc) == 0
    _brush(bc, True, 6, 30, 25)
    assert 0 < _area(bc) < brushed, "삭제 후 재브러시한 부분만 살아나야 함"
    assert _matches_full_replay(bc)
    assert bc._selected_blob_id is None

    # (7) 변경 2: 검출 블랍 A에 브러시가 붙으면 한 블랍 — 삭제 시 둘 다 사라지고 B만 남음.
    jc = _new_canvas(mask.copy())
    _drag(jc, 45, 10)             # B 선택해 둔 채로 브러시 → 낡은 선택은 풀려야 함
    assert jc._selected_blob_id is not None
    _brush(jc, True, 6, 17, 10)   # x=14..20 — A(5..14)에 붙음
    assert jc._selected_blob_id is None and jc._highlight_rect is None
    assert _area(jc) > 200
    assert jc._blob_label_at(QPointF(10, 10)) == jc._blob_label_at(QPointF(19, 10)) is not None
    _drag(jc, 19, 10)             # 브러시 쪽을 클릭해도 붙은 블랍 전체가 선택됨
    jc.keyPressEvent(del_press)
    assert _area(jc) == 100 and not jc.effective_mask()[:, :30].any(), "검출분+브러시분이 함께 삭제돼야 함"
    # 삭제 후 재검출해도 삭제(브러시분 포함)는 유지되고, 새 검출분은 반영됨(설계 결정 3 + BUG-056).
    mask3 = mask.copy()
    mask3[30:40, 20:30] = True
    jc.set_detected_mask(mask3)
    assert _area(jc) == 200 and not jc.effective_mask()[:20, :30].any()
    assert _matches_full_replay(jc)

    # 지우개로 갈라진 검출 영역은 각각 별개 블랍.
    split_m = np.zeros((h, w), dtype=bool)
    split_m[30:40, 10:40] = True
    sc = _new_canvas(split_m)
    assert sc._blob_label_at(QPointF(15, 35)) == sc._blob_label_at(QPointF(35, 35))
    _brush(sc, False, 6, 25, 26, 25, 44)
    assert sc._blob_label_at(QPointF(15, 35)) != sc._blob_label_at(QPointF(35, 35))
    assert sc._blob_label_at(QPointF(25, 35)) is None

    # 4-원소 삭제 영역(zone-v1.16.x 세션) — 오류 없이 열리고 이전처럼 "삭제 먼저, 스트로크 나중".
    lc = _new_canvas(mask.copy())
    lc.set_state({"roi": None, "manual_strokes": [[True, [[10.0, 10.0, 3.0]]]],
                  "removed_blob_regions": [[5.0, 5.0, 10.0, 10.0]]})
    assert lc.effective_mask()[10, 10] and not lc.effective_mask()[5, 5]
    assert 100 < _area(lc) < 200

    # BUG-060: 외부 set_state()는 undo 이력을 버리고, undo()는 여러 단계가 그대로 유지된다.
    uc = _new_canvas(mask.copy())
    _brush(uc, True, 6, 10, 50, 20, 50)
    _brush(uc, True, 6, 30, 50, 40, 50)
    assert len(uc._undo_stack) == 2
    uc.undo()
    assert len(uc._undo_stack) == 1 and len(uc.get_state()["manual_strokes"]) == 1
    uc.set_state({"roi": None, "manual_strokes": [], "removed_blob_regions": []})
    assert not uc.can_undo()

    # (8) 변경 3: ROI 안쪽 — 블랍 위 클릭은 블랍 선택, 빈 곳 클릭/드래그는 기존 ROI 동작.
    rc = _new_canvas(mask.copy())
    rc.set_roi(QRect(2, 2, 55, 45))
    n_undo = len(rc._undo_stack)
    _drag(rc, 45, 10)
    assert rc._selected_blob_id is not None and rc._roi_selected is False, \
        "ROI 안쪽이라도 블랍 위 클릭은 블랍 선택이어야 함"
    assert len(rc._undo_stack) == n_undo and rc.get_roi() == QRect(2, 2, 55, 45)
    _drag(rc, 30, 40)   # ROI 안쪽 빈 곳 클릭 → ROI 선택
    assert rc._roi_selected is True and rc._selected_blob_id is None and rc._highlight_rect is None
    _drag(rc, 45, 10, 49, 10)   # 블랍 위에서 시작했어도 실제 드래그면 ROI 이동
    assert rc.get_roi() == QRect(6, 2, 55, 45), rc.get_roi()
    assert rc._roi_selected is True and rc._selected_blob_id is None

    print("r_roi_canvas self-check OK")
