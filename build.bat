@echo off
rem Segmentation Model UI - one-shot build script
rem (1) clean build\, dist\  (2) PyInstaller onedir build  (3) Inno Setup installer build
rem NOTE: keep this file ASCII-only. cmd.exe's batch-file read-ahead buffering
rem can misalign multi-byte (Korean) text even after chcp 65001, corrupting
rem later tokens on non-English-locale Windows.
setlocal

set "ROOT=%~dp0"
cd /d "%ROOT%"

echo [1/3] Cleaning build\ and dist\ ...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [2/3] PyInstaller build (build.spec) ...
py -3 -m PyInstaller build.spec
if errorlevel 1 goto :error

echo [3/3] Inno Setup installer build (installer\setup.iss) ...
set "ISCC=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
    echo [ERROR] Inno Setup 6 is not installed. Get it from https://jrsoftware.org/isdl.php
    goto :error
)
"%ISCC%" installer\setup.iss
if errorlevel 1 goto :error

echo.
echo ===== Build complete =====
for %%F in ("installer\output\*.exe") do echo   %%~fF
exit /b 0

:error
echo.
echo [ERROR] Build failed - check the log above.
exit /b 1
