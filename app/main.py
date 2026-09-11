"""FastAPI アプリ本体。静的ファイル (フロントエンド) と API を提供する。"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .db import init_db
from .routers import clients, io, journals, masters, passbooks, reports

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def create_app() -> FastAPI:
    init_db()
    app = FastAPI(title="財務エントリ (kaikei-soft)", version="0.1.0", docs_url="/api/docs", redoc_url=None)
    app.include_router(masters.router)
    app.include_router(clients.router)
    app.include_router(journals.router)
    app.include_router(reports.router)
    app.include_router(passbooks.router)
    app.include_router(io.router)

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return FileResponse(STATIC_DIR / "favicon.svg", media_type="image/svg+xml")

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    return app


app = create_app()
