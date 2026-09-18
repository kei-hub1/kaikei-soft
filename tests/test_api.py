import io
import os
import sys
from datetime import date, timedelta
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


def make_client(c, tax_method="inclusive", entity_type="corp", code="001", chart="standard"):
    r = c.post("/api/clients", json={"code": code, "name": "テスト商事", "entity_type": entity_type,
                                     "tax_method": tax_method, "fiscal_start_month": 4,
                                     "chart": chart})
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
    assert dry.json() == {"count": 4, "lines": 6, "skipped": 0, "dry_run": True,
                          "skipped_samples": [], "sub_applied": 0, "sub_label": ""}
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
    r = client.post(f"/api/clients/{cid}/templates", json={"code": "1", "name": "家賃支払", "lines": [
        {"debit_account_id": acc["624"]["id"], "credit_account_id": acc["111"]["id"], "amount": 110000, "tax_class": "21"}]})
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
                                          "chart": "none"})
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


# ---------------------------------------------------------------------------
# TKC コード体系
# ---------------------------------------------------------------------------

def test_tkc_chart_matches_the_reference_table(client):
    """docs/tkc_codes.md に載っているコードと名称がそのまま入っていること。"""
    cl, fy, acc = make_client(client, chart="tkc")
    for code, name in [
        ("1111", "現金"), ("1113", "普通預金"), ("1122", "売掛金"), ("1131", "商品・製品"),
        ("1164", "仮払消費税等"), ("1215", "車両運搬具"), ("1221", "土地"), ("1237", "ソフトウェア"),
        ("2112", "買掛金"), ("2117", "預り金"), ("2212", "長期借入金"), ("3111", "資本金"),
        ("4111", "売上高"), ("5211", "商品仕入高"), ("5431", "賃金"),
        ("6211", "役員報酬"), ("6223", "接待交際費"), ("6312", "法定福利費"),
        ("7111", "受取利息"), ("7511", "支払利息"), ("8311", "法人税、住民税及び事業税"),
        ("9991", "資金諸口"), ("9992", "資金外諸口"),
    ]:
        assert code in acc, f"{code} {name} がありません"
        assert acc[code]["name"] == name, f"{code}: {acc[code]['name']} != {name}"

    # 資料に無いコードを勝手に作っていないこと (暫定コードのみ英字始まり)
    from app.master_data import PROVISIONAL_PREFIX
    for code in acc:
        assert code.isdigit() or code.startswith(PROVISIONAL_PREFIX), code

    # 未確定・未確認のものは収録していない
    assert "1253" not in acc and "1258" not in acc      # 保険積立金
    assert "6234" not in acc and "6228" not in acc      # リース料

    # 法人には事業主勘定を入れない
    assert "9411" not in acc and "9311" not in acc
    assert acc["3111"]["category"] == "equity"
    assert acc["1164"]["role"] == "tax_receivable"
    assert acc["4111"]["default_tax_class"] == "11"
    assert acc["5211"]["default_tax_class"] == "21"


def test_tkc_chart_provisional_accounts(client):
    """コードが判明していない科目は暫定コードで入り、名称に印が付くこと。"""
    from app.master_data import PROVISIONAL_MARK
    cl, fy, acc = make_client(client, chart="tkc")
    prov = {c: a for c, a in acc.items() if PROVISIONAL_MARK in a["name"]}
    assert {a["role"] for a in prov.values()} == {"tax_payable", "retained", ""}
    assert len(prov) == 3   # 仮受消費税等 / 未払消費税等 / 繰越利益剰余金

    _, _, sole = make_client(client, entity_type="sole", code="002", chart="tkc")
    assert sole["9411"]["role"] == "owner_drawing"
    assert sole["9311"]["role"] == "owner_contrib"
    assert "3111" not in sole
    sole_prov = {c: a for c, a in sole.items() if PROVISIONAL_MARK in a["name"]}
    assert {a["role"] for a in sole_prov.values()} == {"tax_payable", "owner_capital", ""}


