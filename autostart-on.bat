@echo off
rem ============================================================
rem  Zaimu Entry (kaikei-soft)
rem  Register the server to start automatically at Windows logon,
rem  and put a shortcut to the app on the desktop.
rem ============================================================
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "APPDIR=%CD%"

if not exist "%APPDIR%\start.bat" (
  echo.
  echo   start.bat が見つかりません。
  echo   このファイルは start.bat と同じフォルダに置いてください。
  echo.
  pause
  exit /b 1
)
if not exist "%APPDIR%\start-background.vbs" (
  echo.
  echo   start-background.vbs が見つかりません。
  echo   ファイル一式をダウンロードし直してください。
  echo.
  pause
  exit /b 1
)

echo.
echo   自動起動を設定しています...

rem PowerShell 側は ASCII のみで書き、文字列は全て単一引用符を使う。
rem 二重引用符やパーセント記号を混ぜるとバッチ側の解釈で壊れるため。
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $q=[string][char]34; $W=New-Object -ComObject WScript.Shell; $sp=[Environment]::GetFolderPath('Startup'); $lnk=$W.CreateShortcut((Join-Path $sp 'ZaimuEntry-Server.lnk')); $lnk.TargetPath='wscript.exe'; $lnk.Arguments=$q+$env:APPDIR+'\start-background.vbs'+$q; $lnk.WorkingDirectory=$env:APPDIR; $lnk.WindowStyle=7; $lnk.Description='Zaimu Entry local server'; $lnk.Save(); $d=[Environment]::GetFolderPath('Desktop'); $n=(-join ([char]0x8CA1,[char]0x52D9,[char]0x30A8,[char]0x30F3,[char]0x30C8,[char]0x30EA)); Set-Content -LiteralPath (Join-Path $d ($n+'.url')) -Value @('[InternetShortcut]','URL=http://127.0.0.1:8765/') -Encoding ASCII; exit 0 } catch { Write-Output $_.Exception.Message; exit 1 }"

if errorlevel 1 (
  echo.
  echo   設定に失敗しました。
  echo   上に表示されているメッセージを控えて、開発者に連絡してください。
  echo.
  pause
  exit /b 1
)

echo   設定が完了しました。
echo.
echo     ・次回 Windows を起動したときから、財務エントリ が自動で立ち上がります。
echo     ・デスクトップに「財務エントリ」のショートカットを作成しました。
echo       ダブルクリックするとブラウザで開けます。
echo     ・黒い窓は最小化された状態で待機します。閉じるとソフトも止まります。
echo.
echo   自動起動をやめたいときは autostart-off.bat を実行してください。
echo.
echo   いま使えるように、財務エントリ を起動します。しばらくお待ちください...

start "" wscript.exe "%APPDIR%\start-background.vbs"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$n=0; while ($n -lt 90) { try { $c=New-Object Net.Sockets.TcpClient; $c.Connect('127.0.0.1',8765); $c.Close(); exit 0 } catch { Start-Sleep -Seconds 1; $n++ } }; exit 1"

if errorlevel 1 (
  echo.
  echo   時間内に起動を確認できませんでした。
  echo   タスクバーの黒い窓を開いて、表示されているメッセージを確認してください。
  echo.
  pause
  exit /b 1
)

start "" "http://127.0.0.1:8765/"
echo.
echo   起動しました。ブラウザが開かない場合は、デスクトップのショートカットを使ってください。
echo.
pause
endlocal
