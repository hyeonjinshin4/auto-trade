from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from safe_logging import get_safe_logger

from .engine_config import ConflictPolicy, EngineConfig, ScoreWeights
from .models import MarketRegime


_log_sc = get_safe_logger(__name__)


@dataclass(frozen=True)
class SignalComponents:
    """각 0~100. regime 슬롯에는 regime_score(0~100)를 넣는 것을 권장."""

    trend: float
    volume: float
    regime: float
    sector: float
    liquidity: float


def _normalize_weights(w: ScoreWeights) -> ScoreWeights:
    s = w.trend + w.volume + w.regime + w.sector + w.liquidity
    if s <= 0:
        return ScoreWeights(0.2, 0.2, 0.2, 0.2, 0.2)
    return ScoreWeights(
        trend=w.trend / s,
        volume=w.volume / s,
        regime=w.regime / s,
        sector=w.sector / s,
        liquidity=w.liquidity / s,
    )


def score_weights_unit_sum(w: ScoreWeights) -> ScoreWeights:
    """동적 가중 보정 후 합 1.0 보장(저장용 ScoreWeights 생성 시 사용)."""
    return _normalize_weights(w)


def raw_signal_score(components: SignalComponents, weights: ScoreWeights) -> float:
    w = _normalize_weights(weights)
    return (
        w.trend * components.trend
        + w.volume * components.volume
        + w.regime * components.regime
        + w.sector * components.sector
        + w.liquidity * components.liquidity
    )


def apply_conflict_resolution(
    raw_signal: float,
    *,
    regime_score: float,
    risk_off: bool,
    vix_spike: bool,
    policy: ConflictPolicy,
    symbol: str | None = None,
) -> tuple[float, list[str]]:
    """
    룰 충돌 해결: 국면 점수·risk_off·VIX가 기술 점수를 상한으로 자른다.
    regime_score 매우 낮으면 사실상 스킵 구간으로 밀어넣음.
    """
    reasons: list[str] = []
    adj = raw_signal

    if regime_score < policy.regime_score_hard_veto_below:
        adj = min(adj, policy.cap_signal_when_regime_low - 5.0)
        reasons.append(f"regime_score<{policy.regime_score_hard_veto_below} → 강한 상한")

    elif regime_score < policy.regime_score_cap_signal_above:
        adj = min(adj, policy.cap_signal_when_regime_low)
        reasons.append(f"regime_score<{policy.regime_score_cap_signal_above} → 점수 상한")

    if risk_off:
        adj = min(adj, policy.risk_off_cap_signal)
        reasons.append("risk_off → 점수 상한")

    if vix_spike:
        adj = max(0.0, adj - policy.vix_spike_extra_penalty)
        reasons.append("vix_spike → 추가 감점")

    if symbol and reasons:
        _log_sc.debug(
            "[CONFLICT] %s — 충돌 보정: %s (raw=%.1f→adj=%.1f, regime_score=%.1f)",
            symbol,
            "; ".join(reasons),
            raw_signal,
            adj,
            regime_score,
        )

    return adj, reasons


EntryTier = Literal["full", "half", "skip"]


def entry_tier_from_score(
    adjusted_signal: float,
    regime_score: float,
    cfg: EngineConfig,
    *,
    hard_veto_skip: bool = True,
) -> EntryTier:
    th = cfg.score_thresholds
    veto = cfg.conflict.regime_score_hard_veto_below

    if hard_veto_skip and regime_score < veto:
        return "skip"
    if adjusted_signal >= th.full_entry_min:
        return "full"
    if adjusted_signal >= th.half_entry_min:
        return "half"
    return "skip"


def position_fraction(tier: EntryTier) -> float:
    if tier == "full":
        return 1.0
    if tier == "half":
        return 0.5
    return 0.0


def explain_decision(
    raw: float,
    adjusted: float,
    tier: EntryTier,
    regime: MarketRegime,
    regime_score: float,
) -> str:
    return (
        f"regime={regime.value} regime_score={regime_score:.1f} | "
        f"signal_raw={raw:.1f} → adjusted={adjusted:.1f} | tier={tier}"
    )
