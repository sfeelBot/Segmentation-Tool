"""오토 라벨러 — 학습된 모델로 미라벨 이미지를 자동 어노테이션."""
import threading
from collections.abc import Callable
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from PIL import Image
from PyQt6.QtCore import QThread, pyqtSignal

from app.core.annotation_store import (
    AnnotationItem, ClassDef, new_id, save, load_classes, get_label_status,
)
from app.core.dataset import IMAGENET_MEAN, IMAGENET_STD
from app.core.inference_engine import _infer_size_from_ckpt
from app.core import project as _project

SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}


class AutoLabelWorker(QThread):
    progress   = pyqtSignal(int, int, str)  # done, total, current_filename
    image_done = pyqtSignal(str)            # filename (완료된 이미지)
    # 메모리상으로만 결과 누적 — 실제 저장은 사용자가 미리보기에서 확정한 뒤 commit_results()
    finished   = pyqtSignal(int, list)      # count, results: [(Path, list[AnnotationItem], w, h)]
    error      = pyqtSignal(str)

    def __init__(
        self,
        model: nn.Module,
        ckpt_path: Path,
        image_paths: list[Path],
    ) -> None:
        super().__init__()
        self._model     = model
        self._ckpt_path = ckpt_path
        self._paths     = image_paths
        self._stop      = threading.Event()

    def request_stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        try:
            self._run()
        except Exception as exc:
            self.error.emit(str(exc))

    def _run(self) -> None:
        classes = load_classes()
        device  = _pick_device()

        ckpt  = torch.load(str(self._ckpt_path), map_location=device)
        state = ckpt.get("model_state_dict", ckpt)
        self._model.load_state_dict(state, strict=False)
        self._model.to(device).eval()

        infer_size = _infer_size_from_ckpt(ckpt)
        total      = len(self._paths)
        results: list[tuple[Path, list, int, int]] = []

        for i, img_path in enumerate(self._paths):
            if self._stop.is_set():
                break
            self.progress.emit(i, total, img_path.name)
            try:
                annotations = _infer_to_annotations(
                    self._model, img_path, infer_size, device, classes,
                    should_stop=self._stop.is_set,
                )
                with Image.open(str(img_path)) as img:
                    results.append((img_path, annotations, img.width, img.height))
                self.image_done.emit(img_path.name)
            except Exception:
                continue  # 개별 이미지 실패 시 계속 진행

        self.finished.emit(len(results), results)


def commit_results(results: list[tuple[Path, list, int, int]]) -> int:
    """미리보기 확인 후 디스크에 저장."""
    n = 0
    for img_path, annotations, w, h in results:
        try:
            save(img_path, annotations, w, h)
            n += 1
        except Exception:
            continue
    return n


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────

def collect_unlabeled(image_dir: Path | None = None) -> list[Path]:
    """어노테이션이 없고 OK 표시도 안 된 이미지만 반환.
    OK 이미지는 이미 검수 완료이므로 자동 라벨링 대상에서 제외."""
    if image_dir is None:
        image_dir = _project.images_dir()
    result = []
    for p in sorted(image_dir.iterdir()):
        if p.suffix.lower() not in SUPPORTED_EXTS:
            continue
        # get_label_status() 1회 read로 OK/라벨 존재 여부를 함께 판별
        # (기존: get_ok() + load() 2회 read와 동치 — "unlabeled"만 자동 라벨링 대상)
        if get_label_status(p) != "unlabeled":
            continue
        result.append(p)
    return result


def collect_all_images(image_dir: Path | None = None) -> list[Path]:
    if image_dir is None:
        image_dir = _project.images_dir()
    return sorted(
        p for p in image_dir.iterdir()
        if p.suffix.lower() in SUPPORTED_EXTS
    )


def _infer_to_annotations(
    model: nn.Module,
    img_path: Path,
    infer_size: tuple[int, int],
    device: torch.device,
    classes: list[ClassDef],
    should_stop: Callable[[], bool] | None = None,
) -> list[AnnotationItem]:
    import torchvision.transforms.functional as TF  # 지연 임포트 — 콜드 기동 단축

    with Image.open(str(img_path)) as opened:
        pil_img = opened.convert("RGB")
    orig_w, orig_h = pil_img.size
    patch_w, patch_h = infer_size
    if patch_w <= 0 or patch_h <= 0:
        raise ValueError(f"Invalid inference patch size: {infer_size}")

    # 원본 픽셀 좌표를 유지한다. 작은 이미지는 우측·하단만 패딩하고 추론 후 crop한다.
    padded_w = max(orig_w, patch_w)
    padded_h = max(orig_h, patch_h)
    image_np = np.asarray(pil_img, dtype=np.uint8)
    image_np = np.pad(
        image_np,
        ((0, padded_h - orig_h), (0, padded_w - orig_w), (0, 0)),
        mode="edge",
    )

    overlap_x = min(64, patch_w // 4)
    overlap_y = min(64, patch_h // 4)
    x_starts = _patch_starts(padded_w, patch_w, patch_w - overlap_x)
    y_starts = _patch_starts(padded_h, patch_h, patch_h - overlap_y)
    coords = [(x, y) for y in y_starts for x in x_starts]

    probabilities: np.ndarray | None = None
    counts = np.zeros((padded_h, padded_w), dtype=np.float32)
    batch_size = 4
    for offset in range(0, len(coords), batch_size):
        if should_stop is not None and should_stop():
            raise InterruptedError("Auto-labeling cancelled")
        batch_coords = coords[offset:offset + batch_size]
        tensors = []
        for x, y in batch_coords:
            patch = image_np[y:y + patch_h, x:x + patch_w]
            tensor = TF.normalize(TF.to_tensor(patch), IMAGENET_MEAN, IMAGENET_STD)
            tensors.append(tensor)
        batch = torch.stack(tensors).to(device)
        with torch.no_grad():
            output = model(batch)
            if output.shape[-2:] != (patch_h, patch_w):
                output = torch.nn.functional.interpolate(
                    output, size=(patch_h, patch_w), mode="bilinear", align_corners=False
                )
            batch_probs = torch.softmax(output, dim=1).cpu().numpy().astype(np.float32)

        if probabilities is None:
            probabilities = np.zeros(
                (batch_probs.shape[1], padded_h, padded_w), dtype=np.float32
            )
        for index, (x, y) in enumerate(batch_coords):
            probabilities[:, y:y + patch_h, x:x + patch_w] += batch_probs[index]
            counts[y:y + patch_h, x:x + patch_w] += 1.0

    if probabilities is None:
        raise RuntimeError("No inference patches were generated")
    probabilities /= np.maximum(counts, 1.0)[None]
    class_map = probabilities.argmax(axis=0)[:orig_h, :orig_w].astype(np.int64)

    annotations: list[AnnotationItem] = []
    for cls in classes:
        if cls.class_id == 0:
            continue
        mask = (class_map == cls.class_id).astype(np.uint8)
        if not mask.any():
            continue
        annotations.append(AnnotationItem(
            annotation_id = new_id(),
            class_id      = cls.class_id,
            type          = "brush_mask",
            order         = len(annotations),
            mask          = mask,
            width         = orig_w,
            height        = orig_h,
        ))
    return annotations


def _patch_starts(image_size: int, patch_size: int, stride: int) -> list[int]:
    """모든 픽셀을 덮고 마지막 패치를 이미지 경계에 맞춘 시작점 목록."""
    last = image_size - patch_size
    starts = list(range(0, last + 1, max(1, stride)))
    if starts[-1] != last:
        starts.append(last)
    return starts


def _pick_device() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")
