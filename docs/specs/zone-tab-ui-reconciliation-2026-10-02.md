# 상/하부 분석 탭 — Artifact ↔ 실제 코드 불일치 조정 (2026-10-02)

디자인 담당 작성. 목적은 **기능 추가가 아니라 비주얼 조정** — 라운드 A~F 구현은 기능적으로
스펙(`docs/specs/zone-tab-redesign-2026-10-01.md`)을 충족했으나, 확정된 Artifact 목업
(https://claude.ai/artifact/4bw8wooYywZjmBQkSYxxP8)의 비주얼 디테일 다수가 코드에 반영되지
않았다. 아래는 Artifact 4개 아트보드(Main/Recipe/Progress/Results)와 실제 코드를 1:1 대조해
뽑은 불일치 목록 + 구현 스펙이다. 구현 에이전트가 이 문서 하나만 보고 작업할 수 있는 수준을
목표로 함.

**조사 방법**: Artifact는 발행 당시 로컬에 작성했던 `.dc.html` 소스(스크래치패드)를 재확인했고,
코드는 `app/tabs/zone_analysis_tab.py`(전체 1332행), `app/widgets/zone_recipe_dialog.py`(전체),
`app/widgets/zone_batch_result_dialog.py`(전체), `app/widgets/inference_image_list.py`(구조
확인용 일부)를 `Read`/`Grep`으로 직접 읽었다. 코드는 건드리지 않음 — 이 문서만 산출.

**적용 범위 밖(이번에 건드리지 않음)**: `zone_canvas.py`(캔버스 내부 렌더링 — 기존 동작 유지),
`zone_recipe_store.py`/`zone_metrics.py` 등 core 로직(수치 계산은 Artifact와 무관, 이미 정확).
이번 문서는 전부 **QWidget 트리 구조 + QSS 스타일** 변경이다.

---

## 0. 전역 전제 — 색상은 대부분 이미 맞다

`main.py`의 전역 QSS(`#1a1d23`/`#1f2329`/`#111418`/`#374151`/`#4b5563`/`#60a5fa`/`#10b981`/
`#34d399`/`#fbbf24`/`#1e3a5f`)가 `QWidget`/`QGroupBox`/`QPushButton`/`QListWidget`/`QDialog`
등에 전역 상속되므로, 아래에서 지적하는 불일치는 **색상 자체가 틀린 경우는 거의 없고**
① 특정 위젯이 아예 없음(스텝 인디케이터), ② 레이아웃 구조/배치 순서가 다름, ③ 강조해야 할
버튼(Run, 메인 탭에 적용, 결과 분석 보기)에 강조 스타일이 안 입혀져 있음, ④ "카드형 박스"
(둥근 테두리) 패턴이 빠진 flat 레이아웃 — 네 패턴으로 수렴한다. 신규 색상은 필요 없다 —
전부 기존 팔레트 hex를 그대로 재사용한다.

---

## 1. 스텝 인디케이터 — 완전 누락 (최우선)

### 불일치
Artifact `Main.dc.html` 최상단의 7단계 진행 안내 띠(①체크포인트~⑦결과분석, 완료=초록 체크/
현재=파란 링/대기=회색 숫자, 연결선 색으로 진행도 표현)가 **실제 코드 어디에도 없다** —
`zone_analysis_tab.py`의 `_build_ui()`를 전체 확인했고 `step`/`인디케이터` 관련 코드 0건.

### 구현 스펙

신규 파일 `app/widgets/zone_step_indicator.py`:

```python
"""Zone 탭 — 시나리오 7단계 진행 안내 위젯. 클릭 전환·잠금 없는 순수 표시용
(CLAUDE.md 디자인 원칙 "위저드 강제 금지" — 상태만 보여주고 아무 것도 막지 않는다)."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

_STEP_LABELS = [
    "① 체크포인트", "② 이미지", "③ 영역 설정", "④ 추론 실행",
    "⑤ 진행상황", "⑥ 결과 보정", "⑦ 결과 분석",
]
_DONE_BG, _DONE_FG = "#10b981", "#34d399"
_CUR_BG, _CUR_BORDER, _CUR_FG = "#1e3a5f", "#60a5fa", "#60a5fa"
_PENDING_FG = "#6b7280"


class ZoneStepIndicator(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            "background:#1f2329;border:1px solid #374151;border-radius:8px;"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 8, 18, 8)
        layout.setSpacing(0)
        self._circles: list[QLabel] = []
        self._captions: list[QLabel] = []
        self._lines: list[QFrame] = []
        for i, text in enumerate(_STEP_LABELS):
            col = QVBoxLayout()
            col.setSpacing(3)
            circle = QLabel()
            circle.setAlignment(Qt.AlignmentFlag.AlignCenter)
            caption = QLabel(text)
            caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
            caption.setStyleSheet("background:transparent;border:none;")
            col.addWidget(circle, alignment=Qt.AlignmentFlag.AlignCenter)
            col.addWidget(caption)
            wrap = QWidget()
            wrap.setLayout(col)
            wrap.setMinimumWidth(84)
            layout.addWidget(wrap)
            self._circles.append(circle)
            self._captions.append(caption)
            if i < len(_STEP_LABELS) - 1:
                line = QFrame()
                line.setFixedHeight(2)
                layout.addWidget(line, stretch=1)
                self._lines.append(line)
        self.set_state(1, set())

    def set_state(self, current: int, completed: set[int]) -> None:
        """current: 1~7 (현재/다음 추천 단계). completed: 완료로 표시할 단계 번호 집합."""
        for i in range(7):
            step = i + 1
            circle, caption = self._circles[i], self._captions[i]
            if step in completed:
                size = 24
                circle.setText("✓")
                circle.setStyleSheet(
                    f"border-radius:{size // 2}px;background:{_DONE_BG};"
                    "color:#0d1f16;font-weight:bold;border:none;"
                )
                caption.setStyleSheet(f"font-size:10.5px;color:{_DONE_FG};background:transparent;border:none;")
            elif step == current:
                size = 26
                circle.setText(str(step))
                circle.setStyleSheet(
                    f"border-radius:{size // 2}px;background:{_CUR_BG};"
                    f"border:2px solid {_CUR_BORDER};color:{_CUR_FG};font-weight:bold;"
                )
                caption.setStyleSheet(
                    f"font-size:11px;color:{_CUR_FG};font-weight:bold;background:transparent;border:none;"
                )
            else:
                size = 24
                circle.setText(str(step))
                circle.setStyleSheet(
                    f"border-radius:{size // 2}px;background:#1a1d23;"
                    f"border:1px solid #4b5563;color:{_PENDING_FG};"
                )
                caption.setStyleSheet(f"font-size:10.5px;color:{_PENDING_FG};background:transparent;border:none;")
            circle.setFixedSize(size, size)
        for i, line in enumerate(self._lines):
            left_done = (i + 1) in completed
            if left_done and (i + 2) in completed:
                color = _DONE_FG
            elif left_done and (i + 2) == current:
                color = _CUR_BORDER
            else:
                color = "#374151"
            line.setStyleSheet(f"background:{color};border:none;")
```

`zone_analysis_tab.py` 변경:

1. import 추가: `from app.widgets.zone_step_indicator import ZoneStepIndicator`
2. `__init__`에 상태 플래그 2개 추가(완료 판정에 필요, 기존 상태만으로는 "⑥ 결과 보정"/
   "⑦ 결과 분석"을 구분할 수 없음):
   ```python
   self._step6_touched = False   # 브러시 그리기/지우기/블랍삭제를 1번이라도 했는가
   self._result_viewed = False   # 결과 분석 팝업을 1번이라도 열었는가
   ```
3. `_build_ui()` 맨 앞, `root = QVBoxLayout(self)` 다음 줄에:
   ```python
   self._step_indicator = ZoneStepIndicator()
   root.addWidget(self._step_indicator)
   ```
4. 진행 상태 계산 헬퍼(새 메서드, 클래스 아무 위치나):
   ```python
   def _compute_step_state(self) -> tuple[int, set[int]]:
       done = {
           1: self._ckpt_path is not None,
           2: self._image_path is not None or self._img_list.count() >= 1,
           3: len(self._canvas.get_circles()) >= 1,
           4: self._last_result is not None or bool(self._results),
       }
       done[5] = done[4]   # "진행상황"은 결과가 있으면 이미 끝난 것으로 간주(아래 러닝 중 예외)
       done[6] = self._step6_touched
       done[7] = self._result_viewed
       if self._worker is not None or self._batch_worker is not None:
           return 5, {k for k in (1, 2, 3, 4) if done[k]}   # 추론 진행 중엔 강제로 5번 강조
       completed = {k for k, v in done.items() if v}
       current = next((k for k in range(1, 8) if k not in completed), 7)
       return current, completed

   def _refresh_step_indicator(self) -> None:
       current, completed = self._compute_step_state()
       self._step_indicator.set_state(current, completed)
   ```
5. 호출 지점(기존 메서드 끝에 한 줄씩 추가 — 신규 시그널 없이 기존 호출부에 편승,
   `_update_undo_button_state` 등 기존 관례와 동일 패턴):
   - `_apply_checkpoint()` 끝
   - `_after_list_load()` 끝, `_on_images_removed()` 끝
   - `__init__`의 시그널 연결부에 `self._canvas.circles_changed.connect(self._refresh_step_indicator)`
   - `_on_run()` 시작부(워커 생성 직후), `_on_inference_finished()` 끝
   - `_on_batch_process()`(워커 생성 직후), `_on_batch_finished()` 끝
   - `_on_blob_deleted()`와 `_canvas.erase_changed` 연결부에 `_step6_touched = True` 설정 후 refresh:
     ```python
     def _mark_step6_touched(self) -> None:
         self._step6_touched = True
         self._refresh_step_indicator()
     ```
     그리고 `__init__`의 시그널 연결부에 추가:
     ```python
     self._canvas.blob_deleted.connect(lambda _id: self._mark_step6_touched())
     self._canvas.erase_changed.connect(self._mark_step6_touched)
     ```
     (주의: `circles_changed`에는 연결하지 않는다 — 원 편집은 ③ 영역 설정 행위이지
     ⑥ 결과 보정이 아니다. `ZoneCanvas`의 undo 스택은 원/블랍/브러시가 공유하므로
     `can_undo()`로는 이 둘을 구분할 수 없어 전용 플래그가 필요하다.)
   - `_on_export_single()`과 `_on_batch_finished()`의 다이얼로그 `.exec()` 호출 직전에:
     ```python
     self._result_viewed = True
     self._refresh_step_indicator()
     ```
6. `__init__` 맨 끝(`_build_ui()` 호출 직후)에 `self._refresh_step_indicator()` 1회 호출 —
   초기 상태(전부 대기, current=1)를 즉시 반영.

---

## 2. 체크포인트+추론 실행 바 — flat 레이아웃 → 카드형 + 강조 버튼

### 불일치
Artifact: 둥근 테두리 카드(`#1f2329`/`#374151`/radius 8) 안에 초록 점(●) + "자동 선택됨" 배지 +
"변경…" 버튼 + 추론방식 고정 텍스트 + accent 강조된 Run 버튼이 한 행. 코드(`toolbar_row1`,
230~262행): 카드 테두리 없이 루트 레이아웃에 바로 `QPushButton("체크포인트 열기 (.pt)…")` +
플레인 `QLabel`(색상만 회색) + Run 버튼(글자만 bold, 강조 테두리 없음) — "자동 선택됨" 배지
자체가 없어 1번 기획(체크포인트 자동 선택)이 구현됐다는 사실이 화면에 전혀 드러나지 않는다.

### 구현 스펙
1. `__init__`에 `self._ckpt_auto_selected = False` 추가.
2. `set_default_checkpoint()`에서 `_apply_checkpoint(path)` 호출 직전/직후에
   `self._ckpt_auto_selected = True` 설정. `_on_select_checkpoint()`(사용자가 직접 변경)에서는
   `_apply_checkpoint(Path(path))` 호출 전 `self._ckpt_auto_selected = False` 설정.
3. `_apply_checkpoint()` 끝에 배지 갱신:
   ```python
   self._lbl_ckpt_badge.setVisible(self._ckpt_auto_selected)
   ```
4. `toolbar_row1` 구성부를 카드로 교체 — 기존 `QHBoxLayout toolbar_row1`를 그대로 두되,
   그걸 감싸는 `QFrame` 추가:
   ```python
   ckpt_card = QFrame()
   ckpt_card.setStyleSheet(
       "background:#1f2329;border:1px solid #374151;border-radius:8px;"
   )
   toolbar_row1 = QHBoxLayout(ckpt_card)
   toolbar_row1.setContentsMargins(14, 7, 14, 7)
   ```
   (기존 `toolbar_row1 = QHBoxLayout()` 줄을 위 코드로 교체, 이후 `addWidget` 호출은 그대로.)
5. 체크포인트 라벨 앞에 초록 점 + 배지 추가(`self._btn_ckpt` 바로 뒤, 기존
   `self._lbl_ckpt` 앞):
   ```python
   self._lbl_ckpt_dot = QLabel("●")
   self._lbl_ckpt_dot.setStyleSheet("color:#34d399;font-size:15px;background:transparent;border:none;")
   toolbar_row1.addWidget(self._lbl_ckpt_dot)
   toolbar_row1.addWidget(self._lbl_ckpt)
   self._lbl_ckpt_badge = QLabel("자동 선택됨")
   self._lbl_ckpt_badge.setStyleSheet(
       "color:#34d399;font-size:11px;background:#0d2318;"
       "border:1px solid #10b981;border-radius:4px;padding:1px 6px;"
   )
   self._lbl_ckpt_badge.hide()
   toolbar_row1.addWidget(self._lbl_ckpt_badge)
   ```
   `self._btn_ckpt`의 버튼 텍스트는 그대로 "체크포인트 열기 (.pt)…" 유지(Artifact의 "변경…"은
   동일 기능의 다른 문구일 뿐 — 기존 문구가 더 명확하므로 문구는 바꾸지 않고 배치만 맞춘다).
6. Run 버튼에 accent 스타일 추가(228행 근처, 기존 `setStyleSheet` 교체):
   ```python
   self._btn_run.setStyleSheet(
       "background:#1e3a5f;border:1.5px solid #60a5fa;border-radius:5px;"
       "padding:6px 18px;color:#93c5fd;font-weight:bold;font-size:13.5px;"
   )
   ```
7. 추론 방식 고정 안내 텍스트 추가 — Run 버튼 앞에 stretch + 라벨:
   ```python
   toolbar_row1.addStretch()
   lbl_mode = QLabel("추론 방식: <b style='color:#cbd5e1'>sliding window</b> (고정)")
   lbl_mode.setStyleSheet("color:#9ca3af;font-size:11px;background:transparent;border:none;")
   toolbar_row1.addWidget(lbl_mode)
   toolbar_row1.addWidget(self._btn_run)
   ```
   (이 라벨은 3번 기획 항목 — sliding window 고정 선택 UI 제거 — 가 이미 코드에 반영돼
   콤보 자체는 없는 상태다. 지금은 "고정됐다"는 사실이 화면에 전혀 안내되지 않으므로
   Artifact대로 텍스트만 추가한다.)
8. `root.addLayout(toolbar_row1)` → `root.addWidget(ckpt_card)`로 교체(레이아웃이 아니라
   프레임을 추가하는 것으로 바뀜).

---

## 3. 편집 툴바 위치 — 상단 공용 영역 → 캔버스 전용 헤더로 이동

### 불일치
Artifact: 원편집/브러시그리기/브러시지우기/블랍삭제/팬/Undo 툴바와 "정렬(중심맞추기)" 버튼이
**중앙 캔버스 패널 상단**(캔버스 바로 위, 같은 카드 안)에 있다 — "이 도구들은 캔버스를 다루는
도구"라는 소속 관계가 시각적으로 명확하다. 코드: `self._edit_toolbar`가 `toolbar_row2`(295~340행,
AI신뢰도/픽셀threshold/민감도 슬라이더와 같은 행)에 붙어 있고, `self._btn_align`은 전혀 다른 곳
(우측 사이드바, 원 목록 위 — 429~431행)에 있다. 캔버스와 시각적으로 분리돼 있어 "이 버튼들이
캔버스 편집 도구"라는 관계가 레이아웃만 봐서는 드러나지 않는다.

