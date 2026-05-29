#!/usr/bin/env python3
"""KRX 상장 종목코드→한글명 JSON (대시보드 config/stock_names.json)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "config" / "stock_names.json"


def main() -> int:
    try:
        import FinanceDataReader as fdr
    except ImportError:
        print("FinanceDataReader 필요: pip install finance-datareader", file=sys.stderr)
        return 1

    df = fdr.StockListing("KRX")
    out: dict[str, str] = {}
    for _, row in df.iterrows():
        code = str(row.get("Code", "")).strip().zfill(6)
        name = str(row.get("Name", "")).strip()
        if code and name:
            out[code] = name

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(out, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"wrote {OUT} ({len(out)} symbols)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
