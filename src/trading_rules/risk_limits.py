from __future__ import annotations

from dataclasses import dataclass

from .engine_config import DailyRiskParams, PortfolioHeatParams


@dataclass
class PnlTrackerState:
    """실전에서는 DB/파일로 일·주 누적 손익률을 복원."""

    today_realized_pnl_pct: float = 0.0
    week_realized_pnl_pct: float = 0.0
    cooldown_days_left: int = 0


def trading_allowed_after_loss(
    state: PnlTrackerState,
    params: DailyRiskParams,
) -> tuple[bool, str]:
    if state.cooldown_days_left > 0:
        return False, f"cooldown:{state.cooldown_days_left}d"
    if state.today_realized_pnl_pct <= -params.max_daily_loss_pct:
        return False, "daily_loss_limit"
    if state.week_realized_pnl_pct <= -params.max_weekly_loss_pct:
        return False, "weekly_loss_limit"
    return True, "ok"


def portfolio_heat_ok(open_risk_as_fraction_of_equity: float, p: PortfolioHeatParams) -> bool:
    """열린 포지션의 손절까지 합산 위험이 상한 이하인지."""
    return open_risk_as_fraction_of_equity <= p.max_total_open_risk_pct


def register_daily_breach(state: PnlTrackerState, params: DailyRiskParams) -> None:
    if state.today_realized_pnl_pct <= -params.max_daily_loss_pct:
        state.cooldown_days_left = max(state.cooldown_days_left, params.cooldown_days_after_breach)
