"""GitHub #12 옵션 B — 같은 클래스 어노테이션의 도구 타입 무관 병합 회귀 테스트."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PyQt6.QtCore import QPointF
from PyQt6.QtWidgets import QApplication

from app.core.annotation_store import AnnotationItem
from app.widgets.annotation_canvas import AnnotationCanvas, TOOL_BRUSH

_APP = QApplication.instance() or QApplication(sys.argv)
_CANVASES: list[AnnotationCanvas] = []


def _canvas(w: int = 32, h: int = 32) -> AnnotationCanvas:
    canvas = AnnotationCanvas()
    canvas._img_w, canvas._img_h = w, h
    canvas._class_id = 1
    canvas._annotations = []
    _CANVASES.append(canvas)
    return canvas


def _polygon(annotation_id: str, x0: int, y0: int, x1: int, y1: int,
             class_id: int = 1) -> AnnotationItem:
    return AnnotationItem(
        annotation_id=annotation_id, class_id=class_id, type="polygon",
        points=[(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
    )


def _mask(annotation_id: str, x0: int, y0: int, x1: int, y1: int,
          class_id: int = 1) -> AnnotationItem:
    mask = np.zeros((32, 32), dtype=np.uint8)
    mask[y0:y1, x0:x1] = 1
    return AnnotationItem(
        annotation_id=annotation_id, class_id=class_id, type="brush_mask",
        mask=mask, width=32, height=32,
    )


def _commit_brush(canvas: AnnotationCanvas, mask: np.ndarray) -> None:
    canvas._tool = TOOL_BRUSH
    canvas._push_undo()
    canvas._brush_np = mask
    ys, xs = np.where(mask)
    canvas._brush_bbox = [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]
    canvas._finish_brush(save=False)


def test_brush_touching_polygon_merges_and_undo_restores_polygon() -> None:
    canvas = _canvas()
    canvas._annotations = [_polygon("poly", 4, 4, 9, 9)]
    brush = np.zeros((32, 32), dtype=np.uint8)
    brush[5:8, 10:13] = 1  # polygon의 오른쪽과 4-neighbor 접촉

    _commit_brush(canvas, brush)

    assert len(canvas._annotations) == 1
    assert canvas._annotations[0].type == "brush_mask"
    assert canvas._annotations[0].mask[6, 6] == 1
    assert canvas._annotations[0].mask[6, 11] == 1

    canvas.undo()
    assert len(canvas._annotations) == 1
    assert canvas._annotations[0].type == "polygon"
    assert canvas._annotations[0].annotation_id == "poly"


def test_polygon_touching_brush_merges() -> None:
    canvas = _canvas()
    canvas._annotations = [_mask("mask", 4, 4, 10, 10)]
    canvas._poly_pts = [QPointF(10, 5), QPointF(14, 5), QPointF(14, 8), QPointF(10, 8)]

    canvas._close_polygon()

    assert len(canvas._annotations) == 1
    assert canvas._annotations[0].type == "brush_mask"
    assert canvas._annotations[0].mask[6, 5] == 1
    assert canvas._annotations[0].mask[6, 12] == 1


def test_polygon_touching_polygon_merges() -> None:
    canvas = _canvas()
    canvas._annotations = [_polygon("first", 4, 4, 9, 9)]
    canvas._poly_pts = [QPointF(10, 5), QPointF(14, 5), QPointF(14, 8), QPointF(10, 8)]

    canvas._close_polygon()

    assert len(canvas._annotations) == 1
    assert canvas._annotations[0].type == "brush_mask"


def test_diagonal_contact_and_bbox_only_overlap_do_not_merge() -> None:
    canvas = _canvas()
    canvas._annotations = [_polygon("diagonal", 4, 4, 8, 8)]
    brush = np.zeros((32, 32), dtype=np.uint8)
    brush[9:12, 9:12] = 1
    _commit_brush(canvas, brush)
    assert [a.type for a in canvas._annotations] == ["polygon", "brush_mask"]

    canvas = _canvas()
    canvas._annotations = [_polygon("concave", 4, 4, 16, 16)]
    # 폴리곤 bbox 안이지만 실제 폴리곤과 떨어진 위치를 만들기 위해 삼각형으로 교체
    canvas._annotations[0].points = [(4, 4), (16, 4), (4, 16)]
    brush = np.zeros((32, 32), dtype=np.uint8)
    brush[14:16, 14:16] = 1
    _commit_brush(canvas, brush)
    assert [a.type for a in canvas._annotations] == ["polygon", "brush_mask"]


def test_different_class_and_eraser_behavior_are_preserved() -> None:
    canvas = _canvas()
    canvas._annotations = [_polygon("other", 4, 4, 9, 9, class_id=2)]
    brush = np.zeros((32, 32), dtype=np.uint8)
    brush[5:8, 10:13] = 1
    _commit_brush(canvas, brush)
    assert canvas._annotations[0].type == "polygon"

    # 지우개 하위 호환 호출은 인접만 한 폴리곤을 변환하지 않는다.
    canvas = _canvas()
    canvas._annotations = [_polygon("poly", 4, 4, 9, 9)]
    eraser = np.zeros((32, 32), dtype=np.uint8)
    eraser[5:8, 10:13] = 1
    canvas._rasterize_polygons_touching(eraser)
    assert canvas._annotations[0].type == "polygon"


def test_merge_removes_stale_selected_annotation_id() -> None:
    canvas = _canvas()
    canvas._annotations = [_polygon("selected-poly", 4, 4, 9, 9)]
    canvas._selected_ids = {"selected-poly"}
    emitted: list[list[str]] = []
    canvas.selection_changed.connect(lambda ids: emitted.append(ids))

    brush = np.zeros((32, 32), dtype=np.uint8)
    brush[5:8, 8:12] = 1  # 기존 폴리곤과 겹쳐 기존 ID가 병합 과정에서 제거됨
    _commit_brush(canvas, brush)

    live_ids = {ann.annotation_id for ann in canvas._annotations}
    assert canvas._selected_ids <= live_ids
    assert "selected-poly" not in canvas._selected_ids
    assert emitted and emitted[-1] == []
