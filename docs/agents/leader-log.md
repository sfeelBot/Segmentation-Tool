# 리더 (Leader) 로그

역할 설명은 [README.md](README.md) 참고. 오케스트레이션 흐름(요청 → 분배 → 결과 → 외부
액션)을 기록한다. 산출물 자체가 아니라 "누가 무엇을 언제 왜 했는지" 재구성이 목적.

## 현재 상황 요약

*(append 아님 — 상황이 바뀔 때마다 이 절을 덮어쓴다)*

> **성능/버그 개선 R1~R6 전체 완료** (2026-08-19) — 전부 구현+독립검증 통과. 커밋:
> `3ce4dc9`(R1 BUG-002), `eee9b9c`(R2 지연임포트), `194430b`(R3 캔버스 캐시),
> `5ed34e9`(R4 데이터로더 캐시+num_workers), `20bb3d0`(R5 추론 다운스케일),
> `e7066b0`(R6 검색 디바운스+캐시). 상세는 [docs/roadmap.md](../roadmap.md) "성능/버그 개선"
> 절과 [docs/specs/perf-improvement-plan-2026-08-19.md](../specs/perf-improvement-plan-2026-08-19.md)
> 참고. 남은 Open 이슈: `QA.md`의 **BUG-003**(R3 검증 중 발견, P3)·**BUG-004**(R6 검증 중
> 발견, P3) — 둘 다 정상 사용 흐름에서는 발현 안 되는 경미한 항목, 별도 라운드 불필요.
> R4는 구현 에이전트가 API 세션 한도로 중단되어 리더가 최종 검증 일부를 직접 수행 후 커밋한
> 예외 케이스였음(상세: `docs/agents/implementation-log.md` R4 항목).
>
> **커스텀 서브에이전트 타입 사용 가능**: `subagent_type: planner/designer/implementer/
> verifier/deployer`가 `.claude/agents/*.md` 정의로 등록되어 실제 사용 가능(R4 검증부터
> 적용 중). `general-purpose` + 페르소나 프롬프트 우회는 더 이상 불필요.
>
> **UI/UX 재편 착수함** — 사용자가 "진행해"로 확인. 1단계(레이아웃 구조 조사) 완료 — 핵심
> 발견: 추론 탭이 3탭 중 제약이 가장 심함(우측 범례 패널 완전 고정폭 190px — QSplitter
> 안에 있는데도 고정, 좌측 이미지목록도 140~180px 제한, 체크포인트 테이블 고정높이 120px,
> 신뢰도/confidence 표시 자체가 없음). 학습 탭은 side_panel 150~220px 제한, 큐 리스트
> 고정높이 140px. 라벨링 탭이 가장 유연(좌우 자유 리사이즈)하나 내부 서브패널(이미지브라우저
> ↔ 클래스패널, 어노테이션목록 ↔ 로그패널)은 QSplitter가 아니라 고정 stretch 비율이라 세로
> 개별 리사이즈 불가. 다크테마도 추론 탭만 스플리터 hover 강조색 재정의가 빠져있어 탭간
> 불일치. **기획 완료** — `docs/specs/ui-redesign-plan-2026-08-19.md`(라운드 1~3). 중간에
> 사용자가 "추론 탭 이미지 목록에 검색/정렬/폴더 기능도 포함해줘"를 추가 요청 → 기획
> 에이전트가 재확인해 스펙에 반영(추론 탭 `_img_list`가 라벨링 탭 `ImageBrowser`와 달리
> 검색·정렬·폴더 기능이 전혀 없는 순수 QListWidget임을 확인, `ImageBrowser` 재사용은
> 기각하고 전용 경량 컴포넌트 신규 구현으로 결정 — 근거는 스펙 문서 참고). 결정 대기 4건 전부
> 사용자 확인 완료(리사이즈 상한 완전 무제한 / 신뢰도 표시 통계까지만 / ClassPanel 200px
> 같이 완화 / 추론 탭 폴더 그룹핑 트리형 채택). `docs/decisions-needed.md` 비움.
> **라운드 1(구현) + 라운드 2(디자인 목업) 병행 착수함** — 서로 다른 성격(코드 vs Artifact
> 목업)이라 동시 진행 안전. 라운드 1: 순수 상수/스타일 조정 4건(추론 탭 hover색, 학습 탭
> side_panel 상한 제거, 추론 탭 범례·이미지목록 폭 상한 제거). 라운드 2: 3탭 서브스플리터
> 전환 + 추론 탭 이미지목록 신규 컴포넌트(검색+정렬+트리형 폴더, 썸네일 그리드 포기) Artifact
> 목업 — 완료 시 사용자 승인 필요, 승인 후에만 구현 착수.
>
> **라운드 1 구현 완료, 검증 대기**: 4개 항목(추론 탭 hover색, 학습 탭 side_panel/추론 탭
> 범례·이미지목록 폭 상한 제거) 전부 수정, `minimumWidth`/`maximumWidth` 속성 조회로 무제한
> 확인, 앱 기동 정상. 커밋 `6355096`(feat)+`b567336`(docs), push 안 함. **독립 검증 통과**
> — 다른 방식(`findChildren` 순회)으로 재조회, 회귀 없음(side_panel stretch factor 0으로
> 고정돼 손실그래프 영역 영향 없음) 확인. `docs/roadmap.md` 라운드 1 체크 완료.
>
> **라운드 2 목업 완료** — Artifact: https://claude.ai/code/artifact/5df2af11-0642-4e69-8ddc-f545333eebca
> (3탭 Before/After + 추론 탭 썸네일그리드 vs 트리 확대비교). `docs/agents/design-log.md`에
> 구현 시 주의사항 기록(QTreeWidgetItem 패턴, 서브스플리터 setSizes 비율 유지, 상한제거는
> 스플리터 전환과 같은 라운드에서 함께 처리).
>
> **사용자 결정**: 목업 확인 중 "push 해줘 + 라벨링탭만 진행해줘" 지시 — 로컬에 밀려있던
> 20개 커밋 전부 `origin/main`에 push 완료(`1de27e6`→`ed24a42`). 라운드 2를 3탭 전체가
> 아니라 **라벨링 탭만**(좌/우 서브스플리터 전환 + `ClassPanel` 200px 상한 제거) 우선
> 착수 — 학습/추론 탭 라운드 2·3은 보류, 라벨링 탭 결과 확인 후 진행 여부 재확인.
>
> **라운드 2(라벨링 탭) 구현 완료 + 독립 검증 통과**: 좌/우 패널 세로 QSplitter 전환(초기
> 비율 3:2/2:3 재현, 4연속 전체화면 토글도 안정) + `ClassPanel` 200px 상한 제거(클래스 10개
> 스크롤 없이 표시 확인). 커밋 `f086636`(feat)+`9901681`(docs), push 안 함(사용자 확인 필요).
> `docs/roadmap.md` 라운드 2(라벨링 탭) 체크 완료. **학습/추론 탭 라운드 2·3은 여전히 보류**
> — 진행 여부 사용자 재확인 필요.
>
> **GitHub 이슈 VOC 접수·처리** (2026-08-20): [#1](https://github.com/sfeelBot/Segmentation-Tool/issues/1)
> "사용성 정리"(폴더정보 표시 — UI재편으로 커버됨 / CPU전용 torch 설치 문제 — 원인 파악해
> README.md·requirements.txt·USER_MANUAL.md 문서 수정으로 직접 해결, 코드 변경 아님),
> [#2](https://github.com/sfeelBot/Segmentation-Tool/issues/2) "프로젝트 내보내기 기능"
> (클릭 자동열기 — 이미 더블클릭 지원 중이라 정확한 요구 재확인 필요 / 프로젝트 전체
> 내보내기·단일파일 통합 — 신규 기능, `export_dialog.py`는 라벨데이터 export만 지원해서
> 겹치지 않음). `QA.md` VOC 테이블에 4건 전부 기록. CUDA 설치 가이드는 리더가 직접 수정
(README.md/requirements.txt/USER_MANUAL.md) 완료·커밋. 라운드2(라벨링탭) 독립 검증도
통과(4연속 전체화면 토글 안정, 클래스 10개 스크롤 없이 표시).
>
> **GitHub #2 기획 완료** — `docs/specs/voc-github-issues-2026-08-20.md`. 요청1(자동열기)은
> 이미 더블클릭으로 지원되고 다른 번거로운 흐름도 없음을 코드로 확인 — 싱글클릭을 원하는
> 명시적 요구인지 단순 미인지인지 이슈 원문만으론 판별 불가라 결정 대기 등록. 요청2(내보내기)는
> 라운드 A(export, zip 패키징)+라운드 B(import, 더 리스크 큼 — A 완료 후 착수) 2라운드로
> 스코프 산정. `decisions-needed.md`에 3건(싱글클릭 여부/체크박스 기본값/import 착수 여부)
> 등록됨 — 아직 사용자 확인 전.
>
> **신규 요청 접수 — exe 패키징 + Setup Guide** (2026-08-20, "추후" 착수): CLAUDE.md에 이미
> "PyInstaller 등 실행파일 패키징/배포는 범위 밖(별도 논의)"로 명시돼 있어 지금 바로 착수하지
> 않고 `docs/roadmap.md`에 배경(torch/CUDA 런타임 번들링 난제, Setup Guide는 USER_MANUAL.md와
> 성격이 다름)과 함께 기록만 해둠. 사용자에게 착수 시점 확인 필요.
>
> **GitHub #2 결정 3건 확인 완료 (2026-08-20) — 요청1 대폭 정정**: 사용자가 "요청1은 최근
> 프로젝트 목록 클릭 얘기가 아니라, 전용 프로젝트 확장자를 만들어 OS에서 더블클릭하면 앱이
> 바로 열리게 해달라는 뜻"이라고 정정 — 애초 기획 판단(싱글/더블클릭 문제)이 틀렸었음. Windows
> 파일 연결은 설치 프로그램이 처리하는 게 정석이라 **exe 패키징(추후) 항목에 하위 요구사항으로
> 편입**, 별도 라운드로 잡지 않음. 요청2는 **export(라운드A)+import(라운드B) 둘 다 이번에
> 진행 확정**(체크포인트 기본 미체크/user_models 기본 체크, import 이름충돌은 자동 리네임으로
> 리더가 안전 기본값 채택). `docs/specs/voc-github-issues-2026-08-20.md`/`docs/roadmap.md`/
> `QA.md`/`docs/decisions-needed.md` 전부 반영. **라운드 A 구현 착수** — 목업 불필요(기존
> export_dialog.py/_FolderImportWorker 패턴 재사용), A 검증 통과 후 곧바로 B로 이어감.
>
> **라운드 A(내보내기) 구현 완료, 검증 대기**: `app/core/project_export.py`(Qt 비의존 순수
> 로직) + `app/widgets/project_export_dialog.py`(`ProjectExportDialog`+`_ProjectExportWorker`)
> 신규, `project_start_dialog.py` 우클릭 메뉴 진입점 추가, `i18n.py` 키 추가. 합성 프로젝트로
> `.thumbs/` 제외, 체크박스별 포함/제외, 500파일 대용량 progress 논블로킹, 에러 케이스 2건
> 확인. 커밋 `911f85a`(feat)+`d42fe46`(docs), push 안 함. 독립 검증 위임 예정 — 통과 시
> 라운드 B(가져오기)로 이어감.
>
> **미해결 결정 대기 없음**(`docs/decisions-needed.md` 비어있음). 커밋은 전부 로컬에만 있고
> `git push` 안 함(사용자가 "push는 진행하지 말고" 확인한 상태 — origin/main은 여전히
> `1de27e6`까지만 반영, 로컬 main은 그 뒤로 8개 커밋 앞섬).

- **원격 저장소 연결 완료**: `https://github.com/sfeelBot/Segmentation-Tool.git` (public,
  기본 브랜치 `main`). 로컬 `master` → `main` 리네임 후 원격의 초기 README 커밋과
  `--allow-unrelated-histories` 병합, `git push -u origin main` 완료 (commit `7a6ce3c`).
- **Harness Engineering 운영 모델 이식 및 커밋 완료**: `.claude/agents/*.md` 서브에이전트
  정의, `docs/roadmap.md`, `docs/decisions-needed.md` 신설, 기존 `docs/agents/*.md` 로그를
  `*-log.md` 명명 규칙으로 정리 — commit `613edb2`(docs 스캐폴드), `e195037`(nok 라벨링
  데이터 별도 커밋), `origin main`에 push 완료.
- **성능 병목 검증 완료**: 검증 서브에이전트(general-purpose, `.claude/agents/verifier.md`
  페르소나)가 `projects/nok/` 실데이터로 벤치마크 실행. 성능 항목 7개(#2~#8, 심각도 P1~P3)
  + 성능과 무관한 심각 버그 1건(**BUG-002, P0** — 브러시 마스크 저장 시 전량 유실,
  `annotation_store.rle_encode()` 언더플로우) 발견. `QA.md`, `docs/agents/verification-log.md`
  기록 완료.
- **개선 계획 수립 완료**: 기획 서브에이전트가 [docs/specs/perf-improvement-plan-2026-08-19.md](../specs/perf-improvement-plan-2026-08-19.md)
  작성. BUG-002(데이터 유실)를 R1 단독 최우선 배치, 나머지 성능 항목은 R2~R6 6개 라운드로
  구성. `docs/roadmap.md` "성능/버그 개선" 절에 체크박스 반영됨.
- **트레이드오프 3건 모두 확인 완료** (2026-08-19): R2 DLL 리스크 감수하고 지연 임포트 진행 /
  R4 `num_workers` 자동 감지(CPU 코어 수 기반) / R5 화면 미리보기만 2048 상한, 저장·내보내기는
  원본 해상도 유지. `docs/decisions-needed.md` 비움, 결과는
  [docs/specs/perf-improvement-plan-2026-08-19.md](../specs/perf-improvement-plan-2026-08-19.md)
  "트레이드오프 결정" 절에 기록.
- **R1(BUG-002) 완료 + 독립 검증 통과**: 구현(`3ce4dc9`) → 검증 에이전트가 별도 재현
  스크립트(9개 케이스, 구현자 스크립트 미재사용)로 재확인 + 앱 기동(QApplication→nok 프로젝트
  오픈→MainWindow 생성) 성공 + nok 실제 polygon 어노테이션 5개 무영향 확인. 최종 판정
  **"R1 통과, R2 착수 가능"**. 단, 이 자동화 환경은 `app.exec()` 이벤트 루프 완주는 확인 못 함
  (R1 변경분이 이벤트 루프와 무관한 순수 함수라 회귀로 보진 않음) — 사용자가 직접 앱을 켜서
  브러시 저장을 한 번 육안 확인하면 더 확실함.
- **R2(콜드 임포트 지연로딩) 구현 완료, 검증 대기**: 9개 파일 수정(main.py + core 4개 +
  model_presets 3개, 후자는 이미 exec() 구조라 사실상 무영향으로 확인됨), 커밋 `eee9b9c`,
  push 안 함. 실측: `app.main_window` import 완료까지 3.3s → 1.852s(약 44% 단축), 시점에
  torchvision/albumentations `sys.modules` 없음 확인. 기능 단위 검증(dataset/augmentations/
  inference/presets)은 nok 데이터로 통과. **미확인**: 다른 Windows/Anaconda 조합에서 DLL
  재발 여부(이 세션에서는 재현 안 됐지만 다른 환경 테스트는 못 함), 대화형 세션에서 실제
  학습 탭 진입 육안 확인. **독립 검증 통과** — 검증 에이전트가 별도 스크립트로 재현(다른
  입력값), `torch`가 항상 `torchvision`보다 먼저 로드되는 구조적 보장 확인, model_presets
  exec-only 주장도 `model_loader.py`/`model_presets/__init__.py` 코드로 재확인. 최종 판정
  **"R2 통과, R3 착수 가능"**.
- **R3(annotation_canvas 이미지 캐시 + bbox fallback) 구현 완료, 검증 대기**: LRU 2장 캐시
  (파생 상태 전부 포함, mtime 무효화) — 재방문 80ms→7.5ms(~10.7배). bbox fallback — 스켈레톤
  결과 동일성 확인, 43ms대 스파이크 케이스 280ms→54.8ms(~5.1배, 합성 케이스라 실측 스케일은
  다를 수 있음). 커밋 `194430b`, push 안 함. R1(rle_encode)과 상호작용 없음 확인.
  **잔여 우려**: `_translate_selected()`(Select 도구로 어노테이션을 캔버스 밖으로 드래그)가
  이론상 전량 0인 빈 brush_mask를 만들 수 있는데, 예전 코드는 항상 전체 스캔이라 다음 브러시
  스트로크 때 우연히 자가 치유됐지만 이번 최적화로 더는 안 잡힐 수 있음 — 기존부터 있던 갭이고
  이번 변경이 만든 버그는 아님. **검증 결과: 독립 재현 후 P3로 판단**(zombie는
  `annotation_store.save()`의 기존 `mask.any()` 필터에서 이미 걸러져 디스크에 저장되지
  않음 — 데이터 유실/손상 없음, 이미지 전환 시 자동 해소). `QA.md`에 **BUG-003(P3, Open)**로
  등록, R3는 통과 처리. 최종 판정 **"R3 통과, R4 착수 가능"**.
- **R4(#3 학습 데이터로더 캐시 + num_workers 자동감지) 착수 중** — 스펙상 가장 리스크 큰
  라운드(Windows spawn 멀티프로세싱, Albumentations pickle 가능 여부).
- **신규 요청 접수 — UI/UX 재편(학습/추론/라벨링 탭)**: 레이아웃+시각 스타일 재편. 사용자가
  짚은 불편: "레이아웃별 움직일 수 없고 정보 부족". **성능 라운드(R3~R6)와 대상 파일이 겹쳐
  순서를 성능 먼저로 결정** — R3~R6 전부 끝난 뒤 디자인 착수. `docs/roadmap.md`에 블로커
  명시해 반영함. 현재 R4 진행 중.
- (배경 기록) R2 위임 전 리더가 직접 import 체인을 확인해 스펙 가정("main.py만 고치면 됨")이
  불충분함을 발견 — `main_window.py`의 4개 탭 top-level import 체인을 따라가면 7개 파일이
  모듈 로드 시점에 이미 torchvision/albumentations를 import하고 있었음. 이 분석을 구현
  에이전트 프롬프트에 포함해 반영시킴 — 실제 결과는 위 R2 항목 참고.

---

## 2026-08-19

| 요청 원문 | 상태 | 비고 |
|-----------|------|------|
| "현재 폴더의 정보를 읽어서 어떤 작업을 하고 있었는지 파악해" | 완료 | [planning-log.md](planning-log.md) 참고 |
| "너는 기획 agent, 구현 agent, 검증agent, 디자인 agent로 나누어서 작업하고, 각 에이전트들은 각 md 파일로 기록하며 작업할 수 있도록 해" | 완료 | `docs/agents/` 워크플로우 최초 구축 |
| "해당 깃허브 주소에 연결할 수있도록 해줘. public저장소야" (https://github.com/sfeelBot/Segmentation-Tool) | 완료 | 리더가 직접 처리(배포 서브에이전트 미도입 상태였음) — remote 추가 → `master`→`main` 리네임 → `--allow-unrelated-histories` 병합 → `git push -u origin main` (`7a6ce3c`) |
| "리더 에이전트도 만들어서 md파일로 사용자 요청사항들을 적을 수 있도록 해" | 완료 | `leader.md` 최초 신설 (이후 `leader-log.md`로 이름 정리) |
| (다른 프로젝트 CLAUDE.md의 Harness Engineering 절 붙여넣고) "지금 상황에 맞는 부분만 가져와서 claude.md 에 업데이트해" | 완료 | 모바일(iOS/Android, 스토어 제출) 특화 항목 제외하고 이식 — 리더 규칙/워크플로우/로그 규칙/역할 표를 CLAUDE.md에 반영, `.claude/agents/*.md` 페르소나 5종 신설, `docs/roadmap.md`·`docs/decisions-needed.md` 신설, 기존 로그 파일 `*-log.md`로 리네임 |
| "커밋하고 push해줘" | 완료 | 의미 단위로 커밋 분리 — `613edb2`(docs: Harness Engineering 스캐폴드), `e195037`(chore: nok 라벨링 데이터). `docs/decisions-needed.md`의 커밋 여부 항목 삭제(결정 완료). `git push`로 `origin/main` 반영. |
| "현재 여러 항목에서 병목 현상이 있어. 병목 현상들을 에이전트가 테스트하면서 확인해보고 리스트업한다음 개선계획을 짜줘." + "이미지가 개당 50mb 정도의 무거운 이미지야. 염두해줘" | 완료 | 검증 서브에이전트(nok 실데이터) → 병목 7건 + BUG-002(P0) 발견 → 기획 서브에이전트 위임 → `docs/specs/perf-improvement-plan-2026-08-19.md`(R1~R6) 작성 → 트레이드오프 3건(R2/R4/R5) 사용자 확인 완료. |
| "구현 시작해" | 완료 | R1(`3ce4dc9`)→검증 통과 → R2(`eee9b9c`)→검증 통과 → R3(`194430b`)→검증 통과(BUG-003 P3 등록) → R4(`5ed34e9`, 구현 에이전트 세션 한도로 중단 → 리더가 직접 마무리 후 커밋)→검증 통과 → R5(`20bb3d0`)→검증 통과 → R6(`e7066b0`, 마지막 라운드)→검증 통과(BUG-004 P3 등록). **R1~R6 전체 완료.** `docs/roadmap.md` 체크박스 전부 갱신. |
| "학습탭과 추론탭 부분 디자인 전체적으로 사용자 편의성을 생각해서 재편해줘. 라벨링 탭 부분도 사용성 생각해서 디자인 변경" | 진행중 | 대상 파일이 R3~R4~R5와 겹쳐 순서 확인 → 사용자가 "성능 먼저" 결정. R1~R6 완료로 블로커 해소 → "진행해" 확인 → Explore(레이아웃 조사) → 기획(스펙 작성, 라운드1~3) |
| "진행해" | 진행중 | 위 항목 이어서 — Explore 조사 → 기획 에이전트 스펙 수립 |
| "이미지 로드하고 그랫을때 정보량이 부족해 폴더 sort 기능, 등등등 검색기능도 포함해줘." | 완료 | 추론 탭 이미지 목록(`_img_list`)에 검색/정렬/폴더 기능이 아예 없음을 확인 → 기획 에이전트에게 재위임(SendMessage로 진행 중이던 에이전트 재개) → 스펙에 반영(전용 경량 컴포넌트, `ImageBrowser` 재사용 기각) → 4건 결정 대기 등록 → 사용자 확인(AskUserQuestion) 전부 완료 → `docs/specs/ui-redesign-plan-2026-08-19.md`/`docs/roadmap.md`/`docs/decisions-needed.md` 반영 완료. 다음: 라운드 1 구현 + 라운드 2 디자인 목업 병행 착수. |
| (목업 확인 중 인터럽트) "진행하기 전에 push 해줘고 라벨링탭만 진행해줘" | 완료 | `origin/main`에 20개 커밋 push(`1de27e6`→`ed24a42`) → 라운드 2를 라벨링 탭으로 좁혀 구현(`f086636`) → 검증 1차 시도 세션한도 실패 → 재시도로 검증 통과. `docs/roadmap.md` 체크 완료. 학습/추론 탭은 계속 보류. |
| "이어서 진행해줘. 추가로 github issue에 몇가지 VOC 들이 있어 해당 VOC 확인 후 업데이트에 반영해" | 완료 | GitHub #1·#2 이슈 확인(WebFetch) → `QA.md` VOC 테이블 4건 등록 → CPU전용 torch 설치 문제는 원인 파악해 리더가 직접 문서 수정(`README.md`/`requirements.txt`/`USER_MANUAL.md`)으로 해결 → 폴더정보 표시 요청은 기존 UI재편 계획으로 커버 확인 → 프로젝트 내보내기/자동열기 2건은 기획 완료(`docs/specs/voc-github-issues-2026-08-20.md`), 결정 대기 3건 등록. 라운드2(라벨링탭) 독립검증도 통과. |
| "추후에는 py파일로 실행이 아닌 exe 파일로 실행하게 하고 싶어. setup guide 관련된 문서도 필요할거야. 참고해줘." | 대기 | CLAUDE.md에 이미 "PyInstaller 등 범위 밖, 별도 논의" 명시돼있어 즉시 착수 안 함 — `docs/roadmap.md`에 배경과 함께 기록만. 착수 시점 사용자 확인 필요. |
