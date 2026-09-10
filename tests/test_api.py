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
    app = create_app()
    with TestClient(app) as c:
        yield c


def make_client(c, tax_method="inclusive", entity_type="corp", code="001"):
    r = c.post("/api/clients", json={"code": code, "name": "テスト商事", "entity_type": entity_type,
                                     "tax_method": tax_method, "fiscal_start_month": 4})
    assert r.status_code == 201, r.text
    cl = r.json()
    fys = c.get(f"/api/clients/{cl['id']}/fiscal-years").json()
    assert len(fys) == 1
    accts = c.get(f"/api/clients/{cl['id']}/accounts").json()
    by_code = {a["code"]: a for a in accts}
    return cl, fys[0], by_code


def test_create_client_copies_standard_accounts(client):
    cl, fy, acc = make_client(client)
    assert "100" in acc and acc["100"]["name"] == "現金"
    assert "412" in acc  # 繰越利益剰余金 (法人)
    assert "420" not in acc  # 元入金は個人のみ
    _, _, acc2 = make_client(client, entity_type="sole", code="002")
    assert "420" in acc2 and "412" not in acc2
    meta = client.get("/api/meta").json()
    assert any(t["code"] == "11" for t in meta["tax_classes"])


def test_entry_validation(client):
    cl, fy, acc = make_client(client)
    d = fy["start_date"]
    # 貸借不一致
    r = client.post(f"/api/clients/{cl['id']}/entries", json={"entry_date": d, "lines": [
        {"debit_account_id": acc["100"]["id"], "amount": 1000},
        {"credit_account_id": acc["500"]["id"], "amount": 900, "tax_class": "11"},
    ]})
    assert r.status_code == 400 and "貸借" in r.json()["detail"]
    # 期間外
    r = client.post(f"/api/clients/{cl['id']}/entries", json={"entry_date": "1999-01-01", "lines": [
        {"debit_account_id": acc["100"]["id"], "credit_account_id": acc["500"]["id"], "amount": 1000}]})
    assert r.status_code == 400
    # 正常 (単一仕訳, 内税自動計算)
    r = client.post(f"/api/clients/{cl['id']}/entries", json={"entry_date": d, "lines": [
        {"debit_account_id": acc["100"]["id"], "credit_account_id": acc["500"]["id"], "amount": 11000,
         "tax_class": "11", "description": "現金売上"}]})
    assert r.status_code == 201, r.text
    e = r.json()
    assert e["voucher_no"] == 1
    assert e["lines"][0]["tax_amount"] == 1000
    assert e["lines"][0]["debit_name"] == "現金"
    # 更新
    r = client.put(f"/api/entries/{e['id']}", json={"entry_date": d, "lines": [
        {"debit_account_id": acc["111"]["id"], "credit_account_id": acc["500"]["id"], "amount": 22000, "tax_class": "11"}]})
    assert r.status_code == 200
    assert r.json()["lines"][0]["tax_amount"] == 2000
    lst = client.get(f"/api/clients/{cl['id']}/entries", params={"account_id": acc["111"]["id"]}).json()
    assert lst["total"] == 1
    # 削除
    assert client.delete(f"/api/entries/{e['id']}").status_code == 204
    assert client.get(f"/api/entries/{e['id']}").status_code == 404


def post_sample_entries(client, cl, fy, acc):
    d = fy["start_date"]
    cid = cl["id"]
    # 資本金払込
    client.post(f"/api/clients/{cid}/entries", json={"entry_date": d, "lines": [
        {"debit_account_id": acc["111"]["id"], "credit_account_id": acc["400"]["id"], "amount": 1000000}]}).raise_for_status()
    # 売上 (課税 10%) 110,000 現金
    client.post(f"/api/clients/{cid}/entries", json={"entry_date": d, "lines": [
        {"debit_account_id": acc["100"]["id"], "credit_account_id": acc["500"]["id"], "amount": 110000, "tax_class": "11"}]}).raise_for_status()
    # 消耗品 (課税仕入 10%) 33,000 現金
    client.post(f"/api/clients/{cid}/entries", json={"entry_date": d, "lines": [
        {"debit_account_id": acc["617"]["id"], "credit_account_id": acc["100"]["id"], "amount": 33000, "tax_class": "21"}]}).raise_for_status()
    # 複合仕訳: 給料 300,000 = 預り金 30,000 + 普通預金 270,000
    r = client.post(f"/api/clients/{cid}/entries", json={"entry_date": d, "lines": [
        {"debit_account_id": acc["601"]["id"], "amount": 300000, "description": "8月分給与"},
        {"credit_account_id": acc["316"]["id"], "amount": 30000, "description": "源泉所得税"},
        {"credit_account_id": acc["111"]["id"], "amount": 270000, "description": "振込"},
    ]})
    r.raise_for_status()


