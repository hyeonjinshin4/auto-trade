"""
Adaptive regime & ATR-stop tuning — config only (no pandas here).

Engine reads these defaults; optional env overrides via regime_engine.load_config_from_env.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from trading_rules.engine_config import ScoreWeights


@dataclass(frozen=True)
class PercentileWindowConfig:
    """Rolling window for percentile ranks (trading days)."""

    vix: int = 252
    realized_vol: int = 60
    min_effective: int = 40  # below this, percentiles widen toward 0.5 (uncertainty)


@dataclass(frozen=True)
class VolatilityRegimeSplitConfig:
    """Split realized / VIX composite percentile into low / mid / high."""

    low_below: float = 0.34
    mid_below: float = 0.67


@dataclass(frozen=True)
class TrendRegimeSplitConfig:
    """20d vs 60d return spread thresholds (fraction)."""

    down_below: float = -0.02
    up_above: float = 0.02


@dataclass(frozen=True)
class LiquidityRegimeSplitConfig:
    """Volume vs 20d MA ratio thresholds."""

    stress_below: float = 0.85
    easy_above: float = 1.15


@dataclass(frozen=True)
class DynamicVixThresholdConfig:
    """Map VIX percentile (0–1) to effective RegimeThresholds.vix_risk_off style levels."""

    risk_off_low_pct: float = 24.0
    risk_off_high_pct: float = 36.0
    tight_trailing_add: float = 5.0


@dataclass(frozen=True)
class ConflictTaperConfig:
    """Taper ConflictPolicy caps when volatility regime is calm (config-driven, bounded)."""

    regime_cap_low_vol: float = 68.0
    regime_cap_high_vol: float = 58.0
    risk_off_cap_low_vol: float = 64.0
    risk_off_cap_high_vol: float = 54.0


@dataclass(frozen=True)
class AtrStopAdaptConfig:
    """Scale hard stop fraction by ATR ratio proxy (atr_now / baseline)."""

    ratio_low: float = 0.75
    ratio_high: float = 1.6
    mult_at_low: float = 0.92
    mult_at_high: float = 1.22


@dataclass(frozen=True)
class RegimeSmoothingConfig:
    """EMA on continuous regime score + discrete label hysteresis."""

    score_ema_alpha: float = 0.28
    hysteresis_consecutive: int = 2


@dataclass(frozen=True)
class VolatilityRegimeWeights:
    """Optional ScoreWeights overrides by volatility bucket (None = use engine base)."""

    low: ScoreWeights | None = None
    mid: ScoreWeights | None = None
    high: ScoreWeights | None = None


@dataclass(frozen=True)
class AdaptiveRegimeConfig:
    percentile_windows: PercentileWindowConfig = field(default_factory=PercentileWindowConfig)
    vol_split: VolatilityRegimeSplitConfig = field(default_factory=VolatilityRegimeSplitConfig)
    trend_split: TrendRegimeSplitConfig = field(default_factory=TrendRegimeSplitConfig)
    liq_split: LiquidityRegimeSplitConfig = field(default_factory=LiquidityRegimeSplitConfig)
    vix_thresholds: DynamicVixThresholdConfig = field(default_factory=DynamicVixThresholdConfig)
    conflict_taper: ConflictTaperConfig = field(default_factory=ConflictTaperConfig)
    atr_stop: AtrStopAdaptConfig = field(default_factory=AtrStopAdaptConfig)
    smoothing: RegimeSmoothingConfig = field(default_factory=RegimeSmoothingConfig)
    vol_weights: VolatilityRegimeWeights = field(default_factory=VolatilityRegimeWeights)
