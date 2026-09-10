"""顧問先・会計期間 API。"""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..db import db, now_iso, rows_to_dicts
from ..master_data import standard_accounts_for
from ..posting import trial_balance

router = APIRouter(prefix="/api", tags=["clients"])


class ClientIn(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1)
    kana: str = ""
    entity_type: str = "corp"
    tax_method: str = "inclusive"
    fiscal_start_month: int = Field(default=4, ge=1, le=12)
    note: str = ""
    # 新規作成時のみ有効。False の場合は科目を空で作り、CSV 取込で自前の科目表を入れる。
    copy_standard_accounts: bool = True


class FiscalYearIn(BaseModel):
    start_date: str
    end_date: str
    label: str = ""


def _validate_client(c: ClientIn) -> None:
    if c.entity_type not in ("corp", "sole"):
        raise HTTPException(400, "entity_type は corp / sole のいずれか")
    if c.tax_method not in ("inclusive", "exclusive", "exempt"):
        raise HTTPException(400, "tax_method は inclusive / exclusive / exempt のいずれか")


def _fy_label(start: str, end: str) -> str:
    s = date.fromisoformat(start)
    e = date.fromisoformat(end)
    return f"{s.year}/{s.month:02d}〜{e.year}/{e.month:02d}期"


def _default_fy(start_month: int, entity_type: str) -> tuple[str, str]:
    today = date.today()
    if entity_type == "sole":
        return f"{today.year}-01-01", f"{today.year}-12-31"
    y = today.year if today.month >= start_month else today.year - 1
    s = date(y, start_month, 1)
    e = (date(y + 1, start_month, 1) - timedelta(days=1))
    return s.isoformat(), e.isoformat()


@router.get("/clients")
def list_clients():
    with db() as conn:
        rows = conn.execute("SELECT * FROM clients ORDER BY code").fetchall()
        return rows_to_dicts(rows)


@router.post("/clients", status_code=201)
def create_client(c: ClientIn):
    _validate_client(c)
    with db() as conn:
        if conn.execute("SELECT 1 FROM clients WHERE code=?", (c.code,)).fetchone():
            raise HTTPException(409, "同じコードの顧問先が既に存在します")
        cur = conn.execute(
            "INSERT INTO clients(code,name,kana,entity_type,tax_method,fiscal_start_month,note,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (c.code, c.name, c.kana, c.entity_type, c.tax_method, c.fiscal_start_month, c.note, now_iso()),
        )
        cid = cur.lastrowid
        # 標準勘定科目を複写 (科目表を CSV で入れる場合は複写しない)
        if c.copy_standard_accounts:
            conn.executemany(
                "INSERT INTO accounts(client_id,code,name,kana,category,grp,default_tax_class,role,sort_order) VALUES(?,?,?,?,?,?,?,?,?)",
                [(cid, a["code"], a["name"], a["kana"], a["category"], a["grp"], a["default_tax_class"], a["role"], a["sort_order"])
                 for a in standard_accounts_for(c.entity_type)],
            )
        # 初期会計期間
        s, e = _default_fy(c.fiscal_start_month, c.entity_type)
        conn.execute("INSERT INTO fiscal_years(client_id,start_date,end_date,label) VALUES(?,?,?,?)",
                     (cid, s, e, _fy_label(s, e)))
        return dict(conn.execute("SELECT * FROM clients WHERE id=?", (cid,)).fetchone())


@router.get("/clients/{client_id}")
def get_client(client_id: int):
    with db() as conn:
        row = conn.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()
        if not row:
            raise HTTPException(404, "顧問先が見つかりません")
        return dict(row)


@router.put("/clients/{client_id}")
def update_client(client_id: int, c: ClientIn):
    _validate_client(c)
    with db() as conn:
        if not conn.execute("SELECT 1 FROM clients WHERE id=?", (client_id,)).fetchone():
            raise HTTPException(404, "顧問先が見つかりません")
        dup = conn.execute("SELECT 1 FROM clients WHERE code=? AND id<>?", (c.code, client_id)).fetchone()
        if dup:
            raise HTTPException(409, "同じコードの顧問先が既に存在します")
        conn.execute(
            "UPDATE clients SET code=?,name=?,kana=?,entity_type=?,tax_method=?,fiscal_start_month=?,note=? WHERE id=?",
            (c.code, c.name, c.kana, c.entity_type, c.tax_method, c.fiscal_start_month, c.note, client_id),
        )
        return dict(conn.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone())


