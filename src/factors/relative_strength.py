"""Relative strength vs benchmark & sector (vectorized, no look-ahead)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class RSWeights:
    w20: float = 0.5
    w60: float = 0.3
    w120: float = 0.2


def _horizon_return(close: pd.Series, h: int) -> float | None:
    """Return from t-h to t using only data ≤ t (last row)."""
    s = close.astype(float).dropna()
    if len(s) < h + 1:
        return None
    a = float(s.iloc[-1])
    b = float(s.iloc[-(h + 1)])
    if b <= 0:
        return None
    return a / b - 1.0


def relative_returns_vs_benchmark(
    stock_close: pd.Series,
    bench_close: pd.Series,
    horizons: tuple[int, ...] = (20, 60, 120),
) -> dict[str, float | None]:
    """Align on calendar intersection; last bar only."""
    df = pd.concat(
        [stock_close.rename("s"), bench_close.rename("b")],
        axis=1,
        join="inner",
    ).dropna()
    if len(df) < max(horizons) + 2:
        return {f"excess_{h}d": None for h in horizons}
    out: dict[str, float | None] = {}
    for h in horizons:
        sr = _horizon_return(df["s"], h)
        br = _horizon_return(df["b"], h)
        out[f"excess_{h}d"] = (sr - br) if sr is not None and br is not None else None
    return out


def composite_momentum_score(
    excess_by_horizon: dict[str, float | None],
    weights: RSWeights = RSWeights(),
) -> float | None:
    """Scalar composite from excess returns (still in return space, not 0–1)."""
    e20 = excess_by_horizon.get("excess_20d")
    e60 = excess_by_horizon.get("excess_60d")
    e120 = excess_by_horizon.get("excess_120d")
    if e20 is None and e60 is None and e120 is None:
        return None
    parts: list[float] = []
    wsum = 0.0
    for e, w in ((e20, weights.w20), (e60, weights.w60), (e120, weights.w120)):
        if e is not None and w > 0:
            parts.append(e * w)
            wsum += w
    if wsum <= 0:
        return None
    return float(sum(parts) / wsum)


def cross_sectional_percentile_rank(scores: pd.Series) -> pd.Series:
    """0–1 percentile rank (midrank), NaN preserved."""
    valid = scores.dropna()
    if valid.empty:
        return scores * np.nan
    ranks = valid.rank(method="average", pct=True)
    out = scores.astype(float).copy()
    out.loc[ranks.index] = ranks
    return out


def sector_excess_overlay(
    market_excess: dict[str, float | None],
    sector_excess: dict[str, float | None],
    *,
    sector_blend: float = 0.35,
) -> dict[str, float | None]:
    """Blend market-relative and sector-relative excess per horizon."""
    out: dict[str, float | None] = {}
    for k in market_excess:
        m = market_excess.get(k)
        s = sector_excess.get(k) if sector_excess else None
        if m is None and s is None:
            out[k] = None
        elif m is None:
            out[k] = s
        elif s is None:
            out[k] = m
        else:
            out[k] = (1.0 - sector_blend) * m + sector_blend * s
    return out


def build_rs_row(
    stock_close: pd.Series,
    bench_close: pd.Series,
    sector_close: pd.Series | None,
    weights: RSWeights = RSWeights(),
) -> dict[str, float | None]:
    """One symbol: excess vs market, optional sector overlay, composite, rs percentile placeholder."""
    mkt = relative_returns_vs_benchmark(stock_close, bench_close)
    if sector_close is not None:
        sec = relative_returns_vs_benchmark(stock_close, sector_close)
        merged = sector_excess_overlay(mkt, sec)
    else:
        merged = mkt
    comp = composite_momentum_score(merged, weights=weights)
    return {
        **{f"mkt_{k}": v for k, v in mkt.items()},
        "composite_raw": comp,
    }
