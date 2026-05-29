"""보유 종목 매수조건 재평가(슬롯 만석)."""
from __future__ import annotations

from unittest.mock import patch

from trade_ops import (
    HoldingEntryDiagnosis,
    holding_entry_scan_enabled,
    scan_held_positions_entry,
)
from trading_rules.loader import get_rulebook
from trading_rules.models import MarketRegime
from trading_rules.pipeline import EntryDecision


def test_holding_entry_scan_enabled_default(monkeypatch) -> None:
    monkeypatch.delenv("TRADING_SCAN_HELD_ENTRY", raising=False)
    assert holding_entry_scan_enabled() is True
    monkeypatch.setenv("TRADING_SCAN_HELD_ENTRY", "false")
    assert holding_entry_scan_enabled() is False


def test_scan_held_positions_entry_prints_summary(capsys) -> None:
    snap = get_rulebook().regime  # not used when mocked
    decision_ok = EntryDecision(
        tier="full",
        position_fraction=1.0,
        signal_raw=80.0,
        signal_adjusted=80.0,
        regime_score=50.0,
        regime_label="neutral",
        conflict_reasons=(),
        size_multiplier=1.0,
        explanation="[점수] 엔진=60 + TA20 → 80",
    )
    decision_weak = EntryDecision(
        tier="skip",
        position_fraction=0.0,
        signal_raw=44.0,
        signal_adjusted=44.0,
        regime_score=50.0,
        regime_label="neutral",
        conflict_reasons=(),
        size_multiplier=1.0,
        explanation="tier=skip",
    )

    holdings = [
        {"pdno": "111111", "evlu_pfls_rt": "5.0"},
        {"pdno": "222222", "evlu_pfls_rt": "-1.0"},
    ]

    def fake_eval(sym: str, **kwargs):  # type: ignore[no-untyped-def]
        if sym == "111111":
            return decision_ok, {}, "kis_quote"
        return decision_weak, {}, "kis_quote"

    with patch("trade_ops.evaluate_entry_score", side_effect=fake_eval):
        out = scan_held_positions_entry(
            holdings,
            snap=snap,
            vix_f=None,
            risk_off=False,
            vix_spike=False,
            adaptive_out=None,
            use_pipeline=True,
            regime_enum=MarketRegime.NEUTRAL,
            client=None,
            blocked={},
            max_open=2,
        )

    assert len(out) == 2
    assert out[0].symbol == "111111" and out[0].tier == "full"
    captured = capsys.readouterr().out
    assert "[보유진단]" in captured
    assert "111111" in captured
    assert "SKIP_BUY: 슬롯 만석" in captured
