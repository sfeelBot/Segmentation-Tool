"""QThread 기반 학습 루프 + TrainingConfig."""
import math
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
    # ── LR 스케쥴러 ─────────────────────────────────────────────────────────
    # 종류: none | step | exp | cosine | cosine_restart | plateau |
    #       onecycle | warmup_cosine | poly
    scheduler: str           = "none"
    # StepLR / ExponentialLR 공통
    sched_step_size: int     = 10    # StepLR: N 에폭마다 감소
    sched_gamma: float       = 0.5   # StepLR/Exp: 감소 배율
    # CosineAnnealingLR / WarmRestarts / WarmupCosine 공통
    sched_T_max: int         = 0     # Cosine: 0 = auto(=epochs), 주기 에폭 수
    sched_T_0: int           = 10    # WarmRestarts: 첫 재시작 주기
    sched_T_mult: int        = 2     # WarmRestarts: 재시작마다 주기 배율
    sched_eta_min: float     = 1e-6  # Cosine 계열: 최소 LR
    # ReduceLROnPlateau
    sched_patience: int      = 5     # Plateau: 개선 없으면 몇 에폭 대기
    sched_factor: float      = 0.5   # Plateau/OneCycle: 감소 배율
    sched_min_lr: float      = 1e-7  # Plateau: 최솟값 LR
    # OneCycleLR
    sched_max_lr: float      = 0.0   # OneCycle: 피크 LR (0 = lr×10 자동)
    sched_pct_start: float   = 0.3   # OneCycle: 웜업 비율 (전체 스텝)
    # WarmupCosine
    sched_warmup_epochs: int = 5     # WarmupCosine: 선형 웜업 에폭 수
    # PolynomialLR
    sched_power: float       = 0.9   # Poly: 지수


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

        # ── 이미지 단위 Train/Val 분할 ─────────────────────────────────────────
        # random_split(dataset, ...) 은 패치 단위로 분할 → 동일 이미지가 train/val
        # 양쪽에 등장해 val 이 training 이미지의 다른 크롭이 됨 (overfitting 감지 불가).
        # 이미지 인덱스 자체를 셔플해서 이미지 단위로 분할한다.
        import random as _rnd
        num_images = dataset.num_pairs
        val_n_img  = max(1, int(num_images * cfg.val_split))
        train_n_img = num_images - val_n_img
        if train_n_img == 0:
            raise RuntimeError("train 데이터가 부족합니다 (val_split 을 줄이세요).")

        all_img_idx = list(range(num_images))
        _rnd.shuffle(all_img_idx)
        val_img_idx   = sorted(all_img_idx[:val_n_img])
        train_img_idx = sorted(all_img_idx[val_n_img:])
        log.info(f"Train/Val 이미지 단위 분할: {train_n_img} / {val_n_img}  "
                 f"(×{cfg.patches_per_image} 패치/epoch)")

        # Training: 학습 이미지만 패치 샘플링
        train_ds = _TrainImageSubset(dataset, train_img_idx)

        # Validation: 검증 이미지만 resize 로 일관되게 평가
        val_ds_resize = SegmentationDataset(
            image_size=(cfg.image_w, cfg.image_h),
            mode="resize",
        )
        val_ds = _IndexedSubset(val_ds_resize, val_img_idx)

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
            scaler = torch.cuda.amp.GradScaler(enabled=use_amp)

        scheduler      = _build_scheduler(optimizer, cfg, len(train_loader))
        _is_onecycle   = cfg.scheduler == "onecycle"    # 배치마다 step
        _is_plateau    = cfg.scheduler == "plateau"     # val_loss 기반 step
        if scheduler:
            log.info(f"LR 스케쥴러: {cfg.scheduler}  (초기 LR: {cfg.lr:.2e})")
        else:
            log.info(f"LR 스케쥴러: 없음 (고정 {cfg.lr:.2e})")

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
                # OneCycleLR: 배치마다 step
                if _is_onecycle and scheduler is not None:
                    scheduler.step()

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

            # ── 에폭 단위 스케쥴러 step ───────────────────────────────────────
            if scheduler is not None and not _is_onecycle:
                if _is_plateau:
                    scheduler.step(val_loss)   # ReduceLROnPlateau: val_loss 기반
                else:
                    scheduler.step()

            current_lr = optimizer.param_groups[0]["lr"]

            metrics = compute_metrics(
                torch.cat(all_preds),
                torch.cat(all_masks),
                self._num_classes,
            ) if all_preds else {"mean_iou": 0.0, "mean_dice": 0.0}

            metrics["epoch_time"] = time.time() - epoch_start
            metrics["current_lr"] = current_lr   # UI·체크포인트에 기록
            self.epoch_done.emit(epoch, train_loss, val_loss, metrics)
            log.debug(f"epoch {epoch}  train={train_loss:.4f}  val={val_loss:.4f}"
                      f"  LR={current_lr:.3e}")

            # ── Checkpoint ────────────────────────────────────────────────────
            if epoch % cfg.checkpoint_every == 0:
                prefix = f"{self._ckpt_prefix}_" if self._ckpt_prefix else ""
                path = _project.checkpoints_dir() / f"{prefix}epoch_{epoch:04d}.pt"
                torch.save({
                    "epoch":                epoch,
                    "model_state_dict":     model.state_dict(),
                    "optimizer_state_dict": optimizer.state_dict(),
                    "scheduler_state_dict": scheduler.state_dict() if scheduler else None,
                    "train_loss":           train_loss,
                    "val_loss":             val_loss,
                    "metrics":              metrics,
                    "config":               {
                        "image_w":      cfg.image_w,
                        "image_h":      cfg.image_h,
                        "sample_mode":  cfg.sample_mode,
                        "model_source": self._model_source,
                        "scheduler":    cfg.scheduler,
                    },
                }, path)
                self.checkpoint_saved.emit(str(path))

        self.training_finished.emit()


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────

