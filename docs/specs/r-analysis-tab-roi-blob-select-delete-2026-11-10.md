# R 분석 탭 — ROI 선택+삭제 / 블랍 선택+삭제 (2026-11-10)

## 배경 / 범위(리더 확정, 재확인 불필요)

사용자 요청 원문: "roi는 선택시 지울 수 있는 기능을 만들어줘. blob을 선택할 수 있는
기능도 만들고 roi도 선택할 수 있게 만들면 좋겟어." 리더가 코드를 조사해 다음으로
재확인·승인 완료:

1. **ROI 선택 + 삭제**: ROI(사각형 1개)를 클릭하면 "선택됨" 상태로 시각 강조되고,
   선택된 상태에서 Delete/Backspace로 ROI를 지운다(지우면 재검출 트리거).
2. **블랍 선택 + 삭제**: Zone 탭의 블랍 삭제(클릭=즉시삭제, 선택 단계 없음)와
   달리, R 탭은 "선택 → 강조 표시 → Delete 키로 삭제" 흐름. ROI/블랍 둘 다 동일한
   "선택 후 삭제" 패턴을 따른다.

영향 파일: `app/widgets/r_roi_canvas.py`(핵심), `app/tabs/r_analysis_tab.py`,
`app/core/r_cell_store.py`(스키마만, 코드 변경 없음), `app/core/i18n.py`(선택,
툴팁 문구만). `app/core/zone_metrics.py`는 `compute_blob_labels()`/
`disk_mask()`/`apply_manual_strokes()` 재사용만(수정 없음).

---

## 핵심 설계 결정

### 1. 모드 체계 — 신규 모드 추가하지 않음(권장안)

**검토한 두 옵션:**
- (A) 신규 `_mode == "blob_select"` 토글 + 전용 툴바 액션 추가.
- (B) 기본 `"roi"` 모드 안에서 클릭 위치로 ROI/블랍/배경을 구분.

**권장: (B).** 근거:
- `_position_overlays()`는 현재 BUG-050/BUG-050 재발/BUG-051 수정으로 "세 클러스터
  최소폭 합만큼 캔버스 최소폭 강제" 공식이 막 안정화된 상태(`r_analysis_tab.py`
  `_build_center_panel()` 주석 2026-11-09)다. `_edit_cluster`에 새 토글 액션을
  추가하면 `minimumSizeHint().width()`가 커져 이 공식 자체는 자동으로 따라가지만
  (하드코딩 수치가 아니라 계산값이라 안전), 폭 예산이 타이트한 상태에서 액션을
  하나 더 늘리는 것 자체가 불필요한 리스크다.
- (B)는 **기존 메커니즘을 그대로 재사용**한다 — 아래 "마우스 상호작용" 절 참고.
  신규 상태/모드 없이 `mouseReleaseEvent`의 "드래그가 너무 작아 ROI 생성 취소"
  분기(이미 존재하는 클릭-vs-드래그 판정)에 블랍 히트테스트를 끼워 넣기만 하면
  된다.
- 트레이드오프(단점): 두 가지 개념(ROI 편집, 블랍 선택)이 한 모드에 묶여
  "매직"처럼 보일 수 있음. 완화책: 툴팁 문구(`r.tool_roi_tip`)에 "블랍 클릭 선택도
  가능"을 짧게 언급.

### 2. ROI 클릭 vs 블랍 클릭 vs 빈 곳 클릭 — 판정 순서

