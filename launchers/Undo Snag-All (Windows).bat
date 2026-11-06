@echo off
title Snag-All Sorting Script - Undo
REM Double-click to put back everything the last sort moved.
where uv >nul 2>nul
if errorlevel 1 (
  echo First run: installing uv, the free helper that runs this tool. This only happens once.
  powershell -NoProfile -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  set "PATH=%USERPROFILE%\.local\bin;%PATH%"
)
uvx --from git+https://github.com/anjavera/Snag-All-Sorting-Script organize --undo
echo.
pause
