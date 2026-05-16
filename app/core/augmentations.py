"""Albumentations 파이프라인 빌더."""
from __future__ import annotations

import albumentations as A


def build_pipeline(steps: list[dict]) -> A.Compose:
    """UI에서 넘겨받은 step dict 목록으로 A.Compose를 생성한다.

    step format: {"type": "HorizontalFlip", "params": {"p": 0.5}}
    """
    transforms: list[A.BasicTransform] = []
    for step in steps:
        cls_name = step.get("type", "")
        params   = step.get("params", {})
        cls = getattr(A, cls_name, None)
        if cls is None:
            continue
        try:
            transforms.append(cls(**params))
        except Exception:
            continue

    return A.Compose(
        transforms,
        additional_targets={"mask": "mask"},
    )


# 기본 제공 증강 옵션 (UI ConfigForm 드롭다운용)
AVAILABLE_AUGMENTATIONS: list[dict] = [
    {"type": "HorizontalFlip",            "params": {"p": 0.5}},
    {"type": "VerticalFlip",              "params": {"p": 0.5}},
    {"type": "RandomRotate90",            "params": {"p": 0.5}},
    {"type": "RandomBrightnessContrast",  "params": {"brightness_limit": 0.2, "contrast_limit": 0.2, "p": 0.5}},
    {"type": "GaussNoise",                "params": {"p": 0.3}},
    {"type": "Blur",                      "params": {"blur_limit": 3, "p": 0.3}},
    {"type": "ElasticTransform",          "params": {"p": 0.3}},
    {"type": "GridDistortion",            "params": {"p": 0.3}},
]