def test_tkc_chart_full_workflow(client):
    """TKC 科目表で税抜経理の仕訳・帳票・繰越が一通り動くこと。"""
    cl, fy, acc = make_client(client, tax_method="exclusive", chart="tkc")
    cid, d = cl["id"], fy["start_date"]
    aid = {c: a["id"] for c, a in acc.items()}
    prov_payable = next(c for c, a in acc.items() if a["role"] == "tax_payable")
    prov_retained = next(c for c, a in acc.items() if a["role"] == "retained")

    # 資本金 / 売上 / 仕入 / 給与 (複合)
    client.post(f"/api/clients/{cid}/entries", json={"entry_date": d, "lines": [
        {"debit_account_id": aid["1113"], "credit_account_id": aid["3111"], "amount": 1000000}]}).raise_for_status()
    client.post(f"/api/clients/{cid}/entries", json={"entry_date": d, "lines": [
        {"debit_account_id": aid["1122"], "credit_account_id": aid["4111"], "amount": 550000, "tax_class": "11"}]}).raise_for_status()
    client.post(f"/api/clients/{cid}/entries", json={"entry_date": d, "lines": [
        {"debit_account_id": aid["5211"], "credit_account_id": aid["2112"], "amount": 220000, "tax_class": "21"}]}).raise_for_status()
    client.post(f"/api/clients/{cid}/entries", json={"entry_date": d, "lines": [
        {"debit_account_id": aid["6212"], "amount": 250000},
        {"credit_account_id": aid["2117"], "amount": 25000},
        {"credit_account_id": aid["1113"], "amount": 225000},
    ]}).raise_for_status()

    tb = client.get(f"/api/fiscal-years/{fy['id']}/reports/trial-balance").json()
    rows = {r["code"]: r for r in tb["rows"]}
    assert rows["4111"]["closing_n"] == 500000          # 税抜の売上
    assert rows[prov_payable]["closing_n"] == 50000     # 仮受消費税等
    assert rows["5211"]["closing_n"] == 200000          # 税抜の仕入
    assert rows["1164"]["closing_n"] == 20000           # 仮払消費税等
    assert rows["1122"]["closing_n"] == 550000          # 売掛金は税込
    assert sum(r["debit"] for r in tb["rows"]) == sum(r["credit"] for r in tb["rows"])

    fs = client.get(f"/api/fiscal-years/{fy['id']}/reports/financial-statements").json()
    assert fs["bs"]["total_assets"] == fs["bs"]["total_liabilities_equity"]
    assert fs["pl"]["gross_profit"] == 300000

    tax = client.get(f"/api/fiscal-years/{fy['id']}/reports/tax-summary").json()
    assert tax["sales_tax"] == 50000 and tax["purchase_tax"] == 20000 and tax["net_tax"] == 30000

    cf = client.post(f"/api/fiscal-years/{fy['id']}/carry-forward")
    assert cf.status_code == 200, cf.text
    ob = {o["account_code"]: o["amount"] for o in
          client.get(f"/api/fiscal-years/{cf.json()['next_fiscal_year']['id']}/opening-balances").json()}
    assert ob["1113"] == 775000
    assert ob["2117"] == -25000
    assert ob["3111"] == -1000000
    assert ob[prov_retained] == -(500000 - 200000 - 250000)
    assert sum(ob.values()) == 0


def test_meta_exposes_charts_and_tkc_tax_divisions(client):
    meta = client.get("/api/meta").json()
    assert [c["code"] for c in meta["charts"]] == ["tkc", "standard", "none"]
    assert meta["provisional_prefix"] == "Z"
    div = {d["code"]: d["name"] for d in meta["tkc_tax_divisions"]}
    assert div["1"] == "課税売上げ"
    assert div["5"] == "課税売上げにのみ要する課税仕入れ"
    assert div["52"] == "免税事業者等からの課税仕入れ（課税売上げ）"
    assert div["0"] == "不課税取引（税外取引）"
    tc = {t["code"]: t for t in meta["tax_classes"]}
    assert tc["11"]["tkc"] == "1" and tc["13"]["tkc"] == "3" and tc["23"]["tkc"] == "8"
    assert tc["21"]["tkc"] == "5 / 6 / 7"


def test_invalid_chart_is_rejected(client):
    r = client.post("/api/clients", json={"code": "900", "name": "X", "entity_type": "corp",
                                          "tax_method": "inclusive", "fiscal_start_month": 4, "chart": "ありえない"})
    assert r.status_code == 400


def test_apply_chart_to_existing_client(client):
    """既存の顧問先に後から TKC 科目表を適用しても、入力済みの仕訳が残ること。"""
    cl, fy, acc = make_client(client, tax_method="exclusive", chart="standard")
    cid, d = cl["id"], fy["start_date"]
    client.post(f"/api/clients/{cid}/entries", json={"entry_date": d, "lines": [
        {"debit_account_id": acc["100"]["id"], "credit_account_id": acc["500"]["id"],
         "amount": 110000, "tax_class": "11", "description": "現金売上"}]}).raise_for_status()

    # merge: 既存科目は残したまま TKC の科目を足す
    r = client.post(f"/api/clients/{cid}/accounts/apply-chart", params={"chart": "tkc", "mode": "merge"})
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] == 0 and r.json()["deactivated"] == 0
    after = {a["code"]: a for a in client.get(f"/api/clients/{cid}/accounts").json()}
    assert "100" in after and "1111" in after          # 旧科目も TKC 科目も居る
    assert after["100"]["id"] == acc["100"]["id"]      # ID は変わらない

    # replace: TKC に無い旧科目は削除、使用中のものは無効化
    r = client.post(f"/api/clients/{cid}/accounts/apply-chart", params={"chart": "tkc", "mode": "replace"})
    assert r.status_code == 200, r.text
    after = {a["code"]: a for a in client.get(f"/api/clients/{cid}/accounts").json()}
    assert "1111" in after and after["1111"]["active"] == 1
    assert after["100"]["active"] == 0 and after["500"]["active"] == 0   # 仕訳で使用中 → 無効化
    assert "101" not in after                                           # 未使用 → 削除

    # 仕訳はそのまま残っている
    entries = client.get(f"/api/clients/{cid}/entries").json()
    assert entries["total"] == 1
    line = entries["entries"][0]["lines"][0]
    assert line["debit_code"] == "100" and line["description"] == "現金売上"
    tb = client.get(f"/api/fiscal-years/{fy['id']}/reports/trial-balance").json()
    rows = {x["code"]: x for x in tb["rows"]}
    assert rows["100"]["closing_n"] == 110000
    assert sum(x["debit"] for x in tb["rows"]) == sum(x["credit"] for x in tb["rows"])

    assert client.post(f"/api/clients/{cid}/accounts/apply-chart", params={"chart": "none"}).status_code == 400
    assert client.post(f"/api/clients/{cid}/accounts/apply-chart", params={"mode": "xx"}).status_code == 400


