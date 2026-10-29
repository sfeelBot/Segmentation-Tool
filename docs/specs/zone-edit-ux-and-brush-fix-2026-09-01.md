# Zone 분석 탭 — 편집 도구 UX 개선 6건 + 브러시 버그 조사 (2026-09-01)

작업 위치: `D:\segmentation model-zone-analysis-tab` (`feature/zone-analysis-tab`, 에디션
브랜치). 6건 전부 `v1.5.0`으로 묶어 릴리스 예정(버전 태깅/빌드는 이 스펙 범위 밖).

사용자 원문 6가지는 `docs/roadmap.md` "존(Zone) 분석 탭" 절 하위(2026-09-01 요청)에도
요약 반영. 코드 대상 파일은 `app/widgets/zone_canvas.py`(734줄, ZoneCanvas)와
`app/tabs/zone_analysis_tab.py`(ZoneAnalysisTab) 둘뿐 — 신규 파일 없음.

## 감사 방법론

이번 세션은 실행 도구(Bash/QTest)가 지급되지 않아 **순수 정적 코드 추적**으로만
감사했다. 요청 1~5는 코드 흐름을 끝까지 따라가 확정적 근거를 확보했다. 요청 6(버그)은
`zone_canvas.py`/`zone_analysis_tab.py`의 모드 전환·활성화·마스크 재계산 경로를
전수 추적했음에도 **재현 가능한 단일 원인을 코드만으로 확정하지 못했다** — 아래 "요청 6"
절에 감사 결과와 가설을 순위별로 정리했고, 구현 착수 전 **실제 GUI 재현이 선행되어야
한다**(추측 금지 원칙 — CLAUDE.md/작업 지시 그대로 준수, 스파이크가 필요한 "라이브러리
선택" 상황은 아니므로 정식 스파이크 요청은 아니다).

---

## 요청 1·2·3 — 브러시 그리기/지우기 색상 + 지우기 실효성 (전부 `zone_canvas.py` 단독)

### 감사 결과

**요청 2·3은 이미 완전히 동작한다 — 신규 로직 불필요, 색상만 바꾸면 된다.**

- `ZoneCanvas._manual_strokes`(시간순 `(draw: bool, stroke)` 리스트)는
  `apply_manual_strokes()`(`zone_canvas.py:246-253`, 얇은 래퍼)를 거쳐
  `zone_metrics.apply_manual_strokes()`(`app/core/zone_metrics.py:64-80`)로 실제 적용된다.
  이 함수는 `result[stroke_mask] = draw`로 **마지막 스트로크가 우선(last-write-wins)**
  하는 순수 numpy 연산이다 — draw=False(지우기) 스트로크가 그 이전에 draw=True(그리기)로
  칠해진 픽셀이든, AI 원본 예측 픽셀이든 구분 없이 덮어써 지운다. 즉:
  - **요청 2("지우개가 실제로 추론 블랍을 지운다")**: `zone_analysis_tab._ai_and_final_masks()`
    (`app/tabs/zone_analysis_tab.py:859-877`)가 `ai_mask`(AI 예측, 블랍삭제 반영)에
    `self._canvas.apply_manual_strokes(ai_mask)`를 적용해 `final_mask`를 만들고, 이
    `final_mask`가 `_current_target_mask()`(존 퍼센티지 계산의 유일한 입력,
    `_compute_zone_percentages()` 경유)와 `_compute_zone_blob_rows()`(Excel blob 내보내기)
    **양쪽 모두**의 실제 계산에 쓰인다. 화면에만 지워진 것처럼 보이고 숫자는 그대로인
    경우는 없다 — 이미 실계산에 반영됨을 코드로 확인 완료.
  - **요청 3("브러시로 칠한 것도 지울 수 있다")**: 위 last-write-wins 구조상 시간순으로
    나중에 커밋된 지우기 스트로크는 원인이 AI든 이전 그리기 스트로크든 가리지 않고
    덮어쓴다 — 이미 성립.
- 존 재계산 트리거도 이미 올바르다: `mouseReleaseEvent`가 스트로크 종료 시
  `erase_changed`(`zone_canvas.py:711`)를 1회 emit하고, 탭이 이를
  `_recompute_zones`(`zone_analysis_tab.py:499`)와 `_save_timer.start()`(사이드카 자동저장,
  `:493`)에 연결해뒀다.

**결론**: 요청 2·3은 **색상 변경(요청 1과 동일 커밋)만으로 완료** — 별도 로직 라운드 불필요.

### 현재 색상 (변경 대상)

`zone_canvas.py`에 브러시 색이 두 곳에 인라인으로 중복돼 있다(신규 이름 상수로 승격):

- `_rasterize_stroke()` (`:329`): `QColor(0, 230, 140, 110) if draw else QColor(255, 60, 60, 110)`
  — 커밋된 스트로크를 `_stroke_overlay` 캐시에 그릴 때.
- `_paint_erase_preview()` (`:596-600`): `QColor(0, 230, 140, 110) if self._mode == "brush_draw" else QColor(255, 60, 60, 110)`
  — 진행 중인 현재 스트로크(`self._current_stroke`)를 매 프레임 그릴 때.

두 곳 다 그리기=초록(`0,230,140`), 지우기=빨강(`255,60,60`), alpha=110.

### 변경 사항

1. `zone_canvas.py` 색상 상수 영역(`:52-54`, `_COLOR_NORMAL`/`_COLOR_SELECTED`/
   `_COLOR_ZONE_HIGHLIGHT` 옆)에 신규 상수 2개 추가:
   ```python
   _COLOR_DRAW  = QColor(96, 165, 250, 110)   # 요청1 — 브러시 그리기(수동 추가), 앱 표준 accent blue(#60a5fa) 재사용
   _COLOR_ERASE = QColor(156, 163, 175, 110)  # 요청2 — 브러시 지우기, annotation_canvas.py 지우개 색(#9ca3af) 재사용
   ```
   신규 색을 발명하지 않는다 — `#60a5fa`는 `main_window.py`/`labeling_tab.py`/
   `training_tab.py`/`inference_tab.py`/`loss_chart.py` 등 앱 전역에서 이미 accent
   색으로 쓰이는 토큰(grep 확인), `#9ca3af`는 `annotation_canvas.py:1740`의 라벨링 탭
   지우개 미리보기 색(`QColor(156, 163, 175)`, alpha만 `OVERLAY_ALPHA=140` 대신 zone
   탭 기존 관례인 110 유지 — 파일 내 일관성 우선, YAGNI로 라벨링 탭과 alpha까지 완전
   통일하지는 않음)과 동일 RGB.
2. `_rasterize_stroke()` (`:329`)와 `_paint_erase_preview()` (`:596-600`) 두 곳의 인라인
   `QColor(...)` 리터럴을 `_COLOR_DRAW`/`_COLOR_ERASE`로 교체.

### 완료 기준

- `python main.py` 구동 → Zone 탭 → 추론 실행 → 브러시 그리기 모드로 칠하면 **파란색**
  반투명 원이 그려지고 커밋 후에도 유지됨.
- 브러시 지우기 모드로 (a) AI가 원래 검출한 영역, (b) 방금 브러시로 그린 파란 영역
  둘 다 칠하면 **연한 회색**으로 표시되고, 우측 "존별 타겟 클래스 비율" 목록의 % 숫자가
  즉시 갱신됨(둘 다 실제로 지워짐 재확인).
- 기존 자동 테스트(`tests/test_zone_edit_toolbar.py` 등, 색상 리터럴을 직접 검증하는
  테스트가 있다면 값 갱신) 통과.

---

## 요청 4 — 블랍 클릭 선택 (AI 블랍 + 브러시 블랍 둘 다)

### 설계 판단 (task brief의 기본값 채택)

"선택"과 "삭제"를 분리한다 — **클릭 시 하이라이트+정보 표시만**, 삭제는 기존
"연결 블랍 삭제" 모드(`blob_delete`, 클릭 즉시 삭제)를 그대로 유지한다. 이렇게 판단한
근거:

- 사용자 원문은 "선택할 수 있도록"까지만 말했다 — 삭제 재설계 요청 아님.
- 오늘 같은 세션에서 추론 탭에 이미 이 정확한 패턴(클릭→하이라이트+통계, 삭제 아님)이
  구현돼 있다(`app/core/inference_engine.py:317-339` `blob_at()`,
  `app/widgets/overlay_viewer.py:15,37-40` `pixmap_clicked`/`set_highlight_rect`,
  `app/tabs/inference_tab.py:380-413` `_on_viewer_clicked`/`_update_blob_selection_ui`).
  `ZoneCanvas`가 `OverlayViewer`를 상속하므로 `set_highlight_rect()`는 이미 상속받아
  쓸 수 있다(`ZoneCanvas.paintEvent()`가 `:507`에서 `super().paintEvent(event)`를
  최상단에서 호출해 하이라이트 렌더링이 자동으로 포함됨, 코드 확인 완료).
- 다만 추론 탭의 `pixmap_clicked`/`blob_at()`을 그대로 재사용하지는 않는다 — Zone 탭의
  "블랍" 정체성은 `inference_engine.BlobStat`(8-connectivity, 전체 클래스)이 아니라
  2026-08-31 라운드(R3, 이미 구현됨)가 확립한 `zone_metrics.compute_blob_labels()`
  (4-connectivity, **타겟 클래스 전용**, `final_mask` 기준)다 — 화면에서 편집(블랍삭제/
  브러시)하는 블랍과 Excel에 찍히는 블랍이 항상 같은 정체성을 가져야 한다는 기존 원칙
  (`zone_metrics.py:130-137` docstring)을 이번에도 그대로 따른다. `final_mask`를 쓰므로
  **AI 블랍과 브러시로 그린 블랍이 자동으로 둘 다 포함**된다(브러시 그리기는 이미
  `final_mask`에 반영되므로 별도 분기 불필요, 요청4 문구 "블랍은 추론 결과 및 브러쉬
  둘다"를 코드 재사용만으로 충족).
- 통계 계산도 신규 함수를 만들지 않는다 — `zone_metrics.zone_blob_stats()`
  (`:124-180`, R3에서 이미 구현·테스트됨)가 `(zones, ai_mask, final_mask, confidence_map)`
  를 받아 blob 단위 `ZoneBlobStat`(존이름/픽셀수/AI점수/centroid/bbox)을 전부 계산해준다.
  `zones=[]`(원이 아직 없을 때)를 넘겨도 안전하다 — `zones_from_circles([])`가 빈
  리스트를 반환하고(`zone_metrics.py:51-52`), `zone_blob_stats()`의 zone 매칭 루프는
  단순히 아무 것도 매치하지 못해 `zone_name="미분류"`로 채워질 뿐 예외가 나지 않는다
  (코드로 확인) — 원을 아직 정의하지 않은 상태에서도 블랍 선택 자체는 동작해야 하므로
  이 폴백이 유용하다.

### 변경 — `app/widgets/zone_canvas.py`

1. 신규 시그널 (기존 시그널 선언부 `:68-74` 옆에 추가):
   ```python
   blob_clicked = pyqtSignal(int, int)   # 원본 이미지 좌표 (x, y) — 요청4, circle 모드에서만 emit
   ```
2. 신규 공개 메서드 (예: `remove_selected()` 근처, "공개 API" 절):
   ```python
   def highlight_blob_bbox(self, x: int, y: int, w: int, h: int) -> None:
       """블랍 클릭 선택(요청4) — 원본 이미지 좌표계 bbox를 픽스맵 좌표계로 변환해
       상속받은 `set_highlight_rect()`(OverlayViewer)에 위임한다. 인자가 None 개념이
       필요하면 호출부가 `set_highlight_rect(None)`을 직접 부르면 된다(getter 대칭
       메서드 신설 불필요)."""
       sx, sy = self._orig_scale()
       self.set_highlight_rect(QRectF(x * sx, y * sy, w * sx, h * sy))
   ```
3. `mouseReleaseEvent()`의 기존 "드래그 없는 단순 클릭 → 존 선택" 분기
   (`:715-735`, `if self._drag_mode == "create" and self._selected_id is not None:` 블록
   내부)에서, `self.circle_selected.emit(None)` 직후 `if self._circles:` 가드 **앞에**
   한 줄 추가:
   ```python
   self.blob_clicked.emit(int(click_x), int(click_y))   # 요청4 — 원 유무와 무관하게 항상 emit
   ```
   `zone_clicked`(존 선택)는 기존처럼 `self._circles` 비어있지 않을 때만 emit되도록
   그대로 두고, `blob_clicked`는 원 존재 여부와 무관하게 항상 emit한다(블랍 선택은
   존 개념에 의존하지 않아야 하므로) — `blob_delete`/`brush_draw`/`brush_erase`/`pan`
   모드는 이 코드 경로 자체에 도달하지 않으므로(각 모드가 `mouseReleaseEvent` 최상단에서
   조기 `return`, `:692-714`) **자동으로 "circle" 모드 전용**이 된다(신규 모드 분기 불필요).

### 변경 — `app/tabs/zone_analysis_tab.py`

1. 우측 패널(`side_layout`, `:439-455`)에 `_zone_list`와 `_btn_export_single` 사이
   (`:449` 다음 줄)에 신규 라벨 추가:
   ```python
   self._lbl_selected_blob = QLabel("")
   self._lbl_selected_blob.setWordWrap(True)
   self._lbl_selected_blob.setStyleSheet("color:#fbbf24; font-size:11px;")
   side_layout.addWidget(self._lbl_selected_blob)
   ```
   `#fbbf24`(amber)는 `inference_tab.py:199`의 `_lbl_selected_blob` 스타일을 그대로
   재사용(같은 개념의 UI를 다른 탭에 이식하므로 시각 언어 통일).
2. 시그널 연결부(`:486-509` 근처)에 추가:
   ```python
   self._canvas.blob_clicked.connect(self._on_canvas_blob_clicked)
   ```
3. 신규 슬롯 (`_on_canvas_zone_clicked`/`_on_zone_row_selected` 근처, `:962-969` 뒤에 추가):
   ```python
   def _on_canvas_blob_clicked(self, x: int, y: int) -> None:
       ai_mask, final_mask = self._ai_and_final_masks()
       if final_mask is None or self._last_result is None:
           return
       h, w = final_mask.shape
       if not (0 <= y < h and 0 <= x < w) or not final_mask[y, x]:
           self._canvas.set_highlight_rect(None)
           self._lbl_selected_blob.setText("")
           return
       labels, _, _ = compute_blob_labels(final_mask)
       label_id = int(labels[y, x])
       if label_id == 0:
           self._canvas.set_highlight_rect(None)
           self._lbl_selected_blob.setText("")
           return
       circles = [Circle(cid, cx, cy, r) for cid, cx, cy, r in self._canvas.circles_with_ids()]
       zones = zones_from_circles(circles, (h, w))
       blob_rows = zone_blob_stats(zones, ai_mask, final_mask, self._last_result.confidence_map)
       blob = next((b for b in blob_rows if b.blob_id == label_id), None)
       if blob is None:
           self._canvas.set_highlight_rect(None)
           self._lbl_selected_blob.setText("")
           return
       self._canvas.highlight_blob_bbox(blob.bbox_x, blob.bbox_y, blob.bbox_w, blob.bbox_h)
       score_txt = f"{blob.ai_score * 100:.1f}%" if blob.ai_score is not None else "N/A(수동 편집)"
       self._lbl_selected_blob.setText(
           f"선택된 블랍 — 존: {blob.zone_name} · 면적 {blob.pixel_count}px · AI 점수 {score_txt}"
       )
   ```
   `compute_blob_labels()`가 `zone_blob_stats()` 내부에서 한 번 더 호출돼 라벨링이
   2회(클릭 지점 라벨 조회용 1회 + 통계 전체 계산용 1회) 수행되는 소폭의 중복 연산이
   있다 — 클릭당 1회(드래그 중 반복 호출 아님)이므로 성능 문제가 되지 않는다고 판단해
   `zone_blob_stats()` 시그니처를 바꾸는 대신 단순함을 택함(ponytail: 클릭 이벤트
   빈도가 낮아 무시 가능한 비용, 만약 클릭 반응이 체감상 느리면 `zone_blob_stats()`에
   `labels` 선택 인자를 추가해 재사용하는 최적화로 승격).
4. 선택 상태 무효화(staleness 방지, BUG-018/019류 재발 방지 원칙 재사용) — 기존
   `self._canvas.set_blob_data(...)` 호출 3곳(`:582`, `:763`, `:829`) 직후 각각에
   추가:
   ```python
   self._canvas.set_highlight_rect(None)
   self._lbl_selected_blob.setText("")
   ```
   타겟 클래스가 바뀌거나 새 이미지를 열면 라벨 id 자체가 무의미해지므로(기존
   `removed_blob_ids`/undo 스택 초기화와 동일한 이유), 이전 선택 표시도 함께 지운다.

### 완료 기준

- 추론 실행 후 "원 편집"(기본) 모드에서 AI가 검출한 영역(회색 하이라이트가 아직 없는
  녹 부분)을 클릭 → 노란 테두리 하이라이트 + "선택된 블랍 — 존: … · 면적 …px · AI
  점수 NN.N%" 표시.
- 브러시로 새로 그린(파란) 영역만 클릭 → 같은 표시 방식, "AI 점수 N/A(수동 편집)".
- 원이 없는 상태(추론만 하고 원을 아직 안 그린 상태)에서도 블랍 클릭 시 정상 동작(zone
  이름만 "미분류").
- 배경(타겟 클래스 아닌 영역) 클릭 시 하이라이트/텍스트가 비워짐.
- 블랍삭제/브러시그리기/브러시지우기/팬 모드 중에는 클릭해도 `blob_clicked`가 emit되지
  않음(기존 동작 그대로 — 회귀 없음, 특히 blob_delete 모드의 "클릭=즉시삭제" 동작이
  안 바뀌었는지 반드시 재확인).
- 타겟 클래스 전환/새 이미지 로드 시 이전 선택 하이라이트가 자동으로 사라짐.

---

## 요청 5 — 도구 버튼 재클릭 시 토글 비활성화(기본 모드로 복귀)

### 감사 결과

`_edit_toolbar`의 5개 모드 액션(`_act_circle`/`_act_brush_draw`/`_act_brush_erase`/
`_act_blob_delete`/`_act_pan`, `zone_analysis_tab.py:304-321`)은 `QActionGroup`
(`_tool_group`, `setExclusive(True)`)으로 묶여 있다. `QActionGroup`이 exclusive일 때
이미 체크된 액션을 다시 클릭하면 **체크 상태는 그대로 유지되지만 `triggered` 시그널은
여전히 emit된다**(Qt 표준 동작 — 클릭 자체는 항상 트리거되고, 그룹이 "최소 1개는
체크 유지" 불변조건만 강제한다). 즉 `_tool_group.triggered`(`:497`,
`self._on_edit_tool_changed`에 연결)만으로는 "같은 액션이 다시 클릭됐다"를 구분할
방법이 없다 — 클릭된 액션 자체를 이전 호출과 비교해 직접 추적해야 한다.

**기본 모드 = "원 편집"(`circle`)로 확정** — 새 판단이 아니라 기존 코드가 이미 3곳
(`:321` 초기화, `:583-584` 새 이미지 로드, `:764-765` 검출 클래스 없음)에서 "리셋 시
circle로 되돌린다"는 동일한 관례를 쓰고 있어 이번 요청도 그 관례를 그대로 따름.

### 변경 — `app/tabs/zone_analysis_tab.py`

1. `self._act_circle.setChecked(True)` 직후(`:321`)에 추적용 필드 추가:
   ```python
   self._active_tool_action: QAction = self._act_circle
   ```
2. `_on_edit_tool_changed()` (`:891-900`) 최상단에 재클릭 감지 삽입:
   ```python
   def _on_edit_tool_changed(self, action: QAction) -> None:
       if action is self._active_tool_action and action is not self._act_circle:
           # 요청5 — 활성 도구를 다시 클릭하면 토글 비활성화, 기본(원편집)으로 복귀.
           self._act_circle.setChecked(True)   # QActionGroup이 이전 액션을 자동으로 unchecked 처리
           action = self._act_circle
       self._active_tool_action = action
       mode = action.data()
       ...   # 이하 기존 로직 그대로(모드 문자열 기준이라 변경 없음)
   ```
   `_act_circle.setChecked(True)`는 프로그램적 호출이라 `triggered`를 재발생시키지
   않는다(Qt 규칙 — `trigger()`/사용자 클릭만 emit, `setChecked()`는 상태만 바꿈) —
   재귀 호출 위험 없음.

### 완료 기준

- 브러시그리기 클릭(활성화) → 브러시그리기 다시 클릭 → 원편집으로 돌아가고 툴바에서
  원편집 아이콘이 체크 표시됨, 캔버스에서 원 드래그/생성이 다시 동작함.
- 나머지 4개 도구(브러시지우기/블랍삭제/팬) 모두 동일하게 재클릭 시 원편집 복귀.
- 원편집 자체를 다시 클릭해도 아무 일도 없음(이미 기본 상태).
- 도구 A → 도구 B로 정상 전환(재클릭 아님)은 기존과 동일하게 동작(회귀 없음).

---

## 요청 6 (버그) — "자동 검출 이후 브러시로 결과를 조정 못 함"

### 감사 결과 — 정적 추적으로는 재현 원인을 확정하지 못함

다음 경로를 전부 추적했으나 논리적 결함을 찾지 못했다:

1. **모드 상태 머신**: `_on_edit_tool_changed()`의 순차 `set_*_mode()` 호출들이
   서로를 덮어쓰는 순서를 4가지 모드 전이(circle/brush_draw/brush_erase/blob_delete/
   pan) 전부에 대해 손으로 시뮬레이션 — 모든 경우 최종 `self._mode`가 의도한 값으로
   정확히 귀결됨을 확인(마지막에 호출되는 `set_*_mode(True)`가 항상 올바른 모드로
   덮어씀).
2. **원 자동 검출(`_btn_detect`, `_on_auto_detect()`, `:1003-1019`)**: `set_circles()`
   호출 1개뿐 — `self._mode`, `self._blob_labels`, `self._manual_strokes`,
   `_act_brush_draw`/`_act_brush_erase`/`_act_blob_delete`의 `setEnabled()` 상태 중
   **어느 것도 건드리지 않는다**. `circles_changed`/`circles_committed`가 연결하는
   슬롯(`_refresh_circle_list`/`_recompute_zones`/`_update_batch_button_state`/
   `_save_timer.start()`) 전부 확인했으나 어느 것도 `set_blob_data()`를 재호출하지
   않는다.
3. **브러시 토글 버튼 활성화 조건**: `_act_brush_draw`/`_act_brush_erase`/
   `_act_blob_delete`는 `_on_target_changed()`(`:829-831`) 내부에서만
   `setEnabled(True)`가 되고, `_setup_target_classes()`가 검출 클래스 없음(`ids`
   빈 리스트, `:766-767`) 또는 새 이미지 로드(`:585-586`)일 때만 다시 `False`로
   내려간다 — **원 자동 검출과 무관한 조건**이다.
4. **브러시 스트로크 → 존 퍼센티지 반영 경로**: 요청 2·3 절에서 이미 확인한 대로
   `apply_manual_strokes()`가 매번 신선하게(캐시 없이) `ai_mask`/`removed_blob_ids`
   /`blob_labels`를 조회해 계산하므로 stale 데이터 문제도 발견하지 못했다.

### 유일하게 발견한 실제 결함 — 좁은 엣지 케이스 (수정 권장, 그러나 주 원인 확신 낮음)

`_setup_target_classes()`(`:751-770`)에서 `self._btn_detect.setEnabled(True)`
(`:754`, 원 자동 검출 버튼)는 **함수 최상단, `ids` 빈 리스트 여부와 무관하게** 실행된다.
반면 브러시 3개 액션은 `ids`가 비어 있으면(`:759-770`) 계속 비활성 상태로 남는다.
즉 **AI가 이번 추론에서 타겟 클래스를 전혀 검출하지 못한 이미지(배경만 검출)에서는,
원(circle) 자동 검출 버튼은 계속 눌리는데 브러시 도구는 회색으로 비활성인 채로 남는다**
— "자동 검출은 되는데 브러시가 안 눌린다"는 사용자 표현과 표면적으로 정확히 일치한다.
다만 이 시나리오(AI가 타겟 클래스를 완전히 0픽셀 검출)는 흔한 경로가 아니라서(raw
argmax는 보통 노이즈만 있어도 무언가를 검출함) **확신도는 낮다** — 사용자가 실제로
이 조건에서 재현했는지 GUI로 확인이 필요하다.

이 갭 자체는(설계상으로도) 고칠 가치가 있다 — AI가 아무것도 못 찾았어도 사용자가
브러시로 처음부터 수동 표시를 할 수 있어야 자연스럽다. 그러나 이를 지원하려면
`_target_class_id`/`ai_mask`가 존재해야 하는 현재 파이프라인 전제(`_ai_and_final_masks()`
가 `self._target_class_id is None`이면 `(None, None)` 반환) 자체를 "타겟 클래스는
있지만 AI 검출 픽셀은 0개"인 합성 상태로 확장해야 하는 더 큰 설계 변경이라, **이번
라운드의 확정 수정 대상으로 포함하지 않는다** — 아래 "권장 절차"의 1차 재현에서 이
가설이 맞는 것으로 확인되면 그때 별도 설계로 승격한다(YAGNI, 확신 없는 상태에서 큰
리팩터링을 먼저 하지 않음).

### 권장 절차 (구현 착수 전 필수)

1. **실제 GUI로 재현 시도가 최우선**(추측 금지 원칙 그대로 계승) —
   `python main.py` → Zone 탭 → 체크포인트+이미지 로드 → 추론 실행 → "자동 검출"
   클릭(원 생성) → 브러시그리기/브러시지우기 클릭 → 캔버스에 드래그. 다음을 각각
   확인:
   - 툴바에서 브러시 아이콘이 실제로 체크(활성) 상태로 바뀌는가?
   - 브러시 크기 스핀박스가 활성화되는가?
   - 캔버스에 드래그 시 파란/회색 원(스탬프)이 그려지는가?
   - 우측 "존별 타겟 클래스 비율" 숫자가 갱신되는가?
   - 위 4개 전부 정상이면(감사 결과와 일치) 요청6은 **재현 불가 — 이미 해결됨**으로
     QA.md에 기록하고 종료.
2. 재현되면 실패 단계(위 4개 중 어디서 끊기는지)를 정확히 특정 — 특히 "타겟 클래스
   검출 안 됨" 조건(임계값을 매우 높게 올려 `ids`를 의도적으로 비워보는 것으로 위
   엣지케이스 가설을 직접 검증 가능)을 우선 시도할 것.
3. 엣지케이스 가설이 맞다면: `_setup_target_classes()`의 `ids` 빈 분기에서
   `_btn_detect.setEnabled(True)`도 함께 `False`로 내리는 **최소 수정**(1줄, 일관성
   확보 — "이 이미지는 AI가 아무것도 못 찾았으니 자동 검출이든 브러시든 편집할 대상
   자체가 없다"는 메시지를 `_lbl_target_info`에 이미 표시 중이므로 자연스러움)을
   적용. 사용자가 "AI가 못 찾은 걸 브러시로 새로 그리고 싶다"는 후속 요청을 하면
   그건 별도 스코프(타겟 클래스가 있어도 초기 마스크가 all-False인 합성 흐름 설계)로
   새로 기획한다.
4. 다른 실패 단계가 발견되면(위 감사가 놓친 경로), 그 정확한 재현 스텝과 함께 이
   문서를 갱신하고 그에 맞는 최소 수정을 설계 — 이번 감사가 이미 모드 전환/활성화/
   마스크 계산 3대 경로를 배제했으므로 남은 후보는 좁혀져 있다(예: Qt 위젯 포커스/
   이벤트 필터, 특정 해상도에서만 발생하는 좌표 변환 경계값 등).

### 완료 기준(라운드 완료 조건)

- 위 절차 1~2를 실행한 재현 로그(성공/실패 여부, 실패 시 정확한 단계)가 구현/검증
  로그에 남는다.
- 재현됐다면 그 근본 원인에 대한 최소 수정 + 회귀 확인(브러시/블랍삭제/원편집 5모드
  전체 골든패스)까지 완료.
- 재현되지 않았다면 QA.md에 "재현 불가 — 정적 감사·라이브 확인 모두 결함 없음"으로
  기록하고 이번 라운드는 코드 변경 없이 종료(억지로 수정하지 않음 — ponytail 원칙).

---

## 실행 순서 제안

파일 겹침 기준(같은 파일을 여러 라운드가 동시에 건드리면 diff 충돌 위험):

1. **R1 (요청1+2+3)** — `zone_canvas.py` 색상 상수 교체만, 최저 리스크, 최우선.
2. **R2 (요청5)** — `zone_analysis_tab.py` 단독, R1과 파일이 달라 병렬 가능.
3. **R3 (요청4)** — `zone_canvas.py`(R1 이후 착수 권장, 같은 파일) +
   `zone_analysis_tab.py`(R2 이후 착수 권장, 같은 파일 `_on_edit_tool_changed` 근처는
   건드리지 않아 실제 충돌은 없지만 diff 검토 단순화를 위해 순서 권장).
4. **R4 (요청6)** — 위 "권장 절차" 1(라이브 재현)부터, 다른 라운드와 독립적으로 아무
   때나 병행 가능(코드 수정이 필요할지 자체가 불확실하므로).

리더 메모(2026-09-01 leader-log)에 따르면 이 스펙의 실제 구현은 **GitHub #32(배치
병목) 수정의 검증·push가 끝난 뒤** 순서를 조정할 예정 — 같은 두 파일(`zone_canvas.py`/
`zone_analysis_tab.py`) 근처를 건드리는 작업이 동시에 진행 중이기 때문(리더가 이미
인지, 이 문서는 순서 조정 자체를 강제하지 않음).

## 결정 필요 항목

없음 — 6건 전부 task brief에서 이미 "진행" 확정됐고, 이번 감사에서 나온 설계 판단
(요청4 선택-vs-삭제 분리, 요청5 기본모드=circle)은 전부 기존 코드 관례와 정확히
일치하는 근거로 직접 결정했다. 요청6은 "결정"이 아니라 "정보 부족"(라이브 재현
필요)이므로 `docs/decisions-needed.md` 대상이 아니다(과거 GitHub #9/#16 라운드와
동일한 처리 — 질문은 남기되 착수를 막지 않음).
