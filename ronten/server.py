"""内蔵 HTTP サーバー（標準ライブラリのみ）。JSON API と静的ファイルを配信する。"""

from __future__ import annotations

import csv
import io
import json
import mimetypes
import os
import re
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from .db import Database, NotFound, ValidationError

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
MAX_BODY = 50 * 1024 * 1024


def _to_int(v: str | None, default: int | None = None) -> int | None:
    if v in (None, ""):
        return default
    try:
        return int(v)
    except ValueError:
        return default


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class Handler(BaseHTTPRequestHandler):
    server_version = "RontenNote/0.1"

    @property
    def db(self) -> Database:
        return self.server.db  # type: ignore[attr-defined]

    # ルート定義: (メソッド, 正規表現, ハンドラ)
    routes: list[tuple[str, re.Pattern[str], Callable]] = []

    @classmethod
    def route(cls, method: str, pattern: str):
        def deco(fn):
            cls.routes.append((method, re.compile("^" + pattern + "$"), fn))
            return fn
        return deco

    # ------------------------------------------------------------ plumbing
    def log_message(self, fmt, *args):  # noqa: D401 - quieter logs
        if os.environ.get("RONTEN_DEBUG"):
            super().log_message(fmt, *args)

    def _dispatch(self, method: str) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        self.query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        try:
            if path.startswith("/api/"):
                for m, rx, fn in self.routes:
                    mo = rx.match(path)
                    if mo and m == method:
                        fn(self, *mo.groups())
                        return
                raise ApiError(404, "API が見つかりません")
            if method != "GET":
                raise ApiError(405, "許可されていないメソッドです")
            self._serve_static(path)
        except ApiError as e:
            self._json({"error": e.message}, e.status)
        except NotFound as e:
            self._json({"error": str(e)}, 404)
        except ValidationError as e:
            self._json({"error": str(e)}, 400)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:  # noqa: BLE001
            self._json({"error": f"サーバーエラー: {e.__class__.__name__}: {e}"}, 500)

    def do_GET(self):  # noqa: N802
        self._dispatch("GET")

    def do_POST(self):  # noqa: N802
        self._dispatch("POST")

    def do_PUT(self):  # noqa: N802
        self._dispatch("PUT")

    def do_DELETE(self):  # noqa: N802
        self._dispatch("DELETE")

    def q(self, name: str, default: str = "") -> str:
        vals = self.query.get(name)
        return vals[0] if vals else default

    def body_json(self) -> Any:
        length = _to_int(self.headers.get("Content-Length"), 0) or 0
        if length > MAX_BODY:
            raise ApiError(413, "リクエストが大きすぎます")
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ApiError(400, "JSON の形式が不正です")

    def _send(self, status: int, content_type: str, body: bytes, extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self._send(status, "application/json; charset=utf-8", body)

    def _serve_static(self, path: str) -> None:
        if path in ("", "/"):
            path = "/index.html"
        rel = os.path.normpath(urllib.parse.unquote(path)).lstrip("/\\")
        full = os.path.join(STATIC_DIR, rel)
        if not os.path.abspath(full).startswith(os.path.abspath(STATIC_DIR) + os.sep) or not os.path.isfile(full):
            # SPA: 未知のパスは index.html を返す
            full = os.path.join(STATIC_DIR, "index.html")
        ctype, _ = mimetypes.guess_type(full)
        ctype = ctype or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        with open(full, "rb") as f:
            self._send(HTTPStatus.OK, ctype, f.read())


# ------------------------------------------------------------------ routes
@Handler.route("GET", "/api/meta")
def api_meta(h: Handler):
    h._json(h.db.meta())


@Handler.route("GET", "/api/clients")
def api_list_clients(h: Handler):
    h._json({"items": h.db.list_clients(h.q("q"))})


@Handler.route("POST", "/api/clients")
def api_create_client(h: Handler):
    h._json(h.db.create_client(h.body_json()), 201)


@Handler.route("GET", r"/api/clients/(\d+)")
def api_get_client(h: Handler, cid: str):
    h._json(h.db.get_client(int(cid)))


@Handler.route("PUT", r"/api/clients/(\d+)")
def api_update_client(h: Handler, cid: str):
    h._json(h.db.update_client(int(cid), h.body_json()))


@Handler.route("DELETE", r"/api/clients/(\d+)")
def api_delete_client(h: Handler, cid: str):
    h.db.delete_client(int(cid))
    h._json({"ok": True})


@Handler.route("GET", r"/api/clients/(\d+)/issues")
def api_client_issues(h: Handler, cid: str):
    h._json(h.db.list_issues(client_id=int(cid), q=h.q("q"), limit=1000))


@Handler.route("GET", "/api/issues")
def api_list_issues(h: Handler):
    h._json(
        h.db.list_issues(
            q=h.q("q"),
            client_id=_to_int(h.q("client_id")),
            tax_type=h.q("tax_type"),
            status=h.q("status"),
            tag=h.q("tag"),
            fiscal_year=h.q("fiscal_year"),
            staff=h.q("staff"),
            open_only=h.q("open") in ("1", "true"),
            limit=min(_to_int(h.q("limit"), 100) or 100, 1000),
            offset=_to_int(h.q("offset"), 0) or 0,
        )
    )


@Handler.route("POST", "/api/issues")
def api_create_issue(h: Handler):
    h._json(h.db.create_issue(h.body_json()), 201)


@Handler.route("GET", r"/api/issues/(\d+)")
def api_get_issue(h: Handler, iid: str):
    h._json(h.db.get_issue(int(iid)))


@Handler.route("PUT", r"/api/issues/(\d+)")
def api_update_issue(h: Handler, iid: str):
    h._json(h.db.update_issue(int(iid), h.body_json()))


@Handler.route("DELETE", r"/api/issues/(\d+)")
def api_delete_issue(h: Handler, iid: str):
    h.db.delete_issue(int(iid))
    h._json({"ok": True})


@Handler.route("GET", r"/api/issues/(\d+)/similar")
def api_similar(h: Handler, iid: str):
    h._json({"items": h.db.similar_issues(int(iid))})


@Handler.route("GET", r"/api/issues/(\d+)/revisions")
def api_revisions(h: Handler, iid: str):
    h._json({"items": h.db.list_revisions(int(iid))})


@Handler.route("GET", "/api/export.json")
def api_export_json(h: Handler):
    data = h.db.export_data()
    body = json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8")
    fname = "ronten-backup-" + data["exported_at"].replace(":", "").replace("-", "") + ".json"
    h._send(200, "application/json; charset=utf-8", body, {"Content-Disposition": f'attachment; filename="{fname}"'})


@Handler.route("GET", "/api/export.csv")
def api_export_csv(h: Handler):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerows(h.db.export_csv_rows())
    body = ("﻿" + buf.getvalue()).encode("utf-8")  # BOM 付き: Excel で文字化けしない
    h._send(200, "text/csv; charset=utf-8", body, {"Content-Disposition": 'attachment; filename="ronten-issues.csv"'})


@Handler.route("POST", "/api/import")
def api_import(h: Handler):
    h._json(h.db.import_data(h.body_json()))


# ------------------------------------------------------------------ server
class RontenServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr: tuple[str, int], db: Database):
        self.db = db
        super().__init__(addr, Handler)


def make_server(host: str, port: int, db: Database) -> RontenServer:
    return RontenServer((host, port), db)
