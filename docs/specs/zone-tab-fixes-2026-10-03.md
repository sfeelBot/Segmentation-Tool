# 상/하부 분석(Zone) 탭 실사용 버그/요청 8건 (2026-10-03)

기획 완료. 1~4번은 1차 접수분, 5~8번은 같은 날 기획 진행 중 사용자가 추가 접수한
건. 대상 파일: `app/tabs/zone_analysis_tab.py`, `app/widgets/inference_image_list.py`,
`app/widgets/zone_canvas.py`, `app/core/zone_metrics.py`,
`app/widgets/zone_batch_result_dialog.py`(1~4번 작성 시점엔 `zone_metrics.py`가
"변경 없음"이었으나 5번에서 `Circle`/`scale_circles`/`zones_from_circles`/
`pivot_wide_format` 수정이 필요해졌음 — 아래 각 절 참고). 전부 코드 근거로 원인을
특정했고 결정 대기 등록 대상 없음 — 1번만 재현 전제(실행 도구 미지급, 정적 추적만
수행)로 구현 착수 전 실제 GUI 재현을 권장(GitHub #9/#16 라운드와 동일 패턴, 구현을
막을 만큼 확신이 낮은 것은 아님).

관련 선행 스펙: `docs/specs/zone-tab-redesign-2026-10-01.md`(레시피/배치 설계),
`docs/specs/zone-tab-ui-reconciliation-2026-10-02.md`(삭제 아이콘 도입 경위).

---

## 1. (버그, 최우선) "일괄 적용" 모드가 전체 이미지에 반영 안 됨

### 결론부터
**(3) 실제 로직 버그.** (1) 선택 범위 기본값 문제도, (2) 흐름 안내 부족도 아니다.

### 조사 과정 — 기각한 가설
- **가설 (1) "다중 선택 안 하면 대상이 좁아진다"는 기각.**
  `InferenceImageList.selected_paths()`(`app/widgets/inference_image_list.py:253-271`)는
  이미 "빈 선택(또는 1개 이하) = 목록 전체"관례로 설계돼 있다:
  ```python
  items = self._tree.selectedItems()
  if len(items) <= 1:
      return self.paths()          # 명시적 다중선택 없으면 전체 반환
  ...
  ```
  즉 사용자가 이미지를 따로 다중선택하지 않아도 `_update_batch_button_label()`
  (`zone_analysis_tab.py:1299-1301`)이 버튼에 `"▶ 선택 이미지 일괄 처리 (N장)"`로
  **전체 장수**를 정확히 표시하고, `_on_batch_process()`의 `targets = self._img_list.selected_paths()`
  (1339행)도 전체 목록을 대상으로 잡는다. 이 경로는 올바르게 동작한다.
- **가설 (2) "레시피 적용 후 안내 부족으로 사용자가 배치 버튼을 안 눌렀다"도 근거 약함.**
  배치 버튼은 항상 화면에 보이고(`_update_batch_button_state()`가 원 1개 이상 +
  이미지 2장 이상일 때만 활성화), 라벨이 매번 "N장"으로 갱신되어 몇 장이 처리될지
  사전에 알 수 있다. 사용자가 버튼 자체를 못 찾았을 가능성을 배제할 순 없지만,
  아래 (3)이 **코드로 확정된 실제 버그**이므로 이를 근본 원인으로 특정한다.

### 확정된 근본 원인 (3)
`_on_batch_process()` → `_on_batch_image_inferred()`(1412-1458행)가 배치 대상 각 이미지에
대해 원을 스케일 적용하고 **사이드카(`zstate.save_state()`, 1444행)에는 정확히 저장**하지만,
**`self._results[path] = result`를 저장하지 않는다.** 반면 메인 "▶ 전체 추론 실행" 버튼
경로(`_on_inference_result()`, 845-852행)는 모든 이미지에 대해 이 줄을 실행한다:
```python
def _on_inference_result(self, path, result, done, total) -> None:
    self._results[path] = result      # ← 배치 경로엔 이 줄이 없음
    ...
    if path == self._image_path:
        self._last_result = result
        self._setup_target_classes(result)
```
그런데 이미지 목록에서 다른 이미지를 클릭하면 `_on_list_image_selected()`(631-684행)가
```python
self._last_result = self._results.get(path)   # 643행 — 배치만 거친 이미지는 항상 None
...
if self._last_result is not None:              # 675행
    self._setup_target_classes(self._last_result)   # → 내부에서 _recompute_zones() 호출
```
로 우측 패널을 복원하는데, 배치만 거친 이미지는 `self._results`에 없으므로 `_last_result`가
`None`으로 남고 **`_compute_zone_percentages()`(1061-1074행)가 `self._last_result is None`
가드에 걸려 빈 리스트를 반환** → 우측 "존별 비율" 패널이 비고, `set_blob_data(None, None)`
(667행)도 복원되지 않아 캔버스의 AI 블랍 색상 오버레이도 나타나지 않는다. 원(circle) 자체는
사이드카에서 정상 복원되지만(`cached = zstate.load_state(path)` → `set_state(cached)`,
680-684행), 사용자 눈에는 "방금 일괄 적용했는데 다른 이미지로 가면 존이 안 잡혀 있다 =
현재 이미지만 적용됐다"로 보인다. 정확히 사용자가 보고한 증상과 일치한다.

실제 데이터(Excel/사이드카)는 전부 정상 저장되므로 **데이터 손실은 없음** — 라이브 UI
캐시(`self._results`)와 디스크 저장(`zstate`) 사이의 동기화 누락이 원인이다.

### 수정 설계 (최소 diff)
`_on_batch_image_inferred()`의 `try:` 블록 맨 위에 한 줄만 추가한다:
```python
def _on_batch_image_inferred(self, path: Path, result: InferenceResult,
                             done: int, total: int) -> None:
    try:
        self._results[path] = result   # NEW — _on_inference_result()와 동일하게 캐시해야
                                        # 이미지 전환 시 우측 존 비율 패널이 복원된다.
        h, w = result.raw_class_map.shape
        ...
```
- `path == self._image_path` 분기 추가는 **불필요** — 배치 시작 시점의 "기준 이미지"는
  이미 레시피 적용 전부터 `_last_result`가 세팅돼 있어 이 한 줄만으로 충분하다
  (조건 분기를 추가로 만들면 오히려 다른 이미지의 `_setup_target_classes()`를 잘못된
  시점에 호출할 위험만 생긴다 — 피할 것).
