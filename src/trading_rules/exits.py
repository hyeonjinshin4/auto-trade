from __future__ import annotations

from dataclasses import dataclass

from .engine_config import ExitThresholds


@dataclass(frozen=True)
class ExitContext:
    holding_days: int
    pnl_pct: float
    atr_now: float
    atr_baseline: float | None
    earnings_in_days: int | None = None
    major_macro_today: bool = False
    trade_value_ratio_vs_20d: float | None = None


def evaluate_exit_signals(ctx: ExitContext, th: ExitThresholds) -> list[str]:
    """
    청산/축소 권고 사유 목록 (비어 있으면 유지).
    실행기에서 우선순위·부분매도 비중은 별도 정책으로 처리.
    """
    out: list[str] = []

    if ctx.holding_days > th.time_stop_max_days and ctx.pnl_pct < th.time_stop_min_pnl_pct:
        out.append("time_stop:장기간 저수익")

    if ctx.atr_baseline and ctx.atr_baseline > 0:
        expansion = ctx.atr_now / ctx.atr_baseline
        if expansion >= th.atr_expansion_exit_mult:
            out.append("vol_exit:ATR급팽창")

    if ctx.earnings_in_days is not None and 0 <= ctx.earnings_in_days <= th.earnings_reduce_within_days:
        out.append("event_risk:실적임박_비중축소권고")

    if th.major_macro_reduce and ctx.major_macro_today:
        out.append("event_risk:주요매크로일_리스크축소")

    if (
        ctx.trade_value_ratio_vs_20d is not None
        and ctx.trade_value_ratio_vs_20d < th.liquidity_decline_mult
    ):
        out.append("liquidity_exit:거래대금급감")

    return out
