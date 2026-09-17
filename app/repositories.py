"""DB への読み書き（顧客名簿・差出人・文書種類・文例・設定）。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from . import paths
from .models import Customer, DocType, Sender, Template


class RepositoryError(Exception):
    """利用者に表示できる、データ操作上のエラー。"""


def _row_to_customer(row: sqlite3.Row) -> Customer:
    return Customer(
        id=row["id"],
        company=row["company"],
        department=row["department"],
        name=row["name"],
        honorific=row["honorific"],
        postal=row["postal"],
        address1=row["address1"],
        address2=row["address2"],
    )


def _row_to_template(row: sqlite3.Row) -> Template:
    return Template(
        id=row["id"],
        name=row["name"],
        doc_type_id=row["doc_type_id"],
        subject=row["subject"],
        body=row["body"],
        has_notes=bool(row["has_notes"]),
        opening=row["opening"],
        closing=row["closing"],
        default_enclosures=row["default_enclosures"],
        sort_order=row["sort_order"],
    )


class CustomerRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def list(self, keyword: str = "") -> list[Customer]:
        """名前の一部で検索。空文字なら全件。会社名・氏名・部署名を対象にする。"""
        kw = (keyword or "").strip()
        if kw:
            like = f"%{kw}%"
            rows = self.conn.execute(
                """SELECT * FROM customers
                   WHERE company LIKE ? OR name LIKE ? OR department LIKE ?
                   ORDER BY company, name""",
                (like, like, like),
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM customers ORDER BY company, name").fetchall()
        return [_row_to_customer(r) for r in rows]

    def get(self, customer_id: int) -> Customer | None:
        row = self.conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
        return _row_to_customer(row) if row else None

    def save(self, c: Customer) -> Customer:
        if not (c.company.strip() or c.name.strip()):
            raise RepositoryError("会社名または氏名のどちらかは入力してください。")
        values = (
            c.company.strip(),
            c.department.strip(),
            c.name.strip(),
            c.honorific.strip(),
            c.postal.strip(),
            c.address1.strip(),
            c.address2.strip(),
        )
        if c.id is None:
            cur = self.conn.execute(
                """INSERT INTO customers
                   (company, department, name, honorific, postal, address1, address2)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                values,
            )
            c.id = cur.lastrowid
        else:
            self.conn.execute(
                """UPDATE customers SET company=?, department=?, name=?, honorific=?,
                   postal=?, address1=?, address2=?, updated_at=datetime('now','localtime')
                   WHERE id=?""",
                values + (c.id,),
            )
        self.conn.commit()
        return c

    def delete(self, customer_id: int) -> None:
        self.conn.execute("DELETE FROM customers WHERE id = ?", (customer_id,))
        self.conn.commit()


class SenderRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get(self) -> Sender:
        row = self.conn.execute("SELECT * FROM sender WHERE id = 1").fetchone()
        if row is None:
            return Sender()
        return Sender(
            office=row["office"],
            accountant=row["accountant"],
            postal=row["postal"],
            address=row["address"],
            tel=row["tel"],
            fax=row["fax"],
            email=row["email"],
            staff=row["staff"],
        )

    def save(self, s: Sender) -> None:
        self.conn.execute(
            """INSERT INTO sender (id, office, accountant, postal, address, tel, fax, email, staff)
               VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 office=excluded.office, accountant=excluded.accountant,
                 postal=excluded.postal, address=excluded.address,
                 tel=excluded.tel, fax=excluded.fax,
                 email=excluded.email, staff=excluded.staff""",
            (
                s.office.strip(),
                s.accountant.strip(),
                s.postal.strip(),
                s.address.strip(),
                s.tel.strip(),
                s.fax.strip(),
                s.email.strip(),
                s.staff.strip(),
            ),
        )
        self.conn.commit()


class DocTypeRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def list(self) -> list[DocType]:
        rows = self.conn.execute("SELECT * FROM doc_types ORDER BY sort_order, id").fetchall()
        return [DocType(id=r["id"], name=r["name"], sort_order=r["sort_order"]) for r in rows]

    def get(self, doc_type_id: int) -> DocType | None:
        row = self.conn.execute("SELECT * FROM doc_types WHERE id = ?", (doc_type_id,)).fetchone()
        return DocType(id=row["id"], name=row["name"], sort_order=row["sort_order"]) if row else None

    def add(self, name: str) -> DocType:
        name = (name or "").strip()
        if not name:
            raise RepositoryError("種類の名前を入力してください。")
        if self.conn.execute("SELECT 1 FROM doc_types WHERE name = ?", (name,)).fetchone():
            raise RepositoryError(f"「{name}」はすでに登録されています。")
        max_order = self.conn.execute("SELECT COALESCE(MAX(sort_order), 0) FROM doc_types").fetchone()[0]
        cur = self.conn.execute(
            "INSERT INTO doc_types (name, sort_order) VALUES (?, ?)", (name, max_order + 1)
        )
        self.conn.commit()
        return DocType(id=cur.lastrowid, name=name, sort_order=max_order + 1)

    def rename(self, doc_type_id: int, name: str) -> None:
        name = (name or "").strip()
        if not name:
            raise RepositoryError("種類の名前を入力してください。")
        dup = self.conn.execute(
            "SELECT 1 FROM doc_types WHERE name = ? AND id <> ?", (name, doc_type_id)
        ).fetchone()
        if dup:
            raise RepositoryError(f"「{name}」はすでに登録されています。")
        self.conn.execute("UPDATE doc_types SET name = ? WHERE id = ?", (name, doc_type_id))
        self.conn.commit()

    def delete(self, doc_type_id: int) -> None:
        used = self.conn.execute(
            "SELECT COUNT(*) FROM templates WHERE doc_type_id = ?", (doc_type_id,)
        ).fetchone()[0]
        if used:
            raise RepositoryError(
                f"この種類は {used} 件の文例で使われているため削除できません。\n"
                "先に文例の種類を変更するか、文例を削除してください。"
            )
        self.conn.execute("DELETE FROM doc_types WHERE id = ?", (doc_type_id,))
        self.conn.commit()


class TemplateRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def list(self, doc_type_id: int | None = None) -> list[Template]:
        if doc_type_id is None:
            rows = self.conn.execute(
                """SELECT t.* FROM templates t
                   LEFT JOIN doc_types d ON d.id = t.doc_type_id
                   ORDER BY d.sort_order, t.sort_order, t.id"""
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM templates WHERE doc_type_id = ? ORDER BY sort_order, id",
                (doc_type_id,),
            ).fetchall()
        return [_row_to_template(r) for r in rows]

    def get(self, template_id: int) -> Template | None:
        row = self.conn.execute("SELECT * FROM templates WHERE id = ?", (template_id,)).fetchone()
        return _row_to_template(row) if row else None

    def save(self, t: Template) -> Template:
        if not t.name.strip():
            raise RepositoryError("文例名を入力してください。")
        if t.doc_type_id is None:
            raise RepositoryError("文書の種類を選択してください。")
        values = (
            t.name.strip(),
            t.doc_type_id,
            t.subject.strip(),
            t.body.strip("\n"),
            1 if t.has_notes else 0,
            t.opening.strip(),
            t.closing.strip(),
            t.default_enclosures.strip("\n"),
        )
        if t.id is None:
            max_order = self.conn.execute(
                "SELECT COALESCE(MAX(sort_order), 0) FROM templates"
            ).fetchone()[0]
            cur = self.conn.execute(
                """INSERT INTO templates
                   (name, doc_type_id, subject, body, has_notes, opening, closing,
                    default_enclosures, sort_order)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                values + (max_order + 1,),
            )
            t.id = cur.lastrowid
            t.sort_order = max_order + 1
        else:
            self.conn.execute(
                """UPDATE templates SET name=?, doc_type_id=?, subject=?, body=?, has_notes=?,
                   opening=?, closing=?, default_enclosures=? WHERE id=?""",
                values + (t.id,),
            )
        self.conn.commit()
        return t

    def delete(self, template_id: int) -> None:
        self.conn.execute("DELETE FROM templates WHERE id = ?", (template_id,))
        self.conn.commit()


class SettingsRepository:
    OUTPUT_DIR = "output_dir"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get(self, key: str, default: str = "") -> str:
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self.conn.commit()

    def output_dir(self) -> Path:
        value = self.get(self.OUTPUT_DIR).strip()
        return Path(value) if value else paths.DEFAULT_OUTPUT_DIR

    def set_output_dir(self, directory: str | Path) -> None:
        self.set(self.OUTPUT_DIR, str(directory))


class Repositories:
    """すべてのリポジトリをまとめた入れ物。画面からはこれを通して DB を使う。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.customers = CustomerRepository(conn)
        self.sender = SenderRepository(conn)
        self.doc_types = DocTypeRepository(conn)
        self.templates = TemplateRepository(conn)
        self.settings = SettingsRepository(conn)

    def close(self) -> None:
        self.conn.close()
