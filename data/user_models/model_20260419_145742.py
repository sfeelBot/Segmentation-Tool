"""
DeepLabV3 + ResNet50 (Chen et al., 2017)
========================================
산업 표준급 정확도를 제공하는 고전 DeepLab 조합. ResNet50 백본 +
ASPP 모듈로 넓은 수용영역과 다중스케일 특징 추출이 가능하다.

- Param: ≈ 40M
- 특징: 큰 수용영역, 안정적 수렴, 산업 표준 베이스라인
- 활용: 고정 설비의 고정확 검사(반도체·디스플레이·자동차 외판)
- 팁: GPU 메모리·데이터가 충분할 때 사용. 소량 데이터에서는 U-Net 계열 권장.
"""
import torch
import torch.nn as nn
from torchvision.models.segmentation import deeplabv3_resnet50


class DeepLabV3_ResNet50(nn.Module):
    def __init__(self, num_classes: int = 2, pretrained: bool = False) -> None:
        super().__init__()
        weights = "DEFAULT" if pretrained else None
        self.model = deeplabv3_resnet50(
            weights=weights, num_classes=num_classes
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.model(x)["out"]