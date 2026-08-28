"""Zone 편집 도구와 patch/sliding-window 기본값 회귀 테스트."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PyQt6.QtWidgets import QApplication

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

