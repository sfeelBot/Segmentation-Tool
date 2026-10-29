# 공유 위젯 추출 — 브러시 툴바 / 뷰어 pan·zoom / 이미지 리스트 (2026-10-27)

사용자 요청(3라운드 확인 완료, 재확인 불필요). 라벨링 탭의 툴바·뷰어·이미지 리스트를
재사용 가능한 위젯으로 뽑아 추론 탭(+차후 존분석/R분석 탭)에도 적용한다.

**이번 라운드(1단계) 범위: main 브랜치만.** 대상 파일 — `labeling_tab.py`,
`inference_tab.py`, `annotation_canvas.py`, `overlay_viewer.py`, `image_browser.py`
(제거), `inference_image_list.py`(확장), 신규 `app/widgets/brush_toolbar.py` +
`app/widgets/view_transform.py`. `zone_analysis_tab.py`/`r_analysis_tab.py`
(에디션 브랜치 `feature/zone-analysis-tab`)는 **2단계**(아래 참고, 이번에 구현하지 않음).

결정 대기 없음 — 설계 재량 사항은 이 문서에서 플래너가 전부 판단해 명시함(근거 포함).

---

## 1. 공유 브러시 툴바 — `app/widgets/brush_toolbar.py` (신규)

### 1.1 범위 판단 (설계 재량)

사용자가 확정한 것: 공통 도구(브러시그리기/지우개/undo/pan/브러시크기)는 동작까지 통일,
flood-eraser(라벨링)와 blob-delete(존분석)는 동일 동작으로 통합, bucket-fill은 재량,
OK·1차 도형 도구·select는 공유 위젯 밖. 재량이 필요했던 나머지(clear/auto/eye/
fullscreen, bucket-fill)는 아래처럼 전부 **공유 위젯 밖**으로 결정했다.

**이유**: 이번 라운드 시점 기준 공유 위젯의 실질 소비자는 라벨링 탭 1개뿐이다(존분석·
R분석은 2단계, 추론 탭은 명시적으로 제외). clear/auto/eye/fullscreen은 다른 두 탭에
대응 기능이 없거나(auto-label 다이얼로그는 라벨링 전용 개념) 의미가 달라질 수 있는
기능(eye 토글은 라벨링엔 `AnnotationCanvas.toggle_overlay_visible()`, 추론엔 이미 다른
구현인 `F` 키 오버레이 토글이 따로 있음)이라, 지금 공유 위젯에 포함하면 소비자 1개를
위한 추측성 옵션 플래그가 된다(YAGNI). bucket-fill도 존/R에 대응 개념이 없으므로 동일
논리로 제외 — 라벨링 탭 전용 버튼으로 툴바에 남긴다.

**공유 위젯에 포함**(4개 탭 중 라벨링·존분석·R분석 공통 요소만, 추론 탭은 위젯 자체를
쓰지 않음):
- `TOOL_BRUSH`(브러시 그리기), `TOOL_ERASER`(지우개), `TOOL_ERASER_FLOOD`(영역삭제 —
  라벨링의 flood-fill과 존분석의 blob-delete를 "클릭한 연결영역 전체 삭제"라는 같은
  개념으로 통합한 공유 액션/아이콘/툴팁. **주의**: 실제 구현(raster flood-fill vs
  벡터 blob 제거)은 캔버스 데이터 모델이 달라 이번 라운드에서 알고리즘까지 합치지
  않는다 — 공유 범위는 툴바의 액션/아이콘/시그널 계약이고, 캔버스별 실행 로직은
  각자 유지한다. 존분석 쪽 통합은 2단계에서 실제로 `set_blob_delete_mode()` 를 이
  공유 시그널에 연결하는 작업이 될 것), `TOOL_PAN`(이동)
- 브러시 크기 `QSpinBox`, undo 버튼
- R분석 탭은 영역삭제 개념이 없으므로(배경 조사 확인됨) `show_delete_region=False` 로
  끔 — 유일하게 실재 근거가 있는 변동 지점이라 플래그로 둠(추측성 아님)

