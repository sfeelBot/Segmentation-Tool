"""2026-10-01 Zone 탭 전면 재설계 — 라운드 D(append+삭제)/E(레시피+수동편집) 회귀 테스트.

스펙: docs/specs/zone-tab-redesign-2026-10-01.md
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QImage, QPixmap
from PyQt6.QtWidgets import QApplication

from app.widgets.inference_image_list import InferenceImageList
from app.widgets.zone_canvas import ZoneCanvas
from app.widgets.zone_recipe_dialog import ZoneRecipeDialog
from app.core import zone_recipe_store as recipe_store
from app.core.zone_metrics import scale_circles
from app.tabs.zone_analysis_tab import ZoneAnalysisTab

_APP = QApplication.instance() or QApplication(sys.argv)


def _save_png(path: Path) -> None:
    assert QImage(4, 4, QImage.Format.Format_RGB32).save(str(path))


# ── 라운드 D: append + 개별 삭제 ────────────────────────────────────────────

def test_load_files_append_merges_and_dedupes(tmp_path: Path) -> None:
    p1, p2, p3 = tmp_path / "a.png", tmp_path / "b.png", tmp_path / "c.png"
    for p in (p1, p2, p3):
        _save_png(p)

    lst = InferenceImageList()
    lst.load_files([p1, p2])
    assert set(lst.paths()) == {p1, p2}

    lst.load_files([p2, p3], append=True)   # p2 중복 — set 연산으로 제거
    assert set(lst.paths()) == {p1, p2, p3}

    lst.load_files([p1], append=False)   # 기본값 False는 기존처럼 전체 교체
    assert set(lst.paths()) == {p1}


def test_load_folder_append_root_mismatch_falls_back_to_flat_tree(tmp_path: Path) -> None:
    root_a = tmp_path / "root_a"
    root_b = tmp_path / "root_b"
    root_a.mkdir()
    root_b.mkdir()
    pa, pb = root_a / "a.png", root_b / "b.png"
    _save_png(pa)
    _save_png(pb)

    lst = InferenceImageList()
    lst.load_folder(root_a)
    assert lst._root == root_a

    lst.load_folder(root_b, append=True)   # 루트 불일치 -> 평탄 그룹 트리로 폴백
    assert lst._root is None
    assert set(lst.paths()) == {pa, pb}


def test_remove_selected_keeps_files_emits_signal_and_clears_status(tmp_path: Path) -> None:
    p1, p2 = tmp_path / "a.png", tmp_path / "b.png"
    _save_png(p1)
    _save_png(p2)

    lst = InferenceImageList()
    lst.load_files([p1, p2])
    lst.set_item_status(p1, "done", badge="완료")

    removed = []
    lst.images_removed.connect(lambda paths: removed.extend(paths))
    lst._tree.setCurrentItem(lst._path_to_item[p1])
    lst._remove_selected()

    assert removed == [p1]
    assert set(lst.paths()) == {p2}
    assert p1 not in lst._status
    assert p1.exists(), "목록에서 제거해도 원본 파일은 보존돼야 한다"


def test_zone_tab_images_removed_clears_results_and_current_canvas(tmp_path: Path) -> None:
    p1, p2 = tmp_path / "a.png", tmp_path / "b.png"
    _save_png(p1)
    _save_png(p2)
    tab = ZoneAnalysisTab()
    try:
        tab._img_list.load_files([p1, p2])
        tab._results[p1] = object()
        tab._results[p2] = object()
        tab._image_path = p1

        tab._on_images_removed([p1])

        assert p1 not in tab._results
        assert p2 in tab._results
        assert tab._image_path is None
    finally:
        tab.close()


# ── 라운드 E: 수동 원 편집(방향키/휠/정렬) ───────────────────────────────────

def test_align_centers_averages_without_changing_radius() -> None:
    canvas = ZoneCanvas()
    canvas.set_image_size(100, 100)
    canvas.set_circles([(0.0, 0.0, 5.0), (10.0, 20.0, 9.0)])

    canvas.align_centers()

    circles = canvas.get_circles()
    assert len(circles) == 2
    for cx, cy, r in circles:
        assert abs(cx - 5.0) < 1e-6 and abs(cy - 10.0) < 1e-6
    assert sorted(r for _, _, r in circles) == [5.0, 9.0]


def test_align_centers_noop_with_fewer_than_two_circles() -> None:
    canvas = ZoneCanvas()
    canvas.set_image_size(100, 100)
    canvas.set_circles([(1.0, 2.0, 3.0)])
    before = canvas.get_circles()

    canvas.align_centers()

    assert canvas.get_circles() == before


def test_wheel_resizes_selected_circle_and_zooms_when_none_selected() -> None:
    canvas = ZoneCanvas()
    canvas.resize(200, 200)
    canvas.set_image_size(100, 100)
    canvas.set_pixmap(QPixmap(100, 100))
    canvas.set_circles([(50.0, 50.0, 10.0)])
    circle_id = canvas.circles_with_ids()[0][0]
    canvas.select_circle(circle_id)

    from PyQt6.QtGui import QWheelEvent
    from PyQt6.QtCore import QPointF, QPoint

    event = QWheelEvent(
        QPointF(50, 50), QPointF(50, 50), QPoint(0, 0), QPoint(0, 120),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase, False,
    )
    canvas.wheelEvent(event)

    _, _, r = canvas.get_circles()[0]
    assert r > 10.0   # 휠 위로 스크롤 -> 반지름(지름) 증가
    assert canvas.can_undo()


def test_arrow_key_moves_selected_circle_with_gesture_debounced_undo() -> None:
    canvas = ZoneCanvas()
    canvas.resize(200, 200)
    canvas.set_image_size(100, 100)
    canvas.set_pixmap(QPixmap(100, 100))
    canvas.set_circles([(50.0, 50.0, 10.0)])
    circle_id = canvas.circles_with_ids()[0][0]
    canvas.select_circle(circle_id)
    undo_depth_before = len(canvas._undo_stack)

    from PyQt6.QtGui import QKeyEvent
    from PyQt6.QtCore import QEvent

    for _ in range(3):   # 연타 -> 디바운스 때문에 undo 스택엔 1개만 쌓여야 함
        ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier)
        canvas.keyPressEvent(ev)

    cx, cy, _ = canvas.get_circles()[0]
    assert cx == 53.0   # 1px * 3회
    assert len(canvas._undo_stack) == undo_depth_before + 1   # 제스처 디바운스 -> 1개만

    canvas.undo()
    cx2, _, _ = canvas.get_circles()[0]
    assert cx2 == 50.0   # 디바운스된 제스처 전체가 undo 1회로 복원


# ── 라운드 E: 레시피 저장/불러오기 + 다이얼로그 게이트 ───────────────────────

def test_recipe_store_round_trip_and_scale(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    circles = [(10.0, 10.0, 5.0), (10.0, 10.0, 8.0)]
    path = recipe_store.save_recipe("테스트 레시피", circles, (100, 100))

    recipes = recipe_store.list_recipes()
    assert recipes == [path]

    loaded = recipe_store.load_recipe(path)
    assert loaded["name"] == "테스트 레시피"
    assert loaded["circles"] == circles

    scaled = scale_circles(loaded["circles"], loaded["ref_size"], (200, 200))
    assert scaled == [(20.0, 20.0, 10.0), (20.0, 20.0, 16.0)]


def test_recipe_dialog_apply_button_gated_on_circle_count(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)   # 레시피 디렉터리를 격리(빈 상태로 시작)
    pixmap = QPixmap(50, 50)
    pixmap.fill(QColor("white"))
    dialog = ZoneRecipeDialog(pixmap, (50, 50))
    try:
        assert not dialog._btn_apply.isEnabled()   # 레시피 없음 -> 빈 캔버스로 시작

        dialog._canvas.set_circles([(25.0, 25.0, 10.0)])
        assert dialog._btn_apply.isEnabled()

        dialog._canvas.clear_circles()
        assert not dialog._btn_apply.isEnabled()

        dialog._canvas.set_circles([(25.0, 25.0, 10.0)])
        dialog._on_apply()
        assert dialog.result_circles() == [(25.0, 25.0, 10.0)]
        assert dialog.result_ref_size() == (50, 50)
    finally:
        dialog.close()


def test_recipe_dialog_autoloads_most_recent_recipe(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    recipe_store.save_recipe("최근 레시피", [(1.0, 1.0, 1.0)], (10, 10))
    pixmap = QPixmap(20, 20)
    dialog = ZoneRecipeDialog(pixmap, (20, 20))
    try:
        assert dialog._canvas.get_circles() == [(2.0, 2.0, 2.0)]   # (10,10)->(20,20) 2배 스케일
        assert dialog._btn_apply.isEnabled()
    finally:
        dialog.close()


# ── 라운드 E: 활성화 조건 분리(7-2) — 추론 전에도 자동검출 가능 ──────────────

def test_detect_button_enabled_right_after_image_load_before_inference(tmp_path: Path) -> None:
    img_path = tmp_path / "img.png"
    assert QImage(20, 20, QImage.Format.Format_RGB32).save(str(img_path))
    tab = ZoneAnalysisTab()
    try:
        assert not tab._btn_detect.isEnabled()   # 이미지 로드 전

        tab._on_list_image_selected(img_path)

        assert tab._btn_detect.isEnabled()   # 추론 없이도 바로 활성화(7-2)
        assert tab._act_circle.isEnabled()
        for action in (tab._act_brush_draw, tab._act_brush_erase, tab._act_blob_delete):
            assert not action.isEnabled()   # 블랍 기반 편집은 여전히 추론 후에만
    finally:
        tab.close()


def test_recipe_button_visibility_follows_batch_mode() -> None:
    tab = ZoneAnalysisTab()
    try:
        assert tab._mode_combo.currentData() == "apply_all"
        assert not tab._btn_recipe.isHidden()

        per_image_idx = [tab._mode_combo.itemData(i) for i in range(tab._mode_combo.count())].index("per_image")
        tab._mode_combo.setCurrentIndex(per_image_idx)
        assert tab._btn_recipe.isHidden()
    finally:
        tab.close()


if __name__ == "__main__":
    import pytest as _pytest
    raise SystemExit(_pytest.main([__file__, "-q"]))
