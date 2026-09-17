@echo off
chcp 932 >nul
rem 定型文書作成ツールを起動します（コンソール画面は表示しません）
cd /d "%~dp0"
where pythonw >nul 2>&1
if %errorlevel%==0 (
    start "" pythonw "%~dp0main.py"
    exit /b
)
where pyw >nul 2>&1
if %errorlevel%==0 (
    start "" pyw "%~dp0main.py"
    exit /b
)
echo Python が見つかりません。Python をインストールしてから、もう一度実行してください。
pause
