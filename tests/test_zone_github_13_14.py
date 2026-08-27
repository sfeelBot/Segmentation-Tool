"""GitHub #13/#14 zone-analysis regression checks."""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image
from PyQt6 import QtSvg  # noqa: F401  # Windows DLL load order before torch imports
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app.tabs.zone_analysis_tab import ZoneAnalysisTab, _PREVIEW_MAX_DIM
from app.widgets.zone_canvas import ZoneCanvas
import app.widgets.zone_canvas as zone_canvas_module


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


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


if __name__ == "__main__":
    test_shared_center_and_diameter_undo()
    test_original_preview_and_failure_clear()
    print("OK: GitHub #13/#14 zone-analysis tests passed")
