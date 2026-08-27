# 기획 (Planning) 로그

역할 설명은 [README.md](README.md) 참고. append-only — 최신 항목이 아래에 추가된다.

---

## 2026-08-19 — 현재 상태 파악 및 워크플로우 세팅

### 확인한 프로젝트 상태
- 최신 릴리즈: `v1.6.0` (2026-05-16, docs/CHANGELOG.md) — 폴리곤 snap-to-close, RGB 채널 분리 뷰어, 픽셀 값 표시
- Phase 1~5(모델 로더/라벨링/학습/추론) 전부 완료 상태이며, 그 이후로도 성능 최적화·CUDA 진단·자동 라벨링·프로젝트 관리(`app/core/project.py`)·SAIGE 변환기 등 CLAUDE.md에 기술되지 않은 기능이 다수 추가되어 있음 (커밋 로그 기준). → `docs/roadmap.md` 신설로 정리(아래 항목 참고).
- `projects/nok/` — 실제 작업자가 사용 중인 라벨링 프로젝트. `annotations/11번.json`, `7번.json`의 uncommitted 변경은 새 코드 작업이 아니라 **정상적인 라벨링 작업물**(폴리곤 좌표 추가)이며, `classes.json` 신규 파일도 클래스 정의(0=background, 1=object)로 정상 산출물.
- `main.py` uncommitted 변경 1건: CSS 오타 발견 → [verification-log.md](verification-log.md) 참고.

### 다음 작업 후보 (사용자 확인 필요)
- 이번 세션에서 사용자로부터 구체적인 신규 기능 요청은 없었음. `main.py` 오타 수정 외에는 대기 중.
- 다음 작업 요청 시 이 파일에 범위/우선순위를 먼저 기록하고 구현으로 넘긴다.

---

## 2026-08-19 — CLAUDE.md의 "구현 단계" 표를 `docs/roadmap.md`로 이관

- CLAUDE.md 최상단에 있던 정적 Phase 1~5 표는 실제 프로젝트 상태(다수의 추가 기능)를 반영하지 못해 살아있는 문서인 [docs/roadmap.md](../roadmap.md)로 대체. CLAUDE.md에는 로드맵 문서 포인터만 남김.

---

## 2026-08-19 — 성능/버그 개선 계획 수립 (검증 결과 기반)

### 배경
검증 에이전트가 `projects/nok/` 실데이터로 전체 앱을 벤치마크해 8개 항목(버그 1 + 성능 7)을 발견 ([verification-log.md](verification-log.md) "전체 병목(Perf) 검증" 항목). 이번 기획은 이 8개 항목의 우선순위·범위·실행 순서를 정리하는 것.

