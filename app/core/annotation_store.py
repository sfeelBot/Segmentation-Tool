"""JSON 어노테이션 읽기·쓰기 + RLE 코덱."""
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from app.core import project as _project

DEFAULT_PALETTE: list[tuple[int, int, int]] = [
    (  0,   0,   0),  # 0 background
    (255,  59,  59),  # 1
    ( 59, 255,  59),  # 2
    ( 59, 130, 255),  # 3
    (255, 230,  59),  # 4
    (255,  59, 255),  # 5
    ( 59, 255, 255),  # 6
    (255, 140,  59),  # 7
]


@dataclass
class ClassDef:
    class_id: int
    name: str
    color: tuple[int, int, int]


@dataclass
class AnnotationItem:
    annotation_id: str
    class_id: int
    type: str           # "polygon" | "brush_mask"
    order: int = 0
    # polygon
    points: list[tuple[float, float]] = field(default_factory=list)
    # brush_mask (decoded, stored as (H,W) uint8 in memory)
    mask: np.ndarray | None = None
    width: int = 0
    height: int = 0


# ── 클래스 I/O ────────────────────────────────────────────────────────────────

def load_classes() -> list[ClassDef]:
    if not _project.classes_file().exists():
        return _default_classes()
    try:
        data = json.loads(_project.classes_file().read_text(encoding="utf-8"))
        return [ClassDef(**c) for c in data]
    except Exception:
        return _default_classes()


def save_classes(classes: list[ClassDef]) -> None:
    _project.classes_file().parent.mkdir(parents=True, exist_ok=True)
    _project.classes_file().write_text(
        json.dumps([{"class_id": c.class_id, "name": c.name, "color": list(c.color)}
                    for c in classes], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _default_classes() -> list[ClassDef]:
    return [
        ClassDef(0, "background", (0, 0, 0)),
        ClassDef(1, "object",     (255, 59, 59)),
    ]


# ── 어노테이션 I/O ────────────────────────────────────────────────────────────

def load(image_path: Path) -> list[AnnotationItem]:
    json_path = _ann_path(image_path)
    if not json_path.exists():
        return []
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    items: list[AnnotationItem] = []
    for a in data.get("annotations", []):
        if a["type"] == "polygon":
            items.append(AnnotationItem(
                annotation_id=a["annotation_id"],
                class_id=a["class_id"],
                type="polygon",
                order=a.get("order", 0),
                points=[tuple(p) for p in a["points"]],
            ))
        elif a["type"] == "brush_mask":
            w, h = a["width"], a["height"]
            mask = rle_decode(a.get("rle", ""), h, w)
            items.append(AnnotationItem(
                annotation_id=a["annotation_id"],
                class_id=a["class_id"],
                type="brush_mask",
                order=a.get("order", 0),
                mask=mask,
                width=w,
                height=h,
            ))
    return sorted(items, key=lambda x: x.order)


def save(image_path: Path, annotations: list[AnnotationItem],
         img_w: int, img_h: int) -> None:
    _project.annotations_dir().mkdir(parents=True, exist_ok=True)
    ok_flag = get_ok(image_path)   # preserve existing ok flag
    ann_list = []
    for i, a in enumerate(annotations):
        a.order = i
        if a.type == "polygon":
            ann_list.append({
                "annotation_id": a.annotation_id,
                "class_id": a.class_id,
                "type": "polygon",
                "order": i,
                "points": [[p[0], p[1]] for p in a.points],
            })
        elif a.type == "brush_mask" and a.mask is not None and a.mask.any():
            ann_list.append({
                "annotation_id": a.annotation_id,
                "class_id": a.class_id,
                "type": "brush_mask",
                "order": i,
                "width": a.width,
                "height": a.height,
                "rle": rle_encode(a.mask),
            })

    doc = {
        "version": "1.0",
        "image": image_path.name,
        "width": img_w,
        "height": img_h,
        "annotations": ann_list,
    }
    if ok_flag:
        doc["ok"] = True
    _ann_path(image_path).write_text(
        json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def new_id() -> str:
    return str(uuid.uuid4())


def _ann_path(image_path: Path) -> Path:
    return _project.annotations_dir() / f"{image_path.stem}.json"


# ── 라벨 상태 / OK 플래그 ──────────────────────────────────────────────────────

def get_label_status(image_path: Path) -> str:
    """Return 'labeled', 'ok', or 'unlabeled'."""
    json_path = _ann_path(image_path)
    if not json_path.exists():
        return "unlabeled"
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        if data.get("ok"):
            return "ok"
        if data.get("annotations"):
            return "labeled"
    except Exception:
        pass
    return "unlabeled"


def get_ok(image_path: Path) -> bool:
    json_path = _ann_path(image_path)
    if not json_path.exists():
        return False
    try:
        return bool(json.loads(json_path.read_text(encoding="utf-8")).get("ok", False))
    except Exception:
        return False


def set_ok(image_path: Path, ok: bool, img_w: int = 0, img_h: int = 0) -> None:
    _project.annotations_dir().mkdir(parents=True, exist_ok=True)
    json_path = _ann_path(image_path)
    try:
        data = json.loads(json_path.read_text(encoding="utf-8")) if json_path.exists() else {}
    except Exception:
        data = {}
    data.setdefault("version", "1.0")
    data.setdefault("image", image_path.name)
    if img_w:
        data["width"] = img_w
    if img_h:
        data["height"] = img_h
    if ok:
        data["ok"] = True
    else:
        data.pop("ok", None)
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ── RLE コーデック ─────────────────────────────────────────────────────────────

def rle_encode(mask: np.ndarray) -> str:
    """numpy 벡터 연산으로 RLE 인코딩.
    .copy() 로 스냅샷을 만들어 백그라운드 스레드 경쟁 조건 방지."""
    flat = mask.flatten()          # 항상 복사본 → 이후 메인 스레드 수정 영향 없음
    flat = (flat != 0).view(np.uint8)
    if not flat.any():
        return ""
    diff   = np.diff(flat, prepend=np.uint8(0), append=np.uint8(0))
    starts = np.where(diff == 1)[0]
    ends   = np.where(diff == -1)[0]
    # 경쟁 조건으로 전환 수가 불일치하는 경우 방어 처리
    n = min(len(starts), len(ends))
    if n == 0:
        return ""
    lengths = ends[:n] - starts[:n]
    pairs   = np.empty(n * 2, dtype=np.int64)
    pairs[0::2] = starts[:n]
    pairs[1::2] = lengths
    return " ".join(map(str, pairs.tolist()))


def rle_decode(rle: str, height: int, width: int) -> np.ndarray:
    """numpy 파싱으로 RLE 디코딩."""
    flat = np.zeros(height * width, dtype=np.uint8)
    s = rle.strip()
    if not s:
        return flat.reshape(height, width)
    arr = np.fromstring(s, dtype=np.int64, sep=" ")
    starts  = arr[0::2].tolist()
    lengths = arr[1::2].tolist()
    for st, ln in zip(starts, lengths):
        flat[st: st + ln] = 1
    return flat.reshape(height, width)