**공유 위젯에서 제외**(각 탭이 자신의 QToolBar에 직접 배치):
- 1차 도형 도구(폴리곤/원/ROI) — 사용자가 명시적으로 제외 확정
- select(라벨링 전용) — 존/R에 대응 기능 없음, 폴리곤과 같은 논리로 호스트 로컬 유지
- bucket-fill(브러시채움, 라벨링 전용)
- OK 토글 — 사용자가 명시적으로 제외 확정
- clear/auto/eye/fullscreen — 위 이유로 제외

### 1.2 Public API

```python
# app/widgets/brush_toolbar.py
TOOL_BRUSH        = "brush"
TOOL_ERASER       = "eraser"
TOOL_ERASER_FLOOD = "eraser_flood"
TOOL_PAN          = "pan"

class BrushToolbar(QObject):
    """기존 QToolBar에 브러시/지우개/영역삭제/pan/undo/브러시크기 액션을 꽂아주는
    컨트롤러. 자체 QWidget이 아님 — 호스트가 만든 QToolBar에 addAction()/addWidget()
    으로 삽입하므로 기존 단일 행 툴바 레이아웃을 그대로 유지할 수 있다."""

    tool_changed       = pyqtSignal(str)   # 사용자가 클릭으로 브러시/지우개/영역삭제/pan 중 하나를 선택
    brush_size_changed = pyqtSignal(int)   # 스핀박스를 사용자가 직접 바꿨을 때만 emit
    undo_requested      = pyqtSignal()

    def __init__(self, toolbar: QToolBar, *, show_delete_region: bool = True,
                 brush_size_range: tuple[int, int] = (1, 200), parent=None) -> None: ...

    # 공개 속성(기존 코드 관례상 QAction/QSpinBox 직접 접근 — _canvas._tool 같은
    # 기존 직접 접근 패턴과 동일 스타일. 호스트가 자기 QActionGroup/수동 토글 루프에
    # 포함시키기 위해 반드시 외부에 노출해야 함):
    #   self.act_brush, self.act_eraser, self.act_delete_region(옵션),
    #   self.act_pan, self.act_undo, self.spin_brush_size

    def current_tool(self) -> str: ...
    def set_tool(self, tool: str) -> None:
        """tool이 이 클러스터 소속이면 그 액션만 checked, 아니면(호스트 로컬 도구가
        활성화된 경우) 클러스터 전체 unchecked. tool_changed는 재발행하지 않음 —
        호스트가 자기 쪽 도구 전환 시 동기화 호출용."""
    def set_brush_size(self, value: int) -> None:
        """캔버스→스핀박스 역동기화. blockSignals로 루프 방지(기존
        `_canvas.brush_size_changed.connect(self._spin_brush.setValue)` 패턴과 동등)."""
```

- `TOOL_BRUSH`/`TOOL_ERASER`/`TOOL_ERASER_FLOOD`/`TOOL_PAN` 문자열은 기존
  `annotation_canvas.py`에 있던 동일 이름 상수를 그대로 이 모듈로 옮긴 것(값 불변).
  `annotation_canvas.py`는 이 4개를 여기서 import하고, `TOOL_POLYGON`/
  `TOOL_BRUSH_FILL`/`TOOL_SELECT` 3개는 그대로 자기 모듈에 남긴다. 확인됨: 이 4개
  상수를 외부에서 import하는 곳은 `annotation_canvas.py` 자신과 `labeling_tab.py`
  뿐(grep 확인) — 이동해도 깨지는 외부 참조 없음.
- 아이콘: `tool_brush`/`tool_eraser`/`tool_eraser_flood`/`tool_pan` 기존 SVG 그대로
  재사용(이미 `zone_analysis_tab.py`가 blob-delete에 `tool_eraser_flood` 아이콘을 쓰고
  있어 시각적으로도 이미 통일돼 있었음 — 이번 통합이 자연스러움을 뒷받침).
