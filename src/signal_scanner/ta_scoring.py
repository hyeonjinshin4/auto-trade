"""
TA 시그널 — 조건별 독립 가점 (합산, 스케일 없음).

충족한 조건마다 표에 적힌 점수가 그대로 더해짐 (RSI만 맞아도 +14).
volume_up/down 은 주요 시그널 1개 이상일 때만 가점.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from signal_scanner.config import WatchlistConfig
from signal_scanner.rules import SignalHit

DEFAULT_BUY_POINTS: dict[str, int] = {
    "rsi_oversold": 14,
    "golden_cross": 16,
    "macd_bull": 14,
    "bb_lower_bounce": 14,
    "stoch_golden": 14,
    "hammer": 12,
    "volume_up": 8,
}

# 매도 감점: 매수 가점과 대칭 (RSI ±14 등). 청산은 min_signals(2)+종가≤20일선.
DEFAULT_SELL_POINTS: dict[str, int] = {
    "rsi_overbought": 14,
    "dead_cross": 16,
    "macd_bear": 14,
    "bb_upper_reject": 14,
    "stoch_dead": 14,
    "shooting_star": 12,
    "volume_down": 8,
}

_BUY_AUX = frozenset({"volume_up"})
_SELL_AUX = frozenset({"volume_down"})


def ta_point_multiplier() -> float:
    """합산 점수에 TA 가점을 더할 때 배수 (1.0 = RSI+14 → 최종 +14)."""
    raw = (os.getenv("TRADING_TA_POINT_MULT") or "1.0").strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 1.0


@dataclass(frozen=True)
class TaScoreDetail:
    """조건별 가점 합계."""

    score: float  # = raw_points (추세 통과 시), 각 조건 독립 합
    raw_points: int
    hit_count: int
    trend_ok: bool
    breakdown: str
    labels: str
    blocked_reason: str | None = None


def _points_table(side: str) -> dict[str, int]:
    return dict(DEFAULT_BUY_POINTS if side == "buy" else DEFAULT_SELL_POINTS)


def _sum_hit_points(
    hits: tuple[SignalHit, ...] | list[SignalHit],
    table: dict[str, int],
    aux: frozenset[str],
) -> tuple[int, int, list[str], list[str]]:
    primary_n = 0
    raw = 0
    parts: list[str] = []
    labels: list[str] = []
    for h in hits:
        pts = table.get(h.code, 0)
        if pts <= 0:
            continue
        if h.code in aux:
            if primary_n < 1:
                continue
        else:
            primary_n += 1
        raw += pts
        parts.append(f"{h.code}+{pts}")
        labels.append(h.label)
    return raw, primary_n, parts, labels


def score_ta_buy(
    hits: tuple[SignalHit, ...] | list[SignalHit],
    cfg: WatchlistConfig,
    *,
    trend_ok: bool,
) -> TaScoreDetail:
    table = _points_table("buy")
    raw, n_hit, parts, labels = _sum_hit_points(hits, table, _BUY_AUX)
    br = ", ".join(parts)
    lbl = "; ".join(labels[: cfg.max_signals_in_message])

    if raw <= 0:
        return TaScoreDetail(0.0, 0, 0, trend_ok, br, lbl, "TA 조건 없음")
    if not trend_ok:
        return TaScoreDetail(0.0, raw, n_hit, False, br, lbl, "추세필터(종가<20일선)")

    return TaScoreDetail(float(raw), raw, n_hit, True, br, lbl, None)


def score_ta_sell_penalty(
    hits: tuple[SignalHit, ...] | list[SignalHit],
    cfg: WatchlistConfig,
) -> TaScoreDetail:
    """매수 점수에서 차감: 충족한 매도 조건마다 가점표와 동일 점수 (추세 무관)."""
    table = _points_table("sell")
    raw, n_hit, parts, labels = _sum_hit_points(hits, table, _SELL_AUX)
    br = ", ".join(parts)
    lbl = "; ".join(labels[: cfg.max_signals_in_message])
    if raw <= 0:
        return TaScoreDetail(0.0, 0, 0, True, br, lbl, "TA 매도조건 없음")
    return TaScoreDetail(float(raw), raw, n_hit, True, br, lbl, None)


def score_ta_sell_exit(
    hits: tuple[SignalHit, ...] | list[SignalHit],
    cfg: WatchlistConfig,
    *,
    trend_ok: bool,
) -> TaScoreDetail:
    """
    보유 청산: 주요 매도 시그널 ≥ min_signals(기본 2) 이고 종가 ≤ 20일선.
    """
    table = _points_table("sell")
    raw, n_primary, parts, labels = _sum_hit_points(hits, table, _SELL_AUX)
    br = ", ".join(parts)
    lbl = "; ".join(labels[: cfg.max_signals_in_message])

    if raw <= 0:
        return TaScoreDetail(0.0, 0, 0, trend_ok, br, lbl, "TA 매도조건 없음")
    if n_primary < cfg.min_signals:
        return TaScoreDetail(
            0.0,
            raw,
            n_primary,
            trend_ok,
            br,
            lbl,
            f"매도시그널<{cfg.min_signals}개(현재 주요{n_primary}개)",
        )
    if not trend_ok:
        return TaScoreDetail(0.0, raw, n_primary, False, br, lbl, "추세필터(종가>20일선)")

    return TaScoreDetail(float(raw), raw, n_primary, True, br, lbl, None)


def score_ta_sell(
    hits: tuple[SignalHit, ...] | list[SignalHit],
    cfg: WatchlistConfig,
    *,
    trend_ok: bool,
) -> TaScoreDetail:
    """하위 호환 — 청산 판정과 동일."""
    return score_ta_sell_exit(hits, cfg, trend_ok=trend_ok)


def ta_sell_exit_min_points() -> int:
    """TA 매도 청산: 감점 합 하한 (기본 28 ≈ RSI+MACD 2개)."""
    raw = (os.getenv("TRADING_TA_SELL_SCORE_MIN") or "28").strip()
    try:
        return max(0, int(float(raw)))
    except ValueError:
        return 28
