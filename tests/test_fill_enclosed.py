"""GitHub #15 회귀 테스트 — 브러시 채우기가 같은 클래스의 기존 어노테이션 경계도
"벽"으로 참여시키는지, 그리고 그 최적화(bbox 후보 축소 / 로컬 캔버스 / 폴백)가
기존 동작을 깨지 않는지 검증한다.

annotation_canvas.AnnotationCanvas._fill_enclosed()를 실제로 호출해 검증한다
(로직을 별도로 재구현해 비교하지 않음 — 실제 코드 경로 검증).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PyQt6.QtWidgets import QApplication

from app.core.annotation_store import AnnotationItem
from app.widgets.annotation_canvas import AnnotationCanvas, _floodfill_interior, _mask_bbox


def _make_canvas(w: int = 40, h: int = 40) -> AnnotationCanvas:
    app = QApplication.instance() or QApplication(sys.argv)
    canvas = AnnotationCanvas()
    canvas._img_w, canvas._img_h = w, h
    canvas._class_id = 1
    canvas._brush_size = 6  # radius = 3
    canvas._annotations = []
    return canvas


def test_basic_regression_no_neighbors() -> None:
    """1. 기본 회귀 — 주변에 어노테이션이 없으면 후보 0개 → 기존 폴백 경로 그대로."""
    canvas = _make_canvas()
    brush = np.zeros((40, 40), dtype=np.uint8)
    brush[5:15, 5] = 1
    brush[5:15, 14] = 1
    brush[5, 5:15] = 1
    brush[14, 5:15] = 1
    canvas._brush_np = brush.copy()
    canvas._brush_bbox = [5, 5, 15, 15]

    canvas._fill_enclosed()

    expected = _floodfill_interior(brush)
    assert np.array_equal(canvas._brush_np, expected)
    assert canvas._brush_np[10, 10] == 1


def test_same_class_neighbor_extends_fill() -> None:
    """2. 핵심 시나리오 — 같은 클래스 기존 라벨 옆에 이어 그리면 벽으로 참여해
    폐곡선 내부가 채워지고, 기존 어노테이션 픽셀은 순증분에서 제외된다."""
    canvas = _make_canvas()
    existing = np.zeros((40, 40), dtype=np.uint8)
    existing[5:15, 0:8] = 1  # 왼쪽 절반을 덮는 기존 같은 클래스 라벨
    canvas._annotations = [AnnotationItem(
        annotation_id="existing-1", class_id=1, type="brush_mask",
        mask=existing, width=40, height=40,
    )]

    brush = np.zeros((40, 40), dtype=np.uint8)
    brush[5, 8:16] = 1
    brush[14, 8:16] = 1
    brush[5:15, 15] = 1
    canvas._brush_np = brush.copy()
    canvas._brush_bbox = [5, 5, 16, 15]

    canvas._fill_enclosed()

    new_region = canvas._brush_np
    assert new_region[10, 10] == 1               # 폐곡선 내부가 채워짐
    assert not (new_region & existing).any()      # 기존 어노테이션 픽셀 흡수 안 됨
    # 후속 병합이 4방향으로 맞닿은 기존 라벨(x=7)을 후보에서 놓치지 않도록
    # 최종 마스크 bbox에는 1px margin이 유지되어야 한다.
    assert canvas._brush_bbox is not None
    assert canvas._brush_bbox[0] <= 7


def test_existing_far_pixels_preserved() -> None:
    """3. 회귀 방지 핵심 — 기존 라벨이 스트로크 bbox보다 훨씬 클 때, 로컬 캔버스
    바깥(먼 부분)의 기존 픽셀이 커밋 후보(new_region)에 전혀 포함되지 않는다."""
    canvas = _make_canvas(w=200, h=200)
    existing = np.zeros((200, 200), dtype=np.uint8)
    existing[0:200, 0:100] = 1  # 화면 대부분을 덮는 큰 기존 라벨
    far_pixel = (190, 5)
    assert existing[far_pixel] == 1
    canvas._annotations = [AnnotationItem(
        annotation_id="existing-big", class_id=1, type="brush_mask",
        mask=existing, width=200, height=200,
    )]

    brush = np.zeros((200, 200), dtype=np.uint8)
    brush[10, 100:110] = 1
    brush[20, 100:110] = 1
    brush[10:20, 109] = 1
    canvas._brush_np = brush.copy()
    canvas._brush_bbox = [100, 10, 110, 20]

    before = existing.copy()
    canvas._fill_enclosed()

    assert np.array_equal(existing, before)          # 원본 배열 자체가 안 바뀜(참조 공유 X)
    assert canvas._brush_np[far_pixel] == 0           # 먼 부분은 new_region에 없음
    assert not (canvas._brush_np & existing).any()    # 기존 몫과 겹치지 않음


def test_fallback_when_all_corners_are_walls() -> None:
    """6. 폴백 경로 — 로컬 사각형 네 모서리가 전부 벽이면 패딩 확장 재시도 후에도
    실패 시 전체-이미지 방식으로 안전 폴백한다."""
    canvas = _make_canvas(w=30, h=30)
    existing = np.ones((30, 30), dtype=np.uint8)  # 이미지 전체를 덮는 기존 라벨(극단 케이스)
    canvas._annotations = [AnnotationItem(
        annotation_id="existing-full", class_id=1, type="brush_mask",
        mask=existing, width=30, height=30,
    )]

    brush = np.zeros((30, 30), dtype=np.uint8)
    brush[10:20, 10] = 1
    canvas._brush_np = brush.copy()
    canvas._brush_bbox = [10, 10, 11, 20]

    # 크래시 없이 완료되어야 함 (전체-이미지 폴백으로 안전하게 처리)
    canvas._fill_enclosed()
    assert canvas._brush_np is not None


def test_different_class_neighbor_not_a_wall() -> None:
    """4. 다른 클래스 인접 케이스 — 벽 후보에서 제외되어 기존처럼(침범 후 양도)
    동작한다. 즉 다른 클래스 마스크는 벽으로 취급되지 않아 후보가 0개가 된다."""
    canvas = _make_canvas()
    other_class = np.zeros((40, 40), dtype=np.uint8)
    other_class[5:15, 0:8] = 1
    canvas._annotations = [AnnotationItem(
        annotation_id="other-class", class_id=2, type="brush_mask",
        mask=other_class, width=40, height=40,
    )]

    brush = np.zeros((40, 40), dtype=np.uint8)
    brush[5, 8:16] = 1
    brush[14, 8:16] = 1
    brush[5:15, 15] = 1
    canvas._brush_np = brush.copy()
    canvas._brush_bbox = [5, 5, 16, 15]

    canvas._fill_enclosed()

    # 다른 클래스는 벽이 아니므로 전체-이미지 기존 폴백 결과와 동일해야 한다
    expected = _floodfill_interior(brush)
    assert np.array_equal(canvas._brush_np, expected)


if __name__ == "__main__":
    test_basic_regression_no_neighbors()
    test_same_class_neighbor_extends_fill()
    test_existing_far_pixels_preserved()
    test_fallback_when_all_corners_are_walls()
    test_different_class_neighbor_not_a_wall()
    print("OK: GitHub #15 fill-enclosed tests passed")
