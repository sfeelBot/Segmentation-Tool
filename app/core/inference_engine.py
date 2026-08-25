"""추론 엔진 — 체크포인트 로드, 전처리, 포워드 패스, 마스크 컬러화."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn as nn
from PIL import Image
from PyQt6.QtGui import QImage, QPixmap

from app.core.dataset import IMAGENET_MEAN, IMAGENET_STD
from app.core.annotation_store import ClassDef, load_classes
from app.core import project as _project


@dataclass
class ClassStat:
    class_id: int
    name: str
    color: tuple[int, int, int]
    pixel_pct: float


@dataclass
class BlobStat:
    """연결 요소(blob) 하나의 통계 — Excel 내보내기·필터링에 쓰인다."""
    blob_id: int
    class_id: int
    class_name: str
    pixel_count: int
    mean_confidence: float   # 0~1
    min_confidence: float
    max_confidence: float
    centroid_x: float
    centroid_y: float
    bbox_x: int
    bbox_y: int
    bbox_w: int
    bbox_h: int


@dataclass
class InferenceResult:
    class_map: np.ndarray          # (H, W) int64 — 필터 적용 후 원본 해상도
    raw_class_map: np.ndarray      # (H, W) int64 — 필터 적용 전 원본 argmax 클래스맵 (재필터링용)
    confidence_map: np.ndarray     # (H, W) float32 — 픽셀별 최고 클래스 확률 (재필터링용)
    overlay_pixmap: QPixmap        # 원본 + 컬러 마스크 블렌딩 결과
    class_stats: list[ClassStat]
    blobs: list[BlobStat]


def run(
    model: nn.Module,
    image_path: Path | str,
    checkpoint_path: Path | str,
    opacity: float = 0.5,
    min_confidence: float = 0.0,
    min_pixel_size: int = 0,
) -> InferenceResult:
    """
    Returns InferenceResult.
    opacity: 0.0 = 원본만, 1.0 = 마스크만
    min_confidence: blob 평균 신뢰도 하한 (0~1) — 미달 blob은 배경으로 제거
    min_pixel_size: blob 최소 픽셀 수 — 미달 blob은 배경으로 제거
    """
    classes  = load_classes()
    cls_map  = {c.class_id: c for c in classes}
    device   = _pick_device()

    # ── 체크포인트 로드 ────────────────────────────────────────────────────────
    ckpt = torch.load(str(checkpoint_path), map_location=device)
    state = ckpt.get("model_state_dict", ckpt)  # full ckpt 또는 raw state_dict 허용
    model.load_state_dict(state, strict=False)
    model.to(device).eval()

    # ── 이미지 전처리 ──────────────────────────────────────────────────────────
    pil_img = Image.open(str(image_path)).convert("RGB")
    orig_w, orig_h = pil_img.size

    import torchvision.transforms.functional as TF  # 지연 임포트 — 콜드 기동 단축

    # 학습 시와 같은 크기로 resize (체크포인트 config 없으면 512×512)
    infer_size = _infer_size_from_ckpt(ckpt)
    resized = pil_img.resize(infer_size, Image.BILINEAR)
    img_np  = np.array(resized, dtype=np.uint8)
    tensor  = TF.to_tensor(img_np)
    tensor  = TF.normalize(tensor, IMAGENET_MEAN, IMAGENET_STD)
    tensor  = tensor.unsqueeze(0).to(device)   # (1, 3, H, W)

    # ── 포워드 패스 ───────────────────────────────────────────────────────────
    with torch.no_grad():
        output = model(tensor)                 # (1, C, H, W)
        probs  = torch.softmax(output, dim=1)

    conf_small, class_map_small = probs.max(dim=1)   # 둘 다 (1, h, w)
    conf_small      = conf_small.squeeze(0).cpu().numpy().astype(np.float32)
    class_map_small = class_map_small.squeeze(0).cpu().numpy()

    # ── 원본 해상도로 리사이즈 ────────────────────────────────────────────────
    raw_class_map = np.array(
        Image.fromarray(class_map_small.astype(np.uint8)).resize(
            (orig_w, orig_h), Image.NEAREST
        ),
        dtype=np.int64,
    )
    confidence_map = np.array(
        Image.fromarray(conf_small).resize((orig_w, orig_h), Image.BILINEAR),
        dtype=np.float32,
    )

    # ── blob 분석 + threshold 필터링 ─────────────────────────────────────────
    class_map, blobs = _compute_blobs_and_filter(
        raw_class_map, confidence_map, classes, min_confidence, min_pixel_size
    )

    # ── 컬러화 + 블렌딩 ───────────────────────────────────────────────────────
    overlay_pix = _colorize_and_blend(
        pil_img, class_map, cls_map, opacity
    )

    # ── 클래스 통계 ───────────────────────────────────────────────────────────
    total = class_map.size
    stats: list[ClassStat] = []
    for c in classes:
        pct = float((class_map == c.class_id).sum()) / total * 100.0
        stats.append(ClassStat(c.class_id, c.name, c.color, round(pct, 2)))
    stats.sort(key=lambda s: s.pixel_pct, reverse=True)

    return InferenceResult(
        class_map=class_map,
        raw_class_map=raw_class_map,
        confidence_map=confidence_map,
        overlay_pixmap=overlay_pix,
        class_stats=stats,
        blobs=blobs,
    )


def run_sliding_window(
    model: nn.Module,
    image_path: Path | str,
    checkpoint_path: Path | str,
    overlap: int = 64,
    opacity: float = 0.5,
    min_confidence: float = 0.0,
    min_pixel_size: int = 0,
) -> InferenceResult:
    """패치 학습 모델용 슬라이딩 윈도우 추론.

    1) 체크포인트 로드 + patch_size 확인
    2) 원본 이미지를 stride = patch_size - overlap 간격으로 패치 분할
    3) 각 패치 추론 → 소프트맥스 확률 누적
    4) 겹치는 영역 평균(weighted blend) → argmax → class_map
    5) 결과를 원본 해상도로 오버레이 합성
    """
    classes = load_classes()
    cls_map = {c.class_id: c for c in classes}
    device  = _pick_device()

    ckpt = torch.load(str(checkpoint_path), map_location=device)
    state = ckpt.get("model_state_dict", ckpt)
    model.load_state_dict(state, strict=False)
    model.to(device).eval()

    pil_img = Image.open(str(image_path)).convert("RGB")
    orig_w, orig_h = pil_img.size
    pw, ph = _infer_size_from_ckpt(ckpt)   # 패치 크기
    n_classes = len(classes)

    stride_x = max(1, pw - overlap)
    stride_y = max(1, ph - overlap)

    # 확률 누적 배열: float16 로 메모리 절약 (C × H × W)
    acc    = np.zeros((n_classes, orig_h, orig_w), dtype=np.float32)
    counts = np.zeros((orig_h, orig_w), dtype=np.float32)

    # 패치 좌표 목록 생성 (경계 근처는 이미지 안으로 클리핑)
    patches: list[tuple[int, int]] = []
    y = 0
    while True:
        y1 = min(y + ph, orig_h);  y0 = y1 - ph
        x = 0
        while True:
            x1 = min(x + pw, orig_w);  x0 = x1 - pw
            patches.append((x0, y0))
            if x1 >= orig_w:
                break
            x += stride_x
        if y1 >= orig_h:
            break
        y += stride_y

    # 배치 추론 (batch_size=4 로 GPU 효율화)
    batch_size = 4
    for i in range(0, len(patches), batch_size):
        batch_coords = patches[i : i + batch_size]
        tensors = []
        for x0, y0 in batch_coords:
            patch  = pil_img.crop((x0, y0, x0 + pw, y0 + ph))
            t      = _preprocess_patch(patch)
            tensors.append(t)
        batch = torch.cat(tensors, dim=0).to(device)
        with torch.no_grad():
            out   = model(batch)                                      # (B, C, ph, pw)
            probs = torch.softmax(out, dim=1).cpu().numpy().astype(np.float32)  # (B, C, ph, pw)
        for j, (x0, y0) in enumerate(batch_coords):
            acc[:, y0:y0+ph, x0:x0+pw]  += probs[j]
            counts[y0:y0+ph, x0:x0+pw]  += 1.0

    # 평균 → argmax / confidence
    counts = np.maximum(counts, 1.0)
    probs_avg = acc / counts[None]
    confidence_map = probs_avg.max(axis=0).astype(np.float32)
    raw_class_map  = probs_avg.argmax(axis=0).astype(np.int64)

    class_map, blobs = _compute_blobs_and_filter(
        raw_class_map, confidence_map, classes, min_confidence, min_pixel_size
    )

    overlay_pix = _colorize_and_blend(pil_img, class_map, cls_map, opacity)
    total = class_map.size
    stats = sorted(
        [ClassStat(c.class_id, c.name, c.color,
                   round(float((class_map == c.class_id).sum()) / total * 100, 2))
         for c in classes],
        key=lambda s: s.pixel_pct, reverse=True,
    )
    return InferenceResult(
        class_map=class_map,
        raw_class_map=raw_class_map,
        confidence_map=confidence_map,
        overlay_pixmap=overlay_pix,
        class_stats=stats,
        blobs=blobs,
    )


def refilter(
    raw_class_map: np.ndarray,
    confidence_map: np.ndarray,
    image_path_or_pil: "Path | str | Image.Image",
    min_confidence: float,
    min_pixel_size: int,
    opacity: float,
) -> InferenceResult:
    """모델 재실행 없이 threshold 만 바꿔 InferenceResult를 재계산.

    UI(추론 탭)에서 min_confidence/min_pixel_size 슬라이더·스핀박스 값이 바뀔 때
    호출한다 — numpy/cv2 연산만 수행하므로 opacity 슬라이더처럼 forward pass를
    다시 돌리지 않는다.
    """
    classes = load_classes()
    cls_map = {c.class_id: c for c in classes}
    pil_img = (
        image_path_or_pil if isinstance(image_path_or_pil, Image.Image)
        else Image.open(str(image_path_or_pil)).convert("RGB")
    )

    class_map, blobs = _compute_blobs_and_filter(
        raw_class_map, confidence_map, classes, min_confidence, min_pixel_size
    )
    overlay_pix = _colorize_and_blend(pil_img, class_map, cls_map, opacity)

    total = class_map.size
    stats = sorted(
        [ClassStat(c.class_id, c.name, c.color,
                   round(float((class_map == c.class_id).sum()) / total * 100, 2))
         for c in classes],
        key=lambda s: s.pixel_pct, reverse=True,
    )
    return InferenceResult(
        class_map=class_map,
        raw_class_map=raw_class_map,
        confidence_map=confidence_map,
        overlay_pixmap=overlay_pix,
        class_stats=stats,
        blobs=blobs,
    )


def export_blobs_to_excel(rows: list[tuple[str, BlobStat]], out_path: Path) -> None:
    """(이미지파일명, BlobStat) 목록을 xlsx로 저장 — 헤더만 볼드, 시트 1개."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "blobs"
    headers = [
        "이미지파일명", "blob_id", "class_id", "클래스명", "픽셀수(면적)",
        "평균 신뢰도(%)", "최소 신뢰도(%)", "최대 신뢰도(%)",
        "중심x", "중심y", "bbox_x", "bbox_y", "bbox_w", "bbox_h",
    ]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)

    for image_name, b in rows:
        ws.append([
            image_name, b.blob_id, b.class_id, b.class_name, b.pixel_count,
            round(b.mean_confidence * 100, 2),
            round(b.min_confidence * 100, 2),
            round(b.max_confidence * 100, 2),
            round(b.centroid_x, 1), round(b.centroid_y, 1),
            b.bbox_x, b.bbox_y, b.bbox_w, b.bbox_h,
        ])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(out_path))


