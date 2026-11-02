# 상/하부(Zone) 분석 탭 — 레이아웃 미세조정 + 오버레이 토글 버튼 + 바깥쪽 클릭 선택해제 (2026-11-02)

> 작업 위치: `D:/segmentation model-zone-analysis-tab` (브랜치 `feature/zone-analysis-tab`).
> 에디션 전용 기능 — main에는 반영하지 않는다.

사용자가 스크린샷 목업으로 제시한 UI/기능 변경 5건. 리더가 사전 조사(파일:line 단위
근거)를 제공하며 범위를 확정했고, 사용자가 그 범위를 확인했다. 아래 문서는 그 확인된
범위를 그대로 스펙화한 것 — 재조사로 범위를 넓히거나 좁히지 않았다(코드 직접 대조로
리더의 라인번호·동작 서술 전부 재확인 완료, 불일치 없음).

## 0. 영향 파일 한눈에

| 파일 | 영향 요구사항 |
|---|---|
| `app/tabs/zone_analysis_tab.py` | 1, 2, 3, 4(토글 액션 배선) |
| `app/widgets/zone_canvas.py` | 5(핵심) |
| `app/core/i18n.py` | 3(기존 키 재사용, 변경 없음) / 4(신규 키 1쌍) |
| `tests/test_zone_layout_compact_2026_10_30.py` | 1, 2 — **기존 회귀 테스트 수정 필요**(아래 "회귀 위험" 참고) |

1·2·3번은 전부 `zone_analysis_tab.py` `_build_ui()`의 같은 영역(`toolbar_row1`/
`toolbar_header`/`opacity_row`)을 건드린다. 4번은 같은 파일이지만 별개 신규 액션
추가라 충돌 범위가 작다. 5번은 `zone_canvas.py` 단독이라 완전히 독립적이다.
**디자인/구현 역할 분담과 실행 순서는 6절 참고.**

---

## 1. "현재 이미지만 추론" 버튼을 "추론 실행" 옆으로 이동

### 현재 상태
`zone_analysis_tab.py` `_build_ui()` 내 `toolbar_row1`(ckpt_card, 약 340~456행).
현재 `addWidget()` 순서:

```
btn_ckpt → lbl_ckpt_dot → lbl_ckpt → lbl_ckpt_badge → infer_progress
→ target_name_edit/target_combo → stretch
→ btn_run_current ("현재 이미지만 추론")
→ conf_slider+lbl_confidence → min_px_spin → edit_toolbar(브러시 도구)
→ btn_run ("추론 실행")
```

`_btn_run_current`가 체크포인트/타겟클래스 바로 다음(stretch 직후)에 있어 신뢰도
슬라이더·픽셀 threshold·편집 툴바를 사이에 두고 `_btn_run`과 멀리 떨어져 있다.

### 변경 방향
`_btn_run_current`를 `addWidget()` 호출 순서상 `_btn_run` 바로 앞으로 옮긴다(즉
conf_slider/min_px_spin 블록보다 뒤로 이동). 2번 항목이 적용되면 `edit_toolbar`가
이 행에서 아예 빠지므로, 최종 순서는:

```
btn_ckpt → lbl_ckpt_dot → lbl_ckpt → lbl_ckpt_badge → infer_progress
→ target_name_edit/target_combo → stretch
→ (3번 적용 후) lbl AI신뢰도 + conf_slider + lbl_confidence
→ (3번 적용 후) lbl 픽셀threshold + min_px_spin
→ btn_run_current → btn_run
```

코드 변경은 `toolbar_row1.addWidget(self._btn_run_current)` 호출 1줄을
`toolbar_row1.addWidget(self._btn_run)` 호출 바로 앞으로 옮기는 것뿐 — 위젯
생성·속성 설정 코드는 그대로 두고 `addWidget()` 순서만 재배치하면 된다(Qt
레이아웃은 addWidget 호출 순서가 화면 순서를 결정).

### 영향 파일/함수
`zone_analysis_tab.py` `_build_ui()` 한 곳. 다른 메서드(`_on_run_current`,
`_run_inference` 등 버튼 동작 로직)는 변경 없음 — 순수 레이아웃 순서 변경.

