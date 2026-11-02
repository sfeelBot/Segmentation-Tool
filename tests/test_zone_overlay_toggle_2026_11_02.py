"""2026-11-02 오버레이 보기/숨기기 토글 버튼 + F 단축키 양방향 동기화 회귀 테스트.

스펙: docs/specs/zone-analysis-tab-layout-and-overlay-toggle-2026-11-02.md (4번)
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtWidgets import QApplication

from app.tabs.zone_analysis_tab import ZoneAnalysisTab

_APP = QApplication.instance() or QApplication(sys.argv)


def test_overlay_toggle_action_checked_matches_default_visible() -> None:
    tab = ZoneAnalysisTab()
    try:
        assert tab._act_overlay_visible.isChecked() == tab._overlay_visible == True
    finally:
        tab.close()


def test_f_key_via_canvas_signal_flips_button_checked_state() -> None:
    """캔버스 F키(overlay_toggle_requested) -> _toggle_overlay() 경로가 버튼
    체크 상태도 함께 뒤집는지(버튼->키보드 단방향이 아니라 양방향 동기화)."""
    tab = ZoneAnalysisTab()
    try:
        tab._canvas.overlay_toggle_requested.emit()
        assert tab._overlay_visible is False
        assert tab._act_overlay_visible.isChecked() is False
    finally:
        tab.close()


def test_button_toggle_flips_overlay_visible_state() -> None:
    """버튼 클릭(QAction.toggle()) -> _set_overlay_visible()이 실제 상태를 바꾸는지."""
    tab = ZoneAnalysisTab()
    try:
        tab._act_overlay_visible.toggle()
        assert tab._overlay_visible is False
        tab._act_overlay_visible.toggle()
        assert tab._overlay_visible is True
    finally:
        tab.close()


def test_tab_keypress_toggle_also_syncs_button() -> None:
    """탭 자신의 keyPressEvent F 경로(_toggle_overlay() 직접 호출)도 버튼과 동기화."""
    tab = ZoneAnalysisTab()
    try:
        tab._toggle_overlay()
        assert tab._overlay_visible is False
        assert tab._act_overlay_visible.isChecked() is False
    finally:
        tab.close()


if __name__ == "__main__":
    test_overlay_toggle_action_checked_matches_default_visible()
    test_f_key_via_canvas_signal_flips_button_checked_state()
    test_button_toggle_flips_overlay_visible_state()
    test_tab_keypress_toggle_also_syncs_button()
    print("OK: zone overlay toggle 2026-11-02 tests passed")
