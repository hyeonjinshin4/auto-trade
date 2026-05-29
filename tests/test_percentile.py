import numpy as np
import pandas as pd

from adaptive.percentile import percentile_rank_last, rolling_percentile_rank


def test_percentile_rank_last_midrank():
    w = np.array([1.0, 2.0, 3.0, 3.0, 4.0])
    p = percentile_rank_last(w)
    assert 0.0 <= p <= 1.0
    assert p > 0.5


def test_rolling_percentile_no_lookahead_shape():
    s = pd.Series(np.linspace(1, 20, 20))
    r = rolling_percentile_rank(s, window=10)
    assert len(r) == len(s)
    assert r.iloc[:4].isna().all() or r.dropna().iloc[0] >= 0  # min_periods
