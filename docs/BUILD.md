# 빌드 및 버전 관리

Windows 실행 파일과 설치 프로그램의 릴리스 정보는 저장소 루트의
[`release.ini`](../release.ini) 한 곳에서 관리한다. `build.spec`나
`installer/setup.iss`의 버전을 직접 수정하지 않는다.

## 버전 변경

1. `release.ini`의 `version`을 `MAJOR.MINOR.PATCH` 형식으로 수정한다.
2. `docs/CHANGELOG.md` 최상단 릴리스 제목도 `## [<tag_prefix>MAJOR.MINOR.PATCH]`로 갱신한다.
3. 필요할 때 제품명, 실행 파일명, 배포자 등을 같은 파일에서 수정한다.
4. `py -3 scripts\generate_version_info.py`로 설정을 검증한다.

### 기능·버그 수정 완료 루틴

모든 기능 추가와 버그 수정은 커밋 전에 installer 버전을 확인한다. 아직 릴리스되지 않은
동일 버전 작업에 포함되지 않았다면 기능 추가는 MINOR, 호환 버그 수정은 PATCH,
호환성 파괴 변경은 MAJOR를 올리고 `release.ini`와 `docs/CHANGELOG.md`를 함께 갱신한 뒤
`scripts/generate_version_info.py` 검증을 실행한다.

CHANGELOG의 최신 버전이 다르거나 필수 키, SemVer, GUID가 잘못되면 생성기는
실패한다. CHANGELOG는 자동으로 수정하지 않는다.

`release.ini` 항목:

| 키 | 용도 |
|---|---|
| `version` | EXE 및 installer 버전 |
| `tag_prefix` | CHANGELOG 및 Git 태그 접두사(main은 `v`, zone은 `zone-v`) |
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

별도의 conda/venv 활성화는 필요 없다. 스크립트가 시스템 Python 3.12로 `build\venv`를
최초 1회 생성하고 CUDA PyTorch와 빌드/런타임 패키지를 설치한 뒤 재사용한다. 첫 실행은
대용량 패키지 다운로드 때문에 오래 걸릴 수 있다.

installer에는 Python 3.12와 PyQt6, PyTorch 2.7.1 cu128 등 실행에 필요한 런타임이 모두
포함되므로 설치 대상 PC는 Python 설치나 인터넷 연결이 필요 없다. NVIDIA GPU가 없는 PC는
동봉된 PyTorch의 CPU 경로로 실행된다.

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

## 빠른 검증

```bat
py -3 scripts\generate_version_info.py
py -3 -m pytest -q tests\test_build_release.py
```

`build.bat`은 Windows `cmd.exe` 호환성을 위해 ASCII 문자만 사용한다.
