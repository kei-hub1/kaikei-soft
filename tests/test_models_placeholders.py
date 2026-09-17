import datetime as dt
import unittest

from app.models import Customer, Enclosure, Sender, parse_enclosure_text
from app.placeholders import PlaceholderContext, help_text, render, unknown_tokens


class CustomerTest(unittest.TestCase):
    def test_full_address(self):
        c = Customer(company="株式会社A", department="経理部", name="鈴木 一郎", honorific="様",
                     postal="100-0001", address1="東京都千代田区1-1", address2="Bビル3階")
        self.assertEqual(
            c.address_lines(),
            ["〒100-0001", "東京都千代田区1-1", "Bビル3階", "株式会社A　経理部", "鈴木 一郎　様"],
        )
        self.assertEqual(c.salutation, "鈴木 一郎　様")
        self.assertEqual(c.display_name, "株式会社A")

    def test_company_only_gets_honorific(self):
        c = Customer(company="有限会社B", honorific="御中", postal="〒150-0001")
        self.assertEqual(c.address_lines(), ["〒150-0001", "有限会社B　御中"])
        self.assertEqual(c.salutation, "有限会社B　御中")

    def test_name_only(self):
        c = Customer(name="山本 花子", honorific="様")
        self.assertEqual(c.address_lines(), ["山本 花子　様"])
        self.assertEqual(c.display_name, "山本 花子")

    def test_blank_fields_produce_no_lines(self):
        c = Customer(name="山本 花子", honorific="", postal="  ", address1="", address2="")
        self.assertEqual(c.address_lines(), ["山本 花子"])


class SenderTest(unittest.TestCase):
    def test_only_registered_items(self):
        s = Sender(office="吉川和章税理士事務所")
        self.assertEqual(s.lines(), ["吉川和章税理士事務所"])

    def test_all_items(self):
        s = Sender(office="事務所", accountant="吉川 和章", postal="100-0001", address="東京都",
                   tel="03-1", fax="03-2", email="a@b.c", staff="山田")
        self.assertEqual(
            s.lines(),
            ["事務所", "税理士　吉川 和章", "〒100-0001", "東京都", "TEL：03-1　FAX：03-2", "E-mail：a@b.c", "担当：山田"],
        )

    def test_accountant_prefix_not_duplicated(self):
        self.assertEqual(Sender(accountant="税理士 吉川 和章").lines(), ["税理士 吉川 和章"])

    def test_fax_only(self):
        self.assertEqual(Sender(fax="03-2").lines(), ["FAX：03-2"])


class EnclosureTest(unittest.TestCase):
    def test_quantity_label(self):
        self.assertEqual(Enclosure("a", "1").quantity_label, "1部")
        self.assertEqual(Enclosure("a", "一式").quantity_label, "一式")
        self.assertEqual(Enclosure("a", "").quantity_label, "")

    def test_parse_enclosure_text(self):
        items = parse_enclosure_text("決算報告書,1\n申告書（控）\t2\n元帳、一式\n\n 総括表，3 ")
        self.assertEqual(
            [(e.title, e.quantity) for e in items],
            [("決算報告書", "1"), ("申告書（控）", "2"), ("元帳", "一式"), ("総括表", "3")],
        )


class PlaceholderTest(unittest.TestCase):
    def setUp(self):
        self.ctx = PlaceholderContext(
            customer=Customer(company="株式会社A", name="鈴木 一郎", honorific="様"),
            sender=Sender(office="吉川和章税理士事務所", accountant="吉川 和章", staff="山田"),
            created_on=dt.date(2026, 9, 17),
        )

    def test_render_all(self):
        text = "{宛名}/{会社名}/{氏名}/{作成日}/{事務所名}/{税理士名}/{担当者名}"
        self.assertEqual(
            render(text, self.ctx),
            "鈴木 一郎　様/株式会社A/鈴木 一郎/令和8年9月17日/吉川和章税理士事務所/吉川 和章/山田",
        )

    def test_fullwidth_braces(self):
        self.assertEqual(render("｛作成日｝", self.ctx), "令和8年9月17日")

    def test_unknown_token_kept(self):
        self.assertEqual(render("{不明}", self.ctx), "{不明}")
        self.assertEqual(unknown_tokens("{宛名} {不明} {謎}"), ["{不明}", "{謎}"])

    def test_help_text_lists_all(self):
        self.assertIn("{宛名}", help_text())
        self.assertIn("{作成日}", help_text())


if __name__ == "__main__":
    unittest.main()
