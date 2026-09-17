import unittest

from app import db
from app.models import Customer, Sender, Template
from app.repositories import Repositories, RepositoryError


class RepositoryTest(unittest.TestCase):
    def setUp(self):
        self.repos = Repositories(db.connect(":memory:"))

    def tearDown(self):
        self.repos.close()

    # -- 初期データ ---------------------------------------------------------

    def test_seed_data(self):
        self.assertEqual(self.repos.sender.get().office, "吉川和章税理士事務所")
        self.assertEqual([d.name for d in self.repos.doc_types.list()], ["送付状", "案内文"])
        templates = self.repos.templates.list()
        self.assertEqual([t.name for t in templates], ["資料送付のご案内", "書類ご送付のお願い", "お知らせ"])
        self.assertEqual([t.has_notes for t in templates], [True, True, False])
        for t in templates:
            self.assertNotIn("拝啓", t.body)
            self.assertNotIn("敬具", t.body)
            self.assertEqual((t.opening, t.closing), ("拝啓", "敬具"))

    def test_initialize_is_idempotent(self):
        db.initialize(self.repos.conn)
        self.assertEqual(len(self.repos.templates.list()), 3)

    # -- 顧客 -----------------------------------------------------------------

    def test_customer_crud_and_search(self):
        c = self.repos.customers.save(Customer(company="株式会社サンプル", name="鈴木"))
        self.assertIsNotNone(c.id)
        self.repos.customers.save(Customer(name="山本 花子"))
        self.assertEqual(len(self.repos.customers.list()), 2)
        self.assertEqual([x.company for x in self.repos.customers.list("サンプル")], ["株式会社サンプル"])
        self.assertEqual([x.name for x in self.repos.customers.list("花子")], ["山本 花子"])

        c.department = "経理部"
        self.repos.customers.save(c)
        self.assertEqual(self.repos.customers.get(c.id).department, "経理部")

        self.repos.customers.delete(c.id)
        self.assertIsNone(self.repos.customers.get(c.id))
        self.assertEqual(len(self.repos.customers.list()), 1)

    def test_customer_requires_company_or_name(self):
        with self.assertRaises(RepositoryError):
            self.repos.customers.save(Customer(postal="100-0001"))

    # -- 差出人 ---------------------------------------------------------------

    def test_sender_save(self):
        self.repos.sender.save(Sender(office="事務所", accountant="吉川", tel="03"))
        s = self.repos.sender.get()
        self.assertEqual((s.office, s.accountant, s.tel, s.fax), ("事務所", "吉川", "03", ""))

    # -- 種類・文例 -------------------------------------------------------------

    def test_doc_type_add_rename_delete(self):
        d = self.repos.doc_types.add("挨拶状")
        self.assertEqual([x.name for x in self.repos.doc_types.list()], ["送付状", "案内文", "挨拶状"])
        with self.assertRaises(RepositoryError):
            self.repos.doc_types.add("挨拶状")
        self.repos.doc_types.rename(d.id, "ご挨拶")
        self.assertEqual(self.repos.doc_types.get(d.id).name, "ご挨拶")
        self.repos.doc_types.delete(d.id)
        self.assertIsNone(self.repos.doc_types.get(d.id))

    def test_doc_type_in_use_cannot_be_deleted(self):
        used = self.repos.doc_types.list()[0]
        with self.assertRaises(RepositoryError):
            self.repos.doc_types.delete(used.id)

    def test_template_crud(self):
        type_id = self.repos.doc_types.list()[1].id
        t = self.repos.templates.save(Template(
            name="新文例", doc_type_id=type_id, subject="件名", body="本文\n2行目",
            has_notes=True, opening="", closing="", default_enclosures="書類A,1",
        ))
        self.assertIsNotNone(t.id)
        loaded = self.repos.templates.get(t.id)
        self.assertEqual(loaded.body, "本文\n2行目")
        self.assertEqual((loaded.opening, loaded.closing), ("", ""))
        self.assertEqual([(e.title, e.quantity) for e in loaded.enclosures()], [("書類A", "1")])
        self.assertEqual([x.name for x in self.repos.templates.list(type_id)], ["お知らせ", "新文例"])

        loaded.subject = "変更"
        self.repos.templates.save(loaded)
        self.assertEqual(self.repos.templates.get(t.id).subject, "変更")

        self.repos.templates.delete(t.id)
        self.assertIsNone(self.repos.templates.get(t.id))

    def test_template_requires_name_and_type(self):
        with self.assertRaises(RepositoryError):
            self.repos.templates.save(Template(name="", doc_type_id=1))
        with self.assertRaises(RepositoryError):
            self.repos.templates.save(Template(name="x", doc_type_id=None))

    # -- 設定 -------------------------------------------------------------------

    def test_settings_output_dir(self):
        self.repos.settings.set_output_dir("C:/out")
        self.assertEqual(str(self.repos.settings.output_dir()).replace("\\", "/"), "C:/out")


if __name__ == "__main__":
    unittest.main()
