@echo off
title Snag-All Sorting Script
REM Double-click to sort your Downloads folder. You'll see a preview and be asked before anything moves.
REM To sort a different folder, drag that folder onto this file.
where uv >nul 2>nul
if errorlevel 1 (
  echo First run: installing uv, the free helper that runs this tool. This only happens once.
  powershell -NoProfile -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  set "PATH=%USERPROFILE%\.local\bin;%PATH%"
)
uvx --from git+https://github.com/anjavera/Snag-All-Sorting-Script organize %*
echo.
pause
