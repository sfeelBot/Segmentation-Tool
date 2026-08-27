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
