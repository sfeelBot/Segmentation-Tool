import os
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PIL import Image
from PyQt6 import QtSvg  # noqa: F401
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app.core import zone_state_store as zstate
from app.core.annotation_store import ClassDef, DEFAULT_PALETTE
from app.tabs import zone_analysis_tab as module
from app.tabs.zone_analysis_tab import ZoneAnalysisTab, _ZoneBatchWorker

_APP = QApplication.instance() or QApplication([])


def _result(size=20):
    data = np.ones((size, size), dtype=np.int64)
    return type("Result", (), {
        "raw_class_map": data, "class_map": data,
        "confidence_map": data.astype(np.float32), "overlay_image": None,
    })()


def _classes():
    return [ClassDef(0, "background", DEFAULT_PALETTE[0]),
            ClassDef(1, "target", DEFAULT_PALETTE[1])]


def _batch_tab(circles_ref, ref_size, sensitivity, mode, target_cid):
    """BUG-030 수정 이후: 존/블랍 후처리는 `_ZoneBatchWorker`가 아니라
    `ZoneAnalysisTab._on_batch_image_inferred`(메인 스레드)가 수행한다 —
    `_on_batch_process()`가 워커 실행 직전에 채우는 `_batch_*` 컨텍스트를 그대로 흉내낸다."""
    tab = ZoneAnalysisTab()
    tab._batch_mode = mode
    tab._batch_circles_ref = circles_ref
    tab._batch_ref_size = ref_size
    tab._batch_sensitivity = sensitivity
    tab._batch_target_cid = target_cid
    tab._batch_rows = []
    tab._batch_blob_rows = []
    return tab


def test_worker_run_only_infers_and_never_touches_cv2_or_sidecars():
    """BUG-030 회귀 방지 — 워커 스레드는 CUDA 추론(engine.run)만 하고, `image_inferred`로
    raw 결과를 넘길 뿐 zone/blob(cv2) 계산이나 사이드카 저장은 절대 하지 않는다."""
    with tempfile.TemporaryDirectory() as tmp:
        paths = [Path(tmp) / f"{i}.png" for i in range(3)]
        for path in paths:
            Image.new("RGB", (20, 20)).save(path)
        calls = []
        old_prepare, old_run = module.engine.prepare_inference, module.engine.run
        module.engine.prepare_inference = lambda *args: calls.append("prepare") or object()
        module.engine.run = lambda **kwargs: calls.append(kwargs["prepared"]) or _result()
        try:
            worker = _ZoneBatchWorker(
                object(), paths, Path(tmp) / "model.pt", {}, _classes(), 0, 0,
            )
            inferred = []
            worker.image_inferred.connect(lambda p, r, d, t: inferred.append((p, r, d, t)))
            worker.run()
            assert calls[0] == "prepare" and calls.count("prepare") == 1
            assert len({id(value) for value in calls[1:]}) == 1   # prepared 객체 재사용
            assert [p for p, _, _, _ in inferred] == paths
            assert not hasattr(worker, "_results")
            for path in paths:
                assert zstate.load_state(path) is None   # 워커는 사이드카를 절대 쓰지 않음
        finally:
            module.engine.prepare_inference, module.engine.run = old_prepare, old_run


def test_main_thread_postprocessing_persists_every_mode_and_computes_rows():
    with tempfile.TemporaryDirectory() as tmp:
        paths = [Path(tmp) / f"{i}.png" for i in range(3)]
        for path in paths:
            Image.new("RGB", (20, 20)).save(path)
        tab = _batch_tab([(5.0, 5.0, 2.0)], (20, 20), .5, "apply_all", 1)
        try:
            for done, path in enumerate(paths, 1):
                tab._on_batch_image_inferred(path, _result(), done, len(paths))
            assert len(tab._batch_rows) == 6   # 3장 x (1원 -> 2존)
            for path in paths:
                assert zstate.load_state(path)["circles"]
        finally:
            tab.close()


def test_existing_edits_survive_circle_replacement_and_skip_leaves_bytes_untouched():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "image.png"
        Image.new("RGB", (20, 20)).save(path)
        zstate.save_state(path, {
            "circles": [(7, 1.0, 1.0, 1.0)], "removed_blob_ids": {3},
            "erase_strokes": [], "manual_strokes": [(True, [(2.0, 2.0, 1.0)])],
        })
        before = zstate.sidecar_path(path).read_bytes()
        tab = _batch_tab([(5.0, 5.0, 2.0)], (20, 20), .5, "apply_all", 1)
        try:
            tab._on_batch_image_inferred(path, _result(), 1, 1)
            saved = zstate.load_state(path)
            assert saved["removed_blob_ids"] == {3}
            assert saved["manual_strokes"] == [(True, [(2.0, 2.0, 1.0)])]
            assert saved["circles"][0][1:] == (5.0, 5.0, 2.0)
            assert zstate.sidecar_path(path).read_bytes() != before

            untouched = zstate.sidecar_path(path).read_bytes()
            worker = _ZoneBatchWorker(
                object(), [], Path(tmp) / "model.pt", {}, _classes(), 0, 0,
            )
            worker.run()   # 빈 target 리스트 -- 추론도 후처리도 전혀 일어나지 않아야 함
            assert zstate.sidecar_path(path).read_bytes() == untouched
        finally:
            tab.close()