### 회귀 위험
- **BUG-021(2026-08-26, 최소폭 1588px 초과로 창이 강제 확대됨) 재발 위험** — 이번
  변경 자체는 폭을 바꾸지 않지만(위젯 추가/삭제 없음), 3번(라벨 재노출)과 동시에
  적용되므로 **통합 측정 필수**(3절 참고).
- `tests/test_zone_layout_compact_2026_10_30.py`의
  `test_ckpt_card_is_single_row_no_second_toolbar_layout()`은 각 위젯의
  `parentWidget()`만 `ckpt_card`인지 확인하고 순서는 검사하지 않으므로 **이 변경
  자체로는 깨지지 않는다**(순서 변경은 이 테스트의 범위 밖). 다만 2번 항목으로
  `_edit_toolbar`가 `ckpt_card`를 벗어나면 같은 테스트의 `_edit_toolbar` 단언이
  깨진다 — 아래 2번 "회귀 위험" 참고.

---

## 2. 브러시 도구 ↔ 오버레이 불투명도를 같은 행으로

### 현재 상태
- `_edit_toolbar`(그리기/지우기/영역삭제/pan + 구분선 + 브러시크기 spin + 구분선
  + undo, `zone_analysis_tab.py` 403~448행)는 현재 `toolbar_row1`(ckpt_card,
  체크포인트 행)에 있다.
- 캔버스 헤더 영역에 `toolbar_header`(562~573행 — `_lbl_wheel_hint`
  "원 모양을 바꾸려면 좌측 '원(Zone) 설정...'을 누르세요 · 휠: 화면 줌" 텍스트 +
  stretch)와 `opacity_row`(575~588행 — "오버레이 불투명도" 라벨 + 슬라이더 +
  퍼센트 라벨)가 **별도의 두 행**으로 존재한다.

### 변경 방향
`_edit_toolbar`를 `toolbar_row1`(ckpt_card)에서 빼내고, 캔버스 헤더의
`toolbar_header`와 `opacity_row`를 **하나의 행**(`QHBoxLayout`)으로 합쳐 그 안에
배치한다. 제안 배치 순서(사용자 목업 기준, 최종 미세조정은 구현 단계 재량):

```
_lbl_wheel_hint → stretch → _edit_toolbar → 구분자
→ "오버레이 불투명도" 라벨 + _overlay_opacity_slider + _lbl_overlay_opacity_pct
```

핵심 요구사항은 "브러시 도구와 오버레이 불투명도가 같은 행"이라는 것 — 정확한
좌우 배치·stretch 비율·구분자 스타일은 구현자가 디자이너 목업을 받아 결정해도
된다.

### 영향 파일/함수
`zone_analysis_tab.py` `_build_ui()` 단독. `_edit_toolbar`/`_brush_tools` 생성
코드와 액션 연결(`_set_tool`, `tool_changed` 등 시그널 배선)은 변경하지 않음 —
`addWidget()`으로 꽂는 **부모 레이아웃만** 바뀐다. `_overlay_opacity_slider`/
`_lbl_overlay_opacity_pct`의 생성·`valueChanged` 연결도 그대로 유지.

### 회귀 위험
- **`tests/test_zone_layout_compact_2026_10_30.py`
  `test_ckpt_card_is_single_row_no_second_toolbar_layout()`이 반드시 수정돼야
  한다** — 이 테스트는 `tab._edit_toolbar.parentWidget() is ckpt_card`를
  단언하는데, 이번 변경으로 `_edit_toolbar`의 부모가 `ckpt_card`가 아니라 캔버스
  헤더 합성 행이 된다. 구현자가 이 단언을 새 부모 기준으로 고치지 않으면 CI/수동
  pytest 실행이 실패한다 — **구현 범위에 반드시 포함**.
- BUG-021 폭 측정은 `ckpt_card`(`toolbar_row1`)만 대상이라, `_edit_toolbar`를
  빼내면 **ckpt_card 폭은 오히려 줄어든다**(3번의 라벨 추가와 상쇄 관계) — 1·2·3번을
  한 커밋으로 같이 반영한 뒤 통합 측정하는 것을 권장(6절 실행 순서 참고).
- 캔버스 헤더 쪽(`toolbar_header`+`opacity_row` 병합) 폭은 기존에 BUG-021 측정
  대상이 아니었다(`ckpt_card` 폭만 측정) — 새로 긴 행이 생기므로, 구현자는
  캔버스 헤더 합성 행도 과도하게 좁아지지 않는지(특히 좌측 패널 리사이즈 시)
  육안 확인 필요(자동 테스트 신설은 선택, 1280px 전체 창 기준 확인이면 충분).