- 메모리 영향: 이미 "▶ 전체 추론 실행"이 목록 전체 이미지에 대해 동일하게
  `self._results`에 전부 캐시하는 기존 동작이 있으므로(828/847행), 이번 수정은 **새로운
  메모리 리스크를 만드는 게 아니라 배치 경로를 기존 메인 경로와 동일한 수준으로
  맞추는 것**이다. 별도 결정 불필요.

### 재현 체크리스트 (구현 전/검증 시 권장)
1. 이미지 2~3장 로드 → 기준 이미지에서 추론 1회 실행(타겟 클래스 확정) → 레시피
   다이얼로그에서 원 설정 → "메인 탭에 적용" → 레시피 적용 결과가 기준 이미지
   캔버스에만 반영됨 확인(의도된 동작, 버그 아님).
2. "▶ 선택 이미지 일괄 처리 (N장)" 클릭 → 진행 완료 후 **수정 전**: 다른 이미지로
   전환 시 우측 "존별 비율" 패널이 비어 있음(버그 재현) / 사이드카
   `data/zone_state/*.json`(또는 실제 저장 경로)에는 원·존 정보가 정상 저장돼 있음
   (Excel 내보내기로도 확인 가능)을 대조 확인.
3. 수정 후: 다른 이미지로 전환해도 우측 패널에 존 비율 + 캔버스 AI 블랍 오버레이가
   즉시 복원되는지 확인.

---

## 2. 이미지 목록 상시 삭제(×) 아이콘 되돌리기

### 현재 상태 (2026-10-02 UI 조정분)
`app/widgets/inference_image_list.py`:
- 생성자(147-163행)에서 `QTreeWidget`을 2컬럼으로 만들고 컬럼1을 20px 고정폭으로
  예약:
  ```python
  self._tree.setColumnCount(2)
  self._tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
  self._tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
  self._tree.header().resizeSection(1, 20)
  ```
- `_attach_delete_icon()`(423-430행)이 각 리프 아이템 생성 직후 컬럼1에 "×" `QLabel`을
  `setItemWidget()`으로 붙임 — 호출부 4곳: `_build_nested_tree()`(479행),
  `_build_flat_group_tree()`(492/504행), `_apply_display()`(545행).
- 삭제 자체는 이미 `_remove_paths()`(310-319행, 원본 파일은 건드리지 않고 목록에서만
  제거)로 공용화돼 있어, 아이콘 클릭도 이 공용 함수를 호출할 뿐이다.

### 유지해야 할 것 (사용자가 요청하지 않은 부분)
- **우클릭 컨텍스트 메뉴 "목록에서 제거"**: `_on_context_menu()`(321-328행)에 이미
  구현돼 있고 `_remove_selected()`를 그대로 호출 — **그대로 둔다**(수정 불필요).
- **Delete/Backspace 키 단축키**: `eventFilter()`(294-299행)에 이미 구현돼 있고
  동일하게 `_remove_selected()` 호출 — **그대로 둔다**.
- 두 경로 모두 `_attach_delete_icon()`/컬럼1과 무관하게 독립적으로 동작하므로,
  아이콘만 제거해도 삭제 기능 자체는 전혀 손상되지 않는다.

### 수정 설계
1. 생성자: `setColumnCount(2)` → `setColumnCount(1)`로 되돌리고, 컬럼1 관련
   `setSectionResizeMode(1, ...)`/`resizeSection(1, 20)` 2줄 삭제. 컬럼0은 이미
   `Stretch`라 1컬럼 환경에서도 그대로 전체 폭을 차지한다(추가 수정 불필요).
2. `_attach_delete_icon()` 메서드 자체(423-430행)와 호출부 4곳(479/492/504/545행)을
   전부 제거.
3. 그 외 로직 변경 없음 — `_remove_paths()`/`_on_context_menu()`/`eventFilter()`/
   `_remove_selected()`는 전혀 손대지 않는다.

### 영향 범위
`InferenceImageList`는 추론 탭과 상/하부 분석 탭이 공유하는 위젯(생성자 주석·로드맵
"라운드 D" 기록 확인) — 이번 되돌리기는 양쪽 모두에 적용되며, 변경 자체가 "추가 제거"가
아니라 "열 구성 원복"이라 추론 탭 쪽 회귀 리스크도 낮다(구현 완료 후 양쪽 다
`python main.py`로 목록 폭/우클릭 삭제/Delete키 확인 권장).

---

## 3. 추론 실행 진행 팝업에 %/예상시간 없음

### 조사 결과 — 사용자가 말하는 경로는 (a) 메인 "▶ 전체 추론 실행"
`zone_analysis_tab.py`에는 진행 표시 경로가 2개다:
- **(a) `_on_run()`**(799행) → `self._infer_progress`(`QProgressBar`, 243-246행,
  `setFixedWidth(110)`) — `_on_inference_result()`(845-852행)가
  `setFormat(f"{done} / {total}")`만 호출. **퍼센트도 ETA도 없음.**
- **(b) `_on_batch_process()`**(1316행) → `QProgressDialog` + `QElapsedTimer`
  (`self._batch_elapsed`, 1373행) — `_on_batch_progress()`(1386-1410행)가 이미
  평균 처리시간 기반 ETA 텍스트(`예상 남은 시간: 약 N분 N초`)를 계산해 라벨에
  표시 중(2026-10-02 UI 조정 라운드에서 추가 완료, 회귀 아님).