class _IndexedSubset(torch.utils.data.Dataset):
    """SegmentationDataset 에서 특정 이미지 인덱스만 뽑는 래퍼 (val resize 용)."""
    def __init__(self, dataset: SegmentationDataset, indices: list[int]) -> None:
        self._ds = dataset
        self._idx = indices
    def __len__(self) -> int:
        return len(self._idx)
    def __getitem__(self, i: int):
        return self._ds[self._idx[i]]


class _TrainImageSubset(torch.utils.data.Dataset):
    """학습 이미지 서브셋에서 패치를 샘플링하는 래퍼.
    random_crop 모드에서 dataset.__getitem__이 같은 idx 를 호출해도
    내부 random.randint 로 매번 다른 크롭 위치를 반환한다."""
    def __init__(self, dataset: SegmentationDataset, image_indices: list[int]) -> None:
        self._ds  = dataset
        self._idx = image_indices
        self._p   = dataset._patches_per_img
    def __len__(self) -> int:
        return len(self._idx) * self._p
    def __getitem__(self, i: int):
        img_in_subset = i % len(self._idx)
        return self._ds[self._idx[img_in_subset]]


def _build_scheduler(optimizer, cfg: TrainingConfig, steps_per_epoch: int):
    """cfg.scheduler 에 따라 PyTorch LR 스케쥴러를 생성해 반환한다.
    스케쥴러가 없으면 None 반환.

    steps_per_epoch : OneCycleLR 전용 — 에폭당 배치 수.
    """
    s = cfg.scheduler
    if s == "none":
        return None

    # ── StepLR: N 에폭마다 LR × gamma ───────────────────────────────────────
    if s == "step":
        return torch.optim.lr_scheduler.StepLR(
            optimizer,
            step_size=max(1, cfg.sched_step_size),
            gamma=cfg.sched_gamma,
        )

    # ── ExponentialLR: 매 에폭 LR × gamma ───────────────────────────────────
    if s == "exp":
        return torch.optim.lr_scheduler.ExponentialLR(
            optimizer,
            gamma=cfg.sched_gamma,
        )

    # ── CosineAnnealingLR: 코사인 감쇠 (재시작 없음) ─────────────────────────
    if s == "cosine":
        T_max = cfg.sched_T_max if cfg.sched_T_max > 0 else cfg.epochs
        return torch.optim.lr_scheduler.CosineAnnealingLR(
            optimizer,
            T_max=T_max,
            eta_min=cfg.sched_eta_min,
        )

    # ── CosineAnnealingWarmRestarts: SGDR 방식 주기 재시작 ───────────────────
    if s == "cosine_restart":
        return torch.optim.lr_scheduler.CosineAnnealingWarmRestarts(
            optimizer,
            T_0=max(1, cfg.sched_T_0),
            T_mult=max(1, cfg.sched_T_mult),
            eta_min=cfg.sched_eta_min,
        )

    # ── ReduceLROnPlateau: val_loss 정체 시 LR 감소 ──────────────────────────
    if s == "plateau":
        return torch.optim.lr_scheduler.ReduceLROnPlateau(
            optimizer,
            mode="min",
            patience=max(1, cfg.sched_patience),
            factor=cfg.sched_factor,
            min_lr=cfg.sched_min_lr,
        )

    # ── OneCycleLR: 웜업 → 피크 → 코사인 감쇠 (배치 단위 step) ─────────────
    if s == "onecycle":
        max_lr      = cfg.sched_max_lr if cfg.sched_max_lr > 0 else cfg.lr * 10
        total_steps = cfg.epochs * max(1, steps_per_epoch)
        return torch.optim.lr_scheduler.OneCycleLR(
            optimizer,
            max_lr=max_lr,
            total_steps=total_steps,
            pct_start=cfg.sched_pct_start,
        )

    # ── WarmupCosine: 선형 웜업 → 코사인 감쇠 (커스텀 LambdaLR) ────────────
    if s == "warmup_cosine":
        warmup  = max(1, cfg.sched_warmup_epochs)
        total   = cfg.epochs
        eta_min = cfg.sched_eta_min
        base_lr = max(cfg.lr, 1e-12)   # ZeroDivision 방지

        def _lr_lambda(epoch: int) -> float:
            if epoch < warmup:
                return (epoch + 1) / warmup            # 선형 웜업
            progress = (epoch - warmup) / max(1, total - warmup)
            cosine   = 0.5 * (1.0 + math.cos(math.pi * progress))
            return eta_min / base_lr + (1.0 - eta_min / base_lr) * cosine

        return torch.optim.lr_scheduler.LambdaLR(optimizer, _lr_lambda)

    # ── PolynomialLR: 다항식 감쇠 (DeepLab 계열 표준) ───────────────────────
    if s == "poly":
        return torch.optim.lr_scheduler.PolynomialLR(
            optimizer,
            total_iters=max(1, cfg.epochs),
            power=cfg.sched_power,
        )

    log.warning(f"알 수 없는 scheduler '{s}' → 스케쥴러 없음으로 처리")
    return None


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
