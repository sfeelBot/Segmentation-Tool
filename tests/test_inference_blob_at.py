"""blob_at() 순수 함수 검증 — QApplication 불필요 (dummy InferenceResult만 사용)."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.inference_engine import BlobStat, InferenceResult, blob_at


def _make_result() -> InferenceResult:
    """10x10 class_map — class 1의 blob 2개(서로 떨어짐) + 배경(0)."""
    class_map = np.zeros((10, 10), dtype=np.int64)
    class_map[1:3, 1:3] = 1   # blob A (top-left) — 4px, label 순서상 먼저
    class_map[6:9, 6:9] = 1   # blob B (bottom-right) — 9px

    # cv2.connectedComponentsWithStats(connectivity=8)는 래스터 스캔 순으로
    # label 1=A, label 2=B를 부여한다 — result.blobs도 같은 순서로 채운다
    # (_compute_blobs_and_filter의 실제 산출 순서와 동일한 계약).
    blob_a = BlobStat(
        blob_id=1, class_id=1, class_name="foo", pixel_count=4,
        mean_confidence=0.9, min_confidence=0.8, max_confidence=1.0,
        centroid_x=1.5, centroid_y=1.5, bbox_x=1, bbox_y=1, bbox_w=2, bbox_h=2,
    )
    blob_b = BlobStat(
        blob_id=2, class_id=1, class_name="foo", pixel_count=9,
        mean_confidence=0.7, min_confidence=0.6, max_confidence=0.9,
        centroid_x=7.0, centroid_y=7.0, bbox_x=6, bbox_y=6, bbox_w=3, bbox_h=3,
    )
    return InferenceResult(
        class_map=class_map,
        raw_class_map=class_map,
        confidence_map=np.full((10, 10), 0.8, dtype=np.float32),
        overlay_image=None,   # blob_at은 overlay_image를 쓰지 않음
        class_stats=[],
        blobs=[blob_a, blob_b],
    )


def test_blob_at_returns_correct_blob_among_two_same_class() -> None:
    result = _make_result()
    hit_a = blob_at(result, 1, 1)
    hit_b = blob_at(result, 7, 7)
    assert hit_a is not None and hit_a.pixel_count == 4
    assert hit_b is not None and hit_b.pixel_count == 9


def test_blob_at_background_returns_none() -> None:
    result = _make_result()
    assert blob_at(result, 0, 0) is None


def test_blob_at_out_of_bounds_returns_none() -> None:
    result = _make_result()
    assert blob_at(result, -1, 0) is None
    assert blob_at(result, 0, -1) is None
    assert blob_at(result, 10, 5) is None
    assert blob_at(result, 5, 10) is None


if __name__ == "__main__":
    test_blob_at_returns_correct_blob_among_two_same_class()
    test_blob_at_background_returns_none()
    test_blob_at_out_of_bounds_returns_none()
    print("OK")
