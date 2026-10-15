@echo off
rem ============================================================
rem  Zaimu Entry (kaikei-soft)
rem  Remove the Windows sign-in auto-start entry and the desktop shortcut.
rem
rem  IMPORTANT: this file must stay in Shift_JIS (CP932). See start.bat.
rem  No Japanese text inside ( ) blocks: use labels and GOTO instead.
rem ============================================================
chcp 932 >nul 2>nul
setlocal
cd /d "%~dp0"

echo.
echo   自動起動の設定を解除しています...

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
%PY% run.py --autostart-off
if errorlevel 1 goto :failed

:shortcuts
rem 以前の方式のショートカットと、デスクトップのショートカットを消す (Python が無くても行う)
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $sp=[Environment]::GetFolderPath('Startup'); Remove-Item -LiteralPath (Join-Path $sp 'ZaimuEntry-Server.lnk') -Force -ErrorAction SilentlyContinue; $d=[Environment]::GetFolderPath('Desktop'); $n=(-join ([char]0x8CA1,[char]0x52D9,[char]0x30A8,[char]0x30F3,[char]0x30C8,[char]0x30EA)); Remove-Item -LiteralPath (Join-Path $d ($n+'.url')) -Force -ErrorAction SilentlyContinue; exit 0 } catch { Write-Output $_.Exception.Message; exit 1 }"

echo   解除しました。次に PC を起動しても、自動では立ち上がりません。
echo.
echo   いま動いている財務エントリを止めるには、「データ管理」画面の
echo   「財務エントリを終了」を押してください。使いたいときは start.bat をダブルクリックします。
echo.
pause
exit /b 0

:no_python
goto :shortcuts

:failed
echo.
echo   解除に失敗しました。
echo   上に表示されているメッセージを控えて、開発者に連絡してください。
echo.
pause
exit /b 1
