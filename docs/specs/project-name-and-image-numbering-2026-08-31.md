# 프로젝트 이름 자동 동기화 + 이미지 리스트 순번 표시 (2026-08-31)

두 사용자 요청의 스코프 산정. main 브랜치 대상, zone 에디션 이식은 별도 라운드.

---

## 요청 1 — 프로젝트 이름을 폴더 이름과 항상 일치시키기

### 문제
`Project.name` 프로퍼티(`app/core/project.py:86-87`)가
`self._meta.get("name", self.path.name)`로 `project.json`의 `name` 필드를 폴더명보다
우선한다. 앱 밖(Windows 탐색기 등)에서 프로젝트 폴더 이름을 바꾸거나 이동해도
`project.json`은 갱신되지 않아 앱은 계속 예전 이름을 표시한다.

### `Project.name` 전수 사용처 (grep 완료)
| 파일:라인 | 용도 | 이번 변경 영향 |
|---|---|---|
| `app/main_window.py:28` | 창 타이틀바 (`proj.name`) | 자동으로 실시간 폴더명 반영 (개선) |
| `app/widgets/project_export_dialog.py:111` | 내보내기 다이얼로그 헤더 표시 | 동일 |
| `app/core/project_export.py:81` `default_export_filename()` | zip 파일명 생성(재-sanitize됨) | 동일, 오히려 실제 폴더명과 일치해 더 정확해짐 |
| `app/core/project.py:128,149` | 로그 메시지 | 동일 |
| `app/widgets/project_start_dialog.py:107-118` `_populate_recent()` | 최근 프로젝트 목록 표시 | **`Project` 인스턴스를 안 쓰고 `project.json`을 직접 재파싱**해 `m.get("name", name)`으로 메타데이터를 우선함 — 아래 "회귀 위험" 참고, **별도 수정 필요** |

`Project.path`(파일 경로 자체)를 써야 하는 곳(images_dir 등 하위 경로 계산)은 전부
`self.path`/`self.images_dir` 등 별도 프로퍼티를 쓰고 있어 `name`과 혼용되는 지점 없음
— 확인 완료.

`project.json`의 `name` 필드 자체는 **표시 용도 외에 실제 기능적 용도가 하나 더 있다**:
`app/core/project_export.py`의 `_infer_base_name()`(161행)이 zip 안의 `project.json`을
직접(파싱, `Project` 객체 아님) 읽어 `name`을 **가져오기(import) 시 새 폴더명 결정**에
쓴다. 이 경로는 `Project.name` 프로퍼티를 거치지 않으므로 프로퍼티를 바꿔도 영향 없음
— **`project.json`의 `name` 필드/`save_metadata(name=...)` 호출은 그대로 유지**해야 한다
(YAGNI 판단: 완전히 없애면 import 시 폴더명 추론 수단이 zip 파일명 stem 하나로 줄어
들어 사용자가 zip 파일명을 바꿔 저장하면 엉뚱한 폴더명이 생기는 회귀가 생김).

### 설계 결정
가장 단순하고 확실한 해법 그대로 채택: **`Project.name`이 메타데이터를 무시하고 항상
`self.path.name`을 반환**하도록 변경. `create()`/`open_existing()`/
`project_export.import_project_zip()`의 `save_metadata(name=...)` 호출은 **변경하지
않음**(import 폴더명 추론용으로 계속 필요, 표시 목적이 아니게 됨 — docstring 정도만
나중에 정정 가능하나 필수 아님).

### 구현 대상 파일 (2개)

**`app/core/project.py`** — `Project.name` 프로퍼티만 수정:
```python
@property
def name(self) -> str:
    return self.path.name
```
(`_meta` 프로퍼티, `created_at` 프로퍼티, `save_metadata()`, `create()`, `open_existing()`은
변경 없음.)

