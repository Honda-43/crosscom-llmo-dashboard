@echo off
setlocal
cd /d "%~dp0"

REM ---------------------------------------------------------------
REM  LLMO Analysis Dashboard - first time setup
REM
REM  ASCII only, CRLF line endings. Do not add non-ASCII characters:
REM  cmd.exe reads this file in the console code page (CP932 on a
REM  Japanese Windows), so UTF-8 text here breaks parsing.
REM ---------------------------------------------------------------

echo ============================================================
echo   LLMO Analysis Dashboard - Setup
echo ============================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] "python" was not found on PATH.
    echo         Install Python 3.10 or later and enable "Add to PATH".
    echo.
    pause
    exit /b 1
)

if exist ".venv\Scripts\python.exe" (
    echo [1/3] Using the existing virtual environment ^(.venv^).
) else (
    echo [1/3] Creating the virtual environment ^(.venv^)...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create the virtual environment.
        echo.
        pause
        exit /b 1
    )
)

echo [2/3] Upgrading pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
if errorlevel 1 (
    echo [ERROR] Failed to upgrade pip.
    echo.
    pause
    exit /b 1
)

echo [3/3] Installing dependencies ^(this can take a few minutes^)...
".venv\Scripts\python.exe" -m pip install -r requirements-dashboard.txt
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies.
    echo.
    pause
    exit /b 1
)

if not exist "credentials" mkdir "credentials"

echo.
echo ============================================================
echo   Setup complete
echo ============================================================
echo.
echo   Next steps:
echo.
echo     1. Put the service account JSON here:
echo          credentials\service_account.json
echo.
echo     2. Set the spreadsheet id, either:
echo          credentials\spreadsheet_id.txt   ^(one line^)
echo        or the SHEETS_SPREADSHEET_ID environment variable.
echo.
echo     3. Run run_dashboard.bat
echo.
echo   Notes:
echo     - The credentials folder is in .gitignore and is never committed.
echo     - Page "P4" works without credentials ^(reads data\raw only^).
echo.
pause