def test_trial_balance_inclusive_and_statements(client):
    cl, fy, acc = make_client(client, tax_method="inclusive")
    post_sample_entries(client, cl, fy, acc)
    tb = client.get(f"/api/fiscal-years/{fy['id']}/reports/trial-balance").json()
    rows = {r["code"]: r for r in tb["rows"]}
    assert rows["100"]["closing_n"] == 110000 - 33000
    assert rows["111"]["closing_n"] == 1000000 - 270000
    assert rows["500"]["closing_n"] == 110000
    assert rows["617"]["closing_n"] == 33000
    assert rows["601"]["closing_n"] == 300000
    assert rows["316"]["closing_n"] == 30000
    assert "166" not in rows and "318" not in rows  # 税込経理では消費税科目に転記しない
    assert tb["net_income"]["closing"] == 110000 - 33000 - 300000
    # 借方合計 = 貸方合計
    assert sum(r["debit"] for r in tb["rows"]) == sum(r["credit"] for r in tb["rows"])

    fs = client.get(f"/api/fiscal-years/{fy['id']}/reports/financial-statements").json()
    assert fs["bs"]["total_assets"] == fs["bs"]["total_liabilities_equity"]
    assert fs["pl"]["net_income"] == tb["net_income"]["closing"]

    ledger = client.get(f"/api/fiscal-years/{fy['id']}/reports/ledger", params={"account_id": acc["100"]["id"]}).json()
    assert ledger["closing"] == 77000
    assert ledger["rows"][0]["counter_name"] == "売上高"
    ledger2 = client.get(f"/api/fiscal-years/{fy['id']}/reports/ledger", params={"account_id": acc["111"]["id"]}).json()
    assert ledger2["rows"][-1]["counter_name"] == "諸口"

    monthly = client.get(f"/api/fiscal-years/{fy['id']}/reports/monthly").json()
    assert len(monthly["months"]) == 12
    m = {r["code"]: r for r in monthly["rows"]}
    assert m["500"]["total"] == 110000

    tax = client.get(f"/api/fiscal-years/{fy['id']}/reports/tax-summary").json()
    assert tax["sales_tax"] == 10000 and tax["purchase_tax"] == 3000 and tax["net_tax"] == 7000


def test_trial_balance_exclusive_splits_tax(client):
    cl, fy, acc = make_client(client, tax_method="exclusive")
    post_sample_entries(client, cl, fy, acc)
    tb = client.get(f"/api/fiscal-years/{fy['id']}/reports/trial-balance").json()
    rows = {r["code"]: r for r in tb["rows"]}
    assert rows["500"]["closing_n"] == 100000
    assert rows["318"]["closing_n"] == 10000   # 仮受消費税
    assert rows["617"]["closing_n"] == 30000
    assert rows["166"]["closing_n"] == 3000    # 仮払消費税
    assert rows["100"]["closing_n"] == 77000   # 現金は税込のまま
    assert sum(r["debit"] for r in tb["rows"]) == sum(r["credit"] for r in tb["rows"])
    fs = client.get(f"/api/fiscal-years/{fy['id']}/reports/financial-statements").json()
    assert fs["bs"]["total_assets"] == fs["bs"]["total_liabilities_equity"]


