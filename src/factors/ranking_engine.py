"""Cross-sectional ranking from RS composites (pandas)."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from factors.relative_strength import cross_sectional_percentile_rank


@dataclass(frozen=True)
class RSRankRow:
    symbol: str
    rs_percentile: float
    composite_momentum: float
    sector_rank: int
    market_rank: int


def rank_from_composite_table(df: pd.DataFrame) -> pd.DataFrame:
    """
    df columns: symbol, composite_raw [, sector_bucket].
    Adds rs_percentile, market_rank; sector_rank within sector_bucket if present.
    """
    out = df.copy()
    out["rs_percentile"] = cross_sectional_percentile_rank(out["composite_raw"])
    out["market_rank"] = out["composite_raw"].rank(ascending=False, method="first").astype(int)
    if "sector_bucket" in out.columns:
        out["sector_rank"] = out.groupby("sector_bucket")["composite_raw"].rank(
            ascending=False, method="first"
        ).astype(int)
    else:
        out["sector_rank"] = out["market_rank"]
    return out


def sort_symbols_by_rs(
    scores: dict[str, float],
    *,
    reverse: bool = True,
) -> list[str]:
    """scores maps symbol → composite (higher better)."""
    items = [(s, v) for s, v in scores.items() if v == v]  # noqa: PLR1714 — filter NaN
    items.sort(key=lambda x: x[1], reverse=reverse)
    return [s for s, _ in items]
