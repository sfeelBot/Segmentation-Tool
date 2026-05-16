"""QThread 기반 학습 루프 + TrainingConfig."""
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, random_split
from PyQt6.QtCore import QThread, pyqtSignal

from app.core.dataset import SegmentationDataset
from app.core.augmentations import build_pipeline
from app.core.metrics import compute_metrics
from app.core.logger import get_logger
from app.core.device_info import pick_device, should_use_amp, format_oom_help
from app.core import project as _project

log = get_logger(__name__)


# ── 설정 dataclass ────────────────────────────────────────────────────────────

@dataclass
class TrainingConfig:
    epochs: int              = 50
    batch_size: int          = 4
    image_w: int             = 512
    image_h: int             = 512
    lr: float                = 1e-4
    optimizer: str           = "Adam"
    weight_decay: float      = 0.0
    momentum: float          = 0.9
    loss_fn: str             = "CrossEntropyLoss"
    mixed_precision: bool    = True
    device: str              = "auto"
    checkpoint_every: int    = 5
    val_split: float         = 0.2
    num_workers: int         = 0
    augmentations: list[dict] = field(default_factory=list)
    # ── 패치 학습 설정 ──────────────────────────────────────────────────────
    sample_mode: str          = "random_crop"   # "resize" | "random_crop" | "center_crop"
    defect_sample_prob: float = 0.7             # 결함 중심 샘플링 확률 (random_crop 모드)
    patches_per_image: int    = 50              # epoch당 이미지 1장에서 추출할 패치 수


# ── Worker ────────────────────────────────────────────────────────────────────

