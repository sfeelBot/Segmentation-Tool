# 존(Zone) 분석 탭 — 신규 기능 5건 기획 (2026-08-27, 라운드3)

브랜치 `feature/zone-analysis-tab`(에디션 브랜치, main 역병합 없음). 워크트리
`D:\segmentation model-zone-analysis-tab`. 전제: R1~R4([zone-analysis-tab-2026-08-25.md](zone-analysis-tab-2026-08-25.md))와
신규 기능 3건 R-A/R-B/R-C([zone-analysis-tab-features-2026-08-26.md](zone-analysis-tab-features-2026-08-26.md))
전부 구현+검증 통과해 push된 상태(`origin/feature/zone-analysis-tab` 최신). 이번 문서는 그 위에
사용자가 추가 요청한 5건을 다룬다 — 기존 확정 사항(원 데이터 모델, 완전 독립 원칙, 존 계산
로직, 체크포인트→모델 재구성, 타겟 클래스 즉석 구성 등)은 그대로 유지, 재논의하지 않는다.

## 코드 조사 결과 요약

기존 5개 핵심 파일(`zone_analysis_tab.py`, `zone_canvas.py`, `circle_detect_preview_dialog.py`,
`zone_batch_result_dialog.py`, `zone_metrics.py`)과 재사용 대상(`annotation_canvas.py`의
undo/브러시 구현)을 전수 정독했다. 핵심 발견:

- **`ZoneCanvas`에는 현재 undo가 전혀 없다.** 원 생성/이동/반지름조절/삭제, 블랍 클릭삭제
  전부 되돌릴 방법이 없음(요청 1의 전제).
- **`annotation_canvas.py`의 undo는 "매 액션 전에 `_annotations` 전체를 deepcopy해 스택에
  push"하는 구조**(`_push_undo()` L1369-1385, `undo()` L410-419)이고, `Ctrl+Z`는
  `keyPressEvent`에서 `event.matches(QKeySequence.StandardKey.Undo)`로 잡는다(L578-579).
  스택은 30개로 캡(`if len(self._undo_stack) > 30: pop(0)`) — **BUG-014가 지적한 것은
  "브러시 스트로크마다 전체 `_annotations`(대형 이미지+brush_mask 수백 개)를 deepcopy"하는
  구조 자체가 무거워서 캡을 걸어도 메모리 부족이 재현된다는 것**(대형 이미지+많은 마스크
  상태에서). 브러시 드래그는 `mousePressEvent`에서 스트로크 시작 시 **1회만**
  `_push_undo()`를 호출(L644-645)하고, 드래그 중(`mouseMoveEvent`)에는 호출하지 않는다 —
  이 "액션당 1회 push" 원칙은 그대로 재사용할 가치가 있는 패턴.
- **`annotation_canvas.py`의 브러시 스탬프 알고리즘**(`_paint_circle()` L886-909,
  `_paint_stroke()` L858-884)은 원본 이미지 좌표계에 bbox-crop 벡터화 원판 비교
  (`(ys-cy)**2+(xs-cx)**2 <= r**2`)로 브러시 자국을 찍고, 드래그 중 마우스가 빨리 움직여도
  끊기지 않도록 이전 점→현재 점을 반지름의 40% 간격으로 선형보간한다. **지우개
  (`TOOL_ERASER`)는 별도 알고리즘이 아니라 같은 스탬프 결과를 `_apply_eraser()`에서
  "기존 마스크에서 빼기"로 해석할 뿐**(L961-981) — 이번 요청 2(브러시 지우기)에 그대로
  이식 가능한 정확히 필요한 패턴.
- **`zone_metrics.py`의 `_disk_mask()`**(L35-39)가 이미 벡터화 원판 마스크 생성 함수라
  브러시 지우기의 스탬프 연산과 수학적으로 동일 — 새로 만들 필요 없이 공개 함수로 전환해
  재사용(아래 판단 2).
- **`ZoneCanvas`는 이미 `selected_id()`/`highlighted_zone()`/`removed_blob_ids()`/
  `blob_labels()` getter 패턴으로 "캔버스가 상태의 단일 출처, 사이드 패널은 재구축 후
  getter로 복원" 원칙(BUG-018/019 수정 패턴)을 확립해 두었다** — 신규 상태(브러시 지우기
  스트로크, undo 스택)도 이 패턴을 그대로 따르면 재발 방지가 자동으로 보장된다.
- **`circle_detect_preview_dialog.py`/`zone_batch_result_dialog.py`는 `QDialog.exec()`가
  진실값을 반환하면 호출부가 이미 알고 있는 데이터로 다음 동작을 진행하는 패턴**
  (`auto_label_dialog.py` L393-399: `if preview.exec(): ...`)을 그대로 따르면 됨 — 요청 5의
  라운드트립에 그대로 적용 가능.
- **`export_zone_percentages_to_excel(rows, out_path)`는 이미 `(이미지파일명, 존이름,
  퍼센티지)` 범용 rows를 받는 함수**라 요청 3(단일 이미지)은 이 함수를 그대로 재사용, 신규
  함수 불필요.

---

## 확정 요구사항 (사용자 답변 완료 — 재질문 불필요)

1. **Undo** — 여러 단계 스택(라벨링 탭과 동일 개념), `Ctrl+Z` + 클릭 가능한 툴바 버튼 둘 다.
2. **브러시 지우기** — 픽셀 단위로 타겟 마스크를 직접 지우는 신규 도구(지우기 전용, 그리기/
   추가 없음). 기존 "블랍 삭제 모드"와 배타적인 3번째 캔버스 모드.
3. **단일 이미지 Excel 내보내기** — 일괄 처리를 거치지 않은 단일 이미지 결과도 내보낼 수
   있어야 함. 기존 `export_zone_percentages_to_excel()` 재사용.
4. **일괄 처리 결과 wide format 뷰** — `ZoneBatchResultDialog`에 기존 long format과 나란히
   (또는 토글로) wide format(이미지×존 피벗) 뷰 추가.
5. **오프라인 원 검출 팝업 → 메인 탭 라운드트립** — 팝업에서 확정한 원을 메인 탭
   `ZoneCanvas`로 가져오는 버튼.

## 재확인 (기존 확정 사항, 변경 없음)

