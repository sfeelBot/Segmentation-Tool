# 존(Zone) 분석 탭 — 오프라인 원 검출 테스트 제거 + 존 일괄 적용 발견성 개선 (2026-08-30)

전제: R1~R4·R-A~R-C·R3-1~R3-5·GitHub #13/#14(R13-A/R14-A/R13-B) 전부 구현+검증 통과
상태. 작업은 워크트리 `D:\segmentation model-zone-analysis-tab`
(`feature/zone-analysis-tab` 브랜치)에서만 수행 — main(`d:\segmentation model`)은
건드리지 않는다.

사용자 요청 2건:
1. "지정된 존을 모든 이미지에 일괄 적용할 수 있는 버튼 지정해줘"
2. "오프라인 원 검출 인식 기능 삭제" — **사용자가 명확히 확인한 요청**, 판단 불필요.

---

## 요청 1 — 존 일괄 적용 버튼

### 최종 해석: **(a) 이미 있는 기능이다 — 신규 로직 불필요, 발견성만 개선**

`decisions-needed.md` 등록 안 함 — 아래 근거로 충분히 좁혀진다고 판단.

### 코드 근거

`app/tabs/zone_analysis_tab.py`:

- `self._chk_apply_all`(L335-341) — 체크박스 라벨 "1번째 이미지 원을 전체에 적용",
  툴팁 "체크: 기준 이미지의 원을 나머지 전체에 그대로 적용 / 해제: 이미지마다 원을
  개별 자동 검출". 기본값 `setChecked(True)`.
- `self._btn_batch`(L342-349) — "▶ 선택 이미지 일괄 처리 (N장)", 툴팁에 활성화 조건
  명시.
- `_update_batch_button_state()`(L953-957) — "목록 2장 이상 + 기준 이미지에 원 1개
  이상"일 때만 `setEnabled(True)`.
- `_on_batch_process()`(L963-1049) — `apply_to_all = self._chk_apply_all.isChecked()`
  분기(L1013-1021): 체크 시 `_scale_circles(circles_ref, (ref_w, ref_h), (w, h))`로
  기준 이미지의 원을 대상 이미지 해상도에 비례 스케일해 **그대로 적용**, 해제 시
  이미지마다 `detect_circles()` 개별 자동 검출. 이후 `zones_from_circles()` +
  `zone_stats()`로 존별 퍼센티지를 계산해 `rows`에 누적하고
  `ZoneBatchResultDialog`로 표시.

**"기준 이미지에 그린 원(존 정의)을 다른 모든 이미지에 그대로 적용"이라는 사용자
원문의 핵심 동작(`apply_to_all=True` 분기)이 정확히 이미 존재한다.** 체크박스
문구("전체에 적용")와 사용자 원문("모든 이미지에 일괄 적용")이 사실상 동일 표현이다.

### (a) vs (b) 판단 — 왜 (b)(추론 없는 순수 원 복사)가 아닌가

`_on_batch_process()`의 최상단 가드(L964-971)가 `self._last_result`/
`self._target_class_id`/`self._target_classes`/`self._model`/`self._ckpt_path`
전부를 요구해 추론 실행 후에만 버튼이 동작한다. task brief는 이 가드가 "사용자가
원하는 것"과 다를 수 있는 지점으로 짚었으나, 코드를 끝까지 추적하면 이 가드는
우회 불가능한 **본질적 의존성**이다:

- 이 탭의 존재 이유 자체가 "존별 결함 면적 비율(%) 계산"이다(CLAUDE.md/roadmap
  "존(Zone) 분석 탭" 절 배경 참고).
- `_on_batch_process()`는 원을 배치하는 것으로 끝나지 않고, 그 즉시
  `result.class_map == target_cid`(L1031, 추론 결과)로 `target_mask`를 만들어
  `zone_stats(zone.mask, target_mask)`를 계산한다(L1027-1036). 추론 결과 없이는
  퍼센티지 자체를 계산할 방법이 없다 — "원만 복사하고 추론은 나중에"는 이 도구의
  출력(퍼센티지 테이블)을 만들어내지 못하는 반쪽짜리 동작이 된다.
- 따라서 (b) 해석("추론과 무관하게 원만 복사")은 이 도구에서 실질적으로 쓸모있는
  산출물을 만들지 못하는 좁은 니즈이고, 사용자 원문에도 "추론 없이"라는 명시적
  단서가 없다. YAGNI 판단: 존재하지 않는 니즈를 가정해 신규 "캔버스에 원만
  프리셋" 기능을 추가하지 않는다.

### 개선 대상 — 발견성(discoverability)만

기능은 이미 정확한 동작을 하지만, 다음 이유로 사용자가 "이게 그 기능"이라고
인지하기 어려웠을 가능성이 있다:

