"""通帳マスタと通帳取込 API のテスト。"""
import io
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture()
def client(tmp_path):
    os.environ["KAIKEI_DB"] = str(tmp_path / "test.db")
    from app import db as dbmod
    dbmod.set_db_path(tmp_path / "test.db")
    from app.main import create_app
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture()
def sole(client):
    """個人事業者 (事業主借がある) を作る。"""
    r = client.post("/api/clients", json={"code": "001", "name": "山田太郎", "entity_type": "sole",
                                          "tax_method": "inclusive", "chart": "tkc"})
    assert r.status_code == 201, r.text
    cl = r.json()
    fy = client.get(f"/api/clients/{cl['id']}/fiscal-years").json()[0]
    acc = {a["code"]: a for a in client.get(f"/api/clients/{cl['id']}/accounts").json()}
    return cl, fy, acc


def make_passbook(client, cid, acc, **kw):
    body = {"name": "みずほ銀行 渋谷支店", "bank_name": "みずほ銀行", "branch_name": "渋谷支店",
            "account_type": "普通", "account_number": "1234567",
            "account_id": acc["1113"]["id"],
            "counter_account_id": next(a["id"] for a in acc.values() if a["role"] == "owner_contrib")}
    body.update(kw)
    r = client.post(f"/api/clients/{cid}/passbooks", json=body)
    assert r.status_code == 201, r.text
    return r.json()


SAMPLE = """みずほ銀行 渋谷支店 普通 1234567
年月日 お取引内容 お支払金額 お預り金額 差引残高
6-04-01 カ)ヤマダショウテン 330,000 1,530,000
6-04-05 ATM出金 50,000 1,480,000
6-04-10 デンキダイ 12,800 1,467,200
"""


# ---------------------------------------------------------------------------
# 通帳マスタ
# ---------------------------------------------------------------------------

def test_passbook_defaults_pick_bank_and_owner_account(client, sole):
    cl, fy, acc = sole
    d = client.get(f"/api/clients/{cl['id']}/passbooks/defaults").json()
    assert d["account_id"] == acc["1113"]["id"]                       # 普通預金
    assert acc_by_id(acc, d["counter_account_id"])["role"] == "owner_contrib"   # 事業主借


def acc_by_id(acc, aid):
    return next(a for a in acc.values() if a["id"] == aid)


def test_passbook_crud(client, sole):
    cl, fy, acc = sole
    cid = cl["id"]
    pb = make_passbook(client, cid, acc)
    assert pb["account_code"] == "1113"
    assert pb["counter_name"] == "事業主借"

    # 同じ名前は登録できない
    assert client.post(f"/api/clients/{cid}/passbooks", json={"name": pb["name"]}).status_code == 409
    # 2 冊目は登録できる
    pb2 = make_passbook(client, cid, acc, name="ゆうちょ銀行", bank_name="ゆうちょ銀行",
                        account_number="9998887")
    assert len({pb["id"], pb2["id"]}) == 2
    assert len(client.get(f"/api/clients/{cid}/passbooks").json()) == 2

    r = client.put(f"/api/passbooks/{pb['id']}", json={**{k: pb[k] for k in
                   ("code", "name", "bank_name", "branch_name", "account_type", "account_number",
                    "account_id", "sub_account_id", "counter_account_id")}, "name": "みずほ(本店)"})
    assert r.status_code == 200 and r.json()["name"] == "みずほ(本店)"

    assert client.delete(f"/api/passbooks/{pb2['id']}").status_code == 204
    assert len(client.get(f"/api/clients/{cid}/passbooks").json()) == 1


def test_passbook_rejects_account_of_other_client(client, sole):
    cl, fy, acc = sole
    other = client.post("/api/clients", json={"code": "002", "name": "他社", "chart": "tkc"}).json()
    oacc = {a["code"]: a for a in client.get(f"/api/clients/{other['id']}/accounts").json()}
    r = client.post(f"/api/clients/{cl['id']}/passbooks",
                    json={"name": "X", "account_id": oacc["1113"]["id"]})
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------

def test_analyze_text_matches_passbook_by_account_number(client, sole):
    cl, fy, acc = sole
    cid = cl["id"]
    pb = make_passbook(client, cid, acc)
    r = client.post(f"/api/clients/{cid}/passbook/analyze-text",
                    json={"text": SAMPLE, "fiscal_year_id": fy["id"], "opening_balance": 1200000})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["account"]["account_number"] == "1234567"
    assert data["passbook"]["id"] == pb["id"]
    assert data["matched_by"] == "口座番号"
    assert [x["direction"] for x in data["rows"]] == ["in", "out", "out"]
    assert [x["amount"] for x in data["rows"]] == [330000, 50000, 12800]
    assert all(not x["issues"] for x in data["rows"])


