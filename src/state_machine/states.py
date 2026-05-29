"""Position lifecycle states (strategy-agnostic)."""
from __future__ import annotations

from enum import Enum


class PositionState(str, Enum):
    SCAN = "scan"
    ENTRY = "entry"
    HOLD = "hold"
    PARTIAL_EXIT = "partial_exit"
    SCALE_IN = "scale_in"
    SCALE_OUT = "scale_out"
    EXIT = "exit"
    COOLDOWN = "cooldown"