@router.delete("/clients/{client_id}", status_code=204)
def delete_client(client_id: int):
    with db() as conn:
        conn.execute("DELETE FROM clients WHERE id=?", (client_id,))


# ---------------------------------------------------------------------------
# 会計期間
# ---------------------------------------------------------------------------

@router.get("/clients/{client_id}/fiscal-years")
def list_fiscal_years(client_id: int):
    with db() as conn:
        rows = conn.execute(
            "SELECT f.*, (SELECT COUNT(*) FROM journal_entries e WHERE e.fiscal_year_id=f.id) AS entry_count "
            "FROM fiscal_years f WHERE client_id=? ORDER BY start_date", (client_id,)
        ).fetchall()
        return rows_to_dicts(rows)


@router.post("/clients/{client_id}/fiscal-years", status_code=201)
def create_fiscal_year(client_id: int, f: FiscalYearIn):
    try:
        s = date.fromisoformat(f.start_date)
        e = date.fromisoformat(f.end_date)
    except ValueError:
        raise HTTPException(400, "日付は YYYY-MM-DD 形式で入力してください")
    if e <= s:
        raise HTTPException(400, "期末日は期首日より後にしてください")
    with db() as conn:
        if not conn.execute("SELECT 1 FROM clients WHERE id=?", (client_id,)).fetchone():
            raise HTTPException(404, "顧問先が見つかりません")
        overlap = conn.execute(
            "SELECT 1 FROM fiscal_years WHERE client_id=? AND NOT (end_date < ? OR start_date > ?)",
            (client_id, f.start_date, f.end_date),
        ).fetchone()
        if overlap:
            raise HTTPException(409, "既存の会計期間と重複しています")
        cur = conn.execute("INSERT INTO fiscal_years(client_id,start_date,end_date,label) VALUES(?,?,?,?)",
                           (client_id, f.start_date, f.end_date, f.label or _fy_label(f.start_date, f.end_date)))
        return dict(conn.execute("SELECT * FROM fiscal_years WHERE id=?", (cur.lastrowid,)).fetchone())


@router.post("/clients/{client_id}/fiscal-years/next", status_code=201)
def create_next_fiscal_year(client_id: int):
    """最終期の翌期を自動作成する。"""
    with db() as conn:
        last = conn.execute("SELECT * FROM fiscal_years WHERE client_id=? ORDER BY start_date DESC LIMIT 1",
                            (client_id,)).fetchone()
        if not last:
            raise HTTPException(404, "会計期間がありません")
        s = date.fromisoformat(last["end_date"]) + timedelta(days=1)
        # 翌期は期首日から 1 年間
        try:
            e = date(s.year + 1, s.month, s.day) - timedelta(days=1)
        except ValueError:  # 2/29 始まり
            e = date(s.year + 1, s.month, 28)
        cur = conn.execute("INSERT INTO fiscal_years(client_id,start_date,end_date,label) VALUES(?,?,?,?)",
                           (client_id, s.isoformat(), e.isoformat(), _fy_label(s.isoformat(), e.isoformat())))
        return dict(conn.execute("SELECT * FROM fiscal_years WHERE id=?", (cur.lastrowid,)).fetchone())


@router.put("/fiscal-years/{fy_id}")
def update_fiscal_year(fy_id: int, f: FiscalYearIn):
    with db() as conn:
        row = conn.execute("SELECT * FROM fiscal_years WHERE id=?", (fy_id,)).fetchone()
        if not row:
            raise HTTPException(404, "会計期間が見つかりません")
        out = conn.execute(
            "SELECT 1 FROM journal_entries WHERE fiscal_year_id=? AND (entry_date < ? OR entry_date > ?)",
            (fy_id, f.start_date, f.end_date)).fetchone()
        if out:
            raise HTTPException(409, "期間外となる仕訳が存在するため変更できません")
        conn.execute("UPDATE fiscal_years SET start_date=?, end_date=?, label=? WHERE id=?",
                     (f.start_date, f.end_date, f.label or _fy_label(f.start_date, f.end_date), fy_id))
        return dict(conn.execute("SELECT * FROM fiscal_years WHERE id=?", (fy_id,)).fetchone())


