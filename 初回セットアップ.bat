@echo off
chcp 932 >nul
rem 必要なライブラリをインストールします（初回のみ実行してください）
cd /d "%~dp0"
echo ライブラリをインストールしています。しばらくお待ちください...
echo.
where python >nul 2>&1
if %errorlevel%==0 (
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
    goto done
)
where py >nul 2>&1
if %errorlevel%==0 (
    py -m pip install --upgrade pip
    py -m pip install -r requirements.txt
    goto done
)
echo Python が見つかりません。Python をインストールしてから、もう一度実行してください。
pause
exit /b 1

:done
echo.
if %errorlevel%==0 (
    echo セットアップが完了しました。「起動.bat」をダブルクリックして起動してください。
) else (
    echo インストールに失敗しました。インターネット接続を確認して、もう一度実行してください。
)
pause