def test_carry_forward(client):
    cl, fy, acc = make_client(client, tax_method="inclusive")
    post_sample_entries(client, cl, fy, acc)
    r = client.post(f"/api/fiscal-years/{fy['id']}/carry-forward")
    assert r.status_code == 200, r.text
    nxt = r.json()["next_fiscal_year"]
    ob = client.get(f"/api/fiscal-years/{nxt['id']}/opening-balances").json()
    by = {o["account_code"]: o["amount"] for o in ob}
    assert by["100"] == 77000
    assert by["111"] == 730000
    assert by["400"] == -1000000
    assert by["316"] == -30000
    assert by["412"] == -(110000 - 33000 - 300000)  # 当期純損失 → 繰越利益剰余金 (借方残)
    assert sum(by.values()) == 0
    # 翌期の試算表: 期首残高が反映され、PL はゼロ
    tb = client.get(f"/api/fiscal-years/{nxt['id']}/reports/trial-balance").json()
    rows = {r["code"]: r for r in tb["rows"]}
    assert rows["100"]["opening_n"] == 77000
    assert "500" not in rows
    fs = client.get(f"/api/fiscal-years/{nxt['id']}/reports/financial-statements").json()
    assert fs["bs"]["total_assets"] == fs["bs"]["total_liabilities_equity"]


def test_csv_roundtrip(client):
    cl, fy, acc = make_client(client)
    post_sample_entries(client, cl, fy, acc)
    r = client.get(f"/api/fiscal-years/{fy['id']}/export/journal.csv")
    assert r.status_code == 200
    text = r.content.decode("utf-8-sig")
    assert text.splitlines()[0].startswith("日付,伝票番号")
    assert len(text.splitlines()) == 1 + 3 + 3

    # 別の顧問先に取り込む
    cl2, fy2, acc2 = make_client(client, code="002")
    files = {"file": ("journal.csv", io.BytesIO(r.content), "text/csv")}
    dry = client.post(f"/api/clients/{cl2['id']}/import/journal", params={"dry_run": True}, files=files)
    assert dry.status_code == 200, dry.text
    assert dry.json() == {"count": 4, "lines": 6, "dry_run": True}
    files = {"file": ("journal.csv", io.BytesIO(r.content), "text/csv")}
    imp = client.post(f"/api/clients/{cl2['id']}/import/journal", files=files)
    assert imp.status_code == 200, imp.text
    assert imp.json()["count"] == 4
    tb1 = client.get(f"/api/fiscal-years/{fy['id']}/reports/trial-balance").json()
    tb2 = client.get(f"/api/fiscal-years/{fy2['id']}/reports/trial-balance").json()
    assert [(r["code"], r["closing"]) for r in tb1["rows"]] == [(r["code"], r["closing"]) for r in tb2["rows"]]


def test_masters_and_opening_balances(client):
    cl, fy, acc = make_client(client)
    cid = cl["id"]
    # 補助科目
    r = client.post(f"/api/accounts/{acc['111']['id']}/sub-accounts", json={"code": "1", "name": "○○銀行"})
    assert r.status_code == 201
    sub = r.json()
    # 補助科目が科目と不一致
    r = client.post(f"/api/clients/{cid}/entries", json={"entry_date": fy["start_date"], "lines": [
        {"debit_account_id": acc["100"]["id"], "debit_sub_id": sub["id"], "credit_account_id": acc["500"]["id"], "amount": 100}]})
    assert r.status_code == 400
    # 期首残高
    r = client.put(f"/api/fiscal-years/{fy['id']}/opening-balances", json={"items": [
        {"account_id": acc["111"]["id"], "sub_account_id": sub["id"], "amount": 500000},
        {"account_id": acc["400"]["id"], "amount": -500000},
    ]})
    assert r.status_code == 200 and r.json()["difference"] == 0
    tb = client.get(f"/api/fiscal-years/{fy['id']}/reports/trial-balance", params={"by_sub": True}).json()
    rows = {r["code"]: r for r in tb["rows"]}
    assert rows["111"]["opening_n"] == 500000
    assert rows["111"]["subs"][0]["closing_n"] == 500000
    # 新規科目 / 使用中科目の削除不可
    r = client.post(f"/api/clients/{cid}/accounts", json={"code": "640", "name": "教育訓練費", "grp": "販売費及び一般管理費", "default_tax_class": "21"})
    assert r.status_code == 201 and r.json()["category"] == "expense"
    r = client.post(f"/api/clients/{cid}/entries", json={"entry_date": fy["start_date"], "lines": [
        {"debit_account_id": acc["617"]["id"], "credit_account_id": acc["100"]["id"], "amount": 100}]})
    assert r.status_code == 201
    assert client.delete(f"/api/accounts/{acc['617']['id']}").status_code == 409
    # 定型仕訳
    r = client.post(f"/api/clients/{cid}/templates", json={"code": "1", "name": "家賃支払", "debit_account_id": acc["624"]["id"],
                                                          "credit_account_id": acc["111"]["id"], "amount": 110000, "tax_class": "21"})
    assert r.status_code == 201
    assert len(client.get(f"/api/clients/{cid}/templates").json()) == 1
    # 締め
    client.post(f"/api/fiscal-years/{fy['id']}/close")
    r = client.post(f"/api/clients/{cid}/entries", json={"entry_date": fy["start_date"], "lines": [
        {"debit_account_id": acc["617"]["id"], "credit_account_id": acc["100"]["id"], "amount": 100}]})
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# 勘定科目マスタの自由な編集
# ---------------------------------------------------------------------------

