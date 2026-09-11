"""通帳マスタと、通帳の写真・テキストから仕訳を起こす API。

起こす仕訳は次の 2 通りだけ (経費・売上の判定や消費税区分の判定は行わない):
    入金  借方 普通預金 / 貸方 事業主借
    出金  借方 事業主借 / 貸方 普通預金
摘要には通帳に書かれている内容をそのまま入れる。
"""
from __future__ import annotations

import tempfile
import uuid
from datetime import date
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel, Field

from .. import docfiles, ocr
from ..db import db, get_db_path, now_iso, rows_to_dicts
from ..passbook import extract_account_info, parse_passbook_text

router = APIRouter(prefix="/api", tags=["passbooks"])

MAX_UPLOAD_BYTES = 60 * 1024 * 1024
XDW_COMMAND_KEY = "xdw_converter"


def get_setting(conn, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def images_dir() -> Path:
    d = get_db_path().parent / "passbook_images"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# 通帳マスタ
# ---------------------------------------------------------------------------

class PassbookIn(BaseModel):
    code: str = ""
    name: str = Field(min_length=1)
    bank_name: str = ""
    branch_name: str = ""
    account_type: str = "普通"
    account_number: str = ""
    account_id: int | None = None
    sub_account_id: int | None = None
    counter_account_id: int | None = None
    last_balance: int | None = None
    last_date: str | None = None
    sort_order: int | None = None
    active: bool = True


PASSBOOK_SELECT = """
SELECT p.*, a.code AS account_code, a.name AS account_name,
       s.name AS sub_account_name, c.code AS counter_code, c.name AS counter_name
FROM passbooks p
LEFT JOIN accounts a ON a.id = p.account_id
LEFT JOIN sub_accounts s ON s.id = p.sub_account_id
LEFT JOIN accounts c ON c.id = p.counter_account_id
"""


def _default_accounts(conn, client_id: int) -> tuple[int | None, int | None]:
    """普通預金 (資産・名前に「普通預金」を含む) と 事業主借 の科目を推測する。"""
    bank = conn.execute(
        "SELECT id FROM accounts WHERE client_id=? AND active=1 AND category='asset' "
        "AND (name LIKE '%普通預金%' OR name LIKE '%普通%預金%') ORDER BY sort_order LIMIT 1",
        (client_id,)).fetchone()
    counter = conn.execute(
        "SELECT id FROM accounts WHERE client_id=? AND active=1 AND role='owner_contrib' LIMIT 1",
        (client_id,)).fetchone()
    if counter is None:
        counter = conn.execute(
            "SELECT id FROM accounts WHERE client_id=? AND active=1 AND name LIKE '%事業主借%' LIMIT 1",
            (client_id,)).fetchone()
    return (bank["id"] if bank else None, counter["id"] if counter else None)


def _validate_passbook(conn, client_id: int, p: PassbookIn) -> None:
    for label, aid in (("預金科目", p.account_id), ("相手科目", p.counter_account_id)):
        if aid is not None and not conn.execute(
                "SELECT 1 FROM accounts WHERE id=? AND client_id=?", (aid, client_id)).fetchone():
            raise HTTPException(400, f"{label}が不正です")
    if p.sub_account_id is not None:
        ok = conn.execute("SELECT 1 FROM sub_accounts WHERE id=? AND account_id=?",
                          (p.sub_account_id, p.account_id)).fetchone()
        if not ok:
            raise HTTPException(400, "補助科目が預金科目と一致しません")


@router.get("/clients/{client_id}/passbooks")
def list_passbooks(client_id: int):
    with db() as conn:
        rows = conn.execute(PASSBOOK_SELECT + " WHERE p.client_id=? ORDER BY p.sort_order, p.name",
                            (client_id,)).fetchall()
        return rows_to_dicts(rows)


@router.get("/clients/{client_id}/passbooks/defaults")
def passbook_defaults(client_id: int):
    """新規登録時に既定で選ぶ科目。"""
    with db() as conn:
        bank, counter = _default_accounts(conn, client_id)
        return {"account_id": bank, "counter_account_id": counter}


@router.post("/clients/{client_id}/passbooks", status_code=201)
def create_passbook(client_id: int, p: PassbookIn):
    with db() as conn:
        if not conn.execute("SELECT 1 FROM clients WHERE id=?", (client_id,)).fetchone():
            raise HTTPException(404, "顧問先が見つかりません")
        if conn.execute("SELECT 1 FROM passbooks WHERE client_id=? AND name=?",
                        (client_id, p.name.strip())).fetchone():
            raise HTTPException(409, f"同じ名前の通帳「{p.name.strip()}」が既に登録されています")
        _validate_passbook(conn, client_id, p)
        bank, counter = _default_accounts(conn, client_id)
        order = p.sort_order
        if order is None:
            r = conn.execute("SELECT MAX(sort_order) FROM passbooks WHERE client_id=?", (client_id,)).fetchone()
            order = (r[0] or 0) + 10
        cur = conn.execute(
            "INSERT INTO passbooks(client_id,code,name,bank_name,branch_name,account_type,account_number,"
            "account_id,sub_account_id,counter_account_id,last_balance,last_date,sort_order,active) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (client_id, p.code.strip(), p.name.strip(), p.bank_name.strip(), p.branch_name.strip(),
             p.account_type.strip(), p.account_number.strip(),
             p.account_id if p.account_id is not None else bank, p.sub_account_id,
             p.counter_account_id if p.counter_account_id is not None else counter,
             p.last_balance, p.last_date, order, int(p.active)))
        return dict(conn.execute(PASSBOOK_SELECT + " WHERE p.id=?", (cur.lastrowid,)).fetchone())


