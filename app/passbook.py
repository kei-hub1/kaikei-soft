"""通帳の入出金履歴テキストを解析して、仕訳の下書きを作る。

OCR でも手入力でも、同じ解析処理を通す。OCR は必ず誤読するため、ここでは
「確実に言えること」だけを判定し、怪しい行には issues を付けて画面で確認させる。

判定の考え方:
  - 通帳の各行は「日付 / 摘要 / 取引金額 / 差引残高」からなる。
  - OCR は列の空白を保てないため、金額と残高の区別は数値の並び順で行う
    (行の最後の数値を残高、その 1 つ前を取引金額とみなす)。
  - 入金か出金かは残高の増減で判定する。これは通帳自身が持つ検算情報なので、
    列の位置を読み違えても正しく判定できる。
  - 残高の増減と取引金額が一致しない行は issues を付ける。
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date

# 元号の開始年 (元年 = その年)
ERAS = {
    "令和": 2018, "令": 2018, "R": 2018, "r": 2018,
    "平成": 1988, "平": 1988, "H": 1988, "h": 1988,
    "昭和": 1925, "昭": 1925, "S": 1925, "s": 1925,
}

# 見出し行として読み飛ばす語
HEADER_WORDS = (
    "年月日", "お取引内容", "お引出", "お預入", "お支払金額", "お預り金額", "差引残高",
    "取引内容", "摘要", "残高", "支払金額", "預入金額", "入金額", "出金額", "備考",
)

# 入出金の向きを示す語 (残高から判定できないときの補助)
OUT_WORDS = ("お引出", "引出", "支払", "出金", "振込手数料", "ＡＴＭ出金", "カード", "引落", "自動払")
IN_WORDS = ("お預入", "預入", "入金", "振込", "給与", "利息", "配当")

_NUM_RE = re.compile(r"[¥\\]?\d{1,3}(?:,\d{3})+|\d+")


def normalize(text: str) -> str:
    """全角英数字・記号を半角に寄せ、OCR で紛れやすい文字を整える。"""
    t = unicodedata.normalize("NFKC", text)
    t = t.replace("−", "-").replace("ー", "-") if False else t   # 長音は摘要に必要なので変換しない
    return t


def _to_int(s: str) -> int:
    return int(re.sub(r"[^\d]", "", s) or 0)


def parse_date(token: str, year_hint: int | None = None) -> str | None:
    """通帳の日付表記を YYYY-MM-DD に直す。

    「令和6年4月1日」「R6.4.1」「6-04-01」「2026/4/1」「4/1」などに対応する。
    年が 1〜2 桁の場合は元号か西暦下 2 桁かを判別できないため、year_hint
    (会計期間の年) に最も近い解釈を採用する。
    """
    t = normalize(token).strip()
    if not t:
        return None
    hint = year_hint or date.today().year

    # 元号つき
    m = re.match(r"^\s*(令和|平成|昭和|令|平|昭|[RrHhSs])\s*(\d{1,2}|元)\s*[年.\-/]\s*(\d{1,2})\s*[月.\-/]\s*(\d{1,2})", t)
    if m:
        era, y, mo, d = m.group(1), m.group(2), int(m.group(3)), int(m.group(4))
        year = ERAS[era] + (1 if y == "元" else int(y))
        return _safe_date(year, mo, d)

    # 数字のみ
    m = re.match(r"^\s*(\d{1,4})\s*[年.\-/]\s*(\d{1,2})\s*[月.\-/]\s*(\d{1,2})", t)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if len(m.group(1)) == 4:
            return _safe_date(y, mo, d)
        # 1〜2 桁: 令和 / 平成 / 西暦下 2 桁 の候補から hint に最も近いものを選ぶ
        cands = [ERAS["令和"] + y, ERAS["平成"] + y, 2000 + y, 1900 + y]
        best = min((c for c in cands if 1950 <= c <= 2100), key=lambda c: abs(c - hint), default=None)
        return _safe_date(best, mo, d) if best else None

    # 月日のみ
    m = re.match(r"^\s*(\d{1,2})\s*[月.\-/]\s*(\d{1,2})\s*日?\s*$", t)
    if m:
        return _safe_date(hint, int(m.group(1)), int(m.group(2)))
    return None


def _safe_date(y: int | None, m: int, d: int) -> str | None:
    if y is None:
        return None
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


# 行頭の日付を取り出す正規表現 (parse_date が扱える形のうち、行頭に現れるもの)
_DATE_HEAD_RE = re.compile(
    r"^\s*((?:令和|平成|昭和|令|平|昭|[RrHhSs])?\s*(?:\d{1,4}|元)\s*[年.\-/]\s*\d{1,2}\s*[月.\-/]\s*\d{1,2}\s*日?)"
)


@dataclass
class PassbookRow:
    date: str | None = None
    description: str = ""
    amount: int | None = None
    balance: int | None = None
    direction: str | None = None          # 'in' 入金 / 'out' 出金
    issues: list[str] = field(default_factory=list)
    source_lines: list[str] = field(default_factory=list)
    values: list[int] = field(default_factory=list)   # 解析前の数値 (内部用)

    def to_dict(self) -> dict:
        return {
            "date": self.date, "description": self.description, "amount": self.amount,
            "balance": self.balance, "direction": self.direction,
            "issues": self.issues, "source": " / ".join(self.source_lines),
        }


def extract_account_info(text: str) -> dict:
    """通帳の見出しから銀行名・支店名・口座種別・口座番号を拾う。"""
    t = normalize(text)
    info: dict[str, str] = {}
    m = re.search(r"([\w぀-ヿ一-鿿]{2,10}(?:銀行|信用金庫|信用組合|信金|労働金庫|農業協同組合))", t)
    if m:
        info["bank_name"] = m.group(1)
    elif re.search(r"ゆうちょ|郵便局", t):
        info["bank_name"] = "ゆうちょ銀行"
    m = re.search(r"([\w぀-ヿ一-鿿]{1,10}(?:支店|出張所|営業部))", t)
    if m:
        info["branch_name"] = m.group(1)
    m = re.search(r"(普通|当座|貯蓄|総合)\s*(?:預金)?", t)
    if m:
        info["account_type"] = m.group(1)
    # 口座番号: 「口座番号」「No.」の後、または 普通/当座 の直後の 6〜8 桁
    for pat in (r"口座番号\s*[:：]?\s*(\d{6,8})",
                r"(?:No|NO|no)\s*[.．]?\s*[:：]?\s*(\d{6,8})",
                r"(?:普通|当座|貯蓄|総合)\s*(?:預金)?\s*[:：]?\s*(\d{6,8})",
                r"\b(\d{7})\b"):
        m = re.search(pat, t)
        if m:
            info["account_number"] = m.group(1)
            break
    m = re.search(r"店番\s*[:：]?\s*(\d{3})", t)
    if m:
        info["branch_number"] = m.group(1)
    return info


def _looks_like_header(line: str) -> bool:
    hits = sum(1 for w in HEADER_WORDS if w in line)
    return hits >= 2 or (hits >= 1 and not _NUM_RE.search(line))


def parse_passbook_text(text: str, year_hint: int | None = None,
                        opening_balance: int | None = None) -> dict:
    """通帳テキストを解析して行のリストを返す。"""
    raw_lines = [l for l in normalize(text).splitlines()]
    rows: list[PassbookRow] = []
    skipped: list[str] = []

    for raw in raw_lines:
        line = raw.strip()
        if not line:
            continue
        if _looks_like_header(line):
            skipped.append(line)
            continue

        m = _DATE_HEAD_RE.match(line)
        d = parse_date(m.group(1), year_hint) if m else None
        rest = line[m.end():] if m else line
        spans = [(mm.start(), mm.end(), _to_int(mm.group())) for mm in _NUM_RE.finditer(rest)]
        # 桁区切りがある、または 4 桁以上の数値を「金額らしい数値」とみなす。
        # 摘要に紛れる「4月分」のような数字と区別するために使う。
        money = [s for s in spans if "," in rest[s[0]:s[1]] or s[2] >= 1000]

        # 日付が読めなくても金額らしい数値が 2 つ並ぶ行は、独立した明細行とみなす
        if d is None and len(money) < 2:
            if not rows:
                # 最初の明細行より前は、銀行名や口座番号などの見出し
                skipped.append(line)
                continue
            prev = rows[-1]
            if not spans or len(prev.values) >= 2:
                # 数値が無い行、または直前の行に金額と残高が揃っている場合は摘要の折り返し
                prev.description = (prev.description + " " + line).strip()
                prev.source_lines.append(line)
                continue
            # 直前の行の数値が足りない場合は、続きの数値とみなす
            prev.values.extend(v for *_s, v in spans)
            prev.source_lines.append(line)
            continue

        # 摘要 = 金額として取り込んだ数値だけを取り除いた残り
        # (「4月分」のような摘要中の数字は残す)
        consumed = spans[-2:] if len(spans) >= 2 else spans[-1:]
        desc = rest
        for start, end, _v in reversed(consumed):
            desc = desc[:start] + " " + desc[end:]
        desc = re.sub(r"[¥\\*＊|｜=]+", " ", desc)
        desc = re.sub(r"\s+", " ", desc).strip(" -–—_")

        row = PassbookRow(date=d, description=desc, source_lines=[line],
                          values=[v for *_s, v in spans])
        if d is None:
            row.issues.append("日付を読み取れませんでした")
        rows.append(row)

    _resolve_values(rows, opening_balance)
    _infer_directions(rows, opening_balance)
    return {
        "rows": [r.to_dict() for r in rows],
        "account": extract_account_info(text),
        "skipped": skipped,
    }


def _resolve_values(rows: list[PassbookRow], opening_balance: int | None) -> None:
    """行から拾った数値を、取引金額と残高に割り当てる。

    通帳の各行は必ず残高を持つので、行の最後の数値を残高とみなすのが基本。
    数値が 1 つしか読めなかった行は、前行の残高と比べて残高らしいかを見る。
    数値が 3 つ以上ある行 (支払欄と預り欄を両方拾った場合) は、残高の増減と
    一致する数値を取引金額として採用する。
    """
    prev = opening_balance
    for r in rows:
        vals = r.values
        if not vals:
            pass
        elif len(vals) == 1:
            v = vals[0]
            # 残高は取引を挟んでも桁が大きく変わらない。前残高との差が
            # その数値自身より小さければ残高、そうでなければ取引金額とみなす。
            if prev is not None and v != prev and abs(v - prev) < v:
                r.balance = v
                r.amount = abs(v - prev)
                r.issues.append("金額欄を読み取れなかったため、残高の増減から金額を求めました")
            else:
                r.amount = v
                r.issues.append("残高を読み取れませんでした")
        else:
            r.balance = vals[-1]
            cands = vals[:-1]
            delta = abs(r.balance - prev) if prev is not None else None
            match = next((c for c in cands if delta is not None and c == delta), None)
            r.amount = match if match is not None else cands[-1]
        if r.balance is not None:
            prev = r.balance


def _infer_directions(rows: list[PassbookRow], opening_balance: int | None) -> None:
    """残高の増減から入金・出金を判定し、金額と合わない行に警告を付ける。"""
    prev = opening_balance
    for r in rows:
        if r.balance is not None and prev is not None:
            delta = r.balance - prev
            if delta > 0:
                r.direction = "in"
            elif delta < 0:
                r.direction = "out"
            else:
                r.issues.append("残高が変わっていません")
            if delta and r.amount is None:
                r.amount = abs(delta)
            elif delta and r.amount is not None and abs(delta) != r.amount:
                r.issues.append(f"残高の増減 {abs(delta):,} と金額 {r.amount:,} が一致しません")
        if r.direction is None:
            # 残高から判定できないときは摘要の語で推測する
            text = r.description
            if any(w in text for w in OUT_WORDS) and not any(w in text for w in IN_WORDS):
                r.direction = "out"
                r.issues.append("残高から判定できないため摘要から推測しました")
            elif any(w in text for w in IN_WORDS):
                r.direction = "in"
                r.issues.append("残高から判定できないため摘要から推測しました")
            else:
                r.issues.append("入金か出金かを判定できませんでした")
        if r.amount is None:
            r.issues.append("金額を読み取れませんでした")
        if r.balance is not None:
            prev = r.balance
