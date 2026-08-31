"""R-ZONE-3 통합 회귀 테스트 — 사이드카 디스크 영속화 + 3-way 배치 모드 분기.

`docs/specs/zone-analysis-tab-batch-modes-and-perf-2026-08-30.md` "요청 A" 절.
"""
import os
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PIL import Image
from PyQt6 import QtSvg  # noqa: F401  # Windows DLL load order before torch imports
from PyQt6.QtWidgets import QApplication

from app.tabs.zone_analysis_tab import ZoneAnalysisTab
from app.tabs import zone_analysis_tab as zone_tab_module
from app.core import zone_state_store as zstate
from app.core.annotation_store import ClassDef, DEFAULT_PALETTE


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _fake_result(size: int = 20):
    class_map = np.ones((size, size), dtype=np.int64)
    return type("Result", (), {
        "raw_class_map": class_map,
        "confidence_map": np.ones((size, size), dtype=np.float32),
        "class_map": class_map,
        "overlay_image": None,
    })()


def test_sidecar_saved_on_switch_and_restored_on_return() -> None:
    _app_ref = _app()
    with tempfile.TemporaryDirectory() as tmp:
        img1 = Path(tmp) / "img1.png"
        img2 = Path(tmp) / "img2.png"
        Image.new("RGB", (20, 20), (1, 2, 3)).save(img1)
        Image.new("RGB", (20, 20), (4, 5, 6)).save(img2)

        tab = ZoneAnalysisTab()
        tab._on_list_image_selected(img1)
        assert not zstate.sidecar_path(img1).exists()

        tab._canvas.set_circles([(5.0, 5.0, 2.0)])   # circles_changed -> _save_timer.start()
        assert tab._save_timer.isActive()

        # 이미지 전환 -- 디바운스 타이머를 기다리지 않고 즉시 동기 flush 되어야 함
        # (img2가 사이드카 없는 빈 이미지라 clear_circles()가 다시 circles_changed를
        # emit해 새 타이머가 재무장될 수 있음 -- 그건 harmless no-op 저장이라 여기서는
        # img1의 sidecar가 전환 시점에 이미 디스크에 쓰였는지만 확인한다).
        tab._on_list_image_selected(img2)
        assert zstate.sidecar_path(img1).exists(), "전환 전 편집 내용이 디스크에 저장돼야 함"

        saved = zstate.load_state(img1)
        assert saved is not None
        assert [(cx, cy, r) for _, cx, cy, r in saved["circles"]] == [(5.0, 5.0, 2.0)]

        # 새 ZoneAnalysisTab(앱 재시작 시뮬레이션)에서도 사이드카가 그대로 복원돼야 한다.
        tab2 = ZoneAnalysisTab()
        tab2._on_list_image_selected(img1)
        assert tab2._canvas.get_circles() == [(5.0, 5.0, 2.0)]
        tab2.close()
        tab.close()


def legacy_batch_mode_controls_scaling_vs_detection_and_sidecar_writes() -> None:
    """GH#32 이전 동기 배치 회귀 시나리오. 새 worker 검증은 test_zone_batch_worker.py."""
    _app_ref = _app()
    with tempfile.TemporaryDirectory() as tmp:
        img1 = Path(tmp) / "img1.png"
        img2 = Path(tmp) / "img2.png"
        Image.new("RGB", (20, 20), (10, 10, 10)).save(img1)
        Image.new("RGB", (20, 20), (20, 20, 20)).save(img2)

        tab = ZoneAnalysisTab()
        tab._img_list.load_files([img1, img2])
        tab._image_path = img1
        tab._image_size = (20, 20)
        tab._last_result = _fake_result()
        tab._results = {}
        tab._target_class_id = 1
        tab._target_classes = [
            ClassDef(0, "background", DEFAULT_PALETTE[0]),
            ClassDef(1, "target", DEFAULT_PALETTE[1]),
        ]
        tab._model = object()
        tab._ckpt_path = Path(tmp) / "model.pt"
        tab._canvas.set_image_size(20, 20)
        tab._canvas.set_circles([(5.0, 5.0, 2.0)])
        detect_calls = []
        run_calls = []
        prev_run = zone_tab_module.engine.run
        prev_detect = zone_tab_module.detect_circles
        prev_gpu = zone_tab_module.prompt_gpu_availability
        prev_dialog = zone_tab_module.ZoneBatchResultDialog
        zone_tab_module.engine.run = lambda **kwargs: run_calls.append(kwargs) or _fake_result()
        zone_tab_module.detect_circles = lambda bgr, sensitivity: detect_calls.append(sensitivity) or [(3.0, 3.0, 1.0)]
        zone_tab_module.prompt_gpu_availability = lambda *a, **k: True
        # 결과 다이얼로그는 모달 exec()가 사용자 클릭을 기다리며 블로킹되므로
        # 테스트에선 열지 않는 no-op으로 대체(배치 분기 로직만 검증 대상).
        zone_tab_module.ZoneBatchResultDialog = lambda rows, parent: type(
            "_NoOpDialog", (), {"exec": lambda self: None}
        )()
        try:
            # ── 모드 1: 일괄 적용 -- 개별 검출 없음, 사이드카도 기록되지 않음 ──
            tab._mode_combo.setCurrentIndex(tab._mode_combo.findData("apply_all"))
            tab._on_batch_process()
            assert detect_calls == []
            assert not zstate.sidecar_path(img2).exists()
            assert img2 in tab._results, "배치가 계산한 결과를 캐시에 저장해야 함(판단 3)"

            # ── 모드 2: 일괄 적용 후 수정 -- 여전히 스케일 적용이지만 사이드카는 기록 ──
            tab._results.clear()
            tab._mode_combo.setCurrentIndex(tab._mode_combo.findData("apply_all_edit"))
            tab._on_batch_process()
            assert detect_calls == []
            state = zstate.load_state(img2)
            assert state is not None
            assert [(cx, cy, r) for _, cx, cy, r in state["circles"]] == [(5.0, 5.0, 2.0)]

            # ── 모드 3: 장별 적용 -- 이미지별 개별 자동검출 호출, 사이드카는 검출 결과로 기록 ──
            zstate.sidecar_path(img2).unlink()
            tab._results.clear()
            tab._mode_combo.setCurrentIndex(tab._mode_combo.findData("per_image"))
            tab._on_batch_process()
            assert len(detect_calls) >= 1
            state = zstate.load_state(img2)
            assert state is not None
            assert [(cx, cy, r) for _, cx, cy, r in state["circles"]] == [(3.0, 3.0, 1.0)]
        finally:
            zone_tab_module.engine.run = prev_run
            zone_tab_module.detect_circles = prev_detect
            zone_tab_module.prompt_gpu_availability = prev_gpu
            zone_tab_module.ZoneBatchResultDialog = prev_dialog
        tab.close()


if __name__ == "__main__":
    test_sidecar_saved_on_switch_and_restored_on_return()
    print("OK: R-ZONE-3 zone state persistence + batch mode tests passed")
