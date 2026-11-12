"""상/하부(Zone) 분석 탭 조작별 지연 벤치 — offscreen, 실제 ZoneAnalysisTab + 가짜 추론 결과 + QTest.

성능 작업의 전/후 비교용 — 시나리오 이름(`scenario`/`edits`/`size`)은 바꾸지 않는다.
인자·JSON 형식은 `bench_r_tab.py`와 같다(측정 틀 Bench/table/pump를 그대로 import).

    set QT_QPA_PLATFORM=offscreen
    set SEG_DATA_DIR=<임시 폴더>            # 사용자 data/ 를 건드리지 않게
    python scripts/bench_zone_tab.py --out zone_before.json
    python scripts/bench_zone_tab.py --out zone_after.json --compare zone_before.json
    python scripts/bench_zone_tab.py --sizes 4000x3000 --blobs 10 --profile-dir prof/   # cProfile 덤프

- 모델 forward는 범위 밖 — 추론 결과(InferenceResult)는 합성해 `_on_inference_result`로 주입한다.
- `size` 라벨: 블랍 ~10개 변형은 `WxH`, 그 외는 `WxH_b<N>` (예: `4000x3000_b500`).
- 편집량: `e0`(편집 없음) / `e30`(스트로크 30 + 영역 삭제 3) / `build`(e0→e30로 쌓는 동안).
- 좌표는 4000x3000 기준으로 적고 이미지 크기에 비례해 스케일한다. 브러시 크기는 원본 40px 고정.
- 디바운스 대기(임계값 150ms, 불투명도 75ms, 자동 저장 500ms)는 빼고 타이머가 부르는 처리만 잰다.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent))

# ponytail: 측정 틀은 R 벤치 모듈을 그대로 쓴다(QApplication 생성·QMessageBox 스텁 포함).
# bench_r_tab.py 가 없어지면 Bench/table/pump(약 80줄)를 이리로 옮길 것.
import bench_r_tab as B  # noqa: E402
from bench_r_tab import LEFT, MODALS, REPO, Bench, pc, pump, qapp, table  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import PIL.Image  # noqa: E402
from PyQt6.QtCore import QElapsedTimer, QPoint, QPointF, Qt  # noqa: E402
from PyQt6.QtGui import QImage, QWheelEvent  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QFileDialog  # noqa: E402

from app.core import inference_engine as engine  # noqa: E402
from app.core import zone_metrics  # noqa: E402
from app.core import zone_state_store as zstate  # noqa: E402
from app.tabs import zone_analysis_tab as zt  # noqa: E402
from app.widgets import inference_image_list as iil  # noqa: E402
from app.widgets import overlay_viewer as ov  # noqa: E402
from app.widgets import zone_canvas as zc  # noqa: E402
from app.widgets.brush_toolbar import TOOL_BRUSH, TOOL_ERASER, TOOL_ERASER_FLOOD, TOOL_PAN  # noqa: E402

TOOL_NONE = "circle"        # 탭의 "도구 없음"(조회 클릭) 상태
CID = 1

_T, _C = zt.ZoneAnalysisTab, zc.ZoneCanvas
HOOKS = [(_T, n, f"tab.{n}") for n in (
    "_on_list_image_selected", "_setup_target_classes", "_on_target_changed", "_show_overlay_state",
    "_reblend_overlay", "_ai_and_final_masks", "_recompute_zones", "_current_zones",
    "_compute_zone_percentages", "_compute_zone_blob_rows", "_make_zone_row_widget",
    "_on_canvas_blob_clicked", "_on_blob_deleted", "_flush_state", "_refresh_circle_list",
    "_refresh_step_indicator", "_on_batch_progress")]
HOOKS += [(_C, n, f"canvas.{n}") for n in (
    "paintEvent", "_paint_current_stroke", "set_state", "set_blob_data", "_replay_erase_strokes",
    "_rebuild_stroke_overlay", "_rasterize_stroke", "_erase_paint_stroke", "edited_masks",
    "_handle_blob_click", "undo")]
HOOKS += [(ov.OverlayViewer, "paintEvent", "viewer.paintEvent(drawPixmap)")]
HOOKS += [(zone_metrics, n, n) for n in (
    "apply_edits", "apply_manual_strokes", "disk_mask", "zones_from_circles", "zone_stats",
    "zone_blob_stats", "compute_blob_labels")]
# `from zone_metrics import X` 로 묶인 이름은 모듈별로 따로 감싼다(같은 라벨로 합산).
HOOKS += [(zt, n, n) for n in ("apply_edits", "zones_from_circles", "zone_stats", "zone_blob_stats",
                               "compute_blob_labels", "_compute_zone_rows", "_rgb_to_qpixmap")]
HOOKS += [(zc, "disk_mask", "disk_mask")]
HOOKS += [(engine, n, f"engine.{n}") for n in (
    "refilter", "reblend", "colorize_class_map", "_colorize_and_blend", "_compute_blobs_and_filter",
    "load_classes")]
HOOKS += [(cv2, "connectedComponentsWithStats", "cv2.connectedComponentsWithStats"),
          (cv2, "floodFill", "cv2.floodFill"),
          (PIL.Image.Image, "convert", "PIL.convert(디코드)"),
          (PIL.Image.Image, "thumbnail", "PIL.thumbnail"),
          (PIL.Image.Image, "resize", "PIL.resize"),
          (zstate, "save_state", "zstate.save_state"),
          (zstate, "load_state", "zstate.load_state"),
          (iil.InferenceImageList, "_apply_display", "image_list._apply_display")]

B.PROFILE.update({
    "infer_result_display", "image_switch_noresult_cold", "image_switch_away", "target_class_change",
    "conf_threshold_change", "min_px_change", "blob_click_select", "zone_click_select",
    "overlay_toggle_on", "recompute_zones", "recipe_apply", "recipe_open", "view_all_results",
    "export_single_open", "autosave_flush", "batch_apply_circles", "brush_commit_long",
})


def install_hooks() -> None:
    """R 벤치와 같은 (호출 수, 포함 시간) 계측. 시그널에 연결된 슬롯은 PyQt가 '인자 줄여 재시도'를
    하지 못하므로(래퍼가 *a 를 받아버림) 원 함수가 받는 개수로 잘라 넘긴다. 구현이 바뀌어
    없어진 이름은 건너뛴다 — 시나리오 측정값 자체는 계측 없이도 유효."""
    for owner, attr, label in HOOKS:
        orig = getattr(owner, attr, None)
        if orig is None:
            print(f"[bench] hook 없음(건너뜀): {label}", file=sys.stderr)
            continue
        code = getattr(orig, "__code__", None)
        nmax = code.co_argcount if code is not None and not code.co_flags & 0x04 else None

        def wrapper(*a, _orig=orig, _label=label, _n=nmax, **k):
            t0 = pc()
            try:
                return _orig(*(a if _n is None else a[:_n]), **k)
            finally:
                s = B.STATS.setdefault(_label, [0, 0.0])
                s[0] += 1
                s[1] += pc() - t0
        setattr(owner, attr, wrapper)


# ── 픽스처 ──────────────────────────────────────────────────────────────────

def ensure_fixtures(base: Path, w: int, h: int, ext: str, n: int) -> list[Path]:
    root = base / f"{w}x{h}_{ext}"
    paths = [root / f"img_{i + 1:02d}.{ext}" for i in range(n)]
    for stale in root.glob("*.zone.json"):      # 이전 실행의 사이드카
        stale.unlink()
    if all(p.exists() for p in paths):
        return paths
    root.mkdir(parents=True, exist_ok=True)
    s, sx, sy = min(w / 4000, h / 3000), w / 4000, h / 3000     # 좌표는 축별, 반지름은 작은 쪽
    rng = np.random.default_rng(1)
    img = np.clip(60 + rng.integers(-6, 7, (h, w, 1)), 0, 255).astype(np.uint8).repeat(3, axis=2)
    cv2.circle(img, (int(2000 * sx), int(1500 * sy)), int(1100 * s), (150, 150, 150), -1)
    ok, buf = cv2.imencode(f".{ext}", img, [cv2.IMWRITE_JPEG_QUALITY, 92] if ext == "jpg" else [])
    assert ok
    for p in paths:
        buf.tofile(str(p))
    return paths


def make_class_map(w: int, h: int, blobs: int):
    """(class_map int64, 삭제용 블랍 중심 4곳, 조회 클릭용 블랍 중심, 존 안 빈 곳) — 좌표는 4000x3000 기준."""
    s, sx, sy = min(w / 4000, h / 3000), w / 4000, h / 3000
    cm = np.zeros((h, w), dtype=np.uint8)

    def disk(x, y, r, v):
        cv2.circle(cm, (int(x * sx), int(y * sy)), max(1, int(r * s)), v, -1)

    if blobs <= 20:     # 링 + 링 안 블랍 + 모서리 원판 4 + 위쪽 작은 점
        disk(2000, 1500, 700, 1)
        disk(2000, 1500, 600, 0)
        disk(2000, 1500, 100, 1)
        del_pts = [(500, 500), (3500, 500), (500, 2500), (3500, 2500)]
        for x, y in del_pts:
            disk(x, y, 120, 1)
        for k in range(max(0, blobs - 6)):
            disk(1200 + 400 * k, 250, 40, 1)
        sel_pt = (2000, 1560)
    else:               # 격자: 60x60 사각형, 25열 x (blobs/25)행
        rows = max(1, blobs // 25)
        dy = 2600 / rows
        for r in range(rows):
            for c in range(25):
                x, y = 200 + c * 146, 200 + r * dy
                cm[int(y * sy):int((y + 60) * sy), int(x * sx):int((x + 60) * sx)] = 1
        del_pts = [(200 + c * 146 + 30, 230) for c in (2, 8, 14, 20)]
        r_mid = min(range(rows), key=lambda r: abs(200 + r * dy + 30 - 1440))
        sel_pt = (200 + 14 * 146 + 30, 200 + r_mid * dy + 30)     # 14열: e30 스트로크(x 1000~1280/1700~1980/2400~2680)가 닿지 않는 열
    disk(300, 1500, 50, 2)      # 두 번째 클래스 — 타겟 클래스 콤보가 2개가 되게
    disk(3700, 1500, 50, 2)
    return cm.astype(np.int64), del_pts, sel_pt, (2200, 1500)


def make_result(cm: np.ndarray) -> zt.InferenceResult:
    h, w = cm.shape
    return zt.InferenceResult(
        class_map=cm.copy(), raw_class_map=cm,
        confidence_map=np.full((h, w), 0.9, dtype=np.float32),
        overlay_image=QImage(8, 8, QImage.Format.Format_RGB32), class_stats=[], blobs=[])


def wait(cond, timeout_s: float = 900) -> None:
    t0 = pc()
    while not cond():
        QTest.qWait(2)
        assert pc() - t0 < timeout_s, "워커 대기 시간 초과"


# ── 크기 x 블랍 수 1조합 ──────────────────────────────────────────────────────

def run_combo(w: int, h: int, blobs: int, label: str, args, profile_dir: Path | None):
    paths = ensure_fixtures(Path(args.fixtures), w, h, args.ext, args.images)
    A, Bp = paths[0], paths[1]
    s, sx, sy = min(w / 4000, h / 3000), w / 4000, h / 3000
    b = Bench(label, args.repeat, profile_dir)
    win = tuple(int(v) for v in args.window.split("x"))

    tab = zt.ZoneAnalysisTab()
    tab.resize(*win)
    tab.show()
    pump()
    QTest.qWait(30)
    cv, il = tab._canvas, tab._img_list
    il.load_files(paths)
    pump()
    assert tab._image_path == A, tab._image_path

    def P(x: float, y: float) -> tuple[float, float]:      # 4000x3000 기준 → 이 이미지의 원본 좌표
        return x * sx, y * sy

    def spt(xy) -> QPoint:
        c, _ = cv._orig_to_screen(xy[0], xy[1], 0.0)
        return QPoint(round(c.x()), round(c.y()))

    def set_tool(name: str) -> None:
        if tab._active_tool != name:        # 같은 도구를 다시 누르면 꺼진다(토글)
            tab._set_tool(name)
        pump()

    def click(xy) -> None:
        QTest.mouseClick(cv, LEFT, pos=spt(P(*xy)))

    def ctrl_z() -> None:
        QTest.keyClick(cv, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)

    def list_click(path: Path) -> None:
        r = il._tree.visualItemRect(il._path_to_item[path])
        QTest.mouseClick(il._tree.viewport(), LEFT, pos=r.center())

    def goto(path: Path) -> None:
        if tab._image_path != path:
            list_click(path)
            pump()
        assert tab._image_path == path, (tab._image_path, path)

    def fire(timer_name: str) -> None:
        """디바운스 타이머가 부를 처리를 지금 실행(대기 시간 제외)."""
        tm = getattr(tab, timer_name)
        tm.stop()
        tm.timeout.emit()

    def drag(scenario, edits, pts, release_scenario=None):
        """press → move마다 (이벤트 처리 + 그리기) 시간 → release(스트로크 커밋) 시간."""
        scr = [spt(p) for p in pts]
        QTest.mousePress(cv, LEFT, pos=scr[0])
        pump()
        moves = [b.t(lambda q=q: QTest.mouseMove(cv, q)) for q in scr[1:]]
        rel = b.t(lambda: QTest.mouseRelease(cv, LEFT, pos=scr[-1]),
                  (release_scenario, edits) if release_scenario else None)
        if scenario:
            b.add(scenario, edits, moves, "mouseMove 1회(그리기 포함)")
        if release_scenario:
            b.add(release_scenario, edits, [rel])
        return moves, rel

    def stroke_pts(x0: float, y: float, n: int = 8, step: float = 40):
        return [P(x0 + k * step, y) for k in range(n)]

    def n_strokes() -> int:
        return len(cv.get_state()["manual_strokes"])

    def switch(scenario, edits, dst, cold=False, pending_save=False):
        src = Bp if dst == A else A

        def setup(i):
            goto(src)
            if pending_save:
                tab._save_timer.start()     # 편집 직후 전환 — 떠나는 이미지의 사이드카 저장이 전환에 얹힌다
            if cold:
                for name in ("_preview_cache", "_target_cache", "_detected_ids_cache"):
                    getattr(tab, name, {}).pop(dst, None)
        b.measure(scenario, edits, lambda i: list_click(dst), setup)
        goto(A)

    # ── 추론 전: 이미지 전환(미리보기 디코드만) ──
    switch("image_switch_noresult_cold", "e0", A, cold=True)
    switch("image_switch_noresult_warm", "e0", A)

    # ── 추론 결과 수신 → 표시 ──
    cm, del_pts, sel_pt, zone_pt = make_class_map(w, h, blobs)
    res_a, res_b = make_result(cm), make_result(cm)
    res_b.class_map = res_a.class_map       # 읽기 전용으로만 쓰인다 — 메모리 절약
    tab._infer_elapsed = QElapsedTimer()
    tab._infer_elapsed.start()

    def evict(i):       # `_run_inference`가 재추론 전에 하는 캐시 비우기와 동일
        for name in ("_results", "_target_cache", "_detected_ids_cache"):
            getattr(tab, name, {}).pop(A, None)
    b.measure("infer_result_display", "e0", lambda i: tab._on_inference_result(A, res_a, 1, 1), evict,
              note="현재 이미지의 추론 결과 수신 → 후처리 → 오버레이 표시(forward 제외)")
    assert tab._target_class_id == CID and tab._target_combo.count() >= 2
    tab._on_inference_result(Bp, res_b, 2, 2)       # 현재 이미지가 아니면 저장만
    circ = [(2000 * sx, 1500 * sy, 300 * s), (2000 * sx, 1500 * sy, 1000 * s)]
    for p in (Bp, A):
        goto(p)
        cv.set_circles(circ)
        pump()
        fire("_save_timer")
    n_blobs = int(cv2.connectedComponents((cm == CID).astype(np.uint8), connectivity=4)[0]) - 1
    cv.set_erase_brush_size(40)

    def battery(edits: str) -> None:
        base = n_strokes()
        set_tool(TOOL_NONE)
        b.measure("paint_repaint", edits, lambda i: cv.repaint(), n=10, note="paintEvent 1회")
        c = cv.rect().center()
        for d in (120,) * 5 + (-120,) * 5:
            ev = QWheelEvent(QPointF(c), QPointF(cv.mapToGlobal(c)), QPoint(0, 0), QPoint(0, d),
                             Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                             Qt.ScrollPhase.NoScrollPhase, False)
            b.add("zoom_wheel", edits, [b.t(lambda: QApplication.sendEvent(cv, ev))])
        cv._fit_view()
        set_tool(TOOL_PAN)
        drag("pan_move", edits, [P(1150 + 25 * k, 1450 + 15 * k) for k in range(21)])
        cv._fit_view()
        set_tool(TOOL_NONE)

        # 조회 클릭(도구 없음): 존 선택 / 블랍 선택 / 우측 목록 행 선택
        b.measure("zone_click_select", edits, lambda i: click(zone_pt), note="마스크 밖 클릭 — 존 하이라이트")
        b.measure("blob_click_select", edits, lambda i: click(sel_pt), note="블랍 위 클릭 — 블랍 정보 표시")
        assert tab._lbl_selected_blob.text(), "블랍 클릭이 블랍을 못 찾음"
        b.measure("zone_row_select", edits, lambda i: tab._zone_list.setCurrentRow(i % 2))

        # 불투명도 / 오버레이 표시 토글
        sl = tab._overlay_opacity_slider
        v0 = sl.value()
        b.measure("opacity_step", edits, lambda i: (sl.setValue(v0 - 5 * (i + 1)), fire("_opacity_timer")),
                  note="슬라이더 값 변경 1회분 재합성(75ms 디바운스 제외)")
        sl.setValue(v0)
        fire("_opacity_timer")
        pump()
        for _ in range(args.repeat):
            b.add("overlay_toggle_off", edits, [b.t(tab._act_overlay_visible.trigger, ("overlay_toggle_off", edits))])
            b.add("overlay_toggle_on", edits, [b.t(tab._act_overlay_visible.trigger, ("overlay_toggle_on", edits))])

        # 우측 패널(존별 비율·블랍 표) 갱신 = 원 확정 시 도는 경로
        b.measure("recompute_zones", edits, lambda i: cv.circles_committed.emit(),
                  note="원 이동/크기 확정 시 우측 패널 갱신")
        b.measure("recipe_apply", edits, lambda i: cv.set_circles(circ), note="원 설정 모달 적용(set_circles)")

        # 브러시 그리기 / 지우기 / 영역 삭제 + 각 Ctrl+Z
        for tool, mv, cm_, un, pts in (
                (TOOL_BRUSH, "brush_move", "brush_commit", "undo_brush", stroke_pts(1000, 2300)),
                (TOOL_ERASER, "eraser_move", "eraser_commit", "undo_eraser", stroke_pts(1860, 2150))):
            set_tool(tool)
            for _ in range(args.repeat):
                drag(mv, edits, pts, cm_)
                assert n_strokes() == base + 1, (tool, n_strokes(), base)
                b.add(un, edits, [b.t(ctrl_z, (un, edits))])
                assert n_strokes() == base, (tool, n_strokes(), base)
        set_tool(TOOL_ERASER_FLOOD)
        for _ in range(args.repeat):
            n0 = len(cv.get_state()["removed_points"])
            b.add("delete_blob", edits, [b.t(lambda: click(del_pts[3]), ("delete_blob", edits))])
            assert len(cv.get_state()["removed_points"]) == n0 + 1, "영역 삭제 클릭이 블랍을 못 맞춤"
            b.add("undo_delete", edits, [b.t(ctrl_z, ("undo_delete", edits))])
            assert len(cv.get_state()["removed_points"]) == n0
        set_tool(TOOL_NONE)

        # 자동 저장 / 결과 보기
        b.measure("autosave_flush", edits, lambda i: fire("_save_timer"), note="사이드카 저장 1회(500ms 디바운스 제외)")
        b.measure("export_single_open", edits, lambda i: tab._btn_export_single.click(),
                  note="현재 이미지 결과표 열기(다이얼로그 구성까지)")
        assert dialogs, "결과표 다이얼로그가 열리지 않음"
        b.measure("view_all_results", edits,
                  lambda i: (tab._btn_view_all.click(), wait(lambda: tab._view_all_worker is None)),
                  note="추론된 2장 집계(워커) + 결과표 구성. 클릭~표 준비까지")

        # 이미지 전환(추론 결과 있음)
        switch("image_switch_list_warm", edits, A)
        switch("image_switch_list_cold", edits, A, cold=True)
        switch("image_switch_away", edits, Bp, pending_save=True)
        assert n_strokes() == base, (n_strokes(), base)

    dialogs: list = []
    zt.ZoneBatchResultDialog.exec = lambda self: dialogs.append(self) or 0     # 모달 대신 인스턴스만 보관

    battery("e0")

    # ── e0 전용: 임계값·타겟 변경(수동 편집을 지우는 경로라 편집 없는 상태에서만) ──
    combo = tab._target_combo
    b.measure("target_class_change", "e0", lambda i: combo.setCurrentIndex(1 - combo.currentIndex()), n=2 * (args.repeat // 2 + 1),
              note="타겟 클래스 콤보 변경(캐시 미스)")
    assert tab._target_class_id == CID
    sl, sp = tab._conf_slider, tab._min_px_spin
    c0, m0 = sl.value(), sp.value()
    b.measure("conf_threshold_change", "e0", lambda i: (sl.setValue(c0 + 10 + i), fire("_threshold_timer")),
              note="AI 신뢰도 값 변경 1회분(150ms 디바운스 제외)")
    sl.setValue(c0)
    b.measure("min_px_change", "e0", lambda i: (sp.setValue(m0 + 1 + i), fire("_threshold_timer")),
              note="최소 픽셀 값 변경 1회분(150ms 디바운스 제외)")
    sp.setValue(m0)
    fire("_threshold_timer")
    pump()

    # ── e0 전용: 긴 스트로크 1획(move 300회) — 획이 길어질수록 move가 느려지는지 ──
    set_tool(TOOL_BRUSH)
    moves, rel = drag(None, "e0", [P(600 + 9.3 * k, 2400 + 60 * ((k // 50) % 2)) for k in range(301)])
    b.add("brush_move_long_first20", "e0", moves[:20], "긴 획의 처음 20 move")
    b.add("brush_move_long_last20", "e0", moves[-20:], "긴 획의 마지막 20 move(300 move째)")
    b.add("brush_commit_long", "e0", [rel], "move 300회짜리 획 1개 커밋")
    ctrl_z()
    pump()
    assert n_strokes() == 0

    # ── e30 만들기: 스트로크 30(그리기 20 + 지우기 10) + 영역 삭제 3 ──
    commits = []
    for i in range(30):
        set_tool(TOOL_ERASER if i % 3 == 2 else TOOL_BRUSH)
        _, rel = drag(None, "build", stroke_pts(1000 + (i // 10) * 700, 900 + (i % 10) * 120))
        commits.append(rel)
    b.add("stroke_commit_build_first5", "build", commits[:5], "1~5번째 스트로크 커밋")
    b.add("stroke_commit_build_last5", "build", commits[-5:], "26~30번째 스트로크 커밋")
    set_tool(TOOL_ERASER_FLOOD)
    b.add("delete_blob_build", "build", [b.t(lambda p=p: click(p)) for p in del_pts[:3]], "스트로크 30 상태에서 삭제 1~3번째")
    st = cv.get_state()
    assert len(st["manual_strokes"]) == 30 and len(st["removed_points"]) == 3, (
        len(st["manual_strokes"]), len(st["removed_points"]))
    stamps = sum(len(pts) for _d, pts in st["manual_strokes"])
    fire("_save_timer")

    battery("e30")

    # ── 원 설정(레시피) 모달 열기 ──
    opened: list = []

    def open_recipe(i):
        dlg = zt.ZoneRecipeDialog(tab._original_pixmap, tab._image_size, tab,
                                  initial_circles=cv.get_circles(), image_name=A.name)
        dlg.show()
        opened.append(dlg)
    b.measure("recipe_open", "e30", open_recipe, teardown=lambda i: (opened[-1].close(), opened[-1].deleteLater()),
              note="원 설정 모달 구성 + 첫 표시(저장된 레시피 0개)")

    # ── 엑셀 내보내기 / 결과 이미지 일괄 저장 ──
    out_dir = Path(tempfile.mkdtemp(prefix="bench_zone_out_"))
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(out_dir / "zones.xlsx"), ""))
    QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: str(out_dir))
    b.measure("excel_export", "e30", lambda i: dialogs[-1]._on_export(),
              note=f"전체 결과표 → xlsx (행 {dialogs[-1]._long_table.rowCount() if hasattr(dialogs[-1], '_long_table') else '?'})")
    b.measure("save_all_images", "e30", lambda i: tab._btn_save_all_images.click(), note="추론된 2장 오버레이 PNG 저장")
    MODALS.clear()      # 내보내기/저장 완료 안내(예상된 모달)

    # ── 배치 "영역 적용": 목록 전체 선택 → 원 복사 ──
    tab._confirm_existing_zones = lambda n: "replace"

    def batch(i):
        tab._btn_batch.click()
        wait(lambda: tab._post_worker is None)
    il._tree.selectAll()
    pump()
    assert len(il.selected_paths()) == len(paths) and tab._btn_batch.isEnabled()
    b.measure("batch_apply_circles", "e30", batch, n=args.batch_repeat,
              note=f"{len(paths)}장에 기준 원 복사(워커 대기 포함)")
    assert all(zstate.sidecar_path(p).exists() for p in paths)
    MODALS.clear()      # 배치 완료 안내(예상된 모달)

    info = {"w": w, "h": h, "blobs": n_blobs, "images": len(paths), "file_kb": round(A.stat().st_size / 1024),
            "e30_stamps": stamps, "canvas": [cv.width(), cv.height()],
            "preview": [tab._original_pixmap.width(), tab._original_pixmap.height()]}
    tab._save_timer.stop()
    tab.close()
    tab.deleteLater()
    pump()
    return b.results(), info


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default="bench_zone_tab.json")
    ap.add_argument("--sizes", default="1920x1200,4000x3000,5472x3648")
    ap.add_argument("--blobs", default="10,500", help="타겟 블랍 수 변형(쉼표). 첫 값은 size 라벨 그대로, 나머지는 _b<N> 접미사")
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--batch-repeat", type=int, default=1, help="배치 영역 적용(가장 긴 시나리오) 반복 수")
    ap.add_argument("--images", type=int, default=12, help="목록 이미지 수(배치 대상)")
    ap.add_argument("--ext", default="jpg", help="픽스처 이미지 형식(jpg/png/bmp) — 디코드 비용이 달라진다")
    ap.add_argument("--window", default="1920x1040", help="탭 위젯 크기")
    ap.add_argument("--fixtures", default=str(Path(tempfile.gettempdir()) / "bench_zone_tab_fixtures"))
    ap.add_argument("--compare", help="이전 결과 JSON — 표에 '이전 → 현재 (×배율)'로 출력")
    ap.add_argument("--profile-dir", help="지정하면 계측 래퍼 대신 cProfile로 주요 시나리오의 함수별 누적 시간을 덤프(JSON은 쓰지 않음)")
    args = ap.parse_args()

    profile_dir = Path(args.profile_dir) if args.profile_dir else None
    if profile_dir:
        profile_dir.mkdir(parents=True, exist_ok=True)
    else:
        install_hooks()

    results: list[dict] = []
    infos: dict[str, dict] = {}
    t0 = pc()
    blob_counts = [int(v) for v in args.blobs.split(",")]
    for s in args.sizes.split(","):
        w, h = (int(v) for v in s.split("x"))
        for nb in blob_counts:
            label = s if nb == blob_counts[0] else f"{s}_b{nb}"
            print(f"[bench] {label} ...", flush=True)
            r, infos[label] = run_combo(w, h, nb, label, args, profile_dir)
            results += r
            print(f"[bench] {label} done ({pc() - t0:.0f}s) {infos[label]}", flush=True)
    assert not MODALS, f"예상 못 한 QMessageBox: {MODALS}"
    if profile_dir:
        print(f"[bench] cProfile 덤프: {profile_dir}")
        return

    try:
        head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
    except OSError:
        head = "?"
    from PyQt6.QtCore import QT_VERSION_STR
    meta = {
        "date": time.strftime("%Y-%m-%d %H:%M:%S"), "git_head": head, "platform": qapp.platformName(),
        "qt": QT_VERSION_STR, "python": sys.version.split()[0], "numpy": np.__version__, "cv2": cv2.__version__,
        "args": vars(args), "sizes": infos, "elapsed_s": round(pc() - t0),
    }
    out = Path(args.out)
    out.write_text(json.dumps({"meta": meta, "results": results}, ensure_ascii=False, indent=1), encoding="utf-8")
    before = json.loads(Path(args.compare).read_text(encoding="utf-8"))["results"] if args.compare else None
    txt = table(results, before)
    out.with_suffix(".summary.md").write_text(txt + "\n", encoding="utf-8")
    print(txt)
    print(f"[bench] {out} ({len(results)} rows, {meta['elapsed_s']}s)")


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    os._exit(0)     # 워커 스레드/Qt 종료 순서에 기대지 않는다