def _preprocess_patch(patch: Image.Image) -> torch.Tensor:
    """PIL 패치 → 정규화된 (1, 3, H, W) 텐서."""
    import torchvision.transforms.functional as TF  # 지연 임포트 — 콜드 기동 단축

    img_np = np.array(patch, dtype=np.uint8)
    t = TF.to_tensor(img_np)
    t = TF.normalize(t, [0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    return t.unsqueeze(0)


def _infer_mode_from_ckpt(ckpt: dict) -> str:
    """체크포인트에 저장된 sample_mode 반환. 없으면 'resize'."""
    cfg = ckpt.get("config", {})
    return cfg.get("sample_mode", "resize")


def list_checkpoints() -> list[Path]:
    ckpt_dir = _project.checkpoints_dir()
    if not ckpt_dir.exists():
        return []
    return sorted(ckpt_dir.glob("*.pt"), key=lambda p: p.stat().st_mtime)


@dataclass
class CheckpointMeta:
    path: Path
    epoch: int
    train_loss: float
    val_loss: float
    mean_iou: float
    model_source: str = ""   # "preset:simple_unet" | "loaded" | ""


def load_checkpoint_meta(path: Path) -> CheckpointMeta:
    """model_state_dict를 제외한 스칼라 메타데이터만 읽는다."""
    try:
        ckpt = torch.load(str(path), map_location="cpu")
        metrics = ckpt.get("metrics", {})
        cfg     = ckpt.get("config", {})
        return CheckpointMeta(
            path         = path,
            epoch        = int(ckpt.get("epoch", 0)),
            train_loss   = float(ckpt.get("train_loss", float("nan"))),
            val_loss     = float(ckpt.get("val_loss",   float("nan"))),
            mean_iou     = float(metrics.get("mean_iou", float("nan"))),
            model_source = str(cfg.get("model_source", "")),
        )
    except Exception:
        return CheckpointMeta(path=path, epoch=0,
                              train_loss=float("nan"),
                              val_loss=float("nan"),
                              mean_iou=float("nan"),
                              model_source="")


def load_model_from_ckpt(ckpt_path: Path) -> "nn.Module | None":
    """체크포인트 메타에서 model_source 를 읽어 자동으로 모델 인스턴스화.
    프리셋 모델이면 fresh weights 로 반환, 알 수 없으면 None."""
    try:
        ckpt = torch.load(str(ckpt_path), map_location="cpu")
        src  = ckpt.get("config", {}).get("model_source", "")
    except Exception:
        return None

    if not src.startswith("preset:"):
        return None

    key = src[len("preset:"):]
    try:
        from app.model_presets import load_preset_code
        from app.core.model_loader import load_from_code
        code = load_preset_code(key)
        if not code:
            return None
        result = load_from_code(code)
        return result.model if result.ok else None
    except Exception:
        return None


def model_source_label(source: str) -> str:
    """model_source 문자열을 사람이 읽기 쉬운 짧은 이름으로 변환."""
    if not source:
        return "—"
    if source == "loaded":
        return "사용자 모델"
    if source.startswith("preset:"):
        key = source[len("preset:"):]
        try:
            from app.model_presets import preset_by_key
            info = preset_by_key(key)
            if info:
                return info.title.split("(")[0].strip()
        except Exception:
            pass
        return key
    return source


# ── 내부 헬퍼 ─────────────────────────────────────────────────────────────────

def _compute_blobs_and_filter(
    class_map: np.ndarray,
    confidence_map: np.ndarray,
    classes: list[ClassDef],
    min_confidence: float,
    min_pixel_size: int,
) -> tuple[np.ndarray, list[BlobStat]]:
    """클래스별 연결 요소(blob)를 분리해 threshold 미달 blob은 배경(0)으로 되돌린다.

    class_id == 0(배경)은 blob 대상에서 제외. 반환하는 class_map은 새 배열이며
    인자로 받은 class_map은 mutate하지 않는다. blob_id는 이미지 전체 기준 1부터 순차 부여.
    """
    filtered = class_map.copy()
    blobs: list[BlobStat] = []
    name_by_id = {c.class_id: c.name for c in classes}
    blob_id = 1

    for cid in (int(c) for c in np.unique(class_map)):
        if cid == 0:
            continue
        mask = (class_map == cid).astype(np.uint8)
        n_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
        if n_labels <= 1:
            continue

        # per-blob mean/min/max confidence — 라벨별 O(H×W) 부울 인덱싱 대신
        # bincount/ufunc.at 으로 전체 픽셀을 한 번씩만 훑는다 (blob 개수에 무관하게 O(H×W)).
        flat_labels = labels.ravel()
        flat_conf   = confidence_map.ravel().astype(np.float64)
        cnt = np.bincount(flat_labels, minlength=n_labels)
        sum_conf = np.bincount(flat_labels, weights=flat_conf, minlength=n_labels)
        mean_per_label = sum_conf / np.maximum(cnt, 1)
        min_per_label = np.full(n_labels, np.inf)
        np.minimum.at(min_per_label, flat_labels, flat_conf)
        max_per_label = np.full(n_labels, -np.inf)
        np.maximum.at(max_per_label, flat_labels, flat_conf)

        reject_labels: list[int] = []
        for lbl in range(1, n_labels):   # 0 = 배경 라벨
            pixel_count = int(stats[lbl, cv2.CC_STAT_AREA])
            mean_conf = float(mean_per_label[lbl])

            if mean_conf < min_confidence or pixel_count < min_pixel_size:
                reject_labels.append(lbl)
                continue

            cx, cy = centroids[lbl]
            blobs.append(BlobStat(
                blob_id=blob_id,
                class_id=cid,
                class_name=name_by_id.get(cid, f"class_{cid}"),
                pixel_count=pixel_count,
                mean_confidence=mean_conf,
                min_confidence=float(min_per_label[lbl]),
                max_confidence=float(max_per_label[lbl]),
                centroid_x=float(cx),
                centroid_y=float(cy),
                bbox_x=int(stats[lbl, cv2.CC_STAT_LEFT]),
                bbox_y=int(stats[lbl, cv2.CC_STAT_TOP]),
                bbox_w=int(stats[lbl, cv2.CC_STAT_WIDTH]),
                bbox_h=int(stats[lbl, cv2.CC_STAT_HEIGHT]),
            ))
            blob_id += 1

        if reject_labels:
            filtered[np.isin(labels, reject_labels)] = 0

    return filtered, blobs


def _pick_device() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def _infer_size_from_ckpt(ckpt: dict) -> tuple[int, int]:
    cfg = ckpt.get("config", {})
    w   = cfg.get("image_w", 512)
    h   = cfg.get("image_h", 512)
    return (int(w), int(h))


# 화면 미리보기 오버레이 최대 크기 (annotation_canvas.py의 _MAX_OVERLAY_DIM과 동일 기준).
# class_map(원본 해상도, InferenceResult.class_map으로 반환/저장에 쓰임)은 절대 건드리지 않고
# 컬러화+블렌딩용 작업 배열만 여기서 로컬로 축소한다.
_MAX_OVERLAY_DIM = 2048


def _colorize_and_blend(
    orig: Image.Image,
    class_map: np.ndarray,
    cls_map: dict[int, ClassDef],
    opacity: float,
) -> QPixmap:
    h, w = class_map.shape

    max_dim = max(h, w)
    if max_dim > _MAX_OVERLAY_DIM:
        scale = _MAX_OVERLAY_DIM / max_dim
        w, h = max(1, round(class_map.shape[1] * scale)), max(1, round(class_map.shape[0] * scale))
        # class_map은 정수 클래스 ID이므로 NEAREST로만 축소 (보간 시 클래스 ID가 오염됨).
        # 원본 class_map 배열(호출자 소유)은 mutate하지 않고 새 배열을 만든다.
        class_map_work = np.array(
            Image.fromarray(class_map.astype(np.uint8)).resize((w, h), Image.NEAREST),
            dtype=np.int64,
        )
    else:
        class_map_work = class_map

    color_img = np.zeros((h, w, 3), dtype=np.uint8)
    for cid, cls in cls_map.items():
        mask = class_map_work == cid
        color_img[mask] = cls.color

    # PIL blend — 원본 이미지는 부드러운 축소를 위해 BILINEAR
    orig_np    = np.array(orig.resize((w, h), Image.BILINEAR), dtype=np.uint8)
    blended    = (orig_np * (1 - opacity) + color_img * opacity).clip(0, 255).astype(np.uint8)

    qimg = QImage(
        blended.tobytes(), w, h,
        w * 3,
        QImage.Format.Format_RGB888,
    )
    return QPixmap.fromImage(qimg)
