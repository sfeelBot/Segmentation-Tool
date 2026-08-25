"""
SegNeXt (Guo et al., NeurIPS 2022)
====================================
Self-attention 없이 대형 커널 depthwise conv 기반의 Multi-Scale
Convolutional Attention(MSCA)만으로 트랜스포머급 문맥 포착 능력을 내는
합성곱 세그멘테이션 모델. MSCA는 여러 크기의 스트립(strip) 컨볼루션
브랜치(1x7+7x1, 1x11+11x1, 1x21+21x1)를 병렬로 합산해 attention weight를
만들고 이를 입력에 곱하는 게이팅 방식으로 동작한다.

주의: 원 논문의 "Hamburger"(행렬분해 기반) 디코더는 구현하지 않고,
마지막 3단계 특징을 공통 채널로 투영 → upsample → concat → conv로
fuse하는 경량 concat-fuse 디코더로 단순화했다.

- Param: ≈ 5M
- 특징: 대형 커널 conv attention(MSCA), self-attention 대비 가볍고 빠름
- 활용: 실시간성이 필요하면서도 넓은 수용영역이 필요한 검사(도장·코팅면
  얼룩, 직물 패턴 결함, 파이프라인 표면 이상)
"""
import torch
import torch.nn as nn
import torch.nn.functional as F


class _MSCA(nn.Module):
    """Multi-Scale Convolutional Attention — 대형 커널 스트립 conv로 attention weight 생성."""

    def __init__(self, dim: int) -> None:
        super().__init__()
        self.conv0 = nn.Conv2d(dim, dim, 5, padding=2, groups=dim)
        self.conv1_1 = nn.Conv2d(dim, dim, (1, 7), padding=(0, 3), groups=dim)
        self.conv1_2 = nn.Conv2d(dim, dim, (7, 1), padding=(3, 0), groups=dim)
        self.conv2_1 = nn.Conv2d(dim, dim, (1, 11), padding=(0, 5), groups=dim)
        self.conv2_2 = nn.Conv2d(dim, dim, (11, 1), padding=(5, 0), groups=dim)
        self.conv3_1 = nn.Conv2d(dim, dim, (1, 21), padding=(0, 10), groups=dim)
        self.conv3_2 = nn.Conv2d(dim, dim, (21, 1), padding=(10, 0), groups=dim)
        self.conv_mix = nn.Conv2d(dim, dim, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        u = x
        attn = self.conv0(x)
        b1 = self.conv1_2(self.conv1_1(attn))
        b2 = self.conv2_2(self.conv2_1(attn))
        b3 = self.conv3_2(self.conv3_1(attn))
        attn = self.conv_mix(attn + b1 + b2 + b3)
        return attn * u


class _ConvFFN(nn.Module):
    def __init__(self, dim: int, hidden: int) -> None:
        super().__init__()
        self.fc1 = nn.Conv2d(dim, hidden, 1)
        self.dwconv = nn.Conv2d(hidden, hidden, 3, padding=1, groups=hidden)
        self.act = nn.GELU()
        self.fc2 = nn.Conv2d(hidden, dim, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.fc1(x)
        x = self.dwconv(x)
        x = self.act(x)
        return self.fc2(x)


class _MSCABlock(nn.Module):
    def __init__(self, dim: int, mlp_ratio: int = 4) -> None:
        super().__init__()
        self.norm1 = nn.BatchNorm2d(dim)
        self.attn = _MSCA(dim)
        self.norm2 = nn.BatchNorm2d(dim)
        self.ffn = _ConvFFN(dim, dim * mlp_ratio)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x + self.attn(self.norm1(x))
        x = x + self.ffn(self.norm2(x))
        return x


class SegNeXt(nn.Module):
    def __init__(
        self,
        num_classes: int = 2,
        in_channels: int = 3,
        dims: tuple[int, ...] = (32, 64, 160, 256),
        depths: tuple[int, ...] = (2, 2, 4, 2),
        decoder_dim: int = 128,
    ) -> None:
        super().__init__()
        self.downsamples = nn.ModuleList()
        self.stages = nn.ModuleList()

        in_c = in_channels
        for i, (dim, depth) in enumerate(zip(dims, depths)):
            if i == 0:
                # 1/4 해상도까지 두 번의 stride-2 conv로 다운샘플
                down = nn.Sequential(
                    nn.Conv2d(in_c, dim, 3, stride=2, padding=1), nn.BatchNorm2d(dim), nn.GELU(),
                    nn.Conv2d(dim, dim, 3, stride=2, padding=1), nn.BatchNorm2d(dim),
                )
            else:
                down = nn.Sequential(
                    nn.Conv2d(in_c, dim, 3, stride=2, padding=1), nn.BatchNorm2d(dim),
                )
            self.downsamples.append(down)
            self.stages.append(nn.Sequential(*[_MSCABlock(dim) for _ in range(depth)]))
            in_c = dim

        # 경량 concat-fuse 디코더: 마지막 3단계(1/8, 1/16, 1/32) 특징만 사용
        self.proj = nn.ModuleList([nn.Conv2d(d, decoder_dim, 1) for d in dims[1:]])
        self.fuse = nn.Sequential(
            nn.Conv2d(decoder_dim * 3, decoder_dim, 3, padding=1, bias=False),
            nn.BatchNorm2d(decoder_dim), nn.ReLU(inplace=True),
        )
        self.dropout = nn.Dropout2d(0.1)
        self.classifier = nn.Conv2d(decoder_dim, num_classes, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        img_h, img_w = x.shape[-2], x.shape[-1]
        feats = []
        cur = x
        for down, stage in zip(self.downsamples, self.stages):
            cur = stage(down(cur))
            feats.append(cur)

        sel = feats[1:]  # 1/8, 1/16, 1/32 단계만 사용
        target_size = sel[0].shape[-2:]
        ups = []
        for i, feat in enumerate(sel):
            t = self.proj[i](feat)
            if t.shape[-2:] != target_size:
                t = F.interpolate(t, size=target_size, mode="bilinear", align_corners=False)
            ups.append(t)

        fused = self.fuse(torch.cat(ups, dim=1))
        out = self.classifier(self.dropout(fused))
        return F.interpolate(out, size=(img_h, img_w), mode="bilinear", align_corners=False)
