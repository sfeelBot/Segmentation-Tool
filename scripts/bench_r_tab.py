"""R 분석 탭 성능 벤치 — 실제 `RAnalysisTab`을 offscreen으로 띄워 조작별 소요 시간(ms)을 잰다.

앱 코드는 수정하지 않는다(런타임 계측 래퍼만 씌움). 시나리오 이름과 JSON 형식은
개선 전/후 비교용으로 고정 — 같은 명령을 그대로 다시 돌려 `--compare`로 비교한다.

    set QT_QPA_PLATFORM=offscreen & set PYTHONPATH=<repo>
    python scripts/bench_r_tab.py --out r_before.json
    python scripts/bench_r_tab.py --out r_after.json --compare r_before.json
    python scripts/bench_r_tab.py --sizes 4000x3000 --profile-dir prof/   # cProfile 상위 함수

기준 좌표계는 4000x3000 — 블랍 격자·ROI·스트로크 위치를 이미지 크기에 비례해 옮긴다
(같은 화면 제스처). 브러시 크기는 40px(원본 픽셀) 고정.
편집량: e0 = 편집 없음, e30 = 브러시 스트로크 30개 + 블랍 삭제 3개.

# ponytail: 탭/캔버스의 private 속성(`_canvas`, `_manual_strokes` 등)에 직접 접근한다 —
# 구조 개편으로 이름이 바뀌면 이 파일의 접근부(HOOKS, run_size)를 같이 고친다.
"""
from __future__ import annotations

import argparse
import cProfile
import io
import json
import os
import pstats
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PyQt6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PyQt6.QtGui import QWheelEvent  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox  # noqa: E402

qapp = QApplication.instance() or QApplication(sys.argv)
# offscreen에서 QMessageBox 정적 호출은 영원히 블록된다 — 뜨면 벤치가 잘못된 것이므로 기록만.
MODALS: list[str] = []
for _k in ("information", "warning", "critical", "question"):
    setattr(QMessageBox, _k, staticmethod(
        lambda p, title, text, *a, **k: (MODALS.append(f"{title}: {text}"), QMessageBox.StandardButton.Ok)[1]))

from app.core import r_analysis_metrics as rm  # noqa: E402
from app.core import zone_metrics  # noqa: E402
from app.tabs import r_analysis_tab as rt  # noqa: E402
from app.widgets import inference_image_list as iil  # noqa: E402
from app.widgets import r_cell_panel as rcp  # noqa: E402
from app.widgets import r_roi_canvas as rc  # noqa: E402

LEFT = Qt.MouseButton.LeftButton
pc = time.perf_counter

# ── 함수별 계측(호출 수 + 포함 시간) — 조작 1회 안에서 같은 무거운 연산이 몇 번 도는지 본다 ──
STATS: dict[str, list[float]] = {}
HOOKS = [
    (rc.RRoiCanvas, "paintEvent", "canvas.paintEvent"),
    (rc.RRoiCanvas, "_rebuild_mask_image", "canvas._rebuild_mask_image"),
    (rc.RRoiCanvas, "_rebuild_stroke_overlay", "canvas._rebuild_stroke_overlay"),
    (rc.RRoiCanvas, "_replay_erase_strokes", "canvas._replay_erase_strokes"),
    (rc.RRoiCanvas, "_rasterize_stroke", "canvas._rasterize_stroke"),
    (rc.RRoiCanvas, "effective_mask", "canvas.effective_mask"),
    (rc, "apply_edits", "apply_edits"),
    (rt, "apply_edits", "apply_edits"),
    (zone_metrics, "apply_manual_strokes", "apply_manual_strokes"),
    (rm, "apply_manual_strokes", "apply_manual_strokes"),
    (zone_metrics, "disk_mask", "disk_mask"),
    (zone_metrics, "compute_blob_labels", "compute_blob_labels"),
    (rt, "detect_contour_mask", "detect_contour_mask"),
    (rt, "imread_unicode", "imread_unicode"),
    (rt, "contour_area", "contour_area"),
    (rt, "_bgr_to_qpixmap", "_bgr_to_qpixmap"),
    (rt.r_store, "save", "r_store.save"),
    (rt.RAnalysisTab, "_load_image", "tab._load_image"),
    (rt.RAnalysisTab, "_set_current_image", "tab._set_current_image"),
    (rt.RAnalysisTab, "_refresh_thumb_strip", "tab._refresh_thumb_strip"),
    (rt.RAnalysisTab, "_refresh_right_panel", "tab._refresh_right_panel"),
    (rt.RAnalysisTab, "_refresh_step_indicator", "tab._refresh_step_indicator"),
    (rt.RAnalysisTab, "_on_canvas_edited", "tab._on_canvas_edited"),
    (rt.RAnalysisTab, "_run_and_display_detection", "tab._run_and_display_detection"),
    (rt.RAnalysisTab, "_do_save", "tab._do_save"),
    (rcp.RCellPanel, "set_cell_status", "cell_panel.set_cell_status"),
    (iil.InferenceImageList, "_apply_display", "image_list._apply_display"),
]


