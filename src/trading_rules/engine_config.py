from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class ScoreWeights:
    """signal_score 가중치. 값은 비율(합 1.0); 엔진 로드 시 검증됨."""

    trend: float = 0.3
    volume: float = 0.2
    regime: float = 0.3
    sector: float = 0.1
    liquidity: float = 0.1

    def __post_init__(self) -> None:
        tot = self.trend + self.volume + self.regime + self.sector + self.liquidity
        if not math.isclose(tot, 1.0, rel_tol=0.0, abs_tol=1e-5):
            raise ValueError(f"ScoreWeights 합계가 1.0이어야 합니다 (현재 {tot:.6f})")


@dataclass(frozen=True)
class ScoreThresholds:
    full_entry_min: float = 70.0
    half_entry_min: float = 55.0


@dataclass(frozen=True)
class RegimeScoreWeights:
    """regime_score 0~100 하위 구성 (미입력 시 중립 50으로 채움). 합 1.0."""

    macro: float = 0.25
    trend_ma: float = 0.25
    volatility: float = 0.2
    flow: float = 0.15
    risk_appetite: float = 0.15

    def __post_init__(self) -> None:
        tot = self.macro + self.trend_ma + self.volatility + self.flow + self.risk_appetite
        if not math.isclose(tot, 1.0, rel_tol=0.0, abs_tol=1e-5):
            raise ValueError(f"RegimeScoreWeights 합계가 1.0이어야 합니다 (현재 {tot:.6f})")


@dataclass(frozen=True)
class ExitThresholds:
    time_stop_max_days: int = 10
    time_stop_min_pnl_pct: float = 0.02
    atr_expansion_exit_mult: float = 2.0
    earnings_reduce_within_days: int = 3
    major_macro_reduce: bool = True
    liquidity_decline_mult: float = 0.5


@dataclass(frozen=True)
class VolTargetingParams:
    """시장/종목 변동성에 따른 사이즈 스케일. vix_soft_above < vix_hard_above 여야 함."""

    vix_soft_above: float = 25.0
    vix_hard_above: float = 30.0
    scale_below_soft: float = 1.0
    scale_between: float = 0.85
    scale_above_hard: float = 0.5
    high_stock_vol_scale: float = 0.5

    def __post_init__(self) -> None:
        if self.vix_soft_above >= self.vix_hard_above:
            raise ValueError(
                f"vix_soft_above({self.vix_soft_above}) >= vix_hard_above({self.vix_hard_above}) — 설정 오류"
            )


@dataclass(frozen=True)
class CorrelationParams:
    max_pair_corr: float = 0.8
    pair_reduce_factor: float = 0.5


@dataclass(frozen=True)
class LiquidityParams:
    min_daily_volume_shares: float = 0.0
    min_daily_trade_value_krw: float = 0.0
    max_spread_bps: float = 30.0


@dataclass(frozen=True)
class SlippageParams:
    half_spread_frac: float = 0.0005
    impact_coef: float = 0.1


@dataclass(frozen=True)
class CommissionParams:
    """
    증권사 수수료 (매수·매도 각 1회, 통상 동일율 가정).
    값은 소수: 0.00147 = 0.147%, 0.0025 = 0.25%.
    """

    kr_one_way: float = 0.00147
    us_one_way: float = 0.0025


@dataclass(frozen=True)
class PortfolioHeatParams:
    max_total_open_risk_pct: float = 0.06


@dataclass(frozen=True)
class DailyRiskParams:
    max_daily_loss_pct: float = 0.03
    max_weekly_loss_pct: float = 0.07
    cooldown_days_after_breach: int = 1


@dataclass(frozen=True)
class ConflictPolicy:
    """
    룰 충돌 시 우선순위: 국면·리스크가 기술 시그널을 '깎거나' 진입을 막음.
    """

    regime_score_hard_veto_below: float = 10.0
    regime_score_cap_signal_above: float = 40.0
    cap_signal_when_regime_low: float = 62.0
    risk_off_cap_signal: float = 60.0
    vix_spike_extra_penalty: float = 10.0


@dataclass(frozen=True)
class EngineConfig:
    score_weights: ScoreWeights = ScoreWeights()
    score_thresholds: ScoreThresholds = ScoreThresholds()
    regime_weights: RegimeScoreWeights = RegimeScoreWeights()
    exit_thresholds: ExitThresholds = ExitThresholds()
    vol_targeting: VolTargetingParams = VolTargetingParams()
    correlation: CorrelationParams = CorrelationParams()
    liquidity: LiquidityParams = LiquidityParams()
    slippage: SlippageParams = SlippageParams()
    commission: CommissionParams = CommissionParams()
    portfolio_heat: PortfolioHeatParams = PortfolioHeatParams()
    daily_risk: DailyRiskParams = DailyRiskParams()
    conflict: ConflictPolicy = ConflictPolicy()
