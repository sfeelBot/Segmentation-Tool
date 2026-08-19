"""SegmentationDataset — 이미지 + 어노테이션 JSON → (image tensor, mask tensor).

학습 샘플링 모드:
  resize       — 전체 이미지를 target_size 로 축소 (기존 방식)
  random_crop  — 원본 해상도에서 target_size 패치를 랜덤 크롭 (대형 이미지 권장)
  center_crop  — 중앙 패치 크롭 (validation 일관성용)

random_crop 에서 defect_sample_prob 만큼 결함 중심으로 패치를 샘플링한다.

이미지 디코딩 캐시:
  random_crop 모드는 patches_per_image(기본 50)만큼 같은 이미지에서 반복해서
  패치를 뽑는데, __getitem__이 매번 Image.open()으로 원본을 새로 디코딩하면
  대형 원본(수십 MB)에서 비용이 크다. 최근 디코딩 결과(원본 PIL 이미지 + 렌더링된
  마스크)를 이미지당 1회만 디코딩하도록 바이트 예산 기반 LRU 캐시에 보관한다.
  DataLoader가 num_workers>0이면 워커 프로세스마다 Dataset 인스턴스가 별도로
  존재하므로(각자 fork/spawn된 복사본) 이 캐시도 워커별로 독립적이다 — 즉
  실제 최대 메모리 사용량은 대략 (캐시 예산) × max(1, num_workers) 이다.
"""
import json
import random
from collections import OrderedDict
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import Dataset
from PIL import Image, ImageDraw

from app.core.annotation_store import rle_decode
from app.core import project as _project

IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD  = [0.229, 0.224, 0.225]

# 디코딩 캐시 예산 (워커 프로세스 1개당). 57MB급 원본(RGB 디코딩 후 약 60MB) 기준
# 8~9장을 동시에 들고 있을 수 있는 크기 — nok(5장) 프로젝트라면 전량 캐시된다.
# num_workers > 0 이면 워커마다 독립 캐시이므로 총 메모리는 이 값의 배수가 된다는
# 점을 호출부(trainer.py)에서 감안해야 한다.
_DEFAULT_CACHE_BUDGET_BYTES = 512 * 1024 * 1024


