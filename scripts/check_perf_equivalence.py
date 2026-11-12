"""성능 개선(docs/specs/perf-2026-11-11-design.md) 결과 동일성 셀프체크.

개선 전(`0704bd6`) 함수 본문을 아래 `_old_*`로 그대로 복사해 고정하고, 현재 앱 함수와
무작위 입력에서 결과가 완전히 같은지 비교한다. 실패하면 1로 종료.

    python scripts/check_perf_equivalence.py
"""
from __future__ import annotations

import os
import random
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import cv2
import numpy as np
from PIL import Image
from PyQt6.QtGui import QImage

from app.core import inference_engine as ie
from app.core import r_analysis_metrics as rm
from app.core import zone_metrics as zm
from app.core.inference_engine import BlobStat
from app.core.zone_metrics import compute_blob_labels, disk_mask


# ── 개선 전 함수 복사본 (수정 금지) ────────────────────────────────────────────

def _old_apply_manual_strokes(mask, manual_strokes):
    result = mask.copy()
    for draw, stroke in manual_strokes:
        stroke_mask = np.zeros(mask.shape, dtype=bool)
        for cx, cy, r in stroke:
            stroke_mask |= disk_mask(cx, cy, r, mask.shape)
        result[stroke_mask] = draw
    return result


def _old_zone_apply_edits(mask, manual_strokes, removed_blob_ids=(), removed_points=(), labels=None):
    ai_mask = mask
    if removed_blob_ids:
        if labels is None:
            labels, _, _ = compute_blob_labels(mask)
        ai_mask = mask & ~np.isin(labels, list(removed_blob_ids))
    by_n: dict = {}
    for x, y, n in removed_points:
        by_n.setdefault(min(max(int(n), 0), len(manual_strokes)), []).append((int(x), int(y)))
    if not by_n:
        return ai_mask, _old_apply_manual_strokes(ai_mask, manual_strokes)
    ai_mask = ai_mask.astype(bool)
    h, w = mask.shape
    final, start = ai_mask, 0
    for n in sorted(by_n):
        final = _old_apply_manual_strokes(final, manual_strokes[start:n])
        start = n
        u8 = final.view(np.uint8)
        for x, y in by_n[n]:
            if not (0 <= x < w and 0 <= y < h) or not final[y, x]:
                continue
            _, _, _, (bx, by, bw, bh) = cv2.floodFill(u8, None, (x, y), 2, flags=4)
            gone = u8[by:by + bh, bx:bx + bw] == 2
            final[by:by + bh, bx:bx + bw][gone] = False
            ai_mask[by:by + bh, bx:bx + bw][gone] = False
    return ai_mask, _old_apply_manual_strokes(final, manual_strokes[start:])


def _old_r_apply_edits(mask, manual_strokes, removed_regions):
    by_n: dict = {}
    for x, y, w, h, *rest in removed_regions:
        n = min(max(int(rest[0]), 0), len(manual_strokes)) if rest else 0
        by_n.setdefault(n, []).append((x, y, w, h))
    result, start = mask, 0
    for n in sorted(by_n):
        result = _old_apply_manual_strokes(result, manual_strokes[start:n])
        result &= ~rm.regions_mask(mask.shape, by_n[n])
        start = n
    return _old_apply_manual_strokes(result, manual_strokes[start:])


