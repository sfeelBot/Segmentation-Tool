"""req6(2026-10-30) — "전체 결과 보기" 비동기화 회귀 테스트.

docs/specs/zone-analysis-tab-recipe-architecture-and-layout-2026-10-30.md 6절.
`_on_view_all_results()`가 더는 메인 스레드에서 동기 for문으로 `_compute_zone_rows()`
(cv2 connected-components 포함)를 돌리지 않고, `_ZoneViewAllWorker`(QThread)에
맡긴다 — 여기서는 (1) 메인 스레드를 블로킹하지 않는지, (2) 결과가 동기 버전과
바이트 단위로 동일한지, (3) 큰 이미지 리스트에서 체감 개선을 실측한다.
"""
import os
import tempfile
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PIL import Image
from PyQt6 import QtSvg  # noqa: F401  — Windows DLL load order before torch imports
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app.core import zone_state_store as zstate
from app.tabs import zone_analysis_tab as module
from app.tabs.zone_analysis_tab import (
    ZoneAnalysisTab, _ZoneViewAllWorker, _compute_zone_rows,
)

_APP = QApplication.instance() or QApplication([])


def _result(size: int, seed: int) -> object:
    """connected-components가 실제로 일할 거리를 만들기 위해 랜덤 블랍 패턴을
    쓴다(전부 1인 단색 마스크는 compute_blob_labels()가 즉시 끝나버려 실측에
    의미가 없음)."""
    rng = np.random.default_rng(seed)
    class_map = (rng.random((size, size)) > 0.5).astype(np.int64)
    return type("Result", (), {
        "raw_class_map": class_map, "class_map": class_map,
        "confidence_map": np.ones((size, size), dtype=np.float32), "overlay_image": None,
    })()


def _sync_reference(paths, results, target_cid, current_path, current_circles):
    """옛 동기 버전(`_on_view_all_results()`가 req6 이전에 하던 일)을 그대로
    재현 — 비동기 워커의 출력과 바이트 단위로 비교하는 기준선."""
    all_rows, all_blob_rows = [], []
    for path in paths:
        result = results.get(path)
        if result is None:
            continue
        previous = zstate.load_state(path)
        circles = (current_circles if path == current_path
                   else [c[1:] for c in (previous or {}).get("circles", [])])
        computed = _compute_zone_rows(path, result, target_cid, circles, previous)
        if computed is None:
            continue
        rows, blob_rows = computed
        all_rows.extend(rows)
        all_blob_rows.extend(blob_rows)
    return all_rows, all_blob_rows


def test_worker_output_matches_sync_reference():
    """결과값이 옛 동기 for문과 바이트 단위로 동일해야 한다(스펙 11절 "6번" 기준)."""
    with tempfile.TemporaryDirectory() as tmp:
        paths = [Path(tmp) / f"img{i}.png" for i in range(6)]
        results = {}
        for i, path in enumerate(paths):
            Image.new("RGB", (40, 40)).save(path)
            results[path] = _result(40, seed=i)
        circles = [(20.0, 20.0, 8.0, "inner", False), (20.0, 20.0, 16.0, "outer", False)]

        expected_rows, expected_blob_rows = _sync_reference(
            paths, results, 1, paths[0], circles
        )

        worker = _ZoneViewAllWorker(paths, results, 1, paths[0], circles)
        captured = []
        worker.result_ready.connect(lambda *a: captured.append(a))
        worker.run()   # 동기 직접 호출(스레드 미사용) — 순수 로직만 검증

        assert len(captured) == 1
        all_rows, all_blob_rows, skipped = captured[0]
        assert all_rows == expected_rows
        assert [(img, s.zone_name, s.blob_id, s.pixel_count) for img, s in all_blob_rows] == \
            [(img, s.zone_name, s.blob_id, s.pixel_count) for img, s in expected_blob_rows]
        assert skipped == []