def test_analyze_uses_last_balance_of_passbook(client, sole):
    cl, fy, acc = sole
    cid = cl["id"]
    make_passbook(client, cid, acc, last_balance=1200000)
    data = client.post(f"/api/clients/{cid}/passbook/analyze-text",
                       json={"text": SAMPLE, "fiscal_year_id": fy["id"]}).json()
    assert data["opening_balance"] == 1200000
    assert data["rows"][0]["direction"] == "in" and not data["rows"][0]["issues"]


def test_analyze_separates_two_passbooks(client, sole):
    """口座番号が違えば別の通帳として認識される。"""
    cl, fy, acc = sole
    cid = cl["id"]
    a = make_passbook(client, cid, acc, name="A銀行", bank_name="A銀行", account_number="1234567")
    b = make_passbook(client, cid, acc, name="B銀行", bank_name="B銀行", account_number="7654321")

    text_a = "A銀行 本店 普通 1234567\n6-04-01 ニュウキン 10,000 110,000\n"
    text_b = "B銀行 本店 普通 7654321\n6-04-01 ニュウキン 20,000 220,000\n"
    ra = client.post(f"/api/clients/{cid}/passbook/analyze-text",
                     json={"text": text_a, "fiscal_year_id": fy["id"]}).json()
    rb = client.post(f"/api/clients/{cid}/passbook/analyze-text",
                     json={"text": text_b, "fiscal_year_id": fy["id"]}).json()
    assert ra["passbook"]["id"] == a["id"] and rb["passbook"]["id"] == b["id"]


def test_analyze_without_match_returns_no_passbook(client, sole):
    cl, fy, acc = sole
    data = client.post(f"/api/clients/{cl['id']}/passbook/analyze-text",
                       json={"text": "6-04-01 ナニカ 1,000 11,000\n", "fiscal_year_id": fy["id"]}).json()
    assert data["passbook"] is None and data["matched_by"] is None


def test_ocr_engines_endpoint(client):
    r = client.get("/api/ocr/engines")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["engines"], list)
    assert body["default"] is None or isinstance(body["default"], str)


def test_analyze_file_rejects_unsupported_format(client, sole):
    cl, fy, acc = sole
    files = {"file": ("passbook.txt", io.BytesIO(b"abc"), "text/plain")}
    r = client.post(f"/api/clients/{cl['id']}/passbook/analyze-file", files=files)
    assert r.status_code == 400 and "対応していない形式" in r.json()["detail"]


def test_analyze_file_without_ocr_engine_reports_clearly(client, sole, monkeypatch):
    """OCR が使えない環境では、別の取り込み方を案内するメッセージを返す。"""
    from app import ocr as ocrmod
    monkeypatch.setattr(ocrmod, "available_engines", lambda: [])
    monkeypatch.setattr(ocrmod, "default_engine", lambda: None)
    cl, fy, acc = sole
    files = {"file": ("p.png", io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"0" * 50), "image/png")}
    r = client.post(f"/api/clients/{cl['id']}/passbook/analyze-file", files=files)
    assert r.status_code == 400
    assert "貼り付け" in r.json()["detail"]


# ---------------------------------------------------------------------------
# 登録
# ---------------------------------------------------------------------------

def rows_for(data):
    return [{"entry_date": x["date"], "description": x["description"],
             "amount": x["amount"], "direction": x["direction"]} for x in data["rows"]]