@router.put("/passbooks/{pid}")
def update_passbook(pid: int, p: PassbookIn):
    with db() as conn:
        row = conn.execute("SELECT * FROM passbooks WHERE id=?", (pid,)).fetchone()
        if not row:
            raise HTTPException(404, "通帳が見つかりません")
        dup = conn.execute("SELECT 1 FROM passbooks WHERE client_id=? AND name=? AND id<>?",
                           (row["client_id"], p.name.strip(), pid)).fetchone()
        if dup:
            raise HTTPException(409, f"同じ名前の通帳「{p.name.strip()}」が既に登録されています")
        _validate_passbook(conn, row["client_id"], p)
        conn.execute(
            "UPDATE passbooks SET code=?,name=?,bank_name=?,branch_name=?,account_type=?,account_number=?,"
            "account_id=?,sub_account_id=?,counter_account_id=?,last_balance=?,last_date=?,sort_order=?,active=? "
            "WHERE id=?",
            (p.code.strip(), p.name.strip(), p.bank_name.strip(), p.branch_name.strip(),
             p.account_type.strip(), p.account_number.strip(), p.account_id, p.sub_account_id,
             p.counter_account_id, p.last_balance, p.last_date,
             p.sort_order if p.sort_order is not None else row["sort_order"], int(p.active), pid))
        return dict(conn.execute(PASSBOOK_SELECT + " WHERE p.id=?", (pid,)).fetchone())


@router.delete("/passbooks/{pid}", status_code=204)
def delete_passbook(pid: int):
    """通帳を消しても、その通帳から起こした仕訳は残る。"""
    with db() as conn:
        conn.execute("UPDATE journal_entries SET passbook_id=NULL WHERE passbook_id=?", (pid,))
        conn.execute("UPDATE passbook_imports SET passbook_id=NULL WHERE passbook_id=?", (pid,))
        conn.execute("DELETE FROM passbooks WHERE id=?", (pid,))


# ---------------------------------------------------------------------------
# 読み取り
# ---------------------------------------------------------------------------

@router.get("/ocr/engines")
def ocr_engines():
    return {"engines": ocr.available_engines(), "default": ocr.default_engine()}


def _match_passbook(conn, client_id: int, info: dict) -> int | None:
    """読み取った口座情報から通帳マスタを探す。口座番号での一致を最優先する。"""
    number = (info.get("account_number") or "").strip()
    if number:
        row = conn.execute(
            "SELECT id FROM passbooks WHERE client_id=? AND account_number<>'' AND account_number=?",
            (client_id, number)).fetchone()
        if row:
            return row["id"]
    bank = (info.get("bank_name") or "").strip()
    if bank:
        row = conn.execute(
            "SELECT id FROM passbooks WHERE client_id=? AND bank_name<>'' AND bank_name=? LIMIT 2",
            (client_id, bank)).fetchall()
        if len(row) == 1:
            return row[0]["id"]
    return None


