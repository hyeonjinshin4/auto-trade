import numpy as np
import pandas as pd

from configs.adaptive_regime import AdaptiveRegimeConfig
from regime_engine import RegimeEnginePersistentState, compute_adaptive_regime
from trading_rules.engine_config import EngineConfig
from trading_rules.models import RegimeThresholds
from trading_rules.regime_score import RegimeFeatureScores


def _series(n: int, drift: float = 0.0) -> pd.Series:
    rng = np.random.default_rng(42)
    x = 100 * np.exp(np.cumsum(rng.normal(drift, 0.01, size=n)))
    return pd.Series(x)


def test_compute_adaptive_regime_runs():
    n = 300
    rng = np.random.default_rng(1)
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    vix = pd.Series(np.clip(15 + np.cumsum(rng.normal(0, 0.3, n)), 10, 40), index=idx)
    kc = _series(n, 0.0003)
    kc.index = idx[: len(kc)]
    kv = pd.Series(np.abs(rng.normal(1e9, 1e8, n)), index=idx)
    feats = RegimeFeatureScores(
        macro=50.0,
        trend_ma=55.0,
        vol_regime=45.0,
        flow=50.0,
        risk_appetite=52.0,
    )
    ec = EngineConfig()
    rb = RegimeThresholds()
    out, st = compute_adaptive_regime(
        vix=vix,
        kospi_close=kc,
        kospi_volume=kv,
        feats=feats,
        engine_cfg=ec,
        rulebook_regime=rb,
        cfg=AdaptiveRegimeConfig(),
        state=RegimeEnginePersistentState(),
        stock_atr_ratio=1.1,
    )
    assert out.volatility_regime in {"low", "mid", "high"}
    assert out.trend_regime in {"down", "flat", "up"}
    assert 0.0 <= out.regime_score_smoothed <= 100.0
    assert st.smoothed_regime_score == out.regime_score_smoothed
    assert out.dynamic_vix_risk_off > 0
