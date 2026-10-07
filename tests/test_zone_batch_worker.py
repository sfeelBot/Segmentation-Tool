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
from app.tabs.zone_analysis_tab import (
    ZoneAnalysisTab, _ZoneBatchWorker, _ZoneBatchPostWorker, _compute_zone_rows,
)
from app.widgets.zone_batch_result_dialog import ZoneBatchResultDialog

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


def _post_worker(circles_ref, ref_size, sensitivity, mode, target_cid):
    """R-PERF-2(2026-10-07) 수정 이후: 존/블랍 cv2 후처리 + 사이드카 저장은
    `_ZoneBatchWorker`(CUDA 전용)가 아니라 `_ZoneBatchPostWorker`(cv2 전용 QThread)가
    수행한다. 기존 `_ZoneBatchWorker.run()` 단위 테스트와 같은 패턴으로 실제
    `.start()` 없이 `run()`을 직접(동기) 호출해 단위 테스트한다."""
    return _ZoneBatchPostWorker(mode, circles_ref, ref_size, sensitivity, target_cid)


def test_worker_run_only_infers_and_never_touches_cv2_or_sidecars():
    """BUG-030 회귀 방지 — 워커 스레드는 CUDA 추론(engine.run_sliding_window)만 하고,
    `image_inferred`로 raw 결과를 넘길 뿐 zone/blob(cv2) 계산이나 사이드카 저장은
    절대 하지 않는다. 2026-10-01 재설계(라운드 C) 이후 배치 경로는 항상
    run_sliding_window()를 호출한다(기존 run() 숨은 버그 수정)."""
    with tempfile.TemporaryDirectory() as tmp:
        paths = [Path(tmp) / f"{i}.png" for i in range(3)]
        for path in paths:
            Image.new("RGB", (20, 20)).save(path)
        calls = []
        old_prepare = module.engine.prepare_inference
        old_run_sw = module.engine.run_sliding_window
        module.engine.prepare_inference = lambda *args: calls.append("prepare") or object()
        module.engine.run_sliding_window = lambda **kwargs: calls.append(kwargs["prepared"]) or _result()
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
            module.engine.prepare_inference = old_prepare
            module.engine.run_sliding_window = old_run_sw


def test_post_worker_never_calls_cuda_inference():
    """R-PERF-2 BUG-030 안전성의 핵심 — `_ZoneBatchPostWorker`는 cv2/numpy 후처리와
    사이드카 저장만 하고 `engine.prepare_inference`/`engine.run_sliding_window`(CUDA
    추론)는 절대 호출하지 않는다. BUG-030 트리거는 "다른 스레드의 실 CUDA 추론 직후
    같은 스레드에서 cv2 후처리"뿐이므로, 이 워커가 CUDA를 호출하지 않으면 그 조합
    자체가 성립하지 않는다 — 두 함수를 호출 즉시 실패하도록 바꿔 증명한다."""
    def _forbidden(*_a, **_k):
        raise AssertionError("_ZoneBatchPostWorker가 CUDA 추론 함수를 호출함 — BUG-030 재발 위험")
    old_prepare, old_run = module.engine.prepare_inference, module.engine.run_sliding_window
    module.engine.prepare_inference = _forbidden
    module.engine.run_sliding_window = _forbidden
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.png"
            Image.new("RGB", (20, 20)).save(path)
            worker = _post_worker([(5.0, 5.0, 2.0)], (20, 20), .5, "apply_all", 1)
            rows_emitted = []
            worker.row_computed.connect(lambda *a: rows_emitted.append(a))
            worker.enqueue(path, _result(20), 1, 1)
            worker.close()
            worker.run()
            assert len(rows_emitted) == 1
    finally:
        module.engine.prepare_inference, module.engine.run_sliding_window = old_prepare, old_run


def test_post_worker_persists_every_mode_and_computes_rows():
    with tempfile.TemporaryDirectory() as tmp:
        paths = [Path(tmp) / f"{i}.png" for i in range(3)]
        for path in paths:
            Image.new("RGB", (20, 20)).save(path)
        worker = _post_worker([(5.0, 5.0, 2.0)], (20, 20), .5, "apply_all", 1)
        rows_total: list = []
        worker.row_computed.connect(
            lambda path, result, rows, blob_rows, done, total: rows_total.extend(rows)
        )
        for done, path in enumerate(paths, 1):
            worker.enqueue(path, _result(), done, len(paths))
        worker.close()
        worker.run()
        assert len(rows_total) == 6   # 3장 x (1원 -> 2존)
        for path in paths:
            assert zstate.load_state(path)["circles"]


