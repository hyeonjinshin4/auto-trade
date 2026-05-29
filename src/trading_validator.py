"""
매수 직전 검증: 체크 함수 리스트 + ValidationResult.
DRY_RUN/LIVE 구분은 호출측(auto_trade)에서 주문 여부로 처리.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable

from trading_rules.models import MarketRegime, MarketRegimeSnapshot, Rulebook, classify_regime


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    reasons: tuple[str, ...]

    @property
    def reasons_list(self) -> list[str]:
        return list(self.reasons)


@dataclass
class BuyValidationContext:
    symbol: str
    qty: int
    rulebook: Rulebook
    snapshot: MarketRegimeSnapshot
    vix_level: float | None
    balance: dict[str, Any]
    stock_ctx: dict[str, Any]
    regime_enum: MarketRegime | None = None
    regime_reasons: list[str] = field(default_factory=list)


BuyCheck = Callable[[BuyValidationContext], str | None]


def _parse_float(x: Any) -> float:
    try:
        return float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def portfolio_nav_krw(balance: dict[str, Any]) -> float:
    o2 = balance.get("output2")
    if not isinstance(o2, list) or not o2:
        return 0.0
    row0 = o2[0]
    if not isinstance(row0, dict):
        return 0.0
    return _parse_float(row0.get("nass_amt"))


def symbol_holding_value_krw(balance: dict[str, Any], symbol: str) -> float:
    o1 = balance.get("output1")
    if not isinstance(o1, list):
        return 0.0
    sym = symbol.strip()
    total = 0.0
    for row in o1:
        if not isinstance(row, dict):
            continue
        if str(row.get("pdno", "")).strip() == sym:
            total += _parse_float(row.get("evlu_amt"))
    return total


def symbol_value_ratio_in_portfolio(balance: dict[str, Any], symbol: str) -> float | None:
    nass = portfolio_nav_krw(balance)
    if nass <= 0:
        return None
    held = symbol_holding_value_krw(balance, symbol)
    return held / nass


def _ensure_regime(ctx: BuyValidationContext) -> None:
    if ctx.regime_enum is None:
        re, rr = classify_regime(ctx.snapshot, ctx.rulebook.regime, vix_level=ctx.vix_level)
        ctx.regime_enum = re
        ctx.regime_reasons = list(rr)


def _check_risk_off(ctx: BuyValidationContext) -> str | None:
    _ensure_regime(ctx)
    block = (os.getenv("TRADING_BLOCK_RISK_OFF", "true")).strip().lower() in {"1", "true", "yes", "y"}
    if block and ctx.regime_enum == MarketRegime.RISK_OFF:
        head = "; ".join(ctx.regime_reasons[:4])
        return f"시장 국면 risk_off — 매수 제한 ({head})"
    return None


def _check_chase_daily(ctx: BuyValidationContext) -> str | None:
    chase_pct = float(os.getenv("TRADING_CHASE_DAILY_PCT", "0.15"))
    dchg = ctx.stock_ctx.get("daily_change_pct")
    if dchg is not None and float(dchg) >= chase_pct:
        return (
            f"no_chase_green_bar: 당일 등락 {float(dchg) * 100:.1f}% >= 허용 {chase_pct * 100:.0f}%"
        )
    return None


def _check_consecutive_up(ctx: BuyValidationContext) -> str | None:
    streak = int(ctx.stock_ctx.get("consecutive_up_days") or 0)
    lim = ctx.rulebook.buy.chase_consecutive_up_days_block
    if streak >= lim:
        return f"연속 상승 {streak}일 — 추격 제한(임계 {lim}일)"
    return None


def _check_concentration(ctx: BuyValidationContext) -> str | None:
    ratio = symbol_value_ratio_in_portfolio(ctx.balance, ctx.symbol)
    raw_cap = (os.getenv("TRADING_VALIDATE_MAX_NAME_PCT") or "").strip()
    max_pct = float(raw_cap) if raw_cap else ctx.rulebook.position.max_single_name_pct_fund_style
    if ratio is not None and ratio >= max_pct:
        return (
            f"no_concentration: 종목 평가비중 {ratio * 100:.1f}% ≥ 상한 {max_pct * 100:.0f}%"
        )
    return None


def _check_leverage(ctx: BuyValidationContext) -> str | None:
    if ctx.stock_ctx.get("using_leverage"):
        return "no_excess_leverage: 레버리지 사용 중으로 차단"
    return None


def _check_community(ctx: BuyValidationContext) -> str | None:
    if ctx.stock_ctx.get("community_chase"):
        return "no_community_chase: 커뮤니티 추종 플래그"
    return None


def _check_avg_down(ctx: BuyValidationContext) -> str | None:
    if ctx.stock_ctx.get("recent_avg_down"):
        return "no_avg_down_loop: 최근 물타기 패턴 플래그"
    return None


def _check_min_price(ctx: BuyValidationContext) -> str | None:
    min_price = float(os.getenv("TRADING_MIN_STOCK_PRICE_KRW", "0"))
    last_close = ctx.stock_ctx.get("last_close")
    if min_price > 0 and last_close is not None:
        lp = float(last_close)
        if 0 < lp < min_price:
            return f"no_penny_without_thesis: 종가 {lp:.0f}원 < 최소가 {min_price:.0f}원 (설정 시만)"
    return None


DEFAULT_BUY_CHECKS: tuple[BuyCheck, ...] = (
    _check_risk_off,
    _check_chase_daily,
    _check_consecutive_up,
    _check_concentration,
    _check_leverage,
    _check_community,
    _check_avg_down,
    _check_min_price,
)


def run_buy_validators(
    ctx: BuyValidationContext,
    checks: tuple[BuyCheck, ...] = DEFAULT_BUY_CHECKS,
) -> ValidationResult:
    """체크를 순서대로 실행. 한 건이라도 메시지면 실패."""
    reasons: list[str] = []
    for fn in checks:
        msg = fn(ctx)
        if msg:
            reasons.append(msg)
    return ValidationResult(ok=len(reasons) == 0, reasons=tuple(reasons))


def validate_buy_order(
    *,
    symbol: str,
    qty: int,
    rulebook: Rulebook,
    snapshot: MarketRegimeSnapshot,
    vix_level: float | None,
    balance: dict[str, Any],
    stock_ctx: dict[str, Any],
    checks: tuple[BuyCheck, ...] = DEFAULT_BUY_CHECKS,
) -> tuple[bool, list[str]]:
    """
    기존 API 유지: (ok, reasons_list).
    stock_ctx는 선택적으로 Pydantic 정규화(TRADING_VALIDATE_STOCK_CTX_PYDANTIC=1).
    """
    ctx_dict = dict(stock_ctx)
    if (os.getenv("TRADING_VALIDATE_STOCK_CTX_PYDANTIC") or "").strip().lower() in {"1", "true", "yes"}:
        try:
            from schemas_context import StockContextPayload

            ctx_dict = StockContextPayload.model_validate(stock_ctx).to_dict()
        except Exception:
            pass

    ctx = BuyValidationContext(
        symbol=symbol,
        qty=qty,
        rulebook=rulebook,
        snapshot=snapshot,
        vix_level=vix_level,
        balance=balance,
        stock_ctx=ctx_dict,
    )
    res = run_buy_validators(ctx, checks=checks)
    return res.ok, res.reasons_list