def test_account_code_and_name_are_freely_editable(client):
    """コードと名称を変えても、過去の仕訳・期首残高は科目 ID で結び付いたまま残る。"""
    cl, fy, acc = make_client(client)
    cid = cl["id"]
    cash_id = acc["100"]["id"]
    sales_id = acc["500"]["id"]
    client.put(f"/api/fiscal-years/{fy['id']}/opening-balances", json={"items": [
        {"account_id": cash_id, "amount": 50000},
        {"account_id": acc["400"]["id"], "amount": -50000},
    ]}).raise_for_status()
    client.post(f"/api/clients/{cid}/entries", json={"entry_date": fy["start_date"], "lines": [
        {"debit_account_id": cash_id, "credit_account_id": sales_id, "amount": 11000, "tax_class": "11"}]}).raise_for_status()

    # TKC 風のコードへ付け替え、名称も変更する
    r = client.put(f"/api/accounts/{cash_id}", json={
        "code": "1101", "name": "現金及び預金", "kana": "げんきんおよびよきん",
        "grp": "流動資産", "default_tax_class": "00", "role": "", "active": True})
    assert r.status_code == 200, r.text
    assert r.json()["code"] == "1101" and r.json()["name"] == "現金及び預金"

    tb = client.get(f"/api/fiscal-years/{fy['id']}/reports/trial-balance").json()
    rows = {x["code"]: x for x in tb["rows"]}
    assert "100" not in rows
    assert rows["1101"]["name"] == "現金及び預金"
    assert rows["1101"]["opening_n"] == 50000
    assert rows["1101"]["closing_n"] == 61000
    entry = client.get(f"/api/clients/{cid}/entries").json()["entries"][0]
    assert entry["lines"][0]["debit_code"] == "1101"


def test_accounts_bulk_save(client):
    cl, fy, acc = make_client(client)
    cid = cl["id"]
    items = [{"id": a["id"], "code": a["code"], "name": a["name"], "kana": a["kana"], "grp": a["grp"],
              "default_tax_class": a["default_tax_class"], "role": a["role"],
              "sort_order": a["sort_order"], "active": bool(a["active"])}
             for a in client.get(f"/api/clients/{cid}/accounts").json()]
    # 既存 1 件のコードを変更、1 件追加、1 件削除
    items[0]["code"] = "1000"
    items[0]["name"] = "現金 (小口)"
    items.append({"id": None, "code": "9001", "name": "教育訓練費", "kana": "きょういくくんれんひ",
                  "grp": "販売費及び一般管理費", "default_tax_class": "21", "role": "", "sort_order": 9999, "active": True})
    drop = acc["101"]["id"]
    r = client.put(f"/api/clients/{cid}/accounts/bulk",
                   json={"items": [i for i in items if i["id"] != drop], "delete_ids": [drop]})
    assert r.status_code == 200, r.text
    assert r.json() == {"created": 1, "updated": len(items) - 2, "deleted": 1}
    after = {a["code"]: a for a in client.get(f"/api/clients/{cid}/accounts").json()}
    assert "1000" in after and after["1000"]["name"] == "現金 (小口)"
    assert "9001" in after and after["9001"]["category"] == "expense"
    assert "101" not in after

    # コード重複は拒否される
    dupe = [dict(i) for i in items if i["id"] != drop]
    dupe[1]["code"] = dupe[0]["code"]
    r = client.put(f"/api/clients/{cid}/accounts/bulk", json={"items": dupe, "delete_ids": []})
    assert r.status_code == 409 and "重複" in r.json()["detail"]

    # 使用中の科目は削除できない
    client.post(f"/api/clients/{cid}/entries", json={"entry_date": fy["start_date"], "lines": [
        {"debit_account_id": acc["617"]["id"], "credit_account_id": after["1000"]["id"], "amount": 500}]}).raise_for_status()
    keep = [i for i in items if i["id"] not in (drop, acc["617"]["id"])]
    r = client.put(f"/api/clients/{cid}/accounts/bulk", json={"items": keep, "delete_ids": [acc["617"]["id"]]})
    assert r.status_code == 409 and "使用されている" in r.json()["detail"]


