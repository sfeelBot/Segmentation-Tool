"""Zone 분석 탭 — 이미지별 편집 상태(원/블랍삭제/브러시스트로크) 디스크 영속화.

annotation_store.py와 같은 역할(JSON 읽기·쓰기 전담, Qt 의존성 없음)이지만 저장
위치가 다르다 — 이 도구는 프로젝트 시스템이 없어 이미지 파일 옆에 사이드카로 둔다.
저장 내용은 ZoneCanvas.get_state()가 반환하는 경량 스냅샷 그대로(마스크 배열 없음).
"""
import json
import logging
import os
from pathlib import Path
import tempfile

log = logging.getLogger(__name__)


def sidecar_path(image_path: Path) -> Path:
    return image_path.with_suffix(".zone.json")


def save_state(image_path: Path, state: dict) -> None:
    """state를 이미지 옆 사이드카에 저장. 원/삭제이력/스트로크가 전부 비어 있으면
    (한 번도 편집 안 한 이미지) 사이드카를 만들지 않고, 기존 파일이 있으면 정리
    차원에서 지운다(빈 파일 난립 방지)."""
    path = sidecar_path(image_path)
    is_empty = not state["circles"] and not state["removed_blob_ids"] and not state["manual_strokes"]
    if is_empty:
        path.unlink(missing_ok=True)
        return
    payload = {
        "circles": state["circles"],
        "removed_blob_ids": sorted(state["removed_blob_ids"]),   # set -> JSON 배열
        "erase_strokes": state["erase_strokes"],
        "manual_strokes": state["manual_strokes"],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def load_state(image_path: Path) -> dict | None:
    """사이드카가 없거나 읽기 실패하면 None(호출부가 빈 상태로 처리)."""
    path = sidecar_path(image_path)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {
            "circles": [tuple(c) for c in payload["circles"]],
            "removed_blob_ids": set(payload["removed_blob_ids"]),
            "erase_strokes": [[tuple(pt) for pt in s] for s in payload["erase_strokes"]],
            "manual_strokes": [(m[0], [tuple(pt) for pt in m[1]]) for m in payload["manual_strokes"]],
        }
    except (OSError, ValueError, KeyError) as exc:
        log.warning(f"Zone 사이드카 로드 실패, 빈 상태로 시작 — {path}: {exc}")
        return None


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        img = Path(tmp) / "7번.bmp"
        img.write_bytes(b"fake")
        assert sidecar_path(img).name == "7번.zone.json"

        state = {
            "circles": [(1, 10.0, 20.0, 5.0)],
            "removed_blob_ids": {3, 1},
            "erase_strokes": [[(1.0, 2.0, 3.0)]],
            "manual_strokes": [(True, [(1.0, 2.0, 3.0)])],
        }
        save_state(img, state)
        loaded = load_state(img)
        assert loaded["circles"] == [(1, 10.0, 20.0, 5.0)]
        assert loaded["removed_blob_ids"] == {1, 3}
        assert loaded["manual_strokes"] == [(True, [(1.0, 2.0, 3.0)])]

        empty = {"circles": [], "removed_blob_ids": set(), "erase_strokes": [], "manual_strokes": []}
        save_state(img, empty)
        assert not sidecar_path(img).exists(), "빈 상태 저장은 기존 사이드카를 지워야 함"
        assert load_state(img) is None

        assert load_state(Path(tmp) / "없음.bmp") is None
        print("zone_state_store self-check OK")
