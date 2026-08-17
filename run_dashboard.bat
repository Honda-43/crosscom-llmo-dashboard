@echo off
chcp 65001 > nul
setlocal
cd /d "%~dp0"

echo ============================================================
echo  LLMO 分析ダッシュボード
echo ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [エラー] 仮想環境がありません。先に setup_dashboard.bat を実行してください。
    pause
    exit /b 1
)

echo [1/2] 最新データを取得しています ^(git pull^)...
git pull --ff-only
if errorlevel 1 (
    echo.
    echo [警告] git pull に失敗しました。ローカルにあるデータで起動します。
    echo.
)

echo [2/2] アプリを起動します。ブラウザが自動で開きます。
echo        終了するには、このウィンドウで Ctrl+C を押してください。
echo.
call ".venv\Scripts\python.exe" -m streamlit run app\main.py

pause
