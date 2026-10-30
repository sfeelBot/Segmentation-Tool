import os
import tempfile
import threading
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PIL import Image
from PyQt6 import QtSvg  # noqa: F401
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app.core import zone_state_store as zstate
from app.tabs import zone_analysis_tab as module
from app.tabs.zone_analysis_tab import ZoneAnalysisTab, _ZoneCircleLayoutWorker, _compute_zone_rows

_APP = QApplication.instance() or QApplication([])


def _result(size=20):
    data = np.ones((size, size), dtype=np.int64)
    return type("Result", (), {
        "raw_class_map": data, "class_map": data,
        "confidence_map": data.astype(np.float32), "overlay_image": None,
    })()


# ── _ZoneCircleLayoutWorker (2026-10-29 배치 단순화) ────────────────────────
# 추론/모델과 완전히 무관 — CUDA를 전혀 호출하지 않으므로 BUG-030류 스레드
# 제약 자체가 성립하지 않는다(단일 워커, 2단 파이프라인 불필요).

def test_layout_worker_scales_circles():
    with tempfile.TemporaryDirectory() as tmp:
        paths = [Path(tmp) / f"{i}.png" for i in range(3)]
        for path in paths:
            Image.new("RGB", (20, 20)).save(path)
        worker = _ZoneCircleLayoutWorker(
            [(5.0, 5.0, 2.0, "inner", False)], (10, 10), paths,
        )
        events = []
        worker.progress.connect(lambda *a: events.append(a))
        worker.run()
        assert len([e for e in events if e[1] == "done"]) == 3
        for path in paths:
            state = zstate.load_state(path)
            assert state["circles"] == [(0, 10.0, 10.0, 4.0, "inner", False)]   # (10,10)->(20,20) 2배 스케일


def test_layout_worker_never_calls_inference():
    """추론/모델과 완전히 무관(요구사항 4) — 호출되면 즉시 실패하도록 바꿔 증명한다."""
    def _forbidden(*_a, **_k):
        raise AssertionError("_ZoneCircleLayoutWorker가 추론 함수를 호출함 — 요구사항 4 위반")
    old_prepare, old_run = module.engine.prepare_inference, module.engine.run_sliding_window
    module.engine.prepare_inference = _forbidden
    module.engine.run_sliding_window = _forbidden
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.png"
            Image.new("RGB", (20, 20)).save(path)
            worker = _ZoneCircleLayoutWorker([(5.0, 5.0, 2.0)], (20, 20), [path])
            worker.run()
            assert zstate.load_state(path) is not None
    finally:
        module.engine.prepare_inference, module.engine.run_sliding_window = old_prepare, old_run


def test_layout_worker_preserves_existing_edits_on_circle_replacement():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "image.png"
        Image.new("RGB", (20, 20)).save(path)
        zstate.save_state(path, {
            "circles": [(7, 1.0, 1.0, 1.0)], "removed_blob_ids": {3},
            "erase_strokes": [], "manual_strokes": [(True, [(2.0, 2.0, 1.0)])],
        })
        worker = _ZoneCircleLayoutWorker([(5.0, 5.0, 2.0)], (20, 20), [path])
        worker.run()
        saved = zstate.load_state(path)
        assert saved["removed_blob_ids"] == {3}
        assert saved["manual_strokes"] == [(True, [(2.0, 2.0, 1.0)])]
        assert saved["circles"] == [(0, 5.0, 5.0, 2.0)]


