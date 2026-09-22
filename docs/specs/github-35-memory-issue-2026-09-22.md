# GitHub #35 "메모리 이슈" — 수정 스펙 (2026-09-22)

기획 완료. 구현 담당은 이 문서의 코드 위치·순서·엣지케이스를 그대로 따를 것 — 구현 전
`git status`로 이 파일들이 최근 커밋 이후 변경되지 않았는지 재확인 권장(라인 번호는
2026-09-22 HEAD 기준).

## 배경

GitHub [#35](https://github.com/sfeelBot/Segmentation-Tool/issues/35) 로그에 반복되는
크래시:
```
numpy._core._exceptions._ArrayMemoryError: Unable to allocate 19.0 MiB for an array
with shape (19961856,) and data type uint8
  app\tabs\labeling_tab.py:376  _on_image_selected
  app\widgets\annotation_canvas.py:352  load_image   (현재 HEAD: 298~376행)
  app\core\annotation_store.py:95  load             (현재 HEAD: 88~119행)
  app\core\annotation_store.py:231  rle_decode       (현재 HEAD: 268~279행)
```
19,961,856 = 5472×3648(대형 배터리 캡 이미지류). 이슈 로그의 정확한 라인 번호는 그 시점
커밋 기준이라 현재 HEAD와 약간 다르지만(위 괄호), 호출 체인
(`labeling_tab._on_image_selected` → `AnnotationCanvas.load_image` → `annotation_store.load`
→ `rle_decode`) 자체는 그대로 유효함을 코드로 재확인했다. `export_dialog.py`의 `_on_run()`
→ `ExportWorker.run()` → `_export_json/_export_yolo/_export_coco` 경로도 같은
`annotation_store.load()`(별칭 `load_annotations`)를 이미지마다 호출해 동일 크래시 계열에
노출됨을 확인(아래 "Part 3" 참고).

`app/widgets/annotation_canvas.py`를 재조사해 근본 원인 하나를 추가로 확정했다:
`AnnotationCanvas._undo_stack`(`__init__` 189행)이 `load_image()`(298~376행, 이미지 전환마다
호출)에서 **전혀 초기화되지 않는다** — `.clear()`는 `clear()` 메서드(378~395행, 프로젝트/캔버스
전체 리셋용)에만 있다. `_push_undo()`(1542~1558행, 매 편집 시작마다 호출)는 현재
`self._annotations`(현재 이미지의 브러시 마스크 포함 전체 목록)의 스냅샷을 스택에 쌓고
(개수 캡 30), `undo()`(417~428행)는 스택 top을 pop해 `self._annotations`에 대입 후
`_schedule_save()`로 **현재 화면에 떠 있는 이미지 경로**에 저장한다.

**정정 — 과거 조사 메모(deepcopy)는 이미 낡음**: `_push_undo()` 자체 코드 주석(1542~1547행)과
`_snapshot_annotations()`(1522~1540행)를 실제로 읽어보면, GitHub 성능 리포트 대응으로 이미
`copy.deepcopy()` → numpy 네이티브 `.copy()`(memcpy) 기반 `_snapshot_annotations()`로 교체되어
있다(polygon points는 얕은 리스트 복사, mask만 `.copy()`). "deepcopy가 느려서 메모리를
더 쓴다"는 설명은 현재 코드에 더 이상 해당하지 않는다 — 다만 **스택 자체가 이미지별로
스코프되지 않고 개수 캡(30)만 있다는 문제는 그대로 남아 있고, 이것이 이번 이슈의 실제
근본 원인**이다. 구현 시 이 사실관계를 혼동하지 말 것(커밋 메시지/로그에 "deepcopy 제거"
같은 부정확한 서술을 넣지 않도록 유의).

결과적으로 두 가지 독립적 문제:
1. 이미지 A→B→C…로 전환하며 편집하면 여러 이미지의 대형 마스크 스냅샷이 캡 30 안에서
   뒤섞여 누적 — 메모리 누적의 실제 원인.
2. 이미지를 여러 번 전환한 뒤 Ctrl+Z를 누르면 스택에 남아있던 **다른 이미지**의 스냅샷이
   pop되어 `self._annotations`에 들어가고, 그게 **현재 화면 이미지의 파일 경로**에 저장될
   위험 — 잠재적 데이터 손상.

추가로 `rle_decode()`(268~279행)가 `np.zeros(height*width, ...)` 할당 시점에서
`_ArrayMemoryError`를 던질 수 있는데(크래시 로그와 정확히 일치하는 지점), 이를 감싸는
가드가 전혀 없다. 단일 대형 이미지 하나만 열어도 시스템 메모리가 빠듯하면(BUG-014가 이미
기록한 Windows 커밋/페이징 한계) 여전히 크래시 가능 — undo 스코핑 수정과 무관하게 별도로
필요.

## 확정된 수정 방향 (사용자 확정)

"이전 이미지 편집은 최대 그 직전 이미지에 대해서만 진행할 수 있도록" — undo 기록을
이미지별로 스코프하되 **현재 이미지 + 바로 직전 이미지 1개**까지만 유지. 추가로(작업 중
사용자 추가 요청) **캡 자체도 대형 이미지에서 메모리 에러를 유발하지 않도록 바이트
예산 기반으로 보강**.

---

## Part 1 — undo 스택 이미지 스코프 (`app/widgets/annotation_canvas.py`)

### 신규 인스턴스 필드 (`__init__`, 189행 부근에 추가)

```python
self._annotations: list[AnnotationItem] = []
self._undo_stack: list[list[AnnotationItem]] = []
self._prev_image_path: Path | None = None            # 신규
self._prev_undo_stack: list[list[AnnotationItem]] = []  # 신규 — "직전 이미지" 슬롯 1개
```

### `load_image(path)` 수정 (298~376행)

현재 코드는 `self._cancel_polygon(); self._finish_brush(); self._image_path = path`
순서로 진행된다(309~311행). **`self._image_path = path` 대입 직전**, 즉
`self._finish_brush()` 호출 뒤·`self._image_path = path` 대입 전에 아래 블록을 삽입한다
(이 시점에는 `self._image_path`/`self._undo_stack`이 여전히 **떠나는 이미지**의 값이라는
점이 핵심 — 순서를 바꾸면 안 됨):

```python
# GitHub #35 — undo 스택을 이미지별로 스코프한다: 현재 이미지 + 바로 직전 이미지
# 1개까지만 유지(그 이상은 자동으로 버려짐). 스코프 없이 그대로 쌓이면 여러 이미지의
# 대형 마스크 스냅샷이 undo 스택 하나에 섞여 메모리가 누적되고, undo() 시 다른
# 이미지의 스냅샷이 튀어나와 현재 이미지 파일에 잘못 저장될 위험이 있었다.
#
# 순서가 중요하다: "직전 슬롯"을 덮어쓰기 전에 먼저 새로 여는 이미지가 그 슬롯과
# 일치하는지 확인해야 A→B→A 왕복 시 A의 undo 이력이 복원된다(아래 "엣지케이스" 참고).
if path == self._prev_image_path:
    restored_stack = self._prev_undo_stack
else:
    restored_stack = None

if self._image_path is not None:   # 최초 load_image 호출(첫 이미지)이 아닐 때만
    self._prev_image_path = self._image_path
    self._prev_undo_stack = self._undo_stack

self._undo_stack = restored_stack if restored_stack is not None else []

self._image_path = path
```

`undo()`(417~428행)는 코드 변경 불필요 — 항상 `self._undo_stack`(현재 이미지에 실제로
속한 스택)만 조작하므로, 위 스코핑만으로 "다른 이미지 스냅샷이 현재 파일에 저장되는"
데이터 손상 위험도 함께 해소된다.

### `clear()` 수정 (378~395행)

기존 `self._undo_stack.clear()` 옆에 직전 슬롯도 함께 비운다(프로젝트/캔버스 전체
리셋이므로 남아있는 다른 이미지의 undo 이력을 들고 있을 이유가 없음 — 메모리 상한
원칙과도 일치):

```python
self._undo_stack.clear()
self._prev_image_path = None      # 신규
self._prev_undo_stack = []        # 신규
```

### 엣지케이스 명세 (구현·검증 시 반드시 확인)

| 시나리오 | 기대 동작 | 근거 |
|---|---|---|
| 최초 로드(`self._image_path is None`) | `_prev_image_path`/`_prev_undo_stack` 건드리지 않음, `_undo_stack = []` | "떠나는 이미지"가 없으므로 저장할 것도 없음 |
| A→B (최초 전환) | B의 `_undo_stack = []`(신규), 직전 슬롯 = A | 일반 전환 |
| A→B→C | C 진입 시 직전 슬롯이 B로 덮어써짐 — **A의 undo 이력은 이 시점에 사라짐** | "직전 1개까지만" 요구사항의 자연스러운 결과 — 2단계 이상 떨어진 이미지는 복원되지 않는 것이 사양(구현자가 "버그 아닌가"로 착각해 되살리는 로직을 추가하지 말 것) |
| A→B→A (왕복) | A 재진입 시 `path(A) == prev_image_path(A)` 비교가 **아직 덮어쓰기 전**에 일어나므로 `restored_stack = A의 이전 undo_stack` — 정확히 복원됨 | 위 코드 블록의 순서(먼저 비교, 그다음 덮어쓰기)가 핵심. 순서를 바꾸면(덮어쓴 뒤 비교) 이 케이스가 깨짐 |
| A→B→C→A (2단계 이상 왕복) | A의 이력은 이미 사라졌으므로 A 재진입 시 `_undo_stack = []`(신규) | 표와 동일 원리, "직전 1개"만 보장 |
| `clear()` 호출 후 재사용 | 직전 슬롯도 비어 있어야 함 | 위 `clear()` 수정 |
| 이미지 전환 중 저장 실패/취소 없음 | 스코핑 로직은 저장 여부와 무관하게 항상 실행(위 기존 `_do_save()` flush 로직 이후) | 저장과 undo 스코핑은 독립적 관심사 |

이 스코핑으로 메모리에는 **최대 2개 이미지 분량**(현재 + 직전)의 undo 스택만 존재하게
된다. 다만 이미지 1장의 스택 자체도 대형 이미지에서는 여전히 클 수 있어 Part 2로 보강한다.

---

## Part 2 — undo 스택 바이트 예산 상한 (사용자 추가 요청, `annotation_canvas.py`)

### 배경 — 기존 개수 캡(30)만으로는 부족한 이유

`_push_undo()`(1542~1558행)의 기존 캡은 `len(self._undo_stack) > 30: pop(0)` — **개수만
보고 바이트 크기를 보지 않는다**. `AnnotationItem.mask`는 항상 `(img_h, img_w)` 크기의
dense `uint8` 배열로 저장된다(`_paint_circle()` 665행 `np.zeros((self._img_h, self._img_w))`,
`_finish_brush()` 961행 `mask=self._brush_np.copy()` — bbox-crop은 오버레이 **렌더링**
최적화(`_OverlayWorker`)에만 적용되고 저장 배열 자체는 크롭되지 않음, 확인 완료). 즉
5472×3648 이미지의 마스크 1개는 정확히 19,961,856바이트(≈19MiB, 크래시 로그와 정확히
일치) — 이미지 한 장에 brush_mask가 여러 개면 스냅샷 1개가 수십~수백MB가 될 수 있고,
Part 1의 "최대 2개 이미지" 스코핑을 적용해도 각 이미지 스택이 30개까지 찰 수 있어
대형 이미지에서는 여전히 부족하다.

### 설계 판단 — 바이트 예산 방식 채택 (해상도 기반 근사 캡 대신)

두 방식을 검토했다:
- (기각) **해상도 비례 캡**(예: `cap = budget / (img_w*img_h)`) — 마스크 1개 크기의 근사치일
  뿐이고, 스냅샷 1개에 마스크가 몇 개 들어있는지(어노테이션 개수)는 전혀 반영하지 못해
  여전히 부정확.
- (채택) **실측 바이트 예산** — 각 마스크가 항상 정확히 `img_h*img_w`바이트(dense, 위에서
  확인)이므로 `ndarray.nbytes`(O(1), numpy가 메타데이터로 들고 있어 스캔 비용 없음)를
  합산하면 근사가 아니라 **정확한 값**이 나온다. 스택 크기 자체가 이미 캡으로 작게
  유지되므로(아래) 매 push마다 전체 재계산해도 비용은 무시할 수준(스냅샷 생성 자체의
  `.copy()` 비용이 이미 훨씬 큼) — 별도의 증분 카운터(push/pop마다 별도 필드 갱신)를
  두지 않는다. 여러 메서드(`_push_undo`/`undo`/`load_image`/`clear`)에 걸쳐 카운터
  동기화를 유지해야 하는 복잡도·버그 위험을 감수할 이유가 없음(기존 코드베이스
  패턴 — `_MAX_OVERLAY_DIM`/`_IMAGE_CACHE_SIZE`도 단순 고정 상수 + 매번 재계산/재적용
  방식이지 증분 카운터를 쓰지 않음 — 이 방식과 가장 자연스럽게 맞음).

### 구현

모듈 상수 블록(150~157행 부근, `_IMAGE_CACHE_SIZE` 옆)에 추가:

```python
_IMAGE_CACHE_SIZE = 2      # 최근 방문 이미지 LRU 캐시 최대 장수 (대형 원본 메모리 고려, 확장 금지)

# GitHub #35 — undo 스택 상한. 개수 캡(30)은 소형 이미지에서 여전히 유효한 1차 방어선으로
# 유지하고, 바이트 예산은 대형 이미지에서 실질적으로 작동하는 2차 방어선이다. 마스크는
# 항상 (img_h*img_w) 바이트 dense 배열이므로(위 설계 판단 참고) 이 값은 근사치가 아니라
# "이미지 1장의 undo 스택에 허용할 마스크 총량"을 그대로 의미한다. 200MB는 시작값 —
# 5472x3648(19MiB/마스크) 기준 약 10개 스냅샷 분량. 현재+직전 이미지 슬롯이 각각 이 예산을
# 가지므로 undo만으로 늘어날 수 있는 최악 총량은 대략 2x(400MB). 실측 OOM 여유가 이보다
# 타이트해야 한다고 검증 단계에서 확인되면 이 상수만 낮추면 된다(구조 변경 불필요).
_MAX_UNDO_STEPS = 30
_MAX_UNDO_BYTES = 200 * 1024 * 1024
```

모듈 레벨 헬퍼(파일 하단, `_mask_bbox`/`_polygon_bbox` 등 기존 free function들과 같은
구역에 추가):

```python
def _annotations_mask_bytes(anns: list[AnnotationItem]) -> int:
    """스냅샷(어노테이션 목록) 하나가 차지하는 마스크 바이트 총량.
    polygon은 points(튜플 리스트)만 가져 사실상 0바이트 — brush_mask만 집계한다."""
    return sum(a.mask.nbytes for a in anns if a.mask is not None)
```

`_push_undo()`(1542~1558행) 수정 — 기존 개수 캡을 개수+바이트 이중 조건으로 교체:

```python
def _push_undo(self) -> None:
    # (기존 MemoryError try/except 블록 그대로 유지 — BUG-014)
    try:
        snap = self._snapshot_annotations()
    except MemoryError as exc:
        from app.core.logger import get_logger
        get_logger(__name__).warning(
            f"undo 스냅샷 생성 실패(메모리 부족) — 이번 편집은 undo 불가: {exc}"
        )
        return
    self._undo_stack.append(snap)
    # GitHub #35 — 개수 캡(30)은 소형 이미지 보호용으로 유지, 바이트 예산은 대형
    # 이미지(마스크 1개당 수십MB)에서 개수 캡보다 먼저 작동하는 실질 상한이다.
    while len(self._undo_stack) > 1 and (
        len(self._undo_stack) > _MAX_UNDO_STEPS
        or sum(_annotations_mask_bytes(s) for s in self._undo_stack) > _MAX_UNDO_BYTES
    ):
        self._undo_stack.pop(0)
```

`len(self._undo_stack) > 1` 가드는 스냅샷 1개(방금 push한 것)조차 예산을 넘는 극단적
케이스(마스크가 매우 많은 이미지)에서 스택을 완전히 비워버려 "이번 편집조차 undo
불가"가 되는 것을 막기 위함 — 최소 1개(가장 최근 것)는 항상 남긴다(BUG-014의 철학과
동일: "undo 불가"가 "무한정 앱이 죽는 것"보다 낫다는 원칙을 여기서도 "가장 최근 1개는
undo 가능"으로 확장 적용).

`_prev_undo_stack`은 이미 이 캡을 통과한 `_undo_stack`을 그대로 이관받으므로(Part 1)
별도 트리밍 로직이 필요 없다 — 자동으로 같은 상한을 상속한다.

### 검증 시 확인 항목 (구현자/검증자 공통)

- 소형 이미지(예: 1000×1000 이하)에서는 기존과 동일하게 30개 개수 캡이 먼저 걸려
  동작·UX 회귀가 없어야 한다(바이트 예산이 개입하지 않는 구간).
  대형 이미지(20MP급)에서 brush_mask를 반복 커밋하며 undo 스택을 push할 때, 스택이
  `_MAX_UNDO_BYTES`를 넘기지 않는 선에서 자동으로 앞에서부터 트리밍됨을 실측(로그 또는
  디버거로 `sum(_annotations_mask_bytes(s) for s in canvas._undo_stack)` 확인).
- 최소 1개는 항상 남아 undo가 완전히 불가능해지지 않는지 확인(위 `len() > 1` 가드).
- 이 기능이 실제로 GitHub #35의 재현 규모(20MP, 브러시 다수 편집)에서 메모리 에러
  발생 여부를 낮추는지 리소스 모니터(작업 관리자/`psutil`)로 정성 확인 — 정확한 OOM
  경계는 사용자 실환경(Windows 커밋 한도)에 의존하므로 100% 재현/반증은 범위 밖.

---

## Part 3 — `rle_decode()` 방어 처리 (`app/core/annotation_store.py`)

### 배경

`load()`(88~119행)이 `brush_mask` 항목마다 `rle_decode()`(268~279행)를 호출하는데,
`rle_decode()` 내부 `np.zeros(height * width, dtype=np.uint8)`(270행)가 크래시 로그의
정확한 실패 지점과 일치한다. 이 경로엔 어떤 가드도 없어 **어노테이션 1개의 디코딩
실패가 이미지 전체 로드를, 나아가 앱 전체를 죽인다.**

### 구현

파일 상단 import 블록에 로거 추가:
```python
from app.core import project as _project
from app.core.file_io import atomic_write
from app.core.logger import get_logger   # 신규

log = get_logger(__name__)               # 신규, 모듈 레벨(export_dialog.py와 동일 관례)
```

`load()`(88~119행)의 `brush_mask` 분기만 수정 — BUG-014의 `_push_undo()` 완화 패턴과
동일하게 "그 어노테이션 1개만 건너뛰고 나머지는 정상 로드":

```python
def load(image_path: Path) -> list[AnnotationItem]:
    json_path = _ann_path(image_path)
    if not json_path.exists():
        return []
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    items: list[AnnotationItem] = []
    for a in data.get("annotations", []):
        if a["type"] == "polygon":
            items.append(AnnotationItem(
                annotation_id=a["annotation_id"],
                class_id=a["class_id"],
                type="polygon",
                order=a.get("order", 0),
                points=[tuple(p) for p in a["points"]],
            ))
        elif a["type"] == "brush_mask":
            w, h = a["width"], a["height"]
            try:
                mask = rle_decode(a.get("rle", ""), h, w)
            except MemoryError as exc:   # numpy _ArrayMemoryError는 MemoryError 서브클래스
                log.warning(
                    f"brush_mask 디코딩 실패(메모리 부족) — "
                    f"annotation_id={a.get('annotation_id')} 건너뜀 "
                    f"(image={image_path.name}, {w}x{h}): {exc}"
                )
                continue
            items.append(AnnotationItem(
                annotation_id=a["annotation_id"],
                class_id=a["class_id"],
                type="brush_mask",
                order=a.get("order", 0),
                mask=mask,
                width=w,
                height=h,
            ))
    return sorted(items, key=lambda x: x.order)
```

### 엣지케이스

- `has_annotations()`(75~85행)는 RLE 디코딩을 하지 않으므로(JSON 메타데이터만 읽음)
  이 가드와 무관 — 수정 불필요.
- 건너뛴 어노테이션은 **그 세션에서 메모리에 올라오지 않을 뿐 디스크 JSON은 그대로**
  보존된다(이 함수는 읽기 전용 — `save()`를 별도로 호출하지 않는 한 유실 없음). 다만
  사용자가 이 상태에서 편집 후 저장하면 `save()`가 `self._annotations`(건너뛴 항목이
  빠진 상태)를 그대로 직렬화하므로 **그 어노테이션은 디스크에서도 사라진다** — 이는
  BUG-014의 undo 스냅샷 실패와 동일한 성격의 트레이드오프(완전한 크래시보다 낫다는
  이미 합의된 원칙)이며 이번 스펙의 범위에서 추가로 막지 않는다. 필요 시 UI 경고
  팝업(로그가 아니라 `QMessageBox`)을 띄울지는 별도 후속 논의로 남긴다(이번 구현
  스펙에는 미포함 — 과잉 구현 방지, `core/`는 예외를 UI로 직접 띄우지 않는 코딩 규칙과도
  충돌).

---

## Part 3-B — `export_dialog.py`는 코드 변경 불필요 (확인만)

`_on_run()`(345~382행) → `ExportWorker`(백그라운드 `QThread`) → `_export_json`(86행)/
`_export_yolo`(139행)/`_export_coco`(188행)가 전부 `load_annotations`(=`annotation_store.load`
의 alias, 18~20행 import)를 이미지 1장씩 호출한다. Part 3의 수정이 `annotation_store.load()`
단일 지점에 들어가므로 **이 세 경로 모두 자동으로 동일하게 보호된다** — root-cause
fix를 공유 함수 1곳에 넣는 원칙대로 `export_dialog.py` 자체는 건드릴 필요가 없다.

다만 개선 효과의 성격이 다르다는 점을 기록해둔다: `ExportWorker.run()`은 이미 최상위
`try/except Exception`(54~66행)으로 감싸여 있어 Part 3 수정 이전에도 `MemoryError`가
**앱 전체를 죽이지는 않았다**(`error` 시그널로 `QMessageBox` 표시, 이미 안전). 그러나
그 최상위 catch는 **export 작업 전체를 그 지점에서 중단**시켜, 실패한 이미지 이후
순서의 이미지들은 아예 내보내지지 않았다. Part 3 수정 후에는 "문제의 마스크 1개만
건너뛰고 export 전체가 끝까지 완료"로 개선된다 — 이것이 `export_dialog.py` 관점에서의
실질적 효과.

---

## 실행 순서 제안

파일이 겹치지 않아 병렬 가능:
- (A) `app/widgets/annotation_canvas.py` — Part 1(undo 스코핑) + Part 2(바이트 예산).
  같은 파일·인접 메서드라 한 번에 함께 구현 권장(Part 1 없이 Part 2만 넣어도 동작은
  하지만, 두 파트가 같은 문제(#35)의 짝이라 리뷰/검증을 분리할 이유가 없음).
- (B) `app/core/annotation_store.py` — Part 3(rle_decode 가드). `export_dialog.py`는
  코드 변경 없음(Part 3-B).

## 검증 골든패스 제안

- 실제 대형 이미지(가능하면 재현 규모에 가까운 것, 없으면 합성 20MP 이미지) + 라벨링
  탭에서 이미지 A→B→A 왕복 편집 후 `canvas._undo_stack`/`canvas._prev_undo_stack`이
  각각 A/B에 정확히 대응하는지, `Ctrl+Z`가 항상 현재 화면 이미지의 올바른 이전 상태로
  복귀하는지(다른 이미지 데이터가 섞이지 않는지) 확인.
- A→B→C→A 시나리오에서 A의 undo 이력이 정확히 사라짐(스펙대로 — 버그 아님)을 확인.
  `clear()`(프로젝트 전환 등) 후 직전 슬롯도 비었는지 확인.
  브러시 반복 편집으로 대형 이미지 undo 스택이 `_MAX_UNDO_BYTES`를 넘기지 않고
  자동 트리밍되는지, 그 상태에서도 최소 1회 undo는 항상 가능한지 확인.
- `rle_decode()`에 인위적으로 `MemoryError`를 주입(모킹)해 `load()`가 해당 어노테이션만
  건너뛰고 나머지 정상 어노테이션은 그대로 반환하는지, 로그에 경고가 남는지 확인.
- `export_dialog.py`로 정상 프로젝트 export 골든패스(JSON/YOLO/COCO 3포맷 각각) 회귀
  확인 — 코드 변경이 없더라도 import 경로(`annotation_store.load`)가 정상 동작하는지
  기존 동작과 동일한지 재확인.

## 결정 필요 사항

없음 — 모든 방향이 사용자 확정(초기 지시) + 이번 세션 추가 요청(바이트 예산)으로 이미
결정됨. `_MAX_UNDO_BYTES` 정확한 수치는 위에 명시한 대로 "시작값, 실측 후 상수만
조정 가능"으로 문서화했으며 별도 사용자 확인 없이 구현 진행 가능.
