"""定型文書作成ツール 起動スクリプト。

「起動.bat」をダブルクリックするか、``python main.py`` で起動する。

pythonw で起動すると画面にエラーが出ないため、起動できなかったときは
必ず logs/起動エラー.txt に理由を書き出す。
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))

ERROR_FILE = APP_DIR / "logs" / "起動エラー.txt"


def _write_error_file(message: str) -> None:
    """起動できなかった理由をファイルに残す（画面に出せない場合の保険）。

    「起動.bat」がこのファイルを type で表示するため、Windows では
    コマンドプロンプトの文字コード（cp932）で書き出す。
    """
    encoding = "cp932" if sys.platform == "win32" else "utf-8"
    try:
        ERROR_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(ERROR_FILE, "w", encoding=encoding, errors="replace") as f:
            f.write(message)
    except Exception:  # noqa: BLE001 - ここで失敗しても何もできない
        pass


def _show_fatal(message: str, detail: str = "") -> None:
    """起動できないときに、ダイアログ・ファイル・標準エラーの順で知らせる。"""
    _write_error_file(message + ("\n\n" + detail if detail else ""))
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("起動できません", message)
        root.destroy()
    except Exception:  # noqa: BLE001 - tkinter が無い場合など
        pass
    print(message, file=sys.stderr)
    if detail:
        print(detail, file=sys.stderr)


def main() -> int:
    try:
        from app import paths

        paths.ensure_dirs()
    except Exception as e:  # noqa: BLE001
        _show_fatal(
            f"アプリのフォルダを準備できませんでした。\n{APP_DIR}\n{e}",
            traceback.format_exc(),
        )
        return 1

    from app import logger

    log = logger.setup_logging()
    log.info("起動 (Python %s / %s)", sys.version.split()[0], sys.executable)

    # 画面表示に必要な tkinter
    try:
        import tkinter  # noqa: F401
    except ImportError:
        msg = (
            "Python に tkinter（画面表示の部品）が入っていないため起動できません。\n\n"
            "python.org から Python を再インストールし、インストール画面で\n"
            "「tcl/tk and IDLE」にチェックを入れてください。"
        )
        log.error(msg)
        _show_fatal(msg, traceback.format_exc())
        return 1

    # Word 出力に必要な python-docx
    try:
        import docx  # noqa: F401
    except ImportError:
        msg = (
            "必要なライブラリ（python-docx）が見つかりません。\n\n"
            "「初回セットアップ.bat」をダブルクリックして、ライブラリをインストールしてください。"
        )
        log.error(msg)
        _show_fatal(msg, traceback.format_exc())
        return 1

    from app import db, paths
    from app.repositories import Repositories

    try:
        repos = Repositories(db.connect())
    except Exception as e:  # noqa: BLE001
        log.exception("データベースを開けません")
        _show_fatal(
            f"データベースを開けませんでした。\n{paths.DB_PATH}\n{e}", traceback.format_exc()
        )
        return 1

    try:
        from app.ui.app import App

        App(repos).mainloop()
    except Exception as e:  # noqa: BLE001
        log.exception("予期しないエラーで終了")
        _show_fatal(
            f"予期しないエラーが発生しました。\n{e}\n\n詳細は logs フォルダを確認してください。",
            traceback.format_exc(),
        )
        return 1

    # 正常に起動できたので、前回のエラーファイルは消しておく
    try:
        ERROR_FILE.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass
    log.info("終了")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as e:  # noqa: BLE001 - 最後の保険
        _show_fatal(f"起動処理で予期しないエラーが発生しました。\n{e}", traceback.format_exc())
        sys.exit(1)
