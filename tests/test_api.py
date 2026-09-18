import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ronten.db import Database  # noqa: E402
from ronten.server import make_server  # noqa: E402


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = Database(":memory:")
        cls.server = make_server("127.0.0.1", 0, cls.db)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.db.close()

    def req(self, method, path, body=None, raw=False):
        data = None
        headers = {}
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        r = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(r) as resp:
                content = resp.read()
                return resp.status, (content if raw else json.loads(content.decode("utf-8"))), resp.headers
        except urllib.error.HTTPError as e:
            content = e.read()
            return e.code, (content if raw else json.loads(content.decode("utf-8"))), e.headers

    def test_static(self):
        status, body, headers = self.req("GET", "/", raw=True)
        self.assertEqual(status, 200)
        self.assertIn(b"<title>", body)
        self.assertIn("text/html", headers["Content-Type"])
        status, body, headers = self.req("GET", "/app.js", raw=True)
        self.assertEqual(status, 200)
        self.assertIn("javascript", headers["Content-Type"])
        # 存在しないパスは SPA の index.html
        status, body, _ = self.req("GET", "/no/such/page", raw=True)
        self.assertEqual(status, 200)
        self.assertIn(b"<title>", body)
        # ディレクトリトラバーサル
        status, body, _ = self.req("GET", "/../db.py", raw=True)
        self.assertEqual(status, 200)
        self.assertNotIn(b"sqlite3", body)

    def test_flow(self):
        status, meta, _ = self.req("GET", "/api/meta")
        self.assertEqual(status, 200)
        self.assertIn("tax_types", meta)

        status, c, _ = self.req("POST", "/api/clients", {"name": "テスト株式会社", "fiscal_month": 3})
        self.assertEqual(status, 201)
        status, err, _ = self.req("POST", "/api/clients", {"name": ""})
        self.assertEqual(status, 400)
        self.assertIn("error", err)

        status, it, _ = self.req("POST", "/api/issues", {
            "client_id": c["id"], "title": "交際費と会議費の区分", "tax_type": "法人税",
            "tags": "交際費 会議費", "conclusion": "1人当たり10,000円以下は会議費",
        })
        self.assertEqual(status, 201)
        self.assertEqual(it["tags"], ["交際費", "会議費"])

        status, r, _ = self.req("GET", "/api/issues?q=" + urllib.request.quote("会議費"))
        self.assertEqual(r["total"], 1)
        status, r, _ = self.req("GET", f"/api/clients/{c['id']}/issues")
        self.assertEqual(r["total"], 1)

        status, upd, _ = self.req("PUT", f"/api/issues/{it['id']}", dict(it, status="結論済"))
        self.assertEqual(status, 200)
        self.assertEqual(upd["status"], "結論済")
        status, revs, _ = self.req("GET", f"/api/issues/{it['id']}/revisions")
        self.assertEqual(len(revs["items"]), 1)
        status, sim, _ = self.req("GET", f"/api/issues/{it['id']}/similar")
        self.assertEqual(status, 200)

        status, body, headers = self.req("GET", "/api/export.csv", raw=True)
        self.assertEqual(status, 200)
        self.assertTrue(body.startswith("﻿".encode("utf-8")))
        self.assertIn("交際費と会議費の区分".encode("utf-8"), body)
        status, exp, headers = self.req("GET", "/api/export.json")
        self.assertEqual(exp["format"], "ronten-export")
        self.assertIn("attachment", headers["Content-Disposition"])

        status, _, _ = self.req("DELETE", f"/api/issues/{it['id']}")
        self.assertEqual(status, 200)
        status, err, _ = self.req("GET", f"/api/issues/{it['id']}")
        self.assertEqual(status, 404)
        status, _, _ = self.req("DELETE", f"/api/clients/{c['id']}")
        self.assertEqual(status, 200)

    def test_bad_json(self):
        r = urllib.request.Request(self.base + "/api/clients", data=b"{bad", method="POST",
                                   headers={"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(r)
        self.assertEqual(cm.exception.code, 400)

    def test_unknown_api(self):
        status, err, _ = self.req("GET", "/api/nothing")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
