@echo off
REM Milso Launcher (Windows sub-app) entry point.
setlocal
set "HERE=%~dp0"
if exist "%HERE%.venv\Scripts\python.exe" (
  "%HERE%.venv\Scripts\python.exe" "%HERE%run.py" %*
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo Python 3.11+ not found. Run setup-win.bat to install it.
    exit /b 1
  )
  python "%HERE%run.py" %*
)
