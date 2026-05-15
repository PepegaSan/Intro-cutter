@echo off
setlocal EnableExtensions
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0intro_cut.ps1"
set "EC=%ERRORLEVEL%"
if not "%EC%"=="0" (
  echo.
  echo Fehlercode %EC%
  pause
)
exit /b %EC%
