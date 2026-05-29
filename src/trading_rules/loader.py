from __future__ import annotations

import os

from dotenv import load_dotenv

from .engine_config import (
    CommissionParams,
    ConflictPolicy,
    CorrelationParams,
    DailyRiskParams,
    EngineConfig,
    ExitThresholds,
    LiquidityParams,
    PortfolioHeatParams,
    RegimeScoreWeights,
    ScoreThresholds,
    ScoreWeights,
    SlippageParams,
    VolTargetingParams,
)
from .models import (
    AtrTrailingParams,
    BuyRuleParams,
    ForbiddenRule,
    FundamentalFilters,
    PositionRules,
    RegimeThresholds,
    Rulebook,
    SellRuleParams,
    default_forbidden_rules,
)

load_dotenv(".env")


def _f(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    return float(raw)


def _i(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    return int(float(raw))


def _b(name: str, default: bool) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "y"}


def get_engine_config() -> EngineConfig:
    """스코어·충돌·청산·유동성·히트 등 엔진 파라미터."""
    sw = ScoreWeights(
        trend=_f("TRADING_W_TREND", 0.3),
        volume=_f("TRADING_W_VOLUME", 0.2),
        regime=_f("TRADING_W_REGIME", 0.3),
        sector=_f("TRADING_W_SECTOR", 0.1),
        liquidity=_f("TRADING_W_LIQUIDITY", 0.1),
    )
    st = ScoreThresholds(
        full_entry_min=_f("TRADING_SCORE_FULL", 70.0),
        half_entry_min=_f("TRADING_SCORE_HALF", 55.0),
    )
    rw = RegimeScoreWeights(
        macro=_f("TRADING_RW_MACRO", 0.25),
        trend_ma=_f("TRADING_RW_TREND", 0.25),
        volatility=_f("TRADING_RW_VOL", 0.2),
        flow=_f("TRADING_RW_FLOW", 0.15),
        risk_appetite=_f("TRADING_RW_RISK", 0.15),
    )
    ex = ExitThresholds(
        time_stop_max_days=_i("TRADING_TIME_STOP_DAYS", 10),
        time_stop_min_pnl_pct=_f("TRADING_TIME_STOP_MIN_PNL", 0.02),
        atr_expansion_exit_mult=_f("TRADING_ATR_EXPAND_MULT", 2.0),
        earnings_reduce_within_days=_i("TRADING_EARNINGS_DAYS", 3),
        major_macro_reduce=_b("TRADING_MACRO_REDUCE", True),
        liquidity_decline_mult=_f("TRADING_LIQ_DECLINE_MULT", 0.5),
    )
    vt = VolTargetingParams(
        vix_soft_above=_f("TRADING_VIX_SOFT", 25.0),
        vix_hard_above=_f("TRADING_VIX_HARD", 30.0),
        scale_below_soft=_f("TRADING_VIX_SCALE_LOW", 1.0),
        scale_between=_f("TRADING_VIX_SCALE_MID", 0.85),
        scale_above_hard=_f("TRADING_VIX_SIZE_SCALE", 0.5),
        high_stock_vol_scale=_f("TRADING_STOCK_VOL_SCALE", 0.5),
    )
    cp = CorrelationParams(
        max_pair_corr=_f("TRADING_MAX_PAIR_CORR", 0.8),
        pair_reduce_factor=_f("TRADING_CORR_REDUCE", 0.5),
    )
    lq = LiquidityParams(
        min_daily_volume_shares=_f("TRADING_MIN_DAILY_VOL", 0.0),
        min_daily_trade_value_krw=_f("TRADING_MIN_TRADE_VALUE_KRW", 0.0),
        max_spread_bps=_f("TRADING_MAX_SPREAD_BPS", 30.0),
    )
    sp = SlippageParams(
        half_spread_frac=_f("TRADING_HALF_SPREAD_FRAC", 0.0005),
        impact_coef=_f("TRADING_IMPACT_COEF", 0.1),
    )
    cm = CommissionParams(
        kr_one_way=_f("COMMISSION_KR_ONEWAY", 0.00147),
        us_one_way=_f("COMMISSION_US_ONEWAY", 0.0025),
    )
    ph = PortfolioHeatParams(max_total_open_risk_pct=_f("TRADING_MAX_PORT_HEAT", 0.06))
    dr = DailyRiskParams(
        max_daily_loss_pct=_f("TRADING_MAX_DAILY_LOSS", 0.03),
        max_weekly_loss_pct=_f("TRADING_MAX_WEEKLY_LOSS", 0.07),
        cooldown_days_after_breach=_i("TRADING_COOLDOWN_DAYS", 1),
    )
    cf = ConflictPolicy(
        regime_score_hard_veto_below=_f("TRADING_REGIME_VETO", 10.0),
        regime_score_cap_signal_above=_f("TRADING_REGIME_CAP_ABOVE", 40.0),
        cap_signal_when_regime_low=_f("TRADING_REGIME_CAP_SCORE", 62.0),
        risk_off_cap_signal=_f("TRADING_RISK_OFF_CAP", 60.0),
        vix_spike_extra_penalty=_f("TRADING_VIX_SPIKE_PENALTY", 10.0),
    )
    return EngineConfig(
        score_weights=sw,
        score_thresholds=st,
        regime_weights=rw,
        exit_thresholds=ex,
        vol_targeting=vt,
        correlation=cp,
        liquidity=lq,
        slippage=sp,
        commission=cm,
        portfolio_heat=ph,
        daily_risk=dr,
        conflict=cf,
    )


def get_rulebook() -> Rulebook:
    """
    환경변수로 일부만 덮어쓸 수 있음 (없으면 문서화된 기본값).
    접두사 예: TRADING_STOP_LOSS_PCT, TRADING_VIX_RISK_OFF, ...
    """
    if (os.getenv("SECURE_STRICT") or "").strip().lower() in {"1", "true", "yes", "y"}:
        from secure_env import validate_kis_credentials

        min_k = int(os.getenv("KIS_MIN_KEY_LEN", "8"))
        min_s = int(os.getenv("KIS_MIN_SECRET_LEN", "8"))
        validate_kis_credentials(min_key_len=min_k, min_secret_len=min_s)

    regime = RegimeThresholds(
        kospi_ma_short=_i("TRADING_KOSPI_MA_SHORT", 20),
        kospi_ma_long=_i("TRADING_KOSPI_MA_LONG", 60),
        vix_risk_off=_f("TRADING_VIX_RISK_OFF", 30.0),
        vix_tight_trailing=_f("TRADING_VIX_TIGHT_TRAILING", 35.0),
    )
    buy = BuyRuleParams(
        pullback_min_pct=_f("TRADING_PULLBACK_MIN_PCT", 0.05),
        pullback_max_pct=_f("TRADING_PULLBACK_MAX_PCT", 0.10),
        volume_surge_vs_20d_avg=_f("TRADING_VOLUME_SURGE_MULT", 1.5),
        chase_consecutive_up_days_block=_i("TRADING_CHASE_BLOCK_DAYS", 5),
    )
    hard_stop = _f("TRADING_HARD_STOP_PCT", _f("TRADING_STOP_LOSS_PCT", 0.075))
    sell = SellRuleParams(
        hard_stop_loss_pct=hard_stop,
        soft_stop_loss_pct=_f("TRADING_SOFT_STOP_PCT", 0.055),
        soft_stop_enabled=_b("TRADING_SOFT_STOP_ENABLED", True),
        soft_stop_ma_confirm=_b("TRADING_SOFT_STOP_MA_CONFIRM", True),
        soft_stop_sell_ratio=_f("TRADING_SOFT_STOP_RATIO", 0.50),
        take_profit_1_pct=_f("TRADING_TP1_PCT", 0.14),
        take_profit_1_ratio=_f("TRADING_TP1_RATIO", 0.40),
        take_profit_2_pct=_f("TRADING_TP2_PCT", 0.28),
        take_profit_2_ratio=_f("TRADING_TP2_RATIO", 0.30),
        trailing_activate_pct=_f(
            "TRADING_TRAIL_ACTIVATE_PCT",
            _f("TRADING_TRAILING_ACTIVATE_PCT", 0.12),
        ),
        trailing_width_stage1=_f("TRADING_TRAIL_W1_PCT", 0.13),
        trailing_width_stage2=_f("TRADING_TRAIL_W2_PCT", 0.11),
        trailing_width_stage3=_f("TRADING_TRAIL_W3_PCT", 0.09),
        trailing_stage2_from=_f(
            "TRADING_TRAIL_STAGE2_FROM",
            _f("TRADING_TRAIL_STAGE2_FROM_GAIN", 0.28),
        ),
        trailing_stage3_from=_f(
            "TRADING_TRAIL_STAGE3_FROM",
            _f("TRADING_TRAIL_STAGE3_FROM_GAIN", 0.45),
        ),
        use_atr_trailing=_b("TRADING_USE_ATR_TRAILING", True),
        atr_trailing_multiplier=_f("TRADING_ATR_TRAIL_MULT", 2.3),
        time_stop_days=_i("TRADING_TIME_STOP_DAYS", 10),
        time_stop_min_pnl=_f("TRADING_TIME_STOP_MIN_PNL", 0.02),
        ta_sell_min_signals=_i("TRADING_TA_SELL_MIN_SIGNALS", 2),
        ta_sell_score_min=_f("TRADING_TA_SELL_SCORE_MIN", 28.0),
        ta_sell_ma20_confirm=_b("TRADING_TA_SELL_MA20_CONFIRM", True),
        ta_sell_cooldown_hours=_i("TRADING_TA_SELL_COOLDOWN_H", 4),
    )
    atr = AtrTrailingParams(
        atr_period_short=_i("TRADING_ATR_PERIOD", 14),
        mult_default=_f("TRADING_ATR_MULT", 3.0),
        mult_high_vol=_f("TRADING_ATR_MULT_HIGH_VOL", 3.5),
    )
    position = PositionRules(
        max_portfolio_risk_per_trade_pct=_f("TRADING_MAX_RISK_PER_TRADE_PCT", 0.05),
        min_portfolio_risk_per_trade_pct=_f("TRADING_MIN_RISK_PER_TRADE_PCT", 0.03),
        max_single_name_pct_fund_style=_f("TRADING_MAX_NAME_PCT", 0.08),
        max_sector_pct=_f("TRADING_MAX_SECTOR_PCT", 0.25),
        min_cash_pct=_f("TRADING_MIN_CASH_PCT", 0.05),
        max_cash_bear_pct=_f("TRADING_MAX_CASH_BEAR_PCT", 0.70),
        min_cash_bear_pct=_f("TRADING_MIN_CASH_BEAR_PCT", 0.50),
    )
    mcap_bn_raw = (os.getenv("TRADING_MIN_MCAP_BN") or os.getenv("AUTO_SCAN_MIN_MCAP_BN") or "").strip()
    fundamental = FundamentalFilters(
        min_roe_pct=_f("TRADING_MIN_ROE_PCT", 12.0),
        # 십억원 단위. universe_scan KRX 스캔 시총 하한과 동일 키(TRADING 우선, 없으면 AUTO_SCAN_MIN_MCAP_BN).
        min_market_cap_krw_bn=float(mcap_bn_raw) if mcap_bn_raw else 0.5,
    )

    extra = _parse_extra_forbidden()
    forbidden: tuple[ForbiddenRule, ...] = default_forbidden_rules() + extra

    return Rulebook(
        regime=regime,
        buy=buy,
        sell=sell,
        atr=atr,
        position=position,
        fundamental=fundamental,
        forbidden=forbidden,
    )


def _parse_extra_forbidden() -> tuple[ForbiddenRule, ...]:
    raw = (os.getenv("TRADING_EXTRA_FORBIDDEN") or "").strip()
    if not raw:
        return ()
    out: list[ForbiddenRule] = []
    for i, part in enumerate(raw.split("|")):
        part = part.strip()
        if part:
            out.append(ForbiddenRule(f"extra_{i}", part))
    return tuple(out)