즉 **(b)는 이미 완전히 구현돼 있고, 사용자가 말하는 "팝업으로 % · 남은시간 안 보임"은
(a)를 가리키는 것으로 판단한다** — (a)는 인라인 `QProgressBar`(모달 아님, 포맷도
"3 / 10"뿐)라 사용자 기대(퍼센트+예상시간)에 애초에 못 미치는 설계였다. (b)에서 이미
구현된 로직을 재사용해 (a)도 맞추는 것이 이번 수정 범위다.

### 수정 설계 (과설계 주의 — 모달로 바꾸지 않는다)
스펙 문서(`zone-tab-redesign-2026-10-01.md`)가 "단일 경로는 인라인 바로 충분, 모달
불필요"로 이미 판단해 놓은 기존 설계 의도를 존중 — (a)를 모달로 바꾸지 않고, **인라인
바에 %+ETA 텍스트만 추가**하는 가벼운 방식을 기본안으로 제안한다.

1. `_on_run()`(799행)에 배치 경로와 동일한 패턴으로 엘랩스드 타이머 추가:
   ```python
   self._infer_elapsed = QElapsedTimer()
   self._infer_elapsed.start()
   ```
   (워커 `.start()` 직전, 834행 부근)
2. `_on_inference_result()`(845-852행)에서 ETA 계산 후 포맷 갱신:
   ```python
   def _on_inference_result(self, path, result, done, total) -> None:
       self._results[path] = result
       self._infer_progress.setValue(done)
       eta_txt = ""
       if done > 0:
           avg_ms = self._infer_elapsed.elapsed() / done
           remain_s = max(0, avg_ms * (total - done) / 1000.0)
           m, s = divmod(int(remain_s), 60)
           eta_txt = f" · {m}분{s}초" if m else f" · {s}초"
       self._infer_progress.setFormat(f"{done}/{total} (%p%){eta_txt}")
       ...
   ```
   (`%p%`는 Qt가 `(value-min)/(max-min)*100`으로 자동 계산 — 범위가 "장수" 단위라도
   퍼센트 계산엔 문제없다. `_on_batch_progress()`의 ETA 계산식·분기(60초 미만이면
   분 생략)와 동일 패턴 재사용, 신규 로직 없음.)

### 디자인 확인 필요 — 폭 제약 (리더가 디자인 에이전트에 확인 요청)
`self._infer_progress`는 현재 `setFixedWidth(110)`이고, 같은 줄(`toolbar_row1`)에
체크포인트 버튼·상태점·라벨·배지·"타겟(녹) 클래스:" 라벨·콤보박스가 이미 빽빽하게
들어차 있다(227-254행). `"7/10 (70%) · 12초"` 같은 텍스트는 110px에 들어가기 빠듯하다.
**과설계를 피하기 위한 기본 제안**: 폭은 그대로 두고 퍼센트까지만 바 텍스트로
표시(`f"{done}/{total} (%p%)"`, 대략 폭 안에 들어감)하고, **ETA는
`self._infer_progress.setToolTip(eta_txt)`로 호버 텍스트에 넣는다** — 레이아웃
변경 없이 요구사항(%는 상시 가시, 예상시간은 확인 가능)을 충족하는 가장 작은 diff.
다만 "항상 보여야 한다"는 사용자 기대와 어긋날 수 있어, 디자인 에이전트가 판단해
필요하면 (대안) 바 폭을 약 180~220px로 넓히고 옆 위젯 간격을 줄이는 쪽으로 대신
갈 수 있음을 기록해 둔다 — 이번 라운드는 둘 중 하나를 디자인/구현 단계에서
확정하면 됨(둘 다 저리스크, 결정 대기 등록 대상 아님).

---

## 4. 우측 존별 비율 패널에 최대 blob 픽셀수 추가

### 현재 상태
`_make_zone_row_widget(zone_name, pct)`(1092-1118행)이 존 이름+퍼센티지+색상바만
렌더링. `_recompute_zones()`(1120행~)이 `_compute_zone_percentages()`만 호출해
`(zone_name, pct)` 목록을 넘긴다. 최대 blob 픽셀수를 계산하는 함수
`zone_metrics.max_blob_pixels_by_zone()`(240-249행)은 이미 Excel 내보내기
(`export_zone_percentages_to_excel()`, 273행)에서 쓰이고 있고, 단일 이미지용 blob
목록은 `_compute_zone_blob_rows()`(1076-1090행, 기존 R3-1 단일 이미지 Excel
내보내기용으로 이미 존재)를 그대로 재사용 가능 — **신규 core 함수 불필요.**

### 수정 설계
1. `app/tabs/zone_analysis_tab.py` 상단 import에 `max_blob_pixels_by_zone` 추가
   (49-52행, 기존 `from app.core.zone_metrics import (...)` 블록에 한 항목만 추가).
2. `_recompute_zones()`에서 `pct_rows` 계산 직후 blob 최대값도 함께 계산:
   ```python
   pct_rows = self._compute_zone_percentages()
   blob_rows = self._compute_zone_blob_rows()          # 기존 함수 재사용
   max_blobs = max_blob_pixels_by_zone(blob_rows) if blob_rows else {}
   image_name = self._image_path.name if self._image_path else ""
   ...
   for zone_name, pct in pct_rows:
       max_px = max_blobs.get((image_name, zone_name), 0)
       ...self._make_zone_row_widget(zone_name, pct, max_px)...
   ```
3. `_make_zone_row_widget(zone_name, pct, max_px)`에 세 번째 줄 추가(기존
   이름+퍼센티지 `QHBoxLayout` "top" 아래, 색상바 위 또는 아래):
   ```python
   lbl_max = QLabel(f"최대 blob {max_px:,}px")
   lbl_max.setStyleSheet("color:#9ca3af;font-size:10px;")
   v.addWidget(lbl_max)
   ```
4. **행 높이 조정 필수**: `_recompute_zones()`(1136행)의
   `item.setSizeHint(QSize(0, 40))`를 텍스트 한 줄이 늘어난 만큼
   `QSize(0, 56)`(가이드값, 실측 후 디자인이 최종 조정) 정도로 키워야 새 줄이
   잘리지 않는다. **디자인 에이전트가 레이아웃 패딩과 함께 최종 수치 확인 필요**
   (비주얼 조정 범주, 2026-10-02 라운드와 동일 성격).

