# 스펙 — "exe 패키징 + Setup Guide" 잔여 미착수 2건 (2026-08-29)

기획일: 2026-08-29. 배경: [docs/roadmap.md](../roadmap.md) "exe 패키징 + Setup Guide" 절이
2026-08-29 캐치업 세션에서 v1.9.0~v1.10.5 완료분을 반영해 최신화됐고, 남은 미착수 항목
2건(GitHub #2 요청1, Setup Guide 문서)의 스코프를 이 문서에서 구체화한다. 관련:
[docs/specs/voc-github-issues-2026-08-20.md](voc-github-issues-2026-08-20.md) "요청 1" 절
(최초 판단 근거 — 이 문서가 그 설계를 구체화해 대체).

두 항목 모두 **사용자 결정 없이 바로 구현 가능**하다고 판단(`docs/decisions-needed.md` 추가
등록 없음) — 근거는 각 절에 명시.

---

## 1. GitHub #2 요청1 — 전용 프로젝트 확장자 더블클릭 연결

### 전제 확인 (코드 조사)

- `app/core/project.py`의 `Project`는 **폴더 구조**다(`images/`, `annotations/`,
  `checkpoints/`, `user_models/`, `classes.json`, `project.json`). 프로젝트를 "단일 파일"로
  나타낼 방법이 원래 없다 — 과거 기획(`voc-github-issues-2026-08-20.md` "요청 1")도 이 점을
  짚었으나 구체적인 파일 설계까지는 내려가지 않았다. 이번에 확정한다.
- `main.py`의 `main()`은 현재 `sys.argv`를 **전혀 읽지 않는다** — `QApplication(sys.argv)`에
  넘기기만 할 뿐, argv[1] 이후는 무시. 프로젝트 선택은 항상
  `ProjectStartDialog`(`app/widgets/project_start_dialog.py`)를 거친다.
- `app/core/project.py`의 `open_existing(path)`는 이미 "메타파일 없으면 자동 생성"
  패턴을 갖고 있다(162~163행: `project.json` 없으면 `save_metadata(imported=True)`로 생성).
  이 관례를 그대로 재사용하면 **기존에 만들어진 프로젝트도 마이그레이션 스크립트 없이
  다음에 한 번 열릴 때 자동으로 신규 파일을 갖게** 할 수 있다.
- `installer/setup.iss`는 `PrivilegesRequired=lowest`(관리자 권한 불필요, per-user
  설치 — `{localappdata}\Programs` 하위). 이는 레지스트리 등록 설계에 직접 영향을준다
  (아래 참고).

### 설계 — 마커 파일 방식 확정

프로젝트 전체를 하나의 파일로 바꾸는 게 아니라, **프로젝트 폴더를 가리키는 얇은 포인터
파일**을 그 폴더 안에 둔다(과거 기획이 "유력한 안"으로 남겨둔 방향을 확정):

- 신규 파일: `{project.path}/{project_name}.segproj` — `Project` 폴더 **내부**에 위치.
  더블클릭 시 OS가 이 파일의 **부모 디렉터리**를 프로젝트 경로로 사용한다(파일 자체 내용은
  검증용 이상의 의미가 없음 — 파일이 이미 자기 프로젝트 폴더 안에 있으므로 경로 계산에
  필요한 정보는 파일 위치 그 자체가 전부).
  - 확장자는 `.segproj`로 잠정 확정(과거 기획 문서가 이미 이 이름으로 예시를 들었고 사용자
    재확인 원문에도 그대로 등장 — 최종 이름은 취향 문제라 결정 대기로 등록하지 않음, 구현
    시 이견 있으면 한 줄 수정으로 바꿀 수 있는 낮은 리스크).
  - 내용: `project.json`과 동일한 메타데이터 dict(JSON) 재사용 — 텍스트 에디터로 열어봐도
    읽을 수 있게. 앱은 내용을 파싱하지 않고 **파일 경로만** 사용(내용 파싱에 의존하면
    스키마 버전 관리 부담이 생기므로 지금은 회피).
- 생성 시점: `Project.ensure_dirs()`(현재 5개 표준 디렉터리를 보장하는 지점)에 마커 파일
  쓰기를 추가. `ensure_dirs()`는 `create()`·`open_existing()`·`set_current()` 경로 전부에서
  이미 호출되므로, **신규 프로젝트든 기존 프로젝트든 다음에 한 번 열리면 자동으로 마커 파일이
  생긴다** — 별도 마이그레이션 로직 불필요.
- `main.py` 변경(`main()` 함수 내부, ~15~20줄 추가):
  1. `sys.argv[1]`이 있고 그 경로가 `.segproj` 확장자면 → 부모 디렉터리를 프로젝트 경로로
     채택. 확장자가 없고 디렉터리 자체면 → 그 디렉터리를 그대로 채택(수동 테스트·커맨드라인
     실행 편의).
  2. 프로젝트 경로가 채택됐으면 `ProjectStartDialog`를 **건너뛰고** 바로
     `proj.open_existing(path)` + `proj.set_current(p)` 호출 후 `MainWindow` 생성 — 워드
     파일 더블클릭 시 다이얼로그 없이 바로 문서가 열리는 것과 동일한 사용자 경험(요청 원문의
     비유 그대로).
  3. 실패 시(존재하지 않는 경로, 손상된 폴더 등) `QMessageBox.critical`로 에러 표시 후
     **정상 흐름(ProjectStartDialog 표시)으로 폴백** — `project_start_dialog.py`의
     `_try_open()`과 동일한 예외 처리 패턴 재사용.
  4. `main()`의 기존 "프로젝트 전환 요청 시 다이얼로그 재표시" 루프는 그대로 둔다 — argv
     경유 진입은 **최초 1회**에만 적용되고, 이후 사용자가 앱 내에서 프로젝트를 전환하면
     평소처럼 `ProjectStartDialog`가 뜬다.
- 코드 영향 범위: `main.py`(argv 파싱 + 분기), `app/core/project.py`(`Project`에
  `marker_file` 프로퍼티 추가 + `ensure_dirs()`에 마커 파일 쓰기 3~5줄). **다른 파일은
  건드릴 필요 없음** — 저리스크, 격리된 diff.

### 설계 — installer 레지스트리 등록

`installer/setup.iss`에 `[Registry]` 섹션 신설. **주의**: `PrivilegesRequired=lowest`라
`HKCR`/`HKLM`에 직접 쓰면 관리자 권한 없는 설치에서 실패한다 — Inno Setup 6의 `HKA`
루트(관리자 권한 있으면 HKLM, 없으면 `HKCU\Software\Classes`로 자동 매핑, Windows는
`HKCU\Software\Classes`를 현재 사용자 한정 파일연결로 인식)를 써야 한다. 표준 패턴:

```
[Registry]
Root: HKA; Subkey: "Software\Classes\.segproj"; ValueType: string; ValueName: ""; \
  ValueData: "SegmentationModelUI.Project"; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\SegmentationModelUI.Project"; ValueType: string; \
  ValueName: ""; ValueData: "Segmentation Model UI Project"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\SegmentationModelUI.Project\DefaultIcon"; \
  ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"
Root: HKA; Subkey: "Software\Classes\SegmentationModelUI.Project\shell\open\command"; \
  ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""
```

- `uninsdeletevalue`/`uninsdeletekey` 플래그로 언인스톨 시 자동 정리(레지스트리 잔재
  방지 — 기존 BUG-016이 다루는 "설치 폴더/로그 잔재" 문제와는 별개 항목이니 혼동 주의).
- Explorer 아이콘 캐시가 설치 직후 즉시 갱신되지 않을 수 있음(Inno Setup이 자동으로
  `SHChangeNotify`를 호출하지 않음) — `[Code]` 섹션에 설치 완료 후
  `SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, 0, 0)` 호출을 추가하는 것이 Inno Setup
  파일연결 튜토리얼의 표준 보완책. 없어도 재부팅/재로그인하면 반영되지만, 설치 직후 바로
  동작하길 원하면 필요.
- 단일 인스턴스 문제: 앱이 이미 실행 중일 때 `.segproj`를 또 더블클릭하면 새 프로세스가
  하나 더 뜬다(기존에도 단일 인스턴스 강제 로직이 없음 — grep 결과 없음). 이번 스코프에서
  새로 막을 필요는 없음(기존 동작과 동일선상, 별도 불편 제기 없음) — 알려진 한계로만 기록.

### 구현 대상 파일

- `main.py` — argv 파싱 + 조건부 다이얼로그 스킵 분기 (`main()` 함수 내부).
- `app/core/project.py` — `Project.marker_file` 프로퍼티, `ensure_dirs()`에 마커 파일
  쓰기 추가.
- `installer/setup.iss` — `[Registry]` 섹션 신설 + `[Code]` 섹션에 `SHChangeNotify` 보완
  (선택, 권장).

### 검증 골든패스 (주요 기능 추가 수준 — 실제 설치본으로 확인 권장)

1. `build.bat`으로 새 installer 빌드 → 설치(관리자 권한 없이).
2. 새 프로젝트 생성 → 프로젝트 폴더 안에 `{이름}.segproj` 파일 생성 확인.
3. Explorer에서 그 파일을 더블클릭 → 앱이 `ProjectStartDialog` 없이 바로 해당 프로젝트로
   `MainWindow`를 띄우는지 확인.
4. **마이그레이션 확인**: 이번 기능 이전에 만들어진 기존 프로젝트(마커 파일 없음)를
   "프로젝트 열기"로 한 번 연 뒤 확인 → 마커 파일이 자동 생성됐는지, 그 다음부터 더블클릭이
   되는지.
5. 존재하지 않는/손상된 마커 파일 경로를 인위적으로 넘겨 실행 → 에러 다이얼로그 후
   `ProjectStartDialog`로 정상 폴백하는지(크래시 없음).
6. 언인스톨 후 레지스트리 키(`HKCU\Software\Classes\.segproj` 등)가 정리됐는지 확인.
7. (있으면 좋음, 필수는 아님) 관리자 권한으로 설치한 경우 `HKA`가 `HKLM`으로 매핑되는지도
   교차 확인 — per-user 설치가 기본값이라 우선순위는 낮음.

---

## 2. Setup Guide 문서

### 전제 확인 (코드 조사)

- `installer/setup.iss` 실제 마법사 구성: Inno Setup 표준 wizard(환영 → 설치 위치 선택
  → 추가 작업[바탕화면 아이콘, 기본 미체크] → 설치 진행 → 완료[실행 여부 체크박스]).
  `DisableProgramGroupPage=yes`라 시작 메뉴 폴더명 선택 단계는 생략됨. 라이선스 페이지 없음.
  한국어 UI(`[Languages] korean`)만 등록.
- `PrivilegesRequired=lowest` — 관리자 권한 불필요, 기본 설치 위치는
  `{localappdata}\Programs\{제품슬러그}` (일반 사용자 권한으로 충분). 설치 용량은 BUG-024
  검증 기록 기준 약 1.815GB.
- **CPU/CUDA 빌드 분기는 exe 배포판에는 없다** — `build.bat`(45~52행)이 항상
  `--extra-index-url https://download.pytorch.org/whl/cu128`로 단일 CUDA(cu128) torch를
  설치해 그 한 벌로 installer를 만든다. `docs/roadmap.md`의 기존 서술("CUDA/CPU 빌드 분기")은
  **부정확한 캐치업 세션의 오기**로 확인됨 — 아래 roadmap 갱신에서 바로잡는다. PyTorch의
  CUDA 빌드 wheel은 NVIDIA GPU가 없는 머신에서도 정상 설치·실행되며 자동으로 CPU로
  폴백하는 게 PyTorch의 표준 동작(런타임에 `torch.cuda.is_available()`이 False면 CPU 경로
  사용) — 별도 실측 없이도 PyTorch 공식 동작으로 알려진 사실이라 스파이크 불필요. 즉
  **installer는 하나뿐이고, 사용자가 GPU 유무에 따라 다른 파일을 고를 필요가 없다.**
  GPU가 있어도 인식이 안 되면 앱 내 "CUDA 종합 진단 팝업"(`cuda_diag.py`)으로 원인 진단
  가능 — Setup Guide에서 이걸 안내하면 충분.
- 배포 채널: `docs/CHANGELOG.md` v1.8.0 사용자 요청 원문("github에 installer 빌드된 것까지
  포함해서 올려줘")과 v1.9.0 이후 관례로 볼 때 **GitHub Releases**에 installer `.exe`를
  첨부하는 방식. 파일명 패턴은 `setup.iss`의 `OutputBaseFilename={#MyProductSlug}-Setup-{#MyAppVersion}`
  (예: `SegmentationModelUI-Setup-1.10.5.exe`).
- 데이터 저장 위치: `main.py`의 `ensure_data_dirs()`/`project.py`의 `_app_root()`가 frozen
  상태에서 `sys.executable` 기준 경로를 쓰므로, **모든 데이터(`data/`, `projects/`)가 설치
  폴더 바로 밑에 저장된다.** 이는 (a) 백업 시 사용자가 알아야 할 위치이고 (b) 기존
  BUG-016(P3, Open) — 언인스톨 시 설치 폴더와 `data\logs\`가 완전히 삭제되지 않는 문제와
  직결되므로 Setup Guide에 "제거 전 프로젝트 백업 권장" 안내가 필요.
- 트러블슈팅: `docs/USER_MANUAL.md`가 이미 갖고 있는 "WinError 1114 DLL 초기화 실패 →
  VC++ Redistributable 설치" 항목은 pip 설치 사용자뿐 아니라 exe 사용자에게도 그대로
  유효한 원인(운영체제 레벨 공용 런타임 DLL 문제)이라 재사용 가능 — 새로 조사할 필요 없음.

### 설계 — 문서 배치: 신규 파일 대신 `USER_MANUAL.md` 기존 절 확장

- `docs/USER_MANUAL.md`의 "🚀 시작하기" 절(목차 1번)이 이미 "설치 및 실행 방법"을 다루는
  자리다. 지금은 pip 설치 안내만 있어 이 절을 **두 갈래**로 확장하는 것으로 충분 —
  새 파일(`docs/SETUP_GUIDE.md` 등)을 만들 필요 없다고 판단(YAGNI):
  - CLAUDE.md의 문서 목록에 `USER_MANUAL.md`는 원래도 명시 안 돼 있고(현행 CLAUDE.md
    "관련 문서" 절 참고), 새 파일을 추가하면 그 목록에도 항목을 하나 더 늘려야 하는데
    비교하면 실질적 이득(가독성)이 크지 않음. `USER_MANUAL.md` 자체가 이미 "일반
    사용자용" 톤(이모지, GUI 워크스루)이라 exe 설치 안내가 그 톤·독자층과 정확히 일치.
  - 분량이 늘어난다는 우려는, exe 설치 안내가 실제로는 짧다(다운로드→더블클릭→마법사
    3~4단계)는 점에서 근거가 약함 — 전체 문서가 800줄대인데 반해 추가분은 40~60줄 내외로
    예상.
- 구체 변경: "🚀 시작하기" 절을 아래처럼 재구성(제안, 문구는 구현 시 다듬을 것):
  - **A. 설치 프로그램(exe) 사용자용** (신규, 우선 배치 — 일반 사용자 다수가 이 경로를
    탈 것으로 예상):
    1. GitHub Releases에서 최신 `SegmentationModelUI-Setup-X.Y.Z.exe` 다운로드.
    2. 더블클릭 실행 → 관리자 권한 불필요(사용자 계정 하위 설치) → 설치 위치 확인(기본값
       그대로 권장) → 설치 완료 후 바로 실행.
    3. (신규 기능 반영 시) 프로젝트 폴더의 `.segproj` 파일을 더블클릭하면 해당 프로젝트로
       바로 열 수 있다는 안내 — 위 "1." 항목 구현 완료 후에만 이 문장 추가.
    4. 시스템 요구사항 표(Windows 10/11 x64, 디스크 여유 공간 ~2GB, GPU 선택사항·있으면
       자동 가속).
    5. 제거 방법: Windows "설정 → 앱" 또는 시작 메뉴 바로가기로 제거. **제거 전 `projects\`
       폴더를 다른 곳에 백업 권장**(BUG-016 언급 — 제거가 완전하지 않을 수 있음, 다음
       설치 전 잔여 폴더 확인 권장).
    6. VC++ Redistributable 등 트러블슈팅은 기존 "🩺 트러블슈팅" 절 링크로 연결(중복
       작성 안 함).
  - **B. 개발자용(소스 실행)** — 기존 pip install 안내 그대로 유지(개발/커스터마이징
    목적 사용자용으로 명확히 라벨링만 추가).
- CLAUDE.md 문서 목록 갱신은 하지 않음(원래도 `USER_MANUAL.md`가 그 목록에 없었으므로
  이번 변경으로 새로 어긋나는 것도 없음 — 현상 유지).

### 구현 대상 파일

- `docs/USER_MANUAL.md` — "🚀 시작하기" 절만 수정(다른 절 변경 없음). 순수 문서 작업,
  코드 변경 없음.

### 검증 골든패스

문서 작업이라 "실행 확인"은 앱 구동이 아니라 **사실관계 재검증**으로 충분(리더 판단에
맡기되 제안):
1. 문서에 적힌 GitHub Releases 링크·파일명 패턴이 실제 최신 릴리스와 일치하는지 확인.
2. installer 실행 마법사 단계 수·문구가 문서 서술과 실제로 일치하는지(변경한 캡처/스크린샷
   없이도 `setup.iss` 재확인으로 충분, 실제 설치까지는 선택사항).
3. 링크된 "🩺 트러블슈팅" 절 앵커가 깨지지 않았는지.
4. 마커파일 안내 문장은 위 "1." 항목이 구현·검증 완료된 뒤에만 추가하도록 순서 지키기
   (아직 없는 기능을 문서에 먼저 적지 않기).

---

## 실행 순서 제안

두 항목은 서로 다른 파일(코드 vs 문서)이라 **병렬 진행 가능**. 다만 위 "Setup Guide"
항목의 마커파일 안내 문장 1개는 "GitHub #2 요청1" 구현이 끝난 뒤 추가해야 하므로, Setup
Guide 문서 작업을 시작만 먼저 하고 그 문장만 나중에 이어붙이거나, 순서를 ①번(코드) →
②번(문서) 순으로 진행해도 무방(리더 재량).