**`app/widgets/project_start_dialog.py`** — `_populate_recent()`(96~121행)이
`Project`를 거치지 않고 독자적으로 `project.json`을 재파싱해 메타데이터 `name`을
우선하던 로직을 제거, 항상 폴더명(`p.name`)을 쓰도록 통일(회귀 방지, 아래 참고):
```python
for p in recents:
    meta_file = p / "project.json"
    name = p.name
    updated = ""
    try:
        if meta_file.exists():
            import json
            m = json.loads(meta_file.read_text(encoding="utf-8"))
            if "updated_at" in m:
                updated = f"   ·   {_format_date(m['updated_at'])}"
    except Exception:
        pass
```
(`name = m.get("name", name)` 줄만 삭제. `updated_at` 읽기는 그대로 유지 — 이번 요청과
무관한 기존 기능.)

### 회귀 위험 검토
1. **최근 프로젝트 목록** — 위 수정 없이 `Project.name`만 바꾸면 메인 창 타이틀은
   실시간 폴더명을 따라가는데 최근 프로젝트 목록은 여전히 예전 메타데이터 이름을 보여줘
   **두 화면이 서로 다른 이름을 표시하는 새로운 불일치**가 생긴다 — 반드시 함께 고쳐야
   할 회귀 위험으로 확인, 위 수정안에 포함시킴.
