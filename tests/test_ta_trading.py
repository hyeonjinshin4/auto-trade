"""TA 자동매매 판단."""
from __future__ import annotations

from unittest.mock import patch

from signal_scanner.rules import SignalHit
from signal_scanner.trading import TaBuyResult, evaluate_ta_buy, use_ta_signals


def test_use_ta_signals_default_on(monkeypatch) -> None:
    monkeypatch.delenv("USE_TA_SIGNALS", raising=False)
    assert use_ta_signals() is True


def test_evaluate_ta_buy_fail_insufficient(monkeypatch) -> None:
    monkeypatch.setenv("USE_TA_SIGNALS", "true")
    with patch("signal_scanner.trading.evaluate_symbol_signals", return_value=None):
        r = evaluate_ta_buy("005930")
    assert r.ok is False


def test_evaluate_ta_buy_ok(monkeypatch) -> None:
    hits = [
        SignalHit("rsi_oversold", "RSI"),
        SignalHit("macd_bull", "MACD"),
    ]
    today = {"close": 100.0, "ma_slow": 90.0}
    with patch("signal_scanner.trading.evaluate_symbol_signals", return_value=(hits, [], today)):
        with patch("signal_scanner.trading.in_cooldown", return_value=False):
            r = evaluate_ta_buy("005930")
    assert r.ok is True
    assert r.score > 0
    assert r.detail is not None and r.detail.raw_points == 28


def test_single_ta_signal_ok(monkeypatch) -> None:
    hits = [SignalHit("rsi_oversold", "RSI")]
    today = {"close": 100.0, "ma_slow": 90.0}
    with patch("signal_scanner.trading.evaluate_symbol_signals", return_value=(hits, [], today)):
        with patch("signal_scanner.trading.in_cooldown", return_value=False):
            r = evaluate_ta_buy("005930")
    assert r.ok is True
    assert r.score == 14.0
    assert isinstance(r, TaBuyResult)
