"""FastAPI アプリ本体。静的ファイル (フロントエンド) と API を提供する。"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .db import init_db
from .routers import clients, io, journals, masters, reports

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

# Cache-Control を付けないと、ブラウザは独自の判断で古いファイルを使い続ける。
# ソフトを更新しても画面が古いままになるため、毎回サーバーに確認させる。
# no-cache は「使う前に必ず確認する」という意味で、内容が変わっていなければ
# 304 が返るだけなので通信量は増えない。
NO_CACHE = "no-cache, must-revalidate"


class NoCacheStaticFiles(StaticFiles):
    """更新が即座に反映されるよう、毎回の再確認を求める静的ファイル配信。"""

    def is_not_modified(self, response_headers, request_headers) -> bool:
        response_headers["cache-control"] = NO_CACHE
        return super().is_not_modified(response_headers, request_headers)

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["cache-control"] = NO_CACHE
        return response


def create_app() -> FastAPI:
    init_db()
    app = FastAPI(title="財務エントリ (kaikei-soft)", version="0.1.0", docs_url="/api/docs", redoc_url=None)
    app.include_router(masters.router)
    app.include_router(clients.router)
    app.include_router(journals.router)
    app.include_router(reports.router)
    app.include_router(io.router)

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": NO_CACHE})

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return FileResponse(STATIC_DIR / "favicon.svg", media_type="image/svg+xml")

    app.mount("/static", NoCacheStaticFiles(directory=str(STATIC_DIR)), name="static")
    return app


app = create_app()
