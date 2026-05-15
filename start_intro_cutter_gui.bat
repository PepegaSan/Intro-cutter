@echo off
setlocal EnableExtensions
cd /d "%~dp0"

where py >nul 2>&1
if not errorlevel 1 (
  py -3 "%~dp0intro_cut_gui.py"
  if not errorlevel 1 exit /b 0
)

where python >nul 2>&1
if not errorlevel 1 (
  python "%~dp0intro_cut_gui.py"
  if not errorlevel 1 exit /b 0
)

echo.
echo Weder py noch python wurde gefunden, oder das Skript ist mit Fehler beendet.
echo Python installieren und: pip install -r requirements.txt
echo.
pause
exit /b 1