def _year_hint(conn, client_id: int, fiscal_year_id: int | None) -> int:
    if fiscal_year_id:
        fy = conn.execute("SELECT start_date FROM fiscal_years WHERE id=?", (fiscal_year_id,)).fetchone()
        if fy:
            return int(fy["start_date"][:4])
    return date.today().year


def _analyze(conn, client_id: int, text: str, fiscal_year_id: int | None,
             passbook_id: int | None, opening_balance: int | None) -> dict:
    info = extract_account_info(text)
    matched = passbook_id or _match_passbook(conn, client_id, info)
    pb = None
    if matched:
        pb = conn.execute(PASSBOOK_SELECT + " WHERE p.id=? AND p.client_id=?",
                          (matched, client_id)).fetchone()
        pb = dict(pb) if pb else None
    if opening_balance is None and pb:
        opening_balance = pb["last_balance"]
    parsed = parse_passbook_text(text, _year_hint(conn, client_id, fiscal_year_id), opening_balance)
    parsed["passbook"] = pb
    parsed["matched_by"] = ("指定" if passbook_id else
                            ("口座番号" if pb and info.get("account_number") == pb["account_number"] and pb["account_number"]
                             else ("銀行名" if pb else None)))
    parsed["opening_balance"] = opening_balance
    parsed["raw_text"] = text
    return parsed


class AnalyzeTextIn(BaseModel):
    text: str
    fiscal_year_id: int | None = None
    passbook_id: int | None = None
    opening_balance: int | None = None


@router.post("/clients/{client_id}/passbook/analyze-text")
def analyze_text(client_id: int, body: AnalyzeTextIn):
    """通帳のテキストを解析して、仕訳の下書きを返す (登録はしない)。"""
    with db() as conn:
        if not conn.execute("SELECT 1 FROM clients WHERE id=?", (client_id,)).fetchone():
            raise HTTPException(404, "顧問先が見つかりません")
        return _analyze(conn, client_id, body.text, body.fiscal_year_id,
                        body.passbook_id, body.opening_balance)


class SettingsIn(BaseModel):
    xdw_converter: str = ""


@router.get("/settings")
def read_settings():
    with db() as conn:
        return {"xdw_converter": get_setting(conn, XDW_COMMAND_KEY)}


@router.put("/settings")
def write_settings(body: SettingsIn):
    """DocuWorks の変換コマンドなど、パソコンごとの設定。"""
    cmd = body.xdw_converter.strip()
    if cmd and "{input}" not in cmd:
        raise HTTPException(400, "変換コマンドには、取り込むファイルの場所を表す {input} を入れてください")
    with db() as conn:
        conn.execute("INSERT INTO settings(key,value) VALUES(?,?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (XDW_COMMAND_KEY, cmd))
        return {"xdw_converter": cmd}


@router.get("/passbook/formats")
def passbook_formats():
    """取り込めるファイル形式と、この環境で使える読み取り方法。"""
    info = docfiles.supported_note()
    with db() as conn:
        info["xdw_command"] = get_setting(conn, XDW_COMMAND_KEY)
    info["ocr"] = ocr.available_engines()
    info["accept"] = sorted(docfiles.SUPPORTED_SUFFIXES)
    return info


@router.post("/clients/{client_id}/passbook/analyze-file")
async def analyze_file(client_id: int, file: UploadFile, engine: str | None = None,
                       fiscal_year_id: int | None = None, passbook_id: int | None = None,
                       opening_balance: int | None = None):
    """通帳のファイル (画像 / PDF / DocuWorks) から仕訳の下書きを作る (登録はしない)。

    PDF に文字情報があればそれを使う (OCR より正確)。無ければページを画像にして
    OCR にかける。DocuWorks は変換コマンドか埋め込み画像の取り出しを試す。
    """
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in docfiles.SUPPORTED_SUFFIXES:
        raise HTTPException(400, f"対応していない形式です ({suffix or '拡張子なし'})。"
                                 f"対応: {', '.join(sorted(docfiles.SUPPORTED_SUFFIXES))}")
    data = await file.read()
    if not data:
        raise HTTPException(400, "ファイルが空です")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, f"ファイルが大きすぎます ({len(data) // 1024 // 1024} MB)。"
                                 f"{MAX_UPLOAD_BYTES // 1024 // 1024} MB 以下にしてください")

    saved = images_dir() / f"{date.today():%Y%m%d}_{uuid.uuid4().hex[:12]}{suffix}"
    saved.write_bytes(data)

    with db() as conn:
        if not conn.execute("SELECT 1 FROM clients WHERE id=?", (client_id,)).fetchone():
            saved.unlink(missing_ok=True)
            raise HTTPException(404, "顧問先が見つかりません")
        xdw_cmd = get_setting(conn, XDW_COMMAND_KEY)

    used_engine = ""
    with tempfile.TemporaryDirectory() as tmp:
        try:
            doc = docfiles.load(saved, Path(tmp), xdw_cmd)
        except docfiles.DocumentError as e:
            saved.unlink(missing_ok=True)
            raise HTTPException(400, str(e))

        if doc.text is not None:
            text = doc.text
        else:
            if not ocr.available_engines():
                saved.unlink(missing_ok=True)
                raise HTTPException(400,
                    "この環境では画像から文字を読み取れません。"
                    "文字情報付きの PDF を取り込むか、通帳のテキストを貼り付けて取り込んでください。")
            parts = []
            for img in doc.images:
                try:
                    parts.append(ocr.run_ocr(img, engine))
                except ocr.OcrError as e:
                    saved.unlink(missing_ok=True)
                    raise HTTPException(400, str(e))
            text = "\n".join(parts)
            used_engine = engine or ocr.default_engine() or ""

    with db() as conn:
        result = _analyze(conn, client_id, text, fiscal_year_id, passbook_id, opening_balance)
    result["image_path"] = saved.name
    result["ocr_engine"] = used_engine
    result["method"] = doc.method
    result["method_note"] = doc.note
    result["pages"] = len(doc.images) or 1
    return result


