@echo off
chcp 932 >nul
setlocal
cd /d "%~dp0"
title 定型文書作成ツール　初回セットアップ

rem ============================================================
rem  必要なライブラリのインストール（初回のみ）
rem ============================================================

set "PY="

py -3 -c "import sys" >nul 2>&1
if not errorlevel 1 (
    set "PY=py -3"
    goto :found
)
python -c "import sys" >nul 2>&1
if not errorlevel 1 (
    set "PY=python"
    goto :found
)

echo.
echo   Python が見つかりません。
echo.
echo   python.org から Python をインストールしてください。
echo   インストール画面で「Add python.exe to PATH」に必ずチェックを入れてください。
echo.
echo   https://www.python.org/downloads/windows/
echo.
pause
exit /b 1

:found
echo.
echo   使用する Python：
%PY% -c "import sys; print('   ' + sys.executable); print('   バージョン ' + sys.version.split()[0])"
echo.
echo   ライブラリをインストールしています。しばらくお待ちください...
echo.

%PY% -m pip install --upgrade pip
%PY% -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo   インストールに失敗しました。
    echo   インターネットに接続されているか確認して、もう一度実行してください。
    echo.
    pause
    exit /b 1
)

echo.
echo   インストール結果を確認しています...
%PY% -c "import docx, tkinter" >nul 2>&1
if errorlevel 1 (
    echo.
    echo   確認できませんでした。「診断.bat」をダブルクリックして原因をお知らせください。
    echo.
    pause
    exit /b 1
)

echo.
echo   セットアップが完了しました。
echo   「起動.bat」をダブルクリックして起動してください。
echo.
pause
exit /b 0
