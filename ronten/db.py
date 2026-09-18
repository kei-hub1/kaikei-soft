"""SQLite データ層。

- clients        : 顧問先
- issues         : 検討論点（事実関係・論点・検討・結論・根拠・翌年以降の留意点）
- tags/issue_tags: タグ
- issue_revisions: 論点の更新履歴（更新前のスナップショット）
- issues_fts     : 全文検索インデックス（FTS5 trigram。使えない環境では LIKE 検索に自動フォールバック）
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
import sqlite3
import threading
from typing import Any, Iterable

TAX_TYPES = [
    "法人税",
    "消費税",
    "所得税",
    "源泉所得税",
    "相続税",
    "贈与税",
    "地方税",
    "印紙税",
    "国際税務",
    "組織再編",
    "会計処理",
    "その他",
]
STATUSES = ["検討中", "結論済", "要再検討", "保留"]
ENTITY_TYPES = ["法人", "個人", "その他"]

ISSUE_TEXT_FIELDS = ["facts", "question", "analysis", "conclusion", "basis", "followup"]
ISSUE_FIELDS = [
    "client_id",
    "title",
    "tax_type",
    "fiscal_year",
    "status",
    "staff",
    "reviewer",
    "decided_on",
] + ISSUE_TEXT_FIELDS
CLIENT_FIELDS = ["code", "name", "kana", "entity_type", "fiscal_month", "industry", "staff", "note"]

FTS_COLUMNS = ["client_name", "title", "tags", "tax_type", "fiscal_year"] + ISSUE_TEXT_FIELDS

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    id           INTEGER PRIMARY KEY,
    code         TEXT NOT NULL DEFAULT '',
    name         TEXT NOT NULL,
    kana         TEXT NOT NULL DEFAULT '',
    entity_type  TEXT NOT NULL DEFAULT '法人',
    fiscal_month INTEGER,
    industry     TEXT NOT NULL DEFAULT '',
    staff        TEXT NOT NULL DEFAULT '',
    note         TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS issues (
    id          INTEGER PRIMARY KEY,
    client_id   INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    tax_type    TEXT NOT NULL DEFAULT 'その他',
    fiscal_year TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT '検討中',
    staff       TEXT NOT NULL DEFAULT '',
    reviewer    TEXT NOT NULL DEFAULT '',
    decided_on  TEXT NOT NULL DEFAULT '',
    facts       TEXT NOT NULL DEFAULT '',
    question    TEXT NOT NULL DEFAULT '',
    analysis    TEXT NOT NULL DEFAULT '',
    conclusion  TEXT NOT NULL DEFAULT '',
    basis       TEXT NOT NULL DEFAULT '',
    followup    TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_issues_client ON issues(client_id);
CREATE INDEX IF NOT EXISTS idx_issues_updated ON issues(updated_at);

CREATE TABLE IF NOT EXISTS tags (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS issue_tags (
    issue_id INTEGER NOT NULL REFERENCES issues(id) ON DELETE CASCADE,
    tag_id   INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (issue_id, tag_id)
);

CREATE TABLE IF NOT EXISTS issue_revisions (
    id       INTEGER PRIMARY KEY,
    issue_id INTEGER NOT NULL REFERENCES issues(id) ON DELETE CASCADE,
    saved_at TEXT NOT NULL,
    data     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_revisions_issue ON issue_revisions(issue_id);
"""

_WS_RE = re.compile(r"[\s　]+")
_CHUNK_RE = re.compile(r"[\s　、。・,.()（）「」『』【】\[\]〈〉《》:：;；/／\-－ー～〜]+")


def now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


class NotFound(Exception):
    pass


class ValidationError(Exception):
    pass


def _s(v: Any) -> str:
    """None → ''、それ以外は strip した文字列に正規化する。"""
    if v is None:
        return ""
    return str(v).strip()


def normalize_tags(tags: Any) -> list[str]:
    if tags is None:
        return []
    if isinstance(tags, str):
        parts = re.split(r"[,、，\s　]+", tags)
    else:
        parts = [str(t) for t in tags]
    out: list[str] = []
    for p in parts:
        p = p.strip().lstrip("#")
        if p and p not in out:
            out.append(p)
    return out


