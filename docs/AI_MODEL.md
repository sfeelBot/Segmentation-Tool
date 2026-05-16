# AI Model — 모델·학습·추론 파이프라인

## 모델 계약 (User Model Contract)

사용자가 제공하는 코드는 다음 조건을 만족해야 한다:

1. `torch.nn.Module` 서브클래스가 정확히 하나 존재
2. `forward(self, x: Tensor) -> Tensor` 메서드 구현
3. 입력 텐서 shape: `(B, C, H, W)` — batch, channel, height, width
4. 출력 텐서 shape: `(B, num_classes, H, W)` — 각 픽셀별 클래스 로짓

```python
# 최소 유효 예시
import torch.nn as nn

class MyModel(nn.Module):
    def __init__(self):
        super().__init__()
        self.conv = nn.Conv2d(3, 2, 1)

    def forward(self, x):
        return self.conv(x)
```

---

## AST 검증 규칙 (`app/core/model_validator.py`)

### 허용 import
```
torch, torch.nn, torch.nn.functional, torch.nn.init
torchvision, torchvision.models, torchvision.ops
numpy, math, typing, collections, functools, itertools
```

### 차단 항목
- import: `os`, `sys`, `subprocess`, `socket`, `requests`, `urllib`, `shutil`, `pathlib`
- 내장 함수 호출: `eval()`, `exec()`, `compile()`, `open()`, `__import__()`
- 속성 접근: `__class__.__bases__`, `__subclasses__`

### 구조 검사
- `nn.Module` 서브클래스 수: 정확히 1개 이상
- `forward` 메서드: 반드시 존재

### 반환값
```python
@dataclass
class ValidationResult:
    ok: bool
    errors: list[str]   # 각 항목: "Line 5: import os is not allowed"
```

---

## 제한적 실행 샌드박스 (`app/core/model_loader.py`)

```python
SAFE_BUILTINS = {
    k: __builtins__[k]
    for k in ['abs','all','any','bool','dict','enumerate','float',
              'int','len','list','map','max','min','range','round',
              'set','sorted','str','sum','tuple','zip','print']
}
safe_globals = {
    '__builtins__': SAFE_BUILTINS,
    'torch': torch,
    'nn': torch.nn,
    'F': torch.nn.functional,
}
exec(validated_code, safe_globals)
ModelClass = _find_nn_module_subclass(safe_globals)
model = ModelClass()
```

---

## 이미지 샘플링 모드 (`app/core/dataset.py`)

50MB 급 대형 이미지(6000×4000 등)의 산업용 검사에는 **random_crop** 을 권장한다.

### 세 가지 모드

| 모드 | 설명 | 권장 상황 |
|---|---|---|
| `random_crop` | 원본 해상도에서 patch_size 크기 패치 랜덤 크롭 | **대형 이미지 기본값** |
| `resize` | 전체 이미지를 patch_size 로 축소 | 작은 이미지, 전역 맥락 중요 시 |
| `center_crop` | 이미지 중앙에서 패치 크롭 | validation 일관성, 단독 사용 지양 |

### resize vs random_crop 비교

```
resize 방식 (6000×4000 → 512×512):
  └─ 원본 1픽셀 → 실제 11.7×11.7 픽셀에 해당
  └─ 3mm 결함 → 0.25mm 로 소멸 ← 산업용 미세 결함 탐지에 치명적

random_crop 방식:
  └─ 6000×4000 이미지에서 512×512 패치를 잘라냄
  └─ 원본 해상도 그대로 유지 ← 미세 결함 학습 가능
```

### Defect-Biased Sampling (결함 우선 샘플링)

순수 랜덤 크롭만 하면 95% 이상 패치가 배경 전용 → 모델 배경 편향 문제 발생.

```
defect_sample_prob = 0.7 (기본값) 일 때:

  70% 확률 ──→ 어노테이션 중심점 근처에서 패치 위치 결정
               ± patch_size × 25% jitter 추가
  30% 확률 ──→ 이미지 전체에서 균등 랜덤 샘플링
```

