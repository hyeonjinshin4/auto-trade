"""journal_export 단위 테스트."""
from __future__ import annotations

from pathlib import Path

from journal_export import build_trade_export_csv, fifo_table_rows, load_journal_rows


def test_fifo_export_matches_journal(tmp_path: Path) -> None:
    p = tmp_path / "j.csv"
    p.write_text(
        "ts,symbol,qty,odno,reason,rt_cd,msg\n"
        "2026-05-18T10:00:00,011200,1,o1,tier=half 기준가=100,0,ok\n"
        "2026-05-19T12:00:00,011200,1,o2,[매도]take_profit_1 +10.0%,0,ok\n",
        encoding="utf-8",
    )
    rows = load_journal_rows(p)
    table = fifo_table_rows(rows)
    assert len(table) == 2
    assert table[0]["action"] == "buy"
    assert table[1]["action"] == "sell"
    assert table[1]["pnl_krw"] is not None

    out = build_trade_export_csv(journal=p, output_path=tmp_path / "out.csv")
    text = out.read_text(encoding="utf-8-sig")
    assert "date,symbol,action" in text
    assert "011200" in text
