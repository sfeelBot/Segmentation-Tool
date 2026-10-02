# 상/하부 분석(Zone) 탭 실사용 버그/요청 4건 (2026-10-03)

기획 완료. 대상 파일: `app/tabs/zone_analysis_tab.py`, `app/widgets/inference_image_list.py`,
`app/core/zone_metrics.py`(변경 없음, 재사용만). 전부 코드 근거로 원인을 특정했고
결정 대기 등록 대상 없음 — 1번만 재현 전제(실행 도구 미지급, 정적 추적만 수행)로
구현 착수 전 실제 GUI 재현을 권장(GitHub #9/#16 라운드와 동일 패턴, 구현을 막을 만큼
확신이 낮은 것은 아님).

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

## 실행 순서 제안
파일 겹침 기준(전부 `zone_analysis_tab.py`를 건드리므로 순차 권장):
1. **1번(버그, 최우선)** — 한 줄 수정, 독립적.
2. **2번** — `inference_image_list.py` 단독, 1번과 파일이 달라 병렬 가능.
3. **3번** — `zone_analysis_tab.py`의 `_on_run()`/`_on_inference_result()` 영역,
   1번이 건드리는 `_on_batch_image_inferred()`와 다른 함수라 병렬 가능하나 같은
   파일이니 순서대로 처리 권장.
4. **4번** — `_recompute_zones()`/`_make_zone_row_widget()`, 3번과 다른 함수.
   디자인 에이전트의 행 높이 확인이 필요해 마지막 권장.

결정 대기 없음. 4번 "등등" 건만 `decisions-needed.md`에 참고 기록 추가(아래 조치).
