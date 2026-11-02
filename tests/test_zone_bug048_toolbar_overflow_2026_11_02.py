"""BUG-048 회귀 테스트 — 좌측 패널을 스플리터로 넓혀도 캔버스 헤더의
undo/eye(오버레이 토글) 버튼이 QToolBar 오버플로("…") 안에 숨지 않아야 한다.

재현 조건: `QSplitter.setSizes([700, 300, 180])`처럼 좌측 패널을 극단적으로
넓히면 canvas_panel이 좁아져 `_edit_toolbar`의 undo/eye 액션이 표준 Qt
오버플로 압축으로 사라졌다(수정 전). `canvas_panel.setMinimumWidth(780)`로
스플리터가 캔버스 폭을 그 아래로 줄이지 못하게 고정해 수정했다.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtWidgets import QApplication, QSplitter

from app.tabs.zone_analysis_tab import ZoneAnalysisTab

_APP = QApplication.instance() or QApplication(sys.argv)


def _find_splitter(tab: ZoneAnalysisTab) -> QSplitter:
    splitters = tab.findChildren(QSplitter)
    assert splitters, "ZoneAnalysisTab에 QSplitter가 없음"
    return splitters[0]


def test_undo_and_eye_actions_stay_visible_when_left_panel_is_dragged_wide() -> None:
    tab = ZoneAnalysisTab()
    try:
        tab.resize(1400, 800)
        tab.show()
        _APP.processEvents()
        splitter = _find_splitter(tab)

        # 좌측 패널을 스플리터로 극단적으로 넓힘(BUG-048 재현 조건과 동일)
        splitter.setSizes([700, 300, 180])
        _APP.processEvents()

        toolbar = tab._edit_toolbar
        undo_widget = toolbar.widgetForAction(tab._act_undo)
        eye_widget = toolbar.widgetForAction(tab._act_overlay_visible)
        assert undo_widget is not None and undo_widget.isVisible(), (
            "BUG-048 재발: undo 버튼이 오버플로('…') 안에 숨음"
        )
        assert eye_widget is not None and eye_widget.isVisible(), (
            "BUG-048 재발: eye(오버레이 토글) 버튼이 오버플로('…') 안에 숨음"
        )
        # canvas_panel이 최소폭 아래로 줄어들지 않았는지도 함께 확인
        assert splitter.widget(1).width() >= 780
    finally:
        tab.close()


def test_default_splitter_sizes_still_leave_left_and_side_panels_usable() -> None:
    """기본 스플리터 비율([200, 700, 180])에서는 좌/우 패널이 각자의
    최소폭(180/160) 이상을 유지해야 한다 — canvas_panel 최소폭 추가가
    기본 레이아웃을 깨지 않는지 확인(회귀 방지)."""
    tab = ZoneAnalysisTab()
    try:
        tab.resize(1400, 800)
        tab.show()
        _APP.processEvents()
        splitter = _find_splitter(tab)
        sizes = splitter.sizes()
        assert sizes[0] >= 180
        assert sizes[2] >= 160
        assert splitter.widget(1).width() >= 780
    finally:
        tab.close()
