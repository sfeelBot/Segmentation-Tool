# QA — 버그 및 VOC 추적

## Open Issues

| ID | 우선순위 | 설명 | 보고자 | 상태 |
|----|----------|------|--------|------|
| BUG-003 | P3 | `AnnotationCanvas._translate_selected()`(Select 도구로 어노테이션을 캔버스 밖까지 드래그) 후 마스크가 전량 0이 되어도 정리(cleanup)가 없어 `self._annotations`에 빈 brush_mask가 세션 동안 남을 수 있음. 저장 시 `annotation_store.save()`가 `a.mask.any()`로 걸러내 디스크에는 저장되지 않지만(데이터 유실·오염 없음), 라벨링 탭 어노테이션 목록 패널(`labeling_tab.py:_refresh_ann_list()`)에 렌더링되지 않는 유령 항목("#N [Mask] ...")이 다음 이미지 전환 전까지 표시될 수 있음 | R3 검증(verifier) | Open |
| BUG-004 | P3 | `auto_labeler.collect_unlabeled()`의 `get_label_status()` 1회 read 통합(R6)이 `get_ok()+load()` 2회 read 구버전과 100% 동치는 아님 — `annotations` 배열에 앱이 절대 생성하지 않는(=`save()`가 쓰지 않는) 미인식 `type` 값의 원소만 있는 손상/외부편집 JSON의 경우, 구버전은 `load()`가 해당 원소를 조용히 건너뛰어 결과 리스트가 비므로 "unlabeled"로 간주(자동 라벨링 대상에 포함)했지만 신버전은 `annotations` 배열 자체가 non-empty이므로 "labeled"로 간주(대상에서 제외). 정상 사용(앱이 직접 저장한 JSON)에서는 재현 불가 — 손으로 편집했거나 외부 도구가 만든 손상 파일에서만 발생. 부수 관찰: 최상위가 dict가 아닌(JSON 배열 등) 손상 파일에서는 구버전(`load()`가 `AttributeError`로 크래시)과 달리 신버전은 크래시 없이 "unlabeled"로 안전 처리 — 이 케이스는 오히려 신버전이 더 견고함 | R6 검증(verifier) | Open |
| BUG-005 | P2 | `image_browser.py`의 폴더 그룹핑 기능(`_build_folder_tree`/`_make_folder_item`/정렬모드 "폴더")이 실제로는 어떤 사용자 동작으로도 트리거되지 않는 죽은 코드 상태. `reload()`가 `images_dir()`에서 비재귀적 `glob(pat)`만 수행(2026-05-27 커밋 `00fd6779` "B2" 의도적 설계 — `dataset._collect_pairs()`도 flat 스캔이라 학습에서 제외되는 이미지가 브라우저에는 보이는 불일치를 막기 위함)하고, 이미지 추가 경로 `_on_add()`/`_on_add_folder()` 둘 다 선택한 파일/폴더를 `images_dir()` 바로 아래로 평탄하게 복사(`_on_add_folder()`도 `Path(folder).iterdir()`로 비재귀적)하기 때문에, 앱의 어떤 기능으로도 `images_dir()` 하위에 서브폴더 구조가 만들어지지 않는다. 사용자가 파일탐색기(상단 폴더 열기 버튼)로 `images_dir()`에 직접 하위폴더를 복사해 넣어도 `reload()`가 무시하므로 브라우저 목록에도, 학습 데이터셋에도 전혀 나타나지 않음(검증 중 실제로 재현 확인: `projects/nok/images/sub_test/`에 이미지 1장을 넣고 앱 재시작해도 목록 5장 그대로, 폴더 헤더 미표시). `_build_folder_tree`/`_make_folder_item` 코드 자체는 `_all_paths`를 직접 조작해 강제로 호출하면 정상 동작(폴더 헤더 SVG 아이콘 정상 렌더링 확인)하므로 이번 "장식 이모지 제거" 라운드가 새로 만든 회귀는 아님. 다만 `QA.md`/`docs/roadmap.md`의 GitHub #1 VOC 응답("라벨링 탭은 기존부터 폴더 트리 있음")과 로드맵 "폴더 접기/펼치기 그룹 헤더" 완료 표시가 실제 도달 가능한 동작과 어긋나므로 문서 정정 또는 기능 구현(예: `_on_add_folder`가 원본 하위 구조를 보존해 복사, `reload()`를 재귀 스캔으로 전환하되 `dataset.py`도 함께 갱신) 중 하나가 필요 | 장식 이모지 제거 라운드 검증(verifier) | Open |
| BUG-006 | P2 | `model_tab.py` 검증/로드 경로 불일치 — `model_validator.validate()`는 허용 목록(`ALLOWED_MODULES`)에 없는 모듈 import를 [WARN]으로만 표시하고 `result.ok=True`를 반환(에러로 취급 안 함), 그래서 상태 라벨이 초록 "검증 통과"로 뜨고 로드 버튼도 활성화되지만, 실제 `_on_load()` → `load_from_code()`가 사용하는 `exec()` 샌드박스(`_make_safe_import`)는 `_ALLOWED_ROOTS`(=`ALLOWED_MODULES`)에 없는 모듈이면 무조건 `ImportError`를 던져 로드가 항상 실패한다(재현: 에디터에 `import random` + 유효한 `nn.Module`을 넣으면 검증은 "[WARN] Line 1: 'random' — 허용 목록에 없는 모듈입니다." 뒤에 "[OK] 검증 통과"까지 나오지만, 로드 버튼을 눌러도 "코드 실행 오류: 'random' import는 허용되지 않습니다."로 즉시 실패). 이번 라운드(model_tab.py 팔레트 정규화, 커밋 a8ac52d)가 만든 회귀는 아니고 이전부터 존재하던 validate()/load_from_code() 간 정책 불일치이며, 실제 GUI 골든패스(검증→로드) 확인 중 발견 | model_tab.py 팔레트 정규화 라운드 검증(verifier) | Open |
| BUG-009 | P2 | 추론 탭 `InferenceImageList`(커밋 `b09fb83`)에서 검색창에 필터를 입력했다가 지우면(예: "gamma" 검색 → 지우기) 트리는 전체 이미지로 정상 복원되지만 하단 이전/다음 카운터(`inference_tab.py`의 `_lbl_nav`, "N / M" 표시)가 갱신되지 않고 필터 중 값("1 / 1")에 고정돼 남음 — "다음" 버튼을 눌러 실제 네비게이션이 발생해야만 올바른 값("4 / 5")으로 정정됨. 원인: `InferenceImageList._apply_display()`가 필터/정렬 변경 후 선택된 경로가 이전과 동일하면(`new_path == cur_path`) `image_selected` 시그널을 재발행하지 않는데, `inference_tab.py`의 `_update_nav_label()` 호출은 `_on_image_selected`(시그널 수신 시)와 `_after_load()`/`_on_prev`/`_on_next`에만 연결돼 있어 "같은 이미지가 선택된 채 전체 개수만 바뀌는" 케이스를 놓침. 실제 이미지 인덱스/네비게이션 자체는 정상(다음 클릭 시 올바른 이미지로 이동)이라 데이터 손상은 없으나, 목록 개수를 오인시키는 표시 버그 | 학습/추론 탭 서브스플리터 라운드 검증(verifier) | Open |
| BUG-010 | P3 | `InferenceImageList`의 폴더 트리(`_TREE_STYLE`, `setRootIsDecorated(True)`)에서 하위 항목이 있는 폴더 헤더 옆에 펼침/접힘 화살표(인디케이터)가 전혀 렌더링되지 않음(스크린샷 8배 확대로 확인 — 화살표 영역이 완전히 빈 배경). 더블클릭으로는 정상적으로 접기/펼치기가 동작하나, 통상 기대되는 단일 클릭 화살표 진입점이 없어 발견성이 낮음. `QTreeWidget::branch { background: ... }` 스타일시트를 지정하면 Qt가 OS 기본 화살표 렌더링을 억제하는데 `:has-children`/`:open`/`:closed` 상태별 커스텀 화살표 이미지를 별도로 지정하지 않아 발생 — `app/widgets/image_browser.py`의 기존 `_TREE_STYLE`을 그대로 재사용한 결과라 이번 라운드가 새로 만든 결함은 아니지만, `image_browser.py` 쪽은 BUG-005(폴더 트리가 죽은 코드)로 인해 지금까지 실제로 노출된 적이 없었고 이번 라운드의 `InferenceImageList`가 처음으로 실사용 가능한 경로에서 이 결함을 드러냄 | 학습/추론 탭 서브스플리터 라운드 검증(verifier) | Open |
| BUG-014 | P3 | `AnnotationCanvas._push_undo()`(브러시/지우개 계열 도구가 스트로크를 시작할 때마다 호출)가 `self._annotations` 전체를 `copy.deepcopy()`하는데, brush_mask 어노테이션의 `mask`는 항상 이미지 전체 해상도의 `(H,W)` uint8 dense 배열이라(예: 5472×3648 이미지 1장당 마스크 1개 ≈19MB) 대형 이미지에 brush_mask 어노테이션이 수백 개 쌓인 상태에서 스트로크를 1개만 더 그려도 그 즉시 수 GB 규모의 deep copy가 발생하고, 이를 최대 30개(`_undo_stack`)까지 유지한다. 검증 중 실측: 5472×3648 이미지에 brush_mask 약 200개(대부분 80×80 소영역)가 있는 상태에서 `_push_undo()` 1회 호출 시 이 세션 환경(Windows, 페이징 파일 2GB — R4 구현 로그에 동일 환경 제약 기록)에서 `numpy._core._exceptions._ArrayMemoryError: Unable to allocate 19.0 MiB` 로 크래시 재현(물리 RAM 자체는 16GB+ 여유 있었음 — 페이징 파일/커밋 한도 문제로 추정). GitHub #6-B(어노테이션 개수 증가 시 로딩 지연) 라운드가 만든 회귀 아님 — `_push_undo()`/`_refresh_ann_list()`/`_OverlayWorker.run()`은 서로 다른 함수이며 이번 라운드는 뒤 두 개만 수정함, `_push_undo()`는 그 이전부터 동일한 전체 deepcopy 구조였음. 다만 #6-B가 "대량 어노테이션에서의 체감"을 개선한 직후라 이 한계가 상대적으로 더 눈에 띌 수 있어 함께 기록 | GitHub #6-B 검증(verifier) | Open |

