"""
한국시간(KST) 기준 당일 주문 건수 추적 — FORCE_DAILY_TRADE(일 1회 이상 주문)용.

- 실매매: KIS 매수·매도 주문 API 성공 시(rt_cd) 카운트.
- 드라이런: 일일 강제 시뮬 분기에서만 카운트(일반 NO_BUY 시뮬은 제외).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from safe_logging import get_safe_logger

_log = get_safe_logger(__name__)

KST = timezone(timedelta(hours=9))


def kst_today_str() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def kst_hour() -> int:
    return datetime.now(KST).hour


def state_path() -> Path:
    raw = (os.getenv("FORCE_DAILY_TRADE_STATE_PATH") or "logs/daily_min_trade_state.json").strip()
    return Path(raw)


@dataclass
class DailyMinTradeState:
    kst_date: str
    order_count: int

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DailyMinTradeState":
        return cls(
            kst_date=str(d.get("kst_date") or ""),
            order_count=int(d.get("order_count") or 0),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"kst_date": self.kst_date, "order_count": self.order_count}


def load_state() -> DailyMinTradeState:
    p = state_path()
    today = kst_today_str()
    if not p.is_file():
        return DailyMinTradeState(kst_date=today, order_count=0)
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        st = DailyMinTradeState.from_dict(d)
        if st.kst_date != today:
            return DailyMinTradeState(kst_date=today, order_count=0)
        return st
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        _log.warning("daily_min_trade: state load failed %s", exc)
        return DailyMinTradeState(kst_date=today, order_count=0)


def save_state(st: DailyMinTradeState) -> None:
    p = state_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(st.to_dict(), ensure_ascii=False, indent=0), encoding="utf-8")
    except OSError as exc:
        _log.warning("daily_min_trade: state save failed %s", exc)


def orders_today() -> int:
    return load_state().order_count


def bump_orders_today(*, reason: str = "") -> None:
    today = kst_today_str()
    st = load_state()
    if st.kst_date != today:
        st = DailyMinTradeState(kst_date=today, order_count=0)
    st = DailyMinTradeState(kst_date=today, order_count=st.order_count + 1)
    save_state(st)
    _log.info(
        "[일일거래카운트] KST=%s 건수=%s reason=%s",
        today,
        st.order_count,
        reason or "-",
    )


def force_daily_trade_enabled() -> bool:
    return str(os.getenv("FORCE_DAILY_TRADE", "")).strip().lower() in {"1", "true", "yes", "y"}


def force_daily_min_orders() -> int:
    raw = (os.getenv("FORCE_DAILY_MIN_ORDERS") or "1").strip()
    try:
        n = int(raw)
    except ValueError:
        n = 1
    return max(1, n)


def force_daily_after_hour_kst() -> int:
    raw = (os.getenv("FORCE_DAILY_TRADE_AFTER_HOUR_KST") or "0").strip()
    try:
        h = int(raw)
    except ValueError:
        h = 0
    return max(0, min(h, 23))


def needs_min_orders_today() -> bool:
    if not force_daily_trade_enabled():
        return False
    return orders_today() < force_daily_min_orders()


def live_force_allowed() -> bool:
    """실계좌에서 일일 강제 매수 허용(위험)."""
    return str(os.getenv("FORCE_DAILY_TRADE_LIVE", "")).strip().lower() in {"1", "true", "yes", "y"}
