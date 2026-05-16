"""
DeepLabV3 + MobileNetV3 (Howard et al., 2019 / Chen et al., 2017)
================================================================
torchvision 이 제공하는 경량 DeepLabV3 구현. MobileNetV3-Large 백본 위에
ASPP(Atrous Spatial Pyramid Pooling)를 얹어 다양한 크기의 구조를 인식한다.

- Param: ≈ 11M
- 특징: ASPP로 다중스케일, 모바일·엣지 친화적
- 활용: 다양한 크기의 결함이 섞인 라인 검사, 실시간 요구 환경
- 팁: `pretrained=True` 로 바꾸면 COCO 가중치를 다운로드해 초기화 (네트워크 필요)
"""
import torch
import torch.nn as nn
from torchvision.models.segmentation import deeplabv3_mobilenet_v3_large


class DeepLabV3_MobileNet(nn.Module):
    def __init__(self, num_classes: int = 2, pretrained: bool = False) -> None:
        super().__init__()
        weights = "DEFAULT" if pretrained else None
        self.model = deeplabv3_mobilenet_v3_large(
            weights=weights, num_classes=num_classes
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.model(x)["out"]
