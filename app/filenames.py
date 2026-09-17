"""出力ファイル名の生成（使えない文字の置換・同名ファイルの連番付け）。"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

# Windows でファイル名に使えない文字は、読みやすさを保つため全角の同形文字に置き換える
_REPLACEMENTS = str.maketrans(
    {
        "\\": "＼",
        "/": "／",
        ":": "：",
        "*": "＊",
        "?": "？",
        '"': "”",
        "<": "＜",
        ">": "＞",
        "|": "｜",
    }
)
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_MAX_PART_LEN = 40


def sanitize_part(text: str, max_len: int = _MAX_PART_LEN) -> str:
    """ファイル名の一部として安全な文字列にする。"""
    s = (text or "").strip().translate(_REPLACEMENTS)
    s = _CONTROL_CHARS.sub("", s)
    s = re.sub(r"[ \t]+", " ", s).strip(" .")  # 全角スペースは氏名などで使うので残す
    if len(s) > max_len:
        s = s[:max_len].rstrip(" .")
    return s or "無題"


def build_stem(created_on: dt.date, recipient: str, subject: str) -> str:
    """「作成日(YYYYMMDD)_宛先名_件名」の拡張子なしファイル名を作る。"""
    return "_".join(
        (created_on.strftime("%Y%m%d"), sanitize_part(recipient), sanitize_part(subject))
    )


def unique_stem(directory: Path, stem: str, extensions: tuple[str, ...] = (".docx", ".pdf")) -> str:
    """指定フォルダで、どの拡張子でも未使用となる名前を返す。使用中なら末尾に連番を付ける。"""

    def taken(candidate: str) -> bool:
        return any((directory / f"{candidate}{ext}").exists() for ext in extensions)

    if not taken(stem):
        return stem
    n = 2
    while taken(f"{stem}_{n}"):
        n += 1
    return f"{stem}_{n}"
