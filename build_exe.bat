@echo off
REM ============================================================
REM  Build KiraluxAutoCapture v2 exe using PyInstaller
REM  Run from inside autocapture\  (conda env with PyQt5 active)
REM ============================================================

cd /d "%~dp0"

echo Installing / upgrading dependencies...
pip install -r requirements.txt --quiet

echo.
echo Building executable (PyInstaller)...
REM Use dist_release / build_release to avoid OneDrive lock on dist\
pyinstaller KiraluxAutoCapture.spec --noconfirm --clean --distpath dist_release --workpath build_release

if errorlevel 1 (
    echo.
    echo BUILD FAILED  (close running exe / pause OneDrive sync and retry)
    pause
    exit /b 1
)

echo.
echo Done!
echo Executable:  dist_release\KiraluxAutoCapture_v2\KiraluxAutoCapture_v2.exe
echo Manuals:     dist_release\KiraluxAutoCapture_v2\_internal\MANUAL_en.md
echo              dist_release\KiraluxAutoCapture_v2\_internal\MANUAL_zh.md
pause
