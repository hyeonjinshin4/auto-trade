"""trade_journal.csv → 대시보드 CSV보내기 형식 (FIFO·수수료 반영)."""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from dashboard_config import KST, journal_path, now_kst
from journal_fifo import extract_journal_price, infer_journal_action

COMMISSION_ONEWAY = 0.00147

_EXPORT_HEADER = (
    "date,symbol,action,qty,price,amount,pnl_krw,pnl_pct,commission,reason\n"
)


@dataclass
class JournalRow:
    ts: str
    date: str
    symbol: str
    qty: int
    price: float
    action: str
    reason: str
    profit_pct_hint: float | None


def _infer_action(reason: str) -> str:
    journal = infer_journal_action(reason)
    if journal == "skip":
        return "skip"
    if journal == "sell":
        return "sell"
    r = reason or ""
    if re.search(r"기준가=\d+", r) and re.search(r"tier=|엔진|TOPUP|PICK", r):
        return "buy"
    if re.search(
        r"\[매도\]|take_profit|hard_stop|soft_stop|trail_stop|time_stop|ta_sell",
        r,
        re.I,
    ):
        return "sell"
    if journal == "buy":
        return "buy"
    return "unknown"


def _extract_profit_pct_hint(reason: str) -> float | None:
    m = re.search(r"([+-]?\d+(?:\.\d+)?)\s*%", reason or "")
    return float(m.group(1)) if m else None


def _parse_ts(ts: str) -> datetime:
    s = (ts or "").strip()
    if not s:
        return now_kst()
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return now_kst()
    if dt.tzinfo is None:
        return dt.replace(tzinfo=KST)
    return dt.astimezone(KST)


def _kst_date_key(dt: datetime) -> str:
    return dt.astimezone(KST).strftime("%Y-%m-%d")


def _leg_commission(qty: int, price: float) -> float:
    return qty * price * COMMISSION_ONEWAY


def _round_trip_commission(qty: int, buy_px: float, sell_px: float) -> float:
    return _leg_commission(qty, buy_px) + _leg_commission(qty, sell_px)


def load_journal_rows(path: Path | None = None) -> list[JournalRow]:
    jp = path or journal_path()
    if not jp.is_file():
        raise FileNotFoundError(f"저널 없음: {jp}")

    out: list[JournalRow] = []
    with jp.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            reason = row.get("reason") or ""
            action = _infer_action(reason)
            if action == "skip":
                continue
            if action not in {"buy", "sell"}:
                continue
            try:
                qty = int(row.get("qty") or 0)
            except ValueError:
                continue
            sym = (row.get("symbol") or "").strip()
            if not sym or qty <= 0:
                continue
            ts = row.get("ts") or ""
            dt = _parse_ts(ts)
            price = float(extract_journal_price(reason))
            out.append(
                JournalRow(
                    ts=ts,
                    date=_kst_date_key(dt),
                    symbol=sym,
                    qty=qty,
                    price=price,
                    action=action,
                    reason=reason,
                    profit_pct_hint=_extract_profit_pct_hint(reason),
                )
            )
    out.sort(key=lambda r: r.ts)
    return out


def fifo_table_rows(rows: list[JournalRow]) -> list[dict[str, Any]]:
    """dashboard.html fifoMatch 결과와 동일한 tableRows."""
    lots: dict[str, list[dict[str, Any]]] = {}
    table_rows: list[dict[str, Any]] = []

    for row in rows:
        sym = row.symbol
        if row.action == "buy":
            px = row.price
            if px <= 0:
                continue
            comm = _leg_commission(row.qty, px)
            lots.setdefault(sym, []).append(
                {"qty": row.qty, "price": px, "date": row.date, "comm_buy": comm}
            )
            table_rows.append(
                {
                    "date": row.date,
                    "symbol": sym,
                    "action": "buy",
                    "qty": row.qty,
                    "price": px,
                    "amount": row.qty * px,
                    "pnl_krw": None,
                    "pnl_pct": None,
                    "commission": comm,
                    "reason": row.reason,
                }
            )
        elif row.action == "sell":
            sell_px = row.price
            remaining = row.qty
            total_pnl = 0.0
            total_cost = 0.0
            matched_qty = 0

            while remaining > 0 and lots.get(sym):
                lot = lots[sym][0]
                take = min(remaining, lot["qty"])
                px = sell_px
                if px <= 0 and row.profit_pct_hint is not None:
                    px = round(lot["price"] * (1 + row.profit_pct_hint / 100))
                if px <= 0:
                    px = lot["price"]

                buy_amt = take * lot["price"]
                sell_amt = take * px
                comm = _round_trip_commission(take, lot["price"], px)
                pnl = sell_amt - buy_amt - comm

                total_pnl += pnl
                total_cost += buy_amt
                matched_qty += take
                remaining -= take
                lot["qty"] -= take
                if lot["qty"] <= 0:
                    lots[sym].pop(0)

            avg_buy = total_cost / matched_qty if matched_qty > 0 else 0.0
            if sell_px > 0:
                display_px = sell_px
            elif matched_qty > 0 and row.profit_pct_hint is not None:
                display_px = round(avg_buy * (1 + row.profit_pct_hint / 100))
            elif matched_qty > 0:
                display_px = round((total_cost + total_pnl) / matched_qty)
            else:
                display_px = 0.0

            comm = (
                _round_trip_commission(matched_qty, avg_buy, display_px)
                if matched_qty > 0
                else 0.0
            )
            table_rows.append(
                {
                    "date": row.date,
                    "symbol": sym,
                    "action": "sell",
                    "qty": row.qty,
                    "price": display_px or row.price,
                    "amount": matched_qty * (display_px or 0),
                    "pnl_krw": total_pnl if matched_qty > 0 else None,
                    "pnl_pct": (total_pnl / total_cost * 100) if total_cost > 0 else row.profit_pct_hint,
                    "commission": comm,
                    "reason": row.reason,
                }
            )

    return table_rows


def trade_export_csv_path(*, as_of: datetime | None = None) -> Path:
    dt = as_of or now_kst()
    from dashboard_config import ROOT

    return ROOT / "reports" / f"trade_export_{dt.strftime('%Y-%m-%d')}.csv"


def format_export_csv(table_rows: list[dict[str, Any]]) -> str:
    lines = [_EXPORT_HEADER.rstrip("\n")]
    for r in table_rows:
        reason = (r.get("reason") or "").replace('"', '""')
        pnl_krw = r.get("pnl_krw")
        pnl_pct = r.get("pnl_pct")
        lines.append(
            ",".join(
                [
                    str(r.get("date", "")),
                    str(r.get("symbol", "")),
                    str(r.get("action", "")),
                    str(r.get("qty", "")),
                    str(int(r["price"])) if r.get("price") else "0",
                    str(int(r["amount"])) if r.get("amount") else "",
                    "" if pnl_krw is None else str(int(round(pnl_krw))),
                    "" if pnl_pct is None else f"{float(pnl_pct):.4f}".rstrip("0").rstrip("."),
                    f"{float(r.get('commission') or 0):.2f}",
                    f'"{reason}"',
                ]
            )
        )
    return "\n".join(lines) + "\n"


def build_trade_export_csv(
    *,
    journal: Path | None = None,
    output_path: Path | None = None,
) -> Path:
    rows = load_journal_rows(journal)
    table = fifo_table_rows(rows)
    out = output_path or trade_export_csv_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\ufeff" + format_export_csv(table), encoding="utf-8")
    return out