def test_per_image_mode_uses_detected_circles():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "image.png"
        Image.new("RGB", (20, 20)).save(path)
        old_detect = module.detect_circles
        module.detect_circles = lambda *args, **kwargs: [(9.0, 8.0, 3.0)]
        tab = _batch_tab([(5.0, 5.0, 2.0)], (20, 20), .5, "per_image", 1)
        try:
            tab._on_batch_image_inferred(path, _result(), 1, 1)
            assert zstate.load_state(path)["circles"][0][1:] == (9.0, 8.0, 3.0)
        finally:
            module.detect_circles = old_detect
            tab.close()


def test_worker_stops_immediately_when_interruption_already_requested():
    with tempfile.TemporaryDirectory() as tmp:
        paths = [Path(tmp) / f"{i}.png" for i in range(2)]
        for p in paths:
            Image.new("RGB", (10, 10)).save(p)
        worker = _ZoneBatchWorker(
            object(), paths, Path(tmp) / "model.pt", {}, _classes(), 0, 0,
        )
        worker.requestInterruption()
        inferred = []
        worker.image_inferred.connect(lambda *a: inferred.append(a))
        old_prepare = module.engine.prepare_inference
        module.engine.prepare_inference = lambda *a: object()
        try:
            worker.run()
        finally:
            module.engine.prepare_inference = old_prepare
        assert inferred == []


def test_golden_path_button_click_reports_progress_error_and_opens_dialog():
    """실제 `_btn_batch` 클릭 -> 진짜 `QThread` 배치 -> 결과 다이얼로그까지 QTest로 확인
    (BUG-030 수정 검증 항목 3: 진행률/에러 처리/다이얼로그 오픈이 여전히 정상 동작)."""
    with tempfile.TemporaryDirectory() as tmp:
        paths = [Path(tmp) / f"img{i}.png" for i in range(3)]
        for p in paths:
            Image.new("RGB", (16, 16)).save(p)

        tab = ZoneAnalysisTab()
        old_run = module.engine.run
        old_prepare = module.engine.prepare_inference
        old_gpu = module.prompt_gpu_availability
        old_dialog = module.ZoneBatchResultDialog
        old_confirm = ZoneAnalysisTab._confirm_existing_zones
        # 캔버스에 원을 세팅하면 500ms 디바운스 자동저장 타이머가 곧 사이드카를
        # 쓸 수 있어(현재 이미지 기준) 배치 타깃에 "기존 존"으로 잡힐 수 있다 —
        # 실제 앱에서도 뜨는 그 확인 모달을 실제 클릭 없이 자동 응답하게 고정
        # (공식 크래시 재현 스크립트 `repro_batch_real_platform.py`와 동일 패턴).
        ZoneAnalysisTab._confirm_existing_zones = lambda self, count: "replace"
        dialogs = []

        class _Dlg:
            def __init__(self, rows, blob_rows, parent=None):
                dialogs.append((rows, blob_rows))

            def exec(self):
                return 0

        def fake_run(**kwargs):
            if kwargs["image_path"].name == "img1.png":
                raise RuntimeError("boom")
            return _result(16)

        module.engine.run = fake_run
        module.engine.prepare_inference = lambda *a: object()
        module.prompt_gpu_availability = lambda *a, **k: True
        module.ZoneBatchResultDialog = _Dlg
        try:
            tab._img_list.load_files(paths)
            tab._image_path = paths[0]
            tab._image_size = (16, 16)
            tab._last_result = _result(16)
            tab._results = {}
            tab._target_class_id = 1
            tab._target_classes = _classes()
            tab._model = object()
            tab._ckpt_path = Path(tmp) / "model.pt"
            tab._canvas.set_image_size(16, 16)
            tab._canvas.set_circles([(5.0, 5.0, 2.0)])
            assert tab._btn_batch.isEnabled()

            QTest.mouseClick(tab._btn_batch, Qt.MouseButton.LeftButton)
            worker = tab._batch_worker
            assert worker is not None
            assert worker.wait(10000)
            QTest.qWait(200)

            assert tab._batch_worker is None
            assert tab._batch_progress is None
            assert len(dialogs) == 1
            rows, blob_rows = dialogs[0]
            assert len(rows) == 4   # img0/img2 성공(1원 -> 2존씩) = 4행, img1은 에러라 0행
            assert tab._img_list._status[paths[1]] == ("done", "오류")
        finally:
            module.engine.run, module.engine.prepare_inference = old_run, old_prepare
            module.prompt_gpu_availability = old_gpu
            module.ZoneBatchResultDialog = old_dialog
            ZoneAnalysisTab._confirm_existing_zones = old_confirm
            tab.close()


def test_save_failure_warning_is_once_per_session():
    tab = ZoneAnalysisTab()
    tab._image_path = Path("image.png")
    outcomes = [OSError("first"), None, OSError("second")]
    warnings = []
    old_save, old_warning = module.zstate.save_state, module.QMessageBox.warning

    def save(*args):
        outcome = outcomes.pop(0)
        if outcome:
            raise outcome

    module.zstate.save_state = save
    module.QMessageBox.warning = lambda *args: warnings.append(args)
    try:
        tab._flush_state()
        tab._flush_state()
        tab._flush_state()
        assert len(warnings) == 1
    finally:
        module.zstate.save_state, module.QMessageBox.warning = old_save, old_warning
        tab.close()