원 데이터 모델(Circle), 완전 독립 도구 원칙(프로젝트 시스템 미사용), 존 계산 로직(원판
마스크 차집합), 체크포인트→모델 재구성, 타겟 클래스 즉석 구성 — 전부 그대로 유지. R1~R4·
R-A~R-C의 판단(탭 배치, 강건한 원피팅, `raw_class_map`→`class_map` root-cause 수정 등)도
무관해 손대지 않는다.

---

## 판단 1 — Undo: 단일 통합 스택 + 경량 스냅샷(브러시 지우기는 스트로크 좌표로 저장, 마스크
아님)

### 통합 스택 vs 카테고리별 분리 — 통합 스택으로 결정

원 편집(생성/이동/반지름조절/삭제), 블랍 클릭삭제, 브러시 지우기 스트로크 **셋 다 하나의
undo 스택**에 넣는다. 근거:

- **UX**: 사용자는 "방금 한 마지막 작업"을 되돌리고 싶어하지, "원 편집 중 마지막 것"처럼
  카테고리별로 분리해서 되돌리고 싶어하지 않는다 — `annotation_canvas.py`도 폴리곤/브러시/
  선택-이동 등 도구 종류와 무관하게 단일 스택이다.
- **구현 난이도**: 스택을 3개로 나누면 `Ctrl+Z` 한 번에 "어느 스택에서 pop할지" 시간순 판단이
  필요해져(예: 방금 한 게 원 이동인지 블랍 삭제인지) 결국 시간순 통합 로그가 다시 필요하다 —
  처음부터 하나의 통합 스택이 더 단순하고 더 정확하다.
- **메모리**: 아래에서 확인하듯 3가지 상태 전부 경량(원 목록 = 튜플 리스트, 블랍 id = 정수
  집합, 브러시 지우기 = 좌표 리스트)이라 통합해도 부담이 없다 — 분리해서 얻는 메모리 이득
  자체가 없다.

### 스냅샷 내용물 — BUG-014 재발 방지가 핵심

`_push_undo()`가 매 액션 전에 push하는 스냅샷은 다음 4개 필드로 구성한다:

```python
snapshot = {
    "circles": [(c.id, c.cx, c.cy, c.r) for c in self._circles],   # 얕은 튜플 리스트, 원본 몇 개 뿐 — 가벼움
    "removed_blob_ids": set(self._removed_blob_ids),               # 정수 집합, 가벼움
    "erase_strokes": list(self._erase_strokes),                    # 아래 참고 — 좌표 리스트, 마스크 아님
}
```

**`_next_id`는 스냅샷에 포함하지 않는다** — 원 id가 undo 이후 재사용되지 않고 계속 증가하는
것은 무해하며(id는 내부 상관관계 용도일 뿐 사용자에게 노출 안 됨), 스냅샷을 한 줄 더 단순하게
유지한다(ponytail: 굳이 되돌릴 필요 없는 카운터).

**브러시 지우기(요청 2)를 마스크가 아니라 "스트로크 좌표 목록"으로 저장하는 것이 이번 설계의
핵심**:

- `self._erase_strokes: list[list[tuple[float, float, float]]]` — 스트로크(드래그 1회)마다
  그 안에서 찍힌 스탬프들의 `(cx, cy, r)` 목록(원본 이미지 좌표). annotation_canvas의
  `_paint_stroke()`가 이미 "이전 점→현재 점을 반지름의 40% 간격으로 보간"하는 로직을 갖고
  있으므로 그대로 재사용해 스탬프 좌표를 뽑아낸다.
- 지운 영역을 실제로 반영하는 "지우기 마스크"(`self._erase_mask_np: np.ndarray | None`,
  원본 해상도 bool 배열)는 **undo 스택에는 절대 들어가지 않는 파생(derived) 캐시**다 —
  화면 렌더링과 `_current_target_mask()` 계산에만 쓰는 표시용 재료.
- **드래그 중(라이브 페인팅)**: `annotation_canvas._paint_circle()`과 동일한 bbox-crop
  벡터화 스탬프(`self._erase_mask_np[y0:y1, x0:x1] |= circle`)로 O(스탬프 반경²)만큼만
  갱신 — 20MP 이미지에서도 스탬프 1개당 비용이 브러시 크기에만 비례, 이미지 전체 크기와
  무관.
- **undo(되돌리기) 시**: 스냅샷에서 복원한 `erase_strokes`로 `_erase_mask_np`를 처음부터
  다시 그린다(각 스트로크의 각 스탬프를 `disk_mask()`로 OR) — O(스트로크 수 × 이미지 크기)로
  드래그 중보다 훨씬 비싸지만, **undo 클릭은 드문 1회성 사용자 조작**이라 허용 가능(ponytail:
  스트로크가 수백 개로 아주 많아지면 체감 지연이 생길 수 있음 — 필요해지면 bbox 단위 증분
  재계산으로 승격할 여지를 남겨둠, 지금은 과설계 금지).

이 설계로 "여러 단계 스택"이 요구하는 깊이 문제가 근본적으로 해소된다 — `annotation_canvas.py`
처럼 30개 캡을 걸 필요조차 없다(모든 필드가 가벼워 캡이 메모리 보호 목적으로 필요하지 않음).
**결정: 캡 없이 무제한 스택**(라벨링 탭의 30개 캡은 "무거운 걸 억지로 담아서 생긴 메모리
보호책"이었을 뿐 — 이 탭은 애초에 가벼우므로 그 제약이 적용되지 않는다는 점을 스펙에 명시해
향후 혼동 방지).

### push 위치 — "실제 상태 변화가 확정되는 시점 직전"에만

일반 원칙: 각 mutator(원 생성/이동/반지름조절/삭제, 블랍 클릭삭제, 브러시 지우기 스트로크
시작)는 **조기 return(no-op 조건) 이후, 실제로 상태가 바뀌는 코드 줄 바로 직전에** 1회
`_push_undo()`를 호출한다. annotation_canvas의 "액션당 1회 push, 드래그 중엔 push 안 함"
원칙을 그대로 따른다:

