from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from signal_scanner.config import SignalThresholds, WatchlistConfig


def _f(x: Any) -> float | None:
    if x is None or (isinstance(x, float) and pd_isna(x)):
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def pd_isna(x: Any) -> bool:
    try:
        import math

        v = float(x)
        return math.isnan(v)
    except (TypeError, ValueError):
        return False


@dataclass(frozen=True)
class SignalHit:
    code: str
    label: str


def _cross_up(prev_a: float, prev_b: float, a: float, b: float) -> bool:
    return prev_a <= prev_b and a > b


def _cross_down(prev_a: float, prev_b: float, a: float, b: float) -> bool:
    return prev_a >= prev_b and a < b


def evaluate_buy_signals(
    today: dict[str, Any],
    prev: dict[str, Any],
    th: SignalThresholds,
) -> list[SignalHit]:
    hits: list[SignalHit] = []
    c = _f(today.get("close"))
    pc = _f(prev.get("close"))
    rsi = _f(today.get("rsi"))
    ma5 = _f(today.get("ma_fast"))
    ma20 = _f(today.get("ma_slow"))
    p_ma5 = _f(prev.get("ma_fast"))
    p_ma20 = _f(prev.get("ma_slow"))
    macd = _f(today.get("macd"))
    macd_sig = _f(today.get("macd_signal"))
    p_macd = _f(prev.get("macd"))
    p_macd_sig = _f(prev.get("macd_signal"))
    bb_low = _f(today.get("bb_lower"))
    p_bb_low = _f(prev.get("bb_lower"))
    p_close = _f(prev.get("close"))
    sk = _f(today.get("stoch_k"))
    sd = _f(today.get("stoch_d"))
    p_sk = _f(prev.get("stoch_k"))
    p_sd = _f(prev.get("stoch_d"))
    vol = _f(today.get("volume"))
    vol_ma = _f(today.get("vol_ma20"))

    if rsi is not None and rsi <= th.rsi_oversold:
        hits.append(SignalHit("rsi_oversold", f"RSI 과매도 RSI(14)={rsi:.1f}≤{th.rsi_oversold:.0f}"))

    if None not in (ma5, ma20, p_ma5, p_ma20) and _cross_up(p_ma5, p_ma20, ma5, ma20):
        hits.append(SignalHit("golden_cross", "이동평균 골든크로스 5일선↑20일선"))

    if None not in (macd, macd_sig, p_macd, p_macd_sig) and _cross_up(p_macd, p_macd_sig, macd, macd_sig):
        hits.append(SignalHit("macd_bull", "MACD 상향 돌파"))

    if None not in (c, p_close, bb_low, p_bb_low) and p_close <= p_bb_low and c > bb_low:
        hits.append(SignalHit("bb_lower_bounce", "볼린저 하단 반등"))

    if None not in (sk, sd, p_sk, p_sd) and _cross_up(p_sk, p_sd, sk, sd) and sk <= th.stoch_low:
        hits.append(SignalHit("stoch_golden", f"스토캐스틱 저점 골든 %K={sk:.1f}≤{th.stoch_low:.0f}"))

    body_pct = _f(today.get("body_pct"))
    lw_pct = _f(today.get("lower_wick_pct"))
    if None not in (c, pc, body_pct, lw_pct):
        if lw_pct >= th.hammer_lower_wick_pct and body_pct <= th.hammer_body_pct and c > pc:
            hits.append(SignalHit("hammer", "망치형 반전 캔들"))

    primary = [h for h in hits if h.code != "volume_up"]
    if primary and None not in (c, pc, vol, vol_ma) and c > pc and vol_ma > 0:
        if vol >= th.volume_mult * vol_ma:
            hits.append(
                SignalHit(
                    "volume_up",
                    f"거래량 동반 상승 (≥{th.volume_mult:.1f}×20일평균)",
                )
            )

    return hits