def test_accounts_csv_roundtrip_and_replace(client):
    cl, fy, acc = make_client(client, tax_method="exclusive")
    cid = cl["id"]
    r = client.get(f"/api/clients/{cid}/export/accounts.csv")
    assert r.status_code == 200
    text = r.content.decode("utf-8-sig")
    assert text.splitlines()[0].startswith("コード,科目名,かな,表示区分,既定の税区分,役割,並び順,有効")
    assert "仮受消費税" in text

    # 自前 (TKC 風) の科目表に丸ごと入れ替える
    csv_text = ("﻿" + "\r\n".join([
        "コード,科目名,かな,表示区分,既定の税区分,役割,並び順,有効",
        "1101,現金,げんきん,流動資産,00,,10,1",
        "1102,普通預金,ふつうよきん,流動資産,00,,20,1",
        "1301,仮払消費税等,かりばらいしょうひぜい,流動資産,00,仮払消費税,30,1",
        "2101,買掛金,かいかけきん,流動負債,00,,40,1",
        "2301,仮受消費税等,かりうけしょうひぜい,流動負債,00,仮受消費税,50,1",
        "3201,繰越利益剰余金,くりこしりえきじょうよきん,純資産,00,繰越利益剰余金,60,1",
        "4101,売上高,うりあげだか,売上高,課税売上 10%,,70,1",
        "5101,仕入高,しいれだか,売上原価,21,,80,1",
        "# この行は読み飛ばされます",
        "",
    ])).encode("utf-8")

    files = {"file": ("accounts.csv", io.BytesIO(csv_text), "text/csv")}
    dry = client.post(f"/api/clients/{cid}/import/accounts", params={"mode": "replace", "dry_run": True}, files=files)
    assert dry.status_code == 200, dry.text
    d = dry.json()
    assert d["created"] == 8 and d["updated"] == 0 and d["warnings"] == []
    assert d["deleted"] + d["deactivated"] == len(acc)
    assert {a["code"] for a in client.get(f"/api/clients/{cid}/accounts").json()} == set(acc)  # 確認だけなので未変更

    files = {"file": ("accounts.csv", io.BytesIO(csv_text), "text/csv")}
    imp = client.post(f"/api/clients/{cid}/import/accounts", params={"mode": "replace"}, files=files)
    assert imp.status_code == 200, imp.text
    after = {a["code"]: a for a in client.get(f"/api/clients/{cid}/accounts").json()}
    assert set(after) == {"1101", "1102", "1301", "2101", "2301", "3201", "4101", "5101"}
    assert after["4101"]["default_tax_class"] == "11"       # 名称からコードを解決
    assert after["1301"]["role"] == "tax_receivable"        # 日本語の役割名を解決
    assert after["3201"]["category"] == "equity"

    # 入れ替えた科目表で税抜経理の仕訳・繰越が動く
    client.post(f"/api/clients/{cid}/entries", json={"entry_date": fy["start_date"], "lines": [
        {"debit_account_id": after["1101"]["id"], "credit_account_id": after["4101"]["id"],
         "amount": 110000, "tax_class": "11"}]}).raise_for_status()
    tb = client.get(f"/api/fiscal-years/{fy['id']}/reports/trial-balance").json()
    rows = {x["code"]: x for x in tb["rows"]}
    assert rows["4101"]["closing_n"] == 100000
    assert rows["2301"]["closing_n"] == 10000
    cf = client.post(f"/api/fiscal-years/{fy['id']}/carry-forward")
    assert cf.status_code == 200, cf.text
    ob = {o["account_code"]: o["amount"] for o in
          client.get(f"/api/fiscal-years/{cf.json()['next_fiscal_year']['id']}/opening-balances").json()}
    assert ob["1101"] == 110000 and ob["3201"] == -100000
    assert sum(ob.values()) == 0


