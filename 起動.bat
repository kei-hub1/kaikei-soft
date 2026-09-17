@echo off
chcp 932 >nul
setlocal
cd /d "%~dp0"
title 定型文書作成ツール

rem ============================================================
rem  定型文書作成ツール　起動
rem ============================================================

set "PY="
set "PYW="

rem --- Python を探す（py ランチャー → python の順）---
py -3 -c "import sys" >nul 2>&1
if not errorlevel 1 (
    set "PY=py -3"
    set "PYW=pyw -3"
    goto :found
)
python -c "import sys" >nul 2>&1
if not errorlevel 1 (
    set "PY=python"
    set "PYW=pythonw"
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
echo   ※ Microsoft Store の Python では動かないことがあります。
echo.
pause
exit /b 1

:found
rem pyw が無い環境では py で代用する（この場合は黒い画面が残ります）
where pyw >nul 2>&1
if errorlevel 1 if "%PYW%"=="pyw -3" set "PYW=%PY%"

rem --- 画面表示の部品を確認 ---
%PY% -c "import tkinter" >nul 2>&1
if errorlevel 1 (
    echo.
    echo   Python に tkinter 〔画面表示の部品〕 が入っていないため起動できません。
    echo.
    echo   python.org から Python を入れ直し、インストール画面で
    echo   「tcl/tk and IDLE」にチェックを入れてください。
    echo.
    pause
    exit /b 1
)

rem --- 必要なライブラリを確認 ---
%PY% -c "import docx" >nul 2>&1
if errorlevel 1 (
    echo.
    echo   必要なライブラリがインストールされていません。
    echo.
    echo   先に「初回セットアップ.bat」をダブルクリックしてください。
    echo.
    pause
    exit /b 1
)

rem --- 起動 ---
if exist "logs\起動エラー.txt" del "logs\起動エラー.txt" >nul 2>&1
start "" %PYW% "%~dp0main.py"

rem 起動直後に失敗していないか確認する（約3秒待つ）
ping -n 4 127.0.0.1 >nul 2>&1
if exist "logs\起動エラー.txt" (
    echo.
    echo   起動に失敗しました。理由は次のとおりです。
    echo   ----------------------------------------------------------
    type "logs\起動エラー.txt"
    echo.
    echo   ----------------------------------------------------------
    echo.
    echo   解決しない場合は「診断.bat」をダブルクリックしてください。
    echo.
    pause
    exit /b 1
)
exit /b 0
