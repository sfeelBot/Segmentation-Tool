"""BUG-065 회귀 — 새 추론 결과가 도착한 모든 이미지(화면 안/밖)는 수동 편집이
초기화되고 원 설정은 유지된다. 결과를 받지 않은 이미지·캐시 재표시는 영향 없음."""
import os
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PIL import Image
from PyQt6 import QtSvg  # noqa: F401  # Windows DLL load order before torch imports
from PyQt6.QtCore import QElapsedTimer
from PyQt6.QtWidgets import QApplication

from app.tabs.zone_analysis_tab import ZoneAnalysisTab
from app.core import zone_state_store as zstate


def _fake_result(size: int = 20):
    class_map = np.ones((size, size), dtype=np.int64)
    return type("Result", (), {
        "raw_class_map": class_map,
        "confidence_map": np.ones((size, size), dtype=np.float32),
        "class_map": class_map,
        "overlay_image": None,
    })()


def _edited_state() -> dict:
    return {
        "circles": [(0, 10.0, 10.0, 5.0, None, False)],
        "removed_blob_ids": {1},
        "removed_points": [(3, 3, 0)],
        "erase_strokes": [[(1.0, 1.0, 1.0)]],
        "manual_strokes": [(True, [(5.0, 5.0, 2.0)])],
    }


def _has_edits(state: dict | None) -> bool:
    return bool(state and (state["manual_strokes"] or state["removed_points"]
                           or state["removed_blob_ids"] or state["erase_strokes"]))


def test_new_inference_resets_edits_on_all_received_images() -> None:
    _app_ref = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as tmp:
        a, b, c = (Path(tmp) / n for n in ("a.png", "b.png", "c.png"))
        for p in (a, b, c):
            Image.new("RGB", (20, 20), (9, 9, 9)).save(p)
            zstate.save_state(p, _edited_state())

        tab = ZoneAnalysisTab()
        tab._img_list.load_files([a, b, c])
        tab._on_list_image_selected(a)
        assert tab._canvas.get_state()["manual_strokes"], "사전조건: a 편집이 캔버스에 복원"

        rev = tab._canvas.edit_revision()
        tab._infer_elapsed = QElapsedTimer()
        tab._infer_elapsed.start()
        tab._on_inference_result(b, _fake_result(), 1, 2)   # 화면 밖
        tab._on_inference_result(a, _fake_result(), 2, 2)   # 화면
        tab._on_inference_finished()

        assert tab._canvas.edit_revision() != rev, "캐시 무효화 리비전 증가"
        assert not _has_edits(tab._canvas.get_state()), "a 캔버스 편집 초기화"
        assert not tab._canvas.can_undo()
        for p in (a, b):
            st = zstate.load_state(p)
            assert not _has_edits(st), f"{p.name} 사이드카 편집 초기화"
            assert st["circles"], f"{p.name} 원 설정 유지"
        assert _has_edits(zstate.load_state(c)), "결과 안 받은 c는 편집 유지"

        # 캐시 재표시(단순 전환)는 초기화하지 않는다.
        st = tab._canvas.get_state()
        st["manual_strokes"] = [(True, [(5.0, 5.0, 2.0)])]
        tab._canvas.set_state(st)
        tab._save_timer.stop()
        tab._flush_state()
        tab._on_list_image_selected(b)
        tab._on_list_image_selected(a)
        assert tab._canvas.get_state()["manual_strokes"], "a→b→a 전환 후 편집 유지"
        tab.close()
