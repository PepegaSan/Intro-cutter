@echo off
setlocal
cd /d "%~dp0"

echo === Intro Cutter — install ===
python -m pip install --upgrade pip
if errorlevel 1 goto fail
python -m pip install -r requirements.txt
if errorlevel 1 goto fail

where ffmpeg >nul 2>&1
if errorlevel 1 echo [WARN] ffmpeg not found on PATH.
where ffprobe >nul 2>&1
if errorlevel 1 echo [WARN] ffprobe not found on PATH.
if not exist "%~dp0davinci_api.py" echo [WARN] davinci_api.py missing — Resolve mode will not work.

echo.
echo Done. Start: start_intro_cutter_gui.bat
pause
exit /b 0

:fail
echo Install failed.
pause
exit /b 1
