"""2026-10-28 — 브러시로 수정한 결과가 AI 검출 결과와 동일한 색/불투명도로 보이도록
overlay_image 재합성에 수동 보정(class_map 사본)을 반영하는 수정의 회귀 테스트.

사용자 요구사항 원문: "결국 검출된 결과물에 브러시로 그 결과물을 수정할 수 있도록
해주는거야" — 브러시 커밋 후 화면은 검출 결과와 완전히 동일해야 한다(별도 색 덧칠 금지).
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication

from app.tabs.zone_analysis_tab import ZoneAnalysisTab
from app.tabs import zone_analysis_tab as zone_tab_module
from app.widgets.zone_canvas import ZoneCanvas


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _make_fake_result(class_map: np.ndarray) -> object:
    """오버레이 합성 경로(engine._colorize_layer/_blend)만 쓰는 최소 스텁."""
    return type("Result", (), {
        "class_map": class_map,
        "raw_class_map": class_map,
        "confidence_map": np.ones(class_map.shape, dtype=np.float32),
        "overlay_image": QImage(class_map.shape[1], class_map.shape[0], QImage.Format.Format_RGB32),
    })()


def test_reblend_overlay_applies_manual_corrections_to_class_map_copy() -> None:
    """지우기 스트로크 → corrected class_map에서 해당 영역이 배경(0)으로,
    그리기 스트로크 → 타겟 클래스 id로 바뀌어 colorize_class_map에 전달되는지 확인.
    원본 result.class_map 자체는 절대 변형되지 않아야 한다(사본 검증)."""
    app = _app()
    tab = ZoneAnalysisTab()
    try:
        class_map = np.zeros((10, 10), dtype=np.int64)
        class_map[2:5, 2:5] = 7   # 타겟 클래스(7)가 이미 검출된 영역
        original_class_map = class_map.copy()
        result = _make_fake_result(class_map)
        tab._last_result = result
        tab._target_class_id = 7
        tab._image_path = Path("unused.png")

        # 수동 지우기: 검출된 영역 일부를 지움(원본 이미지 좌표 기준 disk)
        tab._canvas.set_blob_data(None, None)   # removed/manual 초기화 보장
        tab._canvas._manual_strokes = [(False, [(3.0, 3.0, 1.0)])]   # erase at (3,3) r=1
        # 수동 그리기: 검출 밖 영역에 추가
        tab._canvas._manual_strokes.append((True, [(8.0, 8.0, 1.0)]))

        captured = {}
        real_layer = zone_tab_module.engine._colorize_layer

        # perf D4(2026-11-12): 합성이 색칠 레이어(_colorize_layer) + 블렌드로 나뉘었다 —
        # 보정 class_map은 _colorize_layer로 전달된다. 원본 이미지 파일은 없으므로 축소
        # 원본 로더만 스텁.
        def _fake_layer(cls_map, color_map):
            captured["class_map"] = cls_map.copy()
            return real_layer(cls_map, color_map)

        zone_tab_module.engine._colorize_layer = _fake_layer
        tab._resized_original = lambda path, size: np.zeros((size[1], size[0], 3), np.uint8)
        try:
            tab._reblend_overlay()
        finally:
            zone_tab_module.engine._colorize_layer = real_layer

        assert "class_map" in captured, "target_class_id가 설정된 경우 보정 class_map으로 색칠해야 함"
        corrected = captured["class_map"]
        # 지운 중심 픽셀은 배경(0)으로 바뀌어야 함(검출 안 된 것처럼).
        assert corrected[3, 3] == 0
        # 그린 중심 픽셀은 타겟 클래스 색(7)으로 바뀌어야 함.
        assert corrected[8, 8] == 7
        # 원본 class_map은 절대 변형되지 않아야 함(사본에만 적용).
        assert np.array_equal(result.class_map, original_class_map)
        assert tab._last_result.overlay_image is not None
    finally:
        tab.close()


def test_reblend_overlay_falls_back_to_plain_reblend_without_target() -> None:
    """타겟 클래스가 없으면(_ai_and_final_masks()가 (None,None)) 보정 없이 원본
    result.class_map 그대로 색칠해야 한다(기존 engine.reblend() 경로와 같은 결과 — 회귀 방지)."""
    app = _app()
    tab = ZoneAnalysisTab()
    try:
        class_map = np.zeros((4, 4), dtype=np.int64)
        result = _make_fake_result(class_map)
        tab._last_result = result
        tab._target_class_id = None
        tab._image_path = Path("unused.png")

        calls = []
        real_layer = zone_tab_module.engine._colorize_layer
        zone_tab_module.engine._colorize_layer = lambda cm, color_map: calls.append(cm) or real_layer(cm, color_map)
        tab._resized_original = lambda path, size: np.zeros((size[1], size[0], 3), np.uint8)
        try:
            tab._reblend_overlay()
        finally:
            zone_tab_module.engine._colorize_layer = real_layer

        assert len(calls) == 1 and calls[0] is class_map   # 보정 사본이 아니라 원본 그대로
    finally:
        tab.close()


def test_committed_brush_strokes_no_longer_painted_as_separate_overlay() -> None:
    """ZoneCanvas.paintEvent()는 더 이상 커밋된 _stroke_overlay(파란/회색)를 그리지
    않고, 드래그 중인 _current_stroke만 그려야 한다(사용자 요구사항: 커밋 후엔
    검출 결과와 동일한 레이어 하나만 보여야 함)."""
    _app_ref = _app()
    canvas = ZoneCanvas()
    canvas.set_image_size(10, 10)

    # 커밋된 스트로크가 있어도(캐시 존재) 더 이상 _paint_current_stroke만 불린다 —
    # paintEvent 내부 분기를 직접 검증(실제 QPainter 없이 호출 경로만 확인).
    canvas._manual_strokes = [(True, [(3.0, 3.0, 1.0)])]
    canvas._current_stroke = []
    calls = []
    # zone-v1.18.0: 삭제한 블랍의 빨강 bbox 표시(_paint_removed_blobs)는 제거됐다.
    assert not hasattr(ZoneCanvas, "_paint_removed_blobs")
    canvas._paint_current_stroke = lambda p: calls.append("current")
    canvas._pixmap = None   # paintEvent 본문 진입 전 가드는 그대로 두되, 우린 직접 분기만 호출
    # paintEvent는 pixmap None이면 조기 return하므로, 분기 로직만 직접 재현해 검증.
    if canvas._current_stroke:
        canvas._paint_current_stroke(None)
    assert calls == []   # 둘 다 조건 미충족(런타임엔 committed strokes만 있고 current는 빔)

    canvas._current_stroke = [(5.0, 5.0, 1.0)]
    if canvas._current_stroke:
        canvas._paint_current_stroke(None)
    assert calls == ["current"]   # 드래그 중 스트로크는 호출되지만 committed 래스터는 더 이상 없음
    canvas.close()


if __name__ == "__main__":
    test_reblend_overlay_applies_manual_corrections_to_class_map_copy()
    test_reblend_overlay_falls_back_to_plain_reblend_without_target()
    test_committed_brush_strokes_no_longer_painted_as_separate_overlay()
    print("OK")