def test_layout_worker_stops_mid_batch_on_interruption():
    """`QThread.requestInterruption()`은 `.start()`로 실제 실행 중인 스레드에만
    효과가 있다(Qt 동작 — `.start()`는 호출 시점에 플래그를 초기화하므로, 시작
    전에 미리 걸어둬도 소용없다). 첫 이미지 처리 중(`Image.open`)에 동기화해
    실제로 실행 중인 상태에서 `requestInterruption()`을 걸어 확인한다."""
    with tempfile.TemporaryDirectory() as tmp:
        paths = [Path(tmp) / f"{i}.png" for i in range(3)]
        for p in paths:
            Image.new("RGB", (10, 10)).save(p)
        worker = _ZoneCircleLayoutWorker([(5.0, 5.0, 2.0)], (10, 10), paths)
        started = threading.Event()
        proceed = threading.Event()
        real_open = module.Image.open

        def slow_open(path_str):
            if Path(path_str) == paths[0]:
                started.set()
                proceed.wait(5)
            return real_open(path_str)

        module.Image.open = slow_open
        done_events = []
        worker.progress.connect(lambda *a: done_events.append(a))
        try:
            worker.start()
            assert started.wait(5), "워커가 제한 시간 내에 첫 이미지 처리를 시작하지 않음"
            worker.requestInterruption()
            proceed.set()
            assert worker.wait(5000)
            QTest.qWait(20)   # 워커 스레드 -> 메인 스레드 큐드 시그널을 펌핑해 전달
        finally:
            module.Image.open = real_open
        done_paths = {e[0] for e in done_events if e[1] == "done"}
        assert done_paths == {paths[0]}, "interruption 이후 이미지는 처리되지 않아야 함"
        assert zstate.load_state(paths[1]) is None and zstate.load_state(paths[2]) is None


def test_layout_worker_emits_error_on_unreadable_image():
    with tempfile.TemporaryDirectory() as tmp:
        good = Path(tmp) / "good.png"
        bad = Path(tmp) / "bad.png"
        Image.new("RGB", (20, 20)).save(good)
        bad.write_bytes(b"not an image")
        worker = _ZoneCircleLayoutWorker([(5.0, 5.0, 2.0)], (20, 20), [good, bad])
        events = []
        worker.progress.connect(lambda *a: events.append(a))
        worker.run()
        statuses = {path.name: status for path, status, *_rest in events if status != "processing"}
        assert statuses == {"good.png": "done", "bad.png": "error"}


# ── _on_batch_process() 골든 패스 — 모델/추론과 완전히 무관(요구사항 4) ─────

def test_golden_path_button_click_applies_circles_without_model_or_inference():
    """모델/체크포인트/추론 결과가 전혀 없어도(`_model`/`_ckpt_path`/`_last_result`
    모두 None) 배치 "영역 적용"이 동작해야 한다 — 이게 이번 라운드의 핵심 요구사항."""
    with tempfile.TemporaryDirectory() as tmp:
        paths = [Path(tmp) / f"img{i}.png" for i in range(3)]
        for p in paths:
            Image.new("RGB", (16, 16)).save(p)

        tab = ZoneAnalysisTab()
        old_confirm = ZoneAnalysisTab._confirm_existing_zones
        old_info = module.QMessageBox.information
        ZoneAnalysisTab._confirm_existing_zones = lambda self, count: "replace"
        infos = []
        module.QMessageBox.information = lambda *a: infos.append(a) or None
        try:
            tab._img_list.load_files(paths)
            tab._image_path = paths[0]
            tab._image_size = (16, 16)
            tab._canvas.set_image_size(16, 16)
            tab._canvas.set_circles([(5.0, 5.0, 2.0)])
            assert tab._model is None and tab._ckpt_path is None and tab._last_result is None
            assert tab._btn_batch.isEnabled()

            QTest.mouseClick(tab._btn_batch, Qt.MouseButton.LeftButton)
            post_worker = tab._post_worker
            assert post_worker is not None
            assert post_worker.wait(10000)
            for _ in range(200):
                if tab._post_worker is None:
                    break
                QTest.qWait(20)
            else:
                raise AssertionError("post_worker가 제한 시간 내에 종료되지 않음")

            assert tab._post_worker is None
            assert tab._batch_progress is None
            for p in paths[1:]:
                assert zstate.load_state(p)["circles"][0][1:4] == (5.0, 5.0, 2.0)
            assert len(infos) == 1   # 단순 확인 메시지 1회(퍼센티지 다이얼로그 없음)
        finally:
            ZoneAnalysisTab._confirm_existing_zones = old_confirm
            module.QMessageBox.information = old_info
            tab.close()


