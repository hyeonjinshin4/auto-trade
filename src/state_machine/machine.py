"""Position state machine: deterministic, serializable shell for multi-strategy."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from state_machine.event_log import PositionEventLog
from state_machine.states import PositionState
from state_machine.validator import TransitionContext, is_valid_transition


@dataclass
class PositionLifecycleState:
    symbol: str
    state: PositionState = PositionState.SCAN
    cooldown_days_left: int = 0
    partial_exit_count: int = 0
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["state"] = self.state.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PositionLifecycleState:
        return cls(
            symbol=str(d["symbol"]),
            state=PositionState(str(d.get("state", "scan"))),
            cooldown_days_left=int(d.get("cooldown_days_left", 0)),
            partial_exit_count=int(d.get("partial_exit_count", 0)),
            meta=dict(d.get("meta") or {}),
        )


class PositionStateMachine:
    """
    Minimal orchestrator: validates + logs. Strategy injects actions elsewhere.
    """

    def __init__(self, *, log: PositionEventLog | None = None) -> None:
        self._positions: dict[str, PositionLifecycleState] = {}
        self._log = log or PositionEventLog()

    @property
    def log(self) -> PositionEventLog:
        return self._log

    def get(self, symbol: str) -> PositionLifecycleState:
        if symbol not in self._positions:
            self._positions[symbol] = PositionLifecycleState(symbol=symbol)
        return self._positions[symbol]

    def transition(
        self,
        symbol: str,
        dst: PositionState,
        *,
        reason: str,
        ctx: TransitionContext | None = None,
        meta: dict[str, Any] | None = None,
    ) -> tuple[bool, str]:
        cur = self.get(symbol)
        c0 = ctx or TransitionContext()
        merged = TransitionContext(
            loss_breach=c0.loss_breach,
            cooldown_remaining=cur.cooldown_days_left
            if cur.state == PositionState.COOLDOWN
            else c0.cooldown_remaining,
            partial_fill_ratio=c0.partial_fill_ratio,
        )
        ok, msg = is_valid_transition(cur.state, dst, ctx=merged)
        if not ok:
            return False, msg
        prev = cur.state
        cur.state = dst
        if dst == PositionState.SCAN:
            cur.cooldown_days_left = 0
        if dst == PositionState.COOLDOWN:
            cur.cooldown_days_left = max(cur.cooldown_days_left, int((meta or {}).get("cooldown_days", 1)))
        if dst == PositionState.PARTIAL_EXIT:
            cur.partial_exit_count += 1
        if meta:
            cur.meta.update(meta)
        self._log.append(
            symbol=symbol,
            from_state=prev.value,
            to_state=dst.value,
            reason=reason,
            meta=meta,
        )
        return True, "ok"

    def tick_cooldown(self, symbol: str) -> None:
        st = self.get(symbol)
        if st.state != PositionState.COOLDOWN:
            return
        if st.cooldown_days_left > 0:
            st.cooldown_days_left -= 1

    def to_dict(self) -> dict[str, Any]:
        return {k: v.to_dict() for k, v in self._positions.items()}

    def load_dict(self, d: dict[str, Any]) -> None:
        self._positions = {k: PositionLifecycleState.from_dict(v) for k, v in d.items()}
