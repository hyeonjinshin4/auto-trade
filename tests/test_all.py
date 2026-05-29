"""
진입·VIX 사이징·국면 veto 관련 통합 검증 (기본값 완화 시나리오).
"""
from __future__ import annotations

from dataclasses import replace

from trading_rules.engine_config import EngineConfig, ScoreThresholds, VolTargetingParams
from trading_rules.scoring import entry_tier_from_score
from trading_rules.sizing import vix_size_multiplier


def test_full_entry_at_72_with_threshold_70() -> None:
    """adjusted=72, full 기준 70 → full 티어."""
    base = EngineConfig()
    ec = replace(
        base,
        score_thresholds=ScoreThresholds(full_entry_min=70.0, half_entry_min=55.0),
        conflict=replace(base.conflict, regime_score_hard_veto_below=10.0),
    )
    assert entry_tier_from_score(72.0, 50.0, ec) == "full"


def test_vix_24_uses_scale_between_085() -> None:
    """VIX가 soft~hard 사이일 때 TRADING_VIX_SCALE_MID(예: 0.85) 적용."""
    p = VolTargetingParams(
        vix_soft_above=22.0,
        vix_hard_above=30.0,
        scale_below_soft=1.0,
        scale_between=0.85,
        scale_above_hard=0.5,
        high_stock_vol_scale=0.5,
    )
    assert vix_size_multiplier(24.0, p) == 0.85


def test_regime_score_20_no_tier_skip_when_veto_10() -> None:
    """regime_score=20 일 때 veto=10 이면 entry_tier_from_score 의 regime 하드 skip 에 안 걸림."""
    base = EngineConfig()
    ec_new = replace(
        base,
        score_thresholds=ScoreThresholds(full_entry_min=70.0, half_entry_min=55.0),
        conflict=replace(base.conflict, regime_score_hard_veto_below=10.0),
    )
    assert entry_tier_from_score(72.0, 20.0, ec_new) == "full"


def test_regime_score_20_skipped_when_veto_25_legacy() -> None:
    """구 기준 veto=25 이면 regime_score=20 에서 진입 차단(회귀 문서용)."""
    base = EngineConfig()
    ec_old = replace(
        base,
        score_thresholds=ScoreThresholds(full_entry_min=70.0, half_entry_min=55.0),
        conflict=replace(base.conflict, regime_score_hard_veto_below=25.0),
    )
    assert entry_tier_from_score(72.0, 20.0, ec_old) == "skip"
