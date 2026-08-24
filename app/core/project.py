"""프로젝트(Project) 개념 — 이미지·어노테이션·체크포인트·모델을 격리해서 관리.

현재 열려있는 프로젝트를 모듈 레벨 싱글턴으로 두고, 다른 모듈은
path 헬퍼(`images_dir()`, `annotations_dir()` 등)를 통해 현재 프로젝트의
경로를 조회한다.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.core.logger import get_logger

log = get_logger(__name__)

DEFAULT_PROJECTS_ROOT = Path("projects")
PROJECT_META_FILE = "project.json"
SETTINGS_KEY = "projects_root"

_current: "Project | None" = None


def _app_root() -> Path:
    """앱 루트 디렉터리. PyInstaller onedir 번들에서는 __file__이 실제 파일이
    없는 합성 경로(추출되지 않은 _internal 내부)를 가리키므로 sys.executable
    기준으로 잡는다 (PyInstaller 공식 권장 패턴)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent.parent.parent


def default_projects_root() -> Path:
    """설정 미저장 시 사용할 기본 프로젝트 저장 경로."""
    return (_app_root() / "projects").resolve()


def get_projects_root() -> Path:
    """설정에서 프로젝트 기본 저장 경로를 반환. 미설정 시 기본 경로 사용."""
    try:
        from app.core.i18n import load_settings
        saved = load_settings().get(SETTINGS_KEY, "")
        if saved:
            p = Path(saved)
            if p.is_absolute():
                return p
    except Exception:
        pass
    return default_projects_root()


def set_projects_root(path: Path) -> None:
    """프로젝트 기본 저장 경로를 settings.json 에 저장."""
    from app.core.i18n import save_settings
    save_settings({SETTINGS_KEY: str(path.resolve())})
    log.info(f"프로젝트 기본 경로 변경: {path}")


# ── Project 클래스 ────────────────────────────────────────────────────────────

@dataclass
class Project:
    path: Path

    # 경로 프로퍼티
    @property
    def images_dir(self) -> Path:       return self.path / "images"
    @property
    def thumbs_dir(self) -> Path:       return self.path / "images" / ".thumbs"
    @property
    def annotations_dir(self) -> Path:  return self.path / "annotations"
    @property
    def checkpoints_dir(self) -> Path:  return self.path / "checkpoints"
    @property
    def user_models_dir(self) -> Path:  return self.path / "user_models"
    @property
    def classes_file(self) -> Path:     return self.path / "classes.json"
    @property
    def meta_file(self) -> Path:        return self.path / PROJECT_META_FILE

    # 메타데이터
    @property
    def name(self) -> str:
        return self._meta.get("name", self.path.name)

    @property
    def created_at(self) -> str:
        return self._meta.get("created_at", "")

    @property
    def _meta(self) -> dict:
        if not self.meta_file.exists():
            return {}
        try:
            return json.loads(self.meta_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def ensure_dirs(self) -> None:
        for d in (self.images_dir, self.thumbs_dir, self.annotations_dir,
                  self.checkpoints_dir, self.user_models_dir):
            d.mkdir(parents=True, exist_ok=True)

    def save_metadata(self, **updates) -> None:
        data = self._meta
        data.update(updates)
        data.setdefault("created_at", datetime.now().isoformat(timespec="seconds"))
        data["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self.meta_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


# ── 현재 프로젝트 관리 ────────────────────────────────────────────────────────

def current() -> Project | None:
    return _current


def set_current(project: Project) -> None:
    global _current
    _current = project
    project.ensure_dirs()
    log.info(f"프로젝트 설정: {project.name}  ({project.path})")
    _touch_recent(project.path)


# ── 생성·열기 ─────────────────────────────────────────────────────────────────

def create(name: str, parent_dir: Path | str | None = None) -> Project:
    parent = Path(parent_dir) if parent_dir else get_projects_root()
    parent.mkdir(parents=True, exist_ok=True)

    safe = _sanitize(name)
    if not safe:
        raise ValueError("프로젝트 이름이 비어있습니다.")
    path = parent / safe
    if path.exists():
        raise FileExistsError(f"이미 존재하는 경로입니다: {path}")
    path.mkdir(parents=True)

    proj = Project(path.resolve())
    proj.save_metadata(name=name)
    proj.ensure_dirs()
    log.info(f"새 프로젝트 생성: {proj.name}  ({proj.path})")
    return proj


def open_existing(path: Path | str) -> Project:
    p = Path(path).resolve()
    if not p.exists():
        raise FileNotFoundError(f"경로 없음: {p}")
    if not p.is_dir():
        raise NotADirectoryError(f"폴더가 아님: {p}")
    proj = Project(p)
    proj.ensure_dirs()
    # 메타데이터가 없으면 생성해서 Project 로 인식
    if not proj.meta_file.exists():
        proj.save_metadata(name=p.name, imported=True)
    return proj


# ── 최근 프로젝트 목록 ────────────────────────────────────────────────────────

def recent(max_count: int = 10) -> list[Path]:
    from app.core.i18n import load_settings
    paths = load_settings().get("recent_projects", [])
    seen, out = set(), []
    for p in paths:
        pp = Path(p)
        if str(pp) in seen or not pp.exists():
            continue
        seen.add(str(pp))
        out.append(pp)
        if len(out) >= max_count:
            break
    return out


def add_recent(path: Path) -> None:
    """열지 않고 최근 목록에만 추가(가져오기 완료 직후 등) — `last_project`는 건드리지 않는다."""
    from app.core.i18n import load_settings, save_settings
    s = load_settings()
    recents: list[str] = list(s.get("recent_projects", []))
    path_str = str(Path(path).resolve())
    if path_str in recents:
        recents.remove(path_str)
    recents.insert(0, path_str)
    save_settings({"recent_projects": recents[:10]})


def _touch_recent(path: Path) -> None:
    from app.core.i18n import load_settings, save_settings
    s = load_settings()
    recents: list[str] = list(s.get("recent_projects", []))
    path_str = str(Path(path).resolve())
    if path_str in recents:
        recents.remove(path_str)
    recents.insert(0, path_str)
    save_settings({"recent_projects": recents[:10], "last_project": path_str})


def last_opened() -> Path | None:
    from app.core.i18n import load_settings
    p = load_settings().get("last_project")
    return Path(p) if p and Path(p).exists() else None


# ── 경로 헬퍼 (모듈 상수 대체용) ────────────────────────────────────────────

def _fallback() -> Path:
    """프로젝트가 아직 열리지 않았을 때 임시로 쓸 기본 경로."""
    return Path("data").resolve()


def images_dir() -> Path:
    p = current()
    return p.images_dir if p else _fallback() / "images"


def thumbs_dir() -> Path:
    p = current()
    return p.thumbs_dir if p else _fallback() / "images" / ".thumbs"


def annotations_dir() -> Path:
    p = current()
    return p.annotations_dir if p else _fallback() / "annotations"


def checkpoints_dir() -> Path:
    p = current()
    return p.checkpoints_dir if p else _fallback() / "checkpoints"


def user_models_dir() -> Path:
    p = current()
    return p.user_models_dir if p else _fallback() / "user_models"


def classes_file() -> Path:
    p = current()
    return p.classes_file if p else _fallback() / "classes.json"


# ── 내부 ─────────────────────────────────────────────────────────────────────

_SANITIZE_RE = re.compile(r'[<>:"/\\|?*]')

def _sanitize(name: str) -> str:
    s = _SANITIZE_RE.sub("_", name).strip().strip(".")
    return s
