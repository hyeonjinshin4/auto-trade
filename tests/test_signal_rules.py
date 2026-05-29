"""기술적 시그널 규칙 단위 테스트."""
from __future__ import annotations

import numpy as np
import pandas as pd

from signal_scanner.config import SignalThresholds, WatchlistConfig
from signal_scanner.indicators import compute_indicator_frame, latest_bars
from signal_scanner.rules import (
    SignalHit,
    alert_ready,
    evaluate_buy_signals,
    evaluate_sell_signals,
    sell_alert_ready,
    trend_allows_buy,
    trend_allows_sell,
)


def _synthetic_ohlcv(n: int = 80, *, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 0.5, n))
    high = close + rng.uniform(0.5, 2, n)
    low = close - rng.uniform(0.5, 2, n)
    open_ = close + rng.normal(0, 0.3, n)
    vol = rng.integers(1_000_000, 3_000_000, n)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": vol},
        index=idx,
    )


def test_sell_alert_ignores_volume_aux() -> None:
    cfg = WatchlistConfig(
        path=__file__,
        respect_market_hours=True,
        confirm_trend=True,
        cooldown_hours=4,
        min_signals=2,
        max_signals_in_message=4,
        symbols=(),
        thresholds=SignalThresholds(),
    )
    one = [SignalHit("rsi_overbought", "x")]
    assert sell_alert_ready(one, cfg) is False
    two = [SignalHit("rsi_overbought", "a"), SignalHit("dead_cross", "b")]
    assert sell_alert_ready(two, cfg) is True
    vol_only = [SignalHit("volume_down", "v")]
    assert sell_alert_ready(vol_only, cfg) is False


def test_alert_requires_min_two() -> None:
    cfg = WatchlistConfig(
        path=__file__,
        respect_market_hours=True,
        confirm_trend=True,
        cooldown_hours=4,
        min_signals=2,
        max_signals_in_message=4,
        symbols=(),
        thresholds=SignalThresholds(),
    )
    assert alert_ready([], cfg) is False
    from signal_scanner.rules import SignalHit

    one = [SignalHit("a", "test")]
    assert alert_ready(one, cfg) is False
    two = [SignalHit("a", "1"), SignalHit("b", "2")]
    assert alert_ready(two, cfg) is True


def test_indicators_and_rules_run() -> None:
    df = _synthetic_ohlcv()
    th = SignalThresholds()
    ind = compute_indicator_frame(df, th)
    today, prev = latest_bars(ind)
    cfg = WatchlistConfig(
        path=__file__,
        respect_market_hours=True,
        confirm_trend=False,
        cooldown_hours=4,
        min_signals=2,
        max_signals_in_message=4,
        symbols=(),
        thresholds=th,
    )
    buy = evaluate_buy_signals(today, prev, th)
    sell = evaluate_sell_signals(today, prev, th)
    assert isinstance(buy, list)
    assert isinstance(sell, list)
    if trend_allows_buy(today, cfg):
        _ = alert_ready(buy, cfg)
    if trend_allows_sell(today, cfg):
        _ = alert_ready(sell, cfg)
