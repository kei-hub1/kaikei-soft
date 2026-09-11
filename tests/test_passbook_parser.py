"""通帳テキストの解析 (app/passbook.py) のテスト。

OCR の出力は行の体裁が崩れるので、実際に出てきそうな形をいくつも通す。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.passbook import extract_account_info, parse_date, parse_passbook_text


def rows_of(text, **kw):
    return parse_passbook_text(text, **kw)["rows"]


# ---------------------------------------------------------------------------
# 日付
# ---------------------------------------------------------------------------

def test_parse_date_formats():
    assert parse_date("令和6年4月1日") == "2024-04-01"
    assert parse_date("令和元年5月1日") == "2019-05-01"
    assert parse_date("R6.4.1") == "2024-04-01"
    assert parse_date("R6-04-01") == "2024-04-01"
    assert parse_date("平成31年4月30日") == "2019-04-30"
    assert parse_date("2026/4/1") == "2026-04-01"
    assert parse_date("2026-04-01") == "2026-04-01"
    assert parse_date("１２月３１日", year_hint=2026) == "2026-12-31"


def test_parse_date_two_digit_year_uses_hint():
    # 「6-04-01」は令和6年(2024)とも2006年ともとれる。会計期間の年に近い方を採る。
    assert parse_date("6-04-01", year_hint=2024) == "2024-04-01"
    assert parse_date("26-04-01", year_hint=2026) == "2026-04-01"
    assert parse_date("31-04-30", year_hint=2019) == "2019-04-30"   # 平成31年


def test_parse_date_rejects_garbage():
    assert parse_date("") is None
    assert parse_date("カ)ヤマダ") is None
    assert parse_date("令和6年13月45日") is None
    assert parse_date("2026/2/30") is None


# ---------------------------------------------------------------------------
# 行の解析と入出金の判定
# ---------------------------------------------------------------------------

SAMPLE = """
年月日  お取引内容   お支払金額   お預り金額   差引残高
6-04-01 カ)ヤマダショウテン        330,000   1,530,000
6-04-05 ATM出金        50,000      1,480,000
6-04-10 デンキダイ      12,800      1,467,200
6-04-25 振込 サトウタロウ         220,000   1,687,200
"""


def test_balance_delta_decides_direction():
    r = rows_of(SAMPLE, year_hint=2024, opening_balance=1_200_000)
    assert len(r) == 4
    assert [x["date"] for x in r] == ["2024-04-01", "2024-04-05", "2024-04-10", "2024-04-25"]
    assert [x["direction"] for x in r] == ["in", "out", "out", "in"]
    assert [x["amount"] for x in r] == [330000, 50000, 12800, 220000]
    assert [x["balance"] for x in r] == [1530000, 1480000, 1467200, 1687200]
    assert all(not x["issues"] for x in r), [x["issues"] for x in r]
    assert "カ)ヤマダショウテン" in r[0]["description"]


def test_header_line_is_skipped():
    parsed = parse_passbook_text(SAMPLE, year_hint=2024, opening_balance=1_200_000)
    assert any("年月日" in s for s in parsed["skipped"])
    assert all("年月日" not in x["description"] for x in parsed["rows"])


def test_first_row_without_opening_balance_is_flagged():
    r = rows_of(SAMPLE, year_hint=2024)
    assert r[0]["direction"] is None or r[0]["issues"]
    # 2 行目以降は前行の残高から判定できる
    assert [x["direction"] for x in r[1:]] == ["out", "out", "in"]
    assert not r[1]["issues"]


def test_amount_not_matching_balance_change_is_flagged():
    text = "6-04-01 テスト 100,000 1,300,000\n6-04-02 テスト2 99,999 1,200,000\n"
    r = rows_of(text, year_hint=2024, opening_balance=1_200_000)
    assert r[0]["direction"] == "in" and not r[0]["issues"]
    assert r[1]["direction"] == "out"
    assert any("一致しません" in i for i in r[1]["issues"])


def test_amount_filled_from_balance_when_missing():
    text = "6-04-01 カ)ヤマダ 1,300,000\n"
    r = rows_of(text, year_hint=2024, opening_balance=1_200_000)
    assert r[0]["amount"] == 100000 and r[0]["direction"] == "in"


def test_wrapped_description_is_merged():
    text = ("6-04-01 カ)ヤマダショウ 330,000 1,530,000\n"
            "テン ４月分\n"
            "6-04-05 ATM 50,000 1,480,000\n")
    r = rows_of(text, year_hint=2024, opening_balance=1_200_000)
    assert len(r) == 2
    assert "テン" in r[0]["description"] and "4月分" in r[0]["description"]


def test_direction_guessed_from_words_when_no_balance():
    text = "6-04-01 ATM出金 50,000\n6-04-02 振込入金 30,000\n"
    r = rows_of(text, year_hint=2024)
    assert r[0]["direction"] == "out" and r[1]["direction"] == "in"
    assert all(any("推測" in i for i in x["issues"]) for x in r)


def test_unknown_direction_is_reported():
    text = "6-04-01 ナニカ 50,000\n"
    r = rows_of(text, year_hint=2024)
    assert r[0]["direction"] is None
    assert any("判定できません" in i for i in r[0]["issues"])


def test_full_width_digits_and_yen_marks():
    text = "６－０４－０１　カ）ヤマダ　￥330,000　￥1,530,000\n"
    r = rows_of(text, year_hint=2024, opening_balance=1_200_000)
    assert r[0]["date"] == "2024-04-01"
    assert r[0]["amount"] == 330000 and r[0]["balance"] == 1530000
    assert r[0]["direction"] == "in"


def test_date_unreadable_is_flagged():
    text = "6-04-01 テスト 100,000 1,300,000\nXX-XX-XX ヨメナイ 5,000 1,295,000\n"
    r = rows_of(text, year_hint=2024, opening_balance=1_200_000)
    assert len(r) == 2
    assert r[1]["date"] is None
    assert any("日付" in i for i in r[1]["issues"])
    # 日付が読めなくても残高から入出金は判定できる
    assert r[1]["direction"] == "out" and r[1]["amount"] == 5000


def test_empty_text_gives_no_rows():
    assert rows_of("") == []
    assert rows_of("   \n\n  ") == []


# ---------------------------------------------------------------------------
# 口座情報の抽出
# ---------------------------------------------------------------------------

def test_extract_account_info():
    head = "みずほ銀行 渋谷支店\n普通預金 1234567\n口座番号 1234567\n山田太郎 様\n"
    info = extract_account_info(head)
    assert info["bank_name"] == "みずほ銀行"
    assert info["branch_name"] == "渋谷支店"
    assert info["account_type"] == "普通"
    assert info["account_number"] == "1234567"


def test_extract_account_info_variants():
    assert extract_account_info("ゆうちょ銀行\n記号12345 番号 6789012\n")["bank_name"] == "ゆうちょ銀行"
    assert extract_account_info("○○信用金庫 本店営業部\n普通 9876543\n")["account_number"] == "9876543"
    assert extract_account_info("店番 123 普通 1112223\n")["branch_number"] == "123"
    assert extract_account_info("何も無いテキスト") == {}


def test_account_number_is_returned_with_rows():
    text = "みずほ銀行 渋谷支店 普通 1234567\n" + SAMPLE
    parsed = parse_passbook_text(text, year_hint=2024, opening_balance=1_200_000)
    assert parsed["account"]["account_number"] == "1234567"
    assert parsed["account"]["bank_name"] == "みずほ銀行"
