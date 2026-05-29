"""FDR 일봉 → TA 시그널 판별용 OHLCV·지표."""
from __future__ import annotations

import os
from typing import Any

from safe_logging import get_safe_logger

from fdr_ohlcv_cache import get_ohlcv
from signal_scanner.config import WatchlistConfig, load_watchlist
from signal_scanner.indicators import compute_indicator_frame, latest_bars
from signal_scanner.rules import SignalHit, evaluate_buy_signals, evaluate_sell_signals

_log = get_safe_logger(__name__)


def evaluate_symbol_signals(
    symbol: str,
    cfg: WatchlistConfig,
) -> tuple[list[SignalHit], list[SignalHit], dict[str, Any]] | None:
    sym = symbol.strip()
    if not sym:
        return None
    try:
        df = get_ohlcv(sym, lookback_days=120)
        if df is None or len(df) < 35:
            return None
        ind = compute_indicator_frame(df, cfg.thresholds)
        today, prev = latest_bars(ind)
    except Exception as exc:
        _log.debug("FDR %s: %s", sym, exc)
        return None

    buy_hits = evaluate_buy_signals(today, prev, cfg.thresholds)
    sell_hits = evaluate_sell_signals(today, prev, cfg.thresholds)
    return buy_hits, sell_hits, today