def install_hooks() -> None:
    for owner, attr, label in HOOKS:
        orig = getattr(owner, attr, None)
        if orig is None:   # 성능 라운드로 삭제된 메서드는 건너뛴다(Zone 벤치와 같게)
            continue

        def wrapper(*a, _orig=orig, _label=label, **k):
            t0 = pc()
            try:
                return _orig(*a, **k)
            finally:
                s = STATS.setdefault(_label, [0, 0.0])
                s[0] += 1
                s[1] += pc() - t0
        setattr(owner, attr, wrapper)


def pump(n: int = 3) -> None:
    for _ in range(n):
        qapp.processEvents()


# 함수 단위 원인 특정이 필요한 시나리오만 cProfile 덤프(--profile-dir).
PROFILE = {
    "session_open", "cell_switch_to_50img", "image_switch_list_warm", "image_switch_list_cold",
    "brush_commit", "eraser_commit", "undo_brush", "undo_eraser", "blob_click_first",
    "delete_blob", "undo_delete", "threshold_change", "denominator_change", "opacity_step",
    "paint_repaint", "detect_current", "autosave", "autosave_50img_edited",
    "right_panel_refresh_100cells",
}


class Bench:
    def __init__(self, size: str, repeat: int, profile_dir: Path | None) -> None:
        self.size, self.repeat, self.profile_dir = size, repeat, profile_dir
        self.rows: dict[tuple[str, str], dict] = {}
        self._profiled: set[tuple[str, str]] = set()

    def t(self, fn, tag: tuple[str, str] | None = None) -> tuple[float, dict]:
        """fn() + 이벤트 처리(그리기 포함)까지의 시간(ms)과 함수별 (호출 수, ms) 증분."""
        prof = None
        if self.profile_dir and tag and tag[0] in PROFILE and tag not in self._profiled:
            self._profiled.add(tag)
            prof = cProfile.Profile()
        s0 = {k: tuple(v) for k, v in STATS.items()}
        t0 = pc()
        if prof:
            prof.enable()
        fn()
        pump()
        if prof:
            prof.disable()
        ms = (pc() - t0) * 1000
        if prof:
            buf = io.StringIO()
            pstats.Stats(prof, stream=buf).strip_dirs().sort_stats("cumulative").print_stats(22)
            (self.profile_dir / f"{self.size}_{tag[0]}_{tag[1]}.txt").write_text(
                f"# {tag[0]} {tag[1]} {self.size} — {ms:.1f} ms (프로파일러 오버헤드 포함)\n" + buf.getvalue(),
                encoding="utf-8")
        d = {}
        for k, v in STATS.items():
            c0, s_0 = s0.get(k, (0, 0.0))
            if v[0] != c0:
                d[k] = (v[0] - c0, (v[1] - s_0) * 1000)
        return ms, d

    def add(self, scenario: str, edits: str, samples: list[tuple[float, dict]], note: str = "") -> None:
        row = self.rows.setdefault((scenario, edits), {"samples": [], "agg": {}, "note": note})
        for ms, d in samples:
            row["samples"].append(ms)
            for k, (c, t_ms) in d.items():
                a = row["agg"].setdefault(k, [0, 0.0])
                a[0] += c
                a[1] += t_ms

    def measure(self, scenario: str, edits: str, op, setup=None, teardown=None,
                n: int | None = None, note: str = "") -> None:
        out = []
        for i in range(n or self.repeat):
            if setup:
                setup(i)
                pump()
            out.append(self.t(lambda: op(i), (scenario, edits)))
            if teardown:
                teardown(i)
                pump()
        self.add(scenario, edits, out, note)

    def results(self) -> list[dict]:
        out = []
        for (scenario, edits), row in self.rows.items():
            s = sorted(row["samples"])
            n = len(s)
            out.append({
                "scenario": scenario, "edits": edits, "size": self.size, "n": n,
                "median_ms": round(statistics.median(s), 2), "min_ms": round(s[0], 2),
                "max_ms": round(s[-1], 2), "note": row["note"],
                "samples_ms": [round(v, 2) for v in row["samples"]],
                # 샘플 1회당 평균 — calls가 1보다 크면 한 조작에서 중복 호출
                "breakdown": {k: {"calls": round(c / n, 2), "ms": round(t_ms / n, 2)}
                              for k, (c, t_ms) in sorted(row["agg"].items(), key=lambda kv: -kv[1][1])},
            })
        return out