---

## Closed Issues

| ID | 수정 버전 | 설명 | 근본 원인 | 해결 방법 |
|----|-----------|------|-----------|-----------|
| BUG-001 | Phase 1 | `ImportError: DLL load failed while importing QtWidgets` — PyQt6 6.11.0 기동 불가 | PyQt6 6.8+ 가 Windows Anaconda(Python 3.13) 환경에서 DLL 프로시저 못 찾음 | PyQt6 6.7.1 고정 (`requirements.txt`); 6.8+ 설치 금지 |
| BUG-002 | R1(미배포, 커밋 예정) | `annotation_store.rle_encode()` — 모든 brush_mask 어노테이션이 저장 시 빈 RLE 문자열이 되어 전량 데이터 유실 (재현: `mask[10:20,10:20]=1` 인 100픽셀 마스크도 `rle_encode()` → `""`, 왕복 후 `rle_decode()` 결과 전부 0). `projects/nok/` 실데이터는 전부 polygon 타입이라 이 프로젝트에서는 아직 미발현. 폴리곤 어노테이션은 영향 없음(이 함수를 타지 않음). | `rle_encode()` 내부 `diff = np.diff(flat_uint8, prepend=0, append=0)` 가 `flat`의 uint8 dtype 을 그대로 유지해 1→0 하강 엣지(-1)가 부호없는 정수 언더플로우로 255 가 됨 → `np.where(diff == -1)` 이 항상 빈 배열 → `n = min(len(starts), len(ends)) = 0` → `return ""`. v1.6.0 초기 릴리즈부터 존재하던 결함으로 추정(커밋 43fad19), 이후 경쟁조건 방지 커밋(5769306)의 `n = min(...)` 방어 코드가 예외를 삼켜 증상을 더 눈에 띄지 않게 만듦. | `np.diff` 호출 전 `flat`을 `int8`로 캐스팅(`flat.astype(np.int8)`, prepend/append도 `np.int8(0)`)해 부호없는 언더플로우를 방지. 기존 `n = min(len(starts), len(ends))` 방어 코드(경쟁조건 대비)는 그대로 유지 — 별개 안전장치. 100px/~1.8Mpx 등 여러 마스크로 `rle_encode`→`rle_decode` 라운드트립 검증 완료. **주의**: 이 수정 이전에 이미 저장되어 `"rle": ""`로 남은 과거 brush_mask 데이터는 복구 불가(원본 마스크가 저장 시점에 이미 소실됨). |
| BUG-007 | 디자인 톤 재검토 라운드4 | `loss_chart.py` 배색 정규화(커밋 `e76361a`)에서 그리드(`_GRID`)와 epoch 경계 세로선(`_EPOCH`)이 동일한 `#374151`로 통일돼 두 선이 실제 렌더링에서 거의 구분되지 않음(더미 데이터 렌더링+확대 스크린샷으로 확인, P3 — 데이터 판독엔 영향 없음) | 배색 매핑표에 "그리드와 통일"로 명시된 의도된 절충이었으나 epoch 경계 표시라는 원래 목적이 무력화됨 | `_EPOCH`를 그리드보다 밝은 앱 표준 토큰 `#4b5563`("테두리 강조/비활성")로 분리 — 리더가 직접 1줄 수정, `py_compile` 확인 완료 |
| BUG-008 | 디자인 톤 재검토 라운드5 | 학습 탭 `_queue_splitter`(커밋 `a32a8b5`)와 추론 탭 `outer_splitter`/3분할 스플리터(커밋 `b09fb83`)가 `setMinimumHeight/Width()`를 지정해뒀음에도 핸들을 끝까지 드래그하면 해당 pane이 0px로 완전히 붕괴(제목까지 소실). 라벨링 탭 서브스플리터(`f086636`)도 동일 패턴이라 같은 위험 공유 | `QSplitter.setChildrenCollapsible(False)`를 호출하지 않아 Qt 기본값(`childrenCollapsible=True`)이 적용됨 — `setMinimumHeight/Width`는 창 리사이즈 제약일 뿐 수동 드래그 collapse는 막지 못함(Qt 기본 동작) | 리더가 직접 `setChildrenCollapsible(False)`를 5개 스플리터 전부(학습 `_queue_splitter`, 추론 `outer_splitter`+3분할 `splitter`, 라벨링 `_splitter`+`_left_splitter`+`_right_splitter`)에 추가, `py_compile` 확인 완료(커밋 `7a98760`). **재검증 완료(2026-08-20, verifier)** — `python main.py` 실제 GUI 드래그로 5개 스플리터 전부 양방향 극단 이동 확인: 학습 탭 `_queue_splitter`(큐박스 min 120px / 모니터패널 min 150px), 추론 탭 `outer_splitter`(상단 체크포인트영역 min 140px / 메인영역 min 200px)와 3분할 `splitter`(목록패널 min 140px / 범례패널 min 160px), 라벨링 탭 `_splitter`(좌패널 min 150px / 우패널 min 130px)·`_left_splitter`(이미지브라우저 min 80px / 클래스패널 min 80px)·`_right_splitter`(어노테이션목록 min 80px / 로그패널 min 80px) 전부 설정된 최소 크기에서 정확히 멈추고 0px 붕괴·제목 소실 없음. 각 탭에서 정상 범위 중간 드래그(자유 리사이즈)도 문제없이 동작 확인 — `setChildrenCollapsible(False)`가 일반 리사이즈를 막지 않음. |
| BUG-011 | GitHub #3(b) 검증 후속 | 브러시 계열 도구 활성 상태에서 캔버스 더블클릭으로 브러시 크기 다이얼로그(GitHub #3(b), 커밋 `29248fa`)를 열면, 더블클릭의 첫 클릭(press+release)이 `mouseDoubleClickEvent()`보다 먼저 처리되어 클릭 지점에 원치 않는 `[Mask]` 어노테이션이 추가됨(OK/Cancel 무관하게 남음, Undo로만 제거 가능) | `mouseDoubleClickEvent()`가 브러시 페인트 자체를 막는 로직이 없어 press→release 사이 커밋된 미세 스트로크가 그대로 남음 | 브러시/버킷/지우개/영역지우개 분기 진입 시 다이얼로그를 띄우기 전에 `self.undo()` 호출 — `mousePressEvent`가 브러시 페인트 시작 시 항상 `_push_undo()`를 먼저 호출하므로, undo 1회가 정확히 이번 클릭 시퀀스의 stray 스트로크만 되돌림(그 이전 정상 작업엔 영향 없음). 리더가 직접 1줄 수정, `py_compile` 확인 완료. **재검증 완료(2026-08-20, verifier)** — `QTest.mouseDClick()`으로 실제 Qt 더블클릭 이벤트 시퀀스를 재현(Cancel 1회 + OK 3회 반복), 매번 stray 어노테이션 0건·브러시 크기는 정상 반영됨을 확인. 회귀 확인: 일반 연속 페인팅은 여전히 정상 커밋, Ctrl+Z(undo) 단축키도 정상 동작. |
| BUG-012 | GitHub #3/#4/#6-A/#7 라운드2 검증 후속 | 라벨링 탭에서 GitHub #7 "예" 경로(라벨 삭제 후 OK) 직후엔 사이드바 아이콘이 정확하지만, 다른 이미지 갔다 돌아오면 "미라벨"로 되돌아감(디스크 JSON·툴바 체크는 항상 정확, 표시 캐시만 stale) | `_on_toggle_ok()`의 flush 단계가 호출하는 옛 `_do_save()`(daemon 스레드로 비동기 `store.save()` 후 즉시 `annotation_saved` emit)와, 바로 뒤이은 `toggle_ok()`의 동기 `get_ok()`/`set_ok()` 읽기-수정-쓰기가 **같은 파일에 대한 순서 보장 없는 두 writer**로 경쟁 — 나중에 끝나는 쪽이 이기는 레이스라 `image_browser.refresh_item()`(디스크 재조회 자체는 정상 동작)이 레이스에서 앞선 emit 시점의 상태를 캐싱해버림 | `_do_save()`에 `sync: bool` 매개변수 추가 — `True`면 스레드 없이 동기로 즉시 저장. `_on_toggle_ok()`의 flush를 `_do_save(sync=True)`로 호출해 `toggle_ok()`가 같은 파일을 건드리기 전 쓰기 완료를 보장. 다른 `_do_save()` 호출부(500ms 디바운스, 이미지 전환 전 flush)는 경쟁하는 두 번째 writer가 없어 그대로 둠. 커밋 `5d551c3`. **재검증 완료(2026-08-20, verifier)** — 실제 어노테이션이 있는 이미지(`11번`)로 OK 확인창 "예" 흐름을 거친 뒤 다른 이미지로 갔다 돌아오기를 6회 반복, 매 라운드 사이드바 캐시=`ok`·디스크 JSON `ok:true`·`annotations:[]` 완전 일치(불일치 0건). 회귀 확인: 무라벨 이미지 OK 토글(확인창 없는 경로) on/off 정상, 이미지 전환 시 디바운스 저장 flush(미저장 브러시 스트로크 자동 저장)도 정상 동작. |
| BUG-013 | GitHub #3/#4/#6-A/#7 라운드2 검증 후속 | 브러시 크기 더블클릭 다이얼로그 문자열이 `t()` 체계 밖 한국어 하드코딩 — English 설정에서도 이 다이얼로그만 한국어로 표시됨 | 이번 라운드(GitHub #3(b))에서 신규 추가된 문자열이라 기존 i18n en 정비(193키) 범위 밖에 있었음 | `i18n.py`에 `tool.brush_size_dialog.title`/`.label` 키를 ko/en 양쪽에 추가, `annotation_canvas.py`에 `t` import 후 하드코딩 문자열을 `t()` 호출로 교체. 커밋 `5d551c3`. **재검증 완료(2026-08-20, verifier)** — `i18n.set_language("en")`에서 `t("tool.brush_size_dialog.title")`="Brush Size", `.label`="Brush size (1~200)" 확인. `ko`로 되돌리면 "브러시 크기"/"브러시 크기 (1~200)"로 정상 복귀. |

