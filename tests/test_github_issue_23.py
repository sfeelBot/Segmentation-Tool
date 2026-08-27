from pathlib import Path

from PyQt6 import QtSvg  # noqa: F401  # Windows DLL load order
from PyQt6.QtWidgets import QApplication

from app.tabs import inference_tab
from app.core.inference_engine import ClassDef, _colorize_and_blend


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
