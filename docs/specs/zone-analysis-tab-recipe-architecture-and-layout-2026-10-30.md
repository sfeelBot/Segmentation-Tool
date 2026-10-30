# 상/하부(Zone) 분석 탭 — "원 설정" 아키텍처 전환 + 레이아웃/성능 개선 (2026-10-30)

> 작업 위치: `D:/segmentation model-zone-analysis-tab` (브랜치 `feature/zone-analysis-tab`,
> 기준 tip `47edbd2`). 에디션 전용 기능 — main에는 반영하지 않는다.

리더가 사전 조사(코드 레벨 근거)를 제시하며 위임한 요구사항 8건(3번이 하위 3항목을
포함해 실질 9개 변경 단위). 전부 코드 직접 대조로 재확인했고, 2건(3·5번)은 기존
설계 결정을 **명시적으로 번복**한다 — 왜 번복하는지 각 절에 근거를 남긴다.

## 0. 영향 파일 한눈에

| 파일 | 영향 요구사항 |
|---|---|
| `app/tabs/zone_analysis_tab.py` | 1, 2, 3, 4(배선), 5, 6, 7, 8 — 거의 전부 |
| `app/widgets/zone_canvas.py` | 3(핵심), 4, 5 |
| `app/widgets/zone_recipe_dialog.py` | 3(핵심), 4, 5 |
| `app/core/zone_metrics.py` | 5(핵심) |
| `app/core/zone_recipe_store.py` | 5 |
| `app/core/zone_state_store.py` | 5 |
| `app/widgets/zone_batch_result_dialog.py` | 5(영향 적음, 선택적 정리) |
| `app/core/i18n.py` | 1, 3 (문구 변경/제거) |
| `QA.md` | 7 (BUG-040 갱신) |

같은 파일(`zone_analysis_tab.py`, `zone_canvas.py`)을 여러 요구사항이 공유하므로
**순차 진행을 권장**(10절 "실행 순서" 참고) — 동시 병렬 구현 시 diff 충돌 위험이 큼.

---

## 1. 레이아웃 한 줄 통합 (BUG-021 재발 방지 전제)

### 현재 상태
`zone_analysis_tab.py:263-391`. BUG-021(툴바 1줄 → 최소폭 1588px → 창이 1592×800으로
강제 확대)을 피하려고 2026-08-26에 2줄(`toolbar_row1`/`toolbar_row2`)로 분리했다
(`QA.md` BUG-021, 당시 982px까지 줄여 재검증 통과). 이후 2026-10-29 배치 단순화로
민감도 슬라이더+자동검출 버튼이 삭제돼 폭 압박이 줄었지만, 이번 요청(req3)으로
`_act_circle`(원편집 툴바 액션)도 추가로 빠져 여유가 더 생긴다.

현재 각 행의 위젯 인벤토리:
- **row1**(`ckpt_card`, 프레임): `btn_ckpt` / 점+`lbl_ckpt`(파일명, 비한정 폭) /
  `lbl_ckpt_badge`(숨김 기본) / `infer_progress`(110px, 숨김 기본) / "타겟(녹)
  클래스:" 라벨 + `target_name_edit`(120px)·`target_combo`(160px, 둘 중 하나만
  보임) / stretch / `lbl_mode`("추론 방식: sliding window (고정)", HTML) /
  `btn_run`.
- **row2**(순수 레이아웃, 프레임 없음): "AI 신뢰도:" 라벨 + `conf_slider`(90px) +
  `lbl_confidence`(32px) / "픽셀 threshold:" 라벨 + `min_px_spin`(90px) /
  `edit_toolbar`(원편집+브러시+지우개+영역삭제+pan 5액션 + 구분선 + 브러시크기
  라벨+스핀 + 구분선 + undo 액션) / stretch.

### 변경 방향
두 행을 **1행**(`ckpt_card` 프레임 그대로 유지)으로 합친다. BUG-021 재발을 막기
위해 아래 압축을 **전부** 적용한다(단순히 붙이기만 하면 재현됨 — 특히
`edit_toolbar` 자체는 이미 아이콘 전용이라 폭 문제가 아니라, 텍스트 라벨들이
문제):
1. **"AI 신뢰도:"/"픽셀 threshold:" 텍스트 라벨 제거** — 아이콘(`svg_icon`)+툴팁으로
   교체하거나, 슬라이더/스핀박스 자체에 `setToolTip()`만 남기고 라벨은 삭제.
   기존 `.tip` i18n 키(`zone.confidence_tip`/`zone.pixel_threshold_tip`)가 이미
   있어 텍스트 자산은 보존됨.
2. **`lbl_mode`("추론 방식: sliding window (고정)")를 상시 라벨에서 `btn_run`의
   툴팁으로 이동** — 항상 같은 고정값이라 매번 보여줄 필요가 낮음(정보 손실 없음,
   발견성만 호버로 낮춤).
3. **req3 적용 후 `_act_circle` 액션이 `edit_toolbar`에서 사라짐** — 자동으로
   36~44px 절약(별도 조치 불필요, 3번 선행 전제).
4. **`lbl_ckpt`(체크포인트 파일명) 폭 상한 지정 + elide** — 현재 비한정 폭이라
   긴 경로/파일명이 행 전체를 밀어낼 수 있음. `setMaximumWidth(~160)` +
   `Qt.TextElideMode.ElideMiddle`(또는 `QFontMetrics.elidedText`) 적용.
5. **`_lbl_model_info`(393-398행, 모델 준비/실패/코드필요 안내, 전체폭 별도 줄)와
   `_lbl_ckpt_badge`(282-288행, "자동" 배지) 중복 검토** — 체크포인트가 preset
   자동 로드로 성공한 "정상" 경로에서는 badge("자동")와 model_info("모델 준비됨:
   xxx")가 동시에 녹색으로 나란히 중복 정보를 보여준다(`_on_select_checkpoint`
   787-811행). **제안**: `_lbl_model_info`는 **에러/커스텀 코드 필요 상태일
   때만** 보이도록 하고, "정상 자동 준비" 상태에선 `_lbl_ckpt_badge` 툴팁에
   모델명을 얹어 숨긴다(완전 삭제는 과함 — 에러 메시지는 유용한 정보라 유지).
   디자이너가 정확한 조건/배지 문구는 조정 가능.

위 압축을 다 적용해도 폭이 빠듯할 수 있다 — **구현자는 반드시 BUG-021 검증
때와 동일한 방법으로 회귀 여부를 직접 측정**해야 한다:
```python
# offscreen, BUG-021 재검증 스크립트와 동일 패턴
tab = ZoneAnalysisTab()
assert tab.minimumSizeHint().width() <= 1280   # MainWindow 기본 폭(resize(1280,800)) 기준
```
1280px를 못 맞추면 추가로 압축하거나(예: 체크포인트 상태 dot+배지를 아이콘
하나로 통합) `QToolBar`로 전체 행 자체를 재구성해 오버플로우 시 `>>` 축소
메뉴를 쓰는 방안까지 검토(최후 수단, 과설계 가능성 있어 1차는 비권장).

