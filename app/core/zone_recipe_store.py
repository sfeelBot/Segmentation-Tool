"""Zone 분석 탭 — "일괄 적용" 레시피(원 집합) 저장·불러오기.

`zone_state_store.py`/`annotation_store.py`와 같은 역할 분담(Qt 의존성 없는 순수
JSON 저장소). Zone 탭은 프로젝트 시스템이 없는 "완전 독립" 도구라
`app/core/project.py`의 `_fallback()`과 동일하게 `Path("data")` 루트 아래
`zone_recipes/` 하위 폴더를 쓴다.

레시피는 순수 기하 데이터(cx, cy, r 튜플 리스트 + 저장 당시 기준 이미지 크기)
— id는 저장하지 않는다(적용 시 `ZoneCanvas.set_circles()`가 새 id를 자동 발급).
"최근" 판정은 파일 mtime을 그대로 쓴다(별도 "최근 사용 목록"을 만들지 않음, YAGNI).
"""
import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path


def recipes_dir() -> Path:
    return Path("data/zone_recipes").resolve()


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]', "_", name.strip())
    return cleaned or "recipe"


def save_recipe(
    name: str,
    circles: list[tuple[float, float, float]],
    ref_size: tuple[int, int],
) -> Path:
    """이름 기준 1파일 — 같은 이름으로 다시 저장하면 덮어쓴다(mtime이 "최근"으로
    갱신됨, 의도된 동작)."""
    d = recipes_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{_safe_filename(name)}.json"
    payload = {
        "name": name,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "ref_size": list(ref_size),
        "circles": [list(c) for c in circles],
    }
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return path


def load_recipe(path: Path) -> dict | None:
    """읽기 실패 시 None(호출부가 빈 상태로 처리)."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {
            "name": payload["name"],
            "saved_at": payload.get("saved_at", ""),
            "ref_size": tuple(payload["ref_size"]),
            "circles": [tuple(c) for c in payload["circles"]],
        }
    except (OSError, ValueError, KeyError):
        return None


def list_recipes() -> list[Path]:
    """mtime 내림차순 — 가장 최근 저장/사용한 것이 맨 앞(자동 로드 대상)."""
    d = recipes_dir()
    if not d.exists():
        return []
    return sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)


def touch_recipe(path: Path) -> None:
    """"불러오기"/"자동 적용" 시 mtime을 갱신해 "최근 사용"에도 반영한다."""
    try:
        path.touch()
    except OSError:
        pass


if __name__ == "__main__":
    import shutil
    import time

    tmp_root = Path(tempfile.mkdtemp())
    try:
        orig_cwd = Path.cwd()
        os.chdir(tmp_root)

        assert list_recipes() == []

        p1 = save_recipe("표준 캡 3존", [(1200.0, 1800.0, 400.0), (1200.0, 1800.0, 900.0)], (5472, 3648))
        assert p1.name == "표준 캡 3존.json"
        loaded = load_recipe(p1)
        assert loaded["name"] == "표준 캡 3존"
        assert loaded["ref_size"] == (5472, 3648)
        assert loaded["circles"] == [(1200.0, 1800.0, 400.0), (1200.0, 1800.0, 900.0)]

        time.sleep(0.01)
        p2 = save_recipe("다른 레시피", [(1.0, 2.0, 3.0)], (100, 100))
        recipes = list_recipes()
        assert recipes[0] == p2, "가장 최근 저장이 맨 앞이어야 함"

        time.sleep(0.01)
        touch_recipe(p1)
        recipes = list_recipes()
        assert recipes[0] == p1, "touch 후 p1이 가장 최근이어야 함"

        unsafe_path = save_recipe('나쁜/이름:*?', [], (1, 1))
        assert "/" not in unsafe_path.stem and ":" not in unsafe_path.stem

        assert load_recipe(Path(tmp_root) / "없음.json") is None

        print("zone_recipe_store self-check OK")
    finally:
        os.chdir(orig_cwd)
        shutil.rmtree(tmp_root, ignore_errors=True)