### 성능 메모
`_recompute_zones()`는 `circles_committed`(드래그 릴리즈)와 `erase_changed`에만
연결돼 있어(542/555행) 드래그 도중 매 mouseMoveEvent마다 호출되지 않는다(해당
오해는 주석에 더 오래된 `circles_changed` 관련 설명이 남아있어 생긴 것일 뿐, 실제
연결은 `circles_committed`). `zone_blob_stats()`(connectedComponentsWithStats
1회)는 이미 "단일 이미지 Excel 내보내기" 버튼에서 동일 비용으로 호출되는 함수라,
이번 변경으로 새로운 성능 리스크가 생기지 않는다.

### "등등"(추가 지표) 처리
사용자 원문이 "비율뿐만 아니라 최대 pixel개수 등등도"로 구체 지표를 다 나열하지
않았다 — 이번 라운드는 **퍼센티지 + 최대 blob 픽셀수 2개**로 스코프를 확정하고,
`docs/decisions-needed.md`에 "추가로 필요한 지표가 있으면 알려달라"는 참고 기록만
남긴다(결정 대기 항목 아님, 차단 사유 아님).

---

## 5. 레시피 등록 시 존별 이름 사용자 지정

### 현재 상태
`Zone.name`(`app/core/zone_metrics.py:29-31`)은 `zones_from_circles()`가 반지름
오름차순 위치만 보고 자동 생성한다(0=중심부, 1..N-1=링 N, 마지막=바깥쪽) — 사용자
지정 이름이 들어갈 필드 자체가 어디에도 없다. 원 데이터는 `zone_canvas.py`의
`_CircleItem(id, cx, cy, r)`부터 `get_circles()`/`circles_with_ids()`/`get_state()`/
`zone_recipe_store`/`zone_state_store` 사이드카까지 전부 `(cx, cy, r)` 또는
`(id, cx, cy, r)` 고정 길이 튜플로만 흐른다.

### 설계 — 데이터 모델 (최소 diff, 기존 스키마 전부 호환)
**핵심 관찰 1**: `zone_recipe_store.py`/`zone_state_store.py` 둘 다 이미 **완전히
스키마 비의존적**이다 — `save_recipe()`는 `[list(c) for c in circles]`, `load_recipe()`는
`[tuple(c) for c in payload["circles"]]`로 튜플 길이를 전혀 가정하지 않고 그대로
왕복시킨다(`zone_state_store.py`도 동일, `state["circles"]`를 그대로 JSON에 싣는다).
**따라서 이 두 저장소 파일은 단 한 줄도 바꿀 필요가 없다** — 튜플에 4번째 원소
(`name`)를 추가해도 자동으로 저장/복원된다. 기존에 저장된 3요소/4요소(이름 없음)
레시피·사이드카도 그대로 로드된다(아래 "역호환"이 unpacking 쪽에서 흡수).