현재 `mousePressEvent`("roi" 모드)의 분기:
```
hit = self._hit_test(pt)          # ROI 테두리/핸들/내부 히트테스트(기존)
if hit is not None:
    kind, handle = hit            # "move" | "resize" — 기존 그대로 드래그 시작
else:
    # 기존: 즉시 새 ROI 생성 시작(0-size rect, "se" 리사이즈로 드래그)
```
**ROI 생성 드래그의 실시간 미리보기(`mouseMoveEvent`에서 자라는 사각형)를 깨면
안 되므로, press 시점 분기는 건드리지 않는다.** 대신 release 시점의 기존
"드래그가 `_MIN_CREATE_PX`보다 작아 취소" 분기(현재 이전 ROI를 undo 스택에서
복원만 하는 코드)에 블랍 히트테스트를 추가한다 — 이 분기에 도달한다는 것 자체가
이미 "드래그가 아니라 단순 클릭이었다"는 뜻이므로 클릭-vs-드래그 판정을 새로
만들 필요가 없다.

```
if screen_w < _MIN_CREATE_PX or screen_h < _MIN_CREATE_PX:
    # (기존) undo 스택에서 이전 ROI 복원
    ...
    # (신규) 단순 클릭이었던 지점(self._press_orig_pt)에 블랍이 있으면 선택,
    # 없으면 전체 선택 해제
    label = self._blob_label_at(self._press_orig_pt)
    if label:
        self._select_blob(label)
    else:
        self._deselect_all()
else:
    self._roi_edges = ...
    self._roi_selected = True          # 신규 — 방금 만든 ROI는 선택 상태로 시작
    self._selected_blob_id = None
    self.set_highlight_rect(None)
```
`self._press_orig_pt`는 현재 `r_roi_canvas.py`에 없는 필드 — `mousePressEvent`
("roi" 모드, `hit is None` 분기 진입 직전)에 1줄 추가해 기록한다
(`zone_canvas.py`의 BUG-032 대응 `_press_orig_pt`와 동일한 용도/이름, 포팅).

ROI 테두리/핸들을 직접 클릭(`hit is not None`)한 경우는 `mousePressEvent`에서
즉시 `self._roi_selected = True; self._selected_blob_id = None;
self.set_highlight_rect(None)`.

이동/리사이즈 드래그가 끝나는 기존 `elif self._drag_mode in ("resize", "move")`
분기는 선택 상태를 바꾸지 않는다(이미 press에서 선택됨 — 드래그 중 계속 선택
상태 유지가 맞는 동작).

**엣지케이스**: ROI 사각형과 떨어진 위치에 있는 블랍 픽셀을 클릭하면 블랍이
선택되고 ROI 재생성 드래그는 일어나지 않는다(의도된 동작 변화 — 사용자가
명시한 "블랍도 선택할 수 있게" 요구사항의 핵심). ROI를 블랍 영역 위에 다시
그리고 싶으면 기존 ROI의 핸들을 직접 드래그하거나, 빈(배경) 픽셀에서 드래그를
시작해 ROI를 넓혀야 한다 — 기존에도 ROI 핸들 드래그가 유일한 정밀 조정
수단이었으므로 실질적 퇴행은 아니다.

### 3. 블랍 데이터 모델 — 라벨 id가 아니라 "삭제 영역 목록"을 영속 데이터로 저장

**Zone 탭과 다르게 가야 하는 이유**: Zone의 `removed_blob_ids`(정수 라벨 id
집합)는 `set_blob_data()`가 호출될 때(타겟 클래스 전환/재추론 — 상대적으로
드문 이벤트)만 전체 리셋되므로 라벨 id 안정성이 깨지지 않는다. R 탭은
`set_detected_mask()`가 **threshold/분모/스펙/자동검출 체크박스 등 설정 변경
전부**에서 호출된다(`_on_settings_changed()` → `_run_and_display_detection()` →
`set_detected_mask()`, `r_analysis_tab.py` 801~812행) — 즉 사용자가 분모 값만
바꿔도 매번 호출된다. 이런 빈도로 라벨맵이 다시 계산되면 정수 라벨 id는
전혀 안정적이지 않다(같은 블랍이 다음 호출에서 다른 id를 받거나, 컨투어
모양이 바뀌면 사라질 수도 있음). Zone의 "라벨 id 집합" 패턴을 그대로 복붙하면
**블랍 1개를 지운 뒤 threshold 슬라이더를 만지는 순간 삭제 이력이 증발**하는
회귀가 생긴다.

