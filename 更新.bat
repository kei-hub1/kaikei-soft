@echo off
cd /d "%~dp0"
echo 財務エントリ自動入力を最新の版にします。
echo 自動入力の画面を開いている場合は、先に閉じてください。
echo.
pause
set UPD=%TEMP%\zaimu_update
if exist "%UPD%" rmdir /s /q "%UPD%"
mkdir "%UPD%"
echo 最新の版をダウンロードしています...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/kei-hub1/kaikei-soft/archive/refs/heads/claude/sleepy-heisenberg-zcx9hn.zip' -OutFile '%UPD%\new.zip'; Expand-Archive -Path '%UPD%\new.zip' -DestinationPath '%UPD%' -Force"
if errorlevel 1 (
  echo.
  echo ダウンロードできませんでした。ネットにつながっているか確認してください。
  pause
  exit /b 1
)
set SRC=
for /d %%D in ("%UPD%\kaikei-soft-*") do set SRC=%%D
if not defined SRC (
  echo ダウンロードしたファイルの形が想定と違います。
  pause
  exit /b 1
)
rem 入力のきろくのフォルダーは ZIP に入っていないので、そのまま残る。実行中のこのファイルは上書きしない。
robocopy "%SRC%" "%~dp0." /E /XF 更新.bat /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (
  echo.
  echo ファイルを上書きできませんでした。自動入力の画面を閉じてから、もう一度ダブルクリックしてください。
  pause
  exit /b 1
)
rmdir /s /q "%UPD%"
echo.
echo 最新の版にしました。
pause
