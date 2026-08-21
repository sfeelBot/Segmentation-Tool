# QA — 버그 및 VOC 추적

## Open Issues

| ID | 우선순위 | 설명 | 보고자 | 상태 |
|----|----------|------|--------|------|
| BUG-004 | P3 | `auto_labeler.collect_unlabeled()`의 `get_label_status()` 1회 read 통합(R6)이 `get_ok()+load()` 2회 read 구버전과 100% 동치는 아님 — `annotations` 배열에 앱이 절대 생성하지 않는(=`save()`가 쓰지 않는) 미인식 `type` 값의 원소만 있는 손상/외부편집 JSON의 경우, 구버전은 `load()`가 해당 원소를 조용히 건너뛰어 결과 리스트가 비므로 "unlabeled"로 간주(자동 라벨링 대상에 포함)했지만 신버전은 `annotations` 배열 자체가 non-empty이므로 "labeled"로 간주(대상에서 제외). 정상 사용(앱이 직접 저장한 JSON)에서는 재현 불가 — 손으로 편집했거나 외부 도구가 만든 손상 파일에서만 발생. 부수 관찰: 최상위가 dict가 아닌(JSON 배열 등) 손상 파일에서는 구버전(`load()`가 `AttributeError`로 크래시)과 달리 신버전은 크래시 없이 "unlabeled"로 안전 처리 — 이 케이스는 오히려 신버전이 더 견고함 | R6 검증(verifier) | Open |

---

## Closed Issues

