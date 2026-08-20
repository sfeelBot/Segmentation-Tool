"""프로젝트 전체 내보내기(export) — 압축 대상 파일 목록 산출 (Qt 비의존).

`images/`(`.thumbs/` 캐시 제외), `annotations/`, `classes.json`, `project.json`은
항상 포함하고, `checkpoints/`, `user_models/`는 옵션으로 포함한다.
실제 zip 압축(파일 I/O)은 `app/widgets/project_export_dialog.py`의
`_ProjectExportWorker.run()`에서 수행한다 — 이 모듈은 "무엇을 담을지"만 계산한다.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from app.core.project import Project

_SANITIZE_RE = re.compile(r'[<>:"/\\|?*]')

# images/ 하위에서 제외할 디렉토리명 (썸네일 캐시 — 재생성 가능)
_EXCLUDED_DIR_NAMES = {".thumbs"}


def collect_export_entries(
    project: Project,
    include_checkpoints: bool = False,
    include_user_models: bool = True,
) -> list[tuple[Path, str]]:
    """압축에 포함할 (절대경로, zip 내부 arcname) 튜플 목록을 반환.

    zip 루트에 `images/`, `annotations/`, `classes.json`, `project.json`
    (옵션에 따라 `checkpoints/`, `user_models/`)이 그대로 위치하도록 arcname을
    구성한다 — 추후 가져오기(import) 시 압축 해제 결과가 곧 프로젝트 폴더 구조와
    동일해야 하기 때문.
    """
    entries: list[tuple[Path, str]] = []

    entries.extend(_walk_dir(project.images_dir, "images", exclude_dirs=_EXCLUDED_DIR_NAMES))
    entries.extend(_walk_dir(project.annotations_dir, "annotations"))

    if project.classes_file.exists():
        entries.append((project.classes_file, "classes.json"))
    if project.meta_file.exists():
        entries.append((project.meta_file, "project.json"))

    if include_checkpoints:
        entries.extend(_walk_dir(project.checkpoints_dir, "checkpoints"))
    if include_user_models:
        entries.extend(_walk_dir(project.user_models_dir, "user_models"))

    return entries


def default_export_filename(project: Project) -> str:
    """`{project_name}_{yyyymmdd}.zip` 형태의 기본 파일명."""
    safe = _SANITIZE_RE.sub("_", project.name).strip().strip(".") or "project"
    return f"{safe}_{datetime.now():%Y%m%d}.zip"


def _walk_dir(
    root: Path, arc_prefix: str, exclude_dirs: set[str] | None = None,
) -> list[tuple[Path, str]]:
    if not root.exists() or not root.is_dir():
        return []
    exclude_dirs = exclude_dirs or set()
    out: list[tuple[Path, str]] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(part in exclude_dirs for part in rel.parts[:-1]):
            continue
        out.append((p, f"{arc_prefix}/{rel.as_posix()}"))
    return out
