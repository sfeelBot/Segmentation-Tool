# Harness Engineering — 리더 + 서브에이전트 워크플로우

이 프로젝트는 리더(메인 세션) + 서브에이전트 체계로 운영한다. 자세한 리더 규칙·워크플로우
순서는 [CLAUDE.md](../../CLAUDE.md)의 "운영 방식: Harness Engineering" 절 참고. 이 폴더는
각 역할의 append-only 작업 로그를 보관한다 (코드/문서 산출물 자체가 아니라 "무엇을 언제 왜
했는지"의 기록).

## 역할 · 정의 파일 · 로그 파일 · 산출물

| 역할 | 정의 파일 | 로그 파일 | 산출물 위치 |
|---|---|---|---|
| 리더 (Leader) | (메인 세션, 정의 파일 없음) | [leader-log.md](leader-log.md) | — (오케스트레이션 기록) |
| 기획 (Planning) | `.claude/agents/planner.md` | [planning-log.md](planning-log.md) | [docs/roadmap.md](../roadmap.md) |
| 스파이크 (Spike, 선행검증·필요 시에만) | `.claude/agents/spiker.md` | `spike-log.md` (필요 시 생성) | 관련 조사 문서 |
| 디자인 (Design) | `.claude/agents/designer.md` | [design-log.md](design-log.md) | UI 목업 / Artifact |
| 구현 (Implementation) | `.claude/agents/implementer.md` | [implementation-log.md](implementation-log.md) | (코드) |
| 검증 (Verification) | `.claude/agents/verifier.md` | [verification-log.md](verification-log.md) | [QA.md](../../QA.md) |
| 배포 (Deployment) | `.claude/agents/deployer.md` | `deployment-log.md` (필요 시 생성) | [docs/CHANGELOG.md](../CHANGELOG.md), git tag |

## 로그 규칙

- 각 역할은 작업 시작/종료 시 자기 로그 파일에 **날짜, 작업 요약, 상태(진행중/완료/블로커)**를
  추가한다. **append-only** — 기존 내용을 삭제하거나 고쳐쓰지 않는다.
- 예외: [leader-log.md](leader-log.md) 맨 위 "현재 상황 요약" 절은 append가 아니라 상황이
  바뀔 때마다 덮어쓰는 살아있는 요약이다. 그 아래 날짜별 로그는 append-only 그대로.
- 같은 성격의 살아있는 문서로 [docs/decisions-needed.md](../decisions-needed.md)(사용자 결정
  대기 목록)와 [docs/roadmap.md](../roadmap.md)(기능별 진행 상태)가 있다 — 둘 다 append-only가
  아니라 최신 상태로 덮어쓴다.

## 워크플로우 순서

리더 → 기획 → 구현 + 디자인(병행) → 검증 → 배포. 상세 규칙은 CLAUDE.md 참고.