---

## 3. 신뢰도/픽셀 threshold 라벨 재노출

### 현재 상태
`_conf_slider`(385~393행)와 `_min_px_spin`(395~401행)은 2026-10-30 레이아웃 1행
통합 라운드에서 공간 확보를 위해 라벨 텍스트를 제거하고 툴팁만 남겼다
(`setToolTip(t("zone.confidence_tip"))` / `setToolTip(t("zone.pixel_threshold_tip"))`).

### 변경 방향
라벨을 다시 노출한다. i18n 키가 이미 존재한다(`app/core/i18n.py`):
- `zone.ai_confidence_label` — ko "AI 신뢰도:" / en "AI confidence:" (327/921행)
- `zone.pixel_threshold_label` — ko "픽셀 threshold:" / en "Pixel threshold:" (329/923행)

`_conf_slider` 생성 직전에 `toolbar_row1.addWidget(QLabel(t("zone.ai_confidence_label")))`,
`_min_px_spin` 생성 직전에 `toolbar_row1.addWidget(QLabel(t("zone.pixel_threshold_label")))`을
추가한다. **신규 i18n 키 불필요** — 기존 키 재사용만으로 끝난다. 기존 `.tip`
툴팁(`zone.confidence_tip`/`zone.pixel_threshold_tip`)은 라벨이 생겨도 중복이
아니므로 그대로 유지(라벨은 상시 텍스트, 툴팁은 상세 설명 — 기존 다른 위젯들의
관례와 동일).

### 영향 파일/함수
`zone_analysis_tab.py` `_build_ui()`만 수정. `i18n.py`는 읽기만 — 변경 없음.

### 회귀 위험 (최우선 확인 대상)
- **BUG-021(최소폭 1588px 초과) 재발이 가장 유력한 항목.** 1번(순서 변경, 폭
  불변) + 2번(`_edit_toolbar`가 빠져 폭 감소)과 상쇄되지만, 정확히 얼마나
  남는지는 **실측 없이는 알 수 없다** — 2026-10-30 스펙도 "압축 5가지를 전부
  적용해도 빠듯할 수 있다"고 명시했던 선례가 있다.
- **구현 완료 후 반드시 실행**:
  ```python
  tab = ZoneAnalysisTab()
  assert tab.minimumSizeHint().width() <= 1280
  ```
  (`tests/test_zone_layout_compact_2026_10_30.py`
  `test_ckpt_card_minimum_width_stays_within_1280()`과 동일한 패턴 — 기존 테스트가
  그대로 재사용 가능하므로 신규 테스트 작성보다는 **기존 테스트를 그대로 재실행해
  통과를 확인**하는 쪽을 권장, 실패 시에만 추가 압축 또는 신규 테스트 보강).
- 만약 1280px를 넘기면 추가 압축 후보(2026-10-30 스펙에서 쓴 패턴 재사용):
  라벨을 짧게(`t()` 신규 축약 키 추가는 과함, 기존 텍스트 그대로 두고 폭이
  부족하면 `_lbl_ckpt`의 `setMaximumWidth(140)`을 더 줄이는 등 기존 필드 조정)
  — 단, 이는 실측 후에만 판단할 일이라 지금 미리 설계하지 않는다(YAGNI, 리더
  보고 사항으로 남김).

---

## 4. 오버레이 보기/숨기기 토글 버튼 + F 단축키

### 현재 상태
- 토글 로직은 이미 존재: `_toggle_overlay()`(`zone_analysis_tab.py` 1172행)가
  `self._overlay_visible`을 반전하고 재렌더링.
- F 단축키도 **이미 이중으로 동작한다**:
  1. `zone_canvas.py` `keyPressEvent()`(876행)가 F키(수정자 없음) 시
     `overlay_toggle_requested` 시그널을 emit.
  2. `zone_analysis_tab.py` 674행이 `self._canvas.overlay_toggle_requested.connect(self._toggle_overlay)`로
     연결.
  3. `zone_analysis_tab.py` 자신의 `keyPressEvent()`(1219~1221행)도 F키 시
     `_toggle_overlay()`를 직접 호출(캔버스가 포커스 없을 때 대비).
