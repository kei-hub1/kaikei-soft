import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ronten.db import Database, NotFound, ValidationError, normalize_tags  # noqa: E402


class DbTest(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.c1 = self.db.create_client({"name": "株式会社アルファ", "kana": "あるふぁ", "code": "A001", "fiscal_month": 3})
        self.c2 = self.db.create_client({"name": "ベータ商事株式会社", "kana": "べーた", "code": "B002", "fiscal_month": 9})

    def tearDown(self):
        self.db.close()

    def test_fts_available(self):
        self.assertTrue(self.db.fts_enabled)

    def test_client_validation(self):
        with self.assertRaises(ValidationError):
            self.db.create_client({"name": ""})
        with self.assertRaises(ValidationError):
            self.db.create_client({"name": "x", "fiscal_month": 13})
        with self.assertRaises(NotFound):
            self.db.get_client(999)

    def test_issue_crud_and_tags(self):
        it = self.db.create_issue({
            "client_id": self.c1["id"], "title": "役員退職金の損金算入", "tax_type": "法人税",
            "fiscal_year": "2026年3月期", "tags": "役員退職金, 功績倍率 功績倍率", "conclusion": "功績倍率3.0で妥当",
        })
        self.assertEqual(it["tags"], sorted(["役員退職金", "功績倍率"]))
        self.assertEqual(it["status"], "検討中")
        upd = self.db.update_issue(it["id"], dict(it, status="結論済", tags=["役員退職金"], conclusion="功績倍率2.5に修正"))
        self.assertEqual(upd["status"], "結論済")
        self.assertEqual(upd["tags"], ["役員退職金"])
        # 使われなくなったタグは消える
        self.assertEqual([t["name"] for t in self.db.meta()["tags"]], ["役員退職金"])
        revs = self.db.list_revisions(it["id"])
        self.assertEqual(len(revs), 1)
        self.assertEqual(revs[0]["data"]["conclusion"], "功績倍率3.0で妥当")
        self.assertEqual(revs[0]["data"]["tags"], sorted(["役員退職金", "功績倍率"]))
        self.db.delete_issue(it["id"])
        with self.assertRaises(NotFound):
            self.db.get_issue(it["id"])
        self.assertEqual(self.db.meta()["tags"], [])

    def test_issue_validation(self):
        with self.assertRaises(ValidationError):
            self.db.create_issue({"client_id": self.c1["id"], "title": ""})
        with self.assertRaises(ValidationError):
            self.db.create_issue({"client_id": 999, "title": "x"})
        with self.assertRaises(ValidationError):
            self.db.create_issue({"client_id": self.c1["id"], "title": "x", "status": "不明"})

    def _seed_search(self):
        self.db.create_issue({
            "client_id": self.c1["id"], "title": "インボイス制度 免税事業者からの仕入れ", "tax_type": "消費税",
            "fiscal_year": "2025年3月期", "analysis": "経過措置により80%控除可能", "tags": ["インボイス", "経過措置"],
        })
        self.db.create_issue({
            "client_id": self.c2["id"], "title": "役員退職金の損金算入額", "tax_type": "法人税",
            "fiscal_year": "2025年9月期", "status": "結論済", "conclusion": "功績倍率法により算定", "followup": "翌期に分掌変更の有無を確認",
        })
        self.db.create_issue({
            "client_id": self.c2["id"], "title": "簡易課税の選択", "tax_type": "消費税",
            "fiscal_year": "2026年9月期", "question": "インボイス登録後の簡易課税選択届出の期限",
        })

    def test_search_fts(self):
        self._seed_search()
        r = self.db.list_issues(q="インボイス")
        self.assertTrue(r["fts"])
        self.assertEqual(r["total"], 2)
        self.assertTrue(all("[[" in (i["snippet"] or "") for i in r["items"]))
        # 複数語は AND
        r = self.db.list_issues(q="インボイス 簡易課税")
        self.assertEqual([i["title"] for i in r["items"]], ["簡易課税の選択"])
        # 顧問先名でもヒット
        r = self.db.list_issues(q="ベータ商事")
        self.assertEqual(r["total"], 2)
        # タグでもヒット
        r = self.db.list_issues(q="経過措置")
        self.assertEqual(r["total"], 1)

    def test_search_short_term_like(self):
        self._seed_search()
        r = self.db.list_issues(q="退職")
        self.assertFalse(r["fts"])
        self.assertEqual(r["total"], 1)
        self.assertIsNone(r["items"][0]["snippet"])
        # 短い語と長い語の混在
        r = self.db.list_issues(q="消費 インボイス")
        self.assertEqual(r["total"], 2)

    def test_filters(self):
        self._seed_search()
        self.assertEqual(self.db.list_issues(tax_type="消費税")["total"], 2)
        self.assertEqual(self.db.list_issues(client_id=self.c2["id"])["total"], 2)
        self.assertEqual(self.db.list_issues(status="結論済")["total"], 1)
        self.assertEqual(self.db.list_issues(fiscal_year="2026年9月期")["total"], 1)
        self.assertEqual(self.db.list_issues(tag="経過措置")["total"], 1)
        # 要フォロー: 検討中 or 要再検討 or 留意点あり → 全件該当
        self.assertEqual(self.db.list_issues(open_only=True)["total"], 3)
        self.assertEqual(self.db.list_issues(open_only=True, status="結論済")["total"], 1)
        c2 = self.db.get_client(self.c2["id"])
        self.assertEqual(c2["issue_count"], 2)
        self.assertEqual(c2["open_count"], 2)

    def test_client_rename_reindexes(self):
        self._seed_search()
        self.db.update_client(self.c1["id"], dict(self.c1, name="ガンマ工業株式会社"))
        self.assertEqual(self.db.list_issues(q="ガンマ工業")["total"], 1)
        self.assertEqual(self.db.list_issues(q="アルファ")["total"], 0)

    def test_similar(self):
        self._seed_search()
        ids = {i["title"]: i["id"] for i in self.db.list_issues()["items"]}
        sim = self.db.similar_issues(ids["簡易課税の選択"])
        titles = [s["title"] for s in sim]
        self.assertIn("インボイス制度 免税事業者からの仕入れ", titles)
        self.assertNotIn("簡易課税の選択", titles)

    def test_delete_client_cascades(self):
        self._seed_search()
        self.db.delete_client(self.c2["id"])
        self.assertEqual(self.db.list_issues()["total"], 1)
        self.assertEqual(self.db.list_issues(q="役員退職金")["total"], 0)

    def test_export_import(self):
        self._seed_search()
        data = self.db.export_data()
        self.assertEqual(len(data["issues"]), 3)
        other = Database(":memory:")
        try:
            r = other.import_data(data)
            self.assertEqual(r, {"clients_created": 2, "issues_created": 3})
            self.assertEqual(other.list_issues(q="インボイス")["total"], 2)
            # 再取込: 顧問先は既存に紐付き、論点は追加される
            r = other.import_data(data)
            self.assertEqual(r["clients_created"], 0)
            self.assertEqual(other.meta()["counts"]["issues"], 6)
            with self.assertRaises(ValidationError):
                other.import_data({"foo": 1})
        finally:
            other.close()

    def test_csv_rows(self):
        self._seed_search()
        rows = self.db.export_csv_rows()
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0][3], "論点名")

    def test_meta(self):
        self._seed_search()
        m = self.db.meta()
        self.assertEqual(m["counts"], {"clients": 2, "issues": 3, "open": 2})
        self.assertEqual(m["fiscal_years"], ["2026年9月期", "2025年9月期", "2025年3月期"])
        self.assertIn("法人税", m["tax_types"])

    def test_normalize_tags(self):
        self.assertEqual(normalize_tags("a, b、c　d #e a"), ["a", "b", "c", "d", "e"])
        self.assertEqual(normalize_tags(None), [])
        self.assertEqual(normalize_tags(["x ", "", "x"]), ["x"])


if __name__ == "__main__":
    unittest.main()
