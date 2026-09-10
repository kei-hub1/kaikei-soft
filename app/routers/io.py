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
from ..master_data import TAX_CLASS_MAP
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


@router.get("/clients/{client_id}/export/accounts.csv")
def export_accounts_csv(client_id: int):
    with db() as conn:
        rows = conn.execute("SELECT * FROM accounts WHERE client_id=? ORDER BY sort_order, code", (client_id,)).fetchall()
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(["コード", "科目名", "かな", "表示区分", "消費税区分", "有効"])
    for r in rows:
        w.writerow([r["code"], r["name"], r["kana"], r["grp"], r["default_tax_class"], r["active"]])
    return Response(content=("﻿" + buf.getvalue()).encode("utf-8"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="accounts.csv"'})


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
