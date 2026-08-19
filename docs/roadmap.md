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

## 다음 후보
- 사용자로부터 접수된 신규 기능 요청 없음 (2026-08-19 기준). 새 요청은
  [docs/agents/leader-log.md](agents/leader-log.md)에 먼저 기록된 뒤 이 로드맵에 반영된다.
