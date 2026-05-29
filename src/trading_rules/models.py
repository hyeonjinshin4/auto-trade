from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MarketRegime(str, Enum):
    """시장 국면 (데이터 연동 전에는 UNKNOWN)."""

    RISK_ON = "risk_on"
    RISK_OFF = "risk_off"
    NEUTRAL = "neutral"
    UNKNOWN = "unknown"


class SectorPhase(str, Enum):
    """경기/인플레이션 국면에 따른 섹터 우선순위 힌트 (로테이션 가이드)."""

    EARLY_CYCLE = "early_cycle"
    RECOVERY = "recovery"
    INFLATION = "inflation"
    RATE_CUT_EXPECTATION = "rate_cut_expectation"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RegimeThresholds:
    """시장 국면 판단용 임계값 (지표 연결 시 사용)."""

    kospi_ma_short: int = 20
    kospi_ma_long: int = 60
    vix_risk_off: float = 30.0
    vix_tight_trailing: float = 35.0


@dataclass(frozen=True)
class BuyRuleParams:
    """매수 규칙. pullback_* 등 *_pct 접미 필드는 '퍼센트 포인트(5.0)'가 아니라 가격 대비 소수 비율(0.05=5%)."""

    pullback_min_pct: float = 0.05
    pullback_max_pct: float = 0.10
    volume_surge_vs_20d_avg: float = 1.5
    chase_consecutive_up_days_block: int = 5
    min_ma_alignment: tuple[int, int] = (20, 60)


@dataclass(frozen=True)
class SellRuleParams:
    """
    매도·손절·익절. *_pct 는 소수 비율(0.075 = 7.5%).
    구 필드명은 @property 로 하위 호환.
    """

    # 손절
    hard_stop_loss_pct: float = 0.075
    soft_stop_loss_pct: float = 0.055
    soft_stop_enabled: bool = True
    soft_stop_ma_confirm: bool = True
    soft_stop_sell_ratio: float = 0.50

    # 분할 익절
    take_profit_1_pct: float = 0.14
    take_profit_1_ratio: float = 0.40
    take_profit_2_pct: float = 0.28
    take_profit_2_ratio: float = 0.30

    # 트레일링
    trailing_activate_pct: float = 0.12
    trailing_width_stage1: float = 0.13
    trailing_width_stage2: float = 0.11
    trailing_width_stage3: float = 0.09
    trailing_stage2_from: float = 0.28
    trailing_stage3_from: float = 0.45

    # ATR 트레일링
    use_atr_trailing: bool = True
    atr_trailing_multiplier: float = 2.3

    # Time Stop
    time_stop_days: int = 15
    time_stop_min_pnl: float = 0.01
    time_stop_early_days: int = 5
    time_stop_early_loss_pct: float = 0.05
    time_stop_hash_spread: int = 4

    # TA 연계
    ta_sell_min_signals: int = 2
    ta_sell_score_min: float = 28.0
    ta_sell_ma20_confirm: bool = True
    ta_sell_cooldown_hours: int = 4

    def trailing_width(self, profit_pct: float) -> float:
        """수익률 구간별 트레일 폭(소수) 반환."""
        if profit_pct >= self.trailing_stage3_from:
            return self.trailing_width_stage3
        if profit_pct >= self.trailing_stage2_from:
            return self.trailing_width_stage2
        return self.trailing_width_stage1

    def effective_trail_stop(
        self,
        highest_price: float,
        current_profit_pct: float,
        atr_value: float | None = None,
    ) -> float:
        """
        트레일 스탑 가격. +45% 이상이면 ATR 스탑과 % 스탑 중 더 높은(유리한) 가격.
        """
        width = self.trailing_width(current_profit_pct)
        pct_stop = highest_price * (1.0 - width)
        if (
            self.use_atr_trailing
            and current_profit_pct >= self.trailing_stage3_from
            and atr_value is not None
            and atr_value > 0
        ):
            atr_stop = highest_price - atr_value * self.atr_trailing_multiplier
            return max(pct_stop, atr_stop)
        return pct_stop

    # --- 하위 호환 alias (구 코드·테스트) ---
    @property
    def trailing_activate_gain_pct(self) -> float:
        return self.trailing_activate_pct

    @property
    def trailing_width_stage1_pct(self) -> float:
        return self.trailing_width_stage1

    @property
    def trailing_width_stage2_pct(self) -> float:
        return self.trailing_width_stage2

    @property
    def trailing_width_stage3_pct(self) -> float:
        return self.trailing_width_stage3

    @property
    def trailing_width_stage2_from_gain_pct(self) -> float:
        return self.trailing_stage2_from

    @property
    def trailing_width_stage3_from_gain_pct(self) -> float:
        return self.trailing_stage3_from

    @property
    def first_take_profit_high_pct(self) -> float:
        return self.take_profit_1_pct

    @property
    def first_take_profit_low_pct(self) -> float:
        return self.take_profit_1_pct

    @property
    def swing_stop_loss_pct(self) -> float:
        return self.soft_stop_loss_pct

    @property
    def fund_stop_loss_low_pct(self) -> float:
        return self.hard_stop_loss_pct

    @property
    def fund_stop_loss_high_pct(self) -> float:
        return self.hard_stop_loss_pct

    @property
    def partial_take_at_fund_gain_pct(self) -> float:
        return self.take_profit_2_pct

    @property
    def partial_take_fraction_min(self) -> float:
        return self.take_profit_1_ratio

    @property
    def partial_take_fraction_max(self) -> float:
        return self.take_profit_2_ratio


