import ast
from dataclasses import dataclass, field


ALLOWED_MODULES = {
    "torch", "torch.nn", "torch.nn.functional", "torch.nn.init",
    "torch.utils", "torch.utils.checkpoint",
    "torchvision", "torchvision.models", "torchvision.ops",
    "numpy", "math", "typing", "collections", "functools",
    "itertools", "abc", "copy",
}

BLOCKED_MODULES = {
    "os", "sys", "subprocess", "socket", "requests", "urllib",
    "shutil", "pathlib", "builtins", "ctypes", "importlib",
    "pickle", "shelve", "tempfile", "glob", "io", "signal",
    "threading", "multiprocessing", "concurrent",
}

BLOCKED_CALLS = {
    "eval", "exec", "compile", "open", "__import__",
    "globals", "locals", "vars", "dir", "breakpoint",
    "input", "memoryview",
}


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    model_class_name: str = ""
    param_hint: str = ""


def validate(code: str) -> ValidationResult:
    result = ValidationResult(ok=False)

    # 코드 크기 제한
    if len(code.encode()) > 256 * 1024:
        result.errors.append("코드 크기가 256KB를 초과합니다.")
        return result

    # 파싱
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        result.errors.append(f"Line {e.lineno}: 문법 오류 — {e.msg}")
        return result

    _check_imports(tree, result)
    _check_blocked_calls(tree, result)
    _check_module_structure(tree, result)

    result.ok = len(result.errors) == 0
    return result


def _check_imports(tree: ast.AST, result: ValidationResult) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in BLOCKED_MODULES:
                    result.errors.append(
                        f"Line {node.lineno}: '{alias.name}' import는 허용되지 않습니다."
                    )
                elif not _is_allowed_module(alias.name):
                    result.errors.append(
                        f"Line {node.lineno}: '{alias.name}' — 허용 목록에 없는 모듈입니다."
                    )

        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            root = module.split(".")[0]
            if root in BLOCKED_MODULES:
                result.errors.append(
                    f"Line {node.lineno}: 'from {module} import ...' 는 허용되지 않습니다."
                )
            elif not _is_allowed_module(module):
                result.errors.append(
                    f"Line {node.lineno}: '{module}' — 허용 목록에 없는 모듈입니다."
                )


def _is_allowed_module(name: str) -> bool:
    for allowed in ALLOWED_MODULES:
        if name == allowed or name.startswith(allowed + "."):
            return True
    return False


def _check_blocked_calls(tree: ast.AST, result: ValidationResult) -> None:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = None
        if isinstance(func, ast.Name):
            name = func.id
        elif isinstance(func, ast.Attribute):
            name = func.attr
        if name and name in BLOCKED_CALLS:
            result.errors.append(
                f"Line {node.lineno}: '{name}()' 호출은 허용되지 않습니다."
            )


def _check_module_structure(tree: ast.AST, result: ValidationResult) -> None:
    nn_subclasses = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if _inherits_nn_module(node):
            nn_subclasses.append(node)

    if not nn_subclasses:
        result.errors.append(
            "torch.nn.Module 서브클래스가 없습니다. "
            "'class MyModel(nn.Module):' 형태의 클래스를 정의하세요."
        )
        return

    # forward 메서드 확인
    for cls in nn_subclasses:
        has_forward = any(
            isinstance(n, ast.FunctionDef) and n.name == "forward"
            for n in cls.body
        )
        if not has_forward:
            result.errors.append(
                f"Line {cls.lineno}: '{cls.name}' 클래스에 forward() 메서드가 없습니다."
            )
        else:
            result.model_class_name = cls.name

    if result.model_class_name:
        result.param_hint = f"클래스 '{result.model_class_name}' 발견"


def _inherits_nn_module(node: ast.ClassDef) -> bool:
    for base in node.bases:
        if isinstance(base, ast.Attribute):
            # nn.Module, torch.nn.Module
            if base.attr == "Module":
                return True
        elif isinstance(base, ast.Name):
            if base.id == "Module":
                return True
    return False
