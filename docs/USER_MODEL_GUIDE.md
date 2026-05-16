# 🧠 사용자 모델 작성 가이드

이 앱은 사용자가 직접 PyTorch 모델 아키텍처 코드를 작성하거나 붙여넣어 학습·추론에 사용할 수 있습니다.
코드는 **모델 탭**의 에디터에서 입력하며, 보안 샌드박스에서 검증·실행됩니다.

---

## ✅ 필수 조건

### 1. `torch.nn.Module` 서브클래스 정의

```python
import torch.nn as nn

class MyModel(nn.Module):      # ← nn.Module 을 반드시 상속
    def __init__(self):
        super().__init__()
        ...

    def forward(self, x):      # ← forward() 메서드 반드시 구현
        ...
        return x
```

- 파일 안에 `nn.Module` 서브클래스가 **하나 이상** 있어야 합니다.
- 여러 클래스가 있으면 **마지막으로 정의된** 클래스가 주 모델로 선택됩니다.
- 각 클래스에 `forward()` 메서드가 있어야 합니다.

### 2. 생성자에 기본값 필요

```python
# ❌ 안 됨 — 인자에 기본값 없음
class MyModel(nn.Module):
    def __init__(self, num_classes):   # 기본값 없으면 인스턴스화 실패
        ...

# ✅ 됨
class MyModel(nn.Module):
    def __init__(self, num_classes=2):  # 기본값 지정
        ...
```

앱은 `MyModel()` (인자 없이) 호출해 인스턴스를 만들기 때문에,
생성자에 필수 인자가 있다면 반드시 기본값을 설정해야 합니다.

### 3. 입출력 형태

```
입력:  (B, 3, H, W)  — float32, ImageNet 정규화된 RGB 텐서
출력:  (B, num_classes, H, W)  — 각 픽셀의 클래스 로짓 (softmax 전)
```

- `B` = batch size
- `H`, `W` = 이미지 높이/너비 (학습 설정에서 지정한 patch/resize 크기)
- 채널 수 = 클래스 수 (배경 포함)

---

## ✅ 허용되는 import

```python
# ✅ 허용
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.nn.init
import torch.utils.checkpoint
import torchvision
import torchvision.models
import torchvision.ops
import numpy as np
import math
from typing import Optional, List, Tuple
from collections import OrderedDict
from functools import partial
from itertools import chain
import copy
```

### 사전 제공 이름 (import 없이 사용 가능)

에디터 코드 실행 시 아래 이름이 글로벌로 제공됩니다:

| 이름 | 설명 |
|---|---|
| `torch` | PyTorch |
| `nn` | `torch.nn` |
| `F` | `torch.nn.functional` |

```python
# 이렇게 쓸 수 있습니다 (import 없이)
class MyModel(nn.Module):
    def forward(self, x):
        return F.relu(self.conv(x))
```

---

## ❌ 금지 항목

### 차단되는 모듈

```python
# ❌ 보안상 차단
import os
import sys
import subprocess
import socket
import requests, urllib
import shutil, pathlib
import threading, multiprocessing
import pickle, shelve
import ctypes, importlib
import io, glob, signal
```

### 차단되는 내장 함수 호출

```python
# ❌ 호출 불가
eval(...)
exec(...)
compile(...)
open(...)
__import__(...)
globals()
locals()
vars()
dir()
breakpoint()
input()
memoryview(...)
```

### 코드 크기 제한

- 최대 **256 KB** (약 256,000자)

---

## 📋 검증 과정

모델 탭에서 **🔎 검증** 버튼을 누르면 다음 순서로 검사합니다:

```
1. 문법 검사 (ast.parse)
2. import 화이트리스트 검사
3. 금지 함수 호출 검사
4. nn.Module 서브클래스 존재 확인
5. forward() 메서드 존재 확인
```

모두 통과하면 **✅ 로드** 버튼이 활성화됩니다.

---

## 🔒 실행 샌드박스

검증 통과 후 코드는 제한된 환경에서 실행됩니다:

