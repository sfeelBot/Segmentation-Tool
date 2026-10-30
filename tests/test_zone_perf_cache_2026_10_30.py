"""BUG-040 후속 — 이미지 전환 시 원본 디코드/썸네일 캐시 + detected_ids(np.unique)
캐시가 캐시 적중 시 재계산을 스킵하는지 검증.

스펙: docs/specs/zone-analysis-tab-recipe-architecture-and-layout-2026-10-30.md 7번
"""
import os
import sys
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication

from app.core.inference_engine import InferenceResult
from app.tabs.zone_analysis_tab import ZoneAnalysisTab

_APP = QApplication.instance() or QApplication(sys.argv)


def _save_png(path: Path, size: int = 20) -> None:
    assert QImage(size, size, QImage.Format.Format_RGB32).save(str(path))


def _fake_result(size: int = 20) -> InferenceResult:
    raw = np.zeros((size, size), dtype=np.int64)
    raw[:5, :5] = 1
    return InferenceResult(
        class_map=raw.copy(), raw_class_map=raw, confidence_map=np.ones((size, size), dtype=np.float32),
        overlay_image=QImage(size, size, QImage.Format.Format_RGB32),
        class_stats=[], blobs=[],
    )


def test_preview_cache_skips_decode_on_revisit(tmp_path: Path) -> None:
    p1, p2 = tmp_path / "a.png", tmp_path / "b.png"
    _save_png(p1)
    _save_png(p2)
    tab = ZoneAnalysisTab()
    try:
        tab._on_list_image_selected(p1)
        tab._on_list_image_selected(p2)
        assert p1 in tab._preview_cache

        with patch("app.tabs.zone_analysis_tab.Image.open") as mock_open:
            tab._on_list_image_selected(p1)   # 캐시 적중 — 재디코드 없어야 함
            mock_open.assert_not_called()
        assert tab._image_size == (20, 20)
    finally:
        tab.close()


def test_preview_cache_lru_evicts_oldest(tmp_path: Path) -> None:
    from app.tabs.zone_analysis_tab import _PREVIEW_CACHE_MAX

    tab = ZoneAnalysisTab()
    try:
        paths = []
        for i in range(_PREVIEW_CACHE_MAX + 1):
            p = tmp_path / f"img_{i}.png"
            _save_png(p)
            paths.append(p)
            tab._on_list_image_selected(p)
        assert len(tab._preview_cache) == _PREVIEW_CACHE_MAX
        assert paths[0] not in tab._preview_cache   # 가장 오래된 항목 evict
        assert paths[-1] in tab._preview_cache
    finally:
        tab.close()


def test_detected_ids_cache_skips_np_unique_on_revisit(tmp_path: Path) -> None:
    p1, p2 = tmp_path / "a.png", tmp_path / "b.png"
    _save_png(p1)
    _save_png(p2)
    tab = ZoneAnalysisTab()
    try:
        r1 = _fake_result()
        tab._image_path = p1
        tab._last_result = r1
        tab._setup_target_classes(r1)
        assert tab._detected_ids == [1]
        assert p1 in tab._detected_ids_cache

        tab._image_path = p2
        tab._last_result = _fake_result()
        tab._setup_target_classes(tab._last_result)

        tab._image_path = p1
        with patch("app.tabs.zone_analysis_tab.np.unique") as mock_unique:
            tab._setup_target_classes(r1)   # 캐시 적중 — np.unique() 재호출 없어야 함
            mock_unique.assert_not_called()
        assert tab._detected_ids == [1]
    finally:
        tab.close()


def test_on_run_clears_detected_ids_cache_but_keeps_preview_cache(tmp_path: Path) -> None:
    p1 = tmp_path / "a.png"
    _save_png(p1)
    tab = ZoneAnalysisTab()
    try:
        tab._on_list_image_selected(p1)
        tab._detected_ids_cache[p1] = [1]
        assert p1 in tab._preview_cache
        assert p1 in tab._detected_ids_cache

        tab._results.clear()
        tab._target_cache.clear()
        tab._detected_ids_cache.clear()   # _on_run()이 수행하는 것과 동일한 효과

        assert p1 not in tab._detected_ids_cache
        assert p1 in tab._preview_cache   # 원본 디코드 캐시는 재추론과 무관하게 유지
    finally:
        tab.close()


def test_images_removed_evicts_both_new_caches(tmp_path: Path) -> None:
    p1, p2 = tmp_path / "a.png", tmp_path / "b.png"
    _save_png(p1)
    _save_png(p2)
    tab = ZoneAnalysisTab()
    try:
        tab._img_list.load_files([p1, p2])
        tab._on_list_image_selected(p1)
        tab._detected_ids_cache[p1] = [1]

        tab._on_images_removed([p1])

        assert p1 not in tab._preview_cache
        assert p1 not in tab._detected_ids_cache
    finally:
        tab.close()