### 구현 스펙
1. `toolbar_row2`에서 `self._edit_toolbar` 추가 줄(340행 `toolbar_row2.addWidget(self._edit_toolbar)`)
   **삭제**.
2. 우측 사이드바에서 `self._btn_align` 생성·배치 코드(429~431행)를 **삭제**(버튼 인스턴스
   자체는 유지, 배치 위치만 이동 — 아래 4번에서 재배치).
3. 중앙 캔버스를 감싸는 컨테이너 신규 생성 — 기존 `splitter.addWidget(self._canvas)`(420행)
   직전에 캔버스를 감쌀 `QWidget` + `QVBoxLayout`을 만들고, 그 안에 "편집 툴바 헤더" +
   "캔버스" 순서로 넣는다:
   ```python
   canvas_panel = QWidget()
   canvas_layout = QVBoxLayout(canvas_panel)
   canvas_layout.setContentsMargins(0, 0, 0, 0)
   canvas_layout.setSpacing(0)
   canvas_panel.setStyleSheet(
       "background:#1f2329;border:1px solid #374151;border-radius:8px;"
   )

   toolbar_header = QWidget()
   toolbar_header.setStyleSheet("background:#1f2329;border:none;border-bottom:1px solid #374151;")
   toolbar_header_layout = QHBoxLayout(toolbar_header)
   toolbar_header_layout.setContentsMargins(8, 5, 8, 5)
   toolbar_header_layout.addWidget(self._edit_toolbar)
   toolbar_header_layout.addStretch()
   self._btn_align = QPushButton("정렬(중심 맞추기)")
   self._btn_align.setToolTip("모든 원의 중심을 평균 중심으로 맞춥니다(반지름은 그대로).")
   toolbar_header_layout.addWidget(self._btn_align)
   canvas_layout.addWidget(toolbar_header)
   canvas_layout.addWidget(self._canvas, stretch=1)

   splitter.addWidget(canvas_panel)   # 기존 splitter.addWidget(self._canvas) 대체
   ```
   (`self._btn_align = QPushButton(...)` 생성 코드를 여기로 옮겼으므로 기존 429~431행의
   생성 코드는 삭제하고 이 블록 하나로 합친다. 시그널 연결(`self._btn_align.clicked.connect
   (self._canvas.align_centers)`)은 기존 위치 그대로 유지 — 생성 순서만 `_build_ui()` 안에서
   이 지점 이후가 되도록 조정.)
