"""差し込み記号（{宛名} など）の定義と置き換え。

新しい差し込み記号を増やしたいときは ``PLACEHOLDERS`` に1行追加するだけでよい。
文例管理画面の説明文もこの一覧から自動生成される。
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Callable

from .models import Customer, Sender
from .wareki import to_wareki


@dataclass(frozen=True)
class Placeholder:
    token: str  # 例: "{宛名}"
    description: str
    resolve: Callable[["PlaceholderContext"], str]


@dataclass
class PlaceholderContext:
    customer: Customer
    sender: Sender
    created_on: dt.date


PLACEHOLDERS: tuple[Placeholder, ...] = (
    Placeholder("{宛名}", "宛先の氏名＋敬称（氏名がなければ会社名＋敬称）", lambda c: c.customer.salutation),
    Placeholder("{会社名}", "宛先の会社名", lambda c: c.customer.company.strip()),
    Placeholder("{氏名}", "宛先の氏名", lambda c: c.customer.name.strip()),
    Placeholder("{作成日}", "作成日（和暦）", lambda c: to_wareki(c.created_on)),
    Placeholder("{事務所名}", "差出人の事務所名", lambda c: c.sender.office.strip()),
    Placeholder("{税理士名}", "差出人の税理士名", lambda c: c.sender.accountant.strip()),
    Placeholder("{担当者名}", "差出人の担当者名", lambda c: c.sender.staff.strip()),
)

# 全角の波かっこで書かれても認識できるようにする
_FULLWIDTH_BRACES = str.maketrans("｛｝", "{}")
_TOKEN_RE = re.compile(r"\{[^{}]+\}")


def render(text: str, ctx: PlaceholderContext) -> str:
    """文字列中の差し込み記号を置き換える。未知の記号はそのまま残す。"""
    if not text:
        return ""
    table = {p.token: p.resolve(ctx) for p in PLACEHOLDERS}
    normalized = text.translate(_FULLWIDTH_BRACES)
    return _TOKEN_RE.sub(lambda m: table.get(m.group(0), m.group(0)), normalized)


def unknown_tokens(text: str) -> list[str]:
    """文中にある、定義されていない差し込み記号を返す（入力チェック用）。"""
    known = {p.token for p in PLACEHOLDERS}
    found = _TOKEN_RE.findall((text or "").translate(_FULLWIDTH_BRACES))
    return sorted({t for t in found if t not in known})


def help_text() -> str:
    """文例管理画面に表示する差し込み記号の説明。"""
    return "\n".join(f"{p.token}　{p.description}" for p in PLACEHOLDERS)
