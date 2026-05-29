"""
매매 규칙 + 스코어 엔진 + 청산/사이징/실행현실화 골격.

데이터(feature) 연동 후 pipeline.decide_entry 등을 호출하면 됩니다.
"""

from .loader import get_engine_config, get_rulebook
from .models import (
    ForbiddenRule,
    MarketRegime,
    MarketRegimeSnapshot,
    Rulebook,
    SectorPhase,
    classify_regime,
    default_forbidden_rules,
    sector_hints,
)
from .pipeline import EntryDecision, decide_entry
from .positioning import atr_stop_price, shares_from_portfolio_risk, trailing_stop_from_high
from .regime_score import RegimeFeatureScores, aggregate_regime_score, infer_regime_features_from_snapshot
from .sell_decision import SellDecision, evaluate_sell
from .scoring import (
    SignalComponents,
    apply_conflict_resolution,
    entry_tier_from_score,
    explain_decision,
    position_fraction,
    raw_signal_score,
)

__all__ = [
    "aggregate_regime_score",
    "apply_conflict_resolution",
    "atr_stop_price",
    "classify_regime",
    "decide_entry",
    "default_forbidden_rules",
    "EntryDecision",
    "entry_tier_from_score",
    "explain_decision",
    "ForbiddenRule",
    "get_engine_config",
    "get_rulebook",
    "infer_regime_features_from_snapshot",
    "MarketRegime",
    "MarketRegimeSnapshot",
    "position_fraction",
    "raw_signal_score",
    "RegimeFeatureScores",
    "Rulebook",
    "SectorPhase",
    "sector_hints",
    "SellDecision",
    "evaluate_sell",
    "shares_from_portfolio_risk",
    "SignalComponents",
    "trailing_stop_from_high",
]
