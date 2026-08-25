"""
SegFormer (Xie et al., NVIDIA, NeurIPS 2021)
=============================================
계층적 트랜스포머 인코더(MixVisionTransformer, MiT) + 경량 all-MLP 디코더로
구성된 시맨틱 세그멘테이션 모델. Positional encoding 없이 Mix-FFN(중간에
depthwise 3x3 conv를 끼운 MLP)만으로 위치 정보를 암묵적으로 인코딩하는 것이
특징이다. 이 프리셋은 MiT-B0 스케일을 앱 규모에 맞춰 경량화한 구현이다.

- Param: ≈ 4M
- 특징: 4단계 계층적 트랜스포머 인코더(Efficient Self-Attention으로 큰
  해상도에서도 연산량 절감), all-MLP 디코더로 멀티스케일 특징을 단순 결합
- 활용: 조명·질감 변화가 큰 현장에서 전역 문맥(global context)이 중요한
  결함 검출(대형 이물, 넓은 얼룩·오염, 표면 패턴 이상)
"""
import torch
import torch.nn as nn
import torch.nn.functional as F


class _OverlapPatchEmbed(nn.Module):
    def __init__(self, in_c: int, out_c: int, patch_size: int, stride: int) -> None:
        super().__init__()
        self.proj = nn.Conv2d(in_c, out_c, kernel_size=patch_size, stride=stride,
                               padding=patch_size // 2)
        self.norm = nn.LayerNorm(out_c)

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, int, int]:
        x = self.proj(x)
        h, w = x.shape[-2], x.shape[-1]
        x = x.flatten(2).transpose(1, 2)  # (B, N, C)
        return self.norm(x), h, w


class _EfficientSelfAttention(nn.Module):
    """Spatial reduction으로 K/V 시퀀스 길이를 줄여 연산량을 절감하는 attention."""

    def __init__(self, dim: int, heads: int, sr_ratio: int) -> None:
        super().__init__()
        self.heads = heads
        self.head_dim = dim // heads
        self.scale = self.head_dim ** -0.5
        self.q = nn.Linear(dim, dim)
        self.kv = nn.Linear(dim, dim * 2)
        self.proj = nn.Linear(dim, dim)
        self.sr_ratio = sr_ratio
        if sr_ratio > 1:
            self.sr = nn.Conv2d(dim, dim, kernel_size=sr_ratio, stride=sr_ratio)
            self.sr_norm = nn.LayerNorm(dim)

    def forward(self, x: torch.Tensor, h: int, w: int) -> torch.Tensor:
        b, n, c = x.shape
        q = self.q(x).reshape(b, n, self.heads, self.head_dim).permute(0, 2, 1, 3)

        if self.sr_ratio > 1:
            x_ = x.transpose(1, 2).reshape(b, c, h, w)
            x_ = self.sr(x_).reshape(b, c, -1).transpose(1, 2)
            x_ = self.sr_norm(x_)
        else:
            x_ = x

        kv = self.kv(x_).reshape(b, -1, 2, self.heads, self.head_dim).permute(2, 0, 3, 1, 4)
        k, v = kv[0], kv[1]

        attn = (q @ k.transpose(-2, -1)) * self.scale
        attn = attn.softmax(dim=-1)
        out = (attn @ v).transpose(1, 2).reshape(b, n, c)
        return self.proj(out)


class _MixFFN(nn.Module):
    """일반 MLP 대신 depthwise 3x3 conv를 끼워 위치 정보를 암묵 인코딩한다."""

    def __init__(self, dim: int, hidden: int) -> None:
        super().__init__()
        self.fc1 = nn.Linear(dim, hidden)
        self.dwconv = nn.Conv2d(hidden, hidden, 3, padding=1, groups=hidden)
        self.act = nn.GELU()
        self.fc2 = nn.Linear(hidden, dim)

    def forward(self, x: torch.Tensor, h: int, w: int) -> torch.Tensor:
        x = self.fc1(x)
        b, n, c = x.shape
        x = x.transpose(1, 2).reshape(b, c, h, w)
        x = self.dwconv(x)
        x = x.flatten(2).transpose(1, 2)
        x = self.act(x)
        return self.fc2(x)


class _TransformerBlock(nn.Module):
    def __init__(self, dim: int, heads: int, sr_ratio: int, mlp_ratio: int = 4) -> None:
        super().__init__()
        self.norm1 = nn.LayerNorm(dim)
        self.attn = _EfficientSelfAttention(dim, heads, sr_ratio)
        self.norm2 = nn.LayerNorm(dim)
        self.ffn = _MixFFN(dim, dim * mlp_ratio)

    def forward(self, x: torch.Tensor, h: int, w: int) -> torch.Tensor:
        x = x + self.attn(self.norm1(x), h, w)
        x = x + self.ffn(self.norm2(x), h, w)
        return x


class SegFormer(nn.Module):
    def __init__(
        self,
        num_classes: int = 2,
        in_channels: int = 3,
        embed_dims: tuple[int, ...] = (32, 64, 160, 256),
        depths: tuple[int, ...] = (2, 2, 2, 2),
        heads: tuple[int, ...] = (1, 2, 5, 8),
        sr_ratios: tuple[int, ...] = (8, 4, 2, 1),
        decoder_dim: int = 256,
    ) -> None:
        super().__init__()
        patch_sizes = (7, 3, 3, 3)
        strides = (4, 2, 2, 2)

        self.patch_embeds = nn.ModuleList()
        self.stages = nn.ModuleList()
        self.norms = nn.ModuleList()

        in_c = in_channels
        for i in range(4):
            self.patch_embeds.append(
                _OverlapPatchEmbed(in_c, embed_dims[i], patch_sizes[i], strides[i])
            )
            self.stages.append(nn.ModuleList([
                _TransformerBlock(embed_dims[i], heads[i], sr_ratios[i])
                for _ in range(depths[i])
            ]))
            self.norms.append(nn.LayerNorm(embed_dims[i]))
            in_c = embed_dims[i]

        # all-MLP 디코더: 각 스테이지 출력을 공통 차원으로 투영 후 1/4 해상도로 concat
        self.linear_c = nn.ModuleList([nn.Linear(d, decoder_dim) for d in embed_dims])
        self.fuse = nn.Sequential(
            nn.Conv2d(decoder_dim * 4, decoder_dim, 1, bias=False),
            nn.BatchNorm2d(decoder_dim), nn.ReLU(inplace=True),
        )
        self.dropout = nn.Dropout2d(0.1)
        self.classifier = nn.Conv2d(decoder_dim, num_classes, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        img_h, img_w = x.shape[-2], x.shape[-1]
        feats = []
        cur = x
        for i in range(4):
            tokens, h, w = self.patch_embeds[i](cur)
            for block in self.stages[i]:
                tokens = block(tokens, h, w)
            tokens = self.norms[i](tokens)
            cur = tokens.transpose(1, 2).reshape(tokens.shape[0], -1, h, w)
            feats.append(cur)

        target_size = feats[0].shape[-2:]
        ups = []
        for i, feat in enumerate(feats):
            b, c, h, w = feat.shape
            t = feat.flatten(2).transpose(1, 2)
            t = self.linear_c[i](t)
            t = t.transpose(1, 2).reshape(b, -1, h, w)
            if t.shape[-2:] != target_size:
                t = F.interpolate(t, size=target_size, mode="bilinear", align_corners=False)
            ups.append(t)

        fused = self.fuse(torch.cat(ups, dim=1))
        out = self.classifier(self.dropout(fused))
        return F.interpolate(out, size=(img_h, img_w), mode="bilinear", align_corners=False)