# ---------------------------------------------------------------------------
# 摘要プリセットと摘要順
# ---------------------------------------------------------------------------

def test_description_presets_crud(client):
    cl, fy, acc = make_client(client)
    cid = cl["id"]
    assert client.get(f"/api/clients/{cid}/descriptions").json() == []

    r = client.post(f"/api/clients/{cid}/descriptions", json={
        "code": "1", "text": "株式会社アオイ商店", "kana": "あおいしょうてん",
        "account_id": acc["500"]["id"]})
    assert r.status_code == 201, r.text
    d1 = r.json()
    assert d1["sort_order"] == 10

    # 同じ摘要は登録できない
    assert client.post(f"/api/clients/{cid}/descriptions", json={"text": "株式会社アオイ商店"}).status_code == 409
    # 他の顧問先の科目は関連付けられない
    other, _, oacc = make_client(client, code="002")
    assert client.post(f"/api/clients/{cid}/descriptions",
                       json={"text": "X", "account_id": oacc["100"]["id"]}).status_code == 400

    r = client.put(f"/api/descriptions/{d1['id']}", json={
        "code": "1", "text": "(株)アオイ商店", "kana": "あおいしょうてん", "account_id": None, "active": False})
    assert r.status_code == 200 and r.json()["text"] == "(株)アオイ商店" and r.json()["active"] == 0

    assert client.delete(f"/api/descriptions/{d1['id']}").status_code == 204
    assert client.get(f"/api/clients/{cid}/descriptions").json() == []


def test_description_presets_bulk_and_suggestions(client):
    cl, fy, acc = make_client(client)
    cid, d = cl["id"], fy["start_date"]
    items = [
        {"id": None, "code": "1", "text": "アオイ商店", "kana": "あおい", "account_id": acc["130"]["id"], "active": True},
        {"id": None, "code": "2", "text": "カキ工業", "kana": "かき", "account_id": None, "active": True},
        {"id": None, "code": "3", "text": "使わない摘要", "kana": "", "account_id": None, "active": False},
    ]
    r = client.put(f"/api/clients/{cid}/descriptions/bulk", json={"items": items, "delete_ids": []})
    assert r.status_code == 200 and r.json()["created"] == 3
    saved = client.get(f"/api/clients/{cid}/descriptions").json()
    assert [x["text"] for x in saved] == ["アオイ商店", "カキ工業", "使わない摘要"]
    assert saved[0]["account_code"] == "130"

    # 重複は拒否
    dup = items + [{"id": None, "code": "9", "text": "アオイ商店", "active": True}]
    assert client.put(f"/api/clients/{cid}/descriptions/bulk", json={"items": dup, "delete_ids": []}).status_code == 409

    # 候補: 有効なプリセット + 過去に使った摘要 (プリセットと重複するものは除く)
    client.post(f"/api/clients/{cid}/entries", json={"entry_date": d, "lines": [
        {"debit_account_id": acc["100"]["id"], "credit_account_id": acc["500"]["id"],
         "amount": 1000, "description": "アオイ商店"}]}).raise_for_status()
    client.post(f"/api/clients/{cid}/entries", json={"entry_date": d, "lines": [
        {"debit_account_id": acc["100"]["id"], "credit_account_id": acc["500"]["id"],
         "amount": 2000, "description": "その場で打った摘要"}]}).raise_for_status()
    sug = client.get(f"/api/clients/{cid}/description-suggestions").json()
    assert [p["text"] for p in sug["presets"]] == ["アオイ商店", "カキ工業"]   # 無効は出ない
    assert [h["text"] for h in sug["history"]] == ["その場で打った摘要"]

    # プリセットを消しても入力済みの仕訳の摘要は残る
    target = next(x for x in saved if x["text"] == "アオイ商店")
    client.delete(f"/api/descriptions/{target['id']}")
    e = client.get(f"/api/clients/{cid}/entries").json()["entries"][0]
    assert e["lines"][0]["description"] == "アオイ商店"


