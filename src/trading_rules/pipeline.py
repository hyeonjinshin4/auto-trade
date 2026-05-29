from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from safe_logging import get_safe_logger

from .loader import get_engine_config, get_rulebook
from .models import MarketRegime, MarketRegimeSnapshot, classify_regime
from .regime_score import aggregate_regime_score, infer_regime_features_from_snapshot

try:
    from regime_engine import AdaptiveRegimeOutcome
except ImportError:  # pragma: no cover
    AdaptiveRegimeOutcome = Any  # type: ignore[misc, assignment]
from .scoring import (
    SignalComponents,
    apply_conflict_resolution,
    entry_tier_from_score,
    explain_decision,
    position_fraction,
    raw_signal_score,
)
from .sizing import combined_size_multiplier

_log = get_safe_logger(__name__)


def _pipeline_row(tag: str, step: str, blocked: bool, reason: str) -> None:
    """진입 파이프라인 단계 로그 (INFO). LOG_LEVEL=INFO 일 때 터미널에 표시."""
    status = "BLOCK" if blocked else "PASS"
    _log.info("[PIPELINE] %s | 단계=%-12s | %s | 이유: %s", tag, step, status, reason)


@dataclass(frozen=True)
class EntryDecision:
    tier: str
    position_fraction: float
    signal_raw: float
    signal_adjusted: float
    regime_score: float
    regime_label: str
    conflict_reasons: tuple[str, ...]
    size_multiplier: float
    explanation: str


def decide_entry(
    snap: MarketRegimeSnapshot,
    components: SignalComponents,
    *,
    vix_level: float | None,
    risk_off: bool,
    vix_spike: bool,
    is_high_stock_vol: bool = False,
    adaptive: "AdaptiveRegimeOutcome | None" = None,
    symbol: str | None = None,
) -> EntryDecision:
    """
    스냅샷 + 시그널 분해 → 국면 점수 → 가중 스코어 → 충돌 해결 → 티어·사이즈 배수.

    흐름 요약:
      1) infer_regime_features_from_snapshot (+ adaptive 시 스무딩 점수) → regime_score
      2) classify_regime(snap, RegimeThresholds, vix) → MarketRegime, risk_off와 결합
      3) raw_signal_score(가중 합성)
      4) apply_conflict_resolution → adjusted (국면·risk_off·VIX 스파이크 상한/감점)
      5) entry_tier_from_score: regime_score < regime_score_hard_veto_below 이면 즉시 skip,
         아니면 adjusted 가 ScoreThresholds 와 비교해 full / half / skip
      6) combined_size_multiplier(VIX·종목 변동성) → 사이즈 배수
    """
    ec = get_engine_config()
    rb = get_rulebook()

    feats = infer_regime_features_from_snapshot(snap, vix_level=vix_level)
    if adaptive is not None:
        regime_score = float(adaptive.regime_score_smoothed)
        regime_th = replace(
            rb.regime,
            vix_risk_off=adaptive.dynamic_vix_risk_off,
            vix_tight_trailing=adaptive.dynamic_vix_tight_trailing,
        )
        regime_enum, _ = classify_regime(snap, regime_th, vix_level=vix_level)
        risk_off_effective = risk_off or regime_enum == MarketRegime.RISK_OFF
        comp_adj = replace(components, regime=regime_score)
        raw = raw_signal_score(comp_adj, adaptive.score_weights)
        adj, creasons = apply_conflict_resolution(
            raw,
            regime_score=regime_score,
            risk_off=risk_off_effective,
            vix_spike=vix_spike,
            policy=adaptive.conflict_effective,
            symbol=symbol,
        )
    else:
        regime_score = aggregate_regime_score(feats, ec.regime_weights)
        regime_enum, _ = classify_regime(snap, rb.regime, vix_level=vix_level)
        risk_off_effective = risk_off or regime_enum == MarketRegime.RISK_OFF

        comp_adj = replace(components, regime=regime_score)
        raw = raw_signal_score(comp_adj, ec.score_weights)
        adj, creasons = apply_conflict_resolution(
            raw,
            regime_score=regime_score,
            risk_off=risk_off_effective,
            vix_spike=vix_spike,
            policy=ec.conflict,
            symbol=symbol,
        )
    tag = (symbol or "-").strip() or "-"
    _pipeline_row(tag, "regime_score", False, f"score={regime_score:.2f}")
    _pipeline_row(
        tag,
        "mkt_regime",
        False,
        f"label={regime_enum.value}, risk_off_effective={risk_off_effective}",
    )
    _pipeline_row(tag, "raw_signal", False, f"raw={raw:.2f}")
    cr_txt = "; ".join(creasons) if creasons else "없음"
    _pipeline_row(tag, "conflict_res", False, f"adjusted={adj:.2f}, 보정={cr_txt}")

    tier = entry_tier_from_score(adj, regime_score, ec)
    frac = position_fraction(tier)
    mult = combined_size_multiplier(vix_level, is_high_stock_vol, ec.vol_targeting)
    expl = explain_decision(raw, adj, tier, regime_enum, regime_score)

    veto = ec.conflict.regime_score_hard_veto_below
    th = ec.score_thresholds
    if tier == "skip" and regime_score < veto:
        tier_reason = f"regime_score={regime_score:.2f}<{veto} (하드 veto), {expl}"
    elif tier == "skip":
        tier_reason = (
            f"adjusted={adj:.2f} < half_entry_min({th.half_entry_min:.1f}), full≥{th.full_entry_min:.1f} | {expl}"
        )
    else:
        tier_reason = f"tier={tier}, adj={adj:.2f}, regime_score={regime_score:.2f} | {expl}"
    _pipeline_row(tag, "entry_tier", tier == "skip", tier_reason)

    pos_blocked = tier == "skip" or frac <= 0
    _pipeline_row(
        tag,
        "pos_fraction",
        pos_blocked,
        f"tier={tier}, position_fraction={frac}",
    )
    _pipeline_row(
        tag,
        "size_mult",
        pos_blocked,
        f"mult={mult:.4f}" if not pos_blocked else f"tier=skip로 배수 미적용, mult={mult:.4f}",
    )

    return EntryDecision(
        tier=tier,
        position_fraction=frac,
        signal_raw=raw,
        signal_adjusted=adj,
        regime_score=regime_score,
        regime_label=regime_enum.value,
        conflict_reasons=tuple(creasons),
        size_multiplier=mult,
        explanation=expl,
    )