- 삭제 영역 버튼의 툴팁 문구는 탭마다 다름("영역지우개" vs "블랍삭제") — 생성자 파라미터로
  만들지 않고 호스트가 생성 후 `act_delete_region.setToolTip(t(...))`로 덮어쓰게 둔다
  (불필요한 생성자 옵션 추가 방지).

### 1.3 `labeling_tab.py` 변경

- `_build_toolbar()`: 기존 `tool_action()` 헬퍼로 만들던 `_act_brush`/`_act_eraser`/
  `_act_eraser_flood`/`_act_pan`과 `_spin_brush`/undo `QAction`을 제거하고, 같은
  `QToolBar` 인스턴스를 `BrushToolbar(tb, show_delete_region=True)`에 넘겨 생성.
  `_act_polygon`/`_act_brush_fill`/`_act_select`는 호스트 로컬로 그대로 유지,
  `tb.addAction()`으로 기존과 동일하게 추가(시각적 순서는 완전히 동일하게 유지할
  필요는 없음 — 공유 클러스터를 한 덩어리로 묶어 폴리곤/select/fill 사이에 삽입하는
  정도의 아이콘 재배치는 구현 단계의 소소한 재량, 숨겨진 기능 없이 전부 보이면 충분).
- `_set_tool(tool)`: 호스트 로컬 도구(polygon/select/fill) 체크 루프는 유지하고,
  `self._brush_tools.set_tool(tool)` 호출을 추가해 클러스터 체크 상태 동기화.
  `self._brush_tools.tool_changed.connect(self._set_tool)`로 역방향 연결.
- `self._brush_tools.undo_requested.connect(self._canvas.undo)`,
  `self._brush_tools.spin_brush_size.valueChanged.connect(self._canvas.set_brush_size)`,
  `self._canvas.brush_size_changed.connect(self._brush_tools.set_brush_size)` 로 기존
  시그널 연결 이전.
- `self._act_eraser_flood` 등 이전 속성 참조(`_connect_signals()`/`_set_tool()`/
  키보드 숫자단축키 핸들러, 대략 684~696번째 줄 부근)를 `self._brush_tools.act_*`
  참조로 치환.
