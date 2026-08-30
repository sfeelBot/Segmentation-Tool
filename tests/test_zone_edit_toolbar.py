"""Zone 편집 도구와 patch/sliding-window 기본값 회귀 테스트."""
import importlib
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PyQt6.QtWidgets import QApplication, QGroupBox

from app.tabs.inference_tab import InferenceTab
from app.tabs.zone_analysis_tab import ZoneAnalysisTab
from app.core.zone_metrics import compute_blob_labels
from app.widgets.config_form import ConfigForm
from app.widgets.zone_canvas import ZoneCanvas


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_manual_strokes_are_last_write_wins_and_undo_is_lifo() -> None:
    _app_ref = _app()
    canvas = ZoneCanvas()
    canvas.set_image_size(9, 9)
    canvas._manual_strokes = [(True, [(4.0, 4.0, 2.0)])]
    canvas._push_undo()
    canvas._manual_strokes.append((False, [(4.0, 4.0, 1.0)]))

    edited = canvas.apply_manual_strokes(np.zeros((9, 9), dtype=bool))
    assert edited[4, 2]
    assert not edited[4, 4]

    canvas.undo()
    assert canvas.apply_manual_strokes(np.zeros((9, 9), dtype=bool))[4, 4]


def test_zone_toolbar_is_exclusive_and_defaults_are_patch_based() -> None:
    _app_ref = _app()
    zone = ZoneAnalysisTab()
    inference = InferenceTab()
    training = ConfigForm()

    assert zone._tool_group.isExclusive()
    assert zone._act_circle.isChecked()
    assert zone._infer_mode.currentData() == "sliding_window"
    assert inference._infer_mode.currentData() == "sliding_window"
    assert training._sample_mode.currentData() == "random_crop"


def test_diagonally_touching_pixels_are_separate_blobs() -> None:
    mask = np.array([[1, 0], [0, 1]], dtype=np.uint8)

    labels, stats = compute_blob_labels(mask)

    assert set(labels.ravel()) == {0, 1, 2}
    assert sorted(stats[1:, 4].tolist()) == [1, 1]


def test_offline_circle_detect_test_feature_fully_removed() -> None:
    """2026-08-30: 오프라인 원 검출 테스트 기능 삭제(사용자 요청) 회귀 확인."""
    _app_ref = _app()
    zone = ZoneAnalysisTab()
    assert not hasattr(zone, "_btn_offline_test")
    assert not hasattr(zone, "_on_open_offline_test")
    assert not hasattr(zone, "_apply_circles_from_popup")
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.widgets.circle_detect_preview_dialog")
    zone.close()


def test_batch_apply_groupbox_present_and_still_gated() -> None:
    """존 일괄 적용 발견성 개선(그룹박스) — 로직(_update_batch_button_state)은 그대로."""
    _app_ref = _app()
    zone = ZoneAnalysisTab()
    assert isinstance(zone._batch_box, QGroupBox)
    assert "존 일괄 적용" in zone._batch_box.title()
    assert "존" in zone._chk_apply_all.text()
    assert not zone._btn_batch.isEnabled()   # 초기: 원 없음 + 이미지 1장 이하

    zone._img_list.load_files([Path("a.png"), Path("b.png")])
    zone._update_batch_button_state()
    assert not zone._btn_batch.isEnabled()   # 이미지는 2장이지만 원이 아직 없음

    zone._canvas.set_circles([(10.0, 10.0, 5.0)])
    zone._update_batch_button_state()
    assert zone._btn_batch.isEnabled()   # 원 1개 이상 + 이미지 2장 이상 → 활성화
    zone.close()

