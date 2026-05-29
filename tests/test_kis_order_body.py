"""KIS 현금주문 body/TR_ID (네트워크 없음)."""
from __future__ import annotations

import os
from unittest.mock import patch

from kis_client import KISClient


def _client_stub() -> KISClient:
    with patch.object(KISClient, "__init__", lambda self: None):
        c = KISClient()
    c._cano = "12345678"
    c._acnt_prdt_cd = "01"
    c.kis_env = "prod"
    return c


def test_order_body_includes_krx_exchange() -> None:
    c = _client_stub()
    body = c._order_cash_body(
        symbol="11200",
        qty=1,
        side="buy",
        order_dvsn="01",
        price=0,
    )
    assert body["PDNO"] == "011200"
    assert body["EXCG_ID_DVSN_CD"] == "KRX"
    assert body["ORD_DVSN"] == "01"
    assert body["ORD_UNPR"] == "0"


def test_order_tr_id_modern_buy() -> None:
    c = _client_stub()
    with patch.dict(os.environ, {"KIS_ORDER_LEGACY_TR_ID": ""}, clear=False):
        assert c._order_tr_id("buy") == "TTTC0012U"
        assert c._order_tr_id("sell") == "TTTC0011U"