# ── 픽스처 ──────────────────────────────────────────────────────────────────

def ensure_fixtures(base: Path, w: int, h: int, ext: str, n_small: int, n_large: int) -> Path:
    root = base / f"{w}x{h}_{ext}"
    a, b = root / "cellA", root / "cellB"
    if (len(list(a.glob(f"*.{ext}"))) == n_small and len(list(b.glob(f"*.{ext}"))) == n_large):
        return root
    fx, fy = w / 4000, h / 3000
    rng = np.random.default_rng(1)
    img = np.clip(60 + rng.integers(-6, 7, (h, w, 1)), 0, 255).astype(np.uint8).repeat(3, axis=2)
    for yy in range(500, 2800, 200):
        for xx in range(200, 3800, 200):
            img[int(yy * fy):int((yy + 100) * fy), int(xx * fx):int((xx + 100) * fx)] = 255
    ok, buf = cv2.imencode(f".{ext}", img, [cv2.IMWRITE_JPEG_QUALITY, 92] if ext == "jpg" else [])
    assert ok
    for d, n in ((a, n_small), (b, n_large)):
        d.mkdir(parents=True, exist_ok=True)
        for i in range(n):
            buf.tofile(str(d / f"img_{i + 1:02d}.{ext}"))
    return root


def write_session(path: Path, cells: dict[str, list[Path]], roi: list[int] | None) -> None:
    path.write_text(json.dumps({
        "version": 1, "threshold": 128, "denominator": 1000000.0, "spec_lower": 0.0, "spec_upper": 1.0,
        "auto_detect": roi is not None, "global_roi": roi,
        "cells": {cid: {"images": [{"path": str(p), "roi_override": None, "manual_strokes": [],
                                    "area": 0, "removed_blob_regions": []} for p in paths]}
                  for cid, paths in cells.items()},
    }, ensure_ascii=False), encoding="utf-8")


def new_tab(win: tuple[int, int]):
    tab = rt.RAnalysisTab()
    tab.resize(*win)
    tab.show()
    pump()
    QTest.qWait(30)
    pump()
    return tab


def close_tab(tab) -> None:
    tab._save_timer.stop()
    tab.close()
    tab.deleteLater()
    pump()


# ── 크기별 본 측정 ───────────────────────────────────────────────────────────

