"""TA 조건별 독립 가점."""
from __future__ import annotations

from signal_scanner.config import WatchlistConfig, SignalThresholds
from signal_scanner.rules import SignalHit
from signal_scanner.ta_scoring import score_ta_buy, score_ta_sell_exit, score_ta_sell_penalty


def _cfg() -> WatchlistConfig:
    return WatchlistConfig(
        path=__file__,
        respect_market_hours=True,
        confirm_trend=True,
        cooldown_hours=4,
        min_signals=2,
        max_signals_in_message=4,
        symbols=(),
        thresholds=SignalThresholds(),
    )


def test_single_condition_blocked_for_entry() -> None:
    """주요 시그널 1개만이면 가점 합산은 0 (min_signals=2)."""
    hits = (SignalHit("rsi_oversold", "RSI"),)
    d = score_ta_buy(hits, _cfg(), trend_ok=True)
    assert d.raw_points == 14
    assert d.score == 0.0
    assert d.blocked_reason is not None
    assert "매수시그널<2" in d.blocked_reason


def test_entry_min_signals_env_override(monkeypatch) -> None:
    monkeypatch.setenv("TRADING_TA_ENTRY_MIN_SIGNALS", "1")
    hits = (SignalHit("rsi_oversold", "RSI"),)
    d = score_ta_buy(hits, _cfg(), trend_ok=True)
    assert d.score == 14.0
    assert d.blocked_reason is None


def test_two_conditions_sum_points() -> None:
    hits = (
        SignalHit("rsi_oversold", "RSI"),
        SignalHit("macd_bull", "MACD"),
    )
    d = score_ta_buy(hits, _cfg(), trend_ok=True)
    assert d.raw_points == 28
    assert d.score == 28.0


def test_trend_blocks_contribution_not_count() -> None:
    hits = (SignalHit("rsi_oversold", "RSI"),)
    d = score_ta_buy(hits, _cfg(), trend_ok=False)
    assert d.raw_points == 14
    assert d.score == 0.0
    assert d.blocked_reason is not None


def test_sell_penalty_matches_buy_weights() -> None:
    hits = (SignalHit("rsi_overbought", "RSI"), SignalHit("macd_bear", "MACD"))
    d = score_ta_sell_penalty(hits, _cfg())
    assert d.raw_points == 28  # 14 + 14
    assert d.score == 28.0


def test_sell_exit_needs_two_primary_and_trend() -> None:
    one = (SignalHit("rsi_overbought", "RSI"),)
    d1 = score_ta_sell_exit(one, _cfg(), trend_ok=True)
    assert d1.score == 0.0
    assert d1.blocked_reason is not None

    two = (
        SignalHit("rsi_overbought", "RSI"),
        SignalHit("macd_bear", "MACD"),
    )
    d2 = score_ta_sell_exit(two, _cfg(), trend_ok=True)
    assert d2.score == 28.0
    assert d2.blocked_reason is None

    d3 = score_ta_sell_exit(two, _cfg(), trend_ok=False)
    assert d3.score == 0.0
    assert "20일선" in (d3.blocked_reason or "")
