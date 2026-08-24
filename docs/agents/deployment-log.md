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