- 원 생성/이동/반지름조절: `mousePressEvent`(드래그 시작 시점)에서 1회.
- 원 삭제(`remove_selected()`, Delete 키/우클릭 메뉴): 삭제 직전 1회.
- `set_circles()`(자동 검출 결과 반영, 요청 5의 라운드트립 적용도 이 경로 재사용): 교체
  직전 1회.
- 블랍 클릭삭제(`_handle_blob_click()`): 배경(0)·이미 삭제된 라벨 조기 return **이후**,
  `removed_blob_ids.add()` 직전 1회.
- 브러시 지우기 스트로크: `mousePressEvent`(스트로크 시작)에서 1회(annotation_canvas의
  브러시 push 위치와 동일 타이밍).

**주의 — 기존 "짧은 드래그는 원 생성 취소, 클릭으로 간주해 존 선택 처리" 경로**
(`mouseReleaseEvent` L370-385, `_MIN_CREATE_R_PX` 미만이면 방금 만든 원을 다시 제거)는
`mousePressEvent`에서 이미 push해둔 undo 엔트리가 "결국 아무 일도 없었던" 상태를 가리키게
된다 — 그대로 두면 사용자가 빈 곳을 클릭했을 뿐인데 Undo 스택에 아무 효과 없는 엔트리가
쌓여 "되돌리기 버튼을 눌렀는데 아무것도 안 바뀌는 것처럼 보이는" 사소한 혼란이 생긴다.
**대응**: 이 취소 분기에서 원을 다시 제거할 때 `if self._undo_stack: self._undo_stack.pop()`으로
방금 push해둔 엔트리도 함께 되돌린다(투기적으로 push했다가 no-op로 판명되면 되무름).

### Ctrl+Z + 버튼

- `ZoneCanvas.keyPressEvent()`에 **모드(원편집/블랍삭제/브러시지우기)와 무관하게 가장 먼저**
  `event.matches(QKeySequence.StandardKey.Undo)` 체크를 추가(`QKeySequence`는
  `PyQt6.QtGui`에서 신규 import) — 지금처럼 모드별 분기가 Ctrl+Z보다 먼저 걸려 있으면 블랍
  삭제/브러시 지우기 모드 중에는 단축키가 죽는 회귀가 생기므로 반드시 최상단에 배치.
- `ZoneCanvas`에 공개 API 2개 추가: `undo() -> None`(스택이 비었으면 no-op), `can_undo() ->
  bool`.
- `zone_analysis_tab.py` 툴바에 "실행 취소" 버튼(`QPushButton`) 추가, 클릭 시
  `self._canvas.undo()`. 활성/비활성은 기존 `circles_changed`/`blob_deleted`에 새로
  추가되는 `erase_changed`(판단 2) 3개 시그널에 `lambda: self._btn_undo.setEnabled(self._canvas.can_undo())`를
  연결해 갱신 — 신규 시그널을 추가로 발명하지 않고 이미 있는 갱신 지점에 편승(ponytail).
- `undo()`는 복원 후 **기존 `circles_changed` 시그널을 그대로 재사용해 emit**한다(원/블랍/
  지우기 중 무엇이 바뀌었든 상관없이) — 이미 `circles_changed`가 `_refresh_circle_list()`
  (원 목록 재구성, `selected_id()` getter로 선택 복원)와 `_recompute_zones()`(존 재계산,
  `highlighted_zone()` getter로 하이라이트 복원)와 `_update_batch_button_state()`에 연결돼
  있어 **신규 배선 없이 BUG-018/019 방지 패턴이 undo에도 자동 적용된다**. 원이 안 바뀐 채
  블랍/지우기만 undo된 경우에도 원 목록이 한 번 더 재구성될 뿐(무해, 저비용) — 새 시그널
  종류를 늘리는 것보다 이 쪽이 더 단순하다는 판단.
- `undo()`는 복원 직후 `self._selected_id = None`도 함께 리셋한다(annotation_canvas의
  `undo()`가 `self._selected_ids.clear()`하는 것과 동일한 이유 — 되돌린 상태에 이전 선택이
  더 이상 유효하지 않을 수 있음).

### 타겟 클래스 전환/새 이미지 로드 시 스택 전체 리셋 (데이터 정합성, 단순 정책 아님)

