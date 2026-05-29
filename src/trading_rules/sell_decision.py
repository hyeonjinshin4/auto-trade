"""
보유 종목 매도 판단 — 우선순위 고정 단일 액션.
"""
from __future__ import annotations

from dataclasses import dataclass

from trading_rules.models import SellRuleParams


@dataclass(frozen=True)
class SellDecision:
    action: str  # hold | hard_stop | soft_stop | take_profit_1 | take_profit_2 | trail_stop | time_stop | ta_sell
    sell_ratio: float  # 0.0 | 0.5 | 1.0
    reason: str
    priority: int  # 낮을수록 높은 우선순위


def evaluate_sell(
    *,
    current_price: float,
    entry_price: float,
    highest_price: float,
    holding_days: int,
    atr_value: float | None,
    price_vs_ma20: float,
    ta_signal_count: int,
    ta_signal_score: float,
    tp1_done: bool,
    tp2_done: bool,
    sell: SellRuleParams,
) -> SellDecision:
    """매도 우선순위 1~7 순서대로 첫 매칭만 반환."""
    hold = SellDecision("hold", 0.0, "보유 유지", 99)

    if entry_price <= 0 or current_price <= 0:
        return SellDecision("hold", 0.0, "가격 데이터 부족", 99)

    profit_pct = (current_price - entry_price) / entry_price
    hp = max(highest_price, entry_price, current_price)

    # 1. Hard Stop — 전량
    if profit_pct <= -sell.hard_stop_loss_pct:
        return SellDecision(
            "hard_stop",
            1.0,
            f"Hard Stop {profit_pct * 100:.2f}% ≤ -{sell.hard_stop_loss_pct * 100:.1f}%",
            1,
        )

    # 2. TA 매도 — 전량
    ta_ok = ta_signal_count >= sell.ta_sell_min_signals and ta_signal_score >= sell.ta_sell_score_min
    if sell.ta_sell_ma20_confirm:
        ta_ok = ta_ok and price_vs_ma20 > 0 and price_vs_ma20 <= 1.0
    if ta_ok:
        return SellDecision(
            "ta_sell",
            1.0,
            f"TA 매도 시그널={ta_signal_count}점수={ta_signal_score:.0f} MA20비={price_vs_ma20:.3f}",
            2,
        )

    # 3. Soft Stop — 절반
    if sell.soft_stop_enabled and profit_pct <= -sell.soft_stop_loss_pct:
        ma_ok = not sell.soft_stop_ma_confirm or (price_vs_ma20 > 0 and price_vs_ma20 <= 1.0)
        if ma_ok:
            return SellDecision(
                "soft_stop",
                sell.soft_stop_sell_ratio,
                f"Soft Stop {profit_pct * 100:.2f}% ≤ -{sell.soft_stop_loss_pct * 100:.1f}% "
                f"MA20비={price_vs_ma20:.3f}",
                3,
            )

    # 4. 1차 익절 — 40%
    if not tp1_done and profit_pct >= sell.take_profit_1_pct:
        return SellDecision(
            "take_profit_1",
            sell.take_profit_1_ratio,
            f"1차 익절 +{profit_pct * 100:.1f}% ≥ +{sell.take_profit_1_pct * 100:.0f}%",
            4,
        )

    # 5. 2차 익절 — 30%
    if not tp2_done and profit_pct >= sell.take_profit_2_pct:
        return SellDecision(
            "take_profit_2",
            sell.take_profit_2_ratio,
            f"2차 익절 +{profit_pct * 100:.1f}% ≥ +{sell.take_profit_2_pct * 100:.0f}%",
            5,
        )

    # 6. 트레일 스탑 — 전량
    if profit_pct >= sell.trailing_activate_pct and hp > 0:
        trail_stop = sell.effective_trail_stop(hp, profit_pct, atr_value)
        if current_price <= trail_stop:
            tw = sell.trailing_width(profit_pct) * 100.0
            return SellDecision(
                "trail_stop",
                1.0,
                f"트레일 고가={hp:.0f} 폭={tw:.1f}% 스탑={trail_stop:.0f} cur={current_price:.0f}",
                6,
            )

    # 7. Time Stop — 전량
    if holding_days > sell.time_stop_days and profit_pct < sell.time_stop_min_pnl:
        return SellDecision(
            "time_stop",
            1.0,
            f"Time Stop {holding_days}일 > {sell.time_stop_days}일, 수익 {profit_pct * 100:.2f}% < +{sell.time_stop_min_pnl * 100:.0f}%",
            7,
        )

    return hold
