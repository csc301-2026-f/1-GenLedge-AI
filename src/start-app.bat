@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "FRONTEND_DIR=%SCRIPT_DIR%frontend"
set "BACKEND_DIR=%SCRIPT_DIR%backend"
set "PYTHON="

where pnpm >nul 2>&1
if errorlevel 1 (
  echo pnpm is required. Install Node.js and pnpm, then run this script again.
  pause
  exit /b 1
)

if exist "%BACKEND_DIR%\.venv\Scripts\python.exe" (
  set "PYTHON=%BACKEND_DIR%\.venv\Scripts\python.exe"
) else (
  where py >nul 2>&1
  if not errorlevel 1 set "PYTHON=py -3"
)
if not defined PYTHON (
  where python >nul 2>&1
  if not errorlevel 1 set "PYTHON=python"
)
if not defined PYTHON (
  echo Python 3 is required. Install Python, then run this script again.
  pause
  exit /b 1
)

%PYTHON% -c "import flask" >nul 2>&1
if errorlevel 1 (
  echo Flask is not installed for %PYTHON%.
  echo Install it with: %PYTHON% -m pip install -r "%BACKEND_DIR%\requirements-dev.txt"
  pause
  exit /b 1
)

start "GenLedge Frontend" /D "%FRONTEND_DIR%" cmd /k "pnpm dev --host 127.0.0.1"
start "GenLedge Backend" /D "%BACKEND_DIR%" cmd /k "%PYTHON% main.py"

echo Frontend and backend started in separate windows.
echo Frontend: http://127.0.0.1:5173
echo Backend:  http://127.0.0.1:5000
pause
endlocal
