"""起動スクリプト:  python run.py  → http://127.0.0.1:8765 をブラウザで開く。"""
from __future__ import annotations

import argparse
import threading
import webbrowser

import uvicorn


def main() -> None:
    p = argparse.ArgumentParser(description="財務エントリ (kaikei-soft) を起動します")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true", help="ブラウザを自動で開かない")
    p.add_argument("--reload", action="store_true", help="開発用: ソース変更時に自動再起動")
    args = p.parse_args()

    url = f"http://{args.host}:{args.port}/"
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print(f"財務エントリ を起動しました: {url}  (終了は Ctrl+C)")
    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload, log_level="warning")


if __name__ == "__main__":
    main()
