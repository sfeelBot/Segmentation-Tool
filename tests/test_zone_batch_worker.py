import os
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PIL import Image
from PyQt6 import QtSvg  # noqa: F401
from PyQt6.QtWidgets import QApplication

from app.core import zone_state_store as zstate
from app.core.annotation_store import ClassDef, DEFAULT_PALETTE
from app.tabs import zone_analysis_tab as module
from app.tabs.zone_analysis_tab import ZoneAnalysisTab, _ZoneBatchWorker

_APP = QApplication.instance() or QApplication([])


def _result(size=20):
    data = np.ones((size, size), dtype=np.int64)
    return type("Result", (), {
        "raw_class_map": data, "class_map": data,
        "confidence_map": data.astype(np.float32), "overlay_image": None,
    })()


def _classes():
    return [ClassDef(0, "background", DEFAULT_PALETTE[0]),
            ClassDef(1, "target", DEFAULT_PALETTE[1])]


def test_batch_prepares_once_persists_every_mode_and_does_not_cache_results():
    with tempfile.TemporaryDirectory() as tmp:
        paths = [Path(tmp) / f"{i}.png" for i in range(3)]
        for path in paths:
            Image.new("RGB", (20, 20)).save(path)
        calls = []
        old_prepare, old_run = module.engine.prepare_inference, module.engine.run
        module.engine.prepare_inference = lambda *args: calls.append("prepare") or object()
        module.engine.run = lambda **kwargs: calls.append(kwargs["prepared"]) or _result()
        try:
            worker = _ZoneBatchWorker(
                object(), paths, Path(tmp) / "model.pt", {}, "apply_all",
                [(5.0, 5.0, 2.0)], (20, 20), .5, _classes(), 1, 0, 0,
            )
            completed = []
            worker.completed.connect(completed.append)
            worker.run()
            assert calls[0] == "prepare" and calls.count("prepare") == 1
            assert len({id(value) for value in calls[1:]}) == 1
            assert len(completed[0]) == 6
            assert not hasattr(worker, "_results")
            for path in paths:
                assert zstate.load_state(path)["circles"]
        finally:
            module.engine.prepare_inference, module.engine.run = old_prepare, old_run


def test_existing_edits_survive_circle_replacement_and_skip_leaves_bytes_untouched():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "image.png"
        Image.new("RGB", (20, 20)).save(path)
        zstate.save_state(path, {
            "circles": [(7, 1.0, 1.0, 1.0)], "removed_blob_ids": {3},
            "erase_strokes": [], "manual_strokes": [(True, [(2.0, 2.0, 1.0)])],
        })
        before = zstate.sidecar_path(path).read_bytes()
        worker = _ZoneBatchWorker(
            object(), [path], Path(tmp) / "model.pt", {path: _result()}, "apply_all",
            [(5.0, 5.0, 2.0)], (20, 20), .5, _classes(), 1, 0, 0,
        )
        worker.run()
        saved = zstate.load_state(path)
        assert saved["removed_blob_ids"] == {3}
        assert saved["manual_strokes"] == [(True, [(2.0, 2.0, 1.0)])]
        assert saved["circles"][0][1:] == (5.0, 5.0, 2.0)
        assert zstate.sidecar_path(path).read_bytes() != before

        untouched = zstate.sidecar_path(path).read_bytes()
        worker = _ZoneBatchWorker(
            object(), [], Path(tmp) / "model.pt", {}, "apply_all",
            [(9.0, 9.0, 3.0)], (20, 20), .5, _classes(), 1, 0, 0,
        )
        worker.run()
        assert zstate.sidecar_path(path).read_bytes() == untouched


def test_per_image_mode_uses_detected_circles():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "image.png"
        Image.new("RGB", (20, 20)).save(path)
        old_detect = module.detect_circles
        module.detect_circles = lambda *args, **kwargs: [(9.0, 8.0, 3.0)]
        try:
            worker = _ZoneBatchWorker(
                object(), [path], Path(tmp) / "model.pt", {path: _result()}, "per_image",
                [(5.0, 5.0, 2.0)], (20, 20), .5, _classes(), 1, 0, 0,
            )
            worker.run()
            assert zstate.load_state(path)["circles"][0][1:] == (9.0, 8.0, 3.0)
        finally:
            module.detect_circles = old_detect


def test_save_failure_warning_is_once_per_session():
    tab = ZoneAnalysisTab()
    tab._image_path = Path("image.png")
    outcomes = [OSError("first"), None, OSError("second")]
    warnings = []
    old_save, old_warning = module.zstate.save_state, module.QMessageBox.warning

    def save(*args):
        outcome = outcomes.pop(0)
        if outcome:
            raise outcome

    module.zstate.save_state = save
    module.QMessageBox.warning = lambda *args: warnings.append(args)
    try:
        tab._flush_state()
        tab._flush_state()
        tab._flush_state()
        assert len(warnings) == 1
    finally:
        module.zstate.save_state, module.QMessageBox.warning = old_save, old_warning
        tab.close()
