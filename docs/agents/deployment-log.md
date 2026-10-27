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

## 2026-08-28 — v1.10.4 배포

- 상태: 배포 승인 및 검증 PASS, `origin/main` push와 annotated tag `v1.10.4` 생성 예정.
- 내용: 일반 PowerShell/CMD에서 Python 3.12 빌드 venv를 자동 준비하고, 손상되었거나 다른 Python 버전인 기존 venv를 자동 재생성.
- 검증: main build/release 테스트 24 passed.
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
