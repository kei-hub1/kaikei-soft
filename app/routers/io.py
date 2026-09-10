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
async def import_journal_csv(client_id: int, file: UploadFile, dry_run: bool = False):
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
        subs = conn.execute(
            "SELECT s.id, s.account_id, s.code, s.name FROM sub_accounts s JOIN accounts a ON a.id=s.account_id WHERE a.client_id=?",
            (client_id,)).fetchall()
        sub_by = {(s["account_id"], s["code"]): s["id"] for s in subs}
        sub_by_name = {(s["account_id"], s["name"]): s["id"] for s in subs}
        depts = {d["code"]: d["id"] for d in conn.execute("SELECT id, code FROM departments WHERE client_id=?", (client_id,)).fetchall()}

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
        line = LineIn(
            debit_account_id=dr, debit_sub_id=resolve_sub(dr, col(row, "借方補助コード"), col(row, "借方補助名"), rowno, "借方"),
            debit_dept_id=depts.get(col(row, "借方部門コード")) if col(row, "借方部門コード") else None,
            credit_account_id=cr, credit_sub_id=resolve_sub(cr, col(row, "貸方補助コード"), col(row, "貸方補助名"), rowno, "貸方"),
            credit_dept_id=depts.get(col(row, "貸方部門コード")) if col(row, "貸方部門コード") else None,
            amount=_to_int(col(row, "金額")) or 0, tax_class=tax_cls,
            tax_amount=_to_int(tax_amt_s, None) if tax_amt_s else None,
            description=col(row, "摘要"),
        )
        if key not in groups:
            groups[key] = EntryIn(entry_date=d, memo=col(row, "伝票メモ"), voucher_no=None, lines=[])
            order.append(key)
        groups[key].lines.append(line)

    entries = [groups[k] for k in order]
    if dry_run:
        # 検証のみ
        from .journals import _validate_entry
        with db() as conn:
            for e in entries:
                _validate_entry(conn, client_id, e)
        return {"count": len(entries), "lines": sum(len(e.lines) for e in entries), "dry_run": True}
    result = create_entries_bulk(client_id, entries)
    return {"count": result["count"], "lines": sum(len(e.lines) for e in entries), "dry_run": False}


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