`set_blob_data(labels, stats)`가 호출될 때마다(타겟 클래스 (재)선택마다) `removed_blob_ids`가
초기화되는 기존 규칙이 있다("라벨 id는 마스크에 종속적이라 클래스가 바뀌면 이전 삭제 이력은
무의미"). **이 규칙을 브러시 지우기에도 동일하게 적용**한다 — `erase_strokes`도
`set_blob_data()` 호출 시 함께 비운다(지운 좌표 자체는 클래스 무관이지만, "그 시점 타겟
마스크에서 무엇을 제외했는지"라는 의미는 클래스가 바뀌면 무효화됨).

**추가로, `set_blob_data()`는 undo 스택 전체도 비운다**(`self._undo_stack.clear()`) — 이건
단순한 정책이 아니라 **정합성 문제**다: 클래스 전환 이전 시점의 undo 엔트리를 나중에 복원하면
그 엔트리의 `removed_blob_ids`가 **현재(새 클래스의) `blob_labels`와 대응하지 않는 오래된
라벨 id를 가리키게 되어** 잘못된 픽셀이 제외되거나(우연히 id가 겹치는 경우) 아무 효과가 없는
채로 조용히 남는(id가 범위를 벗어나는 경우) 오류가 생긴다. 원(circle)은 클래스와 무관해
살아남아도 안전하지만, 이 스냅샷 구조에서는 회로 4필드를 통째로 되돌리므로 스택 전체를
같이 비우는 것이 유일한 안전한 선택이다 — **원 편집 undo 이력이 클래스 전환/이미지 전환
경계를 못 넘는다는 트레이드오프는 감수**(사용자가 "방금 한 편집 몇 개를 되돌리고 싶다"는
요구를 만족하는 데는 지장 없음, 클래스를 바꾸기 전 옛날 원 편집까지 고고학적으로 되돌릴
필요는 실사용상 없다고 판단).

---

## 판단 2 — 브러시 지우기 (요청 2): annotation_canvas 브러시 엔진 이식 + 3-way 모드 배타

### 핵심 재사용: 신규 브러시 엔진을 만들지 않는다

`annotation_canvas.py`의 브러시 스탬프(`_paint_circle`/`_paint_stroke`, bbox-crop 벡터화
원판 비교 + 선형보간)를 `ZoneCanvas`에 그대로 이식한다. 차이는 "그리기 후 새 어노테이션
생성"이 아니라 **"찍은 영역을 지우기 마스크에 OR로 누적"**뿐(annotation_canvas의
`TOOL_ERASER`가 이미 "그림→기존 마스크에서 빼기"로 해석하는 것과 개념적으로 동일, 다만 이
탭은 어노테이션 리스트가 아니라 단일 `class_map == target_id` 마스크 하나를 대상으로 한다는
점만 다르다).

### `zone_metrics._disk_mask()` 공개 전환 (라운드 R3-2에서 선행)

`_disk_mask(cx, cy, r, img_shape)`를 `disk_mask()`로 공개(언더스코어 제거)해 `zone_canvas.py`가
import해 쓴다 — 존 마스크 계산과 브러시 지우기 스탬프가 수학적으로 완전히 동일한 연산이므로
신규 함수를 만들 필요가 없다(라더 2단계: 이미 있는 것 재사용). 라이브 드래그 중에는 이
함수(전체 배열 대상) 대신 annotation_canvas 스타일의 bbox-crop 버전을 캔버스 내부 헬퍼로
따로 두고(성능), **undo 복원 시의 전체 재생만** `disk_mask()`를 반복 호출해 재구성한다.

### `ZoneCanvas` 신규 상태/API

```python
self._mode: str = "circle"          # "circle" | "blob_delete" | "brush_erase"
self._erase_strokes: list[list[tuple[float, float, float]]] = []
self._erase_mask_np: np.ndarray | None = None   # 원본 해상도 bool, 파생 캐시(undo에 안 들어감)
self._erase_brush_size = 30         # 원본 이미지 픽셀 단위 지름(annotation_canvas와 동일 관례)
```

- `set_brush_erase_mode(enabled: bool)` — 신규, `set_blob_delete_mode()`와 동일한 얕은
  래퍼(`self._mode = "brush_erase" if enabled else "circle"`).
- `set_blob_delete_mode(enabled: bool)` — 기존 시그니처 유지(하위 호환), 내부적으로
  `self._mode = "blob_delete" if enabled else "circle"`로 리라이트(불리언 플래그
  `_blob_delete_mode`를 없애고 `_mode` 문자열로 통합 — 기존 호출부
  `self._btn_blob_delete.toggled.connect(self._canvas.set_blob_delete_mode)`는 그대로 둬도
  됨, 이름만 유지되는 얕은 래퍼).
- `set_erase_brush_size(size: int)` — annotation_canvas의 `set_brush_size()`와 동일 패턴
  (1~200 clamp 등, 상한은 구현 재량).
- `erase_mask() -> np.ndarray | None` — 지운 영역 getter, `removed_blob_ids()`/
  `blob_labels()`와 동일한 "캔버스가 단일 출처" 패턴.
- `mousePressEvent`/`mouseMoveEvent`/`mouseReleaseEvent`에 `self._mode == "brush_erase"`
  분기 추가(기존 `if self._blob_delete_mode:` 분기와 나란히, `elif self._mode ==
  "brush_erase":`) — press에서 `_push_undo()` + 새 스트로크 리스트 시작 + 첫 스탬프,
  move에서 보간 스탬프 반복(annotation_canvas `_paint_stroke` 로직 이식), release에서
  스트로크를 `self._erase_strokes`에 append.
- **중클릭 팬은 계속 동작해야 한다** — `_blob_delete_mode` 분기가 이미 "좌클릭 외에는
  `super()`로 위임"하는 패턴(L317-323)을 갖고 있으므로 `brush_erase` 분기도 동일하게
  좌클릭만 가로채고 나머지는 `super()`에 위임(R4 블랍삭제모드 검증에서 이미 이 패턴이
  중클릭 팬과 충돌 없음을 실측 확인해둔 전례 재사용).

### 성능 — "지우기 재계산은 스트로크 끝에 1번만" (신규 주의사항)

원 드래그(`mouseMoveEvent`)는 이미 매 이동마다 `circles_changed`를 emit해 `_recompute_zones()`
(numpy 존 재계산)를 매번 트리거하는 기존 구조다 — 원 개수가 적어(보통 2~5개) 지금까지는
문제가 안 됐다. **브러시 지우기는 한 스트로크 안에서 스탬프가 수십~수백 개 찍히므로, 매
스탬프마다(=매 `mouseMoveEvent`마다) 존 재계산을 트리거하면 20MP 이미지에서 눈에 띄게
느려질 위험이 크다.** 대응: 새 시그널 `erase_changed = pyqtSignal()`을 만들어 **스트로크가
끝나는 `mouseReleaseEvent`에서 1회만 emit**한다 — 스탬프 자체(`self.update()`로 화면
리페인트)는 매 이동마다 해도 되지만(Qt 리페인트는 저렴), `_recompute_zones()`를 트리거하는
`erase_changed` emit은 스트로크 종료 시점에만 하도록 명시적으로 분리한다. 라이브 드래그
중에는 `self._erase_mask_np`의 bbox-crop 증분 갱신 + `self.update()`만으로 사용자가 지운
영역이 실시간으로 보이되, 무거운 numpy 존 계산은 스트로크 완료 후 딱 1번만 실행된다.

`zone_analysis_tab.py`는 `self._canvas.erase_changed.connect(self._recompute_zones)`와
`self._canvas.erase_changed.connect(lambda: self._btn_undo.setEnabled(self._canvas.can_undo()))`
를 연결(판단 1의 Undo 버튼 갱신과 동일 편승 패턴).

### `_current_target_mask()` 수정 (기존 함수에 1줄 추가)

```python
def _current_target_mask(self) -> np.ndarray | None:
    ...
    mask = self._last_result.class_map == self._target_class_id
    removed = self._canvas.removed_blob_ids()
    labels = self._canvas.blob_labels()
    if removed and labels is not None:
        mask = mask & ~np.isin(labels, list(removed))
    erase_mask = self._canvas.erase_mask()      # 신규
    if erase_mask is not None:
        mask = mask & ~erase_mask               # 신규
    return mask
```

`_recompute_zones()`가 이 함수를 이미 호출하므로 **존 퍼센티지 즉시 재계산은 추가 배선 없이
자동으로 만족**(요청 2의 "존 퍼센티지가 즉시 재계산돼야 한다" 요구사항).

### 3-way 모드 배타 UX — 기존 체크 가능 버튼 패턴 그대로, 상호 해제만 추가

`QButtonGroup`(exclusive) 같은 새 추상화를 들이지 않는다 — 버튼이 딱 2개(블랍삭제/브러시지우기,
"원편집"은 둘 다 꺼진 기본 상태로 암묵적 표현)뿐이라 서로 상대방을 끄는 2줄짜리 상호배제로
충분하다(라더: 버튼 2개용 새 그룹 위젯은 과함):

```python
def _on_blob_delete_toggled(self, checked: bool) -> None:
    if checked:
        self._btn_brush_erase.setChecked(False)
    self._canvas.set_blob_delete_mode(checked)

def _on_brush_erase_toggled(self, checked: bool) -> None:
    if checked:
        self._btn_blob_delete.setChecked(False)
    self._canvas.set_brush_erase_mode(checked)
```

새 버튼 "브러시 지우기 모드"(체크 가능) + "지우개 크기" `QSpinBox`(1~200px, 기존
`_min_px_spin` 스타일 재사용)를 툴바 2번째 줄, "블랍 삭제 모드" 버튼 옆에 배치(정확한 픽셀
배치는 구현 재량 — 기존 관례 그대로 두 줄 툴바 유지). 두 모드 버튼 모두 활성화 조건은 기존
"블랍 삭제 모드"와 동일(`_on_target_changed()` 성공 후에만 `setEnabled(True)`, 새 이미지
로드 시 `setEnabled(False)` + `setChecked(False)`로 리셋 — `_on_list_image_selected()`의
기존 `self._btn_blob_delete.setChecked(False); setEnabled(False)` 옆에 브러시지우기 버튼도
같은 처리 추가).

---

## 판단 3 — 단일 이미지 Excel 내보내기 (요청 3)

### 공유 헬퍼 추출 — 중복 로직 없이 재사용

현재 `_recompute_zones()`가 `zones_from_circles()` + `zone_stats()`를 호출해 `_zone_list`
문자열만 만들고 구조화된 값은 버린다. 작은 리팩터로 헬퍼를 뽑아 배치 처리(요청 4 코드
경로)와도 자연히 일관되게 한다:

```python
def _compute_zone_percentages(self) -> list[tuple[str, float]]:
    """(존이름, 퍼센티지) 목록 — 원/추론결과/타겟클래스 중 하나라도 없으면 빈 리스트."""
    circles_raw = self._canvas.circles_with_ids()
    if not circles_raw or self._last_result is None or self._target_class_id is None:
        return []
    circles = [Circle(cid, cx, cy, r) for cid, cx, cy, r in circles_raw]
    h, w = self._last_result.raw_class_map.shape
    zones = zones_from_circles(circles, (h, w))
    target_mask = self._current_target_mask()
    return [(z.name, zone_stats(z.mask, target_mask)) for z in zones]
```

`_recompute_zones()`는 이 헬퍼 결과로 `_zone_list`를 채우도록 리팩터(동작 변화 없음, 순수
추출).

### 신규 버튼

우측 패널(`_zone_list` 아래)에 "이 결과 Excel로 내보내기" 버튼 추가:

```python
def _on_export_single(self) -> None:
    rows = self._compute_zone_percentages()
    if not rows or self._image_path is None:
        QMessageBox.information(self, "내보낼 결과 없음", "먼저 원을 정의하고 추론을 실행하세요.")
        return
    path, _ = QFileDialog.getSaveFileName(self, "Excel로 내보내기", "zones.xlsx", "Excel (*.xlsx)")
    if not path:
        return
    excel_rows = [(self._image_path.name, name, pct) for name, pct in rows]
    export_zone_percentages_to_excel(excel_rows, Path(path))
    QMessageBox.information(self, "내보내기 완료", f"{len(excel_rows)}개 행을 내보냈습니다.")
```

**신규 core 함수 불필요** — `export_zone_percentages_to_excel()`(이미 존재)에 이미지 1장짜리
rows를 넘기기만 하면 된다(요청 3 원문 그대로). 파일: `zone_analysis_tab.py`만 수정.

---

## 판단 4 — 일괄 처리 결과 wide format 뷰 (요청 4)

### 핵심 이슈 — 개별 자동검출 모드에서 이미지마다 존 개수가 다를 수 있음

기존 스펙(R-C)이 long format을 택한 이유가 이것이었다. Wide 피벗은 다음 규칙으로 처리한다
(사용자가 위임한 세부사항, 재질문 없이 이 문서에서 확정):

- **행(row) = 고유 이미지 파일명**(rows에 처음 등장한 순서 유지).
- **열(column) = 전체 rows에서 관측된 존 이름의 합집합**, 정렬 순서는 `"중심부"` →
  `"링 N"`(N 오름차순, 정규식으로 숫자 추출해 정렬) → `"바깥쪽"` 순으로 고정(원 개수가
  달라도 자연스러운 중심→외곽 순서 유지).
- **셀 값** = 해당 (이미지, 존이름) 조합이 rows에 있으면 그 퍼센티지, 없으면 빈 문자열(공란)
  — "N/A" 텍스트보다 빈 셀이 Excel/화면 테이블 모두에서 더 자연스럽다고 판단(사소한 재량,
  N/A 문자열로 바꾸는 것도 동등하게 허용, 구현 재량).
- **알려진 한계(문서화, 버그 아님)**: "개별 자동검출" 모드에서 이미지마다 원 개수가 다르면
  "링 1"이 이미지마다 물리적으로 다른 고리를 가리킬 수 있다 — 이는 wide format 자체의
  본질적 한계이며(사용자가 이미 이 트레이드오프를 인지하고 요청), long format이 여전히
  정확한 원본 데이터라는 점을 다이얼로그 안내 문구로 명시(예: 위젯 상단에 작은 안내 라벨).

### `zone_metrics.py`에 순수 함수 추가 (Qt 의존 없음 — core 규칙 준수)

```python
def pivot_wide_format(
    rows: list[tuple[str, str, float]]
) -> tuple[list[str], list[str], dict[tuple[str, str], float]]:
    """(이미지파일명, 존이름, 퍼센티지) long rows -> (이미지목록, 정렬된 존이름 열목록, 값 dict).
    없는 (이미지, 존) 조합은 값 dict에 키가 없음 -> 호출부가 공란/N-A로 렌더링."""
```

UI(`zone_batch_result_dialog.py`)와 Excel 내보내기(아래) 양쪽이 이 함수 하나를 공유해 피벗
로직 중복을 없앤다.

### 다이얼로그 — `QTabWidget`으로 Long/Wide 나란히

새 `QButtonGroup`/토글 버튼 대신 `QTabWidget` 2탭("목록별"/"이미지별") — Qt 표준 위젯으로
두 개의 독립된 `QTableWidget`(컬럼 구조가 완전히 다름)을 나란히 두는 가장 단순한 방법(라더:
동적으로 컬럼을 바꿔치기하는 단일 테이블보다 두 개의 정적 테이블이 버그가 적음). Wide 탭
테이블은 `pivot_wide_format()` 결과로 채운다.

### Excel — 같은 파일에 시트 2개 (long 유지 + wide 추가)

`export_zone_percentages_to_excel()`을 **애디티브로 확장**(시그니처 불변, 기존 호출부
(요청 3의 단일 이미지 내보내기 포함) 전부 아무 변경 없이 자동으로 시트 2개짜리 결과를 얻음):

```python
def export_zone_percentages_to_excel(rows: list[tuple[str, str, float]], out_path: Path) -> None:
    wb = Workbook()
    ws = wb.active; ws.title = "zones"          # 기존 long 시트, 변경 없음
    ...
    ws2 = wb.create_sheet("zones_wide")          # 신규
    images, zone_cols, values = pivot_wide_format(rows)
    ws2.append(["이미지파일명"] + zone_cols)
    for cell in ws2[1]:
        cell.font = Font(bold=True)
    for img in images:
        ws2.append([img] + [round(values[(img, z)], 2) if (img, z) in values else "" for z in zone_cols])
    wb.save(str(out_path))
```

단일 이미지 내보내기(판단 3)도 이 함수를 그대로 쓰므로 자동으로 `zones_wide` 시트를 얻는다
— 1행짜리 wide 시트라 다소 사소하지만 특별취급(`include_wide` 같은 플래그)을 넣는 것보다
함수 하나로 통일하는 편이 더 단순(YAGNI: 굳이 분기를 만들 필요 없음).

---

## 판단 5 — 오프라인 검출 팝업 → 메인 탭 라운드트립 (요청 5)

### 패턴 재사용 — `auto_label_dialog.py`의 "exec() 후 호출부가 결과를 읽는" 방식

`CircleDetectPreviewDialog`는 여전히 `app.core.project`/체크포인트/메인 탭 관련 import를
전혀 하지 않는 **완전 독립 다이얼로그**로 유지한다 — 결과를 되돌려주는 getter만 추가하고,
실제로 메인 탭 상태를 바꾸는 코드는 **호출부(`ZoneAnalysisTab`)에 둔다**(사용자 지시:
"이 기능만 예외적으로 메인 탭 상태를 갱신하는 경로가 된다").

### `CircleDetectPreviewDialog` 변경

- "닫기"/`✕` 버튼은 그대로 `self.close()`(부수효과 없는 단순 닫기, dismiss = 아무 일도 안
  일어남).
- **신규** "메인 탭에 적용" 버튼 추가, `self.accept()`에 연결(`QDialog` 표준 accept 흐름).
- 신규 getter 2개: `result_circles() -> list[tuple[float,float,float]]`(내부적으로
  `self._canvas.get_circles()`), `result_image_size() -> tuple[int, int]`(내부적으로
  `self._orig_size`).

### `ZoneAnalysisTab._on_open_offline_test()` 변경 — `auto_label_dialog.py`와 동일한
`if dialog.exec():` 패턴

```python
def _on_open_offline_test(self) -> None:
    dialog = CircleDetectPreviewDialog(self)
    if dialog.exec():
        circles = dialog.result_circles()
        if circles:
            self._apply_circles_from_popup(circles, *dialog.result_image_size())
```

### 해상도 방어 — 3b(배치 처리)의 비례 스케일 로직 재사용, 방향만 반대

팝업에서 연 이미지와 메인 탭에 로드된 이미지는 **다른 사진**일 수 있다(예: 팝업으로 다른
샘플 이미지를 열어 파라미터를 튜닝한 뒤, 그 결과를 지금 메인 탭에 로드된 실제 검사
대상에 적용하고 싶은 경우 — 완전히 자연스러운 사용 시나리오). "다른 이미지의 원을 가져오는
게 애초에 의미 없다"고 제한하지 않고, **3b가 이미 검증한 "같은 카메라/렌즈/거리, 해상도만
다를 수 있는" 전제를 그대로 적용**해 비례 스케일로 처리한다(스펙 3b: "몇 줄짜리 안전장치...
포함 권장"과 동일한 근거):

```python
def _apply_circles_from_popup(self, circles, pop_w: int, pop_h: int) -> None:
    if self._image_path is None or self._image_size == (0, 0):
        QMessageBox.warning(self, "이미지 없음", "메인 탭에 이미지를 먼저 여세요.")
        return
    ref_w, ref_h = self._image_size
    note = ""
    if pop_w > 0 and pop_h > 0 and (pop_w, pop_h) != (ref_w, ref_h):
        sx, sy = ref_w / pop_w, ref_h / pop_h
        circles = [(cx * sx, cy * sy, r * (sx + sy) / 2) for cx, cy, r in circles]
        note = f" (해상도가 달라 비례 스케일 적용됨: {pop_w}x{pop_h} → {ref_w}x{ref_h})"
    if self._canvas.get_circles():
        reply = QMessageBox.question(
            self, "원 덮어쓰기",
            f"메인 탭에 이미 정의된 원이 있습니다. 팝업에서 가져온 원으로 교체할까요?{note}",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
    self._canvas.set_circles(circles)
```

- **메인 탭에 이미지가 아직 없으면 적용 자체를 막는다**(경고 후 무동작) — 원은 반드시 어떤
  이미지 위에 정의돼야 의미가 있으므로.
- **기존 원이 있으면 확인 팝업으로 덮어쓰기 여부를 묻는다** — 코드베이스에 이미 있는 관례
  (#7 "OK 처리 시 라벨 있으면 확인 팝업", `labeling_tab.py`의 파괴적 동작 전 확인 패턴)를
  그대로 재사용, 사용자의 수동 편집을 실수로 날리지 않도록.
- `set_circles()`는 판단 1(Undo)에서 이미 `_push_undo()`를 호출하도록 설계되므로, 라운드
  순서상 Undo(R3-4)를 먼저 끝내두면 **이 적용 동작도 별도 코드 없이 자동으로 undo 가능**
  해진다(부가 이득, 필수는 아님).

### 완전 독립 회귀 없음 확인 필요

`CircleDetectPreviewDialog`에 새 버튼이 추가되지만 다이얼로그 자체는 여전히 메인 탭 상태를
전혀 읽지 않는다 — "팝업을 열고 아무 것도 적용하지 않고 닫으면 메인 탭 상태가 완전히
그대로"라는 R-A 검증 항목이 이번에도 회귀 없이 유지돼야 한다(적용 버튼을 누르지 않는 한).

---

## 파일 구조 변경 요약

신규 파일 없음 — 기존 5개 파일만 수정한다(전부 재사용/애디티브 확장):

```
app/
├── tabs/
│   └── zone_analysis_tab.py        # 수정 — Undo 버튼+상태갱신, 브러시지우기 툴바(모드버튼+
│                                    #   크기스핀박스)+3-way 배타 배선, _current_target_mask()
│                                    #   에 erase_mask 반영 1줄, _compute_zone_percentages()
│                                    #   헬퍼 추출, 단일 이미지 Excel 내보내기 버튼,
│                                    #   _apply_circles_from_popup()(요청5 라운드트립)
├── widgets/
│   ├── zone_canvas.py              # 수정 — undo 스택(_push_undo/undo/can_undo), 브러시
│   │                                #   지우기 모드(_mode 통합, 스탬프 엔진 이식,
│   │                                #   erase_mask()/erase_changed), Ctrl+Z(keyPressEvent
│   │                                #   최상단), set_blob_data()에 erase_strokes+undo스택
│   │                                #   초기화 추가
│   ├── circle_detect_preview_dialog.py   # 수정 — "메인 탭에 적용" 버튼 +
│   │                                #   result_circles()/result_image_size() getter
│   └── zone_batch_result_dialog.py       # 수정 — QTabWidget(Long/Wide 2탭), Wide 테이블은
│                                    #   zone_metrics.pivot_wide_format() 사용
└── core/
    └── zone_metrics.py             # 수정 — _disk_mask()→disk_mask() 공개 전환,
                                     #   pivot_wide_format() 신규(순수 함수, Qt 의존 없음),
                                     #   export_zone_percentages_to_excel()에 wide 시트 추가
                                     #   (시그니처 불변 — 기존 호출부 전부 무변경으로 혜택)
```

---

## 라운드 분할 제안 (R3-1 ~ R3-5, 기존 R1~R4/R-A~R-C와 번호 겹치지 않게 접두사 부여)

요청 순서(1→5)가 아니라 **의존관계·파일 겹침 기준**으로 재배열. 저리스크·완전 독립 항목을
먼저 끝내 자신감을 쌓고, `zone_canvas.py`를 함께 건드리는 두 무거운 라운드(브러시지우기→
Undo)는 반드시 이 순서로(요청 사항 자체가 명시한 의존관계 — Undo가 브러시 지우기 상태를
포함해야 하므로), 라운드트립(요청5)은 맨 마지막에 둬 Undo의 혜택을 공짜로 받는다.

1. **R3-1 (요청 3, 저리스크, 완전 독립)** — 단일 이미지 Excel 내보내기.
   파일: `zone_analysis_tab.py`. 신규 core 함수 없음.
   검증: 실 GUI로 이미지+체크포인트→추론→원 정의→"내보내기" 클릭→저장된 xlsx가 화면 존
   리스트와 일치. 회귀: 기존 배치 결과창 export 정상.

2. **R3-2 (요청 4, 저리스크, 완전 독립 + `disk_mask` 공개 전환 선행)** — wide format 뷰 +
   Excel 시트 추가. 파일: `zone_metrics.py`(`disk_mask` 공개 전환 — R3-3이 이 공개 함수를
   그대로 가져다 쓰도록 미리 준비, `pivot_wide_format()` 신규, excel 확장),
   `zone_batch_result_dialog.py`(QTabWidget).
   검증: 합성 rows(이미지 3장, 존 개수 2/2/3개 섞은 케이스)로 `pivot_wide_format()`
   self-check(합집합 컬럼·정렬·공란 처리) + 실 GUI 배치 처리 후 Long/Wide 탭 전환 확인 +
   xlsx 재오픈해 `zones`/`zones_wide` 두 시트 값 대조. 회귀: R3-1 export 경로 무변경 확인.

3. **R3-3 (요청 2, 중리스크)** — 브러시 지우기(undo 없이). 파일: `zone_canvas.py`(3-way
   모드, 스탬프 엔진 이식, erase_mask/erase_changed), `zone_analysis_tab.py`(툴바 버튼+
   스핀박스+배타 배선+`_current_target_mask()` 1줄).
   검증: 원 정의+존 계산 후 "브러시 지우기 모드" 토글→드래그로 지우기→존 퍼센티지 즉시
   갱신(numpy 오라클 대조)→모드 버튼 상호배타(블랍삭제↔브러시지우기, 둘 다 끄면 원편집)
   확인→중클릭 팬이 지우기 모드 중에도 동작→대형 이미지 기준 드래그 중 랙 없음(스트로크
   종료 시에만 재계산되는지 실측). 회귀: R1~R4·R-A~R-C 전체 골든패스.

4. **R3-4 (요청 1, 중~고리스크, R3-3 의존)** — Undo 통합(원편집+블랍삭제+브러시지우기,
   Ctrl+Z+버튼). 파일: `zone_canvas.py`(undo 스택+각 mutator에 push_undo 삽입+
   keyPressEvent 최상단 배치+set_blob_data 리셋), `zone_analysis_tab.py`(Undo 버튼+상태갱신).
   검증: 원 추가/이동/반지름조절/삭제·블랍 클릭삭제·브러시 지우기를 섞어 여러 단계 실행→
   Ctrl+Z 반복으로 각 단계가 정확히 역순 복원(오라클 대조: 원 좌표/제거된 블랍/지워진
   영역 전부)→Undo 버튼 클릭도 동일 동작→스택 소진 시 버튼 비활성화→"빈 곳 클릭이 원생성
   취소로 이어지는 경로"에서 no-op 엔트리가 안 남는지→타겟클래스 전환/새 이미지 로드 시
   스택이 리셋되는지(리셋 이전 상태로 못 돌아가는지 확인)→대형 이미지에서 브러시 스트로크
   수십 개 쌓은 뒤 undo 반복 시 메모리/속도 실측. 회귀: R3-3 이하 전체 골든패스, 오프라인
   팝업(`CircleDetectPreviewDialog`)에서도 Ctrl+Z가 부가 혜택으로 동작하는지(회귀 아님,
   보너스 확인).

5. **R3-5 (요청 5, 저~중리스크, R3-4 이후 권장)** — 오프라인 팝업→메인 탭 라운드트립. 파일:
   `circle_detect_preview_dialog.py`("메인 탭에 적용" 버튼+getter 2개),
   `zone_analysis_tab.py`(`_apply_circles_from_popup()`).
   검증: 팝업에서 (a) 메인과 같은 이미지, (b) 다른 이미지·같은 해상도, (c) 다른 이미지·다른
   해상도 3가지로 검출/편집 후 적용→각각 메인 캔버스에 정확히 반영(비례 스케일 케이스는
   좌표 오라클 대조)→메인에 기존 원이 있을 때 확인 다이얼로그 동작(예/아니오 둘 다)→메인에
   이미지가 없을 때 경고 후 무동작→적용 후 Ctrl+Z로 되돌리기 가능(R3-4 통합 확인)→팝업
   자체의 완전 독립성 회귀 없음(적용 버튼 누르지 않고 닫으면 메인 탭 상태 불변, R-A 재확인).

각 라운드는 기존 관례대로 구현 → `python main.py` 실제 구동 검증 → 다음 라운드 순으로
진행한다.

---

## 결정 필요 항목

**이번 라운드는 등록할 항목 없음.** 사용자가 지시문에서 명시적으로 "설계하라"고 위임한
판단(Undo 통합 스택 vs 분리, 브러시 지우기 undo 표현 방식, wide format 컬럼/공란 처리,
라운드트립 해상도 방어 방식)은 전부 이 문서에서 근거와 함께 직접 결정해 명시했다.
`docs/decisions-needed.md`는 갱신하지 않는다(기존 "현재 없음" 상태 유지).

## 향후 확장 후보 (이번 라운드 범위 아님)

- 브러시 지우기 undo 복원 시 전체 재생(O(스트로크 수 × 해상도))이 스트로크가 매우 많아지면
  체감 지연이 생길 수 있음 — 필요해지면 bbox 단위 증분 재계산(스트로크별 영향 영역만
  다시 그리기)으로 승격.
- 브러시 지우기 모드에 커서 위치에 브러시 크기 원 미리보기(annotation_canvas류 커서
  피드백) — 정밀 작업 편의성 향상이지만 이번 요청 범위 아님.
- 오프라인 팝업에 `DetectParams` 필드 단위 고급 파라미터 노출(R-A 스펙의 기존 향후 후보,
  변경 없음).
- wide format 뷰의 "N/A" 문자열 표시 옵션(현재는 공란) — 필요성 제기 시 재검토.

## 리스크 / 주의사항

- **BUG-018/019/020/021/022 패턴 재발 방지 원칙 재확인**: 이번 라운드가 추가하는 모든 신규
  상태(undo 스택, 브러시 지우기 스트로크/마스크)는 예외 없이 "캔버스가 단일 출처, 사이드
  패널은 getter로 복원" 패턴을 따른다(판단 1/2에 명시). 특히 `undo()`가 기존
  `circles_changed` 시그널을 재사용하는 설계는 이미 검증된 복원 경로(`_refresh_circle_list`/
  `_recompute_zones`의 getter 기반 복원)를 그대로 타므로 신규 회귀 표면이 최소화된다.
- **브러시 지우기의 스트로크당 재계산 지연 이슈는 신규 위험**(기존 버그의 재발이 아니라
  이번에 새로 추가되는 기능 특유의 성능 함정) — R3-3 검증에서 반드시 대형 이미지로 실측
  확인해야 한다(위 판단 2 "성능" 절).
- **Undo 스택의 "클래스 전환/이미지 전환 시 전체 리셋" 정책은 데이터 정합성 문제이지 단순
  구현 편의가 아니다** — R3-4 구현 시 이 리셋을 빠뜨리면(예: `set_blob_data()`에 리셋 추가를
  잊으면) 오래된 `removed_blob_ids`가 새 `blob_labels`와 어긋나는 조용한 정확성 버그가 생길
  수 있다(화면에 에러 없이 잘못된 픽셀이 조용히 제외/포함됨) — 반드시 구현+검증 양쪽에서
  명시적으로 확인.
- `zone_canvas.py`는 메인 탭과 오프라인 팝업(`CircleDetectPreviewDialog`) 양쪽이 공유하는
  위젯이다 — R3-3/R3-4 검증은 메인 탭뿐 아니라 **팝업에서도 신규 기능이 오작동하지 않는지**
  (브러시지우기/블랍삭제 버튼이 팝업엔 아예 없으므로 그 모드들이 팝업에서 실수로 활성화될
  경로가 없는지, Ctrl+Z는 팝업에서도 정상 동작하는지) 함께 확인해야 한다.
- `disk_mask()` 공개 전환(R3-2)은 순수 리네임(언더스코어 제거)이라 회귀 위험이 거의 없지만,
  `zone_metrics.py` 내부 다른 호출부(`zones_from_circles`)도 새 이름으로 갱신해야 함을
  구현 시 빠뜨리지 않도록 명시.