**핵심 관찰 2**: `app/widgets/zone_canvas.py`의 원 편집 컨텍스트 메뉴
(`contextMenuEvent()`, 847-865행)에 이미 "지름 변경..." 액션 +
`_prompt_diameter_change()`(`QInputDialog.getDouble()`)가 있다 — 이름 변경도
**같은 메뉴에 "이름 변경..." 액션 하나만 추가**(`QInputDialog.getText()`)하면
된다. 이 캔버스는 메인 탭과 `ZoneRecipeDialog` 양쪽에 **동일하게 임베딩**되므로
(`zone_recipe_dialog.py:67` `self._canvas = ZoneCanvas()`), **이 한 곳만 고치면
레시피 등록 화면과 메인 탭 양쪽에서 즉시 이름 변경이 가능해진다** — 다이얼로그
전용 리스트 위젯을 새로 만들 필요가 없다(애초에 검토했던 "다이얼로그에
`QLineEdit`/리스트 패널 추가" 안보다 훨씬 작은 diff).

구체 변경:
1. `app/widgets/zone_canvas.py` `_CircleItem`(66-70행)에 `name: str | None = None`
   필드 추가(기존 전부 위치인자 생성이라 하위호환).
2. `contextMenuEvent()`에 "이름 변경..." 액션 + `_prompt_name_change()` 신설
   (`_prompt_diameter_change()`와 동일 패턴 — `_push_undo()` → 값 반영 →
   `circles_changed`/`circles_committed` emit):
   ```python
   def _prompt_name_change(self, circle_id: int) -> None:
       item = self._find(circle_id)
       if item is None:
           return
       text, ok = QInputDialog.getText(
           self, "이름 변경", "존 이름(비우면 자동 이름 사용):", text=item.name or "",
       )
       if not ok:
           return
       self._push_undo()
       item.name = text.strip() or None
       self.update()
       self.circles_changed.emit()
       self.circles_committed.emit()
   ```
3. `get_circles()`(156-158행)·`circles_with_ids()`(160-162행)·`get_state()`/
   `_push_undo()`(416/438행) — 전부 반환 튜플에 `c.name` 추가
   (`(cx,cy,r,name)`/`(id,cx,cy,r,name)`). `set_circles()`(143-154행)·
   `set_state()`(444-450행) — 입력 튜플을 `cx, cy, r, *rest = c` 식으로 풀어
   `name = rest[0] if rest else None`로 **역호환**(3요소/4요소 기존 호출부 전부
   그대로 동작, 레시피 적용 시에만 4번째 원소로 이름이 들어온다).
4. `app/core/zone_metrics.py` `Circle`(21-25행)에 `name: str | None = None`
   추가. `scale_circles()`(46-61행)를 `*rest` 통과 방식으로 일반화:
   ```python
   return [(cx * sx, cy * sy, r * (sx + sy) / 2, *rest) for cx, cy, r, *rest in circles]
   ```
   (좌표만 스케일, 이름은 그대로 통과 — 기존 3요소 호출부도 그대로 동작.)
5. `zones_from_circles()`(64-79행) — 정렬된 원에 이름이 있으면 그 이름을 쓰고,
   없으면 기존 자동 생성 이름을 쓴다:
   ```python
   zones = [Zone(0, sorted_c[0].name or "중심부", masks[0])]
   for i in range(n - 1):
       zones.append(Zone(i + 1, sorted_c[i + 1].name or f"링 {i + 1}", masks[i + 1] & ~masks[i]))
   zones.append(Zone(n, "바깥쪽", ~masks[-1]))
   ```
   **범위 결정(의도적 축소, YAGNI)**: "바깥쪽" 존은 특정 원에 귀속되지 않는
   영역(가장 큰 원 밖 전부)이라 이름 커스터마이즈 대상에서 제외한다 — 억지로
   "가장 큰 원의 이름"을 "바깥쪽" 대신 쓰게 하면 오히려 "이 원 안쪽 이름"이라는
   직관과 어긋난다(아래 `zone_name_sort_key` 영향 분석 참고).
6. `app/tabs/zone_analysis_tab.py` — `circles_with_ids()`가 5요소가 되므로
   호출부 4곳 전부 `name`까지 풀어쓰도록 갱신: `_compute_zone_percentages()`
   (1067-1074행)·`_compute_zone_blob_rows()`(1076-1090행)의
   `Circle(cid, cx, cy, r)` → `Circle(cid, cx, cy, r, name)`, `_refresh_circle_list()`
   (1253-1270행)의 표시 텍스트에 이름이 있으면 보여주기(`f"{name}  r=...`).
   `_on_batch_image_inferred()`(1412-1458행)의 `scale_circles`/zstate 저장/
   `zones_from_circles` 호출 3곳도 `*rest` 패턴으로 이름을 통과시킨다(아래
   실측 흐름 참고). `_on_batch_process()`의 `circles_ref = self._canvas.get_circles()`
   (1325행)는 **코드 변경 없이** 자동으로 이름까지 포함된 4-튜플을 넘기게 된다
   (2번 변경의 결과).

### 배치(일괄 적용) 경로로의 전파 확인
`_on_open_recipe_dialog()`(1231-1249행)의 `self._canvas.set_circles(scaled)`가
이름 포함 4-튜플을 받아 메인 탭 캔버스에 즉시 반영 → `_on_batch_process()`가
`circles_ref`(이름 포함)를 `self._batch_circles_ref`로 보관 → `_on_batch_image_inferred()`의
`scale_circles(self._batch_circles_ref, ...)`가 이름을 보존한 채 각 대상 이미지
크기로 스케일 → `zstate.save_state()`가 그대로 저장(스키마 비의존, 수정 불필요) →
다른 이미지로 전환해 `zstate.load_state()`→`set_state()`로 복원해도 이름이
그대로 돌아온다. **1번 버그 수정(배치 결과 캐시)과 결합하면, 배치 처리 후 아무
이미지로 전환해도 우측 존 비율 패널에 커스텀 이름이 즉시 보인다** — 신규 코드
없이 1번 수정 + 이번 데이터 모델 확장만으로 자동 충족.

### 필수 동반 수정 — Excel/필터 바 정렬 안정성
`zone_name_sort_key()`(201-213행)는 리터럴 "중심부"/"바깥쪽" 문자열과 "링 N"의
숫자만으로 정렬 버킷을 판정한다. 이름을 커스터마이즈하면:
- **알려진 한계(의도적으로 받아들임, YAGNI)**: 중심부/바깥쪽 존을 커스텀 이름으로
  바꾸면 그 이름이 "링" 버킷으로 오분류돼 Wide 탭/Excel 열 순서·필터 바 버튼
  순서에서 중심/바깥쪽이 맨 좌/우가 아니라 링들 사이에 낄 수 있다. **데이터
  정확성에는 전혀 영향 없음**(값은 항상 올바름, 열 순서만 미관상 어긋날 수
  있음). `Zone.index`를 행 튜플까지 끌고 가는 완전한 구조적 정렬(여러 파일 추가
  변경 필요)은 지금 요청 범위를 넘어서는 과설계로 판단해 하지 않는다 — 실사용에서
  불편하면 후속 라운드로 분리.
- **반드시 고쳐야 할 실제 버그(이번에 포함)**: `pivot_wide_format()`(236행)과
  `zone_batch_result_dialog.py`의 필터 바(93행) 둘 다 `set()`으로 모은 이름을
  정렬 입력으로 쓰는데, CPython의 `set` 반복 순서는 문자열 해시 랜덤화 영향을
  받아 **같은 정렬 버킷 안에서 동점 처리 순서가 실행마다 달라질 수 있다**(숨어있던
  비결정성 — 이름이 전부 디폴트일 땐 버킷이 전부 달라 드러나지 않았지만, 커스텀
  이름 2개 이상이 같은 버킷에 들어가면 바로 드러난다). 수정은 `set` → 첫 등장 순서
  보존 컨테이너로 교체, 정렬 자체(`zone_name_sort_key`)는 그대로 사용(안정 정렬이라
  동점만 결정적이 됨, 디폴트 케이스 회귀 없음):
  ```python
  # zone_metrics.py pivot_wide_format() 내부
  zone_names: dict[str, None] = {}   # set() 대신 — 첫 등장 순서 보존(동점 결정성)
  ...
  zone_names[zone_name] = None        # .add() 대신
  ...
  zone_cols = sorted(zone_names, key=zone_name_sort_key)   # dict는 키 순서로 반복, 변경 없음

  # zone_batch_result_dialog.py _build_filter_bar() 내부
  zone_names = sorted(dict.fromkeys(zone for _, zone, _ in rows), key=zone_name_sort_key)
  ```
  기존 self-test(`zone_metrics.py` 361-372행, "존 개수 2/2/3개 섞은 케이스")는
  버킷이 전부 다른 케이스라 이 변경으로 결과가 바뀌지 않음(검증 시 그대로 통과
  확인할 것).

### self-check 보강
`zone_metrics.py` self-check(`if __name__ == "__main__":`, 312행~)에 이름
오버라이드 검증 추가 권장:
```python
circles3 = [Circle(1, 2, 2, 1, "상부")]
zones3 = zones_from_circles(circles3, shape)
assert zones3[0].name == "상부"
assert zones3[1].name == "바깥쪽"   # 바깥쪽은 커스터마이즈 범위 밖(의도된 설계)
```

---

## 6. 원 지름 조절을 Alt+휠로, 기본 휠은 항상 줌으로

### 현재 상태 — 조건이 뒤집혀 있음
`zone_canvas.py` `wheelEvent()`(831-845행):
```python
def wheelEvent(self, event) -> None:
    if self._mode == "circle" and self._selected_id is not None:
        item = self._find(self._selected_id)
        if item is not None:
            ...
            event.accept()
            return
    super().wheelEvent(event)   # 선택된 원이 없으면 기존처럼 화면 줌
```
원이 선택돼 있으면 **항상** 반지름 조절로 가로채 `super().wheelEvent()`(줌)로
넘어가지 않는다 — 원 선택 중엔 휠로 줌을 할 수 없는 상태.

### 수정
조건에 `Qt.KeyboardModifier.AltModifier` 체크를 추가해 뒤집는다(Shift 큰걸음
로직은 그대로 유지하되 Alt와 함께일 때만 의미를 가짐):
```python
def wheelEvent(self, event) -> None:
    if (self._mode == "circle" and self._selected_id is not None
            and event.modifiers() & Qt.KeyboardModifier.AltModifier):
        item = self._find(self._selected_id)
        if item is not None:
            self._begin_edit_gesture()
            step = (_WHEEL_STEP_PX_SHIFT if event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                    else _WHEEL_STEP_PX)
            delta = step if event.angleDelta().y() > 0 else -step
            item.r = max(0.0, item.r + delta)
            self.update()
            self.circles_changed.emit()
            self.circles_committed.emit()
            event.accept()
            return
    super().wheelEvent(event)   # Alt 없으면(원 선택 여부 무관) 항상 화면 줌
```
결과: Alt+휠=보통 조절, Alt+Shift+휠=큰 걸음 조절, Alt 없는 휠(Shift 단독 포함)=
항상 줌. `keyPressEvent()`의 방향키 이동(810-828행)은 이번 요청 범위 밖이라
변경하지 않는다(휠만 해당, 방향키는 원래도 Shift로 큰걸음 이동이지 줌과 충돌이
없었음).

### 안내 표시 — 상시 캡션(구현 비용 최소)
"원이 선택됐을 때만" 조건부 표시보다 **상시 노출 캡션 1줄**이 더 싸고 발견성도
높다 — 캔버스 상단 툴바 영역에 이미 있는 저채도 캡션 관례(`_lbl_batch_condition`
`color:#9ca3af;font-size:11px`, 레시피 다이얼로그 `footer_caption`
`color:#6b7280;font-size:10px`)를 그대로 재사용. 위치: 캔버스 헤더
(`toolbar_header_layout`, 467-476행) — `_edit_toolbar` 다음, `addStretch()` 전에
삽입:
```python
self._lbl_wheel_hint = QLabel("원 선택 후 휠: 줌 · Alt+휠: 지름 조절")
self._lbl_wheel_hint.setStyleSheet("color:#9ca3af;font-size:10.5px;")
toolbar_header_layout.addWidget(self._edit_toolbar)
toolbar_header_layout.addWidget(self._lbl_wheel_hint)   # NEW
toolbar_header_layout.addStretch()
```
신규 QLabel 1개, 조건부 표시 로직 없음(항상 보임) — 과설계 방지.

---

## 7. 원 목록 패널(`_circle_list`)에서도 삭제 가능하게

### 현재 상태
삭제 로직 자체(`ZoneCanvas.remove_selected()`, 185-194행)는 이미 공개 메서드로
존재하고 캔버스 키보드(`keyPressEvent()` Delete/Backspace, 810-811행) +
캔버스 우클릭 메뉴("원 삭제", `contextMenuEvent()` 860행)에서 이미 쓰이고 있다.
반면 우측 `_circle_list`(`zone_analysis_tab.py:486`, `QListWidget`)는 선택만
가능하고(`currentRowChanged` → `_on_list_row_selected()`, 1283-1289행) 삭제
수단이 전혀 없다.

### 수정 — 우클릭 컨텍스트 메뉴로 통일(상시 아이콘 금지)
2번 항목에서 막 되돌린 "상시 노출 × 아이콘"과 반대 방향 패턴을 또 추가하지
않도록, **우클릭 컨텍스트 메뉴만** 추가한다(기존 `remove_selected()` 재사용,
신규 삭제 로직 없음):
```python
# _build_ui() 안, self._circle_list 생성 직후(486행 부근)
self._circle_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
self._circle_list.customContextMenuRequested.connect(self._on_circle_list_context_menu)
```
```python
def _on_circle_list_context_menu(self, pos) -> None:
    item = self._circle_list.itemAt(pos)
    if item is None:
        return
    circle_id = item.data(Qt.ItemDataRole.UserRole)
    menu = QMenu(self)
    action = menu.addAction("삭제")
    if menu.exec(self._circle_list.viewport().mapToGlobal(pos)) == action:
        self._canvas.select_circle(circle_id)   # remove_selected()는 _selected_id
                                                  # 기준이므로 먼저 선택을 동기화한다
        self._canvas.remove_selected()
```
`QMenu`가 `zone_analysis_tab.py` 상단 `QtWidgets` import(31-36행)에 없으므로
추가 필요. `remove_selected()`가 `circles_changed`/`circles_committed`를 emit해
`_refresh_circle_list()`/`_recompute_zones()`가 기존 배선 그대로 자동 갱신된다
(신규 배선 불필요).

---

## 8. 결과 분석 — 전체 이미지 한 번에 보기 + 정렬

### 현재 진입점 2개뿐 — "전체 보기"가 없다
- `_on_export_single()`(1186-1201행): 현재 열린 이미지 1장만.
- `_on_batch_finished()`(1461-1478행): 방금 실행한 배치 1회분(`self._batch_rows`)만
  — 과거 세션에 처리했던 이미지나 이번 배치 대상이 아니었던 이미지는 빠진다.

### 제약 — 반드시 스펙에 못박아야 하는 것
`InferenceResult`(`raw_class_map`/`confidence_map`)는 **디스크에 영구 저장되지
않는다** — 세션 메모리(`self._results: dict[Path, InferenceResult]`, 168행)에만
있다. 사이드카(`zstate`, `.zone.json`)는 원/삭제이력/수동스트로크만 저장하고
AI 마스크 자체는 저장하지 않는다(`zone_state_store.py` 주석 "마스크 배열 없음"
그대로). **따라서 "전체 보기"는 "이번 세션에서 이미 추론을 실행한 이미지"만
집계 가능하다** — 과거 세션 결과나 미추론 이미지를 보려면 사용자가 먼저
추론(단일 또는 일괄 처리)을 실행해야 한다. **재추론을 자동으로 트리거하지
않는다**(과설계 방지, YAGNI — 수백~수천 장 폴더에서 버튼 하나로 전체 재추론이
암묵적으로 도는 것은 이번 요청 범위 밖이자 위험한 과잉 동작).

### 설계 — 기존 계산 로직 재사용(신규 core 함수 없음)
`_on_batch_image_inferred()`(1412-1458행)가 이미 "임의의 (path, result)에 대해
circles+zstate+target_cid로 zone 행/blob 행을 계산"하는 로직을 갖고 있다 — 이를
**순수 함수로 추출**해 배치 처리/전체 보기 둘 다 재사용한다(side effect —
`zstate.save_state()`/진행률 UI — 는 호출부가 필요할 때만 별도로 수행):
```python
def _compute_zone_rows(
    path: Path, result: InferenceResult, target_cid: int,
    circles: list[tuple], previous: dict | None,
) -> tuple[list[tuple[str, str, float]], list[tuple[str, "ZoneBlobStat"]]] | None:
    """(rows, blob_rows) — side effect 없음(저장은 호출부 책임).
    `_on_batch_image_inferred()`의 계산 핵심을 그대로 추출."""
    if not circles:
        return None
    h, w = result.raw_class_map.shape
    ai_mask = result.class_map == target_cid
    if previous is not None and previous["removed_blob_ids"]:
        labels, _, _ = compute_blob_labels(ai_mask)
        ai_mask = ai_mask & ~np.isin(labels, list(previous["removed_blob_ids"]))
    final_mask = apply_manual_strokes(ai_mask, previous["manual_strokes"]) if previous else ai_mask
    zones = zones_from_circles(
        [Circle(idx, cx, cy, r, (rest[0] if rest else None))
         for idx, (cx, cy, r, *rest) in enumerate(circles)], (h, w)
    )
    percentages = [zone_stats(zone.mask, final_mask) for zone in zones]
    rows = [(path.name, zone.name, pct) for zone, pct in zip(zones, percentages)]
    blob_rows = [(path.name, s) for s in zone_blob_stats(zones, ai_mask, final_mask, result.confidence_map)]
    return rows, blob_rows
```
`_on_batch_image_inferred()`는 이 함수를 호출한 뒤 자기 책임(`zstate.save_state()`,
`self._batch_rows.extend(rows)`, 진행률 UI)만 수행하도록 리팩터(동작 동일,
중복 제거).

신규 슬롯 `_on_view_all_results()`:
```python
def _on_view_all_results(self) -> None:
    if self._target_class_id is None:
        QMessageBox.information(self, "준비 안 됨", "먼저 추론을 실행하고 타겟 클래스를 확정하세요.")
        return
    self._flush_state()   # 현재 이미지의 편집 상태를 사이드카에 먼저 반영(비교 대상 최신화)
    all_rows, all_blob_rows, skipped = [], [], []
    for path in self._img_list.paths():
        result = self._results.get(path)
        if result is None:
            skipped.append(path.name)
            continue
        previous = zstate.load_state(path)
        circles = (self._canvas.get_circles() if path == self._image_path
                   else (previous or {}).get("circles", []))
        computed = _compute_zone_rows(path, result, self._target_class_id, circles, previous)
        if computed is None:
            continue
        rows, blob_rows = computed
        all_rows.extend(rows)
        all_blob_rows.extend(blob_rows)
    if not all_rows:
        QMessageBox.information(self, "결과 없음", "이번 세션에서 추론을 실행한 이미지가 없습니다.")
        return
    if skipped:
        QMessageBox.information(
            self, "일부 제외됨",
            f"이번 세션에서 추론하지 않은 {len(skipped)}장은 제외했습니다.\n"
            "(과거 세션 결과는 재추론 전까지 복원할 수 없습니다 — 먼저 추론을 실행하세요.)",
        )
    ZoneBatchResultDialog(all_rows, all_blob_rows, self).exec()
```
**진입점 UI**: 좌측 `_batch_box`("Zone 결정 방법" 그룹박스, 415-450행) 맨 아래
`_lbl_batch_condition` 다음에 `self._btn_view_all = QPushButton("전체 결과 보기")`
추가 — 배치 모드와 무관하게(단일 추론만으로도) 쓸 수 있는 기능이라 같은
그룹박스 안이되 모드 콤보와는 독립적으로 항상 평가되는 활성화 조건
(`bool(self._results)`)을 쓴다. 갱신 지점: `_on_run()` 시작부(`self._results.clear()`
직후 비활성화) + `_on_inference_result()`(결과 1개라도 생기면 활성화) +
`_on_batch_image_inferred()`(1번 수정으로 `self._results[path]=result`가 추가되므로
동일하게 활성화 트리거) — 간단히 `self._btn_view_all.setEnabled(bool(self._results))`
한 줄을 이 3곳에 추가.

### 정렬 — Long 탭(그룹화)과 Wide 탭(피벗) 충돌 검토
`zone_batch_result_dialog.py`의 Long 탭(`_build_long_tab()`, 144-192행)은
이미지명 기준 `setSpan()`으로 같은 이미지의 zone 행을 그룹 묶음 처리한다
(176-177행) — 일반 `QTableWidget.setSortingEnabled(True)`을 켜면 사용자가
다른 열(비율 등) 기준으로 정렬할 때 행 순서가 바뀌어 span이 깨진다. Wide 탭
(`_build_wide_tab()`, 196-225행)은 `setSpan()`을 전혀 쓰지 않는 순수 피벗
테이블이라 정렬을 켜도 구조가 깨지지 않는다.

**기본안 (a) 채택**: Long 탭은 정렬 비활성 유지(그룹화 우선), **Wide 탭에만**
`table.setSortingEnabled(True)` 추가. 숫자 열(퍼센티지)은 `QTableWidgetItem`
기본값이 **문자열 사전순 정렬**이라("10.00" < "9.00") 퍼센티지가 숫자 크기
순서로 정렬되도록 반드시 수치 데이터로 설정해야 한다(`setData(Qt.ItemDataRole.EditRole, pct)`
또는 동급 방법으로 — 구현 시 정렬 결과가 사전순이 아니라 크기순인지 반드시
확인할 것, Qt의 흔한 함정).

**(b)안(Long 탭도 정렬 지원, 기준이 '이미지'가 아닐 때 그룹화 해제)은 과설계로
판단해 채택하지 않는다** — 사용자 원문이 Long 탭 정렬을 명시적으로 요구했는지
불확실하고, 그룹화를 깨는 토글 로직까지 추가하면 diff/리스크가 커진다.
**디자인 확인 필요**: 사용자가 실제로 원하는 게 Long 탭 정렬인지, 아니면 "전체
보기 자체"가 핵심 요구였고 정렬은 Wide 탭 하나로 충분한지 디자인 단계에서
최종 확인 권장(결정 대기 등록은 아님 — (a)로 우선 진행해도 리스크 낮음).

### 필터 — 기존 필터 바 재사용, 신규 UI 없음
`ZoneBatchResultDialog`는 이미지명 검색 + 존 다중 토글 필터 바를 이미 갖추고
있다(`_build_filter_bar()`, 81-115행, 2026-10-02 구현). **전체 보기도 같은
`ZoneBatchResultDialog`를 그대로 재사용**(신규 다이얼로그 아님)하므로 이 필터는
추가 작업 없이 "전체 보기" 화면에도 동일하게 적용된다 — 사용자가 "필터링"을
요청한 것은 기존 기능을 몰랐거나, 전체 보기에도 똑같이 동작하는지 확인하고
싶었던 것으로 판단, 둘 다 이 재사용 설계로 충족된다.
**추가 필터 기준 검토**: "미처리 이미지 숨기기" 토글은 이번 설계에서 이미
"제외 + 안내 팝업 1회"로 처리되므로 별도 필터 UI가 필요 없다(참고 기록, 신규
구현 없음).

---

## 실행 순서 제안
파일 겹침 기준(1·3·4·5·6·7·8이 전부 `zone_analysis_tab.py`를 포함, 5·6·7이
추가로 `zone_canvas.py`/`zone_metrics.py`를 겹쳐 공유):
1. **1번(버그, 최우선)** — 한 줄 수정, 독립적. **8번이 1번의
   `self._results[path] = result`에 의존**(전체 보기 대상 판정 기준)하므로
   1번을 먼저 끝낼 것.
2. **2번** — `inference_image_list.py` 단독, 1번과 파일이 달라 병렬 가능.
3. **6번** — `zone_canvas.py` `wheelEvent()` 단독, 다른 항목과 겹침 없어 언제든
   병렬 가능(가장 작고 독립적인 수정).
4. **5번** — `zone_canvas.py`(컨텍스트 메뉴/데이터 모델) + `zone_metrics.py`
   (`Circle`/`zones_from_circles`/`scale_circles`/정렬 안정성) +
   `zone_analysis_tab.py`(circles_with_ids 호출부 4곳) — 6번과 같은 파일
   (`zone_canvas.py`)이니 6번 다음에 순차 진행 권장(병합 충돌 방지 목적일 뿐
   기능적 의존은 없음).
5. **3번** — `_on_run()`/`_on_inference_result()` 영역, 1번(`_on_batch_image_inferred`)과
   다른 함수라 병렬 가능하나 같은 파일.
6. **7번** — `_circle_list` 컨텍스트 메뉴, 5번 이후 권장(같은 사이드 패널 영역을
   다루므로 diff 단순화 목적, 기능적 의존 없음).
7. **4번** — `_recompute_zones()`/`_make_zone_row_widget()`, 디자인의 행 높이
   확인 이후 진행 권장.
8. **8번(마지막)** — 1번에 의존 + `_on_batch_image_inferred()` 리팩터(1번이
   추가한 캐시 라인을 포함해 정리) + 5번이 바꾼 `Circle`/`circles` 튜플 모양을
   그대로 사용하므로 **1·5번 이후** 진행. `zone_batch_result_dialog.py` Wide 탭
   정렬은 다른 항목과 파일이 겹치지 않아 이 안에서도 독립적으로 먼저 끝내도 무방.

디자인 영향 지점(리더 판단으로 구현 전 디자인 확인 권장): **2**(레이아웃 축소,
저위험) · **3**(진행바 폭/ETA 표시 방식) · **4**(패널 행 높이) · **6**(휠 힌트
캡션 문구/위치, 저위험) · **8**(Long 탭 정렬 지원 여부 재확인, "전체 결과 보기"
버튼 위치 확정).

결정 대기 없음. 4번 "등등" 건만 `decisions-needed.md`에 참고 기록 추가(완료).
5번의 "바깥쪽 존 이름 커스터마이즈 제외"·"중심/바깥쪽 renamed 시 Excel 열 순서
미관상 흔들릴 수 있음"과 8번의 "Long 탭 정렬 미지원(기본안 a)"은 전부 기획이
YAGNI/과설계 방지 원칙으로 직접 결정한 설계 범위 축소이며, 사용자 확인이 필요한
모호한 지점이 아니라고 판단해 결정 대기에 올리지 않았다(실사용에서 불편하면
후속 라운드로 분리 가능하다는 점을 각 절에 명시해 둠).
