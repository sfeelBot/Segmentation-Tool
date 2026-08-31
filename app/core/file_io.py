"""공용 파일 쓰기 헬퍼 — 재시도 + 원자적 쓰기 (GitHub #16 후속).

백신/OneDrive/탐색기 미리보기 등 일시적 파일 잠금(PermissionError) 대응.
CLAUDE.md 원칙대로 core 모듈은 예외를 삼키지 않는다 — 마지막 시도까지 실패하면
원래 예외를 그대로 raise한다."""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from typing import Callable, TypeVar

T = TypeVar("T")

_DEFAULT_ATTEMPTS = 3
_DEFAULT_DELAY = 0.3   # 100ms→300ms→900ms 백오프는 호출부에서 필요 시 조정


def retry_on_permission_error(
    write_fn: Callable[[], T],
    *, attempts: int = _DEFAULT_ATTEMPTS, delay: float = _DEFAULT_DELAY,
) -> T:
    """write_fn()을 실행. PermissionError만 재시도(백신/탐색기 미리보기/OneDrive 등
    일시적 잠금 대응) — 다른 예외나 마지막 시도 실패는 그대로 raise한다."""
    for i in range(attempts):
        try:
            return write_fn()
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(delay)
    raise AssertionError("attempts must be >= 1")   # 도달 불가 (attempts>=1 전제)


def atomic_write(
    path: Path, write_fn: Callable[[Path], None],
    *, attempts: int = _DEFAULT_ATTEMPTS, delay: float = _DEFAULT_DELAY,
) -> None:
    """write_fn(temp_path)로 path와 같은 디렉터리에 임시 파일을 쓴 뒤 fsync,
    retry_on_permission_error로 감싼 os.replace(temp_path, path)로 교체한다.
    중간에 실패하면 temp 파일을 정리하고 원래 예외를 그대로 raise한다
    (annotation_store.set_ok_and_clear_annotations()의 기존 temp+replace 패턴을 일반화).

    temp 파일이 path와 같은 디렉터리에 생성되므로 os.replace가 항상 같은
    파일시스템 내 원자적 rename이 된다(다른 드라이브로 인한 실패 없음)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    os.close(fd)
    try:
        write_fn(temp_path)
        fsync_fd = os.open(temp_path, os.O_RDWR)
        try:
            os.fsync(fsync_fd)
        finally:
            os.close(fsync_fd)
        retry_on_permission_error(
            lambda: os.replace(temp_path, path), attempts=attempts, delay=delay,
        )
    except Exception:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
