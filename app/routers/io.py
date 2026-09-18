"""CSV 入出力・バックアップ API。

仕訳 CSV 形式 (ヘッダ行あり, UTF-8 BOM 付き / Shift_JIS も取込可):
  日付, 伝票番号, 借方科目コード, 借方科目名, 借方補助コード, 借方補助名, 借方部門コード,
  貸方科目コード, 貸方科目名, 貸方補助コード, 貸方補助名, 貸方部門コード,
  金額, 消費税区分, 消費税額, 摘要, 伝票メモ
同じ 日付+伝票番号 の行は 1 伝票にまとめる。伝票番号が空の行は 1 行 1 伝票。
"""
from __future__ import annotations

import csv
import io
import shutil
from datetime import datetime

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response

from ..db import db, get_db_path
from ..master_data import (
    GROUP_MAP, GROUPS, ROLE_NAME_BY_CODE, ROLES, TAX_CLASS_MAP, TAX_CLASSES,
    resolve_bool, resolve_role, resolve_tax_class,
)
from .journals import EntryIn, LineIn, create_entries_bulk

router = APIRouter(prefix="/api", tags=["io"])

CSV_HEADER = ["日付", "伝票番号", "借方科目コード", "借方科目名", "借方補助コード", "借方補助名", "借方部門コード",
              "貸方科目コード", "貸方科目名", "貸方補助コード", "貸方補助名", "貸方部門コード",
              "金額", "消費税区分", "消費税額", "摘要", "伝票メモ"]


