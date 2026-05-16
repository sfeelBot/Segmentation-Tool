"""
FPN-SegNet (Feature Pyramid Network 기반 세그멘테이션)
=====================================================
Lin et al., 2017 의 FPN 구조를 세그멘테이션에 적용한 구현.
다중 해상도 피처맵을 top-down + lateral connection 으로 결합해
서로 다른 크기의 대상을 동시에 잘 분할한다.

- Param: ≈ 7M
- 특징: 다중스케일 피라미드 융합, 스케일 변동에 강건
- 활용: 결함 크기 편차가 큰 현장(작은 핀홀 ~ 큰 변형까지 혼재)
"""
import torch
import torch.nn as nn
import torch.nn.functional as F


def _conv_bn_relu(in_c: int, out_c: int, k: int = 3, s: int = 1) -> nn.Sequential:
    return nn.Sequential(
        nn.Conv2d(in_c, out_c, k, stride=s, padding=k // 2, bias=False),
        nn.BatchNorm2d(out_c), nn.ReLU(inplace=True),
    )


class _Block(nn.Module):
    def __init__(self, in_c: int, out_c: int, stride: int = 1) -> None:
        super().__init__()
        self.conv1 = _conv_bn_relu(in_c, out_c, 3, stride)
        self.conv2 = nn.Sequential(
            nn.Conv2d(out_c, out_c, 3, padding=1, bias=False),
            nn.BatchNorm2d(out_c),
        )
        self.skip = (nn.Sequential(
            nn.Conv2d(in_c, out_c, 1, stride=stride, bias=False),
            nn.BatchNorm2d(out_c),
        ) if (in_c != out_c or stride != 1) else nn.Identity())
        self.relu = nn.ReLU(inplace=True)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.relu(self.conv2(self.conv1(x)) + self.skip(x))


class FPNSegNet(nn.Module):
    def __init__(self, num_classes: int = 2, in_channels: int = 3) -> None:
        super().__init__()
        c = [64, 128, 256, 512]

        # Bottom-up (encoder)
        self.stem = _conv_bn_relu(in_channels, c[0], 7, 2)
        self.pool = nn.MaxPool2d(3, stride=2, padding=1)

        self.s2 = nn.Sequential(_Block(c[0], c[0]),     _Block(c[0], c[0]))
        self.s3 = nn.Sequential(_Block(c[0], c[1], 2),  _Block(c[1], c[1]))
        self.s4 = nn.Sequential(_Block(c[1], c[2], 2),  _Block(c[2], c[2]))
        self.s5 = nn.Sequential(_Block(c[2], c[3], 2),  _Block(c[3], c[3]))

        # Lateral 1x1 convs → 공통 채널 수로
        fpn_c = 128
        self.l5 = nn.Conv2d(c[3], fpn_c, 1)
        self.l4 = nn.Conv2d(c[2], fpn_c, 1)
        self.l3 = nn.Conv2d(c[1], fpn_c, 1)
        self.l2 = nn.Conv2d(c[0], fpn_c, 1)

        # Smooth 3x3
        self.sm5 = _conv_bn_relu(fpn_c, fpn_c)
        self.sm4 = _conv_bn_relu(fpn_c, fpn_c)
        self.sm3 = _conv_bn_relu(fpn_c, fpn_c)
        self.sm2 = _conv_bn_relu(fpn_c, fpn_c)

        # 세그멘테이션 헤드 — 네 피라미드 피처 합산 후 원본 해상도로 복원
        self.head = nn.Sequential(
            _conv_bn_relu(fpn_c * 4, fpn_c),
            nn.Dropout2d(0.1),
            nn.Conv2d(fpn_c, num_classes, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        h, w = x.shape[-2:]
        s2 = self.s2(self.pool(self.stem(x)))
        s3 = self.s3(s2)
        s4 = self.s4(s3)
        s5 = self.s5(s4)

        p5 = self.sm5(self.l5(s5))
        p4 = self.sm4(self.l4(s4) + F.interpolate(p5, size=s4.shape[-2:], mode="nearest"))
        p3 = self.sm3(self.l3(s3) + F.interpolate(p4, size=s3.shape[-2:], mode="nearest"))
        p2 = self.sm2(self.l2(s2) + F.interpolate(p3, size=s2.shape[-2:], mode="nearest"))

        target = s2.shape[-2:]
        p5u = F.interpolate(p5, size=target, mode="bilinear", align_corners=False)
        p4u = F.interpolate(p4, size=target, mode="bilinear", align_corners=False)
        p3u = F.interpolate(p3, size=target, mode="bilinear", align_corners=False)
        merged = torch.cat([p2, p3u, p4u, p5u], dim=1)

        out = self.head(merged)
        return F.interpolate(out, size=(h, w), mode="bilinear", align_corners=False)
