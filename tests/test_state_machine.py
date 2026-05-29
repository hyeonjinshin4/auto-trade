from state_machine import (
    PositionState,
    PositionStateMachine,
    TransitionContext,
    is_valid_transition,
)


def test_invalid_edge():
    ok, msg = is_valid_transition(PositionState.SCAN, PositionState.HOLD)
    assert ok is False


def test_cooldown_scan_blocked():
    ok, _ = is_valid_transition(
        PositionState.COOLDOWN,
        PositionState.SCAN,
        ctx=TransitionContext(cooldown_remaining=2),
    )
    assert ok is False


def test_machine_log_serializable():
    m = PositionStateMachine()
    assert m.transition("005930", PositionState.ENTRY, reason="open")[0] is True
    assert m.transition("005930", PositionState.HOLD, reason="fill")[0] is True
    d = m.to_dict()
    assert "005930" in d
    assert len(m.log.to_list()) == 2
