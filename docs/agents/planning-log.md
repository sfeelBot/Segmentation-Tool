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
