from __future__ import annotations

from enum import Enum
from typing import FrozenSet


class TradingState(str, Enum):
    """주문 파이프라인 상태 (경량). 기관형 라이프사이클은 `state_machine.PositionStateMachine` 참고."""

    SCAN = "scan"
    CANDIDATE = "candidate"
    PENDING_BREAKOUT = "pending_breakout"
    ENTRY = "entry"
    SCALE_IN = "scale_in"
    HOLD = "hold"
    REDUCE = "reduce"
    EXIT = "exit"
    COOLDOWN = "cooldown"


# (from_state, to_state) 허용 엣지
_ALLOWED_TRANSITIONS: frozenset[tuple[TradingState, TradingState]] = frozenset(
    {
        (TradingState.SCAN, TradingState.CANDIDATE),
        (TradingState.CANDIDATE, TradingState.PENDING_BREAKOUT),
        (TradingState.PENDING_BREAKOUT, TradingState.ENTRY),
        (TradingState.CANDIDATE, TradingState.ENTRY),
        (TradingState.ENTRY, TradingState.SCALE_IN),
        (TradingState.ENTRY, TradingState.HOLD),
        (TradingState.SCALE_IN, TradingState.HOLD),
        (TradingState.HOLD, TradingState.REDUCE),
        (TradingState.HOLD, TradingState.EXIT),
        (TradingState.SCALE_IN, TradingState.REDUCE),
        (TradingState.REDUCE, TradingState.EXIT),
        (TradingState.REDUCE, TradingState.HOLD),
        (TradingState.EXIT, TradingState.COOLDOWN),
        (TradingState.EXIT, TradingState.SCAN),
        (TradingState.COOLDOWN, TradingState.SCAN),
        (TradingState.SCAN, TradingState.SCAN),
        (TradingState.CANDIDATE, TradingState.SCAN),
        (TradingState.PENDING_BREAKOUT, TradingState.SCAN),
    }
)


# 상태별 허용되는 “액션 이름” (오케스트레이터에서 매핑)
_STATE_ACTIONS: dict[TradingState, FrozenSet[str]] = {
    TradingState.SCAN: frozenset({"scan_universe", "promote_candidate", "noop"}),
    TradingState.CANDIDATE: frozenset({"watch_setup", "drop", "force_pending_breakout"}),
    TradingState.PENDING_BREAKOUT: frozenset({"confirm_breakout", "invalidate", "enter_small"}),
    TradingState.ENTRY: frozenset({"place_entry", "abort"}),
    TradingState.SCALE_IN: frozenset({"add_size", "stop_scaling", "reduce"}),
    TradingState.HOLD: frozenset({"trail", "take_partial", "full_exit_signal"}),
    TradingState.REDUCE: frozenset({"trim", "resume_hold", "exit_rest"}),
    TradingState.EXIT: frozenset({"ack_exit", "go_cooldown", "go_scan"}),
    TradingState.COOLDOWN: frozenset({"tick_cooldown"}),
}


def is_transition_allowed(from_state: TradingState, to_state: TradingState) -> bool:
    return (from_state, to_state) in _ALLOWED_TRANSITIONS


def is_action_allowed(state: TradingState, action: str) -> bool:
    return action in _STATE_ACTIONS.get(state, frozenset())


def can_open_new_trade(state: TradingState) -> bool:
    """COOLDOWN 동안 신규 진입 금지."""
    return state != TradingState.COOLDOWN


def allowed_actions(state: TradingState) -> FrozenSet[str]:
    return _STATE_ACTIONS.get(state, frozenset())
