# 존 분석 탭 전면 재설계 — "상/하부 분석" (2026-10-01 요청)

기획 담당 작성. 구현 에이전트가 바로 착수할 수 있도록 파일/함수/시그니처 단위로 정리했다.
코드는 건드리지 않았다 — 전부 `Read`/`Grep` 기반 조사.

## 0. 조사 범위 및 전제

읽은 파일: `app/main_window.py`, `app/core/i18n.py`, `app/tabs/zone_analysis_tab.py`(전체
1283줄), `app/widgets/zone_canvas.py`(핵심 구간), `app/core/zone_metrics.py`,
`app/core/zone_state_store.py`, `app/widgets/inference_image_list.py`(전체),
`app/widgets/zone_batch_result_dialog.py`, `app/widgets/image_browser.py`(delete/clipboard
패턴), `app/tabs/inference_tab.py`(체크포인트 테이블), `app/core/trainer.py`(체크포인트 저장),
`app/core/inference_engine.py`(`list_checkpoints`/`load_checkpoint_meta`), `app/core/project.py`
(data 루트), `app/core/i18n.py`(`load_settings`/`save_settings`), `app/widgets/overlay_viewer.py`
(`wheelEvent`/줌 구조). `docs/roadmap.md`/`docs/agents/planning-log.md`의 Zone 탭 전체 이력도
확인(R1~R4, R-A~R-C, R3-1~R3-5, GitHub #13/14, 오프라인 팝업 삭제, 배치모드 3종 재설계,
GitHub #32, 블랍 클릭 선택+Excel 확장, 편집 UX 6건).

**중요 — 로드맵 체크박스와 실제 코드가 어긋난 지점 발견**: `docs/roadmap.md`의 "편집 도구 UX
개선 6건(2026-09-01)" R1(색상)·"블랍 클릭 선택"(요청④) 항목이 `[ ]`(미완료)로 남아있지만,
**실제 코드에는 이미 구현되어 있다** — `zone_canvas.py:55-56`(`_COLOR_DRAW`/`_COLOR_ERASE`
파랑/회색 색상 상수)과 `zone_analysis_tab.py`의 `_on_canvas_blob_clicked()`/
`blob_clicked` 시그널 배선(492행대)이 확인됨. 과거에도 이런 체크박스-코드 불일치가
있었던 전례(`docs/agents/planning-log.md` 2026-09-23 항목, GitHub #22/#16)가 있어 이번에도
코드를 1차 소스로 삼았다 — 아래 설계는 전부 **현재 실제 코드 상태**를 기준으로 한다. 리더가
별도로 로드맵 체크박스 정정을 판단할 것(이 스펙의 범위는 아님).

**이 스펙이 다루지 않는 것(범위 밖, YAGNI)**: px-to-mm 환산(추후 계수 제공 시 별도 라운드),
"편집 도구 UX 개선 6건"의 R4(자동검출 후 브러시 미조정 버그, 실행 도구로 재현 필요 — 이번
재설계와 무관하게 별도 처리), "추론 탭 블랍 클릭 선택"(R1, `inference_tab.py`/
`overlay_viewer.py` — 이번 요청 범위 밖).

---

## 1. 체크포인트 자동 선택

### 현재 코드
- `app/tabs/inference_tab.py`: 체크포인트는 프로젝트 `checkpoints_dir()`를 스캔하는
  `QTableWidget`(`_ckpt_table`, `SingleSelection`)에서 고른다. `_refresh_checkpoints()`가
  목록을 채운 뒤 마지막 행을 자동 선택(`selectRow(len(self._ckpt_metas) - 1)`, 642행) —
  이 호출은 `InferenceTab.__init__`/`_build_ui()` 시점에 이미 실행되므로 **사용자가 추론
  탭을 한 번도 열지 않아도** "최근 수정된 체크포인트"가 기본 선택되어 있다. 선택 상태는
  세션 메모리에만 있다(디스크 영속화 없음) — `selectionModel().selectionChanged`로 사용자가
  바꾸면 그 값이 그대로 유지된다.
- `_get_selected_ckpt()`(644행)가 현재 선택 행의 `Path`를 반환하는 비공개 메서드.
- `app/tabs/zone_analysis_tab.py`: 완전 독립 설계(2026-08-25 확정, 프로젝트 시스템 미사용)라
  `_on_select_checkpoint()`가 `QFileDialog`로 임의 경로의 `.pt`를 직접 연다. 기본값이
  전혀 없다 — 매번 수동 선택 필요.

### 설계
1. `inference_tab.py`에 공개 getter 1개 추가:
   ```python
   def selected_checkpoint_path(self) -> Path | None:
       return self._get_selected_ckpt()
   ```
   (기존 `win._model_tab.loaded_model`을 3개 탭이 교차 참조하는 기존 관례와 동일 수준의
   낮은 결합 — "완전 독립" 원칙은 Zone 탭이 프로젝트 데이터 모델에 의존하지 않는다는
   뜻이지, 합리적인 기본값 제안까지 금지하는 것은 아니라고 판단. 사용자는 여전히 Zone
   탭에서 "체크포인트 열기" 버튼으로 임의 경로를 선택해 언제든 덮어쓸 수 있다.)
2. `zone_analysis_tab.py`의 `_on_select_checkpoint()` 본문(632~662행)을 `_apply_checkpoint
   (self, path: Path) -> None`로 추출(파일 다이얼로그 로직만 `_on_select_checkpoint`에 남김).
   공개 메서드 1개 추가:
   ```python
   def set_default_checkpoint(self, path: Path | None) -> None:
       """탭 진입 시 외부(추론 탭)에서 넘겨주는 기본값 — 이미 사용자가 뭔가
       선택해둔 상태(self._ckpt_path is not None)면 아무 것도 하지 않는다."""
       if path is None or self._ckpt_path is not None:
           return
       self._apply_checkpoint(path)
   ```
3. `main_window.py`: `QTabWidget.currentChanged`에 슬롯 연결, Zone 탭으로 전환될 때마다
   호출(멱등 — 이미 선택돼 있으면 `set_default_checkpoint` 내부에서 즉시 반환):
   ```python
   self._tabs.currentChanged.connect(self._on_tab_changed)
   ...
   def _on_tab_changed(self, index: int) -> None:
       if self._tabs.widget(index) is self._zone_tab:
           self._zone_tab.set_default_checkpoint(
               self._inference_tab.selected_checkpoint_path()
           )
   ```
   탭 순서 변경(아래 2번) 이후에도 `self._zone_tab`/`self._inference_tab` 참조 자체는
   그대로이므로 이 배선은 순서와 무관하다.

### 영향 파일
`app/tabs/inference_tab.py`(getter 1개 추가), `app/tabs/zone_analysis_tab.py`(`_apply_checkpoint`
추출 + `set_default_checkpoint` 추가), `app/main_window.py`(`currentChanged` 배선).

---

## 2. 탭 순서 변경

### 현재 코드
`app/main_window.py` 42~46행:
```python
self._tabs.addTab(self._labeling_tab,  t("tab.labeling"))
self._tabs.addTab(self._training_tab,  t("tab.training"))
self._tabs.addTab(self._inference_tab, t("tab.inference"))
self._tabs.addTab(self._model_tab,     t("tab.model"))
self._tabs.addTab(self._zone_tab,      t("tab.zone_analysis"))
```

### 설계
Zone 탭을 맨 앞으로 — `addTab` 호출 순서만 바꾸면 된다(위젯 생성 순서는 그대로 둬도 무방,
`addTab` 호출 순서가 탭 표시 순서를 결정):
```python
self._tabs.addTab(self._zone_tab,      t("tab.zone_analysis"))
self._tabs.addTab(self._labeling_tab,  t("tab.labeling"))
self._tabs.addTab(self._training_tab,  t("tab.training"))
self._tabs.addTab(self._inference_tab, t("tab.inference"))
self._tabs.addTab(self._model_tab,     t("tab.model"))
```
다른 코드가 탭 인덱스를 하드코딩하는지 확인 필요(`self._tabs.widget(0)` 류) — 1번
항목의 `_on_tab_changed`는 `widget(index) is self._zone_tab` 비교라 인덱스에 의존하지
않으므로 순서 변경에 영향받지 않는다. 그 외 인덱스 하드코딩은 발견되지 않았다(`main_window.py`
전체가 탭 인스턴스 변수로만 참조).

### 영향 파일
`app/main_window.py` 단독.

---

## 3. 추론 방식 sliding window 고정

### 현재 코드 — 숨은 불일치 발견
- 단일 이미지 추론(`_ZoneInferenceWorker.run()`, 82~95행)은 `self._infer_mode.currentData()`
  로 `"resize"`/`"sliding_window"`를 선택(기본값 `sliding_window`, `_infer_mode`
  `QComboBox` 240~245행).
- **그런데 배치 처리(`_ZoneBatchWorker.run()`, 120~147행)는 이 설정을 전혀 읽지 않고
  무조건 `engine.run(...)`(resize 방식)만 호출한다** — sliding window 선택이 배치 경로에는
  전혀 반영되지 않던 기존 결함. `docs/roadmap.md` "다음 후보" 절의 "추론·Zone 분석
  sliding_window 기본 선택을 findData()로 명시" 완료 기록은 단일 이미지 경로만 해당했던
  것으로 보인다.

### 설계
1. `_infer_mode` `QComboBox`(240~245행)와 관련 UI(`toolbar_row1`의 해당 위젯, 툴팁) 전체
   제거 — 선택 UI 자체를 없앤다(요구사항 명시).
2. `_ZoneInferenceWorker.__init__`의 `mode` 매개변수 제거, `run()`이 항상
   `engine.run_sliding_window(**kwargs)`만 호출.
3. `_ZoneBatchWorker.run()`의 `engine.run(...)` 호출을 `engine.run_sliding_window(...)`로
   교체 — 시그니처 확인 완료(`inference_engine.py:153`):
   `run_sliding_window(model, image_path, checkpoint_path, overlap=64, opacity=0.5,
   min_confidence=0.0, min_pixel_size=0, prepared=None, classes=None)`. `run()`과 키워드
   인자 이름이 전부 동일(`prepared` 포함)하므로 `_ZoneBatchWorker.run()`의 기존 kwargs
   딕셔너리를 그대로 쓰고 호출 함수명만 바꾸면 된다(추가 매핑 불필요).
4. `_on_run()`의 `self._worker = _ZoneInferenceWorker(self._model, paths, self._ckpt_path,
   self._infer_mode.currentData())` 호출에서 마지막 인자 제거.

### 영향 파일
`app/tabs/zone_analysis_tab.py` 단독(`_ZoneInferenceWorker`, `_ZoneBatchWorker`, `_build_ui`,
`_on_run`). `inference_engine.py`는 수정 없음(기존 `run_sliding_window` 재사용) — 단,
시그니처 확인은 구현 전 선행 필수.

---

## 4. 탭 표시 이름 변경

### 현재 코드
`app/core/i18n.py` 10~14행(ko), 309~313행(en):
```python
"tab.zone_analysis": "존 분석",      # ko
"tab.zone_analysis": "Zone Analysis", # en
```

### 설계
ko 값만 "상/하부 분석"으로 교체(요구사항 명시 — 클래스/모듈/변수명은 변경 안 함).
en 값은 사용자가 명시하지 않았으나 ko와 짝을 맞춰 "Top/Bottom Analysis"로 제안(저위험 —
표시 텍스트 1줄, 나중에 바뀌어도 비용이 거의 없다). 다른 곳에서 "존 분석"/"Zone Analysis"
문자열을 하드코딩한 곳이 있는지 확인 — `grep -rn "존 분석" app/` 결과 `zone_analysis_tab.py`
자체의 주석·로그 메시지("존 분석 추론 실패" 등 `log.error`/`log.exception` 문자열)에서만
등장하고 이들은 로그 전용(사용자 UI 노출 아님, i18n 대상 아님) — 탭 라벨 i18n 키 1곳만
고치면 된다.

### 영향 파일
`app/core/i18n.py` 단독.

---

## 5. 이미지 열기/폴더 열기 버그 — 재현 후보 (코드 근거)

### 후보 A (가장 유력, 요구사항 2와 직결) — "추가 업로드가 기존 목록을 통째로 지운다"
`app/widgets/inference_image_list.py`:
- `load_folder()`(161~171행): `self._all_paths = sorted(p for p in root.rglob("*") ...)` —
  **항상 전체 교체**, 기존 `_all_paths`를 무시.
- `load_files()`(173~178행): `self._all_paths = sorted(paths)` — 역시 **항상 전체 교체**.

`zone_analysis_tab.py`의 `_on_select_image()`/`_on_select_folder()`(519~549행)도
`self._img_list.clear_status()` 후 바로 `load_files()`/`load_folder()`를 호출 — append
개념이 코드 어디에도 없다. 사용자가 "이미지 열기"나 "폴더 열기"를 **두 번째로** 실행하면
첫 번째 로드분이 통째로 사라지는 동작이 되는데, 이게 "버그"로 느껴졌을 가능성이 가장 높다.
(참고: `inference_tab.py`도 같은 컴포넌트를 쓰지만 지금까지 "추가 업로드" 요구가 없어
문제로 드러나지 않았을 뿐 — 동일 결함이 잠재돼 있다.)

### 후보 B — 목록에서 개별 이미지를 지울 방법이 아예 없음
`InferenceImageList` 전체를 봐도 삭제 관련 코드가 전혀 없다(`image_browser.py`의
`_on_delete()`/`eventFilter()` Delete 키 패턴과 달리 Zone 탭 쪽엔 대응 기능 0건). 요구사항
2가 "개별 이미지 삭제 기능 추가"를 명시적으로 요청한 것과 정확히 일치 — 신규 기능이자
동시에 "버그"로 체감됐을 수 있는 누락.

### 후보 C(저확신, 참고용) — 폴더 로드 후 개별 파일 추가 시 트리 구조 붕괴 가능성
현재는 `load_folder`/`load_files`가 항상 전체 교체라 재현되지 않지만, append를 구현하면
새로 생길 수 있는 엣지케이스: `_root`(폴더 스캔 루트)가 설정된 상태에서 공통 루트가 없는
개별 파일을 추가하면 `_build_nested_tree()`가 `p.relative_to(root)`에서 `ValueError`를
던질 수 있다. 아래 6-나 설계에서 이 케이스를 명시적으로 처리한다(루트 불일치 시 플랫
그룹 트리로 폴백).

### 결론
실제 재현은 검증 단계에서 `python main.py`로 "폴더 열기 → 이미지 열기로 파일 추가 → 목록
확인" 시나리오를 실행해 확정할 것 — 후보 A/B는 요구사항 2의 신규 기능으로 그대로
해결되므로 사용자 보고의 "버그"가 바로 이것일 가능성이 높다(GitHub #9/#16 라운드와
동일하게, 결정 없이 바로 구현 진행 가능 — 결정 대기 등록 안 함).

---

## 6. 이미지 업로드 — 리스트 통일 + append + 삭제

### 재사용 여부 판단 — `ImageBrowser` 재사용 기각 (재확인)
`app/widgets/image_browser.py`의 `ImageBrowser`는:
- `reload()`가 `_project.images_dir()`를 하드코딩(프로젝트 시스템 의존) — Zone 탭은
  "완전 독립"(2026-08-25 확정 원칙, 임의 경로 직접 로드)이라 전제가 정반대.
- `_on_add()`/`_on_add_folder()`가 파일을 프로젝트 폴더로 **복사**(`shutil.copy2`) —
  Zone 탭은 원본 경로를 직접 참조해야 한다(사이드카가 원본 이미지 옆에 저장되므로 복사하면
  사이드카 위치도 어긋남).
- `_on_delete()`가 실제 파일 + 어노테이션 JSON을 **디스크에서 삭제** — Zone 탭에서
  "목록에서 제거"는 원본 파일을 지우면 안 된다(사용자 외부 자산).
- 라벨 상태 아이콘 등 라벨링 전용 UI도 불일치.

→ **직접 재사용은 과거 추론 탭 라운드(2026-08-20)와 동일한 이유로 다시 기각**. 대신
Zone 탭이 이미 추론 탭과 공유 중인 `InferenceImageList`(검색/정렬/트리, 시각 형식은
`ImageBrowser`와 이미 유사)를 **두 가지 기능으로 확장** — 추론 탭도 동시에 혜택을
받는 애디티브 변경(추론 탭 호출부는 새 파라미터 기본값 때문에 회귀 없음).

### 설계 — ① append 지원
```python
def load_folder(self, root: Path, append: bool = False) -> None:
    new_paths = sorted(
        p for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS
    )
    if append and self._all_paths:
        # 루트 불일치(후보 C) 시 평탄 그룹 트리로 폴백 — _root를 None으로 낮춤
        if self._root is not None and self._root != root:
            self._root = None
        existing = set(self._all_paths)
        self._all_paths = sorted(existing | set(new_paths))
    else:
        self._root = root
        self._all_paths = new_paths
    self._apply_display()

def load_files(self, paths: list[Path], append: bool = False) -> None:
    if append and self._all_paths:
        self._root = None   # 개별 파일 추가는 공통 루트를 보장 못 하므로 항상 평탄 그룹화
        existing = set(self._all_paths)
        self._all_paths = sorted(existing | {Path(p) for p in paths})
    else:
        self._root = None
        self._all_paths = sorted(paths)
    self._apply_display()
```
기본값 `append=False`라 `inference_tab.py`의 기존 호출(`load_files([...])`,
`load_folder(Path(folder))`)은 전혀 변경 없이 기존 "항상 교체" 동작을 유지한다(회귀 없음).
중복 경로는 `set` 연산으로 자동 제거(같은 파일을 두 번 추가해도 목록에 두 번 나오지 않음).

`zone_analysis_tab.py`의 `_on_select_image()`/`_on_select_folder()`는 `append=True` 전달로
교체, `clear_status()` 호출은 **제거**(기존 이미지의 배치 처리 상태 배지를 지우면 안 됨 —
새로 추가된 이미지는 애초에 `_status` dict에 없어 상태 없음으로 자연스럽게 표시됨).

### 설계 — ② 개별 삭제(목록에서 제거, 파일은 보존)
`image_browser.py`의 `eventFilter()` Ctrl+C 패턴을 그대로 본떠 Delete 키 + 컨텍스트 메뉴
추가:
```python
# __init__에서
self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
self._tree.customContextMenuRequested.connect(self._on_context_menu)

# eventFilter() 기존 Ctrl+C 분기 옆에 추가
if (obj is self._tree and event.type() == QEvent.Type.KeyPress
        and event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace)):
    self._remove_selected()
    return True

def _remove_selected(self) -> None:
    """목록에서만 제거 — 원본 파일은 건드리지 않는다(Zone/추론 탭 둘 다 외부 파일 참조)."""
    removed = {
        p for item in self._tree.selectedItems()
        if (p := self._get_item_path(item)) is not None
    }
    if not removed:
        return
    self._all_paths = [p for p in self._all_paths if p not in removed]
    for p in removed:
        self._status.pop(p, None)
    self._apply_display()
    self.images_removed.emit(list(removed))   # 신규 시그널 — 호출부가 캐시(self._results 등) 정리할 수 있게

def _on_context_menu(self, pos) -> None:
    item = self._tree.itemAt(pos)
    if item is None or self._get_item_path(item) is None:
        return
    menu = QMenu(self)
    action = menu.addAction("목록에서 제거")
    if menu.exec(self._tree.viewport().mapToGlobal(pos)) == action:
        self._remove_selected()
```
신규 시그널 `images_removed = pyqtSignal(list)` 추가. `zone_analysis_tab.py`는 이 시그널에
연결해 `self._results.pop(p, None)`(추론 결과 캐시 정리) + 현재 로드된 이미지가 삭제
대상이면 캔버스를 비우는 정리 로직을 둔다(상세는 구현자 판단, 핵심은 메모리/상태 누수
방지). 삭제는 **사이드카 파일(`{stem}.zone.json`)도, 원본 이미지도 건드리지 않는다** —
"목록에서 빼는 것"과 "데이터를 지우는 것"을 명확히 분리(라벨링 탭 `ImageBrowser`의 삭제
의미와 의도적으로 다름 — 혼동 방지를 위해 메뉴 문구를 "삭제"가 아니라 "목록에서 제거"로
한다).

### 영향 파일
`app/widgets/inference_image_list.py`(`load_folder`/`load_files` 시그니처 확장,
`_remove_selected`/`_on_context_menu`/`images_removed` 신규), `app/tabs/zone_analysis_tab.py`
(`_on_select_image`/`_on_select_folder`에 `append=True`, `clear_status()` 제거,
`images_removed` 연결). `app/tabs/inference_tab.py`는 변경 없음(새 기본값 덕분에 회귀 없음
— 단, "삭제" 컨텍스트 메뉴/Delete 키는 공유 위젯이라 추론 탭에도 동일하게 나타남, 부작용
아니라 자연스러운 기능 확장으로 간주. 추론 탭에서 "목록에서 제거"가 이상하게 느껴지지 않는지
검증 단계에서 가볍게 확인할 것).

---

## 7. 영역(Zone) 설정 — 레시피/수동편집/자동검출 재편

### 7-1. 현재 구조 재확인 — 순서 제약이 "인위적"임을 발견

`_btn_detect`(자동 검출 버튼)는 현재 **추론 완료 후에만** 활성화된다
(`_setup_target_classes()`에서 `self._btn_detect.setEnabled(True)`, 추론 전엔
`_on_list_image_selected()`에서 `False`로 고정). 그런데 `_on_auto_detect()`(1050~1066행)의
실제 구현은 원본 이미지를 직접 다시 읽어(`Image.open(self._image_path)`) 순수 OpenCV
원 검출(`detect_circles`)을 수행할 뿐 **추론 결과(`InferenceResult`)를 전혀 참조하지
않는다** — 즉 이 활성화 제약은 과거 UX 상의 선택이었을 뿐 실제 기술적 의존관계가 아니다.
`ZoneCanvas.get_state()`/`set_state()`도 원(circle) 자체는 블랍 라벨맵과 무관하게 독립
저장/복원되는 것을 이미 확인했다(블랍 삭제 이력/수동 스트로크만 `set_blob_data()`가 있어야
의미를 가짐).

사용자가 요청한 새 시나리오 순서("③ 영역 설정" → "④ 영역 설정 후 추론 실행")는 정확히
이 재발견과 맞아떨어진다 — **영역(원) 설정은 추론 전에 할 수 있어야 한다.**

### 7-2. 설계 — 활성화 조건 분리

- `_act_circle`(원 편집 모드)과 `_btn_detect`(자동 검출)는 **이미지 로드 직후** 활성화
  (현재 `_on_list_image_selected()`가 `_act_circle.setEnabled(True)`는 이미 하고 있음,
  `_btn_detect.setEnabled(True)`만 추가하고 `_setup_target_classes()`/추론 완료 경로의
  `setEnabled` 호출은 제거).
- `_act_brush_draw`/`_act_brush_erase`/`_act_blob_delete`(블랍 기반 편집 3종)는 **그대로
  추론 완료 후에만 활성화**(현재 동작 유지) — 이들은 실제로 타겟 클래스 블랍 마스크
  (`set_blob_data`)에 의존하는 진짜 기술적 제약.
- 사이드바 "존별 타겟 클래스 비율" 리스트는 추론 전엔 당연히 비어 있다(`_compute_zone_
  percentages()`가 이미 `self._last_result is None`이면 `[]` 반환 — 변경 불필요).

### 7-3. 설계 — "일괄 적용(레시피 사용)" 전용 팝업

신규 파일 `app/widgets/zone_recipe_dialog.py`:

```python
class ZoneRecipeDialog(QDialog):
    """'일괄 적용' 모드 전용 — 기준 이미지에 적용할 원(zone) 집합을 레시피로
    불러오거나 새로 만들어 메인 탭에 반영한다. 2026-08-30에 삭제된
    `circle_detect_preview_dialog.py`(오프라인 원 검출 테스트)와 동일한
    "임베디드 ZoneCanvas + 라운드트립 적용" 골격을 재사용하되, 목적은
    '오프라인 테스트'가 아니라 '레시피 관리'로 바뀐다."""
```

- 생성자: `ZoneRecipeDialog(reference_pixmap: QPixmap, ref_size: tuple[int, int], parent=None)`
  — 메인 탭이 **현재 로드된 이미지**(`self._original_pixmap`, `self._image_size`)를
  기준 이미지로 그대로 넘긴다(임의 이미지를 새로 열 필요 없음 — 이미 시나리오 2에서
  업로드됐으므로).
- 내부에 `ZoneCanvas` 인스턴스 1개(순수 원 편집 모드만 사용 — 블랍/브러시 액션은 이
  다이얼로그에 아예 두지 않는다, 레시피는 순수 기하 데이터), `set_image_size`/`set_pixmap`
  으로 기준 이미지 표시.
- 상단 컨트롤: 민감도 슬라이더 + "자동 검출" 버튼(메인 탭과 동일 `detect_circles` 재사용),
  "정렬(중심 맞추기)" 버튼(7-4), Undo 버튼(`canvas.undo`/`can_undo`, 메인 탭과 동일 패턴).
- 레시피 영역: `QComboBox`(최근 레시피 목록, `zone_recipe_store.list_recipes()`) +
  "불러오기" 버튼 + 이름 입력 `QLineEdit` + "저장" 버튼.
  - 다이얼로그 오픈 시 **최근 레시피 자동 로드**(요구사항 명시) — `list_recipes()`가 반환한
    "가장 최근 사용" 레시피가 있으면 자동으로 `canvas.set_circles(...)`까지 실행, 없으면
    빈 캔버스로 시작.
- 하단: "메인 탭에 적용" 버튼(기본 비활성) + "취소" 버튼.
  - `canvas.circles_changed`에 연결된 슬롯이 `len(canvas.get_circles()) >= 1`일 때만
    "메인 탭에 적용" 버튼을 활성화 — **이것이 "영역이 설정 안 된 상태면 나머지 작업
    진행 불가"의 구현**(팝업 자체가 원이 없으면 적용 자체가 안 되므로, 이 경로로는
    원 없이 빠져나갈 수 없다. 단 "취소"로 닫는 것은 항상 가능 — 아무 것도 적용하지 않고
    돌아가는 것은 차단 대상이 아님, 명시적으로 데이터를 안 바꾸는 선택이므로).
  - "적용" 클릭 시 `self.accept()`, 호출부가 `dialog.exec()` 후 `result_circles()`/
    `result_ref_size()` getter로 결과를 읽는다(`auto_label_dialog.py`/구
    `circle_detect_preview_dialog.py`와 동일한 기존 라운드트립 패턴 재사용).

`zone_analysis_tab.py` 쪽 배선:
- `_mode_combo`가 `"apply_all"`/`"apply_all_edit"`일 때만 보이는 버튼 "원(Zone) 설정..."
  신규 추가(좌측 `_batch_box` 안, `_mode_combo` 바로 아래) — 클릭 시 `ZoneRecipeDialog`를
  열고, `dialog.exec()`가 참이면 `_scale_circles()`(기존 R13-B 공용 헬퍼 재사용)로 현재
  기준 이미지 크기에 맞게 스케일한 뒤 `self._canvas.set_circles(scaled)` 호출(기존 원이
  있으면 교체 전 확인 다이얼로그 — `_confirm_existing_zones`류 패턴 재사용 또는 간단한
  `QMessageBox.question` "기존 원을 레시피로 교체하시겠습니까?").
- `_mode_combo`가 `"per_image"`일 때는 이 버튼을 숨김(장별 적용은 기존처럼 메인 캔버스에서
  자동검출+수동편집, 팝업 불필요 — 요구사항 "일괄적용이 아닐 때는 자동 영역 검출을
  활성화해서 이미지별 개별 영역 지정"과 일치, 이 모드는 이미 그렇게 동작 중이므로 추가
  코드 불필요).
- `_on_run()`(추론 실행 버튼)에 신규 가드 추가 — **요구사항 4**:
  ```python
  if not self._canvas.get_circles():
      reply = QMessageBox.question(
          self, "영역 없음",
          "영역(원)이 설정되지 않았습니다. 그래도 추론을 진행하시겠습니까?",
          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
          QMessageBox.StandardButton.No,
      )
      if reply != QMessageBox.StandardButton.Yes:
          return
  ```
  (기존 `#7` OK확인 팝업과 동일한 `QMessageBox.question` 패턴.)

### 7-4. "정렬(중심 맞추기)" 버튼

`ZoneCanvas`에 공개 메서드 추가:
```python
def align_centers(self) -> None:
    """선택된 원이 없어도 전체 원 대상 — 모든 원의 중심을 평균 중심으로 맞춘다
    (반지름은 그대로, 배터리 캡 동심원 전제와 동일한 '평균 중심' 규칙을
    GitHub #13 요구사항2가 이미 신규 원 생성에 쓰는 것과 통일)."""
    if len(self._circles) < 2:
        return
    self._push_undo()
    cx = sum(c.cx for c in self._circles) / len(self._circles)
    cy = sum(c.cy for c in self._circles) / len(self._circles)
    for c in self._circles:
        c.cx, c.cy = cx, cy
    self.update()
    self.circles_changed.emit()
    self.circles_committed.emit()
```
버튼은 메인 탭 우측 원 목록 패널(`side_layout`, `_circle_list` 위/아래)과 `ZoneRecipeDialog`
양쪽에 추가 — 둘 다 같은 `ZoneCanvas` 클래스를 쓰므로 메서드 1개 추가로 양쪽에서 재사용된다.

### 7-5. 수동 원 편집 — 방향키 이동 + 마우스 휠 지름 변경

`zone_canvas.py`의 `keyPressEvent()`(762행)에 방향키 분기 추가(원편집 모드 + 선택된 원이
있을 때만):
```python
_ARROW_STEP_PX = 1.0
_ARROW_STEP_PX_SHIFT = 10.0

# keyPressEvent, 기존 Delete/Backspace 분기 옆
elif (self._mode == "circle" and self._selected_id is not None
      and event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down)):
    item = self._find(self._selected_id)
    if item is not None:
        self._begin_edit_gesture()   # 디바운스 — 아래 참고
        step = _ARROW_STEP_PX_SHIFT if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else _ARROW_STEP_PX
        dx, dy = {
            Qt.Key.Key_Left: (-step, 0), Qt.Key.Key_Right: (step, 0),
            Qt.Key.Key_Up: (0, -step), Qt.Key.Key_Down: (0, step),
        }[event.key()]
        item.cx += dx
        item.cy += dy
        self.update()
        self.circles_changed.emit()
        self.circles_committed.emit()
```

`wheelEvent()` 신규 오버라이드(현재 `ZoneCanvas`엔 없음 — `OverlayViewer.wheelEvent`가
항상 줌으로 처리 중):
```python
_WHEEL_STEP_PX = 5.0
_WHEEL_STEP_PX_SHIFT = 20.0

def wheelEvent(self, event) -> None:
    if self._mode == "circle" and self._selected_id is not None:
        item = self._find(self._selected_id)
        if item is not None:
            self._begin_edit_gesture()
            step = _WHEEL_STEP_PX_SHIFT if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else _WHEEL_STEP_PX
            delta = step if event.angleDelta().y() > 0 else -step
            item.r = max(0.0, item.r + delta)
            self.update()
            self.circles_changed.emit()
            self.circles_committed.emit()
            event.accept()
            return
    super().wheelEvent(event)   # 선택된 원이 없으면 기존처럼 화면 줌
```

**디바운스(`_begin_edit_gesture`)** — 방향키 연타/휠 연속 스크롤이 매번 `_push_undo()`를
호출하면 Ctrl+Z 한 번에 1px만 복구되는 피로감이 생긴다. 드래그(`mousePressEvent`에서
1회만 push)와 동일한 "제스처당 1개" 원칙을 맞추기 위해 타이머 기반 디바운스를 추가:
```python
_GESTURE_DEBOUNCE_MS = 500

def _begin_edit_gesture(self) -> None:
    """방향키 연타/휠 연속 스크롤을 '하나의 편집 제스처'로 묶어 undo 1개만 쌓는다.
    제스처가 끝나고 500ms 안에 새 제스처가 시작되지 않으면 다음 입력이 새 push를 만든다."""
    if not self._gesture_active:
        self._push_undo()
        self._gesture_active = True
    self._gesture_timer.start(_GESTURE_DEBOUNCE_MS)   # 매 입력마다 타이머 재시작(연속 입력이면 계속 연장)
```
`__init__`에 `self._gesture_active = False`, `self._gesture_timer = QTimer(self)`,
`self._gesture_timer.setSingleShot(True)`,
`self._gesture_timer.timeout.connect(lambda: setattr(self, "_gesture_active", False))` 추가.
(이 패턴은 드래그/스트로크처럼 "누르고 있는 동안"이 명확한 제스처가 아니라 "개별 이벤트가
빠르게 반복"되는 입력에 쓰는 범용 디바운스 — 브러시 지우기의 "release 시 1회" 방식과는
다른 메커니즘이 필요해서 새로 추가.)

마우스 휠로 지름(반지름×2)을 조절하는 것이 요구사항 원문("마우스 휠 스크롤로 원 지름
변경")과 일치 — 내부적으로는 반지름(`item.r`)을 직접 조작하되 사용자에게 보이는 결과는
지름 변경과 동일(반지름이 커지면 지름도 커짐, 별도 변환 불필요).

### 영향 파일
`app/widgets/zone_canvas.py`(`align_centers`, `wheelEvent`, `keyPressEvent` 방향키 분기,
`_begin_edit_gesture`/`_gesture_active`/`_gesture_timer`), `app/widgets/zone_recipe_dialog.py`
(신규), `app/core/zone_recipe_store.py`(신규, 아래 7-6), `app/tabs/zone_analysis_tab.py`
(활성화 조건 분리, "원(Zone) 설정..." 버튼 + 배선, `_on_run()` 가드, "정렬" 버튼 배선).

### 7-6. 레시피 저장 포맷/위치

신규 파일 `app/core/zone_recipe_store.py` — `zone_state_store.py`와 동일한 역할
분담(Qt 의존성 없는 순수 JSON 저장소, `annotation_store.py`/`zone_state_store.py`와
같은 "core 저장소 모듈" 관례).

**저장 위치**: `data/zone_recipes/{안전한 이름}.json` — Zone 탭은 프로젝트 시스템이
없으므로(완전 독립 원칙) `app/core/project.py`의 `_fallback()`이 쓰는 것과 동일한
`Path("data").resolve()` 루트 아래 신규 하위 폴더(`data/checkpoints`/`data/images`와
동급). 파일명은 사용자가 입력한 레시피 이름에서 `[\\/:*?"<>|]` 문자만 `_`로 치환(경로
주입 방지, 과한 슬러그화는 하지 않음 — 한글 이름 그대로 허용).

**스키마**:
```json
{
  "name": "표준 캡 3존",
  "saved_at": "2026-10-01T14:32:00",
  "ref_size": [5472, 3648],
  "circles": [[1200.0, 1800.0, 400.0], [1200.0, 1800.0, 900.0]]
}
```
`circles`는 `(cx, cy, r)` 튜플 리스트(원본 이미지 픽셀 좌표, id 없음 — 레시피는 순수
기하 데이터, 적용 시 `ZoneCanvas.set_circles()`가 새 id를 자동 발급). `ref_size`는
저장 당시 기준 이미지 크기 — 다른 해상도 이미지에 불러올 때 기존 `_scale_circles()`로
비례 스케일(배치 적용과 동일한 공용 헬퍼, 이미 R13-B에서 통합됨).

```python
def recipes_dir() -> Path:
    return Path("data/zone_recipes").resolve()

def _safe_filename(name: str) -> str:
    import re
    cleaned = re.sub(r'[\\/:*?"<>|]', "_", name.strip())
    return cleaned or "recipe"

def save_recipe(name: str, circles: list[tuple[float, float, float]],
                ref_size: tuple[int, int]) -> Path: ...

def load_recipe(path: Path) -> dict | None: ...

def list_recipes() -> list[Path]:
    """mtime 내림차순 — 가장 최근 저장/사용한 것이 맨 앞(자동 로드 대상)."""
    d = recipes_dir()
    if not d.exists():
        return []
    return sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
```
"최근 레시피 자동 로드"는 `list_recipes()[0]`(가장 최근 mtime)을 그대로 쓰면 된다 —
별도의 "최근 사용 목록"을 `settings.json`에 중복 저장할 필요 없음(파일시스템 mtime이
이미 정확한 "최근" 순서를 제공, YAGNI). `ZoneRecipeDialog`의 레시피 `QComboBox`는
`list_recipes()`를 그대로 나열(이름은 JSON의 `"name"` 필드로 표시, 경로는 내부 보관).
레시피를 "불러오기"하거나 "자동 적용"할 때마다 **해당 파일의 mtime을 갱신**(예:
`path.touch()` 또는 재저장)해 "최근 사용"이 "최근 저장"뿐 아니라 "최근 사용"까지
반영하도록 한다(선택적 개선, 구현자 판단에 맡김 — 과하면 생략 가능).

### 영향 파일(7-6)
`app/core/zone_recipe_store.py`(신규).

---

## 8. 추론 결과 보정 — 라벨링 탭과 동등한 수정 도구

### 감사 결과 — 추가 구현 거의 불필요
2026-08-31 "R2" 감사(`docs/specs/zone-blob-select-and-export-2026-08-31.md`)가 이미
`zone_canvas.py`/`zone_analysis_tab.py`를 `annotation_canvas.py`/`labeling_tab.py`와
항목별 대조해 **"격차 없음"**으로 결론 낸 바 있다(배타적 `QToolBar`, LIFO Undo, `Ctrl+Z`,
디스크 자동저장 디바운스, 둘 다 동등). 이번 조사로 직접 재확인한 것:
- 브러시 그리기(`brush_draw`)/지우기(`brush_erase`) 둘 다 이미 구현되어 있고
  `zone_metrics.apply_manual_strokes()`(last-write-wins)가 `final_mask` 계산에 실제로
  반영됨(`_ai_and_final_masks()`).
- 보정 내용(수동 스트로크)은 `_save_timer`(500ms 디바운스) + `_flush_state()`로
  이미지 옆 사이드카(`{stem}.zone.json`)에 자동 저장 — "덮어쓰기" 요구사항은 이미 충족:
  `manual_strokes`가 저장되면 이후 모든 퍼센티지/blob 계산(`_compute_zone_percentages`,
  `_compute_zone_blob_rows`, 배치 재처리 `_on_batch_image_inferred`)이 전부 `final_mask`
  기준이라 보정 결과가 항상 "최신 값"으로 반영된다(AI 원본 마스크는 저장하지 않고 매번
  재계산하는 구조이므로 "덮어써짐"이라는 표현이 정확히 맞다 — 별도의 "저장된 AI 마스크"
  자체가 없다).

**결론: 이번 요구사항은 신규 구현 없음.** 7-2(활성화 조건 분리)만 적용하면 "추론 → 보정"
순서 자체는 이미 완전하게 동작한다. 검증 단계에서 골든패스로 "자동검출→추론→브러시
보정→사이드카 저장→재오픈 시 복원" 확인만 하면 된다.

### 영향 파일
없음(검증 전용 항목).

---

## 9. 결과 분석 테이블 — 최대 blob 픽셀수 + Excel/클립보드

### 현재 구조
`ZoneBatchResultDialog`(`app/widgets/zone_batch_result_dialog.py`)가 이미 "Long"(이미지,
존, 타겟비율%) + "Wide"(이미지×존 피벗) 2-tab + Excel 내보내기(`export_zone_percentages_
to_excel`, 3시트: `zones`/`zones_wide`/`zone_blobs`)를 갖추고 있다. `zone_blobs` 시트는
**blob 1개당 1행**(zone_id, pixel_count, ai_score 등)이지 "zone별 최대 blob 픽셀수"는
아직 집계되어 있지 않다 — 이번 요구사항은 `rows`(퍼센티지)와 `blob_rows`를 조인해
(이미지, 존)별 `max(pixel_count)`를 구해 **`zones` 시트에 4번째 열로 추가**하는 것.

### 설계
`app/core/zone_metrics.py`에 순수 함수 추가:
```python
def max_blob_pixels_by_zone(
    blob_rows: list[tuple[str, "ZoneBlobStat"]]
) -> dict[tuple[str, str], int]:
    """(이미지파일명, ZoneBlobStat) 목록 -> (이미지,존)별 최대 blob 픽셀수.
    해당 (이미지,존) 조합에 blob이 하나도 없으면 키가 없음(호출부가 0으로 렌더링)."""
    result: dict[tuple[str, str], int] = {}
    for image_name, stat in blob_rows:
        key = (image_name, stat.zone_name)
        result[key] = max(result.get(key, 0), stat.pixel_count)
    return result
```
`export_zone_percentages_to_excel()` 수정(`zones` 시트만, `zones_wide`/`zone_blobs`
시트는 그대로):
```python
ws.append(["이미지파일명", "존이름", "타겟비율(%)", "최대 blob 픽셀수"])
...
max_blobs = max_blob_pixels_by_zone(blob_rows) if blob_rows else {}
for image_name, zone_name, pct in rows:
    cell = "" if blob_rows is None else max_blobs.get((image_name, zone_name), 0)
    ws.append([image_name, zone_name, round(pct, 2), cell])
```
(`blob_rows is None`과 "제공됐지만 이 존에 blob이 없음"(`0`)을 구분 — 전자는 호출부가
애초에 blob 데이터를 안 줬다는 뜻이라 공란, 후자는 "확인했지만 0개"라는 유효한 값.
실제로는 현재 모든 호출부(`_on_export_single`, 배치 흐름)가 항상 `blob_rows`를 넘기므로
`None` 분기는 거의 발생하지 않지만, 시그니처 하위호환을 위해 남겨둔다.)

**온스크린 Long 탭에도 열 추가**(Excel뿐 아니라 "표로 표시" 요구사항 — `zone_batch_
result_dialog.py`):
```python
def _build_long_tab(self, rows, blob_rows) -> QWidget:
    max_blobs = max_blob_pixels_by_zone(blob_rows)
    table = QTableWidget(len(rows), 4)
    table.setHorizontalHeaderLabels(["이미지", "존", "타겟 비율(%)", "최대 blob 픽셀수"])
    ...
    for r, (img_name, zone_name, pct) in enumerate(rows):
        ...
        table.setItem(r, 3, QTableWidgetItem(str(max_blobs.get((img_name, zone_name), 0))))
    return table
```
(`_build_ui`가 `self._build_long_tab(rows)` 호출하던 것을
`self._build_long_tab(rows, self._blob_rows)`로 변경.)

**클립보드 복사** — 새 버튼 "클립보드로 복사"(기존 "Excel로 내보내기" 옆):
```python
def _on_copy_clipboard(self) -> None:
    max_blobs = max_blob_pixels_by_zone(self._blob_rows)
    lines = ["이미지\t존\t타겟 비율(%)\t최대 blob 픽셀수"]
    for img_name, zone_name, pct in self._rows:
        lines.append(f"{img_name}\t{zone_name}\t{pct:.2f}\t{max_blobs.get((img_name, zone_name), 0)}")
    QApplication.clipboard().setText("\n".join(lines))
```
TSV(탭 구분) 형식이라 엑셀/스프레드시트에 그대로 붙여넣기 가능 — 이 앱에 선택 영역 기반
부분 복사 패턴이 전례가 없어(기존 클립보드 복사는 전부 "버튼 1개 = 전체 복사", 예:
`cuda_diag_dialog.py`) 동일한 "버튼 1개 = 표 전체 복사" 방식을 채택(YAGNI — 셀 범위
선택/부분 복사는 요구사항에 없음).

**단일 이미지 경로**(`zone_analysis_tab.py`의 `_on_export_single`)도 동일 다이얼로그를
재사용하도록 변경 — 현재는 파일 저장 다이얼로그로 바로 가는데, "표로 표시" 요구사항을
만족하려면 화면에 테이블이 먼저 보여야 한다:
```python
def _on_export_single(self) -> None:
    rows = self._compute_zone_percentages()
    if not rows or self._image_path is None:
        QMessageBox.information(self, "내보낼 결과 없음", "먼저 원을 정의하고 추론을 실행하세요.")
        return
    excel_rows = [(self._image_path.name, name, pct) for name, pct in rows]
    blob_rows = self._compute_zone_blob_rows()
    ZoneBatchResultDialog(excel_rows, blob_rows, self).exec()
```
기존 버튼 이름 "Excel로 내보내기"는 "결과 분석 보기"로 바꾸는 것을 권장(다이얼로그 안에서
Excel 내보내기/클립보드 복사 둘 다 제공하므로 버튼 라벨이 "Excel로 내보내기"만 가리키면
혼동). 배치 경로(`_on_batch_finished()`)는 이미 같은 다이얼로그를 띄우고 있어 변경 없음
— 단일/배치 양쪽이 완전히 같은 코드 경로를 타게 되어 중복 로직이 사라진다(라더 원칙:
재사용, 분기 줄이기).

### 영향 파일
`app/core/zone_metrics.py`(`max_blob_pixels_by_zone` 신규 + `export_zone_percentages_
to_excel` 열 추가), `app/widgets/zone_batch_result_dialog.py`(`_build_long_tab` 시그니처
변경, `_on_copy_clipboard` 신규 + 버튼), `app/tabs/zone_analysis_tab.py`(`_on_export_single`
단순화 — 다이얼로그 재사용, 버튼 라벨 변경).

---

## 10. 체크포인트 파일명에 학습 시작 날짜 포함

### 현재 코드
`app/core/trainer.py`:
```python
prefix = f"{self._ckpt_prefix}_" if self._ckpt_prefix else ""     # 382행
path = _project.checkpoints_dir() / f"{prefix}epoch_{epoch:04d}.pt"   # 392행
best_path = _project.checkpoints_dir() / f"{prefix}best.pt"            # 385행
```
`self._ckpt_prefix`는 `training_tab.py`가 `ckpt_prefix=job.name`으로 넘기는 모델/작업
이름(예: `simple_unet`).

### 파싱 의존성 확인 — 안전
`app/core/inference_engine.py`의 `list_checkpoints()`(`ckpt_dir.glob("*.pt")`, mtime 정렬)와
`load_checkpoint_meta()`(파일을 열어 `epoch`/`metrics`/`config` 등 **딕셔너리 내부 값**만
읽음, 파일명 파싱 없음) 둘 다 파일명 포맷에 의존하지 않는다. `app/` 전체에서
`epoch_\d`/정규식/`startswith("epoch_")` 패턴을 `Grep`으로 검색한 결과 trainer.py의
생성 코드 1곳 외 어디서도 파일명 구조를 가정하지 않음을 확인 — **파일명 포맷을 바꿔도
깨지는 기존 로직이 없다.**

### 설계
```python
from datetime import date   # 파일 상단 import 추가
...
def run(self) -> None:
    run_date = date.today().strftime("%Y%m%d")   # 학습 시작 시점 1회만 계산(자정 넘어가도 날짜 안 바뀜)
    ...
    # 기존 prefix 조립부를 교체
    prefix = f"{self._ckpt_prefix}_{run_date}_" if self._ckpt_prefix else f"{run_date}_"
```
결과 파일명 예: `simple_unet_20261001_epoch_0010.pt`, `simple_unet_20261001_best.pt`.
`run_date`는 에폭 루프 **진입 전**에 한 번만 계산해 멤버 변수(또는 지역 변수, 루프
스코프 안에 있으면 그대로 재사용됨)로 둔다 — 매 에폭 `date.today()`를 다시 부르면
자정을 넘기는 긴 학습에서 파일명 날짜가 중간에 바뀌는 혼란을 방지(요구사항 "학습
시작 날짜"와 정확히 일치).

### 영향 파일
`app/core/trainer.py` 단독.

---

## 11. 실행 순서 제안 (구현 라운드 분할)

파일 겹침 기준으로 묶었다 — 각 라운드 구현 후 `python main.py` 실행 확인 권장(CLAUDE.md
"구현 완료 후 검증 필수" 원칙). "주요 기능 추가"에 해당하는 라운드는 골든패스 실 GUI
조작까지 검증 요청할 것(아래 표시).

| 라운드 | 내용 | 파일 | 비고 |
|---|---|---|---|
| A | 2(탭 순서) + 4(탭명) + 10(체크포인트 날짜) | `main_window.py`, `i18n.py`, `trainer.py` | 저위험, 서로 독립, 병렬 가능 |
| B | 1(체크포인트 자동선택) | `inference_tab.py`, `zone_analysis_tab.py`, `main_window.py` | 저위험 |
| C | 3(sliding window 고정 + 배치 버그 수정) | `zone_analysis_tab.py` | `run_sliding_window` 시그니처 선확인 필수 |
| D | 6(이미지 리스트 append+삭제) | `inference_image_list.py`, `zone_analysis_tab.py` | 추론 탭 회귀 확인 필요(공유 위젯) |
| E | 7(레시피+수동편집 UX, 최대 스코프) | `zone_canvas.py`(신규), `zone_recipe_dialog.py`(신규), `zone_recipe_store.py`(신규), `zone_analysis_tab.py` | **주요 기능 추가 — 골든패스 검증 필요**(원 생성/이동/방향키/휠지름조절/정렬/레시피 저장·불러오기/팝업 게이트/추론 전 설정 가능) |
| F | 9(결과 분석 테이블+클립보드) | `zone_metrics.py`, `zone_batch_result_dialog.py`, `zone_analysis_tab.py` | E의 `_on_export_single` 변경과 겹치므로 E 이후 진행 권장 |
| — | 8(보정 도구) | 없음 | 검증만, 코드 변경 없음 |

C/D/E/F는 모두 `zone_analysis_tab.py`를 건드리므로 완전 병렬은 어렵다 — A/B 먼저(독립
파일) → C → D → E → F 순서 권장. 5(버그 후보)는 D 구현 자체가 해결책이라 별도 라운드
불필요.

---

## 12. 사용자 결정이 더 필요한 지점

`docs/decisions-needed.md`에 등록할 항목(리더가 반영):
1. px→mm 환산은 이번에 만들지 않음(사용자가 이미 "추후 계수 제공 예정"이라고 명시) —
   단순 알림성 등록, 결정 대기 아님.
2. 레시피 저장 위치(`data/zone_recipes/`)/포맷(JSON, mtime 기반 "최근")은 사용자가
   세부사항을 명시하지 않아 기획이 직접 결정했음 — 기존 `data/` 하위 폴더 관례를
   그대로 따른 저위험 선택이라 별도 확인 없이 진행 가능하다고 판단, 결정 대기 등록은
   안 함(구현 중 문제가 드러나면 그때 조정).
3. 탭 영문명("Top/Bottom Analysis")은 사용자가 지정하지 않은 값 — 변경 비용이 낮아
   결정 대기 등록은 하지 않되, 리더가 전달 시 한 줄 언급 권장.

실질적으로 "결정 대기" 목록에 올릴 만큼 진행을 막는 항목은 없음(2/3은 저위험 기본값
채택, 1은 이미 사용자가 방향을 정함) — `docs/decisions-needed.md`에는 1번만 "참고
기록"으로 추가.