**사전 계산 (init 시 1회)**:
- JSON 파싱만으로 어노테이션 중심 좌표 추출 (마스크 렌더링 없이 빠름)
- polygon → 꼭짓점 평균
- brush_mask → 저장된 width/height 중앙 근사

### Validation 처리

```python
# 학습: 지정된 sample_mode 사용
train_ds = SegmentationDataset(mode=cfg.sample_mode, ...)

# 검증: 항상 resize (패치 랜덤성으로 인한 loss 변동 방지)
val_ds = SegmentationDataset(mode="resize", ...)
```

### Image-smaller-than-patch 폴백

```
patch_size > image.size 인 경우 → 자동으로 resize 로 폴백
(학습 데이터 중 소수 이미지가 작을 때 에러 없이 처리)
```

---

### Epoch당 학습 샘플 수 — `patches_per_image`

#### 왜 필요한가

`resize` 모드에서는 이미지 1장 = 샘플 1개. 그런데 `random_crop` 에서도 이미지 1장에서
1개만 뽑으면 이미지의 대부분을 못 보고 epoch 가 끝난다.

```
6000×4000 이미지에서 512×512 패치 가능 수 ≈ 117개 (비중복)
patches_per_image=1 이면 epoch당 1개만 추출 → 이미지의 1/117 만 학습
patches_per_image=50 이면 epoch당 50개 추출 → 50/117 ≈ 43% 커버
```

#### 학습 샘플 수 공식

```
epoch당 샘플 수 = 라벨링 이미지 수 × patches_per_image
epoch당 배치 수 = 샘플 수 / batch_size

예) 라벨링 20장, patches_per_image=50, batch_size=4:
  샘플 수 = 20 × 50 = 1,000
  배치 수 = 1,000 / 4 = 250 배치/epoch
```

#### resize vs random_crop 비교 (20장, batch=4, 50 epochs)

| | resize | random_crop (권장 설정) |
|---|---|---|
| epoch당 샘플 | 20 | 1,000 |
| epoch당 배치 | 5 | 250 |
| 해상도 | 1/12 로 축소 | 원본 유지 |
| 50 epochs 총 샘플 | 1,000 | 50,000 |

#### 구현 방식

```python
def __len__(self):
    return len(self._pairs) * self._patches_per_img  # 확장된 가상 길이

def __getitem__(self, idx):
    pair_idx = idx % len(self._pairs)   # 실제 이미지 인덱스로 변환 (순환)
    img, mask = load(self._pairs[pair_idx])
    x0, y0 = self._crop_pos(pair_idx, ...)
    return crop(img, mask, x0, y0)
```

DataLoader 가 `range(len(dataset))` 를 순회하면 각 이미지에서
`patches_per_image` 번씩 무작위 크롭이 발생한다.

#### patches_per_image 권장값

| 이미지 크기 | 권장값 | 이유 |
|---|---|---|
| ~1 MP (1000×1000) | 10~20 | 패치가 이미지의 25% 이상 |
| ~6 MP (6000×4000, 50MB) | **50~100** | 패치가 이미지의 약 1/117 |
| 10 MP 이상 | 100~200 | 커버리지 확보 필요 |

- 크게 잡을수록 epoch가 길어지지만 이미지를 골고루 학습
- 너무 작으면 이미지 대부분을 못 본 채 epoch 종료

---

## 학습 루프 (`app/core/trainer.py`)

### QThread 시그널

```python
class TrainerWorker(QThread):
    epoch_done    = Signal(int, float, float, dict)
    # args: epoch, train_loss, val_loss, metrics
    # metrics: {"mean_iou": float, "dice": float}

    batch_done    = Signal(int, int, float)
    # args: epoch, batch_idx, loss

    checkpoint_saved = Signal(str)   # checkpoint path
    training_finished = Signal()
    training_error    = Signal(str)  # error message
```

### 학습 흐름

