"""SQLite 接続とスキーマ定義。

単一ユーザー・ローカル利用を前提とし、DB は 1 ファイル (data/kaikei.db)。
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = BASE_DIR / "data" / "kaikei.db"

_db_path: Path = Path(os.environ.get("KAIKEI_DB", str(DEFAULT_DB_PATH)))


def set_db_path(path: str | os.PathLike) -> None:
    global _db_path
    _db_path = Path(path)


def get_db_path() -> Path:
    return _db_path


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS clients (
  id INTEGER PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  kana TEXT NOT NULL DEFAULT '',
  entity_type TEXT NOT NULL DEFAULT 'corp',      -- corp: 法人 / sole: 個人
  tax_method TEXT NOT NULL DEFAULT 'inclusive',   -- inclusive: 税込経理 / exclusive: 税抜経理 / exempt: 免税
  fiscal_start_month INTEGER NOT NULL DEFAULT 4,
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fiscal_years (
  id INTEGER PRIMARY KEY,
  client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  start_date TEXT NOT NULL,
  end_date TEXT NOT NULL,
  label TEXT NOT NULL DEFAULT '',
  closed INTEGER NOT NULL DEFAULT 0,
  UNIQUE(client_id, start_date)
);

CREATE TABLE IF NOT EXISTS accounts (
  id INTEGER PRIMARY KEY,
  client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  code TEXT NOT NULL,
  name TEXT NOT NULL,
  kana TEXT NOT NULL DEFAULT '',
  category TEXT NOT NULL,          -- asset / liability / equity / revenue / expense
  grp TEXT NOT NULL,               -- 流動資産, 固定資産, ... (表示区分)
  default_tax_class TEXT NOT NULL DEFAULT '00',
  role TEXT NOT NULL DEFAULT '',   -- tax_receivable / tax_payable / retained / owner_capital / owner_drawing / owner_contrib / suspense
  sort_order INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1,
  UNIQUE(client_id, code)
);

CREATE TABLE IF NOT EXISTS sub_accounts (
  id INTEGER PRIMARY KEY,
  account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  code TEXT NOT NULL,
  name TEXT NOT NULL,
  kana TEXT NOT NULL DEFAULT '',
  active INTEGER NOT NULL DEFAULT 1,
  UNIQUE(account_id, code)
);

CREATE TABLE IF NOT EXISTS departments (
  id INTEGER PRIMARY KEY,
  client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  code TEXT NOT NULL,
  name TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  UNIQUE(client_id, code)
);

CREATE TABLE IF NOT EXISTS opening_balances (
  id INTEGER PRIMARY KEY,
  fiscal_year_id INTEGER NOT NULL REFERENCES fiscal_years(id) ON DELETE CASCADE,
  account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  sub_account_id INTEGER NOT NULL DEFAULT 0,   -- 0 = 補助なし
  amount INTEGER NOT NULL DEFAULT 0,           -- 借方残高を正、貸方残高を負で保持
  UNIQUE(fiscal_year_id, account_id, sub_account_id)
);

CREATE TABLE IF NOT EXISTS journal_entries (
  id INTEGER PRIMARY KEY,
  client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  fiscal_year_id INTEGER NOT NULL REFERENCES fiscal_years(id) ON DELETE CASCADE,
  entry_date TEXT NOT NULL,
  voucher_no INTEGER NOT NULL,
  memo TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_entries_fy_date ON journal_entries(fiscal_year_id, entry_date, voucher_no);

CREATE TABLE IF NOT EXISTS journal_lines (
  id INTEGER PRIMARY KEY,
  entry_id INTEGER NOT NULL REFERENCES journal_entries(id) ON DELETE CASCADE,
  line_no INTEGER NOT NULL,
  debit_account_id INTEGER REFERENCES accounts(id),
  debit_sub_id INTEGER REFERENCES sub_accounts(id),
  debit_dept_id INTEGER REFERENCES departments(id),
  credit_account_id INTEGER REFERENCES accounts(id),
  credit_sub_id INTEGER REFERENCES sub_accounts(id),
  credit_dept_id INTEGER REFERENCES departments(id),
  amount INTEGER NOT NULL,
  tax_class TEXT NOT NULL DEFAULT '00',
  tax_rate INTEGER NOT NULL DEFAULT 0,
  tax_amount INTEGER NOT NULL DEFAULT 0,
  description TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_lines_entry ON journal_lines(entry_id);
CREATE INDEX IF NOT EXISTS idx_lines_debit ON journal_lines(debit_account_id);
CREATE INDEX IF NOT EXISTS idx_lines_credit ON journal_lines(credit_account_id);

CREATE TABLE IF NOT EXISTS entry_templates (
  id INTEGER PRIMARY KEY,
  client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  code TEXT NOT NULL,
  name TEXT NOT NULL,
  debit_account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
  debit_sub_id INTEGER REFERENCES sub_accounts(id) ON DELETE SET NULL,
  credit_account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
  credit_sub_id INTEGER REFERENCES sub_accounts(id) ON DELETE SET NULL,
  amount INTEGER NOT NULL DEFAULT 0,
  tax_class TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  UNIQUE(client_id, code)
);
"""


def connect() -> sqlite3.Connection:
    _db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # 起動後に DB ファイルが差し替えられた場合 (バックアップからの復元など) でも
    # 「no such table」で落ちないよう、テーブルの有無を毎回確認する。
    # sqlite_master の 1 行検索なので負荷は無視できる。
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='clients'").fetchone() is None:
        conn.executescript(SCHEMA)
        conn.commit()
    return conn


def init_db() -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def rows_to_dicts(rows) -> list[dict]:
    return [dict(r) for r in rows]