def _old_compute_blobs_and_filter(class_map, confidence_map, classes, min_confidence, min_pixel_size):
    filtered = class_map
    blobs = []
    name_by_id = {c.class_id: c.name for c in classes}
    blob_id = 1
    for cid in (int(c) for c in np.unique(class_map)):
        if cid == 0:
            continue
        mask = (class_map == cid).astype(np.uint8)
        n_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
        if n_labels <= 1:
            continue
        flat_labels = labels.ravel()
        flat_conf = confidence_map.ravel().astype(np.float64)
        cnt = np.bincount(flat_labels, minlength=n_labels)
        sum_conf = np.bincount(flat_labels, weights=flat_conf, minlength=n_labels)
        mean_per_label = sum_conf / np.maximum(cnt, 1)
        min_per_label = np.full(n_labels, np.inf)
        np.minimum.at(min_per_label, flat_labels, flat_conf)
        max_per_label = np.full(n_labels, -np.inf)
        np.maximum.at(max_per_label, flat_labels, flat_conf)
        reject_labels = []
        for lbl in range(1, n_labels):
            pixel_count = int(stats[lbl, cv2.CC_STAT_AREA])
            mean_conf = float(mean_per_label[lbl])
            if mean_conf < min_confidence or pixel_count < min_pixel_size:
                reject_labels.append(lbl)
                continue
            cx, cy = centroids[lbl]
            blobs.append(BlobStat(
                blob_id=blob_id, class_id=cid, class_name=name_by_id.get(cid, f"class_{cid}"),
                pixel_count=pixel_count, mean_confidence=mean_conf,
                min_confidence=float(min_per_label[lbl]), max_confidence=float(max_per_label[lbl]),
                centroid_x=float(cx), centroid_y=float(cy),
                bbox_x=int(stats[lbl, cv2.CC_STAT_LEFT]), bbox_y=int(stats[lbl, cv2.CC_STAT_TOP]),
                bbox_w=int(stats[lbl, cv2.CC_STAT_WIDTH]), bbox_h=int(stats[lbl, cv2.CC_STAT_HEIGHT]),
            ))
            blob_id += 1
        if reject_labels:
            if filtered is class_map:
                filtered = class_map.copy()
            filtered[np.isin(labels, reject_labels)] = 0
    return filtered, blobs


def _old_colorize_and_blend(orig, class_map, cls_map, opacity):
    h, w = class_map.shape
    max_dim = max(h, w)
    if max_dim > ie._MAX_OVERLAY_DIM:
        scale = ie._MAX_OVERLAY_DIM / max_dim
        w, h = max(1, round(class_map.shape[1] * scale)), max(1, round(class_map.shape[0] * scale))
        class_map_work = np.array(
            Image.fromarray(class_map.astype(np.uint8)).resize((w, h), Image.NEAREST), dtype=np.int64,
        )
    else:
        class_map_work = class_map
    color_img = np.zeros((h, w, 3), dtype=np.uint8)
    for cid, cls in cls_map.items():
        color_img[class_map_work == cid] = cls.color
    orig_np = np.array(orig.resize((w, h), Image.BILINEAR), dtype=np.uint8)
    blended = orig_np.copy()
    foreground = class_map_work != 0
    blended[foreground] = (
        orig_np[foreground] * (1 - opacity) + color_img[foreground] * opacity
    ).clip(0, 255).astype(np.uint8)
    return QImage(blended.tobytes(), w, h, w * 3, QImage.Format.Format_RGB888)


# ── 비교 ─────────────────────────────────────────────────────────────────────

_fail = 0


def _check(ok: bool, what: str) -> None:
    global _fail
    if not ok:
        _fail += 1
        print(f"FAIL: {what}")


def _rand_strokes(rng: random.Random, h: int, w: int) -> list:
    strokes = []
    for _ in range(rng.randint(0, 8)):
        n = rng.choice([0, 1, 3, 20, 80])
        r = rng.choice([0, 0.5, 1, 3.7, 12, 40])
        x, y = rng.uniform(-30, w + 30), rng.uniform(-30, h + 30)
        pts = []
        for _ in range(n):
            x += rng.uniform(-6, 6); y += rng.uniform(-6, 6)
            pts.append((x if rng.random() < .5 else round(x), y, r))
        strokes.append((rng.random() < .6, pts))
    return strokes


