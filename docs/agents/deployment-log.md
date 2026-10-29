# 배포 (Deployment) 로그

역할 설명은 [README.md](README.md) 참고. append-only — 최신 항목이 아래에 추가된다.

---

## 2026-08-24 — v1.7.0 (Windows 인스톨러 최초 배포 + 누적 161커밋 릴리즈)

### 배경
- 사용자 요청: "github에 installer 빌드된 것까지 포함해서 올려줘."
- `v1.6.0` 태그(2026-05-16, 커밋 `43fad19`) 이후 161커밋 동안 버전 태깅이 누락된 채
  기능 추가·GitHub 이슈 대응·성능 개선·UI 재편·Windows exe/installer 빌드 도구가
  누적됨. 이번 배포에서 이를 한 번에 정리.
- 인스톨러 exe(1.9GB, PyInstaller onedir + CUDA torch 포함)는 GitHub 100MB/파일 제한과
  Git LFS public repo 1GB 무료 한도를 모두 초과 → git 커밋 대상에서 제외
  (`installer/output/`은 `.gitignore`에 이미 등록돼 있음, 의도된 것), GitHub Releases로만 배포.

### 조치
- `git log v1.6.0..HEAD --oneline` 161커밋 검토 → MAJOR급(핵심 아키텍처 변경) 없음, 전부
  기능 추가/성능/버그 수정/UI 조정 → MINOR 판단, `v1.7.0` 채택.
