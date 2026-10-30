@echo off
cd /d "%~dp0"
echo 必要なライブラリを入れています。しばらくお待ちください...
echo.
set PY=
where py >nul 2>nul && set PY=py
if not defined PY where python >nul 2>nul && set PY=python
if not defined PY (
  echo Python が見つかりません。Python を入れてから、もう一度ダブルクリックしてください。
  pause
  exit /b 1
)
%PY% -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo ライブラリを入れられませんでした。上のメッセージを確認してください。
  pause
  exit /b 1
)
echo.
echo デスクトップにショートカットを作っています...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\財務エントリ自動入力.lnk'); $s.TargetPath='%~dp0起動.bat'; $s.WorkingDirectory='%~dp0'; $s.WindowStyle=7; $s.Save()"
echo.
echo 準備ができました。
echo デスクトップの「財務エントリ自動入力」をダブルクリックすると起動します。
pause
