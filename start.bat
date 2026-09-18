@echo off
rem 論点ノート 起動スクリプト (Windows)
rem Python 3.8 以上がインストールされている必要があります。
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -m ronten %*
) else (
  python -m ronten %*
)
if errorlevel 1 pause
