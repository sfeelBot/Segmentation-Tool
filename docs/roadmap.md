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

- [ ] R1 — BUG-002: `annotation_store.rle_encode()` uint8 언더플로우로 brush_mask 전량 유실 (P0, 구현 대기)
- [ ] R2 — #2: `main.py` 콜드 임포트 지연로딩 (기동 ~3.3초, P1, 구현 대기 — DLL 리스크 감수하고 진행 결정됨)
- [ ] R3 — #4 + #7: `annotation_canvas.py` 이미지 캐시 + bbox fallback 스캔 축소 (P2/P3, 구현 대기)
- [ ] R4 — #3: 학습 데이터로더 캐시 + `num_workers` 기본값 (P1, 구현 대기 — 기본값을 CPU 코어 수 기반 자동 감지로 결정됨)
- [ ] R5 — #5: `inference_engine._colorize_and_blend()` 다운스케일 (P2, 구현 대기 — 화면 미리보기만 2048 상한, 저장/내보내기는 원본 해상도 유지로 결정됨)
- [ ] R6 — #6 + #8: `image_browser` 검색 디바운스 + `auto_labeler` 중복 read 제거 (P2/P3, 정적 분석만 — 구현 대기, 재검증 조건부)

## UI/UX 재편 — 학습·추론·라벨링 탭 (2026-08-19 요청, 성능 개선 완료 후 착수)

- 범위: 레이아웃 + 시각 스타일 모두. 대상: `training_tab.py`, `inference_tab.py`,
  `labeling_tab.py`(+ `annotation_canvas.py`, `config_form.py`, `overlay_viewer.py` 등 관련 위젯).
- 사용자가 짚은 구체적 불편: **"레이아웃별 움직일 수 없고 각종 정보들이 부족"** — 위젯
  배치가 고정적(리사이즈/재배치 불가)이고, 화면에 표시되는 정보가 부족함. 그 외 세부는
  디자인 에이전트가 코드 + 기존 기능 목록을 감사해 자체 제안.
- **성능 개선(R3~R6)과 대상 파일이 겹쳐 순서를 성능 먼저로 결정** — R3~R6 전부 완료·검증
  통과한 뒤 착수한다 (파일 충돌 방지).
- [ ] 착수 대기 (블로커: R3~R6 완료)

## 다음 후보
- 위 UI/UX 재편 외 추가 신규 기능 요청 없음 (2026-08-19 기준). 새 요청은
  [docs/agents/leader-log.md](agents/leader-log.md)에 먼저 기록된 뒤 이 로드맵에 반영된다.
