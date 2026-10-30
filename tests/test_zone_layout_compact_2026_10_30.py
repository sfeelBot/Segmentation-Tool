"""2026-10-30 레이아웃 압축(1행 통합) + 패널 비율 + "현재 이미지만 추론" 회귀 테스트.

스펙: docs/specs/zone-analysis-tab-recipe-architecture-and-layout-2026-10-30.md
(1번: 레이아웃 1행 통합, 2번: 패널 1:2 비율 + 폭 확장, 8번: "현재 이미지만 추론")
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app.core.inference_engine import InferenceResult
from app.tabs import zone_analysis_tab as module
from app.tabs.zone_analysis_tab import ZoneAnalysisTab

_APP = QApplication.instance() or QApplication(sys.argv)


def _fake_result(size: int = 16) -> InferenceResult:
    raw = np.zeros((size, size), dtype=np.int64)
    raw[:3, :3] = 1
    return InferenceResult(
        class_map=raw.copy(), raw_class_map=raw,
        confidence_map=np.ones((size, size), dtype=np.float32),
        overlay_image=None, class_stats=[], blobs=[],
    )


# ── 1번: 레이아웃 1행 통합 — BUG-021 폭 회귀 게이트 ──────────────────────────

def test_ckpt_card_minimum_width_stays_within_1280() -> None:
    """BUG-021(2026-08-26) 재검증과 동일한 측정 방법 — 스펙 11절 명시."""
    tab = ZoneAnalysisTab()
    try:
        w = tab.minimumSizeHint().width()
        assert w <= 1280, f"BUG-021 재발: minimumSizeHint().width()={w} > 1280"
    finally:
        tab.close()


def test_ckpt_card_is_single_row_no_second_toolbar_layout() -> None:
    """체크포인트 상태/타겟클래스/AI신뢰도/픽셀threshold/편집툴바/추론버튼이
    전부 같은 ckpt_card(1행)에 들어있는지 — 버튼들의 공통 부모가 전부 동일."""
    tab = ZoneAnalysisTab()
    try:
        ckpt_card = tab._btn_ckpt.parentWidget()
        for widget in (
            tab._lbl_ckpt, tab._target_combo, tab._conf_slider,
            tab._min_px_spin, tab._edit_toolbar, tab._btn_run_current, tab._btn_run,
        ):
            assert widget.parentWidget() is ckpt_card, f"{widget} — ckpt_card 1행 밖에 있음"
    finally:
        tab.close()


# ── 2번: 패널 비율 1:2 + 폭 상한 제거 ────────────────────────────────────────

def test_zone_list_panel_has_double_stretch_of_circle_list() -> None:
    tab = ZoneAnalysisTab()
    try:
        side_layout = tab._circle_list.parentWidget().layout()
        circle_idx = side_layout.indexOf(tab._circle_list)
        zone_idx = side_layout.indexOf(tab._zone_list)
        assert side_layout.stretch(circle_idx) == 1
        assert side_layout.stretch(zone_idx) == 2
    finally:
        tab.close()


def test_left_and_side_panels_have_no_max_width_cap() -> None:
    _NO_CAP = 16777215   # QWIDGETSIZE_MAX — setMaximumWidth()를 호출하지 않으면 기본값
    tab = ZoneAnalysisTab()
    try:
        left = tab._img_list.parentWidget()
        side = tab._circle_list.parentWidget()
        assert left.maximumWidth() >= _NO_CAP
        assert side.maximumWidth() >= _NO_CAP
        assert left.minimumWidth() == 180
        assert side.minimumWidth() == 160
    finally:
        tab.close()


# ── 8번: "현재 이미지만 추론" — 다른 이미지 결과 보존(핵심 회귀) ────────────

def test_run_current_only_preserves_other_images_results(tmp_path) -> None:
    p1, p2 = tmp_path / "a.png", tmp_path / "b.png"
    for p in (p1, p2):
        Image.new("RGB", (16, 16)).save(p)

    tab = ZoneAnalysisTab()
    try:
        tab._img_list.load_files([p1, p2])
        tab._image_path = p1
        tab._image_size = (16, 16)
        tab._canvas.set_image_size(16, 16)
        tab._canvas.set_circles([(5.0, 5.0, 2.0)])
        tab._model = object()
        tab._ckpt_path = tmp_path / "model.pt"

        other_result = _fake_result()
        tab._results[p2] = other_result
        tab._target_cache[p2] = (("k",), other_result, np.zeros((1, 1)), [])
        tab._detected_ids_cache[p2] = [7]

        prev_run = module.engine.run_sliding_window
        prev_gpu = module.prompt_gpu_availability
        module.engine.run_sliding_window = lambda **kwargs: _fake_result()
        module.prompt_gpu_availability = lambda *a, **k: True
        try:
            QTest.mouseClick(tab._btn_run_current, Qt.MouseButton.LeftButton)
            worker = tab._worker
            assert worker is not None, "현재이미지만 추론 클릭이 워커를 생성하지 않음"
            assert worker.wait(5000)
            QTest.qWait(50)   # 워커 -> 메인스레드 큐드 시그널 펌핑
        finally:
            module.engine.run_sliding_window = prev_run
            module.prompt_gpu_availability = prev_gpu

        assert p1 in tab._results   # 현재 이미지는 새로 추론됨
        assert tab._results[p2] is other_result   # 핵심 회귀: 다른 이미지 결과 보존
        assert p2 in tab._target_cache
        assert p2 in tab._detected_ids_cache
    finally:
        tab.close()


def test_run_current_only_sends_single_path_to_worker(tmp_path) -> None:
    """리스트에 여러 장이 로드돼 있어도 워커엔 현재 이미지 1장만 전달돼야 한다."""
    p1, p2, p3 = (tmp_path / n for n in ("a.png", "b.png", "c.png"))
    for p in (p1, p2, p3):
        Image.new("RGB", (16, 16)).save(p)

    tab = ZoneAnalysisTab()
    try:
        tab._img_list.load_files([p1, p2, p3])
        tab._image_path = p2
        tab._image_size = (16, 16)
        tab._canvas.set_image_size(16, 16)
        tab._canvas.set_circles([(5.0, 5.0, 2.0)])
        tab._model = object()
        tab._ckpt_path = tmp_path / "model.pt"

        prev_gpu = module.prompt_gpu_availability
        module.prompt_gpu_availability = lambda *a, **k: True
        try:
            tab._on_run_current()
            assert tab._worker is not None
            assert tab._worker._paths == [p2]
        finally:
            module.prompt_gpu_availability = prev_gpu
            if tab._worker is not None:
                tab._worker.wait(5000)
    finally:
        tab.close()


if __name__ == "__main__":
    test_ckpt_card_minimum_width_stays_within_1280()
    test_ckpt_card_is_single_row_no_second_toolbar_layout()
    test_zone_list_panel_has_double_stretch_of_circle_list()
    test_left_and_side_panels_have_no_max_width_cap()
    print("OK: zone layout compact 2026-10-30 tests passed (run via pytest for full coverage)")
