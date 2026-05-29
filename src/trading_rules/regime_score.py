from __future__ import annotations

from dataclasses import dataclass

from .engine_config import RegimeScoreWeights, ScoreWeights
from .models import MarketRegime, MarketRegimeSnapshot


@dataclass(frozen=True)
class RegimeFeatureScores:
    """
    각 축 0~100 (높을수록 롱/리스크온에 유리). None이면 해당 축은 제외 후 가중 재분배.
    """

    macro: float | None = None
    trend_ma: float | None = None
    vol_regime: float | None = None
    flow: float | None = None
    risk_appetite: float | None = None


def aggregate_regime_score(features: RegimeFeatureScores, w: RegimeScoreWeights) -> float:
    pairs = [
        (features.macro, w.macro),
        (features.trend_ma, w.trend_ma),
        (features.vol_regime, w.volatility),
        (features.flow, w.flow),
        (features.risk_appetite, w.risk_appetite),
    ]
    vals: list[float] = []
    weights: list[float] = []
    for v, wt in pairs:
        if v is not None and 0.0 <= v <= 100.0:
            vals.append(v)
            weights.append(wt)
    if not vals:
        return 50.0
    sw = sum(weights)
    if sw <= 0:
        return 50.0
    return sum(v * (wt / sw) for v, wt in zip(vals, weights, strict=True))


def infer_regime_features_from_snapshot(
    snap: MarketRegimeSnapshot,
    *,
    vix_level: float | None,
    vix_calm: float = 15.0,
    vix_stress: float = 35.0,
) -> RegimeFeatureScores:
    """스냅샷·VIX로 하위 점수 추정 (데이터 없으면 None)."""

    trend: float | None = None
    if snap.kospi_above_ma20 is True and snap.kospi_above_ma60 is True:
        trend = 85.0
    elif snap.kospi_above_ma60 is False:
        trend = 25.0
    elif snap.kospi_above_ma20 is True:
        trend = 60.0

    vol_r: float | None = None
    if vix_level is not None:
        if vix_level <= vix_calm:
            vol_r = 80.0
        elif vix_level >= vix_stress:
            vol_r = 20.0
        else:
            vol_r = 80.0 - (vix_level - vix_calm) / (vix_stress - vix_calm) * 60.0

    flow: float | None = None
    if snap.foreign_net_buying_sustained is True:
        flow = 80.0
    elif snap.foreign_heavy_sell is True:
        flow = 20.0

    risk_ap: float | None = None
    if snap.rates_stable_or_cut_expected is True:
        risk_ap = 70.0
    elif snap.rates_spike is True:
        risk_ap = 25.0
    if snap.us_market_crash is True:
        risk_ap = min(risk_ap or 40.0, 15.0)

    macro: float | None = None

    return RegimeFeatureScores(
        macro=macro,
        trend_ma=trend,
        vol_regime=vol_r,
        flow=flow,
        risk_appetite=risk_ap,
    )


def regime_score_from_classification(regime: MarketRegime) -> float:
    """문자열 국면을 대략 점수화 (스코어 미계산 시 보조)."""
    if regime == MarketRegime.RISK_ON:
        return 75.0
    if regime == MarketRegime.RISK_OFF:
        return 25.0
    if regime == MarketRegime.NEUTRAL:
        return 50.0
    return 50.0