1. 좌측 패널 맨 아래(스크롤 없이 보이지만 시각적으로 눈에 띄지 않는 위치)에
   체크박스+버튼만 덩그러니 있고, 이 둘이 "존 일괄 적용"이라는 하나의 기능
   단위임을 알려주는 제목/그룹 표시가 없다.
2. 버튼 텍스트가 "일괄 **처리**"라 사용자가 찾던 "일괄 **적용**"이라는 단어와
   문자열 매칭이 안 된다(기능은 같지만 사용자가 검색하듯 훑어볼 때 놓치기 쉬움).
3. 버튼이 비활성 상태일 때(추론 미실행 등) 왜 비활성인지 시각적으로 드러나지
   않고 툴팁으로만 설명된다(hover해야 알 수 있음).

권장 개선(전부 `zone_analysis_tab.py` 좌측 패널 부분, 저리스크 텍스트/레이아웃
수정, 로직 변경 없음):

- 체크박스+버튼을 `QGroupBox("존 일괄 적용")`으로 묶어 하나의 기능 단위임을
  시각적으로 표시.
- 체크박스 라벨을 "1번째 이미지 원을 전체에 적용" → "기준 이미지의 존(원)을
  전체 이미지에 일괄 적용"으로 변경(사용자 원문 단어 "존"·"일괄 적용" 반영).
- 버튼 텍스트는 기능상 "적용"에 그치지 않고 실제로는 추론+계산까지 수행하므로
  "일괄 처리"라는 정확한 표현을 유지하되, 비활성 상태일 때 버튼 아래(또는
  그룹박스 캡션)에 활성화 조건을 상시 노출하는 보조 라벨 1줄 추가를 고려
  (`QLabel`, 회색 톤, 기존 `_lbl_target_info` 스타일 재사용) — 예: "추론 실행 +
  원 1개 이상 + 이미지 2장 이상 필요". 툴팁에만 의존하지 않게.

이 항목은 텍스트/레이아웃 수정 수준이라 디자인 에이전트 목업 없이 구현 에이전트가
바로 진행 가능한 수준으로 판단한다(리더가 원하면 직접 처리해도 되는 "사소한 수정"
범주에도 해당).

---

## 요청 2 — 오프라인 원 검출 테스트 기능 완전 삭제

### 삭제 범위 (정확한 파일별 목록)

#### 1. `app/widgets/circle_detect_preview_dialog.py` — **파일 전체 삭제**

184줄 전체가 `CircleDetectPreviewDialog` 단일 클래스 + 그 전용 헬퍼
(`_rgb_to_qpixmap()`, 이 파일 안에서만 쓰이는 로컬 복사본)로 구성된 완전 독립
파일. 다른 어떤 파일도 이 파일의 내부 심볼을 재사용하지 않는다(grep 확인 —
`app/` 전체에서 이 파일을 import하는 곳은 `zone_analysis_tab.py` 단 한 곳).

#### 2. `app/tabs/zone_analysis_tab.py` — 아래 지점만 삭제, 나머지는 그대로 유지

- **L50** — import문 삭제:
  `from app.widgets.circle_detect_preview_dialog import CircleDetectPreviewDialog`
- **L266-271** — 버튼 생성+배치 삭제:
  ```python
  toolbar_row2.addStretch()
  self._btn_offline_test = QPushButton("오프라인 원 검출 테스트…")
  self._btn_offline_test.setToolTip(
      "체크포인트 없이 이미지만으로 원 검출 알고리즘을 확인·튜닝합니다"
  )
  toolbar_row2.addWidget(self._btn_offline_test)
  ```
  단, `toolbar_row2.addStretch()`(L266) 자체는 레이아웃상 남겨야 한다(둘째 줄
  툴바 오른쪽 여백 확보 용도로, 버튼 삭제와 무관한 기존 레이아웃 관례) — 버튼
  관련 3줄(`self._btn_offline_test = ...`, `.setToolTip(...)`,
  `toolbar_row2.addWidget(...)`)만 제거.
- **L398** — 시그널 연결 삭제:
  `self._btn_offline_test.clicked.connect(self._on_open_offline_test)`
- **L876-884** — 슬롯 전체 삭제:
  ```python
  def _on_open_offline_test(self) -> None:
      """체크포인트 준비 여부와 무관하게 항상 열 수 있는 독립 팝업 — 이 탭의
      상태(이미지/체크포인트/추론결과)를 전혀 참조·변경하지 않는다(단, "메인 탭에
      적용" 버튼을 눌러 dialog.exec()가 accept로 끝난 경우는 예외 — R3-5)."""
      dialog = CircleDetectPreviewDialog(self)
      if dialog.exec():
          circles = dialog.result_circles()
          if circles:
              self._apply_circles_from_popup(circles, *dialog.result_image_size())
  ```
