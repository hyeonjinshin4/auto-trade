"""Transition validation + cooldown / loss-breach helpers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from state_machine.states import PositionState
from state_machine.transitions import allowed_transitions


@dataclass(frozen=True)
class TransitionContext:
    """Optional guards (caller supplies what strategy needs)."""

    loss_breach: bool = False
    cooldown_remaining: int = 0
    partial_fill_ratio: float | None = None


def is_valid_transition(
    src: PositionState,
    dst: PositionState,
    *,
    ctx: TransitionContext | None = None,
) -> tuple[bool, str]:
    if (src, dst) not in allowed_transitions():
        return False, f"edge_not_allowed:{src.value}->{dst.value}"
    c = ctx or TransitionContext()
    if src == PositionState.COOLDOWN and dst == PositionState.SCAN and c.cooldown_remaining > 0:
        return False, "cooldown_not_elapsed"
    if c.loss_breach and dst not in {
        PositionState.EXIT,
        PositionState.COOLDOWN,
        PositionState.SCAN,
        PositionState.PARTIAL_EXIT,
        PositionState.SCALE_OUT,
    }:
        return False, "loss_breach_guard"
    return True, "ok"


def forced_cooldown_from_loss() -> PositionState:
    return PositionState.COOLDOWN