def evaluate_sell_signals(
    today: dict[str, Any],
    prev: dict[str, Any],
    th: SignalThresholds,
) -> list[SignalHit]:
    hits: list[SignalHit] = []
    c = _f(today.get("close"))
    pc = _f(prev.get("close"))
    rsi = _f(today.get("rsi"))
    ma5 = _f(today.get("ma_fast"))
    ma20 = _f(today.get("ma_slow"))
    p_ma5 = _f(prev.get("ma_fast"))
    p_ma20 = _f(prev.get("ma_slow"))
    macd = _f(today.get("macd"))
    macd_sig = _f(today.get("macd_signal"))
    p_macd = _f(prev.get("macd"))
    p_macd_sig = _f(prev.get("macd_signal"))
    bb_up = _f(today.get("bb_upper"))
    p_bb_up = _f(prev.get("bb_upper"))
    p_close = _f(prev.get("close"))
    sk = _f(today.get("stoch_k"))
    sd = _f(today.get("stoch_d"))
    p_sk = _f(prev.get("stoch_k"))
    p_sd = _f(prev.get("stoch_d"))
    vol = _f(today.get("volume"))
    vol_ma = _f(today.get("vol_ma20"))

    if rsi is not None and rsi >= th.rsi_overbought:
        hits.append(SignalHit("rsi_overbought", f"RSI 과매수 RSI(14)={rsi:.1f}≥{th.rsi_overbought:.0f}"))

    if None not in (ma5, ma20, p_ma5, p_ma20) and _cross_down(p_ma5, p_ma20, ma5, ma20):
        hits.append(SignalHit("dead_cross", "이동평균 데드크로스 5일선↓20일선"))

    if None not in (macd, macd_sig, p_macd, p_macd_sig) and _cross_down(p_macd, p_macd_sig, macd, macd_sig):
        hits.append(SignalHit("macd_bear", "MACD 하향 돌파"))

    if None not in (c, p_close, bb_up, p_bb_up) and p_close >= p_bb_up and c < bb_up:
        hits.append(SignalHit("bb_upper_reject", "볼린저 상단 되밀림"))

    if None not in (sk, sd, p_sk, p_sd) and _cross_down(p_sk, p_sd, sk, sd) and sk >= th.stoch_high:
        hits.append(SignalHit("stoch_dead", f"스토캐스틱 고점 데드 %K={sk:.1f}≥{th.stoch_high:.0f}"))

    body_pct = _f(today.get("body_pct"))
    uw_pct = _f(today.get("upper_wick_pct"))
    if None not in (c, pc, body_pct, uw_pct):
        if uw_pct >= th.shooting_upper_wick_pct and body_pct <= th.shooting_body_pct and c < pc:
            hits.append(SignalHit("shooting_star", "상단 꼬리 반전 캔들"))

    primary = [h for h in hits if h.code != "volume_down"]
    if primary and None not in (c, pc, vol, vol_ma) and c < pc and vol_ma > 0:
        if vol >= th.volume_mult * vol_ma:
            hits.append(
                SignalHit(
                    "volume_down",
                    f"거래량 동반 하락 (≥{th.volume_mult:.1f}×20일평균)",
                )
            )

    return hits


def trend_allows_buy(today: dict[str, Any], cfg: WatchlistConfig) -> bool:
    if not cfg.confirm_trend:
        return True
    c = _f(today.get("close"))
    ma20 = _f(today.get("ma_slow"))
    return c is not None and ma20 is not None and c >= ma20


def trend_allows_sell(today: dict[str, Any], cfg: WatchlistConfig) -> bool:
    if not cfg.confirm_trend:
        return True
    c = _f(today.get("close"))
    ma20 = _f(today.get("ma_slow"))
    return c is not None and ma20 is not None and c <= ma20


def primary_sell_hits(hits: list[SignalHit] | tuple[SignalHit, ...]) -> list[SignalHit]:
    """거래량 보조(volume_down) 제외한 매도 시그널."""
    return [h for h in hits if h.code != "volume_down"]


def sell_alert_ready(hits: list[SignalHit] | tuple[SignalHit, ...], cfg: WatchlistConfig) -> bool:
    """매도 알림/청산: 주요 시그널 min_signals개 이상 (기본 2)."""
    return len(primary_sell_hits(hits)) >= cfg.min_signals


def alert_ready(hits: list[SignalHit], cfg: WatchlistConfig) -> bool:
    return len(hits) >= cfg.min_signals
