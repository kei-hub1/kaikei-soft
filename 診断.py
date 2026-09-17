"""起動できないときの原因を調べて表示・記録する。

「診断.bat」から呼ばれる。結果は logs/診断結果.txt にも保存する。
"""

from __future__ import annotations

import platform
import sys
import traceback
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))

_lines: list[str] = []


def say(text: str = "") -> None:
    print(text)
    _lines.append(text)


def check(title: str, func) -> bool:
    """func() を実行し、成否を「OK/NG」で表示する。"""
    try:
        detail = func()
    except Exception as e:  # noqa: BLE001
        say(f"  [NG] {title}：{type(e).__name__}: {e}")
        return False
    say(f"  [OK] {title}" + (f"：{detail}" if detail else ""))
    return True


def main() -> int:
    say("=" * 60)
    say("  定型文書作成ツール　診断結果")
    say("=" * 60)
    say()

    say("■ 動作環境")
    say(f"  OS          : {platform.platform()}")
    say(f"  Python      : {sys.version.split()[0]}")
    say(f"  実行ファイル: {sys.executable}")
    say(f"  アプリの場所: {APP_DIR}")
    say()

    def _tk_version():
        import tkinter

        return f"Tk {tkinter.TkVersion}"

    def _docx_version():
        import docx

        return getattr(docx, "__version__", "")

    def _sqlite_version():
        import sqlite3

        return sqlite3.sqlite_version

    def _pywin32():
        import win32com.client  # noqa: F401

        return ""

    say("■ 必要な部品")
    ok_tk = check("tkinter（画面表示）", _tk_version)
    ok_docx = check("python-docx（Word 出力）", _docx_version)
    check("sqlite3（データ保存）", _sqlite_version)
    if sys.platform == "win32":
        ok_win32 = check("pywin32（PDF 変換）", _pywin32)
    else:
        ok_win32 = True
        say("  [--] pywin32 は Windows 以外では使いません")
    say()

    say("■ アプリのファイル")
    for rel in ("main.py", "app/__init__.py", "app/ui/app.py", "requirements.txt"):
        p = APP_DIR / rel
        say(f"  [{'OK' if p.exists() else 'NG'}] {rel}")
    say()

    say("■ フォルダへの書き込み")
    for name in ("data", "logs", "出力"):
        d = APP_DIR / name
        try:
            d.mkdir(parents=True, exist_ok=True)
            probe = d / "_書き込みテスト.tmp"
            probe.write_text("test", encoding="utf-8")
            probe.unlink()
            say(f"  [OK] {name}")
        except Exception as e:  # noqa: BLE001
            say(f"  [NG] {name}：{type(e).__name__}: {e}")
    say()

    say("■ アプリの読み込み")
    ok_import = True
    for module in ("app.db", "app.repositories", "app.docx_builder", "app.service"):
        try:
            __import__(module)
            say(f"  [OK] {module}")
        except Exception as e:  # noqa: BLE001
            ok_import = False
            say(f"  [NG] {module}：{type(e).__name__}: {e}")
            for line in traceback.format_exc().splitlines()[-4:]:
                say(f"        {line}")
    say()

    ok_window = False
    if ok_tk:
        say("■ 画面の表示テスト")
        try:
            import tkinter as tk

            root = tk.Tk()
            root.withdraw()
            root.update()
            root.destroy()
            say("  [OK] ウィンドウを作成できました")
            ok_window = True
        except Exception as e:  # noqa: BLE001
            say(f"  [NG] ウィンドウを作成できません：{type(e).__name__}: {e}")
        say()

    err_file = APP_DIR / "logs" / "起動エラー.txt"
    if err_file.exists():
        say("■ 前回の起動エラー（logs/起動エラー.txt）")
        try:
            for line in err_file.read_text(encoding="utf-8").splitlines()[:30]:
                say(f"  {line}")
        except Exception as e:  # noqa: BLE001
            say(f"  読み取れません：{e}")
        say()

    say("=" * 60)
    if not ok_tk:
        say("【原因】Python に tkinter が入っていません。")
        say("　python.org から Python を再インストールし、インストール画面で")
        say("　「tcl/tk and IDLE」にチェックを入れてください。")
    elif not ok_docx:
        say("【原因】python-docx が入っていません。")
        say("　「初回セットアップ.bat」をダブルクリックしてください。")
    elif not ok_import:
        say("【原因】アプリのファイルを読み込めません（上の NG を確認してください）。")
    elif not ok_window:
        say("【原因】ウィンドウを作成できません。パソコンを再起動して試してください。")
    else:
        say("【結果】起動に必要なものはすべて揃っています。")
        if not ok_win32:
            say("　ただし pywin32 が無いため、PDF 変換に失敗する可能性があります。")
            say("　「初回セットアップ.bat」をもう一度実行してください。")
        say("　このあとアプリを起動します。エラーが出る場合は画面の内容を控えてください。")
    say("=" * 60)

    try:
        out = APP_DIR / "logs" / "診断結果.txt"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(_lines) + "\n", encoding="utf-8")
        print(f"\nこの内容は {out} にも保存しました。")
    except Exception as e:  # noqa: BLE001
        print(f"\n診断結果を保存できませんでした：{e}")

    return 0 if (ok_tk and ok_docx and ok_import) else 1


if __name__ == "__main__":
    sys.exit(main())