- 스핀박스 폭 고정(`setMinimumWidth(76)`, GitHub #3(a))과 더블클릭 브러시크기 조절
  (GitHub #3(b), `annotation_canvas.py`의 `mouseDoubleClickEvent` → `brush_size_changed`
  시그널)은 캔버스 쪽 로직이라 이번 이동과 무관 — `BrushToolbar.spin_brush_size`
  생성 시 `setMinimumWidth(76)`을 그대로 넣을 것(회귀 방지 포인트, 놓치기 쉬움).

---

## 2. 뷰어 pan/zoom 공통 로직 — `app/widgets/view_transform.py` (신규)

### 2.1 범위 판단

전체 재작성 금지 지시에 따라 **순수 좌표계산 함수만** 추출한다. `AnnotationCanvas`와
`OverlayViewer`는 그대로 별도 클래스 유지, `self._zoom`/`self._pan`/`_pan_active`
등 상태 필드도 각자 그대로 보유 — 이 모듈은 상태 없는(stateless) 계산 유틸일 뿐이다.
조사 결과 두 클래스의 wheel-zoom·fit-view·pan-drag·canvas→image 좌표변환 공식이
**글자 그대로 동일**(`MIN_ZOOM=0.05`/`MAX_ZOOM=20.0` 상수값까지 일치) — 복붙 중복이
확인됐으므로 추출 리스크가 낮다.

### 2.2 Public API

```python
# app/widgets/view_transform.py
MIN_ZOOM = 0.05
MAX_ZOOM = 20.0

def canvas_to_content(canvas_pt: QPointF, pan: QPointF, zoom: float) -> QPointF: ...
def wheel_zoom(mouse_canvas: QPointF, pan: QPointF, zoom: float, angle_delta_y: int,
               min_zoom: float = MIN_ZOOM, max_zoom: float = MAX_ZOOM) -> tuple[float, QPointF]: ...
def fit_view(view_w: int, view_h: int, content_w: float, content_h: float,
             margin: float = 0.95) -> tuple[float, QPointF]: ...
def pan_drag(pan_start_offset: QPointF, pan_start_mouse: QPointF, current_mouse: QPointF) -> QPointF:
    return pan_start_offset + (current_mouse - pan_start_mouse)
```

### 2.3 변경 지점 (각 파일에서 정확히 이 메서드 본문만 교체 — 그 외 라인 건드리지 않음)

- `annotation_canvas.py`: `_c2i()`, `wheelEvent()`의 zoom/pan 재계산 2줄,
  `_fit_view()`, `mouseMoveEvent()`의 pan 드래그 1줄. **GitHub #9 수정 블록
  (`if self._pan_active: self._pan_start_mouse = ...`) 은 그대로 보존** — 이건
  `wheel_zoom()` 호출 다음에 오는 호스트 쪽 후처리로 남는다, 절대 삭제 금지.
  로컬 `MIN_ZOOM`/`MAX_ZOOM` 정의 제거, `view_transform`에서 import.
- `overlay_viewer.py`: `wheelEvent()`, `mousePressEvent()`+`mouseMoveEvent()`의 pan
  드래그 1줄, `_fit_view()`. 로컬 `MIN_ZOOM`/`MAX_ZOOM` 정의 제거.
  **선택 사항(이번 라운드 필수 아님)**: `OverlayViewer.wheelEvent()`에는
  `AnnotationCanvas`가 GitHub #9에서 추가한 "드래그 중 휠 줌" 재동기화 블록이 없다
  (잠재적으로 같은 버그가 있을 수 있음, 다만 보고된 적 없음). 추출 작업 중 같이
  넣어도 되지만 범위 확장이므로 강제하지 않음 — 넣을 경우 검증 에이전트가 추론 탭
  pan+zoom 골든패스에 "드래그 중 휠 줌" 케이스를 추가로 확인할 것.
- 두 파일 모두 import 외 다른 줄 수는 늘지 않음 — 브러시 페인팅/undo스택/오버레이
  합성/투명도 슬라이더 등은 전혀 손대지 않는다.
- `ZoneCanvas`/`RRoiCanvas`(에디션 브랜치, `OverlayViewer` 상속)는 부모 클래스
  메서드를 그대로 쓰므로 **코드 변경 없이 자동으로 같은 유틸을 타게 됨** — 이번
  라운드에서 건드리지 않아도 2단계 sync 시 자연히 이득을 본다.

---

## 3. 이미지 리스트 완전 통합 — `inference_image_list.py` 확장(파일 유지, 신규 파일
   아님) + `image_browser.py` 제거

### 3.1 설계 재량 — 파일/클래스명 유지

`InferenceImageList`라는 이름이 이제 라벨링 탭에도 쓰여 다소 부적절해지지만, 이름
변경은 순수 리네임 처리 비용만 발생하고(2단계에서 존분석 탭도 같은 클래스를 import하고
있어 리네임하면 그쪽 sync 때 불필요한 충돌 유발) 기능적 이득이 없다 — 파일/클래스명
그대로 유지, 모듈 docstring만 "라벨링/추론(+존분석) 공용"으로 갱신.

### 3.2 신규 생성자 플래그 (2개로 제한 — 실제 쓰임이 확인된 변동 지점만 플래그화)

```python
def __init__(self, parent=None, *, show_status_icons: bool = False,
             editable: bool = False) -> None: ...
```

- `show_status_icons=False`(기본, 추론 탭 동작 불변): 상태 아이콘(●/✓/○)·범례 행·
  `status_done`/`status_todo` 정렬 모드 없음.
  `True`(라벨링 탭): `get_label_status()` 기반 아이콘+범례+정렬모드 추가, 상태 캐시
  `dict[Path, str]` 구축(`ImageBrowser._status_cache` 로직 그대로 포팅).