---

## VOC (Voice of Customer)

사용자가 직접 제기한 요청·불편 사항.

| 날짜 | 요청 내용 | 결정 | 근거 |
|------|-----------|------|------|
| 2026-08-20 | [GitHub #1](https://github.com/sfeelBot/Segmentation-Tool/issues/1) "사용성 정리" ① 라벨링/추론 이미지 탭에 폴더 정보(최하위 폴더명) 표시 요청 | 수용 — 이미 진행 중인 UI/UX 재편 라운드 2에서 커버됨(라벨링 탭은 기존부터 폴더 트리 있음, 추론 탭은 라운드 2에서 트리형 폴더 그룹핑 신규 추가 예정). **2026-08-20 재검증 결과 정정 필요**: 라벨링 탭의 "기존부터 폴더 트리 있음" 판단은 코드상 실제로 도달 불가능한 것으로 확인됨 — [BUG-005](#open-issues) 참고 | `docs/specs/ui-redesign-plan-2026-08-19.md`, `docs/roadmap.md` "UI/UX 재편" 절 |
| 2026-08-20 | [GitHub #1](https://github.com/sfeelBot/Segmentation-Tool/issues/1) "사용성 정리" ② RTX 4500 Ada GPU인데 `torch 2.13.0+cpu`(CPU 전용)로 설치됨, torchvision 설치 실패 원인 문의, .exe 빌드 시 의존성 별도 설치 필요 여부 문의 | 원인 파악 완료 — `requirements.txt`에 CUDA index-url 안내가 없어 `pip install -r requirements.txt`를 먼저 실행하면 CPU 전용 빌드가 잡힘. `docs/USER_MANUAL.md`엔 이미 올바른 설치 순서(torch를 CUDA 빌드로 먼저 설치)가 있었으나 루트 `README.md`가 빈 플레이스홀더라 발견이 안 됨 | **즉시 수정**: `README.md`에 설치 가이드 추가(USER_MANUAL 링크 포함), `requirements.txt`에 경고 주석 추가, `USER_MANUAL.md` GPU 표에 RTX Ada 워크스테이션 계열 행 추가. .exe 빌드 의존성 별도 설치 문제는 CLAUDE.md상 PyInstaller 패키징이 범위 밖이라 별도 논의 필요 |
| 2026-08-20 | [GitHub #2](https://github.com/sfeelBot/Segmentation-Tool/issues/2) "프로젝트 내보내기 기능" ① 프로젝트를 클릭하면 자동으로 열리게 해달라 | **사용자 재확인으로 정정**: 앱 내부 최근 프로젝트 목록 얘기가 아니라 "전용 프로젝트 확장자를 만들어 OS 파일탐색기에서 더블클릭하면 앱이 바로 열리게" 해달라는 요청이었음. Windows 파일 연결은 보통 설치 프로그램이 등록하므로 exe 패키징(별도 "추후" 항목)에 하위 요구사항으로 편입 — 지금 스코프 아님 | `docs/roadmap.md` "exe 패키징 + Setup Guide" 절 |
| 2026-08-20 | [GitHub #2](https://github.com/sfeelBot/Segmentation-Tool/issues/2) "프로젝트 내보내기 기능" ② 프로젝트 전체를 내보내거나 하나의 파일로 통합하는 기능 요청 | 수용 — export(라운드 A: zip 패키징) + import(라운드 B: zip→프로젝트 복원) 둘 다 진행 확정. checkpoints 기본 미체크/user_models 기본 체크, import 이름 충돌 시 자동 리네임(덮어쓰기 금지) | `docs/specs/voc-github-issues-2026-08-20.md` |

---

## 이슈 작성 가이드

### Bug ID 형식
`BUG-{순번}` (예: `BUG-001`)

### 우선순위
- **P0** — 앱 크래시·데이터 손실
- **P1** — 핵심 기능 동작 불가
- **P2** — 기능 동작하나 불편함
- **P3** — 개선 사항·UX 요청

### Bug 항목 예시
```
| BUG-001 | P1 | 폴리곤 닫기 후 Undo가 동작하지 않음 | 사용자 VOC | 조사 중 |
```

### VOC 항목 예시
```
| 2025-01-15 | 브러시 크기 단축키 추가 요청 | 수용 — Phase 3에서 구현 | 사용성 향상 |
```
