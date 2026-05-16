import torch.nn as nn
import torch.nn.functional as F
import torch


class DoubleConv(nn.Module):
    def __init__(self, in_ch, out_ch):
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv2d(in_ch, out_ch, 3, padding=1, bias=False),
            nn.BatchNorm2d(out_ch),
            nn.ReLU(inplace=True),
            nn.Conv2d(out_ch, out_ch, 3, padding=1, bias=False),
            nn.BatchNorm2d(out_ch),
            nn.ReLU(inplace=True),
        )

    def forward(self, x):
        return self.net(x)


class SimpleUNet(nn.Module):
    """
    경량 UNet — 입력: (B, 3, H, W)  출력: (B, num_classes, H, W)
    num_classes : 분류할 클래스 수 (background 포함)
    base_ch     : 기본 채널 수 (줄이면 파라미터 감소)
    """
    def __init__(self, num_classes=2, base_ch=32):
        super().__init__()

        # Encoder
        self.enc1 = DoubleConv(3,        base_ch)
        self.enc2 = DoubleConv(base_ch,  base_ch * 2)
        self.enc3 = DoubleConv(base_ch * 2, base_ch * 4)

        self.pool = nn.MaxPool2d(2)

        # Bottleneck
        self.bottleneck = DoubleConv(base_ch * 4, base_ch * 8)

        # Decoder
        self.up3   = nn.ConvTranspose2d(base_ch * 8, base_ch * 4, 2, stride=2)
        self.dec3  = DoubleConv(base_ch * 8, base_ch * 4)

        self.up2   = nn.ConvTranspose2d(base_ch * 4, base_ch * 2, 2, stride=2)
        self.dec2  = DoubleConv(base_ch * 4, base_ch * 2)

        self.up1   = nn.ConvTranspose2d(base_ch * 2, base_ch, 2, stride=2)
        self.dec1  = DoubleConv(base_ch * 2, base_ch)

        self.head  = nn.Conv2d(base_ch, num_classes, 1)

    def forward(self, x):
        # Encoder
        e1 = self.enc1(x)
        e2 = self.enc2(self.pool(e1))
        e3 = self.enc3(self.pool(e2))

        # Bottleneck
        b = self.bottleneck(self.pool(e3))

        # Decoder (skip connection)
        d3 = self.dec3(torch.cat([self.up3(b),  e3], dim=1))
        d2 = self.dec2(torch.cat([self.up2(d3), e2], dim=1))
        d1 = self.dec1(torch.cat([self.up1(d2), e1], dim=1))

        return self.head(d1)