import numpy as np
import pandas as pd

from factors.relative_strength import composite_momentum_score, relative_returns_vs_benchmark


def test_relative_returns_no_lookahead():
    idx = pd.date_range("2020-01-01", periods=130, freq="B")
    n = len(idx)
    stock = pd.Series(np.cumprod(np.full(n, 1.001)), index=idx) * 100
    bench = pd.Series(np.cumprod(np.full(n, 1.0005)), index=idx) * 100
    ex = relative_returns_vs_benchmark(stock, bench)
    assert ex["excess_20d"] is not None
    comp = composite_momentum_score(ex)
    assert comp is not None
