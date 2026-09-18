#!/bin/sh
# 論点ノート 起動スクリプト (macOS / Linux)
cd "$(dirname "$0")" || exit 1
exec python3 -m ronten "$@"