class Database:
    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            d = os.path.dirname(os.path.abspath(path))
            os.makedirs(d, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        if path != ":memory:":
            self.conn.execute("PRAGMA journal_mode = WAL")
        self.lock = threading.RLock()
        self.fts_enabled = False
        self._init_schema()

    # ------------------------------------------------------------------ schema
    def _init_schema(self) -> None:
        with self.lock, self.conn:
            self.conn.executescript(SCHEMA)
            try:
                cols = ", ".join(FTS_COLUMNS)
                self.conn.execute(
                    f"CREATE VIRTUAL TABLE IF NOT EXISTS issues_fts USING fts5("
                    f"issue_id UNINDEXED, {cols}, tokenize='trigram')"
                )
                self.fts_enabled = True
            except sqlite3.OperationalError:
                # FTS5 / trigram が使えない SQLite。LIKE 検索で代替する。
                self.fts_enabled = False
            self.conn.execute("PRAGMA user_version = 1")
        if self.fts_enabled:
            self._rebuild_fts_if_empty()

    def _rebuild_fts_if_empty(self) -> None:
        with self.lock, self.conn:
            n_issues = self.conn.execute("SELECT COUNT(*) FROM issues").fetchone()[0]
            n_fts = self.conn.execute("SELECT COUNT(*) FROM issues_fts").fetchone()[0]
            if n_issues and not n_fts:
                for row in self.conn.execute("SELECT id FROM issues"):
                    self._reindex_issue(row["id"])

    def close(self) -> None:
        with self.lock:
            self.conn.close()

    # ---------------------------------------------------------------- helpers
    def _reindex_issue(self, issue_id: int) -> None:
        if not self.fts_enabled:
            return
        self.conn.execute("DELETE FROM issues_fts WHERE issue_id = ?", (issue_id,))
        row = self.conn.execute(
            "SELECT i.*, c.name AS client_name FROM issues i JOIN clients c ON c.id = i.client_id WHERE i.id = ?",
            (issue_id,),
        ).fetchone()
        if row is None:
            return
        tags = " ".join(self._tags_for(issue_id))
        values = [issue_id, row["client_name"], row["title"], tags, row["tax_type"], row["fiscal_year"]] + [
            row[f] for f in ISSUE_TEXT_FIELDS
        ]
        placeholders = ", ".join("?" for _ in values)
        self.conn.execute(
            f"INSERT INTO issues_fts (issue_id, {', '.join(FTS_COLUMNS)}) VALUES ({placeholders})",
            values,
        )

    def _reindex_client_issues(self, client_id: int) -> None:
        if not self.fts_enabled:
            return
        for row in self.conn.execute("SELECT id FROM issues WHERE client_id = ?", (client_id,)):
            self._reindex_issue(row["id"])

    def _tags_for(self, issue_id: int) -> list[str]:
        rows = self.conn.execute(
            "SELECT t.name FROM tags t JOIN issue_tags it ON it.tag_id = t.id "
            "WHERE it.issue_id = ? ORDER BY t.name",
            (issue_id,),
        ).fetchall()
        return [r["name"] for r in rows]

    def _set_tags(self, issue_id: int, tags: Iterable[str]) -> None:
        self.conn.execute("DELETE FROM issue_tags WHERE issue_id = ?", (issue_id,))
        for name in normalize_tags(list(tags)):
            self.conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,))
            tag_id = self.conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()["id"]
            self.conn.execute(
                "INSERT OR IGNORE INTO issue_tags (issue_id, tag_id) VALUES (?, ?)", (issue_id, tag_id)
            )
        self.conn.execute("DELETE FROM tags WHERE id NOT IN (SELECT DISTINCT tag_id FROM issue_tags)")

    # ---------------------------------------------------------------- clients
    def _validate_client(self, data: dict) -> dict:
        out: dict[str, Any] = {}
        name = _s(data.get("name"))
        if not name:
            raise ValidationError("顧問先名は必須です")
        out["name"] = name
        for f in ("code", "kana", "industry", "staff", "note"):
            out[f] = _s(data.get(f))
        et = _s(data.get("entity_type")) or "法人"
        out["entity_type"] = et
        fm = data.get("fiscal_month")
        if fm in (None, ""):
            out["fiscal_month"] = None
        else:
            try:
                fm = int(fm)
            except (TypeError, ValueError):
                raise ValidationError("決算月は 1〜12 の数値で入力してください")
            if not 1 <= fm <= 12:
                raise ValidationError("決算月は 1〜12 の数値で入力してください")
            out["fiscal_month"] = fm
        return out

    def create_client(self, data: dict) -> dict:
        d = self._validate_client(data)
        ts = now()
        with self.lock, self.conn:
            cur = self.conn.execute(
                "INSERT INTO clients (code, name, kana, entity_type, fiscal_month, industry, staff, note, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (d["code"], d["name"], d["kana"], d["entity_type"], d["fiscal_month"], d["industry"], d["staff"], d["note"], ts, ts),
            )
            return self.get_client(cur.lastrowid)

    def update_client(self, client_id: int, data: dict) -> dict:
        d = self._validate_client(data)
        with self.lock, self.conn:
            self.get_client(client_id)
            self.conn.execute(
                "UPDATE clients SET code=?, name=?, kana=?, entity_type=?, fiscal_month=?, industry=?, staff=?, note=?, updated_at=? WHERE id=?",
                (d["code"], d["name"], d["kana"], d["entity_type"], d["fiscal_month"], d["industry"], d["staff"], d["note"], now(), client_id),
            )
            self._reindex_client_issues(client_id)
            return self.get_client(client_id)

    def delete_client(self, client_id: int) -> None:
        with self.lock, self.conn:
            self.get_client(client_id)
            ids = [r["id"] for r in self.conn.execute("SELECT id FROM issues WHERE client_id = ?", (client_id,))]
            self.conn.execute("DELETE FROM clients WHERE id = ?", (client_id,))
            if self.fts_enabled:
                for i in ids:
                    self.conn.execute("DELETE FROM issues_fts WHERE issue_id = ?", (i,))
            self.conn.execute("DELETE FROM tags WHERE id NOT IN (SELECT DISTINCT tag_id FROM issue_tags)")

    def get_client(self, client_id: int) -> dict:
        with self.lock:
            row = self.conn.execute(
                "SELECT c.*, (SELECT COUNT(*) FROM issues i WHERE i.client_id = c.id) AS issue_count, "
                "(SELECT COUNT(*) FROM issues i WHERE i.client_id = c.id AND (i.status IN ('検討中','要再検討') OR i.followup <> '')) AS open_count "
                "FROM clients c WHERE c.id = ?",
                (client_id,),
            ).fetchone()
            if row is None:
                raise NotFound("顧問先が見つかりません")
            return dict(row)

    def list_clients(self, q: str = "") -> list[dict]:
        q = _s(q)
        sql = (
            "SELECT c.*, (SELECT COUNT(*) FROM issues i WHERE i.client_id = c.id) AS issue_count, "
            "(SELECT COUNT(*) FROM issues i WHERE i.client_id = c.id AND (i.status IN ('検討中','要再検討') OR i.followup <> '')) AS open_count, "
            "(SELECT MAX(i.updated_at) FROM issues i WHERE i.client_id = c.id) AS last_issue_at "
            "FROM clients c"
        )
        params: list[Any] = []
        if q:
            sql += " WHERE c.name LIKE ? OR c.kana LIKE ? OR c.code LIKE ? OR c.industry LIKE ? OR c.staff LIKE ?"
            like = f"%{q}%"
            params = [like] * 5
        sql += " ORDER BY c.kana, c.name"
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, params)]

    # ----------------------------------------------------------------- issues
    def _validate_issue(self, data: dict, *, partial_client: int | None = None) -> dict:
        out: dict[str, Any] = {}
        try:
            cid = int(data.get("client_id") if data.get("client_id") not in (None, "") else partial_client)
        except (TypeError, ValueError):
            raise ValidationError("顧問先を選択してください")
        if self.conn.execute("SELECT 1 FROM clients WHERE id = ?", (cid,)).fetchone() is None:
            raise ValidationError("顧問先が存在しません")
        out["client_id"] = cid
        title = _s(data.get("title"))
        if not title:
            raise ValidationError("論点名は必須です")
        out["title"] = title
        out["tax_type"] = _s(data.get("tax_type")) or "その他"
        status = _s(data.get("status")) or "検討中"
        if status not in STATUSES:
            raise ValidationError("ステータスの値が不正です")
        out["status"] = status
        for f in ("fiscal_year", "staff", "reviewer", "decided_on") + tuple(ISSUE_TEXT_FIELDS):
            out[f] = _s(data.get(f))
        return out

    def create_issue(self, data: dict) -> dict:
        with self.lock, self.conn:
            d = self._validate_issue(data)
            ts = now()
            cols = ISSUE_FIELDS + ["created_at", "updated_at"]
            values = [d[f] for f in ISSUE_FIELDS] + [ts, ts]
            cur = self.conn.execute(
                f"INSERT INTO issues ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})", values
            )
            issue_id = cur.lastrowid
            self._set_tags(issue_id, normalize_tags(data.get("tags")))
            self._reindex_issue(issue_id)
            return self.get_issue(issue_id)

    def update_issue(self, issue_id: int, data: dict) -> dict:
        with self.lock, self.conn:
            old = self.get_issue(issue_id)
            d = self._validate_issue(data, partial_client=old["client_id"])
            # 更新前の状態を履歴として残す
            snapshot = {k: old[k] for k in ISSUE_FIELDS + ["tags", "updated_at", "client_name"]}
            self.conn.execute(
                "INSERT INTO issue_revisions (issue_id, saved_at, data) VALUES (?, ?, ?)",
                (issue_id, now(), json.dumps(snapshot, ensure_ascii=False)),
            )
            sets = ", ".join(f"{f} = ?" for f in ISSUE_FIELDS)
            values = [d[f] for f in ISSUE_FIELDS] + [now(), issue_id]
            self.conn.execute(f"UPDATE issues SET {sets}, updated_at = ? WHERE id = ?", values)
            self._set_tags(issue_id, normalize_tags(data.get("tags")))
            self._reindex_issue(issue_id)
            return self.get_issue(issue_id)

    def delete_issue(self, issue_id: int) -> None:
        with self.lock, self.conn:
            self.get_issue(issue_id)
            self.conn.execute("DELETE FROM issues WHERE id = ?", (issue_id,))
            if self.fts_enabled:
                self.conn.execute("DELETE FROM issues_fts WHERE issue_id = ?", (issue_id,))
            self.conn.execute("DELETE FROM tags WHERE id NOT IN (SELECT DISTINCT tag_id FROM issue_tags)")

    def get_issue(self, issue_id: int) -> dict:
        with self.lock:
            row = self.conn.execute(
                "SELECT i.*, c.name AS client_name, c.code AS client_code FROM issues i "
                "JOIN clients c ON c.id = i.client_id WHERE i.id = ?",
                (issue_id,),
            ).fetchone()
            if row is None:
                raise NotFound("論点が見つかりません")
            d = dict(row)
            d["tags"] = self._tags_for(issue_id)
            return d

    @staticmethod
    def _split_terms(q: str) -> list[str]:
        return [t for t in _WS_RE.split(_s(q)) if t]

    @staticmethod
    def _fts_phrase(term: str) -> str:
        return '"' + term.replace('"', '""') + '"'

    def list_issues(
        self,
        q: str = "",
        client_id: int | None = None,
        tax_type: str = "",
        status: str = "",
        tag: str = "",
        fiscal_year: str = "",
        staff: str = "",
        open_only: bool = False,
        limit: int = 200,
        offset: int = 0,
    ) -> dict:
        """条件検索。戻り値は {items, total, fts}。"""
        terms = self._split_terms(q)
        fts_terms = [t for t in terms if len(t) >= 3] if self.fts_enabled else []
        like_terms = [t for t in terms if t not in fts_terms]

        where: list[str] = []
        params: list[Any] = []
        joins = " JOIN clients c ON c.id = i.client_id"
        select_extra = ""
        order = "i.updated_at DESC"

        if fts_terms:
            match = " AND ".join(self._fts_phrase(t) for t in fts_terms)
            joins += " JOIN issues_fts f ON f.issue_id = i.id"
            where.append("issues_fts MATCH ?")
            params.append(match)
            select_extra = ", snippet(issues_fts, -1, '[[', ']]', '…', 32) AS snippet, bm25(issues_fts) AS rank"
            order = "rank, i.updated_at DESC"

        for t in like_terms:
            like = f"%{t}%"
            cols = ["c.name", "i.title", "i.tax_type", "i.fiscal_year"] + [f"i.{f}" for f in ISSUE_TEXT_FIELDS]
            cond = " OR ".join(f"{col} LIKE ?" for col in cols)
            cond += " OR EXISTS (SELECT 1 FROM issue_tags it JOIN tags t ON t.id = it.tag_id WHERE it.issue_id = i.id AND t.name LIKE ?)"
            where.append(f"({cond})")
            params.extend([like] * (len(cols) + 1))

        if client_id:
            where.append("i.client_id = ?")
            params.append(int(client_id))
        if tax_type:
            where.append("i.tax_type = ?")
            params.append(tax_type)
        if status:
            where.append("i.status = ?")
            params.append(status)
        if fiscal_year:
            where.append("i.fiscal_year = ?")
            params.append(fiscal_year)
        if staff:
            where.append("(i.staff = ? OR i.reviewer = ?)")
            params.extend([staff, staff])
        if tag:
            where.append(
                "EXISTS (SELECT 1 FROM issue_tags it JOIN tags t ON t.id = it.tag_id WHERE it.issue_id = i.id AND t.name = ?)"
            )
            params.append(tag)
        if open_only:
            where.append("(i.status IN ('検討中','要再検討') OR i.followup <> '')")

        where_sql = (" WHERE " + " AND ".join(where)) if where else ""
        base = f"FROM issues i{joins}{where_sql}"
        with self.lock:
            total = self.conn.execute(f"SELECT COUNT(*) {base}", params).fetchone()[0]
            rows = self.conn.execute(
                "SELECT i.id, i.client_id, c.name AS client_name, c.code AS client_code, i.title, i.tax_type, "
                "i.fiscal_year, i.status, i.staff, i.reviewer, i.decided_on, i.question, i.conclusion, i.followup, "
                "i.created_at, i.updated_at, "
                "(SELECT group_concat(t.name, '\t') FROM issue_tags it JOIN tags t ON t.id = it.tag_id WHERE it.issue_id = i.id) AS tag_list"
                f"{select_extra} {base} ORDER BY {order} LIMIT ? OFFSET ?",
                params + [int(limit), int(offset)],
            ).fetchall()
        items = []
        for r in rows:
            d = dict(r)
            d["tags"] = sorted(d.pop("tag_list").split("\t")) if d.get("tag_list") else []
            d.setdefault("snippet", None)
            d.pop("rank", None)
            items.append(d)
        return {"items": items, "total": total, "fts": bool(fts_terms)}

    def similar_issues(self, issue_id: int, limit: int = 10) -> list[dict]:
        """タイトル・タグ・論点から抽出したキーワードで、他の論点（他の顧問先含む）を引き当てる。"""
        issue = self.get_issue(issue_id)
        chunks: list[str] = []
        for src in [issue["title"]] + issue["tags"] + [issue["question"][:200]]:
            for ch in _CHUNK_RE.split(src or ""):
                ch = ch.strip()
                if len(ch) >= 3 and ch not in chunks:
                    chunks.append(ch)
        chunks = chunks[:20]
        with self.lock:
            rows: list[sqlite3.Row] = []
            if self.fts_enabled and chunks:
                match = " OR ".join(self._fts_phrase(c) for c in chunks)
                rows = self.conn.execute(
                    "SELECT i.id, i.client_id, c.name AS client_name, i.title, i.tax_type, i.fiscal_year, i.status, "
                    "i.conclusion, i.updated_at, bm25(issues_fts) AS rank "
                    "FROM issues_fts f JOIN issues i ON i.id = f.issue_id JOIN clients c ON c.id = i.client_id "
                    "WHERE issues_fts MATCH ? AND i.id <> ? ORDER BY rank LIMIT ?",
                    (match, issue_id, limit),
                ).fetchall()
            if not rows:
                rows = self.conn.execute(
                    "SELECT i.id, i.client_id, c.name AS client_name, i.title, i.tax_type, i.fiscal_year, i.status, "
                    "i.conclusion, i.updated_at FROM issues i JOIN clients c ON c.id = i.client_id "
                    "WHERE i.tax_type = ? AND i.id <> ? ORDER BY i.updated_at DESC LIMIT ?",
                    (issue["tax_type"], issue_id, limit),
                ).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                d.pop("rank", None)
                d["tags"] = self._tags_for(d["id"])
                out.append(d)
            return out

    def list_revisions(self, issue_id: int) -> list[dict]:
        with self.lock:
            self.get_issue(issue_id)
            rows = self.conn.execute(
                "SELECT id, saved_at, data FROM issue_revisions WHERE issue_id = ? ORDER BY id DESC", (issue_id,)
            ).fetchall()
            return [{"id": r["id"], "saved_at": r["saved_at"], "data": json.loads(r["data"])} for r in rows]

    # ------------------------------------------------------------------- meta
    def meta(self) -> dict:
        with self.lock:
            fiscal_years = [
                r[0]
                for r in self.conn.execute(
                    "SELECT DISTINCT fiscal_year FROM issues WHERE fiscal_year <> '' ORDER BY fiscal_year DESC"
                )
            ]
            staff = sorted(
                {
                    r[0]
                    for r in self.conn.execute(
                        "SELECT staff FROM issues WHERE staff <> '' UNION SELECT reviewer FROM issues WHERE reviewer <> '' "
                        "UNION SELECT staff FROM clients WHERE staff <> ''"
                    )
                }
            )
            tags = [
                {"name": r["name"], "count": r["cnt"]}
                for r in self.conn.execute(
                    "SELECT t.name, COUNT(it.issue_id) AS cnt FROM tags t LEFT JOIN issue_tags it ON it.tag_id = t.id "
                    "GROUP BY t.id ORDER BY cnt DESC, t.name"
                )
            ]
            used_tax_types = [r[0] for r in self.conn.execute("SELECT DISTINCT tax_type FROM issues")]
            counts = {
                "clients": self.conn.execute("SELECT COUNT(*) FROM clients").fetchone()[0],
                "issues": self.conn.execute("SELECT COUNT(*) FROM issues").fetchone()[0],
                "open": self.conn.execute(
                    "SELECT COUNT(*) FROM issues WHERE status IN ('検討中','要再検討')"
                ).fetchone()[0],
            }
        tax_types = list(TAX_TYPES)
        for t in used_tax_types:
            if t not in tax_types:
                tax_types.append(t)
        return {
            "tax_types": tax_types,
            "statuses": STATUSES,
            "entity_types": ENTITY_TYPES,
            "fiscal_years": fiscal_years,
            "staff": staff,
            "tags": tags,
            "counts": counts,
            "fts": self.fts_enabled,
            "db_path": os.path.abspath(self.path) if self.path != ":memory:" else self.path,
        }

    # ---------------------------------------------------------- export/import
    def export_data(self) -> dict:
        with self.lock:
            clients = [dict(r) for r in self.conn.execute("SELECT * FROM clients ORDER BY id")]
            issues = []
            for r in self.conn.execute("SELECT * FROM issues ORDER BY id"):
                d = dict(r)
                d["tags"] = self._tags_for(d["id"])
                issues.append(d)
        return {"format": "ronten-export", "version": 1, "exported_at": now(), "clients": clients, "issues": issues}

    def import_data(self, data: dict) -> dict:
        """JSON バックアップを追加取込する。

        顧問先は「コード」または「名称」が一致すれば既存に紐付け、なければ新規作成。
        論点は常に新規作成（重複チェックはしない）。
        """
        if not isinstance(data, dict) or data.get("format") != "ronten-export":
            raise ValidationError("取込ファイルの形式が不正です")
        clients = data.get("clients") or []
        issues = data.get("issues") or []
        id_map: dict[int, int] = {}
        created_clients = 0
        with self.lock, self.conn:
            for c in clients:
                old_id = c.get("id")
                existing = None
                code = _s(c.get("code"))
                if code:
                    existing = self.conn.execute("SELECT id FROM clients WHERE code = ?", (code,)).fetchone()
                if existing is None:
                    existing = self.conn.execute("SELECT id FROM clients WHERE name = ?", (_s(c.get("name")),)).fetchone()
                if existing is not None:
                    id_map[old_id] = existing["id"]
                else:
                    new = self.create_client(c)
                    id_map[old_id] = new["id"]
                    created_clients += 1
            created_issues = 0
            for it in issues:
                cid = id_map.get(it.get("client_id"))
                if cid is None:
                    continue
                payload = dict(it)
                payload["client_id"] = cid
                self.create_issue(payload)
                created_issues += 1
        return {"clients_created": created_clients, "issues_created": created_issues}

    def export_csv_rows(self) -> list[list[str]]:
        header = [
            "論点ID", "顧問先コード", "顧問先", "論点名", "税目", "事業年度", "ステータス", "担当者", "確認者", "結論日",
            "タグ", "事実関係", "論点", "検討内容", "結論", "根拠", "翌年以降の留意点", "作成日時", "更新日時",
        ]
        rows = [header]
        with self.lock:
            for r in self.conn.execute(
                "SELECT i.*, c.name AS client_name, c.code AS client_code FROM issues i JOIN clients c ON c.id = i.client_id ORDER BY c.kana, c.name, i.fiscal_year, i.id"
            ):
                rows.append([
                    str(r["id"]), r["client_code"], r["client_name"], r["title"], r["tax_type"], r["fiscal_year"],
                    r["status"], r["staff"], r["reviewer"], r["decided_on"], " ".join(self._tags_for(r["id"])),
                    r["facts"], r["question"], r["analysis"], r["conclusion"], r["basis"], r["followup"],
                    r["created_at"], r["updated_at"],
                ])
        return rows
