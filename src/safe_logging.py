"""
애플리케이션 로깅. 민감정보는 secure_env.redact_secrets 로 마스킹.
"""
from __future__ import annotations

import logging
import os
import sys

from secure_env import redact_secrets


def configure_app_logging() -> None:
    raw = (os.getenv("LOG_LEVEL") or "WARNING").strip().upper()
    level = getattr(logging, raw, logging.WARNING)
    root = logging.getLogger()
    if root.handlers:
        return
    h = logging.StreamHandler(sys.stderr)
    h.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    root.addHandler(h)
    root.setLevel(level)


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_secrets(record.msg)
        return True


def get_safe_logger(name: str) -> logging.Logger:
    configure_app_logging()
    log = logging.getLogger(name)
    log.addFilter(RedactFilter())
    return log
