@echo off
setlocal
set "SUPPORTPILOT_ROOT=%~dp0"

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SUPPORTPILOT_ROOT%scripts\Start-Local.ps1"
if errorlevel 1 (
  echo.
  echo SupportPilot AI could not be started. Read the message above.
  pause
  exit /b 1
)

endlocal