4. `self._edit_toolbar`가 `QToolBar`라서 `QHBoxLayout`에 직접 `addWidget`하는 건 문제없다
   (`QToolBar`도 `QWidget` 서브클래스). 단, `QToolBar`를 일반 컨테이너 레이아웃 안에 넣으면
   `QMainWindow` 전용 스타일(그림자 등)이 적용 안 될 수 있으니, 기존 `self._edit_toolbar
   .setStyleSheet(...)`(276~279행, 최소 크기 지정)는 그대로 유지하면 충분하다(이미 커스텀
   스타일로 덮어쓰고 있어 영향 없음).

---

## 4. 좌측 이미지 패널 — 헤더/목록 스타일

### 불일치
Artifact: 헤더 행에 "② 이미지 (N)" 굵은 accent 라벨 + 작은 아이콘 버튼 2개(파일/폴더 추가,
26×24px). 각 목록 행에 26px 썸네일 placeholder + 파일명 + 상시 보이는 "×" 삭제 아이콘.
코드: 전체 너비 텍스트 버튼 2개("이미지 열기…"/"폴더 열기…", open_row, 366~371행) + 별도
경로 안내 라벨(`_lbl_folder_path`). `InferenceImageList`(`inference_image_list.py`)는
`QTreeWidget` 기반이며 행마다 14px 상태 아이콘 + 파일명만 있고 **썸네일도, 상시 보이는
삭제 아이콘도 없다** — 삭제는 Delete 키 또는 우클릭 컨텍스트 메뉴로만 가능(스펙 설계가
의도한 그대로지만, Artifact가 보여준 "눈에 보이는 × 버튼"과는 발견성이 다르다).