- `installer/setup.iss`: `MyAppVersion "1.6.0"` → `"1.7.0"`.
- 기존 `dist\SegmentationModelUI\`(빌드 시각이 최신 코드 커밋보다 앞서지만, 그 사이 커밋은
  docs 전용이라 앱 내용 무관 확인) 재사용, Inno Setup(`ISCC.exe`)만 재컴파일 →
  `installer/output/SegmentationModelUI-Setup-1.7.0.exe` (1,911,950,852 bytes) 생성.
- `docs/CHANGELOG.md`에 `[v1.7.0] 2026-08-24` 섹션 추가 (빌드 도구/로고, UI 재편,
  GitHub 이슈 대응, 디자인 톤 정리, 성능/버그 수정 그룹핑 요약).
- 커밋 `c1d8668` (`chore: v1.7.0 릴리즈 준비 — 인스톨러 버전 갱신 + CHANGELOG 누적 반영`).
- 태그 `v1.7.0` (annotate, 커밋 `c1d8668` 대상).
- `git push origin main` + `git push origin v1.7.0` — 사용자가 이번 요청에서 명시적으로
  "github에 올려줘"라고 push를 승인한 상태였으므로 진행.

### 블로커 — GitHub Release 미생성
- `gh` CLI가 이 환경에 설치돼 있지 않음 (`where gh`, PowerShell `Get-Command gh`, winget
  목록 모두 확인 — 미설치). 인증 정보를 임의로 만들거나 무단으로 CLI를 설치하지 않고 중단.
- 남은 작업: `gh` 설치·인증 후
  `gh release create v1.7.0 "installer\output\SegmentationModelUI-Setup-1.7.0.exe" --title "v1.7.0" --notes-file <CHANGELOG v1.7.0 섹션>`
  로 릴리즈 생성 + exe 첨부 필요. 사용자/리더 확인 후 재개.

### 결과 요약
- 버전: v1.7.0
- 커밋: `c1d8668d6c55fe90087493ea3ffee92070042ced` (origin/main에 push 완료)
- 태그: `v1.7.0` (origin에 push 완료)
- GitHub Release: 미완료 (gh CLI 부재)

---

## 2026-08-25 — v1.8.0 (어노테이션 가져오기 + 모델 프리셋 3종, exe/installer 전체 재빌드)

### 배경
- 사용자 요청: "v1.7.0 이후 13커밋이 쌓였다. 새 버전으로 태깅하고, exe/installer를 처음부터
  다시 빌드해서 GitHub Release로 업데이트해줘." (installer 부분도 명시적으로 재빌드 요청)
- `v1.7.0` 이후 13커밋 검토(`git log v1.7.0..HEAD`) → 어노테이션 가져오기(Import),
  SegFormer/SegNeXt/PIDNet 프리셋 등 신규 기능 2건 + 줌/브러시 버그 수정 3건. MAJOR급
  (핵심 아키텍처 변경) 없음 → MINOR 판단, `v1.8.0` 채택.

### 조치
- `installer/setup.iss`: `MyAppVersion "1.7.0"` → `"1.8.0"`.
- `docs/CHANGELOG.md`에 `[v1.8.0] 2026-08-25` 섹션 추가.
- 커밋 `faa533a` (`docs: v1.8.0 릴리즈 준비 — 인스톨러 버전 갱신 + CHANGELOG 반영`).
- 태그 `v1.8.0` (annotate, 커밋 `faa533a` 대상).
- **exe/installer 전체 재빌드** (앱 코드 자체가 크게 바뀌어 dist 재사용 불가 — 모델 프리셋
  신규 패키지, import_dialog.py 신규):
  - `build.bat`(`cmd.exe /c build.bat`)을 그대로 실행 시도 → **실패**: Git Bash(MSYS) 레이어가
    `/c` 스위치를 POSIX 경로로 오인식해 변환(`MSYS_NO_PATHCONV` 지정 여부와 무관하게 재현),
    cmd.exe가 배치 파일을 못 찾거나 인터랙티브 세션으로 진입해 아무 것도 실행되지 않음
    (exit code는 0으로 위장되어 최초 1회는 "성공"으로 오판할 뻔함 — dist/ 산출물 mtime을
    대조해 미실행을 확인).
  - 우회: `build.bat`을 거치지 않고 `py -3 -m PyInstaller build.spec`과 Inno Setup
    `ISCC.exe installer\setup.iss`를 각각 직접 실행 (v1.7.0 배포 때와 동일한 우회 패턴).
    `dist/`, `build/`는 사전에 수동으로 `rm -rf`.
  - PyInstaller onedir 빌드 성공 (`dist\SegmentationModelUI\SegmentationModelUI.exe`,
    Aug 25 11:08 새로 생성 확인) → Inno Setup 컴파일 성공(541초) →
    `installer\output\SegmentationModelUI-Setup-1.8.0.exe` (1,946,367,450 bytes).
  - 빌드된 exe(`dist\SegmentationModelUI\SegmentationModelUI.exe`)를 직접 실행해 스모크
    테스트: 프로세스 정상 기동, 창 응답(`Responding: True`), 크래시 없음 확인 후 종료.
    콘솔에 `UnicodeEncodeError`(cp949 콘솔 코드페이지가 로그 메시지의 em-dash `—`를
    인코딩 못함) 스택트레이스가 다수 출력됐으나, Python `logging` 모듈이 내부적으로 잡아
    처리하는 비치명적 경고이며 실제 크래시로 이어지지 않음 — 신규 회귀 아님(기존 로그
    포맷 이슈, 별도 대응 필요 시 사용자/리더에게 보고).
- `git push origin main` + `git push origin v1.8.0` — 사용자가 이번 요청에서 명시적으로
  "GitHub Release로 업데이트해줘"라고 push를 승인한 상태였으므로 진행.
- `gh release create v1.8.0 installer/output/SegmentationModelUI-Setup-1.8.0.exe --title v1.8.0 --notes-file <CHANGELOG v1.8.0 섹션>` 로 릴리즈 생성 + exe(1.9GB) 첨부 완료
  (`gh auth status` 확인 결과 `sfeellee-collab` 계정으로 이미 인증·write 권한 보유).

### D: 드라이브 용량
- 빌드 전 `Get-PSDrive D` 확인: 25.8GB 여유 (391GB 중 367GB 사용, 94%) — 지난 라운드
  부족 사례와 달리 이번엔 충분해 별도 정리 없이 진행.

### 결과 요약
- 버전: v1.8.0
- 커밋: `faa533a70817ccd110a2184467d47045cedcc9d3` (origin/main에 push 완료)
- 태그: `v1.8.0` (`02e4d6872ca5a471956f82dd8cc16eb168a1dc02`, origin에 push 완료)
- GitHub Release: https://github.com/sfeelBot/Segmentation-Tool/releases/tag/v1.8.0
  (installer exe 1,946,367,450 bytes 첨부 완료)
- exe 스모크 테스트: 정상 기동·응답, 크래시 없음 확인
- 알려진 이슈(신규 회귀 아님): 콘솔(cp949) 실행 시 로그 핸들러가 em-dash 문자를
  인코딩 못해 `UnicodeEncodeError`를 반복 출력 — 기능에는 영향 없음, 필요 시 로그
  포매터를 UTF-8 강제 또는 ASCII 대체 문자로 교체하는 별도 이슈로 논의 필요

---

## 2026-08-27 — v1.9.0 릴리스 준비

- 상태: 진행 중
- 사용자 요청에 따라 main 버전을 `1.8.0`에서 `1.9.0`으로 갱신하고 CHANGELOG에
  v1.8.0 이후 기능·수정 내역을 정리함.
- 범위는 버전 메타데이터 생성·검증, 릴리스 커밋·annotated tag·push까지이며 전체
  PyInstaller/Inno Setup 패키징과 GitHub Release 업로드는 포함하지 않음.
- 검증 완료: 메타데이터 생성 성공, `tests/test_build_release.py` 20 passed.

## 2026-08-27 — zone-v1.1.0 릴리스 준비

- 상태: 진행 중
- zone 버전을 `1.0.0`에서 `1.1.0`으로 갱신하고 main 기능 기준을
  `v1.8.0 + 19 commits`의 `09933fd`로 기록함.
- zone 전용 제품명·EXE·설치 폴더·AppId와 `zone-v` 태그 체계를 유지함.
- `zone-v1.0.0`은 기존 논리적 기준 버전이며 Git 태그 이력에는 없음을 확인함.
- 범위는 메타데이터 생성·검증, 릴리스 커밋·annotated tag·push까지이며 전체 설치
  패키지 생성과 GitHub Release 업로드는 포함하지 않음.
- 검증 완료: 메타데이터 생성 성공, build 릴리스 테스트 34 passed, zone #13/#14
  직접 테스트 통과.

## 2026-08-28 — zone-v1.2.4 배포

- 상태: 배포 승인 및 검증 PASS, 전용 sync PR을 통한 `feature/zone-analysis-tab` 병합과 annotated tag `zone-v1.2.4` 생성 예정.
- 내용: main의 Python 3.12 빌드 venv 자동 준비 및 잘못된 기존 venv 자동 재생성 수정을 zone에 반영.
- 검증: zone build/release 테스트 41 passed 및 zone 전용 검사 통과.
- 제외: 실제 PyInstaller/Inno Setup installer 생성 및 GitHub Release 업로드는 수행하지 않음.

---

## 2026-10-27 — v1.11.0(main) + zone-v1.6.3(존분석 에디션) push, sync PR #37 자동머지

### 배경
- 사용자가 "검증 통과한 두 브랜치 작업을 전부 push" 하라고 명시적으로 확인.
- 범위: main 태깅+push, main→존분석 에디션 브랜치 sync PR, 존분석 에디션 브랜치
  자체 버전 점검+태깅+push. installer/exe 패키징·배포는 범위 밖(별도 논의).

### 조치 — main (`d:/segmentation model`)
- `git fetch origin` 후 `merge-base HEAD origin/main` == `origin/main` 현재 tip(`b9dd6be`)
  확인 → 로컬이 origin/main보다 7커밋 앞섬, divergence 없음 → push 안전 판단.
- `release.ini`/`docs/CHANGELOG.md`는 구현 에이전트가 이미 1.11.0으로 갱신해둔 상태
  (내용 확인만, 추가 변경 없음).
- `git tag -a v1.11.0`(대상 커밋 `7bd280e`) — CHANGELOG `[v1.11.0]` 섹션 요약을 태그
  메시지로 사용.
- `git push origin main` (`b9dd6be..7bd280e`) + `git push origin v1.11.0` 완료.

### 조치 — sync 브랜치 + PR (main → 존분석 에디션)
- 기존 로컬 브랜치 `sync/main-into-zone-analysis-tab-20261027`(main에서 분기, 미push
  상태)를 `git push -u origin`으로 push.
- `gh pr create --base feature/zone-analysis-tab --head sync/main-into-zone-analysis-tab-20261027`
  로 PR #37 생성(본문에 v1.11.0 변경 요약 + sync 필요 이유 기재).

### 조치 — 존분석 에디션 브랜치 (`D:/segmentation model-zone-analysis-tab`)
- `git fetch origin` 후 `merge-base --is-ancestor origin/feature/zone-analysis-tab HEAD`
  확인 → origin이 그 사이 움직이지 않음, divergence 없음 → push 안전 판단(1차: push
  전, 2차: 커밋/태그 생성 후 재확인 — 두 번 모두 안전 확인).
- 버전 점검: `release.ini` `version = 1.6.2`(이미 `zone-v1.6.2`로 릴리즈됨 확인) →
  이번 변경(main sync 반영 + Zone/R분석 탭 편집 툴바를 공유 `BrushToolbar`로 교체,
  기능 동작 보존·R분석 undo UI 위치만 버튼→액션으로 소폭 변경)은 호환 리팩토링 →
  PATCH 판단, `1.6.3`로 갱신. `main_base_tag`도 `v1.10.4` → `v1.11.0`로 갱신
  (`main_base_commit`은 이미 `7bd280e3`로 main의 v1.11.0 태그 대상과 일치해 변경 불필요).
- `docs/CHANGELOG.md`에 `[zone-v1.6.3] 2026-10-27` 섹션 추가(main sync 반영 + BrushToolbar
  교체 요약).
- 커밋 `82340d7` (`docs: zone-v1.6.3 — main sync 반영 + BrushToolbar 교체 릴리즈 노트`).
- `git tag -a zone-v1.6.3`(대상 커밋 `82340d7`).
- `git push origin feature/zone-analysis-tab`(`daba05e..82340d7`) + `git push origin zone-v1.6.3` 완료.
- 존분석 브랜치 push에 sync 커밋들이 조상으로 포함되면서 GitHub이 PR #37을 자동으로
  `MERGED` 처리함(머지 커밋 `f7529a3`, 추가 조치 불필요).

### 결과 요약
- main: 태그 `v1.11.0`(커밋 `7bd280e3fa98a64cc146a7dce37ad3d90abf521d`), origin/main에
  push 완료(`b9dd6be..7bd280e`).
- sync PR: https://github.com/sfeelBot/Segmentation-Tool/pull/37 — `MERGED`
  (머지 커밋 `f7529a3`).
- 존분석 에디션: 태그 `zone-v1.6.3`(커밋 `82340d79491e221204b67723badaa21b4108518a`),
  origin/feature/zone-analysis-tab에 push 완료(`daba05e..82340d7`).
- GitHub Release: 생성하지 않음(요청 범위 밖, installer 패키징 미포함).
- 두 저장소 모두 작업 디렉토리에 이번 작업과 무관한 기존 미추적/수정 파일
  (`AGENTS.md`, `.codex/`, `data/annotations/`, `docs/agents/*-log.md` 등)이 남아있으나
  배포 범위 밖이라 건드리지 않음.

---

## 2026-10-28 — v1.12.0 태깅 (학습 중지 버그 수정 + 준비 단계별 로그 UI + 시간 계측 + 학습 설정 기본값 변경)

### 배경
- 리더 요청: main의 이번 작업 단위(학습 중지 버그 수정 + 학습 준비 단계별 로그 UI +
  느린 시작 구간 실측 + 학습 설정 기본값 변경)가 검증까지 통과하고 push도 완료된 상태
  (`origin/main` 동기화 확인됨) → 버전 태깅.
- 관련 커밋: `0be9c31`(중지 버그), `0d1c834`, `1eee61b`(단계로그+시간계측), `b5b3bef`,
  `48c4a2b`(config_form 기본값), `7a6eb8a`/`4753055`(문서).
- 참고 스펙: `docs/specs/training-progress-and-stop-fix-2026-10-28.md`

### 조치
- `release.ini` 확인: `version = 1.12.0`(이미 구현 라운드에서 1.11.1→1.12.0 MINOR 갱신 완료).
- `docs/CHANGELOG.md` `[v1.12.0]` 섹션 확인: trainer `stage_changed` 시그널, 학습 진행
  다이얼로그 단계 로그 `QListWidget`, `training_tab.py` 연결, i18n 6쌍은 이미 기술돼
  있었으나 **`app/widgets/config_form.py`의 DataLoader `num_workers` 기본값 0 / LR
  스케쥴러 `ReduceLROnPlateau` 기본값 변경(커밋 `48c4a2b`, 구현 라운드와 별도로 리더가
  나중에 추가)이 빠져 있어 보강**("변경" 절 추가).
  - 커밋 `bd3cf98` (`docs: CHANGELOG v1.12.0에 config_form.py 학습 기본값 변경 보강`).
- `scripts/generate_version_info.py` 실행 → `Generated release metadata for 1.12.0` 성공.
- `git tag -a v1.12.0`(대상 커밋 `bd3cf98`, CHANGELOG 요약을 태그 메시지로 사용).
- push는 수행하지 않음 — 리더가 사용자 확인 후 직접 push할 예정(이번 라운드 지시사항).

### 결과 요약
- 버전: v1.12.0
- 커밋: `bd3cf98`(CHANGELOG 보강, 아직 origin에 push 안 됨 — 로컬에만 존재, HEAD는
  push된 `4753055`보다 1커밋 앞섬)
- 태그: `v1.12.0`(annotate, 커밋 `bd3cf98` 대상, 로컬 전용, push 안 함)
- CHANGELOG 보강: 함(config_form.py 기본값 변경 "변경" 절 추가)
- GitHub Release: 생성하지 않음(요청 범위 밖, installer 패키징 미포함)
- 남은 작업: 리더가 사용자에게 push 승인받은 뒤 `git push origin main` + `git push origin v1.12.0`
## 2026-08-31 — Zone 1.4.0 원격 반영

- `release.ini`: `version=1.4.0`, `tag_prefix=zone-v`, main 기준
  `v1.10.4` 이후 `ba8bf5e`로 갱신.
- 생성 메타데이터: `MyAppVersion=1.4.0`, `MyProductSlug=SegmentationModelUIZone`.
- installer 출력명: `SegmentationModelUIZone-Setup-1.4.0.exe`.
- sync PR #33 병합 완료. main과 `feature/zone-analysis-tab` 모두 origin과 동기화.
- 태그와 실제 installer 빌드는 이번 요청 범위에 포함하지 않았다.

---

## 2026-10-01 — zone-v1.5.0 배포 (존 분석 탭 "상/하부 분석" 전면 재설계)

### 배경
- 존 분석 탭 전면 재설계(스펙 `docs/specs/zone-tab-redesign-2026-10-01.md`)가 구현+검증
  완료(커밋 `4477bc3`~`4fecaa6` + 문서 커밋, QA.md BUG-035 Closed). 기존 `release.ini`의
  `1.4.0`은 이미 실제 installer로 빌드·배포된 버전이라 그대로 두고, 이번 재설계는 그
  이후의 새 기능 추가이므로 SemVer MINOR 상승 → `1.5.0` 채택.

### 조치
- `release.ini`: `version` `1.4.0` → `1.5.0` (다른 키는 변경 없음, `main_base_tag`/
  `main_base_commit`은 `v1.10.4`/`ba8bf5e` 그대로 유지 — main 동기화 작업 아님).
- `docs/CHANGELOG.md`에 `## [zone-v1.5.0] 2026-10-01` 섹션 추가: 탭 명칭/순서 변경,
  체크포인트 자동 승계, 레시피 팝업(자동검출/수동편집/저장·불러오기), 원 중심 정렬·
  방향키 이동·휠 지름조절, 영역 설정 활성화 조건 분리, 이미지 append+개별 제거, 결과
  분석 테이블 최대 blob 픽셀수/그룹화/필터/클립보드, 체크포인트 파일명 날짜 포함,
  sliding window 고정 + 배치 처리 숨은 버그 수정, BUG-035(P3) 수정을 정리.
- `C:\Users\Feel\AppData\Local\Python\bin\python.exe scripts\generate_version_info.py`
  실행 → `Generated release metadata for 1.5.0` 성공 (release.ini/CHANGELOG 정합성 검증 통과).
  `build/version_info.txt`, `build/release-defines.iss`는 `.gitignore` 대상(생성 산출물)이라
  커밋하지 않음.
- `release.ini`, `docs/CHANGELOG.md` 2개 파일만 커밋(`5f644db`, `chore: zone 1.5.0 릴리스
  버전 갱신`) — 같은 워크트리에 planning/design 에이전트가 남긴 기존 미커밋 문서 변경
  (`docs/agents/design-log.md`, `docs/agents/planning-log.md`, `docs/decisions-needed.md`
  수정분, `docs/specs/zone-tab-redesign-2026-10-01.md` 신규)과 무관한 미추적 파일
  (`.codex/`, `AGENTS.md`, `data/annotations/`, `graphify-out/`)은 배포 범위 밖이라 손대지
  않음 — 리더 확인 필요.
- 태그 `zone-v1.5.0` (annotate, 커밋 `5f644db` 대상).
- 사용자 명시 승인에 따라 push 진행: `git push origin feature/zone-analysis-tab`
  (`246ba8a..5f644db`), `git push origin zone-v1.5.0`. 둘 다 성공.

### 결과 요약
- 버전: zone-v1.5.0
- 커밋: `5f644db` (origin/feature/zone-analysis-tab에 push 완료)
- 태그: `zone-v1.5.0` (origin에 push 완료)
- installer 실빌드/GitHub Release: 이번 요청 범위에 포함하지 않음(배포 에이전트 범위 밖).

---

## 2026-10-02 — zone-v1.5.1 배포 준비 (상/하부 분석 탭 Artifact 비주얼 조정)

### 배경
- 상/하부 분석 탭을 확정 디자인 Artifact에 맞춰 조정하는 작업(기능 변경 없음, 순수
  비주얼 — 스텝 인디케이터 신설, 체크포인트 카드/배지, 편집 툴바 재배치, 좌측 삭제
  아이콘, 우측 비율 색상바, 레시피/결과분석/진행상황 팝업 스타일)이 구현+검증 완료
  (커밋 `59e136b`~`bacdc13`, 스펙 `docs/specs/zone-tab-ui-reconciliation-2026-10-02.md`,
  검증 결과 `docs/agents/verification-log.md` 2026-10-02 항목 — PASS, 문제 0건).
- 사용자가 버전을 명시적으로 **1.5.1**(PATCH)로 지정 — 기능 추가가 아니라 호환되는
  UI 조정이므로 SemVer PATCH.

### 조치
- `release.ini`: `version` `1.5.0` → `1.5.1` (다른 키는 변경 없음).
- `docs/CHANGELOG.md`에 `## [zone-v1.5.1] 2026-10-02` 섹션 추가: 7단계 스텝 인디케이터,
  체크포인트 카드형+자동선택 배지, 편집 툴바를 캔버스 전용 헤더로 이동, 좌측 이미지
  목록 상시 삭제 아이콘, 우측 존 비율 색상바, 레시피/결과분석/진행상황 팝업 스타일
  정비를 정리 — 기능 변경 없음, 순수 UI/UX 조정임을 명시.
- `build/venv/Scripts/python.exe scripts/generate_version_info.py` 실행 →
  `Generated release metadata for 1.5.1` 성공 (release.ini/CHANGELOG 정합성 검증 통과).
- `release.ini`, `docs/CHANGELOG.md` 2개 파일만 커밋(`b1d9ada`, `chore: zone 1.5.1 릴리즈
  버전 갱신`) — 같은 워크트리의 기존 미추적 파일(`.codex/`, `AGENTS.md`,
  `data/annotations/`, `graphify-out/`)은 배포 범위 밖이라 손대지 않음.
- 태그 `zone-v1.5.1` (annotate, 커밋 `b1d9ada` 대상).
- **push는 수행하지 않음** — 이번엔 리더가 사용자에게 push 여부를 별도로 확인한 뒤
  처리하기로 함 (작업 지시에 명시).

### 결과 요약
- 버전: zone-v1.5.1
- 커밋: `b1d9ada` (로컬에만 존재, origin/feature/zone-analysis-tab 대비 push 전)
- 태그: `zone-v1.5.1` (로컬 annotated tag, push 전)
- installer 실빌드/GitHub Release: 이번 요청 범위에 포함하지 않음(배포 에이전트 범위 밖).
- push 대기: 리더가 사용자 확인 후 `git push origin feature/zone-analysis-tab` +
  `git push origin zone-v1.5.1` 진행 필요.

---

## 2026-10-29 — zone-v1.11.0 배포 (존 분석 탭 배치 단순화)

### 배경
- 스펙 `docs/specs/zone-analysis-tab-batch-simplify-2026-10-29.md`, 사용자 요청 9건
  (자동검출 버튼 삭제, 배치 모드 '고정' 단일화 + 추론/모델 의존성 완전 제거, 존
  숨기기(비파괴)/이름변경(바깥쪽 포함), 레시피 확장(hidden/outer_name, 기본 이름
  `YYYYMMDD_recipe`), 결과 이미지 일괄 저장)이 구현 완료 후 검증까지 통과
  (`docs/agents/verification-log.md` 2026-10-29 항목 — 정적 리뷰 + pytest 57 passed +
  실제 QTest 골든패스 44/44 PASS, 발견된 버그 없음).
- 이번 라운드는 CUDA 추론 워커(`_ZoneBatchWorker`) 제거 + 배치 파이프라인을
  `_ZoneCircleLayoutWorker`(추론 무관)로 교체하는 등 신규 기능이라 SemVer MINOR 판단.

### 조치
- `release.ini`: `version` `1.10.0` → `1.11.0` (`main_base_tag`/`main_base_commit`은
  이미 `v1.12.0`/`95d5823`로 최신 상태, 변경 불필요).
- `docs/CHANGELOG.md`에 `[zone-v1.11.0] 2026-10-29` 섹션 추가 — 사용자 요청 9건을
  추가/변경/삭제로 분류해 요약.
- `scripts/generate_version_info.py` 실행 → `Generated release metadata for 1.11.0` 성공.
- 같은 워크트리에 검증 에이전트가 남긴 미커밋 `docs/agents/verification-log.md`
  (2026-10-29, 44/44 PASS 항목)를 release.ini/CHANGELOG와 함께 커밋에 포함(이번
  라운드 검증 기록이라 분리할 이유 없음). 무관한 기존 미추적 파일(`.codex/`,
  `AGENTS.md`, `data/annotations/`, `graphify-out/`)은 배포 범위 밖이라 손대지 않음.
- 커밋 `5763d8e91ab30f43f1177a83729b08e6eba5b02b`
  (`chore: zone-v1.11.0 릴리스 — 배치 단순화 + 존 hidden/outer_name + 결과 일괄 저장`).
- 태그 `zone-v1.11.0` (annotate, 커밋 `5763d8e9` 대상, CHANGELOG 요약을 태그 메시지로 사용).
- **push는 수행하지 않음** — 지시사항에 따라 커밋/태깅까지만 로컬에서 종료, 리더가
  사용자 확인 후 `git push origin feature/zone-analysis-tab` + `git push origin
  zone-v1.11.0` 진행 필요.

### 결과 요약
- 버전: zone-v1.11.0
- 커밋: `5763d8e91ab30f43f1177a83729b08e6eba5b02b` (로컬에만 존재, origin/feature/zone-analysis-tab
  대비 6커밋 앞섬 — 이전 5커밋도 아직 push 전 상태였음)
- 태그: `zone-v1.11.0` (로컬 annotated tag, push 전)
- installer 실빌드/GitHub Release: 이번 요청 범위에 포함하지 않음(배포 에이전트 범위 밖).
- push 대기: 리더가 사용자 확인 후 진행 필요.
