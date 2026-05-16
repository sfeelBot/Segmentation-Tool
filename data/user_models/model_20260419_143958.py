"""
U-Net (Ronneberger et al., 2015)
================================
가장 고전적인 인코더-디코더 구조로, 적은 데이터로도 뛰어난 성능을 보여
산업 결함 검출의 기본 베이스라인으로 널리 쓰인다.

- Param: ≈ 2.0M
- 특징: 스킵 연결로 공간 정보 보존, 작은 데이터셋에 강함
- 활용: 표면 결함, 균열, 의료 영상, 제조 QC 초기 베이스라인
"""
import torch
import torch.nn as nn
import torch.nn.functional as F


def _conv_block(in_c: int, out_c: int) -> nn.Sequential:
    return nn.Sequential(
        nn.Conv2d(in_c,  out_c, 3, padding=1, bias=False),
        nn.BatchNorm2d(out_c), nn.ReLU(inplace=True),
        nn.Conv2d(out_c, out_c, 3, padding=1, bias=False),
        nn.BatchNorm2d(out_c), nn.ReLU(inplace=True),
    )


class SimpleUNet(nn.Module):
    def __init__(self, num_classes: int = 2, in_channels: int = 3, base: int = 32) -> None:
        super().__init__()
        self.d1 = _conv_block(in_channels, base)
        self.d2 = _conv_block(base,     base * 2)
        self.d3 = _conv_block(base * 2, base * 4)
        self.d4 = _conv_block(base * 4, base * 8)
        self.pool = nn.MaxPool2d(2)

        self.bottleneck = _conv_block(base * 8, base * 16)

        self.u4 = nn.ConvTranspose2d(base * 16, base * 8, 2, stride=2)
        self.c4 = _conv_block(base * 16, base * 8)
        self.u3 = nn.ConvTranspose2d(base * 8, base * 4, 2, stride=2)
        self.c3 = _conv_block(base * 8,  base * 4)
        self.u2 = nn.ConvTranspose2d(base * 4, base * 2, 2, stride=2)
        self.c2 = _conv_block(base * 4,  base * 2)
        self.u1 = nn.ConvTranspose2d(base * 2, base,     2, stride=2)
        self.c1 = _conv_block(base * 2,  base)

        self.head = nn.Conv2d(base, num_classes, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        d1 = self.d1(x)
        d2 = self.d2(self.pool(d1))
        d3 = self.d3(self.pool(d2))
        d4 = self.d4(self.pool(d3))
        b  = self.bottleneck(self.pool(d4))

        u4 = self.u4(b);  u4 = self.c4(torch.cat([u4, d4], dim=1))
        u3 = self.u3(u4); u3 = self.c3(torch.cat([u3, d3], dim=1))
        u2 = self.u2(u3); u2 = self.c2(torch.cat([u2, d2], dim=1))
        u1 = self.u1(u2); u1 = self.c1(torch.cat([u1, d1], dim=1))
        return self.head(u1)