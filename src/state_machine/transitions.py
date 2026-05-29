"""Allowed transitions (deterministic graph)."""
from __future__ import annotations

from typing import FrozenSet

from state_machine.states import PositionState

_ALLOWED: frozenset[tuple[PositionState, PositionState]] = frozenset(
    {
        (PositionState.SCAN, PositionState.ENTRY),
        (PositionState.ENTRY, PositionState.HOLD),
        (PositionState.ENTRY, PositionState.SCALE_IN),
        (PositionState.SCALE_IN, PositionState.HOLD),
        (PositionState.HOLD, PositionState.PARTIAL_EXIT),
        (PositionState.HOLD, PositionState.SCALE_OUT),
        (PositionState.HOLD, PositionState.EXIT),
        (PositionState.HOLD, PositionState.COOLDOWN),
        (PositionState.PARTIAL_EXIT, PositionState.HOLD),
        (PositionState.PARTIAL_EXIT, PositionState.EXIT),
        (PositionState.SCALE_OUT, PositionState.HOLD),
        (PositionState.SCALE_OUT, PositionState.EXIT),
        (PositionState.SCALE_IN, PositionState.EXIT),
        (PositionState.EXIT, PositionState.COOLDOWN),
        (PositionState.EXIT, PositionState.SCAN),
        (PositionState.COOLDOWN, PositionState.SCAN),
        (PositionState.SCAN, PositionState.SCAN),
        (PositionState.HOLD, PositionState.HOLD),
        (PositionState.COOLDOWN, PositionState.COOLDOWN),
    }
)


def allowed_transitions() -> FrozenSet[tuple[PositionState, PositionState]]:
    return _ALLOWED
