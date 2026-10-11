@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "DEMO_DIR=%SCRIPT_DIR%Frontend Demo"

where pnpm >nul 2>&1
if errorlevel 1 (
  echo pnpm is required. Install Node.js and pnpm, then run this script again.
  pause
  exit /b 1
)

start "GenLedge Standalone Demo" /D "%DEMO_DIR%" cmd /k "pnpm dev --host 127.0.0.1 --port 5174 --strictPort"

echo Standalone demo started in a separate window.
echo Demo: http://127.0.0.1:5174
pause
endlocal
