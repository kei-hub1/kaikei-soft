@echo off
chcp 932 >nul
setlocal
cd /d "%~dp0"
title 定型文書作成ツール　初回セットアップ

rem --- zip の中から実行されていないか確認 ---
if not exist "%~dp0main.py" goto :nofiles

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

echo.
echo   使用する Python：
%PY% -c "import sys; print('   ' + sys.executable); print('   バージョン ' + sys.version.split()[0])"
echo.
echo   ライブラリをインストールしています。しばらくお待ちください...
echo.

%PY% -m pip install --upgrade pip
%PY% -m pip install -r requirements.txt
if errorlevel 1 goto :piperror

echo.
echo   インストール結果を確認しています...
%PY% -c "import docx, tkinter" >nul 2>&1
if errorlevel 1 goto :checkerror

echo.
echo   セットアップが完了しました。
echo   「起動.bat」をダブルクリックして起動してください。
echo.
pause
exit /b 0

:piperror
echo.
echo   インストールに失敗しました。
echo   インターネットに接続されているか確認して、もう一度実行してください。
echo.
pause
exit /b 1

:checkerror
echo.
echo   確認できませんでした。「診断.bat」をダブルクリックして原因をお知らせください。
echo.
pause
exit /b 1

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
