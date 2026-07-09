"""Structured application logging."""

from __future__ import annotations

import json
import logging
from collections import deque
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from app.common.settings import DEFAULT_DATA_DIR, env_str

LOGGER_NAME = "app"
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_LOG_MAX_BYTES = 1_000_000
DEFAULT_LOG_BACKUP_COUNT = 3


def log_path() -> Path:
    configured = env_str("INBOX_AI_LOG_FILE", "")
    if configured:
        return Path(configured)
    data_dir = Path(env_str("INBOX_AI_DATA_DIR", DEFAULT_DATA_DIR))
    return data_dir / "app.log"


def _log_level() -> int:
    raw = env_str("INBOX_AI_LOG_LEVEL", DEFAULT_LOG_LEVEL).upper()
    return getattr(logging, raw, logging.INFO)


def configure_logging() -> logging.Logger:
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(_log_level())
    logger.propagate = False

    current_path = str(path.resolve())
    if getattr(logger, "_app_log_path", None) == current_path:
        return logger

    for handler in list(logger.handlers):
        if getattr(handler, "_app_managed", False):
            logger.removeHandler(handler)
            handler.close()

    handler = RotatingFileHandler(
        path,
        maxBytes=DEFAULT_LOG_MAX_BYTES,
        backupCount=DEFAULT_LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    handler._app_managed = True  # type: ignore[attr-defined]
    logger.addHandler(handler)
    logger._app_log_path = current_path  # type: ignore[attr-defined]
    return logger


def get_logger(component: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(f"{LOGGER_NAME}.{component}")


def log_event(logger: logging.Logger, event: str, *, level: int = logging.INFO, **fields: Any) -> None:
    configure_logging()
    payload = json.dumps(fields, ensure_ascii=False, sort_keys=True, default=str) if fields else "{}"
    logger.log(level, "%s %s", event, payload)


def tail_log_lines(limit: int = 120) -> list[str]:
    path = log_path()
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return list(deque((line.rstrip("\n") for line in handle), maxlen=max(1, limit)))
