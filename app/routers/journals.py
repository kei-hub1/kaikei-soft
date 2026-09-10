"""仕訳 API。

1 伝票 (journal_entries) = 日付 + 伝票番号 + 複数行 (journal_lines)。
各行は 借方科目 / 貸方科目 のどちらか、または両方を持つ。
伝票内では 借方合計 = 貸方合計 でなければならない。
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..db import db, now_iso
from ..master_data import TAX_CLASS_MAP, calc_tax_inclusive, tax_class

router = APIRouter(prefix="/api", tags=["journals"])


class LineIn(BaseModel):
    debit_account_id: int | None = None
    debit_sub_id: int | None = None
    debit_dept_id: int | None = None
    credit_account_id: int | None = None
    credit_sub_id: int | None = None
    credit_dept_id: int | None = None
    amount: int = Field(ge=0)
    tax_class: str = "00"
    tax_amount: int | None = None   # None の場合は内税で自動計算
    description: str = ""


class EntryIn(BaseModel):
    entry_date: str
    memo: str = ""
    voucher_no: int | None = None
    lines: list[LineIn]


def _find_fy(conn, client_id: int, entry_date: str):
    return conn.execute(
        "SELECT * FROM fiscal_years WHERE client_id=? AND start_date<=? AND end_date>=?",
        (client_id, entry_date, entry_date)).fetchone()


def _validate_entry(conn, client_id: int, e: EntryIn) -> dict:
    try:
        date.fromisoformat(e.entry_date)
    except ValueError:
        raise HTTPException(400, "日付は YYYY-MM-DD 形式で入力してください")
    fy = _find_fy(conn, client_id, e.entry_date)
    if fy is None:
        raise HTTPException(400, f"{e.entry_date} を含む会計期間がありません")
    if fy["closed"]:
        raise HTTPException(409, "この会計期間は締め切られています")
    if not e.lines:
        raise HTTPException(400, "仕訳行がありません")
    client = conn.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()
    acct_ids = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM accounts WHERE client_id=?", (client_id,)).fetchall()}
    sub_ids = {r["id"]: r["account_id"] for r in conn.execute(
        "SELECT s.id, s.account_id FROM sub_accounts s JOIN accounts a ON a.id=s.account_id WHERE a.client_id=?", (client_id,)).fetchall()}
    dept_ids = {r["id"] for r in conn.execute("SELECT id FROM departments WHERE client_id=?", (client_id,)).fetchall()}

    total_d = total_c = 0
    lines = []
    for i, l in enumerate(e.lines, 1):
        if not l.debit_account_id and not l.credit_account_id:
            raise HTTPException(400, f"{i} 行目: 借方または貸方の科目を入力してください")
        if l.amount <= 0:
            raise HTTPException(400, f"{i} 行目: 金額を入力してください")
        for side, aid, sid, did in (("借方", l.debit_account_id, l.debit_sub_id, l.debit_dept_id),
                                   ("貸方", l.credit_account_id, l.credit_sub_id, l.credit_dept_id)):
            if aid is not None and aid not in acct_ids:
                raise HTTPException(400, f"{i} 行目: {side}科目が不正です")
            if sid:
                if sid not in sub_ids or sub_ids[sid] != aid:
                    raise HTTPException(400, f"{i} 行目: {side}補助科目が科目と一致しません")
            if did and did not in dept_ids:
                raise HTTPException(400, f"{i} 行目: {side}部門が不正です")
        if l.tax_class not in TAX_CLASS_MAP:
            raise HTTPException(400, f"{i} 行目: 消費税区分が不正です")
        tc = tax_class(l.tax_class)
        if client["tax_method"] == "exempt":
            tax_rate, tax_amount = 0, 0
        else:
            tax_rate = tc["rate"]
            tax_amount = l.tax_amount if l.tax_amount is not None else calc_tax_inclusive(l.amount, tax_rate)
            if tax_rate == 0:
                tax_amount = 0
        if l.debit_account_id:
            total_d += l.amount
        if l.credit_account_id:
            total_c += l.amount
        lines.append({
            "debit_account_id": l.debit_account_id, "debit_sub_id": l.debit_sub_id or None, "debit_dept_id": l.debit_dept_id or None,
            "credit_account_id": l.credit_account_id, "credit_sub_id": l.credit_sub_id or None, "credit_dept_id": l.credit_dept_id or None,
            "amount": l.amount, "tax_class": l.tax_class, "tax_rate": tax_rate, "tax_amount": tax_amount,
            "description": l.description.strip(),
        })
    if total_d != total_c:
        raise HTTPException(400, f"貸借が一致しません (借方 {total_d:,} / 貸方 {total_c:,})")
    return {"fy": fy, "lines": lines}


def _insert_lines(conn, entry_id: int, lines: list[dict]) -> None:
    conn.executemany(
        "INSERT INTO journal_lines(entry_id,line_no,debit_account_id,debit_sub_id,debit_dept_id,credit_account_id,credit_sub_id,credit_dept_id,"
        "amount,tax_class,tax_rate,tax_amount,description) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(entry_id, i, l["debit_account_id"], l["debit_sub_id"], l["debit_dept_id"], l["credit_account_id"], l["credit_sub_id"],
          l["credit_dept_id"], l["amount"], l["tax_class"], l["tax_rate"], l["tax_amount"], l["description"])
         for i, l in enumerate(lines, 1)],
    )


def _next_voucher_no(conn, fy_id: int) -> int:
    r = conn.execute("SELECT MAX(voucher_no) FROM journal_entries WHERE fiscal_year_id=?", (fy_id,)).fetchone()
    return (r[0] or 0) + 1


ENTRY_SELECT = """
SELECT e.*,
  (SELECT SUM(CASE WHEN l.debit_account_id IS NOT NULL THEN l.amount ELSE 0 END) FROM journal_lines l WHERE l.entry_id=e.id) AS total
