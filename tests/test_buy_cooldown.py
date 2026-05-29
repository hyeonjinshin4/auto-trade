"""매수 쿨다운·당일 한도."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from trade_ops import buy_skip_reason, clear_buy_attempt, record_buy_attempt

_KST = timezone(timedelta(hours=9))


def test_buy_skip_daily_limit(monkeypatch: object) -> None:
    monkeypatch.setenv("TRADING_ALLOW_REBUY_AFTER_SELL", "false")
    monkeypatch.setenv("TRADING_BUY_COOLDOWN_MINUTES", "0")
    sym = "005930"
    today = datetime.now(_KST).strftime("%Y%m%d")
    st = {
        sym: {
            "buy_count_date": today,
            "buy_count": 1,
            "last_success_at": datetime.now(_KST).isoformat(timespec="seconds"),
        }
    }
    reason = buy_skip_reason(sym, buy_attempts=st, position_state={})
    assert reason is not None
    assert "당일" in reason


def test_buy_skip_position_state(monkeypatch) -> None:
    monkeypatch.setenv("TRADING_SKIP_BUY_IF_POSITION_STATE", "true")
    pos = {"005930": {"entry_px": 70000.0, "highest_px": 70000.0, "entry_date": "20260101"}}
    reason = buy_skip_reason("005930", buy_attempts={}, position_state=pos)
    assert reason is not None
    assert "포지션" in reason


def test_record_success_sets_cooldown() -> None:
    st: dict = {}
    record_buy_attempt("011200", success=True, state=st)
    assert st["011200"]["buy_count"] == 1


def test_clear_buy_attempt_allows_rebuy() -> None:
    st: dict = {}
    record_buy_attempt("011200", success=True, state=st)
    clear_buy_attempt("011200", st)
    assert "011200" not in st
    assert buy_skip_reason("011200", buy_attempts=st, position_state={}) is None
