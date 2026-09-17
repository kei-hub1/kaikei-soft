"""SQLite データベースの接続・スキーマ作成・初期データ投入。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from . import paths
from .models import DEFAULT_CLOSING, DEFAULT_OPENING

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    company     TEXT NOT NULL DEFAULT '',
    department  TEXT NOT NULL DEFAULT '',
    name        TEXT NOT NULL DEFAULT '',
    honorific   TEXT NOT NULL DEFAULT '様',
    postal      TEXT NOT NULL DEFAULT '',
    address1    TEXT NOT NULL DEFAULT '',
    address2    TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS sender (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    office      TEXT NOT NULL DEFAULT '',
    accountant  TEXT NOT NULL DEFAULT '',
    postal      TEXT NOT NULL DEFAULT '',
    address     TEXT NOT NULL DEFAULT '',
    tel         TEXT NOT NULL DEFAULT '',
    fax         TEXT NOT NULL DEFAULT '',
    email       TEXT NOT NULL DEFAULT '',
    staff       TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS doc_types (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    sort_order  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS templates (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL,
    doc_type_id         INTEGER REFERENCES doc_types(id) ON DELETE RESTRICT,
    subject             TEXT NOT NULL DEFAULT '',
    body                TEXT NOT NULL DEFAULT '',
    has_notes           INTEGER NOT NULL DEFAULT 0,
    opening             TEXT NOT NULL DEFAULT '拝啓',
    closing             TEXT NOT NULL DEFAULT '敬具',
    default_enclosures  TEXT NOT NULL DEFAULT '',
    sort_order          INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS settings (
    key     TEXT PRIMARY KEY,
    value   TEXT NOT NULL DEFAULT ''
);
"""

# ---- 初期データ -------------------------------------------------------------

DEFAULT_OFFICE_NAME = "吉川和章税理士事務所"

SEED_DOC_TYPES: tuple[str, ...] = ("送付状", "案内文")

# (文例名, 種類, 件名, 本文, 記書き, 書類一覧の初期値)
SEED_TEMPLATES: tuple[tuple[str, str, str, str, bool, str], ...] = (
    (
        "資料送付のご案内",
        "送付状",
        "資料送付のご案内",
        "平素は格別のご高配を賜り、厚く御礼申し上げます。\n"
        "さて、下記の資料をお送りいたしますので、ご査収のほどよろしくお願い申し上げます。\n"
        "ご不明な点がございましたら、担当までお気軽にお問い合わせください。\n"
        "まずは略儀ながら書中をもってご案内申し上げます。",
        True,
        "",
    ),
    (
        "書類ご送付のお願い",
        "送付状",
        "書類ご送付のお願い",
        "平素は格別のご高配を賜り、厚く御礼申し上げます。\n"
        "さて、業務を進めるにあたり下記の書類が必要となりますので、"
        "ご多忙のところ誠に恐縮ではございますが、ご準備のうえご送付くださいますようお願い申し上げます。\n"
        "ご不明な点がございましたら、担当までお気軽にお問い合わせください。\n"
        "何卒よろしくお願い申し上げます。",
        True,
        "",
    ),
    (
        "お知らせ",
        "案内文",
        "お知らせ",
        "平素は格別のご高配を賜り、厚く御礼申し上げます。\n"
        "さて、このたび当事務所では、○○○○についてご案内申し上げます。\n"
        "ご不明な点がございましたら、担当までお気軽にお問い合わせください。\n"
        "まずは略儀ながら書中をもってお知らせ申し上げます。",
        False,
        "",
    ),
)


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    """DB に接続し、必要ならテーブル作成と初期データ投入を行う。"""
    db_path = db_path or paths.DB_PATH
    if str(db_path) != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    initialize(conn)
    return conn


def initialize(conn: sqlite3.Connection) -> None:
    """スキーマ作成と初期データ投入（何度呼んでも安全）。"""
    conn.executescript(_SCHEMA)
    _seed(conn)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()


def _seed(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()

    if cur.execute("SELECT COUNT(*) FROM sender").fetchone()[0] == 0:
        cur.execute("INSERT INTO sender (id, office) VALUES (1, ?)", (DEFAULT_OFFICE_NAME,))

    if cur.execute("SELECT COUNT(*) FROM doc_types").fetchone()[0] == 0:
        for i, name in enumerate(SEED_DOC_TYPES, start=1):
            cur.execute("INSERT INTO doc_types (name, sort_order) VALUES (?, ?)", (name, i))

    if cur.execute("SELECT COUNT(*) FROM templates").fetchone()[0] == 0:
        for i, (name, type_name, subject, body, has_notes, encl) in enumerate(
            SEED_TEMPLATES, start=1
        ):
            row = cur.execute("SELECT id FROM doc_types WHERE name = ?", (type_name,)).fetchone()
            cur.execute(
                """INSERT INTO templates
                   (name, doc_type_id, subject, body, has_notes, opening, closing,
                    default_enclosures, sort_order)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    name,
                    row["id"] if row else None,
                    subject,
                    body,
                    1 if has_notes else 0,
                    DEFAULT_OPENING,
                    DEFAULT_CLOSING,
                    encl,
                    i,
                ),
            )

    cur.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('output_dir', ?)",
        (str(paths.DEFAULT_OUTPUT_DIR),),
    )
