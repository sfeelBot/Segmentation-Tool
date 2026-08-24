@echo off
chcp 65001 >nul
rem Segmentation Model UI — 원샷 빌드 스크립트
rem (1) build\, dist\ 정리 (2) PyInstaller onedir 빌드 (3) Inno Setup 인스톨러 빌드
setlocal

set "ROOT=%~dp0"
cd /d "%ROOT%"

echo [1/3] 기존 build\, dist\ 정리...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [2/3] PyInstaller 빌드 (build.spec)...
py -3 -m PyInstaller build.spec
if errorlevel 1 goto :error

echo [3/3] Inno Setup 인스톨러 빌드 (installer\setup.iss)...
set "ISCC=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
    echo [오류] Inno Setup 6이 설치되어 있지 않습니다. https://jrsoftware.org/isdl.php 에서 설치하세요.
    goto :error
)
"%ISCC%" installer\setup.iss
if errorlevel 1 goto :error

echo.
echo ===== 빌드 완료 =====
for %%F in ("installer\output\*.exe") do echo   %%~fF
exit /b 0

:error
echo.
echo [오류] 빌드 실패 — 위 로그를 확인하세요.
exit /b 1