```
TrainingConfig 수신
  └─ SegmentationDataset 생성
  │    train_ds: sample_mode (random_crop 등)
  │    val_ds:   항상 resize (일관성)
  └─ DataLoader x2 (train, val)
  └─ model.train()
  for epoch:
    for batch in train_loader:
      optimizer.zero_grad()
      output = model(images)
      loss = loss_fn(output, masks)
      loss.backward()
      optimizer.step()
      emit batch_done
    model.eval()
    compute val_loss, IoU, Dice
    emit epoch_done
    if epoch % checkpoint_every == 0: save + emit checkpoint_saved
    if stop_event.is_set(): break
  emit training_finished
```

### Mixed Precision (AMP)

**AMP = Automatic Mixed Precision** — FP32 와 FP16 을 자동으로 혼합해 학습.

```
FP32 (32비트): 정확하지만 메모리 4 bytes/값
FP16 (16비트): 덜 정확하지만 메모리 2 bytes/값

AMP 동작:
  학습 파라미터 보관  → FP32 (정확도 유지)
  행렬 연산(forward)  → FP16 (빠름, 메모리 절약)
  gradient 계산       → FP16
  gradient 스케일링   → GradScaler (underflow 방지)
  파라미터 업데이트   → FP32 로 변환 후 적용
```

**효과**:
- GPU 메모리 약 50% 절약
- 학습 속도 1.5~3× 향상 (Tensor Core 보유 GPU 기준)

**GPU 세대별 지원**:

| GPU 세대 | CC | 지원 | 효과 |
|---|---|---|---|
| Blackwell (RTX 50) | 12.0 | ✅ | 최대 |
| Ampere (RTX 30) / Ada (RTX 40) | 8.0~8.9 | ✅ | 최대 |
| Turing (RTX 20) | 7.5 | ✅ | 좋음 |
| Volta (V100) | 7.0 | ✅ | 좋음 |
| Pascal (GTX 10) | 6.x | ⚠️ | 이득 거의 없음 |
| Maxwell (M4000/M5000) | 5.x | ❌ | **자동 비활성화** |

```python
# device_info.py
if compute_capability < 7.0:
    log.warning("AMP 자동 비활성화 — Tensor Core 없음")
    return False
```

`torch.cuda.amp.GradScaler` 사용 (config.mixed_precision=True 시).  
MPS / CPU / CC < 7.0 GPU 에서는 자동 비활성화.

---

## 옵티마이저 (`app/core/trainer.py`)

### 종류 비교

| 옵티마이저 | 특징 | 권장 상황 |
|---|---|---|
| **Adam** | 파라미터별 적응적 학습률. 학습률 튜닝에 덜 민감 | 일반적인 기본값 |
| **AdamW** | Adam + Weight Decay 올바른 적용. 일반화 성능 Adam 보다 우수 | **산업용 권장** |
| **SGD** | 단순 gradient 강하 + momentum. 잘 튜닝하면 최고 성능 | Pretrained 미세조정 |
| **RMSprop** | gradient 제곱 이동평균으로 학습률 조정. 현재는 잘 안 씀 | 구형 모델 호환 |

---

## Weight Decay (L2 정규화)

파라미터가 너무 커지는 것을 억제해 **과적합 방지**.

```
loss_total = loss_task + weight_decay × Σ(w²)
```

| 값 | 의미 | 권장 상황 |
|---|---|---|
| `0.0` | 정규화 없음 | 데이터가 충분히 많을 때 |
| `1e-4` (0.0001) | 약한 정규화 | **산업용 결함 검출 기본값** |
| `1e-2` (0.01) | 강한 정규화 | 학습 데이터가 극소 (5장 이하) |

> ⚠️ 라벨 데이터가 적을수록 (20~50장) Weight Decay 가 중요하다.  
> `0.0` 으로 두면 결함이 없는 배경 패턴을 외워버리는(overfitting) 경향이 생긴다.  
> **기본값 `1e-4` 권장.**

---

## Momentum

**SGD 전용** 관성 계수 — 이전 update 방향을 현재에 더해 진동을 줄이고 수렴을 가속.

```
v_t = momentum × v_{t-1} + (1 - momentum) × gradient
w_t = w_{t-1} - lr × v_t

momentum = 0.0 → 순수 SGD (이전 방향 무시)
momentum = 0.9 → 이전 방향의 90% 유지 (표준값)
momentum = 0.99 → 매우 강한 관성 (lr 작을 때)
```

