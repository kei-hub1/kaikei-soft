@echo off
rem ============================================================
rem  Zaimu Entry (kaikei-soft)
rem  Register the server to start automatically at Windows sign-in,
rem  and put a shortcut to the app on the desktop.
rem
rem  The server is registered in HKCU\...\CurrentVersion\Run and started
rem  with pythonw.exe (no console window). See app\autostart.py.
rem  The old method (Startup folder shortcut + start-background.vbs) is
rem  removed automatically.
rem
rem  IMPORTANT: this file must stay in Shift_JIS (CP932). See start.bat.
rem  No Japanese text inside ( ) blocks: use labels and GOTO instead.
rem ============================================================
chcp 932 >nul 2>nul
setlocal
cd /d "%~dp0"
set "APPDIR=%CD%"
if not exist "%APPDIR%\run.py" goto :no_files

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
rem --- 必要なライブラリを確認 ---
%PY% -c "import fastapi, uvicorn, multipart" >nul 2>nul
if not errorlevel 1 goto :ask
echo.
echo   必要なライブラリをインストールします。数分お待ちください。
echo.
%PY% -m pip install -r requirements.txt
if errorlevel 1 goto :pip_failed

:ask
echo.
echo   Windows にサインインしたとき、財務エントリ が自動で起動するように設定します。
echo   (管理者権限は不要です。設定はサインイン中のユーザーだけに入ります)
echo.
set "NB="
choice /c YN /m "  起動したら、ブラウザで画面も開きますか"
if errorlevel 2 set "NB=--no-browser"

echo.
%PY% run.py --autostart-on %NB%
if errorlevel 1 goto :reg_failed

rem --- デスクトップのショートカット ---
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $d=[Environment]::GetFolderPath('Desktop'); $n=(-join ([char]0x8CA1,[char]0x52D9,[char]0x30A8,[char]0x30F3,[char]0x30C8,[char]0x30EA)); Set-Content -LiteralPath (Join-Path $d ($n+'.url')) -Value @('[InternetShortcut]','URL=http://127.0.0.1:8765/') -Encoding ASCII; exit 0 } catch { Write-Output $_.Exception.Message; exit 1 }"

echo.
echo   設定が完了しました。
echo.
echo     * 次に PC を起動してサインインしたときから、財務エントリ が自動で立ち上がります。
echo     * 黒い窓は出ません。終了するときは「データ管理」画面の「財務エントリを終了」を使います。
echo     * デスクトップに「財務エントリ」のショートカットを作りました。
echo     * 設定の状態は「データ管理」画面でも確認・変更できます。
echo.
echo   自動起動をやめたいときは autostart-off.bat を実行してください。
echo.
echo   いま使えるように起動しています。しばらくお待ちください...

powershell -NoProfile -ExecutionPolicy Bypass -Command "$n=0; while ($n -lt 90) { try { $c=New-Object Net.Sockets.TcpClient; $c.Connect('127.0.0.1',8765); $c.Close(); exit 0 } catch { Start-Sleep -Seconds 1; $n++ } }; exit 1"
if errorlevel 1 goto :slow

start "" "http://127.0.0.1:8765/"
echo.
echo   起動しました。ブラウザが開かない場合は、デスクトップのショートカットを使ってください。
echo.
pause
exit /b 0

:no_files
echo.
echo   run.py が見つかりません。
echo   このファイルは start.bat と同じフォルダーに置いてください。
echo.
echo   現在のフォルダー:
echo   %APPDIR%
echo.
pause
exit /b 1

:no_python
echo.
echo   Python が見つかりませんでした。
echo   先に start.bat をダブルクリックして、表示される案内に従ってください。
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

:reg_failed
echo.
echo   設定に失敗しました。
echo   上に表示されているメッセージを控えて、開発者に連絡してください。
echo.
pause
exit /b 1

:slow
echo.
echo   時間内に起動を確認できませんでした。
echo   原因は次のファイルに記録されています:
echo   %APPDIR%\data\logs\server.log
echo   自動起動の設定そのものは完了しています。
echo.
pause
exit /b 1
