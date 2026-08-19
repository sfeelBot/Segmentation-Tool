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
