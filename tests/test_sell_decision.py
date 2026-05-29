"""매도 판단 evaluate_sell."""
from __future__ import annotations

from trading_rules.models import SellRuleParams
from trading_rules.sell_decision import evaluate_sell, time_stop_days_for_symbol


def _sell() -> SellRuleParams:
    return SellRuleParams()


def test_hard_stop_full() -> None:
    d = evaluate_sell(
        current_price=90.0,
        entry_price=100.0,
        highest_price=100.0,
        holding_days=1,
        atr_value=None,
        price_vs_ma20=0.95,
        ta_signal_count=0,
        ta_signal_score=0.0,
        tp1_done=False,
        tp2_done=False,
        sell=_sell(),
    )
    assert d.action == "hard_stop"
    assert d.sell_ratio == 1.0


def test_tp1_partial() -> None:
    d = evaluate_sell(
        current_price=115.0,
        entry_price=100.0,
        highest_price=115.0,
        holding_days=3,
        atr_value=None,
        price_vs_ma20=1.05,
        ta_signal_count=0,
        ta_signal_score=0.0,
        tp1_done=False,
        tp2_done=False,
        sell=_sell(),
    )
    assert d.action == "take_profit_1"
    assert d.sell_ratio == 0.40


def test_trail_stop() -> None:
    s = SellRuleParams(trailing_activate_pct=0.12, trailing_width_stage1=0.13)
    d = evaluate_sell(
        current_price=11600.0,
        entry_price=10000.0,
        highest_price=20000.0,
        holding_days=5,
        atr_value=None,
        price_vs_ma20=1.1,
        ta_signal_count=0,
        ta_signal_score=0.0,
        tp1_done=True,
        tp2_done=True,
        sell=s,
    )
    assert d.action == "trail_stop"
    assert d.sell_ratio == 1.0


def test_time_stop_hash_spread() -> None:
    s = SellRuleParams(time_stop_days=15, time_stop_hash_spread=4)
    assert time_stop_days_for_symbol("005930", s) == 15 + (5930 % 4)
    assert time_stop_days_for_symbol(None, s) == 15


def test_early_time_stop() -> None:
    s = SellRuleParams(time_stop_early_days=5, time_stop_early_loss_pct=0.05)
    d = evaluate_sell(
        current_price=94.0,
        entry_price=100.0,
        highest_price=100.0,
        holding_days=5,
        atr_value=None,
        price_vs_ma20=0.98,
        ta_signal_count=0,
        ta_signal_score=0.0,
        tp1_done=False,
        tp2_done=False,
        sell=s,
    )
    assert d.action == "early_time_stop"
    assert d.sell_ratio == 1.0


def test_time_stop_uses_symbol_days() -> None:
    s = SellRuleParams(
        time_stop_days=15,
        time_stop_min_pnl=0.01,
        time_stop_hash_spread=4,
        time_stop_early_days=0,
    )
    sym = "005930"
    need = time_stop_days_for_symbol(sym, s)
    d = evaluate_sell(
        current_price=100.5,
        entry_price=100.0,
        highest_price=100.5,
        holding_days=need + 1,
        atr_value=None,
        price_vs_ma20=1.0,
        ta_signal_count=0,
        ta_signal_score=0.0,
        tp1_done=False,
        tp2_done=False,
        sell=s,
        symbol=sym,
    )
    assert d.action == "time_stop"
    assert str(need) in d.reason


def test_effective_trail_atr_favors_higher_stop() -> None:
    s = SellRuleParams(
        trailing_stage3_from=0.45,
        trailing_width_stage3=0.09,
        use_atr_trailing=True,
        atr_trailing_multiplier=2.3,
    )
    stop = s.effective_trail_stop(20000.0, 0.50, atr_value=100.0)
    pct_stop = 20000.0 * (1.0 - 0.09)
    atr_stop = 20000.0 - 100.0 * 2.3
    assert stop == max(pct_stop, atr_stop)