# ---------------------------------------------------------------------------
# 仕訳の登録
# ---------------------------------------------------------------------------

class PassbookEntryIn(BaseModel):
    entry_date: str
    description: str = ""
    amount: int = Field(gt=0)
    direction: str            # 'in' 入金 / 'out' 出金


class RegisterIn(BaseModel):
    passbook_id: int
    rows: list[PassbookEntryIn]
    image_path: str = ""
    ocr_engine: str = ""
    raw_text: str = ""
    source: str = "image"
    last_balance: int | None = None      # 取込後の残高 (次回の判定に使う)
    skip_duplicates: bool = True


@router.post("/clients/{client_id}/passbook/register")
def register_entries(client_id: int, body: RegisterIn):
    """確認済みの行から仕訳を作る。

    入金  借方 普通預金 / 貸方 相手科目
    出金  借方 相手科目 / 貸方 普通預金
    消費税区分は「対象外」固定。
    """
    from .journals import EntryIn, LineIn, _validate_entry, _insert_lines, _next_voucher_no

    with db() as conn:
        pb = conn.execute("SELECT * FROM passbooks WHERE id=? AND client_id=?",
                          (body.passbook_id, client_id)).fetchone()
        if not pb:
            raise HTTPException(404, "通帳が見つかりません")
        if not pb["account_id"] or not pb["counter_account_id"]:
            raise HTTPException(400, "通帳に預金科目と相手科目を設定してください")
        if not body.rows:
            raise HTTPException(400, "登録する行がありません")

        bank, counter, sub = pb["account_id"], pb["counter_account_id"], pb["sub_account_id"]
        created, skipped = [], []
        ts = now_iso()

        imp = conn.execute(
            "INSERT INTO passbook_imports(client_id,passbook_id,source,image_path,ocr_engine,raw_text,"
            "entry_count,created_at) VALUES(?,?,?,?,?,?,0,?)",
            (client_id, pb["id"], body.source, body.image_path, body.ocr_engine, body.raw_text, ts))
        import_id = imp.lastrowid

        next_no: dict[int, int] = {}
        for i, r in enumerate(body.rows, 1):
            if r.direction not in ("in", "out"):
                raise HTTPException(400, f"{i} 行目: 入金か出金かを指定してください")
            desc = r.description.strip()
            if body.skip_duplicates and _is_duplicate(conn, client_id, pb["id"], r.entry_date, r.amount, desc):
                skipped.append({"row": i, "date": r.entry_date, "amount": r.amount, "description": desc})
                continue
            if r.direction == "in":
                line = LineIn(debit_account_id=bank, debit_sub_id=sub, credit_account_id=counter,
                              amount=r.amount, tax_class="00", description=desc)
            else:
                line = LineIn(debit_account_id=counter, credit_account_id=bank, credit_sub_id=sub,
                              amount=r.amount, tax_class="00", description=desc)
            e = EntryIn(entry_date=r.entry_date, memo=pb["name"], lines=[line])
            v = _validate_entry(conn, client_id, e)
            fy_id = v["fy"]["id"]
            if fy_id not in next_no:
                next_no[fy_id] = _next_voucher_no(conn, fy_id)
            cur = conn.execute(
                "INSERT INTO journal_entries(client_id,fiscal_year_id,entry_date,voucher_no,memo,"
                "created_at,updated_at,passbook_id,passbook_import_id) VALUES(?,?,?,?,?,?,?,?,?)",
                (client_id, fy_id, r.entry_date, next_no[fy_id], pb["name"], ts, ts, pb["id"], import_id))
            next_no[fy_id] += 1
            _insert_lines(conn, cur.lastrowid, v["lines"])
            created.append(cur.lastrowid)

        conn.execute("UPDATE passbook_imports SET entry_count=? WHERE id=?", (len(created), import_id))
        last_balance = body.last_balance
        last_date = max((r.entry_date for r in body.rows), default=None)
        conn.execute("UPDATE passbooks SET last_balance=COALESCE(?, last_balance), "
                     "last_date=COALESCE(?, last_date) WHERE id=?",
                     (last_balance, last_date, pb["id"]))
        return {"created": len(created), "entry_ids": created,
                "skipped": len(skipped), "skipped_rows": skipped, "import_id": import_id}


