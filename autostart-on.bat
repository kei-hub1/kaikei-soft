@echo off
rem ============================================================
rem  Zaimu Entry (kaikei-soft)
rem  Register the server to start automatically at Windows logon,
rem  and put a shortcut to the app on the desktop.
rem
rem  IMPORTANT: this file must stay in Shift_JIS (CP932). See start.bat.
rem  No Japanese text inside ( ) blocks: use labels and GOTO instead.
rem ============================================================
chcp 932 >nul 2>nul
setlocal
cd /d "%~dp0"
set "APPDIR=%CD%"
set "VBSFILE=%APPDIR%\start-background.vbs"

if not exist "%APPDIR%\start.bat" goto :no_files
if not exist "%APPDIR%\run.py" goto :no_files
if exist "%VBSFILE%" goto :register

rem --- start-background.vbs が無ければ作る (内容は ASCII のみ) ---
echo.
echo   起動用ファイル start-background.vbs を作成します。
echo Set sh = CreateObject("WScript.Shell")> "%VBSFILE%"
echo Set fso = CreateObject("Scripting.FileSystemObject")>> "%VBSFILE%"
echo Set env = sh.Environment("PROCESS")>> "%VBSFILE%"
echo env("KAIKEI_NO_BROWSER") = "1">> "%VBSFILE%"
echo base = fso.GetParentFolderName(WScript.ScriptFullName)>> "%VBSFILE%"
echo sh.CurrentDirectory = base>> "%VBSFILE%"
echo sh.Run Chr(34) + base + "\start.bat" + Chr(34) + " --no-browser", 7, False>> "%VBSFILE%"
if not exist "%VBSFILE%" goto :vbs_failed

:register
echo.
echo   自動起動を設定しています...

rem PowerShell 側は ASCII のみで書き、文字列は全て単一引用符を使う。
rem 二重引用符やパーセント記号を混ぜるとバッチ側の解釈で壊れるため。
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $q=[string][char]34; $W=New-Object -ComObject WScript.Shell; $sp=[Environment]::GetFolderPath('Startup'); $lnk=$W.CreateShortcut((Join-Path $sp 'ZaimuEntry-Server.lnk')); $lnk.TargetPath='wscript.exe'; $lnk.Arguments=$q+$env:APPDIR+'\start-background.vbs'+$q; $lnk.WorkingDirectory=$env:APPDIR; $lnk.WindowStyle=7; $lnk.Description='Zaimu Entry local server'; $lnk.Save(); $d=[Environment]::GetFolderPath('Desktop'); $n=(-join ([char]0x8CA1,[char]0x52D9,[char]0x30A8,[char]0x30F3,[char]0x30C8,[char]0x30EA)); Set-Content -LiteralPath (Join-Path $d ($n+'.url')) -Value @('[InternetShortcut]','URL=http://127.0.0.1:8765/') -Encoding ASCII; exit 0 } catch { Write-Output $_.Exception.Message; exit 1 }"
if errorlevel 1 goto :ps_failed

echo   設定が完了しました。
echo.
echo     * 次回 Windows を起動したときから、財務エントリ が自動で立ち上がります。
echo     * デスクトップに「財務エントリ」のショートカットを作成しました。
echo       ダブルクリックするとブラウザで開けます。
echo     * 黒い窓は最小化された状態で待機します。閉じるとソフトも止まります。
echo.
echo   自動起動をやめたいときは autostart-off.bat を実行してください。
echo.
echo   いま使えるように、財務エントリ を起動します。しばらくお待ちください...

start "" wscript.exe "%VBSFILE%"

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
echo   start.bat または run.py が見つかりません。
echo   このファイルは start.bat と同じフォルダに置いてください。
echo.
echo   現在のフォルダ:
echo   %APPDIR%
echo.
pause
exit /b 1

:vbs_failed
echo.
echo   start-background.vbs を作成できませんでした。
echo   フォルダの書き込み権限を確認してください。
echo.
pause
exit /b 1

:ps_failed
echo.
echo   設定に失敗しました。
echo   上に表示されているメッセージを控えて、開発者に連絡してください。
echo.
pause
exit /b 1

:slow
echo.
echo   時間内に起動を確認できませんでした。
echo   タスクバーの黒い窓を開いて、表示されているメッセージを確認してください。
echo   自動起動の設定そのものは完了しています。
echo.
pause
exit /b 1
