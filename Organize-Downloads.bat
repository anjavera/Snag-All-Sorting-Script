@echo off
REM Clickable launcher for the Downloads organizer.
REM %~dp0 = the folder this .bat lives in, so the script is always found next to it.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Organize-Downloads.ps1" %*
echo.
pause