```python
# 허용된 내장 함수만 포함된 네임스페이스
safe_builtins = {
    "abs", "all", "any", "bool", "dict", "enumerate", "filter",
    "float", "int", "len", "list", "map", "max", "min", "print",
    "range", "round", "set", "sorted", "str", "sum", "tuple",
    "zip", "isinstance", "hasattr", "getattr", "setattr",
    "super", "type", "object", "property", "staticmethod", "classmethod",
    "NotImplementedError", "ValueError", "TypeError", "RuntimeError",
    "__import__",  # ← 화이트리스트 모듈만 허용하는 래퍼
}
```

이 환경 밖의 함수·모듈에는 접근할 수 없습니다.

---

## 💡 작성 예시

### 최소 예시

```python
import torch.nn as nn

class SimpleModel(nn.Module):
    def __init__(self, num_classes=2):
        super().__init__()
        self.conv = nn.Conv2d(3, num_classes, kernel_size=1)

    def forward(self, x):
        return self.conv(x)
```

### torchvision pretrained 백본 사용

```python
import torch.nn as nn
from torchvision.models.segmentation import deeplabv3_mobilenet_v3_large

class DeepLabV3_MobileNet(nn.Module):
    def __init__(self, num_classes=2, pretrained=False):
        super().__init__()
        weights = "DEFAULT" if pretrained else None
        self.model = deeplabv3_mobilenet_v3_large(
            weights=weights, num_classes=num_classes
        )

    def forward(self, x):
        return self.model(x)["out"]
```

### U-Net 스타일 (헬퍼 함수 포함)

```python
import torch
import torch.nn as nn

def _block(in_c, out_c):
    return nn.Sequential(
        nn.Conv2d(in_c, out_c, 3, padding=1, bias=False),
        nn.BatchNorm2d(out_c),
        nn.ReLU(inplace=True),
        nn.Conv2d(out_c, out_c, 3, padding=1, bias=False),
        nn.BatchNorm2d(out_c),
        nn.ReLU(inplace=True),
    )

class UNet(nn.Module):
    def __init__(self, num_classes=2):
        super().__init__()
        self.enc1 = _block(3, 32)
        self.enc2 = _block(32, 64)
        self.pool = nn.MaxPool2d(2)
        self.bot  = _block(64, 128)
        self.up2  = nn.ConvTranspose2d(128, 64, 2, stride=2)
        self.dec2 = _block(128, 64)
        self.up1  = nn.ConvTranspose2d(64, 32, 2, stride=2)
        self.dec1 = _block(64, 32)
        self.head = nn.Conv2d(32, num_classes, 1)

    def forward(self, x):
        e1 = self.enc1(x)
        e2 = self.enc2(self.pool(e1))
        b  = self.bot(self.pool(e2))
        d2 = self.dec2(torch.cat([self.up2(b), e2], 1))
        d1 = self.dec1(torch.cat([self.up1(d2), e1], 1))
        return self.head(d1)
```

---

## ❓ 자주 발생하는 오류

| 오류 메시지 | 원인 | 해결 |
|---|---|---|
| `nn.Module 서브클래스가 없습니다` | 클래스가 `nn.Module` 을 상속하지 않음 | `class MyModel(nn.Module):` 로 변경 |
| `forward() 메서드가 없습니다` | `forward` 를 다른 이름으로 정의함 | 반드시 `def forward(self, x):` 로 정의 |
| `'os' import는 허용되지 않습니다` | 금지 모듈 import | 해당 import 삭제 |
| `모델 인스턴스 생성 실패` | 생성자에 필수 인자 | `__init__` 인자에 기본값 추가 |
| `코드 크기가 256KB를 초과합니다` | 코드가 너무 큼 | 모델만 남기고 나머지 제거 |

---

## 📁 관련 소스 코드

| 파일 | 역할 |
|---|---|
| `app/core/model_validator.py` | AST 기반 코드 검증 |
| `app/core/model_loader.py` | 샌드박스 실행 + nn.Module 인스턴스화 |
| `app/tabs/model_tab.py` | 모델 탭 UI (에디터, 검증/로드 버튼) |
| `app/widgets/model_preset_dialog.py` | 프리셋 라이브러리 팝업 |
| `app/model_presets/` | 내장 프리셋 7종 코드 |
