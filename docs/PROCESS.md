# PROCESS — 이미지 처리 파이프라인

## 1. 이미지 수집

```
사용자 선택 (QFileDialog)
    └─> 원본 파일을 data/images/ 에 복사
    └─> 썸네일 생성 (128x128, JPEG) → data/images/.thumbs/
    └─> ImageBrowser에 항목 추가
```

지원 포맷: JPEG, PNG, BMP, TIFF

---

## 2. 어노테이션 → 마스크 변환 (`app/core/dataset.py`)

### Polygon → 픽셀 마스크
```python
from PIL import Image, ImageDraw

mask = Image.new("L", (width, height), 0)
draw = ImageDraw.Draw(mask)
for ann in polygon_annotations:
    draw.polygon(ann.points, fill=ann.class_id)
```

### Brush Mask (RLE) → 픽셀 마스크
```python
# RLE 인코딩: run-length encoding on flattened boolean array
# 형식: "start_idx length start_idx length ..."
def rle_decode(rle: str, height: int, width: int) -> np.ndarray:
    flat = np.zeros(height * width, dtype=np.uint8)
    tokens = list(map(int, rle.split()))
    for i in range(0, len(tokens), 2):
        flat[tokens[i]: tokens[i] + tokens[i+1]] = 1
    return flat.reshape(height, width)
```

### 레이어 병합 (우선순위: 나중에 추가된 어노테이션이 앞에)
```python
final_mask = np.zeros((height, width), dtype=np.int64)
for ann in sorted(annotations, key=lambda a: a.order):
    layer = render_annotation(ann)
    final_mask[layer > 0] = ann.class_id
```

---

## 3. Dataset 구조 (`app/core/dataset.py`)

```python
class SegmentationDataset(Dataset):
    def __getitem__(self, idx):
        image = load_image(self.image_paths[idx])     # PIL → Tensor (C,H,W) float32
        mask  = render_annotations(self.ann_paths[idx]) # → Tensor (H,W) int64
        if self.transform:
            image, mask = self.transform(image, mask)
        return image, mask
```

### 전처리 (transform)
1. Resize → `config.image_size` (bilinear for image, nearest for mask)
2. Albumentations 적용
3. ToTensor + Normalize(mean=[0.485,0.456,0.406], std=[0.229,0.224,0.225])

---

## 4. Augmentation 파이프라인 (`app/core/augmentations.py`)

```python
import albumentations as A

def build_pipeline(steps: list[AugmentationStep]) -> A.Compose:
    transforms = []
    for step in steps:
        cls = getattr(A, step.type)          # 이름으로 클래스 룩업
        transforms.append(cls(**step.params))
    return A.Compose(
        transforms,
        additional_targets={"mask": "mask"},  # 이미지와 마스크 동일하게 변환
    )
```

### 지원 augmentation 목록

| 이름 | 주요 파라미터 |
|------|---------------|
| HorizontalFlip | p |
| VerticalFlip | p |
| RandomRotate90 | p |
| RandomBrightnessContrast | brightness_limit, contrast_limit, p |
| GaussNoise | var_limit, p |
| Blur | blur_limit, p |
| ElasticTransform | alpha, sigma, p |
| GridDistortion | p |
| RandomCrop | height, width |
| PadIfNeeded | min_height, min_width |

---

## 5. DataLoader 파이프라인

```python
train_size = int(len(dataset) * config.dataset_split)
val_size   = len(dataset) - train_size
train_ds, val_ds = random_split(dataset, [train_size, val_size])

train_loader = DataLoader(
    train_ds, batch_size=config.batch_size,
    shuffle=True, num_workers=config.num_workers,
    pin_memory=(config.device == "cuda"),
)
val_loader = DataLoader(
    val_ds, batch_size=config.batch_size,
    shuffle=False, num_workers=config.num_workers,
)
```

---

## 6. 추론 후처리 (`app/core/inference_engine.py`)

```
입력 이미지 (PIL)
    └─> Resize → 모델 학습 시 image_size로
    └─> Normalize (체크포인트 저장된 mean/std)
    └─> forward pass → logits (1, C, H, W)
    └─> argmax(dim=1) → class_map (H, W) int64
    └─> 팔레트 룩업 → RGB 이미지 (H, W, 3)
    └─> Alpha blend with original image (opacity slider)
    └─> Resize back → 원본 해상도
    └─> QImage → QPixmap → OverlayViewer 표시
```

### Alpha Blending
```python
result = cv2.addWeighted(
    original_rgb, 1.0 - opacity,
    colorized_mask, opacity,
    0,
)
```

---

## 7. 데이터 디렉토리 레이아웃

```
data/
├── images/
│   ├── img_001.jpg
│   ├── img_002.png
│   └── .thumbs/          # 자동 생성 썸네일
│       ├── img_001.jpg
│       └── img_002.jpg
├── annotations/
│   ├── img_001.json
│   └── img_002.json
├── checkpoints/
│   ├── epoch_0005.pt
│   └── epoch_0010.pt
└── user_models/
    └── model_20250418_120000.py
```

---

## 8. 이미지 ↔ 어노테이션 연결

- 이미지 파일 `img_001.jpg` ↔ 어노테이션 `img_001.json` (stem 이름 매칭)
- 이미지 삭제 시 대응하는 JSON도 함께 삭제
- 이미지 이름 변경 금지 (stem으로 연결되므로) — 변경 시 annotation 재연결 필요