@router.post("/fiscal-years/{fy_id}/close")
def toggle_close(fy_id: int, closed: bool = True):
    with db() as conn:
        conn.execute("UPDATE fiscal_years SET closed=? WHERE id=?", (1 if closed else 0, fy_id))
        return dict(conn.execute("SELECT * FROM fiscal_years WHERE id=?", (fy_id,)).fetchone())


@router.delete("/fiscal-years/{fy_id}", status_code=204)
def delete_fiscal_year(fy_id: int):
    with db() as conn:
        n = conn.execute("SELECT COUNT(*) FROM journal_entries WHERE fiscal_year_id=?", (fy_id,)).fetchone()[0]
        if n:
            raise HTTPException(409, f"仕訳が {n} 件登録されているため削除できません")
        conn.execute("DELETE FROM fiscal_years WHERE id=?", (fy_id,))


@router.post("/fiscal-years/{fy_id}/carry-forward")
def carry_forward(fy_id: int):
    """繰越処理: 当期の期末残高を翌期の期首残高へ転記する。

    - BS 科目の期末残高(補助科目別)をそのまま翌期の期首残高へ
    - 当期純利益は 繰越利益剰余金(法人) / 元入金(個人) へ加算
    - 個人: 事業主貸・事業主借は元入金へ振り替えてゼロにする
    翌期が無い場合は自動作成する。
    """
    with db() as conn:
        fy = conn.execute("SELECT * FROM fiscal_years WHERE id=?", (fy_id,)).fetchone()
        if not fy:
            raise HTTPException(404, "会計期間が見つかりません")
        client = conn.execute("SELECT * FROM clients WHERE id=?", (fy["client_id"],)).fetchone()
        nxt = conn.execute("SELECT * FROM fiscal_years WHERE client_id=? AND start_date > ? ORDER BY start_date LIMIT 1",
                           (fy["client_id"], fy["end_date"])).fetchone()
        if not nxt:
            create_next_fiscal_year(fy["client_id"])
            nxt = conn.execute("SELECT * FROM fiscal_years WHERE client_id=? AND start_date > ? ORDER BY start_date LIMIT 1",
                               (fy["client_id"], fy["end_date"])).fetchone()
        tb = trial_balance(conn, fy_id, fy["start_date"], fy["end_date"], by_sub=True)
        roles = {r["role"]: r["id"] for r in conn.execute(
            "SELECT id, role FROM accounts WHERE client_id=? AND role<>''", (fy["client_id"],)).fetchall()}
        net_income = tb["net_income"]["closing"]  # 貸方正

        balances: dict[tuple[int, int], int] = {}
        for r in tb["rows"]:
            if r["category"] not in ("asset", "liability", "equity"):
                continue
            if r["subs"]:
                sub_total = 0
                for s in r["subs"]:
                    balances[(r["account_id"], s["sub_id"])] = s["closing"]
                    sub_total += s["closing"]
                rest = r["closing"] - sub_total
                if rest:
                    balances[(r["account_id"], 0)] = rest
            else:
                balances[(r["account_id"], 0)] = r["closing"]

        if client["entity_type"] == "sole":
            target = roles.get("owner_capital")
            if target is None:
                raise HTTPException(400, "元入金の科目 (role=owner_capital) がありません")
            adj = -net_income  # 貸方増加 → 借方正の符号では負
            for role in ("owner_drawing", "owner_contrib"):
                aid = roles.get(role)
                if aid is None:
                    continue
                for key in [k for k in balances if k[0] == aid]:
                    adj += balances.pop(key)
            balances[(target, 0)] = balances.get((target, 0), 0) + adj
        else:
            target = roles.get("retained")
            if target is None:
                raise HTTPException(400, "繰越利益剰余金の科目 (role=retained) がありません")
            balances[(target, 0)] = balances.get((target, 0), 0) - net_income

        conn.execute("DELETE FROM opening_balances WHERE fiscal_year_id=?", (nxt["id"],))
        conn.executemany(
            "INSERT INTO opening_balances(fiscal_year_id,account_id,sub_account_id,amount) VALUES(?,?,?,?)",
            [(nxt["id"], aid, sid, amt) for (aid, sid), amt in balances.items() if amt != 0],
        )
        return {"next_fiscal_year": dict(nxt), "count": len([1 for v in balances.values() if v]), "net_income": net_income}
