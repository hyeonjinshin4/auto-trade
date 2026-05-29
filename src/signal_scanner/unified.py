"""
통합 점수: 엔진 + TA 매수가점 − TA 매도감점(매수와 동일 점수표).

  combined = clamp(0..100, 엔진 + TA매수×MULT − TA매도×MULT)
  tier: TRADING_SCORE_FULL / HALF

매수 TA: 주요 시그널 ≥ TRADING_TA_ENTRY_MIN_SIGNALS(기본 watchlist min_signals) + 추세필터.
보유 청산: 주요 매도 시그널 ≥2 + 종가≤20일선 (watchlist min_signals, confirm_trend)
"""
from __future__ import annotations

from trading_rules.pipeline import EntryDecision, decide_entry
from trading_rules.scoring import entry_tier_from_score, position_fraction
from trading_rules.loader import get_engine_config
from trading_rules.models import MarketRegimeSnapshot
from trading_rules.sizing import combined_size_multiplier
from trading_rules.scoring import SignalComponents

from signal_scanner.trading import evaluate_ta_buy, evaluate_ta_sell, ta_entry_only, use_ta_signals
from signal_scanner.ta_scoring import ta_point_multiplier, ta_sell_exit_min_points


def decide_entry_unified(
    snap: MarketRegimeSnapshot,
    components: SignalComponents,
    *,
    symbol: str,
    vix_level: float | None,
    risk_off: bool,
    vix_spike: bool,
    is_high_stock_vol: bool = False,
    adaptive: object | None = None,
    use_engine: bool = True,
) -> EntryDecision:
    ec = get_engine_config()

    if use_engine:
        engine = decide_entry(
            snap,
            components,
            vix_level=vix_level,
            risk_off=risk_off,
            vix_spike=vix_spike,
            is_high_stock_vol=is_high_stock_vol,
            adaptive=adaptive,
            symbol=symbol,
        )
    else:
        engine = EntryDecision(
            tier="half",
            position_fraction=0.5,
            signal_raw=50.0,
            signal_adjusted=50.0,
            regime_score=50.0,
            regime_label="neutral",
            conflict_reasons=(),
            size_multiplier=1.0,
            explanation="엔진 미사용",
        )

    if not use_ta_signals():
        return engine

    cd = evaluate_ta_buy(symbol)
    if not cd.ok and "쿨다운" in cd.reason:
        return EntryDecision(
            tier="skip",
            position_fraction=0.0,
            signal_raw=engine.signal_raw,
            signal_adjusted=0.0,
            regime_score=engine.regime_score,
            regime_label=engine.regime_label,
            conflict_reasons=engine.conflict_reasons,
            size_multiplier=1.0,
            explanation=f"[점수] {cd.reason}",
        )

    mult = ta_point_multiplier()
    ta_add = cd.score * mult
    ta_sub = cd.sell_penalty * mult
    raw_buy = cd.detail.raw_points if cd.detail else int(cd.score)
    raw_sell = (
        cd.sell_penalty_detail.raw_points
        if cd.sell_penalty_detail
        else int(cd.sell_penalty)
    )
    br_buy = cd.detail.breakdown if cd.detail else ""
    br_sell = cd.sell_penalty_detail.breakdown if cd.sell_penalty_detail else ""

    def _ta_buy_label() -> str:
        """로그: 실제 합산에 더한 점수(적용). 후보(raw)와 다르면 표시."""
        if raw_buy > 0 and ta_add <= 0:
            return f"TA적용0(후보{raw_buy}×{mult:.1f} 미반영)"
        if mult != 1.0:
            return f"TA{ta_add:.1f}(후보{raw_buy}×{mult:.1f})"
        return f"TA{ta_add:.1f}"

    def _ta_sell_label() -> str:
        if mult != 1.0:
            return f"TA감점{ta_sub:.1f}(후보{raw_sell}×{mult:.1f})"
        return f"TA감점{ta_sub:.1f}"

    if ta_entry_only() or not use_engine:
        combined = min(100.0, max(0.0, ta_add - ta_sub))
        expl = (
            f"[점수] {_ta_buy_label()} − {_ta_sell_label()} "
            f"→ {combined:.1f} [+{br_buy} | -{br_sell}]"
        )
    else:
        combined = min(100.0, max(0.0, engine.signal_adjusted + ta_add - ta_sub))
        expl = (
            f"[점수] 엔진={engine.signal_adjusted:.1f} + {_ta_buy_label()} "
            f"− {_ta_sell_label()} → {combined:.1f} [+{br_buy} | -{br_sell}]"
        )
        if cd.detail and cd.detail.blocked_reason:
            expl += f" | {cd.detail.blocked_reason}"

    tier = entry_tier_from_score(combined, engine.regime_score, ec)
    frac = position_fraction(tier)
    mult_sz = combined_size_multiplier(vix_level, is_high_stock_vol, ec.vol_targeting)
    return EntryDecision(
        tier=tier,
        position_fraction=frac,
        signal_raw=engine.signal_raw,
        signal_adjusted=combined,
        regime_score=engine.regime_score,
        regime_label=engine.regime_label,
        conflict_reasons=engine.conflict_reasons,
        size_multiplier=mult_sz,
        explanation=expl,
    )


def ta_sell_triggers_exit(symbol: str) -> tuple[bool, str]:
    if not use_ta_signals():
        return False, ""
    cd = evaluate_ta_sell(symbol)
    if not cd.ok or cd.detail is None:
        return False, ""
    floor = ta_sell_exit_min_points()
    raw = cd.detail.raw_points
    if cd.detail.score <= 0 or raw < floor:
        return False, ""
    br = cd.detail.breakdown or ""
    return True, f"technical:TA매도={raw}≥{floor}(2+시그널·종가≤20일) [{br}]"
