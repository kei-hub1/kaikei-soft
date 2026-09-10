@echo off
rem 財務エントリ 起動 (Windows)
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python が見つかりません。https://www.python.org/ からインストールしてください。
  pause
  exit /b 1
)
python -c "import fastapi, uvicorn, multipart" >nul 2>nul
if errorlevel 1 (
  echo 必要なライブラリをインストールしています...
  python -m pip install -r requirements.txt
)
python run.py
pause
