"""2026-10-30 "원 설정" 아키텍처 전환 회귀 테스트.

스펙: docs/specs/zone-analysis-tab-recipe-architecture-and-layout-2026-10-30.md
(3번: 원 설정 아키텍처 전환, 4번: 링/중심부 직접 클릭 네이밍)
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtTest import QTest, QSignalSpy
from PyQt6.QtWidgets import QApplication, QMenu, QMessageBox

from app.widgets.zone_canvas import ZoneCanvas
from app.widgets.zone_recipe_dialog import ZoneRecipeDialog
from app.core import zone_recipe_store as recipe_store

_APP = QApplication.instance() or QApplication(sys.argv)


def _auto_click_role(role: QMessageBox.ButtonRole):
    def _auto_exec(self):
        for btn in self.buttons():
            if self.buttonRole(btn) == role:
                btn.click()
                break
        return self.result()
    return _auto_exec


def _make_canvas(editing_enabled: bool) -> ZoneCanvas:
    canvas = ZoneCanvas()
    canvas.resize(500, 400)
    pixmap = QPixmap(400, 300)
    pixmap.fill(QColor("white"))
    canvas.set_image_size(400, 300)
    canvas.set_pixmap(pixmap)
    canvas.set_editing_enabled(editing_enabled)
    canvas.show()
    _APP.processEvents()
    return canvas


# ── 메인 캔버스 — 조회 전용(편집 비활성) ─────────────────────────────────────

def test_editing_disabled_blocks_circle_creation_by_drag() -> None:
    canvas = _make_canvas(editing_enabled=False)
    start = QPoint(100, 100)
    end = QPoint(160, 150)
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, end, delay=10)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    assert canvas.get_circles() == []
    canvas.close()


def test_editing_disabled_blocks_moving_existing_circle() -> None:
    canvas = _make_canvas(editing_enabled=False)
    canvas.set_circles([(100.0, 100.0, 20.0)])
    before = canvas.get_circles()
    center, _ = canvas._orig_to_screen(100.0, 100.0, 20.0)
    start = QPoint(round(center.x()), round(center.y()))
    end = QPoint(start.x() + 40, start.y() + 30)
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, end, delay=10)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    assert canvas.get_circles() == before   # 이동/리사이즈 전혀 안 됨
    canvas.close()


def test_editing_disabled_context_menu_never_opens() -> None:
    canvas = _make_canvas(editing_enabled=False)
    canvas.set_circles([(100.0, 100.0, 20.0)])

    def _boom(self, *_args, **_kwargs):
        raise AssertionError("편집 비활성 상태에서 우클릭 메뉴가 열리면 안 됨")
    original = QMenu.exec
    QMenu.exec = _boom
    try:
        from PyQt6.QtGui import QContextMenuEvent
        center, _ = canvas._orig_to_screen(100.0, 100.0, 20.0)
        pt = QPoint(round(center.x()), round(center.y()))
        event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, pt, canvas.mapToGlobal(pt))
        canvas.contextMenuEvent(event)   # 예외 없이 조용히 무시돼야 함
    finally:
        QMenu.exec = original
    canvas.close()


def test_editing_disabled_click_without_drag_emits_zone_and_blob_clicked() -> None:
    canvas = _make_canvas(editing_enabled=False)
    canvas.set_circles([(200.0, 150.0, 20.0), (200.0, 150.0, 60.0)])   # 중심부 + 링1
    zone_spy = QSignalSpy(canvas.zone_clicked)
    blob_spy = QSignalSpy(canvas.blob_clicked)

    center, _ = canvas._orig_to_screen(200.0, 150.0, 20.0)   # 중심부 내부 클릭
    pt = QPoint(round(center.x()), round(center.y()))
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=pt)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=pt)

    assert len(zone_spy) == 1
    assert zone_spy[0][0] == 0   # 중심부
    assert canvas.highlighted_zone() == 0
    assert len(blob_spy) == 1
    canvas.close()


def test_editing_enabled_default_true_modal_unaffected() -> None:
    """모달이 생성하는 캔버스는 기본값(True)을 그대로 유지해야 한다(역호환)."""
    canvas = ZoneCanvas()
    assert canvas.editing_enabled()


# ── "원 설정" 모달 — 현재 화면 원 우선 로드 ──────────────────────────────────

def test_recipe_dialog_prefers_initial_circles_over_most_recent(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    recipe_store.save_recipe("최근 레시피", [(1.0, 1.0, 1.0)], (10, 10))
    pixmap = QPixmap(20, 20)
    current = [(5.0, 5.0, 2.0, "내가 만든 원", False)]
    dialog = ZoneRecipeDialog(pixmap, (20, 20), initial_circles=current)
    try:
        assert dialog._canvas.get_circles() == current   # 최근 레시피가 아니라 현재 화면 원
    finally:
        dialog.close()


def test_recipe_dialog_falls_back_to_most_recent_when_no_current_circles(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    recipe_store.save_recipe("최근 레시피", [(1.0, 1.0, 1.0)], (10, 10))
    pixmap = QPixmap(20, 20)
    dialog = ZoneRecipeDialog(pixmap, (20, 20), initial_circles=[])
    try:
        assert dialog._canvas.get_circles() == [(2.0, 2.0, 2.0, None, False)]   # 폴백 성공
    finally:
        dialog.close()


def test_recipe_dialog_window_title_includes_image_name(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    pixmap = QPixmap(20, 20)
    dialog = ZoneRecipeDialog(pixmap, (20, 20), image_name="sample.png")
    try:
        assert "sample.png" in dialog.windowTitle()
    finally:
        dialog.close()


# ── 링/중심부 직접 클릭 네이밍 (스펙 4번) ────────────────────────────────────

def test_recipe_dialog_zone_click_enables_rename_and_updates_label(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    pixmap = QPixmap(400, 300)
    dialog = ZoneRecipeDialog(pixmap, (400, 300), initial_circles=[(200.0, 150.0, 60.0)])
    try:
        assert not dialog._btn_rename_zone.isEnabled()
        dialog._canvas.zone_clicked.emit(0)
        assert dialog._btn_rename_zone.isEnabled()
        assert "중심부" in dialog._lbl_selected_zone.text()

        from app.widgets import zone_canvas as zone_canvas_module
        circle_id = dialog._canvas.circles_with_ids()[0][0]
        previous = zone_canvas_module.QInputDialog.getText
        try:
            zone_canvas_module.QInputDialog.getText = staticmethod(
                lambda *args, **kwargs: ("새이름", True)
            )
            dialog._on_rename_zone_clicked()
        finally:
            zone_canvas_module.QInputDialog.getText = previous
        assert circle_id == dialog._canvas.circles_with_ids()[0][0]
        assert "새이름" in dialog._lbl_selected_zone.text()
    finally:
        dialog.close()


# ── BUG-047 회귀 — "기존 원 발견" 확인팝업 제거 ─────────────────────────────

def test_open_recipe_dialog_skips_confirm_popup_when_circles_exist(tmp_path, monkeypatch) -> None:
    """모달이 '최근 레시피'가 아니라 현재 화면 원으로 시작하도록 바뀐 이후
    (스펙 3번, 커밋 da25f5f), 구 아키텍처용 "기존 원 발견" 확인팝업은 더는
    의미가 없다 — 버튼 클릭 시 팝업 없이 곧바로 모달이 열려야 한다(BUG-047)."""
    monkeypatch.chdir(tmp_path)
    from app.tabs.zone_analysis_tab import ZoneAnalysisTab

    def _boom(*_args, **_kwargs):
        raise AssertionError("BUG-047: 확인팝업이 다시 나타나면 안 됨")
    monkeypatch.setattr(QMessageBox, "question", _boom)

    opened_with = {}
    original_init = ZoneRecipeDialog.__init__

    def _capture_init(self, *args, **kwargs):
        opened_with["initial_circles"] = kwargs.get("initial_circles")
        return original_init(self, *args, **kwargs)
    monkeypatch.setattr(ZoneRecipeDialog, "__init__", _capture_init)
    monkeypatch.setattr(ZoneRecipeDialog, "exec", lambda self: 0)

    tab = ZoneAnalysisTab()
    try:
        pixmap = QPixmap(400, 300)
        pixmap.fill(QColor("white"))
        tab._image_path = Path("dummy.png")
        tab._original_pixmap = pixmap
        tab._image_size = (400, 300)
        tab._canvas.set_image_size(400, 300)
        tab._canvas.set_circles([(200.0, 150.0, 20.0)])

        tab._on_open_recipe_dialog()   # 팝업 없이 바로 모달 생성(위 _boom 이 안 터지면 통과)

        assert opened_with["initial_circles"] == [(200.0, 150.0, 20.0, None, False)]
    finally:
        tab.close()


def test_recipe_dialog_apply_shows_save_confirm_popup(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    pixmap = QPixmap(50, 50)
    dialog = ZoneRecipeDialog(pixmap, (50, 50), initial_circles=[(25.0, 25.0, 10.0)])
    try:
        monkeypatch.setattr(QMessageBox, "exec", _auto_click_role(QMessageBox.ButtonRole.RejectRole))
        dialog._on_apply()
        assert dialog.result() == 0   # 취소 -> 모달에 머무름(accept 안 됨)

        monkeypatch.setattr(QMessageBox, "exec", _auto_click_role(QMessageBox.ButtonRole.ActionRole))
        dialog._on_apply()
        assert dialog.result_circles() == [(25.0, 25.0, 10.0, None, False)]
    finally:
        dialog.close()
