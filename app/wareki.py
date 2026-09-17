"""和暦（元号）の変換と、作成日入力の解析。"""

from __future__ import annotations

import datetime as dt
import re

# (元号, 略号, 開始日) 新しい順
_ERAS: tuple[tuple[str, str, dt.date], ...] = (
    ("令和", "R", dt.date(2019, 5, 1)),
    ("平成", "H", dt.date(1989, 1, 8)),
    ("昭和", "S", dt.date(1926, 12, 25)),
    ("大正", "T", dt.date(1912, 7, 30)),
    ("明治", "M", dt.date(1868, 1, 25)),
)

_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９／．－", "0123456789/.-")


def to_wareki(date: dt.date) -> str:
    """西暦の日付を「令和8年9月17日」形式にする。元年は「元年」と表記。"""
    for name, _abbr, start in _ERAS:
        if date >= start:
            year = date.year - start.year + 1
            year_label = "元" if year == 1 else str(year)
            return f"{name}{year_label}年{date.month}月{date.day}日"
    # 明治より前は西暦のまま
    return f"{date.year}年{date.month}月{date.day}日"


def parse_date(text: str) -> dt.date | None:
    """作成日の入力を解析する。解釈できなければ None。

    受け付ける形式の例:
      2026/9/17  2026-09-17  2026.9.17  20260917
      令和8年9月17日  令和元年5月1日  R8/9/17  R8.9.17
    """
    s = (text or "").strip().translate(_FULLWIDTH_DIGITS)
    if not s:
        return None

    m = re.fullmatch(r"(\d{4})[/.\-年](\d{1,2})[/.\-月](\d{1,2})日?", s)
    if m:
        return _safe_date(int(m[1]), int(m[2]), int(m[3]))

    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", s)
    if m:
        return _safe_date(int(m[1]), int(m[2]), int(m[3]))

    m = re.fullmatch(
        r"(令和|平成|昭和|大正|明治|[RHSTMrhstm])\s*(元|\d{1,2})[/.\-年](\d{1,2})[/.\-月](\d{1,2})日?",
        s,
    )
    if m:
        era_key = m[1].upper()
        year = 1 if m[2] == "元" else int(m[2])
        for name, abbr, start in _ERAS:
            if era_key in (name, abbr):
                return _safe_date(start.year + year - 1, int(m[3]), int(m[4]))
    return None


def _safe_date(y: int, m: int, d: int) -> dt.date | None:
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None
