"""Append-only in-memory event log (serializable)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class StateEvent:
    ts: str
    symbol: str
    from_state: str
    to_state: str
    reason: str
    meta: dict[str, Any] = field(default_factory=dict)


class PositionEventLog:
    def __init__(self) -> None:
        self._events: list[StateEvent] = []

    def append(
        self,
        *,
        symbol: str,
        from_state: str,
        to_state: str,
        reason: str,
        meta: dict[str, Any] | None = None,
        ts: datetime | None = None,
    ) -> None:
        t = ts or datetime.now(timezone.utc)
        self._events.append(
            StateEvent(
                ts=t.isoformat(),
                symbol=symbol,
                from_state=from_state,
                to_state=to_state,
                reason=reason,
                meta=dict(meta or {}),
            )
        )

    def to_list(self) -> list[dict[str, Any]]:
        return [asdict(e) for e in self._events]

    @classmethod
    def from_list(cls, rows: list[dict[str, Any]]) -> PositionEventLog:
        lg = cls()
        for r in rows:
            lg._events.append(
                StateEvent(
                    ts=str(r["ts"]),
                    symbol=str(r["symbol"]),
                    from_state=str(r["from_state"]),
                    to_state=str(r["to_state"]),
                    reason=str(r["reason"]),
                    meta=dict(r.get("meta") or {}),
                )
            )
        return lg
