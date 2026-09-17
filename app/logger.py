"""ログ設定。エラー内容はアプリフォルダ内 logs/app.log に記録する。"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

from . import paths

_LOGGER_NAME = "kaikei"


def setup_logging(log_path: Path | None = None) -> logging.Logger:
    """ファイルへのローテーションログを設定し、アプリ用ロガーを返す。"""
    log_path = log_path or paths.LOG_PATH
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(_LOGGER_NAME)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    )
    logger.addHandler(handler)
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """モジュール別の子ロガーを返す。"""
    if name:
        return logging.getLogger(f"{_LOGGER_NAME}.{name}")
    return logging.getLogger(_LOGGER_NAME)
