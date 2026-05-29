from __future__ import annotations

from pathlib import Path

from daily_min_trade import DailyMinTradeState, force_daily_min_orders, kst_today_str, load_state, save_state


def test_force_daily_min_orders_default() -> None:
    assert force_daily_min_orders() >= 1


def test_daily_state_roundtrip(tmp_path: Path, monkeypatch) -> None:
    p = tmp_path / "st.json"
    monkeypatch.setenv("FORCE_DAILY_TRADE_STATE_PATH", str(p))
    today = kst_today_str()
    save_state(DailyMinTradeState(kst_date=today, order_count=1))
    st2 = load_state()
    assert st2.kst_date == today
    assert st2.order_count == 1
