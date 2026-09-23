# GitHub #22 설치 시 기존 버전 체크 + BUG-016 로그 잔존 — 구현 스펙 재확인 (2026-09-23)

## 0. 요약 — 상태가 스코프 산정 시점과 달라졌음

[github-issue-22-and-16-followup-2026-08-29.md](github-issue-22-and-16-followup-2026-08-29.md)의
"GitHub #22" 절(2026-08-29 작성)은 당시 `installer/setup.iss`에 `[Code]` 섹션 자체가 없는 상태를
전제로 설계를 제안했다. **오늘(2026-09-23) 두 워크트리의 `installer/setup.iss`를 직접
읽고 `Grep`으로 교차 확인한 결과, GitHub #22(옵션2: 자동 제거 후 재설치) + BUG-016
(`[UninstallDelete]`) 둘 다 이미 완전히 구현되어 있다** — main·zone 두 브랜치의
`installer/setup.iss`가 `[Code]`/`[UninstallDelete]` 섹션까지 포함해 **byte-for-byte
동일**하다.

- **main**: 구현뿐 아니라 **독립 검증까지 이미 끝남**. `QA.md`(main)의 BUG-029/030/031
  (전부 Closed, 실제 `build.bat` 전체 파이프라인 + 실제 구버전 설치 → 신버전 업그레이드
  → 무인 제거까지 실측 검증) + BUG-016(Closed, "GitHub #22 구현에 포함")이 근거. `1.10.5`로
  이미 출시됨(`build/release-defines.iss` 확인).
