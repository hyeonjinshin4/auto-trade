from __future__ import annotations

from typing import Any

import pandas as pd

from signal_scanner.config import SignalThresholds


def _col(df: pd.DataFrame, name: str) -> pd.Series:
    for c in df.columns:
        if str(c).lower() == name.lower():
            return df[c].astype(float)
    raise KeyError(name)


def compute_indicator_frame(df: pd.DataFrame, th: SignalThresholds) -> pd.DataFrame:
    """OHLCV 일봉 → 지표 컬럼이 붙은 DataFrame."""
    o = _col(df, "Open")
    h = _col(df, "High")
    l = _col(df, "Low")
    c = _col(df, "Close")
    vol_col = next((c for c in df.columns if str(c).lower() == "volume"), None)
    v = df[vol_col].astype(float) if vol_col is not None else pd.Series(0.0, index=df.index)

    out = pd.DataFrame(index=df.index)
    out["open"] = o
    out["high"] = h
    out["low"] = l
    out["close"] = c
    out["volume"] = v

    # RSI
    delta = c.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(span=th.rsi_period, adjust=False).mean()
    avg_loss = loss.ewm(span=th.rsi_period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    out["rsi"] = 100 - (100 / (1 + rs))

    out["ma_fast"] = c.rolling(th.ma_fast).mean()
    out["ma_slow"] = c.rolling(th.ma_slow).mean()

    ema_fast = c.ewm(span=th.macd_fast, adjust=False).mean()
    ema_slow = c.ewm(span=th.macd_slow, adjust=False).mean()
    out["macd"] = ema_fast - ema_slow
    out["macd_signal"] = out["macd"].ewm(span=th.macd_signal, adjust=False).mean()

    mid = c.rolling(th.bb_period).mean()
    std = c.rolling(th.bb_period).std()
    out["bb_mid"] = mid
    out["bb_upper"] = mid + th.bb_std * std
    out["bb_lower"] = mid - th.bb_std * std

    low_min = l.rolling(th.stoch_k).min()
    high_max = h.rolling(th.stoch_k).max()
    raw_k = 100 * (c - low_min) / (high_max - low_min).replace(0, pd.NA)
    out["stoch_k"] = raw_k.rolling(th.stoch_smooth).mean()
    out["stoch_d"] = out["stoch_k"].rolling(th.stoch_d).mean()

    out["vol_ma20"] = v.rolling(20).mean()

    # 캔들 구성요소
    body = (c - o).abs()
    full_range = (h - l).replace(0, pd.NA)
    lower_wick = (o.combine(c, min) - l).clip(lower=0)
    upper_wick = (h - o.combine(c, max)).clip(lower=0)
    out["body_pct"] = body / full_range
    out["lower_wick_pct"] = lower_wick / full_range
    out["upper_wick_pct"] = upper_wick / full_range

    return out


def latest_bars(ind: pd.DataFrame) -> tuple[dict[str, Any], dict[str, Any]]:
    """당일(-1)·전일(-2) 스칼라 dict."""
    if len(ind) < 3:
        raise ValueError("insufficient bars")
    today = ind.iloc[-1]
    prev = ind.iloc[-2]
    return today.to_dict(), prev.to_dict()