@dataclass(frozen=True)
class AtrTrailingParams:
    """ATR 트레일링 (기간·배수)."""

    atr_period_short: int = 14
    atr_period_long: int = 21
    mult_entry_stop_low: float = 2.5
    mult_entry_stop_high: float = 3.0
    mult_default: float = 3.0
    mult_high_vol: float = 3.5
    mult_stable: float = 2.5


@dataclass(frozen=True)
class PositionRules:
    """자금관리·비중."""

    max_portfolio_risk_per_trade_pct: float = 0.05
    min_portfolio_risk_per_trade_pct: float = 0.03
    max_single_name_pct_fund_style: float = 0.08
    single_name_initial_min_pct: float = 0.04
    single_name_initial_max_pct: float = 0.06
    max_sector_pct: float = 0.25
    min_cash_pct: float = 0.05
    max_cash_bear_pct: float = 0.70
    min_cash_bear_pct: float = 0.50
    overheated_cash_min_pct: float = 0.20
    overheated_cash_max_pct: float = 0.40
    typical_positions_min: int = 15
    typical_positions_max: int = 25
    split_buy_1: float = 0.30
    split_buy_2: float = 0.30
    split_buy_3: float = 0.40
    max_single_name_pct_retail: float = 0.20


@dataclass(frozen=True)
class FundamentalFilters:
    """펀더멘털 최소 조건 (데이터 있을 때 스크리닝)."""

    min_roe_pct: float = 12.0
    min_market_cap_krw_bn: float = 0.5
    require_institutional_flow: bool = True


@dataclass(frozen=True)
class ForbiddenRule:
    rule_id: str
    description: str


@dataclass(frozen=True)
class Rulebook:
    """전체 규칙 묶음."""

    regime: RegimeThresholds = field(default_factory=RegimeThresholds)
    buy: BuyRuleParams = field(default_factory=BuyRuleParams)
    sell: SellRuleParams = field(default_factory=SellRuleParams)
    atr: AtrTrailingParams = field(default_factory=AtrTrailingParams)
    position: PositionRules = field(default_factory=PositionRules)
    fundamental: FundamentalFilters = field(default_factory=FundamentalFilters)
    forbidden: tuple[ForbiddenRule, ...] = field(default_factory=tuple)

    def forbidden_list(self) -> list[dict[str, str]]:
        return [{"id": f.rule_id, "desc": f.description} for f in self.forbidden]