### 영향
`zone_analysis_tab.py` `_build_ui()`(249-398행대) 단일 함수 범위. 신규 핵심
로직 없음(순수 레이아웃+문구 이동). `app/core/i18n.py`에 아이콘 전환으로 인해
못 쓰게 되는 라벨 키는 그대로 둬도 무해(죽은 키, 삭제는 선택).

---

## 2. 패널 비율 1:2 + 전반적 확대

### 현재 상태
- 우측 패널(`side`, 526-561행): `_circle_list`(검출된 원)와 `_zone_list`(존별
  비율) 둘 다 `stretch=1`(동일 비율, 534·540행). `side.setMinimumWidth(180)` /
  `setMaximumWidth(220)`(559-560행).
- 좌측 패널(`left`, 434-480행): `left.setMinimumWidth(180)` / `setMaximumWidth(260)`
  (478-479행).
- 중앙 캔버스는 `splitter.setStretchFactor(1, 1)`로 가변이지만 좌/우가 각각
  180~260px/180~220px로 묶여 있어 전체 폭 확장의 체감 효과가 제한적.

### 변경 방향
1. `_circle_list` stretch=1 → stretch 비율 1:2(`_circle_list`:`_zone_list`)로
   변경 — "존별 비율" 패널이 실제 결과 확인에 더 자주 쓰이므로 세로 공간을
   더 받는다. 두 리스트의 세로 합(= `side_layout` 안에서 두 리스트가 차지하는
   총 높이)은 변하지 않음(요구사항 명시) — 헤더 라벨 2개, `_lbl_selected_blob`,
   버튼 3개(`_btn_export_single`/`_btn_view_all`/`_btn_save_all_images`)의 높이는
   그대로 유지.
2. 좌측(`left`)·우측(`side`) `setMaximumWidth` 상한을 완화(또는 제거)하고
   `setMinimumWidth`만 유지 — 2026-08-20 "UI/UX 재편" 라운드에서 이미 다른
   탭(학습/추론/라벨링)에 적용한 "리사이즈 상한 완전 무제한" 결정(roadmap 124행
   확인됨)과 동일 원칙을 Zone 탭에도 맞춘다. `splitter.setSizes([200, 700, 180])`
   초기값은 유지해도 되나, 사용자가 드래그로 넓힐 수 있어야 한다는 게 핵심.
3. 1번 작업(툴바 2행→1행)으로 세로 한 행(~40~50px)이 절약되므로, 그 공간은
   `root` 레이아웃에서 `splitter`(캔버스+좌우패널 전체)로 자동 귀속된다 —
   별도 코드 조치 불필요(`QVBoxLayout`이 `root.addWidget(splitter, stretch=1)`로
   이미 가변 처리 중, 566행).

### 영향
`zone_analysis_tab.py` `_build_ui()`의 좌/우 패널 생성부(434-480, 526-561행)와
`splitter.setStretchFactor`/`setSizes`(563-566행)만 변경. 신규 로직 없음.

---

## 3. "원 설정" 아키텍처 전환 (핵심, 가장 큰 변경 — 기존 설계 번복)

### 3-0. 왜 번복인가 (기록용)
2026-10-01 전면 재설계(`docs/specs/zone-tab-redesign-2026-10-01.md`)에서 **의도적으로**
"자동 원 검출/원편집을 추론 완료 전에도 메인 캔버스에서 쓸 수 있게" 활성화 조건을
풀었다(`zone_analysis_tab.py` 707-709행 주석 "원 편집은 추론 결과와 무관하게
이미지만 로드되면 바로 쓸 수 있다"). 이번 요청은 **그 결정을 되돌리는 것** —
메인 캔버스에서는 원 편집을 완전히 제거하고, 이미 존재하는 "원(Zone) 설정..."
모달(`ZoneRecipeDialog`)을 유일한 편집 창구로 통합한다. 근거: 사용자가 실사용
중 메인 캔버스와 모달 두 곳에서 원을 건드릴 수 있는 것에 혼란을 느꼈고, 모달이
이미 자체 캔버스+자동검출+정렬+undo를 완결된 형태로 갖추고 있어 중복.

### 3-1. 메인 캔버스 원 편집 제거 — 핵심 발견과 설계

**핵심 발견 1 — "원편집(circle) 모드"는 실제로 2가지 역할을 겸하고 있다.**
`zone_canvas.py` `mousePressEvent`/`mouseReleaseEvent`(689-833행)를 보면,
`self._mode == "circle"`일 때:
- 드래그로 원을 생성/이동/반지름조절 하는 **편집** 기능과,
- 드래그 없는 단순 클릭(해제 시 `r_screen < _MIN_CREATE_R_PX`로 판정, 801-828행)을
  **"존 클릭"(`zone_clicked`)/"블랍 클릭"(`blob_clicked`, 요청4 정보 표시용)으로
  해석하는 조회(view) 기능**을 겸한다.

즉 "원편집 모드를 메인 캔버스에서 제거"는 단순히 `_act_circle` 액션 하나를
비활성화하는 문제가 아니라, **편집(생성/이동/리사이즈)과 조회(존/블랍 클릭)를
분리**해야 하는 리팩터링이다. 조회 기능(블랍 정보 표시 `_on_canvas_blob_clicked`,
존 하이라이트 `_on_canvas_zone_clicked`)은 메인 탭에서 계속 필요하다(사용자가
"뷰만 가능"이라고 한 것과 정확히 일치 — 뷰는 되지만 편집은 안 됨).

**설계 제안**: `ZoneCanvas`에 읽기전용 플래그(예: `set_editing_enabled(bool)`,
이름은 구현자 재량)를 추가한다. `False`일 때:
- `mousePressEvent`/`mouseMoveEvent`/`mouseReleaseEvent`의 `"circle"` 분기에서
  **원 생성/이동/리사이즈 로직(히트테스트, `_push_undo()`, `_drag_mode` 상태
  머신) 전부를 건너뛴다.** 대신 `OverlayViewer`가 이미 제공하는 클릭-vs-드래그
  판정(`_CLICK_TOLERANCE_PX=4.0`, `overlay_viewer.py` 99-109행, `pixmap_clicked`
  시그널)을 그대로 상속해 쓰거나, 동등한 경량 로직으로 "드래그 없었음"을
  판정해 `zone_clicked`/`blob_clicked`만 emit한다(원을 투기적으로 만들었다가
  지우는 현재의 우회 경로를 안 타도 됨 — 오히려 코드가 단순해짐).
- `keyPressEvent`의 Delete/방향키 분기(848-866행)는 `_selected_id`가 애초에
  설정되지 않으므로 자연히 no-op(별도 가드 불필요, 단 명확성을 위해 주석 권장).
- `contextMenuEvent`(886-913행) 전체를 비활성화(메뉴 자체를 띄우지 않음) —
  지름변경/이름변경/숨기기/삭제는 전부 모달 전용이 됨(단, 요구사항 7처럼 "패널
  에서 직접 이름변경"은 `_zone_list` 우클릭 메뉴(1322-1344행)로 유지 — 이건
  원 자체의 geometry 편집이 아니라 이름/숨김 메타데이터 토글이라 **편집 제거
  범위 밖으로 유지할지 자체도 디자인 확인 필요**, 아래 3-5 참고).
- `wheelEvent`의 Alt+휠 분기(869-884행)는 `self._mode=="circle"`+선택된 원이
  있어야 타므로, 선택 자체가 없어지면 자연히 죽는다(3-2 참고, 명시적 삭제
  불필요하나 가독성 위해 가드 추가 권장).

이 플래그는 **메인 탭에서만 `False`로 설정**하고, `ZoneRecipeDialog`가 생성하는
`ZoneCanvas` 인스턴스는 기본값(`True`, 기존 동작 그대로)을 유지한다 — 모달은
req3 적용 후에도 지금처럼 완전한 편집 기능을 유지해야 하므로 **역호환 기본값이
전체 동작의 안전장치**다.

브러시 그리기/지우기/블랍삭제 3개 도구(`brush_draw`/`brush_erase`/`blob_delete`
모드)는 **이번 범위 밖** — 이건 "원(zone) geometry 편집"이 아니라 "AI 검출
결과 보정"이라 메인 캔버스에 그대로 남는다(사용자 요청 원문도 "원 설정"에
한정, 검출 결과 보정 도구는 언급 없음).