- `editable=False`(기본, 추론 탭 동작 불변): 파일추가/폴더추가/삭제 버튼 없음,
  `ExtendedSelection` 아님(기존 `SingleSelection` 유지).
  `True`(라벨링 탭): 상단 버튼 행(`+ 파일`/`+ 폴더`/`삭제`) 추가, `_FolderImportWorker`
  + 진행바/상태 라벨(`ImageBrowser`의 해당 블록 그대로 포팅), `ExtendedSelection`,
  `image_deleted` 시그널 실제 발행, `set_mutation_guard()`가 추가/삭제 진입점에서
  실제로 체크됨. **전제**: editable 모드는 항상 `_project.images_dir()`를 관리 대상
  루트로 가정(추가된 파일을 그 디렉터리로 copy2) — `load_folder(_project.images_dir())`
  로 초기화된 경우에만 의미가 있다. 다른 루트로 editable=True를 쓰는 상황은 이번
  소비자(라벨링 탭)에 없으므로 가드/문서화만 해두고 별도 방어 코드는 넣지 않는다.
- 두 플래그 다 `False`인 기존 `InferenceImageList()` 생성 코드(`inference_tab.py:241`)는
  **무변경** — 회귀 리스크 없음.

### 3.3 신규/변경 메서드 (전부 `ImageBrowser` 쪽 호출부 전수 조사 결과 기반,
    `labeling_tab.py`에서 `self._image_browser.*` 로 호출되는 모든 지점 커버 확인)

| 메서드 | 상태 | 비고 |
|---|---|---|
| `set_mutation_guard(guard)` | 신규, 항상 존재 | `editable=False`면 가드는 저장되지만 아무 진입점도 없어 실질 no-op |
| `has_list_focus() -> bool` | 신규, 항상 존재 | `self._tree.hasFocus()` |
| `selected_paths() -> list[Path]` | 신규, 항상 존재 | `ImageBrowser` 구현 그대로 포팅(표시 순서 기준, 선택 없으면 `[current_path()]`) |
| `refresh_item(path)` / `refresh_items(paths)` | 신규, 항상 존재 | `show_status_icons=False`면 상태 캐시가 없어 즉시 return(사실상 no-op) |
| `reload() -> None` | 신규 | `self._root`가 설정돼 있으면 `load_folder(self._root)` 재호출(편의 메서드, `ImageBrowser.reload()` 호출부 대체) |
| `delete_selected() -> None` | 신규(공개 메서드, 기존 `ImageBrowser._on_delete()`를 public으로) | `editable=False`면 아무 동작 안 함(버튼 자체도 없음). 삭제 버튼 클릭 슬롯과 키보드 Delete 경로가 모두 이 메서드를 호출 |
| `image_deleted = pyqtSignal(Path)` | 신규 시그널 | 항상 선언, `editable=True`일 때만 실제 발행 |
| Ctrl+C 파일명 복사(`eventFilter`) | 신규, 항상 설치 | `ImageBrowser`의 GitHub #17 구현 그대로 포팅, 추론 탭에도 부작용 없이 적용(보너스) |
| `is_importing() -> bool` | 신규(공개 메서드) | `labeling_tab.prepare_for_training()`가 현재 `self._image_browser._import_worker`(private) 직접 참조 중인 것을 이 메서드로 교체 — 사소한 위생 개선, 같은 커밋에 포함 |

- 기존 `paths()`(이미 존재)를 `labeling_tab._copy_prev_annotations()`의
  `self._image_browser._paths[idx-1]`(private 직접 접근) 대체에 사용 →
  `self._image_list.paths()[idx - 1]`로 변경.

### 3.4 알려지는 동작 변화 — 리스크로 명시 (리더/검증 에이전트 인지 필요)

- **재귀 스캔으로 전환**: `ImageBrowser.reload()`는 `images_dir()` 1단계만 스캔했지만
  (BUG-005로 폴더 그룹핑이 죽은 코드였음), `InferenceImageList.load_folder()`는
  `rglob("*")` 재귀 스캔이다. 라벨링 탭을 이 위젯으로 교체하면 프로젝트 `images/`
  밑에 (현재 앱 자체는 만들지 않지만, 사용자가 탐색기에서 수동으로 하위폴더를 만들어
  이미지를 넣어둔 경우) 하위폴더 이미지가 **처음으로 보이게 된다**. 데이터 손실
  없음, 오히려 GitHub #1이 요청했던 "폴더 정보 표시"에 더 부합하는 개선이지만,
  이전에는 안 보이던 이미지가 보이는 것이므로 검증 단계에서 "회귀가 아니라 의도된
  개선"임을 명확히 하고 넘어갈 것.
