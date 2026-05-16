"""
Attention U-Net (Oktay et al., 2018)
=====================================
스킵 연결에 Attention Gate 를 삽입해 인코더의 저수준 특징 중
타겟 영역만 강조하고 배경 노이즈를 억제한다.

- Param: ≈ 3.0M
- 특징: Attention Gate, 복잡한 배경에 강건
- 활용: 금속 표면, 직물, 용접부 등 배경이 복잡한 산업 환경
"""
import torch
import torch.nn as nn


def _conv_block(in_c: int, out_c: int) -> nn.Sequential:
    return nn.Sequential(
        nn.Conv2d(in_c,  out_c, 3, padding=1, bias=False),
        nn.BatchNorm2d(out_c), nn.ReLU(inplace=True),
        nn.Conv2d(out_c, out_c, 3, padding=1, bias=False),
        nn.BatchNorm2d(out_c), nn.ReLU(inplace=True),
    )


class _AttentionGate(nn.Module):
    def __init__(self, f_g: int, f_l: int, f_int: int) -> None:
        super().__init__()
        self.w_g = nn.Sequential(
            nn.Conv2d(f_g, f_int, 1, bias=False), nn.BatchNorm2d(f_int)
        )
        self.w_x = nn.Sequential(
            nn.Conv2d(f_l, f_int, 1, bias=False), nn.BatchNorm2d(f_int)
        )
        self.psi = nn.Sequential(
            nn.Conv2d(f_int, 1, 1, bias=False), nn.BatchNorm2d(1), nn.Sigmoid()
        )
        self.relu = nn.ReLU(inplace=True)

    def forward(self, g: torch.Tensor, x: torch.Tensor) -> torch.Tensor:
        a = self.psi(self.relu(self.w_g(g) + self.w_x(x)))
        return x * a


class AttentionUNet(nn.Module):
    def __init__(self, num_classes: int = 2, in_channels: int = 3, base: int = 32) -> None:
        super().__init__()
        self.d1 = _conv_block(in_channels, base)
        self.d2 = _conv_block(base,     base * 2)
        self.d3 = _conv_block(base * 2, base * 4)
        self.d4 = _conv_block(base * 4, base * 8)
        self.pool = nn.MaxPool2d(2)

        self.bottleneck = _conv_block(base * 8, base * 16)

        self.u4  = nn.ConvTranspose2d(base * 16, base * 8, 2, stride=2)
        self.a4  = _AttentionGate(base * 8, base * 8, base * 4)
        self.c4  = _conv_block(base * 16, base * 8)
        self.u3  = nn.ConvTranspose2d(base * 8, base * 4, 2, stride=2)
        self.a3  = _AttentionGate(base * 4, base * 4, base * 2)
        self.c3  = _conv_block(base * 8,  base * 4)
        self.u2  = nn.ConvTranspose2d(base * 4, base * 2, 2, stride=2)
        self.a2  = _AttentionGate(base * 2, base * 2, base)
        self.c2  = _conv_block(base * 4,  base * 2)
        self.u1  = nn.ConvTranspose2d(base * 2, base,     2, stride=2)
        self.a1  = _AttentionGate(base, base, base // 2)
        self.c1  = _conv_block(base * 2,  base)

        self.head = nn.Conv2d(base, num_classes, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        d1 = self.d1(x)
        d2 = self.d2(self.pool(d1))
        d3 = self.d3(self.pool(d2))
        d4 = self.d4(self.pool(d3))
        b  = self.bottleneck(self.pool(d4))

        u4 = self.u4(b);  d4_a = self.a4(u4, d4); u4 = self.c4(torch.cat([u4, d4_a], 1))
        u3 = self.u3(u4); d3_a = self.a3(u3, d3); u3 = self.c3(torch.cat([u3, d3_a], 1))
        u2 = self.u2(u3); d2_a = self.a2(u2, d2); u2 = self.c2(torch.cat([u2, d2_a], 1))
        u1 = self.u1(u2); d1_a = self.a1(u1, d1); u1 = self.c1(torch.cat([u1, d1_a], 1))

        return self.head(u1)
