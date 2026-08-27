"""Segmentation metrics: mean IoU and mean Dice."""
import torch


class StreamingSegmentationMetrics:
    """Accumulate a compact confusion matrix instead of retaining predictions."""

    def __init__(self, num_classes: int, ignore_index: int = 255) -> None:
        self.num_classes = num_classes
        self.ignore_index = ignore_index
        self.confusion = torch.zeros((num_classes, num_classes), dtype=torch.int64)

    def update(self, preds: torch.Tensor, targets: torch.Tensor) -> None:
        preds = preds.detach().reshape(-1)
        targets = targets.detach().reshape(-1)
        valid = ((targets != self.ignore_index) & (targets >= 0)
                 & (targets < self.num_classes) & (preds >= 0)
                 & (preds < self.num_classes))
        encoded = targets[valid] * self.num_classes + preds[valid]
        if encoded.numel():
            batch_confusion = torch.bincount(
                encoded, minlength=self.num_classes ** 2,
            ).reshape(self.num_classes, self.num_classes)
            self.confusion += batch_confusion.to("cpu")

    def compute(self) -> dict[str, float]:
        matrix = self.confusion
        tp = matrix.diag()
        target_count = matrix.sum(dim=1)
        pred_count = matrix.sum(dim=0)
        present = target_count > 0
        if not bool(present.any()):
            return {"mean_iou": 0.0, "mean_dice": 0.0}
        union = target_count + pred_count - tp
        dice_denominator = target_count + pred_count
        iou = tp[present].double() / union[present].clamp_min(1).double()
        dice = 2 * tp[present].double() / dice_denominator[present].clamp_min(1).double()
        return {"mean_iou": round(float(iou.mean()), 4),
                "mean_dice": round(float(dice.mean()), 4)}


def compute_metrics(preds: torch.Tensor, targets: torch.Tensor,
                    num_classes: int, ignore_index: int = 255) -> dict[str, float]:
    """Compatibility wrapper for callers that already hold full tensors."""
    accumulator = StreamingSegmentationMetrics(num_classes, ignore_index)
    accumulator.update(preds, targets)
    return accumulator.compute()


def _nanmean(values: list[float]) -> float:
    """Retained for compatibility with older imports."""
    valid = [v for v in values if v == v]
    return sum(valid) / len(valid) if valid else 0.0
