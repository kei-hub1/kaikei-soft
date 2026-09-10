@echo off
rem ============================================================
rem  Zaimu Entry (kaikei-soft) launcher for Windows
rem  Double-click this file to start the application.
rem
rem  IMPORTANT: this file must stay in Shift_JIS (CP932).
rem  cmd.exe mis-parses multibyte characters in UTF-8 batch files and can
rem  split a line in the middle of a character, so never save it as UTF-8.
rem  For the same reason, no Japanese text is placed inside ( ) blocks.
rem ============================================================
chcp 932 >nul 2>nul
setlocal
cd /d "%~dp0"

rem --- Python を探す (py ランチャーは PATH 設定に関係なく使えるので優先) ---
set "PY="
py -3 -c "import sys" >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if defined PY goto :found
python -c "import sys" >nul 2>nul
if not errorlevel 1 set "PY=python"
if defined PY goto :found
goto :no_python

:found
for /f "delims=" %%v in ('%PY% -c "import sys;print(sys.version.split()[0])" 2^>nul') do set "PYVER=%%v"
echo   Python %PYVER% を使用します。

rem --- 必要なライブラリを確認 ---
%PY% -c "import fastapi, uvicorn, multipart" >nul 2>nul
if not errorlevel 1 goto :launch

echo.
echo   初回起動のため、必要なライブラリをインストールします。
echo   インターネットに接続した状態で、数分お待ちください。
echo.
%PY% -m pip install --upgrade pip >nul 2>nul
%PY% -m pip install -r requirements.txt
if errorlevel 1 goto :pip_failed
%PY% -c "import fastapi, uvicorn, multipart" >nul 2>nul
if errorlevel 1 goto :pip_failed

:launch
echo.
echo   財務エントリ を起動します。ブラウザが自動的に開きます。
echo   終了するときは、このウィンドウで Ctrl+C を押すか、ウィンドウを閉じてください。
echo.
%PY% run.py %*
echo.
echo   財務エントリ を終了しました。
pause
exit /b 0

:no_python
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

:pip_failed
echo.
echo   ライブラリのインストールに失敗しました。
echo   上に表示されているメッセージを控えて、開発者に連絡してください。
echo.
pause
exit /b 1
