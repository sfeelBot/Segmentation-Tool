import builtins
import importlib
import inspect
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime

import torch
import torch.nn as nn
import torch.nn.functional as F

from app.core.model_validator import ALLOWED_MODULES, validate, ValidationResult


_ALLOWED_ROOTS = {m.split(".")[0] for m in ALLOWED_MODULES}


def _make_safe_import():
    """화이트리스트 모듈만 허용하는 __import__ 래퍼.

    Python의 __import__ 반환 규칙을 그대로 따른다:
    - fromlist가 비어 있으면 최상위 패키지 반환  (import a.b as x  → returns a)
    - fromlist가 있으면 해당 서브모듈 반환         (from a.b import c → returns a.b)
    """
    def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
        root = name.split(".")[0]
        if root not in _ALLOWED_ROOTS:
            raise ImportError(f"'{name}' import는 허용되지 않습니다.")
        return builtins.__import__(name, globals, locals, fromlist, level)
    return _safe_import


def _make_safe_builtins() -> dict:
    allowed_names = [
        "abs", "all", "any", "bool", "dict", "enumerate", "filter",
        "float", "int", "len", "list", "map", "max", "min", "print",
        "range", "round", "set", "sorted", "str", "sum", "tuple",
        "zip", "isinstance", "hasattr", "getattr", "setattr",
        "super", "type", "object", "property", "staticmethod",
        "classmethod", "NotImplementedError", "ValueError",
        "TypeError", "RuntimeError", "StopIteration",
    ]
    safe = {k: getattr(builtins, k) for k in allowed_names if hasattr(builtins, k)}
    safe["__import__"] = _make_safe_import()
    safe["__build_class__"] = builtins.__build_class__
    return safe


@dataclass
class LoadResult:
    ok: bool
    model: nn.Module | None = None
    class_name: str = ""
    num_params: int = 0
    error: str = ""


def load_from_code(code: str) -> LoadResult:
    """검증 후 모델을 인스턴스화한다."""
    vr: ValidationResult = validate(code)
    if not vr.ok:
        return LoadResult(ok=False, error="\n".join(vr.errors))

    safe_globals: dict = {
        "__builtins__": _make_safe_builtins(),
        "__name__": "__user_model__",
        "__doc__": None,
        "__package__": None,
        "__spec__": None,
        "__loader__": None,
        "torch": torch,
        "nn": nn,
        "F": F,
    }

    try:
        exec(code, safe_globals)  # noqa: S102
    except Exception as e:
        return LoadResult(ok=False, error=f"코드 실행 오류: {e}")

    cls = _find_module_class(safe_globals)
    if cls is None:
        return LoadResult(ok=False, error="nn.Module 서브클래스를 찾을 수 없습니다.")

    try:
        model: nn.Module = cls()
    except Exception as e:
        return LoadResult(
            ok=False,
            error=f"모델 인스턴스 생성 실패: {e}\n"
                  "생성자에 필수 인자가 있다면 기본값을 설정하세요.",
        )

    num_params = sum(p.numel() for p in model.parameters())
    return LoadResult(
        ok=True,
        model=model,
        class_name=cls.__name__,
        num_params=num_params,
    )


def load_from_file(path: str | Path) -> LoadResult:
    path = Path(path)
    if not path.exists():
        return LoadResult(ok=False, error=f"파일을 찾을 수 없습니다: {path}")
    return load_from_code(path.read_text(encoding="utf-8"))


def save_user_code(code: str, base_dir: str | Path | None = None) -> Path:
    """사용자 코드를 타임스탬프 파일로 저장한다. (현재 프로젝트의 user_models/)"""
    from app.core import project as _project
    dest = Path(base_dir) if base_dir else _project.user_models_dir()
    dest.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fp = dest / f"model_{ts}.py"
    fp.write_text(code, encoding="utf-8")
    return fp


def _find_module_class(namespace: dict) -> type[nn.Module] | None:
    candidates = []
    for obj in namespace.values():
        if (
            inspect.isclass(obj)
            and issubclass(obj, nn.Module)
            and obj is not nn.Module
        ):
            candidates.append(obj)
    if not candidates:
        return None
    # 여러 개면 가장 마지막에 정의된 클래스 선택 (주 모델일 가능성 높음)
    return candidates[-1]