def test_descriptions_from_history(client):
    cl, fy, acc = make_client(client)
    cid, d = cl["id"], fy["start_date"]
    for text, times in [("よく使う摘要", 3), ("たまに使う摘要", 1)]:
        for _ in range(times):
            client.post(f"/api/clients/{cid}/entries", json={"entry_date": d, "lines": [
                {"debit_account_id": acc["100"]["id"], "credit_account_id": acc["500"]["id"],
                 "amount": 100, "description": text}]}).raise_for_status()
    r = client.post(f"/api/clients/{cid}/descriptions/from-history", params={"min_count": 2})
    assert r.status_code == 200 and r.json()["added"] == 1
    assert [x["text"] for x in client.get(f"/api/clients/{cid}/descriptions").json()] == ["よく使う摘要"]
    # 2 回目は重複しない
    assert client.post(f"/api/clients/{cid}/descriptions/from-history", params={"min_count": 2}).json()["added"] == 0


def post_described_entries(client, cid, d, acc):
    for day, text, amount in [
        ("01", "カキ工業", 3000), ("02", "アオイ商店", 1000), ("03", "カキ工業", 5000),
        ("04", "アオイ商店", 2000), ("05", "", 700),
    ]:
        client.post(f"/api/clients/{cid}/entries", json={"entry_date": d[:8] + day, "lines": [
            {"debit_account_id": acc["100"]["id"], "credit_account_id": acc["500"]["id"],
             "amount": amount, "description": text}]}).raise_for_status()


def test_entries_sorted_by_description(client):
    cl, fy, acc = make_client(client)
    cid = cl["id"]
    post_described_entries(client, cid, fy["start_date"], acc)

    by_date = client.get(f"/api/clients/{cid}/entries").json()["entries"]
    assert [e["lines"][0]["description"] for e in by_date] == ["カキ工業", "アオイ商店", "カキ工業", "アオイ商店", ""]

    by_desc = client.get(f"/api/clients/{cid}/entries", params={"sort": "description"}).json()["entries"]
    got = [e["lines"][0]["description"] for e in by_desc]
    assert got == sorted(got, key=lambda s: (s == "", s))          # 同じ摘要がまとまる
    assert got[:2] == ["アオイ商店", "アオイ商店"]
    assert got[-1] == ""                                            # 摘要なしは最後
    # 同じ摘要の中では日付順
    aoi = [e for e in by_desc if e["lines"][0]["description"] == "アオイ商店"]
    assert [e["entry_date"] for e in aoi] == sorted(e["entry_date"] for e in aoi)

    # 摘要の完全一致で絞り込める
    only = client.get(f"/api/clients/{cid}/entries", params={"description": "カキ工業"}).json()
    assert only["total"] == 2
    assert all(e["lines"][0]["description"] == "カキ工業" for e in only["entries"])

    assert client.get(f"/api/clients/{cid}/entries", params={"sort": "ありえない"}).status_code == 400


def test_ledger_sorted_by_description(client):
    cl, fy, acc = make_client(client)
    cid = cl["id"]
    post_described_entries(client, cid, fy["start_date"], acc)
    cash = acc["100"]["id"]

    r = client.get(f"/api/fiscal-years/{fy['id']}/reports/ledger",
                   params={"account_id": cash, "sort": "description"}).json()
    assert r["sort"] == "description"
    assert [x["description"] for x in r["rows"]] == ["アオイ商店", "アオイ商店", "カキ工業", "カキ工業", ""]
    groups = {g["description"]: g for g in r["groups"]}
    assert groups["アオイ商店"]["count"] == 2 and groups["アオイ商店"]["debit"] == 3000
    assert groups["カキ工業"]["count"] == 2 and groups["カキ工業"]["debit"] == 8000
    assert groups[""]["debit"] == 700
    # 合計は日付順と同じ
    d = client.get(f"/api/fiscal-years/{fy['id']}/reports/ledger", params={"account_id": cash}).json()
    assert r["total_debit"] == d["total_debit"] == 11700
    assert d["sort"] == "date" and d["groups"] == []
    assert client.get(f"/api/fiscal-years/{fy['id']}/reports/ledger",
                      params={"account_id": cash, "sort": "xx"}).status_code == 400


