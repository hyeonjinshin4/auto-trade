"""통합 진입 — 엔진 + TA 가점 합산."""
from __future__ import annotations

from unittest.mock import patch

from trading_rules.models import MarketRegimeSnapshot
from trading_rules.scoring import SignalComponents
from trading_rules.pipeline import EntryDecision

from signal_scanner.unified import decide_entry_unified


def test_unified_additive_ta_points(monkeypatch) -> None:
    monkeypatch.setenv("USE_TA_SIGNALS", "true")
    monkeypatch.setenv("TRADING_TA_ENTRY_ONLY", "false")
    monkeypatch.setenv("TRADING_TA_POINT_MULT", "1.0")

    engine = EntryDecision(
        tier="half",
        position_fraction=0.5,
        signal_raw=60.0,
        signal_adjusted=60.0,
        regime_score=50.0,
        regime_label="neutral",
        conflict_reasons=(),
        size_multiplier=1.0,
        explanation="engine",
    )
    from signal_scanner.trading import TaBuyResult
    from signal_scanner.ta_scoring import TaScoreDetail

    detail = TaScoreDetail(
        score=28.0,
        raw_points=28,
        hit_count=2,
        trend_ok=True,
        breakdown="rsi_oversold+14, macd_bull+14",
        labels="RSI; MACD",
        blocked_reason=None,
    )
    from signal_scanner.ta_scoring import TaScoreDetail as TSD

    sell_pen = TSD(28.0, 28, 2, True, "rsi_overbought+14, macd_bear+14", "RSI; MACD", None)
    ta_ok = TaBuyResult(
        True, (), "half", 28.0, "ok", detail, sell_penalty=28.0, sell_penalty_detail=sell_pen
    )

    snap = MarketRegimeSnapshot()
    comp = SignalComponents(50, 50, 50, 50, 50)

    with patch("signal_scanner.unified.decide_entry", return_value=engine):
        with patch("signal_scanner.unified.evaluate_ta_buy", return_value=ta_ok):
            d = decide_entry_unified(
                snap,
                comp,
                symbol="005930",
                vix_level=20.0,
                risk_off=False,
                vix_spike=False,
                use_engine=True,
            )
    assert d.signal_adjusted == 60.0  # 60 + 28 - 28
    assert "TA28.0" in d.explanation or "TA28" in d.explanation


def test_unified_log_shows_ta_blocked_not_raw(monkeypatch) -> None:
    """추세필터 시 TA 가점은 합산 0, 로그는 미반영 표시."""
    monkeypatch.setenv("USE_TA_SIGNALS", "true")
    engine = EntryDecision(
        tier="half",
        position_fraction=0.5,
        signal_raw=55.9,
        signal_adjusted=55.9,
        regime_score=50.0,
        regime_label="neutral",
        conflict_reasons=(),
        size_multiplier=1.0,
        explanation="engine",
    )
    from signal_scanner.trading import TaBuyResult
    from signal_scanner.ta_scoring import TaScoreDetail

    detail = TaScoreDetail(
        score=0.0,
        raw_points=14,
        hit_count=1,
        trend_ok=False,
        breakdown="rsi_oversold+14",
        labels="RSI",
        blocked_reason="추세필터(종가<20일선)",
    )
    ta_ok = TaBuyResult(
        False, (), "skip", 0.0, "추세필터", detail, sell_penalty=0.0, sell_penalty_detail=None
    )
    snap = MarketRegimeSnapshot()
    comp = SignalComponents(50, 50, 50, 50, 50)
    with patch("signal_scanner.unified.decide_entry", return_value=engine):
        with patch("signal_scanner.unified.evaluate_ta_buy", return_value=ta_ok):
            d = decide_entry_unified(
                snap,
                comp,
                symbol="005930",
                vix_level=20.0,
                risk_off=False,
                vix_spike=False,
                use_engine=True,
            )
    assert d.signal_adjusted == 55.9
    assert "TA적용0" in d.explanation
    assert "후보14" in d.explanation


def test_unified_sell_penalty_only(monkeypatch) -> None:
    monkeypatch.setenv("USE_TA_SIGNALS", "true")
    engine = EntryDecision(
        tier="full",
        position_fraction=1.0,
        signal_raw=80.0,
        signal_adjusted=80.0,
        regime_score=50.0,
        regime_label="neutral",
        conflict_reasons=(),
        size_multiplier=1.0,
        explanation="engine",
    )
    from signal_scanner.trading import TaBuyResult
    from signal_scanner.ta_scoring import TaScoreDetail

    sell_pen = TaScoreDetail(42.0, 42, 3, True, "a+14,b+14,c+14", "", None)
    ta_ok = TaBuyResult(
        False, (), "skip", 0.0, "no buy", None, sell_penalty=42.0, sell_penalty_detail=sell_pen
    )
    snap = MarketRegimeSnapshot()
    comp = SignalComponents(50, 50, 50, 50, 50)
    with patch("signal_scanner.unified.decide_entry", return_value=engine):
        with patch("signal_scanner.unified.evaluate_ta_buy", return_value=ta_ok):
            d = decide_entry_unified(
                snap,
                comp,
                symbol="005930",
                vix_level=20.0,
                risk_off=False,
                vix_spike=False,
                use_engine=True,
            )
    assert d.signal_adjusted == 38.0  # 80 - 42
