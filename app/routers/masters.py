"""勘定科目・補助科目・部門・定型仕訳・期首残高 API。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..db import db, rows_to_dicts
from ..master_data import (
    CHART_CODES, CHARTS, GROUPS, GROUP_MAP, PROVISIONAL_PREFIX, ROLE_CODES, ROLES,
    TAX_CLASSES, TAX_CLASS_MAP, TKC_TAX_DIVISIONS, chart_accounts,
)

router = APIRouter(prefix="/api", tags=["masters"])


@router.get("/meta")
def meta():
    return {
        "tax_classes": TAX_CLASSES,
        "groups": GROUPS,
        "roles": ROLES,
        "charts": CHARTS,
        "tkc_tax_divisions": TKC_TAX_DIVISIONS,
        "provisional_prefix": PROVISIONAL_PREFIX,
        "entity_types": [{"code": "corp", "name": "法人"}, {"code": "sole", "name": "個人"}],
        "tax_methods": [
            {"code": "inclusive", "name": "税込経理"},
            {"code": "exclusive", "name": "税抜経理"},
            {"code": "exempt", "name": "免税事業者"},
        ],
    }


# ---------------------------------------------------------------------------
# 勘定科目
# ---------------------------------------------------------------------------

class AccountIn(BaseModel):
    code: str = Field(min_length=1, max_length=10)
    name: str = Field(min_length=1)
    kana: str = ""
    grp: str
    default_tax_class: str = "00"
    role: str = ""
    sort_order: int | None = None
    active: bool = True


@router.get("/clients/{client_id}/accounts")
def list_accounts(client_id: int, include_inactive: bool = True):
    with db() as conn:
        sql = ("SELECT a.*, (SELECT COUNT(*) FROM sub_accounts s WHERE s.account_id=a.id AND s.active=1) AS sub_count "
               "FROM accounts a WHERE client_id=?")
        if not include_inactive:
            sql += " AND active=1"
        rows = conn.execute(sql + " ORDER BY sort_order, code", (client_id,)).fetchall()
        return rows_to_dicts(rows)


@router.get("/clients/{client_id}/sub-accounts")
def list_all_sub_accounts(client_id: int):
    with db() as conn:
        rows = conn.execute(
            "SELECT s.* FROM sub_accounts s JOIN accounts a ON a.id=s.account_id WHERE a.client_id=? ORDER BY s.account_id, s.code",
            (client_id,)).fetchall()
        return rows_to_dicts(rows)


def _validate_account(a: AccountIn) -> None:
    if a.grp not in GROUP_MAP:
        raise HTTPException(400, "表示区分が不正です")
    if a.default_tax_class not in TAX_CLASS_MAP:
        raise HTTPException(400, "消費税区分が不正です")
    if a.role not in ROLE_CODES:
        raise HTTPException(400, "科目の役割が不正です")


@router.post("/clients/{client_id}/accounts", status_code=201)
def create_account(client_id: int, a: AccountIn):
    _validate_account(a)
    with db() as conn:
        if conn.execute("SELECT 1 FROM accounts WHERE client_id=? AND code=?", (client_id, a.code)).fetchone():
            raise HTTPException(409, "同じコードの科目が既に存在します")
        sort_order = a.sort_order
        if sort_order is None:
            # 同じ表示区分の末尾に置く
            r = conn.execute("SELECT MAX(sort_order) FROM accounts WHERE client_id=? AND grp=?", (client_id, a.grp)).fetchone()
            sort_order = (r[0] or 0) + 1
        cur = conn.execute(
            "INSERT INTO accounts(client_id,code,name,kana,category,grp,default_tax_class,role,sort_order,active) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (client_id, a.code, a.name, a.kana, GROUP_MAP[a.grp], a.grp, a.default_tax_class, a.role, sort_order, int(a.active)),
        )
        return dict(conn.execute("SELECT * FROM accounts WHERE id=?", (cur.lastrowid,)).fetchone())


@router.put("/accounts/{account_id}")
def update_account(account_id: int, a: AccountIn):
    _validate_account(a)
    with db() as conn:
        row = conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        if not row:
            raise HTTPException(404, "科目が見つかりません")
        dup = conn.execute("SELECT 1 FROM accounts WHERE client_id=? AND code=? AND id<>?",
                           (row["client_id"], a.code, account_id)).fetchone()
        if dup:
            raise HTTPException(409, "同じコードの科目が既に存在します")
        conn.execute(
            "UPDATE accounts SET code=?,name=?,kana=?,category=?,grp=?,default_tax_class=?,role=?,sort_order=?,active=? WHERE id=?",
            (a.code, a.name, a.kana, GROUP_MAP[a.grp], a.grp, a.default_tax_class, a.role,
             a.sort_order if a.sort_order is not None else row["sort_order"], int(a.active), account_id),
        )
        return dict(conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone())


@router.delete("/accounts/{account_id}", status_code=204)
def delete_account(account_id: int):
    with db() as conn:
        used = conn.execute(
            "SELECT COUNT(*) FROM journal_lines WHERE debit_account_id=? OR credit_account_id=?",
            (account_id, account_id)).fetchone()[0]
        if used:
            raise HTTPException(409, f"仕訳で {used} 件使用されているため削除できません (無効化してください)")
        conn.execute("DELETE FROM opening_balances WHERE account_id=?", (account_id,))
        conn.execute("DELETE FROM accounts WHERE id=?", (account_id,))


class AccountEdit(AccountIn):
    """id を持つ場合は更新、持たない場合は新規追加。"""
    id: int | None = None


class AccountsBulkIn(BaseModel):
    items: list[AccountEdit]
    delete_ids: list[int] = []


@router.put("/clients/{client_id}/accounts/bulk")
def save_accounts_bulk(client_id: int, body: AccountsBulkIn):
    """勘定科目の一括保存。コード・名称の変更、追加、削除をまとめて反映する。

    仕訳や期首残高は科目 ID で結び付いているため、コードや名称を変更しても
    過去の入力内容には影響しない。
    """
    with db() as conn:
        if not conn.execute("SELECT 1 FROM clients WHERE id=?", (client_id,)).fetchone():
            raise HTTPException(404, "顧問先が見つかりません")
        existing = {r["id"]: dict(r) for r in conn.execute(
            "SELECT * FROM accounts WHERE client_id=?", (client_id,)).fetchall()}

        # コード重複の事前チェック (削除対象を除く)
        seen: dict[str, int] = {}
        for i, a in enumerate(body.items, 1):
            _validate_account(a)
            code = a.code.strip()
            if code in seen:
                raise HTTPException(409, f"コード {code} が {seen[code]} 行目と {i} 行目で重複しています")
            seen[code] = i
            if a.id is not None and a.id not in existing:
                raise HTTPException(400, f"{i} 行目: 存在しない科目です")

        deleted = 0
        for aid in body.delete_ids:
            if aid not in existing:
                continue
            used = conn.execute(
                "SELECT COUNT(*) FROM journal_lines WHERE debit_account_id=? OR credit_account_id=?",
                (aid, aid)).fetchone()[0]
            if used:
                raise HTTPException(409, f"{existing[aid]['code']} {existing[aid]['name']} は仕訳で {used} 件使用されているため削除できません")
            conn.execute("DELETE FROM opening_balances WHERE account_id=?", (aid,))
            conn.execute("DELETE FROM accounts WHERE id=?", (aid,))
            deleted += 1

        created = updated = 0
        for order, a in enumerate(body.items):
            sort_order = a.sort_order if a.sort_order is not None else order * 10
            values = (a.code.strip(), a.name.strip(), a.kana.strip(), GROUP_MAP[a.grp], a.grp,
                      a.default_tax_class, a.role, sort_order, int(a.active))
            if a.id is None:
                conn.execute(
                    "INSERT INTO accounts(code,name,kana,category,grp,default_tax_class,role,sort_order,active,client_id) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?)", values + (client_id,))
                created += 1
            else:
                conn.execute(
                    "UPDATE accounts SET code=?,name=?,kana=?,category=?,grp=?,default_tax_class=?,role=?,sort_order=?,active=? "
                    "WHERE id=? AND client_id=?", values + (a.id, client_id))
                updated += 1
        return {"created": created, "updated": updated, "deleted": deleted}


# ---------------------------------------------------------------------------
# 補助科目
# ---------------------------------------------------------------------------

def _apply_account_rows(conn, client_id: int, rows: list[dict], mode: str) -> dict:
    """科目リストを顧問先に反映する。copy-from と apply-chart の共通処理。

    コードが一致する既存科目は上書きし、無いものは追加する。mode="replace" の
    場合、リストに無い既存科目は削除 (仕訳で使用中なら無効化) する。
    戻り値の id_map は 元の科目コード -> 反映後の科目 ID。
    """
    dst = {r["code"]: dict(r) for r in conn.execute(
        "SELECT * FROM accounts WHERE client_id=?", (client_id,)).fetchall()}
    codes = {a["code"] for a in rows}
    created = updated = deleted = deactivated = 0
    id_map: dict[str, int] = {}
    for a in rows:
        cur = dst.get(a["code"])
        values = (a["name"], a["kana"], a["category"], a["grp"], a["default_tax_class"],
                  a["role"], a["sort_order"], int(a.get("active", 1)))
        if cur:
            conn.execute(
                "UPDATE accounts SET name=?,kana=?,category=?,grp=?,default_tax_class=?,role=?,sort_order=?,active=? WHERE id=?",
                values + (cur["id"],))
            id_map[a["code"]] = cur["id"]
            updated += 1
        else:
            c = conn.execute(
                "INSERT INTO accounts(name,kana,category,grp,default_tax_class,role,sort_order,active,client_id,code) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)", values + (client_id, a["code"]))
            id_map[a["code"]] = c.lastrowid
            created += 1

    left_over = []
    if mode == "replace":
        for code, a in dst.items():
            if code in codes:
                continue
            used = conn.execute(
                "SELECT COUNT(*) FROM journal_lines WHERE debit_account_id=? OR credit_account_id=?",
                (a["id"], a["id"])).fetchone()[0]
            if used:
                conn.execute("UPDATE accounts SET active=0 WHERE id=?", (a["id"],))
                deactivated += 1
                left_over.append(f'{a["code"]} {a["name"]}')
            else:
                conn.execute("DELETE FROM opening_balances WHERE account_id=?", (a["id"],))
                conn.execute("DELETE FROM accounts WHERE id=?", (a["id"],))
                deleted += 1
    return {"created": created, "updated": updated, "deleted": deleted,
            "deactivated": deactivated, "deactivated_names": left_over[:20], "id_map": id_map}


@router.post("/clients/{client_id}/accounts/apply-chart")
def apply_chart(client_id: int, chart: str = "tkc", mode: str = "merge"):
    """既存の顧問先に、用意された科目表 (TKC / 汎用) を後から適用する。

    顧問先を作り直さずに科目体系を切り替えるための機能。仕訳は科目 ID で
    結び付いているため、コードが一致する科目は ID を保ったまま名称等だけ
    更新され、過去の入力は失われない。
    """
    if chart not in CHART_CODES or chart == "none":
        raise HTTPException(400, "科目表の指定が不正です")
    if mode not in ("merge", "replace"):
        raise HTTPException(400, "mode は merge / replace のいずれか")
    with db() as conn:
        client = conn.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()
        if not client:
            raise HTTPException(404, "顧問先が見つかりません")
        rows = chart_accounts(chart, client["entity_type"])
        result = _apply_account_rows(conn, client_id, rows, mode)
        result.pop("id_map")
        result["chart"] = chart
        return result


@router.post("/clients/{client_id}/accounts/copy-from/{source_id}")
def copy_accounts_from(client_id: int, source_id: int, mode: str = "merge", with_subs: bool = False):
    """他の顧問先の科目表を複写する。事務所共通の科目表を使い回すための機能。

    mode="merge"   : コードが一致する科目は上書きし、無いものは追加する。
    mode="replace" : 上記に加え、複写元に無い科目を削除 (仕訳で使用中なら無効化) する。
    """
    if mode not in ("merge", "replace"):
        raise HTTPException(400, "mode は merge / replace のいずれか")
    if client_id == source_id:
        raise HTTPException(400, "複写元と複写先が同じです")
    with db() as conn:
        for cid in (client_id, source_id):
            if not conn.execute("SELECT 1 FROM clients WHERE id=?", (cid,)).fetchone():
                raise HTTPException(404, "顧問先が見つかりません")
        src = [dict(r) for r in conn.execute(
            "SELECT * FROM accounts WHERE client_id=? ORDER BY sort_order, code", (source_id,)).fetchall()]
        if not src:
            raise HTTPException(400, "複写元に勘定科目がありません")
        result = _apply_account_rows(conn, client_id, src, mode)
        id_map = result.pop("id_map")

        subs = 0
        if with_subs:
            for s in conn.execute(
                "SELECT s.*, a.code AS account_code FROM sub_accounts s JOIN accounts a ON a.id=s.account_id "
                "WHERE a.client_id=?", (source_id,)).fetchall():
                target = id_map.get(s["account_code"])
                if target is None:
                    continue
                if conn.execute("SELECT 1 FROM sub_accounts WHERE account_id=? AND code=?",
                                (target, s["code"])).fetchone():
                    continue
                conn.execute("INSERT INTO sub_accounts(account_id,code,name,kana,active) VALUES(?,?,?,?,?)",
                             (target, s["code"], s["name"], s["kana"], s["active"]))
                subs += 1
        result["sub_accounts"] = subs
        return result


class SubAccountIn(BaseModel):
    code: str = Field(min_length=1, max_length=10)
    name: str = Field(min_length=1)
    kana: str = ""
    active: bool = True


@router.get("/accounts/{account_id}/sub-accounts")
def list_sub_accounts(account_id: int):
    with db() as conn:
        rows = conn.execute("SELECT * FROM sub_accounts WHERE account_id=? ORDER BY code", (account_id,)).fetchall()
        return rows_to_dicts(rows)


@router.post("/accounts/{account_id}/sub-accounts", status_code=201)
def create_sub_account(account_id: int, s: SubAccountIn):
    with db() as conn:
        if not conn.execute("SELECT 1 FROM accounts WHERE id=?", (account_id,)).fetchone():
            raise HTTPException(404, "科目が見つかりません")
        if conn.execute("SELECT 1 FROM sub_accounts WHERE account_id=? AND code=?", (account_id, s.code)).fetchone():
            raise HTTPException(409, "同じコードの補助科目が既に存在します")
        cur = conn.execute("INSERT INTO sub_accounts(account_id,code,name,kana,active) VALUES(?,?,?,?,?)",
                           (account_id, s.code, s.name, s.kana, int(s.active)))
        return dict(conn.execute("SELECT * FROM sub_accounts WHERE id=?", (cur.lastrowid,)).fetchone())


@router.put("/sub-accounts/{sub_id}")
def update_sub_account(sub_id: int, s: SubAccountIn):
    with db() as conn:
        row = conn.execute("SELECT * FROM sub_accounts WHERE id=?", (sub_id,)).fetchone()
        if not row:
            raise HTTPException(404, "補助科目が見つかりません")
        dup = conn.execute("SELECT 1 FROM sub_accounts WHERE account_id=? AND code=? AND id<>?",
                           (row["account_id"], s.code, sub_id)).fetchone()
        if dup:
            raise HTTPException(409, "同じコードの補助科目が既に存在します")
        conn.execute("UPDATE sub_accounts SET code=?,name=?,kana=?,active=? WHERE id=?",
                     (s.code, s.name, s.kana, int(s.active), sub_id))
        return dict(conn.execute("SELECT * FROM sub_accounts WHERE id=?", (sub_id,)).fetchone())


@router.delete("/sub-accounts/{sub_id}", status_code=204)
def delete_sub_account(sub_id: int):
    with db() as conn:
        used = conn.execute("SELECT COUNT(*) FROM journal_lines WHERE debit_sub_id=? OR credit_sub_id=?",
                            (sub_id, sub_id)).fetchone()[0]
        if used:
            raise HTTPException(409, f"仕訳で {used} 件使用されているため削除できません")
        conn.execute("DELETE FROM opening_balances WHERE sub_account_id=?", (sub_id,))
        conn.execute("DELETE FROM sub_accounts WHERE id=?", (sub_id,))


# ---------------------------------------------------------------------------
# 部門
# ---------------------------------------------------------------------------

class DepartmentIn(BaseModel):
    code: str = Field(min_length=1, max_length=10)
    name: str = Field(min_length=1)
    active: bool = True


@router.get("/clients/{client_id}/departments")
def list_departments(client_id: int):
    with db() as conn:
        return rows_to_dicts(conn.execute("SELECT * FROM departments WHERE client_id=? ORDER BY code", (client_id,)).fetchall())


@router.post("/clients/{client_id}/departments", status_code=201)
def create_department(client_id: int, d: DepartmentIn):
    with db() as conn:
        if conn.execute("SELECT 1 FROM departments WHERE client_id=? AND code=?", (client_id, d.code)).fetchone():
            raise HTTPException(409, "同じコードの部門が既に存在します")
        cur = conn.execute("INSERT INTO departments(client_id,code,name,active) VALUES(?,?,?,?)",
                           (client_id, d.code, d.name, int(d.active)))
        return dict(conn.execute("SELECT * FROM departments WHERE id=?", (cur.lastrowid,)).fetchone())


@router.put("/departments/{dept_id}")
def update_department(dept_id: int, d: DepartmentIn):
    with db() as conn:
        row = conn.execute("SELECT * FROM departments WHERE id=?", (dept_id,)).fetchone()
        if not row:
            raise HTTPException(404, "部門が見つかりません")
        conn.execute("UPDATE departments SET code=?,name=?,active=? WHERE id=?", (d.code, d.name, int(d.active), dept_id))
        return dict(conn.execute("SELECT * FROM departments WHERE id=?", (dept_id,)).fetchone())


@router.delete("/departments/{dept_id}", status_code=204)
def delete_department(dept_id: int):
    with db() as conn:
        used = conn.execute("SELECT COUNT(*) FROM journal_lines WHERE debit_dept_id=? OR credit_dept_id=?",
                            (dept_id, dept_id)).fetchone()[0]
        if used:
            raise HTTPException(409, f"仕訳で {used} 件使用されているため削除できません")
        conn.execute("DELETE FROM departments WHERE id=?", (dept_id,))


# ---------------------------------------------------------------------------
# 摘要プリセット
#   よく使う摘要 (売上先・仕入先など) を登録しておき、仕訳入力で呼び出す。
# ---------------------------------------------------------------------------

class DescriptionIn(BaseModel):
    code: str = ""                       # 呼び出し用の短縮コード (任意)
    text: str = Field(min_length=1)
    kana: str = ""
    account_id: int | None = None        # 関連する科目 (任意)。入力時に優先表示する
    sort_order: int | None = None
    active: bool = True


class DescriptionEdit(DescriptionIn):
    id: int | None = None


class DescriptionsBulkIn(BaseModel):
    items: list[DescriptionEdit]
    delete_ids: list[int] = []


@router.get("/clients/{client_id}/descriptions")
def list_descriptions(client_id: int):
    with db() as conn:
        rows = conn.execute(
            "SELECT d.*, a.code AS account_code, a.name AS account_name FROM descriptions d "
            "LEFT JOIN accounts a ON a.id=d.account_id WHERE d.client_id=? ORDER BY d.sort_order, d.code, d.text",
            (client_id,)).fetchall()
        return rows_to_dicts(rows)


@router.get("/clients/{client_id}/description-suggestions")
def description_suggestions(client_id: int, limit: int = 300):
    """仕訳入力の摘要候補。プリセットを先に、過去に使った摘要を後に返す。"""
    with db() as conn:
        presets = conn.execute(
            "SELECT id, code, text, kana, account_id FROM descriptions "
            "WHERE client_id=? AND active=1 ORDER BY sort_order, code, text", (client_id,)).fetchall()
        seen = {r["text"] for r in presets}
        used = conn.execute(
            "SELECT l.description AS text, COUNT(*) AS n, MAX(e.entry_date) AS last_used "
            "FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id "
            "WHERE e.client_id=? AND l.description<>'' GROUP BY l.description "
            "ORDER BY n DESC, last_used DESC LIMIT ?", (client_id, limit)).fetchall()
        return {
            "presets": [dict(r) for r in presets],
            "history": [dict(r) for r in used if r["text"] not in seen],
        }


def _validate_description(conn, client_id: int, d: DescriptionIn, self_id: int | None = None) -> None:
    if d.account_id is not None:
        ok = conn.execute("SELECT 1 FROM accounts WHERE id=? AND client_id=?",
                          (d.account_id, client_id)).fetchone()
        if not ok:
            raise HTTPException(400, "関連科目が不正です")
    dup = conn.execute(
        "SELECT 1 FROM descriptions WHERE client_id=? AND text=? AND id IS NOT ?",
        (client_id, d.text.strip(), self_id)).fetchone()
    if dup:
        raise HTTPException(409, f"同じ摘要「{d.text.strip()}」が既に登録されています")


@router.post("/clients/{client_id}/descriptions", status_code=201)
def create_description(client_id: int, d: DescriptionIn):
    with db() as conn:
        if not conn.execute("SELECT 1 FROM clients WHERE id=?", (client_id,)).fetchone():
            raise HTTPException(404, "顧問先が見つかりません")
        _validate_description(conn, client_id, d)
        order = d.sort_order
        if order is None:
            r = conn.execute("SELECT MAX(sort_order) FROM descriptions WHERE client_id=?", (client_id,)).fetchone()
            order = (r[0] or 0) + 10
        cur = conn.execute(
            "INSERT INTO descriptions(client_id,code,text,kana,account_id,sort_order,active) VALUES(?,?,?,?,?,?,?)",
            (client_id, d.code.strip(), d.text.strip(), d.kana.strip(), d.account_id, order, int(d.active)))
        return dict(conn.execute("SELECT * FROM descriptions WHERE id=?", (cur.lastrowid,)).fetchone())


@router.put("/descriptions/{did}")
def update_description(did: int, d: DescriptionIn):
    with db() as conn:
        row = conn.execute("SELECT * FROM descriptions WHERE id=?", (did,)).fetchone()
        if not row:
            raise HTTPException(404, "摘要が見つかりません")
        _validate_description(conn, row["client_id"], d, did)
        conn.execute(
            "UPDATE descriptions SET code=?,text=?,kana=?,account_id=?,sort_order=?,active=? WHERE id=?",
            (d.code.strip(), d.text.strip(), d.kana.strip(), d.account_id,
             d.sort_order if d.sort_order is not None else row["sort_order"], int(d.active), did))
        return dict(conn.execute("SELECT * FROM descriptions WHERE id=?", (did,)).fetchone())


@router.delete("/descriptions/{did}", status_code=204)
def delete_description(did: int):
    """プリセットを消しても、既に入力済みの仕訳の摘要はそのまま残る。"""
    with db() as conn:
        conn.execute("DELETE FROM descriptions WHERE id=?", (did,))


@router.put("/clients/{client_id}/descriptions/bulk")
def save_descriptions_bulk(client_id: int, body: DescriptionsBulkIn):
    with db() as conn:
        if not conn.execute("SELECT 1 FROM clients WHERE id=?", (client_id,)).fetchone():
            raise HTTPException(404, "顧問先が見つかりません")
        seen: dict[str, int] = {}
        for i, d in enumerate(body.items, 1):
            text = d.text.strip()
            if not text:
                raise HTTPException(400, f"{i} 行目: 摘要は必須です")
            if text in seen:
                raise HTTPException(409, f"摘要「{text}」が {seen[text]} 行目と {i} 行目で重複しています")
            seen[text] = i
            if d.account_id is not None and not conn.execute(
                    "SELECT 1 FROM accounts WHERE id=? AND client_id=?", (d.account_id, client_id)).fetchone():
                raise HTTPException(400, f"{i} 行目: 関連科目が不正です")

        for did in body.delete_ids:
            conn.execute("DELETE FROM descriptions WHERE id=? AND client_id=?", (did, client_id))

        created = updated = 0
        for order, d in enumerate(body.items):
            values = (d.code.strip(), d.text.strip(), d.kana.strip(), d.account_id,
                      d.sort_order if d.sort_order is not None else order * 10, int(d.active))
            if d.id is None:
                conn.execute(
                    "INSERT INTO descriptions(code,text,kana,account_id,sort_order,active,client_id) "
                    "VALUES(?,?,?,?,?,?,?)", values + (client_id,))
                created += 1
            else:
                conn.execute(
                    "UPDATE descriptions SET code=?,text=?,kana=?,account_id=?,sort_order=?,active=? "
                    "WHERE id=? AND client_id=?", values + (d.id, client_id))
                updated += 1
        return {"created": created, "updated": updated, "deleted": len(body.delete_ids)}


@router.post("/clients/{client_id}/descriptions/from-history")
def descriptions_from_history(client_id: int, min_count: int = 2, limit: int = 200):
    """過去の仕訳でよく使った摘要を、まとめてプリセットに登録する。"""
    with db() as conn:
        if not conn.execute("SELECT 1 FROM clients WHERE id=?", (client_id,)).fetchone():
            raise HTTPException(404, "顧問先が見つかりません")
        existing = {r["text"] for r in conn.execute(
            "SELECT text FROM descriptions WHERE client_id=?", (client_id,)).fetchall()}
        rows = conn.execute(
            "SELECT l.description AS text, COUNT(*) AS n FROM journal_lines l "
            "JOIN journal_entries e ON e.id=l.entry_id WHERE e.client_id=? AND l.description<>'' "
            "GROUP BY l.description HAVING COUNT(*)>=? ORDER BY n DESC LIMIT ?",
            (client_id, min_count, limit)).fetchall()
        r = conn.execute("SELECT MAX(sort_order) FROM descriptions WHERE client_id=?", (client_id,)).fetchone()
        order = (r[0] or 0) + 10
        added = 0
        for row in rows:
            if row["text"] in existing:
                continue
            conn.execute("INSERT INTO descriptions(client_id,code,text,kana,sort_order,active) VALUES(?,?,?,?,?,1)",
                         (client_id, "", row["text"], "", order))
            order += 10
            added += 1
        return {"added": added, "candidates": len(rows)}


# ---------------------------------------------------------------------------
# 定型仕訳
# ---------------------------------------------------------------------------

class TemplateLineIn(BaseModel):
    debit_account_id: int | None = None
    debit_sub_id: int | None = None
    debit_dept_id: int | None = None
    credit_account_id: int | None = None
    credit_sub_id: int | None = None
    credit_dept_id: int | None = None
    amount: int = 0
    tax_class: str = ""
    description: str = ""


class TemplateIn(BaseModel):
    code: str = Field(min_length=1, max_length=10)
    name: str = Field(min_length=1)
    memo: str = ""
    lines: list[TemplateLineIn] = []


def _template_rows(conn, client_id: int | None = None, tid: int | None = None) -> list[dict]:
    """定型仕訳を明細つきで返す。"""
    if tid is not None:
        heads = conn.execute("SELECT * FROM entry_templates WHERE id=?", (tid,)).fetchall()
    else:
        heads = conn.execute(
            "SELECT * FROM entry_templates WHERE client_id=? ORDER BY code", (client_id,)).fetchall()
    out = [dict(h) for h in heads]
    if not out:
        return out
    by_id = {t["id"]: t for t in out}
    for t in out:
        t["lines"] = []
    marks = ",".join("?" * len(by_id))
    for r in conn.execute(
            f"SELECT * FROM entry_template_lines WHERE template_id IN ({marks}) ORDER BY template_id, line_no",
            tuple(by_id)).fetchall():
        by_id[r["template_id"]]["lines"].append(dict(r))
    return out


def _save_template_lines(conn, tid: int, lines: list[TemplateLineIn]) -> None:
    conn.execute("DELETE FROM entry_template_lines WHERE template_id=?", (tid,))
    conn.executemany(
        "INSERT INTO entry_template_lines(template_id,line_no,debit_account_id,debit_sub_id,debit_dept_id,"
        "credit_account_id,credit_sub_id,credit_dept_id,amount,tax_class,description) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        [(tid, i, l.debit_account_id, l.debit_sub_id, l.debit_dept_id,
          l.credit_account_id, l.credit_sub_id, l.credit_dept_id, l.amount, l.tax_class, l.description.strip())
         for i, l in enumerate(lines, 1)])


@router.get("/clients/{client_id}/templates")
def list_templates(client_id: int):
    with db() as conn:
        return _template_rows(conn, client_id=client_id)


@router.post("/clients/{client_id}/templates", status_code=201)
def create_template(client_id: int, t: TemplateIn):
    with db() as conn:
        if conn.execute("SELECT 1 FROM entry_templates WHERE client_id=? AND code=?", (client_id, t.code)).fetchone():
            raise HTTPException(409, "同じコードの定型仕訳が既に存在します")
        cur = conn.execute("INSERT INTO entry_templates(client_id,code,name,memo) VALUES(?,?,?,?)",
                           (client_id, t.code, t.name, t.memo))
        _save_template_lines(conn, cur.lastrowid, t.lines)
        return _template_rows(conn, tid=cur.lastrowid)[0]


@router.put("/templates/{tid}")
def update_template(tid: int, t: TemplateIn):
    with db() as conn:
        row = conn.execute("SELECT * FROM entry_templates WHERE id=?", (tid,)).fetchone()
        if not row:
            raise HTTPException(404, "定型仕訳が見つかりません")
        dup = conn.execute("SELECT 1 FROM entry_templates WHERE client_id=? AND code=? AND id<>?",
                           (row["client_id"], t.code, tid)).fetchone()
        if dup:
            raise HTTPException(409, "同じコードの定型仕訳が既に存在します")
        conn.execute("UPDATE entry_templates SET code=?,name=?,memo=? WHERE id=?", (t.code, t.name, t.memo, tid))
        _save_template_lines(conn, tid, t.lines)
        return _template_rows(conn, tid=tid)[0]


@router.post("/clients/{client_id}/templates/from-entry/{entry_id}", status_code=201)
def create_template_from_entry(client_id: int, entry_id: int, code: str = "", name: str = ""):
    """登録済みの伝票を、そのまま定型仕訳にする。"""
    with db() as conn:
        e = conn.execute("SELECT * FROM journal_entries WHERE id=? AND client_id=?", (entry_id, client_id)).fetchone()
        if not e:
            raise HTTPException(404, "仕訳が見つかりません")
        lines = conn.execute("SELECT * FROM journal_lines WHERE entry_id=? ORDER BY line_no", (entry_id,)).fetchall()
        code = code.strip() or _next_template_code(conn, client_id)
        if conn.execute("SELECT 1 FROM entry_templates WHERE client_id=? AND code=?", (client_id, code)).fetchone():
            raise HTTPException(409, "同じコードの定型仕訳が既に存在します")
        if not name.strip():
            first = next((l["description"] for l in lines if l["description"]), "")
            name = first or f'{e["entry_date"]} の仕訳'
        cur = conn.execute("INSERT INTO entry_templates(client_id,code,name,memo) VALUES(?,?,?,?)",
                           (client_id, code, name.strip(), e["memo"]))
        _save_template_lines(conn, cur.lastrowid, [TemplateLineIn(
            debit_account_id=l["debit_account_id"], debit_sub_id=l["debit_sub_id"], debit_dept_id=l["debit_dept_id"],
            credit_account_id=l["credit_account_id"], credit_sub_id=l["credit_sub_id"], credit_dept_id=l["credit_dept_id"],
            amount=l["amount"], tax_class=l["tax_class"], description=l["description"]) for l in lines])
        return _template_rows(conn, tid=cur.lastrowid)[0]


def _next_template_code(conn, client_id: int) -> str:
    """空いている一番小さい番号をコードにする。"""
    used = {r["code"] for r in conn.execute(
        "SELECT code FROM entry_templates WHERE client_id=?", (client_id,)).fetchall()}
    n = 1
    while str(n) in used:
        n += 1
    return str(n)


@router.delete("/templates/{tid}", status_code=204)
def delete_template(tid: int):
    with db() as conn:
        conn.execute("DELETE FROM entry_templates WHERE id=?", (tid,))


# ---------------------------------------------------------------------------
# 期首残高
# ---------------------------------------------------------------------------

class OpeningBalanceItem(BaseModel):
    account_id: int
    sub_account_id: int = 0
    amount: int  # 借方残高を正、貸方残高を負


class OpeningBalancesIn(BaseModel):
    items: list[OpeningBalanceItem]


@router.get("/fiscal-years/{fy_id}/opening-balances")
def get_opening_balances(fy_id: int):
    with db() as conn:
        rows = conn.execute(
            "SELECT o.*, a.code AS account_code, a.name AS account_name, a.category, s.code AS sub_code, s.name AS sub_name "
            "FROM opening_balances o JOIN accounts a ON a.id=o.account_id "
            "LEFT JOIN sub_accounts s ON s.id=o.sub_account_id WHERE o.fiscal_year_id=? ORDER BY a.sort_order, a.code, s.code",
            (fy_id,)).fetchall()
        return rows_to_dicts(rows)


@router.put("/fiscal-years/{fy_id}/opening-balances")
def put_opening_balances(fy_id: int, body: OpeningBalancesIn):
    with db() as conn:
        if not conn.execute("SELECT 1 FROM fiscal_years WHERE id=?", (fy_id,)).fetchone():
            raise HTTPException(404, "会計期間が見つかりません")
        conn.execute("DELETE FROM opening_balances WHERE fiscal_year_id=?", (fy_id,))
        conn.executemany(
            "INSERT INTO opening_balances(fiscal_year_id,account_id,sub_account_id,amount) VALUES(?,?,?,?)",
            [(fy_id, i.account_id, i.sub_account_id or 0, i.amount) for i in body.items if i.amount != 0])
        total = sum(i.amount for i in body.items)
        return {"count": len([i for i in body.items if i.amount]), "difference": total}