def test_register_creates_only_the_two_patterns(client, sole):
    cl, fy, acc = sole
    cid = cl["id"]
    pb = make_passbook(client, cid, acc)
    # 会計期間に収まる日付にする
    text = SAMPLE.replace("6-04-01", fy["start_date"]).replace("6-04-05", fy["start_date"]) \
                 .replace("6-04-10", fy["start_date"])
    data = client.post(f"/api/clients/{cid}/passbook/analyze-text",
                       json={"text": text, "fiscal_year_id": fy["id"], "opening_balance": 1200000}).json()
    r = client.post(f"/api/clients/{cid}/passbook/register", json={
        "passbook_id": pb["id"], "rows": rows_for(data), "source": "text",
        "raw_text": text, "last_balance": 1467200})
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 3 and r.json()["skipped"] == 0

    entries = client.get(f"/api/clients/{cid}/entries").json()["entries"]
    assert len(entries) == 3
    bank, owner = acc["1113"]["id"], acc_by_id(acc, pb["counter_account_id"])["id"]
    lines = [e["lines"][0] for e in entries]
    # 入金 → 借方 普通預金 / 貸方 事業主借
    assert (lines[0]["debit_account_id"], lines[0]["credit_account_id"]) == (bank, owner)
    # 出金 → 借方 事業主借 / 貸方 普通預金
    assert (lines[1]["debit_account_id"], lines[1]["credit_account_id"]) == (owner, bank)
    assert (lines[2]["debit_account_id"], lines[2]["credit_account_id"]) == (owner, bank)
    # 消費税区分は対象外、摘要は通帳の内容
    assert all(l["tax_class"] == "00" and l["tax_amount"] == 0 for l in lines)
    assert "ヤマダショウテン" in lines[0]["description"]
    assert all(e["memo"] == pb["name"] for e in entries)
    # 通帳の最終残高が更新される
    assert client.get(f"/api/clients/{cid}/passbooks").json()[0]["last_balance"] == 1467200


def test_register_skips_duplicates(client, sole):
    cl, fy, acc = sole
    cid = cl["id"]
    pb = make_passbook(client, cid, acc)
    rows = [{"entry_date": fy["start_date"], "description": "カ)ヤマダ", "amount": 330000, "direction": "in"}]
    first = client.post(f"/api/clients/{cid}/passbook/register",
                        json={"passbook_id": pb["id"], "rows": rows})
    assert first.json()["created"] == 1
    again = client.post(f"/api/clients/{cid}/passbook/register",
                        json={"passbook_id": pb["id"], "rows": rows})
    assert again.json() == {**again.json(), "created": 0, "skipped": 1}
    assert client.get(f"/api/clients/{cid}/entries").json()["total"] == 1
    # 重複を許す指定なら登録される
    forced = client.post(f"/api/clients/{cid}/passbook/register",
                         json={"passbook_id": pb["id"], "rows": rows, "skip_duplicates": False})
    assert forced.json()["created"] == 1
    assert client.get(f"/api/clients/{cid}/entries").json()["total"] == 2


def test_register_validates_rows(client, sole):
    cl, fy, acc = sole
    cid = cl["id"]
    pb = make_passbook(client, cid, acc)
    base = {"passbook_id": pb["id"]}
    # 向きが不明
    r = client.post(f"/api/clients/{cid}/passbook/register", json={
        **base, "rows": [{"entry_date": fy["start_date"], "amount": 100, "direction": "unknown"}]})
    assert r.status_code == 400
    # 金額 0
    r = client.post(f"/api/clients/{cid}/passbook/register", json={
        **base, "rows": [{"entry_date": fy["start_date"], "amount": 0, "direction": "in"}]})
    assert r.status_code == 422
    # 会計期間外
    r = client.post(f"/api/clients/{cid}/passbook/register", json={
        **base, "rows": [{"entry_date": "1999-01-01", "amount": 100, "direction": "in"}]})
    assert r.status_code == 400
    # 行が空
    assert client.post(f"/api/clients/{cid}/passbook/register",
                       json={**base, "rows": []}).status_code == 400
    # 科目が未設定の通帳
    bare = client.post(f"/api/clients/{cid}/passbooks", json={"name": "科目未設定",
                                                             "account_id": None,
                                                             "counter_account_id": None}).json()
    conn_rows = [{"entry_date": fy["start_date"], "amount": 100, "direction": "in"}]
    client.put(f"/api/passbooks/{bare['id']}", json={"name": "科目未設定", "account_id": None,
                                                     "counter_account_id": None})
    r = client.post(f"/api/clients/{cid}/passbook/register",
                    json={"passbook_id": bare["id"], "rows": conn_rows})
    assert r.status_code == 400 and "科目" in r.json()["detail"]


