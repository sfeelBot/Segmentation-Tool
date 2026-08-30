import json

import pytest
import torch
from torch.utils.data import Dataset

from app.core.metrics import StreamingSegmentationMetrics, compute_metrics
from app.core import trainer


def test_streaming_metrics_matches_single_tensor_computation():
    preds = torch.tensor([
        [[0, 1], [1, 1]],
        [[0, 0], [1, 2]],
    ])
    targets = torch.tensor([
        [[0, 1], [2, 255]],
        [[0, 1], [1, 2]],
    ])

    streaming = StreamingSegmentationMetrics(num_classes=3)
    streaming.update(preds[:1], targets[:1])
    streaming.update(preds[1:], targets[1:])

    assert streaming.compute() == compute_metrics(preds, targets, 3)


def test_streaming_metrics_keeps_only_fixed_size_confusion_matrix():
    streaming = StreamingSegmentationMetrics(num_classes=4)
    for _ in range(10):
        streaming.update(torch.zeros((2, 64, 64), dtype=torch.long),
                         torch.zeros((2, 64, 64), dtype=torch.long))

    assert streaming.confusion.shape == (4, 4)
    assert streaming.confusion.sum().item() == 10 * 2 * 64 * 64
    assert streaming.compute() == {"mean_iou": 1.0, "mean_dice": 1.0}


class _TinyFourImageDataset(Dataset):
    """4장 이미지짜리 합성 데이터셋. val_split=0.25 → train 3배치 / val 1배치
    (batch_size=1 기준)로 고정돼 BUG-026 테스트들이 배치 수를 예측 가능하게 만든다."""
    def __init__(self, *args, mode="random_crop", **kwargs):
        self._patches_per_img = 1
        self.num_pairs = 4

    def __len__(self):
        return self.num_pairs

    def __getitem__(self, index):
        return torch.ones((3, 4, 4)), torch.zeros((4, 4), dtype=torch.long)


def test_stop_mid_epoch_skips_remaining_batches_but_preserves_epoch(monkeypatch, tmp_path):
    """BUG-026 회귀 수정 확인: 중지 요청 시 남은 학습 배치는 건너뛰어(응답성 유지)
    지금까지 처리한 배치만으로 validation·체크포인트·지표 파일을 이 부분 epoch에
    대해서도 저장해야 한다 — 1 epoch도 못 채웠다고 전부 유실되면 안 된다."""
    class StopAfterFirstForward(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.weight = torch.nn.Parameter(torch.tensor(1.0))
            self.worker = None
            self.calls = 0

        def forward(self, images):
            self.calls += 1
            if self.calls == 1:
                self.worker.request_stop()
            logits = torch.stack((images[:, 0], -images[:, 0]), dim=1)
            return logits * self.weight

    monkeypatch.setattr(trainer, "SegmentationDataset", _TinyFourImageDataset)
    monkeypatch.setattr(trainer, "pick_device", lambda _choice: torch.device("cpu"))
    monkeypatch.setattr(trainer, "should_use_amp", lambda *_args: False)
    monkeypatch.setattr(trainer._project, "checkpoints_dir", lambda: tmp_path)

    model = StopAfterFirstForward()
    worker = trainer.TrainerWorker(
        model,
        trainer.TrainingConfig(epochs=1, batch_size=1, image_w=4, image_h=4,
                               val_split=0.25, num_workers=0, checkpoint_every=1),
        num_classes=2,
    )
    model.worker = worker

    worker._train()

    # 응답성: train 배치 3개 중 1개만 처리되고 나머지 2개는 건너뛴다.
    # validation 배치(1개)는 예정대로 실행돼 총 forward 호출은 2회.
    assert model.calls == 2

    assert list(tmp_path.glob("*.pt")), \
        "1 epoch도 못 채우고 중지해도 체크포인트는 최소 1개 저장돼야 한다"
    assert (tmp_path / "training_metrics.json").exists()
    assert (tmp_path / "training_metrics.png").exists()


def test_training_completes_without_stop_saves_each_epoch(monkeypatch, tmp_path):
    """회귀 확인: 중지 없이 정상 완주하면 매 epoch 체크포인트·지표가 그대로 저장된다."""
    class TinyModel(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.weight = torch.nn.Parameter(torch.tensor(1.0))

        def forward(self, images):
            logits = torch.stack((images[:, 0], -images[:, 0]), dim=1)
            return logits * self.weight

    monkeypatch.setattr(trainer, "SegmentationDataset", _TinyFourImageDataset)
    monkeypatch.setattr(trainer, "pick_device", lambda _choice: torch.device("cpu"))
    monkeypatch.setattr(trainer, "should_use_amp", lambda *_args: False)
    monkeypatch.setattr(trainer._project, "checkpoints_dir", lambda: tmp_path)

    worker = trainer.TrainerWorker(
        TinyModel(),
        trainer.TrainingConfig(epochs=2, batch_size=1, image_w=4, image_h=4,
                               val_split=0.25, num_workers=0, checkpoint_every=1),
        num_classes=2,
    )

    worker._train()

    assert sorted(p.name for p in tmp_path.glob("epoch_*.pt")) == [
        "epoch_0001.pt", "epoch_0002.pt",
    ]
    assert (tmp_path / "best.pt").exists()
    history = json.loads((tmp_path / "training_metrics.json").read_text())
    assert [row["epoch"] for row in history] == [1, 2]


def test_stop_mid_second_epoch_preserves_first_epoch_and_halts_before_third(
    monkeypatch, tmp_path,
):
    """회귀 확인: 2번째 epoch 도중 중지해도 1번째 epoch 결과는 (기존 보장대로)
    보존되고, BUG-026 수정 덕에 2번째(부분) epoch 결과도 저장되며, 3번째 epoch는
    아예 시작되지 않는다."""
    class StopOnSecondEpochFirstBatch(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.weight = torch.nn.Parameter(torch.tensor(1.0))
            self.worker = None
            self.calls = 0

        def forward(self, images):
            self.calls += 1
            # epoch1: train 배치 3개(calls 1~3) + val 배치 1개(call 4)
            # epoch2 train 첫 배치가 call 5 — 여기서 중지 요청
            if self.calls == 5:
                self.worker.request_stop()
            logits = torch.stack((images[:, 0], -images[:, 0]), dim=1)
            return logits * self.weight

    monkeypatch.setattr(trainer, "SegmentationDataset", _TinyFourImageDataset)
    monkeypatch.setattr(trainer, "pick_device", lambda _choice: torch.device("cpu"))
    monkeypatch.setattr(trainer, "should_use_amp", lambda *_args: False)
    monkeypatch.setattr(trainer._project, "checkpoints_dir", lambda: tmp_path)

    model = StopOnSecondEpochFirstBatch()
    worker = trainer.TrainerWorker(
        model,
        trainer.TrainingConfig(epochs=3, batch_size=1, image_w=4, image_h=4,
                               val_split=0.25, num_workers=0, checkpoint_every=1),
        num_classes=2,
    )
    model.worker = worker

    worker._train()

    # 응답성: epoch2 의 남은 train 배치 2개(calls 6~7 자리)는 건너뛰고 val
    # 배치 1개만 이어서 처리 → 총 forward 호출 6회 (epoch1: 4 + epoch2: 2).
    assert model.calls == 6

    history = json.loads((tmp_path / "training_metrics.json").read_text())
    assert [row["epoch"] for row in history] == [1, 2]
    assert (tmp_path / "epoch_0001.pt").exists()
    assert (tmp_path / "epoch_0002.pt").exists()
    assert not (tmp_path / "epoch_0003.pt").exists()