@router.get("/fiscal-years/{fy_id}/export/journal.csv")
def export_journal_csv(fy_id: int, date_from: str | None = None, date_to: str | None = None):
    with db() as conn:
        fy = conn.execute("SELECT * FROM fiscal_years WHERE id=?", (fy_id,)).fetchone()
        if not fy:
            raise HTTPException(404, "会計期間が見つかりません")
        rows = conn.execute(
            """
            SELECT e.entry_date, e.voucher_no, e.memo, l.amount, l.tax_class, l.tax_amount, l.description,
              da.code AS dc, da.name AS dn, ds.code AS dsc, ds.name AS dsn, dd.code AS ddc,
              ca.code AS cc, ca.name AS cn, cs.code AS csc, cs.name AS csn, cd.code AS cdc
            FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id
            LEFT JOIN accounts da ON da.id=l.debit_account_id
            LEFT JOIN sub_accounts ds ON ds.id=l.debit_sub_id
            LEFT JOIN departments dd ON dd.id=l.debit_dept_id
            LEFT JOIN accounts ca ON ca.id=l.credit_account_id
            LEFT JOIN sub_accounts cs ON cs.id=l.credit_sub_id
            LEFT JOIN departments cd ON cd.id=l.credit_dept_id
            WHERE e.fiscal_year_id=? AND e.entry_date>=? AND e.entry_date<=?
            ORDER BY e.entry_date, e.voucher_no, l.line_no
            """, (fy_id, date_from or fy["start_date"], date_to or fy["end_date"])).fetchall()
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(CSV_HEADER)
    for r in rows:
        w.writerow([r["entry_date"], r["voucher_no"], r["dc"] or "", r["dn"] or "", r["dsc"] or "", r["dsn"] or "", r["ddc"] or "",
                    r["cc"] or "", r["cn"] or "", r["csc"] or "", r["csn"] or "", r["cdc"] or "",
                    r["amount"], r["tax_class"], r["tax_amount"], r["description"], r["memo"]])
    data = ("﻿" + buf.getvalue()).encode("utf-8")
    fname = f"journal_{fy['start_date']}_{fy['end_date']}.csv"
    return Response(content=data, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


ACCOUNT_CSV_HEADER = ["コード", "科目名", "かな", "表示区分", "既定の税区分", "役割", "並び順", "有効"]


@router.get("/clients/{client_id}/export/accounts.csv")
def export_accounts_csv(client_id: int):
    with db() as conn:
        rows = conn.execute("SELECT * FROM accounts WHERE client_id=? ORDER BY sort_order, code", (client_id,)).fetchall()
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(ACCOUNT_CSV_HEADER)
    for r in rows:
        w.writerow([r["code"], r["name"], r["kana"], r["grp"], r["default_tax_class"],
                    ROLE_NAME_BY_CODE.get(r["role"], r["role"]) if r["role"] else "",
                    r["sort_order"], 1 if r["active"] else 0])
    return Response(content=("﻿" + buf.getvalue()).encode("utf-8"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="accounts.csv"'})


@router.get("/export/accounts-template.csv")
def export_accounts_template_csv():
    """空の科目表テンプレート。表示区分と税区分の選択肢を注記として付ける。"""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(ACCOUNT_CSV_HEADER)
    w.writerow(["100", "現金", "げんきん", "流動資産", "00", "", "10", "1"])
    w.writerow(["500", "売上高", "うりあげだか", "売上高", "11", "", "20", "1"])
    w.writerow([])
    w.writerow(["# 表示区分は次のいずれか:"] + [g["grp"] for g in GROUPS])
    w.writerow(["# 既定の税区分:"] + [f'{t["code"]}={t["name"]}' for t in TAX_CLASSES])
    w.writerow(["# 役割 (空欄可):"] + [r["name"] for r in ROLES if r["code"]])
    w.writerow(["# 「#」で始まる行は読み飛ばされます。"])
    return Response(content=("﻿" + buf.getvalue()).encode("utf-8"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="accounts_template.csv"'})


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp932", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise HTTPException(400, "文字コードを判別できません (UTF-8 / Shift_JIS に対応)")


def _norm_date(s: str) -> str:
    s = s.strip().replace("/", "-").replace(".", "-")
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise HTTPException(400, f"日付の形式が不正です: {s}")


def _to_int(s: str, default: int | None = 0) -> int | None:
    s = (s or "").strip().replace(",", "").replace("¥", "").replace("￥", "")
    if s == "":
        return default
    try:
        return int(float(s))
    except ValueError:
        raise HTTPException(400, f"数値の形式が不正です: {s}")


@router.post("/clients/{client_id}/import/journal")
async def import_journal_csv(client_id: int, file: UploadFile, dry_run: bool = False,
                             sub_id: int | None = None, ignore_suspense: bool = False):
    """仕訳 CSV を取り込む。

    sub_id を渡すと、その補助科目が属する科目の行で補助科目が空のものに、
    まとめてその補助科目を付ける。通帳ごとに CSV を分けて取り込むときに、
    CSV へ補助科目の列を用意しなくて済むようにするため。
    """
    text = _decode(await file.read())
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        raise HTTPException(400, "CSV が空です")
    header = [h.strip().lstrip("﻿") for h in header]
    idx = {h: i for i, h in enumerate(header)}

    def col(row, name, default=""):
        i = idx.get(name)
        return row[i].strip() if i is not None and i < len(row) else default

    with db() as conn:
        accts = conn.execute("SELECT id, code, name FROM accounts WHERE client_id=?", (client_id,)).fetchall()
        by_code = {a["code"]: a["id"] for a in accts}
        by_name = {a["name"]: a["id"] for a in accts}
        by_id = {a["id"]: f'{a["code"]} {a["name"]}' for a in accts}
        subs = conn.execute(
            "SELECT s.id, s.account_id, s.code, s.name FROM sub_accounts s JOIN accounts a ON a.id=s.account_id WHERE a.client_id=?",
            (client_id,)).fetchall()
        sub_by = {(s["account_id"], s["code"]): s["id"] for s in subs}
        sub_by_name = {(s["account_id"], s["name"]): s["id"] for s in subs}
        depts = {d["code"]: d["id"] for d in conn.execute("SELECT id, code FROM departments WHERE client_id=?", (client_id,)).fetchall()}
        # 資金諸口 (役割が「諸口」の科目、または名称が資金諸口・諸口の科目)。
        # コードや名称を変えても追えるよう、役割を第一の手掛かりにする。
        suspense = {a["id"]: f'{a["code"]} {a["name"]}' for a in conn.execute(
            "SELECT id, code, name FROM accounts WHERE client_id=? AND (role='suspense' OR name IN ('資金諸口','諸口'))",
            (client_id,)).fetchall()}
        fixed_sub = None
        if sub_id:
            fixed_sub = conn.execute(
                "SELECT s.id, s.account_id, s.code, s.name, a.code AS acode, a.name AS aname "
                "FROM sub_accounts s JOIN accounts a ON a.id=s.account_id WHERE s.id=? AND a.client_id=?",
                (sub_id, client_id)).fetchone()
            if fixed_sub is None:
                raise HTTPException(400, "指定された補助科目が見つかりません")

    def resolve_account(code: str, name: str, rowno: int, side: str) -> int | None:
        if not code and not name:
            return None
        if code and code in by_code:
            return by_code[code]
        if name and name in by_name:
            return by_name[name]
        raise HTTPException(400, f"{rowno} 行目: {side}科目 '{code or name}' が見つかりません")

    def resolve_sub(aid: int | None, code: str, name: str, rowno: int, side: str) -> int | None:
        if aid is None or (not code and not name):
            return None
        if code and (aid, code) in sub_by:
            return sub_by[(aid, code)]
        if name and (aid, name) in sub_by_name:
            return sub_by_name[(aid, name)]
        raise HTTPException(400, f"{rowno} 行目: {side}補助科目 '{code or name}' が見つかりません")

    groups: dict[tuple, EntryIn] = {}
    order: list[tuple] = []
    applied_by_key: dict[tuple, int] = {}   # 補助科目を補った行数 (伝票ごと)
    records: list[dict] = []                # 資金諸口のチェックに使う行の控え
    for rowno, row in enumerate(reader, 2):
        if not any(c.strip() for c in row):
            continue
        d = _norm_date(col(row, "日付"))
        vno = col(row, "伝票番号")
        key = (d, vno) if vno else (d, f"__row{rowno}")
        dr = resolve_account(col(row, "借方科目コード"), col(row, "借方科目名"), rowno, "借方")
        cr = resolve_account(col(row, "貸方科目コード"), col(row, "貸方科目名"), rowno, "貸方")
        tax_cls = col(row, "消費税区分") or "00"
        if tax_cls not in TAX_CLASS_MAP:
            raise HTTPException(400, f"{rowno} 行目: 消費税区分 '{tax_cls}' が不正です")
        tax_amt_s = col(row, "消費税額")
        dr_sub = resolve_sub(dr, col(row, "借方補助コード"), col(row, "借方補助名"), rowno, "借方")
        cr_sub = resolve_sub(cr, col(row, "貸方補助コード"), col(row, "貸方補助名"), rowno, "貸方")
        # 指定された補助科目を、その科目の行で補助科目が空のものにだけ付ける。
        # CSV に補助科目が書いてあれば、そちらを優先する。
        if fixed_sub is not None:
            if dr == fixed_sub["account_id"] and dr_sub is None:
                dr_sub = fixed_sub["id"]
                applied_by_key[key] = applied_by_key.get(key, 0) + 1
            if cr == fixed_sub["account_id"] and cr_sub is None:
                cr_sub = fixed_sub["id"]
                applied_by_key[key] = applied_by_key.get(key, 0) + 1
        line = LineIn(
            debit_account_id=dr, debit_sub_id=dr_sub,
            debit_dept_id=depts.get(col(row, "借方部門コード")) if col(row, "借方部門コード") else None,
            credit_account_id=cr, credit_sub_id=cr_sub,
            credit_dept_id=depts.get(col(row, "貸方部門コード")) if col(row, "貸方部門コード") else None,
            amount=_to_int(col(row, "金額")) or 0, tax_class=tax_cls,
            tax_amount=_to_int(tax_amt_s, None) if tax_amt_s else None,
            description=col(row, "摘要"),
        )
        if key not in groups:
            groups[key] = EntryIn(entry_date=d, memo=col(row, "伝票メモ"), voucher_no=None, lines=[])
            order.append(key)
        groups[key].lines.append(line)
        records.append({
            "rowno": rowno, "key": key, "vno": vno, "date": d,
            "debit": _acct_label(dr, by_id), "credit": _acct_label(cr, by_id),
            "debit_id": dr, "credit_id": cr,
            "amount": line.amount, "description": line.description,
        })

    entries = [groups[k] for k in order]
    from .journals import _validate_entry
    with db() as conn:
        validated = [_validate_entry(conn, client_id, e) for e in entries]
        existing = _existing_fingerprints(conn, client_id, [e.entry_date for e in entries])

    # 日付・金額・摘要が一致する伝票が既にあれば取り込まない (二重計上の防止)。
    # 科目・消費税区分は取り込んだ後で直すことがあるため、あえて比較しない。
    # 同じ内容が既に n 件あれば n 件までを飛ばし、それを超える分は取り込む。
    # 同じ日に同じ金額・同じ摘要の取引が本当に 2 回あることは珍しくないため。
    fresh: list[EntryIn] = []
    skipped: list[EntryIn] = []
    sub_applied = 0
    for key, e, v in zip(order, entries, validated):
        fp = _fingerprint(e.entry_date, e.memo, v["lines"])
        if existing.get(fp, 0) > 0:
            existing[fp] -= 1
            skipped.append(e)
        else:
            fresh.append(e)
            sub_applied += applied_by_key.get(key, 0)

    suspense_report = check_suspense_balance(records, suspense)

    result = {
        "count": len(fresh), "lines": sum(len(e.lines) for e in fresh),
        "skipped": len(skipped), "dry_run": dry_run,
        "skipped_samples": [_entry_label(e) for e in skipped[:20]],
        "sub_applied": sub_applied,
        "sub_label": (f'{fixed_sub["acode"]} {fixed_sub["aname"]} / {fixed_sub["name"]}'
                      if fixed_sub is not None else ""),
        "suspense": suspense_report,
        "blocked": False,
    }
    # 資金諸口が合っていないファイルは、そのまま取り込ませない。
    # 「不一致でも取り込む」を選んだ場合だけ通す。
    if not suspense_report["ok"] and not ignore_suspense:
        result["blocked"] = True
        result["count"] = 0
        result["lines"] = 0
        return result
    if dry_run:
        return result
    created = create_entries_bulk(client_id, fresh)
    result["count"] = created["count"]
    return result


def _acct_label(aid: int | None, by_id: dict) -> str:
    return by_id.get(aid, "") if aid else ""


def check_suspense_balance(records: list[dict], suspense: dict[int, str]) -> dict:
    """資金諸口の貸借一致をみる。

    伝票番号ごとに、借方が資金諸口の行の合計と貸方が資金諸口の行の合計を突き合わせ、
    さらにファイル全体でも同じ集計をする。合わない伝票には原因の手掛かりを付ける。
    """
    report = {
        "checked": bool(suspense),
        "accounts": sorted(suspense.values()),
        "ok": True,
        "debit": 0, "credit": 0, "diff": 0,
        "voucher_errors": [], "error_count": 0, "hints": [],
    }
    if not suspense or not records:
        return report

    # 伝票ごとの集計 (取り込みと同じ区切り = 日付 + 伝票番号)
    per: dict[tuple, dict] = {}
    for r in records:
        g = per.setdefault(r["key"], {
            "vno": r["vno"], "date": r["date"], "debit": 0, "credit": 0, "rows": []})
        g["rows"].append(r)
        if r["debit_id"] in suspense:
            g["debit"] += r["amount"]
        if r["credit_id"] in suspense:
            g["credit"] += r["amount"]

    report["debit"] = sum(g["debit"] for g in per.values())
    report["credit"] = sum(g["credit"] for g in per.values())
    report["diff"] = report["debit"] - report["credit"]

    bad = [dict(g, diff=g["debit"] - g["credit"]) for g in per.values() if g["debit"] != g["credit"]]
    report["error_count"] = len(bad)
    report["ok"] = not bad and report["diff"] == 0

    if report["diff"] != 0:
        report["hints"].append(
            f'ファイル全体で {abs(report["diff"]):,} 円ずれています。'
            f'{"借方" if report["diff"] > 0 else "貸方"}の資金諸口が多い状態です。')
    elif bad:
        report["hints"].append(
            "ファイル全体では合っているので、行がどの伝票番号に属するかの問題です。"
            "下の伝票どうしで、金額の振り分けや伝票番号の付け間違いを確認してください。")

    for g in sorted(bad, key=lambda x: (x["date"], str(x["vno"]))):
        g["hints"] = _suspense_hints(g, bad, suspense)
        g["rows"] = [{
            "rowno": r["rowno"], "debit": r["debit"], "credit": r["credit"],
            "amount": r["amount"], "description": r["description"],
            "suspense_side": ("借方" if r["debit_id"] in suspense else
                              "貸方" if r["credit_id"] in suspense else ""),
        } for r in g["rows"]]
        report["voucher_errors"].append(g)
    report["voucher_errors"] = report["voucher_errors"][:50]
    return report


def _suspense_hints(g: dict, bad: list[dict], suspense: dict[int, str]) -> list[str]:
    """合わない伝票について、考えられる原因を挙げる。"""
    hints = []
    diff = g["diff"]
    if g["debit"] and not g["credit"]:
        hints.append("資金諸口の行が借方にしかありません。相手側の行が抜けている可能性があります。")
    elif g["credit"] and not g["debit"]:
        hints.append("資金諸口の行が貸方にしかありません。相手側の行が抜けている可能性があります。")

    # 差額と同じ金額で、資金諸口を使っていない行があれば、その行が怪しい
    same = [r for r in g["rows"]
            if r["amount"] == abs(diff) and r["debit_id"] not in suspense and r["credit_id"] not in suspense]
    for r in same[:3]:
        hints.append(f'{r["rowno"]} 行目 ({r["amount"]:,} 円 {r["description"]}) が資金諸口を使っていません。'
                     "差額と同じ金額です。")

    # 打ち消し合う伝票があれば、伝票番号の取り違えが考えられる
    for other in bad:
        if other is g or other["diff"] != -diff:
            continue
        hints.append(f'伝票番号 {other["vno"] or "(空欄)"} ({other["date"]}) が反対に '
                     f'{abs(other["diff"]):,} 円ずれています。'
                     "どちらかの行の伝票番号が違う可能性があります。")
        break

    if not g["vno"]:
        hints.append("この行には伝票番号がありません。1 行で 1 伝票として扱われるため、"
                     "同じ取引の行には同じ伝票番号を付けてください。")
    return hints


def _fingerprint(entry_date: str, memo: str, lines: list[dict]) -> tuple:
    """重複判定に使うキー: 日付と、各行の金額・摘要・補助科目。

    科目・部門・消費税区分・税額・伝票メモ・伝票番号は比較しない。
    通帳から取り込んだ仕訳は後で科目を付け替えるのが前提で、付け替えた後に
    同じ期間を取り込み直しても重ならないようにするため。

    補助科目 (通帳) だけは比較に含める。通帳ごとに CSV を分けて取り込むとき、
    別々の口座に同じ日・同じ金額・同じ摘要の入出金があっても、
    片方が取り込まれないということが起きないようにするため。
    """
    return (entry_date, tuple(
        (l["amount"], l["description"].strip(), l["debit_sub_id"], l["credit_sub_id"])
        for l in lines))


def _existing_fingerprints(conn, client_id: int, dates: list[str]) -> dict[tuple, int]:
    """取り込む日付の範囲にある既存伝票を、内容キーごとの件数にまとめる。"""
    if not dates:
        return {}
    rows = conn.execute(
        """
        SELECT e.id, e.entry_date, e.memo, l.amount, l.description, l.debit_sub_id, l.credit_sub_id
        FROM journal_entries e JOIN journal_lines l ON l.entry_id=e.id
        WHERE e.client_id=? AND e.entry_date>=? AND e.entry_date<=?
        ORDER BY e.id, l.line_no
        """, (client_id, min(dates), max(dates))).fetchall()
    by_entry: dict[int, tuple] = {}
    lines_of: dict[int, list[dict]] = {}
    for r in rows:
        by_entry.setdefault(r["id"], (r["entry_date"], r["memo"]))
        lines_of.setdefault(r["id"], []).append(dict(r))
    counts: dict[tuple, int] = {}
    for eid, (d, memo) in by_entry.items():
        fp = _fingerprint(d, memo, lines_of[eid])
        counts[fp] = counts.get(fp, 0) + 1
    return counts


def _entry_label(e: EntryIn) -> str:
    """飛ばした伝票を画面に示すための短い表記。"""
    amount = sum(l.amount for l in e.lines if l.debit_account_id) or sum(l.amount for l in e.lines)
    desc = next((l.description for l in e.lines if l.description), "") or e.memo
    return f"{e.entry_date}  {amount:,}  {desc}".rstrip()


@router.post("/clients/{client_id}/import/accounts")
async def import_accounts_csv(client_id: int, file: UploadFile, mode: str = "merge", dry_run: bool = False):
    """勘定科目表を CSV から取り込む。

    mode="merge"   : コードが一致する科目は更新し、無いものは追加する。CSV に無い既存科目はそのまま。
    mode="replace" : 上記に加え、CSV に無い既存科目を無効化する (仕訳未使用なら削除)。

    仕訳・期首残高は科目 ID で結び付いているため、コードや名称を変更しても
    過去の入力内容は失われない。
    """
    if mode not in ("merge", "replace"):
        raise HTTPException(400, "mode は merge / replace のいずれか")
    text = _decode(await file.read())
    reader = csv.reader(io.StringIO(text))
    try:
        header = [h.strip().lstrip("﻿") for h in next(reader)]
    except StopIteration:
        raise HTTPException(400, "CSV が空です")
    idx = {h: i for i, h in enumerate(header)}
    if "コード" not in idx or "科目名" not in idx:
        raise HTTPException(400, "「コード」と「科目名」の列が必要です")

    def col(row, name, default=""):
        i = idx.get(name)
        return row[i].strip() if i is not None and i < len(row) else default

    parsed: list[dict] = []
    seen: dict[str, int] = {}
    for rowno, row in enumerate(reader, 2):
        if not any(c.strip() for c in row):
            continue
        code = col(row, "コード")
        if code.startswith("#"):
            continue
        name = col(row, "科目名")
        if not code or not name:
            raise HTTPException(400, f"{rowno} 行目: コードと科目名は必須です")
        if code in seen:
            raise HTTPException(400, f"{rowno} 行目: コード {code} が {seen[code]} 行目と重複しています")
        seen[code] = rowno
        grp = col(row, "表示区分")
        if grp not in GROUP_MAP:
            raise HTTPException(400, f"{rowno} 行目: 表示区分 '{grp}' が不正です")
        tax = resolve_tax_class(col(row, "既定の税区分") or col(row, "消費税区分"))
        if tax is None:
            raise HTTPException(400, f"{rowno} 行目: 税区分 '{col(row, '既定の税区分')}' が不正です")
        role = resolve_role(col(row, "役割"))
        if role is None:
            raise HTTPException(400, f"{rowno} 行目: 役割 '{col(row, '役割')}' が不正です")
        order_s = col(row, "並び順")
        parsed.append({
            "code": code, "name": name, "kana": col(row, "かな"), "grp": grp, "category": GROUP_MAP[grp],
            "default_tax_class": tax, "role": role,
            "sort_order": _to_int(order_s) if order_s else len(parsed) * 10,
            "active": 1 if resolve_bool(col(row, "有効")) else 0,
        })
    if not parsed:
        raise HTTPException(400, "取り込む行がありません")

    # 役割の重複チェック
    role_rows: dict[str, str] = {}
    for p in parsed:
        if p["role"]:
            if p["role"] in role_rows:
                raise HTTPException(400, f"役割「{ROLE_NAME_BY_CODE[p['role']]}」が {role_rows[p['role']]} と {p['code']} で重複しています")
            role_rows[p["role"]] = p["code"]

    with db() as conn:
        client = conn.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()
        if not client:
            raise HTTPException(404, "顧問先が見つかりません")
        existing = {r["code"]: dict(r) for r in conn.execute(
            "SELECT * FROM accounts WHERE client_id=?", (client_id,)).fetchall()}

        created = [p["code"] for p in parsed if p["code"] not in existing]
        updated = [p["code"] for p in parsed if p["code"] in existing]
        leftover = [a for code, a in existing.items() if code not in seen]
        to_delete, to_deactivate = [], []
        if mode == "replace":
            for a in leftover:
                used = conn.execute(
                    "SELECT COUNT(*) FROM journal_lines WHERE debit_account_id=? OR credit_account_id=?",
                    (a["id"], a["id"])).fetchone()[0]
                (to_deactivate if used else to_delete).append(a)

        # 経理方式に必要な役割が揃っているかを確認 (警告として返す)
        warnings: list[str] = []
        final_roles = set(role_rows)
        if mode != "replace":
            final_roles |= {a["role"] for code, a in existing.items() if a["role"] and code not in seen}
        if client["tax_method"] == "exclusive":
            for r in ("tax_receivable", "tax_payable"):
                if r not in final_roles:
                    warnings.append(f"税抜経理ですが「{ROLE_NAME_BY_CODE[r]}」の役割を持つ科目がありません")
        need = "owner_capital" if client["entity_type"] == "sole" else "retained"
        if need not in final_roles:
            warnings.append(f"「{ROLE_NAME_BY_CODE[need]}」の役割を持つ科目がありません (繰越処理で必要です)")

        result = {
            "created": len(created), "updated": len(updated),
            "deleted": len(to_delete), "deactivated": len(to_deactivate),
            "kept": len(leftover) if mode == "merge" else 0,
            "warnings": warnings, "dry_run": dry_run,
            "deleted_names": [f'{a["code"]} {a["name"]}' for a in to_delete][:20],
            "deactivated_names": [f'{a["code"]} {a["name"]}' for a in to_deactivate][:20],
        }
        if dry_run:
            return result

        for p in parsed:
            cur = existing.get(p["code"])
            if cur:
                conn.execute(
                    "UPDATE accounts SET name=?,kana=?,category=?,grp=?,default_tax_class=?,role=?,sort_order=?,active=? WHERE id=?",
                    (p["name"], p["kana"], p["category"], p["grp"], p["default_tax_class"], p["role"],
                     p["sort_order"], p["active"], cur["id"]))
            else:
                conn.execute(
                    "INSERT INTO accounts(client_id,code,name,kana,category,grp,default_tax_class,role,sort_order,active) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (client_id, p["code"], p["name"], p["kana"], p["category"], p["grp"],
                     p["default_tax_class"], p["role"], p["sort_order"], p["active"]))
        for a in to_delete:
            conn.execute("DELETE FROM opening_balances WHERE account_id=?", (a["id"],))
            conn.execute("DELETE FROM accounts WHERE id=?", (a["id"],))
        for a in to_deactivate:
            conn.execute("UPDATE accounts SET active=0 WHERE id=?", (a["id"],))
        return result


DESCRIPTION_CSV_HEADER = ["コード", "摘要", "かな", "関連科目コード", "並び順", "有効"]


@router.get("/clients/{client_id}/export/descriptions.csv")
def export_descriptions_csv(client_id: int):
    with db() as conn:
        rows = conn.execute(
            "SELECT d.*, a.code AS account_code FROM descriptions d LEFT JOIN accounts a ON a.id=d.account_id "
            "WHERE d.client_id=? ORDER BY d.sort_order, d.code, d.text", (client_id,)).fetchall()
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(DESCRIPTION_CSV_HEADER)
    for r in rows:
        w.writerow([r["code"], r["text"], r["kana"], r["account_code"] or "", r["sort_order"], 1 if r["active"] else 0])
    return Response(content=("﻿" + buf.getvalue()).encode("utf-8"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="descriptions.csv"'})


@router.post("/clients/{client_id}/import/descriptions")
async def import_descriptions_csv(client_id: int, file: UploadFile, mode: str = "merge", dry_run: bool = False):
    """摘要プリセットを CSV から取り込む。「摘要」の文字列で既存と照合する。"""
    if mode not in ("merge", "replace"):
        raise HTTPException(400, "mode は merge / replace のいずれか")
    text = _decode(await file.read())
    reader = csv.reader(io.StringIO(text))
    try:
        header = [h.strip().lstrip("﻿") for h in next(reader)]
    except StopIteration:
        raise HTTPException(400, "CSV が空です")
    idx = {h: i for i, h in enumerate(header)}
    if "摘要" not in idx:
        raise HTTPException(400, "「摘要」の列が必要です")

    def col(row, name, default=""):
        i = idx.get(name)
        return row[i].strip() if i is not None and i < len(row) else default

    with db() as conn:
        if not conn.execute("SELECT 1 FROM clients WHERE id=?", (client_id,)).fetchone():
            raise HTTPException(404, "顧問先が見つかりません")
        by_code = {a["code"]: a["id"] for a in conn.execute(
            "SELECT id, code FROM accounts WHERE client_id=?", (client_id,)).fetchall()}

        parsed: list[dict] = []
        seen: dict[str, int] = {}
        for rowno, row in enumerate(reader, 2):
            if not any(c.strip() for c in row):
                continue
            body = col(row, "摘要")
            if body.startswith("#"):
                continue
            if not body:
                raise HTTPException(400, f"{rowno} 行目: 摘要は必須です")
            if body in seen:
                raise HTTPException(400, f"{rowno} 行目: 摘要「{body}」が {seen[body]} 行目と重複しています")
            seen[body] = rowno
            acode = col(row, "関連科目コード")
            if acode and acode not in by_code:
                raise HTTPException(400, f"{rowno} 行目: 科目コード '{acode}' が見つかりません")
            order_s = col(row, "並び順")
            parsed.append({
                "code": col(row, "コード"), "text": body, "kana": col(row, "かな"),
                "account_id": by_code.get(acode) if acode else None,
                "sort_order": _to_int(order_s) if order_s else len(parsed) * 10,
                "active": 1 if resolve_bool(col(row, "有効")) else 0,
            })
        if not parsed:
            raise HTTPException(400, "取り込む行がありません")

        existing = {r["text"]: dict(r) for r in conn.execute(
            "SELECT * FROM descriptions WHERE client_id=?", (client_id,)).fetchall()}
        created = [p for p in parsed if p["text"] not in existing]
        updated = [p for p in parsed if p["text"] in existing]
        removed = [d for t, d in existing.items() if t not in seen] if mode == "replace" else []
        result = {"created": len(created), "updated": len(updated), "deleted": len(removed),
                  "kept": 0 if mode == "replace" else len(existing) - len(updated), "dry_run": dry_run,
                  "deleted_names": [d["text"] for d in removed][:20]}
        if dry_run:
            return result

        for p in parsed:
            cur = existing.get(p["text"])
            if cur:
                conn.execute(
                    "UPDATE descriptions SET code=?,kana=?,account_id=?,sort_order=?,active=? WHERE id=?",
                    (p["code"], p["kana"], p["account_id"], p["sort_order"], p["active"], cur["id"]))
            else:
                conn.execute(
                    "INSERT INTO descriptions(client_id,code,text,kana,account_id,sort_order,active) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (client_id, p["code"], p["text"], p["kana"], p["account_id"], p["sort_order"], p["active"]))
        for d in removed:
            conn.execute("DELETE FROM descriptions WHERE id=?", (d["id"],))
        return result


@router.get("/backup")
def download_backup():
    path = get_db_path()
    if not path.exists():
        raise HTTPException(404, "データベースがありません")
    # WAL 等を含めて整合の取れたコピーを作る
    with db() as conn:
        conn.execute("PRAGMA wal_checkpoint(FULL)")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = path.parent / "backup"
    backup_dir.mkdir(exist_ok=True)
    dst = backup_dir / f"kaikei_{stamp}.db"
    shutil.copy2(path, dst)
    return FileResponse(str(dst), media_type="application/octet-stream", filename=dst.name)
