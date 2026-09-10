@echo off
rem ============================================================
rem  Zaimu Entry (kaikei-soft)
rem  Remove the Windows logon auto-start entry and the desktop shortcut.
rem ============================================================
chcp 65001 >nul
setlocal

echo.
echo   自動起動の設定を解除しています...

powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $sp=[Environment]::GetFolderPath('Startup'); Remove-Item -LiteralPath (Join-Path $sp 'ZaimuEntry-Server.lnk') -Force -ErrorAction SilentlyContinue; $d=[Environment]::GetFolderPath('Desktop'); $n=(-join ([char]0x8CA1,[char]0x52D9,[char]0x30A8,[char]0x30F3,[char]0x30C8,[char]0x30EA)); Remove-Item -LiteralPath (Join-Path $d ($n+'.url')) -Force -ErrorAction SilentlyContinue; exit 0 } catch { Write-Output $_.Exception.Message; exit 1 }"

if errorlevel 1 (
  echo.
  echo   解除に失敗しました。
  echo   上に表示されているメッセージを控えて、開発者に連絡してください。
  echo.
  pause
  exit /b 1
)

echo   解除しました。次回 Windows を起動しても自動では立ち上がりません。
echo.
echo   いま動いているソフトを止めるには、タスクバーにある黒い窓を開いて
echo   閉じてください。使いたいときは start.bat をダブルクリックします。
echo.
pause
endlocal
