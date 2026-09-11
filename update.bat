@echo off
rem ============================================================
rem  Zaimu Entry (kaikei-soft)
rem  Download the latest version and update the program files.
rem  Data (data\kaikei.db) is never touched, and is backed up first.
rem
rem  IMPORTANT: this file must stay in Shift_JIS (CP932). See start.bat.
rem  No Japanese text inside ( ) blocks: use labels and GOTO instead.
rem ============================================================
chcp 932 >nul 2>nul
setlocal
cd /d "%~dp0"
set "APPDIR=%CD%"
set "ZIPURL=https://github.com/kei-hub1/kaikei-soft/archive/refs/heads/claude/financial-entry-21-clone-o7te5r.zip"

if not exist "%APPDIR%\run.py" goto :wrong_folder

echo.
echo   財務エントリ を最新版に更新します。
echo   入力済みのデータ (data フォルダー) はそのまま残ります。
echo.

rem --- 動作中なら更新できない ---
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $c=New-Object Net.Sockets.TcpClient; $c.Connect('127.0.0.1',8765); $c.Close(); exit 1 } catch { exit 0 }"
if errorlevel 1 goto :still_running

rem --- データのバックアップ ---
if not exist "%APPDIR%\data\kaikei.db" goto :download
echo   データをバックアップしています...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $d=Join-Path $env:APPDIR 'data\backup'; New-Item -ItemType Directory -Force -Path $d | Out-Null; $n='kaikei_' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '_update.db'; Copy-Item (Join-Path $env:APPDIR 'data\kaikei.db') (Join-Path $d $n); Write-Output ('  ' + (Join-Path $d $n)); exit 0 } catch { Write-Output $_.Exception.Message; exit 1 }"
if errorlevel 1 goto :backup_failed

:download
echo.
echo   最新版をダウンロードしています...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; $tmp=Join-Path $env:TEMP ('kaikei_up_' + [Guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $tmp | Out-Null; $zip=Join-Path $tmp 'src.zip'; Invoke-WebRequest -Uri $env:ZIPURL -OutFile $zip -UseBasicParsing; Expand-Archive -LiteralPath $zip -DestinationPath $tmp -Force; $src=Get-ChildItem -LiteralPath $tmp -Directory | Select-Object -First 1; if (-not $src) { throw 'extracted folder not found' }; foreach ($i in Get-ChildItem -LiteralPath $src.FullName) { if ($i.Name -eq 'data') { continue }; $dest=Join-Path $env:APPDIR $i.Name; if ($i.Name -eq 'update.bat') { $dest=Join-Path $env:APPDIR 'update-new.bat' }; if ($i.PSIsContainer) { if (Test-Path -LiteralPath $dest) { Remove-Item -LiteralPath $dest -Recurse -Force }; Copy-Item -LiteralPath $i.FullName -Destination $dest -Recurse -Force } else { Copy-Item -LiteralPath $i.FullName -Destination $dest -Force } }; Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue; exit 0 } catch { Write-Output $_.Exception.Message; exit 1 }"
if errorlevel 1 goto :download_failed

rem --- 不要になったファイルの削除 ---
rem  Files removed upstream are not overwritten by the copy above, so delete them here.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$o=@('app\passbook.py','app\ocr.py','app\docfiles.py','app\routers\passbooks.py','static\passbook.js','scripts','app\__pycache__','app\routers\__pycache__'); foreach ($r in $o) { $t=Join-Path $env:APPDIR $r; if (Test-Path -LiteralPath $t) { Remove-Item -LiteralPath $t -Recurse -Force -ErrorAction SilentlyContinue } }"

rem --- 追加ライブラリの取り込み ---
echo.
echo   必要なライブラリを確認しています...
set "PY="
py -3 -c "import sys" >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if defined PY goto :pip
python -c "import sys" >nul 2>nul
if not errorlevel 1 set "PY=python"
if not defined PY goto :done

:pip
%PY% -m pip install -r requirements.txt --quiet --disable-pip-version-check
if errorlevel 1 echo   ライブラリの更新に失敗しました。start.bat を実行すると再度試みます。

:done
echo.
echo   更新が完了しました。
echo.
echo     ・入力済みのデータはそのままです。
echo     ・既にある顧問先に新しい勘定科目表を入れるには、
echo       「勘定科目」画面の「科目表を入れ替える」を使ってください。
echo.
rem --- このファイル自体が新しくなっていないか調べる ---
rem  update.bat is running, so it cannot overwrite itself. Receive the new one as
rem  update-new.bat and swap it in a few seconds after this window is closed.
set "SWAP="
if not exist "%APPDIR%\update-new.bat" goto :report
fc /b "%APPDIR%\update.bat" "%APPDIR%\update-new.bat" >nul 2>nul
if errorlevel 1 goto :swap_needed
del "%APPDIR%\update-new.bat" >nul 2>nul
goto :report

:swap_needed
set "SWAP=1"
echo     ・このファイル (update.bat) 自体も新しくなります。自動で入れ替えます。

:report
echo.
echo   start.bat をダブルクリックして起動してください。
echo   次回の更新も、この update.bat をダブルクリックするだけです。
echo.
pause

if not defined SWAP goto :quit
start "" /b powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Sleep -Seconds 2; $d=$env:APPDIR; Copy-Item -LiteralPath (Join-Path $d 'update-new.bat') -Destination (Join-Path $d 'update.bat') -Force; Remove-Item -LiteralPath (Join-Path $d 'update-new.bat') -Force -ErrorAction SilentlyContinue"

:quit
exit /b 0

:wrong_folder
echo.
echo   run.py が見つかりません。
echo   このファイルは start.bat と同じフォルダーに置いてください。
echo.
echo   現在のフォルダー:
echo   %APPDIR%
echo.
pause
exit /b 1

:still_running
echo.
echo   財務エントリ が起動中です。先に終了してください。
echo.
echo     1. タスクバーにある黒いウィンドウを開いて閉じる
echo     2. このファイルをもう一度ダブルクリックする
echo.
echo   自動起動を設定している場合は、黒いウィンドウを閉じれば止まります。
echo.
pause
exit /b 1

:backup_failed
echo.
echo   データのバックアップに失敗したため、更新を中止しました。
echo   上に表示されているメッセージを控えて、開発者に連絡してください。
echo.
pause
exit /b 1

:download_failed
echo.
echo   ダウンロードまたは展開に失敗しました。
echo   インターネットに接続されているか確認してください。
echo   上に表示されているメッセージを控えて、開発者に連絡してください。
echo.
pause
exit /b 1