### 한 일
- 스펙 문서 신설: [docs/specs/perf-improvement-plan-2026-08-19.md](../specs/perf-improvement-plan-2026-08-19.md) — 항목별 해결 방향/난이도/리스크/의존관계, 6개 라운드(R1~R6) 실행 순서.
- **BUG-002(brush_mask RLE 언더플로우, 데이터 유실)를 R1에 단독 최우선 배치**: 성능 항목과 축이 다른 심각도(되돌릴 수 없는 데이터 손실)이며, 원인이 `rle_encode()` 한 곳으로 좁혀져 다른 항목과 의존관계가 없고, R3(annotation_canvas 작업)에서 브러시 관련 검증을 하려면 먼저 고쳐져 있어야 함.
- R2(#2 임포트 지연로딩)는 `main.py` 주석에 명시된 과거 DLL 순서 이슈(BUG-001 계열) 재발 리스크가 있어 단독 라운드로 격리.
- R3(#4+#7), R6(#6+#8)은 같은 파일/같은 저리스크 성격끼리 묶어 검증 비용 절감. R4(#3), R5(#5)는 리스크·트레이드오프가 커서 단독 라운드 유지.
- #6, #8은 nok(5장)로는 실측 불가한 정적 분석 추정 — 구현 자체는 저비용/저리스크라 진행하되, R6 검증 시 더미 이미지 수백~수천 장 규모 합성 프로젝트로 재검증하도록 조건을 명시.
- `docs/roadmap.md`에 "성능/버그 개선" 절 추가(R1~R6 체크박스, 상태 "예정").
- `docs/decisions-needed.md`에 3건 등록: (1) #2 지연 임포트의 DLL 리스크 감수 여부, (2) #3 `num_workers` 새 기본값, (3) #5 추론 미리보기 다운스케일 상한.
- 코드는 건드리지 않음. `git status` 확인 완료(계획 관련 문서 3건만 변경, 기존 uncommitted 항목 그대로).

### 상태
완료 — 구현 단계로 넘길 준비됨. 다음: 리더가 사용자에게 `docs/decisions-needed.md` 3건 확인 후 R1(BUG-002)부터 구현 에이전트에 위임.

---

## 2026-08-20 — UI/UX 재편 스펙 수립 (학습·추론·라벨링 탭)

### 배경
사용자 요청: 3개 탭(학습/추론/라벨링) UI/UX를 "사용자 편의성" 관점에서 재편. 범위는 레이아웃 +
시각 스타일. 사용자가 짚은 구체 불편: "레이아웃별 움직일 수 없고 각종 정보들이 부족". Explore
에이전트가 사전에 코드 감사를 완료해둔 결과(각 탭 고정폭/고정높이 위젯 목록, 현재 표시 정보
목록, 스타일 불일치 지점)를 그대로 받아 기획.

### 한 일
- 스펙 문서 신설: [docs/specs/ui-redesign-plan-2026-08-19.md](../specs/ui-redesign-plan-2026-08-19.md)
  — 탭별(학습/추론/라벨링) 레이아웃 유연성·정보 추가·스타일 통일 항목을 표/목록으로 구체화하고
  실행 순서를 3라운드로 구성:
  - 라운드 1(저리스크, 목업 불필요): `setMaximumWidth`/`setFixedWidth` 등 숫자 제약 조정 +
    추론 탭 스플리터 hover 강조색 누락 보완.
  - 라운드 2(중리스크, 목업 필요): 라벨링 탭 좌/우 내부 서브패널, 학습 탭 큐 영역, 추론 탭
    상단 컨트롤 영역을 고정 stretch/고정높이에서 `QSplitter`로 재구조화.
  - 라운드 3(중~고리스크, 목업 필요): 정보 추가 — 추론 탭 신뢰도(confidence) 표시(최우선,
    `inference_engine.py`에 confidence 계산이 아예 없었던 명백한 갭), 처리시간/해상도 정보,
    학습 탭 현재 LR·체크포인트 리스트 보강, 라벨링 탭 줌 배율·이미지 크기 표시
    (`annotation_canvas.py`에 zoom 시그널 신규 추가 필요 — 1638줄 파일이라 diff를 시그널
    추가로만 한정하도록 명시).
- 기존 표시 정보와 대조해 이미 있는 것(학습 탭 "전체 예상 시간")은 중복 제안하지 않음 확인.
- `docs/decisions-needed.md`에 3건 등록: (1) 리사이즈 상한 구체 수치, (2) 추론 탭 신뢰도 표시
  범위(통계만 vs 히트맵까지), (3) 라벨링 탭 `ClassPanel` 내부 200px 상한 완화(범위 확장) 여부.
- `docs/roadmap.md` "UI/UX 재편" 절 갱신 — 기획 완료 체크, 라운드 1~3 체크박스 추가.
- 코드는 건드리지 않음. 시작 전/후 `git status`로 확인 — 세션 시작 시점에 이미 있던
  `app/core/dataset.py`, `app/core/trainer.py`, `app/widgets/config_form.py`,
  `docs/agents/leader-log.md`의 uncommitted 변경은 이 작업과 무관(건드리지 않음).

### 상태
완료 — 디자인/구현 단계로 넘길 준비됨. 다음: 리더가 사용자에게 `docs/decisions-needed.md`
3건 확인 후 라운드 1은 바로 구현 에이전트에, 라운드 2~3은 디자인 에이전트의 목업 확인을
거쳐 구현으로 진행.

---

## 2026-08-20 — 추가 요구사항 반영: 추론 탭 이미지 목록 검색/정렬 기능

### 배경
사용자가 위 UI/UX 재편 스펙을 확인하기 전에 추가 요구사항을 줬다: "이미지 로드하고 그랬을 때
정보량이 부족해. 폴더 sort 기능, 검색기능도 포함해줘." 확인 결과 이는 **추론 탭의 이미지
목록**(`inference_tab.py` `_img_list`, 순수 `QListWidget` IconMode)을 가리키는 것으로
판단 — 라벨링 탭 `ImageBrowser`는 검색(디바운스)+정렬 4종+폴더 그룹핑을 이미 갖췄지만
추론 탭엔 이 기능이 전혀 없다는 갭이 기존 스펙 초안(레이아웃 "폭 제약"만 다룸)에서 누락돼
있었다.

### 한 일
- `app/widgets/image_browser.py` 재확인 후 **재사용 여부를 판단**: `ImageBrowser.reload()`가
  `_project.images_dir()`를 하드코딩하는데 추론 탭은 프로젝트 밖 임의 경로를 다루는 게
  기본 워크플로우라 전제가 다름. 상단 버튼(추가/폴더추가/삭제)이 파일을 복사·삭제하는
  편집 액션이라 추론 입력 브라우징과 안 맞음. 라벨 상태 아이콘(완료/OK/미라벨)도 추론
  컨텍스트에서 의미가 약함. `ImageBrowser`는 라벨링 탭이 활발히 쓰는 공유 위젯이라 이만큼
  뜯어고치면 라벨링 탭에 회귀 리스크가 전이됨 → **재사용 기각**, 추론 탭 전용 경량 컴포넌트로
  검색(디바운스 패턴 재사용)+정렬(파일명↑↓/폴더 3종, 라벨상태 정렬은 제외)을 새로 구현하는
  쪽으로 판단.
- 폴더 그룹핑은 트리형 접기/펼치기로 만들면 현재 썸네일 아이콘 그리드 뷰를 포기해야 하는
  트레이드오프가 있어, 1차로는 "폴더" **정렬 옵션**까지만 제안하고 트리형 필요 여부는
  사용자 확인으로 넘김.
- 이 항목을 라운드 2(레이아웃 재구조화)에 배치 — 순수 상수 조정이 아니라 검색바+정렬콤보라는
  새 서브레이아웃이 추가되는 구조 변경이라 라운드 1(저리스크)이 아니라고 판단. 다만 공유
  위젯을 건드리지 않는 격리된 신규 컴포넌트라 같은 라운드의 다른 재구조화 항목보다는 회귀
  리스크가 낮다고 명시.
- 산출물 갱신: [docs/specs/ui-redesign-plan-2026-08-19.md](../specs/ui-redesign-plan-2026-08-19.md)
  (추론 탭 절에 "이미지 목록 검색/정렬/폴더 기능 부재" 서브섹션 신설 + 라운드2 항목4 +
  디자인 확인 지점 추가), [docs/decisions-needed.md](../decisions-needed.md)(4번 항목 추가:
  폴더 그룹핑 방식), [docs/roadmap.md](../roadmap.md)(UI/UX 재편 절에 2026-08-20 추가 요청
  반영 사실 기록).
- 코드는 건드리지 않음 — 이번 세션에서 Write/Edit는 문서 4건(스펙/decisions-needed/roadmap/
  본 로그)에만 사용.

### 상태
완료. 다음: 리더가 사용자에게 `docs/decisions-needed.md` 4건(레이아웃 상한 수치, 추론 탭
신뢰도 표시 범위, ClassPanel 200px 상한, 추론 탭 폴더 그룹핑 방식) 확인 후 라운드 1부터 진행.

---

## 2026-08-20 — GitHub #2 "프로젝트 내보내기 기능" VOC 2건 스코프 산정

### 배경
GitHub 이슈 [#2](https://github.com/sfeelBot/Segmentation-Tool/issues/2)에서 접수된 VOC 2건
(`QA.md` VOC 테이블 2026-08-20)의 스코프 산정 위임: ① 최근 프로젝트 클릭 시 자동 열기, ②
프로젝트 전체 내보내기/단일 파일 통합.

### 한 일
- `app/widgets/project_start_dialog.py` 전체 흐름 확인: 최근 프로젝트 목록은 이미 더블클릭
  (`itemDoubleClicked` → `_on_recent_double_clicked` → `_try_open()`)으로 한 번에 열림 —
  중간에 별도 "열기" 버튼을 또 눌러야 하는 번거로운 흐름은 없음(가설 b 기각). 싱글클릭을
  원하는지(가설 a) 단순히 몰랐는지(가설 c)는 GitHub 이슈 원문("클릭하면 자동으로 열리게")
  만으로 판별 불가 — 한국어에서 "클릭"과 "더블클릭"이 혼용되는 경우가 많아 판단을 내리지
  않고 `docs/decisions-needed.md`에 등록.
- `app/core/project.py`(`Project` 경로 구조: images/annotations/checkpoints/user_models/
  classes.json/project.json)와 `app/widgets/export_dialog.py`(기존 export는 라벨 데이터만
  JSON/YOLO/COCO로 변환, 프로젝트 패키징 아님) 확인. 추가로 `trainer.py`/`inference_engine.py`를
  교차 확인해 체크포인트의 `model_source`가 실제 소스 코드가 아니라 태그 문자열이라는 점,
  `"loaded"`(커스텀 모델)는 자동 재인스턴스화가 안 되고 사용자가 모델 탭에서 다시 로드해야
  한다는 기존 갭을 확인 — 이는 `user_models/` 포함 여부 판단(포함해도 체크포인트와 자동
  연결은 안 됨, 그래도 코드 자산 자체는 보존 가치 있음)에 반영.
- `.gitignore`가 `projects/*/checkpoints/`, `*.pt`, `*.pth`를 이미 제외 대상으로 두고 있는
  점을 "체크포인트는 무겁고 재생성 가능한 산출물" 취급 관례의 근거로 삼아 기본 미체크 제안.
  `app/widgets/image_browser.py`의 `_FolderImportWorker(QThread)` 패턴을 확인해 zip 압축도
  같은 관례(백그라운드 워커 + 진행률 시그널)로 구현 가능함을 확인 — 스파이크 불필요(신규
  라이브러리 선택이 아니라 기존 관례 재사용, `zipfile` 표준 라이브러리로 충분).
- 스펙 문서 신설: [docs/specs/voc-github-issues-2026-08-20.md](../specs/voc-github-issues-2026-08-20.md)
  — 요청 1은 판단 보류 + 재확인 경로 제시, 요청 2는 라운드 A(export, zip, 체크박스 기본값 제안)
  + 라운드 B(import, 라운드 A 완료 후 착수 — zip 구조 확정이 선행돼야 함) 2라운드로 스코프
  산정, 라운드 B의 리스크(경로 충돌·zip 검증·버전 호환성)를 라운드 A보다 명시적으로 높게 평가.
- `docs/decisions-needed.md`에 3건 등록: (1) 요청1 싱글클릭 vs 더블클릭 재확인, (2) 라운드 A
  `checkpoints/`·`user_models/` 기본 포함 여부, (3) 라운드 B(import) 착수 여부 + 이름 충돌 정책.
- `docs/roadmap.md` "GitHub 이슈 VOC" 절 갱신 — 스펙 링크 반영, 요청1/2 각각 다음 단계 명시.
- 코드는 건드리지 않음. 시작 전 `git status` 확인 — `app/core/dataset.py`, `app/core/trainer.py`,
  `app/widgets/config_form.py`, `docs/agents/leader-log.md`의 기존 uncommitted 변경은 이번
  작업과 무관(건드리지 않음). 작업 종료 시 `git status`로 스펙/decisions-needed/roadmap/본 로그
  4개 문서 변경만 추가됐음을 확인.

### 상태
완료 — 다음: 리더가 사용자에게 decisions-needed 3건 확인. 요청1은 GitHub 이슈 재확인 코멘트
후 답변에 따라 초경량 수정 또는 안내로 종료(별도 라운드 불필요). 요청2는 답변 확인 후 라운드
A(export)부터 디자인 목업 → 구현 → 검증(주요 기능 추가라 골든패스 수준 검증 요청) 순으로 진행,
라운드 B(import)는 라운드 A 완료 후 착수 여부 재확인.

---

## 2026-08-20 — GitHub 이슈 #3~#7 스코프 산정 (라운드2)

### 배경
GitHub에 2026-08-20 새로 등록된 이슈 4건(#3 브러시 도구, #4 이미지명 복사, #5 모델 탭 변경,
#6 annotation 로딩/깜빡임)의 스코프 산정 위임. 작업 도중 리더가 2건을 추가로 전달: (1) #7
"OK 이미지 기능"(라벨 있는 이미지 OK 처리 시 확인 팝업 요청), (2) 사용자가 GitHub #6 이슈
원문("깜빡임")보다 구체적으로 보고한 별도 불편 — "annotation이 많아지니까 추가하거나 화면이
바뀔 때 로딩 속도가 매우 느려져. 최적화 반드시 필요"(#6-B로 명명해 같은 절에서 함께 정리).

### 한 일
- 이슈 5건(#3~#7) 전부 코드 기준으로 실제 원인/현황을 먼저 검증한 뒤 스펙에 반영 —
  가정으로 스코프를 잡지 않음.
- **#3(브러시 크기)**: 조절 수단은 QSpinBox(툴바)+키보드 단축키(`[`/`]`/`-`/`+`) 둘뿐,
  더블클릭·우클릭은 미구현 확인. **우클릭은 이미 전역 패닝(`mousePressEvent` 581행)에
  배정돼 있어 사용자 요청과 정면 충돌** — 사용자 확인 필요 항목으로 등록. 더블클릭은
  브러시 도구에서 미사용이라 충돌 없음(단, 정확한 동작은 미정, 마찬가지로 확인 필요). 잘림
  버그는 `setFixedWidth(60)` + 전역 QSpinBox padding(main.py)으로 원인 특정 — 저리스크
  즉시 수정 가능.
- **#4(이미지명 복사)**: `settings_dialog.py`에 이미 있는 클립보드 복사 버튼 패턴
  (`svg_icon("clipboard")` + `QApplication.clipboard().setText()`)을 그대로 재사용 가능
  확인. 추론 탭은 기존 `_lbl_filename` 라벨 옆에 곁들이면 되지만, 라벨링 탭은 파일명을
  상시 표시하는 UI 자체가 없어 채널 스트립에 신규 추가 필요. patch training 질문은
  `config_form.py`(학습 기본 샘플링 = random_crop 확인) + `auto_labeler.py`
  (`_infer_to_annotations`가 패치/타일 추론 없이 전체 이미지 리사이즈 단일 추론) 교차
  확인으로 "아니오, 오토라벨은 patch 방식이 아니다"는 사실관계를 답변 완료 — 구현 불필요.
- **#5(모델 탭 구조변경)**: `win._model_tab.loaded_model`을 training_tab·labeling_tab·
  inference_tab **3곳이 교차 참조**하는 것을 grep으로 확인 — 구조 변경 시 MainWindow가
  `ModelTab` 인스턴스를 계속 들고 있어야(표시 컨테이너만 QDialog로 교체) 이 3곳이 깨지지
  않는다는 제약을 스펙에 명시. 탭 기반 UI 패러다임을 부분적으로 깨는 결정이라 **즉시 결정하지
  않고 사용자 확인 항목으로 분류**(요청대로).
- **#6(annotation 로딩/깜빡임)** — 원래 #3~#6 조사 중 원인을 `_invalidate_overlay()`
  (`annotation_canvas.py`)로 특정: `self._overlay = None`을 동기로 즉시 실행한 뒤
  재생성은 `_OverlayWorker`(QThread)로 비동기 처리해, 그 사이 paintEvent가 오버레이 없이
  그려지는 타이밍 버그(flicker, #6-A) 확인. 이미지 전환(`load_image()`)에서도 같은 함수가
  호출됨을 확인해 "채널전환+라벨링" 복합 상황이 실제로는 단일 원인임을 정리.
  - 리더가 작업 도중 전달한 추가 불편(#6-B, "개수 늘수록 느려짐")을 조사한 결과, **서로
    다른 두 곳의 O(n) 전체 재구축 패턴**을 확인: (1) `labeling_tab.py`
    `_refresh_ann_list()` — 매 편집·이미지전환마다 어노테이션 목록 `QListWidget`을
    `clear()` 후 전체 재생성(메인 스레드 동기), (2) `annotation_canvas.py`
    `_rebuild_overlay()`/`_OverlayWorker` — 매 편집·전환마다 오버레이 픽스맵을 어노테이션
    전체에 대해 처음부터 다시 그림(백그라운드 스레드지만 개수에 비례해 시간 증가). 부수로
    `_resolve_overlap_and_merge()`도 브러시 스트로크마다 `self._annotations` 전체를
    2~3회 순회하는 O(n) 구조 확인(2차 기여 요인). 두 개 모두 R1~R6 성능개선이 다룬 경로와는
    무관 — R3(이미지 디코딩 캐시)가 만든 회귀 아님.
  - #6-B는 사용자가 "반드시 필요"로 명시했고 원인도 확정됐으나 수정 난이도가 flicker(#6-A)
    보다 높아(오버레이 컴포지팅 구조 손질 가능성) 별도 라운드 권장, R6 관례대로 대규모 합성
    프로젝트 벤치마크 조건 명시.
- **#7(OK 확인 팝업)**: 리더가 위임한 "사용자 주장이 실제 코드와 일치하는지" 먼저 검증 —
  `toggle_ok()`/`set_ok()`가 `ok` 플래그만 다루고 `annotations` 배열은 건드리지 않아
  **데이터 유실은 없지만 확인 절차 자체가 없다**는 사실 확인. `_on_clear_all()`(같은 파일)이
  이미 동일한 QMessageBox 확인→실행 패턴을 쓰고 있어 신규 설계 없이 그대로 복제 가능 —
  난이도 하로 판정.
- 스펙 문서 신설: [docs/specs/voc-github-issues-round2-2026-08-20.md](../specs/voc-github-issues-round2-2026-08-20.md)
  — #3~#7 전부 코드 근거 + 제안 스코프 + 실행 순서(난이도·파일 겹침 기준 8단계) 포함.
- `docs/decisions-needed.md`에 2건 등록(#5 구조변경 진행 여부, #3 인터랙션 방식) — 나머지
  (#6-A/#6-B/#7/#4/#3-a)는 방향이 명확해 결정 없이 바로 구현 가능하다고 명시.
- `docs/roadmap.md`에 "GitHub 이슈 VOC 라운드2" 절 신설. 작업 도중 다른 프로세스가
  "디자인 톤 홀리스틱 재검토" 5단계를 검증대기→검증완료(조건부 통과, BUG-008/009/010 발견)로
  갱신한 것을 확인해 스펙 문서의 관련 서술(파일 겹침 주의)도 최신 상태로 맞춰 반영.
- 코드는 건드리지 않음 — Write/Edit는 스펙 신설 1건, `decisions-needed.md`/`roadmap.md`/
  본 로그 갱신에만 사용.

### 상태
완료 — 다음: 리더가 사용자에게 decisions-needed 2건(#5 구조변경 여부, #3 인터랙션 방식)
확인. 나머지 5개 항목(#6-B 최우선, #6-A, #7, #4, #3-a)은 결정 없이 바로 구현 에이전트에
위임 가능. #6-B는 난이도가 높아 별도 라운드로 분리 권장.

---

## 2026-08-25 — GitHub 이슈 #8·#9 스코프 산정 (라운드3)

### 배경
사용자가 GitHub 이슈 2건을 순서대로(#9 먼저, #8 다음) 처리해달라고 요청. #9는 라벨링
캔버스 줌 초점 버그, #8은 이미지 브라우저 다중선택+삭제 신규 기능 요청.

### 한 일
- **#9(버그)**: `app/widgets/annotation_canvas.py` 전체 조사. 줌 진입점이 앱 전체에서
  `wheelEvent()`(마우스 휠) 하나뿐임을 `labeling_tab.py` grep(0건 매치)으로 확인 — 드래그
  자체로 줌하는 별도 메커니즘은 존재하지 않음. `wheelEvent()`의 커서 앵커링 수식 자체는
  검산 결과 수학적으로 정확(정지 상태 휠 줌은 정상). 원인을 `_pan_active`(좌클릭 패닝
  드래그) 상태와 `wheelEvent()`의 상호작용으로 좁힘: `mousePressEvent()`가 드래그 시작
  시점에 `_pan_start_mouse`/`_pan_start_offset`을 1회만 캡처해두고 `mouseMoveEvent()`는
  매번 이 값 기준 절대 재계산을 하는데, 드래그 도중 휠이 `_zoom`/`_pan`을 갱신해도 이
  캡처값을 갱신하지 않아 다음 마우스 이동이 휠의 커서-고정 pan을 옛 값으로 덮어씀 —
  "왼쪽 클릭(드래그) 형태에서 줌인/줌아웃할 때 초점이 안 맞는다"는 원문과 정확히 일치하는
  코드 레벨 근거. Select 도구 드래그·브러시 스트로크는 이미지 좌표를 매 이벤트 재계산해
  이 결함의 영향을 받지 않음(패닝 드래그만 해당). 재현조건이 100% 확정은 아니라 사용자
  확인용 질문 3건을 스펙에 남겼으나, 근거가 충분히 강해 구현을 막을 필요는 없다고 판단—
  결정 대기 등록은 하지 않음.
- **#8(신규기능)**: `app/widgets/image_browser.py` 전수 조사 결과 **요청 3가지(다중선택/
  다중선택 후 삭제/삭제 기능)가 이미 전부 구현되어 있음**을 확인 — `_tree`가 이미
  `ExtendedSelection`(Ctrl/Shift 다중선택), `_on_delete()`가 이미 `selectedItems()` 전체를
  순회해 이미지+대응 `annotations/{stem}.json` 함께 삭제 + 확인 다이얼로그(단건/다건 요약
  문구 분기)까지 갖춤. 사용자가 위임 메시지에서 짚은 "과거 `unhashable QTreeWidgetItem`
  버그"는 `data/logs/errors.log`에서 2026-05-27자 크래시로 실물 확인했으나, 원인
  패턴(`self._item_to_path[item] = p` — QTreeWidgetItem을 dict 키로 사용)이 현재 코드
  구조(Path가 dict 키, 아이템→Path는 `item.data(0, _PATH_ROLE)` UserRole 역조회)에서
  완전히 사라져 재현 불가로 판단. `verification-log.md` 2026-08-20 항목이 "QA.md에서 별도
  추적 중"이라 서술했지만 실제 QA.md Open/Closed 어디에도 등록이 없어 문서 정합성 갭임을
  확인(코드 결함 자체는 해소된 것으로 보여 이번 라운드에서 별도 조치하지 않음). 스코프를
  "검증 우선"으로 결정 — 코드가 이미 있는데 재구현하지 않고, 실제 GUI 동작을 먼저 확인한
  뒤 문제 발견 시에만 최소 보강. 저비용 선택 갭 1건(키보드 `Delete` 단축키 없음, 버튼
  클릭만 가능)만 기록.
- 스펙 문서 신설: [docs/specs/voc-github-issues-round3-2026-08-25.md](../specs/voc-github-issues-round3-2026-08-25.md)
  — #9/#8 각각 문제정의·코드 근거·구현 대상 파일·검증 골든패스 정리.
- `docs/roadmap.md`에 "GitHub 이슈 VOC 라운드3" 절 신설(#9/#8 체크박스, 순서 명시).
- `docs/decisions-needed.md`는 갱신하지 않음 — 이번 2건 모두 결정 없이 바로 다음 단계
  (구현/검증) 진행 가능하다고 판단.
- 코드는 건드리지 않음. Write/Edit는 스펙 신설 1건, `roadmap.md`, 본 로그 갱신에만 사용.

### 상태
완료 — 다음: 리더가 순서대로 #9 먼저(구현 에이전트에 `annotation_canvas.py`
`wheelEvent()`/`mouseMoveEvent()` 패닝 분기 최소 수정 위임 → 검증), #8은 구현보다
**검증 에이전트를 먼저** 투입해 기존 다중선택+삭제 동작을 실제 GUI로 확인한 뒤 문제가
없으면 이슈를 바로 닫고, 문제가 있으면 최소 보강을 구현 에이전트에 위임.

---

## 2026-08-27 — GitHub 이슈 #12·#15·#16·#17 스코프 산정 (라운드4)

### 배경
메인 세션 담당 GitHub 이슈 4건(`feature/zone-analysis-tab` 관련 2건은 별도 세션 처리
중이라 범위 밖). #17 이미지 목록 Ctrl+C 복사, #16 내보내기 PermissionError(실사용자
크래시 로그 첨부), #15 브러시 채우기 시 기존 라벨 경계 고려, #12 "브러시는 도구일
뿐 분류 불필요"(원문 매우 짧음). 각각 범위/우선순위/영향 파일을 코드 조사 기반으로
정리.

### 한 일
- **#17**: `image_browser.py` 확인 — `_tree`(QTreeWidget)는 이미 `ExtendedSelection`
  (GitHub #8에서 확인된 그대로)이지만 `keyPressEvent`/`eventFilter` 등 키보드 단축키
  핸들러가 전혀 없음을 재확인. `installEventFilter` 방식(서브클래싱 불필요)으로 최소
  침습 구현 제안. "파일명들"은 확장자 포함으로 결정 — `_on_delete()` 확인 다이얼로그가
  이미 `p.name`(확장자 포함)으로 미리보기하는 기존 관례와 통일, 별도 사용자 확인
  불필요한 사소한 선택으로 판단.
- **#16**: 첨부된 크래시 로그가 `self._pairs`(오늘 커밋 `7dabdb5`로 이미
  `self._image_paths`로 리팩터링된 구버전 변수명)를 참조함을 확인 — MemoryError
  건과는 무관한 별개 버그(PermissionError)임을 먼저 분리. `shutil.copy2` 호출부
  (`export_dialog.py` json/yolo/coco 3곳)는 현재 HEAD에도 retry 없이 단발 호출로 남아
  있어 취약점 자체는 여전히 유효함을 확인. 원인 조사: `_image_size()`는 이미
  `with Image.open() as im`으로 안전, `dataset.py`의 학습 캐시(`_load_cached`)는
  `Image.open().convert("RGB")`가 PIL 내부적으로 `_exclusive_fp=True`일 때 `load()`
  직후 OS 핸들을 즉시 닫는다는 PIL 동작 원리를 근거로 원인에서 제외. 유일하게 발견한
  비-`with` 패턴은 `auto_labeler.py:70`(`.width`/`.height`만 접근, `.convert()` 미호출
  → 다음 루프까지 핸들이 열려있을 수 있음)이나, Windows 기본 파일 공유 모드가
  deny-none이라 자기 프로세스 핸들이 자기 자신의 copy를 막을 개연성은 낮다고 판단 —
  **1순위 원인은 외부 프로세스(백신/탐색기 미리보기/OneDrive 등 클라우드 동기화)**로
  결론, Windows 에러 메시지 자체("다른 프로세스가 파일을 사용 중")가 이를 직접
  뒷받침. 로컬 재현은 실패(OS 레벨 파일 잠금을 인위적으로 만들 방법 없음) — 정적
  분석 기반 결론임을 명시. 제안: `export_dialog.py`에 retry+backoff 헬퍼(주 수정,
  원인이 외부든 내부든 항상 유효한 방어책) + `auto_labeler.py` `with` 보강(보조,
  위생 차원, 근본원인일 개연성은 낮음). 사용자 재현조건 확인용 질문 4건을 스펙에
  남김(동기화 폴더 여부, 동시 실행 작업 여부 등) — 결정 대기 등록은 아님(구현 진행
  막을 필요 없다고 판단, GitHub #9 라운드3 관례와 동일).
- **#15**: `_fill_enclosed()`(`annotation_canvas.py`)가 오늘 커밋 `e02cf95`(시작·끝점
  강제 연결 제거) 이후에도 여전히 이번 궤적(`self._brush_np`)만으로 flood-fill함을
  확인. 핵심 발견 — **병합 자체는 이미 있다**: `_consolidate_class_region()`이 커밋
  직후 같은 클래스의 인접/겹치는 brush_mask들을 connectedComponents로 자동 병합하므로,
  이번 이슈에 필요한 신규 작업은 "벽 확장"뿐(새 병합 로직 불필요). 설계: 기존 어노테이션
  마스크를 flood-fill 입력에 OR로 추가하되, **커밋되는 새 마스크는 (이번 궤적) ∪
  (flood-fill로 새로 드러난 빈 공간)만** 남기고 기존 어노테이션이 차지하던 픽셀은
  제외 — task brief가 우려한 "기존 어노테이션이 새 annotation_id로 흡수되는 회귀"를
  원천 차단하는 설계. 성능은 `_resolve_overlap_and_merge`/`_consolidate_class_region`
  기존 bbox 스코프 패턴을 재사용해 후보 축소(bbox-vs-bbox) + 작업 캔버스를 로컬
  사각형으로 축소하는 방안 제시, 로컬 사각형 네 모서리가 전부 벽이 되는 위험(패딩
  부족 시 오탐)까지 식별해 패딩 확장 재시도 → 최종 실패 시 전체이미지 폴백을 안전장치로
  제안. **결정 대기 2건 등록**(벽 범위: 같은 클래스만 vs 모든 클래스 — 답에 따라
  구현 로직 자체가 달라짐, 패딩 마진 기본값 — 임의로 정하면 이슈가 원하는 "이어 그리기"
  거리감을 못 맞출 위험) — 구현 착수 보류 권장.
- **#12**: 원문이 매우 짧아("브러쉬는 그리는 도구일뿐 이걸 annotation에서 분류할 필요는
  없어") 3가지 가설을 코드로 검증. (a) `class_panel.py` — 클래스 목록만 다루고
  어노테이션 타입 노출 없음, 기각. (b) `labeling_tab.py` `_refresh_ann_list()`가
  `type_label = "Poly" if ann.type == "polygon" else "Mask"`로 목록 항목 텍스트에
  타입 태그를 직접 노출함을 확인 — **가장 유력한 원인**. (c)
  `_resolve_overlap_and_merge()`/`_consolidate_class_region()`이 brush_mask끼리만
  병합하고 폴리곤은 병합 대상에서 제외됨을 확인(같은 클래스라도 그리기 도구가 다르면
  항상 별개 항목) — (b)의 인상을 강화하는 배경 요인이지만 자료구조 제약상(벡터 vs
  래스터) 단독으로 없애기 어려움. 옵션A(저비용, `[Poly]`/`[Mask]` 태그만 제거) /
  옵션B(고비용, 타입 무관 자동 병합·좌표 정밀도 손실 리스크) 2안 제시. **결정 대기
  1건 등록**(원문이 정말 이 화면을 가리키는지 스크린샷으로 재확인 + 옵션A/B 선택) —
  원문만으로는 재현 조건이 100% 확정 아니라 구현 착수 보류 권장.
- 스펙 문서 신설:
  [docs/specs/voc-github-issues-round4-2026-08-27.md](../specs/voc-github-issues-round4-2026-08-27.md)
  — 4건 각각 문제정의·코드근거·설계안·결정필요사항·구현대상파일·검증골든패스 정리,
  실행순서(#16→#15→#12→#17, 파일 겹침 없어 병렬 가능) 명시.
- `docs/decisions-needed.md`에 2건 등록(#15 벽범위+패딩마진, #12 화면확인+옵션선택).
  #16·#17은 결정 없이 바로 구현 가능하다고 명시.
- `docs/roadmap.md`에 "GitHub 이슈 VOC 라운드4" 절 신설(4개 항목 체크박스, 처리순서
  명시).
- 코드는 건드리지 않음 — Write/Edit는 스펙 신설 1건, `decisions-needed.md`/
  `roadmap.md`/본 로그 갱신에만 사용. 시작 전 `git status` 확인(clean).

### 상태
완료 — 다음: 리더가 사용자에게 decisions-needed 2건(#15, #12) 확인. #16·#17은 결정
없이 바로 구현 에이전트에 위임 가능(#16 우선, #17은 언제든 병렬).