### 3-2. 캔버스 헤더 "정렬" 버튼 + Alt+휠 — 자동 소멸, 확인만
`_btn_align`(502-504행)과 `wheelEvent`의 Alt+휠 반지름조절(869-884행)은 3-1이
적용되면 메인 캔버스에서 **자연히 의미를 잃는다**(원 선택이 아예 발생하지
않으므로). 조치: `_btn_align`을 메인 탭 캔버스 헤더에서 **제거**(모달
(`zone_recipe_dialog.py` 93-94, 146행)에는 이미 동일 기능이 있어 그대로 유지).
`_lbl_wheel_hint`("휠: 화면 줌 · Alt+휠: 선택한 원 지름 조절", 498-500행) 캡션도
내용이 더는 사실과 안 맞으므로 **제거 또는 전면 교체**(3-3 결과에 따라 문구
결정 — 줌까지 없어지면 캡션 자체가 필요 없어질 가능성이 높음).

### 3-3. 메인 캔버스 일반 마우스 휠(뷰 줌) 제거 — 디자인 확인 필요
사용자 원문: "이미지 뷰에서는 휠, alt 휠등의 기능은 없애줘." Alt+휠은 3-2로
자동 해소되지만, **일반 휠(화면 줌, `OverlayViewer.wheelEvent` 상속,
`zone_canvas.py` 884행 `super().wheelEvent(event)`)은 원 편집과 무관하게
모든 모드(브러시/블랍삭제/pan 포함)에서 전부 살아있는 공용 기능**이다 —
이것까지 지우면 메인 캔버스에서 확대/축소할 수단이 완전히 사라진다(대체
수단 없음 — `ZoneCanvas`엔 `+`/`-` 버튼이나 리셋줌 버튼이 따로 없음).

**리더 판단(위임 메시지 원문)**: "일반 줌도 제거가 맞다고 보되, 확대/축소
수단이 전혀 없어지는 게 맞는지 디자이너가 짚고 넘어가게 할 것 — 필요하면
리더에게 재확인 요청." 기획 단계에서는 결정하지 않고 아래와 같이 처리한다:
- **기본 가정(구현 착수 가능선)**: 메인 캔버스는 `ZoneCanvas`에 신설할 동일
  플래그(`set_editing_enabled(False)`) 또는 별도 플래그로 `wheelEvent` 자체를
  전부 무시(swallow)하도록 구현 — 사용자 원문을 가장 직접적으로 만족.
- **단, `docs/decisions-needed.md`에 등록**(이 스펙 작성과 함께 등록 완료) —
  디자이너가 검토 중 "확대 수단이 전혀 없으면 블랍 세부 확인이 불편하다"는
  문제를 발견하면, 대체 수단(예: 더블클릭 리셋줌, 키보드 `+`/`-`, 또는
  "뷰 줌만 예외적으로 유지하고 Alt+휠만 제거") 여부를 사용자에게 재확인하도록
  명시.
- 모달(`ZoneRecipeDialog`)의 캔버스는 **영향 없음** — 거기는 편집 작업이라
  확대가 필수, 기존 줌 그대로 유지.

### 3-4. 레시피 저장 시 확인 팝업 추가
현재 `ZoneRecipeDialog._on_apply()`(235-237행)는 "메인 탭에 적용" 버튼을 누르면
바로 `accept()`하고 끝 — 레시피로 저장할지 묻지 않는다. 레시피 저장은 별도로
사용자가 `_name_edit`에 이름을 입력하고 `_btn_save_recipe`를 눌러야만 일어난다
(195-210행). 요구사항: **"적용"(또는 닫기) 시 레시피로 저장할지 묻는 확인
팝업을 추가**.

**설계**: `_on_apply()` 맨 앞에 `QMessageBox.question()`을 추가 —
- "예" → 현재 `_on_save_recipe()`와 동일한 저장 로직을 호출(이름이 비어있으면
  기존처럼 경고, 이름 기본값은 이미 `f"{date.today():%Y%m%d}_recipe"`로 채워져
  있어 사용자가 그대로 눌러도 저장됨) 한 뒤 `accept()`.
- "아니오" → 저장 없이 그대로 `accept()`(현재 동작과 동일).
- "취소" → 모달을 닫지 않고 그대로 머무름(실수로 적용 눌렀을 때 되돌릴 수
  있게).
저장 포맷/경로(`data/zone_recipes/<name>.json`, `zone_recipe_store.py`)는
**변경 없음** — 이미 필수 저장 기능으로 존재, 이번엔 팝업 트리거만 추가.

### 3-5. 핵심 발견 2 — 모달이 "현재 이미지의 기존 원"을 반영하지 않는다
`_on_open_recipe_dialog()`(1475-1496행)를 보면, 모달을 열 때 현재 이미지에
원이 이미 있으면 "교체하시겠습니까" 확인은 받지만(1480-1487행), **모달 자체는
`existing`(현재 캔버스의 실제 원)을 전달받지 않고** `ZoneRecipeDialog.__init__`이
`_load_most_recent()`(166-178행)로 **디스크의 가장 최근 레시피 파일**을 불러와
시작한다. 즉 지금은 "현재 화면에 떠 있는 원"과 "모달이 처음 보여주는 원"이
서로 다른 소스다 — 원 편집이 메인 캔버스에서도 가능했던 지금까지는 이게
큰 문제가 아니었지만(모달은 "일괄 적용 기준 원 재설정" 용도로만 쓰였고, 그냥
각 이미지를 메인 캔버스에서 직접 미세조정하면 됐음), **req3로 메인 캔버스
편집을 없애면 모달이 유일한 편집 경로가 되므로, 이 간극이 실사용 흐름을
깨뜨린다**: 사용자가 이미지 A에서 원을 몇 개 조정해두고, 나중에 다시 "원
설정..."을 눌러 미세조정을 이어가려 하면 자신이 만든 원이 아니라 엉뚱한
(가장 최근에 저장된) 레시피가 뜨게 된다.