def test_accounts_csv_import_validation_and_warnings(client):
    cl, fy, acc = make_client(client, tax_method="exclusive")
    cid = cl["id"]

    def send(body, **params):
        files = {"file": ("a.csv", io.BytesIO(body.encode("utf-8")), "text/csv")}
        return client.post(f"/api/clients/{cid}/import/accounts", params=params, files=files)

    head = "コード,科目名,表示区分,既定の税区分,役割\r\n"
    assert send(head + "100,現金,ありえない区分,00,\r\n").status_code == 400
    assert send(head + "100,現金,流動資産,99,\r\n").status_code == 400
    assert send(head + "100,現金,流動資産,00,ありえない役割\r\n").status_code == 400
    assert send(head + "100,現金,流動資産,00,\r\n100,重複,流動資産,00,\r\n").status_code == 400
    assert send(head + ",名前なし,流動資産,00,\r\n").status_code == 400
    r = send(head + "100,現金,流動資産,00,仮払消費税\r\n101,小口,流動資産,00,仮払消費税\r\n")
    assert r.status_code == 400 and "重複" in r.json()["detail"]

    # replace で必要な役割が欠けると警告が返る (取込自体は行われる)
    r = send(head + "100,現金,流動資産,00,\r\n", mode="replace", dry_run=True)
    assert r.status_code == 200
    w = " ".join(r.json()["warnings"])
    assert "仮払消費税" in w and "仮受消費税" in w and "繰越利益剰余金" in w


def test_copy_accounts_between_clients_and_empty_chart(client):
    src, fy_src, acc_src = make_client(client, code="001")
    # 科目表を空にして顧問先を作る
    r = client.post("/api/clients", json={"code": "002", "name": "新規法人", "entity_type": "corp",
                                          "tax_method": "inclusive", "fiscal_start_month": 4,
                                          "copy_standard_accounts": False})
    assert r.status_code == 201
    dst = r.json()
    assert client.get(f"/api/clients/{dst['id']}/accounts").json() == []
    assert len(client.get(f"/api/clients/{dst['id']}/fiscal-years").json()) == 1

    # 複写元に補助科目を作ってから複写する
    client.post(f"/api/accounts/{acc_src['111']['id']}/sub-accounts", json={"code": "1", "name": "○○銀行"}).raise_for_status()
    client.put(f"/api/accounts/{acc_src['100']['id']}", json={
        "code": "1101", "name": "現金", "kana": "げんきん", "grp": "流動資産",
        "default_tax_class": "00", "role": "", "active": True}).raise_for_status()

    r = client.post(f"/api/clients/{dst['id']}/accounts/copy-from/{src['id']}", params={"with_subs": True})
    assert r.status_code == 200, r.text
    assert r.json()["created"] == len(acc_src) and r.json()["sub_accounts"] == 1
    after = {a["code"]: a for a in client.get(f"/api/clients/{dst['id']}/accounts").json()}
    assert "1101" in after and "100" not in after
    assert after["412"]["role"] == "retained"
    subs = client.get(f"/api/clients/{dst['id']}/sub-accounts").json()
    assert len(subs) == 1 and subs[0]["name"] == "○○銀行"

    # 自分自身を複写元にはできない
    assert client.post(f"/api/clients/{dst['id']}/accounts/copy-from/{dst['id']}").status_code == 400
