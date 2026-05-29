"""trade_journal.csv FIFO 파싱 (대시보드·시세 공용)."""
from __future__ import annotations

import csv
import re
from pathlib import Path

_ACTION_SELL = re.compile(r"\[매도(?!주문)\]|\[매도체결\]")


def infer_journal_action(reason: str) -> str:
    r = reason or ""
    if re.search(r"\[매도주문", r) or re.search(r"\[매수주문", r):
        return "skip"
    return "sell" if _ACTION_SELL.search(r) else "buy"


def extract_journal_price(reason: str) -> int:
    m = re.search(r"기준가=(\d+)", reason or "")
    return int(m.group(1)) if m else 0


def fifo_held_symbols(journal_path: Path) -> list[str]:
    """FIFO 잔여 보유 종목코드 (정렬)."""
    if not journal_path.is_file():
        return []
    lots: dict[str, list[list[int]]] = {}
    with journal_path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    rows.sort(key=lambda r: r.get("ts", ""))
    for row in rows:
        sym = (row.get("symbol") or "").strip()
        if not sym:
            continue
        try:
            qty = int(row.get("qty") or 0)
        except ValueError:
            continue
        reason = row.get("reason") or ""
        action = infer_journal_action(reason)
        if action == "skip":
            continue
        if action == "buy":
            px = extract_journal_price(reason)
            if px <= 0:
                continue
            lots.setdefault(sym, []).append([qty, px])
        else:
            rem = qty
            while rem > 0 and lots.get(sym):
                take = min(rem, lots[sym][0][0])
                lots[sym][0][0] -= take
                rem -= take
                if lots[sym][0][0] <= 0:
                    lots[sym].pop(0)
    return sorted(s for s, arr in lots.items() if arr and sum(x[0] for x in arr) > 0)