FROM journal_entries e
"""

LINE_SELECT = """
SELECT l.*,
  da.code AS debit_code, da.name AS debit_name, ds.code AS debit_sub_code, ds.name AS debit_sub_name, dd.name AS debit_dept_name,
  ca.code AS credit_code, ca.name AS credit_name, cs.code AS credit_sub_code, cs.name AS credit_sub_name, cd.name AS credit_dept_name
FROM journal_lines l
LEFT JOIN accounts da ON da.id=l.debit_account_id
LEFT JOIN sub_accounts ds ON ds.id=l.debit_sub_id
LEFT JOIN departments dd ON dd.id=l.debit_dept_id
LEFT JOIN accounts ca ON ca.id=l.credit_account_id
LEFT JOIN sub_accounts cs ON cs.id=l.credit_sub_id
LEFT JOIN departments cd ON cd.id=l.credit_dept_id
"""


_DESC_EXPR = ("(SELECT MIN(l.description) FROM journal_lines l "
              "WHERE l.entry_id=e.id AND l.description<>'')")
# 摘要プリセットに「かな」があればそれを並び替えキーに使い、五十音順に並べる。
# 無ければ摘要そのものの文字コード順。
_DESC_SORT_KEY = (f"COALESCE((SELECT NULLIF(d.kana,'') FROM descriptions d "
                  f"WHERE d.client_id=e.client_id AND d.text={_DESC_EXPR}), {_DESC_EXPR})")

# 一覧の並び順。摘要順は、同じ摘要の取引をまとめて確認するための並び。
ENTRY_ORDERS = {
    "date": "e.entry_date, e.voucher_no",
    # 摘要なしの伝票 (副問い合わせが NULL) は最後に置く
    "description": (f"{_DESC_EXPR} IS NULL, {_DESC_SORT_KEY}, {_DESC_EXPR}, e.entry_date, e.voucher_no"),
}


def _load_entries(conn, where: str, params: list, limit: int | None = None, offset: int = 0,
                  sort: str = "date") -> list[dict]:
    order = ENTRY_ORDERS.get(sort, ENTRY_ORDERS["date"])
    sql = ENTRY_SELECT + " WHERE " + where + " ORDER BY " + order
    if limit:
        sql += f" LIMIT {int(limit)} OFFSET {int(offset)}"
    entries = [dict(r) for r in conn.execute(sql, params).fetchall()]
    if not entries:
        return []
    ids = [e["id"] for e in entries]
    by_id = {e["id"]: e for e in entries}
    for e in entries:
        e["lines"] = []
    # SQLite のパラメータ上限を避けて分割
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        q = LINE_SELECT + f" WHERE l.entry_id IN ({','.join('?' * len(chunk))}) ORDER BY l.entry_id, l.line_no"
        for r in conn.execute(q, chunk).fetchall():
            by_id[r["entry_id"]]["lines"].append(dict(r))
    return entries


@router.get("/clients/{client_id}/entries")
def list_entries(
    client_id: int,
    fiscal_year_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    account_id: int | None = None,
    sub_id: int | None = None,
    q: str | None = None,
    description: str | None = None,
    sort: str = "date",
    limit: int = Query(default=500, le=5000),
    offset: int = 0,
):
    where = ["e.client_id=?"]
    params: list = [client_id]
    if fiscal_year_id:
        where.append("e.fiscal_year_id=?")
        params.append(fiscal_year_id)
    if date_from:
        where.append("e.entry_date>=?")
        params.append(date_from)
    if date_to:
        where.append("e.entry_date<=?")
        params.append(date_to)
    if account_id:
        where.append("EXISTS (SELECT 1 FROM journal_lines l WHERE l.entry_id=e.id AND (l.debit_account_id=? OR l.credit_account_id=?))")
        params += [account_id, account_id]
    if sub_id:
        where.append("EXISTS (SELECT 1 FROM journal_lines l WHERE l.entry_id=e.id AND (l.debit_sub_id=? OR l.credit_sub_id=?))")
        params += [sub_id, sub_id]
    if q:
        where.append("(e.memo LIKE ? OR EXISTS (SELECT 1 FROM journal_lines l WHERE l.entry_id=e.id AND l.description LIKE ?))")
        params += [f"%{q}%", f"%{q}%"]
    if description:
        # 摘要の完全一致 (同じ摘要の取引だけを抜き出す)
        where.append("EXISTS (SELECT 1 FROM journal_lines l WHERE l.entry_id=e.id AND l.description=?)")
        params.append(description)
    if sort not in ENTRY_ORDERS:
        raise HTTPException(400, "sort は date / description のいずれか")
    with db() as conn:
        entries = _load_entries(conn, " AND ".join(where), params, limit, offset, sort)
        total = conn.execute("SELECT COUNT(*) FROM journal_entries e WHERE " + " AND ".join(where), params).fetchone()[0]
        return {"entries": entries, "total": total}


@router.get("/entries/{entry_id}")
def get_entry(entry_id: int):
    with db() as conn:
        rows = _load_entries(conn, "e.id=?", [entry_id])
        if not rows:
            raise HTTPException(404, "仕訳が見つかりません")
        return rows[0]


@router.post("/clients/{client_id}/entries", status_code=201)
def create_entry(client_id: int, e: EntryIn):
    with db() as conn:
        v = _validate_entry(conn, client_id, e)
        fy = v["fy"]
        vno = e.voucher_no or _next_voucher_no(conn, fy["id"])
        ts = now_iso()
        cur = conn.execute(
            "INSERT INTO journal_entries(client_id,fiscal_year_id,entry_date,voucher_no,memo,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            (client_id, fy["id"], e.entry_date, vno, e.memo, ts, ts))
        _insert_lines(conn, cur.lastrowid, v["lines"])
        return _load_entries(conn, "e.id=?", [cur.lastrowid])[0]


@router.put("/entries/{entry_id}")
def update_entry(entry_id: int, e: EntryIn):
    with db() as conn:
        row = conn.execute("SELECT * FROM journal_entries WHERE id=?", (entry_id,)).fetchone()
        if not row:
            raise HTTPException(404, "仕訳が見つかりません")
        old_fy = conn.execute("SELECT closed FROM fiscal_years WHERE id=?", (row["fiscal_year_id"],)).fetchone()
        if old_fy and old_fy["closed"]:
            raise HTTPException(409, "この会計期間は締め切られています")
        v = _validate_entry(conn, row["client_id"], e)
        fy = v["fy"]
        vno = e.voucher_no or row["voucher_no"]
        if fy["id"] != row["fiscal_year_id"]:
            vno = _next_voucher_no(conn, fy["id"])
        conn.execute("UPDATE journal_entries SET fiscal_year_id=?,entry_date=?,voucher_no=?,memo=?,updated_at=? WHERE id=?",
                     (fy["id"], e.entry_date, vno, e.memo, now_iso(), entry_id))
        conn.execute("DELETE FROM journal_lines WHERE entry_id=?", (entry_id,))
        _insert_lines(conn, entry_id, v["lines"])
        return _load_entries(conn, "e.id=?", [entry_id])[0]


@router.delete("/entries/{entry_id}", status_code=204)
def delete_entry(entry_id: int):
    with db() as conn:
        row = conn.execute("SELECT * FROM journal_entries WHERE id=?", (entry_id,)).fetchone()
        if not row:
            raise HTTPException(404, "仕訳が見つかりません")
        fy = conn.execute("SELECT closed FROM fiscal_years WHERE id=?", (row["fiscal_year_id"],)).fetchone()
        if fy and fy["closed"]:
            raise HTTPException(409, "この会計期間は締め切られています")
        conn.execute("DELETE FROM journal_entries WHERE id=?", (entry_id,))


@router.post("/clients/{client_id}/entries/bulk", status_code=201)
def create_entries_bulk(client_id: int, entries: list[EntryIn]):
    """複数伝票の一括登録 (CSV 取込などで使用)。全件検証してから登録する。"""
    with db() as conn:
        validated = [(_validate_entry(conn, client_id, e), e) for e in entries]
        ts = now_iso()
        next_no: dict[int, int] = {}
        ids = []
        for v, e in validated:
            fy_id = v["fy"]["id"]
            if fy_id not in next_no:
                next_no[fy_id] = _next_voucher_no(conn, fy_id)
            vno = e.voucher_no or next_no[fy_id]
            if not e.voucher_no:
                next_no[fy_id] += 1
            cur = conn.execute(
                "INSERT INTO journal_entries(client_id,fiscal_year_id,entry_date,voucher_no,memo,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                (client_id, fy_id, e.entry_date, vno, e.memo, ts, ts))
            _insert_lines(conn, cur.lastrowid, v["lines"])
            ids.append(cur.lastrowid)
        return {"count": len(ids), "ids": ids}