**필수 동반 수정(req3의 일부, 선택 사항 아님)**: `_on_open_recipe_dialog()`가
이미 들고 있는 `existing = self._canvas.get_circles()`(1479행)를
`ZoneRecipeDialog`에 초기 상태로 전달한다. `ZoneRecipeDialog.__init__`에
신규 매개변수(예: `initial_circles: list[tuple] | None = None`)를 추가 —
비어있지 않으면 `_load_most_recent()` 대신 이걸로 캔버스를 채우고, 비어있으면
(현재 이미지에 원이 아예 없던 경우) 기존처럼 최근 레시피 자동 로드로 폴백한다
(완전히 새 이미지를 여는 흐름은 유지). `outer_name`도 이미 같은 방식으로
전달되고 있으니(1489행 `self._canvas.outer_name()`) 동일 패턴.

### 영향 파일/함수 종합 (3번)
- `app/widgets/zone_canvas.py`: 신규 플래그(`set_editing_enabled`류) +
  `mousePressEvent`/`mouseMoveEvent`/`mouseReleaseEvent`/`keyPressEvent`/
  `wheelEvent`/`contextMenuEvent` 분기 추가(617-976행대 전반), 디폴트는 역호환
  (모달 쪽 무변경 보장).
- `app/tabs/zone_analysis_tab.py`: `_btn_align`/`_lbl_wheel_hint` 제거(493-505행),
  `_act_circle` 제거(348-352, 365-376행), `ZoneCanvas` 생성 후
  `set_editing_enabled(False)` 호출 추가, `_on_open_recipe_dialog()`에
  `existing` 전달(1488-1490행).
- `app/widgets/zone_recipe_dialog.py`: `__init__` 신규 매개변수 +
  `_load_most_recent()` 분기, `_on_apply()` 저장 확인 팝업(235행대).
- `app/core/i18n.py`: `zone.wheel_hint`/`zone.btn_align`/`zone.align_tip`
  (메인 탭 쪽 사용처 제거, 모달 쪽 키는 별도 — 모달은 자체 `zone_recipe.*`
  키를 쓰므로 공유 키가 아님, 확인 필요) + 레시피 저장 확인 팝업 신규 키
  2~3개.
- **버튼/모달 명칭**: 이미 `zone.btn_recipe` = "원(Zone) 설정...",
  `zone_recipe.window_title` = "영역(Zone) 설정 — 레시피"로 **원 설정 브랜딩에
  이미 근접**해 있음 — 구조적 리네임 불필요, 문구 미세조정(괄호/말줄임표 등)만
  디자이너 재량.

---

## 4. 링/중심부 직접 설정 + 네이밍 (3번의 하위 보강)

### 현재 상태와 한계
존 이름은 "귀속된 원"의 `name` 필드로만 간접 결정된다(`zone_metrics.py`
100-106행 — 중심부존은 최소 반지름 원의 `name`, 링 i는 그 링의 바깥쪽 경계
원의 `name`). 원 자체는 우클릭 메뉴로 리네임 가능(`zone_canvas.py` 936-951행,
`_prompt_name_change`)하지만, **경계선(원의 테두리)에 커서를 정확히 맞춰야만
우클릭 메뉴가 뜬다**(`contextMenuEvent`가 `_hit_test()`로 테두리/중심 판정,
563-572행 `_BORDER_HIT_PX=8.0`/`_CENTER_HIT_PX=10.0`) — 링의 **내부 영역**
(색칠된 띠 전체)을 클릭해서는 리네임 메뉴에 도달할 수 없다. 메인 탭의
`_zone_list` 패널(존별 비율 목록)은 이미 행 우클릭으로 이름변경이 가능하지만
(1322-1344행), 이건 "캔버스 위의 직접 클릭"이 아니라 "사이드 패널의 목록
항목"이라 사용자가 찾아내기 어렵다는 게 이번 요청의 핵심 불만이다.

### 요구사항
**"원 설정" 모달 화면에서, 각 결과 존(중심부/각 링) 영역 자체를 직접
클릭/선택해서 이름을 바로 지정**할 수 있는 더 직접적인 상호작용을 설계한다 —
예: 색칠된 영역을 클릭하면 그 존이 선택되고 이름 변경 UI가 뜨는 식. 경계선만
클릭 가능한 현재 방식보다 발견 가능성을 높이는 것이 핵심.

### 기획이 확정하는 것 / 디자이너에게 남기는 것
**확정(기술적 매핑, 이미 코드에 존재)**: "클릭한 좌표가 속한 존 인덱스"는
`ZoneCanvas._zone_index_at(x, y)`(580-589행, 반지름 오름차순 기준 포함된 원
개수로 판정)로 이미 계산 가능하고, **존 인덱스 i는 반지름 오름차순 정렬된
원 리스트의 같은 인덱스 i와 1:1 대응**한다(`zone_analysis_tab.py`
`_recompute_zones()` 1294-1299행이 이미 이 매핑을 `circle_id =
circles_raw[zone_index][0]`으로 실제 사용 중). 즉 "영역 클릭 → 해당 존의
이름을 바꾼다"는 "영역 클릭 → 좌표가 속한 존 인덱스 계산 → 같은 인덱스의
원을 찾아 그 원의 `name`을 변경"으로 구현 가능하며, **5번(바깥쪽 존 제거)이
먼저 적용되면 이 매핑이 예외 없이 항상 성립**한다(현재는 바깥쪽 존만 원이
없어 예외 처리가 필요했음 — `_prompt_rename_outer_zone()`이 바로 그 예외
처리, 5번 적용 후 삭제 대상).

**디자이너 재량(기획이 결정하지 않음)**: 정확한 인터랙션 — 클릭 즉시 인라인
이름 입력 vs 클릭 → 하이라이트 → 별도 "이름 변경" 소형 버튼/팝업 노출 vs
기존 `QInputDialog` 그대로 재사용(클릭 트리거만 바뀜) 등. 모달에만 적용되는
기능이라(메인 캔버스는 3번으로 조회 전용이 됨) 모달의 다른 UI 요소(민감도
슬라이더, 정렬 버튼, 레시피 콤보)와 레이아웃이 충돌하지 않게 디자이너가
확정한다.

### 영향
`app/widgets/zone_canvas.py`(영역 클릭 판정 — 기존 `_zone_index_at()` 재사용
가능, 신규 시그널 필요 시 `zone_clicked`를 모달에서도 연결하거나 신규 시그널
추가), `app/widgets/zone_recipe_dialog.py`(현재 `circles_changed`만 연결돼
있음 — `zone_clicked`/신규 시그널 연결 + 이름 변경 UI 신설).

