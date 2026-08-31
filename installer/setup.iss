; Segmentation Model UI — Inno Setup 스크립트
; 빌드 대상: PyInstaller onedir 산출물 dist\SegmentationModelUI\ 전체
; 사용: "ISCC.exe installer\setup.iss" (build.bat이 dist\ 생성 후 자동 호출)

#include "..\build\release-defines.iss"

[Setup]
AppId={{{#MyAppId}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyProductSlug}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; per-user 설치: PrivilegesRequired=lowest 이면 {autopf}가 관리자 권한 없이도
; 쓰기 가능한 {localappdata}\Programs 로 자동 해석된다 (Inno Setup 6 "Auto" 상수).
; 앱이 설치 폴더 바로 밑에 data\·projects\ 를 만들어 이미지·체크포인트를 쓰기
; 때문에, admin 권한으로 Program Files에 설치하면 표준 사용자 실행 시 쓰기
; 권한 문제가 생길 수 있어 관리자 권한이 필요 없는 per-user 설치를 기본으로 한다.
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=output
OutputBaseFilename={#MyProductSlug}-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
; 소스 저장소 경로를 직접 참조 (dist\ 아래 레이아웃은 PyInstaller 버전에 따라
; onedir datas가 _internal\ 하위로 들어가는 등 바뀔 수 있어 MyDistDir 기준으로
; 잡으면 깨지기 쉽다 — app_icon.ico는 항상 저장소에 존재하므로 이쪽이 안전).
SetupIconFile=..\app\resources\app_icon.ico

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Tasks]
Name: "desktopicon"; Description: "바탕화면에 바로가기 만들기"; GroupDescription: "추가 아이콘:"; Flags: unchecked

[Files]
Source: "{#MyDistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

; BUG-016: 앱이 런타임에 {app}\data\logs 밑에 만드는 로그 파일(app.log/errors.log/perf.log)은
; [Files]로 설치된 적이 없어 Inno Setup 기본 제거 로직이 추적하지 못하고 무인 제거 후에도
; 남는다. images/annotations/checkpoints 등 사용자 데이터는 보존해야 하므로 data\ 전체가
; 아니라 logs\ 폴더만 명시적으로 제거 대상에 포함한다.
[UninstallDelete]
Type: filesandordirs; Name: "{app}\data\logs"

[Code]
function GetUninstallRegKey(): String;
begin
  // BUG-030: 이전엔 ISPP의 SetupSetting 빌트인 함수로 [Setup] 섹션 AppId 값을 읽었는데,
  // AppId={{{#MyAppId}} 표현식을 Inno가 "{{" -> "{" 로 이스케이프 해제하기 *이전의* 원시
  // 텍스트를 돌려줘 "{{GUID}"(중괄호 2개)가 되어버리고, 실제 언인스톨 레지스트리 키는
  // "{GUID}"(중괄호 1개)라 영원히 불일치했다. {#MyAppId}는 전처리기 매크로라 컴파일
  // 타임에 이스케이프 없이 순수 GUID 문자열로 바로 치환되므로, 여기서 중괄호를 직접
  // 한 번만 감싸 실제 레지스트리 키와 정확히 일치시킨다.
  Result := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{{#MyAppId}}_is1';
end;

// GitHub #22: 설치 시작 시 기존 버전이 설치되어 있으면 안내 후, 사용자가 동의하면
// 기존 언인스톨러를 조용히 실행해 제거한 뒤 새 버전 설치를 계속 진행한다.
// PrivilegesRequired=lowest(per-user 설치)이므로 admin/user 레지스트리 루트를
// 하드코딩하지 않고 권한에 따라 자동 매핑되는 HKA 루트로 레지스트리를 조회한다.
// 주의: 일반 MsgBox()는 /SUPPRESSMSGBOXES를 무시하고 항상 실제 대화상자(#32770)를
// 띄워 무인 설치(/VERYSILENT /SUPPRESSMSGBOXES)를 영원히 멈춰 세운다 — 실제로 재현해
// 확인함(BUG-030 수정 직후 GetUninstallRegKey()가 정상 동작하자 이 문제가 드러남).
// 반드시 SuppressibleMsgBox()를 써야 하며, 무인 모드의 기본 응답은 "계속 진행"(자동
// 업그레이드가 이 기능의 목적이므로 IDYES/IDOK)으로 둔다.
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