class SegmentationDataset(Dataset):
    def __init__(
        self,
        image_size: tuple[int, int] = (512, 512),
        mode: str = "random_crop",          # "resize" | "random_crop" | "center_crop"
        defect_sample_prob: float = 0.7,    # random_crop 시 결함 영역 우선 샘플링 확률
        patches_per_image: int = 50,        # random_crop epoch당 이미지 1장에서 뽑을 패치 수
        augment_fn=None,
        cache_bytes_budget: int = _DEFAULT_CACHE_BUDGET_BYTES,
    ) -> None:
        self._size = image_size
        self._mode = mode
        self._defect_prob = defect_sample_prob
        self._patches_per_img = patches_per_image if mode == "random_crop" else 1
        self._augment = augment_fn
        self._pairs = _collect_pairs()
        # 결함 중심 좌표를 미리 파싱해 둠 (JSON 텍스트만 읽으므로 빠름)
        self._ann_centers: list[list[tuple[float, float]]] = (
            [_extract_ann_centers(ann_path) for _, ann_path in self._pairs]
            if mode == "random_crop" else []
        )
        # 원본 디코딩 캐시 (img_path → (PIL image, PIL mask, img_mtime, ann_mtime, nbytes))
        # 워커 프로세스마다 독립 — 모듈 docstring 참고.
        self._cache_budget = max(0, cache_bytes_budget)
        self._img_cache: "OrderedDict[Path, tuple]" = OrderedDict()
        self._cache_bytes = 0

    def __len__(self) -> int:
        # random_crop: 이미지당 patches_per_image 개 패치 → epoch당 학습량 증가
        # resize / center_crop: 이미지 1장 = 1 샘플
        return len(self._pairs) * self._patches_per_img

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        # random_crop 모드에서는 idx가 len(pairs)*patches_per_img 범위이므로
        # 실제 이미지 인덱스로 변환 (이미지를 골고루 반복)
        pair_idx = idx % len(self._pairs)
        img_path, ann_path = self._pairs[pair_idx]

        image, mask_pil = self._load_cached(img_path, ann_path)
        w_orig, h_orig = image.size

        tw, th = self._size

        if self._mode == "resize":
            image    = image.resize((tw, th), Image.BILINEAR)
            mask_pil = mask_pil.resize((tw, th), Image.NEAREST)
            img_np   = np.array(image,    dtype=np.uint8)
            mask_np  = np.array(mask_pil, dtype=np.uint8)

        else:
            # random_crop 또는 center_crop
            # 이미지가 패치보다 작으면 resize 로 폴백
            if w_orig < tw or h_orig < th:
                image    = image.resize((tw, th), Image.BILINEAR)
                mask_pil = mask_pil.resize((tw, th), Image.NEAREST)
                img_np   = np.array(image,    dtype=np.uint8)
                mask_np  = np.array(mask_pil, dtype=np.uint8)
            else:
                x0, y0 = self._crop_pos(pair_idx, w_orig, h_orig, tw, th)
                image    = image.crop   ((x0, y0, x0 + tw, y0 + th))
                mask_pil = mask_pil.crop((x0, y0, x0 + tw, y0 + th))
                img_np   = np.array(image,    dtype=np.uint8)
                mask_np  = np.array(mask_pil, dtype=np.uint8)

        # Albumentations 증강
        if self._augment is not None:
            aug     = self._augment(image=img_np, mask=mask_np)
            img_np  = aug["image"]
            mask_np = aug["mask"]

        import torchvision.transforms.functional as TF  # 지연 임포트 — 콜드 기동 단축

        img_tensor  = TF.to_tensor(img_np)
        img_tensor  = TF.normalize(img_tensor, IMAGENET_MEAN, IMAGENET_STD)
        mask_tensor = torch.from_numpy(mask_np).long()

        return img_tensor, mask_tensor

    @property
    def num_pairs(self) -> int:
        return len(self._pairs)

    # ── 이미지 디코딩 캐시 ────────────────────────────────────────────────────

    def _load_cached(self, img_path: Path, ann_path: Path) -> tuple[Image.Image, Image.Image]:
        """(원본 RGB 이미지, 렌더링된 마스크) 를 반환.
        캐시 히트 시 재디코딩/재렌더링을 건너뛴다.
        mtime 이 바뀐 경우(라벨링 탭 등에서 파일이 외부에서 갱신된 경우) 캐시를
        무효화해 최신 내용을 다시 읽는다 — 학습 중 라벨 수정에 대한 최소 안전장치."""
        try:
            img_mtime = img_path.stat().st_mtime
            ann_mtime = ann_path.stat().st_mtime
        except OSError:
            img_mtime = ann_mtime = None

        entry = self._img_cache.get(img_path)
        if entry is not None:
            cached_image, cached_mask, c_img_mtime, c_ann_mtime, nbytes = entry
            if img_mtime is not None and img_mtime == c_img_mtime and ann_mtime == c_ann_mtime:
                self._img_cache.move_to_end(img_path)
                return cached_image, cached_mask
            # mtime 불일치(외부 수정) 또는 stat 실패 → 캐시 폐기 후 재로드
            del self._img_cache[img_path]
            self._cache_bytes -= nbytes

        image = Image.open(img_path).convert("RGB")
        w, h = image.size
        mask_pil = _render_mask(ann_path, w, h)

        if self._cache_budget > 0 and img_mtime is not None:
            nbytes = w * h * 3 + w * h  # RGB + L(마스크) 1채널 근사치
            self._img_cache[img_path] = (image, mask_pil, img_mtime, ann_mtime, nbytes)
            self._cache_bytes += nbytes
            self._img_cache.move_to_end(img_path)
            # 예산 초과분을 LRU(가장 오래 전에 쓰인 항목)부터 evict
            while self._cache_bytes > self._cache_budget and len(self._img_cache) > 1:
                _, evicted = self._img_cache.popitem(last=False)
                self._cache_bytes -= evicted[4]

        return image, mask_pil

    # ── 패치 위치 결정 ─────────────────────────────────────────────────────────

    def _crop_pos(self, idx: int, w: int, h: int, tw: int, th: int) -> tuple[int, int]:
        """크롭 좌측상단 (x0, y0) 결정."""
        if self._mode == "center_crop":
            x0 = max(0, min((w - tw) // 2, w - tw))
            y0 = max(0, min((h - th) // 2, h - th))
            return x0, y0

        # random_crop — defect-biased sampling
        centers = self._ann_centers[idx] if self._ann_centers else []
        if centers and random.random() < self._defect_prob:
            # 결함 중심점 근처에 패치 위치
            cx, cy = random.choice(centers)
            # 약간의 jitter (패치 크기의 ±25%)
            jitter_x = int(tw * 0.25)
            jitter_y = int(th * 0.25)
            cx += random.randint(-jitter_x, jitter_x)
            cy += random.randint(-jitter_y, jitter_y)
            x0 = int(max(0, min(cx - tw // 2, w - tw)))
            y0 = int(max(0, min(cy - th // 2, h - th)))
            return x0, y0

        # 균등 랜덤
        return random.randint(0, w - tw), random.randint(0, h - th)


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────

def _collect_pairs() -> list[tuple[Path, Path]]:
    pairs = []
    ann_dir = _project.annotations_dir()
    img_dir = _project.images_dir()
    if not ann_dir.exists() or not img_dir.exists():
        return pairs
    for ann_file in sorted(ann_dir.glob("*.json")):
        for ext in (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"):
            img_file = img_dir / (ann_file.stem + ext)
            if img_file.exists():
                pairs.append((img_file, ann_file))
                break
    return pairs


def _extract_ann_centers(ann_path: Path) -> list[tuple[float, float]]:
    """JSON 파싱만으로 어노테이션 중심 좌표 목록 반환 (마스크 렌더링 없이).
    polygon → 꼭짓점 평균, brush_mask → 이미지 중심 근사."""
    centers: list[tuple[float, float]] = []
    try:
        data = json.loads(ann_path.read_text(encoding="utf-8"))
        img_w = float(data.get("width", 0))
        img_h = float(data.get("height", 0))
        for ann in data.get("annotations", []):
            if ann.get("class_id", 0) == 0:
                continue   # background 는 제외
            if ann["type"] == "polygon":
                pts = ann.get("points", [])
                if len(pts) >= 3:
                    cx = sum(float(p[0]) for p in pts) / len(pts)
                    cy = sum(float(p[1]) for p in pts) / len(pts)
                    centers.append((cx, cy))
            elif ann["type"] == "brush_mask":
                # RLE 디코딩 없이: bw/bh 중앙을 결함 중심으로 근사
                bw = float(ann.get("width", img_w))
                bh = float(ann.get("height", img_h))
                if bw > 0 and bh > 0:
                    centers.append((bw / 2.0, bh / 2.0))
    except Exception:
        pass
    return centers


def _render_mask(ann_path: Path, w: int, h: int) -> Image.Image:
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)

    try:
        data = json.loads(ann_path.read_text(encoding="utf-8"))
    except Exception:
        return mask

    for ann in sorted(data.get("annotations", []), key=lambda a: a.get("order", 0)):
        cid = int(ann.get("class_id", 0))
        if ann["type"] == "polygon":
            pts = [(float(p[0]), float(p[1])) for p in ann["points"]]
            if len(pts) >= 3:
                draw.polygon(pts, fill=cid)
        elif ann["type"] == "brush_mask":
            bw, bh = ann.get("width", w), ann.get("height", h)
            bitmask = rle_decode(ann.get("rle", ""), bh, bw)
            layer = Image.fromarray((bitmask * cid).astype(np.uint8), mode="L")
            if (bw, bh) != (w, h):
                layer = layer.resize((w, h), Image.NEAREST)
            arr_mask  = np.array(mask)
            arr_layer = np.array(layer)
            arr_mask[arr_layer > 0] = cid
            mask = Image.fromarray(arr_mask, mode="L")
            draw = ImageDraw.Draw(mask)

    return mask
