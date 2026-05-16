"""
LR-ASPP + MobileNetV3 (Howard et al., 2019)
===========================================
MobileNetV3 전용의 초경량 세그멘테이션 헤드. 추론 속도가 최우선인
생산 라인·엣지 장비용으로 설계되었다.

- Param: ≈ 3.2M
- 특징: 매우 빠른 추론, 작은 모델 크기
- 활용: 컨베이어 고속 카메라, 드론·로봇 탑재 검사, 실시간 FPS 중요 시
- 팁: 정확도는 중간 수준. 고정확도가 필요하면 DeepLabV3-ResNet 계열 사용.
"""
import torch
import torch.nn as nn
from torchvision.models.segmentation import lraspp_mobilenet_v3_large


class LRASPP_MobileNet(nn.Module):
    def __init__(self, num_classes: int = 2, pretrained: bool = False) -> None:
        super().__init__()
        weights = "DEFAULT" if pretrained else None
        self.model = lraspp_mobilenet_v3_large(
            weights=weights, num_classes=num_classes
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.model(x)["out"]