def test_existing_edits_survive_circle_replacement_and_skip_leaves_bytes_untouched():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "image.png"
        Image.new("RGB", (20, 20)).save(path)
        zstate.save_state(path, {
            "circles": [(7, 1.0, 1.0, 1.0)], "removed_blob_ids": {3},
            "erase_strokes": [], "manual_strokes": [(True, [(2.0, 2.0, 1.0)])],
        })
        before = zstate.sidecar_path(path).read_bytes()
        worker = _post_worker([(5.0, 5.0, 2.0)], (20, 20), .5, "apply_all", 1)
        worker.enqueue(path, _result(), 1, 1)
        worker.close()
        worker.run()
        saved = zstate.load_state(path)
        assert saved["removed_blob_ids"] == {3}
        assert saved["manual_strokes"] == [(True, [(2.0, 2.0, 1.0)])]
        assert saved["circles"][0][1:] == (5.0, 5.0, 2.0, None)
        assert zstate.sidecar_path(path).read_bytes() != before

        untouched = zstate.sidecar_path(path).read_bytes()
        cuda_worker = _ZoneBatchWorker(
            object(), [], Path(tmp) / "model.pt", {}, _classes(), 0, 0,
        )
        cuda_worker.run()   # 빈 target 리스트 -- 추론도 후처리도 전혀 일어나지 않아야 함
        assert zstate.sidecar_path(path).read_bytes() == untouched


def test_per_image_mode_uses_detected_circles():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "image.png"
        Image.new("RGB", (20, 20)).save(path)
        old_detect = module.detect_circles
        module.detect_circles = lambda *args, **kwargs: [(9.0, 8.0, 3.0)]
        try:
            worker = _post_worker([(5.0, 5.0, 2.0)], (20, 20), .5, "per_image", 1)
            worker.enqueue(path, _result(), 1, 1)
            worker.close()
            worker.run()
            assert zstate.load_state(path)["circles"][0][1:] == (9.0, 8.0, 3.0, None)
        finally:
            module.detect_circles = old_detect


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


