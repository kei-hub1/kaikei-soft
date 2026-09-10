@echo off
rem ============================================================
rem  Zaimu Entry (kaikei-soft) launcher for Windows
rem  Double-click this file to start the application.
rem ============================================================
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem --- Python を探す ---------------------------------------------------------
rem py ランチャーは PATH の設定に関係なく使えるので最優先で試す。
set "PY="
py -3 -c "import sys" >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if not defined PY (
  python -c "import sys" >nul 2>nul
  if not errorlevel 1 set "PY=python"
)

if not defined PY (
  echo.
  echo   Python が見つかりませんでした。
  echo.
  echo   https://www.python.org/downloads/windows/ からインストーラーを入手し、
  echo   最初の画面の下にある "Add python.exe to PATH" にチェックを入れてから
  echo   "Install Now" を押してください。
  echo.
  echo   インストールが終わったら、このファイルをもう一度ダブルクリックしてください。
  echo.
  pause
  exit /b 1
)

for /f "delims=" %%v in ('%PY% -c "import sys;print(sys.version.split()[0])" 2^>nul') do set "PYVER=%%v"
echo   Python %PYVER% を使用します。

rem --- 必要なライブラリを確認 ------------------------------------------------
%PY% -c "import fastapi, uvicorn, multipart" >nul 2>nul
if errorlevel 1 (
  echo.
  echo   初回起動のため、必要なライブラリをインストールします。
  echo   インターネットに接続した状態で、数分お待ちください。
  echo.
  %PY% -m pip install --upgrade pip >nul 2>nul
  %PY% -m pip install -r requirements.txt
  if errorlevel 1 (
    echo.
    echo   ライブラリのインストールに失敗しました。
    echo   上に表示されているメッセージを控えて、開発者に連絡してください。
    echo.
    pause
    exit /b 1
  )
)

%PY% -c "import fastapi, uvicorn, multipart" >nul 2>nul
if errorlevel 1 (
  echo.
  echo   ライブラリを読み込めませんでした。
  echo.
  pause
  exit /b 1
)

rem --- 起動 ------------------------------------------------------------------
echo.
echo   財務エントリ を起動します。ブラウザが自動的に開きます。
echo   終了するときは、このウィンドウで Ctrl+C を押すか、ウィンドウを閉じてください。
echo.
%PY% run.py
echo.
echo   財務エントリ を終了しました。
pause
endlocal