def test_cancel_resets_lingering_processing_icons_to_pending():
    """BUG-038: 취소 시 아직 "processing"으로 남은 대상들은 결과에서 빠지는 것과
    별개로, 목록 아이콘이 다음 배치 전까지 영구히 "처리 중"으로 남으면 안 된다 —
    `_on_batch_finished()`가 미완료 대상을 모두 "pending"으로 되돌려야 한다."""
    with tempfile.TemporaryDirectory() as tmp:
        paths = [Path(tmp) / f"img{i}.png" for i in range(3)]
        for p in paths:
            Image.new("RGB", (8, 8)).save(p)
        tab = ZoneAnalysisTab()
        old_info = module.QMessageBox.information
        infos = []
        module.QMessageBox.information = lambda *a: infos.append(a) or None
        try:
            tab._img_list.load_files(paths)
            tab._batch_targets = paths
            tab._batch_completed = {paths[0]}   # img0만 완료, img1/img2는 취소 시점에 미완료
            tab._batch_errors = set()
            tab._img_list.set_item_status(paths[0], "done", badge="적용됨")
            tab._img_list.set_item_status(paths[1], "processing")
            tab._img_list.set_item_status(paths[2], "processing")
            tab._on_batch_finished()

            assert tab._img_list._status[paths[0]] == ("done", "적용됨")
            assert tab._img_list._status[paths[1]] == ("pending", None)
            assert tab._img_list._status[paths[2]] == ("pending", None)
            assert tab._batch_targets == [] and tab._batch_completed == set()
            assert len(infos) == 1
        finally:
            module.QMessageBox.information = old_info
            tab.close()


def test_batch_finished_message_excludes_error_count_from_success():
    tab = ZoneAnalysisTab()
    old_info = module.QMessageBox.information
    infos = []
    module.QMessageBox.information = lambda *a: infos.append(a) or None
    try:
        p1, p2 = Path("a.png"), Path("b.png")
        tab._img_list.load_files([p1, p2])
        tab._batch_targets = [p1, p2]
        tab._batch_completed = {p1, p2}
        tab._batch_errors = {p2}   # p2는 오류로 완료됨(성공 아님)
        tab._img_list.set_item_status(p1, "done", badge="적용됨")
        tab._img_list.set_item_status(p2, "done", badge="오류")
        tab._on_batch_finished()
        assert len(infos) == 1
        message = infos[0][2]   # QMessageBox.information(self, title, message)
        assert "1" in message, "완료 2건 - 오류 1건 = 성공 1건이 메시지에 반영돼야 함"
    finally:
        module.QMessageBox.information = old_info
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
    """배치 경로(`_ZoneCircleLayoutWorker`가 저장한 circles)와 "전체 결과 보기"
    둘 다 이 순수 함수를 공유한다 — class_map이 전부 타겟(1)이면 모든 존이 100%여야 한다.
    2026-10-30: "바깥쪽" 존 제거로 원 1개 -> 존 1개(중심부만)."""
    path = Path("img.png")
    result = _result(size=10)
    rows, blob_rows = _compute_zone_rows(path, result, 1, [(5.0, 5.0, 2.0)], None)
    assert [name for _, name, _pct in rows] == ["중심부"]
    assert all(pct == 100.0 for _, _name, pct in rows)
    assert all(img == "img.png" for img, _name, _pct in rows)
    assert len(blob_rows) == 1   # 전체가 하나로 이어진 블랍 1개


def test_compute_zone_rows_drops_hidden():
    """2026-10-30: outer_name 매개변수 제거 — 숨긴 존(hidden=True)만 걸러지는지
    원 2개(중심부 숨김/링 1 비숨김)로 확인한다."""
    path = Path("img.png")
    result = _result(size=10)
    rows, _blob_rows = _compute_zone_rows(
        path, result, 1,
        [(5.0, 5.0, 1.0, "inner", True), (5.0, 5.0, 2.0, "outer", False)], None,
    )
    assert [name for _, name, _pct in rows] == ["outer"]   # 숨긴 중심부(inner)는 제외


