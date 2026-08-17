@echo off
chcp 65001 > nul
setlocal
cd /d "%~dp0"

echo ============================================================
echo  LLMO 分析ダッシュボード 初回セットアップ
echo ============================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [エラー] python が見つかりません。Python 3.10 以上をインストールしてください。
    pause
    exit /b 1
)

if not exist ".venv" (
    echo [1/3] 仮想環境を作成しています...
    python -m venv .venv
    if errorlevel 1 (
        echo [エラー] 仮想環境の作成に失敗しました。
        pause
        exit /b 1
    )
) else (
    echo [1/3] 既存の仮想環境を使用します。
)

echo [2/3] pip を更新しています...
call ".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet

echo [3/3] 依存関係をインストールしています(数分かかります)...
call ".venv\Scripts\python.exe" -m pip install -r requirements-dashboard.txt
if errorlevel 1 (
    echo [エラー] インストールに失敗しました。
    pause
    exit /b 1
)

if not exist "credentials" mkdir credentials

echo.
echo ============================================================
echo  セットアップ完了
echo ============================================================
echo.
echo  次の手順:
echo.
echo   1. サービスアカウントJSONを次の場所に配置してください
echo        credentials\service_account.json
echo.
echo   2. スプレッドシートIDを次のいずれかで設定してください
echo        credentials\spreadsheet_id.txt  にIDを1行で保存
echo        または環境変数 SHEETS_SPREADSHEET_ID
echo.
echo   3. run_dashboard.bat を実行してください
echo.
echo  ※ credentials フォルダは .gitignore 済みでコミットされません
echo  ※ 認証なしでも「P4 回答ビューア・差分」は利用できます
echo.
pause