- `editable=True` 모드에서 `+ 파일`/`+ 폴더` 로 추가된 이미지는 여전히
  `_project.images_dir()` 평면 복사(`copy2`)이므로 트리에 하위폴더가 새로 생기는
  일은 없음 — 기존 동작과 동일, 위 리스크는 "이미 존재하던 하위폴더가 보이기
  시작한다"는 표시 측면 변화일 뿐 추가/삭제 동작 자체는 바뀌지 않음.
- `show_status_icons=True`일 때 정렬 콤보 항목 구성이 `InferenceImageList`의
  5종(`name_asc/name_desc/date_new/date_old/folder`)에 `status_done/status_todo`
  2종이 추가돼 7종이 된다 — 기존 `ImageBrowser`의 4종(`status_done/status_todo`
  포함)보다 폴더/날짜 정렬이 새로 추가되는 것도 부수적 기능 향상(의도된 것, 명시).

### 3.5 `labeling_tab.py` 변경

- `from app.widgets.image_browser import ImageBrowser` →
  `from app.widgets.inference_image_list import InferenceImageList`.
- `self._image_browser = ImageBrowser()` →
  `self._image_list = InferenceImageList(show_status_icons=True, editable=True)`
  + 생성 직후 `self._image_list.load_folder(_project.images_dir())` 명시 호출
  (`ImageBrowser.__init__()`가 내부에서 자동으로 `reload()`를 부르던 것과 달리,
  `InferenceImageList`는 `load_folder()`를 명시적으로 호출해야 함 — 이미 `BUG-017`
  주석에 남아있던 "초기 선택 신호가 리스너 연결 전에 발행되는" 타이밍 문제와 동일한
  주의가 필요하므로, 기존 `initial_path` 동기화 블록(`__init__` 끝부분)을 그대로
  유지하면서 `load_folder()` 호출 위치만 신호 연결 이전으로 맞춘다).
- `self._image_browser.*` 전체 치환(`set_mutation_guard`/`image_selected`/
  `image_deleted`/`has_list_focus`/`_on_delete`→`delete_selected`/`refresh_item`/
  `refresh_items`/`selected_paths`/`reload`/`current_display_index`/
  `_paths[idx-1]`→`paths()[idx-1]`/`navigate`/`_import_worker`→`is_importing()`).
- `app/widgets/image_browser.py` 파일 삭제. 다른 참조자 없음(grep 확인: 라벨링
  탭 외 import처 없음 — 추론/학습/모델 탭, 존분석 탭(`InferenceImageList`만 씀) 전부
  무관).

### 3.6 `inference_tab.py` 변경

없음(생성 코드 `InferenceImageList()`가 신규 기본값과 100% 호환).

---

## 4. 2단계 — 에디션 브랜치 반영 (이번 라운드에 구현하지 않음, 로드맵에 다음 단계로만 기록)

1단계(main) 커밋 완료 후, `AGENTS.md` 기존 규칙대로 sync 브랜치 + PR로
`feature/zone-analysis-tab`에 반영 → 워크트리 `D:/segmentation model-zone-analysis-tab`
에서:
- `zone_analysis_tab.py`: 자체 `_edit_toolbar`(원/브러시그리기/브러시지우기/
  블랍삭제/이동 + 브러시크기 + undo `QAction`)에서 브러시그리기/브러시지우기/
  블랍삭제/이동/브러시크기/undo 6개를 `BrushToolbar(show_delete_region=True)`로
  교체, 원(circle)만 호스트 로컬 유지. 현재 존분석은 `QActionGroup`으로 원/브러시
  계열의 상호배타를 관리하므로(`_tool_group`), `BrushToolbar.act_*`들을 그 그룹에
  편입하거나 라벨링 탭과 같은 수동 토글 방식으로 통일할지는 2단계 구현 시 결정.
  `set_blob_delete_mode()` 호출을 `BrushToolbar.tool_changed == TOOL_ERASER_FLOOD`
  에 연결 — 이게 "flood-eraser와 blob-delete 통합"이 실제로 완성되는 지점.
