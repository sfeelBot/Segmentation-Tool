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
- [x] 폴더 접기/펼치기 그룹 헤더 (QTreeWidget 마이그레이션)
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
      폴더 정보 표시 요청 중 라벨링 탭 쪽은 기존부터 지원(이번 변경과 무관하게 이미 충족).
- [ ] 라운드 2 — 학습 탭 큐 영역 서브스플리터 (보류, 사용자 재확인 필요)
- [ ] 라운드 2 — 추론 탭 상단↔뷰어 서브스플리터 + 이미지 목록 검색/정렬/트리형 폴더 신규
      (보류, 사용자 재확인 필요 — [GitHub #1](https://github.com/sfeelBot/Segmentation-Tool/issues/1)
      폴더 정보 표시 요청과 직결)
- [ ] 라운드 3 — 정보 추가 (디자인 목업 필요, 중~고리스크 — `annotation_canvas.py`,
      `inference_engine.py` 최소 침습 패치 포함, 아직 미착수)
- 다음 단계: 라벨링 탭 라운드 2 구현 → 검증 → 통과 후 학습/추론 탭 진행 여부 사용자 재확인.

## GitHub 이슈 VOC (2026-08-20 접수)

- [GitHub #1](https://github.com/sfeelBot/Segmentation-Tool/issues/1) "사용성 정리"
  - ① 라벨링/추론 이미지 탭 폴더 정보 표시 — 위 "UI/UX 재편" 절에서 커버(라벨링 탭은 완료,
    추론 탭은 라운드 2 보류분).
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
  - [ ] 라운드 B(import) — 구현 착수 가능

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

## 다음 후보
- 위 UI/UX 재편·GitHub 이슈 VOC·exe 패키징 외 추가 신규 기능 요청 없음. 새 요청은
  [docs/agents/leader-log.md](agents/leader-log.md)에 먼저 기록된 뒤 이 로드맵에 반영된다.
