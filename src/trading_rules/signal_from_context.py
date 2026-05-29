"""
FDR stock_ctx + 시장 스냅샷 → SignalComponents (엔진 파이프라인 입력).
규칙 기반 휴리스틱; 추후 ML/외부 시그널로 교체 가능.

유동성(liquidity) 슬롯: atr_ratio 등으로 42~58 근처 값을 쓰며,
LiquidityParams.min_daily_trade_value_krw 미설정(0)이어도 '항상 0점'이 되지는 않음.
"""
from __future__ import annotations

from typing import Any

from .models import MarketRegimeSnapshot
from .scoring import SignalComponents


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def signal_components_from_context(
    stock_ctx: dict[str, Any],
    snap: MarketRegimeSnapshot,
) -> SignalComponents:
    dchg = stock_ctx.get("daily_change_pct")
    if dchg is None:
        trend = 48.0
    else:
        d = float(dchg)
        trend = 50.0 + d * 400.0
        trend = _clamp(trend)

    if snap.kospi_above_ma20 is True and snap.kospi_above_ma60 is True:
        trend = _clamp(trend + 8.0)
    elif snap.kospi_above_ma20 is False and snap.kospi_above_ma60 is False:
        trend = _clamp(trend - 10.0)

    streak = int(stock_ctx.get("consecutive_up_days") or 0)
    volume = _clamp(52.0 + min(streak, 5) * 4.0)

    atr_ratio = stock_ctx.get("atr_ratio")
    if atr_ratio is not None and float(atr_ratio) >= 1.35:
        liquidity = 42.0
    else:
        liquidity = 58.0

    sector = 52.0 if snap.nasdaq_uptrend is not False else 45.0

    rs_pct = stock_ctx.get("rs_composite_pct")
    if rs_pct is not None:
        trend = _clamp(trend + (float(rs_pct) - 0.5) * 16.0)

    return SignalComponents(
        trend=trend,
        volume=volume,
        regime=50.0,
        sector=sector,
        liquidity=liquidity,
    )