---

## 5. "바깥쪽" 존 완전 제거 (기존 설계 결정 번복)

### 왜 번복인가 (기록용)
2026-10-29 배치 단순화 작업에서 **의도적으로** "바깥쪽은 hidden 토글 범위
밖"이라고 결정했다(`zone_metrics.py` 106행 주석 "바깥쪽은 hidden 토글 범위
밖(의도적 축소)", `Zone.hidden` docstring 36행도 "바깥쪽 존은 원이 없어 항상
False"). 이번 요청은 **그 결정을 번복**한다 — 더는 "숨김 가능한 특수 존"이
아니라 **존 자체를 생성하지 않는다**(화면/Excel/배치결과표/전체결과보기
전부에서 사라짐, 비율 계산 분모에서도 제외). 근거: 사용자가 실사용에서
바깥쪽(원 밖 전체 영역)을 분석 대상으로 쓴 적이 없고, 항상 숨기거나 무시해야
했던 존재라는 걸 확인했다(사용자 명시 확인).

### 현재 구조
`zone_metrics.py` `zones_from_circles()`(85-107행): 원 N개 → 존 N+1개(중심부
+ 링 N-1개 + 바깥쪽 1개). 바깥쪽 마스크는 `~masks[-1]`(가장 큰 원 밖 전체,
106행). `outer_name`(스칼라, 원에 귀속 안 됨)이 이 바깥쪽 존의 커스텀 이름
경로로 2026-10-29에 신설됐다 — `ZoneCanvas._outer_name`/`outer_name()`/
`set_outer_name()`/`rename_outer_zone()`/`_prompt_rename_outer_zone()`
(zone_canvas.py 99, 175-193, 953-962행), `get_state()`/`set_state()`의
`outer_name` 키(451, 474, 493행), `zone_state_store.py`(21-26, 35, 65행)·
`zone_recipe_store.py`(33-46, 73행)의 top-level `outer_name` 필드,
`zone_analysis_tab.py`의 `_ZoneCircleLayoutWorker`(121-145행, 배치 적용 시
outer_name도 함께 스케일 없이 복사)와 각 `zones_from_circles()` 호출부
(181, 1192, 1363행)까지 **전부 "바깥쪽 존 커스터마이즈"를 위해 2026-10-29에
추가된 코드**다.

### 변경 방향
1. `zones_from_circles()`(85-107행): 마지막 `zones.append(Zone(n, outer_name
   or "바깥쪽", ~masks[-1], False))` 줄을 **제거**. 원 N개 → 존 N개(중심부 +
   링 N-1개)로 변경. `outer_name` 매개변수 자체도 삭제(더는 쓸 곳이 없음).
2. **파티션 불변식이 깨짐에 주의**: 기존 self-check(`zone_metrics.py`
   382-392행)는 "존들의 합집합 = 전체 이미지, 겹침 없음"을 검증했는데, 바깥쪽
   제거 후엔 **원 밖 영역이 어떤 존에도 속하지 않는 게 의도된 동작**이다 —
   self-check를 "원 안쪽 영역만 파티션, 원 밖은 어느 존에도 없음"으로
   다시 써야 한다(단순 삭제가 아니라 단언문 자체의 의미를 바꿔야 함).
3. **blob 배정 영향 — 오히려 자연스러워짐**: `zone_blob_stats()`(170-226행)는
   이미 "어떤 존에도 속하지 않으면 '미분류'"라는 폴백이 있다(208행
   `zone_name = "미분류"`, 실제로는 존들이 전체를 파티션해 지금까진 도달
   불가능한 코드였음). 바깥쪽 존이 없어지면 **원 밖에 그려진 블랍(수동
   브러시로 원 밖에 그린 경우 등)은 자동으로 "미분류"로 떨어진다** — 신규
   로직 불필요, 기존 폴백이 그대로 의미를 갖게 됨.
4. **`ZoneCanvas`에서 제거**: `_outer_name` 필드, `outer_name()`/
   `set_outer_name()`/`rename_outer_zone()`/`_prompt_rename_outer_zone()`
   메서드, `get_state()`/`set_state()`의 `outer_name` 키, `_zone_index_at()`의
   "n=바깥쪽" 케이스(반환값 범위가 0..n-1로만 좁아짐 — 점이 모든 원 밖에
   있으면 **존이 없다는 뜻이므로 `zone_clicked`를 emit하지 않아야 함**,
   `mouseReleaseEvent` 825-828행의 `if self._circles:` 가드를 `if
   zone_idx < n:`류로 보강), `_paint_zone_highlight()`의 `idx == n` 분기
   (634-637행, 바깥쪽 하이라이트 그리기) 제거.
5. **저장소에서 제거**: `zone_recipe_store.save_recipe()`/`load_recipe()`의
   `outer_name` 매개변수/키(33-46, 68-74행) 및 self-check(106-124행) 삭제.
   `zone_state_store.save_state()`/`load_state()`의 `outer_name` 키(21-36,
   60-69행) 및 self-check(79-116행) 삭제. **역호환 주의**: 이미 디스크에
   저장된 구버전(2026-10-29 포맷) 레시피/사이드카 파일에 `outer_name` 키가
   남아있을 수 있음 — `load_recipe()`/`load_state()`가 그 키를 **그냥
   무시**하면 되므로(현재도 `payload.get("outer_name")`으로 안전하게 읽고
   있어 키 추가엔 관대함 — 단순히 읽은 값을 쓰지 않으면 됨) 마이그레이션
   스크립트는 불필요(YAGNI).
6. **`zone_analysis_tab.py`에서 제거**: `_ZoneCircleLayoutWorker`의 `outer_name`
   매개변수/저장(121, 125, 145행), `_compute_zone_rows()`의 `outer_name`
   매개변수(163, 178-182행), 모든 `zones_from_circles(..., outer_name)` 호출의
   마지막 인자(1192, 1363행), `_on_view_all_results()`/`_on_batch_process()`류의
   `outer_name` 전달 코드(1422-1423, 1489, 1496, 1587, 1617행),
   `_on_zone_list_context_menu()`의 `circle_id is None`(바깥쪽) 분기(1333-1342행,
   이제 모든 `_zone_list` 행이 circle_id를 가지므로 분기 자체가 불필요해짐 —
   단순화됨).
7. **`zone_recipe_dialog.py`에서 제거**: `outer_name` 매개변수/`_initial_outer_name`
   /`set_outer_name()` 호출/`result_outer_name()`(50-55, 75, 177, 191, 205,
   247-248행) 전부.
8. **선택적 정리(필수 아님)**: `zone_name_sort_key()`(zone_metrics.py 229-241행)의
   `"바깥쪽"` 특수 케이스(237-238행)는 이제 도달 불가능한 코드가 되지만,
   사용자가 직접 "바깥쪽"이라는 이름을 커스텀으로 붙이는 극단적 케이스에서도
   안전하게 동작하므로 **그대로 둬도 무해**(제거는 구현자 재량, YAGNI 관점에서
   건드리지 않는 것을 권장).

