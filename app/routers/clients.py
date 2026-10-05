"""顧問先・会計期間 API。"""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..db import db, now_iso, rows_to_dicts
from ..master_data import CHART_CODES, chart_accounts
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
    # 新規作成時のみ有効。どの科目表を複写するか (tkc / standard / none)。
    chart: str = "tkc"


class FiscalYearIn(BaseModel):
    start_date: str
    end_date: str
    label: str = ""


def _validate_client(c: ClientIn) -> None:
    if c.entity_type not in ("corp", "sole"):
        raise HTTPException(400, "entity_type は corp / sole のいずれか")
    if c.tax_method not in ("inclusive", "exclusive", "exempt"):
        raise HTTPException(400, "tax_method は inclusive / exclusive / exempt のいずれか")
    if c.chart not in CHART_CODES:
        raise HTTPException(400, "科目表の指定が不正です")


def _fy_label(start: str, end: str) -> str:
    s = date.fromisoformat(start)
    e = date.fromisoformat(end)
    return f"{s.year}/{s.month:02d}〜{e.year}/{e.month:02d}期"


def fy_period_for(d: date, start_month: int, entity_type: str) -> tuple[str, str]:
    """顧問先の決算期の決まりで、日付 d を含む 1 年間の会計期間 (期首日, 期末日)。

    個人事業主は暦年 (1/1〜12/31)。法人は期首月の 1 日から 1 年間。
    """
    if entity_type == "sole":
        return f"{d.year}-01-01", f"{d.year}-12-31"
    y = d.year if d.month >= start_month else d.year - 1
    s = date(y, start_month, 1)
    e = (date(y + 1, start_month, 1) - timedelta(days=1))
    return s.isoformat(), e.isoformat()


def _default_fy(start_month: int, entity_type: str) -> tuple[str, str]:
    return fy_period_for(date.today(), start_month, entity_type)


def plan_fiscal_years(fys: list[dict], dates: list[str], start_month: int, entity_type: str) -> list[dict]:
    """dates のどれかを含む会計期間が無いとき、どう直せば全部が収まるかを考える。

    fys: 既存の会計期間 (id, start_date, end_date, label, closed, entry_min, entry_max)
    戻り値の各要素:
      {"action": "create", "start_date", "end_date", "partial"}   新しく作る
      {"action": "adjust", "fy_id", "label", "old_start", "old_end", "start_date", "end_date"}
          既存の期間の期首日・期末日を直す (法人で作った顧問先を個人に直したときなど)
    partial=True は、前後の期間に挟まれて 1 年に満たない期間しか作れないもの。
    """
    sim = [dict(f) for f in fys]
    actions: list[dict] = []

    def covered(d: str) -> bool:
        return any(f["start_date"] <= d <= f["end_date"] for f in sim)

    for _ in range(20):
        rest = sorted({d for d in dates if not covered(d)})
        if not rest:
            break
        d = rest[0]
        s, e = fy_period_for(date.fromisoformat(d), start_month, entity_type)
        over = [f for f in sim if not (f["end_date"] < s or f["start_date"] > e)]
        if not over:
            actions.append({"action": "create", "start_date": s, "end_date": e, "partial": False})
            sim.append({"id": None, "start_date": s, "end_date": e})
            continue
        if len(over) == 1:
            f = over[0]
            fits = f.get("entry_min") is None or (s <= f["entry_min"] and f["entry_max"] <= e)
            if f.get("id") and not f.get("closed") and fits:
                actions.append({"action": "adjust", "fy_id": f["id"], "label": f.get("label", ""),
                                "old_start": f["start_date"], "old_end": f["end_date"],
                                "start_date": s, "end_date": e})
                f["start_date"], f["end_date"] = s, e
                continue
        # 既存の期間を動かせないので、前後の期間のすき間だけを作る
        prev_end = max((f["end_date"] for f in sim if f["end_date"] < d), default=None)
        next_start = min((f["start_date"] for f in sim if f["start_date"] > d), default=None)
        gs = max(s, (date.fromisoformat(prev_end) + timedelta(days=1)).isoformat()) if prev_end else s
        ge = min(e, (date.fromisoformat(next_start) - timedelta(days=1)).isoformat()) if next_start else e
        actions.append({"action": "create", "start_date": gs, "end_date": ge, "partial": (gs, ge) != (s, e)})
        sim.append({"id": None, "start_date": gs, "end_date": ge})
    return actions


def fiscal_years_with_entries(conn, client_id: int) -> list[dict]:
    """会計期間に、登録済み仕訳の最初と最後の日付を添えて返す。"""
    rows = conn.execute(
        "SELECT f.id, f.start_date, f.end_date, f.label, f.closed, "
        "(SELECT MIN(entry_date) FROM journal_entries e WHERE e.fiscal_year_id=f.id) AS entry_min, "
        "(SELECT MAX(entry_date) FROM journal_entries e WHERE e.fiscal_year_id=f.id) AS entry_max, "
        "(SELECT COUNT(*) FROM journal_entries e WHERE e.fiscal_year_id=f.id) AS entry_count "
        "FROM fiscal_years f WHERE client_id=? ORDER BY start_date", (client_id,)).fetchall()
    return rows_to_dicts(rows)


