"""定型文書作成ツール 起動スクリプト。

「起動.bat」をダブルクリックするか、``python main.py`` で起動する。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import db, logger, paths  # noqa: E402
from app.repositories import Repositories  # noqa: E402


def _show_fatal(message: str) -> None:
    """起動できないときに、可能ならダイアログで知らせる。"""
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("起動できません", message)
        root.destroy()
    except Exception:  # noqa: BLE001
        print(message, file=sys.stderr)


def main() -> int:
    paths.ensure_dirs()
    log = logger.setup_logging()
    log.info("起動 (Python %s)", sys.version.split()[0])

    try:
        import docx  # noqa: F401
    except ImportError:
        msg = (
            "必要なライブラリ（python-docx）が見つかりません。\n"
            "「初回セットアップ.bat」をダブルクリックして、ライブラリをインストールしてください。"
        )
        log.error(msg)
        _show_fatal(msg)
        return 1

    try:
        repos = Repositories(db.connect())
    except Exception as e:  # noqa: BLE001
        log.exception("データベースを開けません")
        _show_fatal(f"データベースを開けませんでした。\n{paths.DB_PATH}\n{e}")
        return 1

    try:
        from app.ui.app import App

        App(repos).mainloop()
    except Exception as e:  # noqa: BLE001
        log.exception("予期しないエラーで終了")
        _show_fatal(f"予期しないエラーが発生しました。\n{e}\n\n詳細は logs/app.log を確認してください。")
        return 1
    log.info("終了")
    return 0


if __name__ == "__main__":
    sys.exit(main())