class TrainerWorker(QThread):
    training_started  = pyqtSignal(int, int)   # total_train_batches, total_epochs
    epoch_done        = pyqtSignal(int, float, float, dict)
    # epoch, train_loss, val_loss, {"mean_iou": float, "mean_dice": float}
    batch_done        = pyqtSignal(int, int, float)
    # epoch, batch_idx, loss
    checkpoint_saved  = pyqtSignal(str)
    training_finished = pyqtSignal()
    training_error    = pyqtSignal(str)

    def __init__(
        self,
        model: nn.Module,
        config: TrainingConfig,
        num_classes: int,
        ckpt_prefix: str = "",
        model_source: str = "loaded",
    ) -> None:
        super().__init__()
        self._model        = model
        self._cfg          = config
        self._num_classes  = num_classes
        self._ckpt_prefix  = ckpt_prefix
        self._model_source = model_source
        self._stop         = threading.Event()

    def request_stop(self) -> None:
        self._stop.set()

    # ── QThread.run ───────────────────────────────────────────────────────────

    def run(self) -> None:
        try:
            log.info(
                f"학습 시작 — epochs={self._cfg.epochs}, batch={self._cfg.batch_size}, "
                f"image={self._cfg.image_w}x{self._cfg.image_h}, lr={self._cfg.lr}, "
                f"opt={self._cfg.optimizer}, loss={self._cfg.loss_fn}, "
                f"device={self._cfg.device}, amp={self._cfg.mixed_precision}"
            )
            self._train()
            log.info("학습 정상 종료")
        except RuntimeError as exc:
            msg = str(exc)
            if "out of memory" in msg.lower() or "CUDA out of memory" in msg:
                log.error(f"CUDA OOM: {msg}")
                try:
                    torch.cuda.empty_cache()
                except Exception:
                    pass
                self.training_error.emit(format_oom_help(
                    self._cfg.batch_size, self._cfg.image_w, self._cfg.image_h,
                ) + f"\n\n[원문] {msg}")
            else:
                log.exception("학습 중 RuntimeError")
                self.training_error.emit(f"{type(exc).__name__}: {msg}")
        except Exception as exc:
            log.exception("학습 중 예외")
            self.training_error.emit(f"{type(exc).__name__}: {exc}")

    def _train(self) -> None:
        cfg    = self._cfg
        device = pick_device(cfg.device)
        log.info(f"선택된 디바이스: {device}")

        # 데이터셋
        aug = build_pipeline(cfg.augmentations) if cfg.augmentations else None
        log.info(
            f"샘플링 모드: {cfg.sample_mode}"
            + (f"  (결함 우선 확률: {cfg.defect_sample_prob:.0%})"
               if cfg.sample_mode == "random_crop" else "")
        )
        try:
            # 학습: 지정된 샘플링 모드 사용
            dataset = SegmentationDataset(
                image_size=(cfg.image_w, cfg.image_h),
                mode=cfg.sample_mode,
                defect_sample_prob=cfg.defect_sample_prob,
                patches_per_image=cfg.patches_per_image,
                augment_fn=aug,
            )
        except Exception as e:
            log.exception("데이터셋 구성 실패")
            raise RuntimeError(f"데이터셋 구성 실패: {e}") from e
        log.info(f"데이터셋 로드 완료 — 총 {len(dataset)} 샘플")

        if len(dataset) == 0:
            raise RuntimeError(
                "학습 데이터가 없습니다.\n"
                "이미지를 추가하고 라벨링 탭에서 어노테이션하세요."
            )

        val_n   = max(1, int(len(dataset) * cfg.val_split))
        train_n = len(dataset) - val_n
        if train_n == 0:
            raise RuntimeError("train 데이터가 부족합니다 (val_split 을 줄이세요).")
        log.info(f"Train/Val 분할: {train_n} (×{cfg.patches_per_image}패치) / {val_n}")
        train_ds, val_ds_raw = random_split(dataset, [train_n, val_n])
        # Validation 은 항상 resize — 패치 랜덤성으로 인한 손실 변동 방지
        if cfg.sample_mode != "resize":
            val_ds = SegmentationDataset(
                image_size=(cfg.image_w, cfg.image_h),
                mode="resize",
            )
            # val_ds_raw 의 인덱스만 사용하는 서브셋으로 교체
            val_indices = list(val_ds_raw.indices)
            val_ds = _IndexedSubset(val_ds, val_indices)
        else:
            val_ds = val_ds_raw

        pin = device.type == "cuda"
        train_loader = DataLoader(
            train_ds, batch_size=cfg.batch_size, shuffle=True,
            num_workers=cfg.num_workers, pin_memory=pin,
        )
        val_loader = DataLoader(
            val_ds, batch_size=cfg.batch_size, shuffle=False,
            num_workers=cfg.num_workers,
        )

        try:
            model = self._model.to(device)
        except Exception as e:
            log.exception("모델을 디바이스로 이동 실패")
            raise RuntimeError(
                f"모델을 {device} 로 옮길 수 없습니다: {e}\n"
                f"CUDA 메모리 상태와 드라이버를 확인하세요."
            ) from e

        optimizer  = _build_optimizer(model, cfg)
        loss_fn    = _build_loss_fn(cfg.loss_fn, device)
        use_amp    = should_use_amp(device, cfg.mixed_precision)
        log.info(f"Mixed precision: {use_amp}  |  pin_memory: {pin}  |  num_workers: {cfg.num_workers}")
        try:
            scaler = torch.amp.GradScaler("cuda", enabled=use_amp)
        except (AttributeError, TypeError):
            # 구 PyTorch 호환
            scaler = torch.cuda.amp.GradScaler(enabled=use_amp)

        _project.checkpoints_dir().mkdir(parents=True, exist_ok=True)
        self.training_started.emit(len(train_loader), cfg.epochs)
        log.info(f"배치 수/epoch: {len(train_loader)}, 총 epochs: {cfg.epochs}")

        for epoch in range(1, cfg.epochs + 1):
            if self._stop.is_set():
                break
            epoch_start = time.time()

            # ── Train ─────────────────────────────────────────────────────────
            model.train()
            train_loss = 0.0
            for batch_idx, (images, masks) in enumerate(train_loader):
                if self._stop.is_set():
                    break
                images = images.to(device, non_blocking=True)
                masks  = masks.to(device,  non_blocking=True)
                optimizer.zero_grad()
                with torch.autocast(device.type, enabled=use_amp):
                    output = model(images)
                    loss   = loss_fn(output, masks)
                scaler.scale(loss).backward()
                scaler.step(optimizer)
                scaler.update()
                train_loss += loss.item()
                self.batch_done.emit(epoch, batch_idx, loss.item())

            if len(train_loader) > 0:
                train_loss /= len(train_loader)

            # ── Validation ────────────────────────────────────────────────────
            model.eval()
            val_loss = 0.0
            all_preds, all_masks = [], []
            with torch.no_grad():
                for images, masks in val_loader:
                    images = images.to(device, non_blocking=True)
                    masks  = masks.to(device,  non_blocking=True)
                    with torch.autocast(device.type, enabled=use_amp):
                        output = model(images)
                        val_loss += loss_fn(output, masks).item()
                    preds = output.argmax(dim=1)
                    all_preds.append(preds.cpu())
                    all_masks.append(masks.cpu())

            if len(val_loader) > 0:
                val_loss /= len(val_loader)

            metrics = compute_metrics(
                torch.cat(all_preds),
                torch.cat(all_masks),
                self._num_classes,
            ) if all_preds else {"mean_iou": 0.0, "mean_dice": 0.0}

            metrics["epoch_time"] = time.time() - epoch_start
            self.epoch_done.emit(epoch, train_loss, val_loss, metrics)

            # ── Checkpoint ────────────────────────────────────────────────────
            if epoch % cfg.checkpoint_every == 0:
                prefix = f"{self._ckpt_prefix}_" if self._ckpt_prefix else ""
                path = _project.checkpoints_dir() / f"{prefix}epoch_{epoch:04d}.pt"
                torch.save({
                    "epoch":                epoch,
                    "model_state_dict":     model.state_dict(),
                    "optimizer_state_dict": optimizer.state_dict(),
                    "train_loss":           train_loss,
                    "val_loss":             val_loss,
                    "metrics":              metrics,
                    "config":               {
                        "image_w": cfg.image_w, "image_h": cfg.image_h,
                        "sample_mode": cfg.sample_mode,
                        "model_source": self._model_source,
                    },
                }, path)
                self.checkpoint_saved.emit(str(path))

        self.training_finished.emit()


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────

