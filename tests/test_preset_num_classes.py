import tempfile
from pathlib import Path

import torch

from app.core.model_loader import load_from_code
from app.core.inference_engine import load_model_from_ckpt
from app.model_presets import load_preset_code

_PRESET_CODE = load_preset_code("attention_unet")

_CODE_NO_NUM_CLASSES_PARAM = """
import torch.nn as nn

class CustomModel(nn.Module):
    def __init__(self):
        super().__init__()
        self.conv = nn.Conv2d(3, 2, 1)

    def forward(self, x):
        return self.conv(x)
"""


def test_load_from_code_passes_num_classes_to_preset():
    result = load_from_code(_PRESET_CODE, num_classes=5)
    assert result.ok
    # head 레이어 출력 채널 수가 실제 클래스 수(5)와 일치해야 한다.
    assert result.model.head.out_channels == 5


def test_load_from_code_without_num_classes_keeps_default():
    result = load_from_code(_PRESET_CODE)
    assert result.ok
    assert result.model.head.out_channels == 2


def test_load_from_code_falls_back_when_constructor_has_no_num_classes_param():
    result = load_from_code(_CODE_NO_NUM_CLASSES_PARAM, num_classes=5)
    assert result.ok
    assert result.class_name == "CustomModel"


def _make_checkpoint(tmp_path: Path, num_classes: int | None) -> Path:
    config = {
        "image_w": 64, "image_h": 64, "sample_mode": "resize",
        "model_source": "preset:attention_unet", "scheduler": None,
    }
    if num_classes is not None:
        config["num_classes"] = num_classes
    ckpt = {
        "epoch": 1,
        "model_state_dict": {},
        "optimizer_state_dict": {},
        "scheduler_state_dict": None,
        "train_loss": 0.1,
        "val_loss": 0.2,
        "metrics": {"mean_iou": 0.5},
        "config": config,
    }
    path = tmp_path / "ckpt.pt"
    torch.save(ckpt, path)
    return path


def test_load_model_from_ckpt_uses_stored_num_classes(tmp_path):
    ckpt_path = _make_checkpoint(tmp_path, num_classes=4)
    model = load_model_from_ckpt(ckpt_path)
    assert model is not None
    assert model.head.out_channels == 4


def test_load_model_from_ckpt_falls_back_to_live_classes_for_legacy_checkpoint(monkeypatch):
    from app.core import inference_engine as ie

    class _FakeClassDef:
        pass

    monkeypatch.setattr(ie, "load_classes", lambda: [_FakeClassDef()] * 3)
    with tempfile.TemporaryDirectory() as d:
        ckpt_path = _make_checkpoint(Path(d), num_classes=None)
        model = load_model_from_ckpt(ckpt_path)
    assert model is not None
    assert model.head.out_channels == 3
