import torch

from app.core.metrics import StreamingSegmentationMetrics, compute_metrics


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
