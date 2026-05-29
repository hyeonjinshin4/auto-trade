from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SignalThresholds:
    rsi_period: int = 14
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0
    ma_fast: int = 5
    ma_slow: int = 20
    volume_mult: float = 2.0
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    bb_period: int = 20
    bb_std: float = 2.0
    stoch_k: int = 14
    stoch_d: int = 3
    stoch_smooth: int = 3
    stoch_low: float = 25.0
    stoch_high: float = 75.0
    hammer_lower_wick_pct: float = 0.55
    hammer_body_pct: float = 0.35
    shooting_upper_wick_pct: float = 0.55
    shooting_body_pct: float = 0.35


@dataclass(frozen=True)
class WatchlistConfig:
    path: Path
    respect_market_hours: bool
    confirm_trend: bool
    cooldown_hours: float
    min_signals: int
    max_signals_in_message: int
    symbols: tuple[str, ...]
    thresholds: SignalThresholds


def _parse_thresholds(raw: dict[str, Any]) -> SignalThresholds:
    def i(k: str, d: int) -> int:
        try:
            return int(raw.get(k, d))
        except (TypeError, ValueError):
            return d

    def f(k: str, d: float) -> float:
        try:
            return float(raw.get(k, d))
        except (TypeError, ValueError):
            return d

    return SignalThresholds(
        rsi_period=i("rsi_period", 14),
        rsi_oversold=f("rsi_oversold", 30.0),
        rsi_overbought=f("rsi_overbought", 70.0),
        ma_fast=i("ma_fast", 5),
        ma_slow=i("ma_slow", 20),
        volume_mult=f("volume_mult", 2.0),
        macd_fast=i("macd_fast", 12),
        macd_slow=i("macd_slow", 26),
        macd_signal=i("macd_signal", 9),
        bb_period=i("bb_period", 20),
        bb_std=f("bb_std", 2.0),
        stoch_k=i("stoch_k", 14),
        stoch_d=i("stoch_d", 3),
        stoch_smooth=i("stoch_smooth", 3),
        stoch_low=f("stoch_low", 25.0),
        stoch_high=f("stoch_high", 75.0),
        hammer_lower_wick_pct=f("hammer_lower_wick_pct", 0.55),
        hammer_body_pct=f("hammer_body_pct", 0.35),
        shooting_upper_wick_pct=f("shooting_upper_wick_pct", 0.55),
        shooting_body_pct=f("shooting_body_pct", 0.35),
    )


def default_watchlist_path() -> Path:
    raw = (os.getenv("SIGNAL_WATCHLIST_PATH") or "config/watchlist.json").strip()
    p = Path(raw)
    if p.is_absolute():
        return p
    root = Path(__file__).resolve().parent.parent.parent
    return root / p


def load_watchlist(path: Path | None = None) -> WatchlistConfig:
    p = path or default_watchlist_path()
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"watchlist must be object: {p}")

    syms = data.get("symbols") or []
    if not isinstance(syms, list):
        raise ValueError("watchlist.symbols must be array")
    symbols = tuple(str(s).strip() for s in syms if str(s).strip())

    th_raw = data.get("thresholds") or {}
    if not isinstance(th_raw, dict):
        th_raw = {}

    return WatchlistConfig(
        path=p,
        respect_market_hours=bool(data.get("respect_market_hours", True)),
        confirm_trend=bool(data.get("confirm_trend", True)),
        cooldown_hours=float(data.get("cooldown_hours", 4)),
        min_signals=max(1, int(data.get("min_signals", 2))),
        max_signals_in_message=max(1, int(data.get("max_signals_in_message", 4))),
        symbols=symbols,
        thresholds=_parse_thresholds(th_raw),
    )