class _IndexedSubset(torch.utils.data.Dataset):
    """SegmentationDataset 에서 특정 인덱스만 뽑는 래퍼 (val resize 용)."""
    def __init__(self, dataset: SegmentationDataset, indices: list[int]) -> None:
        self._ds = dataset
        self._idx = indices
    def __len__(self) -> int:
        return len(self._idx)
    def __getitem__(self, i: int):
        return self._ds[self._idx[i]]


def _build_optimizer(model: nn.Module, cfg: TrainingConfig):
    params = model.parameters()
    if cfg.optimizer == "Adam":
        return torch.optim.Adam(params, lr=cfg.lr, weight_decay=cfg.weight_decay)
    if cfg.optimizer == "AdamW":
        return torch.optim.AdamW(params, lr=cfg.lr, weight_decay=cfg.weight_decay)
    if cfg.optimizer == "SGD":
        return torch.optim.SGD(params, lr=cfg.lr,
                               weight_decay=cfg.weight_decay,
                               momentum=cfg.momentum)
    if cfg.optimizer == "RMSprop":
        return torch.optim.RMSprop(params, lr=cfg.lr, weight_decay=cfg.weight_decay)
    return torch.optim.Adam(params, lr=cfg.lr)


def _build_loss_fn(name: str, device: torch.device) -> nn.Module:
    if name == "CrossEntropyLoss":
        return nn.CrossEntropyLoss()
    if name == "DiceLoss":
        return _DiceLoss()
    if name == "FocalLoss":
        return _FocalLoss()
    return nn.CrossEntropyLoss()


class _DiceLoss(nn.Module):
    def forward(self, logits: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        num_classes = logits.shape[1]
        probs  = torch.softmax(logits, dim=1)
        target_oh = torch.zeros_like(probs)
        target_oh.scatter_(1, targets.unsqueeze(1), 1)
        dims   = (0, 2, 3)
        inter  = (probs * target_oh).sum(dims)
        union  = (probs + target_oh).sum(dims)
        dice   = (2 * inter + 1e-6) / (union + 1e-6)
        return 1 - dice.mean()


class _FocalLoss(nn.Module):
    def __init__(self, gamma: float = 2.0) -> None:
        super().__init__()
        self._gamma = gamma

    def forward(self, logits: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        ce = torch.nn.functional.cross_entropy(logits, targets, reduction="none")
        pt = torch.exp(-ce)
        return ((1 - pt) ** self._gamma * ce).mean()
