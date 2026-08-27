from pathlib import Path

import numpy as np
import pytest
import torch
from PIL import Image

from app.core.annotation_store import ClassDef
from app.core.auto_labeler import _infer_to_annotations, _patch_starts


class PixelClassifier(torch.nn.Module):
    """패치 위치와 무관하게 밝은 red 픽셀을 class 1로 분류한다."""

    def __init__(self, output_scale: int = 1) -> None:
        super().__init__()
        self.output_scale = output_scale
        self.batch_sizes: list[int] = []

    def forward(self, batch: torch.Tensor) -> torch.Tensor:
        self.batch_sizes.append(batch.shape[0])
        red = batch[:, :1]
        logits = torch.cat((-red, red), dim=1)
        if self.output_scale != 1:
            logits = torch.nn.functional.avg_pool2d(logits, self.output_scale)
        return logits


@pytest.fixture
def classes() -> list[ClassDef]:
    return [
        ClassDef(class_id=0, name="background", color="#000000"),
        ClassDef(class_id=1, name="defect", color="#ff0000"),
    ]


def _save_image(path: Path, width: int, height: int, bright_from_x: int) -> None:
    pixels = np.zeros((height, width, 3), dtype=np.uint8)
    pixels[:, bright_from_x:, 0] = 255
    Image.fromarray(pixels).save(path)


def test_patch_starts_covers_edge_without_duplicate() -> None:
    assert _patch_starts(130, 64, 48) == [0, 48, 66]
    assert _patch_starts(64, 64, 48) == [0]


def test_small_image_is_edge_padded_then_cropped(tmp_path: Path, classes) -> None:
    image_path = tmp_path / "small.png"
    _save_image(image_path, 19, 11, 9)
    annotations = _infer_to_annotations(
        PixelClassifier(), image_path, (32, 24), torch.device("cpu"), classes
    )
    assert len(annotations) == 1
    assert annotations[0].mask.shape == (11, 19)
    assert annotations[0].width == 19
    assert annotations[0].height == 11
    assert annotations[0].mask[:, :9].sum() == 0
    assert annotations[0].mask[:, 9:].all()


def test_large_image_uses_batched_overlapping_patches_at_original_size(
    tmp_path: Path, classes
) -> None:
    image_path = tmp_path / "large.png"
    _save_image(image_path, 130, 90, 65)
    model = PixelClassifier()
    annotations = _infer_to_annotations(
        model, image_path, (64, 48), torch.device("cpu"), classes
    )
    mask = annotations[0].mask
    assert mask.shape == (90, 130)
    assert not mask[:, :65].any()
    assert mask[:, 65:].all()
    assert len(model.batch_sizes) > 1
    assert max(model.batch_sizes) <= 4


def test_model_output_is_restored_to_patch_and_original_size(tmp_path: Path, classes) -> None:
    image_path = tmp_path / "scaled-output.png"
    _save_image(image_path, 73, 51, 36)
    annotations = _infer_to_annotations(
        PixelClassifier(output_scale=2), image_path, (32, 24), torch.device("cpu"), classes
    )
    assert annotations[0].mask.shape == (51, 73)
    assert annotations[0].width == 73
    assert annotations[0].height == 51


def test_cancellation_is_checked_between_patch_batches(tmp_path: Path, classes) -> None:
    image_path = tmp_path / "cancel.png"
    _save_image(image_path, 130, 90, 65)
    checks = iter((False, True))

    with pytest.raises(InterruptedError, match="cancelled"):
        _infer_to_annotations(
            PixelClassifier(), image_path, (32, 24), torch.device("cpu"), classes,
            should_stop=lambda: next(checks),
        )
