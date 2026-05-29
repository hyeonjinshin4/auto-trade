"""진입 점수 — breadth vs regime risk_off 상한."""
from __future__ import annotations

from trading_rules.engine_config import ConflictPolicy
from trading_rules.scoring import apply_conflict_resolution
from trade_ops import entry_risk_off_cap_flag


def test_entry_risk_off_cap_breadth_only_default_off(monkeypatch) -> None:
    monkeypatch.delenv("TRADING_BREADTH_APPLY_RISK_OFF_CAP", raising=False)
    assert entry_risk_off_cap_flag(regime_risk_off=False, breadth_risk_off=True) is False


def test_entry_risk_off_cap_regime_on(monkeypatch) -> None:
    monkeypatch.setenv("TRADING_BREADTH_APPLY_RISK_OFF_CAP", "false")
    assert entry_risk_off_cap_flag(regime_risk_off=True, breadth_risk_off=False) is True


def test_entry_risk_off_cap_breadth_legacy_env(monkeypatch) -> None:
    monkeypatch.setenv("TRADING_BREADTH_APPLY_RISK_OFF_CAP", "true")
    assert entry_risk_off_cap_flag(regime_risk_off=False, breadth_risk_off=True) is True


def test_conflict_no_cap_when_risk_off_false() -> None:
    policy = ConflictPolicy(
        regime_score_hard_veto_below=10.0,
        regime_score_cap_signal_above=40.0,
        cap_signal_when_regime_low=62.0,
        risk_off_cap_signal=60.0,
        vix_spike_extra_penalty=10.0,
    )
    adj, reasons = apply_conflict_resolution(
        63.5,
        regime_score=78.0,
        risk_off=False,
        vix_spike=False,
        policy=policy,
    )
    assert adj == 63.5
    assert not any("risk_off" in r for r in reasons)


def test_conflict_cap_when_risk_off_true() -> None:
    policy = ConflictPolicy(
        regime_score_hard_veto_below=10.0,
        regime_score_cap_signal_above=40.0,
        cap_signal_when_regime_low=62.0,
        risk_off_cap_signal=60.0,
        vix_spike_extra_penalty=10.0,
    )
    adj, _ = apply_conflict_resolution(
        63.5,
        regime_score=78.0,
        risk_off=True,
        vix_spike=False,
        policy=policy,
    )
    assert adj == 60.0
