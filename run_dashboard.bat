@echo off
setlocal
cd /d "%~dp0"

REM ---------------------------------------------------------------
REM  LLMO Analysis Dashboard - launcher
REM
REM  ASCII only, CRLF line endings. Do not add non-ASCII characters:
REM  cmd.exe reads this file in the console code page (CP932 on a
REM  Japanese Windows), so UTF-8 text here breaks parsing.
REM ---------------------------------------------------------------

set "APP_URL=http://localhost:8501"

echo ============================================================
echo   LLMO Analysis Dashboard
echo ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found.
    echo         Run setup_dashboard.bat first.
    echo.
    pause
    exit /b 1
)

echo [1/2] Fetching the latest data ^(git pull^)...
where git >nul 2>nul
if errorlevel 1 (
    echo       [WARN] "git" was not found on PATH. Using local data.
) else (
    git pull --ff-only
    if errorlevel 1 (
        echo       [WARN] git pull failed. Using local data.
    )
)
echo.

echo [2/2] Starting the app at %APP_URL%
echo       The browser opens in a few seconds.
echo       Press Ctrl+C in this window to stop it.
echo.

REM Open the browser from a detached shell after a short delay, so the
REM server has time to bind the port. ping is used as a portable sleep.
start "" /min cmd /c "ping -n 5 127.0.0.1 >nul & start %APP_URL%"

".venv\Scripts\python.exe" -m streamlit run "app\main.py" --server.port 8501

echo.
echo The app has stopped.
pause
