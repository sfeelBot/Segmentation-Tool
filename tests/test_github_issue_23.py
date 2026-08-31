from pathlib import Path

from PyQt6 import QtSvg  # noqa: F401  # Windows DLL load order
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QPointF, QThread
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtTest import QTest

from app.tabs import inference_tab
from app.core import inference_engine
from app.core.inference_engine import (
    ClassDef, InferenceResult, _colorize_and_blend,
    _compute_blobs_and_filter, reblend,
)
from app.widgets.overlay_viewer import OverlayViewer


def _blank_qimage(w: int = 1, h: int = 1) -> QImage:
    return QImage(w, h, QImage.Format.Format_RGB888)


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
        "overlay_image": _blank_qimage(8, 8), "class_stats": [], "blobs": [],
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

    image = _colorize_and_blend(original, class_map, classes, 0.5)

    assert isinstance(image, QImage)
    assert image.pixelColor(0, 0).getRgb()[:3] == (100, 150, 200)
    assert image.pixelColor(1, 0).getRgb()[:3] == (150, 100, 150)


def test_reblend_reuses_filtered_result(monkeypatch) -> None:
    import numpy as np
    from PIL import Image

    result = InferenceResult(
        class_map=np.array([[0, 1]], dtype=np.int64),
        raw_class_map=np.array([[0, 1]], dtype=np.int64),
        confidence_map=np.ones((1, 2), dtype=np.float32),
        overlay_image=_blank_qimage(2, 1), class_stats=[], blobs=[],
    )
    monkeypatch.setattr(
        "app.core.inference_engine.load_classes",
        lambda: [ClassDef(1, "foreground", (200, 50, 100))],
    )
    monkeypatch.setattr(
        "app.core.inference_engine._compute_blobs_and_filter",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("recomputed")),
    )

    image = reblend(result, Image.new("RGB", (2, 1), (100, 150, 200)), 0.5)

    assert isinstance(image, QImage)
    assert image.pixelColor(0, 0).getRgb()[:3] == (100, 150, 200)


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
        overlay_image=_blank_qimage(1, 1), class_stats=[], blobs=[],
    )
    monkeypatch.setattr(
        inference_tab.engine, "reblend",
        lambda *_args: calls.append("opacity") or _blank_qimage(1, 1),
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


def test_inference_engine_never_touches_qpixmap() -> None:
    """BUG-027 회귀 방지 — inference_engine은 QThread 워커에서도 호출되므로
    QPixmap(GUI 스레드 전용)을 절대 다뤄서는 안 된다. QImage만 다룬다."""
    assert not hasattr(inference_engine, "QPixmap")


def test_bug_027_worker_runs_off_gui_thread_and_returns_qimage(monkeypatch) -> None:
    """BUG-027 회귀 방지 — _InferenceWorker가 실제 백그라운드 QThread에서 실행되고,
    결과 오버레이가 (QPixmap이 아닌) QImage로 채워지는지 스레드 아이덴티티로 확인한다."""
    import numpy as np

    main_thread_id = int(QThread.currentThreadId())
    captured: dict = {}

    monkeypatch.setattr(inference_tab.engine, "prepare_inference",
                        lambda model, checkpoint: object())

    def fake_run(**kwargs):
        captured["thread_id"] = int(QThread.currentThreadId())
        return InferenceResult(
            class_map=np.zeros((1, 1), dtype=np.int64),
            raw_class_map=np.zeros((1, 1), dtype=np.int64),
            confidence_map=np.ones((1, 1), dtype=np.float32),
            overlay_image=_blank_qimage(),
            class_stats=[], blobs=[],
        )

    monkeypatch.setattr(inference_tab.engine, "run", fake_run)
    worker = inference_tab._InferenceWorker(
        object(), [Path("a.png")], Path("model.pt"), "resize", 64, 0.5, 0.0, 0,
    )
    results: list[InferenceResult] = []
    worker.result_ready.connect(lambda path, result, done, total: results.append(result))
    worker.start()
    assert worker.wait(5000), "워커 스레드가 시간 내에 끝나지 않음"
    QTest.qWait(50)   # result_ready는 워커→메인 스레드로 큐드 연결되므로 이벤트 루프를 돌려야 전달됨

    assert "thread_id" in captured
    assert captured["thread_id"] != main_thread_id
    assert isinstance(results[0].overlay_image, QImage)
