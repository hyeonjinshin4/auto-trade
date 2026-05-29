"""
TA 시그널 → 자동매매 (조건별 가점 합산).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from safe_logging import get_safe_logger

from signal_scanner.config import WatchlistConfig, load_watchlist
from signal_scanner.cooldown import in_cooldown, mark_sent
from signal_scanner.rules import SignalHit, trend_allows_buy, trend_allows_sell
from signal_scanner.runner import evaluate_symbol_signals
from signal_scanner.ta_scoring import (
    TaScoreDetail,
    score_ta_buy,
    score_ta_sell_exit,
    score_ta_sell_penalty,
)

_log = get_safe_logger(__name__)
_TRADE_CD_PREFIX = "trade:"


def use_ta_signals() -> bool:
    raw = (os.getenv("USE_TA_SIGNALS") or "true").strip().lower()
    return raw in {"1", "true", "yes", "y"}


def ta_entry_only() -> bool:
    raw = (os.getenv("TRADING_TA_ENTRY_ONLY") or "false").strip().lower()
    return raw in {"1", "true", "yes", "y"}


@lru_cache(maxsize=1)
def ta_config() -> WatchlistConfig:
    return load_watchlist()


def clear_ta_config_cache() -> None:
    ta_config.cache_clear()


@dataclass(frozen=True)
class TaBuyResult:
    ok: bool
    hits: tuple[SignalHit, ...]
    tier: str
    score: float
    reason: str
    detail: TaScoreDetail | None = None
    sell_penalty: float = 0.0
    sell_penalty_detail: TaScoreDetail | None = None


@dataclass(frozen=True)
class TaSellResult:
    ok: bool
    hits: tuple[SignalHit, ...]
    reason: str
    score: float = 0.0
    detail: TaScoreDetail | None = None


def ta_buy_metrics(symbol: str, cfg: WatchlistConfig | None = None) -> TaBuyResult:
    sym = symbol.strip()
    c = cfg or ta_config()
    ev = evaluate_symbol_signals(sym, c)
    if ev is None:
        return TaBuyResult(False, (), "skip", 0.0, "TA 지표 데이터 부족", None)

    buy_hits, sell_hits, today = ev
    trend_ok = trend_allows_buy(today, c)
    detail = score_ta_buy(buy_hits, c, trend_ok=trend_ok)
    sell_pen = score_ta_sell_penalty(sell_hits, c)
    pts = detail.score
    tier = "full" if pts >= 70 else "half" if pts >= 50 else "skip"
    reason = f"TA가점합={detail.raw_points} [{detail.breakdown}]"
    if sell_pen.raw_points > 0:
        reason += f" | TA감점=-{sell_pen.raw_points} [{sell_pen.breakdown}]"
    if detail.labels:
        reason += f" | {detail.labels}"
    if detail.blocked_reason:
        return TaBuyResult(
            False,
            tuple(buy_hits),
            "skip",
            0.0,
            f"{detail.blocked_reason}",
            detail,
            sell_penalty=sell_pen.score,
            sell_penalty_detail=sell_pen,
        )
    return TaBuyResult(
        pts > 0 or sell_pen.raw_points > 0,
        tuple(buy_hits),
        tier,
        pts,
        reason,
        detail,
        sell_penalty=sell_pen.score,
        sell_penalty_detail=sell_pen,
    )


def ta_sell_metrics(symbol: str, cfg: WatchlistConfig | None = None) -> TaSellResult:
    sym = symbol.strip()
    c = cfg or ta_config()
    ev = evaluate_symbol_signals(sym, c)
    if ev is None:
        return TaSellResult(False, (), "TA 지표 데이터 부족", 0.0, None)

    _, sell_hits, today = ev
    trend_ok = trend_allows_sell(today, c)
    detail = score_ta_sell_exit(sell_hits, c, trend_ok=trend_ok)
    reason = f"TA매도={detail.raw_points}점(주요≥{c.min_signals}+종가≤20일) [{detail.breakdown}]"
    if detail.labels:
        reason += f" | {detail.labels}"
    if detail.blocked_reason:
        return TaSellResult(False, tuple(sell_hits), detail.blocked_reason, detail.score, detail)
    return TaSellResult(detail.score > 0, tuple(sell_hits), reason, detail.score, detail)


def evaluate_ta_buy(symbol: str) -> TaBuyResult:
    sym = symbol.strip()
    cd_key = f"{_TRADE_CD_PREFIX}{sym}:buy"
    if in_cooldown(cd_key, "", ta_config().cooldown_hours):
        return TaBuyResult(False, (), "skip", 0.0, "TA 매수 쿨다운 중")
    return ta_buy_metrics(sym)


def evaluate_ta_sell(symbol: str) -> TaSellResult:
    sym = symbol.strip()
    cd_key = f"{_TRADE_CD_PREFIX}{sym}:sell"
    if in_cooldown(cd_key, "", ta_config().cooldown_hours):
        return TaSellResult(False, (), "TA 매도 쿨다운 중", 0.0)
    return ta_sell_metrics(sym)


def mark_ta_trade(symbol: str, side: str) -> None:
    sym = symbol.strip()
    mark_sent(f"{_TRADE_CD_PREFIX}{sym}:{side.strip().lower()}", "")
