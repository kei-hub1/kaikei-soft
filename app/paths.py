"""アプリフォルダ内の各種パス定義。

アプリはフォルダごと移動しても動作するよう、すべてのパスを
このモジュールの ``APP_DIR``（main.py があるフォルダ）基準で決める。
"""

from __future__ import annotations

from pathlib import Path

APP_DIR: Path = Path(__file__).resolve().parent.parent

DATA_DIR: Path = APP_DIR / "data"
DB_PATH: Path = DATA_DIR / "app.db"

LOG_DIR: Path = APP_DIR / "logs"
LOG_PATH: Path = LOG_DIR / "app.log"

DEFAULT_OUTPUT_DIR: Path = APP_DIR / "出力"


def ensure_dirs() -> None:
    """データ・ログ・既定の出力フォルダを作成する（存在すれば何もしない）。"""
    for d in (DATA_DIR, LOG_DIR, DEFAULT_OUTPUT_DIR):
        d.mkdir(parents=True, exist_ok=True)