- `r_analysis_tab.py`: 자체 toolbar(ROI/브러시그리기/브러시지우기/이동 + 브러시크기
  + undo `QPushButton`)에서 브러시그리기/브러시지우기/이동/브러시크기/undo 5개를
  `BrushToolbar(show_delete_region=False)`로 교체, ROI만 호스트 로컬 유지.
- `ZoneCanvas`/`RRoiCanvas`는 `OverlayViewer` 상속이라 `view_transform.py` 추출
  이득을 1단계 커밋만으로 이미 받는다 — 2단계에서 추가 작업 불필요.
- 이미지 리스트: 두 탭 다 변경 없음(`zone_analysis_tab.py`는 이미
  `InferenceImageList` 사용 중, `editable=False`/`show_status_icons=False` 유지 —
  존분석엔 라벨 상태/추가/삭제 개념 없음. `r_analysis_tab.py`는 셀 패널 기반이라
  이번 통합 대상에서 계속 제외).

---

## 5. 구현 순서 제안 (리스크 낮은 것부터)

1. `view_transform.py` 추출 + `annotation_canvas.py`/`overlay_viewer.py` 4곳 치환
   (가장 기계적, 수식 완전 동일 확인됨 — 저리스크)
2. `inference_image_list.py` 확장 + `image_browser.py` 제거 + `labeling_tab.py`
   리스트 관련 치환 (중리스크 — 호출부가 많아 누락 주의, 위 3.3 표가 체크리스트)
3. `brush_toolbar.py` 신규 + `labeling_tab.py` 툴바 관련 치환 (중리스크 — 도구
   상호배타 동기화가 양방향이라 꼼꼼히 확인 필요)
2·3은 서로 다른 메서드 영역(`_build_toolbar()` vs 이미지 리스트 관련 메서드들)이라
한 에이전트가 순차로 진행해도 되고, 파일이 겹치는 `labeling_tab.py`만 유의해 병렬
에이전트 2개로 나누려면 "툴바 담당"과 "이미지 리스트 담당"으로 나눌 것(둘 다
`_build_ui()`/`_build_toolbar()`/`_connect_signals()`를 만지므로 완전 분리는 어려움
— 순차 진행 권장).

## 6. 검증 체크리스트 (구현 완료 후 검증 에이전트에게 전달)

- 라벨링 탭: 폴리곤/브러시/브러시채움/지우개/영역지우개/select/pan 7종 전부 동작,
  상호배타(한 번에 하나만 체크) 정상, undo, 브러시크기 스핀+더블클릭 조절(#3b),
  eye 토글, OK 토글(싱글+멀티선택), clear, auto-label, fullscreen — 전부 회귀 없음.
- 라벨링 탭 이미지 리스트: 상태 아이콘 3종, 범례, 검색/정렬 7종, 파일/폴더 추가,
  다중선택+삭제(+어노테이션 동반삭제 확인), Ctrl+C 파일명 복사, Delete 키 포커스별
  분기(이미지 목록 vs 캔버스), 학습 큐 중 추가/삭제 차단(mutation guard), 순번 표시.
- 추론 탭: 완전 무변경 확인(이미지 목록 단일선택/검색/정렬/폴더트리, pan/zoom,
  오버레이 슬라이더, F키 토글) — 플래그 기본값 경로라 회귀 가능성 낮지만 실행 확인 필요.
- 뷰어 pan/zoom: 라벨링 탭 줌-커서고정, 드래그 중 휠 줌(GitHub #9 재발 없음),
  리사이즈 시 fit-view. 추론 탭 pan/zoom 동일 확인.