**해결**: 삭제를 라벨 id가 아니라 **이미지 좌표계의 바운딩박스 목록**으로
저장한다 — 재검출로 라벨 id가 바뀌어도 이미지 좌표는 불변이므로 안전하다.

```python
self._deleted_blob_regions: list[tuple[float, float, float, float]] = []
# (x, y, w, h) 원본 이미지 좌표 — cv2 stats의 CC_STAT_LEFT/TOP/WIDTH/HEIGHT 그대로.
self._blob_delete_mask: np.ndarray | None = None   # 파생 캐시(bool, 원본 해상도).
```
`_blob_delete_mask`는 `_deleted_blob_regions`를 사각형으로 rasterize한 결과
(`_replay_deleted_blob_regions()`, `_replay_erase_strokes()`와 동일한 "파생
캐시는 undo/직렬화 대상이 아니다" 패턴). **`_deleted_blob_regions`만 진짜
상태**이고 `get_state()`/`set_state()`/`_push_undo()`/세션 JSON에 저장되는 건
이 목록뿐이다.

**정확도 트레이드오프(ponytail, 알려진 한계)**: 바운딩박스 근사이므로, 나중에
**다른** threshold로 재검출했을 때 그 박스 영역 안에 (삭제한 블랍과 무관한) 새
블랍이 생기면 함께 가려진다. 처음 삭제 시점엔 박스 밖 픽셀이 원래 배경(False)
이었으므로 100% 정확하지만, 이후 재검출에서의 "오염" 가능성은 남는다. 실사용에서
문제가 되면(가까운 녹 얼룩들이 자주 겹침) 정확한 픽셀 모양을 저장하는 쪽
(`annotation_store.rle_encode()` 재사용)으로 승격 — 지금은 요청받지 않은 정밀도라
구현하지 않음(YAGNI). Zone 탭의 `_paint_removed_blobs()` 자체도 "정확한 블랍
모양이 아니라 bbox 근사"라고 이미 명시하고 있어(파일 상단 주석), 같은 수준의
근사를 데이터 모델에도 적용하는 것은 기존 관례와 일치한다.

**블랍 라벨맵(`_blob_labels`/`_blob_stats`)은 반대로 영속화하지 않는다** —
`zone_metrics.compute_blob_labels(self._detected_mask & ~self._blob_delete_mask)`
로 매번 다시 계산하는 **완전히 파생된 값**이다(히트테스트/선택 하이라이트
bbox 조회용, 삭제 영역은 미리 빼서 이미 지운 블랍을 다시 선택할 수 없게 한다).
재계산 시점: `set_detected_mask()` 호출 시, 그리고 블랍 삭제가 1건 커밋될 때마다
(삭제로 `_blob_delete_mask`가 바뀌어 라벨이 달라지므로). **오버레이 불투명도
슬라이더 드래그(`set_mask_opacity()`)에서는 재계산하지 않는다** — 현재
`_rebuild_mask_image()`가 opacity 변경 시에도 호출되는데, 블랍 라벨 재계산을
거기에 얹으면 슬라이더 드래그 중 매 프레임 `cv2.connectedComponentsWithStats`를
돌리게 돼 성능이 깨진다. 별도 메서드(`_recompute_blob_labels()`)로 분리해
`set_detected_mask()`/삭제 커밋 지점에서만 명시적으로 호출한다.

### 4. `effective_mask()` 캐시와의 통합

기존 P0 성능 캐시(`_mask_cache_base`/`_mask_cache_n_strokes`/`_mask_cache_result`)
는 `_detected_mask`의 **identity**(`is` 비교)로 유효성을 판단한다. 블랍 삭제가
생기면 "유효 기저 마스크"가 `_detected_mask` 자체가 아니라
`_detected_mask & ~_blob_delete_mask`로 바뀌므로, 이 중간 마스크를 캐시 기준으로
삼아야 한다 — 매번 새 배열을 만들면(`&` 연산은 항상 새 객체) identity 비교가
항상 깨져 기존 증분 캐시가 무력화된다(매 커밋마다 전체 재생, 성능 회귀).

```python
def _base_mask(self) -> np.ndarray | None:
    if self._detected_mask is None:
        return None
    if not self._deleted_blob_regions:
        return self._detected_mask          # 삭제 없음 — 기존 identity 그대로 재사용
    if self._base_mask_cache_key != len(self._deleted_blob_regions):
        self._base_mask_cache = self._detected_mask & ~self._blob_delete_mask
        self._base_mask_cache_key = len(self._deleted_blob_regions)
    return self._base_mask_cache
```
`effective_mask()`의 `self._detected_mask`를 참조하던 세 곳을
`self._base_mask()`로 교체. `_base_mask_cache`/`_base_mask_cache_key`는
`_invalidate_mask_cache()`가 함께 리셋하도록 그 메서드에 편입(새 메서드
추가 없이 통합). 삭제가 하나도 없는 일반적인 경우(대다수 사용자)는
`_detected_mask`가 그대로 반환되므로 **기존 동작/성능에 회귀 없음**.

### 5. 삭제 디스패치(Delete/Backspace)

```python
def keyPressEvent(self, event) -> None:
    if event.key() == Qt.Key.Key_F ...:           # 기존, 변경 없음
        ...
    if event.matches(QKeySequence.StandardKey.Undo):   # 기존, 변경 없음
        ...
    if self._mode == "roi" and event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
        if self._selected_blob_id is not None:
            self._delete_selected_blob()
        elif self._roi_selected and self._roi_edges is not None:
            self.set_roi(None)      # 기존 메서드 — 내부에서 이미 _push_undo() 호출
            self._roi_selected = False
        return
    super().keyPressEvent(event)
```
`self._mode == "roi"` 가드는 브러시/지우개/pan 모드 중 Delete 키 입력이 아무
영향도 주지 않게 한다(Zone 탭 `keyPressEvent`의 `self._mode != "circle"` 가드와
동일 관례). 둘 다 선택 안 됐으면 당연히 무동작(위 분기 자체가 매칭 안 됨).
`_roi_selected`와 `_selected_blob_id`는 상호 배타적으로 유지되므로(선택 시
반대쪽을 항상 `None`/`False`로 리셋) 우선순위 충돌은 실제로 발생하지 않는다 —
`elif`는 방어적 코드일 뿐.

`_delete_selected_blob()`:
```python
def _delete_selected_blob(self) -> None:
    if self._selected_blob_id is None or self._blob_stats is None:
        return
    label = self._selected_blob_id
    if not (0 <= label < len(self._blob_stats)):
        return
    self._push_undo()
    x, y, w, h = (float(v) for v in self._blob_stats[label, :4])
    self._deleted_blob_regions.append((x, y, w, h))
    self._rasterize_deleted_region(x, y, w, h)   # _blob_delete_mask에 OR
    self._invalidate_mask_cache()                 # _base_mask_cache도 함께 리셋
    self._recompute_blob_labels()                 # 이번 삭제 반영한 새 라벨맵
    self._rebuild_mask_image()
    self._selected_blob_id = None
    self.set_highlight_rect(None)
    self.update()
    self.blob_deleted.emit(label)
    self.mask_changed.emit()
```

### 6. 시각 표시

- **선택된 ROI**: `_paint_roi()`에서 펜 색/두께를 `_roi_selected` 여부로 분기 —
  선택 시 `overlay_viewer._COLOR_SELECTED`(255,200,0, 앱 표준 "선택" 색, Zone의
  선택된 원과 동일 계열) + 펜 두께 2→3, 핸들 채움색도 동일 교체. 비선택 시 기존
  `_COLOR_ROI`(amber) 그대로 — Zone의 `color = _COLOR_SELECTED if selected else
  _COLOR_NORMAL` 패턴 그대로 포팅.
- **선택된 블랍**: 신규 렌더링 코드 불필요 — 상속받은
  `OverlayViewer.set_highlight_rect()`(이미 `_COLOR_SELECTED` 테두리 사각형을
  그려줌, `ZoneCanvas.highlight_blob_bbox()`가 쓰는 것과 동일 메커니즘)를 그대로
  호출. `_select_blob(label)`가 `_blob_stats[label]`의 bbox를 픽스맵 좌표로 변환해
  `set_highlight_rect()`에 넘긴다(`ZoneCanvas.highlight_blob_bbox()` 구현 1:1 포팅,
  `_orig_scale()`만 R 쪽 걸 사용).
- **삭제된 블랍**: `ZoneCanvas._paint_removed_blobs()`를 그대로 포팅한
  `_paint_deleted_blob_regions()` — `_deleted_blob_regions`를 순회해 반투명 빨강
  (`QColor(255, 60, 60, 110)`, Zone과 동일 색) bbox를 그린다. `paintEvent()`에서
  `_paint_mask_overlay`/`_paint_strokes` 다음, `_paint_roi` 이전에 호출.

### 7. Undo/세션 저장 범위

| 상태 | `_push_undo`/`get_state`/`set_state` | 세션 JSON(`r_cell_store`) |
|---|---|---|
| `roi` | 포함(기존) | 포함(`_default_image_data`의 `roi_override`로 기존 이미 처리) |
| `manual_strokes` | 포함(기존) | 포함(기존) |
| `erase_strokes` | 포함(기존, 레거시) | 미포함(기존과 동일, 변경 없음) |
| `deleted_blob_regions`(신규) | **포함** | **포함**(신규 키) |
| `_roi_selected`/`_selected_blob_id`(신규) | **미포함**(선택은 undo 대상 아님 — Zone의 `_selected_id`/`_highlighted_zone`도 undo/영속 대상이 아닌 것과 동일 결론) | **미포함**(세션 간 유지 불필요 — 이미지 재방문 시 선택 없이 시작하는 게 자연스러움, Zone도 동일) |

`get_state()`/`set_state()`에 `"removed_blob_regions"` 키 추가(이름은
`blob_deleted_ids` 같은 혼동 유발 네이밍을 피해 Zone의 `removed_blob_ids`와
구분되도록 `removed_blob_regions`로 명명 — 데이터 형태가 다르다는 것을
이름에서부터 드러낸다). `set_state()`는 역호환으로
`state.get("removed_blob_regions", [])`(기존 세션 파일에 이 키가 없을 수 있음).

---

## 영향 파일별 변경 사항

### `app/widgets/r_roi_canvas.py` (핵심)

- **신규 필드**(`__init__`): `_roi_selected: bool = False`,
  `_selected_blob_id: int | None = None`, `_blob_labels: np.ndarray | None = None`,
  `_blob_stats: np.ndarray | None = None`, `_deleted_blob_regions: list[tuple] = []`,
  `_blob_delete_mask: np.ndarray | None = None`, `_base_mask_cache: np.ndarray | None
  = None`, `_base_mask_cache_key: int | None = None`, `_press_orig_pt: QPointF | None`
  (roi 모드용 — 기존엔 없었음, brush 모드의 동명 변수와는 별개 용도이므로
  이름 충돌 없음 재확인 필요).
- **신규 시그널**: `blob_deleted = pyqtSignal(int)` (Zone과 동일 이름/시그니처).
- **신규 메서드**: `_blob_label_at(pt)`, `_select_blob(label)`, `_deselect_all()`,
  `_delete_selected_blob()`, `_recompute_blob_labels()`, `_rasterize_deleted_region(x,y,w,h)`,
  `_replay_deleted_blob_regions()`(undo/set_state 복원용, `_replay_erase_strokes()`와
  동일 패턴), `_base_mask()`, `_paint_deleted_blob_regions(p)`.
- **수정 메서드**: `effective_mask()`(`_detected_mask`→`_base_mask()`),
  `_invalidate_mask_cache()`(base_mask_cache도 리셋), `set_detected_mask()`
  (`_recompute_blob_labels()` 호출 추가, 단 `_deleted_blob_regions`는 리셋하지
  않음 — 설계 결정 3 참고), `mousePressEvent`("roi" 분기에 `_press_orig_pt` 기록
  + hit 성공 시 선택 상태 갱신), `mouseReleaseEvent`("create" 취소 분기에 블랍
  히트테스트/선택 추가, 성공 분기에 `_roi_selected=True` 설정), `keyPressEvent`
  (Delete/Backspace 분기 추가), `get_state()`/`set_state()`(removed_blob_regions
  추가), `paintEvent`(삭제 블랍 렌더링 호출 추가), `_paint_roi()`(선택 시 색/굵기
  분기).
- **self-check(`if __name__ == "__main__"`) 추가 항목**(최소): (1)
  `_select_blob()`/`_deselect_all()` 상태 전환, (2) 삭제 전후 `effective_mask()`
  픽셀 수 감소 확인, (3) 같은 블랍을 삭제한 뒤 다른 threshold로 재검출해도
  (`set_detected_mask()` 재호출) `_deleted_blob_regions`가 살아있는지(설계
  결정 3의 핵심 보장), (4) Delete 키 디스패치 — 블랍 선택 상태에서 Delete →
  블랍만 지워짐(ROI 안 지워짐)/ROI 선택 상태에서 Delete → ROI만 지워짐.

### `app/tabs/r_analysis_tab.py`

- `_default_image_data()`: `"removed_blob_regions": []` 추가.
- `_load_session()`: `img.get("removed_blob_regions", [])`를
  `self._image_data_map[...]`에 포함.
- `_do_save()`: `images.append({...})`에 `"removed_blob_regions":
  d.get("removed_blob_regions", [])` 추가.
- `_load_image()`: `self._canvas.set_state({...})` 호출에
  `"removed_blob_regions": data.get("removed_blob_regions", [])` 추가.
- `_clear_current_image()`: `self._canvas.set_state({...})` 호출에
  `"removed_blob_regions": []` 추가.
- `_on_canvas_edited()`: `data["removed_blob_regions"] =
  state["removed_blob_regions"]` 추가(기존 `data["manual_strokes"] = ...` 옆).
- `_build_center_panel()`: `self._canvas.blob_deleted.connect(self._update_undo_button_state)`
  + `self._canvas.blob_deleted.connect(lambda _id: self._on_canvas_edited())`
  2줄 추가(기존 `erase_changed` 연결 2줄과 동일 패턴).
- **버튼 추가 없음** — 폭 예산(BUG-050/051) 리스크를 피하려고 키보드(Delete/
  Backspace)만 제공(설계 결정 1 참고). 필요 시 후속 요청으로 재논의.
- self-check 블록에 골든 패스 추가(최소): 블랍 선택→Delete→area 감소→
  `_do_save()`→`_load_session()` 왕복 후 `removed_blob_regions` 보존 확인.

### `app/core/r_cell_store.py`

코드 변경 없음(제네릭 passthrough — `cells[*].images[*]`의 임의 키를 그대로
직렬화/역직렬화하므로 `removed_blob_regions` 키 추가는 `r_analysis_tab.py`
쪽에서만 처리하면 자동으로 저장/로드된다, Zone 탭의 `name`/`hidden` 필드가
`zone_recipe_store`/`zone_state_store` 코드 변경 없이 저장됐던 것과 동일한
선례 — 2026-10-29 기획 로그 "정정 1" 참고).

### `app/core/i18n.py` (선택, 저리스크)

`r.tool_roi_tip` ko/en 문구에 신규 동작 짧게 추가(새 키 신설 없이 기존 키
텍스트만 갱신):
- ko: `"ROI 편집(생성/이동/리사이즈) · 클릭해 선택 후 Delete로 삭제, 블랍 클릭도 선택 가능"`
- en: `"Edit ROI (create/move/resize) · click to select, Delete to remove — click a detected blob to select it too"`

---

## 엣지케이스 정리

1. **ROI 없음 상태에서 Delete** — `self._roi_edges is None`이므로 `elif` 조건이
   거짓, 무동작(정상).
2. **블랍 선택 후 재검출(threshold 변경)** — `_selected_blob_id`는 라벨 id라
   재검출로 라벨맵이 바뀌면 의미가 사라진다. `set_detected_mask()` 호출 시
   `_selected_blob_id = None; self.set_highlight_rect(None)`로 반드시 리셋
   (Zone의 `set_blob_data()`가 선택 상태를 리셋하는 것과 동일 결론) — 단
   `_deleted_blob_regions`(진짜 영속 데이터)는 리셋하지 않는다(설계 결정 3).
3. **삭제된 블랍 영역을 브러시로 다시 그리기** — `effective_mask()` 순서는
   "`_base_mask()`(검출+삭제 반영) → `apply_manual_strokes()`"이므로, 그 자리에
   `draw=True` 브러시 스트로크를 찍으면 `apply_manual_strokes()`가 마지막에
   픽셀을 다시 True로 덮어써 되살아난다 — Zone의 "ai_mask 제외 → manual_strokes
   덮어쓰기" 순서와 동일한 기존 수학을 그대로 따른 결과이자, 사용자가 "지운 걸
   다시 그리면 살아나야 한다"고 기대할 법한 직관과도 일치. 별도 처리 불필요.
4. **이미지 전환/셀 전환** — `_load_image()`/`_clear_current_image()`가 이미
   `set_state()`를 거치므로 `removed_blob_regions`도 함께 교체/리셋된다(설계
   결정 7 표 참고). 선택 상태(`_roi_selected`/`_selected_blob_id`)는
   `set_state()` 안에서 명시적으로 `False`/`None` + `set_highlight_rect(None)`로
   리셋(기존 `set_state()`가 `self._drag_mode = None` 등을 리셋하는 블록에
   추가).
5. **Undo로 블랍 삭제를 되돌렸는데 그 사이 threshold가 바뀌어 라벨맵이 이미
   달라진 경우** — 문제 없음: undo가 복원하는 건 `_deleted_blob_regions`(bbox
   목록, 좌표 불변)뿐이고, `_blob_labels`/`_blob_stats`는 `set_state()` 이후
   `_recompute_blob_labels()`로 현재 `_detected_mask` 기준으로 다시 계산되므로
   항상 최신 상태와 일치한다.
6. **ROI 생성 드래그를 블랍 위에서 시작했는데 드래그 거리가 `_MIN_CREATE_PX`를
   살짝 넘겨 "진짜 드래그"로 판정된 경우** — 기존 동작 그대로 ROI가 생성된다
   (블랍 선택 로직은 "취소된 생성"에만 걸려 있으므로 간섭하지 않음). 사용자가
   블랍을 선택하려다 살짝 손이 움직여 의도치 않은 작은 ROI가 생기는 경우는
   `_MIN_CREATE_PX`(화면 6px) 임계값이 이미 작은 흔들림을 걸러주므로 실사용상
   거의 발생하지 않음(기존에도 같은 임계값으로 이 문제를 다뤄온 코드).
7. **같은 이미지에서 블랍 10개를 연속으로 삭제** — 매번 `_recompute_blob_labels()`
   (cv2 connectedComponents)를 다시 돌리므로 O(블랍 삭제 횟수 × 이미지 크기)
   비용이 들지만, 이는 "사용자가 명시적으로 수행한 드문 액션" 1회당 비용이라
   `effective_mask()`의 P0 증분 캐시(브러시 스트로크, 훨씬 고빈도)와는 성격이
   다르다(설계 결정 3에서 명시) — 성능 우려 시 실측 후 재논의.

---

## 검증 체크리스트(검증 에이전트용)

1. ROI 테두리/내부 클릭 → 선택 강조(색/굵기 변화) 표시 확인.
2. 선택된 ROI에서 Delete/Backspace → ROI 사라짐 + 재검출 트리거(마스크
   오버레이 갱신) 확인.
3. 검출된 블랍 클릭(ROI 핸들/내부가 아닌 지점) → 선택 하이라이트(bbox) 표시,
   ROI는 선택 해제됨 확인.
4. 선택된 블랍에서 Delete → 그 블랍만 effective_mask에서 제외(면적 감소,
   `_cell_rollup()` 숫자 갱신) + 빨간 bbox로 "삭제됨" 표시 확인.
5. 블랍 삭제 후 threshold 슬라이더를 움직여도 삭제 이력이 유지되는지(핵심
   회귀 포인트, 설계 결정 3) 확인.
6. 블랍 삭제 후 Ctrl+Z → 블랍 복원(면적 원복) 확인.
7. ROI 삭제 후 Ctrl+Z → ROI 복원 확인.
8. 세션 저장 → 다른 세션 불러오기 → 같은 세션 다시 불러오기 왕복 후 삭제된
   블랍/ROI 상태 보존 확인(JSON 직접 확인 포함, `removed_blob_regions` 키).
9. 브러시 그리기 도구로 삭제된 블랍 영역을 다시 그리면 되살아나는지(엣지케이스
   3) 확인.
10. 빈 캔버스(이미지 없음)/브러시·지우개·pan 모드에서 Delete 키 입력 시
    크래시/예외 없음(무동작) 확인.
11. 좁은 창(BUG-050/051 재점검 폭)에서 기존 3클러스터 레이아웃에 회귀 없음
    (이번 라운드는 새 버튼을 추가하지 않으므로 폭 공식 자체는 불변이어야
    함 — `r_analysis_tab.py` 기존 self-check의 폭 단언들이 그대로 통과하는지
    재확인).
12. 이미지/셀 전환 시 선택 상태(ROI 선택/블랍 선택)가 자동으로 풀리는지(엣지
    케이스 2/4) 확인 — 이전 이미지의 선택이 새 이미지에 잔류하면 안 됨.

---

## 실행 순서 제안(구현+디자인 역할분담)

같은 파일(`r_roi_canvas.py`)에 핵심 로직이 몰려 있어 **단일 구현 에이전트가
순차 진행**을 권장(병렬 분리 시 충돌 위험이 더 큼):

1. `r_roi_canvas.py` 데이터 모델 + 좌표/캐시 로직(설계 결정 3·4) — 순수
   numpy/상태 변경, Qt 이벤트 핸들러 건드리지 않음.
2. `r_roi_canvas.py` 마우스/키보드 이벤트 통합(설계 결정 2·5) — 1 완료 후.
3. `r_roi_canvas.py` 렌더링(설계 결정 6).
4. `r_analysis_tab.py` 배선(세션 필드/시그널 연결) — 1~3 완료 후(캔버스 API가
   먼저 확정돼야 함).
5. `i18n.py` 툴팁 문구(독립, 언제든 가능, 1~4와 병렬 가능).

**디자인 에이전트 역할**: 선택 강조 색/굵기(설계 결정 6)는 이미 앱 표준
`_COLOR_SELECTED`/Zone 선례를 그대로 쓰므로 신규 목업 불필요 — 다만 "선택된
ROI"와 "삭제된 블랍(빨강)"과 "선택된 블랍(노랑 bbox)"이 화면에 동시에 떠도
서로 구분 가능한지(세 가지 시각 상태가 겹쳐 보일 때의 가독성) 실제 구현물로
1차 검토만 요청 — 저리스크라 사전 Artifact 목업은 생략 권장.
