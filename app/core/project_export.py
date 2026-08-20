"""프로젝트 전체 내보내기(export)/가져오기(import) — 압축 대상 계산 및 안전한 압축
해제 로직 (Qt 비의존).

**export**: `images/`(`.thumbs/` 캐시 제외), `annotations/`, `classes.json`,
`project.json`은 항상 포함하고, `checkpoints/`, `user_models/`는 옵션으로 포함한다.
실제 zip 압축(파일 I/O)은 `app/widgets/project_export_dialog.py`의
`_ProjectExportWorker.run()`에서 수행한다 — 이 모듈은 "무엇을 담을지"만 계산한다.

**import**: `collect_export_entries()`가 만든 zip 구조(루트에 `images/`,
`annotations/`, `classes.json`, `project.json` 등이 그대로 위치)의 역연산이다.
zip 검증(필수 항목 존재, zip slip 방지)과 이름 충돌 자동 리네임까지 이 모듈에서
수행하고, 실제 파일 쓰기 진행률 UI는 `app/widgets/project_import_dialog.py`의
`_ProjectImportWorker.run()`이 콜백을 통해 표시한다.
"""
from __future__ import annotations

import json
import re
import shutil
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from app.core.logger import get_logger
from app.core.project import Project

log = get_logger(__name__)

_SANITIZE_RE = re.compile(r'[<>:"/\\|?*]')

# images/ 하위에서 제외할 디렉토리명 (썸네일 캐시 — 재생성 가능)
_EXCLUDED_DIR_NAMES = {".thumbs"}

# import 시 zip 안에 반드시 있어야 하는 최소 구성 요소
_REQUIRED_PREFIXES = ("images/", "annotations/")
_REQUIRED_FILES = ("classes.json",)


class ProjectZipError(Exception):
    """zip 검증 실패 — 손상되었거나 프로젝트 백업 zip 구조가 아님."""


class ProjectImportCancelled(Exception):
    """가져오기 도중 사용자가 취소함."""


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


# ── 가져오기 (import) ─────────────────────────────────────────────────────────

@dataclass
class ProjectImportResult:
    project: Project
    dir_name: str          # 실제로 만들어진 프로젝트 폴더명
    renamed: bool           # 이름 충돌로 인해 자동 리네임되었는지 여부
    extracted: int          # 실제로 압축 해제된 파일 수
    skipped: int            # zip slip 등으로 건너뛴 항목 수


def validate_project_zip(zf: zipfile.ZipFile) -> None:
    """`images/`, `annotations/`, `classes.json`이 zip 안에 있는지 확인.

    `collect_export_entries()`가 항상 포함시키는 4가지(zip.json 제외 —
    project.json은 없어도 `open_existing()`이 자동 생성 가능하므로 필수에서 뺌)
    중 필수 3가지만 검증한다. 없으면 `ProjectZipError`.
    """
    names = zf.namelist()
    missing = []
    for prefix in _REQUIRED_PREFIXES:
        if not any(n == prefix or n.startswith(prefix) for n in names):
            missing.append(prefix)
    for fname in _REQUIRED_FILES:
        if fname not in names:
            missing.append(fname)
    if missing:
        raise ProjectZipError(
            "필수 항목이 없습니다 (프로젝트 백업 zip이 아닐 수 있습니다): "
            + ", ".join(missing)
        )


def _sanitize_name(name: str) -> str:
    return _SANITIZE_RE.sub("_", name).strip().strip(".")


def resolve_import_dir_name(dest_root: Path, base_name: str) -> str:
    """`dest_root` 하위에서 `base_name`과 충돌하지 않는 폴더명을 찾는다.

    이미 있으면 `{base_name}_imported`, 그것도 있으면 `_imported_2`, `_3`…
    순으로 증가시킨다. 기존 프로젝트는 절대 덮어쓰지 않는다.
    """
    safe = _sanitize_name(base_name) or "project"
    if not (dest_root / safe).exists():
        return safe
    candidate = f"{safe}_imported"
    n = 2
    while (dest_root / candidate).exists():
        candidate = f"{safe}_imported_{n}"
        n += 1
    return candidate


def _infer_base_name(zf: zipfile.ZipFile, zip_path: Path) -> str:
    """zip 안의 `project.json`에서 이름을 읽고, 없으면 zip 파일명을 사용."""
    try:
        with zf.open("project.json") as f:
            meta = json.loads(f.read().decode("utf-8"))
        name = meta.get("name")
        if name:
            return str(name)
    except (KeyError, json.JSONDecodeError, UnicodeDecodeError, OSError):
        pass
    return zip_path.stem