def test_worker_skips_images_without_inference_result():
    with tempfile.TemporaryDirectory() as tmp:
        p1, p2 = Path(tmp) / "a.png", Path(tmp) / "b.png"
        Image.new("RGB", (20, 20)).save(p1)
        Image.new("RGB", (20, 20)).save(p2)
        results = {p1: _result(20, seed=0)}   # p2는 추론 결과 없음
        worker = _ZoneViewAllWorker([p1, p2], results, 1, p1, [(10.0, 10.0, 5.0)])
        captured = []
        worker.result_ready.connect(lambda *a: captured.append(a))
        worker.run()
        _rows, _blob_rows, skipped = captured[0]
        assert skipped == ["b.png"]


def test_worker_interruption_emits_no_result():
    """취소(`requestInterruption()`) 시 결과를 버리고 `result_ready`를 emit하지
    않아야 한다(디스크/모델 쓰기가 없는 순수 조회라 취소해도 잃을 게 없음, 스펙
    6절). `requestInterruption()`은 `.start()`로 실제 실행 중인 스레드에만 효과가
    있다(Qt 동작 — `_ZoneCircleLayoutWorker` 테스트와 동일 전제, 시작 전에 걸어두면
    `.start()`가 플래그를 리셋해 무효) — 첫 이미지 처리 중에 동기화해 실제로
    실행 중인 상태에서 걸어야 한다."""
    with tempfile.TemporaryDirectory() as tmp:
        paths = [Path(tmp) / f"img{i}.png" for i in range(3)]
        results = {}
        for i, path in enumerate(paths):
            Image.new("RGB", (20, 20)).save(path)
            results[path] = _result(20, seed=i)
        worker = _ZoneViewAllWorker(paths, results, 1, None, [])
        started = threading.Event()
        proceed = threading.Event()
        real_load_state = module.zstate.load_state

        def slow_load_state(path):
            if path == paths[0]:
                started.set()
                proceed.wait(5)
            return real_load_state(path)

        module.zstate.load_state = slow_load_state
        captured = []
        worker.result_ready.connect(lambda *a: captured.append(a))
        try:
            worker.start()
            assert started.wait(5), "워커가 제한 시간 내에 첫 이미지 처리를 시작하지 않음"
            worker.requestInterruption()
            proceed.set()
            assert worker.wait(5000)
            QTest.qWait(20)   # 워커 스레드 -> 메인 스레드 큐드 시그널을 펌핑해 전달
        finally:
            module.zstate.load_state = real_load_state
        assert captured == []