def apply_fiscal_year_plan(conn, client_id: int, actions: list[dict]) -> list[dict]:
    """plan_fiscal_years の結果を登録する。"""
    done = []
    for a in actions:
        s, e = a["start_date"], a["end_date"]
        if a["action"] == "create":
            if conn.execute("SELECT 1 FROM fiscal_years WHERE client_id=? AND NOT (end_date < ? OR start_date > ?)",
                            (client_id, s, e)).fetchone():
                raise HTTPException(409, f"{s}〜{e} は既存の会計期間と重複しています")
            cur = conn.execute("INSERT INTO fiscal_years(client_id,start_date,end_date,label) VALUES(?,?,?,?)",
                               (client_id, s, e, _fy_label(s, e)))
            done.append({**a, "fy_id": cur.lastrowid, "label": _fy_label(s, e)})
        else:
            _check_fy_change(conn, client_id, a["fy_id"], s, e)
            conn.execute("UPDATE fiscal_years SET start_date=?, end_date=?, label=? WHERE id=?",
                         (s, e, _fy_label(s, e), a["fy_id"]))
            done.append({**a, "label": _fy_label(s, e)})
    return done


def _check_fy_change(conn, client_id: int, fy_id: int, start: str, end: str) -> None:
    """会計期間の期首日・期末日を変えてよいか。だめなら HTTPException。"""
    try:
        if date.fromisoformat(end) <= date.fromisoformat(start):
            raise HTTPException(400, "期末日は期首日より後にしてください")
    except ValueError:
        raise HTTPException(400, "日付は YYYY-MM-DD 形式で入力してください")
    if conn.execute("SELECT 1 FROM journal_entries WHERE fiscal_year_id=? AND (entry_date < ? OR entry_date > ?)",
                    (fy_id, start, end)).fetchone():
        raise HTTPException(409, "期間外となる仕訳が存在するため変更できません")
    if conn.execute("SELECT 1 FROM fiscal_years WHERE client_id=? AND id<>? AND NOT (end_date < ? OR start_date > ?)",
                    (client_id, fy_id, start, end)).fetchone():
        raise HTTPException(409, "ほかの会計期間と重複するため変更できません")


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
        # 選択された科目表を複写する
        conn.executemany(
            "INSERT INTO accounts(client_id,code,name,kana,category,grp,default_tax_class,role,sort_order) VALUES(?,?,?,?,?,?,?,?,?)",
            [(cid, a["code"], a["name"], a["kana"], a["category"], a["grp"], a["default_tax_class"], a["role"], a["sort_order"])
             for a in chart_accounts(c.chart, c.entity_type)],
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
        before = conn.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()
        conn.execute(
            "UPDATE clients SET code=?,name=?,kana=?,entity_type=?,tax_method=?,fiscal_start_month=?,note=? WHERE id=?",
            (c.code, c.name, c.kana, c.entity_type, c.tax_method, c.fiscal_start_month, c.note, client_id),
        )
        out = dict(conn.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone())
        out["fiscal_year_adjusted"] = None
        # 事業形態・期首月を直したとき、まだ何も入力していなければ、
        # 作成時に自動で作った会計期間も新しい決まりに合わせて作り直す。
        # (法人で作ってから個人に直すと、4 月始まりの期間のままで 1〜3 月の仕訳が入らないため)
        rule_changed = (before["entity_type"] != c.entity_type
                        or (c.entity_type == "corp" and before["fiscal_start_month"] != c.fiscal_start_month))
        if rule_changed:
            fys = conn.execute("SELECT * FROM fiscal_years WHERE client_id=?", (client_id,)).fetchall()
            used = conn.execute("SELECT 1 FROM journal_entries WHERE client_id=? LIMIT 1", (client_id,)).fetchone() or \
                conn.execute("SELECT 1 FROM opening_balances o JOIN fiscal_years f ON f.id=o.fiscal_year_id "
                             "WHERE f.client_id=? AND o.amount<>0 LIMIT 1", (client_id,)).fetchone()
            if len(fys) == 1 and not used and not fys[0]["closed"]:
                s, e = _default_fy(c.fiscal_start_month, c.entity_type)
                if (s, e) != (fys[0]["start_date"], fys[0]["end_date"]):
                    conn.execute("UPDATE fiscal_years SET start_date=?, end_date=?, label=? WHERE id=?",
                                 (s, e, _fy_label(s, e), fys[0]["id"]))
                    out["fiscal_year_adjusted"] = {"start_date": s, "end_date": e, "label": _fy_label(s, e)}
        return out


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
        _check_fy_change(conn, row["client_id"], fy_id, f.start_date, f.end_date)
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
