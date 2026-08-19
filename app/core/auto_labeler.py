"""오토 라벨러 — 학습된 모델로 미라벨 이미지를 자동 어노테이션."""
import threading
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
                    self._model, img_path, infer_size, device, classes
                )
                img = Image.open(str(img_path))
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
) -> list[AnnotationItem]:
    import torchvision.transforms.functional as TF  # 지연 임포트 — 콜드 기동 단축

    pil_img = Image.open(str(img_path)).convert("RGB")
    orig_w, orig_h = pil_img.size

    resized = pil_img.resize(infer_size, Image.BILINEAR)
    img_np  = np.array(resized, dtype=np.uint8)
    tensor  = TF.to_tensor(img_np)
    tensor  = TF.normalize(tensor, IMAGENET_MEAN, IMAGENET_STD)
    tensor  = tensor.unsqueeze(0).to(device)

    with torch.no_grad():
        output = model(tensor)

    class_map_small = output.argmax(dim=1).squeeze(0).cpu().numpy().astype(np.uint8)
    class_map = np.array(
        Image.fromarray(class_map_small).resize((orig_w, orig_h), Image.NEAREST),
        dtype=np.int64,
    )

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


def _pick_device() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")
