"""KIS 체결안내 텔레그램 포맷."""
from __future__ import annotations

from reporting import format_kis_fill_telegram, mask_account_display


def test_mask_account_display() -> None:
    assert mask_account_display("50123456-01") == "50****56-01"


def test_format_kis_fill_telegram_buy() -> None:
    fills = [
        {
            "ODNO": "18240200",
            "PDNO": "138930",
            "PRDT_NAME": "BNK금융지주",
            "SLL_BUY_DVSN_CD": "02",
            "ORD_QTY": "1",
            "TOT_CCLD_QTY": "1",
            "AVG_PRVS": "17130",
            "ORD_TMD": "102600",
        }
    ]
    msg = format_kis_fill_telegram(
        fills,
        odno="18240200",
        side="buy",
        account_no="46567860-01",
        account_name="신현진",
    )
    assert "[한국투자증권 체결안내]10:26" in msg
    assert "*매매구분:현금매수체결" in msg
    assert "*종목명:BNK금융지주(138930)" in msg
    assert "*체결단가:17,130원" in msg
    assert "*주문번호:18240200" in msg
    assert "46****60-01" in msg


def test_format_kis_fill_rejects_unfilled_hint() -> None:
    """체결 수량 0이면 hint로 가짜 체결안내를 만들지 않는다."""
    msg = format_kis_fill_telegram(
        [{"ODNO": "99", "ORD_QTY": "0", "TOT_CCLD_QTY": "0"}],
        odno="99",
        side="buy",
        symbol="011200",
        stock_name="HMM",
        order_qty=1,
        fill_price_hint=19730.0,
        trade_reason="[엔진] tier=half adj=60.0",
    )
    assert "체결 확인 실패" in msg
    assert "한국투자증권 체결안내" not in msg
