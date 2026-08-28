@echo off
rem Segmentation Model UI - one-shot build script
rem (1) clean  (2) generate metadata  (3) PyInstaller  (4) Inno Setup
rem NOTE: keep this file ASCII-only. cmd.exe's batch-file read-ahead buffering
rem can misalign multi-byte (Korean) text even after chcp 65001, corrupting
rem later tokens on non-English-locale Windows.
setlocal

set "ROOT=%~dp0"
cd /d "%ROOT%"

rem Use one interpreter for validation, metadata generation, and PyInstaller.
if defined PYTHON_EXE if exist "%PYTHON_EXE%" set "BUILD_PYTHON=%PYTHON_EXE%"
if not defined BUILD_PYTHON for /f "delims=" %%P in ('py -3.12 -c "import sys; print(sys.executable)" 2^>nul') do if exist "%%P" set "BUILD_PYTHON=%%P"
if not defined BUILD_PYTHON if defined CONDA_PREFIX if exist "%CONDA_PREFIX%\python.exe" set "BUILD_PYTHON=%CONDA_PREFIX%\python.exe"
if not defined BUILD_PYTHON for /f "delims=" %%P in ('where python.exe 2^>nul ^| findstr /i /v "WindowsApps"') do if not defined BUILD_PYTHON set "BUILD_PYTHON=%%P"
if not defined BUILD_PYTHON (
    echo [ERROR] Python 3.12 was not found.
    echo         Install Python 3.12 from python.org and enable the py launcher.
    goto :error
)

echo [0/4] Checking Python 3.12 and offline runtime packages: "%BUILD_PYTHON%"
"%BUILD_PYTHON%" -c "import sys; assert sys.version_info[:2] == (3, 12), 'Python 3.12 is required'; import PyQt6, PyInstaller, torch, torchvision, cv2, numpy, PIL, albumentations, openpyxl, matplotlib; print('Python and offline runtime packages OK')"
if errorlevel 1 (
    echo [ERROR] Python 3.12 with all build/runtime packages is required.
    echo         Install them into the selected Python:
    echo         "%BUILD_PYTHON%" -m pip install -r requirements.txt
    echo         "%BUILD_PYTHON%" -m pip install PyInstaller
    goto :error
)

echo [1/4] Cleaning build\ and dist\ ...
if exist build\build rmdir /s /q build\build
if exist build\version_info.txt del /q build\version_info.txt
if exist build\release-defines.iss del /q build\release-defines.iss
if exist dist rmdir /s /q dist
if exist dist (
    echo [ERROR] dist\ is still in use. Close the installed app and try again.
    goto :error
)

echo [2/4] Generating release metadata ...
"%BUILD_PYTHON%" scripts\generate_version_info.py
if errorlevel 1 goto :error

echo [3/4] PyInstaller build (build.spec) ...
"%BUILD_PYTHON%" -m PyInstaller build.spec
if errorlevel 1 goto :error

echo [4/4] Inno Setup installer build (installer\setup.iss) ...
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