def test_post_worker_stops_immediately_when_interruption_already_requested():
    """`QThread.requestInterruption()`은 스레드가 실제로 `.start()`된 상태가 아니면
    아무 효과가 없다(Qt 동작) — `_ZoneBatchWorker`의 동급 테스트처럼 `run()`을 직접
    호출하면 이 플래그를 검증할 수 없으므로, 여기서는 실제로 `.start()`해 큐가
    비어 `queue.get()`에서 대기 중일 때 interruption을 건 뒤 항목을 넣어 sentinel로
    깨운다 — 그래도 처리 없이 즉시 멈추는지 확인."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "x.png"
        Image.new("RGB", (10, 10)).save(path)
        worker = _post_worker([(5.0, 5.0, 2.0)], (10, 10), .5, "apply_all", 1)
        rows = []
        worker.row_computed.connect(lambda *a: rows.append(a))
        worker.start()
        worker.requestInterruption()   # 아직 큐가 비어 있어 queue.get()에서 대기 중
        worker.enqueue(path, _result(10), 1, 1)
        worker.close()
        assert worker.wait(5000)
        assert rows == []


def test_golden_path_button_click_reports_progress_error_and_opens_dialog():
    """실제 `_btn_batch` 클릭 -> 진짜 `QThread` 배치 -> 결과 다이얼로그까지 QTest로 확인
    (BUG-030 수정 검증 항목 3: 진행률/에러 처리/다이얼로그 오픈이 여전히 정상 동작)."""
    with tempfile.TemporaryDirectory() as tmp:
        paths = [Path(tmp) / f"img{i}.png" for i in range(3)]
        for p in paths:
            Image.new("RGB", (16, 16)).save(p)

        tab = ZoneAnalysisTab()
        old_run_sw = module.engine.run_sliding_window
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

        module.engine.run_sliding_window = fake_run
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
            batch_worker = tab._batch_worker
            post_worker = tab._post_worker
            assert batch_worker is not None and post_worker is not None
            assert batch_worker.wait(10000)   # CUDA 워커 — 바로 wait() 가능
            # post_worker.close()는 batch_worker.finished의 큐드 시그널로 메인 스레드
            # 이벤트 루프를 거쳐 호출되므로, 여기서 post_worker.wait()를 바로 부르면
            # (이벤트 루프를 펌핑하지 않아) close()가 전달되지 않아 교착될 수 있다 —
            # 이벤트 루프를 펌핑하며 종료(_on_batch_finished가 None으로 비움)를 기다린다.
            for _ in range(200):
                if tab._post_worker is None:
                    break
                QTest.qWait(20)
            else:
                raise AssertionError("post_worker가 제한 시간 내에 종료되지 않음")

            assert tab._batch_worker is None
            assert tab._post_worker is None
            assert tab._batch_progress is None
            assert len(dialogs) == 1
            rows, blob_rows = dialogs[0]
            assert len(rows) == 4   # img0/img2 성공(1원 -> 2존씩) = 4행, img1은 에러라 0행
            assert tab._img_list._status[paths[1]] == ("done", "오류")
        finally:
            module.engine.run_sliding_window = old_run_sw
            module.engine.prepare_inference = old_prepare
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


# ── _compute_zone_rows (2026-10-03#8) — 순수 함수 단위 테스트 ──────────────────

def test_compute_zone_rows_returns_none_without_circles():
    assert _compute_zone_rows(Path("x.png"), _result(), 1, [], None) is None


def test_compute_zone_rows_matches_batch_path_output():
    """배치 경로(`_ZoneBatchPostWorker.run()`)와 "전체 결과 보기" 둘 다 이 순수
    함수를 공유한다 — class_map이 전부 타겟(1)이면 모든 존이 100%여야 한다."""
    path = Path("img.png")
    result = _result(size=10)
    rows, blob_rows = _compute_zone_rows(path, result, 1, [(5.0, 5.0, 2.0)], None)
    assert [name for _, name, _pct in rows] == ["중심부", "바깥쪽"]
    assert all(pct == 100.0 for _, _name, pct in rows)
    assert all(img == "img.png" for img, _name, _pct in rows)
    assert len(blob_rows) == 1   # 전체가 하나로 이어진 블랍 1개


# ── BUG-036 회귀 방지 — 전체 결과 보기 + 비활성 이미지 사이드카 circles ─────────

def test_view_all_results_with_inactive_image_sidecar_does_not_crash():
    """BUG-036: 사이드카 "circles"는 (id, cx, cy, r, name) 5-튜플(ZoneCanvas.get_state()/
    `_ZoneBatchPostWorker.run()` 둘 다 id를 맨 앞에 저장)인데, `_on_view_all_results()`가
    비활성 이미지에 대해 이를 자르지 않고 그대로 `_compute_zone_rows()`에 넘기면
    cx 자리에 id가, 존 이름 자리에 float(반지름)가 들어간다. 실제 크래시는 그 틀어진
    결과가 `ZoneBatchResultDialog` 생성 중 `_build_filter_bar()`의
    `zone_name_sort_key()`에 전달되는 시점에 TypeError로 터진다(검증 에이전트 진단,
    2장 이상 처리하는 핵심 시나리오에서 100% 재현) — 그래서 실제 다이얼로그 클래스를
    그대로 쓰되 모달 `exec()`만 no-op으로 막아 생성 경로 전체를 재현한다."""
    with tempfile.TemporaryDirectory() as tmp:
        path1 = Path(tmp) / "a.png"
        path2 = Path(tmp) / "b.png"
        Image.new("RGB", (20, 20)).save(path1)
        Image.new("RGB", (20, 20)).save(path2)

        # path2(비활성 이미지)는 실사용과 동일하게 id 포함 5-튜플 사이드카로 저장.
        zstate.save_state(path2, {
            "circles": [(1, 3.0, 3.0, 1.0, "커스텀")],
            "removed_blob_ids": set(), "erase_strokes": [], "manual_strokes": [],
        })

        created: list[ZoneBatchResultDialog] = []

        class _NoExecDialog(ZoneBatchResultDialog):
            def __init__(self, rows, blob_rows, parent=None):
                super().__init__(rows, blob_rows, parent)
                created.append(self)

            def exec(self):
                return None

        tab = ZoneAnalysisTab()
        tab._results = {path1: _result(20), path2: _result(20)}
        tab._target_class_id = 1
        tab._img_list.load_files([path1, path2])
        tab._image_path = path1   # 활성 이미지 — get_circles() 경로
        tab._image_size = (20, 20)
        tab._canvas.set_image_size(20, 20)
        tab._canvas.set_circles([(5.0, 5.0, 2.0)])

        old_dialog = module.ZoneBatchResultDialog
        module.ZoneBatchResultDialog = _NoExecDialog
        try:
            tab._on_view_all_results()   # 수정 전엔 다이얼로그 생성 중 TypeError로 크래시했음
        finally:
            module.ZoneBatchResultDialog = old_dialog
            tab.close()

        assert len(created) == 1, "결과 없음 팝업으로 빠지면 안 됨(두 이미지 다 집계돼야 함)"
        rows = created[0]._rows
        assert all(isinstance(name, str) for _, name, _pct in rows), \
            "존 이름 자리에 float(반지름)이 섞이면 안 됨(BUG-036 핵심 증상)"
        zone_names = {name for _, name, _pct in rows}
        assert zone_names == {"중심부", "바깥쪽", "커스텀"}   # path2의 커스텀 이름이 온전히 보존됨