| ID | 수정 버전 | 설명 | 근본 원인 | 해결 방법 |
|----|-----------|------|-----------|-----------|
| BUG-005 | 2026-08-21 죽은 코드 정리 | `image_browser.py`의 폴더 그룹핑 기능(`_build_folder_tree`/`_make_folder_item`/정렬모드 "폴더")이 실제로는 어떤 사용자 동작으로도 트리거되지 않는 죽은 코드 상태(`reload()`는 비재귀 스캔만 하고 이미지 추가 경로도 전부 평탄 복사라 하위폴더 구조 자체가 만들어지지 않음) | 진짜로 재귀 폴더 스캔 기능을 만들려면 `app/core/dataset.py`의 학습 스캔 로직까지 함께 바꿔야 함(2026-05-27 `00fd6779`가 `image_browser.py`를 의도적으로 비재귀로 맞춘 이유가 "학습 시 제외되는 이미지가 브라우저엔 보이는 불일치 방지"였기 때문) — 이는 "버그 수정" 범위를 넘는 별도 기능 개발이라 판단, 대신 도달 불가능한 죽은 코드를 제거하는 방향으로 결정(`docs/decisions-needed.md` 등록 후 리더 판단) | `image_browser.py`에서 `_build_folder_tree()`/`_make_folder_item()`/`_get_folder_font()`/모듈 전역 `_folder_font`/`from collections import defaultdict` 삭제, 정렬모드 목록에서 "folder" 제거(`_SORT_MODE_KEYS`, i18n `browser.sort.folder` ko/en 키 삭제), `_apply_display()`의 "folder" 정렬 분기와 트리 분기 삭제, `_select_by_index()`의 폴더 자동펼침 로직·`refresh_item()`의 폴더 자식 분기(둘 다 폴더 헤더 자식(`item.parent() is not None`)이 더 이상 존재하지 않아 항상 동일 분기만 타므로 단순화) 제거. 추론 탭 `inference_image_list.py`는 `rglob()` 기반 실제 재귀 스캔을 쓰는 별개 구현이라 살아있는 코드로 확인, 그대로 유지. GitHub #1 VOC 응답과 로드맵 "폴더 접기/펼치기 그룹 헤더" 완료 표시를 "라벨링 탭은 폴더 그룹핑 미지원(단일 평탄 목록) — 필요 시 별도 기능 요청으로 논의"로 정정. |
| BUG-006 | 2026-08-21 버그 일괄정리 | `model_tab.py` 검증/로드 경로 불일치 — `model_validator.validate()`가 허용 목록 밖 import를 [WARN]+`ok=True`로만 표시해 검증 통과·로드버튼 활성화로 보이지만, 실제 `load_from_code()`의 exec 샌드박스는 같은 import를 무조건 `ImportError`로 실패시킴 | 검증기와 로더의 허용 정책이 서로 다른 엄격도로 구현돼 있었음(검증기는 경고, 로더는 하드 차단) | 보안 샌드박스(로더)는 완화하지 않고 검증기를 로더 실동작에 맞춰 엄격화 — `model_validator.py`의 `_check_imports()`에서 허용목록 밖 import를 `warnings`가 아닌 `errors`에 추가(`ok=False`)하도록 2줄 수정. `model_tab.py`는 이미 `result.ok`로 로드버튼을 제어해 추가 수정 불필요. 커밋 `7e95ee0`. **재검증 필요**(허용목록 밖 import 시 검증실패+로드버튼 비활성화, 정상 코드 회귀 없음 확인). |
| BUG-001 | Phase 1 | `ImportError: DLL load failed while importing QtWidgets` — PyQt6 6.11.0 기동 불가 | PyQt6 6.8+ 가 Windows Anaconda(Python 3.13) 환경에서 DLL 프로시저 못 찾음 | PyQt6 6.7.1 고정 (`requirements.txt`); 6.8+ 설치 금지 |
| BUG-002 | R1(미배포, 커밋 예정) | `annotation_store.rle_encode()` — 모든 brush_mask 어노테이션이 저장 시 빈 RLE 문자열이 되어 전량 데이터 유실 (재현: `mask[10:20,10:20]=1` 인 100픽셀 마스크도 `rle_encode()` → `""`, 왕복 후 `rle_decode()` 결과 전부 0). `projects/nok/` 실데이터는 전부 polygon 타입이라 이 프로젝트에서는 아직 미발현. 폴리곤 어노테이션은 영향 없음(이 함수를 타지 않음). | `rle_encode()` 내부 `diff = np.diff(flat_uint8, prepend=0, append=0)` 가 `flat`의 uint8 dtype 을 그대로 유지해 1→0 하강 엣지(-1)가 부호없는 정수 언더플로우로 255 가 됨 → `np.where(diff == -1)` 이 항상 빈 배열 → `n = min(len(starts), len(ends)) = 0` → `return ""`. v1.6.0 초기 릴리즈부터 존재하던 결함으로 추정(커밋 43fad19), 이후 경쟁조건 방지 커밋(5769306)의 `n = min(...)` 방어 코드가 예외를 삼켜 증상을 더 눈에 띄지 않게 만듦. | `np.diff` 호출 전 `flat`을 `int8`로 캐스팅(`flat.astype(np.int8)`, prepend/append도 `np.int8(0)`)해 부호없는 언더플로우를 방지. 기존 `n = min(len(starts), len(ends))` 방어 코드(경쟁조건 대비)는 그대로 유지 — 별개 안전장치. 100px/~1.8Mpx 등 여러 마스크로 `rle_encode`→`rle_decode` 라운드트립 검증 완료. **주의**: 이 수정 이전에 이미 저장되어 `"rle": ""`로 남은 과거 brush_mask 데이터는 복구 불가(원본 마스크가 저장 시점에 이미 소실됨). |
| BUG-007 | 디자인 톤 재검토 라운드4 | `loss_chart.py` 배색 정규화(커밋 `e76361a`)에서 그리드(`_GRID`)와 epoch 경계 세로선(`_EPOCH`)이 동일한 `#374151`로 통일돼 두 선이 실제 렌더링에서 거의 구분되지 않음(더미 데이터 렌더링+확대 스크린샷으로 확인, P3 — 데이터 판독엔 영향 없음) | 배색 매핑표에 "그리드와 통일"로 명시된 의도된 절충이었으나 epoch 경계 표시라는 원래 목적이 무력화됨 | `_EPOCH`를 그리드보다 밝은 앱 표준 토큰 `#4b5563`("테두리 강조/비활성")로 분리 — 리더가 직접 1줄 수정, `py_compile` 확인 완료 |
| BUG-008 | 디자인 톤 재검토 라운드5 | 학습 탭 `_queue_splitter`(커밋 `a32a8b5`)와 추론 탭 `outer_splitter`/3분할 스플리터(커밋 `b09fb83`)가 `setMinimumHeight/Width()`를 지정해뒀음에도 핸들을 끝까지 드래그하면 해당 pane이 0px로 완전히 붕괴(제목까지 소실). 라벨링 탭 서브스플리터(`f086636`)도 동일 패턴이라 같은 위험 공유 | `QSplitter.setChildrenCollapsible(False)`를 호출하지 않아 Qt 기본값(`childrenCollapsible=True`)이 적용됨 — `setMinimumHeight/Width`는 창 리사이즈 제약일 뿐 수동 드래그 collapse는 막지 못함(Qt 기본 동작) | 리더가 직접 `setChildrenCollapsible(False)`를 5개 스플리터 전부(학습 `_queue_splitter`, 추론 `outer_splitter`+3분할 `splitter`, 라벨링 `_splitter`+`_left_splitter`+`_right_splitter`)에 추가, `py_compile` 확인 완료(커밋 `7a98760`). **재검증 완료(2026-08-20, verifier)** — `python main.py` 실제 GUI 드래그로 5개 스플리터 전부 양방향 극단 이동 확인: 학습 탭 `_queue_splitter`(큐박스 min 120px / 모니터패널 min 150px), 추론 탭 `outer_splitter`(상단 체크포인트영역 min 140px / 메인영역 min 200px)와 3분할 `splitter`(목록패널 min 140px / 범례패널 min 160px), 라벨링 탭 `_splitter`(좌패널 min 150px / 우패널 min 130px)·`_left_splitter`(이미지브라우저 min 80px / 클래스패널 min 80px)·`_right_splitter`(어노테이션목록 min 80px / 로그패널 min 80px) 전부 설정된 최소 크기에서 정확히 멈추고 0px 붕괴·제목 소실 없음. 각 탭에서 정상 범위 중간 드래그(자유 리사이즈)도 문제없이 동작 확인 — `setChildrenCollapsible(False)`가 일반 리사이즈를 막지 않음. |
| BUG-011 | GitHub #3(b) 검증 후속 | 브러시 계열 도구 활성 상태에서 캔버스 더블클릭으로 브러시 크기 다이얼로그(GitHub #3(b), 커밋 `29248fa`)를 열면, 더블클릭의 첫 클릭(press+release)이 `mouseDoubleClickEvent()`보다 먼저 처리되어 클릭 지점에 원치 않는 `[Mask]` 어노테이션이 추가됨(OK/Cancel 무관하게 남음, Undo로만 제거 가능) | `mouseDoubleClickEvent()`가 브러시 페인트 자체를 막는 로직이 없어 press→release 사이 커밋된 미세 스트로크가 그대로 남음 | 브러시/버킷/지우개/영역지우개 분기 진입 시 다이얼로그를 띄우기 전에 `self.undo()` 호출 — `mousePressEvent`가 브러시 페인트 시작 시 항상 `_push_undo()`를 먼저 호출하므로, undo 1회가 정확히 이번 클릭 시퀀스의 stray 스트로크만 되돌림(그 이전 정상 작업엔 영향 없음). 리더가 직접 1줄 수정, `py_compile` 확인 완료. **재검증 완료(2026-08-20, verifier)** — `QTest.mouseDClick()`으로 실제 Qt 더블클릭 이벤트 시퀀스를 재현(Cancel 1회 + OK 3회 반복), 매번 stray 어노테이션 0건·브러시 크기는 정상 반영됨을 확인. 회귀 확인: 일반 연속 페인팅은 여전히 정상 커밋, Ctrl+Z(undo) 단축키도 정상 동작. |
| BUG-015 | 디자인 7단계 ⑦ 검증 후속 | `training_tab.py` CUDA 배너(커밋 `8f78f8a`)의 좌측 색상 보더가 단일 선이 아니라 ~7px 간격을 두고 두 개의 막대("[[" 형태)로 이중 렌더링됨(성공/실패 두 상태 모두) | `banner.setStyleSheet("background:...; border-left:...")`처럼 선택자 없이 평문 속성만 나열하면 Qt가 `*{...}`와 동일하게 서브트리 전체에 전파 — 자식 `QLabel`이 `QFrame` 서브클래스라 `WA_StyledBackground` 없이도 스스로 같은 `border-left`를 그려, 부모 보더(x≈0)와 자식 보더(레이아웃 좌측마진만큼 밀린 x≈10)가 별개 막대로 겹쳐 보임 | `banner.setObjectName("cudaBanner")` 후 스타일시트를 `"QWidget#cudaBanner { ... }"` ID 선택자로 범위를 좁혀 자손 전파 차단(검증 에이전트가 제시한 해결책 (a) 채택) — 3곳(`_build_cuda_banner()` 초기 스타일 + `_on_cuda_diag_done()`의 성공/실패 두 분기) 전부 동일 패턴으로 수정, 리더가 직접 처리, `py_compile` 확인 완료. **재검증 완료(2026-08-21, verifier)** — 실제 `TrainingTab` 인스턴스를 띄워 `_on_cuda_diag_done()`을 성공/실패 두 상태로 직접 호출 후 `QWidget.grab()` 픽셀 스캔. 배너 상단/하단 부근(텍스트 baseline과 겹치지 않는 y=1,3,5,28,30)에서 x=0~2에만 단일 3px 보더(성공 `#10b981`/실패 `#f87171`)가 나타나고 x=3~19 전 구간이 배경색 `#1f2329`로 균일함을 확인 — 이전에 보였던 x≈10~12 두 번째 막대 완전히 사라짐. 배경/모서리 둥글기(`border-radius:4px`), 라벨 텍스트·"진단 보기" 버튼 geometry도 밀림·잘림 없이 정상. 실패(빨강) 상태는 실제 GPU 미가용 환경 없이 결과 객체를 직접 주입해 동일하게 확인(코드가 성공 분기와 완전 대칭 구조). |
| BUG-012 | GitHub #3/#4/#6-A/#7 라운드2 검증 후속 | 라벨링 탭에서 GitHub #7 "예" 경로(라벨 삭제 후 OK) 직후엔 사이드바 아이콘이 정확하지만, 다른 이미지 갔다 돌아오면 "미라벨"로 되돌아감(디스크 JSON·툴바 체크는 항상 정확, 표시 캐시만 stale) | `_on_toggle_ok()`의 flush 단계가 호출하는 옛 `_do_save()`(daemon 스레드로 비동기 `store.save()` 후 즉시 `annotation_saved` emit)와, 바로 뒤이은 `toggle_ok()`의 동기 `get_ok()`/`set_ok()` 읽기-수정-쓰기가 **같은 파일에 대한 순서 보장 없는 두 writer**로 경쟁 — 나중에 끝나는 쪽이 이기는 레이스라 `image_browser.refresh_item()`(디스크 재조회 자체는 정상 동작)이 레이스에서 앞선 emit 시점의 상태를 캐싱해버림 | `_do_save()`에 `sync: bool` 매개변수 추가 — `True`면 스레드 없이 동기로 즉시 저장. `_on_toggle_ok()`의 flush를 `_do_save(sync=True)`로 호출해 `toggle_ok()`가 같은 파일을 건드리기 전 쓰기 완료를 보장. 다른 `_do_save()` 호출부(500ms 디바운스, 이미지 전환 전 flush)는 경쟁하는 두 번째 writer가 없어 그대로 둠. 커밋 `5d551c3`. **재검증 완료(2026-08-20, verifier)** — 실제 어노테이션이 있는 이미지(`11번`)로 OK 확인창 "예" 흐름을 거친 뒤 다른 이미지로 갔다 돌아오기를 6회 반복, 매 라운드 사이드바 캐시=`ok`·디스크 JSON `ok:true`·`annotations:[]` 완전 일치(불일치 0건). 회귀 확인: 무라벨 이미지 OK 토글(확인창 없는 경로) on/off 정상, 이미지 전환 시 디바운스 저장 flush(미저장 브러시 스트로크 자동 저장)도 정상 동작. |
| BUG-013 | GitHub #3/#4/#6-A/#7 라운드2 검증 후속 | 브러시 크기 더블클릭 다이얼로그 문자열이 `t()` 체계 밖 한국어 하드코딩 — English 설정에서도 이 다이얼로그만 한국어로 표시됨 | 이번 라운드(GitHub #3(b))에서 신규 추가된 문자열이라 기존 i18n en 정비(193키) 범위 밖에 있었음 | `i18n.py`에 `tool.brush_size_dialog.title`/`.label` 키를 ko/en 양쪽에 추가, `annotation_canvas.py`에 `t` import 후 하드코딩 문자열을 `t()` 호출로 교체. 커밋 `5d551c3`. **재검증 완료(2026-08-20, verifier)** — `i18n.set_language("en")`에서 `t("tool.brush_size_dialog.title")`="Brush Size", `.label`="Brush size (1~200)" 확인. `ko`로 되돌리면 "브러시 크기"/"브러시 크기 (1~200)"로 정상 복귀. |

---

## VOC (Voice of Customer)

사용자가 직접 제기한 요청·불편 사항.

| 날짜 | 요청 내용 | 결정 | 근거 |
|------|-----------|------|------|
| 2026-08-20 | [GitHub #1](https://github.com/sfeelBot/Segmentation-Tool/issues/1) "사용성 정리" ① 라벨링/추론 이미지 탭에 폴더 정보(최하위 폴더명) 표시 요청 | 부분 수용 — 추론 탭은 라운드 2에서 트리형 폴더 그룹핑 신규 추가(실제 재귀 스캔, `inference_image_list.py`). **최종 정정(2026-08-21, BUG-005 처리 완료)**: "라벨링 탭은 기존부터 폴더 트리 있음"이라는 이전 응답은 오답이었음 — 라벨링 탭은 폴더 그룹핑을 지원하지 않음(단일 평탄 목록). 실제로 지원하려면 `app/core/dataset.py` 학습 스캔 로직까지 함께 바꿔야 하는 별도 기능 개발이라 이번엔 도달 불가능했던 죽은 코드만 제거함 — 필요 시 별도 기능 요청으로 재논의 | `docs/roadmap.md` "UI/UX 재편" 절, QA.md BUG-005(Closed) |
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