- **즉 새로 만들 것은 "버튼"뿐** — 토글 상태/단축키는 추가 구현이 필요 없다.

### 참고 구현(동일 저장소 내 선례, 거의 그대로 재사용 가능)
`app/tabs/r_analysis_tab.py` 289~295행이 **동일한 요구사항을 이미 구현해 뒀다**:

```python
self._act_overlay_visible = QAction(svg_icon("eye"), "", self)
self._act_overlay_visible.setCheckable(True)
self._act_overlay_visible.setChecked(True)
self._act_overlay_visible.setToolTip(t("r.overlay_visible_tip") + " [F]")
self._act_overlay_visible.toggled.connect(self._canvas.set_mask_overlay_visible)
self._canvas.overlay_toggle_requested.connect(self._act_overlay_visible.toggle)
toolbar.addAction(self._act_overlay_visible)
```

`app/resources/icons/eye.svg`는 이미 존재(라벨링 탭도 같은 아이콘을 눈 모양
가시성 토글로 사용 중, `labeling_tab.py` 289행) — **신규 아이콘 불필요**.

### 변경 방향
Zone 탭에 같은 패턴을 적용한다. 단, Zone 탭은 R 분석 탭과 토글 대상 메서드 이름이
다르므로(`_toggle_overlay()` vs `set_mask_overlay_visible()`) 그대로 복붙은 안
되고 다음과 같이 어댑터가 필요하다:

```python
self._act_overlay_visible = QAction(svg_icon("eye"), "", self)
self._act_overlay_visible.setCheckable(True)
self._act_overlay_visible.setChecked(self._overlay_visible)   # 초기 상태 동기화
self._act_overlay_visible.setToolTip(t("zone.overlay_visible_tip") + " [F]")
self._act_overlay_visible.toggled.connect(self._on_overlay_toggle_action)
self._edit_toolbar.addAction(self._act_overlay_visible)
```

