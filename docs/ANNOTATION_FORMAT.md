# ANNOTATION FORMAT — JSON 스키마 명세

## 버전: 1.0

파일 위치: `data/annotations/{image_stem}.json`

---

## 최상위 구조

```json
{
  "version": "1.0",
  "image": "img_001.jpg",
  "width": 1024,
  "height": 768,
  "classes": [
    {"class_id": 0, "name": "background", "color": [0, 0, 0]},
    {"class_id": 1, "name": "cat",        "color": [255, 0, 0]},
    {"class_id": 2, "name": "dog",        "color": [0, 255, 0]}
  ],
  "annotations": [
    { ... polygon annotation ... },
    { ... brush annotation ... }
  ]
}
```

---

## Polygon Annotation

```json
{
  "annotation_id": "550e8400-e29b-41d4-a716-446655440000",
  "class_id": 1,
  "type": "polygon",
  "order": 0,
  "points": [
    [100.0, 150.0],
    [200.0, 100.0],
    [300.0, 180.0],
    [250.0, 300.0],
    [120.0, 280.0]
  ]
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| annotation_id | string (UUID4) | 고유 식별자 |
| class_id | int | 클래스 인덱스 |
| type | "polygon" | 고정값 |
| order | int | 레이어 순서 (높을수록 앞에 렌더링) |
| points | `[[x, y], ...]` | 픽셀 좌표, float, 최소 3개 |

---

## Brush Annotation (RLE)

```json
{
  "annotation_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
  "class_id": 2,
  "type": "brush_mask",
  "order": 1,
  "width": 1024,
  "height": 768,
  "rle": "1234 56 2000 30 5000 100"
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| annotation_id | string (UUID4) | 고유 식별자 |
| class_id | int | 클래스 인덱스 |
| type | "brush_mask" | 고정값 |
| order | int | 레이어 순서 |
| width, height | int | 마스크 원본 해상도 |
| rle | string | Run-Length Encoding |

### RLE 인코딩 방식

1. 마스크를 `(height, width)` → flatten → `(height * width,)` 1D 배열
2. 값이 1인 픽셀의 연속 구간을 `{시작_인덱스} {길이}` 쌍으로 표현
3. 쌍을 공백으로 구분한 문자열

```python
# 인코딩 예시
def rle_encode(mask: np.ndarray) -> str:
    flat = mask.flatten()
    result = []
    i = 0
    while i < len(flat):
        if flat[i] == 1:
            start = i
            while i < len(flat) and flat[i] == 1:
                i += 1
            result.extend([start, i - start])
        else:
            i += 1
    return " ".join(map(str, result))
```

---

## 버전 이력

| 버전 | 변경 내용 |
|------|-----------|
| 1.0 | 초기 릴리스 — polygon, brush_mask 지원 |

---

## 하위 호환성 정책

- `version` 필드 누락 시 `"1.0"`으로 간주
- 미래 버전에서 필드 추가 시 기존 파일은 기본값으로 처리
- 필드 삭제·타입 변경은 메이저 버전 업으로 처리
