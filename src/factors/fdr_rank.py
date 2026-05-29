"""Optional FDR-based universe sort by RS composite (env-gated from trade_runner)."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from factors.relative_strength import RSWeights, build_rs_row


def rank_universe_fdr(
    symbols: list[str],
    *,
    bench: str = "KS11",
    sector_index_by_symbol: dict[str, str] | None = None,
    calendar_days: int = 400,
    weights: RSWeights | None = None,
) -> tuple[list[str], pd.DataFrame]:
    """
    Returns (symbols_sorted_worst_to_best_fallback_stable, detail_df).
    Missing data symbols go to the end (original order).
    """
    try:
        import FinanceDataReader as fdr  # type: ignore[import-untyped]
    except ImportError:
        return symbols, pd.DataFrame()

    end = datetime.now()
    start = end - timedelta(days=calendar_days)
    d0, d1 = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
    try:
        bdf = fdr.DataReader(bench, d0, d1)
        bench_s = bdf["Close"].astype(float)
    except Exception:
        return symbols, pd.DataFrame()

    w = weights or RSWeights()
    rows: list[dict[str, Any]] = []
    sec_cache: dict[str, pd.Series] = {}
    for sym in symbols:
        try:
            sdf = fdr.DataReader(sym, d0, d1)
            st = sdf["Close"].astype(float)
        except Exception:
            rows.append({"symbol": sym, "composite_raw": float("nan")})
            continue
        sec_s: pd.Series | None = None
        if sector_index_by_symbol and sym in sector_index_by_symbol:
            code = sector_index_by_symbol[sym]
            if code not in sec_cache:
                try:
                    sec_df = fdr.DataReader(code, d0, d1)
                    sec_cache[code] = sec_df["Close"].astype(float)
                except Exception:
                    sec_cache[code] = pd.Series(dtype=float)
            sec_s = sec_cache.get(code)
            if sec_s is not None and sec_s.empty:
                sec_s = None
        row = build_rs_row(st, bench_s, sec_s, weights=w)
        cr = row.get("composite_raw")
        rows.append({"symbol": sym, "composite_raw": cr if cr is not None else float("nan")})

    detail = pd.DataFrame(rows)
    if detail.empty:
        return symbols, detail
    from factors.ranking_engine import rank_from_composite_table

    detail = rank_from_composite_table(detail)
    detail = detail.sort_values("composite_raw", ascending=False, na_position="last")
    ordered = detail["symbol"].tolist()
    tail = [s for s in symbols if s not in ordered]
    return ordered + tail, detail
