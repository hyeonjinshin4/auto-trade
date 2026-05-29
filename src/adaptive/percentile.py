"""
Percentile helpers — no look-ahead: rank of observation t uses only window ending at t.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def percentile_rank_last(window_values: np.ndarray | pd.Series) -> float:
    """
    Rank of the last element within `window_values` (inclusive), in [0, 1].
    NaNs dropped. If insufficient data, returns 0.5.
    """
    if isinstance(window_values, pd.Series):
        arr = window_values.to_numpy(dtype=float)
    else:
        arr = np.asarray(window_values, dtype=float)
    arr = arr[~np.isnan(arr)]
    if arr.size < 2:
        return 0.5
    last = arr[-1]
    past = arr
    # (count strictly below + 0.5 * equal) / n  — midrank
    below = np.sum(past < last)
    equal = np.sum(past == last)
    return float(below + 0.5 * equal) / float(past.size)


def rolling_percentile_rank(series: pd.Series, window: int) -> pd.Series:
    """
    For each index i (after min_periods), percentile rank of series.iloc[i]
    among series.iloc[i-window+1 : i+1]. Same-length series, NaN until min_periods.
    """
    s = series.astype(float)

    def _roll(x: np.ndarray) -> float:
        return percentile_rank_last(x)

    return s.rolling(window=window, min_periods=max(5, min(window, 20))).apply(_roll, raw=True)


def widen_low_sample_percentile(raw_pct: float, n: int, n_min: int) -> float:
    """Pull percentile toward 0.5 when sample is short (stability)."""
    if n >= n_min:
        return raw_pct
    w = n / max(n_min, 1)
    return 0.5 + (raw_pct - 0.5) * w
