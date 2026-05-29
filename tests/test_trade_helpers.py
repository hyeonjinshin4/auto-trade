"""trade_ops (가격·상태·매도사유) 단위 검증."""
from __future__ import annotations

from unittest.mock import MagicMock

from trade_ops import (
    block_symbol_reentry,
    get_entry_reference_price,
    is_symbol_blocked,
    load_blocked_symbols,
    resolve_order_price,
    round_krx_limit_price,
    sell_reasons,
    trading_order_type,
)
from trading_rules.loader import get_engine_config, get_rulebook


def test_resolve_order_price_market() -> None:
    px, dvsn = resolve_order_price("market", reference_price=50000.0)
    assert px == 0 and dvsn == "01"


def test_resolve_order_price_limit_rounds_to_krx_tick() -> None:
    # 1만~5만원 구간 호가 50원 — 21306 → 매수 지정가 21300
    px, dvsn = resolve_order_price("limit", reference_price=21306.0, side="buy")
    assert px == 21300 and dvsn == "00"
    assert round_krx_limit_price(21306.0, side="buy") == 21300
    px2, _ = resolve_order_price("limit", reference_price=50123.4, side="buy")
    assert px2 == 50100  # 5만~10만 구간 호가 100원


def test_get_entry_reference_price_fallback_last_close(monkeypatch) -> None:
    monkeypatch.setenv("TRADING_ENTRY_SLIPPAGE_BUFFER", "0")
    monkeypatch.delenv("USE_KIS_QUOTE_FOR_SIZING", raising=False)
    px, src = get_entry_reference_price("005930", {"last_close": 70000}, client=None)
    assert px == 70000.0 and src == "last_close"


def test_get_entry_reference_price_kis_quote(monkeypatch) -> None:
    monkeypatch.setenv("TRADING_ENTRY_SLIPPAGE_BUFFER", "0")
    monkeypatch.setenv("USE_KIS_QUOTE_FOR_SIZING", "true")
    client = MagicMock()
    client.inquire_price.return_value = {"stck_prpr": "71000"}
    px, src = get_entry_reference_price("005930", {"last_close": 70000}, client=client)
    assert px == 71000.0 and src == "kis_quote"


def test_sell_reasons_trailing_from_highest() -> None:
    rb = get_rulebook()
    ec = get_engine_config()
    row: dict = {"evlu_pfls_rt": "5"}
    pos = {"entry_px": 10000.0, "highest_px": 20000.0, "entry_date": "20260101"}
    reasons = sell_reasons(
        row,
        rb,
        ec,
        {"last_close": 11600.0, "atr_14": 100.0, "ma_slow": 10000.0},
        position={**pos, "tp1_done": True, "tp2_done": True},
        current_price=11600.0,
    )
    assert any("trail_stop" in r or "trailing_stop" in r for r in reasons)


def test_reentry_block_symbol(tmp_path, monkeypatch) -> None:
    p = tmp_path / "blocked.json"
    monkeypatch.setenv("BLOCKED_SYMBOLS_PATH", str(p))
    block_symbol_reentry("123456", days=2)
    blocks = load_blocked_symbols()
    assert is_symbol_blocked("123456", blocks)
