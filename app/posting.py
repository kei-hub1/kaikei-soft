"""仕訳行 → 転記データ(ポスティング) への変換と、帳票の集計ロジック。

ポスティング: (account_id, sub_id, dept_id, side('D'/'C'), amount, counter_account_id, line)

税抜経理 (exclusive) の顧問先では、課税取引の行を本体と仮払/仮受消費税に分離して転記する。
税込経理 (inclusive) / 免税 (exempt) の場合は金額をそのまま転記する。
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from .master_data import GROUP_ORDER, normal_side, tax_class


@dataclass
class Posting:
    account_id: int
    sub_id: int          # 0 = 補助なし
    dept_id: int         # 0 = 部門なし
    side: str            # 'D' or 'C'
    amount: int
    counter_account_id: int | None   # 相手科目 (None = 諸口)
    counter_sub_id: int
    line_id: int
    entry_id: int
    entry_date: str
    voucher_no: int
    description: str
    tax_class: str
    is_tax_split: bool = False


def _tax_accounts(conn: sqlite3.Connection, client_id: int) -> dict[str, int]:
    rows = conn.execute(
        "SELECT id, role FROM accounts WHERE client_id=? AND role IN ('tax_receivable','tax_payable')",
        (client_id,),
    ).fetchall()
    return {r["role"]: r["id"] for r in rows}


def line_to_postings(line: sqlite3.Row | dict, tax_method: str, tax_accounts: dict[str, int]) -> list[Posting]:
    """1 仕訳行を転記データに変換する。"""
    l = dict(line)
    amount = int(l["amount"])
    dr = l.get("debit_account_id")
    cr = l.get("credit_account_id")
    base = dict(
        line_id=l["id"], entry_id=l["entry_id"], entry_date=l["entry_date"],
        voucher_no=l["voucher_no"], description=l.get("description") or "", tax_class=l.get("tax_class") or "00",
    )
    postings: list[Posting] = []

    tc = tax_class(l.get("tax_class") or "00")
    tax_amt = int(l.get("tax_amount") or 0)
    split = tax_method == "exclusive" and tax_amt != 0 and tc["kind"] in ("sales", "purchase")

    # 課税側 (本体を減額し消費税科目に転記する側) を決める
    tax_side = None
    tax_acct = None
    if split:
        if tc["kind"] == "sales":
            tax_side = "C" if cr else "D"
            tax_acct = tax_accounts.get("tax_payable")
        else:
            tax_side = "D" if dr else "C"
            tax_acct = tax_accounts.get("tax_receivable")
        if tax_acct is None:
            split = False

    if dr:
        amt = amount - tax_amt if (split and tax_side == "D") else amount
        postings.append(Posting(
            account_id=dr, sub_id=l.get("debit_sub_id") or 0, dept_id=l.get("debit_dept_id") or 0,
            side="D", amount=amt, counter_account_id=cr, counter_sub_id=l.get("credit_sub_id") or 0, **base,
        ))
        if split and tax_side == "D":
            postings.append(Posting(
                account_id=tax_acct, sub_id=0, dept_id=l.get("debit_dept_id") or 0,
                side="D", amount=tax_amt, counter_account_id=cr, counter_sub_id=l.get("credit_sub_id") or 0,
                is_tax_split=True, **base,
            ))
    if cr:
        amt = amount - tax_amt if (split and tax_side == "C") else amount
        postings.append(Posting(
            account_id=cr, sub_id=l.get("credit_sub_id") or 0, dept_id=l.get("credit_dept_id") or 0,
            side="C", amount=amt, counter_account_id=dr, counter_sub_id=l.get("debit_sub_id") or 0, **base,
        ))
        if split and tax_side == "C":
            postings.append(Posting(
                account_id=tax_acct, sub_id=0, dept_id=l.get("credit_dept_id") or 0,
                side="C", amount=tax_amt, counter_account_id=dr, counter_sub_id=l.get("debit_sub_id") or 0,
                is_tax_split=True, **base,
            ))
    return postings


LINE_SQL = """
SELECT l.*, e.entry_date, e.voucher_no, e.fiscal_year_id, e.client_id
FROM journal_lines l JOIN journal_entries e ON e.id = l.entry_id
WHERE e.fiscal_year_id = ? {extra}
ORDER BY e.entry_date, e.voucher_no, l.line_no
"""


def fetch_postings(conn: sqlite3.Connection, fiscal_year_id: int, date_from: str | None = None,
                   date_to: str | None = None) -> list[Posting]:
    fy = conn.execute("SELECT * FROM fiscal_years WHERE id=?", (fiscal_year_id,)).fetchone()
    if fy is None:
        return []
    client = conn.execute("SELECT * FROM clients WHERE id=?", (fy["client_id"],)).fetchone()
    tax_accounts = _tax_accounts(conn, client["id"])
    extra = ""
    params: list = [fiscal_year_id]
    if date_from:
        extra += " AND e.entry_date >= ?"
        params.append(date_from)
    if date_to:
        extra += " AND e.entry_date <= ?"
        params.append(date_to)
    rows = conn.execute(LINE_SQL.format(extra=extra), params).fetchall()
    result: list[Posting] = []
    for r in rows:
        result.extend(line_to_postings(r, client["tax_method"], tax_accounts))
    return result


# ---------------------------------------------------------------------------
# 集計
# ---------------------------------------------------------------------------

def accounts_map(conn: sqlite3.Connection, client_id: int) -> dict[int, dict]:
    rows = conn.execute(
        "SELECT * FROM accounts WHERE client_id=? ORDER BY sort_order, code", (client_id,)
    ).fetchall()
    return {r["id"]: dict(r) for r in rows}


def sub_accounts_map(conn: sqlite3.Connection, client_id: int) -> dict[int, dict]:
    rows = conn.execute(
        "SELECT s.* FROM sub_accounts s JOIN accounts a ON a.id=s.account_id WHERE a.client_id=?",
        (client_id,),
    ).fetchall()
    return {r["id"]: dict(r) for r in rows}


def opening_balances(conn: sqlite3.Connection, fiscal_year_id: int) -> dict[tuple[int, int], int]:
    """(account_id, sub_id) → 借方正の期首残高"""
    rows = conn.execute(
        "SELECT account_id, sub_account_id, amount FROM opening_balances WHERE fiscal_year_id=?",
        (fiscal_year_id,),
    ).fetchall()
    return {(r["account_id"], r["sub_account_id"]): r["amount"] for r in rows}


def signed(p: Posting) -> int:
    return p.amount if p.side == "D" else -p.amount


def trial_balance(conn: sqlite3.Connection, fiscal_year_id: int, date_from: str, date_to: str,
                  by_sub: bool = False) -> dict:
    """残高試算表。

    期首残高 = 期首残高マスタ(BS科目のみ) + 期間開始前の転記
    期間借方/貸方 = date_from〜date_to の転記
    残高 = 期首 + 借方 - 貸方  (借方正の符号付き)
    """
    fy = conn.execute("SELECT * FROM fiscal_years WHERE id=?", (fiscal_year_id,)).fetchone()
    accts = accounts_map(conn, fy["client_id"])
    subs = sub_accounts_map(conn, fy["client_id"])
    ob = opening_balances(conn, fiscal_year_id)

    open_bal: dict[tuple[int, int], int] = defaultdict(int)
    for (aid, sid), amt in ob.items():
        if aid in accts and accts[aid]["category"] in ("asset", "liability", "equity"):
            open_bal[(aid, sid)] += amt

    debit: dict[tuple[int, int], int] = defaultdict(int)
    credit: dict[tuple[int, int], int] = defaultdict(int)
    for p in fetch_postings(conn, fiscal_year_id, None, date_to):
        key = (p.account_id, p.sub_id)
        if p.entry_date < date_from:
            open_bal[key] += signed(p)
        else:
            if p.side == "D":
                debit[key] += p.amount
            else:
                credit[key] += p.amount

    keys = set(open_bal) | set(debit) | set(credit)
    # 科目ごとに集約
    per_account: dict[int, dict] = {}
    for (aid, sid) in keys:
        if aid not in accts:
            continue
        a = per_account.setdefault(aid, {"opening": 0, "debit": 0, "credit": 0, "subs": {}})
        a["opening"] += open_bal.get((aid, sid), 0)
        a["debit"] += debit.get((aid, sid), 0)
        a["credit"] += credit.get((aid, sid), 0)
        if by_sub and sid:
            a["subs"][sid] = {
                "opening": open_bal.get((aid, sid), 0),
                "debit": debit.get((aid, sid), 0),
                "credit": credit.get((aid, sid), 0),
            }

    rows = []
    totals: dict[str, dict] = defaultdict(lambda: {"opening": 0, "debit": 0, "credit": 0, "closing": 0})
    for aid, acc in sorted(accts.items(), key=lambda kv: (kv[1]["sort_order"], kv[1]["code"])):
        data = per_account.get(aid)
        if data is None:
            continue
        closing = data["opening"] + data["debit"] - data["credit"]
        if data["opening"] == 0 and data["debit"] == 0 and data["credit"] == 0:
            continue
        ns = normal_side(acc["category"])
        row = {
            "account_id": aid, "code": acc["code"], "name": acc["name"], "category": acc["category"],
            "grp": acc["grp"], "normal_side": ns,
            "opening": data["opening"], "debit": data["debit"], "credit": data["credit"], "closing": closing,
            # 正常残高側で見た残高 (表示用)
            "opening_n": data["opening"] if ns == "D" else -data["opening"],
            "closing_n": closing if ns == "D" else -closing,
            "subs": [],
        }
        for sid, sd in sorted(data["subs"].items(), key=lambda kv: subs.get(kv[0], {}).get("code", "")):
            s = subs.get(sid)
            if not s:
                continue
            sc = sd["opening"] + sd["debit"] - sd["credit"]
            row["subs"].append({
                "sub_id": sid, "code": s["code"], "name": s["name"],
                "opening": sd["opening"], "debit": sd["debit"], "credit": sd["credit"], "closing": sc,
                "opening_n": sd["opening"] if ns == "D" else -sd["opening"],
                "closing_n": sc if ns == "D" else -sc,
            })
        rows.append(row)
        t = totals[acc["category"]]
        t["opening"] += data["opening"]
        t["debit"] += data["debit"]
        t["credit"] += data["credit"]
        t["closing"] += closing
        g = totals["grp:" + acc["grp"]]
        g["opening"] += data["opening"]
        g["debit"] += data["debit"]
        g["credit"] += data["credit"]
        g["closing"] += closing

    # 損益 (貸方正: 収益 - 費用)  ※ 符号付き借方正の値を反転
    rev = totals["revenue"]
    exp = totals["expense"]
    net_income_period = -(rev["debit"] - rev["credit"]) - (exp["debit"] - exp["credit"])
    net_income_cum = -(rev["opening"] + rev["debit"] - rev["credit"]) - (exp["opening"] + exp["debit"] - exp["credit"])
    net_income_opening = -rev["opening"] - exp["opening"]

    return {
        "fiscal_year": dict(fy),
        "date_from": date_from,
        "date_to": date_to,
        "rows": rows,
        "totals": {k: v for k, v in totals.items()},
        "net_income": {"opening": net_income_opening, "period": net_income_period, "closing": net_income_cum},
    }


def ledger(conn: sqlite3.Connection, fiscal_year_id: int, account_id: int, date_from: str, date_to: str,
           sub_id: int | None = None) -> dict:
    """総勘定元帳 / 補助元帳。"""
    fy = conn.execute("SELECT * FROM fiscal_years WHERE id=?", (fiscal_year_id,)).fetchone()
    accts = accounts_map(conn, fy["client_id"])
    subs = sub_accounts_map(conn, fy["client_id"])
    acc = accts.get(account_id)
    if acc is None:
        return {"rows": [], "opening": 0, "closing": 0}
    ns = normal_side(acc["category"])
    ob = opening_balances(conn, fiscal_year_id)
    opening = 0
    if acc["category"] in ("asset", "liability", "equity"):
        for (aid, sid), amt in ob.items():
            if aid == account_id and (sub_id is None or sid == sub_id):
                opening += amt
    rows = []
    for p in fetch_postings(conn, fiscal_year_id, None, date_to):
        if p.account_id != account_id:
            continue
        if sub_id is not None and p.sub_id != sub_id:
            continue
        if p.entry_date < date_from:
            opening += signed(p)
            continue
        rows.append(p)
    bal = opening
    out = []
    tot_d = tot_c = 0
    for p in rows:
        bal += signed(p)
        tot_d += p.amount if p.side == "D" else 0
        tot_c += p.amount if p.side == "C" else 0
        ca = accts.get(p.counter_account_id) if p.counter_account_id else None
        cs = subs.get(p.counter_sub_id) if p.counter_sub_id else None
        s = subs.get(p.sub_id) if p.sub_id else None
        out.append({
            "entry_id": p.entry_id, "line_id": p.line_id, "date": p.entry_date, "voucher_no": p.voucher_no,
            "counter_code": ca["code"] if ca else "", "counter_name": ca["name"] if ca else "諸口",
            "counter_sub": cs["name"] if cs else "",
            "sub_name": s["name"] if s else "",
            "description": p.description, "tax_class": p.tax_class,
            "debit": p.amount if p.side == "D" else 0, "credit": p.amount if p.side == "C" else 0,
            "balance": bal if ns == "D" else -bal,
            "is_tax_split": p.is_tax_split,
        })
    return {
        "account": acc, "sub": subs.get(sub_id) if sub_id else None, "normal_side": ns,
        "opening": opening if ns == "D" else -opening,
        "total_debit": tot_d, "total_credit": tot_c,
        "closing": bal if ns == "D" else -bal,
        "rows": out,
    }


def _month_iter(start: str, end: str) -> list[str]:
    s = date.fromisoformat(start)
    e = date.fromisoformat(end)
    months = []
    cur = date(s.year, s.month, 1)
    while cur <= e:
        months.append(cur.strftime("%Y-%m"))
        cur = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
    return months


def monthly_trend(conn: sqlite3.Connection, fiscal_year_id: int) -> dict:
    """月次推移表: 科目ごとの月別発生額(正常残高側を正)と累計残高。"""
    fy = conn.execute("SELECT * FROM fiscal_years WHERE id=?", (fiscal_year_id,)).fetchone()
    accts = accounts_map(conn, fy["client_id"])
    months = _month_iter(fy["start_date"], fy["end_date"])
    ob = opening_balances(conn, fiscal_year_id)
    data: dict[int, dict] = {}
    for (aid, sid), amt in ob.items():
        if aid in accts and accts[aid]["category"] in ("asset", "liability", "equity"):
            d = data.setdefault(aid, {"opening": 0, "months": defaultdict(int)})
            d["opening"] += amt
    for p in fetch_postings(conn, fiscal_year_id):
        d = data.setdefault(p.account_id, {"opening": 0, "months": defaultdict(int)})
        d["months"][p.entry_date[:7]] += signed(p)
    rows = []
    for aid, acc in sorted(accts.items(), key=lambda kv: (kv[1]["sort_order"], kv[1]["code"])):
        d = data.get(aid)
        if not d:
            continue
        ns = normal_side(acc["category"])
        sign = 1 if ns == "D" else -1
        vals = [sign * d["months"].get(m, 0) for m in months]
        if d["opening"] == 0 and not any(vals):
            continue
        rows.append({
            "account_id": aid, "code": acc["code"], "name": acc["name"], "category": acc["category"], "grp": acc["grp"],
            "opening": sign * d["opening"], "months": vals, "total": sum(vals),
            "closing": sign * d["opening"] + sum(vals),
        })
    return {"fiscal_year": dict(fy), "months": months, "rows": rows}


def tax_summary(conn: sqlite3.Connection, fiscal_year_id: int, date_from: str, date_to: str) -> dict:
    """消費税集計表: 税区分ごとの取引金額(税込)、本体、消費税額。"""
    from .master_data import TAX_CLASSES
    rows = conn.execute(LINE_SQL.format(extra=" AND e.entry_date >= ? AND e.entry_date <= ?"),
                        (fiscal_year_id, date_from, date_to)).fetchall()
    agg: dict[str, dict] = {t["code"]: {"amount": 0, "tax": 0, "count": 0} for t in TAX_CLASSES}
    for r in rows:
        a = agg.setdefault(r["tax_class"], {"amount": 0, "tax": 0, "count": 0})
        a["amount"] += r["amount"]
        a["tax"] += r["tax_amount"]
        a["count"] += 1
    out = []
    sales_tax = purchase_tax = 0
    for t in TAX_CLASSES:
        a = agg[t["code"]]
        if a["count"] == 0:
            continue
        deductible = a["tax"] * t["deduction"] // 100 if t["kind"] == "purchase" else 0
        out.append({**t, "amount": a["amount"], "net": a["amount"] - a["tax"], "tax": a["tax"],
                    "deductible": deductible, "count": a["count"]})
        if t["kind"] == "sales":
            sales_tax += a["tax"]
        elif t["kind"] == "purchase":
            purchase_tax += deductible
    return {"rows": out, "sales_tax": sales_tax, "purchase_tax": purchase_tax, "net_tax": sales_tax - purchase_tax,
            "date_from": date_from, "date_to": date_to}


def financial_statements(conn: sqlite3.Connection, fiscal_year_id: int, date_to: str | None = None) -> dict:
    """貸借対照表 / 損益計算書。"""
    fy = conn.execute("SELECT * FROM fiscal_years WHERE id=?", (fiscal_year_id,)).fetchone()
    date_to = date_to or fy["end_date"]
    tb = trial_balance(conn, fiscal_year_id, fy["start_date"], date_to)
    groups: dict[str, list] = defaultdict(list)
    for r in tb["rows"]:
        groups[r["grp"]].append({"code": r["code"], "name": r["name"], "amount": r["closing_n"]})

    def gsum(grp: str) -> int:
        return sum(x["amount"] for x in groups.get(grp, []))

    net_income = tb["net_income"]["closing"]
    bs = {
        "assets": [{"grp": g, "items": groups.get(g, []), "total": gsum(g)} for g in ("流動資産", "固定資産", "繰延資産")],
        "liabilities": [{"grp": g, "items": groups.get(g, []), "total": gsum(g)} for g in ("流動負債", "固定負債")],
        "equity": [{"grp": "純資産", "items": groups.get("純資産", []) + [{"code": "", "name": "当期純利益", "amount": net_income}],
                    "total": gsum("純資産") + net_income}],
    }
    bs["total_assets"] = sum(x["total"] for x in bs["assets"])
    bs["total_liabilities"] = sum(x["total"] for x in bs["liabilities"])
    bs["total_equity"] = bs["equity"][0]["total"]
    bs["total_liabilities_equity"] = bs["total_liabilities"] + bs["total_equity"]

    sales = gsum("売上高")
    cogs = gsum("売上原価")
    sga = gsum("販売費及び一般管理費")
    nonop_rev = gsum("営業外収益")
    nonop_exp = gsum("営業外費用")
    extra_rev = gsum("特別利益")
    extra_exp = gsum("特別損失")
    tax = gsum("法人税等")
    gross = sales - cogs
    operating = gross - sga
    ordinary = operating + nonop_rev - nonop_exp
    pretax = ordinary + extra_rev - extra_exp
    pl = {
        "sections": [
            {"grp": g, "items": groups.get(g, []), "total": gsum(g)}
            for g in ("売上高", "売上原価", "販売費及び一般管理費", "営業外収益", "営業外費用", "特別利益", "特別損失", "法人税等")
        ],
        "gross_profit": gross, "operating_income": operating, "ordinary_income": ordinary,
        "pretax_income": pretax, "net_income": pretax - tax,
    }
    return {"fiscal_year": dict(fy), "date_to": date_to, "bs": bs, "pl": pl}