def test_entries_are_separated_per_passbook(client, sole):
    cl, fy, acc = sole
    cid = cl["id"]
    a = make_passbook(client, cid, acc, name="A銀行", account_number="1111111")
    b = make_passbook(client, cid, acc, name="B銀行", account_number="2222222")
    client.post(f"/api/clients/{cid}/passbook/register", json={"passbook_id": a["id"], "rows": [
        {"entry_date": fy["start_date"], "description": "A入金", "amount": 1000, "direction": "in"}]})
    client.post(f"/api/clients/{cid}/passbook/register", json={"passbook_id": b["id"], "rows": [
        {"entry_date": fy["start_date"], "description": "B入金", "amount": 2000, "direction": "in"}]})

    imports = client.get(f"/api/clients/{cid}/passbook/imports").json()
    assert {i["passbook_name"] for i in imports} == {"A銀行", "B銀行"}
    assert all(i["entry_count"] == 1 for i in imports)
    # 同じ摘要・金額でも通帳が違えば重複扱いにならない
    again = client.post(f"/api/clients/{cid}/passbook/register", json={"passbook_id": b["id"], "rows": [
        {"entry_date": fy["start_date"], "description": "A入金", "amount": 1000, "direction": "in"}]})
    assert again.json()["created"] == 1


def test_delete_import_can_remove_its_entries(client, sole):
    cl, fy, acc = sole
    cid = cl["id"]
    pb = make_passbook(client, cid, acc)
    reg = client.post(f"/api/clients/{cid}/passbook/register", json={"passbook_id": pb["id"], "rows": [
        {"entry_date": fy["start_date"], "description": "テスト", "amount": 5000, "direction": "in"}]}).json()
    assert client.get(f"/api/clients/{cid}/entries").json()["total"] == 1

    # 履歴だけ消す → 仕訳は残る
    assert client.delete(f"/api/passbook/imports/{reg['import_id']}").status_code == 204
    assert client.get(f"/api/clients/{cid}/entries").json()["total"] == 1

    reg2 = client.post(f"/api/clients/{cid}/passbook/register", json={"passbook_id": pb["id"], "rows": [
        {"entry_date": fy["start_date"], "description": "テスト2", "amount": 6000, "direction": "in"}]}).json()
    assert client.delete(f"/api/passbook/imports/{reg2['import_id']}",
                         params={"with_entries": True}).status_code == 204
    assert client.get(f"/api/clients/{cid}/entries").json()["total"] == 1

    # 締め切られた期間の仕訳は消せない
    reg3 = client.post(f"/api/clients/{cid}/passbook/register", json={"passbook_id": pb["id"], "rows": [
        {"entry_date": fy["start_date"], "description": "テスト3", "amount": 7000, "direction": "in"}]}).json()
    client.post(f"/api/fiscal-years/{fy['id']}/close")
    r = client.delete(f"/api/passbook/imports/{reg3['import_id']}", params={"with_entries": True})
    assert r.status_code == 409


def test_deleting_passbook_keeps_entries(client, sole):
    cl, fy, acc = sole
    cid = cl["id"]
    pb = make_passbook(client, cid, acc)
    client.post(f"/api/clients/{cid}/passbook/register", json={"passbook_id": pb["id"], "rows": [
        {"entry_date": fy["start_date"], "description": "テスト", "amount": 5000, "direction": "in"}]})
    assert client.delete(f"/api/passbooks/{pb['id']}").status_code == 204
    assert client.get(f"/api/clients/{cid}/entries").json()["total"] == 1


def test_trial_balance_reflects_passbook_entries(client, sole):
    cl, fy, acc = sole
    cid = cl["id"]
    pb = make_passbook(client, cid, acc)
    client.post(f"/api/clients/{cid}/passbook/register", json={"passbook_id": pb["id"], "rows": [
        {"entry_date": fy["start_date"], "description": "入金", "amount": 330000, "direction": "in"},
        {"entry_date": fy["start_date"], "description": "出金", "amount": 50000, "direction": "out"},
    ]})
    tb = client.get(f"/api/fiscal-years/{fy['id']}/reports/trial-balance").json()
    rows = {r["code"]: r for r in tb["rows"]}
    assert rows["1113"]["closing_n"] == 280000            # 普通預金
    owner = acc_by_id(acc, pb["counter_account_id"])["code"]
    assert rows[owner]["closing_n"] == 280000             # 事業主借 (貸方残)
    assert sum(r["debit"] for r in tb["rows"]) == sum(r["credit"] for r in tb["rows"])


# ---------------------------------------------------------------------------
# PDF / DocuWorks の取り込み
# ---------------------------------------------------------------------------

def test_formats_endpoint(client):
    r = client.get("/api/passbook/formats")
    assert r.status_code == 200
    b = r.json()
    assert ".jpg" in b["accept"] and ".pdf" in b["accept"] and ".xdw" in b["accept"]
    assert isinstance(b["pdf"], bool) and isinstance(b["ocr"], list)
    assert b["xdw_command"] == ""


