@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo.
echo === Intro Cutter — Installation / Pruefung ===
echo.

where ffmpeg >nul 2>&1
if errorlevel 1 (
  echo [FEHLT] ffmpeg ist nicht im PATH.
  echo         Beispiel: Build entpacken, z.B. C:\ffmpeg\bin in PATH eintragen.
  echo         Download-Hinweise: https://www.gyan.dev/ffmpeg/builds/ oder BtbN-Builds.
) else (
  echo [OK]    ffmpeg gefunden:
  where ffmpeg
)

where ffprobe >nul 2>&1
if errorlevel 1 (
  echo [FEHLT] ffprobe ist nicht im PATH ^(gehoert zu FFmpeg^).
) else (
  echo [OK]    ffprobe gefunden:
  where ffprobe
)

echo.
echo --- Python ^(nur fuer DaVinci-Resolve-Modus^) ---
where py >nul 2>&1
if not errorlevel 1 (
  echo [OK]    py Launcher:
  where py
  py -3 --version 2>nul
) else (
  where python >nul 2>&1
  if not errorlevel 1 (
    echo [OK]    python:
    where python
    python --version 2>nul
  ) else (
    echo [INFO]  weder py noch python im PATH — Resolve-Modus braucht Python.
  )
)

echo.
echo Referenz: davinci_api.py soll unter liegen:
echo   "%~dp0..\Davinci API start\davinci_api.py"
if exist "%~dp0..\Davinci API start\davinci_api.py" (
  echo [OK]    davinci_api.py vorhanden.
) else (
  echo [WARN]  davinci_api.py nicht gefunden — Resolve-Modus funktioniert dann nicht.
)

echo.
echo GUI ^(Drag und Drop^): pip install -r requirements.txt ^(windnd unter Windows^).
echo Optional:  py -3 -m venv .venv
echo            .venv\Scripts\pip install -r requirements.txt
echo.
pause
exit /b 0
