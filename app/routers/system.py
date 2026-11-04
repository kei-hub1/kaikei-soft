"""ソフト自体の設定 API: Windows の自動起動、終了。"""
from __future__ import annotations

import os
import threading

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from .. import autostart, backups

router = APIRouter(prefix="/api/system", tags=["system"])


def _require_local(x_kaikei_local: str | None) -> None:
    # 独自ヘッダーを必須にして、ほかのサイトのページからの呼び出し (フォーム送信など) を防ぐ。
    # ブラウザは別サイトから独自ヘッダー付きで送る前に確認 (preflight) し、本ソフトはそれを許可しない。
    if x_kaikei_local != "1":
        raise HTTPException(403, "この操作は財務エントリの画面からのみ行えます")


class RestoreIn(BaseModel):
    name: str


@router.get("/backups")
def list_backups():
    """data/backup にあるバックアップの一覧 (新しい順)。"""
    return backups.list_backups()


@router.post("/backups/restore")
def restore_backup(body: RestoreIn, x_kaikei_local: str | None = Header(default=None)):
    """バックアップの時点に戻す。戻す前の状態も自動でバックアップする (戻したことを取り消せるように)。"""
    _require_local(x_kaikei_local)
    try:
        return backups.restore_backup(body.name)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


class AutostartIn(BaseModel):
    enabled: bool
    open_browser: bool = True


@router.get("/autostart")
def get_autostart():
    return autostart.status()


@router.put("/autostart")
def put_autostart(body: AutostartIn, x_kaikei_local: str | None = Header(default=None)):
    _require_local(x_kaikei_local)
    if not autostart.supported():
        raise HTTPException(400, "自動起動の設定は Windows でのみ使えます")
    try:
        return autostart.enable(body.open_browser) if body.enabled else autostart.disable()
    except OSError as e:
        raise HTTPException(500, f"設定に失敗しました: {e}")


@router.post("/shutdown")
def shutdown(x_kaikei_local: str | None = Header(default=None)):
    """財務エントリ (サーバー) を終了する。自動起動で窓なしで動いているときに使う。"""
    _require_local(x_kaikei_local)
    # 応答を返してから止める。仕訳などは 1 回の操作ごとに保存済みなので、ここで止めても失われない。
    threading.Timer(0.5, lambda: os._exit(0)).start()
    return {"ok": True}
