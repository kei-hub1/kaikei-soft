#!/usr/bin/env bash
# RangeCapture.exe をビルドする（MinGW-w64）
#   Linux (Ubuntu など) : sudo apt install g++-mingw-w64-x86-64 してから ./build.sh
#   Windows (MSYS2)     : pacman -S mingw-w64-x86_64-gcc してから MINGW64 シェルで ./build.sh
set -euo pipefail
cd "$(dirname "$0")"

if command -v x86_64-w64-mingw32-g++ >/dev/null 2>&1; then
  CXX=x86_64-w64-mingw32-g++
  WINDRES=x86_64-w64-mingw32-windres
else
  CXX=g++        # MSYS2 MINGW64 シェル
  WINDRES=windres
fi

mkdir -p build bin
"$WINDRES" -O coff -i src/app.rc -o build/app.res.o --include-dir=src
"$CXX" -std=c++17 -O2 -Wall -Wextra -municode -mwindows -static -s \
  -o bin/RangeCapture.exe src/main.cpp build/app.res.o \
  -lgdi32 -luser32 -lole32 -loleaut32 -luuid -lwindowscodecs -lshell32 -ldwmapi
echo "built: $(pwd)/bin/RangeCapture.exe"
