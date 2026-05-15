@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if "%~1"=="" (
  echo.
  echo Keine Datei uebergeben. Ziehe eine Videodatei auf diese BAT-Datei,
  echo oder starte "start_intro_cutter.bat" und waehle eine Datei.
  echo.
  pause
  exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0intro_cut.ps1" -InputPath "%~1"
set "EC=%ERRORLEVEL%"
if not "%EC%"=="0" (
  echo.
  echo Fehlercode %EC%
  pause
)
exit /b %EC%