def check_strokes_and_edits() -> int:
    rng = random.Random(1)
    nrng = np.random.default_rng(1)
    cases = 0
    for h, w in ((37, 53), (120, 200), (301, 157)):
        for i in range(60):
            mask = nrng.random((h, w)) < nrng.choice([0.05, 0.3, 0.7])
            if i % 10 == 0:
                mask = mask.astype(np.uint8)
            strokes = _rand_strokes(rng, h, w)
            _check(np.array_equal(_old_apply_manual_strokes(mask, strokes), zm.apply_manual_strokes(mask, strokes))
                   and zm.apply_manual_strokes(mask, strokes).dtype == mask.dtype, f"apply_manual_strokes {h}x{w} #{i}")
            bmask = mask.astype(bool)
            pts = [(rng.randrange(-2, w + 2), rng.randrange(-2, h + 2), rng.randint(-1, len(strokes) + 1))
                   for _ in range(rng.randint(0, 5))]
            ids = rng.sample(range(1, 30), rng.randint(0, 3))
            old = _old_zone_apply_edits(bmask, strokes, ids, pts)
            new = zm.apply_edits(bmask, strokes, ids, pts)
            _check(all(np.array_equal(a, b) for a, b in zip(old, new)), f"zone apply_edits {h}x{w} #{i}")
            regions = [(rng.uniform(-5, w), rng.uniform(-5, h), rng.uniform(0, 40), rng.uniform(0, 40),
                        *([rng.randint(-1, len(strokes) + 1)] if rng.random() < .7 else []))
                       for _ in range(rng.randint(0, 4))]
            _check(np.array_equal(_old_r_apply_edits(bmask, strokes, regions), rm.apply_edits(bmask, strokes, regions)),
                   f"r apply_edits {h}x{w} #{i}")
            _check(int(bmask.sum()) == rm.contour_area(bmask), f"contour_area #{i}")
            zone = disk_mask(w / 2, h / 2, min(h, w) / 3, (h, w))
            _check(int(zone.sum()) and abs(zm.zone_stats(zone, mask) - (int((zone & mask).sum()) / int(zone.sum()) * 100.0)) == 0,
                   f"zone_stats #{i}")
            cases += 1
    _check(np.array_equal(zm.apply_manual_strokes(np.zeros((5, 5), bool), []), np.zeros((5, 5), bool)), "empty list")
    return cases


def check_blobs_filter() -> int:
    nrng = np.random.default_rng(2)
    classes = [ie.ClassDef(1, "a", (255, 0, 0)), ie.ClassDef(2, "b", (0, 255, 0))]
    cases = 0
    for h, w, nblob in ((40, 60, 10), (200, 300, 500), (97, 131, 50)):
        for _ in range(20):
            cm = np.zeros((h, w), np.int64)
            for _ in range(nblob):
                y, x = nrng.integers(-3, h), nrng.integers(-3, w)
                cm[max(0, y):y + nrng.integers(1, 9), max(0, x):x + nrng.integers(1, 9)] = nrng.integers(1, 3)
            conf = nrng.random((h, w)).astype(np.float32)
            for mc, mp in ((0.0, 0), (0.5, 3), (0.45, 10)):
                old = _old_compute_blobs_and_filter(cm, conf, classes, mc, mp)
                new = ie._compute_blobs_and_filter(cm, conf, classes, mc, mp)
                _check(np.array_equal(old[0], new[0]) and old[1] == new[1], f"blobs_filter {h}x{w} {mc} {mp}")
                cases += 1
    return cases


def _new_colorize_and_blend(orig, class_map, cls_map, opacity):
    if hasattr(ie, "_colorize_layer"):
        work, color_img, fg, (w, h) = ie._colorize_layer(class_map, cls_map)
        orig_np = np.array(orig.resize((w, h), Image.BILINEAR), dtype=np.uint8)
        return ie._blend(orig_np, color_img, fg, opacity, w, h)
    return ie._colorize_and_blend(orig, class_map, cls_map, opacity)


def _qbytes(q: QImage) -> bytes:
    p = q.constBits()
    p.setsize(q.sizeInBytes())
    return bytes(p)


def check_colorize() -> int:
    nrng = np.random.default_rng(3)
    cls_map = {1: ie.ClassDef(1, "a", (255, 0, 0)), 2: ie.ClassDef(2, "b", (10, 200, 30))}
    cases = 0
    for h, w in ((50, 71), (2100, 1300)):
        cm = nrng.integers(0, 3, (h, w)).astype(np.int64)
        orig = Image.fromarray(nrng.integers(0, 256, (h, w, 3), dtype=np.uint8))
        for op in (0.0, 0.3, 0.5):
            a = _old_colorize_and_blend(orig, cm, cls_map, op)
            b = _new_colorize_and_blend(orig, cm, cls_map, op)
            c = ie._colorize_and_blend(orig, cm, cls_map, op)
            _check(_qbytes(a) == _qbytes(b) == _qbytes(c), f"colorize {h}x{w} op={op}")
            cases += 1
    return cases


