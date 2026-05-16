"""세그멘테이션 메트릭 — mean IoU, mean Dice."""
import torch


def compute_metrics(
    preds: torch.Tensor,   # (N, H, W) int64
    targets: torch.Tensor, # (N, H, W) int64
    num_classes: int,
    ignore_index: int = 255,
) -> dict[str, float]:
    iou_list:  list[float] = []
    dice_list: list[float] = []

    for c in range(num_classes):
        pred_c   = preds   == c
        target_c = targets == c
        # ignore_index 마스크
        valid    = targets != ignore_index
        pred_c   = pred_c  & valid
        target_c = target_c & valid

        tp = (pred_c & target_c).sum().item()
        fp = (pred_c & ~target_c).sum().item()
        fn = (~pred_c & target_c).sum().item()

        union = tp + fp + fn
        iou  = tp / union if union > 0 else float("nan")
        dice = (2 * tp) / (2 * tp + fp + fn) if (2 * tp + fp + fn) > 0 else float("nan")

        if not (tp + fn == 0):   # 클래스가 타겟에 없으면 제외
            iou_list.append(iou)
            dice_list.append(dice)

    mean_iou  = _nanmean(iou_list)
    mean_dice = _nanmean(dice_list)

    return {
        "mean_iou":  round(mean_iou,  4),
        "mean_dice": round(mean_dice, 4),
    }


def _nanmean(values: list[float]) -> float:
    valid = [v for v in values if v == v]  # NaN 제거
    return sum(valid) / len(valid) if valid else 0.0
