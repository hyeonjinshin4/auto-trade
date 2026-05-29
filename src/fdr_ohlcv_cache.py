"""
FinanceDataReader 일봉 캐시 — 동일 종목·사이클 내 중복 HTTP 방지.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from typing import Any

from safe_logging import get_safe_logger

_log = get_safe_logger(__name__)

# symbol -> (monotonic_ts, dataframe)
_store: dict[str, tuple[float, Any]] = {}


def _cache_ttl_sec() -> int:
    raw = (os.getenv("FDR_OHLCV_CACHE_SEC") or "600").strip()
    try:
        return max(30, int(float(raw)))
    except ValueError:
        return 600


def clear_ohlcv_cache() -> None:
    _store.clear()


def get_ohlcv(symbol: str, *, lookback_days: int = 120) -> Any | None:
    """
    종목 일봉 DataFrame (Close/High/Low/Volume 등). 실패 시 None.
    lookback_days 는 캐시 키에 포함하지 않고, 요청보다 긴 기간이 이미 캐시돼 있으면 재사용.
    """
    sym = symbol.strip()
    if not sym:
        return None
    if (os.getenv("SKIP_FDR_SNAPSHOT") or "").strip().lower() in {"1", "true", "yes", "y"}:
        return None

    days = max(35, int(lookback_days))
    now = time.monotonic()
    ttl = _cache_ttl_sec()
    hit = _store.get(sym)
    if hit is not None:
        ts, df = hit
        if (now - ts) < ttl and df is not None and len(df) >= min(35, days // 3):
            return df

    try:
        import FinanceDataReader as fdr  # type: ignore[import-untyped]
    except ImportError:
        return None

    end = datetime.now()
    start = end - timedelta(days=days)
    try:
        df = fdr.DataReader(sym, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        if df is None or len(df) < 3:
            return None
        _store[sym] = (now, df)
        return df
    except Exception as exc:
        _log.debug("FDR ohlcv %s: %s", sym, exc)
        return None