@dataclass
class MarketRegimeSnapshot:
    """외부 데이터로 채운 뒤 국면 판단에 사용."""

    kospi_above_ma20: bool | None = None
    kospi_above_ma60: bool | None = None
    nasdaq_uptrend: bool | None = None
    rates_stable_or_cut_expected: bool | None = None
    foreign_net_buying_sustained: bool | None = None
    us_market_crash: bool | None = None
    vix_spike: bool | None = None
    rates_spike: bool | None = None
    foreign_heavy_sell: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def default_forbidden_rules() -> tuple[ForbiddenRule, ...]:
    return (
        ForbiddenRule("no_avg_down_loop", "물타기 무한 반복 금지"),
        ForbiddenRule("no_concentration", "한 종목 몰빵 금지"),
        ForbiddenRule("no_delay_stop", "손절 미루기 금지"),
        ForbiddenRule("no_hope_hold", "근거 없이 '언젠간 오르겠지' 홀딩 금지"),
        ForbiddenRule("no_community_chase", "커뮤니티 추종 매매 금지"),
        ForbiddenRule("no_penny_without_thesis", "이유 없는 저가주 매매 금지"),
        ForbiddenRule("no_excess_leverage", "과도한 레버리지 금지"),
        ForbiddenRule("no_chase_green_bar", "장대양봉·뉴스 직후 FOMO 추격 금지"),
    )


def classify_regime(
    snap: MarketRegimeSnapshot,
    th: RegimeThresholds,
    *,
    vix_level: float | None = None,
) -> tuple[MarketRegime, list[str]]:
    """
    스냅샷 기반 국면 분류. None이 많으면 UNKNOWN.
    """
    reasons: list[str] = []
    unknowns = 0

    def u() -> None:
        nonlocal unknowns
        unknowns += 1

    bull_score = 0
    bear_score = 0

    if snap.kospi_above_ma20 is True and snap.kospi_above_ma60 is True:
        bull_score += 1
        reasons.append("코스피 MA20·MA60 위")
    elif snap.kospi_above_ma60 is False:
        bear_score += 1
        reasons.append("코스피 MA60 아래")
    else:
        u()

    if snap.nasdaq_uptrend is True:
        bull_score += 1
        reasons.append("나스닥 상승 추세")
    elif snap.nasdaq_uptrend is False:
        bear_score += 1
    else:
        u()

    if snap.us_market_crash is True:
        bear_score += 2
        reasons.append("미국 증시 급락")
    elif snap.us_market_crash is False:
        pass
    else:
        u()

    if vix_level is not None and vix_level >= th.vix_risk_off:
        bear_score += 1
        reasons.append(f"VIX 고수준({vix_level:.1f}>={th.vix_risk_off})")
    elif snap.vix_spike is True:
        bear_score += 1
        reasons.append("VIX 급등")
    elif snap.vix_spike is False:
        pass
    else:
        u()

    if snap.rates_spike is True:
        bear_score += 1
        reasons.append("금리 급등")
    elif snap.rates_stable_or_cut_expected is True:
        bull_score += 1
        reasons.append("금리 안정/인하 기대")
    elif snap.rates_spike is False and snap.rates_stable_or_cut_expected is None:
        pass
    else:
        u()

    if snap.foreign_net_buying_sustained is True:
        bull_score += 1
        reasons.append("외국인 순매수 지속")
    elif snap.foreign_heavy_sell is True:
        bear_score += 1
        reasons.append("외국인 대량 매도")
    else:
        u()

    if unknowns >= 4:
        return MarketRegime.UNKNOWN, ["지표 미충분 — 데이터 연동 필요"]

    if bear_score >= 3:
        return MarketRegime.RISK_OFF, reasons
    if bull_score >= 3 and bear_score == 0:
        return MarketRegime.RISK_ON, reasons
    return MarketRegime.NEUTRAL, reasons


def sector_hints(phase: SectorPhase) -> tuple[str, ...]:
    """경기 국면별 섹터 힌트 (참고용)."""
    m: dict[SectorPhase, tuple[str, ...]] = {
        SectorPhase.EARLY_CYCLE: ("반도체", "IT", "성장주"),
        SectorPhase.RECOVERY: ("소비재", "자동차", "산업재"),
        SectorPhase.INFLATION: ("원자재", "에너지", "방산"),
        SectorPhase.RATE_CUT_EXPECTATION: ("바이오", "기술주", "2차전지"),
        SectorPhase.UNKNOWN: (),
    }
    return m.get(phase, ())
