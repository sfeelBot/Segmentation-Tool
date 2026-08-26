# Roadmap — Segmentation Model UI

살아있는 문서. 리더가 상태 변경 시마다 직접 갱신한다(체크박스 토글, 완료 항목 정리) —
append-only가 아니라 최신 상태로 덮어쓴다. 상세 이력은 [docs/CHANGELOG.md](CHANGELOG.md),
[docs/agents/*-log.md](agents/), [QA.md](../QA.md) 참고.

> 2026-08-19 스냅샷: git 커밋 로그·디렉토리 구조 기반 추정이며, 각 항목이 실제로 정상
> 동작하는지는 검증 로그로 확인된 것이 아니다. 필요 시 검증 에이전트가 실행 확인 후 갱신할 것.

## 모델 탭 (`app/tabs/model_tab.py`)
- [x] AST 기반 코드 검증 + 제한적 exec 로딩
- [x] 모델 프리셋 7종(`app/model_presets/`: simple_unet, unet_plusplus, attention_unet, deeplab_resnet, deeplab_mobilenet, fpn_segnet, lraspp_mobilenet) + 선택 팝업(`model_preset_dialog.py`)

## 라벨링 탭 (`app/tabs/labeling_tab.py`)
- [x] 폴리곤 / 브러시 / 지우개 캔버스 (`annotation_canvas.py`)
- [x] 폴리곤 Snap-to-Close (v1.6.0)
- [x] RGB 채널 분리 뷰어 + 픽셀 값 표시 (v1.6.0)
- [x] 자동 라벨링 (`auto_labeler.py`, `auto_label_dialog.py`, `auto_label_preview_dialog.py`)
- [x] 이미지 브라우저 검색/정렬 + 리사이즈 가능 패널(QSplitter)
- [ ] 폴더 그룹핑 — 미지원(단일 평탄 목록). 과거 `[x]` 표시는 오기였음: `_build_folder_tree`
      코드는 있었지만 `reload()`가 비재귀 스캔만 하고 이미지 추가 경로도 전부 평탄 복사라
      실제로는 어떤 사용자 동작으로도 도달 불가능했음(BUG-005, `QA.md` Closed). 2026-08-21
      죽은 코드 제거 완료 — 필요 시 별도 기능 요청으로 재논의
- [x] 다국어(i18n) 지원 (`app/core/i18n.py`)

## 학습 탭 (`app/tabs/training_tab.py`)
- [x] QThread 학습 루프 + 실시간 손실 그래프
- [x] LR 스케줄러 9종
- [x] CUDA 종합 진단 팝업 (`cuda_diag.py`, `cuda_diag_dialog.py`) — 논블로킹

## 추론 탭 (`app/tabs/inference_tab.py`)
- [x] 체크포인트 선택 → 학습 당시 모델 자동 인스턴스화
- [x] 오버레이 뷰어

## 프로젝트 관리 (`app/core/project.py`, `project_start_dialog.py`)
- [x] 프로젝트 단위 images/annotations/checkpoints/user_models 분리 (`projects/<name>/`)
- [x] 내보내기 (`export_dialog.py`)
- [ ] `saige_converter.py` — 용도 미문서화, 확인 필요 (기획/검증 후 이 항목 갱신)

## 성능/버그 개선 (2026-08-19 검증 결과 기반)

검증 에이전트가 `projects/nok/` 실데이터로 전체 앱을 벤치마크해 발견한 8개 항목(버그 1 + 성능 7).
상세 계획: [docs/specs/perf-improvement-plan-2026-08-19.md](specs/perf-improvement-plan-2026-08-19.md).
원본 벤치마크: [docs/agents/verification-log.md](agents/verification-log.md).

- [x] R1 — BUG-002: `annotation_store.rle_encode()` uint8 언더플로우로 brush_mask 전량 유실 (P0) — 구현+독립검증 통과, 커밋 `3ce4dc9`
- [x] R2 — #2: `main.py` 콜드 임포트 지연로딩 (기동 ~3.3초→~1.85초, P1) — 구현+독립검증 통과, 커밋 `eee9b9c`
- [x] R3 — #4 + #7: `annotation_canvas.py` 이미지 캐시(~10~15배) + bbox fallback 스캔 축소(~5배) (P2/P3) — 구현+독립검증 통과, 커밋 `194430b`. 부수 발견: BUG-003(P3, Open)
- [x] R4 — #3: 학습 데이터로더 캐시 + `num_workers` 자동 감지(상한 2) + persistent_workers (P1) — 구현+독립검증 통과, 커밋 `5ed34e9`
- [x] R5 — #5: `inference_engine._colorize_and_blend()` 다운스케일(992ms→194ms, 화면 미리보기만·저장은 원본 유지) (P2) — 구현+독립검증 통과, 커밋 `20bb3d0`
- [x] R6 — #6 + #8: `image_browser` 검색 디바운스+상태캐시 + `auto_labeler` 중복 read 제거(~30~46% 단축, 대규모 합성 프로젝트로 재검증 완료) (P2/P3) — 구현+독립검증 통과, 커밋 `e7066b0`. 부수 발견: BUG-004(P3, Open)

**R1~R6 전체 완료** (2026-08-19). 남은 Open 이슈는 [QA.md](../QA.md)의 BUG-003·BUG-004(둘 다 P3, 정상 사용 흐름에서는 발현되지 않는 경미한 항목) — 별도 라운드 불필요, 후속 작업 시 참고.

## UI/UX 재편 — 학습·추론·라벨링 탭 (2026-08-19 요청, 성능 개선 완료 후 착수)

- 범위: 레이아웃 + 시각 스타일 모두. 대상: `training_tab.py`, `inference_tab.py`,
  `labeling_tab.py`(+ `annotation_canvas.py`, `config_form.py`, `overlay_viewer.py`,
  `class_panel.py`, `inference_engine.py`, `trainer.py` 등 관련 위젯/core).
- 사용자가 짚은 구체적 불편: **"레이아웃별 움직일 수 없고 각종 정보들이 부족"**.
- **성능 개선(R3~R6)과 대상 파일이 겹쳐 순서를 성능 먼저로 결정** — R3~R6 전부 완료·검증
  통과한 뒤 착수한다 (파일 충돌 방지).
- [x] 블로커 해소 — R1~R6 전체 완료·검증 통과 (2026-08-19).
- [x] 기획 완료 — 탭별 상세 스펙 + 실행 순서(라운드 1~3):
      [docs/specs/ui-redesign-plan-2026-08-19.md](specs/ui-redesign-plan-2026-08-19.md).
      결정 대기 4건 등록됨 → [docs/decisions-needed.md](decisions-needed.md).
- [x] 2026-08-20 추가 요청 반영 — 추론 탭 이미지 목록에 검색/정렬 기능 부재 갭을 스펙에
      추가(라운드 2 항목 4). `ImageBrowser` 재사용은 기각(프로젝트 `images_dir` 하드코딩,
      편집 액션·라벨상태 아이콘이 추론 컨텍스트와 불일치, 공유 위젯 회귀 리스크) —
      추론 탭 전용 경량 컴포넌트 신규 구현으로 결정.
- [x] 결정 대기 4건 전부 사용자 확인 완료 (2026-08-20): 리사이즈 상한 **완전 무제한**,
      신뢰도 표시 **통계까지만**, `ClassPanel` 200px 상한 **같이 완화**, 추론 탭 폴더
      그룹핑 **트리형 채택**(현재 썸네일 그리드 포기 — 사용자가 트레이드오프 인지하고 선택).
      `docs/decisions-needed.md` 비움.
- [x] 라운드 1 — 제약값 조정 + 스타일 통일 (목업 불필요, 저리스크) — 구현+독립검증 통과,
      커밋 `6355096`(feat)+`b567336`(docs)
- [x] 라운드 2 목업 완료 (Artifact: https://claude.ai/code/artifact/5df2af11-0642-4e69-8ddc-f545333eebca)
      — 3탭 전체 대상으로 작성됨. **사용자 결정(2026-08-20): 라벨링 탭만 우선 구현**, 학습/
      추론 탭은 보류.
- [x] 라운드 2 — 라벨링 탭: 좌/우 서브스플리터 전환 + `ClassPanel` 200px 상한 제거 — 구현+
      독립검증 통과, 커밋 `f086636`(feat)+`9901681`(docs). [GitHub #1](https://github.com/sfeelBot/Segmentation-Tool/issues/1)
      폴더 정보 표시 요청 중 라벨링 탭 쪽은 **정정(2026-08-21)**: "기존부터 지원"은 오답
      이었음 — 라벨링 탭은 폴더 그룹핑 미지원(단일 평탄 목록), BUG-005 참고.
- [x] 2026-08-20 사용자 재확인 — 학습/추론 탭 라운드 2 재개 확정. 단, 아래 "디자인 톤
      홀리스틱 재검토"를 먼저 거쳐 아이콘 목업과 함께 일관성 있게 다듬은 뒤 구현.
- [ ] 라운드 2 — 학습 탭 큐 영역 서브스플리터 (재개 확정, 디자인 톤 재검토 반영 후 구현)
- [ ] 라운드 2 — 추론 탭 상단↔뷰어 서브스플리터 + 이미지 목록 검색/정렬/트리형 폴더 신규
      (재개 확정, 디자인 톤 재검토 반영 후 구현 — [GitHub #1](https://github.com/sfeelBot/Segmentation-Tool/issues/1)
      폴더 정보 표시 요청과 직결)
- [ ] 라운드 3 — 정보 추가 (디자인 목업 필요, 중~고리스크 — `annotation_canvas.py`,
      `inference_engine.py` 최소 침습 패치 포함, 아직 미착수)
- 다음 단계: 디자인 톤 홀리스틱 재검토(아래 절) → 학습/추론 탭 라운드 2 구현 → 검증.

## GitHub 이슈 VOC (2026-08-20 접수)

- [GitHub #1](https://github.com/sfeelBot/Segmentation-Tool/issues/1) "사용성 정리"
  - ① 라벨링/추론 이미지 탭 폴더 정보 표시 — 위 "UI/UX 재편" 절에서 커버. **정정
    (2026-08-21)**: 라벨링 탭은 폴더 그룹핑 미지원(단일 평탄 목록, BUG-005로 죽은 코드
    제거 완료 — 필요 시 별도 기능 요청), 추론 탭은 라운드 2에서 실제 재귀 스캔 기반
    트리형 폴더 그룹핑 구현 완료(`inference_image_list.py`).
  - ② RTX 4500 Ada GPU인데 CPU 전용 torch 설치됨 — 원인 파악 및 문서 수정 완료
    (`README.md`, `requirements.txt`, `docs/USER_MANUAL.md`). 코드 변경 아님.
- [GitHub #2](https://github.com/sfeelBot/Segmentation-Tool/issues/2) "프로젝트 내보내기 기능"
  — 기획 완료: [docs/specs/voc-github-issues-2026-08-20.md](specs/voc-github-issues-2026-08-20.md)
  - ① **2026-08-20 사용자 재확인으로 요청 정정** — "최근 프로젝트 목록 클릭" 문제가 아니라
    "전용 프로젝트 확장자를 만들어 OS 파일탐색기에서 더블클릭하면 앱이 그 프로젝트로 바로
    열리게 해달라"는 뜻이었음. Windows 파일 연결(레지스트리 등록)은 보통 설치 프로그램이
    처리하므로 아래 "exe 패키징 + Setup Guide" 항목에 하위 요구사항으로 편입 — 별도 라운드
    아님, exe 패키징 착수 시 함께 설계.
  - ② 프로젝트 전체 내보내기/가져오기 — **2026-08-20 사용자 확인 완료: A(export)+B(import)
    모두 이번에 진행.** 라운드 A: `project_export_dialog.py` 신설(zip, `images/`+`annotations/`+
    `classes.json`+`project.json` 항상 포함, `checkpoints/` 기본 미체크/`user_models/` 기본
    체크), `_FolderImportWorker` 패턴 따르는 백그라운드 압축 워커. 라운드 B: zip→프로젝트
    복원, 이름 충돌 시 자동 리네임(덮어쓰기 금지)으로 확정. A 구현·검증 통과 후 곧바로 B로
    이어서 진행(zip 포맷 의존관계). `docs/decisions-needed.md` 비움.
  - [x] 라운드 A(export) — 구현+독립검증 통과, 커밋 `911f85a`(feat)+`d42fe46`(docs).
        `app/core/project_export.py` + `app/widgets/project_export_dialog.py` 신설,
        zip 상대경로 구조 확인(라운드 B 전제조건 충족).
  - [x] 라운드 B(import) — 구현+독립검증 통과, 커밋 `4129f10`(feat)+`03f5e38`(docs).
        신규 `app/widgets/project_import_dialog.py`, zip slip 방어(8종 공격 벡터 차단),
        왕복 sha256 일치, 이름충돌 자동 리네임, 골든패스 UI 확인까지 완료.
  - **GitHub #2 "프로젝트 내보내기 기능" 요청2 전체 완료** (2026-08-20). 요청1은 exe
    패키징 항목으로 편입(위 참고).

## GitHub 이슈 VOC 라운드2 (2026-08-20 접수, #3~#7)

기획 완료: [docs/specs/voc-github-issues-round2-2026-08-20.md](specs/voc-github-issues-round2-2026-08-20.md).
[GitHub #3](https://github.com/sfeelBot/Segmentation-Tool/issues/3)(브러시 크기 조절 UX +
입력창 잘림) — **완료+Closed**, [#4](https://github.com/sfeelBot/Segmentation-Tool/issues/4)
(이미지명 복사 + 오토라벨 patch training 확인) — **완료+Closed**,
[#5](https://github.com/sfeelBot/Segmentation-Tool/issues/5)(모델 탭→학습 탭 "+" 모달 전환,
구조변경) — **사용자 결정으로 보류, Open 유지**(`decisions-needed.md` "보류된 항목"),
[#6](https://github.com/sfeelBot/Segmentation-Tool/issues/6)(annotation 깜빡임 + 어노테이션
개수비례 로딩 지연) — **완료+Closed**, [#7](https://github.com/sfeelBot/Segmentation-Tool/issues/7)
(OK 처리 시 기존 라벨 삭제 확인 팝업) — **완료+Closed**. 2026-08-21 리더가 각 이슈에 해결
내역 코멘트 남기고 GitHub에서 close 처리 완료(#5 제외).

- [x] **#6-B 어노테이션 개수 증가 시 로딩 지연 (최우선, 사용자 명시)** — `labeling_tab.py`
      `_refresh_ann_list()`(매 편집마다 어노테이션 목록 전체 재생성) +
      `annotation_canvas.py` `_rebuild_overlay()`(매 편집·이미지전환마다 오버레이 전체
      재렌더링) 2곳의 O(n) 전체 재구축 패턴이 원인으로 특정됨. **구현 완료**, 커밋
      `574fb33`(perf)+`5f13df4`(docs). `_refresh_ann_list()`는 clear+전체재생성→
      이전 리스트와 diff해 변경분만 갱신. `_OverlayWorker.run()`은 brush_mask를
      이미지 전체 크기로 resize하던 것을 `cv2.boundingRect` 기반 bbox-crop으로 변경
      (첫 시도 `np.where` 방식은 벤치마크에서 3배 역효과 확인 후 폐기, `cv2.boundingRect`로
      교체해 14배 개선). **벤치마크(전→후)**: `_refresh_ann_list` n=500 연속20회 편집
      200.1ms→22.8ms(8.6배), `_OverlayWorker.run()` n=500·5472×3648 이미지
      3396ms→~1600ms(2.1배). 정확성 검증: 원본해상도 렌더링은 기존과 bit-exact,
      다운스케일 분기는 경계 1px 이내 근사(수학적으로 불가피, 저장 데이터엔 무영향).
      **구현+독립검증 통과**(커밋 `41eaf13`) — 실제 `python main.py` 기동 성공(QtSvg
      DLL 이슈 이번엔 재현 안 됨) + `QTest` 실제 이벤트로 30개 assertion 전부 통과
      (폴리곤/브러시/지우개/영역지우개/선택/undo 골든패스, bbox-crop 오버레이 픽셀단위
      위치 정확성, 목록 diff갱신 순번/유령선택 없음, #6-A·BUG-011·BUG-012 회귀 없음,
      대규모(n=200) 체감 성능도 구현자 벤치마크와 스케일 일치). **부수 발견 BUG-014
      (P3, 정보성)**: `_push_undo()`가 매 브러시 스트로크마다 `_annotations` 전체를
      deepcopy — 대형 이미지+brush_mask 수백 개 상태면 메모리 부족 크래시 가능(이번
      라운드 회귀 아님, 별개 함수의 기존 구조). **GitHub 이슈 라운드2(#3~#7) 전체 완료**
      (#5만 사용자 결정으로 보류).
      **2026-08-20 추가 요청 — 실사용 규모 재검증 완료(커밋 `49cca16`, 코드 변경 없음)**:
      사용자가 "500개 이상, 이미지 만개 이상×이미지당 50개 이상" 규모로 재확인 요청.
      **축1(단일 이미지 어노테이션 500+)**: `_refresh_ann_list()` n=8000까지 선형 유지
      (1.33ms→25.29ms, 16배 규모에서도 비례). `_OverlayWorker.run()`도 메모리 압박이
      없으면 선형 유지(n=1000→338.8ms, n=2000→668.7ms) — 단 브러시 비중이 높고(2/3)
      n≈500~750을 넘으면 대형 이미지(5472×3648) 마스크 자체가 각 19MB라 Windows
      커밋/페이지파일 한계에 부딪힘(BUG-014와 같은 근본원인, `_push_undo()`와 무관하게도
      재현 — #6-B 두 함수의 회귀 아님).
      **축2(10,000장 프로젝트, 8,000장×어노테이션 50개)**: 이미지 전환 2.7~22.6ms로
      문제없음, BUG-014(전체 deepcopy)는 이 규모에서 미재현(해상도/마스크개수가 원인이지
      프로젝트 크기가 원인이 아님을 확인). **신규 발견(수정 안 함, 후속 후보로만 기록)**:
      10,000장 브라우저 초기 스캔 41.7초(콜드)→1.9초(웜, OS 디스크캐시 영향, 앱 버그
      아님), 10,000장 규모에서 검색/정렬 1회 호출당 0.3~0.8초(R6가 이미 문서화한
      `QTreeWidgetItem` 재구축 패턴이 10배 규모에서 정량 확인됨 — 사용자가 명시적으로
      불편을 제기한 적 없어 이번 라운드에서 손대지 않음, 필요시 후속 논의). "500MB 메모리
      사용" 의심도 조사해 실제로는 PyTorch/CUDA 임포트 비용(프로젝트 크기 무관)임을
      확인, 프로젝트 자체 기여분은 ~36MB로 반증.
- [x] #6-A annotation 깜빡임(flicker) — 구현 완료, 커밋 `6a823a5`(fix)+`11355e5`(docs).
      `_invalidate_overlay()`에서 즉시 null 처리하던 것 제거(새 오버레이 준비될 때까지
      이전 오버레이 유지) + `load_image()`에서 이미지 전환 시에만 명시적으로 null(다른
      이미지 크기/스케일이라 이전 오버레이를 유지하면 좌표계 불일치 위험 있어 그 경우만
      예외 처리). `#6-B`(성능, `_rebuild_overlay()`의 O(n) 구조 자체)는 범위 밖으로
      건드리지 않음 확인. **검증 대기** — 연속 브러시 스트로크/빠른 이미지 전환/채널
      토글 3개 시나리오 확인 필요.
- [x] #7 OK 처리 시 라벨 존재하면 확인 팝업 — 구현 완료. `_on_toggle_ok()`가 어노테이션
      있을 때 `_on_clear_all()`과 동일한 `QMessageBox.question()` 패턴 재사용, 예→
      `clear_all_annotations()` + 대기 중인 디바운스 저장 즉시 flush 후 OK 처리(경쟁조건
      방지), 아니오/취소→체크 원복.
- [x] #4 라벨링/추론 탭 이미지명 클립보드 복사 — 구현 완료. `settings_dialog.py`의
      `svg_icon("clipboard")`+클립보드 패턴 재사용, 라벨링 탭은 채널 스트립에 파일명
      라벨+복사버튼 신설, 추론 탭은 기존 `_lbl_filename` 옆에 복사버튼 추가. 오토라벨
      patch training 질문은 답변 완료(구현 불필요, 기존 갭으로 문서화만).
- [x] #3(a) 브러시 크기 입력창 잘림 버그 — 구현 완료, `setFixedWidth(60)`→
      `setMinimumWidth(76)`.
- [x] #3(b) 브러시 크기 더블클릭 조절 — 구현 완료. 브러시 계열 도구 활성 시 캔버스
      더블클릭→`QInputDialog.getInt()`(1~200), 신규 시그널 `brush_size_changed`로
      툴바 스핀박스↔캔버스 양방향 동기화.
      **#7/#4/#3 커밋**: `29248fa`(feat)+`12de145`(docs). `annotation_canvas.py`의
      #3(b) 변경분이 동시 작업 중이던 #6-A 커밋(`6a823a5`)에 함께 묶여 들어감 — 두 작업
      다 겹치는 라인 없이 정상 포함된 것 확인됨(구현 에이전트가 `git show`로 교차검증).
      **검증 완료(조건부 통과)** — #3(a)·#4·#6-A·#7 전부 실제 GUI 조작+클립보드/디스크
      JSON 대조까지 통과. #3(b)에서 **BUG-011(P1)** 발견: 더블클릭 다이얼로그를 열 때
      첫 클릭이 이미 stray `[Mask]` 어노테이션을 커밋해버려 매번 원치 않는 라벨이
      남음(OK/Cancel 무관) — **리더가 즉시 수정**(`mouseDoubleClickEvent()`에서 다이얼로그
      열기 전 `self.undo()` 호출, 커밋 `24e93c9`), **재검증 필요**. 부수 발견 **BUG-012
      (P2)** OK "예" 처리 직후 사이드바 아이콘은 정확하나 다른 이미지 갔다오면 stale해짐
      / **BUG-013(P3)** 신규 브러시 크기 다이얼로그 문자열이 i18n 밖 한국어 하드코딩 —
      둘 다 구현 완료, 커밋 `5d551c3`. BUG-012 근본원인 확정: `_on_toggle_ok()` flush의
      옛 비동기 `_do_save()`와 `toggle_ok()`의 동기 저장이 같은 파일에 순서 보장 없이
      경쟁 — `_do_save(sync=True)` 매개변수 추가로 flush를 동기화해 해결. BUG-013은
      `i18n.py`에 `tool.brush_size_dialog.title`/`.label` 키 추가.
      **전체 재검증 완료(2026-08-20, 커밋 `73aec13`)** — BUG-011/012/013 전부 `QTest`
      실제 Qt 이벤트로 재현 시도 후 통과(stray 어노테이션 0건, OK토글 6회 왕복 전부
      정확, en/ko 다이얼로그 문자열 정상), 일반 페인팅·undo·무라벨 OK토글 등 회귀도 없음.
      **#3·#4·#6-A·#7 전부 완료.**
- [x] #5 모델 탭→학습 탭 "+" 모달 전환 — **2026-08-20 사용자 결정: 보류(탭 구조 유지)**.
      `docs/decisions-needed.md` "보류된 항목"으로 이동. 이번 라운드 구현 대상 아님.
- 실행 순서·파일 겹침(홀리스틱 재검토 5단계는 검증 완료·조건부 통과로 갱신됨 — 아래
  "디자인 톤 홀리스틱 재검토" 절 참고. `inference_tab.py`에 Open인 BUG-009(검색 카운터
  표시버그, P3)와 #4 카피 버튼 착수 시 같은 파일이니 유의)은 스펙 문서 "실행 순서 제안" 절 참고.
  **결정 완료 항목(#3 전체·#4·#6-A·#6-B·#7) 전부 구현 착수 가능** — #5만 보류.
- [ ] **구현 착수** — 두 구현 에이전트 병렬 위임: (A) #7 OK확인팝업 + #4 이미지명 복사
      + #3(a)(b) 브러시 스핀박스 폭+더블클릭 조절(`labeling_tab.py`/`inference_tab.py`),
      (B) #6-A 깜빡임 수정(`annotation_canvas.py`의 `_invalidate_overlay()`만, 다른
      에이전트와 파일 겹침 없게 분리). #6-B(성능)는 두 라운드 검증 통과 후 별도 착수
      (같은 함수 영역이라 순서 충돌 방지).

## GitHub 이슈 VOC 라운드3 (2026-08-25 접수, #8~#9)

기획 완료: [docs/specs/voc-github-issues-round3-2026-08-25.md](specs/voc-github-issues-round3-2026-08-25.md).
사용자 지시대로 처리 순서 **#9(버그) 먼저 → #8(신규 기능)**.

- [ ] [GitHub #9](https://github.com/sfeelBot/Segmentation-Tool/issues/9) "줌인/줌아웃 초점
      안 맞음" — 원인 코드로 확정: `annotation_canvas.py`의 좌클릭 패닝 드래그
      (`_pan_active`) 도중 마우스 휠로 줌하면 `mousePressEvent()`가 캡처해둔
      `_pan_start_mouse`/`_pan_start_offset`이 갱신되지 않아, 휠 직후 `mouseMoveEvent()`가
      휠이 방금 계산한 커서-고정 pan을 옛 기준값으로 덮어씀. 정지 상태 휠 줌·Select
      도구 드래그·브러시 스트로크 도중 줌은 이 결함의 영향 없음(패닝 드래그만 해당). 앱
      전체에서 줌 진입점은 `wheelEvent()`(휠 스크롤) 하나뿐임도 확인. 구현 범위는
      `annotation_canvas.py` 단일 파일, 저리스크. 재현조건 재확인용 질문 3건은 스펙 문서에
      정리(결정 대기 등록은 아님 — 구현 진행 막을 필요 없다고 판단).
- [ ] [GitHub #8](https://github.com/sfeelBot/Segmentation-Tool/issues/8) "이미지탭
      다중선택+삭제" — **코드 조사 결과 이미 구현되어 있음**: `image_browser.py`의
      `_tree`가 이미 `ExtendedSelection`(Ctrl/Shift 다중선택)이고, `_on_delete()`가 이미
      다중 선택 전체를 순회해 이미지+대응 어노테이션 JSON을 함께 삭제 + 확인 다이얼로그
      (1개/2개 이상 요약)까지 갖춤. 과거 `unhashable QTreeWidgetItem` 크래시(2026-05-27
      로그)는 그 원인 코드 패턴(`_item_to_path[item]=...`)이 현재 구조에서 완전히
      사라져 재현 불가로 판단(현재는 Path가 dict 키, 아이템→Path는 UserRole 역조회).
      이번 라운드는 **검증 우선**(실제 GUI로 다중선택+삭제+어노테이션 정리 확인) — 문제
      발견 시에만 최소 보강. 저비용 선택 갭 1건(키보드 `Delete` 단축키 없음, 버튼만 가능)
      기록해둠. 결정 대기 없음.

## 아이콘/이모지 → 미니멀 디자인 + i18n(en) 완비 (2026-08-20 요청)

사용자 요청: "아이콘 가시성이 떨어진다 — 남길 아이콘은 깔끔·미니멀하게, 불필요한 건 글자로
바꿔라. 다국어(영어)도 전부 업데이트되게 해달라." 대상: 전체 앱(라벨링 탭 툴바, 이미지
브라우저 상태기호, 프로젝트 다이얼로그, 각종 팝업 등 이모지 문자로 표현된 UI 전반).
**학습/추론 탭 UI 재편(라운드 2)과는 별개 트랙** — 저건 레이아웃, 이건 아이콘/텍스트/i18n.
파일 겹침(`project_start_dialog.py` 등) 있을 수 있어 진행 중인 GitHub #2 라운드 B(가져오기)
완료 후 그 파일은 순서를 조정할 것.
- [x] 1단계 — Explore 조사 완료. 핵심 발견:
      - i18n(`app/core/i18n.py`): ko/en 193키 1:1 완전 대응, 누락 없음. **이모지가 번역
        값 안에 박혀있어** 교체 시 문자열 하나만 고치면 두 언어 동시 반영됨(좋은 소식).
      - **단, 3개 파일이 i18n 체계 밖에서 한국어+이모지를 직접 하드코딩**: `image_browser.py`,
        `training_progress_dialog.py`, `main_window.py` — 이 파일들은 en 버전 자체가 없어
        `t()` 전환 + en 키 추가가 별도로 필요.
      - **"꼭 필요"로 분류된 기능적 아이콘 4그룹**(미니멀 재설계 대상): 라벨링 탭 툴바 7종
        도구(`labeling_tab.py`, 텍스트 없이 이모지 단독+16px), `image_browser.py` 상태기호
        3종(●✓○, 색상 대비 약함), `training_progress_dialog.py` STATUS_ICON 5종,
        `log_panel.py` 로그 레벨 아이콘 3종.
      - 나머지(다이얼로그 제목, 그룹박스 제목, 버튼 접두 이모지, 프리셋 카드 이모지 등,
        `project_start_dialog.py`/`auto_label_dialog.py`/`settings_dialog.py`/
        `model_presets/__init__.py` 등 다수)는 **장식 판정 — 텍스트만 남기고 이모지 제거**.
      - 예외: `settings_dialog.py` 언어 콤보의 국기 이모지(🇰🇷🇺🇸)는 언어 식별에 실질적
        도움 — 유지 후보.
      상세: [docs/agents/design-log.md](agents/design-log.md) 예정 참고(디자인 단계에서 인용).
- [x] 2단계 — 디자인 에이전트가 목업 제안(Artifact) → **2026-08-20 사용자 승인 완료**
      (SVG+QIcon 방식, 3라운드 실행안 채택). 상세: [design-log.md](agents/design-log.md).
- [ ] 3단계 — 구현: 4그룹 아이콘 재설계(완료, 아래 "디자인 톤 홀리스틱 재검토" 1단계 참고)
      + 장식 이모지 제거 + i18n 밖 3개 파일 en 전환 (아래 "디자인 톤 홀리스틱 재검토" 실행
      순서로 이관해 진행 중. `project_start_dialog.py`는 GitHub #2 라운드B와 겹치니 그쪽
      완료 후 순서 조정 — GitHub #2는 이미 완료됐으므로 다음 라운드에 포함 가능)

## 디자인 톤 홀리스틱 재검토 (2026-08-20 요청)

사용자 요청: 아이콘 목업 승인 + 학습/추론 탭 재개와 별개로, **전체 4탭(모델/라벨링/학습/
추론)의 색상·타이포·여백·아이콘 스타일 일관성**을 디자인 에이전트가 한 번에 다시 검토·
개선. 라벨링 탭은 이미 라운드 2 구현이 끝나 있으므로 그 결과와도 어긋나지 않는지 함께 점검.
- [x] 디자인 에이전트 홀리스틱 검토 완료 — `main.py` 전역 스타일시트 + 라벨링 탭 실구현
      코드를 기준선으로 학습/추론/모델 탭 및 보조 위젯 전수 대조.
      **통합 Artifact**(기존 아이콘 목업 `f76ffe60`, 레이아웃 라운드2 `5df2af11` 대체):
      https://claude.ai/code/artifact/7876ed3e-e6ef-4d8b-92cb-cd2fecf2d98a
      상세: [design-log.md](agents/design-log.md) 2026-08-20 홀리스틱 재검토 항목.
- **발견 8건**(높음 2 / 중간 4 / 낮음 2) — 상세 Artifact 2절:
  1. (높음) `model_tab.py` 코드 에디터·로그 패널이 GitHub 다크 테마 계열 독자 팔레트 사용 —
     앱 표준 팔레트와 가장 크게 어긋남
  2. (높음) `loss_chart.py`(matplotlib)가 독자 팔레트 정의 — 주변 톤과 이질적
  3. (중간) 라벨링 탭 툴바에 승인된 SVG 아이콘 7종과 미교체 색이모지 6종이 한 줄에 공존 —
     재설계 이전보다 더 눈에 띄는 불일치 위험
  4. (중간) `main_window.py`/`log_panel.py`/`settings_dialog.py` 텍스트 없는 아이콘 전용
     버튼 5개 — 기존 "장식 이모지 제거(텍스트만 남기기)" 방식 적용 시 버튼이 텅 빔(분류 오류)
  5. (중간) `model_tab.py` 텍스트+이모지 버튼 4개가 1단계 조사의 "장식 이모지 제거" 목록에서
     누락
  6~8. (낮음) `image_browser.py` 상태기호 미구현 재확인 / 보조 텍스트 색상 혼용
     (`#888`·`#ccc` vs `#9ca3af`) / CUDA 배너 팔레트 밖 신규값
- 산출물에 아이콘 확장안(승인 7종+신규 12종, 동일 시각 언어), 학습/추론 탭 Before/After
  목업, 확장 팔레트 참조표, 7단계 실행 순서 포함.
- **2026-08-20 사용자 승인 완료** — 통합안대로 구현 착수 확정. 새 색상 팔레트 도입 없음
  (기존 값 재사용). 7단계 실행 순서(라운드 단위로 구현+검증):
  1. [x] 기능 아이콘 SVG화 확장판(승인 7종 + 신규 12종) — 구현+독립검증 통과, 커밋
        `2ad0165`(feat)+`2f05313`(docs)+`ed99ca5`(검증로그). `app/resources/icons/*.svg`
        22개 + 로더(`app/widgets/icons.py`) 신설. 검증 에이전트가 `python main.py` 실제
        구동으로 19개 지점 전부 육안 확인(브러시 활성 하이라이트, eye 토글 실동작, 클립보드
        복사 실동작, 학습 탭/진행다이얼로그 STATUS_ICON_NAME 리네임 양쪽 정상 등). 버그 없음.
  2. [x] 장식 이모지 제거 — 구현 완료(2세션 이어서 진행: 1차 에이전트 API세션한도로 중단
        → 리더가 안전성 확인(py_compile, diff 일관성) 후 2차 에이전트가 이어받아 마무리),
        커밋 `b33491d`(feat)+`b9a18d6`(docs). `i18n.py` ko/en 약 96곳 + `training_tab.py`
        `⏸️` 3곳 + `image_browser.py` 폴더 트리 아이콘(기능적 표시라 삭제 대신
        `svg_icon("folder", ...)`로 전환) 등 19개+ 파일. 이모지 전용 라벨(`menu.settings`/
        `menu.export`)은 텍스트가 없어 아이콘 버튼으로 전환(`gear.svg`/`export.svg` 신규),
        `main_window.py`의 기존 `svg_icon()` 패턴 재사용. 예외(설정 언어 국기, 로그레벨
        모노톤 기호, model_tab `✓`/`✗`, config_form `⚠`)는 그대로 보존 확인.
        **구현+독립검증 통과** — 검증 에이전트가 `python main.py` 실제 구동으로 4대 탭
        이름, 설정/내보내기 아이콘 버튼 클릭 동작, 이미지브라우저 폴더 아이콘 렌더링,
        학습 탭 상태 라벨까지 확인. 커밋 `de9722a`(검증로그)까지 반영.
        **부수 발견 — BUG-005(P2, `QA.md`)**: `image_browser.py` 폴더 그룹핑 기능이
        `reload()`/`_on_add*()` 설계상 실제로는 어떤 사용자 동작으로도 트리거되지
        않는 죽은 코드임을 확인(이번 라운드가 만든 회귀 아님, 수개월 전부터 존재).
        GitHub #1 VOC "라벨링 탭은 기존부터 폴더 트리 있음" 응답도 정정 필요 —
        `docs/decisions-needed.md`에 처리 방향(지금 고칠지/보류할지) 등록함.
  3. [x] `model_tab.py` 에디터/로그 팔레트를 앱 표준으로 정규화 (발견 1) — 구현+독립검증
        통과, 커밋 `a8ac52d`(refactor)+`f0fc2ef`(docs)+`386b69b`(검증로그). 신택스
        하이라이터 구조는 유지, 색상값만 표준 팔레트로 매핑. 검증 에이전트가 실제
        `ModelTab` 구동으로 검증(Validate)/로드(Load) 골든패스 확인 + WCAG 대비 전수
        계산으로 가독성 저하 없음(오히려 개선/동등) 확인.
        **부수 발견 BUG-006(P2)**: `model_validator`는 허용 목록 밖 import를 경고만
        띄우고 통과시키지만 `model_loader`의 exec 샌드박스는 같은 모듈에 ImportError로
        무조건 실패 — "검증 통과+로드 버튼 활성화"인데 실제 로드는 항상 실패하는 기존
        정책 불일치. 이번 라운드 회귀 아님(수개월 전부터 존재), `QA.md` 등록 완료.
  4. [x] `loss_chart.py` matplotlib 배색을 앱 톤에 맞게 조정 (발견 2) — 구현+독립검증
        통과, 커밋 `e76361a`(refactor)+`eda6455`(docs)+`9c7916c`(검증로그). 검증 에이전트가
        실제 `LossChart` 위젯에 더미 손실데이터로 렌더링해 배경/선색/범례 대비 확인.
        부수 발견 **BUG-007(P3)** — 그리드·epoch경계선이 동일 색으로 통일돼 구분이 안
        되던 것을 리더가 직접 1줄 수정(`_EPOCH`→`#4b5563`)해 즉시 해결, `QA.md` Closed로
        기록.
  5. [ ] 학습 탭 큐 서브스플리터 + 추론 탭 서브스플리터·이미지 트리 — **양쪽 구현 완료**.
        학습 탭: 커밋 `a32a8b5`(feat)+`b51318f`(docs), `_queue_splitter` 세로 QSplitter
        전환 + `_queue_list` 높이 상한 제거 같은 커밋에서 함께 처리.
        추론 탭: 커밋 `b09fb83`(feat)+`2955da7`(docs) — 상단↔뷰어 세로 서브스플리터 +
        체크포인트테이블 120px 상한 제거(같은 커밋), 신규 `app/widgets/inference_image_list.py`
        (`InferenceImageList`: 검색+정렬+`QTreeWidget` 폴더트리, `rglob("*")`로 실제
        재귀 스캔 — BUG-005 재발 방지 확인됨, 2단계 중첩 폴더로 스크립트 테스트 통과).
        **검증 완료** — 검증 에이전트가 `python main.py` 실제 드래그/타이핑 자동화로
        골든패스(학습 큐→실제 학습 실행→체크포인트 생성, 추론 폴더선택→재귀폴더트리→
        검색/정렬→추론 실행→오버레이) 전부 확인, 크래시·데이터 손실 없음.
        발견 3건: **BUG-008(P2)** 스플리터 핸들 끝까지 드래그 시 0px 붕괴 — 리더가
        `setChildrenCollapsible(False)`를 5개 스플리터 전부에 추가해 즉시 수정(커밋
        `7a98760`) → **재검증 통과**(7개 스플리터 전부 양방향 극단 드래그로 최소크기에서
        정확히 멈춤 확인, 일반 리사이즈도 문제없음), `QA.md` Closed. **BUG-009(P2)** 추론 탭 검색
        필터 해제 시 이전/다음 카운터가 갱신 안 되는 표시 버그(데이터 손상 없음) — Open,
        후속 라운드. **BUG-010(P3)** 폴더 트리 펼침 화살표 인디케이터 미표시(더블클릭은
        정상 동작, `image_browser.py` 기존 스타일 상속분) — Open, 저우선.
  6. [x] i18n 밖 3파일(`image_browser.py`/`training_progress_dialog.py`/`main_window.py`)
        en 전환 — **구현+독립검증 통과**, 커밋 `96b829c`(feat). `i18n.py`에 27개 신규
        ko/en 키쌍(`project.status_bar` + `browser.*` 22개 + `train_progress.*` 10개)
        추가, 3파일 전부 `t()` 호출로 이관. 검증 에이전트가 실제 `python main.py`로
        en/ko 양쪽 전환해 검색창·정렬콤보·범례·파일추가다이얼로그·삭제확인·상태바·학습
        진행다이얼로그 전부 정상 렌더링(KeyError·잔존 한국어 없음) 확인.
  7. [x] 팔레트 토큰 정규화(발견 7·8, 저우선) — **구현+독립검증 통과**, 커밋 `8f78f8a`
        (refactor). 발견 6(image_browser 상태기호 색상)은 라운드1에서 이미 해결 확인.
        발견 7: `#888`→`#9ca3af`, `#ccc`→`#e5e7eb` 정상 확인.
        **부수 발견 BUG-015(P2, 검증 중 발견)**: 발견 8(CUDA 배너 좌측 색상보더)이
        선택자 없는 스타일시트가 자식 QLabel까지 전파돼 보더가 두 개 막대로 이중
        렌더링되는 문제 — 리더가 `banner.setObjectName("cudaBanner")`+ID선택자로
        범위를 좁혀 즉시 수정(커밋 `142d251`) → **재검증 완료**(`QWidget.grab()` 픽셀
        스캔으로 단일 3px 보더만 렌더링됨 확인, 성공/실패 두 상태 모두), `QA.md` Closed.
- 각 라운드는 이전 성능개선 R1~R6과 동일하게 구현→독립검증 통과 후 다음 라운드로 진행.
  **7단계 실행안 ①~⑦ 전체 구현+독립검증 통과로 완전히 마무리됨.**

## exe 패키징 + Setup Guide (2026-08-20 요청, 추후 착수)

사용자 요청: "추후에는 py파일로 실행이 아닌 exe 파일로 실행하게 하고 싶어. setup guide 관련된
문서도 필요할거야." — 지금 당장이 아니라 **추후** 착수. CLAUDE.md에 이미 이 범위 경계가
명시돼 있음: "배포 에이전트 범위: 버전 태깅, CHANGELOG 갱신까지만 담당. PyInstaller 등
실행파일 패키징/배포는 범위 밖 (별도 논의)." 착수 시 다음을 검토해야 함:
- PyInstaller(또는 유사 도구)로 `main.py` → 단일 exe/설치본 패키징. torch/torchvision/CUDA
  런타임 DLL을 exe에 어떻게 포함시킬지가 핵심 난제(용량·GPU 빌드별 분기 — [GitHub #1](https://github.com/sfeelBot/Segmentation-Tool/issues/1)
  의 CPU-only 설치 문제와 같은 종류의 함정이 exe 배포에서도 재현될 수 있음).
- **[GitHub #2](https://github.com/sfeelBot/Segmentation-Tool/issues/2) 요청1 편입** (2026-08-20):
  전용 프로젝트 확장자(예: `.segproj`) 파일을 OS에서 더블클릭하면 이 앱이 그 프로젝트를 바로
  열도록. Windows 파일 연결 레지스트리 등록(보통 설치 프로그램이 처리) + `main.py`가
  `sys.argv[1]`로 넘어온 프로젝트 경로를 받아 시작 다이얼로그를 건너뛰는 로직 필요. 상세:
  [docs/specs/voc-github-issues-2026-08-20.md](specs/voc-github-issues-2026-08-20.md) "요청 1" 절.
- Setup Guide 문서 — 현재 `docs/USER_MANUAL.md`는 "pip install"이 전제인 개발자용 설치
  안내. exe 배포판 사용자는 pip/Python 환경 자체가 없을 수 있으므로 별도 성격의 문서(또는
  같은 문서의 새 절)가 필요.
- [ ] 착수 대기 — 사용자가 "추후" 착수 시점을 알려주면 스파이크(PyInstaller+torch/CUDA
      번들링 실측)부터 시작. 지금은 기록만.

## 존(Zone) 분석 탭 — 배터리 캡 녹 검사 독립 도구 (2026-08-25 요청)

브랜치 `feature/zone-analysis-tab`. 기존 4탭(모델/라벨링/학습/추론)과 완전히 독립된
신규 5번째 탭 — 삼성SDI 원통형 배터리 캡 이미지에서 동심원 구역(존)별 녹 검출 면적
비율(%)을 계산하는 도구. 기획 완료: [docs/specs/zone-analysis-tab-2026-08-25.md](specs/zone-analysis-tab-2026-08-25.md).

- 확정 요구사항(재질문 불필요): ① 프로젝트 시스템 미사용, 이미지/체크포인트 직접 로드 후
  즉석 추론 ② 동심원 자동검출(**2026-08-25 2차 수정**: 1차 수정에서 "Hough 아님, 순수
  컨투어 폐곡선"으로 바꿨던 것을 사용자가 재정정 — 검출 파이프라인은 Canny+findContours를
  유지하되, 마지막에 강건한 원피팅을 추가해 **최종 저장/편집 대상은 다시 원(circle)**)
  + 수동 편집(원 드래그 이동/반지름 조절/추가/삭제, 정점 편집 아님) ③ 존별 클릭 선택 +
  녹 마스크 면적비율(%) ④ 추론 마스크 블랍(connected component) 클릭 삭제 + 재계산 ⑤ main
  병합은 추후 확인.
- 탭 배치: 기존 `QTabWidget` 5번째 탭(별도 진입점 아님) — "독립"은 데이터 모델(프로젝트
  시스템 미사용) 독립을 뜻하는 것으로 판단, core 신규 모듈은 `app.core.project` 미참조로
  보장. 근거 상세는 스펙 문서 "판단 1" 절.
- 핵심 기술 판단: **2026-08-25 2차 수정(최종, 1차 수정을 재정정)** — 데이터 모델은 다시
  `(id, cx, cy, r)` 원(Circle)으로 확정. 사용자가 "자동 검출하더라도 원형을 유지해줘,
  불량 때문에 이상하게 잡으면 안 되니까"로 정정 — 녹(불량)이 에지를 침범해도 검출 결과가
  실제 원형에서 벗어나면 안 된다는 뜻이었음(1차 수정의 "폐곡선 그대로 저장"은 폐기). 다만
  검출 파이프라인은 Hough 단독으로 되돌리지 않고 1차 수정의 조사를 그대로 살려 합침:
  `cv2.Canny`→`cv2.findContours`→원형도(4π·area/perimeter²)+면적 필터로 링 후보 선별→
  **신규: Kasa 대수적 최소자승 원피팅 + 잔차 큰 점 제외 1~2회 재피팅(이상치 강건)**으로
  최종 `(cx,cy,r)` 산출(`scipy` 불필요, `numpy.linalg.lstsq`로 충분). 존 계산은 원 마스크
  (`cv2.circle(thickness=-1)` 또는 벡터화 거리식)의 집합 차집합(`AND NOT`)으로 복귀
  (`fillPoly` 폐기) — 원이 원을 포함하면 하위 원 영역이 항상 자동 제외됨을 명시(반지름
  오름차순 정렬 후 인접쌍 차집합이면 자동 성립). 수동 편집도 원래(1차 수정 이전)의 단순한
  드래그 이동/반지름 핸들 조절/추가삭제로 복귀 — 1차 수정에서 필요하다고 판단했던
  "이미 닫힌 폴리곤 정점 드래그/삽입/삭제 신규 UI 구현"은 데이터 모델이 원으로 돌아오며
  불필요해짐(원 편집이 정점 편집보다 훨씬 단순). 상세는 스펙 "판단 2"(전면 재작성)·
  "존 계산 로직" 절. 체크포인트→모델 재구성(판단 3)과 타겟 클래스 즉석 구성(판단 4)은
  1차·2차 수정 모두와 무관해 변경 없음.
- 신규 파일(예정): `app/tabs/zone_analysis_tab.py`, `app/widgets/zone_canvas.py`,
  `app/core/circle_detector.py`(1차 수정 때 `contour_detector.py`로 개명했던 것을 다시
  `circle_detector.py`로 원복 — 내부 구현은 Canny+findContours+원피팅 파이프라인),
  `app/core/zone_metrics.py`. 기존 파일 최소 수정: `app/core/inference_engine.py`
  (옵션 인자 3곳), `app/main_window.py`(탭 등록), `app/core/i18n.py`(키 추가).
- 실행 순서(라운드 4개, 스펙 "라운드 분할 제안" 절): R1 탭 스켈레톤+파일로드+모델재구성+
  추론실행(원 편집 없음) → R2 원 자동검출/수동편집(**서브스텝 2a: 실제 예시 이미지(특히
  녹 있는 영역)로 Canny/원형도/면적/원피팅 파라미터 스크립트 프로토타입 선행, 강건한
  원피팅이 이상치를 실제로 걸러내는지가 핵심 확인 포인트** → 2b: 위젯 구현, 원 드래그/
  반지름조절/추가/삭제) → R3 존 리스트+퍼센티지 계산 → R4 블랍 클릭 삭제+재계산. 각 라운드
  구현 후 `python main.py` 실제 구동 검증.
- [ ] 결정 대기 1건 등록 — 타겟 클래스 2개 이상 검출 시 v1 범위(단일 드롭다운 vs
      다중 비교표). [docs/decisions-needed.md](decisions-needed.md) 참고.
- [x] R1 (탭 스켈레톤 + 파일 로드 + 모델 재구성 + 추론 실행) — 구현+독립검증 통과,
      커밋 `13f2952`(feat). `ZoneAnalysisTab`/`ZoneCanvas`(순수 뷰어) 신설,
      `inference_engine.run/run_sliding_window/refilter`에 `classes` 옵션 인자 추가
      (기존 4탭 호출부 영향 없음), 타겟(녹) 클래스 즉석 구성(raw_class_map 기반) 반영.
      **검증 완료(2026-08-26, 별도 워크트리 `D:\segmentation model-zone-analysis-tab`)** —
      스크래치 프로젝트로 preset(`lraspp_mobilenet`)/커스텀(`loaded`) 체크포인트 2종을 직접
      학습 생성 후, `python main.py`와 동일한 임포트 순서로 `MainWindow`를 실제 구동해
      `QTest` 실제 클릭/키입력으로 골든패스 31개 항목 전부 통과: 5번째 탭 표시+이름+탭바
      클릭 전환, preset 체크포인트 자동 인스턴스화(코드박스 숨김), 커스텀 체크포인트
      Validate→Load 2단계(코드박스 노출), 타겟 클래스 단일(텍스트필드, 편집 반영)/2개
      이상(드롭다운, 전환 반영) 즉석 구성 양쪽, 오버레이 캔버스 표시. 회귀 확인:
      `inference_tab.py`가 `classes=` 인자를 전혀 넘기지 않는 것을 정적 grep으로 확인 +
      실제 `engine.run()`을 인자 생략 호출로 실행해 `load_classes()` 폴백이 기존과 동일하게
      동작함을 실행 확인. 버그 발견 없음(QA.md 신규 등록 없음).
- [x] R2 (원 자동검출/수동편집, 2a 스크립트 프로토타입 → 2b 위젯 구현) — 구현+독립검증
      통과, 커밋 `1815921`(2a `circle_detector.py`+`scripts/zone_circle_proto.py`),
      `b1f05bc`(2b `zone_canvas.py`+`zone_analysis_tab.py` UI 연결).
      2a: 실제 샘플 5장(`projects/nok/images/7~11번.bmp`)으로 파라미터 튜닝 — 1차
      시도에서 큰 원(케이스 테두리 등)이 글레어/그림자로 인한 에지 끊김 때문에 전혀
      검출 안 되는 문제를 발견해 Canny 직후 모폴로지 CLOSE(15×15, 2회)를 추가해 해결,
      먼지/스크래치발 가짜 원 제거를 위해 `min_area_frac` 상향. 녹 변색이 있는 구간에서도
      피팅된 원이 실제 원형 경계를 벗어나지 않음을 5장 전부 육안 확인(스펙 핵심 확인
      목표 충족). 2b: `ZoneCanvas`에 원 렌더링+편집(중심 드래그 이동/테두리 드래그
      반지름 조절/빈 곳 드래그 생성/Delete·우클릭 삭제) 추가, 탭에 자동 검출 버튼+민감도
      슬라이더+원 목록 사이드 패널 연결.
      **검증 완료(2026-08-26, 별도 워크트리 `D:\segmentation model-zone-analysis-tab`)** —
      스크래치 프로젝트로 `lraspp_mobilenet` preset 체크포인트를 실제 학습 생성 후
      `python main.py`와 동일 임포트 순서로 `MainWindow` 실구동, `QTest` 실제 이벤트로
      37개 assertion 전부 통과: 자동 검출(민감도 50%→2개/90%→4개 원, 배터리 캡 동심원
      구조와 개연성 일치, 원본 5472×3648 스케일 좌표 역산 정확) + 수동 편집 4종(중심
      드래그 이동/테두리 드래그 반지름 조절/빈 곳 드래그 생성/Delete·우클릭 삭제) 전부
      실제 조작으로 확인 + 사이드 패널 반지름 오름차순·양방향 동기화(수정 후) + 라운드1
      회귀 없음. **BUG-018 발견+즉시 수정+재검증 통과**: 캔버스에서 원을 클릭 선택/이동/
      반지름조절/생성해도 `mouseReleaseEvent`가 매번 `circles_changed`를 emit해
      `_refresh_circle_list()`가 리스트를 `clear()`하며 `currentRow`가 -1로 리셋 →
      사이드 패널 하이라이트가 사라지는 버그(원 데이터 자체는 정상). `ZoneCanvas.
      selected_id()` getter 추가 + `_refresh_circle_list()`가 재구성 후 선택을 복원하도록
      수정(공유 함수 1곳 수정으로 모든 경로에 동시 적용). 부수적으로 "추론 전 자동 검출
      클릭 시 캔버스에 아무것도 안 보여 혼란"도 확인돼 `_btn_detect`를 추론 완료 전까지
      비활성화하도록 추가. `QA.md` BUG-018 Closed로 등록. 상세: [implementation-log.md](agents/implementation-log.md)
      2026-08-26 항목, [verification-log.md](agents/verification-log.md) 2026-08-26 항목.
- [x] R3 (존 리스트 + 퍼센티지 계산) — 구현+독립검증 통과, 커밋 `d0fcfd9`(feat).
      `app/core/zone_metrics.py` 신설(`Circle`/`Zone` 데이터클래스, `zones_from_circles()`
      원판 마스크 벡터화 거리식 차집합, `zone_stats()` 존 면적 대비 타겟 클래스 픽셀 비율).
      `zone_canvas.py`에 `zone_clicked` 시그널(원이 아닌 빈 곳 단순 클릭 시 클릭 지점이
      속한 존 인덱스를 기하 조건만으로 계산해 emit) + `set_highlighted_zone()`(원 경로
      짝수-홀수 채우기 규칙으로 반투명 하이라이트, 별도 비트맵 없이 기존 원 렌더링
      좌표변환 재사용) 추가. `zone_analysis_tab.py`에 존 리스트 사이드 패널 추가 — 항상
      전체 존 퍼센티지를 한번에 표시, 리스트 클릭↔캔버스 하이라이트 양방향 동기화, 원
      추가/이동/크기조절/삭제(`circles_changed`) 및 타겟 클래스 전환(`_on_target_changed`)
      시 실시간 재계산.
      **검증 완료(2026-08-26, 별도 워크트리 `D:\segmentation model-zone-analysis-tab`)** —
      `zone_metrics.py` self-check 재확인 통과, `python main.py`와 동일 임포트 순서로
      `MainWindow` 실구동 + `engine.run`/`refilter`를 손계산 가능한 합성 `raw_class_map`
      (반지름 60 디스크)으로 몽키패치해 `QTest` 실제 마우스 드래그로 원 생성/반지름조절/
      이동까지 재현, 존 리스트 표시 퍼센티지를 `zone_metrics`를 거치지 않는 독립 numpy
      오라클과 대조해 완전 일치 확인(원 1개→존 2개 중심부 100%/바깥쪽 4.19% 등), 실시간
      재계산(반지름 변경 시 퍼센티지 즉시 갱신)·타겟 클래스 이름 변경 시 재계산·원 전부
      삭제 시 리스트 비워짐까지 31개 assertion 확인. **BUG-019 발견+즉시 수정+재검증
      통과**: `_recompute_zones()`가 `blockSignals` 없이 `_zone_list.clear()`를 호출해
      원 이동/생성마다(BUG-018과 동일 근본 원인) 캔버스↔리스트 존 하이라이트가 즉시
      사라짐(캔버스 빈 곳 클릭으로 존 선택 자체도 같은 이벤트 틱 안에서 무효화돼 사실상
      전혀 동작하지 않았음) — `ZoneCanvas.highlighted_zone()` getter 추가 +
      `_recompute_zones()`가 재구성 전 하이라이트를 저장, `blockSignals`로 감싼 재구성 후
      복원하도록 수정(BUG-018 수정과 동일 패턴). `QA.md` BUG-019 Closed로 등록. 라운드1·2
      회귀 없음(탭 5개, preset 체크포인트 자동 인스턴스화, 원 생성/조절 정상).
- [x] R4 (블랍 클릭 삭제 + 재계산, 스펙 마지막 라운드) — 구현+독립검증 통과,
      커밋 `80405fd`(feat)+`b288e82`(docs). `zone_metrics.compute_blob_labels()`
      신설 — `cv2.connectedComponentsWithStats(connectivity=8)`를 그대로 노출하는
      작은 헬퍼(`inference_engine._compute_blobs_and_filter()`의 confidence/size
      threshold 필터링은 가져오지 않음 — YAGNI). `ZoneCanvas`에 "블랍 삭제 모드"
      토글(`set_blob_delete_mode`) 추가 — 활성화 시 좌클릭이 원 편집 대신
      화면→이미지 좌표 역변환(`_screen_to_orig` 재사용) 후 라벨맵 조회→삭제
      대상 id 집합(`_removed_blob_ids`)에 추가로 해석됨(원 편집과 클릭 충돌
      방지, 스펙 "UX 흐름 상세 > 블랍 삭제"). 삭제된 블랍은 바운딩박스 반투명
      오버레이로 시각 피드백(ponytail: 정확한 픽셀 형태 아닌 근사 — 필요해지면
      QImage 합성으로 승격). 존 퍼센티지 재계산은 R3의 `zone_stats()`/
      `zones_from_circles()`를 그대로 재사용, 타겟 마스크에서
      `np.isin(labels, removed_ids)` 위치만 제외. **BUG-018/019 재발 방지
      패턴 사전 적용**: `removed_blob_ids()`/`blob_labels()` getter를
      `selected_id()`/`highlighted_zone()`과 동일하게 캔버스를 상태 단일
      출처로 두고, 오버레이 재도색에 `set_pixmap()`(내부적으로 뷰 강제
      리셋)을 쓰지 않고 캔버스 자체 `paintEvent`에 바운딩박스만 덧그리는
      방식을 택해 줌/팬 상태 리셋 위험 자체를 원천 차단.
      **검증 완료(2026-08-26, 별도 워크트리 `D:\segmentation model-zone-analysis-tab`)** —
      `python main.py`와 동일 임포트 순서로 `MainWindow` 실구동, `engine.run`/
      `refilter`를 서로 떨어진 블랍 3개(A/B/C, 손계산 가능한 합성 `raw_class_map`)로
      몽키패치해 `QTest` 실제 마우스 클릭/드래그로 골든패스 확인(총 48개 assertion,
      전부 통과): 블랍 삭제 모드 토글 ON/OFF, 배경(0) 클릭 시 무동작, 블랍 A 클릭 시
      A만 삭제, 같은 블랍 재클릭 시 무동작(idempotent), 블랍 B 추가 삭제 시 A+B
      누적 반영. 삭제 전/A만 삭제 후/A+B 삭제 후 3개 시점 모두 존 퍼센티지를
      `zone_metrics`를 거치지 않는 독립 numpy 오라클과 대조해 소수점 4자리까지
      완전 일치 확인. 줌(2.3배)·팬(11,-7) 상태를 블랍 삭제 조작 전에 강제 설정해두고
      삭제 후에도 완전히 동일하게 유지됨을 확인(`set_pixmap()` 미호출 설계가 실제로
      유효). 원 선택 상태(`selected_id`)·존 하이라이트(`highlighted_zone`)도 블랍
      삭제 조작으로 리셋되지 않음을 확인 — **BUG-018/019 패턴 3번째 재발 없음**.
      중클릭 팬이 블랍 삭제 모드 중에도 정상 동작함을 실측 확인(`super()` 라우팅
      주장 검증됨). 블랍 삭제 모드 OFF 전환 후 원 드래그 이동이 다시 정상 동작함을
      확인(회귀 없음). 타겟 클래스 재선택 시 삭제 이력 초기화+라벨맵 재계산도 확인.
      부가 회귀(별도 스크립트): 자동 검출 버튼 무크래시, non-preset 체크포인트
      코드박스 노출+Validate→Load 커스텀 모델 로드 정상. 라운드 1~3 전체 골든패스
      재확인 결과 회귀 없음. 신규 버그 발견 없음(QA.md 신규 등록 없음). 상세:
      [verification-log.md](agents/verification-log.md) 2026-08-26 라운드4 항목.

**존(Zone) 분석 탭 — 스펙 전체(R1~R4) 완료.** 배터리 캡 녹 검사용 5번째 탭이
프로젝트 시스템과 독립적으로 이미지/체크포인트 직접 로드 → 추론 → 동심원 자동
검출/수동 편집 → 존별 녹 면적 비율 계산 → 오검출 블랍 클릭 삭제 + 재계산까지
전 과정 실 GUI 골든패스로 검증 완료. **2026-08-26 사용자 확정**: 이 브랜치는 main과
독립적으로 계속 유지되는 "에디션" 브랜치로 운영 — main으로 역병합하지 않고, main의
업데이트만 sync 브랜치+PR로 주기적으로 받아온다(CLAUDE.md 8번 규칙 참고). main
병합은 개발이 다 끝나고 사용자가 별도로 결정할 때 재논의.

### 신규 기능 3건 (2026-08-26 요청, R1~R4 완료 이후)

기획 완료: [docs/specs/zone-analysis-tab-features-2026-08-26.md](specs/zone-analysis-tab-features-2026-08-26.md).
사용자 요청 3건 — ① 오프라인 원 검출 테스트 팝업(체크포인트 불필요) ② 폴더 단위 이미지
가져오기 + 일괄 처리(**사용자가 가장 중요하다고 강조**) ③ Threshold(AI 신뢰도/픽셀 크기)
조절. 코드 조사 결과 세 요청 모두 기존 인프라(`circle_detector.DetectParams`,
`inference_engine`의 `classes`/`min_confidence`/`min_pixel_size` 옵션 인자,
`InferenceImageList` 위젯, `export_blobs_to_excel` 패턴)를 그대로 재사용하면 돼 신규
검출/추론 로직이 전혀 필요 없음을 확인 — `inference_engine.py`/`circle_detector.py`는
이번 라운드에서 수정 없음.

- **2026-08-26 UI 디자인 목업 승인**(Artifact `984ea900`) — 메인 탭 좌·중·우 3분할(상단
  툴바[체크포인트/타겟클래스/AI신뢰도 슬라이더/픽셀크기/자동검출/블랍삭제모드/팝업버튼]
  + 좌측 `InferenceImageList` 패널[폴더열기/경로/검색/정렬/상태아이콘+퍼센티지배지 목록/
  배치 컨트롤] + 중앙 `ZoneCanvas` + 우측 원·존 목록) + 팝업(요청1) 구조 확정. 스펙 문서에
  반영 완료 — `InferenceImageList`에 애디티브 API 2건(상태아이콘/배지, 다중선택) 추가
  필요성이 이때 새로 확인됨(기존 "수정 없음" 판단에서 정정, `inference_tab.py` 회귀 없는
  범위로 한정). 상세는 스펙 문서 "승인된 UI 레이아웃" 절.
- **부수 발견(요청 3 관련 숨은 결함)**: `zone_analysis_tab.py`의 `_on_target_changed()`/
  `_current_target_mask()`가 존/블랍 계산에 `InferenceResult.raw_class_map`(threshold
  적용 전)을 쓰고 있어, 지금까지는 threshold가 항상 0 하드코딩이라 문제가 드러나지
  않았지만 스핀박스 UI를 추가하는 순간 "오버레이 화면은 threshold를 반영해 바뀌는데
  존 퍼센티지 숫자는 안 바뀌는" 혼란스러운 버그가 될 것 — `class_map`(threshold 적용
  후)으로 교체하는 root-cause 수정을 요청 3 라운드에 포함.
- 라운드 분할(의존관계 기준, 요청 순서와 다름 — 상세는 스펙 "라운드 분할 제안" 절):
  R-A(요청1, 팝업, 완전 독립) → R-B(요청3, threshold + root-cause 수정, 일괄 처리의
  정확성 전제) → R-C(요청2, 폴더+일괄처리, 최대 스코프, 서브스텝 3a 폴더 UI 배선/3b
  일괄처리+결과표/3c Excel 내보내기로 분할).
- `docs/decisions-needed.md` 갱신 없음 — 위임된 판단(엑셀 내보내기 포함 여부, 개별
  자동검출 결과 확인 UX 등)은 기획 문서에서 YAGNI 기준으로 직접 판단해 명시함.
- [x] R-A — 오프라인 원 검출 팝업(`circle_detect_preview_dialog.py` 신설, `ZoneCanvas`
      재사용, 툴바에 여는 버튼 추가) — 구현+독립검증 통과(2026-08-26, 커밋 `ea28b68`).
      `QTest` 실제 이벤트로 42개 assertion 전부 통과: 완전 독립성(체크포인트/이미지
      미로드 초기 상태에서도 팝업 오픈, 팝업 조작 후에도 메인탭 상태 불변 재확인 +
      메인탭에 체크포인트/이미지/추론결과가 이미 있는 상태에서도 팝업 오픈 후 닫으면
      메인탭 상태 완전 동일 유지), 골든패스(이미지 열기→자동 1차 검출→개수/소요시간
      표시→민감도 조절→다시 검출로 결과 변화→실제 마우스 드래그로 원 이동/반지름
      조절/Delete 삭제 전부 크래시 없이 정상 동작), 재오픈 시 매번 새 인스턴스로 깨끗한
      초기 상태(stale 상태 없음), 하단 닫기/우상단 ✕ 둘 다 정상 종료. R1~R4 회귀 없음
      (체크포인트 로드+추론, 자동검출, 존 리스트, 블랍삭제 모드 토글). 버그 발견 없음.
- [x] R-B — `raw_class_map`→`class_map` root-cause 수정 + Threshold UI(AI신뢰도
      `QSlider`+값라벨, 픽셀크기 `QSpinBox`) 추가 — 구현 완료(2026-08-26, 커밋
      `22c9e60`), 검증 대기. `_on_target_changed()`/`_current_target_mask()`의 마스크
      소스를 `class_map`으로 교체하고 두 컨트롤을 `_on_target_changed()`에 그대로
      연결(새 슬롯 불필요) — 상세는 `docs/agents/implementation-log.md`. 3-way
      `QSplitter`/좌측 `InferenceImageList` 패널 등 나머지 툴바 레이아웃 재편은 R-C
      스코프로 남겨둠(이번 라운드는 기존 `circle_row`에 컨트롤 2개만 승인된 순서로
      삽입). 검증 필요: 실제 GUI에서 신뢰도/픽셀크기 조절 시 존 퍼센티지·블랍 목록이
      실시간으로 바뀌는지, 원 선택/존 하이라이트 상태가 threshold 조절만으로 리셋되지
      않는지(BUG-018/019 재발 방지) 확인.
- [ ] R-C — 폴더 단위 가져오기(`InferenceImageList` 재사용) + 일괄 처리 + 결과 표시/
      Excel 내보내기(`zone_batch_result_dialog.py` 신설) — 착수 대기.

## 다음 후보
- 위 UI/UX 재편·GitHub 이슈 VOC·exe 패키징·존 분석 탭 외 추가 신규 기능 요청 없음. 새
  요청은 [docs/agents/leader-log.md](agents/leader-log.md)에 먼저 기록된 뒤 이 로드맵에
  반영된다.
