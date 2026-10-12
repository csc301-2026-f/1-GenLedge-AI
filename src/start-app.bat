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

%PYTHON% -c "import flask, sqlalchemy" >nul 2>&1
if errorlevel 1 (
  echo Flask and SQLAlchemy are required for %PYTHON%.
  echo Install it with: %PYTHON% -m pip install -r "%BACKEND_DIR%\requirements-dev.txt"
  pause
  exit /b 1
)

pushd "%BACKEND_DIR%"
echo.
echo ===== Database connection status =====
%PYTHON% -m flask --app main auth-db-check
if errorlevel 1 (
  popd
  echo Database connection check failed. The frontend and backend were not started.
  pause
  exit /b 1
)
echo.
choice /C YN /N /M "Continue with migrations and start services? [Y/N] "
if errorlevel 2 (
  popd
  echo Startup cancelled.
  exit /b 0
)
%PYTHON% -m flask --app main auth-init-db
if errorlevel 1 (
  popd
  echo Database migration failed. The frontend and backend were not started.
  pause
  exit /b 1
)
popd

start "GenLedge Frontend" /D "%FRONTEND_DIR%" cmd /k "pnpm dev --host 127.0.0.1 --port 5173 --strictPort"
start "GenLedge Backend" /D "%BACKEND_DIR%" cmd /k "%PYTHON% main.py"

echo Connected frontend and Flask backend started in separate windows.
echo Frontend: http://127.0.0.1:5173
echo Backend:  http://127.0.0.1:5000
pause
endlocal