def check_zone_tab_cache_sequence() -> int:
    """perf D3/D6/D15: offscreen Zone 탭에서 편집·Undo·class_map 교체·타겟 변경·원 변경을 섞어
    돌리며 매 단계 캐시 결과를 직접 계산(`apply_edits`, `zone_blob_stats`, `zones_from_circles`)과 비교."""
    from PyQt6.QtWidgets import QApplication
    from app.tabs.zone_analysis_tab import ZoneAnalysisTab
    app = QApplication.instance() or QApplication([])  # noqa: F841
    rng = random.Random(4)
    nrng = np.random.default_rng(4)
    tab = ZoneAnalysisTab()
    canvas = tab._canvas
    h, w = 90, 120

    def new_result():
        cm = np.zeros((h, w), np.int64)
        for _ in range(12):
            y, x = int(nrng.integers(0, h - 8)), int(nrng.integers(0, w - 8))
            cm[y:y + int(nrng.integers(2, 9)), x:x + int(nrng.integers(2, 9))] = int(nrng.integers(1, 3))
        return type("Result", (), {"class_map": cm, "raw_class_map": cm,
                                   "confidence_map": nrng.random((h, w)).astype(np.float32),
                                   "overlay_image": QImage(w, h, QImage.Format.Format_RGB888)})()

    def reset_target(cid):
        tab._target_class_id = cid
        labels, stats, _ = compute_blob_labels(tab._last_result.class_map == cid)
        canvas.set_blob_data(labels, stats)

    steps = 0
    tab._last_result = new_result()
    reset_target(1)
    for i in range(120):
        op = rng.choice(["stroke", "stroke", "delete", "undo", "swap", "target", "circle", "none"])
        if op == "stroke":
            canvas._push_undo()
            canvas._manual_strokes.append((rng.random() < .6, [(rng.uniform(0, w), rng.uniform(0, h), rng.choice([1, 3, 6]))
                                                              for _ in range(rng.randint(1, 6))]))
            canvas._edit_rev += 1   # mouseReleaseEvent와 같은 갱신
        elif op == "delete":
            canvas._push_undo()
            canvas._removed_points.append((rng.randrange(w), rng.randrange(h), len(canvas._manual_strokes)))
            canvas._edit_rev += 1   # _handle_blob_click과 같은 갱신
        elif op == "undo" and canvas.can_undo():
            canvas.undo()
        elif op == "swap":
            tab._last_result = new_result()
            reset_target(tab._target_class_id)
        elif op == "target":
            reset_target(3 - tab._target_class_id)
        elif op == "circle":
            canvas.set_circles([(w / 2, h / 2, r) for r in sorted(rng.sample([10, 20, 30, 45], rng.randint(0, 3)))])
        target = tab._last_result.class_map == tab._target_class_id
        exp = zm.apply_edits(target, canvas._manual_strokes, canvas._removed_blob_ids, canvas._removed_points,
                             canvas._blob_labels)
        got = tab._ai_and_final_masks()
        _check(all(np.array_equal(a, b) for a, b in zip(exp, got)), f"zone tab masks step {i} ({op})")
        circles_raw = canvas.circles_with_ids()
        exp_zones = zm.zones_from_circles([zm.Circle(*c) for c in circles_raw], (h, w))
        got_zones = tab._zones_for(circles_raw, (h, w))
        _check(len(exp_zones) == len(got_zones) and all(
            a.name == b.name and a.hidden == b.hidden and np.array_equal(a.mask, b.mask)
            for a, b in zip(exp_zones, got_zones)), f"zone tab zones step {i}")
        exp_stats = zm.zone_blob_stats(exp_zones, exp[0], exp[1], tab._last_result.confidence_map)
        _check(tab._zone_blob_stats(got_zones, *got) == exp_stats, f"zone tab blob stats step {i}")
        _check(np.array_equal(tab._final_labels(got[1]), compute_blob_labels(exp[1])[0]), f"zone tab labels step {i}")
        steps += 1
    tab.close()
    return steps


if __name__ == "__main__":
    n1 = check_strokes_and_edits()
    n2 = check_blobs_filter()
    n3 = check_colorize()
    n4 = check_zone_tab_cache_sequence()
    print(f"cases: strokes/edits {n1}, blobs_filter {n2}, colorize {n3}, zone tab cache steps {n4} — fail {_fail}")
    sys.exit(1 if _fail else 0)