- **L886-909** — `_apply_circles_from_popup()` 메서드 전체 삭제(R3-5 라운드트립
  구현). **유일한 호출부가 바로 위 `_on_open_offline_test()`이므로**(grep 확인,
  다른 호출 없음) 이 메서드도 죽은 코드가 된다 — task brief가 명시한 삭제 대상
  "관련 슬롯 ... `_apply_circles_from_popup()` 등"에 정확히 해당:
  ```python
  def _apply_circles_from_popup(
      self, circles: list[tuple[float, float, float]], pop_w: int, pop_h: int
  ) -> None:
      """오프라인 검출 팝업에서 확정한 원을 메인 탭 캔버스로 라운드트립(R3-5).
      ...
      """
      if self._image_path is None or self._image_size == (0, 0):
          QMessageBox.warning(self, "이미지 없음", "메인 탭에 이미지를 먼저 여세요.")
          return
      ref_w, ref_h = self._image_size
      note = ""
      if pop_w > 0 and pop_h > 0 and (pop_w, pop_h) != (ref_w, ref_h):
          circles = _scale_circles(circles, (pop_w, pop_h), (ref_w, ref_h))
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

### 반드시 남겨야 할 것 (실수로 같이 지우면 안 되는 공유 로직)

- **`_scale_circles()`**(L100-111, 모듈 레벨 함수) — `_on_batch_process()`의
  `apply_to_all` 분기(L1013-1015, 요청1이 다루는 배치 적용 기능)가 계속 사용한다.
  이 함수는 오프라인 팝업 전용이 아니라 **범용 비례 스케일 헬퍼**이며,
  `_apply_circles_from_popup()`을 지워도 `_on_batch_process()`가 여전히 호출하므로
  **절대 삭제 금지**. (참고: `tests/test_zone_github_13_14.py` L216-220도
  `_scale_circles()`를 직접 단위 테스트하고 있어, 이 함수가 남아있어야 기존
  테스트도 깨지지 않는다.)
- `ZoneCanvas`(`app/widgets/zone_canvas.py`) — 메인 탭과 오프라인 팝업이 공유하던
  위젯이지만 클래스 자체는 메인 탭이 계속 쓰므로 무관, 수정 대상 아님.
- `self._image_size`, `self._canvas.get_circles()`/`set_circles()` 등 — 메인 탭
  자체 상태/캔버스 API, 오프라인 기능과 무관하게 계속 쓰인다.

### 삭제 후 확인해야 할 죽은 코드 없음 체크리스트

- `app/tabs/zone_analysis_tab.py` 상단 import 블록에 `CircleDetectPreviewDialog`
  외에 오프라인 전용으로만 쓰이던 심볼이 더 없는지(`QPushButton`, `QMessageBox`
  등은 다른 곳에서도 널리 쓰이므로 그대로 유지) — grep 결과 추가로 지울 import는
  없음(`CircleDetectPreviewDialog` 1건뿐).
- 클래스 내 다른 메서드가 `_on_open_offline_test`/`_apply_circles_from_popup`/
  `self._btn_offline_test`를 참조하지 않는지 — grep 결과 위 4개 지점(L50/L266-271/
  L398/L876-909) 외 참조 없음(파일 전체 유일 매치).
- `app/widgets/` 디렉토리에 `circle_detect_preview_dialog.py`를 참조하는 `__init__.py`
  등록/재노출이 없는지 — 없음(개별 모듈 직접 import 관례, 이 프로젝트에
  `app/widgets/__init__.py` 집합 재노출 관례 자체가 없음).
- `tests/` 디렉토리에 `CircleDetectPreviewDialog`/`_on_open_offline_test`/
  `_apply_circles_from_popup`를 참조하는 테스트가 없는지 — grep 결과
  `test_zone_github_13_14.py`/`test_zone_edit_toolbar.py` 둘 다 무관, 삭제 후
  기존 테스트 실행에 영향 없음.

### 문서 정정 대상

- `docs/roadmap.md` "존(Zone) 분석 탭" 절의 **R-A**(오프라인 원 검출 팝업, 완료
  표시)와 **R3-5**(오프라인 팝업 → 메인 탭 라운드트립, 완료 표시) 두 항목에
  "2026-08-30 사용자 요청으로 기능 전체 삭제됨" 정정 주석 추가(과거 완료 이력
  자체는 삭제하지 않고 위에 정정만 남긴다 — CLAUDE.md 로드맵 갱신 원칙: 상태
  변경 시 최신으로 덮어쓰되 상세 이력은 로그에 남아있으므로 지워도 되지만, 이번엔
  "한때 존재했다가 명시적으로 제거됨"이라는 사실 자체가 향후 재요청 방지에
  의미가 있어 남겨두는 편을 권장).
- **R13-B**(#13 요구사항4, `_scale_circles()` 통합)는 삭제 대상이 아님 — 그
  통합 결과물(`_scale_circles()`)이 배치 적용 기능에 그대로 남아 계속 쓰이므로
  정정 불필요. 다만 R13-B가 "팝업→메인 라운드트립과 배치처리 두 경로가 동일
  로직을 공유한다"고 서술한 부분 중 "팝업→메인 라운드트립" 경로는 이제 없어지므로,
  로드맵에 "현재는 배치 적용(`_on_batch_process`) 한 경로만 `_scale_circles()`를
  사용" 정도의 정정 문구를 함께 추가한다.
- `QA.md`에는 "오프라인 원 검출 테스트"를 완료 항목으로 기록한 곳이 없음(grep
  확인) — 정정 불필요.
- 과거 스펙 문서(`zone-analysis-tab-features-2026-08-26.md`,
  `zone-analysis-tab-features-round3-2026-08-27.md`,
  `zone-analysis-tab-github-issues-13-14-2026-08-27.md`)는 append-only 성격의
  당시 의사결정 기록이라 이번 삭제를 반영해 되돌려 쓰지 않는다(과거에 그런
  기능을 왜 만들었는지 이력 자체는 보존 가치가 있음) — 이번 스펙 문서가 최신
  상태를 대체한다.

---

## 구현 대상 파일

1. `app/widgets/circle_detect_preview_dialog.py` — 파일 삭제.
2. `app/tabs/zone_analysis_tab.py` — 위 4개 지점 삭제(요청2) + 좌측 패널 체크박스/
   버튼 텍스트·그룹박스 개선(요청1, 선택적·저리스크).
3. `docs/roadmap.md` — R-A/R3-5 정정 주석(리더 또는 구현 완료 후 검증 에이전트가
   기록, 이번 기획 세션에서 리더가 직접 갱신 예정).

신규 파일 없음. 두 요청이 같은 파일(`zone_analysis_tab.py`)을 건드리지만 겹치는
줄이 없어(요청1은 L335-349 부근, 요청2는 L50/L266-271/L398/L876-909) 한 구현
에이전트가 순서 상관없이 한 번에 처리 가능 — 별도 라운드 분할 불필요.

---

## 검증 골든패스

1. **삭제 확인**: `python main.py` 정상 기동(임포트 에러 없음 — 삭제된 파일을
   더 이상 아무도 import하지 않는지 이 자체로 1차 검증), 존 분석 탭 진입 시
   툴바 2번째 줄에 "오프라인 원 검출 테스트…" 버튼이 더 이상 보이지 않음.
2. **회귀 확인(R1~R4/R-B/R-C/R13-A/R14-A)**: 체크포인트 로드 → 이미지(또는 폴더)
   열기 → 추론 실행 → 타겟 클래스 확정 → 캔버스에서 원 편집(추가/이동/반지름
   조절/우클릭 지름 변경/삭제) → 존 리스트 퍼센티지 갱신 → Undo(Ctrl+Z) → 전부
   기존과 동일하게 동작(오프라인 기능 삭제가 메인 워크플로우에 영향 없음을
   확인).
3. **요청1 골든패스**: 위 상태에서 2장 이상 이미지 로드 → 기준 이미지에 원 1개
   이상 정의 → "존 일괄 적용" 체크박스(개선 후 라벨) 체크 상태에서 배치 버튼
   클릭 → `ZoneBatchResultDialog`에 각 이미지의 존별 퍼센티지가 기준 이미지 원을
   비례 스케일 적용한 결과와 일치하는지 확인(기존 `_scale_circles()` 동작 그대로
   유지되는지 회귀 확인 포함). 체크 해제 시 이미지별 개별 자동검출 분기도 함께
   확인.
4. **자동 테스트**: `pytest tests/test_zone_github_13_14.py tests/test_zone_edit_toolbar.py`
   — `_scale_circles()` 단위 테스트 포함 전부 그대로 통과해야 함(삭제 대상과
   무관한 회귀 없음 확인).
5. **죽은 코드 확인**: `grep -r "CircleDetectPreviewDialog\|circle_detect_preview_dialog\|_on_open_offline_test\|_apply_circles_from_popup\|_btn_offline_test" app/ tests/`
   결과 0건이어야 함.

검증 수준 판단: 요청2는 "삭제"라 저리스크(있던 걸 지우는 것, 새 로직 없음)지만
공유 헬퍼(`_scale_circles`) 오삭제 리스크가 명시적으로 지적된 만큼 위 3번(요청1
골든패스)까지 반드시 실행해 회귀가 없음을 실제 GUI로 확인해야 한다. 요청1은
텍스트/레이아웃 수정뿐이라 별도 목업 불필요.
