from pathlib import Path

from PyQt6 import QtSvg  # noqa: F401  # Windows DLL load order
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QPixmap
from PyQt6.QtTest import QTest

from app.tabs import inference_tab
from app.core.inference_engine import (
    ClassDef, InferenceResult, _colorize_and_blend,
    _compute_blobs_and_filter, reblend,
)
from app.widgets.overlay_viewer import OverlayViewer


_APP = QApplication.instance() or QApplication([])


def test_batch_worker_prepares_checkpoint_once(monkeypatch) -> None:
    paths = [Path("a.png"), Path("b.png")]
    prepared = object()
    calls: list[Path] = []

    monkeypatch.setattr(inference_tab.engine, "prepare_inference",
                        lambda model, checkpoint: prepared)

    def fake_run(**kwargs):
        assert kwargs["prepared"] is prepared
        calls.append(kwargs["image_path"])
        return kwargs["image_path"]

    monkeypatch.setattr(inference_tab.engine, "run", fake_run)
    worker = inference_tab._InferenceWorker(
        object(), paths, Path("model.pt"), "resize", 64, 0.5, 0.0, 0,
    )
    progress: list[tuple[Path, int, int]] = []
    worker.result_ready.connect(
        lambda path, _result, done, total: progress.append((path, done, total))
    )

    worker.run()

    assert calls == paths
    assert progress == [(paths[0], 1, 2), (paths[1], 2, 2)]


def test_inference_tab_f_toggles_overlay(tmp_path) -> None:
    image = tmp_path / "sample.png"
    from PIL import Image
    from PyQt6.QtCore import QEvent, Qt
    from PyQt6.QtGui import QKeyEvent, QPixmap
    Image.new("RGB", (8, 8), "red").save(image)
    tab = inference_tab.InferenceTab()
    tab._image_path = image
    result = type("Result", (), {
        "overlay_pixmap": QPixmap(8, 8), "class_stats": [], "blobs": [],
    })()
    tab._results[image] = result
    tab._show_current_image()

    tab.keyPressEvent(QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_F, Qt.KeyboardModifier.NoModifier,
    ))

    assert tab._overlay_visible is False
    tab.close()


def test_overlay_opacity_does_not_dim_background() -> None:
    import numpy as np
    from PIL import Image

    original = Image.new("RGB", (2, 1), (100, 150, 200))
    class_map = np.array([[0, 1]], dtype=np.int64)
    classes = {1: ClassDef(1, "foreground", (200, 50, 100))}

    image = _colorize_and_blend(original, class_map, classes, 0.5).toImage()

    assert image.pixelColor(0, 0).getRgb()[:3] == (100, 150, 200)
    assert image.pixelColor(1, 0).getRgb()[:3] == (150, 100, 150)


def test_reblend_reuses_filtered_result(monkeypatch) -> None:
    import numpy as np
    from PIL import Image

    result = InferenceResult(
        class_map=np.array([[0, 1]], dtype=np.int64),
        raw_class_map=np.array([[0, 1]], dtype=np.int64),
        confidence_map=np.ones((1, 2), dtype=np.float32),
        overlay_pixmap=QPixmap(2, 1), class_stats=[], blobs=[],
    )
    monkeypatch.setattr(
        "app.core.inference_engine.load_classes",
        lambda: [ClassDef(1, "foreground", (200, 50, 100))],
    )
    monkeypatch.setattr(
        "app.core.inference_engine._compute_blobs_and_filter",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("recomputed")),
    )

    pixmap = reblend(result, Image.new("RGB", (2, 1), (100, 150, 200)), 0.5)

    assert pixmap.toImage().pixelColor(0, 0).getRgb()[:3] == (100, 150, 200)


def test_blob_filter_only_copies_class_map_when_rejecting() -> None:
    import numpy as np

    raw = np.array([[0, 1], [0, 1]], dtype=np.int64)
    confidence = np.ones((2, 2), dtype=np.float32)
    classes = [ClassDef(1, "foreground", (200, 50, 100))]

    accepted, _ = _compute_blobs_and_filter(raw, confidence, classes, 0, 0)
    rejected, _ = _compute_blobs_and_filter(raw, confidence, classes, 0, 3)

    assert accepted is raw
    assert rejected is not raw
    assert np.array_equal(raw, [[0, 1], [0, 1]])
    assert not rejected.any()


def test_slider_updates_are_coalesced(monkeypatch, tmp_path) -> None:
    import numpy as np

    path = tmp_path / "sample.png"
    calls = []
    result = InferenceResult(
        class_map=np.zeros((1, 1), dtype=np.int64),
        raw_class_map=np.zeros((1, 1), dtype=np.int64),
        confidence_map=np.ones((1, 1), dtype=np.float32),
        overlay_pixmap=QPixmap(1, 1), class_stats=[], blobs=[],
    )
    monkeypatch.setattr(
        inference_tab.engine, "reblend",
        lambda *_args: calls.append("opacity") or QPixmap(1, 1),
    )
    monkeypatch.setattr(
        inference_tab.engine, "refilter",
        lambda *_args, **_kwargs: calls.append("threshold") or result,
    )
    tab = inference_tab.InferenceTab()
    tab._image_path = path
    tab._last_result = result
    tab._results[path] = result

    for value in range(5):
        tab._on_opacity_changed(value / 10)
        tab._on_threshold_changed(value)
    QTest.qWait(200)

    assert calls.count("opacity") == 1
    assert calls.count("threshold") == 1
    tab.close()


def test_pixmap_refresh_can_preserve_zoom_and_pan() -> None:
    viewer = OverlayViewer()
    viewer.resize(400, 300)
    viewer.set_pixmap(QPixmap(200, 100))
    viewer._zoom = 2.0
    viewer._pan = QPointF(23, 42)

    viewer.set_pixmap(QPixmap(200, 100), reset_view=False)

    assert viewer._zoom == 2.0
    assert viewer._pan == QPointF(23, 42)
    viewer.close()