### 구현 스펙 — 2단계로 분리(영향 범위가 다름)

**(a) 헤더 — `zone_analysis_tab.py`만 수정, 영향 없음:**
```python
header_row = QHBoxLayout()
lbl_images_header = QLabel("② 이미지")
lbl_images_header.setStyleSheet("color:#60a5fa;font-weight:bold;background:transparent;border:none;")
header_row.addWidget(lbl_images_header)
header_row.addStretch()
self._btn_image = QPushButton("+")
self._btn_image.setToolTip("이미지 추가")
self._btn_image.setFixedSize(26, 24)
self._btn_folder = QPushButton("⊞")
self._btn_folder.setToolTip("폴더 추가")
self._btn_folder.setFixedSize(26, 24)
header_row.addWidget(self._btn_image)
header_row.addWidget(self._btn_folder)
left_layout.addLayout(header_row)
```
(기존 `open_row` 블록 366~371행을 이걸로 교체. `self._lbl_folder_path`는 유지하되 헤더
바로 아래 작은 보조 텍스트로 남겨둔다 — 이미 11px 회색 스타일이라 추가 변경 불필요.)
헤더 라벨의 "(N)" 개수는 `_after_list_load()`/`_on_images_removed()` 끝에
`lbl_images_header.setText(f"② 이미지 ({self._img_list.count()})")`로 갱신(인스턴스 변수로
보관 필요: `self._lbl_images_header = lbl_images_header`).