### 영향 요약 (파일별)
`zone_metrics.py`(핵심 로직+self-check 재작성), `zone_canvas.py`(필드/메서드
제거+범위 가드), `zone_recipe_store.py`/`zone_state_store.py`(필드 제거+
self-check 수정), `zone_recipe_dialog.py`(매개변수 제거), `zone_analysis_tab.py`
(모든 호출부 인자 정리 — 가장 많은 호출부가 모여 있어 **4번/6번/7번 작업
전에 먼저 끝내는 것을 강하게 권장**, 아래 10절).

---

## 6. "전체 결과 보기" 비동기화

### 현재 상태
`_on_view_all_results()`(`zone_analysis_tab.py` 1397-1440행)는 `self._img_list.paths()`
전체를 **동기 for문**으로 순회하며 이미지마다 `_compute_zone_rows()`(161-187행,
내부에서 `compute_blob_labels` cv2 connected-components + `zones_from_circles`
+ `zone_stats`/`zone_blob_stats` 호출)를 메인 스레드에서 실행한 뒤
`ZoneBatchResultDialog(...).exec()`로 모달을 띄운다(1440행). 이미지가 많으면
이 루프 동안 GUI가 그대로 멈춘다.

### 변경 방향
기존 배치 처리의 비동기화 패턴(`_ZoneCircleLayoutWorker`, R-PERF-2의
`_ZoneBatchPostWorker` 전례)을 그대로 따른다 — **신규 QThread 워커**(예:
`_ViewAllResultsWorker`)를 만들어:
- 입력: `self._img_list.paths()`, `self._results`(dict, 이미 메모리에 있는
  `InferenceResult`), `self._target_class_id`, 현재 이미지의 live 캔버스
  circles(메인 스레드에서 미리 읽어 워커에 넘김 — 워커 스레드에서 Qt 위젯
  접근 금지), 다른 이미지들의 `zstate.load_state()` 결과(파일 I/O라 워커
  스레드에서 수행 가능).
- 워커 내부에서 `_compute_zone_rows()`(순수 함수, Qt 의존성 없음 — 이미
  `zone_metrics.py`만 사용)를 이미지마다 호출해 `all_rows`/`all_blob_rows`를
  누적.
- `finished`/`result_ready` 시그널로 메인 스레드에 결과를 전달 →
  `ZoneBatchResultDialog(...).exec()`는 **메인 스레드에서 워커 완료 후** 호출.
- 이미지 수가 적으면(예: 10장 이하) 오버헤드가 더 커질 수 있으므로, **진행률
  팝업은 "오래 걸릴 경우"에만**(요구사항 원문) — 기존
  `_on_batch_process()`의 `QProgressDialog` 패턴(모달, 취소 가능)을 재사용하되,
  이미지 수가 적으면 워커가 즉시 끝나 팝업이 거의 안 보이는 것도 허용(별도
  "짧으면 생략" 분기는 과설계, YAGNI — 기존 배치 처리 팝업도 그런 분기가 없음).
- 취소 버튼 필요 여부: 기존 배치 워커들과 달리 이 작업은 **디스크/모델에
  쓰기 작업이 없는 순수 조회**라 취소해도 잃을 게 없음 — 취소를 누르면 그냥
  워커를 `requestInterruption()`하고 다이얼로그를 띄우지 않고 종료(단순).
- `_flush_state()`(현재 이미지 사이드카 동기 flush, 1405행)는 **워커 시작
  전에 메인 스레드에서 먼저** 수행(현재와 동일한 순서 보장 필요 — 비교 대상
  최신화).

### 영향
`zone_analysis_tab.py` `_on_view_all_results()`(1397-1440행) 교체, 신규 워커
클래스 1개 추가(`_ZoneCircleLayoutWorker`/`_ZoneInferenceWorker`와 같은 파일
상단 영역). `_compute_zone_rows()`(161-187행) 자체는 **이미 순수 함수**라
변경 불필요(QThread에서 그대로 호출 가능) — **단, 5번(바깥쪽 제거) 적용 후
시그니처가 바뀌므로(`outer_name` 매개변수 삭제) 5번을 먼저 끝내고 이 작업을
하는 게 안전**(10절 순서 참고).

---

## 7. 이미지 전환 잔여 성능 이슈 마무리 (BUG-040 후속)

### 현재 상태 (QA.md BUG-040 전문 요약)
R-PERF-1(`_target_cache`, `zone_analysis_tab.py` 203-209행)로 캐시 적중 시에도
대형 이미지(5472×3648) 재선택이 약 462ms 걸린다(원래 921ms에서 절반으로
개선됐으나 여전히 체감됨, verifier 2026-10-07 실측). cProfile 분해(462ms
기준):
1. `set_state()`가 트리거하는 `_recompute_zones()` 1회 — 약 0.22초
   (`zone_blob_stats`/`zone_stats`/`disk_mask` numpy 연산).
2. `np.unique(raw_class_map)`(타겟 클래스 재구성, `_setup_target_classes()`) —
   약 0.09초(2천만 픽셀 규모에서 해시 기반 유니크 연산이 여전히 느림).
3. 원본 디코드 + 썸네일 생성(`_on_list_image_selected()`의 `Image.open()` +
   `.convert("RGB")` + `.thumbnail()`) — 약 0.1초, **이미지를 재선택할 때마다
   디스크에서 다시 읽고 다시 디코드** — 캐시가 전혀 없음(원인 파일:
   `zone_analysis_tab.py` 697-705행).

### 변경 방향 (리더 요청 범위 — "추가로 줄이는 방안 제시")
1. **(최우선, 저위험) 원본 디코드+썸네일 결과 캐싱** — `_on_list_image_selected()`
   가 매번 `Image.open()`을 호출하는 걸 경로별 캐시로 전환. 기존
   `_target_cache`(OrderedDict LRU, BUG-039 패턴)와 **같은 상한/퇴출 정책을
   공유하는 별도 캐시**(예: `_preview_cache: OrderedDict[Path, tuple[tuple[int,int],
   QPixmap]]`, 키=경로, 값=(원본 w·h, 미리보기 QPixmap))를 신설 — `_target_cache`에
   InferenceResult까지 같이 얹으면 "추론 결과 없는 이미지" 재선택 시에도
   캐시가 필요하므로 **별도 캐시가 적절**(추론 전/후 양쪽에서 쓰이는 데이터
   생명주기가 다름). 캐시 적중 시 디코드/리사이즈 완전히 스킵, 미스 시엔
   현재 로직 그대로 수행 후 캐시에 적재. `_on_images_removed()`에서 함께
   evict(기존 `_target_cache.pop()` 패턴 재사용).
2. **(저위험) `detected_ids` 경로별 캐시** — `np.unique(raw_class_map)` 결과를
   `InferenceResult` 자체 또는 `self._results`와 나란히 두는 보조 dict에
   1회만 계산해 캐시. `self._results`가 이미 세션 메모리에 상주하므로,
   새 추론 실행 시(`_on_run()`, `self._results.clear()`) 함께 비우면 정합성
   보장(기존 `_target_cache.clear()` 바로 옆에 한 줄 추가).
