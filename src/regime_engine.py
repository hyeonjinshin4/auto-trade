"""
Adaptive regime engine: separates vol / trend / liquidity regimes, VIX percentile thresholds,
ATR-based stop multiplier, smoothed 0–100 regime score, dynamic score weights.

Pure functions + small mutable state object for EMA / hysteresis (serializable via to_dict).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from typing import Any, Literal

import numpy as np
import pandas as pd

from adaptive.percentile import percentile_rank_last, widen_low_sample_percentile
from adaptive.rolling_vol import realized_volatility
from configs.adaptive_regime import AdaptiveRegimeConfig
from trading_rules.engine_config import ConflictPolicy, EngineConfig, ScoreWeights
from trading_rules.models import RegimeThresholds
from trading_rules.regime_score import RegimeFeatureScores, aggregate_regime_score

VolLabel = Literal["low", "mid", "high"]
TrendLabel = Literal["down", "flat", "up"]
LiqLabel = Literal["stress", "normal", "easy"]


def load_adaptive_regime_config_from_env(base: AdaptiveRegimeConfig | None = None) -> AdaptiveRegimeConfig:
    """Optional numeric env overrides (stable defaults if unset)."""
    b = base or AdaptiveRegimeConfig()

    def gf(name: str, cur: float) -> float:
        raw = (os.getenv(name) or "").strip()
        return float(raw) if raw else cur

    def gi(name: str, cur: int) -> int:
        raw = (os.getenv(name) or "").strip()
        return int(float(raw)) if raw else cur

    sm = b.smoothing
    sm2 = replace(
        sm,
        score_ema_alpha=gf("ADAPTIVE_REGIME_SCORE_EMA", sm.score_ema_alpha),
        hysteresis_consecutive=gi("ADAPTIVE_REGIME_HYSTERESIS", sm.hysteresis_consecutive),
    )
    pw = b.percentile_windows
    pw2 = replace(
        pw,
        vix=gi("ADAPTIVE_VIX_PERCENTILE_WINDOW", pw.vix),
        realized_vol=gi("ADAPTIVE_RV_WINDOW", pw.realized_vol),
        min_effective=gi("ADAPTIVE_MIN_EFFECTIVE_WINDOW", pw.min_effective),
    )
    return replace(b, smoothing=sm2, percentile_windows=pw2)


@dataclass
class RegimeEnginePersistentState:
    """Carried across cycles (e.g. daily); reset when None passed to engine."""

    smoothed_regime_score: float = 50.0
    pending_vol: VolLabel | None = None
    pending_vol_count: int = 0
    last_committed_vol: VolLabel = "mid"

    def to_dict(self) -> dict[str, Any]:
        return {
            "smoothed_regime_score": self.smoothed_regime_score,
            "pending_vol": self.pending_vol,
            "pending_vol_count": self.pending_vol_count,
            "last_committed_vol": self.last_committed_vol,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RegimeEnginePersistentState:
        return cls(
            smoothed_regime_score=float(d.get("smoothed_regime_score", 50.0)),
            pending_vol=d.get("pending_vol"),  # type: ignore[arg-type]
            pending_vol_count=int(d.get("pending_vol_count", 0)),
            last_committed_vol=str(d.get("last_committed_vol", "mid")),  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class AdaptiveRegimeOutcome:
    volatility_regime: VolLabel
    trend_regime: TrendLabel
    liquidity_regime: LiqLabel
    vix_percentile: float
    atr_percentile_proxy: float | None  # when stock ATR ratio supplied
    regime_score_raw: float
    regime_score_smoothed: float
    dynamic_vix_risk_off: float
    dynamic_vix_tight_trailing: float
    score_weights: ScoreWeights
    atr_hard_stop_multiplier: float
    conflict_effective: ConflictPolicy
    meta: dict[str, Any] = field(default_factory=dict)


def _vol_label(p: float, cfg: AdaptiveRegimeConfig) -> VolLabel:
    sp = cfg.vol_split
    if p < sp.low_below:
        return "low"
    if p < sp.mid_below:
        return "mid"
    return "high"


def _trend_label(ret20: float, ret60: float, cfg: AdaptiveRegimeConfig) -> TrendLabel:
    sp = cfg.trend_split
    spread = ret20 - ret60
    if spread < sp.down_below and ret20 < 0:
        return "down"
    if spread > sp.up_above and ret20 > 0:
        return "up"
    return "flat"


def _liq_label(vol_ratio: float | None, cfg: AdaptiveRegimeConfig) -> LiqLabel:
    if vol_ratio is None or np.isnan(vol_ratio):
        return "normal"
    s = cfg.liq_split
    if vol_ratio < s.stress_below:
        return "stress"
    if vol_ratio > s.easy_above:
        return "easy"
    return "normal"


def _hysteresis_commit(
    raw: VolLabel,
    state: RegimeEnginePersistentState,
    need: int,
) -> tuple[VolLabel, RegimeEnginePersistentState]:
    if raw == state.last_committed_vol:
        st = replace(state, pending_vol=None, pending_vol_count=0)
        return raw, st
    if state.pending_vol != raw:
        st = replace(state, pending_vol=raw, pending_vol_count=1)
        return state.last_committed_vol, st
    cnt = state.pending_vol_count + 1
    st = replace(state, pending_vol=raw, pending_vol_count=cnt)
    if cnt >= need:
        st2 = replace(st, last_committed_vol=raw, pending_vol=None, pending_vol_count=0)
        return raw, st2
    return state.last_committed_vol, st


def atr_hard_stop_multiplier(atr_ratio: float | None, cfg: AdaptiveRegimeConfig) -> float:
    """Piecewise linear map from ATR ratio to stop width multiplier."""
    if atr_ratio is None or np.isnan(atr_ratio):
        return 1.0
    a = cfg.atr_stop
    r = float(atr_ratio)
    if r <= a.ratio_low:
        return a.mult_at_low
    if r >= a.ratio_high:
        return a.mult_at_high
    t = (r - a.ratio_low) / (a.ratio_high - a.ratio_low)
    return a.mult_at_low + t * (a.mult_at_high - a.mult_at_low)


def atr_ratio_to_percentile_proxy(atr_ratio: float | None) -> float | None:
    """Map ATR ratio ~ [0.5, 2] to [0,1] for logging / meta (not a true historical percentile)."""
    if atr_ratio is None or np.isnan(atr_ratio):
        return None
    r = max(0.5, min(2.0, float(atr_ratio)))
    return (r - 0.5) / 1.5


def build_dynamic_thresholds(
    vix_pct: float,
    cfg: AdaptiveRegimeConfig,
    base_regime: RegimeThresholds,
) -> tuple[float, float]:
    """VIX percentile → effective vix_risk_off & tight trailing."""
    t = cfg.vix_thresholds
    lo = t.risk_off_low_pct
    hi = t.risk_off_high_pct
    eff = lo + vix_pct * (hi - lo)
    tight = eff + t.tight_trailing_add
    # never below configured base by more than small margin (stability)
    eff = max(float(base_regime.vix_risk_off) * 0.85, eff)
    return eff, tight


def build_conflict_effective(
    vol_label: VolLabel,
    base: ConflictPolicy,
    cfg: AdaptiveRegimeConfig,
) -> ConflictPolicy:
    """Taper caps: high vol → stricter caps."""
    tap = cfg.conflict_taper
    if vol_label == "high":
        rc = tap.regime_cap_high_vol
        ro = tap.risk_off_cap_high_vol
    elif vol_label == "low":
        rc = tap.regime_cap_low_vol
        ro = tap.risk_off_cap_low_vol
    else:
        rc = (tap.regime_cap_low_vol + tap.regime_cap_high_vol) / 2.0
        ro = (tap.risk_off_cap_low_vol + tap.risk_off_cap_high_vol) / 2.0
    return replace(
        base,
        cap_signal_when_regime_low=min(base.cap_signal_when_regime_low, rc),
        risk_off_cap_signal=min(base.risk_off_cap_signal, ro),
    )


def resolve_score_weights(
    vol_label: VolLabel,
    base: ScoreWeights,
    cfg: AdaptiveRegimeConfig,
) -> ScoreWeights:
    from trading_rules.scoring import score_weights_unit_sum

    ow = cfg.vol_weights
    ovr = getattr(ow, vol_label, None)
    if ovr is not None:
        return score_weights_unit_sum(ovr)
    return base


def compute_adaptive_regime(
    *,
    vix: pd.Series,
    kospi_close: pd.Series,
    kospi_volume: pd.Series | None,
    feats: RegimeFeatureScores,
    engine_cfg: EngineConfig,
    rulebook_regime: RegimeThresholds,
    cfg: AdaptiveRegimeConfig | None = None,
    state: RegimeEnginePersistentState | None = None,
    stock_atr_ratio: float | None = None,
) -> tuple[AdaptiveRegimeOutcome, RegimeEnginePersistentState]:
    """
    Point-in-time at last row of series (EOD-style): no future rows used.
    """
    cfg = cfg or AdaptiveRegimeConfig()
    st = state or RegimeEnginePersistentState()

    vix_w = cfg.percentile_windows.vix
    rv_w = cfg.percentile_windows.realized_vol
    nmin = cfg.percentile_windows.min_effective

    vix_clean = vix.astype(float).dropna()
    vix_window = vix_clean.iloc[-min(vix_w, len(vix_clean)) :]
    vix_pct_raw = percentile_rank_last(vix_window)
    vix_pct = widen_low_sample_percentile(vix_pct_raw, len(vix_window), nmin)

    kc = kospi_close.astype(float).dropna()
    rv = realized_volatility(kc, rv_w)
    rv_last = float(rv.iloc[-1]) if len(rv) and not np.isnan(rv.iloc[-1]) else np.nan
    rv_win = rv.dropna().iloc[-min(rv_w, len(rv.dropna())) :]
    rv_pct = percentile_rank_last(rv_win) if len(rv_win) >= 2 else 0.5
    rv_pct = widen_low_sample_percentile(rv_pct, len(rv_win), nmin)

    composite_vol_p = 0.5 * vix_pct + 0.5 * rv_pct
    vol_raw = _vol_label(composite_vol_p, cfg)
    vol_committed, st2 = _hysteresis_commit(vol_raw, st, cfg.smoothing.hysteresis_consecutive)

    if len(kc) < 65:
        ret20 = ret60 = 0.0
    else:
        c = kc.iloc[-1]
        ret20 = float(c / kc.iloc[-21] - 1.0) if kc.iloc[-21] > 0 else 0.0
        ret60 = float(c / kc.iloc[-61] - 1.0) if kc.iloc[-61] > 0 else 0.0
    trend = _trend_label(ret20, ret60, cfg)

    vol_ratio: float | None = None
    if kospi_volume is not None and len(kospi_volume) > 25:
        kv = kospi_volume.astype(float)
        ma20 = kv.rolling(20, min_periods=10).mean()
        if not np.isnan(ma20.iloc[-1]) and ma20.iloc[-1] > 0:
            vol_ratio = float(kv.iloc[-1] / ma20.iloc[-1])
    liq = _liq_label(vol_ratio, cfg)

    raw_regime = aggregate_regime_score(feats, engine_cfg.regime_weights)
    alpha = cfg.smoothing.score_ema_alpha
    sm_score = alpha * raw_regime + (1.0 - alpha) * st2.smoothed_regime_score
    sm_score = max(0.0, min(100.0, sm_score))
    st3 = replace(st2, smoothed_regime_score=sm_score)

    dyn_ro, dyn_tt = build_dynamic_thresholds(vix_pct, cfg, rulebook_regime)
    sw = resolve_score_weights(vol_committed, engine_cfg.score_weights, cfg)
    atr_mult = atr_hard_stop_multiplier(stock_atr_ratio, cfg)
    ce = build_conflict_effective(vol_committed, engine_cfg.conflict, cfg)

    out = AdaptiveRegimeOutcome(
        volatility_regime=vol_committed,
        trend_regime=trend,
        liquidity_regime=liq,
        vix_percentile=vix_pct,
        atr_percentile_proxy=atr_ratio_to_percentile_proxy(stock_atr_ratio),
        regime_score_raw=float(raw_regime),
        regime_score_smoothed=float(sm_score),
        dynamic_vix_risk_off=float(dyn_ro),
        dynamic_vix_tight_trailing=float(dyn_tt),
        score_weights=sw,
        atr_hard_stop_multiplier=float(atr_mult),
        conflict_effective=ce,
        meta={
            "vix_percentile_raw": vix_pct_raw,
            "realized_vol_last": rv_last,
            "realized_vol_percentile": rv_pct,
            "composite_vol_percentile": composite_vol_p,
            "kospi_vol_ratio": vol_ratio,
            "ret20": ret20,
            "ret60": ret60,
            "vol_regime_raw": vol_raw,
        },
    )
    return out, st3


def fetch_market_series_fdr(
    *,
    vix_symbol: str = "VIX",
    kospi_symbol: str = "KS11",
    calendar_days: int = 400,
) -> tuple[pd.Series, pd.Series, pd.Series | None]:
    """FDR download for adaptive engine (optional; caller handles errors)."""
    from datetime import datetime, timedelta

    import FinanceDataReader as fdr  # type: ignore[import-untyped]

    end = datetime.now()
    start = end - timedelta(days=calendar_days)
    d0, d1 = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
    vx = fdr.DataReader(vix_symbol, d0, d1)
    kx = fdr.DataReader(kospi_symbol, d0, d1)
    vix_s = vx["Close"].astype(float)
    close_s = kx["Close"].astype(float)
    vol_s = kx["Volume"].astype(float) if "Volume" in kx.columns else None
    return vix_s, close_s, vol_s
