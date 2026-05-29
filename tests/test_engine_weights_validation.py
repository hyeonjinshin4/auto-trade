import pytest

from trading_rules.engine_config import RegimeScoreWeights, ScoreWeights, VolTargetingParams


def test_score_weights_sum_invalid():
    with pytest.raises(ValueError, match="ScoreWeights"):
        ScoreWeights(trend=0.5, volume=0.5, regime=0.1, sector=0.0, liquidity=0.0)


def test_regime_score_weights_sum_invalid():
    with pytest.raises(ValueError, match="RegimeScoreWeights"):
        RegimeScoreWeights(macro=0.5, trend_ma=0.5, volatility=0.1, flow=0.0, risk_appetite=0.0)


def test_vix_soft_hard_order_invalid():
    with pytest.raises(ValueError, match="vix_soft"):
        VolTargetingParams(vix_soft_above=35.0, vix_hard_above=30.0)


def test_vix_soft_hard_valid_boundary():
    VolTargetingParams(vix_soft_above=22.0, vix_hard_above=30.0)
