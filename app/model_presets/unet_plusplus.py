"""
U-Net++ (Zhou et al., 2018)
===========================
U-Net 의 스킵 연결을 촘촘한(dense) 구조로 확장해 인코더·디코더 간
시맨틱 갭을 줄인 개선 모델.

- Param: ≈ 9.0M
- 특징: Nested dense skip pathway, deep supervision 가능
- 활용: 미세 결함·작은 스크래치·PCB 인쇄 결함 등 경계 정밀도가 중요한 작업
"""
import torch
import torch.nn as nn


def _cbr(in_c: int, out_c: int) -> nn.Sequential:
    return nn.Sequential(
        nn.Conv2d(in_c,  out_c, 3, padding=1, bias=False),
        nn.BatchNorm2d(out_c), nn.ReLU(inplace=True),
        nn.Conv2d(out_c, out_c, 3, padding=1, bias=False),
        nn.BatchNorm2d(out_c), nn.ReLU(inplace=True),
    )


class UNetPlusPlus(nn.Module):
    def __init__(self, num_classes: int = 2, in_channels: int = 3, base: int = 32) -> None:
        super().__init__()
        c = [base, base * 2, base * 4, base * 8, base * 16]
        self.pool = nn.MaxPool2d(2)
        self.up = nn.Upsample(scale_factor=2, mode="bilinear", align_corners=True)

        # Encoder column (X_{i,0})
        self.x00 = _cbr(in_channels, c[0])
        self.x10 = _cbr(c[0], c[1])
        self.x20 = _cbr(c[1], c[2])
        self.x30 = _cbr(c[2], c[3])
        self.x40 = _cbr(c[3], c[4])

        # Nested decoder
        self.x01 = _cbr(c[0] + c[1], c[0])
        self.x11 = _cbr(c[1] + c[2], c[1])
        self.x21 = _cbr(c[2] + c[3], c[2])
        self.x31 = _cbr(c[3] + c[4], c[3])

        self.x02 = _cbr(c[0] * 2 + c[1], c[0])
        self.x12 = _cbr(c[1] * 2 + c[2], c[1])
        self.x22 = _cbr(c[2] * 2 + c[3], c[2])

        self.x03 = _cbr(c[0] * 3 + c[1], c[0])
        self.x13 = _cbr(c[1] * 3 + c[2], c[1])

        self.x04 = _cbr(c[0] * 4 + c[1], c[0])

        self.head = nn.Conv2d(c[0], num_classes, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x00 = self.x00(x)
        x10 = self.x10(self.pool(x00))
        x20 = self.x20(self.pool(x10))
        x30 = self.x30(self.pool(x20))
        x40 = self.x40(self.pool(x30))

        x01 = self.x01(torch.cat([x00, self.up(x10)], 1))
        x11 = self.x11(torch.cat([x10, self.up(x20)], 1))
        x21 = self.x21(torch.cat([x20, self.up(x30)], 1))
        x31 = self.x31(torch.cat([x30, self.up(x40)], 1))

        x02 = self.x02(torch.cat([x00, x01, self.up(x11)], 1))
        x12 = self.x12(torch.cat([x10, x11, self.up(x21)], 1))
        x22 = self.x22(torch.cat([x20, x21, self.up(x31)], 1))

        x03 = self.x03(torch.cat([x00, x01, x02, self.up(x12)], 1))
        x13 = self.x13(torch.cat([x10, x11, x12, self.up(x22)], 1))

        x04 = self.x04(torch.cat([x00, x01, x02, x03, self.up(x13)], 1))
        return self.head(x04)