def _resolve_member_target(dest_dir: Path, arcname: str) -> Path | None:
    """zip 항목 하나의 안전한 해제 대상 경로를 계산한다.

    절대경로/드라이브 문자/`..` 상위 이동이 섞인 arcname(zip slip 시도)은
    `None`을 반환해 호출측이 건너뛰도록 한다.
    """
    normalized = arcname.replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        return None
    parts = [part for part in normalized.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        return None

    target = dest_dir.joinpath(*parts)
    dest_resolved = dest_dir.resolve()
    target_resolved = target.resolve()
    if target_resolved != dest_resolved and dest_resolved not in target_resolved.parents:
        return None
    return target


def collect_import_plan(
    zf: zipfile.ZipFile, dest_dir: Path,
) -> tuple[list[tuple[zipfile.ZipInfo, Path]], int]:
    """zip 내부 파일 항목 각각을 `(ZipInfo, 해제 대상 절대경로)`로 매핑.

    zip slip으로 판정된 항목은 계획에서 제외하고 건너뛴 개수를 함께 반환한다.
    """
    plan: list[tuple[zipfile.ZipInfo, Path]] = []
    skipped = 0
    for info in zf.infolist():
        if info.is_dir():
            continue
        target = _resolve_member_target(dest_dir, info.filename)
        if target is None:
            skipped += 1
            log.warning(f"가져오기: 안전하지 않은 경로 건너뜀 — {info.filename!r}")
            continue
        plan.append((info, target))
    return plan, skipped


def import_project_zip(
    zip_path: Path,
    dest_root: Path,
    progress_cb: Callable[[int, int, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> ProjectImportResult:
    """`zip_path`를 검증 후 `dest_root` 하위에 새 프로젝트 폴더로 압축 해제한다.

    `collect_export_entries()`가 만든 zip 구조의 역연산 — zip 루트의
    `images/`, `annotations/`, `classes.json`, `project.json`(선택적으로
    `checkpoints/`, `user_models/`)을 그대로 새 프로젝트 폴더에 풀어놓는다.

    이름 충돌 시 기존 프로젝트를 덮어쓰지 않고 자동으로 리네임하며(`_imported`,
    `_imported_2`…), zip slip으로 판정된 항목은 건너뛴다. 실패/취소 시 이미
    만든 대상 폴더를 정리(rollback)한다.
    """
    zip_path = Path(zip_path)
    dest_root = Path(dest_root)
    if not zip_path.exists():
        raise FileNotFoundError(f"zip 파일을 찾을 수 없습니다: {zip_path}")

    try:
        zf = zipfile.ZipFile(zip_path, "r")
    except zipfile.BadZipFile as e:
        raise ProjectZipError(f"손상된 zip 파일입니다: {e}") from e

    with zf:
        bad_file = zf.testzip()
        if bad_file is not None:
            raise ProjectZipError(f"zip 내부 파일이 손상되었습니다: {bad_file}")

        validate_project_zip(zf)

        base_name = _infer_base_name(zf, zip_path)
        dest_root.mkdir(parents=True, exist_ok=True)
        dir_name = resolve_import_dir_name(dest_root, base_name)
        dest_dir = dest_root / dir_name

        plan, skipped = collect_import_plan(zf, dest_dir)
        if not plan:
            raise ProjectZipError("압축 파일 안에 가져올 유효한 항목이 없습니다.")

        dest_dir.mkdir(parents=True)
        try:
            total = len(plan)
            extracted = 0
            for i, (info, target) in enumerate(plan, 1):
                if should_cancel is not None and should_cancel():
                    raise ProjectImportCancelled()
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                extracted += 1
                if progress_cb is not None:
                    progress_cb(i, total, info.filename)
        except Exception:
            shutil.rmtree(dest_dir, ignore_errors=True)
            raise

    project = Project(dest_dir.resolve())
    project.ensure_dirs()
    renamed = dir_name != _sanitize_name(base_name)
    if project.meta_file.exists():
        try:
            meta = json.loads(project.meta_file.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    else:
        meta = {}
    meta["name"] = dir_name if renamed else meta.get("name", dir_name)
    meta["imported"] = True
    meta["imported_from"] = str(zip_path)
    project.save_metadata(**meta)

    return ProjectImportResult(
        project=project, dir_name=dir_name, renamed=renamed,
        extracted=extracted, skipped=skipped,
    )