def test_description_summary_report(client):
    cl, fy, acc = make_client(client)
    cid = cl["id"]
    post_described_entries(client, cid, fy["start_date"], acc)

    r = client.get(f"/api/fiscal-years/{fy['id']}/reports/description-summary").json()
    rows = {x["description"]: x for x in r["rows"]}
    assert [x["description"] for x in r["rows"]] == ["アオイ商店", "カキ工業", ""]
    # 現金と売上高の両方に転記されるので 1 摘要あたり 2 行
    assert rows["カキ工業"]["count"] == 4
    assert rows["カキ工業"]["debit"] == 8000 and rows["カキ工業"]["credit"] == 8000
    assert rows["カキ工業"]["net"] == 0
    assert rows["カキ工業"]["accounts"] == ["100 現金", "500 売上高"]
    assert rows["アオイ商店"]["first_date"] < rows["アオイ商店"]["last_date"]
    assert r["total_debit"] == r["total_credit"] == 11700

    # 科目で絞ると片側だけになる
    only = client.get(f"/api/fiscal-years/{fy['id']}/reports/description-summary",
                      params={"account_id": acc["100"]["id"]}).json()
    rows = {x["description"]: x for x in only["rows"]}
    assert rows["カキ工業"]["count"] == 2 and rows["カキ工業"]["debit"] == 8000
    assert rows["カキ工業"]["credit"] == 0
    assert only["account"]["code"] == "100"


def test_descriptions_csv_roundtrip(client):
    cl, fy, acc = make_client(client)
    cid = cl["id"]
    client.put(f"/api/clients/{cid}/descriptions/bulk", json={"items": [
        {"id": None, "code": "1", "text": "アオイ商店", "kana": "あおい", "account_id": acc["130"]["id"], "active": True},
        {"id": None, "code": "2", "text": "カキ工業", "kana": "かき", "account_id": None, "active": True},
    ], "delete_ids": []}).raise_for_status()

    r = client.get(f"/api/clients/{cid}/export/descriptions.csv")
    assert r.status_code == 200
    text = r.content.decode("utf-8-sig")
    assert text.splitlines()[0].startswith("コード,摘要,かな,関連科目コード,並び順,有効")
    assert "アオイ商店" in text and "130" in text

    cl2, _, _ = make_client(client, code="002")
    files = {"file": ("d.csv", io.BytesIO(r.content), "text/csv")}
    dry = client.post(f"/api/clients/{cl2['id']}/import/descriptions", params={"dry_run": True}, files=files)
    assert dry.status_code == 200 and dry.json()["created"] == 2

    files = {"file": ("d.csv", io.BytesIO(r.content), "text/csv")}
    assert client.post(f"/api/clients/{cl2['id']}/import/descriptions", files=files).status_code == 200
    got = client.get(f"/api/clients/{cl2['id']}/descriptions").json()
    assert [x["text"] for x in got] == ["アオイ商店", "カキ工業"]
    assert got[0]["account_code"] == "130"

    # 不正な科目コードと摘要の重複は拒否
    def send(body, **params):
        f = {"file": ("d.csv", io.BytesIO(body.encode("utf-8")), "text/csv")}
        return client.post(f"/api/clients/{cid}/import/descriptions", params=params, files=f)
    head = "コード,摘要,関連科目コード\r\n"
    assert send(head + "1,X,9999\r\n").status_code == 400
    assert send(head + "1,X,\r\n2,X,\r\n").status_code == 400
    assert send("コード,かな\r\n1,あ\r\n").status_code == 400   # 「摘要」列が無い


def test_description_sort_uses_kana_when_registered(client):
    """かなを登録した摘要は五十音順に並ぶ。"""
    cl, fy, acc = make_client(client)
    cid, d = cl["id"], fy["start_date"]
    # 漢字の文字コード順と五十音順が食い違う組み合わせ
    presets = [("株式会社アオイ商店", "あおいしょうてん"),
               ("有限会社ウメダ", "うめだ"),
               ("カキ工業", "かきこうぎょう")]
    client.put(f"/api/clients/{cid}/descriptions/bulk", json={"items": [
        {"id": None, "code": str(i + 1), "text": t, "kana": k, "active": True}
        for i, (t, k) in enumerate(presets)], "delete_ids": []}).raise_for_status()
    for i, (t, _k) in enumerate(reversed(presets)):
        client.post(f"/api/clients/{cid}/entries", json={"entry_date": d, "lines": [
            {"debit_account_id": acc["100"]["id"], "credit_account_id": acc["500"]["id"],
             "amount": 1000 * (i + 1), "description": t}]}).raise_for_status()

    wanted = [t for t, _k in presets]
    entries = client.get(f"/api/clients/{cid}/entries", params={"sort": "description"}).json()["entries"]
    assert [e["lines"][0]["description"] for e in entries] == wanted
    led = client.get(f"/api/fiscal-years/{fy['id']}/reports/ledger",
                     params={"account_id": acc["100"]["id"], "sort": "description"}).json()
    assert [g["description"] for g in led["groups"]] == wanted
    summ = client.get(f"/api/fiscal-years/{fy['id']}/reports/description-summary").json()
    assert [r["description"] for r in summ["rows"]] == wanted