2. **zip export/import(GitHub #2 라운드 A/B)** — `default_export_filename()`은
   `project.name`으로 zip 파일명을 만드는데, 변경 후에는 이 값이 실제 폴더명이 되므로
   오히려 사용자가 보는 폴더/zip 파일명 일치도가 개선된다. `import_project_zip()`이
   쓰는 `_infer_base_name()`은 `Project.name`을 거치지 않고 zip 내부 `project.json`을
   직접 읽으므로 **영향 없음** — 라운드 A/B 왕복 동작(2026-08-20 완료분) 그대로 보존.
3. **`project.json`을 파싱하는 외부 도구** — 코드베이스 안에서 `name` 필드를 기대하는
   곳은 위 두 곳(표시용 `Project.name`, 기능용 `_infer_base_name()`)뿐. `ANNOTATION_FORMAT.md`,
   `saige_converter.py` 등 다른 문서/모듈은 `project.json`의 `name` 필드와 무관.
4. **실행 중 외부 리네임** — `Project.path`는 프로젝트를 연 시점에 고정된 값이라, 앱
   구동 중에 사용자가 폴더를 리네임/이동하면 `path`가 가리키는 경로 자체가 무효화돼
   다른 여러 기능(파일 저장 등)도 함께 깨진다. 이는 이번 변경이 만드는 회귀가 아니라
   기존부터 있던 제약(프로젝트를 다시 열어야 반영) — 문서화만 해두고 고치지 않음
   (범위 밖, `Project` 싱글턴이 실시간 파일시스템 감시를 하지 않는 구조 자체의 한계).

### 검증 골든패스
1. 프로젝트 생성(`Foo`) → 폴더명 `Foo` 확인 → 앱 종료 → 탐색기에서 폴더를 `Bar`로
   리네임 → 앱 재시작 → 시작 다이얼로그 최근 프로젝트 목록에 `Bar`로 표시되는지 확인 →
   더블클릭으로 열기 → 메인 창 타이틀바에 `Bar` 표시 확인.
2. GitHub #2 라운드 A(export) → 라운드 B(import) 왕복 재검증 — zip 파일명이 실제
   폴더명 기준으로 생성되고, import 후 새 폴더명이 원본과 동일(이름 충돌 없을 때)한지
   확인, 이름 충돌 시 자동 리네임(`_imported`) 동작 그대로인지 확인.
3. `open_existing()`으로 메타데이터 없는 외부 폴더를 프로젝트로 처음 인식하는 경로도
   재확인(1회성 `save_metadata(name=p.name, imported=True)` 호출 자체는 변경 없음 —
   프로퍼티가 이 값을 더 이상 읽지 않을 뿐).

### 구현 난이도
매우 낮음 — 2개 파일, 프로퍼티 1줄 + 다이얼로그 1줄 삭제. 결정 대기 없이 바로 구현
가능. zone 에디션은 이번 라운드에서 건드리지 않음 (`app/core/project.py`는 main→zone
sync 브랜치를 통해 나중에 자연히 전달됨, 사용자가 zone 작업을 명시하지 않음).

---

## 요청 2 — 라벨링 탭 + 추론 탭 이미지 리스트에 순번 표시

### 대상 위젯
- `app/widgets/image_browser.py`(`ImageBrowser`, 라벨링 탭) — **단일 평탄 목록**
  (폴더 그룹핑은 BUG-005로 죽은 코드 제거 완료, 현재 미지원). 검색(디바운스)+정렬 4종.
- `app/widgets/inference_image_list.py`(`InferenceImageList`, 추론 탭) — 검색+정렬
  5종(폴더 정렬 포함) + **트리형 폴더 그룹핑 실제 지원**(`rglob` 재귀 스캔).

둘 다 `QTreeWidgetItem`을 컬럼 1개(`setColumnCount(1)`)로만 쓰고 있어 신규 컬럼 추가는
과설계 — **기존 텍스트 앞에 `"1. "` 문자열 접두어를 붙이는 방식**으로 결정(스타일시트/
아이콘 레이아웃 변경 불필요, 가장 단순).

### 번호 매김 기준 — "현재 표시 순서 기준 1부터"로 결정
두 위젯 다 검색/정렬이 바뀔 때마다 `_apply_display()`가 트리를 통째로 재구성하는
구조라, 그 시점에 순번도 같이 새로 매기는 것이 구현이 가장 간단하고 "지금 화면에
보이는 N번째 이미지"라는 사용자 기대와도 자연스럽게 맞는다. 재조사 결과 별도
결정 대기로 등록할 필요 없는 명확한 기본값으로 판단(전체 원본 순번 고정은 검색으로
목록이 줄어들면 "1번, 3번, 7번"처럼 번호가 듬성듬성해져 오히려 직관성이 떨어짐).

### 폴더 그룹핑 모드의 번호 — "전체 통번호"로 결정
`InferenceImageList`의 폴더 트리 모드(정렬 "폴더" 선택 시)에서 번호를 폴더별로
1부터 다시 시작할지, 전체를 통틀어 매길지 — **전체 통번호**로 확정(등록하지 않고
권장안 채택). 근거: 사용자가 "이미지 리스트에 번호"라고만 했고 폴더별 번호가 필요하다는
신호가 없으며, "총 몇 번째 이미지"를 파악하는 용도(예: "127번째 이미지에서 오류 남")로
쓰일 가능성이 폴더 내 상대 순번보다 실용적이다. `ImageBrowser`는애초에 폴더 그룹핑이
없어 이 쟁점 자체가 없음.

### `image_browser.py` 구현 설계
단일 평탄 목록이라 `_apply_display()`가 만든 `filtered`(현재 표시 순서) 리스트의
인덱스를 그대로 번호로 쓰면 된다. 단, `refresh_item()`/`refresh_items()`가 트리를
재구성하지 않고 개별 항목 텍스트만 갱신하는 경로가 있어(R6 성능 최적화, `_status_cache`
활용) 이 경로에서도 같은 번호가 유지되도록 `path → 번호` 매핑을 저장해둬야 한다.

```python
# __init__
self._path_to_number: dict[Path, int] = {}

# _apply_display() — self._paths = filtered 다음 줄에 추가
self._path_to_number = {p: i + 1 for i, p in enumerate(filtered)}

# 신규 헬퍼
def _numbered_label(self, path: Path) -> str:
    num = self._path_to_number.get(path)
    name = self._rel_name(path)
    return f"{num}. {name}" if num is not None else name
```
`_make_tree_item()`의 `label = display_name if display_name is not None else self._rel_name(path)`을
`self._numbered_label(path)` 호출로 교체, `refresh_item()`/`refresh_items()`의
`item.setText(0, self._rel_name(path))` 2곳도 `self._numbered_label(path)`로 교체.

성능: `_path_to_number` 구축은 O(n) 딕셔너리 컴프리헨션 — `_apply_display()`가 이미
`filtered` 전체를 순회해 트리 아이템을 만드는 비용에 비하면 무시할 수준. R6가 도입한
`_status_cache`/`_SEARCH_DEBOUNCE_MS`는 그대로 유지되며 이번 변경과 상호작용 없음
(디바운스 타이머가 만료된 뒤 1회 `_apply_display()`가 호출되는 흐름은 동일).

### `inference_image_list.py` 구현 설계
이 위젯은 폴더 트리 모드가 실재해서 `filtered`(정렬된 플랫 리스트)의 인덱스를 그대로
쓰면 안 된다 — 트리 렌더링 순서(폴더 헤더가 중간에 끼어드는 실제 화면 순서)와
`filtered`의 나열 순서가 항상 정확히 대응한다는 보장이 약하다(다단계 중첩 폴더에서
그룹핑 함수가 부모별로 묶는 방식이 `filtered`의 정렬 키와 100% 동일한 순회 순서를
보장하지 않을 수 있음). **트리를 완성한 뒤 실제 화면에 렌더링되는 순서를
`QTreeWidgetItemIterator`로 순회하며 번호를 매기는 방식**이 "보이는 순서 = 번호"를
항상 정확히 보장하는 가장 단순한 방법이다(폴더 헤더 아이템은 UserRole에 Path가
없어 자동으로 건너뛰어짐 — 번호는 이미지 leaf 항목에만 붙는다).

```python
from PyQt6.QtWidgets import QTreeWidgetItemIterator  # 신규 import

def _number_items(self) -> None:
    """트리에 실제로 보이는 순서(펼침 상태 무관)대로 이미지 항목에 전체 통번호를 접두."""
    idx = 1
    it = QTreeWidgetItemIterator(self._tree)
    while it.value():
        item = it.value()
        if self._get_item_path(item) is not None:
            item.setText(0, f"{idx}. {item.text(0)}")
            idx += 1
        it += 1
```
`_apply_display()`에서 트리 재구성 분기(`if self._sort_mode == "folder": ... else: ...`)
직후, "선택 복원" 절 이전에 `self._number_items()` 1줄 호출 추가.

성능: 이미 만들어진 트리를 1회 더 순회(leaf+폴더 헤더 합쳐 O(n))하는 정도로,
`_build_folder_tree()`/leaf 생성 자체의 O(n)에 비해 무시할 수준. 검색 디바운스
(`_SEARCH_DEBOUNCE_MS`)는 동일하게 유지.

### 검증 골든패스
- `ImageBrowser`: 검색어 입력(디바운스 후 재적용) → 필터링된 목록이 1부터 다시
  번호 매겨지는지, 정렬 4종(파일명↑↓/라벨완료↑↓) 전환 시마다 번호가 새 순서에 맞게
  갱신되는지, 개별 편집(어노테이션 저장)으로 `refresh_item()`만 호출되는 경로에서
  번호가 유지(재계산 없이도 정확)되는지 확인.
- `InferenceImageList`: 검색/정렬(파일명↑↓/날짜↑↓) 각각 번호 확인, "폴더" 정렬
  선택 시 폴더 헤더는 번호가 안 붙고 이미지 항목만 화면 순서대로(중첩 폴더 포함)
  전체 통번호가 매겨지는지, `load_files()`(개별 파일 선택, 공통 루트 없음) 경로의
  1단계 그룹핑에서도 정상 동작하는지 확인.

### zone 에디션 이식 메모 (이번 라운드 범위 아님)
`D:\segmentation model-zone-analysis-tab`(브랜치 `feature/zone-analysis-tab`)에도
두 파일이 동일한 함수/구조(`_apply_display`, `_SORT_MODE_KEYS`/`_SORT_MODES`,
`_make_leaf_item`, `_build_folder_tree` 등)로 존재함을 라인 위치까지 확인 — 큰 구조
차이 없어 이번 설계를 그대로 이식 가능할 것으로 보이나 **상세 diff는 확인하지 않음**
(이번 라운드는 main만 대상, 사용자 지시대로 zone 코드는 건드리지 않음). main 구현·
검증 완료 후 리더가 별도 라운드로 이식할 것 — CLAUDE.md의 sync 브랜치+PR 절차
(`sync/main-into-zone-analysis-tab-<날짜>`)를 따르거나, 두 파일만 별도로 직접
포팅하는 경량 라운드 중 리더가 선택.

### 구현 난이도
낮음 — `image_browser.py` 3곳(속성 추가 1 + 헬퍼 1 + 호출부 교체 3곳),
`inference_image_list.py` 2곳(신규 메서드 1 + 호출 1줄, import 1줄 추가). 결정 대기 없이
바로 구현 가능.