# ── BUG-036 회귀 방지 — 전체 결과 보기 + 비활성 이미지 사이드카 circles ─────────

def test_view_all_results_with_inactive_image_sidecar_does_not_crash():
    """BUG-036: 사이드카 "circles"는 (id, cx, cy, r, name, hidden) 6-튜플
    (ZoneCanvas.get_state()/`_ZoneCircleLayoutWorker.run()` 둘 다 id를 맨 앞에
    저장)인데, `_on_view_all_results()`가 비활성 이미지에 대해 이를 자르지 않고
    그대로 `_compute_zone_rows()`에 넘기면 cx 자리에 id가, 존 이름 자리에
    float(반지름)가 들어간다. 실제 크래시는 그 틀어진 결과가 `ZoneBatchResultDialog`
    생성 중 `_build_filter_bar()`의 `zone_name_sort_key()`에 전달되는 시점에
    TypeError로 터진다(검증 에이전트 진단) — 그래서 실제 다이얼로그 클래스를 그대로
    쓰되 모달 `exec()`만 no-op으로 막아 생성 경로 전체를 재현한다."""
    from app.widgets.zone_batch_result_dialog import ZoneBatchResultDialog

    with tempfile.TemporaryDirectory() as tmp:
        path1 = Path(tmp) / "a.png"
        path2 = Path(tmp) / "b.png"
        Image.new("RGB", (20, 20)).save(path1)
        Image.new("RGB", (20, 20)).save(path2)

        # path2(비활성 이미지)는 실사용과 동일하게 id 포함 6-튜플 사이드카로 저장.
        zstate.save_state(path2, {
            "circles": [(1, 3.0, 3.0, 1.0, "커스텀", False)],
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
        assert zone_names == {"중심부", "커스텀"}   # path2의 커스텀 이름 보존(바깥쪽 존 2026-10-30 제거)


# ── BUG-039 — `_target_cache` LRU 상한 ──────────────────────────────────────

def test_target_cache_is_lru_capped():
    """`_target_cache`가 상한(20) 없이 쌓이면 대형 이미지에서 메모리가 무한정
    늘어난다 — OrderedDict로 LRU 흉내(상한 초과 시 가장 오래된 항목 제거,
    적중 시 최근 사용으로 갱신)."""
    tab = ZoneAnalysisTab()
    old_refilter, old_cbl = module.engine.refilter, module.compute_blob_labels
    module.engine.refilter = lambda *a, **k: _result()
    module.compute_blob_labels = lambda mask: (np.zeros_like(mask, dtype=np.int32), [], 0)
    try:
        tab._overlay_visible = False   # 가짜 overlay_image=None으로 _show_overlay_state 크래시 방지
        tab._detected_ids = [1]
        for i in range(25):
            tab._image_path = Path(f"img_{i}.png")
            tab._last_result = _result()
            tab._on_target_changed()
        assert len(tab._target_cache) == 20
        assert next(reversed(tab._target_cache)) == Path("img_24.png")
        for i in range(5):
            assert Path(f"img_{i}.png") not in tab._target_cache, \
                "가장 오래된 항목이 제거돼야 함(LRU)"

        # 캐시 적중 시 move_to_end로 최근 사용 갱신 확인
        hit_path = Path("img_10.png")
        tab._image_path = hit_path
        tab._last_result = _result()
        tab._on_target_changed()
        assert next(reversed(tab._target_cache)) == hit_path
    finally:
        module.engine.refilter, module.compute_blob_labels = old_refilter, old_cbl
        tab.close()


if __name__ == "__main__":
    import pytest as _pytest
    raise SystemExit(_pytest.main([__file__, "-q"]))
