"""Zone 탭 스텝 인디케이터(`_compute_step_state`) 회귀 테스트 — Artifact 비주얼
조정(2026-10-02)의 유일한 신규 로직이라 self-check 1개만 둔다(ponytail)."""
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from app.tabs.zone_analysis_tab import ZoneAnalysisTab
from app.widgets.zone_step_indicator import ZoneStepIndicator


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_initial_state_is_step1_with_nothing_completed() -> None:
    _app_ref = _app()
    zone = ZoneAnalysisTab()
    current, completed = zone._compute_step_state()
    assert current == 1
    assert completed == set()
    zone.close()


def test_steps_complete_in_order_as_ckpt_image_circles_are_set() -> None:
    _app_ref = _app()
    zone = ZoneAnalysisTab()

    zone._ckpt_path = Path("fake.pt")
    current, completed = zone._compute_step_state()
    assert current == 2
    assert completed == {1}

    zone._img_list.load_files([Path("a.png"), Path("b.png")])
    current, completed = zone._compute_step_state()
    assert current == 3
    assert completed == {1, 2}

    zone._canvas.set_circles([(10.0, 10.0, 5.0)])
    current, completed = zone._compute_step_state()
    assert current == 4
    assert completed == {1, 2, 3}
    zone.close()


def test_running_worker_forces_step5() -> None:
    _app_ref = _app()
    zone = ZoneAnalysisTab()
    zone._ckpt_path = Path("fake.pt")
    zone._worker = object()   # 실제 QThread 불필요 — None 아님만 확인하는 분기
    current, completed = zone._compute_step_state()
    assert current == 5
    assert completed == {1}
    zone._worker = None
    zone.close()


def test_indicator_widget_set_state_does_not_raise() -> None:
    _app_ref = _app()
    indicator = ZoneStepIndicator()
    indicator.set_state(3, {1, 2})
    indicator.set_state(7, {1, 2, 3, 4, 5, 6, 7})
