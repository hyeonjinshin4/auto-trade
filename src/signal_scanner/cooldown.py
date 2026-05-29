from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from safe_logging import get_safe_logger

_log = get_safe_logger(__name__)
_KST = timezone(timedelta(hours=9))


def cooldown_path() -> Path:
    raw = (os.getenv("SIGNAL_ALERT_COOLDOWN_PATH") or "logs/signal_alert_cooldown.json").strip()
    p = Path(raw)
    if p.is_absolute():
        return p
    root = Path(__file__).resolve().parent.parent.parent
    return root / p


def _load() -> dict[str, str]:
    p = cooldown_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        _log.warning("signal cooldown load: %s", exc)
    return {}


def _save(data: dict[str, str]) -> None:
    p = cooldown_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")
    except OSError as exc:
        _log.warning("signal cooldown save: %s", exc)


def _key(symbol: str, side: str) -> str:
    return f"{symbol.strip()}:{side.strip().lower()}"


def in_cooldown(symbol: str, side: str, hours: float) -> bool:
    """symbol 이 'trade:005930:buy' 형태면 그 문자열 전체를 쿨다운 키로 사용."""
    data = _load()
    key = symbol if symbol.startswith("trade:") else _key(symbol, side)
    raw = data.get(key)
    if not raw:
        return False
    try:
        ts = datetime.fromisoformat(raw)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=_KST)
    except ValueError:
        return False
    return datetime.now(_KST) - ts < timedelta(hours=hours)


def mark_sent(symbol: str, side: str) -> None:
    data = _load()
    key = symbol if symbol.startswith("trade:") else _key(symbol, side)
    data[key] = datetime.now(_KST).isoformat(timespec="seconds")
    _save(data)