def run_size(w: int, h: int, args, profile_dir: Path | None) -> tuple[list[dict], dict]:
    size = f"{w}x{h}"
    fx, fy = w / 4000, h / 3000
    b = Bench(size, args.repeat, profile_dir)
    root = ensure_fixtures(Path(args.fixtures), w, h, args.ext, args.small, args.large)
    A = sorted((root / "cellA").glob(f"*.{args.ext}"))
    B = sorted((root / "cellB").glob(f"*.{args.ext}"))
    IMG_E30, IMG_E0, PARTNER = A[0], A[1], A[2]
    win = tuple(int(v) for v in args.window.split("x"))

    def P(x: float, y: float) -> tuple[float, float]:      # 4000x3000 기준 좌표 → 이 이미지의 원본 좌표
        return (x * fx, y * fy)

    roi_ref = ((100, 450), (3900, 2900))
    roi_xywh = [int(roi_ref[0][0] * fx), int(roi_ref[0][1] * fy),
                int((roi_ref[1][0] - roi_ref[0][0]) * fx), int((roi_ref[1][1] - roi_ref[0][1]) * fy)]

    # ── 세션 열기(새 탭마다 1회) — 첫 셀(cellA, 5장) 자동 선택 + 첫 이미지 로드·검출 + 썸네일 ──
    sess = root / "bench_session_open.json"
    write_session(sess, {"cellA": A, "cellB": B}, roi_xywh)
    out = []
    for _ in range(args.repeat):
        tab = new_tab(win)
        out.append(b.t(lambda: tab._load_session(sess), ("session_open", "e0")))
        assert tab._current_image_path == A[0], tab._current_image_path
        close_tab(tab)
    b.add("session_open", "e0", out, f"cells: {args.small}+{args.large}장, auto_detect+ROI")

    tab = new_tab(win)
    cv, dlg, il, strip = tab._canvas, tab._settings_dialog, tab._cell_panel._image_list, tab._thumb_strip
    sel_cell = tab._cell_panel._select_cell

    def spt(xy) -> QPoint:
        p = cv._orig_to_screen_point(*xy).toPoint()
        assert cv.rect().contains(p) and cv.childAt(p) is None, f"{xy} -> {p} 는 캔버스 밖이거나 플로팅 클러스터 아래"
        return p

    def set_tool(name: str) -> None:
        {"roi": tab._act_roi, "brush": tab._brush_tools.act_brush,
         "eraser": tab._brush_tools.act_eraser, "pan": tab._brush_tools.act_pan}[name].trigger()
        pump()

    def click(xy) -> None:
        QTest.mouseClick(cv, LEFT, pos=spt(xy))

    def key_delete() -> None:
        QTest.keyClick(cv, Qt.Key.Key_Delete)

    def ctrl_z() -> None:
        QTest.keyClick(cv, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)

    def list_click(path: Path) -> None:
        r = il._tree.visualItemRect(il._path_to_item[path])
        QTest.mouseClick(il._tree.viewport(), LEFT, pos=r.center())

    def thumb_click(path: Path) -> None:
        item = next(strip.item(i) for i in range(strip.count())
                    if strip.item(i).data(Qt.ItemDataRole.UserRole) == path)
        QTest.mouseClick(strip.viewport(), LEFT, pos=strip.visualItemRect(item).center())

    def goto(path: Path) -> None:
        if tab._current_image_path != path:
            list_click(path)
            pump()
        assert tab._current_image_path == path, (tab._current_image_path, path)

    def drag(scenario: str | None, edits: str, pts, release_scenario: str | None = None) -> None:
        """press → move마다 (이벤트 처리 + 그리기) 시간 → release 시간."""
        scr = [spt(p) for p in pts]
        QTest.mousePress(cv, LEFT, pos=scr[0])
        pump()
        moves = [b.t(lambda s=s: QTest.mouseMove(cv, s)) for s in scr[1:]]
        rel = b.t(lambda: QTest.mouseRelease(cv, LEFT, pos=scr[-1]),
                  (release_scenario, edits) if release_scenario else None)
        if scenario:
            b.add(scenario, edits, moves, "mouseMove 1회(그리기 포함)")
        if release_scenario:
            b.add(release_scenario, edits, [rel])

    def line(x0, y0, x1, y1, n):
        return [P(x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n) for k in range(n + 1)]

    rng = np.random.default_rng(0)

    def stroke_pts(i: int):      # 이전 검증자(probe_perf.py)와 같은 제스처: 12점, 30px 간격
        x, y = int(rng.integers(300, 3300)), int(rng.integers(700, 2700))
        return [P(x + 30 * k, y + (15 * k if i % 2 else 0)) for k in range(12)]

    def blob(k: int):            # y=500~600 행의 k번째 블랍 중심(스트로크가 닿지 않는 행)
        return P(250 + 200 * k, 550)

    def run_batch(btn) -> float:
        btn.click()
        wk = tab._detect_worker
        t0, last, gap = pc(), pc(), 0.0
        while (wk.isRunning() or tab._progress is not None) and pc() - t0 < 1800:
            QTest.qWait(5)
            gap, last = max(gap, pc() - last), pc()
        return gap * 1000

    # ── 폴더 가져오기 → 셀 전환 ─────────────────────────────────────────────
    QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: str(root))
    b.measure("import_folder", "e0", lambda i: tab._cell_panel._on_import_folder(), n=1,
              note=f"첫 가져오기(셀 2개, {args.small}+{args.large}장)")
    assert set(tab._cells) == {"cellA", "cellB"}
    b.measure(f"cell_switch_to_{args.large}img", "e0", lambda i: sel_cell("cellB"), setup=lambda i: sel_cell("cellA"))
    b.measure("right_panel_refresh", "e0", lambda i: tab._refresh_right_panel(), note=f"현재 셀 {args.large}행")
    b.measure(f"cell_switch_to_{args.small}img", "e0", lambda i: sel_cell("cellA"), setup=lambda i: sel_cell("cellB"))

    # ── 자동 검출 켜기 + ROI 생성(드래그) + 전역 지정 ────────────────────────
    goto(IMG_E0)
    dlg._chk_auto_detect.click()
    pump()
    drag("roi_create_move", "e0", line(*roi_ref[0], *roi_ref[1], 20), "roi_create_release")
    b.measure("roi_global_apply", "e0", lambda i: dlg._btn_roi_global.click())
    assert tab._session.get("global_roi") and tab._image_data(IMG_E0)["area"] > 0
    info = {"zoom": round(cv._zoom, 4), "canvas": [cv.width(), cv.height()],
            "detected_area_px": tab._image_data(IMG_E0)["area"]}

    def battery(edits: str, img: Path) -> None:
        """한 이미지 위에서 도는 조작 묶음 — 끝나면 편집 상태는 들어올 때와 같다."""
        goto(img)
        set_tool("roi")
        b.measure("paint_repaint", edits, lambda i: cv.repaint(), n=5)
        tab._act_overlay_visible.trigger()
        b.measure("paint_repaint_mask_hidden", edits, lambda i: cv.repaint(), n=5)
        tab._act_overlay_visible.trigger()
        b.measure("overlay_toggle", edits, lambda i: tab._act_overlay_visible.trigger(), n=4)
        v0 = tab._opacity_slider.value()
        vals = [10, 30, 50, 70, 100, v0]
        b.measure("opacity_step", edits, lambda i: tab._opacity_slider.setValue(vals[i % 6]), n=6)

        # ROI 이동/리사이즈(드래그 중 프레임, 놓을 때) — 끝나면 Ctrl+Z로 원위치
        drag("roi_move", edits, line(1150, 1450, 1450, 1450, 20), "roi_move_release")
        ctrl_z()
        drag("roi_resize", edits, line(3900, 2900, 3600, 2700, 20), "roi_resize_release")
        ctrl_z()
        pump()
        assert cv.get_roi() is not None and abs(cv.get_roi().width() - roi_xywh[2]) <= 2, cv.get_roi()

        # 줌(휠)·팬
        c = cv.rect().center()
        for d in (120,) * 5 + (-120,) * 5:
            ev = QWheelEvent(QPointF(c), QPointF(cv.mapToGlobal(c)), QPoint(0, 0), QPoint(0, d),
                             Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                             Qt.ScrollPhase.NoScrollPhase, False)
            b.add("zoom_wheel", edits, [b.t(lambda: QApplication.sendEvent(cv, ev))])
        cv._fit_view()
        set_tool("pan")
        drag("pan_move", edits, line(1150, 1450, 1650, 1750, 20))
        set_tool("roi")
        cv._fit_view()
        cv.update()
        pump()

        # 브러시/지우개: 드래그 중 프레임, 커밋, Ctrl+Z
        tab._brush_tools.spin_brush_size.setValue(40)
        for i in range(b.repeat):
            set_tool("brush")
            drag("brush_move", edits, stroke_pts(i), "brush_commit")
            b.add("undo_brush", edits, [b.t(ctrl_z, ("undo_brush", edits))])
        for i in range(b.repeat):
            set_tool("eraser")
            drag("eraser_move", edits, line(400, 950, 730, 950, 11), "eraser_commit")
            b.add("undo_eraser", edits, [b.t(ctrl_z, ("undo_eraser", edits))])
        set_tool("brush")     # 긴 스트로크 — 진행 중 스트로크 미리보기가 점 개수에 비례해 느려지는지
        scr = [spt(P(600 + 12 * k, 1450 + (40 if (k // 10) % 2 else 0))) for k in range(151)]
        QTest.mousePress(cv, LEFT, pos=scr[0])
        mv = [b.t(lambda s=s: QTest.mouseMove(cv, s)) for s in scr[1:]]
        QTest.mouseRelease(cv, LEFT, pos=scr[-1])
        pump()
        b.add("brush_move_long_first20", edits, mv[:20], "150 move 스트로크의 처음 20회")
        b.add("brush_move_long_last20", edits, mv[-20:], "150 move 스트로크의 마지막 20회")
        ctrl_z()
        pump()

        # 블랍 클릭 선택(편집 직후 첫 클릭 = 라벨맵 재계산 / 두 번째 = 캐시)
        for i in range(b.repeat):
            set_tool("brush")
            drag(None, edits, line(2000, 1450, 2330, 1450, 11))
            set_tool("roi")
            b.add("blob_click_first", edits, [b.t(lambda: click(blob(8)), ("blob_click_first", edits))])
            assert cv._selected_blob_id is not None
            b.add("blob_click_second", edits, [b.t(lambda: click(blob(9)))])
            ctrl_z()
            pump()

        # 블랍 Delete → Ctrl+Z
        for i in range(b.repeat):
            click(blob(i))
            pump()
            assert cv._selected_blob_id is not None
            b.add("delete_blob", edits, [b.t(key_delete, ("delete_blob", edits))])
            b.add("undo_delete", edits, [b.t(ctrl_z, ("undo_delete", edits))])

        # 설정 변경 — 디바운스(r_settings_panel._DEBOUNCE_MS=150ms) 대기는 빼고 핸들러(_on_settings_changed)만
        def set_thr(i):
            dlg._threshold_slider.setValue(120 + i)
            dlg._debounce.stop()
        b.measure("threshold_change", edits, lambda i: dlg.settings_changed.emit(), setup=set_thr,
                  note="디바운스 대기 제외")

        def set_den(i):
            dlg._denominator_spin.setValue(1000000.0 + i)
            dlg._debounce.stop()
        b.measure("denominator_change", edits, lambda i: dlg.settings_changed.emit(), setup=set_den,
                  note="디바운스 대기 제외 — 스펙 상/하한 변경도 같은 경로")
        dlg._threshold_slider.setValue(128)
        dlg._debounce.stop()
        dlg.settings_changed.emit()
        pump()
        tog = [b.t(dlg._chk_auto_detect.click) for _ in range(4)]
        b.add("auto_detect_off", edits, tog[0::2])
        b.add("auto_detect_on", edits, tog[1::2])
        assert dlg.auto_detect_enabled()
        b.measure("detect_current", edits, lambda i: tab._btn_detect_current.click())

        tab._session_path = root / "bench_autosave.json"     # 자동 저장 타이머가 부르는 _do_save 직접 호출
        b.measure("autosave", edits, lambda i: tab._do_save(), note="_do_save 1회(세션 전체 JSON + fsync)")
        tab._session_path = None

    # ── e0 ──────────────────────────────────────────────────────────────────
    def switch(scenario, edits, src, dst, how, cold=False):
        def setup(i):
            goto(src)
            if cold:
                tab._image_cache.pop(str(dst), None)
        b.measure(scenario, edits, lambda i: how(dst), setup=setup,
                  teardown=lambda i: (_ for _ in ()).throw(AssertionError(tab._current_image_path))
                  if tab._current_image_path != dst else None)

    switch("image_switch_list_warm", "e0", PARTNER, IMG_E0, list_click)
    switch("image_switch_list_cold", "e0", PARTNER, IMG_E0, list_click, cold=True)
    switch("image_switch_thumb", "e0", PARTNER, IMG_E0, thumb_click)
    switch("image_switch_nav", "e0", IMG_E0, PARTNER, lambda _p: tab._navigate(1))
    battery("e0", IMG_E0)
    assert not cv._manual_strokes and not cv._deleted_blob_regions
    gap = run_batch(tab._btn_detect_cell)       # 워밍업(파일 캐시)
    out = []
    for _ in range(b.repeat):
        out.append(b.t(lambda: out.append(None) or run_batch(tab._btn_detect_cell)))
        out.remove(None)
    b.add(f"batch_cell_{args.small}img", "e0", out, "워커 스레드 + 종료 후 메인 스레드 갱신까지")
    gaps = []
    out = [b.t(lambda: gaps.append(run_batch(tab._btn_detect_all))) for _ in range(args.batch_repeat)]
    b.add(f"batch_all_{args.small + args.large}img", "e0", out, f"일괄 중 UI 최대 멈춤 {max(gaps):.0f} ms")

    # ── e30 만들기: 스트로크 30개(커밋 시간 수집) + 삭제 3개 ──────────────────
    goto(IMG_E30)
    tab._brush_tools.spin_brush_size.setValue(40)
    set_tool("brush")
    for i in range(30):
        drag("brush_move_build30", "e0→e30", stroke_pts(i), "brush_commit_build30")
    set_tool("roi")
    assert len(cv._manual_strokes) == 30
    info["e30_stroke_points"] = sum(len(s[1]) for s in cv._manual_strokes)
    battery("e30", IMG_E30)      # 삭제 0개 상태에서 delete/undo 쌍 측정 → 아래에서 3개 확정
    for k in (3, 4, 5):
        click(blob(k))
        pump()
        b.add("delete_blob_kept", "e30", [b.t(key_delete)], "삭제 누적 1→3개째")
    assert len(cv._manual_strokes) == 30 and len(cv._deleted_blob_regions) == 3
    info["e30_area_px"] = tab._image_data(IMG_E30)["area"]

    switch("image_switch_list_warm", "e30", PARTNER, IMG_E30, list_click)
    switch("image_switch_list_cold", "e30", PARTNER, IMG_E30, list_click, cold=True)
    switch("image_switch_away", "e30", IMG_E30, PARTNER, list_click)
    goto(IMG_E30)
    b.measure("paint_repaint", "e30+del3", lambda i: cv.repaint(), n=5)
    out = [b.t(lambda: run_batch(tab._btn_detect_cell)) for _ in range(b.repeat)]
    b.add(f"batch_cell_{args.small}img", "e30", out, "편집(e30+삭제3)은 1장만")

    # 셀 B 전 이미지에 같은 편집을 주입 → 세션 JSON이 커졌을 때의 자동 저장
    strokes = list(cv._manual_strokes)
    for p in B:
        tab._image_data(p)["manual_strokes"] = strokes
    tab._session_path = root / "bench_autosave.json"
    b.measure(f"autosave_{args.large}img_edited", "e30", lambda i: tab._do_save(),
              note=f"{args.large}장 모두 스트로크 30개")
    info["session_json_kb"] = round(tab._session_path.stat().st_size / 1024)
    tab._session_path = None
    close_tab(tab)
    return b.results(), info


def run_many_cells(args, profile_dir: Path | None) -> list[dict]:
    """셀 100개(셀당 5장, 64x64) — 우측 패널/셀 목록 갱신처럼 이미지 크기와 무관한 위젯 비용."""
    b = Bench("100cells", args.repeat, profile_dir)
    root = Path(args.fixtures) / "many_cells"
    cells = {}
    img = np.full((64, 64, 3), 60, np.uint8)
    for c in range(100):
        d = root / f"cell_{c:03d}"
        d.mkdir(parents=True, exist_ok=True)
        cells[d.name] = [d / f"img_{i}.png" for i in range(5)]
        for p in cells[d.name]:
            if not p.exists():
                cv2.imencode(".png", img)[1].tofile(str(p))
    sess = root / "session.json"
    write_session(sess, cells, [4, 4, 56, 56])
    win = tuple(int(v) for v in args.window.split("x"))
    out = []
    for _ in range(args.repeat):
        tab = new_tab(win)
        out.append(b.t(lambda: tab._load_session(sess)))
        close_tab(tab)
    b.add("session_open_100cells", "e0", out)
    tab = new_tab(win)
    tab._load_session(sess)
    pump()
    b.measure("right_panel_refresh_100cells", "e0", lambda i: tab._refresh_right_panel(),
              note="브러시 커밋·삭제·undo·검출마다 1회 이상 호출됨")
    tab._session_path = root / "autosave.json"
    b.measure("autosave_100cells", "e0", lambda i: tab._do_save())
    tab._session_path = None
    close_tab(tab)
    return b.results()


# ── 출력 ────────────────────────────────────────────────────────────────────

def table(results: list[dict], before: list[dict] | None = None) -> str:
    sizes = list(dict.fromkeys(r["size"] for r in results))
    keys = list(dict.fromkeys((r["scenario"], r["edits"]) for r in results))
    cur = {(r["scenario"], r["edits"], r["size"]): r["median_ms"] for r in results}
    old = {(r["scenario"], r["edits"], r["size"]): r["median_ms"] for r in before or []}
    lines = ["| 시나리오 | 편집 | " + " | ".join(sizes) + " |", "|---|---|" + "---:|" * len(sizes)]
    for sc, ed in keys:
        cells = []
        for s in sizes:
            v = cur.get((sc, ed, s))
            if v is None:
                cells.append("-")
            elif (sc, ed, s) in old and v > 0:
                cells.append(f"{old[(sc, ed, s)]:.1f} → {v:.1f} (×{old[(sc, ed, s)] / v:.1f})")
            else:
                cells.append(f"{v:.1f}")
        lines.append(f"| {sc} | {ed} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default="bench_r_tab.json")
    ap.add_argument("--sizes", default="1920x1200,4000x3000,5472x3648")
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--batch-repeat", type=int, default=1, help="전체 일괄 검출(가장 긴 시나리오) 반복 수")
    ap.add_argument("--small", type=int, default=5, help="cellA 이미지 수")
    ap.add_argument("--large", type=int, default=50, help="cellB 이미지 수")
    ap.add_argument("--ext", default="jpg", help="픽스처 이미지 형식(jpg/png/bmp) — 디코드 비용이 달라진다")
    ap.add_argument("--window", default="1920x1040", help="탭 위젯 크기")
    ap.add_argument("--fixtures", default=str(Path(tempfile.gettempdir()) / "bench_r_tab_fixtures"))
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
    for s in args.sizes.split(","):
        w, h = (int(v) for v in s.split("x"))
        print(f"[bench] {s} ...", flush=True)
        r, infos[s] = run_size(w, h, args, profile_dir)
        results += r
        print(f"[bench] {s} done ({pc() - t0:.0f}s) {infos[s]}", flush=True)
    results += run_many_cells(args, profile_dir)
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
