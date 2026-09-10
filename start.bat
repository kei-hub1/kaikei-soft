@echo off
rem Zaimu Entry launcher (Windows)
chcp 65001 >nul
cd /d "%~dp0"
python --version >nul 2>nul
if errorlevel 1 (
  echo Python が見つかりません。https://www.python.org/ からインストールしてください。
  echo インストール時に "Add python.exe to PATH" にチェックを入れてください。
  pause
  exit /b 1
)
python -c "import fastapi, uvicorn, multipart" >nul 2>nul
if errorlevel 1 (
  echo 必要なライブラリをインストールしています...
  python -m pip install -r requirements.txt
  if errorlevel 1 (
    echo ライブラリのインストールに失敗しました。
    pause
    exit /b 1
  )
)
echo 財務エントリ を起動します。終了するにはこのウィンドウで Ctrl+C を押すか、ウィンドウを閉じてください。
python run.py
pause
