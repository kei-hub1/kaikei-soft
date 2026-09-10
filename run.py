"""起動スクリプト:  python run.py  → http://127.0.0.1:8765 をブラウザで開く。"""
from __future__ import annotations

import argparse
import socket
import threading
import webbrowser

import uvicorn


def is_running(host: str, port: int) -> bool:
    """すでに同じポートでサーバーが動いているかを調べる。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def main() -> None:
    p = argparse.ArgumentParser(description="財務エントリ (kaikei-soft) を起動します")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true", help="ブラウザを自動で開かない")
    p.add_argument("--reload", action="store_true", help="開発用: ソース変更時に自動再起動")
    args = p.parse_args()

    url = f"http://{args.host}:{args.port}/"

    # 二重起動の場合はエラーにせず、動いている方をブラウザで開く。
    if is_running(args.host, args.port):
        print(f"財務エントリ はすでに起動しています: {url}")
        if not args.no_browser:
            webbrowser.open(url)
        return

    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print(f"財務エントリ を起動しました: {url}  (終了は Ctrl+C)")
    try:
        uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload, log_level="warning")
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
