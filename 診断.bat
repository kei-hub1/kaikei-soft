@echo off
chcp 932 >nul
setlocal
cd /d "%~dp0"
title 定型文書作成ツール　診断

rem ============================================================
rem  起動できないときの原因を調べます
rem ============================================================

echo.
echo   定型文書作成ツールの診断を行います。
echo.
echo   --- パソコンに入っている Python ---
where py 2>nul
where python 2>nul
where pythonw 2>nul
echo.

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

echo   [NG] Python が見つかりません。
echo.
echo   python.org から Python をインストールしてください。
echo   インストール画面で「Add python.exe to PATH」に必ずチェックを入れてください。
echo.
echo   https://www.python.org/downloads/windows/
echo.
pause
exit /b 1

:found
%PY% "%~dp0診断.py"
echo.
echo   ============================================================
echo   続けてアプリを起動します。
echo   エラーが出た場合は、この画面の内容を控えてください。
echo   ============================================================
echo.
%PY% "%~dp0main.py"
echo.
echo   アプリが終了しました。
echo   この画面の内容と logs フォルダの「診断結果.txt」をお知らせください。
echo.
pause
exit /b 0