**(b) 목록 행 상시 삭제 아이콘 — `inference_image_list.py` 변경, 추론 탭도 영향받음(결정 필요 아님,
저위험 — 아래 설명):**
실제 이미지 썸네일 로딩(디코드+스케일+캐시)은 이번 요청 범위를 벗어나는 별도 기능으로 판단해
**스킵한다**(YAGNI — Artifact의 26px 회색 사각형은 "썸네일이 들어갈 자리가 있다"는 레이아웃
의도였지, 실제 이미지 디코딩 요구가 아니었다. 실제로 필요해지면 `QPixmapCache` 기반 지연
로딩을 추가할 자리로 남겨둔다). 대신 **상시 보이는 삭제 아이콘만** 추가한다 — 이쪽이
Artifact가 보여주려던 핵심(발견성 있는 삭제 동작)에 더 가깝고 비용은 훨씬 낮다:
```python
# _make_leaf_item() 안, item 생성 후
del_label = QLabel("×")
del_label.setStyleSheet("color:#6b7280;padding:0 3px;")
del_label.setCursor(Qt.CursorShape.PointingHandCursor)
self._tree.setItemWidget(item, 1, del_label)   # 컬럼 1 신규 — setColumnCount(2) 필요
```
(트리가 현재 1컬럼이면 `self._tree.setColumnCount(2)` + 컬럼0은 Stretch, 컬럼1은 고정폭
20px로 `header().setSectionResizeMode()` 조정 필요. 클릭 핸들러는 `del_label.mousePressEvent`를
람다로 오버라이드하거나 `eventFilter`에 컬럼1 클릭 감지를 추가 — 기존 `_remove_selected()`를
그대로 재사용(해당 item만 골라 동일 로직 호출).) 이 변경은 `InferenceImageList`가
`inference_tab.py`와 공유되는 위젯이라 추론 탭에도 상시 "×"가 나타난다 — **부작용이 아니라
의도된 확장**으로 간주(기존 설계 로그 2026-10-01 항목에 이미 "추론 탭에서도 자연스러운 기능
확장으로 간주, 검증 단계에서 가볍게 확인"이라고 명시돼 있음, 추가 결정 불필요).

---

## 5. "Zone 결정 방법" 박스 — 레시피 버튼 강조 누락

### 불일치
Artifact: "원(Zone) 설정…(레시피)" 버튼에 원 모양 아이콘 + accent 테두리(`#60a5fa`)/텍스트색
(`#93c5fd`) — 이 버튼이 ③ 영역 설정 단계의 핵심 진입점임을 강조. 코드(394~399행):
`self._btn_recipe = QPushButton("원(Zone) 설정...")` — 아이콘 없음, 일반 버튼 스타일 그대로.

### 구현 스펙
```python
from app.widgets.icons import icon as svg_icon   # 이미 파일 상단에 import돼 있음(60행)
...
self._btn_recipe = QPushButton(svg_icon("tool_polygon"), "원(Zone) 설정...")
self._btn_recipe.setStyleSheet(
    "background:#2b313a;border:1px solid #60a5fa;border-radius:5px;"
    "padding:6px 8px;color:#93c5fd;"
)
```
(`tool_polygon` 아이콘은 이미 `_act_circle` 툴바 액션이 쓰고 있는 "원 편집" 아이콘과 동일 —
의미상 "원을 다룬다"는 연상이 자연스러워 신규 아이콘 없이 재사용 가능.)

---

## 6. 우측 패널 — 존 비율을 플레인 텍스트로만 표시 (색상 바 없음)

### 불일치
Artifact: 존마다 (이름 + 색상 적용된 굵은 %) 행 + 그 아래 색상 채워진 가로 바(비율에 비례한
너비, 값에 따라 amber/green 등 색 구분). 코드(`_recompute_zones()`, 991~1013행): `self._zone_list
.addItem(f"{zone_name}  —  {pct:.2f}%")` — **플레인 텍스트 한 줄**, 색상도 바 그래프도 전혀 없다.

### 구현 스펙
`_recompute_zones()`의 아이템 생성부를 커스텀 위젯으로 교체(기존 `currentRowChanged` 시그널
배선은 `QListWidget` API라 그대로 유지되므로 `_on_zone_row_selected`/`_on_canvas_zone_clicked`
연결부는 변경 불필요):

```python
def _make_zone_row_widget(self, zone_name: str, pct: float) -> QWidget:
    color = "#fbbf24" if pct >= 10.0 else "#34d399"   # 임계값은 시각 구분용 — 기존 판정 로직과 무관
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(6, 4, 6, 4)
    v.setSpacing(3)
    top = QHBoxLayout()
    lbl_name = QLabel(zone_name)
    lbl_pct = QLabel(f"{pct:.1f}%")
    lbl_pct.setStyleSheet(f"color:{color};font-weight:bold;")
    top.addWidget(lbl_name)
    top.addStretch()
    top.addWidget(lbl_pct)
    v.addLayout(top)
    bar_bg = QWidget()
    bar_bg.setFixedHeight(6)
    bar_bg.setStyleSheet("background:#1a1d23;border-radius:3px;")
    bar_layout = QHBoxLayout(bar_bg)
    bar_layout.setContentsMargins(0, 0, 0, 0)
    fill = QWidget()
    fill.setStyleSheet(f"background:{color};border-radius:3px;")
    bar_layout.addWidget(fill, stretch=max(1, round(min(pct, 100))))
    if pct < 100:
        spacer = QWidget()
        bar_layout.addWidget(spacer, stretch=max(1, round(100 - min(pct, 100))))
    v.addWidget(bar_bg)
    return w
```
`_recompute_zones()`의 루프를 `addItem(f"...")` 대신:
```python
for zone_name, pct in pct_rows:
    item = QListWidgetItem()
    item.setSizeHint(QSize(0, 40))
    self._zone_list.addItem(item)
    self._zone_list.setItemWidget(item, self._make_zone_row_widget(zone_name, pct))
```
(`QSize`는 파일 상단에 이미 import돼 있음 — 37행 `from PyQt6.QtCore import ... QSize` 확인됨.)

추가로 `_btn_export_single`("결과 분석 보기", 440~442행)에 accent 스타일 추가:
```python
self._btn_export_single.setStyleSheet(
    "background:#1e3a5f;border:1.5px solid #60a5fa;border-radius:5px;"
    "padding:7px 8px;color:#93c5fd;font-weight:bold;"
)
```

---

## 7. 레시피 팝업(`zone_recipe_dialog.py`)

### 불일치 목록
| Artifact | 코드 | 비고 |
|---|---|---|
| 레시피 영역이 테두리 있는 박스(타이틀 "레시피")로 2행 분리(콤보+불러오기 / 이름+저장) | `recipe_row` 한 줄에 라벨+콤보+불러오기+이름입력+저장 전부(93~105행) | 박스/2행 분리 없음 |
| Undo가 아이콘 버튼, 우측 끝 배치(앞에 stretch) | `self._btn_undo = QPushButton("Undo")`(89행), 정렬 버튼 바로 옆, stretch 없음 | 영문 텍스트, 위치도 다름 |
| "메인 탭에 적용" 버튼 accent 강조(파랑 배경/테두리) | `setStyleSheet("font-weight:bold;")`만(112행) | 강조 없음 |
| 하단에 "원이 1개 이상 있어야 활성화" 설명 캡션 | 없음 | — |

### 구현 스펙
1. `recipe_row` 블록(93~105행)을 `QGroupBox`로 교체:
   ```python
   recipe_box = QGroupBox("레시피")
   recipe_box_layout = QVBoxLayout(recipe_box)
   row1 = QHBoxLayout()
   self._recipe_combo = QComboBox()
   self._recipe_combo.setMinimumWidth(160)
   row1.addWidget(self._recipe_combo, stretch=1)
   self._btn_load_recipe = QPushButton("불러오기")
   row1.addWidget(self._btn_load_recipe)
   recipe_box_layout.addLayout(row1)
   row2 = QHBoxLayout()
   self._name_edit = QLineEdit()
   self._name_edit.setPlaceholderText("레시피 이름")
   row2.addWidget(self._name_edit, stretch=1)
   self._btn_save_recipe = QPushButton("저장")
   row2.addWidget(self._btn_save_recipe)
   recipe_box_layout.addLayout(row2)
   caption = QLabel("팝업을 열면 가장 최근 사용한 레시피가 자동으로 표시됩니다.")
   caption.setStyleSheet("color:#6b7280;font-size:10.5px;")
   recipe_box_layout.addWidget(caption)
   root.addWidget(recipe_box)
   ```
   (`QGroupBox`/`QLabel` import는 이미 파일 상단에 `QLabel` 있음 — `QGroupBox`만 추가 필요.)
2. Undo 버튼을 아이콘으로 교체 + 우측 정렬:
   ```python
   from app.widgets.icons import icon as svg_icon
   ...
   detect_row.addStretch()
   self._btn_undo = QPushButton(svg_icon("undo"), "")
   self._btn_undo.setToolTip("실행 취소 (Ctrl+Z)")
   self._btn_undo.setFixedSize(30, 26)
   detect_row.addWidget(self._btn_undo)
   ```
   (`detect_row.addStretch()`를 `self._btn_align`을 추가한 다음, `self._btn_undo` 추가하기 전에
   삽입 — 기존 87~90행 순서 중 stretch만 끼워 넣고 undo 버튼 생성 코드를 위 코드로 교체.)
3. `self._btn_apply` 스타일(112~113행) 교체:
   ```python
   self._btn_apply.setStyleSheet(
       "background:#1e3a5f;border:1.5px solid #60a5fa;border-radius:5px;"
       "padding:7px 18px;color:#93c5fd;font-weight:bold;"
   )
   ```
4. `bottom_row` 다음에 캡션 추가:
   ```python
   footer_caption = QLabel(
       "\"메인 탭에 적용\"은 원이 1개 이상 있을 때만 활성화됩니다 — 영역 없이 "
       "진행하는 경로를 이 팝업에서 차단합니다. \"취소\"는 항상 가능합니다."
   )
   footer_caption.setWordWrap(True)
   footer_caption.setStyleSheet("color:#6b7280;font-size:10px;")
   root.addWidget(footer_caption)
   ```

**낮은 우선순위(생략 가능)**: `self._lbl_stats`("원 개수: N") 위치를 캔버스 오버레이로 옮기는 것은
이번 스펙에서 강제하지 않는다 — 별도 QLabel로 캔버스 아래 두는 현재 배치도 기능상 문제
없고, Artifact는 공간 배치 예시였을 뿐 이 위치가 핵심 디자인 결정은 아니었다.

---

## 8. 진행상황 팝업 — ETA 없음, 창 제목 없음

### 불일치
Artifact: "처리 중: N/total" + 진행바(%) + **"예상 남은 시간: 약 1분 32초"**. 코드
(`_on_batch_process()`/`_on_batch_progress()`, 1233~1266행): `QProgressDialog`에 라벨 텍스트
`f"{done} / {total}  {path.name}"`만 설정 — **ETA 텍스트 자체가 없다.** 창 제목(`setWindowTitle`)도
설정돼 있지 않다(OS 기본 타이틀바 텍스트로 뜸).

### 구현 스펙
1. `__init__`에 타이머 참조 추가 불필요 — `QElapsedTimer`를 배치 시작 시점에 생성:
   ```python
   from PyQt6.QtCore import QElapsedTimer   # 파일 상단 QtCore import에 추가
   ```
2. `_on_batch_process()`에서 `self._batch_progress = QProgressDialog(...)` 생성 직후:
   ```python
   self._batch_progress.setWindowTitle("일괄 처리 진행 중")
   self._batch_elapsed = QElapsedTimer()
   self._batch_elapsed.start()
   ```
3. `_on_batch_progress()`의 라벨 텍스트 설정부(1259행)를 교체:
   ```python
   eta_txt = ""
   if done > 0:
       avg_ms = self._batch_elapsed.elapsed() / done
       remain_s = max(0, avg_ms * (total - done) / 1000.0)
       m, s = divmod(int(remain_s), 60)
       eta_txt = f"\n예상 남은 시간: 약 {m}분 {s}초" if m else f"\n예상 남은 시간: 약 {s}초"
   dlg.setLabelText(f"{done} / {total}  {path.name}{eta_txt}")
   ```
   (`QProgressDialog`의 라벨은 멀티라인 텍스트를 그대로 지원 — `\n` 두 줄로 표시됨.)

**참고(스코프 명확화)**: 단일 이미지 "▶ 추론 실행"(`_on_run()`)은 인라인 `QProgressBar`
(`self._infer_progress`, 223~226행)를 쓰고 모달 팝업을 띄우지 않는다 — Artifact의
Progress.dc.html은 **배치 처리** 흐름(`_on_batch_process`)에 해당하는 디자인이고, 단일 이미지
흐름은 원래부터 범위 밖이다(빠른 작업이라 모달이 필요 없다는 기존 판단 유지, 변경 없음).

---

## 9. 결과 분석 팝업(`zone_batch_result_dialog.py`)

### 불일치 목록
| Artifact | 코드 | 비고 |
|---|---|---|
| 다이얼로그 1000×760, 여유 있는 레이아웃 | `self.resize(640, 520)`(46행) | 가로/세로 모두 절반 수준으로 빽빽함 |
| 필터 바에 굵은 "필터" 라벨 prefix | 없음(검색창이 바로 시작, 83~87행) | — |
| 존 필터가 pill 모양 칩(선택시 accent 배경, 미선택시 점선 테두리) | `QPushButton(checkable=True)` 기본 스타일(91~97행) — `main.py`엔 `QPushButton:checked` QSS 자체가 없음 | 체크 상태가 시각적으로 거의 안 보임 |
| 탭 라벨 "Long (이미지 × 존)" / "Wide (피벗)" | "목록별 (Long)" / "이미지별 (Wide)"(60~61행) | 문구 다름 |
| 상단에 "총 N개 행" 라벨 없음(필터 카운터로 충분) | `QLabel(f"총 {len(rows)}개 행 (이미지 × 존)")`(55행) | Artifact 대비 중복 요소 |
| 테이블 그룹 경계(굵은 실선) vs 존 구분(점선) 구분 | `setSpan()`만 적용, 테두리 구분 없음(기본 gridline 전부 동일) | 구조는 맞지만 시각적 강약 없음 |
| 테이블 아래 설명 캡션 | 없음 | — |

구조적으로 가장 중요한 두 가지(① 같은 이미지 존 행 그룹화 `setSpan()`, ② 이미지명+존 필터)는
**이미 정확히 구현돼 있다** — 2026-10-01 수정 요청이 반영된 상태. 이번 불일치는 전부 스타일/
문구 수준이다.

### 구현 스펙
1. 다이얼로그 크기(46행):
   ```python
   self.resize(1000, 700)
   ```
2. 탭 라벨(60~61행):
   ```python
   tabs.addTab(self._build_long_tab(rows, self._blob_rows), "Long (이미지 × 존)")
   tabs.addTab(self._build_wide_tab(rows), "Wide (피벗)")
   ```
3. 55행 `layout.addWidget(QLabel(f"총 {len(rows)}개 행 (이미지 × 존)"))` **삭제** — 필터 바의
   `self._lbl_filter_count`가 이미 "N / 전체" 형태로 같은 정보를 보여주므로 중복.
4. `_build_filter_bar()`(81~106행) 맨 앞에 굵은 "필터" 라벨 추가:
   ```python
   bar = QHBoxLayout()
   lbl_filter = QLabel("필터")
   lbl_filter.setStyleSheet("color:#9ca3af;font-weight:bold;")
   bar.addWidget(lbl_filter)
   ```
5. 존 토글 버튼을 pill 스타일로(91~97행 루프 안, `btn = QPushButton(zone)` 다음 줄에 추가):
   ```python
   btn.setStyleSheet("""
       QPushButton { background:#2b313a; border:1px dashed #4b5563; border-radius:12px;
                     padding:2px 10px; color:#9ca3af; }
       QPushButton:checked { background:#1e3a5f; border:1px solid #60a5fa;
                             color:#93c5fd; }
   """)
   ```
   (이 스타일은 이 다이얼로그 로컬에만 적용 — `main.py` 전역 QSS는 건드리지 않는다. 전역에
   `QPushButton:checked` pill 스타일을 추가하면 다른 탭의 체크 가능 버튼에도 영향을 줄 수
   있어 범위를 좁게 유지.)
6. 테이블 그룹 시각 구분(`_build_long_tab()`, 145~160행) — `QTableWidget`에서 셀 단위로 테두리
   굵기를 다르게 주는 것은 `setStyleSheet`만으로는 어렵다. **대안으로 이미지 그룹마다 행
   배경을 교대로 칠한다**(그룹 2개 색 `#111418`/`#15181d` 교대) — Artifact가 의도한
   "그룹 경계 vs 존 구분"의 강/약 구분을 선·배경 두 가지 중 배경 쪽으로 구현하는
   실용적 타협안(완전히 동일한 픽셀 재현은 `QTableWidget` 밖에서 커스텀 델리게이트를
   써야 해서 과설계 — 이 수준이면 충분히 "그룹이 눈에 띄게 묶여 보인다"는 목적 달성):
   ```python
   group_colors = ["#111418", "#15181d"]
   group_idx = 0
   start = 0
   for r in range(1, len(sorted_rows) + 1):
       at_boundary = r == len(sorted_rows) or sorted_rows[r][0] != sorted_rows[start][0]
       if at_boundary:
           color = group_colors[group_idx % 2]
           for rr in range(start, r):
               for cc in range(4):
                   item = table.item(rr, cc)
                   if item is not None:
                       item.setBackground(QColor(color))
           if r - start > 1:
               table.setSpan(start, 0, r - start, 1)
           group_idx += 1
           start = r
   ```
   (`QColor`를 `PyQt6.QtGui`에서 import 추가 필요. 기존 `setSpan` 호출부를 이 블록으로
   통합 — 중복 루프 제거.)
7. 테이블 아래 설명 캡션 추가(`_build_long_tab()` 리턴 직전, 컨테이너로 감싸야 함 — 현재
   `_build_long_tab`이 `table` 자체를 반환하므로, 캡션을 포함하려면 `QWidget` 컨테이너로
   감싸는 작은 리팩터링 필요):
   ```python
   container = QWidget()
   v = QVBoxLayout(container)
   v.setContentsMargins(0, 0, 0, 0)
   v.addWidget(table, stretch=1)
   caption = QLabel(
       "\"최대 blob 픽셀수\"는 해당 (이미지, 존) 안에서 가장 큰 연결 영역 1개의 "
       "픽셀 수입니다 — 존재하지 않으면 0."
   )
   caption.setStyleSheet("color:#6b7280;font-size:10.5px;")
   v.addWidget(caption)
   self._long_table = table
   return container
   ```
   (`self._long_table`은 기존처럼 실제 `QTableWidget` 인스턴스를 계속 가리키므로
   `_apply_filter()`의 `self._long_table.setRowHidden(...)` 호출부는 변경 불필요.)

---

## 10. 작업 순서 제안

파일 겹침 기준 + 위험도 낮은 순:

| 순서 | 내용 | 파일 |
|---|---|---|
| 1 | 결과 분석 팝업 스타일(9번) | `zone_batch_result_dialog.py` |
| 2 | 레시피 팝업 스타일(7번) | `zone_recipe_dialog.py` |
| 3 | 진행상황 ETA(8번) | `zone_analysis_tab.py` (배치 처리 부분만) |
| 4 | 체크포인트 바(2번) + Zone 설정 버튼 강조(5번) + 우측 비율 바(6번) | `zone_analysis_tab.py` |
| 5 | 편집 툴바 위치 이동(3번) — 레이아웃 구조 변경이라 4번 이후 진행 권장(같은 파일, 충돌 줄임) | `zone_analysis_tab.py` |
| 6 | 좌측 패널 헤더(4-a번) | `zone_analysis_tab.py` |
| 7 | 좌측 패널 상시 삭제 아이콘(4-b번) — 공유 위젯이라 마지막, 추론 탭 회귀 확인 필요 | `inference_image_list.py` |
| 8 | **스텝 인디케이터(1번, 최우선 기능이지만 신규 파일이라 다른 항목과 충돌 없음 — 아무 순서에나 끼워도 무방, 번호는 설명 순서일 뿐 작업 순서 아님)** | `zone_step_indicator.py`(신규), `zone_analysis_tab.py` |

각 항목 구현 후 `python main.py`로 Zone(상/하부 분석) 탭을 열어 레이아웃이 깨지지 않는지
확인 권장(CLAUDE.md "구현 완료 후 검증 필수"). 이번 라운드는 "주요 기능 추가"가 아니라
비주얼 조정이므로 검증은 정적 리뷰 + 실행 확인 수준으로 충분 — 단, 7번(공유 위젯 변경)은
추론 탭에서도 목록이 정상 표시되는지 가볍게 확인할 것.

---

## 11. 의도적으로 Artifact와 다르게 둔 것 (결정 사항, 변경 아님)

1. **이미지 썸네일(실제 디코딩) 미구현** — Artifact의 26px 회색 사각형은 레이아웃 자리
   예시였을 뿐, 실제 이미지 디코드 요구는 아니었다고 판단. 대신 상시 삭제 아이콘(4-b)만
   추가해 "발견 가능한 삭제 동작"이라는 핵심 의도는 보존. 나중에 실제 썸네일이 필요해지면
   `QPixmapCache` 기반 지연 로딩을 이 자리에 추가하면 된다.
2. **결과 분석 팝업 테이블의 그룹 경계 vs 존 구분을 선 굵기 대신 배경색 교대로 구현** —
   `QTableWidget` 기본 델리게이트로는 셀 단위 테두리 굵기 제어가 번거로워 과설계 위험,
   배경색 교대로도 "그룹이 묶여 보인다"는 목적은 동일하게 달성.
3. **체크포인트 버튼 문구는 "변경…"으로 바꾸지 않고 기존 "체크포인트 열기 (.pt)…" 유지** —
   기능은 동일하고 기존 문구가 더 명확.

이 3가지는 구현 에이전트가 추가로 사용자 확인을 받을 필요 없음(저위험 — 이미 이 문서에서
근거와 함께 확정).