Adam / AdamW 에서는 내부적으로 유사 메커니즘이 β1 = 0.9 로 이미 포함되어 있어  
이 설정은 **SGD 를 선택했을 때만 의미있다**.

---

## 손실 함수 (`app/core/trainer.py`)

| 이름 | 설명 |
|------|------|
| `CrossEntropyLoss` | `torch.nn.CrossEntropyLoss` — 기본값 |
| `DiceLoss` | `1 - (2·TP) / (2·TP + FP + FN)` — 불균형 데이터에 유리 |
| `FocalLoss` | `-(1-p)^γ · log(p)` — 어려운 샘플 집중 |

---

## 메트릭 (`app/core/metrics.py`)

### IoU (Intersection over Union)
```
IoU_c = TP_c / (TP_c + FP_c + FN_c)
mean_IoU = mean(IoU_c for c in classes)
```

### Dice Coefficient
```
Dice_c = 2·TP_c / (2·TP_c + FP_c + FN_c)
```

---

## 체크포인트 포맷

```python
{
    "epoch": int,
    "model_state_dict": OrderedDict,
    "optimizer_state_dict": dict,
    "train_loss": float,
    "val_loss": float,
    "metrics": {"mean_iou": float, "mean_dice": float, "epoch_time": float},
    "config": {
        "image_w": int,
        "image_h": int,
        "sample_mode": str,   # "random_crop" | "resize" | "center_crop"
    },
}
```

파일명: `projects/<name>/checkpoints/{job_name}_epoch_{n:04d}.pt`

`sample_mode` 는 추론 시 자동 방식 결정에 사용된다.

---

## 추론 파이프라인 (`app/core/inference_engine.py`)

### 방식 1 — resize 추론 (`run()`)

```
이미지 로드
  └─ 체크포인트의 image_w/h 크기로 resize
  └─ ImageNet normalize
  └─ model(tensor) → (1, C, H, W)
  └─ argmax → (h, w) class_map (낮은 해상도)
  └─ 원본 크기로 NEAREST upsample
  └─ 컬러화 + alpha blend
```

적합한 경우: `sample_mode=resize` 로 학습된 모델, 작은 이미지

---

### 방식 2 — 슬라이딩 윈도우 추론 (`run_sliding_window()`)

`sample_mode=random_crop` 으로 학습된 모델에 권장.
원본 해상도에서 패치를 겹쳐가며 추론 후 확률 평균으로 합성한다.

```
원본 이미지 (6000×4000), patch=512×512, overlap=64px, stride=448px

패치 분할:
  x 방향: ceil(6000 / 448) = 14개
  y 방향: ceil(4000 / 448) = 9개
  총 126개 패치 (경계는 이미지 안으로 클리핑)

각 패치 추론 (batch_size=4):
  patch → normalize → model(batch) → softmax → probs (C, 512, 512)

확률 누적 (Probability Accumulation):
  acc[c, y0:y1, x0:x1] += probs[c]   # float32 (C, H, W)
  counts[y0:y1, x0:x1] += 1

겹치는 영역 평균:
  final_probs = acc / max(counts, 1)
  class_map = argmax(final_probs, axis=0)   # 원본 해상도 (H, W)
```

**overlap averaging 효과**:
- 패치 경계에서 부드러운 전환 (단순 tile 방식 대비 아티팩트 감소)
- 각 픽셀이 여러 패치에서 예측된 확률의 평균 → 더 안정적인 결과

**메모리**:
- acc 배열: `n_classes × H × W × 4 bytes`
- 6000×4000, 8 classes → 약 768 MB (float32)
- 메모리 부족 시 overlap 줄이거나 이미지를 행 단위로 분할 처리 고려

---

## 새 손실 함수 추가 방법

1. `app/core/trainer.py`의 `_build_loss_fn()` 에 분기 추가
2. `docs/AI_MODEL.md` 손실 함수 테이블 업데이트
3. `app/widgets/config_form.py` 드롭다운 옵션 추가