def test_on_view_all_results_returns_without_blocking_and_dialog_shown_after_worker_finishes():
    """`_on_view_all_results()` 호출 자체(워커를 start()하고 리턴)는 즉시 끝나야
    한다 — 실제 계산(이미지 20장, cv2 connected-components 포함)은 워커 스레드로
    옮겨졌으므로 메인 스레드는 블로킹되지 않는다."""
    with tempfile.TemporaryDirectory() as tmp:
        n = 20
        paths = [Path(tmp) / f"img{i}.png" for i in range(n)]
        tab = ZoneAnalysisTab()
        old_dialog = module.ZoneBatchResultDialog
        created = []

        class _NoExecDialog:
            def __init__(self, rows, blob_rows, parent=None):
                created.append((rows, blob_rows))

            def exec(self):
                return None

        module.ZoneBatchResultDialog = _NoExecDialog
        try:
            for i, path in enumerate(paths):
                Image.new("RGB", (120, 120)).save(path)
                tab._results[path] = _result(120, seed=i)
                if i != 0:   # paths[0]은 "현재 이미지" — 아래에서 live canvas circles로 설정
                    zstate.save_state(path, {
                        "circles": [(0, 60.0, 60.0, 20.0, "inner", False),
                                    (1, 60.0, 60.0, 50.0, "outer", False)],
                        "removed_blob_ids": set(), "erase_strokes": [], "manual_strokes": [],
                    })
            tab._img_list.load_files(paths)
            tab._image_path = paths[0]
            tab._image_size = (120, 120)
            tab._canvas.set_image_size(120, 120)
            tab._canvas.set_circles([(60.0, 60.0, 20.0, "inner", False), (60.0, 60.0, 50.0, "outer", False)])
            tab._target_class_id = 1

            call_start = time.monotonic()
            tab._on_view_all_results()
            call_elapsed = time.monotonic() - call_start
            # 동기 시절엔 이 구간 안에서 20장의 compute_blob_labels가 전부 끝났어야
            # 했다 — 비동기화 후엔 워커를 start()하고 바로 리턴하므로 수십 ms 이내.
            assert call_elapsed < 0.3, f"_on_view_all_results()가 즉시 리턴하지 않음({call_elapsed:.3f}s)"
            assert created == []   # 워커가 아직 안 끝났으면 다이얼로그도 아직 없어야 함

            worker = tab._view_all_worker
            assert worker is not None
            assert worker.wait(15000)
            for _ in range(500):
                if tab._view_all_worker is None:
                    break
                QTest.qWait(20)
            else:
                raise AssertionError("view_all_worker가 제한 시간 내에 종료되지 않음")

            assert len(created) == 1
            rows, _blob_rows = created[0]
            assert {img for img, _z, _p in rows} == {p.name for p in paths}
        finally:
            module.ZoneBatchResultDialog = old_dialog
            tab.close()


def test_measured_speedup_on_synthetic_image_batch():
    """합성 이미지 30장으로 "동기 for문" 대비 실제 체감 개선을 헤드리스로 측정.
    엄격한 assert보다 측정치 출력이 목적이지만, 최소한 "워커 스레드 실행 시간이
    메인 스레드 blocking 시간보다 훨씬 크다"는 것만은 단언한다(비동기화가 실제로
    적용됐다는 최소 증거)."""
    with tempfile.TemporaryDirectory() as tmp:
        n = 30
        size = 900   # BUG-040 실측(5472x3648)만큼은 아니지만 cv2 connected-components가
                     # 체감될 정도로 키움 — 테스트 전체 시간은 여전히 수 초 이내.
        paths = [Path(tmp) / f"img{i}.png" for i in range(n)]
        results = {}
        for i, path in enumerate(paths):
            Image.new("RGB", (size, size)).save(path)
            results[path] = _result(size, seed=i)
        circles = [(size / 2, size / 2, size * 0.3, "inner", False),
                   (size / 2, size / 2, size * 0.7, "outer", False)]

        sync_start = time.monotonic()
        _sync_reference(paths, results, 1, paths[0], circles)
        sync_elapsed = time.monotonic() - sync_start

        worker = _ZoneViewAllWorker(paths, results, 1, paths[0], circles)
        async_start = time.monotonic()
        worker.start()
        start_call_elapsed = time.monotonic() - async_start   # 메인 스레드 블로킹 시간(.start() 리턴까지)
        assert worker.wait(15000)
        worker_total_elapsed = time.monotonic() - async_start

        # Windows 콘솔(cp949)에서 유니코드 문자가 UnicodeEncodeError를 낼 수 있어
        # 실측 로그는 ASCII로만 출력한다(안전한 pytest -s 출력).
        print(
            f"\n[req6 measured] n={n} images({size}x{size}) - sync for-loop: {sync_elapsed*1000:.1f}ms, "
            f"worker .start() blocking: {start_call_elapsed*1000:.1f}ms, "
            f"worker total runtime: {worker_total_elapsed*1000:.1f}ms"
        )
        assert start_call_elapsed < sync_elapsed, \
            "메인 스레드 블로킹 시간이 동기 버전 전체 계산 시간보다 짧아야 함(비동기화 증거)"


if __name__ == "__main__":
    import pytest as _pytest
    raise SystemExit(_pytest.main([__file__, "-q", "-s"]))
