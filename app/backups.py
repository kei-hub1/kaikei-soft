"""データベースのバックアップと、バックアップからの復元。

バックアップは data/backup/kaikei_YYYYMMDD_HHMMSS[_種類].db に置く。
  _before_delete  : 仕訳をまとめて削除する前 (自動)
  _before_restore : バックアップから戻す前 (自動)
  _update         : update.bat でソフトを更新する前 (自動)
  (種類なし)       : 「バックアップをダウンロード」で作ったもの
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime
from pathlib import Path

from .db import connect, get_db_path, init_db

NAME_RE = re.compile(r"^kaikei_(\d{8})_(\d{6})(?:_([0-9A-Za-z_]+))?\.db$")
KINDS = {
    "before_delete": "仕訳をまとめて削除する前",
    "before_restore": "バックアップから戻す前",
    "update": "ソフトを更新する前",
    "": "手動 (ダウンロード)",
}


def backup_dir() -> Path:
    return get_db_path().parent / "backup"


def make_backup(tag: str = "") -> Path:
    """いまのデータベースを data/backup に複写し、その場所を返す。

    SQLite のバックアップ機能で複写するので、書き込み途中の状態は写らない。
    """
    d = backup_dir()
    d.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = f"kaikei_{stamp}" + (f"_{tag}" if tag else "")
    dst = d / f"{base}.db"
    n = 2
    while dst.exists():                     # 同じ秒に 2 回作ったとき
        dst = d / f"{base}_{n}.db"
        n += 1
    src = connect()
    out = sqlite3.connect(str(dst))
    try:
        src.backup(out)
    finally:
        out.close()
        src.close()
    return dst


def _kind(tag: str) -> str:
    tag = re.sub(r"_\d+$", "", tag or "")  # 同じ秒の 2 つ目に付く _2 などは除く
    return tag if tag in KINDS else ""


def _open_ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


def list_backups() -> list[dict]:
    """バックアップの一覧 (新しい順)。各ファイルの仕訳の件数も添える。"""
    d = backup_dir()
    if not d.exists():
        return []
    out = []
    for p in d.iterdir():
        m = NAME_RE.match(p.name)
        if not m or not p.is_file():
            continue
        day, tm, tag = m.groups()
        created = datetime.strptime(day + tm, "%Y%m%d%H%M%S")
        kind = _kind(tag or "")
        item = {"name": p.name, "created": created.isoformat(), "kind": kind, "kind_label": KINDS[kind],
                "size": p.stat().st_size, "entries": None, "clients": None, "error": ""}
        try:
            conn = _open_ro(p)
            try:
                item["entries"] = conn.execute("SELECT COUNT(*) FROM journal_entries").fetchone()[0]
                item["clients"] = conn.execute("SELECT COUNT(*) FROM clients").fetchone()[0]
            finally:
                conn.close()
        except sqlite3.Error as e:
            item["error"] = f"読み込めません ({e})"
        out.append(item)
    out.sort(key=lambda x: x["name"], reverse=True)
    return out


def restore_backup(name: str) -> dict:
    """バックアップの内容でデータベースを置き換える。戻す前の状態も自動でバックアップする。"""
    if not NAME_RE.match(name or ""):
        raise ValueError("バックアップのファイル名が不正です")
    src_path = backup_dir() / name
    if not src_path.is_file():
        raise FileNotFoundError(f"バックアップ {name} が見つかりません")
    src = _open_ro(src_path)
    try:
        ok = src.execute("PRAGMA quick_check").fetchone()[0]
        if ok != "ok":
            raise ValueError(f"バックアップ {name} が壊れているため戻せません ({ok})")
        if not src.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='journal_entries'").fetchone():
            raise ValueError(f"{name} は財務エントリのバックアップではありません")
        before = make_backup("before_restore")
        dst = connect()
        try:
            src.backup(dst)               # ファイルを差し替えずに中身を丸ごと写す (Windows でも安全)
        finally:
            dst.close()
    finally:
        src.close()
    init_db()                             # 古い版のバックアップなら、今の版の形に直す
    return {"restored": name, "backup": before.name}
