#!/usr/bin/env python3
"""장 마감 대시보드 → reports/dashboard_eod.html (더블클릭용)"""
from __future__ import annotations

import sys

from _bootstrap import setup

setup()

from eod_artifacts import build_eod_artifacts


def main() -> int:
    try:
        paths = build_eod_artifacts()
        out = paths["html"]
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"OK: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
