@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_CMD=py -3"
) else (
    where python >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=python"
)

if not defined PYTHON_CMD (
    echo Python 3 was not found. Install it from https://www.python.org/downloads/windows/
    pause
    exit /b 1
)

%PYTHON_CMD% scripts\setup_windows.py --skip-build %*
if errorlevel 1 (
    echo.
    echo Setup failed. Review the error above, then run this file again.
    pause
    exit /b 1
)

echo.
echo Setup finished. Start the bot with RUN_BOT.bat.
pause
