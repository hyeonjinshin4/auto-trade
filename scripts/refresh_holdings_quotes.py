#!/usr/bin/env python3
"""저널 보유 종목 시세 → logs/holdings_quotes.json"""
from __future__ import annotations

import sys

from _bootstrap import setup

setup()

from dashboard_config import prefer_kis_quotes
from holdings_quotes import sync_holdings_quotes


def main() -> int:
    meta = sync_holdings_quotes(prefer_kis=prefer_kis_quotes())
    n = len((meta["quotes_payload"].get("quotes") or {}))
    print(f"OK: {meta['quotes_path']} · 보유 {len(meta['held_symbols'])}종 · 시세 {n}종")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
