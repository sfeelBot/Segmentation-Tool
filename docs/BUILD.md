# 빌드 & 설치 파일(installer) 만들기

`build.bat` 하나로 exe 빌드부터 설치 프로그램(.exe installer) 생성까지 전부 끝난다.

```
build.bat
  ├─ [1/3] build\, dist\ 정리
  ├─ [2/3] PyInstaller → dist\SegmentationModelUI\ (exe + _internal\)
  └─ [3/3] Inno Setup   → installer\output\SegmentationModelUI-Setup-{버전}.exe
```

즉 `build.bat`은 exe만 만드는 게 아니라 **사용자가 더블클릭해서 설치하는 installer까지** 한 번에 만든다.

---

## 1. 사전 준비: Inno Setup 설치

installer 생성 단계(3단계)는 [Inno Setup 6](https://jrsoftware.org/isdl.php)이 로컬에 설치돼 있어야 동작한다.
없으면 `build.bat`이 아래처럼 에러를 내고 멈춘다.

```
[ERROR] Inno Setup 6 is not installed. Get it from https://jrsoftware.org/isdl.php
```

한 번만 설치하면 이후로는 `build.bat` 실행만으로 계속 재사용된다.

---

## 2. build.bat 실행

```
build.bat
```

- 1~2단계: [build.spec](../build.spec) 기준 PyInstaller `onedir` 빌드
  - onefile이 아니라 onedir인 이유: onefile은 실행마다 임시 폴더에 압축을 풀어 기동이 느리고, torch(CUDA 포함) 번들이 커서 그 비용이 특히 큼
- 3단계: [installer\setup.iss](../installer/setup.iss)를 ISCC(Inno Setup 컴파일러)로 컴파일

성공하면 마지막에 결과 경로를 출력한다.

```
===== Build complete =====
  D:\segmentation model\installer\output\SegmentationModelUI-Setup-1.8.0.exe
```

---

## 3. setup.iss — installer 세부 설정

앱 이름, 버전, 설치 경로, 바로가기 등 installer 동작은 [installer\setup.iss](../installer/setup.iss)에서 정의한다.

| 항목 | 값 | 의미 |
|---|---|---|
| `MyAppName` | Segmentation Model UI | 설치 프로그램/시작 메뉴에 표시되는 이름 |
| `MyAppVersion` | 1.8.0 | 설치 파일명(`...-Setup-1.8.0.exe`)에 그대로 들어감 — **버전 올릴 때 여기를 수정** |
| `MyDistDir` | `..\dist\SegmentationModelUI` | PyInstaller 산출물 경로 (2단계 결과물을 그대로 패키징) |
| `PrivilegesRequired` | `lowest` | 관리자 권한 없이 설치(per-user). 앱이 설치 폴더 밑에 `data\`, `projects\`를 직접 쓰기 때문에 Program Files(admin 전용)에 넣으면 표준 사용자가 쓰기 오류를 겪음 |
| `DefaultDirName` | `{autopf}\SegmentationModelUI` | `PrivilegesRequired=lowest`와 결합하면 관리자 권한 없이도 쓰기 가능한 `%LocalAppData%\Programs\SegmentationModelUI`로 자동 해석됨 |
| `Languages` | 한국어 | 설치 마법사 UI 언어 |
| `Tasks: desktopicon` | 기본 체크 해제 | "바탕화면에 바로가기 만들기" 옵션 (사용자가 켜야 생김) |
| `[Files]` | `{#MyDistDir}\*` 전체 | dist 폴더 안 exe + `_internal\` 라이브러리를 통째로 복사 |
| `[Run]` | 설치 완료 후 실행 옵션 | 설치 마법사 마지막 화면에서 "지금 실행" 체크박스 제공 |

### 자주 바꾸게 될 것

- **버전 올리기**: `#define MyAppVersion "1.8.0"` 수정 (배포 에이전트가 `git tag`/CHANGELOG와 맞춰 관리)
- **바탕화면 바로가기 기본 체크**: `[Tasks]`의 `Flags: unchecked` → `checked`로 변경
- **설치 경로 강제 지정**: `DefaultDirName` 수정 (단, admin 설치로 바꾸면 `PrivilegesRequired`도 같이 검토 필요 — 위 표의 이유 참고)

---

## 4. 범위 밖

- CLAUDE.md 기준 배포 에이전트(deployer)는 버전 태깅 + CHANGELOG 갱신까지만 담당한다.
- PyInstaller/Inno Setup 실행파일 패키징·배포 자체는 별도 논의 대상 — 이 문서는 "어떻게 만드는가"만 다룬다.
