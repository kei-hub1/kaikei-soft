@echo off
chcp 932 >nul
setlocal
cd /d "%~dp0"
title 定型文書作成ツール　診断

rem --- zip の中から実行されていないか確認 ---
if not exist "%~dp0main.py" goto :nofiles

echo.
echo   定型文書作成ツールの診断を行います。
echo.
echo   --- パソコンに入っている Python ---
where py 2>nul
where python 2>nul
where pythonw 2>nul
echo.

set "PY="
set "PYW="

rem --- Python を探す〔py ランチャー → python の順〕---
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
goto :nopython

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

:nopython
echo.
echo   Python が見つかりません。
echo.
echo   python.org から Python をインストールしてください。
echo   インストール画面で「Add python.exe to PATH」に必ずチェックを入れてください。
echo.
echo   https://www.python.org/downloads/windows/
echo.
echo   ※ Microsoft Store 版の Python では動かないことがあります。
echo.
pause
exit /b 1

:nofiles
echo.
echo   ============================================================
echo    zip を解凍せずに実行しているため、起動できません。
echo   ============================================================
echo.
echo   今このファイルがある場所：
echo   %~dp0
echo.
echo   zip を開いたまま中の bat をダブルクリックすると、
echo   この bat だけが一時フォルダにコピーされて実行されます。
echo   アプリ本体〔main.py など〕が無いため動きません。
echo.
echo   【対処】
echo    1. ダウンロードした「定型文書作成ツール.zip」を右クリック
echo    2. 「すべて展開」を選ぶ
echo    3. 展開先〔例 C:\定型文書作成ツール〕のフォルダを開く
echo    4. その中の「初回セットアップ.bat」→「起動.bat」の順に実行する
echo.
pause
exit /b 1
