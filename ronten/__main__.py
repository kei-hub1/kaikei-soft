"""起動: python -m ronten [--db data/ronten.db] [--port 8765] [--host 127.0.0.1] [--no-browser]"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import webbrowser

from . import __version__
from .db import Database
from .server import make_server


def default_db_path() -> str:
    env = os.environ.get("RONTEN_DB")
    if env:
        return env
    # パッケージの親ディレクトリ（リポジトリ直下）に data/ronten.db を作る
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "data", "ronten.db")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ronten", description="論点ノート — 顧問先ごとの税務検討論点を蓄積・検索するローカルアプリ")
    p.add_argument("--db", default=default_db_path(), help="SQLite ファイルのパス (既定: data/ronten.db または環境変数 RONTEN_DB)")
    p.add_argument("--host", default="127.0.0.1", help="待受アドレス (既定: 127.0.0.1 = このPCのみ)")
    p.add_argument("--port", type=int, default=8765, help="ポート番号 (既定: 8765)")
    p.add_argument("--no-browser", action="store_true", help="起動時にブラウザを開かない")
    p.add_argument("--version", action="version", version=f"ronten {__version__}")
    args = p.parse_args(argv)

    db = Database(args.db)
    try:
        server = make_server(args.host, args.port, db)
    except OSError as e:
        print(f"サーバーを起動できません ({args.host}:{args.port}): {e}", file=sys.stderr)
        print("既に起動中か、ポートが使用中の可能性があります。--port で別の番号を指定してください。", file=sys.stderr)
        return 1

    url = f"http://{args.host}:{server.server_address[1]}/"
    print(f"論点ノート v{__version__}")
    print(f"  データ : {os.path.abspath(args.db)}")
    print(f"  全文検索: {'有効 (FTS5)' if db.fts_enabled else '簡易 (LIKE)'}")
    print(f"  URL    : {url}")
    print("終了するには Ctrl+C を押してください。")

    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n停止します。")
    finally:
        server.server_close()
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
