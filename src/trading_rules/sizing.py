from __future__ import annotations

from .engine_config import VolTargetingParams


def vix_size_multiplier(vix: float | None, p: VolTargetingParams) -> float:
    if vix is None:
        return 1.0
    if vix < p.vix_soft_above:
        return p.scale_below_soft
    if vix < p.vix_hard_above:
        return p.scale_between
    return p.scale_above_hard


def stock_vol_multiplier(is_high_realized_vol: bool, p: VolTargetingParams) -> float:
    return p.high_stock_vol_scale if is_high_realized_vol else 1.0


def combined_size_multiplier(
    vix: float | None,
    is_high_stock_vol: bool,
    p: VolTargetingParams,
) -> float:
    return vix_size_multiplier(vix, p) * stock_vol_multiplier(is_high_stock_vol, p)
