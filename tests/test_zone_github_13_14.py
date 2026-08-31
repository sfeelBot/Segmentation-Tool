"""GitHub #13/#14 zone-analysis regression checks."""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image
from PyQt6 import QtSvg  # noqa: F401  # Windows DLL load order before torch imports
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QColor, QImage, QPixmap
from PyQt6.QtTest import QSignalSpy, QTest
from PyQt6.QtWidgets import QApplication

from app.tabs.zone_analysis_tab import (
    ZoneAnalysisTab, _PREVIEW_MAX_DIM, _ZoneInferenceWorker, _scale_circles,
)
from app.tabs import zone_analysis_tab as zone_tab_module
from app.core.annotation_store import ClassDef
from app.core.inference_engine import _colorize_and_blend
from app.widgets.zone_canvas import ZoneCanvas
import app.widgets.zone_canvas as zone_canvas_module


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_overlay_opacity_preserves_background_brightness() -> None:
    app = _app()
    orig = Image.new("RGB", (2, 1))
    orig.putdata([(120, 100, 80), (100, 80, 60)])
    class_map = np.array([[0, 1]], dtype=np.int64)
    classes = {
        0: ClassDef(0, "background", (0, 0, 0)),
        1: ClassDef(1, "foreground", (200, 160, 120)),
    }

    image = _colorize_and_blend(orig, class_map, classes, 0.5)

    assert image.pixelColor(0, 0).getRgb()[:3] == (120, 100, 80)
    assert image.pixelColor(1, 0).getRgb()[:3] == (150, 120, 90)


def test_pixmap_refresh_preserves_zoom_and_pan() -> None:
    _app_ref = _app()
    canvas = ZoneCanvas()
    canvas.set_pixmap(QPixmap(20, 20))
    canvas._zoom = 2.5
    canvas._pan = QPointF(12.0, 34.0)

    canvas.set_pixmap(QPixmap(20, 20), preserve_view=True)

    assert canvas._zoom == 2.5
    assert canvas._pan == QPointF(12.0, 34.0)


def test_threshold_changes_are_debounced() -> None:
    app = _app()
    tab = ZoneAnalysisTab()
    pixmap = QPixmap(2, 2)
    result = type("Result", (), {
        "raw_class_map": np.ones((2, 2), dtype=np.int64),
        "confidence_map": np.ones((2, 2), dtype=np.float32),
        "class_map": np.ones((2, 2), dtype=np.int64),
        "overlay_image": pixmap.toImage(),
    })()
    tab._last_result = result
    tab._detected_ids = [1]
    tab._image_path = Path("unused.png")
    calls = []
    previous = zone_tab_module.engine.refilter
    try:
        zone_tab_module.engine.refilter = lambda *args, **kwargs: calls.append(kwargs) or result
        for value in range(1, 31):
            tab._conf_slider.setValue(value)
        assert calls == []
        QTest.qWait(180)
        app.processEvents()
    finally:
        zone_tab_module.engine.refilter = previous
    assert len(calls) == 1
    tab.close()


def test_circle_drag_commits_zone_calculation_once() -> None:
    app = _app()
    canvas = ZoneCanvas()
    canvas.resize(500, 400)
    canvas.set_image_size(400, 300)
    canvas.set_pixmap(QPixmap(400, 300))
    canvas.set_circles([(100.0, 100.0, 20.0)])
    canvas.show()
    app.processEvents()
    committed = QSignalSpy(canvas.circles_committed)
    center, _ = canvas._orig_to_screen(100.0, 100.0, 20.0)
    start = QPoint(round(center.x()), round(center.y()))
    end = QPoint(start.x() + 30, start.y() + 20)

    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    for step in range(1, 11):
        QTest.mouseMove(
            canvas,
            QPoint(start.x() + 3 * step, start.y() + 2 * step),
        )
    assert len(committed) == 0
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)

    assert len(committed) == 1
    canvas.close()


def test_shared_center_and_diameter_undo() -> None:
    app = _app()
    canvas = ZoneCanvas()
    canvas.resize(500, 400)
    pixmap = QPixmap(400, 300)
    pixmap.fill(QColor("white"))
    canvas.set_image_size(400, 300)
    canvas.set_pixmap(pixmap)
    canvas.set_circles([(100.0, 100.0, 20.0), (120.0, 80.0, 30.0)])
    canvas.show()
    app.processEvents()

    expected_center = (110.0, 90.0)
    center_screen, _ = canvas._orig_to_screen(*expected_center, 0.0)
    start = QPoint(int(center_screen.x() + 80), int(center_screen.y()))
    end = QPoint(int(center_screen.x() + 130), int(center_screen.y()))
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, end, delay=10)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    circles = canvas.get_circles()
    assert len(circles) == 3
    assert abs(circles[-1][0] - expected_center[0]) < 1e-6
    assert abs(circles[-1][1] - expected_center[1]) < 1e-6

    previous = zone_canvas_module.QInputDialog.getDouble
    first_circle_id = canvas.circles_with_ids()[0][0]
    try:
        zone_canvas_module.QInputDialog.getDouble = staticmethod(
            lambda *args, **kwargs: (80.0, True)
        )
        canvas._prompt_diameter_change(first_circle_id)
    finally:
        zone_canvas_module.QInputDialog.getDouble = previous
    assert any(abs(r - 40.0) < 1e-6 for _, _, r in canvas.get_circles())
    canvas.undo()
    assert any(abs(r - 20.0) < 1e-6 for _, _, r in canvas.get_circles())
    canvas.close()