def test_settings_roundtrip(client):
    assert client.get("/api/settings").json() == {"xdw_converter": ""}
    r = client.put("/api/settings", json={"xdw_converter": 'conv.exe "{input}" "{output}"'})
    assert r.status_code == 200
    assert client.get("/api/settings").json()["xdw_converter"] == 'conv.exe "{input}" "{output}"'
    # {input} が無いコマンドは受け付けない
    bad = client.put("/api/settings", json={"xdw_converter": "conv.exe"})
    assert bad.status_code == 400 and "{input}" in bad.json()["detail"]
    # 空にすれば解除できる
    assert client.put("/api/settings", json={"xdw_converter": ""}).json()["xdw_converter"] == ""


def test_analyze_searchable_pdf_without_ocr(client, sole, tmp_path, monkeypatch):
    """文字情報つき PDF は OCR が無い環境でも取り込める。"""
    pytest.importorskip("pypdfium2")
    from app import ocr as ocrmod
    monkeypatch.setattr(ocrmod, "available_engines", lambda: [])
    monkeypatch.setattr(ocrmod, "default_engine", lambda: None)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_docfiles import make_text_pdf

    cl, fy, acc = sole
    cid = cl["id"]
    pb = make_passbook(client, cid, acc)
    y = fy["start_date"][:4]
    pdf = make_text_pdf(tmp_path / "p.pdf", [
        f"{y}-01-01 KA)YAMADA SHOUTEN 330,000 1,530,000",
        f"{y}-01-05 ATM 50,000 1,480,000",
    ])
    files = {"file": ("passbook.pdf", io.BytesIO(pdf.read_bytes()), "application/pdf")}
    r = client.post(f"/api/clients/{cid}/passbook/analyze-file",
                    params={"fiscal_year_id": fy["id"], "opening_balance": 1200000}, files=files)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["method"] == "PDF の文字情報"
    assert data["ocr_engine"] == ""
    assert [x["direction"] for x in data["rows"]] == ["in", "out"]
    assert [x["amount"] for x in data["rows"]] == [330000, 50000]
    assert "YAMADA" in data["rows"][0]["description"]

    # そのまま仕訳にできる
    reg = client.post(f"/api/clients/{cid}/passbook/register", json={
        "passbook_id": pb["id"],
        "rows": [{"entry_date": x["date"], "description": x["description"],
                  "amount": x["amount"], "direction": x["direction"]} for x in data["rows"]],
        "source": "pdf"})
    assert reg.json()["created"] == 2


def test_analyze_xdw_with_embedded_images_needs_ocr(client, sole, monkeypatch):
    """.xdw から画像は取り出せるが、OCR が無ければその旨を返す。"""
    pytest.importorskip("PIL")
    from PIL import Image
    from app import ocr as ocrmod
    monkeypatch.setattr(ocrmod, "available_engines", lambda: [])
    monkeypatch.setattr(ocrmod, "default_engine", lambda: None)
    buf = io.BytesIO()
    Image.new("RGB", (800, 600), "white").save(buf, "JPEG", quality=80)
    blob = b"XDW header" + b"\x00" * 200 + buf.getvalue()

    cl, fy, acc = sole
    files = {"file": ("scan.xdw", io.BytesIO(blob), "application/octet-stream")}
    r = client.post(f"/api/clients/{cl['id']}/passbook/analyze-file", files=files)
    assert r.status_code == 400
    assert "貼り付け" in r.json()["detail"]


def test_analyze_xdw_that_cannot_be_read_gives_guidance(client, sole):
    cl, fy, acc = sole
    files = {"file": ("x.xdw", io.BytesIO(b"XDW" + b"\x01\x02" * 5000), "application/octet-stream")}
    r = client.post(f"/api/clients/{cl['id']}/passbook/analyze-file", files=files)
    assert r.status_code == 400
    msg = r.json()["detail"]
    assert "DocuWorks" in msg and "PDF" in msg


def test_upload_size_limit(client, sole):
    cl, fy, acc = sole
    big = io.BytesIO(b"\x00" * (61 * 1024 * 1024))
    files = {"file": ("big.jpg", big, "image/jpeg")}
    r = client.post(f"/api/clients/{cl['id']}/passbook/analyze-file", files=files)
    assert r.status_code == 400 and "大きすぎます" in r.json()["detail"]