- **zone**: 코드는 main과 완전히 동일하게 이미 있지만, **zone 자체 AppId
  (`0997E818-6906-483C-BA3A-324FED0BFF97`)/빌드 산출물(`SegmentationModelUIZone.exe`)로
  실측 검증된 적이 없고**, `QA.md`(zone)에도 전혀 반영되지 않았다(BUG-016 여전히 Open,
  GitHub #22 항목 자체가 없음). `docs/roadmap.md`(main도 zone도 동일) 체크박스도 `[ ]`로
  남아있음 — 코드는 끝났는데 문서만 못 따라간 순수 doc-lag임이 두 브랜치 모두에서 확인됨.

**결론: 이번 라운드에 신규로 작성해야 할 Pascal 코드는 없다.** 남은 작업은 (a) zone
자체 빌드+설치+무인제거 검증(구현이 아니라 검증 단계), (b) 두 브랜치 문서 동기화뿐이다.
아래는 그래도 구현자/검증자가 참고하도록, 사용자가 오늘 확정한 사항 대비 현재 코드를
항목별로 대조하고 리팩터링 없이 그대로 문서화한 것이다.

## 1. 사용자 오늘 확정사항 대비 현재 코드 대조

| 확정사항 | 현재 코드 충족 여부 |
|---|---|
| 옵션2(안내 팝업 → 확인 시 구버전 `UninstallString` 실행 → 새 설치 진행) | ✓ `InitializeSetup()`이 정확히 이 흐름 |
| main + zone 둘 다 적용 | ✓ 두 브랜치 `installer/setup.iss` 이미 동일 코드 보유 |
| BUG-016(로그 잔존)과 결합 | ✓ `[UninstallDelete]`가 같은 파일에 이미 존재 |
| `PrivilegesRequired=lowest`에서 `HKA` 매핑 | ✓ 전 구간 `HKA` 사용, admin 권한 불필요 |

## 2. 두 브랜치 `installer/setup.iss` 현재 구조 (실측, 2026-09-23)

파일 경로: `installer/setup.iss` (main: `D:\segmentation model\installer\setup.iss`,
zone: `D:\segmentation model-zone-analysis-tab\installer\setup.iss`). 109줄, 두 파일
전체가 완전히 동일하다(`Grep` 라인번호까지 일치 확인).

```
[Setup]        (7~32행)  AppId/AppName/... + PrivilegesRequired=lowest 등
[Languages]    (34~35행) 한국어
[Tasks]        (37~38행) 바탕화면 바로가기
[Files]        (40~41행) {#MyDistDir}\* → {app}
[Icons]        (43~46행)
[Run]          (48~49행) 설치 완료 후 실행
[UninstallDelete] (55~56행) BUG-016 수정 — {app}\data\logs 명시적 제거 대상
[Code]         (58~108행) GetUninstallRegKey() + InitializeSetup() — GitHub #22
```

### 2-1. `[UninstallDelete]` (BUG-016)

```pascal
[UninstallDelete]
Type: filesandordirs; Name: "{app}\data\logs"
```

로그 파일(`app.log`/`errors.log`/`perf.log`)은 `[Files]`로 설치된 적이 없어 Inno
Setup 기본 제거 로직이 추적하지 못하던 것을 명시적으로 제거 대상에 포함. `images/
annotations/checkpoints` 등 사용자 데이터가 있는 `data\` 전체가 아니라 `logs\`만
지정해 사용자 데이터는 보존한다.

### 2-2. `GetUninstallRegKey()` — BUG-030 교훈이 이미 반영됨

```pascal
function GetUninstallRegKey(): String;
begin
  Result := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{{#MyAppId}}_is1';
end;
```

과거 시도(main에서 BUG-030으로 발견·수정됨)는 `SetupSetting('AppId')` 빌트인으로
`[Setup]` 섹션의 `AppId={{{#MyAppId}}` 값을 읽었는데, Inno가 `"{{" → "{"`로 이스케이프
해제하기 **이전의** 원시 텍스트(`{{GUID}`, 중괄호 2개)를 돌려줘 실제 레지스트리 키
(`{GUID}_is1`, 중괄호 1개)와 영원히 불일치했다. `{#MyAppId}`는 전처리기 매크로라
컴파일 타임에 이스케이프 없이 순수 GUID 문자열로 치환되므로, 중괄호를 코드에서 직접
한 번만 감싸 정확히 일치시킨다. **이 함정은 이미 해결된 코드에 반영되어 있어 zone이
다시 겪을 필요는 없다** — 다만 zone 고유 AppId로 실제 레지스트리 키 문자열이 맞는지
실측 확인은 아직 안 됐다(§5-7).

### 2-3. `InitializeSetup()` — GitHub #22 옵션2

```pascal
function InitializeSetup(): Boolean;
var
  OldVersion, UninstallString: String;
  ResultCode: Integer;
begin
  Result := True;
  if RegQueryStringValue(HKA, GetUninstallRegKey(), 'DisplayVersion', OldVersion) then
  begin
    if SuppressibleMsgBox(
      Format(
        '기존 버전 %s이(가) 설치되어 있습니다.'#13#10 +
        '계속 진행하면 기존 버전을 제거한 뒤 새 버전을 설치합니다.'#13#10#13#10 +
        '계속하시겠습니까?', [OldVersion]),
      mbConfirmation, MB_YESNO, IDYES) = IDYES then
    begin
      if RegQueryStringValue(HKA, GetUninstallRegKey(), 'UninstallString', UninstallString) then
      begin
        UninstallString := RemoveQuotes(UninstallString);
        if not Exec(UninstallString, '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART', '',
          SW_HIDE, ewWaitUntilTerminated, ResultCode) then
        begin
          SuppressibleMsgBox('기존 버전 제거에 실패했습니다. 설치를 취소합니다.', mbError, MB_OK, IDOK);
          Result := False;
        end;
      end;
    end
    else
      Result := False;
  end;
end;
```

- **레지스트리 조회**: `RegQueryStringValue(HKA, GetUninstallRegKey(), 'DisplayVersion', OldVersion)`.
  `HKA`는 `PrivilegesRequired=lowest`(per-user 설치) 환경에서 `HKCU`로, admin 설치면
  `HKLM`으로 자동 매핑되는 Inno Setup 6 상수 — 관리자 권한 없이도 정상 동작.
- **안내 팝업 버튼 문구**: "기존 버전 %s이(가) 설치되어 있습니다. 계속 진행하면 기존
  버전을 제거한 뒤 새 버전을 설치합니다. 계속하시겠습니까?" — `MB_YESNO`, 기본
  포커스 `IDYES`.
- **`MsgBox` 대신 `SuppressibleMsgBox` 사용 이유(BUG-031 교훈)**: 일반 `MsgBox()`는
  `/SUPPRESSMSGBOXES` 플래그를 무시하고 항상 실제 모달(`#32770`)을 띄워 무인 설치
  (`/VERYSILENT /SUPPRESSMSGBOXES`)를 영원히 멈춰 세운다(main에서 실제로 재현되어
  BUG-031로 확정·수정됨). `SuppressibleMsgBox`만 이 플래그를 존중하며, 무인 모드의
  기본 응답은 "계속 진행"(`IDYES`) — 자동 업그레이드가 목적이므로 의도된 기본값.
- **구버전 제거 실행**: `UninstallString`(레지스트리에 등록된 언인스톨러 경로,
  따옴표 제거 후) 을 `Exec(..., '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART', '',
  SW_HIDE, ewWaitUntilTerminated, ResultCode)`로 **동기 대기**(`ewWaitUntilTerminated`)
  실행 — 언인스톨이 끝날 때까지 설치가 기다린 뒤 다음 단계(파일 복사)로 진행.
- **실패 처리 — 설치를 중단한다(계속 진행이 아님)**: `Exec()`가 `False`를 반환하면
  (언인스톨러 실행 자체가 안 됨) 에러 메시지 표시 후 `Result := False`로
  `InitializeSetup()`을 실패시켜 **설치 전체를 취소**한다. 사용자가 안내 팝업에서
  "아니오"를 선택해도 동일하게 `Result := False`(설치 취소). "구버전 제거는
  실패했지만 새 버전 설치는 그대로 진행"하는 절충안은 채택하지 않았음 — 구버전이
  일부만 지워진 채 새 버전이 덮어써지는 불확실한 상태를 피하기 위함.
- **최초 설치(기존 버전 없음)**: `RegQueryStringValue`가 `False`를 반환하면 `if` 블록
  전체를 건너뛰고 `Result := True`(함수 최상단에서 이미 설정)가 그대로 유지돼 안내
  없이 정상 진행 — 회귀 없음.

## 3. main vs zone 구조 차이

**차이 없음.** `installer/setup.iss` 파일 내용이 완전히 동일하며, 브랜치별 실제 값은
`#include "..\build\release-defines.iss"`로만 갈라진다(이 파일은 각 워크트리에
독립적으로 존재하고 `.gitignore` 대상이 아니라 커밋되어 있음 — `scripts/
generate_version_info.py`가 버전 올릴 때마다 재생성).

| `#define` | main (`D:\segmentation model\build\release-defines.iss`) | zone (`D:\segmentation model-zone-analysis-tab\build\release-defines.iss`) |
|---|---|---|
| `MyAppName` | `Segmentation Model UI` | `Segmentation Model UI - Zone Analysis` |
| `MyAppVersion` | `1.10.5` | `1.4.0` |
| `MyAppPublisher` | `Segmentation Model UI` | `Segmentation Model UI` |
| `MyAppExeName` | `SegmentationModelUI.exe` | `SegmentationModelUIZone.exe` |
| `MyProductSlug` | `SegmentationModelUI` | `SegmentationModelUIZone` |
| `MyAppId` | `03C2678A-B979-4B99-A68B-842EA853D667` | `0997E818-6906-483C-BA3A-324FED0BFF97` |
| `MyDistDir` | `..\dist\SegmentationModelUI` | `..\dist\SegmentationModelUIZone` |

`InitializeSetup()`/`GetUninstallRegKey()`가 전부 `{#MyAppId}` 매크로만 참조하는
구조라 이 표의 값만 바뀌면 로직 변경 없이 그대로 zone에도 적용된다는 2026-08-29
스펙의 "zone 브랜치 이식성" 판단이 실제로 정확했음을 오늘 확인했다.

## 4. main이 겪은 3개 함정 (zone 검증 시 재현 여부만 확인하면 됨, 재수정 불필요)

코드가 이미 이 3개를 전부 반영한 상태이므로 zone에서 재발할 이유는 없지만, 검증자가
"왜 이렇게 짜여 있는지" 이해하고 같은 함정을 다시 만들지 않도록 기록해둔다.

1. **BUG-029** — `[Code]` 섹션 Pascal Script 안에서도 줄이 `[`로 시작하면 Inno
   Setup 컴파일러가 새 INI 섹션 헤더로 오인해 파싱 에러를 낸다(문서화되지 않은 함정).
   `Format(...)`의 인수 배열 `[OldVersion]`을 줄 앞에 오지 않도록 한 줄로 합쳐야 함 —
   현재 코드(§2-3)는 이미 한 줄로 되어 있어 안전.
2. **BUG-030** — `SetupSetting('AppId')`가 이스케이프 해제 **이전** 원시 텍스트를
   반환해 레지스트리 키가 영원히 불일치하던 함정. `{#MyAppId}` 매크로 직접 참조로
   해결됨(§2-2). zone도 같은 방식이라 이론상 안전하나, zone 고유 AppId로 실제
   `reg query` 결과와 일치하는지는 아직 실측되지 않음(§6-7 남은 작업).
3. **BUG-031** — 일반 `MsgBox()`가 `/SUPPRESSMSGBOXES`를 무시해 무인 설치를 무한
   대기(hang)시키던 함정. `SuppressibleMsgBox()`로 교체 완료(§2-3). zone도 동일
   코드라 안전할 것으로 예상되나 zone 자체로 무인 모드 실측은 아직 없음(§6-3).

## 5. BUG-016 main 실측 검증 요약 (참고용, zone은 별도 실측 필요)

main `QA.md`(2026-08-29, verifier, 실제 빌드 exe로 실기기 재현)에 따르면:
- 신규 설치 후 30초 이상 구동 → `data\logs\app.log`/`errors.log` 생성 확인.
- `unins000.exe /VERYSILENT /SUPPRESSMSGBOXES` 무인 제거 후 `data\logs\`와 그 안의
  로그 파일 완전 삭제 확인.
- 별도 설치에 `data\images\sample.png`/`data\annotations\sample.json`/
  `data\checkpoints\epoch_0001.pt`/`data\logs\*.log` 더미 파일을 두고 동일하게 무인
  제거 → `data\logs\`만 삭제되고 나머지 3개는 전부 보존됨을 확인(요구사항 그대로 충족).
- 비고(별도 티켓화 안 함): `{app}`와 빈 `data\` 폴더 자체는 삭제 후에도 남음(Inno
  Setup 표준 동작, `[UninstallDelete]`가 `logs`만 지정했으므로). 사용자 데이터 손실도
  실질적 디스크 오염도 아니라 무시.
- `app/core/logger.py`의 `LOG_DIR = Path("data/logs")`는 실행 파일 위치가 아니라
  **프로세스 cwd 기준 상대경로**라서, Start Menu/바탕화면 바로가기(둘 다
  `WorkingDir={app}` 지정됨) 외의 실행 방식이면 로그가 엉뚱한 위치에 생길 수 있음.
  정상 설치가 제공하는 두 실행 진입점은 영향 없음(main 판정에 포함 안 됨).

**zone 특이사항 — 실측 필요**: 이 로직(`LOG_DIR`, `[Icons]`의 `WorkingDir={app}`)은
`app/` 코드가 두 브랜치에서 공유되는 부분이라 이론상 zone도 동일하게 동작해야 하지만,
zone 전용 실행 파일명(`SegmentationModelUIZone.exe`)·바로가기 구성이 실제로 같은
결과를 내는지는 아직 아무도 확인하지 않았다.

## 6. 남은 작업 — 구현이 아니라 zone 자체 검증

1. zone `build.bat`(또는 상응 빌드 스크립트)로 실제 `SegmentationModelUIZone-Setup-
   1.4.0.exe` 빌드.
2. 구버전 시나리오 재현 — 가능하면 `installer/output/`에 남아있는 이전 zone 릴리스로
   먼저 설치(없으면 같은 exe를 2회 설치해 셀프 업그레이드로 대체), 새 버전 설치
   프로그램을 `/SILENT`(대화형)로 실행해 실제 Win32 대화상자에 감지된 구버전 번호가
   정확히 표시되는지 확인, "예" 클릭 시 구버전 제거 후 새 버전이 정상 설치되는지 확인.
3. 무인 모드(`/VERYSILENT /SUPPRESSMSGBOXES`)로 재설치 시 행(hang) 없이 정상
   종료되는지 확인(BUG-031이 zone에서 재발하지 않는지).
4. 무인 제거(`unins000.exe /VERYSILENT /SUPPRESSMSGBOXES`) 후 `data\logs\` 삭제 +
   `images/annotations/checkpoints` 보존을 §5 main 절차와 동일하게 재현.
5. 최초 설치(레지스트리 키 없음) 시 팝업 없이 정상 진행되는지 확인(회귀 없음).
6. `PrivilegesRequired=lowest` 환경에서 관리자 권한 없이 레지스트리 조회 + `Exec`가
   정상 동작하는지 확인.
7. `reg query`로 zone AppId(`0997E818-6906-483C-BA3A-324FED0BFF97`) 기준 실제
   레지스트리 키 문자열이 `GetUninstallRegKey()` 계산값과 정확히 일치하는지 직접
   확인 — BUG-030과 동일한 함정이 zone에서 재현되지 않는지, 코드가 매크로 기반이라
   이론상 안전하지만 실측 없이 "안전하다"고 단정하지 않는다.

이 항목들은 전부 **검증(실행 확인) 작업**이지 코드 작성이 아니다 — implementer가
아니라 verifier에게 위임하는 것을 권장한다.

## 7. main 쪽 남은 문서 정리 (참고, 이 세션에서 직접 수정하지 않음)

main `docs/roadmap.md`의 "GitHub #22(신규) + #16 후속" 절 GitHub #22 체크박스가
코드·`QA.md`는 이미 완료 상태인데도 여전히 `[ ]`로 남아있다 — main 워크트리 소관이라
이 세션(zone 플래너)에서 직접 고치지 않는다. main 리더가 다음 세션에서 체크박스만
정정하면 된다(코드/QA.md 변경 불필요).

## 8. `docs/decisions-needed.md` 확인 결과

`#22`/`#16` 패턴으로 grep한 결과 zone `docs/decisions-needed.md`에 해당 항목이
없음을 확인(2026-08-29 스펙 시점엔 "결정 필요 1건"으로 등록되어 있었으나, 이미
사용자가 결정을 마치고 항목이 제거된 상태로 보임) — 이번 세션에서 추가로 삭제할 것
없음, 변경하지 않았다.
