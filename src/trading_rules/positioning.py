from __future__ import annotations


def shares_from_portfolio_risk(
    portfolio_value: float,
    entry_price: float,
    stop_price: float,
    max_risk_fraction: float,
    *,
    round_trip_commission_frac: float = 0.0,
) -> int:
    """
    1회 매매에서 포트 손실 상한(max_risk_fraction)을 넘지 않도록 수량(주) 상한 추정.

    예: 1000만원, 종목당 최대 손실 2% → 20만원까지 허용.
    per_share_risk = entry - stop; qty = floor(allow_loss / per_share_risk)

    round_trip_commission_frac: 매수+매도 수수료를 가격손실에 가산 (예: 2*0.00147).
    """
    if portfolio_value <= 0 or entry_price <= 0 or max_risk_fraction <= 0:
        return 0
    fee_adj = entry_price * max(0.0, round_trip_commission_frac)
    per_share = entry_price - stop_price + fee_adj
    if per_share <= 0:
        return 0
    allow_loss = portfolio_value * max_risk_fraction
    qty = int(allow_loss // per_share)
    return max(qty, 0)


def trailing_stop_from_high(high_price: float, trail_width_pct: float) -> float:
    """고정 % 트레일링 스탑 가격 (롱)."""
    return high_price * (1.0 - trail_width_pct)


def atr_stop_price(close_or_high: float, atr: float, mult: float) -> float:
    """ATR 기반 스탑 가격."""
    return close_or_high - atr * mult
