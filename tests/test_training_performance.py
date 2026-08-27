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


def test_stop_after_train_batch_skips_validation_and_checkpoint(monkeypatch, tmp_path):
    class TinyDataset(Dataset):
        def __init__(self, *args, mode="random_crop", **kwargs):
            self._patches_per_img = 1
            self.num_pairs = 2

        def __len__(self):
            return self.num_pairs

        def __getitem__(self, index):
            return torch.ones((3, 4, 4)), torch.zeros((4, 4), dtype=torch.long)

    class StopAfterForward(torch.nn.Module):
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

    monkeypatch.setattr(trainer, "SegmentationDataset", TinyDataset)
    monkeypatch.setattr(trainer, "pick_device", lambda _choice: torch.device("cpu"))
    monkeypatch.setattr(trainer, "should_use_amp", lambda *_args: False)
    monkeypatch.setattr(trainer._project, "checkpoints_dir", lambda: tmp_path)
    monkeypatch.setattr(torch, "save", lambda *_args, **_kwargs: pytest.fail("checkpoint saved"))

    model = StopAfterForward()
    worker = trainer.TrainerWorker(
        model,
        trainer.TrainingConfig(epochs=1, batch_size=1, image_w=4, image_h=4,
                               val_split=0.5, num_workers=0, checkpoint_every=1),
        num_classes=2,
    )
    model.worker = worker

    worker._train()

    assert model.calls == 1
