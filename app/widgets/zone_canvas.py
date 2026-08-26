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

라운드 4: "블랍 삭제 모드" 토글(`set_blob_delete_mode`) 활성화 시 좌클릭은 원
편집이 아니라 블랍(연결요소) 클릭 삭제로 해석된다(스펙 "UX 흐름 상세 > 블랍
삭제" — 같은 캔버스에서 두 조작이 충돌하지 않도록 최소한의 모드 토글만 둠).

라운드 R3-3: "브러시 지우기 모드"(`set_brush_erase_mode`) 추가 — 3번째 캔버스
모드. 원 편집/블랍삭제/브러시지우기는 `self._mode` 문자열 하나로 배타적으로
관리한다("circle" | "blob_delete" | "brush_erase"). 브러시 스탬프 엔진은
`annotation_canvas.py`의 `_paint_circle`/`_paint_stroke`(bbox-crop 벡터화 원판
+ 선형보간)를 그대로 이식했다. 지운 스트로크는 마스크가 아니라 스탬프
좌표 목록(`self._erase_strokes`)으로 저장해 다음 라운드(Undo)가 재생 가능한
경량 표현을 바로 쓸 수 있게 해둔다(스펙 판단 2). 존 퍼센티지 재계산(무거운
numpy 연산)은 드래그 중이 아니라 스트로크가 끝나는 시점(`erase_changed`
시그널, mouseReleaseEvent 1회)에만 트리거된다 — 드래그 중에는 지우기 마스크의
bbox 증분 갱신 + 화면 리페인트만 수행(성능 요구사항, 스펙 판단 2 "성능" 절).
"""
import math
from dataclasses import dataclass

import numpy as np
from PyQt6.QtWidgets import QMenu
from PyQt6.QtGui import QPainter, QPen, QColor, QPainterPath
from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal

from app.widgets.overlay_viewer import OverlayViewer
from app.core.zone_metrics import disk_mask

_CENTER_HIT_PX = 10.0   # 중심(이동) 판정 반경 — 화면 픽셀
_BORDER_HIT_PX = 8.0    # 테두리(반지름 조절) 판정 허용 오차 — 화면 픽셀
_MIN_CREATE_R_PX = 6.0  # 이보다 작게 드래그하고 놓으면 생성 취소

_COLOR_NORMAL = QColor(0, 230, 140)
_COLOR_SELECTED = QColor(255, 200, 0)
_COLOR_ZONE_HIGHLIGHT = QColor(255, 255, 0, 90)


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
    zone_clicked = pyqtSignal(int)          # 원이 아닌 빈 곳을 (드래그 없이) 클릭 -> 해당 존 인덱스
    blob_deleted = pyqtSignal(int)          # 블랍 삭제 모드에서 클릭으로 삭제된 블랍 라벨 id
    erase_changed = pyqtSignal()            # 브러시 지우기 스트로크가 끝났을 때 1회(R3-3)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._circles: list[_CircleItem] = []
        self._next_id = 1
        self._selected_id: int | None = None
        self._drag_mode: str | None = None   # None | "move" | "resize" | "create"
        self._img_orig_w = 0
        self._img_orig_h = 0
        self._highlighted_zone: int | None = None   # 0=중심부, 1..N-1=링, N=바깥쪽
        self._mode: str = "circle"   # "circle" | "blob_delete" | "brush_erase"
        self._blob_labels: np.ndarray | None = None   # (H, W) int32 라벨맵, 원본 이미지 좌표계
        self._blob_stats: np.ndarray | None = None     # [label] = [x, y, w, h, area]
        self._removed_blob_ids: set[int] = set()
        # ── 브러시 지우기(R3-3) ──────────────────────────────────────────────
        self._erase_strokes: list[list[tuple[float, float, float]]] = []  # 스트로크별 (cx,cy,r) 스탬프 목록
        self._erase_mask_np: np.ndarray | None = None   # 원본 해상도 bool, 파생 캐시(undo 대상 아님)
        self._erase_brush_size = 30   # 원본 이미지 픽셀 단위 지름
        self._current_stroke: list[tuple[float, float, float]] = []
        self._last_erase_pos: QPointF | None = None
        self._erasing = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)   # 클릭 후 Delete 키 삭제를 받으려면 필요

    # ── 공개 API ─────────────────────────────────────────────────────────────

    def set_image_size(self, orig_w: int, orig_h: int) -> None:
        """원본 이미지 픽셀 크기 — 원 좌표(원본 스케일) <-> 오버레이 픽스맵 좌표 변환에 사용."""
        self._img_orig_w = orig_w
        self._img_orig_h = orig_h

    def clear_circles(self) -> None:
        self._circles = []
        self._selected_id = None
        self._highlighted_zone = None
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
        self._highlighted_zone = None
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

    def selected_id(self) -> int | None:
        """현재 선택된 원 id(없으면 None) — 사이드 패널이 목록 재구축 후 선택
        하이라이트를 복원할 때 조회한다."""
        return self._selected_id

    def set_highlighted_zone(self, zone_index: int | None) -> None:
        """존 리스트 패널 클릭 등 외부에서 존 하이라이트만 갱신(원 선택과 별개)."""
        self._highlighted_zone = zone_index
        self.update()

    def highlighted_zone(self) -> int | None:
        """현재 하이라이트된 존 인덱스(없으면 None) — 사이드 패널이 존 리스트를
        재구축(퍼센티지 재계산)한 뒤 하이라이트를 복원할 때 조회한다
        (`selected_id()`와 동일한 용도, BUG-018과 같은 재구축발 리셋 방지)."""
        return self._highlighted_zone

    def remove_selected(self) -> None:
        if self._selected_id is None:
            return
        self._circles = [c for c in self._circles if c.id != self._selected_id]
        self._selected_id = None
        self._highlighted_zone = None
        self.update()
        self.circles_changed.emit()
        self.circle_selected.emit(None)

    # ── 블랍 삭제 모드 (라운드 4) ────────────────────────────────────────────

    def set_blob_delete_mode(self, enabled: bool) -> None:
        """활성화 시 좌클릭은 원 편집 대신 블랍 클릭 삭제로 해석된다."""
        self._mode = "blob_delete" if enabled else "circle"
        self.update()

    def blob_delete_mode(self) -> bool:
        return self._mode == "blob_delete"

    def set_blob_data(self, labels: np.ndarray | None, stats: np.ndarray | None) -> None:
        """타겟 클래스가 바뀔 때마다(새 추론/타겟 클래스 변경) 호출 — 라벨맵을
        교체하고 이전 삭제 이력을 초기화한다(라벨 id는 마스크가 바뀌면 더 이상
        의미가 없으므로). 브러시 지우기 스트로크/마스크(R3-3)도 동일한 이유로
        함께 초기화한다 — 이전에 지운 좌표는 새 타겟 마스크에 대해 의미가 없다."""
        self._blob_labels = labels
        self._blob_stats = stats
        self._removed_blob_ids = set()
        self._erase_strokes = []
        self._erase_mask_np = None
        self._current_stroke = []
        self._last_erase_pos = None
        self._erasing = False
        self.update()

    # ── 브러시 지우기 모드 (R3-3) ────────────────────────────────────────────

    def set_brush_erase_mode(self, enabled: bool) -> None:
        """활성화 시 좌클릭 드래그가 타겟 마스크를 픽셀 단위로 지운다
        (블랍 삭제 모드와 배타적, `self._mode` 하나로 관리)."""
        self._mode = "brush_erase" if enabled else "circle"
        self.update()

    def brush_erase_mode(self) -> bool:
        return self._mode == "brush_erase"

    def set_erase_brush_size(self, size: int) -> None:
        """`annotation_canvas.set_brush_size()`와 동일한 clamp 관례(1~200)."""
        self._erase_brush_size = max(1, min(size, 200))

    def erase_brush_size(self) -> int:
        return self._erase_brush_size

    def erase_mask(self) -> np.ndarray | None:
        """지운 영역(bool, 원본 이미지 좌표계) — `removed_blob_ids()`/
        `blob_labels()`와 동일한 "캔버스가 상태의 단일 출처" getter 패턴."""
        return self._erase_mask_np

    def _erase_mask_shape(self) -> tuple[int, int]:
        if self._blob_labels is not None:
            return self._blob_labels.shape
        return (self._img_orig_h, self._img_orig_w)

    def _erase_stamp(self, cx: float, cy: float, r: float) -> None:
        """bbox-crop 벡터화 원판 스탬프 — `annotation_canvas._paint_circle()` 이식.
        스탬프 반경만큼만 갱신되므로 이미지 전체 크기와 무관하게 저렴하다."""
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
        """이전 위치 -> 현재 위치를 반지름의 40% 간격으로 보간하며 스탬프를 찍는다
        (`annotation_canvas._paint_stroke()` 이식 — 빠른 드래그에도 끊기지 않음)."""
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
        """스트로크 좌표 목록으로부터 지우기 마스크를 처음부터 다시 그린다
        (`disk_mask()` 재사용). 이번 라운드(R3-3)엔 호출부가 없지만, 스트로크가
        이미 "재생 가능한 경량 표현"이므로 다음 라운드(Undo, R3-4)가 이 함수만
        불러 복원에 재사용할 수 있도록 미리 준비해둔다(스펙 판단 1/2)."""
        h, w = self._erase_mask_shape()
        if h <= 0 or w <= 0 or not self._erase_strokes:
            self._erase_mask_np = None
            return
        mask = np.zeros((h, w), dtype=bool)
        for stroke in self._erase_strokes:
            for cx, cy, r in stroke:
                mask |= disk_mask(cx, cy, r, (h, w))
        self._erase_mask_np = mask

    def blob_labels(self) -> np.ndarray | None:
        """현재 라벨맵(원본 이미지 좌표계) — 탭이 존 퍼센티지 재계산 시 삭제된
        라벨을 마스크에서 제외하는 데 사용."""
        return self._blob_labels

    def removed_blob_ids(self) -> set[int]:
        """지금까지 삭제된 블랍 라벨 id 집합 — `selected_id()`/`highlighted_zone()`
        와 동일한 getter 패턴(BUG-018/019 재발 방지: 캔버스가 상태의 단일 출처)."""
        return self._removed_blob_ids

    def _handle_blob_click(self, event) -> None:
        if (self._pixmap is None or event.button() != Qt.MouseButton.LeftButton
                or self._blob_labels is None):
            return
        img_pt = self._screen_to_orig(QPointF(event.position()))
        x, y = int(img_pt.x()), int(img_pt.y())
        h, w = self._blob_labels.shape
        if not (0 <= y < h and 0 <= x < w):
            return
        label = int(self._blob_labels[y, x])
        if label == 0 or label in self._removed_blob_ids:
            return
        self._removed_blob_ids.add(label)
        self.update()
        self.blob_deleted.emit(label)

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

    def _zone_index_at(self, x: float, y: float) -> int:
        """원본 이미지 좌표 (x, y)가 속한 존 인덱스. 존 개수 정의는
        `zone_metrics.zones_from_circles`와 동일한 규칙(반지름 오름차순 정렬,
        0=중심부, N=바깥쪽) — 원을 포함한 개수만 세면 되므로 마스크 배열 없이
        기하 조건만으로 계산 가능(원이 nested라는 전제는 core 모듈과 동일)."""
        n = len(self._circles)
        contained = sum(
            1 for c in self._circles if (x - c.cx) ** 2 + (y - c.cy) ** 2 <= c.r ** 2
        )
        return n - contained

    # ── paintEvent ───────────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._pixmap is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._removed_blob_ids:
            self._paint_removed_blobs(p)
        if self._erase_strokes or self._current_stroke:
            self._paint_erase_preview(p)
        if not self._circles:
            p.end()
            return
        if self._highlighted_zone is not None:
            self._paint_zone_highlight(p)
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

    def _paint_zone_highlight(self, p: QPainter) -> None:
        """존 하이라이트를 짝수-홀수 채우기 규칙의 원 경로 차집합으로 그린다 —
        zone_metrics의 마스크 차집합과 같은 원판 기하를 Qt 경로로 그대로 재사용
        (별도 비트맵/numpy 왕복 불필요, 존 경계 = 원 경계 그 자체이므로)."""
        sorted_c = sorted(self._circles, key=lambda c: c.r)
        n = len(sorted_c)
        idx = self._highlighted_zone
        if idx is None or not (0 <= idx <= n):
            return
        path = QPainterPath()
        path.setFillRule(Qt.FillRule.OddEvenFill)
        if idx == 0:
            center, r = self._orig_to_screen(sorted_c[0].cx, sorted_c[0].cy, sorted_c[0].r)
            path.addEllipse(center, r, r)
        elif idx == n:
            path.addRect(QRectF(self.rect()))
            center, r = self._orig_to_screen(sorted_c[-1].cx, sorted_c[-1].cy, sorted_c[-1].r)
            path.addEllipse(center, r, r)
        else:
            outer, inner = sorted_c[idx], sorted_c[idx - 1]
            c_o, r_o = self._orig_to_screen(outer.cx, outer.cy, outer.r)
            c_i, r_i = self._orig_to_screen(inner.cx, inner.cy, inner.r)
            path.addEllipse(c_o, r_o, r_o)
            path.addEllipse(c_i, r_i, r_i)
        p.fillPath(path, _COLOR_ZONE_HIGHLIGHT)

    def _paint_removed_blobs(self, p: QPainter) -> None:
        """삭제된 블랍을 바운딩 박스로 표시(시각 피드백).

        ponytail: 정확한 블랍 형태(픽셀 단위)가 아니라 bounding box 근사 —
        전체 해상도 마스크를 QImage로 합성하는 것보다 훨씬 단순하고, 오버레이
        픽스맵을 다시 그리지 않으므로 `set_pixmap()`이 강제하는 줌/팬 리셋도
        피한다(BUG-018/019와 같은 부류의 "조작 시 상태 리셋" 재발 방지).
        블랍 모양까지 정확히 겹쳐 보여줘야 하면 그때 QImage 합성으로 승격.
        """
        if self._blob_stats is None:
            return
        sx, sy = self._orig_scale()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 60, 60, 110))
        for label in self._removed_blob_ids:
            if not (0 <= label < len(self._blob_stats)):
                continue
            x, y, w, h = self._blob_stats[label, :4]
            rect = QRectF(
                x * sx * self._zoom + self._pan.x(),
                y * sy * self._zoom + self._pan.y(),
                w * sx * self._zoom,
                h * sy * self._zoom,
            )
            p.drawRect(rect)

    def _paint_erase_preview(self, p: QPainter) -> None:
        """지운 스트로크를 반투명 원으로 겹쳐 그린다 — `_paint_removed_blobs()`와
        같은 원칙(bbox/벡터 근사)으로, 매 프레임 원본 해상도 마스크를 QImage로
        합성하지 않고 스탬프 좌표를 그대로 화면에 투영해 그리므로 드래그 중에도
        이미지 크기와 무관하게 가볍다."""
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 60, 60, 110))
        for stroke in self._erase_strokes:
            for cx, cy, r in stroke:
                center, radius = self._orig_to_screen(cx, cy, r)
                p.drawEllipse(center, radius, radius)
        for cx, cy, r in self._current_stroke:
            center, radius = self._orig_to_screen(cx, cy, r)
            p.drawEllipse(center, radius, radius)

    # ── 마우스 ───────────────────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        if self._mode == "blob_delete":
            if event.button() == Qt.MouseButton.LeftButton:
                self._handle_blob_click(event)
            else:
                super().mousePressEvent(event)   # 좌클릭 외(중클릭 팬 등)는 기존 동작 유지
            return
        if self._mode == "brush_erase":
            if event.button() == Qt.MouseButton.LeftButton and self._pixmap is not None:
                self._current_stroke = []
                self._last_erase_pos = None
                self._erasing = True
                img_pt = self._screen_to_orig(QPointF(event.position()))
                self._erase_paint_stroke(img_pt)
                self.update()
            else:
                super().mousePressEvent(event)   # 좌클릭 외(중클릭 팬 등)는 기존 동작 유지
            return
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
        if self._mode == "blob_delete":
            super().mouseMoveEvent(event)   # 팬 드래그(중클릭)는 계속 동작해야 함
            return
        if self._mode == "brush_erase":
            if self._erasing and (event.buttons() & Qt.MouseButton.LeftButton):
                img_pt = self._screen_to_orig(QPointF(event.position()))
                self._erase_paint_stroke(img_pt)
                self.update()   # 화면 리페인트만(저렴) — 존 재계산은 release 시 1회
            else:
                super().mouseMoveEvent(event)   # 팬 드래그(중클릭)는 계속 동작해야 함
            return
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
        if self._mode == "blob_delete":
            super().mouseReleaseEvent(event)   # 팬 종료 처리(커서 복원 등)
            return
        if self._mode == "brush_erase":
            if self._erasing:
                if self._current_stroke:
                    self._erase_strokes.append(self._current_stroke)
                self._current_stroke = []
                self._last_erase_pos = None
                self._erasing = False
                self.update()
                self.erase_changed.emit()   # 존 재계산은 스트로크 종료 시 1회만(성능, 스펙 판단 2)
            else:
                super().mouseReleaseEvent(event)   # 팬 종료 처리(커서 복원 등)
            return
        if self._drag_mode == "create" and self._selected_id is not None:
            item = self._find(self._selected_id)
            if item is not None:
                _, r_screen = self._orig_to_screen(item.cx, item.cy, item.r)
                if r_screen < _MIN_CREATE_R_PX:
                    click_x, click_y = item.cx, item.cy
                    self._circles.remove(item)
                    self._selected_id = None
                    self.circle_selected.emit(None)
                    # 드래그 없는 단순 클릭이었던 것으로 간주 -- 원 생성 대신
                    # 클릭 위치가 속한 존을 선택한다(원이 하나도 없으면 존 개념이
                    # 성립하지 않으므로 발생시키지 않음).
                    if self._circles:
                        zone_idx = self._zone_index_at(click_x, click_y)
                        self.set_highlighted_zone(zone_idx)
                        self.zone_clicked.emit(zone_idx)
        self._drag_mode = None
        super().mouseReleaseEvent(event)
        self.update()
        self.circles_changed.emit()

    def keyPressEvent(self, event) -> None:
        if self._mode != "circle":
            super().keyPressEvent(event)
            return
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self._selected_id is not None:
            self.remove_selected()
        else:
            super().keyPressEvent(event)

    def contextMenuEvent(self, event) -> None:
        if self._pixmap is None or self._mode != "circle":
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
