"""캔버스 렌더링 병목 측정용 퍼포먼스 프로파일러.

30 프레임마다 각 단계의 평균·최대 소요 시간을 app.log(INFO) + data/logs/perf.log 에 기록.
"""
from __future__ import annotations

import time
from collections import defaultdict
from pathlib import Path

from app.core.logger import get_logger

log = get_logger("perf")

PERF_LOG  = Path("data/logs/perf.log")
LOG_EVERY = 30   # N 프레임마다 리포트


class PerfProfiler:
    """thread-safe 하지 않으므로 메인 스레드(렌더링)에서만 호출."""

    def __init__(self) -> None:
        self._times: dict[str, list[float]] = defaultdict(list)
        self._frame = 0
        self._last_report = time.perf_counter()
        self.ctx: dict = {}
        self.disk_log: bool = False   # True 로 설정하면 perf.log 에 기록

    # ── 타이밍 API ────────────────────────────────────────────────────────────

    def mark(self, name: str) -> float:
        """현재 시각 반환. end(name, t0) 와 쌍으로 사용."""
        return time.perf_counter()

    def end(self, name: str, t0: float) -> None:
        self._times[name].append((time.perf_counter() - t0) * 1000)  # ms

    # ── 프레임 카운터 ─────────────────────────────────────────────────────────

    def tick(self) -> None:
        """paintEvent 끝에 호출."""
        self._frame += 1
        if self._frame % LOG_EVERY == 0:
            self._report()

    # ── 리포트 ────────────────────────────────────────────────────────────────

    def _report(self) -> None:
        now  = time.perf_counter()
        fps  = LOG_EVERY / max(now - self._last_report, 1e-9)
        self._last_report = now

        ctx = self.ctx
        lines = [
            f"━━ Frame #{self._frame:,}  FPS={fps:.1f}  "
            f"img={ctx.get('img_w',0)}×{ctx.get('img_h',0)}  "
            f"zoom={ctx.get('zoom',0):.2f}  "
            f"anns={ctx.get('n_anns',0)}  "
            f"ov_scale={ctx.get('ov_scale',1):.2f}"
        ]
        order = [
            "paintEvent_total",
            "blit_image",
            "blit_overlay",
            "overlay_rebuild",
            "draw_brush_layer",
            "resolve_bbox_overlap",
            "consolidate_region",
            "load_image_pixmap",
            "load_image_total",
            "get_display_pixmap",
        ]
        printed = set()
        for name in order:
            if name in self._times:
                self._fmt_row(lines, name)
                printed.add(name)
        for name in sorted(self._times):
            if name not in printed:
                self._fmt_row(lines, name)

        lines.append(f"  ※ 가장 느린 단계가 최적화 대상입니다.")
        msg = "\n".join(lines)
        log.info(msg)
        # 파일 쓰기는 명시적으로 활성화한 경우에만 (기본 비활성 — I/O 절감)
        if self.disk_log:
            try:
                PERF_LOG.parent.mkdir(parents=True, exist_ok=True)
                with PERF_LOG.open("a", encoding="utf-8") as f:
                    from datetime import datetime
                    f.write(f"\n[{datetime.now().strftime('%H:%M:%S')}]\n{msg}\n")
            except Exception:
                pass

        self._times.clear()

    def _fmt_row(self, lines: list, name: str) -> None:
        vals = self._times[name]
        if not vals:
            return
        avg = sum(vals) / len(vals)
        mx  = max(vals)
        n   = len(vals)
        bar = "█" * min(40, int(avg / 5)) or "▏"
        lines.append(f"  {name:<28s} avg={avg:6.1f}ms  max={mx:6.1f}ms  n={n:3d}  {bar}")


# 앱 전역 싱글턴
profiler = PerfProfiler()