def test_original_preview_and_failure_clear() -> None:
    app = _app()
    tab = ZoneAnalysisTab()
    with tempfile.TemporaryDirectory() as tmp:
        image_path = Path(tmp) / "large.png"
        Image.new("RGB", (3000, 1200), (12, 34, 56)).save(image_path)
        tab._on_list_image_selected(image_path)
        app.processEvents()
        assert tab._image_size == (3000, 1200)
        assert tab._canvas._pixmap is not None
        assert max(tab._canvas._pixmap.width(), tab._canvas._pixmap.height()) <= _PREVIEW_MAX_DIM
        assert not tab._btn_detect.isEnabled()

        broken_path = Path(tmp) / "broken.png"
        broken_path.write_bytes(b"not an image")
        tab._on_list_image_selected(broken_path)
        assert tab._image_size == (0, 0)
        assert tab._canvas._pixmap is None
    tab.close()


def test_f_toggles_zone_overlay() -> None:
    """GitHub #34 회귀 — InferenceResult의 실제 필드명은 overlay_image(QImage)이지
    overlay_pixmap이 아니다. 이 테스트가 예전엔 존재하지 않는 필드명으로 가짜
    객체를 만들어 통과했었고, 그래서 _show_overlay_state()의 AttributeError를
    잡아내지 못했다 — 실제 InferenceResult 계약(overlay_image: QImage)을 그대로
    흉내내고, 오버레이 표시 자체도 토글 전에 확인한다."""
    _app_ref = _app()
    tab = ZoneAnalysisTab()
    original = QPixmap(8, 8)
    overlay = QImage(8, 8, QImage.Format.Format_RGB32)
    original.fill(QColor("red"))
    overlay.fill(QColor("blue"))
    tab._original_pixmap = original
    tab._last_result = type("Result", (), {"overlay_image": overlay})()
    tab._show_overlay_state()

    assert tab._canvas._pixmap.toImage().pixelColor(0, 0) == QColor("blue")

    QTest.keyClick(tab._canvas, Qt.Key.Key_F)

    assert tab._overlay_visible is False
    assert tab._canvas._pixmap.toImage().pixelColor(0, 0) == QColor("red")
    tab.close()


def test_zone_worker_runs_all_images() -> None:
    paths = [Path("a.png"), Path("b.png")]
    calls = []
    previous = zone_tab_module.engine.run_sliding_window
    try:
        zone_tab_module.engine.run_sliding_window = lambda **kwargs: calls.append(
            kwargs["image_path"]
        ) or kwargs["image_path"]
        worker = _ZoneInferenceWorker(object(), paths, Path("model.pt"), "sliding_window")
        progress = []
        worker.result_ready.connect(
            lambda path, _result, done, total: progress.append((path, done, total))
        )
        worker.run()
    finally:
        zone_tab_module.engine.run_sliding_window = previous
    assert calls == paths
    assert progress == [(paths[0], 1, 2), (paths[1], 2, 2)]


def test_popup_and_fixed_batch_share_scaling() -> None:
    circles = [(10.0, 20.0, 5.0), (40.0, 30.0, 8.0)]
    popup_to_main = _scale_circles(circles, (100, 200), (300, 400))
    assert popup_to_main == [(30.0, 40.0, 12.5), (120.0, 60.0, 20.0)]
    fixed_batch = _scale_circles(popup_to_main, (300, 400), (600, 200))
    assert fixed_batch == [(60.0, 20.0, 15.625), (240.0, 30.0, 25.0)]
    assert _scale_circles(circles, (100, 200), (100, 200)) == circles


if __name__ == "__main__":
    test_overlay_opacity_preserves_background_brightness()
    test_shared_center_and_diameter_undo()
    test_original_preview_and_failure_clear()
    test_f_toggles_zone_overlay()
    test_zone_worker_runs_all_images()
    test_popup_and_fixed_batch_share_scaling()
    print("OK: GitHub #13/#14 zone-analysis tests passed")