`_toggle_overlay()`는 내부적으로 `self._overlay_visible`을 직접 반전하는 구조라
(R 분석 탭의 `set_mask_overlay_visible(bool)`처럼 불값을 직접 받는 setter가
아님), QAction의 `toggled(bool)`과 1:1로 맞물리게 하려면 둘 중 하나:
- (권장) `_toggle_overlay()`를 호출하는 **기존 호출부**(캔버스 F키 시그널,
  탭 자신의 `keyPressEvent`)는 그대로 두고, 새 QAction은
  `toggled.connect(lambda checked: self._set_overlay_visible(checked))`처럼
  "상태를 직접 설정하는" 신규 메서드를 하나 추가해 기존 `_toggle_overlay()`
  바디(반전 로직)에서 그 메서드를 호출하도록 리팩터링한다(반전 로직과 "값을
  정하는" 로직을 분리) — 그래야 버튼↔키보드 양방향 동기화가 깨지지 않는다.
- 신규 i18n 키 1쌍 필요: `zone.overlay_visible_tip` (ko "검출 결과 표시/숨김" /
  en "Show/hide detection result" — `r.overlay_visible_tip`과 동일 문구,
  `i18n.py`에 ko/en 쌍으로 추가).

### 영향 파일/함수
`zone_analysis_tab.py` — `_build_ui()`(액션 추가), `_toggle_overlay()`(상태
설정과 반전 로직 분리 소폭 리팩터링). `app/core/i18n.py` — 신규 키 1쌍.
`app/widgets/zone_canvas.py`/`app/resources/icons/eye.svg`는 **변경 없음**(이미
존재하는 시그널/아이콘 재사용).

### `BrushToolbar`(공유 위젯) 배치 여부 — 권장안
사용자 지시의 결정 필요 지점: 이 토글 액션을 공유 위젯 `BrushToolbar`
(`app/widgets/brush_toolbar.py`, 추론 탭 등에서도 재사용)에 넣을지, Zone 탭
전용으로 `_edit_toolbar`에만 addAction할지.

**권장안: Zone 탭 전용으로 `self._edit_toolbar`에 직접 추가한다(`BrushToolbar`
클래스 수정 안 함).** 근거:
1. `BrushToolbar`의 클래스 docstring이 명시하듯 "라벨링 탭(+존분석/R분석)에서
   **동작까지 완전히 통일된 공통 도구만** 다룬다"는 원칙이 이미 있다 — 오버레이
   개념은 탭마다 다르다(Zone은 AI 블랍 오버레이, 추론 탭은 세그멘테이션 결과
   오버레이, 라벨링 탭은 어노테이션 오버레이이고 라벨링 탭은 이미 `eye` 토글을
   `BrushToolbar` 밖에서 독자적으로 구현해 둠).
2. **R 분석 탭도 이미 같은 결정을 내렸다** — `r_analysis_tab.py`가
   `_act_overlay_visible`을 `BrushToolbar`가 아니라 자기 자신의 로컬 QAction으로
   구현했다(4절 "참고 구현" 코드 그대로). 공유 위젯에 넣지 않는 쪽이 이미
   이 저장소의 확립된 패턴이다 — Zone 탭만 다르게 갈 이유가 없다.
3. 2026-10-27 공유 위젯 추출 기획 로그(`docs/agents/planning-log.md`)가 이미
   "bucket-fill/select/clear/auto-label/eye/fullscreen 전부 공유 위젯 밖"으로
   명시적으로 결정해 뒀다(YAGNI — 단일 소비자를 위한 추측성 옵션 플래그 방지
   원칙).

**사용자 재확인 불필요** — 리더가 바로 이 권장안대로 구현자에게 지시해도 된다.
`docs/decisions-needed.md`에는 "참고 기록"이 아니라 등록하지 않는다(코드 선례 2건
+ 기존 설계 원칙 1건으로 이미 답이 명확함).

### 회귀 위험
- `BrushToolbar`를 건드리지 않으므로 추론 탭/라벨링 탭/R 분석 탭 전부 영향 없음.
- 기존 F키 이중 경로(캔버스/탭 자신)와 신규 버튼이 모두 같은 `_overlay_visible`
  상태를 공유해야 함 — 버튼으로 끈 뒤 F키로 다시 켜도 버튼 체크 상태가 따라가는지
  (양방향 동기화) 검증 필수(`toggled`/`overlay_toggle_requested` 양쪽 경로 전부
  테스트).

---

## 5. "바깥쪽"(모든 원 밖) 클릭 시 선택 해제

### 현재 상태
`zone_canvas.py`: 2026-10-30 라운드에서 "바깥쪽 존" 개념 자체를 제거했다
(`_zone_index_at()`, 581~593행 — 모든 원 밖이면 `None` 반환). 그런데
`mouseReleaseEvent()`의 두 클릭 처리 분기가 모두 `zone_idx is None`일 때
**아무 것도 하지 않고 조용히 리턴**한다:
- 814~835행: 편집 비활성(메인 캔버스 조회 전용) 분기 — 828행
  `if zone_idx is not None:` 블록 안에서만 `set_highlighted_zone()`+
  `zone_clicked.emit()` 수행.
- 836~865행: 원 생성을 시도했다가 너무 작아 결국 단순 클릭으로 판정되는 분기 —
  863행 동일 패턴.

즉 이전에 어떤 존이 하이라이트/선택돼 있었다면, 바깥쪽을 클릭해도 그 선택 상태가
그대로 남는다 — 사용자에게 "바깥쪽을 선택했는데 이전 존이 계속 선택된 것처럼
보이는" 혼란을 준다.

### 변경 방향
두 분기 모두 `self._circles`가 있고(원이 1개 이상 존재) `zone_idx`가 `None`인
경우에도:
1. `self.set_highlighted_zone(None)`을 호출해 캔버스 하이라이트를 해제한다.
2. `self.zone_clicked.emit(-1)`을 emit한다(-1을 "바깥쪽/선택해제" sentinel로
   사용).

`zone_analysis_tab.py`의 `_on_canvas_zone_clicked(self, zone_index: int)`
(1454~1457행)은 이미 `self._zone_list.setCurrentRow(zone_index)`만 호출하는데,
`QListWidget.setCurrentRow(-1)`은 Qt 표준 동작으로 선택을 해제하므로 **이 함수는
그대로 둬도 `-1`을 올바르게 처리한다** — 추가 분기 구현 불필요, 코드 변경 없이
동작만 확인하면 된다.

`zone_clicked` 시그널 선언부(89행)의 docstring 주석
`# 원이 아닌 빈 곳을 (드래그 없이) 클릭 -> 해당 존 인덱스`도 "-1 = 바깥쪽/선택
해제"를 포함하도록 갱신한다.

### 영향 파일/함수
`zone_canvas.py` — `mouseReleaseEvent()`의 두 분기(814~835, 836~865행)에 각각
"zone_idx가 None일 때의 처리" 추가, `zone_clicked` 시그널 선언부 주석 갱신.
`zone_analysis_tab.py`는 **코드 변경 없음**(동작 확인만).

### 회귀 위험 — `zone_clicked` 기존 구독자 영향
`zone_clicked.connect(...)` 호출부는 `zone_analysis_tab.py` 667행
(`self._canvas.zone_clicked.connect(self._on_canvas_zone_clicked)`) **1곳뿐**임을
확인(`grep` 결과 다른 구독자 없음). 구독자가 하나뿐이고 그 처리가 `-1`을 이미
올바르게 받아들이는 Qt 표준 API(`setCurrentRow`)이므로, 이번 변경의 실질 회귀
범위는 **거의 없다**. 다만 아래 2가지는 구현자가 직접 확인해야 한다:
- `_on_zone_row_selected()`(1459~1460행, 리스트→캔버스 역방향 동기화)가
  `row == -1`을 받을 때(`row if row >= 0 else None`) 이미 `None`으로 안전하게
  변환하는지 — 코드상 이미 그렇게 돼 있음(변경 불필요, 교차 확인만).
- `zone_clicked.emit(-1)`이 "원이 0개"(즉 `self._circles`가 비어 있는) 상태에서는
  **emit되지 않아야 함**(원 자체가 없으면 "바깥쪽"이라는 개념 자체가 성립하지
  않음 — 2026-10-30 스펙이 이미 "가장 큰 원 밖을 클릭한 경우도 존이 없으므로
  emit하지 않음"이라고 명시한 기존 불변식). 즉 `-1` emit 조건은 반드시
  `self._circles`가 비어있지 않을 때로 한정해야 하며, 이는 과제 설명의 "두 분기
  모두 `self._circles`가 있고 `zone_idx`가 `None`인 경우"라는 조건과 정확히
  일치한다(원 0개일 때는 기존처럼 아무 것도 emit하지 않음, 변경 없음).

---

## 6. 실행 순서 및 디자인/구현 역할 분담

### 파일 충돌 지점
1·2·3번은 전부 `zone_analysis_tab.py` `_build_ui()`의 같은 블록(`toolbar_row1`
+ `toolbar_header`/`opacity_row`)을 수정한다 — **한 커밋으로 같이 반영**하는
것을 권장(순서만 바꾸는 1번, 위젯 이동인 2번, 라벨 추가인 3번을 분리해서 커밋해도
되지만, BUG-021 측정은 셋을 전부 적용한 최종 상태로 한 번만 하면 된다). 4번은
같은 파일이지만 별개 신규 액션(`_act_overlay_visible`)이라 diff 충돌 위험이
작다. 5번은 `zone_canvas.py` 단독으로 **완전히 독립**.

### 디자이너 ↔ 구현자 역할 분담 (병렬 작업용)
- **디자이너**: 1·2·3번의 최종 배치(캔버스 헤더 합성 행의 좌우 순서/구분자
  스타일, 라벨 재노출 후 폭이 빠듯해질 경우의 대안 압축안)와 4번의 토글 버튼
  위치(브러시 클러스터 내 어디에 놓을지, 구분선 앞/뒤)를 Artifact 목업으로
  제안한다. **코드는 건드리지 않는다** — `zone_analysis_tab.py`에 대한 실제
  Edit는 구현자 전담.
- **구현자**: 디자이너의 배치안을 받아 `zone_analysis_tab.py`/`zone_canvas.py`에
  실제 반영. 디자인 목업 확정 전이라도 1·3·5번(배치가 비교적 명확하고 이견이
  적은 항목)은 선행 착수 가능, 2·4번(배치 재량이 큰 항목)은 목업 확정 후 착수
  권장.
- 둘 다 `zone_analysis_tab.py`를 건드리므로, **같은 시간에 동시 Edit는 피한다**
  (디자이너는 Artifact/목업에만, 구현자는 디자이너 결과물이 나온 뒤 코드 반영) —
  진짜 "병렬"은 5번(구현자 A, `zone_canvas.py` 단독)과 1~4번(구현자 B,
  `zone_analysis_tab.py`) 두 갈래로 나누는 것을 의미한다.

### 권장 순서
```
5 (zone_canvas.py 단독, 완전 독립, 디자인 불필요 — 즉시 구현 가능)
   ∥ (병렬)
1 + 2 + 3 (zone_analysis_tab.py 같은 블록, 한 커밋 권장, BUG-021 통합 측정 필수)
   → 4 (같은 파일이지만 신규 액션, 1+2+3 이후 착수해 diff 충돌 최소화)
```
4번은 2번(`_edit_toolbar`가 어느 행에 있는지)이 먼저 확정돼야 토글 액션을
`_edit_toolbar`의 정확히 어느 위치에 꽂을지 정하기 쉬우므로 2번 이후 권장(강한
의존은 아님, 순서 편의상 권장).

---

## 7. 검증 체크리스트 (구현 완료 후)

- [ ] `tab._btn_run_current`와 `tab._btn_run`이 `toolbar_row1`에서 서로 인접한
      순서로 `addWidget()`됐는지 (레이아웃 `indexOf()` 차이 1).
- [ ] `tab._edit_toolbar.parentWidget()`가 더 이상 `ckpt_card`가 아니라 캔버스
      헤더 합성 행인지. 같은 행에 `tab._overlay_opacity_slider`도 있는지(공통
      부모 동일한지).
- [ ] `tab._conf_slider`/`tab._min_px_spin` 앞에 각각 "AI 신뢰도:"/"픽셀
      threshold:" 라벨(`QLabel`)이 실제로 렌더링되는지(en 전환 시 "AI
      confidence:"/"Pixel threshold:").
- [ ] **BUG-021 재발 확인**: `ZoneAnalysisTab().minimumSizeHint().width() <= 1280`
      (offscreen, 기존 `test_ckpt_card_minimum_width_stays_within_1280()` 재실행).
- [ ] `tests/test_zone_layout_compact_2026_10_30.py` 전체 재실행 — 특히
      `test_ckpt_card_is_single_row_no_second_toolbar_layout()`을
      `_edit_toolbar` 이동에 맞게 수정한 뒤 통과하는지.
- [ ] 캔버스 헤더에 오버레이 토글 버튼(눈 아이콘) 클릭 → 오버레이 표시/숨김
      전환, 체크 상태가 실제 표시 상태와 일치.
- [ ] F키로 토글해도 버튼 체크 상태가 따라가는지(버튼↔F키 양방향 동기화).
- [ ] 원이 1개 이상 있는 상태에서 모든 원 밖(바깥쪽)을 클릭 → 이전에 선택돼
      있던 존의 하이라이트/우측 리스트 선택이 해제되는지(편집 비활성 분기, 원
      생성 시도 후 취소 분기 둘 다).
- [ ] 원이 0개인 상태에서 빈 곳 클릭 → 여전히 아무 것도 emit되지 않는지(기존
      불변식 유지 확인, 회귀 아님을 재확인).
- [ ] ko/en 전환 양쪽에서 신규 라벨 3개(`zone.ai_confidence_label`,
      `zone.pixel_threshold_label`, `zone.overlay_visible_tip`)가 정상 렌더링되는지.

---

## 8. 리더 보고 사항 (결정 불필요, 참고용)

- 4번 "토글 버튼을 `BrushToolbar` 공유 위젯에 넣을지" 질문은 **이미 답이 명확함**
  (권장안 = Zone 탭 전용 로컬 액션) — `docs/decisions-needed.md`에 등록하지
  않았다. R 분석 탭이 이미 같은 결정을 내린 선례, 2026-10-27 공유 위젯 추출
  기획 로그의 명시적 원칙(YAGNI) 둘 다 같은 결론을 가리킨다.
- 아이콘도 이미 존재하는 `eye.svg`를 그대로 재사용하면 되므로 별도 디자인 결정이
  필요 없다(라벨링 탭·R 분석 탭과 시각 언어 통일 효과도 덤으로 생김).
- 3번(라벨 재노출)의 BUG-021 재발 여부는 **실측 전까지 알 수 없다** — 구현자가
  7절 체크리스트의 폭 측정을 건너뛰면 안 된다는 점을 검증 단계에서 다시
  강조할 것.
