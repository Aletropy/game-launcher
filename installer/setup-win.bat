@echo off
REM Milso Launcher one-click Windows installer.
REM Usage: setup-win.bat [-Target DIR] [-Yes]
setlocal EnableDelayedExpansion
set "TARGET=%LOCALAPPDATA%\MilsoLauncher"
set "YES=0"
:args
if "%~1"=="" goto done_args
if /I "%~1"=="-Target" set "TARGET=%~2" & shift & shift & goto args
if /I "%~1"=="-Yes" set "YES=1" & shift & goto args
if /I "%~1"=="--check" call :check_only & exit /b %ERRORLEVEL%
shift
goto args
:done_args
echo Installing Milso Launcher (Windows) into %TARGET%
call :ensure_python || exit /b 1
if not exist "%TARGET%" mkdir "%TARGET%"
REM Copy payload (this folder) except .venv and user data.
robocopy "%~dp0" "%TARGET%" /E /XD .venv Prefix prefixes backups Saves dist .git /XF *.pyc >nul
if errorlevel 8 exit /b 1
cd /d "%TARGET%"
if not exist ".venv" (
  echo Creating virtualenv...
  python -m venv ".venv" || exit /b 1
)
echo Installing dependencies (PySide6, this can take a minute)...
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt || exit /b 1
".venv\Scripts\python.exe" -c "import PySide6" || exit /b 1
REM Start Menu shortcut + shim.
set "SM=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Milso Launcher"
if not exist "%SM%" mkdir "%SM%"
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%SM%\Milso Launcher.lnk'); $s.TargetPath='%TARGET%\.venv\Scripts\pythonw.exe'; $s.Arguments='\"%TARGET%\run.py\"'; $s.WorkingDirectory='%TARGET%'; $s.IconLocation='%TARGET%\icon.png'; $s.Save()"
echo Done. Launch from Start Menu or run: run-win.bat
exit /b 0

:ensure_python
where python >nul 2>nul
if %ERRORLEVEL%==0 (
  for /f %%v in ('python -c "import sys; print(1 if sys.version_info^>=(3,11) else 0)"') do set OK=%%v
  if "!OK!"=="1" (
    python -c "import venv" >nul 2>nul
    if !ERRORLEVEL!==0 exit /b 0
  )
)
echo Python 3.11+ with venv not found.
where winget >nul 2>nul
if %ERRORLEVEL%==0 (
  echo Installing Python via winget...
  winget install -e --id Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements
  where python >nul 2>nul
  if !ERRORLEVEL!==0 exit /b 0
  echo winget install finished but python is still not on PATH. Close and reopen the terminal, then retry.
  exit /b 1
)
echo Install Python 3.11+ from https://www.python.org/downloads/ (tick "Add to PATH"), then re-run setup-win.bat.
exit /b 1

:check_only
call :ensure_python
if %ERRORLEVEL%==0 ( echo Checks passed. ) else ( echo Checks failed. )
exit /b %ERRORLEVEL%
