"""FDR 일봉 캐시."""
from __future__ import annotations

import pandas as pd

from fdr_ohlcv_cache import clear_ohlcv_cache, get_ohlcv


def test_ohlcv_cache_reuses_same_fetch(monkeypatch) -> None:
    clear_ohlcv_cache()
    calls = {"n": 0}

    def fake_reader(sym: str, start: str, end: str) -> pd.DataFrame:
        calls["n"] += 1
        return pd.DataFrame(
            {"Close": [100.0 + i for i in range(40)], "High": [101.0] * 40, "Low": [99.0] * 40},
            index=pd.date_range("2024-01-01", periods=40, freq="D"),
        )

    import FinanceDataReader as fdr  # type: ignore[import-untyped]

    monkeypatch.setattr(fdr, "DataReader", fake_reader)
    monkeypatch.setenv("FDR_OHLCV_CACHE_SEC", "600")

    a = get_ohlcv("005930", lookback_days=120)
    b = get_ohlcv("005930", lookback_days=40)
    assert a is not None and b is not None
    assert calls["n"] == 1
