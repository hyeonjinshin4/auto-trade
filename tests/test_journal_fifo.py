"""journal_fifo 단위 테스트."""
from __future__ import annotations

from pathlib import Path

from journal_fifo import extract_journal_price, fifo_held_symbols, infer_journal_action


def test_infer_action() -> None:
    assert infer_journal_action("[매도]take_profit") == "sell"
    assert infer_journal_action("tier=half 기준가=100") == "buy"
    assert infer_journal_action("[매도주문·미체결]soft_stop") == "skip"
    assert infer_journal_action("[매수주문·미체결]tier=half") == "skip"


def test_extract_price() -> None:
    assert extract_journal_price("기준가=19698(kis_quote)") == 19698


def test_fifo_held_symbols(tmp_path: Path) -> None:
    p = tmp_path / "j.csv"
    p.write_text(
        "ts,symbol,qty,odno,reason,rt_cd,msg\n"
        "2026-05-18T10:00:00,011200,1,o1,tier=half 기준가=100,0,ok\n"
        "2026-05-18T11:00:00,011200,1,o2,tier=half 기준가=110,0,ok\n"
        "2026-05-19T12:00:00,011200,2,o3,[매도]tp +10%,0,ok\n"
        "2026-05-19T13:00:00,005930,2,o4,기준가=50000,0,ok\n",
        encoding="utf-8",
    )
    held = fifo_held_symbols(p)
    assert held == ["005930"]
    assert fifo_held_symbols(tmp_path / "missing.csv") == []


def test_fifo_ignores_unfilled_order_rows(tmp_path: Path) -> None:
    p = tmp_path / "j.csv"
    p.write_text(
        "ts,symbol,qty,odno,reason,rt_cd,msg\n"
        "2026-05-28T10:00:00,090460,1,o1,tier=half 기준가=30000,0,ok\n"
        "2026-05-28T12:10:00,090460,1,o2,[매도주문·미체결]soft_stop,0,ok\n",
        encoding="utf-8",
    )
    assert fifo_held_symbols(p) == ["090460"]