3. **(중위험, 측정 후 판단) `_recompute_zones()` 내부 numpy 연산 자체 최적화** —
   QA.md가 이미 "zone_stats/zone_blob_stats/disk_mask 자체의 최적화는 범위
   밖(함수 내부 최적화는 별도 과제)"라고 명시했을 만큼 더 깊이 들어가는
   작업이다. 이번 라운드에서 제안 가능한 저risk 개선 1건: `_compute_zone_percentages()`
   /`_compute_zone_blob_rows()`가 **둘 다 내부에서 각자 `compute_blob_labels()`를
   호출하는지 재확인** — 호출부가 같은 마스크로 중복 호출 중이면 1회로
   합쳐 공유(이미 BUG-040 B가 `zones_from_circles()` 공유로 같은 종류의
   중복을 제거한 전례가 있음, 같은 원칙 재적용). 이 이상의 알고리즘적
   변경(예: `disk_mask`를 매번 계산하지 않고 원 좌표가 바뀌지 않으면
   캐시)은 **실측 없이 이번에 설계하지 않음** — 구현 후 cProfile로 462ms가
   얼마나 줄었는지 먼저 측정하고, 여전히 체감되면 후속 라운드에서 추가
   스파이크 여부를 리더가 판단.
4. **(보류, YAGNI) 백그라운드 스레드로 썸네일 생성** — 리더가 제시한
   선택지 중 하나지만, 위 1~3번(순수 캐싱)만으로 이미지 재선택 시 비용의
   대부분(디코드+썸네일 0.1초 + np.unique 0.09초, 합쳐서 462ms의 약 40%)이
   사라진다. 비동기 스레딩은 "같은 이미지를 처음 여는 그 1회"에만 도움이
   되고, 그조차 UI 갱신 순서를 비동기로 관리해야 하는 복잡도가 생긴다 —
   **1~3번 적용 후 실측 결과를 보고도 체감 지연이 남으면 그때 고려**(이번
   라운드에서 구현하지 않음, 과설계 방지).

### QA.md 갱신
BUG-040 행에 이번 라운드 조치 내용(캐시 2종 추가, 예상 절감폭)과 **재검증
필요**(verifier가 실 GPU로 462ms → 목표치 측정) 상태를 덧붙인다 — 완전히
Closed로 바꾸지 않음(3번 항목처럼 더 깊은 최적화 여지가 남아있다고 이미
명시돼 있으므로, 이번 라운드로 완전히 해소됐다고 과장하지 않는다).

### 영향
`zone_analysis_tab.py`만 — `__init__`(신규 캐시 필드), `_on_list_image_selected()`
(697-705행 캐시 조회/적재), `_setup_target_classes()`(detected_ids 캐시),
`_on_run()`/`_on_images_removed()`(캐시 clear/evict 동반 수정).

---

## 8. "현재 이미지만 추론" 버튼 신규 추가

### 현재 상태
`_btn_run`(274-314행 토글 영역, 핸들러 `_on_run()` 855-903행) 하나뿐이고,
`_on_run()`의 881행 `paths = self._img_list.paths() or [self._image_path]`가
리스트가 로드돼 있으면(이미지 2장 이상) **항상 리스트 전체**를 추론 대상으로
잡는다(`InferenceImageList`가 `count() > 1`일 때만 보이므로, "리스트 로드됨" =
"이미지가 2장 이상"과 동치, 455행).

### 변경 방향
`_btn_run` **왼쪽**(1번 요청으로 레이아웃이 1행으로 합쳐진 뒤의 같은 버튼
클러스터, 기존 요청 원문 위치 "같은 `ckpt_card` 행, 305행 스트레치 뒤")에
신규 버튼(`_btn_run_current`, 예: 아이콘+"현재 이미지만")을 추가한다.
- 클릭 핸들러는 `_on_run()`과 거의 동일하되, `paths` 결정 로직만 차이:
  **항상 `[self._image_path]`만** 사용(리스트 존재 여부 무관). 나머지
  (체크포인트/모델/원 존재 확인 다이얼로그, 진행바, worker 생성, 결과
  처리, step indicator 갱신)는 완전히 동일 경로를 재사용하는 게 바람직 —
  `_on_run()`을 `paths: list[Path]`를 받는 내부 헬퍼로 쪼개고
  (`_run_inference(paths: list[Path])`), 두 버튼의 클릭 핸들러가 각각
  `paths = self._img_list.paths() or [self._image_path]` / `paths =
  [self._image_path]`만 계산해 같은 헬퍼를 호출하는 구조를 권장(중복 코드
  방지, DRY).
- 이미지가 로드돼 있지 않을 때(`self._image_path is None`)는 기존과 동일하게
  경고 다이얼로그(857행)로 막힘 — 신규 버튼도 같은 가드를 그대로 상속.
- `self._results.clear()`/`self._target_cache.clear()`(882-883행)를 "현재
  이미지만" 추론 시에도 그대로 전체 clear할지, 현재 이미지 항목만 선택적으로
  갱신할지는 **구현 세부 판단**(전체 clear가 더 단순하고 기존 "새 추론
  세션" 의미와 일관되지만, "리스트의 다른 이미지 결과까지 날린다"는
  부작용이 생김 — 원문 요청이 "현재 이미지만 추론"이라는 범위이므로,
  **다른 이미지의 기존 결과(`self._results`)는 보존하고 현재 이미지 항목만
  갱신**하는 쪽을 권장, `_target_cache`도 현재 이미지 키만 무효화). 이건
  "전체 추론" 버튼과 명확히 구분되는 핵심 가치이므로 **반드시 다른 이미지
  결과를 보존해야 함**(전체 clear하면 "현재 이미지만"이라는 이름과 실제
  동작이 어긋나는 버그가 됨 — 구현자 주의 필요).

### 영향
`zone_analysis_tab.py`: `_build_ui()`(신규 버튼), `_on_run()`(헬퍼로 분리),
i18n 신규 키 1~2개(`zone.run_current`류). 1번 작업(레이아웃 병합) 이후에
진행하면 같은 행을 두 번 건드리지 않아도 됨(10절 순서 참고).

---

## 9. 종합 영향 파일 표 (요구사항별)

| 요구사항 | zone_analysis_tab.py | zone_canvas.py | zone_recipe_dialog.py | zone_metrics.py | zone_recipe_store.py | zone_state_store.py | i18n.py |
|---|---|---|---|---|---|---|---|
| 1 레이아웃 병합 | ✅(핵심) | – | – | – | – | – | ✅(라벨→툴팁) |
| 2 패널비율/확대 | ✅(핵심) | – | – | – | – | – | – |
| 3 아키텍처 전환 | ✅(배선) | ✅(핵심) | ✅(핵심) | – | – | – | ✅ |
| 4 직접 네이밍 | △(배선) | ✅ | ✅ | – | – | – | △ |
| 5 바깥쪽 제거 | ✅(호출부 다수) | ✅ | ✅ | ✅(핵심) | ✅ | ✅ | – |
| 6 비동기 전체보기 | ✅(핵심) | – | – | – | – | – | – |
| 7 성능 캐싱 | ✅(핵심) | – | – | – | – | – | – |
| 8 현재이미지추론 | ✅(핵심) | – | – | – | – | – | ✅ |

