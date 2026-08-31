"""GitHub #16 후속 — 재시도/원자적 쓰기 공용 헬퍼(app/core/file_io.py) 회귀 테스트."""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.file_io import atomic_write, retry_on_permission_error


def test_retry_recovers_from_transient_permission_error() -> None:
    calls = {"n": 0}

    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError("locked")
        return "ok"

    assert retry_on_permission_error(flaky, delay=0.01) == "ok"
    assert calls["n"] == 3


def test_retry_raises_original_exception_after_exhausting_attempts() -> None:
    def always_locked() -> None:
        raise PermissionError("still locked")

    with pytest.raises(PermissionError, match="still locked"):
        retry_on_permission_error(always_locked, attempts=2, delay=0.01)


def test_retry_does_not_swallow_other_exceptions() -> None:
    def boom() -> None:
        raise ValueError("not a lock")

    with pytest.raises(ValueError):
        retry_on_permission_error(boom, attempts=3, delay=0.01)


def test_atomic_write_replaces_file_and_leaves_no_temp_behind(tmp_path: Path) -> None:
    target = tmp_path / "doc.json"
    target.write_text("old", encoding="utf-8")

    atomic_write(target, lambda p: p.write_text("new", encoding="utf-8"))

    assert target.read_text(encoding="utf-8") == "new"
    assert not list(tmp_path.glob("*.tmp"))


def test_atomic_write_leaves_original_intact_and_cleans_temp_on_failure(tmp_path: Path) -> None:
    target = tmp_path / "doc.json"
    target.write_text("old", encoding="utf-8")

    def boom(_p: Path) -> None:
        raise ValueError("write failed")

    with pytest.raises(ValueError):
        atomic_write(target, boom)

    assert target.read_text(encoding="utf-8") == "old"
    assert not list(tmp_path.glob("*.tmp"))


def test_atomic_write_recovers_from_real_file_lock_held_by_another_thread(tmp_path: Path) -> None:
    """다른 스레드가 대상 파일을 짧게 열고 있다가 놓는 실제 잠금 상황을 재현해
    atomic_write의 재시도가 실제로 복구하는지 확인한다 (Windows: 파일이 열려있는 동안
    os.replace는 PermissionError를 낸다 — GitHub #16)."""
    target = tmp_path / "locked.json"
    target.write_text("old", encoding="utf-8")

    def hold_lock_briefly() -> None:
        with open(target, "r+b"):
            time.sleep(0.25)

    locker = threading.Thread(target=hold_lock_briefly)
    locker.start()
    time.sleep(0.05)   # 락 스레드가 먼저 파일을 열도록 대기

    try:
        atomic_write(target, lambda p: p.write_text("new", encoding="utf-8"), delay=0.15)
    finally:
        locker.join()

    assert target.read_text(encoding="utf-8") == "new"
    assert not list(tmp_path.glob("*.tmp"))


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
