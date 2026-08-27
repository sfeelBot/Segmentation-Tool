# 빌드 및 버전 관리

Windows 실행 파일과 설치 프로그램의 릴리스 정보는 저장소 루트의
[`release.ini`](../release.ini) 한 곳에서 관리한다. `build.spec`나
`installer/setup.iss`의 버전을 직접 수정하지 않는다.

## 버전 변경

1. `release.ini`의 `version`을 `MAJOR.MINOR.PATCH` 형식으로 수정한다.
2. `docs/CHANGELOG.md` 최상단 릴리스 제목도 `## [<tag_prefix>MAJOR.MINOR.PATCH]`로 갱신한다.
3. 필요할 때 제품명, 실행 파일명, 배포자 등을 같은 파일에서 수정한다.
4. main 변경을 동기화했다면 `main_base_tag`와 `main_base_commit`을 마지막으로 반영한
   main 릴리스 태그 및 전체 40자리 커밋 SHA로 함께 갱신한다.
5. `py -3 scripts\generate_version_info.py`로 설정을 검증한다.

CHANGELOG의 최신 버전이 다르거나 필수 키, SemVer, GUID가 잘못되면 생성기는
실패한다. CHANGELOG는 자동으로 수정하지 않는다.

`release.ini` 항목:

| 키 | 용도 |
|---|---|
| `version` | EXE 및 installer 버전 |
| `tag_prefix` | CHANGELOG 및 Git 태그 접두사(main은 `v`, zone은 `zone-v`) |
| `main_base_tag` | zone에 마지막으로 반영된 main 릴리스 태그(`vMAJOR.MINOR.PATCH`) |
| `main_base_commit` | zone에 마지막으로 반영된 main 커밋(전체 40자리 SHA) |
| `product_name` | Windows 제품명과 설치 프로그램 표시명 |
| `product_slug` | 설치 폴더와 installer 파일명의 안전한 이름 |
| `exe_name` | PyInstaller EXE 및 dist 디렉터리 이름(확장자 제외) |
| `publisher` | Windows 버전 정보와 설치 프로그램 배포자 |
| `app_id` | Inno Setup 업그레이드 식별 GUID; 기존 제품은 변경 금지 |

## 전체 빌드

먼저 Python 빌드 의존성과 [Inno Setup 6](https://jrsoftware.org/isdl.php)를 설치한 뒤
저장소 루트에서 실행한다.

```bat
build.bat
```

스크립트는 다음 순서로 동작한다.

1. 기존 `build\`, `dist\` 삭제
2. `release.ini` 검증 및 생성 파일 작성
3. PyInstaller onedir 빌드
4. Inno Setup installer 빌드

생성 파일은 빌드 중 다시 만들어지므로 직접 편집하지 않는다.

- `build/version_info.txt`: PyInstaller Windows `VSVersionInfo`
- `build/release-defines.iss`: Inno Setup 전처리기 define
- `dist/<exe_name>/`: 실행 파일과 라이브러리
- `installer/output/<product_slug>-Setup-<version>.exe`: 최종 설치 프로그램

현재 zone 에디션은 `SegmentationModelUIZone.exe`와
`SegmentationModelUIZone-Setup-<version>.exe`를 생성하며, main과 다른 AppId·설치
폴더를 사용하므로 두 제품을 동시에 설치할 수 있다. zone 릴리스 태그는
`zone-vX.Y.Z` 형식을 사용한다.

Git 메타데이터와 `git` 명령을 사용할 수 있는 개발 환경에서는 생성기가 기준 커밋의
존재 여부, 현재 zone HEAD의 조상인지, 기준 태그가 기준 커밋의 조상인지도 확인한다.
소스 ZIP처럼 Git 정보를 사용할 수 없는 환경에서는 두 값의 형식만 검증한다.

## 빠른 검증

```bat
py -3 scripts\generate_version_info.py
py -3 -m pytest -q tests\test_build_release.py
```

`build.bat`은 Windows `cmd.exe` 호환성을 위해 ASCII 문자만 사용한다.