---

## 10. 실행 순서 제안 (의존관계 기준)

```
5(바깥쪽 제거, 데이터모델 기반)
  → 3(아키텍처 전환: 편집/조회 분리 + 모달 초기상태 + 저장확인팝업)
    → 4(직접 네이밍, 3의 모달 전제 + 5의 1:1 매핑 단순화 전제)
  → 6(비동기 전체보기, _compute_zone_rows 시그니처가 5로 먼저 안정화돼야 함)
  → 7(성능 캐싱, zones_from_circles 호출부가 5로 먼저 안정화돼야 함)
1(레이아웃 병합, 3이 끝나야 _act_circle 제거분까지 반영돼 최종 폭 확정)
  → 2(패널비율/확대, 1의 세로공간 절약을 받음)
  → 8(현재이미지 버튼, 1이 합친 행에 추가하는 게 재작업 없음)
```

**근거**:
- **5 → 3/6/7**: `outer_name` 매개변수가 `zones_from_circles()`/
  `_compute_zone_rows()`/`ZoneCanvas`/저장소 양쪽에 깊게 얽혀 있어, 5번을
  먼저 끝내야 3·6·7이 건드릴 함수 시그니처가 안정적이다(먼저 안 하면 세
  작업이 전부 같은 시그니처를 두 번 고치게 됨).
- **3 → 4**: 4번은 "원 설정 모달이 유일한 편집 창구"라는 3번의 전제 위에서
  설계되는 상호작용이다. 3번이 먼저 끝나 모달이 "현재 이미지의 실제 원"으로
  시작하는 동작(3-5)이 갖춰져야, 4번의 "영역 클릭 → 이름변경"이 실제 그
  이미지의 원을 대상으로 동작한다.
- **1 → 2, 1 → 8**: 1번이 두 행을 한 행으로 합치고 `_act_circle`을 제거하는
  작업이라, 2번(세로 공간 재분배)과 8번(같은 행에 버튼 추가)을 1번보다
  먼저 하면 diff가 서로 겹쳐 재작업이 생긴다.
- **6, 7은 5 이후 서로 독립** — 다른 함수 영역(`_on_view_all_results` vs
  `_on_list_image_selected`/`_setup_target_classes`)이라 **병렬 구현 가능**.
- **1/2/8 그룹과 3/4 그룹, 6, 7 — 서로 다른 함수/레이아웃 영역**이라 5번
  완료 후에는 **최대 3갈래 병렬**(③3+4 / ①1+2+8 / 6 / 7 — 엄밀히는 4갈래)
  까지 가능하나, `zone_analysis_tab.py` 한 파일에 전부 몰려 있어 실제
  동시 구현 시 diff 충돌 가능성이 높다 — **리더 판단으로 구현 에이전트를
  순차 투입하거나, 파일을 쪼개 영역이 겹치지 않는 조합만 병렬 배정할 것을
  권장**(예: "3+4"와 "7"은 건드리는 함수가 거의 안 겹쳐 병렬 가능, "1+2+8"과
  "6"도 마찬가지 — 두 묶음까지의 병렬은 비교적 안전).

---

## 11. 검증 체크리스트 포인트 (검증 에이전트용 요약)

- **BUG-021 회귀 검사(1번)**: `ZoneAnalysisTab().minimumSizeHint().width()`
  오프스크린 측정 + 실제 `MainWindow()` 생성 후 `win.size()`가 `1280×800`
  그대로인지 확인(기존 BUG-021 검증 스크립트 재사용).
- **3번 골든패스(주요 기능 추가 — 필수)**: 메인 캔버스에서 (a) 빈 곳 클릭+
  드래그해도 원이 생성되지 않음, (b) 기존 원이 있어도 드래그해도 이동/
  리사이즈되지 않음, (c) 원 위에서 우클릭해도 메뉴가 뜨지 않음, (d) Alt+휠이
  아무 효과 없음, (e) **일반 휠도 화면 줌이 안 됨**(결정 확정 시), (f) 존
  영역을 드래그 없이 클릭하면 `_zone_list`가 하이라이트되고 블랍 정보가 뜸
  (조회 기능은 살아있음), (g) "원(Zone) 설정..." 모달을 열면 **현재 화면의
  원이 그대로 보임**(최근 레시피가 아니라) — 3-5 핵심 발견 검증, (h) 모달
  "적용" 클릭 시 레시피 저장 확인 팝업이 뜨고 예/아니오/취소 3갈래가 모두
  정확히 동작.
- **5번 골든패스**: 원 N개 이미지에서 존 리스트 항목이 정확히 N개(바깥쪽
  없음), Excel 내보내기 시트 3개 어디에도 "바깥쪽" 행이 없음, 원 밖에 수동
  브러시로 그린 영역이 "미분류"로 집계됨(크래시 없이).
- **6번**: 이미지 20장 이상 세션에서 "전체 결과 보기" 클릭 시 GUI가 멈추지
  않음(최대 블로킹 200ms 이내, 기존 R-PERF-2 수용 기준 재사용), 결과 값이
  동기 버전과 바이트 단위로 동일(스냅샷 대조).
- **7번**: BUG-040 재측정 — 같은 이미지 재선택 시 462ms 대비 개선폭 실측,
  `_preview_cache`/`detected_ids` 캐시 적중 시 디스크 재읽기 0회(파일 I/O
  모니터링 또는 mock으로 확인).
- **8번**: 리스트 3장 이상 로드 + 전체 추론 완료 후, "현재 이미지만 추론"을
  다른 이미지로 재실행 → 나머지 2장의 `self._results`/캐시가 그대로 보존
  되는지 확인(핵심 회귀 포인트, 위 8절 "반드시" 참고).

---

## 12. 결정 필요 / 참고 사항

- `docs/decisions-needed.md`에 **1건 등록**: 메인 캔버스 일반 마우스 휠(뷰
  줌) 완전 제거 여부 — 기본 가정(제거)으로 구현 착수는 가능하나, 디자인
  검토 중 대체 확대 수단 필요성이 제기되면 사용자 재확인 필요(3-3절 참고).
- 4번(직접 네이밍)의 정확한 인터랙션은 디자이너 재량(3-4절 "디자이너
  재량" 명시) — 기획은 기술적 매핑(영역 클릭 → 존 인덱스 → 원)만 확정.
- 7번의 깊은 알고리즘 최적화(disk_mask 캐싱 등)는 이번 라운드 실측 후
  리더가 필요성을 재판단 — 지금 설계하지 않음(YAGNI, 7절 "보류" 참고).
