from __future__ import annotations

from .engine_config import LiquidityParams


def passes_liquidity_filter(
    daily_volume_shares: float,
    daily_trade_value_krw: float,
    spread_bps: float | None,
    p: LiquidityParams,
) -> tuple[bool, str]:
    if p.min_daily_volume_shares > 0 and daily_volume_shares < p.min_daily_volume_shares:
        return False, "거래량 부족"
    if p.min_daily_trade_value_krw > 0 and daily_trade_value_krw < p.min_daily_trade_value_krw:
        return False, "거래대금 부족"
    if spread_bps is not None and spread_bps > p.max_spread_bps:
        return False, "스프레드 과대"
    return True, "ok"
