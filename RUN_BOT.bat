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

%PYTHON_CMD% -u yahtzee_bot.py %*
if errorlevel 1 (
    echo.
    echo The bot exited with an error.
    pause
)
