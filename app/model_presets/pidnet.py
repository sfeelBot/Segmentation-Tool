"""
PIDNet (Xu et al., CVPR 2023)
================================
P(Detail)/I(Context)/D(Boundary) 3-브랜치 실시간 세그멘테이션 모델.
공유 stem에서 1/8 해상도까지 다운샘플한 뒤 세 브랜치로 분기한다: P는
해상도를 유지하며 공간 디테일을, I는 계속 다운샘플하며 전역 문맥을(PPM
으로 집약), D는 얕은 conv로 경계 특징을 뽑는다.

설계 결정: 이 앱의 모델 계약은 `forward(x) -> Tensor` 단일 반환만 허용해
원 논문의 boundary auxiliary loss·멀티 출력 구조는 쓸 수 없다. 따라서
D(Boundary) 브랜치는 최종 반환값에 노출하지 않고, P/I 브랜치를 융합할 때
pixel-attention gate(`sigmoid(D 특징 conv)`로 P/I 가중 합산)로만 내부적으로
사용한다.

- Param: ≈ 2M
- 특징: 3-브랜치 구조(Detail/Context/Boundary), boundary 기반 attention
  게이트 융합, 실시간성 지향 경량 설계
- 활용: 컨베이어·고속 라인 등 실시간 처리량이 중요하면서 경계가 뚜렷한
  결함(스크래치, 크랙, 절단면 이상) 검출
"""
import torch
import torch.nn as nn
import torch.nn.functional as F


def _conv_bn_relu(in_c: int, out_c: int, k: int = 3, s: int = 1) -> nn.Sequential:
    return nn.Sequential(
        nn.Conv2d(in_c, out_c, k, stride=s, padding=k // 2, bias=False),
        nn.BatchNorm2d(out_c), nn.ReLU(inplace=True),
    )


class _ResBlock(nn.Module):
    def __init__(self, in_c: int, out_c: int, stride: int = 1) -> None:
        super().__init__()
        self.conv1 = _conv_bn_relu(in_c, out_c, 3, stride)
        self.conv2 = nn.Sequential(
            nn.Conv2d(out_c, out_c, 3, padding=1, bias=False), nn.BatchNorm2d(out_c),
        )
        self.skip = (nn.Sequential(
            nn.Conv2d(in_c, out_c, 1, stride=stride, bias=False), nn.BatchNorm2d(out_c),
        ) if (in_c != out_c or stride != 1) else nn.Identity())
        self.relu = nn.ReLU(inplace=True)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.relu(self.conv2(self.conv1(x)) + self.skip(x))


class _PPM(nn.Module):
    """Pyramid Pooling Module — 여러 스케일 AdaptiveAvgPool2d 후 concat+conv.

    bin=1 처럼 풀링 결과가 1x1 이 되면 배치 크기 1 학습 시 BatchNorm2d가
    "more than 1 value per channel" 오류를 낸다. 배치/공간 크기에 무관하게
    안전한 GroupNorm(num_groups=1)을 사용한다.
    """

    def __init__(self, in_c: int, out_c: int, bins: tuple[int, ...] = (1, 2, 3, 6)) -> None:
        super().__init__()
        self.stages = nn.ModuleList([
            nn.Sequential(
                nn.AdaptiveAvgPool2d(b),
                nn.Conv2d(in_c, out_c, 1, bias=False), nn.GroupNorm(1, out_c), nn.ReLU(inplace=True),
            ) for b in bins
        ])
        self.fuse = nn.Sequential(
            nn.Conv2d(in_c + out_c * len(bins), out_c, 1, bias=False),
            nn.GroupNorm(1, out_c), nn.ReLU(inplace=True),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        h, w = x.shape[-2], x.shape[-1]
        outs = [x]
        for stage in self.stages:
            y = F.interpolate(stage(x), size=(h, w), mode="bilinear", align_corners=False)
            outs.append(y)
        return self.fuse(torch.cat(outs, dim=1))


class PIDNet(nn.Module):
    def __init__(
        self,
        num_classes: int = 2,
        in_channels: int = 3,
        stem_c: int = 32,
        detail_c: int = 64,
        context_c: int = 64,
        boundary_c: int = 16,
    ) -> None:
        super().__init__()
        # 공유 stem: 1/2 → 1/4 → 1/8
        self.stem = nn.Sequential(
            _conv_bn_relu(in_channels, stem_c, 3, 2),
            _conv_bn_relu(stem_c, stem_c, 3, 2),
            _conv_bn_relu(stem_c, stem_c, 3, 2),
        )

        # P(Detail): 1/8 해상도 유지, residual block만 통과
        self.p_branch = nn.Sequential(
            _ResBlock(stem_c, detail_c), _ResBlock(detail_c, detail_c),
        )

        # I(Context): 1/16 → 1/32 로 계속 다운샘플 후 PPM으로 전역 문맥 집약
        self.i_down16 = nn.Sequential(
            _ResBlock(stem_c, context_c, stride=2), _ResBlock(context_c, context_c),
        )
        self.i_down32 = nn.Sequential(
            _ResBlock(context_c, context_c * 2, stride=2), _ResBlock(context_c * 2, context_c * 2),
        )
        self.ppm = _PPM(context_c * 2, context_c)
        self.i_proj = nn.Conv2d(context_c, detail_c, 1, bias=False)

        # D(Boundary): 1/8 해상도에서 얕은 conv로 경계 특징 추출 — 내부 게이트 전용
        self.d_branch = nn.Sequential(
            nn.Conv2d(stem_c, boundary_c, 3, padding=1, bias=False),
            nn.BatchNorm2d(boundary_c), nn.ReLU(inplace=True),
            nn.Conv2d(boundary_c, boundary_c, 3, padding=1, bias=False),
            nn.BatchNorm2d(boundary_c), nn.ReLU(inplace=True),
        )
        self.gate = nn.Conv2d(boundary_c, detail_c, 1)

        self.head = nn.Sequential(
            _conv_bn_relu(detail_c, detail_c),
            nn.Dropout2d(0.1),
            nn.Conv2d(detail_c, num_classes, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        img_h, img_w = x.shape[-2], x.shape[-1]
        s = self.stem(x)                 # 1/8

        p = self.p_branch(s)             # 1/8, detail_c

        i16 = self.i_down16(s)           # 1/16
        i32 = self.i_down32(i16)         # 1/32
        i = self.ppm(i32)                # 1/32, context_c
        i = F.interpolate(i, size=p.shape[-2:], mode="bilinear", align_corners=False)
        i = self.i_proj(i)               # detail_c

        d = self.d_branch(s)             # 1/8, boundary_c — 최종 출력엔 포함하지 않음
        gate = torch.sigmoid(self.gate(d))

        fused = p * gate + i * (1 - gate)
        out = self.head(fused)
        return F.interpolate(out, size=(img_h, img_w), mode="bilinear", align_corners=False)
