"""Realized volatility from close series (log returns)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def realized_volatility(close: pd.Series, window: int, *, annualization: float = 252.0) -> pd.Series:
    """Annualized realized vol: rolling std of log returns * sqrt(annualization)."""
    c = close.astype(float)
    lr = np.log(c / c.shift(1))
    return lr.rolling(window=window, min_periods=max(5, min(window, 10))).std() * np.sqrt(
        annualization
    )
