# Zone 분석 탭 — 배치 단순화 + 존 이름/숨김 + 결과 일괄 저장 (2026-10-29)

사용자 요청 9건의 스코프 산정. 작업 디렉토리: `D:/segmentation model-zone-analysis-tab`
(worktree, branch `feature/zone-analysis-tab`). 전부 `app/tabs/zone_analysis_tab.py` +
`app/widgets/zone_canvas.py` + `app/core/zone_metrics.py` + `app/core/zone_state_store.py` +
`app/core/zone_recipe_store.py` + `app/widgets/zone_recipe_dialog.py` + `app/core/i18n.py`에
걸쳐 있다. 코드 조사는 플래너가 직접 각 파일을 열어 재검증했고(리더 사전 조사와 거의
일치하되 2곳 정정 — 아래 "리더 사전 조사 대비 정정" 참고), 추측으로 스코프를 잡지 않았다.

## 리더 사전 조사 대비 정정 (중요 — 설계가 달라짐)

1. **"레시피는 이름이 없다"는 사전 조사는 부정확함.** `zone_recipe_store.save_recipe()`의
   타입 힌트는 `list[tuple[float, float, float]]`(3요소)라고 돼 있지만, 실제 구현
   (`payload["circles"] = [list(c) for c in circles]`)은 튜플 길이를 전혀 검사하지 않는
   제네릭 패스스루다. `ZoneRecipeDialog._on_save_recipe()`가 이미 `self._canvas.get_circles()`
   (현재 `(cx, cy, r, name)` 4요소)를 그대로 넘기므로, **이름은 이미 레시피에 저장·복원되고
   있다**(타입 힌트/문서화만 안 돼 있었을 뿐). `zone_state_store.py`의 `save_state`/
   `load_state`도 `state["circles"]`를 완전히 제네릭으로 다룬다(길이 검사 없음). 즉
   요구사항 8의 "레시피 확장"은 **신규 저장 레이어 코드가 필요한 게 아니라, 요구사항 7의
   `hidden` 필드가 원 튜플에 추가되기만 하면 두 저장소(`zone_state_store.py`/
   `zone_recipe_store.py`)는 코드 수정 없이 자동으로 `hidden`도 함께 영속화한다**. 단,
   `scale_circles()`(`zone_metrics.py:64-80`)도 이미 `*rest`를 그대로 통과시키는 제네릭
   함수라 재확인 완료.
2. **바깥쪽(outermost) 존 이름은 원과 달리 튜플에 얹어 보낼 수 없다** — 어떤 원에도
   귀속되지 않는 스칼라 값이라, `zone_state_store.py`/`zone_recipe_store.py` 양쪽에
   **새 top-level 키 `outer_name`을 실제로 추가하는 코드 변경이 필요**하다(이 부분은
   사전 조사 그대로 유효).

이 정정 덕분에 요구사항 8의 실제 구현 범위는 사전 조사보다 훨씬 작다: `hidden`은 "공짜로"
영속화되고, `outer_name`만 두 저장소에 신규 키로 추가하면 된다.

---

## 데이터 모델 변경

### `hidden: bool` — 원(circle) 단위 속성

`app/widgets/zone_canvas.py`의 `_CircleItem`(`:66-72`)에 `hidden: bool = False` 필드 추가.
영향받는 메서드(전부 `name` 필드를 다루는 기존 패턴을 그대로 `hidden`까지 확장):

- `set_circles()`(`:145-152`) — `*rest`에서 `rest[0]`은 name, `rest[1]`은 hidden으로 파싱
  (역호환: 3요소/4요소/5요소 입력 전부 허용, 없으면 각각 `None`/`False` 기본값).