def test_pages_are_not_cached_by_the_browser(client):
    """更新後に古い画面が表示されないよう、毎回サーバーに確認させる。"""
    for url in ("/", "/static/index.html", "/static/app.js", "/static/style.css"):
        r = client.get(url)
        assert r.status_code == 200, url
        assert "no-cache" in r.headers.get("cache-control", ""), url
    # 内容が変わっていなければ 304 が返り、通信量は増えない
    first = client.get("/static/app.js")
    again = client.get("/static/app.js", headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304
    assert "no-cache" in again.headers.get("cache-control", "")


def test_new_screens_are_in_the_menu(client):
    """後から足した画面がメニューに並んでいること。"""
    html = client.get("/").text
    for route, label in [("descriptions", "摘要"), ("descsum", "摘要別集計"),
                         ("templates", "定型仕訳")]:
        assert f'data-route="{route}"' in html, route
        assert label in html, label


def _csv_row(date, dcode, ccode, amount, tax="00", desc="", memo="", vno=""):
    return f"{date},{vno},{dcode},,,,,{ccode},,,,,{amount},{tax},,{desc},{memo}"


def _upload_csv(client, cl, lines, dry_run=False, sub_id=None):
    text = "\ufeff日付,伝票番号,借方科目コード,借方科目名,借方補助コード,借方補助名,借方部門コード," \
           "貸方科目コード,貸方科目名,貸方補助コード,貸方補助名,貸方部門コード,金額,消費税区分,消費税額,摘要,伝票メモ\r\n"
    text += "\r\n".join(lines) + "\r\n"
    files = {"file": ("bank.csv", io.BytesIO(text.encode("utf-8")), "text/csv")}
    params = {"dry_run": dry_run}
    if sub_id:
        params["sub_id"] = sub_id
    r = client.post(f"/api/clients/{cl['id']}/import/journal", params=params, files=files)
    assert r.status_code == 200, r.text
    return r.json()


def _entries(client, fy):
    return client.get(f"/api/clients/{fy['client_id']}/entries", params={"fiscal_year_id": fy["id"]}).json()["entries"]


def test_csv_import_skips_entries_that_already_exist(client):
    """同じ通帳履歴を何度取り込んでも、完全に一致する伝票は二重計上しない。"""
    cl, fy, acc = make_client(client)
    d = fy["start_date"]
    rows = [
        _csv_row(d, "111", "400", 50000, desc="振込 ヤマダ"),
        _csv_row(d, "617", "111", 3300, tax="21", desc="コンビニ"),
    ]
    first = _upload_csv(client, cl, rows)
    assert (first["count"], first["skipped"]) == (2, 0)

    # 同じファイルをもう一度: 検証でも取込でも全件が登録済みと判定される
    dry = _upload_csv(client, cl, rows, dry_run=True)
    assert (dry["count"], dry["skipped"], dry["dry_run"]) == (0, 2, True)
    assert dry["skipped_samples"] == [f"{d}  50,000  振込 ヤマダ", f"{d}  3,300  コンビニ"]
    again = _upload_csv(client, cl, rows)
    assert (again["count"], again["skipped"]) == (0, 2)
    assert len(_entries(client, fy)) == 2

    # 次回訪問: 前回分 + 新しい行が混ざったファイル → 新しい行だけ入る
    rows2 = rows + [_csv_row(d, "111", "400", 70000, desc="振込 サトウ")]
    third = _upload_csv(client, cl, rows2)
    assert (third["count"], third["skipped"]) == (1, 2)
    assert len(_entries(client, fy)) == 3


def test_csv_import_matches_on_date_amount_description_only(client):
    """日付・金額・摘要が同じなら、科目・税区分・伝票メモ・伝票番号が違っても登録済みとみなす。"""
    cl, fy, acc = make_client(client)
    d = fy["start_date"]
    _upload_csv(client, cl, [_csv_row(d, "111", "400", 50000, desc="振込 ヤマダ")])
    same = [
        _csv_row(d, "100", "400", 50000, desc="振込 ヤマダ"),                 # 借方科目を付け替えた後
        _csv_row(d, "111", "400", 50000, tax="11", desc="振込 ヤマダ"),       # 税区分
        _csv_row(d, "111", "400", 50000, desc="振込 ヤマダ", memo="要確認"),  # 伝票メモ
        _csv_row(d, "111", "400", 50000, desc="振込 ヤマダ", vno="999"),      # 伝票番号
        _csv_row(d, "111", "400", 50000, desc="振込 ヤマダ "),                # 前後の空白
    ]
    for row in same:
        r = _upload_csv(client, cl, [row])
        assert (r["count"], r["skipped"]) == (0, 1), row
    assert len(_entries(client, fy)) == 1

    # 金額・摘要・日付のどれかが違えば別の伝票
    d2 = (date.fromisoformat(d) + timedelta(days=1)).isoformat()
    different = [
        _csv_row(d, "111", "400", 50001, desc="振込 ヤマダ"),
        _csv_row(d, "111", "400", 50000, desc="振込 ヤマダ商店"),
        _csv_row(d2, "111", "400", 50000, desc="振込 ヤマダ"),
    ]
    r = _upload_csv(client, cl, different)
    assert (r["count"], r["skipped"]) == (3, 0)


def test_csv_import_skips_after_reclassifying_the_account(client):
    """取り込んだ仕訳の科目を画面で直した後に、同じ CSV を取り込み直しても重ならない。"""
    cl, fy, acc = make_client(client)
    d = fy["start_date"]
    row = _csv_row(d, "111", "400", 33000, desc="コンビニ")
    _upload_csv(client, cl, [row])
    e = _entries(client, fy)[0]
    # 事業主借 → 消耗品費 (課税仕入 10%) に付け替え
    r = client.put(f"/api/entries/{e['id']}", json={"entry_date": d, "lines": [
        {"debit_account_id": acc["617"]["id"], "credit_account_id": acc["111"]["id"],
         "amount": 33000, "tax_class": "21", "description": "コンビニ"}]})
    assert r.status_code == 200, r.text
    r = _upload_csv(client, cl, [row])
    assert (r["count"], r["skipped"]) == (0, 1)
    assert len(_entries(client, fy)) == 1


def test_csv_import_keeps_genuinely_repeated_transactions(client):
    """同じ日に同じ内容の取引が本当に複数回ある場合は、その件数分だけ登録する。"""
    cl, fy, acc = make_client(client)
    d = fy["start_date"]
    twice = [_csv_row(d, "617", "111", 10000, tax="21", desc="ATM引出")] * 2
    r = _upload_csv(client, cl, twice)
    assert (r["count"], r["skipped"]) == (2, 0)          # 同じファイル内の同一行は両方入る
    r = _upload_csv(client, cl, twice)
    assert (r["count"], r["skipped"]) == (0, 2)          # 再取込は両方飛ばす
    r = _upload_csv(client, cl, twice * 2)
    assert (r["count"], r["skipped"]) == (2, 2)          # 4 件のうち登録済み 2 件を超える分だけ入る
    assert len(_entries(client, fy)) == 4


def _add_sub(client, acc, code, name):
    r = client.post(f"/api/accounts/{acc['id']}/sub-accounts", json={"code": code, "name": name})
    assert r.status_code == 201, r.text
    return r.json()


def test_csv_import_assigns_one_sub_account_to_the_whole_file(client):
    """通帳ごとに CSV を分けて取り込むとき、補助科目を一括で付けられる。"""
    cl, fy, acc = make_client(client)
    bank = acc["111"]                      # 普通預金
    a = _add_sub(client, bank, "01", "A銀行")
    b = _add_sub(client, bank, "02", "B銀行")
    d = fy["start_date"]
    rows = [_csv_row(d, "111", "400", 50000, desc="振込 ヤマダ"),      # 入金 (借方が普通預金)
            _csv_row(d, "617", "111", 3300, desc="口座振替")]          # 出金 (貸方が普通預金)

    r = _upload_csv(client, cl, rows, dry_run=True, sub_id=a["id"])
    assert (r["sub_applied"], r["sub_label"]) == (2, "111 普通預金 / A銀行")
    r = _upload_csv(client, cl, rows, sub_id=a["id"])
    assert (r["count"], r["sub_applied"]) == (2, 2)
    lines = [l for e in _entries(client, fy) for l in e["lines"]]
    assert [(l["debit_sub_name"], l["credit_sub_name"]) for l in lines] == [("A銀行", None), (None, "A銀行")]

    # 同じ内容でも別の通帳なら取り込む (補助科目で区別する)
    r = _upload_csv(client, cl, rows, sub_id=b["id"])
    assert (r["count"], r["skipped"]) == (2, 0)
    # 同じ通帳をもう一度なら飛ばす。飛ばした分は「付けた行数」にも数えない
    r = _upload_csv(client, cl, rows, sub_id=b["id"])
    assert (r["count"], r["skipped"], r["sub_applied"]) == (0, 2, 0)
    assert len(_entries(client, fy)) == 4


def test_csv_import_sub_account_does_not_override_the_csv(client):
    """CSV に補助科目が書いてあれば、そちらを優先する。"""
    cl, fy, acc = make_client(client)
    bank = acc["111"]
    a = _add_sub(client, bank, "01", "A銀行")
    _add_sub(client, bank, "02", "B銀行")
    d = fy["start_date"]
    # 借方補助コードに 02 を書いた行 (列位置: 日付,伝票番号,借方科目コード,借方科目名,借方補助コード,...)
    row = f"{d},,111,,02,,,400,,,,,50000,00,,振込,"
    r = _upload_csv(client, cl, [row], sub_id=a["id"])
    assert (r["count"], r["sub_applied"]) == (1, 0)
    assert _entries(client, fy)[0]["lines"][0]["debit_sub_name"] == "B銀行"


def test_csv_import_reports_when_the_sub_account_matches_nothing(client):
    """指定した補助科目の科目が CSV に出てこないときは、件数 0 で知らせる。"""
    cl, fy, acc = make_client(client)
    a = _add_sub(client, acc["111"], "01", "A銀行")
    d = fy["start_date"]
    r = _upload_csv(client, cl, [_csv_row(d, "100", "500", 10000, desc="現金売上")], dry_run=True, sub_id=a["id"])
    assert (r["count"], r["sub_applied"]) == (1, 0)


def test_csv_import_rejects_an_unknown_sub_account(client):
    cl, fy, acc = make_client(client)
    cl2, _, _ = make_client(client, code="002")
    a = _add_sub(client, acc["111"], "01", "A銀行")
    d = fy["start_date"]
    text = "日付,伝票番号,借方科目コード,借方科目名,借方補助コード,借方補助名,借方部門コード," \
           "貸方科目コード,貸方科目名,貸方補助コード,貸方補助名,貸方部門コード,金額,消費税区分,消費税額,摘要,伝票メモ\r\n"
    files = {"file": ("x.csv", io.BytesIO(text.encode("utf-8")), "text/csv")}
    # 別の顧問先の補助科目は使えない
    r = client.post(f"/api/clients/{cl2['id']}/import/journal", params={"sub_id": a["id"]}, files=files)
    assert r.status_code == 400
    assert "補助科目" in r.json()["detail"]


def test_templates_hold_a_whole_voucher(client):
    """定型仕訳は複合仕訳 (伝票まるごと) を持てる。"""
    cl, fy, acc = make_client(client)
    cid = cl["id"]
    body = {"code": "10", "name": "給与支払", "memo": "毎月25日", "lines": [
        {"debit_account_id": acc["601"]["id"], "amount": 300000, "description": "給与"},
        {"credit_account_id": acc["316"]["id"], "amount": 30000, "description": "源泉所得税"},
        {"credit_account_id": acc["111"]["id"], "amount": 270000, "description": "振込"},
    ]}
    t = client.post(f"/api/clients/{cid}/templates", json=body).json()
    assert (t["code"], t["name"], t["memo"]) == ("10", "給与支払", "毎月25日")
    assert [(l["amount"], l["description"]) for l in t["lines"]] == [
        (300000, "給与"), (30000, "源泉所得税"), (270000, "振込")]

    # 修正でも明細が入れ替わる
    body["lines"] = body["lines"][:2]
    body["name"] = "給与支払 (2 行)"
    t2 = client.put(f"/api/templates/{t['id']}", json=body).json()
    assert len(t2["lines"]) == 2 and t2["name"] == "給与支払 (2 行)"

    # 同じコードは使えない
    r = client.post(f"/api/clients/{cid}/templates", json={"code": "10", "name": "別", "lines": []})
    assert r.status_code == 409

    # 削除すると明細も消える
    assert client.delete(f"/api/templates/{t['id']}").status_code == 204
    assert client.get(f"/api/clients/{cid}/templates").json() == []


def test_template_can_be_made_from_an_existing_entry(client):
    """登録済みの伝票を、そのまま定型仕訳にできる。"""
    cl, fy, acc = make_client(client)
    cid = cl["id"]
    d = fy["start_date"]
    e = client.post(f"/api/clients/{cid}/entries", json={"entry_date": d, "memo": "要確認", "lines": [
        {"debit_account_id": acc["601"]["id"], "amount": 300000, "description": "8月分給与"},
        {"credit_account_id": acc["316"]["id"], "amount": 30000, "description": "源泉所得税"},
        {"credit_account_id": acc["111"]["id"], "amount": 270000, "description": "振込"},
    ]}).json()
    t = client.post(f"/api/clients/{cid}/templates/from-entry/{e['id']}",
                    params={"name": "給与の支払"}).json()
    assert t["name"] == "給与の支払"
    assert t["memo"] == "要確認"                      # 伝票メモも引き継ぐ
    assert t["code"] == "1"                            # 空いている番号が付く
    assert [(l["debit_account_id"], l["credit_account_id"], l["amount"], l["description"]) for l in t["lines"]] == [
        (acc["601"]["id"], None, 300000, "8月分給与"),
        (None, acc["316"]["id"], 30000, "源泉所得税"),
        (None, acc["111"]["id"], 270000, "振込")]

    # 名前を省くと最初の摘要が名前になる。コードは次の空き番号
    t2 = client.post(f"/api/clients/{cid}/templates/from-entry/{e['id']}").json()
    assert (t2["code"], t2["name"]) == ("2", "8月分給与")

    # 他の顧問先の伝票は取れない
    cl2, _, _ = make_client(client, code="002")
    r = client.post(f"/api/clients/{cl2['id']}/templates/from-entry/{e['id']}")
    assert r.status_code == 404