def _is_duplicate(conn, client_id: int, passbook_id: int, entry_date: str, amount: int, desc: str) -> bool:
    """同じ通帳・同じ日付・同じ金額・同じ摘要の仕訳が既にあるか。"""
    row = conn.execute(
        "SELECT 1 FROM journal_entries e JOIN journal_lines l ON l.entry_id=e.id "
        "WHERE e.client_id=? AND e.passbook_id=? AND e.entry_date=? AND l.amount=? AND l.description=? LIMIT 1",
        (client_id, passbook_id, entry_date, amount, desc)).fetchone()
    return row is not None


@router.get("/clients/{client_id}/passbook/imports")
def list_imports(client_id: int, limit: int = 50):
    with db() as conn:
        rows = conn.execute(
            "SELECT i.id, i.passbook_id, i.source, i.image_path, i.ocr_engine, i.entry_count, i.created_at, "
            "p.name AS passbook_name FROM passbook_imports i LEFT JOIN passbooks p ON p.id=i.passbook_id "
            "WHERE i.client_id=? ORDER BY i.created_at DESC, i.id DESC LIMIT ?", (client_id, limit)).fetchall()
        return rows_to_dicts(rows)


@router.delete("/passbook/imports/{import_id}", status_code=204)
def delete_import(import_id: int, with_entries: bool = False):
    """取込履歴を消す。with_entries=true ならその取込で作った仕訳もまとめて消す。"""
    with db() as conn:
        row = conn.execute("SELECT * FROM passbook_imports WHERE id=?", (import_id,)).fetchone()
        if not row:
            raise HTTPException(404, "取込履歴が見つかりません")
        if with_entries:
            closed = conn.execute(
                "SELECT 1 FROM journal_entries e JOIN fiscal_years f ON f.id=e.fiscal_year_id "
                "WHERE e.passbook_import_id=? AND f.closed=1 LIMIT 1", (import_id,)).fetchone()
            if closed:
                raise HTTPException(409, "締め切られた会計期間の仕訳が含まれるため削除できません")
            conn.execute("DELETE FROM journal_entries WHERE passbook_import_id=?", (import_id,))
        else:
            # 履歴だけ消す場合も紐付けは外す。行 ID は再利用されるため、
            # 残したままだと後の取込を消したときに巻き添えで消えてしまう。
            conn.execute("UPDATE journal_entries SET passbook_import_id=NULL WHERE passbook_import_id=?",
                         (import_id,))
        if row["image_path"]:
            (images_dir() / row["image_path"]).unlink(missing_ok=True)
        conn.execute("DELETE FROM passbook_imports WHERE id=?", (import_id,))
