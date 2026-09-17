"""アプリで扱うデータ構造（顧客・差出人・文書種類・文例・文書作成依頼）。"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

DEFAULT_OPENING = "拝啓"
DEFAULT_CLOSING = "敬具"
HONORIFIC_CHOICES = ("様", "御中", "殿", "先生")


@dataclass
class Customer:
    """顧客名簿の1件。空欄の項目は文書に出力されない。"""

    id: int | None = None
    company: str = ""  # 会社名
    department: str = ""  # 部署名
    name: str = ""  # 氏名
    honorific: str = "様"  # 敬称
    postal: str = ""  # 郵便番号
    address1: str = ""  # 住所1
    address2: str = ""  # 住所2

    @property
    def display_name(self) -> str:
        """一覧やファイル名に使う代表名（会社名があれば会社名、なければ氏名）。"""
        return (self.company or self.name).strip()

    @property
    def salutation(self) -> str:
        """{宛名} に差し込む文字列（氏名があれば氏名＋敬称、なければ会社名＋敬称）。"""
        base = self.name.strip() or self.company.strip()
        if not base:
            return ""
        return f"{base}{_sep(self.honorific)}"

    def address_lines(self) -> list[str]:
        """文書の宛先ブロックに出力する行（空欄は除外）。"""
        lines: list[str] = []
        if self.postal.strip():
            lines.append(_format_postal(self.postal))
        if self.address1.strip():
            lines.append(self.address1.strip())
        if self.address2.strip():
            lines.append(self.address2.strip())

        company_line = "　".join(
            s for s in (self.company.strip(), self.department.strip()) if s
        )
        honorific = self.honorific.strip()
        if self.name.strip():
            if company_line:
                lines.append(company_line)
            lines.append(f"{self.name.strip()}{_sep(honorific)}")
        elif company_line:
            lines.append(f"{company_line}{_sep(honorific)}")
        return lines


@dataclass
class Sender:
    """差出人（事務所）情報。登録された項目のみ文書に出力する。"""

    office: str = ""  # 事務所名
    accountant: str = ""  # 税理士名
    postal: str = ""  # 郵便番号
    address: str = ""  # 住所
    tel: str = ""  # 電話番号
    fax: str = ""  # FAX番号
    email: str = ""  # メールアドレス
    staff: str = ""  # 担当者名

    def lines(self) -> list[str]:
        """文書の差出人ブロックに出力する行（空欄は除外）。"""
        lines: list[str] = []
        if self.office.strip():
            lines.append(self.office.strip())
        if self.accountant.strip():
            name = self.accountant.strip()
            lines.append(name if "税理士" in name else f"税理士　{name}")
        if self.postal.strip():
            lines.append(_format_postal(self.postal))
        if self.address.strip():
            lines.append(self.address.strip())
        contact = "　".join(
            s
            for s in (
                f"TEL：{self.tel.strip()}" if self.tel.strip() else "",
                f"FAX：{self.fax.strip()}" if self.fax.strip() else "",
            )
            if s
        )
        if contact:
            lines.append(contact)
        if self.email.strip():
            lines.append(f"E-mail：{self.email.strip()}")
        if self.staff.strip():
            lines.append(f"担当：{self.staff.strip()}")
        return lines


@dataclass
class DocType:
    """文書の種類（送付状・案内文など）。画面から自由に追加できる。"""

    id: int | None = None
    name: str = ""
    sort_order: int = 0


@dataclass
class Enclosure:
    """記書きに載せる書類1件（書類名と部数）。"""

    title: str = ""
    quantity: str = ""

    @property
    def quantity_label(self) -> str:
        """数字だけなら「部」を補う。「一式」などはそのまま。"""
        q = self.quantity.strip()
        if q and q.isdigit():
            return f"{q}部"
        return q

    @property
    def is_blank(self) -> bool:
        return not self.title.strip()


@dataclass
class Template:
    """文例。件名・本文のほか、頭語・結語や記書きの初期値も持つ。"""

    id: int | None = None
    name: str = ""  # 文例名
    doc_type_id: int | None = None  # 文書の種類
    subject: str = ""  # 件名
    body: str = ""  # 本文（頭語・結語を除く）
    has_notes: bool = False  # 記書きの初期値
    opening: str = DEFAULT_OPENING  # 頭語
    closing: str = DEFAULT_CLOSING  # 結語
    default_enclosures: str = ""  # 書類一覧の初期値（1行1件「書類名,部数」）
    sort_order: int = 0

    def enclosures(self) -> list[Enclosure]:
        return parse_enclosure_text(self.default_enclosures)


def parse_enclosure_text(text: str) -> list[Enclosure]:
    """「書類名,部数」形式（区切りはタブ・カンマ・読点のいずれか）の複数行を解析する。"""
    result: list[Enclosure] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        title, qty = line, ""
        for sep in ("\t", ",", "，", "、"):
            if sep in line:
                title, qty = line.split(sep, 1)
                break
        result.append(Enclosure(title=title.strip(), quantity=qty.strip()))
    return result


@dataclass
class DocumentRequest:
    """メイン画面の入力内容をまとめた「文書作成の依頼」。"""

    customer: Customer
    sender: Sender
    created_on: dt.date
    subject: str
    body: str
    has_notes: bool = False
    enclosures: list[Enclosure] = field(default_factory=list)
    opening: str = DEFAULT_OPENING
    closing: str = DEFAULT_CLOSING

    def active_enclosures(self) -> list[Enclosure]:
        return [e for e in self.enclosures if not e.is_blank]


@dataclass
class DocumentResult:
    """文書作成の結果。PDF 変換に失敗しても Word ファイルは残す。"""

    docx_path: object  # pathlib.Path
    pdf_path: object | None = None
    pdf_error: str | None = None
    pdf_method: str | None = None

    @property
    def pdf_ok(self) -> bool:
        return self.pdf_path is not None and self.pdf_error is None


def _sep(honorific: str) -> str:
    """敬称の前に全角スペースを入れる（敬称が空なら何も付けない）。"""
    h = (honorific or "").strip()
    return f"　{h}" if h else ""


def _format_postal(postal: str) -> str:
    p = postal.strip()
    return p if p.startswith("〒") else f"〒{p}"