- `get_circles()`(`:160-162`) — 반환 튜플이 `(cx, cy, r, name)` 4요소 →
  `(cx, cy, r, name, hidden)` 5요소로 **확장**(기존 4요소 기대 호출부는 아래 "호출부
  수정 목록"에서 전부 열거).
- `circles_with_ids()`(`:164-166`) — 동일하게 5요소 → 6요소(`id` 포함)로 확장.
- `get_state()`/`set_state()`(`:438-459`) — 사이드카 스냅샷의 `circles` 튜플도 6요소로
  확장(`set_state()`는 이미 `*rest` 가변 길이 파싱이라 길이만 늘리면 됨, 역호환 자동
  확보).
- `contextMenuEvent()`(`:852-874`) — 메뉴 항목 추가: "숨기기"/"보이기"(현재 `hidden` 값에
  따라 라벨 토글). 새 메서드 `_prompt_toggle_hidden(circle_id)` 또는 간단히
  `_toggle_hidden(circle_id)`(확인 다이얼로그 불필요, 비파괴 작업이라 즉시 토글) —
  `_prompt_name_change()`(`:896-911`)와 동일하게 `_push_undo()` → 필드 변경 → emit
  `circles_changed`/`circles_committed`.

**호출부 수정 목록** (`get_circles()`/`circles_with_ids()`의 튜플 길이가 늘어나므로 기존
고정 언패킹 `for cid, cx, cy, r, name in ...` 전부 `hidden`까지 받도록 수정 필요):

| 위치 | 현재 | 수정 |
|---|---|---|
| `zone_analysis_tab.py:1296-1299` `_current_zones()` | `for cid, cx, cy, r, name in circles_raw: Circle(cid, cx, cy, r, name)` | `hidden`까지 언패킹, `Circle(cid, cx, cy, r, name, hidden)` |
| `zone_analysis_tab.py:1429` `_on_canvas_blob_clicked()` | 동일 패턴 | 동일 수정(이 함수는 `hidden` 자체는 안 씀, 언패킹만 맞추면 됨) |
| `zone_analysis_tab.py:1566-1568` `_refresh_circle_list()` | `for i, (circle_id, cx, cy, r, name) in enumerate(...)` | `hidden`까지 받고, 숨김 상태면 라벨에 흐림 표시(예: 괄호 텍스트 또는 아이콘) + 항목 스타일(회색조) 반영 |
| `zone_analysis_tab.py:1486-1487` `_on_view_all_results()` | `[c[1:] for c in (previous...).get("circles", [])]` | 그대로 둬도 동작(슬라이스는 길이에 무관) — 수정 불필요, 확인만 |
| `_ZoneBatchPostWorker.run()`(`:219-222`) | `(idx, cx, cy, r, rest[0] if rest else None)` | **요구사항 4 설계에 따라 이 클래스/이 분기 자체가 삭제됨**(아래 "요구사항 4" 절), 수정 아님 |
| `_compute_zone_rows()`(`:239-262`, 모듈 함수) | `Circle(idx, cx, cy, r, (rest[0] if rest else None))` | `hidden` 파싱 추가 + 아래 "바깥쪽 존 이름" 절의 `outer_name` 파라미터 추가 |

### `outer_name: str | None` — 바깥쪽 존 전용(원에 귀속 안 됨)

- `ZoneCanvas`에 `self._outer_name: str | None = None` 필드 + `outer_name() -> str | None`
  getter + `rename_outer_zone(name: str | None) -> None` 메서드(신규) 추가.
  `rename_outer_zone()`은 `_prompt_name_change()`(`:896-911`)와 동일 패턴
  (`_push_undo()` → 필드 설정 → `update()` → `circles_changed`/`circles_committed` emit)
  — 원 선택과 무관하므로 `_find(circle_id)` 단계만 없음.
- `get_state()`/`set_state()`에 `"outer_name"` 키 추가(역호환: `state.get("outer_name")`으로
  읽어 과거 스냅샷엔 `None` 기본값).
- `zone_state_store.py`: `save_state()`의 `payload`에 `"outer_name": state.get("outer_name")`
  추가 + `is_empty` 판정(`:25`)에 `and not state.get("outer_name")` 추가(이름만 있고 원이
  하나도 없는 극단적 상태도 사이드카를 유지해야 함). `load_state()`의 반환 dict에
  `"outer_name": payload.get("outer_name")` 추가(구버전 파일엔 키가 없으므로 `.get()`
  기본값 `None` — 자동 역호환).
- `zone_recipe_store.py`: `save_recipe()` 시그니처에 `outer_name: str | None = None` 추가,
  `payload["outer_name"] = outer_name`. `load_recipe()` 반환 dict에
  `"outer_name": payload.get("outer_name")` 추가(구버전 레시피 파일 자동 역호환).
- `zone_metrics.py`의 `zones_from_circles()`(`:83-98`)에 `outer_name: str | None = None`
  파라미터 추가, 맨 바깥 Zone 생성 시(`:97`) `outer_name or "바깥쪽"`으로 교체.
- **호출부**: `zone_analysis_tab.py`의 `_current_zones()`(실시간, `self._canvas.outer_name()`
  사용) + 모듈 함수 `_compute_zone_rows()`(새 파라미터로 받아 그대로 전달) +
  `_on_view_all_results()`(루프 안에서 `path == self._image_path`면 `self._canvas.outer_name()`,
  아니면 `(previous or {}).get("outer_name")` — 기존 `circles` 처리와 완전히 동일한 분기
  패턴, `:1486-1487` 바로 옆에 추가).
- `ZoneRecipeDialog`(`app/widgets/zone_recipe_dialog.py`)도 자신의 임베디드 `ZoneCanvas`를
  쓰므로 `_on_save_recipe()`(`:188-203`)가 `self._canvas.outer_name()`을 `save_recipe()`에
  같이 넘기고, `_on_load_recipe()`/`_load_most_recent()`(`:161-186`)가 로드된
  `recipe["outer_name"]`을 `self._canvas.rename_outer_zone()` 또는 직접 setter로 반영.
  **다만 이 다이얼로그 자체에 바깥쪽 존 이름을 입력하는 UI를 새로 넣을 필요는 없다** —
  레시피는 메인 탭에서 이미 설정한 상태(`self._canvas` 전체 상태)를 그대로 가져오는 게
  아니라 "원 집합"만 들고 다니는 별도 편집 플로우이므로, 바깥쪽 이름 입력 자리는 메인
  탭의 `_zone_list` 패널(요구사항 7)에만 추가한다. 레시피 다이얼로그는 저장/로드 시
  **메인 탭의 현재 outer_name을 그대로 실어 나르는 통로 역할만** 한다(구체적으로: 다이얼로그
  오픈 시 메인 탭이 `reference_pixmap`/`ref_size`를 넘기는 생성자에 `outer_name`도 추가로
  넘겨 다이얼로그의 캔버스가 시작부터 그 값을 들고 있게 하고, `_on_apply()`(`:228-230`)가
  `result_circles()`와 함께 `result_outer_name()`도 반환하게 한다).

---

## 요구사항별 설계

### 1. 자동검출 버튼 삭제

`_btn_detect`(`:424-427`) 위젯 생성 + `_on_auto_detect()`(`:1508-1525`) 메서드 전체 +
`:681` 시그널 연결 + `:777,811,819,1041,1059`의 `setEnabled` 호출/주석 삭제. 이미지 로드
직후 "원(circle) 편집" 도구가 활성화되는 로직(`_act_circle.setEnabled(True)` 등, `:806`)은
자동검출과 무관하게 유지.

### 2. 배치 모드를 '고정' 하나로 단순화

`_mode_combo`(`:554-558`) 위젯 자체와 `_on_batch_mode_changed()`(`:1528-1532`) 삭제.
`_btn_recipe`(`:560-566`)는 항상 보이게(`_build_ui()`에서 `setVisible` 호출 없이 기본
노출, 혹은 명시적으로 always-visible 처리) — 더 이상 모드에 따라 토글하지 않는다.
`per_image` 모드가 쓰던 `detect_circles()` 직접 호출 분기(`_ZoneBatchPostWorker.run()`
`:197-200`)는 요구사항 4의 워커 재설계와 함께 통째로 제거된다(아래 참고).

### 3. 민감도 슬라이더 제거

`_sensitivity_slider`/`_lbl_sensitivity`(`:414-423`) 위젯 생성 + `:682-683` 시그널
연결 + `:1512`(`_on_auto_detect` 내부, 1번과 함께 제거) + `:1652`(`_on_batch_process`
내부, 4번과 함께 제거) 삭제. **`ZoneRecipeDialog`(`app/widgets/zone_recipe_dialog.py:78-96`)
의 자체 슬라이더/검출 버튼은 완전히 별개 코드이므로 그대로 유지** — 파일이 다르므로
실수로 같이 지울 위험은 낮지만, 구현 시 diff를 `zone_analysis_tab.py`로 한정할 것.

i18n 키 삭제 대상(ko/en 쌍, `i18n.py:328-331,909-912`): `zone.sensitivity_label`,
`zone.sensitivity_tip`, `zone.btn_detect`, `zone.detect_tip`. **주의**: 이 키들은
`zone_recipe_dialog.py`가 쓰는 `zone_recipe.sensitivity_label`/`zone_recipe.btn_detect`
등(별도 네임스페이스)과 이름이 다르므로 혼동 없이 삭제 가능 — 구현 시 grep으로
`zone_recipe.*` 접두사 키는 건드리지 않는지 재확인.

### 4. 배치 적용에 추론/모델 요구사항 제거 (가장 영향도 큰 항목)

**현재 구조**: `_on_batch_process()`(`:1635-1711`)는 클릭 즉시 (a) 게이팅 체크
(`_last_result`/`_model`/`_ckpt_path`/`_target_class_id`/`_target_classes` 전부 non-None,
`:1636-1643`) → (b) `_ZoneBatchWorker`(CUDA 추론, `:107-158`)로 대상 이미지 전체를
**새로 추론**(캐시 없는 이미지만) → (c) `_ZoneBatchPostWorker`(`:160-228`)가 추론 결과를
받아 원 복사(`scale_circles`) + 존/블랍 퍼센티지 계산(`_compute_zone_rows`) + 사이드카
저장을 수행 → (d) `_on_batch_finished()`(`:1778-1804`)가 모든 결과를 모아
`ZoneBatchResultDialog`(퍼센티지 표)를 띄운다. 즉 "원 복사"와 "추론"이 한 파이프라인에
얽혀 있어, 추론을 아예 안 하고 싶어도(모델 미선택) 원을 복사할 방법이 없다 — 이게
이번 요구사항이 가리키는 근본 문제.

**새 구조 제안**: "원 복사"를 추론과 완전히 분리한다.

1. `_on_batch_process()`의 게이팅을 `circles_ref`(기준 이미지 원 1개 이상, 기존에도
   있던 체크 `:1644-1647`)와 `targets` 비어있지 않음만으로 축소. `_last_result`/
   `_model`/`_ckpt_path`/`_target_class_id`/`_target_classes` 체크(`:1636-1643`) 전부
   삭제. `_update_batch_button_state()`(`:1612-1616`)는 원래부터 모델을 체크하지
   않았으므로(원 개수 + 이미지 2장 이상만) 버튼 활성화 자체는 수정 불필요 — 지금까지
   "버튼은 눌리는데 클릭하면 경고가 뜨는" 불일치가 있었던 것이 이번에 해소되는 것.
2. `_ZoneBatchWorker`(CUDA 추론 워커)는 **배치-원복사 경로에서 더 이상 호출하지
   않는다** — 이 클래스 자체는 코드에서 제거(다른 호출부 없음, 위 조사에서 확인 완료).
3. `_ZoneBatchPostWorker`(`:160-228`)를 더 가벼운 전용 워커로 재작성(이름 변경 제안:
   `_ZoneCircleLayoutWorker`) — 입력은 `(circles_ref, ref_size, outer_name, target_paths)`
   뿐, `InferenceResult`/`target_cid`/`sensitivity`/`mode` 전부 불필요(2·3번 요구사항으로
   `per_image` 분기 자체가 없어졌으므로). `run()`은 각 대상 경로에 대해 ① 이미지를
   열어 크기만 읽음(`Image.open` → `.size`, 디코딩 없이 헤더만 읽어도 되지만 기존
   코드 관례(`Image.open().convert("RGB")`)와 일관되게 `.size` 속성만 접근 — PIL은
   lazy load라 `.size` 접근 시 전체 디코딩을 안 함, 성능상 기존보다 오히려 가벼움)
   ② `scale_circles(circles_ref, ref_size, (w, h))`로 스케일 ③ 기존 사이드카
   (`zstate.load_state(path)`)를 불러와 `removed_blob_ids`/`erase_strokes`/
   `manual_strokes`는 보존하고 `circles`/`outer_name`만 덮어써 `zstate.save_state()`.
   CUDA를 전혀 호출하지 않으므로 BUG-030류 스레드 제약도 해당 없음(단일 워커로 충분,
   `_ZoneBatchPostWorker`처럼 2단 파이프라인일 필요 없음).
4. `_on_batch_finished()`(`:1778-1804`)는 더 이상 퍼센티지(`rows`/`blob_rows`)를 집계하지
   않는다 — **설계 결정이 필요한 지점**(아래 "결정 필요" 절 참고). 권장안: 배치 완료 시
   `ZoneBatchResultDialog`를 띄우지 않고 단순 확인 메시지("N장에 영역 적용 완료 — 개별
   이미지를 열어 추론을 실행하면 비율을 확인할 수 있습니다")만 표시. 사용자가 비율을
   보고 싶으면 이미 있는 "결과보기"(`_btn_view_all`) 버튼을 쓰면 된다(그 버튼은 이미
   추론 안 된 이미지를 자동으로 건너뛰므로, "방금 영역만 깔고 추론 안 한 이미지"가
   섞여 있어도 안전하게 동작 — `_on_view_all_results()` 기존 `skipped` 처리 그대로 재사용).
5. `_update_batch_button_label()`(`:1618-1620`)/진행률 다이얼로그(`:1684-1691`) 등 UI는
   거의 그대로 유지(대상 개수/ETA 표시는 추론 유무와 무관).
6. i18n: `zone.batch_condition_label`(`"필요 조건: 추론 실행 · 원 1개 이상 · 이미지
   2장 이상"`, `:360,941`)에서 "추론 실행" 부분 삭제. `zone.not_ready_msg2`/
   `zone.not_ready_title`(`:408,989`, `_on_batch_process`에서만 쓰이던 경고 문구) —
   `not_ready_title`은 `_on_view_all_results()`도 같이 쓰므로 유지, `not_ready_msg2`는
   더 이상 아무도 참조하지 않으므로 ko/en 키 삭제.

### 5. 배치 후 개별 수정 가능

코드 변경 불필요 — `_on_list_image_selected()`(`:784-823`)가 이미지 선택마다 편집
도구를 항상 재활성화하므로 배치 전후 관계없이 이미 가능. 검증 단계에서 "배치 적용
직후 개별 이미지를 열어 원을 드래그/삭제할 수 있는지"만 회귀 확인.

### 6. 존별 비율 패널에서 "삭제" = 숨기기(비파괴)

`hidden` 필드는 위 "데이터 모델" 절에서 이미 설계. 적용 지점:

- **패널 UI**: `_make_zone_row_widget()`(`:1331-1366`)가 그리는 각 행에 숨기기/
  다시보이기 토글 추가(체크박스 또는 우클릭 메뉴 — 패널 전체가 이미 `QListWidgetItem`+
  `setItemWidget()` 패턴이라 체크박스를 행 위젯에 심는 쪽이 자연스러움). 바깥쪽 존은
  원이 없어 `hidden` 토글 대상이 아니다 — **이번 라운드에서 바깥쪽 존의 숨김 기능은
  범위 밖**(요구사항 6 원문이 "숨김 상태는 원 단위 속성"이라 명시했으므로 결정 불필요,
  단순 스코프 경계로 기재).
- **표시 필터**: `_recompute_zones()`(`:1368-1404`)가 `_current_zones()`로 얻은
  `zones`(각 `Zone.hidden` 보유)와 `_compute_zone_percentages(zones)`가 반환한
  `pct_rows`를 **같은 순서로 zip**해 `hidden=True`인 항목만 걸러내고 패널에 추가.
- **Excel 내보내기 필터**: `_on_export_single()`(`:1445-1461`)과
  `_on_view_all_results()`(`:1463-1504`, 내부에서 `_compute_zone_rows()` 호출) 양쪽
  모두 같은 필터를 적용해야 한다. 퍼센티지 행(`rows`)은 위와 동일하게 zip-필터.
  블랍 행(`blob_rows`, `ZoneBlobStat.zone_name` 문자열만 가짐)은 숨겨진 존의 **이름
  집합**(`{z.name for z in zones if z.hidden}`)으로 걸러낸다 — 이름 충돌(사용자가 두
  존에 같은 이름을 붙인 경우) 시 과도하게 걸러질 수 있는 기존에도 존재하던 한계
  (`max_blob_pixels_by_zone()`도 이미 `(image_name, zone_name)`로 키잉해 이름 충돌을
  가정하지 않음)를 그대로 상속 — 이번 기능이 새로 만드는 리스크 아님, 수정 범위 밖.
  **중복 방지를 위해 이 필터 로직(zones+rows+blob_rows → 숨김 제외)을
  `zone_metrics.py`에 작은 순수 함수(예: `drop_hidden(zones, rows, blob_rows)`)로
  추출해 `_recompute_zones()`/`_on_export_single()`/`_compute_zone_rows()`(모듈 함수,
  `_on_view_all_results()`가 호출) 3곳이 공유**하도록 구현 권장 — 세 곳에 같은 필터
  코드를 복붙하지 않기 위함(DRY, 버그 발생 지점 1곳으로 축소).
- **면적/비율 계산 자체는 변경 없음**: `zone_stats()`(`zone_metrics.py:120-126`)는 존별로
  독립 계산(다른 존의 분모에 영향 없음)이라 숨김이 수학에 개입할 지점이 없음 — 순수
  표시+export 레이어 필터라는 요구사항 원문과 정확히 일치.

### 7. 존 이름 변경을 패널에서 직접

- 각 `_zone_list`(`:635-637`) 행(링 존 + 중심부)에 더블클릭 또는 우클릭 메뉴로 이름
  변경 — 내부적으로 해당 행이 어느 `circle_id`에 대응하는지 알아야 하므로,
  `_make_zone_row_widget()` 호출부(`_recompute_zones()`)가 각 Zone의 인덱스↔circle_id
  매핑을 같이 들고 있어야 한다. `zones_from_circles()`가 반지름 오름차순 정렬
  (`sorted_c`)이므로, `_current_zones()`가 이미 갖고 있는 `circles_raw`(id 포함,
  `circles_with_ids()` 반환, 반지름 오름차순으로 정렬된 상태 — `:162,166`의 `sorted(...,
  key=lambda c: c.r)`와 동일 정렬 기준)를 `_recompute_zones()`까지 전달해 zone index
  0..n-2를 circle_id로 역매핑(index 0 = 가장 작은 원, index i+1 = (i+1)번째로 작은
  원 — `zones_from_circles()`의 정렬 로직과 반드시 같은 키를 써야 함, 안 그러면 엉뚱한
  원 이름이 바뀜). 맨 마지막 인덱스(바깥쪽)는 circle_id가 없으므로 "이름 변경" 메뉴가
  `ZoneCanvas.rename_outer_zone()`을 호출하도록 분기.
- 변경 시 `ZoneCanvas._prompt_name_change(circle_id)`(`:896-911`, 기존 로직 그대로
  재사용 — 캔버스가 다이얼로그를 직접 띄우는 패턴이라 패널에서도 같은 메서드를
  호출하면 됨) 또는 바깥쪽이면 `rename_outer_zone()`.
- 캔버스 우클릭(기존 `contextMenuEvent` 경로)은 그대로 유지 — 패널 경로가 추가되는
  것뿐, 기존 경로 제거 없음.

### 8. 레시피 확장

위 "데이터 모델" 절에서 설명한 대로 `hidden`은 추가 저장소 코드 없이 자동 역호환,
`outer_name`만 `zone_recipe_store.py`/`zone_state_store.py`에 신규 키 추가. 저장 다이얼로그
(`zone_recipe_dialog.py`)의 이름 입력란(`_name_edit`, `:108-109`) 기본값을
`f"{date.today():%Y%m%d}_recipe"`로 미리 채움 — `_build_ui()` 또는 `__init__()`에서
`self._name_edit.setText(...)` 1줄 추가(단, `_load_most_recent()`가 기존 레시피 이름으로
덮어쓰므로, **호출 순서를 반대로**: 기본값 세팅 → `_load_most_recent()` 호출 — 현재
`__init__`(`:55-56`)의 `self._build_ui(); self._load_most_recent()` 순서라면 `_build_ui()`
안에서 기본값을 세팅하면 그 다음 `_load_most_recent()`이 레시피가 있을 때만 덮어쓰고,
레시피가 없으면 날짜 기본값이 그대로 남아 요구사항과 정확히 일치 — 순서 변경 불필요,
그대로 두면 됨).

"최근 레시피 자동 로드"는 `_load_most_recent()`(`:161-172`)가 이미 처리 — 추가 구현 없음,
단 역호환 확인: 옛 레시피 파일(name/hidden/outer_name 필드가 아예 없던 시절 저장분)을
로드할 때 `load_recipe()`가 `KeyError` 없이 기본값(`None`/`False`)으로 복원되는지
자가 테스트(`zone_recipe_store.py` 하단 `__main__` 자가진단 블록, `:91-127`)에 **구버전
포맷 로드 케이스(3-tuple만 있는 레거시 JSON을 직접 작성해 `load_recipe()` 통과 확인)**를
추가하는 것을 구현 단계에 명시 권장.

### 9. "결과보기" 아래 — 결과 이미지 일괄 저장(PNG)

`_btn_view_all`(`:649-652`) 바로 아래 `side_layout`에 신규 버튼 추가(예:
`self._btn_save_all_images`). 핵심 발견 — **이미 거의 공짜로 구현 가능**:
`InferenceResult.overlay_image`(`app/core/inference_engine.py:50`)는 `QImage`이고,
`self._results: dict[Path, InferenceResult]`(`:277`)에 세션 중 추론을 실행한 이미지마다
이미 최신 상태로 보관돼 있다 — 브러시 보정/블랍삭제 편집이 생길 때마다
`_reblend_overlay()`(`:1169-1196`)가 그 이미지가 활성 상태였던 시점에 동기적으로
`self._results[path].overlay_image`를 갱신해두므로(`:1193-1194`), 별도 재계산 없이
`result.overlay_image.save(str(out_dir / f"{path.stem}.png"))` 한 줄로 끝난다.

핸들러 설계:
1. `self._results`가 비어 있으면 안내 팝업(재사용: `_on_view_all_results()`의
   `not_ready_*` 패턴).
2. `QFileDialog.getExistingDirectory()`로 저장 폴더 선택.
3. `self._flush_state()` 호출(현재 이미지의 사이드카를 먼저 디스크에 반영 — 다른
   슬롯들의 기존 관례, `overlay_image` 자체의 신선도에는 영향 없지만 일관성 차원).
4. `self._results.items()`를 순회해 각 `overlay_image.save(...)` — 추론 안 된 이미지는
   `self._results`에 키 자체가 없으므로 자동 제외(요구사항과 일치).
5. 동기 루프로 충분(이미 메모리에 있는 `QImage`를 디스크에 쓰는 것뿐, CUDA/디코딩
   없음) — 수백 장 규모까지는 `QApplication.setOverrideCursor(WaitCursor)` 정도로
   충분, 별도 `QThread`는 **과설계**(YAGNI) — 사용자가 체감 프리징을 보고하면 그때
   `QThread` 승격을 고려. 완료 후 "N개 저장 완료" 안내.

---

## 손대지 않는 것 (명시적 범위 밖)

- `ZoneRecipeDialog` 자체의 민감도 슬라이더/자동검출 버튼(`zone_recipe_dialog.py:78-96,
  207-221`) — 메인 탭과 별개 코드, 이번 라운드 전부 유지.
- `_btn_export_single`(`:642-648`, 기존 단일 이미지 Excel 내보내기 버튼 자체) — 숨김
  필터만 그 내부 계산에 반영되고 버튼/다이얼로그 자체는 그대로.
- `zone_metrics.py`의 면적/퍼센티지 수식(`zone_stats`/`zone_blob_stats`/`disk_mask`) —
  숨김은 순수 표시 레이어 필터이므로 이 함수들 내부 로직은 무변경(요구사항 6 원문과
  일치).
- `zone_state_store.py`/`zone_recipe_store.py`의 "원" 처리 자체(제네릭 패스스루 구조) —
  이미 `hidden`을 공짜로 지원하므로 건드릴 필요 없음(위 "정정" 절 참고).

---

## 리스크/실행 순서 제안

의존관계 그래프:

- **1(자동검출 버튼)·2(모드 콤보 제거)·3(민감도 슬라이더)**: 서로 강하게 얽혀 있다
  — 2번이 없어지면 `per_image` 분기가 죽고, 그 분기가 3번(슬라이더)의 유일한 메인탭
  소비자였으므로 1·2·3은 **한 덩어리로 같은 커밋에서 처리**하는 게 합리적(순서를
  나눠봐야 중간 상태가 더 복잡해짐 — 예: 2번만 먼저 하면 `_on_batch_process`가 여전히
  `mode`/`sensitivity`를 읽는 코드가 남아 깨짐).
- **4(배치 게이팅+워커 재설계)**: 1·2·3이 먼저 끝나야 한다 — `_ZoneBatchPostWorker`
  재작성이 "per_image 분기가 이미 없다"는 전제를 깔고 설계됐기 때문(위 "요구사항 4"
  절 3번 항목). **가장 리스크가 큰 항목** — CUDA 워커(`_ZoneBatchWorker`) 제거 +
  파이프라인 구조 변경이라, 구현 후 검증 에이전트가 반드시 "배치 적용(모델 미로드
  상태에서) → 개별 이미지 추론 → 결과보기"까지 실제 골든패스로 확인해야 한다.
- **5(배치 후 수정 가능)**: 코드 변경 없음, 4번 검증에 자연히 포함.
- **6(숨기기)·7(이름변경 패널)**: 둘 다 `_zone_list`/`_make_zone_row_widget()`를
  건드리므로 **같은 커밋으로 묶는 게 충돌 방지에 유리**(7번의 circle_id 역매핑 설계가
  어차피 `_recompute_zones()` 쪽을 손대야 하고, 6번의 hidden 필터도 같은 함수를 손댐).
  7번(이름변경)이 먼저 필요로 하는 `_CircleItem.hidden` 필드(6번 데이터모델)는
  **독립적으로 먼저 추가**해도 무방 — 6·7은 데이터모델(병렬 가능) → UI(순차, 같은
  파일 영역) 순으로 진행 권장.
- **8(레시피 확장)**: 6·7의 `hidden`/`outer_name` 필드가 먼저 존재해야 저장소가
  "공짜로" 영속화할 수 있다 — **6·7 완료 후 착수**. 레시피 다이얼로그의 이름 기본값
  변경(날짜 포맷)은 8의 나머지 부분과 독립적이라 더 일찍 해도 되지만, 작은 변경이라
  굳이 분리할 필요 없음(같은 커밋 권장).
- **9(결과 일괄 저장)**: 다른 8건과 완전히 독립(읽기 전용 신규 버튼, 기존 데이터
  구조를 전혀 바꾸지 않음) — **언제든 병렬로 진행 가능**, 순서 제약 없음.

권장 순서: **(1+2+3) 단독 → 4(최우선 다음, 고리스크) → (6+7, 데이터모델 병렬 →
UI 순차) → 8 → 9(언제든 병렬)**. 9는 구현 리소스가 남으면 1~3과 동시에 시작해도
무방(완전히 다른 코드 영역).

---

## 결정 필요 (`docs/decisions-needed.md`에 등록함)

**배치 적용(요구사항 4) 완료 후 UX**: 지금은 배치가 끝나면 항상 퍼센티지 결과표
(`ZoneBatchResultDialog`)가 자동으로 열린다. 모델/추론 의존성을 완전히 제거하면 배치
시점에는 퍼센티지를 계산할 데이터(추론 결과)가 없는 경우가 생긴다(사용자가 설명한
워크플로우 자체가 "영역만 먼저 깔고 나중에 개별 추론"이므로 이게 기본 케이스가 됨).
두 가지 선택지:
- **A(플래너 권장)** — 배치 완료 다이얼로그를 퍼센티지 표 대신 단순 확인 메시지로
  교체("N장에 영역 적용 완료"). 비율이 보고 싶으면 사용자가 각 이미지를 열어 추론을
  실행한 뒤 기존 "결과보기" 버튼을 쓴다. 가장 단순하고 추론-무관 요구사항과 정확히
  부합.
- **B** — 배치 대상 중 이미 이번 세션에 추론을 실행해 `self._results`에 캐시가 있는
  이미지만 기회적으로 퍼센티지를 집계해 부분 결과표를 보여준다(나머지는 스킵). 기존
  "배치 후 바로 결과 확인" 체감을 일부 보존하지만, 코드가 더 복잡해지고(모델-무관이라는
  새 요구사항과 "모델이 있으면 그 혜택을 쓴다"는 예외가 공존), 어떤 이미지는 바로
  보이고 어떤 건 안 보이는 혼란스러운 중간 상태를 만들 수 있음.

리더가 사용자에게 확인 필요. 결정 전까지 구현은 A를 기본값으로 진행해도 안전(가장
단순하고, 나중에 B로 확장하는 방향의 변경이 B에서 A로 축소하는 것보다 쉬움).
