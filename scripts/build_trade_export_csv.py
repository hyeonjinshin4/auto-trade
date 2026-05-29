#!/usr/bin/env python3
"""저널 FIFO → reports/trade_export_YYYY-MM-DD.csv"""
from __future__ import annotations

import sys

from _bootstrap import setup

setup()

from journal_export import build_trade_export_csv


def main() -> int:
    try:
        out = build_trade_export_csv()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"OK: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
